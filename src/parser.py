"""Parse Albanian legal PDFs into structured articles.

Each code is split on `Neni N` headers. For every article we capture:
  - number (e.g. "37", "83/a")
  - title (the single line after the `Neni` header)
  - body (full text until the next `Neni`, `KREU`, `SEKSIONI` or `PJESA` header)
  - hierarchy context (part / chapter / section it belongs to)
  - whether the article has been repealed ("Shfuqizuar")

Output: one JSON file per code in PROCESSED_DATA_PATH, plus a combined
`all_articles.jsonl` used by the indexer.
"""
from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path

import pdfplumber

from .config import LEGAL_DOCUMENTS, PROCESSED_DATA_PATH, RAW_DATA_PATH, LegalDocument
from .logging_utils import get_logger

log = get_logger(__name__)

# Matches "Neni 37", "Neni 83/a", "Neni 170/ç" or the glued form "Neni37"
# that some PDFs produce when the text-extractor drops the space.
# NOTE: we use [ \t] (not \s) inside the number group — otherwise newlines are
# consumed and page-number footers get glued to the article number, producing
# phantom articles like "Neni 1913" (really "Neni 19" + page footer "13").
ARTICLE_RE = re.compile(
    r"(?m)^[ \t]*Neni[ \t]*(\d+(?:[ \t]*/[ \t]*[a-zçëA-ZÇË0-9]+)?)[ \t]*$"
)

# Hierarchy headers (PJESA / KREU / SEKSIONI / TITULLI). Used as context.
HIERARCHY_RE = re.compile(
    r"(?m)^[ \t]*(PJESA|KREU|SEKSIONI|TITULLI|KAPITULLI)\s+([A-ZÇËÏ0-9/]+)\s*$"
)

REPEALED_MARKERS = ("shfuqizuar", "shfuqizohet")


@dataclass
class Article:
    """A single article extracted from a code."""

    code: str               # e.g. "kodi_penal"
    title_sq: str           # code title (Kodi Penal ...)
    area: str               # broad area (Penal, Civil, ...)
    number: str             # "37", "83/a"
    heading: str            # first line after "Neni N"
    body: str               # full article text
    pjesa: str = ""         # part
    kreu: str = ""          # chapter
    seksioni: str = ""      # section
    repealed: bool = False
    volatility: str = "STABLE"            # V7.4 — inherited from LegalDocument
    last_amendment_date: str = ""          # V7.4 — ISO date of last indexed amendment

    @property
    def citation(self) -> str:
        return f"Neni {self.number} i {self.title_sq}"

    @property
    def searchable_text(self) -> str:
        """Text to embed — heading + body + citation for recall."""
        parts = [self.citation]
        if self.heading:
            parts.append(self.heading)
        parts.append(self.body)
        return "\n".join(parts)


# ── PDF extraction ──────────────────────────────────────────────────────────

def extract_full_text(pdf_path: Path) -> str:
    """Extract and concatenate all pages of a PDF, stripping typical footers."""
    pages: list[str] = []
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            txt = page.extract_text() or ""
            pages.append(txt)
    text = "\n".join(pages)
    text = _clean_text(text)
    return text


def _clean_text(text: str) -> str:
    # Remove isolated page-number lines (1..9999 on their own line)
    text = re.sub(r"(?m)^\s*\d{1,4}\s*$\n?", "", text)
    # Collapse runs of >2 blank lines
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text


# ── Article splitting ───────────────────────────────────────────────────────

def _hierarchy_context(text_before: str) -> tuple[str, str, str]:
    """Return the most recent (pjesa, kreu, seksioni) mentioned before this pos."""
    pjesa = kreu = seksioni = ""
    for match in HIERARCHY_RE.finditer(text_before):
        label = match.group(1).upper()
        line = match.group(0).strip()
        # Try to include the next line as the title of the section
        tail = text_before[match.end() : match.end() + 200]
        next_line = next((ln.strip() for ln in tail.splitlines() if ln.strip()), "")
        full = f"{line} — {next_line}" if next_line and not HIERARCHY_RE.match(next_line) else line
        if label == "PJESA":
            pjesa = full
            kreu = seksioni = ""
        elif label in ("KREU", "KAPITULLI", "TITULLI"):
            kreu = full
            seksioni = ""
        elif label == "SEKSIONI":
            seksioni = full
    return pjesa, kreu, seksioni


