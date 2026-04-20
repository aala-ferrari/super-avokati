"""Download the official Albanian legal documents.

Downloads each PDF declared in config.LEGAL_DOCUMENTS into RAW_DATA_PATH.
Skips files that already exist and are non-empty, so the pipeline is idempotent.
Prints a summary of successes and failures so you can retry specific codes.
"""
from __future__ import annotations

from pathlib import Path

import requests
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from .config import LEGAL_DOCUMENTS, RAW_DATA_PATH, LegalDocument
from .logging_utils import get_logger

log = get_logger(__name__)

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36 "
    "SuperAvvocato/0.1 (+humanitarian legal assistant)"
)
TIMEOUT_SECONDS = 90
MIN_VALID_PDF_BYTES = 10_000


@retry(
    retry=retry_if_exception_type((requests.RequestException,)),
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=2, min=2, max=30),
    reraise=True,
)
def _fetch(url: str) -> requests.Response:
    resp = requests.get(
        url,
        headers={"User-Agent": USER_AGENT, "Accept": "application/pdf,*/*"},
        timeout=TIMEOUT_SECONDS,
        allow_redirects=True,
        stream=True,
    )
    resp.raise_for_status()
    return resp


def _is_pdf(content: bytes) -> bool:
    return content[:4] == b"%PDF"


def download_one(doc: LegalDocument, force: bool = False) -> tuple[bool, str]:
    """Download a single legal document. Returns (success, message)."""
    if not doc.url:
        return False, "no URL configured"

    target = RAW_DATA_PATH / doc.local_pdf
    if target.exists() and target.stat().st_size >= MIN_VALID_PDF_BYTES and not force:
        return True, f"already cached ({target.stat().st_size} bytes)"

    try:
        resp = _fetch(doc.url)
    except requests.RequestException as exc:
        return False, f"request failed: {exc}"

    content = resp.content
    if not _is_pdf(content):
        # Some government sites return HTML wrappers; the caller may need to
        # open the URL in a browser and save the PDF manually.
        ctype = resp.headers.get("Content-Type", "unknown")
        return False, f"response was not a PDF (Content-Type={ctype}, {len(content)} bytes)"

    target.write_bytes(content)
    return True, f"downloaded {len(content)} bytes → {target.name}"


def download_all(force: bool = False) -> dict[str, tuple[bool, str]]:
    RAW_DATA_PATH.mkdir(parents=True, exist_ok=True)
    results: dict[str, tuple[bool, str]] = {}
    for doc in LEGAL_DOCUMENTS:
        log.info("→ %s (%s)", doc.title_sq, doc.code)
        ok, msg = download_one(doc, force=force)
        results[doc.code] = (ok, msg)
        marker = "OK " if ok else "FAIL"
        log.info("  [%s] %s", marker, msg)
    return results


def summary(results: dict[str, tuple[bool, str]]) -> str:
    ok = [c for c, (s, _) in results.items() if s]
    fail = [c for c, (s, _) in results.items() if not s]
    lines = [
        "",
        "=" * 60,
        f"Downloaded: {len(ok)}/{len(results)}",
        f"  ✓ {', '.join(ok) if ok else '(none)'}",
        f"  ✗ {', '.join(fail) if fail else '(none)'}",
        "=" * 60,
    ]
    return "\n".join(lines)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Download Albanian legal documents")
    parser.add_argument("--force", action="store_true",
                        help="Re-download even if the file is already cached")
    parser.add_argument("--only", nargs="+", default=None,
                        help="Download only these codes (machine ids)")
    args = parser.parse_args()

    if args.only:
        filtered = [d for d in LEGAL_DOCUMENTS if d.code in set(args.only)]
        results = {}
        for d in filtered:
            ok, msg = download_one(d, force=args.force)
            results[d.code] = (ok, msg)
            log.info("[%s] %s — %s", "OK " if ok else "FAIL", d.code, msg)
    else:
        results = download_all(force=args.force)

    print(summary(results))
