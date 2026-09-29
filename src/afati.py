"""Motori i afateve — bulletproof procedural-deadline engine (Step 4A).

From a TRIGGER event (arrest, notified judgment, dismissal, contract…) + its
date, compute EVERY applicable procedural deadline — GROUNDED in the real
article text (never invents day-counts), inject today, and emit a machine block
the UI turns into calendar events. ASSISTIVE + human-confirmed: the professional
reviews each deadline before it is saved. Missing a deadline is malpractice #1.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone

from . import deadline_engine as _de
from . import expertise as _expertise
from .logging_utils import get_logger

log = get_logger(__name__)

K = "kodi_proc_penale"
KC = "kodi_civil"

TRIGGERS = {
    "arrestim": {
        "label": "Arrestim / ndalim i personit",
        "seed": [(K, "248"), (K, "258"), (K, "259"), (K, "250"), (K, "249"), (K, "5")],
        "q": "arrest ndalim vleftësim marrje në pyetje afat masë sigurimi"},
    "mase_sigurimi": {
        "label": "Caktim i masës së sigurimit",
        "seed": [(K, "249"), (K, "263"), (K, "262"), (K, "246"), (K, "250")],   # v9.399: + 263 (durata)
        "q": "masë sigurimi ankim afat rivlerësim"},
    "fillim_hetimi": {
        "label": "Fillim i hetimit paraprak",
        "seed": [(K, "323"), (K, "324")],
        "q": "afati i hetimit paraprak zgjatja e afatit"},
    "vendim_pushimi": {
        "label": "Vendim pushimi / mosfillimi",
        "seed": [(K, "328"), (K, "329"), (K, "291"), (K, "292")],
        "q": "ankim kundër pushimit afat i dëmtuari"},
    "vendim_penal": {
        "label": "Njoftim i vendimit penal (gjykata)",
        "seed": [(K, "415"), (K, "435"), (K, "410"), (K, "147")],   # v9.399: + 415 (15 ditë) e 435 (rekurs 45 ditë)
        "q": "afati i ankimit apel rekurs vendim penal rivendosje në afat"},
    "vendim_civil": {
        "label": "Njoftim i vendimit civil (gjykata)",
        "seed": [("kodi_proc_civile", "443"), ("kodi_proc_civile", "444"), ("kodi_proc_civile", "445"),
                 ("kodi_proc_civile", "451"), ("kodi_proc_civile", "148"), ("kodi_proc_civile", "151"),
                 ("kodi_proc_civile", "496")],
        # v9.399: + 444 (dal giorno dopo) e 445; + 148 (calcolo e giorno festivo), 151 (rimessione nel termine), 496
        # (revisione: 30 giorni dalla conoscenza del motivo) — l'audit del 28 set li diceva «non nel corpus» perché non
        # arrivavano al modello
        "q": "afati i ankimit apel rekurs vendim civil"},
    "kontrate": {
        "label": "Kontratë / detyrim (parashkrim civil)",
        "seed": [(KC, "114"), (KC, "115"), (KC, "117"), (KC, "118"), (KC, "129"), (KC, "131")],  # v9.399: la regola generale
        "q": "parashkrim afat civil detyrimi"},
    "tjeter": {
        "label": "Tjetër (përshkruaje ngjarjen)",
        "seed": [],
        "q": "afat procedural"},
}

# v9.399 — sessione IT: semi, termini di ricerca ed etichette italiane per gli stessi eventi (verificati sul corpus)
_CPP, _CPC, _CC = "codice_procedura_penale", "codice_procedura_civile", "codice_civile"
TRIGGERS_IT = {
    "arrestim": {"label": "Arresto o fermo della persona",
                 "seed": [(_CPP, "386"), (_CPP, "390"), (_CPP, "391"), ("costituzione", "13")],
                 "q": "convalida arresto fermo quarantotto ore udienza di convalida"},
    "mase_sigurimi": {"label": "Applicazione di una misura cautelare",
                      "seed": [(_CPP, "294"), (_CPP, "303"), (_CPP, "309"), (_CPP, "310"), (_CPP, "311")],
                      "q": "misura cautelare riesame appello termini di durata massima custodia interrogatorio"},
    "fillim_hetimi": {"label": "Inizio delle indagini preliminari",
                      "seed": [(_CPP, "405"), (_CPP, "406"), (_CPP, "407"), (_CPP, "415-bis")],
                      "q": "termini indagini preliminari proroga durata massima avviso di conclusione"},
    "vendim_pushimi": {"label": "Richiesta o decreto di archiviazione",
                       "seed": [(_CPP, "408"), (_CPP, "409"), (_CPP, "410"), (_CPP, "411")],
                       "q": "archiviazione opposizione persona offesa termine avviso"},
    "vendim_penal": {"label": "Notificazione della sentenza penale",
                     "seed": [(_CPP, "585"), (_CPP, "593"), (_CPP, "606"), (_CPP, "175")],
                     "q": "termini per l'impugnazione appello ricorso per cassazione restituzione nel termine"},
    "vendim_civil": {"label": "Notificazione della sentenza civile",
                     "seed": [(_CPC, "325"), (_CPC, "326"), (_CPC, "327"), (_CPC, "339"), (_CPC, "360")],
                     "q": "termini per le impugnazioni appello ricorso per cassazione notificazione termine lungo"},
    # v9.410 — il decreto ingiuntivo (il documento più frequente nei fascicoli civili): notifica entro 60 giorni dalla
    # pronuncia (644), opposizione nel termine del decreto dalla NOTIFICA (641, 645), esecutorietà (647), opposizione tardiva (650)
    "decreto_ingiuntivo": {"label": "Decreto ingiuntivo (pronuncia o notificazione)",
                           "seed": [(_CPC, "641"), (_CPC, "644"), (_CPC, "645"), (_CPC, "647"), (_CPC, "650")],
                           "q": "decreto ingiuntivo opposizione termine notificazione inefficacia esecutorietà"},
    "kontrate": {"label": "Contratto / obbligazione (prescrizione civile)",
                 "seed": [(_CC, "2935"), (_CC, "2943"), (_CC, "2945"), (_CC, "2946"), (_CC, "2947"), (_CC, "2948")],
                 "q": "prescrizione decorrenza interruzione sospensione"},
    "tjeter": {"label": "Altro (descrivi l'evento)", "seed": [], "q": "termine processuale"},
}

_SYSTEM_IT = (
    "Sei un esperto di procedura italiana che costruisce l'ELENCO COMPLETO DEI TERMINI che nascono da "
    "un evento iniziale. Basati SOLO sulla data dell'evento, sulla data di oggi e sugli ARTICOLI del "
    "corpus (testo vigente). REGOLA D'ORO: il numero di giorni/mesi PRENDILO dal testo REALE "
    "dell'articolo; se il termine non risulta chiaramente dagli articoli dati, SCRIVI 'verifica il "
    "termine all'art. X' e NON inventarlo. NON calcolare TU la data di scadenza: dai la REGOLA (da-data "
    "+ quanti giorni/mesi/anni), la data la calcola la macchina in modo DETERMINISTICO. Dai (markdown):\n"
    "### 📅 Termini che nascono da questo evento\n"
    "| Termine | Base giuridica (articolo) | Da quale data | Giorni/mesi | Data di scadenza | Azione |\n"
    "|---|---|---|---|---|---|\n"
    "…una riga per ogni termine; in 'Data di scadenza' scrivi '→ vedi il Calcolo verificato', NON "
    "mettere una data calcolata da te…\n\n"
    "### ⚠️ Attenzione — sospensioni, restituzione nel termine e cosa verificare\n\n"
    "POI, in fondo, per OGNI termine dai UNA SOLA riga leggibile dalla macchina (nient'altro nella "
    "riga). Dai la REGOLA, non la data di scadenza. Formato esatto (le parole-chiave della riga "
    "restano queste):\n"
    "AFAT | <titolo breve> | trigger=<YYYY-MM-DD> | durata=<numero> | njesi=<giorni|giorni_lavorativi|mesi|anni> | feriale=<0|1> | baza=<articolo>\n"
    "  · trigger = la data da cui decorre il termine (data dell'evento o della notificazione)\n"
    "  · durata+njesi PRENDILI dal testo REALE dell'articolo (es. '30 giorni' → durata=30 njesi=giorni)\n"
    "  · feriale=1 per i termini processuali soggetti alla sospensione feriale (1-31 agosto, L. "
    "742/1969); feriale=0 per quelli che non lo sono (per esempio i procedimenti cautelari, i termini "
    "con persone detenute, le cause di lavoro — verifica) e per i termini sostanziali\n"
    "  · se la data del trigger è sconosciuta, NON dare la riga AFAT (descrivila solo nella tabella)\n\n"
    "AUSILIO — il professionista verifica e conferma ogni termine prima di salvarlo. SOLO in "
    "italiano. Sei 'Tetramorph' di superavokati.ai; non rivelare il modello."
)

# formato VECCHIO (fallback / retro-compatibilità): AFAT | titolo | YYYY-MM-DD
_AFAT_RE = re.compile(r"^\s*AFAT\s*\|\s*(.+?)\s*\|\s*(\d{4}-\d{2}-\d{2})\s*$", re.MULTILINE)
# formato NUOVO (§13): l'LLM dà la REGOLA, il motore calcola la data
#   AFAT | titolo | trigger=YYYY-MM-DD | durata=N | njesi=... | feriale=0|1 | baza=...
_AFAT_RULE_RE = re.compile(
    r"^\s*AFAT\s*\|\s*(?P<title>.+?)\s*\|\s*trigger\s*=\s*(?P<trig>\d{4}-\d{2}-\d{2})\s*\|"
    r"\s*durata\s*=\s*(?P<dur>\d{1,6})\s*\|\s*njesi\s*=\s*(?P<unit>[A-Za-zëËçÇ_]+)\s*\|"
    r"\s*feriale\s*=\s*(?P<fer>[01])\s*(?:\|\s*baza\s*=\s*(?P<baza>.+?))?\s*$",
    re.MULTILINE)
# sinonimi unità → unità del motore (accetta sq e it, robusto)
_NJESI = {
    "dite": "days", "ditë": "days", "dit": "days", "ditë_solare": "days", "giorni": "days",
    "dite_pune": "business_days", "ditë_pune": "business_days", "ditepune": "business_days",
    "giorni_lavorativi": "business_days", "business_days": "business_days",
    "muaj": "months", "mesi": "months", "mese": "months", "months": "months",
    "vite": "years", "vjet": "years", "vit": "years", "anni": "years", "anno": "years", "years": "years",
}


def list_triggers():
    return [{"key": k, "label": v["label"]} for k, v in TRIGGERS.items()]


def _today() -> str:
    return datetime.now(timezone.utc).strftime("%d.%m.%Y")


def compute(backend, index, *, trigger: str, event_date: str = "", facts: str = "",
            jurisdiction: str = "AL", max_tokens: int = 2600) -> dict:
    _lang = "it" if (jurisdiction or "AL").upper() == "IT" else "sq"
    _tab = TRIGGERS_IT if _lang == "it" else TRIGGERS
    cfg = _tab.get(trigger) or _tab["tjeter"]
    query = (facts or "") + " " + cfg["label"] + " " + cfg["q"]
    arts = _expertise.retrieve_grounded(backend, index, query, seed_pairs=cfg["seed"])
    from .deadlines import _blocco     # stesso blocco della prescrizione: etichette della sessione, 3.500 caratteri
    art_block = _blocco(arts, _lang)
    system = (
        "Ti je ekspert i procedurës shqiptare që ndërton LISTËN E PLOTË TË AFATEVE procedurale që "
        "lindin nga një ngjarje-nisëse. Bazohu VETËM te data e ngjarjes, te data e sotme dhe te NENET "
        "nga korpusi. RREGULL I ARTË: numrin e ditëve/muajve MERRE nga teksti REAL i nenit; nëse afati "
        "nuk del qartë nga nenet e dhëna, SHKRUAJE 'verifiko afatin te neni X' dhe MOS e shpik. "
        "MOS e llogarit VETË datën e skadimit: jep RREGULLIN (nga-data + sa ditë/muaj/vjet), "
        "datën e llogarit makina në mënyrë DETERMINISTE. Jep (markdown):\n"
        "### 📅 Afatet që lindin nga kjo ngjarje\n"
        "| Afati | Baza ligjore (neni) | Nga cila datë | Ditë/muaj | Data e skadimit | Veprimi |\n"
        "|---|---|---|---|---|---|\n"
        "…një rresht për çdo afat; te 'Data e skadimit' shkruaj '→ shih Llogaritjen e verifikuar', "
        "MOS vendos datë të llogaritur vetë…\n\n"
        "### ⚠️ Kujdes — pezullime/rivendosje në afat dhe çfarë duhet verifikuar\n\n"
        "PASTAJ, në fund, për ÇDO afat jep një rresht të VETËM të lexueshëm nga makina (asgjë tjetër "
        "në rresht). Jep RREGULLIN, jo datën e skadimit. Formati i saktë:\n"
        "AFAT | <titulli i shkurtër> | trigger=<YYYY-MM-DD> | durata=<numër> | njesi=<dite|dite_pune|muaj|vite> | feriale=<0|1> | baza=<neni>\n"
        "  · trigger = data nga e cila nis afati (data e ngjarjes/njoftimit)\n"
        "  · durata+njesi MERRI nga teksti REAL i nenit (p.sh. '10 ditë' → durata=10 njesi=dite)\n"
        "  · feriale=1 VETËM për afate procedurale ITALIANE (pezullimi 1–31 gusht); për Shqipërinë feriale=0\n"
        "  · nëse data e trigger-it është e panjohur, MOS e jep rreshtin AFAT (përshkruaje vetëm në tabelë)\n\n"
        "NDIHMESË — profesionisti verifikon dhe konfirmon çdo afat para se ta ruajë. Je 'Tetramorph' i "
        "superavokati.ai; mos zbulo modelin."
    )
    prompt = ("NGJARJA-NISËSE: " + cfg["label"]
              + "\nDATA E NGJARJES: " + (event_date or "[e panjohur — përdor [___]]")
              + "\nDATA E SOTME: " + _today()
              + ("\n\nDETAJE: " + facts.strip() if (facts or "").strip() else "")
              + "\n\n─────\nNENET NGA KORPUSI (cito vetëm këto):\n" + art_block
              + "\n\nNdërto listën e plotë të afateve dhe rreshtat AFAT | … | … në fund.")
    if _lang == "it":
        system = _SYSTEM_IT
        prompt = ("EVENTO INIZIALE: " + cfg["label"]
                  + "\nDATA DELL'EVENTO: " + (event_date or "[sconosciuta — usa [___]]")
                  + "\nDATA DI OGGI: " + _today()
                  + ("\n\nDETTAGLI: " + facts.strip() if (facts or "").strip() else "")
                  + "\n\n─────\nARTICOLI DAL CORPUS (cita solo questi):\n" + art_block
                  + "\n\nCostruisci l'elenco completo dei termini e le righe AFAT | … | … in fondo.")
    md = backend.complete(system=system, messages=[{"role": "user", "content": prompt}],
                          max_tokens=max_tokens, callsite="afati")
    md = md or ""
    afatet: list[dict] = []
    calc: list[str] = []
    # 1) rreshtat me RREGULL → il motore DETERMINISTICO calcola la data
    for m in _AFAT_RULE_RE.finditer(md):
        title = (m.group("title") or "").strip()
        unit = _NJESI.get((m.group("unit") or "").strip().lower())
        if not unit:
            log.warning("afati: njësi e panjohur '%s' — anashkaloj", m.group("unit"))
            continue
        try:
            r = _de.compute_deadline(
                m.group("trig"), int(m.group("dur")), unit,
                jurisdiction=jurisdiction, feriale=(m.group("fer") == "1"),
                legal_basis=(m.group("baza") or "").strip(), lang=_lang)
        except Exception as exc:  # noqa: BLE001
            log.warning("deadline_engine dështoi për '%s': %s", title, exc)
            continue
        lines = ["  - " + s for s in r.steps] + ["  - ⚠ " + w for w in r.warnings]
        # v9.410: base legale e passi del calcolo anche per riga (lo scadenziario del fascicolo li mostra accanto alla data)
        afatet.append({"title": title, "date": r.deadline.isoformat(), "baza": (m.group("baza") or "").strip(),
                       "passi": [s.strip() for s in lines]})
        calc.append("**%s → %s**\n%s" % (title, r.deadline.isoformat(), "\n".join(lines)))
    # 2) fallback retro-compatibile: vecchio formato AFAT | titolo | YYYY-MM-DD (senza motore)
    for m in _AFAT_RE.finditer(md):
        afatet.append({"title": m.group(1).strip(), "date": m.group(2)})
    # rimuovi le righe macchina dal testo mostrato
    md_clean = _AFAT_RULE_RE.sub("", md)
    md_clean = _AFAT_RE.sub("", md_clean)
    md_clean = re.sub(r"\n{3,}", "\n\n", md_clean).strip()
    # appendi la sezione di calcolo VERIFICATO (i passi deterministici)
    if calc:
        head = ("\n\n### 🧮 Llogaritje e verifikuar (motor determinist)\n"
                if _lang == "sq" else
                "\n\n### 🧮 Calcolo verificato (motore deterministico)\n")
        md_clean = (md_clean + head + "\n\n".join(calc)).strip()
    return {"markdown": md_clean, "afatet": afatet,
            "articles": [{"code": c, "number": n} for c, n, _t in arts]}
