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
import re
import time
from dataclasses import dataclass
from typing import Any

from .genio import GENIO_JURISDICTION_GUARD
from .logging_utils import get_logger
from .retrieval import DecisionIndex

log = get_logger(__name__)


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


def gather_precedents(case_description: str, *, top_k: int = 5,
                      decision_index: DecisionIndex | None = None) -> list[PrecedentRef]:
    """BM25 retrieve top-K decisions for the case + load their ratio analyses.

    The ratio is best-effort — decisions without a CaseAnalysis row still
    return as a PrecedentRef with the structured fields empty (the
    synthesizer can still cite them based on objekti+outcome alone, but
    the brief will be deeper when the ratio is present).
    """
    didx = decision_index if decision_index is not None else DecisionIndex.load()
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
    refs = gather_precedents(case_description, top_k=top_k, decision_index=decision_index)
    brief = synthesize(case_description, refs, backend=backend, case_id=case_id)
    brief["precedents"] = [
        {
            "citation": r.citation,
            "court_code": r.court_code,
            "outcome": r.outcome,
            "objekti": r.objekti,
            "source_url": r.source_url,
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
