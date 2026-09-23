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

import os
import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import date

from rank_bm25 import BM25Okapi
from sqlalchemy.orm import selectinload

from src.config import TOP_K_DECISIONS
from src.db import Case, Participation, session_scope
from src.logging_utils import get_logger
from src.retrieval import tokenize  # reuse Albanian tokenizer

log = get_logger(__name__)


# Characters of full_text included in the BM25 corpus. Full decisions can
# be 50-200 KB; the first ~1200 chars usually contain the court header,
# case number, parties, and the "OBJEKTI" section — high-signal for
# matching. Loading the whole body would 10× RAM for marginal recall.
BM25_BODY_CHARS = 1200
DENSE_MIN_COS = float(os.environ.get("DENSE_MIN_COS", "0.5"))   # v9.353: soglia per un precedente portato solo dal senso
# v9.372 — misurati sul set di 22 temi (tools/eval_precedenti.py): peso della lista densa nella fusione e peso del
# legame «il precedente cita i nene recuperati» (prima calcolato ma IGNORATO nell'ordine ibrido)
DENSE_WEIGHT_DEC = float(os.environ.get("DENSE_WEIGHT_DEC", "1.0"))
HINT_WEIGHT_DEC = float(os.environ.get("HINT_WEIGHT_DEC", "0.01"))
# l'area del triage → il Kolegji della Gjykata e Lartë che la giudica (familja, puna, detari → Civil; dogana,
# zgjedhjet, qarkullimi → Administrativ). Kushtetuese, CEDU e Kolegjet e Bashkuara passano sempre il filtro.
_KOLEGJI_PER_TYPE = {"familje": "civil", "pune": "civil", "detar": "civil", "ajror": "civil",
                     "doganor": "administrativ", "zgjedhor": "administrativ", "rrugor": "administrativ"}

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
    source_file: str = ""

    @property
    def year(self) -> int | None:
        return self.decision_date.year if self.decision_date else None

    @property
    def citation(self) -> str:
        """Short human-readable citation for logs & quick rendering."""
        n = str(self.case_number or "")
        # v9.367: «00-2023-1078/2023» ripeteva l'anno già dentro il numero della Gjykata e Lartë
        yr = "" if (not self.year or f"-{self.year}-" in n or n.endswith(f"/{self.year}")) else f"/{self.year}"
        return f"{self.court_name}, nr. {n}{yr}"


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
    def load(cls) -> LegalKBRetriever:
        """Pull all ``complete`` cases from Postgres and build the index.

        Only ``extraction_status='complete'`` cases are indexed — pending
        and failed rows lack the structured metadata the retriever needs
        (outcome, judges, articles cited).
        """
        precedents: list[CasePrecedent] = []
        try:
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
        except Exception as exc:  # noqa: BLE001
            log.info("legalkb: Postgres unavailable (%s) — using local decisions index (expected in production)", exc)
            precedents = []
        if not precedents:
            # Production path: no Postgres. Load the live decisions corpus
            # (bm25_decisions.pkl) so inline precedents work in every answer.
            precedents = _load_precedents_from_pickle()
        if not precedents:
            log.warning("legalkb retriever: no complete cases found — returning empty index")
            return cls([], BM25Okapi([["placeholder"]]))  # empty-but-valid BM25
        corpus = [tokenize(_searchable_text(p), fold=True) for p in precedents]   # v9.367: senza dieresi, come la query
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
            tokens = tokenize(q, fold=True)
            if not tokens:
                continue
            scores = self.bm25.get_scores(tokens)
            for i, s in enumerate(scores):
                if s > best.get(i, 0.0):
                    best[i] = float(s)

        candidates = sorted(best.items(), key=lambda kv: kv[1], reverse=True)
        # v9.353 (roadmap v4, punto 5) — il caso più simile per SENSO: fusione per rango (RRF) fra il
        # BM25 di sopra e la ricerca densa sui precedenti; un caso portato SOLO dal senso entra se la
        # somiglianza è alta (DENSE_MIN_COS). Senza embedding: tutto come prima (fail-silent).
        _fused: dict[int, float] = {}
        _dense_cos: dict[int, float] = {}
        try:
            from . import dense as _dn
            _dd = _dn.precedenti(self)
            if _dd is not None:
                _bm_rank = [i for i, s in candidates if s >= min_score][:_dn.DEPTH]
                for q in queries:
                    _dr = _dd.search(q)
                    for r, i in enumerate(_bm_rank, 1):
                        _fused[i] = _fused.get(i, 0.0) + 1.0 / (_dn.RRF_K + r)
                    for r, (i, cos) in enumerate(_dr, 1):
                        _fused[i] = _fused.get(i, 0.0) + DENSE_WEIGHT_DEC / (_dn.RRF_K + r)
                        _dense_cos[i] = max(_dense_cos.get(i, 0.0), cos)
        except Exception as exc:  # noqa: BLE001
            log.warning("dense: precedenti — ricerca fallita (non-fatal): %s", exc)
        if _fused:
            candidates = [(i, best.get(i, 0.0)) for i in sorted(_fused, key=lambda i: -_fused[i])]

        out: list[tuple[CasePrecedent, float]] = []
        for idx, score in candidates:
            if score < min_score:
                if not _fused:
                    break                   # BM25 puro: ordinati per punteggio, sotto la soglia non c'è altro
                if _dense_cos.get(idx, 0.0) < DENSE_MIN_COS:
                    continue
            c = self.cases[idx]
            # v9.372: il tipo è il Kolegji della Gjykata e Lartë (penal/civil/administrativ); Kushtetuese e CEDU valgono
            # per ogni materia e non si filtrano mai via
            if type and c.court_code == "gjykata_elarte" and c.type != "bashkuara" \
                    and c.type != _KOLEGJI_PER_TYPE.get(type, type):
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

        if not _fused:
            out.sort(key=lambda pair: (-pair[1], -(pair[0].year or 0), pair[0].citation))
        elif HINT_WEIGHT_DEC and article_hint_set:
            _pos = {id(c): i for i, c in enumerate(self.cases)}
            def _k(pair):
                i = _pos[id(pair[0])]
                ov = len(self._cited_articles_per_case[i] & article_hint_set)
                return -(_fused.get(i, 0.0) + HINT_WEIGHT_DEC * min(3, ov))
            out.sort(key=_k)
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


