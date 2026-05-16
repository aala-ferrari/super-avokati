"""V9.4 — Bench Memo Predictor.

Single Opus call producing a judicial bench memo: how a Gjykata e Lartë
judge would frame the issue, predict the outcome, weigh both sides, and
identify argument upgrades. Reuses BM25 articles + V9.2 ratio precedents
+ court-specific calibration.
"""
from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass

from .backends import LLMBackend
from .genio import GENIO_JURISDICTION_GUARD
from .precedent import PrecedentRef, gather_precedents
from .retrieval import ArticleIndex, DecisionIndex

log = logging.getLogger(__name__)

# ── Court calibration labels ──────────────────────────────────────────

COURT_LABELS = {
    "gjykata_lartë": "Gjykata e Lartë e Republikës së Shqipërisë",
    "gjykata_apelit": "Gjykata e Apelit",
    "gjykata_shkalle1": "Gjykata e Shkallës së Parë",
    "gjykata_kushtetuese": "Gjykata Kushtetuese",
    "gjykata_administrative": "Gjykata Administrative",
    "gjykata_komerciale": "Gjykata Komerciale (Tiranë)",
    "ecthr_albania": "Gjykata Evropiane e të Drejtave të Njeriut",
}

DEFAULT_COURT = "gjykata_lartë"

# ── System prompt ─────────────────────────────────────────────────────

BENCH_SYSTEM = (
    GENIO_JURISDICTION_GUARD
    + "Je një gjyqtar shqiptar me 30 vjet eksperiencë (KC, KP, KPC, KPP, "
    "Kushtetutë, ligje sektoriale). Detyra: shkruaj një BENCH MEMO siç do "
    "ta shkruaje për veten para se të vendosësh — jo për të lavdëruar "
    "avokatin, por për të treguar SI do të mendojë gjykata. Vlerëso ftohtë "
    "të dy palët, përcakto rezultatin më të mundshëm me shifra realiste, "
    "dhe identifiko se ku do të bjerë çekani gjyqësor.\n\n"
    "RREGULLAT KRITIKE:\n"
    "1) Bazohu VETËM në nenet shqiptare dhe precedentët e dhënë në kontekst.\n"
    "2) Mos shpik citime — nëse një nen ose vendim nuk është në kontekst, mos e citosh.\n"
    "3) Probabilitetet duhet të jenë të kalibruara: shumë rrallë 90%+ ose 10%-, "
    "shumica e rasteve të vërteta janë 35-65%.\n"
    "4) Konsidero kalibrimin sipas gjykatës specifike — Kushtetuesja vendos "
    "ndryshe nga Gjykata e Lartë komerciale.\n"
    "5) Përfundo me një rekomandim të vetëm: FIGHT, SETTLE, ose FOLD.\n"
    "6) Kthe VETËM JSON të vlefshëm pa asnjë tekst tjetër para apo pas."
)

BENCH_USER_TEMPLATE = """\
═════════════════════════════════════════════
ÇËSHTJA PARA GJYKATËS
═════════════════════════════════════════════
{case_description}

═════════════════════════════════════════════
GJYKATA QË DO TË GJYKOJË
═════════════════════════════════════════════
{court_label}

═════════════════════════════════════════════
DOKUMENTET E PALËS SONË (përmbledhje)
═════════════════════════════════════════════
{documents}

═════════════════════════════════════════════
MEMORIE/PARASHTRIM I KUNDËRSHTARIT
═════════════════════════════════════════════
{opponent_filing}

═════════════════════════════════════════════
NENET SHQIPTARE PËRKATËSE (BM25 top hits)
═════════════════════════════════════════════
{articles_block}

═════════════════════════════════════════════
PRECEDENTË TË NGJASHËM (me ratio të strukturuar nga V9.2)
═════════════════════════════════════════════
{precedents_block}

═════════════════════════════════════════════

Tani shkruaj BENCH MEMO në formatin JSON:

{{
  "issue_framing": "Si do ta inkuadronte gjyqtari pyetjen kryesore (1-2 fjali, terma juridikë).",
  "applicable_law": [
    {{"reference": "Neni X i KC", "relevance": "i lartë|i mesëm|i ulët", "why": "pse ky nen është relevant"}}
  ],
  "controlling_precedents": [
    {{"citation": "Vendimi nr. X dt. Y", "court": "...", "outcome": "...", "ratio_used": "arsyetimi i transferueshëm", "weight": "i lartë|i mesëm|i ulët"}}
  ],
  "outcome_prediction": {{
    "p_plaintiff_pct": 0,
    "p_defendant_pct": 0,
    "confidence": "i lartë|i mesëm|i ulët",
    "key_factor": "Faktori që e zhvendos më shumë rezultatin",
    "court_calibration_note": "Pse kjo gjykatë specifike mund të ndryshojë rezultatin"
  }},
  "our_weaknesses": [
    {{"point": "dobësia jonë", "judge_attack": "Si do ta sulmojë gjyqtari", "severity": "i lartë|i mesëm|i ulët"}}
  ],
  "opponent_strengths": [
    {{"point": "forca e kundërshtarit", "why_judge_accepts": "Pse gjyqtari e pranon", "weight": "i lartë|i mesëm|i ulët"}}
  ],
  "argument_upgrades": [
    {{"current": "argumenti që ke", "upgrade": "si ta riformulosh", "p_shift_pct": 0}}
  ],
  "procedural_risks": [
    {{"risk": "rrezik procedural", "mitigation": "si ta shmangësh"}}
  ],
  "recommendation": "FIGHT|SETTLE|FOLD — me arsyetim të shkurtër prej 1-2 fjalish"
}}"""

