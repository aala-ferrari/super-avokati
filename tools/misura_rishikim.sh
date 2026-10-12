#!/bin/bash
# v9.634 — MISURA DELLA REVISIONE DEI DOCUMENTI (tools/eval_rishikim.py) in un container di prova: server web acceso su una COPIA
# del DB, canali spenti (Telegram, email, notifiche), credenziali copiate (il CLI riscrive .credentials.json), niente ripresa dei
# lavori né scadenziario automatico. Esito in /tmp/misura_rishikim.out, testi in /tmp/misura_rishikim/. Mai col banco pesante acceso.
#   bash tools/misura_rishikim.sh [id_caso ...]
set -u
APP=/var/www/apps/super-avvocato
IMG=${IMG:-$(docker inspect -f '{{.Config.Image}}' super-avvocato)}
OUT=/tmp/misura_rishikim.out
: > "$OUT"
free -m | sed -n 2p >> "$OUT"
T=$(mktemp -d /tmp/rk.XXXX)
python3 -c "import sqlite3;s=sqlite3.connect('file:$APP/data/app.db?mode=ro',uri=True);d=sqlite3.connect('$T/app.db');s.backup(d);d.close()"
mkdir -p "$T/uploads" "$T/creds"; cp -a /opt/claude-creds/. "$T/creds/"; chown -R 1000:1000 "$T"
docker rm -f sa-rk >/dev/null 2>&1
docker run -d --name sa-rk --memory=5000m --oom-score-adj=900 --env-file /opt/super-avvocato.env \
  -e APP_DB_PATH=/tqa/app.db -e TELEGRAM_BOT_TOKEN= -e RESEND_API_KEY= -e VAPID_PRIVATE_KEY= -e VAPID_PUBLIC_KEY= \
  -e LOG_PATH=/tmp/x.log -e RIPRESA_LAVORI=0 -e SCADENZIARIO_AUTO=0 \
  -v $APP/data:/app/data:ro -v "$T":/tqa -v "$T/uploads":/app/data/uploads -v "$T/creds":/home/avvocato/.claude \
  -v $APP/tools:/app/tools:ro "$IMG" >/dev/null
trap 'docker cp sa-rk:/tmp/misura_rishikim /tmp/ >/dev/null 2>&1; docker exec sa-rk cat /tmp/x.log > /tmp/misura_rishikim.app.log 2>/dev/null; docker rm -f sa-rk >/dev/null 2>&1; rm -rf "$T"' EXIT
for i in $(seq 1 80); do docker exec sa-rk python3 -c "import urllib.request;urllib.request.urlopen('http://127.0.0.1:5050/api/status',timeout=3)" >/dev/null 2>&1 && break; sleep 3; done
echo "immagine $IMG, server di prova pronto dopo ~$((i*3)) s" >> "$OUT"
docker exec sa-rk python3 -u tools/eval_rishikim.py "$@" >> "$OUT" 2>&1
echo "uscita $?" >> "$OUT"
echo MISURA_FINITA >> "$OUT"
