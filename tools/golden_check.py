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
from src.retrieval import DecisionIndex, DECISIONS_INDEX_FILE  # noqa: E402
from src import case_citation_verifier as ccv        # noqa: E402

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

    print("\n[6] Precedentët — çfarë hyri dhe çfarë NUK duhet të kishte hyrë")
    dec = DecisionIndex.load(DECISIONS_INDEX_FILE).decisions
    gjl = [d for d in dec if d.court_code == "gjykata_elarte"]
    korte = {d.court_code for d in dec}
    # 1. asgjë nuk humbi: rindërtimi nga e para lexon Postgres-in, që nga
    #    kontejneri nuk përgjigjet — do t\'i zhdukte 813 pa asnjë gabim
    check("≥1400 precedentë", len(dec) >= 1400, "gjetur %d" % len(dec))
    check("të tri gjykatat të pranishme (Postgres-i nuk u humb)",
          {"kushtetuese", "gjykata_elarte", "ecthr_albania"} <= korte,
          "gjetur %s" % sorted(korte))
    # 2. asnjë mospranim: nuk vendos mbi themelin
    mosk = [d for d in gjl if "mospranim" in (d.dispositif or "").lower()]
    check("asnjë vendim mospranimi te precedentët e rinj", not mosk,
          "gjetur %d" % len(mosk))
    # 3. vetëm arsyetimi i Kolegjit — jo i shkallëve që u prishën
    marker = ("vlerëson", "vlereson", "çmon", "cmon", "arsyeton", "VLERËSIMI")
    te_reja = [d for d in gjl if d.dispositif.startswith("[")]
    keq = [d for d in te_reja
           if not any(m in (d.reasoning or "")[:400] for m in marker)]
    check("arsyetimi nis te 'Kolegji vlerëson' (jo shkallët e prishura)",
          not keq, "%d pa marker" % len(keq))
    # 4. esiti sempre dichiarato
    pa_esit = [d for d in te_reja if not d.dispositif.startswith("[")
               or len(d.dispositif) < 20]
    check("çdo precedent i ri e deklaron si përfundoi", not pa_esit,
          "%d pa përfundim" % len(pa_esit))
    # 5. një vendim i prishur nuk mund të dalë si i lënë në fuqi
    kund = [d for d in te_reja
            if d.dispositif.startswith("[prishje") and d.outcome == "rrëzim"]
    check("një vendim i PRISHUR nuk paraqitet si i konfirmuar", not kund,
          "gjetur %d" % len(kund))
    # 6. dhe dalin vërtet nga kërkimi
    idxd = DecisionIndex.load(DECISIONS_INDEX_FILE)
    gjet = [a for a, _s in idxd.search("vrasje me paramendim", top_k=25)
            if a.court_code == "gjykata_elarte"]
    check("kërkimi i nxjerr precedentët e Gjykatës së Lartë", bool(gjet),
          "asnjë te 25 të parët")

    print("\n[8] Shkronjat brenda nenit — të vërtetat kalojnë, të sajuarat jo")
    # «432/c» = shkronja c) e nenit 432 (shkelje procedurale) — citim krejt i
    # saktë, që dilte "fake" dhe i shfaqej avokatit si nen fantazmë.
    check("neni 432/c KPP → verified (shkronja c) është në tekst)",
          status_of(idx, "neni 432/c i Kodit të Procedurës Penale") == "verified")
    check("neni 432/b KPP → verified",
          status_of(idx, "neni 432/b i Kodit të Procedurës Penale") == "verified")
    # ⚠ dhe në drejtimin tjetër: një shkronjë që NUK ekziston duhet të bjerë
    check("neni 432/z KPP → fake (nuk ka shkronjë z)",
          status_of(idx, "neni 432/z i Kodit të Procedurës Penale") == "fake")
    check("neni 300/z KP → fake (i sajuar)",
          status_of(idx, "neni 300/z i Kodit Penal") == "fake")
    # tre nivele: 149/a ekziston si nen më vete, /2 është paragrafi
    check("Neni 149/a/2 KP → verified (149/a ekziston)",
          status_of(idx, "Neni 149/a/2 i Kodit Penal") == "verified")
    check("neni 149/a KP → verified (nen i shtuar)",
          status_of(idx, "neni 149/a i Kodit Penal") == "verified")
    check("neni 76/2 KP → verified (paragraf numerik)",
          status_of(idx, "neni 76/2 i Kodit Penal") == "verified")
    check("neni 99999 KP → fake (mbetet i rreptë)",
          status_of(idx, "neni 99999 i Kodit Penal") == "fake")
    # ⚠ dhe pa emrin e kodit — ashtu si shkruhet vërtet mes juristëve.
    # Prova e parë kalonte me kodin e shkruar dhe dështonte në realitet.
    check("«neni 432/c» pa emrin e kodit → NUK është fantazmë",
          status_of(idx, "Sipas neni 432/c duhet vepruar.") != "fake")
    check("«neni 432/z» pa emrin e kodit → mbetet fake",
          status_of(idx, "Sipas neni 432/z duhet vepruar.") == "fake")

    print("\n[7] Verifikuesi i vendimeve — numrat e sajuar nuk kalojnë më")
    idxd2 = DecisionIndex.load(DECISIONS_INDEX_FILE)
    vera = next((d for d in idxd2.decisions
                 if d.court_code == "gjykata_elarte"
                 and str(d.number).startswith("00-")), None)
    txt_vera = "Sipas vendimit nr. %s të Gjykatës së Lartë..." % (vera.number if vera else "00-2026-680")
    r1 = ccv.verify_cases(txt_vera, idxd2)
    check("njeh një vendim që e kemi vërtet",
          r1["stats"]["verified"] >= 1, str(r1["stats"]))
    # il numero che aveva scatenato tutto
    r2 = ccv.verify_cases("shih vendimin nr. 00-2025-1760 të Gjykatës së Lartë", idxd2)
    check("nuk konfirmon një numër që s\'e kemi (00-2025-1760)",
          r2["stats"]["unverified"] == 1, str(r2["stats"]))
    # ⚠ e non lo chiama MAI falso: baza jonë nuk i ka të gjitha
    check("nuk e quan KURRË 'fake' — vetëm 'i paverifikuar'",
          all(i["status"] in ("verified", "unverified") for i in r2["items"]),
          str([i["status"] for i in r2["items"]]))
    # l'avviso viaggia col testo, non solo sullo schermo
    md = ccv.annotate_unverified("Përgjigje me vendimin nr. 00-2025-1760.", r2)
    check("paralajmërimi ngjitet te teksti (jo vetëm badge)",
          "00-2025-1760" in md and ("Kujdes" in md or "verifikuar" in md))
    check("thotë qartë se MOSGJETJA nuk do të thotë e rreme",
          "nuk" in md.lower() and "pavërteta" in md.lower(), md[-160:])
    # se tutto è confermato, non aggiunge rumore
    check("nuk shton asgjë kur gjithçka konfirmohet",
          ccv.annotate_unverified(txt_vera, r1) == txt_vera)
    # e non deve scambiare un neni per una sentenza
    r3 = ccv.verify_cases("Neni 76 i Kodit Penal dhe neni 2946 c.c.", idxd2)
    check("nuk ngatërron një nen me një vendim", r3["stats"]["total"] == 0,
          str(r3["stats"]))
    # ⚠ Strukturore: mbrojtja mbulon EDHE bisedën, jo vetëm veglat.
    # Gabimi im: e lidha te `_scudo_citazioni` (19 veglat) dhe e quajta
    # "e mbuluar kudo". Rruga kryesore — përgjigjja e trurit — ka një kopje
    # të vetën të mburojës dhe mbeti jashtë. Asnjë test nuk e pa, sepse asnjë
    # test nuk shikonte KU ishte lidhur.
    try:
        _src = open("/app/src/web.py", encoding="utf-8").read()
        check("mbrojtja e vendimeve lidhet në ≥2 rrugë (vegla + bisedë)",
              _src.count("ccv_mod.verify_cases") >= 2,
              "gjetur %d lidhje" % _src.count("ccv_mod.verify_cases"))
        check("rruga e bisedës e ka mburojën e vendimeve",
              "case citation shield skipped (stream)" in _src)
    except OSError:
        check("burimi i web.py i lexueshëm", False, "nuk u lexua")

    print("\n== Përfundim: %d kaluan, %d dështuan ==" % (PASSES, len(FAILS)))
    if FAILS:
        print("DËSHTIME:", ", ".join(FAILS))
        return 1
    print("\033[32mTË GJITHA GJELBËR — truri i shenjtë i paprekur.\033[0m")
    return 0


if __name__ == "__main__":
    sys.exit(main())
