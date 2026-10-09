"""v9.571 — le RUBRICHE DEL CODICE CIVILE E DEL CODICE DI FAMIGLIA stanno SOPRA «Neni N» nel PDF QBZ («Përgjegjësia solidare ⏎
Neni 626»): l'estrazione le lasciava in coda all'articolo PRECEDENTE (il KC 625 sul danno non patrimoniale finiva con «Përgjegjësia
solidare») e l'articolo vero restava con la «prima frase» come titolo: su 1.175 nene del KC solo 16 avevano una rubrica (le ancore
per titolo li saltano, il blocco mostrava al cervello il titolo sbagliato all'articolo sbagliato). La mappa «Neni N → rubrica che lo
precede» si legge dal TESTO SORGENTE in cache (data/processed/al_text_cache): KC 292, KF 51. Per ciascuna: la rubrica diventa il
titolo del suo articolo («rubrike»), la vecchia «prima frase» torna in testa al corpo, la rubrica esce dalla coda dell'articolo
precedente. Poi `repair_coda_capitoli2.py` (intestazioni di capitolo rimaste in coda) — DOPO, così non cancella la rubrica.
jsonl E pickle, backup, idempotente. Prova su copia: RUBPAR_JSONL / RUBPAR_PKL.
    python3 tools/repair_rubriche_anticipate_al.py [-v] [--apply]   → <pkl>.rubant.json per build_dense.py --rifai"""
import json, os, re, shutil, sys
from datetime import datetime
from pathlib import Path
sys.path.insert(0, "/app")
from src.parser import _paragrafet  # noqa: E402
from src.retrieval import ArticleIndex  # noqa: E402

JSONL = Path(os.environ.get("RUBPAR_JSONL", "/app/data/processed/all_articles.jsonl"))
PKL = Path(os.environ.get("RUBPAR_PKL", "/app/data/index/bm25.pkl"))
CACHE = Path(os.environ.get("AL_TEXT_CACHE", "/app/data/processed/al_text_cache"))
CODICI = ("kodi_civil", "kodi_familjes")
NENI = re.compile(r"^\s*Neni\s+(\d+(?:/\d+)?(?:/[a-zë])?)\s*$")
HIER = re.compile(r"^(?:PJESA|KREU|SEKSIONI|TITULLI|KAPITULLI|Kapitulli|Seksioni|Kreu)\s+([IVXLC]+|\d+)\s*$")


def _titolo(t: str) -> bool:
    """Una riga di rubrica: maiuscola in testa, con minuscole, corta, senza punteggiatura finale; mai un'intestazione di capitolo,
    un sotto-titolo «A. …» o una nota «(Ndryshuar …)»."""
    return (bool(t) and len(t) <= 110 and bool(re.match(r"^[A-ZÇË]", t)) and not re.search(r"[.;:,]\s*$", t) and not HIER.match(t)
            and bool(re.search(r"[a-zëç]", t)) and not re.match(r"^[A-ZÇË]\.\s", t)
            and not re.match(r"^\((?:Ndryshuar|Shtuar|Shfuqizuar)", t))


def mappa_rubriche(testo: str) -> dict:
    """{numero: rubrica} — la riga (o le due righe, se va a capo) subito sopra «Neni N» nel testo sorgente."""
    L = [l.rstrip() for l in testo.splitlines()]
    out = {}
    for i, l in enumerate(L):
        m = NENI.match(l)
        if not m:
            continue
        j = i - 1
        while j >= 0 and not L[j].strip():
            j -= 1
        prev = L[j].strip() if j >= 0 else ""
        k = j - 1
        while k >= 0 and not L[k].strip():
            k -= 1
        pp = L[k].strip() if k >= 0 else ""
        if _titolo(prev):
            out[m.group(1)] = (pp + " " + prev) if (prev[:1].islower() and _titolo(pp)) else prev
        elif prev[:1].islower() and len(prev) <= 60 and not re.search(r"[.;:,]\s*$", prev) and _titolo(pp):
            out[m.group(1)] = pp + " " + prev
    return out


