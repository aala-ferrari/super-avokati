#!/bin/bash
# v9.393 — MISURA DEI MODELLI PER PERCORSO (richiesta del titolare, 25 set): stesse domande, stessa immagine, env diverse.
# Tre binari in parallelo (container di prova, canali promemoria/email/notifiche SPENTI, credenziali in copia):
#   S  = domande semplici (il triage decide): S0 oggi (inizio Sonnet 5, senior Opus 5 max) · S1 senior Opus 5.5 high ·
#        S2 senior Opus 5.5 max · S3 inizio Opus 5.5 medium al posto di Sonnet (senior di oggi) · S4 inizio Opus 5.5 medium +
#        senior Opus 5.5 high («togliere Sonnet: un buon inizio cambia il finale», 25 set)
#   Da = sala di guerra: D0 oggi (senior Opus 5 max, diavolo Fable high, Giudice Fable max) · D1 Giudice Opus 5.5 max
#   Db = sala di guerra: D3 tutto Opus 5.5 (inizio e fasi junior medium, senior high, Giudice max; diavolo Fable high) ·
#        D2 senior Opus 5.5 high + Giudice Opus 5.5 max (inizio Sonnet)
IMG=${IMG:-super-avvocato:v9.393}
L=/var/log/superavokati/bench393
mkdir -p "$L"
SIMPLE="al-parashkrim-civil-01,al-zhurma-makina-01,al-trashegimi-ligjore-pjeset-01,al-mosha-pergjegjesise-penale-01,al-afati-ankimit-civil-01,al-neni-88-kp-01,al-divorci-pelqim-01,al-ketamina-7975-01,it-prescrizione-ordinaria-01,it-prescrizione-illecito-01,it-impugnazione-licenziamento-01,it-art-2043-01"
DEEP="al-pushim-leje-qendrimi-01,al-prona-kufizim-rubrika-d-01,it-auto-shpk-targa-albanese-01,it-cittadinanza-matrimonio-01,it-immobiliare-visura-ipoteca-pignoramento-01,it-licenziamento-gmo-tutele-crescenti-01"

run_variant() {   # container, nome, modo, ids, env...
  local C=$1 NAME=$2 MODE=$3 IDS=$4; shift 4
  docker rm -f "$C" >/dev/null 2>&1
  docker run -d --name "$C" --memory=3500m --oom-score-adj=900 \
    --env-file /opt/super-avvocato.env \
    -e TELEGRAM_BOT_TOKEN= -e WHATSAPP_TOKEN= -e RESEND_API_KEY= -e VAPID_PRIVATE_KEY= -e VAPID_PUBLIC_KEY= \
    -v /var/www/apps/super-avvocato/data:/app/data \
    -v /tmp/creds-test:/home/avvocato/.claude \
    -v /var/www/apps/super-avvocato/tools/golden_cases:/app/tools/golden_cases:ro \
    "$@" "$IMG" >/dev/null
  sleep 3
  docker exec -u avvocato "$C" sh -c 'test -f /home/avvocato/.claude.json || cp "$(ls -t /home/avvocato/.claude/backups/.claude.json.backup.* 2>/dev/null | head -1)" /home/avvocato/.claude.json 2>/dev/null' || true
  for i in $(seq 1 90); do
    docker exec "$C" python3 -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:5050/api/status', timeout=5).status == 200 else 1)" >/dev/null 2>&1 && break
    sleep 5
  done
  echo "$(date -u +%FT%TZ) START $NAME ($MODE) env: $*" >> "$L/timeline.txt"
  # --limit 0 = TUTTI i casi (il predefinito dello strato 2 è 3: il primo giro del 25 set ne ha misurati 3 per variante)
  docker exec "$C" python3 tools/benchmark_lab.py run --layer 2 --limit 0 --mode "$MODE" --ids "$IDS" > "$L/$NAME.log" 2>&1
  echo "$(date -u +%FT%TZ) END   $NAME: $(grep -o "strato 2: .*" "$L/$NAME.log" | head -c 300)" >> "$L/timeline.txt"
  docker rm -f "$C" >/dev/null 2>&1
}

# DUE binari, non tre: tre container di misura + la produzione hanno esaurito gli 11 GB (OOM del 25 set, 21:39: il kernel ha
# ucciso il container della D3 — marcato oom-score-adj 900 apposta — e la produzione è rimasta intatta)
binario_A() {
  run_variant sa-bench-a S0 normal "$SIMPLE"
  run_variant sa-bench-a S1 normal "$SIMPLE" -e SENIOR_SIMPLE_MODEL=claude-opus-5-5 -e SENIOR_SIMPLE_EFFORT=high
  run_variant sa-bench-a S3 normal "$SIMPLE" -e CLAUDE_CODE_FAST_MODEL=claude-opus-5-5 -e CLAUDE_CODE_FAST_EFFORT=medium -e CLAUDE_CODE_MEDIUM_MODEL=claude-opus-5-5 -e CLAUDE_CODE_MEDIUM_EFFORT=medium
  run_variant sa-bench-a S4 normal "$SIMPLE" -e CLAUDE_CODE_FAST_MODEL=claude-opus-5-5 -e CLAUDE_CODE_FAST_EFFORT=medium -e CLAUDE_CODE_MEDIUM_MODEL=claude-opus-5-5 -e CLAUDE_CODE_MEDIUM_EFFORT=medium -e SENIOR_SIMPLE_MODEL=claude-opus-5-5 -e SENIOR_SIMPLE_EFFORT=high
  run_variant sa-bench-a S2 normal "$SIMPLE" -e SENIOR_SIMPLE_MODEL=claude-opus-5-5 -e SENIOR_SIMPLE_EFFORT=max
  echo S_DONE >> "$L/timeline.txt"
  run_variant sa-bench-a D2 deep "$DEEP" -e SENIOR_DEEP_MODEL=claude-opus-5-5 -e SENIOR_DEEP_EFFORT=high -e STUDIO_GJYQTARI_MODEL=claude-opus-5-5
  echo A_DONE >> "$L/timeline.txt"
}
binario_B() {
  run_variant sa-bench-b D0 deep "$DEEP"
  run_variant sa-bench-b D1 deep "$DEEP" -e STUDIO_GJYQTARI_MODEL=claude-opus-5-5
  run_variant sa-bench-b D3 deep "$DEEP" -e CLAUDE_CODE_FAST_MODEL=claude-opus-5-5 -e CLAUDE_CODE_FAST_EFFORT=medium -e CLAUDE_CODE_MEDIUM_MODEL=claude-opus-5-5 -e CLAUDE_CODE_MEDIUM_EFFORT=medium -e SENIOR_DEEP_MODEL=claude-opus-5-5 -e SENIOR_DEEP_EFFORT=high -e STUDIO_GJYQTARI_MODEL=claude-opus-5-5
  echo B_DONE >> "$L/timeline.txt"
}
binario_A &
sleep 120
binario_B &
wait
echo BENCH_DONE >> "$L/timeline.txt"
