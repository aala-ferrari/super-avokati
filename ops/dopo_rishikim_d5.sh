#!/bin/bash
# v9.634 — aspetta la fine della misura della revisione (tools/misura_rishikim.sh), poi il binario D5 del banco dei modelli
# (Opus 5.5 max + Sonnet 5.5) DA SOLO, con almeno 4 GB liberi. Si lancia staccato:  nohup setsid bash ops/dopo_rishikim_d5.sh &
set -u
L=/var/log/superavokati/bench634
mkdir -p "$L"
echo "$(date -u +%FT%TZ) attendo la fine della misura della revisione" >> "$L/timeline.txt"
until grep -q MISURA_FINITA /tmp/misura_rishikim.out 2>/dev/null && ! docker ps --format '{{.Names}}' | grep -qx sa-rk; do sleep 30; done
for i in $(seq 1 120); do [ "$(free -m | awk '/^Mem:/{print $7}')" -ge 4000 ] && break; sleep 30; done
echo "$(date -u +%FT%TZ) memoria disponibile $(free -m | awk '/^Mem:/{print $7}') MB — parte D5" >> "$L/timeline.txt"
cd /var/www/apps/super-avvocato && bash ops/bench_modelli634.sh D5 > /tmp/bench634.out 2>&1
echo "$(date -u +%FT%TZ) FINITO" >> "$L/timeline.txt"
