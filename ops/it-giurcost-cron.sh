#!/bin/bash
# [B] Notturno: aggiorna anno corrente + estende un anno indietro.
set -uo pipefail
T=/var/www/apps/super-avvocato/tools/ingest_it_giurcost.py
META=/var/www/apps/super-avvocato/data/processed/it_decisions_meta.json
ANNO=$(date +%Y)
/usr/bin/python3 "$T" --anno "$ANNO"
MIN=$(/usr/bin/python3 -c "import json;m=json.load(open(\"$META\"));ys=m.get(\"CCost\",{}).get(\"complete_years\",[]);print(min(ys) if ys else $ANNO)" 2>/dev/null || echo "$ANNO")
PREC=$((MIN-1))
if [ "$PREC" -ge 1956 ]; then
  /usr/bin/python3 "$T" --anno "$PREC" --chiudi
fi
# Mossa 1: l'indice FTS si ricostruisce subito dopo l'harvest, cosi' il
# primo avvocato del mattino non paga il rebuild.
/usr/bin/python3 -c 'import sys; sys.path.insert(0, "/var/www/apps/super-avvocato"); from src.it_precedent_fts import rebuild_indeksi; print("fts:", rebuild_indeksi(), "decisioni indicizzate")'
