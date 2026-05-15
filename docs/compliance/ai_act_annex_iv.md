# EU AI Act — Annex IV Technical Documentation

Super Avvocato is provisionally classified as a **high-risk** AI system
under the AI Act, on the conservative reading that it provides
decision-support for legal professionals operating under regulated
duties (art. 6 + Annex III §8(a) — administration of justice). We
document accordingly even where that classification is not strictly
mandated.

## 1. General description (art. 11(1)(a), Annex IV §1)

- **Intended purpose**: assist qualified lawyers and law-firm staff
  with legal research, document drafting, deadline computation, and
  case strategy in the Albanian (and progressively wider) jurisdiction.
- **Intended users**: admitted lawyers, paralegals, law-firm
  administrative staff. Not for unsupervised use by lay citizens.
- **Out of scope**: criminal sentencing predictions, facial
  recognition, biometric categorisation, social scoring, employment
  scoring. The system MUST NOT be marketed for any of these uses.
- **Geographic scope**: Albania (primary), Italy and EU jurisdictions
  (V8.13+).

## 2. System architecture (Annex IV §2)

- **Frontend**: Flask + Jinja2 + plain JS (`static/app.js`,
  `static/style.css`).
- **Application logic**: Python 3.12 (`src/`).
- **Knowledge base**: BM25 index over 18 hand-curated legal-text
  sources (13 codes + Kushtetuta + 5 specific laws). The KB is built
  by `src/build_kb.py` and is fully reproducible from the source files
  in `data/`. The KB hash is exposed via the `/api/status` endpoint.
- **Foundation models**:
  - Anthropic Claude Opus 4.7 — main answer composition.
  - Anthropic Claude Sonnet 4.6 — analytical / intermediate stages.
  - Anthropic Claude Haiku 4.5 — JSON parsing / scaffolding ONLY.
- **Data store**: SQLite (`data/app.db`). Single-tenant by default,
  multi-tenant per studio in V8.0+.
- **No external API except**: the chosen LLM provider (Claude Code
  CLI / Anthropic API / Gemini API as configured).

## 3. Development process (Annex IV §3)

- Source control: `scripts/snapshot.py` snapshot system; full repo
  state at every released version.
- Testing: `benchmarks/run_eval.py` — 50 ground-truth Albanian legal
  queries, scored on citation_present / expected_code_hit /
  fake_count. Baseline V8.11: 92% expected_code_hit, 0 fake citations.
- Pre-deployment evaluation: every release MUST re-run the benchmark
  and the run file is archived under `benchmarks/runs/`.

## 4. Monitoring (Annex IV §4)

- Application logs: `data/logs/app.log` (rotated by `logging_utils`).
- AI Act art. 12 log: `ai_audit_log` table (one row per LLM call,
  see `ai_act_art12_logging.md`).
- Provenance packs: one per user-visible answer, stored in
  `provenance_packs` table; downloadable as JSON or DOCX.

## 5. Risk management (Annex IV §5)

See `risk_register.md`.

Primary mitigations:

1. **Citation Shield V2** (V8.11) — every "Neni X" cited in an
   answer is verified against the BM25 index; fakes are flagged in
   the UI. Below 50% confidence the system refuses.
2. **Human-in-the-loop**: every output ends with a reminder that
   the lawyer is responsible for review; deadlines and document
   drafts are explicitly marked as "do not file unread".
3. **Provenance pack**: lawyer + regulator can replay any answer
   with the exact KB hash + model + prompt hash that produced it.

## 6. Conformity assessment (art. 43)

Pending external conformity assessment by an accredited notified
body. Until then the system operates under self-assessed conformity
with the obligations in art. 9-15 (risk management, data governance,
technical documentation, record-keeping, transparency, human
oversight, accuracy/robustness/cybersecurity).

## 7. CE marking

Not yet affixed. Plan: complete external assessment by 2027-01-01
(initial AI Act enforcement deadline for high-risk systems).

## 8. Post-market monitoring (art. 72)

- All material errors reported by users land in
  `feedback` and `ai_audit_log` tables and are reviewed weekly by
  the founder.
- Serious incidents (output that caused or could have caused
  material legal harm) are reported per `incident_response.md`.
