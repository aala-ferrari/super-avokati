"""Conflict-of-interest checker (deontology).

Extracts a case's named parties (client / opponent) and flags ADVERSE overlaps
with the firm's OTHER cases — the same person we represent here appearing as an
opponent elsewhere, or vice versa. Deterministic once parties are known; the
brain is used only to pull names+sides from free text, never to judge conflicts.
"""
from __future__ import annotations

import json
import re

from . import storage
from .logging_utils import get_logger

def _juris(system_prompt: str) -> str:
    """System prompt adattato alla giurisdizione della richiesta.

    Import differito: brain.py importa alcuni di questi moduli, quindi un
    import in testa creerebbe un ciclo."""
    try:
        from .brain import apply_current
        return apply_current(system_prompt)
    except Exception:  # noqa: BLE001
        return system_prompt



log = get_logger(__name__)

_attempted: set[str] = set()  # per-process guard: don't re-extract nameless cases

_EXTRACT_SYSTEM = (
    "Nga PËRSHKRIMI i një çështjeje ligjore, nxirr palët me EMËR TË PLOTË (persona "
    "ose subjekte/kompani me emër). Për secilën cakto anën: \"client\" (klienti "
    "ynë), \"opponent\" (kundërshtari), ose \"third\". MOS shpik emra dhe MOS "
    "përfshij role gjenerike pa emër (p.sh. 'klienti', 'burri', 'gruaja', 'i "
    "padituri'). Nëse s'ka emra konkretë, kthe listë bosh. Kthe VETËM JSON: "
    "{\"parties\":[{\"name\":\"Emri i plotë\",\"side\":\"client|opponent|third\"}]}"
)

_GENERIC = {
    "i panjohur", "unknown", "kliente", "klienti", "klientja", "burri", "gruaja",
    "i padituri", "e paditura", "paditesi", "pala", "kundershtari", "kunder shtari",
    "shteti", "gjykata", "prokuroria", "prokurori", "avokati", "avokatja",
    "gjyqtari", "gjyqtarja", "policia", "banka", "kompania", "shoqeria",
    "i pandehuri", "e dëmtuara", "i dëmtuari", "paditur", "paditës",
}


def _extract_json(text: str) -> dict | None:
    if not text:
        return None
    t = re.sub(r"^```(?:json)?|```$", "", text.strip()).strip()
    a, b = t.find("{"), t.rfind("}")
    if a >= 0 and b > a:
        t = t[a:b + 1]
    try:
        return json.loads(t)
    except Exception:  # noqa: BLE001
        return None


def maybe_extract(brain, case_id: str, firm_id: int, text: str) -> None:
    """Extract named parties into case_parties if the case has none yet."""
    if case_id in _attempted:
        return
    if storage.list_parties_in_case(case_id):
        return
    if not text or len(text.strip()) < 15 or brain is None:
        return  # not a real attempt (short text / brain down) — retry later
    try:
        raw = brain.backend.complete(
            system=_juris(_EXTRACT_SYSTEM),
            messages=[{"role": "user", "content": text[:4000]}],
            max_tokens=300, fast=True, callsite="conflict_extract",
        )
    except Exception as exc:  # noqa: BLE001
        log.warning("conflict: extraction failed (%s)", exc)
        return  # transient — allow a later retry, don't poison the guard
    _attempted.add(case_id)  # a genuine extraction ran; don't repeat it
    data = _extract_json(raw) or {}
    for p in (data.get("parties") or [])[:8]:
        name = (p.get("name") or "").strip()
        side = p.get("side") if p.get("side") in ("client", "opponent", "third") else "unknown"
        if len(name) >= 3 and name.lower() not in _GENERIC:
            storage.add_case_party(case_id, firm_id, name, side=side, source="extracted")


_ADVERSE = {("client", "opponent"), ("opponent", "client")}


def check(case_id: str, firm_id: int) -> dict:
    parties = storage.list_parties_in_case(case_id)
    conflicts, related, seen = [], [], set()
    for p in parties:
        try:
            matches = storage.search_parties_in_firm(firm_id, p.display_name)
        except Exception as exc:  # noqa: BLE001
            log.warning("conflict: firm search failed (%s)", exc)
            continue
        for m in matches:
            if m["case_id"] == case_id:
                continue
            key = (p.name, m["case_id"], m["side"])
            if key in seen:
                continue
            seen.add(key)
            entry = {
                "party": p.display_name, "here_side": p.side,
                "other_case_id": m["case_id"],
                "other_case_title": m.get("case_title") or "",
                "other_side": m["side"],
            }
            if (p.side, m["side"]) in _ADVERSE:
                conflicts.append(entry)
            else:
                related.append(entry)
    return {
        "parties": [{"name": p.display_name, "side": p.side} for p in parties],
        "conflicts": conflicts, "related": related,
        "has_conflict": len(conflicts) > 0,
    }
