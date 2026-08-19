# -*- coding: utf-8 -*-
"""Build bm25_it.pkl from the downloaded Normattiva acts.
Writes: all_articles_it.jsonl, it_codes.json (metadata for the UI), bm25_it.pkl.
Keeps a timestamped backup of the previous index so a rollback is trivial.
"""
import json, shutil, sys, time
from dataclasses import asdict
from pathlib import Path
sys.path.insert(0, "/app")
from src.parser import Article
from src.retrieval import ArticleIndex

SRC = Path("/app/data/processed/it_acts")
JSONL = Path("/app/data/processed/all_articles_it.jsonl")
CODES_META = Path("/app/data/processed/it_codes.json")
INDEX = Path("/app/data/index/bm25_it.pkl")

# display order: fundamentals first, then by area
ORDER = ["costituzione", "codice_civile", "disp_att_cc", "codice_procedura_civile",
         "codice_penale", "codice_procedura_penale", "disp_att_cpp",
         "codice_strada", "regolamento_strada", "codice_consumo", "codice_crisi_impresa",
         "ordinamento_polizia", "tulps", "statuto_lavoratori", "sicurezza_lavoro",
         "tu_bancario", "tu_finanza", "codice_proprieta_industriale", "codice_terzo_settore",
         "codice_assicurazioni", "responsabilita_enti", "procedimento_amministrativo",
         "codice_processo_amministrativo", "codice_amministrazione_digitale",
         "tu_documentazione_amministrativa", "codice_contratti_pubblici",
         "sanzioni_amministrative", "tu_spese_giustizia", "codice_privacy",
         "codice_ambiente", "tu_edilizia", "tu_immigrazione", "codice_antimafia",
         "tuir", "codice_beni_culturali", "codice_navigazione", "stupefacenti",
         "ordinamento_penitenziario", "codice_pari_opportunita", "codice_protezione_civile",
         "divorzio", "adozione", "equa_riparazione"]


def main():
    files = sorted(SRC.glob("*.json"))
    if not files:
        print("nessun atto scaricato — esco")
        return 1
    acts = {}
    for f in files:
        try:
            acts[f.stem] = json.loads(f.read_text(encoding="utf-8"))
        except Exception as e:  # noqa: BLE001
            print(f"  ! {f.name} illeggibile: {e}")
    ordered = [c for c in ORDER if c in acts] + [c for c in sorted(acts) if c not in ORDER]

    all_articles, meta = [], []
    for cid in ordered:
        a = acts[cid]
        arts = a.get("articles") or []
        if not arts:
            print(f"  ! {cid}: 0 articoli — escluso")
            continue
        for art in arts:
            all_articles.append(Article(
                code=cid, title_sq=a["title"], area=a.get("area") or "",
                number=art["number"], heading=art.get("heading") or "",
                body=art.get("body") or "",
                pjesa="", kreu="", seksioni="",
                repealed=bool(art.get("repealed")), volatility="STABLE"))
        meta.append({"code": cid, "title": a["title"], "area": a.get("area") or "",
                     "count": len(arts)})
        print(f"  {cid:34s} {len(arts):>5} art   {a['title'][:46]}")

    print(f"\nTOTALE: {len(all_articles)} articoli su {len(meta)} corpora")

    # backup previous index before overwriting
    if INDEX.exists():
        bak = INDEX.with_suffix(f".pkl.bak-{time.strftime('%Y%m%d-%H%M%S')}")
        shutil.copy2(INDEX, bak)
        print(f"backup indice precedente -> {bak.name}")

    with JSONL.open("w", encoding="utf-8") as fh:
        for a in all_articles:
            fh.write(json.dumps(asdict(a), ensure_ascii=False) + "\n")
    CODES_META.write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
    ArticleIndex.build(all_articles, lang="it").save(INDEX)
    print(f"scritto: {JSONL.name}, {CODES_META.name}, {INDEX.name}")

    # sanity: reload and spot-check
    idx = ArticleIndex.load(INDEX)
    print(f"reload OK: {len(idx.articles)} articoli, lang={getattr(idx, 'lang', '?')}")
    by = {(a.code, a.number): a for a in idx.articles}
    checks = [("codice_civile", "2043"), ("codice_penale", "575"),
              ("codice_procedura_civile", "163"), ("codice_procedura_penale", "273"),
              ("costituzione", "21"), ("codice_strada", "186"), ("codice_strada", "142"),
              ("codice_consumo", "33"), ("codice_crisi_impresa", "2"),
              ("statuto_lavoratori", "18"), ("codice_privacy", "1")]
    for code, n in checks:
        a = by.get((code, n))
        print(f"  {code} art.{n}: " + (f"{(a.heading or a.body[:44])[:50]!r}" if a else "MANCANTE"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
