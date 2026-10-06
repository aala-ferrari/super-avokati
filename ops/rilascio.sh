#!/usr/bin/env bash
# ops/rilascio.sh vX.Y — IL RILASCIO in un comando (1 ott 2026), al posto degli script copiati a mano con sed per ogni versione
# (due volte oggi si sono rotti: condizioni che contavano righe «8/8 ok» uguali di prove diverse). Decide sui CODICI DI USCITA:
#   1. build dell'immagine
#   2. QA in un container di prova (COPIA del DB, dati :ro): golden, smoke, giurisdizione e tutte le prove dello scadenziario —
#      ognuna esce 1 se fallisce
#   3. deploy SOLO se tutto è verde, con la guardia (ops/deploy_when_idle.sh: mai durante il lavoro di un avvocato)
#   4. QA in produzione
# Si lancia SUL SERVER, staccato dalla ssh:  nohup setsid bash ops/rilascio.sh v9.448 > /dev/null 2>&1 < /dev/null &
# Esito in /tmp/qa-<versione>.out (ultima riga QA_FINITA; «QA NON VERDE: niente deploy» se qualcosa è rosso).
set -u
V="${1:?versione, es. v9.448}"
APP=/var/www/apps/super-avvocato
OUT="/tmp/qa-$V.out"
PROVE="prova_conferma_telegram prova_sollecito prova_link_scadenze prova_fascicolo_lungo prova_segretaria_avvisi
       prova_scadenze_studio prova_doppioni prova_rinvio prova_ripresa prova_chiedi"
PROVE=$(echo $PROVE)                 # su UNA riga: dentro «bash -c» un a capo spezza il for (primo uso, v9.449: nessuna prova girava)
cd "$APP" || exit 1
: > "$OUT"
if ! docker build -q -t "super-avvocato:$V" . > /dev/null 2>> "$OUT"; then
  echo "BUILD FALLITO: niente deploy" >> "$OUT"; echo QA_FINITA >> "$OUT"; exit 1
fi
T=$(mktemp -d /tmp/tqa.XXXX)
trap 'rm -rf "$T"' EXIT      # v9.518: la copia del DB (e delle credenziali) non resta in /tmp nemmeno se lo script si interrompe
python3 -c "import sqlite3;s=sqlite3.connect('$APP/data/app.db');d=sqlite3.connect('$T/app.db');s.backup(d);d.close()"
chown -R 1000:1000 "$T"
docker run --rm --name "sa-q-$V" --memory=6000m --oom-score-adj=900 --env-file /opt/super-avvocato.env \
  -e APP_DB_PATH=/tqa/app.db -e TELEGRAM_BOT_TOKEN= -e RESEND_API_KEY= \
  -v "$APP/data:/app/data:ro" -v "$T:/tqa" "super-avvocato:$V" bash -c "
    ok=1
    python3 tools/golden_check.py > /tmp/g.out 2>&1 || ok=0
    grep -E 'Përfundim|DËSHTIME' /tmp/g.out; grep '31m✗' /tmp/g.out | cut -c1-300
    python3 tools/smoke_test.py > /tmp/s.out 2>&1 || { ok=0; echo 'SMOKE ROSSO'; }; tail -1 /tmp/s.out
    python3 tools/juris_guard.py > /tmp/j.out 2>&1 || { ok=0; echo 'GIURISDIZIONE ROSSA'; }; tail -1 /tmp/j.out
    for p in $PROVE; do
      if python3 tools/\$p.py > /tmp/p.out 2>&1; then echo \"OK \$p \$(tail -1 /tmp/p.out)\"; else ok=0; echo \"KO \$p\"; grep '✗' /tmp/p.out | head -5; fi
    done
    [ \$ok = 1 ] && echo QA_VERDE
  " >> "$OUT" 2>&1
rm -rf "$T"
if grep -q "^QA_VERDE" "$OUT"; then
  bash ops/deploy_when_idle.sh "$V" > "/var/log/superavokati/deploy-$V.log" 2>&1
  until [ "$(docker inspect -f '{{.State.Health.Status}}' super-avvocato 2>/dev/null)" = healthy ]; do sleep 5; done
  sleep 20
  { echo "--- produzione"; docker ps --format "{{.Image}} {{.Status}}" | grep super-avvocato:
    docker exec super-avvocato python3 tools/golden_check.py 2>&1 | tail -1
    docker exec super-avvocato python3 tools/smoke_test.py 2>&1 | tail -1; } >> "$OUT" 2>&1
else
  echo "QA NON VERDE: niente deploy" >> "$OUT"
fi
echo QA_FINITA >> "$OUT"
