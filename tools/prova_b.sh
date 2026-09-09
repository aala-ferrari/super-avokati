#!/usr/bin/env bash
# Prova dal vivo del gradino B via HTTP: la domanda dell'Aventador in un
# fascicolo AL nuovo deve prendere il percorso SIMPLE con i raccoglitori,
# rispondere in albanese citando il Neni 153 e metterci minuti, non 44.
set -u
B=http://127.0.0.1:5050
S=$(grep '^DEMO_PROVISION_SECRET=' /opt/super-avvocato.env | cut -d= -f2- | tr -d '"'"'")
TS=$(date +%s)
EMAIL="prova-b-${TS}@superavokati.test"; CODE="Prova-${TS}-b"; JAR=/tmp/pb_${TS}.jar
curl -s -o /dev/null -X POST $B/api/provision-demo -H "X-Provision-Secret: $S" -H 'Content-Type: application/json' \
  -d "{\"email\":\"$EMAIL\",\"code\":\"$CODE\",\"hours\":1,\"modules\":[\"avokat\"]}"
curl -s -o /dev/null -c $JAR -X POST $B/api/login -H 'Content-Type: application/json' -d "{\"username\":\"$EMAIL\",\"password\":\"$CODE\"}"
CID=$(curl -s -b $JAR -X POST $B/api/cases -H 'Content-Type: application/json' -d '{"title":"Prova gradino B"}' | python3 -c 'import sys,json; print(json.load(sys.stdin)["id"])')
Q="kam nje rast klienti ankohet se e ka ndaluar policia e shtetit, dhe i thot se makina e tij lamborghini aventador ben zhurme dhe se do i vendosin gjobe. nderkoh klienti deklaron se makina esht makin fabrike e pa modifikuar. cila esht shkelja?"
T0=$(date +%s)
JOB=$(curl -s -b $JAR -X POST $B/api/ask/start -H 'Content-Type: application/json' \
  -d "$(python3 -c 'import json,sys; print(json.dumps({"message": sys.argv[1], "case_id": sys.argv[2]}))' "$Q" "$CID")" | python3 -c 'import sys,json; print(json.load(sys.stdin).get("job_id",""))')
curl -s -N -b $JAR --max-time 1500 -o /tmp/pb_${TS}.stream "$B/api/ask/events?job=$JOB&from=0"
T1=$(date +%s)
python3 - /tmp/pb_${TS}.stream $((T1-T0)) <<'PY'
import json, sys
raw = open(sys.argv[1], encoding="utf-8", errors="replace").read()
fin = ""; stati = []
for ln in raw.splitlines():
    if ln.startswith("data:"):
        try: ev = json.loads(ln[5:].strip())
        except Exception: continue
        if ev.get("type") == "status": stati.append(ev.get("text", "")[:60])
        if ev.get("type") == "final": fin = ev.get("text") or (ev.get("data") or {}).get("text") or ""
t = fin.lower()
print("   tempo totale: %ss | caratteri: %d | Neni 153: %s | 79 come centrale: %s | italiano: %s" % (
    sys.argv[2], len(fin), "153" in t, ("neni 79" in t and "153" not in t), any(w in (" "+t+" ") for w in (" della ", " codice ", " art. "))))
print("   stati:", " → ".join(dict.fromkeys(stati)))
print("   inizio:", fin[:300].replace("\n", " "))
PY
echo "   log del server:"
docker logs --since 30m super-avvocato 2>&1 | grep -i "simple fast-path\|mbledhësit\|ancorati\|kërkuesi shtoi\|analizë e thellë" | tail -5 | cut -c1-200
docker exec super-avvocato python -c "from src import storage; print('   pulizia:', storage.delete_user('$EMAIL'))"
rm -f $JAR
