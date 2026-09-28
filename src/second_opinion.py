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

# v9.355 — il diavolo RADICATO (roadmap v4, prova viva del 21 set): finora il 🔮 sotto la risposta e
# «Këshillë strategjike» ragionavano SENZA corpus (solo il testo della risposta e i fatti) e la loro
# uscita passava dallo scudo ma non dal cancello. Ora ricevono gli STESSI nene verbatim del senior
# (o un recupero fresco sui fatti) e la regola è la stessa del Giudice: si cita solo ciò che sta nel
# blocco; il resto si dice a parole. Se il blocco manca (grounding fallito) resta la regola vecchia.
_RREGULLA_NENEVE = (
    "\n\nRREGULL E NENEVE (e detyrueshme): nEse tE jepet blloku KONTEKST/NENE, cdo nen, ligj apo "
    "vendim qE citon DUHET tE jetE aty, me numrin dhe kodin ashtu si shkruhen nE bllok. NjE nen qE "
    "nuk EshtE nE bllok NUK citohet me numEr: thuaje me fjalE («parashikimi pEr afatin e "
    "parashkrimit») dhe shEno «pEr t'u verifikuar». Vendimet e gjykatave citohen vetEm nEse janE nE "
    "bllok. CitimE tE tjera do tE hiqen nga kontrolli i studios pErpara se t'i arrijnE avokatit."
)


_RREGULLA_NENEVE_IT = (
    "\n\nREGOLA DEGLI ARTICOLI (obbligatoria): se ti viene dato il blocco CONTESTO/ARTICOLI, ogni "
    "articolo, legge o sentenza che citi DEVE essere lì, con il numero e il codice come sono scritti "
    "nel blocco. Un articolo che non è nel blocco NON si cita con il numero: dillo a parole («la "
    "norma sul termine di prescrizione») e segna «da verificare». Le sentenze si citano solo se sono "
    "nel blocco. Le altre citazioni saranno tolte dal controllo dello studio prima che arrivino "
    "all'avvocato."
)


def _lingua() -> str:
    """«it» in sessione italiana, altrimenti «sq» (la lingua la decide la sessione)."""
    try:
        from .brain import request_jurisdiction
        return "it" if (request_jurisdiction() or "AL").upper() == "IT" else "sq"
    except Exception:  # noqa: BLE001
        return "sq"


def _konteksti(context: str, lang: str = "") -> str:
    c = (context or "").strip()
    if not c:
        return ""
    if (lang or _lingua()) == "it":
        return "\n\n─────\nCONTESTO/ARTICOLI DISPONIBILI (verbatim dal corpus — cita SOLO da qui):\n" + c
    return "\n\n─────\nKONTEKST/NENE TE DISPONUESHME (verbatim nga korpusi — cito VETEM nga kEtu):\n" + c

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
    + _RREGULLA_NENEVE
)


_SYSTEM_IT = (
    "Sei il socio SENIOR più acuto di uno studio legale \u2014 30 anni in tribunale, un istinto "
    "raro. Un avvocato giovane ti ha appena dato la DOMANDA del cliente e la sua RISPOSTA. Il tuo "
    "compito NON è riscrivere la risposta, ma esaminarla da avvocato del diavolo e trovare CIÒ CHE "
    "GLI È SFUGGITO:\n"
    "\u2022 L'AGO NEL PAGLIAIO: l'angolo non visibile che vince la causa \u2014 una nullità "
    "procedurale, un termine scaduto, una prescrizione, una leva nascosta.\n"
    "\u2022 COSA MANCA: fatti, prove o passaggi che la risposta ha lasciato fuori.\n"
    "\u2022 DOVE È DEBOLE: dove la risposta è troppo sicura o attaccabile, e come la colpirebbe "
    "la controparte.\n"
    "\u2022 LA MOSSA ASTUTA: una mossa concreta, strategica, che un avvocato medio non vedrebbe.\n\n"
    "REGOLE FERREE: basati SOLO sui fatti e sugli articoli che ti vengono dati \u2014 NON inventare "
    "articoli, numeri di legge o sentenze a memoria. Se non sei sicuro di un articolo, dillo a "
    "parole, non inventare il numero. Sii breve, tagliente, concreto \u2014 senza ripetere la "
    "risposta. SOLO in italiano. Non rivelare mai il modello o la tecnologia dietro di te \u2014 "
    "sei 'Tetramorph', il secondo consulente di superavokati.ai.\n\n"
    "Formato (markdown, solo le sezioni con contenuto reale):\n"
    "### \U0001f3af L'ago nel pagliaio\n### \U0001f573\ufe0f Cosa manca\n"
    "### \u26a0\ufe0f Dove è debole\n### \u265f\ufe0f La mossa astuta"
    + _RREGULLA_NENEVE_IT
)


