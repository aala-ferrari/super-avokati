# -*- coding: utf-8 -*-
"""v9.633 — le PARTI dei codici albanesi («PJESA E PARË … PJESA E TETËMBËDHJETË»), che il parser non leggeva.

Il regex delle intestazioni voleva UNA parola dopo l'etichetta («PJESA I», «KREU IV»): la forma «PJESA E PARË» non passava, quindi in
19 codici nessuna Parte entrava nel campo `pjesa` e il CAPITOLO non si azzerava quando cominciava una Parte nuova. Nella Costituzione gli
artt. 121-183 (Corte costituzionale, tribunali, procura, referendum, finanze, forze armate, misure straordinarie, disposizioni
transitorie — anche la 179/b del vetting) erano tutti nel «KREU II — MARRËVESHJET NDËRKOMBËTARE», e gli artt. 81-115 (Presidente,
Consiglio dei ministri, governo locale) nel «KREU IV — PROCESI LIGJVËNËS»: il titolo del capitolo entra nella ricerca per parole, negli
embedding e nell'indice del capitolo dato al cervello. E l'intestazione della Parte seguente restava in coda all'ultimo articolo della
Parte prima («… PJESA E KATËRT ⏎ PRESIDENTI I REPUBLIKËS» nell'art. 85).

Come ripara, SENZA riscaricare e senza toccare il resto: per ogni codice col testo sorgente in `data/processed/al_text_cache`, rilegge il
testo DUE volte col parser di oggi — col regex vecchio e con quello nuovo — e prende la differenza: un articolo cambia `pjesa/kreu/seksioni`
SOLO se i valori del jsonl coincidono con quelli del regex vecchio (cioè vengono da lì) e quelli nuovi sono diversi; dal corpo si toglie
la coda che comincia con un'intestazione «PJESA E …» (solo righe di titolo). Testo, rubriche, note, numeri e abrogazioni restano.

    docker run … python3 tools/repair_pjesa_al.py                        # rapporto a secco
    docker run … python3 tools/repair_pjesa_al.py --out-dir /tmp/pjesa   # jsonl + bm25.pkl di PROVA (produzione intatta)
    docker run … python3 tools/repair_pjesa_al.py --apply                # produzione, con backup; scrive <pkl>.pjesa.json per
                                                                          # build_dense.py --rifai (gli embedding portano il capitolo)
"""
import argparse, json, re, shutil, sys, time
sys.path.insert(0, "/app")
from pathlib import Path

from src import parser as P
from src.config import LegalDocument, PROCESSED_DATA_PATH
from src.retrieval import ArticleIndex, INDEX_FILE

JSONL = PROCESSED_DATA_PATH / "all_articles.jsonl"
CACHE = PROCESSED_DATA_PATH / "al_text_cache"
PJESA_E = re.compile(r"(?m)^[ \t]*PJESA\s+E\s+[A-ZÇË]+\s*$")
VECCHIO = re.compile(r"(?m)^[ \t]*(PJESA|KREU|SEKSIONI|TITULLI|KAPITULLI)\s+([A-ZÇËÏ0-9/]+)\s*$")


def _gerarchie(text, doc, rx):
    salva = P.HIERARCHY_RE
    P.HIERARCHY_RE = rx
    try:
        arts = P.split_into_articles(text, doc)
    finally:
        P.HIERARCHY_RE = salva
    return {str(a.number): ((a.pjesa or ""), (a.kreu or ""), (a.seksioni or "")) for a in arts}


