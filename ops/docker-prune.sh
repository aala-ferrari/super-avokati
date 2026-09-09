#!/usr/bin/env bash
# Igiene disco Docker: tiene solo le 2 immagini super-avvocato più recenti
# (attuale + rollback) e svuota la build cache. Il 9 set 2026 il disco si è
# riempito (193G, 100%, SITO GIÙ) per ~40 immagini da ~5GB lasciate dai build.
set -u
KEEP=2
# tag v9.NNN ordinati per numero, decrescente; via tutte tranne le prime KEEP
docker images super-avvocato --format '{{.Tag}}' \
  | grep -E '^v9\.[0-9]+$' \
  | sort -t. -k2 -n -r \
  | tail -n +$((KEEP + 1)) \
  | while read -r t; do
      docker rmi "super-avvocato:$t" >/dev/null 2>&1 && echo "rimossa super-avvocato:$t"
    done
docker builder prune -f >/dev/null 2>&1
docker image prune -f    >/dev/null 2>&1
echo "$(date -u +%FT%TZ) prune ok — disco: $(df -h / | awk 'NR==2{print $5" usato, "$4" liberi"}')"
