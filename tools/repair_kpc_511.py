"""v9.468 — il Neni 511 del K.Pr.C. («Urdhri i ekzekutimit», l'ordine di esecuzione: base di ogni esecuzione forzata) MANCAVA dal
corpus: nel consolidato QBZ l'intestazione è «Neni 5111» (il numero della nota a piè di pagina incollato: la nota è la decisione
della Gjykata Kushtetuese n. 30/2022 sul paragrafo 5, lettera d) e il parser l'ha lasciato dentro il corpo del 510. Qui: il 510
torna al suo testo, il 511 diventa un articolo a sé con la nota della GjK nel campo `note` (dichiarata). jsonl E pickle, backup,
idempotente. Nel container con /app/data scrivibile:  python3 tools/repair_kpc_511.py [--apply]"""
import copy, json, shutil, sys
from datetime import datetime
from pathlib import Path
sys.path.insert(0, "/app")
from src.retrieval import ArticleIndex, Article  # noqa: E402

JSONL = Path("/app/data/processed/all_articles.jsonl")
TAGLIO = "\nNeni 5111\n"
NOTA_GJK = ("Vendimi i Gjykatës Kushtetuese nr. 30, datë 2.11.2022: zbatimi i nenit 511, paragrafi i pestë, shkronja «d», në "
            "shprehjen «që rregullon pagesat e vonuara në detyrimet kontraktore dhe tregtare», nuk është në përputhje me Kushtetutën "
            "në rastet e akteve për dhënie kredie bankare konsumatore; Kuvendi detyrohet të plotësojë ligjin brenda gjashtë muajve "
            "(shënim në fund të faqes së tekstit të konsoliduar QBZ).")


def ndaj(a510: dict) -> tuple[dict, dict] | None:
    b = a510.get("body") or ""
    if TAGLIO not in b:
        return None
    para, pas = b.split(TAGLIO, 1)
    rreshta = pas.split("\n")
    titulli = rreshta[0].strip()                               # «Urdhri i ekzekutimit»
    mbetja = "\n".join(rreshta[1:])
    shenim = ""
    if mbetja.startswith("(Shtuar"):
        j = mbetja.find(")\n")
        shenim, mbetja = mbetja[:j + 1].replace("\n", " "), mbetja[j + 2:]
    # la nota a piè di pagina della GjK (righe «1 Vendimi … 1. Të deklarojë … 2. Të detyrojë …») fuori dal testo
    i = mbetja.find("1 Vendimi i Gjykatës Kushtetuese nr. 30")
    if i >= 0:
        k = mbetja.find("a) për rastet e parashikuara", i)
        if k > i:
            mbetja = mbetja[:i] + mbetja[k:]
    n510 = dict(a510, body=para.rstrip(), paragrafet=[p for p in (a510.get("paragrafet") or []) if "Neni 5111" not in p][:2])
    n511 = copy.deepcopy(a510)
    n511.update(number="511", heading=titulli, body=mbetja.strip(), note=(shenim + " " + NOTA_GJK).strip(),
                paragrafet=[], heading_kind="rubrike", last_amendment_date="2017-03-30")
    return n510, n511


def main() -> int:
    apply = "--apply" in sys.argv
    righe = JSONL.read_text(encoding="utf-8").splitlines()
    dati = [json.loads(r) for r in righe]
    if any(d["code"] == "kodi_proc_civile" and d["number"] == "511" for d in dati):
        print("già riparato: il 511 c'è"); return 0
    i = next(k for k, d in enumerate(dati) if d["code"] == "kodi_proc_civile" and d["number"] == "510")
    r = ndaj(dati[i])
    if not r:
        print("taglio non trovato"); return 1
    n510, n511 = r
    print("510:", len(dati[i]["body"]), "→", len(n510["body"]), "| 511:", n511["heading"], len(n511["body"]), "chr")
    print("511 inizio:", n511["body"][:200].replace("\n", " "))
    print("511 nota:", n511["note"][:200])
    if not apply:
        return 0
    stamp = datetime.now().strftime("%Y%m%d-%H%M")
    shutil.copy2(JSONL, str(JSONL) + f".bak-{stamp}-kpc511")
    dati[i] = n510
    dati.insert(i + 1, n511)
    JSONL.write_text("\n".join(json.dumps(d, ensure_ascii=False) for d in dati) + "\n", encoding="utf-8")
    idx = ArticleIndex.load()
    pkl = Path("/app/data/index/bm25.pkl")
    shutil.copy2(pkl, str(pkl) + f".bak-{stamp}-kpc511")
    arts = list(idx.articles)
    j = next(k for k, a in enumerate(arts) if a.code == "kodi_proc_civile" and a.number == "510")
    campi = set(Article.__dataclass_fields__)
    arts[j] = Article(**{k: v for k, v in n510.items() if k in campi})
    arts.insert(j + 1, Article(**{k: v for k, v in n511.items() if k in campi}))
    ArticleIndex.build(arts, lang="sq", stem=bool(getattr(idx, "stem", False)), fold=bool(getattr(idx, "fold", True))).save()
    print("FATTO: jsonl e pickle, backup", stamp)
    return 0


if __name__ == "__main__":
    sys.exit(main())
