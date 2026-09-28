#!/usr/bin/env python3
"""v9.399 — toglie dal corpus AL i FALSI titoli di capitolo: «KREU XIV — Neni 140» (122 articoli del Codice del lavoro:
nel consolidato QBZ i titoli dei capitoli mancano e una lettura vecchia del parser prendeva la riga «Neni N» come titolo)
e «KREU XVII — (Ndryshuar titulli me ligjin …)» (una nota presa per titolo). Il capitolo resta, senza titolo inventato:
nulla entra nel corpus che non venga dalla fonte.

    python3 tools/repair_kreu_titolo_falso.py            # rapporto, nulla scritto
    python3 tools/repair_kreu_titolo_falso.py --apply    # backup del jsonl + scrittura + pickle ricostruito
"""
import json, re, shutil, sys, time, collections
sys.path.insert(0, "/app")
from src.config import PROCESSED_DATA_PATH

JSONL = PROCESSED_DATA_PATH / "all_articles.jsonl"
_FALSO = re.compile(r"^((?:PJESA|KREU|KAPITULLI|TITULLI|SEKSIONI|NËNSEKSIONI)\s+[IVXLCDM\d]+[A-Z]?)\s+—\s+"
                    r"(?:Neni\s+\d+\S*|\(\s*(?:Ndryshuar|Shtuar|Hequr)\b[^)]*\)?)\s*$", re.I)


def main() -> int:
    rows = [json.loads(l) for l in JSONL.open(encoding="utf-8") if l.strip()]
    cambi, esempi = collections.Counter(), {}
    for r in rows:
        for k in ("pjesa", "kreu", "seksioni"):
            v = r.get(k) or ""
            m = _FALSO.match(v)
            if m:
                esempi.setdefault((r.get("code"), v), m.group(1))
                r[k] = m.group(1)
                cambi[r.get("code")] += 1
    for (c, v), n in sorted(esempi.items()):
        print(f"{c:28s} {v[:80]!r} → {n!r}")
    print("campi corretti:", sum(cambi.values()), dict(cambi))
    if "--apply" not in sys.argv or not cambi:
        return 0
    stamp = time.strftime("%Y%m%d%H%M")
    bak = JSONL.with_suffix(f".jsonl.bak-kreufalso-{stamp}")
    shutil.copy2(JSONL, bak)
    with JSONL.open("w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    from src.retrieval import ArticleIndex, INDEX_FILE
    shutil.copy2(INDEX_FILE, INDEX_FILE.with_suffix(f".pkl.bak-kreufalso-{stamp}"))
    ix = ArticleIndex.from_jsonl(JSONL)
    ix.save(INDEX_FILE)
    print("scritto", JSONL, "backup", bak, "· pickle", INDEX_FILE, len(ix.articles), "articoli, fold", getattr(ix, "fold", None))
    return 0


if __name__ == "__main__":
    sys.exit(main())