def _pickle_norm_file(rel: str) -> str:
    """Strip stale absolute/dev prefixes -> jurisprudence-relative path."""
    rel = (rel or "").strip().replace("\\", "/")
    i = rel.find("jurisprudence/")
    if i >= 0:
        rel = rel[i + len("jurisprudence/"):]
    return rel.lstrip("/")


def _pickle_to_precedent(d: dict, idx: int) -> CasePrecedent:
    """Map a bm25_decisions.pkl decision dict -> CasePrecedent (id = idx+1)."""
    from datetime import datetime
    dt = None
    raw = str(d.get("date") or "").strip()
    for fmt in ("%d.%m.%Y", "%Y-%m-%d", "%Y.%m.%d"):
        try:
            dt = datetime.strptime(raw, fmt).date()
            break
        except ValueError:
            continue
    court_code = d.get("court_code") or ""
    level = {"kushtetuese": "kushtetues", "gjykata_elarte": "larte",
             "ecthr_albania": "cedu"}.get(court_code, court_code)
    excerpt = (d.get("reasoning") or d.get("dispositif") or "")[:PROMPT_SUMMARY_CHARS].strip()
    # v9.366 — i nene citati con il codice («kodi_proc_penale:432») diventano coppie (code, art): prima
    # venivano buttati (articles_cited=[]), e il filtro «precedente solo se cita un nene recuperato»
    # non poteva mai combaciare. I numeri nudi («432») restano fuori: senza codice non si legano.
    arts: list[tuple[str, str]] = []
    for s in (d.get("cited_articles") or []):
        if isinstance(s, str) and ":" in s:
            code, art = s.split(":", 1)
            if code.strip() and art.strip() and (code.strip(), art.strip()) not in arts:
                arts.append((code.strip(), art.strip()))
    # v9.367: l'esito letterale della Gjykata e Lartë («[prishje + lënia në fuqi]») viaggia come `subtype`, così la
    # scheda e il prompt non mostrano un nudo «pranim» che l'avvocato può leggere al contrario
    _disp = d.get("dispositif") or ""
    _label = _disp[1:_disp.find("]")].strip() if _disp.startswith("[") and "]" in _disp else None
    # v9.372: `type` era «decision» per tutti i 3.996 → il filtro per area del cervello tornava SEMPRE vuoto
    # (la citazione della GjL porta sempre il Kolegji: «… i Gjykatës së Lartë (Kolegji Civil)»)
    _cit = d.get("citation") or ""
    if court_code == "kushtetuese":
        _type = "kushtetues"
    elif court_code == "ecthr_albania":
        _type = "cedu"
    elif "Bashkuara" in _cit:
        _type = "bashkuara"
    elif "Kolegji Penal" in _cit:
        _type = "penal"
    elif "Kolegji Administrativ" in _cit:
        _type = "administrativ"
    elif "Kolegji Civil" in _cit:
        _type = "civil"
    else:
        _type = "decision"
    p = CasePrecedent(
        id=idx + 1,
        court_code=court_code,
        court_name=d.get("court_short_sq") or d.get("court_title_sq") or "",
        court_level=level,
        case_number=str(d.get("number") or ""),
        decision_date=dt,
        type=_type,
        subtype=_label or None,
        outcome=d.get("outcome") or None,
        summary=(d.get("objekti") or "").strip(),
        excerpt=excerpt,
        judges=[j for j in (d.get("judges") or []) if isinstance(j, str)],
        lawyers=[], prosecutors=[],
        articles_cited=arts,
        source_url=d.get("source_url") or None,
        source_file=_pickle_norm_file(d.get("source_file") or ""),
    )
    # v9.367: il BM25 dei precedenti legge il ragionamento VERO (dal Kolegji) e il dispositivo, non 500 chr di testa
    p._bm25_text = " ".join(x for x in ((d.get("objekti") or ""), _disp, (d.get("reasoning") or "")[:3000]) if x)
    # v9.372: le CEDU sono in inglese/francese e l'avvocato cerca in shqip («tortura në polici») → per le parole si
    # aggiunge il NOME albanese degli articoli della Convenzione che la decisione cita (dai metadati HUDOC). Solo
    # per la ricerca: nulla di questo si mostra.
    if court_code == "ecthr_albania":
        _gl = []
        for code, art in arts:
            if code == "convention":
                _k = "-".join(art.split("-")[:2]) if art.startswith("P") else art.split("-")[0]
                if _k in _KONVENTA_SQ and _KONVENTA_SQ[_k] not in _gl:
                    _gl.append(_KONVENTA_SQ[_k])
        if _gl:
            p._bm25_text += " " + " ".join(_gl)
    return p


