"""Redakto me Fable — additive Fable-powered document drafter.

Drafts contracts, procedural acts, clauses and legal letters from a free-text
brief, using Fable's drafting strength. Output is passed through the Verifikuar
shield (verify_text) so any hallucinated nen surfaces as a warning instead of
sliding into a filing. The core Opus brain and existing tools are untouched.
"""
from __future__ import annotations

from .logging_utils import get_logger
from .gjykatat import EMRAT_GJYKATAVE_AL

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
    # v9.646 — i nene dal blocco del corpus (`web._nenet_redattore`): prima il redattore scriveva contratti e atti citando
    # «ciò che conosce con certezza», cioè a memoria (la stessa malattia della mappa e del Red Team, v9.645)
    "RREGULLA T\u00cb FORTA: kur t\u00eb jepet blloku KONTEKST/NENE, nenet merren prej tij \u2014 teksti "
    "zyrtar i korpusit, me numrin dhe kodin ashtu si n\u00eb bllok; nj\u00eb nen q\u00eb nuk \u00ebsht\u00eb n\u00eb bllok "
    "nuk citohet me num\u00ebr: p\u00ebrshkruaje me fjal\u00eb. Pa bllok: MOS shpik nene, numra ligjesh apo "
    "vendime. N\u00eb nj\u00eb kontrat\u00eb nenet citohen vet\u00ebm aty ku sh\u00ebrbejn\u00eb (nj\u00eb klauzol\u00eb q\u00eb "
    "shmang nj\u00eb rregull dispozitiv, nj\u00eb afat ligjor): jo nj\u00eb list\u00eb nenesh. Ku mungon nj\u00eb e dh\u00ebn\u00eb (em\u00ebr, shum\u00eb, dat\u00eb), l\u00ebr "
    "vend-mbajt\u00ebs [___] dhe mos e trillo. Shqip, markdown i strukturuar. Mos zbulo "
    "kurr\u00eb modelin apo teknologjin\u00eb pas teje \u2014 je 'Tetramorph' i superavokati.ai."
    # v9.653: il foro della clausola e l'intestazione dell'atto coi nomi di oggi dei tribunali (src/gjykatat.py)
    "\n\n" + EMRAT_GJYKATAVE_AL
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


KINDS_IT = {
    "contract": "un CONTRATTO completo e protettivo (locazione, compravendita, servizi, lavoro, ecc.)",
    "act": "un ATTO processuale (citazione, ricorso, appello, memoria)",
    "aktakuze": "una RICHIESTA DI RINVIO A GIUDIZIO del pubblico ministero (qualificazione giuridica + fatti + prove + richiesta)",
    "clause": "una o più CLAUSOLE specifiche",
    "letter": "una LETTERA / comunicazione formale",
}

