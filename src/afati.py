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
    # v9.454 — il debitore riceve dal PËRMBARUESI il «lajmërim për ekzekutim vullnetar»: in Albania non c'è un decreto
    # ingiuntivo (verificato sul K.Pr.C. del corpus), è QUESTO l'evento che fa correre i termini: pagare (517: 5 giorni se paga o
    # alimenti, 10 negli altri casi), opporsi al titolo (609: 30 giorni dalla conoscenza dell'esecuzione), ricorrere contro gli
    # atti del përmbarues (610: 5 giorni)
    "ekzekutim": {
        "label": "Lajmërim për ekzekutim vullnetar (përmbaruesi gjyqësor)",
        "seed": [("kodi_proc_civile", "510"), ("kodi_proc_civile", "517"), ("kodi_proc_civile", "518"),
                 ("kodi_proc_civile", "609"), ("kodi_proc_civile", "610"), ("kodi_proc_civile", "148")],
        "q": "lajmërim ekzekutim vullnetar përmbarues kundërshtim titull ekzekutiv"},
    # v9.456 — i due eventi più frequenti nel fascicolo di un cliente, che finora cadevano in «tjeter» (nessun articolo): la
    # lettera di licenziamento (KP 146/2: 180 giorni dalla fine del preavviso; 155/4: 180 dal giorno della risoluzione immediata;
    # 30 dalla scoperta del motivo) e l'atto amministrativo (KPA 132: ricorso amministrativo 30 giorni; ligji 49/2012 neni 18:
    # causa 45 giorni dalla notifica dell'atto o della decisione sul ricorso)
    "pushim_nga_puna": {
        "label": "Njoftim i zgjidhjes së kontratës së punës (pushim nga puna)",
        "seed": [("kodi_punes", "143"), ("kodi_punes", "144"), ("kodi_punes", "146"), ("kodi_punes", "153"),
                 ("kodi_punes", "155"), ("kodi_punes", "145")],
        "q": "zgjidhje kontrate pune padi afat ditë njoftim pushim pa shkaqe të arsyeshme"},
    "akt_administrativ": {
        "label": "Njoftim i aktit administrativ (organ publik)",
        "seed": [("kodi_proc_admin", "132"), ("kodi_proc_admin", "133"), ("kodi_proc_admin", "140"),
                 ("ligji_gjykatat_administrative", "18"), ("ligji_gjykatat_administrative", "15"),
                 ("ligji_gjykatat_administrative", "17")],
        "q": "ankim administrativ afat padi gjykata administrative akt administrativ njoftim"},
    # v9.457 — la multa (procesverbal; KRr 202: 5 giorni dalla decisione dell'organo, 203: pagare entro 15 giorni col 50 % di
    # sconto; ligji 10279/2010 neni 26 e 29: 30 giorni in tribunale, 30: 10 giorni per pagare) e l'avviso di accertamento fiscale
    # (ligji 9920/2008 neni 106: ricorso alla direzione degli appelli 30 giorni dal ricevimento, 107: pagare o garantire, 109: 30
    # giorni in tribunale dalla decisione, o se la direzione tace 60 giorni)
    "kundervajtje": {
        "label": "Procesverbal / vendim për kundërvajtje administrative me gjobë (rrugore ose tjetër)",
        "seed": [("kodi_rrugor", "199"), ("kodi_rrugor", "201"), ("kodi_rrugor", "202"), ("kodi_rrugor", "203"),
                 ("ligji_kundervajtjet", "17"), ("ligji_kundervajtjet", "26"), ("ligji_kundervajtjet", "29"),
                 ("ligji_kundervajtjet", "30")],
        "q": "ankim gjykatë gjobë kundërvajtje administrative afat pagesa procesverbal"},
    "vleresim_tatimor": {
        "label": "Njoftim i vlerësimit tatimor / vendim i administratës tatimore",
        "seed": [("ligji_procedurat_tatimore", "69"), ("ligji_procedurat_tatimore", "106"),
                 ("ligji_procedurat_tatimore", "107"), ("ligji_procedurat_tatimore", "108"),
                 ("ligji_procedurat_tatimore", "109")],
        "q": "ankim administrativ tatimor drejtoria e apelimit afat gjykatë vlerësim tatimor"},
    # v9.458 — la domanda giudiziale RICEVUTA: KPC 158 (deklarata e mbrojtjes nel termine che fissa la gjykata, al massimo 30
    # giorni dalla notifica), 160 (kundërpadia fino all'urdhër del 158/c), 158/a-c
    "padi_e_marre": {
        "label": "Kërkesëpadi e njoftuar të paditurit",
        "seed": [("kodi_proc_civile", "158"), ("kodi_proc_civile", "158/a"), ("kodi_proc_civile", "158/b"),
                 ("kodi_proc_civile", "158/c"), ("kodi_proc_civile", "160"), ("kodi_proc_civile", "154"),
                 ("kodi_proc_civile", "148")],
        "q": "deklarata e mbrojtjes afat i padituri kundërpadi njoftim kërkesëpadi"},
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
    # v9.455 — l'ATTO DI PRECETTO notificato al debitore (verificato sul c.p.c. del corpus): pagare entro il termine intimato (480:
    # non minore di dieci giorni), il precetto perde efficacia se entro 90 giorni non inizia l'esecuzione (481), opposizione al
    # precetto prima dell'esecuzione (615), opposizione formale entro 20 giorni dalla notificazione (617); computo (155)
    "precetto": {"label": "Notificazione dell'atto di precetto",
                 "seed": [(_CPC, "474"), (_CPC, "479"), (_CPC, "480"), (_CPC, "481"), (_CPC, "615"), (_CPC, "617"),
                          (_CPC, "155")],
                 "q": "precetto opposizione atti esecutivi termine inefficacia esecuzione forzata"},
    # v9.456 — licenziamento (L. 604/1966 art. 6: impugnazione 60 giorni dalla RICEZIONE, deposito o conciliazione nei 180
    # successivi; St. Lav. 7, 18; d.lgs. 23/2015 3, 6) e provvedimento amministrativo (c.p.a. 29: 60 giorni; 41: dalla
    # notificazione o piena conoscenza; 45: deposito 30 giorni; 30 e 31; 119-120: appalti 30 giorni)
    "pushim_nga_puna": {"label": "Comunicazione scritta del licenziamento",
                        "seed": [("licenziamenti_individuali", "6"), ("licenziamenti_individuali", "2"),
                                 ("licenziamenti_individuali", "5"), ("statuto_lavoratori", "7"), ("statuto_lavoratori", "18"),
                                 ("tutele_crescenti", "3"), ("tutele_crescenti", "6")],
                        "q": "impugnazione licenziamento decadenza sessanta giorni centottanta deposito ricorso"},
    "akt_administrativ": {"label": "Notificazione o comunicazione di un provvedimento amministrativo",
                          "seed": [("codice_processo_amministrativo", "29"), ("codice_processo_amministrativo", "41"),
                                   ("codice_processo_amministrativo", "45"), ("codice_processo_amministrativo", "30"),
                                   ("codice_processo_amministrativo", "31"), ("codice_processo_amministrativo", "119"),
                                   ("codice_processo_amministrativo", "120")],
                          "q": "ricorso tribunale amministrativo annullamento termine decadenza sessanta giorni notificazione deposito"},
    # v9.457 — verbale e ordinanza-ingiunzione (C.d.S. 202: pagamento ridotto 60 giorni, -30 % entro 5; 203: prefetto 60; 204-bis
    # e d.lgs. 150/2011 art. 7: giudice di pace 30; L. 689/1981 14, 16, 18, 22 e d.lgs. 150/2011 art. 6) e avviso di accertamento
    # (d.lgs. 546/1992 art. 21: ricorso 60 giorni dalla notificazione; 22: costituzione 30; vigente fino al 31/12/2026)
    "kundervajtje": {"label": "Verbale di contestazione o ordinanza-ingiunzione (sanzione amministrativa, anche Codice della strada)",
                     "seed": [("codice_strada", "202"), ("codice_strada", "203"), ("codice_strada", "204-bis"),
                              ("riti_civili_semplificati", "7"), ("riti_civili_semplificati", "6"),
                              ("sanzioni_amministrative", "14"), ("sanzioni_amministrative", "16"),
                              ("sanzioni_amministrative", "18"), ("sanzioni_amministrative", "22")],
                     "q": "ricorso prefetto opposizione giudice di pace verbale pagamento misura ridotta ordinanza ingiunzione termine"},
    "vleresim_tatimor": {"label": "Avviso di accertamento o altro atto impositivo notificato",
                         # + gli stessi articoli nel testo unico della giustizia tributaria (67, 68, 65, 46), che si applica
                         # dal 1° gennaio 2027: il blocco degli articoli dice al modello quale vale alla data dell'atto
                         "seed": [("processo_tributario", "21"), ("processo_tributario", "22"),
                                  ("processo_tributario", "19"), ("processo_tributario", "2"),
                                  ("giustizia_tributaria", "67"), ("giustizia_tributaria", "68"),
                                  ("giustizia_tributaria", "65")],
                         "q": "ricorso tributario termine sessanta giorni notificazione atto impugnabile costituzione in giudizio"},
    # v9.458 — l'atto di citazione RICEVUTO: i termini corrono A RITROSO dall'udienza di comparizione (166: costituzione 70 giorni
    # prima; 171-ter: memorie 40/20/10 giorni prima; 167 e 38: domande riconvenzionali, chiamata del terzo, incompetenza nella
    # comparsa); 163-bis per controllare il termine a comparire (120 giorni liberi)
    # v9.460: anche il RICORSO — rito del lavoro (416: costituzione almeno 10 giorni prima dell'udienza; 415: notifica e termine a
    # comparire) e semplificato (281-undecies: entro il termine del decreto, non oltre 10 giorni prima) — senza questi semi un ricorso
    # di lavoro prendeva i 70 giorni della citazione
    "padi_e_marre": {"label": "Atto di citazione o ricorso notificato al convenuto (anche rito del lavoro o semplificato)",
                     "seed": [(_CPC, "166"), (_CPC, "167"), (_CPC, "171-ter"), (_CPC, "163-bis"), (_CPC, "38"),
                              (_CPC, "269"), (_CPC, "155"), (_CPC, "416"), (_CPC, "415"), (_CPC, "281-undecies")],
                     "q": "costituzione convenuto comparsa di risposta termine prima dell'udienza memorie integrative ricorso rito del "
                          "lavoro dieci giorni"},
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
    "AFAT | <titolo breve> | trigger=<YYYY-MM-DD> | durata=<numero> | njesi=<giorni|giorni_lavorativi|mesi|anni> | feriale=<0|1> | verso=<dopo|prima> | baza=<articolo>\n"
    "  · trigger = la data da cui decorre il termine (data dell'evento o della notificazione)\n"
    "  · verso=prima per i termini A RITROSO («almeno N giorni PRIMA dell'udienza»): allora trigger = la data dell'UDIENZA (o "
    "dell'altra data di riferimento) scritta nei dettagli; altrimenti verso=dopo\n"
    "  · se l'articolo dà solo un limite MASSIMO che fissa il giudice («entro un termine non superiore a N giorni»), usa il "
    "termine scritto nell'atto del giudice se è nei dettagli; se non c'è, NON dare la riga AFAT (scrivi nella tabella «termine "
    "fissato dal giudice, al massimo N giorni»)\n"
    "  · durata+njesi PRENDILI dal testo REALE dell'articolo (es. '30 giorni' → durata=30 njesi=giorni)\n"
    "  · feriale=1 per i termini processuali soggetti alla sospensione feriale (1-31 agosto, L. "
    "742/1969); feriale=0 per quelli che non lo sono (per esempio i procedimenti cautelari, i termini "
    "con persone detenute, le cause di lavoro — verifica) e per i termini sostanziali\n"
    "  · se la data del trigger è sconosciuta, NON dare la riga AFAT (descrivila solo nella tabella)\n"
    "  · riga AFAT SOLO per i termini che valgono per QUESTO caso con i fatti dati; le varianti che dipendono da fatti non noti "
    "(anzianità, residenza all'estero, tipo di permesso…) scrivile nella tabella con la condizione, NON come righe AFAT — ogni "
    "riga AFAT diventa una scadenza nel calendario dell'avvocato\n"
    "  · riga AFAT SOLO per i termini che deve rispettare il cliente o l'avvocato (per impugnare, pagare, depositare, agire); "
    "i termini dell'autorità, del giudice o della controparte (per esempio entro quando l'amministrazione deve decidere o "
    "notificare) — utili alla difesa — scrivili nella tabella\n\n"
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
    r"\s*feriale\s*=\s*(?P<fer>[01])\s*(?:\|\s*verso\s*=\s*(?P<verso>[A-Za-zëË]+)\s*)?"
    r"(?:\|\s*baza\s*=\s*(?P<baza>.+?))?\s*$",
    re.MULTILINE)
