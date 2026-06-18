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
import re
import sqlite3
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

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
    nullity_radar_json TEXT,                 -- JSON-serialised nullity + deadline radar
    urgency_radar_json TEXT,                 -- JSON-serialised urgency signals (top-of-page emergency panel)
    action_plan_json TEXT,                   -- JSON-serialised consolidated action plan (time-bucketed checklist)
    contradictions_json TEXT,                -- JSON-serialised cross-document contradiction report
    opponent_playbook_json TEXT,             -- JSON-serialised opponent playbook (V7.3 — two moves ahead)
    leverage_json   TEXT,                    -- JSON-serialised leverage map (V7.3 — pressure points short of trial)
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

-- V7.10 — calendar: agjenda for the lawyer.
-- Events are user-scoped; case_id is optional so a pure personal appointment
-- (client intake call, deposition prep) doesn't need to be tied to a case.
-- All timestamps are ISO-8601 UTC strings; the UI converts to local time.
CREATE TABLE IF NOT EXISTS events (
    id           TEXT PRIMARY KEY,           -- uuid hex
    user_id      INTEGER NOT NULL,
    case_id      TEXT,                        -- nullable: personal appt vs case event
    title        TEXT NOT NULL,
    description  TEXT,                        -- free text notes
    kind         TEXT NOT NULL,               -- 'takim' | 'seance' | 'afat' | 'dorëzim' | 'tjetër'
    starts_at    TEXT NOT NULL,               -- UTC ISO-8601
    ends_at      TEXT,                        -- optional; NULL → point event
    all_day      INTEGER NOT NULL DEFAULT 0,  -- 1 if event spans a whole day
    location     TEXT,
    color        TEXT,                        -- optional hex override; UI has default per kind
    source       TEXT NOT NULL DEFAULT 'manual',  -- 'manual' | 'dossier'
    source_ref   TEXT,                        -- when source='dossier': the dedup key
    done         INTEGER NOT NULL DEFAULT 0,  -- 1 once the deadline/meeting is past and checked off
    created_at   TEXT NOT NULL,
    updated_at   TEXT NOT NULL,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
    FOREIGN KEY (case_id) REFERENCES cases(id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_events_user_time ON events(user_id, starts_at);
CREATE INDEX IF NOT EXISTS idx_events_case ON events(case_id, starts_at);
CREATE UNIQUE INDEX IF NOT EXISTS idx_events_source_dedup
    ON events(user_id, source_ref) WHERE source_ref IS NOT NULL;

CREATE TABLE IF NOT EXISTS reminders (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id       TEXT NOT NULL,
    offset_minutes INTEGER NOT NULL,    -- positive = before event; e.g. 1440 = 1 day before
    channel        TEXT NOT NULL,       -- 'telegram' | 'inapp'
    fire_at        TEXT NOT NULL,       -- UTC ISO-8601, denormalised for efficient polling
    sent_at        TEXT,                -- NULL until delivered
    error          TEXT,                -- last delivery error, if any
    created_at     TEXT NOT NULL,
    FOREIGN KEY (event_id) REFERENCES events(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_reminders_pending ON reminders(sent_at, fire_at)
    WHERE sent_at IS NULL;

-- V7.11 — new professional features.
-- stress_tests: pre-udienza red-team simulations run per-case (feature ①).
-- Each row stores the hypothesis the lawyer submitted + the structured
-- JSON result (counter_brief, weaknesses, cross_exam, objections, etc).
CREATE TABLE IF NOT EXISTS stress_tests (
    id          TEXT PRIMARY KEY,
    case_id     TEXT NOT NULL,
    user_id     INTEGER NOT NULL,
    hypothesis  TEXT NOT NULL,
    result_json TEXT NOT NULL,          -- structured red-team output
    created_at  TEXT NOT NULL,
    FOREIGN KEY (case_id) REFERENCES cases(id) ON DELETE CASCADE,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_stress_tests_case ON stress_tests(case_id, created_at DESC);

-- citation_audits: auditor delle citazioni (feature ②). Each audit stores
-- the source text submitted + the JSON list of findings (citation, status,
-- verdict, notes, correct_version).
CREATE TABLE IF NOT EXISTS citation_audits (
    id          TEXT PRIMARY KEY,
    case_id     TEXT,                    -- nullable: may audit a free text
    user_id     INTEGER NOT NULL,
    source_text TEXT NOT NULL,
    result_json TEXT NOT NULL,
    created_at  TEXT NOT NULL,
    FOREIGN KEY (case_id) REFERENCES cases(id) ON DELETE SET NULL,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_citation_audits_user ON citation_audits(user_id, created_at DESC);

-- drafted_acts: fabbrica degli atti processuali (feature ③). Stores the
-- brief + final draft text + doc metadata. docx is generated on demand.
CREATE TABLE IF NOT EXISTS drafted_acts (
    id          TEXT PRIMARY KEY,
    case_id     TEXT,
    user_id     INTEGER NOT NULL,
    act_type    TEXT NOT NULL,           -- padi | kerkese | ankim | memorie | ...
    brief       TEXT NOT NULL,           -- lawyer's natural-language description
    draft_text  TEXT NOT NULL,           -- the generated act body
    meta_json   TEXT,                    -- parties, court, petitum, cited nene
    created_at  TEXT NOT NULL,
    FOREIGN KEY (case_id) REFERENCES cases(id) ON DELETE SET NULL,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_drafted_acts_user ON drafted_acts(user_id, created_at DESC);

-- case_timelines: V7.12 feature A — chronological reconstruction of a case.
-- One row per case (latest build replaces previous). result_json holds:
--   { events: [{date, time?, type, summary, parties, source_doc_id,
--               source_excerpt, confidence}], contradictions: [...],
--     gaps: [...], generated_at }.
-- We dedupe on case_id with INSERT OR REPLACE so re-running just refreshes.
CREATE TABLE IF NOT EXISTS case_timelines (
    case_id     TEXT PRIMARY KEY,
    user_id     INTEGER NOT NULL,
    result_json TEXT NOT NULL,
    doc_count   INTEGER NOT NULL,
    event_count INTEGER NOT NULL,
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL,
    FOREIGN KEY (case_id) REFERENCES cases(id) ON DELETE CASCADE,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_case_timelines_user ON case_timelines(user_id, updated_at DESC);

-- adversarial_loops: V7.12 feature C — multi-round red team where the AI
-- argues both sides until convergence. Each row is one full session.
CREATE TABLE IF NOT EXISTS adversarial_loops (
    id          TEXT PRIMARY KEY,
    case_id     TEXT NOT NULL,
    user_id     INTEGER NOT NULL,
    hypothesis  TEXT NOT NULL,
    rounds_json TEXT NOT NULL,              -- list of {round, attacker, attack, defender_reply, residual_risk}
    summary_json TEXT NOT NULL,             -- final converged plan + remaining weaknesses
    round_count INTEGER NOT NULL,
    created_at  TEXT NOT NULL,
    FOREIGN KEY (case_id) REFERENCES cases(id) ON DELETE CASCADE,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_adversarial_loops_case ON adversarial_loops(case_id, created_at DESC);

-- strategy_compasses: V7.12 feature B — branching decision tree for a case.
-- tree_json holds the full nested structure { root, branches[], leaves[] }
-- with probabilities, costs, recommended moves; meta_json stores stats.
CREATE TABLE IF NOT EXISTS strategy_compasses (
    id          TEXT PRIMARY KEY,
    case_id     TEXT NOT NULL,
    user_id     INTEGER NOT NULL,
    objective   TEXT NOT NULL,              -- lawyer's goal in own words
    tree_json   TEXT NOT NULL,
    meta_json   TEXT,                       -- node count, max depth, KB cases used
    created_at  TEXT NOT NULL,
    FOREIGN KEY (case_id) REFERENCES cases(id) ON DELETE CASCADE,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_strategy_case ON strategy_compasses(case_id, created_at DESC);

-- ── V8.0 — Multi-tenancy (studio legale) ─────────────────────────────────
-- A firm is the container. Each user belongs to ≥1 firm via firm_members,
-- with a role that gates permissions (owner can do everything, praticante
-- can only draft, segretaria handles scheduling, etc.). Existing solo
-- users get a personal firm auto-created at migration time.
CREATE TABLE IF NOT EXISTS firms (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL,
    slug        TEXT UNIQUE NOT NULL COLLATE NOCASE,    -- /intake/<slug> public route
    owner_id    INTEGER NOT NULL,                       -- the founding member (user_id)
    is_personal INTEGER NOT NULL DEFAULT 0,             -- 1 = auto-created solo firm
    created_at  TEXT NOT NULL,
    FOREIGN KEY (owner_id) REFERENCES users(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS firm_members (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    firm_id   INTEGER NOT NULL,
    user_id   INTEGER NOT NULL,
    role      TEXT NOT NULL,                            -- 'owner'|'partner'|'lawyer'|'paralegal'|'assistant'
    status    TEXT NOT NULL DEFAULT 'active',           -- 'active'|'invited'|'removed'
    joined_at TEXT NOT NULL,
    UNIQUE(firm_id, user_id),
    FOREIGN KEY (firm_id) REFERENCES firms(id) ON DELETE CASCADE,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_firm_members_user ON firm_members(user_id, status);
CREATE INDEX IF NOT EXISTS idx_firm_members_firm ON firm_members(firm_id, status);

-- case_assignments: a case lives in a firm (cases.firm_id) and can have
-- N additional assignees on top of the case creator. The creator is the
-- implicit primary lawyer; assignments define the rest of the team.
CREATE TABLE IF NOT EXISTS case_assignments (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    case_id     TEXT NOT NULL,
    member_id   INTEGER NOT NULL,                       -- firm_members.id
    role_in_case TEXT NOT NULL DEFAULT 'collaborator',  -- 'lead'|'collaborator'|'reviewer'|'observer'
    assigned_at TEXT NOT NULL,
    UNIQUE(case_id, member_id),
    FOREIGN KEY (case_id) REFERENCES cases(id) ON DELETE CASCADE,
    FOREIGN KEY (member_id) REFERENCES firm_members(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_assignments_case ON case_assignments(case_id);
CREATE INDEX IF NOT EXISTS idx_assignments_member ON case_assignments(member_id);

-- case_parties: V8.0 — extracted parties (clients, opponents, witnesses)
-- per case. Used by the conflict-of-interest checker to detect "this
-- person was already on the other side of an old case."
CREATE TABLE IF NOT EXISTS case_parties (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    case_id   TEXT NOT NULL,
    firm_id   INTEGER NOT NULL,
    name      TEXT NOT NULL,                           -- normalised lowercase form for lookup
    display_name TEXT NOT NULL,                        -- original casing
    side      TEXT NOT NULL DEFAULT 'unknown',         -- 'client'|'opponent'|'witness'|'third'|'unknown'
    source    TEXT,                                    -- 'manual'|'extracted_title'|'extracted_msg'
    created_at TEXT NOT NULL,
    FOREIGN KEY (case_id) REFERENCES cases(id) ON DELETE CASCADE,
    FOREIGN KEY (firm_id) REFERENCES firms(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_parties_firm_name ON case_parties(firm_id, name);
CREATE INDEX IF NOT EXISTS idx_parties_case ON case_parties(case_id);

-- case_drafts: V8.1 — review loop. Junior member submits a draft (note,
-- atto, research) on a case → senior member approves / asks for changes
-- with an inline comment. Audit trail stays with the case.
CREATE TABLE IF NOT EXISTS case_drafts (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    case_id      TEXT NOT NULL,
    firm_id      INTEGER NOT NULL,
    author_id    INTEGER NOT NULL,
    title        TEXT NOT NULL,
    content      TEXT NOT NULL,
    kind         TEXT NOT NULL DEFAULT 'note',          -- 'note'|'atto'|'research'|'memo'
    status       TEXT NOT NULL DEFAULT 'pending',       -- 'pending'|'approved'|'needs_changes'
    reviewer_id  INTEGER,
    review_comment TEXT,
    reviewed_at  TEXT,
    created_at   TEXT NOT NULL,
    updated_at   TEXT NOT NULL,
    FOREIGN KEY (case_id) REFERENCES cases(id) ON DELETE CASCADE,
    FOREIGN KEY (firm_id) REFERENCES firms(id) ON DELETE CASCADE,
    FOREIGN KEY (author_id) REFERENCES users(id),
    FOREIGN KEY (reviewer_id) REFERENCES users(id)
);
CREATE INDEX IF NOT EXISTS idx_drafts_firm_status ON case_drafts(firm_id, status);
CREATE INDEX IF NOT EXISTS idx_drafts_case ON case_drafts(case_id);
CREATE INDEX IF NOT EXISTS idx_drafts_author ON case_drafts(author_id);

-- V8.3 — client portal. The citizen we represent gets a magic-link
-- (portal_token) to a read-only view of THEIR case: current stage,
-- upcoming hearings/deadlines, status updates the lawyer chose to share.
-- The token is the only credential — no login required, no PII stored
-- beyond name + optional phone/email for the lawyer's reference.
CREATE TABLE IF NOT EXISTS client_contacts (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    case_id        TEXT NOT NULL,
    firm_id        INTEGER NOT NULL,
    name           TEXT NOT NULL,
    phone          TEXT,
    email          TEXT,
    portal_token   TEXT UNIQUE NOT NULL,
    last_viewed_at TEXT,
    created_at     TEXT NOT NULL,
    FOREIGN KEY (case_id) REFERENCES cases(id) ON DELETE CASCADE,
    FOREIGN KEY (firm_id) REFERENCES firms(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_clients_case ON client_contacts(case_id);

-- V8.3 — client-visible updates. Separate from `messages` (lawyer↔AI
-- conversation): these are what the lawyer CURATES and shares with
-- the client. Either typed manually or produced by the jargon→qytetar
-- translator (kind='translation'/source_kind='ai_translate').
CREATE TABLE IF NOT EXISTS case_status_updates (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    case_id     TEXT NOT NULL,
    firm_id     INTEGER NOT NULL,
    author_id   INTEGER NOT NULL,
    body_sq     TEXT NOT NULL,                      -- plain Albanian for the client
    kind        TEXT NOT NULL DEFAULT 'status',     -- 'status'|'milestone'|'document_request'|'translation'
    source_kind TEXT,                               -- 'manual'|'ai_translate'|'stage_change'
    created_at  TEXT NOT NULL,
    FOREIGN KEY (case_id) REFERENCES cases(id) ON DELETE CASCADE,
    FOREIGN KEY (firm_id) REFERENCES firms(id) ON DELETE CASCADE,
    FOREIGN KEY (author_id) REFERENCES users(id)
);
CREATE INDEX IF NOT EXISTS idx_status_updates_case
    ON case_status_updates(case_id, created_at DESC);

-- V8.4 — contract review. The lawyer pastes a contract; AI returns a
-- semaforo (🟢/🟡/🔴) per clause + obligations + deadlines + GDPR-AL
-- flags. Persisted per-case so the lawyer can revisit the analysis or
-- export it as a memo for the client.
CREATE TABLE IF NOT EXISTS contract_reviews (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    case_id         TEXT NOT NULL,
    user_id         INTEGER NOT NULL,
    contract_label  TEXT,                          -- short label/title
    contract_kind   TEXT,                          -- 'qira'|'punës'|'tregtar'|...
    source_text     TEXT NOT NULL,                 -- the input contract
    result_json     TEXT NOT NULL,                 -- full structured AI output
    risk_score      INTEGER,                       -- 0-100, derived from clause levels
    created_at      TEXT NOT NULL,
    FOREIGN KEY (case_id) REFERENCES cases(id) ON DELETE CASCADE,
    FOREIGN KEY (user_id) REFERENCES users(id)
);
CREATE INDEX IF NOT EXISTS idx_contract_reviews_case
    ON contract_reviews(case_id, created_at DESC);

-- V8.5 — money layer. Track lawyer time per case (hours×rate), produce
-- invoices with line items. Albanian tariff is shipped as a Python const.
-- Amounts stored in cents to avoid float drift.
CREATE TABLE IF NOT EXISTS time_entries (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    case_id         TEXT NOT NULL,
    user_id         INTEGER NOT NULL,
    firm_id         INTEGER,
    entry_date      TEXT NOT NULL,                    -- 'YYYY-MM-DD' (UTC date)
    minutes         INTEGER NOT NULL,                 -- > 0
    description     TEXT NOT NULL,
    activity_kind   TEXT NOT NULL DEFAULT 'work',     -- 'work'|'hearing'|'meeting'|'travel'|'research'|'drafting'
    hourly_rate     INTEGER NOT NULL,                 -- cents per hour (EUR/ALL stored, currency separate)
    currency        TEXT NOT NULL DEFAULT 'EUR',
    billed_invoice_id INTEGER,                        -- NULL until billed; set when included on an invoice
    created_at      TEXT NOT NULL,
    FOREIGN KEY (case_id) REFERENCES cases(id) ON DELETE CASCADE,
    FOREIGN KEY (user_id) REFERENCES users(id),
    FOREIGN KEY (firm_id) REFERENCES firms(id) ON DELETE SET NULL,
    FOREIGN KEY (billed_invoice_id) REFERENCES invoices(id) ON DELETE SET NULL
);
CREATE INDEX IF NOT EXISTS idx_time_entries_case
    ON time_entries(case_id, entry_date DESC);
CREATE INDEX IF NOT EXISTS idx_time_entries_user
    ON time_entries(user_id, entry_date DESC);
CREATE INDEX IF NOT EXISTS idx_time_entries_unbilled
    ON time_entries(case_id, billed_invoice_id) WHERE billed_invoice_id IS NULL;

CREATE TABLE IF NOT EXISTS invoices (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    case_id       TEXT NOT NULL,
    firm_id       INTEGER,
    user_id       INTEGER NOT NULL,
    invoice_no    TEXT NOT NULL,                      -- 'INV-2026-0001' style
    client_name   TEXT NOT NULL,
    client_address TEXT,
    issue_date    TEXT NOT NULL,                      -- YYYY-MM-DD
    due_date      TEXT,
    currency      TEXT NOT NULL DEFAULT 'EUR',
    subtotal_cents INTEGER NOT NULL DEFAULT 0,
    vat_rate      INTEGER NOT NULL DEFAULT 0,         -- percent (0, 20 etc.)
    vat_cents     INTEGER NOT NULL DEFAULT 0,
    total_cents   INTEGER NOT NULL DEFAULT 0,
    status        TEXT NOT NULL DEFAULT 'draft',      -- 'draft'|'sent'|'paid'|'cancelled'
    notes         TEXT,
    line_items_json TEXT NOT NULL,                    -- JSON array of { description, minutes, rate_cents, amount_cents, kind }
    markdown      TEXT,                               -- rendered markdown for export
    created_at    TEXT NOT NULL,
    updated_at    TEXT NOT NULL,
    FOREIGN KEY (case_id) REFERENCES cases(id) ON DELETE CASCADE,
    FOREIGN KEY (firm_id) REFERENCES firms(id) ON DELETE SET NULL,
    FOREIGN KEY (user_id) REFERENCES users(id)
);
CREATE INDEX IF NOT EXISTS idx_invoices_case ON invoices(case_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_invoices_firm ON invoices(firm_id, created_at DESC);

-- V8.6 — agentic mode. The lawyer asks Super Avvocato to scan a case and
-- propose proactive actions (chase the client, draft a letter, request
-- documents). Each suggestion is stored so the lawyer can dismiss or
-- execute it; executed letter drafts go into auto_letters.
CREATE TABLE IF NOT EXISTS agent_suggestions (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    case_id     TEXT NOT NULL,
    user_id     INTEGER NOT NULL,
    kind        TEXT NOT NULL,                     -- 'followup_client'|'draft_letter'|'request_docs'|'precedent_alert'|'deadline_reminder'
    title       TEXT NOT NULL,                     -- short headline shown in the UI
    rationale   TEXT NOT NULL,                     -- why the agent thinks this matters
    payload_json TEXT,                             -- structured params (e.g. precedent IDs, draft kind, target_email)
    status      TEXT NOT NULL DEFAULT 'pending',   -- 'pending'|'dismissed'|'executed'
    executed_letter_id INTEGER,                    -- FK to auto_letters when executed
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL,
    FOREIGN KEY (case_id) REFERENCES cases(id) ON DELETE CASCADE,
    FOREIGN KEY (user_id) REFERENCES users(id),
    FOREIGN KEY (executed_letter_id) REFERENCES auto_letters(id) ON DELETE SET NULL
);
CREATE INDEX IF NOT EXISTS idx_agent_suggestions_case
    ON agent_suggestions(case_id, status, created_at DESC);

-- V8.6 — auto-drafted letters. Editable Albanian-language drafts ready
-- for the lawyer to review, copy and send. Stored so they can be
-- revisited and exported.
CREATE TABLE IF NOT EXISTS auto_letters (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    case_id     TEXT NOT NULL,
    user_id     INTEGER NOT NULL,
    kind        TEXT NOT NULL,                     -- 'client_followup'|'payment_reminder'|'court_followup'|'opponent_response'|'document_request'
    recipient   TEXT,                              -- name of intended recipient
    subject     TEXT,
    body_md     TEXT NOT NULL,                     -- the full draft (Albanian, markdown)
    notes       TEXT,
    status      TEXT NOT NULL DEFAULT 'draft',     -- 'draft'|'sent'|'archived'
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL,
    FOREIGN KEY (case_id) REFERENCES cases(id) ON DELETE CASCADE,
    FOREIGN KEY (user_id) REFERENCES users(id)
);
CREATE INDEX IF NOT EXISTS idx_auto_letters_case
    ON auto_letters(case_id, created_at DESC);

-- V8.7 — in-hearing mode. The lawyer dictates notes from court (or types
-- on a phone). Each note is a row; AI replies are stored with kind='ai_reply'
-- so the timeline can replay the whole hearing.
CREATE TABLE IF NOT EXISTS hearing_notes (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    case_id     TEXT NOT NULL,
    user_id     INTEGER NOT NULL,
    kind        TEXT NOT NULL DEFAULT 'note',       -- 'note'|'question'|'ai_reply'
    body_sq     TEXT NOT NULL,
    parent_id   INTEGER,                            -- ai_reply → question linkage
    created_at  TEXT NOT NULL,
    FOREIGN KEY (case_id) REFERENCES cases(id) ON DELETE CASCADE,
    FOREIGN KEY (user_id) REFERENCES users(id),
    FOREIGN KEY (parent_id) REFERENCES hearing_notes(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_hearing_notes_case
    ON hearing_notes(case_id, created_at DESC);

-- V8.9 — incoming leads. A citizen who hasn't yet engaged a lawyer fills out
-- a public intake form (web /intake/<firm_slug> or Telegram /intake) and
-- their problem lands here. The lawyer triages from the inbox and converts
-- promising ones to real cases.
CREATE TABLE IF NOT EXISTS leads (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    firm_id         INTEGER,                          -- target studio (NULL=open pool)
    source          TEXT NOT NULL,                    -- 'web'|'telegram'|'manual'
    contact_name    TEXT NOT NULL,
    contact_phone   TEXT,
    contact_email   TEXT,
    problem_text    TEXT NOT NULL,                    -- the citizen's own words
    ai_summary      TEXT,                             -- AI-derived 1-2 sentences
    ai_area         TEXT,                             -- 'familjare'|'pune'|'penale'|...
    ai_urgency      TEXT,                             -- 'low'|'medium'|'high'
    ai_missing      TEXT,                             -- JSON array of suggested follow-up questions
    telegram_chat_id INTEGER,                         -- if source=telegram
    status          TEXT NOT NULL DEFAULT 'new',      -- 'new'|'contacted'|'converted'|'rejected'
    converted_case_id TEXT,                           -- FK to cases.id when converted
    assignee_user_id INTEGER,                         -- which lawyer claimed it
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL,
    FOREIGN KEY (firm_id) REFERENCES firms(id) ON DELETE SET NULL,
    FOREIGN KEY (converted_case_id) REFERENCES cases(id) ON DELETE SET NULL,
    FOREIGN KEY (assignee_user_id) REFERENCES users(id) ON DELETE SET NULL
);
CREATE INDEX IF NOT EXISTS idx_leads_firm ON leads(firm_id, status, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_leads_status ON leads(status, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_leads_telegram ON leads(telegram_chat_id);

-- V8.11 Citation Shield V2 — provenance pack per response.
-- One row per LLM response from /api/ask. Used by:
--  * the "Provenance" UI panel (lawyer reads sources, hashes, KB version)
--  * PDF export per case dossier
--  * V8.12 EU AI Act audit log query path
-- Append-only by design: we never UPDATE/DELETE provenance rows; if a row
-- needs amending, write a new row that supersedes it.
CREATE TABLE IF NOT EXISTS provenance_packs (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    response_id     TEXT NOT NULL,                     -- short hash from citation_shield
    case_id         TEXT,                              -- nullable for non-case responses
    user_id         INTEGER NOT NULL,
    jurisdiction    TEXT NOT NULL DEFAULT 'AL',        -- 'AL'|'IT'|'EU'|...
    kb_version      TEXT NOT NULL,                     -- KB hash at retrieval time
    model           TEXT NOT NULL,                     -- 'claude-opus-4-8' etc
    system_prompt_version TEXT,                        -- short hash of system prompt
    prompt_hash     TEXT NOT NULL,
    response_hash   TEXT NOT NULL,
    confidence      REAL NOT NULL,                     -- 0.0–1.0
    refused         INTEGER NOT NULL DEFAULT 0,        -- 1 = refusal preamble applied
    payload_json    TEXT NOT NULL,                     -- full ProvenancePack as JSON
    created_at      TEXT NOT NULL,
    FOREIGN KEY (case_id) REFERENCES cases(id) ON DELETE SET NULL,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_prov_case ON provenance_packs(case_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_prov_user ON provenance_packs(user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_prov_response ON provenance_packs(response_id);

-- V8.12 EU AI Act art. 12 — automated logging for high-risk AI systems.
-- One row per LLM call (any callsite that uses backends.complete or
-- complete_stream). Append-only by design: never UPDATE, never DELETE
-- automatically. Operator can run a retention sweep manually if local
-- regulation demands one. Schema covers Annex IV traceability minimum:
--   * input/output content (hashed for privacy by default; raw stored
--     only if AUDIT_STORE_RAW=1 in env)
--   * model + tier + parameters
--   * latency + token usage if available
--   * who called (user_id) and from what feature (callsite)
--   * outcome (success / error class)
CREATE TABLE IF NOT EXISTS ai_audit_log (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp       TEXT NOT NULL,
    user_id         INTEGER,
    case_id         TEXT,
    callsite        TEXT NOT NULL,                    -- e.g. 'brain.compose'|'web.lead_intake'|'documents.analysis'
    backend         TEXT NOT NULL,                    -- 'claude_code'|'anthropic'|'gemini'
    model           TEXT NOT NULL,                    -- exact model id used
    tier            TEXT NOT NULL,                    -- 'default'|'medium'|'fast'
    prompt_hash     TEXT NOT NULL,                    -- SHA-256[:16] of system+user
    response_hash   TEXT,                             -- SHA-256[:16] of output
    prompt_raw      TEXT,                             -- stored only if AUDIT_STORE_RAW=1
    response_raw    TEXT,                             -- stored only if AUDIT_STORE_RAW=1
    latency_ms      INTEGER,
    input_tokens    INTEGER,
    output_tokens   INTEGER,
    outcome         TEXT NOT NULL DEFAULT 'success',  -- 'success'|'error'|'refusal'
    error_class     TEXT,
    extra_json      TEXT,                             -- arbitrary callsite-specific payload
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE SET NULL,
    FOREIGN KEY (case_id) REFERENCES cases(id) ON DELETE SET NULL
);
CREATE INDEX IF NOT EXISTS idx_audit_ts ON ai_audit_log(timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_audit_user ON ai_audit_log(user_id, timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_audit_case ON ai_audit_log(case_id, timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_audit_callsite ON ai_audit_log(callsite, timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_audit_outcome ON ai_audit_log(outcome);
"""

# V8.15 — workflow runtime state. Definitions live in src/workflows.py
# (predefined library) or in `definition_json` (custom per-firm).
SCHEMA_WORKFLOWS = """
CREATE TABLE IF NOT EXISTS case_workflows (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    case_id           TEXT NOT NULL,
    user_id           INTEGER NOT NULL,         -- starter
    workflow_key      TEXT NOT NULL,            -- 'open_contentious_case' | 'custom:<slug>'
    title             TEXT NOT NULL,
    state             TEXT NOT NULL DEFAULT 'active',  -- active|paused|completed|cancelled
    current_step_id   TEXT,
    current_step_idx  INTEGER NOT NULL DEFAULT 0,
    step_results_json TEXT NOT NULL DEFAULT '{}',
    definition_json   TEXT,                     -- NULL for predefined; the full DSL for custom
    started_at        TEXT NOT NULL,
    updated_at        TEXT NOT NULL,
    completed_at      TEXT,
    FOREIGN KEY (case_id) REFERENCES cases(id) ON DELETE CASCADE,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE SET NULL
);
CREATE INDEX IF NOT EXISTS idx_wf_case ON case_workflows(case_id, started_at DESC);
CREATE INDEX IF NOT EXISTS idx_wf_state ON case_workflows(state);

-- V8.17 — Settlement Monte Carlo. We persist each simulation so the
-- lawyer can revisit / compare and so the firm can audit how the
-- recommendation was produced (regulatory: this is a financial-decision
-- support tool, not just a chat).
CREATE TABLE IF NOT EXISTS settlement_simulations (
    id                   INTEGER PRIMARY KEY AUTOINCREMENT,
    case_id              TEXT NOT NULL,
    user_id              INTEGER NOT NULL,
    description          TEXT NOT NULL,
    valore_in_causa_cents INTEGER,
    current_offer_cents  INTEGER,
    currency             TEXT NOT NULL DEFAULT 'EUR',
    scenarios_json       TEXT NOT NULL,
    distribution_json    TEXT NOT NULL,
    recommendation_json  TEXT NOT NULL,
    precedents_json      TEXT,
    samples              INTEGER NOT NULL DEFAULT 10000,
    seed                 INTEGER,
    created_at           TEXT NOT NULL,
    FOREIGN KEY (case_id) REFERENCES cases(id) ON DELETE CASCADE,
    FOREIGN KEY (user_id) REFERENCES users(id)
);
CREATE INDEX IF NOT EXISTS idx_settle_sim_case
    ON settlement_simulations(case_id, created_at DESC);

-- V9.0 — Genio Legale: Senior-Partner-grade multi-perspective briefs.
-- Each row holds the result of one full Genio run (6 parallel Opus
-- perspectives). by_key_json is the canonical {perspective_key: result}.
-- Status reflects the orchestrator outcome: 'completed' if all 6 returned
-- (even with parse errors), 'partial' if some perspective threw, 'error'
-- if the overall run aborted before any perspective returned.
CREATE TABLE IF NOT EXISTS genio_briefs (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    case_id         TEXT NOT NULL,
    user_id         INTEGER NOT NULL,
    description     TEXT,
    case_block      TEXT NOT NULL,
    by_key_json     TEXT NOT NULL,
    status          TEXT NOT NULL DEFAULT 'completed',
    elapsed_ms      INTEGER,
    started_at      TEXT NOT NULL,
    completed_at    TEXT,
    FOREIGN KEY (case_id) REFERENCES cases(id) ON DELETE CASCADE,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE SET NULL
);
CREATE INDEX IF NOT EXISTS idx_genio_case ON genio_briefs(case_id, started_at DESC);

-- V9.2 — Precedent Pattern Analyzer: ratio-aware case-law briefs.
-- One row per analysis run. brief_json is the synthesized output
-- (moves_to_imitate, traps_to_avoid, kill_shot, per_precedent,
-- divergence_warning, precedents[]). case_id is nullable so the lawyer
-- can run a precedent analysis on a free-form description without
-- attaching it to a fascicolo.
CREATE TABLE IF NOT EXISTS precedent_briefs (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    case_id         TEXT,
    user_id         INTEGER NOT NULL,
    case_description TEXT NOT NULL,
    brief_json      TEXT NOT NULL DEFAULT '{}',
    status          TEXT NOT NULL DEFAULT 'running',
    elapsed_ms      INTEGER,
    started_at      TEXT NOT NULL,
    completed_at    TEXT,
    FOREIGN KEY (case_id) REFERENCES cases(id) ON DELETE CASCADE,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE SET NULL
);
CREATE INDEX IF NOT EXISTS idx_precedent_case ON precedent_briefs(case_id, started_at DESC);
CREATE INDEX IF NOT EXISTS idx_precedent_user ON precedent_briefs(user_id, started_at DESC);

-- ── V9.3 Corporate Intelligence ──────────────────────────────────────
-- One row per document analysed. Multiple rows per case are merged by
-- the backend into a single corporate profile (soci, CDA, procure, …).
CREATE TABLE IF NOT EXISTS corporate_extractions (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    case_id         TEXT    NOT NULL,
    user_id         INTEGER NOT NULL,
    doc_name        TEXT    NOT NULL,
    doc_type        TEXT    NOT NULL DEFAULT 'i panjohur',
    extracted_json  TEXT    NOT NULL DEFAULT '{}',
    created_at      TEXT    NOT NULL,
    FOREIGN KEY (case_id) REFERENCES cases(id) ON DELETE CASCADE,
    FOREIGN KEY (user_id) REFERENCES users(id)  ON DELETE SET NULL
);
CREATE INDEX IF NOT EXISTS idx_corp_case ON corporate_extractions(case_id, created_at DESC);

-- ── V9.4 Bench Memo Predictor ────────────────────────────────────────
CREATE TABLE IF NOT EXISTS bench_memos (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    case_id         TEXT    NOT NULL,
    user_id         INTEGER NOT NULL,
    description     TEXT    NOT NULL,
    court_code      TEXT    NOT NULL DEFAULT 'gjykata_lartë',
    opponent_filing TEXT,
    memo_json       TEXT    NOT NULL DEFAULT '{}',
    status          TEXT    NOT NULL DEFAULT 'running',
    elapsed_ms      INTEGER,
    started_at      TEXT    NOT NULL,
    completed_at    TEXT,
    FOREIGN KEY (case_id) REFERENCES cases(id) ON DELETE CASCADE,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE SET NULL
);
CREATE INDEX IF NOT EXISTS idx_bench_case ON bench_memos(case_id, started_at DESC);

-- ── V9.5 Vigilanza Normativa ─────────────────────────────────────────
CREATE TABLE IF NOT EXISTS legal_updates (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    source          TEXT    NOT NULL DEFAULT 'manual',
    source_url      TEXT,
    title           TEXT    NOT NULL,
    content         TEXT    NOT NULL,
    published_at    TEXT,
    classification_json TEXT NOT NULL DEFAULT '{}',
    fetched_at      TEXT    NOT NULL,
    fetched_by      INTEGER,
    FOREIGN KEY (fetched_by) REFERENCES users(id) ON DELETE SET NULL
);
CREATE INDEX IF NOT EXISTS idx_legal_updates_fetched ON legal_updates(fetched_at DESC);

CREATE TABLE IF NOT EXISTS case_alerts (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    case_id         TEXT    NOT NULL,
    update_id       INTEGER NOT NULL,
    user_id         INTEGER NOT NULL,
    relevance_score REAL    NOT NULL DEFAULT 0,
    match_summary   TEXT    NOT NULL DEFAULT '{}',
    dismissed       INTEGER NOT NULL DEFAULT 0,
    created_at      TEXT    NOT NULL,
    dismissed_at    TEXT,
    FOREIGN KEY (case_id) REFERENCES cases(id) ON DELETE CASCADE,
    FOREIGN KEY (update_id) REFERENCES legal_updates(id) ON DELETE CASCADE,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE SET NULL,
    UNIQUE(case_id, update_id)
);
CREATE INDEX IF NOT EXISTS idx_case_alerts_user ON case_alerts(user_id, dismissed, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_case_alerts_case ON case_alerts(case_id, dismissed, created_at DESC);

-- ── V9.6 Ratio Coach (case post-mortems) ─────────────────────────────
CREATE TABLE IF NOT EXISTS case_lessons (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    case_id             TEXT    NOT NULL,
    user_id             INTEGER NOT NULL,
    firm_id             INTEGER,
    outcome             TEXT    NOT NULL DEFAULT 'fituar',
    archetype           TEXT,
    transferable_lesson TEXT,
    summary_hint        TEXT,
    lesson_json         TEXT    NOT NULL DEFAULT '{}',
    elapsed_ms          INTEGER,
    created_at          TEXT    NOT NULL,
    FOREIGN KEY (case_id) REFERENCES cases(id) ON DELETE CASCADE,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE SET NULL,
    UNIQUE(case_id)
);
CREATE INDEX IF NOT EXISTS idx_case_lessons_user ON case_lessons(user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_case_lessons_firm ON case_lessons(firm_id, created_at DESC);
"""

# Roles ordered by seniority/permission breadth. Used by permission checks.
FIRM_ROLES = ("owner", "partner", "lawyer", "paralegal", "assistant")
ROLE_LABELS = {
    "owner": "Titullari",
    "partner": "Ortak",
    "lawyer": "Avokat",
    "paralegal": "Praktikant",
    "assistant": "Sekretar/e",
}
# What each role can do. Booleans grouped by capability.
ROLE_PERMISSIONS = {
    "owner":     {"manage_firm": True,  "manage_members": True,  "create_case": True,  "delete_case": True,  "all_cases": True,  "billing": True},
    "partner":   {"manage_firm": False, "manage_members": True,  "create_case": True,  "delete_case": True,  "all_cases": True,  "billing": True},
    "lawyer":    {"manage_firm": False, "manage_members": False, "create_case": True,  "delete_case": False, "all_cases": False, "billing": False},
    "paralegal": {"manage_firm": False, "manage_members": False, "create_case": False, "delete_case": False, "all_cases": False, "billing": False},
    "assistant": {"manage_firm": False, "manage_members": False, "create_case": False, "delete_case": False, "all_cases": False, "billing": False},
}


def _utcnow() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


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
        _add_column_if_missing(conn, "messages", "nullity_radar_json", "TEXT")
        _add_column_if_missing(conn, "messages", "urgency_radar_json", "TEXT")
        _add_column_if_missing(conn, "messages", "action_plan_json", "TEXT")
        _add_column_if_missing(conn, "messages", "contradictions_json", "TEXT")
        _add_column_if_missing(conn, "messages", "opponent_playbook_json", "TEXT")
        _add_column_if_missing(conn, "messages", "leverage_json", "TEXT")
        _add_column_if_missing(conn, "cases", "answer_system_version", "TEXT")
        # V7.10 calendar — users need a Telegram chat_id for push reminders
        # and a random token so they can subscribe their Apple/Google
        # Calendar to their feed without logging into the app.
        _add_column_if_missing(conn, "users", "telegram_chat_id", "TEXT")
        _add_column_if_missing(conn, "users", "ical_token", "TEXT")
        # V8.0 multi-tenancy
        _add_column_if_missing(conn, "cases", "firm_id", "INTEGER")
        _add_column_if_missing(conn, "users", "active_firm_id", "INTEGER")
        _backfill_personal_firms(conn)
        # V8.2 — workflow stage on cases
        _add_column_if_missing(conn, "cases", "stage", "TEXT NOT NULL DEFAULT 'intake'")
        # V8.13 multi-jurisdiction — each case carries its applicable
        # jurisdiction tag. Drives KB selection + system-prompt language.
        # Allowed values: AL (Albania, default), IT (Italy), EU (EU law).
        _add_column_if_missing(conn, "cases", "jurisdiction", "TEXT NOT NULL DEFAULT 'AL'")
        # Optional secondary jurisdiction for cross-border matters
        # (e.g. AL+IT for an Italian client litigating in Tirana).
        _add_column_if_missing(conn, "cases", "jurisdiction_secondary", "TEXT")
        # V8.15 workflow library — runtime instances of predefined or
        # custom workflow definitions, attached to cases.
        conn.executescript(SCHEMA_WORKFLOWS)
        # V9.2 — last_active timestamp per user, updated on every authenticated
        # request. Powers the "online users" display in the admin panel.
        _add_column_if_missing(conn, "users", "last_active", "TEXT")
        conn.commit()
    log.info("app db ready at %s", db_path)


# ── V9.2 — usage / online tracking (admin dashboard) ──────────────────────

# Anthropic API list-price reference for the equivalent-cost estimation.
# Even when the brain runs through the Claude Code CLI (subscription),
# the dashboard surfaces the dollar value the team would otherwise spend.
# Prices in USD per 1M tokens, by family substring matched on the model id.
_MODEL_PRICING_PER_1M = (
    ("opus", 15.0, 75.0),     # input, output
    ("sonnet", 3.0, 15.0),
    ("haiku", 0.80, 4.0),
)


def estimate_cost_cents(model: str, input_tokens: int, output_tokens: int) -> int:
    """Return cost in CENTS (USD * 100, integer) for a single LLM call.

    Conservative: if the model id doesn't match a known family, falls back
    to Opus pricing (the most expensive) so we never underreport.
    """
    m = (model or "").lower()
    in_price, out_price = 15.0, 75.0  # default = opus
    for tag, ip, op in _MODEL_PRICING_PER_1M:
        if tag in m:
            in_price, out_price = ip, op
            break
    usd = (input_tokens / 1_000_000.0) * in_price + (output_tokens / 1_000_000.0) * out_price
    return int(round(usd * 100))


def update_user_last_active(user_id: int) -> None:
    """Bump users.last_active to now. Cheap UPDATE, called from the request
    auth middleware on every authenticated request."""
    if not user_id:
        return
    now = _utcnow()
    with db() as conn:
        conn.execute("UPDATE users SET last_active = ? WHERE id = ?", (now, user_id))


def usage_stats_by_user(since_iso: str | None = None) -> list[dict]:
    """Aggregate ai_audit_log per user. Returns one row per user with:
    calls, tokens_in, tokens_out, cost_cents (sum), last_active, is_admin.
    Sorted by total tokens descending so the heavy users are at the top."""
    where = "WHERE u.id IS NOT NULL"
    params: list = []
    if since_iso:
        where += " AND (al.timestamp >= ? OR al.timestamp IS NULL)"
        params.append(since_iso)
    with db() as conn:
        rows = conn.execute(
            f"""
            SELECT
                u.id              AS user_id,
                u.username        AS username,
                u.is_admin        AS is_admin,
                u.last_active     AS last_active,
                COUNT(al.id)      AS calls,
                COALESCE(SUM(al.input_tokens), 0)  AS tokens_in,
                COALESCE(SUM(al.output_tokens), 0) AS tokens_out,
                al.model          AS sample_model
            FROM users u
            LEFT JOIN ai_audit_log al ON al.user_id = u.id
              {('AND al.timestamp >= ?' if since_iso else '')}
            GROUP BY u.id
            ORDER BY (COALESCE(SUM(al.input_tokens), 0) + COALESCE(SUM(al.output_tokens), 0)) DESC,
                     u.username ASC
            """,
            params if since_iso else (),
        ).fetchall()
    out: list[dict] = []
    for r in rows:
        # Cost: sum per-call cost (model matters) — re-query the breakdown.
        tokens_in = int(r["tokens_in"] or 0)
        tokens_out = int(r["tokens_out"] or 0)
        # Approximation: use the most-used model for this user as the rate basis.
        cost = estimate_cost_cents(r["sample_model"] or "", tokens_in, tokens_out)
        out.append({
            "user_id": r["user_id"],
            "username": r["username"],
            "is_admin": bool(r["is_admin"]),
            "last_active": r["last_active"],
            "calls": int(r["calls"] or 0),
            "tokens_in": tokens_in,
            "tokens_out": tokens_out,
            "cost_cents": cost,
        })
    return out


def usage_totals(since_iso: str | None = None) -> dict:
    """Grand totals across all users for the period."""
    where = ""
    params: list = []
    if since_iso:
        where = "WHERE timestamp >= ?"
        params.append(since_iso)
    with db() as conn:
        row = conn.execute(
            f"""
            SELECT
                COUNT(*)                              AS calls,
                COALESCE(SUM(input_tokens), 0)        AS tokens_in,
                COALESCE(SUM(output_tokens), 0)       AS tokens_out,
                COUNT(DISTINCT user_id)               AS active_users
            FROM ai_audit_log {where}
            """,
            params,
        ).fetchone()
    tokens_in = int(row["tokens_in"] or 0)
    tokens_out = int(row["tokens_out"] or 0)
    return {
        "calls": int(row["calls"] or 0),
        "tokens_in": tokens_in,
        "tokens_out": tokens_out,
        "active_users": int(row["active_users"] or 0),
        # All-opus assumption for the grand total — safe overestimate.
        "cost_cents": estimate_cost_cents("opus", tokens_in, tokens_out),
    }


def online_user_ids(window_seconds: int = 300) -> set[int]:
    """User ids active within the last `window_seconds` (default 5 min)."""
    cutoff = (datetime.now(UTC) - timedelta(seconds=window_seconds)).strftime("%Y-%m-%dT%H:%M:%SZ")
    with db() as conn:
        rows = conn.execute(
            "SELECT id FROM users WHERE last_active IS NOT NULL AND last_active >= ?",
            (cutoff,),
        ).fetchall()
    return {r["id"] for r in rows}


def _backfill_personal_firms(conn: sqlite3.Connection) -> None:
    """Every user without a firm gets a personal firm with role=owner.

    Idempotent: only acts on users whose id is not in firm_members. Newly
    created firms get a slug derived from username (deduped if collision).
    Existing cases of that user get firm_id set to the personal firm id.
    """
    rows = conn.execute(
        "SELECT u.id, u.username FROM users u "
        "WHERE NOT EXISTS (SELECT 1 FROM firm_members fm WHERE fm.user_id = u.id)"
    ).fetchall()
    if not rows:
        return
    now = _utcnow()
    for r in rows:
        uid, uname = r["id"], r["username"]
        slug_base = re.sub(r"[^a-z0-9]+", "-", uname.lower()).strip("-") or f"u{uid}"
        slug = slug_base
        n = 1
        while conn.execute("SELECT 1 FROM firms WHERE slug = ?", (slug,)).fetchone():
            n += 1
            slug = f"{slug_base}-{n}"
        cur = conn.execute(
            "INSERT INTO firms (name, slug, owner_id, is_personal, created_at) "
            "VALUES (?, ?, ?, 1, ?)",
            (f"Studio {uname}", slug, uid, now),
        )
        firm_id = cur.lastrowid
        conn.execute(
            "INSERT INTO firm_members (firm_id, user_id, role, status, joined_at) "
            "VALUES (?, ?, 'owner', 'active', ?)",
            (firm_id, uid, now),
        )
        conn.execute(
            "UPDATE cases SET firm_id = ? WHERE user_id = ? AND firm_id IS NULL",
            (firm_id, uid),
        )
        conn.execute(
            "UPDATE users SET active_firm_id = ? WHERE id = ? AND active_firm_id IS NULL",
            (firm_id, uid),
        )
        log.info("backfill: user %s → personal firm #%s (slug=%s)", uname, firm_id, slug)


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


CASE_STAGES: tuple[str, ...] = (
    "intake", "preparation", "hearing", "decision", "execution",
)
CASE_STAGE_LABELS_SQ: dict[str, str] = {
    "intake": "Intake / pranim",
    "preparation": "Përgatitje",
    "hearing": "Seancë",
    "decision": "Vendim",
    "execution": "Ekzekutim",
}


@dataclass
class Case:
    id: str
    user_id: int
    title: str
    claude_session_id: str | None
    created_at: str
    updated_at: str
    # Fingerprint of the ANSWER_SYSTEM prompt used when this session was
    # started. NULL on pre-V6.9 rows; callers treat NULL as "stale" so
    # older cases invalidate their session on the next question.
    answer_system_version: str | None = None
    stage: str = "intake"
    # V8.13 — applicable jurisdiction. Drives KB selection + system-prompt
    # language. Allowed: AL (Albania, default), IT (Italy), EU (EU law).
    jurisdiction: str = "AL"
    jurisdiction_secondary: str | None = None


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
    nullity_radar: dict | None
    urgency_radar: dict | None
    action_plan: dict | None
    contradictions: dict | None
    opponent_playbook: dict | None
    leverage: dict | None
    created_at: str


def _user_from_row(r: sqlite3.Row) -> User:
    return User(id=r["id"], username=r["username"],
                is_admin=bool(r["is_admin"]), created_at=r["created_at"])


def _case_from_row(r: sqlite3.Row) -> Case:
    keys = r.keys()
    asv = r["answer_system_version"] if "answer_system_version" in keys else None
    stage = r["stage"] if "stage" in keys and r["stage"] else "intake"
    jur = r["jurisdiction"] if "jurisdiction" in keys and r["jurisdiction"] else "AL"
    jur2 = r["jurisdiction_secondary"] if "jurisdiction_secondary" in keys else None
    return Case(id=r["id"], user_id=r["user_id"], title=r["title"],
                claude_session_id=r["claude_session_id"],
                created_at=r["created_at"], updated_at=r["updated_at"],
                answer_system_version=asv, stage=stage,
                jurisdiction=jur, jurisdiction_secondary=jur2)


def set_case_stage(case_id: str, stage: str,
                   db_path: Path = APP_DB_PATH) -> bool:
    """Update a case's workflow stage. Returns False if invalid stage."""
    if stage not in CASE_STAGES:
        return False
    with _connect(db_path) as conn:
        cur = conn.execute(
            "UPDATE cases SET stage = ?, updated_at = ? WHERE id = ?",
            (stage, _utcnow(), case_id),
        )
        conn.commit()
        return cur.rowcount > 0


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
    nullity_radar_raw = r["nullity_radar_json"] if "nullity_radar_json" in keys else None
    urgency_radar_raw = r["urgency_radar_json"] if "urgency_radar_json" in keys else None
    action_plan_raw = r["action_plan_json"] if "action_plan_json" in keys else None
    contradictions_raw = r["contradictions_json"] if "contradictions_json" in keys else None
    opponent_raw = r["opponent_playbook_json"] if "opponent_playbook_json" in keys else None
    leverage_raw = r["leverage_json"] if "leverage_json" in keys else None
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
        nullity_radar=json.loads(nullity_radar_raw) if nullity_radar_raw else None,
        urgency_radar=json.loads(urgency_radar_raw) if urgency_radar_raw else None,
        action_plan=json.loads(action_plan_raw) if action_plan_raw else None,
        contradictions=json.loads(contradictions_raw) if contradictions_raw else None,
        opponent_playbook=json.loads(opponent_raw) if opponent_raw else None,
        leverage=json.loads(leverage_raw) if leverage_raw else None,
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
        # V8.0: every new user gets a personal firm so they can immediately
        # create cases. They can later join other firms or be invited by an
        # owner; the personal firm stays as a fallback workspace.
        slug_base = re.sub(r"[^a-z0-9]+", "-", username.lower()).strip("-") or f"u{uid}"
        slug = slug_base
        n = 1
        while conn.execute("SELECT 1 FROM firms WHERE slug = ?", (slug,)).fetchone():
            n += 1
            slug = f"{slug_base}-{n}"
        fcur = conn.execute(
            "INSERT INTO firms (name, slug, owner_id, is_personal, created_at) "
            "VALUES (?, ?, ?, 1, ?)",
            (f"Studio {username}", slug, uid, now),
        )
        firm_id = fcur.lastrowid
        conn.execute(
            "INSERT INTO firm_members (firm_id, user_id, role, status, joined_at) "
            "VALUES (?, ?, 'owner', 'active', ?)",
            (firm_id, uid, now),
        )
        conn.execute("UPDATE users SET active_firm_id = ? WHERE id = ?", (firm_id, uid))
    log.info("created user %r (id=%d, admin=%s, firm=%s)", username, uid, is_admin, slug)
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

def create_case(user_id: int, title: str, firm_id: int | None = None,
                jurisdiction: str = "AL") -> Case:
    title = (title or "").strip() or "Rast pa titull"
    jurisdiction = (jurisdiction or "AL").upper().strip()
    if jurisdiction not in ("AL", "IT", "EU"):
        jurisdiction = "AL"
    case_id = uuid.uuid4().hex
    now = _utcnow()
    with db() as conn:
        if firm_id is None:
            row = conn.execute(
                "SELECT active_firm_id FROM users WHERE id = ?", (user_id,)
            ).fetchone()
            firm_id = row["active_firm_id"] if row else None
        conn.execute(
            "INSERT INTO cases (id, user_id, firm_id, title, jurisdiction, "
            "created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (case_id, user_id, firm_id, title, jurisdiction, now, now),
        )
    return Case(id=case_id, user_id=user_id, title=title,
                claude_session_id=None, created_at=now, updated_at=now,
                jurisdiction=jurisdiction)


def update_case_jurisdiction(case_id: str, user_id: int,
                             jurisdiction: str,
                             jurisdiction_secondary: str | None = None) -> bool:
    jurisdiction = (jurisdiction or "AL").upper().strip()
    if jurisdiction not in ("AL", "IT", "EU"):
        return False
    if jurisdiction_secondary:
        jurisdiction_secondary = jurisdiction_secondary.upper().strip()
        if jurisdiction_secondary not in ("AL", "IT", "EU"):
            jurisdiction_secondary = None
    with db() as conn:
        cur = conn.execute(
            "UPDATE cases SET jurisdiction = ?, jurisdiction_secondary = ?, "
            "updated_at = ? WHERE id = ? AND user_id = ?",
            (jurisdiction, jurisdiction_secondary, _utcnow(), case_id, user_id),
        )
        return cur.rowcount > 0


def get_case(case_id: str, user_id: int) -> Case | None:
    """Fetch a case only if it belongs to `user_id` (defence in depth)."""
    with db() as conn:
        row = conn.execute(
            "SELECT * FROM cases WHERE id = ? AND user_id = ?",
            (case_id, user_id),
        ).fetchone()
    return _case_from_row(row) if row else None


def get_case_unscoped(case_id: str) -> Case | None:
    """Fetch a case without user/firm scoping. Caller MUST already have
    proven authorisation (e.g. a valid portal_token, an internal cron)."""
    with db() as conn:
        row = conn.execute(
            "SELECT * FROM cases WHERE id = ?", (case_id,),
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


def set_case_answer_system_version(
    case_id: str, user_id: int, version: str | None,
) -> None:
    """Record which ANSWER_SYSTEM fingerprint this case's session was
    started under. Called right after a fresh session is created so we
    can detect drift at the next turn and invalidate if needed."""
    with db() as conn:
        conn.execute(
            "UPDATE cases SET answer_system_version = ?, updated_at = ? "
            "WHERE id = ? AND user_id = ?",
            (version, _utcnow(), case_id, user_id),
        )


def invalidate_case_session_if_stale(
    case_id: str, user_id: int, current_version: str,
) -> bool:
    """Drop claude_session_id if the case's session was started under a
    different ANSWER_SYSTEM fingerprint (or none at all). Returns True
    when invalidation happened. The case's version is NOT updated here —
    the next successful compose writes the new fingerprint, which keeps
    invalidation and write-of-new-session transactional at the call
    site instead of eagerly overwriting before we know the new session
    took hold."""
    with db() as conn:
        row = conn.execute(
            "SELECT claude_session_id, answer_system_version "
            "FROM cases WHERE id = ? AND user_id = ?",
            (case_id, user_id),
        ).fetchone()
        if not row:
            return False
        if row["claude_session_id"] is None:
            return False
        if row["answer_system_version"] == current_version:
            return False
        conn.execute(
            "UPDATE cases SET claude_session_id = NULL, updated_at = ? "
            "WHERE id = ? AND user_id = ?",
            (_utcnow(), case_id, user_id),
        )
    return True


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
    nullity_radar: dict | None = None,
    urgency_radar: dict | None = None,
    action_plan: dict | None = None,
    contradictions: dict | None = None,
    opponent_playbook: dict | None = None,
    leverage: dict | None = None,
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
    nullity_radar_json = (
        json.dumps(nullity_radar, ensure_ascii=False) if nullity_radar else None
    )
    urgency_radar_json = (
        json.dumps(urgency_radar, ensure_ascii=False) if urgency_radar else None
    )
    action_plan_json = (
        json.dumps(action_plan, ensure_ascii=False) if action_plan else None
    )
    contradictions_json = (
        json.dumps(contradictions, ensure_ascii=False) if contradictions else None
    )
    opponent_playbook_json = (
        json.dumps(opponent_playbook, ensure_ascii=False) if opponent_playbook else None
    )
    leverage_json = (
        json.dumps(leverage, ensure_ascii=False) if leverage else None
    )
    with db() as conn:
        cur = conn.execute(
            "INSERT INTO messages (case_id, role, content, kind, "
            "articles_json, precedents_json, timeline_json, comparison_json, "
            "missing_facts_json, premortem_json, distinguishing_json, "
            "evidence_map_json, nullity_radar_json, urgency_radar_json, "
            "action_plan_json, contradictions_json, opponent_playbook_json, "
            "leverage_json, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (case_id, role, content, kind, articles_json, precedents_json,
             timeline_json, comparison_json, missing_json, premortem_json,
             distinguishing_json, evidence_map_json, nullity_radar_json,
             urgency_radar_json, action_plan_json, contradictions_json,
             opponent_playbook_json, leverage_json, now),
        )
        mid = cur.lastrowid
        conn.execute("UPDATE cases SET updated_at = ? WHERE id = ?", (now, case_id))
    return Message(
        id=mid, case_id=case_id, role=role, content=content, kind=kind,
        articles=articles or [], precedents=precedents or [],
        timeline=timeline, comparison=comparison, missing_facts=missing_facts,
        premortem=premortem, distinguishing=distinguishing,
        evidence_map=evidence_map, nullity_radar=nullity_radar,
        urgency_radar=urgency_radar, action_plan=action_plan,
        contradictions=contradictions,
        opponent_playbook=opponent_playbook, leverage=leverage,
        created_at=now,
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


# ── events / calendar (V7.10) ───────────────────────────────────────────────

EVENT_KINDS = {"takim", "seance", "afat", "dorëzim", "tjetër"}
# Default palette — chosen once so the UI stays consistent when the user
# hasn't picked a custom colour. Verde calmo for meetings (Romeo's pick),
# rosso for hard deadlines so they pop.
EVENT_DEFAULT_COLORS: dict[str, str] = {
    "takim":   "#16a34a",  # green-600  — client meetings
    "seance":  "#2563eb",  # blue-600   — court hearings
    "afat":    "#dc2626",  # red-600    — hard legal deadlines
    "dorëzim": "#f59e0b",  # amber-500  — document filings
    "tjetër":  "#6b7280",  # gray-500
}


@dataclass
class Event:
    id: str
    user_id: int
    case_id: str | None
    title: str
    description: str | None
    kind: str
    starts_at: str
    ends_at: str | None
    all_day: bool
    location: str | None
    color: str | None
    source: str
    source_ref: str | None
    done: bool
    created_at: str
    updated_at: str


@dataclass
class Reminder:
    id: int
    event_id: str
    offset_minutes: int
    channel: str
    fire_at: str
    sent_at: str | None
    error: str | None
    created_at: str


def _event_from_row(r: sqlite3.Row) -> Event:
    return Event(
        id=r["id"], user_id=r["user_id"], case_id=r["case_id"],
        title=r["title"], description=r["description"], kind=r["kind"],
        starts_at=r["starts_at"], ends_at=r["ends_at"],
        all_day=bool(r["all_day"]), location=r["location"], color=r["color"],
        source=r["source"], source_ref=r["source_ref"],
        done=bool(r["done"]),
        created_at=r["created_at"], updated_at=r["updated_at"],
    )


def _reminder_from_row(r: sqlite3.Row) -> Reminder:
    return Reminder(
        id=r["id"], event_id=r["event_id"],
        offset_minutes=r["offset_minutes"], channel=r["channel"],
        fire_at=r["fire_at"], sent_at=r["sent_at"], error=r["error"],
        created_at=r["created_at"],
    )


def _compute_fire_at(starts_at: str, offset_minutes: int) -> str:
    """starts_at − offset_minutes, as UTC ISO string. starts_at must be
    an ISO-8601 string with a 'Z' or +hh:mm suffix; we parse via fromisoformat
    after normalising 'Z' to +00:00."""
    from datetime import timedelta
    s = starts_at.replace("Z", "+00:00")
    dt = datetime.fromisoformat(s)
    fire = dt - timedelta(minutes=offset_minutes)
    # Emit with Z suffix so it round-trips cleanly.
    if fire.tzinfo is None:
        fire = fire.replace(tzinfo=UTC)
    return fire.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def create_event(
    user_id: int,
    title: str,
    kind: str,
    starts_at: str,
    *,
    case_id: str | None = None,
    description: str | None = None,
    ends_at: str | None = None,
    all_day: bool = False,
    location: str | None = None,
    color: str | None = None,
    source: str = "manual",
    source_ref: str | None = None,
    reminders: list[int] | None = None,
) -> Event:
    """Create an event and its attached reminders in a single transaction.

    ``reminders`` is a list of offset-in-minutes (e.g. [1440, 60] for a
    day-ahead + hour-ahead ping). Reminders are skipped for events that
    are already in the past — it would only confuse the scheduler.
    """
    if kind not in EVENT_KINDS:
        raise ValueError(f"unknown event kind: {kind!r}")
    title = (title or "").strip() or "Ngjarje pa titull"
    event_id = uuid.uuid4().hex
    now = _utcnow()
    with db() as conn:
        conn.execute(
            "INSERT INTO events (id, user_id, case_id, title, description, "
            "kind, starts_at, ends_at, all_day, location, color, source, "
            "source_ref, created_at, updated_at) VALUES "
            "(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (event_id, user_id, case_id, title, description, kind,
             starts_at, ends_at, int(all_day), location, color,
             source, source_ref, now, now),
        )
        for off in (reminders or []):
            try:
                fire_at = _compute_fire_at(starts_at, int(off))
            except Exception as exc:
                log.warning("invalid reminder offset %s: %s", off, exc)
                continue
            if fire_at <= now:
                continue
            conn.execute(
                "INSERT INTO reminders (event_id, offset_minutes, channel, "
                "fire_at, created_at) VALUES (?, ?, ?, ?, ?)",
                (event_id, int(off), "telegram", fire_at, now),
            )
    return Event(
        id=event_id, user_id=user_id, case_id=case_id, title=title,
        description=description, kind=kind, starts_at=starts_at,
        ends_at=ends_at, all_day=all_day, location=location, color=color,
        source=source, source_ref=source_ref, done=False,
        created_at=now, updated_at=now,
    )


def get_event(event_id: str, user_id: int) -> Event | None:
    with db() as conn:
        row = conn.execute(
            "SELECT * FROM events WHERE id = ? AND user_id = ?",
            (event_id, user_id),
        ).fetchone()
    return _event_from_row(row) if row else None


def list_events(
    user_id: int,
    *,
    start: str | None = None,
    end: str | None = None,
    case_id: str | None = None,
) -> list[Event]:
    """Events for `user_id`, optionally filtered by [start, end) and/or case.

    Range bounds are ISO-8601 UTC. We compare on starts_at only — multi-day
    events whose end falls outside the window still count as "in" the window
    if they started inside it. That matches how the month-view renders: a
    hearing that starts on the 30th is shown on the 30th even if it carries
    into the 31st.
    """
    clauses = ["user_id = ?"]
    params: list = [user_id]
    if start:
        clauses.append("starts_at >= ?")
        params.append(start)
    if end:
        clauses.append("starts_at < ?")
        params.append(end)
    if case_id:
        clauses.append("case_id = ?")
        params.append(case_id)
    sql = ("SELECT * FROM events WHERE " + " AND ".join(clauses)
           + " ORDER BY starts_at ASC")
    with db() as conn:
        rows = conn.execute(sql, params).fetchall()
    return [_event_from_row(r) for r in rows]


def update_event(
    event_id: str,
    user_id: int,
    **fields,
) -> Event | None:
    """Update whitelisted columns on an event. Recomputes fire_at for all
    pending reminders when starts_at changes."""
    allowed = {"title", "description", "kind", "starts_at", "ends_at",
               "all_day", "location", "color", "done", "case_id"}
    patch = {k: v for k, v in fields.items() if k in allowed}
    if not patch:
        return get_event(event_id, user_id)
    if "kind" in patch and patch["kind"] not in EVENT_KINDS:
        raise ValueError(f"unknown event kind: {patch['kind']!r}")
    if "all_day" in patch:
        patch["all_day"] = int(bool(patch["all_day"]))
    if "done" in patch:
        patch["done"] = int(bool(patch["done"]))
    sets = ", ".join(f"{k} = ?" for k in patch)
    params = list(patch.values()) + [_utcnow(), event_id, user_id]
    with db() as conn:
        cur = conn.execute(
            f"UPDATE events SET {sets}, updated_at = ? "
            "WHERE id = ? AND user_id = ?",
            params,
        )
        if cur.rowcount == 0:
            return None
        if "starts_at" in patch:
            # Recompute fire_at for every still-pending reminder.
            pending = conn.execute(
                "SELECT id, offset_minutes FROM reminders "
                "WHERE event_id = ? AND sent_at IS NULL",
                (event_id,),
            ).fetchall()
            for pr in pending:
                try:
                    fire = _compute_fire_at(patch["starts_at"], pr["offset_minutes"])
                except Exception:
                    continue
                conn.execute(
                    "UPDATE reminders SET fire_at = ? WHERE id = ?",
                    (fire, pr["id"]),
                )
    return get_event(event_id, user_id)


def delete_event(event_id: str, user_id: int) -> bool:
    with db() as conn:
        cur = conn.execute(
            "DELETE FROM events WHERE id = ? AND user_id = ?",
            (event_id, user_id),
        )
    return cur.rowcount > 0


def event_by_source_ref(user_id: int, source_ref: str) -> Event | None:
    """Lookup for dedup when auto-populating from a dossier analysis."""
    with db() as conn:
        row = conn.execute(
            "SELECT * FROM events WHERE user_id = ? AND source_ref = ?",
            (user_id, source_ref),
        ).fetchone()
    return _event_from_row(row) if row else None


# ── reminders ──────────────────────────────────────────────────────────────

def list_pending_reminders(now_iso: str) -> list[tuple[Reminder, Event]]:
    """All reminders whose fire_at ≤ now and that haven't been sent yet.

    Returns (reminder, event) pairs so the scheduler has everything it
    needs to format the message without a second query."""
    with db() as conn:
        rows = conn.execute(
            "SELECT r.id AS r_id, r.event_id, r.offset_minutes, r.channel, "
            "       r.fire_at, r.sent_at, r.error, r.created_at AS r_created, "
            "       e.* "
            "FROM reminders r JOIN events e ON r.event_id = e.id "
            "WHERE r.sent_at IS NULL AND r.fire_at <= ? "
            "ORDER BY r.fire_at ASC",
            (now_iso,),
        ).fetchall()
    out: list[tuple[Reminder, Event]] = []
    for r in rows:
        rem = Reminder(
            id=r["r_id"], event_id=r["event_id"],
            offset_minutes=r["offset_minutes"], channel=r["channel"],
            fire_at=r["fire_at"], sent_at=r["sent_at"], error=r["error"],
            created_at=r["r_created"],
        )
        ev = Event(
            id=r["id"], user_id=r["user_id"], case_id=r["case_id"],
            title=r["title"], description=r["description"], kind=r["kind"],
            starts_at=r["starts_at"], ends_at=r["ends_at"],
            all_day=bool(r["all_day"]), location=r["location"],
            color=r["color"], source=r["source"], source_ref=r["source_ref"],
            done=bool(r["done"]),
            created_at=r["created_at"], updated_at=r["updated_at"],
        )
        out.append((rem, ev))
    return out


def mark_reminder_sent(reminder_id: int, error: str | None = None) -> None:
    with db() as conn:
        conn.execute(
            "UPDATE reminders SET sent_at = ?, error = ? WHERE id = ?",
            (_utcnow(), (error or "")[:500] or None, reminder_id),
        )


def list_reminders_for_event(event_id: str) -> list[Reminder]:
    with db() as conn:
        rows = conn.execute(
            "SELECT * FROM reminders WHERE event_id = ? ORDER BY fire_at ASC",
            (event_id,),
        ).fetchall()
    return [_reminder_from_row(r) for r in rows]


def replace_reminders(
    event_id: str, offsets: list[int], starts_at: str, channel: str = "telegram",
) -> None:
    """Wipe pending reminders for ``event_id`` and recreate from ``offsets``."""
    now = _utcnow()
    with db() as conn:
        conn.execute(
            "DELETE FROM reminders WHERE event_id = ? AND sent_at IS NULL",
            (event_id,),
        )
        for off in offsets:
            try:
                fire_at = _compute_fire_at(starts_at, int(off))
            except Exception:
                continue
            if fire_at <= now:
                continue
            conn.execute(
                "INSERT INTO reminders (event_id, offset_minutes, channel, "
                "fire_at, created_at) VALUES (?, ?, ?, ?, ?)",
                (event_id, int(off), channel, fire_at, now),
            )


# ── user helpers for calendar integrations ─────────────────────────────────

def set_user_telegram_chat(user_id: int, chat_id: str | None) -> None:
    with db() as conn:
        conn.execute(
            "UPDATE users SET telegram_chat_id = ? WHERE id = ?",
            (chat_id, user_id),
        )


def get_user_telegram_chat(user_id: int) -> str | None:
    with db() as conn:
        row = conn.execute(
            "SELECT telegram_chat_id FROM users WHERE id = ?",
            (user_id,),
        ).fetchone()
    return row["telegram_chat_id"] if row else None


def ensure_ical_token(user_id: int) -> str:
    """Return the user's ical subscription token, creating one on first access."""
    with db() as conn:
        row = conn.execute(
            "SELECT ical_token FROM users WHERE id = ?", (user_id,),
        ).fetchone()
        if row and row["ical_token"]:
            return row["ical_token"]
        token = uuid.uuid4().hex
        conn.execute(
            "UPDATE users SET ical_token = ? WHERE id = ?",
            (token, user_id),
        )
    return token


def get_user_by_ical_token(token: str) -> User | None:
    with db() as conn:
        row = conn.execute(
            "SELECT id, username, is_admin, created_at FROM users "
            "WHERE ical_token = ?",
            (token,),
        ).fetchone()
    return _user_from_row(row) if row else None


# ── V7.11 — stress_tests / citation_audits / drafted_acts ────────────────

@dataclass
class StressTest:
    id: str
    case_id: str
    user_id: int
    hypothesis: str
    result: dict
    created_at: str


@dataclass
class CitationAudit:
    id: str
    case_id: str | None
    user_id: int
    source_text: str
    result: dict
    created_at: str


@dataclass
class DraftedAct:
    id: str
    case_id: str | None
    user_id: int
    act_type: str
    brief: str
    draft_text: str
    meta: dict
    created_at: str


def create_stress_test(
    case_id: str, user_id: int, hypothesis: str, result: dict,
) -> StressTest:
    sid = uuid.uuid4().hex
    now = _utcnow()
    payload = json.dumps(result, ensure_ascii=False)
    with db() as conn:
        conn.execute(
            "INSERT INTO stress_tests (id, case_id, user_id, hypothesis, "
            "result_json, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (sid, case_id, user_id, hypothesis, payload, now),
        )
    return StressTest(id=sid, case_id=case_id, user_id=user_id,
                      hypothesis=hypothesis, result=result, created_at=now)


def list_stress_tests(case_id: str, user_id: int) -> list[StressTest]:
    with db() as conn:
        rows = conn.execute(
            "SELECT * FROM stress_tests WHERE case_id = ? AND user_id = ? "
            "ORDER BY created_at DESC",
            (case_id, user_id),
        ).fetchall()
    return [
        StressTest(id=r["id"], case_id=r["case_id"], user_id=r["user_id"],
                   hypothesis=r["hypothesis"],
                   result=json.loads(r["result_json"]),
                   created_at=r["created_at"])
        for r in rows
    ]


def get_stress_test(test_id: str, user_id: int) -> StressTest | None:
    with db() as conn:
        row = conn.execute(
            "SELECT * FROM stress_tests WHERE id = ? AND user_id = ?",
            (test_id, user_id),
        ).fetchone()
    if not row:
        return None
    return StressTest(id=row["id"], case_id=row["case_id"],
                      user_id=row["user_id"], hypothesis=row["hypothesis"],
                      result=json.loads(row["result_json"]),
                      created_at=row["created_at"])


def delete_stress_test(test_id: str, user_id: int) -> bool:
    with db() as conn:
        cur = conn.execute(
            "DELETE FROM stress_tests WHERE id = ? AND user_id = ?",
            (test_id, user_id),
        )
    return cur.rowcount > 0


def create_citation_audit(
    user_id: int, source_text: str, result: dict,
    case_id: str | None = None,
) -> CitationAudit:
    aid = uuid.uuid4().hex
    now = _utcnow()
    payload = json.dumps(result, ensure_ascii=False)
    with db() as conn:
        conn.execute(
            "INSERT INTO citation_audits (id, case_id, user_id, source_text, "
            "result_json, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (aid, case_id, user_id, source_text, payload, now),
        )
    return CitationAudit(id=aid, case_id=case_id, user_id=user_id,
                         source_text=source_text, result=result,
                         created_at=now)


def get_citation_audit(audit_id: str, user_id: int) -> CitationAudit | None:
    with db() as conn:
        row = conn.execute(
            "SELECT * FROM citation_audits WHERE id = ? AND user_id = ?",
            (audit_id, user_id),
        ).fetchone()
    if not row:
        return None
    return CitationAudit(id=row["id"], case_id=row["case_id"],
                         user_id=row["user_id"],
                         source_text=row["source_text"],
                         result=json.loads(row["result_json"]),
                         created_at=row["created_at"])


def list_citation_audits(user_id: int, limit: int = 20) -> list[CitationAudit]:
    with db() as conn:
        rows = conn.execute(
            "SELECT * FROM citation_audits WHERE user_id = ? "
            "ORDER BY created_at DESC LIMIT ?",
            (user_id, int(limit)),
        ).fetchall()
    return [
        CitationAudit(id=r["id"], case_id=r["case_id"],
                      user_id=r["user_id"],
                      source_text=r["source_text"],
                      result=json.loads(r["result_json"]),
                      created_at=r["created_at"])
        for r in rows
    ]


def create_drafted_act(
    user_id: int, act_type: str, brief: str, draft_text: str,
    *, case_id: str | None = None, meta: dict | None = None,
) -> DraftedAct:
    did = uuid.uuid4().hex
    now = _utcnow()
    meta_payload = json.dumps(meta or {}, ensure_ascii=False)
    with db() as conn:
        conn.execute(
            "INSERT INTO drafted_acts (id, case_id, user_id, act_type, brief, "
            "draft_text, meta_json, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (did, case_id, user_id, act_type, brief, draft_text,
             meta_payload, now),
        )
    return DraftedAct(id=did, case_id=case_id, user_id=user_id,
                      act_type=act_type, brief=brief, draft_text=draft_text,
                      meta=(meta or {}), created_at=now)


def get_drafted_act(act_id: str, user_id: int) -> DraftedAct | None:
    with db() as conn:
        row = conn.execute(
            "SELECT * FROM drafted_acts WHERE id = ? AND user_id = ?",
            (act_id, user_id),
        ).fetchone()
    if not row:
        return None
    return DraftedAct(id=row["id"], case_id=row["case_id"],
                      user_id=row["user_id"], act_type=row["act_type"],
                      brief=row["brief"], draft_text=row["draft_text"],
                      meta=json.loads(row["meta_json"] or "{}"),
                      created_at=row["created_at"])


def list_drafted_acts(user_id: int, limit: int = 20) -> list[DraftedAct]:
    with db() as conn:
        rows = conn.execute(
            "SELECT * FROM drafted_acts WHERE user_id = ? "
            "ORDER BY created_at DESC LIMIT ?",
            (user_id, int(limit)),
        ).fetchall()
    return [
        DraftedAct(id=r["id"], case_id=r["case_id"],
                   user_id=r["user_id"], act_type=r["act_type"],
                   brief=r["brief"], draft_text=r["draft_text"],
                   meta=json.loads(r["meta_json"] or "{}"),
                   created_at=r["created_at"])
        for r in rows
    ]


# ── V7.12 — case_timelines / adversarial_loops / strategy_compasses ──────

@dataclass
class CaseTimeline:
    case_id: str
    user_id: int
    result: dict
    doc_count: int
    event_count: int
    created_at: str
    updated_at: str


@dataclass
class AdversarialLoop:
    id: str
    case_id: str
    user_id: int
    hypothesis: str
    rounds: list[dict]
    summary: dict
    round_count: int
    created_at: str


@dataclass
class StrategyCompass:
    id: str
    case_id: str
    user_id: int
    objective: str
    tree: dict
    meta: dict
    created_at: str


def upsert_case_timeline(
    case_id: str, user_id: int, result: dict,
    doc_count: int, event_count: int,
) -> CaseTimeline:
    """Save (or refresh) the timeline for a case. We keep only the latest."""
    now = _utcnow()
    payload = json.dumps(result, ensure_ascii=False)
    with _connect() as conn:
        existing = conn.execute(
            "SELECT created_at FROM case_timelines WHERE case_id = ?",
            (case_id,),
        ).fetchone()
        created = existing["created_at"] if existing else now
        conn.execute(
            "INSERT OR REPLACE INTO case_timelines "
            "(case_id, user_id, result_json, doc_count, event_count, "
            " created_at, updated_at) VALUES (?,?,?,?,?,?,?)",
            (case_id, user_id, payload, doc_count, event_count, created, now),
        )
        conn.commit()
    return CaseTimeline(
        case_id=case_id, user_id=user_id, result=result,
        doc_count=doc_count, event_count=event_count,
        created_at=created, updated_at=now,
    )


def get_case_timeline(case_id: str, user_id: int) -> CaseTimeline | None:
    with _connect() as conn:
        row = conn.execute(
            "SELECT * FROM case_timelines WHERE case_id = ? AND user_id = ?",
            (case_id, user_id),
        ).fetchone()
    if not row:
        return None
    return CaseTimeline(
        case_id=row["case_id"], user_id=row["user_id"],
        result=json.loads(row["result_json"]),
        doc_count=row["doc_count"], event_count=row["event_count"],
        created_at=row["created_at"], updated_at=row["updated_at"],
    )


def delete_case_timeline(case_id: str, user_id: int) -> bool:
    with _connect() as conn:
        cur = conn.execute(
            "DELETE FROM case_timelines WHERE case_id = ? AND user_id = ?",
            (case_id, user_id),
        )
        conn.commit()
    return cur.rowcount > 0


def create_adversarial_loop(
    case_id: str, user_id: int, hypothesis: str,
    rounds: list[dict], summary: dict,
) -> AdversarialLoop:
    aid = uuid.uuid4().hex
    now = _utcnow()
    with _connect() as conn:
        conn.execute(
            "INSERT INTO adversarial_loops (id, case_id, user_id, hypothesis, "
            " rounds_json, summary_json, round_count, created_at) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (aid, case_id, user_id, hypothesis,
             json.dumps(rounds, ensure_ascii=False),
             json.dumps(summary, ensure_ascii=False),
             len(rounds), now),
        )
        conn.commit()
    return AdversarialLoop(
        id=aid, case_id=case_id, user_id=user_id, hypothesis=hypothesis,
        rounds=rounds, summary=summary, round_count=len(rounds), created_at=now,
    )


def get_adversarial_loop(loop_id: str, user_id: int) -> AdversarialLoop | None:
    with _connect() as conn:
        row = conn.execute(
            "SELECT * FROM adversarial_loops WHERE id = ? AND user_id = ?",
            (loop_id, user_id),
        ).fetchone()
    if not row:
        return None
    return AdversarialLoop(
        id=row["id"], case_id=row["case_id"], user_id=row["user_id"],
        hypothesis=row["hypothesis"],
        rounds=json.loads(row["rounds_json"]),
        summary=json.loads(row["summary_json"]),
        round_count=row["round_count"], created_at=row["created_at"],
    )


def list_adversarial_loops(case_id: str, user_id: int) -> list[AdversarialLoop]:
    with _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM adversarial_loops WHERE case_id = ? AND user_id = ? "
            "ORDER BY created_at DESC",
            (case_id, user_id),
        ).fetchall()
    return [
        AdversarialLoop(
            id=r["id"], case_id=r["case_id"], user_id=r["user_id"],
            hypothesis=r["hypothesis"],
            rounds=json.loads(r["rounds_json"]),
            summary=json.loads(r["summary_json"]),
            round_count=r["round_count"], created_at=r["created_at"],
        ) for r in rows
    ]


def create_strategy_compass(
    case_id: str, user_id: int, objective: str,
    tree: dict, meta: dict,
) -> StrategyCompass:
    sid = uuid.uuid4().hex
    now = _utcnow()
    with _connect() as conn:
        conn.execute(
            "INSERT INTO strategy_compasses (id, case_id, user_id, objective, "
            " tree_json, meta_json, created_at) VALUES (?,?,?,?,?,?,?)",
            (sid, case_id, user_id, objective,
             json.dumps(tree, ensure_ascii=False),
             json.dumps(meta, ensure_ascii=False),
             now),
        )
        conn.commit()
    return StrategyCompass(
        id=sid, case_id=case_id, user_id=user_id, objective=objective,
        tree=tree, meta=meta, created_at=now,
    )


def get_strategy_compass(sid: str, user_id: int) -> StrategyCompass | None:
    with _connect() as conn:
        row = conn.execute(
            "SELECT * FROM strategy_compasses WHERE id = ? AND user_id = ?",
            (sid, user_id),
        ).fetchone()
    if not row:
        return None
    return StrategyCompass(
        id=row["id"], case_id=row["case_id"], user_id=row["user_id"],
        objective=row["objective"],
        tree=json.loads(row["tree_json"]),
        meta=json.loads(row["meta_json"] or "{}"),
        created_at=row["created_at"],
    )


def list_strategy_compasses(case_id: str, user_id: int) -> list[StrategyCompass]:
    with _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM strategy_compasses WHERE case_id = ? AND user_id = ? "
            "ORDER BY created_at DESC",
            (case_id, user_id),
        ).fetchall()
    return [
        StrategyCompass(
            id=r["id"], case_id=r["case_id"], user_id=r["user_id"],
            objective=r["objective"],
            tree=json.loads(r["tree_json"]),
            meta=json.loads(r["meta_json"] or "{}"),
            created_at=r["created_at"],
        ) for r in rows
    ]


# ── V8.0 — Firms / Members / Assignments / Parties ─────────────────────────

@dataclass
class Firm:
    id: int
    name: str
    slug: str
    owner_id: int
    is_personal: bool
    created_at: str


@dataclass
class FirmMember:
    id: int
    firm_id: int
    user_id: int
    username: str
    role: str
    status: str
    joined_at: str


@dataclass
class CaseAssignment:
    id: int
    case_id: str
    member_id: int
    user_id: int
    username: str
    role_in_case: str
    assigned_at: str


@dataclass
class CaseParty:
    id: int
    case_id: str
    firm_id: int
    name: str
    display_name: str
    side: str
    source: str | None
    created_at: str


def _firm_from_row(r: sqlite3.Row) -> Firm:
    return Firm(
        id=r["id"], name=r["name"], slug=r["slug"],
        owner_id=r["owner_id"], is_personal=bool(r["is_personal"]),
        created_at=r["created_at"],
    )


def _member_from_row(r: sqlite3.Row) -> FirmMember:
    return FirmMember(
        id=r["id"], firm_id=r["firm_id"], user_id=r["user_id"],
        username=r["username"], role=r["role"], status=r["status"],
        joined_at=r["joined_at"],
    )


# ── firms ─────────────────────────────────────────────────────────────────

def create_firm(name: str, owner_user_id: int) -> Firm:
    name = (name or "").strip()
    if not name:
        raise ValueError("firm name cannot be empty")
    now = _utcnow()
    slug_base = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or f"f{owner_user_id}"
    with db() as conn:
        slug = slug_base
        n = 1
        while conn.execute("SELECT 1 FROM firms WHERE slug = ?", (slug,)).fetchone():
            n += 1
            slug = f"{slug_base}-{n}"
        cur = conn.execute(
            "INSERT INTO firms (name, slug, owner_id, is_personal, created_at) "
            "VALUES (?, ?, ?, 0, ?)",
            (name, slug, owner_user_id, now),
        )
        firm_id = cur.lastrowid
        conn.execute(
            "INSERT INTO firm_members (firm_id, user_id, role, status, joined_at) "
            "VALUES (?, ?, 'owner', 'active', ?)",
            (firm_id, owner_user_id, now),
        )
    return Firm(id=firm_id, name=name, slug=slug, owner_id=owner_user_id,
                is_personal=False, created_at=now)


def get_firm(firm_id: int) -> Firm | None:
    with db() as conn:
        row = conn.execute("SELECT * FROM firms WHERE id = ?", (firm_id,)).fetchone()
    return _firm_from_row(row) if row else None


def get_firm_by_slug(slug: str) -> Firm | None:
    with db() as conn:
        row = conn.execute(
            "SELECT * FROM firms WHERE slug = ?", (slug,)
        ).fetchone()
    return _firm_from_row(row) if row else None


def list_firms_for_user(user_id: int) -> list[Firm]:
    """All firms where this user is an active member."""
    with db() as conn:
        rows = conn.execute(
            "SELECT f.* FROM firms f "
            "JOIN firm_members fm ON fm.firm_id = f.id "
            "WHERE fm.user_id = ? AND fm.status = 'active' "
            "ORDER BY f.is_personal DESC, f.created_at ASC",
            (user_id,),
        ).fetchall()
    return [_firm_from_row(r) for r in rows]


def set_active_firm(user_id: int, firm_id: int) -> bool:
    """Switch the user's active workspace. Validates membership."""
    with db() as conn:
        ok = conn.execute(
            "SELECT 1 FROM firm_members WHERE user_id = ? AND firm_id = ? AND status = 'active'",
            (user_id, firm_id),
        ).fetchone()
        if not ok:
            return False
        conn.execute("UPDATE users SET active_firm_id = ? WHERE id = ?",
                     (firm_id, user_id))
    return True


def get_active_firm(user_id: int) -> Firm | None:
    with db() as conn:
        row = conn.execute(
            "SELECT f.* FROM firms f "
            "JOIN users u ON u.active_firm_id = f.id "
            "WHERE u.id = ?",
            (user_id,),
        ).fetchone()
    return _firm_from_row(row) if row else None


# ── members ───────────────────────────────────────────────────────────────

def add_member(firm_id: int, user_id: int, role: str = "lawyer") -> FirmMember:
    if role not in FIRM_ROLES:
        raise ValueError(f"unknown role: {role!r}")
    now = _utcnow()
    with db() as conn:
        # Idempotent — re-activate a 'removed' record if present.
        existing = conn.execute(
            "SELECT id FROM firm_members WHERE firm_id = ? AND user_id = ?",
            (firm_id, user_id),
        ).fetchone()
        if existing:
            conn.execute(
                "UPDATE firm_members SET role = ?, status = 'active', joined_at = ? "
                "WHERE id = ?",
                (role, now, existing["id"]),
            )
            mid = existing["id"]
        else:
            cur = conn.execute(
                "INSERT INTO firm_members (firm_id, user_id, role, status, joined_at) "
                "VALUES (?, ?, ?, 'active', ?)",
                (firm_id, user_id, role, now),
            )
            mid = cur.lastrowid
        row = conn.execute(
            "SELECT fm.*, u.username FROM firm_members fm "
            "JOIN users u ON u.id = fm.user_id WHERE fm.id = ?",
            (mid,),
        ).fetchone()
    return _member_from_row(row)


def remove_member(firm_id: int, member_id: int) -> bool:
    """Soft-remove (status='removed'). Owner cannot be removed."""
    with db() as conn:
        row = conn.execute(
            "SELECT user_id, role FROM firm_members WHERE id = ? AND firm_id = ?",
            (member_id, firm_id),
        ).fetchone()
        if not row:
            return False
        if row["role"] == "owner":
            return False
        conn.execute(
            "UPDATE firm_members SET status = 'removed' WHERE id = ?",
            (member_id,),
        )
    return True


def update_member_role(firm_id: int, member_id: int, new_role: str) -> bool:
    if new_role not in FIRM_ROLES:
        raise ValueError(f"unknown role: {new_role!r}")
    with db() as conn:
        row = conn.execute(
            "SELECT role FROM firm_members WHERE id = ? AND firm_id = ?",
            (member_id, firm_id),
        ).fetchone()
        if not row:
            return False
        # Cannot demote the only owner.
        if row["role"] == "owner" and new_role != "owner":
            count = conn.execute(
                "SELECT COUNT(*) FROM firm_members "
                "WHERE firm_id = ? AND role = 'owner' AND status = 'active'",
                (firm_id,),
            ).fetchone()[0]
            if count <= 1:
                return False
        conn.execute(
            "UPDATE firm_members SET role = ? WHERE id = ?",
            (new_role, member_id),
        )
    return True


def list_members(firm_id: int, *, include_removed: bool = False) -> list[FirmMember]:
    where = "fm.firm_id = ?" + ("" if include_removed else " AND fm.status = 'active'")
    with db() as conn:
        rows = conn.execute(
            f"SELECT fm.*, u.username FROM firm_members fm "
            f"JOIN users u ON u.id = fm.user_id "
            f"WHERE {where} "
            f"ORDER BY CASE fm.role "
            f"  WHEN 'owner' THEN 0 WHEN 'partner' THEN 1 WHEN 'lawyer' THEN 2 "
            f"  WHEN 'paralegal' THEN 3 WHEN 'assistant' THEN 4 ELSE 9 END, "
            f"u.username ASC",
            (firm_id,),
        ).fetchall()
    return [_member_from_row(r) for r in rows]


def get_member_by_user_firm(user_id: int, firm_id: int) -> FirmMember | None:
    with db() as conn:
        row = conn.execute(
            "SELECT fm.*, u.username FROM firm_members fm "
            "JOIN users u ON u.id = fm.user_id "
            "WHERE fm.user_id = ? AND fm.firm_id = ? AND fm.status = 'active'",
            (user_id, firm_id),
        ).fetchone()
    return _member_from_row(row) if row else None


def get_user_role_in_firm(user_id: int, firm_id: int) -> str | None:
    """Return the active role string ('owner'|...) or None if not a member."""
    m = get_member_by_user_firm(user_id, firm_id)
    return m.role if m else None


# ── case assignments + firm-scoped case visibility ────────────────────────

def assign_member_to_case(case_id: str, member_id: int,
                          role_in_case: str = "collaborator") -> CaseAssignment:
    now = _utcnow()
    with db() as conn:
        existing = conn.execute(
            "SELECT id FROM case_assignments WHERE case_id = ? AND member_id = ?",
            (case_id, member_id),
        ).fetchone()
        if existing:
            conn.execute(
                "UPDATE case_assignments SET role_in_case = ?, assigned_at = ? "
                "WHERE id = ?",
                (role_in_case, now, existing["id"]),
            )
            aid = existing["id"]
        else:
            cur = conn.execute(
                "INSERT INTO case_assignments (case_id, member_id, role_in_case, assigned_at) "
                "VALUES (?, ?, ?, ?)",
                (case_id, member_id, role_in_case, now),
            )
            aid = cur.lastrowid
        row = conn.execute(
            "SELECT ca.*, fm.user_id, u.username FROM case_assignments ca "
            "JOIN firm_members fm ON fm.id = ca.member_id "
            "JOIN users u ON u.id = fm.user_id WHERE ca.id = ?",
            (aid,),
        ).fetchone()
    return CaseAssignment(
        id=row["id"], case_id=row["case_id"], member_id=row["member_id"],
        user_id=row["user_id"], username=row["username"],
        role_in_case=row["role_in_case"], assigned_at=row["assigned_at"],
    )


def remove_assignment(case_id: str, member_id: int) -> bool:
    with db() as conn:
        cur = conn.execute(
            "DELETE FROM case_assignments WHERE case_id = ? AND member_id = ?",
            (case_id, member_id),
        )
    return cur.rowcount > 0


def list_assignments_for_case(case_id: str) -> list[CaseAssignment]:
    with db() as conn:
        rows = conn.execute(
            "SELECT ca.*, fm.user_id, u.username FROM case_assignments ca "
            "JOIN firm_members fm ON fm.id = ca.member_id "
            "JOIN users u ON u.id = fm.user_id "
            "WHERE ca.case_id = ? "
            "ORDER BY ca.assigned_at ASC",
            (case_id,),
        ).fetchall()
    return [
        CaseAssignment(
            id=r["id"], case_id=r["case_id"], member_id=r["member_id"],
            user_id=r["user_id"], username=r["username"],
            role_in_case=r["role_in_case"], assigned_at=r["assigned_at"],
        ) for r in rows
    ]


def get_case_for_member(case_id: str, user_id: int, firm_id: int) -> Case | None:
    """Firm-scoped fetch with visibility rules.

    Owner/partner: any case in the firm.
    Other roles:   only cases they created OR are assigned to.
    """
    role = get_user_role_in_firm(user_id, firm_id)
    if role is None:
        return None
    can_see_all = ROLE_PERMISSIONS.get(role, {}).get("all_cases", False)
    with db() as conn:
        if can_see_all:
            row = conn.execute(
                "SELECT * FROM cases WHERE id = ? AND firm_id = ?",
                (case_id, firm_id),
            ).fetchone()
        else:
            row = conn.execute(
                "SELECT c.* FROM cases c "
                "WHERE c.id = ? AND c.firm_id = ? AND ("
                "  c.user_id = ? OR EXISTS ("
                "    SELECT 1 FROM case_assignments ca "
                "    JOIN firm_members fm ON fm.id = ca.member_id "
                "    WHERE ca.case_id = c.id AND fm.user_id = ?"
                "  )"
                ")",
                (case_id, firm_id, user_id, user_id),
            ).fetchone()
    return _case_from_row(row) if row else None


def list_cases_for_member(user_id: int, firm_id: int) -> list[Case]:
    """Same visibility rules as get_case_for_member."""
    role = get_user_role_in_firm(user_id, firm_id)
    if role is None:
        return []
    can_see_all = ROLE_PERMISSIONS.get(role, {}).get("all_cases", False)
    with db() as conn:
        if can_see_all:
            rows = conn.execute(
                "SELECT * FROM cases WHERE firm_id = ? ORDER BY updated_at DESC",
                (firm_id,),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT DISTINCT c.* FROM cases c "
                "LEFT JOIN case_assignments ca ON ca.case_id = c.id "
                "LEFT JOIN firm_members fm ON fm.id = ca.member_id "
                "WHERE c.firm_id = ? AND (c.user_id = ? OR fm.user_id = ?) "
                "ORDER BY c.updated_at DESC",
                (firm_id, user_id, user_id),
            ).fetchall()
    return [_case_from_row(r) for r in rows]


# ── case parties (conflict-of-interest source) ────────────────────────────

def add_case_party(case_id: str, firm_id: int, display_name: str,
                   side: str = "unknown", source: str | None = None) -> CaseParty | None:
    display_name = (display_name or "").strip()
    if len(display_name) < 2:
        return None
    norm = re.sub(r"\s+", " ", display_name.lower()).strip()
    now = _utcnow()
    with db() as conn:
        # Dedupe within the same case.
        existing = conn.execute(
            "SELECT id FROM case_parties WHERE case_id = ? AND name = ?",
            (case_id, norm),
        ).fetchone()
        if existing:
            return None
        cur = conn.execute(
            "INSERT INTO case_parties (case_id, firm_id, name, display_name, side, source, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (case_id, firm_id, norm, display_name, side, source, now),
        )
        pid = cur.lastrowid
    return CaseParty(id=pid, case_id=case_id, firm_id=firm_id,
                     name=norm, display_name=display_name,
                     side=side, source=source, created_at=now)


def search_parties_in_firm(firm_id: int, query: str) -> list[dict]:
    """Substring + token-overlap search; returns matched parties with case meta."""
    q = re.sub(r"\s+", " ", (query or "").lower()).strip()
    if len(q) < 2:
        return []
    with db() as conn:
        rows = conn.execute(
            "SELECT p.*, c.title AS case_title, c.user_id AS case_creator "
            "FROM case_parties p JOIN cases c ON c.id = p.case_id "
            "WHERE p.firm_id = ? AND (p.name LIKE ? OR p.name = ?)",
            (firm_id, f"%{q}%", q),
        ).fetchall()
    out = []
    q_tokens = set(q.split())
    for r in rows:
        toks = set(r["name"].split())
        overlap = len(q_tokens & toks) / max(len(q_tokens), 1)
        out.append({
            "id": r["id"], "case_id": r["case_id"], "case_title": r["case_title"],
            "case_creator_user_id": r["case_creator"],
            "name": r["display_name"], "side": r["side"],
            "source": r["source"], "created_at": r["created_at"],
            "match_score": round(overlap, 2),
        })
    out.sort(key=lambda d: d["match_score"], reverse=True)
    return out


def firm_capacity_snapshot(firm_id: int, *, horizon_days: int = 7) -> list[dict]:
    """One row per active firm member with workload signals.

    Columns we surface (every member, even with zero work):
      - active_cases: total cases the member created or is assigned to
      - upcoming_events: count of events in the next horizon_days
      - upcoming_hearings: subset where kind='seance' (highest gravity)
      - urgent_deadlines: events with kind='afat' starting within horizon

    The score is a simple weighted sum so the UI can sort. We deliberately
    avoid baking judgment into a percentage — a partner with 30 cases isn't
    necessarily over-loaded; the UI compares relative to peers.
    """
    horizon_end = (datetime.now(UTC)
                   + timedelta(days=horizon_days)).strftime("%Y-%m-%dT%H:%M:%SZ")
    now_iso = _utcnow()
    members = list_members(firm_id)
    out = []
    with db() as conn:
        for m in members:
            # Active cases: created OR assigned (deduped)
            row = conn.execute(
                "SELECT COUNT(DISTINCT c.id) AS n FROM cases c "
                "LEFT JOIN case_assignments ca ON ca.case_id = c.id "
                "LEFT JOIN firm_members fm ON fm.id = ca.member_id "
                "WHERE c.firm_id = ? AND (c.user_id = ? OR fm.user_id = ?)",
                (firm_id, m.user_id, m.user_id),
            ).fetchone()
            active_cases = row["n"] if row else 0
            # Upcoming events on cases in this firm
            row = conn.execute(
                "SELECT "
                "  SUM(CASE WHEN 1=1 THEN 1 ELSE 0 END) AS total, "
                "  SUM(CASE WHEN e.kind='seance' THEN 1 ELSE 0 END) AS hearings, "
                "  SUM(CASE WHEN e.kind='afat' THEN 1 ELSE 0 END) AS deadlines "
                "FROM events e "
                "JOIN cases c ON c.id = e.case_id "
                "WHERE c.firm_id = ? AND e.user_id = ? "
                "AND e.starts_at >= ? AND e.starts_at < ? "
                "AND e.done = 0",
                (firm_id, m.user_id, now_iso, horizon_end),
            ).fetchone()
            upcoming = (row["total"] or 0) if row else 0
            hearings = (row["hearings"] or 0) if row else 0
            deadlines = (row["deadlines"] or 0) if row else 0
            score = active_cases + (hearings * 3) + (deadlines * 2) + upcoming
            out.append({
                "member_id": m.id,
                "user_id": m.user_id,
                "username": m.username,
                "role": m.role,
                "role_label": ROLE_LABELS.get(m.role, m.role),
                "active_cases": active_cases,
                "upcoming_events": upcoming,
                "upcoming_hearings": hearings,
                "urgent_deadlines": deadlines,
                "load_score": score,
            })
    out.sort(key=lambda r: r["load_score"], reverse=True)
    return out


def find_substitutes_for_event(event_id: str) -> list[dict] | None:
    """Rank candidates who could cover this hearing.

    Eligible: firm members with role in {owner, partner, lawyer} (paralegals
    can't appear in court alone). Sorted by load_score asc, with a
    `has_conflict` flag for anyone with another event overlapping the
    hearing's time window — they're shown last but not hidden, since the
    user might decide to reschedule the conflicting one.
    """
    with db() as conn:
        ev_row = conn.execute(
            "SELECT e.*, c.firm_id FROM events e "
            "JOIN cases c ON c.id = e.case_id "
            "WHERE e.id = ?",
            (event_id,),
        ).fetchone()
        if not ev_row or not ev_row["firm_id"]:
            return None
        firm_id = ev_row["firm_id"]
        starts = ev_row["starts_at"]
        ends = ev_row["ends_at"] or starts
        original_user = ev_row["user_id"]

    capacity = firm_capacity_snapshot(firm_id, horizon_days=7)
    eligible_roles = {"owner", "partner", "lawyer"}
    candidates = []
    with db() as conn:
        for cap in capacity:
            if cap["user_id"] == original_user:
                continue
            if cap["role"] not in eligible_roles:
                continue
            # Conflict detection: any event overlapping [starts, ends].
            row = conn.execute(
                "SELECT COUNT(*) AS n FROM events "
                "WHERE user_id = ? AND id != ? "
                "AND ((starts_at < ? AND COALESCE(ends_at, starts_at) > ?) "
                "  OR (starts_at >= ? AND starts_at < ?))",
                (cap["user_id"], event_id, ends, starts, starts, ends),
            ).fetchone()
            has_conflict = (row["n"] or 0) > 0
            candidates.append({
                **cap,
                "has_conflict": has_conflict,
            })
    candidates.sort(key=lambda c: (c["has_conflict"], c["load_score"]))
    return candidates


def list_events_for_firm(
    firm_id: int, *, start: str | None = None, end: str | None = None,
) -> list[tuple[Event, str]]:
    """All events tied to a case in `firm_id`. Returns (event, creator_username) pairs.

    Personal events (no case_id) are excluded — those stay private to the
    individual member; the master calendar surfaces shared work only.
    """
    clauses = ["c.firm_id = ?"]
    params: list = [firm_id]
    if start:
        clauses.append("e.starts_at >= ?")
        params.append(start)
    if end:
        clauses.append("e.starts_at < ?")
        params.append(end)
    sql = ("SELECT e.*, u.username AS creator_username "
           "FROM events e "
           "JOIN cases c ON c.id = e.case_id "
           "JOIN users u ON u.id = e.user_id "
           "WHERE " + " AND ".join(clauses) + " "
           "ORDER BY e.starts_at ASC")
    with db() as conn:
        rows = conn.execute(sql, params).fetchall()
    return [(_event_from_row(r), r["creator_username"]) for r in rows]


# ── case drafts (review loop) ─────────────────────────────────────────────

DRAFT_KINDS = ("note", "atto", "research", "memo")
DRAFT_KIND_LABELS = {
    "note": "Shënim",
    "atto": "Akt procedural",
    "research": "Kërkim ligjor",
    "memo": "Memorandum",
}
DRAFT_STATUSES = ("pending", "approved", "needs_changes")


@dataclass
class CaseDraft:
    id: int
    case_id: str
    firm_id: int
    author_id: int
    author_username: str
    case_title: str
    title: str
    content: str
    kind: str
    status: str
    reviewer_id: int | None
    reviewer_username: str | None
    review_comment: str | None
    reviewed_at: str | None
    created_at: str
    updated_at: str


def _draft_from_row(r: sqlite3.Row) -> CaseDraft:
    return CaseDraft(
        id=r["id"], case_id=r["case_id"], firm_id=r["firm_id"],
        author_id=r["author_id"], author_username=r["author_username"],
        case_title=r["case_title"],
        title=r["title"], content=r["content"], kind=r["kind"],
        status=r["status"],
        reviewer_id=r["reviewer_id"],
        reviewer_username=r["reviewer_username"],
        review_comment=r["review_comment"],
        reviewed_at=r["reviewed_at"],
        created_at=r["created_at"], updated_at=r["updated_at"],
    )


def create_draft(case_id: str, firm_id: int, author_id: int, *,
                 title: str, content: str, kind: str = "note") -> CaseDraft:
    if kind not in DRAFT_KINDS:
        raise ValueError(f"unknown draft kind: {kind!r}")
    title = (title or "").strip() or "Bozzë pa titull"
    content = (content or "").strip()
    if len(content) < 10:
        raise ValueError("draft content too short (min 10 chars)")
    now = _utcnow()
    with db() as conn:
        cur = conn.execute(
            "INSERT INTO case_drafts (case_id, firm_id, author_id, title, content, "
            "kind, status, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, 'pending', ?, ?)",
            (case_id, firm_id, author_id, title, content, kind, now, now),
        )
        did = cur.lastrowid
    return get_draft(did)  # type: ignore[return-value]


def get_draft(draft_id: int) -> CaseDraft | None:
    with db() as conn:
        row = conn.execute(
            "SELECT d.*, "
            "  ua.username AS author_username, "
            "  ur.username AS reviewer_username, "
            "  c.title AS case_title "
            "FROM case_drafts d "
            "JOIN users ua ON ua.id = d.author_id "
            "LEFT JOIN users ur ON ur.id = d.reviewer_id "
            "JOIN cases c ON c.id = d.case_id "
            "WHERE d.id = ?",
            (draft_id,),
        ).fetchone()
    return _draft_from_row(row) if row else None


def list_drafts_for_case(case_id: str) -> list[CaseDraft]:
    with db() as conn:
        rows = conn.execute(
            "SELECT d.*, ua.username AS author_username, "
            "  ur.username AS reviewer_username, c.title AS case_title "
            "FROM case_drafts d "
            "JOIN users ua ON ua.id = d.author_id "
            "LEFT JOIN users ur ON ur.id = d.reviewer_id "
            "JOIN cases c ON c.id = d.case_id "
            "WHERE d.case_id = ? "
            "ORDER BY d.created_at DESC",
            (case_id,),
        ).fetchall()
    return [_draft_from_row(r) for r in rows]


def list_review_queue(firm_id: int, *, status: str = "pending",
                      author_id: int | None = None) -> list[CaseDraft]:
    """Drafts waiting for review (or filtered by status). When `author_id`
    is given, scope to that author — used for paralegals who should see
    only their own submissions, not peers'."""
    clauses = ["d.firm_id = ?", "d.status = ?"]
    params: list = [firm_id, status]
    if author_id is not None:
        clauses.append("d.author_id = ?")
        params.append(author_id)
    sql = ("SELECT d.*, ua.username AS author_username, "
           "  ur.username AS reviewer_username, c.title AS case_title "
           "FROM case_drafts d "
           "JOIN users ua ON ua.id = d.author_id "
           "LEFT JOIN users ur ON ur.id = d.reviewer_id "
           "JOIN cases c ON c.id = d.case_id "
           "WHERE " + " AND ".join(clauses) + " "
           "ORDER BY d.created_at ASC")
    with db() as conn:
        rows = conn.execute(sql, params).fetchall()
    return [_draft_from_row(r) for r in rows]


def review_draft(draft_id: int, reviewer_id: int, *,
                 status: str, comment: str | None = None) -> CaseDraft | None:
    if status not in ("approved", "needs_changes"):
        raise ValueError(f"invalid review status: {status!r}")
    now = _utcnow()
    with db() as conn:
        cur = conn.execute(
            "UPDATE case_drafts SET status = ?, reviewer_id = ?, "
            "review_comment = ?, reviewed_at = ?, updated_at = ? "
            "WHERE id = ? AND status = 'pending'",
            (status, reviewer_id, comment, now, now, draft_id),
        )
        if cur.rowcount == 0:
            return None
    return get_draft(draft_id)


def delete_draft(draft_id: int, author_id: int) -> bool:
    """Authors can withdraw their own pending drafts. Reviewed drafts stay
    as audit trail and can't be deleted via this path."""
    with db() as conn:
        cur = conn.execute(
            "DELETE FROM case_drafts "
            "WHERE id = ? AND author_id = ? AND status = 'pending'",
            (draft_id, author_id),
        )
    return cur.rowcount > 0


def list_parties_in_case(case_id: str) -> list[CaseParty]:
    with db() as conn:
        rows = conn.execute(
            "SELECT * FROM case_parties WHERE case_id = ? ORDER BY created_at ASC",
            (case_id,),
        ).fetchall()
    return [
        CaseParty(
            id=r["id"], case_id=r["case_id"], firm_id=r["firm_id"],
            name=r["name"], display_name=r["display_name"],
            side=r["side"], source=r["source"], created_at=r["created_at"],
        ) for r in rows
    ]


# ── V8.3 client portal ──────────────────────────────────────────────────────

@dataclass
class ClientContact:
    id: int
    case_id: str
    firm_id: int
    name: str
    phone: str | None
    email: str | None
    portal_token: str
    last_viewed_at: str | None
    created_at: str


@dataclass
class CaseStatusUpdate:
    id: int
    case_id: str
    firm_id: int
    author_id: int
    author_username: str | None
    body_sq: str
    kind: str
    source_kind: str | None
    created_at: str


def _client_from_row(r: sqlite3.Row) -> ClientContact:
    return ClientContact(
        id=r["id"], case_id=r["case_id"], firm_id=r["firm_id"],
        name=r["name"], phone=r["phone"], email=r["email"],
        portal_token=r["portal_token"],
        last_viewed_at=r["last_viewed_at"],
        created_at=r["created_at"],
    )


def _new_portal_token() -> str:
    # 32 url-safe chars ≈ 192 bits — collision-free for any realistic install.
    import secrets as _s
    return _s.token_urlsafe(24)


def create_client_contact(
    case_id: str, firm_id: int, name: str,
    phone: str | None = None, email: str | None = None,
) -> ClientContact:
    name = (name or "").strip()
    if not name:
        raise ValueError("client name required")
    phone = (phone or "").strip() or None
    email = (email or "").strip() or None
    now = _utcnow()
    token = _new_portal_token()
    with db() as conn:
        # extremely unlikely retry — but cheap
        for _ in range(3):
            try:
                cur = conn.execute(
                    "INSERT INTO client_contacts "
                    "(case_id, firm_id, name, phone, email, portal_token, created_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (case_id, firm_id, name, phone, email, token, now),
                )
                cid = cur.lastrowid
                break
            except sqlite3.IntegrityError:
                token = _new_portal_token()
        else:
            raise RuntimeError("could not allocate unique portal token")
    return get_client_contact(cid)  # type: ignore[return-value]


def get_client_contact(client_id: int) -> ClientContact | None:
    with db() as conn:
        row = conn.execute(
            "SELECT * FROM client_contacts WHERE id = ?", (client_id,),
        ).fetchone()
    return _client_from_row(row) if row else None


def get_client_by_token(token: str) -> ClientContact | None:
    if not token:
        return None
    with db() as conn:
        row = conn.execute(
            "SELECT * FROM client_contacts WHERE portal_token = ?", (token,),
        ).fetchone()
    return _client_from_row(row) if row else None


def list_client_contacts_for_case(case_id: str) -> list[ClientContact]:
    with db() as conn:
        rows = conn.execute(
            "SELECT * FROM client_contacts WHERE case_id = ? "
            "ORDER BY created_at ASC",
            (case_id,),
        ).fetchall()
    return [_client_from_row(r) for r in rows]


def regenerate_portal_token(client_id: int) -> ClientContact | None:
    new_token = _new_portal_token()
    with db() as conn:
        for _ in range(3):
            try:
                cur = conn.execute(
                    "UPDATE client_contacts SET portal_token = ? WHERE id = ?",
                    (new_token, client_id),
                )
                if cur.rowcount == 0:
                    return None
                break
            except sqlite3.IntegrityError:
                new_token = _new_portal_token()
        else:
            raise RuntimeError("could not allocate unique portal token")
    return get_client_contact(client_id)


def delete_client_contact(client_id: int, case_id: str) -> bool:
    with db() as conn:
        cur = conn.execute(
            "DELETE FROM client_contacts WHERE id = ? AND case_id = ?",
            (client_id, case_id),
        )
    return cur.rowcount > 0


def mark_portal_viewed(token: str) -> None:
    with db() as conn:
        conn.execute(
            "UPDATE client_contacts SET last_viewed_at = ? WHERE portal_token = ?",
            (_utcnow(), token),
        )


# ── V8.3 status updates (client-facing) ─────────────────────────────────────

CLIENT_UPDATE_KINDS: tuple[str, ...] = (
    "status", "milestone", "document_request", "translation",
)


def _status_update_from_row(r: sqlite3.Row) -> CaseStatusUpdate:
    keys = r.keys()
    return CaseStatusUpdate(
        id=r["id"], case_id=r["case_id"], firm_id=r["firm_id"],
        author_id=r["author_id"],
        author_username=(r["author_username"]
                         if "author_username" in keys else None),
        body_sq=r["body_sq"], kind=r["kind"],
        source_kind=r["source_kind"], created_at=r["created_at"],
    )


def create_status_update(
    case_id: str, firm_id: int, author_id: int,
    body_sq: str, *,
    kind: str = "status", source_kind: str = "manual",
) -> CaseStatusUpdate:
    body_sq = (body_sq or "").strip()
    if not body_sq:
        raise ValueError("status update body required")
    if kind not in CLIENT_UPDATE_KINDS:
        raise ValueError(f"invalid update kind: {kind!r}")
    now = _utcnow()
    with db() as conn:
        cur = conn.execute(
            "INSERT INTO case_status_updates "
            "(case_id, firm_id, author_id, body_sq, kind, source_kind, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (case_id, firm_id, author_id, body_sq, kind, source_kind, now),
        )
        sid = cur.lastrowid
    return get_status_update(sid)  # type: ignore[return-value]


def get_status_update(update_id: int) -> CaseStatusUpdate | None:
    with db() as conn:
        row = conn.execute(
            "SELECT s.*, u.username AS author_username "
            "FROM case_status_updates s "
            "LEFT JOIN users u ON u.id = s.author_id "
            "WHERE s.id = ?", (update_id,),
        ).fetchone()
    return _status_update_from_row(row) if row else None


def list_status_updates_for_case(case_id: str) -> list[CaseStatusUpdate]:
    with db() as conn:
        rows = conn.execute(
            "SELECT s.*, u.username AS author_username "
            "FROM case_status_updates s "
            "LEFT JOIN users u ON u.id = s.author_id "
            "WHERE s.case_id = ? "
            "ORDER BY s.created_at DESC",
            (case_id,),
        ).fetchall()
    return [_status_update_from_row(r) for r in rows]


def delete_status_update(update_id: int, case_id: str) -> bool:
    with db() as conn:
        cur = conn.execute(
            "DELETE FROM case_status_updates WHERE id = ? AND case_id = ?",
            (update_id, case_id),
        )
    return cur.rowcount > 0


# ── V8.4 contract reviews ───────────────────────────────────────────────────

@dataclass
class ContractReview:
    id: int
    case_id: str
    user_id: int
    contract_label: str | None
    contract_kind: str | None
    source_text: str
    result: dict
    risk_score: int | None
    created_at: str


def _contract_review_from_row(r: sqlite3.Row) -> ContractReview:
    return ContractReview(
        id=r["id"], case_id=r["case_id"], user_id=r["user_id"],
        contract_label=r["contract_label"],
        contract_kind=r["contract_kind"],
        source_text=r["source_text"],
        result=json.loads(r["result_json"]) if r["result_json"] else {},
        risk_score=r["risk_score"], created_at=r["created_at"],
    )


def create_contract_review(
    case_id: str, user_id: int, source_text: str,
    result: dict, *,
    contract_label: str | None = None,
    contract_kind: str | None = None,
    risk_score: int | None = None,
) -> ContractReview:
    now = _utcnow()
    with db() as conn:
        cur = conn.execute(
            "INSERT INTO contract_reviews "
            "(case_id, user_id, contract_label, contract_kind, "
            " source_text, result_json, risk_score, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (case_id, user_id, contract_label, contract_kind,
             source_text, json.dumps(result, ensure_ascii=False),
             risk_score, now),
        )
        rid = cur.lastrowid
    return get_contract_review(rid)  # type: ignore[return-value]


def get_contract_review(review_id: int) -> ContractReview | None:
    with db() as conn:
        row = conn.execute(
            "SELECT * FROM contract_reviews WHERE id = ?", (review_id,),
        ).fetchone()
    return _contract_review_from_row(row) if row else None


def list_contract_reviews_for_case(case_id: str) -> list[ContractReview]:
    with db() as conn:
        rows = conn.execute(
            "SELECT * FROM contract_reviews WHERE case_id = ? "
            "ORDER BY created_at DESC", (case_id,),
        ).fetchall()
    return [_contract_review_from_row(r) for r in rows]


def delete_contract_review(review_id: int, case_id: str) -> bool:
    with db() as conn:
        cur = conn.execute(
            "DELETE FROM contract_reviews WHERE id = ? AND case_id = ?",
            (review_id, case_id),
        )
    return cur.rowcount > 0


# ── V8.5 money layer (time entries + invoices) ─────────────────────────────

# Reference: Tarifa minimale e shërbimeve të avokatisë (Dhoma Kombëtare e
# Avokatisë, RSH). Values in EUR (approx, indicative — the actual tariff
# is in ALL and varies by court level). The lawyer can override per
# entry. We use cents internally to avoid float arithmetic.
ALBANIAN_BAR_TARIFF_EUR = {
    # rate per hour (cents)
    "default": 4000,         # 40 €/h — junior/intake
    "lawyer": 6000,          # 60 €/h — standard avokat
    "partner": 9000,         # 90 €/h — partner
    "senior": 12000,         # 120 €/h — drejtues studio
    "hearing": 8000,         # 80 €/h — perfaqësim ne gjykatë
    "drafting": 7500,        # 75 €/h — hartim akti
    "research": 5500,        # 55 €/h — kërkim juridik
    "travel": 3000,          # 30 €/h — udhetim/zëvendësim
}

ACTIVITY_KIND_LABELS_SQ: dict[str, str] = {
    "work": "Punë e përgjithshme",
    "hearing": "Përfaqësim në gjykatë",
    "meeting": "Takim me klient",
    "travel": "Udhëtim",
    "research": "Kërkim juridik",
    "drafting": "Hartim akti",
}


@dataclass
class TimeEntry:
    id: int
    case_id: str
    user_id: int
    firm_id: int | None
    entry_date: str
    minutes: int
    description: str
    activity_kind: str
    hourly_rate: int        # cents
    currency: str
    billed_invoice_id: int | None
    created_at: str

    @property
    def amount_cents(self) -> int:
        return (self.minutes * self.hourly_rate) // 60


@dataclass
class Invoice:
    id: int
    case_id: str
    firm_id: int | None
    user_id: int
    invoice_no: str
    client_name: str
    client_address: str | None
    issue_date: str
    due_date: str | None
    currency: str
    subtotal_cents: int
    vat_rate: int
    vat_cents: int
    total_cents: int
    status: str
    notes: str | None
    line_items: list
    markdown: str | None
    created_at: str
    updated_at: str


def _time_entry_from_row(r: sqlite3.Row) -> TimeEntry:
    return TimeEntry(
        id=r["id"], case_id=r["case_id"], user_id=r["user_id"],
        firm_id=r["firm_id"], entry_date=r["entry_date"],
        minutes=r["minutes"], description=r["description"],
        activity_kind=r["activity_kind"], hourly_rate=r["hourly_rate"],
        currency=r["currency"], billed_invoice_id=r["billed_invoice_id"],
        created_at=r["created_at"],
    )


def _invoice_from_row(r: sqlite3.Row) -> Invoice:
    return Invoice(
        id=r["id"], case_id=r["case_id"], firm_id=r["firm_id"],
        user_id=r["user_id"], invoice_no=r["invoice_no"],
        client_name=r["client_name"], client_address=r["client_address"],
        issue_date=r["issue_date"], due_date=r["due_date"],
        currency=r["currency"],
        subtotal_cents=r["subtotal_cents"], vat_rate=r["vat_rate"],
        vat_cents=r["vat_cents"], total_cents=r["total_cents"],
        status=r["status"], notes=r["notes"],
        line_items=json.loads(r["line_items_json"]) if r["line_items_json"] else [],
        markdown=r["markdown"], created_at=r["created_at"],
        updated_at=r["updated_at"],
    )


def create_time_entry(
    case_id: str, user_id: int, *,
    minutes: int, description: str,
    activity_kind: str = "work",
    hourly_rate: int | None = None,
    currency: str = "EUR",
    entry_date: str | None = None,
    firm_id: int | None = None,
) -> TimeEntry:
    if minutes <= 0:
        raise ValueError("minutes must be > 0")
    description = (description or "").strip()
    if not description:
        raise ValueError("description required")
    if activity_kind not in ACTIVITY_KIND_LABELS_SQ:
        raise ValueError(f"invalid activity_kind: {activity_kind}")
    if hourly_rate is None:
        rate_key = activity_kind if activity_kind in ALBANIAN_BAR_TARIFF_EUR else "default"
        hourly_rate = ALBANIAN_BAR_TARIFF_EUR.get(rate_key, 4000)
    if hourly_rate < 0:
        raise ValueError("hourly_rate must be >= 0")
    entry_date = entry_date or datetime.now(UTC).strftime("%Y-%m-%d")
    now = _utcnow()
    with db() as conn:
        cur = conn.execute(
            "INSERT INTO time_entries (case_id, user_id, firm_id, entry_date, "
            "minutes, description, activity_kind, hourly_rate, currency, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (case_id, user_id, firm_id, entry_date, minutes, description,
             activity_kind, hourly_rate, currency, now),
        )
        eid = cur.lastrowid
    return get_time_entry(eid)  # type: ignore[return-value]


def get_time_entry(entry_id: int) -> TimeEntry | None:
    with db() as conn:
        row = conn.execute(
            "SELECT * FROM time_entries WHERE id = ?", (entry_id,),
        ).fetchone()
    return _time_entry_from_row(row) if row else None


def list_time_entries_for_case(case_id: str, *,
                               unbilled_only: bool = False) -> list[TimeEntry]:
    sql = "SELECT * FROM time_entries WHERE case_id = ?"
    params: list = [case_id]
    if unbilled_only:
        sql += " AND billed_invoice_id IS NULL"
    sql += " ORDER BY entry_date DESC, id DESC"
    with db() as conn:
        rows = conn.execute(sql, params).fetchall()
    return [_time_entry_from_row(r) for r in rows]


def delete_time_entry(entry_id: int, case_id: str) -> bool:
    """Deleting a billed entry is allowed (audit lives on the invoice)."""
    with db() as conn:
        cur = conn.execute(
            "DELETE FROM time_entries WHERE id = ? AND case_id = ?",
            (entry_id, case_id),
        )
    return cur.rowcount > 0


def _next_invoice_no(firm_id: int | None) -> str:
    """INV-YYYY-NNNN. Per-firm sequence (per-user if no firm)."""
    year = datetime.now(UTC).year
    prefix = f"INV-{year}-"
    with db() as conn:
        if firm_id is not None:
            row = conn.execute(
                "SELECT invoice_no FROM invoices WHERE firm_id = ? "
                "AND invoice_no LIKE ? ORDER BY id DESC LIMIT 1",
                (firm_id, prefix + "%"),
            ).fetchone()
        else:
            row = conn.execute(
                "SELECT invoice_no FROM invoices WHERE invoice_no LIKE ? "
                "ORDER BY id DESC LIMIT 1",
                (prefix + "%",),
            ).fetchone()
    if row and row["invoice_no"].startswith(prefix):
        try:
            n = int(row["invoice_no"][len(prefix):])
        except ValueError:
            n = 0
        n += 1
    else:
        n = 1
    return f"{prefix}{n:04d}"


def create_invoice_from_unbilled(
    case_id: str, user_id: int, *,
    client_name: str,
    client_address: str | None = None,
    vat_rate: int = 0,
    notes: str | None = None,
    due_date: str | None = None,
    firm_id: int | None = None,
) -> Invoice:
    client_name = (client_name or "").strip()
    if not client_name:
        raise ValueError("client_name required")
    entries = list_time_entries_for_case(case_id, unbilled_only=True)
    if not entries:
        raise ValueError("no unbilled time entries for this case")
    currency = entries[0].currency
    line_items = []
    subtotal = 0
    for e in entries:
        amt = e.amount_cents
        subtotal += amt
        line_items.append({
            "entry_id": e.id,
            "date": e.entry_date,
            "kind": e.activity_kind,
            "kind_label": ACTIVITY_KIND_LABELS_SQ.get(e.activity_kind, e.activity_kind),
            "description": e.description,
            "minutes": e.minutes,
            "hours": round(e.minutes / 60.0, 2),
            "rate_cents": e.hourly_rate,
            "amount_cents": amt,
        })
    vat_cents = (subtotal * vat_rate) // 100
    total = subtotal + vat_cents
    issue_date = datetime.now(UTC).strftime("%Y-%m-%d")
    invoice_no = _next_invoice_no(firm_id)
    now = _utcnow()
    md = _render_invoice_markdown(
        invoice_no=invoice_no, issue_date=issue_date, due_date=due_date,
        client_name=client_name, client_address=client_address,
        currency=currency, line_items=line_items,
        subtotal_cents=subtotal, vat_rate=vat_rate, vat_cents=vat_cents,
        total_cents=total, notes=notes,
    )
    with db() as conn:
        cur = conn.execute(
            "INSERT INTO invoices (case_id, firm_id, user_id, invoice_no, "
            "client_name, client_address, issue_date, due_date, currency, "
            "subtotal_cents, vat_rate, vat_cents, total_cents, status, notes, "
            "line_items_json, markdown, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'draft', ?, ?, ?, ?, ?)",
            (case_id, firm_id, user_id, invoice_no, client_name, client_address,
             issue_date, due_date, currency, subtotal, vat_rate, vat_cents, total,
             notes, json.dumps(line_items, ensure_ascii=False), md, now, now),
        )
        inv_id = cur.lastrowid
        # Mark entries as billed
        conn.execute(
            "UPDATE time_entries SET billed_invoice_id = ? "
            "WHERE id IN (" + ",".join("?" * len(entries)) + ")",
            [inv_id] + [e.id for e in entries],
        )
    return get_invoice(inv_id)  # type: ignore[return-value]


def get_invoice(invoice_id: int) -> Invoice | None:
    with db() as conn:
        row = conn.execute(
            "SELECT * FROM invoices WHERE id = ?", (invoice_id,),
        ).fetchone()
    return _invoice_from_row(row) if row else None


def list_invoices_for_case(case_id: str) -> list[Invoice]:
    with db() as conn:
        rows = conn.execute(
            "SELECT * FROM invoices WHERE case_id = ? "
            "ORDER BY created_at DESC", (case_id,),
        ).fetchall()
    return [_invoice_from_row(r) for r in rows]


def update_invoice_status(invoice_id: int, status: str) -> bool:
    if status not in ("draft", "sent", "paid", "cancelled"):
        raise ValueError(f"invalid invoice status: {status}")
    with db() as conn:
        cur = conn.execute(
            "UPDATE invoices SET status = ?, updated_at = ? WHERE id = ?",
            (status, _utcnow(), invoice_id),
        )
    return cur.rowcount > 0


def delete_invoice(invoice_id: int, case_id: str) -> bool:
    """Removes invoice + un-bills entries so they can be re-invoiced."""
    with db() as conn:
        conn.execute(
            "UPDATE time_entries SET billed_invoice_id = NULL "
            "WHERE billed_invoice_id = ?", (invoice_id,),
        )
        cur = conn.execute(
            "DELETE FROM invoices WHERE id = ? AND case_id = ?",
            (invoice_id, case_id),
        )
    return cur.rowcount > 0


def _fmt_money(cents: int, currency: str) -> str:
    sign = "-" if cents < 0 else ""
    cents = abs(cents)
    whole, frac = divmod(cents, 100)
    return f"{sign}{whole:,}.{frac:02d} {currency}"


# ── V8.14 Financial OS — profitability, realization, WIP aging, cashflow ─

def case_profitability(case_id: str) -> dict:
    """Per-matter financial picture: worked vs billed vs paid + margin.

    All amounts in cents. Currency taken from the first time entry; mixed-
    currency cases just report the currency string of the first row (the
    UI can flag the mismatch — this function doesn't FX-convert).
    """
    with db() as conn:
        worked = conn.execute(
            "SELECT COALESCE(SUM((minutes * hourly_rate) / 60), 0) AS cents, "
            "COALESCE(SUM(minutes), 0) AS minutes, "
            "COALESCE(MIN(currency), 'EUR') AS currency "
            "FROM time_entries WHERE case_id = ?", (case_id,)
        ).fetchone()
        billed = conn.execute(
            "SELECT COALESCE(SUM(total_cents), 0) AS cents "
            "FROM invoices WHERE case_id = ? AND status IN ('sent','paid')",
            (case_id,)
        ).fetchone()
        paid = conn.execute(
            "SELECT COALESCE(SUM(total_cents), 0) AS cents "
            "FROM invoices WHERE case_id = ? AND status = 'paid'",
            (case_id,)
        ).fetchone()
        wip = conn.execute(
            "SELECT COALESCE(SUM((minutes * hourly_rate) / 60), 0) AS cents, "
            "COALESCE(SUM(minutes), 0) AS minutes "
            "FROM time_entries WHERE case_id = ? AND billed_invoice_id IS NULL",
            (case_id,)
        ).fetchone()
    worked_c = int(worked["cents"]) if worked else 0
    billed_c = int(billed["cents"]) if billed else 0
    paid_c = int(paid["cents"]) if paid else 0
    wip_c = int(wip["cents"]) if wip else 0
    realization = (paid_c / worked_c) if worked_c else None
    return {
        "case_id": case_id,
        "currency": worked["currency"] if worked else "EUR",
        "worked_cents": worked_c,
        "worked_minutes": int(worked["minutes"]) if worked else 0,
        "billed_cents": billed_c,
        "paid_cents": paid_c,
        "wip_cents": wip_c,
        "wip_minutes": int(wip["minutes"]) if wip else 0,
        "realization_rate": round(realization, 3) if realization is not None else None,
        "outstanding_cents": billed_c - paid_c,
    }


def firm_realization(firm_id: int, since: str | None = None) -> dict:
    """Firm-wide realization: paid / worked across all cases in the firm."""
    where = ["case_id IN (SELECT id FROM cases WHERE firm_id = ?)"]
    params: list = [firm_id]
    if since:
        where.append("entry_date >= ?")
        params.append(since)
    where_clause = " AND ".join(where)
    with db() as conn:
        worked = conn.execute(
            f"SELECT COALESCE(SUM((minutes * hourly_rate) / 60), 0) AS cents "
            f"FROM time_entries WHERE {where_clause}", tuple(params)
        ).fetchone()
        params2 = [firm_id]
        if since:
            params2.append(since)
        paid_clause = "case_id IN (SELECT id FROM cases WHERE firm_id = ?) AND status = 'paid'"
        if since:
            paid_clause += " AND issue_date >= ?"
        paid = conn.execute(
            f"SELECT COALESCE(SUM(total_cents), 0) AS cents "
            f"FROM invoices WHERE {paid_clause}", tuple(params2)
        ).fetchone()
    worked_c = int(worked["cents"]) if worked else 0
    paid_c = int(paid["cents"]) if paid else 0
    return {
        "firm_id": firm_id,
        "since": since,
        "worked_cents": worked_c,
        "paid_cents": paid_c,
        "realization_rate": round(paid_c / worked_c, 3) if worked_c else None,
    }


def wip_aging(firm_id: int) -> list[dict]:
    """Unbilled time entries bucketed by age. One row per case + bucket.

    Buckets: 0-30, 31-60, 61-90, 90+ days. Lawyers chase aged WIP first.
    """
    today_str = _utcnow()[:10]
    with db() as conn:
        rows = conn.execute(
            """
            SELECT te.case_id,
                   c.title AS case_title,
                   julianday(?) - julianday(te.entry_date) AS age_days,
                   te.minutes,
                   te.hourly_rate,
                   te.currency,
                   te.entry_date
            FROM time_entries te
            JOIN cases c ON c.id = te.case_id
            WHERE te.billed_invoice_id IS NULL
              AND c.firm_id = ?
            """,
            (today_str, firm_id),
        ).fetchall()

    buckets: dict[tuple[str, str], dict] = {}
    for r in rows:
        age = float(r["age_days"]) if r["age_days"] is not None else 0.0
        if age <= 30: bucket = "0-30"
        elif age <= 60: bucket = "31-60"
        elif age <= 90: bucket = "61-90"
        else: bucket = "90+"
        key = (r["case_id"], bucket)
        cell = buckets.setdefault(key, {
            "case_id": r["case_id"],
            "case_title": r["case_title"],
            "bucket": bucket,
            "minutes": 0,
            "cents": 0,
            "currency": r["currency"],
            "oldest_entry_date": r["entry_date"],
        })
        cell["minutes"] += int(r["minutes"])
        cell["cents"] += (int(r["minutes"]) * int(r["hourly_rate"])) // 60
        if r["entry_date"] < cell["oldest_entry_date"]:
            cell["oldest_entry_date"] = r["entry_date"]
    return sorted(buckets.values(),
                  key=lambda x: (
                      {"90+": 0, "61-90": 1, "31-60": 2, "0-30": 3}[x["bucket"]],
                      -x["cents"],
                  ))


def cashflow_forecast(firm_id: int, horizon_days: int = 90) -> list[dict]:
    """Projected receivables. One bucket per week ahead; cents per currency.

    Method: for invoices in 'sent' status, count due_date toward forecast;
    if no due_date, default to issue_date + 30. Past-due (due before
    today) stack into the first bucket. 'paid' invoices excluded.
    """
    from datetime import datetime, timedelta
    today = datetime.utcnow().date()
    with db() as conn:
        rows = conn.execute(
            """
            SELECT issue_date, due_date, total_cents, currency
            FROM invoices
            WHERE firm_id = ? AND status = 'sent'
            """,
            (firm_id,),
        ).fetchall()
    buckets: dict[str, dict] = {}
    for r in rows:
        try:
            issue = datetime.strptime(r["issue_date"], "%Y-%m-%d").date()
            due = (datetime.strptime(r["due_date"], "%Y-%m-%d").date()
                   if r["due_date"] else issue + timedelta(days=30))
        except (TypeError, ValueError):
            continue
        delta_days = (due - today).days
        if delta_days < 0:
            label = "past_due"
        elif delta_days > horizon_days:
            label = f"beyond_{horizon_days}d"
        else:
            week = (delta_days // 7) * 7
            label = f"week_{week}"
        cell = buckets.setdefault(label, {
            "bucket": label,
            "cents": 0,
            "currency": r["currency"],
            "count": 0,
        })
        cell["cents"] += int(r["total_cents"])
        cell["count"] += 1
    # stable ordering: past_due, week_0, week_7, …, beyond_*
    def sort_key(b):
        n = b["bucket"]
        if n == "past_due": return (-1, 0)
        if n.startswith("week_"): return (0, int(n.split("_")[1]))
        return (1, 0)
    return sorted(buckets.values(), key=sort_key)


def _render_invoice_markdown(
    *, invoice_no: str, issue_date: str, due_date: str | None,
    client_name: str, client_address: str | None,
    currency: str, line_items: list,
    subtotal_cents: int, vat_rate: int, vat_cents: int,
    total_cents: int, notes: str | None,
) -> str:
    lines = [f"# Faturë {invoice_no}", ""]
    lines.append(f"**Data e lëshimit:** {issue_date}")
    if due_date:
        lines.append(f"**Afati i pagesës:** {due_date}")
    lines.append("")
    lines.append(f"**Klienti:** {client_name}")
    if client_address:
        lines.append(f"**Adresa:** {client_address}")
    lines.append("")
    lines.append("## Shërbime")
    lines.append("")
    lines.append("| Data | Aktivitet | Përshkrim | Orë | Tarifa | Shumë |")
    lines.append("|---|---|---|---:|---:|---:|")
    for li in line_items:
        rate = _fmt_money(li["rate_cents"], currency)
        amt = _fmt_money(li["amount_cents"], currency)
        desc = (li["description"] or "").replace("|", "\\|").replace("\n", " ")
        lines.append(f"| {li['date']} | {li.get('kind_label') or li['kind']} | {desc} | {li['hours']:.2f} | {rate} | {amt} |")
    lines.append("")
    lines.append(f"**Nën-totali:** {_fmt_money(subtotal_cents, currency)}  ")
    if vat_rate:
        lines.append(f"**TVSH ({vat_rate}%):** {_fmt_money(vat_cents, currency)}  ")
    lines.append(f"**TOTALI:** **{_fmt_money(total_cents, currency)}**")
    if notes:
        lines.append("")
        lines.append("## Shënime")
        lines.append(notes)
    lines.append("")
    lines.append("---")
    lines.append("_Tarifa e referuar nga Dhoma Kombëtare e Avokatisë (orientuese). Pagesa në llogarinë bankare të studios._")
    return "\n".join(lines)


# ── V8.6 agentic mode (suggestions + auto-letters) ─────────────────────────

AGENT_SUGGESTION_KINDS = (
    "followup_client", "draft_letter", "request_docs",
    "precedent_alert", "deadline_reminder",
)
AGENT_SUGGESTION_LABELS_SQ: dict[str, str] = {
    "followup_client": "Kontakto klientin",
    "draft_letter": "Hartoj një letër",
    "request_docs": "Kërko dokumente",
    "precedent_alert": "Precedent i ri",
    "deadline_reminder": "Kujto afatin",
}

AUTO_LETTER_KINDS = (
    "client_followup", "payment_reminder",
    "court_followup", "opponent_response", "document_request",
)
AUTO_LETTER_LABELS_SQ: dict[str, str] = {
    "client_followup": "Ndjekje me klientin",
    "payment_reminder": "Kujtesë pagese",
    "court_followup": "Ndjekje gjyqësore",
    "opponent_response": "Përgjigje për kundërshtarin",
    "document_request": "Kërkesë për dokumente",
}


@dataclass
class AgentSuggestion:
    id: int
    case_id: str
    user_id: int
    kind: str
    title: str
    rationale: str
    payload: dict | None
    status: str
    executed_letter_id: int | None
    created_at: str
    updated_at: str


@dataclass
class AutoLetter:
    id: int
    case_id: str
    user_id: int
    kind: str
    recipient: str | None
    subject: str | None
    body_md: str
    notes: str | None
    status: str
    created_at: str
    updated_at: str


def _suggestion_from_row(r: sqlite3.Row) -> AgentSuggestion:
    return AgentSuggestion(
        id=r["id"], case_id=r["case_id"], user_id=r["user_id"],
        kind=r["kind"], title=r["title"], rationale=r["rationale"],
        payload=json.loads(r["payload_json"]) if r["payload_json"] else None,
        status=r["status"],
        executed_letter_id=r["executed_letter_id"],
        created_at=r["created_at"], updated_at=r["updated_at"],
    )


def _letter_from_row(r: sqlite3.Row) -> AutoLetter:
    return AutoLetter(
        id=r["id"], case_id=r["case_id"], user_id=r["user_id"],
        kind=r["kind"], recipient=r["recipient"], subject=r["subject"],
        body_md=r["body_md"], notes=r["notes"], status=r["status"],
        created_at=r["created_at"], updated_at=r["updated_at"],
    )


def create_agent_suggestion(
    case_id: str, user_id: int, *,
    kind: str, title: str, rationale: str,
    payload: dict | None = None,
) -> AgentSuggestion:
    if kind not in AGENT_SUGGESTION_KINDS:
        raise ValueError(f"invalid suggestion kind: {kind}")
    if not title.strip():
        raise ValueError("title required")
    now = _utcnow()
    with db() as conn:
        cur = conn.execute(
            "INSERT INTO agent_suggestions (case_id, user_id, kind, title, "
            "rationale, payload_json, status, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, 'pending', ?, ?)",
            (case_id, user_id, kind, title.strip(), rationale.strip(),
             json.dumps(payload, ensure_ascii=False) if payload else None,
             now, now),
        )
        sid = cur.lastrowid
    return get_agent_suggestion(sid)  # type: ignore[return-value]


def get_agent_suggestion(suggestion_id: int) -> AgentSuggestion | None:
    with db() as conn:
        row = conn.execute(
            "SELECT * FROM agent_suggestions WHERE id = ?", (suggestion_id,),
        ).fetchone()
    return _suggestion_from_row(row) if row else None


def list_agent_suggestions(case_id: str, *,
                           include_dismissed: bool = False) -> list[AgentSuggestion]:
    sql = "SELECT * FROM agent_suggestions WHERE case_id = ?"
    if not include_dismissed:
        sql += " AND status != 'dismissed'"
    sql += " ORDER BY created_at DESC"
    with db() as conn:
        rows = conn.execute(sql, (case_id,)).fetchall()
    return [_suggestion_from_row(r) for r in rows]


def update_agent_suggestion_status(
    suggestion_id: int, status: str, *,
    executed_letter_id: int | None = None,
) -> bool:
    if status not in ("pending", "dismissed", "executed"):
        raise ValueError(f"invalid status: {status}")
    with db() as conn:
        cur = conn.execute(
            "UPDATE agent_suggestions SET status = ?, executed_letter_id = ?, "
            "updated_at = ? WHERE id = ?",
            (status, executed_letter_id, _utcnow(), suggestion_id),
        )
    return cur.rowcount > 0


def delete_agent_suggestion(suggestion_id: int, case_id: str) -> bool:
    with db() as conn:
        cur = conn.execute(
            "DELETE FROM agent_suggestions WHERE id = ? AND case_id = ?",
            (suggestion_id, case_id),
        )
    return cur.rowcount > 0


def create_auto_letter(
    case_id: str, user_id: int, *,
    kind: str, body_md: str,
    recipient: str | None = None,
    subject: str | None = None,
    notes: str | None = None,
) -> AutoLetter:
    if kind not in AUTO_LETTER_KINDS:
        raise ValueError(f"invalid letter kind: {kind}")
    if not body_md.strip():
        raise ValueError("body_md required")
    now = _utcnow()
    with db() as conn:
        cur = conn.execute(
            "INSERT INTO auto_letters (case_id, user_id, kind, recipient, "
            "subject, body_md, notes, status, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, 'draft', ?, ?)",
            (case_id, user_id, kind, recipient, subject, body_md.strip(),
             notes, now, now),
        )
        lid = cur.lastrowid
    return get_auto_letter(lid)  # type: ignore[return-value]


def get_auto_letter(letter_id: int) -> AutoLetter | None:
    with db() as conn:
        row = conn.execute(
            "SELECT * FROM auto_letters WHERE id = ?", (letter_id,),
        ).fetchone()
    return _letter_from_row(row) if row else None


def list_auto_letters_for_case(case_id: str) -> list[AutoLetter]:
    with db() as conn:
        rows = conn.execute(
            "SELECT * FROM auto_letters WHERE case_id = ? "
            "ORDER BY created_at DESC", (case_id,),
        ).fetchall()
    return [_letter_from_row(r) for r in rows]


def update_auto_letter(
    letter_id: int, *,
    body_md: str | None = None,
    subject: str | None = None,
    recipient: str | None = None,
    notes: str | None = None,
    status: str | None = None,
) -> bool:
    fields: list[str] = []
    params: list = []
    if body_md is not None:
        fields.append("body_md = ?"); params.append(body_md.strip())
    if subject is not None:
        fields.append("subject = ?"); params.append(subject)
    if recipient is not None:
        fields.append("recipient = ?"); params.append(recipient)
    if notes is not None:
        fields.append("notes = ?"); params.append(notes)
    if status is not None:
        if status not in ("draft", "sent", "archived"):
            raise ValueError(f"invalid status: {status}")
        fields.append("status = ?"); params.append(status)
    if not fields:
        return False
    fields.append("updated_at = ?"); params.append(_utcnow())
    params.append(letter_id)
    with db() as conn:
        cur = conn.execute(
            f"UPDATE auto_letters SET {', '.join(fields)} WHERE id = ?",
            params,
        )
    return cur.rowcount > 0


def delete_auto_letter(letter_id: int, case_id: str) -> bool:
    with db() as conn:
        cur = conn.execute(
            "DELETE FROM auto_letters WHERE id = ? AND case_id = ?",
            (letter_id, case_id),
        )
    return cur.rowcount > 0


# ── V8.7 hearing notes (in-court companion) ────────────────────────────────

HEARING_NOTE_KINDS = ("note", "question", "ai_reply")


@dataclass
class HearingNote:
    id: int
    case_id: str
    user_id: int
    kind: str
    body_sq: str
    parent_id: int | None
    created_at: str


def _hearing_note_from_row(r: sqlite3.Row) -> HearingNote:
    return HearingNote(
        id=r["id"], case_id=r["case_id"], user_id=r["user_id"],
        kind=r["kind"], body_sq=r["body_sq"],
        parent_id=r["parent_id"], created_at=r["created_at"],
    )


def create_hearing_note(
    case_id: str, user_id: int, *,
    body_sq: str, kind: str = "note",
    parent_id: int | None = None,
) -> HearingNote:
    if kind not in HEARING_NOTE_KINDS:
        raise ValueError(f"invalid kind: {kind}")
    body_sq = (body_sq or "").strip()
    if not body_sq:
        raise ValueError("body_sq required")
    now = _utcnow()
    with db() as conn:
        cur = conn.execute(
            "INSERT INTO hearing_notes (case_id, user_id, kind, body_sq, "
            "parent_id, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (case_id, user_id, kind, body_sq, parent_id, now),
        )
        nid = cur.lastrowid
    return get_hearing_note(nid)  # type: ignore[return-value]


def get_hearing_note(note_id: int) -> HearingNote | None:
    with db() as conn:
        row = conn.execute(
            "SELECT * FROM hearing_notes WHERE id = ?", (note_id,),
        ).fetchone()
    return _hearing_note_from_row(row) if row else None


def list_hearing_notes_for_case(case_id: str) -> list[HearingNote]:
    """Returns chronological (oldest → newest) for replay."""
    with db() as conn:
        rows = conn.execute(
            "SELECT * FROM hearing_notes WHERE case_id = ? "
            "ORDER BY created_at ASC, id ASC", (case_id,),
        ).fetchall()
    return [_hearing_note_from_row(r) for r in rows]


def delete_hearing_note(note_id: int, case_id: str) -> bool:
    with db() as conn:
        cur = conn.execute(
            "DELETE FROM hearing_notes WHERE id = ? AND case_id = ?",
            (note_id, case_id),
        )
    return cur.rowcount > 0


# ── V8.9 leads (citizen intake → lawyer inbox) ─────────────────────────────

LEAD_STATUSES = ("new", "contacted", "converted", "rejected")
LEAD_SOURCES = ("web", "telegram", "manual")
LEAD_URGENCIES = ("low", "medium", "high")


@dataclass
class Lead:
    id: int
    firm_id: int | None
    source: str
    contact_name: str
    contact_phone: str | None
    contact_email: str | None
    problem_text: str
    ai_summary: str | None
    ai_area: str | None
    ai_urgency: str | None
    ai_missing: list | None
    telegram_chat_id: int | None
    status: str
    converted_case_id: str | None
    assignee_user_id: int | None
    created_at: str
    updated_at: str


def _lead_from_row(r: sqlite3.Row) -> Lead:
    return Lead(
        id=r["id"], firm_id=r["firm_id"], source=r["source"],
        contact_name=r["contact_name"], contact_phone=r["contact_phone"],
        contact_email=r["contact_email"], problem_text=r["problem_text"],
        ai_summary=r["ai_summary"], ai_area=r["ai_area"],
        ai_urgency=r["ai_urgency"],
        ai_missing=json.loads(r["ai_missing"]) if r["ai_missing"] else None,
        telegram_chat_id=r["telegram_chat_id"],
        status=r["status"], converted_case_id=r["converted_case_id"],
        assignee_user_id=r["assignee_user_id"],
        created_at=r["created_at"], updated_at=r["updated_at"],
    )


def create_lead(
    *, source: str,
    contact_name: str, problem_text: str,
    contact_phone: str | None = None,
    contact_email: str | None = None,
    firm_id: int | None = None,
    telegram_chat_id: int | None = None,
    ai_summary: str | None = None,
    ai_area: str | None = None,
    ai_urgency: str | None = None,
    ai_missing: list | None = None,
) -> Lead:
    if source not in LEAD_SOURCES:
        raise ValueError(f"invalid source: {source}")
    contact_name = (contact_name or "").strip()
    problem_text = (problem_text or "").strip()
    if not contact_name:
        raise ValueError("contact_name required")
    if len(problem_text) < 20:
        raise ValueError("problem_text too short (min 20 chars)")
    if ai_urgency and ai_urgency not in LEAD_URGENCIES:
        raise ValueError(f"invalid urgency: {ai_urgency}")
    now = _utcnow()
    with db() as conn:
        cur = conn.execute(
            "INSERT INTO leads (firm_id, source, contact_name, contact_phone, "
            "contact_email, problem_text, ai_summary, ai_area, ai_urgency, "
            "ai_missing, telegram_chat_id, status, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'new', ?, ?)",
            (firm_id, source, contact_name, contact_phone, contact_email,
             problem_text, ai_summary, ai_area, ai_urgency,
             json.dumps(ai_missing, ensure_ascii=False) if ai_missing else None,
             telegram_chat_id, now, now),
        )
        lid = cur.lastrowid
    return get_lead(lid)  # type: ignore[return-value]


def get_lead(lead_id: int) -> Lead | None:
    with db() as conn:
        row = conn.execute(
            "SELECT * FROM leads WHERE id = ?", (lead_id,),
        ).fetchone()
    return _lead_from_row(row) if row else None


def list_leads(*, firm_id: int | None = None,
               status: str | None = None,
               include_archived: bool = False) -> list[Lead]:
    sql = "SELECT * FROM leads WHERE 1=1"
    params: list = []
    if firm_id is not None:
        sql += " AND (firm_id = ? OR firm_id IS NULL)"
        params.append(firm_id)
    if status:
        if status not in LEAD_STATUSES:
            raise ValueError(f"invalid status: {status}")
        sql += " AND status = ?"
        params.append(status)
    elif not include_archived:
        sql += " AND status NOT IN ('rejected', 'converted')"
    sql += " ORDER BY created_at DESC"
    with db() as conn:
        rows = conn.execute(sql, params).fetchall()
    return [_lead_from_row(r) for r in rows]


def update_lead(
    lead_id: int, *,
    status: str | None = None,
    assignee_user_id: int | None = None,
    converted_case_id: str | None = None,
) -> bool:
    fields: list[str] = []
    params: list = []
    if status is not None:
        if status not in LEAD_STATUSES:
            raise ValueError(f"invalid status: {status}")
        fields.append("status = ?"); params.append(status)
    if assignee_user_id is not None:
        fields.append("assignee_user_id = ?"); params.append(assignee_user_id)
    if converted_case_id is not None:
        fields.append("converted_case_id = ?"); params.append(converted_case_id)
    if not fields:
        return False
    fields.append("updated_at = ?"); params.append(_utcnow())
    params.append(lead_id)
    with db() as conn:
        cur = conn.execute(
            f"UPDATE leads SET {', '.join(fields)} WHERE id = ?",
            params,
        )
    return cur.rowcount > 0


def delete_lead(lead_id: int) -> bool:
    with db() as conn:
        cur = conn.execute("DELETE FROM leads WHERE id = ?", (lead_id,))
    return cur.rowcount > 0


def find_firm_by_slug(slug: str) -> Firm | None:
    with db() as conn:
        row = conn.execute(
            "SELECT * FROM firms WHERE slug = ?", (slug,),
        ).fetchone()
    return _firm_from_row(row) if row else None


# ── V8.11 Citation Shield V2 — provenance ──────────────────────────────────

def save_provenance(case_id: str | None, user_id: int, pack: dict) -> int:
    """Append a ProvenancePack to the audit log. Returns the new row id.

    The pack dict comes straight from ``citation_shield.ProvenancePack.to_dict()``
    so we don't redo the work — we just split out hot fields for indexing.
    """
    payload_json = json.dumps(pack, ensure_ascii=False)
    with db() as conn:
        cur = conn.execute(
            """
            INSERT INTO provenance_packs (
                response_id, case_id, user_id, jurisdiction,
                kb_version, model, system_prompt_version,
                prompt_hash, response_hash, confidence, refused,
                payload_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                str(pack.get("response_id") or ""),
                case_id,
                user_id,
                str(pack.get("jurisdiction") or "AL"),
                str(pack.get("kb_version") or ""),
                str(pack.get("model") or ""),
                str(pack.get("system_prompt_version") or ""),
                str(pack.get("prompt_hash") or ""),
                str(pack.get("response_hash") or ""),
                float(pack.get("confidence") or 0.0),
                1 if pack.get("refused") else 0,
                payload_json,
                _utcnow(),
            ),
        )
        return int(cur.lastrowid or 0)


def get_provenance(response_id: str, user_id: int) -> dict | None:
    with db() as conn:
        row = conn.execute(
            """
            SELECT payload_json FROM provenance_packs
            WHERE response_id = ? AND user_id = ?
            ORDER BY id DESC LIMIT 1
            """,
            (response_id, user_id),
        ).fetchone()
    if not row:
        return None
    try:
        return json.loads(row["payload_json"])
    except Exception:
        return None


def list_provenance(case_id: str, user_id: int, limit: int = 50) -> list[dict]:
    """Most-recent-first list of provenance packs for one case (lawyer view)."""
    with db() as conn:
        rows = conn.execute(
            """
            SELECT payload_json FROM provenance_packs
            WHERE case_id = ? AND user_id = ?
            ORDER BY id DESC LIMIT ?
            """,
            (case_id, user_id, limit),
        ).fetchall()
    out: list[dict] = []
    for row in rows:
        try:
            out.append(json.loads(row["payload_json"]))
        except Exception:
            continue
    return out


# ── V8.12 EU AI Act audit log ─────────────────────────────────────────────

def audit_log_call(
    *,
    callsite: str,
    backend: str,
    model: str,
    tier: str,
    prompt_hash: str,
    response_hash: str | None = None,
    prompt_raw: str | None = None,
    response_raw: str | None = None,
    user_id: int | None = None,
    case_id: str | None = None,
    latency_ms: int | None = None,
    input_tokens: int | None = None,
    output_tokens: int | None = None,
    outcome: str = "success",
    error_class: str | None = None,
    extra: dict | None = None,
) -> int:
    """Append one row to the AI Act audit log. Returns row id.

    The row is meant to satisfy AI Act art. 12 (automated logs for
    high-risk systems) + Annex IV traceability. Designed to be cheap
    enough to call on every backend invocation without throttling
    user-facing latency.
    """
    extra_json = json.dumps(extra, ensure_ascii=False) if extra else None
    with db() as conn:
        cur = conn.execute(
            """
            INSERT INTO ai_audit_log (
                timestamp, user_id, case_id, callsite, backend, model, tier,
                prompt_hash, response_hash, prompt_raw, response_raw,
                latency_ms, input_tokens, output_tokens,
                outcome, error_class, extra_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                _utcnow(),
                user_id,
                case_id,
                callsite,
                backend,
                model,
                tier,
                prompt_hash,
                response_hash,
                prompt_raw,
                response_raw,
                latency_ms,
                input_tokens,
                output_tokens,
                outcome,
                error_class,
                extra_json,
            ),
        )
        return int(cur.lastrowid or 0)


def list_audit(
    *,
    user_id: int | None = None,
    case_id: str | None = None,
    callsite: str | None = None,
    outcome: str | None = None,
    since: str | None = None,
    limit: int = 200,
) -> list[dict]:
    """Filtered audit log read. Default: 200 most recent entries."""
    where: list[str] = []
    params: list = []
    if user_id is not None:
        where.append("user_id = ?"); params.append(user_id)
    if case_id is not None:
        where.append("case_id = ?"); params.append(case_id)
    if callsite is not None:
        where.append("callsite = ?"); params.append(callsite)
    if outcome is not None:
        where.append("outcome = ?"); params.append(outcome)
    if since is not None:
        where.append("timestamp >= ?"); params.append(since)
    sql = "SELECT * FROM ai_audit_log"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY id DESC LIMIT ?"
    params.append(limit)
    with db() as conn:
        rows = conn.execute(sql, tuple(params)).fetchall()
    return [dict(r) for r in rows]


def audit_summary(since: str | None = None) -> dict:
    """Aggregate stats over the audit log — for the AI Act dashboard."""
    where = ""
    params: tuple = ()
    if since:
        where = " WHERE timestamp >= ?"
        params = (since,)
    with db() as conn:
        total = conn.execute(
            f"SELECT COUNT(*) AS n FROM ai_audit_log{where}", params
        ).fetchone()["n"]
        by_outcome = {
            r["outcome"]: r["n"]
            for r in conn.execute(
                f"SELECT outcome, COUNT(*) AS n FROM ai_audit_log{where} GROUP BY outcome",
                params,
            ).fetchall()
        }
        by_tier = {
            r["tier"]: r["n"]
            for r in conn.execute(
                f"SELECT tier, COUNT(*) AS n FROM ai_audit_log{where} GROUP BY tier",
                params,
            ).fetchall()
        }
        by_model = {
            r["model"]: r["n"]
            for r in conn.execute(
                f"SELECT model, COUNT(*) AS n FROM ai_audit_log{where} GROUP BY model",
                params,
            ).fetchall()
        }
        by_callsite = {
            r["callsite"]: r["n"]
            for r in conn.execute(
                f"SELECT callsite, COUNT(*) AS n FROM ai_audit_log{where} GROUP BY callsite ORDER BY n DESC LIMIT 30",
                params,
            ).fetchall()
        }
        avg_latency_row = conn.execute(
            f"SELECT AVG(latency_ms) AS avg_ms FROM ai_audit_log{where}", params,
        ).fetchone()
        avg_latency_ms = avg_latency_row["avg_ms"] if avg_latency_row else None
    return {
        "total": total,
        "by_outcome": by_outcome,
        "by_tier": by_tier,
        "by_model": by_model,
        "top_callsites": by_callsite,
        "avg_latency_ms": round(avg_latency_ms, 1) if avg_latency_ms else None,
        "since": since,
    }


# ── V8.15 Workflow runtime ──────────────────────────────────────────────

@dataclass
class CaseWorkflow:
    id: int
    case_id: str
    user_id: int
    workflow_key: str
    title: str
    state: str
    current_step_id: str | None
    current_step_idx: int
    step_results: dict
    definition: dict | None  # None for predefined library workflows
    started_at: str
    updated_at: str
    completed_at: str | None


def _wf_from_row(row) -> CaseWorkflow:
    return CaseWorkflow(
        id=row["id"],
        case_id=row["case_id"],
        user_id=row["user_id"],
        workflow_key=row["workflow_key"],
        title=row["title"],
        state=row["state"],
        current_step_id=row["current_step_id"],
        current_step_idx=int(row["current_step_idx"]),
        step_results=json.loads(row["step_results_json"] or "{}"),
        definition=(json.loads(row["definition_json"])
                    if row["definition_json"] else None),
        started_at=row["started_at"],
        updated_at=row["updated_at"],
        completed_at=row["completed_at"],
    )


def _resolve_workflow_definition(wf: CaseWorkflow) -> dict | None:
    """Returns the full DSL for a workflow row (predefined or custom)."""
    if wf.definition is not None:
        return wf.definition
    from . import workflows as wf_mod
    return wf_mod.get_definition(wf.workflow_key)


def start_workflow(*, case_id: str, user_id: int, workflow_key: str,
                   custom_definition: dict | None = None,
                   title: str | None = None) -> CaseWorkflow:
    """Instantiate a workflow on a case.

    If `custom_definition` is given, it's stored verbatim — the workflow
    runs against a per-instance DSL. Otherwise `workflow_key` must match
    a definition in src/workflows.py.
    """
    from . import workflows as wf_mod
    if custom_definition is not None:
        ok, err = wf_mod.validate_custom(custom_definition)
        if not ok:
            raise ValueError(f"invalid_definition:{err}")
        definition = custom_definition
    else:
        definition = wf_mod.get_definition(workflow_key)
        if definition is None:
            raise ValueError(f"unknown_workflow:{workflow_key}")
    steps = definition["steps"]
    first_id = steps[0]["id"] if steps else None
    resolved_title = title or definition.get("title") or workflow_key
    now = _utcnow()
    with db() as conn:
        cur = conn.execute(
            "INSERT INTO case_workflows "
            "(case_id, user_id, workflow_key, title, state, "
            " current_step_id, current_step_idx, step_results_json, "
            " definition_json, started_at, updated_at) "
            "VALUES (?, ?, ?, ?, 'active', ?, 0, '{}', ?, ?, ?)",
            (case_id, user_id, workflow_key, resolved_title,
             first_id,
             json.dumps(custom_definition) if custom_definition else None,
             now, now),
        )
        row = conn.execute(
            "SELECT * FROM case_workflows WHERE id = ?", (cur.lastrowid,)
        ).fetchone()
    return _wf_from_row(row)


def get_workflow(workflow_id: int) -> CaseWorkflow | None:
    with db() as conn:
        row = conn.execute(
            "SELECT * FROM case_workflows WHERE id = ?", (workflow_id,)
        ).fetchone()
    return _wf_from_row(row) if row else None


def list_case_workflows(case_id: str) -> list[CaseWorkflow]:
    with db() as conn:
        rows = conn.execute(
            "SELECT * FROM case_workflows WHERE case_id = ? "
            "ORDER BY started_at DESC",
            (case_id,),
        ).fetchall()
    return [_wf_from_row(r) for r in rows]


def advance_workflow(workflow_id: int, *,
                     step_id: str | None = None,
                     result: Any | None = None) -> CaseWorkflow:
    """Mark the named step as complete + move to the next.

    `step_id` defaults to the workflow's current step. `result` is
    JSON-serialisable and stored under that step's id.
    Raises ValueError on bad inputs / inactive workflow.
    """
    wf = get_workflow(workflow_id)
    if wf is None:
        raise ValueError("unknown_workflow_instance")
    if wf.state != "active":
        raise ValueError(f"workflow_not_active:{wf.state}")
    definition = _resolve_workflow_definition(wf)
    if definition is None:
        raise ValueError("definition_unavailable")
    steps: list = definition.get("steps") or []
    target = step_id or wf.current_step_id
    if target is None:
        raise ValueError("no_current_step")
    idx = next((i for i, s in enumerate(steps) if s["id"] == target), -1)
    if idx < 0:
        raise ValueError(f"unknown_step:{target}")
    if idx != wf.current_step_idx:
        raise ValueError(
            f"out_of_order:expected_{wf.current_step_idx}_got_{idx}"
        )
    new_results = dict(wf.step_results)
    output_key = steps[idx].get("output_key", target)
    if result is not None:
        new_results[output_key] = result
    new_results.setdefault("_completed_steps", []).append(target)
    next_idx = idx + 1
    is_last = next_idx >= len(steps)
    new_state = "completed" if is_last else "active"
    next_id = None if is_last else steps[next_idx]["id"]
    now = _utcnow()
    completed_at = now if is_last else wf.completed_at
    with db() as conn:
        conn.execute(
            "UPDATE case_workflows SET "
            "  state = ?, current_step_id = ?, current_step_idx = ?, "
            "  step_results_json = ?, updated_at = ?, completed_at = ? "
            "WHERE id = ?",
            (new_state, next_id, next_idx if not is_last else idx,
             json.dumps(new_results), now, completed_at, workflow_id),
        )
    return get_workflow(workflow_id)  # type: ignore[return-value]


def update_workflow_state(workflow_id: int, new_state: str) -> CaseWorkflow:
    """Pause/resume/cancel without advancing — admin/owner action."""
    if new_state not in ("active", "paused", "cancelled"):
        raise ValueError(f"invalid_state:{new_state}")
    now = _utcnow()
    with db() as conn:
        conn.execute(
            "UPDATE case_workflows SET state = ?, updated_at = ? WHERE id = ?",
            (new_state, now, workflow_id),
        )
    wf = get_workflow(workflow_id)
    if wf is None:
        raise ValueError("unknown_workflow_instance")
    return wf


# ── V8.16 Time-Block Reconstruction ────────────────────────────────────
#
# Build proposed billable time blocks for a user on a given date by
# aggregating activity signals across the existing tables — *without*
# adding any new schema. Signals carry a confidence weight; a clustering
# pass groups nearby signals (≤ GAP_MINUTES apart on the same case) into
# one block. The lawyer reviews + accepts; on accept the block becomes
# a normal time_entries row.

_BLOCK_GAP_MINUTES = 25
_MIN_BLOCK_MINUTES = 6  # ignore tiny single-event blocks (1 message at 14:03)


def _hhmm(iso_ts: str) -> str:
    """Return HH:MM (UTC) of an ISO-8601 timestamp."""
    try:
        dt = datetime.fromisoformat(iso_ts.replace("Z", "+00:00"))
        return dt.astimezone(UTC).strftime("%H:%M")
    except (TypeError, ValueError):
        return "00:00"


def _date_only(iso_ts: str) -> str:
    return (iso_ts or "")[:10]


def _date_window(date_str: str) -> tuple[str, str]:
    return f"{date_str}T00:00:00Z", f"{date_str}T23:59:59Z"


def _collect_user_activities(user_id: int, date_str: str) -> list[dict]:
    """Pull every per-user activity signal observed on `date_str`.

    Each item: {ts, case_id, kind, weight, evidence}. Cases that the user
    can see (creator OR firm member) are eligible. We attribute a signal
    to the user when the row carries `user_id`; for `messages`/`documents`
    where there is no per-row attribution, we use the case's owner — which
    matches the solo-lawyer case correctly and undercounts (but never
    over-attributes) in multi-member firms.
    """
    lo, hi = _date_window(date_str)
    out: list[dict] = []
    with db() as conn:
        # auto_letters (V8.6) — explicit user_id
        for r in conn.execute(
            "SELECT case_id, kind, subject, recipient, created_at "
            "FROM auto_letters WHERE user_id = ? "
            "AND created_at BETWEEN ? AND ?",
            (user_id, lo, hi),
        ).fetchall():
            out.append({
                "ts": r["created_at"], "case_id": r["case_id"],
                "kind": "drafting", "weight": 25,
                "evidence": f"letër '{r['kind']}'"
                            + (f" për {r['recipient']}" if r["recipient"] else ""),
            })
        # drafted_acts (V7.11)
        for r in conn.execute(
            "SELECT case_id, act_type, created_at FROM drafted_acts "
            "WHERE user_id = ? AND created_at BETWEEN ? AND ?",
            (user_id, lo, hi),
        ).fetchall():
            if not r["case_id"]:
                continue
            out.append({
                "ts": r["created_at"], "case_id": r["case_id"],
                "kind": "drafting", "weight": 35,
                "evidence": f"akt '{r['act_type']}'",
            })
        # citation_audits + stress_tests
        for table, label, kind, weight in (
            ("citation_audits", "audit citimi", "research", 15),
            ("stress_tests", "stress-test udienze", "research", 25),
        ):
            for r in conn.execute(
                f"SELECT case_id, created_at FROM {table} "
                f"WHERE user_id = ? AND created_at BETWEEN ? AND ?",
                (user_id, lo, hi),
            ).fetchall():
                if not r["case_id"]:
                    continue
                out.append({
                    "ts": r["created_at"], "case_id": r["case_id"],
                    "kind": kind, "weight": weight, "evidence": label,
                })
        # events (V7.10) — calendar appointments owned by user
        for r in conn.execute(
            "SELECT case_id, kind, title, starts_at, ends_at, all_day "
            "FROM events WHERE user_id = ? "
            "AND starts_at BETWEEN ? AND ?",
            (user_id, lo, hi),
        ).fetchall():
            if r["all_day"]:
                continue
            mapped = {
                "seance": "hearing", "takim": "meeting",
                "afat": "drafting", "dorëzim": "drafting",
            }.get(r["kind"], "work")
            ev_minutes = 60
            if r["ends_at"]:
                try:
                    a = datetime.fromisoformat(r["starts_at"].replace("Z", "+00:00"))
                    b = datetime.fromisoformat(r["ends_at"].replace("Z", "+00:00"))
                    ev_minutes = max(15, int((b - a).total_seconds() // 60))
                except (TypeError, ValueError):
                    pass
            out.append({
                "ts": r["starts_at"], "case_id": r["case_id"] or "_personal",
                "kind": mapped, "weight": 60,
                "duration_hint": ev_minutes,
                "evidence": f"event '{r['title']}'",
            })
        # case_workflows advances (V8.15) — proxy via updated_at
        for r in conn.execute(
            "SELECT case_id, workflow_key, current_step_id, updated_at "
            "FROM case_workflows WHERE user_id = ? "
            "AND updated_at BETWEEN ? AND ?",
            (user_id, lo, hi),
        ).fetchall():
            out.append({
                "ts": r["updated_at"], "case_id": r["case_id"],
                "kind": "drafting", "weight": 15,
                "evidence": f"workflow {r['workflow_key']} → {r['current_step_id']}",
            })
        # provenance_packs (V8.11) — proxy for "asked Super Avvocato a serious question"
        try:
            for r in conn.execute(
                "SELECT case_id, created_at FROM provenance_packs "
                "WHERE created_at BETWEEN ? AND ? "
                "AND case_id IN (SELECT id FROM cases WHERE user_id = ?)",
                (lo, hi, user_id),
            ).fetchall():
                out.append({
                    "ts": r["created_at"], "case_id": r["case_id"],
                    "kind": "research", "weight": 20,
                    "evidence": "pyetje me Citation Shield",
                })
        except sqlite3.OperationalError:
            # provenance_packs table absent in old DBs
            pass
        # messages — attributed via case ownership only (V8.16 conservative)
        for r in conn.execute(
            "SELECT m.case_id, m.role, m.kind, m.created_at "
            "FROM messages m JOIN cases c ON c.id = m.case_id "
            "WHERE c.user_id = ? AND m.created_at BETWEEN ? AND ?",
            (user_id, lo, hi),
        ).fetchall():
            if r["role"] == "user":
                out.append({
                    "ts": r["created_at"], "case_id": r["case_id"],
                    "kind": "research", "weight": 8,
                    "evidence": "chat: pyetje",
                })
        # documents uploaded — attributed via case ownership
        for r in conn.execute(
            "SELECT d.case_id, d.filename, d.created_at "
            "FROM documents d JOIN cases c ON c.id = d.case_id "
            "WHERE c.user_id = ? AND d.created_at BETWEEN ? AND ?",
            (user_id, lo, hi),
        ).fetchall():
            out.append({
                "ts": r["created_at"], "case_id": r["case_id"],
                "kind": "research", "weight": 12,
                "evidence": f"dok i ri '{r['filename'][:40]}'",
            })
    return sorted(out, key=lambda a: (a["case_id"], a["ts"]))


def _cluster_activities(activities: list[dict]) -> list[dict]:
    """Group activities on the same case, ≤ GAP minutes apart, into blocks."""
    blocks: list[dict] = []
    current: dict | None = None
    for a in activities:
        try:
            ts = datetime.fromisoformat(a["ts"].replace("Z", "+00:00"))
        except (TypeError, ValueError):
            continue
        if (current is not None
                and a["case_id"] == current["case_id"]
                and (ts - current["_end_dt"]).total_seconds()
                    <= _BLOCK_GAP_MINUTES * 60):
            # extend
            current["_end_dt"] = ts
            current["weight"] += a["weight"]
            current["evidence"].append(a["evidence"])
            current["kinds"][a["kind"]] = current["kinds"].get(a["kind"], 0) + a["weight"]
            if "duration_hint" in a:
                current.setdefault("hint_minutes", 0)
                current["hint_minutes"] = max(current["hint_minutes"], a["duration_hint"])
        else:
            if current is not None:
                blocks.append(current)
            current = {
                "case_id": a["case_id"],
                "_start_dt": ts, "_end_dt": ts,
                "weight": a["weight"],
                "evidence": [a["evidence"]],
                "kinds": {a["kind"]: a["weight"]},
                "hint_minutes": a.get("duration_hint", 0),
            }
    if current is not None:
        blocks.append(current)
    return blocks


def _finalise_blocks(blocks: list[dict]) -> list[dict]:
    """Convert raw clusters to API shape with kind/duration/confidence."""
    out: list[dict] = []
    for b in blocks:
        start, end = b["_start_dt"], b["_end_dt"]
        span = max(_MIN_BLOCK_MINUTES,
                   int((end - start).total_seconds() // 60))
        # bump short blocks with hint (e.g. calendar event w/ end_at)
        duration = max(span, b.get("hint_minutes", 0))
        # round to nearest 5 minutes (lawyers bill in 6-min units)
        duration = max(_MIN_BLOCK_MINUTES, ((duration + 2) // 6) * 6)
        # winning kind = highest accumulated weight
        kind = max(b["kinds"].items(), key=lambda kv: kv[1])[0]
        # confidence: heuristic on weight + signal diversity
        diversity = len(b["kinds"])
        conf_score = b["weight"] + diversity * 10
        if conf_score >= 60: confidence = "high"
        elif conf_score >= 25: confidence = "medium"
        else: confidence = "low"
        out.append({
            "case_id": b["case_id"],
            "started_at": start.strftime("%H:%M"),
            "ended_at": end.strftime("%H:%M"),
            "minutes": duration,
            "activity_kind": kind,
            "kind_label": ACTIVITY_KIND_LABELS_SQ.get(kind, kind),
            "confidence": confidence,
            "evidence": b["evidence"][:6],
            "evidence_count": len(b["evidence"]),
        })
    return out


def reconstruct_time_blocks(user_id: int, date_str: str) -> dict:
    """Top-level: signals → clusters → API blocks + already-logged note.

    Returns:
        {
          "date": "YYYY-MM-DD",
          "user_id": int,
          "blocks": [...],
          "already_logged": [{case_id, total_minutes}, ...],
          "no_data": bool,
        }
    """
    activities = _collect_user_activities(user_id, date_str)
    blocks_raw = _cluster_activities(activities)
    blocks = _finalise_blocks(blocks_raw)
    # per-case minutes already logged → marks blocks as redundant
    with db() as conn:
        already = conn.execute(
            "SELECT case_id, COALESCE(SUM(minutes),0) AS m "
            "FROM time_entries WHERE user_id = ? AND entry_date = ? "
            "GROUP BY case_id",
            (user_id, date_str),
        ).fetchall()
    already_map = {r["case_id"]: int(r["m"]) for r in already}
    for b in blocks:
        b["already_logged_for_case_minutes"] = already_map.get(b["case_id"], 0)
    # enrich case titles
    case_ids = sorted({b["case_id"] for b in blocks
                       if b["case_id"] != "_personal"})
    title_map: dict[str, str] = {}
    if case_ids:
        with db() as conn:
            placeholders = ",".join("?" * len(case_ids))
            for r in conn.execute(
                f"SELECT id, title FROM cases WHERE id IN ({placeholders})",
                case_ids,
            ).fetchall():
                title_map[r["id"]] = r["title"]
    for b in blocks:
        b["case_title"] = title_map.get(b["case_id"], "Personal / non-case")
    return {
        "date": date_str,
        "user_id": user_id,
        "blocks": blocks,
        "already_logged": [
            {"case_id": cid, "case_title": title_map.get(cid, ""),
             "total_minutes": m}
            for cid, m in already_map.items()
        ],
        "no_data": not blocks,
    }


def accept_time_blocks(user_id: int, date_str: str,
                       blocks: list[dict],
                       firm_id: int | None = None) -> list[TimeEntry]:
    """Convert accepted blocks to time_entries rows. One row per block.

    Each block dict must contain: case_id, minutes, activity_kind,
    description (lawyer-edited). Blocks with case_id == '_personal' are
    silently skipped (no case to bill against). Returns the created rows.
    """
    out: list[TimeEntry] = []
    for b in blocks:
        case_id = b.get("case_id")
        if not case_id or case_id == "_personal":
            continue
        minutes = int(b.get("minutes") or 0)
        if minutes <= 0:
            continue
        desc = (b.get("description") or "").strip()
        if not desc:
            ev = b.get("evidence") or []
            desc = "; ".join(ev[:3]) if ev else "Punë e ricostruktuar"
        kind = b.get("activity_kind") or "work"
        if kind not in ACTIVITY_KIND_LABELS_SQ:
            kind = "work"
        out.append(create_time_entry(
            case_id=case_id, user_id=user_id,
            minutes=minutes, description=desc,
            activity_kind=kind,
            entry_date=date_str,
            firm_id=firm_id,
        ))
    return out


def workflow_summary(wf: CaseWorkflow) -> dict:
    """Project a CaseWorkflow + its definition to API-friendly dict."""
    definition = _resolve_workflow_definition(wf)
    steps = (definition or {}).get("steps") or []
    completed = set(wf.step_results.get("_completed_steps", []))
    return {
        "id": wf.id,
        "case_id": wf.case_id,
        "workflow_key": wf.workflow_key,
        "title": wf.title,
        "state": wf.state,
        "current_step_id": wf.current_step_id,
        "current_step_idx": wf.current_step_idx,
        "started_at": wf.started_at,
        "updated_at": wf.updated_at,
        "completed_at": wf.completed_at,
        "step_count": len(steps),
        "is_custom": wf.definition is not None,
        "steps": [
            {
                "id": s["id"],
                "title": s["title"],
                "kind": s["kind"],
                "description": s.get("description", ""),
                "blocking": s.get("blocking", True),
                "completed": s["id"] in completed,
                "is_current": s["id"] == wf.current_step_id,
                "result": wf.step_results.get(s.get("output_key", s["id"])),
            }
            for s in steps
        ],
    }


# ── V8.17 Settlement Monte Carlo persistence ───────────────────────────

def save_settlement_simulation(*,
        case_id: str, user_id: int,
        description: str,
        valore_in_causa_cents: int | None,
        current_offer_cents: int | None,
        currency: str,
        scenarios: list[dict],
        distribution: dict,
        recommendation: dict,
        precedents: list[dict] | None = None,
        samples: int = 10000,
        seed: int | None = None) -> int:
    now = _utcnow()
    with db() as conn:
        cur = conn.execute(
            "INSERT INTO settlement_simulations "
            "(case_id, user_id, description, valore_in_causa_cents, "
            " current_offer_cents, currency, scenarios_json, "
            " distribution_json, recommendation_json, precedents_json, "
            " samples, seed, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (case_id, user_id, description, valore_in_causa_cents,
             current_offer_cents, currency,
             json.dumps(scenarios), json.dumps(distribution),
             json.dumps(recommendation),
             json.dumps(precedents) if precedents is not None else None,
             samples, seed, now),
        )
        return int(cur.lastrowid)


def get_settlement_simulation(sim_id: int) -> dict | None:
    with db() as conn:
        r = conn.execute(
            "SELECT * FROM settlement_simulations WHERE id = ?", (sim_id,)
        ).fetchone()
    if r is None:
        return None
    return {
        "id": r["id"], "case_id": r["case_id"], "user_id": r["user_id"],
        "description": r["description"],
        "valore_in_causa_cents": r["valore_in_causa_cents"],
        "current_offer_cents": r["current_offer_cents"],
        "currency": r["currency"],
        "scenarios": json.loads(r["scenarios_json"] or "[]"),
        "distribution": json.loads(r["distribution_json"] or "{}"),
        "recommendation": json.loads(r["recommendation_json"] or "{}"),
        "precedents": json.loads(r["precedents_json"]) if r["precedents_json"] else None,
        "samples": r["samples"], "seed": r["seed"],
        "created_at": r["created_at"],
    }


def list_settlement_simulations(case_id: str) -> list[dict]:
    with db() as conn:
        rows = conn.execute(
            "SELECT id, description, current_offer_cents, currency, "
            "  recommendation_json, samples, created_at "
            "FROM settlement_simulations WHERE case_id = ? "
            "ORDER BY created_at DESC",
            (case_id,),
        ).fetchall()
    return [{
        "id": r["id"],
        "description": r["description"],
        "current_offer_cents": r["current_offer_cents"],
        "currency": r["currency"],
        "samples": r["samples"],
        "created_at": r["created_at"],
        "verdict": (json.loads(r["recommendation_json"] or "{}")
                    .get("verdict")),
    } for r in rows]


# ── V9.0 Genio Legale persistence ──────────────────────────────────────

def create_genio_brief(*, case_id: str, user_id: int,
                       description: str, case_block: str) -> int:
    """Create a brief row in 'running' state. Returns its id.

    The orchestrator updates by_key_json + status + elapsed_ms when the
    run finishes. Storing the row up-front means the UI can poll/show
    the brief even while perspectives are still streaming in.
    """
    now = _utcnow()
    with db() as conn:
        cur = conn.execute(
            "INSERT INTO genio_briefs "
            "(case_id, user_id, description, case_block, by_key_json, "
            " status, started_at) "
            "VALUES (?, ?, ?, ?, '{}', 'running', ?)",
            (case_id, user_id, description, case_block, now),
        )
        return int(cur.lastrowid)


def finalize_genio_brief(brief_id: int, *, by_key: dict,
                         status: str, elapsed_ms: int) -> None:
    """Persist a finished brief (called by the orchestrator on completion)."""
    now = _utcnow()
    with db() as conn:
        conn.execute(
            "UPDATE genio_briefs SET by_key_json = ?, status = ?, "
            "elapsed_ms = ?, completed_at = ? WHERE id = ?",
            (json.dumps(by_key), status, elapsed_ms, now, brief_id),
        )


def get_genio_brief(brief_id: int) -> dict | None:
    with db() as conn:
        r = conn.execute(
            "SELECT * FROM genio_briefs WHERE id = ?", (brief_id,),
        ).fetchone()
    if r is None:
        return None
    return {
        "id": r["id"], "case_id": r["case_id"], "user_id": r["user_id"],
        "description": r["description"],
        "case_block": r["case_block"],
        "by_key": json.loads(r["by_key_json"] or "{}"),
        "status": r["status"], "elapsed_ms": r["elapsed_ms"],
        "started_at": r["started_at"], "completed_at": r["completed_at"],
    }


def list_genio_briefs(case_id: str) -> list[dict]:
    with db() as conn:
        rows = conn.execute(
            "SELECT id, description, status, elapsed_ms, started_at, "
            "       completed_at "
            "FROM genio_briefs WHERE case_id = ? "
            "ORDER BY started_at DESC",
            (case_id,),
        ).fetchall()
    return [{
        "id": r["id"], "description": r["description"],
        "status": r["status"], "elapsed_ms": r["elapsed_ms"],
        "started_at": r["started_at"], "completed_at": r["completed_at"],
    } for r in rows]


# ── V9.2 Precedent Pattern Analyzer persistence ────────────────────────

def create_precedent_brief(*, case_id: str | None, user_id: int,
                           case_description: str) -> int:
    """Insert a brief row in 'running' state and return its id."""
    now = _utcnow()
    with db() as conn:
        cur = conn.execute(
            "INSERT INTO precedent_briefs "
            "(case_id, user_id, case_description, brief_json, status, "
            " started_at) VALUES (?, ?, ?, '{}', 'running', ?)",
            (case_id, user_id, case_description, now),
        )
        return int(cur.lastrowid)


def finalize_precedent_brief(brief_id: int, *, brief: dict,
                             status: str, elapsed_ms: int) -> None:
    """Persist the synthesized brief on completion."""
    now = _utcnow()
    with db() as conn:
        conn.execute(
            "UPDATE precedent_briefs SET brief_json = ?, status = ?, "
            "elapsed_ms = ?, completed_at = ? WHERE id = ?",
            (json.dumps(brief, ensure_ascii=False), status, elapsed_ms,
             now, brief_id),
        )


def get_precedent_brief(brief_id: int) -> dict | None:
    with db() as conn:
        r = conn.execute(
            "SELECT * FROM precedent_briefs WHERE id = ?", (brief_id,),
        ).fetchone()
    if r is None:
        return None
    return {
        "id": r["id"], "case_id": r["case_id"], "user_id": r["user_id"],
        "case_description": r["case_description"],
        "brief": json.loads(r["brief_json"] or "{}"),
        "status": r["status"], "elapsed_ms": r["elapsed_ms"],
        "started_at": r["started_at"], "completed_at": r["completed_at"],
    }


def list_precedent_briefs(*, case_id: str | None = None,
                          user_id: int | None = None,
                          limit: int = 50) -> list[dict]:
    """List briefs for a case OR for a user (standalone analyses).

    If case_id is given, returns briefs tied to that fascicolo.
    Otherwise returns the user's standalone (case_id IS NULL) briefs.
    """
    with db() as conn:
        if case_id is not None:
            rows = conn.execute(
                "SELECT id, case_id, case_description, status, elapsed_ms, "
                "       started_at, completed_at "
                "FROM precedent_briefs WHERE case_id = ? "
                "ORDER BY started_at DESC LIMIT ?",
                (case_id, limit),
            ).fetchall()
        elif user_id is not None:
            rows = conn.execute(
                "SELECT id, case_id, case_description, status, elapsed_ms, "
                "       started_at, completed_at "
                "FROM precedent_briefs "
                "WHERE user_id = ? AND case_id IS NULL "
                "ORDER BY started_at DESC LIMIT ?",
                (user_id, limit),
            ).fetchall()
        else:
            return []
    return [{
        "id": r["id"], "case_id": r["case_id"],
        "case_description": r["case_description"],
        "status": r["status"], "elapsed_ms": r["elapsed_ms"],
        "started_at": r["started_at"], "completed_at": r["completed_at"],
    } for r in rows]


# ── V9.3 Corporate Intelligence persistence ───────────────────────────

def save_corporate_extraction(
    *,
    case_id: str,
    user_id: int,
    doc_name: str,
    doc_type: str,
    extracted: dict,
) -> int:
    now = _utcnow()
    with db() as conn:
        cur = conn.execute(
            "INSERT INTO corporate_extractions "
            "(case_id, user_id, doc_name, doc_type, extracted_json, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (case_id, user_id, doc_name, doc_type,
             json.dumps(extracted, ensure_ascii=False), now),
        )
        return int(cur.lastrowid)


def list_corporate_extractions(case_id: str) -> list[dict]:
    with db() as conn:
        rows = conn.execute(
            "SELECT id, doc_name, doc_type, extracted_json, created_at "
            "FROM corporate_extractions WHERE case_id = ? "
            "ORDER BY created_at DESC",
            (case_id,),
        ).fetchall()
    return [{
        "id": r["id"],
        "doc_name": r["doc_name"],
        "doc_type": r["doc_type"],
        "extracted": json.loads(r["extracted_json"] or "{}"),
        "created_at": r["created_at"],
    } for r in rows]


def delete_corporate_extraction(extraction_id: int, case_id: str) -> bool:
    with db() as conn:
        cur = conn.execute(
            "DELETE FROM corporate_extractions WHERE id = ? AND case_id = ?",
            (extraction_id, case_id),
        )
        return cur.rowcount > 0


# ── V9.4 Bench Memo persistence ───────────────────────────────────────

def create_bench_memo(*, case_id: str, user_id: int, description: str,
                      court_code: str, opponent_filing: str | None) -> int:
    now = _utcnow()
    with db() as conn:
        cur = conn.execute(
            "INSERT INTO bench_memos (case_id, user_id, description, court_code, "
            "opponent_filing, memo_json, status, started_at) "
            "VALUES (?, ?, ?, ?, ?, '{}', 'running', ?)",
            (case_id, user_id, description, court_code, opponent_filing, now),
        )
        return int(cur.lastrowid)


def finalize_bench_memo(memo_id: int, *, memo: dict, status: str,
                        elapsed_ms: int) -> None:
    now = _utcnow()
    with db() as conn:
        conn.execute(
            "UPDATE bench_memos SET memo_json = ?, status = ?, "
            "elapsed_ms = ?, completed_at = ? WHERE id = ?",
            (json.dumps(memo, ensure_ascii=False), status, elapsed_ms, now, memo_id),
        )


def get_bench_memo(memo_id: int) -> dict | None:
    with db() as conn:
        r = conn.execute(
            "SELECT * FROM bench_memos WHERE id = ?", (memo_id,),
        ).fetchone()
    if r is None:
        return None
    return {
        "id": r["id"], "case_id": r["case_id"], "user_id": r["user_id"],
        "description": r["description"], "court_code": r["court_code"],
        "opponent_filing": r["opponent_filing"],
        "memo": json.loads(r["memo_json"] or "{}"),
        "status": r["status"], "elapsed_ms": r["elapsed_ms"],
        "started_at": r["started_at"], "completed_at": r["completed_at"],
    }


def list_bench_memos(case_id: str, limit: int = 20) -> list[dict]:
    with db() as conn:
        rows = conn.execute(
            "SELECT id, case_id, court_code, status, elapsed_ms, "
            "       started_at, completed_at "
            "FROM bench_memos WHERE case_id = ? "
            "ORDER BY started_at DESC LIMIT ?",
            (case_id, limit),
        ).fetchall()
    return [{
        "id": r["id"], "case_id": r["case_id"],
        "court_code": r["court_code"],
        "status": r["status"], "elapsed_ms": r["elapsed_ms"],
        "started_at": r["started_at"], "completed_at": r["completed_at"],
    } for r in rows]


# ── V9.5 Vigilanza Normativa persistence ──────────────────────────────

def save_legal_update(*, source: str, source_url: str | None,
                      title: str, content: str, published_at: str | None,
                      classification: dict, fetched_by: int | None) -> int:
    now = _utcnow()
    with db() as conn:
        cur = conn.execute(
            "INSERT INTO legal_updates "
            "(source, source_url, title, content, published_at, "
            " classification_json, fetched_at, fetched_by) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (source, source_url, title, content, published_at,
             json.dumps(classification, ensure_ascii=False),
             now, fetched_by),
        )
        return int(cur.lastrowid)


def list_legal_updates(limit: int = 50) -> list[dict]:
    with db() as conn:
        rows = conn.execute(
            "SELECT id, source, source_url, title, published_at, "
            "       classification_json, fetched_at "
            "FROM legal_updates ORDER BY fetched_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return [{
        "id": r["id"], "source": r["source"], "source_url": r["source_url"],
        "title": r["title"], "published_at": r["published_at"],
        "classification": json.loads(r["classification_json"] or "{}"),
        "fetched_at": r["fetched_at"],
    } for r in rows]


def get_legal_update(update_id: int) -> dict | None:
    with db() as conn:
        r = conn.execute(
            "SELECT * FROM legal_updates WHERE id = ?", (update_id,),
        ).fetchone()
    if r is None:
        return None
    return {
        "id": r["id"], "source": r["source"], "source_url": r["source_url"],
        "title": r["title"], "content": r["content"],
        "published_at": r["published_at"],
        "classification": json.loads(r["classification_json"] or "{}"),
        "fetched_at": r["fetched_at"], "fetched_by": r["fetched_by"],
    }


def create_case_alert(*, case_id: str, update_id: int, user_id: int,
                      relevance_score: float, match_summary: dict) -> int | None:
    """Insert a new alert; returns id or None if (case_id, update_id) already exists."""
    now = _utcnow()
    try:
        with db() as conn:
            cur = conn.execute(
                "INSERT INTO case_alerts "
                "(case_id, update_id, user_id, relevance_score, match_summary, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (case_id, update_id, user_id, relevance_score,
                 json.dumps(match_summary, ensure_ascii=False), now),
            )
            return int(cur.lastrowid)
    except sqlite3.IntegrityError:
        return None  # duplicate (case_id, update_id)


def list_case_alerts(*, user_id: int, case_id: str | None = None,
                     include_dismissed: bool = False,
                     limit: int = 100) -> list[dict]:
    where = ["a.user_id = ?"]
    args: list = [user_id]
    if case_id is not None:
        where.append("a.case_id = ?")
        args.append(case_id)
    if not include_dismissed:
        where.append("a.dismissed = 0")
    args.append(limit)
    sql = (
        "SELECT a.*, u.title AS update_title, u.source AS update_source, "
        "       u.source_url AS update_url, u.published_at AS update_published, "
        "       u.classification_json AS update_class, "
        "       c.title AS case_title "
        "FROM case_alerts a "
        "JOIN legal_updates u ON u.id = a.update_id "
        "JOIN cases c ON c.id = a.case_id "
        "WHERE " + " AND ".join(where) +
        " ORDER BY a.created_at DESC LIMIT ?"
    )
    with db() as conn:
        rows = conn.execute(sql, args).fetchall()
    return [{
        "id": r["id"], "case_id": r["case_id"], "update_id": r["update_id"],
        "case_title": r["case_title"],
        "update_title": r["update_title"], "update_source": r["update_source"],
        "update_url": r["update_url"], "update_published": r["update_published"],
        "update_classification": json.loads(r["update_class"] or "{}"),
        "relevance_score": r["relevance_score"],
        "match_summary": json.loads(r["match_summary"] or "{}"),
        "dismissed": bool(r["dismissed"]),
        "created_at": r["created_at"], "dismissed_at": r["dismissed_at"],
    } for r in rows]


def count_pending_alerts(user_id: int) -> int:
    with db() as conn:
        r = conn.execute(
            "SELECT COUNT(*) AS n FROM case_alerts "
            "WHERE user_id = ? AND dismissed = 0",
            (user_id,),
        ).fetchone()
    return int(r["n"]) if r else 0


def dismiss_alert(alert_id: int, user_id: int) -> bool:
    now = _utcnow()
    with db() as conn:
        cur = conn.execute(
            "UPDATE case_alerts SET dismissed = 1, dismissed_at = ? "
            "WHERE id = ? AND user_id = ?",
            (now, alert_id, user_id),
        )
        return cur.rowcount > 0


# ── V9.6 Ratio Coach persistence ──────────────────────────────────────

def save_case_lesson(*, case_id: str, user_id: int, firm_id: int | None,
                     outcome: str, summary_hint: str | None,
                     lesson: dict, elapsed_ms: int) -> int:
    """Insert or replace the lesson for this case (UNIQUE on case_id)."""
    now = _utcnow()
    archetype = lesson.get("archetype") or ""
    transferable = lesson.get("transferable_lesson") or ""
    payload = json.dumps(lesson, ensure_ascii=False)
    with db() as conn:
        # delete existing lesson for this case (UNIQUE constraint)
        conn.execute("DELETE FROM case_lessons WHERE case_id = ?", (case_id,))
        cur = conn.execute(
            "INSERT INTO case_lessons "
            "(case_id, user_id, firm_id, outcome, archetype, transferable_lesson, "
            " summary_hint, lesson_json, elapsed_ms, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (case_id, user_id, firm_id, outcome, archetype, transferable,
             summary_hint, payload, elapsed_ms, now),
        )
        return int(cur.lastrowid)


def get_case_lesson(case_id: str) -> dict | None:
    with db() as conn:
        r = conn.execute(
            "SELECT * FROM case_lessons WHERE case_id = ?", (case_id,),
        ).fetchone()
    if r is None:
        return None
    return _lesson_row_to_dict(r)


def list_case_lessons(*, user_id: int, firm_id: int | None = None,
                      limit: int = 100) -> list[dict]:
    """List lessons visible to the user — own + firm-shared if firm_id given."""
    with db() as conn:
        if firm_id is not None:
            rows = conn.execute(
                "SELECT l.*, c.title AS case_title FROM case_lessons l "
                "JOIN cases c ON c.id = l.case_id "
                "WHERE l.user_id = ? OR l.firm_id = ? "
                "ORDER BY l.created_at DESC LIMIT ?",
                (user_id, firm_id, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT l.*, c.title AS case_title FROM case_lessons l "
                "JOIN cases c ON c.id = l.case_id "
                "WHERE l.user_id = ? "
                "ORDER BY l.created_at DESC LIMIT ?",
                (user_id, limit),
            ).fetchall()
    return [_lesson_row_to_dict(r) for r in rows]


def delete_case_lesson(case_id: str, user_id: int) -> bool:
    with db() as conn:
        cur = conn.execute(
            "DELETE FROM case_lessons WHERE case_id = ? AND user_id = ?",
            (case_id, user_id),
        )
        return cur.rowcount > 0


def _lesson_row_to_dict(r) -> dict:
    keys = r.keys()
    return {
        "id": r["id"],
        "case_id": r["case_id"],
        "user_id": r["user_id"],
        "firm_id": r["firm_id"],
        "outcome": r["outcome"],
        "archetype": r["archetype"],
        "transferable_lesson": r["transferable_lesson"],
        "summary_hint": r["summary_hint"],
        "lesson_json": json.loads(r["lesson_json"] or "{}"),
        "elapsed_ms": r["elapsed_ms"],
        "created_at": r["created_at"],
        "case_title": r["case_title"] if "case_title" in keys else None,
    }


def list_user_open_cases_for_matching(user_id: int) -> list[dict]:
    """Return all cases of user with concatenated content for matching."""
    with db() as conn:
        case_rows = conn.execute(
            "SELECT id, title, stage FROM cases WHERE user_id = ? "
            "ORDER BY updated_at DESC",
            (user_id,),
        ).fetchall()
        result = []
        for cr in case_rows:
            cid = cr["id"]
            msgs = conn.execute(
                "SELECT role, content FROM messages WHERE case_id = ? "
                "ORDER BY id DESC LIMIT 30",
                (cid,),
            ).fetchall()
            doc_summaries = conn.execute(
                "SELECT filename, COALESCE(summary, '') AS summary "
                "FROM documents WHERE case_id = ?",
                (cid,),
            ).fetchall()
            content_parts = [cr["title"] or ""]
            content_parts.extend(m["content"] or "" for m in msgs)
            content_parts.extend(
                f"{d['filename']}: {d['summary']}" for d in doc_summaries
            )
            result.append({
                "case_id": cid,
                "title": cr["title"] or "",
                "content": "\n".join(p for p in content_parts if p),
            })
    return result
