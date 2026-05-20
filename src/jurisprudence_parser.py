"""Parse Constitutional-Court decisions into structured Decision objects.

A Kushtetuese decision follows a stereotyped template:

    Vendim nr. N datë DD.MM.YYYY
    (V-N/YY)
    Gjykata Kushtetuese ... përbërë nga: <judges>, me sekretar
    KËRKUES(E)(I): <requesting party>
    SUBJEKT(E)(I) I(TË) INTERESUAR(I)(A): <affected parties>
    OBJEKTI: <subject of the case>
    BAZA LIGJORE: <legal basis>
    GJYKATA KUSHTETUESE,
    pasi dëgjoi ...
    V Ë R E N:
    <numbered reasoning>
    PËR KËTO ARSYE,
    <citation of articles supporting the decision>
    V E N D O S I:
    <dispositif — Rrëzim / Pranim / Pushim etc.>

We split on these markers, extract each field, and classify the outcome. The
reasoning body (between "V Ë R E N:" and "PËR KËTO ARSYE,") is what feeds
BM25 retrieval — that's where the substantive legal analysis lives.

Output: PROCESSED_DATA_PATH/all_decisions.jsonl, one Decision per line.
"""
from __future__ import annotations

import argparse
import json
import re
from collections.abc import Iterable
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Literal

import pdfplumber
from docx import Document

from .config import COURTS, JURISPRUDENCE_PATH, PROCESSED_DATA_PATH, Court, court_by_code
from .logging_utils import get_logger

log = get_logger(__name__)

DECISIONS_JSONL = PROCESSED_DATA_PATH / "all_decisions.jsonl"

# ── field extraction regexes ──────────────────────────────────────────────

# "Vendim nr. 42 datë 29.05.2024" — case header. Captures (number, date).
HEADER_RE = re.compile(
    r"Vendim\s+nr\.?\s*([\w/\-]+)\s+dat[ëe]?\s*(\d{1,2}[./\-]\d{1,2}[./\-]\d{4})",
    re.IGNORECASE,
)

# Judges sit between "përbërë nga" and "me sekretar". Comma/semicolon separated,
# each entry is "Name Surname, Role" — we keep the whole composition block and
# parse out the names afterwards.
COMPOSITION_RE = re.compile(
    r"p[ëe]rb[ëe]r[ëe]\s+nga\s*:?\s*(.+?)(?:me\s+sekretar|V\s*[ËE]\s*R\s*[ËE]\s*N|$)",
    re.IGNORECASE | re.DOTALL,
)
# A judge tag looks like "Bashkim Dedja, Kryetar" or "Vitore Tusha, anëtare".
NAME_RE = re.compile(
    r"\b([A-ZÇËÏ][a-zçëï]+(?:\s+[A-ZÇËÏ][a-zçëï]+){1,3})\b",
)

# Field labels — anchored to start-of-line (after a newline or at buffer start)
# so we don't misfire on the same word appearing mid-paragraph.
# Labels in Kushtetuese decisions:
#   KËRKUES / KËRKUESE / KËRKUESI / KËRKUESIA  (requesting party)
#   SUBJEKTE TË INTERESUARA / SUBJEKTI I INTERESUAR (affected parties)
#   OBJEKTI / OBJEKTI I KËRKESËS  (subject of the case)
#   BAZA LIGJORE  (legal basis)
# Some older DOCX decisions use letter-spaced labels for emphasis:
#   "K Ë R K U ES:", "O B J E K T I:", "V Ë R E N:"
# We normalise by building patterns that accept optional whitespace between
# every pair of letters, so "KËRKUES" and "K Ë R K U ES" both match.
def _spaced(word: str) -> str:
    return r"\s*".join(re.escape(ch) for ch in word)

_KERKUES = rf"(?:{_spaced('KËRKUES')}|{_spaced('KERKUES')}|{_spaced('KËRKUESE')}|{_spaced('KERKUESE')}|{_spaced('KËRKUESI')}|{_spaced('KERKUESI')})"
_OBJEKTI = rf"(?:{_spaced('OBJEKTI')}|{_spaced('OBJEKT')})"
_BAZA = rf"(?:{_spaced('BAZA')}\s+{_spaced('LIGJORE')})"
_SUBJEKT = rf"(?:{_spaced('SUBJEKTE')}|{_spaced('SUBJEKTI')}|{_spaced('SUBJEKT')})"
_GJYKATA = _spaced('GJYKATA')

_FIELD_STOP = rf"(?=\n\s*(?:{_SUBJEKT}|{_OBJEKTI}|{_BAZA}|{_GJYKATA}|{_spaced('VËREN')}|{_spaced('VEREN')}|P[ËE]R\s+K[ËE]TO)|$)"

