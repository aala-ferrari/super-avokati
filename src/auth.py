"""Authentication helpers: password hashing + Flask session decorators.

Passwords are hashed with werkzeug's PBKDF2 (already a Flask transitive
dependency — no new package pulled in). The Flask cookie holds only the
user id; server-side look-up enforces authorisation on every request.
"""
from __future__ import annotations

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
        return storage.get_user_by_username(username)
    return None


def current_user() -> storage.User | None:
    uid = session.get("user_id")
    if not uid:
        return None
    return storage.get_user_by_id(uid)


def login_user(user: storage.User) -> None:
    session.clear()
    session["user_id"] = user.id
    session.permanent = True


def logout_user() -> None:
    session.clear()


# ── decorators ──────────────────────────────────────────────────────────────

def login_required_api(fn):
    """For JSON APIs — returns 401 JSON when unauthenticated."""
    @wraps(fn)
    def wrapper(*args, **kwargs):
        user = current_user()
        if user is None:
            return jsonify({"error": "unauthorized"}), 401
        request.user = user  # type: ignore[attr-defined]
        return fn(*args, **kwargs)
    return wrapper


def login_required_page(fn):
    """For HTML pages — redirects to /login when unauthenticated."""
    @wraps(fn)
    def wrapper(*args, **kwargs):
        user = current_user()
        if user is None:
            return redirect(url_for("login_page"))
        request.user = user  # type: ignore[attr-defined]
        return fn(*args, **kwargs)
    return wrapper