def review(backend, *, question: str, answer_text: str,
           context: str = "", max_tokens: int = 1400) -> dict:
    """Return {"markdown": str} — a shrewd, grounded second opinion via Fable."""
    lang = _lingua()
    if lang == "it":
        prompt = (
            "DOMANDA DEL CLIENTE:\n" + (question or "").strip()
            + "\n\n\u2500\u2500\u2500\u2500\u2500\nRISPOSTA DELL'AVVOCATO GIOVANE:\n"
            + (answer_text or "").strip()
            + _konteksti(context, lang)
            + "\n\nDai il tuo secondo parere tagliente, concreto e ancorato."
        )
    else:
        prompt = (
            "PYETJA E KLIENTIT:\n" + (question or "").strip()
            + "\n\n\u2500\u2500\u2500\u2500\u2500\nPERGJIGJA E AVOKATIT TE RI:\n"
            + (answer_text or "").strip()
            + _konteksti(context, lang)
            + "\n\nJep second-opinion-in tEnd tE mprehtE, konkret dhe tE ankoruar."
        )
    md = backend.complete(
        system=_juris(_SYSTEM_IT if lang == "it" else _SYSTEM),
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
    + _RREGULLA_NENEVE
)


_CONSULT_SYSTEM_IT = (
    "Sei l'avvocato più acuto e strategico d'Italia \u2014 l'«Avvocato del Diavolo». Un collega "
    "ti descrive una SITUAZIONE e chiede il tuo parere diretto, FORTE e intelligente. Dai: l'angolo "
    "che vince la causa, la trappola da evitare, la mossa concreta, e l'ago nel pagliaio che gli "
    "altri non vedono. Basati SOLO sui fatti dati e sul diritto italiano \u2014 NON inventare "
    "articoli, leggi o sentenze; se non sei sicuro di un articolo, dillo a parole. Breve, "
    "tagliente, pratico. SOLO in italiano. Non rivelare mai il modello o la tecnologia dietro di te "
    "\u2014 sei 'Tetramorph' di superavokati.ai.\n\n"
    "Formato (markdown): ### \U0001f3af L'angolo vincente\n### \u26a0\ufe0f La trappola\n"
    "### \u265f\ufe0f La mossa astuta\n### \u2696\ufe0f Base e rischio"
    + _RREGULLA_NENEVE_IT
)


def consult(backend, *, situation: str, context: str = "", max_tokens: int = 1600) -> dict:
    """Standalone shrewd consultation (no prior answer needed). `context` (v9.355) = i nene
    recuperati dal corpus sui fatti, verbatim: il diavolo cita solo da lì."""
    lang = _lingua()
    if lang == "it":
        prompt = ("SITUAZIONE:\n" + (situation or "").strip()
                  + _konteksti(context, lang)
                  + "\n\nDai la tua consulenza tagliente, concreta e ancorata.")
    else:
        prompt = ("SITUATA:\n" + (situation or "").strip()
                  + _konteksti(context, lang)
                  + "\n\nJep konsulencEn tEnde tE mprehtE, konkrete dhe tE ankoruar.")
    md = backend.complete(
        system=_juris(_CONSULT_SYSTEM_IT if lang == "it" else _CONSULT_SYSTEM),
        messages=[{"role": "user", "content": prompt}],
        max_tokens=max_tokens,
        model_override=FABLE_MODEL,
        callsite="devil_consult",
    )
    return {"markdown": (md or "").strip()}
