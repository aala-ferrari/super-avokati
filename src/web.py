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
    Flask, jsonify, redirect, render_template, render_template_string,
    request, send_file, session, url_for,
)

from . import documents as docs_mod
from . import storage
from .auth import (
    authenticate, current_user, login_required_api, login_required_page,
    login_user, logout_user,
)
from .backends import detect_available_backend
from .brain import ANSWER_SYSTEM_VERSION, SuperAvvocato
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


@app.route("/case-precedent/<int:case_id>")
@login_required_page
def case_precedent_page(case_id: int):
    """Detail page for one KB precedent — the target of `[[case:ID]]` links.

    Pin-to-row: the id comes straight from the Postgres row we indexed, so
    a citation in an answer can always round-trip to the full dossier. If
    the brain is unavailable or the KB doesn't have this id (e.g. the row
    was pruned since the answer was generated), we show a clean 404 rather
    than exploding.
    """
    _ensure_loaded()
    if _BRAIN is None or not _BRAIN.kb.cases:
        return render_template_string(_CASE_PRECEDENT_MISSING, case_id=case_id), 404
    c = _BRAIN.kb.get(case_id)
    if c is None:
        return render_template_string(_CASE_PRECEDENT_MISSING, case_id=case_id), 404
    return render_template_string(_CASE_PRECEDENT_TEMPLATE, c=c)


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
             "timeline": m.timeline, "comparison": m.comparison,
             "missing_facts": m.missing_facts, "premortem": m.premortem,
             "distinguishing": m.distinguishing, "evidence_map": m.evidence_map,
             "nullity_radar": m.nullity_radar,
             "urgency_radar": m.urgency_radar,
             "action_plan": m.action_plan,
             "contradictions": m.contradictions,
             "opponent_playbook": m.opponent_playbook,
             "leverage": m.leverage,
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
                 "timeline": m.timeline, "comparison": m.comparison,
                 "missing_facts": m.missing_facts, "premortem": m.premortem,
                 "distinguishing": m.distinguishing, "evidence_map": m.evidence_map,
                 "nullity_radar": m.nullity_radar,
                 "urgency_radar": m.urgency_radar,
                 "action_plan": m.action_plan,
                 "contradictions": m.contradictions,
                 "opponent_playbook": m.opponent_playbook,
                 "leverage": m.leverage,
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

    # ANSWER_SYSTEM versioning (V6.9): Claude Code's `--resume` keeps the
    # session's baked-in system prompt, so a case that was started under
    # an older brain would keep using it even after we ship a new one.
    # If the fingerprint doesn't match, we null the session_id here so
    # the next compose starts fresh with the current system prompt. The
    # new fingerprint is written only after the fresh session succeeds.
    if storage.invalidate_case_session_if_stale(
        case.id, user.id, ANSWER_SYSTEM_VERSION,
    ):
        log.info("case %s: dropped stale Claude session (version mismatch)", case.id)
        case.claude_session_id = None

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
    timeline_payload = _timeline_payload(result.timeline)
    comparison_payload = _comparison_payload(result.comparison)
    missing_facts_payload = _missing_facts_payload(result.missing_facts)
    premortem_payload = _premortem_payload(result.premortem)
    distinguishing_payload = _distinguishing_payload(result.distinguishing)
    evidence_map_payload = _evidence_map_payload(result.evidence_map)
    nullity_radar_payload = _nullity_radar_payload(result.nullity_radar)
    urgency_radar_payload = _urgency_radar_payload(result.urgency_radar)
    action_plan_payload = _action_plan_payload(result.action_plan)
    contradictions_payload = _contradictions_payload(result.contradictions)
    opponent_payload = _opponent_playbook_payload(result.opponent_playbook)
    leverage_payload = _leverage_payload(result.leverage)
    storage.add_message(case.id, "assistant", result.text,
                        kind=result.kind, articles=articles, precedents=precedents,
                        timeline=timeline_payload, comparison=comparison_payload,
                        missing_facts=missing_facts_payload,
                        premortem=premortem_payload,
                        distinguishing=distinguishing_payload,
                        evidence_map=evidence_map_payload,
                        nullity_radar=nullity_radar_payload,
                        urgency_radar=urgency_radar_payload,
                        action_plan=action_plan_payload,
                        contradictions=contradictions_payload,
                        opponent_playbook=opponent_payload,
                        leverage=leverage_payload)
    if result.session_id:
        storage.update_case_claude_session(case.id, user.id, result.session_id)
        # Record the fingerprint alongside the session so the next turn
        # can detect drift if ANSWER_SYSTEM changes again.
        storage.set_case_answer_system_version(
            case.id, user.id, ANSWER_SYSTEM_VERSION,
        )
        # Audit trail: if the backend fell back from --resume to a fresh
        # session, the conversational thread was lost and we now wrote a
        # brand-new session id. Loud log so it shows up in ops.
        if getattr(_BRAIN.backend, "last_resume_failed", False):
            log.error(
                "case %s: --resume lost, rebuilt as fresh session %s",
                case.id, result.session_id,
            )

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
        "timeline": timeline_payload,
        "comparison": comparison_payload,
        "missing_facts": missing_facts_payload,
        "premortem": premortem_payload,
        "distinguishing": distinguishing_payload,
        "evidence_map": evidence_map_payload,
        "nullity_radar": nullity_radar_payload,
        "urgency_radar": urgency_radar_payload,
        "action_plan": action_plan_payload,
        "contradictions": contradictions_payload,
        "opponent_playbook": opponent_payload,
        "leverage": leverage_payload,
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


