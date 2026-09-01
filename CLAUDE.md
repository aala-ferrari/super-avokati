# Super Avvocato — istruzioni di progetto

Strumento AI per avvocati (B2B), **bi-giurisdizione AL + IT**. Front-end Flask
su porta 5050, SQLite (`data/app.db`) + Postgres `legalkb` per i casi
giurisprudenziali. Due corpora BM25 SEPARATI:
- **AL** (`bm25.pkl`): 6061 nene / 21 codici + `bm25_decisions.pkl` 1258 precedenti
  (Kushtetuese + Gjykata e Lartë + CEDU).
- **IT** (`bm25_it.pkl`): **15.507 articoli / 43 corpora** da Normattiva
  (testi vigenti ufficiali) — vedi "CORPUS ITALIANO" più sotto.

## Regola #1 — Scope: UNA SOLA GIURISDIZIONE PER SESSIONE

**Le due giurisdizioni non si mescolano MAI.** La sessione è bloccata su AL
oppure IT (`web._active_jurisdiction`, scelta al login con la bandiera 🇦🇱/🇮🇹
tra quelle a cui lo studio è abilitato); il caso eredita la giurisdizione
della sessione, e retrieval + preambolo + UI seguono quella. In sessione AL
vale tutto quanto scritto qui sotto; in sessione IT vale il diritto italiano
con il corpus italiano.

**In sessione AL** il corpus è albanese: 21 fonti normative (Kushtetuta +
codici + 5 ligji settoriali = 5615 nene), 282 vendime Gjykata Kushtetuese
(2015-2024), ~813 casi in Postgres `legalkb` (Gjykata e Lartë + ECHR
limitatamente ai casi Albania).

Il modello deve operare e ragionare SOLO dentro questo perimetro:

- **Base argomentativa:** sempre legge shqiptare (KC, KP, KPC, KPP,
  KFamiljes, KPunes, Kushtetuta, ligji settoriali) + giurisprudenza
  Kushtetuese / Gjykata e Lartë. Nessun riferimento a codici di altri
  paesi come autorità.
- **Termini bandidi come basi argomentative:** `riserva`, `legittima`,
  `réserve`, `quotité disponible`, `successione necessaria`. La KC
  shqiptare è più liberale (vedi Neni 378 KC: il testatore può
  escludere eredi legali) — trapiantare quote 50%/75% italo-francesi
  è un anti-consiglio.
- **Comparazioni con sistemi stranieri:** OK SOLO se l'utente le chiede
  esplicitamente ("come funzionerebbe in Italia?"); marcare con
  "krahasim, jo bazë vendimi" e tornare subito al neni shqiptar.
- **Conversazione meta con Romeo (debug, design, analisi rischi):**
  vale lo stesso vincolo. Niente esempi ipotetici con framework
  stranieri (tedesco, US, ecc.) nemmeno come ipotesi.
- **Schema `cases.jurisdiction` AL/IT/EU:** **IT è ATTIVO** (dal 19 ago 2026,
  v9.114→9.131): corpus, retrieval, verifica citazioni, preambolo e UI
  italiani sono live. EU resta predisposizione futura. In sessione AL non
  citare mai il corpus IT e viceversa.

## CORPUS ITALIANO (attivo — 43 corpora / 15.507 articoli)

Fonte: **Normattiva** (normattiva.it, testi vigenti ufficiali; le leggi
italiane non hanno copyright, art. 5 L. 633/1941). NON Wikisource: copre
male i codici moderni e salta gli articoli abrogati/rinumerati.

Contenuto: Costituzione, c.c. (3216) + disp. att., c.p.c. (982), c.p. (978),
c.p.p. (902) + disp. att., Codice della Strada + Regolamento di esecuzione,
Consumo, Crisi d'Impresa, TULPS + ordinamento Pubblica Sicurezza, Statuto
Lavoratori, TU Sicurezza Lavoro, TUB, TUF, Proprietà Industriale, Terzo
Settore, Assicurazioni, D.Lgs 231, L.241/1990, Processo Amministrativo, CAD,
DPR 445, Contratti Pubblici, L.689/1981, Spese Giustizia, Privacy, Ambiente,
Edilizia, Immigrazione, Antimafia, Testo Unico imposte sui redditi, Beni
Culturali, Navigazione, Stupefacenti, Penitenziario, Pari Opportunità,
Protezione Civile, Divorzio, Adozione, Legge Pinto.

Pipeline in `tools/`: `normattiva_lib.py` (sessione + parsing) ·
`ingest_it_normattiva.py` (scarica, resume-safe, un JSON per atto in
`data/processed/it_acts/`) · `build_it_index.py` (→ `bm25_it.pkl` +
`it_codes.json`, con backup del pkl precedente) · `repair_it_corpus.py`
(ri-scarica gli atti incompleti) · `qa_it_corpus.py` (controllo qualità).

**GOTCHA (costati ore — non ripeterli):**
- `/atto/caricaArticolo` dà **HTTP 500 senza sessione**: aprire prima la
  pagina dell'atto (URN) con lo stesso cookie jar. Serve UA da browser.
- Normattiva serve **TRE formati di markup**: AKN con commi (decreti
  moderni), AKN testo unico (`art-just-text-akn`), e allegato legacy
  (`attachment-just-text`, usato dai CODICI veri: c.c./c.p./c.p.c./c.p.p.,
  TULPS). Il parser li gestisce tutti.
