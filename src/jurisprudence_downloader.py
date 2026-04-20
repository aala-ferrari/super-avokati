"""Download Albanian court decisions (jurisprudence) to local disk.

Why local-first:
  * works offline for citizens with flaky mobile internet;
  * zero runtime dependency on external sites staying up;
  * lets us build a single BM25 index once and serve queries in milliseconds.

Scraper strategy:
  * for each configured Court, fetch the per-year listing page;
  * regex out links to decision files along with their "Vendim Nr: N Date: D"
    labels (this is the only metadata the listing exposes);
  * download each file into data/raw/jurisprudence/{court_code}/{year}/,
    using a canonical filename vend_{NNNN}_{year}.{ext};
  * save a sidecar `_index.json` per court that maps filename → (nr, date, url).
    The parser reads this alongside the raw files to build Decision objects.

Politeness:
  * 0.4 s between requests, capped concurrency = 1, real User-Agent header;
  * idempotent — skip files already on disk with the same size;
  * tenacity retries transient errors (network, 5xx).
"""
from __future__ import annotations

import argparse
import json
import re
import time
from dataclasses import asdict, dataclass
from pathlib import Path

import requests
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from .config import COURTS, JURISPRUDENCE_PATH, Court, court_by_code
from .logging_utils import get_logger

log = get_logger(__name__)

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36 "
    "SuperAvvocato/0.1 (+humanitarian legal assistant)"
)
REQUEST_TIMEOUT = 60
POLITE_DELAY = 0.4  # seconds between requests to the same host
MIN_VALID_FILE_BYTES = 3_000  # short circular letters can be tiny; be lenient

# Matches an anchor like:
#   <a class="link_editor" ... href="URL">Vendim Nr: 42 Date: 29.05.2024</a>
# on the gjykatakushtetuese.gov.al yearly pages. Captures (url, nr, date).
# We keep it permissive on attribute order and whitespace.
GJK_LINK_RE = re.compile(
    r'<a[^>]*href="([^"]+\.(?:pdf|docx?|PDF|DOCX?))"[^>]*>\s*'
    r'(?:<b>)?\s*Vendim[^<:]*Nr[^\d]*(\d+)[^\d]*'
    r'(?:Date|Datë|Dt)[^\d]*(\d{1,2}[./-]\d{1,2}[./-]\d{4})',
    re.IGNORECASE | re.DOTALL,
)

# Accepted extensions; .doc (legacy binary Word) we skip for now — pandoc-only.
ACCEPTED_EXT = {"pdf", "docx"}


@dataclass
class DecisionRef:
    """Metadata extracted from a year listing, written to `_index.json`."""
    court_code: str
    year: int
    number: str              # raw Albanian-numbered decision id, e.g. "42"
    date: str                # normalised DD.MM.YYYY
    url: str                 # original source URL
    local_file: str          # path relative to JURISPRUDENCE_PATH


# ── HTTP helpers ───────────────────────────────────────────────────────────

@retry(
    retry=retry_if_exception_type(requests.RequestException),
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=2, min=2, max=20),
    reraise=True,
)
def _fetch(url: str, *, accept: str = "*/*") -> requests.Response:
    resp = requests.get(
        url,
        headers={"User-Agent": USER_AGENT, "Accept": accept},
        timeout=REQUEST_TIMEOUT,
        allow_redirects=True,
    )
    resp.raise_for_status()
    return resp


def _normalise_date(raw: str) -> str:
    """Accept DD.MM.YYYY, DD/MM/YYYY, DD-MM-YYYY → DD.MM.YYYY with zero-pad."""
    parts = re.split(r"[./-]", raw.strip())
    if len(parts) != 3:
        return raw
    d, m, y = (p.strip() for p in parts)
    return f"{int(d):02d}.{int(m):02d}.{int(y):04d}"


# ── year-page scraping ────────────────────────────────────────────────────

