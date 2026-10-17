"""v9.656 — GLI ATTI DEL NOTAIO IN SESSIONE ITALIANA, scritti per il diritto italiano.

Fino alla v9.655 il redattore degli atti («Redigi atto notarile») in sessione italiana riceveva il catalogo ALBANESE: le clausole
obbligatorie dell'atto in albanese (in una compravendita italiana «Deklarimi i mungesës së barrëve», la registrazione
«në ASHK/QKB»), i semi del Codice civile albanese (nell'indice italiano non esistono: l'atto restava senza gli articoli della
forma e della trascrizione) e il prompt «Ti je NOTER shqiptar… Ligji nr. 110/2018». Qui, con le STESSE chiavi del catalogo
albanese, l'etichetta, le clausole e gli articoli dell'atto italiano; ogni seme è verificato sul corpus italiano (golden [465]).
Senza import: lo legge `notary`."""

_CC = "codice_civile"

ATTI_IT = {
    "shitje_pasurie": {
        "parole": "vendita vende vendere venduto acquisto acquista acquistare compra comprare rogito appartamento casa immobile terreno villa box fabbricato",
        "label": "Compravendita immobiliare",
        "must": ["Identità completa delle parti e regime patrimoniale (comunione legale: l'intervento del coniuge)",
                 "Immobile: dati catastali, confini e dichiarazione di conformità catastale (art. 29 L. 52/1985)",
                 "Menzioni urbanistiche (titolo edilizio, art. 46 TU edilizia) e attestato di prestazione energetica",
                 "Prezzo e modalità di pagamento (mezzi tracciabili)",
                 "Garanzia per evizione e per vizi; libertà da ipoteche, trascrizioni pregiudizievoli e pesi",
                 "Data, lettura, sottoscrizioni; trascrizione nei registri immobiliari"],
        "seed": [(_CC, "1470"), (_CC, "1476"), (_CC, "1483"), (_CC, "1490"), (_CC, "1350"), (_CC, "2643"),
                 (_CC, "2657"), (_CC, "177"), (_CC, "179"), (_CC, "184"), ("legge_52_1985", "29"), ("tu_edilizia", "46"),
                 ("prestazione_energetica", "6"), ("legge_notarile", "47"), ("legge_notarile", "51")],
    },
    "hipoteke": {
        "parole": "ipoteca ipotecaria iscrizione garanzia mutuo fondiario",
        "label": "Concessione di ipoteca volontaria",
        "must": ["Parti (creditore, datore d'ipoteca, debitore se diverso)",
                 "Credito garantito e somma per cui si iscrive l'ipoteca",
                 "Immobile ipotecato (dati catastali e confini)",
                 "Durata dell'iscrizione (vent'anni, rinnovabile) e grado",
                 "Forma (atto pubblico o scrittura privata autenticata); iscrizione nei registri immobiliari"],
        "seed": [(_CC, "2808"), (_CC, "2821"), (_CC, "2838"), (_CC, "2847"), (_CC, "2827"), ("legge_52_1985", "29")],
    },
    "prokure": {
        "parole": "procura procuratore rappresentante delega poteri",
        "label": "Procura (generale o speciale)",
        "must": ["Rappresentato e procuratore (identità)", "Poteri conferiti e loro limiti (generale o speciale)",
                 "Durata e facoltà di sostituzione (solo se date)",
                 "Forma richiesta per l'atto da compiere (art. 1392 c.c.)", "Data, sottoscrizione, autentica"],
        "seed": [(_CC, "1387"), (_CC, "1392"), (_CC, "1393"), (_CC, "1394"), (_CC, "1395"), (_CC, "1396"), (_CC, "1708")],
    },
    "testament": {
        "parole": "testamento testatore erede legato ultime volontà",
        "label": "Testamento pubblico",
        "must": ["Testatore: identità e capacità (art. 591 c.c.)",
                 "Disposizioni chiare (istituzione di erede, legati)",
                 "Rispetto delle quote dei legittimari (artt. 536 ss. c.c.)",
                 "Forma: dichiarazione della volontà al notaio in presenza di due testimoni (art. 603 c.c.)",
                 "Data, lettura, sottoscrizioni; iscrizione nel Registro generale dei testamenti"],
        "seed": [(_CC, "601"), (_CC, "603"), (_CC, "591"), (_CC, "457"), (_CC, "536"), (_CC, "537"), (_CC, "540"),
                 (_CC, "549"), (_CC, "679")],
    },
    "dhurim": {
        "parole": "donazione dona donare donatario regalo liberalità",
        "label": "Donazione",
        "must": ["Donante e donatario", "Oggetto (solo beni presenti: art. 771 c.c.)",
                 "Forma: atto pubblico in presenza di due testimoni, a pena di nullità (art. 782 c.c.; art. 48 legge notarile)",
                 "Accettazione del donatario (nell'atto o in atto pubblico successivo)",
                 "Data, sottoscrizioni; trascrizione se ha per oggetto immobili"],
        "seed": [(_CC, "769"), (_CC, "771"), (_CC, "782"), (_CC, "800"), (_CC, "801"), (_CC, "2643"),
                 ("legge_notarile", "48")],
    },
    "trashegimi": {
        "parole": "eredità erede successione defunto accettazione deceduto morto",
        "label": "Accettazione di eredità (atto notarile)",
        "must": ["Defunto, data e luogo di apertura della successione", "Chiamati all'eredità e titolo (legge o testamento)",
                 "Quote spettanti", "Beni ereditari",
                 "Forma dell'accettazione (espressa o con beneficio d'inventario) e trascrizione dell'acquisto (art. 2648 c.c.)"],
        "seed": [(_CC, "459"), (_CC, "470"), (_CC, "474"), (_CC, "475"), (_CC, "484"), (_CC, "565"), (_CC, "566"),
                 (_CC, "581"), (_CC, "2648")],
    },
    "kontrate_martese": {
        "parole": "convenzione matrimoniale coniugi separazione beni fondo patrimoniale nubendi",
        "label": "Convenzione matrimoniale",
        "must": ["Coniugi o nubendi (identità)",
                 "Regime scelto (separazione dei beni, comunione convenzionale, fondo patrimoniale)", "Beni compresi",
                 "Forma: atto pubblico con due testimoni (art. 162 c.c.; art. 48 legge notarile) e annotazione a margine "
                 "dell'atto di matrimonio",
                 "Data, sottoscrizioni"],
        "seed": [(_CC, "159"), (_CC, "162"), (_CC, "163"), (_CC, "167"), (_CC, "210"), (_CC, "215"),
                 ("legge_notarile", "48")],
    },
    "themelim_shoqerie": {
        "parole": "costituzione società srl socio soci capitale atto costitutivo",
        "label": "Atto costitutivo di società (S.r.l.)",
        "must": ["Soci e quote", "Denominazione, sede, oggetto sociale", "Capitale sociale e conferimenti",
                 "Amministrazione e rappresentanza", "Data, sottoscrizioni; deposito e iscrizione nel registro delle imprese"],
        "seed": [(_CC, "2463"), (_CC, "2463-bis"), (_CC, "2464"), (_CC, "2475"), (_CC, "2330")],
    },
    "qira": {
        "parole": "locazione affitto affittare inquilino conduttore locatore canone",
        "label": "Contratto di locazione",
        "must": ["Locatore e conduttore", "Immobile (dati catastali) e destinazione",
                 "Durata e rinnovo (regime della locazione abitativa o commerciale)", "Canone, aggiornamento e deposito cauzionale",
                 "Obblighi di manutenzione e riconsegna", "Data, sottoscrizioni; registrazione"],
        "seed": [(_CC, "1571"), (_CC, "1575"), (_CC, "1587"), ("locazioni_abitative", "1"), ("locazioni_abitative", "2"),
                 ("locazioni_abitative", "13")],
    },
    "huaje": {
        "parole": "mutuo prestito presta prestare restituzione interessi",
        "label": "Contratto di mutuo",
        "must": ["Mutuante e mutuatario", "Somma e modalità di erogazione", "Interessi (tasso, pattuizione per iscritto)",
                 "Piano di restituzione e decadenza dal beneficio del termine", "Garanzie eventuali",
                 "Data, sottoscrizioni (in atto pubblico: titolo esecutivo)"],
        "seed": [(_CC, "1813"), (_CC, "1815"), (_CC, "1819"), ("codice_procedura_civile", "474")],
    },
    "sipermarrje": {
        "parole": "appalto appaltatore lavori ristrutturazione impresa opera",
        "label": "Contratto d'appalto",
        "must": ["Committente e appaltatore", "Opera o servizio e capitolato", "Corrispettivo e pagamenti",
                 "Termini di esecuzione e penali", "Verifica, collaudo e garanzia per difformità e vizi",
                 "Data, sottoscrizioni"],
        "seed": [(_CC, "1655"), (_CC, "1657"), (_CC, "1665"), (_CC, "1667"), (_CC, "1668"), (_CC, "1669")],
    },
    "peng": {
        "parole": "pegno pignoratizio garanzia bene mobile",
        "label": "Costituzione di pegno (bene mobile)",
        "must": ["Creditore pignoratizio e costituente", "Credito garantito",
                 "Bene dato in pegno e sua consegna", "Atto scritto con data certa (art. 2787 c.c.)", "Data, sottoscrizioni"],
        "seed": [(_CC, "2784"), (_CC, "2786"), (_CC, "2787")],
    },
    "shkembim": {
        "parole": "permuta scambio scambiare",
        "label": "Permuta",
        "must": ["Permutanti", "Beni scambiati (dati catastali se immobili) ed eventuale conguaglio",
                 "Garanzie (si applicano le norme sulla vendita)", "Data, sottoscrizioni; trascrizione se immobili"],
        "seed": [(_CC, "1552"), (_CC, "1555"), (_CC, "1350"), (_CC, "2643")],
    },
    "shitje_automjeti": {
        "parole": "auto automobile veicolo moto targa vendita",
        "label": "Vendita di autoveicolo (atto con firma autenticata)",
        "must": ["Venditore e acquirente", "Veicolo (targa, telaio, carta di circolazione)", "Prezzo e pagamento",
                 "Autentica della firma del venditore e trascrizione al PRA (art. 94 C.d.S.)", "Data, sottoscrizioni"],
        "seed": [(_CC, "1470"), (_CC, "2683"), (_CC, "2703"), ("codice_strada", "94")],
    },
    "shitje_kuotash": {
        "parole": "cessione quote quota partecipazione socio srl",
        "label": "Cessione di quote di S.r.l.",
        "must": ["Cedente e cessionario", "Società (denominazione, sede, codice fiscale) e quota ceduta",
                 "Prezzo e pagamento", "Limiti statutari al trasferimento (prelazione, gradimento)",
                 "Data, sottoscrizioni; deposito nel registro delle imprese (art. 2470 c.c.)"],
        "seed": [(_CC, "2469"), (_CC, "2470")],
    },
    "premtim_shitje": {
        "parole": "preliminare compromesso caparra promessa",
        "label": "Contratto preliminare di compravendita (con caparra)",
        "must": ["Promittente venditore e promissario acquirente", "Immobile e dati catastali", "Prezzo e caparra confirmatoria",
                 "Termine per il definitivo", "Forma scritta; trascrizione del preliminare se in atto pubblico o con firme "
                 "autenticate (art. 2645-bis c.c.)", "Data, sottoscrizioni"],
        "seed": [(_CC, "1351"), (_CC, "1385"), (_CC, "2645-bis"), (_CC, "2932")],
    },
    "aktmarreveshje": {
        "parole": "transazione accordo lite controversia",
        "label": "Transazione",
        "must": ["Parti e lite (in corso o che può sorgere)", "Reciproche concessioni", "Obblighi e termini di adempimento",
                 "Rinunce e quietanza", "Data, sottoscrizioni (in atto pubblico: titolo esecutivo)"],
        "seed": [(_CC, "1965"), (_CC, "1966"), ("codice_procedura_civile", "474")],
    },
    "statut_shpk": {
        "parole": "statuto srl società regole",
        "label": "Statuto di S.r.l.",
        "must": ["Denominazione, sede, oggetto, durata", "Capitale e partecipazioni", "Amministrazione e rappresentanza",
                 "Decisioni dei soci e assemblea", "Trasferimento delle quote", "Bilancio e utili"],
        "seed": [(_CC, "2463"), (_CC, "2475"), (_CC, "2479"), (_CC, "2479-bis"), (_CC, "2469")],
    },
    "vendim_asambleje": {
        "parole": "assemblea verbale delibera soci",
        "label": "Verbale di assemblea dei soci di S.r.l.",
        "must": ["Convocazione, intervenuti e quorum", "Ordine del giorno", "Deliberazioni e voti",
                 "Firma del presidente e del segretario (o del notaio per le modifiche dell'atto costitutivo)",
                 "Deposito e iscrizione nel registro delle imprese, se richiesti"],
        "seed": [(_CC, "2479"), (_CC, "2479-bis"), (_CC, "2480"), (_CC, "2436")],
    },
    "likuidim_shpk": {
        "parole": "liquidazione scioglimento liquidatore cancellazione chiusura società",
        "label": "Scioglimento e liquidazione di S.r.l.",
        "must": ["Causa di scioglimento", "Nomina dei liquidatori e loro poteri", "Criteri della liquidazione",
                 "Bilancio finale e piano di riparto", "Cancellazione dal registro delle imprese"],
        "seed": [(_CC, "2484"), (_CC, "2487"), (_CC, "2492"), (_CC, "2495")],
    },
    "uzufrukt": {
        "parole": "usufrutto usufruttuario nuda proprietà",
        "label": "Costituzione di usufrutto",
        "must": ["Proprietario e usufruttuario", "Bene (dati catastali)", "Durata (al massimo la vita dell'usufruttuario)",
                 "Diritti e obblighi (inventario e garanzia)", "Data, sottoscrizioni; trascrizione"],
        "seed": [(_CC, "978"), (_CC, "979"), (_CC, "981"), (_CC, "1002"), (_CC, "2643")],
    },
    "servitut": {
        "parole": "servitù passaggio fondo servente dominante",
        "label": "Costituzione di servitù (passaggio ecc.)",
        "must": ["Fondo servente e fondo dominante (dati catastali)", "Contenuto ed esercizio della servitù",
                 "Eventuale indennità", "Data, sottoscrizioni; trascrizione"],
        "seed": [(_CC, "1027"), (_CC, "1031"), (_CC, "1058"), (_CC, "1063"), (_CC, "2643")],
    },
}

