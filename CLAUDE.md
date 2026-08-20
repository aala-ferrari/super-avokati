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

4. **Giurisdizione al collo di bottiglia (v9.155)** — il vincolo di
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
- Le etichette che arrivano dalle API (tipi atto, poteri procura, template
  perizia, clausole obbligatorie…) passano da `t()` con una mappa AL→IT nel
  dizionario (~340 voci).

---

# PRODUZIONE — VPS, DEPLOY, BUILD  (aggiornato 7 ago 2026, v9.82)

Numeri attuali: **6061 nene · 21 codici · 1258 precedenti** (pickle vivo). Corpus cresciuto da 5615 (18 codici) aggiungendo: Kodi Civil +2, Familjes +4, Konsumatorët +3, Ligji Policia 108/2014 (135), Rregullore Policia VKM 750/2015 (255), Ligj Policia 82/2024 (143, ATTUALE). Dedup Zgjedhor -96.

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

## Fix corpus (GOTCHA importante)
I fix agli articoli vivono nel **PICKLE `data/index/bm25.pkl`** (volume montato), NON nel sorgente. Per aggiungere/correggere articoli: script python che fa `ArticleIndex.load()` → append `Article(...)` → `ArticleIndex.build(arts).save()` → `chown 1000:1000 data/index/bm25.pkl` → `docker restart super-avvocato`. Un re-parse da zero PERDE questi fix. Article ha campi: code, title_sq, area, number, heading, body, pjesa, kreu, seksioni, repealed, volatility (STABLE/MEDIUM), last_amendment_date.

## Patch UTF-8 (GOTCHA)
Le patch a file con ë/ç/emoji: SEMPRE via file `.py` scp'd sul VPS (`scp patch.py root@…:/tmp/ && python3 /tmp/patch.py`), MAI heredoc SSH inline (mangia UTF-8/`\n`). Anchor precisi + `assert old in s and s.count(old)==1`.

## QA — rete di sicurezza (lanciare dopo ogni build)
```bash
docker exec super-avvocato python3 tools/golden_check.py   # 19 check deterministici: corpus + Verifikuar + heading-scan. Baseline 19/19.
docker exec super-avvocato python3 tools/smoke_test.py     # 101 tool chiamati con cervello STUBBATO (no LLM): firma/parsing/logica. Baseline 101/101.
docker exec super-avvocato python3 tools/juris_guard.py    # 16 check strutturali sulla giurisdizione. Baseline 16/16.
```
Estendere GOLDENS/smoke quando emerge un bug nuovo.

**Con il cervello vero** (lento, ~40 min, ma è l'unico che vede la lingua
delle risposte): `tools/audit_tools_it.py` chiama i 14 strumenti in sessione
IT e per ciascuno conta albanese / diritto AL / diritto IT. Baseline **14/14**.
Da rilanciare dopo ogni modifica alla giurisdizione.

## Mappa feature / moduli (src/)
- **expertise.py** — Modele Ekspertize (8 template, incl. abuzim_policor "due menti"). `retrieve_grounded` (seed + `_expand_terms` LLM + `_heading_scan` stem 5-char diacritic-fold + BM25). Riusato da prosecutor/notary/deadlines/afati.
- **prosecutor.py** — Super Prokuror: analyze, draft_indictment, investigation_plan, investigative_act(kind), coercive_measure, dismissal_request, stress_test + cittadino (citizen_complaint, victim_rights, dismissal_appeal, delay_complaint). Assistivo, mai auto-accusa (EU AI Act).
- **notary.py** — Super Noteri: DEED_TYPES (20), PROKURA_SCOPES (16 tagra), DECLARATION_TYPES (6), draft_deed/prokura/declaration, check_deed, succession, documents_needed, draft_revocation, check_conflicts.
- **living_law.py** — Ligj i gjallë: verify_claims (verifica frase↔testo reale nen), check_law_live (web→QBZ). + freschezza in citation_verifier (volatility/stale).
- **intake.py** — Pika e parë: triage(story) → orientamento + urgenza + ROUTE token → instrada allo strumento.
- **afati.py** — Motore afate: TRIGGERS (8) → scadenze grounded + blocco `AFAT | titolo | YYYY-MM-DD` → calendario (POST /api/events).
- **vault.py** — Fashikull: build_context(case_id), ask (Q&A [Dok N]), find_needle, who_said_what. **pro_features.py** build_case_timeline (events/contradictions/gaps).
- **citation_verifier.py** — Verifikuar (verified/fake/repealed/needs_code + volatility/stale). **deadlines.py** prescrizione.
- **letters.py** — Letra dhe shkresa: lettere/PEC pronte da inviare, radicate
  nel **fascicolo** (`vault.build_context`) e negli articoli **recuperati**
  (`expertise.retrieve_grounded`). Cataloghi separati per giurisdizione
  (**14 IT / 12 AL**): destinatario, canale, elementi obbligatori, seed.
  Tre famiglie — `CLAIM` (controparte), `REPORT` (autorità), `REQUEST` (PA) —
  con **divieto duro di mescolarle**: minacciare una denuncia per ottenere
  pagamento è estorsione, e il prompt lo vieta esplicitamente (annunciare le
  vie legali resta lecito). `letter_body()` isola la sola lettera per il
  .docx, scartando le note al collega. Export via `pro_features.render_act_docx`.
- **second_opinion/adversary/fable_drafter.py** — tool Fable (model_override="fable").
- **web.py** — endpoint (199 rotte). UI: `static/app.js` (hub `_openHub` nel menu PRO: Super Prokurori/Super Noteri/Ligj i gjallë; mode-bar snellite che puntano ai hub; `openFascikull`, `openIntake`, `openAfati`, `openSavedResearch`). `templates/index.html` menu PRO.

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
26 destinatari IT+AL, export .docx) + smoke 74→101.

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
