#!/usr/bin/env python3
"""v9.373 — ripara i TITOLI DI CAPITOLO troncati nel corpus AL (kreu/seksioni/pjesa), senza riscaricare nulla.

Il parser prendeva solo la PRIMA riga del titolo («KREU X — KËQYRJA E PERSONAVE, SENDEVE DHE»); ora
`parser._titolo_con_intestazione` continua sulle righe in maiuscolo. Qui si rilegge ogni testo in
`data/processed/al_text_cache/<code>.txt`, si calcola per ogni intestazione il titolo vecchio e quello nuovo, e si
sostituisce nel jsonl SOLO dove il vecchio porta a UN solo nuovo (mai a caso) e il nuovo comincia col vecchio.

    python3 tools/repair_kreu.py            # rapporto, nulla scritto
    python3 tools/repair_kreu.py --apply    # backup del jsonl + scrittura + pickle ricostruito
"""
import json, shutil, sys, time, collections
sys.path.insert(0, "/app")
from pathlib import Path
from src import parser as P
from src.config import PROCESSED_DATA_PATH, INDEX_PATH

JSONL = PROCESSED_DATA_PATH / "all_articles.jsonl"
CACHE = PROCESSED_DATA_PATH / "al_text_cache"


def _vecchio(line: str, tail: str) -> str:
    nl = next((ln.strip() for ln in tail[:200].splitlines() if ln.strip()), "")
    return f"{line} — {nl}" if nl and not P.HIERARCHY_RE.match(nl) else line


def mappa(code: str) -> dict:
    f = CACHE / f"{code}.txt"
    if not f.exists():
        return {}
    text = f.read_text(encoding="utf-8")
    m = collections.defaultdict(set)
    for mt in P.HIERARCHY_RE.finditer(text):
        line = mt.group(0).strip()
        tail = text[mt.end(): mt.end() + 500]
        old, new = _vecchio(line, tail), P._titolo_con_intestazione(line, tail)
        m[old].add(new)
    return {o: next(iter(n)) for o, n in m.items() if len(n) == 1 and next(iter(n)) != o and next(iter(n)).startswith(o)}


def main() -> int:
    rows = [json.loads(l) for l in JSONL.open(encoding="utf-8") if l.strip()]
    maps, cambi = {}, collections.Counter()
    for r in rows:
        code = r.get("code")
        if code not in maps:
            maps[code] = mappa(code)
        for k in ("kreu", "seksioni", "pjesa"):
            v = r.get(k) or ""
            if v in maps[code]:
                r[k] = maps[code][v]; cambi[code] += 1
    for code, mp in maps.items():
        for o, n in mp.items():
            print(f"{code:28s} {o[:70]!r}\n{'':28s} → {n[:150]!r}")
    print("articoli toccati:", sum(cambi.values()), dict(cambi))
    if "--apply" not in sys.argv:
        return 0
    bak = JSONL.with_suffix(f".jsonl.bak-kreu-{time.strftime('%Y%m%d%H%M')}")
    shutil.copy2(JSONL, bak)
    with JSONL.open("w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    from src.retrieval import ArticleIndex, INDEX_FILE
    shutil.copy2(INDEX_FILE, INDEX_FILE.with_suffix(f".pkl.bak-kreu-{time.strftime('%Y%m%d%H%M')}"))
    ix = ArticleIndex.from_jsonl(JSONL)
    ix.save(INDEX_FILE)
    print("scritto", JSONL, "backup", bak, "· pickle", INDEX_FILE, len(ix.articles), "articoli, fold", getattr(ix, "fold", None))
    return 0


if __name__ == "__main__":
    sys.exit(main())
