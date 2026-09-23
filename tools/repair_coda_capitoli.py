#!/usr/bin/env python3
"""v9.376 — toglie dal CORPO degli articoli AL l'intestazione del capitolo SEGUENTE (976 articoli: «KREU VI / MASAT E
SIGURIMIT PASUROR / SEKSIONI I / SEKUESTROJA KONSERVATIVE» in coda al K.Pr.P. 269). Il capitolo dell'articolo seguente
resta nel suo campo `kreu` (letto dal testo, non dal corpo). Senza riscaricare nulla.

    python3 tools/repair_coda_capitoli.py            # rapporto, nulla scritto
    python3 tools/repair_coda_capitoli.py --apply    # backup del jsonl + scrittura + indice ricostruito
"""
import collections, json, shutil, sys, time
sys.path.insert(0, "/app")
from src import parser as P
from src.config import PROCESSED_DATA_PATH

JSONL = PROCESSED_DATA_PATH / "all_articles.jsonl"


def _norm(s: str) -> str:
    return " ".join((s or "").split())


def ripara(r: dict) -> str | None:
    """Ritorna la coda tolta (None se l'articolo non cambia). Modifica `r` sul posto."""
    body = r.get("body") or ""
    nuovo, coda = P.taglia_coda_gerarchia(body)
    if not coda:
        # articolo ABROGATO il cui «corpo» è solo l'intestazione seguente (Kodi Zgjedhor 85/1: «PJESA VII / …»)
        righe = [ln.strip() for ln in body.split("\n") if ln.strip()]
        if r.get("repealed") and righe and any(P.HIERARCHY_RE.match(x) for x in righe) and \
                all(P.HIERARCHY_RE.match(x) or P._riga_titolo(x) or P._NOTA_INTEST_RE.match(x) for x in righe):
            nuovo, coda = "", "\n".join(righe)
        else:
            return None
    r["body"] = nuovo
    par = list(r.get("paragrafet") or [])
    if par:
        cf, last = _norm(coda), _norm(par[-1])
        if cf and last.endswith(cf):
            last = last[: len(last) - len(cf)].rstrip()
            if last:
                par[-1] = last
            else:
                par.pop()
        elif not nuovo:
            par = []
        r["paragrafet"] = par
    return coda


def main() -> int:
    rows = [json.loads(l) for l in JSONL.open(encoding="utf-8") if l.strip()]
    cnt, ex = collections.Counter(), []
    for r in rows:
        if P._is_italian_code(r.get("code") or ""):
            continue
        coda = ripara(r)
        if coda is not None:
            cnt[r["code"]] += 1
            if len(ex) < 12:
                ex.append((r["code"], r["number"], _norm(coda)[:90], _norm(r["body"])[-60:]))
    print("articoli riparati:", sum(cnt.values()), dict(cnt.most_common(15)))
    for e in ex:
        print(f"  {e[0]:26s} {e[1]:>6s}  tolto «{e[2]}»  · ora finisce «…{e[3]}»")
    if "--apply" not in sys.argv:
        print("(a secco: niente scritto; --apply per applicare)")
        return 0
    bak = JSONL.with_suffix(f".jsonl.bak-coda-{time.strftime('%Y%m%d%H%M')}")
    shutil.copy2(JSONL, bak)
    with JSONL.open("w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    from src.retrieval import ArticleIndex, INDEX_FILE
    shutil.copy2(INDEX_FILE, INDEX_FILE.with_suffix(f".pkl.bak-coda-{time.strftime('%Y%m%d%H%M')}"))
    ix = ArticleIndex.from_jsonl(JSONL)
    ix.save(INDEX_FILE)
    print("scritto", JSONL.name, "(backup", bak.name + ") · indice", len(ix.articles), "articoli, fold", getattr(ix, "fold", None))
    return 0


if __name__ == "__main__":
    sys.exit(main())