# sinonimi unità → unità del motore (accetta sq e it, robusto)
_NJESI = {
    "dite": "days", "ditë": "days", "dit": "days", "ditë_solare": "days", "giorni": "days",
    "dite_pune": "business_days", "ditë_pune": "business_days", "ditepune": "business_days",
    "giorni_lavorativi": "business_days", "business_days": "business_days",
    "muaj": "months", "mesi": "months", "mese": "months", "months": "months",
    "vite": "years", "vjet": "years", "vit": "years", "anni": "years", "anno": "years", "years": "years",
}


def list_triggers(jurisdiction: str = "AL"):
    # v9.456: in sessione IT l'elenco italiano — prima il motore dei termini offriva le chiavi albanesi (l'«ekzekutim» AL, e né
    # il decreto ingiuntivo né il precetto): scegliendo un evento che in Italia non c'è, il calcolo ripiegava su «Altro»
    tab = TRIGGERS_IT if (jurisdiction or "AL").upper() == "IT" else TRIGGERS
    return [{"key": k, "label": v["label"]} for k, v in tab.items()]


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
        "AFAT | <titulli i shkurtër> | trigger=<YYYY-MM-DD> | durata=<numër> | njesi=<dite|dite_pune|muaj|vite> | feriale=<0|1> | verso=<pas|para> | baza=<neni>\n"
        "  · trigger = data nga e cila nis afati (data e ngjarjes/njoftimit)\n"
        "  · verso=para për afatet PRAPA («të paktën N ditë PARA seancës»): atëherë trigger = data e SEANCËS (ose e datës tjetër "
        "të referimit) e shkruar te detajet; përndryshe verso=pas\n"
        "  · kur neni jep vetëm një kufi MAKSIMAL që e cakton gjykata («jo më vonë se N ditë»), përdor afatin e shkruar në "
        "njoftimin e gjykatës nëse është te detajet; nëse nuk është, MOS jep rresht AFAT (shkruaj në tabelë «afati që cakton "
        "gjykata, maksimumi N ditë»)\n"
        "  · durata+njesi MERRI nga teksti REAL i nenit (p.sh. '10 ditë' → durata=10 njesi=dite)\n"
        "  · feriale=1 VETËM për afate procedurale ITALIANE (pezullimi 1–31 gusht); për Shqipërinë feriale=0\n"
        "  · nëse data e trigger-it është e panjohur, MOS e jep rreshtin AFAT (përshkruaje vetëm në tabelë)\n"
        "  · rresht AFAT VETËM për afatet që vlejnë për KËTË rast me faktet e dhëna; variantet që varen nga fakte të panjohura "
        "(vjetërsia, vendbanimi jashtë shtetit, lloji i lejes…) shkruaji në tabelë me kushtin, JO si rreshta AFAT — çdo rresht "
        "AFAT bëhet një afat në kalendarin e avokatit\n"
        "  · rresht AFAT VETËM për afatet që duhet t'i respektojë klienti ose avokati (për t'u ankuar, paguar, depozituar, "
        "vepruar); afatet e organit publik, të gjykatës ose të palës tjetër (p.sh. sa kohë ka organi për të vendosur) — të "
        "dobishme për mbrojtjen — shkruaji në tabelë\n\n"
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
    afatet, md_clean = righe_afat(md, jurisdiction=jurisdiction, lang=_lang)
    return {"markdown": md_clean, "afatet": afatet,
            "articles": [{"code": c, "number": n} for c, n, _t in arts]}


