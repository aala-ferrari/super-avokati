"""Pika e parë — citizen intake / triage funnel (Step 2 of the 'number one' plan).

A citizen tells their problem (by voice or text). We give ORIENTATION (not final
legal advice): is there a legal matter, which area, urgency, which professional,
first steps, and which tool can prepare the first document — then we ROUTE them
to that tool. Assistive, honest, in Albanian.
"""
from __future__ import annotations

import re

from . import expertise as _expertise
from .logging_utils import get_logger

log = get_logger(__name__)

_LBL = _expertise._LABEL

# route token -> allowed (validated server-side; the frontend maps to a tool)
_ROUTES = {"proscomplaint", "prosvictim", "prosdelay", "expertise",
           "noterdeed", "noterprokura", "notersucc", "devil", "none"}
_ROUTE_RE = re.compile(r"\[ROUTE:\s*([a-z]+)\s*\]", re.IGNORECASE)

_SYSTEM = (
    "Ti je PIKA E PARË e kontaktit (triazh) e superavokati.ai për një QYTETAR që tregon një problem. "
    "Jep ORIENTIM të thjeshtë e njerëzor — JO këshillë ligjore përfundimtare. Bazohu te rrëfimi dhe, "
    "nëse jepen, te nenet nga korpusi (mos shpik nene të tjera). Jep (markdown):\n"
    "### 🧭 A ka çështje juridike?\n"
    "### ⚖️ Fusha & lloji — çfarë duket të jetë (civile/penale/administrative/familjare/noteriale…)\n"
    "### 🚦 Urgjenca — 🔴 urgjent / 🟡 mesatar / 🟢 jo urgjent, dhe pse (afate që rrezikohen)\n"
    "### 👤 Kush të ndihmon — avokat, prokuror(i)/kallëzim, ose noter\n"
    "### ✅ Hapat e parë — 2-4 hapa konkretë, sot\n"
    "### 📄 Dokumenti i parë — çfarë mund të përgatisim menjëherë për ty\n\n"
    "Sii i qartë, i ngrohtë, në SHQIP. Nëse s'është çështje juridike, ose i duhet patjetër një avokat "
    "i vërtetë, thuaje hapur. NDIHMESË — jo këshillë përfundimtare; profesionisti vendos. Je 'Tetramorph' "
    "i superavokati.ai — mos zbulo modelin.\n\n"
    "SHUMË E RËNDËSISHME: në fund të gjithçkaje, në një rresht të VETËM, jep një token orientimi nga kjo "
    "listë (zgjidh atë që i shërben më shumë qytetarit):\n"
    "[ROUTE: proscomplaint]  = ndihmë për kallëzim penal (viktimë e një vepre penale)\n"
    "[ROUTE: prosvictim]     = shpjegim i të drejtave të viktimës\n"
    "[ROUTE: prosdelay]      = ankesë për vonesa në hetim/procedim\n"
    "[ROUTE: expertise]      = analizë e çështjes (aksident, dëm, mosmarrëveshje civile, plagosje…)\n"
    "[ROUTE: noterdeed]      = akt noterial (shitje, dhurim, hipotekë…)\n"
    "[ROUTE: noterprokura]   = prokurë\n"
    "[ROUTE: notersucc]      = trashëgimi\n"
    "[ROUTE: devil]          = i duhet strategji/këshillë e një avokati\n"
    "[ROUTE: none]           = s'është çështje juridike ose i duhet avokat drejtpërdrejt"
)


