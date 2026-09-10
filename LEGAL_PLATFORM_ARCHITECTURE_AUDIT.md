# LEGAL_PLATFORM_ARCHITECTURE_AUDIT

**Super Avokati / superavokati.ai** — audit richiesto dallo spec «LEGAL PLATFORM —
NEXT GENERATION UPGRADE» (§49). Prodotto **senza toccare codice**, grounded nel
repository reale (non a memoria).

- **Data**: 2026-09-10 · **versione in produzione**: v9.287
- **Metodo**: lettura diretta di `src/*.py`, schema SQLite (`storage.py`), grep
  mirati. Ogni «MANCA / PARZIALE / FATTO» qui sotto è verificato nel codice, non
  assunto (regola §48).
- **Regola di lettura**: questo documento fotografa lo stato; NON è un ordine di
  costruzione. Le regole del titolare valgono più dello spec: *precisione >
  velocità · non peggiorare il cervello · non rompere ciò che funziona · misura
  prima di aggiungere.*

> **Tesi in una riga.** La piattaforma implementa già ~60-70% dei *comportamenti*
> chiesti dallo spec (verifica, avversariale, no-absence, dossier canonico,
> cost-control, anti-injection) — perché lo spec è il superset enterprise degli
> spec-1/2 già costruiti. Il divario reale non sono «funzioni»: è che questi
> comportamenti vivono come **logica live per-domanda**, non come **livello DATI
> persistente, versionato e condiviso**. Quel livello è lavoro da mesi e, per il
> contesto attuale (SQLite, un processo waitress, abbonamento condiviso, avvocati
> AL/IT, pre-lancio), è in gran parte prematuro. Il 20% che vale davvero adesso è
> piccolo e preciso (vedi Q).

---

## A. CURRENT ARCHITECTURE

- **Front-end**: Flask (`src/web.py`, ~9.4k righe, 199 rotte) servito da
  **waitress** su `127.0.0.1:5050`, dietro nginx (`superavokati.ai`). Vincolo
  scolpito: **UN processo** (jobs/parcheggio/battiti SSE vivono in memoria),
  thread generosi (`WEB_THREADS=32`).
- **Persistenza**: **SQLite** `data/app.db` (WAL + busy_timeout) — ~44 tabelle.
  Postgres `legalkb` (precedenti) esiste ma **spesso irraggiungibile dal
  container** → si ripiega sul pickle locale.
- **Corpus normativo**: due indici BM25 SEPARATI in pickle (volume montato):
  **AL** `bm25.pkl` (21 codici / 6.061 nene), **IT** `bm25_it.pkl`
  (43 corpora / 15.507 articoli). Fix corpus vivono nel PICKLE, non nel sorgente.
- **Giurisprudenza**: AL pickle `bm25_decisions.pkl` (1.407) + IT **FTS5 su disco**
  (846). NON in SQLite.
- **Cervello**: backend = **`claude` CLI headless** in subprocess
  (`src/backends.py`), interno «Tetramorph». Opus 5 max (senior), Sonnet 5 high
  (junior), Fable 5.1 max (red team). **Collo di bottiglia unico**:
  `backends.complete()/complete_stream()` — vi passano giurisdizione + lingua.
- **Deploy**: Docker image `super-avvocato:vX.Y`, `run.sh`, `/opt/docker-prune.sh`,
  QA trio (golden 402 / smoke 103 / juris 16) + prove vive SSE/LINGUA/Skuadra.
- **Sicurezza**: cervello in gabbia (niente `Read` su codice/DB), CSP, SSH a
  chiave, backup cifrati, 0 porte esposte, difesa prompt-injection.

## B. CURRENT DATABASE MODEL (~44 tabelle SQLite)

Raggruppate per dominio (nome reale → ruolo):

- **Identità / studio**: `users` (is_admin, jurisdiction entitlement),
  `firms` (owner_id), `firm_members` (role owner|partner|lawyer|paralegal|
  assistant), `case_assignments` (role_in_case lead|collaborator|reviewer|
  observer).
