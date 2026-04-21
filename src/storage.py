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
    timeline_json   TEXT,                   -- JSON-serialised timeline (anchors + deadlines)
    comparison_json TEXT,                   -- JSON-serialised precedent comparison (winners vs losers)
    missing_facts_json TEXT,                -- JSON-serialised missing-facts questions
    premortem_json  TEXT,                   -- JSON-serialised pre-mortem risks
    distinguishing_json TEXT,                -- JSON-serialised distinguishing of adverse precedents
    evidence_map_json TEXT,                  -- JSON-serialised burden-of-proof map
    created_at      TEXT NOT NULL,
    FOREIGN KEY (case_id) REFERENCES cases(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_messages_case ON messages(case_id, id);

CREATE TABLE IF NOT EXISTS documents (
    id             TEXT PRIMARY KEY,           -- uuid hex, doubles as storage filename stem
    case_id        TEXT NOT NULL,
    filename       TEXT NOT NULL,              -- original filename as uploaded
    ext            TEXT NOT NULL,              -- lowercased extension including the dot
    mimetype       TEXT NOT NULL,
    size_bytes     INTEGER NOT NULL,
    storage_path   TEXT NOT NULL,              -- absolute path on disk
    status         TEXT NOT NULL,              -- 'pending' | 'ready' | 'error'
    error          TEXT,                       -- set when status='error'
    extracted_text TEXT,                       -- full OCR/text-layer output
    doc_type       TEXT,                       -- AI-classified type (vendim, kontratë, padi, etc.)
    summary        TEXT,                       -- AI-generated short summary
    key_facts_json TEXT,                       -- JSON array of bullet strings (dates, parties, sums)
    created_at     TEXT NOT NULL,
    FOREIGN KEY (case_id) REFERENCES cases(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_documents_case ON documents(case_id, created_at);
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
    """Create tables if they don't exist, then run additive migrations.

    We never rebuild tables — only add nullable columns. SQLite's ALTER
    TABLE is limited but ADD COLUMN is safe and idempotent (we guard with
    PRAGMA table_info). Old rows get NULL for the new column, which our
    readers already tolerate.
    """
    with _connect(db_path) as conn:
        conn.executescript(SCHEMA)
        _add_column_if_missing(conn, "messages", "timeline_json", "TEXT")
        _add_column_if_missing(conn, "messages", "comparison_json", "TEXT")
        _add_column_if_missing(conn, "messages", "missing_facts_json", "TEXT")
        _add_column_if_missing(conn, "messages", "premortem_json", "TEXT")
        _add_column_if_missing(conn, "messages", "distinguishing_json", "TEXT")
        _add_column_if_missing(conn, "messages", "evidence_map_json", "TEXT")
        conn.commit()
    log.info("app db ready at %s", db_path)


def _add_column_if_missing(
    conn: sqlite3.Connection, table: str, column: str, coltype: str
) -> None:
    cols = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}
    if column not in cols:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {coltype}")
        log.info("migration: added %s.%s", table, column)


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
    timeline: dict | None
    comparison: dict | None
    missing_facts: dict | None
    premortem: dict | None
    distinguishing: dict | None
    evidence_map: dict | None
    created_at: str


def _user_from_row(r: sqlite3.Row) -> User:
    return User(id=r["id"], username=r["username"],
                is_admin=bool(r["is_admin"]), created_at=r["created_at"])


def _case_from_row(r: sqlite3.Row) -> Case:
    return Case(id=r["id"], user_id=r["user_id"], title=r["title"],
                claude_session_id=r["claude_session_id"],
                created_at=r["created_at"], updated_at=r["updated_at"])


def _message_from_row(r: sqlite3.Row) -> Message:
    # timeline_json / comparison_json are post-initial-schema columns — old
    # rows predate them, and sqlite3.Row raises on unknown keys, so we
    # probe defensively.
    keys = r.keys()
    timeline_raw = r["timeline_json"] if "timeline_json" in keys else None
    comparison_raw = r["comparison_json"] if "comparison_json" in keys else None
    missing_raw = r["missing_facts_json"] if "missing_facts_json" in keys else None
    premortem_raw = r["premortem_json"] if "premortem_json" in keys else None
    distinguishing_raw = r["distinguishing_json"] if "distinguishing_json" in keys else None
    evidence_map_raw = r["evidence_map_json"] if "evidence_map_json" in keys else None
    return Message(
        id=r["id"], case_id=r["case_id"], role=r["role"],
        content=r["content"], kind=r["kind"],
        articles=json.loads(r["articles_json"]) if r["articles_json"] else [],
        precedents=json.loads(r["precedents_json"]) if r["precedents_json"] else [],
        timeline=json.loads(timeline_raw) if timeline_raw else None,
        comparison=json.loads(comparison_raw) if comparison_raw else None,
        missing_facts=json.loads(missing_raw) if missing_raw else None,
        premortem=json.loads(premortem_raw) if premortem_raw else None,
        distinguishing=json.loads(distinguishing_raw) if distinguishing_raw else None,
        evidence_map=json.loads(evidence_map_raw) if evidence_map_raw else None,
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
    timeline: dict | None = None,
    comparison: dict | None = None,
    missing_facts: dict | None = None,
    premortem: dict | None = None,
    distinguishing: dict | None = None,
    evidence_map: dict | None = None,
) -> Message:
    now = _utcnow()
    articles_json = json.dumps(articles, ensure_ascii=False) if articles else None
    precedents_json = json.dumps(precedents, ensure_ascii=False) if precedents else None
    timeline_json = json.dumps(timeline, ensure_ascii=False) if timeline else None
    comparison_json = json.dumps(comparison, ensure_ascii=False) if comparison else None
    missing_json = json.dumps(missing_facts, ensure_ascii=False) if missing_facts else None
    premortem_json = json.dumps(premortem, ensure_ascii=False) if premortem else None
    distinguishing_json = (
        json.dumps(distinguishing, ensure_ascii=False) if distinguishing else None
    )
    evidence_map_json = (
        json.dumps(evidence_map, ensure_ascii=False) if evidence_map else None
    )
    with db() as conn:
        cur = conn.execute(
            "INSERT INTO messages (case_id, role, content, kind, "
            "articles_json, precedents_json, timeline_json, comparison_json, "
            "missing_facts_json, premortem_json, distinguishing_json, "
            "evidence_map_json, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (case_id, role, content, kind, articles_json, precedents_json,
             timeline_json, comparison_json, missing_json, premortem_json,
             distinguishing_json, evidence_map_json, now),
        )
        mid = cur.lastrowid
        conn.execute("UPDATE cases SET updated_at = ? WHERE id = ?", (now, case_id))
    return Message(
        id=mid, case_id=case_id, role=role, content=content, kind=kind,
        articles=articles or [], precedents=precedents or [],
        timeline=timeline, comparison=comparison, missing_facts=missing_facts,
        premortem=premortem, distinguishing=distinguishing,
        evidence_map=evidence_map, created_at=now,
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


# ── documents (the case file / "dosja") ────────────────────────────────────

@dataclass
class Document:
    id: str
    case_id: str
    filename: str
    ext: str
    mimetype: str
    size_bytes: int
    storage_path: str
    status: str                 # pending | ready | error
    error: str | None
    extracted_text: str | None
    doc_type: str | None
    summary: str | None
    key_facts: list[str]
    created_at: str


def _document_from_row(r: sqlite3.Row) -> Document:
    return Document(
        id=r["id"], case_id=r["case_id"], filename=r["filename"], ext=r["ext"],
        mimetype=r["mimetype"], size_bytes=int(r["size_bytes"]),
        storage_path=r["storage_path"], status=r["status"], error=r["error"],
        extracted_text=r["extracted_text"], doc_type=r["doc_type"],
        summary=r["summary"],
        key_facts=json.loads(r["key_facts_json"]) if r["key_facts_json"] else [],
        created_at=r["created_at"],
    )


def create_document(
    *,
    case_id: str,
    filename: str,
    ext: str,
    mimetype: str,
    size_bytes: int,
    storage_path: str,
) -> Document:
    doc_id = uuid.uuid4().hex
    now = _utcnow()
    with db() as conn:
        conn.execute(
            "INSERT INTO documents (id, case_id, filename, ext, mimetype, "
            "size_bytes, storage_path, status, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, 'pending', ?)",
            (doc_id, case_id, filename, ext, mimetype, size_bytes, storage_path, now),
        )
        conn.execute("UPDATE cases SET updated_at = ? WHERE id = ?", (now, case_id))
    return Document(
        id=doc_id, case_id=case_id, filename=filename, ext=ext, mimetype=mimetype,
        size_bytes=size_bytes, storage_path=storage_path, status="pending",
        error=None, extracted_text=None, doc_type=None, summary=None,
        key_facts=[], created_at=now,
    )


def update_document_analysis(
    doc_id: str,
    *,
    extracted_text: str | None,
    doc_type: str | None,
    summary: str | None,
    key_facts: list[str] | None,
) -> None:
    with db() as conn:
        conn.execute(
            "UPDATE documents SET status='ready', error=NULL, "
            "extracted_text=?, doc_type=?, summary=?, key_facts_json=? "
            "WHERE id = ?",
            (
                extracted_text,
                doc_type,
                summary,
                json.dumps(key_facts, ensure_ascii=False) if key_facts else None,
                doc_id,
            ),
        )


def mark_document_error(doc_id: str, error: str) -> None:
    with db() as conn:
        conn.execute(
            "UPDATE documents SET status='error', error=? WHERE id = ?",
            (error[:500], doc_id),
        )


def list_documents(case_id: str) -> list[Document]:
    with db() as conn:
        rows = conn.execute(
            "SELECT * FROM documents WHERE case_id = ? ORDER BY created_at ASC",
            (case_id,),
        ).fetchall()
    return [_document_from_row(r) for r in rows]


def get_document(doc_id: str, case_id: str) -> Document | None:
    """Fetch a document but only if it belongs to `case_id` (defence in depth)."""
    with db() as conn:
        row = conn.execute(
            "SELECT * FROM documents WHERE id = ? AND case_id = ?",
            (doc_id, case_id),
        ).fetchone()
    return _document_from_row(row) if row else None


def count_documents(case_id: str) -> int:
    with db() as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS n FROM documents WHERE case_id = ?",
            (case_id,),
        ).fetchone()
    return int(row["n"])


def delete_document(doc_id: str, case_id: str) -> Document | None:
    """Delete a document row and return the previous row (so the caller can
    remove the file on disk). Returns None if the row didn't exist."""
    doc = get_document(doc_id, case_id)
    if doc is None:
        return None
    with db() as conn:
        conn.execute("DELETE FROM documents WHERE id = ?", (doc_id,))
    return doc
