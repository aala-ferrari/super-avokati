#!/usr/bin/env bash
# v9.416 — prova dal vivo dello scadenziario AUTOMATICO in sessione ITALIANA (sull'HOST): account di prova IT → fascicolo IT → carica
# decreto ingiuntivo + verbale → nessun pulsante → proposte in italiano, termini di legge dal c.p.c. Cancella l'account alla fine.
set -u
B=http://127.0.0.1:5050
S=$(grep '^DEMO_PROVISION_SECRET=' /opt/super-avvocato.env | cut -d= -f2- | tr -d '"'"'")
TS=$(date +%s)
EMAIL="prova-scadit-${TS}@superavokati.test"
CODE="Prova-${TS}-scadit"
JAR=/tmp/prova_scadit_${TS}.jar
DOC=/tmp/prova_scadit_${TS}.txt
trap 'docker exec super-avvocato python -c "from src import storage; print(storage.delete_user(\"'"$EMAIL"'\"))" >/dev/null; rm -f $JAR $DOC' EXIT
cat > $DOC <<'TXT'
TRIBUNALE ORDINARIO DI MILANO — Sezione VI civile
DECRETO INGIUNTIVO n. 1234/2026 (R.G. 5678/2026)
Il Giudice, letto il ricorso depositato da Alfa S.r.l., INGIUNGE a Rossi Mario di pagare a Alfa S.r.l. la somma di euro 18.000,00
entro quaranta giorni dalla notificazione del presente decreto, con l'avvertimento che nello stesso termine può essere proposta
opposizione davanti a questo Tribunale. Milano, 15 settembre 2026. Il Giudice.
VERBALE DI UDIENZA — causa R.G. 9012/2025, Rossi Mario c. Beta S.p.A.
All'udienza del 2 ottobre 2026 il Giudice rinvia la causa all'udienza del 15.01.2027 ore 9.30 per la precisazione delle conclusioni,
assegnando alle parti termine di venti giorni dalla comunicazione del presente verbale per il deposito di memorie, e dispone che la
parte attrice depositi entro il 30 novembre 2026 copia del contratto di fornitura.
TXT
j() { python3 -c "import sys,json; d=json.load(sys.stdin); print($1)"; }
curl -s -X POST $B/api/provision-demo -H "X-Provision-Secret: $S" -H 'Content-Type: application/json' \
  -d "{\"email\":\"$EMAIL\",\"code\":\"$CODE\",\"hours\":1,\"modules\":[\"avokat\"]}" >/dev/null
docker exec super-avvocato python3 -c "from src import storage; u=storage.get_user_by_username('$EMAIL'); print(storage.set_user_jurisdictions(u.id, ['IT']))" >/dev/null 2>&1
curl -s -c $JAR -X POST $B/api/login -H 'Content-Type: application/json' -d "{\"username\":\"$EMAIL\",\"password\":\"$CODE\",\"lang\":\"it\"}" >/dev/null
CID=$(curl -s -b $JAR -X POST $B/api/cases -H 'Content-Type: application/json' -d '{"title":"Rossi c. Alfa","jurisdiction":"IT"}' | j 'd["id"]')
echo "1) fascicolo IT $CID"
curl -s -b $JAR -F "file=@$DOC;filename=decreto_e_verbale.txt" $B/api/cases/$CID/documents >/dev/null
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