def _timeline_payload(timeline) -> dict | None:
    """Serialise TimelineAnalysis for the UI. None when empty."""
    if timeline is None or timeline.is_empty():
        return None
    return {
        "anchors": [asdict(a) for a in timeline.anchors],
        "deadlines": [asdict(d) for d in timeline.deadlines],
    }


def _comparison_payload(comparison) -> dict | None:
    """Serialise PrecedentComparison for the UI. None when empty."""
    if comparison is None or comparison.is_empty():
        return None
    return asdict(comparison)


def _missing_facts_payload(mf) -> dict | None:
    """Serialise MissingFactsAnalysis for the UI. None when empty."""
    if mf is None or mf.is_empty():
        return None
    return {"facts": [asdict(f) for f in mf.facts]}


def _premortem_payload(pm) -> dict | None:
    """Serialise Premortem for the UI. None when empty."""
    if pm is None or pm.is_empty():
        return None
    return {"risks": [asdict(r) for r in pm.risks]}


def _distinguishing_payload(d) -> dict | None:
    """Serialise DistinguishingAnalysis for the UI. None when empty."""
    if d is None or d.is_empty():
        return None
    return {"items": [asdict(i) for i in d.items]}


def _evidence_map_payload(em) -> dict | None:
    """Serialise EvidenceMap for the UI. None when empty."""
    if em is None or em.is_empty():
        return None
    return {"claims": [asdict(c) for c in em.claims]}


def _nullity_radar_payload(nr) -> dict | None:
    """Serialise NullityRadar for the UI. None when empty."""
    if nr is None or nr.is_empty():
        return None
    return {"findings": [asdict(f) for f in nr.findings]}


def _urgency_radar_payload(ur) -> dict | None:
    """Serialise UrgencyRadar for the UI. None when empty (keeps theoretical
    questions visually calm). Level + per-signal cards for the emergency panel.
    """
    if ur is None or ur.is_empty():
        return None
    return {
        "level": ur.level,
        "signals": [asdict(s) for s in ur.signals],
    }


def _action_plan_payload(ap) -> dict | None:
    """Serialise ActionPlan for the UI. None when empty so we don't render
    an empty 'here's your plan' panel on theoretical questions."""
    if ap is None or ap.is_empty():
        return None
    return {"items": [asdict(it) for it in ap.items]}


def _contradictions_payload(cr) -> dict | None:
    """Serialise ContradictionReport for the UI. None when empty — a
    single-document dossier or a clean dossier doesn't render a panel."""
    if cr is None or cr.is_empty():
        return None
    return {"items": [asdict(c) for c in cr.items]}


