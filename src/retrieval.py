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
from dataclasses import asdict
from pathlib import Path
from typing import Iterable

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
    "janë", "kam", "kemi", "ka", "kanë", "do", "duhet", "nuk", "as", "më",
    "se", "sikur", "nëse", "kur", "ku", "si", "cila", "cili", "cilat", "cilët",
    "ky", "kjo", "këto", "këta", "këtij", "kësaj", "asaj", "atij", "aty",
    "këtu", "atje", "un", "po", "jo", "pa", "deri", "qysh", "çdo",
})

TOKEN_RE = re.compile(r"[a-zçëï0-9]+", re.IGNORECASE)


def tokenize(text: str) -> list[str]:
    """Tokenize Albanian text — lowercase, keep ç/ë/ï, drop stopwords."""
    tokens = TOKEN_RE.findall(text.lower())
    return [t for t in tokens if t not in STOPWORDS and len(t) > 1]


class ArticleIndex:
    """BM25 index over every article from every code."""

    def __init__(self, articles: list[Article], bm25: BM25Okapi):
        self.articles = articles
        self.bm25 = bm25

    # ── construction ────────────────────────────────────────────────────────

    @classmethod
    def build(cls, articles: list[Article]) -> "ArticleIndex":
        log.info("tokenising %d articles ...", len(articles))
        corpus = [tokenize(a.searchable_text) for a in articles]
        log.info("building BM25 index ...")
        bm25 = BM25Okapi(corpus)
        return cls(articles, bm25)

    @classmethod
    def from_jsonl(cls, path: Path = ARTICLES_JSONL) -> "ArticleIndex":
        articles: list[Article] = []
        with path.open(encoding="utf-8") as fh:
            for line in fh:
                data = json.loads(line)
                articles.append(Article(**data))
        return cls.build(articles)

    # ── persistence ─────────────────────────────────────────────────────────

    def save(self, path: Path = INDEX_FILE) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("wb") as fh:
            pickle.dump({"articles": [asdict(a) for a in self.articles],
                         "bm25": self.bm25}, fh)
        log.info("index saved to %s (%d articles)", path, len(self.articles))

    @classmethod
    def load(cls, path: Path = INDEX_FILE) -> "ArticleIndex":
        with path.open("rb") as fh:
            data = pickle.load(fh)
        articles = [Article(**a) for a in data["articles"]]
        return cls(articles, data["bm25"])

    # ── querying ────────────────────────────────────────────────────────────

    def search(
        self,
        query: str,
        top_k: int = TOP_K_ARTICLES,
        include_repealed: bool = False,
        restrict_codes: Iterable[str] | None = None,
    ) -> list[tuple[Article, float]]:
        """Return (article, score) pairs sorted by BM25 score descending."""
        tokens = tokenize(query)
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
    def build(cls, decisions: list[Decision]) -> "DecisionIndex":
        log.info("tokenising %d decisions ...", len(decisions))
        corpus = [tokenize(d.searchable_text) for d in decisions]
        log.info("building BM25 decisions index ...")
        bm25 = BM25Okapi(corpus) if corpus else None
        return cls(decisions, bm25)

    @classmethod
    def from_jsonl(cls, path: Path = DECISIONS_JSONL) -> "DecisionIndex":
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
    def load(cls, path: Path = DECISIONS_INDEX_FILE) -> "DecisionIndex":
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
        tokens = tokenize(query)
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


def build_and_save_decisions() -> DecisionIndex:
    index = DecisionIndex.from_jsonl()
    index.save()
    return index


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Build or query the BM25 index")
    parser.add_argument("--build", action="store_true",
                        help="Rebuild the articles index from parsed articles")
    parser.add_argument("--build-decisions", action="store_true",
                        help="Rebuild the decisions index from parsed decisions")
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

    if args.build_decisions or (not DECISIONS_INDEX_FILE.exists() and DECISIONS_JSONL.exists()):
        didx = build_and_save_decisions()
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
