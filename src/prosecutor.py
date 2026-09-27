"""Procuratore (Prokurori) — prosecution analysis (Phase 2).

Given the facts / case file, produces a GROUNDED prosecution playbook: legal
qualification of the offense(s), element-by-element evidence sufficiency with
GAP detection (what is still missing to charge), the investigative next steps,
the possible sentence — and, mandatorily, an OBJECTIVITY REVIEW (the defense
case + exculpatory evidence + weak elements). That review is the ethics shield:
research shows AI defaults to "charge", so we force it to see the other side.

ASSISTIVE ONLY: the prosecutor decides and signs. Never auto-charges, never
scores a defendant. Grounded — articles come from the corpus, never invented.

v9.397 — DUE GIURISDIZIONI. Prima era scritto solo per l'Albania (prompt, istituzioni — SPAK,
Avokati i Popullit — e norme di partenza del KPP) e in sessione italiana reggeva solo perché il
vincolo di giurisdizione lo correggeva a valle: alcuni prompt nominavano per numero articoli
albanesi («neni 291/329 KPP») dentro un parere italiano. Ora in sessione IT ogni strumento ha il
suo prompt italiano (pubblico ministero, GIP, archiviazione, avocazione, persona offesa) e le norme
di partenza del c.p.p./c.p. — tutte verificate sul corpus il 27 set 2026. La sessione AL è invariata.
E il testo degli articoli arriva al modello INTERO fino a 3.500 caratteri (prima 900: l'art. 275
c.p.p. ne ha 7.516, il KPP 58 2.483 — si perdevano proprio i commi decisivi), con l'avviso del taglio.
"""
from __future__ import annotations

from . import expertise as _expertise
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


def _lingua() -> str:
    """«it» in sessione italiana, altrimenti «sq» (la giurisdizione la decide la sessione)."""
    try:
        from .brain import request_jurisdiction
        return "it" if (request_jurisdiction() or "AL").upper() == "IT" else "sq"
    except Exception:  # noqa: BLE001
        return "sq"



log = get_logger(__name__)

_LABEL = {
    "kodi_penal": "Kodi Penal", "kodi_proc_penale": "K. Pr. Penale",
    "kodi_civil": "Kodi Civil", "kodi_familjes": "Kodi i Familjes",
    "kodi_rrugor": "Kodi Rrugor",
}

# Testo dell'articolo nel prompt: intero fino a questo punto (per articolo) e in tutto.
_MAX_ART = 3500
_MAX_TOT = 42000


def _lbl(c):
    return _expertise._LABEL.get(c) or _LABEL.get(c) or c


def _lbl_it(c):
    try:
        from .citation_verifier import CODE_LABELS
        if CODE_LABELS.get(c):
            return CODE_LABELS[c]
    except Exception:  # noqa: BLE001
        pass
    return c.replace("_", " ")


def _blocco(arts, lang: str) -> str:
    """Il blocco degli articoli per il prompt, con le etichette della sessione («art.» / «neni»)."""
    out, tot = [], 0
    for c, n, t in arts:
        t = (t or "").strip()
        cap = _MAX_ART if tot < _MAX_TOT else 400
        testo = t[:cap]
        if len(t) > cap:
            testo += ((" […testo tagliato qui: altri %d caratteri — non completarlo a memoria]" if lang == "it"
                       else " […teksti u shkurtua këtu: edhe %d karaktere — mos e plotëso nga kujtesa]") % (len(t) - cap))
        if lang == "it":
            out.append("• [%s art. %s] %s" % (_lbl_it(c), n, testo))
        else:
            out.append("• [%s neni %s] %s" % (_lbl(c), n, testo))
        tot += len(testo)
    if out:
        return "\n".join(out)
    return ("(nessun articolo trovato — descrivi a parole, non inventare)" if lang == "it"
            else "(asnjë nen i gjetur — përshkruaj me fjalë, mos shpik)")


def _cpp(*nums):
    return [("codice_procedura_penale", n) for n in nums]


def _cp(*nums):
    return [("codice_penale", n) for n in nums]


# ───────────────────────── prompt albanesi (invariati) ─────────────────────────

_SYSTEM = (
    "Ti je ndihmës i një PROKURORI në Shqipëri. Nga faktet e çështjes (dhe fashikulli "
    "nëse jepet), ndërto një analizë akuzuese profesionale, TË BAZUAR VETËM te faktet "
    "dhe te NENET e dhëna nga korpusi ynë. MOS shpik nene, numra ligjesh apo vendime — "
    "përdor vetëm ato që të jepen; nëse diçka nuk të jepet, thuaje me fjalë pa e trilluar.\n\n"
    "Jep këto seksione (markdown):\n"
    "### \U0001f4dc Kualifikimi ligjor — cila/cilat vepra penale zbatohen, me nenet e sakta nga korpusi (dhe rrethanat rënduese/lehtësuese)\n"
    "### ✅ Mjaftueshmëria e provave — për çdo ELEMENT të veprës: çfarë e provon, çfarë MUNGON (buku/gap) për të ngritur akuzën, forca\n"
    "### \U0001f50e Hapat hetimorë — çfarë duhet siguruar/kërkuar për të mbyllur boshllëqet (prova, ekspertiza, dëshmitarë, afate ruajtjeje)\n"
    "### ⚖️ REVIEW I OBJEKTIVITETIT (i detyrueshëm) — vër syzet e MBROJTJES: çfarë do të kundërshtonte avokati, cilat prova SHFAJËSUESE ekzistojnë ose duhen kërkuar, cili element është më i dobët. Prokurori ka detyrën e objektivitetit — kërko edhe provat në favor të të pandehurit. MOS anashkalo asnjë provë shfajësuese.\n"
    "### ⏰ Afatet & parashkrimi — afatet procedurale dhe parashkrimi (verifiko me dispozitat; mos shpik numra)\n"
    "### \U0001f4b0 Dënimi i mundshëm — diapazoni sipas nenit + rrethanat\n"
    "### \U0001f9ed Rekomandim — analizë e balancuar (ngritje akuze / hetim i mëtejshëm / mospërputhje). VENDIMI I TAKON PROKURORIT — mos e merr ti vendimin.\n\n"
    "I qartë, konkret, i balancuar. Shqip. Kjo është NDIHMESË — prokurori vendos dhe firmos. "
    "Mos zbulo kurrë modelin — je 'Tetramorph' i superavokati.ai."
)

