# Registro dei trattamenti

**Documento interno — non si consegna al cliente, si mostra all'autorità**

Art. 30 GDPR · Ligji nr. 124/2024 · versione 2026-08-31

---

> ⚠️ **BOZZA DA FAR VERIFICARE.** Base di lavoro preparata da un assistente.
> Va riletta da un avvocato e **aggiornata a ogni cambiamento reale** — un
> registro che descrive un sistema che non esiste più è peggio di nessun
> registro: davanti a un'ispezione dimostra che non lo si tiene.

---

## Il titolare / responsabile

| | |
|---|---|
| **Chi** | Super Avokati — superavokati.ai |
| **Contatto** | info@aala.global · +355 69 95 55 777 |
| **Sedi** | Tirana · Milano |
| **Responsabile protezione dati (DPO)** | ⚠️ **da valutare** — vedi nota in fondo |

**Due ruoli distinti, e vanno tenuti separati** perché gli obblighi cambiano:

- **PARTE A** — Super Avokati è **titolare** (*kontrollues*) dei dati degli
  utenti professionisti: sono dati suoi, decide lui perché trattarli.
- **PARTE B** — Super Avokati è **responsabile** (*përpunues*) dei dati dei
  clienti degli studi: lì decide lo studio, Super Avokati esegue.

Confondere i due ruoli è l'errore che rende inutile tutto il resto del registro.

---

# PARTE A — Come titolare (dati degli utenti professionisti)

## A1. Account e autenticazione

| | |
|---|---|
| **Finalità** | consentire l'accesso e identificare chi lavora |
| **Interessati** | avvocati, notai, procuratori, personale dello studio |
| **Dati** | nome utente, email, hash della password, appartenenza allo studio, ruolo |
| **Base giuridica** | esecuzione del contratto (art. 6.1.b) |
| **Dove** | `users`, `firms`, `firm_members` |
| **Conservazione** | durata del rapporto + 12 mesi |
| **Destinatari** | nessuno esterno |
| **Misure** | password PBKDF2-SHA256 con salt; freno 5/20 tentativi; accesso al DB limitato al solo processo dell'applicazione |

## A2. Registro degli accessi ai fascicoli

| | |
|---|---|
| **Finalità** | sicurezza; poter dire **quali** clienti sono stati esposti in caso di incidente, invece di doverli avvisare tutti |
| **Dati** | utenza, fascicolo, data, indirizzo IP, dispositivo |
| **Base giuridica** | legittimo interesse alla sicurezza (art. 6.1.f) |
| **Dove** | `case_access_log` |
| **Conservazione** | **24 mesi** |
| **Nota** | metadati soltanto — nessun contenuto del fascicolo, per non raddoppiare i dati da proteggere |

## A3. Registro delle chiamate al motore di analisi

| | |
|---|---|
| **Finalità** | qualità, diagnosi dei guasti, poter ricostruire **come** è nata una risposta |
| **Dati** | utenza, fascicolo, momento, modello, esito, impronte crittografiche del testo |
| **Base giuridica** | legittimo interesse (art. 6.1.f) |
| **Dove** | `ai_audit_log` |
| **Conservazione** | **12 mesi** |
| **✅ Verificato 30/08/2026** | `AUDIT_STORE_RAW` **non è impostata** e **0 righe su 1.233** contengono il testo: nel registro ci sono solo impronte crittografiche, nessun contenuto di fascicolo. ⚠️ Se un giorno la si accendesse, questo registro **cambierebbe natura** e andrebbe riscritto |

## A4. Prova dell'accettazione delle condizioni

| | |
|---|---|
| **Finalità** | dimostrare chi ha accettato **quale versione** e quando |
| **Dati** | utenza, versione, documenti, data, IP, dispositivo |
| **Base giuridica** | obbligo legale / accountability (art. 5.2) |
| **Dove** | `legal_acceptances` |
| **Conservazione** | **10 anni** (termine di prescrizione ordinario) |

## A5. Notifiche push

| | |
|---|---|
| **Finalità** | avvisare quando un'analisi è pronta |
| **Dati** | endpoint del browser e chiavi di cifratura del dispositivo |
| **Base giuridica** | consenso (chiesto solo al click) |
| **Dove** | `push_subscriptions` |
| **Conservazione** | fino alla revoca; **cancellazione automatica** su errore 404/410 (dispositivo sparito) |

---

# PARTE B — Come responsabile (dati dei clienti degli studi)

Un'unica voce, perché la finalità è una sola: **erogare il servizio su
istruzione dello studio**. Titolare è ciascuno studio.

| | |
|---|---|
| **Categorie di interessati** | clienti degli studi, controparti, testimoni, periti, e chiunque sia nominato nei documenti |
| **Tipi di dati** | dati identificativi e di contatto; contenuto di atti, contratti, sentenze, corrispondenza |
| **⚠️ Categorie particolari** | **dati relativi a condanne penali e reati (art. 10)** e dati sensibili (art. 9) quando il fascicolo li contiene — per la natura stessa del servizio. Sono coperti da **segreto professionale** |
| **Dove** | `cases`, `messages`, `documents` (+ file su disco), `case_parties`, `case_research`, `case_timelines`, `events`, `reminders`, `client_contacts` |
| **Conservazione** | durata del contratto; alla cessazione **restituzione o cancellazione entro 30 giorni**, backup compresi entro il ciclo di rotazione (max 14 giorni) |
| **Trasferimenti** | vedi B1 |