- **Fascicolo**: `cases` (jurisdiction AL/IT, firm_id, answer_system_version),
  `case_parties`, `client_contacts`, `case_status_updates`, `case_drafts`,
  `case_research`, `case_timelines`, `case_workflows`, `case_lessons`,
  `case_alerts`.
- **Conversazione / risposta**: `messages` (articles_json, citations_json),
  `provenance_packs` (**kb_version** = hash KB al retrieval, **system_prompt_version**),
  `citation_audits`.
- **Documenti**: `documents` (sha256, extracted_text, ocr_status), `drafted_acts`,
  `contract_reviews`, `auto_letters`, `hearing_notes`.
- **Strumenti PRO (output)**: `stress_tests`, `adversarial_loops`,
  `strategy_compasses`, `settlement_simulations`, `genio_briefs`,
  `precedent_briefs`, `corporate_extractions`, `bench_memos`, `agent_suggestions`.
- **Agenda / studio-gestione**: `events`, `reminders`, `time_entries`, `invoices`,
  `firm_clauses`, `firm_inspections`.
- **Compliance / audit**: `ai_audit_log` (model, cost_micro_usd, token, callsite,
  outcome, kb_version), `case_access_log`, `legal_acceptances`, `leads`,
  `push_subscriptions`, `legal_updates`.

**Osservazione chiave**: molte tabelle che §50 «chiede» esistono già con altro
nome. Mancano davvero solo le tabelle del **livello fonte tipizzato/versionato**
(vedi T).

## C. CURRENT AI FLOW

```
DOMANDA
  └─ triage (Sonnet) → simple | complex   (force_complex via deep:true)
     ├─ SIMPLE:  raccoglitori paralleli (web+QBZ) + Kërkuesi → dossier → senior (1 giro)
     └─ COMPLEX: 9-11 fasi «war-room» (_run_stages) → compose →
                 [⚡ Fable] research loop → Avokati i djallit multi-round
                 (V1→Fable→V2→gate→Fable#2→V3) → [⚡] Source Verifier
  └─ scudo citazioni (nene + numeri sentenza) + provenance pack → messages
```

- Senior **Opus 5 max** = default sacro; **Fable 5.1 max** solo su `mendja=fable`
  (pulsante ⚡). Junior a effort **high**, red team Fable **max**.
- Lavori lunghi in background (`jobs.py`, `/api/ask/start` + `/events`
  riattaccabile), notifica push a fine.

## D. CURRENT RETRIEVAL FLOW

```
QUERY → triage (search_queries con TERMINI DEL CODICE)
      → BM25 (bm25.pkl | bm25_it.pkl)
      → + ANCORE per titolo (la regola generale che BM25 non trova, se BM25>0)
      → + heading_scan (stem 5-char, diacritic-fold)
      → taglio TOP_K → Kërkuesi (cerca la norma che DEFINISCE l'istituto)
      → [⚡] research loop (gap-detector → ricerca la norma mancante)
```

- **Solo BM25, per scelta** (documentato in `retrieval.py`: «Claude gestisce il
  layer semantico sopra»). **Nessun embedding / vector / reranker.**
- Le **ancore** e l'heading-scan sono le cicatrici della cecità morfologica di
  BM25 (niente stemming): rattoppi strutturali misurati, non un layer semantico.
- Precedenti: query-expansion LLM + BM25/FTS5 (`precedent.py`), non vettoriale.

## E. CURRENT SOURCE MODEL

- **Norma** = `Article` (code, number, title_sq, body, area, pjesa/kreu/seksioni,
  **repealed**, **volatility** STABLE/MEDIUM, **last_amendment_date**). Nel pickle.
- **NESSUNA versione storica del testo** (`valid_from/valid_to/law_versions`
  assenti — verificato). Solo flag «abrogato / volatilità / data ultimo
  emendamento».
