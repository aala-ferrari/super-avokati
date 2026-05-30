# Super Avvocato — istruzioni di progetto

Strumento AI per avvocati shqiptar (B2B). Front-end Flask su porta 5050,
SQLite (`data/app.db`) + Postgres `legalkb` per i casi giurisprudenziali,
BM25 retrieval sopra 5615 nene + 282 vendime Kushtetuese.

## Regola #1 — Scope: SOLO LEGGE ALBANESE

Tutto il corpus è albanese: 18 fonti normative (Kushtetuta + 13 codici +
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
