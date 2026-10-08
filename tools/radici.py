import sys, re, collections; sys.path.insert(0, "/app")
from pathlib import Path
from src import brain as B
from src.retrieval import ArticleIndex
for lang, anc, pkl in (("AL", B.ANCORE_AL, "bm25.pkl"), ("IT", B.ANCORE_IT, "bm25_it.pkl")):
    idx = ArticleIndex.load(Path("/app/data/index/" + pkl))
    voc = collections.Counter()
    for a in idx.articles[::3]:
        for w in re.findall(r"[a-zàèéìòùëç'-]+", ((a.heading or "") + " " + (a.body or "")[:800]).lower()):
            voc[w] += 1
    radici = set()
    for v in anc:
        for p in v[0]:
            for x in (p if isinstance(p, tuple) else (p,)):
                if " " not in x.strip() and 3 <= len(x.strip()) <= 5: radici.add(x.strip())
    print("==", lang, len(radici), "radici brevi")
    for r in sorted(radici):
        dentro = [(w, n) for w, n in voc.items() if r in w and not w.startswith(r)]
        dentro.sort(key=lambda x: -x[1])
        tot = sum(n for _, n in dentro)
        if tot >= 30: print(f"  {r!r:10} dentro {tot:5d}: " + ", ".join(f"{w}({n})" for w, n in dentro[:6]))