# v9.657 — le DICHIARAZIONI del notaio in sessione italiana (stesse chiavi di notary.DECLARATION_TYPES): prima il catalogo
# albanese (i semi del KF 215-222 e del KC 64, che nell'indice italiano non esistono) e il prompt «Ti je NOTER shqiptar…»
DICHIARAZIONI_IT = {
    "pelqim_udhetimi_minor": {
        "label": "Assenso del genitore al viaggio / all'espatrio del minore",
        "must": ["Genitore dichiarante (identità) e indicazione dell'altro genitore",
                 "Minore (nome, data di nascita, documento)",
                 "Assenso al viaggio o all'espatrio: destinazione, accompagnatore, periodo",
                 "Data, sottoscrizione, autentica della firma"],
        "seed": [(_CC, "316"), (_CC, "337-ter"), (_CC, "2703")],
    },
    "mbajtje_financiare": {
        "label": "Dichiarazione di garanzia economica (per il visto)",
        "must": ["Dichiarante (garante) e beneficiario", "Rapporto fra loro",
                 "Impegno a coprire le spese (alloggio, vitto, viaggio)", "Periodo e scopo (visto)",
                 "Redditi o mezzi con cui le spese sono coperte", "Data, sottoscrizione, autentica della firma"],
        "seed": [("codice_visti", "14"), ("tu_immigrazione", "4"), (_CC, "2703")],
    },
    "pelqim_bashkeshortor": {
        "label": "Consenso del coniuge (comunione legale)",
        "must": ["Coniuge dichiarante", "Atto a cui si presta il consenso (straordinaria amministrazione dei beni comuni)",
                 "Bene interessato", "Data, sottoscrizione (nella forma dell'atto a cui si riferisce)"],
        "seed": [(_CC, "177"), (_CC, "180"), (_CC, "184")],
    },
    "autorizim_perfaqesimi": {
        "label": "Delega / autorizzazione",
        "must": ["Delegante e delegato", "Atto o scopo della delega", "Limiti e durata", "Data, sottoscrizione, autentica"],
        "seed": [(_CC, "1387"), (_CC, "1392"), (_CC, "2703")],
    },
    "vertetim_fakti": {
        "label": "Dichiarazione sostitutiva dell'atto di notorietà (firma autenticata)",
        "must": ["Dichiarante (identità)", "Fatto, stato o qualità dichiarati con chiarezza",
                 "Avvertenza sulle sanzioni penali per le dichiarazioni mendaci (art. 76 d.P.R. 445/2000)",
                 "Data, sottoscrizione e autentica"],
        "seed": [("tu_documentazione_amministrativa", "47"), ("tu_documentazione_amministrativa", "76"),
                 ("tu_documentazione_amministrativa", "21")],
    },
    "burim_fondesh": {
        "label": "Dichiarazione sull'origine dei fondi (antiriciclaggio)",
        "must": ["Dichiarante", "Somma e operazione", "Origine lecita dei fondi e mezzi di pagamento",
                 "Dichiarazione di veridicità (obblighi del cliente, art. 22 d.lgs. 231/2007)", "Data, sottoscrizione"],
        "seed": [("antiriciclaggio", "22"), ("antiriciclaggio", "18"), ("antiriciclaggio", "19")],
    },
}
