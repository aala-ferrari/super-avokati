#!/usr/bin/env bash
# Prova dal vivo: LINGUA = SESSIONE.
#  A) sessione AL (account di prova, AL) + domanda scritta in ITALIANO
#     → la risposta deve essere in ALBANESE (e citare il Neni 114 KC).
#  B) sessione IT (avvocato.it) + domanda scritta in ALBANESE
#     → la risposta deve essere in ITALIANO (e citare l'art. 2946 c.c.).
# Entrambe passano dal percorso simple (~1 min l'una). Sull'host del VPS.
set -u
B=http://127.0.0.1:5050
S=$(grep '^DEMO_PROVISION_SECRET=' /opt/super-avvocato.env | cut -d= -f2- | tr -d '"'"'")
TS=$(date +%s)

conta() {  # $1 file, $2 etichetta — conta parole-spia albanesi e italiane nel testo finale
  local f=$1
  python3 - "$f" <<'PY'
import json, re, sys
raw = open(sys.argv[1], encoding="utf-8", errors="replace").read()
fin = ""
for ln in raw.splitlines():
    if ln.startswith("data:"):
        try:
            ev = json.loads(ln[5:].strip())
        except Exception:
            continue
        if ev.get("type") == "final":
            fin = ev.get("text") or (ev.get("data") or {}).get("text") or ""
t = " " + fin.lower() + " "
sq = sum(t.count(" %s " % w) for w in ("është", "nuk", "dhe", "për", "sipas", "neni", "kodi", "afati", "vjet", "që"))
it = sum(t.count(" %s " % w) for w in ("è", "non", "della", "il", "per", "art.", "codice", "termine", "anni", "che"))
print("   caratteri=%d  spie-albanesi=%d  spie-italiane=%d  | 114 KC: %s | 2946: %s" % (
    len(fin), sq, it, "neni 114" in t, "2946" in t))
print("   inizio:", fin[:220].replace("\n", " "))
PY
}

echo "=== A) sessione AL, domanda in italiano ==="
EMAIL="prova-gjuha-${TS}@superavokati.test"; CODE="Prova-${TS}-gj"; JAR=/tmp/pg_${TS}_a.jar
curl -s -o /dev/null -X POST $B/api/provision-demo -H "X-Provision-Secret: $S" -H 'Content-Type: application/json' \
  -d "{\"email\":\"$EMAIL\",\"code\":\"$CODE\",\"hours\":1,\"modules\":[\"avokat\"]}"
curl -s -o /dev/null -c $JAR -X POST $B/api/login -H 'Content-Type: application/json' -d "{\"username\":\"$EMAIL\",\"password\":\"$CODE\"}"
echo "   sessione: $(curl -s -b $JAR $B/api/session/jurisdiction)"
CID=$(curl -s -b $JAR -X POST $B/api/cases -H 'Content-Type: application/json' -d '{"title":"Prova lingua AL"}' | python3 -c 'import sys,json; print(json.load(sys.stdin)["id"])')
echo "   rifiuto IT in sessione AL → HTTP $(curl -s -o /dev/null -w '%{http_code}' -b $JAR -X POST $B/api/cases -H 'Content-Type: application/json' -d '{"title":"x","jurisdiction":"IT"}')"
JOB=$(curl -s -b $JAR -X POST $B/api/ask/start -H 'Content-Type: application/json' \
  -d "{\"message\":\"Qual è il termine ordinario di prescrizione dei contratti secondo il Codice Civile?\",\"case_id\":\"$CID\"}" | python3 -c 'import sys,json; print(json.load(sys.stdin).get("job_id",""))')
T0=$(date +%s); curl -s -N -b $JAR --max-time 900 -o /tmp/pg_${TS}_a.stream "$B/api/ask/events?job=$JOB&from=0"; echo "   stream in $(( $(date +%s)-T0 ))s"
conta /tmp/pg_${TS}_a.stream
docker exec super-avvocato python -c "from src import storage; print('   pulizia:', storage.delete_user('$EMAIL'))"

echo "=== B) sessione IT (admin.it, AL+IT), domanda in albanese ==="
JAR=/tmp/pg_${TS}_b.jar
curl -s -o /dev/null -c $JAR -X POST $B/api/login -H 'Content-Type: application/json' -d '{"username":"admin.it","password":"AdminIT2026!","lang":"it"}'
echo "   sessione: $(curl -s -b $JAR $B/api/session/jurisdiction)"
echo "   fascicoli visibili/nascosti: $(curl -s -b $JAR $B/api/cases | python3 -c 'import sys,json; d=json.load(sys.stdin); print(len(d["cases"]), "/", d.get("hidden_other"))')"
CID=$(curl -s -b $JAR -X POST $B/api/cases -H 'Content-Type: application/json' -d '{"title":"Prova lingua IT"}' | python3 -c 'import sys,json; print(json.load(sys.stdin)["id"])')
JOB=$(curl -s -b $JAR -X POST $B/api/ask/start -H 'Content-Type: application/json' \
  -d "{\"message\":\"Cili është afati i zakonshëm i parashkrimit të kontratave sipas Kodit Civil?\",\"case_id\":\"$CID\"}" | python3 -c 'import sys,json; print(json.load(sys.stdin).get("job_id",""))')
T0=$(date +%s); curl -s -N -b $JAR --max-time 900 -o /tmp/pg_${TS}_b.stream "$B/api/ask/events?job=$JOB&from=0"; echo "   stream in $(( $(date +%s)-T0 ))s"
conta /tmp/pg_${TS}_b.stream
echo "=== C) cancello: lo STESSO utente passa alla sessione AL ==="
echo "   in IT: GET /api/cases/$CID → HTTP $(curl -s -o /dev/null -w '%{http_code}' -b $JAR $B/api/cases/$CID)"
curl -s -o /dev/null -b $JAR -c $JAR -X POST $B/api/session/jurisdiction -H 'Content-Type: application/json' -d '{"jurisdiction":"AL"}'
echo "   sessione ora: $(curl -s -b $JAR $B/api/session/jurisdiction)"
echo "   in AL: GET /api/cases/$CID → HTTP $(curl -s -o /dev/null -w '%{http_code}' -b $JAR $B/api/cases/$CID)  (atteso 404)"
echo "   in AL: /api/cases visibili/nascosti: $(curl -s -b $JAR $B/api/cases | python3 -c 'import sys,json; d=json.load(sys.stdin); print(len(d["cases"]), "/", d.get("hidden_other"))')"
echo "   in AL: ask sul fascicolo IT → HTTP $(curl -s -o /dev/null -w '%{http_code}' -b $JAR -X POST $B/api/ask/start -H 'Content-Type: application/json' -d "{\"message\":\"test\",\"case_id\":\"$CID\"}")  (atteso 404)"
curl -s -o /dev/null -b $JAR -c $JAR -X POST $B/api/session/jurisdiction -H 'Content-Type: application/json' -d '{"jurisdiction":"IT"}'
curl -s -o /dev/null -b $JAR -X DELETE $B/api/cases/$CID && echo "   fascicolo di prova IT cancellato (sessione riportata a IT)"
rm -f /tmp/pg_${TS}_*.jar
