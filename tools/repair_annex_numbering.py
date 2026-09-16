# -*- coding: utf-8 -*-
"""Ripara gli atti «approvati con allegato» già scaricati SENZA riscaricarli (16 set 2026).

Normattiva distingue i gruppi con `art.flagTipoArticolo` (0 = atto di approvazione,
1 = allegato, 2 = altro allegato). La vecchia dedup buttava via gli allegati con gli
stessi numeri: il c.c. era senza artt. 1-31 (al loro posto decreto e preleggi), il DNC
senza 1-10, ogni testo unico senza l'art. 1. Qui, per ogni atto: si riapre la pagina, si
prendono TUTTI i link con il gruppo, si riscaricano solo gli articoli i cui id compaiono
in più gruppi, e si riassegnano i numeri con normattiva_lib.assign_numbers (principale =
gruppo più grande; gruppo 0 → «N-legge»; altro gruppo numerato → «N-allK»). Per il
codice civile il gruppo 1 (31 articoli «-all1») diventa il corpus a sé `preleggi`.

    IT_ACTS_DIR=/var/www/apps/super-avvocato/data/processed/it_acts \\
        python3 /tmp/repair_annex_numbering.py codice_civile tuel …   # sull'host
"""
import json, os, re, sys, time
from pathlib import Path

sys.path.insert(0, "/tmp")
from normattiva_lib import Normattiva, parse_article_page, assign_numbers, sortkey  # noqa: E402
from ingest_it_normattiva import ACTS  # noqa: E402

OUT = Path(os.environ.get("IT_ACTS_DIR", "/app/data/processed/it_acts"))
URN = {a[0]: a[3] for a in ACTS}
PRELEGGI_TITLE = "Disposizioni sulla legge in generale — preleggi al codice civile (R.D. 262/1942)"


def _ida(href: str) -> tuple[str, str]:
    m = re.search(r"art\.idArticolo=(\d+)", href)
    ms = re.search(r"art\.idSottoArticolo=(\d+)", href)
    return (m.group(1) if m else href, ms.group(1) if ms else "")


def repair(cid: str, delay: float = 0.45) -> None:
    dest = OUT / f"{cid}.json"
    if not dest.exists():
        print(f"  ! {cid}: manca il json"); return
    d = json.loads(dest.read_text(encoding="utf-8"))
    old = d["articles"]
    nm = Normattiva(delay=delay)
    links = nm.article_links_all(nm.open_act(URN[cid]))
    sizes, ids = {}, {}
    for href, label, flag in links:
        sizes[flag] = sizes.get(flag, 0) + 1
        ids.setdefault(_ida(href), set()).add(flag)
    collide = {k for k, fl in ids.items() if len(fl) > 1}
    if not collide:
        print(f"  = {cid}: gruppi {sizes} — nessuna collisione, nulla da fare"); return
    refetch = [(h, l, f) for h, l, f in links if _ida(h) in collide]
    t0 = time.time()
    fetched, fails = [], 0
    for href, label, flag in refetch:
        try:
            a = parse_article_page(nm.fetch_article(href), fallback_number=label)
            if a:
                a["group"] = flag
                fetched.append(a)
        except Exception as exc:  # noqa: BLE001
            fails += 1
            print(f"    ✗ {label}: {type(exc).__name__}: {str(exc)[:60]}")
    new = assign_numbers(fetched, sizes=sizes)
    touched = {a["number"] for a in fetched}                       # numeri ambigui (prima della politica)
    kept = [a for a in old if a["number"] not in touched
            and not re.search(r"-(legge|all\d+)$", a["number"])]  # via anche i residui del giro precedente
    merged = sorted(kept + new, key=lambda a: sortkey(a["number"]))
    prel = [a for a in merged if a["number"].endswith("-all1")] if cid == "codice_civile" else []
    if prel:
        merged = [a for a in merged if not a["number"].endswith("-all1")]
        pd = {"id": "preleggi", "title": PRELEGGI_TITLE, "area": "Civile", "urn": URN[cid], "wave": "wave1",
              "source": "normattiva-allegato-1",
              "articles": [dict(a, number=a["number"][:-5]) for a in prel], "failures": []}
        (OUT / "preleggi.json").write_text(json.dumps(pd, ensure_ascii=False), encoding="utf-8")
    d["articles"] = merged
    dest.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
    a1 = next((a for a in merged if a["number"] == "1"), None)
    print(f"  ✓ {cid}: gruppi {sizes}, collisioni {len(collide)}, riscaricati {len(fetched)} (falliti {fails}), "
          f"articoli {len(old)}→{len(merged)}" + (f", preleggi {len(prel)}" if prel else "") +
          f", {time.time() - t0:.0f}s | art.1: {(a1['heading'] or a1['body'][:50]) if a1 else '-'!r}")


if __name__ == "__main__":
    for cid in sys.argv[1:]:
        repair(cid)
