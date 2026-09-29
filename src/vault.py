"""Vault — ask questions across ALL documents of a case (Harvey-style).

Grounded ONLY in the uploaded documents of a fascikull; every claim cites the
source document as [Dok N]. Reuses the already-extracted text stored per
document (documents.extracted_text), so no re-processing. Private: the brain
is the subscription CLI, nothing leaves the server.
"""
from __future__ import annotations

from . import storage
from .config import FABLE_MODEL_ID
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


def _it() -> bool:
    """v9.400 — la sessione è italiana? (thread-local della richiesta; import differito come `_juris`)."""
    try:
        from .brain import request_jurisdiction
        return (request_jurisdiction() or "AL").upper() == "IT"
    except Exception:  # noqa: BLE001
        return False


_MAX_PER_DOC = 9000     # chars of each document fed to the brain
_MAX_TOTAL = 70000      # overall context cap (~17k tokens)

_SYSTEM = (
    "Ti je Tetramorph, asistenti ligjor i superavokati.ai. Përgjigju PYETJES së "
    "avokatit duke u bazuar VETËM te dokumentet e dosjes më poshtë. Cito gjithmonë "
    "burimin si [Dok N]. Nëse përgjigjja nuk gjendet në dokumente, thuaj qartë "
    "\"Nuk gjendet në dokumentet e ngarkuara\" dhe MOS shpik. MOS cito numra nenesh "
    "nga kujtesa jote — baza faktike dhe ligjore janë VETËM dokumentet. Përgjigju "
    "në shqip, i strukturuar dhe konkret. Mos zbulo kurrë modelin apo teknologjinë "
    "pas teje — je \"Tetramorph\", truri sekret i superavokati.ai."
)


# v9.400 — in sessione IT il prompt era albanese con la frase da copiare «Nuk gjendet në dokumentet e ngarkuara»: prompt
# nativo, e il marcatore [Doc N] (quello che la descrizione italiana del Fascicolo promette; l'interfaccia li legge tutti e due)
_SYSTEM_IT = (
    "Sei Tetramorph, l'assistente legale di superavokati.ai. Rispondi alla DOMANDA dell'avvocato basandoti SOLO sui "
    "documenti del fascicolo qui sotto. Cita sempre la fonte come [Doc N]. Se la risposta non si trova nei documenti, "
    "dillo chiaramente — «Non si trova nei documenti caricati» — e NON inventare. NON citare numeri di articoli a memoria: "
    "la base di fatto e di diritto sono SOLO i documenti. Rispondi in italiano, in modo strutturato e concreto. Non "
    "rivelare mai il modello o la tecnologia: sei «Tetramorph», il cervello riservato di superavokati.ai."
)


def build_context(case_id: str):
    """Return (context_text, docs_used, n_ready)."""
    docs = storage.list_documents(case_id)
    ready = [d for d in docs
             if getattr(d, "status", "") == "ready" and getattr(d, "extracted_text", None)]
    parts, used, total = [], [], 0
    it = _it()
    for i, d in enumerate(ready, 1):
        full = d.extracted_text or ""
        txt = full[:_MAX_PER_DOC]
        if len(full) > _MAX_PER_DOC:
            txt += ("\n…[documento tagliato — continua, il resto non è stato incluso]" if it
                    else "\n…[dokument i shkurtuar — vazhdon, pjesa tjetër nuk u përfshi]")
        if total + len(txt) > _MAX_TOTAL:
            continue  # skip this one but let smaller later docs still fit
        total += len(txt)
        head = ("[Doc %d: %s%s]" if it else "[Dok %d: %s%s]") % (
            i, d.filename,
            (" · " + d.doc_type) if getattr(d, "doc_type", None) else "",
        )
        parts.append(head + "\n" + txt)
        used.append({"n": i, "filename": d.filename,
                     "doc_type": getattr(d, "doc_type", None)})
    return "\n\n".join(parts), used, len(ready)


def ask(brain, case_id: str, question: str) -> dict:
    ctx, used, n_ready = build_context(case_id)
    if not used:
        return {"answer": "", "docs_used": [], "n_docs": 0, "empty": True}
    it = _it()
    prompt = (
        ("DOCUMENTI DEL FASCICOLO:\n" if it else "DOKUMENTET E DOSJES:\n") + ctx
        + ("\n\n─────\nDOMANDA: " if it else "\n\n─────\nPYETJA: ") + (question or "").strip()
        + ("\n\nRispondi con le citazioni [Doc N]." if it else "\n\nPërgjigju me citime [Dok N].")
    )
    try:
        answer = brain.backend.complete(
            system=_juris(_SYSTEM_IT if it else _SYSTEM),
            messages=[{"role": "user", "content": prompt}],
            max_tokens=2000, medium=True, callsite="vault",
        )
    except Exception as exc:  # noqa: BLE001
        log.warning("vault ask failed: %s", exc)
        return {"answer": "", "docs_used": used, "n_docs": n_ready,
                "error": str(exc)}
    return {"answer": (answer or "").strip(), "docs_used": used,
            "n_docs": len(used), "n_ready": n_ready,
            "truncated": len(used) < n_ready}