def _opponent_playbook_payload(op) -> dict | None:
    """Serialise OpponentPlaybook for the UI. None when empty so purely
    informative questions (no opposing party) don't render a panel."""
    if op is None or op.is_empty():
        return None
    return {
        "opponent": op.opponent,
        "moves": [asdict(m) for m in op.moves],
    }


def _leverage_payload(lm) -> dict | None:
    """Serialise LeverageMap for the UI. None when empty."""
    if lm is None or lm.is_empty():
        return None
    return {"levers": [asdict(lv) for lv in lm.levers]}


def _precedent_payload(c, score: float) -> dict:
    """Render a CasePrecedent (V4 KB row) for the chat UI."""
    return {
        "id": c.id,                       # pin-to-row for /case/<id> links
        "citation": c.citation,
        "court": c.court_name,
        "court_code": c.court_code,
        "number": c.case_number,
        "year": c.year,
        "date": c.decision_date.isoformat() if c.decision_date else None,
        "type": c.type,
        "outcome": c.outcome,
        "summary": c.summary,
        "judges": c.judges[:3],
        "articles_cited": [
            {"code": code, "article": art} for code, art in c.articles_cited[:6]
        ],
        "source_url": c.source_url,
        "score": round(score, 2),
    }


# ── precedent detail templates ─────────────────────────────────────────────
# Inline to avoid a third jinja file for what is a self-contained read-only
# page. The brain is the source of truth; we render whatever CasePrecedent
# hands back. Styling reuses /static/style.css variables.

