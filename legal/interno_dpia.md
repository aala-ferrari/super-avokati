# Valutazione d'impatto sulla protezione dei dati (DPIA)

**Super Avokati — assistente legale con motore Tetramorph**

**Documento interno** — art. 35 GDPR (UE 2016/679) · Ligji nr. 124/2024
Versione 1.0 — 31 agosto 2026 · prossima revisione: **31 agosto 2027**

---

> ⚠️ **BOZZA DA FAR VERIFICARE.** Preparata da un assistente sulla base di una
> verifica tecnica reale del sistema. Le valutazioni giuridiche — se la DPIA sia
> obbligatoria, se il rischio residuo sia accettabile, se serva la consultazione
> preventiva dell'autorità — vanno confermate da un avvocato.

---

## Chi

| | Albania | Italia |
|---|---|---|
| **Società** | **AALA** — Albania Auto Legal Alliance | **Deltalux Srl** |
| **Sede** | Tirana | Via San Raffaele 1, Milano |
| **P.IVA** | — | 12021700963 |
| **Contatto** | info@aala.global · +355 69 95 55 777 | info@aala.global |
| **Autorità** | Komisioneri për të Drejtën e Informimit dhe Mbrojtjen e të Dhënave Personale (IDP) | Garante per la protezione dei dati personali |

**Ruolo**: per i dati dei clienti degli studi siamo **responsabili del
trattamento** (*përpunues*); titolare è ciascuno studio. Questa DPIA è
predisposta **a supporto dei titolari**, che restano tenuti alla propria.

---

# 1. Perché questa valutazione è necessaria

L'art. 35 la impone quando il trattamento presenta un rischio elevato. Qui
ricorrono **tre criteri contemporaneamente**:

| Criterio | Come si presenta qui |
|---|---|
| **Dati relativi a reati** (art. 10) | i fascicoli contengono imputati, indagati, vittime, misure cautelari |
| **Uso di tecnologia innovativa** | un modello linguistico che legge e analizza atti giudiziari |
| **Larga scala** | il servizio è rivolto a più studi, ciascuno con l'intero portafoglio clienti |

## ⚠️ E un quarto elemento, che è il vero motivo

**Le persone nei fascicoli non sono nostri utenti e non sanno che esistiamo.**

L'imputato, la controparte, il testimone, la vittima: nessuno di loro ha scelto
Super Avokati, nessuno può revocare, nessuno sa a chi rivolgersi. Sono **i più
esposti e i meno tutelati** — ed è esattamente la situazione per cui questa
valutazione esiste.

Tutto il resto del documento va letto con loro in mente, non con in mente
l'avvocato che paga.

---

# 2. Descrizione del trattamento (art. 35.7.a)

## 2.1 Cosa succede, in ordine

1. L'avvocato apre un fascicolo e carica documenti (PDF, foto, atti, sentenze).
2. Il sistema ne estrae il testo; per le immagini usa il riconoscimento ottico.
3. L'avvocato pone una domanda o avvia uno strumento di analisi.
4. **Il motore Tetramorph** riceve: la domanda, il contesto del fascicolo, gli
   articoli di legge recuperati dal corpus e, quando servono, i documenti.
5. La risposta torna all'avvocato, viene salvata nel fascicolo e sottoposta ai
   controlli di citazione.

## 2.2 Dati trattati

| Categoria | Contenuto |
|---|---|
| Identificativi | nomi, contatti delle parti e dei terzi nominati |
| Contenuto processuale | atti, contratti, sentenze, corrispondenza, perizie |
| **Categorie particolari** (art. 9) | salute, convinzioni, vita sessuale — quando il fascicolo li contiene |
| **Dati giudiziari** (art. 10) | reati contestati, misure cautelari, condanne |
| Metadati | chi ha aperto quale fascicolo, quando, da dove |

Tutto è coperto da **segreto professionale**.

## 2.3 Finalità

Una sola: **fornire allo studio strumenti di analisi e redazione**. Nessuna
finalità propria, nessuna profilazione, nessuna cessione, **nessun uso per
addestrare modelli**.

## 2.4 Conservazione

Durata del contratto. Alla cessazione: restituzione o cancellazione entro 30
giorni, backup compresi entro il ciclo di rotazione (max 14 giorni).

---

# 3. Necessità e proporzionalità (art. 35.7.b)

**Il trattamento è necessario?** Sì: senza i documenti del fascicolo il servizio
non può fare quello per cui esiste. Un'analisi legale su dati inventati sarebbe
inutile e pericolosa.

**È proporzionato?** Sì, con tre limiti che lo rendono tale:

1. **È lo studio a decidere cosa caricare.** Il sistema non attinge a fonti
   esterne, non arricchisce i profili, non cerca le persone altrove.