- **Verifica**: `citation_verifier` (nene: verified/fake/repealed/needs_code +
  freschezza) · `case_citation_verifier` (numeri sentenza: verified/unverified/
  fake, con **regola di copertura**: «non trovato ≠ falso») · `war_room`
  (DossierItem tipizzato con `cilesia` PRIMARY/AUTHORITATIVE/SECONDARY +
  `verifikimi` VERIFIED/PARTIAL + Source Verifier).
- **Verifica live, non persistente**: Agent C (QBZ vigenza) e Agent D (Fletorja
  Zyrtare, ultima modifica) girano **per-domanda**; l'esito NON è salvato come
  stato-fonte riusabile.
- **Provenienza**: `provenance_packs` conserva **hash KB** + **hash system prompt**
  al momento della risposta.

## F. CURRENT MATTER MODEL

- `cases` è il fascicolo (giurisdizione ereditata dalla sessione). Attorno:
  `case_parties`, `documents`, `events`, `case_research`, `drafted_acts`,
  `case_timelines`, `case_status_updates`.
- **`case_brief.py`** assembla un «contesto del caso» (fatti, ultima analisi,
  blocchi strutturati, documenti, ricerche salvate) con **budget per sezione**,
  marcato SFONDO, iniettato in ~12 punti (`web._with_case`) → gli strumenti PRO
  continuano il lavoro del cervello invece di ricominciare.
- **Non** è ancora un oggetto MATTER unico con FACTS/EVIDENCE/ARGUMENTS come
  entità strutturate: è un **assemblaggio a runtime** da tabelle esistenti.

## G. CURRENT PERMISSION MODEL

- **Ruoli reali** (meglio di quanto sembrasse): `FIRM_ROLES` =
  owner|partner|lawyer|paralegal|assistant + `ROLE_LABELS` + **matrice di
  capacità** (booleans per capability, `storage.py`); `case_assignments.role_in_case`
  = lead|collaborator|reviewer|observer; `users.is_admin`.
- **auth.py**: `current_role()`, `get_user_role_in_firm()`, entitlement di
  giurisdizione armato in `_arm_request_jurisdiction`.
- **Isolamento tra studi**: solido — cross-tenant → 404 (4 attacchi IDOR, 4
  bloccati). Registro accessi agganciato a `_resolve_case` (un aggancio, non 60).
- **Gap reali**: (a) enforcement **PRIMA del retrieval** per muri etici (§26)
  non c'è; (b) la matrice di capacità non copre tutte le azioni AI granulari
  dello spec (run_ai/view_ai_runs/export…) in modo uniforme.

## H. CURRENT GENIO ARCHITECTURE

- `genio.py` (~755 righe): **sistema SEPARATO**, 6 lenti in parallelo
  (riframing, kill_shot, leverage, decision_tree, brutal_truth, voice),
  memoria fra i giri, allegati veri, background+notifica, **seconda mente Fable**
  quando una lente torna vuota. Semaforo dedicato (1 Genio alla volta).
- **NON** è una view del War Room (lo spec §15 lo vorrebbe): condivide il
  `case_brief` ma ha pipeline e prompt propri.

## I. CURRENT WAR ROOM ARCHITECTURE

- `studio.py` (raccoglitori A/B/C/D, senior_pergjigjja, sulmi_i_dyte, duhet_raund2)
  + innesti in `brain.py` + `war_room.py` (dossier canonico tipizzato, Source
  Verifier, research loop). Pipeline completa e provata dal vivo (v9.287).
- Additivo, gated su ⚡ (Fable), fail-silent, **mai auto-ingest**. È già il motore
  strategico centrale del percorso complesso (§14) — da NON riscrivere.

## J. DUPLICATED SYSTEMS

- **Due verificatori di citazioni** (`citation_verifier` nene / `case_citation_verifier`
  sentenze): **intenzionale**, non duplicazione (corpus completo vs incompleto).
