"""Postgres-backed precedent retrieval over the V4 legal knowledge base.

Replaces the old JSONL-backed ``DecisionIndex`` in ``retrieval.py`` with a
retriever that talks directly to the structured corpus in Postgres
(``Case``, ``Participation``, ``ArticleCited``, ``Person``, ``Court``).

Why this matters
----------------
The old path retrieved decisions as free-text Decision objects. The new
path returns ``CasePrecedent`` with the *whole dossier* of each precedent:
court, outcome, judges, articles cited, summary — everything the answer
stage needs to cite precisely ("Gjykata e Lartë, nr. 123/2024, vendosi
rrëzimin e rekursit") and everything a filter stage needs to restrict by
(materia, esito, corte, anno, nen citato).

Retrieval strategy
------------------
In-memory BM25 over a composite searchable text per case (summary +
court + judges + cited articles + truncated excerpt). ~800 cases at v1
fit comfortably in RAM; Postgres FTS (``tsvector``) is a later upgrade
if/when the corpus grows past ~20k.

Composite text is built once at startup and cached. DB is the source of
truth — we don't try to invalidate the cache, callers restart the process
when the corpus grows (same pattern as the articles BM25 index).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Iterable

from rank_bm25 import BM25Okapi
from sqlalchemy.orm import selectinload

from src.config import TOP_K_DECISIONS
from src.db import ArticleCited, Case, Court, Participation, Person, session_scope
from src.logging_utils import get_logger
from src.retrieval import tokenize  # reuse Albanian tokenizer

log = get_logger(__name__)


# Characters of full_text included in the BM25 corpus. Full decisions can
# be 50-200 KB; the first ~1200 chars usually contain the court header,
# case number, parties, and the "OBJEKTI" section — high-signal for
# matching. Loading the whole body would 10× RAM for marginal recall.
BM25_BODY_CHARS = 1200

# Characters of summary / full_text shown to the answer model per
# precedent. Enough for the reasoning but not enough to dominate the
# prompt when we return several.
PROMPT_SUMMARY_CHARS = 500


# ──────────────────────────────────────────────────────────────────────
# Result type
# ──────────────────────────────────────────────────────────────────────


@dataclass
class CasePrecedent:
    """One precedent, fully structured for prompt rendering + UI linking."""

    id: int                              # DB primary key → pin-to-row citations
    court_code: str
    court_name: str
    court_level: str
    case_number: str
    decision_date: date | None
    type: str                            # penal | civil | administrativ | cedu | ...
    subtype: str | None
    outcome: str | None
    summary: str                         # short Albanian summary (LLM-extracted)
    excerpt: str                         # short excerpt of full_text for prompt
    judges: list[str] = field(default_factory=list)
    lawyers: list[str] = field(default_factory=list)
    prosecutors: list[str] = field(default_factory=list)
    articles_cited: list[tuple[str, str]] = field(default_factory=list)
    # [(code, article)] — e.g. [("kodi_penal", "76"), ("kushtetuta", "42")]
    source_url: str | None = None

    @property
    def year(self) -> int | None:
        return self.decision_date.year if self.decision_date else None

    @property
    def citation(self) -> str:
        """Short human-readable citation for logs & quick rendering."""
        yr = f"/{self.year}" if self.year else ""
        return f"{self.court_name}, nr. {self.case_number}{yr}"


# ──────────────────────────────────────────────────────────────────────
# Retriever
# ──────────────────────────────────────────────────────────────────────


class LegalKBRetriever:
    """BM25 over V4 cases, with structured filters applied post-rank."""

    def __init__(self, cases: list[CasePrecedent], bm25: BM25Okapi):
        self.cases = cases
        self.bm25 = bm25
        self._cited_codes_per_case = [
            {code for code, _art in c.articles_cited} for c in cases
        ]
        self._cited_articles_per_case = [
            {_article_key(code, art) for code, art in c.articles_cited}
            for c in cases
        ]

    # ── construction ───────────────────────────────────────────────────

    @classmethod
    def load(cls) -> "LegalKBRetriever":
        """Pull all ``complete`` cases from Postgres and build the index.

        Only ``extraction_status='complete'`` cases are indexed — pending
        and failed rows lack the structured metadata the retriever needs
        (outcome, judges, articles cited).
        """
        with session_scope() as sess:
            rows = (
                sess.query(Case)
                .options(
                    selectinload(Case.court),
                    selectinload(Case.participations).selectinload(Participation.person),
                    selectinload(Case.articles_cited),
                )
                .filter(Case.extraction_status == "complete")
                .all()
            )
            precedents = [_row_to_precedent(c) for c in rows]
        if not precedents:
            log.warning("legalkb retriever: no complete cases found — returning empty index")
            return cls([], BM25Okapi([["placeholder"]]))  # empty-but-valid BM25
        corpus = [tokenize(_searchable_text(p)) for p in precedents]
        bm25 = BM25Okapi(corpus)
        log.info("legalkb retriever: indexed %d cases", len(precedents))
        return cls(precedents, bm25)

    # ── querying ───────────────────────────────────────────────────────

    def search(
        self,
        queries: Iterable[str],
        top_k: int = TOP_K_DECISIONS,
        *,
        type: str | None = None,
        outcome: str | None = None,
        outcomes: Iterable[str] | None = None,
        court_code: str | None = None,
        year_from: int | None = None,
        year_to: int | None = None,
        cited_code: str | None = None,
        cited_articles: Iterable[tuple[str, str]] | None = None,
        min_score: float = 1.0,
    ) -> list[tuple[CasePrecedent, float]]:
        """Rank cases by max-BM25 over any of ``queries``, then filter.

        Filters cut *after* ranking so we don't lose an on-topic precedent
        just because one of its fields happens to be null. The min_score
        floor prevents marginal BM25 hits from sneaking in when filters
        happen to match a weak candidate.

        ``outcomes`` (set semantics) is how adversarial retrieval works:
        pass the set of losing outcomes to guarantee the top-K includes
        unfavorable precedents, even when the best BM25 hits happen to
        be wins. ``outcome`` (singular) remains as a precise 1-value filter.
        """
        outcome_set = set(outcomes) if outcomes else None
        article_hint_set = {
            _article_key(code, article) for code, article in (cited_articles or [])
            if code and article
        }
        code_hint_set = {code for code, _article in article_hint_set}
        if not self.cases:
            return []

        # Per-case best score across the query set. Taking max (not sum)
        # prevents a single broadly-matching query from dominating; we
        # want "is this case a strong match for *any* framing of the
        # problem?"
        best: dict[int, float] = {}
        for q in queries:
            tokens = tokenize(q)
            if not tokens:
                continue
            scores = self.bm25.get_scores(tokens)
            for i, s in enumerate(scores):
                if s > best.get(i, 0.0):
                    best[i] = float(s)

        candidates = sorted(best.items(), key=lambda kv: kv[1], reverse=True)

        out: list[tuple[CasePrecedent, float]] = []
        for idx, score in candidates:
            if score < min_score:
                break
            c = self.cases[idx]
            if type and c.type != type:
                continue
            if outcome and c.outcome != outcome:
                continue
            if outcome_set and (c.outcome or "") not in outcome_set:
                continue
            if court_code and c.court_code != court_code:
                continue
            if year_from and (not c.year or c.year < year_from):
                continue
            if year_to and (not c.year or c.year > year_to):
                continue
            if cited_code and cited_code not in self._cited_codes_per_case[idx]:
                continue
            enriched_score = score + _precedent_match_bonus(
                c,
                article_hint_set=article_hint_set,
                code_hint_set=code_hint_set,
                case_codes=self._cited_codes_per_case[idx],
                case_articles=self._cited_articles_per_case[idx],
            )
            out.append((c, enriched_score))

        out.sort(key=lambda pair: (-pair[1], -(pair[0].year or 0), pair[0].citation))
        return out[:top_k]

    # ── direct lookup (for citation pin-back) ──────────────────────────

    def get(self, case_id: int) -> CasePrecedent | None:
        """Look up a precedent by DB id (used by citation-link endpoints)."""
        for c in self.cases:
            if c.id == case_id:
                return c
        return None


# ──────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────


def _row_to_precedent(case: Case) -> CasePrecedent:
    """Map a SQLAlchemy ``Case`` (eager-loaded) to a ``CasePrecedent``."""
    judges: list[str] = []
    lawyers: list[str] = []
    prosecutors: list[str] = []
    for p in case.participations:
        name = p.person.canonical_name if p.person else ""
        if not name:
            continue
        if p.role == "judge":
            judges.append(name)
        elif p.role == "defense":
            lawyers.append(name)
        elif p.role == "prosecution":
            prosecutors.append(name)

    articles: list[tuple[str, str]] = []
    for a in case.articles_cited:
        if a.code and a.article:
            articles.append((a.code, a.article))

    full = case.full_text or ""
    excerpt = full[:PROMPT_SUMMARY_CHARS].strip()
    if len(full) > PROMPT_SUMMARY_CHARS:
        excerpt += "…"

    return CasePrecedent(
        id=case.id,
        court_code=case.court.code if case.court else "",
        court_name=case.court.name if case.court else "",
        court_level=case.court.level if case.court else "",
        case_number=case.case_number or "",
        decision_date=case.decision_date,
        type=case.type or "",
        subtype=case.subtype,
        outcome=case.outcome,
        summary=(case.summary or "").strip(),
        excerpt=excerpt,
        judges=judges,
        lawyers=lawyers,
        prosecutors=prosecutors,
        articles_cited=articles,
        source_url=case.source_url,
    )


def _searchable_text(p: CasePrecedent) -> str:
    """Composite text fed into BM25.

    Ordering matters for BM25 term-frequency: we keep the summary first
    (highest information density — one sentence the LLM wrote), then the
    structured signals (court, judges, articles), then a body excerpt as
    fallback for terms that appear only in the judgment body.
    """
    parts = [
        p.summary,
        p.court_name,
        p.case_number,
        p.type,
        p.subtype or "",
        " ".join(p.judges),
        " ".join(p.lawyers),
        " ".join(f"{code} {art}" for code, art in p.articles_cited),
        p.excerpt,
    ]
    return "\n".join(x for x in parts if x)


def _article_key(code: str, article: str) -> tuple[str, str]:
    return (code.strip(), _normalise_article(article))


def _normalise_article(article: str) -> str:
    return "".join((article or "").strip().lower().split())


def _court_authority_bonus(level: str) -> float:
    return {
        "kushtetuese": 0.60,
        "larte": 0.45,
        "apel": 0.20,
        "administrative": 0.18,
        "administrativ": 0.18,
        "shkalla_pare": 0.08,
        "ushtarake": 0.05,
    }.get((level or "").strip().lower(), 0.0)


def _precedent_match_bonus(
    case: CasePrecedent,
    *,
    article_hint_set: set[tuple[str, str]],
    code_hint_set: set[str],
    case_codes: set[str],
    case_articles: set[tuple[str, str]],
) -> float:
    """Structured bonus on top of BM25.

    The best precedent is not just lexically similar; it often cites the
    same article(s) and comes from a court whose authority matters more.
    These bonuses are intentionally modest: BM25 stays primary, but the
    ranking nudges toward legally stronger, more on-point cases.
    """
    bonus = _court_authority_bonus(case.court_level)

    exact_article_overlap = len(case_articles & article_hint_set)
    if exact_article_overlap:
        bonus += min(1.35, exact_article_overlap * 0.55)

    shared_codes = len(case_codes & code_hint_set)
    if shared_codes:
        bonus += min(0.45, shared_codes * 0.15)

    if case.year:
        age = max(0, date.today().year - case.year)
        bonus += max(0.0, 0.12 - min(0.12, age * 0.01))

    return bonus
