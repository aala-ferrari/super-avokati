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
import re
import secrets
import threading

from . import jobs as jobs_mod
from . import push as push_mod
import time
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from pathlib import Path

from flask import (
    Flask,
    Response,
    jsonify,
    redirect,
    render_template,
    render_template_string,
    request,
    send_file,
    stream_with_context,
    send_from_directory,
    url_for,
)

from . import citation_shield as cs_mod
from . import citation_verifier as cv_mod
from . import case_citation_verifier as ccv_mod
from . import decision_verifier as dv_mod
from . import documents as docs_mod
from . import video as video_mod
from . import pro_features as pro_mod
from . import reminders as reminders_mod
from . import secretary as secretary_mod
from . import storage
from . import validity as validity_mod
from . import actcheck as actcheck_mod
from . import conflicts as conflicts_mod
from . import vault as vault_mod
from . import second_opinion as second_opinion_mod
from . import fable_drafter as fable_drafter_mod
from . import adversary as adversary_mod
from . import expertise as expertise_mod
from . import prosecutor as prosecutor_mod
from . import living_law as living_mod
from . import intake as intake_mod
from . import afati as afati_mod
from . import registry as registry_mod
from . import notary as notary_mod
from . import deadlines as deadlines_mod
from . import letters as letters_mod
from . import case_brief as brief_mod
from . import brain as brain_mod
from .auth import (
    authenticate,
    current_user,
    hash_password,
    login_required_api,
    login_required_page,
    login_user,
    logout_user,
    require_permission,
)
from .backends import detect_available_backend
from .brain import ANSWER_SYSTEM_VERSION, SuperAvvocato
from .config import (
    APP_DB_PATH,
    CLAUDE_MODEL,
    LEGAL_DOCUMENTS,
    MAX_CONVERSATION_TURNS,
    MAX_DOCUMENTS_PER_CASE,
    MAX_UPLOAD_SIZE_MB,
)
from .logging_utils import get_logger
from .retrieval import ArticleIndex

log = get_logger(__name__)

app = Flask(__name__, template_folder="../templates", static_folder="../static")
app.config["TEMPLATES_AUTO_RELOAD"] = True
app.jinja_env.auto_reload = True

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
#
# ⚠️ Il tetto segue il file piu' grande che ACCETTIAMO, cioe' un video: con i
# 25 MB degli atti, qualunque video veniva respinto da Flask **prima** che il
# nostro codice potesse dire una parola — un 413 secco, senza spiegazione.
# Questo resta la rete contro l'assurdo; la regola vera e' `validate_upload`,
# che applica 25 MB agli atti e 500 ai video, ciascuno al suo tipo.
from .config import MAX_VIDEO_SIZE_MB as _MAX_VIDEO_MB  # noqa: E402
app.config["MAX_CONTENT_LENGTH"] = (
    max(MAX_UPLOAD_SIZE_MB, _MAX_VIDEO_MB) + 2
) * 1024 * 1024

_INDEX: ArticleIndex | None = None
_INDEX_IT: ArticleIndex | None = None
_BRAIN: SuperAvvocato | None = None


def _ensure_loaded() -> None:
    global _INDEX, _BRAIN, _INDEX_IT
    if _INDEX is None:
        _INDEX = ArticleIndex.load()
        log.info("index loaded: %d articles", len(_INDEX.articles))
        try:
            from .retrieval import INDEX_FILE
            _it_path = INDEX_FILE.parent / "bm25_it.pkl"
            if _it_path.exists():
                _INDEX_IT = ArticleIndex.load(_it_path)
                log.info("IT index loaded: %d articles", len(_INDEX_IT.articles))
        except Exception as exc:  # noqa: BLE001
            log.warning("IT index not loaded: %s", exc)
    if _BRAIN is None and detect_available_backend():
        try:
            _BRAIN = SuperAvvocato(index=_INDEX, index_it=_INDEX_IT)
        except Exception as exc:
            log.warning("brain init failed: %s", exc)
            _BRAIN = None
    storage.init_db()
    reminders_mod.start_background()


# ── pages ──────────────────────────────────────────────────────────────────

_LEGAL_DOCS_IT_FALLBACK = [
    {"code": "costituzione", "title": "Costituzione della Repubblica Italiana", "area": "Costituzionale"},
    {"code": "codice_civile", "title": "Codice Civile", "area": "Civile"},
    {"code": "codice_procedura_civile", "title": "Codice di Procedura Civile", "area": "Procedura Civile"},
    {"code": "codice_penale", "title": "Codice Penale", "area": "Penale"},
    {"code": "codice_procedura_penale", "title": "Codice di Procedura Penale", "area": "Procedura Penale"},
]
_IT_CODES_CACHE: list | None = None


def _legal_docs_it():
    """The Italian corpora we actually index, in display order.

    Read once from data/processed/it_codes.json (written when the index is
    built); falls back to the five fundamental codes if that file is absent."""
    global _IT_CODES_CACHE
    if _IT_CODES_CACHE is None:
        try:
            import json as _json
            from pathlib import Path as _Path
            p = _Path(__file__).resolve().parent.parent / "data" / "processed" / "it_codes.json"
            rows = _json.loads(p.read_text(encoding="utf-8"))
            _IT_CODES_CACHE = [{"code": r["code"], "title": r["title"],
                                "area": r.get("area") or ""} for r in rows if r.get("code")]
        except Exception:  # noqa: BLE001 - metadata is optional
            _IT_CODES_CACHE = list(_LEGAL_DOCS_IT_FALLBACK)
    return _IT_CODES_CACHE


# ── PWA ───────────────────────────────────────────────────────────────────
# Due file di testo, serviti dalla radice per una ragione precisa: un service
# worker vale solo per la cartella da cui viene servito. Da `/static/sw.js`
# governerebbe soltanto `/static/`, cioe' niente. Da `/sw.js` governa il sito.


# ── notifiche push ────────────────────────────────────────────────────────


@app.get("/api/push/key")
@login_required_api
def api_push_key():
    """La chiave pubblica con cui il browser lega l'abbonamento a noi."""
    return jsonify({"key": push_mod.VAPID_PUBLIC_KEY,
                    "enabled": push_mod.configurato()})


@app.post("/api/push/subscribe")
@login_required_api
def api_push_subscribe():
    d = request.get_json(force=True, silent=True) or {}
    endpoint = (d.get("endpoint") or "").strip()
    keys = d.get("keys") or {}
    p256dh = (keys.get("p256dh") or "").strip()
    auth = (keys.get("auth") or "").strip()
    if not (endpoint and p256dh and auth):
        return jsonify({"error": "incomplete subscription"}), 400
    storage.save_push_subscription(
        request.user.id, endpoint, p256dh, auth,  # type: ignore[attr-defined]
        (request.headers.get("User-Agent") or "")[:300],
    )
    return jsonify({"ok": True})


@app.post("/api/push/unsubscribe")
@login_required_api
def api_push_unsubscribe():
    d = request.get_json(force=True, silent=True) or {}
    endpoint = (d.get("endpoint") or "").strip()
    if endpoint:
        storage.delete_push_subscription(endpoint)
    return jsonify({"ok": True})


@app.post("/api/push/test")
@login_required_api
def api_push_test():
    """Manda una notifica di prova a chi la chiede: senza, l'utente non ha
    modo di sapere se ha davvero attivato qualcosa."""
    push_mod.avvisa(storage, request.user.id,  # type: ignore[attr-defined]
                    "Super Avokati",
                    "Njoftimet janë aktive. Do të të lajmërojmë kur analiza të jetë gati.",
                    url="/", tag="test")
    return jsonify({"ok": True, "enabled": push_mod.configurato()})


@app.get("/manifest.webmanifest")
def pwa_manifest():
    """Il manifest, con il tipo MIME giusto (Flask non conosce .webmanifest)."""
    return send_from_directory(
        app.static_folder, "manifest.webmanifest",
        mimetype="application/manifest+json",
    )


@app.get("/sw.js")
def pwa_service_worker():
    """Il service worker. `max-age=0`: un service worker sbagliato che resta
    in cache e' un problema che non si risolve a distanza."""
    resp = send_from_directory(app.static_folder, "sw.js",
                               mimetype="application/javascript")
    resp.headers["Cache-Control"] = "no-cache, max-age=0"
    resp.headers["Service-Worker-Allowed"] = "/"
    return resp


