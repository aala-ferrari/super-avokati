"""V9.2 Precedent Pattern Analyzer — what wins, what loses, what to imitate.

For a given case description (free-form Albanian text describing the
ongoing matter), this module:

  1. Retrieves the top-K most similar past decisions across the
     unified BM25 index (Kushtetuese + Gjykata e Lartë + ECHR Albania).
  2. Loads the structured ratio decidendi (``CaseAnalysis``) for each
     retrieved decision when available.
  3. Asks Opus to synthesize three actionable buckets in shqip:
       - **mosse_da_imitare** (LËVIZJE PËR T'I IMITUAR)
       - **trappole_da_evitare** (KURTHE PËR T'U SHMANGUR)
       - **kill_shot** — the single highest-leverage move if any
     plus a per-precedent annotation (why each one is relevant).

Same Albanian-only jurisdiction guard as Genio. No italo-francese
doctrine, no foreign codes — only KC/KP/KPC/KPP/Kushtetuta/ligji and
the actual case law in our index.
"""
from __future__ import annotations

import json
import os
import re
import time
from dataclasses import dataclass
from typing import Any

from .genio import GENIO_JURISDICTION_GUARD
from .logging_utils import get_logger
from .retrieval import DecisionIndex

log = get_logger(__name__)

_JURIS_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "data", "raw", "jurisprudence",
)


def _local_file(rel: str) -> str:
    """Return the jurisprudence-relative path if the raw decision file exists
    locally, else "". Guards against path traversal. Powers the download
    button — we only expose it when the file is genuinely on disk."""
    rel = (rel or "").strip().replace(chr(92), "/")
    if not rel:
        return ""
    # tolerate stale absolute/dev paths (e.g. old Mac paths): keep only the
    # portion under jurisprudence/ so the file resolves inside the container.
    marker = "jurisprudence/"
    i = rel.find(marker)
    if i >= 0:
        rel = rel[i + len(marker):]
    rel = rel.lstrip("/")
    if not rel:
        return ""
    p = os.path.normpath(os.path.join(_JURIS_DIR, rel))
    # true path-boundary check (prefix match alone would allow a sibling dir
    # like jurisprudence_backup/ to pass)
    if (p == _JURIS_DIR or p.startswith(_JURIS_DIR + os.sep)) and os.path.isfile(p):
        return os.path.relpath(p, _JURIS_DIR)
    return ""


PRECEDENT_SYSTEM = (
    GENIO_JURISDICTION_GUARD +
    "Ti je partner senior i një studio shqiptare me 25 vjet eksperiencë "
    "në litigim. Misioni: nga një grup vendimesh të kaluara mbi çështje "
    "të ngjashme, NXJERR pattern-et që përcaktuan fitoren ose humbjen "
    "dhe transferoji në çështjen aktuale të avokatit. Bazohu VETËM në "
    "vendimet që të jepen — mos shpik fakte, mos importo doktrinë të "
    "huaj. Çdo rekomanim duhet të ankorohet te një vendim specifik me "
    "citation. Output VETËM JSON sipas skemës."
)


PRECEDENT_USER_TEMPLATE = """ÇËSHTJA AKTUALE E AVOKATIT:
{case_description}

VENDIMET E NGJASHME (renditur sipas relevancës BM25):
{precedents_block}

DETYRA: Sintetizo nga këto vendime tre kova konkrete për avokatin:

1. **moves_to_imitate** — lëvizjet që fituan çështje të ngjashme. Për "
"secilën: cita vendimin specifik (nga lista lart), shpjego LËVIZJEN "
"konkrete (jo abstrakte) dhe pse ka shanse të zbatohet edhe këtu.

2. **traps_to_avoid** — gabimet që humbën çështje të ngjashme. Për "
"secilin: cita vendimin specifik, përshkruaj GABIMIN konkret dhe "
"sinjalin që e bën të rëndësishëm për çështjen aktuale.

3. **kill_shot** — nëse ekziston një lëvizje të vetme me leve të lartë "
"që mund të mbyllë çështjen (p.sh. një precedent unifikues, një "
"kundërshtim procedural fitues, një provë e munguar e kundërshtarit), "
"identifiko atë. Bosh nëse nuk ka.

4. **per_precedent** — për secilin vendim të dhënë, një frazë (≤ 120 "
"karaktere) që shpjegon pse është relevant për çështjen aktuale.

5. **divergence_warning** — nëse vendimet e ngjashme japin sinjale të "
"përziera (gjyqe që fitojnë gjysmën, humbin gjysmën), përshkruaj "
"variablin që duket të ndajë rezultatet. Bosh nëse pattern-i është "
"i qartë.

Kthe VETËM JSON të pastër me skemën:
{{
  "moves_to_imitate": [
    {{
      "cite": "Vendimi nr. X/Y i Gjykatës Z",
      "move": "1-2 fjali konkrete",
      "why_applicable": "1 fjali"
    }}
  ],
  "traps_to_avoid": [
    {{
      "cite": "Vendimi nr. X/Y i Gjykatës Z",
      "mistake": "1-2 fjali konkrete",
      "warning_signal": "1 fjali — kur kjo trapë aktivizohet"
    }}
  ],
  "kill_shot": {{
    "exists": true | false,
    "move": "1-3 fjali (bosh nëse exists=false)",
    "based_on": ["Vendimi nr. X/Y", ...]
  }},
  "per_precedent": [
    {{
      "cite": "Vendimi nr. X/Y i Gjykatës Z",
      "relevance": "≤ 120 karaktere"
    }}
  ],
  "divergence_warning": "string ose bosh"
}}"""


