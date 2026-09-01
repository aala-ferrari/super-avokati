"""Authentication helpers: password hashing + Flask session decorators.

Passwords are hashed with werkzeug's PBKDF2 (already a Flask transitive
dependency — no new package pulled in). The Flask cookie holds only the
user id; server-side look-up enforces authorisation on every request.
"""
from __future__ import annotations

from datetime import UTC, datetime
from functools import wraps

from flask import jsonify, redirect, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

from . import storage
from .logging_utils import get_logger

log = get_logger(__name__)


def hash_password(plain: str) -> str:
    """PBKDF2-SHA256 — slow on purpose so brute force is expensive."""
    return generate_password_hash(plain, method="pbkdf2:sha256", salt_length=16)


def verify_password(plain: str, stored_hash: str) -> bool:
    try:
        return check_password_hash(stored_hash, plain)
    except ValueError:
        # malformed hash — treat as failure, never crash the login endpoint
        return False


def authenticate(username: str, password: str) -> storage.User | None:
    """Return the user if credentials are valid, else None. Never reveals
    which of username/password was wrong — same response either way."""
    stored = storage.get_user_password_hash(username)
    if stored and verify_password(password, stored):
        user = storage.get_user_by_username(username)
        reason = storage.access_block_reason(user)
        if reason:
            log.info("login refused for %r: %s", username, reason)
            return None
        return user
    return None


def login_reason(username: str, password: str) -> str | None:
    """If the password is valid but access is blocked, return the reason
    (suspended / demo_expired / plan_expired) so the login UI can show a clear
    message. Returns None on wrong password (no info leak) or when access is OK."""
    stored = storage.get_user_password_hash(username)
    if not (stored and verify_password(password, stored)):
        return None
    return storage.access_block_reason(storage.get_user_by_username(username))


def current_user() -> storage.User | None:
    uid = session.get("user_id")
    if not uid:
        return None
    user = storage.get_user_by_id(uid)
    # Enforce on every request: an active session is cut off the moment the
    # subscription/demo expires or the account is suspended (admin exempt).
    if user is not None and storage.access_block_reason(user):
        return None
    return user


def current_firm() -> storage.Firm | None:
    """Active workspace for the logged-in user. None when not authenticated."""
    uid = session.get("user_id")
    if not uid:
        return None
    return storage.get_active_firm(uid)


def current_role(firm_id: int | None = None) -> str | None:
    """Role of the current user in the given (or active) firm. None if not a member."""
    user = current_user()
    if user is None:
        return None
    if firm_id is None:
        firm = current_firm()
        if firm is None:
            return None
        firm_id = firm.id
    return storage.get_user_role_in_firm(user.id, firm_id)


def login_user(user: storage.User) -> None:
    session.clear()
    session["user_id"] = user.id
    session.permanent = True


def logout_user() -> None:
    session.clear()


# ── decorators ──────────────────────────────────────────────────────────────

def _arm_request_jurisdiction(user) -> None:
    """Rende disponibile la giurisdizione della sessione a TUTTI i moduli.

    Va chiamata quando l'utente e gia noto: un before_request girerebbe prima
    e vedrebbe request.user assente, facendo ricadere ogni strumento su AL."""
    try:
        from flask import session
        from . import storage as _storage, brain as _brain
        allowed = _storage.user_jurisdictions(user)
        chosen = (session.get("jurisdiction") or "").upper()
        if chosen not in allowed:
            chosen = "AL" if "AL" in allowed else sorted(allowed)[0]
        _brain.set_request_jurisdiction(chosen)
        # Chi sta chiedendo: stesso posto, stesso momento. Qui l'utente e'
        # gia' noto (un before_request girerebbe troppo presto).
        _brain.set_request_user(getattr(user, "id", None))
    except Exception:  # noqa: BLE001 - non deve mai bloccare la richiesta
        pass


def login_required_api(fn):
    """For JSON APIs — returns 401 JSON when unauthenticated.

    Injects request.user, request.firm (active workspace) and request.role
    (the user's role in that firm). All endpoints that operate on cases or
    members can rely on these without re-querying.
    """
    @wraps(fn)
    def wrapper(*args, **kwargs):
        user = current_user()
        if user is None:
            return jsonify({"error": "unauthorized"}), 401
        firm = current_firm()
        request.user = user  # type: ignore[attr-defined]
        _arm_request_jurisdiction(user)
        request.firm = firm  # type: ignore[attr-defined]
        request.role = (storage.get_user_role_in_firm(user.id, firm.id)
                        if firm else None)  # type: ignore[attr-defined]
        # V9.2 — bump last_active for the admin online-users dashboard.
        # Try/except so a transient DB hiccup never blocks the request.
        try:
            storage.update_user_last_active(user.id)
        except Exception:
            pass
        return fn(*args, **kwargs)
    return wrapper


def login_required_page(fn):
    """For HTML pages — redirects to /login when unauthenticated."""
    @wraps(fn)
    def wrapper(*args, **kwargs):
        user = current_user()
        if user is None:
            return redirect(url_for("login_page"))
        firm = current_firm()
        request.user = user  # type: ignore[attr-defined]
        _arm_request_jurisdiction(user)
        request.firm = firm  # type: ignore[attr-defined]
        request.role = (storage.get_user_role_in_firm(user.id, firm.id)
                        if firm else None)  # type: ignore[attr-defined]
        try:
            storage.update_user_last_active(user.id)
        except Exception:
            pass
        return fn(*args, **kwargs)
    return wrapper


def require_permission(perm: str):
    """Gate an API endpoint by a role-permission key (storage.ROLE_PERMISSIONS).

    Use *after* @login_required_api so request.role is set::

        @app.post("/api/firm/members")
        @login_required_api
        @require_permission("manage_members")
        def add_member(): ...
    """
    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            role = getattr(request, "role", None)
            allowed = storage.ROLE_PERMISSIONS.get(role or "", {}).get(perm, False)
            if not allowed:
                return jsonify({
                    "error": "forbidden",
                    "needed": perm,
                    "your_role": role,
                }), 403
            return fn(*args, **kwargs)
        return wrapper
    return decorator
