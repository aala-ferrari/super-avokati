# -*- coding: utf-8 -*-
"""Riempie `last_amendment_date` PER ARTICOLO nel corpus AL dalle note editoriali dei consolidati QBZ
(«(Ndryshuar … me ligjin nr. 48/2012, datë 26.4.2012)»), senza riscaricare né ri-parsare, e
ricostruisce `bm25.pkl` dal jsonl (fonte). v9.334, roadmap v3 P3b.

    python3 tools/recompute_amendments_al.py            # a secco
    python3 tools/recompute_amendments_al.py --apply    # scrive jsonl (backup) + indice
"""
import json, shutil, sys, time
from collections import Counter
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from src.config import PROCESSED_DATA_PATH  # noqa: E402
from src.retrieval import INDEX_FILE  # noqa: E402
from src.temporal import ultima_modifica  # noqa: E402

JSONL = PROCESSED_DATA_PATH / "all_articles.jsonl"


def main() -> int:
    apply = "--apply" in sys.argv
    lines = JSONL.read_text(encoding="utf-8").splitlines()
    out, per_code, cambiati = [], Counter(), 0
    for ln in lines:
        if not ln.strip():
            continue
        d = json.loads(ln)
        lad = ultima_modifica(SimpleNamespace(heading=d.get("heading", ""), body=d.get("body", "")))
        if lad and lad != (d.get("last_amendment_date") or ""):
            d["last_amendment_date"] = lad
            cambiati += 1
            per_code[d["code"]] += 1
        out.append(json.dumps(d, ensure_ascii=False))
    print(f"articoli con data di modifica dalle note: {cambiati}  →  {dict(per_code.most_common(12))} …")
    if not apply:
        print("(a secco: niente scritto; --apply per applicare)")
        return 0
    bak = JSONL.with_suffix(f".jsonl.bak-{time.strftime('%Y%m%d-%H%M%S')}")
    shutil.copy2(JSONL, bak)
    JSONL.write_text("\n".join(out) + "\n", encoding="utf-8")
    from src.retrieval import ArticleIndex
    if INDEX_FILE.exists():
        shutil.copy2(INDEX_FILE, INDEX_FILE.with_suffix(f".pkl.bak-{time.strftime('%Y%m%d-%H%M%S')}"))
    idx = ArticleIndex.from_jsonl(JSONL, lang="sq")
    idx.save(INDEX_FILE)
    idx2 = ArticleIndex.load(INDEX_FILE)
    con = sum(1 for a in idx2.articles if a.last_amendment_date)
    print(f"scritto {JSONL.name} (backup {bak.name}); indice AL: {len(idx2.articles)} nene, {con} con data di modifica")
    return 0


if __name__ == "__main__":
    sys.exit(main())