def _taglia_coda_pjesa(body: str, heading: str = "") -> tuple[str, str]:
    """Toglie dal corpo la coda che comincia con «PJESA E …» se è fatta solo di righe di titolo (col parser nuovo). Se il corpo è
    fatto SOLO dell'intestazione della Parte seguente (Costituzione 94, 147/ë, 176: l'articolo di una frase ha il testo nella rubrica,
    come i corpi-capitolo della v9.578) lo svuota — solo se la rubrica ha il testo."""
    if not PJESA_E.search(body or ""):
        return body, ""
    nuovo, coda = P.taglia_coda_gerarchia(body)
    if coda and PJESA_E.search(coda):
        return nuovo, coda
    righe = [ln.strip() for ln in (body or "").split("\n") if ln.strip()]
    if righe and len((heading or "").strip()) >= 20 and all(P.HIERARCHY_RE.match(ln) or P._riga_titolo(ln) for ln in righe):
        return "", "\n".join(righe)
    return body, ""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--out-dir", default="")
    ap.add_argument("--only", default="")
    a = ap.parse_args()
    rows = [json.loads(l) for l in JSONL.read_text(encoding="utf-8").splitlines() if l.strip()]
    per_code: dict[str, list[dict]] = {}
    for r in rows:
        per_code.setdefault(r["code"], []).append(r)
    only = {c for c in a.only.split(",") if c}
    cambi: dict[tuple, dict] = {}
    ricodifica: set = set()          # contenitore o corpo cambiati: gli embedding (che portano il capitolo) vanno rifatti
    tot = {"codici": 0, "gerarchia": 0, "contenitore": 0, "code_tolte": 0, "diversi_dal_vecchio": 0}
    for code, olds in sorted(per_code.items()):
        if only and code not in only:
            continue
        f = CACHE / f"{code}.txt"
        if not f.exists():
            continue
        text = f.read_text(encoding="utf-8", errors="replace")
        if not PJESA_E.search(text):
            continue
        o = olds[0]
        doc = LegalDocument(code=code, title_sq=o["title_sq"], title_en=code, area=o.get("area", ""), url="", local_pdf="",
                            volatility=o.get("volatility", "MEDIUM"))
        vecchio, nuovo = _gerarchie(text, doc, VECCHIO), _gerarchie(text, doc, P.HIERARCHY_RE)
        tot["codici"] += 1
        g = c = d = k = 0
        esempi = []
        for r in olds:
            n = str(r["number"])
            cur = ((r.get("pjesa") or ""), (r.get("kreu") or ""), (r.get("seksioni") or ""))
            mod = {}
            if n in vecchio and n in nuovo and vecchio[n] != nuovo[n]:
                if cur == vecchio[n]:
                    mod["pjesa"], mod["kreu"], mod["seksioni"] = nuovo[n]
                    g += 1
                    # il CONTENITORE (capitolo, o la Parte senza capitoli) è ciò che entra in ricerca ed embedding
                    if (cur[1] or cur[0], cur[2]) != (nuovo[n][1] or nuovo[n][0], nuovo[n][2]):
                        k += 1
                        ricodifica.add((code, n))
                        if len(esempi) < 4:
                            esempi.append(f"{n}: «{(cur[1] or cur[0])[:55]}» → «{(nuovo[n][1] or nuovo[n][0])[:55]}»")
                else:
                    d += 1
            corpo, coda = _taglia_coda_pjesa(r.get("body") or "", r.get("heading") or "")
            if coda:
                mod["body"] = corpo
                c += 1
                ricodifica.add((code, n))
            if mod:
                cambi[(code, n)] = mod
        tot["gerarchia"] += g; tot["contenitore"] += k; tot["code_tolte"] += c; tot["diversi_dal_vecchio"] += d
        print(f"[{code:30s}] Parti nel testo {len(PJESA_E.findall(text)):2d} · gerarchia cambiata {g:3d} · CONTENITORE cambiato {k:3d}"
              f" · code tolte {c:2d}"
              + (f" · {d} diversi dal regex vecchio (non toccati)" if d else ""))
        for e in esempi:
            print("     ", e)
    print("\nTOTALE:", json.dumps(tot, ensure_ascii=False))
    if not a.apply and not a.out_dir:
        return 0
    out = []
    for r in rows:
        mod = cambi.get((r["code"], str(r["number"])))
        if mod:
            r = dict(r); r.update(mod)
        out.append(json.dumps(r, ensure_ascii=False))
    chiavi = [list(k) for k in sorted(ricodifica)]
    if a.out_dir:
        od = Path(a.out_dir); od.mkdir(parents=True, exist_ok=True)
        jl, pk = od / "all_articles.jsonl", od / "bm25.pkl"
        jl.write_text("\n".join(out) + "\n", encoding="utf-8")
        ArticleIndex.from_jsonl(jl, lang="sq").save(pk)
        (od / "bm25.pkl.pjesa.json").write_text(json.dumps(chiavi), encoding="utf-8")
        idx = ArticleIndex.load(pk)
        print(f"PROVA in {od}: {len(idx.articles)} nene, {len(chiavi)} articoli cambiati (produzione intatta)")
        return 0
    stamp = time.strftime("%Y%m%d-%H%M%S")
    shutil.copy2(JSONL, JSONL.with_suffix(f".jsonl.bak-{stamp}-pjesa"))
    tmp = JSONL.with_suffix(".jsonl.nuovo")
    tmp.write_text("\n".join(out) + "\n", encoding="utf-8")
    tmp.replace(JSONL)
    shutil.copy2(INDEX_FILE, INDEX_FILE.with_suffix(f".pkl.bak-{stamp}-pjesa"))
    tmpk = INDEX_FILE.with_suffix(".pkl.nuovo")
    ArticleIndex.from_jsonl(JSONL, lang="sq").save(tmpk)
    tmpk.replace(INDEX_FILE)
    INDEX_FILE.with_suffix(".pkl.pjesa.json").write_text(json.dumps(chiavi), encoding="utf-8")
    print(f"APPLICATO: jsonl e {INDEX_FILE.name} riscritti (backup *.bak-{stamp}-pjesa); {len(chiavi)} articoli → "
          f"build_dense.py --rifai {INDEX_FILE.with_suffix('.pkl.pjesa.json').name}, poi riavvio guardato")
    return 0


if __name__ == "__main__":
    sys.exit(main())
