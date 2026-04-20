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
ARTICLE_RE = re.compile(
    r"(?m)^[ \t]*Neni\s*(\d+(?:\s*/\s*[a-zçëA-ZÇË0-9]+)?)\s*$"
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
    matches = list(ARTICLE_RE.finditer(text))
    articles: list[Article] = []
    for i, m in enumerate(matches):
        number = re.sub(r"\s+", "", m.group(1))  # "83 / a" -> "83/a"
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        raw = text[start:end].strip()

        # The first non-empty line after "Neni N" is the heading.
        lines = [ln.strip() for ln in raw.splitlines() if ln.strip()]
        heading = lines[0] if lines else ""
        body = "\n".join(lines[1:]).strip() if len(lines) > 1 else ""

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
