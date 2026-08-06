"""V8.11 — Citation Shield V2.

Built on top of V7.13 ``citation_verifier``. Three responsibilities:

1. **Confidence scoring** — a single 0.0–1.0 number derived from the verifier
   stats so the UI / API can show a green/amber/red badge without re-running
   logic. Above ``REFUSAL_CONFIDENCE_THRESHOLD`` the answer is considered
   trustworthy; below the threshold the lawyer should treat any cited
   article with suspicion.

2. **Refusal mode** — when no citation verifies AND at least one fake
   citation appears, we prepend a short Albanian disclaimer to the answer
   ("Verifikim citimesh dështoi…"). We do NOT delete the answer because
   sometimes the analysis is sound but the model invented a number; the
   lawyer can still read it but knows the citations are unreliable. Per
   the lawyer-first pivot: never paternalistic, never silent.

3. **Provenance pack** — a structured artifact suitable for attaching to
   the case dossier. Includes prompt hash, model, KB version, retrieved
   articles, citations, timestamps. Exportable as JSON; PDF export lives
   in ``pro_features.provenance_pdf``.

The module is pure-functional with no DB or LLM dependencies, so it's
trivially testable and cheap to call on every response.
"""
from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterable
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Any

from .config import PROCESSED_DATA_PATH

# Confidence threshold below which the response carries a "refusal" preamble.
# Picked at 0.5 because mixed (1 verified + 1 fake) sits at 0.5 and that's
# already too risky for an avvocato to use blindly. Tunable via env later.
REFUSAL_CONFIDENCE_THRESHOLD = 0.5

# Plain Albanian preamble we prepend on refusal. Short on purpose — the
# lawyer reads dozens of these per day, no novellas.
REFUSAL_PREAMBLE_AL = (
    "⚠️ **Verifikim citimesh dështoi.** Numri/kodi i citimeve më poshtë "
    "nuk u gjet në bazën e neneve të Super Avvocato. Mos u mbështet "
    "verbatim te këto referenca pa kontrolluar Fletoren Zyrtare.\n\n"
)

# Same in Italian — used when jurisdiction == "IT" (V8.13 hook).
REFUSAL_PREAMBLE_IT = (
    "⚠️ **Verifica delle citazioni fallita.** Il numero/codice delle "
    "citazioni qui sotto non risulta nella base articoli di Super "
    "Avvocato. Non utilizzarle prima di un controllo in Gazzetta "
    "Ufficiale o in Italgiure.\n\n"
)


# ── confidence scoring ────────────────────────────────────────────────────


def confidence_from_stats(stats: dict[str, int]) -> float:
    """Map the V7.13 stats block to a single confidence score in [0,1].

    Rules of thumb:
      * no citations at all → 1.0 (the answer is general, no exposure)
      * verified / total weighted by penalty for fake / needs_code
      * fake counts double against confidence (worst case: a fabricated nen)
    """
    total = int(stats.get("total") or 0)
    if total == 0:
        return 1.0
    verified = int(stats.get("verified") or 0)
    fake = int(stats.get("fake") or 0)
    needs = int(stats.get("needs_code") or 0)
    repealed = int(stats.get("repealed") or 0)
    # weight: verified=+1, repealed=+0.5 (real but superseded, NOT fabricated),
    # needs_code=+0.5, fake=-1
    score = (verified + 0.5 * repealed + 0.5 * needs - fake) / max(total, 1)
    # clip to [0,1]
    if score < 0.0:
        return 0.0
    if score > 1.0:
        return 1.0
    return round(score, 3)


def confidence_label(score: float) -> str:
    """Albanian label for the UI badge."""
    if score >= 0.85:
        return "I lartë"          # green
    if score >= REFUSAL_CONFIDENCE_THRESHOLD:
        return "Mesatar"          # amber
    return "I ulët"               # red


# ── refusal mode ──────────────────────────────────────────────────────────


def should_refuse(citations_payload: dict[str, Any]) -> bool:
    """True when the response carries fake citations and zero verified.

    Conservative on purpose: a mixed response (some verified, some fake) is
    NOT refused — we let the lawyer see both with the badge. We only refuse
    when the model went full-hallucinate (no anchors, fabricated nens).
    """
    stats = citations_payload.get("stats") or {}
    total = int(stats.get("total") or 0)
    if total == 0:
        return False
    verified = int(stats.get("verified") or 0)
    fake = int(stats.get("fake") or 0)
    return verified == 0 and fake >= 1


def apply_refusal(text: str, jurisdiction: str = "AL") -> str:
    """Prepend the refusal preamble in the right language."""
    if not text:
        return text
    preamble = REFUSAL_PREAMBLE_IT if jurisdiction == "IT" else REFUSAL_PREAMBLE_AL
    if text.startswith("⚠️"):  # already prepended by something else
        return text
    return preamble + text


# ── KB version ────────────────────────────────────────────────────────────
#
# The KB version is the SHA-256 of the canonical articles file. If the
# corpus changes, the hash changes, and every saved provenance pack remains
# auditable against the exact KB the answer was produced from.

_KB_VERSION_CACHE: dict[str, str] = {}


