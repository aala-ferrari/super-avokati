"""V9.5 — Vigilanza Normativa.

Watch Fletorja Zyrtare + new Gjykata e Lartë decisions, classify each
new item (which codes/articles affected), then match against the user's
open cases and produce push alerts.

V1 approach: lawyer pastes new content manually OR feeds via
`POST /api/vigilanza/manual`. Real scraping of fletorjazyrtare.gov.al
is stubbed in `fetch_fletorja_recent()` and can be wired up later
without changing the rest of the pipeline.
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass

from .backends import LLMBackend
from .genio import GENIO_JURISDICTION_GUARD

log = logging.getLogger(__name__)

# Albanian legal code abbreviations we recognize.
KNOWN_CODES = {
    "KC", "KPC", "KP", "KPP", "KFamiljes", "KPunes", "KAjror",
    "KDoganor", "KDetar", "KRrugor", "KZgjedhor", "KProcAdmin",
    "Kushtetuta", "KodiCivil", "KodiPenal",
}

# ── Classification prompt ─────────────────────────────────────────────

_CLASSIFY_SYSTEM = (
    GENIO_JURISDICTION_GUARD
    + "Je analist juridik shqiptar. Detyra: kategorizo një tekst të ri "
    "(akt normativ, vendim Gjykate, udhëzim) dhe ekstrakto fushat që "
    "afekton. Kthe VETËM JSON të vlefshëm pa asnjë tekst tjetër."
)

_CLASSIFY_TEMPLATE = """\
Ky tekst ka mbërritur në sistem. Klasifikoje sipas të drejtës shqiptare.

═══════════════════════════════════════════════
TEKSTI:
═══════════════════════════════════════════════
{content}

Kthe VETËM JSON me skemën e mëposhtme:

{{
  "title": "titull i shkurtër (≤120 char) që identifikon ndryshimin",
  "source_type": "ligj | vkm | udhëzim | vendim_gjykate | rregullore | tjetër",
  "kind": "ndryshim_neni | shfuqizim | ligj_i_ri | precedent_i_ri | interpretim | tjetër",
  "affected_codes": ["KC", "KP", ...],  // shkurtesat shqipe
  "affected_articles": ["Neni 248 KC", "Neni 12 KP", ...],
  "topics": ["fjalë çelës që përshkruajnë lëndën — 3-8 sende"],
  "summary": "1-2 fjali që përshkruajnë çfarë ndryshon dhe pse ka rëndësi",
  "urgency": "i lartë | i mesëm | i ulët",
  "effective_date": "YYYY-MM-DD ose null",
  "actionable_for_lawyers": "1 fjali — çfarë duhet të bëjë avokati që ka raste të prekura"
}}"""

_CLASSIFY_SCHEMA = {
    "title": "", "source_type": "tjetër", "kind": "tjetër",
    "affected_codes": [], "affected_articles": [], "topics": [],
    "summary": "", "urgency": "i mesëm", "effective_date": None,
    "actionable_for_lawyers": "",
}


@dataclass
class CaseMatch:
    case_id: str
    case_title: str
    relevance_score: float
    matched_codes: list[str]
    matched_articles: list[str]
    matched_topics: list[str]


def classify_update(content: str, *, backend: LLMBackend) -> dict:
    """Send content to Opus and return structured classification."""
    prompt = _CLASSIFY_TEMPLATE.format(content=content[:10000])
    try:
        raw = backend.complete(
            system=_CLASSIFY_SYSTEM,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=1500,
            callsite="vigilanza_classify",
        )
    except Exception as exc:  # noqa: BLE001
        log.exception("vigilanza: classify backend error")
        return {**_CLASSIFY_SCHEMA, "_parse_error": str(exc)}

    parsed = _extract_json(raw)
    if parsed is None:
        return {**_CLASSIFY_SCHEMA, "_raw": raw[:1500],
                "_parse_error": "JSON parse failed"}
    # ensure all fields exist
    for k, v in _CLASSIFY_SCHEMA.items():
        parsed.setdefault(k, v if not isinstance(v, list) else list(v))
    return parsed


# ── Matching against open cases ──────────────────────────────────────

# Regex for "Neni 248", "Neni 248 KC", "Neni 12/3 KP" and variants
_ARTICLE_RE = re.compile(
    r"(?i)\bneni\s+(\d+(?:[/.\-]\d+)*)\s*(?:i\s+)?([A-ZÇËa-zçë]+)?\b"
)


def _extract_article_refs(text: str) -> list[str]:
    """Pull out all 'Neni N CODE' references from a string."""
    refs = []
    for m in _ARTICLE_RE.finditer(text or ""):
        n, code = m.group(1), (m.group(2) or "").upper()
        refs.append(f"Neni {n}" + (f" {code}" if code else ""))
    return refs


def match_to_cases(
    classification: dict,
    open_cases: list[dict],
    *,
    threshold: float = 0.3,
) -> list[CaseMatch]:
    """Score every open case against the new classification.

    open_cases items must have keys: case_id, title, content
    (where content concatenates description + recent messages + doc summaries).
    """
    affected_codes = {c.upper() for c in classification.get("affected_codes") or []}
    affected_articles = set(classification.get("affected_articles") or [])
    topics = [t.lower() for t in classification.get("topics") or []]

    matches: list[CaseMatch] = []
    for case in open_cases:
        case_text = (case.get("content") or "").lower()
        if not case_text:
            continue

        # Article match — strong signal
        case_article_refs = set(_extract_article_refs(case.get("content", "")))
        article_overlap = affected_articles & case_article_refs
        # Bare-number match (article without code)
        if affected_articles:
            for art in affected_articles:
                bare = art.split()[1] if len(art.split()) > 1 else art
                if bare and bare in case_text and art not in article_overlap:
                    article_overlap.add(art)

        # Code match — moderate signal (case-insensitive on the lowercased text)
        code_overlap = set()
        for code in affected_codes:
            if re.search(rf"\b{re.escape(code.lower())}\b", case_text):
                code_overlap.add(code)

        # Topic match — soft signal (keyword frequency)
        topic_hits = [t for t in topics if t and t in case_text]
        topic_score = min(1.0, len(topic_hits) / max(len(topics), 1)) if topics else 0

        # Weighted relevance
        score = (
            0.6 * (1.0 if article_overlap else 0.0)
            + 0.25 * min(1.0, len(code_overlap) / max(len(affected_codes), 1))
            + 0.15 * topic_score
        )
        if score < threshold:
            continue

        matches.append(CaseMatch(
            case_id=case["case_id"],
            case_title=case.get("title", ""),
            relevance_score=round(score, 3),
            matched_codes=sorted(code_overlap),
            matched_articles=sorted(article_overlap),
            matched_topics=topic_hits,
        ))

    matches.sort(key=lambda m: m.relevance_score, reverse=True)
    return matches


# ── Stubs for future scraping integration ─────────────────────────────

def fetch_fletorja_recent(limit: int = 10) -> list[dict]:
    """Placeholder. Returns the most recent items from Fletorja Zyrtare.

    Wire-up: GET https://qbz.gov.al/eli/fz, paginate, parse HTML.
    Skipped in V1 — lawyers paste content manually via the modal.
    """
    log.info("vigilanza: fetch_fletorja_recent stub — real scraping not yet wired")
    return []


def fetch_gjykata_lartë_recent(limit: int = 10) -> list[dict]:
    """Placeholder. Returns the most recent decisions from gjykataelarte.gov.al."""
    log.info("vigilanza: fetch_gjykata_lartë_recent stub — real scraping not yet wired")
    return []


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
