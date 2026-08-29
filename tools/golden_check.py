#!/usr/bin/env python3
"""Set aureo — golden regression harness for the sacred brain (Step 4B).

Deterministic, LLM-FREE checks that run in seconds and catch the regressions we
have actually hit: corpus gaps, citation-verifier misclassifications, and
retrieval stem bugs. Run after every build:

    docker exec super-avvocato python3 tools/golden_check.py

Exit code 0 = all green; 1 = at least one regression. Extend GOLDENS freely.
"""
import sys
sys.path.insert(0, "/app")

from src.retrieval import ArticleIndex           # noqa: E402
from src import citation_verifier as cv           # noqa: E402
from src import expertise as ex                   # noqa: E402
from src import brain                             # noqa: E402
from src.retrieval import INDEX_FILE              # noqa: E402

FAILS = []
PASSES = 0


def check(name, cond, detail=""):
    global PASSES
    if cond:
        PASSES += 1
        print("  \033[32m✓\033[0m %s" % name)
    else:
        FAILS.append(name)
        print("  \033[31m✗ %s\033[0m %s" % (name, ("— " + detail) if detail else ""))


def has_article(idx, code, number):
    return any(a.code == code and a.number == number for a in idx.articles)


def status_of(idx, text):
    items = cv.verify_text(text, idx)["items"]
    return items[0]["status"] if items else "none"


def retrieved(idx, query, seed=None):
    arts = ex.retrieve_grounded(None, idx, query, seed_pairs=seed)
    return {(c, n) for c, n, _t in arts}


def scanned(idx, term):
    # deterministic heading-scan (LLM-free) — this is where the stem/diacritic
    # bug lived; retrieve_grounded's term-expansion needs the LLM so we test the
    # scanner directly.
    return {(c, n) for c, n, _h in ex._heading_scan(idx, term)}


def ancorato(idx, query, aree, chiave):
    """L'articolo entra nei dodici che vede il cervello?

    Ricostruisce la stessa fusione BM25 di `brain._retrieve` e poi applica le
    ancore: cosi' la prova misura il comportamento vero, non una scorciatoia.
    """
    seen = {}
    for art, sc in idx.search(query, top_k=12):
        k = (art.code, art.number)
        if sc > seen.get(k, 0.0):
            seen[k] = sc
    per_k = {(a.code, a.number): a for a in idx.articles}
    pairs = sorted([(per_k[k], v) for k, v in seen.items() if k in per_k],
                   key=lambda x: x[1], reverse=True)
    finali = brain._applica_ancore(pairs, idx, [query], aree)[:12]
    return chiave in {(a.code, a.number) for a, _ in finali}


def main():
    print("== Set aureo — golden regression ==")
    idx = ArticleIndex.load()
    codes = {}
    for a in idx.articles:
        codes[a.code] = codes.get(a.code, 0) + 1

    print("\n[1] Integriteti i korpusit")
    check("≥6000 nene në korpus", len(idx.articles) >= 6000, "gjetur %d" % len(idx.articles))
    check("≥21 kode", len(codes) >= 21, "gjetur %d" % len(codes))
    for code, num in [("kodi_penal", "76"), ("kodi_penal", "134"), ("kodi_penal", "139"),
                      ("kodi_proc_penale", "244"), ("kodi_proc_penale", "258"),
                      ("kodi_proc_penale", "323"), ("kodi_civil", "124"),
                      ("ligji_policia_2024", "4")]:
        check("ekziston %s neni %s" % (code, num), has_article(idx, code, num))

    print("\n[2] Verifikuar — klasifikimi i citimeve")
    check("neni real KP 76 → verified", status_of(idx, "neni 76 i Kodit Penal") == "verified")
    check("neni fantazmë KP 99999 → fake", status_of(idx, "neni 99999 i Kodit Penal") == "fake")
    check("neni 4 i Ligjit për Policinë → verified (82/2024)",
          status_of(idx, "neni 4 i Ligjit për Policinë e Shtetit") == "verified")
    # freshness fields present in the payload
    _st = cv.verify_text("neni 76 i Kodit Penal", idx)
    check("stats ka fushën 'stale'", "stale" in _st.get("stats", {}))
    check("citimi ka fushën 'volatility'", "volatility" in (_st["items"][0] if _st["items"] else {}))

    print("\n[3] Retrieval — heading-scan i qëndrueshëm (bug-et historike të stem/theksit)")
    check("heading-scan 'vjedhje' → KP 134 (stem 5-shkronjësh)",
          ("kodi_penal", "134") in scanned(idx, "vjedhje"))
    check("heading-scan 'plagosje' → KP 88",
          ("kodi_penal", "88") in scanned(idx, "plagosje"))
    check("heading-scan 'trashegimia' (pa theks) → KC 316 (diacritic-fold)",
          ("kodi_civil", "316") in scanned(idx, "trashegimia"))
    check("seed pairs respektohen (KP 66 për parashkrim)",
          ("kodi_penal", "66") in retrieved(idx, "parashkrim", seed=[("kodi_penal", "66")]))

    print("\n[4] Ancore — rregulli i përgjithshëm nuk humbet nga përjashtimet")
    K114 = ("kodi_civil", "114")
    check("ekziston KC 114 (parashkrimi i zakonshëm)", has_article(idx, *K114))
    # Il difetto misurato: senza ancora non entrava nei dodici con NESSUNA
    # delle formulazioni normali della domanda.
    check("KC 114 hyn te 12 nenet — pyetje civile për parashkrimin",
          ancorato(idx, "afati i parashkrimit të zakonshëm", ["Civil"], K114))
    check("KC 114 hyn edhe pa 'areas' nga triazhi",
          ancorato(idx, "sa është afati i parashkrimit", [], K114))
    # Le due che contano di piu': l'ancora deve tacere.
    check("KC 114 NUK hyn në pyetje penale (do të ishte këshillë e gabuar)",
          not ancorato(idx, "parashkrimi i ndjekjes penale", ["Penal"], K114))
    check("KC 114 NUK hyn në pyetje pa lidhje me parashkrimin",
          not ancorato(idx, "si bëhet divorci me marrëveshje", ["Familje"], K114))

    print("\n[5] Korpusi italian — rregulli i përgjithshëm del vetë")
    _it = INDEX_FILE.parent / "bm25_it.pkl"
    if _it.exists():
        idx_it = ArticleIndex.load(_it)
        top = {(a.code, a.number) for a, _ in
               idx_it.search("qual è il termine di prescrizione ordinaria", top_k=6)}
        # Qui NON c'è nessuna ancora di proposito: esce da solo. Questa prova
        # esiste perché il giorno in cui smettesse, nessuno se ne accorgerebbe.
        check("art. 2946 c.c. del vetë te 6 të parët (pa ankorim)",
              ("codice_civile", "2946") in top)
    else:
        check("korpusi italian i pranishëm", False, "bm25_it.pkl mungon")

    print("\n== Përfundim: %d kaluan, %d dështuan ==" % (PASSES, len(FAILS)))
    if FAILS:
        print("DËSHTIME:", ", ".join(FAILS))
        return 1
    print("\033[32mTË GJITHA GJELBËR — truri i shenjtë i paprekur.\033[0m")
    return 0


if __name__ == "__main__":
    sys.exit(main())
