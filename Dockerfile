# Super Avvocato V3 — multi-user legal assistant for Albanian citizens,
# with per-case dossier upload (PDF/JPG/PNG/SVG) and AI analysis.
#
# Default backend inside the container is the Anthropic API (ANTHROPIC_API_KEY)
# or Gemini (GEMINI_API_KEY) — the Claude Code CLI backend is unavailable
# because it needs an interactive `claude /login` which doesn't work headless.
# Note: the dossier's image/scanned-PDF OCR requires ANTHROPIC_API_KEY or
# GEMINI_API_KEY (native PDF text layers work without either).
#
# Build:   docker build -t super-avvocato:v3 .
# Run:     docker run --rm -p 5050:5050 \
#            -v $(pwd)/data:/app/data \
#            -e ANTHROPIC_API_KEY=sk-ant-... \
#            -e BRAIN_BACKEND=anthropic \
#            super-avvocato:v3
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
    BRAIN_BACKEND=auto

WORKDIR /app

# pdfplumber + python-docx are pure-Python but lean on a few shared libs for
# image and XML parsing. Install only what is needed, then purge apt caches.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        libjpeg62-turbo \
        libxml2 \
        libxslt1.1 \
        curl \
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
COPY README.md .env.example ./

# Non-root user for runtime safety.
RUN useradd --create-home --shell /bin/bash avvocato \
    && chown -R avvocato:avvocato /app
USER avvocato

EXPOSE 5050

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD curl -fsS http://127.0.0.1:${PORT}/api/status || exit 1

CMD ["python", "-m", "src.web"]