# ── Data classes ──────────────────────────────────────────────────────

@dataclass
class BenchMemoInput:
    case_description: str
    documents_summary: str = ""
    opponent_filing: str = ""
    court_code: str = DEFAULT_COURT


# ── Public API ────────────────────────────────────────────────────────

def generate_bench_memo(
    inp: BenchMemoInput,
    *,
    backend: LLMBackend,
    article_index: ArticleIndex,
    decision_index: DecisionIndex | None = None,
    case_id: str | None = None,
    top_k_articles: int = 8,
    top_k_precedents: int = 6,
) -> dict:
    """Generate the judicial bench memo (single Opus call)."""

    # Retrieve articles + precedents
    articles = _retrieve_articles(article_index, inp.case_description, top_k_articles)
    precedents = gather_precedents(
        inp.case_description,
        top_k=top_k_precedents,
        decision_index=decision_index,
    )

    articles_block = _format_articles(articles) or "(asnjë nen specifik nuk u gjet)"
    precedents_block = "\n\n".join(p.to_block() for p in precedents) \
        if precedents else "(asnjë precedent i ngjashëm nuk u gjet)"

    court_label = COURT_LABELS.get(inp.court_code, inp.court_code)

    prompt = BENCH_USER_TEMPLATE.format(
        case_description=inp.case_description.strip(),
        court_label=court_label,
        documents=(inp.documents_summary or "(s'ka dokumente të ngarkuara)")[:6000],
        opponent_filing=(inp.opponent_filing or "(s'ka memorie kundërshtari)")[:6000],
        articles_block=articles_block[:5000],
        precedents_block=precedents_block[:8000],
    )

    t0 = time.monotonic()
    try:
        text = backend.complete(
            system=BENCH_SYSTEM,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=4500,
            callsite="bench_memo",
            case_id=case_id,
        )
    except Exception as exc:  # noqa: BLE001
        log.exception("bench_memo: backend error")
        return {**_empty_memo(),
                "_ms": int((time.monotonic() - t0) * 1000),
                "_parse_error": f"backend: {type(exc).__name__}: {exc}",
                "precedents_used": _serialize_precedents(precedents)}

    elapsed_ms = int((time.monotonic() - t0) * 1000)
    parsed = _extract_json(text)
    if parsed is None:
        log.warning("bench_memo: JSON parse failed")
        return {**_empty_memo(), "_raw": text[:2000], "_ms": elapsed_ms,
                "_parse_error": "JSON parse failed",
                "precedents_used": _serialize_precedents(precedents)}

    parsed["_ms"] = elapsed_ms
    parsed["precedents_used"] = _serialize_precedents(precedents)
    parsed["articles_used"] = [
        {"id": a.id, "label": getattr(a, "label", "") or getattr(a, "heading", ""),
         "code": a.code} for a, _ in articles
    ]
    return parsed


# ── Helpers ───────────────────────────────────────────────────────────

def _retrieve_articles(idx: ArticleIndex, query: str, top_k: int):
    if idx is None:
        return []
    try:
        return idx.search(query, top_k=top_k)
    except Exception:  # noqa: BLE001
        log.exception("bench_memo: article retrieval failed")
        return []


def _format_articles(hits) -> str:
    """Format article hits into prompt-ready block."""
    lines = []
    for art, score in hits:
        label = (getattr(art, "label", None) or getattr(art, "heading", None)
                 or getattr(art, "id", "?"))
        body = (getattr(art, "body", "") or getattr(art, "text", "") or "")[:400]
        lines.append(f"### {label} [{art.code}]\n{body.strip()}")
    return "\n\n".join(lines)


def _serialize_precedents(precs: list[PrecedentRef]) -> list[dict]:
    return [{
        "citation": p.citation, "court_code": p.court_code,
        "outcome": p.outcome, "objekti": p.objekti,
        "source_url": p.source_url, "bm25_score": p.bm25_score,
        "archetype": p.archetype, "has_ratio": bool(p.winning_argument),
    } for p in precs]


def _extract_json(text: str) -> dict | None:
    text = text.strip()
    m = re.search(r"```(?:json)?\s*([\s\S]+?)```", text)
    if m:
        text = m.group(1).strip()
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return None
    try:
        return json.loads(text[start:end + 1])
    except json.JSONDecodeError:
        return None


def _empty_memo() -> dict:
    return {
        "issue_framing": "",
        "applicable_law": [],
        "controlling_precedents": [],
        "outcome_prediction": {
            "p_plaintiff_pct": 0, "p_defendant_pct": 0,
            "confidence": "i ulët", "key_factor": "",
            "court_calibration_note": "",
        },
        "our_weaknesses": [],
        "opponent_strengths": [],
        "argument_upgrades": [],
        "procedural_risks": [],
        "recommendation": "",
    }