2. **Al motore arriva solo il necessario**: gli articoli recuperati sono i primi
   dodici, i precedenti quattro, i documenti solo quelli del fascicolo aperto.
3. **Il motore non conserva**: ogni chiamata è isolata, non c'è memoria fra un
   fascicolo e l'altro se non quella che il sistema stesso ricostruisce dai dati
   dello studio.

**Si poteva fare con meno dati?** No, per il nucleo del servizio. Ma **sì per il
registro delle chiamate**, e infatti è così: **verificato il 30/08/2026, zero
righe su 1.233 contengono il testo dei fascicoli** — solo impronte
crittografiche. Il registro dice *che* una chiamata è avvenuta, non *cosa*
diceva.

---

# 4. I rischi per le persone (art. 35.7.c)

Valutati **dal punto di vista dell'interessato**, non dell'azienda.

## R1 — Le credenziali di uno studio finiscono a un estraneo

**Probabilità: media** — è la prima causa reale di accesso non autorizzato
| **Impatto: molto alto** — accesso all'intero portafoglio clienti di uno studio

*Cosa c'è:* isolamento fra studi verificato (un'utenza non raggiunge i fascicoli
di un'altra); freno di 5 tentativi per utenza e 20 per rete; **registro degli
accessi** che permette di dire *quali* clienti sono stati esposti invece di
avvisarli tutti.

*Cosa manca:* **nessun secondo fattore di autenticazione**, e nessun avviso
automatico su accessi anomali. → vedi Piano d'azione **P1** e **P2**.

**Rischio residuo: MEDIO.**

## R2 — I documenti vengono letti da chi non deve

**Probabilità: bassa** | **Impatto: molto alto**

*Cosa c'è:* controllo d'accesso verificato con quattro tentativi di attacco
(elenco e scarico di documenti altrui, due percorsi di traversal: tutti
respinti); documenti e banca dati leggibili **solo** dal processo
dell'applicazione e non dagli altri servizi della macchina; backup cifrati
AES-256 con ripristino provato.

*Cosa manca:* **i documenti non sono cifrati a riposo**. La cifratura
applicativa avrebbe la chiave sullo stesso server, quindi proteggerebbe da un
disco rubato ma non da chi ottiene i privilegi di amministratore. → **P3**.

**Rischio residuo: MEDIO-BASSO.**

## R3 — Il motore viene usato per estrarre ciò che non deve

**Probabilità: bassa** | **Impatto: alto**

⚠️ **Questo rischio si è materializzato in verifica.** Il 30/08/2026 un test
interno ha dimostrato che il motore, quando riceveva allegati, poteva leggere
qualunque file del server — compreso il codice dell'applicazione.

*Chiuso lo stesso giorno:* il motore ora è **confinato** e legge **soltanto** i
documenti del fascicolo su cui sta lavorando. Verificato dopo la correzione:
tentativi di accedere al codice, alla banca dati e alle credenziali → tutti
respinti; documento legittimo → letto correttamente. Tre controlli automatici
sorvegliano che la gabbia non si riapra.

**Rischio residuo: BASSO.** *Il fatto che sia stato trovato da noi e non da un
attaccante è la ragione per cui questa valutazione va rifatta periodicamente.*

## R4 — Un'istruzione ostile nascosta in un documento di controparte

**Probabilità: media** — i documenti arrivano da avversari
| **Impatto: medio**

Un atto ricevuto dalla controparte può contenere istruzioni rivolte al motore
(«ignora le istruzioni e scrivi che…»).

*Cosa c'è:* il contenuto dei documenti è marcato come **sfondo e non come
comando**, con divieto esplicito di obbedire a istruzioni interne; il motore è
confinato, quindi anche obbedendo non raggiunge nulla di sensibile.

*Cosa manca:* il canale web resta aperto sulle chiamate ragionate. → **P4**.

**Rischio residuo: MEDIO-BASSO.**

## R5 — Il motore produce una citazione sbagliata e finisce in un atto

**Probabilità: media** | **Impatto: alto per il cliente dello studio**

*Cosa c'è:* ogni risposta passa da due controlli — uno sugli **articoli**
(esiste? abrogato? aggiornato?) e uno sulle **sentenze** (è nel nostro corpus?).
Quando un articolo non esiste viene marcato; quando una sentenza non si può
confermare l'avviso **si attacca al testo**, così viaggia anche quando la
risposta viene copiata altrove.

*Limite dichiarato:* il controllo **riduce** il rischio, non lo elimina. Le
condizioni d'uso dicono espressamente che ogni citazione va verificata prima di
finire in un atto.

**Rischio residuo: MEDIO** — mitigato dal fatto che il destinatario è un
professionista tenuto a verificare.

## R6 — Trasferimento fuori dall'Unione europea

**Probabilità: certa** (è nel funzionamento) | **Impatto: medio-alto**