- **Due scudi citazioni**: il percorso chat ha una copia sua in `_ask_prepare`,
  i 19 strumenti passano da `_scudo_citazioni` — agganciati entrambi di proposito
  (v9.191). Da tenere sotto golden.
- **Genio ⟷ War Room**: sovrapposizione concettuale (entrambi «trovano leve»),
  pipeline separate (§15). Candidato a consolidamento *logico*, non urgente.
- **30 file `.bak*` in `src/`** sul filesystem — **0 tracciati da git**, esclusi
  dall'immagine: cruft di lavorazione, non debito di codice. Igiene, non rischio.

## K. MAJOR TECHNICAL DEBT

- `web.py` **9.4k righe** / `storage.py` 6.7k / `brain.py` 6.3k: moduli monolitici.
  Rischio di attrito futuro, non un bug.
- **Stato in memoria** (jobs/parcheggio/battiti): un deploy li perde — vincolo
  architetturale del processo-unico, mitigato ma intrinseco.
- **Corpus nel pickle**: i fix non stanno nel sorgente; un re-parse da zero li
  perde (documentato, procedura obbligata `load→append→build→chown`).
- **Precedenti solo nel pickle** (AL): mai `build_and_save_decisions` dal
  container (Postgres irraggiungibile → cancellerebbe 813 precedenti).

## L. LEGAL RELIABILITY RISKS

1. **Versioning temporale assente (il più importante)**: si serve il testo di
   OGGI. Mitigato *live* da Agent C/D («oggi ≠ applicabile ai fatti») ma **non
   garantito**: se il gatherer non torna, il senior non ha la versione storica.
2. **Afati calcolati dall'LLM** (`afati.py`/`deadlines.py` → `backend.complete`):
   una data processuale sbagliata = decadenza = malpractice. Nessun motore
   deterministico di date.
3. **Giurisprudenza incompleta** (1.407 AL + 846 IT su molte di più): mitigato
   dalla **regola di copertura** (timbra solo (corte, anno) chiusi) — corretto,
   ma la copertura resta parziale.
4. **BM25 morfologico**: recall a rischio su formulazioni diverse dalla legge;
   mitigato da ancore/heading-scan, non risolto alla radice.

## M. SECURITY RISKS

- **Documenti in chiaro a riposo** (scelta ragionata: accessi stretti + backup
  cifrati; la via realistica di fuga è già cifrata). Residuo: chi diventa root.
- **Passphrase chiavi SSH**: a carico dell'utente. **2FA assente.**
- **Muri etici (§26) assenti**: un membro dello studio con accesso vede tutti i
  fascicoli dello studio; nessun blocco per conflitto d'interesse *pre-retrieval*.
- Positivi forti: cervello in gabbia, CSP, porte 0, freno login, prompt-injection.

## N. DATA INTEGRITY RISKS

- Stato volatile in memoria (sopra).
- **Nessun content-hash/diff sistematico sulle FONTI normative** (sì sui
  documenti caricati). Il watcher GJK fa diff-URL ma non è generalizzato a QBZ/
  Normattiva con versioning.
- **Nessuna immutabilità** su output ad alto rischio (atti generati): esistono
  `drafted_acts`/`case_drafts` ma senza catena di versioni con confronto.

## O. RECOMMENDED TARGET ARCHITECTURE

**NON una riscrittura.** Un **Legal Source Layer** incrementale, additivo sopra
l'esistente, che diventi la *single source of truth* SOLO dove porta valore:

1. **Vocabolario stati-fonte UNICO** (§5) condiviso da tutti i verificatori —
   la fondazione a costo basso che rende coerente tutto il resto.
2. **Motore afati deterministico** (§13): l'LLM sceglie la regola, Python calcola
   la data (feriali/solari, sospensioni), passi mostrati.
3. **Tabelle `legal_sources` + `source_versions` + `content_hash`** (§2/§4) —
   introdotte **solo quando arriva il dato** (una fonte alla volta), mai come Big
   Bang; il testo storico si aggiunge dove esiste, il resto resta flag+warning.