KERKUES_RE = re.compile(
    rf"(?:^|\n)\s*{_KERKUES}\s*:\s*(.+?){_FIELD_STOP}",
    re.IGNORECASE | re.DOTALL,
)
SUBJECT_RE = re.compile(
    rf"(?:^|\n)\s*{_SUBJEKT}\s+[IT][ËE]?\s*INTERESUAR[A-ZÇËÏa-zçëï]*\s*:\s*(.+?){_FIELD_STOP}",
    re.IGNORECASE | re.DOTALL,
)
OBJEKT_RE = re.compile(
    rf"(?:^|\n)\s*{_OBJEKTI}\s*:\s*(.+?){_FIELD_STOP}",
    re.IGNORECASE | re.DOTALL,
)
BAZA_RE = re.compile(
    rf"(?:^|\n)\s*{_BAZA}\s*:\s*(.+?){_FIELD_STOP}",
    re.IGNORECASE | re.DOTALL,
)

# Reasoning body: between "VËREN:" (compact) or "V Ë R E N:" (letter-spaced,
# both forms exist across years) and "PËR KËTO ARSYE" (the per-curiam block).
# The "VËREN" token never appears in narrative text — it's exclusively the
# per-curiam heading — so it's a reliable anchor.
REASONING_RE = re.compile(
    rf"(?:{_spaced('VËREN')}|{_spaced('VEREN')})\s*:?(.+?)P[ËE]R\s+K[ËE]TO\s+ARSYE",
    re.IGNORECASE | re.DOTALL,
)
# Dispositif: scoped to text AFTER "PËR KËTO ARSYE" so we never hit the many
# narrative "vendosi"/"ka vendosur" mentions earlier in the reasoning.
PER_KETO_RE = re.compile(r"P[ËE]R\s+K[ËE]TO\s+ARSYE", re.IGNORECASE)
# Operative part starts at "VENDOSI:" (compact) or "V E N D O S I:" (spaced).
DISPOSITIF_RE = re.compile(
    rf"{_spaced('VENDOSI')}\s*:?\s*(.+?)(?=Ky\s+vendim|\Z)",
    re.IGNORECASE | re.DOTALL,
)

# Articles cited anywhere in the decision text — "neni 42", "nenit 42/a",
# "nenet 5, 7 dhe 9". Normalised to a set of {number} strings.
NENI_RE = re.compile(
    r"\bnen(?:i|it|in|e|eve|et)?\s+(\d+(?:\s*/\s*[a-zçëï0-9]+)?)",
    re.IGNORECASE,
)

# Outcome classification — order matters (pjesërisht before pranim).
OUTCOME_KEYWORDS: tuple[tuple[str, str], ...] = (
    ("pjes[ëe]risht", "pjesërisht"),
    ("rr[ëe]zim", "rrëzim"),
    ("pushim", "pushim"),
    ("pranim", "pranim"),
    ("moskompetenc", "moskompetencë"),
)


@dataclass
class Decision:
    """A court decision — sibling of Article for the retrieval index."""

    court_code: str            # "kushtetuese"
    court_title_sq: str        # "Gjykata Kushtetuese e Republikës së Shqipërisë"
    court_short_sq: str        # "Gjykata Kushtetuese"
    year: int
    number: str                # raw decision number as printed, e.g. "42"
    date: str                  # DD.MM.YYYY
    citation: str = ""         # "Vendimi nr. 42/2024 i Gjykatës Kushtetuese"
    short_id: str = ""         # "V-42/24"
    objekti: str = ""          # subject of the case
    kerkues: str = ""          # requesting party (often an institution)
    subjekte_interesuara: str = ""  # affected parties (kept anonymized)
    baza_ligjore: str = ""     # legal basis cited in header
    judges: list[str] = field(default_factory=list)   # composition names
    cited_articles: list[str] = field(default_factory=list)  # normalised "N" / "N/a"
    outcome: str = ""          # "pranim" / "rrëzim" / "pjesërisht" / "pushim" / "moskompetencë" / ""
    dispositif: str = ""       # short text of the operative part
    reasoning: str = ""        # full "VËREN" block (trimmed)
    source_file: str = ""      # path relative to JURISPRUDENCE_PATH
    source_url: str = ""       # original URL at gjykatakushtetuese.gov.al
    kind: Literal["decision"] = "decision"

    @property
    def searchable_text(self) -> str:
        """What BM25 sees — citation + subject + parties + reasoning."""
        parts: list[str] = [self.citation]
        if self.objekti:
            parts.append("OBJEKTI: " + self.objekti)
        if self.kerkues:
            parts.append("KËRKUES: " + self.kerkues)
        if self.subjekte_interesuara:
            parts.append("SUBJEKTE TË INTERESUARA: " + self.subjekte_interesuara)
        if self.baza_ligjore:
            parts.append("BAZA LIGJORE: " + self.baza_ligjore)
        if self.reasoning:
            # Cap reasoning at 5k chars — the first half is where the holdings
            # usually land; BM25 is robust to trailing noise anyway.
            parts.append(self.reasoning[:5000])
        return "\n".join(parts)


