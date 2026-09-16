# -*- coding: utf-8 -*-
"""Promuove il RI-INGEST Normattiva (con le note di aggiornamento per articolo) dalla cartella di
prova a quella vera, atto per atto, SOLO se non perde articoli (roadmap v3 P3b-IT, 16 set 2026).

Il ri-download gira sull'host in una cartella a parte:
    IT_ACTS_DIR=…/data/processed/it_acts_refresh python3 tools/ingest_it_normattiva.py
(resume-safe: gli atti già presenti nella cartella nuova si saltano). Poi:
    python3 tools/promote_it_refresh.py            # a secco: cosa verrebbe promosso
    python3 tools/promote_it_refresh.py --apply    # copia (backup .bak-DATA dell'atto vecchio)
Regola: si promuove se il nuovo ha ≥ articoli del vecchio − 1, nessun fallimento in più, e almeno
un articolo con `notes`. Poi `build_it_index.py` nel container ricostruisce l'indice.
"""
import json, shutil, sys, time
from pathlib import Path

BASE = Path(sys.argv[sys.argv.index("--dir") + 1]) if "--dir" in sys.argv else Path("/var/www/apps/super-avvocato/data/processed")
OLD, NEW = BASE / "it_acts", BASE / "it_acts_refresh"


def main() -> int:
    apply = "--apply" in sys.argv
    ok, ko = [], []
    for f in sorted(NEW.glob("*.json")):
        try:
            n = json.loads(f.read_text(encoding="utf-8"))
        except Exception as e:  # noqa: BLE001
            ko.append((f.stem, f"illeggibile: {e}")); continue
        o_path = OLD / f.name
        o = json.loads(o_path.read_text(encoding="utf-8")) if o_path.exists() else {"articles": [], "failures": []}
        n_art, o_art = len(n.get("articles") or []), len(o.get("articles") or [])
        n_fail, o_fail = len(n.get("failures") or []), len(o.get("failures") or [])
        with_notes = sum(1 for a in n.get("articles") or [] if a.get("notes"))
        if n_art < o_art - 1:
            ko.append((f.stem, f"perde articoli: {o_art} → {n_art}")); continue
        if n_fail > o_fail:
            ko.append((f.stem, f"più fallimenti: {o_fail} → {n_fail}")); continue
        if with_notes == 0 and o_art > 0:
            ko.append((f.stem, "nessuna nota letta (parser?)")); continue
        ok.append((f.stem, o_art, n_art, with_notes))
    for s, oa, na, wn in ok:
        print(f"  ✓ {s:34s} {oa:5d} → {na:5d} art, {wn:4d} con note")
    for s, why in ko:
        print(f"  ✗ {s:34s} {why}")
    print(f"promuovibili: {len(ok)}, bloccati: {len(ko)}")
    if not apply:
        return 0
    stamp = time.strftime("%Y%m%d-%H%M%S")
    for s, *_r in ok:
        src, dst = NEW / f"{s}.json", OLD / f"{s}.json"
        if dst.exists():
            shutil.copy2(dst, dst.with_suffix(f".json.bak-{stamp}"))
        shutil.copy2(src, dst)
    print(f"promossi {len(ok)} atti (backup .bak-{stamp}); ora: build_it_index.py nel container")
    return 0


if __name__ == "__main__":
    sys.exit(main())
