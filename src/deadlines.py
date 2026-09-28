"""Afatet — prescription / deadline tracker (grounded, Opus).

Given the offense (or claim) + the relevant date, computes the prescription
period (from KP 66 scale by gravity for criminal, KC 112-136 for civil — in sessione IT artt. 157-161-bis c.p.
e 2934 ss. c.c.), the
deadline, and whether it has already expired — grounded in the corpus, never
invented. Assistive: the professional verifies.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone

from . import deadline_engine as _de
from . import expertise as _expertise
from .logging_utils import get_logger

log = get_logger(__name__)

# v9.399 — i semi civili saltavano la REGOLA GENERALE (KC 114: dieci anni) e i termini brevi (115): c'erano il 124
# (domande accessorie) e il 128 (pagamento dopo la prescrizione), e il prompt diceva «zbato nenin 124 e vijues»
_SEED = [("kodi_penal", "66"), ("kodi_penal", "67"), ("kodi_penal", "68"),
         ("kodi_civil", "114"), ("kodi_civil", "115"), ("kodi_civil", "117"),
         ("kodi_civil", "129"), ("kodi_civil", "131")]
# v9.399 — sessione IT: prima gli stessi semi albanesi (inesistenti nell'indice italiano) e il prompt sul KP 66
_SEED_IT = [("codice_penale", "157"), ("codice_penale", "158"), ("codice_penale", "159"),
            ("codice_penale", "160"), ("codice_penale", "161-bis"),
            ("codice_civile", "2935"), ("codice_civile", "2943"), ("codice_civile", "2945"),
            ("codice_civile", "2946"), ("codice_civile", "2947"), ("codice_civile", "2948")]
_MAX_ART = 3500      # prima 900: il KC 115 (elenco dei termini brevi) e l'art. 157 c.p. arrivavano tagliati


def _lbl_it(c):
    try:
        from .citation_verifier import CODE_LABELS
        if CODE_LABELS.get(c):
            return CODE_LABELS[c]
    except Exception:  # noqa: BLE001
        pass
    return c.replace("_", " ")


def _blocco(arts, lang: str) -> str:
    out = []
    for c, n, t in arts:
        t = (t or "").strip()
        testo = t[:_MAX_ART]
        if len(t) > _MAX_ART:
            testo += ((" […testo tagliato qui: altri %d caratteri — non completarlo a memoria]" if lang == "it"
                       else " […teksti u shkurtua këtu: edhe %d karaktere — mos e plotëso nga kujtesa]") % (len(t) - _MAX_ART))
        out.append(("• [%s art. %s] %s" % (_lbl_it(c), n, testo)) if lang == "it"
                   else ("• [%s neni %s] %s" % (_expertise.etichetta_al(c), n, testo)))
    return "\n".join(out) or ("(nessun articolo trovato — non inventare)" if lang == "it"
                             else "(asnjë nen i gjetur — mos shpik)")


_SYSTEM_IT = (
    "Sei un esperto di diritto italiano. Calcola la PRESCRIZIONE e i termini per il caso dato, "
    "basandoti SOLO sui fatti, sulla data indicata e sugli ARTICOLI del corpus riportati sotto "
    "(testo vigente). NON inventare articoli, termini o numeri.\n\n"
    "Se è PENALE: determina il massimo edittale del reato (dalla norma incriminatrice) e applica "
    "l'art. 157 c.p. (tempo necessario a prescrivere, con i minimi per delitti e contravvenzioni, i "
    "termini raddoppiati e i reati imprescrittibili che l'articolo indica), la decorrenza (art. 158), "
    "la sospensione (art. 159), l'interruzione e i suoi limiti (artt. 160-161) e la cessazione del "
    "corso della prescrizione (art. 161-bis c.p.); nei giudizi di impugnazione verifica anche "
    "l'improcedibilità dell'art. 344-bis c.p.p. Se è CIVILE: applica gli artt. 2934 ss. c.c. — "
    "art. 2946 (prescrizione ordinaria), le prescrizioni brevi (art. 2947 per il risarcimento del "
    "danno, art. 2948 e seguenti), la decorrenza (art. 2935), la sospensione (artt. 2941-2942) e "
    "l'interruzione (artt. 2943-2945) — e i termini speciali se indicati.\n\n"
    "Dai (markdown):\n"
    "### ⚖️ Natura e base — penale o civile, e l'articolo sulla prescrizione applicabile\n"
    "### ⏳ Termine di prescrizione — quanti anni, e PERCHÉ\n"
    "### \U0001f4c5 Calcolo — data di inizio + termine = data di scadenza; è già PRESCRITTO oggi (data di oggi: DATA_SOT)\n"
    "### \U0001f504 Sospensione / interruzione — cause che fermano o fanno ripartire il termine (articoli)\n"
    "### ⚠️ Attenzione — cosa verificare prima di fare affidamento su questo calcolo\n\n"
    "POI, in fondo, dai UNA SOLA riga leggibile dalla macchina (nient'altro nella riga) per il calcolo "
    "PRINCIPALE della prescrizione. NON calcolare tu la data di scadenza — dai la REGOLA, la data la "
    "calcola la macchina in modo DETERMINISTICO. Formato (le parole-chiave della riga restano queste):\n"
    "PARASHKRIM | trigger=<YYYY-MM-DD> | durata=<numero> | njesi=<anni|mesi|giorni> | baza=<articolo>\n"
    "  · trigger = la data EFFETTIVA di inizio (dopo l'interruzione/sospensione, se ce ne sono)\n"
    "  · durata+njesi dall'articolo reale (es. 10 anni → durata=10 njesi=anni)\n"
    "  · se la data di inizio è sconosciuta, NON dare la riga\n\n"
    "Preciso, chiaro. SOLO in italiano. AUSILIO — il professionista verifica. Sei 'Tetramorph' di "
    "superavokati.ai; non rivelare il modello."
)

# §13 — l'LLM dà la REGOLA di prescrizione, il motore calcola la data (deterministico)
#   PARASHKRIM | trigger=YYYY-MM-DD | durata=N | njesi=vite|muaj|dite | baza=...
_PRESH_RE = re.compile(
    r"^\s*PARASHKRIM\s*\|\s*trigger\s*=\s*(?P<trig>\d{4}-\d{2}-\d{2})\s*\|"
    r"\s*durata\s*=\s*(?P<dur>\d{1,4})\s*\|\s*njesi\s*=\s*(?P<unit>[A-Za-zëËçÇ_]+)"
    r"(?:\s*\|\s*baza\s*=\s*(?P<baza>.+?))?\s*$", re.MULTILINE)
_NJESI = {"vite": "years", "vit": "years", "vjet": "years", "anni": "years", "anno": "years",
          "muaj": "months", "mesi": "months", "mese": "months", "months": "months",
          "dite": "days", "ditë": "days", "giorni": "days", "days": "days"}


def _today() -> str:
    return datetime.now(timezone.utc).strftime("%d.%m.%Y")


def prescription(backend, index, *, facts: str, jurisdiction: str = "AL", max_tokens: int = 2400) -> dict:
    _lang = "it" if (jurisdiction or "AL").upper() == "IT" else "sq"
    arts = _expertise.retrieve_grounded(backend, index, facts, seed_pairs=(_SEED_IT if _lang == "it" else _SEED))
    art_block = _blocco(arts, _lang)
    system = (
        "Ti je ekspert i së drejtës shqiptare. Llogarit PARASHKRIMIN dhe afatet për rastin e "
        "dhënë, i BAZUAR VETËM te faktet, te data e dhënë dhe te NENET nga korpusi. MOS shpik "
        "nene, afate apo numra.\n\n"
        "Nëse është PENALE: përcakto dënimin maksimal të veprës (nga neni material), zbato "
        "SHKALLËN e nenit 66 të Kodit Penal (parashkrimi i ndjekjes penale sipas rëndësisë), dhe "
        "kontrollo nenin 67 (veprat që NUK parashkruhen). Nëse është CIVILE: zbato nenet 112-136 "
        "të Kodit Civil — neni 114 (rregulli i përgjithshëm: dhjetë vjet), neni 115 (afatet e "
        "shkurtra), nenet 117-123 (kur fillon afati), 129-130 (pezullimi), 131-135 (ndërprerja), "
        "136 (llogaritja e afatit) — dhe afatet e posaçme nëse jepen.\n\n"
        "Jep (markdown):\n"
        "### ⚖️ Natyra & baza — penale apo civile, dhe neni i parashkrimit i zbatueshëm\n"
        "### ⏳ Afati i parashkrimit — sa vjet, dhe PSE (shkalla/rëndësia)\n"
        "### \U0001f4c5 Llogaritja — data e fillimit + afati = data e skadimit; a ka SKADUAR sot (data e sotme: DATA_SOT)\n"
        "### \U0001f504 Pezullim / ndërprerje — shkaqe që e ndalojnë ose e rifillojnë afatin (nenet përkatëse)\n"
        "### ⚠️ Kujdes — çfarë duhet verifikuar para se të mbështetesh në këtë llogaritje\n\n"
        "PASTAJ, në fund, jep një rresht të VETËM të lexueshëm nga makina (asgjë tjetër në rresht) "
        "për llogaritjen KRYESORE të parashkrimit. MOS e llogarit vetë datën e skadimit — jep "
        "RREGULLIN, datën e llogarit makina në mënyrë DETERMINISTE. Formati:\n"
        "PARASHKRIM | trigger=<YYYY-MM-DD> | durata=<numër> | njesi=<vite|muaj|dite> | baza=<neni>\n"
        "  · trigger = data EFEKTIVE e fillimit (pas ndërprerjes/pezullimit, nëse ka)\n"
        "  · durata+njesi nga neni real (p.sh. 10 vjet → durata=10 njesi=vite)\n"
        "  · nëse data e fillimit është e panjohur, MOS e jep rreshtin\n\n"
        "I saktë, i qartë. Shqip. NDIHMESË — profesionisti verifikon. Je 'Tetramorph' i "
        "superavokati.ai; mos zbulo modelin."
    ).replace("DATA_SOT", _today())
    prompt = ("FAKTET / VEPRA / DATA:\n" + (facts or "").strip()
              + "\n\nDATA E SOTME: " + _today()
              + "\n\n─────\nNENET NGA KORPUSI (cito vetëm këto):\n" + art_block
              + "\n\nLlogarit parashkrimin dhe afatet.")
    if _lang == "it":
        system = _SYSTEM_IT.replace("DATA_SOT", _today())
        prompt = ("FATTI / REATO / DATA:\n" + (facts or "").strip()
                  + "\n\nDATA DI OGGI: " + _today()
                  + "\n\n─────\nARTICOLI DAL CORPUS (cita solo questi):\n" + art_block
                  + "\n\nCalcola la prescrizione e i termini.")
    md = backend.complete(system=system, messages=[{"role": "user", "content": prompt}],
                          max_tokens=max_tokens, callsite="prescription") or ""
    # §13 — il motore DETERMINISTICO calcola la data di scadenza + se è già decorsa.
    # Prescrizione = termine SOSTANZIALE: niente feriale, niente proroga festiva.
    extra = ""
    m = _PRESH_RE.search(md)
    if m:
        unit = _NJESI.get((m.group("unit") or "").strip().lower())
        if unit:
            try:
                r = _de.compute_deadline(
                    m.group("trig"), int(m.group("dur")), unit,
                    jurisdiction=jurisdiction, feriale=False, roll_on_holiday=False,
                    legal_basis=(m.group("baza") or "").strip(), lang=_lang)
                today = datetime.now(timezone.utc).date()
                expired = r.deadline < today
                if _lang == "it":
                    head = "\n\n### 🧮 Calcolo verificato (motore deterministico)\n"
                    verdict = ("⛔ PRESCRITTO" if expired else "✅ NON ancora prescritto") + \
                        " — scadenza **%s** (oggi %s)" % (r.deadline.isoformat(), today.isoformat())
                else:
                    head = "\n\n### 🧮 Llogaritje e verifikuar (motor determinist)\n"
                    verdict = ("⛔ I PARASHKRUAR" if expired else "✅ ENDE JO i parashkruar") + \
                        " — skadimi **%s** (sot %s)" % (r.deadline.isoformat(), today.isoformat())
                lines = ["  - " + s for s in r.steps] + ["  - ⚠ " + w for w in r.warnings]
                extra = head + verdict + "\n" + "\n".join(lines)
            except Exception as exc:  # noqa: BLE001
                log.warning("deadline_engine (prescription) dështoi: %s", exc)
    md_clean = _PRESH_RE.sub("", md)
    md_clean = re.sub(r"\n{3,}", "\n\n", md_clean).strip()
    if extra:
        md_clean = (md_clean + extra).strip()
    return {"markdown": md_clean,
            "articles": [{"code": c, "number": n} for c, n, _t in arts]}
