"""Multi-user web interface for Super Avvocato.

Run:
    ./venv/bin/python -m src.web
    → http://127.0.0.1:5050

Each citizen has a login (provisioned via `python -m src.admin adduser`).
Each legal problem lives in its own *case* — a standalone chat — so that
history, Claude Code session and retrieved articles never bleed from
one cause to another. Cases can be renamed, exported (JSON or Markdown)
or deleted on demand by the owner.

If no LLM backend is available the `/api/ask` endpoint still works in
"retrieval-only" mode, surfacing the BM25 hits so the operator can tune
the index without spending tokens.
"""
from __future__ import annotations

import html
import io
import json
import os
import secrets
from dataclasses import asdict
from datetime import timedelta
from pathlib import Path

from flask import (
    Flask, jsonify, redirect, render_template, request, send_file,
    session, url_for,
)

from . import documents as docs_mod
from . import storage
from .auth import (
    authenticate, current_user, login_required_api, login_required_page,
    login_user, logout_user,
)
from .backends import detect_available_backend
from .brain import SuperAvvocato
from .config import (
    APP_DB_PATH,
    LEGAL_DOCUMENTS,
    MAX_CONVERSATION_TURNS,
    MAX_DOCUMENTS_PER_CASE,
    MAX_UPLOAD_SIZE_MB,
    ROOT,
)
from .logging_utils import get_logger
from .retrieval import ArticleIndex

log = get_logger(__name__)

app = Flask(__name__, template_folder="../templates", static_folder="../static")

# Secret key: persisted under data/ so sessions survive a restart. If the
# file does not exist, generate a fresh cryptographically-strong secret.
_SECRET_FILE = APP_DB_PATH.parent / ".secret_key"
def _load_secret_key() -> bytes:
    env = os.environ.get("SECRET_KEY")
    if env:
        return env.encode("utf-8")
    if _SECRET_FILE.exists():
        return _SECRET_FILE.read_bytes()
    _SECRET_FILE.parent.mkdir(parents=True, exist_ok=True)
    secret = secrets.token_bytes(32)
    _SECRET_FILE.write_bytes(secret)
    try:
        os.chmod(_SECRET_FILE, 0o600)
    except OSError:
        pass
    return secret

app.secret_key = _load_secret_key()
app.permanent_session_lifetime = timedelta(days=30)
# Flask only checks Content-Length against MAX_CONTENT_LENGTH when set —
# without this the server would happily buffer multi-GB uploads. We add a
# small cushion over the per-file limit to account for multipart overhead.
app.config["MAX_CONTENT_LENGTH"] = (MAX_UPLOAD_SIZE_MB + 2) * 1024 * 1024

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
    storage.init_db()


# ── pages ──────────────────────────────────────────────────────────────────

@app.route("/")
@login_required_page
def index() -> str:
    _ensure_loaded()
    user = current_user()
    return render_template(
        "index.html",
        total_articles=len(_INDEX.articles),
        num_codes=len(LEGAL_DOCUMENTS),
        has_brain=bool(_BRAIN),
        backend_name=_BRAIN.backend.name if _BRAIN else None,
        codes=[{"code": d.code, "title": d.title_sq, "area": d.area}
               for d in LEGAL_DOCUMENTS],
        username=user.username,
        is_admin=user.is_admin,
    )


@app.route("/login", methods=["GET"])
def login_page() -> str:
    _ensure_loaded()
    if current_user() is not None:
        return redirect(url_for("index"))
    return render_template("login.html")


# ── auth API ───────────────────────────────────────────────────────────────

@app.post("/api/login")
def api_login():
    _ensure_loaded()
    data = request.get_json(force=True, silent=True) or {}
    username = (data.get("username") or "").strip()
    password = data.get("password") or ""
    if not username or not password:
        return jsonify({"error": "missing credentials"}), 400
    user = authenticate(username, password)
    if user is None:
        log.info("failed login for %r", username)
        return jsonify({"error": "invalid credentials"}), 401
    login_user(user)
    log.info("login ok: %r", user.username)
    return jsonify({"ok": True, "user": {"username": user.username,
                                         "is_admin": user.is_admin}})


@app.post("/api/logout")
def api_logout():
    logout_user()
    return jsonify({"ok": True})


@app.get("/api/me")
def api_me():
    u = current_user()
    if u is None:
        return jsonify({"authenticated": False}), 401
    return jsonify({
        "authenticated": True,
        "username": u.username,
        "is_admin": u.is_admin,
    })


# ── cases API ──────────────────────────────────────────────────────────────

@app.get("/api/cases")
@login_required_api
def api_list_cases():
    user = request.user  # type: ignore[attr-defined]
    cases = storage.list_cases(user.id)
    return jsonify({"cases": [
        {"id": c.id, "title": c.title,
         "created_at": c.created_at, "updated_at": c.updated_at}
        for c in cases
    ]})


