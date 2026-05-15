# GDPR — Data Protection Impact Assessment (Summary)

A full DPIA is recommended for any deployment where lawyers process
client personal data through the system. This document captures the
risk analysis common to every Super Avvocato deployment; firms layer
their own client-specific DPIA on top.

## 1. Processing operation

Super Avvocato ingests legal questions, dossier documents (PDFs,
images, contracts, evidence) and produces written analysis,
draft briefs, calendar entries, contract redlines.

## 2. Lawful basis (art. 6)

- Per the firm's mandate from its client → art. 6(1)(b) (contract).
- Where the firm acts on a court's appointment → art. 6(1)(c)
  (legal obligation) and art. 6(1)(e) (public interest).
- Special categories (criminal data, health data, etc.) →
  professional secrecy (art. 9(2)(f) + art. 10) — the firm relies
  on its lawyers' professional privilege as the carve-out.

## 3. Data categories

| Category | Source | Processing |
|---|---|---|
| Client identity | dossier upload | retrieved by name in answers; not sent to any third party |
| Case facts | dossier + chat | sent to LLM provider as part of the prompt |
| Counterparty data | dossier | as above |
| Lawyer / staff identity | login | used for access control + audit |

## 4. Data subjects

- The firm's clients (primary).
- Counterparties named in dossiers.
- Witnesses and third parties named in evidence.
- The firm's own lawyers and staff.

## 5. Risks identified

- **R1 — LLM provider exposure**. Prompts are sent to the
  configured LLM provider. Mitigation: enterprise contract with
  zero-data-retention (Anthropic enterprise tier) OR self-hosted
  model. Default deployment uses Anthropic with zero retention.
- **R2 — Hallucinated citations**. Mitigation: Citation Shield
  V2 (V8.11) post-verifies every citation; refuses below 50%
  confidence.
- **R3 — Cross-case leakage**. Risk that dossier text from case A
  ends up in an answer to case B. Mitigation: every prompt builds
  the retrieval set from `case_id`-scoped documents only;
  multi-tenancy (V8.0+) isolates studios.
- **R4 — Audit log accumulation**. Mitigation: hashes by default
  (no raw text), configurable retention.
- **R5 — Insider misuse**. Mitigation: every action is attributed
  to a `user_id` in the audit log; admin-only access to
  cross-firm data.

## 6. Residual risk

After mitigations, residual risk is assessed as **medium** for R1
(provider dependency cannot be eliminated short of self-hosting)
and **low** for the rest. Self-hosting is offered as a deployment
option for firms whose risk appetite requires R1 elimination
(see `data_residency.md`).

## 7. Review

Every 12 months or whenever a material architectural change is
made. The next material change pending review: V8.13
multi-jurisdiction (Italy/EU KB).
