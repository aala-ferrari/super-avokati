# -*- coding: utf-8 -*-
"""Ricalcola il flag `repealed` di tutti gli atti Normattiva già scaricati con la regola
stretta di normattiva_lib.is_repealed (16 set 2026) — senza riscaricare nulla.

Prima la parola «abrogato» nei primi 400 caratteri bastava: art. 15 preleggi, gli articoli
«Abrogazioni» dei testi unici e TUEL 274 risultavano abrogati e la ricerca li saltava.
Stampa per atto quanti flag cambiano (vero→falso, falso→vero) e un esempio.

    IT_ACTS_DIR=/var/www/apps/super-avvocato/data/processed/it_acts python3 /tmp/recompute_repealed.py
"""
import json, os, sys
from pathlib import Path

sys.path.insert(0, "/tmp")
from normattiva_lib import is_repealed  # noqa: E402

D = Path(os.environ.get("IT_ACTS_DIR", "/app/data/processed/it_acts"))
SKIP_SOURCES = ("html-consolidato", "pdf-consolidato", "html-originale", "pdf-coe-colonne")  # EUR-Lex/CEDU: regola propria
tot_tf = tot_ft = 0
for f in sorted(D.glob("*.json")):
    d = json.loads(f.read_text(encoding="utf-8"))
    if d.get("source") in SKIP_SOURCES:
        continue
    tf = ft = 0
    ex = ""
    for a in d.get("articles") or []:
        old = bool(a.get("repealed"))
        new = is_repealed(a.get("heading") or "", a.get("body") or "")
        if old != new:
            a["repealed"] = new
            if old and not new:
                tf += 1
                ex = ex or f"art. {a['number']} «{(a.get('heading') or a.get('body') or '')[:40]}»"
            else:
                ft += 1
    if tf or ft:
        f.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
        print(f"  {f.stem:30s} abrogati→vivi {tf:>3}  vivi→abrogati {ft:>2}   es. {ex}")
    tot_tf += tf; tot_ft += ft
print(f"\ntotale: {tot_tf} articoli tornati vivi, {tot_ft} marcati abrogati")
