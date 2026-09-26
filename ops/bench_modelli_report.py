#!/usr/bin/env python3
"""Riassunto della misura v9.393 (ops/bench_modelli.sh): per variante punteggio medio, secondi, citazioni false, esito del
Giudice e, caso per caso, il punteggio — dai summary.json dello strato 2 sul volume."""
import json, re, sqlite3, sys
from pathlib import Path

L = Path("/var/log/superavokati/bench393")
BASE = Path("/var/www/apps/super-avvocato/data/benchmark/layer2")
ORD = ["S0", "S1", "S2", "S3", "S4", "S5", "D0", "D1", "D2", "D3", "D4", "D5"]
DESC = {"S0": "oggi: inizio Sonnet 5, senior Opus 5 max", "S1": "senior Opus 5.5 high", "S2": "senior Opus 5.5 max",
        "S3": "inizio Opus 5.5 medium (senior di oggi)", "S4": "inizio Opus 5.5 medium + senior Opus 5.5 high",
        "D0": "oggi: senior Opus 5 max, diavolo Fable high, Giudice Fable max", "D1": "Giudice Opus 5.5 max",
        "D2": "senior Opus 5.5 high + Giudice Opus 5.5 max", "D3": "tutto Opus 5.5 (inizio/junior medium, senior high, Giudice max)",
        "D4": "oggi + inizio/junior Opus 5.5 medium (senior Opus 5 max, Giudice Fable max)",
        "S5": "inizio Opus 5.5 HIGH (senior di oggi)", "D5": "oggi + inizio/junior Opus 5.5 HIGH (senior Opus 5 max, Giudice Fable max)"}
res = {}
for v in ORD:
    f = L / f"{v}.log"
    if not f.exists():
        continue
    m = re.search(r"strato 2: (\{.*\})\s+→\s+(\S+)", f.read_text(encoding="utf-8", errors="replace"))
    if not m:
        res[v] = None
        continue
    out = Path(m.group(2).replace("/app/data", "/var/www/apps/super-avvocato/data"))
    try:
        res[v] = json.loads((out / "summary.json").read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        res[v] = None
print("variante | descrizione | n | punteggio medio | secondi medi | citazioni false | errori | Giudice (verdetto/tot)")
for v in ORD:
    r = res.get(v)
    if not r:
        print(f"{v} | {DESC[v]} | (non finita)")
        continue
    rs = [x for x in r["results"] if "score" in x]
    fake = sum(x.get("fake", 0) for x in rs)
    gj = sum(1 for x in rs if x.get("giudice") == "verdetto")
    print(f"{v} | {DESC[v]} | {len(rs)} | {r['agg']['mean_score']:.3f} | {r['agg']['mean_secs']} | {fake} | {r['agg']['errors']} | {gj}/{len(rs)}")
print()
for grp in (["S0", "S1", "S2", "S3", "S4", "S5"], ["D0", "D1", "D2", "D3", "D4", "D5"]):
    ids = sorted({x["id"] for v in grp if res.get(v) for x in res[v]["results"]})
    print("caso | " + " | ".join(grp))
    for cid in ids:
        cells = []
        for v in grp:
            x = next((y for y in (res.get(v) or {}).get("results", []) if y["id"] == cid), None)
            cells.append("—" if not x else ("ERR" if "error" in x else f"{x['score']:.2f} ({x['secs']}s, norme {x['must_cite']}, punti {x['key_points']}"
                                                                   + (f", fake {x['fake']}" if x.get("fake") else "") + ")"))
        print(f"{cid} | " + " | ".join(cells))
    print()
try:
    c = sqlite3.connect("/var/www/apps/super-avvocato/data/app.db")
    lim = c.execute("SELECT model, COUNT(*) FROM ai_audit_log WHERE error_class='ModelLimit' AND timestamp > ? GROUP BY model",
                    (sys.argv[1] if len(sys.argv) > 1 else "2026-09-25T21:00:00Z",)).fetchall()
    print("limiti della sottoscrizione durante la misura:", lim or "nessuno")
except Exception as e:  # noqa: BLE001
    print("audit non letto:", e)
