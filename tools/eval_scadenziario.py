"""v9.431 — MISURA dello scadenziario su documenti con le risposte scritte prima (`tools/golden_cases/scadenziario/*.json`):
il modello estrae, il codice verifica (come in produzione: `estrai_tutto` + `proposte_da_estrazione`), e si conta

  · date attese trovate (e l'ora giusta, quando c'è) — una mancata è una scadenza persa;
  · termini attesi («entro 40 giorni») riconosciuti con la loro durata;
  · eventi che fanno partire termini di legge (sentenza, decreto) con la data GIUSTA (la notifica, non la pronuncia);
  · date VIETATE (l'errore noto: l'appello calcolato dalla data della sentenza);
  · proposte con una data che NEL DOCUMENTO NON C'È (inventata) e quante escono «verificate».

Nessun database, nessun avviso. `--modello opus` rifà la stessa misura col modello del senior (per decidere SUI NUMERI se cambiare).

    docker run --rm --env-file … -v <copia credenziali>:/home/avvocato/.claude super-avvocato:vX python3 tools/eval_scadenziario.py [--modello opus] [--solo id,id]
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src import scadenziario as scad  # noqa: E402
from src.backends import build_backend  # noqa: E402


class _Forza:
    """Il backend con il tier scelto: le chiamate `medium=True` dello scadenziario vanno al senior (Opus, sforzo dell'env)."""

    def __init__(self, be, senior: bool):
        self.be, self.senior = be, senior

    def complete(self, *a, **kw):
        if self.senior:
            kw["medium"] = False
        return self.be.complete(*a, **kw)


def valuta(caso: dict, backend) -> dict:
    from src import brain
    brain.set_request_jurisdiction(caso["jurisdiction"])      # come in produzione: la lingua è quella del fascicolo
    t0 = time.time()
    est = scad.estrai_tutto(backend, caso["testo"], caso["id"], caso["lang"], caso["oggi"])
    proposte, inneschi = scad.proposte_da_estrazione(est, caso["testo"], lang=caso["lang"], jurisdiction=caso["jurisdiction"],
                                                     oggi=caso["oggi"])
    date = [p for p in proposte if p.get("data")]
    trovate = 0
    for a in caso.get("attese") or []:
        if any(p["data"] == a["data"] and (not a.get("ora") or p.get("ora") == a["ora"]) for p in date):
            trovate += 1
    termini = 0
    for t in caso.get("termini_attesi") or []:
        for p in proposte:
            try:
                r = json.loads(p.get("regola_json") or "{}")
            except ValueError:
                r = {}
            if int(r.get("durata") or -1) == t["durata"] and scad._UNITA.get(t["unita"]) == r.get("unita") \
                    and (t.get("data") is None or p.get("data") == t["data"]):
                termini += 1
                break
    inn_ok = 0
    for i in caso.get("inneschi_attesi") or []:
        if any(x.get("trigger") == i["trigger"] and (x.get("data") or "") == i["data"] for x in inneschi):
            inn_ok += 1
    vietate = [p["data"] for p in date if p["data"] in (caso.get("vietate") or [])]
    if caso.get("max_proposte") is not None and len(proposte) > caso["max_proposte"]:
        vietate += [f"{len(proposte)} proposte (max {caso['max_proposte']})"]
    inventate = [p["data"] for p in date if p.get("tipo") == "data" and not p.get("regola_json")
                 and not scad.data_nel_testo(p["data"], caso["testo"])]
    return {"id": caso["id"], "secondi": round(time.time() - t0, 1),
            "date": f"{trovate}/{len(caso.get('attese') or [])}",
            "termini": f"{termini}/{len(caso.get('termini_attesi') or [])}",
            "inneschi": f"{inn_ok}/{len(caso.get('inneschi_attesi') or [])}",
            "vietate": vietate, "inventate": inventate,
            "proposte": len(proposte), "verificate": sum(1 for p in proposte if p.get("verificato")),
            "_punti": (trovate, len(caso.get("attese") or []), termini, len(caso.get("termini_attesi") or []),
                       inn_ok, len(caso.get("inneschi_attesi") or []), len(vietate), len(inventate)),
            "dettaglio": [(p.get("tipo"), p.get("data"), p.get("ora"), p.get("titolo", "")[:60], bool(p.get("verificato")))
                          for p in proposte] + [("innesco", x.get("trigger"), x.get("data")) for x in inneschi]}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--modello", choices=["medio", "opus"], default="medio")
    ap.add_argument("--solo", default="")
    ap.add_argument("--dettaglio", action="store_true")
    a = ap.parse_args()
    cartella = os.path.join(os.path.dirname(os.path.abspath(__file__)), "golden_cases", "scadenziario")
    casi = [json.load(open(f, encoding="utf-8")) for f in sorted(glob.glob(os.path.join(cartella, "*.json")))]
    if a.solo:
        casi = [c for c in casi if c["id"] in a.solo.split(",")]
    be = _Forza(build_backend(), a.modello == "opus")
    tot = [0] * 8
    for c in casi:
        try:
            r = valuta(c, be)
        except Exception as exc:  # noqa: BLE001
            print(f"✗ {c['id']}: {type(exc).__name__}: {exc}")
            continue
        tot = [x + y for x, y in zip(tot, r["_punti"])]
        print(f"{'✓' if not r['vietate'] and not r['inventate'] and r['_punti'][0] == r['_punti'][1] else '·'} {r['id']:<24} "
              f"date {r['date']}  termini {r['termini']}  inneschi {r['inneschi']}  vietate {r['vietate'] or '-'}  "
              f"inventate {r['inventate'] or '-'}  proposte {r['proposte']} (verificate {r['verificate']})  {r['secondi']} s")
        if a.dettaglio:
            for d in r["dettaglio"]:
                print("      ", d)
    print(f"\nTOTALE ({a.modello}): date {tot[0]}/{tot[1]} · termini {tot[2]}/{tot[3]} · inneschi {tot[4]}/{tot[5]} · "
          f"vietate {tot[6]} · inventate {tot[7]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
