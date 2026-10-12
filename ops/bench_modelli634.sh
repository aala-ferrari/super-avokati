#!/bin/bash
# v9.634 — il binario D5 MAI girato (titolare, 12 ott sera: «Opus 5.5 e Sonnet 5.5 insieme: fai questa misurazione»), sulle
# STESSE 6 domande difficili e con lo stesso metro di D0 / D4 / D0S5. Copia di ops/bench_modelli626.sh.
# v9.626 — MISURA richiesta dal titolare (12 ott): «Opus 5.5 max per i casi difficili» e «Sonnet 5.5 al posto del vecchio Sonnet».
# Stesse domande, stessa immagine, env diverse; varianti accese SOLO nei container di prova (canali spenti, credenziali in copia).
#   S0 oggi (inizio Sonnet 5, senior Opus 5 max)                       · S5 inizio e fasi junior Sonnet 5.5 (senior di oggi)
#   D0 oggi sui casi DIFFICILI albanesi (senior Opus 5 max, diavolo Fable high, Giudice Fable max)
#   D4 senior dei casi difficili Opus 5.5 MAX (resto di oggi)          · D5 D4 + inizio e fasi junior Sonnet 5.5
# Il 26 set (v9.393) avevano perso: Giudice Opus 5.5, senior 5.5 high + Giudice 5.5, tutto 5.5, inizio Opus 5.5. MAI misurato:
# il senior 5.5 MAX col Giudice di oggi, e Sonnet 5.5 (il CLI 2.1.282 lo serve con una riga d'avviso: letta dal v9.626).
IMG=${IMG:-super-avvocato:v9.634}
# ⚠️ OGNI binario su una COPIA del database (12 ott): con il database vero il ciclo dei promemoria del container di prova (canali
# spenti) segnava come FATTI il riepilogo del mattino e i solleciti degli avvocati veri — li segna prima di spedirli — e in
# produzione non partivano più. Copia e credenziali per binario, cancellate alla fine.
B=${1:-AB}
CR=/tmp/creds-test-$B; DB=/tmp/stbench_$B
rm -rf "$CR" "$DB" && cp -a /opt/claude-creds "$CR" && mkdir -p "$DB"
python3 -c "import sqlite3;s=sqlite3.connect('/var/www/apps/super-avvocato/data/app.db');d=sqlite3.connect('$DB/app.db');s.backup(d);d.close()"
chown -R 1000:1000 "$CR" "$DB"
trap 'rm -rf "$CR" "$DB"' EXIT
L=/var/log/superavokati/bench634
mkdir -p "$L"
SIMPLE="al-parashkrim-civil-01,al-zhurma-makina-01,al-trashegimi-ligjore-pjeset-01,al-mosha-pergjegjesise-penale-01,al-afati-ankimit-civil-01,al-neni-88-kp-01,al-divorci-pelqim-01,al-ketamina-7975-01,it-prescrizione-ordinaria-01,it-prescrizione-illecito-01,it-impugnazione-licenziamento-01,it-art-2043-01"
DEEP="al-pushim-leje-qendrimi-01,al-prona-kufizim-rubrika-d-01,al-gabim-mjekesor-gaze-01,al-vetting-ankim-kpk-01,al-pushim-goje-shofer-01,al-shitje-banese-bashkeshortore-01"
SONNET55="-e CLAUDE_CODE_MEDIUM_MODEL=claude-sonnet-5-5 -e CLAUDE_CODE_FAST_MODEL=claude-sonnet-5-5"
OPUS55MAX="-e SENIOR_DEEP_MODEL=claude-opus-5-5 -e SENIOR_DEEP_EFFORT=max"

run_variant() {   # container, nome, modo, ids, env...
  local C=$1 NAME=$2 MODE=$3 IDS=$4; shift 4
  docker rm -f "$C" >/dev/null 2>&1
  docker run -d --name "$C" --memory=3500m --oom-score-adj=900 \
    --env-file /opt/super-avvocato.env \
    -e TELEGRAM_BOT_TOKEN= -e WHATSAPP_TOKEN= -e RESEND_API_KEY= -e VAPID_PRIVATE_KEY= -e VAPID_PUBLIC_KEY= \
    -e FEEDBACK_ALERT=0 \
    -e APP_DB_PATH=/tbench/app.db -v "$DB":/tbench \
    -v /var/www/apps/super-avvocato/data:/app/data \
    -v "$CR":/home/avvocato/.claude \
    -v /var/www/apps/super-avvocato/tools/golden_cases:/app/tools/golden_cases:ro \
    "$@" "$IMG" >/dev/null
  sleep 3
  docker exec -u avvocato "$C" sh -c 'test -f /home/avvocato/.claude.json || cp "$(ls -t /home/avvocato/.claude/backups/.claude.json.backup.* 2>/dev/null | head -1)" /home/avvocato/.claude.json 2>/dev/null' || true
  for i in $(seq 1 90); do
    docker exec "$C" python3 -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:5050/api/status', timeout=5).status == 200 else 1)" >/dev/null 2>&1 && break
    sleep 5
  done
  echo "$(date -u +%FT%TZ) START $NAME ($MODE) env: $*" >> "$L/timeline.txt"
  docker exec "$C" python3 tools/benchmark_lab.py run --layer 2 --limit 0 --mode "$MODE" --ids "$IDS" > "$L/$NAME.log" 2>&1
  # i ripieghi per limite della sottoscrizione falsano la misura: si contano (e quei casi si rileggono a parte)
  echo "$(date -u +%FT%TZ) END   $NAME: $(grep -o "strato 2: .*" "$L/$NAME.log" | head -c 300) | ripieghi: $(docker logs "$C" 2>&1 | grep -c 'limite')" >> "$L/timeline.txt"
  docker logs "$C" > "$L/$NAME.container.log" 2>&1
  docker rm -f "$C" >/dev/null 2>&1
}

binario_A() {
  run_variant sa-bench-a S0 normal "$SIMPLE"
  run_variant sa-bench-a S5 normal "$SIMPLE" $SONNET55
  run_variant sa-bench-a D5 deep "$DEEP" $OPUS55MAX $SONNET55
  echo A_DONE >> "$L/timeline.txt"
}
binario_B() {
  run_variant sa-bench-b D0 deep "$DEEP"
  run_variant sa-bench-b D4 deep "$DEEP" $OPUS55MAX
  echo B_DONE >> "$L/timeline.txt"
}
# un binario alla volta («A» o «B») per far girare in parallelo l'audit degli strumenti (mai più di DUE container di prova
# insieme alla produzione: tre hanno esaurito gli 11 GB il 25 set); senza argomento i due binari insieme
binario_D5() {   # v9.634: DA SOLO (mai col rilascio né con un altro binario pesante)
  run_variant sa-bench-d5 D5 deep "$DEEP" $OPUS55MAX $SONNET55
  echo D5_DONE >> "$L/timeline.txt"
}
case "$1" in
  A) binario_A ;;
  B) binario_B ;;
  D5) binario_D5 ;;
  *) binario_A & sleep 120; binario_B & wait ;;
esac
echo "BENCH_DONE ${1:-AB}" >> "$L/timeline.txt"