@dataclass
class PrecedentRef:
    """A retrieved decision + its (optional) extracted ratio."""
    citation: str
    court_code: str
    outcome: str
    objekti: str
    source_url: str
    bm25_score: float
    case_id: int | None = None  # if from legalkb
    archetype: str | None = None
    winning_argument: str | None = None
    losing_mistake: str | None = None
    dispositive_fact: str | None = None
    transferable_lesson: str | None = None
    source_file: str = ""

    def to_block(self) -> str:
        """Render the precedent as a prompt-ready block."""
        lines = [f"### {self.citation}"]
        lines.append(f"GJYKATA: {self.court_code}  |  REZULTATI: {self.outcome or 'i panjohur'}")
        if self.objekti:
            lines.append(f"OBJEKTI: {self.objekti[:400]}")
        if self.archetype:
            lines.append(f"ARKETIPI: {self.archetype}")
        if self.winning_argument:
            lines.append(f"ARG. FITUES: {self.winning_argument}")
        if self.losing_mistake:
            lines.append(f"GABIMI HUMBËS: {self.losing_mistake}")
        if self.dispositive_fact:
            lines.append(f"FAKTI VENDIMTAR: {self.dispositive_fact}")
        if self.transferable_lesson:
            lines.append(f"MËSIMI: {self.transferable_lesson}")
        return "\n".join(lines)


_EXPAND_SYSTEM = (
    "Ti je jurist shqiptar ekspert. Nga PËRSHKRIMI i rastit, nxirr fjalët-kyçe "
    "dhe konceptet juridike për të kërkuar precedentë: institute juridike, "
    "sinonime, terma teknikë dhe numra nenesh të mundshëm (Kodi Civil, Kodi i "
    "Familjes, KPC, KPP, Kushtetuta). Kthe VETËM një listë të shkurtër "
    "fjalësh/frazash të ndara me presje, në shqip — pa fjali, pa shpjegime."
)


def _expand_query(case_description: str, backend) -> str:
    """Brain-driven query expansion → legal keywords/concepts string."""
    try:
        out = backend.complete(
            system=_EXPAND_SYSTEM,
            messages=[{"role": "user", "content": case_description.strip()[:2000]}],
            max_tokens=250, fast=True, callsite="precedent_expand",
        )
        return (out or "").strip().replace("\n", " ")
    except Exception as exc:  # noqa: BLE001
        log.warning("precedent: query expansion failed (%s)", exc)
        return ""


_RERANK_SYSTEM = (
    "Ti je jurist shqiptar. Ke një RAST dhe një listë vendimesh kandidatë. "
    "Zgjidh vetëm vendimet VËRTET relevante juridikisht (i njëjti institut ose "
    "problem i ngjashëm), të renditura nga më relevanti te më pak. Injoro ato "
    "që përkojnë vetëm me fjalë procedurale të përgjithshme. Kthe VETËM JSON: "
    '{"rank": [indekset e plota me radhë sipas relevancës]}'
)


