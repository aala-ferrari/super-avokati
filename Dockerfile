# Super Avvocato V9.1 — multi-user legal assistant for Albanian lawyers,
# 18-source legal corpus (Kushtetuta + 13 codes + 5 sectoral laws,
# 5615 articles) with volatility tagging, 282 Constitutional Court
# decisions (2015-2024) indexed for precedent retrieval, per-case
# dossier upload, V9.0 Genio Legale (6 parallel Opus perspectives), and
# AI analysis via the 15-stage parallel pipeline.
#
# V9.1 (2026-04-27): parser heading multi-line fix + jurisdiction
# guard against italo-francez doctrine drift (KUFI JURIDIKSIONAL).
#
# Default backend inside the container is the Anthropic API (ANTHROPIC_API_KEY)
# or Gemini (GEMINI_API_KEY) — the Claude Code CLI backend is unavailable
# because it needs an interactive `claude /login` which doesn't work headless.
# Note: the dossier's image/scanned-PDF OCR requires ANTHROPIC_API_KEY or
# GEMINI_API_KEY (native PDF text layers work without either).
#
# Build:   docker build -t super-avvocato:v9.1 .
# Run:     docker run --rm -p 5050:5050 \
#            -v $(pwd)/data:/app/data \
#            -e ANTHROPIC_API_KEY=sk-ant-... \
#            -e BRAIN_BACKEND=anthropic \
#            super-avvocato:v9.1
# The data volume persists: sqlite DB, session secret, AND the per-case
# uploaded files under data/uploads/ — mount it or lose them on restart.
# Then provision the first admin user:
#   docker exec -it <container_id> python -m src.admin adduser <name> --admin
# Open:    http://localhost:5050

FROM python:3.14-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    HOST=0.0.0.0 \
    PORT=5050 \
    BRAIN_BACKEND=auto \
    BRAIN_PARALLEL_STAGES=1 \
    BRAIN_PARALLEL_WORKERS=3 \
    CLAUDE_CODE_MAX_CONCURRENCY=6 \
    FOLLOWUP_FASTPATH_MAX_CHARS=200 \
    SIMPLE_FASTPATH_ENABLED=1

WORKDIR /app

# pdfplumber + python-docx are pure-Python but lean on a few shared libs for
# image and XML parsing. Install only what is needed, then purge apt caches.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        libjpeg62-turbo \
        libxml2 \
        antiword \
        libxslt1.1 \
        curl \
        ca-certificates \
        gnupg \
    && curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && npm install -g @anthropic-ai/claude-code \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Copy source + data in the order that maximises layer reuse: code changes
# more often than data, so we copy data first.
COPY data/ ./data/
COPY src/ ./src/
COPY static/ ./static/
COPY templates/ ./templates/
COPY scripts/ ./scripts/
COPY tools/ ./tools/
# i testi legali: fonte unica, mostrati nell'app e firmati fuori
COPY legal/ ./legal/
COPY README.md .env.example ./

# Non-root user for runtime safety.
RUN useradd --create-home --shell /bin/bash avvocato \
    && chown -R avvocato:avvocato /app
USER avvocato

EXPOSE 5050

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD curl -fsS http://127.0.0.1:${PORT}/api/status || exit 1

CMD ["python", "-m", "src.web"]