@app.post("/api/cases")
@login_required_api
def api_create_case():
    user = request.user  # type: ignore[attr-defined]
    data = request.get_json(force=True, silent=True) or {}
    title = (data.get("title") or "").strip() or "Rast i ri"
    case = storage.create_case(user.id, title)
    return jsonify({"id": case.id, "title": case.title,
                    "created_at": case.created_at, "updated_at": case.updated_at})


@app.get("/api/cases/<case_id>")
@login_required_api
def api_get_case(case_id: str):
    user = request.user  # type: ignore[attr-defined]
    case = storage.get_case(case_id, user.id)
    if not case:
        return jsonify({"error": "not found"}), 404
    messages = storage.list_messages(case_id)
    documents = storage.list_documents(case_id)
    return jsonify({
        "id": case.id,
        "title": case.title,
        "created_at": case.created_at,
        "updated_at": case.updated_at,
        "messages": [
            {"id": m.id, "role": m.role, "content": m.content, "kind": m.kind,
             "articles": m.articles, "precedents": m.precedents,
             "created_at": m.created_at}
            for m in messages
        ],
        "documents": [_document_payload(d) for d in documents],
    })


@app.patch("/api/cases/<case_id>")
@login_required_api
def api_rename_case(case_id: str):
    user = request.user  # type: ignore[attr-defined]
    data = request.get_json(force=True, silent=True) or {}
    title = (data.get("title") or "").strip()
    if not title:
        return jsonify({"error": "empty title"}), 400
    if not storage.rename_case(case_id, user.id, title):
        return jsonify({"error": "not found"}), 404
    return jsonify({"ok": True, "title": title})


@app.delete("/api/cases/<case_id>")
@login_required_api
def api_delete_case(case_id: str):
    user = request.user  # type: ignore[attr-defined]
    if not storage.delete_case(case_id, user.id):
        return jsonify({"error": "not found"}), 404
    return jsonify({"ok": True})


@app.get("/api/cases/<case_id>/export")
@login_required_api
def api_export_case(case_id: str):
    """Download a case as JSON (full fidelity) or Markdown (human-readable).

    ?format=md — Markdown transcript with headings per message.
    default    — JSON with everything (articles, precedents, timestamps).
    """
    user = request.user  # type: ignore[attr-defined]
    case = storage.get_case(case_id, user.id)
    if not case:
        return jsonify({"error": "not found"}), 404
    messages = storage.list_messages(case_id)
    fmt = request.args.get("format", "json").lower()

    slug = "".join(c if c.isalnum() or c in "-_" else "_"
                   for c in case.title.lower())[:60] or "rast"

    if fmt == "md":
        buf = io.StringIO()
        buf.write(f"# {case.title}\n\n")
        buf.write(f"_Super Avvocato — eksport i bisedës_\n")
        buf.write(f"Krijuar: {case.created_at} · Përditësuar: {case.updated_at}\n\n")
        buf.write("---\n\n")
        for m in messages:
            who = "🧑 Qytetari" if m.role == "user" else "⚖️ Super Avvocato"
            buf.write(f"## {who} — _{m.created_at}_\n\n{m.content}\n\n")
            if m.articles:
                buf.write("**Nenet e cituara:**\n")
                for a in m.articles:
                    buf.write(f"- [{a.get('score', '?')}] {a.get('citation', '')} — "
                              f"{a.get('heading', '')}\n")
                buf.write("\n")
            if m.precedents:
                buf.write("**Vendime precedent:**\n")
                for p in m.precedents:
                    oc = f" ({p.get('outcome')})" if p.get("outcome") else ""
                    buf.write(f"- [{p.get('score', '?')}] {p.get('citation', '')}{oc} — "
                              f"{(p.get('objekti') or '')[:120]}\n")
                buf.write("\n")
            buf.write("---\n\n")
        data = buf.getvalue().encode("utf-8")
        filename = f"{slug}.md"
        mimetype = "text/markdown; charset=utf-8"
    else:
        payload = {
            "case": {
                "id": case.id,
                "title": case.title,
                "created_at": case.created_at,
                "updated_at": case.updated_at,
            },
            "messages": [
                {"role": m.role, "content": m.content, "kind": m.kind,
                 "articles": m.articles, "precedents": m.precedents,
                 "created_at": m.created_at}
                for m in messages
            ],
        }
        data = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
        filename = f"{slug}.json"
        mimetype = "application/json; charset=utf-8"

    return send_file(io.BytesIO(data), mimetype=mimetype,
                     as_attachment=True, download_name=filename)


# ── dossier (per-case documents) API ───────────────────────────────────────