def _rerank(case_description: str, candidates, backend, top_k: int):
    """LLM re-rank of BM25 candidates by true legal relevance.
    candidates: list[(Decision, score)]. Falls back to BM25 order on failure."""
    if len(candidates) <= top_k:
        return candidates
    lines = []
    for i, (d, _sc) in enumerate(candidates):
        obj = (d.objekti or "")[:200]
        lines.append(f"[{i}] {d.citation} | {d.outcome or '?'} | {obj}")
    prompt = (
        "RASTI:\n" + case_description.strip()[:1500]
        + "\n\nKANDIDATËT:\n" + "\n".join(lines)
        + f"\n\nKthe {top_k} indekset më relevante, JSON."
    )
    try:
        out = backend.complete(
            system=_RERANK_SYSTEM,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=250, fast=True, callsite="precedent_rerank",
        )
        data, _err = _extract_json(out)
        idxs = (data or {}).get("rank") or []
        picked, seen = [], set()
        for i in idxs:
            if isinstance(i, int) and 0 <= i < len(candidates) and i not in seen:
                picked.append(candidates[i]); seen.add(i)
        # top up with remaining BM25 order so we always return top_k
        for j, c in enumerate(candidates):
            if len(picked) >= top_k:
                break
            if j not in seen:
                picked.append(c)
        return picked[:top_k]
    except Exception as exc:  # noqa: BLE001
        log.warning("precedent: rerank failed (%s)", exc)
        return candidates[:top_k]


def gather_precedents(case_description: str, *, top_k: int = 5,
                      decision_index: DecisionIndex | None = None,
                      backend=None) -> list[PrecedentRef]:
    """BM25 retrieve top-K decisions for the case + load their ratio analyses.

    The ratio is best-effort — decisions without a CaseAnalysis row still
    return as a PrecedentRef with the structured fields empty (the
    synthesizer can still cite them based on objekti+outcome alone, but
    the brief will be deeper when the ratio is present).
    """
    didx = decision_index if decision_index is not None else DecisionIndex.load()
    if backend is not None:
        # Semantic hybrid: expand the query with legal concepts, cast a wider
        # BM25 net, then let the brain re-rank by true legal relevance.
        expanded = _expand_query(case_description, backend)
        query = (case_description + "  " + expanded).strip() if expanded else case_description
        pool = didx.search(query, top_k=max(top_k * 4, 24), min_score=0.3)
        if not pool:  # expansion drifted — retry with the raw case
            pool = didx.search(case_description, top_k=max(top_k * 4, 24), min_score=0.3)
        hits = _rerank(case_description, pool, backend, top_k) if pool else []
        log.info("precedent: semantic retrieval — pool=%d → top_k=%d", len(pool), len(hits))
    else:
        hits = didx.search(case_description, top_k=top_k, min_score=0.5)
    if not hits:
        return []

    refs: list[PrecedentRef] = []
    # Bulk-load case_analyses for the legalkb decisions among hits.
    legalkb_keys = []  # list of (court_code, case_number) for the postgres-sourced hits
    for d, _ in hits:
        if d.court_code in ("gjykata_elarte", "ecthr_albania"):
            legalkb_keys.append((d.court_code, d.number))

    analyses_by_key: dict[tuple[str, str], dict] = {}
    if legalkb_keys:
        try:
            from sqlalchemy import select

            from .db import Case, CaseAnalysis, Court, session_scope
            with session_scope() as sess:
                # Fetch cases by (court_code, case_number) via join — small set
                # so we just fetch all and filter in memory.
                court_codes = list({k[0] for k in legalkb_keys})
                rows = sess.execute(
                    select(Case, CaseAnalysis, Court)
                    .join(Court, Court.id == Case.court_id)
                    .outerjoin(CaseAnalysis, CaseAnalysis.case_id == Case.id)
                    .where(Court.code.in_(court_codes))
                    .where(Case.case_number.in_([k[1] for k in legalkb_keys]))
                ).all()
                for case, analysis, court in rows:
                    if analysis is None:
                        continue
                    analyses_by_key[(court.code, case.case_number)] = {
                        "case_id": case.id,
                        "archetype": analysis.case_archetype,
                        "winning_argument": analysis.winning_argument,
                        "losing_mistake": analysis.losing_mistake,
                        "dispositive_fact": analysis.dispositive_fact,
                        "transferable_lesson": analysis.transferable_lesson,
                    }
        except Exception as exc:  # noqa: BLE001
            log.warning("precedent: case_analyses fetch failed (%s) — refs will lack ratio", exc)

    for d, score in hits:
        analysis = analyses_by_key.get((d.court_code, d.number))
        refs.append(PrecedentRef(
            citation=d.citation,
            court_code=d.court_code,
            outcome=d.outcome or "",
            objekti=d.objekti or "",
            source_url=d.source_url or "",
            source_file=_local_file(getattr(d, "source_file", "") or ""),
            bm25_score=score,
            case_id=analysis["case_id"] if analysis else None,
            archetype=analysis["archetype"] if analysis else None,
            winning_argument=analysis["winning_argument"] if analysis else None,
            losing_mistake=analysis["losing_mistake"] if analysis else None,
            dispositive_fact=analysis["dispositive_fact"] if analysis else None,
            transferable_lesson=analysis["transferable_lesson"] if analysis else None,
        ))
    return refs


