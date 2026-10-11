# -*- coding: utf-8 -*-
"""v9.609 — le parole SPEZZATE a fine riga dai PDF di QBZ nei testi albanesi («kompen-simit», «adminis-⏎trative»,
«provue-⏎shmërisë», «Moni-torimit»): due pezzi che la ricerca non trova mai, né per parole né per senso.

Si riunisce SOLO quando la parola intera esiste ALTROVE nel corpus (vocabolario contato sul corpus, almeno `MIN_FREQ` volte) e il
pezzo di sinistra non è una sigla (MAIUSCOLO: «ILDKPKI-së», «KPK-ja») né un prefisso che si scrive col trattino («ish-shërbimit»):
un composto vero («njëri-tjetrit», «import-eksporti», «kripto-aseteve», «hyrje-dalje») non ha la forma unita nel corpus e resta.

    python3 tools/repair_trattini_al.py report [--code X]   # cosa cambierebbe, per codice (nulla scritto)
    python3 tools/repair_trattini_al.py json FILE.json      # il JSON di un atto PRIMA dell'ingest (ingest_al_qbz probe → apply)
    python3 tools/repair_trattini_al.py apply [--code X]    # all_articles.jsonl + bm25.pkl (backup), scrive <pkl>.trattini.json
                                                            # con le chiavi cambiate (per build_dense.py --rifai)
Gira nel container (o con le stesse cartelle): il pickle si ricostruisce con ArticleIndex.from_jsonl().
"""
import json
import os
import re
import shutil
import sys
import time
from collections import Counter
from pathlib import Path

sys.path.insert(0, "/app")

JSONL = Path(os.environ.get("TRATTINI_JSONL", "/app/data/processed/all_articles.jsonl"))
PKL = Path(os.environ.get("TRATTINI_PKL", "/app/data/index/bm25.pkl"))
MIN_FREQ = 2
_LETT = "A-Za-zËÇëç"
# «parola-» + (spazi e un a capo facoltativi) + «resto»: i due pezzi sono lettere, mai cifre (5-bis, 1-2), mai un altro trattino dopo
_RX = re.compile(rf"(?<![\w-])([{_LETT}]{{2,}})-[ \t]*(\n?)[ \t]*([a-zëç]{{2,}})(?![\w-])")
_TOK = re.compile(rf"[{_LETT}]+")
# in albanese col trattino si scrive il prefisso «ish-» («ish-bashkëshorti»); «para-», «ndër-», «vetë-», «mbi-» si scrivono uniti
# (parashikim, ndërkombëtare, vetëqeverisje): lì il trattino è un pezzo di PDF e la parola unita c'è nel vocabolario
_PREFISSI = {"ish", "zv"}


def vocabolario(testi) -> Counter:
    """Le parole del corpus (minuscole) e, sotto la chiave «a-b», quante volte compare la forma COL trattino."""
    c = Counter()
    for t in testi:
        c.update(w.lower() for w in _TOK.findall(t or ""))
        c.update(f"{m.group(1)}-{m.group(3)}".lower() for m in _RX.finditer(t or ""))
    return c


def ripara(testo: str, voc: Counter) -> tuple[str, list[str]]:
    """Il testo con le parole spezzate riunite e l'elenco dei cambi («kompen-simit → kompensimit»)."""
    cambi: list[str] = []

    def _sost(m):
        sx, acapo, dx = m.group(1), m.group(2), m.group(3)
        unita = sx + dx
        if sx.isupper() or sx.lower() in _PREFISSI or voc.get(unita.lower(), 0) < MIN_FREQ:
            return m.group(0)
        # la forma col trattino è DAVVERO un composto se compare più spesso della parola unita (non è il caso dei pezzi di PDF)
        if voc.get(f"{sx}-{dx}".lower(), 0) > voc.get(unita.lower(), 0):
            return m.group(0)
        cambi.append(f"{sx}-{'⏎' if acapo else ''}{dx} → {unita}")
        return unita

    return _RX.sub(_sost, testo or ""), cambi


def _campi(a: dict):
    return [k for k in ("heading", "body", "note") if isinstance(a.get(k), str) and a.get(k)]


def _ripara_articoli(articoli: list[dict], voc: Counter, solo: str | None = None):
    cambiati = []
    per_codice = Counter()
    esempi: dict[str, list[str]] = {}
    for a in articoli:
        if solo and a.get("code") != solo:
            continue
        tutti = []
        for k in _campi(a):
            nuovo, cambi = ripara(a[k], voc)
            if cambi:
                a[k] = nuovo
                tutti += cambi
        if tutti:
            cambiati.append(a)
            per_codice[a.get("code", "?")] += len(tutti)
            esempi.setdefault(a.get("code", "?"), []).extend(tutti)
    return cambiati, per_codice, esempi


def main() -> int:
    if len(sys.argv) < 2 or sys.argv[1] not in ("report", "json", "apply"):
        print(__doc__); return 2
    modo = sys.argv[1]
    solo = sys.argv[sys.argv.index("--code") + 1] if "--code" in sys.argv else None
    righe = [json.loads(l) for l in JSONL.read_text(encoding="utf-8").splitlines() if l.strip()]
    voc = vocabolario([(a.get("heading") or "") + " " + (a.get("body") or "") for a in righe])
    if modo == "json":
        p = Path(sys.argv[2])
        dati = json.loads(p.read_text(encoding="utf-8"))
        arts = dati["articles"] if isinstance(dati, dict) else dati
        voc.update(vocabolario([(a.get("heading") or "") + " " + (a.get("body") or "") for a in arts]))
        cambiati, per_codice, esempi = _ripara_articoli(arts, voc)
        for c, n in per_codice.items():
            print(f"  {c}: {n} parole riunite in {len(cambiati)} articoli — es. {esempi[c][:12]}")
        if cambiati:
            shutil.copy2(p, p.with_name(p.name + ".bak-" + time.strftime("%Y%m%d-%H%M%S") + "-trattini"))
            p.write_text(json.dumps(dati, ensure_ascii=False, indent=1), encoding="utf-8")
            print(f"scritto {p}")
        return 0
    cambiati, per_codice, esempi = _ripara_articoli(righe, voc, solo)
    print(f"{sum(per_codice.values())} parole riunite in {len(cambiati)} articoli")
    for c, n in per_codice.most_common():
        print(f"  {n:5d} {c:34s} es. {esempi[c][:8]}")
    if modo == "report" or not cambiati:
        return 0
    stamp = time.strftime("%Y%m%d-%H%M%S")
    shutil.copy2(JSONL, JSONL.with_name(JSONL.name + f".bak-{stamp}-trattini"))
    if PKL.exists():
        shutil.copy2(PKL, PKL.with_name(PKL.name + f".bak-{stamp}-trattini"))
    JSONL.write_text("".join(json.dumps(a, ensure_ascii=False) + "\n" for a in righe), encoding="utf-8")
    from src.retrieval import ArticleIndex
    ArticleIndex.from_jsonl(JSONL).save(PKL)
    chiavi = sorted({(str(a.get("code")), str(a.get("number"))) for a in cambiati})
    # lo stesso formato di repair_rubrika_paragrafi_al ([code, number]): build_dense.py --only al --kreu [--flat] --suffix _flat3|_ck3
    # --incremental --rifai <file>
    PKL.with_name(PKL.name + ".trattini.json").write_text(json.dumps([list(k) for k in chiavi], ensure_ascii=False), encoding="utf-8")
    print(f"scritti {JSONL} e {PKL} ({len(chiavi)} articoli cambiati → {PKL.name}.trattini.json)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
