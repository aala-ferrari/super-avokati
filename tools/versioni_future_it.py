# -*- coding: utf-8 -*-
"""v9.405 — VERSIONI FUTURE nel corpus italiano. Normattiva, aperta SENZA data, mostra per ogni articolo l'ULTIMA versione
pubblicata, anche se entra in vigore più avanti (i testi unici fiscali: «ARTICOLO ABROGATO» dal 1° gennaio 2027; con
«!vig=» di oggi l'art. 8 d.lgs. 74/2000 ha il testo «in vigore dal 27-10-2019 al 31-12-2026»). L'ingest usava la pagina senza
data. Qui, per ogni atto Normattiva del corpus, si apre la pagina due volte (senza data e con la data di oggi) e si
confronta `art.versione` di ogni link-articolo: gli articoli con una versione diversa hanno un testo FUTURO nel corpus.

    python3 tools/versioni_future_it.py report [--only id1,id2]      # sull'HOST (come l'ingest), 2 richieste per atto
    → data/processed/it_versioni_future.json  {code: [{"label","group","v_oggi","v_futura","href_oggi"}...]}
"""
import json
import os
import re
import sys
import time
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import normattiva_lib as nl  # noqa: E402

SRC = Path(os.environ.get("IT_ACTS_DIR", "/var/www/apps/super-avvocato/data/processed/it_acts"))
OUT = Path(os.environ.get("IT_VF_OUT", "/var/www/apps/super-avvocato/data/processed/it_versioni_future.json"))
_URN_OK = re.compile(r"^(decreto\.legislativo|decreto\.presidente\.repubblica|decreto\.legge|legge|regio\.decreto|"
                     r"costituzione|decreto\.legislativo\.luogotenenziale|decreto\.ministeriale|legge\.costituzionale)[:;]")


def _versioni(links):
    out = {}
    for href, label, flag in links:
        m = re.search(r"art\.versione=(\d+)", href)
        mid = re.search(r"art\.idArticolo=(\d+)", href)
        ms = re.search(r"art\.idSottoArticolo=(\d+)", href)
        ms1 = re.search(r"art\.idSottoArticolo1=(\d+)", href)
        key = (flag, mid.group(1) if mid else label, ms.group(1) if ms else "", ms1.group(1) if ms1 else "")
        out[key] = (int(m.group(1)) if m else 0, label, href)
    return out


def main():
    args = sys.argv[1:]
    only = None
    if "--only" in args:
        only = set(args[args.index("--only") + 1].split(","))
    oggi = date.today().isoformat()
    nm = nl.Normattiva(delay=0.6)
    risultato, tot = {}, 0
    files = sorted(SRC.glob("*.json"))
    for f in files:
        cid = f.stem
        if only and cid not in only:
            continue
        try:
            j = json.loads(f.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            continue
        urn = (j.get("urn") or "").strip()
        if not _URN_OK.match(urn):
            continue
        try:
            v_def = _versioni(nm.article_links_all(nm.open_act(urn)))
            v_oggi = _versioni(nm.article_links_all(nm.open_act(urn + "!vig=" + oggi)))
        except Exception as exc:  # noqa: BLE001
            print(f"  ! {cid}: {type(exc).__name__} {str(exc)[:80]}", flush=True)
            continue
        diff = []
        for k, (vo, label, href) in v_oggi.items():
            d = v_def.get(k)
            if d and d[0] != vo:
                diff.append({"label": label, "group": k[0], "v_oggi": vo, "v_futura": d[0], "href_oggi": href})
        solo_futuro = [v_def[k][1] for k in v_def if k not in v_oggi]      # articoli che esistono solo nella versione futura
        if diff or solo_futuro:
            risultato[cid] = {"diversi": diff, "solo_futuro": solo_futuro}
            tot += len(diff)
        print(f"  {cid:34s} articoli {len(v_oggi):5d} · versione futura diversa {len(diff):4d} · solo nel futuro {len(solo_futuro):3d}",
              flush=True)
    OUT.write_text(json.dumps({"data": oggi, "atti": risultato}, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\nTOTALE articoli con una versione futura diversa: {tot} in {len(risultato)} atti → {OUT}")


if __name__ == "__main__":
    main()
