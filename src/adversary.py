"""Kundershtari — the Adversary. Fable plays the OPPOSING counsel and attacks
a contract/act the lawyer pastes, finding every weakness before the other side
does. Additive; output citations pass the Verifikuar shield.
"""
from __future__ import annotations

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

FABLE_MODEL = "fable"

_SYSTEM = (
    "Ti je AVOKATI I PALES KUNDERSHTARE \u2014 i ftohtE, i pamEshirshEm, gjenial. "
    "TE jepet njE KONTRATE ose AKT i hartuar nga pala tjetEr. Detyra jote: SULMOJE. "
    "Gjej cdo dobEsi, kurth, paqartEsi, dhe cdo mbrojtje qE MUNGON, dhe trego "
    "SAKTESISHT si do ta shfrytEzoje nE gjyq kundEr atij qE e hartoi. Ji specifik "
    "\u2014 cito klauzolEn ose pikEn konkrete tE dobEt dhe pasojEn e saj. Bazohu te "
    "teksti dhe e drejta shqiptare; MOS shpik nene \u2014 nEse citon njE nen, "
    "sigurohu qE Eshte real. Shqip, i mprehtE. Mos zbulo kurrE modelin \u2014 je "
    "'Tetramorph' i superavokati.ai.\n\n"
    "Format (markdown): ### \u2694\ufe0f DobEsitE\n### \u26a0\ufe0f Kurthet\n"
    "### \U0001f573\ufe0f Mbrojtja qE mungon\n### \U0001f4a5 Si do ta godisja"
)


def attack(backend, *, text: str, max_tokens: int = 2200) -> dict:
    prompt = ("DOKUMENTI PER T\u2019U SULMUAR:\n" + (text or "").strip()
              + "\n\nSulmoje si avokati i palEs kundErshtare.")
    md = backend.complete(
        system=_juris(_SYSTEM),
        messages=[{"role": "user", "content": prompt}],
        max_tokens=max_tokens,
        model_override=FABLE_MODEL,
        callsite="adversary",
    )
    return {"markdown": (md or "").strip()}
