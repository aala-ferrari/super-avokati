#!/usr/bin/env bash
# prova_viva.sh <AL|IT> "<domanda>" <etichetta> — domanda vera dal percorso start+events, risposta finale in /tmp/pv_<etichetta>.txt
set -u
J=$1; Q=$2; L=$3
B=http://127.0.0.1:5050
S=$(grep '^DEMO_PROVISION_SECRET=' /opt/super-avvocato.env | cut -d= -f2- | tr -d '"'"'")
TS=$(date +%s)
EMAIL="prova-viva-${L}-${TS}@superavokati.test"; CODE="Prova-${TS}-pv"; JAR=/tmp/pv_${TS}.jar; OUT=/tmp/pv_${L}.stream
curl -s -X POST $B/api/provision-demo -H "X-Provision-Secret: $S" -H 'Content-Type: application/json' \
  -d "{\"email\":\"$EMAIL\",\"code\":\"$CODE\",\"hours\":2,\"modules\":[\"avokat\"]}" > /dev/null
if [ "$J" = "IT" ]; then
  docker exec super-avvocato python -c "from src import storage; u=storage.get_user_by_username('$EMAIL'); print('giurisdizioni:', storage.set_user_jurisdictions(u.id, ['AL','IT']))"
fi
curl -s -c $JAR -X POST $B/api/login -H 'Content-Type: application/json' -d "{\"username\":\"$EMAIL\",\"password\":\"$CODE\"}" > /dev/null
[ "$J" = "IT" ] && curl -s -b $JAR -c $JAR -X POST $B/api/session/jurisdiction -H 'Content-Type: application/json' -d '{"jurisdiction":"IT"}' && echo
CID=$(curl -s -b $JAR -X POST $B/api/cases -H 'Content-Type: application/json' -d "{\"title\":\"Prova viva $L\",\"jurisdiction\":\"$J\"}" | python3 -c 'import sys,json; print(json.load(sys.stdin)["id"])')
BODY=$(python3 -c 'import json,sys; print(json.dumps({"message": sys.argv[1], "case_id": sys.argv[2]}))' "$Q" "$CID")
JOB=$(curl -s -b $JAR -X POST $B/api/ask/start -H 'Content-Type: application/json' -d "$BODY" | python3 -c 'import sys,json; print(json.load(sys.stdin).get("job_id",""))')
T0=$(date +%s)
HTTP=$(curl -s -N -b $JAR --max-time 2400 -o $OUT -w '%{http_code}' "$B/api/ask/events?job=$JOB&from=0")
echo "HTTP $HTTP in $(( $(date +%s)-T0 ))s — eventi $(grep -c '^data:' $OUT)"
python3 - "$OUT" "/tmp/pv_${L}.txt" <<'PY'
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
docker exec super-avvocato python -c "from src import storage; print('pulizia:', storage.delete_user('$EMAIL'))"
rm -f $JAR
