"""v9.656 — I MODELLI DI PERIZIA IN SESSIONE ITALIANA, scritti per il diritto italiano.

Fino alla v9.655 la sessione italiana riceveva gli stessi testi dei modelli albanesi (tradotti a schermo dal dizionario del
client, e in ALBANESE dentro il prompt): l'avvocato italiano leggeva «riqualificazione come furto semplice 134», «premeditazione
per l'art. 78», «gravità della lesione (tier: grave 88 / lieve 89)», «identificazione obbligatoria (Legge 82/2024, artt. 10 e 18)»,
«termine di impugnazione di 15 giorni» — numeri e leggi ALBANESI —, e una riga restava in albanese («Ankesa te Agjencia e
Mbikëqyrjes Policore…»). Qui gli stessi campi (stesse chiavi del modello albanese, che l'interfaccia legge) per il diritto italiano;
i numeri sono solo quelli verificati sul corpus italiano, il resto a parole: gli articoli veri li porta il blocco del corpus
(`expertise._SEMI_IT`). Senza import: lo legge `expertise`."""

TESTI_IT = {
    "aksident_rrugor": {
        "label": "Incidente stradale / danno",
        "elements": ["Condotta e colpa (violazione delle norme del codice della strada; presunzione dell'art. 2054 c.c.)",
                     "Nesso causale con il danno",
                     "Danno concreto (patrimoniale + non patrimoniale)",
                     "Legittimazione passiva dell'assicuratore del responsabile (azione diretta)"],
        "evidence": ["Rapporto della polizia stradale / verbale", "Testimoni oculari", "Foto/video (dashcam, CCTV)",
                     "Perizia medico-legale sulle lesioni", "Fatture mediche + documentazione del reddito perso",
                     "Perizia sul danno al veicolo", "Constatazione amichevole (CAI), se firmata"],
        "deadlines": ["Prescrizione: due anni dal sinistro per i danni da circolazione (art. 2947 c.c.), più lunga se il fatto è "
                      "reato",
                      "Richiesta di risarcimento all'assicuratore prima della causa (artt. 145 e 148 cod. ass.: 60 giorni, 90 in "
                      "caso di lesioni)"],
        "defenses": ["Concorso di colpa del danneggiato (art. 1227 c.c.)", "Caso fortuito / forza maggiore",
                     "Mancata riduzione del danno da parte del danneggiato", "Stato preesistente (contesta il nesso causale)"],
        "valuation": ("Danno = danno patrimoniale (spese mediche, reddito perso, danno al veicolo) + danno non patrimoniale "
                      "(biologico secondo gli artt. 138-139 cod. ass., morale). Confronta con i precedenti."),
        "questions": ["Data, ora e luogo del sinistro?",
                      "Esiste un rapporto della polizia e chi è stato considerato responsabile?",
                      "Quali sono le lesioni personali e quanti giorni di malattia?",
                      "Totale delle spese mediche e dei giorni di lavoro persi?"],
    },
    "vjedhje": {
        "label": "Furto",
        "elements": ["Impossessamento della cosa mobile altrui, sottraendola a chi la detiene (art. 624 c.p.)",
                     "La cosa appartiene ad altri", "Senza il consenso del detentore",
                     "Fine di trarne profitto (dolo specifico)"],
        "evidence": ["Denuncia-querela del danneggiato + elenco dei beni", "CCTV / testimoni",
                     "Tracce (DNA, impronte digitali)", "Recupero della refurtiva", "Stima del valore del bene"],
        "deadlines": ["Querela entro tre mesi dalla notizia del fatto, se il furto è procedibile a querela (art. 124 c.p.)",
                      "Prescrizione secondo la pena della figura contestata (art. 157 c.p.)",
                      "Termini di impugnazione: 15, 30 o 45 giorni secondo il deposito della motivazione (art. 585 c.p.p.)"],
        "defenses": ["Alibi / errata identificazione", "Assenza di dolo", "Consenso del detentore",
                     "Prova acquisita in violazione della legge (inutilizzabilità)",
                     "Particolare tenuità del fatto (art. 131-bis c.p.)"],
        "valuation": ("La pena dipende dalla figura (furto semplice, aggravato ex art. 625 c.p., in abitazione o con strappo ex "
                      "art. 624-bis c.p.) e dalle circostanze. Attenuanti: restituzione e risarcimento del danno (art. 62 c.p.), "
                      "incensuratezza."),
        "questions": ["Qual è l'imputazione esatta (articolo e aggravanti)?",
                      "Ci sono CCTV/testimoni che identificano l'autore?",
                      "Il bene è stato restituito o c'è stato un risarcimento?",
                      "L'imputato ha precedenti penali?"],
    },
    "grabitje": {
        "label": "Rapina",
        "elements": ["Impossessamento della cosa mobile altrui", "Violenza alla persona o minaccia (art. 628 c.p.)",
                     "Circostanze aggravanti (arma, più persone riunite, travisamento, luogo)"],
        "evidence": ["Dichiarazioni della persona offesa", "Referto medico sulle lesioni / prova della minaccia",
                     "CCTV / testimoni", "Sequestro dell'arma + catena di custodia", "DNA/tracce"],
        "deadlines": ["Termini della custodia cautelare",
                      "Termini di impugnazione: 15, 30 o 45 giorni secondo il deposito della motivazione (art. 585 c.p.p.)",
                      "Prescrizione (art. 157 c.p.)"],
        "defenses": ["Errata identificazione / alibi",
                     "Contestazione della violenza o della minaccia (riqualificazione in furto, art. 624 c.p.)",
                     "Assenza di dolo", "Catena di custodia dell'arma / prova inutilizzabile"],
        "valuation": "Pena severa secondo le circostanze. Contesta le aggravanti per far scendere la pena.",
        "questions": ["È stata usata violenza o un'arma, e come è stato provato?",
                      "C'è una lesione personale (referto medico)?",
                      "Ha agito da solo o con altri?",
                      "Come è stata sequestrata l'arma?"],
    },
    "vrasje": {
        "label": "Omicidio",
        "elements": ["Condotta che cagiona la morte", "Nesso causale",
                     "Dolo (e l'eventuale premeditazione, aggravante dell'art. 577 c.p.)",
                     "Circostanze (rapporto con la vittima, motivi, mezzi)"],
        "evidence": ["Autopsia / perizia medico-legale", "Scena del crimine + prove materiali", "Balistica / arma",
                     "Testimoni", "DNA, tracce", "Movente (comunicazioni, storia di conflitto)"],
        "deadlines": ["Termini della custodia cautelare e delle indagini",
                      "Termini di impugnazione: 15, 30 o 45 giorni secondo il deposito della motivazione (art. 585 c.p.p.)"],
        "defenses": ["Legittima difesa / eccesso colposo (artt. 52 e 55 c.p.)",
                     "Assenza di dolo (riqualificazione in omicidio preterintenzionale o colposo, artt. 584 e 589 c.p.)",
                     "Provocazione (art. 62 c.p.)", "Alibi / errata identificazione",
                     "Vizio di mente (perizia psichiatrica, artt. 88-89 c.p.)"],
        "valuation": "Pena severa; premeditazione e aggravanti la aumentano. Contesta il dolo e la premeditazione.",
        "questions": ["C'è premeditazione (pianificazione, mezzi predisposti)?",
                      "Cosa rivela l'autopsia sulla causa e le modalità della morte?",
                      "C'era minaccia/provocazione da parte della vittima?",
                      "Ci sono questioni di capacità di intendere e di volere?"],
    },
    "plagosje": {
        "label": "Lesioni (lesione personale / arma da taglio)",
        "elements": ["Condotta antigiuridica", "Lesione personale con malattia nel corpo o nella mente (art. 582 c.p.)",
                     "Dolo o colpa (art. 590 c.p. per le lesioni colpose)",
                     "Gravità della lesione: semplice, grave o gravissima (art. 583 c.p.) — decidono i giorni di malattia del "
                     "referto"],
        "evidence": ["Referto medico-legale (giorni di malattia → gravità)", "Foto delle lesioni / cartella clinica",
                     "Arma (coltello) + sequestro", "Testimoni / CCTV sull'inizio del conflitto"],
        "deadlines": ["Querela entro tre mesi dalla notizia del fatto, se le lesioni sono procedibili a querela (art. 124 c.p.); d'ufficio con "
                      "le aggravanti (art. 582, secondo periodo)",
                      "Prescrizione secondo la gravità (art. 157 c.p.)",
                      "Termini di impugnazione: 15, 30 o 45 giorni secondo il deposito della motivazione (art. 585 c.p.p.)"],
        "defenses": ["Legittima difesa (proporzionalità, art. 52 c.p.)", "Provocazione (art. 62 c.p.)",
                     "Contestazione della gravità della lesione (da grave a semplice)", "Errata identificazione",
                     "Catena di custodia dell'arma"],
        "valuation": ("La pena segue la gravità della lesione e le aggravanti (l'arma: art. 585 c.p.). Battaglia principale: "
                      "gravità della lesione + legittima difesa."),
        "questions": ["Quanti giorni di malattia indica il referto medico-legale?",
                      "Chi ha iniziato il conflitto / c'era una minaccia verso il cliente?",
                      "È stato usato un coltello/arma e come è stato sequestrato?",
                      "C'è stata conciliazione o risarcimento con la vittima?"],
    },
    "mashtrim": {
        "label": "Truffa",
        "elements": ["Artifizi o raggiri", "Induzione in errore della vittima", "Danno patrimoniale altrui",
                     "Ingiusto profitto (dolo) — art. 640 c.p."],
        "evidence": ["Documenti/contratti", "Comunicazioni (email, messaggi)", "Transazioni bancarie",
                     "Dichiarazioni della persona offesa", "Perizia contabile/finanziaria"],
        "deadlines": ["Querela entro tre mesi dalla notizia del fatto, se la truffa è procedibile a querela (art. 124 c.p.)",
                      "Prescrizione (art. 157 c.p.)",
                      "Termini di impugnazione: 15, 30 o 45 giorni secondo il deposito della motivazione (art. 585 c.p.p.)"],
        "defenses": ["Controversia meramente civile (inadempimento, non truffa)", "Assenza di dolo iniziale",
                     "Assenza del nesso causale con il danno"],
        "valuation": ("La pena è quella dell'art. 640 c.p. (aggravata nei casi del secondo comma); il danno di rilevante gravità o "
                      "di speciale tenuità conta come circostanza (artt. 61 e 62 c.p.). Argomenta la natura civile per evitare il "
                      "penale."),
        "questions": ["In cosa è consistita la truffa e come è stata indotta in errore la vittima?",
                      "A quanto ammonta il danno patrimoniale e come si prova?",
                      "Ci sono prove del dolo sin dall'inizio (non un semplice inadempimento contrattuale)?"],
    },
    "mosmarreveshje_civile": {
        "label": "Controversia civile / contratto",
        "elements": ["Esistenza dell'obbligazione (contratto valido)", "Inadempimento (art. 1218 c.c.)",
                     "Danno da inadempimento", "Nesso causale"],
        "evidence": ["Contratto + allegati", "Prove dell'adempimento/inadempimento", "Corrispondenza", "Fatture/pagamenti",
                     "Perizia sul danno"],
        "deadlines": ["Prescrizione ordinaria di dieci anni (art. 2946 c.c.), salvo i termini brevi del singolo contratto",
                      "Termini contrattuali di denuncia e di diffida"],
        "defenses": ["Adempimento eseguito", "Eccezione di inadempimento (art. 1460 c.c.)", "Nullità del contratto",
                     "Impossibilità sopravvenuta / forza maggiore", "Prescrizione"],
        "valuation": ("Danno = danno emergente + lucro cessante (art. 1223 c.c.), nei limiti del danno prevedibile se non c'è dolo "
                      "(art. 1225 c.c.); verifica la clausola penale (artt. 1382-1384 c.c.)."),
        "questions": ["Qual è il contratto e l'obbligazione violata?", "Come è stata violata e quale danno ha causato?",
                      "C'è una clausola penale o un termine?", "L'altra parte è stata messa in mora per l'inadempimento?"],
    },
    "abuzim_policor": {
        "label": "Abuso di polizia / posto di blocco",
        "elements": ["Qualifica degli operanti (polizia giudiziaria o di pubblica sicurezza) e base giuridica dell'intervento",
                     "Identificazione: accompagnamento negli uffici solo per il tempo necessario, nei limiti di ore dell'art. "
                     "349 c.p.p.",
                     "Legittimità della perquisizione della persona/del veicolo (casi di legge, flagranza: art. 352 c.p.p.)",
                     "Legittimità e durata del trattenimento",
                     "Proporzionalità della forza (uso legittimo delle armi solo se costretti: art. 53 c.p.) e conseguenze "
                     "(lesioni, tortura)",
                     "Diritti della persona (difensore, informazione sul motivo del trattenimento)"],
        "evidence": ["Referto medico sulle lesioni — URGENTE, fallo subito", "Foto/video delle lesioni con data",
                     "Verbale di identificazione, perquisizione o sequestro (richiedilo per iscritto)",
                     "Registrazioni delle telecamere del posto di blocco / body-cam", "Ordine di servizio e nomi degli operanti",
                     "Testimoni oculari"],
        "deadlines": ["Querela entro tre mesi dalla notizia del fatto per i reati procedibili a querela (art. 124 c.p.); per gli altri la "
                      "denuncia, il prima possibile (le prove scompaiono, le lesioni si attenuano)",
                      "Referto medico entro 24-48 ore",
                      "Esposto al Questore o al Comando dell'Arma (profilo disciplinare) e denuncia alla Procura della Repubblica"],
        "defenses": ["Pretesa del 'fondato motivo' per la perquisizione — contesta: manca una base concreta",
                     "Pretesa di 'resistenza/pericolo' per giustificare la forza — contesta con il video",
                     "Pretesa che il trattenimento fosse nei limiti di legge — verifica la durata effettiva",
                     "Verbale non conforme ai fatti — confrontalo con video e testimoni"],
        "valuation": ("Distingui le responsabilità: (a) PENALE degli operanti (trattenimento illegittimo: sequestro di persona, "
                      "art. 605 c.p., o arresto illegale, art. 606 c.p.; percosse e lesioni, artt. 581-582 c.p.; violenza "
                      "privata, art. 610 c.p.; abuso di autorità contro arrestati o detenuti, art. 608 c.p.; tortura, art. "
                      "613-bis c.p.), "
                      "(b) DISCIPLINARE (esposto all'amministrazione di appartenenza), (c) RISARCIMENTO (costituzione di parte "
                      "civile nel processo penale, art. 74 c.p.p., o causa civile contro l'amministrazione: art. 28 Cost.; artt. 2043 e 2059 "
                      "c.c.). "
                      "Valuta il danno patrimoniale + non patrimoniale."),
        "questions": ["Data, ora e luogo esatto del posto di blocco?",
                      "Gli operanti si sono qualificati e hanno indicato il reparto?",
                      "Hai lesioni e hai un referto medico?",
                      "Quanto è durato il trattenimento e ti hanno permesso di avvisare un avvocato o un familiare?",
                      "Ti hanno consegnato un verbale o un atto scritto?"],
        "dual": ("\n\nQUESTO CASO HA DUE MENTI OPPOSTE — rendile entrambe affilate:\n"
                 "### \U0001f6e1️ LA MENTE DEL CITTADINO (IL SUO AVVOCATO) — quali diritti sono stati violati, quali "
                 "articoli li proteggono, come si costruiscono denuncia e azione di risarcimento, quali prove servono prima che "
                 "scompaiano.\n"
                 "### \U0001f46e LA MENTE DELLA DIFESA DEGLI OPERANTI — come giustificheranno l'intervento (fondato motivo, "
                 "pericolo, proporzionalità), dov'è il loro punto forte — per prevenirlo e smontarlo.\n"
                 "Chi conosce la difesa dell'altro vince."),
    },
}