_INDIETRO = {"prima", "para", "prapa", "indietro"}


def righe_afat(md: str, *, jurisdiction: str = "AL", lang: str = "sq") -> tuple[list[dict], str]:
    """Le righe macchina AFAT del modello → date dal motore DETERMINISTICO + il testo pulito con il calcolo verificato.
    v9.458: «verso=prima» = termine A RITROSO dalla data di riferimento (costituzione del convenuto 70 giorni PRIMA dell'udienza,
    memorie dell'art. 171-ter): stesso calcolo dello scadenziario (giorno non lavorativo anticipato, agosto non contato nei termini
    processuali italiani)."""
    _lang = lang
    afatet: list[dict] = []
    calc: list[str] = []
    # 1) rreshtat me RREGULL → il motore DETERMINISTICO calcola la data
    for m in _AFAT_RULE_RE.finditer(md):
        title = (m.group("title") or "").strip()
        unit = _NJESI.get((m.group("unit") or "").strip().lower())
        if not unit:
            log.warning("afati: njësi e panjohur '%s' — anashkaloj", m.group("unit"))
            continue
        indietro = (m.group("verso") or "").strip().lower() in _INDIETRO
        try:
            if indietro:
                from .scadenziario import _calcola_a_ritroso
                rr = _calcola_a_ritroso({"durata": int(m.group("dur")), "unita": unit,
                                         "processuale": m.group("fer") == "1", "lavoro_o_urgente": False},
                                        m.group("trig"), jurisdiction, _lang)
                scad, steps, warns = rr["data"], rr["passi"], []
            else:
                r = _de.compute_deadline(
                    m.group("trig"), int(m.group("dur")), unit,
                    jurisdiction=jurisdiction, feriale=(m.group("fer") == "1"),
                    legal_basis=(m.group("baza") or "").strip(), lang=_lang)
                scad, steps, warns = r.deadline.isoformat(), r.steps, r.warnings
        except Exception as exc:  # noqa: BLE001
            log.warning("deadline_engine dështoi për '%s': %s", title, exc)
            continue
        lines = ["  - " + s for s in steps] + ["  - ⚠ " + w for w in warns]
        # v9.410: base legale e passi del calcolo anche per riga (lo scadenziario del fascicolo li mostra accanto alla data)
        afatet.append({"title": title, "date": scad, "baza": (m.group("baza") or "").strip(),
                       "passi": [s.strip() for s in lines], "a_ritroso": indietro})
        calc.append("**%s → %s**\n%s" % (title, scad, "\n".join(lines)))
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
    return afatet, md_clean
