# Super Avvocato AI 🇦🇱

**Asistent ligjor falas për qytetarët shqiptarë** — free legal assistant for
Albanian citizens.

An AI lawyer that reads your facts, the official Albanian codes, **and 813
real court decisions**, and gives you a concrete answer — not a generic
summary of the law. Humanitarian mission: access to justice for everyone,
regardless of income.

## What it knows

**Statutes** — 13 official legal documents, 6,600+ articles:

- **Kushtetuta** (Constitution)
- **Kodi Civil**, **Kodi i Procedurës Civile**
- **Kodi Penal**, **Kodi i Procedurës Penale**
- **Kodi i Punës**, **Kodi i Familjes**
- **Kodi i Procedurave Administrative**
- **Kodi Doganor**, **Kodi Rrugor**, **Kodi Zgjedhor**
- **Kodi Detar**, **Kodi Ajror**

**Case law** — 813 structured decisions from Gjykata e Lartë and
Gjykata Kushtetuese (V4 corpus): each decision carries court, chamber,
date, parties, articles cited, outcome classification (accepted /
rejected / dismissed / modified / partially_accepted), judges, and a
normalised excerpt. Stored in Postgres, loaded into a BM25 index at
startup.

## How it answers (V5 brain)

Every question goes through a layered pipeline. Each layer is non-fatal —
one stage failing never breaks the primary answer.

```
question
   │
   ├── 1. Triage (Haiku)             — classify, expand query, flag gaps
   ├── 2. Statute retrieval (BM25)   — top articles from 6,616 total
   ├── 3. Precedent retrieval (BM25) — top cases from 813 decisions
   ├── 4. Strategic analysis (Haiku) — posture + risk frame
   ├── 5. Timeline (Haiku)           — deadlines + computed urgency
   ├── 6. Comparison (Haiku)         — winners vs losers pattern
   ├── 7. Answer (Opus, max effort)  — grounded 4-section reply
   └── 8. Missing-facts (Haiku)      — the 2-4 questions a lawyer asks next
```

The answer body always follows four sections in Albanian:

1. **Çfarë thotë ligji** — What the law says (with exact `Neni` citation)
2. **Të drejtat e tua** — Your rights
3. **Çfarë duhet të bësh** — Practical steps
4. **Afatet ligjore** — Legal deadlines

Layered on top of that body, the UI shows:

- **Pin-to-row precedents** — the model emits `[[case:ID]]` markers inline;
  the client rewrites them into clickable links that open the full decision
  page (`/case-precedent/<id>`) with court, judges, articles, outcome,
  excerpt.
- **Timeline widget** — every deadline gets an urgency class computed in
  Python from `(due_date - today).days`: expired / critical (≤3d) /
  warning (≤10d) / info. Icons + pulse animation for the ones that matter.
- **Winners-vs-losers card** — when the retrieved precedents split both
  ways, the comparison stage extracts what made the winners win and the
  losers lose, plus an overall alignment flag (favorable / mixed /
  unfavorable).
- **Missing-facts panel** — 2-4 clickable questions. Clicking pre-fills
  the composer with `Përgjigja për pyetjen «…» është: ` so the user
  just types the answer and hits send.

### Why BM25 over vector embeddings

Legal retrieval rewards exact term matches (article numbers, statute
names, specific Albanian legal terms). BM25 nails those. Claude handles
the semantic layer on top — which is where LLMs genuinely shine. This
also keeps the stack light: no GPU, no embedding model, no vector DB for
the statute/precedent index.

### Why Opus + max effort by default

Super Avvocato is a persona, not a toolkit. No quality toggles. A citizen
asking about an eviction doesn't know they should click "deeper answer" —
they need the best answer we can give. Latency is the cost we pay.

## Project structure

