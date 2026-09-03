#!/bin/bash
# ──────────────────────────────────────────────────────────────────────
# Super Avokati — ricrea il container dall'immagine consolidata v9.3.
# v9.3 (docker commit del 23/06/2026) contiene TUTTI i fix:
#   - ricerca WEB nel Genio (WebSearch/WebFetch) + istruzione "ago nel pagliaio"
#   - --resume rimosso (follow-up usa la history completa)
#   - privacy errori (claude -> Tetramorph)
#   - effort=max, timeout 30 min, pulsante verde ~10 min
#   - token CLAUDE_CODE_OAUTH_TOKEN + CLAUDE_CODE_EFFORT in /app/.env (dentro l'immagine)
# I sorgenti aggiornati sono anche in ./src e ./templates (per rebuild puliti).
# ──────────────────────────────────────────────────────────────────────
set -e
docker rm -f super-avvocato 2>/dev/null || true
docker run -d --name super-avvocato --restart unless-stopped \
  -p 127.0.0.1:5050:5050 \
  --env-file /opt/super-avvocato.env \
  -v /var/www/apps/super-avvocato/data:/app/data \
  -v /opt/claude-creds:/home/avvocato/.claude \
  super-avvocato:v9.257
# ripristina .claude.json (fuori dal mount, sparisce ai rebuild) — evita warning nel cervello
sleep 3
docker exec -u avvocato super-avvocato sh -c 'test -f /home/avvocato/.claude.json || cp "$(ls -t /home/avvocato/.claude/backups/.claude.json.backup.* 2>/dev/null | head -1)" /home/avvocato/.claude.json 2>/dev/null' || true
echo "✓ super-avvocato avviato da v9.3"