_INDICT_SYSTEM = (
    "Ti je ndihmës i një PROKURORI. Harto një AKTAKUZË të strukturuar sipas së "
    "drejtës proceduriale penale shqiptare, TË BAZUAR VETËM te faktet dhe te nenet "
    "e dhëna. MOS shpik nene apo numra. Ku mungon një e dhënë (emër, datë, nr.), lër "
    "vend-mbajës [___]. Struktura (markdown):\n"
    "### PALËT — Prokuroria pranë [___]; I pandehuri [___] (gjeneralitetet)\n"
    "### RRETHANAT E FAKTIT — kronologjia e fakteve të provuara\n"
    "### KUALIFIKIMI LIGJOR — vepra penale me nenin e saktë nga korpusi + elementet\n"
    "### PROVAT — provat që mbështesin çdo element\n"
    "### KËRKESA — dërgimi në gjyq / masa / dënimi i kërkuar\n\n"
    "NDIHMESË — prokurori verifikon dhe nënshkruan. Je 'Tetramorph' i "
    "superavokati.ai; mos zbulo modelin."
)

# ───────────────────────── prompt italiani (v9.397) ─────────────────────────

_SYSTEM_IT = (
    "Sei l'assistente di un PUBBLICO MINISTERO in Italia. Dai fatti del procedimento (e dal fascicolo, se "
    "c'è) costruisci un'analisi d'accusa professionale, FONDATA SOLO sui fatti e sugli ARTICOLI forniti dal "
    "nostro corpus. NON inventare articoli, numeri di legge o sentenze — usa solo quelli forniti; se qualcosa "
    "non c'è, dillo a parole senza inventarlo.\n\n"
    "Sezioni (markdown):\n"
    "### \U0001f4dc Qualificazione giuridica — quale/i reato/i, con gli articoli esatti del corpus (e le circostanze aggravanti/attenuanti)\n"
    "### ✅ Sufficienza degli elementi — per ogni ELEMENTO del reato: cosa lo prova, cosa MANCA per esercitare l'azione penale; la regola di giudizio è la ragionevole previsione di condanna (art. 408 c.p.p.)\n"
    "### \U0001f50e Atti d'indagine — cosa acquisire per colmare le lacune (prove, consulenze tecniche, persone informate sui fatti, conservazione dei dati)\n"
    "### ⚖️ REVISIONE DI OBIETTIVITÀ (obbligatoria) — mettiti dalla parte della DIFESA: cosa contesterebbe il difensore, quali elementi A FAVORE dell'indagato esistono o vanno cercati (il PM svolge accertamenti anche su fatti e circostanze a favore della persona sottoposta alle indagini, art. 358 c.p.p.), quale elemento è il più debole. NON tralasciare nessun elemento a discarico.\n"
    "### ⏰ Termini e prescrizione — termini delle indagini preliminari e prescrizione del reato (verifica sulle norme fornite; non inventare numeri)\n"
    "### \U0001f4b0 Pena edittale — la cornice secondo l'articolo + circostanze\n"
    "### \U0001f9ed Raccomandazione — analisi equilibrata (esercizio dell'azione penale / ulteriori indagini / richiesta di archiviazione). LA DECISIONE SPETTA AL PUBBLICO MINISTERO — non prenderla tu.\n\n"
    "Chiaro, concreto, equilibrato. In italiano. È un AUSILIO — il pubblico ministero decide e firma. "
    "Non rivelare mai il modello — sei 'Tetramorph' di superavokati.ai."
)

_INDICT_SYSTEM_IT = (
    "Sei l'assistente di un PUBBLICO MINISTERO. Redigi l'atto con cui si esercita l'azione penale secondo il "
    "codice di procedura penale italiano: RICHIESTA DI RINVIO A GIUDIZIO (artt. 416-417 c.p.p.) oppure, per i "
    "reati a citazione diretta (art. 550 c.p.p.), DECRETO DI CITAZIONE DIRETTA A GIUDIZIO (art. 552 c.p.p.) — "
    "scegli in base al reato e dillo in una riga. FONDATO SOLO sui fatti e sugli articoli forniti. NON inventare "
    "articoli o numeri. Dove manca un dato (nome, data, n. R.G.N.R.), lascia [___]. Ricorda in una riga che "
    "l'atto va preceduto dall'avviso di conclusione delle indagini (art. 415-bis c.p.p.). Struttura (markdown):\n"
    "### PARTI — Procura della Repubblica presso il Tribunale di [___]; imputato [___] (generalità); difensore [___]; persona offesa [___]\n"
    "### IMPUTAZIONE — l'enunciazione, in forma chiara e precisa, del fatto, delle circostanze aggravanti e di quelle che possono comportare misure di sicurezza, con gli articoli di legge (art. 417 c.p.p.)\n"
    "### FONTI DI PROVA — le fonti di prova acquisite, elemento per elemento\n"
    "### RICHIESTA — rinvio a giudizio / citazione a giudizio; data e sottoscrizione [___]\n\n"
    "AUSILIO — il pubblico ministero verifica e sottoscrive. Sei 'Tetramorph' di superavokati.ai; non "
    "rivelare il modello."
)

_TETRA = ("NDIHMESË juridike — vendimin dhe firmën i vë profesionisti; VENDIMI PËR AKUZË, "
          "PUSHIM ose MASË I TAKON PROKURORIT/GJYKATËS, mos e merr ti. Mos vlerëso 'rrezikshmërinë' "
          "e personit me profilizim. Je 'Tetramorph' i superavokati.ai — mos zbulo kurrë modelin.")

