#!/usr/bin/env bash
# One-shot pipeline: download → parse → index.
# Run once after cloning (or `./venv/bin/python -m src.downloader --force` later).

set -euo pipefail
cd "$(dirname "$0")/.."

PY="./venv/bin/python"
[ -x "$PY" ] || { echo "Create a venv first: python3 -m venv venv && ./venv/bin/pip install -r requirements.txt"; exit 1; }

echo "→ 1/3  downloading 13 Albanian legal documents ..."
$PY -m src.downloader

echo "→ 2/3  parsing articles ..."
$PY -m src.parser

echo "→ 3/3  building BM25 index ..."
$PY -m src.retrieval --build

echo ""
echo "✅ Pipeline complete. Next: set ANTHROPIC_API_KEY + TELEGRAM_BOT_TOKEN in .env, then:"
echo "   $PY -m src.brain \"your question here\"   # CLI test"
echo "   $PY -m src.bot                             # launch Telegram bot"