@app.get("/api/cases/<case_id>/documents")
@login_required_api
def api_list_documents(case_id: str):
    user = request.user  # type: ignore[attr-defined]
    if storage.get_case(case_id, user.id) is None:
        return jsonify({"error": "not found"}), 404
    return jsonify({"documents": [_document_payload(d)
                                   for d in storage.list_documents(case_id)]})


@app.post("/api/cases/<case_id>/documents")
@login_required_api
def api_upload_document(case_id: str):
    """Upload a PDF/JPG/PNG/SVG to the case's dossier.

    We run extraction + AI analysis synchronously — a typical dossier is a
    handful of small PDFs, and blocking 5-10s here is simpler than a job
    queue. If the user uploads a large scanned PDF, vision OCR happens in
    the same request; the frontend shows a spinner.
    """
    _ensure_loaded()
    user = request.user  # type: ignore[attr-defined]
    case = storage.get_case(case_id, user.id)
    if case is None:
        return jsonify({"error": "not found"}), 404

    if storage.count_documents(case_id) >= MAX_DOCUMENTS_PER_CASE:
        return jsonify({
            "error": f"maksimumi {MAX_DOCUMENTS_PER_CASE} dokumente për rast"
        }), 413

    if "file" not in request.files:
        return jsonify({"error": "no file"}), 400
    f = request.files["file"]
    if not f.filename:
        return jsonify({"error": "no filename"}), 400

    # Read file into memory for validation; upload limit (25MB default) makes
    # this safe and saves a useless partial write on invalid uploads.
    content = f.read()
    v = docs_mod.validate_upload(f.filename, len(content))
    if not v.ok:
        return jsonify({"error": v.error}), 400

    storage_path = docs_mod.storage_path_for(case_id, v.ext)
    storage_path.write_bytes(content)

    doc = storage.create_document(
        case_id=case_id,
        filename=f.filename,
        ext=v.ext,
        mimetype=v.mimetype,
        size_bytes=len(content),
        storage_path=str(storage_path),
    )

    try:
        text, used_ocr = docs_mod.extract_text(
            storage_path, v.ext, v.mimetype,
            backend=_BRAIN.backend if _BRAIN else None,
        )
    except Exception as exc:
        log.exception("extraction failed for %s", f.filename)
        storage.mark_document_error(doc.id, f"{type(exc).__name__}: {exc}")
        return jsonify(_document_payload(storage.get_document(doc.id, case_id))), 200

    analysis = {"doc_type": None, "summary": None, "key_facts": []}
    if text and _BRAIN:
        try:
            analysis = docs_mod.summarize_document(text, f.filename, _BRAIN.backend)
        except Exception as exc:
            log.warning("analysis failed for %s: %s", f.filename, exc)

    storage.update_document_analysis(
        doc.id,
        extracted_text=text or None,
        doc_type=analysis.get("doc_type"),
        summary=analysis.get("summary"),
        key_facts=analysis.get("key_facts") or [],
    )
    storage.touch_case(case_id, user.id)

    fresh = storage.get_document(doc.id, case_id)
    payload = _document_payload(fresh)
    payload["used_vision_ocr"] = used_ocr
    return jsonify(payload), 201


@app.delete("/api/cases/<case_id>/documents/<doc_id>")
@login_required_api
def api_delete_document(case_id: str, doc_id: str):
    user = request.user  # type: ignore[attr-defined]
    if storage.get_case(case_id, user.id) is None:
        return jsonify({"error": "not found"}), 404
    removed = storage.delete_document(doc_id, case_id)
    if removed is None:
        return jsonify({"error": "not found"}), 404
    # Remove the file on disk (best-effort — missing file is not an error).
    try:
        Path(removed.storage_path).unlink(missing_ok=True)
    except OSError as exc:
        log.warning("could not unlink %s: %s", removed.storage_path, exc)
    return jsonify({"ok": True})


@app.get("/api/cases/<case_id>/documents/<doc_id>/raw")
@login_required_api
def api_view_document(case_id: str, doc_id: str):
    """Stream the original file back to the owner — for preview/download."""
    user = request.user  # type: ignore[attr-defined]
    if storage.get_case(case_id, user.id) is None:
        return jsonify({"error": "not found"}), 404
    doc = storage.get_document(doc_id, case_id)
    if doc is None:
        return jsonify({"error": "not found"}), 404
    path = Path(doc.storage_path)
    if not path.exists():
        return jsonify({"error": "file missing"}), 410
    return send_file(
        path, mimetype=doc.mimetype,
        as_attachment=False,
        download_name=doc.filename,
    )


# ── ask API (scoped to a case) ─────────────────────────────────────────────

