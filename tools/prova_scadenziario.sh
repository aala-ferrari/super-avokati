#!/usr/bin/env bash
# v9.410 — prova dal vivo dello SCADENZIARIO del fascicolo (sull'HOST): account di prova → fascicolo AL → carica una sentenza
# (testo) → analisi dei documenti → proposte → conferma di un'udienza (evento + avvisi) → calcolo dei termini di legge con la
# data di notifica → vista di tutti i clienti. 2-3 chiamate al cervello (~3-5 min). Cancella l'account alla fine.
set -u
B=http://127.0.0.1:5050
S=$(grep '^DEMO_PROVISION_SECRET=' /opt/super-avvocato.env | cut -d= -f2- | tr -d '"'"'")
TS=$(date +%s)
EMAIL="prova-scad-${TS}@superavokati.test"
CODE="Prova-${TS}-scad"
JAR=/tmp/prova_scad_${TS}.jar
DOC=/tmp/prova_scad_${TS}.txt
trap 'docker exec super-avvocato python -c "from src import storage; print(storage.delete_user(\"'"$EMAIL"'\"))" >/dev/null; rm -f $JAR $DOC' EXIT
cat > $DOC <<'TXT'
REPUBLIKA E SHQIPËRISË — GJYKATA E RRETHIT GJYQËSOR TIRANË
VENDIM Nr. 4567, datë 10.09.2026
PADITËS: Elira Kola; I PADITUR: Shoqëria "Delta" sh.p.k. OBJEKTI: Pagimi i shpërblimit për pushim të padrejtë nga puna.
PËR KËTO ARSYE, Gjykata VENDOSI: Pranimin pjesërisht të padisë. Kundër këtij vendimi mund të bëhet ankim në Gjykatën e Apelit
Tiranë brenda 15 ditëve nga dita e nesërme e njoftimit të vendimit.
Në çështjen tjetër midis të njëjtave palë (nr. 890/2026), seanca e radhës caktohet më 20.10.2026, ora 11:00, salla 5, dhe palët
duhet të paraqesin dëshmitarët deri më 15 tetor 2026.
TXT
j() { python3 -c "import sys,json; d=json.load(sys.stdin); print($1)"; }
curl -s -X POST $B/api/provision-demo -H "X-Provision-Secret: $S" -H 'Content-Type: application/json' \
  -d "{\"email\":\"$EMAIL\",\"code\":\"$CODE\",\"hours\":1,\"modules\":[\"avokat\"]}" >/dev/null
curl -s -c $JAR -X POST $B/api/login -H 'Content-Type: application/json' -d "{\"username\":\"$EMAIL\",\"password\":\"$CODE\"}" >/dev/null
CID=$(curl -s -b $JAR -X POST $B/api/cases -H 'Content-Type: application/json' -d '{"title":"Prova scadenziario","jurisdiction":"AL"}' | j 'd["id"]')
echo "1) fascicolo $CID"
curl -s -b $JAR -F "file=@$DOC;filename=vendim_4567.txt" $B/api/cases/$CID/documents | j 'd.get("id"), d.get("status")'
for i in $(seq 1 30); do
  ST=$(curl -s -b $JAR $B/api/cases/$CID/documents | j '",".join(x["status"] for x in d["documents"])')
  [ "$ST" = "ready" ] && break; sleep 3
done
echo "2) documento: $ST"
echo "3) analizza → $(curl -s -b $JAR -X POST $B/api/cases/$CID/scadenze/analizza -H 'Content-Type: application/json' -d '{}')"
T0=$(date +%s)
for i in $(seq 1 120); do
  R=$(curl -s -b $JAR $B/api/cases/$CID/scadenze)
  [ "$(echo "$R" | j 'd["in_corso"]')" = "False" ] && break; sleep 5
done
echo "4) analisi in $(( $(date +%s) - T0 ))s:"
echo "$R" | python3 -c '
import sys,json; d=json.load(sys.stdin)
for p in d["proposte"]: print("   ", p["tipo"], p["kind"], p["data"] or "—", p.get("ora") or "", "ver=%s" % p["verificato"], "|", p["titolo"][:70])
print("    analisi:", d["analisi"])'
PID_UD=$(echo "$R" | j 'next((p["id"] for p in d["proposte"] if p["kind"]=="seance" and p["data"]), "")')
PID_IN=$(echo "$R" | j 'next((p["id"] for p in d["proposte"] if p["tipo"]=="innesco"), "")')
echo "5) conferma udienza → $(curl -s -b $JAR -X POST $B/api/scadenze/$PID_UD/conferma -H 'Content-Type: application/json' -d '{}')"
docker exec super-avvocato python3 -c "
from src import storage
ev=[e for e in storage.list_events(user_id=storage.get_user_by_username('$EMAIL').id) if e.case_id=='$CID']
for e in ev: print('    evento:', e.title, e.starts_at, e.kind, 'avvisi:', [(r.offset_minutes, r.fire_at) for r in storage.list_reminders_for_event(e.id)])
" 2>&1 | grep -v INFO
[ -n "$PID_IN" ] && echo "6) calcola termini di legge (notifica 25.09.2026) → $(curl -s -b $JAR -X POST $B/api/scadenze/$PID_IN/calcola -H 'Content-Type: application/json' -d '{"data":"2026-09-25"}')"
curl -s -b $JAR $B/api/cases/$CID/scadenze | python3 -c '
import sys,json; d=json.load(sys.stdin)
for p in d["proposte"]:
    if p["origine"]=="legge" and p["tipo"]=="data": print("    legge:", p["data"], "|", p["titolo"][:70], "|", (p.get("base") or "")[:60], "ver=%s" % p["verificato"])'
echo "7) tutti i clienti → $(curl -s -b $JAR $B/api/scadenze | j 'len(d["scadenze"])') voci"
echo "8) telegram link → $(curl -s -b $JAR $B/api/settings/telegram/link)"
