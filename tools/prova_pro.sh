#!/bin/bash
# v9.642 — PROVA COL CERVELLO VERO in un container usa-e-getta (sull'host, da /root o dalla cartella dell'app):
#   bash tools/prova_pro.sh <nome> <script.py> [immagine] [cartella_con_src_di_prova]
# copia delle credenziali SENZA projects/ (1,3 GB di sessioni), copia del DB (APP_DB_PATH), canali di notifica spenti;
# lo script vede /out (risultati in /tmp/pp_<nome>/out) e il log va in /tmp/pp_<nome>/run.log. ⚠️ Mai sovrascrivere questo file
# mentre gira: bash legge lo script a pezzi e quello vecchio muore a metà (container e credenziali restano).
# copia delle credenziali SENZA projects/ (1,3 GB di sessioni), copia del DB, canali di notifica spenti
set -u
N="$1"; S="$2"; IMG="${3:-$(grep -o 'super-avvocato:v[0-9.]*' /var/www/apps/super-avvocato/run.sh | head -1)}"; SRC="${4:-}"
APP=/var/www/apps/super-avvocato
W=/tmp/pp_$N
rm -rf "$W"; mkdir -p "$W/tqa" "$W/out"
rsync -a --exclude projects /opt/claude-creds/ "$W/creds/"
python3 -c "import sqlite3,sys; s=sqlite3.connect('file:'+sys.argv[1]+'?mode=ro', uri=True); d=sqlite3.connect(sys.argv[2]); s.backup(d); d.close()" "$APP/data/app.db" "$W/tqa/app.db"
chown -R 1000:1000 "$W"
EXTRA=""
if [ -n "$SRC" ]; then EXTRA="-v $SRC/src:/app/src:ro"; fi
docker rm -f "pp_$N" >/dev/null 2>&1
docker run -d --name "pp_$N" --memory=4500m --oom-score-adj=900 --env-file /opt/super-avvocato.env \
  -e TELEGRAM_BOT_TOKEN= -e RESEND_API_KEY= -e VAPID_PRIVATE_KEY= -e APP_DB_PATH=/tqa/app.db \
  -v "$W/tqa:/tqa" -v "$W/out:/out" -v "$APP/data:/app/data:ro" -v "$W/creds:/home/avvocato/.claude" $EXTRA \
  --entrypoint sleep "$IMG" infinity >/dev/null
docker exec -u avvocato "pp_$N" sh -c 'cp "$(ls -t /home/avvocato/.claude/backups/.claude.json.backup.* 2>/dev/null | head -1)" /home/avvocato/.claude.json 2>/dev/null' || true
docker cp "$S" "pp_$N:/tmp/prova.py"
echo "start $(date -u +%H:%M:%S) img=$IMG src=${SRC:-immagine}" > "$W/run.log"
docker exec -u avvocato "pp_$N" python3 -u /tmp/prova.py >> "$W/run.log" 2>&1
echo "fine $(date -u +%H:%M:%S) rc=$?" >> "$W/run.log"
docker rm -f "pp_$N" >/dev/null 2>&1
rm -rf "$W/creds" "$W/tqa"