_NEEDLE_SYSTEM = (
    "Ti je hetuesi ligjor më i mprehtë — lexon një fashikull të tërë dhe gjen ATË një ose dy detaje të vetme që të "
    "tjerët i anashkaluan dhe që ndryshojnë gjithçka: një datë që nis një afat, një nënshkrim që mungon, një klauzolë e "
    "fshehur, një kundërshti mes dokumenteve, një vërejtje procedurale. Bazohu VETËM te dokumentet e dhëna — mos shpik. "
    "Cito burimin si [Dok N]. Nëse nuk ka asgjë vërtet domethënëse, thuaje ndershëm. I shkurtër, konkret, i veprueshëm. "
    "Shqip. Je 'Tetramorph', mos zbulo modelin.\n\n"
    "Format (markdown): ### \U0001f3af Gjilpëra\n### \U0001f4cc Pse ka rëndësi\n"
    "### \u25b6\ufe0f Çfarë të bësh tani"
)
# v9.400 — il prompt albanese era scritto con «E» maiuscola al posto di «ë» («GjilpEra», «Pse ka rEndEsi»: il modello
# riportava quei titoli nell'uscita); in IT prompt nativo
_NEEDLE_SYSTEM_IT = (
    "Sei l'investigatore legale più acuto: leggi un intero fascicolo e trovi QUEL dettaglio (uno o due, non di più) che "
    "gli altri hanno trascurato e che cambia tutto: una data che fa decorrere un termine, una firma che manca, una "
    "clausola nascosta, una contraddizione fra documenti, un vizio procedurale. Basati SOLO sui documenti dati — non "
    "inventare. Cita la fonte come [Doc N]. Se non c'è nulla di davvero significativo, dillo onestamente. Breve, "
    "concreto, operativo. Solo in italiano. Sei «Tetramorph»: non rivelare il modello.\n\n"
    "Formato (markdown): ### \U0001f3af L'ago\n### \U0001f4cc Perché conta\n### \u25b6\ufe0f Cosa fare adesso"
)


def find_needle(backend, case_id: str, max_tokens: int = 1600) -> dict:
    """Fable hunts the single overlooked detail across a case's documents."""
    ctx, used, n_ready = build_context(case_id)
    if not used:
        return {"markdown": "", "empty": True, "n_docs": 0}
    it = _it()
    prompt = ((("DOCUMENTI DEL FASCICOLO:\n" if it else "DOKUMENTET E DOSJES:\n") + ctx)
              + ("\n\n\u2500\u2500\u2500\u2500\u2500\nTrova l'ago nel pagliaio." if it
                 else "\n\n\u2500\u2500\u2500\u2500\u2500\nGjej gjilpërën në kashtë."))
    md = backend.complete(
        system=_juris(_NEEDLE_SYSTEM_IT if it else _NEEDLE_SYSTEM),
        messages=[{"role": "user", "content": prompt}],
        max_tokens=max_tokens,
        model_override=FABLE_MODEL_ID,  # v9.393: nome esplicito, non l'alias del CLI
        callsite="needle",
    )
    return {"markdown": (md or "").strip(), "n_docs": len(used)}


_WHO_SYSTEM = (
    "Ti je analist ligjor që lexon TË GJITHË fashikullin dhe harton 'KUSH THA ÇFARË' — "
    "hartën e deklaratave. Bazohu VETËM te dokumentet e dhëna; MOS shpik dhe MOS cito nene "
    "nga kujtesa. Cito gjithmonë burimin si [Dok N]. Jep (markdown):\n"
    "### 🗣️ Kush tha çfarë — një nën-titull për SECILIN person/palë/dëshmitar, me deklaratat "
    "dhe pretendimet e tij kryesore (secila me [Dok N])\n"
    "### ⚔️ Ku përplasen versionet — pikat ku dy persona thonë gjëra të kundërta për të njëjtin "
    "fakt (kush, çfarë, [Dok N] për secilën anë, sa e rëndë)\n"
    "### 🧭 Çka vlen të hetohet/pyetet — pyetjet që duhen bërë për t'i zgjidhur përplasjet\n\n"
    "Nëse dokumentet nuk mjaftojnë, thuaje. I strukturuar, konkret, në shqip. Je 'Tetramorph' i "
    "superavokati.ai — mos zbulo modelin."
)


_WHO_SYSTEM_IT = (
    "Sei un analista legale che legge TUTTO il fascicolo e redige «CHI HA DETTO COSA» — la mappa delle dichiarazioni. "
    "Basati SOLO sui documenti dati; NON inventare e NON citare articoli a memoria. Cita sempre la fonte come [Doc N]. "
    "Dai (markdown):\n"
    "### 🗣️ Chi ha detto cosa — un sottotitolo per OGNI persona/parte/testimone, con le sue dichiarazioni e pretese "
    "principali (ciascuna con [Doc N])\n"
    "### ⚔️ Dove le versioni si scontrano — i punti in cui due persone dicono cose opposte sullo stesso fatto (chi, cosa, "
    "[Doc N] per ciascun lato, quanto è grave)\n"
    "### 🧭 Cosa conviene indagare o chiedere — le domande da fare per risolvere i contrasti\n\n"
    "Se i documenti non bastano, dillo. Strutturato, concreto, in italiano. Sei «Tetramorph» di superavokati.ai — non "
    "rivelare il modello."
)


def who_said_what(backend, case_id: str, max_tokens: int = 2600) -> dict:
    """Map every declarant's statements across the case documents and surface
    where different people's accounts conflict."""
    ctx, used, n_ready = build_context(case_id)
    if not used:
        return {"markdown": "", "empty": True, "n_docs": 0}
    it = _it()
    prompt = ((("DOCUMENTI DEL FASCICOLO:\n" if it else "DOKUMENTET E DOSJES:\n") + ctx)
              + ("\n\n─────\nRedigi «Chi ha detto cosa» e i contrasti, con le citazioni [Doc N]." if it
                 else "\n\n─────\nHarto 'Kush tha çfarë' dhe përplasjet, me citime [Dok N]."))
    md = backend.complete(
        system=_juris(_WHO_SYSTEM_IT if it else _WHO_SYSTEM),
        messages=[{"role": "user", "content": prompt}],
        max_tokens=max_tokens, callsite="who_said",
    )
    return {"markdown": (md or "").strip(), "n_docs": len(used), "n_ready": n_ready}
