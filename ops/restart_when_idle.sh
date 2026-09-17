#!/usr/bin/env bash
# Riavvio del container SENZA immagine nuova (v9.347, 17 set 2026): serve quando cambia solo un
# DATO sul volume — indice IT/AL ricostruito (`build_it_index.py`, `ingest_al_qbz.py apply`),
# precedenti aggiunti — e il processo vivo deve ricaricarlo (i pickle si leggono all'avvio).
# Stessa guardia di deploy_when_idle.sh: si riparte solo quando nel container non gira nessun
# processo del cervello, altrimenti si uccide l'analisi di un avvocato. Tetto MAX_WAIT_MIN (45),
# poi si procede comunque.
#
#   ops/restart_when_idle.sh
#   MAX_WAIT_MIN=90 ops/restart_when_idle.sh
set -u
MAX_WAIT_MIN="${MAX_WAIT_MIN:-45}"
echo "RESTART RICHIESTO $(date -u +%H:%M:%S)  ($(docker ps --format '{{.Image}}' --filter name=^super-avvocato$))"

# ⚠️ come in deploy_when_idle.sh: conteggio con -c (mai via stdin), si salta il proprio pid e
# l'ago non si scrive per intero; conteggio non numerico = OCCUPATO.
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
  case "$n" in ''|*[!0-9]*) n=999 ;; esac
  if [ "$n" -eq 0 ]; then break; fi
  if [ "$waited" -ge $((MAX_WAIT_MIN * 60)) ]; then
    echo "ATTESA SCADUTA ($MAX_WAIT_MIN min) con $n processi attivi: procedo comunque"
    break
  fi
  [ $((waited % 300)) -eq 0 ] && echo "$(date -u +%H:%M:%S) in attesa: $n analisi in corso"
  sleep 30; waited=$((waited + 30))
done

docker restart super-avvocato >/dev/null || { echo "RESTART FALLITO"; exit 1; }
docker cp /root/completa_brief.py super-avvocato:/tmp/completa_brief.py 2>/dev/null || true
for i in 1 2 3 4 5 6 7 8 9 10 11 12; do
  st=$(docker inspect -f '{{.State.Health.Status}}' super-avvocato 2>/dev/null)
  [ "$st" = "healthy" ] && break
  sleep 5
done
echo "salute: ${st:-?} · sito $(curl -s -o /dev/null -w '%{http_code}' https://superavokati.ai/)"
echo "RESTART DONE $(date -u +%H:%M:%S)"
