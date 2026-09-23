#!/bin/bash
# v9.376 — TAR/CdS/CGARS di ogni notte (03:45) + ricostruzione dell'indice FTS SUBITO DOPO, nel container.
# Prima il cron lanciava solo l'harvester: l'archivio cambiava e la prima domanda italiana del giorno pagava la
# ricostruzione (56 s misurati il 23 set) dentro la sua ricerca.
set -uo pipefail
/usr/bin/python3 /var/www/apps/super-avvocato/tools/ingest_it_ga.py --tutte-sedi --pagine 2
docker exec super-avvocato python3 -c 'from src.it_precedent_fts import rebuild_indeksi; print("fts:", rebuild_indeksi(), "decisioni indicizzate")'