```
.
├── data/
│   ├── raw/          # Original PDFs of the codes
│   ├── processed/    # Parsed articles (JSON)
│   └── index/        # BM25 indices
├── src/
│   ├── config.py        # 13-document list, model IDs, effort level
│   ├── downloader.py    # Official sources → PDFs
│   ├── parser.py        # PDF → Neni-structured JSON
│   ├── retrieval.py     # BM25 over statute articles
│   ├── retrieval_kb.py  # BM25 over 813 court decisions (Postgres)
│   ├── brain.py         # The 8-layer pipeline above
│   ├── storage.py       # SQLite schema + additive migrations (app.db)
│   ├── backends.py      # Claude Code + API backends
│   ├── web.py           # Flask UI + JSON APIs
│   ├── bot.py           # Telegram interface
│   └── admin.py         # User provisioning CLI
├── static/              # app.js, style.css (dark theme)
├── scripts/             # One-off ops
└── tests/               # Real scenarios
```

## Setup

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# Fill in ANTHROPIC_API_KEY, TELEGRAM_BOT_TOKEN, and the Postgres
# DATABASE_URL pointing at the legalkb
```

## Pipeline

```bash
# 1. Download the 13 legal documents
python -m src.downloader

# 2. Parse them into Neni-structured JSON
python -m src.parser

# 3. Build the BM25 statute index (writes data/index/bm25.pkl)
python -m src.retrieval --build

# 4. The precedent index loads automatically from Postgres on web.py boot
#    (no separate build step — 813 decisions indexed in ~1s at startup)

# 5. Try a single question from the CLI
python -m src.brain "burri më dhunon, çfarë të bëj"

# 6. Provision the first user (admin) before launching the web UI
python -m src.admin adduser romeo --admin

# 7. Launch the multi-user web UI — open http://127.0.0.1:5050
python -m src.web

# 8. Start the Telegram bot (production)
python -m src.bot
```

## Multi-user & cases

The web UI is a gated, multi-user app. Each citizen has a login (you
create them from the admin CLI — there is no public signup). Every legal
problem lives in its own **case** — an isolated chat, so memory and
retrieval never bleed from one matter to another.

```bash
python -m src.admin adduser alice
python -m src.admin adduser bob --admin
python -m src.admin listusers
python -m src.admin passwd alice
python -m src.admin deluser alice   # deletes user + all their cases
```

Cases can be renamed, exported as Markdown or JSON, or deleted from the
web UI. Everything persists in `data/app.db` (SQLite) — one file to back
up. The schema uses additive `ALTER TABLE ADD COLUMN` migrations guarded
by `PRAGMA table_info`, so upgrading an existing DB never requires a
manual step.

## Dosja — a lawyer's case file

Each case can have a **dossier** (dosja): PDFs, images or SVG files the
lawyer attaches as evidence. Typical uploads — a judgment to be appealed,
a labor contract, an administrative act, a photo of a notice, scans of
receipts.

When a file is uploaded the server:

1. **Extracts the text** — pdfplumber for PDFs; AI vision OCR for images
   and scanned PDFs (`ANTHROPIC_API_KEY` or `GEMINI_API_KEY`);
   XML text-node extraction for SVG.
2. **Classifies + summarizes** the document with the fast model, pulling
   parties, dates, amounts, references, deadlines, operative dispositif.
3. **Injects the analysed dossier** into every subsequent question in
   that case — triage uses the summary to frame smarter retrieval
   queries; the main model cites documents by filename in the answer.

Formats: **PDF, JPG, PNG, SVG, WEBP, TIFF**. Defaults (override in
`.env`): 25 MB/file, 20 docs/case, 6,000 chars/doc fed into the prompt
(head + tail with ellipsis on longer texts).

Files live under `data/uploads/<case_id>/<uuid>.<ext>`, served only to
the owning user via authenticated routes — the raw filename never
touches the filesystem. Uploads are gitignored and excluded from the
Docker image; mount `data/` to persist across container restarts.

## Disclaimer

This tool provides legal information based on Albanian statutes and
case law. It is not a substitute for a licensed attorney in serious or
urgent cases. Always consult a qualified lawyer for representation in
court.

---

Built with ❤️ for everyone who needs justice.