_TETRA_IT = ("AUSILIO giuridico — la decisione e la firma spettano al professionista; LA DECISIONE SU AZIONE "
             "PENALE, ARCHIVIAZIONE O MISURA SPETTA AL PUBBLICO MINISTERO/AL GIUDICE, non prenderla tu. Non "
             "valutare la «pericolosità» della persona con profilazioni. Sei 'Tetramorph' di superavokati.ai — "
             "non rivelare mai il modello.")

# Le parti del messaggio utente, nelle due lingue.
_P = {
    "sq": {"fatti": "FAKTET E ÇËSHTJES / FASHIKULLI:", "fatti_ind": "FAKTET E ÇËSHTJES:", "dati": "TË DHËNAT / FAKTET:",
           "norme": "NENET NGA KORPUSI (cito vetëm këto):", "fine_an": "Ndërto analizën akuzuese të plotë, me review objektiviteti të detyrueshëm.",
           "fine_ind": "Harto aktakuzën e plotë.", "fine": "Ndërtoje të plotë, në markdown.",
           "stress": "AKTI PËR STRES-TEST:", "citt": "RRËFIMI I QYTETARIT:", "vitt": "SITUATA E QYTETARIT:",
           "app": "VENDIMI / SITUATA:", "del": "SITUATA E VONESËS:"},
    "it": {"fatti": "I FATTI DEL PROCEDIMENTO / IL FASCICOLO:", "fatti_ind": "I FATTI DEL PROCEDIMENTO:", "dati": "DATI / FATTI:",
           "norme": "ARTICOLI DAL CORPUS (cita solo questi):", "fine_an": "Costruisci l'analisi d'accusa completa, con la revisione di obiettività obbligatoria.",
           "fine_ind": "Redigi l'atto completo.", "fine": "Costruiscilo completo, in markdown.",
           "stress": "L'ATTO DA METTERE ALLA PROVA:", "citt": "IL RACCONTO DEL CITTADINO:", "vitt": "LA SITUAZIONE DEL CITTADINO:",
           "app": "IL PROVVEDIMENTO / LA SITUAZIONE:", "del": "LA SITUAZIONE DEL RITARDO:"},
}


def analyze(backend, index, *, facts: str, max_tokens: int = 3000) -> dict:
    lang = _lingua()
    P = _P[lang]
    seeds = (_cpp("358", "405", "408") if lang == "it" else None)
    arts = _expertise.retrieve_grounded(backend, index, facts, seed_pairs=seeds)
    prompt = (
        P["fatti"] + "\n" + (facts or "").strip()
        + "\n\n─────\n" + P["norme"] + "\n" + _blocco(arts, lang)
        + "\n\n" + P["fine_an"]
    )
    md = backend.complete(
        system=_juris(_SYSTEM_IT if lang == "it" else _SYSTEM),
        messages=[{"role": "user", "content": prompt}],
        max_tokens=max_tokens, callsite="prosecutor",  # default = Opus effort=max
    )
    return {"markdown": (md or "").strip(),
            "articles": [{"code": c, "number": n} for c, n, _t in arts]}


def draft_indictment(backend, index, *, facts, max_tokens=3200):
    lang = _lingua()
    P = _P[lang]
    seeds = (_cpp("415-bis", "416", "417", "550", "552") if lang == "it" else None)
    arts = _expertise.retrieve_grounded(backend, index, facts, seed_pairs=seeds)
    prompt = (P["fatti_ind"] + "\n" + (facts or "").strip()
              + "\n\n─────\n" + P["norme"] + "\n" + _blocco(arts, lang)
              + "\n\n" + P["fine_ind"])
    md = backend.complete(system=_juris(_INDICT_SYSTEM_IT if lang == "it" else _INDICT_SYSTEM),
                          messages=[{"role": "user", "content": prompt}],
                          max_tokens=max_tokens, callsite="indictment")
    return {"markdown": (md or "").strip(),
            "articles": [{"code": c, "number": n} for c, n, _t in arts]}


# ═══════════════════════════════════════════════════════════════════
# SUPER PROKUROR — expansion (additive). Seeds VERIFIED against corpus.
# Two axes: (i) prosecutor-facing efficiency, (ii) citizen-facing.
# HARD RULES: always assistive — the human prosecutor/judge decides and
# signs. NEVER auto-charge, auto-dismiss, or risk-score a person (EU AI
# Act red line). Grounded only — articles from the corpus, never invented.
# ═══════════════════════════════════════════════════════════════════


def _gen(backend, index, *, facts, system, callsite, seeds=None, extra="",
         intro=None, max_tokens=2800):
    lang = _lingua()
    P = _P[lang]
    arts = _expertise.retrieve_grounded(backend, index, (facts or "") + " " + extra, seed_pairs=seeds)
    prompt = ((intro or P["dati"]) + "\n" + (facts or "").strip()
              + "\n\n─────\n" + P["norme"] + "\n" + _blocco(arts, lang)
              + "\n\n" + P["fine"])
    md = backend.complete(system=_juris(system), messages=[{"role": "user", "content": prompt}],
                          max_tokens=max_tokens, callsite=callsite)
    return {"markdown": (md or "").strip(),
            "articles": [{"code": c, "number": n} for c, n, _t in arts]}


# ───────────────────────── (i) PROSECUTOR-FACING ─────────────────────────

