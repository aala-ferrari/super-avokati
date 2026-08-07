# Super Avvocato — istruzioni di progetto

Strumento AI per avvocati shqiptar (B2B). Front-end Flask su porta 5050,
SQLite (`data/app.db`) + Postgres `legalkb` per i casi giurisprudenziali,
BM25 retrieval sopra 6061 nene (21 codici) + 1258 precedenti (Kushtetuese+Gjykata e Lartë+CEDU).

## Regola #1 — Scope: SOLO LEGGE ALBANESE

Tutto il corpus è albanese: 21 fonti normative (Kushtetuta + codici +
5 ligji settoriali = 5615 nene), 282 vendime Gjykata Kushtetuese
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
- **Schema `cases.jurisdiction` AL/IT/EU (V8.13):** è predisposizione
  futura. Oggi il KB è solo AL — non comportarsi come se IT/EU fosse
  attivo.

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

Quando aggiungi un nuovo system prompt fuori `brain.py`/`genio.py`,
attaccaci esplicitamente il guard — non confidare che basti
`ALBANIAN_LANGUAGE_RULES`.

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

- Risposte all'utente: shqip (albanese).
- Conversazione con Romeo: italiano informale ("fratello").

---

# PRODUZIONE — VPS, DEPLOY, BUILD  (aggiornato 7 ago 2026, v9.82)

Numeri attuali: **6061 nene · 21 codici · 1258 precedenti** (pickle vivo). Corpus cresciuto da 5615 (18 codici) aggiungendo: Kodi Civil +2, Familjes +4, Konsumatorët +3, Ligji Policia 108/2014 (135), Rregullore Policia VKM 750/2015 (255), Ligj Policia 82/2024 (143, ATTUALE). Dedup Zgjedhor -96.

## Dove gira
- **VPS**: `root@31.220.90.246` (SSH dal Mac senza password). App in `/var/www/apps/super-avvocato`.
- **Container Docker** `super-avvocato`, image `super-avvocato:vX.Y` (attuale **v9.82**). Flask su `127.0.0.1:5050`; nginx `superavokati.ai` → 5050.
- **Volumi**: `-v /var/www/apps/super-avvocato/data:/app/data` (SQLite `app.db` + BM25 `index/bm25.pkl` — PERSISTONO tra recreate); `-v /opt/claude-creds:/home/avvocato/.claude` (credenziali del backend).
- **Cervello**: backend = **`claude` CLI headless** in subprocess (`src/backends.py`), name interno "Tetramorph". Opus 4.8 effort=max default; `medium=True`→Sonnet; `fast=True`→Sonnet senza web. **Il backend Opus (non-fast) ha WebSearch/WebFetch ABILITATI** (`backends.py:280`) — usato da Ligj i gjallë per il check legge live. `BRAIN_PARALLEL_WORKERS=6` (fasi in parallelo).

## Deploy / build (procedura usata ~25 volte)
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
docker exec super-avvocato python3 tools/smoke_test.py     # 68 tool chiamati con cervello STUBBATO (no LLM): firma/parsing/logica. Baseline 68/68.
```
Estendere GOLDENS/smoke quando emerge un bug nuovo.

## Mappa feature / moduli (src/)
- **expertise.py** — Modele Ekspertize (8 template, incl. abuzim_policor "due menti"). `retrieve_grounded` (seed + `_expand_terms` LLM + `_heading_scan` stem 5-char diacritic-fold + BM25). Riusato da prosecutor/notary/deadlines/afati.
- **prosecutor.py** — Super Prokuror: analyze, draft_indictment, investigation_plan, investigative_act(kind), coercive_measure, dismissal_request, stress_test + cittadino (citizen_complaint, victim_rights, dismissal_appeal, delay_complaint). Assistivo, mai auto-accusa (EU AI Act).
- **notary.py** — Super Noteri: DEED_TYPES (20), PROKURA_SCOPES (16 tagra), DECLARATION_TYPES (6), draft_deed/prokura/declaration, check_deed, succession, documents_needed, draft_revocation, check_conflicts.
- **living_law.py** — Ligj i gjallë: verify_claims (verifica frase↔testo reale nen), check_law_live (web→QBZ). + freschezza in citation_verifier (volatility/stale).
- **intake.py** — Pika e parë: triage(story) → orientamento + urgenza + ROUTE token → instrada allo strumento.
- **afati.py** — Motore afate: TRIGGERS (8) → scadenze grounded + blocco `AFAT | titolo | YYYY-MM-DD` → calendario (POST /api/events).
- **vault.py** — Fashikull: build_context(case_id), ask (Q&A [Dok N]), find_needle, who_said_what. **pro_features.py** build_case_timeline (events/contradictions/gaps).
- **citation_verifier.py** — Verifikuar (verified/fake/repealed/needs_code + volatility/stale). **deadlines.py** prescrizione.
- **second_opinion/adversary/fable_drafter.py** — tool Fable (model_override="fable").
- **web.py** — endpoint (199 rotte). UI: `static/app.js` (hub `_openHub` nel menu PRO: Super Prokurori/Super Noteri/Ligj i gjallë; mode-bar snellite che puntano ai hub; `openFascikull`, `openIntake`, `openAfati`, `openSavedResearch`). `templates/index.html` menu PRO.

## Regole ferree (customer-facing)
- Errori customer-facing MAI nominano il modello → sempre "Tetramorph"/generico.
- Tutto **assistivo**: il professionista verifica e firma; niente auto-accusa/archiviazione/scadenze cieche.
- **Grounding sempre**: i nene vengono dal corpus, MAI dalla memoria del modello. Precisione > velocità (Opus max, anche 4 min ok).
- Super Avokati ha auth propria (login_required_api); utenti creati da admin o auto-provisionati da AALA (`/api/provision-demo`, secret-guarded).

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
rsync -az -e ssh "$SRC/data/index/bm25.pkl" data/index/bm25.pkl   # corpus (12M, committato)
# 2) commit + push (dal Mac; chiave dedicata gia configurata)
git add -A && git commit -m "vX.Y: ..." && git push origin main
```

**SSH/chiavi (GOTCHA)**: una chiave SSH può stare in UN SOLO posto su GitHub (chiave-account XOR deploy-key di un repo). Il Mac usa una **chiave dedicata** `~/.ssh/id_ed25519_gh` (aggiunta come chiave-ACCOUNT di aala-ferrari); `~/.ssh/config` ha `Host github.com → IdentityFile ~/.ssh/id_ed25519_gh, IdentitiesOnly yes`. La vecchia `~/.ssh/id_ed25519` era incastrata come deploy-key del repo `aala`, per questo servì la chiave nuova. Il VPS ha una deploy-key separata (`~/.ssh/id_ed25519_aala`) per il repo AALA. `data/` NON è gitignored qui → il pickle bm25.pkl (corpus) è committato di proposito.