def split_into_articles(text: str, doc: LegalDocument) -> list[Article]:
    """Split the full code text into Article objects."""
    raw_matches = list(ARTICLE_RE.finditer(text))

    # V7.4 step 1 — filter out phantom matches. A "Neni 1913" produced by a
    # page-footer "13" glued to the real "Neni 19" has either no body or just
    # another "Neni X" header in its range. Drop those before any further
    # analysis so counter-restart detection isn't poisoned by fake maxima.
    filtered: list = []
    for i, m in enumerate(raw_matches):
        number = re.sub(r"\s+", "", m.group(1))
        num_only = number.split("/")[0]
        end = raw_matches[i + 1].start() if i + 1 < len(raw_matches) else len(text)
        body_len = len(text[m.end():end].strip())
        if num_only.isdigit():
            n_int = int(num_only)
            # Hard cap — no Albanian code exceeds ~1300 articles (Kodi Civil)
            if n_int > 2000:
                continue
            # Implausible + empty body → page-footer collision artifact
            if n_int > 500 and body_len < 40:
                continue
        filtered.append(m)

    # V7.4 step 2 — some official PDFs (especially for ligji_*) bundle the
    # main law with implementing acts (VKM, UDHËZIM) that each start their
    # own Neni 1. Detect a counter restart (a number far below the running
    # max) and drop everything past that point.
    seen_max = 0
    truncate_idx = len(filtered)
    for i, m in enumerate(filtered):
        num_str = re.sub(r"\s+", "", m.group(1))
        try:
            num_int = int(num_str.split("/")[0])
        except ValueError:
            num_int = 0
        if i > 0 and num_int > 0 and num_int < seen_max - 5:
            log.info(
                "parser: truncating %s at Neni %s — counter dropped from %d",
                doc.code, num_str, seen_max,
            )
            truncate_idx = i
            break
        if num_int > seen_max:
            seen_max = num_int
    matches = filtered[:truncate_idx]

    articles: list[Article] = []
    for i, m in enumerate(matches):
        number = re.sub(r"\s+", "", m.group(1))  # "83 / a" -> "83/a"
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        raw = text[start:end].strip()

        # Heading = the FIRST COMPLETE SENTENCE after "Neni N", body = rest.
        # The Albanian PDFs hard-wrap mid-sentence ("Trashëgimlënësi edhe pa
        # caktuar trashëgimtarë në testament\nmund të përjashtojë nga...");
        # the old parser took only line[0], producing tronche headings that
        # poisoned BM25 retrieval and led the model to drift on
        # successioni-testamentari analyses (V9.0.3 doctrine bug). We now
        # glue lines until a sentence terminator is reached.
        lines = [ln.strip() for ln in raw.splitlines() if ln.strip()]
        heading = ""
        body = ""
        if lines:
            buf = lines[0]
            consumed = 1
            # Sentence is complete if it ends with `.`, `:`, `!`, `?` AND
            # is at least 25 chars (so we don't stop on "p.sh." abbreviation
            # at the very start). Cap at 8 lines to never swallow whole body.
            def _is_complete(s: str) -> bool:
                return len(s) >= 25 and s[-1] in ".:!?"
            while consumed < len(lines) and consumed < 8 and not _is_complete(buf):
                buf = buf + " " + lines[consumed]
                consumed += 1
            heading = buf
            body = "\n".join(lines[consumed:]).strip()

        # Hierarchy from the text *before* this article
        pjesa, kreu, seksioni = _hierarchy_context(text[: m.start()])

        repealed = any(mk in (heading + " " + body).lower() for mk in REPEALED_MARKERS) \
                   and len(body) < 400  # short body + "shfuqizuar" → repealed stub

        articles.append(
            Article(
                code=doc.code,
                title_sq=doc.title_sq,
                area=doc.area,
                number=number,
                heading=heading,
                body=body,
                pjesa=pjesa,
                kreu=kreu,
                seksioni=seksioni,
                repealed=repealed,
                volatility=doc.volatility,
                last_amendment_date=doc.last_amendment_date,
            )
        )
    return articles


# ── Orchestration ───────────────────────────────────────────────────────────

def parse_one(doc: LegalDocument) -> list[Article]:
    pdf_path = RAW_DATA_PATH / doc.local_pdf
    if not pdf_path.exists():
        log.warning("skip %s — file not found: %s", doc.code, pdf_path)
        return []

    log.info("parsing %s ...", doc.code)
    text = extract_full_text(pdf_path)
    articles = split_into_articles(text, doc)
    log.info("  → %d articles extracted from %s", len(articles), doc.code)
    return articles


def parse_all() -> dict[str, list[Article]]:
    PROCESSED_DATA_PATH.mkdir(parents=True, exist_ok=True)
    all_articles: dict[str, list[Article]] = {}
    combined_path = PROCESSED_DATA_PATH / "all_articles.jsonl"
    with combined_path.open("w", encoding="utf-8") as combined:
        for doc in LEGAL_DOCUMENTS:
            articles = parse_one(doc)
            all_articles[doc.code] = articles

            # per-code JSON for debugging / inspection
            (PROCESSED_DATA_PATH / f"{doc.code}.json").write_text(
                json.dumps([asdict(a) for a in articles], ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

            for a in articles:
                combined.write(json.dumps(asdict(a), ensure_ascii=False) + "\n")
    log.info("combined articles written to %s", combined_path)
    return all_articles


def print_summary(results: dict[str, list[Article]]) -> None:
    print("\n" + "=" * 60)
    print(f"{'Code':<22}{'Articles':>10}{'Repealed':>12}{'Avg body':>12}")
    print("-" * 60)
    total = 0
    for code, articles in results.items():
        total += len(articles)
        if not articles:
            print(f"{code:<22}{'0':>10}{'-':>12}{'-':>12}")
            continue
        repealed = sum(1 for a in articles if a.repealed)
        avg_body = int(sum(len(a.body) for a in articles) / len(articles))
        print(f"{code:<22}{len(articles):>10}{repealed:>12}{avg_body:>12}")
    print("-" * 60)
    print(f"{'TOTAL':<22}{total:>10}")
    print("=" * 60 + "\n")


if __name__ == "__main__":
    results = parse_all()
    print_summary(results)