@app.post("/api/ask")
@login_required_api
def api_ask():
    _ensure_loaded()
    user = request.user  # type: ignore[attr-defined]
    data = request.get_json(force=True, silent=True) or {}
    message = (data.get("message") or "").strip()
    case_id = (data.get("case_id") or "").strip()
    if not message:
        return jsonify({"error": "empty message"}), 400
    if not case_id:
        return jsonify({"error": "missing case_id"}), 400
    case = storage.get_case(case_id, user.id)
    if case is None:
        return jsonify({"error": "case not found"}), 404

    storage.add_message(case.id, "user", message)
    history = storage.conversation_history(case.id, MAX_CONVERSATION_TURNS)
    # Drop the trailing user turn we just added — SuperAvvocato.answer
    # expects `history` to be prior context and `message` to be the new turn.
    if history and history[-1]["role"] == "user":
        history = history[:-1]

    # Gather the dossier for this case. Every doc whose file is still on
    # disk gets attached — the brain passes the raw files to Claude so it
    # reads them natively (same UX as a user pasting an image into chat).
    # Pre-extracted text/summary is a hint for triage; placeholder strings
    # left over from older code are wiped so they don't mislead the model.
    _STALE_PREFIXES = (
        "(Një imazh u ngarkua",
        "(Ky skedar duket i skanuar",
    )
    case_docs = []
    for d in storage.list_documents(case.id):
        if not d.storage_path or not Path(d.storage_path).exists():
            continue
        text = d.extracted_text or ""
        summary = d.summary
        if text.startswith(_STALE_PREFIXES):
            text = ""
            summary = None
        case_docs.append({
            "filename": d.filename,
            "doc_type": d.doc_type,
            "summary": summary,
            "key_facts": d.key_facts,
            "extracted_text": text or None,
            "storage_path": d.storage_path,
        })

    if not _BRAIN:
        hits = _INDEX.search(message, top_k=10)
        articles = [_article_payload(a, s) for a, s in hits]
        text = ("⚠️ Asnjë backend LLM nuk është i disponueshëm — "
                "instaloni Claude Code (`claude /login`) ose vendosni "
                "GEMINI_API_KEY/ANTHROPIC_API_KEY. Po tregoj vetëm "
                "nenet që BM25-ja gjeti për pyetjen tënde.")
        storage.add_message(case.id, "assistant", text,
                            kind="retrieval_only", articles=articles)
        return jsonify({"kind": "retrieval_only", "text": text,
                        "articles": articles, "triage": None,
                        "precedents": [], "case_id": case.id})

    try:
        result = _BRAIN.answer(message, history=history,
                               session_id=case.claude_session_id,
                               documents=case_docs)
    except Exception as exc:
        log.exception("brain failure")
        err_text = f"Gabim teknik: {type(exc).__name__}: {html.escape(str(exc))[:200]}"
        storage.add_message(case.id, "assistant", err_text, kind="error")
        return jsonify({"kind": "error", "text": err_text}), 500

    articles = [_article_payload(a, s) for a, s in result.retrieved]
    precedents = [_precedent_payload(d, s) for d, s in result.precedents]
    storage.add_message(case.id, "assistant", result.text,
                        kind=result.kind, articles=articles, precedents=precedents)
    if result.session_id:
        storage.update_case_claude_session(case.id, user.id, result.session_id)

    # Auto-title the case with the first user message if it's still default.
    if case.title in ("Rast i ri", "Rast pa titull"):
        auto_title = message[:60].strip()
        if auto_title:
            storage.rename_case(case.id, user.id, auto_title)

    return jsonify({
        "kind": result.kind,
        "text": result.text,
        "triage": asdict(result.triage) if result.triage else None,
        "articles": articles,
        "precedents": precedents,
        "case_id": case.id,
    })


@app.get("/api/status")
def api_status():
    _ensure_loaded()
    return jsonify({
        "has_brain": bool(_BRAIN),
        "backend": _BRAIN.backend.name if _BRAIN else None,
        "total_articles": len(_INDEX.articles) if _INDEX else 0,
        "num_codes": len(LEGAL_DOCUMENTS),
        "authenticated": current_user() is not None,
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


def _document_payload(d) -> dict:
    """Serialise a Document for the UI. Never exposes the on-disk path."""
    if d is None:
        return {}
    return {
        "id": d.id,
        "filename": d.filename,
        "ext": d.ext,
        "mimetype": d.mimetype,
        "size_bytes": d.size_bytes,
        "status": d.status,
        "error": d.error,
        "doc_type": d.doc_type,
        "summary": d.summary,
        "key_facts": d.key_facts,
        "has_text": bool(d.extracted_text),
        "created_at": d.created_at,
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
    _ensure_loaded()
    port = int(os.environ.get("PORT", "5050"))
    host = os.environ.get("HOST", "127.0.0.1")
    log.info("starting Super Avvocato web UI at http://%s:%d", host, port)
    app.run(host=host, port=port, debug=False, use_reloader=False)


if __name__ == "__main__":
    main()
