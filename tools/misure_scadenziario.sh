#!/usr/bin/env bash
# v9.437 — LE TRE MISURE dello scadenziario in un comando (SULL'HOST): estrazione dai documenti (eval_scadenziario), termini di
# legge (eval_afati), Segretaria (eval_segretaria). Copia del DB e delle credenziali (mai i dati veri: il cervello, caricandosi,
# scrive nel DB), immagine in produzione, pulizia alla fine. Costa ~20 chiamate al cervello (~15 minuti). Da lanciare dopo ogni
# modifica a scadenziario, afati, deadline_engine o secretary. Riferimento (1 ott 2026): date 11/11 · termini 6/6 · inneschi 2/2 · rinvii 2/2 ·
# 0 vietate · 0 inventate | termini di legge 4/4 | Segretaria 8/8.
set -u
APP=/var/www/apps/super-avvocato
T=$(mktemp -d /tmp/misure.XXXX)
IMG=$(docker inspect -f '{{.Config.Image}}' super-avvocato)
mkdir -p "$T/tqa"
python3 -c "import sqlite3;s=sqlite3.connect('$APP/data/app.db');d=sqlite3.connect('$T/tqa/app.db');s.backup(d);d.close()"
cp -a /opt/claude-creds "$T/creds"
chown -R 1000:1000 "$T"
for m in eval_scadenziario eval_afati eval_segretaria; do
  echo "=== $m ($IMG)"
  docker run --rm --memory=7000m --oom-score-adj=900 --env-file /opt/super-avvocato.env -e TELEGRAM_BOT_TOKEN= -e RESEND_API_KEY= \
    -e APP_DB_PATH=/tqa/app.db -v "$T/tqa:/tqa" -v "$APP/data:/app/data:ro" -v "$T/creds:/home/avvocato/.claude" \
    "$IMG" python3 "tools/$m.py" 2>&1 | grep -v "INFO\|WARNING\|legalkb\|Postgres\|sqlalche\|connection\|TCP/IP\|host:"
done
rm -rf "$T"
