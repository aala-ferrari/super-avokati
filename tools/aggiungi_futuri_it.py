# -*- coding: utf-8 -*-
"""v9.405 — gli articoli NUOVI che entrano in vigore più avanti (sull'HOST, come l'ingest; backup dei JSON).

`versioni_future_it.py report` elenca per ogni atto gli articoli che esistono SOLO nella versione futura (29 set 2026: art.
437-bis c.p., art. 359-ter c.p.p., art. 25-vicies d.lgs. 231/2001, dal 30 settembre 2026). Qui si scaricano e si mettono nel JSON
con `non_in_vigore_dal` = la loro data: il build li tiene nel corpus, il verificatore e il blocco degli articoli dicono «non ancora
in vigore» fino a quella data, e dalla notte in cui la data arriva il cron (`ops/it_vigenze_cron.py`) ricostruisce l'indice e
diventano articoli come gli altri. Il numero viene dall'ETICHETTA del link e dal gruppo (come riallinea_vigenti_it.py).

    python3 tools/aggiungi_futuri_it.py apply [--only id1,id2] [--dry]
"""
import json
import os
import re
import shutil
import sys
import time
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import normattiva_lib as nl  # noqa: E402
from riallinea_vigenti_it import _key, _num_lab, _numero_nel_json, _vigenza  # noqa: E402

SRC = Path(os.environ.get("IT_ACTS_DIR", "/var/www/apps/super-avvocato/data/processed/it_acts"))
VF = Path(os.environ.get("IT_VF_OUT", "/var/www/apps/super-avvocato/data/processed/it_versioni_future.json"))


def _posizione(arts, numero: str) -> int:
    """Dopo l'ultimo articolo con lo stesso numero di base e un ordine minore (437 → dopo «437»; 359-ter → dopo «359-bis»)."""
    base = re.match(r"^\d+", numero).group(0) if re.match(r"^\d+", numero) else None
    sk = nl.sortkey(numero)
    best = None
    for i, a in enumerate(arts):
        n = str(a.get("number") or "")
        if base and re.match(r"^\d+", n) and re.match(r"^\d+", n).group(0) == base and nl.sortkey(n) < sk:
            best = i
    if best is None:
        for i, a in enumerate(arts):
            n = str(a.get("number") or "")
            if re.match(r"^\d+", n) and nl.sortkey(n) < sk:
                best = i
    return (best + 1) if best is not None else len(arts)


def main():
    args = sys.argv[1:]
    dry = "--dry" in args
    only = set(args[args.index("--only") + 1].split(",")) if "--only" in args else None
    vf = json.loads(VF.read_text(encoding="utf-8"))
    oggi = date.today().isoformat()
    nm = nl.Normattiva(delay=0.6)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    for cid, info in sorted((vf.get("atti") or {}).items()):
        if (only and cid not in only) or not info.get("solo_futuro"):
            continue
        f = SRC / f"{cid}.json"
        j = json.loads(f.read_text(encoding="utf-8"))
        arts = j.get("articles") or []
        try:
            fut_links = nm.article_links_all(nm.open_act(j["urn"]))
            cur_keys = {_key(h) for h, _l, _g in nm.article_links_all(nm.open_act(j["urn"] + "!vig=" + oggi))}
        except Exception as exc:  # noqa: BLE001
            print(f"  ! {cid}: {exc}", flush=True)
            continue
        sizes, etich = {}, {}
        for h, l, g in fut_links:
            sizes[g] = sizes.get(g, 0) + 1
            etich.setdefault(g, []).append(l)
        aggiunti = 0
        for h, lab, g in fut_links:
            if _key(h) in cur_keys:
                continue
            target = _numero_nel_json(_num_lab(lab), g, sizes, etich)
            if not target or any(str(a.get("number")).lower() == target for a in arts):
                continue
            p = nm.fetch_article(h)
            a = nl.parse_article_page(p, fallback_number=lab) or {}
            dal, _al = _vigenza(p)
            if not a.get("body") or not dal or dal <= oggi:
                print(f"    ? {cid} {lab}: pagina senza testo o senza data futura ({dal}) — saltato", flush=True)
                continue
            nuovo = {"number": target, "heading": a.get("heading") or "", "body": a.get("body") or "",
                     "repealed": nl.is_repealed(a.get("heading"), a.get("body")), "non_in_vigore_dal": dal,
                     "aggiunto": oggi}
            if a.get("notes"):
                nuovo["notes"] = a["notes"]
            arts.insert(_posizione(arts, target), nuovo)
            aggiunti += 1
            print(f"  {cid:26s} + art. {target} «{nuovo['heading'][:60]}» {len(nuovo['body'])} chr · in vigore dal {dal}",
                  flush=True)
        if aggiunti and not dry:
            shutil.copy2(f, f.with_name(f.name + f".bak-{stamp}-futuri"))
            j["articles"] = arts
            f.write_text(json.dumps(j, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
