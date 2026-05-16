"""V9.6 — Ratio Coach.

After a case closes (won/lost/settled), Opus extracts a structured
"lesson" — what worked, what didn't, the dispositive factor, the
transferable lesson — and stores it. When a NEW case opens that resembles
a past archetype, we surface the top-3 most relevant past lessons before
the lawyer makes the same mistake or repeats the same winning move.
"""
from __future__ import annotations

import json
import logging
import re
import time
from collections import Counter
from dataclasses import dataclass

from .backends import LLMBackend
from .genio import GENIO_JURISDICTION_GUARD

log = logging.getLogger(__name__)

OUTCOMES = ("fituar", "humbur", "marrëveshje", "tërhequr", "i hapur")
DEFAULT_OUTCOME = "fituar"

# ── Post-mortem prompt ────────────────────────────────────────────────

_POSTMORTEM_SYSTEM = (
    GENIO_JURISDICTION_GUARD
    + "Je mentor i avokatëve shqiptarë, ekspert në post-mortem të rasteve. "
    "Detyra: nga konteksti i një rasti të mbyllur, ekstrakto mësime "
    "STRUKTURORE që mund t'i transferosh në raste të tjera të ardhshme. "
    "Mos u kufizo në fakte specifike — kërko parime të transferueshme. "
    "Kthe VETËM JSON të vlefshëm pa asnjë tekst tjetër para apo pas."
)

_POSTMORTEM_TEMPLATE = """\
═══════════════════════════════════════════════
RASTI I MBYLLUR
═══════════════════════════════════════════════
Titulli: {case_title}
Rezultati: {outcome}
Përshkrim shtesë (nga avokati): {summary_hint}

═══════════════════════════════════════════════
HISTORIKU I BISEDIMIT (deri 25 mesazhe të fundit)
═══════════════════════════════════════════════
{conversation}

═══════════════════════════════════════════════
DOKUMENTET KYÇE TË FASCIKULIT
═══════════════════════════════════════════════
{documents}

═══════════════════════════════════════════════

Tani ekstrakto mësimet. Kthe VETËM JSON me skemën:

{{
  "archetype": "Përshkrim 3-6 fjalësh i tipit të rastit (p.sh. 'kontestim divorci për shkak ekonomik', 'padi rikthim posedimi tokë komuniste', 'mosrespektim kushti suspensiv')",
  "what_worked": [
    "Lëvizja konkrete që funksionoi 1",
    "Lëvizja konkrete që funksionoi 2",
    ... (deri 4 sende, ose [] nëse asgjë nuk funksionoi)
  ],
  "what_failed": [
    "Gabimi ose mungesa konkrete 1",
    ... (deri 4 sende, ose [] nëse pa gabime)
  ],
  "dispositive_factor": "Faktori i vetëm që e zgjidhi rastin (1 fjali, konkret).",
  "transferable_lesson": "Mësimi i përgjithshëm që e transferon në çdo rast të ngjashëm (1-2 fjali, parim, jo fakt specifik).",
  "opponent_strategy": "Strategjia që përdori kundërshtari, nëse u identifikua (1 fjali ose null).",
  "applicable_codes": ["KC", "KP", ...],
  "key_articles": ["Neni 248 KC", ...],
  "warning_signs_for_future": [
    "Sinjal i hershëm që do ta kërkoja në raste të ngjashme në të ardhmen",
    ... (deri 3 sende)
  ]
}}"""

_POSTMORTEM_SCHEMA = {
    "archetype": "",
    "what_worked": [],
    "what_failed": [],
    "dispositive_factor": "",
    "transferable_lesson": "",
    "opponent_strategy": None,
    "applicable_codes": [],
    "key_articles": [],
    "warning_signs_for_future": [],
}


@dataclass
class PostmortemInput:
    case_title: str
    outcome: str  # one of OUTCOMES
    summary_hint: str = ""
    conversation: str = ""
    documents: str = ""


