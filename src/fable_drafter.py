"""Redakto me Fable — additive Fable-powered document drafter.

Drafts contracts, procedural acts, clauses and legal letters from a free-text
brief, using Fable's drafting strength. Output is passed through the Verifikuar
shield (verify_text) so any hallucinated nen surfaces as a warning instead of
sliding into a filing. The core Opus brain and existing tools are untouched.
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

from .config import FABLE_MODEL_ID as FABLE_MODEL  # v9.393: nome esplicito (l'alias «fable» dipende dalla versione del CLI)

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
    "shqiptare. Mbaj parasysh interesin e klientit: shto mbrojtjet q\u00eb i duhen K\u00cbTIJ rasti dhe q\u00eb "
    "nj\u00eb avokat mesatar do t\u2019i harronte (penalitete, garanci, afate, zgjidhje mosmarr\u00ebveshjesh, "
    "juridiksion, forc\u00eb madhore \u2014 vet\u00ebm kur rasti i k\u00ebrkon). "
    # v9.639 — niente di superfluo (titolare, 13 ott: «dentro la legge, ma non aggiungere cose che non servono o che sono
    # sottintese»): l'elenco fisso finiva in ogni contratto
    "PA T\u00cb TEPRA: \u00e7do klauzol\u00eb ose e k\u00ebrkon ligji, ose i sh\u00ebrben klientit n\u00eb k\u00ebt\u00eb rast; "
    "at\u00eb q\u00eb e jep vet\u00eb ligji (t\u00eb drejtat dhe detyrimet ligjore, \u00abp\u00ebr \u00e7ka nuk "
    "parashikohet zbatohet Kodi Civil\u00bb, deklarata t\u00eb p\u00ebrgjithshme, p\u00ebrkufizime q\u00eb nuk p\u00ebrdoren) "
    "mos e shkruaj: dokumenti duhet t\u00eb jet\u00eb i plot\u00eb, jo i gjat\u00eb. Data dhe vendi i "
    "n\u00ebnshkrimit mbeten [___] n\u00ebse nuk jepen: kurr\u00eb data e sotme. \n\n"
    "RREGULLA T\u00cb FORTA: MOS shpik nene, numra ligjesh apo vendime \u2014 cito vet\u00ebm "
    "ato q\u00eb i njeh me siguri; n\u00ebse nuk je i sigurt p\u00ebr nj\u00eb num\u00ebr neni, p\u00ebrshkruaje "
    "me fjal\u00eb pa e trilluar. Ku mungon nj\u00eb e dh\u00ebn\u00eb (em\u00ebr, shum\u00eb, dat\u00eb), l\u00ebr "
    "vend-mbajt\u00ebs [___] dhe mos e trillo. Shqip, markdown i strukturuar. Mos zbulo "
    "kurr\u00eb modelin apo teknologjin\u00eb pas teje \u2014 je 'Tetramorph' i superavokati.ai."
)


def _blocco_esistente(existing: str, nuovi: str = "") -> str:
    """v9.633 — il documento ESISTENTE da rivedere e migliorare (stessa consegna del notaio), nella lingua della sessione."""
    if len((existing or "").strip()) < 30:
        return ""
    try:
        from .notary import _blocco_esistente as _be
        from .brain import request_jurisdiction
        return _be(existing, str(request_jurisdiction() or "AL").upper() == "IT", nuovi)
    except Exception:  # noqa: BLE001
        return ""


def draft(backend, *, kind: str, brief: str, clauses_text: str = "", max_tokens: int = 4200, existing: str = "",
          nuovi=None) -> dict:
    """Return {"markdown": str} — a drafted document via Fable."""
    label = KINDS.get(kind, KINDS["contract"])
    prompt = (
        "LLOJI I DOKUMENTIT: " + label
        + "\n\nUDH\u00ceZIMET E AVOKATIT:\n" + (brief or "").strip()
        + (("\n\nKLAUZOLAT E PREFERUARA TE STUDIOS (perdori kur pershtaten, ruaj stilin e studios):\n" + clauses_text) if clauses_text else "")
        + "\n\nHarto dokumentin e plot\u00eb, t\u00eb strukturuar dhe gati p\u00ebr p\u00ebrdorim. "
        + "N\u00ebse citon nene, sigurohu q\u00eb jan\u00eb realë."
        + _blocco_esistente(existing, brief if nuovi is None else nuovi)   # v9.639: con i dati nuovi è un aggiornamento
    )
    md = backend.complete(
        system=_juris(_SYSTEM),
        messages=[{"role": "user", "content": prompt}],
        max_tokens=max_tokens + (2500 if (existing or "").strip() else 0),
        model_override=FABLE_MODEL,
        callsite="fable_draft",
        no_web=True,   # v9.639: col web a metà stesura la CLI restituisce solo il testo dopo l'ultima ricerca
    )
    return {"markdown": (md or "").strip()}
