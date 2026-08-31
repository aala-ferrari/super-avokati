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


    print("\n== Përfundim: %d kaluan, %d dështuan ==" % (PASSES, len(FAILS)))
    if FAILS:
        print("DËSHTIME:", ", ".join(FAILS))
        return 1
    print("\033[32mTË GJITHA GJELBËR — truri i shenjtë i paprekur.\033[0m")
    return 0


if __name__ == "__main__":
    sys.exit(main())
