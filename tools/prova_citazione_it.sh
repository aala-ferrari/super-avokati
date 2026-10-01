#!/usr/bin/env bash
# v9.458 — prova dal vivo: un ATTO DI CITAZIONE ricevuto (sessione ITALIANA, sull'HOST) → lo scadenziario propone l'udienza e i
# termini del convenuto A RITROSO dall'udienza (art. 166: 70 giorni prima → 24/11/2026; art. 171-ter: 24/12, 13/01, 22/01). Account di
# prova, cancellato alla fine; nessun avviso esce (account .test, nessun Telegram).
set -u
B=http://127.0.0.1:5050
S=$(grep '^DEMO_PROVISION_SECRET=' /opt/super-avvocato.env | cut -d= -f2- | tr -d '"'"'")
TS=$(date +%s)
EMAIL="prova-citit-${TS}@superavokati.test"
CODE="Prova-${TS}-citit"
JAR=/tmp/prova_citit_${TS}.jar
DOC=/tmp/prova_citit_${TS}.txt
trap 'docker exec super-avvocato python -c "from src import storage; print(storage.delete_user(\"'"$EMAIL"'\"))" >/dev/null; rm -f $JAR $DOC' EXIT
cat > $DOC <<'TXT'
TRIBUNALE DI MILANO
ATTO DI CITAZIONE
La Beta Forniture S.r.l., con l'avv. Paolo Neri,
CITA
la Gamma Impianti S.p.A. a comparire all'udienza del 2 febbraio 2027, ore 9:30, davanti al Tribunale di Milano, giudice designando,
con l'invito a costituirsi nel termine di settanta giorni prima dell'udienza indicata ai sensi e nelle forme dell'art. 166 c.p.c.,
con l'avvertimento che la costituzione oltre il termine implica le decadenze di cui agli artt. 38 e 167 c.p.c.
Per ottenere la condanna al pagamento di euro 48.000 per inadempimento del contratto di fornitura.
Milano, 15 settembre 2026 — avv. Paolo Neri
RELATA DI NOTIFICA: notificato a mezzo PEC alla Gamma Impianti S.p.A. il 24 settembre 2026.
TXT
j() { python3 -c "import sys,json; d=json.load(sys.stdin); print($1)"; }
curl -s -X POST $B/api/provision-demo -H "X-Provision-Secret: $S" -H 'Content-Type: application/json' \
  -d "{\"email\":\"$EMAIL\",\"code\":\"$CODE\",\"hours\":1,\"modules\":[\"avokat\"]}" >/dev/null
docker exec super-avvocato python3 -c "from src import storage; u=storage.get_user_by_username('$EMAIL'); print(storage.set_user_jurisdictions(u.id, ['IT']))" >/dev/null 2>&1
curl -s -c $JAR -X POST $B/api/login -H 'Content-Type: application/json' -d "{\"username\":\"$EMAIL\",\"password\":\"$CODE\",\"lang\":\"it\"}" >/dev/null
CID=$(curl -s -b $JAR -X POST $B/api/cases -H 'Content-Type: application/json' -d '{"title":"Gamma c. Beta","jurisdiction":"IT"}' | j 'd["id"]')
echo "1) fascicolo IT $CID"
curl -s -b $JAR -F "file=@$DOC;filename=citazione_gamma.txt" $B/api/cases/$CID/documents >/dev/null
T0=$(date +%s)
for i in $(seq 1 150); do
  R=$(curl -s -b $JAR $B/api/cases/$CID/scadenze)
  [ "$(echo "$R" | j 'len(d.get("proposte",[]))>0 and not d.get("in_corso")')" = "True" ] && break; sleep 5
done
echo "2) proposte comparse da sole in $(( $(date +%s) - T0 ))s:"
echo "$R" | python3 -c '
import sys,json; d=json.load(sys.stdin)
for p in d.get("proposte",[]): print("   ", p["tipo"], p["origine"], p["data"] or "—", p.get("ora") or "", "ver=%s" % p["verificato"], "|", p["titolo"][:75], "|", (p.get("base") or "")[:40])
print("    nota esempio:", next((p["nota"][:140] for p in d.get("proposte",[]) if p.get("nota")), ""))'
echo "3) avviso: $(docker logs --since 15m super-avvocato 2>&1 | grep 'avviso di .* scadenze nuove' | tail -1 | cut -c60-200)"
