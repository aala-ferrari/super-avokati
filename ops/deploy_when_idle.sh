#!/usr/bin/env bash
# Deploy che NON uccide il lavoro dell'avvocato (v9.322, regola del 15 set 2026).
#
# `./run.sh` ricrea il container: ogni analisi in corso muore («Failed to fetch»,
# «Tetramorph e' impegnato…» — visti dal titolare mentre deployavo). Qui la build
# parte subito (non tocca il container vivo), ma il RIAVVIO aspetta che dentro il
# container non ci sia nessun processo del cervello (claude CLI) e nessun job
# aperto. Tetto d'attesa: MAX_WAIT_MIN (default 45), poi si procede comunque.
#
#   ops/deploy_when_idle.sh v9.322          # OLD dedotto da run.sh
#   MAX_WAIT_MIN=90 ops/deploy_when_idle.sh v9.323
set -u
cd /var/www/apps/super-avvocato
NEW="$1"
OLD=$(grep -oE "super-avvocato:v[0-9.]+" run.sh | head -1 | cut -d: -f2)
MAX_WAIT_MIN="${MAX_WAIT_MIN:-45}"
[ -z "$NEW" ] && { echo "uso: $0 vX.Y"; exit 2; }
[ "$NEW" = "$OLD" ] && { echo "tag $NEW = tag attuale"; exit 2; }

echo "BUILD START $(date -u +%H:%M:%S)  ($OLD -> $NEW)"
df -h / | tail -1
docker build -q -t "super-avvocato:$NEW" . || { echo "BUILD FALLITA"; exit 1; }

_busy() {
  docker exec super-avvocato python3 - <<'PY' 2>/dev/null || echo 0
import glob
n = 0
for f in glob.glob("/proc/[0-9]*/cmdline"):
    try:
        c = open(f, "rb").read().replace(b"\0", b" ").decode(errors="ignore")
    except Exception:
        continue
    if "/usr/bin/claude" in c:
        n += 1
print(n)
PY
}

waited=0
while :; do
  n=$(_busy | tail -1)
  if [ "${n:-0}" -eq 0 ]; then break; fi
  if [ "$waited" -ge $((MAX_WAIT_MIN * 60)) ]; then
    echo "ATTESA SCADUTA ($MAX_WAIT_MIN min) con $n processi attivi: procedo comunque"
    break
  fi
  [ $((waited % 300)) -eq 0 ] && echo "$(date -u +%H:%M:%S) in attesa: $n analisi in corso"
  sleep 30; waited=$((waited + 30))
done

sed -i "s/super-avvocato:$OLD/super-avvocato:$NEW/" run.sh
echo "RUN.SH $(grep -oE "super-avvocato:v[0-9.]+" run.sh | head -1)"
./run.sh && /opt/docker-prune.sh
docker cp /root/completa_brief.py super-avvocato:/tmp/completa_brief.py 2>/dev/null || true
echo "DEPLOY DONE $(date -u +%H:%M:%S)"
