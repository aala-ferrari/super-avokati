"""v9.492 — i NUMERI DOPPI del corpus albanese. Nel testo ufficiale della ligji 8788/2001 «Për organizatat jofitimprurëse» (base E
consolidato QBZ) DUE articoli portano il numero 12 («Ndarja e organizatave jofitimprurëse sipas së drejtës» e «Subjektet
themeluese»): un errore di redazione del legislatore. Nel corpus due voci con la stessa chiave rompono la ricerca per numero (se ne
trova una sola) e l'allineamento degli embedding («1 articoli nuovi senza embedding»). Qui: i testi diversi diventano UNA unità
con entrambi i testi in ordine e una nota redazionale dichiarata; un doppione identico si toglie. jsonl E pickle, backup,
idempotente. Nel container con /app/data scrivibile:  python3 tools/repair_doppi_neni_al.py [--apply]"""
import collections
import json
import shutil
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, "/app")
from src.retrieval import ArticleIndex  # noqa: E402

JSONL = Path("/app/data/processed/all_articles.jsonl")
NOTA = ("Shënim redaksional: në tekstin zyrtar të ligjit dy nene mbajnë numrin {n} («{h1}» dhe «{h2}»); këtu janë bashkuar në një "
        "njësi, në rendin e tekstit zyrtar.")


def main() -> int:
    apply = "--apply" in sys.argv
    dati = [json.loads(r) for r in JSONL.read_text(encoding="utf-8").splitlines() if r.strip()]
    gruppi = collections.defaultdict(list)
    for k, d in enumerate(dati):
        gruppi[(d["code"], str(d["number"]))].append(k)
    doppi = {k: v for k, v in gruppi.items() if len(v) > 1}
    if not doppi:
        print("nessun numero doppio")
        return 0
    togli = set()
    for (code, num), pos in doppi.items():
        primi = [dati[p] for p in pos]
        if all((x.get("body") or "").strip() == (primi[0].get("body") or "").strip() for x in primi):
            togli.update(pos[1:])
            print(f"{code} {num}: {len(pos)} copie identiche → tengo la prima")
            continue
        h = [(x.get("heading") or "").strip() for x in primi]
        unito = dict(primi[0])
        unito["heading"] = " / ".join(x for x in h if x)
        unito["body"] = "\n\n".join(f"Neni {num} — {hh}\n{(x.get('body') or '').strip()}" for x, hh in zip(primi, h))
        nota = NOTA.format(n=num, h1=h[0], h2=h[1] if len(h) > 1 else "")
        unito["note"] = ((primi[0].get("note") or "") + " " + nota).strip()
        unito["paragrafet"] = []
        dati[pos[0]] = unito
        togli.update(pos[1:])
        print(f"{code} {num}: {len(pos)} articoli diversi → una unità «{unito['heading'][:90]}» ({len(unito['body'])} chr)")
    if not apply:
        return 0
    stamp = datetime.now().strftime("%Y%m%d-%H%M")
    shutil.copy2(JSONL, str(JSONL) + f".bak-{stamp}-doppi")
    nuovi = [d for k, d in enumerate(dati) if k not in togli]
    JSONL.write_text("\n".join(json.dumps(d, ensure_ascii=False) for d in nuovi) + "\n", encoding="utf-8")
    pkl = Path("/app/data/index/bm25.pkl")
    shutil.copy2(pkl, str(pkl) + f".bak-{stamp}-doppi")
    vecchio = ArticleIndex.load()
    idx = ArticleIndex.from_jsonl(JSONL, lang="sq")
    idx.save()
    print(f"FATTO: {len(dati)} → {len(nuovi)} voci; indice {len(vecchio.articles)} → {len(idx.articles)}; backup {stamp}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