def investigation_plan(backend, index, *, facts, max_tokens=2800):
    """Plani i hetimit — investigation plan from the complaint/facts."""
    if _lingua() == "it":
        system = (
            "Sei l'assistente di un PUBBLICO MINISTERO in Italia. Dalla notizia di reato/dai fatti, redigi un PIANO "
            "DELLE INDAGINI professionale, FONDATO SOLO sui fatti e sugli articoli forniti. NON inventare articoli. "
            "Sezioni (markdown):\n"
            "### \U0001f3af Ipotesi investigative — le versioni possibili da provare o escludere\n"
            "### \U0001f4dc Qualificazione provvisoria — il reato o i reati con l'articolo del corpus (provvisoria, non definitiva)\n"
            "### ✅ Elementi da provare — per ogni elemento: quale prova lo dimostra\n"
            "### \U0001f50e Atti d'indagine — cosa compiere (perquisizioni, sequestri, accertamenti tecnici, intercettazioni, acquisizione di dati e tabulati), in che ordine e perché\n"
            "### \U0001f465 Chi sentire — persone informate sui fatti, indagato (con le garanzie difensive), consulenti — e su cosa\n"
            "### ⏰ Termini — durata delle indagini preliminari e proroghe (verifica sulle norme, non inventare numeri)\n"
            "### ⚖️ Obiettività — anche gli elementi A FAVORE dell'indagato da cercare (art. 358 c.p.p.)\n"
            + _TETRA_IT)
        return _gen(backend, index, facts=facts, system=system, callsite="pros_plan",
                    seeds=_cpp("326", "327", "358", "335", "405", "406", "407"),
                    extra="piano delle indagini atti di indagine termini", max_tokens=max_tokens)
    system = (
        "Ti je ndihmës i një PROKURORI në Shqipëri. Nga kallëzimi/faktet, harto një PLAN HETIMI "
        "profesional, TË BAZUAR VETËM te faktet dhe te nenet e dhëna. MOS shpik nene. Jep (markdown):\n"
        "### \U0001f3af Hipotezat hetimore — versionet e mundshme që duhen provuar ose përjashtuar\n"
        "### \U0001f4dc Kualifikimi i mundshëm — vepra/at penale me nenin nga korpusi (paraprak, jo përfundimtar)\n"
        "### ✅ Elementet për t'u provuar — për secilin element: çfarë prove e provon\n"
        "### \U0001f50e Veprimet hetimore — çfarë të kryhet (kontroll, sekuestrim, ekspertim, përgjim), radha dhe përse\n"
        "### \U0001f465 Kush të pyetet — dëshmitarë, të pandehur, ekspertë — dhe çka të pyeten\n"
        "### ⏰ Afatet — afati i hetimit paraprak dhe zgjatja (verifiko me dispozitat, mos shpik numra)\n"
        "### ⚖️ Objektiviteti — edhe provat SHFAJËSUESE që duhen kërkuar (detyra e objektivitetit)\n"
        + _TETRA)
    return _gen(backend, index, facts=facts, system=system, callsite="pros_plan",
                seeds=[("kodi_proc_penale", "24"), ("kodi_proc_penale", "287"),
                       ("kodi_proc_penale", "323"), ("kodi_proc_penale", "324"),
                       ("kodi_proc_penale", "283")],
                extra="plan hetimi veprime hetimore afati", max_tokens=max_tokens)


_ACT_KINDS = {
    "kontroll": {"label": "Kërkesë për kontroll (person/vend)",
                 "seed": [("kodi_proc_penale", "202"), ("kodi_proc_penale", "204"), ("kodi_proc_penale", "205")],
                 "q": "kontroll personi vendi kushtet"},
    "sekuestrim": {"label": "Kërkesë për sekuestrim",
                   "seed": [("kodi_proc_penale", "208"), ("kodi_proc_penale", "203"), ("kodi_proc_penale", "301")],
                   "q": "sekuestrim objekti provë materiale"},
    "ekspertim": {"label": "Kërkesë për ekspertim",
                  "seed": [("kodi_proc_penale", "178"), ("kodi_proc_penale", "179"),
                           ("kodi_proc_penale", "183"), ("kodi_proc_penale", "185")],
                  "q": "ekspertim ekspert detyra pyetjet"},
    "pergjim": {"label": "Kërkesë për përgjim",
                "seed": [("kodi_proc_penale", "221"), ("kodi_proc_penale", "224"), ("kodi_proc_penale", "225")],
                "q": "përgjim kufijtë lejimi"},
}

# Stesse chiavi (l'API e l'interfaccia non cambiano), atti e norme del c.p.p.
_ACT_KINDS_IT = {
    "kontroll": {"label": "Decreto di perquisizione (personale/locale)",
                 "seed": _cpp("247", "249", "250", "251", "191"),
                 "q": "perquisizione personale locale domicilio decreto motivato"},
    "sekuestrim": {"label": "Decreto di sequestro probatorio / richiesta di sequestro preventivo",
                   "seed": _cpp("253", "257", "262", "321", "191"),
                   "q": "sequestro probatorio preventivo corpo del reato cose pertinenti"},
    "ekspertim": {"label": "Accertamento tecnico / consulenza tecnica",
                  "seed": _cpp("359", "360", "191"),
                  "q": "consulente tecnico accertamento tecnico non ripetibile avviso difensore"},
    "pergjim": {"label": "Richiesta di autorizzazione alle intercettazioni",
                "seed": _cpp("266", "267", "268", "271"),
                "q": "intercettazioni gravi indizi assolutamente indispensabili decreto autorizzazione"},
}


def list_act_kinds():
    kinds = _ACT_KINDS_IT if _lingua() == "it" else _ACT_KINDS
    return [{"key": k, "label": v["label"]} for k, v in kinds.items()]


