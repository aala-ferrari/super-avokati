"""Redakto me Fable — additive Fable-powered document drafter.

Drafts contracts, procedural acts, clauses and legal letters from a free-text
brief, using Fable's drafting strength. Output is passed through the Verifikuar
shield (verify_text) so any hallucinated nen surfaces as a warning instead of
sliding into a filing. The core Opus brain and existing tools are untouched.
"""
from __future__ import annotations

from .logging_utils import get_logger

log = get_logger(__name__)

FABLE_MODEL = "fable"

KINDS = {
    "contract": "nj\u00eb KONTRAT\u00cb e plot\u00eb dhe mbrojt\u00ebse (qiraje, shitjeje, sh\u00ebrbimi, pune, etj.)",
    "act": "nj\u00eb AKT procedural (padi, ankim, k\u00ebrkes\u00eb, memorie)",
    "aktakuze": "nj\u00eb AKTAKUZ\u00cb e prokurorit (kualifikimi ligjor + faktet + provat + k\u00ebrkesa)",
    "clause": "nj\u00eb ose disa KLAUZOLA specifike",
    "letter": "nj\u00eb LET\u00cbR / shkres\u00eb zyrtare juridike",
}

_SYSTEM = (
    "Ti je avokat SENIOR shqiptar, hartues i zoti me 30 vjet p\u00ebrvoj\u00eb, i njohur "
    "si i zgjuar dhe mbrojt\u00ebs i palodhur i klientit. Harto dokumentin e k\u00ebrkuar "
    "T\u00cb PLOT\u00cb, profesional dhe t\u00eb gatsh\u00ebm p\u00ebr p\u00ebrdorim, sipas s\u00eb drejt\u00ebs "
    "shqiptare. Mbaj parasysh interesin e klientit: shto klauzola/mbrojtje q\u00eb nj\u00eb "
    "avokat mesatar do t\u2019i harronte (penalitete, garanci, afate, zgjidhje "
    "mosmarr\u00ebveshjesh, juridiksion, force madhore). \n\n"
    "RREGULLA T\u00cb FORTA: MOS shpik nene, numra ligjesh apo vendime \u2014 cito vet\u00ebm "
    "ato q\u00eb i njeh me siguri; n\u00ebse nuk je i sigurt p\u00ebr nj\u00eb num\u00ebr neni, p\u00ebrshkruaje "
    "me fjal\u00eb pa e trilluar. Ku mungon nj\u00eb e dh\u00ebn\u00eb (em\u00ebr, shum\u00eb, dat\u00eb), l\u00ebr "
    "vend-mbajt\u00ebs [___] dhe mos e trillo. Shqip, markdown i strukturuar. Mos zbulo "
    "kurr\u00eb modelin apo teknologjin\u00eb pas teje \u2014 je 'Tetramorph' i superavokati.ai."
)


def draft(backend, *, kind: str, brief: str, max_tokens: int = 4200) -> dict:
    """Return {"markdown": str} — a drafted document via Fable."""
    label = KINDS.get(kind, KINDS["contract"])
    prompt = (
        "LLOJI I DOKUMENTIT: " + label
        + "\n\nUDH\u00ceZIMET E AVOKATIT:\n" + (brief or "").strip()
        + "\n\nHarto dokumentin e plot\u00eb, t\u00eb strukturuar dhe gati p\u00ebr p\u00ebrdorim. "
        + "N\u00ebse citon nene, sigurohu q\u00eb jan\u00eb realë."
    )
    md = backend.complete(
        system=_SYSTEM,
        messages=[{"role": "user", "content": prompt}],
        max_tokens=max_tokens,
        model_override=FABLE_MODEL,
        callsite="fable_draft",
    )
    return {"markdown": (md or "").strip()}