- Delimitare `class="bodyTesto"` **per indici**, non con regex non-greedy
  (si ferma al primo `</div>` annidato e **tronca** l'articolo).
- Il corpo è **tutto il resto** dopo numero/rubrica: iterare sui singoli
  `art-comma-div-akn` perde i commi 2..N (art. 186 CdS: 20 commi → 1).
- **Max 1-2 flussi paralleli**: 3 fanno scattare il rate limiting (centinaia
  di GET fallite). `_get` ha 5 retry a backoff + riapertura sessione.
- Eseguire l'ingest **sull'host, non nel container** (un deploy lo ucciderebbe);
  l'output va nel volume `data/processed/it_acts/`.
- Se tutti gli articoli di un atto restituiscono lo stesso testo
  "PROVVEDIMENTO ABROGATO", l'atto è abrogato → cercare il sostitutivo
  (è successo col TUIR: DPR 917/1986 → D.Lgs 117/2026).
- Nel QA, "articolo precedente" nel testo è **linguaggio normativo
  legittimo**, non navigazione: falso positivo.

**Per aggiungere altri codici**: una riga nella lista `ACTS` di
`tools/ingest_it_normattiva.py` (id, titolo, area, URN NIR, wave), poi
`ingest` → `build_it_index` → deploy. Le sigle per il verificatore di
citazioni si aggiungono in `_IT_CODE_CHECKS` (`src/citation_verifier.py`,
ordine longest-first: `ccii` prima di `cc`, `cpa`/`cpi` prima di `cp`) e
l'etichetta badge in `CODE_LABELS`.

## Implementazione attiva (V9.0.3 + V9.1)

Tre layer di protezione contro doctrine drift:

1. **Prompt guard** — `KUFI JURIDIKSIONAL` in `ALBANIAN_LANGUAGE_RULES`
   (`src/brain.py`), propagato a tutti i 17 system prompt;
   `GENIO_JURISDICTION_GUARD` in `src/genio.py` prepended alle 6 lenti
   parallele del Genio Legale.
2. **Retrieval grounding** — `src/parser.py` ricostruisce le rubriche
   multi-line fino a fine-frase (cap 8 righe / 25 char min). Pre-V9.1
   il troncamento a `lines[0]` avvelenava BM25 e il modello compensava
   con doctrine training-set continentale. Test di regressione:
   `tests/test_parser_headings.py`.
3. **Citation Shield V8.11** — refusal mode <50% conf, provenance pack
   JSON+DOCX. Se il retrieval fallisce, il modello rifiuta invece di
   hallucinare.

4. **Ancore — la regola generale non perde contro le eccezioni (v9.187)**
   — `brain.ANCORE_AL` + `_applica_ancore`. **Misurato**: alla domanda più
   banale sul parashkrim, il **Neni 114 KC** — *la* regola generale — non
   entrava nei primi dodici con **nessuna** delle formulazioni normali. Sopra
   di lui il parashkrim doganale e le eccezioni, perché BM25 premia chi ripete
   le parole della domanda e la regola generale le dice con parole sue
   («parashkruhen brenda dhjetë vjetëve», non «afati i parashkrimit»). Il suo
   punteggio BM25 per quella domanda è **zero**: nessuna parola in comune.
   Il cervello se n'era accorto e lo scriveva all'avvocato («neni 114 nuk
   figuronte…»), rispondendo giusto **dalla sua preparazione** — cioè senza
   grounding, che è l'opposto della promessa del prodotto.
   Un'ancora è un articolo che entra per **ragione giuridica**, non lessicale.
   Stessa idea del safety-net sui codici procedurali, un livello più in giù.
   Quattro regole:
   * **si aggiunge, non sostituisce** — se BM25 l'aveva già trovato, nulla cambia;
   * **entra PRIMA del taglio** a `TOP_K_ARTICLES` — è in fondo per punteggio,
     è il motivo per cui esiste;
   * **si dichiara al cervello** (`⚑ RREGULL E PËRGJITHSHME`) invece di mostrare
     un `score=0.00` che lo farebbe scartare. Marcata su una **copia**
     (`copy.copy`), mai sull'oggetto dell'indice: sei richieste girano insieme
     e l'ancora di un avvocato non deve comparire nel blocco di un altro;
   * **escludere conta più che includere** — la prescrizione civile dentro una
     domanda penale è un anti-consiglio: l'ancora non scatta se il triage ha
     visto materia penale.
   Solo AL: sul corpus italiano l'art. 2946 c.c. esce già secondo, e un'ancora
   inutile toglie il posto a un risultato vero. **Si ancora ciò che si è
   misurato rotto**, non per simmetria. Sorvegliata dal set aureo (sezioni
   [4] e [5], 6 check: scatta / scatta senza `areas` / NON scatta sul penale /
   NON scatta fuori tema / esiste / l'italiano esce da solo).
   Verificato in produzione: `retrieval: ancorati kodi_civil 114` → risposta
   corretta in **44 secondi** citando il neni, contro 22 minuti e una nota di
   scusa prima.

5. **Giurisdizione al collo di bottiglia (v9.155)** — il vincolo di
   giurisdizione si applica dentro `backends.complete()` /
   `complete_stream()`, da cui passa OGNI chiamata al cervello.
   `brain.apply_jurisdiction` è **idempotente**, quindi chi la applica già a
   monte non ottiene il vincolo due volte. Guardia: `tools/juris_guard.py`.

Quando aggiungi un nuovo system prompt fuori `brain.py`/`genio.py`,
attaccaci esplicitamente il guard — non confidare che basti
`ALBANIAN_LANGUAGE_RULES`.

### GOTCHA storico: "in sessione IT risponde in albanese"

Costato tre giri di correzioni giuste ma inefficaci. **Due cause distinte:**

1. **Il contesto arrivava vuoto.** Il `@app.before_request` che armava la
   giurisdizione girava PRIMA che `login_required_api` impostasse
   `request.user` → leggeva `None` → default AL per **tutti** gli strumenti
   con endpoint separato. `/api/ask` si salvava perché il brain prende la
   giurisdizione dal **caso**, non dalla richiesta. Fix:
   `auth._arm_request_jurisdiction(user)` chiamata subito dopo
   `request.user = user` (in `login_required_api` **e** `login_required_page`);
   il `before_request` resta solo come reset ad AL.
2. **41 chiamate al cervello non applicavano il vincolo**, sparse in 15
   moduli (notary 12, web 15, intake, afati, secretary, vigilanza…). Fix
   strutturale: il collo di bottiglia sopra, invece di 41 rattoppi.

**Metodo che l'ha risolto**: smettere di rincorrere gli screenshot e
**misurare tutti i punti d'ingresso insieme** (`tools/audit_tools_it.py`):
da 1/14 strumenti corretti a **14/14**.

## Comandi rapidi

```bash
# avvio dev
./venv/bin/python -m src.web

# re-build KB (dopo aver toccato parser o aggiunto fonti)
./venv/bin/python -m src.parser
./venv/bin/python -m src.jurisprudence_parser
./venv/bin/python -m src.retrieval --build
./venv/bin/python -m src.retrieval --build-decisions

# test
./venv/bin/python -m pytest tests/

# snapshot (mini-git numerato)
./scripts/snapshot.py commit -m "..."
./scripts/snapshot.py list
```

## Modelli — cosa gira davvero (verificato 30 ago 2026)

Sorgente di verità: `/opt/super-avvocato.env`, letto da `config.py`.
- **`CLAUDE_CODE_MODEL=claude-opus-5`** + **`CLAUDE_CODE_EFFORT=max`** — il cervello;
- `CLAUDE_CODE_MEDIUM_MODEL` / `FAST_MODEL` = **`claude-sonnet-5`** — fasi ausiliarie;
- **Fable**: `model_override="fable"` va dritto al CLI come `--model fable`.
  **Verificato chiedendo al modello il proprio identificativo: risponde
  `claude-fable-5`.** E l'effort si applica anche a lui — `backends.py` fa
  `if not fast and self.effort`, senza escludere `model_override` (un bug
  precedente lo escludeva e Fable rispondeva senza ragionamento esteso).

**✅ Opus 5 su tutti i cervelli (30 ago 2026).** Bolla + Super Consulente
(AALA), Nabuel e l'OwnerAssistant del Taxi ora sono ancorati a `claude-opus-5`
come Super Avokati. **Il modello era scritto nel CODICE, non solo nell'env** —
un controllo sull'ambiente diceva «non fissato» e ingannava. Cambiati env
**e** fallback nel sorgente: se resta indietro il fallback, alla prima perdita
di un `.env` il prodotto torna al modello vecchio in silenzio. Per il Taxi
toccato anche `dist/` (è quello che gira; `src/` è quello che sopravvive al
prossimo build).
**Costo misurato**: Opus 5 impiega 17-19s contro i 7s di Opus 4.8; la Bolla ha
un timeout di 45s e ripiega su risposte a regole se scade. Provato dopo il
cambio: Bolla 10-14s, Nabuel 9-19s, sempre col modello. Se un giorno la Bolla
risponde con frasi generiche, guardare quel timeout per primo.

**GOTCHA**: esistono DUE costanti che sembrano la stessa cosa.
`CLAUDE_CODE_MODEL` (backend CLI, quello in uso) e `CLAUDE_MODEL` (backend API
diretta). La seconda era ferma a `claude-opus-4-8` e finiva nel **provenance
pack** — il documento che certifica come è stata prodotta una risposta:
dichiarava opus-4-8 mentre rispondeva opus-5. Ora `CLAUDE_MODEL` segue
`CLAUDE_CODE_MODEL`. Sorvegliato dal golden, sezione [9].

## Tier di backend

- **Opus 4.8** (default per Super Avvocato) — profondità > velocità,
  thinking max. È il cervello del ragionamento legale.
- **Sonnet 4.6** (`medium=True` e `fast=True`) — tutto il resto:
  intake, jargon plain, contract review iniziale, scaffolding.
- **Haiku rimosso**: in uno strumento legale non vogliamo modelli
  "piccoli". Solo Opus (risposta) + Sonnet (resto).

## Lingua

- Risposte all'utente: **shqip in sessione AL, italiano in sessione IT**
  (il preambolo di giurisdizione impone la lingua al cervello).
- Conversazione con Romeo: italiano informale ("fratello").

### UI bilingue (i18n) — come funziona

`body[data-lang]` vale `it` quando la giurisdizione attiva è IT. In `app.js`:
- `UI_LANG` letto da `data-lang`; `I18N_IT` + `applyStaticI18n(root)` traducono
  gli elementi con `data-i18n` / `data-i18n-ph` (layer statico, anche dentro i
  modali creati a runtime: chiamare `applyStaticI18n(ov)` dopo l'append).
- `T_IT` + `t(sq)` traducono le stringhe generate a runtime (match esatto);
  `tMode(sq)` traduce i titoli con emoji (match a sottostringa + fallback
  emoji+testo sul dizionario).
- **TRAPPOLA**: dentro callback il cui parametro si chiama `t` (template, type,
  trigger) la funzione `t()` è mascherata → usare l'alias **`TT(...)`**.
  Ha già rotto la griglia perizie e 3 dropdown (fix v9.130).
- **TRAPPOLA**: `initModeBar()` gira a inizio file, PRIMA che `UI_LANG` sia
  assegnato → va ri-chiamato dopo `applyStaticI18n()`, altrimenti la mode-bar
  resta albanese (fix v9.131).
- **⚠️ DUE difetti diversi, e vanno cercati tutti e due** (audit 30 ago 2026):
  1. l'elemento ha `data-i18n="x"` ma `x` **non è nel dizionario** → resta
     l'albanese scritto nell'HTML. Ne è stato trovato **uno solo**: `dosja`;
  2. testo albanese **senza nessun `data-i18n`** → non verrà mai tradotto, e
     nessuno se ne accorge finché un avvocato italiano non ci finisce sopra.
     Ne sono stati trovati **72**, quasi tutte le voci del menu PRO con la loro
     descrizione. **Cercare solo il primo tipo dà «tutto a posto» mentre il
     difetto è in piena vista.**
  Lo script di audit sta in `scratchpad/audit_italiano.py` (confronta le chiavi
  `data-i18n` usate nell'HTML con quelle del dizionario, e cerca testo albanese
  senza attributo). **GOTCHA dell'audit**: le chiavi di `I18N_IT` sono **non
  quotate** (`sidebar_aria: "..."`), quindi un regex che le cerca fra virgolette
  trova zero chiavi e dichiara «tutto non tradotto».
  Il marchio **«SUPER AVOKATI» non si traduce** in nessuna lingua.

  ### ⚠️⚠️ COME SI MISURA LA TRADUZIONE — e come NON si misura (1 set 2026)

  Cercando «alcune frasi in albanese» ho prodotto **tre audit statici** che
  hanno detto, in fila: «16 mancanti», «187», «181». **Tutti e tre falsi.**
  Due ragioni strutturali, e vanno sapute prima di scrivere il quarto:

  1. **`T_IT` viene ESTESO otto volte** con `Object.assign(T_IT, {…})` più
     avanti nel file. Chi lo legge in un punto solo conta una frazione delle
     chiavi e conclude che manchi tutto.
  2. **Le stringhe passate a `t()` sono spesso solo il testo predefinito**, che
     `applyStaticI18n` sostituisce un istante dopo tramite `data-i18n`.
     Contare le chiamate a `t()` non misura **niente**.

  A queste si aggiungono i due errori di regex già noti (chiavi non quotate,
  **più chiavi sulla stessa riga**) — che mi hanno morso di nuovo.

  **L'unica misura vera: aprire i pannelli in sessione italiana e leggere.**
  Fatto su venti pannelli: diciotto giusti, due sbagliati.

  ### ⚠️ La traduzione spaccava una parola: «Pyet Avvocatoin e Djallit»

  `tMode()`, quando non trova la traduzione esatta, sostituisce una
  **sottostringa** dalla tabella `MODEBAR_TXT`. La coppia
  `["Avokat", "Avvocato"]` colpiva **dentro** «Avokat*in*» e produceva
  **«Pyet Avvocatoin e Djallit»** — né albanese né italiano, sul titolo del
  pannello più caratteristico del prodotto. Nessuna analisi del testo l'avrebbe
  trovato: solo aprire il pannello.

  **La correzione non è la traduzione, è la causa**: la sostituzione avviene ora
  solo su **confine di parola** (`(^|[^\wëçËÇ])… (?![\wëçËÇ])`). Aggiunte anche
  le due traduzioni esatte (`"😈 Pyet Avokatin e Djallit"`, `"Dosja"`), perché
  una traduzione scritta è sempre meglio di una sostituzione automatica.
  ⚠️ `tMode` esce subito se `UI_LANG !== "it"`: in sessione albanese è inerte,
  quindi la modifica non poteva romperla.

  **E una lezione sulle guardie**: ne ho scritte due «intelligenti» che
  rifacevano `tMode` per verificare i titoli. La prima segnalava «Super Noteri»
  come rotto (**falso** — la tabella prova prima le voci più lunghe), la seconda
  si è inventata una stringa combinando male i blocchi del dizionario. Il golden
  sezione [16] sorveglia ora **la causa** — una riga sola che non si può
  fraintendere — più due regressioni. **Una guardia che grida al lupo è peggio
  di nessuna guardia: insegna a ignorare il QA.**
- Le etichette che arrivano dalle API (tipi atto, poteri procura, template
  perizia, clausole obbligatorie…) passano da `t()` con una mappa AL→IT nel
  dizionario (~340 voci).

---

# PRODUZIONE — VPS, DEPLOY, BUILD  (aggiornato 7 ago 2026, v9.82)

Numeri attuali: **6061 nene · 21 codici · 1402 precedenti** (pickle vivo). Corpus cresciuto da 5615 (18 codici) aggiungendo: Kodi Civil +2, Familjes +4, Konsumatorët +3, Ligji Policia 108/2014 (135), Rregullore Policia VKM 750/2015 (255), Ligj Policia 82/2024 (143, ATTUALE). Dedup Zgjedhor -96.

## Dove gira
- **VPS**: `root@31.220.90.246` (SSH dal Mac senza password). App in `/var/www/apps/super-avvocato`.
- **Container Docker** `super-avvocato`, image `super-avvocato:vX.Y` (attuale **v9.82**). Flask su `127.0.0.1:5050`; nginx `superavokati.ai` → 5050.
- **Volumi**: `-v /var/www/apps/super-avvocato/data:/app/data` (SQLite `app.db` + BM25 `index/bm25.pkl` — PERSISTONO tra recreate); `-v /opt/claude-creds:/home/avvocato/.claude` (credenziali del backend).
- **Cervello**: backend = **`claude` CLI headless** in subprocess (`src/backends.py`), name interno "Tetramorph". Opus 4.8 effort=max default; `medium=True`→Sonnet; `fast=True`→Sonnet senza web. **Il backend Opus (non-fast) ha WebSearch/WebFetch ABILITATI** (`backends.py:280`) — usato da Ligj i gjallë per il check legge live. `BRAIN_PARALLEL_WORKERS=6` (fasi in parallelo).

## Deploy / build (procedura usata ~25 volte)
**Deployare SEMPRE con `./run.sh`**, non con un `docker run` a mano: lo
script monta anche `-v /opt/claude-creds:/home/avvocato/.claude` e ripristina
`.claude.json`. Un deploy manuale che dimentica quel volume lascia il
container in piedi e apparentemente sano. E se `run.sh` resta indietro di
versione, chi lo lancia **riporta l'app a un'immagine vecchia**: aggiornarlo
sempre insieme al build.

```bash
cd /var/www/apps/super-avvocato
docker build -q -t super-avvocato:vNEW .
sed -i 's/super-avvocato:vOLD/super-avvocato:vNEW/' run.sh
./run.sh
# health-check:
for i in 1 2 3 4 5 6; do docker inspect -f '{{.State.Health.Status}}' super-avvocato; sleep 4; done  # atteso: healthy
curl -s -o /dev/null -w '%{http_code}' https://superavokati.ai/   # atteso: 200
```
Dockerfile COPY: `data/ src/ static/ templates/ scripts/ tools/`. Dopo un cambio env (NEXT_PUBLIC inlined) serve rebuild — qui NON applicabile (Flask), ma per gli altri servizi sì.

## Precedenti — cosa entra e cosa NON deve entrare (29 ago 2026)

**1.258 → 1.407** (Kushtetuese 445 · **Gjykata e Lartë 538** · CEDU 424).
Aggiunte 149 decisioni della Gjykata e Lartë scaricate dall'archivio ufficiale
(`panel.gjykataelarte.gov.al/graphql`, Strapi pubblico, campo `files`).

**⚠️ MAI chiamare `build_and_save_decisions()`** per aggiungere: ricostruisce da
zero leggendo Postgres `legalkb`, che **dal container non è raggiungibile** —
sparirebbero gli 813 precedenti (Gjykata e Lartë + CEDU) che oggi vivono solo
nel pickle, e senza un errore. Si fa come per gli articoli: `DecisionIndex.load()`
→ append → `DecisionIndex.build(tutte).save()` → `chown 1000:1000` → restart.

**Regola permanente (utente, 29 ago 2026): entra SOLO ciò che migliora.**
Su 437 decisioni scaricate ne sono entrate 144. Tenute fuori di proposito:
- **mospranim / inammissibilità** — non decidono il merito; come precedente
  valgono zero e il recupero, che va per parole, le citerebbe come autorità;
- documenti che **non sono decisioni** (leggi, elenchi candidati, relazioni);
- quelle **già presenti**.

**Il rischio più grave, e come è chiuso**: in 74 di queste la Cassazione ha
**annullato** (`prishje`) la decisione di sotto. Dentro il documento c'è per
esteso il ragionamento di quel grado — che è diritto dichiarato sbagliato.
Si indicizza **solo dal marcatore «Kolegji vlerëson»** (presente nel 96%) fino a
«PËR KËTO ARSYE»: quello è il ragionamento della Cassazione, mai quello cassato.
L'esito letterale sta in `dispositif` fra parentesi quadre (`[prishje + kthim]`,
`[lënia në fuqi]`) e `outcome` resta nel vocabolario esistente
(pranim/rrëzim/pushim/pjesërisht/kthim për rishqyrtim/ndryshim) perché il
modello veda un solo lessico.

**GOTCHA della chiave anti-duplicati**: il controllo «c'è già?» deve essere
`(corte, anno, numero)`. Senza la corte, la Kushtetuese n. 68/2025 blocca la
Gjykata e Lartë 00-2025-68, che è tutt'altra decisione — 5 vendime veri esclusi
così. E la normalizzazione deve reggere DUE formati: i precedenti vecchi hanno
`number="42"`, quelli nuovi `number="00-2025-68"` (togliendo i non-numeri
diventa "00202568" e NIENTE combacia più → si duplicherebbe tutto).
Conseguenza concreta e misurata: uno dei 5 esclusi è proprio il vendim che il
cervello ha poi **citato in una risposta senza averlo nel corpus**,
ricostruendolo dalla propria preparazione. L'esclusione sbagliata crea la
condizione per una citazione non fondata.

**✅ CHIUSO (v9.188) — `src/case_citation_verifier.py`, il Verifikuesi i vendimeve.**
`citation_verifier` guarda i **nene**; questo guarda i **numeri di sentenza**,
che prima nessuno controllava: una risposta di prova citava `00-2025-1760`, che
non esiste in nessun documento nostro, e passava perché i nene erano tutti buoni.
Riconosce due formati (`00-ANNO-N` della Gjykata e Lartë; `Vendim nr. N, datë …`
della Kushtetuese) e su quella stessa risposta trova **7 citazioni**, non le 4
che avevo visto a mano.

**⚠️ LA DIFFERENZA DA NON SBAGLIARE MAI**: per i nene il corpus è completo,
quindi «non c'è» = `fake` è onesto. Per le sentenze **no**: ne abbiamo 1.407 su
molte di più pubblicate, quindi «non lo trovo» vuol dire solo
**`unverified` — controllala**. Marchiare come falso un precedente vero farebbe
buttare all'avvocato una carta buona: è un danno grande quanto lasciar passare
un numero inventato. Per questo **non rifiuta e non censura mai**, avvisa.
Quando invece lo trova, mostra anche **come è finito** (`outcome` + dispositivo).

**⚠️ DUE agganci, non uno.** `_scudo_citazioni` copre i **19 strumenti**
(Fable, notaio, procuratore…). Ma la **chat** — la risposta del cervello, il
percorso più usato — ha una **copia sua** dello scudo (in `_ask_prepare`, con
provenance pack e refusal) e NON passa di lì. Avevo agganciato solo il primo e
dichiarato «copre tutti i percorsi»: falso, e l'ha scoperto la prova viva —
13 citazioni di sentenze, **7 non confermabili, e nel testo nessun avviso**.
Ora l'aggancio è in tutti e due (v9.191). Un golden strutturale conta gli
agganci nel sorgente, perché nessun test funzionale vede *dove* è attaccata una
protezione. Non chiama il modello (calcolo sul testo già
prodotto) e non solleva mai. L'avviso si **attacca al markdown**, perché il
badge resta sullo schermo mentre la risposta viene copiata dentro una memoria.
Sorvegliato dal golden, sezione [7].

## Lettere dentro il nene: «432/c» NON è un fantasma (v9.189-9.190)

Su una domanda vera di giurisprudenza il cervello ha citato **`neni 432/c KPP`**
— la lettera c) dell'art. 432, *«shkelje procedurale që kanë ndikuar në dhënien
e vendimit»*: il motivo di ricorso esatto. Lo scudo l'ha marcato **fake** e
all'avvocato è comparso **«2 nene fantazmë» su una citazione giusta e decisiva**.

**Due cose si scrivono uguale e non lo sono:**
- `149/a` = **articolo inserito a sé** (esiste nel corpus come articolo);
- `432/c` = **comma dentro** l'art. 432 (il corpo elenca «a) … b) … c) …»).

La regola diceva «un suffisso-lettera è sempre un articolo distinto, mai
collassarlo» — vera per il primo caso, falsa per il secondo.

**Come si distinguono senza indovinare**: `_lettera_e_un_koma()` guarda se quel
comma è **davvero scritto** nel corpo dell'articolo base. Se c'è → citazione
valida. Se non c'è → resta fake. Così `neni 432/z` continua a cadere.
Aggiunto anche il livello triplo: `149/a/2` prova `149/a` prima di arrendersi.

**⚠️ GOTCHA che ha reso la prima correzione inutile**: vanno riparate **due
strade**. `_verify_number` (quando il codice è scritto: «neni 432/c i KPP») e
`_codes_for_number` (quando NON lo è: «neni 432/c», come si scrive davvero fra
giuristi). La prima correzione passava i test e falliva sul caso reale, perché
i test scrivevano il codice per esteso e il cervello no. **Una prova che non
somiglia al caso vero dà una sicurezza falsa** — il golden ora ha entrambe le
forme (sezione [8], 10 check, metà dei quali verificano che le lettere
inventate CADANO ancora).

Effetto misurato sulla stessa risposta: `fake 2 → 0`, `verified 6 → 7`.

**GOTCHA costato una correzione doppia**: per sapere **come è finita** una
decisione si guarda il **dispositivo**, MAI l'intestazione — «mospranim» sta in
fondo, dopo trenta pagine, e 5 inammissibilità sono passate col filtro sui primi
8.000 caratteri (le ha trovate il golden check, non io). Ma non si guarda nemmeno
il *ragionamento*: una decisione che **discute** l'inammissibilità di un grado
inferiore ha comunque deciso nel merito — cercando lì avevo tolto 13 precedenti
invece di 5, di cui 8 validi. **Solo il dispositivo dice cosa è stato deciso.**

Sorveglianza: `golden_check.py` sezione [6], 6 check di cui **5 sorvegliano un
danno** (nessuna inammissibilità · le tre corti ancora presenti · il ragionamento
parte dal marcatore del Kolegji · l'esito sempre dichiarato · una annullata non
può risultare confermata).

## Fix corpus (GOTCHA importante)
I fix agli articoli vivono nel **PICKLE `data/index/bm25.pkl`** (volume montato), NON nel sorgente. Per aggiungere/correggere articoli: script python che fa `ArticleIndex.load()` → append `Article(...)` → `ArticleIndex.build(arts).save()` → `chown 1000:1000 data/index/bm25.pkl` → `docker restart super-avvocato`. Un re-parse da zero PERDE questi fix. Article ha campi: code, title_sq, area, number, heading, body, pjesa, kreu, seksioni, repealed, volatility (STABLE/MEDIUM), last_amendment_date.

## nginx: limite di caricamento (GOTCHA GRAVE)

`client_max_body_size 30m` nel blocco server di superavokati.ai (**entrambi**,
:80 e :443). Il predefinito di nginx e' **1 MB**: qualunque allegato piu'
grande — uno screenshot lo supera facilmente — veniva respinto con un **413 in
HTML**, che il client provava a leggere come JSON e mostrava all'avvocato
`Unexpected token '<'`. L'app dichiara 25 MB, ma nginx si fermava molto prima.
I test con file piccoli (17 KB) **non lo intercettano**: provare sempre con
un file oltre 1 MB.

**ATTENZIONE ai backup in `sites-enabled/`**: nginx carica *tutti* i file di
quella cartella. Un `cp config config.bak` fatto li' dentro crea un secondo
blocco per lo stesso `server_name` e nginx usa il primo che trova — la
modifica sembra non avere effetto. I backup vanno in `sites-available/`.

Gli altri siti (aala.global, crm, auto, taxi) sono **ancora al predefinito di
1 MB**: se un giorno caricano allegati, avranno lo stesso difetto.

## Cache dell'HTML (GOTCHA GRAVE)

`web._no_cache_html` manda `Cache-Control: no-store` su ogni risposta HTML e
`immutable` sugli static con `?v=`. **Senza, il cache-busting non serve a
nulla**: e' l'HTML a dire quale `app.js?v=N` caricare, e se il browser
trattiene l'HTML vecchio continua a chiedere la versione vecchia. Scoperto
guardando la pagina viva dell'utente: caricava `app.js?v=100` mentre il
server serviva `?v=103` — girava con l'interfaccia di tre release prima e
nessuna correzione UI lo raggiungeva. Se un utente segnala un bug gia'
corretto, **prima cosa: verificare quale `?v=` sta caricando**.

## Caricamento documenti — asincrono

Il POST crea la riga (`status='pending'`) e **ritorna subito**; estrazione,
OCR e classificazione girano in un thread. Prima la richiesta restava aperta
30-65s PER FILE (quattro pagine fotografate = oltre 4 minuti) e l'avvocato
concludeva che il caricamento non funzionasse. Misurato: **160s → 0,4s** per
comparire, analisi completa in ~20s in sottofondo. Il client ripolla ogni 4s
(`_pollDossier`) finche' restano `pending`.
**Due trappole**: la giurisdizione vive in una `threading.local` e va passata
a mano al thread, altrimenti classifica in albanese un documento italiano; e
la lingua va ripetuta **nel messaggio utente** (`documents._LANG_LINE`), non
solo nel preambolo — il tier veloce non ragiona a lungo e si ancora al prompt
di sistema albanese (misurato: 1 documento su 3 sbagliato).

## Allegati — UI

`_readFilesInto(input, ta, statusEl, runBtn)` è l'UNICO gestore di allegati
(app.js): legge **tutti** i file scelti, li accoda con il nome come
intestazione e imposta `multiple` da sé, così il markup dei singoli strumenti
non va toccato. Prima dieci strumenti ripetevano lo stesso codice a file
singolo e un documento fotografato in 4 pagine andava caricato riaprendo la
galleria ogni volta. **Usa `TT()` e non `t()`**: diversi di quei blocchi
vivono in callback con parametro `t` (es. `t.key` nelle perizie).

Il `case_id` viaggia con ogni strumento: `_openTetramorphTool` lo aggiunge al
payload per tutti e 19 i suoi strumenti in un punto solo, più 5 pannelli
autonomi (drafter, perizie, notaio-bozza, atto d'indagine, scadenze).

## Allegati (GOTCHA)

`ALLOWED_UPLOAD_EXTENSIONS` (config.py) e `documents.extract_text` sono **due
liste separate**: ammettere un'estensione senza aggiungere il ramo che la
legge fa tornare testo **vuoto senza errore**, e l'allegato sparisce in
silenzio. Successo due volte (.docx, poi .heic). Un lettore che fallisce ora
**solleva** invece di restituire "": meglio un errore visibile che un
documento apparentemente caricato e vuoto.

**Foto iPhone**: le foto sono **HEIC**, che il cervello non sa leggere e che
il selettore mostrava grigie. Ora sono ammesse e `_to_jpeg()` le converte
(via `pillow-heif`) prima dell'OCR — stesso trattamento per i TIFF degli
scanner. Gli screenshot PNG funzionavano gia'. Formati letti: PDF (pdfplumber + OCR di riserva), immagini (vision
OCR), e via `extract/readers.py` docx (python-docx), doc (**antiword**, nel
Dockerfile), txt/rtf/html. Guardia: `smoke_test` verifica che ogni estensione
ammessa produca davvero testo.

## Patch UTF-8 (GOTCHA)
Le patch a file con ë/ç/emoji: SEMPRE via file `.py` scp'd sul VPS (`scp patch.py root@…:/tmp/ && python3 /tmp/patch.py`), MAI heredoc SSH inline (mangia UTF-8/`\n`). Anchor precisi + `assert old in s and s.count(old)==1`.

## QA — rete di sicurezza (lanciare dopo ogni build)

Dal 28 ago 2026 conviene aggiungere, oltre a golden+smoke+juris_guard, una
**prova viva** su due domande vere (una AL, una IT) passando dal percorso
nuovo `start` + `events`: i test dicono che gli strumenti si chiamano senza
errori, non che le risposte sono ancora giuste. Riferimento verificato il
28 ago: prescrizione ordinaria → **10 vjet** (AL) e **art. 2946 c.c.** (IT),
12 articoli recuperati per ciascuna.

```bash
docker exec super-avvocato python3 tools/golden_check.py   # check deterministici: corpus + Verifikuar + heading-scan + ancore + precedenti + vendime + shkronja + documenti legali. Baseline **98/98** (31 ago).
docker exec super-avvocato python3 tools/smoke_test.py     # 103 tool chiamati con cervello STUBBATO (no LLM): firma/parsing/logica. Baseline 103/103.
docker exec super-avvocato python3 tools/juris_guard.py    # 16 check strutturali sulla giurisdizione. Baseline 16/16.
```
Estendere GOLDENS/smoke quando emerge un bug nuovo.

**Con il cervello vero** (lento, ~40 min, ma è l'unico che vede la lingua
delle risposte): `tools/audit_tools_it.py` chiama i 14 strumenti in sessione
IT e per ciascuno conta albanese / diritto AL / diritto IT. Baseline **14/14**.
Da rilanciare dopo ogni modifica alla giurisdizione.

## Chi decide il tempo di una risposta (misurato 30 ago 2026)

**`nullity_radar` è una fase del cervello della CHAT, non del Genio.** Non si
toccano:
- **chat, percorso `complex`** → 9-11 fasi «war room» (`_run_stages` in
  `brain.py`): strategic · timeline · comparison · missing_facts · premortem ·
  distinguishing · evidence_map · **nullity_radar** · contradictions (+ opponent
  e leverage se `_has_adversary`);
- **Genio** → 6 lenti sue (riframing, kill_shot, leverage, decision_tree,
  brutal_truth, voice). `nullity_radar` lì non entra mai.

Scatta **solo** se il triage dice `complex`: una domanda semplice prende il
fast-path (misurato **44 s** sul parashkrim), una complessa 28-65 min.
**La variabilità è del modello**: stessa domanda, stesso indice, due giri con
`nullity_radar` a **810s** e **2353s**.

**⚠️ NON sono i precedenti a rallentare** — domanda che torna spesso, misurata:
una ricerca su 1.407 precedenti costa **7-13 ms**, l'indice si carica in 0,67 s
una volta sola, e al modello ne arrivano **4** (numero fisso: il testo che legge
è identico con 1.258 o 1.407). La ricerca costa ~200.000 volte meno della fase
lenta, e le due prove avevano lo **stesso** indice. Toglierli non guadagna un
secondo e fa tornare «non confermabili» 4 delle 6 sentenze citate.

Se un giorno serve accorciare: la leva è un tetto su `nullity_radar` — ma è la
lente che cerca pavlefshmëri e afate, cioè le leve procedurali che vincono senza
entrare nel merito. L'alternativa già pronta è il background + notifica.

# UTENTE MULTI-MODULO E PASSWORD CONFERMATA (v9.231-9.233, 1 set 2026)

Il form «Krijo përdorues të ri» aveva un **menu a tendina** con una sola
professione: il cliente **3-in-1** — quello che paga di più — andava creato e
poi corretto dal pannello ⚙️. Due passaggi per il cliente migliore, e un
passaggio che prima o poi qualcuno si dimentica.

⚠️ **Il server era già pronto.** `POST /api/admin/users` accetta
`modules: [...]` e ripiega sulla professione singola solo se manca. **Non ho
toccato una riga di server**: era l'interfaccia a impoverire una cosa che
funzionava già. Vale la pena guardare sempre, prima di costruire.

Ora: **tre caselle** (Avvocato · Procuratore · Notaio, la prima spuntata),
`profession` = la prima scelta (serve alla mode-bar), `modules` = la lista.

**La password si scrive due volte, con l'occhio per vederla.** Un errore di
battitura creava un utente che non riesce a entrare, e non se ne accorgeva
nessuno finché il cliente non provava. Se non coincidono, **non si crea** —
verificato dal browser: l'utente con le due password diverse non esiste in
banca dati.

⚠️ **Trappola dell'emoji**: `it_48` vale `"⚖️ Avvocato"`, emoji **inclusa**.
Mettendo l'emoji fuori dallo span tradotto, in italiano ne comparivano **due** —
e in albanese no, perché lì resta il testo dell'HTML. Un difetto visibile in
una lingua sola. L'emoji va **dentro** lo span.

⚠️ **Trovati creando davvero un utente dal browser** (non leggendo il codice):
- il distintivo **«3-in-1» stava sull'essere amministratore**, non sui moduli
  pagati. Un cliente con tre moduli **non lo vedeva**, un amministratore con un
  modulo solo sì. Rapporto rovesciato: amministratore è un **permesso**, non un
  abbonamento. Ora il distintivo racconta **cosa paga** — e c'è anche un
  **«2-in-1»**, perché chi paga due moduli finora era indistinguibile da chi ne
  paga uno.
- il messaggio di conferma era **in albanese** anche in sessione italiana
  (`✓ U krijua 'prima'`), ed è l'ultima cosa che l'avvocato legge dopo aver
  creato un cliente. Ora dice anche **quanti moduli**.

**Il pannello ⚙️ resta com'è** e serve ancora: è lì che si cambiano i moduli
**dopo** (un cliente che aggiunge il notaio a metà abbonamento), insieme a
giurisdizione e durata dell'abbonamento.

Sorveglianza: golden sezione [17], 8 check (tre caselle e non un menu, la
lista inviata, almeno un modulo, la seconda password, il blocco se non
coincidono, l'occhio, e l'emoji dentro lo span). **196/196.**

# IL TELEFONO CHE CADE — parcheggio delle risposte (v9.227-9.228, 31 ago 2026)

**Il difetto, vecchio e mai visto.** I **venti strumenti PRO** — compresi
«Avokati i Djallit» (`/api/devil-consult`) e «Kundërshtari» (`/api/adversary`)
— chiamavano il server con una `fetch` normale che tiene aperta la richiesta
HTTP per **tutti i minuti** dell'analisi. Sul telefono basta passare a WhatsApp:
il sistema sospende la scheda, la connessione cade, e al ritorno compare
«Gabim rrjeti».

⚠️ **E la parte peggiore non si vedeva: il server aveva finito il lavoro.**
Flask esegue la funzione fino in fondo anche se il client se n'è andato — è solo
la scrittura finale che fallisce. Il cervello ragionava dieci minuti, la
risposta esisteva, e **nessuno la raccoglieva**.

Era lo stesso difetto già riparato per la **chat** (v9.170) e per il **Genio**
(v9.183). Per gli strumenti PRO no, e sono venti.

## Il rimedio, in un punto solo

Non venti endpoint riscritti: **un `after_request`** che, quando la richiesta
porta l'intestazione `X-Job-Key`, **parcheggia** la risposta prima di provare a
scriverla. Se la scrittura fallisce, il risultato è già al sicuro e il client se
lo riprende con `GET /api/tool/result?key=…`. Lato client basta toccare
`_openTetramorphTool`, che è il punto da cui passano **tutti e venti**.

**Due casi, e servono entrambi:**
1. **scheda sospesa e ripresa** → la pagina è viva, la `fetch` è morta: si
   ripesca con la chiave che si ha in mano;
2. **scheda UCCISA** (Android libera memoria, la pagina riparte da zero) → la
   chiave in memoria è persa, per questo si scrive anche in **`localStorage`** e
   all'avvio si controlla se c'è un lavoro in sospeso. È il caso che succede
   davvero su un telefono con poca memoria, ed è il peggiore: l'avvocato torna e
   non trova **niente**, nemmeno l'errore. La risposta recuperata si mostra in
   un pannello suo, perché la finestra da cui era partita non c'è più.

⚠️ **Legato all'utente**: la chiave è un UUID, ma il parcheggio è comunque
vincolato a chi ha fatto la richiesta — verificato: proprietario `200`, altro
studio `202` (come se non esistesse), senza sessione `401`.
⚠️ **Vive in memoria**, come il registro dei lavori: un deploy lo svuota. Tetto
200 voci, scadenza 40 minuti.

**Verificato sul campo**: connessione tagliata dopo 8 secondi come fa il
telefono, risposta completa (3.374 caratteri) recuperata 160 secondi dopo.

Sorveglianza: golden sezione [15], 9 check — magazzino, aggancio, rotta, legame
con l'utente, tetto e scadenza, e lato client la chiave inviata, il ripescaggio
e **il ricordo in `localStorage`** (senza il quale una scheda uccisa perde la
risposta per sempre). **185/185.**

# IMPALCATURA FORENSE — SWGDE (v9.223-9.225, 31 ago 2026)

Nata leggendo lo standard vero, **SWGDE Best Practices for Digital Forensic
Video Analysis**, che è ciò su cui sono costruiti Amped FIVE e gli altri. I
suoi quattro requisiti **non riguardano l'intelligenza artificiale**:
integrità · riproducibilità · il miglioramento non può aggiungere informazione ·
i rilievi vanno separati dalle interpretazioni.

⚠️ **La nostra analisi era filosoficamente l'opposto**: un modello che descrive
è interpretazione pura, e nel documento era mescolata alle misure. `src/forensics.py`
mette attorno l'impalcatura che mancava.

## Cosa c'è ora nel documento

1. **Impronta SHA-256 dell'originale**, stampata nel referto. È la cosa più
   economica e più importante: permette di scrivere in un atto «il file che ho
   analizzato è questo», e a chiunque di verificarlo con un comando.
2. **Registro di lavorazione**: il comando ffmpeg con i parametri veri
   (`select='gt(scene,0.25)'`, scala, qualità, tetto), i **minutaggi di ogni
   fotogramma letti da `showinfo`** (non stimati), il modello di trascrizione e
   la lingua riconosciuta con la sua confidenza, le versioni degli strumenti.
   È quello che fa il referto di Amped, e per noi costava solo scriverlo.
3. **Metadati profondi con `exiftool`** (nel Dockerfile): gli atomi del
   contenitore, i tag del produttore, le date per traccia. Da lì si capisce se
   un file esce da una telecamera o da un editor. Le firme (`Lavf`, `Adobe`,
   `HandBrake`, `WhatsApp`, `ExifTool`…) vengono da Xiang et al., *Forensic
   Analysis of Video Files Using Metadata* (Purdue): con i **soli metadati** si
   distingue un originale da un rielaborato al 99%. **Regole, non modelli** —
   quindi deterministico, quindi difendibile.
4. **Due sezioni separate**: `RILIEVI (misure — verificabili)` e
   `INTERPRETAZIONE DEL MOTORE (non misure)`.
5. **Dichiarazioni esplicite**: non miglioriamo l'immagine (né
   super-risoluzione né denoise) e non identifichiamo persone.

