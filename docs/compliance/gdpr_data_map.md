# GDPR — Data Map

```
                 ┌──────────────────────────────┐
                 │ Lawyer / firm staff (browser)│
                 └──────────┬───────────────────┘
                            │ HTTPS
                            ▼
                 ┌──────────────────────────────┐
                 │ Flask app  (src/web.py)      │
                 │  • session cookie            │
                 │  • CSRF on POST              │
                 └──────────┬───────────────────┘
                            │
              ┌─────────────┼──────────────┐
              ▼             ▼              ▼
    ┌──────────────┐ ┌────────────┐ ┌────────────────┐
    │ SQLite       │ │ BM25 idx   │ │ LLM backend    │
    │ data/app.db  │ │ data/kb/   │ │ (Claude / etc) │
    └──────────────┘ └────────────┘ └─────┬──────────┘
                                          │ API call
                                          ▼
                                ┌──────────────────────┐
                                │ Anthropic API        │
                                │ (zero retention TOS) │
                                └──────────────────────┘
```

## Stores

| Store | Location | Personal data? | Encryption |
|---|---|---|---|
| `data/app.db` | SQLite, on the application host | Yes (users, dossiers, chat, calendar, audit) | At-rest via filesystem (deployer responsibility) |
| `data/uploads/` | Filesystem | Yes (uploaded dossier files) | At-rest via filesystem |
| `data/kb/` | Filesystem | No (legal codes, public domain) | n/a |
| Application logs | `data/logs/` | Possibly (chat IDs, error stacks) | At-rest |

## Data flows

1. **Lawyer uploads document** → stored under
   `data/uploads/<case_id>/`; OCR text indexed in `documents` table.
2. **Lawyer asks question** → prompt built from KB + case docs + chat
   history; sent to LLM provider; response stored in `messages` table
   and audited in `ai_audit_log`.
3. **System schedules deadline** → row in `events` + `reminders`;
   optional Telegram push.
4. **Lawyer downloads provenance pack** → row served from
   `provenance_packs`; never leaves the firm's instance.

## Third-party processors

| Processor | Purpose | DPA in place |
|---|---|---|
| Anthropic | LLM inference | Yes (Anthropic enterprise terms) |
| Telegram | Optional push notifications | Lawyers opt-in per user |
| (none others) | | |

## Cross-border transfers

Anthropic processes prompts on US infrastructure. Lawyers
processing EU personal data rely on:

- the EU-US Data Privacy Framework (Anthropic is certified), and/or
- Anthropic's Standard Contractual Clauses, and/or
- self-hosted deployment (see `data_residency.md`).
