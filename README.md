# Super Avvocato AI 🇦🇱

**Asistent ligjor falas për qytetarët shqiptarë** — free legal assistant for Albanian citizens.

AI-powered legal assistant that answers citizens' legal questions based on the official Albanian codes and Constitution. Humanitarian mission: access to justice for everyone, regardless of income.

## Mission

Every citizen deserves to know their rights. This project gives free, clear, code-grounded legal guidance on:

- **Kushtetuta** (Constitution)
- **Kodi Civil** — Civil Code
- **Kodi i Procedurës Civile** — Civil Procedure Code
- **Kodi Penal** — Criminal Code
- **Kodi i Procedurës Penale** — Criminal Procedure Code
- **Kodi i Punës** — Labor Code
- **Kodi i Familjes** — Family Code
- **Kodi i Procedurave Administrative** — Administrative Procedure Code
- **Kodi Doganor** — Customs Code
- **Kodi Rrugor** — Road Code
- **Kodi Zgjedhor** — Electoral Code
- **Kodi Detar** — Maritime Code
- **Kodi Ajror** — Air Code

## Architecture

```
Citizen → Telegram bot → Legal Brain (Claude Opus 4.7)
                           ↓
                   3-stage pipeline:
                      1. Triage (Haiku 4.5): classify + expand query
                      2. Retrieval (BM25 over 6,600+ articles)
                      3. Answer (Opus 4.7): grounded 4-section answer
                           ↓
                   13 Albanian legal documents (PDFs → structured articles)
```

We use BM25 instead of vector embeddings because (a) legal retrieval rewards
exact term matches and (b) it works without heavy ML dependencies — Claude
handles the semantic layer on top, which is where LLMs genuinely shine.

Answers always follow this 4-section structure (in Albanian):

1. **Çfarë thotë ligji** — What the law says (with exact article citation)
2. **Të drejtat e tua** — Your rights
3. **Çfarë duhet të bësh** — Practical steps
4. **Afatet ligjore** — Legal deadlines

## Project structure

```
.
├── data/
│   ├── raw/          # Original PDFs of the codes
│   └── processed/    # Parsed articles (JSON)
├── src/
│   ├── config.py     # Configuration + list of 13 legal documents
│   ├── logging_utils.py
│   ├── downloader.py # Downloads official codes from QBZ / ministries
│   ├── parser.py     # Extracts articles (Neni X) from PDFs
│   ├── retrieval.py  # BM25 index + search
│   ├── brain.py      # Triage + retrieval + answer with Claude
│   └── bot.py        # Telegram interface
├── scripts/          # One-off operational scripts
├── tests/            # Test cases with real scenarios
└── logs/             # Runtime logs
```

## Setup

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# Fill in ANTHROPIC_API_KEY and TELEGRAM_BOT_TOKEN
```

## Pipeline

```bash
# 1. Download the 13 legal documents
python -m src.downloader

# 2. Parse them into articles (writes data/processed/*.json)
python -m src.parser

# 3. Build the BM25 index (writes data/index/bm25.pkl)
python -m src.retrieval --build

# 4. Try a single question from the CLI (no Telegram needed)
python -m src.brain "burri më dhunon, çfarë të bëj"

# 5. Provision the first user (admin) before launching the web UI
python -m src.admin adduser romeo --admin

# 6. Launch the multi-user web UI — open http://127.0.0.1:5050
python -m src.web

# 7. Start the Telegram bot (production)
python -m src.bot
```

## Multi-user & cases (V2)

The web UI is a gated, multi-user app. Each citizen has a login (you create
them from the admin CLI — there is no public signup). Every legal problem
lives in its own **case** — an isolated chat, so the bot's memory and
retrieval never bleed from one matter to another.

```bash
# Add users (first user is automatically admin)
python -m src.admin adduser alice
python -m src.admin adduser bob --admin

# List, rename, delete
python -m src.admin listusers
python -m src.admin passwd alice     # reset password
python -m src.admin deluser alice    # deletes user + all their cases
```

Cases can be renamed, downloaded as Markdown or JSON, or deleted on demand
from the web UI. Everything is persisted in `data/app.db` (SQLite) so it
survives restarts and can be backed up by copying a single file.

## Disclaimer

This tool provides legal information based on Albanian statutes. It is not a substitute for a licensed attorney in serious or urgent cases. Always consult a qualified lawyer for representation in court.

---

Built with ❤️ for everyone who needs justice.
