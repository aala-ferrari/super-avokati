"""Precedent validity check — is a cited decision still good law?

Given a decision, we search the LIVE corpus for LATER decisions on the same
topic and let the brain judge whether the earlier holding still stands or was
superseded / limited (e.g. by a unifying decision of the Gjykata e Lartë or an
annulment by the Gjykata Kushtetuese). On-demand, best-effort, GROUNDED — it
never invents an overruling: with no clear evidence it returns "ne_fuqi".
"""
from __future__ import annotations

import json
import re

from .logging_utils import get_logger

log = get_logger(__name__)

_SYSTEM = (
    "Ti je jurist shqiptar ekspert në precedentë. Të jepet një VENDIM (precedent) "
    "dhe një listë VENDIMESH TË MËVONSHME nga baza jonë që prekin tema të ngjashme. "
    "Vlerëso nëse qëndrimi juridik i vendimit është ende i vlefshëm apo i tejkaluar.\n"
    "Statuset e mundshme:\n"
    "- \"ne_fuqi\": ende i vlefshëm; asnjë tregues i qartë tejkalimi.\n"
    "- \"tejkaluar\": një vendim i mëvonshëm ka ndryshuar qëndrimin (vendim unifikues "
    "i Kolegjeve të Bashkuara, ose Gjykata Kushtetuese ka shfuqizuar normën/interpretimin).\n"
    "- \"kufizuar\": mbetet i vlefshëm por i kufizuar ose i dalluar nga vendime të mëvonshme.\n"
    "- \"e_paqarte\": nuk ka të dhëna të mjaftueshme në bazë për të gjykuar.\n"
    "RREGULL: MOS shpik tejkalim. Nëse s'ka provë të qartë te vendimet e dhëna, kthe "
    "\"ne_fuqi\" (ose \"e_paqarte\"). Kthe VETËM JSON:\n"
    "{\"status\": \"...\", \"superseded_by\": \"citim ose null\", "
    "\"note\": \"shpjegim i shkurtër në shqip\", \"confidence\": 0-100}"
)

_STATUS_LABEL = {
    "ne_fuqi": ("✅", "Ende në fuqi"),
    "tejkaluar": ("⚠️", "E tejkaluar"),
    "kufizuar": ("🔶", "E kufizuar"),
    "e_paqarte": ("❔", "E paqartë"),
}


def _as_confidence(v) -> int:
    """Tolerant 0-100 parse: accepts 85, "85", "85%", 85.0 -> 85; else 0."""
    try:
        return max(0, min(100, int(float(str(v).replace("%", "").strip()))))
    except Exception:  # noqa: BLE001
        return 0


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


def _fmt_decision(c) -> str:
    parts = [c.citation]
    if getattr(c, "decision_date", None):
        parts.append("datë " + c.decision_date.isoformat())
    if getattr(c, "outcome", None):
        parts.append("rezultati: " + c.outcome)
    head = " | ".join(parts)
    body = (getattr(c, "summary", "") or getattr(c, "excerpt", "") or "")[:500]
    return head + ("\n" + body if body else "")


def check(brain, kb, decision) -> dict:
    """decision: a CasePrecedent. kb: LegalKBRetriever (for searching later cases)."""
    label = decision.citation
    query = (getattr(decision, "summary", "") or "") + " " \
            + (getattr(decision, "excerpt", "") or "")[:400]
    later = []
    try:
        hits = kb.search([query.strip() or label], top_k=12)
        d_date = getattr(decision, "decision_date", None)
        for c, _s in hits:
            if c.id == decision.id:
                continue
            cd = getattr(c, "decision_date", None)
            # keep only genuinely later decisions (or unknown date, kept as weak signal)
            if d_date and cd and cd <= d_date:
                continue
            later.append(c)
            if len(later) >= 6:
                break
    except Exception as exc:  # noqa: BLE001
        log.warning("validity: corpus search failed (%s)", exc)

    if not later:
        return {
            "status": "ne_fuqi",
            "superseded_by": None,
            "note": "Nuk u gjet asnjë vendim i mëvonshëm në bazë që ta tejkalojë. "
                    "Sipas të dhënave tona, mbetet i vlefshëm (kontroll jo shterues).",
            "confidence": 55,
            "checked_against": 0,
        }

    prompt = (
        "VENDIMI PËR T'U VLERËSUAR:\n" + _fmt_decision(decision)
        + "\n\n─────\nVENDIME NGA BAZA (mundësisht të mëvonshme; disa mund të mos kenë datë të konfirmuar — MOS supozo se e tejkalojnë pa prova të qartë):\n"
        + "\n\n".join("• " + _fmt_decision(c) for c in later)
        + "\n\nVlerëso statusin. JSON."
    )
    try:
        raw = brain.backend.complete(
            system=_SYSTEM,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=400, medium=True, callsite="validity",
        )
    except Exception as exc:  # noqa: BLE001
        log.warning("validity: brain failed (%s)", exc)
        return {"status": "e_paqarte", "superseded_by": None,
                "note": "Kontrolli teknik dështoi. Provo përsëri.",
                "confidence": 0, "checked_against": len(later)}

    data = _extract_json(raw) or {}
    status = data.get("status")
    if status not in _STATUS_LABEL:
        status = "e_paqarte"
    icon, lbl = _STATUS_LABEL[status]
    return {
        "status": status,
        "icon": icon,
        "label": lbl,
        "superseded_by": data.get("superseded_by") or None,
        "note": (data.get("note") or "").strip(),
        "confidence": _as_confidence(data.get("confidence")),
        "checked_against": len(later),
    }