def investigative_act(backend, index, *, kind, facts, max_tokens=2600):
    """Veprime hetimore — draft a request for a search/seizure/expertise/interception."""
    if _lingua() == "it":
        cfg = _ACT_KINDS_IT.get(kind) or _ACT_KINDS_IT["kontroll"]
        system = (
            "Sei l'assistente di un PUBBLICO MINISTERO. Redigi il DECRETO o la RICHIESTA per l'atto d'indagine '"
            + cfg["label"] + "' secondo il codice di procedura penale, FONDATO SOLO sui fatti e sugli articoli forniti. "
            "NON inventare articoli. Dove manca un dato, lascia [___]. Sezioni (markdown):\n"
            "### \U0001f4cc Base giuridica e presupposti — gli articoli del corpus e le condizioni da soddisfare\n"
            "### \U0001f9e9 Motivazione — perché l'atto è necessario e proporzionato alle indagini\n"
            "### \U0001f4dd Testo del decreto/della richiesta — completo, pronto (oggetto, luogo/persona, cosa si dispone, avvisi e garanzie per il difensore quando dovuti)\n"
            "### ⚠️ Attenzione — cosa rispettare perché l'atto non sia nullo né la prova inutilizzabile (autorizzazione del giudice quando richiesta, termini, garanzie difensive)\n"
            + _TETRA_IT)
        return _gen(backend, index, facts=facts, system=system, callsite="pros_act",
                    seeds=cfg["seed"], extra=cfg["q"], max_tokens=max_tokens)
    cfg = _ACT_KINDS.get(kind) or _ACT_KINDS["kontroll"]
    system = (
        "Ti je ndihmës i një PROKURORI. Harto KËRKESËN/URDHRIN për veprimin hetimor '" + cfg["label"]
        + "' sipas Kodit të Procedurës Penale, TË BAZUAR VETËM te faktet dhe te nenet e dhëna. MOS "
        "shpik nene. Ku mungon një e dhënë, lër [___]. Jep (markdown):\n"
        "### \U0001f4cc Baza ligjore & kushtet — nenet nga korpusi dhe kushtet që duhen plotësuar\n"
        "### \U0001f9e9 Arsyetimi — pse ky veprim është i nevojshëm dhe proporcional me hetimin\n"
        "### \U0001f4dd Kërkesa/urdhri — teksti i plotë, gati për t'u paraqitur (objekti, vendi/personi, çka kërkohet)\n"
        "### ⚠️ Kujdes — çka duhet respektuar që veprimi të mos jetë i pavlefshëm (autorizim gjyqësor nëse kërkohet, afate, të drejtat)\n"
        + _TETRA)
    return _gen(backend, index, facts=facts, system=system, callsite="pros_act",
                seeds=cfg["seed"], extra=cfg["q"], max_tokens=max_tokens)


def coercive_measure(backend, index, *, facts, max_tokens=2800):
    """Kërkesë për masë sigurimi — SENSITIVE (liberty). Strictly a draft; court decides."""
    if _lingua() == "it":
        system = (
            "Sei l'assistente di un PUBBLICO MINISTERO. Redigi una RICHIESTA DI APPLICAZIONE DI MISURA CAUTELARE "
            "PERSONALE al giudice per le indagini preliminari, secondo il c.p.p., FONDATA SOLO sui fatti e sugli "
            "articoli forniti. ⚠️ È IN GIOCO LA LIBERTÀ PERSONALE: è solo una BOZZA; decide il GIUDICE. NON "
            "presentare il carcere come scontato: esponi le condizioni in modo obiettivo e scegli la misura MENO "
            "AFFLITTIVA che basta (adeguatezza e proporzionalità). NON inventare articoli. Sezioni (markdown):\n"
            "### \U0001f4dc Reato e qualificazione — gli articoli del corpus e i limiti di pena che consentono la misura\n"
            "### \U0001f50d Gravi indizi di colpevolezza — gli elementi che li sostengono, elemento per elemento\n"
            "### ⚠️ Esigenze cautelari — pericolo di inquinamento probatorio, di fuga, di reiterazione: CONCRETE e ATTUALI, non ipotetiche\n"
            "### ⚖️ Adeguatezza e proporzionalità — perché la misura richiesta e non una meno grave (obbligo di presentazione, divieto di espatrio, obbligo/divieto di dimora, arresti domiciliari)\n"
            "### \U0001f4dd Richiesta — la misura richiesta e il testo per il GIP, con l'elenco degli elementi a favore dell'indagato che il PM deve trasmettere insieme alla richiesta\n"
            "### \U0001f6e1️ La parte della difesa — cosa obietterebbe il difensore (obiettività)\n"
            + _TETRA_IT)
        return _gen(backend, index, facts=facts, system=system, callsite="pros_measure",
                    seeds=_cpp("272", "273", "274", "275", "280", "283", "284", "285", "291", "292"),
                    extra="misure cautelari esigenze cautelari gravi indizi criteri di scelta", max_tokens=max_tokens)
    system = (
        "Ti je ndihmës i një PROKURORI. Harto një KËRKESË PËR MASË SIGURIMI drejtuar gjykatës, sipas "
        "KPP, TË BAZUAR VETËM te faktet dhe te nenet e dhëna. ⚠️ LIRIA E PERSONIT ËSHTË NË LOJË: "
        "kjo është VETËM PROJEKT-kërkesë; GJYKATA vendos. MOS rekomando arrestin si të sigurt — parashtro "
        "kushtet objektivisht dhe zgjidh masën më pak shtrënguese që mjafton. MOS shpik nene. Jep (markdown):\n"
        "### \U0001f4dc Vepra & kualifikimi — nenet nga korpusi\n"
        "### \U0001f50d Dyshimi i arsyeshëm (fumus) — provat që e mbështesin, element për element\n"
        "### ⚠️ Rreziqet (periculum) — rreziku i ikjes/përsëritjes/prishjes së provave, KONKRET (jo hamendje)\n"
        "### ⚖️ Proporcionaliteti — pse masa e kërkuar; a mjafton një masë më e butë (detyrim paraqitjeje, arrest shtëpie)?\n"
        "### \U0001f4dd Kërkesa — masa e kërkuar dhe teksti drejtuar gjykatës\n"
        "### \U0001f6e1️ Ana e mbrojtjes — çfarë do të kundërshtonte mbrojtja (objektiviteti)\n"
        + _TETRA)
    return _gen(backend, index, facts=facts, system=system, callsite="pros_measure",
                seeds=[("kodi_proc_penale", "228"), ("kodi_proc_penale", "229"),
                       ("kodi_proc_penale", "230"), ("kodi_proc_penale", "232"),
                       ("kodi_proc_penale", "237"), ("kodi_proc_penale", "238"),
                       ("kodi_proc_penale", "244")],
                extra="masë sigurimi personal arrest kushtet kriteret", max_tokens=max_tokens)