4. **Eval harness + golden cases legali** (§37-40): misurare l'accuratezza vera,
   non solo il verde strutturale. Bottleneck = etichettatura umana.
5. Tutto il resto (knowledge graph pieno, fact/evidence graph, permessi
   enterprise, ethical walls, observability) resta **NORD**: si fa a scala, per
   fette, guidato dalla domanda reale del mercato.

## P. MIGRATION PLAN (incrementale, ogni fase additiva + golden come cancello)

- **Fase 0 — Fondazione a costo basso**: (1) vocabolario stati unico, (2)
  esporli in UI (§45), (3) afati deterministici. *Nessuna nuova tabella pesante.*
- **Fase 1 — Fonte tipizzata**: `legal_sources`/`source_versions`/`content_hash`
  per **una** fonte pilota (es. i codici IT da Normattiva), diff in background,
  **mai auto-ingest**. Retrieval invariato; il layer è solo verifica/tracciabilità.
- **Fase 2 — Qualità misurata**: eval harness + 10-20 golden cases verificati da
  un avvocato → metriche (recall statuti, hallucinated-authority-rate); regression
  che **blocca il deploy** se peggiora.
- **Fase 3+ — Nord su domanda**: versioning storico esteso, fact/evidence graph,
  Genio come view, permessi granulari, ethical walls. Solo se e quando serve.

Per ogni fase: *files changed · migrations · backward-compat · rischi · test ·
rollback · done-criteria* si dettagliano al momento del via, non prima.

## Q. PRIORITY MATRIX (valore × costo)

| | **Costo basso (S/M)** | **Costo alto (L/XL)** |
|---|---|---|
| **Valore ALTO** | ⭐ §13 afati deterministici · §5 stati unici · §18 bande UI · §37-40 eval (start piccolo) | §1-2 knowledge graph + versioning storico (blocco = DATI) · §19-20 case-law strutturata |
| **Valore MEDIO** | §45 sorgente cliccabile · §29 registro prompt · §34 freshness per-fonte | §11-12 fact/evidence graph · §6 layer semantico (da MISURARE) |
| **Valore BASSO ora** | §46 «WHY» drill-down | §25 permessi granulari · §26 ethical walls · §28 AI-run-trace · §30 adapter · §36 · §42 dashboard |

## R. ESTIMATED COMPLEXITY

- **S** (giorni): §5 stati unici, §18 bande, §45 badge cliccabile, §29 registro.
- **M** (1-2 settimane): §13 afati deterministici, eval harness (impalcatura).
- **L** (settimane-mese): §1 grafo (incrementale), §11-12 graph, §6 semantico+misura.
- **XL** (mesi + acquisizione dati): §2 versioning storico completo, §19-20
  relazioni giurisprudenza, §25-26 enterprise, §37-40 con 200-500 golden case.

## S. FILES / MODULES TO MODIFY (per la Fase 0-1 consigliata)

