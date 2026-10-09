"""v9.570 — il KC art. 3 («Të huajt gëzojnë po ato të drejta e detyrime që u njihen shtetasve shqiptarë…», lo straniero ha gli
stessi diritti del cittadino) aveva come «prima frase» la NOTA A PIÈ DI PAGINA del consolidato QBZ: «1 Ligj nr. 17/2012, datë
16.2.2012 në nenin 4 shprehet; ‘’Për çështjet civile me objekt shpërblimin e dëmit jopasuror ndaj reputacionit…’’» — la nota
dell'elenco delle modifiche in testa al codice, stampata a fondo pagina sopra il testo del neni 3. Il neni 3 torna al suo testo;
la nota (la norma TRANSITORIA dell'art. 4 della legge 17/2012 sul danno non patrimoniale alla reputazione) va nella nota del
KC 625, l'articolo che quella legge ha modificato. Idempotente; jsonl E pickle, backup. Prova su copia: RUBPAR_JSONL / RUBPAR_PKL.
    python3 tools/repair_kc3_nota.py [--apply]      → poi build_dense.py --only al --kreu [--flat] --suffix _flat3|_ck3
                                                       --incremental --rifai <pkl>.kc3.json"""
import json, os, re, shutil, sys
from datetime import datetime
from pathlib import Path
sys.path.insert(0, "/app")
from src.parser import _paragrafet  # noqa: E402
from src.retrieval import ArticleIndex  # noqa: E402

JSONL = Path(os.environ.get("RUBPAR_JSONL", "/app/data/processed/all_articles.jsonl"))
PKL = Path(os.environ.get("RUBPAR_PKL", "/app/data/index/bm25.pkl"))
RX = re.compile(r"^\s*1\s+Ligj nr\.\s*17/2012.*?jopasuror\.\s*(?:’’|''|”|\")\s*(?P<t>Të huajt\b.*)$", re.S)


def _nuovo(h3: str):
    m = RX.match(h3 or "")
    if not m:
        return None
    nota = " ".join(h3[:m.start("t")].split())
    nota = re.sub(r"^1\s+", "", nota)                         # il numero della nota a piè di pagina
    testo = " ".join(m.group("t").split())
    trans = "Dispozitë kalimtare — " + nota.replace("në nenin 4 shprehet;", "neni 4:")
    return testo, trans


def main() -> int:
    apply = "--apply" in sys.argv
    dati = [json.loads(r) for r in JSONL.read_text(encoding="utf-8").splitlines() if r.strip()]
    d3 = next(d for d in dati if d["code"] == "kodi_civil" and str(d["number"]) == "3")
    d625 = next(d for d in dati if d["code"] == "kodi_civil" and str(d["number"]) == "625")
    x = _nuovo(d3.get("heading") or "")
    if not x:
        print("KC 3 già a posto:", (d3.get("heading") or "")[:80]); return 0
    testo, trans = x
    print("KC 3  →", testo)
    print("KC 625 nota +", trans[:160], "…")
    d3["heading"], d3["body"], d3["paragrafet"] = testo, "", _paragrafet(testo)
    if "17/2012" not in (d625.get("note") or "") or "kalimtare" not in (d625.get("note") or ""):
        d625["note"] = " ".join(y for y in ((d625.get("note") or "").strip(), trans) if y)
    if not apply:
        return 0
    stamp = datetime.now().strftime("%Y%m%d-%H%M")
    shutil.copy2(JSONL, str(JSONL) + f".bak-{stamp}-kc3")
    JSONL.write_text("\n".join(json.dumps(d, ensure_ascii=False) for d in dati) + "\n", encoding="utf-8")
    idx = ArticleIndex.load(PKL)
    shutil.copy2(PKL, str(PKL) + f".bak-{stamp}-kc3")
    for a in idx.articles:
        if a.code == "kodi_civil" and str(a.number) == "3":
            a.heading, a.body, a.paragrafet = testo, "", _paragrafet(testo)
        elif a.code == "kodi_civil" and str(a.number) == "625":
            a.note = d625["note"]
    ArticleIndex.build(list(idx.articles), lang="sq", stem=bool(getattr(idx, "stem", False)),
                       fold=bool(getattr(idx, "fold", True))).save(PKL)
    Path(str(PKL) + ".kc3.json").write_text(json.dumps([["kodi_civil", "3"]]), encoding="utf-8")
    print("FATTO")
    return 0


if __name__ == "__main__":
    sys.exit(main())
