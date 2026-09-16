# -*- coding: utf-8 -*-
"""Costruisce `data/index/case_graph.json` dai precedenti del pickle (v9.339, roadmap v3 P6):
citazioni fra decisioni, decisioni della Gjykata e Lartë ANNULLATE dalla Kushtetuese, decisioni
unificatrici. Da rilanciare dopo ogni aggiunta di precedenti (DecisionIndex).

    docker exec super-avvocato python3 tools/build_case_graph.py          # scrive + riepilogo
    docker exec super-avvocato python3 tools/build_case_graph.py --dry    # solo riepilogo
"""
import json, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from src.retrieval import DecisionIndex, DECISIONS_INDEX_FILE  # noqa: E402
from src import case_graph  # noqa: E402


def main() -> int:
    idx = DecisionIndex.load(DECISIONS_INDEX_FILE)
    g = case_graph.build(idx.decisions)
    print(f"decisioni {g['n']} · citazioni risolte {g['edges']} · vendime GjL annullati dalla Kushtetuese {g['quashes_total']} "
          f"(di cui nel corpus {g['quashed']}) · norme dichiarate incostituzionali {g['invalidations']} · unificatrici {g['unifying']}")
    top = sorted(g["nodes"].values(), key=lambda v: -v["cited_by"])[:8]
    print("più citate:", [(v["court"], v["number"], v["year"], v["cited_by"]) for v in top])
    q = [(k, v["quashed_by"]) for k, v in g["nodes"].items() if v["quashed_by"]]
    print("annullate nel corpus:", q[:10])
    inv = [(k, i["law"], i["articles"]) for k, v in g["nodes"].items() for i in v["invalidates"]]
    print("incostituzionali (esempi):", inv[:8])
    if "--dry" in sys.argv:
        return 0
    p = case_graph.path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(g, ensure_ascii=False), encoding="utf-8")
    print("scritto", p, p.stat().st_size // 1024, "KB")
    return 0


if __name__ == "__main__":
    sys.exit(main())