- §5 stati: `war_room.py`, `citation_verifier.py`, `case_citation_verifier.py`,
  `studio.py` (un modulo nuovo `source_status.py` con l'enum condiviso).
- §13 afati: **nuovo** `deadline_engine.py` (matematica pura, testabile) +
  `afati.py`/`deadlines.py` (l'LLM sceglie la regola, chiama il motore).
- §18 bande: `settlement.py` (già scenario-based) + `static/app.js`
  (`renderSettlement`) + i18n.
- §45 UI: `static/app.js` (`renderCitationsBadge`) + endpoint dettaglio-fonte.
- Eval: **nuovo** `tools/legal_eval.py` + `tests/golden_cases/` (dati).

## T. NEW TABLES / SCHEMAS REQUIRED (solo quando la fase lo richiede)

- **Fase 1**: `legal_sources` (source_id, url, source_type, retrieved_at,
  content_hash, previous_hash), `source_versions` (article_id, version, text,
  valid_from, valid_to, content_hash, official_ref).
- **Fase 3+ (nord)**: `source_relations` (amended_by/cross_ref/interprets),
  `deadline_rules`, `prompt_versions`, `claims`+`claim_sources` (evoluzione di
  `provenance_packs`), `case_law`+`case_passages` (portare i precedenti in
  relazionale, oggi in pickle/FTS5).
- **NON** creare tabelle inutili: `matters`≈`cases`, `parties`≈`case_parties`,
  `ai_runs`≈`ai_audit_log`, `strategies`≈`strategy_compasses` esistono già.

---

## MAPPA SEZIONE-PER-SEZIONE (1-53)

Legenda stato: ✅ FATTO · 🟨 PARZIALE · ⬜ MANCA. Costo: S/M/L/XL.

| § | Tema | Stato | Dove / nota | Costo per completare |
|---|---|---|---|---|
| 1 | Knowledge Graph | ⬜ | nessuna tabella relazioni; `Article` piatto nel pickle | L-XL |
| 2 | Temporal versioning | 🟨 | flag repealed/volatility/last_amendment; **niente versioni storiche**; live via Agent C/D | XL (dato) |
| 3 | QBZ + Fletorja verification | 🟨 | Agent C/D **live per-query**; non persistito come stato-fonte | M |
| 4 | Source immutability + hash | 🟨 | sha256 sui **documenti**; **non** sulle norme; provenance ha kb_version | M |
| 5 | Source status standard | 🟨 | stati esistono **sparsi**; da unificare | **S** ⭐ |
| 6 | Hybrid retrieval | 🟨 | **solo BM25** per scelta + ancore/heading; niente vector/reranker | L (misurare) |
| 7 | Exact passage retrieval | 🟨 | articolo intero; snippet solo per sentenze; no offset | M |
| 8 | Authority ranking | 🟨 | `cilesia` in war_room; non score separati combinati | M |
| 9 | Claim → Source | 🟨 | provenance_packs + citation_verifier; no CLAIM_ID formale | M |
| 10 | Canonical dossier | 🟨 | `war_room.build_canonical` (in-memory) + `case_brief` | M |
| 11 | Fact/Evidence graph | ⬜ | contraddizioni/gap sì; grafo strutturato no | L |
| 12 | Event timeline engine | 🟨 | `case_timelines`/`build_case_timeline`; no date_precision/confidence | M |
| 13 | Deadline engine | 🟨 | **LLM calcola la data**; niente matematica deterministica | **M** ⭐ |
| 14 | War Room integration | ✅ | pipeline completa v9.287 — NON riscrivere | — |
| 15 | Genio come view | ⬜ | `genio.py` separato (scelta) | L |
| 16 | Red Team | ✅ | Avokati i djallit (Fable), passa dallo scudo | — |
| 17 | Bench Memo | ✅ | `bench_memo.py` + tabella | — |
| 18 | Numeric probability safety | 🟨 | `settlement.py` **già scenario-based e onesto**; manca labeling UI a bande | **S** ⭐ |
| 19 | Case Law engine | 🟨 | precedenti in pickle/FTS5; no relazioni struct | L |
| 20 | Precedent pattern | 🟨 | funzione esiste; poco dato strutturato | M |
| 21 | Drafting engine | 🟨 | Fabrika/`drafted_acts`; riceve case_brief; no NEW_SOURCE_REQUEST formale | M |
| 22 | Contract review | 🟨 | `contract_reviews` + semaforo; segmentazione clausole da rafforzare | M |
| 23 | Document ingestion | ✅ | sha256, originale immutabile, testo separato, OCR | — |
| 24 | Document versioning | ⬜ | `case_drafts` senza catena versioni/compare | M |
| 25 | Matter permissions | 🟨 | **ruoli + capability matrix ESISTONO**; granularità azioni AI parziale | M |
| 26 | Ethical walls | ⬜ | isolamento studio sì; muri intra-studio no | L |
| 27 | Audit log immutabile | ✅ | ai_audit_log + case_access_log + legal_acceptances (AI Act art.12) | — |
| 28 | AI run trace | 🟨 | model/cost/token/callsite/kb_version; no dossier_version/source_ids | M |
| 29 | Prompt versioning | 🟨 | **system_prompt_version (hash) già nel provenance**; no registro attivo | S |
| 30 | Model adapter | 🟨 | `backends.py` astratto ma Claude-CLI-centrico | M |
| 31 | Structured output | 🟨 | DossierItem, parse_gaps, Kërkuesi JSON, devil struttur.; in crescita | M |
| 32 | Citation verify gate | ✅ | Source Verifier + 2 verificatori; veto su citazione non strategia | — |
| 33 | No evidence ≠ absence | ✅ | «MOSGJETJA NUK ËSHTË MUNGESË» + regola di copertura, golden-guarded | — |
| 34 | Source freshness | 🟨 | volatility/stale + living_law; no LAST_CHECKED per-fonte | M |
| 35 | Background update | 🟨 | cron harvester giurcost/GA/GJK; **mai auto-ingest** (scelta) | M |
| 36 | High-impact change | ⬜ | richiede grafo + link matter | L |
| 37 | Evaluation framework | ⬜ | golden/smoke = **strutturali**, non accuratezza legale | **M-L** ⭐ |
| 38 | Regression tests | 🟨 | golden 402 blocca su struttura; non su metriche legali | M |
| 39 | Golden cases | ⬜ | serve etichettatura avvocato (bottleneck umano) | L (umano) |
| 40 | Hallucination suite | 🟨 | verificatori + alcuni golden; non suite dedicata | M |
| 41 | Prompt injection defense | ✅ | forte e diffusa (contenuto = DATA, SFONDO, allegati isolati) | — |
| 42 | Observability | 🟨 | consumo + monitor 12 controlli; no dashboard tecnica retrieval | M |
| 43 | Cost control | ✅ | «il compito sceglie il modello» + budget caps | — |
| 44 | Human review gate | 🟨 | tutto «assistivo» (regola); no flag HUMAN_REVIEW_REQUIRED per tipo | S |
| 45 | UI source transparency | 🟨 | badge verified/fake + provenance persistito; dettaglio profondo no | S |
| 46 | UI case trace WHY | ⬜ | drill-down conclusione→fonte assente | M |
| 47 | Implementation priority | — | (meta) — vedi P/Q | — |
| 48 | Analyze before change | ✅ | **questo documento** | — |
| 49 | Audit doc first | ✅ | **questo documento** | — |
| 50 | Database target | 🟨 | ~44 tabelle già coprono gran parte; mancano solo quelle-fonte | vedi T |
| 51 | End state | 🟨 | il flusso esiste per l'80%; mancano versioning storico + graph | — |
| 52 | Ultimate quality rule | ✅ | è già la filosofia del prodotto (fonte>testo, no-absence, red team) | — |
| 53 | Final instruction | ✅ | audit→target→migrazione incrementale, niente riscrittura | — |

---

## RACCOMANDAZIONE FINALE

**Non costruire tutto.** Il valore reale, subito, è la **Fase 0** della sezione P
(§5 stati unici + §13 afati deterministici + §18 bande UI): alto valore, costo
S-M, **non tocca il cervello sacro**, tutto sotto golden. La **Fase 2** (eval con
golden cases) è la più importante per la qualità legale, ma il collo di bottiglia
è **umano** (etichettatura da avvocato), quindi parte piccola.

Il resto — knowledge graph, versioning storico completo, enterprise, ethical
walls — è **NORD legittimo ma prematuro** per SQLite/un-processo/pre-lancio.
Si fa a fette, guidato dalla domanda reale, misurando prima di aggiungere.

> *Il prodotto non vince perché genera più testo (§52). Vince perché trova la
> fonte giusta, la versione giusta, l'eccezione, il precedente contrario, il
> difetto procedurale — e mostra da dove viene ogni conclusione. Su questo siamo
> già impostati; il resto è profondità, non direzione.*
