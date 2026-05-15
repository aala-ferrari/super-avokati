# Risk Register

Tracks the failure modes that materially threaten user (lawyer or
end-client) outcomes, plus their mitigations and residual risk.

| ID | Risk | Likelihood | Impact | Mitigation | Residual |
|---|---|---|---|---|---|
| RR-01 | Hallucinated citation (article number that does not exist) | Was high pre-V7.13 | Severe (could mislead a court filing) | Citation Shield V2 (V8.11) — every "Neni X" verified against BM25 index; flagged in UI; refusal below 50% confidence | Low |
| RR-02 | Stale legal text in KB (recent amendment not reflected) | Medium (KB rebuilt manually) | Severe | KB hash exposed in `/api/status` and provenance pack; planned: monthly KB-refresh cron + diff alert | Medium |
| RR-03 | Cross-case data leakage | Low | Severe | retrieval scoped to `case_id`; multi-tenancy isolation in V8.0 | Low |
| RR-04 | LLM provider outage | Medium | Moderate (degraded service) | three backends (Claude Code, Anthropic API, Gemini) with auto-fallback | Low |
| RR-05 | Prompt injection from uploaded document | Medium | Moderate (model could ignore instructions) | system prompts include explicit instruction-isolation; uploaded text rendered as DOSSIER content not SYSTEM | Medium |
| RR-06 | Misinterpreted procedural deadline | Medium | Severe (missed appeal) | deadline cascade engine (V7.11) uses code-driven rules, not LLM; lawyer must confirm before calendar entry is firm | Low |
| RR-07 | Audit log gaps | Low | Moderate (regulator finding) | best-effort emit + warning log + automated tests in benchmark | Low |
| RR-08 | Dossier upload exfiltration via vulnerable third-party lib | Medium | Severe | dependency pinning + monthly `pip-audit`; sandboxed renderers (PyMuPDF) | Medium |
| RR-09 | Adversarial user prompt that bypasses Citation Shield | Low | Severe | Shield runs on output text not on input — prompt cannot bypass post-output verification | Low |
| RR-10 | Catastrophic forgetting between session resumes | Low | Moderate (lawyer confused) | resume failure detected and surfaced as warning; session id invalidated and conversation re-bootstrapped | Low |

## Triggers for re-assessment

- Any change to the LLM provider or model identifier.
- Any change to the KB build pipeline.
- Any new feature that places AI output directly in front of a court
  or client without lawyer review (we do not currently allow this and
  any future feature that would must enter this register first).

## Last full review

- Drafted: 2026-04-26 (V8.12 ship)
- Owner: Romeo Redi
- Next: 2026-10-26
