"""BM25-based article retrieval tuned for Albanian legal text.

Why BM25 instead of vector embeddings:
  * legal retrieval rewards exact term matches (articles, institutions, specific
    terminology) — BM25 excels at this;
  * zero model dependency — works on any Python version, no torch/GPU;
  * fast enough: ~6.6k short articles indexed and queried in milliseconds;
  * Claude handles the semantic/reasoning layer on top, which is where LLMs
    truly shine — the retriever only needs to give it a strong candidate set.

The index is serialised to INDEX_PATH/bm25.pkl so the bot starts instantly.
"""
from __future__ import annotations

import json
import pickle
import re
from collections.abc import Iterable
from dataclasses import asdict
from pathlib import Path

from rank_bm25 import BM25Okapi

from .config import INDEX_PATH, PROCESSED_DATA_PATH, TOP_K_ARTICLES, TOP_K_DECISIONS
from .jurisprudence_parser import Decision
from .logging_utils import get_logger
from .parser import Article

log = get_logger(__name__)

INDEX_FILE = INDEX_PATH / "bm25.pkl"
DECISIONS_INDEX_FILE = INDEX_PATH / "bm25_decisions.pkl"
ARTICLES_JSONL = PROCESSED_DATA_PATH / "all_articles.jsonl"
DECISIONS_JSONL = PROCESSED_DATA_PATH / "all_decisions.jsonl"

# Minimal Albanian stopword set. We keep most legal-relevant words (nga, për,
# në, me, pa, sipas, kundër, etj.) because they carry meaning in statutes —
# only obvious function words are removed.
STOPWORDS: frozenset[str] = frozenset({
    "a", "e", "i", "të", "ta", "atë", "ai", "ajo", "ata", "ato", "un", "unë",
    "ti", "ne", "ju", "dhe", "edhe", "ose", "apo", "është", "ishte", "janë",
    "kam", "kemi", "ka", "kanë", "do", "duhet", "nuk", "as", "më",
    "se", "sikur", "nëse", "kur", "ku", "si", "cila", "cili", "cilat", "cilët",
    "ky", "kjo", "këto", "këta", "këtij", "kësaj", "asaj", "atij", "aty",
    "këtu", "atje", "po", "jo", "pa", "deri", "qysh", "çdo",
})

TOKEN_RE = re.compile(r"[a-zçëï0-9]+", re.IGNORECASE)


def tokenize(text: str) -> list[str]:
    """Tokenize Albanian text — lowercase, keep ç/ë/ï, drop stopwords."""
    tokens = TOKEN_RE.findall(text.lower())
    return [t for t in tokens if t not in STOPWORDS and len(t) > 1]


# ── Italian tokenizer (for the IT corpus) ────────────────────────────────────
TOKEN_RE_IT = re.compile(r"[a-zàáèéìíòóùúü0-9]+", re.IGNORECASE)
STOPWORDS_IT: frozenset[str] = frozenset({
    "il", "lo", "la", "i", "gli", "le", "l", "un", "uno", "una",
    "di", "a", "da", "in", "con", "su", "per", "tra", "fra",
    "del", "dello", "della", "dei", "degli", "delle", "dell",
    "al", "allo", "alla", "ai", "agli", "alle", "all",
    "dal", "dallo", "dalla", "dai", "dagli", "dalle", "dall",
    "nel", "nello", "nella", "nei", "negli", "nelle", "nell",
    "sul", "sullo", "sulla", "sui", "sugli", "sulle", "sull",
    "col", "coi", "e", "ed", "o", "od", "ma", "che", "chi", "cui", "come", "se",
    "è", "sono", "ha", "hanno", "essere", "avere", "sia", "siano",
    "si", "ne", "ci", "vi", "questo", "questa", "questi", "queste",
    "quello", "quella", "quelli", "quelle", "anche", "ovvero", "nonché",
    "ogni", "quale", "quali", "esso", "essa", "essi", "loro",
})


def tokenize_it(text: str) -> list[str]:
    """Tokenize Italian text — lowercase, keep àèéìòù, drop Italian stopwords.
    Keeps negations (non) and legal terms."""
    tokens = TOKEN_RE_IT.findall(text.lower())
    return [t for t in tokens if t not in STOPWORDS_IT and len(t) > 1]


def tokenize_for(lang: str, text: str) -> list[str]:
    return tokenize_it(text) if (lang or "sq") == "it" else tokenize(text)


