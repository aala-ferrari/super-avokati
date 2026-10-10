"""v9.578 — gli articoli albanesi il cui CORPO è soltanto il titolo del capitolo seguente.

Nei codici senza rubriche (KC, Kushtetuta, KF) il testo dell'articolo sta nella «prima frase» (`heading`, «fjali») e il corpo
arriva fino al «Neni» successivo: quando l'articolo è l'ultimo del suo capitolo, il corpo è SOLO l'intestazione del capitolo dopo —
il KC 540 (nullità del patto commissorio) aveva per corpo «KREU II ⏎ KUSHTI PENAL», il KC 63 «TITULLI II ⏎ PËRFAQËSIMI ⏎ KREU I ⏎
KUPTIMI DHE LLOJET E PËRFAQËSIMIT», la Kushtetuta 44 «KREU III ⏎ LIRITË DHE TË DREJTAT POLITIKE». `parser.taglia_coda_gerarchia`
(v9.376/571) non svuota mai un corpo per intero e li lasciava: nel blocco del cervello quel titolo stava come testo dell'articolo
sbagliato, e la ricerca trovava il KC 540 cercando «kushti penal». Qui il corpo si svuota solo se è fatto per intero di
intestazioni e titoli (la stessa regola, provata aggiungendo una riga di contenuto in testa) e la rubrica porta il testo
dell'articolo; e si taglia la stessa intestazione incollata in fondo all'ultima riga («… nga Akademia e Sigurisë. KREU II
AUTORITETET», ligji 108/2014). jsonl E pickle, backup, idempotente. Prova su copia: RUBPAR_JSONL / RUBPAR_PKL.
    python3 tools/repair_coda_sola_al.py [--apply]   → poi build_dense.py --only al --kreu [--flat] --suffix _flat3|_ck3
                                                       --incremental --rifai <pkl>.codasola.json"""
import json, os, re, shutil, sys
from datetime import datetime
from pathlib import Path
sys.path.insert(0, "/app")
from src.parser import taglia_coda_gerarchia, _is_italian_code, _paragrafet  # noqa: E402
from src.retrieval import ArticleIndex  # noqa: E402

JSONL = Path(os.environ.get("RUBPAR_JSONL", "/app/data/processed/all_articles.jsonl"))
PKL = Path(os.environ.get("RUBPAR_PKL", "/app/data/index/bm25.pkl"))
# l'intestazione incollata in fondo all'ultima riga, dopo la fine di una frase: «… Sigurisë. KREU II AUTORITETET»
INCOLLATA = re.compile(r"(?<=[.;:])\s+(?:KREU|PJESA|SEKSIONI|TITULLI|KAPITULLI)\s+[IVXLC]+\s+[A-ZËÇ][A-ZËÇ ,]{3,}$")


def nuovo_corpo(d: dict):
    """→ (corpo nuovo, coda tolta) oppure None se non c'è niente da fare."""
    body = d.get("body") or ""
    if not body.strip():
        return None
    corpo, coda = taglia_coda_gerarchia("Riga di contenuto.\n" + body)
    if corpo.strip() == "Riga di contenuto." and coda and len((d.get("heading") or "").strip()) >= 20:
        return "", coda                                   # il corpo era SOLO intestazioni: il testo dell'articolo è nella rubrica
    m = INCOLLATA.search(body)
    if m:
        return body[:m.start()].rstrip(), m.group(0).strip()
    return None


def main() -> int:
    apply = "--apply" in sys.argv
    dati = [json.loads(r) for r in JSONL.read_text(encoding="utf-8").splitlines() if r.strip()]
    cambi = {}
    for d in dati:
        if _is_italian_code(d["code"]):
            continue
        x = nuovo_corpo(d)
        if x is None:
            continue
        corpo, coda = x
        cambi[(d["code"], str(d["number"]))] = corpo
        print(f"{d['code']} {d['number']}: «{(d.get('heading') or '')[:50]}» — tolto «{coda.replace(chr(10), ' ⏎ ')[:80]}»"
              + (f" | resta {len(corpo)} chr" if corpo else " | corpo vuoto"))
        d["body"] = corpo
        d["paragrafet"] = _paragrafet(corpo) if corpo else []
    print(f"articoli cambiati {len(cambi)}")
    if not apply or not cambi:
        return 0
    stamp = datetime.now().strftime("%Y%m%d-%H%M")
    shutil.copy2(JSONL, str(JSONL) + f".bak-{stamp}-codasola")
    JSONL.write_text("\n".join(json.dumps(d, ensure_ascii=False) for d in dati) + "\n", encoding="utf-8")
    idx = ArticleIndex.load(PKL)
    shutil.copy2(PKL, str(PKL) + f".bak-{stamp}-codasola")
    for a in idx.articles:
        k = (a.code, str(a.number))
        if k in cambi:
            a.body = cambi[k]
            a.paragrafet = _paragrafet(a.body) if a.body else []
    ArticleIndex.build(list(idx.articles), lang="sq", stem=bool(getattr(idx, "stem", False)),
                       fold=bool(getattr(idx, "fold", True))).save(PKL)
    Path(str(PKL) + ".codasola.json").write_text(json.dumps([list(k) for k in cambi], ensure_ascii=False), encoding="utf-8")
    print(f"scritti {JSONL} e {PKL}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
