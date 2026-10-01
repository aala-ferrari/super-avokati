#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""v9.463 — riscarica le decisioni italiane TAGLIATE a 60.000 caratteri (Consulta da giurcost.org, giustizia amministrativa da
mdp.*): il tetto degli harvester faceva perdere il DISPOSITIVO delle decisioni lunghe (622 della Corte costituzionale, 24 dei
TAR/CdS/CGARS — fra cui la 129/2024 sul licenziamento disciplinare). Solo stdlib, SULL'HOST, una pagina alla volta.

    rifai_tagliati_it.py report          → quante, nessuna scrittura
    rifai_tagliati_it.py apply [--max N] → riscarica e riscrive il jsonl (backup .bak-<data>-tagliati); un testo nuovo entra solo se
                                           è PIÙ LUNGO del vecchio e ne contiene l'inizio (stessa pagina); poi ricostruire l'FTS
"""
import json
import os
import shutil
import sys
import time
import urllib.request
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ingest_it_giurcost as _cc  # noqa: E402
import ingest_it_ga as _ga  # noqa: E402

OUT = _cc.OUT
SOGLIA = 59_900


def scarica(d: dict) -> str | None:
    url = d.get("url") or ""
    if not url:
        return None
    if d.get("court") == "CCost":
        raw = _cc.fetch(url)
        return _cc.pulisci(raw) if raw else None
    req = urllib.request.Request(url, headers={"User-Agent": _ga.UA, "Referer": _ga.BASE, "From": _ga.FROM_HDR})
    try:
        with urllib.request.urlopen(req, timeout=40) as r:
            return _ga.pulisci(r.read().decode("utf-8", errors="replace"))
    except Exception as exc:  # noqa: BLE001
        print("  ! rete", url, exc, flush=True)
        return None


def main() -> int:
    modo = sys.argv[1] if len(sys.argv) > 1 else "report"
    tetto = int(sys.argv[sys.argv.index("--max") + 1]) if "--max" in sys.argv else 10**9
    righe = open(OUT, encoding="utf-8").read().splitlines()
    tagliati = [i for i, r in enumerate(righe) if len((json.loads(r).get("text") or "")) >= SOGLIA]
    print(f"decisioni {len(righe)} · tagliate a 60.000: {len(tagliati)}", flush=True)
    if modo != "apply":
        return 0
    rifatte = fallite = 0
    for k, i in enumerate(tagliati[:tetto], 1):
        d = json.loads(righe[i])
        nuovo = scarica(d)
        time.sleep(0.7)
        vecchio = d.get("text") or ""
        if not nuovo or len(nuovo) <= len(vecchio) or nuovo[:300] != vecchio[:300]:
            fallite += 1
            print(f"  ✗ {d.get('court')} {d.get('number')}/{d.get('year')}: {len(nuovo or '')} car.", flush=True)
            continue
        d["text"] = nuovo
        righe[i] = json.dumps(d, ensure_ascii=False)
        rifatte += 1
        if k % 50 == 0:
            print(f"  … {k}/{len(tagliati)} (rifatte {rifatte}, fallite {fallite})", flush=True)
    bak = OUT + ".bak-" + datetime.now().strftime("%Y%m%d-%H%M") + "-tagliati"
    shutil.copy2(OUT, bak)
    tmp = OUT + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write("\n".join(righe) + "\n")
    os.replace(tmp, OUT)
    print(f"FATTO: rifatte {rifatte}, fallite {fallite}; backup {bak}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