⚠️ **Sui nomi degli strumenti** — tensione risolta di proposito: gli strumenti
**deterministici** si nominano con la versione (sono liberi, e sono la parte
che un altro **può** rifare); il motore di descrizione resta **«Tetramorph»**,
con accanto scritto che quella parte **non è riproducibile per natura**. Dare
un nome e lasciar credere il contrario sarebbe peggio.

**Posizionamento**: non competiamo con Amped FIVE (oltre 10.000 €/postazione +
certificazione LEVA) — quello è *la perizia*. Noi siamo lo strumento
dell'**avvocato**: triage di ore di filmato, linea temporale, e il confronto
col verbale. Va detto nel documento, e ci protegge.

Sorveglianza: golden sezione [14], 11 check (impronta, registro con i parametri
veri, separazione nelle due lingue, le due dichiarazioni, il motore che non si
chiama col nome del modello). **173/173.**

# YOLO: MISURATO, E PER ORA NO (31 ago 2026)

Promesso di misurare prima di installare. Misurato sul video reale
dell'utente (4,6 MB, 21 s, 1280×720), **3 thread su 6 core, nessuna GPU**:

| | ms/fotogramma | 10 min di video a 2 fps | 60 min |
|---|---|---|---|
| **yolov8n** | **717 ms** | 14 min | 86 min |
| **yolov8s** | **1492 ms** | 30 min | 179 min |