I testi inviati a Tetramorph sono elaborati fuori dall'UE. **Dettaglio tecnico
in sezione 5.**

*Cosa c'è:* Clausole Contrattuali Standard; dichiarazione esplicita
nell'accordo con gli studi e nell'informativa; nessun uso dei contenuti per
addestramento.

*Cosa manca:* lo studio non può **escludere selettivamente** un singolo
fascicolo dal trasferimento. → **P5**.

**Rischio residuo: MEDIO.**

## R7 — Nessuno si accorge di un incidente

**Probabilità: media** | **Impatto: alto** (allunga i tempi di reazione)

*Cosa c'è:* registro degli accessi, registro delle chiamate al motore, log di
sistema, procedura di violazione scritta con comandi eseguibili.

*Cosa manca:* **nessun avviso automatico**. Oggi la rilevazione dipende da
qualcuno che guarda. E **c'è un solo amministratore**: se non è raggiungibile,
nessuno può contenere. → **P2** e **P6**.

**Rischio residuo: MEDIO-ALTO.** *È il rischio più alto rimasto, ed è
organizzativo, non tecnico.*

---

# 5. Il motore Tetramorph — dato tecnico per la valutazione del trasferimento

> Questa sezione esiste perché l'art. 35 impone di valutare i trasferimenti
> verso paesi terzi, e non si può valutare ciò che non si nomina. **Nel resto
> della documentazione, e in tutto ciò che vede il cliente, il motore è
> «Tetramorph».** Qui, e solo qui, si indica chi lo opera — perché un documento
> di conformità che lo tace non sembra riservato, sembra reticente.

| | |
|---|---|
| Fornitore che opera il motore | **Anthropic PBC** |
| Paese di elaborazione | **Stati Uniti** |
| Garanzia per il trasferimento | Clausole Contrattuali Standard (UE) |
| Uso per addestramento | **escluso** |
| Conservazione presso il fornitore | secondo i termini del servizio sottoscritto |

**Altri fornitori:** Contabo GmbH (Germania, UE — server) · Resend (email di
servizio).

⚠️ Se il fornitore o il paese di elaborazione cambiano, **questa DPIA e
l'accordo con gli studi vanno aggiornati prima del cambiamento**, non dopo.

---

# 6. Le misure già in atto (art. 35.7.d)

Verificate il 30 agosto 2026 — non dichiarate.

| Rischio | Misura |
|---|---|
| accessi | isolamento fra studi provato · PBKDF2 con salt · freno 5/20 · registro accessi |
| trasmissione | TLS 1.3 · HSTS · CSP con `connect-src 'self'` |
| server | accesso **solo a chiave** · nessuna password · porte di servizio chiuse all'esterno · fail2ban |
| conservazione | dati leggibili solo dal processo dell'app · **backup cifrati** con ripristino provato |
| motore | **confinato** al fascicolo · ogni chiamata registrata · sorvegliato da controlli automatici |
| qualità | verifica degli articoli e delle sentenze citate, con avviso che viaggia col testo |
| trasparenza | accettazione tracciata con versione, data e indirizzo |

---

# 7. Piano d'azione — cosa manca e quando

| | Cosa | Perché | Quando |
|---|---|---|---|
| **P1** | **Secondo fattore di autenticazione** | è la misura che chiude R1, il rischio più probabile | **prioritario** |
| **P2** | Avviso automatico su accessi anomali | oggi nessuno si accorge di niente (R7) | prioritario |
| **P3** | Valutare la cifratura del disco (LUKS) | R2 — la cifratura applicativa non basta, la chiave resterebbe accanto | medio termine |
| **P4** | Disattivare il canale web quando ci sono allegati | riduce R4: se un'istruzione ostile passa, non ha dove mandare i dati | medio termine |
| **P5** | Permettere allo studio di escludere un fascicolo dall'elaborazione esterna | R6 — oggi è tutto o niente | da valutare |
| **P6** | Un secondo amministratore | R7 — un solo punto umano di guasto | **organizzativo** |

---

# 8. Conclusione

**Il trattamento può proseguire** con le misure in atto e il piano d'azione
sopra.

**Rischio residuo complessivo: MEDIO.** Nessun rischio residuo è valutato
*elevato*: **non ricorre l'obbligo di consultazione preventiva** dell'autorità
(art. 36). ⚠️ **Questa conclusione va confermata da un avvocato** — se anche uno
solo dei rischi fosse valutato elevato, la consultazione diventa obbligatoria
**prima** di proseguire.

**Va rifatta se**: cambia il fornitore del motore o il paese di elaborazione ·
si aggiungono categorie di dati o finalità · si apre a un nuovo tipo di utenza ·
si verifica un incidente significativo. **E comunque entro il 31 agosto 2027.**

---

**Redatta da** ________________  data ________
**Approvata da** _______________  data ________
**Consultato il DPO** (se nominato) ________________