class ArticleIndex:
    """BM25 index over every article from every code."""

    def __init__(self, articles: list[Article], bm25: BM25Okapi, lang: str = "sq"):
        self.articles = articles
        self.bm25 = bm25
        self.lang = lang

    # ── construction ────────────────────────────────────────────────────────

    @classmethod
    def build(cls, articles: list[Article], lang: str = "sq") -> ArticleIndex:
        log.info("tokenising %d articles (lang=%s) ...", len(articles), lang)
        corpus = [tokenize_for(lang, a.searchable_text) for a in articles]
        log.info("building BM25 index ...")
        bm25 = BM25Okapi(corpus)
        return cls(articles, bm25, lang)

    @classmethod
    def from_jsonl(cls, path: Path = ARTICLES_JSONL, lang: str = "sq") -> ArticleIndex:
        articles: list[Article] = []
        with path.open(encoding="utf-8") as fh:
            for line in fh:
                data = json.loads(line)
                articles.append(Article(**data))
        return cls.build(articles, lang=lang)

    # ── persistence ─────────────────────────────────────────────────────────

    def save(self, path: Path = INDEX_FILE) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("wb") as fh:
            pickle.dump({"articles": [asdict(a) for a in self.articles],
                         "bm25": self.bm25,
                         "lang": getattr(self, "lang", "sq")}, fh)
        log.info("index saved to %s (%d articles)", path, len(self.articles))

    @classmethod
    def load(cls, path: Path = INDEX_FILE) -> ArticleIndex:
        with path.open("rb") as fh:
            data = pickle.load(fh)
        articles = [Article(**a) for a in data["articles"]]
        return cls(articles, data["bm25"], data.get("lang", "sq"))

    # ── querying ────────────────────────────────────────────────────────────

    def search(
        self,
        query: str,
        top_k: int = TOP_K_ARTICLES,
        include_repealed: bool = False,
        restrict_codes: Iterable[str] | None = None,
    ) -> list[tuple[Article, float]]:
        """Return (article, score) pairs sorted by BM25 score descending."""
        tokens = tokenize_for(getattr(self, "lang", "sq"), query)
        if not tokens:
            return []

        scores = self.bm25.get_scores(tokens)
        ranked = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)

        results: list[tuple[Article, float]] = []
        restrict = set(restrict_codes) if restrict_codes else None
        for idx in ranked:
            art = self.articles[idx]
            if not include_repealed and art.repealed:
                continue
            if restrict and art.code not in restrict:
                continue
            if scores[idx] <= 0:
                break
            results.append((art, float(scores[idx])))
            if len(results) >= top_k:
                break
        return results