def kb_version(jurisdiction: str = "AL") -> str:
    """Return a short hash that identifies the current KB content.

    We hash the articles JSONL (canonical, deterministic). Jurisdiction
    parameter is forward-looking for V8.13 — Albanian KB is the only one
    on disk today; Italian/EU paths fall back to the AL hash.
    """
    if jurisdiction in _KB_VERSION_CACHE:
        return _KB_VERSION_CACHE[jurisdiction]

    candidate = PROCESSED_DATA_PATH / "all_articles.jsonl"
    if not candidate.exists():
        version = "unknown"
    else:
        h = hashlib.sha256()
        with open(candidate, "rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                h.update(chunk)
        version = h.hexdigest()[:12]
    _KB_VERSION_CACHE[jurisdiction] = version
    return version


def invalidate_kb_version_cache() -> None:
    """Call after corpus refresh so subsequent answers get the new hash."""
    _KB_VERSION_CACHE.clear()


# ── provenance pack ───────────────────────────────────────────────────────


@dataclass
class ProvenancePack:
    """Audit-grade record of how an answer was produced.

    Designed to satisfy two readers:
      * a lawyer who wants to defend the work product against a client
        challenge ("you cited X — can you prove the system actually had
        article X?")
      * an EU AI Act auditor (V8.12) who needs traceability of input,
        output, sources, and model used for a high-risk legal AI decision.
    """
    response_id: str
    timestamp_iso: str
    jurisdiction: str
    kb_version: str
    model: str
    system_prompt_version: str
    prompt_hash: str
    response_hash: str
    confidence: float
    confidence_label: str
    refused: bool
    citations: dict[str, Any] = field(default_factory=dict)
    retrieved_articles: list[dict[str, Any]] = field(default_factory=list)
    retrieved_precedents: list[dict[str, Any]] = field(default_factory=list)
    extra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=2)


def _hash_text(text: str) -> str:
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()[:16]


def build_provenance_pack(
    *,
    response_text: str,
    user_message: str,
    citations_payload: dict[str, Any],
    retrieved_articles: Iterable[Any] = (),
    retrieved_precedents: Iterable[Any] = (),
    model: str,
    system_prompt_version: str,
    jurisdiction: str = "AL",
    refused: bool = False,
    extra: dict[str, Any] | None = None,
) -> ProvenancePack:
    """Assemble a ProvenancePack from the data already on hand at /api/ask.

    ``retrieved_articles`` accepts the (Article, score) tuples produced by
    the brain's retrieval stage. Any object that exposes ``code`` and
    ``number`` attributes works; extra fields are best-effort.
    """
    stats = citations_payload.get("stats") or {}
    score = confidence_from_stats(stats)
    label = confidence_label(score)

    arts: list[dict[str, Any]] = []
    for item in retrieved_articles:
        art, ret_score = (item if isinstance(item, tuple) else (item, None))
        try:
            arts.append({
                "code": getattr(art, "code", None),
                "number": getattr(art, "number", None),
                "heading": getattr(art, "heading", None),
                "score": round(float(ret_score), 4) if ret_score is not None else None,
            })
        except Exception:
            continue

    precs: list[dict[str, Any]] = []
    for item in retrieved_precedents:
        case, ret_score = (item if isinstance(item, tuple) else (item, None))
        try:
            precs.append({
                "id": getattr(case, "id", None),
                "citation": getattr(case, "citation", None) or getattr(case, "title", None),
                "outcome": getattr(case, "outcome", None),
                "score": round(float(ret_score), 4) if ret_score is not None else None,
            })
        except Exception:
            continue

    response_id = _hash_text(f"{user_message}|{response_text}|{datetime.now(UTC).isoformat()}")[:12]

    return ProvenancePack(
        response_id=response_id,
        timestamp_iso=datetime.now(UTC).isoformat(timespec="seconds"),
        jurisdiction=jurisdiction,
        kb_version=kb_version(jurisdiction),
        model=model,
        system_prompt_version=system_prompt_version,
        prompt_hash=_hash_text(user_message),
        response_hash=_hash_text(response_text),
        confidence=score,
        confidence_label=label,
        refused=refused,
        citations=citations_payload,
        retrieved_articles=arts,
        retrieved_precedents=precs,
        extra=extra or {},
    )


# ── citation suppression in text ──────────────────────────────────────────
#
# When an answer carries a fake citation, the lawyer might not read every
# badge. To avoid the worst case (lawyer copies "Neni 137 KP" verbatim into
# a brief and the article doesn't exist), we provide an opt-in helper that
# rewrites fake citations inline with a [verifikim dështoi] marker.


def annotate_fake_citations(text: str, citations_payload: dict[str, Any]) -> str:
    """Append a small marker after each fake citation occurrence.

    Conservative: we don't remove the original number — that would alter
    the lawyer's draft if they ASK'd before drafting. We just flag it
    inline so a copy-paste into a brief still carries the warning.
    """
    items = citations_payload.get("items") or []
    if not items or not text:
        return text

    fake_raws = [it.get("raw") for it in items if it.get("status") == "fake" and it.get("raw")]
    if not fake_raws:
        return text

    out = text
    for raw in fake_raws:
        # Replace only first occurrence to avoid runaway substitutions on
        # repeated citations.
        marker = f"{raw} [⚠ verifikim dështoi]"
        # word-boundary replacement, case-insensitive
        pattern = re.compile(re.escape(raw), re.IGNORECASE)
        out, n = pattern.subn(marker, out, count=1)
        if n == 0:
            continue
    return out