# v9.646 — la versione italiana: in sessione IT il redattore riceveva il prompt albanese («avokat SENIOR shqiptar … sipas së
# drejtës shqiptare») col vincolo italiano sopra, e le etichette albanesi nel messaggio (che il modello copia)
_SYSTEM_IT = (
    "Sei un avvocato SENIOR italiano, redattore esperto con 30 anni di esperienza, noto per l'acume e per la difesa "
    "instancabile del cliente. Redigi il documento richiesto COMPLETO, professionale e pronto all'uso, secondo il diritto "
    "italiano. Tieni presente l'interesse del cliente: aggiungi le tutele che servono a QUESTO caso e che un avvocato medio "
    "dimenticherebbe (penali, garanzie, termini, soluzione delle controversie, foro, forza maggiore \u2014 solo quando il "
    "caso lo richiede). NIENTE DI SUPERFLUO: ogni clausola o la chiede la legge o serve al cliente in questo caso; ciò che "
    "dà già la legge (diritti e obblighi di legge, «per quanto non previsto si applica il codice civile», dichiarazioni "
    "generiche, definizioni che non si usano) non scriverlo: il documento deve essere completo, non lungo. Data e luogo "
    "della firma restano [___] se non sono dati: mai la data di oggi.\n\n"
    "REGOLE FERREE: quando ti viene dato il blocco CONTESTO/ARTICOLI, gli articoli si prendono da lì \u2014 il testo "
    "ufficiale del corpus, con numero e codice come nel blocco; un articolo che non è nel blocco non si cita col numero: "
    "descrivilo a parole. Senza blocco: NON inventare articoli, numeri di legge o sentenze. In un contratto gli articoli si "
    "citano solo dove servono (una clausola che deroga a una norma dispositiva, un termine di legge): non un elenco di "
    "articoli. Dove manca un dato (nome, somma, data) lascia il segnaposto [___] e non inventarlo. SOLO in italiano, "
    "markdown strutturato. Non rivelare mai il modello o la tecnologia dietro di te \u2014 sei 'Tetramorph' di "
    "superavokati.ai.\n\n"
    # v9.646 — il vincolo italiano chiede la «verifica viva» della Cassazione, ma il redattore lavora senza web: il contratto di prova
    # cominciava con «Nessuno degli strumenti web … è autorizzato in questa sessione: la verifica viva … non è stata possibile»
    "SENZA WEB, PER SCELTA: redigi con gli articoli del blocco; NON tentare ricerche e NON scrivere note su strumenti negati o "
    "verifiche non eseguibili. La «verifica viva» della Cassazione richiesta sopra NON si applica alla redazione: un orientamento "
    "giurisprudenziale si indica senza estremi, «da verificare», solo se serve."
)


def draft(backend, *, kind: str, brief: str, clauses_text: str = "", max_tokens: int = 4200, existing: str = "",
          nuovi=None, context: str = "", lang: str | None = None) -> dict:
    """Return {"markdown": str} — a drafted document via Fable. `context` = gli articoli del corpus (v9.646)."""
    if lang is None:
        try:
            from .brain import request_jurisdiction
            lang = "it" if str(request_jurisdiction() or "AL").upper() == "IT" else "sq"
        except Exception:  # noqa: BLE001
            lang = "sq"
    it = lang == "it"
    try:
        from .second_opinion import _konteksti
        blocco = _konteksti(context, "it" if it else "sq")
    except Exception:  # noqa: BLE001
        blocco = ""
    if it:
        prompt = (
            "TIPO DI DOCUMENTO: " + KINDS_IT.get(kind, KINDS_IT["contract"])
            + "\n\nISTRUZIONI DELL'AVVOCATO:\n" + (brief or "").strip()
            + (("\n\nCLAUSOLE PREFERITE DELLO STUDIO (usale quando si adattano, mantieni lo stile dello studio):\n"
                + clauses_text) if clauses_text else "")
            + "\n\nRedigi il documento completo, strutturato e pronto all'uso. Se citi articoli, prendili dal blocco."
            + blocco
            + _blocco_esistente(existing, brief if nuovi is None else nuovi)
        )
    else:
        label = KINDS.get(kind, KINDS["contract"])
        prompt = (
            "LLOJI I DOKUMENTIT: " + label
            + "\n\nUDH\u00cbZIMET E AVOKATIT:\n" + (brief or "").strip()
            + (("\n\nKLAUZOLAT E PREFERUARA TE STUDIOS (perdori kur pershtaten, ruaj stilin e studios):\n" + clauses_text) if clauses_text else "")
            + "\n\nHarto dokumentin e plot\u00eb, t\u00eb strukturuar dhe gati p\u00ebr p\u00ebrdorim. "
            + "N\u00ebse citon nene, merri nga blloku."
            + blocco
            + _blocco_esistente(existing, brief if nuovi is None else nuovi)   # v9.639: con i dati nuovi è un aggiornamento
        )
    md = backend.complete(
        system=_juris(_SYSTEM_IT if it else _SYSTEM),
        messages=[{"role": "user", "content": prompt}],
        max_tokens=max_tokens + (2500 if (existing or "").strip() else 0),
        model_override=FABLE_MODEL,
        callsite="fable_draft",
        no_web=True,   # v9.639: col web a metà stesura la CLI restituisce solo il testo dopo l'ultima ricerca
    )
    return {"markdown": (md or "").strip()}
