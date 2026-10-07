#!/usr/bin/env python3
"""v9.380 — la prova DALL'INIZIO ALLA FINE della ricerca delle leggi: domande scritte come le scrive un avvocato →
triage VERO del cervello (riscrive nei termini del codice) → `_retrieve` + ancore + nene chiesti → l'articolo decisivo
è nel blocco che il senior legge? Costa un triage (modello veloce) per domanda. Nessuna risposta viene scritta.

    docker exec super-avvocato python3 tools/eval_triage_ricerca.py
"""
import sys, time, threading
sys.path.insert(0, "/app")
from src import brain as B

CASI = [  # (giurisdizione, domanda dell'avvocato, articoli di cui almeno uno DEVE essere nel blocco)
    ("AL", "Vëllai i klientit kërkohej nga policia për vjedhje dhe klienti e mbajti dy ditë në shtëpi. A rrezikon përgjegjësi penale?", [("kodi_penal", "302")]),
    ("AL", "Klienti u mbajt 8 muaj në paraburgim dhe u pafajësua me vendim të formës së prerë. Çfarë kompensimi i takon dhe brenda çfarë afati?", [("kodi_proc_penale", "268"), ("kodi_proc_penale", "269")]),
    ("AL", "Punëdhënësi e pushoi klientin pas 8 vitesh pa asnjë paralajmërim. Çfarë i takon?", [("kodi_punes", "155"), ("kodi_punes", "146")]),
    # v9.400 — il preavviso (KP 143) decide paga dovuta e inizio dei 180 giorni: non entrava in nessun licenziamento misurato
    ("AL", "Klienti u pushua me gojë pas 7 vitesh pune; punëdhënësi thotë se ai dha dorëheqjen. Çfarë i takon dhe brenda sa kohe duhet padia?", [("kodi_punes", "143")]),
    ("AL", "Qiramarrësi nuk paguan qiranë prej 5 muajsh. Si ta nxjerr nga banesa?", [("kodi_civil", "801"), ("kodi_civil", "698"), ("kodi_civil", "703")]),
    # v9.394 — il caso del banco di prova che NESSUNA variante risolve (26 set: legge sugli stranieri 72-73 e premio di anzianità
    # mancati 6 giri su 6): licenziamento di un lavoratore straniero con permesso unico
    ("AL", "Shtetas i huaj, leje qëndrimi për punë, 3 vjet punë, zgjidhje e menjëhershme e kontratës pa shkak, pa afat njoftimi.", [("ligji_te_huajt", "72"), ("kodi_punes", "152")]),
    # v9.391 — stupefacenti (ligji 7975/1995 e 61/2023 nel corpus)
    ("AL", "Klienti u kap nga policia me 3 gram kokainë në xhep. Çfarë rrezikon dhe a mund të mbrohemi me përdorimin vetjak?", [("kodi_penal", "283")]),
    ("AL", "A lejohet në Shqipëri kultivimi i kanabisit për qëllime mjekësore dhe çfarë licence duhet?", [("ligji_kanabisi_mjekesor", "14"), ("ligji_kanabisi_mjekesor", "15"), ("ligji_kanabisi_mjekesor", "4"), ("ligji_kanabisi_mjekesor", "5"), ("ligji_kanabisi_mjekesor", "1")]),
    ("AL", "Ketamina konsiderohet lëndë narkotike sipas ligjit shqiptar apo është lëndë e kontrolluar?", [("ligji_lendet_narkotike", "2"), ("ligji_lendet_narkotike", "shtojca"), ("ligji_lendet_narkotike", "3")]),
    ("AL", "Farmacia e klientit shiste tramadol pa recetë mjekësore. Çfarë sanksionesh rrezikon?", [("ligji_lendet_narkotike", "101"), ("ligji_lendet_narkotike", "72"), ("ligji_lendet_narkotike", "65"), ("ligji_lendet_narkotike", "64"),
                                                                                                    ("ligji_barnat", "52"), ("ligji_barnat", "63")]),   # v9.502: il tramadolo non è in nessuna lista: decide la legge sui farmaci
    ("AL", "Klienti u kap në mars 2026 me disa gram HHC të blera në internet. A është vepër penale?", [("ligji_lendet_narkotike", "shtojca"), ("kodi_penal", "283")]),
    ("AL", "Një fermer kishte mbjellë 200 bimë kanabisi në tokën e tij. Çfarë dënimi rrezikon?", [("kodi_penal", "284")]),
    ("AL", "Klienti ka një borxh nga viti 2012 dhe kreditori tani e padit. A ka rënë në parashkrim?", [("kodi_civil", "114"), ("kodi_civil", "115")]),
    ("AL", "Dogana i sekuestroi klientit makinën për kontrabandë. Si ta kundërshtojmë?", [("kodi_doganor", "272"), ("kodi_doganor", "274"), ("ligji_gjykatat_administrative", "18")]),
    ("AL", "Bashkia i refuzoi klientit lejen e ndërtimit. Brenda sa ditësh e padisim në gjykatën administrative?", [("ligji_gjykatat_administrative", "18")]),
    ("AL", "Klientja kërkon divorc, bashkëshorti nuk pranon. Si shkojmë dhe kush merr fëmijët?", [("kodi_familjes", "129"), ("kodi_familjes", "132"), ("kodi_familjes", "155")]),
    ("AL", "Babai i klientit vdiq pa testament, ka lënë gruan dhe tre fëmijë. Si ndahet trashëgimia?", [("kodi_civil", "361")]),
    ("AL", "Klienti u godit nga një makinë në vendkalim për këmbësorë dhe ka dëme shëndetësore. Kë padisim dhe për çfarë?", [("kodi_civil", "608"), ("kodi_civil", "640"), ("ligji_sigurimi_mjeteve", "9")]),
    ("AL", "Një vendim i Gjykatës së Lartë e shkel të drejtën e klientit për proces të rregullt. Si i drejtohemi Gjykatës Kushtetuese dhe brenda sa kohe?", [("ligji_gjykata_kushtetuese", "71/a"), ("kushtetuta", "131")]),
    # v9.492 — prova viva in Chrome del 4 ott: c'era il KPC 443 (15 giorni), mancava il 444 (decorrenza: dal giorno dopo la notifica)
    ("AL", "Gjykata e shkallës së parë e rrëzoi padinë me vendim të shpallur më 15 shtator, na u njoftua më 22 shtator. Brenda cilës datë bëjmë ankim në apel?", [("kodi_proc_civile", "444")]),
    # v9.504 — la prescrizione dei crediti di lavoro: KP 203 (3 anni), non il KC 114
    ("AL", "Punëdhënësi nuk i ka paguar klientit pagat e tetorit dhe nëntorit 2022. A janë parashkruar?", [("kodi_punes", "203")]),
    ("IT", "Il datore di lavoro non ha pagato al cliente gli stipendi di ottobre e novembre 2020. Sono prescritti?", [("codice_civile", "2948")]),
    ("AL", "Qiramarrësi nuk më ka paguar qiranë e vitit 2021. A është parashkruar e drejta për ta kërkuar?", [("kodi_civil", "115")]),
    ("AL", "Gjykata administrative e shkallës së parë e rrëzoi padinë tonë kundër bashkisë. Deri kur mund të bëjmë apel?", [("ligji_gjykatat_administrative", "44"), ("kodi_proc_civile", "443")]),
    ("IT", "Il cliente ha subito un incidente stradale nel marzo 2023 e non ha ancora chiesto il risarcimento. È prescritto?", [("codice_civile", "2947")]),
    # v9.524 — prova viva in Chrome del 6 ott: il ramo del fatto-reato senza 590-bis c.p. nel blocco
    ("IT", "Il mio cliente ha avuto un incidente stradale il 10 marzo 2024 (auto contro auto, colpa dell'altro conducente). Entro quando deve chiedere il risarcimento del danno prima che si prescriva?", [("codice_penale", "590-bis")]),
    ("IT", "Il cliente, albanese, è sposato da tre anni con una cittadina italiana e vive in Italia. Come ottiene la cittadinanza?", [("cittadinanza", "10")]),
    # v9.517 — la revoca del permesso di soggiorno: l'art. 73 della 79/2021 rinvia per nome al KPA (termine del ricorso: KPA 132)
    ("AL", "Klientit i anuloi policia lejen e qëndrimit pasi humbi punën. Brenda sa kohe mund të bëjë ankim dhe te kush?", [("kodi_proc_admin", "132")]),
    # v9.511 — banco di prova della v9.510: la risposta parla di trascrizione 20 volte e non nomina mai l'art. 2644 c.c.
    ("IT", "Il mio cliente vuole acquistare un appartamento. Dalla visura ipotecaria risultano un'ipoteca volontaria a favore di una banca e un pignoramento trascritto su 1/2 dell'immobile. La vendita è possibile? Quali formalità bloccano e quali condizionano l'atto?", [("codice_civile", "2644")]),
    # v9.500 — il CALCOLO del termine (giorno di riposo): prova viva del 4 ott, il senior fissava una domenica
    ("AL", "Dje (3 tetor) klientit iu njoftua vendimi i arsyetuar civil që ia rrëzoi padinë. Deri kur mund të bëjmë apel?", [("kodi_proc_civile", "148")]),
    ("AL", "Klientit tim iu dha dënim me burgim nga gjykata e shkallës së parë, vendimi u njoftua dje. Deri kur bëjmë ankim në apel?", [("kodi_proc_penale", "144")]),
    # v9.487 — prova viva 3 ott: il recupero portava solo la legge sulle armi, il KP 278 lo aggiungeva il Kërkuesi
    ("AL", "Klienti u kap nga policia me një pistoletë pa leje në makinë, dhe në shtëpi i gjetën 20 fishekë luftarakë. Çfarë dënimi rrezikon dhe si mbrohemi?", [("kodi_penal", "278")]),
    ("AL", "Policia i gjeti klientit një thikë të madhe në makinë. A është vepër penale?", [("kodi_penal", "279")]),
    ("IT", "Il cliente, amministratore di una sh.p.k. albanese, residente in Italia, guida l'auto aziendale targata albanese. Rischia la confisca?", [("reg_ue_2015_2446", "215"), ("codice_strada", "93-bis")]),
    ("IT", "Il credito del cliente risale al 2013 e il debitore non ha mai pagato: è prescritto?", [("codice_civile", "2946")]),
    ("IT", "Il cliente è stato licenziato per giustificato motivo oggettivo, assunto nel 2018 in azienda con 30 dipendenti. Che tutele ha?", [("tutele_crescenti", "3")]),
    # v9.525 — risposte vere del 1° e 3 ott: NASpI senza l'art. 4 (misura) e senza il 6 (68 giorni)
    ("IT", "Il cliente è stato licenziato a settembre dopo 4 anni di lavoro: quanto prende di NASpI, per quanto tempo ed entro quando fa domanda?", [("naspi", "4")]),
    ("IT", "Il cliente è stato licenziato per giusta causa dopo una contestazione disciplinare. Cosa può fare e cosa gli spetta?", [("naspi", "6")]),
    # v9.527 — i temi più frequenti degli albanesi in Italia (immigrazione, patente, cittadinanza): l'articolo che decide entra?
    ("IT", "[migr] Il permesso di soggiorno per lavoro del cliente albanese è scaduto da tre mesi e non ha chiesto il rinnovo. Può ancora rinnovarlo o rischia l'espulsione?", [("tu_immigrazione", "5"), ("tu_immigrazione", "13")]),
    ("IT", "[migr] Il cliente albanese lavora in Italia e vuole far venire la moglie e i due figli minori. Quali requisiti servono per il ricongiungimento familiare?", [("tu_immigrazione", "29")]),
    ("IT", "[migr] Il cliente vive in Italia da due anni e guida ancora con la patente albanese. È valida o deve convertirla?", [("codice_strada", "135")]),
    ("IT", "[migr] Al cliente è stato notificato ieri un decreto di espulsione del Prefetto. Entro quando e davanti a chi lo impugniamo?", [("tu_immigrazione", "13")]),
    ("IT", "[migr] Il cliente albanese risiede legalmente in Italia da undici anni. Può chiedere la cittadinanza italiana e a quali condizioni?", [("cittadinanza", "9")]),
    ("IT", "[migr] Il cliente ha il permesso di soggiorno da sei anni con reddito stabile. Può ottenere il permesso UE per soggiornanti di lungo periodo?", [("tu_immigrazione", "9")]),
    # v9.527 — domande frequenti degli avvocati ITALIANI
    ("IT", "[frek-it] Al cliente è stato notificato un decreto ingiuntivo di 18.000 euro il 1° ottobre. Entro quando fa opposizione?", [("codice_procedura_civile", "641")]),
    ("IT", "[frek-it] L'inquilino del cliente non paga l'affitto da quattro mesi. Come lo mandiamo via?", [("codice_procedura_civile", "658")]),
    ("IT", "[frek-it] La cliente si separa dal marito e hanno due figli minori. Come si stabilisce l'assegno di mantenimento per i figli?", [("codice_civile", "337-ter")]),
    ("IT", "[frek-it] Il cliente ha ricevuto una multa da autovelox notificata ieri. Entro quando e a chi può fare ricorso?", [("codice_strada", "204-bis"), ("codice_strada", "203")]),
    ("IT", "[frek-it] Il cliente è stato aggredito e ferito lievemente un mese fa. Entro quando deve presentare querela?", [("codice_penale", "124")]),
    ("IT", "[frek-it] Il datore ha detto al cliente a voce di non tornare più al lavoro, senza nessuna lettera. Cosa fa il cliente?", [("licenziamenti_individuali", "2")]),
    ("IT", "[frek-it2] Il padre del cliente è morto lasciando più debiti che beni. Come evita il cliente di pagare i debiti del padre?", [("codice_civile", "519"), ("codice_civile", "484")]),
    ("IT", "[frek-it2] Un creditore vuole pignorare lo stipendio del cliente. Quanto gli possono prendere ogni mese?", [("codice_procedura_civile", "545")]),
    ("IT", "[frek-it2] La cliente è caduta su una buca del marciapiede comunale e si è rotta il polso. Chi risponde e cosa deve provare?", [("codice_civile", "2051")]),
    ("IT", "[frek-it2] Il cliente coltiva e recinta da 25 anni un terreno del vicino senza che nessuno abbia mai detto nulla. Può diventarne proprietario?", [("codice_civile", "1158")]),
    ("IT", "[frek-it2] Il cliente divorzia dopo 20 anni di matrimonio; la moglie non ha mai lavorato. Le spetta l'assegno divorzile?", [("divorzio", "5")]),
    # v9.530 — quinto giro (riti e benefici penali, successioni, lavoro a termine)
    ("IT", "[frek-it5] Il cliente è imputato per lesioni personali: conviene il rito abbreviato e di quanto si riduce la pena?", [("codice_procedura_penale", "442")]),
    ("IT", "[frek-it5] Il cliente, accusato di furto aggravato, vuole patteggiare. Come funziona e che pena può concordare?", [("codice_procedura_penale", "444")]),
    ("IT", "[frek-it5] Il cliente incensurato è imputato di guida senza patente e lesioni lievi: può chiedere la messa alla prova?", [("codice_penale", "168-bis")]),
    ("IT", "[frek-it5] Il cliente è stato condannato a un anno e sei mesi; non ha precedenti. Può ottenere la sospensione condizionale?", [("codice_penale", "163")]),
    ("IT", "[frek-it5] Il nonno ha lasciato un testamento scritto a mano ma senza data. È valido?", [("codice_civile", "602")]),
    ("IT", "[frek-it5] Il padre ha lasciato tutto alla seconda moglie escludendo i due figli. Cosa spetta ai figli?", [("codice_civile", "537")]),
    ("IT", "[frek-it5] Il cliente ha donato una casa al figlio, che ora lo ha aggredito e lo ingiuria. Può revocare la donazione?", [("codice_civile", "801")]),
    ("IT", "[frek-it5] Il cliente lavora con contratti a termine rinnovati da 30 mesi nella stessa azienda. Può chiedere l'assunzione a tempo indeterminato?", [("contratti_lavoro", "19")]),
    ("AL", "[frek5] Klienti u dënua me 2 vjet burg për herë të parë. A mund t'i pezullohet ekzekutimi i dënimit?", [("kodi_penal", "59")]),
    ("AL", "[frek5] Klienti akuzohet për vjedhje dhe dëshiron gjykim të shkurtuar. Si funksionon dhe sa ulet dënimi?", [("kodi_proc_penale", "403"), ("kodi_proc_penale", "406")]),
    # v9.529 — quarto giro
    ("IT", "[frek-it4] La cliente vuole separarsi perché il marito la tradisce da anni. Può chiedere che la separazione sia addebitata a lui?", [("codice_civile", "151")]),
    ("IT", "[frek-it4] Il figlio del cliente ha 24 anni, ha lasciato l'università e non lavora. Il padre deve ancora mantenerlo?", [("codice_civile", "337-septies")]),
    ("IT", "[frek-it4] Il cane del vicino ha morso il figlio del cliente al parco. Chi risponde dei danni?", [("codice_civile", "2052")]),
    ("IT", "[frek-it4] Il cliente ha firmato un preliminare per comprare casa ma il venditore ora si rifiuta di fare il rogito. Cosa possiamo fare?", [("codice_civile", "2932")]),
    ("IT", "[frek-it4] Il cliente ha versato 20.000 euro di caparra confirmatoria e il venditore non vuole più vendere. Può avere il doppio?", [("codice_civile", "1385")]),
    ("IT", "[frek-it4] L'assemblea di condominio ha approvato una spesa che il cliente ritiene illegittima; lui era assente. Entro quando la impugna?", [("codice_civile", "1137")]),
    ("IT", "[frek-it4] Il cliente è in malattia da otto mesi e teme di essere licenziato. Fino a quando ha diritto alla conservazione del posto?", [("codice_civile", "2110")]),
    ("AL", "[frek4] Gjykata e Apelit la në fuqi vendimin kundër klientit. A mund të bëjmë rekurs në Gjykatën e Lartë dhe për çfarë shkaqesh?", [("kodi_proc_civile", "472")]),
    ("AL", "[frek4] Klienti dha 5 mijë euro kapar për një shtëpi dhe shitësi tani nuk do ta shesë më. A mund t'i kërkojë dyfishin?", [("kodi_civil", "602")]),
    # v9.528 — terzo giro di domande frequenti
    ("IT", "[frek-it3] Il cliente ha rubato al supermercato due confezioni di carne per 15 euro, incensurato. Può evitare la condanna?", [("codice_penale", "131-bis")]),
    ("IT", "[frek-it3] Il cliente è stato fermato alla guida con un tasso alcolemico di 1,3 g/l. Cosa rischia?", [("codice_strada", "186")]),
    ("IT", "[frek-it3] La cliente subisce da anni insulti e spinte dal marito convivente. Quale reato e come la tuteliamo subito?", [("codice_penale", "572")]),
    ("IT", "[frek-it3] Il datore non paga lo stipendio al cliente da tre mesi. Può dimettersi subito senza preavviso?", [("codice_civile", "2119")]),
    ("IT", "[frek-it3] Il cliente ha comprato casa sei mesi fa e ha scoperto infiltrazioni nascoste nel bagno. Cosa può chiedere al venditore e entro quando?", [("codice_civile", "1490"), ("codice_civile", "1495")]),
    ("IT", "[frek-it3] Dall'attico di uso esclusivo del vicino entra acqua nell'appartamento del cliente. Chi paga la riparazione del lastrico?", [("codice_civile", "1126")]),
    ("IT", "[frek-it3] Il cliente ha comprato un telefono che dopo otto mesi non si accende più e il negozio rifiuta la riparazione. Che diritti ha?", [("codice_consumo", "130"), ("codice_consumo", "135-bis"), ("codice_consumo", "133")]),
    ("IT", "[frek-it3] L'inquilino del cliente vuole lasciare la casa dopo un anno di un contratto 4+4 per un trasferimento di lavoro. Con quale preavviso?", [("locazioni_abitative", "3"), ("locazioni_immobili_urbani", "4"), ("locazioni_immobili_urbani", "27")]),
    ("AL", "[frek3] Klientin e ndaloi policia duke drejtuar makinën i dehur, me 1,5 gram alkool. Çfarë rrezikon?", [("kodi_penal", "291")]),
    ("AL", "[frek3] Klienti u kap duke vjedhur në një dyqan sende me vlerë 20 mijë lekë. Çfarë dënimi rrezikon?", [("kodi_penal", "134")]),
    ("AL", "[frek3] Një person i mori klientit 5 mijë euro duke i premtuar një vizë pune për Gjermani dhe u zhduk. Çfarë vepre është?", [("kodi_penal", "143")]),
    ("AL", "[frek3] Klienti bleu një shtëpi me një marrëveshje të shkruar me dorë dhe pagoi paratë, pa noter. Është i zoti i shtëpisë?", [("kodi_civil", "83")]),
    # v9.527 — domande frequenti degli avvocati albanesi (testamento, diffamazione): l'articolo che decide entra?
    ("AL", "[frek] Babai i klientit la me testament gjithë pasurinë vëllait të madh; klienti ishte 16 vjeç kur babai vdiq. A ka të drejtë në trashëgimi?", [("kodi_civil", "379")]),
    ("AL", "[frek] Gjyshi la një testament të shtypur në kompjuter dhe të nënshkruar me dorë. A është i vlefshëm?", [("kodi_civil", "393"), ("kodi_civil", "404")]),
    ("AL", "[frek] Një person publikoi në Facebook se klienti im është hajdut dhe mashtrues, gjë që nuk është e vërtetë. Çfarë mund të bëjmë?", [("kodi_penal", "120")]),
    ("AL", "[frek] Klientja u divorcua një vit më parë dhe ish-bashkëshorti nuk paguan asgjë për djalin 8 vjeç. Si e detyrojmë të paguajë ushqimin?", [("kodi_familjes", "197"), ("kodi_familjes", "161")]),
    ("AL", "[frek] Klienti punoi dy vjet në një restorant pa kontratë të shkruar dhe tani pronari e largoi. A ka të drejta?", [("kodi_punes", "21")]),
    ("AL", "[frek] Punëdhënësi e detyron klientin të punojë 12 orë në ditë pa ia paguar orët shtesë. Çfarë i takon?", [("kodi_punes", "91")]),
    ("AL", "[frek2] Klienti e punon dhe e ka rrethuar prej 25 vjetësh një tokë që në hipotekë është e fqinjit. A mund të bëhet pronar?", [("kodi_civil", "169")]),
    ("AL", "[frek2] Burri i klientes e shiti shtëpinë ku jetojnë me fëmijët pa e pyetur atë. Shtëpia u ble gjatë martesës. Çfarë mund të bëjë?", [("kodi_familjes", "57"), ("kodi_familjes", "60")]),
    ("AL", "[frek2] Klientja i tha punëdhënësit se është shtatzënë dhe pas një jave e hoqën nga puna. A është e ligjshme?", [("kodi_punes", "105/a"), ("kodi_punes", "146")]),
]


