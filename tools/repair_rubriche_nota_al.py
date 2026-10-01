"""v9.468 — rubriche albanesi col numero della NOTA A PIÈ DI PAGINA incollato in coda («Gjobat e komisionit35», «Fusha e
zbatimit2», «Përllogaritja e mandateve të subjekteve zgjedhore1»: 5 nel corpus): il numero si toglie. Solo una cifra o due
attaccate a una LETTERA (mai «… 2024», mai un numero staccato). jsonl E pickle, backup. Nel container con /app/data scrivibile:
python3 tools/repair_rubriche_nota_al.py [--apply]"""
import json, re, shutil, sys
from datetime import datetime
from pathlib import Path
sys.path.insert(0, "/app")
from src.retrieval import ArticleIndex  # noqa: E402

JSONL = Path("/app/data/processed/all_articles.jsonl")
RX = re.compile(r"(?<=[a-zçë»”)])\d{1,2}$")


def main() -> int:
    apply = "--apply" in sys.argv
    dati = [json.loads(r) for r in JSONL.read_text(encoding="utf-8").splitlines()]
    toccati = {}
    for d in dati:
        h = d.get("heading") or ""
        if RX.search(h):
            toccati[(d["code"], d["number"])] = RX.sub("", h)
            print(d["code"], d["number"], repr(h[-40:]), "→", repr(toccati[(d["code"], d["number"])][-40:]))
            d["heading"] = toccati[(d["code"], d["number"])]
    if not apply or not toccati:
        return 0
    stamp = datetime.now().strftime("%Y%m%d-%H%M")
    shutil.copy2(JSONL, str(JSONL) + f".bak-{stamp}-rubriche")
    JSONL.write_text("\n".join(json.dumps(d, ensure_ascii=False) for d in dati) + "\n", encoding="utf-8")
    idx = ArticleIndex.load()
    pkl = Path("/app/data/index/bm25.pkl")
    shutil.copy2(pkl, str(pkl) + f".bak-{stamp}-rubriche")
    for a in idx.articles:
        if (a.code, a.number) in toccati:
            a.heading = toccati[(a.code, a.number)]
    ArticleIndex.build(list(idx.articles), lang="sq", stem=bool(getattr(idx, "stem", False)),
                       fold=bool(getattr(idx, "fold", True))).save()
    print("FATTO", len(toccati))
    return 0


if __name__ == "__main__":
    sys.exit(main())
