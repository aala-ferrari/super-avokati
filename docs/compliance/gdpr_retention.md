# GDPR — Retention & Deletion

## Default retention periods

| Data | Default | Trigger for deletion |
|---|---|---|
| User account | indefinite while active | account closure → soft delete (anonymise PII, keep audit) |
| Dossier documents | per matter | matter closed + 10 years (matches Albanian advocate-archive duty) |
| Chat history | per matter | matter closed + 10 years |
| Calendar events | per matter | matter closed + 10 years |
| Provenance packs | per matter | matter closed + 10 years (audit trail) |
| `ai_audit_log` | indefinite | annual purge job optional (see art12_logging.md) |
| Application logs | 90 days rolling | log rotation |

These defaults reflect the typical Albanian / Italian advocate-archive
duty (10 years from matter closure). Firms with different obligations
can adjust per-table retention via cron jobs.

## Right to erasure (art. 17)

A data subject's request (typically a client of the firm) is
processed by the firm's DPO via:

1. Identify the relevant `case_id`(s) in `cases` table.
2. Run `DELETE FROM messages WHERE case_id IN (...)`,
   `DELETE FROM documents WHERE case_id IN (...)`,
   `DELETE FROM events WHERE case_id IN (...)`,
   `DELETE FROM provenance_packs WHERE case_id IN (...)`,
   `DELETE FROM cases WHERE id IN (...)`.
3. The `ai_audit_log` rows referencing those cases retain the
   `case_id` foreign reference but no longer point to a live row.
   Hashes alone are not personal data per GDPR Recital 26 (cannot be
   reversed without the original prompt). Therefore audit rows can
   be retained for AI Act compliance even after the underlying case
   is deleted.
4. Uploaded files in `data/uploads/<case_id>/` are removed from disk.

## Right to access (art. 15)

The firm exports the data subject's records via the existing case
export (`/api/cases/<id>/export.zip`) — JSON + uploaded files +
provenance packs. There is no platform-level data subject self-
service; the firm is the controller and mediates all DSARs.

## Right to rectification (art. 16)

Dossier metadata is editable in-app. Chat history is append-only by
design (legal-traceability requirement); rectification of factual
errors is handled by adding a correcting message rather than
editing prior turns.

## Procedure ownership

The DPO designated by the firm. Default escalation contact: the
firm's managing partner. Platform vendor (Anthropic) handles its own
sub-processor DSARs per its enterprise terms.