class DecisionIndex:
    """BM25 index over parsed court decisions (jurisprudence).

    Parallel to ArticleIndex but a separate index so we can tune retrieval
    independently — articles are authoritative statutes (must be retrieved
    exhaustively), decisions are persuasive precedent (smaller top-k,
    optionally filtered by outcome/year/court).
    """

    def __init__(self, decisions: list[Decision], bm25: BM25Okapi):
        self.decisions = decisions
        self.bm25 = bm25

    # ── construction ────────────────────────────────────────────────────────

    @classmethod
    def build(cls, decisions: list[Decision]) -> DecisionIndex:
        log.info("tokenising %d decisions ...", len(decisions))
        corpus = [tokenize(d.searchable_text) for d in decisions]
        log.info("building BM25 decisions index ...")
        bm25 = BM25Okapi(corpus) if corpus else None
        return cls(decisions, bm25)

    @classmethod
    def from_jsonl(cls, path: Path = DECISIONS_JSONL) -> DecisionIndex:
        decisions: list[Decision] = []
        if not path.exists():
            log.warning("no decisions jsonl at %s — index will be empty", path)
            return cls([], None)  # type: ignore[arg-type]
        with path.open(encoding="utf-8") as fh:
            for line in fh:
                data = json.loads(line)
                data.pop("kind", None)  # Literal field — not a real constructor arg
                decisions.append(Decision(**data))
        return cls.build(decisions)

    @classmethod
    def from_unified(cls, path: Path = DECISIONS_JSONL) -> DecisionIndex:
        """Load Kushtetuese (jsonl) + Gjykata e Lartë + ECHR (Postgres) into a
        single index. Falls back to jsonl-only if Postgres is unreachable.

        This is what we want for the Precedent Pattern Analyzer — the model
        searches across the full ~1100 decisions corpus, not just one court.
        """
        decisions: list[Decision] = []
        if path.exists():
            with path.open(encoding="utf-8") as fh:
                for line in fh:
                    data = json.loads(line)
                    data.pop("kind", None)
                    decisions.append(Decision(**data))
            log.info("loaded %d Kushtetuese decisions from jsonl", len(decisions))
        try:
            pg_decisions = _load_postgres_decisions()
            decisions.extend(pg_decisions)
            log.info("loaded %d cases from Postgres legalkb", len(pg_decisions))
        except Exception as exc:  # noqa: BLE001
            log.warning("Postgres legalkb unreachable (%s) — index will be jsonl-only", exc)
        return cls.build(decisions)

    # ── persistence ─────────────────────────────────────────────────────────

    def save(self, path: Path = DECISIONS_INDEX_FILE) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("wb") as fh:
            pickle.dump({
                "decisions": [asdict(d) for d in self.decisions],
                "bm25": self.bm25,
            }, fh)
        log.info("decisions index saved to %s (%d decisions)", path, len(self.decisions))

    @classmethod
    def load(cls, path: Path = DECISIONS_INDEX_FILE) -> DecisionIndex:
        if not path.exists():
            return cls([], None)  # type: ignore[arg-type]
        with path.open("rb") as fh:
            data = pickle.load(fh)
        decisions = []
        for d in data["decisions"]:
            d.pop("kind", None)
            decisions.append(Decision(**d))
        return cls(decisions, data["bm25"])

    # ── querying ────────────────────────────────────────────────────────────

    def search(
        self,
        query: str,
        top_k: int = TOP_K_DECISIONS,
        *,
        min_score: float = 1.0,
    ) -> list[tuple[Decision, float]]:
        """Top-K decisions for a query. Empty list if index is empty.

        We apply a `min_score` floor because BM25 scores for decisions are
        typically higher than for articles (decisions have longer text →
        more term overlap by chance). We only want decisions that are
        clearly on-topic, not marginal matches added as filler.
        """
        if not self.decisions or self.bm25 is None:
            return []
        tokens = tokenize_for(getattr(self, "lang", "sq"), query)
        if not tokens:
            return []

        scores = self.bm25.get_scores(tokens)
        ranked = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)
        out: list[tuple[Decision, float]] = []
        for idx in ranked:
            s = float(scores[idx])
            if s < min_score:
                break
            out.append((self.decisions[idx], s))
            if len(out) >= top_k:
                break
        return out


# ── CLI ────────────────────────────────────────────────────────────────────

def build_and_save() -> ArticleIndex:
    index = ArticleIndex.from_jsonl()
    index.save()
    return index


def build_and_save_decisions(unified: bool = True) -> DecisionIndex:
    """Build and save the decisions BM25 index.

    Default `unified=True` merges Kushtetuese (282 from jsonl) +
    Gjykata e Lartë + ECHR Albania (~815 from Postgres legalkb) into one
    index so the Precedent Analyzer searches across the full corpus.

    Pass `unified=False` for a jsonl-only build (legacy / offline).
    """
    if unified:
        index = DecisionIndex.from_unified()
    else:
        index = DecisionIndex.from_jsonl()
    index.save()
    return index


# ── Postgres legalkb ingestion ─────────────────────────────────────────────

# Map outcomes from the Postgres extraction vocabulary (English, see
# src/extract/llm.py EXTRACTION_SCHEMA enum) to the shqip vocabulary used
# by the Kushtetuese parser. We unify so the model sees one terminology
# regardless of which court issued the decision.
_OUTCOME_MAP_EN_TO_SQ: dict[str, str] = {
    "accepted": "pranim",
    "partially_accepted": "pjesërisht",
    "rejected": "rrëzim",
    "dismissed": "pushim",
    "remanded": "kthim për rishqyrtim",
    "settled": "marrëveshje",
    "modified": "ndryshim",
    "convicted": "fajësim",
    "acquitted": "pafajësim",
    "other": "",
    "unknown": "",
}