⚠️ **Avevo stimato 50-150 ms: era sbagliato di 5-10 volte.** Il vantaggio sul
modello di visione (~30 s/fotogramma) è quindi **~42×**, non 200× come avevo
detto.

**E l'accuratezza non è chiaramente migliore.** Su quel filmato: yolov8n vede
al massimo 5 persone (media 2,0) e inventa **un cavallo e una sedia**;
yolov8s al massimo 7 (media 2,8) e una **cravatta**. Il modello di visione
diceva «circa 8-10 persone». Un falso positivo «cavallo» in un atto giudiziario
è imbarazzante; presentare quei numeri come misure sarebbe peggio che non
averli.

**Conclusione: non si installa ora.** Costa 2 GB nell'immagine e ~1,4× il tempo
reale su una macchina che regge già sei siti, per un guadagno di affidabilità
non dimostrato. Il valore vero di YOLO resta **la copertura temporale** («dove
succede qualcosa in 40 ore») e la **riproducibilità** — due cose che
diventerebbero interessanti con una macchina con GPU o su un caso d'uso di
sorveglianza lunga. Da riprendere allora, non prima.

# ⚠️ JAVASCRIPT INLINE = CODICE MORTO (v9.216-9.219, 31 ago 2026)

**Regressione mia del 30 agosto, scoperta dall'utente un giorno dopo.**
La CSP `script-src 'self'` è giusta e **va tenuta** — è ciò che impedisce a uno
script iniettato di eseguire. Ma vieta anche **il nostro** JavaScript scritto
dentro l'HTML, e lo fa **in silenzio**: nessun errore, la pagina sembra a posto
e non funziona.

