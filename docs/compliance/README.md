# Super Avvocato — Compliance Pack

This folder is the DPO / regulator-facing documentation pack for Super
Avvocato. It is meant to be handed to a Data Protection Officer, an
internal counsel, or a supervisory authority on request.

The pack is intentionally short. Lawyers reading it want answers, not
prose. Each file covers one regulatory question.

## Files

| File | Question it answers |
|---|---|
| `ai_act_annex_iv.md` | EU AI Act Annex IV technical documentation for a high-risk system |
| `ai_act_art12_logging.md` | How automated logging of system operations works (art. 12) |
| `ai_act_art13_transparency.md` | What end users are told about the AI (art. 13) |
| `ai_act_art14_human_oversight.md` | How a lawyer overrides / discards model output (art. 14) |
| `gdpr_dpia.md` | Data Protection Impact Assessment summary |
| `gdpr_data_map.md` | Personal data flows in the system |
| `gdpr_retention.md` | Retention periods + deletion procedure |
| `risk_register.md` | Known failure modes + mitigations |
| `incident_response.md` | What to do if the model gives wrong legal advice |
| `data_residency.md` | Where data lives, self-host option |

## Versioning

This pack is versioned with the application. The current application
version (and the SHA-256 hash of the legal knowledge base it ships with)
is exposed via `GET /api/status`. When a regulator audits a specific
incident, the response provenance pack
(`/api/provenance/<id>.json`) carries the exact KB hash that was used at
the time the answer was produced.

## Last review

- **Drafted**: 2026-04-26 (V8.12)
- **Owner**: Romeo Redi (founder, qualified lawyer)
- **Next review due**: 2026-10-26 (every 6 months minimum)
