# AI Act art. 12 — Automatic Logging

## What is logged

One row per LLM invocation lands in `ai_audit_log` (SQLite). Every
backend call goes through `src/backends.py`, which wraps the actual API
call with timing + hashing + audit emission.

| Column | Meaning |
|---|---|
| `id` | row id (primary key) |
| `timestamp` | UTC ISO-8601 |
| `user_id` | who issued the request (nullable for system calls) |
| `case_id` | which dossier the call belongs to (nullable) |
| `callsite` | which function inside the codebase made the call (auto-inferred from stack) |
| `backend` | claude_code / anthropic / gemini |
| `model` | exact model identifier (e.g. `claude-opus-4-7`) |
| `tier` | `default` / `medium` / `fast` (lawyer-first routing) |
| `prompt_hash` | SHA-256[:16] of the system + flattened messages |
| `response_hash` | SHA-256[:16] of the assistant text (null on error) |
| `prompt_raw` | optional truncated raw prompt (only if `AI_AUDIT_STORE_RAW=1`) |
| `response_raw` | optional truncated raw response (only if `AI_AUDIT_STORE_RAW=1`) |
| `latency_ms` | wall-clock time from invocation to result |
| `input_tokens` | from provider response (Anthropic populates; CLI does not) |
| `output_tokens` | as above |
| `outcome` | `success` / `error` |
| `error_class` | Python exception class on error (e.g. `TimeoutExpired`, `ResumeFailed`) |
| `extra_json` | free-form JSON: session_id, resumed flag, stream flag |

## What is NOT logged by default

Raw prompt and response text are NOT persisted by default — only the
SHA-256[:16] hashes. This is a deliberate GDPR / data-minimisation
choice: hashes are enough to (a) prove the same input produces the same
output (reproducibility), (b) match an audit row to a provenance pack
that DOES contain the full text under access control. Set
`AI_AUDIT_STORE_RAW=1` in the environment if a regulator requires raw
storage during a specific investigation; truncation defaults to 4000
characters, configurable via `AI_AUDIT_RAW_TRUNCATE`.

## Retention

The audit log is append-only. Default retention: indefinite (the table
is never truncated). When deploying for clients with stricter retention
policy, run a periodic `DELETE FROM ai_audit_log WHERE timestamp < ?`
job. Recommended floor: 5 years (matches Albanian tax-record retention
and exceeds the AI Act art. 19(1) minimum of 6 months).

## Access

- Lawyers / firm admins see THEIR OWN call history via case-level
  views (V8.13+).
- Platform admins access the full log via the `/api/admin/audit*`
  endpoints (auth: `is_admin=1` flag on user row).
- Regulators receive a JSONL export via
  `GET /api/admin/audit.jsonl?since=YYYY-MM-DD`.

## Failure mode

Audit emission is best-effort: a failure to write to `ai_audit_log`
logs a WARNING in the application log and the user request continues.
This is a deliberate design choice — refusing service because of an
audit-store hiccup is worse than the missing log row, and the
application log captures the hiccup independently. If audit log
integrity is critical for a specific deployment, switch to a
WAL-mode database with synchronous writes.
