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

    print("\n[10] Kafazi i trurit — nuk lexon dot kodin as bazën e të dhënave")
    _bk = open("/app/src/backends.py", encoding="utf-8").read()
    # 1. asnjë bypass: ai i heq të gjithë kufijtë e sistemit të skedarëve
    check("asnjë '--permission-mode' nuk i jepet CLI-së",
          '"--permission-mode"' not in _bk,
          "u gjet — bypass-i i rihap të gjitha")
    # 2. truri NUK niset nga /app: dosja e punës lexohet gjithnjë
    check("truri nuk niset nga ROOT (/app)", "cwd=str(ROOT)" not in _bk,
          "u gjet cwd=ROOT — src/ dhe app.db bëhen të lexueshme")
    check("truri niset nga një dosje e veçuar", "_CWD_CERVELLO" in _bk)
    # 3. Read i kufizuar te dosjet e bashkëngjitjeve, jo i zhveshur
    check("Read është i kufizuar me shteg, jo i zhveshur",
          'Read({d}/**)' in _bk or 'Read(%s/**)' in _bk or "Read({extra_dir}/**)" in _bk,
          "Read pa shteg = pa kufi")

    print("\n[9] Truri — modeli i deklaruar është ai që përgjigjet vërtet")
    from src import config as _cfg   # noqa: E402
    check("truri kryesor = Opus 5", "opus-5" in (_cfg.CLAUDE_CODE_MODEL or ""),
          _cfg.CLAUDE_CODE_MODEL)
    check("effort = max", (_cfg.CLAUDE_CODE_EFFORT or "") == "max",
          _cfg.CLAUDE_CODE_EFFORT)
    check("ndihmësit = Sonnet 5", "sonnet-5" in (_cfg.CLAUDE_CODE_MEDIUM_MODEL or ""),
          _cfg.CLAUDE_CODE_MEDIUM_MODEL)
    # ⚠ il provenance pack certifica COME è stata prodotta una risposta:
    # se dichiara un modello diverso da quello che risponde, mente.
    check("provenance-i deklaron të njëjtin model si CLI-ja",
          _cfg.CLAUDE_MODEL == _cfg.CLAUDE_CODE_MODEL,
          "%s vs %s" % (_cfg.CLAUDE_MODEL, _cfg.CLAUDE_CODE_MODEL))

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

    # ── [10] dokumentet ligjore: faqja publike i tregon te plote ────────
    # Renderi i faqes publike mbulon vetem 8 ndertime. Nese dikush shkruan
    # nje ndertim tjeter, brenda aplikacionit duket mire dhe NE FAQEN PUBLIKE
    # humbet — pikerisht atje ku lexon kush nuk eshte ende klient.
    import glob as _glob, io as _io, os as _os, re as _re
    _rrenja = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))
    _lg = _os.path.join(_rrenja, "legal")
    _pub = sorted(_glob.glob(_os.path.join(_lg, "condizioni_*.md"))
                  + _glob.glob(_os.path.join(_lg, "privacy_*.md"))
                  + _glob.glob(_os.path.join(_lg, "dpa_*.md")))
    check("ligjore: 6 dokumentet publike ekzistojne", len(_pub) == 6,
          "u gjeten %d" % len(_pub))

    _pambuluar = [
        (r"\[[^\]]+\]\([^)]+\)", "link"),
        (r"```", "bllok kodi"),
        (r"(?<![\w`])`[^`\n]+`(?![\w`])", "kod inline"),
        (r"<[a-zA-Z/]", "HTML i papershtatur"),
    ]
    for _f in _pub:
        _t = _io.open(_f, encoding="utf-8").read()
        _n = _os.path.basename(_f)
        for _pat, _et in _pambuluar:
            _g = _re.search(_pat, _t, _re.M)
            check("ligjore: %s pa %s" % (_n, _et), not _g,
                  "u gjet: %r" % (_g.group(0)[:40] if _g else ""))
        check("ligjore: %s ka ** te balancuara" % _n, _t.count("**") % 2 == 0,
              "%d shenja **" % _t.count("**"))
        # una tabella senza riga di separazione perde l'intestazione
        _righe = [r for r in _t.split("\n") if r.lstrip().startswith("|")]
        if _righe:
            _sep = [r for r in _righe if set(r.replace("|", "").strip()) <= set("-: ")
                    and r.strip()]
            check("ligjore: %s tabelat kane rreshtin ndares" % _n, bool(_sep),
                  "asnje rresht |---|")

    try:
        _w = _io.open(_os.path.join(_rrenja, "src", "web.py"), encoding="utf-8").read()
    except OSError:
        _w = ""
    check("ligjore: renderi ekziston", "_legal_md_to_html" in _w)
    check("ligjore: rruga publike e perdor renderin",
          _w.count("_legal_md_to_html") >= 2, "i percaktuar por i pathirrur")
    # la pagina pubblica DEVE restare senza login: e' tutto il suo scopo
    _blok = _w.split('@app.get("/legale")')[1].split("\ndef ")[0] if '@app.get("/legale")' in _w else "X"
    check("ligjore: faqja publike pa login", "login_required" not in _blok)
    # e i documenti INTERNI non devono uscire da nessuna delle due strade
    check("ligjore: dokumentet e brendshme nuk sherbehen",
          "interno_" not in _w, "nje rruge permend interno_")


    # ── [11] video si provave: rruga te mos prishet ne heshtje ─────────
    import io as _io2, os as _os2, re as _re2
    _rr = _os2.path.dirname(_os2.path.dirname(_os2.path.abspath(__file__)))
    try:
        from src.config import (VIDEO_EXTENSIONS as _VE, MAX_VIDEO_SIZE_MB as _MV,
                                MAX_UPLOAD_SIZE_MB as _MU, VIDEO_MAX_FRAMES as _VF)
        from src import video as _vid
    except Exception as _e:
        check("video: moduli importohet", False, str(_e))
        _VE, _MV, _MU, _VF, _vid = set(), 0, 0, 0, None

    check("video: formatet e pranuara >= 10", len(_VE) >= 10, "u gjeten %d" % len(_VE))
    check("video: .dav (Dahua) pranohet", ".dav" in _VE)
    check("video: .mp4/.mov/.avi pranohen",
          {".mp4", ".mov", ".avi"} <= set(_VE))
    # ⚠️ Dy pragje TE NDRYSHME: 25 MB akt, 500 MB video. Te barabarta do te
    # thote qe dikush i ka "thjeshtuar" — dhe ose videot nuk kalojne me, ose
    # pranojme PDF gjysme-gigabajt.
    check("video: pragu i vet, i ndryshem nga dokumentet", _MV > _MU,
          "video %s MB vs dokument %s MB" % (_MV, _MU))
    check("video: tavan fotogramash i arsyeshem", 6 <= _VF <= 60, "%s" % _VF)

    if _vid is not None:
        check("video: is_video ndan videon nga dokumenti",
              _vid.is_video(".mp4") and not _vid.is_video(".pdf"))
        # ⚠️ Verejtjet duhet te ekzistojne NE TE DYJA gjuhet me te njejtat celesa:
        # difekti i gjetur nga prova e vertete ishte pikerisht ky — titujt ne
        # shqip dhe verejtjet ne italisht, brenda te njejtit dokument.
        try:
            _sq = set(_vid._RILIEVI["sq"]); _it = set(_vid._RILIEVI["it"])
            check("video: verejtjet ne te dyja gjuhet, te njejtat celesa",
                  _sq == _it and len(_sq) >= 6,
                  "sq=%d it=%d, ndryshim=%s" % (len(_sq), len(_it), _sq ^ _it))
        except Exception as _e:
            check("video: verejtjet dygjuhesore", False, str(_e))
        # nuk identifikon persona: kufiri qe e mban produktin brenda AI Act
        _p = (_vid._PROMPT_FOTOGRAMMA_SQ + _vid._PROMPT_FOTOGRAMMA_IT
              + _vid._CONFRONTO_SQ + _vid._CONFRONTO_IT)
        check("video: promptet ndalojne identifikimin e personave",
              ("MOS identifiko" in _p) and ("NON identificare" in _p))
        # ë/ç piegate come fa _norm(): senza, "fajësinë" non combacia mai
        _pn = _p.lower().replace("ë", "e").replace("ç", "c")
        check("video: promptet ndalojne perfundimin per fajesine/fajin",
              ("faj" in _pn) and ("colpevolezza" in _pn or "colpa" in _pn),
              "faj=%s colpa=%s" % ("faj" in _pn, "colpa" in _pn))
        # kufiri i deklaruar brenda tekstit qe lexon avokati
        for _g, _fjale in (("sq", "KUFIJTË"), ("it", "LIMITI")):
            check("video: kufiri i deklaruar ne %s" % _g,
                  _fjale in _vid._INTESTAZIONE[_g]["kufi"])

    # ⚠️ Formatet duhet te perputhen ne TRE vende: config, `accept` i HTML-se
    # dhe regex-i i shfletuesit. Nese ndryshojne, nje format i pranuar nga
    # serveri del gri ne dritaren e zgjedhjes ose "shume i madh" ne shfletues:
    # difekt i padukshem per ate qe shkruan kodin, i qarte per ate qe e perdor.
    try:
        _js = _io2.open(_os2.path.join(_rr, "static", "app.js"), encoding="utf-8").read()
        _m = _re2.search(r"VIDEO_EXT\s*=\s*/\\\.\(([^)]+)\)", _js)
        _nel_js = set("." + x for x in (_m.group(1).split("|") if _m else []))
        check("video: shfletuesi njeh te njejtat formate",
              _nel_js and _nel_js == set(_VE),
              "vetem ne server: %s | vetem ne shfletues: %s"
              % (sorted(set(_VE) - _nel_js), sorted(_nel_js - set(_VE))))
        check("video: shfletuesi ka prag te vetin per videot",
              "MAX_VIDEO" in _js, "nje prag i vetem 25 MB do t'i ndalonte videot")
        check("video: paneli ekziston", "openVideo" in _js)
    except OSError as _e:
        check("video: app.js i lexueshem", False, str(_e))

    try:
        _h = _io2.open(_os2.path.join(_rr, "templates", "index.html"),
                       encoding="utf-8").read()
        check("video: zeri ne menune PRO", 'data-pro="video"' in _h)
    except OSError:
        check("video: index.html i lexueshem", False)

    try:
        _w2 = _io2.open(_os2.path.join(_rr, "src", "web.py"), encoding="utf-8").read()
        check("video: rruget e reja ekzistojne",
              "/videos" in _w2 and "/video/compare" in _w2)
        # ngarkimi i videove NUK kalon nga memoria
        check("video: ngarkimi shkruhet ne disk (jo ne memorie)",
              "f.save(str(storage_path))" in _w2,
              "500 MB ne RAM per cdo ngarkim")
    except OSError:
        check("video: web.py i lexueshem", False)


    # ── [12] audio si prove ───────────────────────────────────────────
    try:
        from src.config import (AUDIO_EXTENSIONS as _AE, MAX_AUDIO_SIZE_MB as _MA,
                                WHISPER_MODEL as _WM, WHISPER_THREADS as _WT)
        from src import audio as _aud
    except Exception as _e:
        check("audio: moduli importohet", False, str(_e))
        _AE, _MA, _WM, _WT, _aud = set(), 0, "", 0, None

    check("audio: formatet e pranuara >= 8", len(_AE) >= 8, "%d" % len(_AE))
    check("audio: mp3/m4a/wav/amr pranohen",
          {".mp3", ".m4a", ".wav", ".amr"} <= set(_AE))
    check("audio: pragu i vet (midis dokumentit dhe videos)",
          0 < _MA < 500, "%s MB" % _MA)
    # meta makine, jo e gjitha: siper ka edhe pese site te tjere
    check("audio: threads te kufizuara", 1 <= _WT <= 4, "%s" % _WT)

    if _aud is not None:
        check("audio: is_audio ndan audion nga videoja",
              _aud.is_audio(".mp3") and not _aud.is_audio(".mp4"))
        # ⚠️ KONTROLLI ME I RENDESISHEM I KETIJ SEKSIONI.
        # Gjuha duhet te NJIHET, jo te imponohet nga sesioni. Difekti u kap nga
        # prova e vertete: nje deklarate italisht, e transkriptuar duke imponuar
        # shqipen, doli "una giakka skura ... kvalkosa im mano" — fonetika
        # italiane e shkruar me drejtshkrim shqip. E gabuar DHE e besueshme.
        import inspect as _insp
        try:
            _src_a = _insp.getsource(_aud.analizza)
            check("audio: gjuha NJIHET, nuk imponohet nga sesioni",
                  "trascrivi(path, None)" in _src_a,
                  "duket sikur gjuha po imponohet perseri")
            check("audio: gjuha e njohur DEKLAROHET ne tekst",
                  '_NOMI_LINGUA' in _insp.getsource(_aud) or "lingua" in _src_a)
        except Exception as _e:
            check("audio: burimi i lexueshem", False, str(_e))
        # nje transkriptim ne te njejten kohe: CPU-ja ndahet me pese site te tjere
        check("audio: nje transkriptim ne te njejten kohe",
              getattr(_aud, "_semaforo", None) is not None
              and _aud._semaforo._value <= 1)
        # avvertimento "bozza, non verbale" ne te dyja gjuhet
        for _g in ("sq", "it"):
            _av = _aud._INTESTAZIONE[_g].get("avviso", "")
            check("audio: paralajmerimi 'boze, jo procesverbal' ne %s" % _g,
                  ("BOZ" in _av.upper()) or ("BOZZ" in _av.upper()))

    try:
        _js2 = _io2.open(_os2.path.join(_rr, "static", "app.js"), encoding="utf-8").read()
        _m2 = _re2.search(r"AUDIO_EXT\s*=\s*/\\\.\(([^)]+)\)", _js2)
        _nel_js2 = set("." + x for x in (_m2.group(1).split("|") if _m2 else []))
        check("audio: shfletuesi njeh te njejtat formate",
              _nel_js2 and _nel_js2 == set(_AE),
              "vetem server: %s | vetem shfletues: %s"
              % (sorted(set(_AE) - _nel_js2), sorted(_nel_js2 - set(_AE))))
        check("audio: shfletuesi ka prag te vetin",
              "MAX_AUDIO" in _js2)
    except OSError:
        check("audio: app.js i lexueshem", False)


    # ── selezionatori di file: i multimediali dove servono, e solo li ──
    try:
        _js3 = _io2.open(_os2.path.join(_rr, "static", "app.js"), encoding="utf-8").read()
        _h3 = _io2.open(_os2.path.join(_rr, "templates", "index.html"), encoding="utf-8").read()
        # 1) il caricamento nel fashikull DEVE accettarli
        _dos = _re2.search(r'id="dossier-input"[^>]*accept="([^"]*)"', _h3)
        check("zgjedhesit e skedareve: dossier-input pranon video/audio",
              bool(_dos) and ".mp4" in _dos.group(1) and ".mp3" in _dos.group(1),
              "pa kete, mp4-at duken gri ne dritaren e zgjedhjes")
        _fk = _re2.search(r'class="fk-file" accept="([^"]*)"', _js3)
        check("zgjedhesit e skedareve: fk-file pranon video/audio",
              bool(_fk) and ".mp4" in _fk.group(1))
        # 2) gli allegati degli STRUMENTI non devono: il cervello legge PDF e
        #    immagini col tool Read, un mp4 non lo apre — sceglierlo
        #    significherebbe fallire in silenzio
        _con = [m.group(1) for m in
                _re2.finditer(r'class="([a-z-]+)-file" accept="([^"]*)"', _js3)
                if ".mp4" in m.group(2)]
        check("zgjedhesit e skedareve: vetem 2 pranojne video (vd, fk)",
              sorted(_con) == ["fk", "vd"],
              "gjetur: %s" % sorted(_con))
    except OSError:
        check("zgjedhesit e skedareve: skedaret e lexueshem", False)


    # ── [13] javascript inline: e' codice morto sotto la CSP ───────────
    import glob as _g3
    _tmpl = [f for f in _g3.glob(_os2.path.join(_rr, "templates", "*.html"))
             if "bak" not in _os2.path.basename(f)]
    check("csp: ka template per te kontrolluar", len(_tmpl) >= 5, "%d" % len(_tmpl))
    for _f in sorted(_tmpl):
        _n = _os2.path.basename(_f)
        _t = _io2.open(_f, encoding="utf-8").read()
        # <script> senza src ed eseguibile (application/ld+json non eshte kod)
        _inline = _re2.findall(r"<script(?![^>]*\bsrc=)(?![^>]*type=[\"']application/)[^>]*>", _t)
        check("csp: %s pa javascript inline" % _n, not _inline,
              "%d blloqe — CSP i bllokon NE HESHTJE" % len(_inline))
        # attributi on* : bllokohen njesoj
        _on = _re2.findall(r"\son(?:click|change|submit|input|load)\s*=", _t)
        check("csp: %s pa atribute on*" % _n, not _on, "%d" % len(_on))
        # nje skedar i njejte i ngarkuar dy here => cdo degjues dy here =>
        # klikimi kryhet dhe zhbehet: duket sikur butoni nuk pergjigjet
        _src = _re2.findall(r'<script src="(/static/[^"?]+)', _t)
        _dopio = {x for x in _src if _src.count(x) > 1}
        check("csp: %s pa skedare te dyfishuar" % _n, not _dopio, "%s" % _dopio)

    # la CSP non deve essere indebolita per far funzionare l'inline
    try:
        _cfg = _io2.open("/etc/nginx/sites-available/superavokati.ai",
                         encoding="utf-8").read()
        if "Content-Security-Policy" in _cfg:
            _riga = [l for l in _cfg.split("\n") if "Content-Security-Policy" in l][0]
            check("csp: script-src pa 'unsafe-inline'",
                  "'unsafe-inline'" not in _riga.split("script-src")[1].split(";")[0]
                  if "script-src" in _riga else True,
                  "dobesimi i CSP nuk eshte rregullimi i duhur")
    except (OSError, IndexError):
        pass   # dentro il container non c'e' nginx: non e' un fallimento


    # ── hyrja: butoni "Hyr" duhet te kete ende kodin e vet ─────────────
    # Formulari nuk ka as `action` as `method`: pa kete JavaScript, klikimi
    # nuk ben ASGJE — pa gabim, pa mesazh. Ka ndodhur me 31 gusht, duke
    # mbishkruar skedarin gjate nxjerrjes se skripteve inline.
    try:
        _lj = _io2.open(_os2.path.join(_rr, "static", "login.js"), encoding="utf-8").read()
        check("hyrja: login.js ka trajtuesin e formularit",
              'getElementById("login-form")' in _lj or "getElementById('login-form')" in _lj,
              "pa te, butoni 'Hyr' nuk ben asgje")
        check("hyrja: login.js therret /api/login", "/api/login" in _lj)
        # gli altri pezzi che vivono nello stesso file
        for _k, _perse in (("toggle-pw", "syri i fjalekalimit"),
                           ("ll-btn", "butonat e gjuhes"),
                           ("forgot-form", "rikuperimi i fjalekalimit")):
            check("hyrja: login.js ka %s (%s)" % (_k, _perse), _k in _lj)
        _lh = _io2.open(_os2.path.join(_rr, "templates", "login.html"),
                        encoding="utf-8").read()
        # il tag deve esserci UNA volta e con la versione, o il browser
        # continua a servire il file vecchio dopo una correzione
        _tag = _re2.findall(r'<script src="/static/login\.js([^"]*)"', _lh)
        check("hyrja: login.js i lidhur nje here e vetme", len(_tag) == 1,
              "%d here" % len(_tag))
        check("hyrja: login.js ka numer versioni",
              bool(_tag) and "?v=" in _tag[0],
              "pa te, shfletuesi sherben skedarin e vjeter")
    except OSError as _e:
        check("hyrja: skedaret e lexueshem", False, str(_e))


    # ── ripolling i dokumenteve: mos u dorezo para se videoja te mbaroje ─
    # Ishte 90 tentativa x 4s = GJASHTE minuta, te matura per nje dokument.
    # Nje video merr dhjete-njezet: puna mbaronte, paneli mbetej "po
    # analizohet" pergjithmone — dhe dorezohej NE HESHTJE.
    try:
        _aj = _io2.open(_os2.path.join(_rr, "static", "app.js"), encoding="utf-8").read()
        _m = _re2.search(r"MAX_TENTATIVI\s*=\s*([0-9+ *]+);", _aj)
        _val = eval(_m.group(1)) if _m else 0            # nje shprehje e thjeshte
        check("ripolling: mbulon te pakten 30 minuta", _val >= 200,
              "%s tentativa — nje video merr me shume" % _val)
        check("ripolling: pret me gjate pas minutes se pare",
              "function attesa(" in _aj, "pa kete, 40 min me 4s = 600 kerkesa")
        check("ripolling: kur dorezohet, E THOTE",
              "_dossierRinuncia" in _aj,
              "nje rrote qe rrotullohet pergjithmone genjen")
    except OSError:
        check("ripolling: app.js i lexueshem", False)


    # ── [14] impalcatura forense (SWGDE) ───────────────────────────────
    try:
        from src import forensics as _fx
        import inspect as _in2
        _vsrc = _io2.open(_os2.path.join(_rr, "src", "video.py"), encoding="utf-8").read()

        # 1) integriteti: gjurma SHA-256 e skedarit
        check("forense: llogaritet gjurma SHA-256",
              hasattr(_fx, "impronta") and "impronta(path)" in _vsrc,
              "pa gjurme, analiza flet per nje skedar qe askush nuk e identifikon")
        # 2) riprodhueshmeria: regjistri i perpunimit
        check("forense: regjistri i perpunimit ekziston",
              hasattr(_fx, "Registro") and "blocco_registro" in _vsrc)
        check("forense: regjistri shkruan parametrat e vertete",
              "gt(scene," in _vsrc and "showinfo" in _vsrc,
              "parametrat duhet te jene ata realet, jo te pergjithshem")
        # 3) ndarja: matje vs interpretim
        for _g in ("sq", "it"):
            _e = _fx and None
        import src.video as _vv
        for _g in ("sq", "it"):
            _et = _vv._INTESTAZIONE[_g]
            check("forense: [%s] ndarje matje/interpretim" % _g,
                  "rilevato" in _et and "interpretato" in _et)
        # 4) deklarimet qe na mbrojne DHE i ndihmojne
        for _g, _fj in (("sq", "nuk identifikon persona"),
                        ("it", "non identifica persone")):
            check("forense: [%s] deklarohet mos-identifikimi" % _g,
                  _fj in _fx._REG[_g]["limite"])
        # ⚠️ ë/ç piegate PRIMA di confrontare: «nuk përmirëson» non combacia
        # mai con «permireson». Vale per ogni confronto letterale sullo shqip.
        def _piega(t):
            return t.lower().replace("ë", "e").replace("ç", "c")
        for _g, _fj in (("sq", "nuk permireson"), ("it", "non migliora")):
            check("forense: [%s] deklarohet mos-permiresimi" % _g,
                  _fj in _piega(_fx._REG[_g]["limite"]),
                  "permiresimi i bere keq shton informacion qe nuk kishte")
        # 5) rilievi del contenitore in due lingue, stesse chiavi
        check("forense: verejtjet e kontejnerit ne te dyja gjuhet",
              set(_fx._TESTI["sq"]) == set(_fx._TESTI["it"]))
        # 6) motori i pershkrimit nuk emertohet me modelin
        _tutto = " ".join(_fx._REG[g]["limite"] for g in ("sq", "it"))
        check("forense: motori quhet Tetramorph, jo modeli",
              "Tetramorph" in _tutto
              and not any(x in _tutto.lower() for x in ("claude", "gpt", "opus", "sonnet")))
    except Exception as _e:
        check("forense: moduli i lexueshem", False, str(_e))


    # ── frazat e regjistrit: te dyja gjuhet, te njejtat celesa ─────────
    # Gabim i perseritur TRE here ne dy dite: teksti i ri lind vetem ne
    # italisht dhe del ne nje dokument shqip. Kontrolli kushton me pak se
    # vemendja.
    try:
        check("forense: hapat e regjistrit ne te dyja gjuhet",
              set(_fx.PASSI["sq"]) == set(_fx.PASSI["it"]),
              "ndryshim: %s" % (set(_fx.PASSI["sq"]) ^ set(_fx.PASSI["it"])))
        # nessuna frase albanese deve essere identica all'italiana: vorrebbe
        # dire che e' stata copiata e non tradotta
        _uguali = [k for k in _fx.PASSI["sq"]
                   if _fx.PASSI["sq"][k] == _fx.PASSI["it"][k]
                   and not _fx.PASSI["sq"][k].startswith("Tetramorph")]
        check("forense: nessuna frase copiata invece che tradotta",
              not _uguali, "identiche: %s" % _uguali)
        # i segnaposto devono coincidere, o il testo tradotto esplode
        import re as _re4
        _diff = [k for k in _fx.PASSI["sq"]
                 if set(_re4.findall(r"\{(\w+)\}", _fx.PASSI["sq"][k]))
                 != set(_re4.findall(r"\{(\w+)\}", _fx.PASSI["it"][k]))]
        check("forense: gli stessi segnaposto nelle due lingue",
              not _diff, "diversi in: %s" % _diff)
    except Exception as _e:
        check("forense: tabella dei passi leggibile", False, str(_e))


    # ── [15] parkimi i pergjigjeve te gjata (telefoni qe bie) ──────────
    try:
        _w5 = _io2.open(_os2.path.join(_rr, "src", "web.py"), encoding="utf-8").read()
        _a5 = _io2.open(_os2.path.join(_rr, "static", "app.js"), encoding="utf-8").read()

        # server: il magazzino, l'aggancio e la rotta per riprendersela
        check("parkimi: magazina ekziston", "_PARCHEGGIO" in _w5)
        check("parkimi: lidhet me after_request",
              "_parcheggia_risposta" in _w5 and "X-Job-Key" in _w5)
        check("parkimi: rruga per ta marre", "/api/tool/result" in _w5)
        # ⚠️ i lidhur me perdoruesin: nje fashikull nuk del nga nje sesion tjeter
        check("parkimi: i lidhur me perdoruesin",
              "proprietario != uid" in _w5,
              "pa kete, kush gjen celesin merr pergjigjen e nje studioje tjeter")
        # ha un tetto e una scadenza: e' memoria, non un archivio
        check("parkimi: ka tavan dhe skadence",
              "_PARCHEGGIO_MAX" in _w5 and "_PARCHEGGIO_TTL" in _w5)

        # client: manda la chiave, la ricorda, la ripesca
        check("parkimi: klienti dergon celesin",
              '"X-Job-Key": chiave' in _a5)
        check("parkimi: klienti e ripeshkon", "_ripescaRisposta" in _a5)
        # ⚠️ in localStorage: su Android la scheda a volte viene UCCISA, e al
        # ritorno la pagina riparte da zero — senza questo non si trova nulla
        check("parkimi: celesi mbahet edhe pas rinisjes se faqes",
              "localStorage.setItem(_PARCHEGGIO_CHIAVE" in _a5,
              "pa kete, nje skede e vrare humbet pergjigjen perfundimisht")
        check("parkimi: rikuperimi ne nisje", "_recuperaLavoroInSospeso" in _a5)
    except OSError as _e:
        check("parkimi: skedaret e lexueshem", False, str(_e))


    # ── [16] titujt: perkthimi te mos sakatoje fjale ───────────────────
    # «Pyet Avokatin e Djallit» dilte «Pyet Avvocatoin e Djallit»: zevendesimi
    # per nenvarg godiste brenda fjales. Ruajme SHKAKUN — nje rresht i vetem,
    # qe s'mund te keqkuptohet — jo simulimin e funksionit: e provova dy here
    # dhe te dyja rradhet dha alarme te rreme.
    try:
        _aj6 = _io2.open(_os2.path.join(_rr, "static", "app.js"), encoding="utf-8").read()
        check("titujt: zevendesimi vetem ne kufi fjale",
              "confine di parola" in _aj6 and "tMode" in _aj6,
              "pa kete, «Avokat» godet brenda «Avokatin» → «Avvocatoin»")
        # regresionet: te dy titujt e gabuar, gjetur duke hapur panelet ne
        # sesion italisht (jo duke lexuar kodin — kodi me genjeu tri here)
        check("titujt: «Pyet Avokatin e Djallit» ka perkthim te sakte",
              "Pyet Avokatin e Djallit\":" in _aj6
              or "Pyet Avokatin e Djallit\": " in _aj6,
              "pa perkthim te sakte, zevendesimi e sakaton")
        check("titujt: «Dosja» ka perkthim",
              '"Dosja":' in _aj6, "dilte ne shqip ne sesion italisht")
    except OSError as _e:
        check("titujt: app.js i lexueshem", False, str(_e))


    # ── [17] krijimi i perdoruesit: module te shumefishta + fjalekalim 2x ─
    try:
        _h7 = _io2.open(_os2.path.join(_rr, "templates", "index.html"), encoding="utf-8").read()
        _a7 = _io2.open(_os2.path.join(_rr, "static", "app.js"), encoding="utf-8").read()

        # moduli: caselle, non un menu a tendina
        _n = _h7.count('class="nu-mod"')
        check("krijimi: tri kutiza modulesh (jo menu)", _n == 3, "u gjeten %d" % _n)
        check("krijimi: menuja e vjeter u hoq",
              'id="new-user-profession"' not in _h7,
              "nje menu lejon nje profesion te vetem")
        check("krijimi: dergohet lista e moduleve",
              "modules: moduli" in _a7,
              "serveri e pranon listen; interfaqja duhet ta dergoje")
        check("krijimi: te pakten nje modul i detyrueshem",
              "moduli.length" in _a7)

        # password: due volte, e non si crea se non coincidono
        check("krijimi: fusha e dyte e fjalekalimit",
              'id="new-user-password2"' in _h7)
        check("krijimi: bllokohet nese nuk perputhen",
              "password !== password2" in _a7,
              "nje gabim shtypi krijon nje perdorues qe s'hyn dot")
        check("krijimi: syri per ta pare", 'id="new-user-eye"' in _h7)

        # ⚠️ l'emoji sta DENTRO lo span tradotto: fuori, in italiano
        # comparirebbe due volte (it_48 la contiene gia')
        check("krijimi: emoji brenda span-it te perkthyer",
              '> ⚖️ <span data-i18n="it_48"' not in _h7,
              "jashte, ne italisht do te dukej dy here")
    except OSError as _e:
        check("krijimi: skedaret e lexueshem", False, str(_e))


    # ── [18] matja e konsumit: paneli te mos kthehet ne zero ne heshtje ──
    try:
        _b8 = _io2.open(_os2.path.join(_rr, "src", "backends.py"), encoding="utf-8").read()
        _s8 = _io2.open(_os2.path.join(_rr, "src", "storage.py"), encoding="utf-8").read()
        _w8 = _io2.open(_os2.path.join(_rr, "src", "web.py"), encoding="utf-8").read()

        # La riga che raccoglie: senza, tutto torna a zero e nessuno se ne accorge.
        check("konsumi: lexohet nga pergjigjja e CLI-se",
              "_uso_da_risposta" in _b8,
              "pa te, paneli kthehet ne zero pa asnje gabim")
        check("konsumi: merret edhe ne streaming",
              "_uso_finale" in _b8)
        check("konsumi: kostoja vjen nga ofruesi",
              "total_cost_usd" in _b8,
              "llogaritja jone injoron cache-n dhe gabon shume here")

        # ⚠️ Il costo NON va ri-stimato nei totali: la stima prezza tutto a
        # tariffa piena e qui quasi tutto il volume e' cache.
        _tot = _s8.split("def usage_totals")[1][:1600]
        check("konsumi: totali nuk e ri-vlereson koston",
              "estimate_cost_cents" not in _tot,
              "vleresimi injoron cache-n")

        # L'attribuzione: ripiego, mai sostituzione.
        check("perdoruesi: kthehet vetem si zgjidhje e fundit",
              'if kw.get("user_id") is None:' in _b8,
              "mbishkrimi do t'ia jepte punen studios se gabuar")
        check("perdoruesi: kontekst per kerkese",
              "_REQUEST_USER" in _io2.open(
                  _os2.path.join(_rr, "src", "brain.py"), encoding="utf-8").read())
        _n8 = _w8.count("porta_utente")
        check("perdoruesi: kalon ne punet ne sfond", _n8 >= 4,
              "u gjeten %d nga 4 thread" % _n8)

        # Il tetto per studio e la quota.
        check("tavani: endpoint per ta vendosur",
              "api_admin_set_cap" in _w8)
        check("tavani: java levizese (jo javë kalendarike)",
              "days=7" in _s8.split("def studi_oltre_soglia")[1][:900],
              "e hena nuk fshin asgje")
        check("kuota: llogaritet per studio", "quota_pct" in _w8)

        # Punto 5: la guardia sul contesto.
        _c8 = _io2.open(_os2.path.join(_rr, "src", "config.py"), encoding="utf-8").read()
        check("konteksti: pragu i paralajmerimit ekziston",
              "CONTEXT_ALERT_TOKENS" in _c8)
        # La valvola vive SOLO nell'ambiente: se un giorno qualcuno le
        # scrivesse un valore fisso nel codice, una causa vera verrebbe
        # troncata a meta' per risparmiare centesimi.
        check("konteksti: valvula rri e fikur si parazgjedhje",
              'os.environ.get("TETRAMORPH_MAX_BUDGET_USD")' in _c8,
              "ndalimi i nje analize ligjore ne mes eshte demi, jo ilaci")
    except OSError as _e:
        check("konsumi: skedaret e lexueshem", False, str(_e))


    # ── [19] biseda: mos deklaro te vdekur ate qe eshte gjalle ──────────
    try:
        _w9 = _io2.open(_os2.path.join(_rr, "src", "web.py"), encoding="utf-8").read()
        _a9 = _io2.open(_os2.path.join(_rr, "static", "app.js"), encoding="utf-8").read()

        # ⚠️ La riga che ha fatto il danno: «900 secondi di silenzio → done».
        # Il silenzio non dice nulla sul fatto che il lavoro sia vivo.
        check("biseda: nuk dorezohet nga heshtja",
              "quiet > 900" not in _w9,
              "heshtja nuk tregon nese puna eshte gjalle")
        check("biseda: dorezimi shikon regjistrin e punes",
              "vivo = jobs_mod.get(job_id)" in _w9,
              "vetem regjistri e di nese puna vazhdon")
        check("biseda: mesazhi i vjeter 'Timeout' u hoq",
              "Timeout: përgjigja nuk mbërriti" not in _w9,
              "ishte genjeshter: serveri po punonte")

        # Il battito, e da dove viene.
        check("biseda: rrahje ne cdo minute", "def _battito" in _w9)
        check("biseda: rrahja shtyhet nga prodhuesi",
              "jobs_mod.push(job_id, _sse_event({" in _w9,
              "nje kuader qe e sheh vetem nje lexues i prish numerimin klientit")

        # La rete di sicurezza sul client.
        check("biseda: endpoint /api/ask/alive", "api_ask_alive" in _w9)
        check("biseda: klienti pyet para se te dorezohet",
              "reteDiSicurezza" in _a9)
        check("biseda: rrahja dhe gabimet ne dy gjuhe",
              "text_it" in _w9 and "evt.text_it" in _a9)
    except OSError as _e:
        check("biseda: skedaret e lexueshem", False, str(_e))


    # ── [20] kompozimi: mos rinis nga zeroja, mos gëlltit gjithë dosjen ──
    try:
        _b0 = _io2.open(_os2.path.join(_rr, "src", "brain.py"), encoding="utf-8").read()

        # ⚠️ La riga che ha bruciato 2h07m: ricominciare l'intera pipeline
        # quando la composizione scade. Il muro e' un tetto fisso: il secondo
        # tentativo era condannato in partenza.
        check("kompozimi: nuk rinis gjithë pipeline-n",
              "result = self.answer(user_message, history=history," not in _b0,
              "muri eshte tavan fiks: riprovimi ishte i dënuar që në fillim")
        check("kompozimi: rikompozon nga fazat e bëra",
              "ricompongo dalle fasi" in _b0)
        check("kompozimi: riprova pa bashkëngjitjet",
              "documents=None, **_fasi" in _b0,
              "bashkëngjitjet janë pesha që e bëri të skadonte")
        check("kompozimi: referat pa tru si hap i fundit",
              "_risposta_dalle_fasi" in _b0,
              "nje avokat parapelqen dymbedhjete analiza te papërpunuara para nje gabimi")

        # L'ordine del piano d'azione: alfabetico metteva «kjo_javë» prima di «sot».
        check("plani: rendi kronologjik, jo alfabetik",
              "_ORDINE_BUCKET" in _b0,
              "rreshti i pare eshte ai qe avokati ben sapo mbyll ekranin")

        # Il filtro degli allegati — provato DAVVERO, non letto: leggendolo
        # mi e' sembrato giusto due volte mentre era rotto (estensioni senza
        # punto, doppioni per nome invece che per contenuto).
        import sys as _sys2, tempfile as _tf2
        _sys2.path.insert(0, _rr)
        from src.brain import _allegati_per_cervello as _filtro
        _d = _tf2.mkdtemp()
        def _crea(n, kb, c=b"x"):
            p = _os2.path.join(_d, n)
            open(p, "wb").write(c * (kb * 1024))
            return p
        _docs = [
            {"filename": "atto.docx", "storage_path": _crea("a1.docx", 200)},
            {"filename": "copia.docx", "storage_path": _crea("a2.docx", 200)},
            {"filename": "video.mp4", "storage_path": _crea("v.mp4", 300)},
            {"filename": "audio.m4a", "storage_path": _crea("s.m4a", 100)},
        ]
        _leggi, _fuori = _filtro(_docs)
        _nomi = [x["filename"] for x in _leggi]
        check("bashkëngjitjet: videoja nuk i jepet trurit",
              "video.mp4" not in _nomi,
              "truri s'e sheh dot videon; raporti i shkruar eshte ne permbledhje")
        check("bashkëngjitjet: audioja nuk i jepet trurit",
              "audio.m4a" not in _nomi)
        check("bashkëngjitjet: dublikata hiqet nga PERMBAJTJA",
              "copia.docx" not in _nomi,
              "dy .docx identike kane emra ruajtjeje te ndryshem")
        check("bashkëngjitjet: dokumenti i vlefshëm mbetet",
              "atto.docx" in _nomi)
        check("bashkëngjitjet: te perjashtuarit nuk zhduken",
              len(_fuori) == 3,
              "nje dosje e cunguar ne heshtje eshte me keq se nje e ngadalte")
    except Exception as _e:  # noqa: BLE001
        check("kompozimi: kontrollet u ekzekutuan", False, str(_e))


    # ── [21] auditi i 2 shtatorit: kater rregullimet te mos kthehen ─────
    try:
        _s21 = _io2.open(_os2.path.join(_rr, "src", "storage.py"), encoding="utf-8").read()
        _w21 = _io2.open(_os2.path.join(_rr, "src", "web.py"), encoding="utf-8").read()
        _a21 = _io2.open(_os2.path.join(_rr, "static", "app.js"), encoding="utf-8").read()

        # [1] fshirja e perdoruesit
        check("fshirja: pastrim i qarte, jo vetem CASCADE",
              "DELETE FROM firm_members WHERE user_id" in _s21,
              "nje lidhje pa PRAGMA e anashkalon CASCADE-n (e provuar: prova3in1)")
        check("fshirja: ndalon te studiot e perbashketa",
              "COALESCE(is_personal, 0) = 0" in _s21,
              "CASCADE do t'i zhdukte per te gjithe anetaret")
        check("fshirja: arsyeja i shkon administratorit",
              "motivo or \"errore eliminazione\"" in _w21)

        # [2] baza e te dhenave
        check("db: WAL i ndezur", "journal_mode = WAL" in _s21,
              "ne delete-mode lexuesi bllokon shkruesin")
        check("db: busy_timeout i ndezur", "busy_timeout" in _s21,
              "pa te, «database is locked» ne mes te nje analize")

        # [3] higjiena
        check("app.js: _sideLabel eshte NJE e vetme",
              _a21.count("function _sideLabel(") == 1,
              "e dyta mbishkruante te paren ne heshtje")
        check("stima e vdekur e kostos u hoq",
              "estimate_cost_cents" not in _s21,
              "vleresonte gjithcka me tarife te plote duke injoruar cache-n")
        check("etiketa e vellimit nuk genjeb me",
              "vëll. maks" in _a21 and '"kulmi"' not in _a21,
              "1.8M si «pik» do te tremb kend qe njeh tavanet e modeleve")

        # [4] serveri
        check("serveri: waitress, jo dev-server",
              "from waitress import serve" in _w21)
        check("serveri: kufizimi NJE-proces i dokumentuar",
              "UN processo" in _w21,
              "multi-worker do te thyente jobs/parcheggio/battiti ne memorie")
        _r21 = _io2.open(_os2.path.join(_rr, "requirements.txt"), encoding="utf-8").read()
        check("serveri: waitress ne requirements", "waitress" in _r21)
    except OSError as _e:
        check("auditi: skedaret e lexueshem", False, str(_e))


    # ── [22] kompozimi: tekst inline, Read vetem per te verbrit ────────
    try:
        _b2 = _io2.open(_os2.path.join(_rr, "src", "brain.py"), encoding="utf-8").read()
        _c2 = _io2.open(_os2.path.join(_rr, "src", "config.py"), encoding="utf-8").read()

        # ⚠️ Kjo eshte kura: me bashkengjitje kompozimi skadonte (2x1800s),
        # pa to 472s. Nese dikush i rikthen skedaret me tekst te Read-i,
        # fashikujt e medhenj rikthehen ne timeout.
        check("kompozimi: perdor ndarjen tekst/te-verber",
              "_docs_per_compose" in _b2)
        check("kompozimi: buxhet i dedikuar per tekstin inline",
              "char_budget=COMPOSE_DOC_CHAR_BUDGET" in _b2,
              "6000 gjermat e vjetra ishin per epoken e Read-it te shtrenjte")
        check("kompozimi: buxheti ekziston ne config",
              "COMPOSE_DOC_CHAR_BUDGET" in _c2)
        check("kompozimi: udhezimi flet per tekst MË LART, jo skedare",
              "Teksti i dokumenteve është MË LART" in _b2,
              "udhezimi i vjeter i thoshte trurit se skedaret jane te leximit")

        # Selektori i PROVUAR me dokumente te rreme.
        import sys as _sy3
        _sy3.path.insert(0, _rr)
        from src.brain import _docs_per_compose as _sel
        import tempfile as _tf3
        _d3 = _tf3.mkdtemp()
        _f3 = _os2.path.join(_d3, "skan.png")
        open(_f3, "wb").write(b"x" * 1024)
        _docs3 = [
            {"filename": "akt.pdf", "extracted_text": "teksti i aktit",
             "storage_path": _f3},                       # ka tekst → inline
            {"filename": "video.mp4", "extracted_text": "",
             "summary": "raporti forensik i videos",
             "storage_path": _f3},                       # referto → inline
            {"filename": "skan.png", "extracted_text": "", "summary": "",
             "storage_path": _f3},                       # i verber → Read
            {"filename": "humbur.docx", "extracted_text": "", "summary": ""},
        ]
        _inl, _ler = _sel(_docs3)
        _ni = [x["filename"] for x in _inl]
        _nl = [x["filename"] for x in _ler]
        check("selektori: teksti shkon inline", "akt.pdf" in _ni)
        check("selektori: raporti i videos shkon inline (jo Read)",
              "video.mp4" in _ni and "video.mp4" not in _nl,
              "truri s'e sheh dot videon; raportin e ka ne tekst")
        check("selektori: i verberi shkon te Read-i", "skan.png" in _nl,
              "vetem aty syte e Read-it duhen vertet")
        check("selektori: pa tekst dhe pa skedar → mbetet emri",
              "humbur.docx" in _ni)
    except Exception as _e:  # noqa: BLE001
        check("kompozimi[22]: kontrollet u ekzekutuan", False, str(_e))


    # ── [23] besimi qe mbahet mend + tabela qe s'shpik ──────────────────
    try:
        _s23 = _io2.open(_os2.path.join(_rr, "src", "storage.py"), encoding="utf-8").read()
        _w23 = _io2.open(_os2.path.join(_rr, "src", "web.py"), encoding="utf-8").read()
        _a23 = _io2.open(_os2.path.join(_rr, "static", "app.js"), encoding="utf-8").read()
        _h23 = _io2.open(_os2.path.join(_rr, "templates", "index.html"), encoding="utf-8").read()

        # ① Verifikat e citimeve MBIJETOJNE refresh-in. Pa keto, distinktivi
        # i besimit dhe shenjat ⚠ zhdukeshin sapo rihapej faqja.
        check("besimi: kolona citations_json ekziston",
              "citations_json" in _s23)
        check("besimi: mesazhi perditesohet PAS verifikave",
              _w23.count("update_message_verification") >= 2,
              "ruajtja mbetet e para (pergjigja mbijeton), verifikat shtohen pas")
        check("besimi: historiku ia jep distinktivit citimet",
              _w23.count('"citations": m.citations') >= 2)
        check("besimi: klienti i kalon te appendBot",
              "citations: m.citations || null" in _a23,
              "distinktivi ekzistonte por historiku s'ia jepte te dhenat")

        # ② Tabela — e gjetshme dhe e paster
        check("tabela: ze ne menu PRO", 'data-pro="tabela"' in _h23)
        check("tabela: dispatcher-i e hap", 'key === "tabela"' in _a23)
        check("tabela: endpoint-i ekziston", "/table" in _w23 and "api_case_table" in _w23)
        check("tabela: CSV me pikepresje (Excel it/al)", "join(\";\")" in _a23,
              "me presje Excel-i lokal e hap gjithcka ne nje kolone")
        # E gjetur nga titullari ne shikimin e pare: pa ngarkim, nje
        # fashikull bosh ishte rruge pa krye.
        check("tabela: ngarkon dokumente nga vete paneli",
              "tb-up-inp" in _a23 and 'method: "POST", body: fd' in _a23)
        check("tabela: lista vetepërditësohet gjate përpunimit",
              "sorvegliaLista" in _a23,
              "nxjerrja eshte asinkrone: kutia ndizet kur teksti ekziston")
        check("tabela: lexon celesin e vertete te pergjigjes",
              "j.documents || j.items" in _a23,
              "endpoint kthen {documents}: .items betohej se s'ka dokumente")

        # Parse-i i PROVUAR me pergjigje te renditura si i vjen modelit
        import sys as _sy4
        _sy4.path.insert(0, _rr)
        from src.tabela import parse_qeliza, pastro_pyetjet, MAX_PYETJE
        _ok1 = parse_qeliza('```json\n[{"answer":"Stiven","quote":"pala e demtuar Stiven","found":true}]\n```', 1)
        check("tabela: parse me recinti ```", _ok1[0]["answer"] == "Stiven" and _ok1[0]["found"] is True)
        _ok2 = parse_qeliza('Ja rezultati: [{"answer":"12.000 €","found":true},{"answer":"—","found":false}] shpresoj te ndihmoje', 2)
        check("tabela: parse me proze rreth listes", _ok2[1]["found"] is False)
        _ok3 = parse_qeliza('[{"answer":"vetem nje"}]', 3)
        check("tabela: rreshti sfazuar plotesohet me «—»",
              len(_ok3) == 3 and _ok3[2]["answer"] == "—",
              "nje tabele e sfazuar nje kolone eshte me keq se nje qelize bosh")
        try:
            parse_qeliza("s'ka fare json ketu", 2)
            check("tabela: plehra → ValueError", False, "duhej te ngrinte")
        except ValueError:
            check("tabela: plehra → ValueError", True)
        _q = pastro_pyetjet(["  a?  ", "a?", "", "b?"] + ["x%d" % i for i in range(20)])
        check("tabela: pyetjet pastrohen dhe kufizohen",
              _q[0] == "a?" and len(_q) == MAX_PYETJE,
              "dublikatat dhe boshlleqet s'behen kolona")
    except Exception as _e:  # noqa: BLE001
        check("besimi/tabela[23]: kontrollet u ekzekutuan", False, str(_e))


    # ── [24] nga konkurrentet: profili, kasacioni, burimet, harta ───────
    try:
        _b4 = _io2.open(_os2.path.join(_rr, "src", "brain.py"), encoding="utf-8").read()
        _w4 = _io2.open(_os2.path.join(_rr, "src", "web.py"), encoding="utf-8").read()
        _bk4 = _io2.open(_os2.path.join(_rr, "src", "backends.py"), encoding="utf-8").read()
        _a4 = _io2.open(_os2.path.join(_rr, "static", "app.js"), encoding="utf-8").read()
        _h4 = _io2.open(_os2.path.join(_rr, "templates", "index.html"), encoding="utf-8").read()

        # 4️⃣ binario IT: Cassazione e detyrueshme, shpikja e ndaluar
        check("IT: Kasacioni kerkohet live",
              "CASSAZIONE — VERIFICA VIVA" in _b4,
              "konkurrentet italiane jetojne me Kasacion")
        check("IT: ndalimi i shpikjes se ekstremeve",
              "MAI inventare numero, sezione o anno" in _b4)

        # 5️⃣ burimet e webit ne fund te pergjigjes
        check("burimet: seksioni i detyruar kur perdoret webi",
              "Burimet e webit" in _b4)

        # 1️⃣ profili i studios — zinxhiri i plote
        check("profili: kolona ne firms", "profile_json" in
              _io2.open(_os2.path.join(_rr, "src", "storage.py"), encoding="utf-8").read())
        check("profili: armatoset ne auth", "set_request_profile" in
              _io2.open(_os2.path.join(_rr, "src", "auth.py"), encoding="utf-8").read())
        check("profili: udheton me porta_utente",
              "_profili = request_profile()" in _b4,
              "pa te, punet ne sfond humbnin rregullat e shtepise")
        check("profili: fazat e trurit e ri-armatosin",
              "_stage_profili" in _b4)
        check("profili: injektohet VETEM jo-fast",
              "_shto_profilin" in _bk4 and "if fast:" in _bk4,
              "triage dhe qelizat e tabeles duhet te mbeten neutrale")
        check("profili: endpoint-et", "/api/firm/profile" in _w4)
        check("profili: forma ne Studio", 'id="fp-sec"' in _h4
              and "loadFirmProfile" in _a4)

        # 6️⃣ faqja publike e verifikimit
        check("verifikimi: skedaret ekzistojne",
              _os2.path.isfile(_os2.path.join(_rr, "legal", "si_e_verifikojme_sq.md"))
              and _os2.path.isfile(_os2.path.join(_rr, "legal", "si_e_verifikojme_it.md")))
        check("verifikimi: seksion i /legale + shkurtore",
              "si_e_verifikojme" in _w4 and '"/verifikimi"' in _w4)

        # 7️⃣ harta e pretendimeve — parimet e metodologjise
        check("harta: endpoint + menu",
              "api_claim_chart" in _w4 and 'data-pro="harta"' in _h4)
        check("harta: boshlleku eshte prioriteti",
              "BOSHLLËQET — PRIORITETI" in _w4,
              "harta sherben te fitosh discovery-n, jo te dukesh i plote")
        check("harta: citim tekstual, jo parafraze",
              "kurrë parafrazë" in _w4)
        check("harta: nuk konkludon mbi themelin",
              "mos konkludo mbi fajësinë" in _w4)

        # profilo: formattatore PROVATO eseguendolo
        import sys as _sy5
        _sy5.path.insert(0, _rr)
        from src.profilo import pastro, formato_blloku, MAX_RREGULLA
        _d = pastro({"stili": "  Formal  ", "rregulla": "a\nb\n\n" + "\n".join("r%d" % i for i in range(20)), "boh": "x"})
        check("profili: pastro heq te panjohurat dhe kufizon",
              "boh" not in _d and len(_d["rregulla"]) == MAX_RREGULLA
              and _d["stili"] == "Formal")
        _bl = formato_blloku({"intestazione": "Studio X", "rregulla": ["mai penali >0,1%"]})
        check("profili: blloku thote JO burim ligjor",
              "JO burim ligjor" in _bl and "Studio X" in _bl,
              "nje rregull shtepie s'duhet te behet kurre baze juridike")
        check("profili: bosh → bllok bosh", formato_blloku({}) == "")
    except Exception as _e:  # noqa: BLE001
        check("konkurrentet[24]: kontrollet u ekzekutuan", False, str(_e))


    # ── [25] jurisprudenca IT (mbulimi si ligj) + email-i i perdoruesit ──
    try:
        _w5 = _io2.open(_os2.path.join(_rr, "src", "web.py"), encoding="utf-8").read()
        _c5 = _io2.open(_os2.path.join(_rr, "src", "case_citation_verifier.py"), encoding="utf-8").read()
        _a5 = _io2.open(_os2.path.join(_rr, "static", "app.js"), encoding="utf-8").read()
        _h5 = _io2.open(_os2.path.join(_rr, "templates", "index.html"), encoding="utf-8").read()

        check("IT-vendime: helper i vetem per te dy binaret",
              _w5.count("_verify_decisions_smart(") >= 3,
              "stream + vegla/blocking kalojne nga e njejta dere")
        check("IT-vendime: moduli i indeksit ekziston",
              _os2.path.isfile(_os2.path.join(_rr, "src", "it_case_index.py")))
        check("IT-vendime: pattern CCost i pranishem", "_IT_CCOST" in _c5)

        # ⚠️ REGOLA E MBULIMIT — provuar duke EKZEKUTUAR, jo duke lexuar:
        # nje vit i pambyllur s'guxon te vulose asgje.
        import sys as _sy6, json as _js6, tempfile as _tf6, importlib as _il6
        _sy6.path.insert(0, _rr)
        import src.it_case_index as _ici
        _d6 = _tf6.mkdtemp()
        from pathlib import Path as _P6
        _ici.FILE_DECISIONI = _P6(_d6) / "it_decisions.jsonl"
        _ici.FILE_META = _P6(_d6) / "it_decisions_meta.json"
        _ici._cache["mtime"] = None
        _ici.FILE_DECISIONI.write_text(_js6.dumps(
            {"court": "CCost", "number": 100, "year": 2024}) + "\n",
            encoding="utf-8")
        _ici.FILE_META.write_text(_js6.dumps(
            {"CCost": {"complete_years": [2024]}}), encoding="utf-8")
        from src.case_citation_verifier import verify_cases_it as _vit
        _r1 = _vit("Shih Corte cost. n. 100/2024 dhe C. cost., sent. n. 999/2024.")
        check("IT-vendime: e verteta vuloset ✓",
              any(i["number"] == 100 and i["status"] == "verified"
                  for i in _r1["items"]))
        check("IT-vendime: e paekzistuara ne vit TE MBYLLUR vuloset ⚠",
              any(i["number"] == 999 and i["status"] == "unverified"
                  for i in _r1["items"]))
        _r2 = _vit("Shih Corte cost. n. 50/1999.")
        check("IT-vendime: viti i PAMBULUAR nuk preket fare",
              _r2["stats"]["total"] == 0,
              "«nuk e gjej ≠ eshte i rreme»: vrima jone s'njollos ekstremin e vertete")

        # Harvester-i giurcost: validatori STRUKTUROR (marker '404' u
        # tregua i verber nen urllib — 3.127 guacka ne nje nate; ligji i
        # mbulimit e mbajti jashte prodhimit).
        import importlib.util as _ilu
        _spec = _ilu.spec_from_file_location(
            "ing_it", _os2.path.join(_rr, "tools", "ingest_it_giurcost.py"))
        _ing = _ilu.module_from_spec(_spec)
        _spec.loader.exec_module(_ing)
        check("giurcost: faqja e vertete pranohet",
              _ing.e_vendim("bla SENTENZA N. 100 ANNO 2024 bla",
                            "sentenza", 100))
        check("giurcost: guacka (numri vetem ne koment URL) refuzohet",
              not _ing.e_vendim(
                  "<!-- decisioni, 2024, 3200s-24 --> CONSULTA ON LINE",
                  "sentenza", 3200),
              "markeri '404' u tregua i verber; kriteri strukturor jo")
        check("giurcost: numri i gabuar refuzohet",
              not _ing.e_vendim("SENTENZA N. 99 ...", "sentenza", 100))

        # D — email-i i perdoruesit
        check("email: krijimi e kerkon", '"email e pavlefshme' in _w5)
        check("email: PATCH per administratorin", "api_admin_user_email" in _w5)
        check("email: fusha ne formularin e krijimit",
              'id="new-user-email"' in _h5)
        check("email: modal-i ⚙️ e tregon dhe e ruan",
              "um-save-email" in _a5 and "um-email" in _a5)
    except Exception as _e:  # noqa: BLE001
        check("IT/email[25]: kontrollet u ekzekutuan", False, str(_e))


    # ── [26] precedentet IT ne tru: FTS5 + dega IT, AL i paprekur ───────
    try:
        _b6 = _io2.open(_os2.path.join(_rr, "src", "brain.py"), encoding="utf-8").read()
        check("IT-prec: dega IT ne _retrieve_precedents",
              '_jur == "IT"' in _b6 and "_precedenti_it(triage)" in _b6)
        check("IT-prec: AL i paprekur (guard-i i vjeter jeton)",
              'if _jur != "AL":' in _b6 and "self.kb.cases" in _b6)

        # FTS5 i PROVUAR: indeks i perkohshem, kerkese, fragment «...»
        import sys as _sy7, json as _js7, tempfile as _tf7
        _sy7.path.insert(0, _rr)
        import src.it_precedent_fts as _fts
        from pathlib import Path as _P7
        _d7 = _tf7.mkdtemp()
        _fts.JSONL = _P7(_d7) / "it_decisions.jsonl"
        _fts.DB = _P7(_d7) / "fts.db"
        _fts.JSONL.write_text(
            _js7.dumps({"court": "CCost", "type": "sentenza", "number": 100,
                        "year": 2024, "date": "4 giugno 2024",
                        "url": "https://x/1",
                        "text": "La clausola penale nel contratto di vendita "
                                "eccede la misura consentita."}) + "\n" +
            _js7.dumps({"court": "CCost", "type": "ordinanza", "number": 7,
                        "year": 2025, "date": "", "url": "https://x/2",
                        "text": "Questione di legittimita' sull'imposta di "
                                "registro."}) + "\n", encoding="utf-8")
        _n7 = _fts.rebuild_indeksi()
        check("IT-prec: indeksi ndertohet", _n7 == 2)
        _r7 = _fts.kerko(["clausola penale contratto"], top_k=3)
        check("IT-prec: gjen vendimin e duhur",
              len(_r7) >= 1 and _r7[0]["number"] == 100)
        check("IT-prec: fragmenti i evidentuar «...»",
              "«" in _r7[0]["passo"] and "»" in _r7[0]["passo"],
              "pasazhi vjen nga motori FTS5, jo nga ne")
        check("IT-prec: kerkesa boshe s'rrezon asgje",
              _fts.kerko([], top_k=3) == [])

        # dega e trurit e PROVUAR me nje triage-kukull (duck-typed)
        from types import SimpleNamespace as _NS7
        from src.brain import _precedenti_it as _pit
        import src.brain as _br7
        _br7.it_precedent_fts = _fts  # noop; importi eshte lazy brenda
        _rr7 = _pit(_NS7(search_queries=["clausola penale"],
                         strategic_angles=[]))
        check("IT-prec: CasePrecedent i vertete me citim dhe pasazh",
              len(_rr7) >= 1
              and _rr7[0][0].court_name == "Corte costituzionale"
              and "«" in _rr7[0][0].summary
              and _rr7[0][0].source_url == "https://x/1")
        check("IT-prec: data italiane e lexuar (4 giugno 2024)",
              _rr7[0][0].year == 2024)
        from src.brain import _tipo_per_corte as _tpc
        check("IT-prec: TAR/CdS nuk vishen si kushtetuese",
              _tpc("CCost") == "kushtetuese"
              and _tpc("CdS") == "administrativ"
              and _tpc("TAR Bari") == "administrativ",
              "karta e nje TAR-i me chip «kushtetuese» eshte genjeshter vizive")
    except Exception as _e:  # noqa: BLE001
        check("IT-prec[26]: kontrollet u ekzekutuan", False, str(_e))

    # ── [27] Përkthim ligjor: funksionet e pastra + rojet e firmave ──────
    try:
        from src import perkthim as _pk

        # spezza: ASNJË gërmë e humbur — rindërtimi = origjinali, gjithmonë
        _t27 = ("Neni 1. Palët bien dakord.\n\n" * 300) + "Fund."
        _cope = _pk.spezza(_t27, max_cope=2000)
        check("perkthim: spezza rindërton origjinalin gërmë për gërmë",
              "".join(_cope) == _t27 and len(_cope) > 1
              and all(len(c) <= 2000 for c in _cope),
              "po humbasin gërma në kufijtë e copave")
        _mostro = "x" * 5000  # paragraf pa asnjë \n: prerje e thatë
        check("perkthim: paragrafi-përbindësh pritet pa humbje",
              "".join(_pk.spezza(_mostro, max_cope=2000)) == _mostro)

        # glossari: kapet, pastrohet, dhe mungesa nuk thyen asgjë
        _resp = "Testo tradotto qui.\n\n---GLOSSAR---\nmasë sigurimi = misura cautelare\nkërkesë padi = atto di citazione\n"
        _puro, _gl = _pk.estrai_glossar(_resp)
        check("perkthim: glossari kapet dhe teksti pastrohet",
              _gl.get("masë sigurimi") == "misura cautelare"
              and len(_gl) == 2 and "GLOSSAR" not in _puro)
        _puro2, _gl2 = _pk.estrai_glossar("Vetëm tekst, pa bllok.")
        check("perkthim: pa bllok glossari — teksti i paprekur, fjalori bosh",
              _gl2 == {} and _puro2 == "Vetëm tekst, pa bllok.")

        # disclaimeri: GJITHMONË, në gjuhën e synuar — kurrë i betuar
        for _tg in ("sq", "it", "en"):
            pass
        check("perkthim: disclaimer në të tria gjuhët, kurrë «i betuar»",
              all(_tg in _pk.DISCLAIMER for _tg in ("sq", "it", "en"))
              and _pk.attacca_disclaimer("Tekst.", "it").endswith(
                  _pk.DISCLAIMER["it"])
              and "giurato" in _pk.DISCLAIMER["it"]
              and "betuar" in _pk.DISCLAIMER["sq"])

        # firmat: effort_override ekziston KUDO me default None — truri
        # ligjor nuk e sheh dhe mbetet në max
        import inspect as _insp
        from src import backends as _bk
        _klasat = [c for c in vars(_bk).values()
                   if _insp.isclass(c) and hasattr(c, "complete")
                   and c.__module__ == _bk.__name__]
        _ok_firma = True
        for _c in _klasat:
            try:
                _par = _insp.signature(_c.complete).parameters.get("effort_override")
                if _par is None or _par.default is not None:
                    _ok_firma = False
            except (ValueError, TypeError):
                pass
        check("perkthim: effort_override në çdo firmë, default None (truri max)",
              _ok_firma and len(_klasat) >= 3,
              "nje backend pa scavalco ose me default jo-None")

        # prompt-i i përkthyesit: glosari udhëton dhe blloku kërkohet
        _sysp = _pk._system_perkthyes("it", {"afat": "termine"})
        check("perkthim: prompti mban glosarin dhe kërkon bllokun në fund",
              "afat = termine" in _sysp and "---GLOSSAR---" in _sysp
              and "italisht" in _sysp)
    except Exception as _e:  # noqa: BLE001
        check("perkthim[27]: kontrollet u ekzekutuan", False, str(_e))


    print("\n== Përfundim: %d kaluan, %d dështuan ==" % (PASSES, len(FAILS)))
    if FAILS:
        print("DËSHTIME:", ", ".join(FAILS))
        return 1
    print("\033[32mTË GJITHA GJELBËR — truri i shenjtë i paprekur.\033[0m")
    return 0


if __name__ == "__main__":
    sys.exit(main())