def synthesize(case_description: str, refs: list[PrecedentRef], *,
               backend, case_id: str | None = None) -> dict[str, Any]:
    """Call Opus with the precedents block; return parsed JSON or text fallback.

    Returns:
        {
            "moves_to_imitate": [...],
            "traps_to_avoid": [...],
            "kill_shot": {...},
            "per_precedent": [...],
            "divergence_warning": str,
            "_raw": str (always),
            "_ms": int,
            "_parse_error": str | None,
        }
    """
    if not refs:
        return {
            "moves_to_imitate": [], "traps_to_avoid": [],
            "kill_shot": {"exists": False, "move": "", "based_on": []},
            "per_precedent": [], "divergence_warning": "",
            "_raw": "", "_ms": 0,
            "_parse_error": "no precedents found in BM25 index",
        }

    precedents_block = "\n\n".join(r.to_block() for r in refs)
    prompt = PRECEDENT_USER_TEMPLATE.format(
        case_description=case_description.strip(),
        precedents_block=precedents_block,
    )

    t0 = time.monotonic()
    try:
        text = backend.complete(
            system=PRECEDENT_SYSTEM,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=3500,
            callsite="precedent_analyzer",
            case_id=case_id,
        )
    except Exception as exc:  # noqa: BLE001
        return {
            "moves_to_imitate": [], "traps_to_avoid": [],
            "kill_shot": {"exists": False, "move": "", "based_on": []},
            "per_precedent": [], "divergence_warning": "",
            "_raw": "", "_ms": int((time.monotonic() - t0) * 1000),
            "_parse_error": f"backend error: {type(exc).__name__}: {exc}",
        }

    elapsed_ms = int((time.monotonic() - t0) * 1000)
    parsed, err = _extract_json(text)
    if parsed is None:
        return {
            "moves_to_imitate": [], "traps_to_avoid": [],
            "kill_shot": {"exists": False, "move": "", "based_on": []},
            "per_precedent": [], "divergence_warning": "",
            "_raw": text, "_ms": elapsed_ms, "_parse_error": err,
        }

    parsed.setdefault("moves_to_imitate", [])
    parsed.setdefault("traps_to_avoid", [])
    parsed.setdefault("kill_shot", {"exists": False, "move": "", "based_on": []})
    parsed.setdefault("per_precedent", [])
    parsed.setdefault("divergence_warning", "")
    parsed["_raw"] = text
    parsed["_ms"] = elapsed_ms
    parsed["_parse_error"] = None
    return parsed


def analyze(case_description: str, *, backend, top_k: int = 5,
            case_id: str | None = None,
            decision_index: DecisionIndex | None = None) -> dict[str, Any]:
    """Convenience: gather + synthesize. Returns the brief dict."""
    refs = gather_precedents(case_description, top_k=top_k, decision_index=decision_index, backend=backend)
    brief = synthesize(case_description, refs, backend=backend, case_id=case_id)
    brief["precedents"] = [
        {
            "citation": r.citation,
            "court_code": r.court_code,
            "outcome": r.outcome,
            "objekti": r.objekti,
            "source_url": r.source_url,
            "download": r.source_file or None,
            "bm25_score": round(r.bm25_score, 2),
            "archetype": r.archetype,
            "has_ratio": r.winning_argument is not None,
        }
        for r in refs
    ]
    return brief


# ── helpers ─────────────────────────────────────────────────────────────

_JSON_RE = re.compile(r"\{[\s\S]*\}", re.MULTILINE)


def _extract_json(text: str) -> tuple[dict | None, str | None]:
    """Best-effort JSON extraction from a model response."""
    if not text or not text.strip():
        return None, "empty response"
    # Direct parse
    try:
        return json.loads(text), None
    except json.JSONDecodeError:
        pass
    # Code-fence stripped
    stripped = re.sub(r"^```(?:json)?\s*|```\s*$", "", text.strip(),
                      flags=re.MULTILINE)
    try:
        return json.loads(stripped), None
    except json.JSONDecodeError:
        pass
    # First {...} block
    m = _JSON_RE.search(text)
    if m:
        try:
            return json.loads(m.group(0)), None
        except json.JSONDecodeError as exc:
            return None, f"JSON decode failed: {exc}"
    return None, "no JSON object found in response"
