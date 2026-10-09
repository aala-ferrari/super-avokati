"""v9.567 — rubriche albanesi NON riconosciute, incollate al paragrafo 1 come «prima frase» («Përpunimi që nuk kërkon
identifikim 1. Nëse qëllimet…»): nelle leggi CON rubriche (≥60% «rubrike») la rubrica torna rubrica e il «1. …» torna nel
corpo. La regola è quella del parser (src/parser.py `rubrika_para_paragrafit`), così un ingest futuro dà lo stesso risultato.
Numeri, abrogazioni, date, note: intatti. jsonl E pickle, backup. Nel container con /app/data scrivibile:
python3 tools/repair_rubrika_paragrafi_al.py [--apply]
Dopo --apply: `<pkl>.rubpar.json` = le chiavi toccate per `build_dense.py --only al --kreu [--flat] --suffix _flat3|_ck3
--incremental --rifai <file>`."""
import json, os, shutil, sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path
sys.path.insert(0, "/app")
from src.parser import rubrika_para_paragrafit, _paragrafet  # noqa: E402
from src.retrieval import ArticleIndex  # noqa: E402

# prova su una COPIA: RUBPAR_JSONL / RUBPAR_PKL (default: i file veri)
JSONL = Path(os.environ.get("RUBPAR_JSONL", "/app/data/processed/all_articles.jsonl"))
PKL = Path(os.environ.get("RUBPAR_PKL", "/app/data/index/bm25.pkl"))


def main() -> int:
    apply = "--apply" in sys.argv
    dati = [json.loads(r) for r in JSONL.read_text(encoding="utf-8").splitlines() if r.strip()]
    per = defaultdict(list)
    for d in dati:
        per[d["code"]].append(d)
    nuovi = {}
    for code, arts in per.items():
        if sum(1 for d in arts if d.get("heading_kind") == "rubrike") < 0.6 * len(arts):
            continue
        for d in arts:
            if d.get("heading_kind") != "fjali" or d.get("repealed"):
                continue
            x = rubrika_para_paragrafit(d.get("heading") or "")
            if not x:
                continue
            rub, nota, primo = x
            if nota:
                d["note"] = " ".join(y for y in ((d.get("note") or ""), nota) if y).strip()
            body = (primo + ("\n" + d["body"] if (d.get("body") or "").strip() else "")).strip()
            nuovi[(code, d["number"])] = (rub, body, d.get("note") or "")
            print(f"{code} {d['number']}: «{rub}» {nota[:60]} | {primo[:60]}")
            d["heading"], d["body"], d["heading_kind"], d["paragrafet"] = rub, body, "rubrike", _paragrafet(body)
    print("TOTALE", len(nuovi))
    if not apply or not nuovi:
        return 0
    stamp = datetime.now().strftime("%Y%m%d-%H%M")
    shutil.copy2(JSONL, str(JSONL) + f".bak-{stamp}-rubpar")
    JSONL.write_text("\n".join(json.dumps(d, ensure_ascii=False) for d in dati) + "\n", encoding="utf-8")
    idx = ArticleIndex.load(PKL)
    shutil.copy2(PKL, str(PKL) + f".bak-{stamp}-rubpar")
    k = 0
    for a in idx.articles:
        if (a.code, a.number) in nuovi:
            a.heading, a.body, a.note = nuovi[(a.code, a.number)]
            a.heading_kind = "rubrike"
            a.paragrafet = _paragrafet(a.body)
            k += 1
    ArticleIndex.build(list(idx.articles), lang="sq", stem=bool(getattr(idx, "stem", False)),
                       fold=bool(getattr(idx, "fold", True))).save(PKL)
    Path(str(PKL) + ".rubpar.json").write_text(json.dumps([list(k) for k in nuovi], ensure_ascii=False), encoding="utf-8")
    print("FATTO jsonl", len(nuovi), "pickle", k)
    return 0


if __name__ == "__main__":
    sys.exit(main())