_KONVENTA_SQ = {
    "2": "e drejta për jetën vrasje vdekje",
    "3": "ndalimi i torturës tortura trajtim çnjerëzor poshtërues keqtrajtim dhunë",
    "4": "ndalimi i skllavërisë dhe punës së detyruar",
    "5": "e drejta e lirisë dhe e sigurisë arrest paraburgim ndalim burgim i padrejtë",
    "6": "e drejta për një proces të rregullt gjykatë e paanshme afat i arsyeshëm zgjatja e procesit ekzekutimi i vendimit gjyqësor të formës së prerë arsyetimi i vendimit",
    "7": "asnjë dënim pa ligj",
    "8": "e drejta e respektimit të jetës private dhe familjare banesa korrespondenca",
    "9": "liria e mendimit ndërgjegjes dhe fesë",
    "10": "liria e shprehjes",
    "11": "liria e tubimit dhe e organizimit",
    "13": "e drejta për një mjet efektiv ankimi",
    "14": "ndalimi i diskriminimit",
    "P1-1": "mbrojtja e pronës shpronësim kompensimi i pronarëve kthimi i pronës",
    "P1-3": "e drejta për zgjedhje të lira",
    "P4-2": "liria e lëvizjes",
    "P7-4": "e drejta për të mos u gjykuar ose dënuar dy herë",
    "35": "kushtet e pranueshmërisë shterimi i mjeteve të brendshme",
}


def _load_precedents_from_pickle() -> list[CasePrecedent]:
    """Load the live decisions corpus when Postgres is absent."""
    import pickle
    from pathlib import Path
    path = (Path(__file__).resolve().parent.parent
            / "data" / "index" / "bm25_decisions.pkl")
    if not path.exists():
        return []
    try:
        with open(path, "rb") as fh:
            data = pickle.load(fh)
        decs = data.get("decisions", []) if isinstance(data, dict) else []
    except Exception as exc:  # noqa: BLE001
        log.warning("legalkb: decisions pickle load failed (%s)", exc)
        return []
    return [_pickle_to_precedent(d, i) for i, d in enumerate(decs)]


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
        getattr(p, "_bm25_text", None) or p.excerpt,
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