@app.route("/")
@login_required_page
def index() -> str:
    _ensure_loaded()
    user = current_user()
    _juris = _active_jurisdiction(user)
    if _juris == "IT" and _INDEX_IT is not None:
        _codes = _legal_docs_it()
        _total_articles = len(_INDEX_IT.articles)
    else:
        _codes = [{"code": d.code, "title": d.title_sq, "area": d.area}
                  for d in LEGAL_DOCUMENTS]
        _total_articles = len(_INDEX.articles)
    return render_template(
        "index.html",
        total_articles=_total_articles,
        num_codes=len(_codes),
        has_brain=bool(_BRAIN),
        backend_name=_BRAIN.backend.name if _BRAIN else None,
        codes=_codes,
        username=user.username,
        user_id=user.id,
        is_admin=user.is_admin,
        profession=getattr(user, "profession", "avokat"),
        modules=sorted(storage.user_modules(user)),
        jurisdiction=_juris,
        ui_lang=("it" if _juris == "IT" else "sq"),
        jurisdictions=sorted(storage.user_jurisdictions(user)),
        cascade_event_types=pro_mod.cascade_event_types(),
        act_types=[{"key": k, "label": v} for k, v in pro_mod.ACT_TYPES.items()],
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

def require_module(*mods):
    """Gate an endpoint to users entitled to >=1 of `mods` (admin always
    passes — storage.user_modules returns all for admins). Stack BELOW
    @login_required_api so request.user is already set."""
    from functools import wraps as _wraps

    def _deco(fn):
        @_wraps(fn)
        def _wrapper(*args, **kwargs):
            u = getattr(request, "user", None)
            if u is None:
                return jsonify({"error": "unauthorized"}), 401
            if not (set(mods) & storage.user_modules(u)):
                return jsonify({"error": "Ky mjet nuk përfshihet në abonimin tuaj.",
                                "need_module": list(mods)}), 403
            return fn(*args, **kwargs)
        return _wrapper
    return _deco


# ── Freno ai tentativi di password ────────────────────────────────────
#
# Due contatori: per utenza e per indirizzo. Uno solo non basta —
# quello per utenza lascia passare chi prova UNA password su mille nomi
# diversi, quello per indirizzo punisce uno studio intero dietro un IP solo.
# Per UTENZA: chi prova a entrare in un account preciso ha 5 colpi.
_TENTATIVI_MAX = int(os.environ.get("LOGIN_MAX_TENTATIVI", "5"))
# Per INDIRIZZO: piu' alto di proposito. Uno studio con dieci avvocati esce da
# un IP solo, e con la stessa soglia si bloccherebbero a vicenda — difesa che
# fa perdere il cliente invece dell'attaccante. Qui serve solo a fermare chi
# prova una password su mille utenze: 20 in un quarto d'ora e' un muro per
# quello e non si sente in uno studio vero.
_TENTATIVI_MAX_IP = int(os.environ.get("LOGIN_MAX_TENTATIVI_IP", "20"))
_FINESTRA_S = int(os.environ.get("LOGIN_FINESTRA_S", "900"))      # 15 minuti
_BLOCCO_S = int(os.environ.get("LOGIN_BLOCCO_S", "900"))          # 15 minuti
_tentativi_login: dict[str, list[float]] = {}
_lock_tentativi = threading.Lock()


def _chiavi_tentativo(username: str) -> list[str]:
    ip = (request.headers.get("X-Forwarded-For", "").split(",")[0].strip()
          or request.remote_addr or "?")
    return ["u:" + (username or "").lower(), "ip:" + ip]


def _login_bloccato(username: str) -> int:
    """Secondi di attesa rimasti, 0 se puo' provare."""
    ora = time.time()
    with _lock_tentativi:
        for k in _chiavi_tentativo(username):
            recenti = [t for t in _tentativi_login.get(k, []) if ora - t < _FINESTRA_S]
            _tentativi_login[k] = recenti
            soglia = _TENTATIVI_MAX_IP if k.startswith("ip:") else _TENTATIVI_MAX
            if len(recenti) >= soglia:
                resta = int(_BLOCCO_S - (ora - recenti[-1]))
                if resta > 0:
                    return resta
                _tentativi_login[k] = []      # il blocco si e' sciolto
    return 0


def _segna_fallito(username: str) -> None:
    ora = time.time()
    with _lock_tentativi:
        for k in _chiavi_tentativo(username):
            _tentativi_login.setdefault(k, []).append(ora)
        # una pulizia ogni tanto, per non tenere in memoria chiavi morte
        if len(_tentativi_login) > 5000:
            for k in list(_tentativi_login):
                if not [t for t in _tentativi_login[k] if ora - t < _FINESTRA_S]:
                    _tentativi_login.pop(k, None)


def _azzera_tentativi(username: str) -> None:
    """Chi entra ha dimostrato di essere lui: gli errori di prima non contano."""
    with _lock_tentativi:
        for k in _chiavi_tentativo(username):
            _tentativi_login.pop(k, None)


@app.post("/api/login")
def api_login():
    _ensure_loaded()
    data = request.get_json(force=True, silent=True) or {}
    username = (data.get("username") or "").strip()
    password = data.get("password") or ""
    if not username or not password:
        return jsonify({"error": "missing credentials"}), 400
    # Il freno scatta PRIMA di controllare la password: cosi' non si puo'
    # usare il tempo di risposta per capire se un'utenza esiste.
    _attesa = _login_bloccato(username)
    if _attesa:
        log.warning("login bloccato per %r: troppi tentativi", username)
        return jsonify({
            "error": ("Shumë përpjekje. Provo përsëri pas %d minutash."
                      % max(1, _attesa // 60)),
            "retry_after": _attesa,
        }), 429
    user = authenticate(username, password)
    if user is None:
        from .auth import login_reason
        reason = login_reason(username, password)
        if reason:
            msg = {
                "suspended": "Llogaria juaj është pezulluar. Kontaktoni studion.",
                "demo_expired": "Demo ka skaduar.",
                "plan_expired": "Abonimi juaj ka skaduar. Kontaktoni për ta rinovuar.",
            }.get(reason, "Qasja është bllokuar.")
            log.info("blocked login for %r: %s", username, reason)
            return jsonify({"error": msg, "blocked": reason}), 403
        log.info("failed login for %r", username)
        _segna_fallito(username)
        return jsonify({"error": "invalid credentials"}), 401
    _azzera_tentativi(username)
    login_user(user)
    try:
        from flask import session as _sess
        _lang = str(data.get("lang") or "").strip().lower()
        _chosen = "IT" if _lang == "it" else ("AL" if _lang == "sq" else "")
        if _chosen and _chosen in storage.user_jurisdictions(user):
            _sess["jurisdiction"] = _chosen
    except Exception:  # noqa: BLE001
        pass
    log.info("login ok: %r", user.username)
    return jsonify({"ok": True, "user": {"username": user.username,
                                         "is_admin": user.is_admin}})


@app.post("/api/provision-demo")
def api_provision_demo():
    """Server-to-server: AALA calls this when an admin approves a legal demo
    lead. Creates/refreshes a time-limited trial account (username=email,
    password=code). Guarded by a shared secret; reachable only on localhost."""
    secret = os.environ.get("DEMO_PROVISION_SECRET", "")
    if not secret or request.headers.get("X-Provision-Secret", "") != secret:
        return jsonify({"error": "forbidden"}), 403
    data = request.get_json(force=True, silent=True) or {}
    email = (data.get("email") or "").strip()
    code = (data.get("code") or "").strip()
    try:
        hours = int(data.get("hours") or 6)
    except (TypeError, ValueError):
        hours = 6
    months = data.get("months")
    try:
        months = int(months) if months else None
    except (TypeError, ValueError):
        months = None
    modules = data.get("modules")
    if not isinstance(modules, list):
        modules = None
    if not email or not code:
        return jsonify({"error": "missing email/code"}), 400
    from .auth import hash_password
    try:
        expires = storage.provision_account(email, hash_password(code),
                                             modules=modules, months=months, hours=hours)
    except Exception as exc:  # noqa: BLE001 - best-effort provisioning
        log.warning("provision failed for %r: %s", email, exc)
        return jsonify({"error": "provision failed"}), 500
    return jsonify({"ok": True, "expires_at": expires, "paid": bool(months)})


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
        "id": u.id,
        "username": u.username,
        "is_admin": u.is_admin,
    })


# ── Bolla Segretaria (assistant AI: agjenda + shkrim me konfirmim) ─────────

@app.post("/api/secretary/message")
@login_required_api
def api_secretary_message():
    _ensure_loaded()
    if _BRAIN is None:
        return jsonify({"error": "brain unavailable"}), 503
    user = request.user  # type: ignore[attr-defined]
    data = request.get_json(silent=True) or {}
    messages = data.get("messages")
    if not isinstance(messages, list) or not messages:
        return jsonify({"error": "messages required"}), 400
    clean = []
    for m in messages[-12:]:
        if not isinstance(m, dict):
            continue
        role = "assistant" if m.get("role") == "assistant" else "user"
        content = str(m.get("content") or "").strip()
        if content:
            clean.append({"role": role, "content": content[:4000]})
    if not clean:
        return jsonify({"error": "empty message"}), 400
    result = secretary_mod.handle_message(_BRAIN, user.id, clean)
    return jsonify(result)


@app.post("/api/secretary/execute")
@login_required_api
def api_secretary_execute():
    user = request.user  # type: ignore[attr-defined]
    data = request.get_json(silent=True) or {}
    action = data.get("action")
    if not isinstance(action, dict):
        return jsonify({"error": "action required"}), 400
    result = secretary_mod.execute_action(user.id, action)
    return jsonify(result), (200 if result.get("ok") else 400)


# ── firm (studio) API ──────────────────────────────────────────────────────

def _firm_payload(firm: storage.Firm) -> dict:
    return {
        "id": firm.id, "name": firm.name, "slug": firm.slug,
        "owner_id": firm.owner_id, "is_personal": firm.is_personal,
        "created_at": firm.created_at,
    }


def _member_payload(m: storage.FirmMember) -> dict:
    return {
        "id": m.id, "user_id": m.user_id, "username": m.username,
        "role": m.role, "role_label": storage.ROLE_LABELS.get(m.role, m.role),
        "status": m.status, "joined_at": m.joined_at,
    }


@app.get("/api/firm")
@login_required_api
def api_get_firm():
    """Active workspace + members + the caller's role/permissions."""
    firm = request.firm  # type: ignore[attr-defined]
    role = request.role  # type: ignore[attr-defined]
    if firm is None:
        return jsonify({"firm": None, "members": [], "role": None,
                        "permissions": {}})
    members = storage.list_members(firm.id)
    return jsonify({
        "firm": _firm_payload(firm),
        "members": [_member_payload(m) for m in members],
        "role": role,
        "role_label": storage.ROLE_LABELS.get(role or "", ""),
        "permissions": storage.ROLE_PERMISSIONS.get(role or "", {}),
        "available_roles": [
            {"key": r, "label": storage.ROLE_LABELS[r]}
            for r in storage.FIRM_ROLES if r != "owner"
        ],
    })


@app.get("/api/firm/list")
@login_required_api
def api_list_firms():
    user = request.user  # type: ignore[attr-defined]
    active = request.firm  # type: ignore[attr-defined]
    firms = storage.list_firms_for_user(user.id)
    return jsonify({
        "active_firm_id": active.id if active else None,
        "firms": [_firm_payload(f) for f in firms],
    })


@app.post("/api/firm")
@login_required_api
def api_create_firm():
    """Create a new firm. Caller becomes the owner."""
    user = request.user  # type: ignore[attr-defined]
    data = request.get_json(force=True, silent=True) or {}
    name = (data.get("name") or "").strip()
    if not name:
        return jsonify({"error": "name required"}), 400
    try:
        firm = storage.create_firm(name, user.id)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    storage.set_active_firm(user.id, firm.id)
    log.info("firm created: %s by user %s", firm.slug, user.username)
    return jsonify({"firm": _firm_payload(firm)}), 201


@app.post("/api/firm/switch")
@login_required_api
def api_switch_firm():
    user = request.user  # type: ignore[attr-defined]
    data = request.get_json(force=True, silent=True) or {}
    firm_id = data.get("firm_id")
    if not isinstance(firm_id, int):
        return jsonify({"error": "firm_id must be int"}), 400
    if not storage.set_active_firm(user.id, firm_id):
        return jsonify({"error": "not a member of that firm"}), 403
    firm = storage.get_firm(firm_id)
    return jsonify({"firm": _firm_payload(firm) if firm else None})


@app.post("/api/firm/members")
@login_required_api
@require_permission("manage_members")
def api_add_member():
    """Invite by username + role. The user must already exist."""
    firm = request.firm  # type: ignore[attr-defined]
    if firm is None:
        return jsonify({"error": "no active firm"}), 400
    data = request.get_json(force=True, silent=True) or {}
    username = (data.get("username") or "").strip()
    role = (data.get("role") or "lawyer").strip()
    if not username:
        return jsonify({"error": "username required"}), 400
    if role == "owner":
        return jsonify({"error": "cannot grant owner via invite"}), 400
    if role not in storage.FIRM_ROLES:
        return jsonify({"error": f"unknown role: {role}"}), 400
    target = storage.get_user_by_username(username)
    if target is None:
        return jsonify({"error": "user not found"}), 404
    member = storage.add_member(firm.id, target.id, role)
    log.info("member added: %s as %s in firm %s", username, role, firm.slug)
    return jsonify({"member": _member_payload(member)}), 201


@app.patch("/api/firm/members/<int:member_id>")
@login_required_api
@require_permission("manage_members")
def api_update_member_role(member_id: int):
    firm = request.firm  # type: ignore[attr-defined]
    if firm is None:
        return jsonify({"error": "no active firm"}), 400
    data = request.get_json(force=True, silent=True) or {}
    new_role = (data.get("role") or "").strip()
    if new_role not in storage.FIRM_ROLES:
        return jsonify({"error": f"unknown role: {new_role}"}), 400
    try:
        ok = storage.update_member_role(firm.id, member_id, new_role)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    if not ok:
        return jsonify({"error": "cannot change role (last owner or not found)"}), 400
    return jsonify({"ok": True, "role": new_role})


@app.get("/api/events/<event_id>/substitutes")
@login_required_api
def api_event_substitutes(event_id: str):
    """Suggest who could cover this hearing if the assignee is unavailable.

    Visible to anyone in the firm — useful for the owner planning coverage,
    but also for the assignee themselves who needs to find a replacement
    when sick. Returns 404 when the event isn't in a firm context.
    """
    firm = request.firm  # type: ignore[attr-defined]
    if firm is None:
        return jsonify({"error": "no active firm"}), 400
    candidates = storage.find_substitutes_for_event(event_id, firm.id)
    if candidates is None:
        return jsonify({"error": "event not found or not firm-scoped"}), 404
    return jsonify({"event_id": event_id, "candidates": candidates})


@app.get("/api/firm/capacity")
@login_required_api
@require_permission("all_cases")
def api_firm_capacity():
    """Per-member workload snapshot. Owner/partner-only — capacity is a
    management view; rank-and-file shouldn't see peers' load."""
    firm = request.firm  # type: ignore[attr-defined]
    if firm is None:
        return jsonify({"error": "no active firm"}), 400
    try:
        horizon = max(1, min(30, int(request.args.get("days", 7))))
    except (TypeError, ValueError):
        horizon = 7
    return jsonify({
        "firm": _firm_payload(firm),
        "horizon_days": horizon,
        "members": storage.firm_capacity_snapshot(firm.id, horizon_days=horizon),
    })


@app.post("/api/firm/conflict-check")
@login_required_api
def api_conflict_check():
    """Search the firm's case-parties index for a name. Returns matches
    with case context so the lawyer can decide whether taking on the
    counter-party would be a conflict.

    Visible to anyone in the firm — early detection beats role-gating
    here, and the search returns only metadata (no case content)."""
    firm = request.firm  # type: ignore[attr-defined]
    if firm is None:
        return jsonify({"error": "no active firm"}), 400
    data = request.get_json(force=True, silent=True) or {}
    query = (data.get("query") or "").strip()
    if len(query) < 2:
        return jsonify({"error": "query too short (min 2 chars)"}), 400
    matches = storage.search_parties_in_firm(firm.id, query)
    return jsonify({"query": query, "matches": matches,
                    "count": len(matches)})


@app.delete("/api/firm/members/<int:member_id>")
@login_required_api
@require_permission("manage_members")
def api_remove_member(member_id: int):
    firm = request.firm  # type: ignore[attr-defined]
    if firm is None:
        return jsonify({"error": "no active firm"}), 400
    if not storage.remove_member(firm.id, member_id):
        return jsonify({"error": "cannot remove (owner or not found)"}), 400
    return jsonify({"ok": True})


@app.get("/api/firm/today")
@login_required_api
def api_daily_brief():
    """Aggregate the active member's day: imminent events, pending drafts
    they need to review or that need their feedback, cases without recent
    activity, and a count of cases per stage. Used by the home widget."""
    user = request.user  # type: ignore[attr-defined]
    firm = request.firm  # type: ignore[attr-defined]
    role = request.role  # type: ignore[attr-defined]
    from datetime import datetime, timedelta
    now = datetime.now(UTC)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    horizon = today_start + timedelta(days=7)

    # Visible cases (firm-aware)
    if firm is None:
        my_cases = storage.list_cases(user.id)
    else:
        my_cases = storage.list_cases_for_member(user.id, firm.id)

    # Events in next 7 days, scoped to my visible cases
    visible_ids = {c.id for c in my_cases}
    events = storage.list_events(
        user.id,
        start=today_start.isoformat(),
        end=horizon.isoformat(),
    )
    upcoming_events = [
        {"id": e.id, "case_id": e.case_id, "title": e.title,
         "kind": e.kind, "starts_at": e.starts_at,
         "location": e.location}
        for e in events if not e.case_id or e.case_id in visible_ids
    ]

    # Pending drafts: as reviewer (if can_review) and as author (always)
    can_review = bool(firm and storage.ROLE_PERMISSIONS.get(role or "", {})
                      .get("all_cases", False))
    drafts_to_review: list[dict] = []
    my_pending_drafts: list[dict] = []
    if firm is not None:
        if can_review:
            queue = storage.list_review_queue(firm.id, status="pending")
            drafts_to_review = [_draft_payload(d) for d in queue
                                if d.author_id != user.id]
        author_pending = storage.list_review_queue(
            firm.id, status="pending", author_id=user.id,
        )
        my_pending_drafts = [_draft_payload(d) for d in author_pending]

    # Stage breakdown — gives a quick glance at the studio's pipeline
    stage_counts: dict[str, int] = {s: 0 for s in storage.CASE_STAGES}
    for c in my_cases:
        stage_counts[c.stage] = stage_counts.get(c.stage, 0) + 1

    # Stale cases — visible to me but no message in last 14 days
    stale_threshold = now - timedelta(days=14)
    stale: list[dict] = []
    for c in my_cases:
        try:
            last = datetime.fromisoformat(c.updated_at.replace("Z", "+00:00"))
        except Exception:
            continue
        if last < stale_threshold and c.stage not in ("execution",):
            stale.append({"id": c.id, "title": c.title,
                          "stage": c.stage,
                          "stage_label": storage.CASE_STAGE_LABELS_SQ.get(c.stage, c.stage),
                          "updated_at": c.updated_at,
                          "days_silent": (now - last).days})
    stale.sort(key=lambda x: -x["days_silent"])

    return jsonify({
        "now": now.isoformat(),
        "user": user.username,
        "firm": _firm_payload(firm) if firm else None,
        "role": role,
        "can_review": can_review,
        "upcoming_events": upcoming_events[:10],
        "drafts_to_review": drafts_to_review[:10],
        "my_pending_drafts": my_pending_drafts[:10],
        "stage_counts": stage_counts,
        "stale_cases": stale[:5],
        "total_cases": len(my_cases),
    })


# ── intake AI ──────────────────────────────────────────────────────────────

INTAKE_SYSTEM_NEXT = (
    "Ti je një asistent ligjor profesional për një studio avokatie shqiptare. "
    "Po kryen INTAKE-n e parë me një klient potencial. Detyra: bëj NJË pyetje "
    "të vetme, të qartë, VETËM në SHQIP — pyetjen që do të ndihmonte më "
    "shumë avokatin për të kuptuar rastin më pas. Mos jep këshilla ligjore. "
    "Mos supozo. Bëj vetëm pyetje informative.\n\n"
    "RREGULLA TË RËNDËSISHME:\n"
    "- Çdo pyetje dhe çdo `why` DUHET të jenë VETËM në shqip standard (jo "
    "italisht, anglisht etj.).\n"
    "- Mos përsërit pyetje për tema që janë mbuluar tashmë në bisedë.\n"
    "- Nëse përgjigja e fundit nuk i përgjigjet pyetjes së fundit, ribëje "
    "pyetjen me fjalë të tjera ose kërkoji klientit ta sqarojë.\n"
    "- Pyetjet të jenë konkrete dhe lehtësisht të kuptueshme nga një klient "
    "i thjeshtë (jo terminologji ligjore e thelluar).\n\n"
    "Tema që DUHEN mbuluar (në rendin që ka kuptim sipas përgjigjeve):\n"
    "1. Identiteti i klientit (emri i plotë, kontakt nëse mungon)\n"
    "2. Fusha ligjore (civil/penal/familje/punë/tregtar/administrativ)\n"
    "3. Palët e tjera të përfshira (kundërshtari, dëshmitarë)\n"
    "4. Faktet kryesore (çfarë ndodhi, kur, ku)\n"
    "5. Datat / afatet (skadenca procedurale, urdhra gjykate)\n"
    "6. Provat ekzistuese (dokumente, dëshmitarë)\n"
    "7. Procedurat ekzistuese (a është nisur ndonjë çështje gjyqësore?)\n"
    "8. Pritshmëria / qëllimi (çfarë do klienti — dëmshpërblim, anulim, etj.)\n\n"
    "Pasi të kesh mbledhur ÇKA NEVOJITET (zakonisht 6-8 pyetje), kthe "
    "{\"done\": true} pa pyetje. Mos kalo 10 pyetje totale.\n\n"
    "PËRGJIGJU GJITHMONË VETËM ME JSON të vlefshëm:\n"
    "{\"question\": \"...\", \"why\": \"shpjegim i shkurtër pse e bën këtë "
    "pyetje (1 fjali)\", \"done\": false}\n"
    "ose\n"
    "{\"done\": true}"
)

INTAKE_SYSTEM_BRIEF = (
    "Ti je një asistent ligjor profesional. Po krijon një PËRMBLEDHJE "
    "STRUKTURORE të intake-s, që do të lexohet nga avokati që do të "
    "marrë rastin. Shkruaj qartë, pa zbukurime, pa këshilla ligjore.\n\n"
    "RREGULL ABSOLUT I GJUHËS: Çdo vlerë teksti në JSON DUHET të jetë "
    "VETËM në SHQIP — duke përfshirë title, facts, deadlines, evidence, "
    "client_goal, open_questions, suggested_next_steps. NUK lejohet "
    "italisht, anglisht ose ndonjë gjuhë tjetër. Edhe nëse përgjigjet e "
    "klientit përmbajnë fjalë në gjuhë të tjera, përmbledhja është "
    "VETËM në shqip standard.\n\n"
    "PËRGJIGJU VETËM ME JSON të vlefshëm me këtë skemë:\n"
    "{\n"
    '  "title": "Titull i shkurtër në SHQIP (max 60 karaktere)",\n'
    '  "area": "civil|penal|familje|punë|tregtar|administrativ|tjetër",\n'
    '  "client": "Emri dhe roli i klientit",\n'
    '  "counterparty": "Pala kundërshtare ose null",\n'
    '  "facts": "Përshkrim i fakteve në SHQIP (3-6 fjali)",\n'
    '  "deadlines": "Afate / data kritike në SHQIP ose null",\n'
    '  "evidence": "Provat e disponueshme në SHQIP ose null",\n'
    '  "client_goal": "Çfarë kërkon klienti — në SHQIP",\n'
    '  "open_questions": ["Pyetje në SHQIP për avokatin"],\n'
    '  "urgency": "low|medium|high",\n'
    '  "suggested_next_steps": ["Hapi në SHQIP", "Hapi 2 në SHQIP"]\n'
    "}"
)


INTAKE_SYSTEM_NEXT_IT = (
    "Sei un assistente legale professionale per uno studio legale italiano. "
    "Stai conducendo il primo INTAKE con un potenziale cliente. Compito: fai "
    "UNA sola domanda, chiara, SOLO in ITALIANO — la domanda che aiuterebbe "
    "di più l'avvocato a capire il caso. Non dare consulenza legale. Non "
    "dare nulla per scontato. Fai solo domande informative.\n\n"
    "REGOLE IMPORTANTI:\n"
    "- Ogni domanda e ogni `why` DEVONO essere SOLO in italiano.\n"
    "- Non ripetere domande su temi già coperti nella conversazione.\n"
    "- Se l'ultima risposta non risponde all'ultima domanda, riformula la "
    "domanda o chiedi al cliente di chiarire.\n"
    "- Le domande devono essere concrete e comprensibili da un cliente "
    "comune (niente terminologia giuridica approfondita).\n\n"
    "Temi da coprire (nell'ordine che ha senso in base alle risposte):\n"
    "1. Identita del cliente (nome completo, contatto se manca)\n"
    "2. Materia giuridica (civile/penale/famiglia/lavoro/commerciale/"
    "amministrativo)\n"
    "3. Altre parti coinvolte (controparte, testimoni)\n"
    "4. Fatti principali (cosa e successo, quando, dove)\n"
    "5. Date / termini (scadenze procedurali, provvedimenti del giudice)\n"
    "6. Prove esistenti (documenti, testimoni)\n"
    "7. Procedimenti gia avviati (e stata iniziata una causa?)\n"
    "8. Aspettativa / obiettivo (cosa vuole il cliente — risarcimento, "
    "annullamento, ecc.)\n\n"
    "Quando hai raccolto QUANTO SERVE (di norma 6-8 domande), restituisci "
    "{\"done\": true} senza domanda. Non superare 10 domande in totale.\n\n"
    "RISPONDI SEMPRE E SOLO CON JSON valido:\n"
    "{\"question\": \"...\", \"why\": \"breve spiegazione del perché fai "
    "questa domanda (1 frase)\", \"done\": false}\n"
    "oppure\n"
    "{\"done\": true}"
)

INTAKE_SYSTEM_BRIEF_IT = (
    "Sei un assistente legale professionale. Stai creando un RIEPILOGO "
    "STRUTTURATO dell'intake, che sarà letto dall'avvocato che prenderà il "
    "caso. Scrivi in modo chiaro, senza abbellimenti, senza consulenza "
    "legale.\n\n"
    "REGOLA ASSOLUTA DI LINGUA: ogni valore testuale nel JSON DEVE essere "
    "SOLO in ITALIANO — inclusi title, facts, deadlines, evidence, "
    "client_goal, open_questions, suggested_next_steps. Anche se le "
    "risposte del cliente contengono parole in altre lingue, il riepilogo "
    "e SOLO in italiano.\n\n"
    "RISPONDI SOLO CON JSON valido con questo schema:\n"
    "{\n"
    '  "title": "Titolo breve in ITALIANO (max 60 caratteri)",\n'
    '  "area": "civile|penale|famiglia|lavoro|commerciale|amministrativo|altro",\n'
    '  "client": "Nome e ruolo del cliente",\n'
    '  "counterparty": "Controparte oppure null",\n'
    '  "facts": "Descrizione dei fatti in ITALIANO (3-6 frasi)",\n'
    '  "deadlines": "Termini / date critiche in ITALIANO oppure null",\n'
    '  "evidence": "Prove disponibili in ITALIANO oppure null",\n'
    '  "client_goal": "Cosa chiede il cliente — in ITALIANO",\n'
    '  "open_questions": ["Domanda in ITALIANO per l\'avvocato"],\n'
    '  "urgency": "low|medium|high",\n'
    '  "suggested_next_steps": ["Passo in ITALIANO", "Passo 2 in ITALIANO"]\n'
    "}"
)


def _intake_prompts():
    """(system_next, system_brief, user_prefix) per la giurisdizione attiva."""
    try:
        if _active_jurisdiction(getattr(request, "user", None)) == "IT":
            return (INTAKE_SYSTEM_NEXT_IT, INTAKE_SYSTEM_BRIEF_IT,
                    "Conversazione finora:\n{t}\n\nFai la prossima domanda "
                    "oppure restituisci {{\"done\": true}} se sei pronto per "
                    "il riepilogo.")
    except Exception:  # noqa: BLE001
        pass
    return (INTAKE_SYSTEM_NEXT, INTAKE_SYSTEM_BRIEF,
            "Bisedoja deri tani:\n{t}\n\nBëj pyetjen tjetër ose kthe "
            "{{\"done\": true}} nëse je gati për përmbledhje.")


def _format_intake_brief(brief: dict) -> str:
    """Render the structured brief as the case's first user message."""
    def _line(label, val):
        if not val:
            return ""
        return f"**{label}:** {val}\n"

    parts = ["# Intake klienti\n"]
    parts.append(_line("Klienti", brief.get("client")))
    parts.append(_line("Pala kundërshtare", brief.get("counterparty")))
    parts.append(_line("Fusha", brief.get("area")))
    parts.append(_line("Urgjenca", brief.get("urgency")))
    parts.append(_line("Afate", brief.get("deadlines")))
    parts.append("\n## Faktet\n")
    parts.append((brief.get("facts") or "—") + "\n")
    parts.append("\n## Provat\n")
    parts.append((brief.get("evidence") or "—") + "\n")
    parts.append("\n## Kërkesa e klientit\n")
    parts.append((brief.get("client_goal") or "—") + "\n")
    open_q = brief.get("open_questions") or []
    if open_q:
        parts.append("\n## Pyetje të hapura\n")
        for q in open_q:
            parts.append(f"- {q}\n")
    next_steps = brief.get("suggested_next_steps") or []
    if next_steps:
        parts.append("\n## Hapat e sugjeruar\n")
        for s in next_steps:
            parts.append(f"- {s}\n")
    return "".join(p for p in parts if p)


def _intake_history_to_text(history: list[dict]) -> str:
    if not history:
        return "(ende asnjë përgjigje)"
    lines = []
    for i, qa in enumerate(history, 1):
        q = (qa.get("q") or "").strip()
        a = (qa.get("a") or "").strip()
        lines.append(f"P{i}: {q}\nR{i}: {a}")
    return "\n\n".join(lines)


@app.post("/api/firm/intake")
@login_required_api
def api_firm_intake():
    """AI-driven client intake. Two actions:
      - "next": given Q&A history, return next question (or done=true).
      - "finalize": produce structured brief, create case, post brief
        as first message, return new case_id.
    Requires create_case permission (paralegal/assistant cannot finalize)."""
    user = request.user  # type: ignore[attr-defined]
    firm = request.firm  # type: ignore[attr-defined]
    role = request.role  # type: ignore[attr-defined]

    if _BRAIN is None:
        return jsonify({"error": "brain not available"}), 503

    data = request.get_json(force=True, silent=True) or {}
    action = (data.get("action") or "next").strip()
    history = data.get("history") or []
    if not isinstance(history, list):
        return jsonify({"error": "history must be a list"}), 400

    transcript = _intake_history_to_text(history)

    if action == "next":
        _sys_next, _sys_brief, _tpl = _intake_prompts()
        prompt = _tpl.format(t=transcript)
        try:
            raw = _BRAIN.backend.complete(
                system=_sys_next,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=400,
                medium=True,  # Sonnet — wizard conversazionale per il cliente
            )
        except Exception as exc:
            log.warning("intake next failed: %s", exc)
            return jsonify({"error": "AI call failed"}), 502
        try:
            parsed = _intake_parse_json(raw)
        except ValueError:
            return jsonify({"error": "AI returned invalid JSON",
                            "raw": raw[:500]}), 502
        if parsed.get("done"):
            return jsonify({"done": True, "step": len(history) + 1})
        return jsonify({
            "done": False,
            "question": str(parsed.get("question") or "").strip(),
            "why": str(parsed.get("why") or "").strip(),
            "step": len(history) + 1,
        })

    if action == "finalize":
        if not history:
            return jsonify({"error": "no answers to finalize"}), 400
        # Permission gate — only members who can create cases get to ship
        # a new file from intake. Lower-tier roles can still RUN the wizard
        # (for prep), but finalization needs create_case.
        if firm is not None and not firm.is_personal:
            if not storage.ROLE_PERMISSIONS.get(role or "", {}).get(
                "create_case", False
            ):
                return jsonify({"error": "forbidden",
                                "needed": "create_case",
                                "your_role": role}), 403
        prompt = (
            f"Bisedoja e plotë e intake-s:\n{transcript}\n\n"
            f"Tani prodho JSON-in e përmbledhjes së strukturuar."
        )
        try:
            # V8.10: brief finale è il documento che legge l'avvocato →
            # Opus default, niente shortcut
            raw = _BRAIN.backend.complete(
                system=_intake_prompts()[1],
                messages=[{"role": "user", "content": prompt}],
                max_tokens=1200,
            )
        except Exception as exc:
            log.warning("intake finalize failed: %s", exc)
            return jsonify({"error": "AI call failed"}), 502
        try:
            brief = _intake_parse_json(raw)
        except ValueError:
            return jsonify({"error": "AI returned invalid JSON",
                            "raw": raw[:500]}), 502
        title = (brief.get("title") or "").strip() or "Rast nga intake"
        title = title[:80]
        firm_id = firm.id if firm else None
        case = storage.create_case(user.id, title, firm_id=firm_id)
        body = _format_intake_brief(brief)
        storage.add_message(case.id, "user", body, kind="intake")
        return jsonify({
            "ok": True,
            "case_id": case.id,
            "title": case.title,
            "brief": brief,
        })

    return jsonify({"error": f"unknown action: {action}"}), 400


def _intake_parse_json(raw: str) -> dict:
    """Robust JSON extraction from a fast-model response."""
    import json as _json
    import re as _re
    if not raw:
        raise ValueError("empty response")
    s = raw.strip()
    # Strip markdown code fences
    if s.startswith("```"):
        s = _re.sub(r"^```(?:json)?\s*", "", s)
        s = _re.sub(r"\s*```$", "", s)
    # First brace-balanced object
    try:
        return _json.loads(s)
    except Exception:
        pass
    m = _re.search(r"\{.*\}", s, _re.DOTALL)
    if not m:
        raise ValueError("no JSON object found")
    return _json.loads(m.group(0))


# ── cases API ──────────────────────────────────────────────────────────────

def _safe_err(exc) -> str:
    """Client-safe error text: keep humanized Albanian messages, but never let
    a vendor name, file path, or traceback reach the user (Tetramorph rule)."""
    msg = str(exc or "")
    low = msg.lower()
    if not msg or any(k in low for k in (
        "claude", "anthropic", "openai", "gemini", "traceback",
        "/app/", "/home/", "/usr/", "/var/", "model", "subprocess",
        "sqlite", "psycopg", "http", "token")):
        return "Gabim teknik i përkohshëm. Provo përsëri pas pak."
    return msg[:200]


def _resolve_case(case_id: str):
    """Firm-aware case fetch — applies role-based visibility when in a firm.

    Falls back to user-scoped (legacy) when the user has no active firm,
    which keeps single-user installs working without migration friction.
    """
    user = request.user  # type: ignore[attr-defined]
    firm = request.firm  # type: ignore[attr-defined]
    if firm is None:
        caso = storage.get_case(case_id, user.id)   # user-scoped legacy fallback
    else:
        caso = storage.get_case_for_member(case_id, user.id, firm.id)
    # Si registra SOLO quando l'accesso e' andato a buon fine: un 404 non e'
    # un accesso, e riempire il registro di tentativi falliti lo renderebbe
    # illeggibile proprio quando serve leggerlo.
    #
    # Qui perche' e' il collo di bottiglia: ogni endpoint che tocca un
    # fascicolo passa da questa funzione. Un aggancio invece di sessanta.
    if caso is not None:
        storage.log_case_access(
            user_id=user.id, username=getattr(user, "username", None),
            case_id=case_id, firm_id=(firm.id if firm else None),
            action="open",
            ip=(request.headers.get("X-Forwarded-For", "").split(",")[0].strip()
                or request.remote_addr),
            user_agent=request.headers.get("User-Agent"),
        )
    return caso


@app.get("/api/cases")
@login_required_api
def api_list_cases():
    user = request.user  # type: ignore[attr-defined]
    firm = request.firm  # type: ignore[attr-defined]
    if firm is None:
        cases = storage.list_cases(user.id)
    else:
        cases = storage.list_cases_for_member(user.id, firm.id)
    return jsonify({"cases": [
        {"id": c.id, "title": c.title,
         "created_at": c.created_at, "updated_at": c.updated_at,
         "creator_id": c.user_id,
         "is_mine": c.user_id == user.id,
         "stage": c.stage,
         "stage_label": storage.CASE_STAGE_LABELS_SQ.get(c.stage, c.stage)}
        for c in cases
    ]})


@app.post("/api/cases")
@login_required_api
def api_create_case():
    user = request.user  # type: ignore[attr-defined]
    firm = request.firm  # type: ignore[attr-defined]
    role = request.role  # type: ignore[attr-defined]
    # Lower-tier roles cannot create cases unilaterally — they can still be
    # assigned to one. The personal firm path (firm.is_personal) bypasses
    # this since a solo user has nothing to gate against.
    if firm is not None and not firm.is_personal:
        if not storage.ROLE_PERMISSIONS.get(role or "", {}).get("create_case", False):
            return jsonify({"error": "forbidden",
                            "needed": "create_case",
                            "your_role": role}), 403
    data = request.get_json(force=True, silent=True) or {}
    title = (data.get("title") or "").strip() or "Rast i ri"
    jurisdiction = (data.get("jurisdiction") or _active_jurisdiction(user)).upper()
    firm_id = firm.id if firm else None
    case = storage.create_case(user.id, title, firm_id=firm_id,
                               jurisdiction=jurisdiction)
    return jsonify({"id": case.id, "title": case.title,
                    "jurisdiction": case.jurisdiction,
                    "created_at": case.created_at, "updated_at": case.updated_at})


@app.post("/api/cases/<case_id>/jurisdiction")
@login_required_api
def api_update_case_jurisdiction(case_id: str):
    user = request.user  # type: ignore[attr-defined]
    case = _resolve_case(case_id)
    if not case:
        return jsonify({"error": "not found"}), 404
    data = request.get_json(force=True, silent=True) or {}
    jurisdiction = (data.get("jurisdiction") or "").upper()
    secondary = (data.get("secondary") or None)
    if jurisdiction not in ("AL", "IT", "EU"):
        return jsonify({"error": "invalid_jurisdiction",
                        "allowed": ["AL", "IT", "EU"]}), 400
    ok = storage.update_case_jurisdiction(case_id, user.id,
                                          jurisdiction, secondary)
    if not ok:
        return jsonify({"error": "not_updated"}), 404
    return jsonify({"id": case_id, "jurisdiction": jurisdiction,
                    "secondary": secondary})


@app.get("/api/cases/<case_id>")
@login_required_api
def api_get_case(case_id: str):
    user = request.user  # type: ignore[attr-defined]
    case = _resolve_case(case_id)
    if not case:
        return jsonify({"error": "not found"}), 404
    messages = storage.list_messages(case_id)
    documents = storage.list_documents(case_id)
    return jsonify({
        "id": case.id,
        "title": case.title,
        "stage": case.stage,
        "stage_label": storage.CASE_STAGE_LABELS_SQ.get(case.stage, case.stage),
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


@app.patch("/api/cases/<case_id>/stage")
@login_required_api
def api_set_case_stage(case_id: str):
    """Update case workflow stage. Must have visibility on the case."""
    case = _resolve_case(case_id)
    if not case:
        return jsonify({"error": "not found"}), 404
    data = request.get_json(force=True, silent=True) or {}
    stage = (data.get("stage") or "").strip()
    if stage not in storage.CASE_STAGES:
        return jsonify({"error": "invalid stage",
                        "allowed": list(storage.CASE_STAGES)}), 400
    if not storage.set_case_stage(case_id, stage):
        return jsonify({"error": "update failed"}), 500
    return jsonify({"ok": True, "stage": stage,
                    "stage_label": storage.CASE_STAGE_LABELS_SQ.get(stage, stage)})


# ── V8.3 client portal (magic-link, read-only) ─────────────────────────────

def _client_payload(cc: storage.ClientContact) -> dict:
    return {
        "id": cc.id, "case_id": cc.case_id, "name": cc.name,
        "phone": cc.phone, "email": cc.email,
        "portal_token": cc.portal_token,
        "portal_url": url_for("client_portal", token=cc.portal_token,
                              _external=True),
        "last_viewed_at": cc.last_viewed_at,
        "created_at": cc.created_at,
    }


def _status_update_payload(u: storage.CaseStatusUpdate) -> dict:
    return {
        "id": u.id, "case_id": u.case_id,
        "author_id": u.author_id, "author_username": u.author_username,
        "body_sq": u.body_sq, "kind": u.kind,
        "source_kind": u.source_kind, "created_at": u.created_at,
    }


@app.get("/api/cases/<case_id>/clients")
@login_required_api
def api_list_clients(case_id: str):
    if _resolve_case(case_id) is None:
        return jsonify({"error": "not found"}), 404
    clients = storage.list_client_contacts_for_case(case_id)
    return jsonify({"clients": [_client_payload(c) for c in clients]})


@app.post("/api/cases/<case_id>/clients")
@login_required_api
def api_add_client(case_id: str):
    """Add a client contact + auto-mint a portal token. Anyone with case
    visibility can do this — the lawyer needs to share access with their
    own client without bottlenecking through the owner."""
    case = _resolve_case(case_id)
    if case is None:
        return jsonify({"error": "not found"}), 404
    firm = request.firm  # type: ignore[attr-defined]
    if firm is None:
        return jsonify({"error": "no active firm"}), 400
    data = request.get_json(force=True, silent=True) or {}
    name = (data.get("name") or "").strip()
    if not name:
        return jsonify({"error": "name required"}), 400
    phone = (data.get("phone") or "").strip() or None
    email = (data.get("email") or "").strip() or None
    try:
        cc = storage.create_client_contact(case_id, firm.id, name, phone, email)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    return jsonify({"client": _client_payload(cc)}), 201


@app.delete("/api/cases/<case_id>/clients/<int:client_id>")
@login_required_api
def api_delete_client(case_id: str, client_id: int):
    if _resolve_case(case_id) is None:
        return jsonify({"error": "not found"}), 404
    if not storage.delete_client_contact(client_id, case_id):
        return jsonify({"error": "not found"}), 404
    return jsonify({"ok": True})


@app.post("/api/cases/<case_id>/clients/<int:client_id>/regenerate-token")
@login_required_api
def api_regenerate_client_token(case_id: str, client_id: int):
    if _resolve_case(case_id) is None:
        return jsonify({"error": "not found"}), 404
    cc = storage.regenerate_portal_token(client_id)
    if cc is None or cc.case_id != case_id:
        return jsonify({"error": "not found"}), 404
    return jsonify({"client": _client_payload(cc)})


# ── V8.3 status updates (lawyer → client) ──────────────────────────────────

@app.get("/api/cases/<case_id>/status-updates")
@login_required_api
def api_list_status_updates(case_id: str):
    if _resolve_case(case_id) is None:
        return jsonify({"error": "not found"}), 404
    items = storage.list_status_updates_for_case(case_id)
    return jsonify({"updates": [_status_update_payload(u) for u in items]})


@app.post("/api/cases/<case_id>/status-updates")
@login_required_api
def api_create_status_update(case_id: str):
    case = _resolve_case(case_id)
    if case is None:
        return jsonify({"error": "not found"}), 404
    firm = request.firm  # type: ignore[attr-defined]
    user = request.user  # type: ignore[attr-defined]
    if firm is None:
        return jsonify({"error": "no active firm"}), 400
    data = request.get_json(force=True, silent=True) or {}
    body_sq = (data.get("body_sq") or "").strip()
    kind = (data.get("kind") or "status").strip()
    source_kind = (data.get("source_kind") or "manual").strip()
    if len(body_sq) < 10:
        return jsonify({"error": "body too short (min 10 chars)"}), 400
    if kind not in storage.CLIENT_UPDATE_KINDS:
        return jsonify({"error": f"invalid kind: {kind}",
                        "allowed": list(storage.CLIENT_UPDATE_KINDS)}), 400
    try:
        u = storage.create_status_update(
            case_id, firm.id, user.id, body_sq,
            kind=kind, source_kind=source_kind,
        )
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    return jsonify({"update": _status_update_payload(u)}), 201


@app.delete("/api/cases/<case_id>/status-updates/<int:update_id>")
@login_required_api
def api_delete_status_update(case_id: str, update_id: int):
    if _resolve_case(case_id) is None:
        return jsonify({"error": "not found"}), 404
    if not storage.delete_status_update(update_id, case_id):
        return jsonify({"error": "not found"}), 404
    return jsonify({"ok": True})


# ── V8.3 jargon→qytetar translator + auto-status (AI) ──────────────────────

JARGON_TRANSLATE_SYSTEM = (
    "Ti je një ndihmës që përkthen GJUHËN LIGJORE TEKNIKE në gjuhë të "
    "thjeshtë, të kuptueshme nga një qytetar pa formim juridik. Lexuesi "
    "është klienti i avokatit — ai do të dijë çfarë po ndodh me rastin e "
    "tij, pa terminologji juridike, pa latinizma, pa nene të cituar.\n\n"
    "RREGULLA:\n"
    "- VETËM në SHQIP standard (jo italisht, anglisht, etj.)\n"
    "- Mos shto KËSHILLA LIGJORE të reja — vetëm RIFORMULIM të tekstit "
    "ekzistues në gjuhë të thjeshtë.\n"
    "- Mos shto pjesë që nuk janë në tekstin origjinal.\n"
    "- 1-3 paragrafë të shkurtër, fjali të qarta.\n"
    "- Përdor 'ne' / 'avokati juaj' / 'ju' kur i drejtohesh klientit.\n"
    "- Shmang fjalët: padi, sentencë, ekzekutim, juridiksion, kompetencë "
    "lëndore, neni X i Kodit Y. Përkthe ato në gjuhë të thjeshtë "
    "('një kërkesë te gjykata', 'vendimi i gjyqtarit', etj.).\n\n"
    "PËRGJIGJU VETËM ME JSON të vlefshëm:\n"
    '{"plain_sq": "tekst i thjeshtuar në SHQIP", '
    '"jargon_terms": ["fjalë teknike që ke përkthyer", ...]}'
)


@app.post("/api/cases/<case_id>/translate-jargon")
@login_required_api
def api_translate_jargon(case_id: str):
    """Plain-Albanian rewrite of legal text — preview, not saved. The
    lawyer can edit the result and then post it via /status-updates."""
    if _resolve_case(case_id) is None:
        return jsonify({"error": "not found"}), 404
    if _BRAIN is None:
        return jsonify({"error": "brain not available"}), 503
    data = request.get_json(force=True, silent=True) or {}
    source_text = (data.get("source_text") or "").strip()
    if len(source_text) < 20:
        return jsonify({"error": "source_text too short (min 20 chars)"}), 400
    if len(source_text) > 4000:
        source_text = source_text[:4000]
    try:
        # V8.10: traduzione registro popolare → Sonnet (qualità albanese)
        raw = _BRAIN.backend.complete(
            system=JARGON_TRANSLATE_SYSTEM,
            messages=[{"role": "user", "content": source_text}],
            max_tokens=900,
            medium=True,
        )
        parsed = _intake_parse_json(raw)
        plain = (parsed.get("plain_sq") or "").strip()
        terms = parsed.get("jargon_terms") or []
        if not plain:
            return jsonify({"error": "no translation produced",
                            "raw": raw[:300]}), 502
        return jsonify({
            "plain_sq": plain,
            "jargon_terms": terms if isinstance(terms, list) else [],
        })
    except Exception as exc:
        log.warning("translate-jargon failed: %s", exc)
        return jsonify({"error": "translation failed",
                        "detail": str(exc)[:200]}), 502


AUTO_STATUS_SYSTEM = (
    "Ti je një asistent që shkruan një LAJM të shkurtër për klientin e "
    "një studio avokatësh. Klienti dëshiron të dijë çfarë po ndodh me "
    "rastin e tij — pa terminologji juridike.\n\n"
    "Të jepet konteksti i rastit (titulli, faza, mesazhi i fundit i "
    "AI-së për avokatin, ngjarjet e ardhshme). Prodho NJË LAJM të vetëm, "
    "i thjeshtë, 2-4 fjali, në SHQIP, që përshkruan: ku janë gjërat "
    "tani, çfarë vjen më pas, dhe nëse klientit i kërkohet diçka.\n\n"
    "RREGULLA:\n"
    "- VETËM SHQIP standard.\n"
    "- Mos cito nene apo terminologji.\n"
    "- Mos premto rezultate konkrete ('do fitoni', 'sigurisht').\n"
    "- Toni: i sjellshëm, profesional, i sinqertë.\n"
    "- Nëse nuk ka risi reale për të raportuar, kthe `body_sq` bosh dhe "
    "ven `kind` = 'status' me një mesazh të përgjithshëm si 'Po vijojmë "
    "punën, do t'ju njoftojmë sapo të ketë lëvizje.'\n\n"
    "PËRGJIGJU VETËM ME JSON:\n"
    '{"body_sq": "lajmi në SHQIP", '
    '"kind": "status|milestone|document_request"}'
)


# ── V8.4 contract review (semaforo + obligations + GDPR) ───────────────────

CONTRACT_REVIEW_SYSTEM = (
    "Ti je një avokat-rishikues kontratash në Shqipëri. Të jepet teksti i "
    "një kontrate. Detyra: prodho një ANALIZË STRUKTURORE që ndihmon "
    "avokatin të identifikojë shpejt rrezikun, detyrimet dhe afatet.\n\n"
    "RREGULLA TË RËNDËSISHME:\n"
    "- VETËM në SHQIP standard për të gjitha vlerat tekstuale.\n"
    "- Lexoje çdo klauzolë dhe vlerësoje me NJË semafor:\n"
    "  • 'ok' (🟢) — klauzolë standarde, e arsyeshme, e rregullt;\n"
    "  • 'watch' (🟡) — klauzolë e pazakontë por e pranueshme — shenoji "
    "    rrezikun edhe pse e nënshkruajshme;\n"
    "  • 'risk' (🔴) — klauzolë me rrezik real ose abuziv — kërkon "
    "    negocim/heqje ose mungon një mbrojtje thelbësore.\n"
    "- Kontrolloji shqip për: penalitete asimetrike, detyrime pa afat, "
    "  klauzola arbitrazhi të padrejtë, transferim të dhënash personale "
    "  pa bazë (GDPR-AL = Ligji 9887/2008 për mbrojtjen e të dhënave), "
    "  pavlefshmëri për shkak të nenit 92/686/911 KC, mungesë force "
    "  madhore, klauzola jurisdiksioni jashtë RSH pa qëllim të qartë.\n"
    "- Identifiko dhe LIST KLAUZOLAT QË MUNGOJNË por janë standarde për "
    "  llojin e kontratës (p.sh. zgjidhje për shkak të mungesës së pagesës "
    "  në një kontratë qiraje, ose afat-prove në një kontratë pune).\n\n"
    "PËRGJIGJU VETËM ME JSON të vlefshëm me këtë skemë:\n"
    "{\n"
    '  "summary": "1-2 fjali përmbledhëse të kontratës (në SHQIP)",\n'
    '  "contract_kind": "qira|punës|shitje|sherbim|huapërdorje|tregtar|...",\n'
    '  "parties": ["Pala A", "Pala B"],\n'
    '  "clauses": [\n'
    '    {"n": 1, "title": "Titulli i klauzolës", '
    '"excerpt": "fragment i shkurtër (max 120 karaktere)", '
    '"level": "ok|watch|risk", '
    '"issue": "shpjegim i shkurtër pse (në SHQIP)", '
    '"suggestion": "çfarë të bëjmë (ose null nëse ok)"}\n'
    '  ],\n'
    '  "obligations": [\n'
    '    {"party": "Pala", "duty": "çfarë duhet bërë", '
    '"deadline": "kur (ose null)"}\n'
    '  ],\n'
    '  "deadlines": [\n'
    '    {"what": "çfarë", "when": "data ose periudha", '
    '"who": "kush detyrohet"}\n'
    '  ],\n'
    '  "gdpr_flags": [\n'
    '    {"flag": "p.sh. transferim te palë e tretë pa bazë", '
    '"location": "klauzola N ose null", '
    '"severity": "low|medium|high"}\n'
    '  ],\n'
    '  "missing_clauses": ["Klauzola që mungojnë por duhen", ...],\n'
    '  "risk_score": 0-100\n'
    "}\n\n"
    "risk_score: 0 = standardë, 30 = i pranueshëm me 1-2 vërejtje, "
    "60 = i rrezikshëm pa modifikime, 90+ = i pa-nënshkruajshëm."
)


def _compute_contract_risk(clauses: list, gdpr_flags: list) -> int:
    """Fallback risk calc if AI didn't return one. Each risk clause = 25,
    each watch = 10, plus GDPR severity bumps. Capped at 100."""
    score = 0
    for c in clauses or []:
        lvl = (c.get("level") or "").lower()
        if lvl == "risk":
            score += 25
        elif lvl == "watch":
            score += 10
    for g in gdpr_flags or []:
        sev = (g.get("severity") or "").lower()
        if sev == "high":
            score += 20
        elif sev == "medium":
            score += 10
        elif sev == "low":
            score += 4
    return min(100, score)


@app.post("/api/cases/<case_id>/contract-review")
@login_required_api
def api_contract_review(case_id: str):
    """Run an AI semaforo review on a contract. Saves the result so the
    lawyer can revisit. Heavyweight call — uses the slow path on purpose
    (full Opus) since contract review is high-stakes."""
    case = _resolve_case(case_id)
    if case is None:
        return jsonify({"error": "not found"}), 404
    if _BRAIN is None:
        return jsonify({"error": "brain not available"}), 503
    user = request.user  # type: ignore[attr-defined]
    data = request.get_json(force=True, silent=True) or {}
    source_text = (data.get("contract_text") or "").strip()
    contract_label = (data.get("contract_label") or "").strip() or None
    if len(source_text) < 100:
        return jsonify({"error": "contract too short (min 100 chars)"}), 400
    if len(source_text) > 60000:
        source_text = source_text[:60000]
    try:
        raw = _BRAIN.backend.complete(
            system=CONTRACT_REVIEW_SYSTEM,
            messages=[{"role": "user", "content": source_text}],
            max_tokens=6000,
            fast=False,  # full Opus — high-stakes
        )
        parsed = _intake_parse_json(raw)
    except Exception as exc:
        log.warning("contract-review failed: %s", exc)
        return jsonify({"error": "review failed",
                        "detail": str(exc)[:200]}), 502

    clauses = parsed.get("clauses") or []
    gdpr = parsed.get("gdpr_flags") or []
    risk_score = parsed.get("risk_score")
    if not isinstance(risk_score, int):
        risk_score = _compute_contract_risk(clauses, gdpr)

    review = storage.create_contract_review(
        case_id=case_id, user_id=user.id,
        source_text=source_text, result=parsed,
        contract_label=contract_label,
        contract_kind=(parsed.get("contract_kind") or None),
        risk_score=risk_score,
    )
    return jsonify({
        "review_id": review.id,
        "created_at": review.created_at,
        "contract_label": review.contract_label,
        "contract_kind": review.contract_kind,
        "risk_score": risk_score,
        "result": parsed,
    }), 201


@app.get("/api/cases/<case_id>/contract-reviews")
@login_required_api
def api_list_contract_reviews(case_id: str):
    if _resolve_case(case_id) is None:
        return jsonify({"error": "not found"}), 404
    items = storage.list_contract_reviews_for_case(case_id)
    return jsonify({"reviews": [
        {"id": r.id, "contract_label": r.contract_label,
         "contract_kind": r.contract_kind,
         "risk_score": r.risk_score, "created_at": r.created_at,
         "summary": (r.result or {}).get("summary")}
        for r in items
    ]})


@app.get("/api/cases/<case_id>/contract-reviews/<int:review_id>")
@login_required_api
def api_get_contract_review(case_id: str, review_id: int):
    if _resolve_case(case_id) is None:
        return jsonify({"error": "not found"}), 404
    r = storage.get_contract_review(review_id)
    if r is None or r.case_id != case_id:
        return jsonify({"error": "not found"}), 404
    return jsonify({
        "review_id": r.id,
        "contract_label": r.contract_label,
        "contract_kind": r.contract_kind,
        "risk_score": r.risk_score,
        "created_at": r.created_at,
        "result": r.result,
    })


@app.delete("/api/cases/<case_id>/contract-reviews/<int:review_id>")
@login_required_api
def api_delete_contract_review(case_id: str, review_id: int):
    if _resolve_case(case_id) is None:
        return jsonify({"error": "not found"}), 404
    if not storage.delete_contract_review(review_id, case_id):
        return jsonify({"error": "not found"}), 404
    return jsonify({"ok": True})


# ── V8.5 money layer (time entries + invoices) ─────────────────────────────

def _serialize_time_entry(e: storage.TimeEntry) -> dict:
    return {
        "id": e.id,
        "entry_date": e.entry_date,
        "minutes": e.minutes,
        "hours": round(e.minutes / 60.0, 2),
        "description": e.description,
        "activity_kind": e.activity_kind,
        "activity_label": storage.ACTIVITY_KIND_LABELS_SQ.get(
            e.activity_kind, e.activity_kind),
        "hourly_rate": e.hourly_rate,
        "currency": e.currency,
        "amount_cents": e.amount_cents,
        "billed_invoice_id": e.billed_invoice_id,
        "created_at": e.created_at,
    }


def _serialize_invoice(inv: storage.Invoice, *, include_md: bool = False) -> dict:
    out = {
        "id": inv.id,
        "invoice_no": inv.invoice_no,
        "client_name": inv.client_name,
        "client_address": inv.client_address,
        "issue_date": inv.issue_date,
        "due_date": inv.due_date,
        "currency": inv.currency,
        "subtotal_cents": inv.subtotal_cents,
        "vat_rate": inv.vat_rate,
        "vat_cents": inv.vat_cents,
        "total_cents": inv.total_cents,
        "status": inv.status,
        "notes": inv.notes,
        "line_items": inv.line_items,
        "created_at": inv.created_at,
        "updated_at": inv.updated_at,
    }
    if include_md:
        out["markdown"] = inv.markdown
    return out


@app.get("/api/firm/tariff")
@login_required_api
def api_firm_tariff():
    """Returns the indicative Albanian Bar tariff (cents/h) for UI dropdowns."""
    return jsonify({
        "tariff": storage.ALBANIAN_BAR_TARIFF_EUR,
        "labels": storage.ACTIVITY_KIND_LABELS_SQ,
        "default_currency": "EUR",
    })


@app.post("/api/cases/<case_id>/time-entries")
@login_required_api
def api_create_time_entry(case_id: str):
    case = _resolve_case(case_id)
    if case is None:
        return jsonify({"error": "not found"}), 404
    user = request.user  # type: ignore[attr-defined]
    firm = request.firm  # type: ignore[attr-defined]
    data = request.get_json(force=True, silent=True) or {}
    try:
        minutes = int(data.get("minutes") or 0)
    except (TypeError, ValueError):
        return jsonify({"error": "invalid minutes"}), 400
    description = (data.get("description") or "").strip()
    activity_kind = (data.get("activity_kind") or "work").strip()
    rate_raw = data.get("hourly_rate")
    hourly_rate = None
    if rate_raw not in (None, ""):
        try:
            hourly_rate = int(rate_raw)
        except (TypeError, ValueError):
            return jsonify({"error": "invalid hourly_rate"}), 400
    currency = (data.get("currency") or "EUR").strip().upper()[:3] or "EUR"
    entry_date = (data.get("entry_date") or "").strip() or None
    try:
        entry = storage.create_time_entry(
            case_id, user.id,
            minutes=minutes, description=description,
            activity_kind=activity_kind, hourly_rate=hourly_rate,
            currency=currency, entry_date=entry_date,
            firm_id=firm.id if firm else None,
        )
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    return jsonify(_serialize_time_entry(entry)), 201


@app.get("/api/cases/<case_id>/time-entries")
@login_required_api
def api_list_time_entries(case_id: str):
    if _resolve_case(case_id) is None:
        return jsonify({"error": "not found"}), 404
    unbilled = request.args.get("unbilled_only", "").lower() in ("1", "true", "yes")
    entries = storage.list_time_entries_for_case(case_id, unbilled_only=unbilled)
    total_unbilled = sum(e.amount_cents for e in entries if e.billed_invoice_id is None)
    return jsonify({
        "entries": [_serialize_time_entry(e) for e in entries],
        "total_unbilled_cents": total_unbilled,
    })


@app.delete("/api/cases/<case_id>/time-entries/<int:entry_id>")
@login_required_api
def api_delete_time_entry(case_id: str, entry_id: int):
    if _resolve_case(case_id) is None:
        return jsonify({"error": "not found"}), 404
    if not storage.delete_time_entry(entry_id, case_id):
        return jsonify({"error": "not found"}), 404
    return jsonify({"ok": True})


@app.post("/api/cases/<case_id>/invoice")
@login_required_api
def api_create_invoice(case_id: str):
    case = _resolve_case(case_id)
    if case is None:
        return jsonify({"error": "not found"}), 404
    user = request.user  # type: ignore[attr-defined]
    firm = request.firm  # type: ignore[attr-defined]
    data = request.get_json(force=True, silent=True) or {}
    client_name = (data.get("client_name") or "").strip()
    client_address = (data.get("client_address") or "").strip() or None
    notes = (data.get("notes") or "").strip() or None
    due_date = (data.get("due_date") or "").strip() or None
    try:
        vat_rate = int(data.get("vat_rate") or 0)
    except (TypeError, ValueError):
        return jsonify({"error": "invalid vat_rate"}), 400
    if vat_rate < 0 or vat_rate > 100:
        return jsonify({"error": "vat_rate out of range"}), 400
    try:
        inv = storage.create_invoice_from_unbilled(
            case_id, user.id,
            client_name=client_name, client_address=client_address,
            vat_rate=vat_rate, notes=notes, due_date=due_date,
            firm_id=firm.id if firm else None,
        )
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    return jsonify(_serialize_invoice(inv, include_md=True)), 201


@app.get("/api/cases/<case_id>/invoices")
@login_required_api
def api_list_invoices(case_id: str):
    if _resolve_case(case_id) is None:
        return jsonify({"error": "not found"}), 404
    invs = storage.list_invoices_for_case(case_id)
    return jsonify({"invoices": [_serialize_invoice(i) for i in invs]})


@app.get("/api/cases/<case_id>/invoices/<int:invoice_id>")
@login_required_api
def api_get_invoice(case_id: str, invoice_id: int):
    if _resolve_case(case_id) is None:
        return jsonify({"error": "not found"}), 404
    inv = storage.get_invoice(invoice_id)
    if inv is None or inv.case_id != case_id:
        return jsonify({"error": "not found"}), 404
    return jsonify(_serialize_invoice(inv, include_md=True))


@app.patch("/api/cases/<case_id>/invoices/<int:invoice_id>/status")
@login_required_api
def api_update_invoice_status(case_id: str, invoice_id: int):
    if _resolve_case(case_id) is None:
        return jsonify({"error": "not found"}), 404
    inv = storage.get_invoice(invoice_id)
    if inv is None or inv.case_id != case_id:
        return jsonify({"error": "not found"}), 404
    data = request.get_json(force=True, silent=True) or {}
    status = (data.get("status") or "").strip()
    try:
        ok = storage.update_invoice_status(invoice_id, status)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    if not ok:
        return jsonify({"error": "not found"}), 404
    return jsonify(_serialize_invoice(storage.get_invoice(invoice_id)))


@app.delete("/api/cases/<case_id>/invoices/<int:invoice_id>")
@login_required_api
def api_delete_invoice(case_id: str, invoice_id: int):
    if _resolve_case(case_id) is None:
        return jsonify({"error": "not found"}), 404
    inv = storage.get_invoice(invoice_id)
    if inv is None or inv.case_id != case_id:
        return jsonify({"error": "not found"}), 404
    storage.delete_invoice(invoice_id, case_id)
    return jsonify({"ok": True})


# ── V8.14 Financial OS — profitability, WIP aging, cashflow, AI fee estimator ─

@app.get("/api/cases/<case_id>/profitability")
@login_required_api
def api_case_profitability(case_id: str):
    if _resolve_case(case_id) is None:
        return jsonify({"error": "not found"}), 404
    return jsonify(storage.case_profitability(case_id))


@app.get("/api/firm/realization")
@login_required_api
def api_firm_realization():
    firm = request.firm  # type: ignore[attr-defined]
    if firm is None:
        return jsonify({"error": "no_firm"}), 400
    since = request.args.get("since") or None
    return jsonify(storage.firm_realization(firm.id, since=since))


@app.get("/api/firm/wip-aging")
@login_required_api
def api_firm_wip_aging():
    firm = request.firm  # type: ignore[attr-defined]
    if firm is None:
        return jsonify({"error": "no_firm"}), 400
    return jsonify({"items": storage.wip_aging(firm.id)})


@app.get("/api/firm/cashflow")
@login_required_api
def api_firm_cashflow():
    firm = request.firm  # type: ignore[attr-defined]
    if firm is None:
        return jsonify({"error": "no_firm"}), 400
    horizon = request.args.get("horizon", default=90, type=int)
    return jsonify({"items": storage.cashflow_forecast(firm.id, horizon)})


@app.post("/api/cases/<case_id>/fee-estimate")
@login_required_api
def api_fee_estimate(case_id: str):
    """AI-driven pre-mandate fee estimate.

    Asks the model to produce a low/likely/high fee range in EUR with
    a brief rationale, anchored to the case's facts and jurisdiction.
    """
    case = _resolve_case(case_id)
    if case is None:
        return jsonify({"error": "not found"}), 404
    data = request.get_json(force=True, silent=True) or {}
    description = (data.get("description") or "").strip()
    if not description:
        return jsonify({"error": "missing_description"}), 400
    _ensure_loaded()
    if _BRAIN is None:
        return jsonify({"error": "brain_unavailable"}), 503
    jur = getattr(case, "jurisdiction", "AL")
    prompt = (
        f"PËRSHKRIMI I RASTIT (juridiksioni: {jur}):\n{description}\n\n"
        "Vlerëso një interval tarife realiste (EUR) për një avokat "
        "shqiptar/italian/EU për këtë çështje. Kthe JSON të pastër "
        "(pa code-fence) me fushat: low_eur, likely_eur, high_eur, "
        "hours_estimate, rationale (2-3 fjali), risk_flags (listë "
        "shkurt). Bazohu në praktikën e zakonshme të tregut, jo në "
        "tarifat zyrtare të Dhomës; mos shkruaj asgjë jashtë JSON-it."
    )
    text = _BRAIN.backend.complete(
        system="Ti je një avokat strateg me eksperiencë financiare.",
        messages=[{"role": "user", "content": prompt}],
        max_tokens=600,
        medium=True,  # Sonnet — analytical task, no need for Opus
        callsite="fee_estimate",
        case_id=case_id,
    )
    import re as _re
    m = _re.search(r"\{.*\}", text, _re.DOTALL)
    if not m:
        return jsonify({"error": "ai_format", "raw": text[:400]}), 502
    try:
        payload = json.loads(m.group(0))
    except json.JSONDecodeError:
        return jsonify({"error": "ai_json", "raw": text[:400]}), 502
    return jsonify(payload)


@app.post("/api/cases/<case_id>/invoices/<int:invoice_id>/review")
@login_required_api
def api_invoice_review(case_id: str, invoice_id: int):
    """AI invoice sanity check before sending: spots missing references,
    weak descriptions, mis-scaled time vs activity, formatting issues."""
    if _resolve_case(case_id) is None:
        return jsonify({"error": "not found"}), 404
    inv = storage.get_invoice(invoice_id)
    if inv is None or inv.case_id != case_id:
        return jsonify({"error": "not found"}), 404
    _ensure_loaded()
    if _BRAIN is None:
        return jsonify({"error": "brain_unavailable"}), 503
    md = inv.markdown or ""
    prompt = (
        "Lexoj faturë më poshtë dhe identifico probleme PARA DËRGIMIT te "
        "klienti. Kthe JSON të pastër me fushat: issues (listë me "
        "{severity: 'high'|'medium'|'low', area, message}), suggestions "
        "(listë stringa), estimated_dispute_risk (low|medium|high). "
        "Mos rishkruaj faturën — vetëm gjej probleme.\n\n"
        f"FATURA:\n{md[:6000]}"
    )
    text = _BRAIN.backend.complete(
        system="Ti je auditor financiar i specializuar në fatura ligjore.",
        messages=[{"role": "user", "content": prompt}],
        max_tokens=900,
        medium=True,
        callsite="invoice_review",
        case_id=case_id,
    )
    import re as _re
    m = _re.search(r"\{.*\}", text, _re.DOTALL)
    if not m:
        return jsonify({"error": "ai_format", "raw": text[:400]}), 502
    try:
        payload = json.loads(m.group(0))
    except json.JSONDecodeError:
        return jsonify({"error": "ai_json", "raw": text[:400]}), 502
    return jsonify(payload)


# ── V8.15 Workflow library — predefined plans + custom JSON DSL ────────

from . import workflows as wf_mod  # noqa: E402  (kept near endpoints)


@app.get("/api/workflows")
@login_required_api
def api_list_workflows():
    """Library catalogue (predefined definitions only)."""
    return jsonify({"definitions": wf_mod.list_definitions()})


@app.get("/api/workflows/<key>")
@login_required_api
def api_workflow_definition(key: str):
    d = wf_mod.get_definition(key)
    if d is None:
        return jsonify({"error": "not_found"}), 404
    return jsonify({
        **{k: d[k] for k in ("key", "title", "summary",
                              "jurisdiction", "estimated_days")},
        "steps": [wf_mod.step_summary(s) for s in d["steps"]],
    })


@app.get("/api/cases/<case_id>/workflows")
@login_required_api
def api_case_workflows_list(case_id: str):
    if _resolve_case(case_id) is None:
        return jsonify({"error": "not_found"}), 404
    instances = storage.list_case_workflows(case_id)
    return jsonify({
        "instances": [storage.workflow_summary(w) for w in instances],
    })


@app.post("/api/cases/<case_id>/workflows")
@login_required_api
def api_case_workflows_start(case_id: str):
    case = _resolve_case(case_id)
    if case is None:
        return jsonify({"error": "not_found"}), 404
    user = request.user  # type: ignore[attr-defined]
    body = request.get_json(force=True, silent=True) or {}
    key = (body.get("workflow_key") or "").strip()
    custom = body.get("custom_definition")
    title = body.get("title")
    if not key and not custom:
        return jsonify({"error": "missing_workflow_key_or_custom"}), 400
    try:
        wf = storage.start_workflow(
            case_id=case_id, user_id=user.id,
            workflow_key=key or f"custom:{(custom or {}).get('key', 'unnamed')}",
            custom_definition=custom,
            title=title,
        )
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    return jsonify(storage.workflow_summary(wf)), 201


@app.get("/api/cases/<case_id>/workflows/<int:workflow_id>")
@login_required_api
def api_case_workflow_get(case_id: str, workflow_id: int):
    if _resolve_case(case_id) is None:
        return jsonify({"error": "not_found"}), 404
    wf = storage.get_workflow(workflow_id)
    if wf is None or wf.case_id != case_id:
        return jsonify({"error": "not_found"}), 404
    return jsonify(storage.workflow_summary(wf))


@app.post("/api/cases/<case_id>/workflows/<int:workflow_id>/advance")
@login_required_api
def api_case_workflow_advance(case_id: str, workflow_id: int):
    if _resolve_case(case_id) is None:
        return jsonify({"error": "not_found"}), 404
    wf = storage.get_workflow(workflow_id)
    if wf is None or wf.case_id != case_id:
        return jsonify({"error": "not_found"}), 404
    body = request.get_json(force=True, silent=True) or {}
    step_id = body.get("step_id")
    result = body.get("result")
    try:
        wf2 = storage.advance_workflow(workflow_id,
                                       step_id=step_id, result=result)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    return jsonify(storage.workflow_summary(wf2))


@app.post("/api/cases/<case_id>/workflows/<int:workflow_id>/state")
@login_required_api
def api_case_workflow_state(case_id: str, workflow_id: int):
    if _resolve_case(case_id) is None:
        return jsonify({"error": "not_found"}), 404
    wf = storage.get_workflow(workflow_id)
    if wf is None or wf.case_id != case_id:
        return jsonify({"error": "not_found"}), 404
    body = request.get_json(force=True, silent=True) or {}
    new_state = (body.get("state") or "").strip()
    try:
        wf2 = storage.update_workflow_state(workflow_id, new_state)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    return jsonify(storage.workflow_summary(wf2))


@app.post("/api/cases/<case_id>/workflows/<int:workflow_id>/run-step")
@login_required_api
def api_case_workflow_run_ai_step(case_id: str, workflow_id: int):
    """Execute the current step if it's an `ai_call`, then auto-advance.

    For non-ai steps the caller should POST `/advance` directly with their
    own `result`. This endpoint exists so the UI can offer a "Run with AI"
    button on `ai_call` steps without pasting prompts manually.
    """
    case = _resolve_case(case_id)
    if case is None:
        return jsonify({"error": "not_found"}), 404
    wf = storage.get_workflow(workflow_id)
    if wf is None or wf.case_id != case_id:
        return jsonify({"error": "not_found"}), 404
    if wf.state != "active":
        return jsonify({"error": "workflow_not_active"}), 400
    definition = storage._resolve_workflow_definition(wf)  # type: ignore[attr-defined]
    if definition is None:
        return jsonify({"error": "definition_unavailable"}), 500
    steps = definition.get("steps") or []
    cur = next((s for s in steps if s["id"] == wf.current_step_id), None)
    if cur is None:
        return jsonify({"error": "no_current_step"}), 400
    if cur["kind"] != "ai_call":
        return jsonify({"error": f"step_not_ai_call:{cur['kind']}"}), 400
    _ensure_loaded()
    if _BRAIN is None:
        return jsonify({"error": "brain_unavailable"}), 503
    p = cur["params"]
    tier = (p.get("tier") or "medium").lower()
    fast = tier == "fast"
    medium = tier == "medium"
    # interpolate prior outputs into prompt template (very lightweight)
    user_prompt = p.get("prompt_user") or ""
    for k, v in (wf.step_results or {}).items():
        if isinstance(v, str):
            user_prompt = user_prompt.replace(f"{{{{{k}}}}}", v)
    text = _BRAIN.backend.complete(
        system=p.get("prompt_system") or "Ti je Super Avvocato.",
        messages=[{"role": "user", "content": user_prompt}],
        max_tokens=int(p.get("max_tokens") or 1200),
        fast=fast,
        medium=medium,
        callsite=f"workflow_step:{wf.workflow_key}:{cur['id']}",
        case_id=case_id,
    )
    try:
        wf2 = storage.advance_workflow(workflow_id,
                                       step_id=cur["id"], result=text)
    except ValueError as e:
        return jsonify({"error": str(e), "ai_output": text}), 400
    return jsonify({**storage.workflow_summary(wf2), "ai_output": text})


# ── V8.16 Time-Block Reconstruction — auto-fill timesheet from activity ──

@app.get("/api/time/reconstruction")
@login_required_api
def api_time_reconstruction():
    """Propose billable time blocks for a user/date by aggregating activity."""
    user = request.user  # type: ignore[attr-defined]
    date_str = (request.args.get("date") or "").strip()
    if not date_str:
        date_str = datetime.now(UTC).strftime("%Y-%m-%d")
    if not re.match(r"^\d{4}-\d{2}-\d{2}$", date_str):
        return jsonify({"error": "invalid_date_format"}), 400
    result = storage.reconstruct_time_blocks(user.id, date_str)
    # optional AI labelling: keep deterministic if disabled
    if request.args.get("label", "0") == "1" and result["blocks"]:
        _ensure_loaded()
        if _BRAIN is not None:
            for b in result["blocks"]:
                if b["confidence"] == "low":
                    continue
                ev = "; ".join(b["evidence"][:6])
                prompt = (
                    f"Çështja: {b['case_title']}\n"
                    f"Sinjalet e ditës ({b['started_at']}-{b['ended_at']}): {ev}\n\n"
                    "Shkruaj NJË përshkrim të shkurtër (≤ 14 fjalë, shqip) që "
                    "do të hyjë në timesheet të avokatit. Pa preambël, pa "
                    "thonjëza, vetëm fraza."
                )
                try:
                    text = _BRAIN.backend.complete(
                        system="Ti je asistent fakturimi për avokat shqiptar. Shkurt, faktik.",
                        messages=[{"role": "user", "content": prompt}],
                        max_tokens=80,
                        fast=True,  # Sonnet — etichettatura banale
                        callsite="time_block_label",
                    )
                    b["suggested_description"] = text.strip().splitlines()[0][:140]
                except Exception:
                    pass
    return jsonify(result)


@app.post("/api/time/reconstruction/accept")
@login_required_api
def api_time_reconstruction_accept():
    """Bulk-accept proposed blocks → time_entries rows.

    Body: {"date": "YYYY-MM-DD", "blocks": [{case_id, minutes,
    activity_kind, description}, ...]}
    """
    user = request.user  # type: ignore[attr-defined]
    firm = request.firm  # type: ignore[attr-defined]
    body = request.get_json(force=True, silent=True) or {}
    date_str = (body.get("date") or "").strip()
    if not re.match(r"^\d{4}-\d{2}-\d{2}$", date_str or ""):
        return jsonify({"error": "invalid_date_format"}), 400
    blocks = body.get("blocks") or []
    if not isinstance(blocks, list) or not blocks:
        return jsonify({"error": "blocks_required"}), 400
    try:
        created = storage.accept_time_blocks(
            user.id, date_str, blocks,
            firm_id=firm.id if firm else None,
        )
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    return jsonify({
        "created": [{
            "id": e.id, "case_id": e.case_id, "minutes": e.minutes,
            "activity_kind": e.activity_kind,
            "description": e.description,
            "hourly_rate_cents": e.hourly_rate, "currency": e.currency,
        } for e in created],
        "count": len(created),
    }), 201


# ── V8.17 Settlement Monte Carlo — quasi-MC over AI-elicited scenarios ───

from . import settlement as settle_mod  # noqa: E402


@app.post("/api/cases/<case_id>/settlement-simulation")
@login_required_api
def api_settlement_simulate(case_id: str):
    """Run a Monte Carlo simulation of the case settlement value.

    Body: {
      description (required): str — case facts in lawyer's words
      current_offer_eur (optional): number — opponent's current offer
      valore_in_causa_eur (optional): number — pleaded amount
      plaintiff (default true): bool — are we the receiving side?
      samples (default 10000): int 1000-50000
      seed (optional): int — for reproducibility
    }
    """
    case = _resolve_case(case_id)
    if case is None:
        return jsonify({"error": "not_found"}), 404
    user = request.user  # type: ignore[attr-defined]
    body = request.get_json(force=True, silent=True) or {}
    description = (body.get("description") or "").strip()
    if not description:
        return jsonify({"error": "missing_description"}), 400
    current_offer_eur = body.get("current_offer_eur")
    valore_eur = body.get("valore_in_causa_eur")
    plaintiff = bool(body.get("plaintiff", True))
    samples = int(body.get("samples") or 10000)
    samples = max(1000, min(50000, samples))
    seed = body.get("seed")
    seed = int(seed) if isinstance(seed, (int, float, str)) and str(seed).lstrip("-").isdigit() else None

    _ensure_loaded()
    if _BRAIN is None:
        return jsonify({"error": "brain_unavailable"}), 503
    jur = getattr(case, "jurisdiction", "AL")

    # Light precedent retrieval — best-effort, no failure if KB absent
    precedent_snippets: list[dict] = []
    try:
        retr = getattr(_BRAIN, "_legalkb_retriever", None) or getattr(_BRAIN, "legalkb", None)
        if retr is not None and hasattr(retr, "search"):
            hits = retr.search([description], top_k=8)
            for c, score in hits[:5]:
                precedent_snippets.append({
                    "id": getattr(c, "id", None),
                    "citation": getattr(c, "citation", None),
                    "outcome": getattr(c, "outcome", None),
                    "summary": (getattr(c, "summary", "") or "")[:280],
                    "score": round(float(score), 2),
                })
    except Exception as e:
        log.warning("settlement: precedent retrieval skipped: %s", e)

    precedent_block = ""
    if precedent_snippets:
        precedent_block = "\n\nPrecedentë të ngjashëm (top BM25):\n" + "\n".join(
            f"- [{p.get('outcome') or '?'}] {p.get('citation') or '#'+str(p.get('id'))}: "
            f"{p.get('summary')}"
            for p in precedent_snippets
        )

    offer_line = (
        f"\n\nOferta aktuale e palës tjetër: {current_offer_eur} EUR"
        if current_offer_eur is not None else ""
    )
    valore_line = (
        f"\n\nVlera e kërkuar (valore in causa): {valore_eur} EUR"
        if valore_eur is not None else ""
    )
    role_line = "\n\nRoli ynë: paditës (kërkojmë vlerë sa më të lartë)." if plaintiff else \
                "\n\nRoli ynë: i paditur (duam vlerë sa më të ulët)."

    user_prompt = (
        f"Juridiksioni: {jur}\n\n"
        f"Përshkrimi i çështjes:\n{description}"
        f"{valore_line}{offer_line}{role_line}"
        f"{precedent_block}\n\n"
        "Si avokat me eksperiencë negocimi dhe gjyqi, ndërto një model "
        "probabilistik të rezultatit financiar të kësaj çështjeje. "
        "Mendo në skenarë (settle, gjykim me fitore, gjykim me humbje, "
        "tërheqje, etj.) — për secilin: probabiliteti, intervali min/mode/"
        "max në EUR, dhe arsyeja.\n\n"
        + settle_mod.SCENARIO_SCHEMA_HINT
    )

    text = _BRAIN.backend.complete(
        system=("Ti je avokat strateg me 15+ vite eksperiencë në negocim "
                "dhe gjyqësor. Mendoj në numra reala, jo fjalë të mëdha."),
        messages=[{"role": "user", "content": user_prompt}],
        max_tokens=2000,
        # Opus — strategic financial reasoning, exactly the use case
        callsite="settlement_scenarios",
        case_id=case_id,
    )
    try:
        scenarios, meta = settle_mod.parse_scenarios_text(text)
    except ValueError as e:
        return jsonify({
            "error": "ai_format",
            "detail": str(e),
            "raw": text[:1500],
        }), 502

    distribution = settle_mod.simulate(scenarios, samples=samples, seed=seed)
    rec = settle_mod.recommendation(
        distribution,
        current_offer_eur=float(current_offer_eur) if current_offer_eur is not None else None,
        plaintiff=plaintiff,
    )
    if current_offer_eur is not None:
        rec["current_offer_percentile"] = settle_mod.percentile_of(
            float(current_offer_eur), scenarios, samples=samples, seed=seed
        )

    scenarios_json = [{
        "name": s.name, "label": s.label,
        "probability": round(s.probability, 3),
        "min_eur": s.min_eur, "mode_eur": s.mode_eur, "max_eur": s.max_eur,
        "rationale": s.rationale,
    } for s in scenarios]

    sim_id = storage.save_settlement_simulation(
        case_id=case_id, user_id=user.id,
        description=description,
        valore_in_causa_cents=int(float(valore_eur) * 100) if valore_eur is not None else None,
        current_offer_cents=int(float(current_offer_eur) * 100) if current_offer_eur is not None else None,
        currency=meta.get("currency") or "EUR",
        scenarios=scenarios_json,
        distribution=distribution,
        recommendation=rec,
        precedents=precedent_snippets or None,
        samples=samples, seed=seed,
    )

    return jsonify({
        "id": sim_id,
        "case_id": case_id,
        "scenarios": scenarios_json,
        "meta": meta,
        "distribution": distribution,
        "recommendation": rec,
        "precedents": precedent_snippets,
        "samples": samples,
        "seed": seed,
    }), 201


@app.get("/api/cases/<case_id>/settlement-simulations")
@login_required_api
def api_settlement_list(case_id: str):
    if _resolve_case(case_id) is None:
        return jsonify({"error": "not_found"}), 404
    return jsonify({"items": storage.list_settlement_simulations(case_id)})


@app.get("/api/settlement-simulations/<int:sim_id>")
@login_required_api
def api_settlement_get(sim_id: int):
    sim = storage.get_settlement_simulation(sim_id)
    if sim is None:
        return jsonify({"error": "not_found"}), 404
    if _resolve_case(sim["case_id"]) is None:
        return jsonify({"error": "forbidden"}), 403
    return jsonify(sim)


# ── V9.0 Genio Legale — Senior Partner Brief (6 parallel Opus) ──────────

from . import genio as genio_mod  # noqa: E402


def _gather_case_recent_messages(case_id: str, limit: int = 8) -> list[dict]:
    """Recent user/assistant turns for grounding the case_block."""
    msgs = storage.list_messages(case_id) if hasattr(storage, "list_messages") else []
    return [{"role": m.role, "content": m.content} for m in msgs[-limit:]]


def _gather_case_documents(case_id: str, limit: int = 12) -> list[dict]:
    """Document summaries for the case, if storage exposes them."""
    if not hasattr(storage, "list_documents"):
        return []
    docs = storage.list_documents(case_id) or []
    out: list[dict] = []
    for d in docs[:limit]:
        out.append({
            "filename": getattr(d, "filename", ""),
            "doc_type": getattr(d, "doc_type", None),
            "summary": getattr(d, "summary", None),
            "extracted_text": getattr(d, "extracted_text", None),
            "storage_path": getattr(d, "storage_path", None),
        })
    return out


def _genio_prepare(case_id: str, description: str = ""):
    """Prepara un giro di Genio. Torna `(generatore, brief_id, None)` se si
    puo' partire, oppure `(None, None, (payload, status))` se no.

    Tre valori e non due di proposito: `jsonify(...), 404` e' anch'essa una
    tupla, e distinguere il successo dall'errore guardando la forma sarebbe
    un trabocchetto per chi legge questo codice fra sei mesi.
    """
    case = _resolve_case(case_id)
    if case is None:
        return None, None, ({"error": "not_found"}, 404)
    user = request.user  # type: ignore[attr-defined]

    _ensure_loaded()
    if _BRAIN is None:
        return None, None, ({"error": "brain_unavailable"}, 503)

    jur = getattr(case, "jurisdiction", "AL")
    recent_msgs = _gather_case_recent_messages(case_id)
    docs = _gather_case_documents(case_id)

    # I file senza testo estratto — foto, scansioni — vanno allegati davvero:
    # per quelli il riassunto non dice niente e il testo non esiste. Pochi,
    # perché ogni allegato viaggia con tutte e sei le lenti.
    allegati: list[Path] = []
    for d in docs:
        if allegati and len(allegati) >= 4:
            break
        if (d.get("extracted_text") or "").strip():
            continue
        p = d.get("storage_path")
        if p and Path(p).exists():
            allegati.append(Path(p))
            d["allegato"] = True

    # Cosa aveva concluso il Genio la volta scorsa su questo caso: senza,
    # ogni giro riparte da zero e rianalizza gli stessi fatti.
    try:
        precedenti = storage.list_genio_briefs(case_id) or []
    except Exception:  # noqa: BLE001
        precedenti = []

    case_block = genio_mod.build_case_block(
        case, jurisdiction=jur, extra_description=description,
        recent_messages=recent_msgs, documents=docs,
        previous_briefs=precedenti,
    )
    voice_block = genio_mod._gather_voice_samples(user.id)

    brief_id = storage.create_genio_brief(
        case_id=case_id, user_id=user.id,
        description=description, case_block=case_block,
    )

    backend = _BRAIN.backend

    def _event(evt: dict) -> str:
        payload = json.dumps(evt, ensure_ascii=False)
        return f"data: {payload}\n\n"

    def _stream():
        yield _event({"type": "brief_id", "id": brief_id})
        by_key: dict = {}
        had_any_error = False
        had_any_success = False
        elapsed = 0
        for evt in genio_mod.run_brief(
            backend=backend, case_block=case_block,
            voice_samples_block=voice_block, case_id=case_id,
            attachments=allegati,
        ):
            if evt["type"] == "perspective":
                r = evt["result"]
                if r.get("kind") == "error":
                    had_any_error = True
                else:
                    had_any_success = True
                yield _event(evt)
            elif evt["type"] == "completed":
                by_key = evt["by_key"]
                elapsed = evt["elapsed_ms"]
                yield _event(evt)
            else:
                yield _event(evt)
        if had_any_success and had_any_error:
            status = "partial"
        elif had_any_success:
            status = "completed"
        else:
            status = "error"
        try:
            storage.finalize_genio_brief(
                brief_id, by_key=by_key, status=status, elapsed_ms=elapsed,
            )
        except Exception as e:
            log.warning("genio finalize failed: %s", e)
        yield _event({"type": "done", "brief_id": brief_id,
                      "status": status, "elapsed_ms": elapsed})

    return _stream, brief_id, None


def _genio_body_description() -> str:
    body = request.get_json(force=True, silent=True) or {}
    return (body.get("description") or "").strip()


@app.post("/api/cases/<case_id>/genio")
@login_required_api
@require_module("avokat", "prokuror")
def api_genio_run(case_id: str):
    """Percorso storico: il Genio trasmette dentro questa connessione.

    Tenuto vivo di proposito — se il percorso in background facesse i
    capricci, il client torna qui cambiando una riga, senza un deploy.
    """
    gen, _bid, err = _genio_prepare(case_id, _genio_body_description())
    if err is not None:
        payload, status = err
        return jsonify(payload), status
    return Response(stream_with_context(gen()),
                    mimetype="text/event-stream", headers=_SSE_HEADERS)


# ── Condizioni, privacy e accordo sul trattamento ─────────────────────
#
# La versione e' una data. Cambiando i testi si alza, e tutti riaccettano:
# altrimenti l'accettazione si riferisce a un documento che non esiste piu'.
LEGAL_VERSION = os.environ.get("LEGAL_VERSION", "2026-08-31")
LEGAL_DOCS = "terms,privacy,dpa"


def _legal_md_to_html(md: str) -> str:
    """Markdown → HTML per la pagina pubblica dei documenti legali.

    Copre gli otto costrutti effettivamente usati nei file di `legal/`
    (h1-h3, paragrafi, **grassetto**, elenchi puntati e numerati, tabelle,
    righe orizzontali, citazioni). Non e' un renderer generico e non vuole
    esserlo: `tools/golden_check.py` sezione [10] fallisce se in quei file
    compare un costrutto che qui non c'e', invece di lasciarlo sparire.

    Tutto passa da `escape()` prima di qualunque markup: i file li scriviamo
    noi, ma un documento legale reso senza escaping e' un'abitudine che prima
    o poi incontra un testo che non hai scritto tu.
    """
    from markupsafe import escape

    def inline(t: str) -> str:
        t = str(escape(t))
        pezzi = t.split("**")
        # dispari = dentro le stelline; se restano spaiate si lascia il testo
        return "".join(f"<strong>{p}</strong>" if i % 2 else p
                       for i, p in enumerate(pezzi))

    out: list[str] = []
    lista: str = ""        # "ul" / "ol" / "" — quale elenco e' aperto
    tabella: list[str] = []

    def chiudi_lista() -> None:
        nonlocal lista
        if lista:
            out.append(f"</{lista}>")
            lista = ""

    def chiudi_tabella() -> None:
        if not tabella:
            return
        righe = [[c.strip() for c in r.strip().strip("|").split("|")]
                 for r in tabella]
        del tabella[:]
        # la riga di separazione (|---|---|) non e' contenuto
        corpo = [r for r in righe[1:]
                 if not all(set(c) <= set("-: ") for c in r)]
        out.append("<table><thead><tr>")
        out.extend(f"<th>{inline(c)}</th>" for c in righe[0])
        out.append("</tr></thead><tbody>")
        for r in corpo:
            out.append("<tr>" + "".join(f"<td>{inline(c)}</td>" for c in r) + "</tr>")
        out.append("</tbody></table>")

    for riga in (md or "").replace("\r\n", "\n").split("\n"):
        r = riga.rstrip()
        if r.lstrip().startswith("|"):
            chiudi_lista()
            tabella.append(r)
            continue
        chiudi_tabella()
        if not r.strip():
            chiudi_lista()
            continue
        if r.startswith("---") and set(r) == {"-"}:
            chiudi_lista()
            out.append("<hr>")
        elif r.startswith("#"):
            chiudi_lista()
            liv = len(r) - len(r.lstrip("#"))
            out.append(f"<h{min(liv, 3)}>{inline(r[liv:].strip())}</h{min(liv, 3)}>")
        elif r.startswith("> "):
            chiudi_lista()
            out.append(f"<blockquote>{inline(r[2:])}</blockquote>")
        elif r[:2] in ("- ", "* "):
            if lista != "ul":
                chiudi_lista()
                out.append("<ul>")
                lista = "ul"
            out.append(f"<li>{inline(r[2:])}</li>")
        elif r[:1].isdigit() and ". " in r[:4]:
            if lista != "ol":
                chiudi_lista()
                out.append("<ol>")
                lista = "ol"
            out.append(f"<li>{inline(r.split('. ', 1)[1])}</li>")
        else:
            chiudi_lista()
            out.append(f"<p>{inline(r)}</p>")
    chiudi_tabella()
    chiudi_lista()
    return "\n".join(out)


@app.get("/legale")
@app.get("/legale/<lang>")
def pagina_legale(lang: str = ""):
    """Pagina pubblica: i documenti si leggono SENZA account.

    Serve a chi sta valutando il prodotto. Uno studio serio, prima di aprire un
    account, manda il proprio responsabile protezione dati a leggere l'accordo
    sul trattamento: se per leggerlo bisogna gia' essere clienti, la trattativa
    si ferma prima di cominciare.

    Senza `login_required` di proposito. Non espone nulla: sono gli stessi
    documenti che chiunque riceverebbe via email prima di firmare.
    """
    lingua = "it" if str(lang).lower().startswith("it") else "sq"
    base = Path(__file__).resolve().parent.parent / "legal"
    pezzi = []
    titoli = {
        "sq": [("condizioni", "Kushtet e përdorimit"),
               ("privacy", "Të dhënat e tua"),
               ("dpa", "Të dhënat e klientëve të tu")],
        "it": [("condizioni", "Condizioni d'uso"),
               ("privacy", "I tuoi dati"),
               ("dpa", "Dati dei tuoi clienti")],
    }[lingua]
    for nome, etichetta in titoli:
        f = base / f"{nome}_{lingua}.md"
        if not f.is_file():
            f = base / f"{nome}_it.md"
        if f.is_file():
            try:
                pezzi.append((nome, etichetta,
                              _legal_md_to_html(f.read_text(encoding="utf-8"))))
            except OSError:
                pass
    altra = "sq" if lingua == "it" else "it"
    return render_template("legale.html", pezzi=pezzi, lingua=lingua,
                           altra=altra, versione=LEGAL_VERSION)


@app.get("/api/legal/doc/<nome>")
@login_required_api
def api_legal_doc(nome: str):
    """Serve un documento legale. Fonte unica: i file in `legal/`.

    Scritti su file e non nel codice perche' cambiano e perche' devono essere
    **gli stessi** che si mandano via email: se il testo a schermo e quello
    firmato divergono, la firma non prova niente.
    """
    if nome not in ("condizioni", "privacy", "dpa"):
        return jsonify({"error": "not found"}), 404
    # dal file stesso: non dipende da un import che potrebbe non esserci
    base = Path(__file__).resolve().parent.parent / "legal"
    juris = "AL"
    try:
        juris = _active_jurisdiction(getattr(request, "user", None)) or "AL"
    except Exception:  # noqa: BLE001
        pass
    lingua = "sq" if str(juris).upper() == "AL" else "it"
    # la sua lingua se c'e'; altrimenti l'italiano, ma DICENDOLO: un consenso a
    # un testo che non si capisce non e' un consenso.
    f = base / f"{nome}_{lingua}.md"
    tradotto = f.is_file()
    if not tradotto:
        f = base / f"{nome}_it.md"
    if not f.is_file():
        return jsonify({"error": "not found"}), 404
    try:
        testo = f.read_text(encoding="utf-8")
    except OSError:
        return jsonify({"error": "unreadable"}), 500
    return jsonify({"name": nome, "lang": lingua if tradotto else "it",
                    "translated": tradotto, "version": LEGAL_VERSION,
                    "markdown": testo})


@app.get("/api/legal/status")
@login_required_api
def api_legal_status():
    """Deve vedere le condizioni? E cosa ha gia' accettato in passato."""
    user = request.user  # type: ignore[attr-defined]
    ok = storage.has_accepted_legal(user.id, LEGAL_VERSION)
    return jsonify({
        "version": LEGAL_VERSION,
        "accepted": bool(ok),
        "documents": LEGAL_DOCS.split(","),
        "history": storage.legal_acceptances_for(user.id) if ok else [],
    })


@app.post("/api/legal/accept")
@login_required_api
def api_legal_accept():
    """Registra l'accettazione — o dice chiaramente che non ci e' riuscito.

    Se la scrittura fallisce si risponde con un errore invece di lasciar
    passare: un'accettazione che l'utente crede data e che non e' registrata
    e' il peggiore dei due mondi — lui pensa di aver firmato e noi non
    possiamo dimostrarlo.
    """
    user = request.user  # type: ignore[attr-defined]
    data = request.get_json(force=True, silent=True) or {}
    if (data.get("version") or "") != LEGAL_VERSION:
        # il client ha in mano un testo vecchio: meglio farglielo ricaricare
        return jsonify({"error": "version_mismatch",
                        "version": LEGAL_VERSION}), 409
    ok = storage.record_legal_acceptance(
        user_id=user.id, username=getattr(user, "username", None),
        version=LEGAL_VERSION, documents=LEGAL_DOCS,
        ip=(request.headers.get("X-Forwarded-For", "").split(",")[0].strip()
            or request.remote_addr),
        user_agent=request.headers.get("User-Agent"),
    )
    if not ok:
        return jsonify({"error": "not_recorded"}), 500
    log.info("condizioni accettate da %s (versione %s)",
             getattr(user, "username", "?"), LEGAL_VERSION)
    return jsonify({"ok": True, "version": LEGAL_VERSION})


@app.get("/api/ask/active")
@login_required_api
def api_ask_active():
    """C'e' un lavoro ancora in corso per questo fascicolo?

    Il client lo chiede quando riapre un fascicolo che finisce con una domanda
    senza risposta. Se c'e', si riattacca e la risposta compare — anche se la
    domanda era partita da un altro dispositivo. Se non c'e', sa di poterlo
    dire all'avvocato invece di lasciarlo davanti a una pagina muta.
    """
    user = request.user  # type: ignore[attr-defined]
    case_id = (request.args.get("case") or "").strip()
    if not case_id:
        return jsonify({"error": "missing case"}), 400
    return jsonify({"job_id": jobs_mod.find_active(user.id, case_id)})


@app.post("/api/genio/start")
@login_required_api
@require_module("avokat", "prokuror")
def api_genio_start():
    """Commissiona il Genio e restituisce subito il numero di pratica.

    Da qui in poi il socio anziano lavora per conto suo: la connessione che
    ha dato il via puo' morire un secondo dopo — sul telefono succede — e i
    sette-trentatre minuti di ragionamento non si perdono.
    """
    data = request.get_json(force=True, silent=True) or {}
    case_id = (data.get("case_id") or "").strip()
    if not case_id:
        return jsonify({"error": "missing case_id"}), 400
    gen, brief_id, err = _genio_prepare(
        case_id, (data.get("description") or "").strip())
    if err is not None:
        payload, status = err
        return jsonify(payload), status

    user = request.user  # type: ignore[attr-defined]
    job_id = jobs_mod.create(user.id, case_id)
    _uid, _cid = user.id, case_id

    def _run():
        try:
            for frame in gen():
                jobs_mod.push(job_id, frame)
        except Exception as exc:  # noqa: BLE001
            log.exception("genio job %s failed", job_id)
            jobs_mod.push(job_id, _sse_event(
                {"type": "error", "message": html.escape(_safe_err(exc))}))
            jobs_mod.push(job_id, _sse_event({"type": "done"}))
        finally:
            jobs_mod.finish(job_id)
            try:
                push_mod.avvisa(
                    storage, _uid,
                    "Gjenio Legale është gati",
                    "Analiza e thellë e rastit ka përfunduar. Hape për ta lexuar.",
                    url="/", tag="genio-%s" % _cid[:8],
                )
            except Exception:  # noqa: BLE001
                log.debug("push notify skipped (genio)", exc_info=True)

    threading.Thread(target=brain_mod.porta_utente(_uid, _run),
                 name="genio-%s" % job_id[:8],
                     daemon=True).start()
    return jsonify({"job_id": job_id, "brief_id": brief_id})


@app.get("/api/cases/<case_id>/genio")
@login_required_api
def api_genio_list(case_id: str):
    if _resolve_case(case_id) is None:
        return jsonify({"error": "not_found"}), 404
    return jsonify({"items": storage.list_genio_briefs(case_id)})


@app.get("/api/genio/<int:brief_id>")
@login_required_api
def api_genio_get(brief_id: int):
    brief = storage.get_genio_brief(brief_id)
    if brief is None:
        return jsonify({"error": "not_found"}), 404
    if _resolve_case(brief["case_id"]) is None:
        return jsonify({"error": "forbidden"}), 403
    return jsonify(brief)


# ── V9.2 Precedent Pattern Analyzer ────────────────────────────────────

from . import precedent as precedent_mod  # noqa: E402


def _build_precedent_description(case_id: str | None, body_desc: str) -> str:
    """Compose a rich case description from the body + (optional) fascicolo.

    If the analysis is tied to a case, we splice in recent messages and
    document summaries so BM25 retrieval has more signal than the bare
    description string alone.
    """
    parts: list[str] = []
    if body_desc:
        parts.append(body_desc.strip())
    if case_id:
        case = _resolve_case(case_id)
        if case is not None:
            title = getattr(case, "title", None) or getattr(case, "name", None)
            if title and title not in (body_desc or ""):
                parts.insert(0, f"FASCIKULLI: {title}")
            for m in _gather_case_recent_messages(case_id, limit=4):
                content = (m.get("content") or "").strip()
                if content:
                    parts.append(content[:600])
            for d in _gather_case_documents(case_id, limit=4):
                summary = (d.get("summary") or "").strip()
                if summary:
                    parts.append(summary[:400])
    return "\n\n".join(parts).strip()


@app.post("/api/act-check")
@login_required_api
def api_act_check():
    """Quality-check a drafted act: fake / repealed / ambiguous articles."""
    _ensure_loaded()
    if _INDEX is None:
        return jsonify({"error": "index_unavailable"}), 503
    body = request.get_json(silent=True) or {}
    text = (body.get("text") or "").strip()
    if not text:
        return jsonify({"error": "text_required"}), 400
    return jsonify(actcheck_mod.check_act(_req_index(), text[:60000]))


@app.post("/api/second-opinion")
@login_required_api
@require_module("avokat", "prokuror")
def api_second_opinion():
    """Fable 5 second advisor: a shrewd devil's-advocate review of an answer.

    Additive and optional — only runs when the lawyer clicks. Never replaces
    the main Opus answer. Its citations pass the Verifikuar shield."""
    _ensure_loaded()
    if _BRAIN is None:
        return jsonify({"error": "unavailable"}), 503
    body = request.get_json(silent=True) or {}
    question = (body.get("question") or "").strip()
    answer = (body.get("answer") or "").strip()
    if len(answer) < 20:
        return jsonify({"error": "answer_required"}), 400
    try:
        res = second_opinion_mod.review(
            _BRAIN.backend,
            question=question[:4000],
            answer_text=answer[:16000],
        )
    except Exception as exc:  # noqa: BLE001
        log.exception("second-opinion failed")
        return jsonify({"error": _safe_err(exc)}), 200
    md = res.get("markdown") or ""
    citations = {"items": [], "stats": {}}
    try:
        if _INDEX is not None and md:
            citations = cv_mod.verify_text(md, _req_index())
    except Exception:  # noqa: BLE001
        pass
    md = _scudo_citazioni(md, citations)
    return jsonify({"markdown": md, "citations": citations})


@app.post("/api/devil-consult")
@login_required_api
@require_module("avokat", "prokuror")
def api_devil_consult():
    """Pyet Avokatin e Djallit — standalone shrewd consultation (Fable)."""
    _ensure_loaded()
    if _BRAIN is None:
        return jsonify({"error": "unavailable"}), 503
    body = request.get_json(silent=True) or {}
    situation = (body.get("situation") or "").strip()
    if len(situation) < 15:
        return jsonify({"error": "situation_required"}), 400
    try:
        res = second_opinion_mod.consult(_BRAIN.backend,
                                         situation=_with_case(situation[:12000], body))
    except Exception as exc:  # noqa: BLE001
        log.exception("devil-consult failed")
        return jsonify({"error": _safe_err(exc)}), 200
    md = res.get("markdown") or ""
    citations = {"items": [], "stats": {}}
    try:
        if _INDEX is not None and md:
            citations = cv_mod.verify_text(md, _req_index())
    except Exception:  # noqa: BLE001
        pass
    md = _scudo_citazioni(md, citations)
    return jsonify({"markdown": md, "citations": citations})


@app.post("/api/adversary")
@login_required_api
@require_module("avokat", "prokuror")
def api_adversary():
    """Kundershtari — Fable attacks a pasted contract/act as opposing counsel."""
    _ensure_loaded()
    if _BRAIN is None:
        return jsonify({"error": "unavailable"}), 503
    body = request.get_json(silent=True) or {}
    text = (body.get("text") or "").strip()
    if len(text) < 30:
        return jsonify({"error": "text_required"}), 400
    try:
        res = adversary_mod.attack(_BRAIN.backend, text=_with_case(text[:16000], body))
    except Exception as exc:  # noqa: BLE001
        log.exception("adversary failed")
        return jsonify({"error": _safe_err(exc)}), 200
    md = res.get("markdown") or ""
    citations = {"items": [], "stats": {}}
    try:
        if _INDEX is not None and md:
            citations = cv_mod.verify_text(md, _req_index())
    except Exception:  # noqa: BLE001
        pass
    md = _scudo_citazioni(md, citations)
    return jsonify({"markdown": md, "citations": citations})


@app.post("/api/cases/<case_id>/needle")
@login_required_api
def api_case_needle(case_id: str):
    """Gjilpëra në dosje — Fable hunts the overlooked detail across case docs."""
    _ensure_loaded()
    case = _resolve_case(case_id)
    if case is None:
        return jsonify({"error": "not found"}), 404
    if _BRAIN is None:
        return jsonify({"error": "unavailable"}), 503
    try:
        res = vault_mod.find_needle(_BRAIN.backend, case_id)
    except Exception as exc:  # noqa: BLE001
        log.exception("needle failed")
        return jsonify({"error": _safe_err(exc)}), 200
    md = res.get("markdown") or ""
    citations = {"items": [], "stats": {}}
    try:
        if _INDEX is not None and md:
            citations = cv_mod.verify_text(md, _req_index())
    except Exception:  # noqa: BLE001
        pass
    return jsonify({"markdown": md, "citations": citations,
                    "empty": res.get("empty", False), "n_docs": res.get("n_docs", 0)})


@app.post("/api/fable-draft")
@login_required_api
@require_module("avokat", "prokuror")
def api_fable_draft():
    """Fable 5 drafter: contracts / acts / clauses / letters. Additive; output
    citations pass the Verifikuar shield."""
    _ensure_loaded()
    if _BRAIN is None:
        return jsonify({"error": "unavailable"}), 503
    body = request.get_json(silent=True) or {}
    kind = (body.get("kind") or "contract").strip()
    brief = (body.get("brief") or "").strip()
    if len(brief) < 15:
        return jsonify({"error": "brief_required"}), 400
    try:
        res = fable_drafter_mod.draft(_BRAIN.backend, kind=kind,
                                      brief=_with_case(brief[:8000], body),
                                      clauses_text=_firm_clauses_text(body))
    except Exception as exc:  # noqa: BLE001
        log.exception("fable-draft failed")
        return jsonify({"error": _safe_err(exc)}), 200
    md = res.get("markdown") or ""
    citations = {"items": [], "stats": {}}
    try:
        if _INDEX is not None and md:
            citations = cv_mod.verify_text(md, _req_index())
    except Exception:  # noqa: BLE001
        pass
    md = _scudo_citazioni(md, citations)
    return jsonify({"markdown": md, "citations": citations})


@app.post("/api/extract-text")
@login_required_api
def api_extract_text():
    """Extract plain text from an uploaded PDF/image/SVG for the free-form
    PRO tools (act-check, contract review) so the lawyer can attach a file
    instead of pasting. Not tied to a case: extract, return, delete the file."""
    _ensure_loaded()
    if "file" not in request.files:
        return jsonify({"error": "no file"}), 400
    f = request.files["file"]
    if not f.filename:
        return jsonify({"error": "no filename"}), 400
    content = f.read()
    v = docs_mod.validate_upload(f.filename, len(content))
    if not v.ok:
        return jsonify({"error": v.error}), 400
    storage_path = docs_mod.storage_path_for("_scratch", v.ext)
    storage_path.write_bytes(content)
    err = None
    text, used_ocr = "", False
    try:
        text, used_ocr = docs_mod.extract_text(
            storage_path, v.ext, v.mimetype,
            backend=_BRAIN.backend if _BRAIN else None,
        )
    except Exception as exc:
        log.warning("extract-text failed for %s: %s", f.filename, exc)
        err = str(exc)
    finally:
        try:
            storage_path.unlink()
        except Exception:
            pass
    if err and not text:
        return jsonify({"error": "Nuk u lexua dokumenti: " + err}), 422
    return jsonify({
        "text": text or "",
        "used_vision_ocr": used_ocr,
        "filename": f.filename,
    })


@app.post("/api/decision-validity")
@login_required_api
def api_decision_validity():
    """Is a cited decision still good law? Grounded, on-demand check."""
    _ensure_loaded()
    if _BRAIN is None or not _BRAIN.kb.cases:
        return jsonify({"error": "unavailable"}), 503
    body = request.get_json(silent=True) or {}
    try:
        did = int(body.get("id"))
    except (TypeError, ValueError):
        return jsonify({"error": "id_required"}), 400
    dec = _BRAIN.kb.get(did)
    if dec is None:
        return jsonify({"error": "not_found"}), 404
    return jsonify(validity_mod.check(_BRAIN, _BRAIN.kb, dec))


@app.get("/api/precedent-file")
@login_required_api
def api_precedent_file():
    """Serve the locally-stored raw court decision as a download.

    ``f`` is a jurisprudence-relative path (e.g. "kushtetuese/2015/vend.docx").
    Hardened: resolved under data/raw/jurisprudence, no traversal, whitelisted
    extensions. Lets the lawyer keep the original document even if the court
    site later removes it."""
    from pathlib import Path
    from flask import send_file
    rel = (request.args.get("f") or "").strip().lstrip("/")
    if not rel:
        return jsonify({"error": "missing file"}), 400
    base = (Path(__file__).resolve().parent.parent
            / "data" / "raw" / "jurisprudence").resolve()
    target = (base / rel).resolve()
    if base != target and base not in target.parents:
        return jsonify({"error": "forbidden"}), 403
    if target.suffix.lower() not in {".pdf", ".docx", ".doc", ".html", ".htm"}:
        return jsonify({"error": "type not allowed"}), 403
    if not target.is_file():
        return jsonify({"error": "not found"}), 404
    return send_file(str(target), as_attachment=True, download_name=target.name)


@app.post("/api/precedent-analyzer")
@login_required_api
def api_precedent_run():
    """Run the Precedent Pattern Analyzer on a case description.

    Body:
        {
            "case_description": "string (required)",
            "case_id": "string (optional, attaches the brief to a case)",
            "top_k": 5
        }
    """
    user = request.user  # type: ignore[attr-defined]
    body = request.get_json(force=True, silent=True) or {}
    description = (body.get("case_description") or "").strip()
    case_id = body.get("case_id") or None
    try:
        top_k = int(body.get("top_k") or 5)
    except (TypeError, ValueError):
        top_k = 5
    top_k = max(3, min(10, top_k))

    if not description and not case_id:
        return jsonify({"error": "case_description_required"}), 400

    if case_id is not None:
        if _resolve_case(case_id) is None:
            return jsonify({"error": "case_not_found"}), 404

    enriched = _build_precedent_description(case_id, description)
    if not enriched:
        return jsonify({"error": "case_description_empty"}), 400

    _ensure_loaded()
    if _BRAIN is None:
        return jsonify({"error": "brain_unavailable"}), 503

    brief_id = storage.create_precedent_brief(
        case_id=case_id, user_id=user.id,
        case_description=description or enriched[:500],
    )

    # The synthesis is slow (~4-6 min, Opus effort=max). Running it inside the
    # request means holding a multi-minute connection open — fragile on real
    # networks (mobile/proxy drops → "load failed"). Instead we spawn a
    # background thread that persists the brief, and return immediately; the
    # frontend polls GET /api/precedent/<id> for the result.
    brain = _BRAIN

    def _run_precedent_analysis():
        t0 = time.monotonic()
        status = "completed"
        try:
            b = precedent_mod.analyze(
                enriched, backend=brain.backend, top_k=top_k, case_id=case_id,
            )
        except Exception as exc:  # noqa: BLE001
            log.exception("precedent analyzer failed: %s", exc)
            b = {
                "moves_to_imitate": [], "traps_to_avoid": [],
                "kill_shot": {"exists": False, "move": "", "based_on": []},
                "per_precedent": [], "divergence_warning": "",
                "precedents": [], "_parse_error": f"{type(exc).__name__}: {exc}",
            }
            status = "error"
        elapsed_ms = int((time.monotonic() - t0) * 1000)
        if status != "error" and b.get("_parse_error"):
            status = "partial"
        try:
            storage.finalize_precedent_brief(
                brief_id, brief=b, status=status, elapsed_ms=elapsed_ms,
            )
        except Exception as e:  # noqa: BLE001
            log.warning("precedent finalize failed: %s", e)

    threading.Thread(target=brain_mod.porta_utente(user.id, _run_precedent_analysis),
                     name=f"precedent-{brief_id}", daemon=True).start()
    return jsonify({"brief_id": brief_id, "status": "running"})


@app.get("/api/precedent/<int:brief_id>")
@login_required_api
def api_precedent_get(brief_id: int):
    brief = storage.get_precedent_brief(brief_id)
    if brief is None:
        return jsonify({"error": "not_found"}), 404
    user = request.user  # type: ignore[attr-defined]
    if brief["case_id"] is not None:
        if _resolve_case(brief["case_id"]) is None:
            return jsonify({"error": "forbidden"}), 403
    elif brief["user_id"] != user.id:
        return jsonify({"error": "forbidden"}), 403
    return jsonify(brief)


@app.get("/api/cases/<case_id>/precedent")
@login_required_api
def api_precedent_list_for_case(case_id: str):
    if _resolve_case(case_id) is None:
        return jsonify({"error": "not_found"}), 404
    return jsonify({"items": storage.list_precedent_briefs(case_id=case_id)})


@app.get("/api/precedent")
@login_required_api
def api_precedent_list_standalone():
    """List the user's standalone (non-fascicolo) precedent briefs."""
    user = request.user  # type: ignore[attr-defined]
    return jsonify({
        "items": storage.list_precedent_briefs(user_id=user.id),
    })


# ── V9.3 Corporate Intelligence ─────────────────────────────────────────────

from . import corporate as corp_mod  # noqa: E402


@app.post("/api/cases/<case_id>/corporate/extract")
@login_required_api
def api_corporate_extract(case_id: str):
    """Extract structured data from a corporate document.

    Body: { doc_text, doc_name, doc_type }
    Returns: { id, extracted, doc_name, doc_type }
    """
    user = request.user  # type: ignore[attr-defined]
    case = storage.get_case(case_id, user.id)
    if not case:
        return jsonify({"error": "Rasti nuk u gjet"}), 404

    body = request.get_json(silent=True) or {}
    doc_text = (body.get("doc_text") or "").strip()
    doc_name = (body.get("doc_name") or "Dokument i panjohur").strip()
    doc_type = (body.get("doc_type") or "i panjohur").strip()

    if not doc_text:
        return jsonify({"error": "doc_text mungon"}), 400

    if _BRAIN is None:
        return jsonify({"error": "Backend jo i disponueshëm"}), 503

    t0 = time.monotonic()
    extracted = corp_mod.extract_corporate(doc_text, doc_type, backend=_BRAIN.backend)
    elapsed_ms = int((time.monotonic() - t0) * 1000)

    row_id = storage.save_corporate_extraction(
        case_id=case_id,
        user_id=user.id,
        doc_name=doc_name,
        doc_type=doc_type,
        extracted=extracted,
    )
    return jsonify({
        "id": row_id,
        "doc_name": doc_name,
        "doc_type": doc_type,
        "extracted": extracted,
        "elapsed_ms": elapsed_ms,
    }), 201


@app.post("/api/cases/<case_id>/corporate/gatekeeper")
@login_required_api
def api_corporate_gatekeeper(case_id: str):
    """Check signatory authority before signing a contract.

    Body: { signatory_name, value_all?, contract_type? }
    Returns: gatekeeper result dict
    """
    user = request.user  # type: ignore[attr-defined]
    case = storage.get_case(case_id, user.id)
    if not case:
        return jsonify({"error": "Rasti nuk u gjet"}), 404

    body = request.get_json(silent=True) or {}
    signatory_name = (body.get("signatory_name") or "").strip()
    if not signatory_name:
        return jsonify({"error": "signatory_name mungon"}), 400

    value_all = float(body.get("value_all") or 0)
    contract_type = (body.get("contract_type") or "kontratë tregtare").strip()

    rows = storage.list_corporate_extractions(case_id)
    if not rows:
        return jsonify({"error": "Nuk ka dokumente korporative të ngarkuara për këtë rast"}), 400

    if _BRAIN is None:
        return jsonify({"error": "Backend jo i disponueshëm"}), 503

    t0 = time.monotonic()
    result = corp_mod.check_signatory(
        signatory_name, value_all, contract_type,
        [r["extracted"] for r in rows],
        backend=_BRAIN.backend,
    )
    result["elapsed_ms"] = int((time.monotonic() - t0) * 1000)
    return jsonify(result)


@app.post("/api/cases/<case_id>/corporate/kyc")
@login_required_api
def api_corporate_kyc(case_id: str):
    """Return KYC/AML checklist for the case (rule-based, no AI call)."""
    user = request.user  # type: ignore[attr-defined]
    case = storage.get_case(case_id, user.id)
    if not case:
        return jsonify({"error": "Rasti nuk u gjet"}), 404

    rows = storage.list_corporate_extractions(case_id)
    uploaded_types = [r["doc_type"] for r in rows]
    extractions = [r["extracted"] for r in rows]

    result = corp_mod.kyc_checklist(extractions, uploaded_types)
    return jsonify(result)


@app.get("/api/cases/<case_id>/corporate")
@login_required_api
def api_corporate_list(case_id: str):
    """List all corporate extractions for a case."""
    user = request.user  # type: ignore[attr-defined]
    case = storage.get_case(case_id, user.id)
    if not case:
        return jsonify({"error": "Rasti nuk u gjet"}), 404

    rows = storage.list_corporate_extractions(case_id)
    return jsonify({"items": rows})


@app.delete("/api/cases/<case_id>/corporate/<int:extraction_id>")
@login_required_api
def api_corporate_delete(case_id: str, extraction_id: int):
    user = request.user  # type: ignore[attr-defined]
    case = storage.get_case(case_id, user.id)
    if not case:
        return jsonify({"error": "Rasti nuk u gjet"}), 404

    deleted = storage.delete_corporate_extraction(extraction_id, case_id)
    if not deleted:
        return jsonify({"error": "Nuk u gjet"}), 404
    return jsonify({"ok": True})


# ── V9.4 Bench Memo Predictor ────────────────────────────────────────────────

from . import bench_memo as bench_mod  # noqa: E402


def _build_case_summary_for_memo(case_id: str, body_desc: str | None) -> tuple[str, str]:
    """Return (case_description, documents_summary) for the bench memo prompt.

    Stitches case title + recent messages + document summaries so the bench
    memo prompt has rich context beyond the bare description string.
    """
    case = storage.get_case_unscoped(case_id)
    case_title = (case.title if case else "") or ""
    parts = []
    if body_desc:
        parts.append(body_desc.strip())
    if case_title:
        parts.append(f"Titulli i fascikujit: {case_title}")
    try:
        msgs = storage.list_messages(case_id) or []
        if msgs:
            convo = "\n".join(
                f"[{m.role}] {(m.content or '')[:300]}"
                for m in msgs[-12:]
            )
            parts.append(f"Bisedimet e fundit:\n{convo}")
    except Exception:
        pass
    case_description = "\n\n".join(parts) or (body_desc or "")

    doc_lines = []
    try:
        for d in storage.list_documents(case_id) or []:
            summary = (getattr(d, "summary", "") or "").strip()
            if summary:
                doc_lines.append(f"- {d.filename}: {summary[:300]}")
    except Exception:
        pass
    documents_summary = "\n".join(doc_lines)
    return case_description, documents_summary


@app.post("/api/cases/<case_id>/bench-memo")
@login_required_api
def api_bench_memo_run(case_id: str):
    """Generate a judicial bench memo for the case.

    Body: { description?, court_code?, opponent_filing? }
    Returns: { memo_id, status, elapsed_ms, memo }
    """
    user = request.user  # type: ignore[attr-defined]
    case = storage.get_case(case_id, user.id)
    if not case:
        return jsonify({"error": "Rasti nuk u gjet"}), 404
    if _BRAIN is None or _INDEX is None:
        return jsonify({"error": "Backend ose KB jo i disponueshëm"}), 503

    body = request.get_json(silent=True) or {}
    description_hint = (body.get("description") or "").strip()
    court_code = (body.get("court_code") or bench_mod.DEFAULT_COURT).strip()
    opponent_filing = (body.get("opponent_filing") or "").strip()

    case_description, documents_summary = _build_case_summary_for_memo(
        case_id, description_hint
    )
    if not case_description:
        return jsonify({"error": "Përshkrimi i çështjes mungon"}), 400

    memo_id = storage.create_bench_memo(
        case_id=case_id, user_id=user.id,
        description=case_description, court_code=court_code,
        opponent_filing=opponent_filing or None,
    )

    inp = bench_mod.BenchMemoInput(
        case_description=case_description,
        documents_summary=documents_summary,
        opponent_filing=opponent_filing,
        court_code=court_code,
    )

    t0 = time.monotonic()
    memo = bench_mod.generate_bench_memo(
        inp, backend=_BRAIN.backend,
        article_index=_req_index(), decision_index=None,
        case_id=case_id,
    )
    elapsed_ms = int((time.monotonic() - t0) * 1000)
    status = "error" if memo.get("_parse_error") else "completed"
    storage.finalize_bench_memo(memo_id, memo=memo, status=status,
                                elapsed_ms=elapsed_ms)

    return jsonify({
        "memo_id": memo_id, "status": status, "elapsed_ms": elapsed_ms,
        "memo": memo, "court_code": court_code,
    }), 201


@app.get("/api/bench-memo/<int:memo_id>")
@login_required_api
def api_bench_memo_get(memo_id: int):
    user = request.user  # type: ignore[attr-defined]
    row = storage.get_bench_memo(memo_id)
    if not row:
        return jsonify({"error": "Bench memo nuk u gjet"}), 404
    case = storage.get_case(row["case_id"], user.id) if row["case_id"] else None
    if not case:
        return jsonify({"error": "Nuk autorizuar"}), 403
    return jsonify(row)


@app.get("/api/cases/<case_id>/bench-memos")
@login_required_api
def api_bench_memo_list(case_id: str):
    user = request.user  # type: ignore[attr-defined]
    case = storage.get_case(case_id, user.id)
    if not case:
        return jsonify({"error": "Rasti nuk u gjet"}), 404
    return jsonify({"items": storage.list_bench_memos(case_id)})


@app.get("/api/bench-memo/courts")
@login_required_api
def api_bench_memo_courts():
    """Return the list of court codes the user can pick for calibration."""
    return jsonify({
        "default": bench_mod.DEFAULT_COURT,
        "courts": [{"code": k, "label": v}
                   for k, v in bench_mod.COURT_LABELS.items()],
    })


# ── V9.5 Vigilanza Normativa ────────────────────────────────────────────────

from . import vigilanza as vig_mod  # noqa: E402


@app.post("/api/vigilanza/manual")
@login_required_api
def api_vigilanza_manual():
    """Lawyer pastes a new legal update → classify + match against open cases.

    Body: { content, title?, source?, source_url?, published_at? }
    Returns: { update_id, classification, matches[], alerts_created }
    """
    user = request.user  # type: ignore[attr-defined]
    if _BRAIN is None:
        return jsonify({"error": "Backend jo i disponueshëm"}), 503

    body = request.get_json(silent=True) or {}
    content = (body.get("content") or "").strip()
    if not content or len(content) < 50:
        return jsonify({"error": "Përmbajtja mungon ose është shumë e shkurtër"}), 400

    title_hint = (body.get("title") or "").strip()
    source = (body.get("source") or "manual").strip()
    source_url = (body.get("source_url") or "").strip() or None
    published_at = (body.get("published_at") or "").strip() or None

    classification = vig_mod.classify_update(content, backend=_BRAIN.backend)
    title = (title_hint or classification.get("title") or "Update i panjohur")[:300]

    update_id = storage.save_legal_update(
        source=source, source_url=source_url, title=title,
        content=content, published_at=published_at,
        classification=classification, fetched_by=user.id,
    )

    open_cases = storage.list_user_open_cases_for_matching(user.id)
    matches = vig_mod.match_to_cases(classification, open_cases)
    alerts_created = 0
    for m in matches:
        alert_id = storage.create_case_alert(
            case_id=m.case_id, update_id=update_id, user_id=user.id,
            relevance_score=m.relevance_score,
            match_summary={
                "matched_codes": m.matched_codes,
                "matched_articles": m.matched_articles,
                "matched_topics": m.matched_topics,
            },
        )
        if alert_id is not None:
            alerts_created += 1

    return jsonify({
        "update_id": update_id,
        "classification": classification,
        "matches": [{
            "case_id": m.case_id, "case_title": m.case_title,
            "relevance_score": m.relevance_score,
            "matched_codes": m.matched_codes,
            "matched_articles": m.matched_articles,
            "matched_topics": m.matched_topics,
        } for m in matches],
        "alerts_created": alerts_created,
    }), 201


@app.get("/api/vigilanza/alerts")
@login_required_api
def api_vigilanza_alerts():
    """List alerts for the current user. ?case_id=X to filter, ?all=1 to include dismissed."""
    user = request.user  # type: ignore[attr-defined]
    case_id = request.args.get("case_id")
    include_dismissed = request.args.get("all") == "1"
    items = storage.list_case_alerts(
        user_id=user.id, case_id=case_id,
        include_dismissed=include_dismissed,
    )
    return jsonify({"items": items})


@app.get("/api/vigilanza/alerts/count")
@login_required_api
def api_vigilanza_alerts_count():
    user = request.user  # type: ignore[attr-defined]
    return jsonify({"pending": storage.count_pending_alerts(user.id)})


@app.post("/api/vigilanza/alerts/<int:alert_id>/dismiss")
@login_required_api
def api_vigilanza_dismiss(alert_id: int):
    user = request.user  # type: ignore[attr-defined]
    ok = storage.dismiss_alert(alert_id, user.id)
    if not ok:
        return jsonify({"error": "Alert nuk u gjet"}), 404
    return jsonify({"ok": True})


@app.get("/api/vigilanza/updates")
@login_required_api
def api_vigilanza_updates():
    """List recent legal updates classified by the system."""
    return jsonify({"items": storage.list_legal_updates()})


@app.get("/api/vigilanza/updates/<int:update_id>")
@login_required_api
def api_vigilanza_update_get(update_id: int):
    upd = storage.get_legal_update(update_id)
    if not upd:
        return jsonify({"error": "Update nuk u gjet"}), 404
    return jsonify(upd)


# ── V9.6 Ratio Coach ────────────────────────────────────────────────────────

from . import ratio_coach as coach_mod  # noqa: E402


def _build_postmortem_context(case_id: str) -> tuple[str, str, str]:
    """Return (case_title, conversation_text, documents_text) for the post-mortem."""
    case = storage.get_case_unscoped(case_id)
    title = (case.title if case else "") or ""
    msgs = storage.list_messages(case_id) or []
    convo = "\n".join(
        f"[{m.role}] {(m.content or '')[:500]}"
        for m in msgs[-25:]
    )
    docs = []
    try:
        for d in storage.list_documents(case_id) or []:
            summary = (getattr(d, "summary", "") or "").strip()
            if summary:
                docs.append(f"- {d.filename}: {summary[:300]}")
    except Exception:
        pass
    return title, convo, "\n".join(docs)


@app.post("/api/cases/<case_id>/post-mortem")
@login_required_api
def api_postmortem_run(case_id: str):
    """Generate a structured post-mortem lesson for the case.

    Body: { outcome: 'fituar'|'humbur'|'marrëveshje'|'tërhequr'|'i hapur',
            summary_hint?: string }
    Returns: { lesson_id, lesson, elapsed_ms }
    """
    user = request.user  # type: ignore[attr-defined]
    case = storage.get_case(case_id, user.id)
    if not case:
        return jsonify({"error": "Rasti nuk u gjet"}), 404
    if _BRAIN is None:
        return jsonify({"error": "Backend jo i disponueshëm"}), 503

    body = request.get_json(silent=True) or {}
    outcome = (body.get("outcome") or coach_mod.DEFAULT_OUTCOME).strip()
    if outcome not in coach_mod.OUTCOMES:
        return jsonify({"error": f"Outcome jo i vlefshëm. Lejohen: {coach_mod.OUTCOMES}"}), 400
    summary_hint = (body.get("summary_hint") or "").strip()

    title, convo, docs = _build_postmortem_context(case_id)

    inp = coach_mod.PostmortemInput(
        case_title=title, outcome=outcome,
        summary_hint=summary_hint, conversation=convo, documents=docs,
    )

    t0 = time.monotonic()
    lesson = coach_mod.case_postmortem(inp, backend=_BRAIN.backend, case_id=case_id)
    elapsed_ms = int((time.monotonic() - t0) * 1000)

    firm_id = getattr(request.firm, "id", None)  # type: ignore[attr-defined]
    lesson_id = storage.save_case_lesson(
        case_id=case_id, user_id=user.id, firm_id=firm_id,
        outcome=outcome, summary_hint=summary_hint,
        lesson=lesson, elapsed_ms=elapsed_ms,
    )

    return jsonify({
        "lesson_id": lesson_id, "lesson": lesson,
        "elapsed_ms": elapsed_ms, "outcome": outcome,
    }), 201


@app.get("/api/cases/<case_id>/lesson")
@login_required_api
def api_case_lesson_get(case_id: str):
    user = request.user  # type: ignore[attr-defined]
    case = storage.get_case(case_id, user.id)
    if not case:
        return jsonify({"error": "Rasti nuk u gjet"}), 404
    lesson = storage.get_case_lesson(case_id)
    if not lesson:
        return jsonify({"lesson": None})
    return jsonify({"lesson": lesson})


@app.delete("/api/cases/<case_id>/lesson")
@login_required_api
def api_case_lesson_delete(case_id: str):
    user = request.user  # type: ignore[attr-defined]
    case = storage.get_case(case_id, user.id)
    if not case:
        return jsonify({"error": "Rasti nuk u gjet"}), 404
    deleted = storage.delete_case_lesson(case_id, user.id)
    return jsonify({"ok": deleted})


@app.get("/api/lessons")
@login_required_api
def api_lessons_list():
    """List all lessons (own + firm-shared) for the current user."""
    user = request.user  # type: ignore[attr-defined]
    firm_id = getattr(request.firm, "id", None)  # type: ignore[attr-defined]
    return jsonify({
        "items": storage.list_case_lessons(user_id=user.id, firm_id=firm_id),
    })


@app.post("/api/lessons/relevant")
@login_required_api
def api_lessons_relevant():
    """Find the top-3 past lessons most relevant to a new case description.

    Body: { description } OR { case_id }
    """
    user = request.user  # type: ignore[attr-defined]
    body = request.get_json(silent=True) or {}
    description = (body.get("description") or "").strip()
    case_id = (body.get("case_id") or "").strip()

    if case_id and not description:
        # build description from case content
        case = storage.get_case(case_id, user.id)
        if not case:
            return jsonify({"error": "Rasti nuk u gjet"}), 404
        title, convo, docs = _build_postmortem_context(case_id)
        description = "\n".join([title, convo, docs])

    if not description:
        return jsonify({"items": []})

    firm_id = getattr(request.firm, "id", None)  # type: ignore[attr-defined]
    stored = storage.list_case_lessons(user_id=user.id, firm_id=firm_id)
    # exclude this case's own lesson if matching from a case
    if case_id:
        stored = [s for s in stored if s["case_id"] != case_id]

    matches = coach_mod.surface_lessons(description, stored, top_k=3)
    return jsonify({"items": [{
        "lesson_id": m.lesson_id, "case_id": m.case_id,
        "archetype": m.archetype,
        "transferable_lesson": m.transferable_lesson,
        "relevance_score": m.relevance_score,
        "overlap_terms": m.overlap_terms,
        "outcome": m.outcome,
    } for m in matches]})


# ── V8.6 agentic mode (suggestions + auto-letters) ─────────────────────────

AGENT_SCAN_SYSTEM = """Je 'agent proaktiv' brenda Super Avvocato — ndihmës i avokatit shqiptar.

Detyra: lexo kontekstin e një rasti dhe propozoji avokatit MAKSIMUM 4 veprime konkrete që duhen marrë TANI.

Rregulla:
1) Shkruaj VETËM në shqip standard.
2) Mos sajo fakte — bazohu vetëm në kontekstin e dhënë.
3) Kapësh sinjale të vërteta: klient pa kontakt prej kohësh, afat afër, dokument që mungon, precedent përkatës i përmendur, kundërshtar pa përgjigje, fatura të papaguara.
4) Çdo sugjerim duhet të jetë i ekzekutueshëm me një klikim — jo "konsidero të bësh X" por "drafto letër kujtese pagese për klientin Y".
5) NUK propozohet veprim që dështon i pari nga konteksti (p.sh. mos propozo "kontakto klientin" nëse s'ka klient të regjistruar).

Kthe një objekt JSON me skemën:
{
  "suggestions": [
    {
      "kind": "followup_client" | "draft_letter" | "request_docs" | "precedent_alert" | "deadline_reminder",
      "title": "≤ 80 karaktere — titull veprimi",
      "rationale": "1-2 fjali që shpjegojnë pse",
      "payload": {
        // për draft_letter: { "letter_kind": "client_followup"|"payment_reminder"|"court_followup"|"opponent_response"|"document_request", "recipient": "..." (opsional), "subject": "..." (opsional) }
        // për precedent_alert: { "precedent_ids": [...], "summary": "..." }
        // për deadline_reminder: { "due_date": "YYYY-MM-DD", "what": "..." }
        // për request_docs: { "items": ["...", "..."] }
      }
    }
  ]
}

Nëse asgjë nuk është urgjente kthe { "suggestions": [] } dhe asgjë tjetër."""


LETTER_DRAFT_SYSTEMS: dict[str, str] = {
    "client_followup": (
        "Je avokat shqiptar. Drafto një email/letër të shkurtër profesionale për klientin "
        "tënd, në shqip standard, që e informon për ecurinë e rastit dhe i kërkon nëse "
        "është e nevojshme një takim ose informacion. Toni: i ngrohtë por profesional. "
        "Mos shkruaj 'i nderuar' pa emër. Përfshi nënshkrim me [Emri i avokatit]. Vetëm trupi i letrës — pa preambul."
    ),
    "payment_reminder": (
        "Je avokat shqiptar. Drafto një kujtesë të sjellshme por të qartë pagese për klientin, në shqip. "
        "Jep referenca konkrete: numër faturash, shumë, afat. Toni: profesional, pa kërcënime. "
        "Përmend opsionin për plan pagese nëse ka pengesa. Mbylle me nënshkrim [Emri]. Vetëm trupi i letrës."
    ),
    "court_followup": (
        "Je avokat shqiptar. Drafto një kërkesë të shkurtër zyrtare drejtuar gjykatës për "
        "informim mbi statusin e procedurës / caktim seance / lëshim akti. Përdor formulë "
        "zyrtare: 'Gjykatës...', 'Bazuar në nenin...', 'Kërkojmë...'. Vetëm trupi."
    ),
    "opponent_response": (
        "Je avokat shqiptar. Drafto një përgjigje të masur dhe juridike drejtuar avokatit "
        "të palës tjetër. Mbaje neutral por të vendosur. Mos pranosh fakte të padëshmuara. "
        "Përdor formulë: 'I/E nderuar koleg...', mbyll me 'Me respekt, [Emri]'. Vetëm trupi."
    ),
    "document_request": (
        "Je avokat shqiptar. Drafto një kërkesë formale për dokumente, drejtuar palës / "
        "institucionit përkatës. Listo qartë çfarë kërkohet, afatin e arsyeshëm, dhe bazën "
        "ligjore (nëse ka). Toni: profesional, korrekt. Vetëm trupi."
    ),
}


def _build_agent_context(case_id: str, user_id: int) -> str:
    """Compact, trustable context for the agent: case meta, recent messages,
    upcoming events, contacts, unbilled hours, last status updates."""
    lines: list[str] = []
    case = storage.get_case_unscoped(case_id)
    if case is None:
        return ""
    lines.append(f"# Rasti: {case.title}")
    lines.append(f"Stadi: {getattr(case, 'stage', 'intake') or 'intake'}")
    lines.append(f"Krijuar: {case.created_at}")
    lines.append(f"Përditësuar: {case.updated_at}")
    lines.append("")

    # Last 4 messages (lawyer ↔ AI)
    msgs = storage.list_messages(case_id)
    if msgs:
        lines.append("## Bisedat e fundit")
        for m in msgs[-4:]:
            who = "AVOKATI" if m.role == "user" else "AI"
            snippet = (m.content or "")[:600].replace("\n", " ")
            lines.append(f"- [{who}] {snippet}")
        lines.append("")

    # Upcoming events (next 14 days)
    try:
        events = storage.list_events_for_case(case_id) or []
    except Exception:
        events = []
    if events:
        upcoming = [e for e in events
                    if getattr(e, "starts_at", "") >= datetime.now(UTC).strftime("%Y-%m-%d")]
        if upcoming:
            lines.append("## Ngjarje të ardhshme")
            for e in upcoming[:6]:
                lines.append(f"- {e.starts_at} — {getattr(e, 'title', '?')}")
            lines.append("")

    # Clients
    try:
        contacts = storage.list_client_contacts_for_case(case_id) or []
    except Exception:
        contacts = []
    if contacts:
        lines.append("## Klientët")
        for c in contacts[:5]:
            last = getattr(c, "last_viewed_at", None) or "asnjëherë"
            lines.append(f"- {c.name} (parë portalin: {last})")
        lines.append("")
    else:
        lines.append("## Klientët\n- (asnjë klient i regjistruar)\n")

    # Unbilled hours
    try:
        entries = storage.list_time_entries_for_case(case_id, unbilled_only=True)
    except Exception:
        entries = []
    if entries:
        unbilled_total = sum(e.amount_cents for e in entries)
        lines.append(f"## Orë të papaguara: {len(entries)} regjistrime, "
                     f"{storage._fmt_money(unbilled_total, entries[0].currency)}")
        lines.append("")

    # Recent status updates to client
    try:
        updates = storage.list_status_updates_for_case(case_id)[:3]
    except Exception:
        updates = []
    if updates:
        lines.append("## Update-et e fundit drejtuar klientit")
        for u in updates:
            lines.append(f"- [{u.created_at[:10]}] {u.body_sq[:200]}")
        lines.append("")

    return "\n".join(lines)


@app.post("/api/cases/<case_id>/agent/scan")
@login_required_api
def api_agent_scan(case_id: str):
    """The agent reads case context and proposes 0-4 actionable next steps."""
    case = _resolve_case(case_id)
    if case is None:
        return jsonify({"error": "not found"}), 404
    if _BRAIN is None:
        return jsonify({"error": "brain not available"}), 503
    user = request.user  # type: ignore[attr-defined]

    context = _build_agent_context(case_id, user.id)
    if not context:
        return jsonify({"error": "empty context"}), 400
    try:
        raw = _BRAIN.backend.complete(
            system=AGENT_SCAN_SYSTEM,
            messages=[{"role": "user", "content": context}],
            max_tokens=2400,
            fast=False,
        )
        parsed = _intake_parse_json(raw)
    except Exception as exc:
        log.warning("agent scan failed: %s", exc)
        return jsonify({"error": "scan failed",
                        "detail": str(exc)[:200]}), 502

    suggestions = parsed.get("suggestions") or []
    saved = []
    for s in suggestions[:4]:
        kind = s.get("kind")
        title = (s.get("title") or "").strip()
        rationale = (s.get("rationale") or "").strip()
        if not kind or not title or kind not in storage.AGENT_SUGGESTION_KINDS:
            continue
        try:
            sug = storage.create_agent_suggestion(
                case_id, user.id,
                kind=kind, title=title[:200], rationale=rationale[:600],
                payload=s.get("payload") if isinstance(s.get("payload"), dict) else None,
            )
            saved.append(sug)
        except ValueError:
            continue
    return jsonify({
        "scanned_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "suggestions": [_serialize_suggestion(s) for s in saved],
    }), 201


def _serialize_suggestion(s: storage.AgentSuggestion) -> dict:
    return {
        "id": s.id, "kind": s.kind,
        "kind_label": storage.AGENT_SUGGESTION_LABELS_SQ.get(s.kind, s.kind),
        "title": s.title, "rationale": s.rationale,
        "payload": s.payload, "status": s.status,
        "executed_letter_id": s.executed_letter_id,
        "created_at": s.created_at,
    }


@app.get("/api/cases/<case_id>/agent/suggestions")
@login_required_api
def api_list_suggestions(case_id: str):
    if _resolve_case(case_id) is None:
        return jsonify({"error": "not found"}), 404
    include_dismissed = request.args.get("include_dismissed", "").lower() in ("1", "true", "yes")
    items = storage.list_agent_suggestions(case_id, include_dismissed=include_dismissed)
    return jsonify({"suggestions": [_serialize_suggestion(s) for s in items]})


@app.patch("/api/cases/<case_id>/agent/suggestions/<int:sid>")
@login_required_api
def api_update_suggestion(case_id: str, sid: int):
    if _resolve_case(case_id) is None:
        return jsonify({"error": "not found"}), 404
    s = storage.get_agent_suggestion(sid)
    if s is None or s.case_id != case_id:
        return jsonify({"error": "not found"}), 404
    data = request.get_json(force=True, silent=True) or {}
    status = (data.get("status") or "").strip()
    try:
        ok = storage.update_agent_suggestion_status(sid, status)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    if not ok:
        return jsonify({"error": "not found"}), 404
    return jsonify(_serialize_suggestion(storage.get_agent_suggestion(sid)))


@app.delete("/api/cases/<case_id>/agent/suggestions/<int:sid>")
@login_required_api
def api_delete_suggestion(case_id: str, sid: int):
    if _resolve_case(case_id) is None:
        return jsonify({"error": "not found"}), 404
    if not storage.delete_agent_suggestion(sid, case_id):
        return jsonify({"error": "not found"}), 404
    return jsonify({"ok": True})


@app.post("/api/cases/<case_id>/letters")
@login_required_api
def api_create_letter(case_id: str):
    """AI drafts a letter (client_followup, payment_reminder, court_followup,
    opponent_response, document_request). Returns saved draft."""
    case = _resolve_case(case_id)
    if case is None:
        return jsonify({"error": "not found"}), 404
    if _BRAIN is None:
        return jsonify({"error": "brain not available"}), 503
    user = request.user  # type: ignore[attr-defined]
    data = request.get_json(force=True, silent=True) or {}

    kind = (data.get("kind") or "").strip()
    if kind not in storage.AUTO_LETTER_KINDS:
        return jsonify({"error": "invalid kind"}), 400
    recipient = (data.get("recipient") or "").strip() or None
    subject = (data.get("subject") or "").strip() or None
    extra_context = (data.get("context") or "").strip()
    suggestion_id = data.get("from_suggestion_id")

    sys_prompt = LETTER_DRAFT_SYSTEMS[kind]
    case_ctx = _build_agent_context(case_id, user.id)
    user_msg = f"## Konteksti i rastit\n{case_ctx}\n"
    if extra_context:
        user_msg += f"\n## Udhëzime të avokatit\n{extra_context}\n"
    if recipient:
        user_msg += f"\n## Marrësi\n{recipient}\n"
    if subject:
        user_msg += f"\n## Subjekti i kërkuar\n{subject}\n"
    user_msg += "\nTani drafto trupin e letrës në shqip."

    try:
        body_md = _BRAIN.backend.complete(
            system=sys_prompt,
            messages=[{"role": "user", "content": user_msg}],
            max_tokens=1800,
            fast=False,
        )
    except Exception as exc:
        log.warning("letter draft failed: %s", exc)
        return jsonify({"error": "draft failed",
                        "detail": str(exc)[:200]}), 502

    body_md = (body_md or "").strip()
    if not body_md:
        return jsonify({"error": "empty draft"}), 502

    try:
        letter = storage.create_auto_letter(
            case_id, user.id, kind=kind, body_md=body_md,
            recipient=recipient, subject=subject,
        )
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    # If this letter was generated from a suggestion, mark it executed.
    if isinstance(suggestion_id, int):
        s = storage.get_agent_suggestion(suggestion_id)
        if s and s.case_id == case_id:
            storage.update_agent_suggestion_status(
                suggestion_id, "executed", executed_letter_id=letter.id)

    return jsonify(_serialize_letter(letter)), 201


def _serialize_letter(l: storage.AutoLetter) -> dict:
    return {
        "id": l.id, "kind": l.kind,
        "kind_label": storage.AUTO_LETTER_LABELS_SQ.get(l.kind, l.kind),
        "recipient": l.recipient, "subject": l.subject,
        "body_md": l.body_md, "notes": l.notes,
        "status": l.status,
        "created_at": l.created_at, "updated_at": l.updated_at,
    }


@app.get("/api/cases/<case_id>/letters")
@login_required_api
def api_list_letters(case_id: str):
    if _resolve_case(case_id) is None:
        return jsonify({"error": "not found"}), 404
    items = storage.list_auto_letters_for_case(case_id)
    return jsonify({"letters": [_serialize_letter(l) for l in items]})


@app.get("/api/cases/<case_id>/letters/<int:letter_id>")
@login_required_api
def api_get_letter(case_id: str, letter_id: int):
    if _resolve_case(case_id) is None:
        return jsonify({"error": "not found"}), 404
    l = storage.get_auto_letter(letter_id)
    if l is None or l.case_id != case_id:
        return jsonify({"error": "not found"}), 404
    return jsonify(_serialize_letter(l))


@app.patch("/api/cases/<case_id>/letters/<int:letter_id>")
@login_required_api
def api_update_letter(case_id: str, letter_id: int):
    if _resolve_case(case_id) is None:
        return jsonify({"error": "not found"}), 404
    l = storage.get_auto_letter(letter_id)
    if l is None or l.case_id != case_id:
        return jsonify({"error": "not found"}), 404
    data = request.get_json(force=True, silent=True) or {}
    try:
        ok = storage.update_auto_letter(
            letter_id,
            body_md=data.get("body_md"),
            subject=data.get("subject"),
            recipient=data.get("recipient"),
            notes=data.get("notes"),
            status=data.get("status"),
        )
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    if not ok:
        return jsonify({"error": "no fields"}), 400
    return jsonify(_serialize_letter(storage.get_auto_letter(letter_id)))


@app.delete("/api/cases/<case_id>/letters/<int:letter_id>")
@login_required_api
def api_delete_letter(case_id: str, letter_id: int):
    if _resolve_case(case_id) is None:
        return jsonify({"error": "not found"}), 404
    if not storage.delete_auto_letter(letter_id, case_id):
        return jsonify({"error": "not found"}), 404
    return jsonify({"ok": True})


# ── V8.7 in-hearing mobile companion ───────────────────────────────────────

HEARING_QUICK_SYSTEM = """Je 'Super Avvocato' — pranë avokatit në SEANCË gjyqësore.

KONTEKSTI: avokati po flet/pyet me telefonin/laptopin nën dorë. Përgjigja jote duhet të vijë në 5-10 sekonda.

RREGULLA TË FORTA:
1) MAKSIMUM 2-3 fjali. Nëse e nevojshme jep një referim (Neni X i KPC/KPP/KC), pa shpjegime të gjata.
2) SHQIP. Asnjë gjuhë tjetër.
3) Nëse pyetja kërkon kërkim ose nuk ke informacion, thuaj qartë: "Nuk e di me siguri këtë moment" ose "Më duhet kontekst më shumë" — kurrë mos shpik.
4) Përgjigje veprimore: çfarë DUHET të bëjë avokati TANI, jo histori abstrakte.
5) MOS jep këshillë procedurale që të dëmtojë klientin (p.sh. "pranoje" pa kontekst).

Stili: i shkurtër, i drejtpërdrejtë, profesional. Pa fjalë boshe."""


@app.get("/case/<case_id>/in-hearing")
@login_required_page
def in_hearing_page(case_id: str):
    _ensure_loaded()
    case = _resolve_case(case_id)
    if case is None:
        return redirect(url_for("index"))
    return render_template("in_hearing.html", case=case)


@app.post("/api/cases/<case_id>/hearing/notes")
@login_required_api
def api_create_hearing_note(case_id: str):
    if _resolve_case(case_id) is None:
        return jsonify({"error": "not found"}), 404
    user = request.user  # type: ignore[attr-defined]
    data = request.get_json(force=True, silent=True) or {}
    body = (data.get("body_sq") or "").strip()
    kind = (data.get("kind") or "note").strip()
    if not body:
        return jsonify({"error": "body_sq required"}), 400
    if len(body) > 4000:
        body = body[:4000]
    try:
        note = storage.create_hearing_note(
            case_id, user.id, body_sq=body, kind=kind)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    return jsonify(_serialize_hearing_note(note)), 201


def _serialize_hearing_note(n: storage.HearingNote) -> dict:
    return {
        "id": n.id, "kind": n.kind, "body_sq": n.body_sq,
        "parent_id": n.parent_id, "created_at": n.created_at,
    }


@app.get("/api/cases/<case_id>/hearing/notes")
@login_required_api
def api_list_hearing_notes(case_id: str):
    if _resolve_case(case_id) is None:
        return jsonify({"error": "not found"}), 404
    notes = storage.list_hearing_notes_for_case(case_id)
    return jsonify({"notes": [_serialize_hearing_note(n) for n in notes]})


@app.delete("/api/cases/<case_id>/hearing/notes/<int:note_id>")
@login_required_api
def api_delete_hearing_note(case_id: str, note_id: int):
    if _resolve_case(case_id) is None:
        return jsonify({"error": "not found"}), 404
    if not storage.delete_hearing_note(note_id, case_id):
        return jsonify({"error": "not found"}), 404
    return jsonify({"ok": True})


@app.post("/api/cases/<case_id>/hearing/quick")
@login_required_api
def api_hearing_quick(case_id: str):
    """Low-latency Q&A optimized for in-court use. Saves both the question
    and the AI reply as hearing_notes so the lawyer has a full transcript."""
    case = _resolve_case(case_id)
    if case is None:
        return jsonify({"error": "not found"}), 404
    if _BRAIN is None:
        return jsonify({"error": "brain not available"}), 503
    user = request.user  # type: ignore[attr-defined]
    data = request.get_json(force=True, silent=True) or {}
    question = (data.get("question") or "").strip()
    if not question:
        return jsonify({"error": "question required"}), 400
    if len(question) > 1500:
        question = question[:1500]

    # Save question
    try:
        q_note = storage.create_hearing_note(
            case_id, user.id, body_sq=question, kind="question")
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    # Build minimal context: case title + last 3 messages (compact)
    ctx_lines = [f"Rasti: {case.title}"]
    msgs = storage.list_messages(case_id)
    for m in msgs[-3:]:
        who = "AVOKATI" if m.role == "user" else "AI"
        ctx_lines.append(f"[{who}] {(m.content or '')[:300]}")

    user_msg = "## Konteksti i shkurtër\n" + "\n".join(ctx_lines)
    user_msg += f"\n\n## Pyetja TANI në seancë\n{question}"

    try:
        # Avvocato in udienza merita risposta intelligente: Sonnet bilancia
        # qualità e latenza (~3-5s, accettabile in court).
        reply = _BRAIN.backend.complete(
            system=HEARING_QUICK_SYSTEM,
            messages=[{"role": "user", "content": user_msg}],
            max_tokens=400,
            medium=True,
        )
    except Exception as exc:
        log.warning("hearing quick failed: %s", exc)
        return jsonify({"error": "answer failed",
                        "detail": str(exc)[:200]}), 502

    reply = (reply or "").strip()
    if not reply:
        return jsonify({"error": "empty reply"}), 502

    a_note = storage.create_hearing_note(
        case_id, user.id, body_sq=reply, kind="ai_reply", parent_id=q_note.id)

    return jsonify({
        "question": _serialize_hearing_note(q_note),
        "reply": _serialize_hearing_note(a_note),
    }), 201


# ── V8.8 voice rehearsal (judge / opposing / coach) ────────────────────────

REHEARSAL_SYSTEMS: dict[str, str] = {
    "judge": (
        "Je një GJYQTAR shqiptar i ngurtë por i drejtë në një seancë. Avokati po të prezanton "
        "një argument. Roli yt: bëj pyetje të vështira, kërko bazë juridike (citate nenesh), "
        "vër në dukje pikat e dobëta procedurale, dhe kërko qartësi. Mbaje skeptik por i sjellshëm.\n\n"
        "FORMAT: Përgjigja jote duhet të ketë EKZAKTËSISHT 2-3 pyetje të mprehta nga gjykata, "
        "pa preambul. Vetëm pyetje. Shqip standard."
    ),
    "opposing": (
        "Je AVOKATI I PALËS KUNDËRSHTARE në një seancë gjyqësore shqiptare. Avokati përballë "
        "(përdoruesi) po prezanton argumentin e tij. Detyra jote: ngul shtizë, gjej dobësi në "
        "logjikën e tij, citoji prova që dëmtojnë rastin e tij, kërko të paqartat, propozo "
        "interpretim alternativ të ligjit në favor të klientit tënd.\n\n"
        "FORMAT: 1-2 paragrafë me KUNDËR-ARGUMENTE konkrete. Profesional, jo personal. Shqip."
    ),
    "coach": (
        "Je një trajner i lartë i avokatisë shqiptare. Avokati po praktikon argumentin e tij me ty. "
        "Detyra: jep feedback KONSTRUKTIV: çfarë është e fortë, çfarë mungon, ku duhet të citosh "
        "ligj/precedent specifik, ku është gjuha e dobët ose e ndërlikuar. Sugjero përmirësime "
        "konkrete me shembull.\n\n"
        "FORMAT: Listë e shkurtër me 3-5 pika feedback-u (✅ pikat e forta, ⚠️ ku duhet punuar, "
        "💡 sugjerime). Shqip."
    ),
}


@app.post("/api/rehearsal")
@login_required_api
def api_rehearsal():
    """Stateless rehearsal turn. Body: { mode: 'judge'|'opposing'|'coach',
    user_text: '...', case_id: optional (gives a bit of case context),
    history: [{role, content}] (optional, last few turns) }."""
    if _BRAIN is None:
        return jsonify({"error": "brain not available"}), 503
    data = request.get_json(force=True, silent=True) or {}
    mode = (data.get("mode") or "").strip()
    if mode not in REHEARSAL_SYSTEMS:
        return jsonify({"error": "invalid mode"}), 400
    user_text = (data.get("user_text") or "").strip()
    if len(user_text) < 10:
        return jsonify({"error": "user_text too short"}), 400
    if len(user_text) > 6000:
        user_text = user_text[:6000]

    history = data.get("history") if isinstance(data.get("history"), list) else []
    case_ctx = ""
    case_id = (data.get("case_id") or "").strip()
    if case_id:
        case = _resolve_case(case_id)
        if case is not None:
            try:
                case_ctx = f"## Konteksti i rastit\nTitulli: {case.title}\nStadi: {getattr(case, 'stage', 'intake')}\n\n"
            except Exception:
                case_ctx = ""

    messages: list[dict] = []
    for h in history[-6:]:
        if not isinstance(h, dict): continue
        role = h.get("role")
        content = (h.get("content") or "").strip()
        if role in ("user", "assistant") and content:
            messages.append({"role": role, "content": content[:4000]})
    final_user = case_ctx + user_text if case_ctx else user_text
    messages.append({"role": "user", "content": final_user})

    try:
        reply = _BRAIN.backend.complete(
            system=REHEARSAL_SYSTEMS[mode],
            messages=messages,
            max_tokens=1200,
            fast=False,
        )
    except Exception as exc:
        log.warning("rehearsal failed: %s", exc)
        return jsonify({"error": "reply failed",
                        "detail": str(exc)[:200]}), 502
    reply = (reply or "").strip()
    if not reply:
        return jsonify({"error": "empty reply"}), 502
    return jsonify({"mode": mode, "reply": reply})


# ── V8.9 leads (citizen intake → lawyer inbox) ─────────────────────────────

LEAD_INTAKE_SYSTEM = """Je 'Super Avvocato' — bot pranues hyrjesh nga qytetarët shqiptarë drejt një studio avokatie.

Ke marrë mesazhin e parë të një qytetari që përshkruan një problem ligjor. Detyra:
1) Shkruaj një PËRMBLEDHJE 1-2 fjali të problemit (e qartë, neutrale).
2) Klasifiko FUSHËN ligjore (`ai_area`): familjare | pune | penale | civile | tregtare | administrative | trashëgimi | banimore | konsumatore | tjeter
3) Cakto URGJENCËN (`ai_urgency`): high (afat <7 ditësh, arrest, dhunë), medium (situatë problematike por jo akute), low (kërkim informacioni i përgjithshëm)
4) Identifiko 2-4 PYETJE TË RËNDËSISHME që mungojnë (data e ngjarjes, palët e përfshira, dokumentet ekzistuese, etj.) për ta bërë rastin të punueshëm.

Kthe vetëm JSON me skemë:
{
  "summary": "≤200 karaktere — përshkrim neutral i problemit",
  "area": "familjare|pune|...|tjeter",
  "urgency": "low|medium|high",
  "missing_questions": ["Pyetje 1", "Pyetje 2", "Pyetje 3"]
}

Mos shto fjalë të tjera jashtë JSON-it."""


def _classify_lead_problem(problem_text: str) -> dict:
    """AI-classify a lead's problem. Returns {} if anything fails."""
    if _BRAIN is None:
        return {}
    try:
        # V8.10: il summary è letto dall'avvocato → Sonnet (qualità albanese
        # del riassunto + classificazione area conta più della latenza).
        raw = _BRAIN.backend.complete(
            system=LEAD_INTAKE_SYSTEM,
            messages=[{"role": "user", "content": problem_text[:4000]}],
            max_tokens=600,
            medium=True,
        )
        return _intake_parse_json(raw)
    except Exception as exc:
        log.warning("lead classify failed: %s", exc)
        return {}


@app.post("/api/leads/intake")
def api_lead_intake():
    """PUBLIC endpoint — citizen submits a lead via the public form or the
    Telegram bot. No auth required. We rate-limit minimally by problem
    length and require a name. The lead lands in the firm's inbox."""
    data = request.get_json(force=True, silent=True) or {}
    contact_name = (data.get("contact_name") or "").strip()
    contact_phone = (data.get("contact_phone") or "").strip() or None
    contact_email = (data.get("contact_email") or "").strip() or None
    problem_text = (data.get("problem_text") or "").strip()
    firm_slug = (data.get("firm_slug") or "").strip()
    source = (data.get("source") or "web").strip()
    telegram_chat_id = data.get("telegram_chat_id")
    if source not in storage.LEAD_SOURCES:
        return jsonify({"error": "invalid source"}), 400
    if not contact_name:
        return jsonify({"error": "contact_name required"}), 400
    if len(problem_text) < 20:
        return jsonify({"error": "problem_text too short"}), 400
    if len(problem_text) > 6000:
        problem_text = problem_text[:6000]

    firm_id = None
    if firm_slug:
        firm = storage.find_firm_by_slug(firm_slug)
        if firm is None:
            return jsonify({"error": "unknown firm"}), 404
        firm_id = firm.id

    classification = _classify_lead_problem(problem_text)
    summary = (classification.get("summary") or "")[:300] or None
    area = (classification.get("area") or "tjeter")[:40]
    urgency = (classification.get("urgency") or "medium")
    if urgency not in storage.LEAD_URGENCIES:
        urgency = "medium"
    missing = classification.get("missing_questions") or []
    if not isinstance(missing, list):
        missing = []

    try:
        lead = storage.create_lead(
            source=source, contact_name=contact_name,
            contact_phone=contact_phone, contact_email=contact_email,
            problem_text=problem_text, firm_id=firm_id,
            telegram_chat_id=telegram_chat_id if isinstance(telegram_chat_id, int) else None,
            ai_summary=summary, ai_area=area, ai_urgency=urgency,
            ai_missing=missing,
        )
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    return jsonify({
        "lead_id": lead.id,
        "ai_summary": lead.ai_summary,
        "ai_area": lead.ai_area,
        "ai_urgency": lead.ai_urgency,
        "ai_missing": lead.ai_missing,
    }), 201


@app.get("/intake/<firm_slug>")
def public_intake_page(firm_slug: str):
    """Public form a citizen can land on (no login). Branded to the firm."""
    firm = storage.find_firm_by_slug(firm_slug)
    if firm is None:
        return "Studio nuk u gjet.", 404
    return render_template("intake.html", firm=firm, firm_slug=firm_slug)


def _serialize_lead(l: storage.Lead) -> dict:
    return {
        "id": l.id, "firm_id": l.firm_id, "source": l.source,
        "contact_name": l.contact_name, "contact_phone": l.contact_phone,
        "contact_email": l.contact_email, "problem_text": l.problem_text,
        "ai_summary": l.ai_summary, "ai_area": l.ai_area,
        "ai_urgency": l.ai_urgency, "ai_missing": l.ai_missing or [],
        "telegram_chat_id": l.telegram_chat_id,
        "status": l.status, "converted_case_id": l.converted_case_id,
        "assignee_user_id": l.assignee_user_id,
        "created_at": l.created_at, "updated_at": l.updated_at,
    }


@app.get("/api/leads")
@login_required_api
def api_list_leads():
    firm = request.firm  # type: ignore[attr-defined]
    status = request.args.get("status")
    try:
        items = storage.list_leads(
            firm_id=firm.id if firm else None,
            status=status if status else None,
            include_archived=request.args.get("archived", "").lower() in ("1", "true", "yes"),
        )
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    return jsonify({
        "leads": [_serialize_lead(l) for l in items],
        "counts": {
            "new": sum(1 for l in items if l.status == "new"),
            "contacted": sum(1 for l in items if l.status == "contacted"),
            "converted": sum(1 for l in items if l.status == "converted"),
            "rejected": sum(1 for l in items if l.status == "rejected"),
        },
    })


@app.get("/api/leads/<int:lead_id>")
@login_required_api
def api_get_lead(lead_id: int):
    l = storage.get_lead(lead_id)
    if l is None:
        return jsonify({"error": "not found"}), 404
    firm = request.firm  # type: ignore[attr-defined]
    if firm and l.firm_id is not None and l.firm_id != firm.id:
        return jsonify({"error": "not found"}), 404
    return jsonify(_serialize_lead(l))


@app.patch("/api/leads/<int:lead_id>")
@login_required_api
def api_update_lead(lead_id: int):
    l = storage.get_lead(lead_id)
    if l is None:
        return jsonify({"error": "not found"}), 404
    firm = request.firm  # type: ignore[attr-defined]
    if firm and l.firm_id is not None and l.firm_id != firm.id:
        return jsonify({"error": "not found"}), 404
    data = request.get_json(force=True, silent=True) or {}
    user = request.user  # type: ignore[attr-defined]
    try:
        ok = storage.update_lead(
            lead_id,
            status=data.get("status"),
            assignee_user_id=user.id if data.get("claim") else None,
        )
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    if not ok:
        return jsonify({"error": "no fields"}), 400
    return jsonify(_serialize_lead(storage.get_lead(lead_id)))


@app.post("/api/leads/<int:lead_id>/convert")
@login_required_api
def api_convert_lead(lead_id: int):
    """Convert a lead to a real case. Pre-populates the case title and seeds
    the conversation with the citizen's problem text."""
    l = storage.get_lead(lead_id)
    if l is None:
        return jsonify({"error": "not found"}), 404
    if l.status == "converted":
        return jsonify({"error": "already converted",
                        "case_id": l.converted_case_id}), 409
    user = request.user  # type: ignore[attr-defined]
    firm = request.firm  # type: ignore[attr-defined]
    if firm and l.firm_id is not None and l.firm_id != firm.id:
        return jsonify({"error": "not found"}), 404

    data = request.get_json(force=True, silent=True) or {}
    title = (data.get("title") or "").strip() or l.ai_summary or l.contact_name
    case = storage.create_case(user.id, title[:200],
                               firm_id=firm.id if firm else None)
    # Seed conversation with the problem text so the lawyer has it in context
    storage.add_message(
        case.id, "user",
        f"[Hyrje nga klienti — {l.contact_name}]\n\n{l.problem_text}"
    )
    storage.update_lead(lead_id, status="converted",
                        converted_case_id=case.id,
                        assignee_user_id=user.id)
    return jsonify({"case_id": case.id, "lead_id": lead_id}), 201


@app.post("/api/cases/<case_id>/auto-status")
@login_required_api
def api_auto_status(case_id: str):
    """AI proposes a draft status update based on the case context. Returns
    a preview the lawyer can edit before saving via /status-updates."""
    case = _resolve_case(case_id)
    if case is None:
        return jsonify({"error": "not found"}), 404
    if _BRAIN is None:
        return jsonify({"error": "brain not available"}), 503

    # Build context: title, stage, last assistant message, upcoming events
    user_id = case.user_id
    last_msg = ""
    msgs = storage.list_messages(case_id)
    for m in reversed(msgs):
        if m.role == "assistant" and m.content:
            last_msg = m.content[:1500]
            break
    upcoming = []
    for e in storage.list_events(user_id):
        if e.case_id == case_id and not e.done:
            upcoming.append(f"- {e.starts_at[:10]} {e.kind}: {e.title}")
    upcoming_block = "\n".join(upcoming[:5]) or "(asnjë në planifikim)"

    ctx = (
        f"TITULLI: {case.title}\n"
        f"FAZA: {storage.CASE_STAGE_LABELS_SQ.get(case.stage, case.stage)}\n\n"
        f"NGJARJET E ARDHSHME:\n{upcoming_block}\n\n"
        f"MESAZHI I FUNDIT I ASISTENTIT (vetëm për kontekst, mos e cito):\n"
        f"{last_msg or '(asnjë)'}"
    )
    try:
        # V8.10: status update è firmato dall'avvocato e inviato al cittadino →
        # Opus default, comunicazione professionale full quality
        raw = _BRAIN.backend.complete(
            system=AUTO_STATUS_SYSTEM,
            messages=[{"role": "user", "content": ctx}],
            max_tokens=500,
        )
        parsed = _intake_parse_json(raw)
        body_sq = (parsed.get("body_sq") or "").strip()
        kind = (parsed.get("kind") or "status").strip()
        if kind not in storage.CLIENT_UPDATE_KINDS:
            kind = "status"
        return jsonify({"body_sq": body_sq, "kind": kind})
    except Exception as exc:
        log.warning("auto-status failed: %s", exc)
        return jsonify({"error": "generation failed",
                        "detail": str(exc)[:200]}), 502


# ── public portal (token-gated, no login) ──────────────────────────────────

@app.route("/portal/<token>")
def client_portal(token: str):
    """Read-only view of a case for the represented client. The token is
    the only credential — no login, no PII beyond the name the lawyer
    typed. Fails closed (404) on unknown tokens to avoid token enumeration."""
    _ensure_loaded()
    cc = storage.get_client_by_token(token)
    if cc is None:
        return render_template_string(
            "<h1>Linku nuk është i vlefshëm</h1>"
            "<p>Lidhja juaj me studion mund të jetë rifreskuar. "
            "Ju lutem kontaktoni avokatin tuaj për një link të ri.</p>"
        ), 404
    case = storage.get_case_unscoped(cc.case_id)
    if case is None:
        return render_template_string(
            "<h1>Rasti nuk u gjet</h1>"
        ), 404
    storage.mark_portal_viewed(token)

    # Curate visible content: stage, upcoming events tied to the case,
    # status updates the lawyer chose to share. Documents / messages /
    # AI conversation stay private.
    events = [e for e in storage.list_events(case.user_id) if e.case_id == cc.case_id]
    upcoming = sorted(
        [e for e in events if not e.done],
        key=lambda e: e.starts_at,
    )[:10]
    past = sorted(
        [e for e in events if e.done],
        key=lambda e: e.starts_at, reverse=True,
    )[:5]

    updates = storage.list_status_updates_for_case(cc.case_id)

    # Firm name for branding — joined via case row since firm_id isn't on
    # the Case dataclass.
    firm_name = None
    with storage._connect() as conn:
        row = conn.execute(
            "SELECT f.name FROM cases c "
            "LEFT JOIN firms f ON f.id = c.firm_id "
            "WHERE c.id = ?", (cc.case_id,),
        ).fetchone()
        firm_name = row["name"] if row and row["name"] else None

    stage_idx = storage.CASE_STAGES.index(case.stage) if case.stage in storage.CASE_STAGES else 0
    stage_steps = []
    for i, s in enumerate(storage.CASE_STAGES):
        if i < stage_idx:
            state = "past"
        elif i == stage_idx:
            state = "current"
        else:
            state = "future"
        stage_steps.append({
            "key": s, "label": storage.CASE_STAGE_LABELS_SQ[s],
            "state": state,
        })

    return render_template(
        "portal.html",
        client=cc,
        case=case,
        firm_name=firm_name,
        stage_label=storage.CASE_STAGE_LABELS_SQ.get(case.stage, case.stage),
        stage=case.stage,
        stage_steps=stage_steps,
        upcoming_events=upcoming,
        past_events=past,
        updates=updates,
    )


# ── case sharing (firm assignments) ────────────────────────────────────────

def _assignment_payload(a: storage.CaseAssignment) -> dict:
    return {
        "id": a.id, "case_id": a.case_id, "member_id": a.member_id,
        "user_id": a.user_id, "username": a.username,
        "role_in_case": a.role_in_case, "assigned_at": a.assigned_at,
    }


@app.get("/api/cases/<case_id>/assignees")
@login_required_api
def api_list_assignees(case_id: str):
    if _resolve_case(case_id) is None:
        return jsonify({"error": "not found"}), 404
    return jsonify({
        "assignees": [_assignment_payload(a)
                      for a in storage.list_assignments_for_case(case_id)],
    })


@app.post("/api/cases/<case_id>/assignees")
@login_required_api
def api_add_assignee(case_id: str):
    """Assign a firm member to a case. Owner/partner can assign anyone;
    a regular lawyer can assign collaborators on cases they created."""
    user = request.user  # type: ignore[attr-defined]
    firm = request.firm  # type: ignore[attr-defined]
    role = request.role  # type: ignore[attr-defined]
    if firm is None:
        return jsonify({"error": "no active firm"}), 400
    case = _resolve_case(case_id)
    if case is None:
        return jsonify({"error": "not found"}), 404
    can_manage = storage.ROLE_PERMISSIONS.get(role or "", {}).get("all_cases", False)
    if not can_manage and case.user_id != user.id:
        return jsonify({"error": "forbidden"}), 403
    data = request.get_json(force=True, silent=True) or {}
    member_id = data.get("member_id")
    role_in_case = (data.get("role_in_case") or "collaborator").strip()
    if not isinstance(member_id, int):
        return jsonify({"error": "member_id (int) required"}), 400
    # Validate the member belongs to this firm.
    members = {m.id: m for m in storage.list_members(firm.id)}
    if member_id not in members:
        return jsonify({"error": "member not in firm"}), 400
    a = storage.assign_member_to_case(case_id, member_id, role_in_case)
    return jsonify({"assignee": _assignment_payload(a)}), 201


@app.delete("/api/cases/<case_id>/assignees/<int:member_id>")
@login_required_api
def api_remove_assignee(case_id: str, member_id: int):
    user = request.user  # type: ignore[attr-defined]
    role = request.role  # type: ignore[attr-defined]
    case = _resolve_case(case_id)
    if case is None:
        return jsonify({"error": "not found"}), 404
    can_manage = storage.ROLE_PERMISSIONS.get(role or "", {}).get("all_cases", False)
    if not can_manage and case.user_id != user.id:
        return jsonify({"error": "forbidden"}), 403
    if not storage.remove_assignment(case_id, member_id):
        return jsonify({"error": "not found"}), 404
    return jsonify({"ok": True})


# ── case drafts (review loop) ──────────────────────────────────────────────

def _draft_payload(d: storage.CaseDraft) -> dict:
    return {
        "id": d.id, "case_id": d.case_id, "case_title": d.case_title,
        "author_id": d.author_id, "author_username": d.author_username,
        "title": d.title, "content": d.content,
        "kind": d.kind, "kind_label": storage.DRAFT_KIND_LABELS.get(d.kind, d.kind),
        "status": d.status,
        "reviewer_id": d.reviewer_id,
        "reviewer_username": d.reviewer_username,
        "review_comment": d.review_comment,
        "reviewed_at": d.reviewed_at,
        "created_at": d.created_at, "updated_at": d.updated_at,
    }


@app.get("/api/cases/<case_id>/drafts")
@login_required_api
def api_list_case_drafts(case_id: str):
    if _resolve_case(case_id) is None:
        return jsonify({"error": "not found"}), 404
    return jsonify({"drafts": [_draft_payload(d)
                                for d in storage.list_drafts_for_case(case_id)]})


@app.post("/api/cases/<case_id>/drafts")
@login_required_api
def api_create_draft(case_id: str):
    user = request.user  # type: ignore[attr-defined]
    firm = request.firm  # type: ignore[attr-defined]
    if firm is None:
        return jsonify({"error": "no active firm"}), 400
    if _resolve_case(case_id) is None:
        return jsonify({"error": "not found"}), 404
    data = request.get_json(force=True, silent=True) or {}
    try:
        d = storage.create_draft(
            case_id, firm.id, user.id,
            title=data.get("title", ""),
            content=data.get("content", ""),
            kind=(data.get("kind") or "note").strip(),
        )
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    return jsonify({"draft": _draft_payload(d)}), 201


@app.get("/api/dosja")
@login_required_api
def api_dosja():
    """Tutto quello che e' stato salvato, in tutti i fascicoli dello studio.

    Esiste perche' `list_research` da sola non basta: mostra un fascicolo per
    volta, e chi ha chiuso la pagina non si ricorda in quale aveva salvato.
    Qui la domanda e' l'altra — «dov'e' finita quella procura?» — e la
    risposta non puo' dipendere dal ricordarsi il fascicolo.
    """
    firm = request.firm  # type: ignore[attr-defined]
    if firm is None:
        return jsonify({"items": []})
    return jsonify({
        "items": storage.list_firm_research(firm.id, limit=500),
        "docs": storage.list_firm_documents(firm.id, limit=500),
    })


@app.get("/api/cases/<case_id>/research")
@login_required_api
def api_list_research(case_id: str):
    if _resolve_case(case_id) is None:
        return jsonify({"error": "not found"}), 404
    return jsonify({"items": storage.list_research(case_id)})


@app.post("/api/cases/<case_id>/research")
@login_required_api
def api_save_research(case_id: str):
    user = request.user  # type: ignore[attr-defined]
    firm = request.firm  # type: ignore[attr-defined]
    if _resolve_case(case_id) is None:
        return jsonify({"error": "not found"}), 404
    data = request.get_json(silent=True) or {}
    client_name = None
    try:
        clients = storage.list_client_contacts_for_case(case_id)
        if clients:
            client_name = clients[0].name
    except Exception:  # noqa: BLE001
        client_name = None
    try:
        rid = storage.save_research(
            case_id, getattr(firm, "id", None), user.id,
            source=(data.get("source") or "research")[:32],
            title=(data.get("title") or "Kërkim")[:200],
            content=(data.get("content") or ""),
            client_name=client_name,
        )
    except ValueError:
        return jsonify({"error": "empty"}), 400
    return jsonify({"id": rid, "ok": True}), 201


@app.delete("/api/cases/<case_id>/research/<int:research_id>")
@login_required_api
def api_delete_research(case_id: str, research_id: int):
    if _resolve_case(case_id) is None:
        return jsonify({"error": "not found"}), 404
    return jsonify({"ok": storage.delete_research(research_id, case_id)})


@app.get("/api/firm/clients")
@login_required_api
def api_firm_clients():
    """Client directory: firm-wide clients (grouped) + all saved research."""
    firm = request.firm  # type: ignore[attr-defined]
    if firm is None:
        return jsonify({"clients": [], "research": []})
    return jsonify({
        "clients": storage.list_firm_clients(firm.id),
        "research": storage.list_firm_research(firm.id),
    })


@app.get("/api/expertise/templates")
@login_required_api
def api_expertise_templates():
    return jsonify({"templates": expertise_mod.list_templates()})


def _with_case(text: str, body: dict) -> str:
    """Aggiunge al testo il riassunto del fascicolo aperto.

    Cosi' lo strumento PRO continua il lavoro invece di ricominciarlo: sa
    gia' i fatti, cosa ha risposto il cervello e cosa c'e' nel fascicolo.
    Silenzioso se non c'e' un caso o se il caso e' vuoto."""
    cid = (body.get("case_id") or "").strip()
    if not cid or _resolve_case(cid) is None:
        return text or ""
    try:
        return brief_mod.append_to(text or "", cid)
    except Exception:  # noqa: BLE001 - mai bloccare uno strumento per il contesto
        return text or ""


def _notary_run(fn, **kw):
    _ensure_loaded()
    if _BRAIN is None or _INDEX is None:
        return None, (jsonify({"error": "unavailable"}), 503)
    try:
        res = fn(_BRAIN.backend, _req_index(), **kw)
    except ValueError:
        return None, (jsonify({"error": "bad_request"}), 400)
    except Exception as exc:  # noqa: BLE001
        log.exception("notary failed")
        return None, (jsonify({"error": _safe_err(exc)}), 200)
    md = res.get("markdown") or ""
    cits = {"items": [], "stats": {}}
    try:
        if md:
            cits = cv_mod.verify_text(md, _req_index())
    except Exception:  # noqa: BLE001
        pass
    md = _scudo_citazioni(md, cits)
    return jsonify({"markdown": md, "citations": cits}), None


@app.get("/api/notary/deed-types")
@login_required_api
def api_notary_deed_types():
    return jsonify({"types": notary_mod.list_deed_types()})


@app.get("/api/letters/kinds")
@login_required_api
def api_letters_kinds():
    """Catalogo dei destinatari per la giurisdizione della sessione."""
    user = getattr(request, "user", None)
    return jsonify({"kinds": letters_mod.list_kinds(_active_jurisdiction(user))})


@app.post("/api/letters/draft")
@login_required_api
@require_module("avokat", "prokuror", "noter")
def api_letters_draft():
    """Lettera pronta da inviare, radicata nel fascicolo e nel corpus."""
    _ensure_loaded()
    if _BRAIN is None or _INDEX is None:
        return jsonify({"error": "unavailable"}), 503
    body = request.get_json(silent=True) or {}
    kind = (body.get("kind") or "").strip()
    facts = (body.get("facts") or "").strip()
    case_id = (body.get("case_id") or "").strip()

    # il fascicolo e' la ragione d'essere dello strumento: se c'e' un caso,
    # i suoi documenti entrano nel contesto senza che l'avvocato li incolli
    case_context = ""
    if case_id and _resolve_case(case_id) is not None:
        try:
            ctx, used, _n = vault_mod.build_context(case_id)
            if used:
                case_context = ctx
        except Exception:  # noqa: BLE001
            case_context = ""
    if len(facts) < 15 and len(case_context) < 200:
        return jsonify({"error": "facts_required"}), 400

    try:
        res = letters_mod.draft(
            _BRAIN.backend, _req_index(),
            kind=kind, facts=facts, case_context=case_context,
            jurisdiction=_active_jurisdiction(getattr(request, "user", None)),
            form=(body.get("form") or "letter").strip(),
            extra=(body.get("extra") or "").strip()[:4000],
            received=(body.get("received") or "").strip()[:24000],
        )
    except ValueError:
        return jsonify({"error": "bad_request"}), 400
    except Exception as exc:  # noqa: BLE001
        log.exception("letters draft failed")
        return jsonify({"error": _safe_err(exc)}), 200

    md = res.get("markdown") or ""
    cits = {"items": [], "stats": {}}
    try:
        if md:
            cits = cv_mod.verify_text(md, _req_index())
    except Exception:  # noqa: BLE001
        pass
    res["citations"] = cits
    return jsonify(res)


@app.post("/api/letters/docx")
@login_required_api
def api_letters_docx():
    """Solo la lettera in .docx: le sezioni operative restano all'avvocato."""
    body = request.get_json(silent=True) or {}
    md = letters_mod.letter_body((body.get("markdown") or "").strip())
    if len(md) < 5:
        return Response("empty", status=400)
    title = (body.get("title") or "Lettera").strip()
    lines = []
    for ln in md.split("\n"):
        t = ln.rstrip()
        st = t.lstrip()
        if st.startswith("* ") and not st.startswith("**"):
            t = t[: len(t) - len(st)] + "- " + st[2:]
        t = re.sub(r"\*\*(.+?)\*\*", r"\1", t)
        t = re.sub(r"`([^`]+)`", r"\1", t)
        lines.append(t)
    safe = re.sub(r"[^0-9A-Za-zçëÇË _-]", "", title)[:60].strip() or "lettera"
    out_path = APP_DB_PATH.parent / "exports" / (safe.replace(" ", "_") + ".docx")
    try:
        pro_mod.render_act_docx({"title": title, "body_markdown": "\n".join(lines)},
                                out_path)
    except Exception as exc:  # noqa: BLE001
        log.exception("letters docx failure")
        return Response(f"render error: {exc}", status=500)
    return send_file(
        out_path, as_attachment=True, download_name=safe + ".docx",
        mimetype="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    )


@app.post("/api/notary/draft")
@login_required_api
@require_module("noter")
def api_notary_draft():
    body = request.get_json(silent=True) or {}
    details = (body.get("details") or "").strip()
    if len(details) < 10:
        return jsonify({"error": "details_required"}), 400
    out, err = _notary_run(notary_mod.draft_deed,
                           deed_type=(body.get("deed_type") or "").strip(),
                           details=_with_case(details[:12000], body),
                           clauses_text=_firm_clauses_text(body))
    return err if err else out


@app.post("/api/notary/check")
@login_required_api
def api_notary_check():
    body = request.get_json(silent=True) or {}
    text = (body.get("text") or "").strip()
    if len(text) < 30:
        return jsonify({"error": "text_required"}), 400
    out, err = _notary_run(notary_mod.check_deed, text=_with_case(text[:16000], body))
    return err if err else out


@app.post("/api/notary/succession")
@login_required_api
@require_module("noter")
def api_notary_succession():
    body = request.get_json(silent=True) or {}
    sit = (body.get("situation") or "").strip()
    if len(sit) < 15:
        return jsonify({"error": "situation_required"}), 400
    out, err = _notary_run(notary_mod.succession, situation=_with_case(sit[:8000], body))
    return err if err else out


@app.get("/api/notary/prokura-scopes")
@login_required_api
def api_notary_prokura_scopes():
    return jsonify(notary_mod.list_prokura_scopes())


@app.post("/api/notary/prokura")
@login_required_api
@require_module("noter")
def api_notary_prokura():
    body = request.get_json(silent=True) or {}
    scopes = body.get("scope_keys") or []
    if not isinstance(scopes, list):
        scopes = []
    out, err = _notary_run(notary_mod.draft_prokura,
                           form=(body.get("form") or "e_posacme").strip(),
                           scope_keys=[str(x)[:40] for x in scopes][:16],
                           details=(body.get("details") or "").strip()[:12000],
                           duration=(body.get("duration") or "").strip()[:120],
                           subdelegation=bool(body.get("subdelegation")),
                           clauses_text=_firm_clauses_text(body))
    return err if err else out


@app.get("/api/notary/declaration-types")
@login_required_api
def api_notary_declaration_types():
    return jsonify({"types": notary_mod.list_declaration_types()})


@app.post("/api/notary/declaration")
@login_required_api
@require_module("noter")
def api_notary_declaration():
    body = request.get_json(silent=True) or {}
    details = (body.get("details") or "").strip()
    if len(details) < 10:
        return jsonify({"error": "details_required"}), 400
    out, err = _notary_run(notary_mod.draft_declaration,
                           decl_type=(body.get("decl_type") or "").strip(),
                           details=details[:12000])
    return err if err else out


@app.post("/api/notary/documents")
@login_required_api
@require_module("noter")
def api_notary_documents():
    body = request.get_json(silent=True) or {}
    act = (body.get("act") or "").strip()
    if len(act) < 6:
        return jsonify({"error": "act_required"}), 400
    out, err = _notary_run(notary_mod.documents_needed, act=_with_case(act[:2000], body))
    return err if err else out


@app.post("/api/notary/revocation")
@login_required_api
@require_module("noter")
def api_notary_revocation():
    body = request.get_json(silent=True) or {}
    details = (body.get("details") or "").strip()
    if len(details) < 10:
        return jsonify({"error": "details_required"}), 400
    out, err = _notary_run(notary_mod.draft_revocation, details=_with_case(details[:12000], body))
    return err if err else out


@app.post("/api/notary/conflicts")
@login_required_api
def api_notary_conflicts():
    body = request.get_json(silent=True) or {}
    case_id = (body.get("case_id") or "").strip()
    new_act = (body.get("new_act") or "").strip()
    if len(new_act) < 20:
        return jsonify({"error": "new_act_required"}), 400
    prior = []
    if case_id and _resolve_case(case_id) is not None:
        try:
            items = storage.list_research(case_id)
            notarial = [it for it in items if (it.get("source") or "") == "notary"]
            prior = notarial or items
        except Exception:  # noqa: BLE001
            prior = []
    out, err = _notary_run(
        notary_mod.check_conflicts,
        new_act=new_act[:12000],
        prior_acts=[{"title": p.get("title"), "content": p.get("content")} for p in prior[:8]])
    return err if err else out


@app.post("/api/notary/inspect")
@login_required_api
def api_notary_inspect():
    _ensure_loaded()
    if _BRAIN is None or _INDEX is None:
        return jsonify({"error": "unavailable"}), 503
    body = request.get_json(silent=True) or {}
    text = (body.get("text") or "").strip()
    if len(text) < 30:
        return jsonify({"error": "text_required"}), 400
    case_id = (body.get("case_id") or "").strip()
    prior = []
    if case_id and _resolve_case(case_id) is not None:
        try:
            items = storage.list_research(case_id)
            notarial = [it for it in items if (it.get("source") or "") == "notary"]
            prior = [{"title": p.get("title"), "content": p.get("content")}
                     for p in (notarial or items)[:6]]
        except Exception:  # noqa: BLE001
            prior = []
    try:
        res = notary_mod.inspect_act(_BRAIN.backend, _req_index(), text=text[:14000], prior_acts=prior)
    except Exception as exc:  # noqa: BLE001
        log.exception("inspect failed")
        return jsonify({"error": _safe_err(exc)}), 200
    md = res.get("markdown") or ""
    cits = {"items": [], "stats": {}}
    try:
        if md:
            cits = cv_mod.verify_text(md, _req_index())
    except Exception:  # noqa: BLE001
        pass
    try:
        storage.log_inspection(getattr(getattr(request, "firm", None), "id", None),
                               res.get("risk"), res.get("verdict"))
    except Exception:  # noqa: BLE001
        pass
    return jsonify({"markdown": md, "risk": res.get("risk"),
                    "verdict": res.get("verdict"), "citations": cits})


@app.post("/api/notary/extract")
@login_required_api
def api_notary_extract():
    body = request.get_json(silent=True) or {}
    text = (body.get("text") or "").strip()
    case_id = (body.get("case_id") or "").strip()
    if not text and case_id and _resolve_case(case_id) is not None:
        try:
            ctx, used, _n = vault_mod.build_context(case_id)
            if used:
                text = ctx
        except Exception:  # noqa: BLE001
            text = ""
    if len(text) < 20:
        return jsonify({"error": "text_required"}), 400
    out, err = _notary_run(notary_mod.extract_data, text=text[:16000])
    return err if err else out


@app.post("/api/notary/checklist")
@login_required_api
def api_notary_checklist():
    _ensure_loaded()
    if _BRAIN is None or _INDEX is None:
        return jsonify({"error": "unavailable"}), 503
    body = request.get_json(silent=True) or {}
    act = (body.get("act") or "").strip()
    if len(act) < 3:
        return jsonify({"error": "act_required"}), 400
    text = (body.get("text") or "").strip()
    case_id = (body.get("case_id") or "").strip()
    if not text and case_id and _resolve_case(case_id) is not None:
        try:
            ctx, used, _n = vault_mod.build_context(case_id)
            if used:
                text = ctx
        except Exception:  # noqa: BLE001
            text = ""
    if len(text) < 20:
        return jsonify({"error": "documents_required"}), 400
    try:
        res = notary_mod.dossier_checklist(_BRAIN.backend, _req_index(), act=act[:200],
                                           documents_text=text[:16000])
    except Exception as exc:  # noqa: BLE001
        log.exception("checklist failed")
        return jsonify({"error": _safe_err(exc)}), 200
    md = res.get("markdown") or ""
    cits = {"items": [], "stats": {}}
    try:
        if md:
            cits = cv_mod.verify_text(md, _req_index())
    except Exception:  # noqa: BLE001
        pass
    return jsonify({"markdown": md, "completeness": res.get("completeness"), "citations": cits})


@app.get("/api/notary/client-kinds")
@login_required_api
def api_notary_client_kinds():
    return jsonify({"kinds": notary_mod.list_client_kinds()})


@app.post("/api/registry/search")
@login_required_api
@require_module("avokat", "prokuror")
def api_registry_search():
    _ensure_loaded()
    if _BRAIN is None:
        return jsonify({"error": "unavailable"}), 503
    firm = getattr(request, "firm", None)
    body = request.get_json(silent=True) or {}
    q = (body.get("query") or "").strip()
    if len(q) < 2:
        return jsonify({"error": "query_required"}), 400
    case_id = (body.get("case_id") or "").strip()
    acts = []
    if case_id and _resolve_case(case_id) is not None:
        try:
            acts = storage.list_research(case_id)
        except Exception:  # noqa: BLE001
            acts = []
    elif firm is not None:
        try:
            acts = storage.list_firm_research(firm.id)
        except Exception:  # noqa: BLE001
            acts = []
    if not acts:
        return jsonify({"markdown": "Regjistri është bosh — ende asnjë akt i ruajtur. "
                                    "Ruaj akte me \u201c\ud83d\udcbe Ruaj në fashikull\u201d.",
                        "matches": []})
    try:
        res = registry_mod.search_acts(_BRAIN.backend, q, acts)
    except Exception as exc:  # noqa: BLE001
        log.exception("registry failed")
        return jsonify({"error": _safe_err(exc)}), 200
    ids = set(res.get("match_ids") or [])
    matches = [a for a in acts if str(a.get("id")) in ids]
    return jsonify({"markdown": res.get("markdown") or "", "matches": matches})


@app.post("/api/notary/client")
@login_required_api
def api_notary_client():
    body = request.get_json(silent=True) or {}
    text = (body.get("text") or "").strip()
    if len(text) < 10:
        return jsonify({"error": "text_required"}), 400
    out, err = _notary_run(notary_mod.client_comm,
                           kind=(body.get("kind") or "shpjego").strip()[:30],
                           text=text[:14000])
    return err if err else out


@app.post("/api/notary/whatif")
@login_required_api
def api_notary_whatif():
    body = request.get_json(silent=True) or {}
    act = (body.get("act") or "").strip()
    change = (body.get("change") or "").strip()
    if len(act) < 15 or len(change) < 4:
        return jsonify({"error": "act_and_change_required"}), 400
    out, err = _notary_run(notary_mod.what_if, act=act[:12000], change=change[:2000])
    return err if err else out


def _firm_clauses_text(body):
    """Build the studio's preferred-clauses block, if the request opted in."""
    if not (body or {}).get("use_clauses"):
        return ""
    firm = getattr(request, "firm", None)
    if firm is None:
        return ""
    try:
        cl = storage.list_firm_clauses(firm.id)
    except Exception:  # noqa: BLE001
        return ""
    return "\n\n".join(
        "\u2022 [%s] %s\n%s" % ((c.get("category") or "-"), (c.get("label") or ""),
                                  (c.get("content") or "")[:1200])
        for c in cl[:20])


@app.get("/api/firm/dashboard")
@login_required_api
def api_firm_dashboard():
    firm = getattr(request, "firm", None)
    if firm is None:
        return jsonify({"empty": True})
    return jsonify(storage.firm_dashboard(firm.id))


@app.get("/api/firm/clauses")
@login_required_api
def api_firm_clauses_list():
    firm = getattr(request, "firm", None)
    if firm is None:
        return jsonify({"clauses": []})
    return jsonify({"clauses": storage.list_firm_clauses(firm.id)})


@app.post("/api/firm/clauses")
@login_required_api
def api_firm_clauses_add():
    user = request.user  # type: ignore[attr-defined]
    firm = getattr(request, "firm", None)
    if firm is None:
        return jsonify({"error": "no_firm"}), 400
    body = request.get_json(silent=True) or {}
    try:
        cid = storage.add_firm_clause(firm.id, user.id,
                                      label=(body.get("label") or "").strip(),
                                      category=(body.get("category") or "").strip() or None,
                                      content=(body.get("content") or "").strip())
    except ValueError:
        return jsonify({"error": "empty"}), 400
    return jsonify({"id": cid, "ok": True}), 201


@app.delete("/api/firm/clauses/<int:clause_id>")
@login_required_api
def api_firm_clauses_delete(clause_id: int):
    firm = getattr(request, "firm", None)
    if firm is None:
        return jsonify({"ok": False}), 400
    return jsonify({"ok": storage.delete_firm_clause(clause_id, firm.id)})


@app.post("/api/prosecutor/indictment")
@login_required_api
@require_module("prokuror")
def api_prosecutor_indictment():
    _ensure_loaded()
    if _BRAIN is None or _INDEX is None:
        return jsonify({"error": "unavailable"}), 503
    body = request.get_json(silent=True) or {}
    facts = (body.get("facts") or "").strip()
    if len(facts) < 15:
        return jsonify({"error": "facts_required"}), 400
    try:
        res = prosecutor_mod.draft_indictment(_BRAIN.backend, _req_index(), facts=facts[:14000])
    except Exception as exc:  # noqa: BLE001
        log.exception("indictment failed")
        return jsonify({"error": _safe_err(exc)}), 200
    md = res.get("markdown") or ""
    cits = {"items": [], "stats": {}}
    try:
        if md:
            cits = cv_mod.verify_text(md, _req_index())
    except Exception:  # noqa: BLE001
        pass
    md = _scudo_citazioni(md, cits)
    return jsonify({"markdown": md, "citations": cits})


def _pros_facts(fn, body, key="facts", minlen=15, **extra):
    val = (body.get(key) or "").strip()
    if len(val) < minlen:
        return jsonify({"error": key + "_required"}), 400
    kw = {key: _with_case(val[:14000], body)}
    kw.update(extra)
    out, err = _notary_run(fn, **kw)
    return err if err else out


@app.get("/api/prosecutor/act-kinds")
@login_required_api
def api_prosecutor_act_kinds():
    return jsonify({"kinds": prosecutor_mod.list_act_kinds()})


@app.post("/api/prosecutor/investigation-plan")
@login_required_api
@require_module("prokuror")
def api_prosecutor_plan():
    return _pros_facts(prosecutor_mod.investigation_plan, request.get_json(silent=True) or {})


@app.post("/api/prosecutor/investigative-act")
@login_required_api
@require_module("prokuror")
def api_prosecutor_act():
    body = request.get_json(silent=True) or {}
    return _pros_facts(prosecutor_mod.investigative_act, body,
                       kind=(body.get("kind") or "kontroll").strip()[:20])


@app.post("/api/prosecutor/coercive-measure")
@login_required_api
@require_module("prokuror")
def api_prosecutor_measure():
    return _pros_facts(prosecutor_mod.coercive_measure, request.get_json(silent=True) or {})


@app.post("/api/prosecutor/dismissal")
@login_required_api
@require_module("prokuror")
def api_prosecutor_dismissal():
    return _pros_facts(prosecutor_mod.dismissal_request, request.get_json(silent=True) or {})


@app.post("/api/prosecutor/stress-test")
@login_required_api
@require_module("prokuror")
def api_prosecutor_stress():
    return _pros_facts(prosecutor_mod.stress_test, request.get_json(silent=True) or {},
                       key="text", minlen=30)


@app.post("/api/prosecutor/complaint")
@login_required_api
@require_module("prokuror")
def api_prosecutor_complaint():
    return _pros_facts(prosecutor_mod.citizen_complaint, request.get_json(silent=True) or {})


@app.post("/api/prosecutor/victim-rights")
@login_required_api
@require_module("prokuror")
def api_prosecutor_victim():
    return _pros_facts(prosecutor_mod.victim_rights, request.get_json(silent=True) or {})


@app.post("/api/prosecutor/dismissal-appeal")
@login_required_api
@require_module("prokuror")
def api_prosecutor_appeal():
    return _pros_facts(prosecutor_mod.dismissal_appeal, request.get_json(silent=True) or {})


@app.post("/api/prosecutor/delay")
@login_required_api
@require_module("prokuror")
def api_prosecutor_delay():
    return _pros_facts(prosecutor_mod.delay_complaint, request.get_json(silent=True) or {})


@app.post("/api/deep-verify")
@login_required_api
def api_deep_verify():
    body = request.get_json(silent=True) or {}
    text = (body.get("text") or "").strip()
    if len(text) < 30:
        return jsonify({"error": "text_required"}), 400
    out, err = _notary_run(living_mod.verify_claims, text=text[:16000])
    return err if err else out


@app.post("/api/law-live")
@login_required_api
def api_law_live():
    body = request.get_json(silent=True) or {}
    q = (body.get("query") or "").strip()
    if len(q) < 4:
        return jsonify({"error": "query_required"}), 400
    out, err = _notary_run(living_mod.check_law_live, query=q[:2000])
    return err if err else out


@app.post("/api/intake/triage")
@login_required_api
@require_module("avokat", "prokuror")
def api_intake_triage():
    _ensure_loaded()
    if _BRAIN is None or _INDEX is None:
        return jsonify({"error": "unavailable"}), 503
    body = request.get_json(silent=True) or {}
    story = (body.get("story") or "").strip()
    if len(story) < 15:
        return jsonify({"error": "story_required"}), 400
    try:
        res = intake_mod.triage(_BRAIN.backend, _req_index(), story=story[:8000])
    except Exception as exc:  # noqa: BLE001
        log.exception("intake failed")
        return jsonify({"error": _safe_err(exc)}), 200
    md = res.get("markdown") or ""
    cits = {"items": [], "stats": {}}
    try:
        if md:
            cits = cv_mod.verify_text(md, _req_index())
    except Exception:  # noqa: BLE001
        pass
    return jsonify({"markdown": md, "route": res.get("route", "none"), "citations": cits})


@app.get("/api/afati/triggers")
@login_required_api
def api_afati_triggers():
    return jsonify({"triggers": afati_mod.list_triggers()})


@app.post("/api/afati/compute")
@login_required_api
def api_afati_compute():
    _ensure_loaded()
    if _BRAIN is None or _INDEX is None:
        return jsonify({"error": "unavailable"}), 503
    body = request.get_json(silent=True) or {}
    trigger = (body.get("trigger") or "tjeter").strip()[:30]
    event_date = (body.get("event_date") or "").strip()[:20]
    facts = (body.get("facts") or "").strip()[:6000]
    try:
        res = afati_mod.compute(_BRAIN.backend, _req_index(), trigger=trigger,
                                event_date=event_date, facts=_with_case(facts, body))
    except Exception as exc:  # noqa: BLE001
        log.exception("afati failed")
        return jsonify({"error": _safe_err(exc)}), 200
    md = res.get("markdown") or ""
    cits = {"items": [], "stats": {}}
    try:
        if md:
            cits = cv_mod.verify_text(md, _req_index())
    except Exception:  # noqa: BLE001
        pass
    return jsonify({"markdown": md, "afatet": res.get("afatet", []), "citations": cits})


@app.post("/api/deadlines/prescription")
@login_required_api
def api_prescription():
    _ensure_loaded()
    if _BRAIN is None or _INDEX is None:
        return jsonify({"error": "unavailable"}), 503
    body = request.get_json(silent=True) or {}
    facts = (body.get("facts") or "").strip()
    if len(facts) < 15:
        return jsonify({"error": "facts_required"}), 400
    try:
        res = deadlines_mod.prescription(_BRAIN.backend, _req_index(),
                                         facts=_with_case(facts[:8000], body))
    except Exception as exc:  # noqa: BLE001
        log.exception("prescription failed")
        return jsonify({"error": _safe_err(exc)}), 200
    md = res.get("markdown") or ""
    cits = {"items": [], "stats": {}}
    try:
        if md:
            cits = cv_mod.verify_text(md, _req_index())
    except Exception:  # noqa: BLE001
        pass
    md = _scudo_citazioni(md, cits)
    return jsonify({"markdown": md, "citations": cits})


@app.post("/api/prosecutor/analyze")
@login_required_api
@require_module("prokuror")
def api_prosecutor_analyze():
    _ensure_loaded()
    if _BRAIN is None or _INDEX is None:
        return jsonify({"error": "unavailable"}), 503
    body = request.get_json(silent=True) or {}
    facts = (body.get("facts") or "").strip()
    if len(facts) < 15:
        return jsonify({"error": "facts_required"}), 400
    try:
        res = prosecutor_mod.analyze(_BRAIN.backend, _req_index(), facts=facts[:14000])
    except Exception as exc:  # noqa: BLE001
        log.exception("prosecutor failed")
        return jsonify({"error": _safe_err(exc)}), 200
    md = res.get("markdown") or ""
    citations = {"items": [], "stats": {}}
    try:
        if md:
            citations = cv_mod.verify_text(md, _req_index())
    except Exception:  # noqa: BLE001
        pass
    md = _scudo_citazioni(md, citations)
    return jsonify({"markdown": md, "citations": citations})


@app.post("/api/expertise/analyze")
@login_required_api
@require_module("avokat", "prokuror")
def api_expertise_analyze():
    _ensure_loaded()
    if _BRAIN is None or _INDEX is None:
        return jsonify({"error": "unavailable"}), 503
    body = request.get_json(silent=True) or {}
    case_type = (body.get("case_type") or "").strip()
    facts = (body.get("facts") or "").strip()
    if len(facts) < 15:
        return jsonify({"error": "facts_required"}), 400
    try:
        res = expertise_mod.analyze(_BRAIN.backend, _req_index(), case_type=case_type,
                                    facts=_with_case(facts[:14000], body))
    except ValueError:
        return jsonify({"error": "unknown_case_type"}), 400
    except Exception as exc:  # noqa: BLE001
        log.exception("expertise failed")
        return jsonify({"error": _safe_err(exc)}), 200
    md = res.get("markdown") or ""
    citations = {"items": [], "stats": {}}
    try:
        if md:
            citations = cv_mod.verify_text(md, _req_index())
    except Exception:  # noqa: BLE001
        pass
    md = _scudo_citazioni(md, citations)
    return jsonify({"markdown": md, "citations": citations})


@app.get("/api/firm/review-queue")
@login_required_api
def api_review_queue():
    """Pending drafts in the firm. Senior roles (lawyer+) see all; juniors
    see only their own submissions, so they can track review status."""
    user = request.user  # type: ignore[attr-defined]
    firm = request.firm  # type: ignore[attr-defined]
    role = request.role  # type: ignore[attr-defined]
    if firm is None:
        return jsonify({"error": "no active firm"}), 400
    status = (request.args.get("status") or "pending").strip()
    if status not in storage.DRAFT_STATUSES:
        return jsonify({"error": f"invalid status: {status}"}), 400
    can_review = role in ("owner", "partner", "lawyer")
    author_id = None if can_review else user.id
    drafts = storage.list_review_queue(firm.id, status=status, author_id=author_id)
    return jsonify({
        "drafts": [_draft_payload(d) for d in drafts],
        "can_review": can_review,
        "status": status,
    })


@app.patch("/api/drafts/<int:draft_id>")
@login_required_api
def api_review_draft(draft_id: int):
    user = request.user  # type: ignore[attr-defined]
    role = request.role  # type: ignore[attr-defined]
    if role not in ("owner", "partner", "lawyer"):
        return jsonify({"error": "forbidden",
                        "needed": "lawyer-or-above",
                        "your_role": role}), 403
    data = request.get_json(force=True, silent=True) or {}
    status = (data.get("status") or "").strip()
    comment = (data.get("comment") or "").strip() or None
    try:
        d = storage.review_draft(draft_id, user.id, status=status, comment=comment)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    if d is None:
        return jsonify({"error": "draft not found or already reviewed"}), 404
    return jsonify({"draft": _draft_payload(d)})


@app.delete("/api/drafts/<int:draft_id>")
@login_required_api
def api_delete_draft(draft_id: int):
    user = request.user  # type: ignore[attr-defined]
    if not storage.delete_draft(draft_id, user.id):
        return jsonify({"error": "not found or not deletable"}), 404
    return jsonify({"ok": True})


# ── parties (conflict-of-interest source) ──────────────────────────────────

def _party_payload(p: storage.CaseParty) -> dict:
    return {
        "id": p.id, "case_id": p.case_id,
        "name": p.display_name, "side": p.side,
        "source": p.source, "created_at": p.created_at,
    }


@app.get("/api/cases/<case_id>/parties")
@login_required_api
def api_list_parties(case_id: str):
    if _resolve_case(case_id) is None:
        return jsonify({"error": "not found"}), 404
    return jsonify({"parties": [_party_payload(p)
                                for p in storage.list_parties_in_case(case_id)]})


@app.post("/api/cases/<case_id>/parties")
@login_required_api
def api_add_party(case_id: str):
    """Manually register a party on this case. Returns null when the party
    is a duplicate (already on the case) or shorter than 2 chars — both
    are no-ops, not errors, so callers can fire-and-forget on every save."""
    firm = request.firm  # type: ignore[attr-defined]
    if firm is None:
        return jsonify({"error": "no active firm"}), 400
    case = _resolve_case(case_id)
    if case is None:
        return jsonify({"error": "not found"}), 404
    data = request.get_json(force=True, silent=True) or {}
    name = (data.get("name") or "").strip()
    side = (data.get("side") or "unknown").strip()
    if side not in ("client", "opponent", "third", "unknown"):
        return jsonify({"error": f"invalid side: {side}"}), 400
    p = storage.add_case_party(case_id, firm.id, name, side=side, source="manual")
    if p is None:
        return jsonify({"party": None, "skipped": True}), 200
    return jsonify({"party": _party_payload(p)}), 201


@app.get("/api/cases/<case_id>/export")
@login_required_api
def api_export_case(case_id: str):
    """Download a case as JSON (full fidelity) or Markdown (human-readable).

    ?format=md — Markdown transcript with headings per message.
    default    — JSON with everything (articles, precedents, timestamps).
    """
    user = request.user  # type: ignore[attr-defined]
    case = _resolve_case(case_id)
    if not case:
        return jsonify({"error": "not found"}), 404
    messages = storage.list_messages(case_id)
    fmt = request.args.get("format", "json").lower()

    slug = "".join(c if c.isalnum() or c in "-_" else "_"
                   for c in case.title.lower())[:60] or "rast"

    if fmt == "md":
        buf = io.StringIO()
        buf.write(f"# {case.title}\n\n")
        buf.write("_Super Avvocato — eksport i bisedës_\n")
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

@app.get("/api/cases/<case_id>/conflicts")
@login_required_api
def api_case_conflicts(case_id: str):
    """Adverse conflict-of-interest check for a case (deontology)."""
    if _resolve_case(case_id) is None:
        return jsonify({"error": "case_not_found"}), 404
    firm = getattr(request, "firm", None)
    if firm is None:
        return jsonify({"parties": [], "conflicts": [], "related": [],
                        "has_conflict": False, "no_firm": True})
    try:
        if not storage.list_parties_in_case(case_id):
            _ensure_loaded()
            text = _build_precedent_description(case_id, "")
            conflicts_mod.maybe_extract(_BRAIN, case_id, firm.id, text)
    except Exception as exc:  # noqa: BLE001
        log.warning("conflict pre-extract failed: %s", exc)
    return jsonify(conflicts_mod.check(case_id, firm.id))


@app.post("/api/cases/<case_id>/vault")
@login_required_api
def api_vault_ask(case_id: str):
    """Vault — answer a question grounded in ALL documents of the case."""
    if _resolve_case(case_id) is None:
        return jsonify({"error": "case_not_found"}), 404
    _ensure_loaded()
    if _BRAIN is None:
        return jsonify({"error": "brain_unavailable"}), 503
    body = request.get_json(silent=True) or {}
    q = (body.get("question") or "").strip()
    if not q:
        return jsonify({"error": "question_required"}), 400
    result = vault_mod.ask(_BRAIN, case_id, q)
    if result.get("empty"):
        return jsonify({
            "answer": "Nuk ka dokumente të gatshme në këtë dosje. "
                      "Ngarko dokumente më parë (📎).",
            "docs_used": [], "n_docs": 0,
        })
    return jsonify(result)


@app.post("/api/cases/<case_id>/who-said")
@login_required_api
def api_who_said(case_id: str):
    """Fashikulli intelligjent — who said what across the case documents."""
    if _resolve_case(case_id) is None:
        return jsonify({"error": "case_not_found"}), 404
    _ensure_loaded()
    if _BRAIN is None:
        return jsonify({"error": "brain_unavailable"}), 503
    try:
        res = vault_mod.who_said_what(_BRAIN.backend, case_id)
    except Exception as exc:  # noqa: BLE001
        log.exception("who-said failed")
        return jsonify({"error": _safe_err(exc)}), 200
    if res.get("empty"):
        return jsonify({"markdown": "Nuk ka dokumente të gatshme në këtë dosje. "
                                    "Ngarko dokumente më parë (📎).", "n_docs": 0})
    md = res.get("markdown") or ""
    cits = {"items": [], "stats": {}}
    try:
        if md and _INDEX is not None:
            cits = cv_mod.verify_text(md, _req_index())
    except Exception:  # noqa: BLE001
        pass
    res["citations"] = cits
    return jsonify(res)


@app.get("/api/cases/<case_id>/documents")
@login_required_api
def api_list_documents(case_id: str):
    user = request.user  # type: ignore[attr-defined]
    if _resolve_case(case_id) is None:
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
    case = _resolve_case(case_id)
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

    # salvataggio a flusso: i documenti passano ancora dalla memoria (sono
    # piccoli e cosi' un file non valido non tocca mai il disco), i VIDEO no —
    # 500 MB in RAM per ogni caricamento in corso metterebbero in ginocchio la
    # macchina, e con lei gli altri cinque siti che ci girano.
    from .config import VIDEO_EXTENSIONS as _VIDEO_EXT
    _ext_dichiarata = Path(f.filename).suffix.lower()

    if _ext_dichiarata in _VIDEO_EXT:
        # Content-Length e' una DICHIARAZIONE del client: serve a rifiutare
        # subito l'assurdo, non a fidarsi. La verifica vera e' dopo la scrittura.
        dichiarato = request.content_length or 0
        pre = docs_mod.validate_upload(f.filename, dichiarato or 1)
        if not pre.ok:
            return jsonify({"error": pre.error}), 400
        storage_path = docs_mod.storage_path_for(case_id, pre.ext)
        try:
            f.save(str(storage_path))          # a pezzi, non in memoria
        except OSError as exc:
            log.exception("scrittura video fallita")
            return jsonify({"error": f"nuk u ruajt: {exc}"}), 500
        reale = storage_path.stat().st_size
        v = docs_mod.validate_upload(f.filename, reale)
        if not v.ok:
            # dimensione vera diversa da quella dichiarata: si cancella,
            # altrimenti bastano richieste che mentono per riempire il disco
            storage_path.unlink(missing_ok=True)
            return jsonify({"error": v.error}), 400
        dimensione = reale
    else:
        # Read file into memory for validation; upload limit (25MB default) makes
        # this safe and saves a useless partial write on invalid uploads.
        content = f.read()
        v = docs_mod.validate_upload(f.filename, len(content))
        if not v.ok:
            return jsonify({"error": v.error}), 400
        storage_path = docs_mod.storage_path_for(case_id, v.ext)
        storage_path.write_bytes(content)
        dimensione = len(content)

    doc = storage.create_document(
        case_id=case_id,
        filename=f.filename,
        ext=v.ext,
        mimetype=v.mimetype,
        size_bytes=dimensione,
        storage_path=str(storage_path),
    )

    # Estrazione + analisi girano IN SOTTOFONDO: tenere aperta la richiesta
    # costava 30-65 secondi per file (OCR delle foto + classificazione), e
    # l'avvocato concludeva che il caricamento non funzionasse. La riga
    # esiste gia' con stato 'pending', quindi il documento compare subito e
    # passa da solo a 'e analizuar'.
    backend = _BRAIN.backend if _BRAIN else None
    doc_id, fname, ext, mime = doc.id, f.filename, v.ext, v.mimetype
    # la giurisdizione vive in una threading.local: va passata a mano, o il
    # thread ricade su AL e classifica in albanese un documento italiano
    juris = _active_jurisdiction(user)
    uid = user.id

    def _process() -> None:
        try:
            brain_mod.set_request_jurisdiction(juris)
        except Exception:  # noqa: BLE001
            pass
        try:
            text, _ocr = docs_mod.extract_text(storage_path, ext, mime,
                                               backend=backend,
                                               original_filename=fname)
        except Exception as exc:  # noqa: BLE001
            log.exception("extraction failed for %s", fname)
            storage.mark_document_error(doc_id, f"{type(exc).__name__}: {exc}")
            return
        analysis = {"doc_type": None, "summary": None, "key_facts": []}
        if text and backend is not None:
            try:
                analysis = docs_mod.summarize_document(text, fname, backend)
            except Exception as exc:  # noqa: BLE001
                log.warning("analysis failed for %s: %s", fname, exc)
        try:
            storage.update_document_analysis(
                doc_id,
                extracted_text=text or None,
                doc_type=analysis.get("doc_type"),
                summary=analysis.get("summary"),
                key_facts=analysis.get("key_facts") or [],
            )
            storage.touch_case(case_id, uid)
        except Exception:  # noqa: BLE001
            log.exception("could not store analysis for %s", fname)

    threading.Thread(target=brain_mod.porta_utente(uid, _process),
                 name=f"doc-{doc_id[:8]}", daemon=True).start()

    payload = _document_payload(storage.get_document(doc_id, case_id))
    payload["processing"] = True
    return jsonify(payload), 201


@app.get("/api/cases/<case_id>/videos")
@login_required_api
def api_case_videos(case_id: str):
    """I video del fascicolo, con lo stato della loro analisi.

    Serve al pannello per sapere cosa c'e' gia' dentro: un video di
    sorveglianza si carica una volta e si riguarda per settimane.
    """
    case = _resolve_case(case_id)
    if case is None:
        return jsonify({"error": "not found"}), 404
    # audio e video insieme: sono la stessa prova vista da due lati, e
    # separarli costringerebbe l'avvocato a ricordare dove ha messo cosa
    from .config import VIDEO_EXTENSIONS as _VE, AUDIO_EXTENSIONS as _AE
    fuori = []
    for d in storage.list_documents(case_id):
        _e = (getattr(d, "ext", "") or "").lower()
        if _e not in _VE and _e not in _AE:
            continue
        testo = getattr(d, "extracted_text", None) or ""
        fuori.append({
            "id": d.id,
            "filename": d.filename,
            "ext": d.ext,
            "size_mb": round((getattr(d, "size_bytes", 0) or 0) / 1048576, 1),
            "kind": "audio" if _e in _AE else "video",
            "status": getattr(d, "status", ""),
            "error": getattr(d, "error", None),
            "analysis": testo,
            "has_analysis": bool(testo),
        })
    return jsonify({"videos": fuori, "count": len(fuori)})


@app.post("/api/cases/<case_id>/video/compare")
@login_required_api
def api_video_compare(case_id: str):
    """Il video contro le carte: conferme, discordanze, silenzi.

    E' la parte che vale. La descrizione dei fotogrammi da sola dice cosa si
    vede; questa dice **dove il verbale e il video non tornano**, che e' la
    crepa su cui si lavora.
    """
    case = _resolve_case(case_id)
    if case is None:
        return jsonify({"error": "not found"}), 404
    if _BRAIN is None:
        return jsonify({"error": "brain unavailable"}), 503

    body = request.get_json(silent=True) or {}
    voluti = set(body.get("doc_ids") or [])

    from .config import VIDEO_EXTENSIONS as _VE, AUDIO_EXTENSIONS as _AE
    testi_video, altri = [], []
    for d in storage.list_documents(case_id):
        testo = getattr(d, "extracted_text", None) or ""
        if not testo:
            continue
        if (getattr(d, "ext", "") or "").lower() in (_VE | _AE):
            if not voluti or d.id in voluti:
                testi_video.append(f"### {d.filename}\n\n{testo}")
        else:
            altri.append(f"### {d.filename}\n\n{testo[:6000]}")

    if not testi_video:
        return jsonify({
            "error": "asnjë provë video ose audio e analizuar në fashikull"
        }), 400

    juris = _active_jurisdiction(request.user)  # type: ignore[attr-defined]
    lingua = "it" if str(juris).upper() == "IT" else "sq"
    try:
        out = video_mod.confronta(
            testi_video, "\n\n".join(altri), _BRAIN.backend,
            lingua=lingua, case_id=case_id,
        )
    except Exception as exc:  # noqa: BLE001
        log.exception("confronto video fallito")
        return jsonify({"error": f"{type(exc).__name__}: {exc}"}), 500

    # Lo scudo delle citazioni vale anche qui: il confronto puo' citare nene
    # e sentenze, e non deve essere l'unico percorso senza verifica.
    # ⚠️ Le citazioni si CALCOLANO e si passano: lo scudo non le deduce.
    citations = {"items": [], "stats": {}}
    try:
        if _INDEX is not None and out:
            citations = cv_mod.verify_text(out, _req_index())
        out = _scudo_citazioni(out, citations)
    except Exception:  # noqa: BLE001
        log.exception("scudo citazioni sul confronto video")
    return jsonify({"result": out, "citations": citations,
                    "n_video": len(testi_video), "n_docs": len(altri)})


@app.delete("/api/cases/<case_id>/documents/<doc_id>")
@login_required_api
def api_delete_document(case_id: str, doc_id: str):
    user = request.user  # type: ignore[attr-defined]
    if _resolve_case(case_id) is None:
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
    if _resolve_case(case_id) is None:
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
@require_module("avokat", "prokuror")
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
    case = _resolve_case(case_id)
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
        hits = _req_index().search(message, top_k=10)
        articles = [_article_payload(a, s) for a, s in hits]
        text = ("⚠️ Motori AI nuk është i disponueshëm për momentin. "
                "Po tregoj vetëm nenet që u gjetën për pyetjen tënde.")
        storage.add_message(case.id, "assistant", text,
                            kind="retrieval_only", articles=articles)
        return jsonify({"kind": "retrieval_only", "text": text,
                        "articles": articles, "triage": None,
                        "precedents": [], "case_id": case.id})

    try:
        result = _BRAIN.answer(message, history=history,
                               session_id=case.claude_session_id,
                               documents=case_docs,
                               jurisdiction=getattr(case, "jurisdiction", "AL"))
    except Exception as exc:
        log.exception("brain failure")
        err_text = html.escape(_safe_err(exc))
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

    try:
        created = _autopopulate_events_from_result(user.id, case.id, result)
        if created:
            log.info("case %s: auto-populated %d calendar events", case.id, created)
    except Exception as exc:
        log.warning("autopopulate events failed (non-fatal): %s", exc)

    retrieved_codes = {a.code for a, _ in result.retrieved}
    citations_payload = cv_mod.verify_text(
        result.text or "", _req_index(), retrieved_codes=retrieved_codes,
    )

    # V8.11 Citation Shield V2 — refusal preamble when all citations are
    # fabricated, fake-citation inline annotation, provenance pack.
    refused = cs_mod.should_refuse(citations_payload)
    answer_text = result.text or ""
    if refused:
        answer_text = cs_mod.apply_refusal(answer_text, jurisdiction="AL")
    if citations_payload.get("stats", {}).get("fake", 0) > 0:
        answer_text = cs_mod.annotate_fake_citations(answer_text, citations_payload)
    try:
        decision_citations = dv_mod.verify_decisions(
            answer_text, _BRAIN.kb if _BRAIN is not None else None)
    except Exception as exc:  # noqa: BLE001
        log.warning("decision verify failed (non-fatal): %s", exc)
        decision_citations = {"items": [], "stats": {"verified": 0, "unverified": 0, "total": 0}}

    provenance = cs_mod.build_provenance_pack(
        response_text=answer_text,
        user_message=message,
        citations_payload=citations_payload,
        retrieved_articles=result.retrieved,
        retrieved_precedents=result.precedents,
        model=CLAUDE_MODEL,
        system_prompt_version=ANSWER_SYSTEM_VERSION,
        jurisdiction=getattr(case, "jurisdiction", "AL") or "AL",
        refused=refused,
    )
    try:
        storage.save_provenance(case.id, user.id, provenance.to_dict())
    except Exception as exc:
        log.warning("provenance save failed (non-fatal): %s", exc)

    return jsonify({
        "kind": result.kind,
        "text": answer_text,
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
        "citations": citations_payload,
        "decision_citations": decision_citations,
        "provenance": provenance.to_dict(),
        "case_id": case.id,
    })


# V7.7 — streaming variant of /api/ask.
# Emits text/event-stream so the web UI can render the answer token by
# token on fast-path queries (simple / short followup). Complex queries
# still run the full blocking pipeline and emit a single "final" event
# at the end — the UI just shows a spinner during that wait.
def _ask_prepare(user, data):
    """Build the SSE generator for one question.

    Returns `(generate, None)` when the request is good, `(None, (payload,
    status))` when it is not. Everything the generator will need is captured
    here, inside the request context: it has to be able to run later in a
    thread, where `request` no longer exists.
    """
    _ensure_loaded()
    message = (data.get("message") or "").strip()
    case_id = (data.get("case_id") or "").strip()
    if not message:
        return None, ({"error": "empty message"}, 400)
    if not case_id:
        return None, ({"error": "missing case_id"}, 400)
    case = _resolve_case(case_id)
    if case is None:
        return None, ({"error": "case not found"}, 404)

    if storage.invalidate_case_session_if_stale(
        case.id, user.id, ANSWER_SYSTEM_VERSION,
    ):
        log.info("case %s: dropped stale Claude session (version mismatch)", case.id)
        case.claude_session_id = None

    storage.add_message(case.id, "user", message)
    history = storage.conversation_history(case.id, MAX_CONVERSATION_TURNS)
    if history and history[-1]["role"] == "user":
        history = history[:-1]

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
        def nobrain():
            yield _sse_event({"type": "error",
                              "message": "Asnjë backend LLM nuk është i disponueshëm."})
            yield _sse_event({"type": "done"})
        return nobrain, None

    # `_req_index()` reads Flask's `request`, which does not exist inside a
    # thread. Take it now, while we are still in the request.
    _idx = _req_index()

    def generate():
        try:
            final_result = None
            for kind, payload in _BRAIN.answer_stream(
                message, history=history,
                session_id=case.claude_session_id,
                documents=case_docs,
                jurisdiction=getattr(case, "jurisdiction", "AL"),
            ):
                if kind == "status":
                    yield _sse_event({"type": "status", "text": str(payload)})
                elif kind == "delta":
                    yield _sse_event({"type": "delta", "text": str(payload)})
                elif kind == "final":
                    final_result = payload
                elif kind == "error":
                    yield _sse_event({"type": "error", "message": str(payload)})

            if final_result is None:
                yield _sse_event({"type": "error",
                                  "message": "Stream ended without a final answer."})
                yield _sse_event({"type": "done"})
                return

            result = final_result
            # Persist + serialize identically to /api/ask so the UI can
            # reuse the same rendering code for articles/precedents etc.
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
                                kind=result.kind, articles=articles,
                                precedents=precedents,
                                timeline=timeline_payload,
                                comparison=comparison_payload,
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
                storage.set_case_answer_system_version(
                    case.id, user.id, ANSWER_SYSTEM_VERSION,
                )
            if case.title in ("Rast i ri", "Rast pa titull"):
                auto_title = message[:60].strip()
                if auto_title:
                    storage.rename_case(case.id, user.id, auto_title)

            try:
                created = _autopopulate_events_from_result(user.id, case.id, result)
                if created:
                    log.info("case %s: auto-populated %d calendar events (stream)",
                             case.id, created)
            except Exception as exc:
                log.warning("autopopulate events failed (stream): %s", exc)

            retrieved_codes = {a.code for a, _ in result.retrieved}
            citations_payload = cv_mod.verify_text(
                result.text or "", _idx, retrieved_codes=retrieved_codes,
            )

            # V8.11 Citation Shield V2 — same logic as the blocking path
            refused = cs_mod.should_refuse(citations_payload)
            answer_text = result.text or ""
            if refused:
                answer_text = cs_mod.apply_refusal(answer_text, jurisdiction="AL")
            if citations_payload.get("stats", {}).get("fake", 0) > 0:
                answer_text = cs_mod.annotate_fake_citations(answer_text, citations_payload)
            # ── e i VENDIME ────────────────────────────────────────────
            #
            # Questo percorso — la chat, quello che l'avvocato usa tutto il
            # giorno — NON passa da `_scudo_citazioni`: ha una copia sua dello
            # scudo, scritta prima e mai unificata. Agganciare li' il
            # verificatore delle sentenze copriva i diciannove strumenti e
            # lasciava scoperta proprio la risposta principale.
            # Misurato: 13 citazioni di sentenze, 7 non confermabili, e nel
            # testo nessun avviso.
            try:
                _idx_dec = _decisions_index()
                if _idx_dec is not None:
                    cases_payload = ccv_mod.verify_cases(answer_text, _idx_dec)
                    if (cases_payload.get("stats") or {}).get("unverified"):
                        answer_text = ccv_mod.annotate_unverified(
                            answer_text, cases_payload,
                            jurisdiction=getattr(case, "jurisdiction", "AL") or "AL")
            except Exception:  # noqa: BLE001
                log.debug("case citation shield skipped (stream)", exc_info=True)
            provenance = cs_mod.build_provenance_pack(
                response_text=answer_text,
                user_message=message,
                citations_payload=citations_payload,
                retrieved_articles=result.retrieved,
                retrieved_precedents=result.precedents,
                model=CLAUDE_MODEL,
                system_prompt_version=ANSWER_SYSTEM_VERSION,
                jurisdiction=getattr(case, "jurisdiction", "AL") or "AL",
                refused=refused,
            )
            try:
                storage.save_provenance(case.id, user.id, provenance.to_dict())
            except Exception as exc:
                log.warning("provenance save failed stream (non-fatal): %s", exc)

            yield _sse_event({
                "type": "final",
                "kind": result.kind,
                "text": answer_text,
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
                "citations": citations_payload,
                "provenance": provenance.to_dict(),
                "case_id": case.id,
            })
        except Exception as exc:
            log.exception("stream failure")
            err_text = html.escape(_safe_err(exc))
            try:
                storage.add_message(case.id, "assistant", err_text, kind="error")
            except Exception:
                pass
            yield _sse_event({"type": "error", "message": err_text})
        finally:
            yield _sse_event({"type": "done"})

    return generate, None


_SSE_HEADERS = {
    "X-Accel-Buffering": "no",      # nginx must not buffer an event stream
    "Cache-Control": "no-cache",
    "Connection": "keep-alive",
}


@app.post("/api/ask/stream")
@login_required_api
@require_module("avokat", "prokuror")
def api_ask_stream():
    """Legacy path: the brain streams straight into this connection.

    Kept working on purpose. If anything about the job path misbehaves, the
    client can fall back to this without waiting for a deploy.
    """
    gen, err = _ask_prepare(request.user,  # type: ignore[attr-defined]
                            request.get_json(force=True, silent=True) or {})
    if err is not None:
        payload, status = err
        return jsonify(payload), status
    return Response(stream_with_context(gen()),
                    mimetype="text/event-stream", headers=_SSE_HEADERS)


@app.post("/api/ask/start")
@login_required_api
@require_module("avokat", "prokuror")
def api_ask_start():
    """Run the answer in the background; hand back a job id at once.

    This is what makes the answer survive the page. The connection that
    started the work is free to die a second later — on a phone it usually
    does — and the brain keeps going.
    """
    user = request.user  # type: ignore[attr-defined]
    data = request.get_json(force=True, silent=True) or {}
    gen, err = _ask_prepare(user, data)
    if err is not None:
        payload, status = err
        return jsonify(payload), status

    job_id = jobs_mod.create(user.id, (data.get("case_id") or "").strip())
    _uid = user.id                                   # catturati qui: dentro
    _cid = (data.get("case_id") or "").strip()       # il thread non c'e' request

    def _run():
        try:
            for frame in gen():
                jobs_mod.push(job_id, frame)
        except Exception as exc:  # noqa: BLE001
            log.exception("ask job %s failed", job_id)
            jobs_mod.push(job_id, _sse_event(
                {"type": "error", "message": html.escape(_safe_err(exc))}))
            jobs_mod.push(job_id, _sse_event({"type": "done"}))
        finally:
            jobs_mod.finish(job_id)
            # L'unico punto in cui le notifiche toccano il percorso di una
            # risposta, e non puo' fare danni: se qui esplode qualcosa, la
            # risposta e' gia' salvata e l'utente la trova comunque.
            try:
                push_mod.avvisa(
                    storage, _uid,
                    "Përgjigjja është gati",
                    "Analiza jote ka përfunduar. Hape për ta lexuar.",
                    url="/", tag="ask-%s" % _cid[:8],
                )
            except Exception:  # noqa: BLE001
                log.debug("push notify skipped", exc_info=True)

    # ── Il battito ────────────────────────────────────────────────────
    #
    # Le fasi lavorano in silenzio per minuti: su un fascicolo grosso, piu'
    # di quindici. Senza un segno di vita l'avvocato non sa se aspettare o
    # rinunciare — e rinuncia, che e' il caso peggiore perche' il lavoro sta
    # andando bene.
    #
    # ⚠️ Spinto nel LAVORO, non inventato dal lettore: il client conta i
    # fotogrammi per sapere da dove riprendere dopo una caduta, e un
    # fotogramma che esiste solo per un lettore gli sfaserebbe il conto.
    def _battito():
        partenza = time.time()
        # ⚠️ Tetto duro. `jobs.py` ripulisce i lavori scaduti solo dentro
        # `create()`: se nessuno fa piu' domande la pulizia non gira, e senza
        # questo limite il battito continuerebbe per sempre su un lavoro
        # morto. Allineato a KEEP_RUNNING_S: oltre le due ore il lavoro
        # verrebbe buttato comunque.
        _TETTO_BATTITO = 2 * 60 * 60
        while time.time() - partenza < _TETTO_BATTITO:
            time.sleep(60)
            lavoro = jobs_mod.get(job_id)
            if lavoro is None or lavoro.done:
                return
            minuti = int((time.time() - partenza) / 60)
            jobs_mod.push(job_id, _sse_event({
                "type": "status",
                "text": "Po punoj ende — %d min. Analiza vazhdon edhe nëse "
                        "e mbyll faqen." % minuti,
                "text_it": "Sto ancora lavorando — %d min. L'analisi "
                           "continua anche se chiudi la pagina." % minuti,
            }))

    threading.Thread(target=brain_mod.porta_utente(_uid, _run),
                     name="ask-%s" % job_id[:8], daemon=True).start()
    threading.Thread(target=_battito, name="batt-%s" % job_id[:8],
                     daemon=True).start()
    return jsonify({"job_id": job_id})


@app.get("/api/ask/alive")
@login_required_api
def api_ask_alive():
    """Il lavoro esiste ancora e sta lavorando?

    Serve al client come ultima verifica prima di dichiarare perso il lavoro
    di mezz'ora. Risponde solo al proprietario: lo stato di un lavoro dice
    che quell'utente ha una causa in analisi, ed e' gia' un'informazione.
    """
    job_id = (request.args.get("job") or "").strip()
    lavoro = jobs_mod.get(job_id) if job_id else None
    if lavoro is None or lavoro.user_id != request.user.id:  # type: ignore[attr-defined]
        return jsonify({"alive": False})
    return jsonify({"alive": not lavoro.done})


@app.get("/api/ask/events")
@login_required_api
def api_ask_events():
    """Replay a job's frames from `from`, then follow the live ones.

    Idempotent by design: asking twice from the same index gives the same
    frames. That is what lets a client reconnect without the server having to
    remember anything about the connection that died.
    """
    job_id = (request.args.get("job") or "").strip()
    try:
        since = max(0, int(request.args.get("from") or 0))
    except (TypeError, ValueError):
        since = 0

    job = jobs_mod.get(job_id)
    if job is None:
        return jsonify({"error": "job not found"}), 404
    if job.user_id != request.user.id:  # type: ignore[attr-defined]
        return jsonify({"error": "forbidden"}), 403

    def follow():
        i = since
        quiet = 0
        while True:
            frames, done, i = jobs_mod.slice_from(job_id, i)
            for f in frames:
                yield f
            if frames:
                quiet = 0
                continue
            if done:
                break
            # An SSE comment: the client ignores it, but it stops nginx and
            # the phone's radio from concluding the connection is dead.
            yield ": ping\n\n"
            quiet += 1
            # ⚠️ NON si dichiara finito cio' che e' vivo.
            #
            # Qui prima c'era «dopo 900 secondi di silenzio: errore + done».
            # Quel `done` era una bugia — il lavoro stava lavorando — e il
            # client, che e' costruito per riattaccarsi da solo quando la
            # connessione cade, smetteva proprio perche' il server gli aveva
            # detto che era finita. Un caso vero: 14 fasi riuscite, 32 minuti
            # di analisi su un omicidio, e l'avvocato ha letto «Timeout».
            #
            # Le fasi tacciono a lungo quando il fascicolo e' grosso (una ha
            # lavorato con 789.203 token). Il silenzio non dice niente sul
            # fatto che il lavoro sia vivo: quello lo dice il registro dei
            # lavori, e si guarda quello.
            if quiet % 30 == 0:
                vivo = jobs_mod.get(job_id)
                if vivo is None:
                    # Sparito davvero: riavvio del server, o le due ore di
                    # KEEP_RUNNING_S. Si dice la verita', non «timeout».
                    yield _sse_event({
                        "type": "error",
                        "message": "Puna u ndërpre në server (rinisje). "
                                   "Pyetja nuk u humb — dërgoje sërish.",
                        "message_it": "Il lavoro si è interrotto sul server "
                                      "(riavvio). La domanda non è persa — "
                                      "rimandala.",
                    })
                    yield _sse_event({"type": "done"})
                    break
            time.sleep(1)

    return Response(stream_with_context(follow()),
                    mimetype="text/event-stream", headers=_SSE_HEADERS)


def _sse_event(payload: dict) -> str:
    """Format a dict as one SSE 'data: ...' frame."""
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


# ── calendar / events (V7.10) ──────────────────────────────────────────────

def _event_payload(ev, case_title: str | None = None,
                   reminders: list | None = None) -> dict:
    color = ev.color or storage.EVENT_DEFAULT_COLORS.get(ev.kind)
    return {
        "id": ev.id,
        "user_id": ev.user_id,
        "case_id": ev.case_id,
        "case_title": case_title,
        "title": ev.title,
        "description": ev.description,
        "kind": ev.kind,
        "starts_at": ev.starts_at,
        "ends_at": ev.ends_at,
        "all_day": ev.all_day,
        "location": ev.location,
        "color": color,
        "source": ev.source,
        "source_ref": ev.source_ref,
        "done": ev.done,
        "reminders": [
            {"id": r.id, "offset_minutes": r.offset_minutes,
             "channel": r.channel, "fire_at": r.fire_at,
             "sent_at": r.sent_at}
            for r in (reminders or [])
        ],
        "created_at": ev.created_at,
        "updated_at": ev.updated_at,
    }


def _parse_reminders(raw) -> list[int]:
    """Accept a list of ints, strings, or {"offset_minutes": N}; return
    sanitised minute offsets."""
    if not isinstance(raw, list):
        return []
    out: list[int] = []
    for x in raw:
        if isinstance(x, dict):
            x = x.get("offset_minutes")
        try:
            n = int(x)
        except (TypeError, ValueError):
            continue
        if n > 0 and n <= 60 * 24 * 30:  # cap at 30 days out
            out.append(n)
    return out


_ISO_DATE_RE = re.compile(r"(\d{4}-\d{2}-\d{2})")


def _autopopulate_events_from_result(
    user_id: int, case_id: str, result,
) -> int:
    """Derive events from timeline deadlines + critical urgency signals.

    Dedup key is `source_ref` so re-running the same analysis doesn't
    create duplicate rows. If the extracted date has slipped (answer()
    ran again after the user updated facts), update the existing event's
    start time instead of minting a new one. Returns count of events
    created or updated.
    """
    n = 0
    try:
        timeline = getattr(result, "timeline", None)
        deadlines = list(getattr(timeline, "deadlines", []) or [])
        for idx, d in enumerate(deadlines):
            due = (d.due_date or "").strip()
            if not due:
                continue
            m = _ISO_DATE_RE.match(due)
            if not m:
                continue
            # Default to 09:00 local — deadlines rarely include a time,
            # and 09:00 gives the lawyer a full workday to act.
            starts_at = f"{m.group(1)}T09:00:00+00:00"
            try:
                dt = datetime.fromisoformat(starts_at.replace("Z", "+00:00"))
                starts_iso = dt.astimezone(UTC).isoformat().replace("+00:00", "Z")
            except Exception:
                continue
            source_ref = f"case:{case_id}:timeline:{idx}"
            title = (d.action or "Afat ligjor")[:180]
            description_lines = []
            if d.article_ref:
                description_lines.append(f"Neni: {d.article_ref}")
            if d.anchor_event:
                description_lines.append(f"Nga ngjarja: {d.anchor_event}")
            description = "\n".join(description_lines) or None
            urgency = d.urgency or "unknown"
            reminders_offsets = [2880, 1440] if urgency in {"critical", "high"} else [1440]
            _upsert_autoevent(
                user_id=user_id, case_id=case_id, source_ref=source_ref,
                title=title, kind="afat", starts_at=starts_iso,
                description=description, reminders=reminders_offsets,
            )
            n += 1
    except Exception as exc:
        log.warning("timeline autopopulate failed: %s", exc)

    try:
        urgency_radar = getattr(result, "urgency_radar", None)
        signals = list(getattr(urgency_radar, "signals", []) or [])
        for idx, s in enumerate(signals):
            if s.severity not in {"critical", "elevated"}:
                continue
            raw = (s.deadline or "").strip()
            if not raw:
                continue
            m = _ISO_DATE_RE.search(raw)
            if not m:
                continue
            starts_at = f"{m.group(1)}T09:00:00+00:00"
            try:
                dt = datetime.fromisoformat(starts_at.replace("Z", "+00:00"))
                starts_iso = dt.astimezone(UTC).isoformat().replace("+00:00", "Z")
            except Exception:
                continue
            source_ref = f"case:{case_id}:urgency:{idx}"
            title = (s.label or s.action or "Veprim urgjent")[:180]
            desc = s.reason or s.action or None
            _upsert_autoevent(
                user_id=user_id, case_id=case_id, source_ref=source_ref,
                title=title, kind="afat", starts_at=starts_iso,
                description=desc, reminders=[2880, 1440, 180],
            )
            n += 1
    except Exception as exc:
        log.warning("urgency autopopulate failed: %s", exc)

    return n


def _upsert_autoevent(
    *, user_id: int, case_id: str, source_ref: str, title: str,
    kind: str, starts_at: str, description: str | None,
    reminders: list[int],
) -> None:
    existing = storage.event_by_source_ref(user_id, source_ref)
    if existing:
        # If the date shifted (e.g. the LLM reinterpreted the anchor),
        # push the update through — this also recomputes fire_at for
        # pending reminders. If title/desc changed keep them fresh too.
        changed = {}
        if existing.starts_at != starts_at:
            changed["starts_at"] = starts_at
        if existing.title != title:
            changed["title"] = title
        if (existing.description or None) != (description or None):
            changed["description"] = description
        if changed:
            storage.update_event(existing.id, user_id, **changed)
        return
    storage.create_event(
        user_id=user_id, title=title, kind=kind, starts_at=starts_at,
        case_id=case_id, description=description,
        source="auto", source_ref=source_ref, reminders=reminders,
    )


@app.get("/api/events")
@login_required_api
def api_list_events():
    user = request.user  # type: ignore[attr-defined]
    start = request.args.get("start") or None
    end = request.args.get("end") or None
    case_id = request.args.get("case_id") or None
    events = storage.list_events(user.id, start=start, end=end, case_id=case_id)
    # Batch-fetch case titles so a month view with 30 events doesn't do 30
    # separate lookups.
    case_ids = {e.case_id for e in events if e.case_id}
    titles: dict[str, str] = {}
    if case_ids:
        for cid in case_ids:
            c = _resolve_case(cid)
            if c:
                titles[cid] = c.title
    payload = []
    for e in events:
        payload.append(_event_payload(
            e,
            case_title=titles.get(e.case_id) if e.case_id else None,
            reminders=storage.list_reminders_for_event(e.id),
        ))
    return jsonify({"events": payload})


@app.get("/api/agenda/upcoming")
@login_required_api
def api_agenda_upcoming():
    """Deadline safety-net: overdue + upcoming (not-done) events."""
    from datetime import datetime, timedelta, UTC
    user = request.user  # type: ignore[attr-defined]
    try:
        days = int(request.args.get("days") or 7)
    except (TypeError, ValueError):
        days = 7
    days = max(1, min(days, 60))
    now = datetime.now(UTC)
    back = (now - timedelta(days=30)).isoformat().replace("+00:00", "Z")
    ahead = (now + timedelta(days=days)).isoformat().replace("+00:00", "Z")
    events = storage.list_events(user.id, start=back, end=ahead)

    def _parse(v):
        try:
            return datetime.fromisoformat((v or "").replace("Z", "+00:00"))
        except Exception:  # noqa: BLE001
            return None

    case_titles: dict = {}
    overdue, upcoming = [], []
    for e in events:
        if e.done:
            continue
        ct = None
        if e.case_id:
            if e.case_id not in case_titles:
                c = _resolve_case(e.case_id)
                case_titles[e.case_id] = c.title if c else None
            ct = case_titles[e.case_id]
        dt = _parse(e.starts_at)
        item = {"id": e.id, "title": e.title, "kind": e.kind,
                "starts_at": e.starts_at, "location": e.location,
                "case_title": ct}
        if dt is not None and dt < now:
            item["days_overdue"] = (now - dt).days
            overdue.append(item)
        else:
            if dt is not None:
                item["days_until"] = (dt - now).days
            upcoming.append(item)
    today_n = sum(1 for it in upcoming if it.get("days_until") == 0)
    return jsonify({
        "overdue": overdue,
        "upcoming": upcoming,
        "counts": {"overdue": len(overdue), "upcoming": len(upcoming),
                   "today": today_n, "days": days},
    })


@app.get("/api/firm/calendar")
@login_required_api
def api_firm_calendar():
    """Master calendar — events tied to any case in the active firm.

    Visible only to roles with all_cases permission (owner/partner). Other
    members see their own events through /api/events as before.
    """
    firm = request.firm  # type: ignore[attr-defined]
    role = request.role  # type: ignore[attr-defined]
    if firm is None:
        return jsonify({"error": "no active firm"}), 400
    if not storage.ROLE_PERMISSIONS.get(role or "", {}).get("all_cases", False):
        return jsonify({"error": "forbidden",
                        "needed": "all_cases",
                        "your_role": role}), 403
    start = request.args.get("start") or None
    end = request.args.get("end") or None
    pairs = storage.list_events_for_firm(firm.id, start=start, end=end)
    case_ids = {e.case_id for e, _ in pairs if e.case_id}
    titles: dict[str, str] = {}
    for cid in case_ids:
        c = _resolve_case(cid)
        if c:
            titles[cid] = c.title
    payload = []
    for ev, creator in pairs:
        item = _event_payload(
            ev,
            case_title=titles.get(ev.case_id) if ev.case_id else None,
            reminders=storage.list_reminders_for_event(ev.id),
        )
        item["creator_username"] = creator
        payload.append(item)
    return jsonify({"events": payload, "firm": _firm_payload(firm)})


@app.post("/api/events")
@login_required_api
def api_create_event():
    user = request.user  # type: ignore[attr-defined]
    data = request.get_json(force=True, silent=True) or {}
    title = (data.get("title") or "").strip()
    kind = (data.get("kind") or "takim").strip()
    starts_at = (data.get("starts_at") or "").strip()
    if not title or not starts_at:
        return jsonify({"error": "title and starts_at required"}), 400
    if kind not in storage.EVENT_KINDS:
        return jsonify({"error": f"unknown kind {kind!r}"}), 400
    case_id = data.get("case_id") or None
    if case_id and not _resolve_case(case_id):
        return jsonify({"error": "case not found"}), 404
    try:
        ev = storage.create_event(
            user.id, title=title, kind=kind, starts_at=starts_at,
            case_id=case_id,
            description=data.get("description") or None,
            ends_at=data.get("ends_at") or None,
            all_day=bool(data.get("all_day")),
            location=(data.get("location") or None),
            color=(data.get("color") or None),
            reminders=_parse_reminders(data.get("reminders")),
        )
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    case_title = None
    if ev.case_id:
        c = _resolve_case(ev.case_id)
        case_title = c.title if c else None
    return jsonify(_event_payload(
        ev, case_title=case_title,
        reminders=storage.list_reminders_for_event(ev.id),
    ))


@app.patch("/api/events/<event_id>")
@login_required_api
def api_update_event(event_id: str):
    user = request.user  # type: ignore[attr-defined]
    data = request.get_json(force=True, silent=True) or {}
    patch = {k: v for k, v in data.items() if k in {
        "title", "description", "kind", "starts_at", "ends_at",
        "all_day", "location", "color", "done", "case_id",
    }}
    if "case_id" in patch and patch["case_id"]:
        if not _resolve_case(patch["case_id"]):
            return jsonify({"error": "case not found"}), 404
    try:
        ev = storage.update_event(event_id, user.id, **patch)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    if ev is None:
        return jsonify({"error": "not found"}), 404
    # Replace reminders if the caller sent an explicit list.
    if "reminders" in data:
        storage.replace_reminders(
            ev.id, _parse_reminders(data["reminders"]), ev.starts_at)
    case_title = None
    if ev.case_id:
        c = _resolve_case(ev.case_id)
        case_title = c.title if c else None
    return jsonify(_event_payload(
        ev, case_title=case_title,
        reminders=storage.list_reminders_for_event(ev.id),
    ))


@app.delete("/api/events/<event_id>")
@login_required_api
def api_delete_event(event_id: str):
    user = request.user  # type: ignore[attr-defined]
    if not storage.delete_event(event_id, user.id):
        return jsonify({"error": "not found"}), 404
    return jsonify({"ok": True})


@app.get("/api/calendar/ical-url")
@login_required_api
def api_ical_url():
    user = request.user  # type: ignore[attr-defined]
    token = storage.ensure_ical_token(user.id)
    return jsonify({
        "url": url_for("api_ical_feed", token=token, _external=True),
        "token": token,
    })


@app.get("/api/settings/telegram")
@login_required_api
def api_settings_telegram_get():
    user = request.user  # type: ignore[attr-defined]
    chat_id = storage.get_user_telegram_chat(user.id)
    return jsonify({"chat_id": chat_id, "linked": bool(chat_id)})


@app.post("/api/settings/telegram")
@login_required_api
def api_settings_telegram_set():
    user = request.user  # type: ignore[attr-defined]
    data = request.get_json(silent=True) or {}
    raw = (data.get("chat_id") or "").strip()
    if raw and not re.fullmatch(r"-?\d{1,20}", raw):
        return jsonify({"error": "chat_id duhet të jetë numër"}), 400
    storage.set_user_telegram_chat(user.id, raw or None)
    return jsonify({"linked": bool(raw)})


@app.get("/api/settings/whatsapp")
@login_required_api
def api_settings_whatsapp_get():
    from .config import WHATSAPP_TOKEN, WHATSAPP_PHONE_NUMBER_ID, WHATSAPP_TEMPLATE_NAME
    user = request.user  # type: ignore[attr-defined]
    phone = storage.get_user_whatsapp(user.id)
    backend_ready = bool(WHATSAPP_TOKEN and WHATSAPP_PHONE_NUMBER_ID and WHATSAPP_TEMPLATE_NAME)
    return jsonify({"phone": phone, "linked": bool(phone), "backend_ready": backend_ready})


@app.post("/api/settings/whatsapp")
@login_required_api
def api_settings_whatsapp_set():
    user = request.user  # type: ignore[attr-defined]
    data = request.get_json(silent=True) or {}
    raw = (data.get("phone") or "").strip()
    digits = re.sub(r"[^\d]", "", raw)
    if raw and not (6 <= len(digits) <= 15):
        return jsonify({"error": "Numri i WhatsApp duhet 6–15 shifra (me prefiks shteti, p.sh. 3556…)"}), 400
    storage.set_user_whatsapp(user.id, digits or None)
    return jsonify({"linked": bool(digits), "phone": digits or None})


@app.get("/api/settings/reminder-email")
@login_required_api
def api_settings_reminder_email_get():
    from .config import RESEND_API_KEY, REMINDER_EMAIL_FROM
    user = request.user  # type: ignore[attr-defined]
    email = storage.get_user_reminder_email(user.id)
    uname = getattr(user, "username", "") or ""
    suggestion = uname if ("@" in uname and "." in uname) else None
    backend_ready = bool(RESEND_API_KEY and REMINDER_EMAIL_FROM)
    return jsonify({"email": email, "linked": bool(email),
                    "suggestion": suggestion, "backend_ready": backend_ready})


@app.post("/api/settings/reminder-email")
@login_required_api
def api_settings_reminder_email_set():
    user = request.user  # type: ignore[attr-defined]
    data = request.get_json(silent=True) or {}
    raw = (data.get("email") or "").strip()
    if raw and not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", raw):
        return jsonify({"error": "Email e pavlefshme"}), 400
    storage.set_user_reminder_email(user.id, raw or None)
    return jsonify({"linked": bool(raw), "email": raw or None})


@app.get("/api/calendar/ical/<token>.ics")
def api_ical_feed(token: str):
    """Public iCal feed — auth is the token itself, so users can paste the
    URL into Google Calendar / Apple Calendar without logging in. Tokens
    are opaque 128-bit hex; they can be rotated by regenerating."""
    user = storage.get_user_by_ical_token(token)
    if user is None:
        return Response("not found", status=404, mimetype="text/plain")
    events = storage.list_events(user.id)
    body = _render_ical(user.username, events)
    return Response(body, mimetype="text/calendar; charset=utf-8")


def _render_ical(cal_name: str, events: list) -> str:
    """Render events as a minimal VCALENDAR feed.

    Timestamps are emitted in UTC (Z suffix). Google Calendar + Apple
    Calendar accept this directly. All-day events use VALUE=DATE.
    """
    from datetime import datetime as _dt
    def _fmt(ts: str, *, all_day: bool = False) -> str:
        s = ts.replace("Z", "+00:00")
        try:
            d = _dt.fromisoformat(s)
        except ValueError:
            return ts
        if all_day:
            return d.strftime("%Y%m%d")
        return d.strftime("%Y%m%dT%H%M%SZ")

    def _esc(s: str | None) -> str:
        if not s:
            return ""
        return (s.replace("\\", "\\\\").replace(",", "\\,")
                 .replace(";", "\\;").replace("\n", "\\n"))

    lines = [
        "BEGIN:VCALENDAR", "VERSION:2.0",
        "PRODID:-//Super Avvocato//Kalendari//SQ",
        f"X-WR-CALNAME:Super Avvocato — {cal_name}",
        "X-WR-TIMEZONE:Europe/Tirane",
    ]
    for ev in events:
        lines.append("BEGIN:VEVENT")
        lines.append(f"UID:{ev.id}@super-avvocato")
        lines.append(f"DTSTAMP:{_fmt(ev.updated_at)}")
        if ev.all_day:
            lines.append(f"DTSTART;VALUE=DATE:{_fmt(ev.starts_at, all_day=True)}")
            if ev.ends_at:
                lines.append(f"DTEND;VALUE=DATE:{_fmt(ev.ends_at, all_day=True)}")
        else:
            lines.append(f"DTSTART:{_fmt(ev.starts_at)}")
            if ev.ends_at:
                lines.append(f"DTEND:{_fmt(ev.ends_at)}")
        lines.append(f"SUMMARY:{_esc(ev.title)}")
        if ev.description:
            lines.append(f"DESCRIPTION:{_esc(ev.description)}")
        if ev.location:
            lines.append(f"LOCATION:{_esc(ev.location)}")
        lines.append(f"CATEGORIES:{_esc(ev.kind)}")
        lines.append("END:VEVENT")
    lines.append("END:VCALENDAR")
    # Per RFC 5545 lines shouldn't exceed 75 octets; most clients tolerate
    # longer lines, but we fold just in case.
    folded: list[str] = []
    for ln in lines:
        b = ln.encode("utf-8")
        if len(b) <= 75:
            folded.append(ln)
            continue
        # Naive fold on 70-byte chunks with CRLF + space continuation.
        i = 0
        while i < len(b):
            chunk = b[i:i + 70].decode("utf-8", errors="ignore")
            folded.append(chunk if i == 0 else " " + chunk)
            i += 70
    return "\r\n".join(folded) + "\r\n"


# ── V7.11 professional tier ────────────────────────────────────────────────
# ① stress-test udienza   ② auditor citazioni
# ③ fabbrica atti          ④ cascata termini

def _load_case_docs(case_id: str) -> list[dict]:
    """Helper — same doc payload shape /api/ask builds."""
    out: list[dict] = []
    _STALE_PREFIXES = (
        "(Një imazh u ngarkua",
        "(Ky skedar duket i skanuar",
    )
    for d in storage.list_documents(case_id):
        if not d.storage_path or not Path(d.storage_path).exists():
            continue
        text = d.extracted_text or ""
        if text.startswith(_STALE_PREFIXES):
            text = ""
        out.append({
            "filename": d.filename,
            "doc_type": d.doc_type,
            "summary": d.summary,
            "key_facts": d.key_facts,
            "extracted_text": text or None,
            "storage_path": d.storage_path,
        })
    return out


@app.post("/api/cases/<case_id>/stress-test")
@login_required_api
def api_stress_test_create(case_id: str):
    _ensure_loaded()
    user = request.user  # type: ignore[attr-defined]
    case = _resolve_case(case_id)
    if case is None:
        return jsonify({"error": "case not found"}), 404
    if not _BRAIN:
        return jsonify({"error": "no LLM backend available"}), 503
    data = request.get_json(force=True, silent=True) or {}
    hypothesis = (data.get("hypothesis") or "").strip()
    if len(hypothesis) < 20:
        return jsonify({"error": "hypothesis too short (min 20 chars)"}), 400
    try:
        result = pro_mod.stress_test_hearing(
            _BRAIN.backend, _req_index(), hypothesis,
            case_docs=_load_case_docs(case.id),
        )
    except Exception as exc:
        log.exception("stress-test failure")
        return jsonify({"error": f"{type(exc).__name__}: {exc}"}), 500
    row = storage.create_stress_test(
        case_id=case.id, user_id=user.id,
        hypothesis=hypothesis, result=result,
    )
    return jsonify({
        "id": row.id, "case_id": row.case_id, "hypothesis": row.hypothesis,
        "result": row.result, "created_at": row.created_at,
    })


@app.get("/api/cases/<case_id>/stress-tests")
@login_required_api
def api_stress_test_list(case_id: str):
    _ensure_loaded()
    user = request.user  # type: ignore[attr-defined]
    if not _resolve_case(case_id):
        return jsonify({"error": "case not found"}), 404
    rows = storage.list_stress_tests(case_id, user.id)
    return jsonify({"items": [
        {"id": r.id, "hypothesis": r.hypothesis,
         "created_at": r.created_at,
         "score": r.result.get("score", {})}
        for r in rows
    ]})


@app.get("/api/stress-test/<test_id>")
@login_required_api
def api_stress_test_get(test_id: str):
    user = request.user  # type: ignore[attr-defined]
    row = storage.get_stress_test(test_id, user.id)
    if row is None:
        return jsonify({"error": "not found"}), 404
    return jsonify({
        "id": row.id, "case_id": row.case_id,
        "hypothesis": row.hypothesis, "result": row.result,
        "created_at": row.created_at,
    })


@app.delete("/api/stress-test/<test_id>")
@login_required_api
def api_stress_test_delete(test_id: str):
    user = request.user  # type: ignore[attr-defined]
    ok = storage.delete_stress_test(test_id, user.id)
    return jsonify({"ok": ok})


# ── ② auditor citazioni ────────────────────────────────────────────────────

@app.post("/api/citation-audit")
@login_required_api
def api_citation_audit_create():
    _ensure_loaded()
    user = request.user  # type: ignore[attr-defined]
    if not _BRAIN:
        return jsonify({"error": "no LLM backend available"}), 503
    data = request.get_json(force=True, silent=True) or {}
    source_text = (data.get("text") or "").strip()
    case_id = (data.get("case_id") or "").strip() or None
    if len(source_text) < 40:
        return jsonify({"error": "text too short (min 40 chars)"}), 400
    if case_id and not _resolve_case(case_id):
        return jsonify({"error": "case not found"}), 404
    try:
        result = pro_mod.audit_citations(_BRAIN.backend, _req_index(), source_text)
    except Exception as exc:
        log.exception("citation audit failure")
        return jsonify({"error": f"{type(exc).__name__}: {exc}"}), 500
    row = storage.create_citation_audit(
        user_id=user.id, source_text=source_text,
        result=result, case_id=case_id,
    )
    return jsonify({
        "id": row.id, "case_id": row.case_id,
        "result": row.result, "created_at": row.created_at,
    })


@app.get("/api/citation-audit/<audit_id>")
@login_required_api
def api_citation_audit_get(audit_id: str):
    user = request.user  # type: ignore[attr-defined]
    row = storage.get_citation_audit(audit_id, user.id)
    if row is None:
        return jsonify({"error": "not found"}), 404
    return jsonify({
        "id": row.id, "case_id": row.case_id,
        "source_text": row.source_text, "result": row.result,
        "created_at": row.created_at,
    })


@app.get("/api/citation-audits")
@login_required_api
def api_citation_audit_list():
    user = request.user  # type: ignore[attr-defined]
    rows = storage.list_citation_audits(user.id)
    return jsonify({"items": [
        {"id": r.id, "case_id": r.case_id,
         "summary": r.result.get("summary", {}),
         "created_at": r.created_at}
        for r in rows
    ]})


# ── ③ fabbrica atti ────────────────────────────────────────────────────────

@app.get("/api/act-types")
@login_required_api
def api_act_types():
    return jsonify({"items": [
        {"key": k, "label": v} for k, v in pro_mod.ACT_TYPES.items()
    ]})


@app.post("/api/draft-act")
@login_required_api
@require_module("avokat", "prokuror")
def api_draft_act_create():
    _ensure_loaded()
    user = request.user  # type: ignore[attr-defined]
    if not _BRAIN:
        return jsonify({"error": "no LLM backend available"}), 503
    data = request.get_json(force=True, silent=True) or {}
    act_type = (data.get("act_type") or "").strip()
    brief = (data.get("brief") or "").strip()
    case_id = (data.get("case_id") or "").strip() or None
    if act_type not in pro_mod.ACT_TYPES:
        return jsonify({"error": "unknown act_type"}), 400
    if len(brief) < 50:
        return jsonify({"error": "brief too short (min 50 chars)"}), 400
    case_docs: list[dict] = []
    if case_id:
        if not _resolve_case(case_id):
            return jsonify({"error": "case not found"}), 404
        case_docs = _load_case_docs(case_id)
    try:
        draft = pro_mod.draft_act(
            _BRAIN.backend, _req_index(),
            act_type=act_type, brief=brief, case_docs=case_docs,
        )
    except Exception as exc:
        log.exception("draft act failure")
        return jsonify({"error": f"{type(exc).__name__}: {exc}"}), 500
    row = storage.create_drafted_act(
        user_id=user.id, act_type=act_type, brief=brief,
        draft_text=draft.get("body_markdown", ""),
        case_id=case_id, meta=draft,
    )
    return jsonify({
        "id": row.id, "case_id": row.case_id, "act_type": row.act_type,
        "brief": row.brief, "draft": draft, "created_at": row.created_at,
    })


@app.get("/api/draft-act/<act_id>")
@login_required_api
def api_draft_act_get(act_id: str):
    user = request.user  # type: ignore[attr-defined]
    row = storage.get_drafted_act(act_id, user.id)
    if row is None:
        return jsonify({"error": "not found"}), 404
    return jsonify({
        "id": row.id, "case_id": row.case_id, "act_type": row.act_type,
        "brief": row.brief, "draft": row.meta,
        "created_at": row.created_at,
    })


@app.get("/api/draft-act/<act_id>/docx")
@login_required_api
def api_draft_act_docx(act_id: str):
    user = request.user  # type: ignore[attr-defined]
    row = storage.get_drafted_act(act_id, user.id)
    if row is None:
        return Response("not found", status=404)
    out_dir = APP_DB_PATH.parent / "drafts"
    out_path = out_dir / f"{row.act_type}-{row.id[:8]}.docx"
    try:
        pro_mod.render_act_docx(row.meta, out_path)
    except Exception as exc:
        log.exception("docx render failure")
        return Response(f"render error: {exc}", status=500)
    safe_name = f"{row.act_type}-{row.created_at[:10]}.docx"
    return send_file(
        out_path, as_attachment=True, download_name=safe_name,
        mimetype="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    )


@app.post("/api/export/docx")
@login_required_api
def api_export_docx():
    """Generic: any Copilota markdown output -> downloadable .docx."""
    data = request.get_json(silent=True) or {}
    md = (data.get("markdown") or "").strip()
    title = (data.get("title") or "Dokument").strip()
    if len(md) < 5:
        return Response("empty", status=400)
    # light inline-markdown cleanup so the .docx reads cleanly
    lines = []
    for ln in md.split("\n"):
        t = ln.rstrip()
        st = t.lstrip()
        # normalise "* bullet" -> "- bullet" (render_act_docx handles "- ")
        if st.startswith("* ") and not st.startswith("**"):
            t = t[: len(t) - len(st)] + "- " + st[2:]
        t = re.sub(r"\*\*(.+?)\*\*", r"\1", t)   # bold
        t = re.sub(r"`([^`]+)`", r"\1", t)          # inline code
        t = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r"\1 (\2)", t)  # links
        lines.append(t)
    draft = {"title": title, "body_markdown": "\n".join(lines)}
    safe = re.sub(r"[^0-9A-Za-zçëÇË _-]", "", title)[:60].strip() or "dokument"
    out_dir = APP_DB_PATH.parent / "exports"
    out_path = out_dir / (safe.replace(" ", "_") + ".docx")
    try:
        pro_mod.render_act_docx(draft, out_path)
    except Exception as exc:  # noqa: BLE001
        log.exception("export docx failure")
        return Response(f"render error: {exc}", status=500)
    return send_file(
        out_path, as_attachment=True, download_name=safe + ".docx",
        mimetype="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    )


@app.get("/api/drafted-acts")
@login_required_api
def api_drafted_acts_list():
    user = request.user  # type: ignore[attr-defined]
    rows = storage.list_drafted_acts(user.id)
    return jsonify({"items": [
        {"id": r.id, "case_id": r.case_id, "act_type": r.act_type,
         "title": (r.meta or {}).get("title"),
         "created_at": r.created_at}
        for r in rows
    ]})


# ── ④ cascata termini processuali ──────────────────────────────────────────

@app.get("/api/cascade/event-types")
@login_required_api
def api_cascade_event_types():
    return jsonify({"items": pro_mod.cascade_event_types()})


@app.post("/api/cascade/compute")
@login_required_api
def api_cascade_compute():
    data = request.get_json(force=True, silent=True) or {}
    event_type = (data.get("event_type") or "").strip()
    event_date = (data.get("event_date") or "").strip()
    if not event_type or not event_date:
        return jsonify({"error": "event_type and event_date required"}), 400
    try:
        result = pro_mod.compute_deadline_cascade(event_type, event_date)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    return jsonify(result)


@app.post("/api/cascade/schedule")
@login_required_api
def api_cascade_schedule():
    """Push every derived deadline into the V7.10 calendar as events."""
    user = request.user  # type: ignore[attr-defined]
    data = request.get_json(force=True, silent=True) or {}
    event_type = (data.get("event_type") or "").strip()
    event_date = (data.get("event_date") or "").strip()
    case_id = (data.get("case_id") or "").strip() or None
    if case_id and not _resolve_case(case_id):
        return jsonify({"error": "case not found"}), 404
    try:
        cascade = pro_mod.compute_deadline_cascade(event_type, event_date)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    created = 0
    for d in cascade["derived_deadlines"]:
        iso_date = d["due_date"]
        starts_at = datetime.fromisoformat(
            f"{iso_date}T09:00:00+00:00",
        ).astimezone(UTC).isoformat().replace("+00:00", "Z")
        source_ref = (
            f"cascade:{event_type}:{event_date}:{d['key']}"
            + (f":{case_id}" if case_id else "")
        )
        existing = storage.event_by_source_ref(user.id, source_ref)
        if existing:
            continue
        urgency = d.get("urgency", "medium")
        reminders = {
            "critical": [2880, 1440, 180],
            "high":     [2880, 1440],
            "medium":   [1440],
            "low":      [1440],
        }.get(urgency, [1440])
        title = d["label"]
        description = f"Baza ligjore: {d['citation']}\n{d.get('notes', '')}"
        storage.create_event(
            user_id=user.id, title=title, kind="afat",
            starts_at=starts_at, case_id=case_id,
            description=description.strip(),
            source="cascade", source_ref=source_ref,
            reminders=reminders,
        )
        created += 1
    cascade["events_created"] = created
    return jsonify(cascade)


# ── ⑤ V7.12 — TIMELINE DEL FASCICOLO ───────────────────────────────────────

def _case_summary_text(case_id: str, fallback: str = "") -> str:
    """Pull the lawyer's narrative for a case — first user message + title.

    Falls back to ``fallback`` (typically a passed-in body) if the case has
    no chat history yet.
    """
    msgs = storage.list_messages(case_id)
    user_msgs = [m for m in msgs if m.role == "user"]
    if user_msgs:
        return "\n\n".join(m.content for m in user_msgs[:3]).strip()
    return fallback.strip()


@app.post("/api/cases/<case_id>/timeline")
@login_required_api
def api_timeline_build(case_id: str):
    user = request.user  # type: ignore[attr-defined]
    if _BRAIN is None:
        return jsonify({"error": "brain not available"}), 503
    case = _resolve_case(case_id)
    if not case:
        return jsonify({"error": "case not found"}), 404

    data = request.get_json(force=True, silent=True) or {}
    extra_summary = (data.get("summary") or "").strip()
    summary = _case_summary_text(case_id, fallback=extra_summary)
    if not summary and not extra_summary:
        return jsonify({"error": "case has no narrative or documents to analyse"}), 400

    docs = _load_case_docs(case_id)
    try:
        result = pro_mod.build_case_timeline(
            backend=_BRAIN.backend,
            case_summary=summary or extra_summary,
            case_title=case.title or "rast pa titull",
            case_docs=docs,
        )
    except Exception as exc:
        log.exception("timeline build failed for case %s", case_id)
        return jsonify({"error": str(exc)}), 500

    row = storage.upsert_case_timeline(
        case_id=case_id, user_id=user.id, result=result,
        doc_count=result.get("doc_count", len(docs)),
        event_count=result.get("event_count", len(result.get("events", []))),
    )
    return jsonify({
        "case_id": case_id,
        "result": result,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    })


@app.get("/api/cases/<case_id>/timeline")
@login_required_api
def api_timeline_get(case_id: str):
    user = request.user  # type: ignore[attr-defined]
    if not _resolve_case(case_id):
        return jsonify({"error": "case not found"}), 404
    row = storage.get_case_timeline(case_id, user.id)
    if not row:
        return jsonify({"result": None}), 200
    return jsonify({
        "case_id": case_id,
        "result": row.result,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
        "doc_count": row.doc_count,
        "event_count": row.event_count,
    })


@app.delete("/api/cases/<case_id>/timeline")
@login_required_api
def api_timeline_delete(case_id: str):
    user = request.user  # type: ignore[attr-defined]
    ok = storage.delete_case_timeline(case_id, user.id)
    if not ok:
        return jsonify({"error": "no timeline"}), 404
    return jsonify({"deleted": True})


# ── ⑥ V7.12 — ADVERSARIAL LOOP ─────────────────────────────────────────────

@app.post("/api/cases/<case_id>/adversarial")
@login_required_api
def api_adversarial_run(case_id: str):
    user = request.user  # type: ignore[attr-defined]
    if _BRAIN is None:
        return jsonify({"error": "brain not available"}), 503
    case = _resolve_case(case_id)
    if not case:
        return jsonify({"error": "case not found"}), 404

    data = request.get_json(force=True, silent=True) or {}
    hypothesis = (data.get("hypothesis") or "").strip()
    if len(hypothesis) < 30:
        return jsonify({"error": "hypothesis too short (min 30 chars)"}), 400
    try:
        max_rounds = int(data.get("max_rounds") or 5)
    except (TypeError, ValueError):
        max_rounds = 5
    max_rounds = max(2, min(max_rounds, 8))

    docs = _load_case_docs(case_id)
    try:
        result = pro_mod.adversarial_loop(
            backend=_BRAIN.backend, index=_INDEX,
            hypothesis=hypothesis, max_rounds=max_rounds,
            case_docs=docs,
        )
    except Exception as exc:
        log.exception("adversarial loop failed for case %s", case_id)
        return jsonify({"error": str(exc)}), 500

    row = storage.create_adversarial_loop(
        case_id=case_id, user_id=user.id, hypothesis=hypothesis,
        rounds=result["rounds"], summary=result["summary"],
    )
    return jsonify({
        "id": row.id, "case_id": case_id,
        "result": result, "created_at": row.created_at,
    })


@app.get("/api/cases/<case_id>/adversarial")
@login_required_api
def api_adversarial_list(case_id: str):
    user = request.user  # type: ignore[attr-defined]
    if not _resolve_case(case_id):
        return jsonify({"error": "case not found"}), 404
    rows = storage.list_adversarial_loops(case_id, user.id)
    return jsonify({"items": [
        {"id": r.id, "hypothesis": r.hypothesis,
         "round_count": r.round_count,
         "verdict": (r.summary or {}).get("verdict_likelihood"),
         "created_at": r.created_at}
        for r in rows
    ]})


@app.get("/api/adversarial/<loop_id>")
@login_required_api
def api_adversarial_get(loop_id: str):
    user = request.user  # type: ignore[attr-defined]
    row = storage.get_adversarial_loop(loop_id, user.id)
    if not row:
        return jsonify({"error": "not found"}), 404
    return jsonify({
        "id": row.id, "case_id": row.case_id,
        "hypothesis": row.hypothesis,
        "rounds": row.rounds, "summary": row.summary,
        "round_count": row.round_count,
        "created_at": row.created_at,
    })


@app.post("/api/cases/<case_id>/strategy")
@login_required_api
def api_strategy_build(case_id: str):
    user = request.user  # type: ignore[attr-defined]
    if _BRAIN is None:
        return jsonify({"error": "brain not available"}), 503
    case = _resolve_case(case_id)
    if not case:
        return jsonify({"error": "case not found"}), 404

    data = request.get_json(force=True, silent=True) or {}
    objective = (data.get("objective") or "").strip()
    if len(objective) < 10:
        return jsonify({"error": "objective too short (min 10 chars)"}), 400

    case_summary = _case_summary_text(case_id, fallback=case.title or "")
    docs = _load_case_docs(case_id)
    try:
        result = pro_mod.build_strategy_compass(
            backend=_BRAIN.backend, index=_INDEX,
            objective=objective, case_summary=case_summary,
            case_title=case.title, case_docs=docs,
        )
    except Exception as exc:
        log.exception("strategy compass failed for case %s", case_id)
        return jsonify({"error": str(exc)}), 500

    row = storage.create_strategy_compass(
        case_id=case_id, user_id=user.id,
        objective=objective, tree=result, meta=result.get("meta") or {},
    )
    return jsonify({
        "id": row.id, "case_id": case_id,
        "result": result, "created_at": row.created_at,
    })


@app.get("/api/cases/<case_id>/strategy")
@login_required_api
def api_strategy_list(case_id: str):
    user = request.user  # type: ignore[attr-defined]
    if not _resolve_case(case_id):
        return jsonify({"error": "case not found"}), 404
    rows = storage.list_strategy_compasses(case_id, user.id)
    return jsonify({"items": [
        {"id": r.id, "objective": r.objective,
         "node_count": (r.meta or {}).get("node_count"),
         "depth": (r.meta or {}).get("depth"),
         "created_at": r.created_at}
        for r in rows
    ]})


@app.get("/api/strategy/<compass_id>")
@login_required_api
def api_strategy_get(compass_id: str):
    user = request.user  # type: ignore[attr-defined]
    row = storage.get_strategy_compass(compass_id, user.id)
    if not row:
        return jsonify({"error": "not found"}), 404
    return jsonify({
        "id": row.id, "case_id": row.case_id,
        "objective": row.objective,
        "result": row.tree,
        "meta": row.meta,
        "created_at": row.created_at,
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


# ── V8.11 Citation Shield V2 — provenance export ──────────────────────────

@app.get("/api/provenance/<response_id>.json")
@login_required_api
def api_provenance_json(response_id: str):
    user = request.user  # type: ignore[attr-defined]
    pack = storage.get_provenance(response_id, user.id)
    if not pack:
        return jsonify({"error": "not_found"}), 404
    response = jsonify(pack)
    response.headers["Content-Disposition"] = (
        f'attachment; filename="provenance_{response_id}.json"'
    )
    return response


@app.get("/api/provenance/<response_id>.docx")
@login_required_api
def api_provenance_docx(response_id: str):
    user = request.user  # type: ignore[attr-defined]
    pack = storage.get_provenance(response_id, user.id)
    if not pack:
        return ("Provenance pack not found", 404)
    docx_bytes = pro_mod.provenance_docx(pack)
    return send_file(
        io.BytesIO(docx_bytes),
        mimetype="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        as_attachment=True,
        download_name=f"provenance_{response_id}.docx",
    )


@app.get("/api/cases/<case_id>/provenance")
@login_required_api
def api_case_provenance_list(case_id: str):
    user = request.user  # type: ignore[attr-defined]
    case = storage.get_case(case_id, user.id)
    if not case:
        return jsonify({"error": "not_found"}), 404
    packs = storage.list_provenance(case_id, user.id, limit=100)
    return jsonify({"items": packs, "count": len(packs)})


# ── V8.12 EU AI Act audit log — admin endpoints ───────────────────────────
#
# These satisfy AI Act art. 12 (automated logs accessible to deployer) and
# art. 13 (transparency to users / regulators on request). Restricted to
# admin users; the DPO inspects the log via this surface during incident
# triage or supervisory authority requests.

@app.get("/admin/audit")
@login_required_page
def admin_audit_page():
    """DPO-facing audit log viewer — paired with the JSON/JSONL API endpoints
    below. Admin-only; non-admin users get a 403 to keep the surface honest."""
    user = current_user()
    if not user.is_admin:
        return ("Forbidden — admin access required.", 403)
    return render_template("admin_audit.html")


@app.get("/api/admin/audit/summary")
@login_required_api
def api_admin_audit_summary():
    user = request.user  # type: ignore[attr-defined]
    if not user.is_admin:
        return jsonify({"error": "forbidden"}), 403
    since = request.args.get("since") or None
    return jsonify(storage.audit_summary(since=since))


@app.get("/api/admin/audit")
@login_required_api
def api_admin_audit_list():
    user = request.user  # type: ignore[attr-defined]
    if not user.is_admin:
        return jsonify({"error": "forbidden"}), 403
    rows = storage.list_audit(
        user_id=request.args.get("user_id", type=int),
        case_id=request.args.get("case_id"),
        callsite=request.args.get("callsite"),
        outcome=request.args.get("outcome"),
        since=request.args.get("since"),
        limit=request.args.get("limit", default=200, type=int),
    )
    return jsonify({"items": rows, "count": len(rows)})


@app.get("/api/admin/audit.jsonl")
@login_required_api
def api_admin_audit_export():
    """Stream the full audit log as JSONL — for regulator handover."""
    user = request.user  # type: ignore[attr-defined]
    if not user.is_admin:
        return ("forbidden", 403)
    since = request.args.get("since") or None
    rows = storage.list_audit(since=since, limit=100000)
    payload = "\n".join(json.dumps(r, ensure_ascii=False, default=str) for r in rows)
    return (
        payload + "\n",
        200,
        {
            "Content-Type": "application/x-jsonlines; charset=utf-8",
            "Content-Disposition": 'attachment; filename="ai_audit_log.jsonl"',
        },
    )


# ── admin user management (V9.2) ──────────────────────────────────────────
# Self-serve user provisioning from the Studio modal. Only admins can list,
# create, delete, or reset passwords for other users. Any logged-in user can
# change their OWN password.

# ── Parcheggio delle risposte lunghe ───────────────────────────────────
#
# Gli strumenti PRO tengono aperta la richiesta per minuti. Sul telefono,
# passare a WhatsApp sospende la scheda e la connessione cade: al ritorno
# l'avvocato vede «Gabim rrjeti» — ma il server ha finito il lavoro comunque
# (Flask esegue la funzione fino in fondo anche se il client se n'e' andato).
# Qui la risposta viene messa da parte PRIMA di provare a scriverla, cosi'
# c'e' ancora quando il telefono torna.
_PARCHEGGIO: dict[str, tuple[float, int, bytes, str]] = {}
_PARCHEGGIO_LOCK = threading.Lock()
_PARCHEGGIO_TTL = 40 * 60          # mezz'ora abbondante: copre l'analisi + il ritorno
_PARCHEGGIO_MAX = 200              # tetto: e' memoria, non un archivio


def _parcheggia(chiave: str, uid: int, corpo: bytes, mimetype: str) -> None:
    """Mette da parte una risposta. Non solleva mai: e' un di piu'."""
    try:
        adesso = time.time()
        with _PARCHEGGIO_LOCK:
            # pulizia delle scadute, cosi' non cresce all'infinito
            for k in [k for k, (t, *_r) in _PARCHEGGIO.items()
                      if adesso - t > _PARCHEGGIO_TTL]:
                _PARCHEGGIO.pop(k, None)
            if len(_PARCHEGGIO) >= _PARCHEGGIO_MAX:
                # via la piu' vecchia
                vecchia = min(_PARCHEGGIO.items(), key=lambda x: x[1][0])[0]
                _PARCHEGGIO.pop(vecchia, None)
            _PARCHEGGIO[chiave] = (adesso, uid, corpo, mimetype)
    except Exception:  # noqa: BLE001
        log.exception("parcheggio risposta")


@app.get("/api/tool/result")
@login_required_api
def api_tool_result():
    """La risposta parcheggiata, se c'e'.

    202 = non ancora (o mai esistita): il client continua ad aspettare. Non
    distinguiamo i due casi di proposito — dall'esterno sono identici, e
    dirlo aprirebbe un modo per sapere se una chiave esiste.
    """
    chiave = (request.args.get("key") or "").strip()
    if not chiave:
        return jsonify({"error": "no key"}), 400
    uid = request.user.id  # type: ignore[attr-defined]
    with _PARCHEGGIO_LOCK:
        voce = _PARCHEGGIO.get(chiave)
    if not voce:
        return jsonify({"status": "running"}), 202
    _t, proprietario, corpo, mimetype = voce
    # ⚠️ legato all'utente: la chiave e' imprevedibile, ma il fascicolo di uno
    # studio non deve poter uscire da un'altra sessione nemmeno per sbaglio.
    if proprietario != uid:
        return jsonify({"status": "running"}), 202
    return app.response_class(corpo, mimetype=mimetype or "application/json")


@app.after_request
def _parcheggia_risposta(resp):
    """Mette da parte la risposta quando il client ha chiesto di poterla
    ritrovare. Silenzioso e inerte senza l'intestazione."""
    try:
        chiave = request.headers.get("X-Job-Key", "").strip()
        if (chiave and resp.status_code == 200
                and (resp.mimetype or "").endswith("json")
                and not resp.direct_passthrough):
            uid = getattr(getattr(request, "user", None), "id", None)
            if uid is not None:
                _parcheggia(chiave, uid, resp.get_data(), resp.mimetype)
    except Exception:  # noqa: BLE001
        pass
    return resp


@app.after_request
def _no_cache_html(resp):
    """HTML sempre fresco, asset versionati con cache lunga.

    Senza questo il browser trattiene la pagina e continua a chiedere la
    vecchia `app.js?v=N`: il cache-busting non serve a nulla, perche' e'
    proprio l'HTML vecchio a dire quale versione caricare."""
    try:
        ctype = (resp.headers.get("Content-Type") or "")
        if ctype.startswith("text/html"):
            resp.headers["Cache-Control"] = "no-store, must-revalidate"
            resp.headers["Pragma"] = "no-cache"
        elif request.path.startswith("/static/") and request.args.get("v"):
            # l'URL cambia a ogni release: si puo' tenere a lungo
            resp.headers["Cache-Control"] = "public, max-age=31536000, immutable"
    except Exception:  # noqa: BLE001 - mai far fallire una risposta per gli header
        pass
    return resp


@app.before_request
def _arm_jurisdiction():
    """Reset di partenza per ogni richiesta.

    ATTENZIONE: qui request.user NON e ancora impostato (lo fa
    login_required_api dopo), quindi questo non basta: il valore giusto lo
    arma auth._arm_request_jurisdiction() quando l'utente e noto. Qui si
    azzera soltanto, per non ereditare la giurisdizione di una richiesta
    precedente sullo stesso thread."""
    try:
        from . import brain as _brain_mod
        _brain_mod.set_request_jurisdiction("AL")
    except Exception:  # noqa: BLE001
        pass


def _active_jurisdiction(user):
    """The jurisdiction locked for THIS session — one of the user's entitled
    countries. The brain loads only this law + language (no mixing). Defaults
    to the session choice if allowed, else AL, else the first entitled."""
    from flask import session
    allowed = storage.user_jurisdictions(user)
    j = (session.get("jurisdiction") or "").upper()
    if j in allowed:
        return j
    return "AL" if "AL" in allowed else sorted(allowed)[0]


def _index_for(user):
    """Article index for the user's active jurisdiction — Italian corpus for IT
    sessions, Albanian otherwise."""
    try:
        if _INDEX_IT is not None and user is not None and _active_jurisdiction(user) == "IT":
            return _INDEX_IT
    except Exception:  # noqa: BLE001
        pass
    return _INDEX


def _scudo_citazioni(md: str, citations: dict) -> str:
    """Fa viaggiare l'avviso insieme al testo, non solo a schermo.

    Il badge dice all'avvocato che una citazione e' falsa finche' guarda la
    pagina. Ma la risposta viene copiata dentro le memorie, e da li' in poi il
    badge non c'e' piu': l'articolo inventato arriverebbe in tribunale senza
    un segno addosso.

    Stessa logica del cervello principale, e stessa prudenza: si rifiuta solo
    quando NON c'e' nemmeno una citazione buona (`should_refuse` lascia
    passare le risposte miste, col badge a dire quali sono quali).

    Non chiama il modello: e' calcolo sul testo gia' prodotto, quindi non
    rallenta niente e non puo' cambiare il ragionamento.
    """
    if not md or not isinstance(citations, dict):
        return md
    try:
        juris = "AL"
        try:
            juris = _active_jurisdiction(getattr(request, "user", None)) or "AL"
        except Exception:  # noqa: BLE001
            pass
        if cs_mod.should_refuse(citations):
            md = cs_mod.apply_refusal(md, jurisdiction=juris)
        if int((citations.get("stats") or {}).get("fake") or 0) > 0:
            md = cs_mod.annotate_fake_citations(md, citations)
    except Exception:  # noqa: BLE001
        log.debug("citation shield skipped", exc_info=True)
    # ── e adesso i VENDIME, che il controllo dei nene non guarda ──────
    #
    # Misurato: una risposta citava «00-2025-1760», un numero di sentenza che
    # non esiste in nessun documento nostro. I nene erano tutti buoni, quindi
    # lo scudo taceva e il numero inventato arrivava in fondo — e da li' in un
    # atto. Qui si dice quali non si possono confermare.
    #
    # Non rifiuta e non cancella: la nostra base ha 1.407 decisioni su molte di
    # piu' pubblicate, quindi «non lo trovo» significa «controllala», non
    # «e' falsa». Marchiare come falso un precedente vero sarebbe grave quanto
    # lasciar passare uno inventato.
    try:
        idx_dec = _decisions_index()
        if idx_dec is not None:
            casi = ccv_mod.verify_cases(md, idx_dec)
            if (casi.get("stats") or {}).get("unverified"):
                md = ccv_mod.annotate_unverified(md, casi, jurisdiction=juris)
    except Exception:  # noqa: BLE001
        log.debug("case citation shield skipped", exc_info=True)
    return md


def _decisions_index():
    """L'indice dei precedenti gia' caricato, senza rileggerlo dal disco.

    Il pickle pesa 33 MB: ricaricarlo a ogni risposta costerebbe piu' della
    verifica stessa. Il cervello ce l'ha gia' in memoria.
    """
    try:
        _ensure_loaded()
        for attr in ("decisions_index", "decision_index", "_decisions"):
            got = getattr(_BRAIN, attr, None)
            if got is not None and getattr(got, "decisions", None):
                return got
    except Exception:  # noqa: BLE001
        pass
    try:
        from .retrieval import DecisionIndex, DECISIONS_INDEX_FILE
        global _DEC_IDX
        if _DEC_IDX is None:
            _DEC_IDX = DecisionIndex.load(DECISIONS_INDEX_FILE)
        return _DEC_IDX
    except Exception:  # noqa: BLE001
        return None


_DEC_IDX = None


def _req_index():
    """Index for the current request's user (safe if unauthenticated -> AL)."""
    return _index_for(getattr(request, "user", None))


def _user_payload(u) -> dict:
    from datetime import datetime, UTC
    reason = storage.access_block_reason(u)
    status = "admin" if u.is_admin else (reason or "active")
    plan = getattr(u, "plan_expires_at", None)
    demo = getattr(u, "demo_expires_at", None)
    days_left = None
    exp = plan or demo
    if exp and not u.is_admin:
        try:
            dt = datetime.fromisoformat(exp.replace("Z", "+00:00"))
            days_left = (dt - datetime.now(UTC)).days
        except Exception:  # noqa: BLE001
            days_left = None
    return {
        "id": u.id,
        "username": u.username,
        "is_admin": u.is_admin,
        "created_at": (u.created_at.isoformat() if hasattr(getattr(u, "created_at", None), "isoformat") else getattr(u, "created_at", None)),
        "suspended": bool(getattr(u, "suspended", False)),
        "profession": getattr(u, "profession", "avokat"),
        "modules": sorted(storage.user_modules(u)),
        "jurisdictions": sorted(storage.user_jurisdictions(u)),
        "plan_expires_at": plan,
        "demo_expires_at": demo,
        "status": status,
        "days_left": days_left,
    }


@app.get("/api/admin/users")
@login_required_api
def api_admin_users_list():
    user = request.user  # type: ignore[attr-defined]
    if not user.is_admin:
        return jsonify({"error": "forbidden"}), 403
    rows = storage.list_users()
    return jsonify({"items": [_user_payload(u) for u in rows], "count": len(rows)})


@app.post("/api/admin/users")
@login_required_api
def api_admin_users_create():
    user = request.user  # type: ignore[attr-defined]
    if not user.is_admin:
        return jsonify({"error": "forbidden"}), 403
    data = request.get_json(silent=True) or {}
    username = (data.get("username") or "").strip().lower()
    password = data.get("password") or ""
    is_admin_flag = bool(data.get("is_admin"))
    if not username or not username.replace(".", "").replace("_", "").replace("-", "").isalnum():
        return jsonify({"error": "username invalido (solo lettere, numeri, . _ -)"}), 400
    if len(password) < 6:
        return jsonify({"error": "password troppo corta (min 6 caratteri)"}), 400
    if storage.get_user_by_username(username):
        return jsonify({"error": f"utente '{username}' esiste già"}), 409
    profession = (data.get("profession") or "avokat").strip()
    new_user = storage.create_user(
        username=username,
        password_hash=hash_password(password),
        is_admin=is_admin_flag,
        profession=profession,
    )
    mods = data.get("modules")
    if isinstance(mods, list) and any(m in storage.VALID_MODULES for m in mods):
        storage.set_user_modules(new_user.id, mods)
    elif profession in storage.VALID_MODULES:
        storage.set_user_modules(new_user.id, [profession])
    if data.get("plan_expires_at"):
        storage.set_user_plan_expiry(new_user.id, str(data["plan_expires_at"]))
    new_user = storage.get_user_by_id(new_user.id)
    log.info("admin %s created user %s (admin=%s)", user.username, username, is_admin_flag)
    return jsonify(_user_payload(new_user)), 201


@app.post("/api/admin/firms")
@login_required_api
def api_admin_create_firm():
    """Admin: create a new studio (firm) and assign its owner."""
    user = request.user  # type: ignore[attr-defined]
    if not user.is_admin:
        return jsonify({"error": "forbidden"}), 403
    data = request.get_json(silent=True) or {}
    name = (data.get("name") or "").strip()
    owner_username = (data.get("owner_username") or "").strip().lower()
    if not name:
        return jsonify({"error": "emri i studios mungon"}), 400
    if owner_username:
        owner = storage.get_user_by_username(owner_username)
        if owner is None:
            return jsonify({"error": f"përdoruesi '{owner_username}' nuk ekziston"}), 404
    else:
        owner = user
    try:
        firm = storage.create_firm(name, owner.id)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    log.info("admin %s created firm '%s' (owner=%s)", user.username, name, owner.username)
    return jsonify({"id": firm.id, "name": firm.name,
                    "owner": owner.username}), 201


@app.patch("/api/admin/users/<int:user_id>/profession")
@login_required_api
def api_admin_set_profession(user_id):
    user = request.user  # type: ignore[attr-defined]
    if not user.is_admin:
        return jsonify({"error": "forbidden"}), 403
    prof = ((request.get_json(silent=True) or {}).get("profession") or "").strip()
    if not storage.set_user_profession(user_id, prof):
        return jsonify({"error": "profesion i pavlefshëm"}), 400
    return jsonify({"ok": True, "profession": prof})


@app.patch("/api/admin/users/<int:user_id>/modules")
@login_required_api
def api_admin_set_modules(user_id):
    user = request.user  # type: ignore[attr-defined]
    if not user.is_admin:
        return jsonify({"error": "forbidden"}), 403
    mods = (request.get_json(silent=True) or {}).get("modules")
    if not isinstance(mods, list) or not any(m in storage.VALID_MODULES for m in mods):
        return jsonify({"error": "të paktën një modul i vlefshëm"}), 400
    if not storage.set_user_modules(user_id, mods):
        return jsonify({"error": "dështoi"}), 400
    return jsonify(_user_payload(storage.get_user_by_id(user_id)))


@app.patch("/api/admin/users/<int:user_id>/plan")
@login_required_api
def api_admin_set_plan(user_id):
    """Set/extend/clear subscription expiry. Body: {months:N} extend from
    max(now, current); {expires_at:"ISO"} explicit; {clear:true} permanent."""
    from datetime import datetime, UTC
    import calendar
    user = request.user  # type: ignore[attr-defined]
    if not user.is_admin:
        return jsonify({"error": "forbidden"}), 403
    target = storage.get_user_by_id(user_id)
    if target is None:
        return jsonify({"error": "user not found"}), 404
    data = request.get_json(silent=True) or {}
    if data.get("clear"):
        storage.set_user_plan_expiry(user_id, None)
        return jsonify(_user_payload(storage.get_user_by_id(user_id)))
    if data.get("expires_at"):
        storage.set_user_plan_expiry(user_id, str(data["expires_at"]))
        return jsonify(_user_payload(storage.get_user_by_id(user_id)))
    if data.get("months"):
        try:
            months = int(data["months"])
        except (TypeError, ValueError):
            return jsonify({"error": "muaj i pavlefshëm"}), 400
        now = datetime.now(UTC)
        base = now
        cur = getattr(target, "plan_expires_at", None)
        if cur:
            try:
                curdt = datetime.fromisoformat(cur.replace("Z", "+00:00"))
                if curdt > now:
                    base = curdt
            except Exception:  # noqa: BLE001
                base = now
        m = base.month - 1 + months
        y = base.year + m // 12
        m = m % 12 + 1
        d = min(base.day, calendar.monthrange(y, m)[1])
        newdt = base.replace(year=y, month=m, day=d)
        storage.set_user_plan_expiry(user_id, newdt.strftime("%Y-%m-%dT%H:%M:%SZ"))
        return jsonify(_user_payload(storage.get_user_by_id(user_id)))
    return jsonify({"error": "specifiko months, expires_at ose clear"}), 400


@app.get("/api/session/jurisdiction")
@login_required_api
def api_session_jurisdiction_get():
    user = request.user  # type: ignore[attr-defined]
    return jsonify({"active": _active_jurisdiction(user),
                    "available": sorted(storage.user_jurisdictions(user))})


@app.post("/api/session/jurisdiction")
@login_required_api
def api_session_jurisdiction_set():
    from flask import session
    user = request.user  # type: ignore[attr-defined]
    j = ((request.get_json(silent=True) or {}).get("jurisdiction") or "").upper()
    if j not in storage.user_jurisdictions(user):
        return jsonify({"error": "juridiksion i palejuar"}), 403
    session["jurisdiction"] = j
    return jsonify({"active": j})


@app.patch("/api/admin/users/<int:user_id>/jurisdictions")
@login_required_api
def api_admin_set_jurisdictions(user_id):
    user = request.user  # type: ignore[attr-defined]
    if not user.is_admin:
        return jsonify({"error": "forbidden"}), 403
    js = (request.get_json(silent=True) or {}).get("jurisdictions")
    if not isinstance(js, list) or not any(str(x).strip().upper() in storage.VALID_JURISDICTIONS for x in js):
        return jsonify({"error": "të paktën një juridiksion i vlefshëm"}), 400
    if not storage.set_user_jurisdictions(user_id, js):
        return jsonify({"error": "dështoi"}), 400
    return jsonify(_user_payload(storage.get_user_by_id(user_id)))


@app.patch("/api/me/profession")
@login_required_api
def api_me_set_profession():
    user = request.user  # type: ignore[attr-defined]
    prof = ((request.get_json(silent=True) or {}).get("profession") or "").strip()
    if not storage.set_user_profession(user.id, prof):
        return jsonify({"error": "profesion i pavlefshëm"}), 400
    return jsonify({"ok": True, "profession": prof})


@app.patch("/api/admin/users/<int:user_id>/password")
@login_required_api
def api_admin_users_set_password(user_id):
    user = request.user  # type: ignore[attr-defined]
    target = storage.get_user_by_id(user_id)
    if target is None:
        return jsonify({"error": "utente non trovato"}), 404
    # Admin può cambiare a chiunque, non-admin solo se è la propria
    if not user.is_admin and user.id != target.id:
        return jsonify({"error": "forbidden"}), 403
    data = request.get_json(silent=True) or {}
    new_pw = data.get("password") or ""
    if len(new_pw) < 6:
        return jsonify({"error": "password troppo corta (min 6 caratteri)"}), 400
    ok = storage.set_password_hash(target.username, hash_password(new_pw))
    if not ok:
        return jsonify({"error": "errore aggiornamento password"}), 500
    log.info("user %s changed password for user %s", user.username, target.username)
    return jsonify({"ok": True})


@app.get("/api/admin/usage")
@login_required_api
def api_admin_usage():
    """Aggregated usage stats per user. Admin-only.
    Query param `period` = 'day' | 'week' | 'month' | 'all' (default: month)."""
    from datetime import datetime, timedelta, UTC
    user = request.user  # type: ignore[attr-defined]
    if not user.is_admin:
        return jsonify({"error": "forbidden"}), 403
    period = (request.args.get("period") or "month").lower()
    since_iso = None
    if period == "day":
        since = datetime.now(UTC) - timedelta(days=1)
        since_iso = since.strftime("%Y-%m-%dT%H:%M:%SZ")
    elif period == "week":
        since = datetime.now(UTC) - timedelta(days=7)
        since_iso = since.strftime("%Y-%m-%dT%H:%M:%SZ")
    elif period == "month":
        since = datetime.now(UTC) - timedelta(days=30)
        since_iso = since.strftime("%Y-%m-%dT%H:%M:%SZ")
    # 'all' = no filter
    rows = storage.usage_stats_by_user(since_iso=since_iso)
    totals = storage.usage_totals(since_iso=since_iso)
    online = storage.online_user_ids(window_seconds=300)
    # La quota: il numero che serve davvero quando un abbonamento e' diviso
    # fra piu' studi. «Lo studio A e' il 62% del consumo» si legge in un colpo
    # d'occhio; «$4,10 contro $0,90» no.
    _tot_micro = sum(int(r.get("cost_micro") or 0) for r in rows) or 0
    for r in rows:
        r["online"] = r["user_id"] in online
        r["quota_pct"] = (
            round(100.0 * int(r.get("cost_micro") or 0) / _tot_micro, 1)
            if _tot_micro else 0.0
        )
    # Chi sta per saturare: si calcola sempre sulla settimana mobile, a
    # prescindere dal periodo che l'amministratore sta guardando — il
    # rischio non cambia perche' lui ha selezionato «oggi».
    try:
        allarmi = storage.studi_oltre_soglia()
    except Exception:  # noqa: BLE001
        log.exception("soglie studi")
        allarmi = []
    return jsonify({
        "period": period,
        "since": since_iso,
        "users": rows,
        "totals": totals,
        "online_count": len(online),
        "allarmi": allarmi,
    })


@app.patch("/api/admin/users/<int:user_id>/cap")
@login_required_api
def api_admin_set_cap(user_id: int):
    """Il tetto settimanale di consumo di uno studio. Solo amministratore.

    Il corpo porta `cap_usd` (dollari di «peso» a settimana). Vuoto o 0 =
    non sorvegliato: NON e' un tetto a zero, che vorrebbe dire «qualunque
    uso e' troppo».
    """
    user = request.user  # type: ignore[attr-defined]
    if not user.is_admin:
        return jsonify({"error": "forbidden"}), 403
    data = request.get_json(force=True, silent=True) or {}
    grezzo = data.get("cap_usd")
    try:
        usd = float(grezzo) if grezzo not in (None, "", "0", 0) else 0.0
    except (TypeError, ValueError):
        return jsonify({"error": "cap_usd non valido"}), 400
    if usd < 0:
        return jsonify({"error": "cap_usd non valido"}), 400
    micro = int(round(usd * 1_000_000)) if usd > 0 else None
    storage.imposta_tetto_settimanale(user_id, micro)
    return jsonify({"ok": True, "cap_micro": micro})


@app.patch("/api/admin/users/<int:user_id>/suspend")
@login_required_api
def api_admin_users_suspend(user_id):
    user = request.user  # type: ignore[attr-defined]
    if not user.is_admin:
        return jsonify({"error": "forbidden"}), 403
    target = storage.get_user_by_id(user_id)
    if target is None:
        return jsonify({"error": "utente non trovato"}), 404
    if target.id == user.id:
        return jsonify({"error": "non puoi disattivare il tuo stesso utente"}), 400
    data = request.get_json(silent=True) or {}
    suspended = bool(data.get("suspended"))
    storage.set_user_suspended(target.id, suspended)
    log.info("admin %s %s user %s", user.username,
             "suspended" if suspended else "reactivated", target.username)
    return jsonify({"ok": True, "suspended": suspended})


@app.delete("/api/admin/users/<int:user_id>")
@login_required_api
def api_admin_users_delete(user_id):
    user = request.user  # type: ignore[attr-defined]
    if not user.is_admin:
        return jsonify({"error": "forbidden"}), 403
    target = storage.get_user_by_id(user_id)
    if target is None:
        return jsonify({"error": "utente non trovato"}), 404
    if target.id == user.id:
        return jsonify({"error": "non puoi eliminare il tuo stesso utente"}), 400
    ok = storage.delete_user(target.username)
    if not ok:
        return jsonify({"error": "errore eliminazione"}), 500
    log.info("admin %s deleted user %s", user.username, target.username)
    return jsonify({"ok": True})


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
        "download": getattr(c, "source_file", "") or None,
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
    {% if c.source_file %}<a class="badge external" href="/api/precedent-file?f={{ c.source_file | urlencode }}">📎 Shkarko vendimin</a>{% endif %}
  </div>

  <div id="validity-box" style="margin:2px 0 22px">
    <button id="validity-btn" style="background:#1a1a1a;border:1px solid #c9a24d;color:#e8dcb0;padding:9px 15px;border-radius:8px;cursor:pointer;font-size:14px;font-weight:600">&#128269; Kontrollo nëse është ende në fuqi</button>
    <div id="validity-result" style="margin-top:12px"></div>
  </div>
  <script>
    (function(){
      var btn=document.getElementById("validity-btn"),out=document.getElementById("validity-result");
      if(!btn)return;
      btn.onclick=async function(){
        btn.disabled=true;
        out.innerHTML='<em style="color:#9a9a9a">Po kontrolloj vendimet e mëvonshme\u2026 (~15s)</em>';
        try{
          var r=await fetch("/api/decision-validity",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({id:{{ c.id }}})});
          var d=await r.json();
          if(!r.ok)throw new Error(d.error||("HTTP "+r.status));
          var col={ne_fuqi:"#2f6a4e",tejkaluar:"#8a3b1d",kufizuar:"#8a6a1d",e_paqarte:"#444"}[d.status]||"#444";
          var h='<div style="border:1px solid '+col+';background:#141414;border-radius:8px;padding:12px 14px">'
            +'<div style="font-size:16px;font-weight:700;color:#e8e0c8">'+(d.icon||"")+" "+(d.label||d.status)
            +' <span style="font-size:12px;color:#9a9a9a">\u00b7 besueshmëri '+(d.confidence||0)+'%</span></div>';
          if(d.superseded_by)h+='<div style="margin-top:6px;color:#f2c1c1">\u21b3 '+d.superseded_by+"</div>";
          if(d.note)h+='<div style="margin-top:8px;color:#c8c8c8;line-height:1.5">'+d.note+"</div>";
          h+='<div style="margin-top:8px;font-size:11px;color:#777">Kontrolluar kundër '+(d.checked_against||0)+' vendimeve. Mbështetje informative \u2014 jo garanci ligjore.</div></div>';
          out.innerHTML=h;
        }catch(e){out.innerHTML='<span style="color:#f2c1c1">Gabim: '+e.message+"</span>";}
        finally{btn.disabled=false;}
      };
    })();
  </script>

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