def dismissal_request(backend, index, *, facts, max_tokens=2600):
    """Kërkesë për pushim/mosfillim — SENSITIVE. Assistive draft; prosecutor decides."""
    if _lingua() == "it":
        system = (
            "Sei l'assistente di un PUBBLICO MINISTERO. Redigi una RICHIESTA DI ARCHIVIAZIONE al giudice per le "
            "indagini preliminari, secondo il c.p.p., FONDATA SOLO sui fatti e sugli articoli forniti. LA DECISIONE "
            "SPETTA AL PUBBLICO MINISTERO E POI AL GIUDICE — è solo una bozza motivata. NON inventare articoli. "
            "Sezioni (markdown):\n"
            "### \U0001f4dc Base giuridica — infondatezza della notizia di reato per mancanza di una ragionevole previsione di condanna, oppure gli altri casi di archiviazione (condizione di procedibilità mancante, reato estinto, fatto non previsto dalla legge come reato, particolare tenuità del fatto) o autore ignoto — con gli articoli del corpus\n"
            "### \U0001f9ed Motivazione — perché non c'è luogo a procedere, elemento per elemento\n"
            "### ⚖️ Possibile opposizione — ci sono elementi che imporrebbero di proseguire le indagini? (obiettività)\n"
            "### \U0001f4e2 Avvisi — alla persona offesa che ha chiesto di essere informata e, per i delitti commessi con violenza alla persona, in ogni caso; il termine per l'opposizione (verifica sulle norme fornite)\n"
            + _TETRA_IT)
        return _gen(backend, index, facts=facts, system=system, callsite="pros_dismiss",
                    seeds=_cpp("408", "409", "410", "411", "415") + _cp("131-bis"),
                    extra="richiesta di archiviazione infondatezza notizia di reato", max_tokens=max_tokens)
    system = (
        "Ti je ndihmës i një PROKURORI. Harto një KËRKESË/PROJEKT-VENDIM për PUSHIM ose MOSFILLIM të "
        "procedimit sipas KPP, TË BAZUAR VETËM te faktet dhe te nenet e dhëna. VENDIMI I TAKON "
        "PROKURORIT — ky është vetëm projekt i arsyetuar. MOS shpik nene. Jep (markdown):\n"
        "### \U0001f4dc Baza ligjore — mosfillim apo pushim, me nenin nga korpusi dhe shkakun\n"
        "### \U0001f9ed Arsyetimi — pse nuk ka vend për ndjekje (mungon fakti/prova/vepra, parashkrim etj.)\n"
        "### ⚖️ Kundërshtimi i mundshëm — a ka prova që do të kërkonin vazhdim? (objektiviteti)\n"
        "### \U0001f4e2 Njoftimi & ankimi — kush njoftohet dhe e drejta e të dëmtuarit për ankim\n"
        + _TETRA)
    return _gen(backend, index, facts=facts, system=system, callsite="pros_dismiss",
                seeds=[("kodi_proc_penale", "290"), ("kodi_proc_penale", "291"),
                       ("kodi_proc_penale", "328")],
                extra="pushim mosfillim procedimi", max_tokens=max_tokens)


def stress_test(backend, index, *, text, max_tokens=2600):
    """Test objektiviteti — stress-test a prosecutor work-product from the defense side."""
    if _lingua() == "it":
        system = (
            "Sei il DIFENSORE più bravo che legge un ATTO DEL PUBBLICO MINISTERO (richiesta di rinvio a giudizio, "
            "richiesta di misura, analisi) e cerca ogni debolezza PRIMA che il PM lo depositi. Fondati sul testo e "
            "sugli articoli forniti — non inventare. Sezioni (markdown):\n"
            "### \U0001f6e1️ Debolezze degli elementi — quale elemento resta non provato o fragile\n"
            "### ⚖️ Controdeduzioni — cosa solleverà la difesa su ogni punto\n"
            "### \U0001f6a8 Nullità e inutilizzabilità — atti senza autorizzazione, termini scaduti, avvisi omessi, diritti violati\n"
            "### \U0001f50e Elementi a discarico — cosa cercare a favore dell'indagato\n"
            "### ✅ Come rafforzare l'atto — cosa completare prima del deposito\n"
            + _TETRA_IT)
        return _gen(backend, index, facts=text, system=system, callsite="pros_stress",
                    seeds=_cpp("178", "180", "181", "191", "407"), intro=_P["it"]["stress"],
                    extra="nullità inutilizzabilità prova termini", max_tokens=max_tokens)
    system = (
        "Ti je AVOKATI MBROJTËS më i zoti, që lexon një AKT TË PROKURORISË (aktakuzë, kërkesë mase, "
        "analizë) dhe kërkon çdo dobësi PARA se ta paraqesë prokurori. Bazohu te teksti dhe te nenet e "
        "dhëna — mos shpik. Jep (markdown):\n"
        "### \U0001f6e1️ Dobësitë e provave — cili element mbetet i paprovuar ose i dobët\n"
        "### ⚖️ Kundër-argumentet — çfarë do të ngrejë mbrojtja për çdo pikë\n"
        "### \U0001f6a8 Pavlefshmëritë procedurale — veprime pa autorizim, afate të shkelura, të drejta të cenuara\n"
        "### \U0001f50e Provat shfajësuese — çka duhet kërkuar në favor të të pandehurit\n"
        "### ✅ Si të forcohet akti — çka duhet plotësuar para paraqitjes\n"
        + _TETRA)
    return _gen(backend, index, facts=text, system=system, callsite="pros_stress",
                seeds=None, intro=_P["sq"]["stress"], extra="dobësi pavlefshmëri provë",
                max_tokens=max_tokens)


# ───────────────────────── (ii) CITIZEN-FACING ─────────────────────────

