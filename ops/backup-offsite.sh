#!/bin/bash
# [C] Replica offsite dei backup cifrati. GATED: senza un remote rclone
# configurato non fa nulla e lo dice — un backup che sembra fatto e non
# esiste è peggio di nessun backup.
set -uo pipefail
if ! command -v rclone >/dev/null || ! rclone listremotes 2>/dev/null | grep -q "^offsite:"; then
  echo "$(date "+%F %T") ⏸ offsite non configurato (rclone remote \"offsite:\" assente) — in attesa credenziali"
  exit 0
fi
rclone sync /root/sa-backups offsite:superavokati/sa-backups --transfers 4 -q \
  && echo "$(date "+%F %T") ✅ sa-backups replicati offsite" \
  || echo "$(date "+%F %T") ❌ replica offsite FALLITA"