_CASE_PRECEDENT_TEMPLATE = """<!DOCTYPE html>
<html lang="sq">
<head>
<meta charset="UTF-8" />
<meta name="viewport" content="width=device-width, initial-scale=1.0" />
<title>{{ c.citation }} — Super Avokati</title>
<link rel="stylesheet" href="/static/style.css" />
<style>
  body { background: #0a0a0a; color: #e8e8e8; font-family: Inter, sans-serif; margin: 0; padding: 24px 18px 80px; }
  .wrap { max-width: 820px; margin: 0 auto; }
  .back { display: inline-block; color: #c9a24d; text-decoration: none; margin-bottom: 14px; font-size: 14px; }
  .back:hover { text-decoration: underline; }
  h1 { font-family: "Playfair Display", serif; font-size: 28px; margin: 0 0 4px; line-height: 1.2; }
  .sub { color: #9a9a9a; font-size: 14px; margin-bottom: 20px; }
  .badges { display: flex; flex-wrap: wrap; gap: 8px; margin-bottom: 24px; }
  .badge { padding: 3px 10px; border-radius: 6px; background: #1a1a1a; border: 1px solid #2a2a2a; font-size: 13px; color: #d5d5d5; }
  .badge.outcome { background: #1b3e2e; border-color: #2f6a4e; color: #b9e8cd; }
  .badge.outcome.prec-rejected, .badge.outcome.prec-dismissed, .badge.outcome.prec-acquitted { background: #3a1d1d; border-color: #6a2f2f; color: #f2c1c1; }
  .badge.court { background: #1d2b3a; border-color: #2f4c6a; color: #bcd4ec; }
  h2 { font-size: 16px; color: #c9a24d; margin: 28px 0 10px; border-bottom: 1px solid #2a2a2a; padding-bottom: 6px; }
  .summary { background: #111; border-left: 3px solid #c9a24d; padding: 12px 16px; border-radius: 4px; line-height: 1.55; }
  ul.articles { list-style: none; padding: 0; margin: 0; display: flex; flex-wrap: wrap; gap: 6px; }
  ul.articles li { background: #141b28; border: 1px solid #2a3b55; padding: 4px 10px; border-radius: 5px; font-size: 13px; color: #bcd4ec; }
  .people { display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 14px; }
  .people .box h3 { margin: 0 0 6px; font-size: 13px; color: #9a9a9a; text-transform: uppercase; letter-spacing: 0.5px; }
  .people .box ul { list-style: none; padding: 0; margin: 0; }
  .people .box li { padding: 3px 0; font-size: 14px; color: #d5d5d5; }
  pre.excerpt { white-space: pre-wrap; word-wrap: break-word; background: #0f0f0f; border: 1px solid #1f1f1f; padding: 14px; border-radius: 6px; color: #c8c8c8; font-size: 13px; line-height: 1.55; }
  a.external { color: #c9a24d; }
</style>
</head>
<body>
<div class="wrap">
  <a class="back" href="/">← Kthehu te biseda</a>
  <h1>{{ c.court_name }}</h1>
  <div class="sub">
    nr. {{ c.case_number }}{% if c.decision_date %} · {{ c.decision_date.isoformat() }}{% endif %}
  </div>

  <div class="badges">
    {% if c.court_code %}<span class="badge court">{{ c.court_code }}</span>{% endif %}
    {% if c.type %}<span class="badge">{{ c.type }}{% if c.subtype %} / {{ c.subtype }}{% endif %}</span>{% endif %}
    {% if c.outcome %}<span class="badge outcome prec-{{ c.outcome }}">{{ c.outcome }}</span>{% endif %}
    {% if c.source_url %}<a class="badge external" href="{{ c.source_url }}" target="_blank" rel="noopener">Burimi origjinal →</a>{% endif %}
  </div>

  {% if c.summary %}
    <h2>Përmbledhje</h2>
    <div class="summary">{{ c.summary }}</div>
  {% endif %}

  {% if c.articles_cited %}
    <h2>Nenet e cituara ({{ c.articles_cited|length }})</h2>
    <ul class="articles">
      {% for code, art in c.articles_cited %}
        <li>{{ code }} neni {{ art }}</li>
      {% endfor %}
    </ul>
  {% endif %}

  {% if c.judges or c.lawyers or c.prosecutors %}
    <h2>Palët procedurale</h2>
    <div class="people">
      {% if c.judges %}
        <div class="box"><h3>Trupi gjykues</h3>
          <ul>{% for j in c.judges %}<li>{{ j }}</li>{% endfor %}</ul>
        </div>
      {% endif %}
      {% if c.prosecutors %}
        <div class="box"><h3>Prokuroria</h3>
          <ul>{% for p in c.prosecutors %}<li>{{ p }}</li>{% endfor %}</ul>
        </div>
      {% endif %}
      {% if c.lawyers %}
        <div class="box"><h3>Mbrojtja</h3>
          <ul>{% for l in c.lawyers %}<li>{{ l }}</li>{% endfor %}</ul>
        </div>
      {% endif %}
    </div>
  {% endif %}

  {% if c.excerpt %}
    <h2>Fragment nga vendimi</h2>
    <pre class="excerpt">{{ c.excerpt }}</pre>
  {% endif %}
</div>
</body>
</html>
"""

_CASE_PRECEDENT_MISSING = """<!DOCTYPE html>
<html lang="sq">
<head>
<meta charset="UTF-8" />
<title>Vendimi nuk u gjet — Super Avokati</title>
<link rel="stylesheet" href="/static/style.css" />
<style>
  body { background: #0a0a0a; color: #e8e8e8; font-family: Inter, sans-serif; padding: 80px 24px; text-align: center; }
  h1 { font-family: "Playfair Display", serif; color: #c9a24d; }
  a { color: #c9a24d; }
</style>
</head>
<body>
  <h1>Vendimi #{{ case_id }} nuk është në bazën tonë</h1>
  <p>Mund të jetë hequr nga indeksi ose id-ja nuk është e vlefshme.</p>
  <p><a href="/">← Kthehu te biseda</a></p>
</body>
</html>
"""


# ── entrypoint ─────────────────────────────────────────────────────────────

def main() -> None:
    _ensure_loaded()
    port = int(os.environ.get("PORT", "5050"))
    host = os.environ.get("HOST", "127.0.0.1")
    log.info("starting Super Avvocato web UI at http://%s:%d", host, port)
    app.run(host=host, port=port, debug=False, use_reloader=False)


if __name__ == "__main__":
    main()