def citizen_complaint(backend, index, *, facts, max_tokens=2800):
    """Kallëzim penal builder + office router (Prokuroria vs SPAK) + attachments."""
    if _lingua() == "it":
        system = (
            "Sei l'assistente che aiuta un CITTADINO a preparare una DENUNCIA o una QUERELA corretta (ausilio, non "
            "consulenza legale ufficiale). Dal racconto, redigi l'atto COMPLETO e strutturato, FONDATO sui fatti e "
            "sugli articoli forniti. NON inventare articoli. Dove manca un dato, lascia [___]. Sezioni (markdown):\n"
            "### \U0001f4dd LA DENUNCIA / LA QUERELA — testo pronto: chi la presenta, i fatti (chi/cosa/quando/dove), il danno, le prove, le persone coinvolte (se note), la richiesta di procedere e di essere informato dell'eventuale richiesta di archiviazione. Di' se il reato è procedibile a QUERELA (con il suo termine) o d'ufficio (DENUNCIA)\n"
            "### \U0001f4cd Dove si presenta — alla Procura della Repubblica presso il Tribunale competente o a un ufficio di Polizia o dei Carabinieri; per mafia e terrorismo la competenza è della procura distrettuale; per le frodi al bilancio dell'Unione europea la Procura europea (EPPO) — spiega in breve perché\n"
            "### \U0001f4ce Documenti da allegare — elenco concreto secondo il tipo di reato\n"
            "### ⚖️ I tuoi diritti come persona offesa — in breve: informazioni, difensore, costituzione di parte civile, opposizione all'archiviazione\n"
            + _TETRA_IT)
        return _gen(backend, index, facts=facts, system=system, callsite="pros_complaint",
                    seeds=_cpp("333", "336", "337", "90", "90-bis", "101", "408") + _cp("124"),
                    intro=_P["it"]["citt"], extra="denuncia querela persona offesa diritti", max_tokens=max_tokens)
    system = (
        "Ti je ndihmës që e ndihmon një QYTETAR të përgatisë një KALLËZIM PENAL të saktë (ndihmesë, jo "
        "këshillë ligjore zyrtare). Nga rrëfimi, harto kallëzimin TË PLOTË dhe të strukturuar, TË BAZUAR "
        "te faktet dhe te nenet e dhëna. MOS shpik nene. Ku mungon një e dhënë, lër [___]. Jep (markdown):\n"
        "### \U0001f4dd KALLËZIMI — teksti gati për dorëzim: kallëzuesi, të dhënat, RRETHANAT (kush/çfarë/kur/ku), "
        "dëmi, provat, personat e përfshirë (nëse dihen), dhe KËRKESA për fillim procedimi\n"
        "### \U0001f4cd Ku dorëzohet — Prokuroria pranë gjykatës kompetente sipas vendit; ose SPAK nëse është "
        "korrupsion/krim i organizuar/funksionarë të lartë (shpjego shkurt pse)\n"
        "### \U0001f4ce Dokumentet për t'u bashkangjitur — lista konkrete sipas llojit të veprës\n"
        "### ⚖️ Të drejtat e tua si i dëmtuar — shkurt (neni 58 KPP) dhe se mund të njoftohesh e të ankohesh\n"
        + _TETRA)
    return _gen(backend, index, facts=facts, system=system, callsite="pros_complaint",
                seeds=[("kodi_proc_penale", "283"), ("kodi_proc_penale", "58"),
                       ("kodi_proc_penale", "290")],
                intro=_P["sq"]["citt"], extra="kallëzim i dëmtuar të drejtat",
                max_tokens=max_tokens)


def victim_rights(backend, index, *, facts, max_tokens=2400):
    """Të drejtat e viktimës + shpjegim i fazave — plain-language."""
    if _lingua() == "it":
        system = (
            "Sei l'assistente che spiega a un CITTADINO, PERSONA OFFESA da un reato, i suoi diritti e le fasi del "
            "processo penale, in modo semplice e chiaro (ausilio, non consulenza ufficiale). Fondati sui fatti e sugli "
            "articoli forniti — non inventare. Sezioni (markdown):\n"
            "### ⚖️ I tuoi diritti — cosa puoi chiedere (informazioni sul procedimento, nominare un difensore, presentare memorie e indicare elementi di prova, essere avvisato della richiesta di archiviazione e opporti, comunicazioni sulla scarcerazione o evasione nei delitti con violenza alla persona, costituirti parte civile per il risarcimento)\n"
            "### \U0001f5fa️ Le fasi e cosa aspettarti — indagini preliminari, archiviazione o azione penale, udienza preliminare, dibattimento — in parole semplici\n"
            "### ⏰ I termini che ti riguardano — cosa succede quando e entro quanto puoi agire (verifica sulle norme, non inventare numeri)\n"
            "### ✅ I tuoi prossimi passi — concreti\n"
            + _TETRA_IT)
        return _gen(backend, index, facts=facts, system=system, callsite="pros_victim",
                    seeds=_cpp("90", "90-bis", "90-ter", "101", "74", "408", "410", "335"),
                    intro=_P["it"]["vitt"], extra="persona offesa diritti informazioni fasi termini", max_tokens=max_tokens)
    system = (
        "Ti je ndihmës që i shpjegon një QYTETARI TË DËMTUAR të drejtat dhe fazat e procesit penal, "
        "thjesht dhe qartë (ndihmesë, jo këshillë zyrtare). Bazohu te faktet dhe te nenet e dhëna — mos "
        "shpik. Jep (markdown):\n"
        "### ⚖️ Të drejtat e tua — çfarë mund të kërkosh (informim, akses në akte, kërkim provash, "
        "njoftim për arrestin/lirimin, ankim, dëmshpërblim si paditës civil) — bazuar në nenin 58 KPP\n"
        "### \U0001f5fa️ Fazat & çfarë presin — hetimi paraprak, vendimi (akuzë/pushim), gjykimi — thjesht\n"
        "### ⏰ Afatet që të interesojnë — kur pritet çfarë dhe brenda sa kohe mund të veprosh (verifiko, mos shpik numra)\n"
        "### ✅ Hapat e tu të radhës — konkret\n"
        + _TETRA)
    return _gen(backend, index, facts=facts, system=system, callsite="pros_victim",
                seeds=[("kodi_proc_penale", "58"), ("kodi_proc_penale", "292"),
                       ("kodi_proc_penale", "329"), ("kodi_proc_penale", "323")],
                intro=_P["sq"]["vitt"], extra="të drejtat i dëmtuar faza afati",
                max_tokens=max_tokens)


