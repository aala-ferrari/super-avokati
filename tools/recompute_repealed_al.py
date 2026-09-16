# -*- coding: utf-8 -*-
"""Ricalcola il flag `repealed` sul corpus AL (`data/processed/all_articles.jsonl`) con la regola
`parser.is_repealed_stub` (16 set 2026), SENZA riscaricare né ri-parsare. Le leggi SUPERATE per
intero (ligji_te_dhenat 9887/2008, ligji_policia 108/2014, ligji_dhuna_familje 9669/2006) restano
tutte abrogate. Poi ricostruisce `bm25.pkl` dal jsonl (fonte).

    python3 tools/recompute_repealed_al.py            # a secco: cosa cambierebbe
    python3 tools/recompute_repealed_al.py --apply    # scrive jsonl (backup) + ricostruisce l'indice
"""
import json, shutil, sys, time
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from src.config import PROCESSED_DATA_PATH  # noqa: E402
from src.parser import is_repealed_stub  # noqa: E402
from src.retrieval import INDEX_FILE  # noqa: E402

JSONL = PROCESSED_DATA_PATH / "all_articles.jsonl"
WHOLE_LAW_REPEALED = {"ligji_te_dhenat", "ligji_policia", "ligji_dhuna_familje"}


def main() -> int:
    apply = "--apply" in sys.argv
    lines = JSONL.read_text(encoding="utf-8").splitlines()
    out, to_live, to_dead = [], Counter(), Counter()
    ex_live, ex_dead = [], []
    for ln in lines:
        if not ln.strip():
            continue
        d = json.loads(ln)
        old = bool(d.get("repealed"))
        if d["code"] in WHOLE_LAW_REPEALED:
            new = True
        else:
            new = is_repealed_stub(d.get("heading", ""), d.get("body", ""))
        if new != old:
            (to_live if old else to_dead)[d["code"]] += 1
            (ex_live if old else ex_dead).append((d["code"], d["number"], (d.get("heading", "") + " | " + d.get("body", ""))[:110].replace("\n", " ")))
            d["repealed"] = new
        out.append(json.dumps(d, ensure_ascii=False))
    print(f"tornano VIVI: {sum(to_live.values())}  →  {dict(to_live)}")
    for c, n, t in ex_live[:60]:
        print(f"   ↑ {c:28s} {n:>6}  {t}")
    print(f"diventano ABROGATI: {sum(to_dead.values())}  →  {dict(to_dead)}")
    for c, n, t in ex_dead[:40]:
        print(f"   ↓ {c:28s} {n:>6}  {t}")
    if not apply:
        print("(a secco: niente scritto; --apply per applicare)")
        return 0
    if not to_live and not to_dead:
        print("niente da cambiare"); return 0
    bak = JSONL.with_suffix(f".jsonl.bak-{time.strftime('%Y%m%d-%H%M%S')}")
    shutil.copy2(JSONL, bak)
    JSONL.write_text("\n".join(out) + "\n", encoding="utf-8")
    from src.retrieval import ArticleIndex
    if INDEX_FILE.exists():
        ibak = INDEX_FILE.with_suffix(f".pkl.bak-{time.strftime('%Y%m%d-%H%M%S')}")
        shutil.copy2(INDEX_FILE, ibak)
    idx = ArticleIndex.from_jsonl(JSONL, lang="sq")
    idx.save(INDEX_FILE)
    idx2 = ArticleIndex.load(INDEX_FILE)
    rep = sum(1 for a in idx2.articles if a.repealed)
    print(f"scritto {JSONL.name} (backup {bak.name}); indice AL: {len(idx2.articles)} nene, {rep} abrogati")
    return 0


if __name__ == "__main__":
    sys.exit(main())
