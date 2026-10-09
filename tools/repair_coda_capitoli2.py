"""v9.571 — seconda passata della v9.376 sulle CODE DI CAPITOLO nei testi AL: l'intestazione del capitolo seguente rimasta in fondo
all'articolo quando il titolo è in minuscolo («KREU II ⏎ SUBJEKTET E SË DREJTËS ⏎ SEKSIONI I ⏎ Personat fizikë», dnp 7; «KREU III
⏎ … ⏎ Kapitulli 1 ⏎ Dispozitat e përgjithshme …», imposta sul reddito 26): la regola nuova è in `parser.taglia_coda_gerarchia`,
qui si applica a jsonl E pickle (backup) con `repair_coda_capitoli.ripara` — il capitolo dell'articolo seguente resta nel suo
campo `kreu`. Prova su copia: RUBPAR_JSONL / RUBPAR_PKL.  python3 tools/repair_coda_capitoli2.py [-v] [--apply]
→ poi build_dense.py --only al --kreu [--flat] --suffix _flat3|_ck3 --incremental --rifai <pkl>.coda2.json"""
import collections, importlib.util, json, os, shutil, sys
from datetime import datetime
from pathlib import Path
sys.path.insert(0, "/app")
from src import parser as P  # noqa: E402
from src.retrieval import ArticleIndex  # noqa: E402

JSONL = Path(os.environ.get("RUBPAR_JSONL", "/app/data/processed/all_articles.jsonl"))
PKL = Path(os.environ.get("RUBPAR_PKL", "/app/data/index/bm25.pkl"))
_sp = importlib.util.spec_from_file_location("rcc", str(Path(__file__).with_name("repair_coda_capitoli.py")))
_rcc = importlib.util.module_from_spec(_sp); _sp.loader.exec_module(_rcc)


def main() -> int:
    apply, verbose = "--apply" in sys.argv, "-v" in sys.argv
    rows = [json.loads(l) for l in JSONL.read_text(encoding="utf-8").splitlines() if l.strip()]
    nuovi, cnt = {}, collections.Counter()
    for r in rows:
        if P._is_italian_code(r.get("code") or ""):
            continue
        prima = r.get("body") or ""
        coda = _rcc.ripara(r)
        if coda is None:
            continue
        k = (r["code"], str(r["number"]))
        nuovi[k] = (r["body"], list(r.get("paragrafet") or []))
        cnt[r["code"]] += 1
        if verbose:
            print(f"{k[0]} {k[1]}: tolto «{' ⏎ '.join(coda.splitlines())[:160]}» · ora finisce «…{' '.join(r['body'].split())[-70:]}»")
    print("articoli:", len(nuovi), dict(cnt.most_common(15)))
    if not apply or not nuovi:
        return 0
    stamp = datetime.now().strftime("%Y%m%d-%H%M")
    shutil.copy2(JSONL, str(JSONL) + f".bak-{stamp}-coda2")
    JSONL.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n", encoding="utf-8")
    idx = ArticleIndex.load(PKL)
    shutil.copy2(PKL, str(PKL) + f".bak-{stamp}-coda2")
    for a in idx.articles:
        k = (a.code, str(a.number))
        if k in nuovi:
            a.body, a.paragrafet = nuovi[k]
    ArticleIndex.build(list(idx.articles), lang="sq", stem=bool(getattr(idx, "stem", False)),
                       fold=bool(getattr(idx, "fold", True))).save(PKL)
    Path(str(PKL) + ".coda2.json").write_text(json.dumps([list(k) for k in nuovi], ensure_ascii=False), encoding="utf-8")
    print("FATTO", len(nuovi))
    return 0


if __name__ == "__main__":
    sys.exit(main())
