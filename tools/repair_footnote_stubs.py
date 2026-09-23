#!/usr/bin/env python3
"""v9.376 — gli articoli ABROGATI che il parser saltava perché il numero della nota era attaccato al numero
dell'articolo («Neni 19¹³» → «Neni 1913», nota 13: «Shfuqizuar me ligjin nr. 10444/2011»): restava un BUCO e chi
citava il neni 19 riceveva «nen fantazmë» invece di «i shfuqizuar». Per ogni buco di numerazione di un codice AL si
cerca nel testo sorgente la riga «Neni <N><nota>» e la nota «<nota> Shfuqizuar …»: solo se c'è, l'articolo entra come
stub ABROGATO con la sua fonte nella nota. Mai inventato: senza la nota di abrogazione il buco resta.

    python3 tools/repair_footnote_stubs.py            # rapporto
    python3 tools/repair_footnote_stubs.py --apply    # backup + jsonl + indice
"""
import collections, json, re, shutil, sys, time
sys.path.insert(0, "/app")
from pathlib import Path
from src.config import PROCESSED_DATA_PATH, RAW_DATA_PATH, LEGAL_DOCUMENTS
from src import parser as P

JSONL = PROCESSED_DATA_PATH / "all_articles.jsonl"
CACHE = PROCESSED_DATA_PATH / "al_text_cache"


def testo(code: str) -> str:
    f = CACHE / f"{code}.txt"
    if f.exists():
        return f.read_text(encoding="utf-8")
    doc = next((d for d in LEGAL_DOCUMENTS if d.code == code), None)
    if doc is None:
        return ""
    for pdf in (RAW_DATA_PATH / (doc.local_pdf or ""), RAW_DATA_PATH / "al_qbz" / f"{code}.pdf"):
        if pdf.is_file():
            try:
                return P.extract_full_text(pdf)
            except Exception:  # noqa: BLE001
                return ""
    return ""


def main() -> int:
    rows = [json.loads(l) for l in JSONL.open(encoding="utf-8") if l.strip()]
    per = collections.defaultdict(list)
    for r in rows:
        per[r["code"]].append(r)
    nuovi, rep = [], collections.Counter()
    for code, arts in per.items():
        if P._is_italian_code(code):
            continue
        base = {int(m.group()) for a in arts for m in [re.match(r"\d+", str(a["number"]))] if m}
        if not base:
            continue
        mancanti = [n for n in range(1, max(base)) if n not in base]
        if not mancanti:
            continue
        t = testo(code)
        if not t:
            continue
        for n in mancanti:
            m = re.search(rf"(?m)^[ \t]*Neni[ \t]*{n}(\d{{1,3}})[ \t]*$", t)
            if not m:
                continue
            fn = m.group(1)
            nota = re.search(rf"(?m)^{fn}[ \t]+((?:Shfuqizuar|Hequr)[^\n]{{0,200}})", t)
            if not nota:
                continue
            kreu = P._hierarchy_context(t[: m.start()])
            nuovi.append({"code": code, "title_sq": arts[0]["title_sq"], "area": arts[0].get("area", ""), "number": str(n),
                          "heading": "", "body": "", "pjesa": kreu[0], "kreu": kreu[1], "seksioni": kreu[2],
                          "repealed": True, "volatility": arts[0].get("volatility", "STABLE"), "last_amendment_date": "",
                          "note": "(" + nota.group(1).strip().rstrip(".") + ")", "paragrafet": [], "heading_kind": "rubrike"})
            rep[code] += 1
    print("stub abrogati da aggiungere:", len(nuovi), dict(rep))
    for x in nuovi[:20]:
        print(f"  {x['code']:28s} neni {x['number']:>5s}  {x['note'][:90]}")
    if "--apply" not in sys.argv:
        print("(a secco: niente scritto; --apply per applicare)")
        return 0
    bak = JSONL.with_suffix(f".jsonl.bak-stub-{time.strftime('%Y%m%d%H%M')}")
    shutil.copy2(JSONL, bak)
    ordine = {}
    for i, r in enumerate(rows):
        ordine.setdefault(r["code"], i)
    rows += nuovi
    def _k(r):
        m = re.match(r"(\d+)(.*)", str(r["number"]))
        return (ordine.get(r["code"], 10**9), int(m.group(1)) if m else 0, m.group(2) if m else str(r["number"]))
    rows.sort(key=_k)
    with JSONL.open("w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    from src.retrieval import ArticleIndex, INDEX_FILE
    shutil.copy2(INDEX_FILE, INDEX_FILE.with_suffix(f".pkl.bak-stub-{time.strftime('%Y%m%d%H%M')}"))
    ix = ArticleIndex.from_jsonl(JSONL)
    ix.save(INDEX_FILE)
    print("scritto", JSONL.name, "(backup", bak.name + ") · indice", len(ix.articles), "articoli")
    return 0


if __name__ == "__main__":
    sys.exit(main())