Sono rimasti muti per un giorno intero:
- **`index.html`** → il service worker non si registrava: **PWA e notifiche
  push ferme** (le notifiche sono ciò che avvisa quando l'analisi è pronta);
- **`intake.html`** → il modulo di primo contatto **pubblico**, quello che
  compila il cliente;
- **`in_hearing.html`** → l'assistente d'udienza;
- **`admin_audit.html`** → il registro degli accessi;
- **`login.html`** → i pulsanti 🇦🇱/🇮🇹 e l'occhio della password.

**Il rimedio NON è indebolire la CSP.** Tutto il codice sta ora in
`/static/*.js`, che `'self'` permette. Le due variabili che venivano dal server
passano da attributi `data-` (`data-firm-slug`, `data-case-id`).

**Golden sezione [13]** (22 check): fallisce se qualcuno rimette JavaScript in
un template, se usa attributi `on*`, **o se indebolisce la CSP** per farlo
funzionare. Verificato che morda.

## ⚠️⚠️ IL DANNO PIÙ GRAVE: HO SOVRASCRITTO UN FILE CHE ESISTEVA

**`static/login.js` esisteva già dal 19 agosto** e conteneva **l'unico gestore
dell'invio del modulo di accesso**. Il template aveva
`<script src="/static/login.js">`, che ho letto come «tag rotto verso un file
inesistente» — senza verificarlo — e la mia estrazione degli script inline ci
ha **scritto sopra**.

Risultato: **il pulsante «Hyr» non faceva più niente.** Il modulo non ha né
`action` né `method`: senza quel JavaScript il click non produce nulla —
nessun errore, nessun messaggio, nessun indizio. Se ne è accorto l'utente,
che non riusciva più a entrare nel proprio prodotto.

Recuperato dall'immagine `v9.215` e riunito con i blocchi estratti.
**Prima di scrivere un file, guardare se c'è.** Avevo perfino notato il tag e
concluso che puntasse al vuoto: un `ls` sarebbe bastato. Gli altri quattro file
(`sw-register`, `intake`, `in_hearing`, `admin_audit`) li ho creati io —
verificato, nessun altro danno.

**Guardia**: il golden ora controlla che `login.js` contenga il gestore del
modulo, la chiamata a `/api/login`, l'occhio, i pulsanti lingua e il recupero
password — e che il tag sia **uno solo e con il numero di versione**.
Verificato che morda.

## Due trappole trovate riparando

**1. Un file caricato due volte = ogni gestore agganciato due volte.** In
`login.html` c'era già un `<script src="/static/login.js">` che puntava a un
file **inesistente** (404 silenzioso): creandolo, quel tag è tornato vivo e si
è sommato al mio. Un click sull'occhio commutava **e ri-commutava**: effetto
visibile **nessuno**, che è il modo più confondente di rompersi — sembra che il
pulsante non risponda, mentre risponde due volte. Prima di aggiungere un tag,
guardare se ce n'è già uno, **anche rotto**.

**2. L'occhio ora usa la delega sul documento**, non `getElementById(...)
.addEventListener`. Quest'ultimo era lì e non funzionava, e la diagnosi non è
mai arrivata in fondo (il click arrivava al pulsante — trusted, fase di
risalita — il file girava, l'elemento era unico, lo script differito; e
riagganciando lo **stesso** gestore a mano funzionava). Quando una diagnosi non
converge, la cosa utile non è insistere: è **togliere la condizione che può
fallire**. ⚠️ Non tornare all'aggancio diretto.

## E il cache-busting vale anche per questi file

Cambiare `static/login.js` senza alzare il `?v=` serve a niente: il browser
continua a servire il vecchio. Successo subito, la prima volta.

## Le lingue miste: NON era un difetto di traduzione

L'utente ha segnalato interfaccia mista. Misurato: **210 chiavi `data-i18n`
usate, 210 tradotte, zero mancanti**; sulla pagina viva in sessione IT, **zero**
testi albanesi nell'interfaccia (34 voci del menu PRO comprese). Quello che si
vedeva in albanese erano i **titoli degli eventi**, cioè dati creati in sessione
albanese fra il 20 e il 30 agosto.

⚠️ **Due miei audit hanno dato «118 traduzioni mancanti», ed era falso.** Il
primo contava le graffe e si spezzava sulle parentesi dentro le stringhe; il
secondo cercava `^chiave:` e prendeva **solo la prima chiave per riga**, mentre
il dizionario ne ha molte sulla stessa riga. **Quando un audit produce un
numero allarmante, la prima ipotesi da scartare è che sia rotto l'audit** — se
ci avessi creduto avrei riscritto traduzioni già presenti.

# PROVE VIDEO (v9.207-9.211, 31 ago 2026)

Rapina, omicidio, aggressione: la videosorveglianza è spesso **la** prova. Ora
entra nel fascicolo come tutto il resto — `.mp4 .mov .avi .mkv .dav` e altri
11 formati. **`.dav` è il contenitore delle telecamere Dahua**, cioè di gran
parte di negozi e banche in Albania: è il caso d'uso vero, non un extra.

## ⚠️ IL LIMITE CHE DECIDE COSA POSSIAMO PROMETTERE

**Il cervello non guarda i video**: prende immagini e testo. Quindi non
«analizziamo un video» — estraiamo fotogrammi e li facciamo leggere uno per
uno. Ne segue che **l'istante decisivo può cadere fra due fotogrammi** e non
essere visto da nessuno. Questo avviso è scritto **dentro il risultato** che
l'avvocato legge e copia, non nella documentazione dove non lo leggerebbe.

## Cosa fa, e cosa NON fa di proposito

Ricostruisce, mette in fila, misura, e guarda il **file**: com'è stato
prodotto, se è stato ricodificato, se i tempi sono continui. **Non dice chi è
la persona inquadrata** — riconoscere qualcuno dai tratti è identificazione
biometrica, la linea rossa dell'AI Act, ed è il punto in cui un errore non è
più recuperabile: un «è lui» sbagliato una volta brucia il prodotto. Le
persone si indicano per posizione («persona A»).

La mira è quella che vale per un difensore: non *«cosa mostra»* (lo vede anche
lui) ma **«possono usarlo, e mostra davvero quello che l'accusa dice?»**.

## `src/video.py`

`probe()` (ffprobe → durata, codec, fps, data dichiarata, encoder) ·
`rilievi_integrita()` (**osservazioni sul file, non accuse**: «prodotto da un
programma di montaggio» è verificabile, «manomesso» è una conclusione che non
ci spetta) · `estrai_fotogrammi()` · `descrivi_fotogrammi()` · `analizza()` ·
**`confronta()`** — il video contro le carte.

**Innesto**: `documents.extract_text` ha un ramo video che restituisce **testo
con i minutaggi**. Da lì in poi il video è un documento come un PDF e
attraversa analisi, fascicolo, contraddizioni e Q&A **senza che nessuno di
quei moduli sappia che è un video**. Un percorso parallelo avrebbe voluto dire
duplicarli tutti.

**GOTCHA (costati una prova viva, non trovati dai test):**
- **`ocr_image` aggiungeva «restituisci SOLO il testo estratto, nessun
  commento»** — giusto per un documento scansionato, opposto a quel che serve
  per descrivere una scena. Il modello notava il conflitto e ci scriveva sopra
  un paragrafo, arrivando a chiedersi se fosse prompt injection: l'avvocato
  leggeva la meta-discussione invece della scena. Ora `istruzione_finale` è
  sostituibile; il predefinito resta identico per tutti gli altri.
- **Il titolo mostrava il nome interno del file** (`4cc450930ecf….mp4`). In un
  atto va il nome che l'avvocato riconosce: `extract_text` riceve
  `original_filename`.
- **Intestazioni in albanese e rilievi in italiano** nello stesso documento:
  `rilievi_integrita` era scritta solo in italiano. Ora `_RILIEVI` ha le stesse
  chiavi nelle due lingue, e il golden verifica che restino allineate.
- **Fotogrammi sui cambi di scena, con ripiego a intervallo.** Senza ripiego,
  un video con una sola inquadratura non produce **nessun** fotogramma e
  l'analisi esce vuota senza errore.
- **`showinfo` per i minutaggi veri**: stimarli dal numero d'ordine dà tempi
  sbagliati, e un minutaggio sbagliato in un atto è peggio di uno mancante.

## ⚠️ Il pannello diceva «in analisi» per sempre

`_pollDossier` si fermava a **90 tentativi × 4s = sei minuti**, tarati su un
documento (30-60s). Un video ne impiega **dieci-venti**: il lavoro finiva sul
server e il pannello restava con la rotella che gira — **e si arrendeva in
silenzio**. Misurato su un video vero di 20 secondi (4,4 MB): analisi completa
in ~12 minuti, pannello fermo su «Po e analizojmë…».

Ora: **attesa progressiva** (4s per il primo minuto, poi 10s) fino a **~40
minuti**, e quando si arrende **lo dice** con un pulsante «Ricontrolla ora» —
il lavoro continua sul server anche a pagina chiusa, quindi il messaggio non
è un errore, è un'informazione. Golden: il limite non può tornare sotto i 30
minuti e il messaggio non può sparire.

## Limiti e caricamento

**Due soglie diverse**: 25 MB per un atto, **500 MB** per un video. Alzarla per
tutti sarebbe sbagliato — un PDF da 400 MB non è un atto, è un errore.
La soglia vive in **quattro posti** e devono coincidere: `config.py`,
`MAX_CONTENT_LENGTH` di Flask (era 27 MB e respingeva i video **prima** del
nostro codice), `client_max_body_size` di nginx (**520m**, in entrambi i
blocchi :80 e :443) e il tetto **nel browser** dentro `uploadFiles` — che da
solo rendeva inutile tutto il resto, perché il video non partiva proprio.
E l'`accept` del selettore: senza, un `.mp4` compare **grigio**, come già
successo con .docx e .heic.

I video si scrivono **a flusso** (`f.save()`), non in memoria: 500 MB in RAM
per caricamento metterebbero in ginocchio la macchina e con lei gli altri
cinque siti. La dimensione vera si verifica **dopo** la scrittura e il file si
cancella se non torna — `Content-Length` è una dichiarazione del client.

## Il pannello — 🎥 nel menu PRO

`openVideo()`: elenco dei video del fascicolo con lo stato, la loro analisi, e
il **confronto**. Bilingue (`data-i18n` + `I18N_IT` + `T_IT`).

## Costi misurati

Un video di 12 secondi → 12 fotogrammi → **~195 s**. Il confronto: **~230 s**.
I fotogrammi si leggono **in sequenza**: parallelizzarli accorcerebbe l'attesa
ma prenderebbe posti al semaforo globale (6), e la lezione del Genio è di
lasciarne liberi. Tutto gira in sottofondo, il caricamento torna in 0 s.

## Sorveglianza — golden sezione [11], 17 check

Formati coincidenti nei tre posti · le due soglie diverse · rilievi bilingue
con le stesse chiavi · **i prompt vietano l'identificazione e la conclusione
sulla colpevolezza** · il limite dichiarato in entrambe le lingue · il
caricamento scrive su disco. Verificato che morda: tolto il divieto di
identificazione, il QA cade. Golden **98 → 115**.

## GDPR — è un trattamento NUOVO, non un formato in più

Un video di rapina contiene i volti di **persone che non c'entrano niente**.
Aggiornati: **DPA** (il video fra i tipi di dato + obbligo di minimizzazione:
se rilevano tre minuti non si caricano tre ore + il non-riconoscimento
facciale), **registro dei trattamenti** (voce **A6**, con la misura che i
fotogrammi estratti **non si conservano** — cartella temporanea) e **DPIA**
(rischio nuovo, misure verificabili, rischio residuo **medio**).

# PROVE AUDIO — trascrizione (v9.212-9.215, 31 ago 2026)

Una telefonata registrata, un vocale, l'audio di una telecamera. Finora
entravano solo se qualcuno li trascriveva a mano. `src/audio.py`, motore
**faster-whisper** che gira **in locale sul nostro server** — le parole
registrate non escono dall'Europa (i fotogrammi sì, vanno a Tetramorph).

## Misurato PRIMA di prometterlo (6 core, 4 thread)

| lingua | `small` | `medium` |
|---|---|---|
| **italiano** | **parola per parola**, 0,73× | uguale, 1,56× |
| **albanese** | impreciso, 0,81× | **non migliora**, 2,13× |

`medium` costa 2,6 volte tanto e in albanese non guadagna niente → **`small`**.
Un video di 10 minuti costa ~7 minuti di trascrizione, in sottofondo.
⚠️ **Dubbio onesto sulla misura albanese**: l'audio di prova era sintetico (TTS
locale, qualità modesta). Può darsi che il problema fosse la voce e non la
lingua — prima di dire «Whisper non sa l'albanese» va rifatta su una
registrazione **vera**.

## ⚠️ IL DIFETTO PIÙ GRAVE, E COME È STATO TROVATO

Imponevo al trascrittore la lingua **della sessione**. Ma un avvocato che
lavora in albanese ha spessissimo una registrazione **in italiano**. Misurato:
la stessa dichiarazione italiana, forzata a shqip, usciva
*«Uno aveva una giakka skura e teneva kvalkosa im mano»* — la fonetica italiana
scritta in ortografia albanese. **Sbagliata e plausibile insieme**, che è la
combinazione peggiore: un avvocato di fretta potrebbe citarla.

Ora la lingua si **riconosce e si dichiara** (`it` 100%, `sq` 91% sulle prove),
con avviso se la confidenza è sotto il 60%. Il golden sezione [12] fallisce se
qualcuno rimette l'imposizione dalla sessione.

**L'ha trovato la prova viva, non i test.** I test passavano tutti.

## Come si innesta

Stessa scelta del video: `documents.extract_text` ha un ramo audio che
restituisce **testo con i minutaggi**, e da lì in poi la registrazione è un
documento come gli altri.

**Nel video, le battute sono INTRECCIATE ai fotogrammi in ordine di tempo**,
non appese in fondo: in una rapina quello che conta è che allo stesso minuto si
veda una mano nella tasca **e** si senta la frase. Separati, l'incrocio lo deve
fare l'avvocato a mente.

## Precauzioni sulla macchina

**Una trascrizione alla volta** in tutto il sistema (semaforo in `audio.py`) e
**3 thread su 6 core**: sopra ci sono altri cinque siti, e tre avvocati che
caricano insieme prenderebbero dodici thread su sei core. Il modello sta nel
**volume dati** (`data/whisper/`, 464 MB), non nell'immagine: sopravvive ai
deploy e non pesa su ogni build. Si carica in 5,6 s, una volta sola.

⚠️ `faster-whisper==1.2.1`, **non 1.0.3**: quella non ha wheel per Python 3.14 e
pip falliva **in silenzio** dentro una pipe, col build che dichiarava successo.
Se si aggiorna, provare che **importi**, non che il build passi.

## I selezionatori di file — 18, e non sono la stessa cosa

**Due** devono accettare video e audio (`dossier-input` e `fk-file`: caricano
nel fascicolo e passano da `extract_text`). **Tutti gli altri no**, di
proposito: sono allegati per uno strumento, finiscono al cervello che li legge
col tool `Read` — che apre PDF e immagini e **non apre un mp4**. Metterceli
vorrebbe dire far scegliere un video per poi fallire in silenzio.
Il golden verifica **entrambe le direzioni**: che i due li accettino e che gli
altri no.

## Limiti e QA

Tre soglie: **25 MB** atto · **200 MB** audio · **500 MB** video.
Golden sezione [12] (12 check) + selezionatori (3): **115 → 130**.

## Mappa feature / moduli (src/)
- **expertise.py** — Modele Ekspertize (8 template, incl. abuzim_policor "due menti"). `retrieve_grounded` (seed + `_expand_terms` LLM + `_heading_scan` stem 5-char diacritic-fold + BM25). Riusato da prosecutor/notary/deadlines/afati.
- **prosecutor.py** — Super Prokuror: analyze, draft_indictment, investigation_plan, investigative_act(kind), coercive_measure, dismissal_request, stress_test + cittadino (citizen_complaint, victim_rights, dismissal_appeal, delay_complaint). Assistivo, mai auto-accusa (EU AI Act).
- **notary.py** — Super Noteri: DEED_TYPES (20), PROKURA_SCOPES (16 tagra), DECLARATION_TYPES (6), draft_deed/prokura/declaration, check_deed, succession, documents_needed, draft_revocation, check_conflicts.
- **living_law.py** — Ligj i gjallë: verify_claims (verifica frase↔testo reale nen), check_law_live (web→QBZ). + freschezza in citation_verifier (volatility/stale).
- **intake.py** — Pika e parë: triage(story) → orientamento + urgenza + ROUTE token → instrada allo strumento.
- **afati.py** — Motore afate: TRIGGERS (8) → scadenze grounded + blocco `AFAT | titolo | YYYY-MM-DD` → calendario (POST /api/events).
- **vault.py** — Fashikull: build_context(case_id), ask (Q&A [Dok N]), find_needle, who_said_what. **pro_features.py** build_case_timeline (events/contradictions/gaps).
- **citation_verifier.py** — Verifikuar (verified/fake/repealed/needs_code + volatility/stale). **deadlines.py** prescrizione.
- **case_brief.py** — **memoria del caso**: il riassunto del fascicolo che ogni
  strumento PRO riceve, perché prima ripartivano da ZERO anche a caso aperto.
  Contiene titolo+giurisdizione, i fatti come li ha raccontati l'avvocato,
  l'ultima analisi del cervello, i blocchi strutturati (piano d'azione, leve,
  urgenze), i documenti caricati, le ricerche salvate. **Quote per sezione**:
  senza budget un fascicolo maturo scaccia la domanda vera.
  `append_to()` lo mette **in CODA** al testo — la richiesta dell'avvocato resta
  la prima cosa letta e i documenti da analizzare non vengono spostati — marcato
  come SFONDO con divieto di obbedire a istruzioni interne (i documenti vengono
  da controparti). Innestato via `web._with_case(text, body)` in 12 punti:
  `_pros_facts` copre da solo gli 11 strumenti del procuratore.
  **NON va negli strumenti che VERIFICANO** (act-check, verify_claims,
  extract_data): porterebbe con sé le citazioni delle risposte precedenti e il
  verificatore darebbe risultati falsi.
  Misurato sulla stessa domanda generica ("qual è l'angolo vincente?"):
  **senza fascicolo 0/5** (il modello rifiuta: "non è stato fornito alcun
  fatto"), **con fascicolo 4/6** e strategia specifica.
- **letters.py** — Letra dhe shkresa: lettere/PEC pronte da inviare, radicate
  nel **fascicolo** (`vault.build_context`) e negli articoli **recuperati**
  (`expertise.retrieve_grounded`). Cataloghi separati per giurisdizione
  (**14 IT / 12 AL**): destinatario, canale, elementi obbligatori, seed.
  Tre famiglie — `CLAIM` (controparte), `REPORT` (autorità), `REQUEST` (PA) —
  con **divieto duro di mescolarle**: minacciare una denuncia per ottenere
  pagamento è estorsione, e il prompt lo vieta esplicitamente (annunciare le
  vie legali resta lecito). `letter_body()` isola la sola lettera per il
  .docx, scartando le note al collega. Export via `pro_features.render_act_docx`
  (DOCX) e stampa del browser (PDF: nel container non c'è alcun generatore, e
  aggiungerlo significherebbe gestire i font per ë/ç/à).
  **Allegati**: il documento ricevuto (lettera di licenziamento, atto, foto)
  entra in una sezione SUA con l'istruzione di ribattere punto per punto —
  mai mescolato alle istruzioni dell'avvocato, che sarebbe anche un vettore di
  prompt injection. Con l'allegato la lettera passa da 3/6 a **6/6** riscontri
  puntuali (nomina la controparte, la data, usa le loro parole contro di loro).
- **jobs.py** (28 ago 2026) — registro dei lavori lunghi. Il cervello impiega
  minuti e prima girava DENTRO la richiesta HTTP: sul telefono bastava passare
  a WhatsApp perché il sistema sospendesse la scheda, la connessione cadesse e
  **il lavoro morisse con lei** («Gabim rrjeti» in rosso, dopo che il server
  aveva già fatto tutto). Ora `POST /api/ask/start` avvia un thread e torna
  subito un `job_id`; `GET /api/ask/events?job=&from=N` rigioca i frame dal
  numero N e poi segue i vivi. Riconnettersi = chiedere di nuovo da dove si è
  rimasti, quindi una caduta di rete costa un secondo, non una risposta.
  I frame si conservano **già formattati** (`data: {...}`), e `slice_from()`
  restituisce frame+done+indice **sotto un solo lock**: altrimenti un frame
  appeso fra le due domande verrebbe perso in silenzio.
  **TRAPPOLA**: `_req_index()` legge l'oggetto `request` di Flask e in un
  thread esplode → va catturato PRIMA (`_idx = _req_index()`). Vale per
  qualunque altro lavoro si sposti in background.
  Il vecchio `POST /api/ask/stream` è rimasto identico e funzionante: il
  rollback è cambiare solo `app.js`.
  **La domanda appesa (v9.187)** — il registro vive in memoria, quindi **un
  deploy uccide i lavori in corso**. Misurato sullo storico: **8 fascicoli su
  71** finivano con una domanda dell'avvocato e nient'altro — nessuna
  risposta, nessun errore, nessuna spiegazione. (Attenzione contando: «domanda
  senza assistant subito dopo» ne dà 20, ma la maggior parte sono domande
  consecutive poi risposte. Il conto vero è «domanda che è l'ULTIMO messaggio
  del suo caso».) Ora riaprendo un fascicolo così, `jobs.find_active` +
  `GET /api/ask/active?case=` distinguono i due casi che dal client sembrano
  identici: **lavoro vivo** → ci si riattacca e la risposta compare (anche se
  la domanda era partita da un altro dispositivo — questo prima non
  succedeva); **lavoro morto** → si dice, con il pulsante per rimandarla.
  `find_active` è vincolato all'utente: il registro dei lavori è un elenco di
  chi sta chiedendo cosa.
  **`seguiJob` è UNO SOLO** per le due strade (domanda inviata / domanda
  ritrovata): due copie divergerebbero, e a divergere sarebbe il modo in cui
  l'avvocato vede la risposta. Estraendolo dal gestore d'invio è facilissimo
  portarsi via anche il suo `catch` — successo, e riprodurrebbe esattamente il
  difetto che si sta riparando un livello più su.
- **push.py** (28 ago 2026) — notifica quando l'analisi è pronta. Possibile
  solo perché il lavoro sopravvive alla pagina. VAPID in `/opt/super-avvocato.env`
  (`VAPID_PRIVATE_KEY/PUBLIC_KEY/SUBJECT`) — **cambiarle invalida tutti gli
  abbonamenti degli utenti**. Invia in un thread, non solleva mai, e su 404/410
  cancella l'abbonamento (dispositivo sparito) invece di ritentare per sempre.
  Tabella `push_subscriptions` (endpoint UNIQUE + upsert: un telefono non
  diventa dieci righe). L'aggancio è **una riga sola** dopo `jobs_mod.finish()`,
  dentro un try che ingoia tutto: se le notifiche si rompono, la risposta
  arriva comunque.
- **second_opinion/adversary/fable_drafter.py** — tool Fable (model_override="fable").
- **genio.py** — Genio Legale, 6 lenti in parallelo. Rifatto il 29 ago 2026
  (v9.183-9.185) su cinque punti; i numeri qui sotto sono **misurati**, non stimati.
  * **Memoria.** `build_case_block` riceve `previous_briefs`: del Genio
    precedente entrano 700 caratteri per lente, con l'ordine `MOS I PËRSËRIT`.
    Prima ogni giro ripartiva da zero: 27 brief su 12 casi = **15 ri-giri, circa
    11 ore di modello** spese a ripensare cose già pensate.
  * **Allegati veri.** `_blocco_documenti()` passa il **testo estratto** dei
    documenti del fascicolo, con budget **totale** `BUDGET_DOCUMENTI = 24_000`
    (non per file: dieci documenti non devono moltiplicare il contesto per dieci).
    Le lenti ricevono anche `attachments` per PDF/foto/docx.
  * **Capacità.** Il semaforo globale delle chiamate al modello è 6 e il Genio
    ne prendeva **tutti e sei**: per la durata del giro nessun altro avvocato
    riusciva a far partire niente. Ora `MENTI_PARALLELE = 4` (env `GENIO_PARALLEL`)
    lascia due slot sempre liberi, e `_genio_sem` (env `GENIO_CONCURRENT`, 1)
    tiene **un Genio alla volta** in tutto il sistema. Le sei lenti si fanno
    comunque tutte: cambia quante corrono insieme, non quante ne corrono.
    Verificato dal vivo: mai più di 4 processi `claude -p` durante un giro.
    **`run_brief` è un involucro con `try/finally` attorno a `_run_brief`**: il
    `finally` di un generatore scatta anche se chi consuma abbandona a metà
    (utente che chiude, connessione che cade). Senza, il semaforo resterebbe
    preso per sempre e il Genio sarebbe bloccato a tutti fino al riavvio.
  * **In background.** `POST /api/genio/start` → `job_id` in **0,2s**, il lavoro
    gira in un thread sul registro di `jobs.py`, il client si riattacca con
    `askAttach`. Alla fine parte la notifica push. Verificato: pagina chiusa,
    cervello ancora al lavoro 37 minuti dopo. Il percorso storico
    `POST /api/cases/<id>/genio` resta funzionante — rollback = una riga in `app.js`.
    `_genio_prepare` torna **tre** valori `(gen, brief_id, err)` e non due:
    anche `jsonify(...), 404` è una tupla, e distinguerli dalla forma sarebbe
    un trabocchetto.
  * **Seconda mente (Fable).** Se una delle tre lenti che devono *trovare*
    (`LENTI_DA_RITENTARE = kill_shot, leverage, riframing`) torna a mani vuote,
    la stessa domanda va a **Fable effort max** con `SPRONE_FABLE`: «un'altra
    mente non ha trovato nulla, non rifare la sua strada». Additivo, mai
    sostitutivo: arriva come chiave `leverage:fable` e si vede da chi viene.
    Se anche Fable torna vuoto non si mostra niente (due risposte vuote sono
    rumore, non trasparenza). **Ha già salvato un caso reale**: brief #30,
    `leverage` di Opus in timeout a 1800s, Fable trova 3 leve in 7,8 minuti
    citando le date del documento caricato.
  * **GOTCHA UI**: `leverage:fable` non ha una carta sua, va **dentro** quella
    della lente fallita. E il ramo `kind === "error"` fa `body.textContent =`,
    che azzera il corpo: siccome il caso più probabile per la seconda mente è
    proprio una lente in errore, quel ramo ora **conserva** un `.gn-second` già
    presente. Dal vivo l'ordine è giusto per costruzione, ma riaprendo dallo
    storico dipendeva dall'ordine delle chiavi nel JSON.
- **web.py** — endpoint (199 rotte). UI: `static/app.js` (hub `_openHub` nel menu PRO: Super Prokurori/Super Noteri/Ligj i gjallë; mode-bar snellite che puntano ai hub; `openFascikull`, `openIntake`, `openAfati`, `openSavedResearch`). `templates/index.html` menu PRO.

## PWA — installabile sul telefono (28 ago 2026)

Il sito era già responsive; mancava solo la confezione. Ora si aggiunge alla
schermata home e si apre a schermo intero, senza store e senza costi.

- **`/manifest.webmanifest` e `/sw.js` sono rotte Flask, servite dalla RADICE.**
  Non è pignoleria: un service worker vale solo per la cartella da cui viene
  servito — da `/static/sw.js` governerebbe soltanto `/static/`, cioè niente.
  Header `Service-Worker-Allowed: /` e `Cache-Control: no-cache, max-age=0`
  (un service worker sbagliato che resta in cache non si corregge a distanza).
- **⚠️ IL SERVICE WORKER NON METTE IN CACHE L'APPLICAZIONE, E NON DEVE MAI
  FARLO.** In cache ci sono due sole cose: `offline.html` e un'icona. Salta
  `/api/`, i POST e gli altri domini. Un service worker che conserva pagine o
  `app.js` sopravvive ai deploy e continua a servire codice vecchio a utenti
  che non capiscono perché — e per toglierlo devi convincere il browser di
  ognuno. Se un giorno serve cache, si aggiunga **solo** su asset con hash nel
  nome, mai su HTML.
  Verifica: in console `caches.open('sa-guscio-2').then(c=>c.keys()).then(k=>k.map(r=>r.url))`
  deve restituire due sole voci.
- **Icone**: `static/icon-{192,512}.png`, `icon-maskable-512.png` (margine 22%,
  Android ritaglia), `apple-touch-icon.png`. Generate con Pillow **dentro il
  container** (sul VPS non c'è né Pillow né ImageMagick) ridisegnando la
  bilancia della favicon SVG già presente in `index.html`.
- **iPhone**: `apple-mobile-web-app-status-bar-style` deve restare **`black`**,
  NON `black-translucent`. Con translucent iOS fa passare la pagina sotto la
  barra di stato e l'intestazione finisce dietro l'orologio. Il CSS gestiva già
  la safe-area (`--safe-t`): il problema era il meta, non il CSS.
- **Il nome sotto l'icona** viene da `short_name` (Android) e dal meta
  `apple-mobile-web-app-title` (iPhone — è questo che decide, non `short_name`).
  **È congelato al momento dell'installazione**: per vederlo cambiare bisogna
  togliere e rimettere l'icona dalla home.
- **Notifiche**: voce nel menu ☰, permesso chiesto **solo al click** (chiederlo
  all'apertura si prende un "blocca" quasi definitivo) + notifica di prova
  immediata. Il service worker **non mostra nulla se l'app è già in primo
  piano** (`clients.matchAll` + `focused`): notificare una cosa che uno ha
  davanti agli occhi è il modo più rapido per farsi disattivare le notifiche.
- **Dopo ogni modifica a `style.css` o `app.js` va alzato `?v=` in
  `templates/index.html`**, altrimenti i browser servono la versione vecchia.

# SICUREZZA — cosa è chiuso e come (30 ago 2026)

Audit completo e blindatura. **Tutto misurato**, non ipotizzato.

## 🔴 Il cervello non legge più il codice né i dati (v9.193-9.195)

Con gli allegati riceveva `Read` + `--permission-mode bypassPermissions`, e
quel bypass **toglie ogni confine sul filesystem**. Verificato in produzione:
chiedendo `/app/src/config.py` rispondeva «422 righe».

**Due rimedi che NON funzionano** (provati):
1. limitare `Read(/percorso/**)` **lasciando** il bypass → legge lo stesso;
2. spostare la cartella di lavoro **lasciando** il bypass → legge lo stesso.

**Servono INSIEME**: niente `--permission-mode`, **e** non partire da `/app`.
⚠️ **La cartella di lavoro è sempre leggibile dagli strumenti del processo.**
Ora parte da `_CWD_CERVELLO` (`/tmp/brain-cwd`, vuota) e `Read` è limitato alle
cartelle degli allegati di **quella** chiamata.
⚠️ `--allowedTools` è variadico: era chiuso da `--permission-mode`, quindi ora
il prompt DEVE arrivare da stdin (e così fa). Passandolo come argomento la CLI
se lo mangia come nome di tool — errore fuorviante «Input must be provided».

## 🔴 SSH solo a chiave

`/etc/ssh/sshd_config.d/00-blindatura.conf`. ⚠️ **Il prefisso `00-` non è
estetica**: in sshd vince la **PRIMA** occorrenza e `50-cloud-init.conf` dice
`PasswordAuthentication yes` — un file `99-` non ha effetto e `sshd -T`
continua a mostrare `yes`.

## 🟠 Freno al login (v9.196-9.197)

**5 per utenza, 20 per indirizzo.** ⚠️ Uguali sarebbe un difetto: uno studio con
dieci avvocati esce da un IP solo e si bloccherebbe da solo. Scatta **prima**
di controllare la password (il tempo di risposta non deve rivelare se l'utenza
esiste); si azzera al login riuscito.

## 🟠 Backup cifrati

37 file AES-256, i 4 script cifrano e cancellano il chiaro, chiave in
`/root/.backup-key` (600), ripristino in `/root/ripristina-backup.sh`
**provato**. ⚠️ La chiave va copiata **fuori dal server**.
⚠️ I comandi di cifratura su **UNA riga**: le continuazioni dentro un heredoc si
sono rotte fra gli escape e hanno prodotto un backup **in chiaro**.

## 🟡 CSP — solo su superavokati.ai

**NON** nello snippet condiviso `aala-security.conf` (lo includono anche aala,
taxi, auto, crm, korauto). La riga che conta è **`connect-src 'self'`**.
`script-src` senza `'unsafe-inline'`; `style-src` ce l'ha per i 24 `style=`
nel markup.

## 🟡 Registro accessi ai fascicoli (v9.198)

`case_access_log`, agganciato a **`_resolve_case`** (un aggancio invece di 60).
Solo metadati, solo accessi riusciti, non ripete entro 5 minuti, non solleva mai.

## 🟡 Porte: da 7 esposte a 0

Fuori solo 22/80/443, verificato bussando da fuori.
⚠️ Per Next.js **`HOSTNAME=127.0.0.1` NON basta** con `npm start`: serve
`npx next start -p <porta> -H 127.0.0.1`. Con la sola variabile tre app su
quattro restano su `*` e sembra fatto.

## 🟠 Permessi sui dati: non più leggibili da tutta la macchina

Erano `755`/`644` — **chiunque** sulla macchina leggeva `app.db` e i documenti
(verificato: `www-data` ci arrivava), e lì girano **11 utenti non-root**: un
difetto di lettura file in un qualunque altro dei cinque siti sarebbe arrivato
ai fascicoli. Ora `700`/`600`, `chown 1000:1000`.
⚠️ **Da rilanciare dopo un ripristino**: `/root/permessi-dati.sh`. I permessi
non sopravvivono a un tar estratto male.

## 💭 Perché i documenti NON sono cifrati a riposo

Scelta ragionata, non dimenticanza: il controllo d'accesso è solido (nessun
IDOR — 4 attacchi, 4 bloccati), i permessi ora sono stretti, e **i backup — la
via realistica per cui un file esce — sono già cifrati**. Una cifratura
applicativa avrebbe la chiave sul server (l'app legge senza un umano): protegge
da un'immagine disco rubata, **non** da chi diventa root. E costerebbe cara:
tocca caricamento, OCR, **allegati del cervello** (la CLI legge dal disco col
tool `Read`) e scarico. Se un giorno serve, la strada è **LUKS sul volume**.

## Cosa tiene già (verificato)

Isolamento fra studi (4 tentativi cross-tenant → 404, fallisce chiuso) ·
password PBKDF2 salate · TLS 1.3 + HSTS · ufw · fail2ban · `ai_audit_log` ·
la **chat** non abilita `Read` (solo Genio e strumenti PRO passano allegati).

## Ancora aperto

Documenti caricati e `app.db` in chiaro · passphrase sulle chiavi SSH (tocca
all'utente) · far rileggere le 9 bozze legali a un avvocato · nomina del DPO ·
dal piano d'azione della DPIA: 2FA, allerte automatiche, valutazione LUKS,
canale web disattivabile con allegati, esclusione per-caso dal trattamento
esterno, secondo amministratore.

---

# GDPR — i documenti, e DOVE si vedono (31 ago 2026, v9.199-9.206)

## I 9 documenti — `legal/`, non nel codice

**Pubblici** (si mostrano, si firmano): `condizioni_{it,sq}.md` ·
`privacy_{it,sq}.md` (informativa sui dati **dell'avvocato**, art. 13) ·
`dpa_{it,sq}.md` (accordo sui dati dei **suoi clienti**, art. 26 L.124/2024 /
art. 28 GDPR — lo studio è titolare, noi responsabili).
**Interni** (non escono mai): `interno_registro_trattamenti.md` ·
`interno_procedura_violazione.md` (+ `violazioni/LEGGIMI.md`) · `interno_dpia.md`.

**Su file e non nel codice**: devono essere **gli stessi** che si mandano via
email. Se il testo a schermo e quello firmato divergono, la firma non prova niente.

⚠️ **Nei documenti per il cliente il motore si chiama «Tetramorph»**, ma nel
DPA il sub-responsabile deve restare **identificabile** — è il cliente ad avere
il diritto di sapere chi tratta i dati dei suoi assistiti e di opporsi a un
sub-responsabile nuovo. Formula: **«Tetramorph — operato da Anthropic PBC»**.
Nasconderlo violerebbe la clausola stessa che quel documento contiene.
⚠️ **Un contratto nomina la SOCIETÀ, non un marchio**: «Super Avokati» è il
prodotto e non può firmare né essere convenuto. Firmano **AALA** (Albania) e
**Deltalux Srl** (Italia, P.IVA 12021700963).

## Le TRE strade per leggerli — e perché servono tutte

1. **Al primo accesso** — `controllaCondizioni()` → finestra con spunta e
   «Accetto». `LEGAL_VERSION` in `web.py`: alzandola tutti riaccettano.
   Traccia in `legal_acceptances` (chi, quando, IP, versione).
2. **Dopo, dal menu ☰ → «Kushtet dhe të dhënat» / «Condizioni e dati»**
   (v9.203). ⚠️ **Questo mancava del tutto**: `controllaCondizioni` apriva la
   finestra solo a `!st.accepted`, quindi chi aveva accettato non aveva
   **nessun modo** di rileggere cosa aveva firmato. Il GDPR chiede che
   l'informativa sia *accessibile*, non che sia stata mostrata una volta.
   Stessa finestra con `mostraCondizioni(versione, soloLettura)`: via spunta e
   «Accetto», resta «Chiudi», titolo «Condizioni e dati» (non «Prima di
   cominciare» — chi rilegge ha già cominciato) e link alla pagina pubblica.
3. **`GET /legale` e `/legale/<lang>`, PUBBLICA, senza login** (v9.203).
   ⚠️ Non è una comodità: uno studio strutturato, prima di aprire un account,
   manda il proprio responsabile protezione dati a leggere il DPA. Se per
   leggerlo bisogna già essere clienti, la trattativa si ferma lì.
   Sorvegliata dal golden: se qualcuno ci mette `login_required`, il QA cade.

**Fonte unica per tutte e tre**: gli stessi file `.md`. Sono tre viste, non tre
testi.

## Il renderer della pagina pubblica (v9.206)

La prima versione serviva **markdown crudo** — `# Condizioni d'uso`, `**...**`,
le tabelle come file di barre. Difetto visibile **solo da fuori**, cioè
esattamente dove guarda chi non è ancora cliente: dentro l'app `renderMarkdown`
(app.js) rendeva già bene.

`web._legal_md_to_html()`. **Non riuso quello di app.js**: `app.js` avvia tutta
l'applicazione autenticata (login, service worker, chiamate API) e caricarlo su
una pagina pubblica è assurdo. Nel container **non c'è nessuna libreria
markdown** (verificato: markdown, markdown2, mistune, commonmark tutte assenti).

⚠️ **Due renderer sullo stesso testo sono una condizione di divergenza**, e a
divergere sarebbe *cosa si vede* di un testo che si firma: una tabella non resa
è informazione persa, non un difetto estetico. Non la elimino, la **sorveglio**:
il renderer copre gli **8 costrutti misurati** nei file (h1-h3, paragrafi,
`**grassetto**`, elenchi puntati e numerati, tabelle, `---`, `>`) e il **golden
sezione [10]** fallisce se in un documento legale compare un link, del codice,
dell'HTML o delle stelline spaiate. **Verificato che morda**: 4 costrutti
iniettati → 4 fallimenti. Meglio un QA rosso che una clausola che sparisce in
silenzio. Tutto passa da `markupsafe.escape` prima del markup.

Golden **59 → 98 check**.

## Il resto dell'impianto

- `legal_acceptances` + `case_access_log` (`storage.py`). Il registro accessi è
  agganciato a **`_resolve_case`**, il collo di bottiglia: un aggancio invece di 60.
- `GET /api/legal/doc/<nome>` — **whitelist di tre nomi**, quindi i documenti
  interni non possono uscire di lì (verificato anche con `../`).
  Serve il testo nella lingua della sessione e, se non c'è, **lo dice**: un
  consenso a un testo che non si capisce non è un consenso.
- `/legale/<lang>` accetta solo `it`; qualunque altra cosa cade su `sq`. Non è
  un nome di file: `/legale/interno_dpia` dà la pagina albanese, non la DPIA.

**Cosa resta all'utente**: far rileggere le bozze a un avvocato (lo dicono loro
stesse in testa), decidere sulla nomina del DPO, confermare la conclusione sul
rischio residuo della DPIA.

---

## Regole ferree (customer-facing)
- Errori customer-facing MAI nominano il modello → sempre "Tetramorph"/generico.
- Tutto **assistivo**: il professionista verifica e firma; niente auto-accusa/archiviazione/scadenze cieche.
- **Grounding sempre**: i nene vengono dal corpus, MAI dalla memoria del modello. Precisione > velocità (Opus max, anche 4 min ok).
- Super Avokati ha auth propria (login_required_api); utenti creati da admin o auto-provisionati da AALA (`/api/provision-demo`, secret-guarded).

## Storia versioni (sessione 19 ago 2026 — espansione ITALIA)
v9.112-9.113 giurisdizione come entitlement + isolamento sessione · 9.114-9.116
corpus IT (Wikisource) + retrieval jurisdiction-aware + Verifikuar IT · 9.118-9.128
**Fase C**: UI italiana completa (login bilingue, mode-bar, 3 hub, 19 modali
`_openFableTool`, drafter notaio, Modelli di perizia, Fascicolo, Primo contatto,
12 renderer standalone, dropdown backend, 271 stringhe legali di clausole/perizie,
calendario + dashboard) · 9.129 **sessione IT davvero italiana** (login imposta la
giurisdizione, codici jurisdiction-aware, mode-bar, benvenuto) · 9.130 fix `t()`
mascherata da parametri `t` · **9.131 CORPUS ITALIANO NORMATTIVA: 43 corpora /
15.507 articoli** (da 5 / 5.180) + verificatore esteso ai 43 codici + preambolo IT
corretto (fondare sul corpus, non sulla memoria) + lista codici dinamica.
Account di test: `admin.it` (admin, AL+IT) e `avvocato.it` (avvocato IT).

## Storia versioni (sessione 20 ago 2026 — giurisdizione + lettere)
v9.154 giurisdizione armata dentro l'autenticazione (causa #1) · **9.155 il
vincolo al collo di bottiglia in `backends.complete()`** + `apply_jurisdiction`
idempotente + `tools/juris_guard.py` → audit strumenti IT da 1/14 a **14/14** ·
9.156 testo cliente: tagline al congiuntivo, **nessun nome di modello negli
asset serviti** (Fable/Opus rimossi anche da commenti HTML/CSS e identificatori
JS), cache-bust anche per style.css · 9.157 i backup `.bak-*` esclusi
dall'immagine (2.01→1.81 GB) · **9.158-9.159 Lettere e atti** (`src/letters.py`,
26 destinatari IT+AL, export .docx) + smoke 74→101 · **9.160-9.161 allegati**
(docx/doc/txt/rtf + antiword; `documents.extract_text` insegnato a leggerli —
prima li ammetteva e li perdeva in silenzio) + PDF via stampa browser + smoke 102 ·
**9.162 memoria del caso** (`src/case_brief.py`: gli strumenti PRO continuano il
lavoro del cervello invece di ricominciarlo) + allegati nei 6 strumenti che ne
erano privi (19/19) + **selezione multipla** in tutti + smoke 103 · **9.163-9.167** HTML non piu in cache (l utente girava con app.js di 3 release prima), caricamento documenti asincrono (160s -> 0,4s) con lingua corretta nel thread · **9.168-9.169 foto iPhone (HEIC)** convertite prima dell'OCR + guardia estensioni estesa a TUTTI i formati.

## Storia versioni (sessione 30-31 ago 2026 — blindatura e documenti legali)

v9.193-9.198 **sicurezza** (cervello in gabbia, SSH a chiave, freno al login,
backup cifrati, CSP, registro accessi, porte da 7 a 0) — vedi la sezione
SICUREZZA · v9.199-9.202 **pacchetto GDPR** (9 documenti in `legal/`,
accettazione tracciata al primo accesso) · **v9.203 i documenti si possono
RILEGGERE**: voce nel menu ☰ in sola lettura + **`/legale` pubblica senza
login** — prima sparivano dopo l'accettazione e chi valutava il prodotto non
poteva leggerli affatto · **v9.206 la pagina pubblica rende il markdown**
(serviva `#` e `**` crudi, e le tabelle dell'accordo come file di barre) +
**golden sezione [10]** che sorveglia i costrutti non coperti dal renderer.
QA dopo il deploy: golden **98/98** (da 59), smoke 103/103, juris verde.

## Storia versioni (sessione 28-29 ago 2026 — lavori lunghi, PWA, Dosja, Genio)
v9.170-9.174 **il lavoro sopravvive alla pagina** (`jobs.py`, `/api/ask/start` +
`/api/ask/events`): su iPhone passare a WhatsApp uccideva l'analisi con «Gabim
rrjeti» · 9.175-9.177 **PWA** installabile + **notifiche push** (`push.py`) ·
9.178 nome icona «Superavokati» + barra di stato iPhone (`black`, non
`black-translucent`) · 9.179-9.182 **Dosja**: le carte prodotte non si perdono
più chiudendo la pagina — ricerche salvate + documenti caricati, raggruppati per
fascicolo, con copia/PDF/scarico; il pulsante 🗂️ compare in ogni strumento via
MutationObserver · **9.183-9.185 Genio Legale rifatto** (memoria fra i giri,
allegati veri, 4 menti su 6 e uno alla volta, background + notifica, seconda
mente Fable quando la prima torna a mani vuote) — vedi `genio.py` nella mappa
moduli · **9.186 la graffetta nel Genio** (il pannello leggeva i documenti del
fascicolo ma non permetteva di attaccarne uno lì per lì) + tempo dichiarato
onesto (~10 min → ~20-30, misurato 37,8) · **9.187 due difetti trovati provando
dal browser**: la domanda che restava appesa in silenzio dopo un riavvio
(8 fascicoli su 71) e il Neni 114 che non veniva mai recuperato — vedi
«Ancore» sopra e `jobs.py` nella mappa moduli.
QA dopo il deploy: golden **25/25**, smoke 103/103, juris_guard verde.

## Storia versioni (sessione 6-7 ago 2026)
v9.50→9.54 piattaforma 3 professioni · 9.55 extra tool · 9.56 full-text+matching · 9.61-9.68 police laws + Super Noteri + revoca/conflitti · 9.69-9.71 Super Prokuror + hub · 9.72 Ligj i gjallë · 9.73 Pika e parë · 9.74 Fashikull · 9.75-9.76 Motore afate + golden · 9.77 fix needle empty-state · 9.78 upload in Fashikull · 9.79-9.80 Shiko të ruajturat · 9.81 fix forgot-password · 9.82 mode-bar snellite. Punto di ritorno sicuro storico: commit `1e9fb84`.

Dettaglio completo nelle memorie Claude (`~/.claude/.../memory/`): super_avokati_piattaforma, _super_prokuror, _super_noteri, _ligj_i_gjalle, _pika_e_pare, _fashikull, _afate_golden, aala_audit_backup_nginx.

## GIT / BACKUP  (config 7 ago 2026)

Il codice sta in **4 posti**: (1) VPS produzione `/var/www/apps/super-avvocato` (NON è un repo git — i deploy editano i file direttamente), (2) copia locale Mac `/Users/aldo/Desktop/multi service/Super Avocati/` (QUESTA è il repo git), (3) **GitHub `git@github.com:aala-ferrari/super-avokati.git`** (privato, branch main), (4) tarball in `_backups/`.

**Workflow per restare allineati** (dopo modifiche sul VPS):
```bash
# 1) sync VPS -> locale (codice + corpus, escludi cache/bak/app.db)
cd "/Users/aldo/Desktop/multi service/Super Avocati"
SRC=root@31.220.90.246:/var/www/apps/super-avvocato
for d in src static templates tools; do rsync -az -e ssh --exclude='__pycache__/' --exclude='*.pyc' --exclude='*.bak' --exclude='*.bak-*' "$SRC/$d/" "$d/"; done
rsync -az -e ssh "$SRC/Dockerfile" "$SRC/run.sh" "$SRC/CLAUDE.md" .
rsync -az -e ssh "$SRC/data/index/bm25.pkl" data/index/bm25.pkl        # corpus AL (12M)
rsync -az -e ssh "$SRC/data/index/bm25_it.pkl" data/index/bm25_it.pkl  # corpus IT (35M)
rsync -az -e ssh "$SRC/data/processed/it_codes.json" data/processed/   # metadata codici IT (UI)
# I JSON sorgente degli atti (data/processed/it_acts/, 21M) NON si committano:
# si rigenerano con tools/ingest_it_normattiva.py (vedi "CORPUS ITALIANO").
# 2) commit + push (dal Mac; chiave dedicata gia configurata)
git add -A && git commit -m "vX.Y: ..." && git push origin main
```

**SSH/chiavi (GOTCHA)**: una chiave SSH può stare in UN SOLO posto su GitHub (chiave-account XOR deploy-key di un repo). Il Mac usa una **chiave dedicata** `~/.ssh/id_ed25519_gh` (aggiunta come chiave-ACCOUNT di aala-ferrari); `~/.ssh/config` ha `Host github.com → IdentityFile ~/.ssh/id_ed25519_gh, IdentitiesOnly yes`. La vecchia `~/.ssh/id_ed25519` era incastrata come deploy-key del repo `aala`, per questo servì la chiave nuova. Il VPS ha una deploy-key separata (`~/.ssh/id_ed25519_aala`) per il repo AALA. `data/` NON è gitignored qui → il pickle bm25.pkl (corpus) è committato di proposito.
