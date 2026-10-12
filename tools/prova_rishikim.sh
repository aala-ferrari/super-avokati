#!/bin/bash
# v9.633 — prova viva della REVISIONE di un documento col codice nuovo (/tmp/sa634): server web in un container di prova (COPIA del
# DB, canali spenti, credenziali copiate), account di prova, fascicolo, il documento caricato, la domanda, risposta in /tmp/pr_<etichetta>.txt
set -u
APP=/var/www/apps/super-avvocato
IMG=${IMG:-super-avvocato:v9.632}
DOC=${DOC:?percorso del documento da caricare (es. un .doc/.docx/.pdf in data/uploads)}
NOME=${NOME:-$(basename "$DOC")}
L=${L:-rishikim}
J=${J:-AL}
Q=${Q:-"rishiko pak kete dokument nese esht ok per te autorizuar drejtimin e mjetit prone e shoqeris shpk, nga administratori i saj. per perdorim jasht shtetit."}
free -m | head -2
T=$(mktemp -d /tmp/r634.XXXX)
python3 -c "import sqlite3;s=sqlite3.connect('file:$APP/data/app.db?mode=ro',uri=True);d=sqlite3.connect('$T/app.db');s.backup(d);d.close()"
mkdir -p "$T/uploads" "$T/creds"; cp -a /opt/claude-creds/. "$T/creds/"; chown -R 1000:1000 "$T"
docker rm -f sa-r634 >/dev/null 2>&1
docker run -d --name sa-r634 --memory=5000m --oom-score-adj=900 --env-file /opt/super-avvocato.env \
  -e APP_DB_PATH=/tqa/app.db -e TELEGRAM_BOT_TOKEN= -e RESEND_API_KEY= -e VAPID_PRIVATE_KEY= -e VAPID_PUBLIC_KEY= \
  -e LOG_PATH=/tmp/x.log -e RIPRESA_LAVORI=0 -e SCADENZIARIO_AUTO=0 \
  -p 127.0.0.1:5098:5050 \
  -v $APP/data:/app/data:ro -v "$T":/tqa -v "$T/uploads":/app/data/uploads -v "$T/creds":/home/avvocato/.claude \
  -v /tmp/sa634/src:/app/src:ro -v /tmp/sa634/tools:/app/tools:ro \
  -v /tmp/sa634/static:/app/static:ro -v /tmp/sa634/templates:/app/templates:ro \
  "$IMG" >/dev/null
trap 'docker logs sa-r634 > /tmp/pr_${L}.docker.log 2>&1; docker exec sa-r634 cat /tmp/x.log > /tmp/pr_${L}.app.log 2>/dev/null; docker rm -f sa-r634 >/dev/null 2>&1; rm -rf "$T"' EXIT
B=http://127.0.0.1:5098
for i in $(seq 1 80); do curl -fsS $B/api/status >/dev/null 2>&1 && break; sleep 3; done
echo "server di prova pronto dopo ~$((i*3)) s"
S=$(grep '^DEMO_PROVISION_SECRET=' /opt/super-avvocato.env | cut -d= -f2- | tr -d '"'"'")
TS=$(date +%s)
EMAIL="prova-rishikim-${TS}@superavokati.test"; CODE="Prova-${TS}-pr"; JAR=/tmp/pr_${TS}.jar; OUT=/tmp/pr_${L}.stream
curl -s -X POST $B/api/provision-demo -H "X-Provision-Secret: $S" -H 'Content-Type: application/json' \
  -d "{\"email\":\"$EMAIL\",\"code\":\"$CODE\",\"hours\":3,\"modules\":[\"avokat\",\"noter\",\"prokuror\"]}" > /dev/null
if [ "$J" = "IT" ]; then
  docker exec sa-r634 python -c "from src import storage; u=storage.get_user_by_username('$EMAIL'); print('giurisdizioni:', storage.set_user_jurisdictions(u.id, ['AL','IT']))"
fi
curl -s -c $JAR -X POST $B/api/login -H 'Content-Type: application/json' -d "{\"username\":\"$EMAIL\",\"password\":\"$CODE\"}" > /dev/null
curl -s -b $JAR -c $JAR -X POST $B/api/legal/accept -H 'Content-Type: application/json' -d '{}' > /dev/null 2>&1
[ "$J" = "IT" ] && curl -s -b $JAR -c $JAR -X POST $B/api/session/jurisdiction -H 'Content-Type: application/json' -d '{"jurisdiction":"IT"}' && echo
CID=$(curl -s -b $JAR -X POST $B/api/cases -H 'Content-Type: application/json' -d "{\"title\":\"Prova revisione $L\",\"jurisdiction\":\"$J\"}" | python3 -c 'import sys,json; print(json.load(sys.stdin)["id"])')
echo "fascicolo $CID"
curl -s -b $JAR -F "file=@$DOC;filename=$NOME" "$B/api/cases/$CID/documents" | python3 -c 'import sys,json; d=json.load(sys.stdin); print("caricato:", (d.get("document") or d).get("status"), (d.get("document") or d).get("error"))'
for i in $(seq 1 60); do
  ST=$(curl -s -b $JAR "$B/api/cases/$CID/documents" | python3 -c 'import sys,json; ds=json.load(sys.stdin).get("documents") or [{}]; d=ds[-1]; print(d.get("status"), d.get("has_text"), (d.get("error") or "")[:80])')
  case "$ST" in pending*) sleep 4 ;; *) break ;; esac
done
echo "documento: $ST"
BODY=$(python3 -c 'import json,sys; print(json.dumps({"message": sys.argv[1], "case_id": sys.argv[2]}))' "$Q" "$CID")
JOB=$(curl -s -b $JAR -X POST $B/api/ask/start -H 'Content-Type: application/json' -d "$BODY" | python3 -c 'import sys,json; print(json.load(sys.stdin).get("job_id",""))')
T0=$(date +%s)
HTTP=$(curl -s -N -b $JAR --max-time 3000 -o $OUT -w '%{http_code}' "$B/api/ask/events?job=$JOB&from=0")
echo "HTTP $HTTP in $(( $(date +%s)-T0 ))s — eventi $(grep -c '^data:' $OUT)"
python3 - "$OUT" "/tmp/pr_${L}.txt" <<'PY'
import json, sys
fin = ""
for ln in open(sys.argv[1], encoding="utf-8", errors="replace"):
    if not ln.startswith("data:"): continue
    try: ev = json.loads(ln[5:])
    except Exception: continue
    if ev.get("type") in ("final", "done") and (ev.get("text") or ev.get("answer") or ev.get("content")):
        fin = ev.get("text") or ev.get("answer") or ev.get("content")
open(sys.argv[2], "w").write(fin or "")
print("risposta finale:", len(fin), "caratteri")
PY
docker exec sa-r634 sh -c "grep -E 'rishikim|formato reale|norme della revisione|stage|complex|simple|gjyqtari|djalli|ancorati' /tmp/x.log | tail -40" > /tmp/pr_${L}.righe.log 2>/dev/null
rm -f $JAR
