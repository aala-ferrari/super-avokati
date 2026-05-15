# Data Residency & Self-Hosting

Super Avvocato is designed so that a firm can choose where its data
lives. Three deployment topologies are supported; the choice is made
by the firm's DPO based on the client mix and the applicable bar-rules
on cloud-stored client data.

## Topology A — SaaS (default, easiest)

- Application: hosted by Super Avvocato on EU-region infrastructure.
- Database: SQLite per tenant on the same host.
- LLM: Anthropic API (US infrastructure, zero-data-retention enterprise terms; EU-US Data Privacy Framework certification).
- Lawyer data leaves the EU only for the duration of the LLM
  inference call.

When to choose: solo / small firm without an in-house IT function and
without ultra-sensitive client data.

## Topology B — EU-hosted, EU-only LLM

- Application: hosted in EU.
- Database: in EU.
- LLM: configured to use only the Anthropic EU endpoint when
  available, OR a self-hosted open-weight model for inference.
- No data crosses the EU boundary.

When to choose: firms with EU-public-sector clients or matters
involving EU regulatory authorities.

## Topology C — Self-hosted (firm's own infrastructure)

- Application: deployed on the firm's own server (bare metal or
  private VPC). The full repo is provided; no proprietary closed
  components. `requirements.txt` lists every dependency.
- Database: the firm's own SQLite or Postgres instance.
- LLM: either the firm's own Anthropic enterprise contract OR a
  fully self-hosted open-weight model. The `BRAIN_BACKEND`
  environment variable selects which.
- Audit log + provenance packs: stay on the firm's hardware.

When to choose: large firms with critical-sensitivity client data,
public-sector matters where data crossing the firm boundary is
disallowed, or firms whose risk appetite requires R1 elimination
(see `gdpr_dpia.md`).

## Backend selection

The `BRAIN_BACKEND` environment variable controls which LLM is used:

- `claude_code` — Claude Code CLI (subscription auth; default in
  developer environments).
- `anthropic` — Anthropic API (provide `ANTHROPIC_API_KEY`).
- `gemini` — Google Gemini API (provide `GEMINI_API_KEY`).
- `auto` — pick the first available, in the order above.

For self-hosted open-weight models a thin adapter implementing
`LLMBackend` is straightforward (see `src/backends.py`); we maintain
a community-contributed Ollama backend on a side branch.

## Encryption

- In transit: HTTPS (the deploying firm provides the cert; the
  app does not run HTTPS internally).
- At rest: filesystem-level encryption is the deployer's
  responsibility. Recommended: LUKS on Linux, FileVault on macOS,
  BitLocker on Windows. The application does not store secrets in
  the database other than hashed passwords.

## Backup

The firm is responsible for backing up `data/`. The application is
stateless apart from `data/app.db` and `data/uploads/`; copying
those two directories is a complete backup.
