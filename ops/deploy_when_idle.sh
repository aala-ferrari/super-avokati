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

# ⚠️ `docker exec` SENZA `-i` non passa lo stdin: la prima versione usava
# `python3 - <<'PY'` e leggeva stdin vuoto → stampava niente → «0 attivi» →
# il riavvio partiva sempre e ha ucciso una domanda del titolare (16 set).
# Il conteggio va passato con -c, mai via stdin. Se il conteggio fallisce,
# si assume OCCUPATO (999), non libero.
# ⚠️ seconda trappola (16 set, 02:40): il conteggio girava con `-c` e il testo del
# programma — che contiene la stringa cercata — finiva nella cmdline del processo
# stesso: contava SEMPRE almeno 1 («1 analisi in corso» a container vuoto) e ogni
# deploy aspettava l'intera MAX_WAIT (v9.325 mai andato live: 1h49 di attesa, ucciso).
# Cura: si salta il proprio pid e l'ago non si scrive per intero.
_busy() {
  docker exec super-avvocato python3 -c '
import glob, os
me = str(os.getpid())
needle = "/usr/bin/" + "cla" + "ude"
n = 0
for f in glob.glob("/proc/[0-9]*/cmdline"):
    if f.split("/")[2] == me:
        continue
    try:
        c = open(f, "rb").read().replace(b"\0", b" ").decode(errors="ignore")
    except Exception:
        continue
    if needle in c:
        n += 1
print(n)
' 2>/dev/null || echo 999
}

waited=0
while :; do
  n=$(_busy | tail -1)
  case "$n" in ''|*[!0-9]*) n=999 ;; esac   # niente numero = non so = occupato
  if [ "$n" -eq 0 ]; then break; fi
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