def case_postmortem(inp: PostmortemInput, *, backend: LLMBackend,
                    case_id: str | None = None) -> dict:
    """Run the structured post-mortem (single Opus call)."""
    prompt = _POSTMORTEM_TEMPLATE.format(
        case_title=inp.case_title or "(pa titull)",
        outcome=inp.outcome,
        summary_hint=inp.summary_hint or "(asgjë e shkruar)",
        conversation=(inp.conversation or "(s'ka histori bisedimi)")[:8000],
        documents=(inp.documents or "(s'ka dokumente)")[:4000],
    )
    t0 = time.monotonic()
    try:
        raw = backend.complete(
            system=_POSTMORTEM_SYSTEM,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=2200,
            callsite="ratio_coach_postmortem",
            case_id=case_id,
        )
    except Exception as exc:  # noqa: BLE001
        log.exception("ratio_coach: backend error")
        return {**_POSTMORTEM_SCHEMA,
                "_ms": int((time.monotonic() - t0) * 1000),
                "_parse_error": str(exc)}

    elapsed_ms = int((time.monotonic() - t0) * 1000)
    parsed = _extract_json(raw)
    if parsed is None:
        return {**_POSTMORTEM_SCHEMA, "_raw": raw[:1500], "_ms": elapsed_ms,
                "_parse_error": "JSON parse failed"}

    # backfill missing keys
    for k, v in _POSTMORTEM_SCHEMA.items():
        parsed.setdefault(k, v if not isinstance(v, list) else list(v))
    parsed["_ms"] = elapsed_ms
    return parsed


# ── Lesson surfacing (relevance match) ────────────────────────────────

@dataclass
class LessonMatch:
    lesson_id: int
    case_id: str
    archetype: str
    transferable_lesson: str
    relevance_score: float
    overlap_terms: list[str]
    outcome: str


_TOKEN_RE = re.compile(r"[a-zA-ZçëÇË]{4,}")
_STOPWORDS = {
    "është", "ishin", "është", "shumë", "është", "duhet", "këtë", "këto",
    "atë", "ata", "ato", "një", "dhe", "për", "është", "siç", "kemi",
    "kanë", "deri", "nuk", "mos", "ose", "edhe", "kur", "ku", "si",
    "secili", "njëri", "veç", "vetëm", "ende", "tashmë", "ndaj", "kur",
}


def _tokenize(text: str) -> set[str]:
    return {
        t.lower() for t in _TOKEN_RE.findall(text or "")
        if t.lower() not in _STOPWORDS
    }


def surface_lessons(
    case_description: str,
    stored_lessons: list[dict],
    *,
    top_k: int = 3,
    threshold: float = 0.08,
) -> list[LessonMatch]:
    """Return the top-K most relevant past lessons for a new case description.

    stored_lessons: rows from list_case_lessons() — each must have
    keys: id, case_id, archetype, transferable_lesson, lesson_json, outcome.
    """
    if not stored_lessons:
        return []

    case_tokens = _tokenize(case_description)
    if not case_tokens:
        return []

    # Extract code / article references from the new description
    case_codes = {c.upper() for c in re.findall(r"\b(K[CP]C?|KP[CP]?|KFamiljes|KPunes|Kushtetuta)\b", case_description, re.I)}
    case_arts = set(re.findall(r"(?i)Neni\s+\d+(?:[/.\-]\d+)*", case_description))

    matches: list[LessonMatch] = []
    for L in stored_lessons:
        meta = L.get("lesson_json") or L
        if isinstance(meta, str):
            try:
                meta = json.loads(meta)
            except (json.JSONDecodeError, TypeError):
                meta = {}
        # combine archetype + transferable_lesson + warning_signs for matching
        matchable = " ".join([
            L.get("archetype", "") or meta.get("archetype", ""),
            L.get("transferable_lesson", "") or meta.get("transferable_lesson", ""),
            " ".join(meta.get("warning_signs_for_future") or []),
            " ".join(meta.get("what_worked") or []),
            " ".join(meta.get("what_failed") or []),
        ])
        lesson_tokens = _tokenize(matchable)
        if not lesson_tokens:
            continue

        token_overlap = case_tokens & lesson_tokens
        token_score = len(token_overlap) / max(len(lesson_tokens), 1)

        # Code/article overlap is a strong signal
        lesson_codes = {c.upper() for c in (meta.get("applicable_codes") or [])}
        lesson_arts = set(meta.get("key_articles") or [])
        code_match = bool(case_codes & lesson_codes)
        art_match = bool(case_arts & lesson_arts)

        score = (
            0.5 * token_score
            + 0.3 * (1.0 if code_match else 0.0)
            + 0.2 * (1.0 if art_match else 0.0)
        )
        if score < threshold:
            continue

        matches.append(LessonMatch(
            lesson_id=L["id"],
            case_id=L["case_id"],
            archetype=L.get("archetype") or meta.get("archetype", ""),
            transferable_lesson=L.get("transferable_lesson") or meta.get("transferable_lesson", ""),
            relevance_score=round(score, 3),
            overlap_terms=sorted(token_overlap)[:8],
            outcome=L.get("outcome", ""),
        ))

    matches.sort(key=lambda m: m.relevance_score, reverse=True)
    return matches[:top_k]


# ── Helpers ───────────────────────────────────────────────────────────

def _extract_json(text: str) -> dict | None:
    text = (text or "").strip()
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
