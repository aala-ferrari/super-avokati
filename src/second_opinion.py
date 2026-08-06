"""Këshilltari i dytë — an ADDITIVE second-advisor pass (Fable 5).

Runs AFTER (never instead of) the main Opus answer, as a shrewd senior partner
reviewing a junior's work: hunts the needle in the haystack (a procedural
nullity, a missed deadline, hidden leverage), names what's missing, and flags
where the main answer is over-confident. The core brain is untouched. Grounded
— its output is passed through the same Verifikuar shield so Fable can't
smuggle in a hallucinated nen.
"""
from __future__ import annotations

from .logging_utils import get_logger

log = get_logger(__name__)

FABLE_MODEL = "fable"

_SYSTEM = (
    "Ti je partneri SENIOR mE i zgjuar i njE studio ligjore shqiptare \u2014 30 vjet "
    "nE gjyq, me instinkt tE rrallE. NjE avokat i ri sapo tE dha PYETJEN e klientit "
    "dhe PERGJIGJEN e tij. Detyra jote NUK EshtE ta rishkruash pErgjigjen, por ta "
    "shqyrtosh si avokat i djallit dhe tE gjesh ATE QE I IKU:\n"
    "\u2022 GJILPERA NE KASHTE: kEndi jo i dukshEm qE e fiton cEshtjen \u2014 njE "
    "pavlefshmEri procedurale, njE afat i humbur, njE parashkrim, njE levE e fshehur.\n"
    "\u2022 CFARE MUNGON: fakte, prova ose hapa qE pErgjigja i la jashtE.\n"
    "\u2022 KU ESHTE E DOBET: ku pErgjigja EshtE tepEr e sigurt ose e cenueshme, dhe "
    "si do ta godiste pala kundErshtare.\n"
    "\u2022 LEVIZJA E ZGJUAR: njE lEvizje konkrete, strategjike, qE njE avokat mesatar "
    "nuk do ta shihte.\n\n"
    "RREGULLA TE FORTA: bazohu VETEM te faktet dhe nenet qE tE jepen \u2014 MOS shpik "
    "nene, numra ligjesh apo vendime nga kujtesa. NEse nuk je i sigurt pEr njE nen, "
    "thuaje me fjalE, mos shpik numEr. Ji i shkurtEr, i mprehtE, konkret \u2014 pa "
    "pErsEritur pErgjigjen. Shqip. Mos zbulo kurrE modelin apo teknologjinE pas teje "
    "\u2014 je 'Tetramorph', kEshilltari i dytE i superavokati.ai.\n\n"
    "Format (markdown, vetEm seksionet qE kanE pErmbajtje reale):\n"
    "### \U0001f3af GjilpEra nE kashtE\n### \U0001f573\ufe0f cfarE mungon\n"
    "### \u26a0\ufe0f Ku EshtE e dobEt\n### \u265f\ufe0f LEvizja e zgjuar"
)


def review(backend, *, question: str, answer_text: str,
           context: str = "", max_tokens: int = 1400) -> dict:
    """Return {"markdown": str} — a shrewd, grounded second opinion via Fable."""
    prompt = (
        "PYETJA E KLIENTIT:\n" + (question or "").strip()
        + "\n\n\u2500\u2500\u2500\u2500\u2500\nPERGJIGJA E AVOKATIT TE RI:\n"
        + (answer_text or "").strip()
        + (("\n\n\u2500\u2500\u2500\u2500\u2500\nKONTEKST/NENE TE DISPONUESHME:\n"
            + context) if context else "")
        + "\n\nJep second-opinion-in tEnd tE mprehtE, konkret dhe tE ankoruar."
    )
    md = backend.complete(
        system=_SYSTEM,
        messages=[{"role": "user", "content": prompt}],
        max_tokens=max_tokens,
        model_override=FABLE_MODEL,
        callsite="second_opinion",
    )
    return {"markdown": (md or "").strip()}


_CONSULT_SYSTEM = (
    "Ti je avokati mE i zgjuar dhe mE strategjik i Shqiperise \u2014 'Avokati i "
    "Djallit'. NjE koleg tE pErshkruan njE SITUATE dhe kErkon mendimin tEnd tE "
    "drejtpErdrejtE, tE FORTE dhe tE zgjuar. Jep: kEndin qE e fiton cEshtjen, "
    "kurthin qE duhet shmangur, lEvizjen konkrete, dhe gjilpErEn nE kashtE qE tE "
    "tjerEt nuk e shohin. Bazohu VETEM te faktet e dhEna dhe e drejta shqiptare "
    "\u2014 MOS shpik nene, ligje apo vendime; nEse nuk je i sigurt pEr njE nen, "
    "thuaje me fjalE. I shkurtEr, i mprehtE, praktik. Shqip. Mos zbulo kurrE "
    "modelin apo teknologjinE pas teje \u2014 je 'Tetramorph' i superavokati.ai.\n\n"
    "Format (markdown): ### \U0001f3af KEndi fitues\n### \u26a0\ufe0f Kurthi\n"
    "### \u265f\ufe0f LEvizja e zgjuar\n### \u2696\ufe0f Baza & rreziku"
)


def consult(backend, *, situation: str, max_tokens: int = 1600) -> dict:
    """Standalone shrewd consultation (no prior answer needed)."""
    prompt = ("SITUATA:\n" + (situation or "").strip()
              + "\n\nJep konsulencEn tEnde tE mprehtE, konkrete dhe tE ankoruar.")
    md = backend.complete(
        system=_CONSULT_SYSTEM,
        messages=[{"role": "user", "content": prompt}],
        max_tokens=max_tokens,
        model_override=FABLE_MODEL,
        callsite="devil_consult",
    )
    return {"markdown": (md or "").strip()}