def _togli_coda(body: str, rub: str):
    """Il corpo senza la rubrica in coda (una o due righe); None se il corpo non finisce con la rubrica."""
    righe = (body or "").rstrip().split("\n")
    norm = lambda x: " ".join(x.split())
    for k in (1, 2):
        if len(righe) >= k and norm(" ".join(righe[-k:])) == norm(rub):
            return "\n".join(righe[:-k]).rstrip()
    return None


def main() -> int:
    apply, verbose = "--apply" in sys.argv, "-v" in sys.argv
    rows = [json.loads(l) for l in JSONL.read_text(encoding="utf-8").splitlines() if l.strip()]
    toccati, n_rub, n_coda, salti = {}, 0, 0, []
    for code in CODICI:
        f = CACHE / f"{code}.txt"
        if not f.exists():
            print("manca il testo sorgente", f); continue
        mappa = mappa_rubriche(f.read_text(encoding="utf-8"))
        arts = [r for r in rows if r.get("code") == code]
        pos = {str(r["number"]): i for i, r in enumerate(arts)}
        for n, rub in mappa.items():
            i = pos.get(n)
            if i is None:
                salti.append((code, n, "assente")); continue
            d = arts[i]
            if i > 0:                                         # la rubrica esce dalla coda dell'articolo precedente
                p = arts[i - 1]
                nuovo = _togli_coda(p.get("body") or "", rub)
                if nuovo is not None:
                    p["body"], p["paragrafet"] = nuovo, _paragrafet(nuovo if nuovo else p.get("heading") or "")
                    toccati[(code, str(p["number"]))] = p; n_coda += 1
            if d.get("repealed"):
                salti.append((code, n, "abrogato")); continue
            if d.get("heading_kind") == "rubrike":
                if " ".join((d.get("heading") or "").split()) != " ".join(rub.split()):
                    salti.append((code, n, f"ha già la rubrica «{(d.get('heading') or '')[:40]}»"))
                continue
            vecchia = (d.get("heading") or "").strip()
            corpo = (vecchia + ("\n" + d["body"] if (d.get("body") or "").strip() else "")).strip()
            d["heading"], d["body"], d["heading_kind"], d["paragrafet"] = rub, corpo, "rubrike", _paragrafet(corpo)
            toccati[(code, n)] = d; n_rub += 1
            if verbose:
                print(f"{code} {n}: «{rub}» | corpo: {' '.join(corpo.split())[:90]}")
    print(f"rubriche spostate {n_rub} · tolte dalla coda del precedente {n_coda} · articoli toccati {len(toccati)} · saltati {len(salti)}")
    for s in salti[:20]:
        print("  saltato", s)
    if not apply or not toccati:
        return 0
    stamp = datetime.now().strftime("%Y%m%d-%H%M")
    shutil.copy2(JSONL, str(JSONL) + f".bak-{stamp}-rubant")
    JSONL.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n", encoding="utf-8")
    idx = ArticleIndex.load(PKL)
    shutil.copy2(PKL, str(PKL) + f".bak-{stamp}-rubant")
    for a in idx.articles:
        d = toccati.get((a.code, str(a.number)))
        if d is not None:
            a.heading, a.body, a.heading_kind, a.paragrafet = d["heading"], d["body"], d.get("heading_kind", a.heading_kind), d["paragrafet"]
    ArticleIndex.build(list(idx.articles), lang="sq", stem=bool(getattr(idx, "stem", False)),
                       fold=bool(getattr(idx, "fold", True))).save(PKL)
    Path(str(PKL) + ".rubant.json").write_text(json.dumps([list(k) for k in toccati], ensure_ascii=False), encoding="utf-8")
    print("FATTO", len(toccati))
    return 0


if __name__ == "__main__":
    sys.exit(main())