def _load_postgres_decisions() -> list[Decision]:
    """Pull complete cases from Postgres legalkb and shape them as Decision.

    We deliberately keep the schema mapping minimal:
      - objekti        ← summary (LLM-extracted one-liner)
      - reasoning      ← full_text (capped via Decision.searchable_text)
      - cited_articles ← articles_cited rows (normalised)
      - judges         ← participations where role='judge'
      - dispositif     ← left empty (no structured operative-part field
                         in legalkb — full_text already covers it)

    Empty raw_path / missing decision_date falls through gracefully.
    """
    from sqlalchemy.orm import joinedload

    from .db import Case, session_scope

    decisions: list[Decision] = []
    with session_scope() as sess:
        q = (
            sess.query(Case)
            .options(
                joinedload(Case.court),
                joinedload(Case.articles_cited),
                joinedload(Case.participations),
            )
            .filter(Case.extraction_status == "complete")
        )
        for case in q.all():
            year = case.decision_date.year if case.decision_date else 0
            date = case.decision_date.strftime("%d.%m.%Y") if case.decision_date else ""
            court = case.court
            short_sq = _short_sq(court.code if court else "")
            citation = f"Vendimi nr. {case.case_number}/{year} i {short_sq}" if year else \
                       f"Vendimi nr. {case.case_number} i {short_sq}"
            cited = sorted({
                f"{a.code}:{a.article}" for a in case.articles_cited
                if a.code and a.article
            })
            judges = [
                p.person.canonical_name
                for p in case.participations
                if p.role == "judge" and p.person and p.person.canonical_name
            ]
            outcome_sq = _OUTCOME_MAP_EN_TO_SQ.get(
                (case.outcome or "").strip().lower(), case.outcome or ""
            )
            decisions.append(Decision(
                court_code=court.code if court else "",
                court_title_sq=court.name if court else "",
                court_short_sq=short_sq,
                year=year,
                number=str(case.case_number or ""),
                date=date,
                citation=citation,
                short_id="",
                objekti=(case.summary or "")[:800],
                kerkues="",
                subjekte_interesuara="",
                baza_ligjore="",
                judges=judges[:12],
                cited_articles=cited[:40],
                outcome=outcome_sq,
                dispositif="",
                reasoning=(case.full_text or "")[:8000],
                source_file=case.raw_path or "",
                source_url=case.source_url or "",
            ))
    return decisions


def _short_sq(court_code: str) -> str:
    """Map court_code → display string in shqip."""
    return {
        "kushtetuese": "Gjykata Kushtetuese",
        "gjykata_elarte": "Gjykata e Lartë",
        "ecthr_albania": "Gjykata Evropiane e të Drejtave të Njeriut",
        "apel_tirane": "Gjykata e Apelit Tiranë",
    }.get(court_code, court_code)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Build or query the BM25 index")
    parser.add_argument("--build", action="store_true",
                        help="Rebuild the articles index from parsed articles")
    parser.add_argument("--build-decisions", action="store_true",
                        help="Rebuild the unified decisions index (Kushtetuese jsonl + Postgres legalkb)")
    parser.add_argument("--build-decisions-jsonl-only", action="store_true",
                        help="Build decisions index from jsonl only (no Postgres lookup)")
    parser.add_argument("--query", type=str, default=None,
                        help="Test query against the articles index")
    parser.add_argument("--query-decisions", type=str, default=None,
                        help="Test query against the decisions index")
    parser.add_argument("--top", type=int, default=5,
                        help="How many results to show for --query")
    args = parser.parse_args()

    if args.build or not INDEX_FILE.exists():
        idx = build_and_save()
    else:
        idx = ArticleIndex.load()
        log.info("loaded articles index: %d articles", len(idx.articles))

    if args.build_decisions_jsonl_only:
        didx = build_and_save_decisions(unified=False)
    elif args.build_decisions or (not DECISIONS_INDEX_FILE.exists() and DECISIONS_JSONL.exists()):
        didx = build_and_save_decisions(unified=True)
    else:
        didx = DecisionIndex.load()
        log.info("loaded decisions index: %d decisions", len(didx.decisions))

    if args.query:
        print(f"\nArticle query: {args.query}\n" + "=" * 70)
        for art, score in idx.search(args.query, top_k=args.top):
            print(f"[{score:6.2f}] {art.citation}")
            print(f"         {art.heading[:80]}")
            print(f"         {art.body[:120].strip()}...")
            print()

    if args.query_decisions:
        print(f"\nDecision query: {args.query_decisions}\n" + "=" * 70)
        for dec, score in didx.search(args.query_decisions, top_k=args.top):
            print(f"[{score:6.2f}] {dec.citation} — {dec.outcome or '?'}")
            print(f"         OBJEKTI: {dec.objekti[:120]}")
            print()
