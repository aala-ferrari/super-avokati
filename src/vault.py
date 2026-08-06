"""Vault — ask questions across ALL documents of a case (Harvey-style).

Grounded ONLY in the uploaded documents of a fascikull; every claim cites the
source document as [Dok N]. Reuses the already-extracted text stored per
document (documents.extracted_text), so no re-processing. Private: the brain
is the subscription CLI, nothing leaves the server.
"""
from __future__ import annotations

from . import storage
from .logging_utils import get_logger

log = get_logger(__name__)

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


def build_context(case_id: str):
    """Return (context_text, docs_used, n_ready)."""
    docs = storage.list_documents(case_id)
    ready = [d for d in docs
             if getattr(d, "status", "") == "ready" and getattr(d, "extracted_text", None)]
    parts, used, total = [], [], 0
    for i, d in enumerate(ready, 1):
        full = d.extracted_text or ""
        txt = full[:_MAX_PER_DOC]
        if len(full) > _MAX_PER_DOC:
            txt += "\n…[dokument i shkurtuar — vazhdon, pjesa tjetër nuk u përfshi]"
        if total + len(txt) > _MAX_TOTAL:
            continue  # skip this one but let smaller later docs still fit
        total += len(txt)
        head = "[Dok %d: %s%s]" % (
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
    prompt = (
        "DOKUMENTET E DOSJES:\n" + ctx
        + "\n\n─────\nPYETJA: " + (question or "").strip()
        + "\n\nPërgjigju me citime [Dok N]."
    )
    try:
        answer = brain.backend.complete(
            system=_SYSTEM,
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
    "Ti je hetuesi mE i mprehtE ligjor \u2014 lexon njE fashikull tE tErE dhe gjen "
    "ATE njE ose dy detaje tE vetme qE tE tjerEt i mbivEshtruan dhe qE ndryshojnE "
    "gjithcka: njE datE qE nis njE afat, njE nEnshkrim qE mungon, njE klauzolE e "
    "fshehur, njE kundErshti mes dokumenteve, njE vErejtje procedurale. Bazohu "
    "VETEM te dokumentet e dhEna \u2014 mos shpik. Cito burimin si [Dok N]. NEse "
    "nuk ka asgjE vErtet domethEnEse, thuaje ndershEm. I shkurtEr, konkret, i "
    "veprueshEm. Shqip. Je 'Tetramorph', mos zbulo modelin.\n\n"
    "Format (markdown): ### \U0001f3af GjilpEra\n### \U0001f4cc Pse ka rEndEsi\n"
    "### \u25b6\ufe0f cfarE tE bEsh tani"
)


def find_needle(backend, case_id: str, max_tokens: int = 1600) -> dict:
    """Fable hunts the single overlooked detail across a case's documents."""
    ctx, used, n_ready = build_context(case_id)
    if not used:
        return {"markdown": "", "empty": True, "n_docs": 0}
    prompt = ("DOKUMENTET E DOSJES:\n" + ctx
              + "\n\n\u2500\u2500\u2500\u2500\u2500\nGjej gjilpErEn nE kashtE.")
    md = backend.complete(
        system=_NEEDLE_SYSTEM,
        messages=[{"role": "user", "content": prompt}],
        max_tokens=max_tokens,
        model_override="fable",
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


def who_said_what(backend, case_id: str, max_tokens: int = 2600) -> dict:
    """Map every declarant's statements across the case documents and surface
    where different people's accounts conflict."""
    ctx, used, n_ready = build_context(case_id)
    if not used:
        return {"markdown": "", "empty": True, "n_docs": 0}
    prompt = ("DOKUMENTET E DOSJES:\n" + ctx
              + "\n\n─────\nHarto 'Kush tha çfarë' dhe përplasjet, me citime [Dok N].")
    md = backend.complete(
        system=_WHO_SYSTEM,
        messages=[{"role": "user", "content": prompt}],
        max_tokens=max_tokens, callsite="who_said",
    )
    return {"markdown": (md or "").strip(), "n_docs": len(used), "n_ready": n_ready}
