"""SQLite storage for users, cases and per-case messages.

The bot moved from a single-user session cookie to a multi-user model:
 * each `user` has their own login and their own set of legal cases;
 * each `case` is a standalone "new chat" for a specific legal problem —
   history and Claude Code session stay scoped to that case, so the model
   never mixes one citizen's divorce with another's labour dispute;
 * messages are persisted so a user can come back weeks later, re-open
   a case and keep working, or download the transcript as a record.

Stdlib sqlite3 only — no extra dependency. Database file location is
controlled by `APP_DB_PATH` in config.py (default `data/app.db`).
"""
from __future__ import annotations

import json
import sqlite3
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

from .config import APP_DB_PATH
from .logging_utils import get_logger

log = get_logger(__name__)


SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    username      TEXT UNIQUE NOT NULL COLLATE NOCASE,
    password_hash TEXT NOT NULL,
    is_admin      INTEGER NOT NULL DEFAULT 0,
    created_at    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS cases (
    id                TEXT PRIMARY KEY,
    user_id           INTEGER NOT NULL,
    title             TEXT NOT NULL,
    claude_session_id TEXT,
    created_at        TEXT NOT NULL,
    updated_at        TEXT NOT NULL,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_cases_user ON cases(user_id, updated_at DESC);

CREATE TABLE IF NOT EXISTS messages (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    case_id         TEXT NOT NULL,
    role            TEXT NOT NULL,          -- 'user' or 'assistant'
    content         TEXT NOT NULL,
    kind            TEXT,                   -- 'answer' | 'followup' | 'error' | 'retrieval_only'
    articles_json   TEXT,                   -- JSON-serialised retrieved articles (assistant only)
    precedents_json TEXT,                   -- JSON-serialised retrieved precedents (assistant only)
    created_at      TEXT NOT NULL,
    FOREIGN KEY (case_id) REFERENCES cases(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_messages_case ON messages(case_id, id);
"""


def _utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ── connection management ───────────────────────────────────────────────────

def _connect(db_path: Path = APP_DB_PATH) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path, detect_types=sqlite3.PARSE_DECLTYPES)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn


def init_db(db_path: Path = APP_DB_PATH) -> None:
    """Create tables if they don't exist. Idempotent."""
    with _connect(db_path) as conn:
        conn.executescript(SCHEMA)
        conn.commit()
    log.info("app db ready at %s", db_path)


@contextmanager
def db() -> Iterator[sqlite3.Connection]:
    """Short-lived connection context — commits on clean exit, rolls back otherwise."""
    conn = _connect()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


# ── dataclasses (thin wrappers around rows) ─────────────────────────────────

@dataclass
class User:
    id: int
    username: str
    is_admin: bool
    created_at: str


@dataclass
class Case:
    id: str
    user_id: int
    title: str
    claude_session_id: str | None
    created_at: str
    updated_at: str


@dataclass
class Message:
    id: int
    case_id: str
    role: str
    content: str
    kind: str | None
    articles: list
    precedents: list
    created_at: str


def _user_from_row(r: sqlite3.Row) -> User:
    return User(id=r["id"], username=r["username"],
                is_admin=bool(r["is_admin"]), created_at=r["created_at"])


def _case_from_row(r: sqlite3.Row) -> Case:
    return Case(id=r["id"], user_id=r["user_id"], title=r["title"],
                claude_session_id=r["claude_session_id"],
                created_at=r["created_at"], updated_at=r["updated_at"])


def _message_from_row(r: sqlite3.Row) -> Message:
    return Message(
        id=r["id"], case_id=r["case_id"], role=r["role"],
        content=r["content"], kind=r["kind"],
        articles=json.loads(r["articles_json"]) if r["articles_json"] else [],
        precedents=json.loads(r["precedents_json"]) if r["precedents_json"] else [],
        created_at=r["created_at"],
    )


# ── users ───────────────────────────────────────────────────────────────────

def create_user(username: str, password_hash: str, is_admin: bool = False) -> User:
    username = username.strip()
    if not username:
        raise ValueError("username cannot be empty")
    now = _utcnow()
    with db() as conn:
        cur = conn.execute(
            "INSERT INTO users (username, password_hash, is_admin, created_at) "
            "VALUES (?, ?, ?, ?)",
            (username, password_hash, int(is_admin), now),
        )
        uid = cur.lastrowid
    log.info("created user %r (id=%d, admin=%s)", username, uid, is_admin)
    return User(id=uid, username=username, is_admin=is_admin, created_at=now)


def get_user_by_username(username: str) -> User | None:
    with db() as conn:
        row = conn.execute(
            "SELECT id, username, is_admin, created_at FROM users "
            "WHERE username = ? COLLATE NOCASE",
            (username.strip(),),
        ).fetchone()
    return _user_from_row(row) if row else None


def get_user_password_hash(username: str) -> str | None:
    with db() as conn:
        row = conn.execute(
            "SELECT password_hash FROM users WHERE username = ? COLLATE NOCASE",
            (username.strip(),),
        ).fetchone()
    return row["password_hash"] if row else None


def get_user_by_id(user_id: int) -> User | None:
    with db() as conn:
        row = conn.execute(
            "SELECT id, username, is_admin, created_at FROM users WHERE id = ?",
            (user_id,),
        ).fetchone()
    return _user_from_row(row) if row else None


def list_users() -> list[User]:
    with db() as conn:
        rows = conn.execute(
            "SELECT id, username, is_admin, created_at FROM users "
            "ORDER BY id ASC"
        ).fetchall()
    return [_user_from_row(r) for r in rows]


def delete_user(username: str) -> bool:
    with db() as conn:
        cur = conn.execute(
            "DELETE FROM users WHERE username = ? COLLATE NOCASE",
            (username.strip(),),
        )
        return cur.rowcount > 0


def set_password_hash(username: str, password_hash: str) -> bool:
    with db() as conn:
        cur = conn.execute(
            "UPDATE users SET password_hash = ? WHERE username = ? COLLATE NOCASE",
            (password_hash, username.strip()),
        )
        return cur.rowcount > 0


def count_users() -> int:
    with db() as conn:
        row = conn.execute("SELECT COUNT(*) AS n FROM users").fetchone()
    return int(row["n"])


# ── cases ───────────────────────────────────────────────────────────────────

def create_case(user_id: int, title: str) -> Case:
    title = (title or "").strip() or "Rast pa titull"
    case_id = uuid.uuid4().hex
    now = _utcnow()
    with db() as conn:
        conn.execute(
            "INSERT INTO cases (id, user_id, title, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (case_id, user_id, title, now, now),
        )
    return Case(id=case_id, user_id=user_id, title=title,
                claude_session_id=None, created_at=now, updated_at=now)


def get_case(case_id: str, user_id: int) -> Case | None:
    """Fetch a case only if it belongs to `user_id` (defence in depth)."""
    with db() as conn:
        row = conn.execute(
            "SELECT * FROM cases WHERE id = ? AND user_id = ?",
            (case_id, user_id),
        ).fetchone()
    return _case_from_row(row) if row else None


def list_cases(user_id: int) -> list[Case]:
    with db() as conn:
        rows = conn.execute(
            "SELECT * FROM cases WHERE user_id = ? "
            "ORDER BY updated_at DESC",
            (user_id,),
        ).fetchall()
    return [_case_from_row(r) for r in rows]


def update_case_claude_session(case_id: str, user_id: int, session_id: str | None) -> None:
    with db() as conn:
        conn.execute(
            "UPDATE cases SET claude_session_id = ?, updated_at = ? "
            "WHERE id = ? AND user_id = ?",
            (session_id, _utcnow(), case_id, user_id),
        )


def rename_case(case_id: str, user_id: int, new_title: str) -> bool:
    new_title = (new_title or "").strip()
    if not new_title:
        return False
    with db() as conn:
        cur = conn.execute(
            "UPDATE cases SET title = ?, updated_at = ? "
            "WHERE id = ? AND user_id = ?",
            (new_title, _utcnow(), case_id, user_id),
        )
        return cur.rowcount > 0


def delete_case(case_id: str, user_id: int) -> bool:
    with db() as conn:
        cur = conn.execute(
            "DELETE FROM cases WHERE id = ? AND user_id = ?",
            (case_id, user_id),
        )
        return cur.rowcount > 0


def touch_case(case_id: str, user_id: int) -> None:
    with db() as conn:
        conn.execute(
            "UPDATE cases SET updated_at = ? WHERE id = ? AND user_id = ?",
            (_utcnow(), case_id, user_id),
        )


# ── messages ────────────────────────────────────────────────────────────────

def add_message(
    case_id: str,
    role: str,
    content: str,
    *,
    kind: str | None = None,
    articles: list | None = None,
    precedents: list | None = None,
) -> Message:
    now = _utcnow()
    articles_json = json.dumps(articles, ensure_ascii=False) if articles else None
    precedents_json = json.dumps(precedents, ensure_ascii=False) if precedents else None
    with db() as conn:
        cur = conn.execute(
            "INSERT INTO messages (case_id, role, content, kind, "
            "articles_json, precedents_json, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (case_id, role, content, kind, articles_json, precedents_json, now),
        )
        mid = cur.lastrowid
        conn.execute("UPDATE cases SET updated_at = ? WHERE id = ?", (now, case_id))
    return Message(
        id=mid, case_id=case_id, role=role, content=content, kind=kind,
        articles=articles or [], precedents=precedents or [], created_at=now,
    )


def list_messages(case_id: str) -> list[Message]:
    with db() as conn:
        rows = conn.execute(
            "SELECT * FROM messages WHERE case_id = ? ORDER BY id ASC",
            (case_id,),
        ).fetchall()
    return [_message_from_row(r) for r in rows]


def conversation_history(case_id: str, max_turns: int = 20) -> list[dict]:
    """Return the last N user+assistant turns in the `role`/`content` shape
    that `SuperAvvocato.answer(history=...)` expects."""
    msgs = list_messages(case_id)
    pruned = msgs[-(max_turns * 2):]
    return [{"role": m.role, "content": m.content} for m in pruned]
