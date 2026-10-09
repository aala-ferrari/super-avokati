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
    # v9.537 — nono giro (società, assicurazione del sinistro, responsabilità medica)
    ("IT", "[frek9] L'amministratore della srl ha prelevato soldi dalla società senza giustificazione. Il cliente, socio al 30%, cosa può fare?", [("codice_civile", "2476")]),
    ("IT", "[frek9] Il cliente ha avuto un tamponamento: l'assicurazione dell'altro non risponde da due mesi. Come funziona la richiesta di risarcimento?", [("codice_assicurazioni", "148"), ("codice_assicurazioni", "149")]),
    ("IT", "[frek9] La cliente ha subito un intervento sbagliato in un ospedale pubblico. Contro chi agiamo e cosa dobbiamo fare prima della causa?", [("responsabilita_sanitaria", "7"), ("responsabilita_sanitaria", "8")]),
    ("AL", "[frek9] Klienti pati një aksident, faji ishte i tjetrit, dhe siguruesi nuk po i përgjigjet prej dy muajsh. Si ta detyrojmë të paguajë?", [("ligji_sigurimi_mjeteve", "10"), ("ligji_sigurimi_mjeteve", "9")]),
    ("AL", "[frek9] Klienti është ortak me 40% në një shpk dhe dëshiron të largohet nga shoqëria. Si e bën dhe çfarë i takon?", [("ligji_shoqerite_tregtare", "101"), ("ligji_shoqerite_tregtare", "103"), ("ligji_shoqerite_tregtare", "73")]),
    # v9.568 — ventitreesimo giro (9 ott): successione senza testamento AL/IT, asta contestata AL; usura, disdetta del 4+4,
    # furto in abitazione, guida senza patente
    ("AL", "[frek23] Babai i klientit vdiq pa lënë testament. Ka gruan dhe tre fëmijë. Si ndahet pasuria?", [("kodi_civil", "361")]),
    ("AL", "[frek23] Përmbaruesi e shiti në ankand shtëpinë e klientit me një çmim shumë të ulët. A mund ta kundërshtojmë shitjen?", [("kodi_proc_civile", "572"), ("kodi_proc_civile", "580")]),
    ("IT", "[frek23] Il padre è morto senza testamento lasciando la moglie e due figli. Come si divide l'eredità?", [("codice_civile", "581"), ("codice_civile", "566")]),
    ("IT", "[frek23] Un privato ha prestato soldi al cliente e ora pretende interessi del 10% al mese. Cosa possiamo fare?", [("codice_penale", "644")]),
    ("IT", "[frek23] Il proprietario vuole mandare via l'inquilino alla prima scadenza del contratto 4+4. Può farlo?", [("locazioni_abitative", "3")]),
    ("IT", "[frek23] Dei ladri sono entrati nell'appartamento del cliente mentre era in vacanza. Che reato è e cosa rischiano?", [("codice_penale", "624-bis")]),
    ("IT", "[frek23] Il cliente è stato fermato alla guida senza aver mai preso la patente. Cosa rischia?", [("codice_strada", "116")]),
    # v9.567 — ventiduesimo giro (9 ott): rinuncia all'eredità AL/IT, costruzione abusiva AL, infortunio sul lavoro AL,
    # affidamento dei figli, dimissioni per giusta causa
    ("AL", "[frek22] Babai i klientit vdiq dhe la shumë borxhe. Klienti nuk do ta marrë trashëgiminë. Si veprojmë dhe brenda çfarë afati?", [("kodi_civil", "333"), ("kodi_civil", "335")]),
    ("AL", "[frek22] Fqinji po ndërton një kat shtesë pa leje mbi pallatin ku banon klienti. Çfarë mund të bëjmë?", [("kodi_penal", "199/a")]),
    ("AL", "[frek22] Punëtori u lëndua rëndë në punë, por punëdhënësi thotë se nuk ka faj. Çfarë të drejtash ka?", [("kodi_punes", "39"), ("ligji_sigurimet_shoqerore", "44")]),  # il 131 è solo la paga durante l'infortunio
    ("IT", "[frek22] Il padre del cliente è morto pieno di debiti. Come può evitare di ereditarli?", [("codice_civile", "519")]),
    ("IT", "[frek22] Nella separazione i genitori litigano su con chi devono stare i figli. Cosa decide il giudice?", [("codice_civile", "337-ter")]),
    ("IT", "[frek22] Il datore non paga lo stipendio da tre mesi e il dipendente vuole dimettersi subito senza preavviso. Può farlo?", [("codice_civile", "2119")]),
    # v9.566 — ventunesimo giro (9 ott): cane del vicino, auto senza assicurazione AL; IT dati del conducente, Fondo di garanzia,
    # finita locazione, licenziamento collettivo
    ("AL", "[frek21] Qeni i fqinjit kafshoi djalin e klientes në rrugë. Kush përgjigjet për dëmin?", [("kodi_civil", "621")]),
    ("AL", "[frek21] Klientin e përplasi një makinë pa siguracion dhe drejtuesi u largua. Kush ia paguan dëmin?", [("ligji_sigurimi_mjeteve", "41")]),
    ("IT", "[frek21] Al cliente è arrivata una multa con la richiesta di comunicare chi guidava. Se non lo comunica cosa succede?", [("codice_strada", "126-bis")]),
    ("IT", "[frek21] Il cliente è stato investito da un'auto senza assicurazione. Chi lo risarcisce?", [("codice_assicurazioni", "283")]),
    ("IT", "[frek21] Il contratto d'affitto è scaduto e l'inquilino non lascia la casa. Come procediamo?", [("codice_procedura_civile", "657")]),
    ("IT", "[frek21] L'azienda vuole licenziare 20 dipendenti per crisi. Quali criteri deve rispettare nella scelta dei lavoratori?", [("licenziamenti_collettivi", "5"), ("licenziamenti_collettivi", "24")]),
    # v9.566 — ventesimo giro (9 ott): privacy e dintorni — cancellazione dei dati AL, telecamera del vicino AL/IT, diritto all'oblio,
    # regolamento condominiale sugli animali, revisione scaduta, danno per dati sanitari diffusi
    ("AL", "[frek20] Një kompani publikoi të dhënat personale të klientit pa pëlqimin e tij dhe ai kërkon që t'i fshijë. Çfarë të drejte ka?", [("ligji_te_dhenat_2024", "15")]),  # v9.566: il 57 è della parte per le autorità competenti (artt. 47 ss.)
    ("AL", "[frek20] Fqinji vendosi një kamerë që filmon oborrin dhe dritaret e shtëpisë së klientit. Çfarë mund të bëjmë?", [("kodi_penal", "121")]),
    ("IT", "[frek20] Il cliente vuole che un sito cancelli vecchie notizie e dati personali che lo riguardano. Come procediamo?", [("gdpr", "17")]),
    ("IT", "[frek20] Il vicino ha installato una telecamera che riprende il giardino e le finestre del cliente. È lecito?", [("codice_penale", "615-bis")]),
    ("IT", "[frek20] Il regolamento condominiale vieta di tenere cani negli appartamenti. Questo divieto è valido?", [("codice_civile", "1138")]),
    ("IT", "[frek20] Il cliente è stato fermato con la revisione dell'auto scaduta da sei mesi. Cosa rischia?", [("codice_strada", "80")]),
    ("IT", "[frek20] Una clinica ha diffuso per errore i dati sanitari del cliente. Può chiedere il risarcimento?", [("gdpr", "82")]),
    # v9.561 — diciannovesimo giro (9 ott): energia elettrica, violazione di domicilio AL; IT adozione del figlio del coniuge, rifiuto
    # dell'alcoltest, usura, omessa dichiarazione, estorsione
    ("AL", "[frek19] OSHEE e kallëzoi klientin sepse kishte një lidhje të paligjshme me rrjetin elektrik. Çfarë rrezikon?", [("kodi_penal", "137")]),
    ("AL", "[frek19] Ish-burri i klientes hyri me forcë në shtëpinë e saj pa leje. Çfarë vepre është?", [("kodi_penal", "112")]),
    ("IT", "[frek19] Il cliente vuole adottare il figlio che la moglie ha avuto da una precedente relazione. Come si fa?", [("adozione", "44")]),
    ("IT", "[frek19] Il cliente fermato dalla polizia si è rifiutato di fare l'alcoltest. Cosa rischia?", [("codice_strada", "186")]),
    ("IT", "[frek19] Un conoscente ha prestato soldi al cliente con interessi del 10% al mese e ora lo minaccia. Che reato è?", [("codice_penale", "644")]),
    ("IT", "[frek19] Il cliente non ha presentato la dichiarazione dei redditi per tre anni e ha evaso 80.000 euro di imposte all'anno. Rischia il penale?", [("reati_tributari", "5")]),
    ("IT", "[frek19] Un ex socio minaccia di diffondere documenti compromettenti se il cliente non gli dà 20.000 euro. Che reato è?", [("codice_penale", "629")]),
    # v9.558 — diciottesimo giro (8 ott): privacy, alimenti non pagati (reato), rinuncia all'eredità AL; IT fermo dell'auto per cartelle,
    # casa familiare, violazione di domicilio, falso profilo
    ("AL", "[frek18] Ish-partneri publikoi në Facebook fotot private të klientes pa pëlqimin e saj. Çfarë vepre është?", [("kodi_penal", "121")]),
    ("AL", "[frek18] Ish-bashkëshorti nuk paguan detyrimin ushqimor për fëmijën prej një viti, pavarësisht vendimit të gjykatës. A është vepër penale?", [("kodi_penal", "125")]),
    ("AL", "[frek18] Babai i klientit vdiq me shumë borxhe. Si heq dorë klienti nga trashëgimia dhe brenda sa kohe?", [("kodi_civil", "333"), ("kodi_civil", "335")]),
    ("IT", "[frek18] L'Agenzia delle Entrate Riscossione ha messo il fermo amministrativo sull'auto del cliente per delle cartelle. Come lo togliamo?", [("tu_riscossione", "187")]),
    ("IT", "[frek18] Nella separazione i figli vivono con la madre. Chi resta nella casa familiare, che è intestata al marito?", [("codice_civile", "337-sexies")]),
    ("IT", "[frek18] L'ex marito è entrato senza permesso in casa della cliente con le vecchie chiavi. Che reato è?", [("codice_penale", "614")]),
    ("IT", "[frek18] Qualcuno ha aperto un profilo social a nome del cliente usando le sue foto per truffare altre persone. Che reato è?", [("codice_penale", "494")]),
    # v9.556 — diciassettesimo giro (8 ott): rapina, abuso d'ufficio, accesso agli atti AL, recesso online AL; IT decreto penale, messa
    # alla prova, immagini intime, ingiuria (D.Lgs. 7/2016)
    ("AL", "[frek17] Dy persona e sulmuan klientin në rrugë dhe i morën telefonin me forcë. Çfarë vepre është dhe çfarë dënimi parashikon?", [("kodi_penal", "139")]),
    ("AL", "[frek17] Një nëpunës i bashkisë e refuzoi qëllimisht lejen e klientit pa asnjë arsye ligjore, për ta dëmtuar. A ka vepër penale?", [("kodi_penal", "248")]),
    ("AL", "[frek17] Bashkia nuk i jep klientit kopjen e vendimit të këshillit bashkiak. Si e kërkojmë dhe brenda sa kohe duhet të përgjigjen?", [("ligji_informimi", "15"), ("ligji_informimi", "11")]),
    ("AL", "[frek17] Klienti bleu online një celular dhe pas pesë ditësh do ta kthejë pa dhënë arsye. A ka të drejtë?", [("ligji_konsumatoret", "37/1"), ("ligji_konsumatoret", "37/3")]),
    ("IT", "[frek17] Al cliente è stato notificato un decreto penale di condanna. Entro quando e come si oppone?", [("codice_procedura_penale", "461")]),
    ("IT", "[frek17] Il cliente incensurato è accusato di furto semplice. Può chiedere la messa alla prova?", [("codice_penale", "168-bis")]),
    ("IT", "[frek17] L'ex fidanzato ha pubblicato in un gruppo foto intime della cliente senza il suo consenso. Che reato è?", [("codice_penale", "612-ter")]),
    ("IT", "[frek17] Un collega ha insultato pesantemente il cliente davanti a tutti in ufficio. Possiamo denunciarlo?", [("sanzioni_pecuniarie_civili", "4")]),
    # v9.555 — sedicesimo giro (8 ott): età imputabile, multa amministrativa, divisione fra coeredi, licenziamento in malattia; IT disdetta
    # del locatore, danni del figlio minore, casa occupata
    ("AL", "[frek16] Djali 13 vjeç i klientes vodhi një telefon në shkollë. A mund të ndiqet penalisht?", [("kodi_penal", "12")]),
    ("AL", "[frek16] Policia rrugore i vendosi klientit një gjobë që e konsideron të padrejtë. Si dhe brenda sa ditësh ankohet?", [("ligji_kundervajtjet", "29"), ("ligji_kundervajtjet", "26")]),
    ("AL", "[frek16] Tre vëllezër trashëguan një shtëpi dhe njëri nuk pranon as ta ndajë as ta shesë. Si e zgjidhim?", [("kodi_civil", "207")]),
    ("AL", "[frek16] Punëdhënësi e pushoi klientin ndërsa ishte me raport mjekësor për sëmundje. A është i ligjshëm pushimi?", [("kodi_punes", "130")]),
    ("IT", "[frek16] Il proprietario vuole mandare via l'inquilino alla prima scadenza del contratto 4+4 per vendere la casa. Può farlo?", [("locazioni_abitative", "3")]),
    ("IT", "[frek16] Il figlio quindicenne del cliente ha rotto con un pallone il vetro dell'auto del vicino. Chi deve pagare?", [("codice_civile", "2048")]),
    ("IT", "[frek16] Mentre il cliente era in vacanza degli sconosciuti hanno occupato la sua casa. Cosa possiamo fare subito?", [("codice_penale", "634-bis")]),
    # v9.551 — quindicesimo giro (8 ott): servitù AL, corruzione; IT straordinari, ferie, diffamazione online, mantenimento non versato,
    # furto in casa, successione senza testamento, permessi L. 104
    ("AL", "[frek15] Toka e klientit nuk ka dalje në rrugë publike dhe fqinji nuk e lë të kalojë nga toka e tij. Çfarë të drejte kemi?", [("kodi_civil", "277")]),
    ("AL", "[frek15] Një zyrtar i bashkisë i kërkoi klientit 2000 euro për t'i dhënë lejen e ndërtimit. Çfarë vepre është dhe çfarë rrezikon klienti nëse paguan?", [("kodi_penal", "259"), ("kodi_penal", "244")]),
    ("IT", "[frek15] Il cliente lavora 50 ore a settimana e gli straordinari non vengono pagati. Cosa può chiedere?", [("orario_lavoro", "5"), ("codice_civile", "2108")]),
    ("IT", "[frek15] Da due anni il datore non fa godere le ferie al cliente e ora vuole licenziarlo. Che diritti ha sulle ferie non godute?", [("orario_lavoro", "10")]),
    ("IT", "[frek15] Un ex collega ha scritto su Facebook che il cliente è un ladro. È diffamazione? Cosa rischia?", [("codice_penale", "595")]),
    ("IT", "[frek15] L'ex marito non versa l'assegno per i figli da sei mesi. È anche un reato?", [("codice_penale", "570-bis")]),
    ("IT", "[frek15] Di notte sono entrati in casa del cliente e hanno rubato gioielli. Il ladro è stato preso: che pena rischia?", [("codice_penale", "624-bis")]),
    ("IT", "[frek15] Il padre del cliente è morto senza testamento lasciando la moglie e due figli. Come si divide l'eredità?", [("codice_civile", "581")]),
    ("IT", "[frek15] Il cliente assiste la madre con disabilità grave. Ha diritto a permessi retribuiti dal lavoro?", [("legge_104", "33")]),
    # v9.550 — quattordicesimo giro (8 ott): maternità, cautelare civile, alimenti fra parenti; IT separazione consensuale
    ("AL", "[frek14] Klientja është shtatzënë në muajin e pestë. Sa leje lindjeje i takon dhe kush e paguan?", [("kodi_punes", "105")]),
    ("AL", "[frek14] Debitori po i shet pasuritë para se të fillojë gjyqi. Si ia bllokojmë pasurinë klientit tonë që të mos humbasë kredinë?", [("kodi_proc_civile", "202"), ("kodi_proc_civile", "206")]),
    ("AL", "[frek14] Nëna e moshuar e klientit nuk ka asnjë të ardhur. A janë të detyruar fëmijët t'i japin ushqim dhe sa?", [("kodi_familjes", "192"), ("kodi_familjes", "198")]),
    ("IT", "[frek14] Marito e moglie sono d'accordo a separarsi e hanno un figlio. Qual è la strada più rapida?", [("codice_civile", "158"), ("negoziazione_assistita", "6")]),
    ("IT", "[frek14] Il debitore sta vendendo i suoi immobili prima della causa. Come blocchiamo i beni a garanzia del credito del cliente?", [("codice_procedura_civile", "671")]),
    ("IT", "[frek14] Il padre anziano del cliente non ha reddito e chiede gli alimenti ai figli. Chi deve pagare e quanto?", [("codice_civile", "433"), ("codice_civile", "438")]),
    # v9.548 — tredicesimo giro (8 ott): lesioni, minacce, ingiuria, abusi edilizi, esecuzione, falso; IT maternità, sanatoria, pignoramento,
    # lesioni stradali, distanze — attese lette sul testo
    ("AL", "[frek13] Fqinji e rrahu klientin dhe mjeku i dha 12 ditë paaftësi në punë. Çfarë vepre është dhe si ankohemi?", [("kodi_penal", "89"), ("kodi_penal", "90")]),
    ("AL", "[frek13] Një person i dërgon klientit mesazhe se do ta vrasë. Çfarë mund të bëjmë penalisht?", [("kodi_penal", "84")]),
    ("AL", "[frek13] Dikush e ofendoi rëndë klientin në Facebook me fjalë fyese, pa i atribuar ndonjë fakt. A është vepër penale?", [("kodi_penal", "119")]),
    ("AL", "[frek13] Klienti ndërtoi një kat shtesë pa leje dhe policia e ndërtimit i bëri kallëzim. Çfarë rrezikon penalisht?", [("kodi_penal", "199/a")]),
    ("AL", "[frek13] Përmbaruesi privat i vuri sekuestro shtëpisë së klientit për një kredi bankare, pa e njoftuar. Si i kundërshtojmë veprimet e tij?", [("kodi_proc_civile", "610"), ("kodi_proc_civile", "609")]),
    ("AL", "[frek13] Vëllai i klientit ia falsifikoi nënshkrimin në një prokurë dhe shiti tokën e tij. Çfarë bëjmë?", [("kodi_penal", "186"), ("kodi_civil", "92")]),
    ("IT", "[frek13] La cliente è stata licenziata mentre era incinta di quattro mesi. Il licenziamento è valido?", [("maternita_paternita", "54")]),
    ("IT", "[frek13] Il cliente ha costruito una veranda senza permesso e il Comune vuole la demolizione. Si può sanare?", [("tu_edilizia", "36"), ("tu_edilizia", "36-bis"), ("tu_edilizia", "31")]),
    ("IT", "[frek13] Un creditore ha pignorato il conto corrente del cliente su cui arriva lo stipendio. Quanto può trattenere?", [("codice_procedura_civile", "545")]),
    ("IT", "[frek13] Il cliente alla guida ha investito un pedone causandogli fratture con prognosi di 60 giorni. Che reato rischia?", [("codice_penale", "590-bis")]),
    ("IT", "[frek13] Il cliente è denunciato per aver costruito un capannone senza permesso di costruire. Che pena rischia?", [("tu_edilizia", "44")]),
    ("IT", "[frek13] Il vicino ha costruito a un metro e mezzo dal confine del cliente. Cosa possiamo chiedere?", [("codice_civile", "873")]),
    ("IT", "[frek13] Il cliente è stato condannato a un anno di reclusione per furto; la motivazione è stata depositata il 25 settembre. Entro quando va proposto l'appello?", [("codice_procedura_penale", "585")]),
    ("IT", "[frek13] La sentenza civile di primo grado che ha respinto la domanda del cliente è stata notificata il 1° ottobre. Entro quando l'appello?", [("codice_procedura_civile", "325")]),
    # v9.544 — dodicesimo giro (8 ott): penale e amministrativo, attese lette sul testo
    ("AL", "[frek12] Klienti u arrestua për vjedhje dhe prokuroria kërkon arrest në burg. Çfarë kriteresh duhen dhe çfarë mase më të butë mund të kërkojmë?", [("kodi_proc_penale", "228"), ("kodi_proc_penale", "229"), ("kodi_proc_penale", "230")]),
    ("AL", "[frek12] Shteti do t'i shpronësojë klientit tokën për një rrugë. Çfarë të drejtash ka dhe si e kundërshton vlerën?", [("ligji_shpronesimi", "6"), ("ligji_shpronesimi", "16"), ("ligji_shpronesimi", "5")]),
    ("AL", "[frek12] Klienti ka 62 vjeç dhe 30 vjet kontribute. A ka të drejtë për pension pleqërie?", [("ligji_sigurimet_shoqerore", "31"), ("ligji_sigurimet_shoqerore", "92")]),
    ("AL", "[frek12] Bashkia nuk i përgjigjet kërkesës së klientit për leje prej tre muajsh. Çfarë pasoje ka heshtja?", [("kodi_proc_admin", "97")]),
    ("IT", "[frek12] Il cliente è stato arrestato per spaccio e il PM chiede il carcere. Quali esigenze cautelari servono e come impugniamo l'ordinanza?", [("codice_procedura_penale", "274"), ("codice_procedura_penale", "275"), ("codice_procedura_penale", "309")]),
    ("IT", "[frek12] Il cliente vuole patteggiare per un furto aggravato. Come funziona e che effetti ha la sentenza?", [("codice_procedura_penale", "444"), ("codice_procedura_penale", "445")]),
    ("IT", "[frek12] Il Comune non risponde da cinque mesi all'istanza del cliente. Cosa possiamo fare contro il silenzio?", [("procedimento_amministrativo", "2"), ("codice_processo_amministrativo", "117"), ("codice_processo_amministrativo", "31")]),
    ("IT", "[frek12] L'ASL rifiuta di dare al cliente copia della sua pratica. Come otteniamo l'accesso agli atti?", [("procedimento_amministrativo", "22"), ("procedimento_amministrativo", "25")]),
    # v9.543 — undicesimo giro (8 ott), attese lette sul testo
    ("AL", "[frek11] Klienti i dha një shoku 10 mijë euro hua me shkrim dhe ai nuk ia kthen. Çfarë mund të kërkojë, edhe kamata?", [("kodi_civil", "1050"), ("kodi_civil", "1051")]),
    ("AL", "[frek11] Klientja i dhuroi të birit një apartament dhe tani ai e ka përzënë nga shtëpia. A mund ta kthejë dhurimin?", [("kodi_civil", "771")]),
    ("AL", "[frek11] Firma e ndërtimit i dorëzoi klientit shtëpinë me lagështirë dhe çarje në mure. Çfarë mund të kërkojë?", [("kodi_civil", "864"), ("kodi_civil", "865"), ("kodi_civil", "866")]),
    ("AL", "[frek11] Ish-i dashuri e ndjek klienten çdo ditë dhe i dërgon mesazhe kërcënuese. Çfarë vepre penale është?", [("kodi_penal", "121/a"), ("kodi_penal", "84")]),
    ("AL", "[frek11] Klienti u ndalua nga policia duke drejtuar makinën i dehur. Çfarë rrezikon penalisht?", [("kodi_penal", "291")]),
    ("AL", "[frek11] Pas divorcit fëmija i është lënë nënës; babai dëshiron ta shohë më shpesh. Si ta ndryshojmë vendimin?", [("kodi_familjes", "159"), ("kodi_familjes", "158")]),
    ("IT", "[frek11] La cliente ha donato la casa al figlio, che ora l'ha cacciata e la insulta. Può revocare la donazione?", [("codice_civile", "801")]),
    ("IT", "[frek11] L'impresa ha consegnato la casa nuova con infiltrazioni e crepe nei muri. Quali azioni abbiamo e in che termini?", [("codice_civile", "1667"), ("codice_civile", "1668"), ("codice_civile", "1669")]),
    ("IT", "[frek11] I nonni non riescono più a vedere il nipote dopo la separazione dei genitori. Possono rivolgersi al giudice?", [("codice_civile", "317-bis")]),
    ("IT", "[frek11] Il cliente ha prestato 15.000 euro a un amico con una scrittura privata e non gli vengono restituiti. Cosa può chiedere?", [("codice_civile", "1813"), ("codice_civile", "1815")]),
    ("IT", "[frek11] Il fondo del cliente non ha accesso alla strada pubblica e il vicino non lo fa passare. Cosa possiamo fare?", [("codice_civile", "1051")]),
    ("IT", "[frek11] L'ex compagno segue la cliente, la tempesta di messaggi e lei ha cambiato abitudini per paura. Che reato è?", [("codice_penale", "612-bis")]),
    ("IT", "[frek11] Il cliente ha pagato su un sito un'auto che non è mai arrivata; il venditore è sparito. Che reato è?", [("codice_penale", "640"), ("codice_penale", "640-ter")]),
    # v9.542 — decimo giro di domande frequenti (8 ott): attese lette sul testo del corpus prima di scriverle
    ("AL", "[frek10] Klienti bleu një makinë të përdorur dhe pas dy javësh doli një defekt motori që shitësi e kishte fshehur. Çfarë të drejtash ka?", [("kodi_civil", "716"), ("kodi_civil", "717"), ("kodi_civil", "722")]),
    ("AL", "[frek10] Kontrata e qirasë mbaroi në qershor, por qiramarrësi nuk largohet nga apartamenti i klientit. Si e nxjerrim?", [("kodi_civil", "820"), ("kodi_civil", "814"), ("kodi_civil", "815")]),
    ("AL", "[frek10] Punëdhënësi nuk i ka paguar klientit pagën prej tre muajsh. Çfarë mund të kërkojë dhe me çfarë interesash?", [("kodi_punes", "120"), ("kodi_punes", "119")]),
    ("AL", "[frek10] Fqinji ndërtoi një mur që hyn dy metra në tokën e klientit. Si e mbrojmë pronën?", [("kodi_civil", "296"), ("kodi_civil", "302")]),
    ("AL", "[frek10] Pas divorcit ish-bashkëshortët nuk bien dakord si të ndajnë apartamentin e blerë gjatë martesës. Si bëhet pjesëtimi?", [("kodi_familjes", "98"), ("kodi_familjes", "103"), ("kodi_familjes", "107")]),
    ("AL", "[frek10] Klientja ka një fëmijë jashtë martese dhe babai nuk e njeh. Si vërtetohet atësia?", [("kodi_familjes", "183"), ("kodi_familjes", "181")]),
    ("AL", "[frek10] Punëtori u lëndua në kantier sepse nuk kishte mjete mbrojtëse. Kush përgjigjet dhe për çfarë?", [("kodi_punes", "39"), ("kodi_punes", "131")]),
    ("IT", "[frek10] Il cliente ha comprato un'auto usata da un concessionario e dopo un mese si è rotto il cambio. Cosa può chiedere?", [("codice_consumo", "135-bis"), ("codice_consumo", "135-ter"), ("codice_consumo", "129"), ("codice_consumo", "130")]),
    ("IT", "[frek10] L'inquilino non paga l'affitto da quattro mesi. Come procediamo con lo sfratto?", [("codice_procedura_civile", "658"), ("codice_procedura_civile", "663"), ("codice_procedura_civile", "665")]),
    ("IT", "[frek10] Da mesi il datore di lavoro umilia e isola il dipendente davanti ai colleghi. Cosa possiamo chiedere?", [("codice_civile", "2087")]),
    ("IT", "[frek10] Il padre biologico non ha mai riconosciuto il cliente, oggi maggiorenne. Può chiedere che il giudice dichiari la paternità?", [("codice_civile", "269"), ("codice_civile", "270")]),
    ("IT", "[frek10] Dall'appartamento del piano di sopra arriva acqua che ha rovinato il soffitto del cliente. Chi risponde dei danni?", [("codice_civile", "2051"), ("codice_civile", "2043")]),
    ("IT", "[frek10] Il fratello impugna il testamento scritto a mano dal padre perché manca la data. È valido?", [("codice_civile", "602"), ("codice_civile", "606")]),
    ("IT", "[frek10] Il dipendente è rimasto assente cinque giorni senza giustificazione e l'azienda lo licenzia in tronco. È legittimo?", [("codice_civile", "2119"), ("statuto_lavoratori", "7")]),
    ("IT", "[frek10] Nella separazione la moglie, che non lavora, chiede l'assegno di mantenimento. Su quali criteri decide il giudice?", [("codice_civile", "156")]),
    # v9.534 — ottavo giro (lavoro, consumo, strada, locazione, condominio, immigrazione)
    ("IT", "[frek8] Il cliente si è dimesso dopo 12 anni e il datore non gli ha ancora pagato il TFR. Come si calcola e cosa facciamo?", [("codice_civile", "2120")]),
    ("IT", "[frek8] Il cliente ha comprato online un divano e dopo una settimana vuole restituirlo. Può farlo senza motivo?", [("codice_consumo", "52")]),
    ("IT", "[frek8] Al cliente sono stati tolti 10 punti dalla patente per eccesso di velocità. Quanti ne ha e come li recupera?", [("codice_strada", "126-bis")]),
    ("IT", "[frek8] Il padrone di casa non restituisce al cliente il deposito cauzionale di tre mensilità dopo la fine dell'affitto. Cosa facciamo?", [("locazioni_immobili_urbani", "11")]),
    ("IT", "[frek8] Un condomino non paga le spese condominiali da un anno. Come recupera l'amministratore?", [("disp_att_cc", "63")]),
    ("IT", "[frek8] Il cliente albanese, senza permesso, ha in Italia la moglie e due figli minori regolari. Può essere espulso?", [("tu_immigrazione", "19")]),
    # v9.533 — settimo giro (fisco, amministrativo, crisi d'impresa, forma della donazione)
    ("IT", "[frek7] Al cliente è stato notificato un avviso di accertamento IRPEF il 15 settembre. Entro quando presentiamo ricorso?", [("processo_tributario", "21"), ("giustizia_tributaria", "67")]),   # il TU si applica dal 2027
    ("IT", "[frek7] Il Comune ha negato al cliente il permesso di costruire con un provvedimento notificato ieri. Come e entro quando lo impugniamo?", [("codice_processo_amministrativo", "29")]),
    ("IT", "[frek7] Una società deve al cliente 120.000 euro e non paga da un anno; è chiaramente insolvente. Possiamo chiederne la liquidazione giudiziale?", [("codice_crisi_impresa", "121"), ("codice_crisi_impresa", "37")]),
    ("IT", "[frek7] Il cliente vuole donare la casa alla figlia. Basta una scrittura privata firmata da entrambi?", [("codice_civile", "782")]),
    ("AL", "[frek7] Tatimet i bënë klientit një vlerësim tatimor prej 3 milionë lekësh që e konsideron të padrejtë. Si e ankimojmë dhe brenda sa kohe?", [("ligji_procedurat_tatimore", "106"), ("ligji_procedurat_tatimore", "107"), ("ligji_procedurat_tatimore", "109")]),
    # v9.531 — sesto giro (albanese: famiglia e procedura penale)
    ("AL", "[frek6] Klientja rrihet nga bashkëshorti dhe ka frikë të kthehet në shtëpi. Si marrim menjëherë një urdhër mbrojtjeje?", [("ligji_dhuna_familje_2026", "30"), ("ligji_dhuna_familje_2026", "18"), ("ligji_dhuna_familje_2026", "36")]),
    ("AL", "[frek6] Policia e arrestoi klientin dje në flagrancë. Brenda sa orësh duhet ta shohë gjyqtari dhe çfarë ndodh në seancë?", [("kodi_proc_penale", "258"), ("kodi_proc_penale", "259"), ("kodi_proc_penale", "251")]),
    ("AL", "[frek6] Klienti është në paraburgim prej 10 muajsh për vjedhje dhe gjykimi nuk ka filluar. A ka një afat maksimal?", [("kodi_proc_penale", "263")]),
    ("AL", "[frek6] Klienti u dënua 8 vjet më parë dhe e ka vuajtur dënimin. Si i hiqet precedenti penal nga dosja?", [("kodi_penal", "69")]),
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
    # v9.546: «--giur=IT» / «--giur=AL» — solo le domande di una giurisdizione (un indice nuovo di una sola lingua)
    _giur = next((x.split("=", 1)[1].upper() for x in sys.argv[1:] if x.startswith("--giur=")), None)
    _tc_path = next((x.split("=", 1)[1] for x in sys.argv[1:] if x.startswith("--triage-cache=")), None)
    import json
    from pathlib import Path
    _tc = json.loads(Path(_tc_path).read_text(encoding="utf-8")) if _tc_path and Path(_tc_path).exists() else {}
    _posizioni = []
    for jur, q, exp in [c for c in CASI if (not solo or any(w.lower() in c[1].lower() for w in solo)) and (not _giur or c[0] == _giur)]:
        B.set_request_jurisdiction(jur)
        try:
            sa._jurisdiction_ctx.code = jur
        except Exception:  # noqa: BLE001
            pass
        # v9.562 — «--triage-cache=FILE»: il triage di ogni domanda si salva e si RIGIOCA identico (il triage vero cambia a ogni giro:
        # per confrontare due versioni della ricerca serve lo stesso triage)
        if _tc_path and q in _tc:
            tr = B.TriageResult(**{k: v for k, v in _tc[q].items() if k in B.TriageResult.__dataclass_fields__})
        else:
            tr = sa._triage(q, [], None)
            if _tc_path:
                import dataclasses as _dc
                _tc[q] = _dc.asdict(tr)
                Path(_tc_path).write_text(json.dumps(_tc, ensure_ascii=False), encoding="utf-8")
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
        _posizioni.append(pos)
        print(f"{'✓' if hit else '✗'} [{jur}] {q[:70]:70s} | trovato {hit[:2]} pos {pos} | aree {tr.areas} | query {[x[:40] for x in tr.search_queries[:3]]}", flush=True)
        if not hit or "-v" in sys.argv:
            print("      blocco:", [f"{c}:{n}" for c, n in got[:14]], flush=True)
    n = len([c for c in CASI if (not solo or any(w.lower() in c[1].lower() for w in solo)) and (not _giur or c[0] == _giur)])
    print(f"\nnel blocco del senior: {ok}/{n} · {int((time.time()-t0)/max(n,1))} s/domanda (triage vero)")
    _pp = [p for p in _posizioni if p]
    if _pp:
        print(f"posizioni: media {sum(_pp)/len(_pp):.2f} · nei primi 3: {sum(1 for p in _pp if p <= 3)} · oltre il 9°: {sum(1 for p in _pp if p > 9)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
