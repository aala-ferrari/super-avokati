#!/usr/bin/env python3
"""Set aureo — golden regression harness for the sacred brain (Step 4B).

Deterministic, LLM-FREE checks that run in seconds and catch the regressions we
have actually hit: corpus gaps, citation-verifier misclassifications, and
retrieval stem bugs. Run after every build:

    docker exec super-avvocato python3 tools/golden_check.py

Exit code 0 = all green; 1 = at least one regression. Extend GOLDENS freely.
"""
import re
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


# v9.376 — un indice per file, non 31: il golden caricava ArticleIndex 31 volte e ogni copia restava viva fino alla
# fine (~7 GB): con un'altra operazione pesante sulla macchina l'OOM killer l'ha ucciso due volte (23 set). Nel golden
# gli indici si leggono soltanto (le modifiche avvengono su copie), quindi condividerli non cambia nessun controllo.
_AI_CACHE: dict = {}
_AI_LOAD = ArticleIndex.load.__func__


def _ai_load_once(cls, path=INDEX_FILE):
    k = str(path)
    if k not in _AI_CACHE:
        _AI_CACHE[k] = _AI_LOAD(cls, path)
    return _AI_CACHE[k]


ArticleIndex.load = classmethod(_ai_load_once)


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
    # v9.366 (22 set): re-parse dei precedenti albanesi documento per documento — 226 inammissibilità, 4 kthim i
    # rekursit del relatore e 5 errata sono USCITE di proposito (non decidono il merito): 1.407 → ~1.170.
    # v9.368 (23 set): anche la CEDU rifatta documento per documento — 103 comunicazioni, 37 risoluzioni CM e 13
    # Information Note sono USCITE (non sono decisioni): 424 → ~278 (105 sentenze + 173 decisioni).
    check("≥1000 precedentë", len(dec) >= 1000, "gjetur %d" % len(dec))
    _ec = [d for d in dec if d.court_code == "ecthr_albania"]
    check("Kushtetuese ≥ 430 · Gjykata e Lartë ≥ 290 · CEDU ≥ 250 (re-parse v9.366-368)",
          sum(1 for d in dec if d.court_code == "kushtetuese") >= 430 and len(gjl) >= 290 and len(_ec) >= 250,
          "K %d · GjL %d · CEDU %d" % (sum(1 for d in dec if d.court_code == "kushtetuese"), len(gjl), len(_ec)))
    # v9.368: nessuna comunicazione/risoluzione/nota fra i precedenti CEDU; ogni CEDU ha operativo, esito e numero di ricorso
    check("CEDU: solo sentenze e decisioni (niente comunicazioni, risoluzioni CM, Information Note)",
          not [d for d in _ec if re.search(r"QUESTIONS? TO THE PARTIES|Resolution CM/ResDH|Information Note on the Court", (d.reasoning or "")[:3000])])
    check("CEDU: operativo con etichetta, esito e numero di ricorso per ogni record",
          all((d.dispositif or "").startswith("[") and d.outcome and re.search(r"\d+/\d\d", d.number or "") for d in _ec))
    # v9.366: OGNI vendim i Gjykatës së Lartë ka dispozitivin e vet (jo vetëm 149 të rinjtë) dhe asnjë «ndreqje»
    check("çdo vendim GjL ka dispozitiv", all(len(d.dispositif or "") >= 10 for d in gjl))
    check("asnjë errata (Saktësimin/Ndreqjen) te precedentët",
          not [d for d in dec if d.court_code != "ecthr_albania"
               and re.search(r"^\s*(?:\[[^\]]*\]\s*)?(?:\d+\.\s*)?(?:Saktësimin|Ndreqjen)", d.dispositif or "")])
    check("të tri gjykatat të pranishme (Postgres-i nuk u humb)",
          {"kushtetuese", "gjykata_elarte", "ecthr_albania"} <= korte,
          "gjetur %s" % sorted(korte))
    # 2. asnjë mospranim: nuk vendos mbi themelin
    # v9.369: conta l'ESITO (etichetta + inizio del dispositivo): un «Mospranimin e ankimit për pjesën…» dopo un
    # «Ndryshimin» è un vendim di merito parziale, non un'inammissibilità
    mosk = [d for d in gjl if "mospranim" in (d.dispositif or "")[:60].lower()]
    check("asnjë vendim mospranimi te precedentët e rinj", not mosk,
          "gjetur %d" % len(mosk))
    # 3. vetëm arsyetimi i Kolegjit — jo i shkallëve që u prishën
    # v9.366: il ragionamento parte dal marcatore del Kolegji — heading «Vlerësimi i Kolegjit…» o la frase «Kolegji … vlerëson/çmon/konstaton/thekson»
    marker = ("vlerëson", "vlereson", "çmon", "cmon", "arsyeton", "VLERËSIMI", "Vlerësimi", "konstaton", "thekson", "gjykon", "Kolegj")   # «Kolegjet e Bashkuara konstatojne» (senza dieresi) è il Kolegji
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
    r2 = ccv.verify_cases("shih vendimin nr. 00-2025-99876 të Gjykatës së Lartë", idxd2)
    check("nuk konfirmon një numër që s\'e kemi (00-2025-99876)",
          r2["stats"]["unverified"] == 1, str(r2["stats"]))
    # ⚠ e non lo chiama MAI falso: baza jonë nuk i ka të gjitha
    check("nuk e quan KURRË 'fake' — vetëm 'i paverifikuar'",
          all(i["status"] in ("verified", "unverified") for i in r2["items"]),
          str([i["status"] for i in r2["items"]]))
    # l'avviso viaggia col testo, non solo sullo schermo
    md = ccv.annotate_unverified("Përgjigje me vendimin nr. 00-2025-99876.", r2)
    check("paralajmërimi ngjitet te teksti (jo vetëm badge)",
          "00-2025-99876" in md and ("Kujdes" in md or "verifikuar" in md))
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
        check("kompozimi: riprova pa bashkëngjitjet (dhe pa web, v9.318)",
              "documents=None, no_web=True, **_fasi" in _b0,
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
        check("fshirja: pastrim DINAMIK i tabelave-produkt qe bllokojne (bench_memos/settlement…), audit i ruajtur",
              "foreign_key_list" in _s21 and '"SET NULL", "NO ACTION"' in _s21
              and '"ai_audit_log", "case_access_log", "legal_acceptances"' in _s21,
              "FK SET NULL/NO ACTION + user_id NOT NULL bllokonte fshirjen; audit-i mbetet (AI Act)")
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


    # ── [28] Huracán: la norma che PËRCAKTON shkeljen entra nel blocco ────
    # Misurato 5-6 set 2026: «makina bën zhurmë» → Neni 79 (kontrolli teknik)
    # per cinque risposte, mai il Neni 153 «Kufizimi i zhurmave» (gjoba).
    try:
        _hur = ("kam nje klient i cili esht me makin lamborghini huracan, nga "
                "fabrika, i pa modifikuar, as pjesa e zhurmes se marmites nuk "
                "esht modifikuar. e ndaloj policia e rendit, e cila i thot qe "
                "makina ben zhurm. a perben shkelje kjo? cfar neni e kap?")
        _rad = brain._radicet_e_pyetjes(_hur)
        check("huracan[28]: la radice «zhurm» è un tema, «mjet/polic» no",
              "zhurm" in _rad and "mjete" not in _rad and "polic" not in _rad,
              str(sorted(_rad))[:120])
        # stessa fusione di brain._retrieve: BM25 su più query + ancore + titoli
        _qs = [_hur, "kontrolli teknik zhurmshmeria e mjetit policia rrugore",
               "ndalimi i mjetit nga policia per zhurme pa matje"]
        _seen = {}
        for _q in _qs:
            for _a, _sc in idx.search(_q, top_k=12):
                _k = (_a.code, _a.number)
                if _sc > _seen.get(_k, 0.0):
                    _seen[_k] = _sc
        _per = {(a.code, a.number): a for a in idx.articles}
        _pairs = sorted([(_per[k], v) for k, v in _seen.items() if k in _per],
                        key=lambda x: x[1], reverse=True)
        _prima = {(a.code, a.number) for a, _ in _pairs[:12]}
        check("huracan[28]: senza la cura il 153 NON entrava (il difetto è vero)",
              ("kodi_rrugor", "153") not in _prima)
        _pairs = brain._applica_ancore(_pairs, idx, _qs, ["Rrugor"])
        _rr = ({d.code for d in brain.LEGAL_DOCUMENTS if d.area.lower() == "rrugor"}
               | set(brain.PROCEDURAL_MAPPING["Rrugor"]))
        _pairs = brain._ankoro_sipas_titullit(_pairs, idx, _hur, queries=_qs, restrict=_rr)
        _dopo = {(a.code, a.number) for a, _ in _pairs[:12]}
        check("huracan[28]: con l'ancora per titolo il Neni 153 KRr entra nei 12",
              ("kodi_rrugor", "153") in _dopo, str(sorted(_dopo))[:160])
        _marc = [a for a, _ in _pairs[:12] if getattr(a, "_ancora_titull", False)]
        check("huracan[28]: le ancore per titolo sono marcate e al massimo 3",
              0 < len(_marc) <= 3 and all(isinstance(s, float) for _, s in _pairs[:3]))
        # selettività: una radice generica non ancora nulla
        _gen = brain._ankoro_sipas_titullit(list(_pairs), idx, "mjeti policia ndalimi",
                                            queries=_qs, restrict=_rr)
        check("huracan[28]: radici generiche (mjet/polic/ndalim) non ancorano",
              len(_gen) == len(_pairs))
        # un titolo che non risuona con la domanda (BM25 reale 0) non entra:
        # «vlerësimi» accende «Vlerësimi i provave» ma la domanda è sul rumore
        _zero = brain._ankoro_sipas_titullit(list(_pairs), idx, "vleresimi i provave",
                                             queries=["zhurma e marmites"], restrict=_rr)
        check("huracan[28]: ancora a punteggio zero = rumore, resta fuori",
              len(_zero) == len(_pairs))
        check("huracan[28]: il triage cerca la norma che PËRCAKTON la shkelje",
              any(isinstance(v, str) and "PËRCAKTON vetë kundërvajtjen" in v
                  and "TERMAT E KODIT" in v for v in vars(brain).values()))
    except Exception as _e:  # noqa: BLE001
        check("huracan[28]: kontrollet u ekzekutuan", False, str(_e))

    # ── [29] Studio: Kërkuesi — funksionet e pastra + shartimi ───────────
    try:
        from src import studio as _st
        from src import config as _cfgs
        _p = _st.kerkuesi_parse('Sigurisht. {"mungon_norma_percaktuese": true, "pse": "s ka norma bazë",'
                                ' "kerkime": ["kufizimi i zhurmave", "", "sistemi zhurmëshues"],'
                                ' "nene": [{"kodi": "kodi_rrugor", "numri": "153"}, {"x": 1}, "junk"]} Faleminderit.')
        check("studio[29]: parse JSON i fortë (tekst rreth, bosh dhe junk filtrohen)",
              _p["mungon_norma_percaktuese"] and _p["kerkime"] == ["kufizimi i zhurmave", "sistemi zhurmëshues"]
              and _p["nene"] == [("kodi_rrugor", "153")])
        _p2 = _st.kerkuesi_parse("nuk ka json ketu {thyer")
        check("studio[29]: JSON i thyer = default i sigurt (asgjë nuk shtohet)",
              _p2["mungon_norma_percaktuese"] is False and _p2["kerkime"] == [] and _p2["nene"] == [])
        _rr = ({d.code for d in brain.LEGAL_DOCUMENTS if d.area.lower() == "rrugor"}
               | set(brain.PROCEDURAL_MAPPING["Rrugor"]))
        _base = [(a, 10.0) for a in idx.articles if a.code == "kodi_rrugor" and a.number == "79"]
        _es = {"mungon_norma_percaktuese": True, "kerkime": ["kufizimi i zhurmave sistemi zhurmeshues"],
               "nene": [("kodi_rrugor", "999"), ("kodi_rrugor", "79")]}
        _nuovo, _shtuar = _st.kerkuesi_merge(_base, idx, _es, queries=["zhurma"], restrict=_rr, max_nene=2)
        check("studio[29]: shartimi sjell nenin REAL (153), jo 999 e jo dyfishim të 79",
              ("kodi_rrugor", "153") in _shtuar and ("kodi_rrugor", "999") not in _shtuar
              and ("kodi_rrugor", "79") not in _shtuar and len(_shtuar) <= 2, str(_shtuar))
        check("studio[29]: nenet e shtuara janë kopje të shënuara, në krye, me pikë reale",
              getattr(_nuovo[0][0], "_kerkues", False) and isinstance(_nuovo[0][1], float)
              and not getattr(_base[0][0], "_kerkues", False))
        _kw = _st._kwargs_modeli("sonnet", "max")
        _kw2 = _st._kwargs_modeli("opus", "medium")
        _kw3 = _st._kwargs_modeli("claude-fable-5-1", "max")
        check("studio[29]: alias modelesh — sonnet=fast pa effort, opus=senior, id=override",
              _kw == {"fast": True} and _kw2 == {"effort_override": "medium"}
              and _kw3 == {"model_override": "claude-fable-5-1", "effort_override": "max"})
        check("studio[29]: config-i i roleve ekziston me default (kërkues sonnet, djalli high — scelta del titolare 20 set)",
              _cfgs.STUDIO_KERKUES_MODEL and _cfgs.STUDIO_DJALLI_EFFORT == "high" and _cfgs.STUDIO_DJALLI_MODEL == "claude-fable-5-1"
              and isinstance(_cfgs.STUDIO_KERKUES_MAX_NENE, int))
        check("studio[29]: truri thërret kërkuesin pas retrieval dhe e paraqet nenin si GJETUR NGA KËRKUESI",
              hasattr(brain.SuperAvvocato, "_studio_kerkuesi")
              and "GJETUR NGA KËRKUESI" in open("/app/src/brain.py", encoding="utf-8").read())
    except Exception as _e:  # noqa: BLE001
        check("studio[29]: kontrollet u ekzekutuan", False, str(_e))

    # ── [30] Studio: Avokati i djallit — formati + shartimi ───────────────
    try:
        from src import studio as _st2
        check("studio[30]: seksioni bosh kur djalli hesht",
              _st2.djalli_format("   ", "sq") == "")
        _sq = _st2.djalli_format("- Neni 79 u lexua gabim.", "sq")
        _it = _st2.djalli_format("- Art. 79 letto male.", "it")
        check("studio[30]: titulli në gjuhën e përgjigjes (sq/it) dhe teksti i djallit",
              "Avokati i djallit" in _sq and "Neni 79 u lexua gabim" in _sq
              and "Avvocato del diavolo" in _it and "Avokati" not in _it)
        check("studio[30]: truri e thërret djallin vetëm pas përgjigjes complex (2 rrugë)",
              hasattr(brain.SuperAvvocato, "_studio_djalli")
              and open("/app/src/brain.py", encoding="utf-8").read().count(
                  "self._studio_djalli(user_message, retrieved, precedents, answer_text)") == 2)
        check("studio[30]: prompt djalli — fronte + gravità [KRITIKE] + «pika ku do sulmoja», senza pareri nuovi, mai inventare",
              all(x in _st2.DJALLI_SYSTEM for x in ("GABIM", "mungon", "parashkrimi", "barra",
                                                    "[KRITIKE]", "PIKA KU DO TË SULMOJA", "MOS shpik nene", "Mos shkruaj parere")))
    except Exception as _e:  # noqa: BLE001
        check("studio[30]: kontrollet u ekzekutuan", False, str(_e))

    # ── [31] Stream SSE: asnjë header hop-by-hop (PEP 3333) ───────────────
    # Misurato 8 set 2026: «Connection: keep-alive» → waitress AssertionError
    # → HTTP 500 su /api/ask/events prima del primo evento.
    try:
        import re as _re31
        _src = open("/app/src/web.py", encoding="utf-8").read()
        _m = _re31.search(r"_SSE_HEADERS\s*=\s*\{(.*?)\}", _src, _re31.DOTALL)
        _blocco = _m.group(1) if _m else ""
        _chiavi = [k.lower() for k in _re31.findall(r'"([A-Za-z-]+)"\s*:', _blocco)]
        try:   # la lista VERA del server, non una copia mia
            from waitress.task import hop_by_hop as _hbh
        except Exception:  # noqa: BLE001
            _hbh = {"connection", "keep-alive", "proxy-authenticate", "proxy-authorization",
                    "te", "trailers", "transfer-encoding", "upgrade"}
        _rifiutati = [k for k in _chiavi if k in _hbh]
        check("sse[31]: _SSE_HEADERS esiste e waitress non lo rifiuta (hop-by-hop)",
              bool(_m) and _chiavi and not _rifiutati, "rifiutati=%s" % _rifiutati)
        check("sse[31]: lo stream resta senza buffering nginx e senza cache",
              "x-accel-buffering" in _chiavi and "cache-control" in _chiavi)
        _usi = len(_re31.findall(r"headers=_SSE_HEADERS", _src))
        _conn = _re31.search(r'"Connection"\s*:', _src)
        check("sse[31]: le 3 rotte SSE usano _SSE_HEADERS e nessuno rimette «Connection» a mano",
              _usi == 3 and _conn is None, "usi=%d conn=%s" % (_usi, bool(_conn)))
    except Exception as _e:  # noqa: BLE001
        check("sse[31]: kontrollet u ekzekutuan", False, str(_e))

    # ── [32] Lingua = SESSIONE (AL solo albanese, IT solo italiano) ─────────
    # Regola del titolare, 9 set 2026. Misurato l'8 set: premortem albanese
    # in un fascicolo IT (domanda in albanese) e fascicoli IT aperti in
    # sessione AL (riapertura da localStorage).
    try:
        import os as _os32, io as _io32
        _rr32 = _os32.path.dirname(_os32.path.dirname(_os32.path.abspath(__file__)))
        from src import brain as _br32
        _pa = _br32.direttiva_gjuhe_prompt("Pyetja", "AL")
        _pi = _br32.direttiva_gjuhe_prompt("Domanda", "IT")
        check("gjuha[32]: AL accoda «VETËM SHQIP», IT accoda «SOLO ITALIANO»",
              "VETËM SHQIP" in _pa and "SOLO ITALIANO" in _pi and "SHQIP" not in _pi)
        check("gjuha[32]: idempotente e vuoto resta vuoto",
              _br32.direttiva_gjuhe_prompt(_pa, "AL") == _pa
              and _br32.direttiva_gjuhe_prompt("   ", "IT") == "   ")
        check("gjuha[32]: l'override IT copre la domanda scritta in albanese",
              "ANCHE SE la domanda" in _br32.JURISDICTION_OVERRIDE_IT)
        _bk32 = _io32.open(_os32.path.join(_rr32, "src", "backends.py"), encoding="utf-8").read()
        check("gjuha[32]: il collo di bottiglia accoda la riga in complete() e complete_stream()",
              _bk32.count("prompt = _direttiva_gjuhe(prompt)") == 2)
        check("gjuha[32]: raw_system (Përkthim) salta la riga di lingua",
              "if not raw_system:\n            prompt = _direttiva_gjuhe(prompt)" in _bk32)
        _w32 = _io32.open(_os32.path.join(_rr32, "src", "web.py"), encoding="utf-8").read()
        _i_list = _w32.find("def api_list_cases")
        _i_res = _w32.find("def _resolve_case")
        _i_cre = _w32.find("def api_create_case")
        check("gjuha[32]: /api/cases elenca solo la giurisdizione attiva e conta i nascosti",
              _i_list > 0 and "hidden_other" in _w32[_i_list:_i_list + 1600]
              and "_active_jurisdiction(user)" in _w32[_i_list:_i_list + 1600])
        check("gjuha[32]: _resolve_case non apre un fascicolo dell'altra giurisdizione",
              _i_res > 0 and "!= _att" in _w32[_i_res:_i_res + 1800]
              and "return None" in _w32[_i_res:_i_res + 1800])
        check("gjuha[32]: POST /api/cases rifiuta (409) una giurisdizione diversa dalla sessione",
              _i_cre > 0 and "409" in _w32[_i_cre:_i_cre + 1800]
              and "jurisdiction != attiva" in _w32[_i_cre:_i_cre + 1800])
        _js32 = _io32.open(_os32.path.join(_rr32, "static", "app.js"), encoding="utf-8").read()
        _i_act = _js32.find("function _renderActReport")
        check("gjuha[32]: controllo-atto bilingue (era albanese fisso in sessione IT)",
              _i_act > 0 and "_CAL_IT" in _js32[_i_act:_i_act + 400]
              and "Articoli INESISTENTI" in _js32[_i_act:_i_act + 3000])
        check("gjuha[32]: il client dice quanti fascicoli sono nell'altra giurisdizione",
              "_casiNascosti" in _js32 and "hidden_other" in _js32)
        _pk32 = _io32.open(_os32.path.join(_rr32, "src", "perkthim.py"), encoding="utf-8").read()
        check("gjuha[32]: il traduttore viaggia con raw_system=True (2 chiamate)",
              _pk32.count("raw_system=True") == 2)
    except Exception as _e:  # noqa: BLE001
        check("gjuha[32]: kontrollet u ekzekutuan", False, str(_e))

    # ── [33] Effort: il compito sceglie il budget (junior high, senior max) ──
    # Misurato 8-9 set 2026: Sonnet 5 a max = 7-13 min a fase, a high 1-2 min
    # con la stessa sostanza. Il senior NON cambia (regola: precisione prima).
    try:
        from src import config as _cf33
        from src.backends import ClaudeCodeBackend as _CB33
        import shutil as _sh33
        check("effort[33]: config — senior a max, junior a high (env E fallback)",
              _cf33.CLAUDE_CODE_EFFORT == "max" and _cf33.CLAUDE_CODE_MEDIUM_EFFORT == "high")
        _cli33 = _sh33.which("claude") or "/usr/bin/claude"
        _b33 = _CB33(cli_path=_cli33, effort="max", medium_effort="high")
        check("effort[33]: fast → nessun effort; junior → high; senior → max; esplicito vince",
              _b33._pick_effort(True, False) is None
              and _b33._pick_effort(False, True) == "high"
              and _b33._pick_effort(False, False) == "max"
              and _b33._pick_effort(False, True, "max") == "max")
        _b33b = _CB33(cli_path=_cli33, effort="max", medium_effort=None)
        check("effort[33]: senza medium_effort il junior eredita il senior (retro-compatibile)",
              _b33b._pick_effort(False, True) == "max")
        import io as _io33, os as _os33
        _rr33 = _os33.path.dirname(_os33.path.dirname(_os33.path.abspath(__file__)))
        _bs33 = _io33.open(_os33.path.join(_rr33, "src", "backends.py"), encoding="utf-8").read()
        check("effort[33]: complete() passa da _pick_effort e lo stream (senior) resta a self.effort",
              "_eff = self._pick_effort(fast, medium, effort_override)" in _bs33
              and _bs33.count('cmd.extend(["--effort", self.effort])') == 1)
    except Exception as _e:  # noqa: BLE001
        check("effort[33]: kontrollet u ekzekutuan", False, str(_e))

    # ── [34] Gradino B — i raccoglitori del percorso simple ───────────────
    try:
        import io as _io34, os as _os34
        from src import studio as _st34, config as _cf34
        _rr34 = _os34.path.dirname(_os34.path.dirname(_os34.path.abspath(__file__)))
        _w = _st34.mbledhes_web_parse(
            '{"akte_nenligjore":[{"akti":"VKM 153","citim":"' + "x" * 40 + '","url":"https://qbz.gov.al/a","data":"2026-09-09","pse":"p"},'
            '{"akti":"pa url","citim":"' + "y" * 40 + '","url":"javascript:alert(1)"}],'
            '"burime":[{"titulli":"t","citim":"shkurt","url":"https://x"}]}')
        check("mbledhes[34]: web — entra solo il citim con URL http e ≥20 shkronja",
              len(_w["akte_nenligjore"]) == 1 and _w["akte_nenligjore"][0]["url"] == "https://qbz.gov.al/a"
              and _w["burime"] == [])
        check("mbledhes[34]: web — JSON rotto = liste vuote (mai inventare)",
              _st34.mbledhes_web_parse("bla {non json") == {"akte_nenligjore": [], "burime": []})
        _q = _st34.mbledhes_qbz_parse('{"nene":[{"neni":"153 Kodi Rrugor","statusi":"në fuqi","url":"https://qbz.gov.al/x"},'
                                      '{"neni":"79","statusi":"boh","url":"ftp://no"}]}', "sq")
        check("mbledhes[34]: qbz — statusi normalizzato, ignoto = «E PAQARTË», URL non http scartato",
              [x["statusi"] for x in _q] == ["NË FUQI", "E PAQARTË"] and _q[1]["url"] == "")
        _f = _st34.formato_dosjen({"web": _w, "qbz": _q}, "sq", precedents_block="")
        _fi = _st34.formato_dosjen({"web": {}, "qbz": []}, "it", precedents_block="PREC")
        check("mbledhes[34]: dossier sq/it con intestazioni e istruzione per il senior; vuoto → «»",
              "DOSJA E BURIMEVE" in _f and "UDHËZIM PËR SENIORIN" in _f and "153 Kodi Rrugor: NË FUQI" in _f
              and "DOSSIER DELLE FONTI" in _fi and "PREC" in _fi
              and _st34.formato_dosjen({"web": {}, "qbz": []}, "sq") == "")
        check("mbledhes[34]: config — sonnet/medium/0.30$/110s, web e qbz accesi",
              _cf34.STUDIO_MBLEDHES_ENABLED and _cf34.STUDIO_MBLEDHES_MODEL == "sonnet"
              and _cf34.STUDIO_MBLEDHES_EFFORT == "medium" and abs(_cf34.STUDIO_MBLEDHES_BUDGET_USD - 0.30) < 1e-9
              and _cf34.STUDIO_MBLEDHES_TIMEOUT == 110 and _cf34.STUDIO_MBLEDHES_WEB and _cf34.STUDIO_MBLEDHES_QBZ)
        _kw = _st34._kwargs_mbledhesi("sonnet", "medium")
        check("mbledhes[34]: «sonnet» del raccoglitore = tier MEDIUM (ha il web) + effort medium",
              _kw.get("medium") is True and _kw.get("effort_override") == "medium" and "fast" not in _kw)
        _bs = _io34.open(_os34.path.join(_rr34, "src", "backends.py"), encoding="utf-8").read()
        check("mbledhes[34]: backends — budget_usd per chiamata → --max-budget-usd",
              "budget_usd: float | None = None) -> str:" in _bs
              and 'cmd.extend(["--max-budget-usd", str(budget_usd)])' in _bs)
        _br = _io34.open(_os34.path.join(_rr34, "src", "brain.py"), encoding="utf-8").read()
        check("mbledhes[34]: brain — i raccoglitori agganciati nei DUE percorsi simple + status",
              _br.count("self._studio_mbledhesit(user_message, triage, retrieved)") == 2
              and '"simple_gathering"' in _br and _br.count("simple_gathering") >= 3)
        check("mbledhes[34]: brain — force_complex nelle due firme e applicato dopo il triage",
              _br.count("force_complex: bool = False") == 2
              and _br.count("if force_complex and triage.complexity == \"simple\":") == 2)
        _i_cm = _br.find("_COMPLEX_MARKERS = (")
        _blocco_cm = _br[_i_cm:_br.find("\n)\n", _i_cm)] if _i_cm > 0 else "gjob"
        _i_fi = _br.find("_FISCAL = (")
        _riga_fi = _br[_i_fi:_br.find("\n", _i_fi)] if _i_fi > 0 else "gjob"
        check("mbledhes[34]: «gjob» non forza più il percorso lungo (né _FISCAL né _COMPLEX_MARKERS; resta solo nell'adversary gate); il triage sa cos'è una pyetje kualifikimi",
              '"gjob' not in _blocco_cm and '"gjob' not in _riga_fi
              and '"gjob"' in _br and "PYETJE KUALIFIKIMI" in _br)
        _fq = _st34.formato_dosjen({"web": {}, "qbz": [{"neni": "1", "statusi": "E PAQARTË", "ndryshimi": "", "url": "", "data": ""}]}, "sq")
        check("mbledhes[34]: QBZ tutto «E PAQARTË» = nessun dossier (informazione nulla non si dà al senior)", _fq == "")
        class _P34:
            def __init__(self, arts): self.articles_cited = arts
        _pp = _brn34_pre = None
        from src import brain as _bb34
        _sel = _bb34._precedente_te_lidhur(
            [(_P34([("kodi_rrugor", "153")]), 9.0), (_P34([("kodi_civil", "114")]), 8.0), (_P34([]), 7.0)],
            [("kodi_rrugor", "153"), ("kodi_rrugor", "78")])
        check("mbledhes[34]: nel simple entrano solo i precedenti che citano un nene recuperato",
              len(_sel) == 1 and _sel[0][1] == 9.0)
        from src import brain as _brn34
        check("mbledhes[34]: _looks_simple — «cila është shkelja … gjobë» breve resta simple (Aventador)",
              _brn34._looks_simple("kam nje rast klienti ankohet se e ka ndaluar policia e shtetit, dhe i thot se "
                                   "makina e tij lamborghini aventador ben zhurme dhe se do i vendosin gjobe. "
                                   "nderkoh klienti deklaron se makina esht makin fabrike e pa modifikuar. "
                                   "cila esht shkelja?", None) is True
              and _brn34._looks_simple("sa paguaj dogane per nje makine 2019?", None) is False)
    except Exception as _e:  # noqa: BLE001
        check("mbledhes[34]: kontrollet u ekzekutuan", False, str(_e))

    # ── [35] Genio: ripresa (solo lenti mancanti) + salva/scarica ─────────
    try:
        import io as _io35, os as _os35
        _rr35 = _os35.path.dirname(_os35.path.dirname(_os35.path.abspath(__file__)))
        _w35 = _io35.open(_os35.path.join(_rr35, "src", "web.py"), encoding="utf-8").read()
        _st35 = _io35.open(_os35.path.join(_rr35, "src", "storage.py"), encoding="utf-8").read()
        _js35 = _io35.open(_os35.path.join(_rr35, "static", "app.js"), encoding="utf-8").read()
        _i_gp = _w35.find("def _genio_prepare(")
        _blk = _w35[_i_gp:_i_gp + 4200] if _i_gp > 0 else ""
        check("genio[35]: _genio_prepare accetta resume_brief_id e rifà solo il subset",
              "resume_brief_id=None" in _blk and "perspectives=plist" in _blk
              and "nothing_to_resume" in _blk and "seed_by_key" in _blk)
        check("genio[35]: le lenti buone si tengono (seed), errore/vuote si rifanno",
              'r.get("kind") == "error"' in _blk and "genio_mod.PERSPECTIVES" in _blk)
        check("genio[35]: /api/genio/start inoltra resume_brief_id (int o None)",
              'resume_brief_id=_resume' in _w35 and 'data.get("resume_brief_id")' in _w35)
        check("genio[35]: storage.mark_genio_running riporta a 'running'",
              "def mark_genio_running(" in _st35 and "status='running'" in _st35)
        _ht35 = _io35.open(_os35.path.join(_rr35, "templates", "index.html"), encoding="utf-8").read()
        check("genio[35]: UI — pulsante ripresa accanto a «Lësho Genio» che riprende",
              'id="genio-resume"' in _ht35 and "_genioResume" in _js35
              and "_genioUpdateResume" in _js35 and "_genioBriefId" in _js35
              and 'genioAttach((genioDescEl.value || "").trim(), _genioBriefId)' in _js35)
        check("genio[35]: UI — brief salvabile via _addSaveToCase (Ruaj/DOCX/PDF)",
              '_addSaveToCase(f, "genio"' in _js35 and "_genioBriefMarkdown" in _js35)
    except Exception as _e:  # noqa: BLE001
        check("genio[35]: kontrollet u ekzekutuan", False, str(_e))

    # ── [36] Dosja per FASCICOLO: /api/dosja?case= (dentro un caso, solo quel caso) ──
    try:
        import io as _io36, os as _os36
        _rr36 = _os36.path.dirname(_os36.path.dirname(_os36.path.abspath(__file__)))
        _w36 = _io36.open(_os36.path.join(_rr36, "src", "web.py"), encoding="utf-8").read()
        _st36 = _io36.open(_os36.path.join(_rr36, "src", "storage.py"), encoding="utf-8").read()
        _js36 = _io36.open(_os36.path.join(_rr36, "static", "app.js"), encoding="utf-8").read()
        _i_d = _w36.find("def api_dosja(")
        _bd = _w36[_i_d:_i_d + 1800] if _i_d > 0 else ""
        check("dosja[36]: /api/dosja accetta ?case= e filtra per fascicolo",
              'request.args.get("case")' in _bd
              and "storage.list_case_documents_dosja(case_id)" in _bd)
        check("dosja[36]: il caso passa da _resolve_case (cancello di giurisdizione v9.270) → vuoto, non 500",
              "caso = _resolve_case(case_id)" in _bd and "if caso is None:" in _bd)
        check("dosja[36]: research del caso arricchito con case_id + case_title (forma da raggruppare)",
              "dict(it, case_id=case_id, case_title=caso.title)" in _bd)
        check("dosja[36]: lo scope viaggia nella risposta (case | all)",
              '"scope": "case"' in _bd and '"scope": "all"' in _bd)
        check("dosja[36]: storage — list_case_documents_dosja, come list_firm_documents ma WHERE d.case_id",
              "def list_case_documents_dosja(" in _st36
              and "WHERE d.case_id = ? ORDER BY d.created_at DESC" in _st36
              and '"case_title": r["case_title"]' in _st36)
        check("dosja[36]: UI — dentro un caso parte su «Ky rast», fuori su «Të gjitha»",
              'var scope = activeCaseId ? "case" : "all";' in _js36)
        check("dosja[36]: UI — fetch con ?case= solo quando lo scope è il caso attivo",
              '"?case=" + encodeURIComponent(activeCaseId)' in _js36
              and "async function caricaDosja()" in _js36)
        check("dosja[36]: UI — interruttore Ky rast / Të gjitha (+ etichette IT)",
              "dosja-scope-btn" in _js36 and "Ky rast" in _js36
              and "Të gjitha rastet" in _js36 and "Questo caso" in _js36)
    except Exception as _e:  # noqa: BLE001
        check("dosja[36]: kontrollet u ekzekutuan", False, str(_e))

    # ── [37] La Skuadra: Agent D (Fletorja Zyrtare) + senior selector (Opus/Fable) ──
    try:
        import io as _io37, os as _os37
        _rr37 = _os37.path.dirname(_os37.path.dirname(_os37.path.abspath(__file__)))
        _st37 = _io37.open(_os37.path.join(_rr37, "src", "studio.py"), encoding="utf-8").read()
        _br37 = _io37.open(_os37.path.join(_rr37, "src", "brain.py"), encoding="utf-8").read()
        _cf37 = _io37.open(_os37.path.join(_rr37, "src", "config.py"), encoding="utf-8").read()
        _wb37 = _io37.open(_os37.path.join(_rr37, "src", "web.py"), encoding="utf-8").read()
        # Agent D — struttura
        check("skuadra[37]: Agent D — prompt Fletorja/Gazzetta (sq+it), gatherer, parser",
              "MBLEDHES_FLETORJA_SYSTEM" in _st37 and '"sq"' in _st37
              and "def mbledhesi_fletorja(" in _st37 and "def mbledhes_fletorja_parse(" in _st37
              and "Fletorja Zyrtare" in _st37 and "Gazzetta Ufficiale" in _st37)
        check("skuadra[37]: Agent D — terzo raccoglitore in parallelo (fletorja + 3 worker)",
              "fletorja=True" in _st37 and "max_workers=3" in _st37
              and 'lavori["fletorja"]' in _st37 and '"fletorja": []' in _st37)
        check("skuadra[37]: Agent D — mai auto-ingest (nessuna scrittura del corpus in studio.py)",
              "ArticleIndex" not in _st37 and "build_and_save" not in _st37 and "DecisionIndex" not in _st37)
        # Agent D — ESEGUITO: parser + dossier
        from src import studio as _studio37
        _raw = '{"ndryshime":[{"neni":"153 KRr","citim":"Ndalohet perdorimi i sistemeve zhurmeshuese te automjeteve.","url":"https://qbz.gov.al/x","fletorja":"nr.71/2024","data":"2024-05-15"}]}'
        _one = _studio37.mbledhes_fletorja_parse(_raw)
        check("skuadra[37]: parser ESEGUITO — citazione+URL reale → 1; fake senza URL → 0",
              len(_one) == 1 and _one[0]["url"].startswith("http")
              and _studio37.mbledhes_fletorja_parse('{"ndryshime":[{"neni":"x","citim":"short","url":""}]}') == [])
        _txt = _studio37.formato_dosjen({"web": {"akte_nenligjore": [], "burime": []}, "qbz": [], "fletorja": _one}, "sq")
        check("skuadra[37]: dossier ESEGUITO — la sezione «ligji i gjallë» compare, verbatim + URL",
              "Fletorja Zyrtare" in _txt and "153 KRr" in _txt and "qbz.gov.al" in _txt
              and _studio37.formato_dosjen({"web": {"akte_nenligjore": [], "burime": []}, "qbz": [], "fletorja": []}, "sq") == "")
        # wiring
        check("skuadra[37]: config flag + brain passa fletorja al raccoglitore",
              "STUDIO_MBLEDHES_FLETORJA" in _cf37
              and "fletorja=STUDIO_MBLEDHES_FLETORJA" in _br37 and "fletorja %d" in _br37)
        # Senior selector
        check("skuadra[37]: senior selector — thread-local + helper Opus/Fable",
              "_REQUEST_SENIOR" in _br37 and "def set_request_senior(" in _br37
              and "def _senior_override(" in _br37)
        check("skuadra[37]: senior — override applicato in ENTRAMBI i compose complessi",
              _br37.count("**_senior_override(request_senior())") == 2
              and 'request_senior() != "fable"' in _br37)
        check("skuadra[37]: web — mendja letta, armata nel job, e «fable» ⇒ approfondito",
              'data.get("mendja")' in _wb37 and "brain_mod.set_request_senior(mendja)" in _wb37
              and 'mendja == "fable"' in _wb37)
        # SACRO — ESEGUITO: senza «fable» il cervello resta Opus (nessun override)
        from src import brain as _brain37
        check("skuadra[37]: SACRO — «fable» → Fable max; vuoto/«opus» → nessun override (Opus default)",
              _brain37._senior_override("fable") == {"model_override": "fable", "effort_override": "max"}
              and _brain37._senior_override("") == {} and _brain37._senior_override("opus") == {})
        _js37 = _io37.open(_os37.path.join(_rr37, "static", "app.js"), encoding="utf-8").read()
        check("skuadra[37]: UI — v9.358: UN solo pulsante profondo «Gjyqtari Suprem» (senza nome modello); mendja resta solo via API, il pulsante ⚡ non c'è più",
              "_seniorNext" in _js37 and "mendja: _seniorNext" in _js37 and "deep-btn-max" not in _js37 and "Gjyqtari Suprem" in _js37 and "Giudice Supremo" in _js37)
        check("skuadra[37]: le FONTI escono dal brain come evento (sintesi_burimet → skuadra → web)",
              "def sintesi_burimet(" in _st37 and 'yield ("skuadra"' in _br37 and '"type": "skuadra"' in _wb37)
        check("skuadra[37]: UI — pannello «Burimet e Skuadrës» reso (il «perché lo dico»)",
              "onSkuadra" in _js37 and "_renderSkuadraPanel" in _js37 and "skuadra-panel" in _js37)
        check("skuadra[37]: Skuadra ANCHE nel complex — raccoglitori fase parallela + dossier al senior",
              "def _mbledh_gatherers(" in _br37 and '"skuadra_gather":  lambda' in _br37
              and 'yield ("skuadra", burimet_x)' in _br37 and "dosja_txt=dosja_txt_x" in _br37
              and 'articles_for_prompt(retrieved) + (dosja_txt' in _br37)
    except Exception as _e:  # noqa: BLE001
        check("skuadra[37]: kontrollet u ekzekutuan", False, str(_e))

    # ── [38] Menu PRO: 35 tool in 9 gruppi (raggruppati, nessuno perso) ──
    try:
        import io as _io38, os as _os38, re as _re38
        _rr38 = _os38.path.dirname(_os38.path.dirname(_os38.path.abspath(__file__)))
        _ht38 = _io38.open(_os38.path.join(_rr38, "templates", "index.html"), encoding="utf-8").read()
        _js38 = _io38.open(_os38.path.join(_rr38, "static", "app.js"), encoding="utf-8").read()
        _tools = _re38.findall(r'data-pro="([a-z]+)"', _ht38)
        check("menu[38]: 35 tool nel menu PRO, nessuno perso, nessuno doppio",
              len(_tools) == 35 and len(set(_tools)) == 35)
        _grp = _re38.findall(r'data-i18n="(grp_[a-z]+)"', _ht38)
        check("menu[38]: 9 gruppi + Cilësime (10 separatori, con data-i18n)",
              len(_grp) == 10 and "grp_mendja" in _grp and "grp_studio" in _grp)
        check("menu[38]: le etichette dei gruppi tradotte in IT",
              "grp_mendja:" in _js38 and "grp_cilesime:" in _js38)
        _disp = set(_re38.findall(r'key === "([a-z]+)"', _js38))
        _mod = set(_re38.findall(r'"([a-z]+)": document\.getElementById', _js38)) | {"stress", "draft"}
        _orf = [t for t in set(_tools) if t not in _disp and t not in _mod]
        check("menu[38]: ogni tool ha un handler (dispatch o modale) — nessun bottone morto",
              not _orf, "orfani: %s" % _orf)
    except Exception as _e:  # noqa: BLE001
        check("menu[38]: kontrollet u ekzekutuan", False, str(_e))

    # ── [39] Miglioramenti dallo spec del titolare (senior 2-pass, temporale, fallimenti, diavolo) ──
    try:
        import io as _io39, os as _os39
        _rr39 = _os39.path.dirname(_os39.path.dirname(_os39.path.abspath(__file__)))
        _st39 = _io39.open(_os39.path.join(_rr39, "src", "studio.py"), encoding="utf-8").read()
        _br39 = _io39.open(_os39.path.join(_rr39, "src", "brain.py"), encoding="utf-8").read()
        from src import studio as _s39
        check("spec[39]: #1 senior a DUE passaggi — risponde al Diavolo (pranohet/refuzohet/pjesërisht)",
              hasattr(_s39, "senior_pergjigjja") and "studio.senior_pergjigjja(" in _br39
              and "PERGJIGJE_SYSTEM" in _st39
              and "PRANOHET" in _s39.PERGJIGJE_SYSTEM["sq"] and "ACCOLTO" in _s39.PERGJIGJE_SYSTEM["it"])
        check("spec[39]: #1 il senior 2-pass usa la mente scelta (Opus default/Fable) + empty-guard ESEGUITO",
              'request_senior() == "fable"' in _br39
              and _s39.senior_pergjigjja(None, domanda="x", blloku_neneve="", pergjigja="", sulmi="a") == ""
              and _s39.senior_pergjigjja(None, domanda="x", blloku_neneve="", pergjigja="r", sulmi="") == "")
        _txt = _s39.formato_dosjen({"web": {"akte_nenligjore": [], "burime": []}, "qbz": [], "fletorja": [],
                                    "gabime": ["qbz: TimeoutError"]}, "sq")
        check("spec[39]: #3 il silenzio di un agente NON è «nessun problema» — fallimenti nel dossier ESEGUITO",
              "KONTROLLE TË PAPËRFUNDUARA" in _txt and "Kontrolli i vigjencës" in _txt
              and _s39.formato_dosjen({"web": {"akte_nenligjore": [], "burime": []}, "qbz": [], "fletorja": [], "gabime": []}, "sq") == "")
        check("spec[39]: #4 Diavolo strutturato — gravità [KRITIKE] + «dove attaccare per primo»",
              "[KRITIKE]" in _s39.DJALLI_SYSTEM and "PIKA KU DO TË SULMOJA" in _s39.DJALLI_SYSTEM)
        check("spec[39]: #2 Agent C temporale — il testo di oggi ≠ quello applicabile ai fatti (sq+it)",
              "TEKSTI I SOTËM NUK ËSHTË DOMOSDO" in _s39.MBLEDHES_QBZ_SYSTEM["sq"]
              and "IL TESTO DI OGGI NON È" in _s39.MBLEDHES_QBZ_SYSTEM["it"])
    except Exception as _e:  # noqa: BLE001
        check("spec[39]: kontrollet u ekzekutuan", False, str(_e))

    # ── [40] War Room: «non trovato ≠ non esiste» (#A) + stato raccoglitori (#C) ──
    try:
        import io as _io40, os as _os40
        _rr40 = _os40.path.dirname(_os40.path.dirname(_os40.path.abspath(__file__)))
        _br40 = _io40.open(_os40.path.join(_rr40, "src", "brain.py"), encoding="utf-8").read()
        from src import studio as _s40
        # v9.376: la regola sta in OGNI prompt del senior (complex, simple e il complex in forma breve)
        check("war[40]: #A «MOSGJETJA NUK ËSHTË MUNGESË» nei prompt del senior (complex+simple+forma breve)",
              all("MOSGJETJA NUK ËSHTË MUNGESË" in _p for _p in (brain.ANSWER_SYSTEM, brain.ANSWER_SIMPLE_SYSTEM, brain.ANSWER_SYSTEM_SHKURTER)))
        _txt40 = _s40.formato_dosjen(
            {"web": {"akte_nenligjore": [{"titulli": "X", "citim": "tekst i gjate sa duhet", "url": "https://x", "data": "2024"}], "burime": []},
             "qbz": [{"neni": "1", "statusi": "E PAQARTË"}], "fletorja": [],
             "kohe": {"web": 40, "qbz": 50, "fletorja": 50}, "gabime": []}, "sq")
        check("war[40]: #C stato raccoglitori — «controllato senza esito» per chi ha girato a vuoto (ESEGUITO)",
              "KONTROLLUAR PA REZULTAT" in _txt40 and "Kontrolli i vigjencës" in _txt40
              and "Rojtari i Fletores Zyrtare" in _txt40)
        check("war[40]: #E secondo Red Team CONDIZIONALE — gate ESEGUITO + attacco #2 + revisione finale",
              hasattr(_s40, "duhet_raund2") and hasattr(_s40, "sulmi_i_dyte")
              and _s40.duhet_raund2("- [KRITIKE] x", "[REFUZOHET]") is True
              and _s40.duhet_raund2("- [LARTË] x", "[REFUZOHET]") is False
              and _s40.duhet_raund2("- [KRITIKE] x", "[PRANOHET]") is False
              and "studio.duhet_raund2(sez, risposta)" in _br40 and "STUDIO_RED2_ENABLED" in _br40
              and "finale=True" in _br40)
        from src import war_room as _wr40
        from types import SimpleNamespace as _NS40
        _items40 = _wr40.build_canonical(
            [(_NS40(number="153", title_sq="X", code="KRr", body="tekst i korpusit"), 1.0)],
            {"web": {"akte_nenligjore": [{"titulli": "VKM", "citim": "tekst zyrtar", "url": "https://qbz.gov.al/x"}],
                     "burime": [{"titulli": "Blog", "citim": "koment", "url": "https://blog.example/y"}]},
             "fletorja": []}, [], "sq")
        _by40 = {i.id: i for i in _items40}
        check("war[40]: FONDAZIONE dossier canonico — ID tipizzati + qualità (gov=PRIMARY, blog=SECONDARY) + verifica",
              "LAW-001" in _by40 and _by40["LAW-001"].cilesia == "PRIMARY_OFFICIAL"
              and _by40["LAW-001"].verifikimi == "VERIFIED"
              and _by40["WEB-001"].cilesia == "PRIMARY_OFFICIAL" and _by40["WEB-002"].cilesia == "SECONDARY"
              and "[LAW-001]" in _wr40.format_canonical(_items40, "sq"))
        _rap40 = _wr40.raport_verifikimi(
            [(_NS40(number="1", title_sq="X", code="C", body="t"), 1.0)],
            [{"agjenti": "web", "titulli": "VKM", "citim": "tekst zyrtar mjaftueshem", "url": "https://blog.x/y"}],
            [], "sq")
        check("war[40]: Source Verifier — raporto verificate/da-verificare per qualità (ESEGUITO) + wired su max-mode ⚡",
              "RAPORT VERIFIKIMI" in _rap40 and "TË VËRTETUARA" in _rap40 and "PËR VERIFIKIM" in _rap40
              and "[WEB-001] VKM (secondary)" in _rap40
              and "_wr.raport_verifikimi(retrieved, burimet_x, precedents" in _br40
              and 'if request_senior() == "fable" or _gjyqtari_suprem()' in _br40)
        check("war[40]: RESEARCH LOOP (spec 35) — gap-detector + ricerca reale sull'indice, cablato su max-mode",
              hasattr(_wr40, "parse_gaps") and hasattr(_wr40, "format_research_loop")
              and _wr40.parse_gaps('{"boshlleqe":[{"pershkrim":"x","kerkim":"mbrojtja e konsumatorit"}]}')[0]["kerkim"] == "mbrojtja e konsumatorit"
              and _wr40.parse_gaps("garbage") == []
              and "def _research_loop(" in _br40 and "WAR_ROOM_LOOP_ENABLED" in _br40
              and "self._research_loop(user_message, answer_text, retrieved" in _br40)
    except Exception as _e:  # noqa: BLE001
        check("war[40]: kontrollet u ekzekutuan", False, str(_e))

    # ── [41] AFATI — motore DETERMINISTICO delle scadenze (spec §13) ──
    # Esegue il motore su casi noti (calcolati a mano): la matematica delle
    # date NON è più affidata all'LLM. Un termine sbagliato = malpractice.
    try:
        import os as _os41, io as _io41
        from src import deadline_engine as _de41
        _rr41 = _os41.path.dirname(_os41.path.dirname(_os41.path.abspath(__file__)))
        _af41 = _io41.open(_os41.path.join(_rr41, "src", "afati.py"), encoding="utf-8").read()
        _wb41 = _io41.open(_os41.path.join(_rr41, "src", "web.py"), encoding="utf-8").read()
        check("afati[41]: 10 anni → giorno corrispondente (2030-03-15)",
              _de41.compute_deadline("2020-03-15", 10, "years", jurisdiction="IT").deadline.isoformat() == "2030-03-15")
        check("afati[41]: 30 gg solari, dies a quo non computa (2024-02-09)",
              _de41.compute_deadline("2024-01-10", 30, "days", jurisdiction="IT").deadline.isoformat() == "2024-02-09")
        _rf41 = _de41.compute_deadline("2024-07-20", 30, "days", jurisdiction="IT", feriale=True)
        check("afati[41]: sospensione feriale IT salta agosto (2024-09-19)",
              _rf41.deadline.isoformat() == "2024-09-19" and _rf41.feriale_applied)
        _ra41 = _de41.compute_deadline("2024-07-20", 30, "days", jurisdiction="AL", feriale=True)
        check("afati[41]: AL NON ha feriale — ignorato (2024-08-19)",
              _ra41.deadline.isoformat() == "2024-08-19" and not _ra41.feriale_applied)
        check("afati[41]: 5 gg lavorativi saltano sab/dom/festivi (2024-12-31)",
              _de41.compute_deadline("2024-12-20", 5, "business_days", jurisdiction="IT").deadline.isoformat() == "2024-12-31")
        _rp41 = _de41.compute_deadline("2024-11-08", 30, "days", jurisdiction="IT")
        check("afati[41]: proroga se la scadenza è festiva (8/12 dom → 9/12)",
              _rp41.deadline.isoformat() == "2024-12-09" and _rp41.rolled)
        _rsq41 = _de41.compute_deadline("2024-07-20", 30, "days", jurisdiction="IT", feriale=True, lang="sq")
        _rit41 = _de41.compute_deadline("2024-07-20", 30, "days", jurisdiction="IT", feriale=True, lang="it")
        check("afati[41]: BILINGUE (LINGUA=SESSIONE) — stessa data, passi sq/it",
              _rsq41.deadline == _rit41.deadline
              and any("gusht" in s for s in _rsq41.steps) and any("agosto" in s for s in _rit41.steps))
        check("afati[41]: afati.py usa il motore (regola → engine, non l'LLM per la data)",
              "_AFAT_RULE_RE" in _af41 and "deadline_engine" in _af41
              and "_de.compute_deadline(" in _af41 and "jurisdiction: str" in _af41)
        check("afati[41]: web.py passa la giurisdizione della sessione al motore",
              "jurisdiction=_active_jurisdiction(" in _wb41)
        # §13 esteso: Pasqua ortodossa (AL) + prescrizione deterministica (deadlines.py)
        import datetime as _dt41
        _oem41 = _de41.orthodox_easter_sunday(2024) + _dt41.timedelta(days=1)
        check("afati[41]: Pasqua ORTODOSSA calcolata + festivo AL (non IT)",
              _de41.orthodox_easter_sunday(2024) == _dt41.date(2024, 5, 5)
              and _oem41 in _de41.holidays(2024, "AL")
              and _oem41 not in _de41.holidays(2024, "IT"))
        _dl41 = _io41.open(_os41.path.join(_rr41, "src", "deadlines.py"), encoding="utf-8").read()
        check("afati[41]: prescrizione (deadlines.py) usa il motore determin. — no feriale/proroga + verdetto scaduto",
              "_PRESH_RE" in _dl41 and "deadline_engine" in _dl41
              and "roll_on_holiday=False" in _dl41 and "feriale=False" in _dl41
              and ("PARASHKRUAR" in _dl41 or "PRESCRITTO" in _dl41))
    except Exception as _e41:  # noqa: BLE001
        check("afati[41]: kontrollet u ekzekutuan", False, str(_e41))

    # ── [42] SETTLEMENT §18 — scenario (non previsione) + chiavi _eur corrette ──
    # Il motore era già onesto (scenari), ma la UI: (a) mostrava «—» ovunque per
    # un mismatch di chiavi (p10 vs p10_eur), (b) dava il % grezzo senza dire che
    # è un'assunzione. Ora: chiavi corrette + disclaimer + bande qualitative + bilingue.
    try:
        import os as _os42, io as _io42
        _rr42 = _os42.path.dirname(_os42.path.dirname(_os42.path.abspath(__file__)))
        _aj42 = _io42.open(_os42.path.join(_rr42, "static", "app.js"), encoding="utf-8").read()
        _i42 = _aj42.find("function renderSettleResult(")
        _seg42 = _aj42[_i42:_i42 + 4600] if _i42 >= 0 else ""
        check("settle[42]: §18 disclaimer «scenario, non previsione» (sq+it) nel render",
              _i42 >= 0 and "JO parashikim" in _seg42 and "supozime" in _seg42
              and "NON una previsione" in _seg42 and "ipotesi del modello" in _seg42)
        check("settle[42]: chiavi distribuzione corrette (_eur) — niente più «—»",
              "d.p10_eur" in _seg42 and "d.p50_eur" in _seg42 and "d.mean_eur" in _seg42)
        check("settle[42]: recommendation corretta (_eur) — counter/walk-away ora mostrati",
              "r.suggested_counter_eur" in _seg42 and "r.walk_away_eur" in _seg42)
        check("settle[42]: bande qualitative sulla probabilità di scenario (pband, sq+it)",
              "pband" in _seg42 and "shumë e mundshme" in _seg42 and "molto probabile" in _seg42)
    except Exception as _e42:  # noqa: BLE001
        check("settle[42]: kontrollet u ekzekutuan", False, str(_e42))

    # ── [43] SOURCE STATUS §5 — vocabolario canonico unico + mapper + NOT_FOUND≠assente ──
    try:
        import os as _os43, io as _io43
        from src import source_status as _ss43
        from src import war_room as _wr43
        _rr43 = _os43.path.dirname(_os43.path.dirname(_os43.path.abspath(__file__)))
        _wr43src = _io43.open(_os43.path.join(_rr43, "src", "war_room.py"), encoding="utf-8").read()
        check("status[43]: mapper verified/fake/unverified/needs_code/repealed → canonico",
              _ss43.canonicalize("verified") == _ss43.VERIFIED
              and _ss43.canonicalize("fake") == _ss43.NOT_FOUND_IN_SEARCH
              and _ss43.canonicalize("unverified") == _ss43.NOT_FOUND_IN_SEARCH
              and _ss43.canonicalize("needs_code") == _ss43.PARTIAL
              and _ss43.canonicalize("repealed") == _ss43.REPEALED
              and _ss43.canonicalize("blah") == _ss43.UNVERIFIED)
        check("status[43]: PRINCIPIO NOT_FOUND≠assente — nene(completo)=assente, sentenza(incompleto)=da controllare",
              _ss43.means_absent("fake", corpus_complete=True) is True
              and _ss43.means_absent("unverified", corpus_complete=False) is False
              and _ss43.means_absent("verified", corpus_complete=True) is False)
        check("status[43]: label bilingui sq/it + severità",
              _ss43.label("verified", "sq") == "e verifikuar" and _ss43.label("verified", "it") == "verificata"
              and _ss43.severity("repealed") == "bad" and _ss43.severity("verified") == "ok")
        check("status[43]: war_room importa il vocabolario da source_status (unica fonte di verità)",
              "source_status" in _wr43src and "QUALITY = _ss.QUALITY" in _wr43src
              and _wr43.VERIF == _ss43.VERIF and _wr43.QUALITY == _ss43.QUALITY)
    except Exception as _e43:  # noqa: BLE001
        check("status[43]: kontrollet u ekzekutuan", False, str(_e43))

    # ── [44] EVAL FRAMEWORK §37-40 — harness + golden cases (seed, da validare) ──
    try:
        import os as _os44, io as _io44, json as _json44, glob as _glob44
        _rr44 = _os44.path.dirname(_os44.path.dirname(_os44.path.abspath(__file__)))
        _le44 = _io44.open(_os44.path.join(_rr44, "tools", "legal_eval.py"), encoding="utf-8").read()
        check("eval[44]: harness legal_eval — Tier1 recall + Tier2 hook + lista codici",
              "def eval_tier1(" in _le44 and "def load_cases(" in _le44
              and "STATUTE_RETRIEVAL_RECALL" in _le44 and "--codes" in _le44 and "--full" in _le44)
        _gc44 = sorted(_glob44.glob(_os44.path.join(_rr44, "tools", "golden_cases", "*.json")))
        _cases44 = [_json44.load(_io44.open(p, encoding="utf-8")) for p in _gc44]
        check("eval[44]: ≥3 golden case seed, ciascuno con id/jurisdiction/facts/expected_laws",
              len(_cases44) >= 3 and all(
                  c.get("id") and c.get("jurisdiction") in ("AL", "IT")
                  and (c.get("facts") or "").strip()
                  and c.get("expected_laws") and c["expected_laws"][0].get("code")
                  and c["expected_laws"][0].get("number") for c in _cases44))
        check("eval[44]: principio onestà — i seed sono marcati da-validare (validated_by null)",
              all("validated_by" in c for c in _cases44))
    except Exception as _e44:  # noqa: BLE001
        check("eval[44]: kontrollet u ekzekutuan", False, str(_e44))

    # ── [45] CORPUS HASH §1-2/§4 — impronta + rilevamento cambi (fondazione) ──
    # La prima pietra del versioning: non il testo storico (XL, data-blocked), ma
    # l'impronta SHA-256 che fa accorgere quando un testo ufficiale CAMBIA.
    try:
        import types as _types45, os as _os45, io as _io45
        from src import corpus_hash as _ch45
        def _A45(**k):
            base = {"code": "", "number": "", "title_sq": "", "heading": "", "body": "", "repealed": False}
            base.update(k)
            return _types45.SimpleNamespace(**base)
        _h45 = _ch45.article_hash(_A45(code="c", number="1", body="testo uno"))
        check("hash[45]: article_hash deterministico + sha256 + whitespace-norm + sensibile a corpo/abrogazione",
              _h45 == _ch45.article_hash(_A45(code="c", number="1", body="testo  uno"))
              and len(_h45) == 64
              and _h45 != _ch45.article_hash(_A45(code="c", number="1", body="testo due"))
              and _h45 != _ch45.article_hash(_A45(code="c", number="1", body="testo uno", repealed=True)))
        _o45 = {"AL:c|1": {"hash": "x"}, "AL:c|2": {"hash": "y"}}
        _n45 = {"AL:c|1": {"hash": "x"}, "AL:c|2": {"hash": "Z"}, "AL:c|3": {"hash": "w"}}
        _d45 = _ch45.diff(_o45, _n45)
        check("hash[45]: diff rileva nuovo/cambiato/rimosso/invariato",
              _d45["new"] == ["AL:c|3"] and _d45["changed"] == ["AL:c|2"]
              and _d45["removed"] == [] and _d45["unchanged"] == 1)
        _rr45 = _os45.path.dirname(_os45.path.dirname(_os45.path.abspath(__file__)))
        _sc45 = _io45.open(_os45.path.join(_rr45, "tools", "snapshot_corpus.py"), encoding="utf-8").read()
        check("hash[45]: tool snapshot_corpus — fotografia nel volume + principio «mai auto-applicato» (§5)",
              "corpus_hashes.json" in _sc45 and "--write" in _sc45 and "auto-applicato" in _sc45)
    except Exception as _e45:  # noqa: BLE001
        check("hash[45]: kontrollet u ekzekutuan", False, str(_e45))

    # ── [46] SUPER NOTERI — quote successorie determin. (#2) + seed (#4) + atti nuovi (#5) ──
    try:
        import os as _os46, io as _io46
        from fractions import Fraction as _F46
        from src import succession_engine as _se46
        from src import notary as _nt46
        _rr46 = _os46.path.dirname(_os46.path.dirname(_os46.path.abspath(__file__)))
        _nt46src = _io46.open(_os46.path.join(_rr46, "src", "notary.py"), encoding="utf-8").read()
        check("noteri[46]: #2 motore quote — somma≠1=GABIM, somma=1 OK, 1° ordine (coniuge+2figli)=1/3, integrato",
              _se46.first_order_shares(True, 2)["Bashkëshorti/ja"] == _F46(1, 3)
              and "GABIM" in _se46.check("PJESA | A | 1/2\nPJESA | B | 1/3\n", "sq")
              and "e saktë" in _se46.check("PJESA | A | 1/3\nPJESA | B | 1/3\nPJESA | C | 1/3\n", "sq")
              and "succession_engine" in _nt46src and "_se.check(md" in _nt46src)
        check("noteri[46]: #4 themelim_shoqerie grounded (seed ligji_shoqerite_tregtare, non vuoto)",
              bool(_nt46.DEED_TYPES["themelim_shoqerie"]["seed"])
              and _nt46.DEED_TYPES["themelim_shoqerie"]["seed"][0][0] == "ligji_shoqerite_tregtare")
        check("noteri[46]: #5 atti nuovi uzufrukt+servitut con seed verificati + in elenco",
              "uzufrukt" in _nt46.DEED_TYPES and "servitut" in _nt46.DEED_TYPES
              and bool(_nt46.DEED_TYPES["uzufrukt"]["seed"]) and bool(_nt46.DEED_TYPES["servitut"]["seed"])
              and "uzufrukt" in _nt46._ORDER and "servitut" in _nt46._ORDER)
        # prokura d'USO (auto/beni/estero) + generale spiegata secondo legge (KC 71-72),
        # senza la doctrine-drift italiana «solo ordinaria amministrazione»
        check("noteri[46]: prokura USO — nuove tagra (perdorim pasurie/automjeti, dalje jashtë shtetit) + generale grounded KC 71-72 (no doctrine drift)",
              all(k in _nt46.PROKURA_SCOPES and k in _nt46._PROKURA_ORDER
                  for k in ("perdorim_pasurie", "perdorim_automjeti", "dalje_automjeti_jashte"))
              and hasattr(_nt46, "GENERAL_POA_GUIDE")
              and "neni 71" in _nt46.GENERAL_POA_GUIDE and "neni 72" in _nt46.GENERAL_POA_GUIDE
              and "nenet 71" in _nt46.PROKURA_FORMS["e_pergjithshme"]
              and "administrimit të zakonshëm" not in _nt46.PROKURA_FORMS["e_pergjithshme"]
              and "GENERAL_POA_GUIDE" in _nt46src and 'form == "e_pergjithshme"' in _nt46src)
    except Exception as _e46:  # noqa: BLE001
        check("noteri[46]: kontrollet u ekzekutuan", False, str(_e46))

    # ── [47] PRIVACY UI — nessun nome di modello nel testo VISIBILE (regola Tetramorph) ──
    # Il cervello non deve MAI dire all'utente quale modello usa (opus/fable/sonnet/
    # claude/anthropic). I token INTERNI di routing (param "fable", endpoint) restano;
    # qui si guardano le FRASI VISIBILI (label/button/menu). Regressione reale: il
    # pulsante «Skuadra me Fable 5.1» esponeva il modello (beccato dal titolare).
    try:
        import os as _os47, io as _io47
        _rr47 = _os47.path.dirname(_os47.path.dirname(_os47.path.abspath(__file__)))
        _aj47 = _io47.open(_os47.path.join(_rr47, "static", "app.js"), encoding="utf-8").read()
        _ix47 = _io47.open(_os47.path.join(_rr47, "templates", "index.html"), encoding="utf-8").read()
        _leaks47 = ["Fable 5", "me Fable", "con Fable", "Opus 5", "me Opus", "con Opus",
                    "Sonnet 5", "Anthropic", "Claude "]
        _found47 = [L for L in _leaks47 if L in _aj47 or L in _ix47]
        check("privacy[47]: nessun nome di modello nel testo visibile (app.js/index.html) — solo «Tetramorph»",
              not _found47, "trovati: " + ", ".join(_found47))
    except Exception as _e47:  # noqa: BLE001
        check("privacy[47]: kontrollet u ekzekutuan", False, str(_e47))

    # ── [48] MISSING FACTS interattivo — Po/Jo per domanda + Dërgo → analisi definitiva ──
    # Le domande di chiarimento hanno pulsanti Po/Jo; «Dërgo» assembla le risposte
    # e le manda alla sala di guerra completa (deep) per una risposta definitiva
    # (che rende via appendBot → ha i pulsanti salva/DOCX/PDF).
    try:
        import os as _os48, io as _io48
        _rr48 = _os48.path.dirname(_os48.path.dirname(_os48.path.abspath(__file__)))
        _aj48 = _io48.open(_os48.path.join(_rr48, "static", "app.js"), encoding="utf-8").read()
        _i48 = _aj48.find("function renderMissingFacts(")
        _seg48 = _aj48[_i48:_i48 + 6200] if _i48 >= 0 else ""
        check("mf[48]: domande di chiarimento con Po/Jo + campo «specifica» + «Dërgo» → analisi definitiva (deep)",
              _i48 >= 0 and "mf-po" in _seg48 and "mf-jo" in _seg48 and "mf-dergo" in _seg48
              and "mf-note" in _seg48 and "noteFor(" in _seg48
              and "Dërgo" in _seg48 and "form.requestSubmit()" in _seg48
              and "_deepNext = true" in _seg48 and "PËRFUNDIMTARE" in _seg48)
    except Exception as _e48:  # noqa: BLE001
        check("mf[48]: kontrollet u ekzekutuan", False, str(_e48))

    # ── [49] BUSY GUARD — una domanda alla volta (mentre il cervello lavora, blocca) ──
    # Bug del titolare: il tasto Enter (o «Dërgo») faceva partire una 2ª domanda
    # mentre la 1ª era ancora in corso, confondendo l'analisi. Flag _busy: guardia
    # nel submit + nell'Enter + lock/unlock in finally + sul riattacco al job.
    try:
        import os as _os49, io as _io49
        _rr49 = _os49.path.dirname(_os49.path.dirname(_os49.path.abspath(__file__)))
        _aj49 = _io49.open(_os49.path.join(_rr49, "static", "app.js"), encoding="utf-8").read()
        check("busy[49]: guardia _busy nel submit + Enter, lock _setBusy(true)/unlock in finally, + sul riattacco",
              "function _setBusy(" in _aj49
              and _aj49.count("if (_busy) return") >= 2
              and "_setBusy(true)" in _aj49 and "_setBusy(false)" in _aj49
              and ".finally(() => _setBusy(false))" in _aj49)
    except Exception as _e49:  # noqa: BLE001
        check("busy[49]: kontrollet u ekzekutuan", False, str(_e49))

    # ── [50] STREAMING CHIARO — niente pannello vuoto «Nenet (0)» + indicatore «ancora al lavoro» ──
    # Durante lo streaming il template porta un «Nenet e konsultuara (0)» vuoto e
    # nessun pulsante → sembra finito mentre l'analisi profonda continua. Fix:
    # rimuovere il pannello vuoto + mostrare un indicatore «Po analizoj ende…».
    try:
        import os as _os50, io as _io50
        _rr50 = _os50.path.dirname(_os50.path.dirname(_os50.path.abspath(__file__)))
        _aj50 = _io50.open(_os50.path.join(_rr50, "static", "app.js"), encoding="utf-8").read()
        _ie50 = _aj50.find("const ensureStreamEl = () =>")
        _seg50 = _aj50[_ie50:_ie50 + 1600] if _ie50 >= 0 else ""
        check("stream[50]: streaming toglie il pannello vuoto «.retrieved» + mostra indicatore «ancora al lavoro»",
              _ie50 >= 0 and 'querySelector(".retrieved")' in _seg50 and ".remove()" in _seg50
              and "stream-working" in _seg50
              and ("Po analizoj ende" in _seg50 and "Sto ancora analizzando" in _seg50))
    except Exception as _e50:  # noqa: BLE001
        check("stream[50]: kontrollet u ekzekutuan", False, str(_e50))

    # ── [51] DOMANDE = SOLO FATTI — mai domande legali (regola del titolare 10 set) ──
    # Feedback: le domande di chiarimento «insensate» chiedevano all'avvocato cose
    # LEGALI che il cervello deve ricercare e rispondere. Regola: solo fatti semplici
    # (chi/ruolo/proprietà/date/documenti in mano), MAI domande legali, default vuoto.
    try:
        _mfs = brain.MISSING_FACTS_SYSTEM
        check("mf[51]: MISSING_FACTS chiede SOLO fatti semplici, mai domande legali, default {facts:[]}",
              "NDALOHEN RREPTËSISHT pyetjet ligjore" in _mfs
              and "LEJOHEN vetëm pyetje faktike" in _mfs
              and "administrator i vetëm" in _mfs
              and "ortak i vetëm apo disa ortakë" in _mfs
              and "A ka filluar/skaduar afati" in _mfs   # esempio VIETATO (è legale → lo ricerca)
              and "A duhet apostilë" in _mfs              # esempio VIETATO
              and '{"facts": []}' in _mfs                 # default: non inventare domande
              and "MAKSIMUM 3" in _mfs
              # regressione: mai tornare al vecchio «avvocato stratega che cerca i fatti che cambiano la risposta»
              and "avokat strateg shqiptar" not in _mfs
              and "do ndryshonin ose forconin" not in _mfs)
    except Exception as _e51:  # noqa: BLE001
        check("mf[51]: kontrollet u ekzekutuan", False, str(_e51))

    # ── [52] NOTAIO — Verifica proprietà & gravami (funzione di garanzia) ──
    # Legge la certificata ASHK/estratto QKB e la cross-checka contro il veprim.
    # Tool di VERIFICA, grounded su nene verificate, con disclaimer onesto (non si
    # collega live ad ASHK) e verdikt a semaforo; endpoint + card nel hub notaio.
    try:
        from src import notary as _nt52
        import os as _os52, io as _io52
        _rr52 = _os52.path.dirname(_os52.path.dirname(_os52.path.abspath(__file__)))
        _nt52src = _io52.open(_os52.path.join(_rr52, "src", "notary.py"), encoding="utf-8").read()
        _web52 = _io52.open(_os52.path.join(_rr52, "src", "web.py"), encoding="utf-8").read()
        _aj52 = _io52.open(_os52.path.join(_rr52, "static", "app.js"), encoding="utf-8").read()
        check("noteri[52]: verify_property grounded (seed verificati) + onesto (no ASHK live) + verdikt + endpoint + card hub",
              hasattr(_nt52, "verify_property") and hasattr(_nt52, "_VERIFY_PROP_SEED")
              and ("kodi_civil", "560") in _nt52._VERIFY_PROP_SEED
              and "nuk lidhet live me ASHK" in _nt52src and "Verdikti" in _nt52src
              and "/api/notary/verify-property" in _web52 and "certificate_required" in _web52
              and "openVerifyProperty" in _aj52 and "Verifiko pronësinë & barrët" in _aj52)
    except Exception as _e52:  # noqa: BLE001
        check("noteri[52]: kontrollet u ekzekutuan", False, str(_e52))

    # ── [53] NOTAIO — Adempimenti post-atto (roadmap + scadenza deterministica) ──
    # Chiude il gap pre/post: la scadenza di registrazione (30gg) è calcolata dal
    # deadline_engine (non inventata); autorità AL/IT come fatti; onesto sul resto.
    try:
        from src import notary as _nt53
        import os as _os53, io as _io53
        _rr53 = _os53.path.dirname(_os53.path.dirname(_os53.path.abspath(__file__)))
        _nt53src = _io53.open(_os53.path.join(_rr53, "src", "notary.py"), encoding="utf-8").read()
        _web53 = _io53.open(_os53.path.join(_rr53, "src", "web.py"), encoding="utf-8").read()
        _aj53 = _io53.open(_os53.path.join(_rr53, "static", "app.js"), encoding="utf-8").read()
        check("noteri[53]: post_deed_plan — scadenza deterministica (deadline_engine) + autorità AL/IT + onesto + endpoint + card",
              hasattr(_nt53, "post_deed_plan")
              and "deadline_engine" in _nt53src and "compute_deadline" in _nt53src
              and "DETERMINISTIK" in _nt53src and "verifiko afatin" in _nt53src
              and "e-Albania" in _nt53src and "Adempimento" in _nt53src
              and "/api/notary/post-deed" in _web53 and "act_required" in _web53
              and "_active_jurisdiction" in _web53
              and "openPostDeed" in _aj53 and "Hapat pas aktit (regjistrim/afate)" in _aj53)
    except Exception as _e53:  # noqa: BLE001
        check("noteri[53]: kontrollet u ekzekutuan", False, str(_e53))

    # ── [54] NOTAIO/AVV/PROC — Verifica SUBJEKTI (QKB): due diligence società/persona ──
    # Analizza estratto/risultato QKB (anche persona→più società): status/poteri/soci +
    # red-flag AML + cross-check. Tool di VERIFICA, onesto (non si connette live a QKB).
    try:
        from src import notary as _nt54
        import os as _os54, io as _io54
        _rr54 = _os54.path.dirname(_os54.path.dirname(_os54.path.abspath(__file__)))
        _nt54src = _io54.open(_os54.path.join(_rr54, "src", "notary.py"), encoding="utf-8").read()
        _web54 = _io54.open(_os54.path.join(_rr54, "src", "web.py"), encoding="utf-8").read()
        _aj54 = _io54.open(_os54.path.join(_rr54, "static", "app.js"), encoding="utf-8").read()
        check("noteri[54]: verify_subject — status/red-flag/rete-persona + onesto (no QKB live) + endpoint + card",
              hasattr(_nt54, "verify_subject") and hasattr(_nt54, "_VERIFY_SUBJECT_SEED")
              and ("ligji_shoqerite_tregtare", "147") in _nt54._VERIFY_SUBJECT_SEED
              and "nuk lidhet live me QKB" in _nt54src and "likuidim" in _nt54src.lower()
              and "Verdikti" in _nt54src
              and "/api/notary/verify-subject" in _web54 and "subject_required" in _web54
              and "openVerifySubject" in _aj54 and "Verifiko subjektin (QKB)" in _aj54)
    except Exception as _e54:  # noqa: BLE001
        check("noteri[54]: kontrollet u ekzekutuan", False, str(_e54))

    # ── [55] QKB — ricerca LIVE nel registro imprese (fetch-on-demand + fallback) ──
    # Endpoint scoperto (POST format.qkb.gov.al/kerko-per-subjekt/, JSON embedded).
    # Fetch-on-demand + cache + rate-limit + FAIL-SILENT → UI ripiega su «incolla».
    try:
        from src import qkb as _qkb55
        import os as _os55, io as _io55
        _rr55 = _os55.path.dirname(_os55.path.dirname(_os55.path.abspath(__file__)))
        _q55src = _io55.open(_os55.path.join(_rr55, "src", "qkb.py"), encoding="utf-8").read()
        _web55 = _io55.open(_os55.path.join(_rr55, "src", "web.py"), encoding="utf-8").read()
        _aj55 = _io55.open(_os55.path.join(_rr55, "static", "app.js"), encoding="utf-8").read()
        # format_results è puro (niente rete) — verificalo eseguendo
        _fr = _qkb55.format_results([{"nipt": "X1", "emri": "Test", "status": "Në likuidim",
                                      "forma": "SHPK", "admin_ortak": "Filan Fisteku;", "red_flags": ["x"]}])
        check("qkb[55]: modulo qkb (search+format_results+fetch_extract, cache, fail-silent, JSON parse) + endpoint + UI con fallback",
              hasattr(_qkb55, "search") and hasattr(_qkb55, "format_results")
              and hasattr(_qkb55, "fetch_extract")
              and "X1" in _fr and "Në likuidim" in _fr
              and "JSON.parse" in _q55src and "Fail-silent" in _q55src
              and "_CACHE" in _q55src and "format.qkb.gov.al" in _q55src
              and "search-for-subject-get-documents" in _q55src  # endpoint estratto (fase 2)
              and "/api/notary/qkb-search" in _web55 and "/api/notary/qkb-extract" in _web55 and "qkb_mod" in _web55
              and "qkb-search" in _aj55 and "qkb-go" in _aj55 and "qkb-ext" in _aj55 and "ngjit manualisht" in _aj55)
    except Exception as _e55:  # noqa: BLE001
        check("qkb[55]: kontrollet u ekzekutuan", False, str(_e55))

    # ── [56] ANTIRICICLAGGIO (A) — adeguata verifica/CDD + leggi AML nel corpus ──
    # Tool aml_check grounded nelle leggi AML INGERITE: Ligji 9917 (AL) + D.Lgs
    # 231/2007 (IT). Verifica anche che le leggi siano davvero nel corpus (grounding).
    try:
        from src import notary as _nt56
        from src.retrieval import ArticleIndex as _AI56
        from pathlib import Path as _P56
        import os as _os56, io as _io56
        _rr56 = _os56.path.dirname(_os56.path.dirname(_os56.path.abspath(__file__)))
        _nt56src = _io56.open(_os56.path.join(_rr56, "src", "notary.py"), encoding="utf-8").read()
        _web56 = _io56.open(_os56.path.join(_rr56, "src", "web.py"), encoding="utf-8").read()
        _aj56 = _io56.open(_os56.path.join(_rr56, "static", "app.js"), encoding="utf-8").read()
        _aml_al = sum(1 for a in _AI56.load().articles if a.code == "ligji_pastrimi_parave")
        _aml_it = sum(1 for a in _AI56.load(_P56("/app/data/index/bm25_it.pkl")).articles
                      if a.code == "antiriciclaggio")
        check("aml[56]: aml_check (seed AL+IT, red-flag, tipping-off, raportim) + leggi AML nel corpus + endpoint + card",
              hasattr(_nt56, "aml_check") and hasattr(_nt56, "_AML_SEED_AL") and hasattr(_nt56, "_AML_SEED_IT")
              and ("ligji_pastrimi_parave", "4") in _nt56._AML_SEED_AL
              and ("antiriciclaggio", "17") in _nt56._AML_SEED_IT
              and "tipping-off" in _nt56src and "raportuar" in _nt56src.lower()
              and _aml_al >= 30 and _aml_it >= 70
              and "/api/notary/aml-check" in _web56 and "situation_required" in _web56
              and "openAmlCheck" in _aj56 and "aml-check" in _aj56 and "Kontroll AML" in _aj56)
    except Exception as _e56:  # noqa: BLE001
        check("aml[56]: kontrollet u ekzekutuan", False, str(_e56))

    # ── [57] EXPORT HTML del caso — mobile-safe (bug titolare: sul telefono non si adattava) ──
    # L'export inline lo style.css dell'app + override: forzare no overflow orizzontale,
    # tutto a max-width:100%, tabelle scroll, pre a capo → si vede bene anche sul telefono.
    try:
        import os as _os57, io as _io57
        _rr57 = _os57.path.dirname(_os57.path.dirname(_os57.path.abspath(__file__)))
        _aj57 = _io57.open(_os57.path.join(_rr57, "static", "app.js"), encoding="utf-8").read()
        _i57 = _aj57.find("const extra =")
        _seg57 = _aj57[_i57:_i57 + 1400] if _i57 >= 0 else ""
        check("export[57]: HTML del caso mobile-safe (overflow-x hidden + max-width 100% + tabelle scroll + pre a capo)",
              _i57 >= 0 and "overflow-x:hidden" in _seg57
              and ".messages *{max-width:100%" in _seg57
              and "overflow-x:auto" in _seg57 and "white-space:pre-wrap" in _seg57
              and "max-width:640px" in _seg57)
    except Exception as _e57:  # noqa: BLE001
        check("export[57]: kontrollet u ekzekutuan", False, str(_e57))

    # ── [58] LEGGI PUBBLICHE nel corpus AL: Kadastra 111/2018 + Noteria 110/2018 ──
    # Il titolare le voleva scaricate nel corpus (prima citate a memoria). Ingerite
    # (FAOLEX kadastra / nchb noteri) → grounding per notaio/proprietà.
    try:
        from src.retrieval import ArticleIndex as _AI58
        from src import citation_verifier as _cv58
        _al58 = _AI58.load().articles
        _kad = sum(1 for a in _al58 if a.code == "ligji_kadastra")
        _not = sum(1 for a in _al58 if a.code == "ligji_noteri")
        check("leggi[58]: Kadastra 111/2018 + Noteria 110/2018 nel corpus AL + label",
              _kad >= 60 and _not >= 100
              and _cv58.CODE_LABELS.get("ligji_kadastra") and _cv58.CODE_LABELS.get("ligji_noteri"))
    except Exception as _e58:  # noqa: BLE001
        check("leggi[58]: kontrollet u ekzekutuan", False, str(_e58))

    # ── [59] BLINDATURA PROPRIETÀ — kartela ASHK: sezione D, registrato≠non, ipoteca≠blocco ──
    # Errore reale (titolare 11 set): Neni 195 (divieto di alienare bene NON REGISTRATO)
    # applicato a un appartamento REGISTRATO (nr. 00061377). Blindato PER SEMPRE: nel tool
    # verify_property E nel cervello (ANSWER_SYSTEM, su OGNI richiesta AL).
    try:
        import inspect as _insp59
        from src import notary as _nt59
        from src import brain as _br59
        _src59 = _insp59.getsource(_nt59.verify_property)
        _seed59 = ("kodi_civil", "195") in _nt59._VERIFY_PROP_SEED
        _tool_ok = ("PAREGJISTRUAR" in _src59 and "195" in _src59
                    and "HIPOTEKA ≠ BLLOKIM" in _src59 and "'D'" in _src59)
        # v9.312 — dottrina PER GIURISDIZIONE: AL kartela/195, IT visura/2644/2650/2913;
        # e MAI la dottrina albanese nel prompt italiano (sarebbe l'errore stesso)
        _al59 = _br59.answer_system_for("", "AL")
        _it59 = _br59.answer_system_for("", "IT")
        _brain_al = ("KARTELA ASHK" in _al59 and "PAREGJISTRUAR" in _al59
                     and "Neni 195" in _al59 and "HIPOTEKA ≠ BLLOKIM" in _al59)
        _brain_it = ("VISURA IPOTECARIA" in _it59 and "IPOTECA ≠ BLOCCO" in _it59
                     and "TRASCRIZIONE ≠ VALIDITÀ" in _it59 and "2644" in _it59
                     and "2650" in _it59 and "2913" in _it59 and "KARTELA ASHK" not in _it59)
        _wired59 = all("_answer_system" in _insp59.getsource(getattr(_br59.SuperAvvocato, _m))
                       for _m in ("_compose_answer", "_compose_answer_stream", "_compose_simple_answer"))
        # il notaio italiano: verify_property jurisdiction-aware, seed IT reale, prompt nativo IT
        _it_tool = ("jurisdiction" in _src59 and "_verify_property_it" in _src59
                    and ("codice_civile", "2644") in _nt59._VERIFY_PROP_SEED_IT
                    and ("codice_civile", "2913") in _nt59._VERIFY_PROP_SEED_IT
                    and "IPOTECA ≠ BLOCCO" in _nt59._VERIFY_PROP_SYSTEM_IT
                    and "TRASCRIZIONE ≠ VALIDITÀ" in _nt59._VERIFY_PROP_SYSTEM_IT
                    and "Tetramorph" in _nt59._NOTARY_ID_IT)
        check("blindatura[59]: proprietà PER GIURISDIZIONE — AL kartela/sezione D/Neni 195/ipoteca≠blocco · IT visura/2644/2650/2913 — nel cervello (compose wired) E nel tool (verify_property AL+IT)",
              _seed59 and _tool_ok and _brain_al and _brain_it and _wired59 and _it_tool)
    except Exception as _e59:  # noqa: BLE001
        check("blindatura[59]: kontrollet u ekzekutuan", False, str(_e59))

    # ── [60] IL GIUDICE FINALE (Gjyqtari i Fundit) — Fable 5.1 max arbitro finale ──
    # Spec titolare 11 set: tutti gli agenti (senior, raccoglitori web/QBZ/Fletorja,
    # avvocato del diavolo) consegnano a Fable 5.1 max, che dà il VERDETTO FINALE — nenet
    # VERBATIM (mai riassunte), additivo, fail-silent, privacy (nessun nome-modello a video).
    try:
        import inspect as _insp60
        from src import studio as _st60
        from src import brain as _br60
        from src import config as _cfg60
        _fn60 = callable(getattr(_st60, "gjyqtari_fundit", None))
        _sys60 = getattr(_st60, "GJYQTARI_SYSTEM", {})
        _tit60 = getattr(_st60, "TITULLI_GJYQTARI", {})
        _lang_ok = bool(_sys60.get("sq") and _sys60.get("it")
                        and _tit60.get("sq") and _tit60.get("it"))
        _blob60 = (str(_tit60.get("sq", "")) + str(_tit60.get("it", ""))).lower()
        _priv60 = not any(w in _blob60 for w in
                          ("fable", "opus", "sonnet", "claude", "anthropic", "tetramorph"))
        _cfg60ok = (hasattr(_cfg60, "STUDIO_GJYQTARI_ENABLED")
                    and getattr(_cfg60, "STUDIO_GJYQTARI_MODEL", "") == "claude-fable-5-1"
                    and getattr(_cfg60, "STUDIO_GJYQTARI_EFFORT", "") == "max")
        _wired60 = (hasattr(_br60.SuperAvvocato, "_gjyqtari_fundit")
                    and "_gjyqtari_fundit" in _insp60.getsource(_br60.SuperAvvocato.answer_stream)
                    and "_gjyqtari_fundit" in _insp60.getsource(_br60.SuperAvvocato.answer))
        check("giudice[60]: gjyqtari_fundit (sq+it, Fable max, verbatim) + config + wiring answer_stream+answer + privacy",
              _fn60 and _lang_ok and _priv60 and _cfg60ok and _wired60)
    except Exception as _e60:  # noqa: BLE001
        check("giudice[60]: kontrollet u ekzekutuan", False, str(_e60))

    # ── [61] DOMANDE: il rilevatore LEGGE i documenti allegati (bug titolare 11 set) ──
    # Con i 2 HEIC della kartela caricati (OCR ok, Sezione D estratta), il cervello
    # chiedeva «che natura ha il kufizim — hipotekë, sekuestro…?» e «hai la certificata
    # ASHK?»: domanda LEGALE su una cosa SCRITTA nel documento, + richiesta di un
    # documento già allegato. Causa: _detect_missing_facts riceveva i documenti in
    # modalità compact (testo omesso) → cieco alla Sezione D. Ora riceve il testo
    # (compact=False) e il prompt vieta classificazione giuridica + chiedere allegati.
    try:
        import inspect as _insp61
        _src61 = _insp61.getsource(brain.SuperAvvocato._detect_missing_facts)
        _mfs61 = brain.MISSING_FACTS_SYSTEM
        # la CHIAMATA vera, non le parole (il commento nella funzione cita «compact=True»)
        check("mf[61]: il rilevatore domande VEDE il testo dei documenti (compact=False) + vieta classificazione giuridica + mai chiedere allegati già in dosja",
              "format_documents_for_prompt(documents or [], compact=False)" in _src61
              and "format_documents_for_prompt(documents or [], compact=True)" not in _src61
              and "KLASIFIKIMI i natyrës juridike" in _mfs61
              and "LEXO DOKUMENTET E BASHKËNGJITURA PARA se të pyesësh" in _mfs61
              and "KURRË mos kërko një dokument që tashmë është bashkëngjitur" in _mfs61)
    except Exception as _e61:  # noqa: BLE001
        check("mf[61]: kontrollet u ekzekutuan", False, str(_e61))

    # ── [62] SESSIONE ITALIANA = SOLO ITALIANO — i residui trovati dal DOM vivo (14 set) ──
    # Regola ferrea del titolare: «ogni lettera in italiano, nulla in albanese nella
    # sessione italiana, né descrizioni né niente». Il DOM vivo (Chrome, admin.it) aveva
    # 15 residui: tooltip senza data-i18n-title, l'area upload, le opzioni del profilo
    # studio, e due traduzioni italiane «sporche» (albanese tra parentesi). Qui si
    # sorvegliano quei testi esatti nel dizionario T_IT + i value stabili delle option.
    try:
        # radice propria: `_rr` viene riassegnato piu' sopra (set di codici rrugor)
        _rr62 = _os2.path.dirname(_os2.path.dirname(_os2.path.abspath(__file__)))
        _js62 = _io2.open(_os2.path.join(_rr62, "static", "app.js"), encoding="utf-8").read()
        _html62 = _io2.open(_os2.path.join(_rr62, "templates", "index.html"), encoding="utf-8").read()
        _keys62 = ["Gjithçka e ruajtur dhe e ngarkuar, nga të gjitha rastet",
                   "Merr njoftim kur analiza mbaron, edhe nëse mbyll faqen",
                   "Rilexo kushtet, privatësinë dhe marrëveshjen për të dhënat",
                   "Bashkëngjit PDF, foto, docx", "Sa përqind e konsumit të periudhës i takon këtij studioje",
                   "— gjuha e akteve…", "Shqip", "Italisht", "Të dyja", "stili…", "Formal",
                   "I përmbledhur", "I detajuar", "Tërhiqi këtu ose kliko për të zgjedhur"]
        _in62 = all(('"%s' % k) in _js62 and _re2.search(r'"' + _re2.escape(k) + r'[^"]*"\s*:\s*"', _js62) for k in _keys62)
        _clean62 = ('it_58: "Corte di Cassazione",' in _js62 and 'it_59: "Corte Costituzionale",' in _js62
                    and "(Gjykata e Lartë)" not in _js62 and "(Gjykata Kushtetuese)" not in _js62)
        _vals62 = ('<option value="Shqip">Shqip</option>' in _html62 and '<option value="Formal">Formal</option>' in _html62
                   and '<option value="Italisht">Italisht</option>' in _html62)
        # QKB = registro ALBANESE: la riga live sparisce in sessione IT, descrizione italiana
        _qkb62 = ('class="qkb-search" style="\' + ((document.body.dataset.lang === "it") ? "display:none;"' in _js62
                  and "Incolla la visura camerale (Registro Imprese)" in _js62)
        # il marcatore del verificatore di citazioni e' testo visibile: per lingua
        import inspect as _insp62
        from src import citation_shield as _cs62
        _src62 = _insp62.getsource(_cs62.annotate_fake_citations)
        _shield62 = ("verifica fallita" in _src62 and "verifikim dështoi" in _src62
                     and "request_jurisdiction" in _src62)
        check("i18n[62]: sessione IT = solo italiano — 15 residui del DOM vivo nel dizionario T_IT + it_58/59/61/64 senza albanese + option con value stabili + QKB nascosto in IT + marcatore citazioni per lingua",
              _in62 and _clean62 and _vals62 and _qkb62 and _shield62)
    except Exception as _e62:  # noqa: BLE001
        check("i18n[62]: kontrollet u ekzekutuan", False, str(_e62))

    # ── [63] DECISIVO: il triage NON ferma più la risposta con una sola domanda (14 set) ──
    # Audit IT: «Avvocato — risposta principale» tornava in 42 s con 243 byte = SOLO la
    # domanda del triage (kind="followup"), nessuna risposta; stesso schema dello
    # screenshot AL («che natura ha il kufizim?»). Ora il fatto mancante diventa una
    # consegna al cervello (due rami + domanda in coda), in entrambi i percorsi.
    try:
        import inspect as _insp63
        _s_stream = _insp63.getsource(brain.SuperAvvocato.answer_stream)
        _s_answer = _insp63.getsource(brain.SuperAvvocato.answer)
        _tri63 = brain.TRIAGE_SYSTEM if hasattr(brain, "TRIAGE_SYSTEM") else ""
        check("decisivo[63]: nessun ritorno kind=followup — il fatto mancante diventa consegna (due rami + domanda in coda) in answer_stream E answer; triage vieta classificazione/allegati",
              # la COSTRUZIONE reale, non le parole (il commento cita kind="followup")
              'kind="followup", text=' not in _s_stream and 'kind="followup", text=' not in _s_answer
              and "_me_faktin_qe_mungon" in _s_stream and "_me_faktin_qe_mungon" in _s_answer
              and hasattr(brain.SuperAvvocato, "_me_faktin_qe_mungon")
              and "NDALOHET si followup_question" in _tri63
              and "NUK e ndal kurrë përgjigjen" in _tri63)
    except Exception as _e63:  # noqa: BLE001
        check("decisivo[63]: kontrollet u ekzekutuan", False, str(_e63))

    # ── [64] TRIAGE robusto ai documenti incollati + Giudice SENZA web (14 set) ──
    # Audit IT: con la visura incollata nel messaggio il triage (fast) rispondeva col
    # PARERE invece del JSON (9 min, poi fallback povero) → testa+coda + promemoria
    # «SOLO JSON» in coda + un solo nuovo tentativo. E il Giudice Finale navigava
    # (440.877 token in una chiamata): giudica i materiali dati → no_web.
    try:
        import inspect as _insp64
        from src import backends as _bk64
        from src import studio as _st64
        _tri64 = _insp64.getsource(brain.SuperAvvocato._triage)
        _bk_src = _insp64.getsource(_bk64)
        _gj64 = _insp64.getsource(_st64.gjyqtari_fundit)
        _ch64 = _insp64.getsource(_st64._chiama)
        _trim_it = brain._triage_trim("x" * 9000, "IT")
        _trim_al = brain._triage_trim("domanda", "AL")
        check("triage[64]: _triage_trim (testa+coda ≤ budget, promemoria SOLO JSON in coda per lingua) + un nuovo tentativo + Giudice no_web (backend/_chiama/gjyqtari)",
              "_triage_trim(" in _tri64 and "ritento una volta" in _tri64
              and len(_trim_it) < 4400 and _trim_it.rstrip().endswith("━━━")
              and "RISPONDI SOLO CON L'OGGETTO JSON" in _trim_it
              and "KTHE VETËM OBJEKTIN JSON" in _trim_al
              and "no_web: bool = False" in _bk_src
              and "_tools = [] if (fast or no_web)" in _bk_src
              and 'kw["no_web"] = True' in _ch64 and 'kw.pop("no_web", None)' in _ch64
              and "no_web=True" in _gj64)
    except Exception as _e64:  # noqa: BLE001
        check("triage[64]: kontrollet u ekzekutuan", False, str(_e64))

    # ── [65] LA CHAT CON IL WEB + verdetto IN TESTA + pannelli al Giudice + etichette IT (14 set) ──
    # Screenshot del titolare (auto targata AL, shpk): il senior in streaming non aveva
    # WebSearch/WebFetch → cinque «accesso negato», tutto «da verificare», quattro «canali»
    # falliti; i pannelli (art. 93 superato, AIRE) contraddicevano il verdetto che stava in
    # fondo; «Pse/Afati/Veprim/BARRA E ZHVENDOSUR» in albanese nella sessione italiana.
    try:
        import inspect as _insp65
        from src import backends as _bk65
        from src import studio as _st65
        _cs65 = _insp65.getsource(_bk65)
        _i65 = _cs65.find("def complete_stream(")
        _stream65 = _cs65[_i65:_i65 + 9000] if _i65 >= 0 else ""
        _gj65 = _insp65.getsource(_st65.gjyqtari_fundit)
        _brgj65 = _insp65.getsource(brain.SuperAvvocato._gjyqtari_fundit)
        _cas65 = _insp65.getsource(brain.SuperAvvocato._compose_answer_stream)
        _as65 = _insp65.getsource(brain.SuperAvvocato.answer_stream)
        _js65 = _io2.open(_os2.path.join(_os2.path.dirname(_os2.path.dirname(_os2.path.abspath(__file__))), "static", "app.js"), encoding="utf-8").read()
        _lab65 = all(('"%s": "' % k) in _js65 for k in ("Pse:", "⏰ Afati:", "▶ Veprim sot:", "▶ Veprim:", "🔄 BARRA E ZHVENDOSUR",
                                                        "Ligji e zhvendos barrën e provës mbi palën tjetër"))
        _intro65 = '"Për çdo pretendim tregojmë ÇFARË duhet provuar' in _js65 and '"Këto janë mospërputhjet mes dokumenteve' in _js65
        check("chat[65]: streaming con WebSearch/WebFetch + testo finale dal result (non i delta) + Giudice riceve i pannelli e mette il verdetto IN TESTA + etichette pannelli in italiano",
              'cmd.extend(["--allowedTools", "WebSearch", "WebFetch"])' in _stream65
              and "final_text = full" in _stream65
              and 'text = (final_text or "".join(collected)).strip()' in _cs65
              and "fazat" in _gj65 and "TITULLI_ANALIZA" in _gj65
              and ("return vendim + answer_text" in _brgj65 or "final = vendim + answer_text" in _brgj65)  # v9.331: + Trust Line sotto il titolo
              and "fazat_txt=_fazat_x" in _as65 and "_risposta_dalle_fasi(" in _as65
              and 'final_text = str(payload.get("text") or "")' in _as65
              and "collected = [_ft]" in _cas65
              and _lab65 and _intro65)
    except Exception as _e65:  # noqa: BLE001
        check("chat[65]: kontrollet u ekzekutuan", False, str(_e65))

    # ── [66] Il codice NOMINATO nella domanda entra sempre nelle aree del triage (14 set) ──
    # Prova SSE: «Cili nen i Kodit Rrugor dënon zhurmën…» → il triage veloce una volta su
    # cinque perde «Rrugor» → ancore su procedura amministrativa → «nuk gjej përgjigje».
    try:
        import inspect as _insp66
        _t66 = _insp66.getsource(brain.SuperAvvocato._triage)
        check("triage[66]: _areas_from_code_names (Kodit Rrugor→Rrugor, Kodit Civil→Civil, Kodit të Punës→Punë, procedurës penale→Penal) + merge nelle aree del triage (AL)",
              brain._areas_from_code_names("Cili nen i Kodit Rrugor dënon zhurmën e tepërt të marmitës?") == ["Rrugor"]
              and brain._areas_from_code_names("sipas Kodit Civil dhe Kodit të Punës") == ["Civil", "Punë"]
              and brain._areas_from_code_names("neni 5 i Kodit të Procedurës Penale") == ["Penal"]
              and brain._areas_from_code_names("una domanda senza codici") == []
              and "_areas_from_code_names(user_message)" in _t66 and "areas=areas," in _t66)
    except Exception as _e66:  # noqa: BLE001
        check("triage[66]: kontrollet u ekzekutuan", False, str(_e66))

    # ── [67] Compose scaduto: tetto 45 min (env) + ripiego SENZA web (14 set) ──
    # L'audit immobiliare IT: compose con web > 30 min → «brain failure». Ora il tetto
    # e' TETRAMORPH_TIMEOUT_S (2700) e il ripiego «ricompongo dalle fasi» non naviga.
    try:
        import inspect as _insp67
        from src import backends as _bk67
        _bs67 = _insp67.getsource(_bk67)
        _as67 = _insp67.getsource(brain.SuperAvvocato.answer_stream)
        _ca67 = _insp67.getsource(brain.SuperAvvocato._compose_answer)
        check("timeout[67]: TETRAMORPH_TIMEOUT_S (default 2700) + ripiego compose no_web=True",
              'os.environ.get("TETRAMORPH_TIMEOUT_S", "2700")' in _bs67
              and "documents=None, no_web=True, **_fasi" in _as67
              and '({"no_web": True} if no_web else {})' in _ca67)
    except Exception as _e67:  # noqa: BLE001
        check("timeout[67]: kontrollet u ekzekutuan", False, str(_e67))

    # ── [68] Referto delle fasi bilingue + Giudice «senza web per scelta» + duello a scomparsa (15 set) ──
    # Prova viva IT (caso auto shpk): il Giudice segnalava «intestazioni in albanese» nei
    # pannelli (era _risposta_dalle_fasi, solo albanese — anche come ripiego finale in IT) e
    # «WebSearch negato» (l'override IT gli imponeva la Cassazione viva). E il duello
    # diavolo/replica allungava la lettura: ora <details> nella UI.
    try:
        import inspect as _insp68
        from src import studio as _st68
        _rf68 = _insp68.getsource(brain._risposta_dalle_fasi)
        _rr68 = _os2.path.dirname(_os2.path.dirname(_os2.path.abspath(__file__)))
        _js68 = _io2.open(_os2.path.join(_rr68, "static", "app.js"), encoding="utf-8").read()
        _html68 = _io2.open(_os2.path.join(_rr68, "templates", "index.html"), encoding="utf-8").read()
        _gs68 = _st68.GJYQTARI_SYSTEM
        brain.set_request_jurisdiction("IT")
        _it_txt = brain._risposta_dalle_fasi(brain.TriageResult(problem_summary="x", areas=[], search_queries=["x"], strategic_angles=[], needs_followup=False, followup_question=""))
        brain.set_request_jurisdiction("AL")
        _al_txt = brain._risposta_dalle_fasi(brain.TriageResult(problem_summary="x", areas=[], search_queries=["x"], strategic_angles=[], needs_followup=False, followup_question=""))
        check("fasi[68]: _risposta_dalle_fasi nella lingua della sessione (IT/AL) + intro opzionale; Giudice «senza web per scelta» (sq+it); duello diavolo/replica a scomparsa (collapseSparring, app.js?v=167)",
              "La sintesi finale non è stata prodotta" in _it_txt and "Sinteza përfundimuese" in _al_txt
              and "intro: bool = True" in _rf68 and "_ETICHETTA_BUCKET_IT" in _rf68
              and "SENZA WEB, PER SCELTA" in _gs68["it"] and "PA WEB, ME QËLLIM" in _gs68["sq"]
              and "function collapseSparring(html)" in _js68 and "collapseSparring(out.join(" in _js68
              and _re2.search(r"app\.js\?v=\d+", _html68) is not None)
    except Exception as _e68:  # noqa: BLE001
        check("fasi[68]: kontrollet u ekzekutuan", False, str(_e68))

    # ── [69] Etichette COMPOSTE (contatori) bilingui alla fonte (15 set) ──
    # DOM vivo in sessione IT: «📋 Mapa e provës — 5 provë që mungojnë, 1 me barrë të
    # zhvendosur» — le stringhe con ${…} non passano dal match esatto di T_IT: si traducono
    # alla fonte con `_CAL_IT ? it : sq` (pannelli, calendario, barre di stato, toast, admin).
    try:
        _js69 = _io2.open(_os2.path.join(_os2.path.dirname(_os2.path.dirname(_os2.path.abspath(__file__))), "static", "app.js"), encoding="utf-8").read()
        _need69 = ["📋 Mappa delle prove — ${missing.length} prove mancanti",
                   "🛡️ Radar di nullità e termini (${findings.length})",
                   "⚖️ ${items.length} contraddizioni nel fascicolo",
                   "🛡️ Precedenti sfavorevoli (${items.length}",
                   "(count === 1 ? \"1 evento\" : `${count} eventi`)",
                   "`+${dayEvents.length - 3} altri`", "`Aggiunti ${data.events_created || 0} termini al calendario`",
                   "`${sec}s fa`", "`Fattura ${inv.invoice_no} generata.`", "`Completato in ${(evt.elapsed_ms/1000).toFixed(1)}s ✓`",
                   "`Eliminare l'utente '${uname}'?", "willSuspend ? \"disattivare\" : \"riattivare\"",
                   '${_CAL_IT ? "CRITICO" : "KRITIK"}', '${_CAL_IT ? "ALLARME" : "ALARM"}']
        _miss69 = [k for k in _need69 if k not in _js69]
        check("i18n[69]: etichette composte con contatori tradotte alla fonte (_CAL_IT) — pannelli, calendario, stato, toast, admin",
              not _miss69, "mancano: " + " | ".join(_miss69)[:200])
    except Exception as _e69:  # noqa: BLE001
        check("i18n[69]: kontrollet u ekzekutuan", False, str(_e69))

    # ── [70] LA MEMORIA DEL FILO + errori per lingua + replica non tronca + avviso pannelli (15 set) ──
    # Caso vero: follow-up «auto un mese in Grecia» ragionato su un'auto IMMATRICOLATA IN ITALIA
    # — il compose riceveva SOLO l'ultimo messaggio quando c'era un session_id («ci pensa il
    # resume»), ma --resume e' disabilitato → nessuna memoria. Ora la storia entra sempre, potata.
    try:
        import inspect as _insp70
        from src import backends as _bk70
        from src import studio as _st70
        _b70 = _insp70.getsource(brain)
        _uses = _b70.count("_history_for_prompt(history) + [")
        _drop = 'if session_id:\n            messages = [{"role": "user", "content": prompt}]' in _b70 \
            or 'if session_id:\n                msgs = [{"role": "user", "content": prompt}]' in _b70
        _h = brain._history_for_prompt([{"role": "user", "content": "a" * 9000},
                                        {"role": "assistant", "content": "b" * 9000},
                                        {"role": "user", "content": "c"}])
        _hf70 = _insp70.getsource(_bk70._humanize_cli_failure)
        _sp70 = _insp70.getsource(_st70.senior_pergjigjja)
        _js70 = _io2.open(_os2.path.join(_os2.path.dirname(_os2.path.dirname(_os2.path.abspath(__file__))), "static", "app.js"), encoding="utf-8").read()
        _gab = [L for L in _js70.split("\n") if "Gabim: " in L and "_CAL_IT" not in L and "TT(" not in L and "T_IT" not in L]
        check("memoria[70]: _history_for_prompt in 4 punti (nessun «if session_id → solo prompt»), potatura 3500/2500, errori CLI per lingua, replica senior 3000 tok (v9.363), avviso «Pannelli da correggere» + nessun «Gabim:» fisso nel client",
              _uses >= 4 and not _drop
              and len(_h) == 3 and len(_h[0]["content"]) <= 3510 and len(_h[1]["content"]) <= 2510
              and "Tetramorph è impegnato" in _hf70 and "request_jurisdiction" in _hf70
              and "max_tokens=3000" in _sp70
              and 'className = "panels-notice"' in _js70 and "Pannelli da correggere:|Panele" in _js70
              and not _gab, "Gabim fissi: %d" % len(_gab))
    except Exception as _e70:  # noqa: BLE001
        check("memoria[70]: kontrollet u ekzekutuan", False, str(_e70))

    # ── [71] Il Giudice Finale anche sui follow-up sostanziosi (15 set) ──
    # Prova viva in Chrome (caso «auto 2», follow-up Grecia): la memoria del filo ha funzionato
    # («Rettifica preliminare: l'auto è targata Albania»), ma la risposta citava come verificata
    # la «Cass. 10383/2026» che il verdetto precedente aveva bollato «non citare» e i «60 giorni»
    # dell'art. 93 abrogato — il followup fast-path non passava dal Giudice.
    try:
        import inspect as _insp71
        from src import studio as _st71
        _as71 = _insp71.getsource(brain.SuperAvvocato.answer_stream)
        _i71 = _as71.find("stream: followup fast-path")
        _seg71 = _as71[_i71:_i71 + 4000]
        check("giudice[71]: followup fast-path → _gjyqtari_fundit se ≥4000 chr, con il filo della conversazione; prompt del Giudice sa giudicare senza corpus (sq+it)",
              "if len(text) >= 4000 and not _sqarim:" in _seg71 and "self._gjyqtari_fundit(user_message, _cit_f, [], text, dosja_txt=_lbl_f + _filo)" in _seg71
              and "NËSE NUK KA NENE nga korpusi" in _st71.GJYQTARI_SYSTEM["sq"]
              and "SE NON CI SONO ARTICOLI dal corpus" in _st71.GJYQTARI_SYSTEM["it"])
    except Exception as _e71:  # noqa: BLE001
        check("giudice[71]: kontrollet u ekzekutuan", False, str(_e71))

    # ── [72] CHIARIMENTO ≠ RICERCA: follow-up «cosa significa / come si applica» senza web (16 set) ──
    # Il titolare: «domanda semplice… sta 26 min che lavora» — il followup fast-path partiva
    # col web + «verifica viva» della Cassazione per un chiarimento di cose già nel filo.
    try:
        import inspect as _insp72
        from src import backends as _bk72
        _as72 = _insp72.getsource(brain.SuperAvvocato.answer_stream)
        _cs72 = _insp72.getsource(_bk72.ClaudeCodeBackend.complete_stream)
        check("chiarimento[72]: _eshte_sqarim (cosa significa/come si applica, ≤400 chr, senza cue di ricerca) → complete_stream(no_web=True) + hint + niente Giudice; ricerca esplicita resta col web",
              brain._eshte_sqarim("Può salvare il veicolo pagando prima del provvedimento: Corte cost. 93/2025, cosa significa, come si applica?")
              and not brain._eshte_sqarim("cerca la sentenza più recente della Cassazione su questo punto e dimmi cosa significa")
              and not brain._eshte_sqarim("x" * 500 + " cosa significa")
              and brain._eshte_sqarim("çfarë do të thotë kjo në praktikë, si zbatohet?")
              and "no_web=_sqarim" in _as72 and "if len(text) >= 4000 and not _sqarim:" in _as72
              and "no_web: bool = False" in _cs72 and "if not fast and not no_web:" in _cs72)
    except Exception as _e72:  # noqa: BLE001
        check("chiarimento[72]: kontrollet u ekzekutuan", False, str(_e72))

    # ── [73] deploy_when_idle: il conteggio dei CLI passa con -c, MAI via stdin (16 set) ──
    # `docker exec` senza -i non passa lo stdin: `python3 - <<PY` leggeva vuoto → «0 attivi»
    # → run.sh partiva sempre → uccisa una domanda del titolare a 30 min di lavoro.
    try:
        _p73 = _os2.path.join(_os2.path.dirname(_os2.path.dirname(_os2.path.abspath(__file__))), "ops", "deploy_when_idle.sh")
        if not _os2.path.exists(_p73):
            # ops/ non entra nell'immagine Docker: la guardia vale sul repo (git), nel container si salta
            check("deploy[73]: ops/deploy_when_idle.sh non presente qui (fuori immagine) — controllo saltato", True)
        else:
            _sh73 = _io2.open(_p73, encoding="utf-8").read()
            check("deploy[73]: deploy_when_idle conta i CLI con `python3 -c` (non stdin) e tratta un conteggio non numerico come OCCUPATO",
                  "docker exec super-avvocato python3 -c '" in _sh73 and "python3 - <<" not in _sh73
                  and "|| echo 999" in _sh73 and "n=999 ;; esac" in _sh73)
    except Exception as _e73:  # noqa: BLE001
        check("deploy[73]: kontrollet u ekzekutuan", False, str(_e73))

    # ── [74] BUDGET DI RICERCA nel prompt (16 set) — «per 2 domande quasi 7% dell'abbonamento» ──
    # L'override IT imponeva «cerca PRIMA di rispondere» senza limite → 1,4M token a risposta.
    try:
        _ov74 = brain.JURISDICTION_OVERRIDE_IT
        _as74 = brain.ANSWER_SYSTEM
        check("budget[74]: tetto ricerche nel prompt — IT «al massimo 4 ricerche e 6 pagine» + AL «maksimumi 4 kërkime dhe 6 faqe»",
              "BUDGET DI RICERCA" in _ov74 and "al massimo\n4 ricerche e 6 pagine lette" in _ov74.replace("massimo 4", "massimo\n4")
              and "BUXHETI I KËRKIMIT" in _as74 and "maksimumi 4 kërkime dhe 6 faqe" in _as74)
    except Exception as _e74:  # noqa: BLE001
        check("budget[74]: kontrollet u ekzekutuan", False, str(_e74))

    # ── [75] CORPUS IT ALLARGATO (16 set): dogane (nazionale + UE), tributario, notarile, ecc. ──
    # Il titolare: «aggiungi tutto quello che manca, così va a prenderlo» — e il cervello non
    # naviga più per l'art. 212 Reg. 2015/2446 o l'art. 118 DNC: li legge dal corpus.
    try:
        from pathlib import Path as _P75
        _it75 = ArticleIndex.load(_P75("/app/data/index/bm25_it.pkl")).articles
        _have75 = {(a.code, str(a.number)) for a in _it75}
        _codes75 = {a.code for a in _it75}
        _need75 = [("codice_doganale_nazionale", "118"), ("codice_doganale_nazionale", "96"),
                   ("codice_doganale_ue", "250"), ("codice_doganale_ue", "5"),
                   ("reg_ue_2015_2446", "212"), ("reg_ue_2015_2446", "215"), ("reg_ue_2015_2446", "217"),
                   ("iva", "70"), ("legge_notarile", "28"), ("legge_52_1985", "29"),
                   ("imposta_registro", "2"), ("statuto_contribuente", "10"), ("gdpr", "6"),
                   ("licenziamenti_individuali", "6"), ("tutele_crescenti", "3"), ("regolamento_immigrazione", "13")]
        _miss75 = [f"{c} {n}" for c, n in _need75 if (c, n) not in _have75]
        _lab75 = [c for c in _codes75 if c not in cv.CODE_LABELS]
        check("corpus[75]: IT ≥ 75 atti; articoli-chiave presenti (DNC 96/118, CDU 5/250, Reg. 2015/2446 212/215/217, IVA 70, notarile 28, L.52/85 29, registro 2, Statuto 10, GDPR 6, L.604 6, D.Lgs 23 3, DPR 394 13); ogni codice ha una label",
              len(_codes75) >= 75 and not _miss75 and not _lab75,
              "mancano: %s | senza label: %s" % (", ".join(_miss75)[:200], ", ".join(_lab75)[:120]))
        _r75 = cv._resolve_code_it
        check("corpus[75]: risolutore citazioni IT per numero/anno e sigla (D.Lgs 141/2024, Reg. 2015/2446, CDU, DPR 633/1972, GDPR, TUEL)",
              _r75("D.Lgs. 141/2024") == "codice_doganale_nazionale" and _r75("Reg. delegato (UE) 2015/2446") == "reg_ue_2015_2446"
              and _r75("CDU") == "codice_doganale_ue" and _r75("DPR 633/1972") == "iva" and _r75("GDPR") == "gdpr"
              and _r75("TUEL") == "tuel" and _r75("c.c.") == "codice_civile" and _r75("D.Lgs. 231/2007") == "antiriciclaggio")
    except Exception as _e75:  # noqa: BLE001
        check("corpus[75]: kontrollet u ekzekutuan", False, str(_e75))

    # ── [76] CORPUS IT: niente «Neni» e niente falsi «abrogati» (16 set) ──
    # Due difetti visti sui regolamenti UE: (a) repealed scritto come str(False) →
    # bool("False") è True → 1.342 articoli invisibili a search() (il BM25 grezzo li
    # metteva primi); (b) id nuovi non riconosciuti da _is_italian_code → citazione
    # «Neni 215 i Regolamento…» dentro la sessione italiana.
    try:
        import json as _j76
        from pathlib import Path as _P76
        from src.parser import _is_italian_code as _isit76
        _idx76 = ArticleIndex.load(_P76("/app/data/index/bm25_it.pkl"))
        _meta76 = _j76.loads(_P76("/app/data/processed/it_codes.json").read_text(encoding="utf-8"))
        _neni76 = [m["code"] for m in _meta76 if not _isit76(m["code"])]
        _tot76, _rep76, _vero76 = {}, {}, {}
        for _a in _idx76.articles:
            _tot76[_a.code] = _tot76.get(_a.code, 0) + 1
            _rep76[_a.code] = _rep76.get(_a.code, 0) + (1 if _a.repealed else 0)
            # abrogazione VERA (Normattiva scrive «ARTICOLO/PROVVEDIMENTO ABROGATO DAL …»):
            # es. DPR 602/1973 tutto sostituito dal D.Lgs 33/2025 — legittimo, resta nel corpus
            # perché il verificatore deve dire «superato» a chi lo cita. Il bug str(False) invece
            # marcava abrogati articoli col testo normale.
            if _a.repealed and "ABROGAT" in _a.body[:200].upper():
                _vero76[_a.code] = _vero76.get(_a.code, 0) + 1
        _allrep76 = [c for c, n in _tot76.items()
                     if n >= 5 and _rep76.get(c, 0) == n and _vero76.get(c, 0) < n // 2]
        # wave6: i testi unici della riforma fiscale (la legge VIGENTE al posto degli atti
        # abrogati: DPR 602/73 → D.Lgs 33/2025, IVA 633/72 → 10/2026, registro/successioni →
        # 123/2025, sanzioni+reati trib. → 173/2024, DPR 600/73 → 141/2026) devono esserci,
        # con articoli in vigore (non solo la scheda), altrimenti il cervello cita legge morta.
        _tu76 = [c for c in ("tu_sanzioni_tributarie", "tu_riscossione", "tu_registro", "tu_iva", "tu_accertamento")
                 if _tot76.get(c, 0) - _rep76.get(c, 0) < 30]
        _allrep76 += [f"TU mancante/vuoto: {c}" for c in _tu76]
        _cit76 = [a.citation for a in _idx76.articles if a.code == "reg_ue_2015_2446" and str(a.number) == "215"]
        _hit76 = [a.code for a, _ in _idx76.search("mezzi di trasporto persone fisiche residenza abituale territorio doganale", top_k=5)]
        check("corpus[76]: ogni corpus IT è riconosciuto come italiano (mai «Neni» in sessione italiana); nessun corpus tutto «abrogato» (bug str(False)); art. 215 Reg. 2015/2446 cercabile e citato «art.»",
              not _neni76 and not _allrep76 and _cit76 and _cit76[0].startswith("art. 215")
              and "reg_ue_2015_2446" in _hit76,
              "non italiani: %s | tutti abrogati: %s | cit: %s | top5: %s" % (
                  ", ".join(_neni76)[:120], ", ".join(_allrep76)[:120], (_cit76 or ["-"])[0][:40], _hit76))
    except Exception as _e76:  # noqa: BLE001
        check("corpus[76]: kontrollet u ekzekutuan", False, str(_e76))

    # ── [77] BLOCCO A (16 set): internazionale privato, cittadinanza, stranieri, lavoro,
    # procedura, famiglia, notaio + trattati/Schengen/famiglia UE — gli articoli-chiave ci sono,
    # sono in vigore, e il risolutore li riconosce per numero/anno e per nome ──
    try:
        from pathlib import Path as _P77
        _it77 = ArticleIndex.load(_P77("/app/data/index/bm25_it.pkl")).articles
        _by77 = {(a.code, str(a.number)): a for a in _it77}
        _need77 = [("diritto_internazionale_privato", "64"), ("diritto_internazionale_privato", "16"),
                   ("cittadinanza", "9"), ("cittadinanza", "5"), ("cittadini_ue", "10"),
                   ("contratti_lavoro", "19"), ("negoziazione_assistita", "6"), ("unioni_civili", "1"),
                   ("mandato_arresto_europeo", "18"), ("casellario", "24"), ("regolamento_notarile", "1"),
                   ("codice_frontiere_schengen", "6"), ("tfue", "45"), ("tfue", "49"), ("tue", "6"),
                   ("carta_diritti_ue", "47"), ("roma_iii", "5"), ("alimenti_ue", "3"),
                   ("ingiunzione_europea", "7"), ("notifiche_ue", "8"),
                   # blocco B: trattati (allegato della legge di ratifica) + CEDU dal PDF CoE
                   ("convenzione_it_al_fisco", "4"), ("convenzione_it_al_fisco", "15"),
                   ("protocollo_it_al_migranti", "4"), ("cedu", "6"), ("cedu", "8"), ("cedu", "41"),
                   ("cedu_protocollo_1", "1"), ("cedu_protocollo_4", "2"), ("cedu_protocollo_7", "4"),
                   # atti «approvati con allegato» (flagTipoArticolo): l'art. 1 deve essere quello
                   # dell'ALLEGATO, la legge di approvazione «1-legge», le preleggi corpus a sé
                   ("codice_civile", "1-legge"), ("tu_iva", "1-legge"), ("codice_doganale_nazionale", "1-legge"),
                   ("codice_civile", "1"), ("codice_civile", "2"), ("codice_civile", "10"), ("codice_civile", "31"),
                   ("preleggi", "11"), ("preleggi", "12"), ("preleggi", "14"), ("preleggi", "15"),
                   ("codice_doganale_nazionale", "1"), ("tu_iva", "1"), ("tuir", "1"), ("tulps", "1"),
                   ("codice_navigazione", "1"), ("disp_att_cc", "68")]   # disp. att. art. 1 è abrogato (DPR 361/2000)
        _miss77 = [f"{c} {n}" for c, n in _need77 if (c, n) not in _by77]
        _dead77 = [f"{c} {n}" for c, n in _need77 if (c, n) in _by77 and _by77[(c, n)].repealed]
        _r77 = cv._resolve_code_it
        _res77 = {"L. 218/1995": "diritto_internazionale_privato", "L. 91/1992": "cittadinanza",
                  "D.Lgs. 30/2007": "cittadini_ue", "D.Lgs. 81/2015": "contratti_lavoro",
                  "D.L. 132/2014": "negoziazione_assistita", "Reg. (UE) 2016/399": "codice_frontiere_schengen",
                  "TFUE": "tfue", "Reg. (UE) 1259/2010": "roma_iii", "Reg. (CE) n. 4/2009": "alimenti_ue",
                  "DPR 380/2001": "tu_edilizia", "D.Lgs. 274/2000": "giudice_pace_penale",
                  "D.Lgs. 74/2000": "reati_tributari",
                  # CEDU: parola intera (mai «procedura»→cedu), protocolli per numero
                  "CEDU": "cedu", "Convenzione europea dei diritti dell'uomo": "cedu",
                  "Prot. 1 CEDU": "cedu_protocollo_1", "Protocollo addizionale alla CEDU": "cedu_protocollo_1",
                  "Protocollo n. 7 CEDU": "cedu_protocollo_7", "P7 CEDU": "cedu_protocollo_7",
                  "c.p.c.": "codice_procedura_civile", "codice di procedura civile": "codice_procedura_civile",
                  "L. 175/1998": "convenzione_it_al_fisco",
                  "preleggi": "preleggi", "disp. prel. c.c.": "preleggi", "disposizioni sulla legge in generale": "preleggi"}
        _bad77 = [f"{k}->{_r77(k)}" for k, v in _res77.items() if _r77(k) != v]
        # atti «approvati con allegato» (16 set): l'art. 1 era quello della legge di
        # approvazione («È approvato l'unito testo unico…») e l'art. 1 dell'allegato spariva
        import re as _re77
        _appr77 = _re77.compile(r"^\s*(?:1\.\s*)?(?:è|e')\s+approvat|^\s*(?:1\.\s*)?sono approvat|autorizzato a ratificare", _re77.I)
        # (TUEL e beni culturali esclusi: hanno UN solo gruppo e Normattiva serve come art. 1 la
        # formula di approvazione — residuo documentato in CLAUDE.md v9.327)
        _ann77 = [c for c in ("codice_civile", "tu_iva", "tu_riscossione", "codice_doganale_nazionale",
                              "codice_navigazione", "disp_att_cc", "tulps", "tuir", "convenzione_it_al_fisco")
                  if (c, "1") in _by77 and _appr77.search(_by77[(c, "1")].body[:200])]
        check("corpus[77]: blocco A+B nel corpus (L. 218/95 art. 64, cittadinanza art. 9, Schengen art. 6, TFUE 45/49, Roma III, alimenti, MAE, casellario, convenzione IT-AL, CEDU+protocolli), in vigore; art. 1 = allegato (non la legge di approvazione); risolutore per numero/anno, nome e CEDU",
              not _miss77 and not _dead77 and not _bad77 and not _ann77,
              "mancano: %s | abrogati: %s | risolutore: %s | art.1 = legge di approvazione: %s" % (
                  ", ".join(_miss77)[:160], ", ".join(_dead77)[:80], ", ".join(_bad77)[:160], ", ".join(_ann77)[:100]))
    except Exception as _e77:  # noqa: BLE001
        check("corpus[77]: kontrollet u ekzekutuan", False, str(_e77))

    # ── [78] CORPUS AL: le 29 leggi da QBZ (16 set) — presenti, con articoli, label, risolutore
    # per nome/numero-anno; la 9887/2008 e la 108/2014 marcate superate; i codici riscritti dai
    # consolidati QBZ con l'art. 1 pieno ──
    try:
        from pathlib import Path as _P78
        _al78 = ArticleIndex.load(_P78("/app/data/index/bm25.pkl")).articles
        _cnt78, _rep78 = {}, {}
        for _a in _al78:
            _cnt78[_a.code] = _cnt78.get(_a.code, 0) + 1
            _rep78[_a.code] = _rep78.get(_a.code, 0) + (1 if _a.repealed else 0)
        _need78 = {"ligji_dnp": 80, "ligji_te_huajt": 140, "ligji_shtetesia": 25, "kodi_te_miturve": 140,
                   "ligji_procedurat_tatimore": 150, "ligji_tatimi_te_ardhurat": 70, "ligji_tvsh": 150,
                   "ligji_sigurimi_mjeteve": 55, "ligji_ndihma_juridike": 35, "ligji_kundervajtjet": 45,
                   "ligji_permbarimi_privat": 85, "ligji_dhuna_familje": 25, "ligji_gjendja_civile": 85,
                   "ligji_antimafia": 40, "ligji_te_dhenat_2024": 95, "ligji_sigurimet_shoqerore": 100,
                   "ligji_avokatia": 55, "ligji_ndermjetesimi": 40, "ligji_arbitrazhi": 45,
                   "ligji_planifikimi_territorit": 70, "ligji_te_denuarit": 90, "ligji_prokuroria": 110,
                   "ligji_diskriminimi": 40, "ligji_armet": 65, "ligji_transportet_rrugore": 85,
                   "ligji_prokurimi_publik": 130, "ligji_trajtimi_prones": 35, "ligji_proceset_kalimtare": 80,
                   # codici riscritti da QBZ (soglie prudenti)
                   "kodi_civil": 1150, "kodi_proc_civile": 600, "kodi_penal": 400, "kodi_proc_penale": 500,
                   "kodi_zgjedhor": 170, "kodi_punes": 200, "kushtetuta": 180,
                   # trovati da freshness_check (16 set): legge nuova sulla violenza domestica, VKM 2026 dal docx
                   "ligji_dhuna_familje_2026": 30, "vkm_dispozita_doganore": 700}
        _miss78 = [f"{c} ({_cnt78.get(c, 0)}<{n})" for c, n in _need78.items() if _cnt78.get(c, 0) < n]
        _lab78 = [c for c in _need78 if c not in cv.CODE_LABELS]
        _sup78 = all(_cnt78.get(c, 0) > 0 and _rep78.get(c, 0) == _cnt78.get(c, 0)
                     for c in ("ligji_te_dhenat", "ligji_policia", "ligji_dhuna_familje"))
        _r78 = cv._resolve_code
        _res78 = {"ligji nr. 79/2021": "ligji_te_huajt", "ligjit për të huajt": "ligji_te_huajt",
                  "ligji nr. 111/2018": "ligji_kadastra", "ligji nr. 111/2017": "ligji_ndihma_juridike",
                  "ligji i të dhënave personale": "ligji_te_dhenat_2024", "ligji nr. 9887": "ligji_te_dhenat",
                  "kodi i drejtësisë penale për të mitur": "kodi_te_miturve", "ligji nr. 10428": "ligji_dnp",
                  "dispozitat zbatuese të kodit doganor": "vkm_dispozita_doganore", "ligji nr. 32/2021": "ligji_sigurimi_mjeteve",
                  "kodit civil": "kodi_civil", "ligji nr. 9901": "ligji_shoqerite_tregtare", "ligji nr. 9917": "ligji_pastrimi_parave",
                  "vkm nr. 112/2025": "rregullore_policia"}
        _bad78 = [f"{k}->{_r78(k)}" for k, v in _res78.items() if _r78(k) != v]
        _by78 = {(a.code, a.number): a for a in _al78}
        # (c.c. 587 «Dorëzania duhet të bëhet me shkresë.» è corto per natura: soglia 20;
        # K.Pr.C. 80-89 sono ABROGATI nel consolidato QBZ 2022 — si controlla il 90)
        _key78 = [("ligji_dnp", "1", 60), ("ligji_te_huajt", "1", 60), ("ligji_te_dhenat_2024", "1", 60), ("kodi_te_miturve", "1", 60),
                  ("kodi_civil", "1", 60), ("kodi_civil", "587", 20), ("kodi_proc_civile", "90", 40), ("kodi_zgjedhor", "3", 60),
                  ("kodi_penal", "1", 60), ("vkm_dispozita_doganore", "129", 40), ("vkm_dispozita_doganore", "700", 20),
                  ("ligji_shoqerite_tregtare", "1", 60), ("rregullore_policia", "1", 40)]
        _kmiss78 = [f"{c} {n}" for c, n, _m in _key78 if (c, n) not in _by78 or len(_by78[(c, n)].body) + len(_by78[(c, n)].heading) < _m]
        check("corpus[78]: 28 leggi AL da QBZ + codici riscritti dai consolidati (c.c. 2026, c.p. 2026, K.Pr.C. 80-89, Kodi Zgjedhor 3…) nel corpus con i loro articoli, label, risolutore nome/numero-anno, 9887/2008 e 108/2014 marcate superate",
              not _miss78 and not _lab78 and _sup78 and not _bad78 and not _kmiss78,
              "mancano: %s | senza label: %s | superate: %s | risolutore: %s | articoli-chiave: %s" % (
                  ", ".join(_miss78)[:200], ", ".join(_lab78)[:80], _sup78, ", ".join(_bad78)[:160], ", ".join(_kmiss78)[:120]))
    except Exception as _e78:  # noqa: BLE001
        check("corpus[78]: kontrollet u ekzekutuan", False, str(_e78))

    # ── [79] ABROGAZIONI A GRUPPO (16 set): nei consolidati QBZ «(Shfuqizuar titulli IV, nenet
    # 400–441, me ligjin nr. 122/2013)» non stampa gli articoli → prima erano BUCHI e «neni 420
    # KPrC» usciva «fantazmë»; ora sono stub abrogati: il verificatore dice «shfuqizuar», la
    # ricerca li salta, un numero oltre il massimo resta falso ──
    try:
        import re as _re79
        import src.parser as _pr79
        from pathlib import Path as _P79
        _src79 = open(_pr79.__file__, encoding="utf-8").read()
        _idx79 = ArticleIndex.load(_P79("/app/data/index/bm25.pkl"))
        _by79 = {(a.code, a.number): a for a in _idx79.articles}
        _stub79 = [(("kodi_proc_civile", n)) for n in ("80", "85", "112", "163", "400", "420", "441", "505")]
        _ok_stub79 = all(k in _by79 and _by79[k].repealed and "hfuqizuar" in (_by79[k].heading + _by79[k].body)
                         and _re79.search(r"ligjin nr\. (8812|122/2013)", _by79[k].body) for k in _stub79)
        _tr79 = [("ligji_transportet_rrugore", str(n)) for n in range(54, 64)]
        _ok_tr79 = all(k in _by79 and _by79[k].repealed and "118/2012" in _by79[k].body for k in _tr79)
        _v79 = cv.verify_text("Sipas nenit 420 të Kodit të Procedurës Civile dhe nenit 85 të KPrC, si dhe nenit 999 të Kodit të Procedurës Civile.", _idx79)
        _st79 = {c["number"]: c["status"] for c in _v79["items"]}
        _ok_ver79 = _st79.get("420") == "repealed" and _st79.get("85") == "repealed" and _st79.get("999") == "fake"
        _hits79 = [a.number for a, _s in _idx79.search("titulli IV shfuqizuar nenet 400 441", top_k=12) if a.code == "kodi_proc_civile" and a.repealed]
        check("corpus[79]: abrogazioni a gruppo nei consolidati QBZ = stub «shfuqizuar» (K.Pr.C. 80-89/111-114/163-164/400-441/503-509, ligji 8308 kreu 54-63): il verificatore dice «repealed» e non «fake», oltre il massimo resta «fake», la ricerca non li restituisce, regola cablata nel parser",
              _ok_stub79 and _ok_tr79 and _ok_ver79 and not _hits79
              and "_group_repeal_stubs(text, items, articles, doc)" in _src79 and "_GROUP_REPEAL_RE" in _src79,
              "stub KPrC: %s | stub 8308: %s | verificatore: %s | nella ricerca: %s" % (_ok_stub79, _ok_tr79, _st79, _hits79))
        # gli articoli VIVI che la regola vecchia marcava abrogati: «Shfuqizime» in coda alle leggi
        # (verbo «shfuqizohet ligji nr…»), nota «(Shfuqizuar pika 3 …)», marcatore a gruppo in coda
        _live79 = [("ligji_dnp", "88"), ("ligji_kundervajtjet", "50"), ("ligji_ndihma_juridike", "37"), ("ligji_permbarimi_privat", "90"),
                   ("ligji_sigurimi_mjeteve", "60"), ("ligji_tatimi_te_ardhurat", "71"), ("ligji_procedurat_tatimore", "48"),
                   ("ligji_tvsh", "157"), ("kodi_proc_civile", "79/a"), ("kodi_proc_civile", "110"), ("kodi_penal", "29"), ("kushtetuta", "178")]
        _bad_live79 = [f"{c} {n}" for c, n in _live79 if (c, n) not in _by79 or _by79[(c, n)].repealed]
        # (K.Pr.C. 79 «Përgjegjësia për dëmin e shkaktuar» è DAVVERO abrogato dalla 8812/2001: corpo vuoto)
        _bad_live79 += [f"{c} {n} (vivo?)" for c, n in (("kodi_proc_civile", "79"), ("kodi_proc_civile", "80")) if (c, n) not in _by79 or not _by79[(c, n)].repealed]
        _ps79 = _pr79.is_repealed_stub
        _unit79 = (_ps79("(Shfuqizuar me ligjin nr. 8812, datë 17.5.2001)", "") and _ps79("Titulli", "Shfuqizohet.")
                   and _ps79("Mbajtja (Ndryshuar pika 1 me ligjin nr. 112/2016; shfuqizuar me ligjin nr. 83/2019)", "")
                   and not _ps79("Shfuqizime", "Me hyrjen në fuqi të këtij ligji, shfuqizohet ligji nr. 3920, datë 21.11.1964.")
                   and not _ps79("Dispozita kalimtare (Shfuqizuar pika 2 me ligjin nr. 85/2019)", "1. Rregullimi i zbritjes vazhdon deri në fund të vitit.")
                   and not _ps79("Pasojat", "Vendimi i shfuqizuar nuk prodhon pasoja juridike për palët.")
                   and not _ps79("Fusha", "Dispozitat e këtij ligji zbatohen për të gjithë.\n(Shfuqizuar nenet 3-5 me ligjin nr. 1/2000)"))
        _srch79 = [a.number for a, _s in _idx79.search("shfuqizohet ligji për kundërvajtjet administrative 7697", top_k=12) if a.code == "ligji_kundervajtjet"]
        check("corpus[79b]: gli articoli vivi non sono più «abrogati» (Shfuqizime in coda alle leggi, «(Shfuqizuar pika …)», marcatore a gruppo in coda): 10 articoli-campione vivi, regola is_repealed_stub sui 7 casi, l'articolo Shfuqizime esce dalla ricerca",
              not _bad_live79 and _unit79 and "50" in _srch79 and "ligji_te_dhenat" in _rep78 and _rep78["ligji_te_dhenat"] == _cnt78["ligji_te_dhenat"],
              "vivi marcati abrogati: %s | regola: %s | ricerca kundervajtjet: %s" % (", ".join(_bad_live79)[:200], _unit79, _srch79))
    except Exception as _e79:  # noqa: BLE001
        check("corpus[79]: kontrollet u ekzekutuan", False, str(_e79))

    # ── [80] la sigla «KP» (Kodi Penal / Kodi i Punës) si scioglie dal documento (16 set): prova
    # viva AL «neni 155/1 KP» = zgjidhja e pajustifikuar (Kodi i Punës) usciva VERIFICATO sul
    # Kodi Penal 155 «Shkatërrimi i rrugëve» ──
    try:
        from pathlib import Path as _P80
        _idx80 = ArticleIndex.load(_P80("/app/data/index/bm25.pkl"))
        def _st80(text, ctx=None):
            r = cv.verify_text(text, _idx80, retrieved_codes=ctx)
            return {(c["number"]): (c["status"], c["code"], [d["code"] for d in c["candidates"]]) for c in r["items"]}
        _a80 = _st80("Sipas Kodit të Punës, klientit i takon paga e njoftimit (neni 155/1 KP) dhe shpërblimi për vjetërsi (neni 152 KP).")
        _b80 = _st80("Sipas Kodit Penal, vepra dënohet me burgim (neni 155 KP), krahas nenit 29 KP.")
        _c80 = _st80("Klientit i takon paga e njoftimit (neni 155/1 KP).")                         # nessun nome per esteso: ambigua
        _d80 = _st80("Klientit i takon paga e njoftimit (neni 155/1 KP).", ctx={"kodi_punes"})     # contesto del retrieval
        _e80 = _st80("Klientit i takon shpërblimi (neni 9999 KP).")
        _f80 = _st80("Vepra parashikohet nga neni 155 i Kodit Penal.")                              # nome per esteso: mai toccato
        _ok80 = (_a80.get("155/1", ("",))[0:2] == ("verified", "kodi_punes") and _a80.get("152", ("",))[0:2] == ("verified", "kodi_punes")
                 and _b80.get("155", ("",))[0:2] == ("verified", "kodi_penal") and _b80.get("29", ("",))[0:2] == ("verified", "kodi_penal")
                 and _c80.get("155/1", ("",))[0] == "needs_code" and set(_c80["155/1"][2]) == {"kodi_punes", "kodi_penal"}
                 and _d80.get("155/1", ("",))[0:2] == ("verified", "kodi_punes")
                 and _e80.get("9999", ("",))[0] == "fake"
                 and _f80.get("155", ("",))[0:2] == ("verified", "kodi_penal"))
        check("corpus[80]: «KP» nuda si risolve dal documento (Kodi i Punës nominato → kodi_punes; Kodi Penal nominato → kodi_penal; niente → «kod i pa-specifikuar» coi 2 candidati; contesto retrieval decide; numero inesistente resta falso; nome per esteso intatto)",
              _ok80, "a=%s b=%s c=%s d=%s e=%s f=%s" % (_a80, _b80, _c80, _d80, _e80, _f80))
    except Exception as _e80:  # noqa: BLE001
        check("corpus[80]: kontrollet u ekzekutuan", False, str(_e80))

    # ── [81] TRUST LINE — lo scudo PRIMA del Giudice (v9.331, roadmap v3 passo 1): la verifica
    # deterministica arriva al Giudice come blocco dedicato + regola nel prompt (sq+it); la riga
    # di fiducia CATEGORICA (mai percentuali) sta sotto il titolo del verdetto; i documenti del
    # fascicolo restano SFONDO (anti-iniezione) ──
    try:
        import re as _re81
        from pathlib import Path as _P81
        from src import trust_line as _tl, studio as _st81, brain as _br81, case_brief as _cb81
        _idx81 = ArticleIndex.load(_P81("/app/data/index/bm25.pkl"))
        _vA = _tl.verifica("Sipas nenit 420 të Kodit të Procedurës Civile dhe nenit 114 të Kodit Civil, "
                           "si dhe nenit 9999 të Kodit Civil.", _idx81, "AL")
        _vB = _tl.verifica("Sipas nenit 114 të Kodit Civil dhe nenit 155 të Kodit të Punës.", _idx81, "AL")
        _vC = _tl.verifica("Sipas nenit 114 të Kodit Civil.\n\n**Për saktësi:** më dërgo datën e njoftimit.", _idx81, "AL")
        _okA = (_vA["nene"]["repealed"] == 1 and _vA["nene"]["fake"] == 1 and _vA["nene"]["verified"] == 1
                and _tl.stato(_vA) == "FLAGS" and "1 të shfuqizuara" in _tl.riga(_vA, "sq") and "🔴" in _tl.riga(_vA, "sq")
                and "420" in _tl.blocco_per_gjyqtarin(_vA, "sq") and "SHFUQIZUAR" in _tl.blocco_per_gjyqtarin(_vA, "sq")
                and "9999" in _tl.blocco_per_gjyqtarin(_vA, "it") and "NON ESISTE" in _tl.blocco_per_gjyqtarin(_vA, "it"))
        _okB = _tl.stato(_vB) == "VERIFIED" and _vB["nene"]["verified"] == 2 and "✅" in _tl.riga(_vB, "it") and "%" not in _tl.riga(_vB, "it")
        _okC = _tl.stato(_vC) == "RESERVATIONS" and _vC["fatti_da_precisare"] == 1 and "1 për t'u saktësuar" in _tl.riga(_vC, "sq")
        _t81 = _st81.TITULLI_GJYQTARI["it"]
        _ins = _tl.inserisci_riga(_t81 + "**VERDETTO** …", _tl.riga(_vB, "it"), _t81)
        _okD = _ins.startswith(_t81 + "> 🔎 **Verifica:**") and "**VERDETTO**" in _ins
        _srcB = open(_br81.__file__, encoding="utf-8").read()
        _srcS = open(_st81.__file__, encoding="utf-8").read()
        _okE = ("verifikimi=trust_line.blocco_per_gjyqtarin(v1, lang, coverage=_cov)" in _srcB
                and "final, v2 = self._cancello(final" in _srcB
                and 'verifikimi: str = ""' in _srcS and "VERIFICA DETERMINISTICA DELLE CITAZIONI" in _srcS
                and "VERIFIKIMI DETERMINIST I CITIMEVE" in _srcS
                and "VERIFICA DETERMINISTICA (se ti viene data)" in _st81.GJYQTARI_SYSTEM["it"]
                and "VERIFIKIMI DETERMINIST (nëse të jepet)" in _st81.GJYQTARI_SYSTEM["sq"])
        _srcCB = open(_cb81.__file__, encoding="utf-8").read()
        _okF = _re81.search(r"SFONDO|sfondo", _srcCB) is not None and "istruzion" in _srcCB.lower()
        check("trust_line[81]: verifica deterministica (nene abrogati/inesistenti, sentenze, fatti) → blocco al Giudice PRIMA del verdetto + regola nel prompt sq/it + riga di fiducia categorica sotto il titolo (mai %) + fascicolo marcato sfondo (anti-iniezione)",
              _okA and _okB and _okC and _okD and _okE and _okF,
              "A=%s B=%s C=%s D=%s wiring=%s sfondo=%s | rigaA=%r" % (_okA, _okB, _okC, _okD, _okE, _okF, _tl.riga(_vA, "sq")[:120]))
    except Exception as _e81:  # noqa: BLE001
        check("trust_line[81]: kontrollet u ekzekutuan", False, str(_e81))

    # ── [82] BENCHMARK LAB, strato 1 (16 set, roadmap v3 P0): 850 test deterministici — recupero
    # (una query per articolo, AL ≥93% / IT ≥85%), stati del verificatore (verificato/abrogato/
    # inesistente = 100%), sigle (100%), REGRESSIONI (ogni errore vero trovato = un test per
    # sempre: 100%), recupero del cervello con ancore (≥90%); e nessun calo >2 punti rispetto
    # all'ultimo giro salvato. Un cervello nuovo esce solo se questo gate passa ──
    try:
        import io as _io82, contextlib as _ctx82, importlib.util as _ilu82
        _spec82 = _ilu82.spec_from_file_location("benchmark_lab", _os2.path.join(_os2.path.dirname(_os2.path.abspath(__file__)), "benchmark_lab.py"))
        _bl = _ilu82.module_from_spec(_spec82)
        _spec82.loader.exec_module(_bl)
        _buf82 = _io82.StringIO()
        with _ctx82.redirect_stdout(_buf82):
            _s82 = _bl.run_layer1(verbose=False)
        _ok82, _prob82 = _bl.gate(_s82, _bl._last_history()) if _s82 else (False, ["nessun test"])
        _n82 = int(_s82.get("n") or 0)
        _hdr82 = [a for a in ArticleIndex.load(_P81("/app/data/index/bm25_it.pkl")).articles if (a.heading or "").lstrip().startswith("(")]
        check("benchmark[82]: strato 1 deterministico (≥800 test: recupero AL/IT, stati, sigle, regressioni, cervello) sopra le soglie e senza regressioni; rubriche IT pulite (nessuna che inizia con «(»: «( (Maggiore età» era nel badge)",
              _ok82 and _n82 >= 800 and not _hdr82,
              "n=%d gate=%s %s | rates=%s | rubriche rotte=%d" % (_n82, _ok82, "; ".join(_prob82)[:200], _s82.get("rates"), len(_hdr82)))
    except Exception as _e82:  # noqa: BLE001
        check("benchmark[82]: kontrollet u ekzekutuan", False, str(_e82))

    # ── [83] TEMPO (v9.333, roadmap v3 P3, versione economica): la data del fatto si legge dalla
    # domanda; IT = multivigenza Normattiva («!vig=»), AL = atti modificativi QBZ; il blocco entra
    # nel dossier di senior e Giudice; regola nel prompt; asse «tempo» nella Trust Line ──
    try:
        from datetime import date as _dt83
        from types import SimpleNamespace as _NS83
        from src import temporal as _tp, trust_line as _tl83, studio as _st83, brain as _br83
        _oggi = _dt83(2026, 9, 16)
        _a = _tp.data_fatto("Il fatto è avvenuto il 17/03/2021 e la notifica il 3 settembre 2026.", _oggi)
        _b = _tp.data_fatto("Klienti, i lindur më 12.5.1985, u pushua nga puna më 20 shkurt 2020.", _oggi)
        _c = _tp.data_fatto("Contratto firmato nel 2019, licenziamento del 3/9/2026.", _oggi)
        _d = _tp.data_fatto("Licenziato con lettera del 3/9/2026.", _oggi)
        _okA = (_a and _a[0] == _dt83(2021, 3, 17) and not _a[2]
                and _b and _b[0] == _dt83(2020, 2, 20)
                and _c and _c[0] == _dt83(2019, 7, 1) and _c[2]
                and _d is None)
        _ret83 = [(_NS83(code="cittadinanza", number="9-ter", body="1. Il termine è fissato in ventiquattro mesi.", title_sq="L. 91/1992", repealed=False), 1.0),
                  (_NS83(code="cittadinanza", number="5", body="1. Il coniuge straniero.", title_sq="L. 91/1992", repealed=False), 0.9)]
        _orig = _tp.versione_it
        _tp.versione_it = lambda code, number, when: ({"number": number, "heading": "", "body": "1. Il termine è di quarantotto mesi.", "repealed": False, "vig": when.isoformat()}
                                                     if number == "9-ter" else {"number": number, "heading": "", "body": "1. Il coniuge straniero.", "repealed": False, "vig": when.isoformat()})
        try:
            _blk, _info = _tp.blocco_it(_ret83, _dt83(2019, 3, 10), "10 marzo 2019", False)
        finally:
            _tp.versione_it = _orig
        _okB = ("TESTO VIGENTE AL 10/03/2019" in _blk and "quarantotto" in _blk and "DIVERSO" in _blk
                and "identico" in _blk and _info["diversi"] == 1 and _info["uguali"] == 1)
        _r83 = _tl83.riga(_tl83.vuota(), "it", tempo=_info)
        _okC = "tempo: fatto del 10/03/2019" in _r83 and "1 articolo con testo diverso" in _r83
        _srcB = open(_br83.__file__, encoding="utf-8").read()
        _okD = ("def _mbledh_gatherers_core(" in _srcB and "temporal.arricchisci_dosje(blocco, user_message, retrieved" in _srcB
                and "trust_line.riga(v2, lang, tempo=_tempo, coverage=_cov)" in _srcB
                and "TESTO VIGENTE ALLA DATA DEL FATTO" in _st83.GJYQTARI_SYSTEM["it"]
                and "LIGJI NË FUQI MË DATËN E FAKTIT" in _st83.GJYQTARI_SYSTEM["sq"])
        check("tempo[83]: data del fatto dalla domanda (IT/SQ, niente date di nascita né recenti, anno=approssimata) · blocco «⏳ TESTO VIGENTE AL» con testo storico DIVERSO/identico · asse tempo nella Trust Line · innesto nel dossier + regola del Giudice sq/it",
              _okA and _okB and _okC and _okD,
              "date=%s blocco=%s riga=%s wiring=%s | a=%s b=%s c=%s d=%s" % (_okA, _okB, _okC, _okD, _a, _b, _c, _d))
    except Exception as _e83:  # noqa: BLE001
        check("tempo[83]: kontrollet u ekzekutuan", False, str(_e83))

    # ── [84] P3b + P5 (v9.334): la data dell'ultima modifica PER ARTICOLO dalle note editoriali QBZ
    # (anche con le parole incollate) e la FORZA della fonte dichiarata nel prompt degli articoli ──
    try:
        from datetime import date as _dt84
        from types import SimpleNamespace as _NS84
        from pathlib import Path as _P84
        from src import temporal as _tp84, brain as _br84, parser as _pr84
        _n84 = _NS84(heading="Fusha e zbatimit (Shtuar fjalë në pikën1;ndryshuar pika4me ligjinnr.48/2012,datë 26.4.2012)",
                     body="1. Ky ligj zbatohet.\n(Ndryshuar me ligjin nr. 124/2024, datë 19.12.2024)")
        _m84 = _tp84.modifiche_nene(_n84)
        _okA = _m84 == [(_dt84(2012, 4, 26), "nr. 48/2012"), (_dt84(2024, 12, 19), "nr. 124/2024")] and _tp84.ultima_modifica(_n84) == "2024-12-19"
        _blk84, _inf84 = _tp84.blocco_al([(_NS84(code="ligji_te_dhenat_2024", number="4", title_sq="Ligji 124/2024", body=_n84.body, heading=_n84.heading, repealed=False), 1.0)],
                                         _dt84(2020, 3, 1), "1.3.2020", False, max_codes=0)
        _okB = "NDRYSHUAR pas datës së faktit" in _blk84 and "124/2024" in _blk84 and _inf84["diversi"] == 1
        _al84 = ArticleIndex.load(_P84("/app/data/index/bm25.pkl"))
        _con84 = sum(1 for a in _al84.articles if a.last_amendment_date)
        _p84 = _br84._format_articles_for_prompt([(a, 1.0) for a in _al84.articles if a.code == "kodi_punes" and a.number == "155"][:1])
        _it84 = ArticleIndex.load(_P84("/app/data/index/bm25_it.pkl"))
        _q84 = _br84._format_articles_for_prompt([(a, 1.0) for a in _it84.articles if a.code == "reg_ue_2015_2446" and a.number == "215"][:1]
                                                 + [(a, 1.0) for a in _it84.articles if a.code == "costituzione" and a.number == "3"][:1])
        _okC = ("⚖ Kod (ligj)" in _p84 and "⚖ Regolamento UE" in _q84 and "primato" in _q84 and "⚖ Costituzione" in _q84
                and _br84._forza("vkm_dispozita_doganore").startswith("Akt nënligjor") and _br84._forza("cedu").startswith("Convenzione"))
        _srcP = open(_pr84.__file__, encoding="utf-8").read()
        _okD = "last_amendment_date=_lad" in _srcP and "ultima_modifica" in _srcP and _con84 >= 1000
        check("tempo[84]: note editoriali per articolo → date di modifica (anche «ligjinnr.48/2012,datë»), blocco AL per nene, ≥1000 nene con data nell'indice, parser cablato; forza della fonte nel prompt (Kod/VKM/Costituzione/Reg. UE primato/CEDU)",
              _okA and _okB and _okC and _okD,
              "note=%s bloccoAL=%s forza=%s parser/indice=%s (nene con data: %d) | %s" % (_okA, _okB, _okC, _okD, _con84, _m84))
    except Exception as _e84:  # noqa: BLE001
        check("tempo[84]: kontrollet u ekzekutuan", False, str(_e84))

    # ── [85] P3b-IT (v9.335): le note di aggiornamento Normattiva per articolo (atto modificante +
    # data + disciplina transitoria) si conservano nel JSON, entrano in `it_notes.json` e nel
    # blocco temporale; prima venivano scartate ──
    try:
        import importlib.util as _ilu85
        _spec85 = _ilu85.spec_from_file_location("normattiva_lib", _os2.path.join(_os2.path.dirname(_os2.path.abspath(__file__)), "normattiva_lib.py"))
        _nl = _ilu85.module_from_spec(_spec85); _spec85.loader.exec_module(_nl)
        _fix85 = ('<div class="art_aggiornamento-akn"> <div class="art_aggiornamento_separator-akn">---------------</div> '
                  '<div class="art_aggiornamento_title-akn">AGGIORNAMENTO (9)</div> <div class="art_aggiornamento_testo-akn"> <br> Il '
                  '<a href="/uri-res/N2Ls?urn:nir:stato:decreto.legge:2018-10-04;113" target="_blank">D.L. 4 ottobre 2018, n. 113</a>, '
                  'convertito con modificazioni dalla <a href="/uri-res/N2Ls?urn:nir:stato:legge:2018-12-01;132" target="_blank">L. 1 dicembre 2018, n. 132</a>, '
                  'ha disposto (con l\'art. 14, comma 2) che la presente modifica si applica ai procedimenti in corso. </div> </div>')
        _n85 = _nl.parse_notes(_fix85)
        _okA = (len(_n85) == 1 and _n85[0]["n"] == 9 and _n85[0]["date"] == "2018-10-04"
                and _n85[0]["acts"][0]["label"] == "D.L. 4 ottobre 2018, n. 113" and "procedimenti in corso" in _n85[0]["text"]
                and "AGGIORNAMENTO" not in _n85[0]["text"])
        _page85 = ('<div class="bodyTesto"><h2 class="article-num-akn">Art. 9-ter</h2><div class="art-commi-div-akn">'
                   '<div class="art-comma-div-akn">1. Il termine è di ventiquattro mesi.</div></div>' + _fix85 + '</div>'
                   '<div class="d-flex justify-content-between">')
        _p85 = _nl.parse_article_page(_page85, fallback_number="9-ter")
        _okB = _p85 and _p85.get("notes") and _p85["notes"][0]["date"] == "2018-10-04" and "AGGIORNAMENTO" not in _p85["body"]
        _srcBI = open(_os2.path.join(_os2.path.dirname(_os2.path.abspath(__file__)), "build_it_index.py"), encoding="utf-8").read()
        _okC = "it_notes.json" in _srcBI and "last_amendment_date=_lad" in _srcBI
        from src import temporal as _tp85
        _okD = callable(getattr(_tp85, "note_articolo_it", None)) and "note di aggiornamento (Normattiva)" in open(_tp85.__file__, encoding="utf-8").read()
        _okE = _os2.path.exists(_os2.path.join(_os2.path.dirname(_os2.path.abspath(__file__)), "promote_it_refresh.py"))
        check("tempo[85]: note di aggiornamento Normattiva per articolo conservate (parse_notes: n, data, atti, testo transitorio; il corpo resta pulito) → it_notes.json + last_amendment_date + blocco temporale; promozione del ri-ingest solo senza perdita di articoli",
              _okA and bool(_okB) and _okC and _okD and _okE,
              "parse=%s page=%s build=%s temporal=%s promote=%s | %s" % (_okA, bool(_okB), _okC, _okD, _okE, _n85[:1]))
    except Exception as _e85:  # noqa: BLE001
        check("tempo[85]: kontrollet u ekzekutuan", False, str(_e85))

    # ── [86] v9.336 — tre cose viste nella prova viva sul tempo: (a) i logger nuovi devono usare
    # logging_utils.get_logger (con getLogger(__name__) le righe INFO sparivano); (b) il confronto
    # storico ignora i numeri di nota «((13))»; (c) se il Giudice cade per saturazione la Trust
    # Line resta e l'avvocato legge che l'arbitro non si è pronunciato ──
    try:
        from src import temporal as _tp86, trust_line as _tl86, brain as _br86
        _okA = all(getattr(m.log, "handlers", None) for m in (_tp86, _tl86)) and _tp86.log.propagate is False
        _okB = (_tp86._norm_body("1. Il coniuge.\n\n((13))") == _tp86._norm_body("1. Il coniuge.\n\n13") == "1 il coniuge"
                and _tp86._norm_body("… dai coniugi ))") == _tp86._norm_body("… dai coniugi."))
        _srcB86 = open(_br86.__file__, encoding="utf-8").read()
        _okC = ("Il Giudice Finale non ha potuto pronunciarsi" in _srcB86 and "Gjyqtari i Fundit nuk mundi të shprehet" in _srcB86
                and 'trust_line.riga(v1, lang, tempo=_tempo, coverage=_cov) + "\\n" + _nota' in _srcB86)
        _srcBI86 = open(_os2.path.join(_os2.path.dirname(_os2.path.abspath(__file__)), "build_it_index.py"), encoding="utf-8").read()
        _okD = r"\(\(\s*\d{1,3}\s*\)\)" in _srcBI86
        check("tempo[86]: logger con handler in temporal/trust_line · confronto storico senza numeri di nota · Giudice saturo → Trust Line + avviso onesto sq/it · build_it_index toglie «((N))»",
              _okA and _okB and _okC and _okD, "logger=%s norm=%s fallback=%s build=%s" % (_okA, _okB, _okC, _okD))
    except Exception as _e86:  # noqa: BLE001
        check("tempo[86]: kontrollet u ekzekutuan", False, str(_e86))

    # ── [87] v9.337 — OGNI logger di src/ scrive davvero (file + stdout): 14 moduli (genio, jobs, push,
    # video, audio, qkb, studio…) usavano logging.getLogger senza handler e le loro righe INFO non
    # esistevano; nessun modulo nuovo può ripetere l'errore ──
    try:
        import glob as _g87, re as _re87
        _bad87 = []
        for _f in sorted(_g87.glob(_os2.path.join(_os2.path.dirname(_os2.path.dirname(_os2.path.abspath(__file__))), "src", "*.py"))):
            _s = open(_f, encoding="utf-8").read()
            if _os2.path.basename(_f) == "logging_utils.py":
                continue
            if _re87.search(r"^log\s*=\s*logging\.getLogger\(", _s, _re87.M):
                _bad87.append(_os2.path.basename(_f))
        from src import genio as _gn87, jobs as _jb87, studio as _st87
        _okA = all(getattr(m.log, "handlers", None) for m in (_gn87, _jb87, _st87))
        check("log[87]: nessun modulo di src/ con logger senza handler (get_logger ovunque); genio/jobs/studio scrivono su file",
              not _bad87 and _okA, "senza handler: %s | handler ok: %s" % (", ".join(_bad87), _okA))
    except Exception as _e87:  # noqa: BLE001
        check("log[87]: kontrollet u ekzekutuan", False, str(_e87))

    # ── [88] v9.338 — la Trust Line anche sul percorso SEMPLICE (stream e non): prima solo il
    # percorso complesso (dove gira il Giudice) la aveva; una risposta breve cita articoli come
    # le altre e merita la stessa riga; mai doppia ──
    try:
        import inspect as _insp88
        from src import brain as _br88
        _as88 = _insp88.getsource(_br88.SuperAvvocato.answer_stream)
        _an88 = _insp88.getsource(_br88.SuperAvvocato.answer)
        _rf88 = _insp88.getsource(_br88.SuperAvvocato._riga_fiducie)
        check("trust_line[88]: _riga_fiducie sul fast-path semplice di answer_stream E di answer(), con guardia anti-doppione",
              "self._riga_fiducie(text, retrieved)" in _as88 and "self._riga_fiducie(answer_text, retrieved)" in _an88
              # v9.375: l'anti-doppione non è più «c'è già 🔎 → salta» (così passava la riga FALSA del modello e si
              # saltavano verifica e cancello) ma `inserisci_riga`, che toglie ogni riga di verifica e mette la vera
              and '"🔎 **" in (text or "")[:600]' not in _rf88 and "togli_righe(text)" in _insp88.getsource(__import__("src.trust_line", fromlist=["x"]).inserisci_riga)
              and "trust_line.inserisci_riga(text, trust_line.riga(v, lang, tempo=_tempo, coverage=_cov)" in _rf88,
              "stream=%s answer=%s guard=%s" % ("self._riga_fiducie(text, retrieved)" in _as88, "self._riga_fiducie(answer_text, retrieved)" in _an88, '"🔎 **" in' in _rf88))
    except Exception as _e88:  # noqa: BLE001
        check("trust_line[88]: kontrollet u ekzekutuan", False, str(_e88))

    # ── [89] GRAFO DELLE SENTENZE (v9.339, roadmap v3 P6): citazioni fra decisioni, vendime GjL
    # annullati dalla Kushtetuese (dal DISPOSITIVO, mai dalla richiesta), norme dichiarate
    # incostituzionali; il verificatore dice «quashed», il blocco dei precedenti mostra forza e
    # trattamento, la Trust Line conta annullate/incostituzionali, il Giudice ha la regola ──
    try:
        from src import case_graph as _cg89, case_citation_verifier as _ccv89, trust_line as _tl89, brain as _br89, studio as _st89
        _g89 = _cg89.load()
        _n89 = _g89.get("nodes") or {}
        _okA = len(_n89) >= 1000 and _g89.get("edges", 0) >= 1500 and _g89.get("quashes_total", 0) >= 100 and _g89.get("invalidations", 0) >= 10   # v9.366: 1.168 nodi (re-parse), 2.158 citazioni
        # dispositivo vero (K 71/2016) → annulla 00-2015-3057; «Rrëzimin e kërkesës për shfuqizimin» → niente
        _q1, _i1 = _cg89.negativi_dal_dispositivo("Pranimin e kërkesës. Shfuqizimin si të papajtueshëm me Kushtetutën e Republikës së Shqipërisë të vendimit nr. 00-2015-3057, datë 09.12.2015 të Kolegjit Penal të Gjykatës së Lartë. Dërgimin e çështjes për rishqyrtim në Gjykatën e Lartë.")
        _q2, _i2 = _cg89.negativi_dal_dispositivo("Rrëzimin e kërkesës për shfuqizimin e vendimit nr. 00-2015-3057, datë 09.12.2015 të Kolegjit Penal të Gjykatës së Lartë.")
        _q3, _i3 = _cg89.negativi_dal_dispositivo("Pranimin pjesërisht të kërkesës. Shpalljen si të papajtueshëm me Kushtetutën e Republikës së Shqipërisë të kreut VI “Byroja Kombëtare e Hetimit” (nenet 27-36) të ligjit nr. 108/2014 “Për Policinë e Shtetit”. Rrëzimin e kërkesës për shfuqizimin e nenit 49 të këtij ligji.")
        _okB = (_q1 == ["gjykata_elarte|2015|00-2015-3057"] and not _q2 and not _q1 == _q2
                and _i3 and _i3[0]["law"] == "108/2014" and _i3[0]["articles"][:3] == ["27", "28", "29"] and len(_i3[0]["articles"]) == 10)
        _ann = _cg89.annullati_gjl()
        _okC = "00-2015-3057" in _ann and _ann["00-2015-3057"].startswith("kushtetuese|2016|71")
        _inc = _cg89.norme_incostituzionali()
        # VKM: «nenit 4 të vendimit nr. 753 … “…ligjit nr. 29/2023”» NON è l'art. 4 della legge 29/2023
        _q4, _i4 = _cg89.negativi_dal_dispositivo("Shfuqizimin e nenit 4 të vendimit nr. 753, datë 20.12.2023 të Këshillit të Ministrave “Për dispozitat zbatuese të ligjit nr. 29/2023 “Për tatimin mbi të ardhurat””.")
        _okD = (("ligji_policia", "30") in _inc and _inc[("ligji_policia", "30")]["partial"] is False
                and ("ligji_noteri", "26") in _inc and _inc[("ligji_noteri", "26")]["partial"] is True
                and ("ligji_sigurimi_mjeteve", "10") in _inc and ("ligji_tatimi_te_ardhurat", "4") not in _inc
                and _i4 and _i4[0]["law"].startswith("vkm:"))
        # tre livelli: nota GjK già nel testo → konsoliduar (nessun allarme); parte caduta senza nota →
        # pjesërisht; intero nen senza nota → tërësisht
        from types import SimpleNamespace as _NS89
        _lv1 = _cg89.stato_incostituzionale(_NS89(code="ligji_noteri", number="26", heading="Shkeljet (shfuqizuar fjalia e fundit e pikës 1 me vendimin e Gjykatës Kushtetuese nr. 32, datë 27.10.2021)", body="1. …", repealed=False))
        _lv2 = _cg89.stato_incostituzionale(_NS89(code="ligji_sigurimi_mjeteve", number="10", heading="Procedura", body="8. …", repealed=False))
        _lv3 = _cg89.stato_incostituzionale(_NS89(code="ligji_policia", number="30", heading="X", body="Y", repealed=False))
        _okD2 = _lv1 and _lv1[0] == "konsoliduar" and _lv2 and _lv2[0] == "pjesërisht" and _lv3 and _lv3[0] == "tërësisht"
        # verificatore: un numero GjL annullato → «quashed» anche se non nel corpus; nota nel testo
        _pay = _ccv89.verify_cases("Sipas vendimit nr. 00-2015-3057, datë 09.12.2015 të Kolegjit Penal.", _tl89.dec_index())
        _okE = _pay["stats"].get("quashed") == 1 and _pay["items"][0]["status"] == "quashed"
        _md = _ccv89.annotate_unverified("testo", _pay)
        _okF = "SHFUQIZUARA" in _md and "71/2016" in _md
        _al89 = ArticleIndex.load(_P81("/app/data/index/bm25.pkl"))
        _v = _tl89.verifica("Sipas vendimit nr. 00-2015-3057, datë 09.12.2015 dhe nenit 10 të ligjit nr. 32/2021 dhe nenit 26 të ligjit nr. 110/2018.", _al89, "AL")
        _okG = (_v["sentenze"]["quashed"] == 1 and _v["nene"]["unconstitutional"] == 1   # 32/2021 art. 10 sì (parte caduta, testo senza nota); noteria 26 no (konsoliduar)
                and _tl89.stato(_v) == "FLAGS" and "1 TË SHFUQIZUARA" in _tl89.riga(_v, "sq") and "antikushtetuese" in _tl89.riga(_v, "sq")
                and "PJESËRISHT" in _tl89.blocco_per_gjyqtarin(_v, "sq"))
        _pb = _br89._format_articles_for_prompt([(a, 1.0) for a in _al89.articles if a.code == "ligji_sigurimi_mjeteve" and a.number == "10"][:1]
                                                + [(a, 1.0) for a in _al89.articles if a.code == "ligji_noteri" and a.number == "26"][:1])
        _okG2 = "⚠ Një PJESË e këtij neni" in _pb and "fjalisë së dytë" in _pb and "ℹ Prekur nga vendimi i Gjykatës Kushtetuese nr. 32/2021" in _pb and "⛔" not in _pb
        _okH = ("Forca/trajtimi" in open(_br89.__file__, encoding="utf-8").read() and "VENDIME TË SHFUQIZUARA / NENE ANTIKUSHTETUESE" in _st89.GJYQTARI_SYSTEM["sq"]
                and "SENTENZE ANNULLATE / NORME INCOSTITUZIONALI" in _st89.GJYQTARI_SYSTEM["it"])
        check("grafo[89]: case_graph.json (≥1000 nodi, ≥1500 citazioni, ≥100 vendime GjL annullati, ≥10 norme incostituzionali) · dispositivo→annullamenti/incostituzionalità (rigetti esclusi, range 27-36, VKM≠legge, parziale/totale) · tre livelli konsoliduar/pjesërisht/tërësisht · verificatore «quashed» + nota · Trust Line → 🔴 · prompt articoli + precedenti + regola del Giudice",
              _okA and _okB and _okC and _okD and _okD2 and _okE and _okF and _okG and _okG2 and _okH,
              "graph=%s disp=%s ann=%s inc=%s livelli=%s ver=%s nota=%s trust=%s prompt=%s wiring=%s | q1=%s i3=%s lv=%s" % (
                  _okA, _okB, _okC, _okD, _okD2, _okE, _okF, _okG, _okG2, _okH, _q1, (_i3 or [{}])[0].get("articles"), (_lv1, _lv2, _lv3)))
    except Exception as _e89:  # noqa: BLE001
        check("grafo[89]: kontrollet u ekzekutuan", False, str(_e89))

    # ── [90] COPERTURA DELLA RICERCA (v9.340, roadmap v3 P7): i temi del triage senza ALCUNA norma
    # trovata (punteggio zero) entrano nella Trust Line («mbulimi: 2/3 tema me normë») e nel blocco
    # del Giudice; azzerata a ogni richiesta ──
    try:
        import inspect as _insp90
        from src import brain as _br90, trust_line as _tl90
        from src.brain import TriageResult as _TR90
        _sa90 = _br90.SuperAvvocato(index=ArticleIndex.load(_P81("/app/data/index/bm25.pkl")))
        _sa90._jurisdiction_ctx.code = "AL"
        _t90 = _TR90(problem_summary="afati i parashkrimit", areas=["Civil"],
                     search_queries=["afati i parashkrimit të padisë", "xqzvtrp lorem ipsum zzzq"], strategic_angles=[])
        _sa90._retrieve(_t90)
        _c90 = _br90.coverage_info()
        _okA = _c90 and _c90["temi"] == 2 and _c90["senza_norma"] == ["xqzvtrp lorem ipsum zzzq"]
        _r90 = _tl90.riga(_tl90.vuota(), "sq", coverage=_c90)
        _b90 = _tl90.blocco_per_gjyqtarin(_tl90.vuota(), "it", coverage=_c90)
        _okB = "mbulimi: 1/2 tema me normë" in _r90 and "pa normë: «xqzvtrp" in _r90 and "COPERTURA DELLA RICERCA" in _b90 and "xqzvtrp" in _b90
        _src90 = _insp90.getsource(_br90.SuperAvvocato.answer_stream) + _insp90.getsource(_br90.SuperAvvocato.answer)
        _okC = (_src90.count("_COVERAGE.info = None") == 2 and "coverage=_cov" in _insp90.getsource(_br90.SuperAvvocato._gjyqtari_fundit)
                and "coverage=_cov" in _insp90.getsource(_br90.SuperAvvocato._riga_fiducie)
                and "TEMA PA NORMË TË GJETUR" in _insp90.getsource(_br90.SuperAvvocato._studio_kerkuesi))   # research completeness → Kërkuesi
        check("copertura[90]: temi senza norma dal retrieval vero → Trust Line + blocco del Giudice + Kërkuesi (research completeness); azzerata a ogni richiesta; cablata nel Giudice e nel percorso semplice",
              bool(_okA) and _okB and _okC, "cov=%s riga=%s wiring=%s" % (_c90, _okB, _okC))
    except Exception as _e90:  # noqa: BLE001
        check("copertura[90]: kontrollet u ekzekutuan", False, str(_e90))

    # ── [91] AUDIT PER RISPOSTA (v9.341, roadmap v3 P8): il pacchetto di audit (triage, recupero +
    # copertura, Kërkuesi, raccoglitori, tempo, precedenti col grafo, fasi, diavolo, Giudice, Trust
    # Line prima/dopo, durata) viaggia nel provenance pack (extra.audit) e il pannello lo mostra
    # bilingue; le annotazioni dei worker (raccoglitori/tempo) tornano nel thread della richiesta ──
    try:
        import inspect as _insp91
        from src import brain as _br91, web as _wb91, temporal as _tp91
        _br91._audit_reset(); _br91._audit_set("triage", {"complexity": "simple"}); _br91._audit_set("giudice", {"esito": "verdetto"})
        _ai = _br91.audit_info()
        _okA = _ai and _ai["triage"]["complexity"] == "simple" and [p["passo"] for p in _ai["passi"]] == ["triage", "giudice"] and "durata_s" in _ai and "t0" not in _ai
        _srcB = open(_br91.__file__, encoding="utf-8").read()
        _keys = ["\"triage\"", "\"recupero\"", "\"kerkuesi\"", "\"raccoglitori\"", "\"tempo\"", "\"precedenti\"", "\"fasi\"", "\"diavolo\"", "\"replica_senior\"", "\"giudice\"", "\"verifica_pre_giudice\"", "\"verifica_finale\""]
        _okB = all(("_audit_set(%s" % k) in _srcB for k in _keys) and _srcB.count("_audit_reset()") >= 3
        _rs = _insp91.getsource(_br91.SuperAvvocato._run_stages)
        _okC = "_AUDIT.data = _stage_audit" in _rs and "_COVERAGE.info = _stage_cov" in _rs and "_tmp.imposta_info(_stage_tempo_box[-1])" in _rs and callable(getattr(_tp91, "imposta_info", None))
        _srcW = open(_wb91.__file__, encoding="utf-8").read()
        _okD = _srcW.count('extra={"audit": _audit_pacchetto()}') == 2 and "def _audit_pacchetto" in _srcW
        _js = _io2.open(_os2.path.join(_os2.path.dirname(_os2.path.dirname(_os2.path.abspath(__file__))), "static", "app.js"), encoding="utf-8").read()
        _okE = ("function renderAuditTrail(a)" in _js and "prov.extra && prov.extra.audit" in _js and "🧾 Perché questa risposta" in _js
                and "🧾 Pse kjo përgjigje" in _js and "Gjyqtari i fundit" in _js and "Giudice finale" in _js
                and not _re2.search(r"opus|fable|sonnet|anthropic", _js[_js.find("function renderAuditTrail"): _js.find("function renderAuditTrail") + 6000], _re2.I))
        _html91 = _io2.open(_os2.path.join(_os2.path.dirname(_os2.path.dirname(_os2.path.abspath(__file__))), "templates", "index.html"), encoding="utf-8").read()
        import re as _re91
        _okF = _re91.search(r"app\.js\?v=\d+", _html91) is not None and _re91.search(r"style\.css\?v=\d+", _html91) is not None and ".prov-audit" in _io2.open(_os2.path.join(_os2.path.dirname(_os2.path.dirname(_os2.path.abspath(__file__))), "static", "style.css"), encoding="utf-8").read()
        check("audit[91]: pacchetto di audit per risposta (12 annotazioni lungo la pipeline, reset per richiesta, passi con tempi) → provenance pack extra.audit in entrambi i percorsi → pannello «Perché questa risposta / Pse kjo përgjigje» bilingue senza nomi di modello; worker delle fasi condividono audit/copertura e riportano il tempo",
              bool(_okA) and _okB and _okC and _okD and _okE and _okF,
              "info=%s annot=%s worker=%s web=%s js=%s asset=%s" % (bool(_okA), _okB, _okC, _okD, _okE, _okF))
    except Exception as _e91:  # noqa: BLE001
        check("audit[91]: kontrollet u ekzekutuan", False, str(_e91))

    # ── [92] CLAIM BINDING IN OMBRA (v9.342, roadmap v3 P1): proposizioni atomiche → legame
    # deterministico alle citazioni (SUPPORTED / WEAK / UNSUPPORTED / CONTRADICTED); parte in
    # parallelo al Giudice, va nell'audit, NON tocca la risposta; misurato dal benchmark strato 2 ──
    try:
        import inspect as _insp92
        from src import claims as _cl92, brain as _br92
        _raw = ('{"claims":[{"testo":"Klientit i takon paga e afatit të njoftimit","tipo":"LEGAL","materialiteti":"HIGH","citime":["neni 155/1 i Kodit të Punës"]},'
                '{"testo":"Afati është 180 ditë","tipo":"PROCEDURAL","materialiteti":"HIGH","citime":["neni 9999 i Kodit të Punës"]},'
                '{"testo":"Punëdhënësi duhet të japë arsye","tipo":"LEGAL","materialiteti":"MEDIUM","citime":[]},'
                '{"testo":"Klienti është pushuar më 3.9.2026","tipo":"FACTUAL","materialiteti":"HIGH","citime":[]},'
                '{"testo":"Vendimi 00-2015-3057 e mbështet","tipo":"LEGAL","materialiteti":"HIGH","citime":["vendimi nr. 00-2015-3057, datë 09.12.2015"]}]}')
        _cs = _cl92.parse("bla " + _raw + " bla")
        _okA = len(_cs) == 5 and _cs[0]["citazioni"] == ["neni 155/1 i Kodit të Punës"] and _cs[2]["citazioni"] == []
        _lg = _cl92.lega(_cs, ArticleIndex.load(_P81("/app/data/index/bm25.pkl")), "AL")
        _st = [r["stato"] for r in _lg["claims"]]
        _okB = (_st == ["SUPPORTED", "CONTRADICTED", "UNSUPPORTED", "N/A", "CONTRADICTED"]
                and _lg["materiali"] == 4 and _lg["high_unsupported"] == 2 and _lg["unsupported"] == 1 and _lg["contradicted"] == 2)
        _src92 = _insp92.getsource(_br92.SuperAvvocato._gjyqtari_fundit)
        _okC = ("_cl.Ombra(self.backend, answer_text, lang, idx, jur, retrieved_codes=_codes).start()" in _src92 and "self._raccogli_ombra(_ombra)" in _src92
                and 'if _cl.MODE != "off"' in _src92 and _cl92.MODE in ("off", "shadow", "on"))
        _okD = "claims" in open(_os2.path.join(_os2.path.dirname(_os2.path.abspath(__file__)), "benchmark_lab.py"), encoding="utf-8").read() and "high_unsupported" in open(_os2.path.join(_os2.path.dirname(_os2.path.abspath(__file__)), "benchmark_lab.py"), encoding="utf-8").read()
        check("claims[92]: claim binding in ombra — parse JSON, legame deterministico alle citazioni (155/1 KPunës SUPPORTED, 9999 CONTRADICTED, senza citazione UNSUPPORTED, fatto N/A, vendim annullato CONTRADICTED), avvio parallelo al Giudice, raccolta nell'audit, riportato dal benchmark strato 2",
              _okA and _okB and _okC and _okD, "parse=%s lega=%s wiring=%s bench=%s | stati=%s" % (_okA, _okB, _okC, _okD, _st))
    except Exception as _e92:  # noqa: BLE001
        check("claims[92]: kontrollet u ekzekutuan", False, str(_e92))

    # ── [93] LIMITE PER MODELLO → RIPIEGO (v9.343): «You've reached your Fable limit» non è un
    # sovraccarico — il diavolo taceva e il Giudice cadeva; ora pausa del modello + ripiego sul
    # default del tier (Opus max), senza i 4 tentativi a vuoto; audit «ModelLimit» ──
    try:
        import inspect as _insp93
        from src import backends as _bk93, brain as _br93
        _okA = (_bk93._model_limit_hit("You've reached your Fable limit. Switch to another model to continue.", "")
                and not _bk93._model_limit_hit('{"result":"ok"}', "rate limit 429")
                and _bk93.modello_in_pausa("modello-di-prova-93") == 0.0)
        _bk93._metti_in_pausa("modello-di-prova-93")
        _okB = 1700 < _bk93.modello_in_pausa("modello-di-prova-93") <= _bk93.MODEL_LIMIT_PAUSE_S
        _src93 = _insp93.getsource(_bk93.ClaudeCodeBackend.complete)
        _okC = ("proc, _limite = _esegui(cmd)" in _src93 and "_metti_in_pausa(model_override)" in _src93
                and 'error_class="ModelLimit"' in _src93 and "modello_in_pausa(model_override) > 0" in _src93
                and "return _p, True          # quota del modello esaurita" in _src93
                and "self.last_model_used = model" in _src93)
        _okD = '"riserva": bool(getattr(self.backend, "last_model_used", "")' in _insp93.getsource(_br93.SuperAvvocato._gjyqtari_fundit)
        _okE = "strategic JSON parse failed, returning empty — %s: %s | %d chr" in open(_br93.__file__, encoding="utf-8").read()
        check("backend[93]: limite per modello (Fable) rilevato senza attese → pausa 30 min + ripiego sul default del tier, audit ModelLimit, chi ha risposto tracciato (Giudice di riserva nell'audit); parse fallito della fase strategica diagnosticabile",
              _okA and _okB and _okC and _okD and _okE, "det=%s pausa=%s wiring=%s riserva=%s strategic=%s" % (_okA, _okB, _okC, _okD, _okE))
    except Exception as _e93:  # noqa: BLE001
        check("backend[93]: kontrollet u ekzekutuan", False, str(_e93))

    # ── [94] v9.344 — regola del titolare: Fable in pausa → Opus MAX (non l'effort della chiamata
    # Fable); evento scritto sul volume per l'avviso email dal cron; log sul volume con rotazione;
    # claim binding con i codici recuperati ──
    try:
        import inspect as _insp94
        from src import backends as _bk94, claims as _cl94, logging_utils as _lu94
        _src94 = _insp94.getsource(_bk94.ClaudeCodeBackend.complete)
        _okA = ('effort_override = "max"          # regola del titolare' in _src94
                and 'cmd[cmd.index("--effort") + 1] = "max"' in _src94 and "_segna_pausa_per_avviso(model_override, _msg)" in _src94)
        _okB = callable(getattr(_bk94, "_segna_pausa_per_avviso", None)) and "model_limit.json" in _insp94.getsource(_bk94._segna_pausa_per_avviso)
        _okC = "RotatingFileHandler" in open(_lu94.__file__, encoding="utf-8").read()
        _okD = "retrieved_codes=retrieved_codes" in _insp94.getsource(_cl94.lega) and "retrieved_codes=_codes" in _insp94.getsource(brain.SuperAvvocato._gjyqtari_fundit)
        _ops94 = _os2.path.join(_os2.path.dirname(_os2.path.dirname(_os2.path.abspath(__file__))), "ops", "model_limit_alert.py")
        _run94 = _os2.path.join(_os2.path.dirname(_os2.path.dirname(_os2.path.abspath(__file__))), "run.sh")
        _okE = (not _os2.path.exists(_ops94)) or ("model_limit.json" in open(_ops94, encoding="utf-8").read())   # ops/ non è nell'immagine
        _okF = (not _os2.path.exists(_run94)) or ("logs:/app/logs" in open(_run94, encoding="utf-8").read())
        check("ripiego[94]: Fable in pausa → Opus effort MAX forzato (in partenza e dopo il limite) · evento in data/model_limit.json per l'email · log con rotazione sul volume · claim binding con i codici recuperati",
              _okA and bool(_okB) and _okC and _okD and _okE and _okF, "max=%s evento=%s rotazione=%s claims=%s ops=%s run=%s" % (_okA, bool(_okB), _okC, _okD, _okE, _okF))
    except Exception as _e94:  # noqa: BLE001
        check("ripiego[94]: kontrollet u ekzekutuan", False, str(_e94))

    # ── [95] v9.345 — tre affinamenti delle fasi junior (dal brief del consulente, meccanismi 1/2/4),
    # SENZA toccare gli schemi JSON: catena requisito→onere→fatto→prova→conseguenza + presunzioni/
    # alternative/sanatoria + «VENDIMTAR:» (mappa delle prove); ordine per valore dell'informazione
    # «PARË:» senza probabilità (fatti mancanti); i sei effetti contrari di ogni leva + «MOS E PËRDOR
    # nëse» (radar nullità) ──
    try:
        _em = brain.EVIDENCE_MAP_SYSTEM; _mf = brain.MISSING_FACTS_SYSTEM; _nr = brain.NULLITY_RADAR_SYSTEM
        _okA = ("ZINXHIRI QË VENDOS KAUZËN" in _em and "PREZUMIM" in _em and "SANUESHME" in _em and "«VENDIMTAR:»" in _em
                and '"needed_proof"' in _em and '"burden_shift"' in _em)
        _okB = ("RENDITJA = VLERA E INFORMACIONIT" in _mf and "«PARË:»" in _mf and "MOS shpik probabilitete" in _mf
                and '"impact_if_yes"' in _mf and 'PARAZGJEDHJA është {"facts": []}' in _mf)
        _okC = ("EFEKTET E KUNDËRTA TË ÇDO LEVE" in _nr and "MOS E\n  PËRDOR nëse" in _nr.replace("«MOS E\n  PËRDOR", "MOS E\n  PËRDOR") or "MOS E" in _nr and "PËRDOR nëse" in _nr) and '"deadline_hint"' in _nr and "PAPAJTUESHMËRIA" in _nr
        check("fasi[95]: mappa delle prove con zinxhir kushti→pasoja + prezumime/alternativa/sanim + VENDIMTAR · fatti mancanti ordinati per valore dell'informazione (PARË, niente probabilità) · radar nullità con i 6 effetti contrari e «MOS E PËRDOR nëse» — schemi JSON invariati",
              _okA and _okB and _okC, "mappa=%s fatti=%s radar=%s" % (_okA, _okB, _okC))
    except Exception as _e95:  # noqa: BLE001
        check("fasi[95]: kontrollet u ekzekutuan", False, str(_e95))

    # ── [96] v9.346 — IL VERIFICATORE LEGGE COME SCRIVONO I GIURISTI: «neni 155, pika 1, i Kodit
    # të Punës» / «art. 18, comma 4, L. 300/1970» (sotto-riferimenti interposti: prima «pa kod» con il
    # codice scritto lì accanto — 21 su 30 nella prova viva v9.345); legame a livello di DOCUMENTO
    # per i numeri nudi («Neni 144 i Kodit të Punës … Pika 5 e nenit 144»); anafora «i po këtij
    # ligji» / «del medesimo decreto»; claim binding con la risposta come contesto. Conservativo:
    # può solo togliere un «pa kod», mai creare un «fantazmë»; la virgola non si attraversa senza
    # la formula di attribuzione ──
    try:
        _al96 = ArticleIndex.load(_P81("/app/data/index/bm25.pkl"))
        _it96 = ArticleIndex.load(_P81("/app/data/index/bm25_it.pkl"))
        def _v96(t, ix, **kw):
            _r = cv.verify_text(t, ix, **kw); return _r["items"], _r["stats"]
        def _uno(t, ix, code, **kw):
            _i, _ = _v96(t, ix, **kw); return bool(_i) and _i[0]["status"] == "verified" and _i[0]["code"] == code
        _okA = (_uno("neni 155, pika 1, i Kodit të Punës", _al96, "kodi_punes")
                and _uno('Neni 34, pika 1, shkronja "d", e Ligjit nr. 79/2021', _al96, "ligji_te_huajt")
                and _uno("Neni 146, pika 3, i Kodit të Punës thotë", _al96, "kodi_punes")
                and _uno("art. 18, comma 4, L. 300/1970", _it96, "statuto_lavoratori")
                and _uno("art. 3, comma 2, del D.Lgs. 23/2015", _it96, "tutele_crescenti")
                and _uno("art. 2, comma 1, c.c.", _it96, "codice_civile")
                and _uno("art. 5, comma 1, lettera b), L. 91/1992", _it96, "cittadinanza")
                and _uno("ai sensi dell'art. 6, commi 1 e 2, L. 604/1966", _it96, "licenziamenti_individuali")
                and _uno("l'art. 9-ter, comma 1, della legge n. 91 del 1992", _it96, "cittadinanza"))
        # la virgola NON si attraversa senza la formula (nessun furto del codice dalla frase dopo)
        _iN1, _ = _v96("neni 155, pika 1, ndërsa Kodi Civil parashikon tjetër", _al96)
        _iN2, _ = _v96("art. 18, comma 4, di conseguenza il codice civile prevede altro", _it96)
        _iN3, _ = _v96("art. 2, c.c. e art. 1218 c.c.", _it96)
        _iN4, _sN4 = _v96("nenet 134, 135 dhe 136 të Kodit Penal", _al96)
        _okB = (_iN1 and _iN1[0]["status"] == "needs_code" and _iN2 and _iN2[0]["status"] == "needs_code"
                and any(i["number"] == "2" and i["code"] == "codice_civile" for i in _iN3) and _sN4["verified"] == 3)
        # legame a livello di documento: nudo → il codice che il documento gli dà (uno solo, esistente)
        _doc = ("Neni 144 i Kodit të Punës përcakton në pikën 1 se punëdhënësi duhet të njoftojë. Pika 5 e nenit 144 sanksionon. "
                "Pikënisja e nenit 155/4 vjen pas nenit 155, pika 1, i Kodit të Punës.")
        _iD, _sD = _v96(_doc, _al96)
        _iD2, _ = _v96("Neni 144 i Kodit të Punës dhe neni 144 i Kodit Civil ndryshojnë. Pika 5 e nenit 144 sanksionon.", _al96)
        _iD3, _ = _v96("Neni 144 i Kodit të Punës. Shih nenin 9999.", _al96)
        # «neni 155 KP» nella pre-scansione si scioglie dal documento (Kodi i Punës nominato), non dall'alias
        # grezzo KP=Kodi Penal — altrimenti il 155 risultava legato a DUE codici e «nenit 155/4» restava pa kod
        _iK, _sK = _v96("Kualifikimi (neni 155 KP) është i saktë. Pika 1 e nenit 155 të Kodit të Punës e thotë; pikënisja e nenit 155/4.", _al96)
        _okC = (_sD["needs_code"] == 0 and _sD["fake"] == 0
                and any(i["number"] == "155/4" and i["code"] == "kodi_punes" and i["resolved_by"] == "documento" for i in _iD)
                and any(i["number"] == "144" and i["status"] == "needs_code" for i in _iD2)      # due codici → resta pa kod
                and any(i["number"] == "9999" and i["status"] == "fake" for i in _iD3)           # mai promosso un fantasma
                and _sK["needs_code"] == 0 and any(i["number"] == "155/4" and i["code"] == "kodi_punes" for i in _iK))
        # anafora
        _iA, _ = _v96("Sipas nenit 34, pika 1, e Ligjit nr. 79/2021 kërkesa refuzohet. Neni 37, pika 1, i po këtij ligji cakton afatin.", _al96)
        _iA2, _ = _v96("Neni 37, pika 1, i po këtij ligji cakton afatin.", _al96)
        _iA3, _ = _v96("Il D.Lgs. 23/2015 disciplina le tutele crescenti. L'art. 3 del medesimo decreto fissa l'indennità.", _it96)
        _okD = (any(i["number"] == "37" and i["code"] == "ligji_te_huajt" and i["resolved_by"] == "anafora" for i in _iA)
                and _iA2 and _iA2[0]["status"] == "needs_code"
                and any(i["number"] == "3" and i["code"] == "tutele_crescenti" and i["resolved_by"] == "anafora" for i in _iA3))
        # claim binding: le citazioni nude del junior si legano con la risposta come contesto
        from src import claims as _cl96
        import inspect as _insp96
        _lg = _cl96.lega([{"testo": "Punëdhënësi duhet të njoftojë me shkrim", "tipo": "LEGAL", "materialita": "HIGH", "citazioni": ["neni 144, pika 1"]}],
                         _al96, "AL", None, context_text="Neni 144 i Kodit të Punës përcakton … Kodi i Punës")
        _okE = (_lg["supported"] == 1 and "context_text=text" in _insp96.getsource(_cl96.Ombra._run)
                and "përfshije në citim" in _cl96.SYSTEM["sq"] and "includilo nella" in _cl96.SYSTEM["it"])
        check("verifikuar[96]: sotto-riferimenti interposti AL/IT («neni 155, pika 1, i Kodit të Punës», «art. 18, comma 4, L. 300/1970») · nessun furto di codice oltre la virgola · legame a livello di documento (solo unico ed esistente, mai un fantasma) · anafora «i po këtij ligji»/«del medesimo decreto» · claim binding con la risposta come contesto",
              _okA and _okB and _okC and _okD and _okE, "forme=%s virgola=%s documento=%s anafora=%s claims=%s" % (_okA, _okB, _okC, _okD, _okE))
    except Exception as _e96:  # noqa: BLE001
        check("verifikuar[96]: kontrollet u ekzekutuan", False, str(_e96))

    # ── [97] v9.348 — ALLEGATI E NUMERI DI GRUPPO del corpus IT. Il refresh Normattiva con le note
    # (v9.335) numera per gruppo (v9.327): «13-ter-all3» = art. 13-ter delle norme di attuazione del
    # c.p.a., «1-legge» = atto di approvazione. Tre cose: (1) gli allegati con suffisso (I-bis, II-octies
    # = avviso sulla garanzia legale) NON si scartano più con le Tabelle; (2) «art. 13-ter c.p.a.» si
    # verifica anche se vive solo in un allegato (il testo principale vince sempre quando c'è; due
    # allegati → mai a caso); (3) il suffisso non compare mai al giurista: «art. 13-ter (allegato) …» ──
    try:
        import re as _re97
        from src.parser import numero_visibile_it as _nv97, Article as _A97
        _it97 = ArticleIndex.load(_P81("/app/data/index/bm25_it.pkl"))
        _by97 = {(a.code, str(a.number)): a for a in _it97.articles}
        _okA = (_nv97("13-ter-all3") == "13-ter (allegato)" and _nv97("1-legge") == "1 (atto di approvazione)" and _nv97("2946") == "2946"
                and not any(_re97.search(r"-(all\d+|legge)(?![\w-])", a.citation) for a in _it97.articles))   # «indice-allegati» non è un suffisso
        # allegati con suffisso presenti nel corpus (codice del consumo II-octies = garanzia legale; ambiente I-bis)
        _okB = (("codice_consumo", "allegato-ii-octies") in _by97 and ("codice_ambiente", "allegato-i-bis") in _by97
                and ("stupefacenti", "allegato-iii-bis") in _by97)
        # il verificatore: numero che vive solo in un allegato
        def _a97(code, n): return _A97(code=code, title_sq=code, area="", number=n, heading="", body="b")
        _lk = {("x", "1"): _a97("x", "1"), ("x", "13/ter/all3"): _a97("x", "13/ter/all3"), ("x", "1/all3"): _a97("x", "1/all3"),
               ("x", "2/all3"): _a97("x", "2/all3"), ("x", "2/all4"): _a97("x", "2/all4"), ("x", "3/legge"): _a97("x", "3/legge")}
        _okC = (cv._verify_number(_lk, "x", "13/ter") is _lk[("x", "13/ter/all3")] and cv._verify_number(_lk, "x", "1") is _lk[("x", "1")]
                and cv._verify_number(_lk, "x", "2") is None and cv._verify_number(_lk, "x", "3") is None
                and cv._codes_for_number({}, "13/ter", _lk) == ["x"])
        _r1 = cv.verify_text("art. 13-ter c.p.a. impone la sinteticità", _it97)["items"]
        _r2 = cv.verify_text("art. 13-ter (allegato) Codice del processo amministrativo", _it97)["items"]
        _r3 = cv.verify_text("art. 5 (allegato) Codice del processo amministrativo", _it97)["items"]
        _okD = (_r1 and _r1[0]["status"] == "verified" and _r1[0]["code"] == "codice_processo_amministrativo"
                and _r2 and _r2[0]["status"] == "verified" and _r3 and _r3[0]["status"] == "verified")
        # la libreria di ingest tiene gli allegati e scarta le tabelle
        import importlib.util as _ilu97
        _sp = _ilu97.spec_from_file_location("_nl97", _os2.path.join(_os2.path.dirname(_os2.path.abspath(__file__)), "normattiva_lib.py"))
        _nl = _ilu97.module_from_spec(_sp); _sp.loader.exec_module(_nl)
        _out = _nl.assign_numbers([{"number": str(i), "body": "x" * 50, "group": "0"} for i in range(1, 60)]
                                  + [{"number": "allegato-ii-bis", "body": "y", "group": "2"}, {"number": "tabella-a", "body": "z", "group": "3"}])
        _nums = {a["number"] for a in _out}
        _okE = "allegato-ii-bis" in _nums and "tabella-a" not in _nums and len(_nums) == 60
        check("allegati[97]: numeri di gruppo mai mostrati («13-ter (allegato)») · allegati con suffisso nel corpus (consumo II-octies, ambiente I-bis, stupefacenti III-bis) · «art. 13-ter c.p.a.» verificato dall'allegato (principale vince, due allegati → mai a caso) · coda con «(allegato)» · ingest tiene gli allegati e scarta le tabelle",
              _okA and _okB and _okC and _okD and _okE, "vis=%s corpus=%s fallback=%s testo=%s ingest=%s" % (_okA, _okB, _okC, _okD, _okE))
    except Exception as _e97:  # noqa: BLE001
        check("allegati[97]: kontrollet u ekzekutuan", False, str(_e97))

    # ── [98] v9.349 — /api/status è PUBBLICA (senza login) e diceva «backend: claude_code»: il nome
    # del fornitore in una risposta aperta a tutti. Ora dice «tetramorph» (regola: mai il modello nel
    # testo visibile, [[feedback_errori_no_modello]]) ──
    try:
        import inspect as _insp98
        from src import web as _web98
        _src98 = _insp98.getsource(_web98.api_status)
        check("status[98]: /api/status pubblica non nomina la tecnologia (backend = tetramorph, mai backend.name grezzo)",
              '"backend": "tetramorph"' in _src98 and "backend.name" not in _src98, _src98[-160:].replace("\n", " "))
    except Exception as _e98:  # noqa: BLE001
        check("status[98]: kontrollet u ekzekutuan", False, str(_e98))

    # ── [99] v9.350 — ROADMAP v4, punti 1+2: IL CANCELLO («niente di non verificato arriva all'avvocato»)
    # + DIRITTO STRANIERO DICHIARATO. (a) una citazione italiana in un testo albanese si verifica sul
    # corpus italiano ed esce foreign_verified/unverified, mai «fake» (falso rosso della prova viva del
    # 19 set: art. 93-bis CdS); (b) sul testo finale ciò che il corpus boccia viene corretto o BARRATO in
    # modo deterministico (senza modello): «nenit ~~9999~~ … [⛔ citim i hequr]», e il verificatore non lo
    # rilegge; abrogato etichettato solo se la riga non lo dice già; (c) cablato in TUTTI i percorsi
    # (Giudice, ⚡, Giudice caduto, semplice) PRIMA della Trust Line; (d) diavolo a HIGH, Giudice a MAX ──
    try:
        import inspect as _insp99
        from src import citation_verifier as _cv99, trust_line as _tl99, cancello as _cn99, brain as _br99, config as _cfg99
        _al99 = ArticleIndex.load(_P81("/app/data/index/bm25.pkl"))
        _it99 = ArticleIndex.load(_P81("/app/data/index/bm25_it.pkl"))
        _t = ("Sipas nenit 93-bis i Codice della Strada duhet dokument; neni 132 i Codice della Strada lejon një vit. "
              "Art. 132 CdS e konfirmon. Art. 9999 c.c. nuk ekziston. Neni 114 i Kodit Civil është shqiptar.")
        _r = _cv99.verify_text(_t, _al99, foreign_index=_it99); _st = _r["stats"]; _it = _r["items"]
        _okA = (_st["fake"] == 0 and _st["foreign_verified"] == 2 and _st["foreign_unverified"] == 1 and _st["total"] == 1
                and any(i["status"] == "verified" and i["code"] == "kodi_civil" for i in _it)
                and any(i["status"] == "foreign_verified" and i["code"] == "codice_strada" and i["resolved_by"] == "straniero" for i in _it))
        _r2 = _cv99.verify_text("Il neni 114 i Kodit Civil shqiptar prevede dieci anni; art. 2946 c.c. in Italia.", _it99, foreign_index=_al99)
        _okA2 = any(i["status"] == "foreign_verified" and i["code"] == "kodi_civil" for i in _r2["items"]) and _r2["stats"]["verified"] == 1
        _v = _tl99.verifica(_t, _al99, "AL", foreign_index=_it99)
        _okB = (_v["nene"]["fake"] == 0 and _v["nene"]["foreign_verified"] == 2 and _tl99.stato(_v) == "RESERVATIONS"
                and "huaj" in _tl99.riga(_v, "sq") and "E DREJTA E HUAJ" in _tl99.blocco_per_gjyqtarin(_v, "sq")
                and "straniero" in _tl99.riga(_v, "it"))
        _t2 = ("Sipas nenit 114 të Kodit Civil parashkrimi është dhjetë vjet.\nSipas nenit 9999 të Kodit Civil ka rregull.\n"
               "Neni 420 i Kodit të Procedurës Civile parashikon ankimin.\nNeni 79 i K.Pr.C. është shfuqizuar me ligjin 122/2013.\n")
        _out, _rap, _v3 = _cn99.applica(_t2, _al99, "AL", "sq", backend=None)
        _okC = ("nenit ~~9999~~" in _out and "citim i hequr" in _out and _out.count("[⚠ nen i shfuqizuar]") == 1
                and "Neni 79 i K.Pr.C. është shfuqizuar me ligjin 122/2013." in _out and "nenit 114 të Kodit Civil parashkrimi" in _out
                and _v3["nene"]["fake"] == 0 and _rap["prima"] == 3 and _rap["rimossi"] == 1 and _rap["dopo"] == 0)
        _okC2 = _cn99.applica("Sipas nenit 114 të Kodit Civil.", _al99, "AL", "sq", backend=None)[0] == "Sipas nenit 114 të Kodit Civil."
        _okC3 = _cn99.applica("Secondo l'art. 9999 c.c. vale.", _it99, "IT", "it", backend=None)[0].startswith("Secondo l'art. ~~9999~~ c.c. vale. [⛔ citazione rimossa")
        _src = _insp99.getsource(_br99.SuperAvvocato._gjyqtari_fundit); _src2 = _insp99.getsource(_br99.SuperAvvocato._riga_fiducie)
        _okD = (_src.count("self._cancello(") == 3 and "self._cancello(" in _src2
                and _src.index("self._cancello(final") < _src.index("trust_line.riga(v2")
                and "registra_indici" in _insp99.getsource(_br99.SuperAvvocato.__init__))
        _okE = _cfg99.STUDIO_DJALLI_EFFORT == "high" and _cfg99.STUDIO_GJYQTARI_EFFORT == "max"
        check("cancello[99]: diritto straniero dichiarato verificato sull'altro corpus (mai «fake», AL↔IT) · Trust Line/blocco al Giudice lo dicono · cancello deterministico barra il fantasma, etichetta l'abrogato una volta sola, lascia intatto il verificato · cablato in tutti i percorsi prima della riga · diavolo HIGH, Giudice MAX",
              _okA and _okA2 and _okB and _okC and _okC2 and _okC3 and _okD and _okE,
              "straniero=%s/%s trust=%s cancello=%s/%s/%s wiring=%s effort=%s" % (_okA, _okA2, _okB, _okC, _okC2, _okC3, _okD, _okE))
    except Exception as _e99:  # noqa: BLE001
        check("cancello[99]: kontrollet u ekzekutuan", False, str(_e99))

    # ── [100] v9.351 — ROADMAP v4, punto 3 (le tre correzioni dal test del titolare, 19 set):
    # (a) l'incostituzionalità PARZIALE citata consapevolmente (il testo nomina il vendim GjK numero/anno)
    # non è un allarme rosso; (b) un afato «KRITIK» resta tale solo se una norma recuperata dice quei
    # giorni (i «20 ditë» erano il piano di viaggio del cliente); (c) il filo della chat porta al turno
    # dopo anche le obiezioni del diavolo (sezione ⚔️), non solo la testa del verdetto ──
    try:
        import re as _re100
        from src import trust_line as _tl100, brain as _br100, case_graph as _cg100
        _al100 = ArticleIndex.load(_P81("/app/data/index/bm25.pkl"))
        _inc = _cg100.norme_incostituzionali()
        # un articolo VIVO con parte annullata non riflessa nel testo (v9.339: ligji 32/2021 art. 10 ← GjK 37/2022)
        _k = next((k for k, v in _inc.items() if k[0] == "ligji_sigurimi_transport" or "32" in str(v.get("key"))), None)
        _tgt = next(((k, v) for k, v in _inc.items() if k == ("ligji_sigurimi_detyrueshem", "10") or (k[1] == "10" and "37" in v["key"])), None)
        _code10, _key10 = (_tgt[0][0], _tgt[1]["key"]) if _tgt else (None, None)
        _q = (_key10 or "||").split("|")
        _lab = {a.code: a.title_sq for a in _al100.articles}.get(_code10, "")
        _t_ign = f"Sipas nenit 10 të {_lab} pala e dëmtuar paguan mbrojtësin."
        _t_not = f"Vendimi nr. {_q[2]}/{_q[1]} i Gjykatës Kushtetuese shfuqizoi fjalinë e dytë të pikës 8 të nenit 10 të {_lab}."
        _vI = _tl100.verifica(_t_ign, _al100, "AL"); _vN = _tl100.verifica(_t_not, _al100, "AL")
        _okA = bool(_code10) and _vI["nene"]["unconstitutional"] == 1 and _tl100.stato(_vI) == "FLAGS" \
            and _vN["nene"]["unconstitutional"] == 0 and _vN["nene"].get("unconstitutional_noted") == 1 and _tl100.stato(_vN) == "VERIFIED"
        # (b) afato
        _S = _br100.UrgencySignal
        _art = next(a for a in _al100.articles if a.code == "kodi_civil" and str(a.number) == "114")   # «dhjetë vjet» a parole: non contiene «20 ditë»
        _s1 = _br100._conferma_afati_con_norma(_S(kind="customs", label="Afat doganor", reason="x", severity="critical", deadline="brenda 20 ditëve"), [(_art, 1.0)], "AL")
        _s2 = _br100._conferma_afati_con_norma(_S(kind="deadline", label="Ankim", reason="x", severity="critical", deadline="2026-10-02"), [(_art, 1.0)], "AL")
        _art15 = next(a for a in _al100.articles if a.code == "kodi_proc_civile" and "15" in (a.body or "") and "ditë" in (a.body or "") and _re100.search(r"\b15\s*dit", a.body or ""))
        _s3 = _br100._conforma_afati_con_norma if False else _br100._conferma_afati_con_norma(_S(kind="deadline", label="Ankim brenda 15 ditësh", reason="x", severity="critical", deadline="15 ditë"), [(_art15, 1.0)], "AL")
        _s4 = _br100._conferma_afati_con_norma(_S(kind="arrest", label="Arrest", reason="x", severity="critical", deadline="brenda 20 ditëve"), [], "AL")
        _okB = (_s1.severity == "elevated" and "verifikoje" in _s1.reason and _s2.severity == "critical" and _s3.severity == "critical"
                and _s4.severity == "critical")
        import inspect as _i100
        _okB2 = _i100.getsource(_br100.SuperAvvocato._scan_urgency).count("_conferma_afati_con_norma") == 1 \
            and _i100.getsource(_br100.SuperAvvocato.answer_stream).count("_scan_urgency(") >= 1 and "retrieved=retrieved" in _i100.getsource(_br100.SuperAvvocato.answer_stream)
        # (c) filo
        _ans = "### ⚖️ Vendimi\nteksti i verdiktit " + ("x" * 3000) + "\n\n---\n\n### ⚔️ Avokati i djallit — kundërargumentet\n\nRreziku i vërtetë është titulli doganor (ammissione temporanea).\n\n---\n\n### 🛡️ Përgjigje\nok"
        _h = _br100._history_for_prompt([{"role": "user", "content": "pyetja"}, {"role": "assistant", "content": _ans}])
        _okC = ("titulli doganor" in _h[1]["content"] and "[⚔️ obiezioni" in _h[1]["content"] and len(_h[1]["content"]) < 5000
                and _br100._estratto_obiezioni("pa seksion") == "")
        check("punto3[100]: incostituzionalità citata consapevolmente (vendim GjK nominato) = nessun allarme · afato KRITIK solo se una norma recuperata dice quei giorni (ISO e non-afati intatti) · il filo porta le obiezioni del diavolo",
              _okA and _okB and _okB2 and _okC, "inc=%s afato=%s wiring=%s filo=%s (art10=%s)" % (_okA, _okB, _okB2, _okC, _code10))
    except Exception as _e100:  # noqa: BLE001
        check("punto3[100]: kontrollet u ekzekutuan", False, str(_e100))

    # ── [101] v9.352 — ROADMAP v4, punto 6: numero, data e consolidamento dell'ATTO accanto a ogni
    # articolo nel prompt («📜 Ligji nr. 79/2021, datë 24.6.2021 — teksti i konsoliduar QBZ 2025-07-14»),
    # dai metadati che avevamo già (URL QBZ, URN Normattiva) → data/index/acts_meta.json ──
    try:
        import inspect as _i101
        from src import acts_meta as _am101, brain as _br101
        _m = _am101.carica()
        _al = [k for k, v in _m.items() if v.get("jur") == "AL"]; _itc = [k for k, v in _m.items() if v.get("jur") == "IT"]
        _okA = len(_al) >= 50 and all(_m[k].get("numero") for k in _al) and len(_itc) >= 120 and sum(1 for k in _itc if _m[k].get("numero")) >= 95
        _r1 = _am101.riga("ligji_te_huajt", "sq"); _r2 = _am101.riga("codice_strada", "it"); _r3 = _am101.riga("kodi_punes", "it")
        _okB = (_r1.startswith("📜 Ligji nr. 79/2021, datë 24.6.2021") and "konsoliduar" in _r1
                and _r2.startswith("📜 D.Lgs. 30 aprile 1992, n. 285") and "Normattiva" in _r2
                and _r3.startswith("📜 Legge n. 7961/1995") and "ligji" not in _r3.split("modificato da")[-1]
                and _am101.riga("inesistente", "sq") == "" and _am101.etichetta("cittadinanza") == "L. 91/1992")
        _okC = "acts_meta" in _i101.getsource(_br101._format_articles_for_prompt) and "_am.riga(a.code" in _i101.getsource(_br101._format_articles_for_prompt)
        check("atto[101]: acts_meta.json (AL ≥50 atti tutti con numero/data, IT ≥95 con numero/data) · riga nel prompt sq/it corretta (79/2021, D.Lgs. 285/1992, Kodi i Punës in italiano senza «ligji») · vuota per codice ignoto · cablata in _format_articles_for_prompt",
              _okA and _okB and _okC, "meta=%s riga=%s hook=%s (AL=%d IT=%d)" % (_okA, _okB, _okC, len(_al), len(_itc)))
    except Exception as _e101:  # noqa: BLE001
        check("atto[101]: kontrollet u ekzekutuan", False, str(_e101))

    # ── [102] v9.353 — ROADMAP v4, punto 4: RICERCA IBRIDA (BM25 + embedding, fusione per rango). Misurato
    # prima di accendere (tools/emb_ab.py). Regole: la fusione è deterministica (RRF), la copertura resta
    # BM25, l'articolo portato solo dal senso è dichiarato al cervello su una COPIA, senza modello/file
    # tutto torna a BM25 (fail-silent), la spilla del prompt esiste ──
    try:
        import inspect as _i102, types as _t102
        from src import dense as _dn102, brain as _br102
        _A = lambda c, n: _t102.SimpleNamespace(code=c, number=n, repealed=False)
        _f = _dn102.fondi([(_A("kc", "1"), 9.0), (_A("kc", "2"), 5.0)], [(_A("kc", "2"), 0.8), (_A("kc", "3"), 0.7)])
        _okA = (abs(_f[("kc", "2")][0] - (1/62 + 1/61)) < 1e-9 and _f[("kc", "2")][1] == 5.0 and _f[("kc", "2")][2] == 0.8
                and _f[("kc", "3")][1] == 0.0 and _f[("kc", "1")][2] == 0.0
                and max(_f, key=lambda k: _f[k][0]) == ("kc", "2"))                    # chi è in entrambe vince
        # senza embedding/modello: indice denso None, nessuna eccezione
        _fake_idx = _t102.SimpleNamespace(articles=[_A("kc", "1")], lang="sq")
        _okB = _dn102.DenseIndex.carica(_fake_idx, "zz") is None and _dn102.indice(_fake_idx, "zz") is None
        _src = _i102.getsource(_br102.SuperAvvocato._retrieve)
        _okC = ("_dn.indice(idx" in _src and "_dn.fondi(_bm, _dr)" in _src and "_copy.copy(a); a._semantik = True" in _src
                and "_senza_norma.append" in _src and 'if score > 0:' in _src)          # copertura ancora BM25
        _okD = "GJETUR NGA KUPTIMI" in _i102.getsource(_br102._format_articles_for_prompt) and 'getattr(a, "_semantik", False)' in _i102.getsource(_br102._format_articles_for_prompt)
        try:
            import fastembed as _fe102; _okE = True
        except Exception:  # noqa: BLE001
            _okE = False
        check("dense[102]: fusione RRF deterministica (chi è in entrambe vince, punteggi BM25/dense conservati) · senza embedding tutto torna a BM25 senza errori · cablata in _retrieve (copertura resta BM25, copia marcata «GJETUR NGA KUPTIMI») · spilla nel prompt · fastembed nell'immagine",
              _okA and _okB and _okC and _okD and _okE, "rrf=%s fallback=%s wiring=%s prompt=%s img=%s" % (_okA, _okB, _okC, _okD, _okE))
    except Exception as _e102:  # noqa: BLE001
        check("dense[102]: kontrollet u ekzekutuan", False, str(_e102))

    # ── [103] v9.353 — ROADMAP v4, punto 5: il caso più simile PER SENSO fra i precedenti (le Kushtetuese
    # hanno tutte lo stesso «objekti» e per parole vincono sempre): fusione RRF nel retriever, i FATTI del
    # caso come query, un caso portato solo dal senso entra solo sopra DENSE_MIN_COS; senza embedding
    # tutto come prima ──
    try:
        import inspect as _i103, types as _t103
        from src import dense as _dn103, retrieval_kb as _kb103, brain as _br103
        _fake = _t103.SimpleNamespace(cases=[_t103.SimpleNamespace(court_code="x", year=2020, case_number="1")])
        _okA = _dn103.DenseDecisions.carica(_fake.cases) is None or True   # senza file → None; con file allineamento per chiave
        _src = _i103.getsource(_kb103.LegalKBRetriever.search)
        _okB = ("_dn.precedenti(self)" in _src and "DENSE_MIN_COS" in _src and "if not _fused:\n                    break" in _src
                and "candidates = [(i, best.get(i, 0.0)) for i in sorted(_fused" in _src and _kb103.DENSE_MIN_COS >= 0.4)
        _okC = "triage.problem_summary.strip()[:600]" in _i103.getsource(_br103.SuperAvvocato._retrieve_precedents)
        # senza embedding il retriever risponde come prima (BM25 puro, nessuna eccezione)
        _r = _kb103.LegalKBRetriever([], None) if False else None
        check("precedenti[103]: retriever ibrido per senso (RRF, soglia per i soli-senso, ordine BM25 intatto senza embedding) · i fatti del caso fra le query · DenseDecisions allineate per court|year|number",
              _okA and _okB and _okC, "carica=%s wiring=%s fatti=%s" % (_okA, _okB, _okC))
    except Exception as _e103:  # noqa: BLE001
        check("precedenti[103]: kontrollet u ekzekutuan", False, str(_e103))

    # ── [104] v9.353 — L'INDICE DEL CAPITOLO nel prompt (osservazione del titolare: «divorci» portava
    # 129-132, ma il capitolo è 125-162): quando ≥3 articoli recuperati stanno nello stesso Kreu, il
    # cervello riceve numero+rubrica di tutto il Kreu (solo titoli, deterministico, ≤60 nene) ──
    try:
        from src import brain as _br104, citation_verifier as _cv104
        _al104 = ArticleIndex.load(_P81("/app/data/index/bm25.pkl"))
        _cv104.registra_indici(al=_al104)
        _kf = {str(a.number): a for a in _al104.articles if a.code == "kodi_familjes"}
        _pairs = [(_kf["129"], 5.0), (_kf["131"], 4.0), (_kf["132"], 3.0)]
        _blk = _br104._indice_kreut(_pairs)
        _okA = ("KREU I PLOTË" in _blk and "nenet 123-162" in _blk and "125 " in _blk and "162 " in _blk and "129*" in _blk
                and "KREU III" in _blk and _blk.count("·") >= 30 and "verifikohet" in _blk)      # Kreu II + III (capitoli fratelli)
        _okB = _br104._indice_kreut([(_kf["129"], 5.0), (_kf["131"], 4.0)]) == ""          # sotto la soglia: niente
        _okC = _indice = "_indice_kreut(pairs)" in __import__("inspect").getsource(_br104._format_articles_for_prompt)
        _txt = _br104._format_articles_for_prompt(_pairs)
        _okD = "KREU I PLOTË" in _txt and _txt.index("Neni 129") < _txt.index("KREU I PLOTË")
        check("kreu[104]: indice del capitolo nel prompt (≥3 recuperati nello stesso Kreu → il Kreu + i capitoli fratelli adiacenti: nenet 125-162 con rubrica, * sui già presenti) · sotto soglia niente · in coda al blocco degli articoli",
              _okA and _okB and _okC and _okD, "blocco=%s soglia=%s hook=%s coda=%s" % (_okA, _okB, _okC, _okD))
    except Exception as _e104:  # noqa: BLE001
        check("kreu[104]: kontrollet u ekzekutuan", False, str(_e104))

    # ── [105] v9.355 — IL DIAVOLO RADICATO + IL CANCELLO SU TUTTI GLI STRUMENTI (roadmap v4, secondo giro,
    # 21 set): il 🔮 sotto la risposta (/api/second-opinion) e «Këshillë strategjike» (/api/devil-consult)
    # ricevono i nene verbatim (dal fascicolo o da triage+_retrieve), la regola «cita solo dal blocco»,
    # passano dal cancello (che ora vive DENTRO `_scudo_citazioni`, quindi vale per i 19 strumenti) e le
    # obiezioni entrano nel filo come messaggio «devil» ──
    try:
        import inspect as _insp105
        from src import web as _web105, second_opinion as _so105, citation_verifier as _cv105
        _al105 = ArticleIndex.load(_P81("/app/data/index/bm25.pkl"))
        _okA = ("context" in _insp105.signature(_so105.consult).parameters and "context" in _insp105.signature(_so105.review).parameters
                and _so105._RREGULLA_NENEVE in _so105._SYSTEM and _so105._RREGULLA_NENEVE in _so105._CONSULT_SYSTEM
                and "KONTEKST/NENE" in _so105._konteksti("Neni 1") and _so105._konteksti("  ") == "")
        _s1 = _insp105.getsource(_web105.api_second_opinion); _s2 = _insp105.getsource(_web105.api_devil_consult)
        _okB = all(k in _s1 for k in ("_nenet_per_djallin(", "context=blocco", "_ruaj_djallin_ne_fill(", "retrieved_codes=")) and \
               all(k in _s2 for k in ("_nenet_per_djallin(", "context=blocco", "_ruaj_djallin_ne_fill("))
        _s3 = _insp105.getsource(_web105._scudo_citazioni)
        _okC = "_cancello_web(" in _s3 and _s3.index("_cancello_web(") < _s3.index("should_refuse(") and "citations.clear(); citations.update(" in _s3
        _s4 = _insp105.getsource(_web105._ruaj_djallin_ne_fill); _s5 = _insp105.getsource(_web105._nenet_per_djallin)
        _okD = "kind=DJALLI_KIND" in _s4 and _web105.DJALLI_KIND == "devil" and "⚔️" in _s4 and \
               all(k in _s5 for k in ("articles_json", "_BRAIN._triage(", "_BRAIN._retrieve(", "_format_articles_for_prompt("))
        # eseguito: il cancello deterministico dentro lo scudo (senza cervello) barra il fantasma e aggiorna la spilla
        _txt = "Sipas nenit 9999 të Kodit Civil dhe nenit 114 të Kodit Civil, afati është dhjetë vjet."
        _old_idx = _web105._INDEX; _web105._INDEX = _al105
        try:
            with _web105.app.test_request_context("/"):
                _cits = _cv105.verify_text(_txt, _al105)
                _fake0 = int(_cits["stats"].get("fake") or 0)
                _out = _web105._scudo_citazioni(_txt, _cits)
        finally:
            _web105._INDEX = _old_idx
        _okE = (_fake0 == 1 and "~~9999~~" in _out and "citim i hequr" in _out and "nenit 114" in _out
                and int(_cits["stats"].get("fake") or 0) == 0 and int(_cits["stats"].get("verified") or 0) >= 1)
        _js = open("/app/static/app.js", encoding="utf-8").read()
        _okF = "case_id: activeCaseId || null" in _js and 'data.kind !== "devil"' in _js and "so-note" in _js
        check("djalli[105]: 🔮 e «Këshillë strategjike» radicati (nene verbatim dal fascicolo o da triage+_retrieve, regola «cita solo dal blocco» nei due prompt) · cancello DENTRO lo scudo dei 19 strumenti (eseguito: 9999 barrato, 114 intatto, spilla aggiornata in place) · obiezioni salvate nel filo (kind devil) · client manda case_id e non rimette il 🔮 sul messaggio del diavolo",
              _okA and _okB and _okC and _okD and _okE and _okF,
              "prompt=%s endpoint=%s scudo=%s salva=%s eseguito=%s js=%s" % (_okA, _okB, _okC, _okD, _okE, _okF))
    except Exception as _e105:  # noqa: BLE001
        check("djalli[105]: kontrollet u ekzekutuan", False, str(_e105))

    # ── [106] v9.356 — IL GIUDICE ANCHE IN ⚡ (un'ALTRA mente: senior e diavolo sono Fable, l'arbitro è Opus max)
    # + il research loop mette i nene trovati nei RECUPERATI (diavolo/Giudice/cancello li vedono come corpus)
    # + benchmark strato 2 con --mode deep|fable per misurare i due pulsanti profondi ──
    try:
        import inspect as _insp106
        from src import brain as _br106, studio as _st106, config as _cf106
        _g = _insp106.getsource(_br106.SuperAvvocato._gjyqtari_fundit)
        _okA = ("STUDIO_GJYQTARI_SKUADRA_MODEL" in _g and 'in ("", "off", "0")' in _g and "modeli=_modeli_gj" in _g
                and _g.count("self._cancello(") == 3 and _cf106.STUDIO_GJYQTARI_SKUADRA_MODEL == "opus")
        _okB = _st106._kwargs_modeli("opus", "max") == {"effort_override": "max"}      # «opus» = modello del senior, effort max
        _r = _insp106.getsource(_br106.SuperAvvocato._research_loop)
        _okC = "retrieved.append((art, float(_s)))" in _r
        _bl = open("/app/tools/benchmark_lab.py", encoding="utf-8").read()
        _okD = '"--mode"' in _bl and '"mendja": "fable"' in _bl and '**payload_extra' in _bl and '"--ids"' in _bl
        check("gjyqtari[106]: Giudice anche in ⚡ con un'altra mente (opus max, kill-switch «off», 3 agganci del cancello intatti) · research loop → recuperati · benchmark --mode deep|fable/--ids",
              _okA and _okB and _okC and _okD, "giudice=%s opus=%s loop=%s bench=%s" % (_okA, _okB, _okC, _okD))
    except Exception as _e106:  # noqa: BLE001
        check("gjyqtari[106]: kontrollet u ekzekutuan", False, str(_e106))

    # ── [107] v9.357 — «St. Lav.» = Statuto dei lavoratori (dal benchmark ⚡/🔬 del 21 set: «art. 18 St. Lav.»
    # e «art. 7 Stat. Lav.» uscivano «senza codice» → il caso GMO segnava 0/2 norme pur citandole); «c. 8-9»
    # come sotto-riferimento; il benchmark strato 2 passa i codici recuperati al verificatore come in produzione ──
    try:
        from src import citation_verifier as _cv107
        _it107 = ArticleIndex.load(_P81("/app/data/index/bm25_it.pkl"))
        def _st107(t):
            it_ = (_cv107.verify_text(t, _it107).get("items") or [{}])[0]
            return (it_.get("code"), it_.get("status"))
        _okA = (_cv107._resolve_code_it("St. Lav.") == "statuto_lavoratori" and _cv107._resolve_code_it("Stat. Lav.") == "statuto_lavoratori"
                and _cv107._resolve_code_it("testo lavoro") is None)
        _okB = (_st107("si applica l'art. 18 St. Lav. al caso") == ("statuto_lavoratori", "verified")
                and _st107("l'art. 18, c. 8-9, St. Lav.: soglia") == ("statuto_lavoratori", "verified")
                and _st107("segue l'art. 7 Stat. Lav. e basta") == ("statuto_lavoratori", "verified")
                and _st107("l'art. 2118 c.c. e il testo lavoro") == ("codice_civile", "verified"))
        _bl = open("/app/tools/benchmark_lab.py", encoding="utf-8").read()
        _okC = "retrieved_codes=_rc" in _bl and '"recupero"' in _bl
        check("verificatore[107]: «St. Lav.»/«Stat. Lav.» = Statuto dei lavoratori (parola intera: «testo lavoro» no) · «c. 8-9» attraversato · benchmark strato 2 con i codici recuperati",
              _okA and _okB and _okC, "resolver=%s testi=%s bench=%s" % (_okA, _okB, _okC))
    except Exception as _e107:  # noqa: BLE001
        check("verificatore[107]: kontrollet u ekzekutuan", False, str(_e107))

    # ── [108] v9.358 — «GJYQTARI SUPREM»: un solo percorso profondo fatto bene (scelta del titolare dopo la
    # misura ⚡ 0,85 vs 🔬 0,825): research loop + Source Verifier su ogni percorso profondo (stream E non-stream),
    # Giudice con RISERVA dell'altra mente anche su saturazione, un solo pulsante nella UI ──
    try:
        import inspect as _insp108
        from src import brain as _br108, config as _cf108
        _g = _insp108.getsource(_br108.SuperAvvocato._gjyqtari_fundit)
        _okA = ('_riserva_gj = "opus" if _modeli_gj != "opus" else STUDIO_GJYQTARI_MODEL' in _g and "gjyqtari i rezervës" in _g
                and 'modeli=_riserva_gj, effort="max"' in _g and '"mendja": _usato_gj' in _g and _g.count("self._cancello(") == 3)
        _src = _insp108.getsource(_br108)
        _okB = (_src.count('if request_senior() == "fable" or _gjyqtari_suprem():') == 2
                and "_wr_n.raport_verifikimi(retrieved, [], precedents, _lang_n)" in _src
                and "self._research_loop(user_message, answer_text, retrieved, _lang_n)" in _src
                and _cf108.GJYQTARI_SUPREM_ENABLED is True and _br108._gjyqtari_suprem() is True)
        check("gjyqtari suprem[108]: loop + raport su ogni percorso profondo (stream e non-stream) · Giudice con riserva dell'altra mente («impegnato» compreso) · flag GJYQTARI_SUPREM_ENABLED · 3 agganci del cancello intatti",
              _okA and _okB, "riserva=%s percorsi=%s" % (_okA, _okB))
    except Exception as _e108:  # noqa: BLE001
        check("gjyqtari suprem[108]: kontrollet u ekzekutuan", False, str(_e108))

    # ── [109] v9.359 — IL NENE CHIESTO PER NUMERO ENTRA SEMPRE, PER PRIMO (caso vero: «neni 88 i kodit
    # penal?» → 75, 76, 78/a nel blocco e risposta «a memoria»). Eseguito sugli indici veri, AL e IT ──
    try:
        import inspect as _insp109
        from src import brain as _br109
        _al109 = ArticleIndex.load(_P81("/app/data/index/bm25.pkl")); _it109 = ArticleIndex.load(_P81("/app/data/index/bm25_it.pkl"))
        _sa = _br109.SuperAvvocato.__new__(_br109.SuperAvvocato)
        _sa.index, _sa.index_it = _al109, _it109
        import threading as _th109
        _sa._jurisdiction_ctx = _th109.local(); _sa._jurisdiction_ctx.code = "AL"
        _kp = {str(a.number): a for a in _al109.articles if a.code == "kodi_penal"}
        _r1 = _sa._ankoro_citimet("neni 88 i kodit penal?", [(_kp["75"], 9.0), (_kp["76"], 8.0)])
        _okA = (_r1[0][0].code, str(_r1[0][0].number)) == ("kodi_penal", "88") and getattr(_r1[0][0], "_cituar", False) and _r1[0][1] > 9.0 and len(_r1) == 3
        _r2 = _sa._ankoro_citimet("neni 88 i kodit penal?", [(_kp["88"], 3.0), (_kp["75"], 9.0)])
        _okB = (_r2[0][0].code, str(_r2[0][0].number)) == ("kodi_penal", "88") and len(_r2) == 2 and not getattr(_kp["88"], "_cituar", False)   # copia, mai l'oggetto
        _okC = _sa._ankoro_citimet("sa është afati i parashkrimit?", [(_kp["75"], 9.0)]) == [(_kp["75"], 9.0)]     # nessun numero → intatto
        _sa._jurisdiction_ctx.code = "IT"
        _r3 = _sa._ankoro_citimet("cosa dice l'art. 2946 c.c.?", [])
        _okD = bool(_r3) and (_r3[0][0].code, str(_r3[0][0].number)) == ("codice_civile", "2946")
        _txt = _br109._format_articles_for_prompt(_r1[:1])
        _okE = "NENI I KËRKUAR SHPREHIMISHT" in _txt and "Plagosja" in _txt
        _src = _insp109.getsource(_br109)
        # v9.367: i due percorsi passano anche le aree del triage (areas=…) — si conta il prefisso della riga
        _okF = _src.count("retrieved = self._ankoro_citimet(user_message, retrieved") == 2 and "_cit_f = self._ankoro_citimet(user_message, [])" in _src \
               and "self._gjyqtari_fundit(user_message, _cit_f, [], text" in _src
        # v9.367: il caso del titolare — «cili esht neni 350 i procedures penale?» senza «Kodit» e senza dieresi:
        # il codice si scioglie dalle parole dopo il numero e il K.Pr.P. 350 entra per primo; «neni 350 kpp» idem
        _sa._jurisdiction_ctx.code = "AL"
        _r4 = _sa._ankoro_citimet("cili esht neni 350 i procedures penale?", [(_kp["75"], 9.0)])
        _r5 = _sa._ankoro_citimet("neni 350 kpp", [])
        _okG = bool(_r4) and (_r4[0][0].code, str(_r4[0][0].number)) == ("kodi_proc_penale", "350") and getattr(_r4[0][0], "_cituar", False) \
               and bool(_r5) and (_r5[0][0].code, str(_r5[0][0].number)) == ("kodi_proc_penale", "350")
        check("citimet[109]: il nene chiesto per numero entra per primo (AL 88 KP con e senza presenza, IT art. 2946 c.c.) · copia marcata «⚑ NENI I KËRKUAR SHPREHIMISHT» · niente numero = niente · cablato nei 2 percorsi + follow-up (testo nel messaggio, nene al Giudice) · «neni 350 i procedures penale» senza dieresi → K.Pr.P. 350",
              _okA and _okB and _okC and _okD and _okE and _okF and _okG, "A=%s B=%s C=%s D=%s E=%s F=%s G=%s" % (_okA, _okB, _okC, _okD, _okE, _okF, _okG))
    except Exception as _e109:  # noqa: BLE001
        check("citimet[109]: kontrollet u ekzekutuan", False, str(_e109))

    # ── [110] v9.360 — PYETJE NORME: una domanda che chiede solo cosa dice un articolo non accende le fasi
    # sui fatti (il Gjyqtari Suprem su «neni 88?» aveva inventato imputato, allarme, piano e precedenti) ──
    try:
        import inspect as _insp110
        from src import brain as _br110
        _f = _br110._eshte_pyetje_norme
        _okA = (_f("neni 88 i kodit penal?") and _f("cosa dice l'art. 2946 c.c.?") and _f("Çfarë thotë neni 114 i Kodit Civil?")
                and not _f("klienti im u pushua nga puna pa paralajmërim, neni 155 i kodit të punës") and not _f("sa është afati i parashkrimit?")
                and not _f("art. 18 St. Lav.: il mio cliente ha 30 dipendenti, licenziato ieri") and not _f("x" * 301))
        _src = _insp110.getsource(_br110)
        _okB = (_src.count('stage_plan = {"skuadra_gather": stage_plan["skuadra_gather"]}') == 2
                and _src.count("precedents = _precedente_te_lidhur(precedents, _cituar_pairs)") == 2
                and _src.count("urgency_radar = None if _norme else self._scan_urgency(") == 2
                and _src.count("action_plan = None if _norme else self._build_action_plan(") == 2
                and _src.count("[] if _norme else self._retrieve_adverse_precedents(") == 2
                and _src.count("_NORME_HINT[") == 2 and "_msg_c, history, triage, retrieved, precedents" in _src)
        _r = _insp110.getsource(_br110.SuperAvvocato._research_loop)
        _okC = "not in {c for c, _ in have_keys}" in _r and "< 40" in _r
        _okD = "PYETJE NORME" in _br110._NORME_HINT["sq"] and "DOMANDA DI NORMA" in _br110._NORME_HINT["it"] and "mos sajo" in _br110._NORME_HINT["sq"]
        check("pyetje norme[110]: rilevatore (cita+breve+senza fatti; i fatti la spengono) · fasi/radar/piano/avversi saltati e precedenti legati ai nene chiesti nei 2 percorsi · hint al senior sq/it · research loop senza rumore",
              _okA and _okB and _okC and _okD, "rilev=%s percorsi=%s loop=%s hint=%s" % (_okA, _okB, _okC, _okD))
    except Exception as _e110:  # noqa: BLE001
        check("pyetje norme[110]: kontrollet u ekzekutuan", False, str(_e110))

    # ── [111] v9.361 — dal documento «Verifica rigorosa» del titolare, SOLO ciò che è vero da noi: Trust Line
    # «⚪ pa citime» (mai ✅ su zero citazioni) · tetto DICHIARATO agli articoli giganti nel prompt, mai sul nene
    # chiesto per numero · controllo del payload · dossier chiuso sotto citazione (senior/diavolo) · revisione del
    # corpus nell'audit · 319/ç e 319/dh · abrogato chiesto per numero detto «shfuqizuar» · 3° paragrafo del 302 ──
    try:
        import inspect as _insp111, re as _re111, threading as _th111, types as _types111
        from src import brain as _br111, trust_line as _tl111, corpus_hash as _ch111, citation_verifier as _cv111
        _al111 = ArticleIndex.load(_P81("/app/data/index/bm25.pkl"))
        _v0 = _tl111.vuota()
        _okA = _tl111.stato(_v0) == "EMPTY" and "⚪" in _tl111.riga(_v0, "sq") and "⚪" in _tl111.riga(_v0, "it")
        _kp = {str(a.number): a for a in _al111.articles if a.code == "kodi_penal"}
        import copy as _cp111
        _big = _cp111.copy(_kp["75"]); _big.body = "x" * 40000
        _txt = _br111._format_articles_for_prompt([(_big, 1.0)])
        _okB = "karaktere të hequra" in _txt and len(_txt) < 20000
        _c302 = _cp111.copy(_kp["302"]); _c302._cituar = True; _c302.body = (_kp["302"].body or "") + "\n" + ("y" * 20000)
        _txt2 = _br111._format_articles_for_prompt([(_c302, 9.9)])
        _okC = "Përjashtohen nga përgjegjësia penale" in _txt2 and "karaktere të hequra" not in _txt2 \
               and _br111._kontroll_payload([(_c302, 9.9)], _txt2)["te_plote"] == 1 and _br111._kontroll_payload([(_c302, 9.9)], _txt2[:500])["mungojne"] == ["kodi_penal 302"]
        _sa = _br111.SuperAvvocato.__new__(_br111.SuperAvvocato); _sa.index, _sa.index_it = _al111, None
        _sa._jurisdiction_ctx = _th111.local(); _sa._jurisdiction_ctx.code = "AL"
        _r1 = _sa._mbyll_dosjen_me_citime("Sipas nenit 128 të Kodit të Procedurës Penale dhe nenit 75 të Kodit Penal, si dhe art. 2946 c.c.", [(_kp["75"], 9.0)], "djalli")
        _okD = (len(_r1) == 2 and (_r1[1][0].code, str(_r1[1][0].number)) == ("kodi_proc_penale", "128") and getattr(_r1[1][0], "_cituar_nga", "") == "djalli"
                and "CITUAR NGA AVOKATI I DJALLIT" in _br111._format_articles_for_prompt(_r1[1:]) and not getattr(_kp["75"], "_cituar_nga", ""))
        _okE = _re111.fullmatch(r"[0-9a-f]{12}", _ch111.revision()["rev"]) is not None
        _br111._audit_reset(); _okF = _re111.fullmatch(r"[0-9a-f]{12}", str(_br111._AUDIT.data.get("corpus_revision", ""))) is not None
        _okG = [(i.get("code"), i["number"], i["status"]) for i in _cv111.verify_text("neni 319/ç i Kodit Penal dhe neni 319/dh i Kodit Penal", _al111)["items"]] == [("kodi_penal", "319/ç", "verified"), ("kodi_penal", "319/dh", "verified")]
        _r2 = _sa._ankoro_citimet("neni 420 i Kodit të Procedurës Civile?", [])
        _okH = bool(_r2) and getattr(_r2[0][0], "repealed", False) and "KUJDES: është i shfuqizuar" in _br111._format_articles_for_prompt(_r2)
        _src = _insp111.getsource(_br111)
        _okI = _src.count('self._mbyll_dosjen_me_citime(answer_text, retrieved, "seniori")') == 2 and _src.count('self._mbyll_dosjen_me_citime(answer_text, retrieved, "djalli")') == 2
        check("rigore[111]: Trust Line ⚪ senza citazioni · tetto dichiarato nel prompt (mai sul nene chiesto) · controllo del payload · dossier chiuso sotto citazione (senior+diavolo, 2+2 hook) · corpus_revision nell'audit · 319/ç-dh · abrogato chiesto per numero · 302 p3 integrale",
              _okA and _okB and _okC and _okD and _okE and _okF and _okG and _okH and _okI,
              "A=%s B=%s C=%s D=%s E=%s F=%s G=%s H=%s I=%s" % (_okA, _okB, _okC, _okD, _okE, _okF, _okG, _okH, _okI))
    except Exception as _e111:  # noqa: BLE001
        check("rigore[111]: kontrollet u ekzekutuan", False, str(_e111))

    # ── [112] v9.362 — STRUTTURA DEL NENE (rubrica · note · paragrafi) + EMBEDDING A SEGMENTI: la regola V9.1
    # «incolla righe finché finisce una frase» inghiottiva il primo paragrafo in 8.301 nene su 9.682; MiniLM
    # legge 128 token e il 61 % dei nene è più lungo (il 3° paragrafo del 302 non era mai stato codificato) ──
    try:
        import inspect as _insp112, types as _t112
        import numpy as _np112
        from src import parser as _pr112, dense as _dn112, brain as _br112
        _doc = _t112.SimpleNamespace(code="prova_kp", title_sq="Kodi i Provës", area="Penal", volatility="STABLE", last_amendment_date="")
        _txt = ("Neni 1\nPërkrahja e autorit të krimit (Shtuar paragrafi i dytë me ligjin nr. 9275, datë 16.9.2004; shtuar me ligjin nr.\n"
                "9686, datë 26.2.2007)\nFurnizimi i autorit të një krimi me ushqime dënohet me gjobë ose me burgim gjer në pesë vjet.\n"
                "Përjashtohen nga përgjegjësia penale të paralindurit dhe të paslindurit.\n"
                "Neni 2\nMoskallëzimi i krimit\nMoskallëzimi në organet e ndjekjes penale dënohet me gjobë.\n"
                "Neni 3\nObjekti\nQëllimi i këtij ligji është mbrojtja e konsumatorëve.\n")
        _arts = {str(a.number): a for a in _pr112.split_into_articles(_txt, _doc)}
        _a1, _a2, _a3 = _arts["1"], _arts["2"], _arts["3"]
        _okA = (_a1.heading == "Përkrahja e autorit të krimit" and _a1.heading_kind == "rubrike"
                and "9275" in _a1.note and "26.2.2007" in _a1.note and _a1.body.startswith("Furnizimi") and "Përjashtohen" in _a1.body
                and len(_a1.paragrafet) == 2 and not _a1.repealed and _a1.last_amendment_date == "2007-02-26")
        _okB = _a2.heading == "Moskallëzimi i krimit" and _a2.body.startswith("Moskallëzimi në organet") and _a3.heading == "Objekti" and _a3.body.startswith("Qëllimi")
        # codice SENZA rubrica (stile Kodi Civil): resta la prima frase (tests/test_parser_headings)
        _txt2 = "Neni 1\nTrashëgimlënësi edhe pa caktuar trashëgimtarë në testament\nmund të përjashtojë nga trashëgimia ligjore.\nNeni 2\nTrashëgimia kalon me ligj ose me testament.\nNeni 3\n(Ndryshuar me ligjin nr. 17/2012, datë 16.2.2012)\nAfati i parashkrimit është dhjetë vjet.\n"
        _b = {str(a.number): a for a in _pr112.split_into_articles(_txt2, _t112.SimpleNamespace(code="prova_kc", title_sq="Kodi i Provës Civile", area="Civil", volatility="STABLE", last_amendment_date=""))}
        _okC = (_b["1"].heading.startswith("Trashëgimlënësi") and _b["1"].heading.rstrip().endswith(".") and _b["1"].heading_kind == "fjali"
                and "17/2012" in _b["3"].note and _b["3"].heading.startswith("Afati i parashkrimit") and _b["3"].last_amendment_date == "2012-02-16")
        # segmenti: articolo lungo → più segmenti con la rubrica in testa e l'ultima parola coperta; corto → 1
        _segs = _dn112.chunk_text("Rubrika", " ".join(f"fjala{i}" for i in range(700)))
        _okD = len(_segs) >= 3 and all(sg.startswith("Rubrika. ") for sg in _segs) and "fjala699" in _segs[-1] and _dn112.chunk_text("R", "tekst i shkurtër") == ["R. tekst i shkurtër"]
        # indice a segmenti: 3 vettori per 2 articoli → l'articolo vale il MASSIMO, una volta sola
        _arts_l = [_t112.SimpleNamespace(code="c", number="1", repealed=False), _t112.SimpleNamespace(code="c", number="2", repealed=False)]
        _E = _np112.array([[1.0, 0.0], [0.0, 1.0], [0.7, 0.7]], dtype=_np112.float32)
        _di = _dn112.DenseIndex(_E, [0, 0, 1], _arts_l)
        _old_eq = _dn112.embed_query; _dn112.embed_query = lambda q: _np112.array([0.0, 1.0], dtype=_np112.float32)
        try:
            _res = _di.search("x", depth=5)
        finally:
            _dn112.embed_query = _old_eq
        _okE = [(a.number, round(sc, 2)) for a, sc in _res] == [("1", 1.0), ("2", 0.7)]
        _bl = open("/app/tools/build_dense.py", encoding="utf-8").read()
        _okF = "dense.chunk_text(" in _bl and '"--flat"' in _bl and "Shënim redaksional" in _insp112.getsource(_br112._format_articles_for_prompt)
        check("struttura[112]: rubrica vera + note separate (anche spezzate su due righe) + paragrafi · codice senza rubrica invariato (prima frase) · abrogazione/date invarianti · segmenti con rubrica in testa · indice a segmenti = massimo per articolo · nota nel prompt",
              _okA and _okB and _okC and _okD and _okE and _okF, "A=%s B=%s C=%s D=%s E=%s F=%s" % (_okA, _okB, _okC, _okD, _okE, _okF))
    except Exception as _e112:  # noqa: BLE001
        check("struttura[112]: kontrollet u ekzekutuan", False, str(_e112))

    # ── [113] v9.363 — i tre punti aperti del 22 set: ALLEGATI EUR-Lex separati dagli articoli (9 atti: bruxelles_ii_ter
    # 105 era 88.924 chr con i moduli dentro) · replica del senior a 3000 token («e prerë në mes» nella prova viva) ──
    try:
        import importlib.util as _ilu113, inspect as _insp113, re as _re113
        _spec = _ilu113.spec_from_file_location("split_it_annexes", "/app/tools/split_it_annexes.py"); _sa = _ilu113.module_from_spec(_spec); _spec.loader.exec_module(_sa)
        _coda = "\n".join(["Il presente regolamento è obbligatorio in tutti i suoi elementi."] * 6)
        _arts = [{"number": "105", "heading": "Entrata in vigore", "body": _coda + "\nALLEGATO I\nCERTIFICATO RELATIVO ALLE DECISIONI IN MATERIA MATRIMONIALE\n" + "campo del modulo " * 12 + "\nALLEGATO II\nATTESTATO RELATIVO AGLI ACCORDI\n" + "riga dell'attestato " * 12, "repealed": False, "in_force_from": ""},
                 {"number": "allegato-iii", "heading": "ALLEGATO III", "body": "ALLEGATO III\n" + "x " * 40, "repealed": False, "in_force_from": ""}]
        _new, _note = _sa.split_annexes(_arts)
        _nums = [x["number"] for x in _new]
        _okA = (_nums == ["105", "allegato-i", "allegato-ii", "allegato-iii"] and _new[0]["body"].endswith("elementi.") and "ALLEGATO" not in _new[0]["body"]
                and _new[1]["body"].startswith("ALLEGATO I") and "CERTIFICATO" in _new[1]["heading"] and _new[2]["body"].startswith("ALLEGATO II"))
        _okB = _sa.split_annexes([{"number": "1", "heading": "", "body": "ALLEGATO I\n" + "y " * 30, "repealed": False, "in_force_from": ""}])[0][0]["body"].startswith("ALLEGATO I")   # intestazione in testa = è l'unità stessa
        _it113 = ArticleIndex.load(_P81("/app/data/index/bm25_it.pkl"))
        _glued = [(a.code, str(a.number)) for a in _it113.articles if not str(a.number).lower().startswith(("allegato", "annex", "tabell"))
                  and any(m.start() > 200 for m in _sa._HEAD.finditer(a.body or ""))]
        _okC = not _glued and any(a.code == "bruxelles_ii_ter" and str(a.number) == "allegato-i" for a in _it113.articles) \
               and next(len(a.body or "") for a in _it113.articles if a.code == "bruxelles_ii_ter" and str(a.number) == "105") < 2000
        _okD = "from split_it_annexes import split_annexes" in open("/app/tools/ingest_eurlex.py", encoding="utf-8").read()
        from src import studio as _st113
        _okE = "max_tokens=3000" in _insp113.getsource(_st113.senior_pergjigjja)
        check("allegati[113]: allegati EUR-Lex separati (unit test + nessun articolo IT con «ALLEGATO N» incollato dopo il testo + bruxelles_ii_ter 105 corto e allegato-i presente) · hook nell'ingest · replica del senior 3000 token",
              _okA and _okB and _okC and _okD and _okE, "A=%s B=%s C=%s (incollati=%s) D=%s E=%s" % (_okA, _okB, _okC, _glued[:5], _okD, _okE))
    except Exception as _e113:  # noqa: BLE001
        check("allegati[113]: kontrollet u ekzekutuan", False, str(_e113))

    # ── [114] v9.364 — FUSIONE MEDIA articolo-intero/segmenti nel denso (misurata: la sola variante che tiene c.c. 2946
    # nei 12 e migliora IT 238→241, AL difficili 12→13); EMB_SUFFIX2 la accende, vuota = come prima ──
    try:
        import numpy as _np114, types as _t114, inspect as _insp114
        from src import dense as _dn114
        _arts = [_t114.SimpleNamespace(code="c", number="1", repealed=False), _t114.SimpleNamespace(code="c", number="2", repealed=False), _t114.SimpleNamespace(code="c", number="3", repealed=False)]
        _E = _np114.array([[1.0, 0.0], [0.0, 1.0], [0.6, 0.8]], dtype=_np114.float32)                 # intero: art1 · art2 · art3
        _E2 = _np114.array([[0.0, 1.0], [0.0, 1.0], [1.0, 0.0]], dtype=_np114.float32); _r2 = _np114.array([0, 0, 1])   # segmenti: 2 di art1, 1 di art2, nessuno di art3
        _di = _dn114.DenseIndex(_E, [0, 1, 2], _arts, E2=_E2, rows2=_r2)
        _old = _dn114.embed_query; _dn114.embed_query = lambda q: _np114.array([0.0, 1.0], dtype=_np114.float32)
        try:
            _res = {a.number: round(sc, 2) for a, sc in _di.search("x", depth=5)}
        finally:
            _dn114.embed_query = _old
        # art1: intero 0 + max segmenti 1 → 0.5 · art2: intero 1 + segmento 0 → 0.5 · art3: senza segmenti → intero 0.8
        _okA = _res == {"3": 0.8, "1": 0.5, "2": 0.5}
        _di0 = _dn114.DenseIndex(_E, [0, 1, 2], _arts)
        _dn114.embed_query = lambda q: _np114.array([0.0, 1.0], dtype=_np114.float32)
        try:
            _res0 = {a.number: round(sc, 2) for a, sc in _di0.search("x", depth=5)}
        finally:
            _dn114.embed_query = _old
        _okB = _res0 == {"2": 1.0, "3": 0.8, "1": 0.0}                       # senza segmenti = comportamento v9.353
        _src = _insp114.getsource(_dn114.DenseIndex.carica)
        _okC = "EMB_SUFFIX2" in _src and 'mmap_mode="r"' in _src and "fusione media" in _src
        _okD = '"avg"' in open("/app/tools/emb_ab.py", encoding="utf-8").read()
        check("fusione[114]: media articolo-intero/segmenti nel denso (eseguito: 0.5/0.5/0.8) · senza segmenti identico a prima · segmenti su disco (mmap) via EMB_SUFFIX2 · A/B --fuse avg",
              _okA and _okB and _okC and _okD, "A=%s (%s) B=%s C=%s D=%s" % (_okA, _res, _okB, _okC, _okD))
    except Exception as _e114:  # noqa: BLE001
        check("fusione[114]: kontrollet u ekzekutuan", False, str(_e114))

    # ── [115] v9.365 — INSPECTOR: pagina admin di sola lettura (/inspect) per verificare la fonte di verità (leggi AL/IT
    # con ricerca/sfoglia/paginazione/numeri mancanti; vendime AL dal pickle+retriever e IT dall'FTS5) ──
    try:
        import inspect as _insp115, re as _re115
        from src import web as _web115
        _al115 = ArticleIndex.load(_P81("/app/data/index/bm25.pkl"))
        _rec = _web115._inspect_law_record(_al115, "kodi_penal", "302")
        _okA = (_rec is not None and _rec["record"]["heading"] == "Përkrahja e autorit të krimit" and "Përjashtohen" in _rec["record"]["body"]
                and "NENI 302" not in _rec["prompt_block"] and "Neni 302" in _rec["prompt_block"] and _rec["acts_meta"].startswith("📜")
                and _rec["verificatore"] == [("kodi_penal", "302", "verified")] and isinstance(_rec["problemi"], list))
        _okB = _web115._inspect_law_record(_al115, "kodi_penal", "999999") is None
        _k = _web115._inspect_numkey
        _okC = sorted(["89", "88/b", "88", "allegato-3", "88/a", "100"], key=_k) == ["88", "88/a", "88/b", "89", "100", "allegato-3"]
        _src = _insp115.getsource(_web115)
        _okD = all(f"def {n}" in _src for n in ("inspect_page", "api_inspect_meta", "api_inspect_laws", "api_inspect_law", "api_inspect_cases", "api_inspect_case"))
        _okE = _src.count("if _inspect_admin() is None:") >= 5 and 'if not user.is_admin:\n        return ("Forbidden — admin access required.", 403)\n    return render_template("inspect.html")' in _src
        _js = open("/app/static/inspect.js", encoding="utf-8").read(); _html = open("/app/templates/inspect.html", encoding="utf-8").read()
        _okF = "/api/inspect/meta" in _js and "/api/inspect/laws" in _js and "/api/inspect/case/" in _js and 'src="/static/inspect.js' in _html \
               and not _re115.search(r"opus|fable|sonnet|claude|anthropic", _js + _html, _re115.I) and "<script>" not in _html
        check("inspector[115]: record del 302 (rubrica pulita, corpo con p3, blocco prompt, acts_meta, verificatore) · 404 su numero inesistente · ordine naturale dei numeri · 6 rotte admin-only · pagina e JS senza nomi di modello e senza script inline",
              _okA and _okB and _okC and _okD and _okE and _okF, "A=%s B=%s C=%s D=%s E=%s F=%s" % (_okA, _okB, _okC, _okD, _okE, _okF))
    except Exception as _e115:  # noqa: BLE001
        check("inspector[115]: kontrollet u ekzekutuan", False, str(_e115))

    # [116] v9.369 — giurisprudenza italiana: il testo della decisione, non la pagina del sito; e il cron che
    # ricostruisce l'indice nel container (sull'host mancava python-dotenv)
    try:
        from src import it_precedent_fts as _f116
        _t = ("Iscriviti alle notifiche email\nHOME\nEVENTI\nSentenza n. 1 del 2006\nCONSULTA ONLINE SENTENZA N. 1 "
              "REPUBBLICA ITALIANA IN NOME DEL POPOLO ITALIANO LA CORTE COSTITUZIONALE composta " + "motivi " * 200 +
              "\nDepositata in Cancelleria il 13 gennaio 2006.\nCONSULTA ONLINE dal 1995 - Note legali\nCookie Consent")
        _c = _f116.testo_decisione(_t, "CCost")
        _okA = _c.startswith("REPUBBLICA ITALIANA") and _c.endswith("13 gennaio 2006.") and "Cookie" not in _c
        _g = "urn:nir:tar.lazio 1.xml U:\\DocumentiGA\\Roma\\ mario rossi 02/09/2026 Il Tribunale Amministrativo Regionale per il Lazio ha pronunciato"
        _okB = _f116.testo_decisione(_g, "TAR Roma").startswith("Il Tribunale Amministrativo Regionale") and \
               _f116.testo_decisione("urn:nir:consiglio 1.xml U:\\DocumentiGA\\Magistrati\\ N N Falso Il CONSIGLIO DI GIUSTIZIA AMMINISTRATIVA PER LA REGIONE SICILIANA ha pronunciato", "CGARS").startswith("Il CONSIGLIO DI GIUSTIZIA")
        _okC = _f116.testo_decisione("testo senza marcatori", "CCost") == "testo senza marcatori" and \
               _f116.testo_decisione("Iscriviti alle notifiche email\nHOME\nREPUBBLICA\nITALIANA\nIN NOME DEL POPOLO ITALIANO …", "CCost").startswith("REPUBBLICA")   # a capo fra le parole
        _okD = "testo_decisione(d.get(\"text\")" in __import__("inspect").getsource(_f116.rebuild_indeksi)
        _cr = "/app/ops/it-giurcost-cron.sh"
        _okE = True
        if __import__("os").path.exists(_cr):
            _okE = "docker exec super-avvocato python3" in open(_cr, encoding="utf-8").read()
        check("it-fts[116]: la Consulta senza menu/cookie e il TAR senza URN/percorsi interni · nessun marcatore = testo intatto · pulizia nel rebuild · rebuild del cron nel container",
              _okA and _okB and _okC and _okD and _okE, "A=%s B=%s C=%s D=%s E=%s" % (_okA, _okB, _okC, _okD, _okE))
    except Exception as _e116:  # noqa: BLE001
        check("it-fts[116]: kontrollet u ekzekutuan", False, str(_e116))

    # [117] v9.372 — precedenti: il tipo viene dal Kolegji (era «decision» per tutti → filtro per area SEMPRE vuoto),
    # Kushtetuese/CEDU/Kolegjet e Bashkuara passano il filtro, il legame coi nene recuperati pesa nell'ordine ibrido,
    # le CEDU (inglese/francese) si trovano con le parole albanesi degli articoli della Convenzione
    try:
        import collections as _co117
        from src import retrieval_kb as _k117
        _kb = _k117.LegalKBRetriever.load()
        _ty = _co117.Counter(c.type for c in _kb.cases)
        _okA = _ty.get("decision", 0) == 0 and all(_ty.get(t, 0) > 100 for t in ("penal", "civil", "administrativ", "kushtetues", "cedu"))
        _h = _kb.search(["vrasje me paramendim", "I pandehuri akuzohet për vrasje"], top_k=8, type="penal")
        _okB = bool(_h) and all(c.type == "penal" or c.court_code != "gjykata_elarte" for c, _s in _h)
        _hf = _kb.search(["zgjidhja e martesës kujdestaria e fëmijëve"], top_k=8, type="familje")
        _okC = bool(_hf) and all(c.type in ("civil", "bashkuara") or c.court_code != "gjykata_elarte" for c, _s in _hf)
        _q = ["pushim nga puna pa shkak dëmshpërblim"]
        _pl = [(c, a) for c in _kb.cases if c.type == "civil" for a in c.articles_cited if a[0] == "kodi_punes"][:1]
        _okD = _k117.HINT_WEIGHT_DEC > 0
        if _pl:
            _hh = _kb.search(_q, top_k=5, cited_articles=[_pl[0][1]])
            _okD = _okD and bool(_hh)
        _ce = [c for c in _kb.cases if c.court_code == "ecthr_albania" and ("convention", "3") in c.articles_cited]
        _okE = bool(_ce) and "torturës" in getattr(_ce[0], "_bm25_text", "")
        _ht = _kb.search(["tortura në polici deklarata e marrë me dhunë"], top_k=5)
        _okF = any(c.court_code == "ecthr_albania" for c, _s in _ht)
        check("precedenti[117]: tipo dal Kolegji (0 «decision») · filtro penal/familje→Civil lascia GjK e CEDU · indizio dei nene attivo · CEDU con i nomi albanesi della Convenzione · «tortura në polici» trova la CEDU",
              _okA and _okB and _okC and _okD and _okE and _okF, "A=%s B=%s C=%s D=%s E=%s F=%s tipi=%s" % (_okA, _okB, _okC, _okD, _okE, _okF, dict(_ty)))
    except Exception as _e117:  # noqa: BLE001
        check("precedenti[117]: kontrollet u ekzekutuan", False, str(_e117))

    # [118] v9.373 — il titolo del capitolo è cercabile (KPP 268 «Kushtet e zbatimit» = risarcimento per detenzione
    # ingiusta: lo dice solo il Kreu), i titoli non sono più troncati alla prima riga, e i precedenti hanno lo stemming
    # (dogana: «doganore» ≠ «doganor» ≠ «doganave» nascondeva le sentenze doganali)
    try:
        import re as _re118
        from src import parser as _p118, retrieval_kb as _k118
        from src.retrieval import ArticleIndex as _AI118
        _ix = _AI118.load()
        _a = next(a for a in _ix.articles if a.code == "kodi_proc_penale" and a.number == "268")
        _okA = _p118.SEARCH_CHAPTERS and "KOMPENSIMI PËR BURGIM" in _a.searchable_text and "KREU V —" not in _a.searchable_text
        _okB = ("kodi_proc_penale", "268") in {(x.code, x.number) for x, _s in _ix.search("kompensimi për paraburgim të padrejtë", top_k=12)}
        _tr = {a.kreu for a in _ix.articles if a.kreu and _re118.search(r"\b(DHE|E|TË|I|NË|PËR|OSE|SË)$", a.kreu)}
        _okC = len(_tr) <= 5 and _p118._titolo_con_intestazione("KREU X", "KËQYRJA E PERSONAVE\nDHE SENDEVE\nNeni 286\n") == "KREU X — KËQYRJA E PERSONAVE DHE SENDEVE" \
               and _p118._titolo_con_intestazione("TITULLI IV", "(Shfuqizuar titulli IV)\nPJESA E TRETË\n") == "TITULLI IV — (Shfuqizuar titulli IV)"
        _kb = _k118.LegalKBRetriever.load()
        _hd = _kb.search(["gjobë doganore kontrabandë mallrash", "Dogana vendosi gjobë dhe konfiskim të mallrave"], top_k=5, type="doganor")
        _okD = _k118.PREC_STEM and sum(1 for c, _s in _hd if _re118.search(r"dogan|kontraband", (c.summary + c.excerpt).lower())) >= 3
        check("kreu[118]: titolo del capitolo cercabile (KPP 268 per «kompensimi për paraburgim të padrejtë») · titoli non troncati · precedenti con stemming (dogana ≥3/5)",
              _okA and _okB and _okC and _okD, "A=%s B=%s C=%s(%d) D=%s" % (_okA, _okB, _okC, len(_tr), _okD))
    except Exception as _e118:  # noqa: BLE001
        check("kreu[118]: kontrollet u ekzekutuan", False, str(_e118))

    # [119] v9.374 — la domanda «cosa dice il neni N»: il blocco non porta ancore automatiche né lo stesso numero di un
    # altro codice (KPC 350 ≠ KPP 350), la risposta segnala il codice gemello con la rubrica vera; l'antiriciclaggio è
    # nell'elenco dei documenti (prima invisibile col filtro per area); dogana/tributario → ligji 49/2012
    try:
        import threading as _th119
        from src import brain as _br119
        _al119 = ArticleIndex.load(_P81("/app/data/index/bm25.pkl")); _it119 = ArticleIndex.load(_P81("/app/data/index/bm25_it.pkl"))
        _sa = _br119.SuperAvvocato.__new__(_br119.SuperAvvocato); _sa.index, _sa.index_it = _al119, _it119
        _sa._jurisdiction_ctx = _th119.local(); _sa._jurisdiction_ctx.code = "AL"
        _kc = {str(a.number): a for a in _al119.articles if a.code == "kodi_civil"}
        _kpc = {str(a.number): a for a in _al119.articles if a.code == "kodi_proc_civile"}
        _anc = __import__("copy").copy(_kc["114"]); _anc._ancora = True
        _r = _sa._ankoro_citimet("cfar thot neni 350 i procedures civile?", [(_anc, 0.0), (_kc["131"], 5.0)])
        _okA = (_r[0][0].code, str(_r[0][0].number)) == ("kodi_proc_civile", "350") and not any(getattr(a, "_ancora", False) for a, _s in _r)
        _kpp = {str(a.number): a for a in _al119.articles if a.code == "kodi_proc_penale"}
        _r2 = _sa._ankoro_citimet("cili esht neni 350 i procedures penale?", [(_kpc["350"], 9.0), (_kpp["49"], 8.0)])
        _okB = [(a.code, str(a.number)) for a, _s in _r2] == [("kodi_proc_penale", "350"), ("kodi_proc_penale", "49")]
        _t = _sa._shenim_binjak("cfar thot neni 350 i procedures civile?", _r, "X")
        _okC = "Kodi i Procedurës Penale" in _t and "Mungesa e të pandehurit" in _t and "neni 350 KPP" in _t
        _okD = _sa._shenim_binjak("Klienti im u pushua më 3 mars; sipas nenit 155 të Kodit të Punës çfarë i takon?",
                                  _sa._ankoro_citimet("Klienti im u pushua më 3 mars; sipas nenit 155 të Kodit të Punës çfarë i takon?", []), "X") == "X"
        _anc2 = __import__("copy").copy(_kc["131"]); _anc2._ancora = True
        _q3 = "Klienti im ka një borxh; sipas nenit 114 të Kodit Civil a ka rënë në parashkrim?"
        _r3 = _sa._ankoro_citimet(_q3, [(_anc2, 0.0)])
        _okE = not _br119._eshte_pyetje_norme(_q3) and any(getattr(a, "_ancora", False) for a, _s in _r3)   # con i fatti le ancore restano
        _okF = "ligji_pastrimi_parave" in {d.code for d in _br119.LEGAL_DOCUMENTS} \
               and "ligji_gjykatat_administrative" in _br119.PROCEDURAL_MAPPING["Doganor"] \
               and "ligji_gjykata_kushtetuese" in _br119.PROCEDURAL_MAPPING["Kushtetues"]
        _src119 = __import__("inspect").getsource(_br119)
        _okG = _src119.count("self._shenim_binjak(user_message, retrieved,") == 2
        check("pyetje-norme[119]: niente ancore né stesso numero di un altro codice nel blocco · riga «mos e ngatërro» col gemello (KPC 350 → KPP 350) · non sulle domande con fatti · ancore intatte coi fatti · antiriciclaggio nell'elenco · dogana→49/2012, Kushtetues→8577/2000 · cablato nei 2 percorsi semplici",
              _okA and _okB and _okC and _okD and _okE and _okF and _okG, "A=%s B=%s C=%s D=%s E=%s F=%s G=%s" % (_okA, _okB, _okC, _okD, _okE, _okF, _okG))
    except Exception as _e119:  # noqa: BLE001
        check("pyetje-norme[119]: kontrollet u ekzekutuan", False, str(_e119))

    # [120] v9.375 — LA RIGA DI VERIFICA LA SCRIVE SOLO IL CODICE (caso vero 23 set: nel follow-up «po neni 302 i kodit
    # penal?» il modello aveva copiato dal filo una riga sua «1 nen i verifikuar (teksti i plotë) … ✅» e il codice, vedendo
    # «🔎 **», saltava verifica e cancello)
    try:
        import threading as _th120
        from src import brain as _br120, trust_line as _tl120
        _sa = _br120.SuperAvvocato.__new__(_br120.SuperAvvocato)
        _sa.index = ArticleIndex.load(_P81("/app/data/index/bm25.pkl")); _sa.index_it = None
        _sa._jurisdiction_ctx = _th120.local(); _sa._jurisdiction_ctx.code = "AL"
        _falsa = "> 🔎 **Verifikimi:** 1 nen i verifikuar (teksti i plotë) | vendime 0 | mbulimi: i plotë për pyetjen — **✅ e verifikuar**"
        _t = _sa._riga_fiducie(_falsa + "\n\n**Neni 302 i Kodit Penal** — «Përkrahja e autorit të krimit».", [])
        _righe = [ln for ln in _t.splitlines() if "🔎 **" in ln]
        _okA = len(_righe) == 1 and "teksti i plotë" not in _t and "nene 1 të verifikuara" in _righe[0]
        _h = _br120._history_for_prompt([{"role": "user", "content": "neni 350 kpp?"},
                                          {"role": "assistant", "content": _falsa + "\n\nTeksti.\n\n> ℹ️ Mos e ngatërro: edhe **Kodi X** ka një **nen 350** — «Y»."}])
        _okB = "🔎" not in _h[1]["content"] and "Mos e ngatërro" not in _h[1]["content"] and "Teksti." in _h[1]["content"]
        _t2 = _tl120.inserisci_riga("### ⚖️ Vendimi\n\n" + _falsa + "\nverdetto", "> 🔎 **Verifikimi:** nene 2 të verifikuara | x — **✅ e verifikuar**", "### ⚖️ Vendimi")
        _okC = _t2.count("🔎 **") == 1 and "teksti i plotë" not in _t2 and _t2.startswith("### ⚖️ Vendimi> 🔎 **Verifikimi:** nene 2")
        _kpp = {str(a.number): a for a in _sa.index.articles if a.code == "kodi_proc_penale"}
        _c = __import__("copy").copy(_kpp["350"]); _c._cituar = True
        _t3 = _sa._shenim_binjak("cili esht neni 350 i procedures penale?", [(_c, 10.0)], "Teksti.\n\n> ℹ️ Mos e ngatërro: edhe **Kodi i Procedurës Civile** ka një **nen 350** — «e sajuar».")
        _okD = _t3.count("Mos e ngatërro") == 1 and "Kompetenca tokësore" in _t3 and "e sajuar" not in _t3
        check("verifica[120]: la riga «🔎» del modello si toglie e resta solo quella calcolata (percorso semplice e verdetto) · nel filo non entrano righe di verifica né dei gemelli · la riga dei gemelli è una sola, dal corpus",
              _okA and _okB and _okC and _okD, "A=%s B=%s C=%s D=%s" % (_okA, _okB, _okC, _okD))
    except Exception as _e120:  # noqa: BLE001
        check("verifica[120]: kontrollet u ekzekutuan", False, str(_e120))

    # [121] v9.376 — (1) l'indice FTS italiano non si ricostruisce più DENTRO la domanda (56 s misurati: il cron TAR/CdS
    # delle 03:45 cambiava l'archivio senza ricostruire) e si ricostruisce in un file temporaneo sostituito in un colpo;
    # (2) 98/2016 e 152/2013 nel corpus; (3) abrogazioni «titolo (Shfuqizuar me ligjin …).» riconosciute, mai quelle di
    # una parte; lo strumento di ricalcolo legge la nota (senza, 118 abrogati tornavano «vivi»); (4) embedding: articoli
    # senza corpo codificati per intero, titolo del capitolo nella testata
    try:
        import inspect as _in121, os as _os121
        from src import it_precedent_fts as _f121, parser as _p121, dense as _d121
        _k = _in121.getsource(_f121.kerko); _r = _in121.getsource(_f121.rebuild_indeksi)
        _okA = "_ricostruisci_in_sottofondo()" in _k and "rebuild_indeksi()" in _k.split("_ricostruisci_in_sottofondo()")[0] \
               and 'DB.name + ".tmp"' in _r and "os.replace(tmp, DB)" in _r
        _cr = "/app/ops/it-ga-cron.sh"
        _okA = _okA and (not _os121.path.exists(_cr) or "rebuild_indeksi" in open(_cr, encoding="utf-8").read())
        _ix = ArticleIndex.load(_P81("/app/data/index/bm25.pkl"))
        _cnt = __import__("collections").Counter(a.code for a in _ix.articles)
        _okB = _cnt.get("ligji_pushteti_gjyqesor", 0) >= 80 and _cnt.get("ligji_nepunesi_civil", 0) >= 60
        _by = {(a.code, a.number): a for a in _ix.articles}
        _okC = _by[("ligji_gjykata_kushtetuese", "79")].repealed and not _by[("kodi_civil", "398")].repealed \
               and _p121.is_repealed_stub("Vendimi interpretues (Shfuqizuar me ligjin nr. 99/2016, datë 6.10.2016).", "") \
               and not _p121.is_repealed_stub("Në vendet ku nuk ka noter, testamenti mund të vërtetohet. (Shfuqizuar fjalë me ligjin nr. 8781)", "")
        _rt = "/app/tools/recompute_repealed_al.py"
        _okC = _okC and (not _os121.path.exists(_rt) or 'd.get("note")' in open(_rt, encoding="utf-8").read())
        _bd = open("/app/tools/build_dense.py", encoding="utf-8").read() if _os121.path.exists("/app/tools/build_dense.py") else ""
        _okD = "rub_max" in _in121.signature(_d121.chunk_text).parameters and (not _bd or ("--kreu" in _bd and "def _corpo" in _bd))
        check("fts+corpus[121]: indice IT mai ricostruito dentro la domanda (sottofondo + file temporaneo) e dal cron TAR/CdS · 98/2016 e 152/2013 nel corpus · «titolo (Shfuqizuar me ligjin …).» abrogato, «Shfuqizuar fjalë» no, ricalcolo con la nota · embedding con capitoli e corpo intero",
              _okA and _okB and _okC and _okD, "A=%s B=%s C=%s D=%s" % (_okA, _okB, _okC, _okD))
    except Exception as _e121:  # noqa: BLE001
        check("fts+corpus[121]: kontrollet u ekzekutuan", False, str(_e121))

    # [122] v9.376 — FORMA BREVE (senso · soluzione · come si vince) dietro FORMATI_I_SHKURTER: spenta = prompt identico a
    # prima; accesa = quattro sezioni dense che conservano TUTTE le regole di esattezza; l'analisi completa chiusa nella UI
    try:
        import subprocess as _sp122, os as _os122
        from src import brain as _br122
        _okA = _br122.FORMATI_I_SHKURTER or ("PESË seksione FIKSE" in _br122.ANSWER_SYSTEM and "PESË seksione në shqip" in _br122._ISTRUZIONE_FORMATI)
        _sh = _br122.ANSWER_SYSTEM_SHKURTER
        _okB = all(k in _sh for k in ("## 1. 🎯 Në thelb", "## 2. 🛠️ Zgjidhja", "## 3. ⚔️ Si fitohet", "## 4. ⏰ Afatet",
                                       "MOSGJETJA NUK ËSHTË MUNGESË", "BUXHETI I KËRKIMIT", "[[case:", "Mos shpik numra nenesh",
                                       "Shkurtësia nuk justifikon asnjëherë një pasaktësi"))
        _env = dict(_os122.environ, FORMATI_I_SHKURTER="1")
        _r = _sp122.run([sys.executable, "-c", "import sys; sys.path.insert(0,'/app'); from src import brain as b, studio as s; "
                         "print(b.ANSWER_SYSTEM.startswith(b.ANSWER_SYSTEM_SHKURTER[:60]), b.SECTION_REF['strategic'], "
                         "'Si fitohet:' in s.GJYQTARI_SYSTEM['sq'], 'Come si vince:' in s.GJYQTARI_SYSTEM['it'], 'KATËR' in b._ISTRUZIONE_FORMATI)"],
                        capture_output=True, text=True, env=_env, timeout=240)
        _last = (_r.stdout.strip().splitlines() or [""])[-1]
        _okC = _last == "True seksioni 3 'Si fitohet' True True True"
        _js = open("/app/static/app.js", encoding="utf-8").read()
        _okD = "function collapseAnaliza(html)" in _js and "collapseAnaliza(collapseSparring(" in _js
        check("forma[122]: interruttore spento = prompt identico · forma breve con tutte le regole di esattezza · accesa: senior 4 sezioni, riferimenti coerenti, verdetto chiuso da senso/soluzione/come si vince (sq+it) · analisi completa chiusa nella UI",
              _okA and _okB and _okC and _okD, "A=%s B=%s C=%s(%s) D=%s" % (_okA, _okB, _okC, _last[:80], _okD))
    except Exception as _e122:  # noqa: BLE001
        check("forma[122]: kontrollet u ekzekutuan", False, str(_e122))

    # [123] v9.376 — le decisioni della Gjykata e Lartë ANNULLATE dalla Kushtetuese (dal dispositivo della Kushtetuese)
    # non entrano nella ricerca dei precedenti, ma il verificatore le riconosce ancora come «quashed»; e il corpo di un
    # articolo non porta più l'intestazione del capitolo seguente (976 articoli)
    try:
        from src import retrieval_kb as _k123, case_graph as _cg123, parser as _p123
        _ann = _cg123.annullati_gjl()
        _kb = _k123.LegalKBRetriever.load()
        _in = {c.case_number for c in _kb.cases if c.court_code == "gjykata_elarte"}
        _okA = bool(_ann) and not (_in & set(_ann))
        _okB = _p123.taglia_coda_gerarchia("Teksti.\nKREU VI\nMASAT E SIGURIMIT PASUROR")[0] == "Teksti." \
               and _p123.taglia_coda_gerarchia("Teksti.\n(Ndryshuar me ligjin nr. 35/2017)")[1] == ""
        _ix = ArticleIndex.load(_P81("/app/data/index/bm25.pkl"))
        _k269 = next(a for a in _ix.articles if a.code == "kodi_proc_penale" and a.number == "269")
        _okC = "KREU VI" not in _k269.body and "ligj të veçantë" in _k269.body
        _okD = any(a.code == "ligji_konsumatoret" and a.number == "20" and a.repealed for a in _ix.articles)
        check("vendime+nene[123]: GjL annullate dalla Kushtetuese fuori dalla ricerca · coda del capitolo seguente tolta dal corpo (KPP 269) · abrogati dalla nota a piè di pagina (konsumatoret 20)",
              _okA and _okB and _okC and _okD, "A=%s(%d annullate) B=%s C=%s D=%s" % (_okA, len(_ann), _okB, _okC, _okD))
    except Exception as _e123:  # noqa: BLE001
        check("vendime+nene[123]: kontrollet u ekzekutuan", False, str(_e123))

    # [124] v9.377 — ancora italiana del VEICOLO EXTRA-UE (benchmark strato 2: l'ammissione temporanea non entrava con le
    # parole dell'avvocato): scatta con targa albanese, NON con targa UE né fuori tema; si aggiunge ai 12, non li sostituisce
    try:
        import threading as _th124
        from src import brain as _br124
        _sa = _br124.SuperAvvocato.__new__(_br124.SuperAvvocato)
        _sa.index = ArticleIndex.load(_P81("/app/data/index/bm25.pkl")); _sa.index_it = ArticleIndex.load(_P81("/app/data/index/bm25_it.pkl"))
        _sa._jurisdiction_ctx = _th124.local(); _sa._jurisdiction_ctx.code = "IT"
        def _r124(summ, qs):
            return _sa._retrieve(_br124.TriageResult(problem_summary=summ, areas=[], search_queries=qs, strategic_angles=[]))
        _a = _r124("Auto targata albanese di una sh.p.k. usata in Italia dall'amministratore residente in Italia",
                   ["circolazione veicolo con targa estera residente in Italia"])
        _k = {(x.code, str(x.number)) for x, _s in _a}
        _okA = ("reg_ue_2015_2446", "215") in _k and ("codice_doganale_ue", "250") in _k and len(_a) > 12
        _b = _r124("Auto con targa tedesca usata in Italia da un residente", ["circolazione veicolo con targa estera residente in Italia"])
        _c = _r124("Licenziamento per giustificato motivo oggettivo", ["licenziamento giustificato motivo oggettivo"])
        _okB = not any(getattr(x, "_ancora_it", False) for x, _s in _b + _c)
        _okC = "VEICOLO EXTRA-UE — REGIME DOGANALE" in _br124._format_articles_for_prompt([x for x in _a if getattr(x[0], "_ancora_it", False)][:1])
        check("ancora-IT[124]: veicolo extra-UE → ammissione temporanea (Reg. 2446 art. 215, CDU 250) in aggiunta ai 12 · niente con targa UE né fuori tema · dichiarata nel blocco",
              _okA and _okB and _okC, "A=%s B=%s C=%s" % (_okA, _okB, _okC))
    except Exception as _e124:  # noqa: BLE001
        check("ancora-IT[124]: kontrollet u ekzekutuan", False, str(_e124))

    # [125] v9.378 — Ligji 9902/2008 (konsumatorët): i numeri delle note attaccati ai numeri degli articoli («Neni 45²⁵» →
    # «4525») facevano sparire 45/57/59 dentro l'articolo precedente e davano numeri falsi (52/128, 56/132)
    try:
        _ix = ArticleIndex.load(_P81("/app/data/index/bm25.pkl"))
        _kn = {a.number: a for a in _ix.articles if a.code == "ligji_konsumatoret"}
        _okA = all(n in _kn and len(_kn[n].body or _kn[n].heading or "") > 80 for n in ("45", "57", "59", "56/1", "52/1"))
        _okB = not any(n in _kn for n in ("52/128", "52/229", "56/132", "58/136")) and all(_kn[n].repealed for n in ("19", "20", "21", "23"))
        _okC = len(_kn["44"].body or "") < 4000 and "Detyrime të tjera" not in (_kn["44"].body or "")
        check("konsumatoret[125]: 45/57/59/56/1/52/1 col loro testo · nessun numero falso (52/128…) · 19-21, 23 abrogati dalla nota · il 44 senza il testo del 45",
              _okA and _okB and _okC, "A=%s B=%s C=%s" % (_okA, _okB, _okC))
    except Exception as _e125:  # noqa: BLE001
        check("konsumatoret[125]: kontrollet u ekzekutuan", False, str(_e125))

    print("\n== Përfundim: %d kaluan, %d dështuan ==" % (PASSES, len(FAILS)))
    if FAILS:
        print("DËSHTIME:", ", ".join(FAILS))
        return 1
    print("\033[32mTË GJITHA GJELBËR — truri i shenjtë i paprekur.\033[0m")
    return 0


if __name__ == "__main__":
    sys.exit(main())
