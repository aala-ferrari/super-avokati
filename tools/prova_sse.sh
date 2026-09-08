#!/usr/bin/env bash
# Prova dal vivo dello stream /api/ask/events attraverso waitress (porta 5050,
# dentro il VPS): account di prova → login → fascicolo → domanda → stream.
# Prima della cura: HTTP 500 immediato (AssertionError hop-by-hop).
set -u
B=http://127.0.0.1:5050
S=$(grep '^DEMO_PROVISION_SECRET=' /opt/super-avvocato.env | cut -d= -f2- | tr -d '"'"'")
TS=$(date +%s)
EMAIL="prova-sse-${TS}@superavokati.test"
CODE="Prova-${TS}-sse"
JAR=/tmp/prova_sse_${TS}.jar
OUT=/tmp/prova_sse_${TS}.stream

echo "1) provision → $(curl -s -X POST $B/api/provision-demo -H "X-Provision-Secret: $S" \
  -H 'Content-Type: application/json' \
  -d "{\"email\":\"$EMAIL\",\"code\":\"$CODE\",\"hours\":1,\"modules\":[\"avokat\"]}")"
echo "2) login → $(curl -s -c $JAR -X POST $B/api/login -H 'Content-Type: application/json' \
  -d "{\"username\":\"$EMAIL\",\"password\":\"$CODE\"}")"
CASE=$(curl -s -b $JAR -X POST $B/api/cases -H 'Content-Type: application/json' \
  -d '{"title":"Prova stream SSE","jurisdiction":"AL"}')
CID=$(echo "$CASE" | python3 -c 'import sys,json; print(json.load(sys.stdin)["id"])')
echo "3) fascicolo → $CID"
START=$(curl -s -b $JAR -X POST $B/api/ask/start -H 'Content-Type: application/json' \
  -d "{\"message\":\"Cili nen i Kodit Rrugor dënon zhurmën e tepërt të marmitës së një automjeti?\",\"case_id\":\"$CID\"}")
JOB=$(echo "$START" | python3 -c 'import sys,json; print(json.load(sys.stdin).get("job_id",""))')
echo "4) job → $JOB  ($START)"
T0=$(date +%s)
CODE_HTTP=$(curl -s -N -b $JAR --max-time 600 -o $OUT -w '%{http_code}' \
  "$B/api/ask/events?job=$JOB&from=0")
T1=$(date +%s)
echo "5) stream HTTP $CODE_HTTP in $((T1-T0))s — eventi: $(grep -c '^data:' $OUT); done: $(grep -c '"done"' $OUT); final: $(grep -c '"final"' $OUT); error: $(grep -c '"type": *"error"' $OUT)"
echo "--- primi eventi ---"
grep '^data:' $OUT | head -4 | cut -c1-160
echo "--- ultimo evento (tagliato) ---"
grep '^data:' $OUT | tail -2 | cut -c1-400
echo "6) pulizia account di prova:"
docker exec super-avvocato python -c "from src import storage; print(storage.delete_user('$EMAIL'))"
rm -f $JAR