def scrape_year_index(court: Court, year: int) -> list[DecisionRef]:
    """Fetch one year's listing and return the decisions it advertises."""
    url = court.year_index_url.format(year=year)
    log.info("fetching year index: %s", url)
    resp = _fetch(url, accept="text/html,application/xhtml+xml")
    html = resp.text

    refs: list[DecisionRef] = []
    seen_urls: set[str] = set()
    for match in GJK_LINK_RE.finditer(html):
        file_url, nr, date_raw = match.group(1), match.group(2), match.group(3)
        if file_url in seen_urls:
            continue
        seen_urls.add(file_url)
        ext = file_url.rsplit(".", 1)[-1].lower()
        if ext not in ACCEPTED_EXT:
            log.debug("  skip %s (ext=%s)", file_url, ext)
            continue

        date = _normalise_date(date_raw)
        # Canonical local filename: vend_0042_2024.pdf — sortable and unambiguous.
        fname = f"vend_{int(nr):04d}_{year}.{ext}"
        local = Path(court.code) / str(year) / fname
        refs.append(DecisionRef(
            court_code=court.code,
            year=year,
            number=nr,
            date=date,
            url=file_url,
            local_file=str(local),
        ))
    log.info("  found %d decisions for %s %d", len(refs), court.code, year)
    return refs


# ── downloading ───────────────────────────────────────────────────────────

def _is_valid_file(data: bytes, ext: str) -> bool:
    if len(data) < MIN_VALID_FILE_BYTES:
        return False
    if ext == "pdf":
        return data[:4] == b"%PDF"
    if ext == "docx":
        # .docx is a zip container
        return data[:2] == b"PK"
    return True


def download_decision(ref: DecisionRef, *, force: bool = False) -> tuple[bool, str]:
    target = JURISPRUDENCE_PATH / ref.local_file
    target.parent.mkdir(parents=True, exist_ok=True)

    if target.exists() and target.stat().st_size >= MIN_VALID_FILE_BYTES and not force:
        return True, f"cached ({target.stat().st_size} bytes)"

    try:
        resp = _fetch(ref.url, accept="application/pdf,application/octet-stream,*/*")
    except requests.RequestException as exc:
        return False, f"request failed: {exc}"

    data = resp.content
    ext = target.suffix.lstrip(".").lower()
    if not _is_valid_file(data, ext):
        ctype = resp.headers.get("Content-Type", "?")
        return False, f"invalid payload (ct={ctype}, {len(data)} bytes)"

    target.write_bytes(data)
    return True, f"{len(data)} bytes → {target.relative_to(JURISPRUDENCE_PATH)}"


def download_court(court: Court, *, force: bool = False, dry_run: bool = False) -> list[DecisionRef]:
    """Scrape every year of a court and download each decision."""
    all_refs: list[DecisionRef] = []
    for year in court.years:
        try:
            refs = scrape_year_index(court, year)
        except requests.RequestException as exc:
            log.warning("year %d unreachable (%s) — skipping", year, exc)
            continue
        time.sleep(POLITE_DELAY)
        all_refs.extend(refs)

        if dry_run:
            continue

        for ref in refs:
            ok, msg = download_decision(ref, force=force)
            marker = "OK " if ok else "FAIL"
            log.info("  [%s] %s %s — %s", marker, ref.court_code, ref.local_file, msg)
            time.sleep(POLITE_DELAY)

    # Write a master index so the parser knows what to read.
    index_path = JURISPRUDENCE_PATH / court.code / "_index.json"
    index_path.parent.mkdir(parents=True, exist_ok=True)
    index_path.write_text(
        json.dumps([asdict(r) for r in all_refs], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    log.info("wrote %d refs → %s", len(all_refs), index_path)
    return all_refs


# ── CLI ───────────────────────────────────────────────────────────────────

def main() -> None:
    ap = argparse.ArgumentParser(description="Download Albanian court decisions")
    ap.add_argument("--court", default=None,
                    help="Only this court code (default: all)")
    ap.add_argument("--years", default=None,
                    help="Comma-separated years override, e.g. 2023,2024")
    ap.add_argument("--force", action="store_true",
                    help="Re-download already-cached files")
    ap.add_argument("--dry-run", action="store_true",
                    help="Scrape listings but do not download files")
    args = ap.parse_args()

    courts: list[Court]
    if args.court:
        c = court_by_code(args.court)
        if not c:
            raise SystemExit(f"unknown court: {args.court}")
        courts = [c]
    else:
        courts = list(COURTS)

    for c in courts:
        court = c
        if args.years:
            years = tuple(int(y.strip()) for y in args.years.split(",") if y.strip())
            # Clone with overridden years (Court is frozen)
            from dataclasses import replace
            court = replace(c, years=years)
        refs = download_court(court, force=args.force, dry_run=args.dry_run)
        log.info("%s: %d decisions tracked", c.code, len(refs))


if __name__ == "__main__":
    main()