# La sezione «due menti» delle perizie penali (quella albanese parla di «MENDJA E PROKURORIT»)
DUAL_PENALE_IT = (
    "\n\nÈ UN CASO PENALE — dai l'analisi con DUE MENTI OPPOSTE, perché lo stesso utente capisca le due parti:\n"
    "### \U0001f3db️ LA MENTE DEL PUBBLICO MINISTERO — cosa deve provare per ogni elemento, quali prove gli servono, dove "
    "è forte.\n"
    "### ⚖️ LA MENTE DEL DIFENSORE — quale elemento è più debole, dove attacca, quali difese solleva, quali prove "
    "mancano.\n"
    "Chi conosce la mente dell'altro vince — rendile entrambe affilate."
)

FORMA_EKSP_IT = (
    "\n\nFORMA (obbligatoria): BREVE ed esatta — in tutto non oltre circa 1.300 parole. In ogni sezione solo i punti che servono "
    "al caso, una o due frasi ciascuno; tabelle solo se chiariscono, brevi. Non ripetere il testo degli articoli: bastano "
    "l'articolo e il senso in una riga. Cita SEMPRE con «art.» davanti al numero e il codice dopo («art. [numero] c.p.», «art. "
    "[numero] c.p.p.»), anche nelle tabelle: altrimenti la citazione non si verifica. Non elencare articoli che NON si applicano "
    "e non spiegare perché non si applicano: gli articoli del blocco che non c'entrano col caso lasciali fuori senza nominarli. "
    "Quando ti manca un articolo che servirebbe, dillo in UNA riga. Calcola i termini dalla data del fatto, della notifica o "
    "della conoscenza, secondo l'articolo che li fissa."
)
