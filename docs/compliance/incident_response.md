# Incident Response

## What counts as an incident

| Severity | Definition | Examples |
|---|---|---|
| SEV-1 | Output caused or could have caused material legal harm | Wrong deadline filed, fake citation in a brief, leaked dossier to wrong matter |
| SEV-2 | Output systematically incorrect for a class of queries | Code repealed, KB version stale by 6 months |
| SEV-3 | System unavailable or degraded | LLM provider outage, DB locked |
| SEV-4 | Cosmetic / minor | UI typo, small formatting bug |

## Reporting channels

- In-app: "Report incident" button in dossier view (SEV-1/2/3) →
  writes a row in `incidents` table + emails the founder.
- Email: `romeoredi@libero.it` (founder, current incident owner).
- Telegram: bot `/admin incident <text>` (admin users only).

## Triage (within 4 hours of report)

1. **Reproduce**. Pull the response provenance pack
   (`/api/provenance/<id>.json`) — it contains the exact KB hash,
   model, and prompt hash that produced the output. Re-run the same
   prompt against the same KB hash; check whether the bug is
   deterministic.
2. **Scope**. Query `ai_audit_log` for the last 30 days filtered by
   the affected `callsite` and a similar `prompt_hash`. Estimate how
   many other lawyers were exposed.
3. **Contain**. If SEV-1: flip a feature flag to disable the
   affected callsite (e.g. add `if FEATURE_DISABLED.get('citation'):`
   short-circuit). If SEV-2: rebuild KB or pin to known-good model.
4. **Notify**. Notify affected lawyers via in-app banner +
   Telegram. If SEV-1 with downstream effect on a court filing,
   call them.

## Post-mortem (within 7 days)

A SEV-1 incident always gets a written post-mortem under
`docs/postmortems/YYYY-MM-DD-<slug>.md`. It contains:

- Timeline (UTC).
- Affected users + cases.
- Root cause.
- Remediation already shipped.
- Prevention plan.
- Whether AI Act art. 73 (serious-incident reporting to market
  surveillance authority) is triggered. Threshold: any incident
  causing infringement of fundamental rights, serious harm to
  health/safety/property, or serious disruption of critical
  infrastructure.

## Regulator notification

Where art. 73 is triggered:

1. Notify the competent market surveillance authority within the
   timeframe required (15 days for non-fatal incidents; 2 days for
   widespread infringement; 10 days for fatal incidents — keep the
   most conservative deadline as the working SLA).
2. Hand over the JSONL audit export
   (`GET /api/admin/audit.jsonl?since=...`) for the relevant period.
3. Hand over the provenance packs for the affected responses.