def dismissal_appeal(backend, index, *, facts, max_tokens=2600):
    """Ankim kundër pushimit/mosfillimit — decode + draft the victim's appeal. SENSITIVE deadline."""
    if _lingua() == "it":
        system = (
            "Sei l'assistente che aiuta una PERSONA OFFESA a capire una RICHIESTA o un PROVVEDIMENTO DI ARCHIVIAZIONE "
            "e a preparare l'OPPOSIZIONE alla richiesta di archiviazione — oppure, se l'archiviazione è già stata "
            "disposta con un vizio, il RECLAMO per nullità (ausilio, non consulenza ufficiale). Fondati sui fatti e "
            "sugli articoli forniti — non inventare. ⚠️ I TERMINI sono decisivi — sottolinea che vanno verificati con "
            "un avvocato e sulle norme. Sezioni (markdown):\n"
            "### \U0001f50e Cosa dice il provvedimento — spiegazione semplice delle ragioni dell'archiviazione\n"
            "### ⚖️ C'è base per opporsi — i punti deboli; ricorda che l'opposizione deve indicare, a pena di inammissibilità, l'oggetto dell'investigazione suppletiva e i relativi elementi di prova\n"
            "### \U0001f4dd L'OPPOSIZIONE (o il RECLAMO) — testo strutturato, rivolto al giudice competente\n"
            "### ⏰ Il termine — entro quando va presentata (VERIFICA sulle norme/con l'avvocato — non tardare)\n"
            + _TETRA_IT)
        return _gen(backend, index, facts=facts, system=system, callsite="pros_appeal",
                    seeds=_cpp("408", "409", "410", "410-bis", "411"),
                    intro=_P["it"]["app"], extra="opposizione archiviazione termine reclamo nullità", max_tokens=max_tokens)
    system = (
        "Ti je ndihmës që e ndihmon një QYTETAR TË DËMTUAR të kuptojë një VENDIM PUSHIMI/MOSFILLIMI dhe "
        "të përgatisë ANKIMIN në gjykatë (ndihmesë, jo këshillë zyrtare). Bazohu te faktet dhe te nenet e "
        "dhëna — mos shpik. ⚠️ AFATET E ANKIMIT janë vendimtare — thekso që të verifikohen me "
        "avokat/dispozitat. Jep (markdown):\n"
        "### \U0001f50e Çfarë thotë vendimi — shpjegim i thjeshtë i arsyeve të pushimit/mosfillimit\n"
        "### ⚖️ A ka bazë ankimi — pikat e dobëta të vendimit dhe të drejta e ankimit (neni 291/329 KPP)\n"
        "### \U0001f4dd ANKIMI — teksti i strukturuar drejtuar gjykatës kompetente\n"
        "### ⏰ Afati — brenda sa kohe duhet paraqitur (VERIFIKO me dispozitat/avokat — mos u vono)\n"
        + _TETRA)
    return _gen(backend, index, facts=facts, system=system, callsite="pros_appeal",
                seeds=[("kodi_proc_penale", "291"), ("kodi_proc_penale", "292"),
                       ("kodi_proc_penale", "328"), ("kodi_proc_penale", "329"),
                       ("kodi_proc_penale", "284")],
                intro=_P["sq"]["app"], extra="ankim pushim mosfillim afati",
                max_tokens=max_tokens)


def delay_complaint(backend, index, *, facts, max_tokens=2400):
    """Ankesa për vonesa — escalation to the office + Avokati i Popullit + doc-copy request."""
    if _lingua() == "it":
        system = (
            "Sei l'assistente che aiuta un CITTADINO, PERSONA OFFESA, a sollecitare un procedimento penale fermo "
            "(ausilio, non consulenza ufficiale). Fondati sui fatti e sugli articoli forniti — non inventare. "
            "Sezioni (markdown):\n"
            "### \U0001f4e8 Istanza al Pubblico Ministero — testo che sollecita la definizione e chiede informazioni sullo stato del procedimento, richiamando i termini delle indagini preliminari\n"
            "### \U0001f3db️ Richiesta di avocazione al Procuratore generale — quando i termini sono scaduti senza che il PM abbia chiesto l'archiviazione o esercitato l'azione penale: testo breve\n"
            "### \U0001f4c4 Richiesta di copie degli atti — il testo, e quali atti si possono ottenere e quando\n"
            "### ✅ Consigli pratici — come depositarle (protocollo, PEC) e cosa conservare\n"
            + _TETRA_IT)
        return _gen(backend, index, facts=facts, system=system, callsite="pros_delay",
                    seeds=_cpp("335", "405", "406", "407", "412", "413", "116"),
                    intro=_P["it"]["del"], extra="termini indagini avocazione sollecito copie atti", max_tokens=max_tokens)
    system = (
        "Ti je ndihmës që e ndihmon një QYTETAR të ankohet për VONESA në hetim/procedim (ndihmesë, jo "
        "këshillë zyrtare). Bazohu te faktet dhe te nenet e dhëna — mos shpik. Jep (markdown):\n"
        "### \U0001f4e8 Ankesa te Prokuroria — teksti drejtuar prokurorit/kryeprokurorit, që kërkon "
        "përshpejtim dhe informim mbi ecurinë (referto afatin e hetimit, neni 323/324 KPP)\n"
        "### \U0001f3db️ Ankesa te Avokati i Popullit — teksti i shkurtër i ankesës për vonesë/mosveprim\n"
        "### \U0001f4c4 Kërkesë për kopje aktesh — teksti për të marrë kopje të akteve të çështjes\n"
        "### ✅ Këshilla praktike — si t'i protokollosh dhe çka të ruash\n"
        + _TETRA)
    return _gen(backend, index, facts=facts, system=system, callsite="pros_delay",
                seeds=[("kodi_proc_penale", "323"), ("kodi_proc_penale", "324"),
                       ("kodi_proc_penale", "58")],
                intro=_P["sq"]["del"], extra="vonesa ankesa afati hetimit",
                max_tokens=max_tokens)