# ── text extraction ───────────────────────────────────────────────────────

def _extract_text(path: Path) -> str:
    """Return raw text, extension-aware. Empty string on hard failure."""
    ext = path.suffix.lower().lstrip(".")
    try:
        if ext == "pdf":
            with pdfplumber.open(path) as pdf:
                return "\n".join((p.extract_text() or "") for p in pdf.pages)
        if ext == "docx":
            doc = Document(path)
            return "\n".join(p.text for p in doc.paragraphs)
    except Exception as exc:  # noqa: BLE001
        log.warning("extract failed (%s): %s", path.name, exc)
    return ""


def _clean(text: str) -> str:
    text = re.sub(r"\r\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


# ── field helpers ─────────────────────────────────────────────────────────

def _first_line(block: str) -> str:
    for ln in block.splitlines():
        s = ln.strip()
        if s:
            return s
    return ""


def _match_group(pattern: re.Pattern[str], text: str, *, group: int = 1) -> str:
    m = pattern.search(text)
    if not m:
        return ""
    return re.sub(r"\s+", " ", m.group(group)).strip(" :;-\t")


def _classify_outcome(dispositif: str) -> str:
    low = dispositif.lower()
    for pat, label in OUTCOME_KEYWORDS:
        if re.search(pat, low):
            return label
    return ""


def _extract_judges(composition: str) -> list[str]:
    if not composition:
        return []
    # Names come before role tags. Split on commas and grab the first
    # two-to-four capitalised tokens from each chunk.
    judges: list[str] = []
    for chunk in re.split(r"[,;]\s*", composition):
        m = NAME_RE.match(chunk.strip())
        if m:
            name = m.group(1).strip()
            if name and name.split()[0] not in {"Republika", "Shqiperise", "Shqiperisë"}:
                judges.append(name)
    # De-dup while preserving order
    seen: set[str] = set()
    unique: list[str] = []
    for j in judges:
        if j not in seen:
            seen.add(j)
            unique.append(j)
    return unique


def _extract_articles(text: str) -> list[str]:
    found: list[str] = []
    seen: set[str] = set()
    for m in NENI_RE.finditer(text):
        normalised = re.sub(r"\s+", "", m.group(1))
        if normalised not in seen:
            seen.add(normalised)
            found.append(normalised)
    return found


# ── per-decision parser ───────────────────────────────────────────────────

def parse_decision(ref: dict, court: Court) -> Decision | None:
    path = JURISPRUDENCE_PATH / ref["local_file"]
    if not path.exists() or path.stat().st_size < 1000:
        log.debug("skip missing/tiny %s", ref["local_file"])
        return None

    raw = _clean(_extract_text(path))
    if len(raw) < 500:
        log.debug("skip unparseable %s (%d chars)", ref["local_file"], len(raw))
        return None

    year = int(ref["year"])
    number = str(ref["number"])
    date = ref["date"]

    # Header re-check from the body itself (trust the file over the listing).
    hm = HEADER_RE.search(raw)
    if hm:
        number = number or hm.group(1)
        date = date or hm.group(2)

    # Short id like V-42/24 — optional, nice for citations
    short_id_m = re.search(r"\(\s*V\s*-\s*(\d+)\s*/\s*(\d{2,4})\s*\)", raw)
    short_id = f"V-{short_id_m.group(1)}/{short_id_m.group(2)}" if short_id_m else ""

    composition = _match_group(COMPOSITION_RE, raw)
    kerkues = _first_line(_match_group(KERKUES_RE, raw))
    subjekte = _match_group(SUBJECT_RE, raw)
    objekti = _match_group(OBJEKT_RE, raw)
    baza = _match_group(BAZA_RE, raw)
    reasoning = _match_group(REASONING_RE, raw)

    # Dispositif: restrict search to the per-curiam tail to avoid matching
    # earlier narrative mentions of "vendosi" / "ka vendosur".
    per_keto = PER_KETO_RE.search(raw)
    tail = raw[per_keto.end():] if per_keto else raw
    dispositif = _match_group(DISPOSITIF_RE, tail)

    judges = _extract_judges(composition)
    # Cite detection runs over the whole decision — baza + reasoning + the
    # per-curiam block (where the court explicitly names the articles it
    # relies on to decide). This maximises precedent-matching recall.
    cited = _extract_articles(" ".join(filter(None, (baza, reasoning, tail[:4000]))))
    outcome = _classify_outcome(dispositif)

    citation = f"Vendimi nr. {number}/{year} i {court.short_sq}"

    return Decision(
        court_code=court.code,
        court_title_sq=court.title_sq,
        court_short_sq=court.short_sq,
        year=year,
        number=number,
        date=date,
        citation=citation,
        short_id=short_id,
        objekti=objekti[:800],
        kerkues=kerkues[:300],
        subjekte_interesuara=subjekte[:500],
        baza_ligjore=baza[:800],
        judges=judges[:12],
        cited_articles=cited[:40],
        outcome=outcome,
        dispositif=dispositif[:400],
        reasoning=reasoning,
        source_file=ref["local_file"],
        source_url=ref.get("url", ""),
    )


# ── orchestration ─────────────────────────────────────────────────────────

def parse_court(court: Court) -> list[Decision]:
    index_path = JURISPRUDENCE_PATH / court.code / "_index.json"
    if not index_path.exists():
        log.warning("no _index.json for %s — run the downloader first", court.code)
        return []

    refs = json.loads(index_path.read_text(encoding="utf-8"))
    # Some decisions are listed twice on the source site under different URLs
    # but collapse to the same local file — dedupe by local_file to avoid
    # double-counting the same ruling in the BM25 index.
    seen: set[str] = set()
    unique_refs = []
    for r in refs:
        key = r["local_file"]
        if key in seen:
            continue
        seen.add(key)
        unique_refs.append(r)
    if len(unique_refs) < len(refs):
        log.info("deduped %d → %d refs", len(refs), len(unique_refs))
    log.info("parsing %d refs for %s ...", len(unique_refs), court.code)
    decisions: list[Decision] = []
    for ref in unique_refs:
        dec = parse_decision(ref, court)
        if dec:
            decisions.append(dec)
    log.info("  → %d decisions parsed (of %d refs)", len(decisions), len(unique_refs))
    return decisions


def parse_all(courts: Iterable[Court] | None = None) -> list[Decision]:
    PROCESSED_DATA_PATH.mkdir(parents=True, exist_ok=True)
    all_decisions: list[Decision] = []
    for court in (courts or COURTS):
        all_decisions.extend(parse_court(court))

    with DECISIONS_JSONL.open("w", encoding="utf-8") as fh:
        for d in all_decisions:
            fh.write(json.dumps(asdict(d), ensure_ascii=False) + "\n")
    log.info("wrote %d decisions → %s", len(all_decisions), DECISIONS_JSONL)
    return all_decisions


def print_summary(decisions: list[Decision]) -> None:
    from collections import Counter
    by_court = Counter(d.court_code for d in decisions)
    by_outcome = Counter(d.outcome or "(unknown)" for d in decisions)
    by_year = Counter(d.year for d in decisions)
    print("\n" + "=" * 60)
    print(f"Total decisions parsed: {len(decisions)}")
    print("-" * 60)
    print("By court:    ", dict(by_court))
    print("By year:     ", dict(sorted(by_year.items())))
    print("By outcome:  ", dict(by_outcome))
    print("-" * 60)
    # Sample articles + judges metadata coverage
    with_articles = sum(1 for d in decisions if d.cited_articles)
    with_judges = sum(1 for d in decisions if d.judges)
    with_outcome = sum(1 for d in decisions if d.outcome)
    print("Fields populated:")
    print(f"  cited_articles: {with_articles}/{len(decisions)}")
    print(f"  judges:         {with_judges}/{len(decisions)}")
    print(f"  outcome:        {with_outcome}/{len(decisions)}")
    print("=" * 60 + "\n")


def main() -> None:
    ap = argparse.ArgumentParser(description="Parse Albanian court decisions")
    ap.add_argument("--court", default=None,
                    help="Only this court code (default: all)")
    args = ap.parse_args()

    courts: list[Court]
    if args.court:
        c = court_by_code(args.court)
        if not c:
            raise SystemExit(f"unknown court: {args.court}")
        courts = [c]
    else:
        courts = list(COURTS)

    decisions = parse_all(courts)
    print_summary(decisions)


if __name__ == "__main__":
    main()