def main() -> int:
    sa = B.SuperAvvocato()
    if getattr(sa, "index_it", None) is None:          # l'indice italiano lo carica l'app web all'avvio, non il cervello
        from pathlib import Path
        from src.retrieval import ArticleIndex
        sa.index_it = ArticleIndex.load(Path("/app/data/index/bm25_it.pkl"))
    solo = [x for x in sys.argv[1:] if not x.startswith("-")]
    ok = 0; t0 = time.time()
    for jur, q, exp in [c for c in CASI if not solo or any(w.lower() in c[1].lower() for w in solo)]:
        B.set_request_jurisdiction(jur)
        try:
            sa._jurisdiction_ctx.code = jur
        except Exception:  # noqa: BLE001
            pass
        tr = sa._triage(q, [], None)
        ret = sa._retrieve(tr)
        ret = sa._ankoro_citimet(q, ret, areas=getattr(tr, "areas", None))
        ret = sa._aggiungi_previgenti(ret)          # v9.492: la stessa catena della chat
        ret = sa._aggiungi_rinvii(ret)
        ret = sa._aggiungi_rinvio_kpa(ret)      # v9.517
        ret = sa._aggiungi_richiami_inversi(ret)
        if "--kerkuesi" in sys.argv:                   # il percorso vero: anche il ricercatore junior (una chiamata veloce)
            ret = sa._studio_kerkuesi(q, tr, ret)
        got = [(a.code, str(a.number)) for a, _ in ret]
        hit = [e for e in exp if e in got]
        ok += bool(hit)
        pos = min((got.index(e) + 1 for e in hit), default=None)
        print(f"{'✓' if hit else '✗'} [{jur}] {q[:70]:70s} | trovato {hit[:2]} pos {pos} | aree {tr.areas} | query {[x[:40] for x in tr.search_queries[:3]]}", flush=True)
        if not hit or "-v" in sys.argv:
            print("      blocco:", [f"{c}:{n}" for c, n in got[:14]], flush=True)
    n = len([c for c in CASI if not solo or any(w.lower() in c[1].lower() for w in solo)])
    print(f"\nnel blocco del senior: {ok}/{n} · {int((time.time()-t0)/max(n,1))} s/domanda (triage vero)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