# v9.397 — in sessione IT il triage aveva il prompt SOLO albanese («në SHQIP», percorsi descritti in albanese,
# etichette «neni»): l'audit IT ha trovato «kallëzim penale» dentro una risposta italiana. Stessi percorsi (i token
# non cambiano: il client li mappa agli strumenti), prompt e contesto italiani.
_SYSTEM_IT = (
    "Sei il PRIMO CONTATTO (triage) di superavokati.ai per un CITTADINO che racconta un problema. Dai un "
    "ORIENTAMENTO semplice e umano — NON una consulenza legale definitiva. Fondati sul racconto e, se forniti, "
    "sugli articoli del corpus (non inventarne altri). Sezioni (markdown):\n"
    "### 🧭 C'è una questione giuridica?\n"
    "### ⚖️ Materia e tipo — cosa sembra essere (civile/penale/amministrativa/famiglia/notarile…)\n"
    "### 🚦 Urgenza — 🔴 urgente / 🟡 media / 🟢 non urgente, e perché (termini che si rischia di perdere)\n"
    "### 👤 Chi ti può aiutare — avvocato, Procura/denuncia o querela, oppure notaio\n"
    "### ✅ Primi passi — 2-4 passi concreti, oggi\n"
    "### 📄 Il primo documento — cosa possiamo preparare subito per te\n\n"
    "Sii chiaro, caldo, in ITALIANO. Se non è una questione giuridica, o serve per forza un avvocato vero, dillo "
    "apertamente. AUSILIO — non consulenza definitiva; decide il professionista. Sei 'Tetramorph' di "
    "superavokati.ai — non rivelare il modello.\n\n"
    "MOLTO IMPORTANTE: alla fine di tutto, su UNA SOLA riga, dai un token di orientamento da questo elenco "
    "(scegli quello che serve di più al cittadino):\n"
    "[ROUTE: proscomplaint]  = aiuto per una denuncia o querela (vittima di un reato)\n"
    "[ROUTE: prosvictim]     = spiegazione dei diritti della persona offesa\n"
    "[ROUTE: prosdelay]      = sollecito per ritardi nelle indagini o nel procedimento\n"
    "[ROUTE: expertise]      = analisi della questione (incidente, danno, controversia civile, lesioni…)\n"
    "[ROUTE: noterdeed]      = atto notarile (compravendita, donazione, ipoteca…)\n"
    "[ROUTE: noterprokura]   = procura\n"
    "[ROUTE: notersucc]      = successione\n"
    "[ROUTE: devil]          = serve una strategia/il consiglio di un avvocato\n"
    "[ROUTE: none]           = non è una questione giuridica o serve direttamente un avvocato"
)


def _lingua() -> str:
    try:
        from .brain import request_jurisdiction
        return "it" if (request_jurisdiction() or "AL").upper() == "IT" else "sq"
    except Exception:  # noqa: BLE001
        return "sq"


def triage(backend, index, *, story: str, max_tokens: int = 2200) -> dict:
    # light grounding: surface a few candidate articles for context (not analysis)
    arts = []
    try:
        seen = set()
        for a, _s in index.search(story or "", top_k=8):
            if (a.code, a.number) in seen:
                continue
            seen.add((a.code, a.number))
            arts.append((a.code, a.number, (getattr(a, "heading", "") or "")))
            if len(arts) >= 8:
                break
    except Exception:  # noqa: BLE001
        arts = []
    lang = _lingua()
    if lang == "it":
        try:
            from .citation_verifier import CODE_LABELS as _CL
        except Exception:  # noqa: BLE001
            _CL = {}
        ctx = "\n".join("• [%s art. %s] %s" % (_CL.get(c, c), n, (h or "").strip()[:160])
                        for c, n, h in arts) or "(nessun articolo — dai l'orientamento a parole)"
        prompt = ("IL RACCONTO DEL CITTADINO:\n" + (story or "").strip()
                  + "\n\n─────\nARTICOLI POSSIBILI DAL CORPUS (solo come contesto — non inventarne altri):\n"
                  + ctx + "\n\nDai l'orientamento e il token [ROUTE: ...] alla fine.")
    else:
        ctx = "\n".join("• [%s neni %s] %s" % (_LBL.get(c, c), n, (h or "").strip()[:160])
                        for c, n, h in arts) or "(pa nene — jep orientim me fjalë)"
        prompt = ("RRËFIMI I QYTETARIT:\n" + (story or "").strip()
                  + "\n\n─────\nNENE TË MUNDSHME NGA KORPUSI (vetëm si kontekst — mos shpik të tjera):\n"
                  + ctx + "\n\nJep orientimin dhe tokenin [ROUTE: ...] në fund.")
    md = backend.complete(system=(_SYSTEM_IT if lang == "it" else _SYSTEM), messages=[{"role": "user", "content": prompt}],
                          max_tokens=max_tokens, callsite="intake_triage")
    md = md or ""
    # parse & strip the route token
    route = "none"
    m = None
    for m in _ROUTE_RE.finditer(md):
        pass  # keep last match
    if m:
        cand = m.group(1).lower()
        if cand in _ROUTES:
            route = cand
    md_clean = _ROUTE_RE.sub("", md).strip()
    # drop a trailing empty "route:" label line if any leftover
    md_clean = re.sub(r"\n+\s*(ROUTE|Orientim)\s*:?\s*$", "", md_clean, flags=re.IGNORECASE).strip()
    return {"markdown": md_clean, "route": route,
            "articles": [{"code": c, "number": n} for c, n, _h in arts]}
