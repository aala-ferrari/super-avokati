"""Local web interface for Super Avvocato.

Run:
    ./venv/bin/python -m src.web
    → http://127.0.0.1:5050

Designed as a pre-Telegram playground: you type a problem, see the same 4-section
answer the bot would give, and also the list of articles the retriever pulled
so you can judge whether the grounding is correct.

If ANTHROPIC_API_KEY is not set, the app still runs but in "retrieval-only"
mode: you can see which articles BM25 pulls for any query — useful to tune
prompts without burning tokens.
"""
from __future__ import annotations

import html
from dataclasses import asdict

from flask import Flask, jsonify, render_template, request, session

from .backends import detect_available_backend
from .brain import SuperAvvocato
from .config import LEGAL_DOCUMENTS, MAX_CONVERSATION_TURNS
from .logging_utils import get_logger
from .retrieval import ArticleIndex

log = get_logger(__name__)

app = Flask(__name__, template_folder="../templates", static_folder="../static")
app.secret_key = "super-avvocato-dev-secret"  # localhost only; rotate for prod

_INDEX: ArticleIndex | None = None
_BRAIN: SuperAvvocato | None = None


def _ensure_loaded() -> None:
    global _INDEX, _BRAIN
    if _INDEX is None:
        _INDEX = ArticleIndex.load()
        log.info("index loaded: %d articles", len(_INDEX.articles))
    if _BRAIN is None and detect_available_backend():
        try:
            _BRAIN = SuperAvvocato(index=_INDEX)
        except Exception as exc:
            log.warning("brain init failed: %s", exc)
            _BRAIN = None


# ── pages ──────────────────────────────────────────────────────────────────

@app.route("/")
def index() -> str:
    _ensure_loaded()
    return render_template(
        "index.html",
        total_articles=len(_INDEX.articles),
        num_codes=len(LEGAL_DOCUMENTS),
        has_brain=bool(_BRAIN),
        backend_name=_BRAIN.backend.name if _BRAIN else None,
        codes=[{"code": d.code, "title": d.title_sq, "area": d.area}
               for d in LEGAL_DOCUMENTS],
    )


# ── API ────────────────────────────────────────────────────────────────────

@app.post("/api/ask")
def api_ask():
    _ensure_loaded()
    data = request.get_json(force=True) or {}
    message = (data.get("message") or "").strip()
    if not message:
        return jsonify({"error": "empty message"}), 400

    history = session.get("history", [])
    claude_session_id = session.get("claude_session_id")

    if not _BRAIN:
        # Retrieval-only fallback: show the articles BM25 would give the LLM.
        hits = _INDEX.search(message, top_k=10)
        return jsonify({
            "kind": "retrieval_only",
            "text": ("⚠️ Asnjë backend LLM nuk është i disponueshëm — "
                     "instaloni Claude Code (`claude /login`) ose vendosni "
                     "GEMINI_API_KEY/ANTHROPIC_API_KEY. Po tregoj vetëm "
                     "nenet që BM25-ja gjeti për pyetjen tënde."),
            "articles": [_article_payload(a, s) for a, s in hits],
            "triage": None,
        })

    try:
        result = _BRAIN.answer(message, history=history, session_id=claude_session_id)
    except Exception as exc:
        log.exception("brain failure")
        return jsonify({
            "kind": "error",
            "text": f"Gabim teknik: {type(exc).__name__}: {html.escape(str(exc))[:200]}",
        }), 500

    # persist short history server-side
    history = history + [
        {"role": "user", "content": message},
        {"role": "assistant", "content": result.text},
    ]
    history = history[-MAX_CONVERSATION_TURNS * 2 :]
    session["history"] = history
    # Persist the Claude Code session id so the next turn resumes natively.
    if result.session_id:
        session["claude_session_id"] = result.session_id

    return jsonify({
        "kind": result.kind,
        "text": result.text,
        "triage": asdict(result.triage) if result.triage else None,
        "articles": [_article_payload(a, s) for a, s in result.retrieved],
        "precedents": [_precedent_payload(d, s) for d, s in result.precedents],
    })


@app.post("/api/reset")
def api_reset():
    session.pop("history", None)
    session.pop("claude_session_id", None)
    return jsonify({"ok": True})


@app.get("/api/status")
def api_status():
    _ensure_loaded()
    return jsonify({
        "has_brain": bool(_BRAIN),
        "backend": _BRAIN.backend.name if _BRAIN else None,
        "total_articles": len(_INDEX.articles) if _INDEX else 0,
        "num_codes": len(LEGAL_DOCUMENTS),
    })


# ── helpers ────────────────────────────────────────────────────────────────

def _article_payload(a, score: float) -> dict:
    return {
        "citation": a.citation,
        "code": a.code,
        "number": a.number,
        "heading": a.heading,
        "body": a.body,
        "area": a.area,
        "hierarchy": " / ".join(x for x in (a.pjesa, a.kreu, a.seksioni) if x),
        "repealed": a.repealed,
        "score": round(score, 2),
    }


def _precedent_payload(d, score: float) -> dict:
    return {
        "citation": d.citation,
        "court": d.court_short_sq,
        "number": d.number,
        "year": d.year,
        "date": d.date,
        "outcome": d.outcome,
        "objekti": d.objekti,
        "kerkues": d.kerkues,
        "dispositif": d.dispositif,
        "source_url": d.source_url,
        "score": round(score, 2),
    }


# ── entrypoint ─────────────────────────────────────────────────────────────

def main() -> None:
    import os
    _ensure_loaded()
    port = int(os.environ.get("PORT", "5050"))
    host = os.environ.get("HOST", "127.0.0.1")
    log.info("starting Super Avvocato web UI at http://%s:%d", host, port)
    app.run(host=host, port=port, debug=False, use_reloader=False)


if __name__ == "__main__":
    main()