## A6. Analisi di registrazioni video depositate come prova

⚠️ **Trattamento con rischio più alto degli altri.** Un video di
videosorveglianza contiene immagini di persone del tutto estranee al
procedimento, che non hanno rapporti con lo Studio e non sanno di essere in un
fascicolo giudiziario. È stato aggiunto il 31 agosto 2026 ed è una modifica
**sostanziale**, non un'estensione dei formati accettati.

| | |
|---|---|
| **Finalità** | permettere al professionista di leggere, mettere in fila e confrontare con gli atti una prova video |
| **Interessati** | le persone riprese: parti, testimoni, **e terzi estranei** (clienti, passanti, personale) |
| **Dati** | immagini di persone e luoghi; metadati tecnici del file; descrizioni testuali dei fotogrammi |
| **Base giuridica** | esecuzione del contratto verso lo Studio (art. 6.1.b); per lo Studio, l'esercizio del diritto di difesa (art. 9.2.f) |
| **Dove** | file su disco in `data/uploads/<caso>/`; descrizioni in `documents.extracted_text` |
| **Conservazione** | come gli altri documenti del fascicolo: durata del contratto, poi restituzione o cancellazione entro 30 giorni |
| **Destinatari** | Tetramorph (motore di analisi, operato da Anthropic PBC — Stati Uniti) per la descrizione dei fotogrammi |
| **Misure** | **nessun riconoscimento facciale né identificazione biometrica** — divieto scritto nelle istruzioni al motore e verificato a ogni rilascio dal controllo automatico; le persone sono indicate per posizione. I **fotogrammi estratti non vengono conservati**: vivono in una cartella temporanea cancellata a fine analisi. Limite di 500 MB per file. Minimizzazione richiesta contrattualmente allo Studio (caricare solo le porzioni necessarie). |

**Limite dichiarato**: il motore non elabora il video ma un numero limitato di
fotogrammi (massimo 24). L'avviso è scritto **dentro il risultato** che il
professionista legge, non solo qui.

## B1. Sub-responsabili e trasferimenti

| Chi | Cosa | Dove | Garanzia |
|---|---|---|---|
| **Tetramorph** — motore di analisi, operato da **Anthropic PBC** | elabora i testi inviati al motore | **Stati Uniti** | Clausole Contrattuali Standard |
| **Contabo GmbH** | ospita il server | Germania (UE) | interno UE |
| **Resend** | email di servizio | UE/USA | Clausole Contrattuali Standard |

⚠️ **Il trasferimento verso il motore Tetramorph è il punto più delicato del registro.**
È dichiarato nell'accordo con gli studi e nell'informativa. Va **riverificato**
se cambia il fornitore del motore o la sua sede.

---

# Le misure di sicurezza (art. 32)

Verificate il **30 agosto 2026**. L'elenco esteso è nell'Allegato A dell'accordo
con gli studi; qui la sintesi con i **limiti dichiarati**.

| Ambito | Misura |
|---|---|
| Accesso | isolamento fra studi verificato · PBKDF2 · freno ai tentativi · registro accessi |
| Trasmissione | TLS 1.3 · HSTS · Content-Security-Policy con `connect-src 'self'` |
| Server | accesso **solo a chiave** · nessuna password · porte di servizio non raggiungibili dall'esterno · fail2ban |
| Conservazione | dati leggibili **solo** dal processo dell'applicazione · **backup cifrati AES-256** con ripristino provato |
| Motore | **confinato**: legge solo i documenti del fascicolo su cui lavora, non il codice né la banca dati · ogni chiamata registrata |

**Limiti — dichiarati perché un elenco che li tace non è verificabile:**
1. i documenti e la banca dati sono conservati **non cifrati** sul disco,
   protetti dai permessi del sistema e dalla cifratura dei backup;
2. chi ottenesse i privilegi di amministratore del server accederebbe ai dati;
3. **la chiave dei backup vive sul server**: protegge il file che esce, non il
   server stesso.

---

# ⚠️ Punti aperti — da decidere, non da dimenticare

1. **DPO**: valutare se è obbligatorio. Il trattamento **su larga scala di dati
   relativi a reati** è uno dei criteri che lo rendono necessario. **Da
   sottoporre a un avvocato**: se serve e non c'è, è una violazione autonoma.
2. **Valutazione d'impatto (DPIA)**: probabilmente dovuta — dati giudiziari +
   tecnologia nuova + trattamento su larga scala. Anche questa da valutare.
3. **Traduzione albanese** di questo registro e della procedura di violazione,
   se l'IDP li richiede.
4. **Nessun avviso automatico di sicurezza**: oggi la rilevazione di un
   incidente dipende da qualcuno che guarda i log. Vedi la procedura di
   violazione, sezione «Cosa NON c'è».
5. **Un solo amministratore**: rischio organizzativo, non tecnico.
6. **Aggiornare questo documento a ogni cambiamento** — nuova tabella, nuovo
   fornitore, nuova finalità. Un registro che descrive un sistema che non
   esiste più dimostra che non lo si tiene.
