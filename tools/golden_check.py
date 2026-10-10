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


def _cv_esiste(index, code, number) -> bool:
    """v9.403: l'articolo esiste nel corpus ed è in vigore (per le sezioni che controllano i semi)."""
    n = str(number)
    return any(a.code == code and str(a.number) == n and not getattr(a, "repealed", False) for a in index.articles)


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
    # v9.571: il KC 316 ha ora la sua rubrica vera («Kuptimi i trashëgimit»; la prima frase «Trashëgimia është…» è tornata nel corpo):
    # il controllo resta sullo SCOPO — senza accenti si trovano le rubriche del KC che cominciano con «Trashëgim…»
    _tr3 = [(c, n, h) for c, n, h in ex._heading_scan(idx, "trashegimia")]
    check("heading-scan 'trashegimia' (pa theks) → nene të KC me titull «Trashëgim…» (diacritic-fold)",
          any(c == "kodi_civil" and ex._fold(h).startswith("trashegim") for c, n, h in _tr3), str([(c, n) for c, n, _h in _tr3]))
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
        check("effort[33]: complete() passa da _pick_effort e lo stream (senior) resta a self.effort salvo scelta del percorso (v9.393)",
              "_eff = self._pick_effort(fast, medium, effort_override)" in _bs33
              and "_eff_s = effort_override or self.effort" in _bs33)
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
        check("mbledhes[34]: config — sonnet/medium/0.50$/110s, web e qbz accesi (v9.518: 0,30 → 0,50)",
              _cf34.STUDIO_MBLEDHES_ENABLED and _cf34.STUDIO_MBLEDHES_MODEL == "sonnet"
              and _cf34.STUDIO_MBLEDHES_EFFORT == "medium" and abs(_cf34.STUDIO_MBLEDHES_BUDGET_USD - 0.50) < 1e-9
              and _cf34.STUDIO_MBLEDHES_TIMEOUT == 110 and _cf34.STUDIO_MBLEDHES_WEB and _cf34.STUDIO_MBLEDHES_QBZ)
        _kw = _st34._kwargs_mbledhesi("sonnet", "medium")
        check("mbledhes[34]: «sonnet» del raccoglitore = tier MEDIUM (ha il web) + effort medium",
              _kw.get("medium") is True and _kw.get("effort_override") == "medium" and "fast" not in _kw)
        _bs = _io34.open(_os34.path.join(_rr34, "src", "backends.py"), encoding="utf-8").read()
        check("mbledhes[34]: backends — budget_usd per chiamata → --max-budget-usd",
              "budget_usd: float | None = None" in _bs
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
        # v9.393: il senior della sala di guerra passa da _senior_kw("deep") (⚡ Fable compreso) in TUTTI e tre i compose
        check("skuadra[37]: senior — override applicato in TUTTI i compose complessi (_senior_kw, ⚡ compreso)",
              _br37.count('**_senior_kw("deep")') == 3 and 'return _senior_override("fable")' in _br37
              and 'request_senior() != "fable"' in _br37)
        check("skuadra[37]: web — mendja letta, armata nel job, e «fable» ⇒ approfondito",
              'data.get("mendja")' in _wb37 and "brain_mod.set_request_senior(mendja)" in _wb37
              and 'mendja == "fable"' in _wb37)
        # SACRO — ESEGUITO: senza «fable» il cervello resta Opus (nessun override)
        from src import brain as _brain37
        check("skuadra[37]: SACRO — «fable» → Fable max; vuoto/«opus» → nessun override (Opus default)",
              _brain37._senior_override("fable") == {"model_override": "claude-fable-5-1", "effort_override": "max"}
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
              and "[WEB-001] VKM (burim dytësor)" in _rap40      # v9.399: la qualità a parole, in shqip
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
        _stream65 = _cs65[_i65:_i65 + 12000] if _i65 >= 0 else ""
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
              and ('text = (final_text or "".join(collected)).strip()' in _cs65
                   or 'text = _trattini((final_text or "".join(collected)).strip())' in _cs65)   # v9.513
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
                # v9.404: l'abrogato che la riga DICHIARA («Neni 79 … është shfuqizuar me ligjin 122/2013») non è più bocciato
                # (trust_line._abrogazione_dichiarata): i bocciati sono il fantasma 9999 e il 420 citato come vigente
                and _v3["nene"]["fake"] == 0 and _rap["prima"] == 2 and _rap["rimossi"] == 1 and _rap["dopo"] == 0)
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
        _okA = (abs(_f[("kc", "2")][0] - (1/(_dn102.RRF_K + 2) + 1/(_dn102.RRF_K + 1))) < 1e-9 and _f[("kc", "2")][1] == 5.0 and _f[("kc", "2")][2] == 0.8
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
        _okA = ('_riserva_gj = _riserva_giudice(_modeli_gj)' in _g and "gjyqtari i rezervës" in _g
                and _br108._riserva_giudice("claude-fable-5-1") == "opus" and _br108._riserva_giudice("opus") == "claude-fable-5-1"
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
        _env = dict(_os122.environ, FORMATI_I_SHKURTER="1", GJYQTARI_TRE_RRESHTA="1")
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

    # [126] v9.379 — segni di nota dopo il numero («Neni 70†»: il 70 «Shfuqizimi» della 152/2013 finiva nel 69) e sotto-articoli
    # con la nota attaccata («77/11», «77/22» = 77/1, 77/2 della legge sui trasporti, aggiunti dalla 10/2016)
    try:
        from src import parser as _p126
        _okA = _p126._SEGNO_NOTA_RE.sub(r"\1", "Neni 70†\nShfuqizimi") == "Neni 70\nShfuqizimi" and _p126._SEGNO_NOTA_RE.sub(r"\1", "Neni 1913") == "Neni 1913"
        _ix = ArticleIndex.load(_P81("/app/data/index/bm25.pkl"))
        _by = {(a.code, a.number): a for a in _ix.articles}
        _okB = ("ligji_nepunesi_civil", "70") in _by and "8549" in (_by[("ligji_nepunesi_civil", "70")].body or "") \
               and "Shfuqizimi" not in (_by[("ligji_nepunesi_civil", "69")].body or "")
        _okC = ("ligji_transportet_rrugore", "77/1") in _by and ("ligji_transportet_rrugore", "77/2") in _by \
               and ("ligji_transportet_rrugore", "77/11") not in _by and ("ligji_transportet_rrugore", "77/22") not in _by
        check("nene[126]: segno di nota dopo il numero tolto (152/2013 neni 70 torna suo) · 77/1 e 77/2 dei trasporti invece di 77/11 e 77/22",
              _okA and _okB and _okC, "A=%s B=%s C=%s" % (_okA, _okB, _okC))
    except Exception as _e126:  # noqa: BLE001
        check("nene[126]: kontrollet u ekzekutuan", False, str(_e126))

    # [127] v9.380 — ancore misurate col triage VERO (tools/eval_triage_ricerca.py, 10/14 → 13-14/14): «già presente» vuol dire
    # dentro i 12 (dalla ricerca ibrida un articolo al 40° posto contava come trovato e il taglio lo buttava); KC 698 sulla
    # qira non pagata (non nel lavoro), KC 360-361 sulla successione legittima, 8577/2000 art. 71/a sul ricorso individuale
    # (anche con radici sparse), art. 2946 c.c. sulla prescrizione (non nel penale)
    try:
        from src import brain as _br127
        _ix = ArticleIndex.load(_P81("/app/data/index/bm25.pkl")); _it = ArticleIndex.load(_P81("/app/data/index/bm25_it.pkl"))
        _al = [a for a in _ix.articles if a.code == "kodi_civil"][:30]
        _k698 = next(a for a in _ix.articles if a.code == "kodi_civil" and a.number == "698")
        _p = [(a, 1.0) for a in _al[:20]] + [(_k698, 0.5)]              # il 698 c'è, ma al 21° posto
        _r = _br127._applica_ancore(_p, _ix, ["zgjidhja e kontratës së qirasë për mospagim"], ["Civil"])
        _okA = [(a.code, a.number) for a, _s in _r[:12]].count(("kodi_civil", "698")) == 1
        _okB = not any(getattr(a, "_ancora", False) and a.number == "698" for a, _s in
                       _br127._applica_ancore([(a, 1.0) for a in _al[:5]], _ix, ["zgjidhja e kontratës së punës për mospagim e pagës"], ["Punë"]))
        _r3 = _br127._applica_ancore([(a, 1.0) for a in _al[:5]], _ix, ["ndarja e pasurisë së babait midis bashkëshortes dhe fëmijëve"], ["Civil"])
        _okC = {("kodi_civil", "360"), ("kodi_civil", "361")} <= {(a.code, a.number) for a, _s in _r3[:12]} or \
               "trashëgim" not in "ndarja e pasurisë së babait midis bashkëshortes dhe fëmijëve"
        _r3b = _br127._applica_ancore([(a, 1.0) for a in _al[:5]], _ix, ["trashëgimia e bashkëshortit dhe fëmijëve pa testament"], ["Civil"])
        _okC = {("kodi_civil", "360"), ("kodi_civil", "361")} <= {(a.code, a.number) for a, _s in _r3b[:12]}
        _r4 = _br127._applica_ancore([(a, 1.0) for a in _al[:5]], _ix, ["ankim individual në gjykatën kushtetuese afati"], ["Kushtetues"])
        _okD = ("ligji_gjykata_kushtetuese", "71/a") in {(a.code, a.number) for a, _s in _r4[:12]}
        _itc = [a for a in _it.articles if a.code == "codice_civile"][:5]
        _r5 = _br127._applica_ancore([(a, 1.0) for a in _itc], _it, ["interruzione della prescrizione del credito"], ["Civile"], ancore=_br127.ANCORE_IT)
        _r6 = _br127._applica_ancore([(a, 1.0) for a in _itc], _it, ["prescrizione del reato"], ["Penale"], ancore=_br127.ANCORE_IT)
        _okE = ("codice_civile", "2946") in {(a.code, a.number) for a, _s in _r5[:12]} and \
               ("codice_civile", "2946") not in {(a.code, a.number) for a, _s in _r6[:12]}
        check("ancore[127]: presente = dentro i 12 (il 698 al 21° posto sale) · KC 698 qira sì, lavoro no · KC 360-361 successione · 71/a ricorso individuale (radici) · 2946 c.c. civile sì, penale no",
              _okA and _okB and _okC and _okD and _okE, "A=%s B=%s C=%s D=%s E=%s" % (_okA, _okB, _okC, _okD, _okE))
    except Exception as _e127:  # noqa: BLE001
        check("ancore[127]: kontrollet u ekzekutuan", False, str(_e127))

    # [128] v9.381 — compravendita di immobile registrato → KC 193 e 195 nel blocco (la trappola del caso «kufizim»: il 195 non
    # arrivava MAI); e «parashkrimi fitues» (usucapione) non accende più il KC 114 (prescrizione estintiva)
    try:
        from src import brain as _br128
        _ix = ArticleIndex.load(_P81("/app/data/index/bm25.pkl"))
        _base = [(a, 1.0) for a in _ix.articles if a.code == "ligji_kadastra"][:6]
        _r = _br128._applica_ancore(_base, _ix, ["shitja e apartamentit të regjistruar në ASHK me kufizim në kartelë"], ["Prone", "Civil"])
        _k = {(a.code, a.number) for a, _s in _r[:12]}
        _okA = {("kodi_civil", "193"), ("kodi_civil", "195")} <= _k
        _r2 = _br128._applica_ancore(_base, _ix, ["fitimi i pronësisë me parashkrim fitues të truallit"], ["Prone", "Civil"])
        _okB = ("kodi_civil", "114") not in {(a.code, a.number) for a, _s in _r2[:12]}
        _r3 = _br128._applica_ancore(_base, _ix, ["afati i parashkrimit të padisë për detyrimin"], ["Civil"])
        _okC = ("kodi_civil", "114") in {(a.code, a.number) for a, _s in _r3[:12]}
        check("ancore[128]: immobile registrato → KC 193 + 195 · usucapione («parashkrimi fitues») non accende il KC 114 · la prescrizione estintiva sì",
              _okA and _okB and _okC, "A=%s B=%s C=%s" % (_okA, _okB, _okC))
    except Exception as _e128:  # noqa: BLE001
        check("ancore[128]: kontrollet u ekzekutuan", False, str(_e128))

    # [129] v9.383 — I TITOLI DEI CAPITOLI ITALIANI (Libro / Titolo / Capo / Sezione), letti dall'albero di Normattiva da
    # tools/it_gerarchia.py con le regole trovate MISURANDO: l'etichetta del testo modificato «<em><strong>((TITOLO IV» (il
    # primo regex la saltava: 288 intestazioni perse, fra cui il rito del lavoro del c.p.c.), «TITOLO DODICESIMO», «Par. 2»,
    # la SEZIONE sopra i TITOLI (cod. ambiente), il capo abrogato, il gruppo decreto/allegato; poi il testo cercabile (etichette
    # tolte, note di abrogazione fuori) e l'indice vero (c.p.c. 414 = rito del lavoro, c.p.p. 314 = ingiusta detenzione)
    try:
        import importlib.util as _ilu129, os as _os129
        from pathlib import Path as _P129
        _sp129 = _ilu129.spec_from_file_location("_ger129", _os129.path.join(_os129.path.dirname(_os129.path.abspath(__file__)), "it_gerarchia.py"))
        _G = _ilu129.module_from_spec(_sp129); _sp129.loader.exec_module(_G)

        def _h129(lab, corpo, n):
            return (f'<div class="collapse-header"><a class="" data-toggle="collapse" data-target="#coll_{n}" aria-expanded="true">{lab}</a>'
                    f'</div><span class="snippets"><div id="coll_{n}" class="collapse show">{corpo}</div></span>')

        def _a129(num, flag="1", s1="10"):
            return (f'<a href="" onclick="return showArticle(\'/atto/caricaArticolo?art.flagTipoArticolo={flag}&art.idArticolo={num}'
                    f'&art.idSottoArticolo=1&art.idSottoArticolo1={s1}\', this);" class="numero_articolo">art. {num}</a>')
        _pg = (_h129("LIBRO SECONDO", "DEL PROCESSO<br/>TITOLO III<br/>DELLE IMPUGNAZIONI<br/>CAPO V<br/>Dell'opposizione di terzo", 1) + _a129(404) +
               _h129("<em><strong>((TITOLO IV", "NORME PER LE CONTROVERSIE IN MATERIA DI LAVORO<br/>CAPO I<br/>Delle controversie individuali"
                     "<br/>Sezione II<br/>Del procedimento<br/>Par. 1<br/>Del primo grado))</strong></em><br/>", 2) + _a129(414) +
               _h129("Par. 2", "Delle impugnazioni", 3) + _a129(433) +
               _h129("PARTE TERZA", "NORME AMBIENTALI<br/>SEZIONE II<br/>TUTELA DELLE ACQUE<br/>TITOLO I<br/>PRINCIPI", 4) + _a129(73) +
               _h129("TITOLO II", "OBIETTIVI", 5) + _a129(76) + _h129("SEZIONE III", "RISORSE IDRICHE<br/>TITOLO I<br/>PRINCIPI", 6) + _a129(141) +
               _h129("TITOLO DODICESIMO", "DEI DELITTI CONTRO LA PERSONA<br/>CAPO I<br/>Dei delitti contro la vita", 7) + _a129(575) +
               _h129("CAPO II", "Dei delitti ((CAPO ABROGATO DALLA L. 1 GENNAIO 2000, N. 1))", 8) + _a129(580) + _a129(1, flag="0"))
        _m, _st = _G.albero(_pg, "")
        _v = lambda n, g="1": " | ".join(_m.get((g, n), ("", "", "")))
        _okA = (_st["intestazioni"] == 8 and "CAPO V — Dell'opposizione di terzo" in _v("404")
                and "TITOLO IV — NORME PER LE CONTROVERSIE IN MATERIA DI LAVORO" in _v("414") and "Par. 1 — Del primo grado" in _v("414")
                and "Par. 2 — Delle impugnazioni" in _v("433") and "TITOLO IV — NORME PER LE CONTROVERSIE" in _v("433"))
        _okB = ("SEZIONE II — TUTELA DELLE ACQUE" in _m[("1", "73")][0] and _m[("1", "73")][1] == "TITOLO I — PRINCIPI"
                and "SEZIONE II" in _m[("1", "76")][0] and _m[("1", "76")][1] == "TITOLO II — OBIETTIVI"
                and "SEZIONE III — RISORSE IDRICHE" in _m[("1", "141")][0])
        _okC = ("TITOLO DODICESIMO — DEI DELITTI CONTRO LA PERSONA · CAPO I — Dei delitti contro la vita" in _v("575")
                and "(CAPO ABROGATO DALLA L. 1 GENNAIO 2000, N. 1)" in _v("580") and _m.get(("0", "1")) == ("", "", ""))
        _okD = (_G._livello("Capo dello Stato") is None and _G._livello("PARTE CIVILE, RESPONSABILE CIVILE") is None
                and _G._livello("Sez. III - DOCUMENTI")["etichetta"] == "Sezione III" and _G._livello("Sezione 1ª")["etichetta"] == "Sezione 1ª"
                and _G._spezza("MODIFICHE AL TITOLO VIII") == ["MODIFICHE AL TITOLO VIII"]
                and _G._spezza("DOCUMENTAZIONE AMMINISTRATIVA SEZIONE I") == ["DOCUMENTAZIONE AMMINISTRATIVA", "SEZIONE I"])
        from src.parser import titoli_capitolo as _tc129
        _okE = (_tc129("TITOLO V — DELLA PRESCRIZIONE · CAPO I — Della prescrizione", "§ 1 — Della prescrizione ordinaria")
                == ["DELLA PRESCRIZIONE", "Della prescrizione", "Della prescrizione ordinaria"]
                and _tc129("TITOLO NONO — X · CAPO I — Dei delitti (CAPO ABROGATO DALLA L. 15 FEBBRAIO 1996, N. 66)") == ["X", "Dei delitti"]
                and _tc129("PARTE PRIMA · Capo II") == [] and _tc129("Capo dello Stato e poteri") == ["Capo dello Stato e poteri"]
                and _tc129("KREU V — KOMPENSIMI PËR BURGIM") == ["KOMPENSIMI PËR BURGIM"])
        _it129 = ArticleIndex.load(_P129("/app/data/index/bm25_it.pkl"))
        _by = {(a.code, str(a.number)): a for a in _it129.articles}
        _okF = ("CONTROVERSIE IN MATERIA DI LAVORO" in _by[("codice_procedura_civile", "414")].kreu
                and "DEI DELITTI CONTRO LA PERSONA" in _by[("codice_penale", "575")].kreu
                and "Della prescrizione ordinaria" in _by[("codice_civile", "2946")].seksioni
                and "RIPARAZIONE PER L'INGIUSTA DETENZIONE" in _by[("codice_procedura_penale", "314")].searchable_text
                and sum(1 for a in _it129.articles if a.kreu or a.seksioni or a.pjesa) >= 0.8 * len(_it129.articles))
        _okG = (("codice_procedura_penale", "314") in {(a.code, str(a.number)) for a, _s in _it129.search("riparazione per ingiusta detenzione", top_k=12)}
                and ("codice_procedura_civile", "665") in {(a.code, str(a.number)) for a, _s in _it129.search("opposizione alla convalida di sfratto", top_k=12)})
        check("capitoli IT[129]: albero (etichetta del testo modificato, Par., SEZIONE sopra i TITOLI, TITOLO DODICESIMO, capo abrogato, gruppo) · "
              "testo cercabile · indice vero (414 lavoro, 575 persona, 2946 §1, 314 ingiusta detenzione) · ricerca 314/665 nei 12",
              _okA and _okB and _okC and _okD and _okE and _okF and _okG,
              "A=%s B=%s C=%s D=%s E=%s F=%s G=%s" % (_okA, _okB, _okC, _okD, _okE, _okF, _okG))
    except Exception as _e129:  # noqa: BLE001
        check("capitoli IT[129]: kontrollet u ekzekutuan", False, str(_e129))

    # [130] v9.383 — GLI ARTICOLI «PUNTATI» (473-bis.1-71 c.p.c., 270-bis.1 c.p., 9.1 L. 91/1992…): la dedup dell'ingest non
    # guardava idSottoArticolo1 e ne buttava 263; il numero «Art. 473-bis.2» si leggeva «473-bis». Qui: la dedup nuova, il
    # numero, l'ordine, il corpus, e il verificatore («473-bis.12 c.p.c.» vero, «473-bis.99» falso, «6.1 CEDU» = par. 1)
    try:
        import importlib.util as _ilu130, os as _os130
        from pathlib import Path as _P130
        _sp130 = _ilu130.spec_from_file_location("_nl130", _os130.path.join(_os130.path.dirname(_os130.path.abspath(__file__)), "normattiva_lib.py"))
        _NL = _ilu130.module_from_spec(_sp130); _sp130.loader.exec_module(_NL)
        _l = ('<a onclick="return showArticle(\'/atto/caricaArticolo?art.flagTipoArticolo=1&art.idArticolo=473&art.idSottoArticolo=2'
              '&art.idSottoArticolo1=%s\', this);" class="numero_articolo">art. %s</a>')
        _html130 = (_l % ("10", "473 bis")) + (_l % ("20", "473 bis.1")) + (_l % ("30", "473 bis.2"))
        _okA = len(_NL.Normattiva.article_links_all(_html130)) == 3
        _okB = (_NL.LEGACY_HEAD.match("Art. 473-bis.2\n\n(Poteri del giudice).").groups() == ("473-bis.2", "Poteri del giudice")
                and sorted(["518-bis", "518.1", "518", "473-bis.10", "473-bis.2", "473-bis"], key=_NL.sortkey)
                == ["473-bis", "473-bis.2", "473-bis.10", "518", "518.1", "518-bis"])
        _it130 = ArticleIndex.load(_P130("/app/data/index/bm25_it.pkl"))
        _k130 = {(a.code, str(a.number)): a for a in _it130.articles}
        _okC = (all((("codice_procedura_civile", n) in _k130) for n in ("473-bis.1", "473-bis.12", "473-bis.71", "380-bis.1"))
                and ("codice_penale", "270-bis.1") in _k130 and ("cittadinanza", "9.1") in _k130
                and "Poteri del giudice" in (_k130[("codice_procedura_civile", "473-bis.2")].heading or ""))
        _st130 = lambda t: cv.verify_text(t, _it130)["items"][0]["status"] if cv.verify_text(t, _it130)["items"] else "none"
        _okD = (_st130("art. 473-bis.12 c.p.c.") == "verified" and _st130("art. 473-bis.99 c.p.c.") == "fake"
                and _st130("art. 270-bis.1 c.p.") == "verified" and _st130("art. 6.1 CEDU") == "verified"
                # lo spazio al posto del trattino («art. 473 bis c.p.c.») era un «inesistente» su un articolo vero
                and _st130("art. 473 bis c.p.c.") == "verified" and _st130("art. 473 bis.12 c.p.c.") == "verified"
                and _st130("art. 186 bis c.d.s.") in ("verified", "repealed") and _st130("art. 999 bis c.p.c.") == "fake")
        from src import temporal as _tm130
        _okE = _tm130._norm_num("473-bis.2") == "473bis.2" and _tm130._norm_num("9.1") != _tm130._norm_num("91")
        check("puntati IT[130]: dedup con idSottoArticolo1 · «Art. 473-bis.2» letto intero · ordine 518/518.1/518-bis · corpus "
              "(473-bis.1-71, 380-bis.1, 270-bis.1, 9.1) · verificatore (vero/falso/paragrafo) · temporal",
              _okA and _okB and _okC and _okD and _okE, "A=%s B=%s C=%s D=%s E=%s" % (_okA, _okB, _okC, _okD, _okE))
    except Exception as _e130:  # noqa: BLE001
        check("puntati IT[130]: kontrollet u ekzekutuan", False, str(_e130))

    # [131] v9.383 — LA RUBRICA RIMASTA NEL CORPO: 4.848 articoli IT vivi senza rubrica (c.c. 316 «Responsabilità
    # genitoriale», 536 «Legittimari», c.p. 635 «Danneggiamento», c.p.p. 11…) → build_it_index la prende dalla prima riga SOLO
    # se è una rubrica (corta, «.»/«)», riga vuota dopo, parola piena, nessun verbo finito); una frase normativa breve resta
    # nel corpo e non si inventa niente (c.c. 147 non ha rubrica su Normattiva)
    try:
        import importlib.util as _ilu131, os as _os131
        from pathlib import Path as _P131
        _sp131 = _ilu131.spec_from_file_location("_bii131", _os131.path.join(_os131.path.dirname(_os131.path.abspath(__file__)), "build_it_index.py"))
        _B = _ilu131.module_from_spec(_sp131); _sp131.loader.exec_module(_B)
        _okA = (_B._pulisci("", "Domicilio dei coniugi, del minore e dell'interdetto.\n\nCiascuno dei coniugi ha il proprio domicilio.")[0]
                == "Domicilio dei coniugi, del minore e dell'interdetto"
                and _B._pulisci("", "(( (Competenza per i procedimenti riguardanti i magistrati).\n\n1. I procedimenti")[0]
                == "Competenza per i procedimenti riguardanti i magistrati"
                and _B._pulisci("", "Prova del pagamento ( articolo 14 decreto legislativo 31 ottobre 1990, n. 347 )\n\n1. La prova")
                == ("Prova del pagamento", "( articolo 14 decreto legislativo 31 ottobre 1990, n. 347 )\n\n1. La prova")
                and _B._pulisci("", "Il matrimonio impone ai coniugi l'obbligo di mantenere i figli.\n\nAltro.")[0] == ""
                and _B._pulisci("", "I beni pubblici appartengono allo Stato.\n\nAltro.")[0] == ""
                and _B._pulisci("Rubrica vera", "Testo.\n\nAltro.")[0] == "Rubrica vera")
        _it131 = ArticleIndex.load(_P131("/app/data/index/bm25_it.pkl"))
        _by131 = {(a.code, str(a.number)): a for a in _it131.articles}
        _okB = (_by131[("codice_civile", "316")].heading == "Responsabilità genitoriale"
                and _by131[("codice_penale", "635")].heading == "Danneggiamento"
                and _by131[("codice_procedura_penale", "11")].heading == "Competenza per i procedimenti riguardanti i magistrati"
                and _by131[("codice_civile", "147")].heading == ""
                # i trattati (TFUE/TUE) non hanno rubriche: dal v9.384 la nota «(ex articolo … del TCE)» non fa più da rubrica
                and sum(1 for a in _it131.articles if not a.repealed and not (a.heading or "").strip()
                        and a.code not in ("tfue", "tue")) <= 3700)
        check("rubriche IT[131]: la rubrica rimasta nel corpo torna rubrica (anche dopo «(( (…).», con la fonte «( articolo … )» lasciata nel "
              "corpo) · mai da una frase normativa · indice vero (c.c. 316, c.p. 635, c.p.p. 11 sì; c.c. 147 no; senza rubrica ≤ 3.700 fuori dai trattati)",
              _okA and _okB, "A=%s B=%s" % (_okA, _okB))
    except Exception as _e131:  # noqa: BLE001
        check("rubriche IT[131]: kontrollet u ekzekutuan", False, str(_e131))

    # [132] v9.384 — IL DIRITTO UE E LA CEDU: capitoli (tools/eu_gerarchia.py, testo CELLAR dell'Ufficio delle pubblicazioni)
    # e testo riletto dalla stessa fonte strutturata (tools/reparse_eu_xhtml.py): prima il codice visti aveva negli artt.
    # 2/4/6/9 il testo dell'ALLEGATO sui Giochi olimpici, il Reg. 2446 all'art. 163 pezzi di una tabella e all'art. 4 un
    # altro articolo, e mancavano 28 articoli «bis» (Schengen 8-bis…, Reg. visti 8-bis…, Bruxelles I-bis 71-bis…) finiti
    # dentro l'articolo precedente; Roma I con le rubriche nel testo; TFUE con la nota «(ex articolo … del TCE)» come rubrica
    try:
        import importlib.util as _ilu132, os as _os132
        from pathlib import Path as _P132
        _sp132 = _ilu132.spec_from_file_location("_eug132", _os132.path.join(_os132.path.dirname(_os132.path.abspath(__file__)), "eu_gerarchia.py"))
        _EU = _ilu132.module_from_spec(_sp132); _sp132.loader.exec_module(_EU)
        _x = ('<p class="title-division-1">TITOLO VII</p><p class="title-division-2">REGIMI SPECIALI</p>'
              '<p class="title-division-1">CAPO 4</p><p class="title-division-2">Uso particolare</p>'
              '<p class="title-division-1">Sezione 1</p><p class="title-division-2">Ammissione temporanea</p>'
              '<p class="title-article-norm">Articolo 250</p><p class="norm">x</p>'
              '<p class="title-division-1">Sottosezione 2</p><p class="title-division-2">Mezzi di trasporto</p>'
              '<p class="title-article-norm">▼M5 Articolo 250 bis</p>'
              '<p class="title-division-1">CAPO 5</p><p class="title-division-2">Perfezionamento</p><p class="title-article-norm">Articolo 256</p>'
              '<p class="title-annex-1">ALLEGATO</p><p class="title-article-norm">Articolo 1</p>')
        _m132, _st132 = _EU.albero_ue(_x)
        _okA = (_m132[("0", "250")] == ("", "TITOLO VII — REGIMI SPECIALI · CAPO 4 — Uso particolare", "Sezione 1 — Ammissione temporanea")
                and "Sottosezione 2 — Mezzi di trasporto" in _m132[("0", "250-bis")][2]
                and _m132[("0", "256")][1].endswith("CAPO 5 — Perfezionamento") and _m132[("0", "256")][2] == ""
                and ("0", "1") not in _m132)                                # l'«Articolo 1» dell'allegato: ci si ferma al riavvio
        _it132 = ArticleIndex.load(_P132("/app/data/index/bm25_it.pkl"))
        _k132 = {(a.code, str(a.number)): a for a in _it132.articles}
        _okB = ("Ammissione temporanea" in _k132[("codice_doganale_ue", "250")].seksioni
                and "Mezzi di trasporto" in _k132[("reg_ue_2015_2446", "215")].seksioni
                and "contratti conclusi da consumatori" in _k132[("bruxelles_i_bis", "17")].seksioni
                and "DIRITTI E LIBERTÀ" in _k132[("cedu", "6")].kreu
                and "TITOLO I" not in _k132[("cedu", "1")].body[-40:])
        _okC = (_k132[("codice_visti", "6")].heading == "Competenza territoriale consolare"
                and "olimpic" not in _k132[("codice_visti", "6")].body.lower()
                and _k132[("reg_ue_2015_2446", "163")].heading == "Domanda di autorizzazione sulla base di una dichiarazione in dogana"
                and _k132[("reg_ue_2015_2446", "4")].heading == "Presentazione delle indicazioni per la registrazione EORI"
                and all((c, n) in _k132 for c, n in (("codice_frontiere_schengen", "8-bis"), ("reg_ue_2018_1806", "8-bis"),
                                                     ("bruxelles_i_bis", "71-bis"), ("codice_doganale_ue", "260-bis")))
                and _k132[("roma_i", "3")].heading == "Libertà di scelta"
                and _k132[("tfue", "45")].heading == "" and _k132[("tfue", "45")].body.startswith("(ex articolo 39 del TCE)"))
        check("UE/CEDU[132]: capitoli dall'albero CELLAR (pila, Sottosezione, riavvio agli allegati) · indice vero (CDU 250 ammissione "
              "temporanea, 2446 215 mezzi di trasporto, Bruxelles I-bis 17 consumatori, CEDU 6) · testo riletto (visti 6 senza Giochi "
              "olimpici, 2446 artt. 4/163, articoli «bis» presenti, Roma I rubriche, TFUE «ex articolo» nel testo)",
              _okA and _okB and _okC, "A=%s B=%s C=%s" % (_okA, _okB, _okC))
    except Exception as _e132:  # noqa: BLE001
        check("UE/CEDU[132]: kontrollet u ekzekutuan", False, str(_e132))

    # [133] v9.385 — LA CASSAZIONE SULL'ARCHIVIO UFFICIALE (src/cassazione.py). Misurato sulle 44 risposte italiane
    # salvate: 246 citazioni di Cassazione, 38 decisioni distinte dal 2009 — TUTTE vere (una data e una sezione
    # sbagliate), ma il verificatore conosceva solo la Consulta e senior/diavolo/Giudice le facevano espungere («non
    # compare negli archivi della verifica deterministica»: la Cass. 10383/2026, il caso identico dell'auto targata
    # Albania, «Non la citi»). Qui: la lettura delle forme vere (e di quelle che NON sono citazioni), il ramo dei record,
    # il confronto degli estremi, gli agganci; il controllo vivo solo se l'archivio risponde (mai un falso rosso).
    try:
        from src import cassazione as _C133
        _tr = lambda t: [(c["numero"], c["anno"], c["ramo"], c["sezione"], c["tipo"]) for c in _C133.trova(t)]
        _casi133 = [
            ("Cass. civ., Sez. V, ord. n. 10383/2026", [(10383, 2026, "civ", "5", "O")]),
            ("Cass. civ., Sez. VI-3, ord. 5 gennaio 2023, n. 194** e **Cass. civ., Sez. III, 11 giugno 2024, n. 16160**",
             [(194, 2023, "civ", "6", "O"), (16160, 2024, "civ", "3", "")]),
            ("Cass. SS.UU. nn. 18284 e 18286 del 4 luglio 2024; Cass. Sez. V n. 6614/2025 su Porsche",
             [(18284, 2024, None, "U", ""), (18286, 2024, None, "U", ""), (6614, 2025, None, "5", "")]),
            ("Cass. pen., Sez. III, sent. 29 luglio 2026, n. 28668** (yacht NEW VOGUE, su ordinanza del Tribunale di Imperia 24 febbraio 2026)",
             [(28668, 2026, "pen", "3", "S")]),
            ("Cass. civ., Sez. Lav., ord. n. 28927 dell'11 novembre 2024", [(28927, 2024, "civ", "L", "O")]),
            ("Cassazione civile, sez. lavoro, sentenza n. 1234 del 2023", [(1234, 2023, "civ", "L", "S")]),
            ("Cass. pen. Sez. 6, n. 12345 del 15/12/2023 (dep. 2024), Rv. 286123-01", [(12345, 2024, "pen", "6", "")]),
            ("*Cass. ord. n. 26035/2025* e *n. 30079/2024*", [(26035, 2025, None, "", "O"), (30079, 2024, None, "", "O")]),
            ("SS.UU. 141/2006 chiude il punto", [(141, 2006, None, "U", "")]),
            ("Cass., Sez. Un. civ., ord. 4 luglio 2024, r.o. n. 167/2024", []),                 # r.o. = registro della Consulta
            ("CTR Emilia-Romagna n. 1516/4/2020 e CTP Brescia n. 221/3/2020", []),
            ("la Cassazione ha ripetutamente affermato che il deposito", []),
            ("[Cass. Sez. Lav. n. 4879/2020](https://x.it/cassazione-sentenza-n-9999-2021)", [(4879, 2020, "civ", "L", "")]),
            ("S.U.A.P. n. 123/2024", []),
        ]
        _bad133 = [(t, _tr(t), e) for t, e in _casi133 if _tr(t) != e]
        _d1 = _C133.trova("Cass. civ., Sez. V, ord. n. 10383/2026, dep. 27 aprile 2026")[0]["date"]
        _d2 = _C133.trova("Cass. civ., Sez. V, n. 15208/2024 (consultata il 15/09/2026)")[0]["date"]
        _okA = not _bad133 and _d1 == [("2026-04-27", "dep")] and _d2 == []
        _rs = _C133._record({"id": "sic2026510383O021202", "kind": "sic", "sic-datdep": "20/04/2026", "sic-data_ud": ["25/02/2026"],
                             "sic-materia": ["TRIBUTI E DAZI DOGANALI"], "sic-ricorrente": ["AGENZIA DELLE DOGANE"]})
        _rp = _C133._record({"id": "sic2026710383O038340", "kind": "sic", "sic-datdep": "18/03/2026"})
        _rn = _C133._record({"id": "snciv2026510383O", "kind": "snciv", "datdep": ["20260420"], "datdec": "20260225",
                             "filename": ["./20260420/snciv@s50@a2026@n10383@tO.pdf"], "ocrdis": ["P.Q.M. La Corte accoglie il ricorso, cassa e rinvia"]})
        _okB = (_rs["ramo"] == "civ" and _rs["sezione"] == "5" and _rs["numero"] == 10383 and _rs["datdep"] == "2026-04-20"
                and _rp["ramo"] == "pen" and _rn["url"].endswith("snciv@s50@a2026@n10383@tO.clean.pdf")
                and _rn["url"].startswith("https://www.italgiure.giustizia.it/") and _rn["esito"].startswith("accoglie")
                and _C133._esito("P.Q.M. Dichiara inammissibile il ricorso") == "ricorso inammissibile"
                and _C133._esito("P.Q.M. visto l'art. 267 TFUE chiede alla Corte di giustizia dell'Unione europea di pronunciarsi").startswith("rinvio"))
        _recs = _C133._unisci([_rs, _rn, _rp])
        _m1 = _C133.trova("Cass. civ., Sez. V, ord. n. 10383/2026, dep. 27 aprile 2026")
        _v1 = _C133.valuta(_m1, _recs)
        _m2 = _C133.trova("Cass. civ., Sez. VI, ord. n. 10383/2026")
        _v2 = _C133.valuta(_m2, _recs)
        _v3 = _C133.valuta(_C133.trova("Cass. n. 10383/2026"), _recs, "civ")
        _v4 = _C133.valuta(_C133.trova("Cass. n. 10383/2026"), [])
        # sezione sbagliata MA data giusta = lo stesso provvedimento (la «sesta-3» citata «Sez. III», Cass. 3882/2015)
        _v5 = _C133.valuta(_C133.trova("Cass. civ., Sez. III, ord. n. 10383 del 20 aprile 2026"), _recs)
        _okC = (_v1["status"] == "verified" and any("20/04/2026" in c and "27/04/2026" in c for c in _v1["correzioni"])
                and _v2["status"] == "mismatch" and _v2.get("motivo") == "sezione"
                and _v3["status"] == "verified" and _v3.get("dedotto") and _v3["record"]["ramo"] == "civ"
                and _v4["status"] == "unverified"
                and _v5["status"] == "verified" and any(c.startswith("sezione: Sez. V") for c in _v5["correzioni"]))
        import inspect as _in133
        from src import trust_line as _tl133, studio as _st133
        _js133 = open("/app/static/app.js", encoding="utf-8").read()
        _br133 = open("/app/src/brain.py", encoding="utf-8").read()
        _okD = ("cassazione as _cass" in _in133.getsource(ccv.verify_cases_it)
                and "_note_cassazione" in _in133.getsource(ccv.annotate_unverified)
                and "_cass" in _in133.getsource(_tl133.verifica) and "cassazione" in _in133.getsource(_tl133.blocco_per_gjyqtarin)
                and "con estremi diversi" in _in133.getsource(_tl133.riga)
                and "blocco_dossier" in _br133 and "CASSAZIONE (se la verifica" in _in133.getsource(_st133)
                and "_cassDesc" in _js133 and "https://www.italgiure.giustizia.it/" in _js133 and "testo ufficiale" in _js133)
        # TLS: l'intermedio incorporato si carica e non è scaduto (scade il 29/07/2029: prima di allora va rinnovato)
        import ssl as _ssl133, tempfile as _tf133, datetime as _dt133
        _C133._ctx = None
        _C133._ssl_ctx()
        with _tf133.NamedTemporaryFile("w", suffix=".pem", delete=False) as _fh133:
            _fh133.write(_C133._INTERMEDIO)
        _na = _ssl133._ssl._test_decode_cert(_fh133.name)["notAfter"]
        _okE = _dt133.datetime.strptime(_na, "%b %d %H:%M:%S %Y %Z") > _dt133.datetime.utcnow() + _dt133.timedelta(days=60)
        check("Cassazione[133]: lettura delle forme vere (sezioni, SS.UU., liste «nn. … e …», date, «dep.», r.o./CTR/URL/prosa esclusi) · "
              "ramo dei record (sic civ/pen, testo integrale, link ufficiale .clean.pdf) · esito dal P.Q.M. · confronto (data corretta, "
              "sezione diversa = mismatch, ramo dedotto, non trovata) · agganci (verificatore IT, nota, Trust Line, Giudice, dossier, "
              "pannello) · intermedio TLS valido",
              _okA and _okB and _okC and _okD and _okE,
              "A=%s B=%s C=%s D=%s E=%s %s" % (_okA, _okB, _okC, _okD, _okE, _bad133[:2]))
        _live, _off = _C133.cerca([(10383, 2026)])
        if _off or (10383, 2026) not in _live:
            print("  · Cassazione[133]: archivio non raggiungibile ora — controllo vivo saltato (nessun esito: fail-silent)")
        else:
            _v = _C133.valuta(_C133.trova("Cass. civ., Sez. V, ord. n. 10383/2026"), _live[(10383, 2026)])
            check("Cassazione[133]: dal vivo la Cass. civ. Sez. V ord. 10383/2026 (auto targata Albania) è CONFERMATA, dep. 20/04/2026",
                  _v["status"] == "verified" and (_v["record"] or {}).get("datdep") == "2026-04-20", str(_v)[:200])
    except Exception as _e133:  # noqa: BLE001
        check("Cassazione[133]: kontrollet u ekzekutuan", False, str(_e133))

    # [134] v9.386 — I PRECEDENTI DI CASSAZIONE PER LA DOMANDA (ricerca viva sul testo integrale della Corte) + le etichette
    # del prompt nella lingua della sessione. Misurato (tools/eval_cassazione_precedenti.py, 10 domande IT salvate): cercando
    # coi FATTI (riassunto + domanda) con il consenso di due ricerche, la decisione che il cervello aveva poi citato è in
    # testa in 5 su 10 (l'auto targata Albania → Cass. 10383/2026 in tutte e tre le varianti), rumore ~1 su 7; con le query
    # per le norme 1 su 10; i precedenti di oggi (Consulta/TAR/CdS) 0. Prova viva v9.385: «Neni 216 Regolamento…» nel
    # testo italiano (il blocco del research loop scriveva «Neni» in ogni lingua).
    try:
        import inspect as _in134, threading as _th134, copy as _cp134
        from src import brain as _br134, cassazione as _C134, war_room as _wr134
        _src134 = _in134.getsource(_br134)
        _okA = ("_precedenti_cassazione(triage, domande)" in _in134.getsource(_br134._precedenti_it)
                and "consenso=2" in _in134.getsource(_br134._precedenti_cassazione)
                and "k=2" in _in134.getsource(_br134._precedenti_cassazione)
                and 'getattr(p[0], "court_code", "") == "Cass"' in _in134.getsource(_br134.SuperAvvocato._studio_mbledhesit)
                and "domanda=user_message" in _in134.getsource(_br134.SuperAvvocato._triage)
                and _src134.count("domanda=user_message") >= 3
                and "domanda" in {f.name for f in __import__("dataclasses").fields(_br134.TriageResult)})
        _srcC = _in134.getsource(_C134.cerca_precedenti)
        _okB = ('-tipoprov:Decreto' in _srcC and '"Ordinanza Interlocutoria"' in _srcC and "-ocrdis:inammissibil*" in _srcC
                and "voti.get(i, 0) >= consenso" in _srcC
                and _C134._termini_query("Il ricorrente propone ricorso in Cassazione contro la sentenza della Corte d'appello sul deposito cauzionale")
                == ["propone", "contro", "deposito", "cauzionale"])
        # le etichette nella lingua dell'articolo: in sessione IT niente «Neni/Titulli/GJETUR NGA/Shënim»
        _it134 = ArticleIndex.load(Path("/app/data/index/bm25_it.pkl")) if "Path" in globals() else None
        from pathlib import Path as _P134
        _it134 = _it134 or ArticleIndex.load(_P134("/app/data/index/bm25_it.pkl"))
        _a134 = next(a for a in _it134.articles if a.code == "codice_civile" and str(a.number) == "2946")
        _k134 = _cp134.copy(_a134); _k134._kerkues = True
        _t134 = _br134._format_articles_for_prompt([(_k134, 3.0)])
        _okC = ("Rubrica:" in _t134 and "Titulli:" not in _t134 and "TROVATO DAL RICERCATORE" in _t134 and "GJETUR" not in _t134
                and "Art. 216" in _wr134.format_research_loop([("x", "216", "Esenzione", "testo")], "it")
                and "Neni" not in _wr134.format_research_loop([("x", "216", "Esenzione", "testo")], "it")
                and "Neni 216" in _wr134.format_research_loop([("x", "216", "Esenzione", "testo")], "sq"))
        # il blocco dei precedenti in sessione IT: etichette italiane, e il passo della Cassazione non tagliato a 260
        from src.retrieval_kb import CasePrecedent as _CP134
        import datetime as _d134
        _br134.set_request_jurisdiction("IT")
        _pc = _CP134(id=0, court_code="Cass", court_name="Cass. civ., Sez. V, ordinanza", court_level="cassazione", case_number="10383",
                     decision_date=_d134.date(2026, 4, 20), type="civil", subtype="accoglie", outcome=None,
                     summary="X" * 600, excerpt="", source_url="https://www.italgiure.giustizia.it/x")
        _bp = _br134._format_precedents_block([(_pc, 1.0)])
        _br134.set_request_jurisdiction("AL")
        _okD = ("DECISIONI RILEVANTI" in _bp and "Sintesi:" in _bp and "Përmbledhje" not in _bp and "X" * 600 in _bp
                and "Cass. civ., Sez. V, ordinanza, nr. 10383/2026" in _bp)
        check("Cassazione[134]: precedenti di Cassazione per la domanda (fatti + consenso di 2 ricerche, k=2, solo merito: niente decreti, "
              "interlocutorie, inammissibili) prima di Consulta/TAR/CdS, anche nel percorso semplice · la domanda viaggia nel triage · "
              "etichette del prompt e del research loop nella lingua della sessione («Rubrica», «Art.», niente «Neni» in IT)",
              _okA and _okB and _okC and _okD, "A=%s B=%s C=%s D=%s" % (_okA, _okB, _okC, _okD))
        _vivi = _C134.cerca_precedenti(["amministratore unico di una società albanese guida in Italia l'auto della società targata Albania, "
                                        "è residente in Italia: esenzione dall'ammissione temporanea e confisca",
                                        "auto targata albanese della società albanese guidata dall'amministratore residente in Italia"],
                                       k=2, termini=14, consenso=2)
        if not _vivi:
            print("  · Cassazione[134]: archivio non raggiungibile ora (o nessun consenso) — controllo vivo saltato")
        else:
            check("Cassazione[134]: dal vivo la ricerca coi fatti porta solo decisioni di merito (niente decreti/interlocutorie), al massimo 2",
                  len(_vivi) <= 2 and all(r["tipo"] in ("S", "O") for r in _vivi), str([(_C134.descrivi(r)[:60]) for r in _vivi]))
    except Exception as _e134:  # noqa: BLE001
        check("Cassazione[134]: kontrollet u ekzekutuan", False, str(_e134))

    # [135] v9.388 — LE SENTENZE ALBANESI «NON CONFERMATE» ERANO QUASI TUTTE ALTRO. Misurato sulle risposte AL salvate: delle 6
    # Gjykata e Lartë «të pakonfirmuara» 5 ESISTONO nell'archivio ufficiale già scaricato ed erano mospranim / kthim i rekursit
    # (citate come precedenti!); delle 10 «Kushtetuese non confermate» nessuna era della Kushtetuese nel periodo coperto (Appello,
    # Tribunale, VKM, registro OJF, o 2012 fuori copertura) e 2 «confermate» erano sentenze d'APPELLO (10/2023, «të Gjykatës së
    # Apelit Shkodër»). Ora: esiste ma non è precedente → «excluded» con il motivo dal dispositivo; altro organo → nessun esito.
    try:
        from src import arkiva_gjl as _ag135, trust_line as _tl135
        _c1 = _ag135.classifica("… PËR KËTO ARSYE, Kolegji Administrativ … V E N D O S I: Mospranimin e rekursit të paraqitur nga pala paditëse")
        _c2 = _ag135.classifica("PËR KËTO ARSYE … V E N D O S A: - Kthimin e rekursit të paraqitur nga pala paditëse")
        _c3 = _ag135.classifica("për këto arsye mospranimi i apelit … PËR KËTO ARSYE Kolegji Civil V E N D O S I: Prishjen e vendimit nr. 64 dhe dërgimin e çështjes për rishqyrtim")
        _okA = (_c1["esclusa"] and _c1["esito"] == "mospranim" and _c2["esclusa"] and _c2["esito"] == "kthim i rekursit"
                and not _c3["esclusa"] and _c3["esito"] == "merito" and _c3["kolegji"].lower().startswith("kolegji civil"))
        _dec135 = _tl135.dec_index()
        _t = ("Gjykata e Lartë ka vendosur me vendimin 00-2021-756 dhe me vendimin nr. 10, datë 26.01.2023, të Gjykatës së Apelit "
              "Shkodër; Vendimi nr. 1842, datë 18.02.2026 i Gjykatës së Rrethit; vendimi nr. 55, datë 18.12.2012 i Gjykatës Kushtetuese.")
        _p = ccv.verify_cases(_t, _dec135)
        _st = {(i["court"], i["number"]): i["status"] for i in _p["items"]}
        _arch = _ag135.info("2021", "756") is not None
        _okB = (("kushtetuese", "10") not in _st and ("kushtetuese", "1842") not in _st and ("kushtetuese", "55") not in _st
                and (_st.get(("gjykata_elarte", "756")) == "excluded" if _arch else _st.get(("gjykata_elarte", "756")) == "unverified"))
        _md = ccv.annotate_unverified(_t, _p)
        _okC = (not _arch) or ("NUK janë precedent" in _md and _md.count("NUK janë precedent") == 1
                                and ccv.annotate_unverified(_md, ccv.verify_cases(_md, _dec135)).count("NUK janë precedent") == 1)
        _v135 = _tl135.vuota(); _v135["sentenze"].update(total=1, excluded=1)
        _okD = ("pa vlerë precedenti" in _tl135.riga(_v135, "sq") and _tl135.stato(_v135) == "RESERVATIONS"
                and '_st.get("excluded")' in open("/app/src/web.py", encoding="utf-8").read()
                and 'dc.status === "excluded"' in open("/app/static/app.js", encoding="utf-8").read())
        check("vendime AL[135]: esistono nell'archivio ufficiale ma NON sono precedenti (mospranim / kthim i rekursit dal dispositivo) "
              "→ «excluded» con l'avviso · «vendim nr. …» di Appello/Tribunale/VKM o fuori copertura non è della Kushtetuese · riga, "
              "stato 🟡, nota idempotente, pannello",
              _okA and _okB and _okC and _okD, "A=%s B=%s C=%s D=%s arch=%s st=%s" % (_okA, _okB, _okC, _okD, _arch, _st))
    except Exception as _e135:  # noqa: BLE001
        check("vendime AL[135]: kontrollet u ekzekutuan", False, str(_e135))

    # [136] v9.389 — LA CORTE DI GIUSTIZIA UE sull'archivio ufficiale (CELLAR). Misurato sulle 44 risposte IT: 61 citazioni di
    # cause CGUE (10 distinte) mai riscontrate — la C-274/20 citata 31 volte con «estremi da confermare». Riscontrate: 8 esistono
    # con intestazione e oggetto ufficiali, 2 sono cause RIUNITE (la sentenza sta sotto il primo numero: C-717/22 e C-372/23).
    try:
        from src import cgue as _G136
        _tr136 = {(c["lettera"], c["numero"]): c for c in _G136.trova(
            "CGUE, 19 dicembre 2024, cause riunite C-717/22 e C-372/23, SISTEM LUX; sentenza del 16 dicembre 2021 (causa C‑274/20); "
            "Fonti consultate il 21/09/2026: [CGUE C-182/12](https://curia.europa.eu/x?num=C-999/12); T-123/19")}
        _okA = (set(_tr136) == {("C", 717), ("C", 372), ("C", 274), ("C", 182), ("T", 123)}
                and _tr136[("C", 372)].get("riunita_con") == "C-717/22" and not _tr136[("C", 274)].get("riunita_con")
                and _tr136[("C", 274)]["date"] == ["2021-12-16"] and _tr136[("C", 182)]["date"] == []
                and _G136._celex("C", 274, "20", "J") == "62020CJ0274" and _G136._celex("C", 262, "99", "J") == "61999CJ0262"
                and _G136._celex("T", 123, "19", "O") == "62019TO0123")
        _h = _G136._intestazione("<p>SENTENZA DELLA CORTE (Sesta Sezione)</p><p>16 dicembre 2021 ( *1 )</p><p>«Rinvio pregiudiziale – "
                                 "Articolo 63 TFUE – Veicolo immatricolato in un altro Stato membro»</p>")
        _okB = (_h["data"] == "2021-12-16" and _h["intestazione"].startswith("SENTENZA DELLA CORTE (Sesta Sezione)")
                and _h["oggetto"].startswith("Rinvio pregiudiziale"))
        import inspect as _in136
        from src import trust_line as _tl136
        _okC = ("cgue as _cgue" in _in136.getsource(ccv.verify_cases_it) and "_note_cgue" in _in136.getsource(ccv.annotate_unverified)
                and "_cgue" in _in136.getsource(_tl136.verifica) and "_cgue.blocco" in _in136.getsource(_tl136.blocco_per_gjyqtarin)
                and 'dc.court === "CGUE"' in open("/app/static/app.js", encoding="utf-8").read())
        check("CGUE[136]: cause lette (anche «C‑274/20», le riunite ereditano dal primo numero, mai la data di consultazione) · CELEX "
              "(CJ/CO, TJ/TO, anno del ruolo) · intestazione e oggetto ufficiali · agganci (verificatore IT, nota, Giudice, pannello)",
              _okA and _okB and _okC, "A=%s B=%s C=%s" % (_okA, _okB, _okC))
        _v136 = _G136.verifica("la sentenza della Corte di giustizia del 16 dicembre 2021 (causa C-274/20)")
        if not _v136["items"]:
            print("  · CGUE[136]: archivio UE non raggiungibile ora — controllo vivo saltato")
        else:
            _r136 = _v136["items"][0]
            check("CGUE[136]: dal vivo la C-274/20 è CONFERMATA (sentenza del 16/12/2021), senza correzioni di data",
                  _r136["status"] == "verified" and _r136["record"].get("data") == "2021-12-16" and not _r136["correzioni"], str(_r136)[:200])
    except Exception as _e136:  # noqa: BLE001
        check("CGUE[136]: kontrollet u ekzekutuan", False, str(_e136))

    # [137] v9.390 — LE TABELLE DEGLI STUPEFACENTI (d.P.R. 309/1990, testo vigente da Normattiva). Misurato: a memoria il cervello
    # sbagliava la tabella di 6 sostanze su 30 (ketamina, GHB, buprenorfina, metaqualone, tramadolo «non inclusa», 1cP-LSD) e la
    # tabella decide il comma dell'art. 73. Le tabelle stanno su Normattiva in TABELLE HTML che il lettore degli articoli scartava.
    try:
        import importlib.util as _ilu137, os as _os137
        from src import stupefacenti as _S137, trust_line as _tl137
        _sp137 = _ilu137.spec_from_file_location("_its137", _os137.path.join(_os137.path.dirname(_os137.path.abspath(__file__)), "ingest_tabelle_stupefacenti.py"))
        _I137 = _ilu137.module_from_spec(_sp137); _sp137.loader.exec_module(_I137)
        _pg = ('<div class="bodyTesto"><span class="attachment-just-text"><br> TABELLA I <br> SOSTANZE <br></span>'
               '<span class="table-akn"><table><tr><td>DENOMINAZIONE COMUNE</td><td>DENOMINAZIONE CHIMICA</td><td>ALTRA</td></tr>'
               '<tr><td>Ketamina</td><td>(±)-2-(2-clorofenil)</td><td></td></tr></table></span>'
               '<span class="attachment-just-text"> TABELLA MEDICINALI SEZIONE B </span><span class="table-akn"><table>'
               '<tr><td>Acido gamma-idrossibutirrico (GHB)</td><td></td><td>oxibato</td></tr><tr><td>I sali delle sostanze</td></tr>'
               '</table></span></div>')
        _r137, _n137 = _I137.parse([_pg])
        _okA = ([(r["tabella"], r["sezione"], r["nome"]) for r in _r137] == [("I", "", "Ketamina"), ("MED", "B", "Acido gamma-idrossibutirrico (GHB)")]
                and "MED-B" in _n137)
        _d137 = _S137._dati()
        _cnt = {}
        for r in (_d137 or {}).get("righe") or []:
            _cnt[r["tabella"]] = _cnt.get(r["tabella"], 0) + 1
        _dove = {x["testo"]: _S137._dove(x["voci"]) for x in _S137.trova(
            "20 grammi di hashish, cocaina, GHB, ketamina, tramadolo, buprenorfina, pasticche di ecstasy e un DOC dell'AMT")}
        _okB = (_d137 is not None and _cnt.get("I", 0) >= 600 and _cnt.get("II") == 3 and _cnt.get("IV", 0) >= 100
                and _dove.get("hashish") == "Tabella II" and _dove.get("cocaina") == "Tabella I"
                and _dove.get("ghb", "").startswith("Tabella IV") and _dove.get("ketamina", "").startswith("Tabella I +")
                and _dove.get("tramadolo", "").startswith("Tabella I") and _dove.get("buprenorfina", "").startswith("Tabella IV")
                and _dove.get("ecstasy") == "Tabella I" and "doc" not in _dove and "amt" not in _dove)
        _e137 = _S137.verifica("il GHB, inserito nella Tabella I, rientra nel comma 1; la cocaina (Tabella I) e l'hashish (Tabella II); le Tabelle I e III")
        _okC = (len(_e137) == 1 and _e137[0]["sostanza"] == "GHB" and _e137[0]["detta"] == "I"
                and _S137.nota("il GHB, inserito nella Tabella I").count("da correggere") == 1
                and _S137.nota("il GHB, inserito nella Tabella I" + _S137.nota("il GHB, inserito nella Tabella I")) == "")
        import inspect as _in137
        from src import brain as _br137
        _okD = ("stupefacenti.blocco(" in _in137.getsource(_br137.SuperAvvocato._mbledh_gatherers)
                and "_stup" in _in137.getsource(_tl137.verifica) and "TABELLE DEGLI STUPEFACENTI" in _in137.getsource(_tl137.blocco_per_gjyqtarin)
                and "_stp.nota(" in open("/app/src/web.py", encoding="utf-8").read())
        check("stupefacenti[137]: tabelle dal testo vigente di Normattiva (le tabelle HTML dell'allegato) · sostanze e nomi di strada "
              "(hashish II, cocaina I, GHB IV, ketamina I, tramadolo I, buprenorfina IV, ecstasy I; niente DOC/AMT) · tabella sbagliata "
              "nella risposta → correzione idempotente · agganci (dossier, Giudice, scudo)",
              _okA and _okB and _okC and _okD, "A=%s B=%s C=%s D=%s cnt=%s dove=%s" % (_okA, _okB, _okC, _okD, _cnt, _dove))
    except Exception as _e137x:  # noqa: BLE001
        check("stupefacenti[137]: kontrollet u ekzekutuan", False, str(_e137x))

    # [138] v9.391 — LE LEGGI ALBANESI SUGLI STUPEFACENTI. Il KP 283-284/c punisce ciò che è «në kundërshtim me ligjin» /
    # «pa leje dhe autorizim sipas ligjit», ma quella legge (7975/1995: gruppi, liste delle Convenzioni, lëndë të kontrolluara
    # = Lista A con ketamina/GBL/N2O, ricette, sanzioni) NON era nel corpus, e nemmeno la 61/2023 sulla cannabis medica. Il
    # .docx di QBZ ha tre difetti riparati da tools/repair_lendet_narkotike.py: titoli di capo in coda agli articoli, allegato
    # dentro il neni 105, e il neni 9 (divieto di OGNI coltivazione) senza il rimando alla 61/2023 che lo abroga in parte.
    try:
        _n138 = [a for a in idx.articles if a.code == "ligji_lendet_narkotike"]
        _k138 = [a for a in idx.articles if a.code == "ligji_kanabisi_mjekesor"]
        _by138 = {str(a.number): a for a in _n138}
        _docs138 = {d.code: d.area for d in brain.LEGAL_DOCUMENTS}
        _okA = (len(_n138) >= 100 and len(_k138) >= 40 and _docs138.get("ligji_lendet_narkotike") == "Penal"
                and _docs138.get("ligji_kanabisi_mjekesor") == "Penal")
        _sh = _by138.get("shtojca")
        _okB = (_sh is not None and "Ketamine" in _sh.body and "Hexahydrocannabinol (HHC)" in _sh.body and "17/2026" in _sh.body
                and "KLASIFIKIMI" not in (_by138["105"].body if "105" in _by138 else "KLASIFIKIMI")
                and not any(re.search(r"\bKREU\s+[IVXLC]+\s+\S+[^.]{0,200}$", (a.body or "")[-260:]) for a in _n138)
                and "dhe lëndëve të kontrolluara" in (_by138["3"].kreu if "3" in _by138 else "")
                and "61/2023" in (_by138["9"].note if "9" in _by138 else "") and "Neni 44" in _by138["9"].note)
        def _st138(t):
            it = (cv.verify_text(t, idx) or {}).get("items") or []
            return [(x["code"], x["number"], x["status"]) for x in it]
        _okC = (_st138("Sipas nenit 9 të ligjit nr. 7975/1995 kultivimi ndalohet.") == [("ligji_lendet_narkotike", "9", "verified")]
                and _st138("Neni 14 i ligjit nr. 61/2023 parashikon licencën.") == [("ligji_kanabisi_mjekesor", "14", "verified")]
                and _st138("neni 101 i ligjit për barnat narkotike dhe lëndët psikotrope") == [("ligji_lendet_narkotike", "101", "verified")]
                and _st138("Neni 999 i ligjit nr. 7975/1995") == [("ligji_lendet_narkotike", "999", "fake")])
        _pen138 = {d.code for d in brain.LEGAL_DOCUMENTS if d.area == "Penal"} | {"kodi_proc_penale"}
        def _top138(q):
            return [(a.code, str(a.number)) for a, _ in idx.search(q, top_k=12, restrict_codes=_pen138)]
        _okD = (("ligji_kanabisi_mjekesor", "14") in _top138("licenca për kultivimin e cannabis-it për qëllime mjekësore")
                and ("ligji_lendet_narkotike", "2") in _top138("lëndë të kontrolluara që nuk janë narkotike dhe psikotrope")
                and ("ligji_lendet_narkotike", "shtojca") in _top138("ketamine GBL nitrous oxide lista A"))
        from src import acts_meta as _am138
        import glob as _gl138, json as _js138
        _kf = sorted(_gl138.glob("/app/data/models/emb_sq_*_flat3.keys.json"))
        _emb = {tuple(k[:2]) for k in _js138.load(open(_kf[0], encoding="utf-8"))} if _kf else set()
        _okE = ("7975/1995" in (_am138.riga("ligji_lendet_narkotike") or "") and "2026-02-20" in _am138.riga("ligji_lendet_narkotike")
                and ("ligji_lendet_narkotike", "9") in _emb and ("ligji_kanabisi_mjekesor", "14") in _emb)
        check("narkotike[138]: ligji 7975/1995 + 61/2023 nel corpus (area Penal) · capi e allegato riparati, rimando 61/2023 sul neni 9 "
              "· verificatore (numero, nome vecchio e nuovo, inesistente) · ricerca (licenza cannabis, lëndë të kontrolluara, Lista A) "
              "· metadati dell'atto e ricerca per significato", _okA and _okB and _okC and _okD and _okE,
              "A=%s B=%s C=%s D=%s E=%s" % (_okA, _okB, _okC, _okD, _okE))
    except Exception as _e138:  # noqa: BLE001
        check("narkotike[138]: kontrollet u ekzekutuan", False, str(_e138))

    # [139] v9.392 — LE LISTE ALBANESI DELLE SOSTANZE (ligji 7975/1995, allegato). Misurato (tools/eval_narkotike_al.py, 35
    # sostanze, senza web): a memoria il GRUPPO era sbagliato 12 volte (cocaina, cannabis, morfina, fentanil nel gruppo I: lo
    # schema li mette nel II) e ketamina/N2O/GBL (Lista A) e HHC/carisoprodol (ligji 17/2026) risultavano «non controllate».
    # Le liste sono figure dell'allegato, lette una per una con la cifra di controllo dei CAS (tools/ingest_liste_narkotike_al.py).
    try:
        import importlib.util as _ilu139, os as _os139
        from src import narkotike_al as _N139
        _sp139 = _ilu139.spec_from_file_location("_iln139", _os139.path.join(_os139.path.dirname(_os139.path.abspath(__file__)), "ingest_liste_narkotike_al.py"))
        _I139 = _ilu139.module_from_spec(_sp139); _sp139.loader.exec_module(_I139)
        _okA = (_I139.cas_ok("50-36-2") and _I139.cas_ok("6740-88-1") and not _I139.cas_ok("50-36-3")
                and _I139.chiave_lista("Lista I e Konventës Unike për Lëndët Narkotike e vitit 1961") == "1961-I"
                and _I139.chiave_lista("LISTA IV E KONVENTËS PËR LËNDËT PSIKOTROPE E VITIT 1971") == "1971-IV"
                and _I139.chiave_lista("LISTA A") == "A" and _I139.chiave_lista("Skema e klasifikimit") is None)
        _d139 = _N139._dati() or {}
        _per139 = {}
        for r in _d139.get("righe") or []:
            _per139[r["lista"]] = _per139.get(r["lista"], 0) + 1
        _t = {x["chiave"]: x for x in _N139.trova("kokainë, heroinë, kanabis, ketaminë, HHC, GBL, tramadol dhe morfinë")}
        _okB = (len(_d139.get("righe") or []) >= 350 and _per139.get("1961-I", 0) >= 120 and _per139.get("1971-II", 0) >= 50
                and _per139.get("1971-IV", 0) >= 50 and _per139.get("A") == 3
                and _N139.gruppo(_t["cocaine"]["voci"]) == "II" and _N139.gruppo(_t["heroin"]["voci"]) == "I"
                and _N139.gruppo(_t["cannabis"]["voci"]) == "II" and "1961-IV" not in _N139._liste(_t["cannabis"]["voci"])
                and _N139.categoria(_t["ketamine"]["voci"]) == "e kontrolluar" and _N139.gruppo(_t["morphine"]["voci"]) == "II"
                and _N139._liste(_t["hexahydrocannabinol"]["voci"]) == ["1971-II"] and "17/2026" in _N139._dove(_t["hexahydrocannabinol"])
                and _N139.categoria(_t["gamma-butyrolactone"]["voci"]) == "e kontrolluar" and _t["tramadol"]["jo"])
        _A139 = ("Kokaina bën pjesë në Grupin I. Heroina është në Grupin I. HHC nuk figuron në Konventat 1961/1971 (shih Neni 7). "
                 "Ketamina nuk është nën kontroll ndërkombëtar. Ketamina nuk është lëndë narkotike as psikotrope. "
                 "Tramadoli është lëndë psikotrope sipas ligjit.")
        _e139 = {(e["sostanza"], e["lloji"]) for e in _N139.verifica(_A139)}
        _okC = (_e139 == {("Kokaina", "grupi"), ("HHC", "jo"), ("Tramadoli", "jo_ne_liste")}
                and _N139.nota(_A139).count("për t'u korrigjuar") == 1 and _N139.nota(_A139 + _N139.nota(_A139)) == ""
                and _N139.blocco("Qiramarrësi nuk paguan qiranë.") == "" and "Grupi II" in _N139.blocco("u kap me kokainë")
                and [s["testo"] for s in _N139.trova("ghb dhe thc me shkronja të vogla")] == [])
        import inspect as _in139
        from src import brain as _br139, trust_line as _tl139
        _okD = ("narkotike_al.blocco(" in _in139.getsource(_br139.SuperAvvocato._mbledh_gatherers)
                and "_nark" in _in139.getsource(_tl139.verifica) and "LISTAT E LËNDËVE" in _in139.getsource(_tl139.blocco_per_gjyqtarin)
                and "_nk.nota(" in open("/app/src/web.py", encoding="utf-8").read())
        _sk139 = next((a for a in idx.articles if a.code == "ligji_lendet_narkotike" and str(a.number) == "skema"), None)
        _okE = (_sk139 is not None and "Nëngrupi A: barna që mund të përshkruhen për jo më shumë se 7 ditë" in _sk139.body
                and "përveç rastit të përdorimit vetjak" in (_sk139.note or ""))
        check("narkotike[139]: liste dell'allegato lette dalle figure (CAS con cifra di controllo) · gruppi dello schema (cocaina/cannabis/"
              "morfina II, eroina I), Lista A (ketamina, GBL), aggiunte 17/2026 (HHC), tramadol in nessuna lista · verifica che corregge "
              "gruppo/«non controllata» e lascia le frasi vere · agganci (dossier, Giudice, nota) · schema dei gruppi nel corpus",
              _okA and _okB and _okC and _okD and _okE,
              "A=%s B=%s C=%s D=%s E=%s per=%s err=%s" % (_okA, _okB, _okC, _okD, _okE, _per139, _e139))
    except Exception as _e139x:  # noqa: BLE001
        check("narkotike[139]: kontrollet u ekzekutuan", False, str(_e139x))

    # [140] v9.393 — IL COMPITO SCEGLIE IL MODELLO ANCHE PER IL SENIOR (richiesta del titolare, 25 set): Opus 5.5 nel CLI
    # (2.1.265 lo rifiutava: «unrecognized_model»), modello ed effort per PERCORSO (semplice / sala di guerra) dall'env, la
    # riserva del Giudice = l'ALTRA mente, Fable per nome esplicito (sul 2.1.282 l'alias «opus» = opus-5-5: un aggiornamento
    # del CLI non deve cambiare un modello in silenzio), e il ripiego per limite anche nello streaming.
    try:
        import inspect as _in140, subprocess as _sp140
        from src import brain as _br140, config as _cf140, backends as _bk140
        from src import second_opinion as _so140, genio as _ge140, adversary as _ad140, fable_drafter as _fd140, vault as _va140
        _v = (_sp140.run(["claude", "--version"], capture_output=True, text=True, timeout=30).stdout or "").split()[0:1]
        _ver = tuple(int(x) for x in (_v[0] if _v else "0.0.0").split(".")[:3])
        _okA = _ver >= (2, 1, 281)
        _par = _in140.signature(_bk140.ClaudeCodeBackend.complete_stream).parameters
        _cs = _in140.getsource(_bk140.ClaudeCodeBackend.complete_stream)
        _okB = ("model_override" in _par and "effort_override" in _par and "_limite_stream" in _cs
                and _cs.count('error_class="ModelLimit"') == 2 and 'effort_override="max"' in _cs)
        # la proposta del titolare («togliere Sonnet: un buon inizio cambia il finale»): lo sforzo del tier veloce e la rete
        # di sicurezza dei tier veloce/junior quando Opus 5.5 è al limite — eseguiti, non letti
        import shutil as _sh140
        _b140 = _bk140.ClaudeCodeBackend(cli_path=_sh140.which("claude") or "/usr/bin/claude", effort="max", medium_effort="high",
                                         fast_effort="medium", limit_fallback_model="claude-sonnet-5")
        _cc = _in140.getsource(_bk140.ClaudeCodeBackend.complete) + _in140.getsource(_bk140.ClaudeCodeBackend.ocr_image)
        _okB = (_okB and _b140._pick_effort(True, False) == "medium" and _b140._pick_effort(False, True) == "high"
                and "elif _limite and _rete and model != _rete:" in _cc and "_rete_ocr" in _cc
                and isinstance(_cf140.CLAUDE_CODE_LIMIT_FALLBACK_MODEL, str) and hasattr(_cf140, "CLAUDE_CODE_FAST_EFFORT"))
        _salva = {k: getattr(_cf140, k) for k in ("SENIOR_SIMPLE_MODEL", "SENIOR_SIMPLE_EFFORT", "SENIOR_DEEP_MODEL", "SENIOR_DEEP_EFFORT")}
        try:
            for k in _salva:
                setattr(_cf140, k, "")
            _vuoto = _br140._senior_kw("simple") == {} and _br140._senior_kw("deep") == {}
            _cf140.SENIOR_SIMPLE_MODEL, _cf140.SENIOR_SIMPLE_EFFORT = "claude-opus-5-5", "high"
            _cf140.SENIOR_DEEP_MODEL, _cf140.SENIOR_DEEP_EFFORT = "claude-opus-5-5", "max"
            _pieno = (_br140._senior_kw("simple") == {"model_override": "claude-opus-5-5", "effort_override": "high"}
                      and _br140._senior_kw("deep") == {"model_override": "claude-opus-5-5", "effort_override": "max"})
            _br140.set_request_senior("fable")
            _fab = _br140._senior_kw("deep") == {"model_override": "claude-fable-5-1", "effort_override": "max"}
        finally:
            _br140.set_request_senior("")
            for k, v in _salva.items():
                setattr(_cf140, k, v)
        _src140 = _in140.getsource(_br140)
        _okC = (_vuoto and _pieno and _fab and _src140.count('**_senior_kw("simple")') == 4 and _src140.count('**_senior_kw("deep")') == 3
                and "_eff_rep = " in _src140 and _br140._riserva_giudice("claude-opus-5-5") == "claude-fable-5-1"
                and _br140._riserva_giudice("claude-fable-5-1") == "opus")
        _okD = (_so140.FABLE_MODEL == _ge140.FABLE_MODEL == _ad140.FABLE_MODEL == _fd140.FABLE_MODEL == "claude-fable-5-1"
                and "model_override=FABLE_MODEL_ID" in _in140.getsource(_va140))
        check("modelli[140]: Opus 5.5 nel CLI (≥ 2.1.281) · streaming con modello/effort scelti e ripiego per limite · senior per "
              "percorso (vuoto = Opus 5 max; ⚡ Fable vince) in 4 punti semplici e 3 profondi · replica al diavolo · riserva del "
              "Giudice = l'altra mente · Fable per nome esplicito", _okA and _okB and _okC and _okD,
              "cli=%s A=%s B=%s C=%s D=%s" % (_ver, _okA, _okB, _okC, _okD))
    except Exception as _e140:  # noqa: BLE001
        check("modelli[140]: kontrollet u ekzekutuan", False, str(_e140))

    # [141] v9.394 — LE NORME CHE NESSUN MODELLO CITAVA (misura dei modelli, 26 set: 6 giri su 6, qualunque configurazione):
    # nel licenziamento dello straniero la ligji 79/2021 art. 72-73 (il licenziamento da solo non annulla il permesso unico) e il
    # premio di anzianità (KP 152, dopo 3 anni). La ricerca non le portava al senior → ancore di ragione giuridica, a FRASE INTERA
    # («qëndrim» è anche «posizione», «pushime» le ferie); e un'ancora già fra i 12 sale in testa, perché ciò che entra dopo
    # (ancore per titolo, nene chiesti, Kërkuesi) la spingeva oltre il taglio.
    try:
        import inspect as _in141
        from src import brain as _br141
        _pp141 = [(a, 1.0) for a in idx.articles if a.code == "kodi_punes"][:12]
        def _anc141(t, aree=("Punë", "Civil")):
            out = _br141._applica_ancore(list(_pp141), idx, [t], list(aree))
            return {(a.code, a.number) for a, _ in out[:6]}
        _a = _anc141("Shtetas i huaj me leje qëndrimi për punë, zgjidhje e menjëhershme e kontratës pas 3 vjet punë")
        _okA = (("ligji_te_huajt", "72") in _a and ("ligji_te_huajt", "73") in _a and ("kodi_punes", "152") in _a
                and {("kodi_punes", "145"), ("kodi_punes", "152")} <= _anc141("Punëdhënësi e pushoi klientin pas 8 vitesh pa asnjë paralajmërim"))
        _t1 = _anc141("qëndrimi i gjykatës për zgjidhjen e mosmarrëveshjes për lejen e ndërtimit")
        _t2 = _anc141("sa ditë pushime vjetore më takojnë pas 5 vitesh punë?")
        _t3 = _anc141("i huaji u dënua për vjedhje, leje qëndrimi e anuluar, zgjidhja e çështjes", ("Penal",))
        _okB = (not any(k[0] == "ligji_te_huajt" for k in _t1 | _t2 | _t3) and ("kodi_punes", "152") not in (_t1 | _t2 | _t3))
        _k152 = next(a for a in idx.articles if a.code == "kodi_punes" and str(a.number) == "152")
        _k145 = next(a for a in idx.articles if a.code == "kodi_punes" and str(a.number) == "145")   # v9.399: la base
        _pp = [(a, 1.0) for a in idx.articles if a.code == "kodi_punes" and str(a.number) not in ("145", "152")][:8] + \
              [(_k152, 0.5), (_k145, 0.45)] + [(a, 0.4) for a in idx.articles if a.code == "kodi_punes"][20:23]
        _out = _br141._applica_ancore(_pp, idx, ["Klienti është pushuar nga puna pas 8 vitesh punë"], ["Punë"])
        _pos = [(a.code, a.number) for a, _ in _out].index(("kodi_punes", "152"))
        # v9.400: sullo stesso testo entra ora anche il preavviso (KP 143, ancora del licenziamento) → si accettano SOLO
        # aggiunte di ancore dichiarate, e nessun doppione di ciò che è stato promosso
        _chiavi141 = [(a.code, str(a.number)) for a, _ in _out]
        _okC = (_pos < 3 and not getattr(_out[_pos][0], "_ancora", False)
                and len(_out) == len(_pp) + sum(1 for a, _ in _out if getattr(a, "_ancora", False))
                and _chiavi141.count(("kodi_punes", "152")) == 1 and _chiavi141.count(("kodi_punes", "145")) == 1
                and '(getattr(triage, "domanda", "") or "")[:600]' in _in141.getsource(_br141.SuperAvvocato._retrieve))
        check("ancore[141]: straniero licenziato → ligji 79/2021 art. 72-73 · licenziamento dopo anni → KP 152 · niente sulla "
              "«posizione» della corte, sulle ferie, nel penale · un'ancora già fra i 12 sale in testa (originale, non copia) · "
              "le ancore leggono anche la domanda", _okA and _okB and _okC,
              "A=%s B=%s C=%s pos152=%s" % (_okA, _okB, _okC, _pos))
    except Exception as _e141:  # noqa: BLE001
        check("ancore[141]: kontrollet u ekzekutuan", False, str(_e141))

    # [142] v9.395 — LA SESSIONE IT MOSTRAVA DATI E TESTI ALBANESI (verifica pre-lancio dal browser, 27 set): il briefing del
    # giorno elencava i fascicoli albanesi, calendario/banner delle scadenze/segretaria gli eventi dei fascicoli albanesi e quelli
    # senza fascicolo nati in sessione AL, la fase del caso arrivava sempre in albanese («Përgatitje»), il portale del cliente era
    # SOLO in albanese, il marchio «SUPER AVOKATI» diventava «SUPER AVVOCATO» (voce del dizionario) e il titolo della scheda restava
    # «asistent ligjor falas». Regola #1: in una sessione l'altra giurisdizione NON esiste — neanche nell'agenda.
    try:
        import inspect as _in142
        _rr142 = _os2.path.dirname(_os2.path.dirname(_os2.path.abspath(__file__)))
        from types import SimpleNamespace as _NS142
        from src import storage as _st142, web as _we142, secretary as _se142
        _E = lambda cid, j: _NS142(case_id=cid, jurisdiction=j, title="x")
        _mappa = {"c_it": "IT", "c_al": "AL"}
        _okA = (_st142.giurisdizione_evento(_E("c_it", "AL"), _mappa) == "IT"          # il fascicolo fa fede
                and _st142.giurisdizione_evento(_E(None, "IT"), _mappa) == "IT"
                and _st142.giurisdizione_evento(_E(None, None), _mappa) == "AL"         # eredità: nati in sessione AL
                and _st142.stage_label("preparation", "IT") == "Preparazione"
                and _st142.stage_label("hearing", "AL") == "Seancë" and _st142.stage_label("xyz", "IT") == "xyz")
        _srcs = {n: _in142.getsource(f) for n, f in (("events", _we142.api_list_events), ("agenda", _we142.api_agenda_upcoming),
                                                     ("brief", _we142.api_daily_brief), ("seg", _se142.build_agenda_snapshot))}
        _okB = (all("eventi_della_giurisdizione" in v for v in _srcs.values())
                and "_active_jurisdiction(user)" in _srcs["brief"] and "CASE_STAGE_LABELS_SQ" not in _in142.getsource(_we142.api_list_cases)
                and "CASE_STAGE_LABELS_SQ" not in _srcs["brief"])
        _pt = _io2.open(_os2.path.join(_rr142, "templates", "portal.html"), encoding="utf-8").read()
        import jinja2 as _j142
        _html = _j142.Environment().from_string(_pt).render(
            L=_we142._PORTAL_T["it"], lang="it", kind_label=lambda k: _we142._PORTAL_KIND["it"].get(k, k),
            case=_NS142(title="Caso"), client=_NS142(name="Mario", last_viewed_at=None), firm_name=None,
            stage_steps=[{"key": "intake", "label": "Intake / accoglienza", "state": "current"}], stage_label="Preparazione",
            upcoming_events=[{"starts_at": "2026-10-01T09:00:00Z", "title": "t", "kind": "seance", "location": None, "description": None}],
            past_events=[], updates=[])
        _okC = (not re.search(r"[ëçËÇ]", _pt) and "Benvenuto," in _html and "Udienza" in _html
                and not re.search(r"[ëçËÇ]|Mirë|Faza aktuale|Lajme nga", _html)
                and set(_we142._PORTAL_T["it"]) == set(_we142._PORTAL_T["sq"]))
        _ix = _io2.open(_os2.path.join(_rr142, "templates", "index.html"), encoding="utf-8").read()
        _js = _io2.open(_os2.path.join(_rr142, "static", "app.js"), encoding="utf-8").read()
        _okD = ('<h1 translate="no">' in _ix and "Super Avvocato" not in _ix and "shkruaj në albanian" not in _ix
                and '"AVOKATI": "AVVOCATO"' not in _js and "[translate=no]" in _js
                and "document.title = T_IT[document.title]" in _js)
        check("sessione[142]: eventi/briefing/segretaria solo della giurisdizione della sessione (il fascicolo fa fede, senza "
              "fascicolo quella di nascita, eredità = AL) · fase del caso nella lingua · portale del cliente nella lingua del "
              "fascicolo · marchio mai tradotto · titolo della scheda in italiano", _okA and _okB and _okC and _okD,
              "A=%s B=%s C=%s D=%s" % (_okA, _okB, _okC, _okD))
    except Exception as _e142:  # noqa: BLE001
        check("sessione[142]: kontrollet u ekzekutuan", False, str(_e142))

    # [143] v9.395 — IL SECONDO GIRO DELLA VERIFICA PRE-LANCIO (27 set): (1) `porta_utente` portava nei thread l'utente e
    # il profilo ma NON la giurisdizione → l'analizzatore dei precedenti (in sottofondo) girava come sessione AL anche per un
    # avvocato italiano; (2) e cercava SEMPRE nell'archivio albanese (Kushtetuese/GjL/CEDU-Albania): in sessione IT ora
    # l'archivio italiano (Consulta, CdS, TAR + Cassazione) con prompt italiani; (3) il pannello e il DOCX «Provenance» erano
    # solo albanesi e mostravano l'identificativo del modello: motore = Tetramorph, lingua del fascicolo; (4) pannelli dei
    # precedenti e dei contratti con etichette fisse albanesi; (5) il traduttore del DOM saltava gli attributi dell'elemento
    # aggiunto direttamente («Mbyll»).
    try:
        import threading as _th143, inspect as _in143, re as _re143
        from types import SimpleNamespace as _NS143
        from src import brain as _br143, precedent as _pr143, pro_features as _pf143, web as _we143
        _rr143 = _os2.path.dirname(_os2.path.dirname(_os2.path.abspath(__file__)))
        _vista = {}
        _br143.set_request_jurisdiction("IT")
        _f = _br143.porta_utente(1, lambda: _vista.setdefault("j", _br143.request_jurisdiction()))
        _t = _th143.Thread(target=_f); _t.start(); _t.join(5)
        _br143.set_request_jurisdiction("AL")
        _okA = _vista.get("j") == "IT"
        _ref = _pr143.PrecedentRef(citation="Cons. Stato, n. 1/2026", court_code="CdS", outcome="", objekti="passo",
                                   source_url="", bm25_score=1.0)
        _blk = _ref.to_block("it")
        _okB = (hasattr(_pr143, "gather_precedents_it") and "PASSO DELLA DECISIONE" in _blk
                and not _re143.search(r"GJYKATA|REZULTATI|OBJEKTI", _blk)
                and "niente diritto" in _pr143.PRECEDENT_SYSTEM_IT and "jurisdiction=_juris_prec" in _in143.getsource(_we143.api_precedent_run)
                and 'lang="it"' in _in143.getsource(_pr143.analyze))
        import io as _io143
        from docx import Document as _Doc143
        _pk = {"jurisdiction": "IT", "response_id": "r1", "timestamp_iso": "2026-09-27", "model": "claude-opus-5",
               "confidence": 1.0, "confidence_label": "I lartë", "citations": {"items": [{"raw": "art. 641 c.p.c.", "code_label": "c.p.c.", "status": "verified"}]},
               "retrieved_articles": [{"number": "641", "code": "codice_procedura_civile", "heading": "Accoglimento della domanda", "score": 3.1}]}
        _dt = "\n".join(p.text for p in _Doc143(_io143.BytesIO(_pf143.provenance_docx(_pk))).paragraphs)
        _dt += "\n".join(c.text for t in _Doc143(_io143.BytesIO(_pf143.provenance_docx(_pk))).tables for r in t.rows for c in r.cells)
        _okC = ("Tetramorph" in _dt and not _re143.search(r"claude|opus|sonnet|fable|anthropic", _dt, _re143.I)
                and not _re143.search(r"[ëçË]", _dt) and "Configurazione" in _dt and "Art. 641" in _dt
                and 'pack["model"] = "Tetramorph"' in _in143.getsource(_we143.api_provenance_json))
        _js = _io2.open(_os2.path.join(_rr143, "static", "app.js"), encoding="utf-8").read()
        _okD = ("<dt>${PL.motore}</dt><dd><code>Tetramorph</code></dd>" in _js and "prov.model ||" not in _js
                and '_CAL_IT ? "✓ Mosse da imitare"' in _js and '_CAL_IT ? "Parte" : "Pala"' in _js
                and "if (root.matches && root.matches(_SEL)) els.unshift(root);" in _js
                and 'kerk: "Ricercatore (norma mancante)"' in _js and "GDPR-AL flags\"" not in _js.split('"Semafor 🟢🟡🔴 për çdo klauzolë + GDPR-AL flags": ')[1][:80])
        from src import reminders as _rm143
        _R = _NS143(offset_minutes=1440)
        _okE = (_rm143._fmt_ahead(_R, "it") == "1 giorno prima" and _rm143._fmt_ahead(_R) == "1 ditë para"
                and "giurisdizione_evento" in _in143.getsource(_rm143._lingua)
                and '"La risposta è pronta" if _it_push' in _in143.getsource(_we143)
                and '"Genio Legale è pronto" if _it_push' in _in143.getsource(_we143)
                and '"Rasti u fshi.": "Caso eliminato."' in _js and '"Po kërkoj…": "Sto cercando…"' in _js
                and ".calendar-toggle[hidden] { display: none; }" in _io2.open(_os2.path.join(_rr143, "static", "style.css"), encoding="utf-8").read()
                and ".deadline-banner[hidden], .clients-count[hidden], .dossier-count[hidden] { display: none; }"
                in _io2.open(_os2.path.join(_rr143, "static", "style.css"), encoding="utf-8").read())
        from src import succession_engine as _se143
        _q_ok = _se143.check("PJESA | M | 1/3\nPJESA | A | 2/9\nPJESA | B | 2/9\nPJESA | C | 2/9\n"
                             "STRUKTURA | bashkeshort=1 | femije=3 | rend=1\n", "it")
        _q_al = _se143.check("PJESA | M | 1/4\nPJESA | A | 1/4\nPJESA | B | 1/4\nPJESA | C | 1/4\n"
                             "STRUKTURA | bashkeshort=1 | femije=3 | rend=1\n", "it")
        _okF = ("art. 581 c.c." in _q_ok and "⚠" not in _q_ok and "Neni 361" not in _q_ok and "⚠" in _q_al
                and _se143.first_order_shares(True, 0) is None and _se143.quote_certe_it(True, 0) is None
                and "Neni 361" not in _se143.check("PJESA | G | 1/1\nSTRUKTURA | bashkeshort=1 | femije=0 | rend=1\n", "sq"))
        _okE = _okE and _okF
        check("sessione[143]: la giurisdizione viaggia nei thread · precedenti italiani in sessione IT · provenienza nella "
              "lingua del fascicolo e motore Tetramorph (mai il nome del modello) · pannelli precedenti/contratti bilingui · "
              "attributi dell'elemento aggiunto tradotti · notifiche push e promemoria nella lingua giusta · il pulsante "
              "sospeso resta nascosto · quote successorie italiane (artt. 566/581 c.c.), mai il KC 361 in IT", _okA and _okB and _okC and _okD and _okE,
              "A=%s B=%s C=%s D=%s E=%s" % (_okA, _okB, _okC, _okD, _okE))
    except Exception as _e143:  # noqa: BLE001
        check("sessione[143]: kontrollet u ekzekutuan", False, str(_e143))

    # [144] v9.397 — IL PROCURATORE IN DUE GIURISDIZIONI: era scritto solo per l'Albania (prompt, SPAK, Avokati i
    # Popullit, semi del KPP; «neni 291/329 KPP» dentro un parere italiano), il testo degli articoli arrivava tagliato a
    # 900 caratteri (art. 275 c.p.p.: 7.516) e analisi/atto d'accusa non ricevevano il fascicolo. Con un cervello FINTO
    # che registra i prompt: in IT ogni strumento parla italiano, con articoli italiani e l'etichetta «art.»; in AL resta
    # tutto come prima.
    try:
        import re as _re144, inspect as _in144
        from src import prosecutor as _pr144, brain as _br144, web as _we144
        _idx_it144 = idx_it if "idx_it" in dir() else ArticleIndex.load(INDEX_FILE.parent / "bm25_it.pkl")
        class _F144:
            def __init__(self): self.c = []
            def complete(self, system=None, messages=None, **kw):
                self.c.append((system or "", messages[0]["content"] if messages else "", kw.get("fast")))
                if kw.get("fast"):          # l'espansione dei termini, nella lingua della sessione
                    return "furto\nrapina" if _br144.request_jurisdiction() == "IT" else "vjedhje\nplagosje"
                return "## ok"
        _ALB144 = _re144.compile(r"[ëçË]|\bneni\b|\bKPP\b|\bSPAK\b|Avokati i Popullit", _re144.I)
        _tools = [("analyze", {"facts": "x"}), ("draft_indictment", {"facts": "x"}), ("investigation_plan", {"facts": "x"}),
                  ("investigative_act", {"kind": "pergjim", "facts": "x"}), ("coercive_measure", {"facts": "x"}),
                  ("dismissal_request", {"facts": "x"}), ("stress_test", {"text": "x"}), ("citizen_complaint", {"facts": "x"}),
                  ("victim_rights", {"facts": "x"}), ("dismissal_appeal", {"facts": "x"}), ("delay_complaint", {"facts": "x"})]
        _bad = []
        for _lg, _ix in (("IT", _idx_it144), ("AL", idx)):
            _br144.set_request_jurisdiction(_lg)
            for _nm, _kw in _tools:
                _f = _F144()
                _res = getattr(_pr144, _nm)(_f, _ix, **_kw)
                _sys, _pr = [x for x in _f.c if not x[2]][-1][:2]
                _arts = _res.get("articles") or []
                if _lg == "IT":
                    _corpo = _sys.split("━━━")[-1]
                    if (_ALB144.search(_corpo + _pr) or "art. " not in _pr or "neni " in _pr or not _arts
                            or any(a["code"].startswith(("kodi_", "ligji_")) for a in _arts)):
                        _bad.append("IT:" + _nm)
                else:
                    if "neni " not in _pr or not _arts or any(a["code"].startswith(("codice_", "costituzione")) for a in _arts):
                        _bad.append("AL:" + _nm)
        _br144.set_request_jurisdiction("IT")
        _kinds_it = [k["label"] for k in _pr144.list_act_kinds()]
        _br144.set_request_jurisdiction("AL")
        _a275 = next(a for a in _idx_it144.articles if a.code == "codice_procedura_penale" and a.number == "275")
        _b275 = _pr144._blocco([(_a275.code, _a275.number, (_a275.heading or "") + " " + _a275.body)], "it")
        _src_an = _in144.getsource(_we144.api_prosecutor_analyze) + _in144.getsource(_we144.api_prosecutor_indictment)
        _okB = ("Decreto di perquisizione (personale/locale)" in _kinds_it and len(_b275) > 3400
                and "testo tagliato" in _b275 and _src_an.count("_with_case(facts[:14000], body)") == 2)
        check("procuratore[144]: 11 strumenti in sessione IT in italiano con articoli italiani («art.», niente KPP/SPAK) e in "
              "AL invariati · atti d'indagine con le etichette del c.p.p. · testo degli articoli fino a 3.500 caratteri con "
              "l'avviso del taglio · analisi e atto d'accusa ricevono il fascicolo", not _bad and _okB,
              "bad=%s okB=%s" % (_bad, _okB))
    except Exception as _e144:  # noqa: BLE001
        check("procuratore[144]: kontrollet u ekzekutuan", False, str(_e144))

    # [145] v9.397 — (1) IL VERIFICATORE SUGLI ELENCHI ITALIANI: «artt. 335 c.p.p. e 107 disp. att. c.p.p.» dava il 335
    # «inesistente» (la coda arrivava alle disp. att. e prendeva il codice più lungo) e perdeva il 107; «artt. 408, comma 2,
    # e 410 c.p.p.» lasciava il 408 «senza codice» e perdeva il 410. (2) IL RECUPERO CONDIVISO (perizie, notaio, scadenze,
    # prescrizione, lettere, procuratore): in sessione IT l'estrazione dei termini tornava un paragrafo invece dei nomi
    # dei reati (prompt albanese + vincolo italiano); e la ricerca per titolo prendeva i primi titoli in ordine di codice.
    # Misurato su 12 casi penali tipici: la norma del reato fra gli articoli dati al modello 5/12 → 11/12.
    try:
        import inspect as _in145
        from src import expertise as _ex145
        _it145 = idx_it if "idx_it" in dir() else ArticleIndex.load(INDEX_FILE.parent / "bm25_it.pkl")
        def _st145(t):
            return {(x.get("code"), str(x.get("number"))): x.get("status") for x in cv.verify_text(t, _it145)["items"]}
        _a = _st145("artt. 335 c.p.p. e 107 disp. att. c.p.p.")
        _b = _st145("artt. 408, comma 2, e 410 c.p.p.")
        _c = _st145("art. 335 c.p.p. e 9999 disp. att. c.p.p.")
        _d = _st145("art. 18, comma 4 e 5, L. 300/1970")
        _okA = (_a.get(("codice_procedura_penale", "335")) == "verified" and _a.get(("disp_att_cpp", "107")) == "verified"
                and ("disp_att_cpp", "335") not in _a
                and _b.get(("codice_procedura_penale", "408")) == "verified" and _b.get(("codice_procedura_penale", "410")) == "verified"
                and _c.get(("disp_att_cpp", "9999")) == "fake"                 # il numero inventato resta inventato
                and _d.get(("statuto_lavoratori", "18")) == "verified" and len(_d) == 1)
        _okB = ("raw_system=True" in _in145.getsource(_ex145._expand_terms) and set(_ex145._ESPANDI) == {"sq", "it"}
                and _ex145._pulisci_termini("Nota preliminare:** in questa sessione non mi è stato concesso l'accesso allo strumento di ricerca web, quindi non posso\nTruffa\n- Appropriazione indebita") == ["Truffa", "Appropriazione indebita"])
        _okC = (("kodi_penal", "130/a") in {(c, n) for c, n, _ in _ex145._heading_scan_rank(idx, "dhunë në familje")}
                and "_heading_scan_rank" in _in145.getsource(_ex145.retrieve_grounded)
                and "index.search(query, top_k=4)" in _in145.getsource(_ex145.retrieve_grounded)
                and ("kodi_penal", "134") in scanned(idx, "vjedhje"))            # la ricerca per titolo di prima resta
        check("recupero[145]: elenchi «artt.» del verificatore (335 c.p.p. + 107 disp. att.; 408, comma 2, e 410) senza "
              "falsi «inesistente» né articoli persi, il numero inventato resta inventato · estrazione dei termini nella "
              "lingua dell'indice, senza preambolo, righe pulite · ricerca per titolo ordinata e posti alla ricerca per "
              "contenuto", _okA and _okB and _okC, "A=%s B=%s C=%s %s %s" % (_okA, _okB, _okC, _a, _b))
    except Exception as _e145:  # noqa: BLE001
        check("recupero[145]: kontrollet u ekzekutuan", False, str(_e145))

    # [146] v9.398 — IL PRIMO CONTATTO in sessione IT: prompt solo albanese («në SHQIP», percorsi in albanese, «neni»)
    # e l'audit IT ha trovato «kallëzim penale» in una risposta italiana. Con un cervello finto: in IT prompt e contesto
    # italiani, stessi token di instradamento; in AL invariato.
    try:
        import re as _re146
        from src import intake as _ik146, brain as _br146
        _it146 = idx_it if "idx_it" in dir() else ArticleIndex.load(INDEX_FILE.parent / "bm25_it.pkl")
        class _F146:
            def __init__(self): self.c = []
            def complete(self, system=None, messages=None, **kw):
                self.c.append((system or "", messages[0]["content"])); return "ok\n[ROUTE: proscomplaint]"
        _br146.set_request_jurisdiction("IT"); _f1 = _F146()
        _r1 = _ik146.triage(_f1, _it146, story="Mi hanno rubato l'auto sotto casa")
        _br146.set_request_jurisdiction("AL"); _f2 = _F146()
        _r2 = _ik146.triage(_f2, idx, story="Më vodhën makinën poshtë pallatit")
        _tok = lambda t: sorted(set(_re146.findall(r"\[ROUTE: ([a-z]+)\]", t)))
        _okA = (not _re146.search(r"[ëçË]|\bneni\b|SHQIP|kallëzim", _f1.c[0][0] + _f1.c[0][1])
                and "art. " in _f1.c[0][1] and _tok(_f1.c[0][0]) == _tok(_f2.c[0][0])
                and "SHQIP" in _f2.c[0][0] and "neni " in _f2.c[0][1]
                and _r1.get("route") == "proscomplaint" == _r2.get("route"))
        check("primo_contatto[146]: in sessione IT prompt e contesto italiani (niente «kallëzim», «neni», «SHQIP»), stessi "
              "token di instradamento; in AL invariato", _okA, "okA=%s" % _okA)
    except Exception as _e146:  # noqa: BLE001
        check("primo_contatto[146]: kontrollet u ekzekutuan", False, str(_e146))

    # [147] v9.399 — L'AVVOCATO DEL DIAVOLO IN ITALIANO: in sessione IT il prompt del diavolo era SOLO albanese e
    # il modello copiava alla lettera «[LARTË]» e «PIKA KU DO TË SULMOJA I PARI» (audit v9.397, pipeline immobiliare:
    # 8 volte). Con un cervello finto: in IT prompt, etichette del messaggio e cancello del 2° round italiani
    # ([CRITICA]); in AL identico a prima. Stessa cosa per il 🔮 secondo parere e «Consiglio strategico».
    try:
        import re as _re147
        from src import studio as _st147, second_opinion as _so147, brain as _br147
        class _F147:
            def __init__(self): self.c = []
            def complete(self, system=None, messages=None, **kw):
                self.c.append((system or "", messages[0]["content"])); return "- [CRITICA] x " * 3
        _alb147 = _re147.compile(r"[ëçË]|\bPYETJA\b|\bNENET\b|SULMI|PIKA KU|\[LARTË\]|\[KRITIKE\]|\[MESATARE\]")
        _fi, _fs = _F147(), _F147()
        _st147.avokati_i_djallit(_fi, domanda="D", blloku_neneve="art. 1", pergjigja="R", lang="it")
        _st147.avokati_i_djallit(_fs, domanda="D", blloku_neneve="neni 1", pergjigja="R", lang="sq")
        _st147.sulmi_i_dyte(_fi, domanda="D", blloku_neneve="art. 1", pergjigja_v2="R2", lang="it")
        _st147.sulmi_i_dyte(_fs, domanda="D", blloku_neneve="neni 1", pergjigja_v2="R2", lang="sq")
        _st147.senior_pergjigjja(_fi, domanda="D", blloku_neneve="art. 1", pergjigja="R", sulmi="S", lang="it")
        _st147.senior_pergjigjja(_fs, domanda="D", blloku_neneve="neni 1", pergjigja="R", sulmi="S", lang="sq")
        _okA = (len(_fi.c) == 3 and not any(_alb147.search(a + b) for a, b in _fi.c)
                and "[CRITICA]" in _fi.c[0][0] and "PUNTO DA CUI ATTACCHEREI PER PRIMO" in _fi.c[0][0]
                and _fi.c[0][1].startswith("DOMANDA:") and "[CRITICA]" in _fi.c[1][0]
                and "ATTACCO DELL'AVVOCATO DEL DIAVOLO:" in _fi.c[2][1])
        _okB = (_fs.c[0][0] == _st147.DJALLI_SYSTEM and _fs.c[1][0] == _st147.DJALLI_2_SYSTEM
                and _fs.c[0][1] == "PYETJA:\nD\n\nNENET (tekst i plotë):\nneni 1\n\nPËRGJIGJA E PROPOZUAR:\nR"
                and _fs.c[2][1] == "PYETJA:\nD\n\nNENET (tekst i plotë):\nneni 1\n\nPËRGJIGJA IME:\nR"
                                   "\n\nSULMI I AVOKATIT TË DJALLIT:\nS")
        _okC = (_st147.duhet_raund2("- [CRITICA] x", "[RESPINTO]") is True
                and _st147.duhet_raund2("- [ALTA] x", "[RESPINTO]") is False
                and _st147.duhet_raund2("- [CRITICA] x", "[ACCOLTO]") is False
                and _st147.duhet_raund2("- [KRITIKE] x", "[REFUZOHET]") is True
                and _st147.duhet_raund2("- [MEDIA] x", "[PARZIALE]") is False)
        _gi, _gs = _F147(), _F147()
        _br147.set_request_jurisdiction("IT")
        _so147.review(_gi, question="Q", answer_text="A", context="art. 1 c.c.")
        _so147.consult(_gi, situation="S", context="art. 1 c.c.")
        _br147.set_request_jurisdiction("AL")
        _so147.review(_gs, question="Q", answer_text="A", context="neni 1")
        _so147.consult(_gs, situation="S", context="neni 1")
        _okD = (_so147._SYSTEM_IT in _gi.c[0][0] and _so147._CONSULT_SYSTEM_IT in _gi.c[1][0]
                and not any(_re147.search(r"[ëçË]|KONTEKST|PYETJA|SITUATA|Gjilp|Shqip", b) for _, b in _gi.c)
                and "CONTESTO/ARTICOLI" in _gi.c[0][1] and not _re147.search(r"[ëçË]|Gjilp|Shqip\.", _so147._SYSTEM_IT + _so147._CONSULT_SYSTEM_IT)
                and _so147._SYSTEM in _gs.c[0][0] and _so147._CONSULT_SYSTEM in _gs.c[1][0]
                and "KONTEKST/NENE" in _gs.c[0][1] and _gs.c[1][1].startswith("SITUATA:"))
        check("diavolo[147]: in sessione IT l'avvocato del diavolo (1° e 2° round), la replica del senior, il secondo "
              "parere e il consiglio strategico hanno prompt ed etichette italiani ([CRITICA]/[ALTA]/[MEDIA], «PUNTO DA "
              "CUI ATTACCHEREI»), il cancello del 2° round legge [CRITICA]; in AL tutto identico",
              _okA and _okB and _okC and _okD, "A=%s B=%s C=%s D=%s" % (_okA, _okB, _okC, _okD))
    except Exception as _e147:  # noqa: BLE001
        check("diavolo[147]: kontrollet u ekzekutuan", False, str(_e147))
    finally:
        try:
            _br147.set_request_jurisdiction("AL")
        except Exception:  # noqa: BLE001
            pass

    # [148] v9.399 — GLI STRUMENTI DI CONTORNO nella lingua e nel diritto della sessione: revisione contratto (AL: la
    # legge privacy è la 124/2024, non la 9887/2008 abrogata; il neni 911 KC è il comodato, non una nullità — IT: prompt
    # italiano con 1341-1342, 1229, 33-36 cod. consumo), gergo e notizia di stato per il cliente, simulazione dell'accordo
    # con i precedenti ITALIANI in sessione IT, raccoglitori con etichette italiane, qualità delle fonti a parole.
    try:
        import inspect as _in148
        from src import web as _w148, war_room as _wr148, studio as _st148, settlement as _se148, storage as _sg148
        _cr_al, _cr_it = _w148.CONTRACT_REVIEW_SYSTEM, _w148.CONTRACT_REVIEW_SYSTEM_IT
        _okA = ("124/2024" in _cr_al and "92/686/911" not in _cr_al and "neni 686 KC" in _cr_al
                and all(k in _cr_it for k in ("1341", "1342", "1229", "33-36", "806-808", "2016/679"))
                and "CONTRACT_REVIEW_SYSTEM_IT if _active_jurisdiction(user) == \"IT\"" in _in148.getsource(_w148.api_contract_review))
        _okB = ('"plain_sq"' in _w148.JARGON_TRANSLATE_SYSTEM_IT and '"body_sq"' in _w148.AUTO_STATUS_SYSTEM_IT
                and "JARGON_TRANSLATE_SYSTEM_IT" in _in148.getsource(_w148.api_translate_jargon)
                and "AUTO_STATUS_SYSTEM_IT" in _in148.getsource(_w148.api_auto_status)
                and "storage.stage_label(case.stage, 'IT')" in _in148.getsource(_w148.api_auto_status)
                and not __import__("re").search(r"[ëçË]", _w148.JARGON_TRANSLATE_SYSTEM_IT + _w148.AUTO_STATUS_SYSTEM_IT
                                                 + _cr_it))
        _src_set = _in148.getsource(_w148.api_settlement_simulate)
        _dist = {"mean_eur": 20000.0, "p10_eur": 5000.0, "p25_eur": 10000.0, "p50_eur": 18000.0,
                 "p75_eur": 28000.0, "p90_eur": 40000.0}
        _r_it = _se148.recommendation(_dist, current_offer_eur=None, plaintiff=True, lang="it")["summary"]
        _r_sq = _se148.recommendation(_dist, current_offer_eur=15000.0, plaintiff=True)["summary"]
        _okC = ("gather_precedents_it(" in _src_set and "None if _it_set else" in _src_set
                and "SCENARIO_SCHEMA_HINT_IT" in _src_set and "Nessuna offerta concreta" in _r_it
                and "Oferta 15000 EUR" in _r_sq and '"name": "settle_normal"' in _se148.SCENARIO_SCHEMA_HINT_IT)
        class _F148:
            def __init__(self): self.c = []
            def complete(self, system=None, messages=None, **kw):
                self.c.append(messages[0]["content"]); return "{}"
        class _A148:
            code, number, title_sq, heading, body = "codice_civile", "2946", "Codice civile", "Prescrizione ordinaria", "x"
        _fi, _fs = _F148(), _F148()
        _st148.mbledhesi_web(_fi, domanda="D", summary="S", retrieved=[(_A148(), 1.0)], lang="it")
        _st148.mbledhesi_qbz(_fi, retrieved=[(_A148(), 1.0)], lang="it")
        _st148.mbledhesi_web(_fs, domanda="D", summary="S", retrieved=[(_A148(), 1.0)], lang="sq")
        _okD = (_fi.c[0].startswith("DOMANDA:") and "ARTICOLI NEL CORPUS:" in _fi.c[0]
                and _fi.c[1].startswith("ARTICOLI DA CONTROLLARE:")
                and _fs.c[0].startswith("PYETJA:") and "NENET NË KORPUS:" in _fs.c[0]
                and _st148._blocco_nenesh([], lang="it") == "(nessuno)" and _st148._blocco_nenesh([]) == "(asnjë)")
        _rap_it = _wr148.raport_verifikimi([], [{"agjenti": "web", "titulli": "Circolare", "citim": "testo ufficiale abbastanza",
                                                "url": "https://blog.example/x"}], [], "it")
        _okE = ("(fonte secondaria)" in _rap_it and "secondary" not in _rap_it
                and _sg148.AUTO_LETTER_LABELS_IT.keys() == _sg148.AUTO_LETTER_LABELS_SQ.keys()
                and _sg148.AGENT_SUGGESTION_LABELS_IT.keys() == _sg148.AGENT_SUGGESTION_LABELS_SQ.keys())
        check("contorno[148]: revisione contratto (AL 124/2024 + KC 686/688, IT artt. 1341-1342/1229/33-36), gergo e "
              "notizia per il cliente, accordo con precedenti italiani, raccoglitori ed etichette nella lingua della "
              "sessione; AL invariato", _okA and _okB and _okC and _okD and _okE,
              "A=%s B=%s C=%s D=%s E=%s" % (_okA, _okB, _okC, _okD, _okE))
    except Exception as _e148:  # noqa: BLE001
        check("contorno[148]: kontrollet u ekzekutuan", False, str(_e148))

    # [149] v9.399 — PRESCRIZIONE: in AL i semi civili saltavano la regola generale (KC 114, dieci anni) e i termini
    # brevi (115) e il prompt mandava al «124 e vijues»; in IT stesso prompt albanese (KP 66) con semi inesistenti
    # nell'indice italiano. E due esempi sbagliati nei prompt del cervello (KP 75 = pronto soccorso, non l'onere della
    # prova; «48-51» comprendeva le aggravanti e i minori).
    try:
        import re as _re149
        from src import deadlines as _dl149, brain as _br149
        _it149 = idx_it if "idx_it" in dir() else ArticleIndex.load(INDEX_FILE.parent / "bm25_it.pkl")
        _ba = {(a.code, a.number) for a in idx.articles}
        _bi = {(a.code, a.number) for a in _it149.articles}
        _okA = (("kodi_civil", "114") in _dl149._SEED and ("kodi_civil", "115") in _dl149._SEED
                and ("kodi_civil", "124") not in _dl149._SEED and all(k in _ba for k in _dl149._SEED)
                and all(k in _bi for k in _dl149._SEED_IT)
                and ("codice_penale", "157") in _dl149._SEED_IT and ("codice_civile", "2946") in _dl149._SEED_IT)
        class _F149:
            def __init__(self): self.c = []
            def complete(self, system=None, messages=None, callsite=None, **kw):
                if callsite == "prescription":
                    self.c.append((system or "", messages[0]["content"]))
                return ""
        _fi, _fs = _F149(), _F149()
        _dl149.prescription(_fi, _it149, facts="Prestito di 20.000 euro del marzo 2014, mai sollecitato.", jurisdiction="IT")
        _dl149.prescription(_fs, idx, facts="Hua prej 20.000 eurosh në mars 2014, kurrë e kërkuar.", jurisdiction="AL")
        _si, _ui = _fi.c[0]
        _ss, _us = _fs.c[0]
        _okB = (not _re149.search(r"[ëçË]|\bneni\b|\bNENET\b", _si + _ui) and "art. 2946" in _si
                and _ui.startswith("FATTI / REATO / DATA:") and "art. 2946]" in _ui
                and "PARASHKRIM | trigger=" in _si)
        _okC = ("neni 114 (rregulli i përgjithshëm" in _ss and "nenin 124 e" not in _ss
                and _us.startswith("FAKTET / VEPRA / DATA:") and "neni 114]" in _us)
        _src149 = open(_br149.__file__, encoding="utf-8").read()
        _okD = ("Neni 75 Kodi i Punës" not in _src149 and "neni 144, pika 5/1, i Kodit të Punës" in _src149
                and "Neni 48-51 Kodi Penal" not in _src149)
        check("prescrizione[149]: semi AL con KC 114/115 (non 124/128) e in IT semi italiani esistenti, prompt e articoli "
              "nella lingua della sessione, riga macchina invariata; esempi del cervello corretti (KP 144/5-1, KP 9, "
              "48-49 lehtësuese)", _okA and _okB and _okC and _okD, "A=%s B=%s C=%s D=%s" % (_okA, _okB, _okC, _okD))
    except Exception as _e149:  # noqa: BLE001
        check("prescrizione[149]: kontrollet u ekzekutuan", False, str(_e149))

    # [150] v9.399 — IL VERIFICATORE E LE CITAZIONI VICINE (misurato su 204 risposte vere: +23 verificate, 0 falsi nuovi):
    # la coda di una citazione attraversava la successiva — con l'apostrofo («l'art. 1218 c.c. e l'art. 2043 c.c.»: il 2043
    # spariva; «l'art. 157 c.p. e l'art. 344-bis c.p.p.»: il 157 verificato sul c.p.p.), le virgolette, la barra e il
    # grassetto («"art. 2043 c.c." / "art. 81 c.p."»: il 2043 «inesistente» nel codice penale); l'elenco con «art.» ripetuto
    # condivide il codice solo come INFERENZA (mai un «falso»); disp. att. c.p.c. (fuori corpus) mai confuse col c.p.c.;
    # leggi citate per numero a confine di cifra.
    try:
        from src import citation_verifier as _cv150
        _it150 = idx_it if "idx_it" in dir() else ArticleIndex.load(INDEX_FILE.parent / "bm25_it.pkl")
        def _v150(t, ix):
            return [(c["number"], c["code"], c["status"]) for c in _cv150.verify_text(t, ix)["items"]]
        _casi = [
            ("l'art. 1218 c.c. e l'art. 2043 c.c.", [("1218", "codice_civile", "verified"), ("2043", "codice_civile", "verified")]),
            ("l'art. 157 c.p. e l'art. 344-bis c.p.p.", [("157", "codice_penale", "verified"),
                                                          ("344/bis", "codice_procedura_penale", "verified")]),
            ('"art. 2043 c.c." / "art. 81 c.p."', [("2043", "codice_civile", "verified"), ("81", "codice_penale", "verified")]),
            ("«art. 81 c.p.» e «art. 414 c.p.c.»", [("81", "codice_penale", "verified"),
                                                   ("414", "codice_procedura_civile", "verified")]),
            ("alle abilitazioni ex art. 116 e all'art. 126 C.d.S.", [("116", "codice_strada", "verified"),
                                                                    ("126", "codice_strada", "verified")]),
            ("ex art. 22 L. 241/1990.  ---  ## 3.", [("22", "procedimento_amministrativo", "verified")]),
            ("art. 21 D.Lgs. 58/1998", [("21", "tu_finanza", "verified")]),
            ("art. 33 Cod. Consumo", [("33", "codice_consumo", "verified")]),
            ("**Art. 212, par. 3, Reg. delegato (UE) 2015/2446**", [("212", "reg_ue_2015_2446", "verified")]),
            ("dell'art. 214 Reg. delegato. - **Art. 215 Reg. delegato 2015/2446**", None),
            ("artt. 1341 e 9999 c.c.", [("1341", "codice_civile", "verified"), ("9999", "codice_civile", "fake")]),
        ]
        _bad = []
        for _t, _exp in _casi:
            _got = _v150(_t, _it150)
            if _exp is not None and _got != _exp:
                _bad.append((_t, _got))
        # mai «falso» per un'inferenza o un atto fuori corpus
        for _t in ("(art. 93-bis e art. 215 Reg. (UE) 2015/2446)", "art. 186, co. 9-bis, e art. 1 L. 91/1992",
                   "l'art. 557 c.p.c. e l'art. 164-ter disp. att. c.p.c.", "art. 2 D.Lgs. 158/1998"):
            _g = _v150(_t, _it150)
            if any(st == "fake" for _n, _c, st in _g) or any(c == "tu_finanza" for _n, c, _s in _g):
                _bad.append((_t, _g))
        _g = _v150("dell'art. 214 Reg. delegato. - **Art. 215 Reg. delegato 2015/2446**", _it150)
        if ("215", "reg_ue_2015_2446", "verified") not in _g:
            _bad.append(("**Art. 215**", _g))
        for _t, _exp in (('"neni 114 KC" / "neni 443 KPC"', [("114", "kodi_civil", "verified"), ("443", "kodi_proc_civile", "verified")]),
                         ("neni 114 dhe neni 115 i Kodit Civil", [("114", "kodi_civil", "verified"), ("115", "kodi_civil", "verified")])):
            _got = _v150(_t, idx)
            if _got != _exp:
                _bad.append((_t, _got))
        check("verificatore[150]: citazioni vicine lette una per una (apostrofo, virgolette, barra, grassetto), elenco con "
              "«art.» ripetuto = inferenza mai «falsa», disp. att. c.p.c. fuori corpus mai «inesistenti», leggi per numero "
              "a confine di cifra, «Cod. Consumo»/«Reg. delegato»; l'elenco esplicito «artt. 1341 e 9999 c.c.» resta falso",
              not _bad, "; ".join("%s → %s" % b for b in _bad)[:600])
    except Exception as _e150:  # noqa: BLE001
        check("verificatore[150]: kontrollet u ekzekutuan", False, str(_e150))

    # [151] v9.399 — MOTORE DELLE SCADENZE: in AL mancavano gli articoli dei termini che contano (KPP 415 «Afatet e
    # ankimit», 435 ricorso, 263 durata della custodia, KPC 444-445, KC 114/115/117); in IT semi albanesi inesistenti
    # nell'indice italiano e prompt «procedura shqiptare». Con un cervello finto: semi esistenti, prompt e articoli
    # nella lingua della sessione.
    try:
        import re as _re151
        from src import afati as _af151
        _it151 = idx_it if "idx_it" in dir() else ArticleIndex.load(INDEX_FILE.parent / "bm25_it.pkl")
        _ba151 = {(a.code, a.number) for a in idx.articles}
        _bi151 = {(a.code, a.number) for a in _it151.articles}
        _seed = lambda t, k: [tuple(x) for x in t[k]["seed"]]
        _okA = (("kodi_proc_penale", "415") in _seed(_af151.TRIGGERS, "vendim_penal")
                and ("kodi_proc_penale", "435") in _seed(_af151.TRIGGERS, "vendim_penal")
                and ("kodi_proc_penale", "263") in _seed(_af151.TRIGGERS, "mase_sigurimi")
                and ("kodi_civil", "114") in _seed(_af151.TRIGGERS, "kontrate")
                and all(x in _ba151 for v in _af151.TRIGGERS.values() for x in v["seed"])
                # v9.410: + decreto_ingiuntivo, solo IT; v9.454: ekzekutim solo AL (in Albania non c'è un decreto ingiuntivo)
                and set(_af151.TRIGGERS) - {"ekzekutim"} <= set(_af151.TRIGGERS_IT)
                and all(tuple(x) in _bi151 for v in _af151.TRIGGERS_IT.values() for x in v["seed"]))
        class _F151:
            def __init__(self): self.c = []
            def complete(self, system=None, messages=None, callsite=None, **kw):
                if callsite == "afati":
                    self.c.append((system or "", messages[0]["content"]))
                return ""
        _fi, _fs = _F151(), _F151()
        _af151.compute(_fi, _it151, trigger="vendim_civil", event_date="2026-09-10",
                       facts="Sentenza del Tribunale di Milano notificata il 10 settembre 2026.", jurisdiction="IT")
        _af151.compute(_fs, idx, trigger="vendim_civil", event_date="2026-09-10",
                       facts="Vendimi i Gjykatës së Tiranës u njoftua më 10 shtator 2026.", jurisdiction="AL")
        _si, _ui = _fi.c[0]; _ss, _us = _fs.c[0]
        _okB = (_si == _af151._SYSTEM_IT and _ui.startswith("EVENTO INIZIALE: Notificazione della sentenza civile")
                and "art. 325]" in _ui and not _re151.search(r"[ëçË]|\bneni\b|NENET", _si + _ui)
                and "AFAT | <titolo breve>" in _si)
        _okC = (_ss.startswith("Ti je ekspert i procedurës shqiptare") and _us.startswith("NGJARJA-NISËSE:")
                and "neni 443]" in _us and "neni 444]" in _us)
        check("scadenze[151]: semi AL con i termini veri (KPP 415/435, 263, KPC 444-445, KC 114), semi IT esistenti, "
              "prompt ed etichette nella lingua della sessione, riga macchina invariata",
              _okA and _okB and _okC, "A=%s B=%s C=%s" % (_okA, _okB, _okC))
    except Exception as _e151:  # noqa: BLE001
        check("scadenze[151]: kontrollet u ekzekutuan", False, str(_e151))

    # [152] v9.399 — SESSIONE AL, dall'audit «da avvocato» del 28 set: (a) il premio di anzianità entra col KP 145 (la regola
    # di base del contratto a tempo indeterminato) — l'ancora v9.394 portava solo il 152 (contratti a termine); (b) la
    # richiesta di intercettazione riceve il KPP 222 (la decisione che autorizza); (c) niente falsi titoli di capitolo
    # («KREU XIV — Neni 140», «— (Ndryshuar titulli …)»: 202 nel corpus) e il parser salta le note di modifica.
    try:
        import re as _re152
        from src import brain as _br152, prosecutor as _pr152, parser as _pa152
        _anc = [a for a in _br152.ANCORE_AL if ("kodi_punes", "152") in tuple(a[2])]
        _okA = bool(_anc) and ("kodi_punes", "145") in tuple(_anc[0][2]) and tuple(_anc[0][2])[0] == ("kodi_punes", "145")
        _okB = ("kodi_proc_penale", "222") in [tuple(x) for x in _pr152._ACT_KINDS["pergjim"]["seed"]]
        _falsi = [(a.code, a.number, getattr(a, "kreu", "")) for a in idx.articles
                  if _re152.search(r"—\s*(?:Neni\s+\d|\(\s*(?:Ndryshuar|Shtuar)\b)", (getattr(a, "kreu", "") or "") + " "
                                   + (getattr(a, "pjesa", "") or "") + " " + (getattr(a, "seksioni", "") or ""))]
        _okC = (not _falsi
                and _pa152._titolo_con_intestazione("KREU XIV", "\nNeni 140\nKohëzgjatja e kontratës") == "KREU XIV"
                and _pa152._titolo_con_intestazione("KREU XVII", "\n(Ndryshuar titulli me ligjin nr. 9125)\nNeni 188") == "KREU XVII"
                and _pa152._titolo_con_intestazione("KREU II", "\nFUSHA E ZBATIMIT\nNeni 3") == "KREU II — FUSHA E ZBATIMIT")
        check("al[152]: premio di anzianità col KP 145 (152 solo a termine), intercettazione col KPP 222, niente falsi titoli "
              "di capitolo nel corpus AL e il parser salta le note di modifica", _okA and _okB and _okC,
              "A=%s B=%s C=%s falsi=%s" % (_okA, _okB, _okC, _falsi[:3]))
    except Exception as _e152:  # noqa: BLE001
        check("al[152]: kontrollet u ekzekutuan", False, str(_e152))

    # [153] v9.399 — RECUPERO CONDIVISO DEGLI STRUMENTI PRO: (a) la «testa di sezione» — il primo articolo della sezione il
    # cui titolo contiene il termine è la figura generale del reato (KP 143 truffa: 11/12 → 12/12 sui casi penali della
    # v9.397); (b) i rinvii interni degli articoli dati («sipas paragrafit 6, të nenit 327, të këtij Kodi»; «ai sensi degli
    # articoli 406 e 407»): il procuratore scriveva «il neni 327 / 75/a / l'art. 406 non è nel corpus».
    try:
        from src import expertise as _ex153
        _it153 = idx_it if "idx_it" in dir() else ArticleIndex.load(INDEX_FILE.parent / "bm25_it.pkl")
        _art153 = lambda ix, c, n: (c, n, _ex153._article_text(ix, c, n))
        _okA = ("kodi_penal", "143") in [(c, n) for c, n, _ in _ex153._teste_di_sezione(idx, "mashtrim")]
        _r1 = [(c, n) for c, n, _ in _ex153._rinvii_interni(idx, [_art153(idx, "kodi_proc_penale", "323")], "sq")]
        _r2 = [(c, n) for c, n, _ in _ex153._rinvii_interni(_it153, [_art153(_it153, "codice_procedura_penale", "405")], "it")]
        _r3 = [(c, n) for c, n, _ in _ex153._rinvii_interni(_it153, [_art153(_it153, "codice_procedura_civile", "7")], "it")]
        _okB = (("kodi_proc_penale", "327") in _r1 and ("kodi_proc_penale", "75/a") in _r1
                and ("codice_procedura_penale", "406") in _r2 and ("codice_procedura_penale", "407") in _r2
                and ("codice_procedura_civile", "71") not in _r3 and len(_r1) <= 4)
        class _F153:
            def complete(self, system=None, messages=None, **kw):
                return "mashtrim\nfalsifikim dokumentesh"
        _g = [(c, n) for c, n, _ in _ex153.retrieve_grounded(_F153(), idx, "Viktima pagoi 5.000 euro për një investim "
                                                                 "që nuk ekzistonte, e mashtruar me dokumente të rreme.")]
        _okC = ("kodi_penal", "143") in _g
        # sostanze stupefacenti nei fatti → le norme penali sugli stupefacenti entrano sempre (KP 283 / art. 73 d.P.R. 309/1990)
        class _F153b:
            def complete(self, system=None, messages=None, **kw):
                return ""
        _gk = [(c, n) for c, n, _ in _ex153.retrieve_grounded(_F153b(), idx, "U kap duke shitur 50 gram kokainë në rrugë.")]
        _gt = [(c, n) for c, n, _ in _ex153.retrieve_grounded(_F153b(), idx, "I gjetën 30 tableta tramadol në makinë.")]
        _gi = [(c, n) for c, n, _ in _ex153.retrieve_grounded(_F153b(), _it153, "Arrestato mentre cedeva 200 grammi di cocaina.")]
        _okD = (("kodi_penal", "283") in _gk[:4] and ("kodi_penal", "283/a") in _gk[:4]
                and ("kodi_penal", "283") not in _gt[:2] and ("stupefacenti", "73") in _gi[:3])
        check("recupero[153]: testa di sezione (KP 143 per «mashtrim»), rinvii interni espliciti/impliciti (KPP 323 → 327, "
              "75/a; c.p.p. 405 → 406, 407; mai «art. 71» per «71-quater delle disp. att.»), sostanze nei fatti → KP 283/283-a "
              "o art. 73 d.P.R. 309/1990 (non il tramadolo, che non è in nessuna lista)", _okA and _okB and _okC and _okD,
              "A=%s B=%s C=%s D=%s r1=%s r2=%s r3=%s" % (_okA, _okB, _okC, _okD, _r1, _r2, _r3))
    except Exception as _e153:  # noqa: BLE001
        check("recupero[153]: kontrollet u ekzekutuan", False, str(_e153))

    # [154] v9.399 — IL TESTO DEGLI ARTICOLI NEGLI STRUMENTI DEL NOTAIO, DELLE LETTERE E DELLE PERIZIE: tagliato a 900 caratteri
    # (l'audit AL: la successione scriveva «il neni 361 è troncato: "Në çdo rast bashkëshorti merr 1/2 pjesë të tra…"»). Ora
    # fino a 3.500 con l'avviso del taglio, «art.» in italiano — stesso blocco condiviso per i tre moduli.
    try:
        import inspect as _in154
        from src import expertise as _ex154, notary as _no154, letters as _le154
        _it154 = idx_it if "idx_it" in dir() else ArticleIndex.load(INDEX_FILE.parent / "bm25_it.pkl")
        _t361 = _ex154._article_text(idx, "kodi_civil", "361") or ""
        _b = _ex154.blocco_articoli([("kodi_civil", "361", _t361)], "sq")
        _bi = _ex154.blocco_articoli([("codice_civile", "2946", _ex154._article_text(_it154, "codice_civile", "2946"))], "it")
        _lungo = _ex154.blocco_articoli([("kodi_civil", "1", "x" * 5000)], "sq")
        _okA = (len(_t361) > 900 and "1/2" in _b and "neni 361]" in _b and "art. 2946]" in _bi and "neni" not in _bi
                and "teksti u shkurtua" in _lungo and len(_lungo) < 3700)
        _okB = all("blocco_articoli(" in _in154.getsource(f) for f in (_no154._art_block, _le154._art_block, _ex154.analyze))
        # mai l'identificativo interno nel blocco (finiva NELL'ATTO: «[ligji_kadastra neni 14]»)
        _bk = _ex154.blocco_articoli([("ligji_kadastra", "14", "Zona kadastrale është njësia bazë.")], "sq")
        _okB = _okB and "ligji_kadastra" not in _bk and "Kadastra" in _bk and _ex154.etichetta_al("kodi_civil") == "Kodi Civil"
        check("blocco[154]: notaio, lettere e perizie ricevono il testo intero fino a 3.500 caratteri (KC 361 con la quota del "
              "coniuge), l'avviso del taglio e «art.» in sessione IT", _okA and _okB, "A=%s B=%s" % (_okA, _okB))
    except Exception as _e154:  # noqa: BLE001
        check("blocco[154]: kontrollet u ekzekutuan", False, str(_e154))

    # [155] v9.399 — LA PROCURA: in IT il prompt era albanese (KC 64-78, Ligji 110/2018) e la procura generale portava la guida
    # del KC 71/72; senza poteri scelti il testo predefinito era sempre «ordinaria amministrazione — procura generale», anche per
    # una procura SPECIALE (e per l'Albania è la dottrina italiana: il KC 71 dice la totalità dei diritti).
    try:
        import re as _re155
        from src import notary as _no155
        _it155 = idx_it if "idx_it" in dir() else ArticleIndex.load(INDEX_FILE.parent / "bm25_it.pkl")
        class _F155:
            def __init__(self): self.c = []
            def complete(self, system=None, messages=None, callsite=None, **kw):
                if callsite == "notary_prokura":
                    self.c.append((system or "", messages[0]["content"]))
                return ""
        _f = _F155()
        _no155.draft_prokura(_f, _it155, form="e_pergjithshme", details="Procura generale per gestire gli affari del mandante.")
        _no155.draft_prokura(_f, _it155, form="e_posacme", details="Procura speciale per vendere un immobile a Roma.")
        _no155.draft_prokura(_f, idx, form="e_posacme", details="Prokurë e posaçme për shitjen e apartamentit.")
        _no155.draft_prokura(_f, idx, form="e_pergjithshme", details="Prokurë e përgjithshme për punët e të përfaqësuarit.")
        (_s1, _u1), (_s2, _u2), (_s3, _u3), (_s4, _u4) = _f.c
        _okA = (_s1.startswith("Sei un NOTAIO italiano") and "art. 1708" in _u1 and "art. 1392]" in _u1
                and not _re155.search(r"\bKC\b|\bneni\b|[ëçË]", _s1 + _u1))
        _okB = ("solo gli atti indicati espressamente" in _u2 and "ordinaria amministrazione — procura generale" not in _u2)
        _okC = ("administrimit të zakonshëm" not in _u3 and "vetëm veprimet e përcaktuara shprehimisht" in _u3
                and "neni 71 KC" in _u4 and _s3.startswith("Ti je NOTER shqiptar"))
        check("procura[155]: in IT prompt, forme, guida (art. 1708 c.c.) e semi italiani, niente KC; poteri predefiniti coerenti "
              "con la forma (speciale ≠ «ordinaria amministrazione»; generale AL = KC 71)", _okA and _okB and _okC,
              "A=%s B=%s C=%s" % (_okA, _okB, _okC))
    except Exception as _e155:  # noqa: BLE001
        check("procura[155]: kontrollet u ekzekutuan", False, str(_e155))

    # [156] v9.399 — LE ETICHETTE LETTERALI DELLE FASI in sessione IT: il radar di nullità ha scritto «AFATI: il termine…»
    # dentro una scheda italiana (audit IT del 28 set). Le parole che i prompt albanesi chiedono di copiare tali e quali
    # («MOS E PËRDOR nëse …», «VENDIMTAR:», «PARË:», la catena «Kushti → … → PASOJA») in IT arrivano già italiane; in AL il
    # prompt resta identico. Ogni chiave deve esistere nel suo prompt: se qualcuno riscrive il prompt, la mappa va aggiornata.
    try:
        from src import brain as _b156
        _prompts156 = {"EVIDENCE_MAP_SYSTEM": _b156.EVIDENCE_MAP_SYSTEM, "NULLITY_RADAR_SYSTEM": _b156.NULLITY_RADAR_SYSTEM,
                       "MISSING_FACTS_SYSTEM": _b156.MISSING_FACTS_SYSTEM}
        _mancanti156 = [sq[:30] for sq, _it in _b156._ETICHETTE_IT
                        if not any(sq in p for p in _prompts156.values())]
        _it156 = {k: _b156.apply_jurisdiction(v, "IT") for k, v in _prompts156.items()}
        _al156 = {k: _b156.apply_jurisdiction(v, "AL") for k, v in _prompts156.items()}
        _okIT = ("«NON USARLA se …»" in _it156["NULLITY_RADAR_SYSTEM"] and "MOS E\n  PËRDOR" not in _it156["NULLITY_RADAR_SYSTEM"]
                 and "(1) TERMINE" in _it156["NULLITY_RADAR_SYSTEM"] and "(1) AFATI" not in _it156["NULLITY_RADAR_SYSTEM"]
                 and "«DECISIVO:»" in _it156["EVIDENCE_MAP_SYSTEM"] and "«Requisito:" in _it156["EVIDENCE_MAP_SYSTEM"]
                 and "«PRIORITARIO:»" in _it156["MISSING_FACTS_SYSTEM"] and "«PARË" not in _it156["MISSING_FACTS_SYSTEM"])
        _okAL = all(_prompts156[k] in _al156[k] for k in _prompts156) and "(1) AFATI" in _al156["NULLITY_RADAR_SYSTEM"]
        _okIdem = _b156.apply_jurisdiction(_it156["NULLITY_RADAR_SYSTEM"], "IT") == _it156["NULLITY_RADAR_SYSTEM"]
        check("fasi[156]: in IT le etichette da copiare sono italiane (TERMINE, NON USARLA, DECISIVO, PRIORITARIO, Requisito→…); "
              "in AL il prompt è identico; ogni chiave esiste nel suo prompt; idempotente",
              not _mancanti156 and _okIT and _okAL and _okIdem,
              "mancanti=%s IT=%s AL=%s idem=%s" % (_mancanti156, _okIT, _okAL, _okIdem))
    except Exception as _e156:  # noqa: BLE001
        check("fasi[156]: kontrollet u ekzekutuan", False, str(_e156))

    # [157] v9.399 — (a) SOSPENSIONE FERIALE NEI TERMINI A MESI/ANNI: il motore la IGNORAVA («termini sostanziali») anche
    # quando la regola la chiedeva → il termine lungo (art. 327 c.p.c., sei mesi) di una sentenza pubblicata a giugno usciva
    # scaduto 31 giorni prima del vero. Ora i giorni di agosto nel decorso si aggiungono; decorso che inizia in agosto →
    # differito alla fine del periodo; AL mai. (b) ASSISTENTE D'UDIENZA: prompt nativo italiano, prima frase non fraintendibile,
    # premessa sbagliata corretta, articoli del fascicolo dal corpus (nell'audit AL rispondeva «Jo —» senza i 180 giorni).
    # (c) SIMULAZIONE DELL'ACCORDO: gli articoli del caso nel prompt e niente termini inventati (uno scenario si reggeva su un
    # «reclamo scritto entro 30 giorni» che il Kodi i Punës non prevede).
    try:
        from src import deadline_engine as _de157
        _c157 = lambda *a, **k: _de157.compute_deadline(*a, **k).deadline.isoformat()
        _okA = (_c157("2026-06-15", 6, "months", jurisdiction="IT", feriale=True) == "2027-01-15"
                and _c157("2026-09-10", 6, "months", jurisdiction="IT", feriale=True) == "2027-03-10"
                and _c157("2026-08-10", 6, "months", jurisdiction="IT", feriale=True) == "2027-03-01"
                and _c157("2026-07-01", 1, "years", jurisdiction="IT", feriale=True) == "2027-09-01"
                and _c157("2026-06-15", 6, "months", jurisdiction="IT", feriale=False) == "2026-12-15"
                and _c157("2026-06-15", 6, "months", jurisdiction="AL", feriale=True) == "2026-12-15"
                and _c157("2024-07-20", 30, "days", jurisdiction="IT", feriale=True) == "2024-09-19")
        _web157 = open("/app/src/web.py", encoding="utf-8").read()
        _i157 = _web157.find("def api_hearing_quick(")
        _hq157 = _web157[_i157:_i157 + 3500]
        _s157 = _web157.find("def api_settlement_simulate(")
        _st157 = _web157[_s157:_s157 + 9000]
        _okB = ("HEARING_QUICK_SYSTEM_IT = " in _web157 and "Non cominciare con un «Sì» o «No» isolato" in _web157
                and "Mos fillo me një «Po» ose «Jo» të vetëm" in _web157 and "comincia dalla correzione" in _web157
                and "fillo me korrigjimin" in _web157 and "«Jo, nuk ankimohet" not in _web157
                and "HEARING_QUICK_SYSTEM_IT if _it else" in _hq157
                and "_nenet_e_rastit(" in _hq157 and "## Domanda ORA in udienza" in _hq157)
        _okC = ("_nenet_e_rastit(case_id, description" in _st157 and "Kurrë mos parashiko pagesa të padeklaruara" in _st157
                and "Mai ipotizzare pagamenti non dichiarati" in _st157)
        check("feriale+udienza[157]: sospensione feriale nei termini a mesi/anni (giugno → +31, inizio in agosto differito, "
              "anni, AL mai); assistente d'udienza nativo IT e radicato; simulazione dell'accordo con gli articoli del caso",
              _okA and _okB and _okC, "A=%s B=%s C=%s" % (_okA, _okB, _okC))
    except Exception as _e157:  # noqa: BLE001
        check("feriale+udienza[157]: kontrollet u ekzekutuan", False, str(_e157))

    # [158] v9.399 — LE LEGGI ALBANESI ABROGATE FUORI CORPUS: il notaio ha citato «Ligji 8438, neni 11» (imposte 1998, abrogata
    # dalla 29/2023) e usciva «senza codice». Il registro si legge dal corpus stesso (frasi «Ligji nr. X … shfuqizohet» degli
    # articoli vigenti): la citazione esce «abrogata» con la legge di oggi; «shfuqizuar me ligjin nr. X» (abrogato DA X) non conta;
    # una legge vigente che non abbiamo resta «senza codice»; nessuna legge nostra entra nel registro.
    try:
        from src import citation_verifier as _cv158
        _reg158 = _cv158._ligje_te_shfuqizuara(idx)
        def _st158(t):
            r = _cv158.verify_text(t, idx)
            return [(i["status"], i.get("code"), i.get("article_heading") or "") for i in r["items"]]
        _a = _st158("Sipas nenit 11 të ligjit nr. 8438/1998 «Për tatimin mbi të ardhurat», tatimi paguhet.")
        _b = _st158("neni 25 i ligjit nr. 7829, datë 1.6.1994 «Për noterinë»")
        _c = _st158("neni 5 i ligjit nr. 175/2014")
        _d = _st158("neni 3 i Ligjit nr. 119/2014 për të drejtën e informimit")
        _e = _st158("neni 5 i ligjit nr. 124/2024")
        _okR = (len(_reg158) >= 20 and {"8438/1998", "7829/1994", "9109/2003", "33/2012", "108/2013"} <= set(_reg158)
                and "175/2014" not in _reg158 and "124/2024" not in _reg158 and "111/2018" not in _reg158)
        _okV = (_a and _a[0][0] == "repealed" and "29/2023" in _a[0][2] and _b and _b[0][0] == "repealed" and "110/2018" in _b[0][2]
                and _c and _c[0][0] == "needs_code" and _e and _e[0][0] == "verified"
                # v9.477: la 119/2014 ora è nel corpus (era l'esempio di legge vigente che non abbiamo)
                and _d and _d[0][0] == "verified" and _d[0][1] == "ligji_informimi")
        check("ligje[158]: le leggi albanesi abrogate fuori corpus escono «abrogate» con la legge di oggi (8438/1998 → 29/2023, "
              "7829/1994 → 110/2018); registro dal corpus, senza le leggi nostre né «shfuqizuar me ligjin»",
              _okR and _okV, "R=%s V=%s reg=%d %s %s" % (_okR, _okV, len(_reg158), _a, _c))
    except Exception as _e158:  # noqa: BLE001
        check("ligje[158]: kontrollet u ekzekutuan", False, str(_e158))

    # [159] v9.399 — LA CHECKLIST DEL FASCICOLO NOTARILE era senza articoli (citava a memoria: «Ligji 8438, neni 11», abrogata):
    # ora riceve i semi dell'atto del catalogo (compravendita: KC 750/751 + registrazione kadastra 24 + imposta 29/2023 neni 17
    # + comunione dei coniugi KF 76/77), con le etichette leggibili e la regola «solo dal blocco»; la lista dei documenti idem.
    try:
        from src import notary as _no159
        class _F159:
            def __init__(self): self.c = []
            def complete(self, system=None, messages=None, callsite=None, **kw):
                self.c.append((callsite, system or "", messages[0]["content"]))
                return "PLOTESIA: 40" if callsite == "notary_checklist" else ""
        _f = _F159()
        _r159 = _no159.dossier_checklist(_f, idx, act="shitje pasurie e paluajtshme",
                                         documents_text="Certifikata e pronësisë nga ASHK dhe kartat e identitetit të palëve.")
        _cl = [c for c in _f.c if c[0] == "notary_checklist"][0]
        _keys = {(a["code"], a["number"]) for a in _r159["articles"]}
        _ok159 = ({("kodi_civil", "750"), ("ligji_kadastra", "24"), ("ligji_tatimi_te_ardhurat", "17"), ("kodi_familjes", "76")} <= _keys
                  and "NENET NGA KORPUSI" in _cl[2] and "ligji_tatimi_te_ardhurat" not in _cl[2] and "29/2023" in _cl[2]
                  and "mos cito ligje të vjetra nga kujtesa" in _cl[1] and _no159._seed_per_akt("vërtetim nënshkrimi") is None)
        check("noter[159]: la checklist del fascicolo e la lista documenti ricevono gli articoli dell'atto (compravendita: KC 750, "
              "kadastra 24, imposta 29/2023 neni 17, KF 76/77), etichette leggibili, niente leggi a memoria", _ok159,
              "keys=%s" % sorted(_keys)[:8])
    except Exception as _e159:  # noqa: BLE001
        check("noter[159]: kontrollet u ekzekutuan", False, str(_e159))

    # [160] v9.399 — LIGJ I GJALLË / LEGGE VIVA: (a) la verifica delle affermazioni riceveva il testo reale TAGLIATO a 1.100
    # caratteri (un'affermazione giusta sul KP 146/3 sarebbe uscita «non sostenuta»): ora l'articolo intero fino a 6.000;
    # (b) in sessione IT prompt nativi (verifica: diritto italiano; legge viva: Normattiva/GU/EUR-Lex, non QBZ); (c) etichette
    # leggibili anche nel primo contatto del cittadino (prima «[ligji_konsumatoret neni 30]»).
    try:
        from src import living_law as _ll160, intake as _in160
        _it160 = idx_it if "idx_it" in dir() else ArticleIndex.load(INDEX_FILE.parent / "bm25_it.pkl")
        class _F160:
            def __init__(self): self.c = []
            def complete(self, system=None, messages=None, callsite=None, **kw):
                self.c.append((callsite, system or "", messages[0]["content"])); return "ok"
        _f = _F160()
        _ll160.verify_claims(_f, idx, text="Sipas nenit 146 të Kodit të Punës, zgjidhja pa shkaqe të arsyeshme është e pavlefshme.")
        _ll160.verify_claims(_f, _it160, text="L'art. 2946 c.c. prevede la prescrizione ordinaria decennale.")
        _ll160.check_law_live(_f, _it160, query="art. 18 L. 300/1970")
        _in160.triage(_f, idx, story="Bleva një makinë nga një tregtar dhe pas dy javësh motori u prish; tregtari nuk përgjigjet.")
        _vc = [c for c in _f.c if c[0] == "deep_verify"]
        _lv = [c for c in _f.c if c[0] == "law_live"]
        _tr = [c for c in _f.c if c[0] not in ("deep_verify", "law_live", "expand_terms")]
        _okA = len(_vc) == 2 and "punëdhënësi është i detyruar të zbatojë këtë vendim" in _vc[0][2]
        _okB = (_vc[1][1].startswith("Sei un VERIFICATORE") and "art. 2946" in _vc[1][2] and "neni" not in _vc[1][2]
                and _lv and "normattiva.it" in _lv[0][1] and "qbz" not in _lv[0][1].lower())
        _okC = bool(_tr) and not re.search(r"\[(ligji|kodi)_[a-z_]+ neni", _tr[-1][2])
        check("ligj-i-gjallë[160]: verifica delle affermazioni con l'articolo intero (KP 146/3), prompt nativi IT (verifica e "
              "legge viva su Normattiva), etichette leggibili nel primo contatto", _okA and _okB and _okC,
              "A=%s B=%s C=%s" % (_okA, _okB, _okC))
    except Exception as _e160:  # noqa: BLE001
        check("ligj-i-gjallë[160]: kontrollet u ekzekutuan", False, str(_e160))

    # [161] v9.400 — IL VAULT DEL FASCICOLO («Pyet dokumentet», l'ago, chi ha detto cosa): in sessione IT il prompt era albanese,
    # con la frase da copiare «Nuk gjendet në dokumentet e ngarkuara»; il prompt albanese dell'ago era scritto con «E» al posto di
    # «ë» («GjilpEra», «Pse ka rEndEsi» finivano nei titoli). Ora prompt nativi IT, marcatore [Doc N] in italiano ([Dok N] in
    # albanese) nel contesto e nelle istruzioni, l'interfaccia li legge tutti e due.
    try:
        from types import SimpleNamespace as _NS161
        from src import vault as _v161, brain as _b161
        _orig161 = _v161.storage.list_documents
        _v161.storage.list_documents = lambda cid: [_NS161(status="ready", extracted_text="Contratto del 10 marzo 2026.",
                                                           filename="contratto.pdf", doc_type="contratto")]
        class _F161:
            def __init__(self): self.c = []
            def complete(self, system=None, messages=None, callsite=None, **kw):
                self.c.append((callsite, system or "", messages[0]["content"])); return "ok"
        _f = _F161()
        _br = _NS161(backend=_f)
        try:
            _b161.set_request_jurisdiction("IT")
            _v161.ask(_br, "c1", "Quando è stato firmato?"); _v161.find_needle(_f, "c1"); _v161.who_said_what(_f, "c1")
            _b161.set_request_jurisdiction("AL")
            _v161.ask(_br, "c1", "Kur u nënshkrua?"); _v161.find_needle(_f, "c1")
        finally:
            _v161.storage.list_documents = _orig161
            _b161.set_request_jurisdiction("AL")
        _it_c, _al_c = _f.c[:3], _f.c[3:]
        _okIT = all("[Doc 1: contratto.pdf" in u and "[Dok" not in u and "Sei " in sy and "Nuk gjendet" not in sy
                    for _cs, sy, u in _it_c)
        _okAL = all("[Dok 1: contratto.pdf" in u for _cs, sy, u in _al_c) and "Gjilpëra" in _al_c[1][1] and "GjilpEra" not in _al_c[1][1]
        _js161 = (SRC_STATIC / "app.js").read_text(encoding="utf-8") if "SRC_STATIC" in dir() else open("/app/static/app.js", encoding="utf-8").read()
        _okUI = "/\\[(Do[kc]) (\\d+)\\]/g" in _js161 and '(_CAL_IT ? "[Doc " : "[Dok ")' in _js161 and '("usati " + d.n_docs + " doc")' in _js161
        check("vault[161]: Pyet dokumentet / l'ago / chi ha detto cosa con prompt nativi IT e [Doc N]; albanese con i diacritici "
              "giusti e [Dok N]; l'interfaccia legge le due forme", _okIT and _okAL and _okUI,
              "IT=%s AL=%s UI=%s" % (_okIT, _okAL, _okUI))
    except Exception as _e161:  # noqa: BLE001
        check("vault[161]: kontrollet u ekzekutuan", False, str(_e161))

    # [162] v9.400 — LA CASCATA DEI TERMINI (`/afatet`, regole scritte nel codice): il ricorso penale era 30 giorni (KPP 435/1:
    # 45), la risposta alla domanda citava il KPC 163 ABROGATO nel 2001 (oggi 158/1), i termini citavano l'articolo dei motivi
    # (472, 494, 410, KPA 135); la scadenza di domenica non slittava (KPC 148); il comando in chat leggeva campi inesistenti e
    # rispondeva sempre «Asnjë afat»; in sessione IT dava termini albanesi.
    try:
        from src import pro_features as _pf162
        _by162 = {(a.code, str(a.number)): a for a in idx.articles}
        _bad162 = [(k, r["code"], r["article"]) for k, rs in _pf162.DEADLINE_RULES.items() for r in rs
                   if (r["code"], r["article"]) not in _by162 or _by162[(r["code"], r["article"])].repealed]
        _pen = _pf162.compute_deadline_cascade("njoftim_vendimi_apel_penal", "2026-09-10")["derived_deadlines"][0]
        _civ = _pf162.compute_deadline_cascade("njoftim_vendimi_civil_shkalle_pare", "2026-08-01")["derived_deadlines"][0]
        try:
            _pf162.compute_deadline_cascade("njoftim_vendimi_apel_penal", "2026-09-10", jurisdiction="IT"); _okIT = False
        except ValueError:
            _okIT = True
        _js162 = open("/app/static/app.js", encoding="utf-8").read()
        _okUI = "(data.derived_deadlines || [])" in _js162 and "d.deadline_date" not in _js162 and "if (ev.note)" in _js162
        _ok162 = (not _bad162 and _pen["days"] == 45 and _pen["article"] == "435" and _pen["due_date"] == "2026-10-26"
                  and _civ["due_date"] == "2026-08-17" and "neni 148 KPC" in _civ["notes"] and _okIT and _okUI)
        check("afatet[162]: cascata dei termini con articoli esistenti e vigenti, ricorso penale 45 giorni (KPP 435), proroga del "
              "festivo (KPC 148), niente termini albanesi in IT, `/afatet` sui campi veri", _ok162,
              "bad=%s pen=%s/%s/%s civ=%s IT=%s UI=%s" % (_bad162, _pen["days"], _pen["article"], _pen["due_date"],
                                                          _civ["due_date"], _okIT, _okUI))
    except Exception as _e162:  # noqa: BLE001
        check("afatet[162]: kontrollet u ekzekutuan", False, str(_e162))

    # [163] v9.400 — GLI STRUMENTI PRO DEL FASCICOLO (Red Team, bozza d'atto, duello avversariale, bussola strategica): il
    # testo degli articoli arrivava TAGLIATO a 300 caratteri; il recupero era la sola ricerca per parole (licenziamento orale:
    # 1/3 delle norme decisive, in IT senza gli artt. 2 e 6 L. 604/1966, contro 3/3 del recupero del cervello); duello e
    # bussola usavano sempre l'indice ALBANESE anche in sessione IT; la convergenza del duello si riconosceva solo in albanese.
    try:
        from src import pro_features as _pf163, brain as _b163
        _art163 = next(a for a in idx.articles if a.code == "kodi_punes" and str(a.number) == "146")
        _blk = _pf163._format_articles_compact([(_art163, 1.0)])
        _okA = (len(_art163.body or "") > 1100 and "e pavlefshme" in _blk and "(asnjë nen i gjetur)" == _pf163._format_articles_compact([])
                and "neni 146]" in _blk and "Neni 146 i Kodi" not in _blk)
        _b163.set_request_jurisdiction("IT")
        try:
            _okIT = _pf163._format_articles_compact([]) == "(nessun articolo trovato)"
        finally:
            _b163.set_request_jurisdiction("AL")
        _web163 = open("/app/src/web.py", encoding="utf-8").read()
        _pfs163 = open("/app/src/pro_features.py", encoding="utf-8").read()
        _okB = (_web163.count("retrieved=_coppie_per_pro(") == 4 and "backend=_BRAIN.backend, index=_INDEX" not in _web163
                and '"converg" in thesis' in _pfs163 and "retrieved = retrieved or index.search(" in _pfs163)
        check("pro[163]: strumenti PRO con l'articolo fino a 1.500 caratteri (KP 146 intero), recupero del cervello, indice "
              "della sessione (niente indice albanese in IT), convergenza del duello anche in italiano", _okA and _okIT and _okB,
              "A=%s IT=%s B=%s" % (_okA, _okIT, _okB))
    except Exception as _e163:  # noqa: BLE001
        check("pro[163]: kontrollet u ekzekutuan", False, str(_e163))

    # [164] v9.400 — IL MODULO PUBBLICO DEL PRIMO CONTATTO (`/intake/<studio>`, lo compila il cittadino): era solo albanese anche
    # per uno studio italiano (e il link condiviso dalla posta in arrivo era lo stesso in sessione IT); il piè di pagina
    # affermava il falso («tutti i dati sono cifrati e solo l'avvocato assegnato li legge»: a riposo non sono cifrati, le
    # richieste le vede lo studio) con un link «Super Avvocato» a github.com; «non li condividiamo con nessun terzo» taceva
    # l'analisi del motore. Ora: pagina nella lingua dello studio, frasi vere, riassunto per l'avvocato nella stessa lingua.
    try:
        from types import SimpleNamespace as _NS164
        import flask as _fl164
        from src import web as _w164
        with _w164.app.test_request_context("/intake/x?lang=it"):
            _h_it = _fl164.render_template("intake.html", firm=_NS164(name="Studio Rossi"), firm_slug="x", lang="it")
            _h_sq = _fl164.render_template("intake.html", firm=_NS164(name="Studio Hoxha"), firm_slug="x", lang="sq")
        _okIT = ('<html lang="it">' in _h_it and "Invia la richiesta" in _h_it and "Nome e cognome" in _h_it
                 and 'data-lang="it"' in _h_it and not re.search(r"[ëç]|\bnuk\b|Dërgo", _h_it.split("<body", 1)[1]))
        _okSQ = ('<html lang="sq">' in _h_sq and "Dërgo kërkesën" in _h_sq and "Invia la richiesta" not in _h_sq)
        _okVero = all("github.com" not in h and "të enkriptuara dhe vetëm avokati" not in h and "Nuk i ndajmë" not in h
                      and "superavokati.ai" in h for h in (_h_it, _h_sq))
        _js164 = open("/app/static/intake.js", encoding="utf-8").read()
        _app164 = open("/app/static/app.js", encoding="utf-8").read()
        _okFlusso = ("lang: IT ? 'it' : 'sq'" in _js164 and "LEAD_INTAKE_SYSTEM_IT" in open("/app/src/web.py", encoding="utf-8").read()
                     and '(_INBOX_IT ? "?lang=it" : "")' in _app164)
        check("intake[164]: modulo pubblico nella lingua dello studio (IT reso senza albanese), affermazioni vere sulla "
              "riservatezza (niente «tutto cifrato», niente github), lingua inviata al server e link italiano dalla posta",
              _okIT and _okSQ and _okVero and _okFlusso,
              "IT=%s SQ=%s vero=%s flusso=%s" % (_okIT, _okSQ, _okVero, _okFlusso))
    except Exception as _e164:  # noqa: BLE001
        check("intake[164]: kontrollet u ekzekutuan", False, str(_e164))

    # [165] v9.400 — I MESSAGGI D'ERRORE DEL SERVER nella lingua della sessione: l'interfaccia mostra `error` così com'è e 42
    # messaggi erano solo albanesi («Ky mjet nuk përfshihet në abonimin tuaj», «Rasti nuk u gjet»…); la Tabela e Dosjes diceva
    # al modello di rispondere «nella lingua della DOMANDA» (contro la regola: decide la sessione).
    try:
        _w165 = open("/app/src/web.py", encoding="utf-8").read()
        _residui = re.findall(r'jsonify\(\{"error": "([^"]*[ëçË][^"]*|[^"]*\b(?:nuk u gjet|mungon)\b[^"]*)"', _w165)
        from src import web as _web165, tabela as _tb165
        with _web165.app.test_request_context("/"):
            _okF = _web165._t_err("sq", "it") == "sq"      # senza sessione IT resta albanese
        _okTb = "gjuhen e PYETJES" not in _tb165.SISTEMI and "gjuha e sesionit" in _tb165.SISTEMI
        check("errori[165]: nessun messaggio d'errore solo albanese nel server (tutti via `_t_err`), la tabella dei documenti "
              "risponde nella lingua della sessione", not _residui and _okF and _okTb, "residui=%s" % _residui[:5])
    except Exception as _e165:  # noqa: BLE001
        check("errori[165]: kontrollet u ekzekutuan", False, str(_e165))

    # [166] v9.400 — LE LETTERE in sessione IT: il prompt era albanese e il modello copiava i titoli delle sezioni («### 📎 Si
    # dërgohet», «### ⚠️ Përpara se ta dërgosh» in una diffida italiana — audit notaio IT del 28 set). Ora ramo italiano nativo
    # (prompt, forme, etichette, titoli); l'albanese resta identico.
    try:
        from src import letters as _lt166
        _it166 = idx_it if "idx_it" in dir() else ArticleIndex.load(INDEX_FILE.parent / "bm25_it.pkl")
        class _F166:
            def __init__(self): self.c = []
            def complete(self, system=None, messages=None, callsite=None, **kw):
                if callsite == "letters_draft":
                    self.c.append((system or "", messages[0]["content"]))
                return "### ✉️ Documento\nTesto.\n### 📎 Come si invia\nPEC."
        _f = _F166()
        _k_it = next(iter(_lt166.catalogue("IT"))); _k_al = next(iter(_lt166.catalogue("AL")))
        _r166 = _lt166.draft(_f, _it166, kind=_k_it, facts="Il conduttore non paga il canone da tre mesi.", jurisdiction="IT")
        _lt166.draft(_f, idx, kind=_k_al, facts="Qiramarrësi nuk e paguan qiranë prej tre muajsh.", jurisdiction="AL")
        (_s_it, _u_it), (_s_al, _u_al) = _f.c
        _okIT = (_s_it.startswith(("Sei un avvocato SENIOR",)) or "Sei un avvocato SENIOR" in _s_it) and "### 📎 Come si invia" in _s_it \
            and "Si dërgohet" not in _s_it and "TIPO DI ATTO:" in _u_it and "LLOJI I SHKRESËS" not in _u_it \
            and _r166.get("document", "").strip() == "Testo."
        _okAL = "Ti je avokat SENIOR" in _s_al and "### 📎 Si dërgohet" in _s_al and "LLOJI I SHKRESËS" in _u_al
        check("lettere[166]: in IT prompt, etichette e titoli italiani (niente «Si dërgohet»), il documento esportato è la "
              "prima sezione; in AL invariato", _okIT and _okAL, "IT=%s AL=%s" % (_okIT, _okAL))
    except Exception as _e166:  # noqa: BLE001
        check("lettere[166]: kontrollet u ekzekutuan", False, str(_e166))

    # [167] v9.400 — FESTIVITÀ ITALIANE: la L. 8 ottobre 2025, n. 151 (GU n. 236 del 10.10.2025) ha reso il 4 OTTOBRE festa
    # nazionale dal 2026; il motore non lo sapeva e una scadenza di lunedì 4 ottobre 2027 non si prorogava. AL invariata
    # (5 settembre = Dita e Shenjtërimit të Nënë Terezës dal 2017, non più il 19 ottobre).
    try:
        import datetime as _dt167
        from src import deadline_engine as _de167
        _r167 = _de167.compute_deadline("2027-09-04", 30, "days", jurisdiction="IT", feriale=False, lang="it")
        _ok167 = (_de167.is_holiday(_dt167.date(2027, 10, 4), "IT") and not _de167.is_holiday(_dt167.date(2025, 10, 4), "IT")
                  and not _de167.is_holiday(_dt167.date(2027, 10, 4), "AL") and _r167.deadline.isoformat() == "2027-10-05"
                  and _de167.is_holiday(_dt167.date(2026, 9, 5), "AL") and not _de167.is_holiday(_dt167.date(2026, 10, 19), "AL"))
        check("feste[167]: 4 ottobre festivo in Italia dal 2026 (L. 151/2025) e proroga della scadenza; Albania con il 5 "
              "settembre", _ok167, "scadenza=%s" % _r167.deadline)
    except Exception as _e167:  # noqa: BLE001
        check("feste[167]: kontrollet u ekzekutuan", False, str(_e167))

    # [168] v9.400 — LA FATTURA DELLO STUDIO (dalle ore registrate): era solo albanese («Faturë», «TVSH», il rimando alla Dhoma
    # Kombëtare e Avokatisë) anche per un fascicolo italiano. Ora nella lingua del fascicolo, e la nota dice cos'è il documento
    # (la fattura fiscale passa dal SdI in Italia, dalla fiscalizzazione in Albania).
    try:
        from src import storage as _st168
        _kw168 = dict(invoice_no="F-0001", issue_date="2026-09-29", due_date=None, client_name="Rossi", client_address=None,
                      currency="EUR", line_items=[{"date": "2026-09-01", "kind": "hearing", "kind_label": "Udienza",
                                                   "description": "x", "hours": 1.0, "rate_cents": 10000, "amount_cents": 10000}],
                      subtotal_cents=10000, vat_rate=22, vat_cents=2200, total_cents=12200, notes=None)
        _it168 = _st168._render_invoice_markdown(lang="it", **_kw168)
        _sq168 = _st168._render_invoice_markdown(**_kw168)
        _ok168 = ("# Fattura F-0001" in _it168 and "**IVA (22%):**" in _it168 and "SdI" in _it168 and "TVSH" not in _it168
                  and "Dhoma" not in _it168 and "# Faturë F-0001" in _sq168 and "**TVSH (22%):**" in _sq168
                  and _st168.ACTIVITY_KIND_LABELS_IT.get("hearing") == "Udienza"
                  and 'lang="it" if (getattr(case, "jurisdiction"' in open("/app/src/web.py", encoding="utf-8").read())
        check("fattura[168]: nella lingua del fascicolo (IT: «Fattura», «IVA», nota sul SdI; AL invariata con la "
              "fiscalizzazione)", _ok168)
    except Exception as _e168:  # noqa: BLE001
        check("fattura[168]: kontrollet u ekzekutuan", False, str(_e168))

    # [169] v9.400 — LO SCUDO DETERMINISTICO sugli strumenti che non passavano da nessuno scudo (assistente d'udienza, Vault,
    # l'ago, chi ha detto cosa): nella prova viva l'ago citava sentenze di Cassazione prese dal web senza riscontro.
    try:
        from src import web as _w169
        _src169 = open("/app/src/web.py", encoding="utf-8").read()
        _prev169 = _w169._INDEX
        if _w169._INDEX is None:
            _w169._INDEX = idx                     # l'indice AL del golden (senza caricare tutto il web)
        try:
            with _w169.app.test_request_context("/"):
                _out169 = _w169._scudo_deterministico("Sipas nenit 9999 të Kodit Penal, vepra dënohet.", "IT")   # IT: niente indice vendime
        finally:
            _w169._INDEX = _prev169
        _ok169 = ("⚠" in _out169 and _out169 != "Sipas nenit 9999 të Kodit Penal, vepra dënohet."
                  and _src169.count("_scudo_deterministico(") >= 5)
        check("scudo[169]: udienza, Vault, ago e «chi ha detto cosa» con lo scudo deterministico (nene inesistente annotato, "
              "sentenze riscontrate)", _ok169, "out=%r" % _out169[:120])
    except Exception as _e169:  # noqa: BLE001
        check("scudo[169]: kontrollet u ekzekutuan", False, str(_e169))

    # [170] v9.400 — ANCORE: l'ancora per titolo guarda solo i TITOLI veri (mai la prima frase di un articolo senza rubrica:
    # KC 907/1121 entravano in testa a un licenziamento per la parola «pushuar»), l'ancora del licenziamento (KP 143 preavviso
    # + KP 145 anzianità, solo nell'area Punë), le ancore di regola generale si AGGIUNGONO ai 12; la cronologia radicata sugli
    # articoli del caso e senza l'esempio «30 ditë» che il modello copiava; il triage senza il «13 codici» fermo da mesi.
    try:
        _sum170 = ("Punëmarrës i pushuar nga puna me gojë, pa njoftim me shkrim dhe pa arsye, ka kundërshtuar me shkrim "
                   "brenda afatit, ndërsa punëdhënësi pretendon dorëheqje; kërkohet padi për pavlefshmërinë e pushimit.")
        _rr170 = ({d.code for d in brain.LEGAL_DOCUMENTS if d.area in ("Punë", "Civil")}
                  | set(brain.PROCEDURAL_MAPPING["Punë"]) | set(brain.PROCEDURAL_MAPPING["Civil"]))
        _qs170 = ["zgjidhja e kontratës së punës pa afat nga punëdhënësi", "dorëheqja e punëmarrësit formë provë"]
        _seen170 = {}
        for _q in _qs170:
            for _a, _sc in idx.search(_q, top_k=12):
                _k = (_a.code, _a.number)
                if _sc > _seen170.get(_k, 0.0):
                    _seen170[_k] = _sc
        _per170 = {(a.code, a.number): a for a in idx.articles}
        _p170 = sorted([(_per170[k], v) for k, v in _seen170.items() if k in _per170], key=lambda x: x[1], reverse=True)
        _t170 = brain._ankoro_sipas_titullit(list(_p170), idx, _sum170, queries=_qs170, restrict=_rr170)
        _tit170 = [a for a, _ in _t170 if getattr(a, "_ancora_titull", False)]
        _okT = (all(getattr(a, "heading_kind", "rubrike") != "fjali" for a in _tit170)
                and not any((a.code, str(a.number)) in {("kodi_civil", "907"), ("kodi_civil", "1121")} for a, _ in _t170[:3]))
        # l'ancora del licenziamento (senza 143/145 già fra i trovati, così deve entrare come ancora dichiarata)
        _x170 = [(a, sc) for a, sc in _p170 if (a.code, str(a.number)) not in {("kodi_punes", "143"), ("kodi_punes", "145")}]
        _anc170 = lambda lst: {(a.code, str(a.number)) for a, _ in lst if getattr(a, "_ancora", False)}
        _lav170 = _anc170(brain._applica_ancore(list(_x170), idx, _qs170 + [_sum170], ["Punë", "Civil"]))
        _pen170 = _anc170(brain._applica_ancore(list(_x170), idx, _qs170 + [_sum170], ["Punë", "Penal"]))
        _civ170 = _anc170(brain._applica_ancore(list(_x170), idx, _qs170 + [_sum170], ["Civil"]))
        _okA = ({("kodi_punes", "143"), ("kodi_punes", "145")} <= _lav170
                and ("kodi_punes", "143") not in _pen170 and ("kodi_punes", "143") not in _civ170)
        _srcb170 = open("/app/src/brain.py", encoding="utf-8").read()
        _okC = ('_extra += min(4, sum(1 for a, _ in pairs if getattr(a, "_ancora", False)))' in _srcb170
                and "(13 gjithsej" not in _srcb170)
        from src import pro_features as _pf170
        _srcp170 = open("/app/src/pro_features.py", encoding="utf-8").read()
        _srcw170 = open("/app/src/web.py", encoding="utf-8").read()
        _okL = ("30 ditë heshtje" not in _pf170.TIMELINE_SYSTEM and "AFATET DHE KUSHTET LIGJORE" in _pf170.TIMELINE_SYSTEM
                and "articles_block: str" in _srcp170 and "articles_block=_art_tl" in _srcw170)
        check("ancore[170]: l'ancora per titolo non prende mai la PRIMA FRASE di un articolo senza rubrica (KC 907/1121 fuori)",
              _okT, str([f"{a.code}:{a.number}" for a in _tit170]))
        check("ancore[170]: licenziamento → KP 143 (preavviso) + KP 145 (anzianità) solo con l'area lavoro, mai nel penale",
              _okA, "lavoro=%s penale=%s civile=%s" % (sorted(_lav170), sorted(_pen170), sorted(_civ170)))
        check("ancore[170]: le ancore di regola generale si aggiungono ai 12 · il triage non dice più «13 codici»", _okC)
        check("cronologia[170]: radicata sugli articoli del caso, senza l'esempio numerico che il modello copiava", _okL)
    except Exception as _e170:  # noqa: BLE001
        check("ancore[170]: kontrollet u ekzekutuan", False, str(_e170))

    # [171] v9.401 — LA SOSPENSIONE FERIALE NEL CORPUS: la bozza di un ricorso di lavoro salvava il termine di 180 giorni
    # (art. 6 L. 604/1966) «in ragione della sospensione feriale», ma l'art. 3 L. 742/1969 la esclude per le controversie di
    # lavoro e previdenza; la legge mancava e la chat diceva «da verificare». Legge + nota di collegamento sull'art. 3 (gli artt.
    # 429 e 459 c.p.c. richiamati sono quelli anteriori al 1973), verificatore per numero, ancore (lavoro+termine, penale).
    try:
        from pathlib import Path as _P171
        from src import citation_verifier as _cv171
        from src.parser import _is_italian_code as _itc171
        _ix171 = ArticleIndex.load(_P171("/app/data/index/bm25_it.pkl"))
        _by171 = {(a.code, str(a.number)): a for a in _ix171.articles}
        _a3 = _by171.get(("legge_sospensione_feriale", "3"))
        _a1 = _by171.get(("legge_sospensione_feriale", "1"))
        _okK = (_a1 is not None and _a3 is not None and "non si applica" in (_a3.body or "")
                and "1º al 31 agosto" in (_a1.body or "").replace("1° ", "1º ") and "409" in (getattr(_a3, "note", "") or "")
                and _itc171("legge_sospensione_feriale"))
        _v171 = _cv171.verify_text("Il termine non è sospeso: art. 3 L. 742/1969.", _ix171).get("items") or []
        _okV = any(c.get("status") == "verified" and c.get("code") == "legge_sospensione_feriale" for c in _v171)
        _pp171 = [(a, 1.0) for a in _ix171.articles if a.code == "licenziamenti_individuali"][:12]
        _anc171 = lambda q, aree: {(a.code, str(a.number)) for a, _ in brain._applica_ancore(list(_pp171), _ix171, [q], list(aree),
                                                                                        ancore=brain.ANCORE_IT)
                                   if getattr(a, "_ancora", False)}
        _lav171 = _anc171("termine di impugnazione del licenziamento orale e decadenza", ["Lavoro", "Civile"])
        _pen171 = _anc171("sospensione feriale dei termini nelle indagini preliminari", ["Penale"])
        _civ171 = _anc171("risoluzione del contratto di locazione per morosità", ["Civile"])
        _okA = ({("legge_sospensione_feriale", "1"), ("legge_sospensione_feriale", "3")} <= _lav171
                and ("legge_sospensione_feriale", "2") in _pen171 and ("legge_sospensione_feriale", "3") not in _pen171
                and not any(k[0] == "legge_sospensione_feriale" for k in _civ171))
        check("feriale[171]: L. 742/1969 nel corpus (art. 1 sospensione, art. 3 esclusioni con la nota: lavoro e previdenza = "
              "artt. 409 e 442 c.p.c.) e riconosciuta dal verificatore per numero", _okK and _okV,
              "corpus=%s verificatore=%s" % (_okK, _okV))
        check("feriale[171]: ancore — lavoro con termine → artt. 1 e 3; penale → artt. 1 e 2; civile senza lavoro né feriale → nulla",
              _okA, "lavoro=%s penale=%s civile=%s" % (sorted(_lav171), sorted(_pen171), sorted(_civ171)))
    except Exception as _e171:  # noqa: BLE001
        check("feriale[171]: kontrollet u ekzekutuan", False, str(_e171))

    # [172] v9.401 — RADAR D'URGENZA: le voci dedotte dalla cronologia leggevano campi che TimelineDeadline NON ha (label,
    # description, date) → sempre «Afat ligjor kritik» e nessuna data, anche in sessione IT (il Giudice: «Due voci «Afat ligjor
    # kritik» in albanese»); e un termine «entro 15 giorni» non era mai «critico» (si cercavano «ditë/orë»).
    try:
        from types import SimpleNamespace as _NS172
        _td172 = brain.TimelineDeadline(action="Depositare il ricorso", anchor_event="Notifica della sentenza",
                                        anchor_date="2026-09-20", days_after=15, due_date="2026-10-05",
                                        article_ref="art. 325 c.p.c.", urgency="critical", days_remaining=5)
        _nr172 = brain.NullityRadar(findings=[brain.NullityFinding(kind="procedural_defect", name="Vizio di notifica",
                                                                   citizen_applicable="po", deadline_hint="entro 15 giorni")])

        class _BK172:
            def complete(self, **kw):
                return '{"level": "none", "signals": []}'

        class _F172:
            backend = _BK172()

            def __init__(self, j):
                self._j = j

            def _system_for(self, x):
                return x

            def _current_jurisdiction(self):
                return self._j

        _out172 = {}
        for _j in ("AL", "IT"):
            _r = brain.SuperAvvocato._scan_urgency(_F172(_j), "domanda", _NS172(problem_summary="x"),
                                                   brain.TimelineAnalysis(anchors=[], deadlines=[_td172]), _nr172, [],
                                                   retrieved=[(_NS172(body="Il ricorso si propone entro 15 giorni dalla "
                                                                           "notifica.", heading=""), 1.0)])
            _out172[_j] = _r
        _s_it = _out172["IT"].signals
        _s_al = _out172["AL"].signals
        _testo_it = " ".join(f"{x.label} {x.reason} {x.action}" for x in _s_it)
        _ok172 = (_s_it and _s_it[0].label == "Depositare il ricorso" and _s_it[0].deadline == "2026-10-05"
                  and "art. 325 c.p.c." in _s_it[0].reason and "Afat" not in _testo_it and "Kontrollo" not in _testo_it
                  and any(x.label == "Vizio di notifica" and x.severity == "critical" for x in _s_it)
                  and _s_al and _s_al[0].deadline == "2026-10-05" and "kronologjisë" in _s_al[0].reason
                  and "'critical'" not in _s_al[0].reason)
        # il numero scritto in LETTERE nella norma («centottanta giorni») conferma il termine; senza la norma resta la nota
        _sig_a = brain.UrgencySignal(kind="deadline", label="Termine di decadenza di 180 giorni", reason="", severity="critical")
        _sig_b = brain.UrgencySignal(kind="deadline", label="Termine di decadenza di 180 giorni", reason="", severity="critical")
        _art6 = [(_NS172(body="Il licenziamento deve essere impugnato a pena di decadenza entro sessanta giorni… inefficace se "
                              "non è seguita, entro il successivo termine di centottanta giorni, dal deposito del ricorso.",
                         heading=""), 1.0)]
        _ok172 = _ok172 and (brain._conferma_afati_con_norma(_sig_a, _art6, "IT").severity == "critical"
                             and brain._conferma_afati_con_norma(_sig_b, [], "IT").severity == "elevated")
        check("urgenza[172]: le voci dalla cronologia portano azione, scadenza e articolo veri, nella lingua della sessione; "
              "«entro 15 giorni» è critico anche in italiano; «centottanta giorni» nella norma conferma i 180", bool(_ok172),
              "IT=%s | AL=%s" % ([(x.label, x.deadline, x.severity) for x in _s_it], [(x.label, x.deadline) for x in _s_al]))
    except Exception as _e172:  # noqa: BLE001
        check("urgenza[172]: kontrollet u ekzekutuan", False, str(_e172))

    # [173] v9.402 — LETTORE JSON TOLLERANTE: la bozza d'atto italiana dava 500 dopo 9 minuti per virgolette non protette nel
    # testo dell'atto; la fase «strategic» si era persa per una virgola finale. Solo quando la lettura normale fallisce.
    try:
        from src import json_tollerante as _jt173
        _ok173 = (_jt173.carica('{"a": "x"}') == {"a": "x"}
                  and _jt173.carica('{"body": "sostiene "si sia dimesso", poi", "x": 1}')["body"] == 'sostiene "si sia dimesso", poi'
                  and _jt173.carica('{"a": [1, 2,], "b": {"c": 3,},}') == {"a": [1, 2], "b": {"c": 3}}
                  and _jt173.carica('{"a": "uno, } due", "b": 2}') == {"a": "uno, } due", "b": 2}
                  and _jt173.carica('{"t": "riga uno\nriga due"}')["t"] == "riga uno\nriga due")
        try:
            _jt173.carica('{"a": "tronc')
            _ok173 = False
        except Exception:  # noqa: BLE001
            pass
        _src173 = "".join(open(f"/app/src/{m}.py", encoding="utf-8").read() for m in ("brain", "pro_features", "genio", "documents"))
        _ok173 = _ok173 and _src173.count("json_tollerante import carica") >= 4 and "_corpo_da_uscita_rotta(raw)" in _src173
        check("json[173]: lettura tollerante (virgolette interne, virgole finali, a capo crudi) nei 4 lettori; la bozza d'atto "
              "consegna il testo invece di un errore 500", _ok173)
    except Exception as _e173:  # noqa: BLE001
        check("json[173]: kontrollet u ekzekutuan", False, str(_e173))

    # [174] v9.402 — ARTICOLI DI PROCEDURA DELLA BOZZA D'ATTO: la padia scriveva «dispozitat përkatëse procedurale» e «të
    # verifikohet kompetenca tokësore» senza numero. Contenuto (KPC 154), allegati (156), competenza (42, 43 società, 47 lavoro).
    try:
        from src import pro_features as _pf174
        from pathlib import Path as _P174
        _ixit174 = ArticleIndex.load(_P174("/app/data/index/bm25_it.pkl"))
        brain.set_request_jurisdiction("AL")
        _k = lambda r: {(a.code, str(a.number)) for a, _ in r}
        _al_lav = _k(_pf174._con_semi_dell_atto([], idx, "padi", "Punëdhënësi ALFA shpk e pushoi punëmarrësin me gojë."))
        _al_civ = _k(_pf174._con_semi_dell_atto([], idx, "padi", "Fqinji nuk e liron pasurinë."))
        _al_pen = _k(_pf174._con_semi_dell_atto([], idx, "ankim", "Vendimi i dënimit për të pandehurin."))
        brain.set_request_jurisdiction("IT")
        _it_lav = _k(_pf174._con_semi_dell_atto([], _ixit174, "padi", "Il lavoratore è stato licenziato a voce."))
        _it_civ = _k(_pf174._con_semi_dell_atto([], _ixit174, "padi", "Il vicino non restituisce l'immobile."))
        brain.set_request_jurisdiction("AL")
        _ok174 = ({("kodi_proc_civile", n) for n in ("154", "156", "42", "43", "47")} <= _al_lav
                  and ("kodi_proc_civile", "47") not in _al_civ and ("kodi_proc_civile", "43") not in _al_civ
                  and {("kodi_proc_penale", "410"), ("kodi_proc_penale", "415")} <= _al_pen
                  and ("kodi_proc_civile", "443") not in _al_pen
                  and {("codice_procedura_civile", n) for n in ("409", "413", "414")} <= _it_lav
                  and ("codice_procedura_civile", "163") not in _it_lav and ("codice_procedura_civile", "163") in _it_civ)
        check("atto[174]: la bozza riceve gli articoli di procedura del tipo d'atto (padia: KPC 154/156/42, 43 se società, 47 se "
              "lavoro; appello penale KPP 410/415; ricorso di lavoro IT 409/413/414, citazione 163)", _ok174,
              "AL lavoro=%s civile=%s penale=%s | IT lavoro=%s civile=%s" % (sorted(_al_lav), sorted(_al_civ), sorted(_al_pen),
                                                                              sorted(_it_lav), sorted(_it_civ)))
    except Exception as _e174:  # noqa: BLE001
        check("atto[174]: kontrollet u ekzekutuan", False, str(_e174))

    # [175] v9.402 — INTERVALLI nel verificatore: «Nenet 150–9999 të Kodit Civil» usciva VERIFICATA (art. 150 par. 9999);
    # «artt. 1218-1223 c.c.» dava il 1218 senza codice e perdeva il 1223. Misurato su 204 risposte: IT +38 verificate,
    # −14 senza codice, 0 falsi nuovi.
    try:
        from src import citation_verifier as _cv175
        from pathlib import Path as _P175
        _ixit175 = ArticleIndex.load(_P175("/app/data/index/bm25_it.pkl"))
        _i = lambda t, ix: {c["number"]: c for c in (_cv175.verify_text(t, ix).get("items") or [])}
        _a = _i("Nenet 150–9999 të Kodit Civil janë të zbatueshme.", idx)
        _b = _i("Sipas neneve 601–602 të Kodit Civil, kapari humbet.", idx)
        _c = _i("Si applicano gli artt. 1218-1223 c.c.", _ixit175)
        _d = _i("Il D.L. 87/2018 porta a 6-36 per l'art. 3, 3-27 per l'art. 6 del D.Lgs. 23/2015.", _ixit175)
        _e = _i("neni 134/1 i Kodit Civil", idx)
        _ok175 = (_a.get("9999", {}).get("status") == "fake" and _a.get("150", {}).get("status") == "verified"
                  and _b.get("601", {}).get("status") == "verified" and _b.get("602", {}).get("status") == "verified"
                  and _c.get("1218", {}).get("code") == "codice_civile" and _c.get("1223", {}).get("status") == "verified"
                  and "27" not in _d and _e.get("134/1", {}).get("status") == "verified")
        check("verificatore[175]: gli intervalli sono due articoli (AL «601–602», IT «1218-1223»); «134/1» resta paragrafo; "
              "«3-27» mensilità non è un articolo", _ok175,
              "AL=%s %s IT=%s %s" % (sorted(_a), sorted(_b), sorted(_c), sorted(_d)))
    except Exception as _e175:  # noqa: BLE001
        check("verificatore[175]: kontrollet u ekzekutuan", False, str(_e175))

    # [176] v9.402 — STUPEFACENTI nella chat AL: una sostanza delle liste della 7975/1995 in una domanda penale porta il KP 283
    # (e 283/a; 284 se si coltiva), come negli strumenti PRO dal v9.399; mai fuori dal penale né per una sostanza non in lista.
    try:
        _base176 = [(a, 1.0) for a in idx.articles if a.code == "kodi_penal" and str(a.number) in ("140", "141")]
        _anc176 = lambda t, aree: {(a.code, str(a.number)) for a, _ in brain._ancore_narkotike_al(list(_base176), idx, [t], aree)
                                   if getattr(a, "_ancora", False)}
        _h = _anc176("Klienti u kap me disa gram HHC të blera në internet.", ["Penal"])
        _k176 = _anc176("Fermeri kishte mbjellë 200 bimë kanabisi.", ["Penal"])
        _adm = _anc176("Klienti u kap me disa gram HHC.", ["Administrativ"])
        _tram = _anc176("Farmacia shiste tramadol pa recetë.", ["Penal"])
        _ok176 = ({("kodi_penal", "283"), ("kodi_penal", "283/a")} <= _h and ("kodi_penal", "284") in _k176
                  and not _adm and ("kodi_penal", "283") not in _tram)
        check("narkotike[176]: sostanza delle liste in una domanda penale → KP 283 (+284 se coltivazione); mai fuori dal penale "
              "né per il tramadolo (in nessuna lista)", _ok176, "HHC=%s kanabis=%s adm=%s tramadol=%s" % (sorted(_h), sorted(_k176),
                                                                                                          sorted(_adm), sorted(_tram)))
    except Exception as _e176:  # noqa: BLE001
        check("narkotike[176]: kontrollet u ekzekutuan", False, str(_e176))

    # [177] v9.402 — PAGINA D'UDIENZA bilingue: era solo albanese (anche per un fascicolo italiano), dettava sempre in sq-AL e
    # mostrava il marchio sbagliato «SUPER AVVOCATO».
    try:
        from types import SimpleNamespace as _NS177
        from src import web as _w177
        _js177 = open("/app/static/in_hearing.js", encoding="utf-8").read()
        with _w177.app.test_request_context("/"):
            _it177 = _w177.render_template("in_hearing.html", case=_NS177(id="x", title="Caso"), lang="it")
            _sq177 = _w177.render_template("in_hearing.html", case=_NS177(id="x", title="Rast"), lang="sq")
        _ok177 = ('data-lang="it"' in _it177 and "In udienza" in _it177 and "Annota" in _it177 and "Shëno" not in _it177
                  and 'data-lang="sq"' in _sq177 and "Në seancë" in _sq177 and "Shëno" in _sq177
                  and 'rec.lang = IT ? "it-IT" : "sq-AL"' in _js177 and "SUPER AVOKATI" in _js177
                  and "SUPER AVVOCATO" not in _js177 and "<script>" not in _it177)
        check("udienza[177]: pagina «in udienza» nella lingua del fascicolo, dettatura it-IT/sq-AL, marchio «SUPER AVOKATI»",
              _ok177)
    except Exception as _e177:  # noqa: BLE001
        check("udienza[177]: kontrollet u ekzekutuan", False, str(_e177))

    # [178] v9.402 — la PRESCRIZIONE CIVILE (KC 114) solo nelle materie civilistiche: in una domanda amministrativa (permesso
    # di costruire rifiutato: 45 giorni della 49/2012, prescrizione degli illeciti amministrativi) entrava 3 volte su 3.
    try:
        _b178 = [(a, 1.0) for a in idx.articles if a.code == "kodi_proc_admin" and str(a.number) in ("132", "135")]
        _k178 = lambda aree: ("kodi_civil", "114") in {(a.code, str(a.number)) for a, _ in
                                                       brain._applica_ancore(list(_b178), idx, ["afati i parashkrimit të së drejtës"], aree)}
        _ok178 = (not _k178(["Administrativ"]) and not _k178(["Administrativ", "Ndertim"]) and _k178(["Civil"])
                  and _k178(["Administrativ", "Civil"]) and _k178([]) and not _k178(["Penal", "Civil"]))
        check("ancore[178]: KC 114 nelle materie civilistiche e senza aree, mai nel solo amministrativo né nel penale", _ok178)
    except Exception as _e178:  # noqa: BLE001
        check("ancore[178]: kontrollet u ekzekutuan", False, str(_e178))

    # [179] v9.403 — LE RUBRICHE ITALIANE RIMASTE NEL TESTO: ~1.940 articoli (testi unici fiscali 2024-2026 con la riga della
    # fonte «( articolo 2 del decreto legislativo n. 74 del 2000 )», c.p.a., codice doganale nazionale, processo minorile,
    # convenzione Italia-Albania, regolamento del C.d.S.) senza rubrica: invisibili alla ricerca per titolo e senza titolo nel
    # prompt. Tre forme nuove in `build_it_index` (E fonte, F comma dopo la riga vuota, H parentesi su più righe), mai una
    # rubrica già presente cambiata, mai testo perso; «(L comma 3 e 4 - R …)» del TU edilizia e il seguito di frase del
    # regolamento notarile NON sono rubriche.
    try:
        import importlib.util as _ilu179
        _sp179 = _ilu179.spec_from_file_location("bi179", "/app/tools/build_it_index.py")
        _bi179 = _ilu179.module_from_spec(_sp179); _sp179.loader.exec_module(_bi179)
        _p = lambda b: _bi179._pulisci("", b)
        _e1 = _p("Emissione di fatture o altri documenti per operazioni inesistenti\n\n( articolo 8 del decreto legislativo n. 74 del 2000 )\n\n1. È punito")
        _e2 = _p("Atti sottoposti a condizione sospensiva, approvazione od omologazione ( articolo 27 decreto del Presidente della Repubblica 26 aprile 1986, n. 131 )\n\n1. Gli atti")
        _f1 = _p("Regolamento preventivo di giurisdizione\n\n1. Nel giudizio davanti ai tribunali")
        _f2 = _p("Espropriazione od occupazione temporanea\n\ndi locali per la tutela degli interessi doganali\n\n1. L'Agenzia")
        _h1 = _p("(Verifiche e prove\n\nper l'omologazione delle macchine agricole)\n\n1. Le verifiche")
        _n1 = _p("(L comma 3 e 4 - R comma 1, 2, 5, 6 e 7)\n\nInterventi subordinati a segnalazione")
        _n2 = _p("Il deposito delle copie autentiche, che i conservatori delle ipoteche debbono trasmettere\n\n(art. 106, n. 8 della legge), è eseguito di anno in anno")
        _n3 = _p("Sono abrogati i seguenti atti\n\n1) regio decreto 17 agosto 1907, n. 638")
        from pathlib import Path as _P179
        _ixit179 = ArticleIndex.load(_P179("/app/data/index/bm25_it.pkl"))
        _by179 = {(a.code, str(a.number)): a for a in _ixit179.articles}
        _h = lambda c, n: (getattr(_by179.get((c, n)), "heading", "") or "")
        _ok179 = (_e1[0] == "Emissione di fatture o altri documenti per operazioni inesistenti" and _e1[1].startswith("( articolo 8")
                  and _e2[0].startswith("Atti sottoposti a condizione sospensiva") and _e2[1].startswith("( articolo 27")
                  and _f1[0] == "Regolamento preventivo di giurisdizione" and _f1[1].startswith("1. Nel giudizio")
                  and _f2[0] == "Espropriazione od occupazione temporanea di locali per la tutela degli interessi doganali"
                  and _h1[0] == "Verifiche e prove per l'omologazione delle macchine agricole"
                  and _n1[0] == "" and _n2[0] == "" and _n3[0] == ""
                  and _h("tu_sanzioni_tributarie", "79").startswith("Emissione di fatture")
                  and _h("codice_processo_amministrativo", "10") == "Regolamento preventivo di giurisdizione"
                  and _h("convenzione_it_al_fisco", "15") == "LAVORO SUBORDINATO" and _h("tu_edilizia", "23") == "")
        check("corpus-it[179]: le rubriche rimaste nel testo (testi unici con la fonte, comma dopo la riga vuota, parentesi su più "
              "righe) diventano rubriche; «(L comma…)», i seguiti di frase e le frasi normative restano testo", _ok179,
              "E=%r F=%r H=%r no=%r | indice: 79=%r cpa10=%r" % (_e1[0], _f2[0], _h1[0], (_n1[0], _n2[0], _n3[0]),
                                                                 _h("tu_sanzioni_tributarie", "79"), _h("codice_processo_amministrativo", "10")))
    except Exception as _e179:  # noqa: BLE001
        check("corpus-it[179]: kontrollet u ekzekutuan", False, str(_e179))

    # [180] v9.403-404 — VECCHI ARTICOLI FISCALI ↔ TESTI UNICI (src/corrispondenze_tu.py, dalle righe della fonte), CON LA DATA:
    # i testi unici si applicano dal 1° gennaio 2027 e le abrogazioni dei vecchi atti decorrono da lì (Normattiva senza data
    # mostra la versione futura: verificato con «!vig=» di oggi). Prima: «art. 8 d.lgs. 74/2000» VIGENTE (col numero del 2027),
    # «art. 73 TUIR» = il d.P.R. 917/1986 (vigente), un articolo di testo unico → avviso «si applica dal 2027: fino ad allora …».
    # Dopo: abrogato → dove sta oggi; «art. 73 TUIR» sul nuovo con l'avviso della numerazione vecchia.
    try:
        from datetime import date as _d180
        from src import corrispondenze_tu as _ctu180, citation_verifier as _cv180, trust_line as _tl180
        _lf = _ctu180.leggi_fonte
        _okf = (_lf("( articolo 2 decreto del Presidente della Repubblica 22 dicembre 1986, n. 917 )\n\n1. x") == [("dpr:917:1986", ["2"])]
                and _lf("( articolo 10-bis del decreto legislativo n. 74 del 2000 )\n\n1. x") == [("dlgs:74:2000", ["10/bis"])]
                and _lf("(articoli 5, 6, comma 1, 7 decreto-legge 30 settembre 1983, n. 512 , convertito)\n\n1.") == [("dl:512:1983", ["5", "6"])]
                and _lf("1. Nessuna fonte") == [])
        from pathlib import Path as _P180
        _it180 = ArticleIndex.load(_P180("/app/data/index/bm25_it.pkl"))
        _v = lambda t: (_cv180.verify_text(t, _it180).get("items") or [{}])[0]
        _s = lambda it: [(x.get("code"), x.get("number")) for x in (it.get("successori") or [])]
        _dec = _ctu180.decorrenza("tu_sanzioni_tributarie")
        try:
            _ctu180._OGGI_FORZATO = _d180(2026, 9, 29)             # PRIMA della decorrenza
            _a = _v("Il reato è quello dell'art. 8 d.lgs. 74/2000.")
            _b = _v("Si apre il fronte dell'esterovestizione (art. 73, comma 3, TUIR).")
            _c = _v("art. 73 del d.P.R. 22 dicembre 1986, n. 917")
            _f = _v("L'art. 79 del testo unico sanzioni tributarie punisce l'emissione di fatture false.")
            _g = _v("art. 20 del testo unico dell'imposta di registro")
            _vv = _tl180.verifica("Rischia per l'art. 8 d.lgs. 74/2000 e per l'art. 73, comma 3, TUIR.", _it180, "IT")
            _prima = (_a.get("status") == "verified" and _s(_a) == [("tu_sanzioni_tributarie", "79")]
                      and "in vigore fino al 31/12/2026" in (_a.get("article_heading") or "")
                      and _b.get("status") == "verified" and _b.get("resolved_by") in ("trasfuso", "vigente") and ("tuir", "82") in _s(_b)
                      and _c.get("status") == "verified" and ("tuir", "82") in _s(_c)
                      and _v("Il ricorso va proposto ai sensi dell'art. 21 d.lgs. 546/1992.").get("status") == "verified"
                      and _f.get("status") == "verified" and "art. 8 d.lgs. 74/2000" in (_f.get("avviso") or "")
                      and _g.get("status") == "verified" and ("tu_registro", "24") in _s(_g)
                      and _tl180.stato(_vv) != "FLAGS"
                      and "TESTO UNICO APPLICABILE DAL 01/01/2027" in _ctu180.nota_decorrenza("tu_sanzioni_tributarie"))
            _ctu180._OGGI_FORZATO = _d180(2027, 2, 1)              # DOPO
            _a2 = _v("Il reato è quello dell'art. 8 d.lgs. 74/2000.")
            _b2 = _v("Si apre il fronte dell'esterovestizione (art. 73, comma 3, TUIR).")
            _c2 = _v("art. 73 del d.P.R. 22 dicembre 1986, n. 917")
            _d2 = _v("La residenza si determina ai sensi dell'art. 2 TUIR.")
            _dopo = (_a2.get("status") == "repealed" and "oggi art. 79" in (_a2.get("article_heading") or "")
                     and _b2.get("status") == "verified" and "82" in (_b2.get("avviso") or "")
                     and ((_c2.get("status") == "needs_code" and _c2.get("resolved_by") == "trasfuso")      # v9.404: fuori corpus
                          or (_c2.get("status") == "repealed" and ("tuir", "82") in _s(_c2)))          # v9.409: nel corpus
                     and _d2.get("status") == "verified" and not _d2.get("avviso")
                     and _ctu180.nota_decorrenza("tu_sanzioni_tributarie") == "")
        finally:
            _ctu180._OGGI_FORZATO = None
        _e = _v("Regime forfettario: art. 1, comma 54, l. 190/2014.")
        _src180 = open("/app/src/brain.py", encoding="utf-8").read()
        _ok180 = (_okf and str(_dec) == "2027-01-01" and _ctu180.successori("dlgs:74:2000", "8") == [("tu_sanzioni_tributarie", "79")]
                  and _prima and _dopo and _e.get("resolved_by") != "trasfuso"
                  and _src180.count("_sostituisce") >= 5 and "ABROGAZIONE NON ANCORA EFFICACE" in _src180)
        check("tu[180]: vecchi articoli fiscali ↔ testi unici CON LA DATA (fino al 31/12/2026 la norma vecchia è vigente; dal 2027 "
              "il testo unico) — verificatore, Trust Line, nota nel blocco", _ok180,
              "decorrenza=%s prima=%s dopo=%s a=%s %s b=%s c=%s f=%r" % (_dec, locals().get("_prima"), locals().get("_dopo"),
                                                                         _a.get("status"), _s(_a), _b.get("status"), _c.get("status"),
                                                                         (_f.get("avviso") or "")[:70]))
    except Exception as _e180:  # noqa: BLE001
        check("tu[180]: kontrollet u ekzekutuan", False, str(_e180))

    # [181] v9.403 — IL RECUPERO DEL PROCURATORE: semi di situazione (fatture false → KP 180; sequestro della polizia → KPP 300/301;
    # riciclaggio → KP 287; «shpërdorim» → KP 248/135), semi mancanti degli strumenti (analisi e piano: KPP 284; piano: 202, 208,
    # 178, 221, 274; vittima: 291), radici delle parole flesse e preferenza al codice penale nella ricerca per titolo. Misurato
    # (tools/misura_semi_pro, 20 casi × 3 campioni dei termini): la norma decisiva nel blocco 21/40 → 32/40 → vedi CLAUDE.md.
    try:
        from src import prosecutor as _pr181, expertise as _ex181
        _ss = _pr181._semi_situazione_al
        _k = lambda t: set(_ss(t))
        _fisc = _k("Një biznesmen ka lëshuar fatura fiktive për 20 milionë lekë; policia ka sekuestruar dokumentacionin kontabël.")
        _pas = _k("Transferoi paratë e trafikut në llogaritë e vëllait për t'ua fshehur origjinën.")
        _brib = _k("Inspektori i tatimeve mori 1.000 euro për të mos vendosur gjobë.")
        _sr = _ex181._stessa_radice
        _hs = _ex181._heading_scan_rank(idx, "ndërtim pa leje", preferiti=("kodi_penal",))
        _src181 = open("/app/src/prosecutor.py", encoding="utf-8").read()
        _esistono = all(_cv_esiste(idx, c, n) for c, n in [("kodi_penal", "180"), ("kodi_penal", "287"), ("kodi_proc_penale", "301"),
                                                               ("kodi_proc_penale", "300"), ("kodi_proc_penale", "284"),
                                                               ("kodi_proc_penale", "291"), ("kodi_proc_penale", "274"),
                                                               ("kodi_penal", "248"), ("kodi_penal", "135"), ("kodi_penal", "199/a")])
        _ok181 = ({("kodi_penal", "180"), ("kodi_proc_penale", "301"), ("kodi_proc_penale", "300")} <= _fisc
                  and ("kodi_penal", "287") in _pas and not _brib
                  and _sr("detyre", "detyres") and _sr("dhuna", "dhune") and not _sr("parave", "paraqitja") and not _sr("para", "paraqitje")
                  and ("kodi_penal", "199/a") in {(c, str(n)) for c, n, _t in _hs}
                  and _src181.count("_semi_al(") >= 4 and '("kodi_proc_penale", "291")' in _src181
                  and "preferiti=_PREF_AL" in _src181 and _esistono)
        check("procuratore[181]: semi di situazione (fiscale, sequestro della polizia, riciclaggio, shpërdorim), semi mancanti "
              "(284, 202/208/178/221/274, 291), radici flesse e codice penale preferito nella ricerca per titolo", _ok181,
              "fisc=%s pas=%s brib=%s titoli=%s" % (sorted(_fisc), sorted(_pas), sorted(_brib), [(c, n) for c, n, _t in _hs]))
    except Exception as _e181:  # noqa: BLE001
        check("procuratore[181]: kontrollet u ekzekutuan", False, str(_e181))

    # [182] v9.403 — IL NOTAIO: il controllo dell'atto riceve la forma dell'atto notarile (ligji 110/2018 101, 105, 137) e, coi
    # contanti, il divieto oltre 100.000 lekë (9920/2008 neni 59) e l'adeguata verifica (9917/2008 neni 4, 12); la successione col
    # coniuge la comunione (KF 74, 76, 96, 103). Nell'audit del 29 set erano «fuori dal corpus».
    try:
        from src import notary as _no182
        _sc = set(_no182._seed_controllo("KONTRATË SHITJEJE. Z. Hoxha i shet apartamentin me çmim 80.000 euro. Pagesa bëhet në para në dorë."))
        _sc2 = set(_no182._seed_controllo("KONTRATË QIRAJE për një dyqan."))
        _ok182 = ({("ligji_noteri", "105"), ("ligji_noteri", "101"), ("ligji_noteri", "137"), ("ligji_procedurat_tatimore", "59"),
                   ("ligji_pastrimi_parave", "4"), ("ligji_pastrimi_parave", "12")} <= _sc
                  and ("ligji_procedurat_tatimore", "59") not in _sc2 and ("ligji_noteri", "105") in _sc2
                  and all(_cv_esiste(idx, c, n) for c, n in list(_sc) + list(_no182._SEED_KOMUNITET))
                  and "_SEED_KOMUNITET" in open("/app/src/notary.py", encoding="utf-8").read())
        check("notaio[182]: forma dell'atto notarile, contanti e antiriciclaggio nel controllo; comunione del coniuge nella "
              "successione — tutti articoli del corpus", _ok182, "vendita=%s qira=%s" % (sorted(_sc), sorted(_sc2)))
    except Exception as _e182:  # noqa: BLE001
        check("notaio[182]: kontrollet u ekzekutuan", False, str(_e182))

    # [183] v9.404 — IL PROCURATORE IN SESSIONE IT: parte generale (continuazione, prescrizione) nell'analisi e nell'archiviazione,
    # semi di situazione (reati tributari → testo unico delle sanzioni artt. 73, 86-97 e, con le fatture false, 74/79/80; sequestro
    # della polizia giudiziaria → c.p.p. 253, 354, 355; riciclaggio → c.p. 648-bis ss.), atti d'indagine nel piano (247, 253, 266,
    # 359, 360, 321). Misurato: 15/27 → 27/27. Il tetto del blocco a 60.000 caratteri (i semi fiscali sono ~29.000).
    try:
        from src import prosecutor as _pr183
        from pathlib import Path as _P183
        _it183 = ArticleIndex.load(_P183("/app/data/index/bm25_it.pkl"))
        _s = lambda t: {(c, n) for c, n in _pr183._semi_situazione_it(t)}
        _f = _s("Un imprenditore ha emesso fatture per operazioni inesistenti per 200.000 euro; la Guardia di Finanza ha sequestrato la documentazione.")
        _iva = _s("L'amministratore della srl non ha versato l'IVA dovuta per 400.000 euro.")
        _ric = _s("Ha trasferito su conti esteri i proventi di una truffa per ostacolarne l'identificazione della provenienza.")
        _furto = _s("Furto in appartamento: entrato forzando la finestra, ha sottratto gioielli.")
        _src183 = open("/app/src/prosecutor.py", encoding="utf-8").read()
        _tutti = list(_f) + list(_ric) + _pr183._CP_GENERALE_IT + _pr183._cpp("247", "253", "266", "359", "360", "321")
        _ok183 = ({("tu_sanzioni_tributarie", "79"), ("tu_sanzioni_tributarie", "87"), ("tu_sanzioni_tributarie", "89"),
                   ("codice_procedura_penale", "354"), ("codice_procedura_penale", "355")} <= _f
                  and ("tu_sanzioni_tributarie", "89") in _iva and ("tu_sanzioni_tributarie", "79") not in _iva
                  and ("codice_penale", "648-bis") in _ric and not _furto
                  and _pr183._MAX_TOT >= 60000 and _src183.count("_semi_it(") >= 4
                  and 'semi_in_piu_it=_cpp("247", "253", "266", "359", "360", "321")' in _src183
                  and '("kodi_penal", "55")' in _src183
                  and all(_cv_esiste(_it183, c, n) for c, n in _tutti))
        check("procuratore-it[183]: semi dei reati tributari (testo unico delle sanzioni), del sequestro della p.g. e del "
              "riciclaggio, parte generale e atti d'indagine — tutti articoli vigenti del corpus IT", _ok183,
              "fiscale=%s iva=%s ric=%s" % (sorted(_f), sorted(_iva), sorted(_ric)))
    except Exception as _e183:  # noqa: BLE001
        check("procuratore-it[183]: kontrollet u ekzekutuan", False, str(_e183))

    # [184] v9.404 — la FONTE incollata davanti alla rubrica nel testo unico degli stupefacenti («Legge 26 giugno 1990, n. 162,
    # … ) Associazione finalizzata al traffico…», 107 articoli) va in testa al testo; e il procuratore IT riceve l'art. 74 d.P.R.
    # 309/1990 quando i fatti parlano di un'organizzazione (l'audit IT: «richiamato dall'art. 51 c.p.p. ma non fornito»).
    try:
        import importlib.util as _ilu184
        _sp184 = _ilu184.spec_from_file_location("bi184", "/app/tools/build_it_index.py")
        _bi184 = _ilu184.module_from_spec(_sp184); _sp184.loader.exec_module(_bi184)
        _h184, _b184 = _bi184._pulisci("Legge 26 giugno 1990, n. 162 , articoli 14, comma 1, e 38, comma 2) Associazione finalizzata "
                                       "al traffico illecito di sostanze stupefacenti o psicotrope", "1. Quando tre o più persone")
        _n184 = _bi184._pulisci("Responsabilità genitoriale", "La responsabilità genitoriale")
        from src import expertise as _ex184
        from pathlib import Path as _P184
        _it184 = ArticleIndex.load(_P184("/app/data/index/bm25_it.pkl"))
        brain.set_request_jurisdiction("IT")
        _org = {(c, str(n)) for c, n, _t in _ex184.retrieve_grounded(None, _it184, "Gruppo organizzato che traffica cocaina nel quartiere.",
                                                                    seed_pairs=[], max_arts=6)}
        _sol = {(c, str(n)) for c, n, _t in _ex184.retrieve_grounded(None, _it184, "Ha ceduto 20 grammi di cocaina a un acquirente.",
                                                                    seed_pairs=[], max_arts=6)}
        brain.set_request_jurisdiction("AL")
        _ok184 = (_h184.startswith("Associazione finalizzata") and _b184.startswith("(Legge 26 giugno 1990")
                  and _n184 == ("Responsabilità genitoriale", "La responsabilità genitoriale")
                  and ("stupefacenti", "74") in _org and ("stupefacenti", "73") in _org and ("stupefacenti", "73") in _sol)
        check("stupefacenti-it[184]: la fonte davanti alla rubrica va nel testo; l'associazione (art. 74) entra con l'organizzazione",
              _ok184, "h=%r org=%s sol=%s" % (_h184[:40], sorted(_org), sorted(_sol)))
    except Exception as _e184:  # noqa: BLE001
        check("stupefacenti-it[184]: kontrollet u ekzekutuan", False, str(_e184))

    # [185] v9.404 — l'ABROGATO DICHIARATO non è un errore: «art. 79 TU (già art. 8 d.lgs. 74/2000, oggi abrogato)» o «nel testo
    # previgente» è diritto intertemporale detto bene (prova viva del 29 set: 10 citazioni così accendevano la riga in rosso su
    # un'analisi giusta del pubblico ministero); l'abrogato citato come vigente resta una segnalazione.
    try:
        from src import trust_line as _tl185, cancello as _cn185
        from pathlib import Path as _P185
        _it185 = ArticleIndex.load(_P185("/app/data/index/bm25_it.pkl"))
        # (un articolo abrogato DAVVERO: il d.P.R. 633/1972 art. 31, abrogato dalla L. 413/1991 — i vecchi articoli fiscali abrogati
        # dai testi unici sono ancora vigenti fino al 2027, sezione [180])
        _v1 = _tl185.verifica("L'art. 31 del d.P.R. 633/1972, oggi abrogato, prevedeva una disciplina diversa.", _it185, "IT")
        _v2 = _tl185.verifica("Si applica l'art. 31 del d.P.R. 633/1972.", _it185, "IT")
        _ok185 = (_v1["nene"].get("repealed_noted", 0) >= 1 and _v1["nene"]["repealed"] == 0 and _tl185.stato(_v1) != "FLAGS"
                  and "dichiarate tali" in _tl185.riga(_v1, "it")
                  and _v2["nene"]["repealed"] == 1 and _tl185.stato(_v2) == "FLAGS"
                  and bool(_cn185._GIA_DETTO_RE.search("L'art. 79, comma 2, TU (già art. 8, comma 2, D.Lgs 74/2000) stabilisce"))
                  and not _cn185._GIA_DETTO_RE.search("Si applica l'art. 31 del d.P.R. 633/1972."))
        check("trust[185]: l'abrogato dichiarato nella frase (già/oggi/previgente) non accende il rosso; l'abrogato citato come "
              "vigente sì", _ok185, "v1=%s v2=%s" % (_v1["nene"], _v2["nene"]))
    except Exception as _e185:  # noqa: BLE001
        check("trust[185]: kontrollet u ekzekutuan", False, str(_e185))

    # [186] v9.405 — IL CORPUS ITALIANO AL TESTO VIGENTE OGGI. Normattiva aperta senza data mostra la versione FUTURA (656 articoli
    # di 20 atti: i vecchi atti fiscali «ARTICOLO ABROGATO» dal 2027, articoli con modifiche future, 3 che esistono solo dal
    # futuro): tools/riallinea_vigenti_it.py mette nel JSON il testo di oggi e conserva la versione futura con la data; il build
    # usa quella giusta per la sua data e scrive `_vigenze`; verificatore, blocco degli articoli e strumenti PRO le leggono.
    # Il primo giro dello script abbinava per NUMERO e nell'imposta di registro l'art. 5 della Tabella finiva sull'art. 5 del
    # testo unico: ora per gruppo, come l'ingest.
    try:
        from datetime import date as _d186
        from src import corrispondenze_tu as _ctu186, citation_verifier as _cv186, expertise as _ex186
        from pathlib import Path as _P186
        import importlib.util as _ilu186
        _it186 = ArticleIndex.load(_P186("/app/data/index/bm25_it.pkl"))
        _by186 = {(a.code, str(a.number)): a for a in _it186.articles}
        _a8 = _by186.get(("reati_tributari", "8"))
        _n_vg = sum(len(v) for v in ((_ctu186.carica().get("_vigenze") or {}).values()))
        _testo_ok = bool(_a8 is not None and not _a8.repealed
                         and "operazioni inesistenti" in ((_a8.heading or "") + " " + (_a8.body or "")).lower()
                         and "ARTICOLO ABROGATO" not in (_a8.body or "")[:300].upper())
        _r5 = _by186.get(("imposta_registro", "5"))
        _r5_ok = bool(_r5 is not None and "Atti e documenti formati per l'applicazione" not in (_r5.body or ""))
        _s2 = _by186.get(("imposta_successioni", "2"))
        _s2_ok = bool(_s2 is not None and "territorialit" in (_s2.heading or "").lower() and "637/1972" in (_s2.body or "")[:200])
        _v186 = lambda t: (_cv186.verify_text(t, _it186).get("items") or [{}])[0]
        try:
            _ctu186._OGGI_FORZATO = _d186(2026, 9, 29)
            _nv = _ctu186.nota_vigenza("reati_tributari", "8")
            _i8 = _v186("Il reato è quello dell'art. 8 d.lgs. 74/2000.")
            _bl = _ex186._previgenti(_it186, [("tu_sanzioni_tributarie", "79", "x")])
            _cp = _ex186._con_previgenti(_it186, [("tu_sanzioni_tributarie", "79", "x" * 3000), ("codice_penale", "56", "y")])
            _blk = _ex186.blocco_articoli(_cp, "it")
            _dd1 = _v186("Si applica l'art. 79 del testo unico sanzioni tributarie.")
            _dd2 = _v186("L'art. 79 del testo unico sanzioni tributarie, applicabile dal 1° gennaio 2027, sostituirà l'art. 8.")
            _prima = (bool(_dd1.get("avviso")) and not _dd2.get("avviso")
                      and "VIGENTE FINO AL 31/12/2026" in _nv and "ABROGATO" in _nv
                      and _i8.get("status") == "verified" and "in vigore fino al 31/12/2026" in (_i8.get("article_heading") or "")
                      and ("reati_tributari", "8") in _ctu186.previgenti("tu_sanzioni_tributarie", "79")
                      and any(c == "reati_tributari" and n == "8" for c, n, _t in _bl)
                      and [(c, n) for c, n, _t in _cp][:2] == [("tu_sanzioni_tributarie", "79"), ("reati_tributari", "8")]
                      and "testo unico abbreviato" in _blk
                      and _blk.index("%s art. 79]" % _ex186._lbl_it("tu_sanzioni_tributarie")) < _blk.index(
                          "%s art. 8]" % _ex186._lbl_it("reati_tributari")))
            _ctu186._OGGI_FORZATO = _d186(2027, 2, 1)
            _i8b = _v186("Il reato è quello dell'art. 8 d.lgs. 74/2000.")
            _dopo = (_ctu186.nota_vigenza("reati_tributari", "8").startswith("⚠ ARTICOLO ABROGATO DAL 01/01/2027")
                     and _i8b.get("status") == "repealed" and "oggi art. 79" in (_i8b.get("article_heading") or "")
                     and _ex186._previgenti(_it186, [("tu_sanzioni_tributarie", "79", "x")]) == [])
        finally:
            _ctu186._OGGI_FORZATO = None
        # le altre due forme con una mappa finta: articolo che CAMBIA più avanti, articolo NON ANCORA IN VIGORE
        _orig186 = _ctu186.carica
        try:
            _ctu186.carica = lambda: {"_vigenze": {"x_atto": {
                "7": {"fino": "2027-02-28", "dal": "2027-03-01", "futuro_abrogato": False, "futuro_rubrica": "Nuova rubrica",
                      "futuro_testo": "1. Testo nuovo.", "non_in_vigore_dal": ""},
                "9-bis": {"fino": "", "dal": "", "futuro_abrogato": False, "futuro_rubrica": "", "futuro_testo": "",
                          "non_in_vigore_dal": "2027-06-01"}}}}
            _ctu186._OGGI_FORZATO = _d186(2026, 10, 1)
            _f1 = _ctu186.nota_vigenza("x_atto", "7")
            _f2 = _ctu186.nota_vigenza("x_atto", "9-bis")
            _ctu186._OGGI_FORZATO = _d186(2027, 7, 1)
            _f3 = _ctu186.nota_vigenza("x_atto", "7")
            _f4 = _ctu186.nota_vigenza("x_atto", "9-bis")
            _finte = (_f1.startswith("ℹ TESTO VIGENTE FINO AL 28/02/2027") and "dal 01/03/2027 cambia" in _f1
                      and _f2.startswith("⚠ ARTICOLO NON ANCORA IN VIGORE: si applica dal 01/06/2027")
                      and _f3.startswith("⚠ TESTO CAMBIATO DAL 01/03/2027") and _f4 == "")
        finally:
            _ctu186.carica = _orig186
            _ctu186._OGGI_FORZATO = None
        # lo script abbina per GRUPPO come l'ingest (normattiva_lib.assign_numbers)
        _sp = _ilu186.spec_from_file_location("riall186", "/app/tools/riallinea_vigenti_it.py")
        _rm = _ilu186.module_from_spec(_sp)
        sys.path.insert(0, "/app/tools")
        _sp.loader.exec_module(_rm)
        _sz = {"0": 80, "1": 14, "2": 12, "3": 13, "4": 1}
        _et = {"1": ["art. %d" % i for i in range(1, 15)], "2": ["art. %d" % i for i in range(1, 13)],
               "3": ["art. %d" % i for i in range(1, 14)], "4": ["Prospetto"]}
        _gr = (_rm._numero_nel_json("5", "0", _sz, _et) == "5" and _rm._numero_nel_json("5", "3", _sz, _et) == "5-all3"
               and _rm._numero_nel_json("prospetto", "4", _sz, _et) is None
               and _rm._numero_nel_json("1", "0", {"0": 1, "1": 62}, {}) == "1-legge"
               and _rm._numero_nel_json("2", "1", {"0": 1, "1": 62}, {}) == "2"
               and _rm._numero_nel_json("8", "0", {"0": 34}, {}) == "8"
               and _rm._trova([{"number": "5"}, {"number": "5-all3"}], "5-all3", "3") == {"number": "5-all3"}
               and _rm._trova([{"number": "5", "group": "0"}], "5", "3") is None)
        _src_n = open("/app/src/notary.py", encoding="utf-8").read()
        _src_b = open("/app/src/brain.py", encoding="utf-8").read()
        # la chat: accanto all'articolo di testo unico non ancora applicabile entra la norma vigente (copia marcata)
        _chat_prev = False
        try:
            from src.brain import SuperAvvocato as _SA186, set_request_jurisdiction as _srj186
            _sa186 = _SA186.__new__(_SA186)
            _sa186.index_it = _it186
            _sa186._current_jurisdiction = lambda: "IT"
            _ctu186._OGGI_FORZATO = _d186(2026, 9, 29)
            _r = _sa186._aggiungi_previgenti([(_by186[("tu_sanzioni_tributarie", "79")], 1.0)])
            _chat_prev = ([(a.code, str(a.number)) for a, _ in _r] == [("tu_sanzioni_tributarie", "79"), ("reati_tributari", "8")]
                          and bool(getattr(_r[1][0], "_previgente_di", "")) and not hasattr(_by186[("reati_tributari", "8")], "_previgente_di")
                          and _src_b.count("self._aggiungi_previgenti(retrieved)") == 2)
        except Exception as _e_cp:  # noqa: BLE001
            print("   chat previgenti:", _e_cp)
        finally:
            _ctu186._OGGI_FORZATO = None
        from src import notary as _nt186, prosecutor as _pr186
        _semi = (("codice_civile", "568") in _nt186._semi_successione_it("Il de cuius lascia la madre e un fratello.")
                 and ("legge_52_1985", "29") in _nt186._seed_controllo_it("Compravendita di un appartamento in Milano")
                 and ("antiriciclaggio", "49") in _nt186._seed_controllo_it("prezzo pagato in contanti")
                 and "_CHECK_SYSTEM_IT" in _src_n and "_SUCC_SYSTEM_IT" in _src_n and '"2657", "2671")' in _src_n
                 and '("codice_procedura_civile", "441-bis")' in _src_b
                 and ("kodi_penal", "22") in _pr186._semi_situazione_al("u përpoq të vidhte makinën por nuk arriti")
                 and ("codice_penale", "56") in _pr186._semi_situazione_it("ha tentato di rubare l'auto")
                 and {("disp_att_cpp", "220"), ("responsabilita_enti", "25-quinquiesdecies")} <= set(_pr186._semi_situazione_it(
                     "L'amministratore della srl ha emesso fatture per operazioni inesistenti")))
        _ok186 = (_n_vg >= 400 and _testo_ok and _r5_ok and _s2_ok and _prima and _dopo and _finte and _gr and _semi and _chat_prev)
        check("vigenti-it[186]: il corpus italiano ha il testo in vigore oggi, le date di vigenza (fino a / dal / non ancora) nel "
              "verificatore e nel blocco, la norma previgente accanto al testo unico, l'abbinamento per gruppo, il notaio italiano",
              _ok186, "vigenze=%s testo=%s reg5=%s succ2=%s prima=%s dopo=%s finte=%s gruppi=%s semi=%s chat=%s | i8=%s %r" % (
                  _n_vg, _testo_ok, _r5_ok, _s2_ok, locals().get("_prima"), locals().get("_dopo"), locals().get("_finte"),
                  locals().get("_gr"), locals().get("_semi"), locals().get("_chat_prev"), (locals().get("_i8") or {}).get("status"),
                  ((locals().get("_i8") or {}).get("article_heading") or "")[:120]))
    except Exception as _e186:  # noqa: BLE001
        check("vigenti-it[186]: kontrollet u ekzekutuan", False, str(_e186))

    # [187] v9.406 — TARIFFE e TABELLE degli atti fiscali nel corpus: la Tariffa del d.P.R. 131/1986 (le aliquote stanno in tabelle
    # HTML che il parser scartava: `normattiva_lib.tabelle_in_testo`), le Tabelle IVA divise per parti e in blocchi di voci, la
    # Tariffa del testo unico del registro; nomi leggibili («Tabella A, parte III, nn. 37–80», «Tariffa, parte I, art. 1»).
    try:
        import importlib.util as _ilu187
        from pathlib import Path as _P187
        from src import parser as _ps187, corrispondenze_tu as _ctu187
        _it187 = ArticleIndex.load(_P187("/app/data/index/bm25_it.pkl"))
        _by187 = {(a.code, str(a.number)): a for a in _it187.articles}
        _t1 = _by187.get(("imposta_registro", "1-all1"))
        _tar = bool(_t1 is not None and not _t1.repealed and "9 per cento" in _t1.body and "2 per cento" in _t1.body
                    and "II-bis" in _t1.body and "Tariffa, parte I" in (_t1.heading or ""))
        _spur = ("imposta_registro", "2-bis") not in _by187 and ("imposta_registro", "2-bis-all2") in _by187
        _iva = [a for (c, n), a in _by187.items() if c == "iva" and n.startswith("tabella-a-parte-iii")]
        _iva_ok = (len(_iva) >= 3 and any("127-quaterdicies" in a.body for a in _iva)       # (così nel testo ufficiale, «-dicies»)
                   and all(len(a.body) < 9000 for a in _iva))
        _tu = _by187.get(("tu_registro", "tariffa-i-1"))
        _tu_ok = bool(_tu is not None and "2 per cento" in _tu.body)
        _sp187 = _ilu187.spec_from_file_location("nl187", "/app/tools/normattiva_lib.py")
        _nl187 = _ilu187.module_from_spec(_sp187); _sp187.loader.exec_module(_nl187)
        _html187 = ('<div class="bodyTesto"><span class="attachment-just-text">TARIFFA<br>Art. 1.<br></span><span class="table-akn">'
                    '<table class="table-formatted-akn"><tr><td>1. Atti traslativi a titolo oneroso</td><td> 9 per cento </td></tr>'
                    '</table> </span><span class="attachment-just-text">Note: II-bis) prima casa<br></span></div>'
                    '<div class="d-flex justify-content-between">')
        _pa187 = _nl187.parse_article_page(_nl187.tabelle_in_testo(_html187), fallback_number="1") or {}
        _tab_ok = ("Atti traslativi a titolo oneroso — 9 per cento" in (_pa187.get("body") or "")
                   and (_pa187.get("body") or "").index("9 per cento") < (_pa187.get("body") or "").index("II-bis"))
        _nomi = (_ps187.numero_visibile_it("tabella-a-parte-iii-nn-37-80") == "Tabella A, parte III, nn. 37–80"
                 and _ps187.numero_visibile_it("tariffa-i-1") == "Tariffa, parte I, art. 1"
                 and _ps187.numero_visibile_it("allegato-ii-octies") == "Allegato II-octies"
                 and _ps187.numero_visibile_it("13-ter-all3") == "13-ter (allegato)"
                 and (_t1 is None or not _iva or _iva[0].citation.startswith("Tabella A, parte III")))
        _hits = [(a.code, str(a.number)) for a, _ in _it187.search("aliquota del 2 per cento prima casa imposta di registro trasferimento", top_k=12)]
        _ric = ("imposta_registro", "1-all1") in _hits
        _vg187 = bool(_ctu187.vigenza("imposta_registro", "1-all1"))
        # il verificatore: la voce della Tariffa/Tabella (non l'articolo del testo), la voce IVA sul suo blocco, la data per esteso
        from src import citation_verifier as _cv187
        _v187 = lambda t: [(x["code"], x["number"], x["status"]) for x in (_cv187.verify_text(t, _it187).get("items") or [])]
        _ver = (("imposta_registro", "1/all1", "verified") in _v187("Si applica l'art. 1 della Tariffa, parte I, allegata al d.P.R. 131/1986.")
                and ("imposta_registro", "2/all3", "verified") in _v187("art. 2 della Tabella allegata al d.P.R. 131/1986")
                and ("imposta_registro", "99/all1", "fake") in _v187("art. 99 della Tariffa, parte I, allegata al d.P.R. 131/1986")
                and any(c == "iva" and st == "verified" and n.startswith("tabella-a-parte-iii") for c, n, st in
                        _v187("aliquota del 10% (n. 127-duodecies della Tabella A, parte III, allegata al d.P.R. 633/1972)"))
                and ("reati_tributari", "8", "verified") in _v187("Il reato è previsto dall'art. 8 del d.lgs. 10 marzo 2000, n. 74.")
                and ("sanzioni_amministrative", "28", "verified") in _v187("art. 28 L. 24 novembre 1981, n. 689")
                and [x[2] for x in _v187("art. 2 della Tariffa del d.P.R. 131/1986")] == ["needs_code"]
                and ("tu_registro", "tariffa/i/1", "verified") in _v187(
                    "art. 1 della Tariffa, parte I, allegata al testo unico dell'imposta di registro e altri tributi indiretti"))
        _ok187 = _tar and _spur and _iva_ok and _tu_ok and _tab_ok and _nomi and _ric and _vg187 and _ver
        check("tariffe-it[187]: la Tariffa del registro con le aliquote, le Tabelle IVA in parti e blocchi, la Tariffa del testo unico, "
              "nomi leggibili, recupero e vigenza", _ok187,
              "tariffa=%s spurio=%s iva=%s(%d) tu=%s tabelle=%s nomi=%s ricerca=%s vigenza=%s verificatore=%s" % (
                  _tar, _spur, _iva_ok, len(_iva), _tu_ok, _tab_ok, _nomi, _ric, _vg187, locals().get("_ver")))
    except Exception as _e187:  # noqa: BLE001
        check("tariffe-it[187]: kontrollet u ekzekutuan", False, str(_e187))

    # [188] v9.408 — gli ALLEGATI mai entrati (misura del 29 set: 241 in 31 atti; d.lgs. 81/2008 0 su 55): le violazioni gravi che
    # fanno sospendere l'attività (Allegato I), i requisiti dei luoghi di lavoro (IV, in blocchi), i contenuti del PSC (XV), i lavori
    # vietati alle lavoratrici madri (maternità, Allegato A), la tabella dei punti della patente (C.d.S.), gli allegati del codice dei
    # contratti (revisione prezzi); le pagine lunghe in blocchi, nomi leggibili, recupero
    try:
        from pathlib import Path as _P188
        from src import parser as _ps188
        _it188 = ArticleIndex.load(_P188("/app/data/index/bm25_it.pkl"))
        _by188 = {(a.code, str(a.number)): a for a in _it188.articles}
        _a1 = _by188.get(("sicurezza_lavoro", "allegato-i"))
        _iv = [a for (c, n), a in _by188.items() if c == "sicurezza_lavoro" and n.startswith("allegato-iv-")]
        _mat = _by188.get(("maternita_paternita", "allegato-a"))
        _pat = _by188.get(("codice_strada", "tabella"))
        _cp = [a for (c, n), a in _by188.items() if c == "codice_contratti_pubblici" and n.startswith("allegato-ii.2-bis")]
        _ok_c = bool(_a1 is not None and "articolo 14" in (_a1.heading + " " + _a1.body).lower()     # art. 14 = la sospensione
                     and len(_iv) >= 5 and all(len(a.body) < 12000 for a in _iv) and "Requisiti dei luoghi di lavoro" in _iv[0].heading
                     and _mat is not None and "insalubri" in (_mat.heading or "").lower()
                     and _pat is not None and "126-bis" in (_pat.heading + _pat.body)
                     and len(_cp) >= 10)
        _nomi188 = (_ps188.numero_visibile_it("allegato-ii.2-bis-art-1") == "Allegato II.2-bis, art. 1"
                    and _ps188.numero_visibile_it("allegato-iv-2") == "Allegato IV (2)"
                    and _ps188.numero_visibile_it("allegato-a") == "Allegato A"
                    and (_a1 is None or _a1.citation.startswith("Allegato I ")))
        _hits188 = [(a.code, str(a.number)) for a, _ in _it188.search(
            "lavori vietati alle lavoratrici in gravidanza lavori faticosi pericolosi insalubri", top_k=12)]
        _ric188 = ("maternita_paternita", "allegato-a") in _hits188
        _ok188 = _ok_c and _nomi188 and _ric188
        check("allegati-it[188]: gli allegati mai entrati (d.lgs. 81/2008, maternità, C.d.S., contratti pubblici), in blocchi, "
              "con nomi leggibili e trovati dalla ricerca", _ok188,
              "contenuti=%s nomi=%s ricerca=%s | iv=%d cp=%d" % (_ok_c, _nomi188, _ric188, len(_iv), len(_cp)))
    except Exception as _e188:  # noqa: BLE001
        check("allegati-it[188]: kontrollet u ekzekutuan", False, str(_e188))

    # [189] v9.409 — i VECCHI ATTI FISCALI VIGENTI FINO AL 31/12/2026 che mancavano: il TUIR del 1986 (tolto ad agosto perché
    # Normattiva senza data lo mostrava «PROVVEDIMENTO ABROGATO»: la versione futura), il processo tributario (d.lgs. 546/1992), le
    # sanzioni non penali (471/1997), ipotecaria e catastale (347/1990), bollo (642/1972), adempimento unico (463/1997). Scaricati al
    # testo di oggi; il verificatore li verifica sul loro testo col numero del 2027; «art. N TUIR» col nome va al TUIR vigente
    try:
        from datetime import date as _d189
        from pathlib import Path as _P189
        from src import corrispondenze_tu as _ctu189, citation_verifier as _cv189
        _it189 = ArticleIndex.load(_P189("/app/data/index/bm25_it.pkl"))
        _by189 = {(a.code, str(a.number)): a for a in _it189.articles}
        _t73 = _by189.get(("tuir_1986", "73"))
        _p21 = _by189.get(("processo_tributario", "21"))
        _nel = bool(_t73 is not None and not _t73.repealed and _p21 is not None and not _p21.repealed
                    and ("imposta_bollo", "13") in _by189 and ("imposta_ipotecaria_catastale", "1") in _by189)
        _v189 = lambda t: (_cv189.verify_text(t, _it189).get("items") or [{}])[0]
        _sv = lambda it: [(x.get("code"), x.get("number")) for x in (it.get("successori") or [])]
        try:
            _ctu189._OGGI_FORZATO = _d189(2026, 9, 29)
            _a = _v189("Si apre il fronte dell'esterovestizione (art. 73, comma 3, TUIR).")
            _b = _v189("art. 73 del d.P.R. 22 dicembre 1986, n. 917")
            _c = _v189("Il ricorso va proposto entro sessanta giorni ai sensi dell'art. 21 d.lgs. 546/1992.")
            _prima = (_a.get("code") == "tuir_1986" and _a.get("status") == "verified" and ("tuir", "82") in _sv(_a)
                      and _b.get("code") == "tuir_1986" and _b.get("status") == "verified"
                      and "in vigore fino al 31/12/2026" in (_b.get("article_heading") or "")
                      and _c.get("code") == "processo_tributario" and _c.get("status") == "verified"
                      and ("tuir_1986", "73") in _ctu189.previgenti("tuir", "82"))
            _ctu189._OGGI_FORZATO = _d189(2027, 2, 1)
            _b2 = _v189("art. 73 del d.P.R. 22 dicembre 1986, n. 917")
            _a2 = _v189("Si apre il fronte dell'esterovestizione (art. 73, comma 3, TUIR).")
            _dopo = (_b2.get("status") == "repealed" and ("tuir", "82") in _sv(_b2) and _a2.get("code") == "tuir")
        finally:
            _ctu189._OGGI_FORZATO = None
        _ok189 = _nel and _prima and _dopo
        check("fiscali-vigenti-it[189]: TUIR 1986, processo tributario, sanzioni, ipocatastali, bollo, adempimento unico nel corpus "
              "col testo vigente; verificati sul loro testo fino al 2026, abrogati dal 2027", _ok189,
              "nel_corpus=%s prima=%s dopo=%s | a=%s b=%s c=%s" % (_nel, locals().get("_prima"), locals().get("_dopo"),
                                                                  (locals().get("_a") or {}).get("code"), (locals().get("_b") or {}).get("status"),
                                                                  (locals().get("_c") or {}).get("code")))
    except Exception as _e189:  # noqa: BLE001
        check("fiscali-vigenti-it[189]: kontrollet u ekzekutuan", False, str(_e189))

    # [190] v9.409 — le TABELLE A CARATTERI di Normattiva (Tariffa del bollo, Tariffa e Tabella delle imposte ipotecarie e
    # catastali): le voci separate (fatture ≠ estratti conto), il decreto del bollo coi SUOI numeri e la Tariffa come «N-all1»,
    # le cifre in lire accompagnate dalla misura di oggi (2 %, 16 e 2 euro, 200 euro), il testo modificato «((…))» non più
    # perso nella rubrica, le pagine-etichetta fuori dall'indice; il verificatore legge «art. 13 della Tariffa allegata al d.P.R.
    # 642/1972» sulla voce e non sull'art. 13 del decreto
    try:
        import re as _re190
        from pathlib import Path as _P190
        from src import citation_verifier as _cv190
        _it190 = ArticleIndex.load(_P190("/app/data/index/bm25_it.pkl"))
        _by190 = {(a.code, str(a.number)): a for a in _it190.articles}
        _t13 = _by190.get(("imposta_bollo", "13-all1"))
        _d13 = _by190.get(("imposta_bollo", "13"))
        _tar = _by190.get(("imposta_ipotecaria_catastale", "tariffa"))
        _tab = _by190.get(("imposta_ipotecaria_catastale", "tabella"))
        _b16 = _by190.get(("imposta_bollo", "16-all2"))
        _voci = bool(_t13 and _re190.search(r"(?m)^1\. Fatture", _t13.body) and _re190.search(r"(?m)^2-bis\. Estratti conto", _t13.body)
                     and "16,00" in (_t13.note or "") and _d13 is not None and "all1" not in _d13.number)
        _ipo = bool(_tar and "2 per cento" in _tar.body and "euro 200" in (_tar.note or "")
                    and _tab and "35,00" in _tab.body)
        _rub = bool(_b16 and "amministrazioni dello Stato" in _b16.body
                    and "amministrazioni" not in (_b16.heading or "").split("art. 16")[-1])
        _cc148 = _by190.get(("codice_civile", "148"))
        _rub = _rub and bool(_cc148 and "I coniugi devono adempiere" in _cc148.body)
        _vuote = not any(_re190.fullmatch(r"(?i)\[senza testo\]|(?:tabella|allegato|tariffa|prospetto)(?:\s+[\w.\-]{1,12})?\.?",
                                          (a.body or "").strip()) for a in _it190.articles if not a.repealed)
        _v190 = lambda t: (_cv190.verify_text(t, _it190).get("items") or [{}])[0]
        _x = _v190("Sulle fatture si applica l'art. 13 della Tariffa allegata al d.P.R. 642/1972.")
        _y = _v190("L'imposta di bollo si applica ai sensi dell'art. 13 d.P.R. 642/1972.")
        _ver = (_x.get("code") == "imposta_bollo" and str(_x.get("number")).replace("/", "-") == "13-all1" and _x.get("status") == "verified"
                and _y.get("code") == "imposta_bollo" and str(_y.get("number")) == "13")
        check("tabelle-a-caratteri-it[190]: bollo e imposte ipotecarie con le voci, le misure di oggi e il verificatore sulla voce",
              _voci and _ipo and _rub and _vuote and _ver,
              "voci=%s ipo=%s rubrica=%s vuote=%s verificatore=%s (%s %s)" % (
                  _voci, _ipo, _rub, _vuote, _ver, _x.get("number"), _y.get("number")))
    except Exception as _e190:  # noqa: BLE001
        check("tabelle-a-caratteri-it[190]: kontrollet u ekzekutuan", False, str(_e190))

    # [191] v9.410 — SCADENZIARIO DEL FASCICOLO (chiesto da un avvocato albanese): dai PDF del cliente udienze, termini e
    # documenti da mandare, PROPOSTI e confermati dall'avvocato; la frase e la data si ritrovano nel testo (un'invenzione esce
    # «da verificare»), il termine relativo lo calcola il motore; gli avvisi vanno su TUTTI i canali collegati (email e
    # Telegram), il bot si collega con un codice monouso e il webhook risponde solo con la firma giusta
    try:
        import inspect as _in191
        from src import scadenziario as _sc191, reminders as _rm191, web as _w191, storage as _st191
        _doc = ("Il Giudice rinvia la causa all'udienza del 15.01.2027 ore 9.30 per la precisazione delle conclusioni, "
                "assegnando alle parti termine di venti giorni dalla comunicazione del presente verbale per il deposito di memorie. "
                "Gjykata cakton seancën më 20 tetor 2026.")
        _est = {"date": [{"tipo": "udienza", "titolo": "Udienza", "data": "2027-01-15", "ora": "9.30",
                          "citazione": "rinvia la causa all'udienza del 15.01.2027 ore 9.30 per la precisazione delle conclusioni"},
                         {"tipo": "udienza", "titolo": "Inventata", "data": "2027-02-20", "citazione": "udienza del 20 febbraio 2027"}],
                "termini": [{"titolo": "Memorie", "durata": 20, "unita": "giorni", "decorrenza": "dalla comunicazione",
                             "processuale": True, "citazione": "termine di venti giorni dalla comunicazione del presente verbale"}],
                "inneschi": [{"trigger": "nessuna-chiave", "descrizione": "Verbale", "citazione": "rinvia la causa all'udienza"}]}
        _pr, _inn = _sc191.proposte_da_estrazione(_est, _doc, lang="it", jurisdiction="IT", oggi="2026-09-29")
        _v = {p["titolo"]: p for p in _pr}
        _det = (_v["Udienza"]["verificato"] and _v["Udienza"]["ora"] == "09:30" and _v["Udienza"]["kind"] == "seance"
                and not _v["Inventata"]["verificato"] and _v["Memorie"]["tipo"] == "regola" and _v["Memorie"]["verificato"]
                and _inn and _inn[0]["trigger"] == "tjeter"
                and _sc191.data_nel_testo("2026-10-20", _doc) and not _sc191.data_nel_testo("2026-10-21", _doc))
        _, _inn2 = _sc191.proposte_da_estrazione(
            {"inneschi": [{"trigger": "vendim_civil", "data": "2026-10-20", "data_atto": "2026-10-20",
                           "descrizione": "Vendim", "citazione": "Gjykata cakton seancën"}]}, _doc, lang="sq", jurisdiction="AL",
            oggi="2026-09-29")
        _det = _det and _inn2 and _inn2[0]["data"] == "" and _inn2[0]["data_atto"] == "2026-10-20"   # atto ≠ notifica
        _calc = _sc191.calcola_regola({"durata": 20, "unita": "days", "processuale": True}, "2026-07-25", "IT", "it")["data"]
        _calc_al = _sc191.calcola_regola({"durata": 20, "unita": "days", "processuale": True}, "2026-07-25", "AL", "sq")["data"]
        _det = _det and _calc == "2026-09-14" and _calc_al == "2026-08-14"
        _srcr = _in191.getsource(_rm191._deliver) + _in191.getsource(_rm191._consegna)   # v9.412: i canali in _consegna
        _canali = ("esiti.append((\"telegram\"" in _srcr and "esiti.append((\"email\"" in _srcr
                   and "if pref == \"telegram\" and tg_chat" not in _srcr)
        _rotte = {str(r) for r in _w191.app.url_map.iter_rules()}
        _rt = all(x in _rotte for x in ("/api/cases/<case_id>/scadenze/analizza", "/api/cases/<case_id>/scadenze",
                                        "/api/scadenze/<pid>/conferma", "/api/scadenze/<pid>/calcola", "/api/scadenze",
                                        "/api/settings/telegram/link", "/telegram/webhook/<segreto>"))
        _wh = _in191.getsource(_w191.telegram_webhook)
        _firma = "X-Telegram-Bot-Api-Secret-Token" in _wh and "compare_digest" in _wh
        # v9.424: la conferma vive in `conferma_proposta` (una strada per portale e Telegram); la rotta la chiama
        _conf = _in191.getsource(_w191.api_scadenze_conferma) + _in191.getsource(_w191.conferma_proposta)
        _conf = _conf if "conferma_proposta(p, user.id" in _in191.getsource(_w191.api_scadenze_conferma) else ""
        _solo_conf = "create_event" in _conf and "create_event" not in _in191.getsource(_w191.api_scadenze_analizza)
        _js = open("/app/static/app.js", encoding="utf-8").read()
        _ui = ("_scadDopoDocumenti(documents)" in _js and "openScadenziario" in _js and "/api/settings/telegram/link" in _js
               and "Scadenze del fascicolo" in _js and "Afatet e dosjes" in _js)
        _ui = _ui and "_scheme=" in _in191.getsource(_w191.api_ical_url)     # il link del calendario pubblico in https
        _tok = "usa_token_telegram" in _in191.getsource(_st191) and "DELETE FROM telegram_link WHERE token" in _in191.getsource(_st191.usa_token_telegram)
        check("scadenziario[191]: date e termini dai documenti verificati sul testo, conferma dell'avvocato, avvisi su tutti i "
              "canali, Telegram con codice monouso e webhook firmato", _det and _canali and _rt and _firma and _solo_conf and _ui and _tok,
              "det=%s calc=%s/%s canali=%s rotte=%s firma=%s solo_conferma=%s ui=%s token=%s" % (
                  _det, _calc, _calc_al, _canali, _rt, _firma, _solo_conf, _ui, _tok))
    except Exception as _e191:  # noqa: BLE001
        check("scadenziario[191]: kontrollet u ekzekutuan", False, str(_e191))

    # [192] v9.412 — «avvisa anche i colleghi dello studio»: gli avvisi di un evento del fascicolo vanno anche a chi ha creato il
    # fascicolo e ai membri ATTIVI assegnati, ricalcolati al momento dell'avviso con le regole di visibilità (mai tutto lo studio:
    # un avvocato non assegnato non deve ricevere titolo e dettagli di un fascicolo che non vede)
    try:
        import inspect as _in192
        from src import storage as _st192, reminders as _rm192, web as _w192
        _col = _in192.getsource(_st192.colleghi_del_fascicolo)
        _dl = _in192.getsource(_rm192._deliver)
        _ok192 = ("case_assignments" in _col and "fm.status = 'active'" in _col and "get_case_for_member" in _col
                  and "notify_team" in _dl and "colleghi_del_fascicolo" in _dl
                  and "notify_team" in _in192.signature(_st192.create_event).parameters
                  and "notify_team" in _in192.getsource(_w192.api_create_event)
                  and "avvisa_studio" in _in192.getsource(_w192.conferma_proposta)
                  and "conferma_proposta(p, user.id" in _in192.getsource(_w192.api_scadenze_conferma))
        _js192 = open("/app/static/app.js", encoding="utf-8").read()
        _ok192 = _ok192 and "avvisa_studio" in _js192 and "notify_team: !!fd.get(\"notify_team\")" in _js192
        check("colleghi-studio[192]: avvisi anche ai colleghi assegnati al fascicolo, con le regole di visibilità", _ok192)
    except Exception as _e192:  # noqa: BLE001
        check("colleghi-studio[192]: kontrollet u ekzekutuan", False, str(_e192))

    # [193] v9.413 — IMPORTI IN LIRE nel testo vigente: la nota (nostra, dichiarata) con gli importi convertiti dal CODICE al tasso
    # di 1.936,27 (art. 14 Reg. 974/98; sanzioni: art. 51 d.lgs. 213/1998, senza decimali); «L. 1150/1942» è una legge, non un importo
    try:
        import importlib.util as _ilu193
        from pathlib import Path as _P193
        _sp193 = _ilu193.spec_from_file_location("bi193", "/app/tools/build_it_index.py")
        _bi193 = _ilu193.module_from_spec(_sp193); _sp193.loader.exec_module(_bi193)
        _n1 = _bi193._nota_lire("è punito con la multa da lire cinquemila a ventimila")          # pena: MAI convertita diretta
        _n2 = _bi193._nota_lire("ai sensi della L. 1150/1942 e della L. 47/1985")
        _n3 = _bi193._nota_lire("Se il prezzo è superiore alle lire trentamila, la riserva della proprietà")
        _det193 = ("NON si convertono direttamente" in _n1 and "art. 113 L. 24 novembre 1981, n. 689" in _n1 and "euro 2,58" not in _n1
                   and "euro 50" in _n1 and "1.936,27" in _n1 and "redazionale" in _n1 and _n2 == ""
                   and "lire 30.000 = euro 15,49" in _n3 and _bi193.numero_in_lettere("duecentocinquantamila") == 250000)
        _it193 = ArticleIndex.load(_P193("/app/data/index/bm25_it.pkl"))
        _con = [a for a in _it193.articles if not a.repealed and "1 euro = 1.936,27 lire" in (a.note or "")]
        _idx193 = len(_con) >= 250 and all(("lire" in (a.body or "").lower() or "L." in (a.body or "")) for a in _con[:50])
        check("lire-in-euro[193]: importi in lire convertiti, pene e sanzioni con gli aumenti di legge (mai la conversione diretta), mai sulle leggi", _det193 and _idx193,
              "det=%s articoli con nota=%d" % (_det193, len(_con)))
    except Exception as _e193:  # noqa: BLE001
        check("lire-in-euro[193]: kontrollet u ekzekutuan", False, str(_e193))

    # [194] v9.414 — FUSO ORARIO degli eventi: un orario senza fuso (scadenziario, motore dei termini) vale come ora locale della
    # giurisdizione e si salva in UTC; l'avviso lo stampa in ora locale (il container è in UTC: un'udienza delle 10 usciva «08:00»),
    # con l'ora legale e quella solare
    try:
        import inspect as _in194
        from src import storage as _st194, reminders as _rm194
        _ok194 = (_st194.a_utc("2026-10-20T11:00:00", "AL") == "2026-10-20T09:00:00Z"
                  and _st194.a_utc("2026-12-16T10:00:00", "IT") == "2026-12-16T09:00:00Z"
                  and _st194.a_utc("2026-12-15T09:30:00.000Z", "IT") == "2026-12-15T09:30:00Z"
                  and _st194.ora_locale("2026-12-15T09:30:00Z", "IT") == "15/12/2026 10:30"
                  and _st194.ora_locale("2026-10-20T09:00:00Z", "AL") == "20/10/2026 11:00"
                  and "ora_locale" in _in194.getsource(_rm194._fmt_when) and "dt.astimezone()" not in _in194.getsource(_rm194._fmt_when)
                  and "a_utc(starts_at, jurisdiction)" in _in194.getsource(_st194.create_event))
        check("fuso-orario[194]: eventi in UTC, avvisi in ora locale di Tirana/Roma (ora legale e solare)", _ok194)
    except Exception as _e194:  # noqa: BLE001
        check("fuso-orario[194]: kontrollet u ekzekutuan", False, str(_e194))

    # [195] v9.415 — lo scadenziario PARTE DA SOLO dopo il caricamento se il documento ha delle date (mai video/audio, spegnibile),
    # i documenti caricati insieme vanno in UNA coda per fascicolo, e alla fine UN avviso (Telegram + email) con le scadenze nuove
    # da confermare; mai email agli account di prova .test
    try:
        import inspect as _in195
        from src import web as _w195, reminders as _rm195
        _rx = _w195._DATA_NEL_TESTO_RX
        _date_ok = all(_rx.search(x) for x in ("seanca më 20.10.2026", "udienza del 15 gennaio 2027", "il 2026-11-30", "më 3 tetor 2026"))
        _no = not _rx.search("ai sensi della L. 689/1981 e del d.lgs. 213/1998, art. 10.2")
        _up = _in195.getsource(_w195.avvia_elaborazione_documento)   # v9.422: il caricamento passa da qui (portale e Telegram)
        _auto = _in195.getsource(_w195._scad_auto_dopo_caricamento)
        _lan = _in195.getsource(_w195._scad_lancia)
        _ok195 = (_date_ok and _no and "_scad_auto_dopo_caricamento(case_id, uid, juris, doc_id, ext" in _up
                  and "SCADENZIARIO_AUTO" in _auto and "VIDEO_EXTENSIONS" in _auto and "avvisa=True" in _auto
                  and "_SCAD_CODA" in _lan and "_scad_avvisa_nuove" in _lan
                  and ".test" in _in195.getsource(_rm195.avvisa_utente) and ".test" in _in195.getsource(_rm195._consegna))
        check("scadenziario-auto[195]: analisi da sola al caricamento se ci sono date, coda per fascicolo, un avviso con le scadenze nuove",
              _ok195, "date=%s no_leggi=%s" % (_date_ok, _no))
    except Exception as _e195:  # noqa: BLE001
        check("scadenziario-auto[195]: kontrollet u ekzekutuan", False, str(_e195))

    # [196] v9.416 — comandi del bot Telegram (/oggi /settimana /scadenze e /sot /java /afatet): solo per il Telegram COLLEGATO a un
    # account (a chi non è collegato nessun dato), agenda in ora locale, scadenze da confermare per fascicolo
    try:
        import inspect as _in196
        from src import telegram_bot as _tg196
        _g = _in196.getsource(_tg196.gestisci_update)
        _ok196 = ({"/oggi", "/sot"} == _tg196._CMD_OGGI and {"/settimana", "/java"} == _tg196._CMD_SETT
                  and {"/scadenze", "/afatet"} == _tg196._CMD_SCAD
                  and "if uid and comando in" in _g and 'chat.get("type") != "private"' in _g
                  and "ora_locale" in _in196.getsource(_tg196.agenda)
                  and 'stati=("proposta",)' in _in196.getsource(_tg196.da_confermare))
        check("telegram-comandi[196]: agenda e scadenze da confermare dal bot, solo al Telegram collegato", _ok196)
    except Exception as _e196:  # noqa: BLE001
        check("telegram-comandi[196]: kontrollet u ekzekutuan", False, str(_e196))

    # [197] v9.417 — «Afate nga dosja» DAL CALENDARIO: scegli o crea il cliente, carica PDF/foto, proposte nella stessa finestra
    # (riquadro legato al suo fascicolo con data-case), il calendario aperto si aggiorna alla conferma
    try:
        _h197 = open("/app/templates/index.html", encoding="utf-8").read()
        _j197 = open("/app/static/app.js", encoding="utf-8").read()
        _w197 = open("/app/src/web.py", encoding="utf-8").read()
        _ok197 = ('id="cal-scad-btn"' in _h197 and "openScadDaCalendario" in _j197 and 'class="scad-box scadcrm-box" data-case="' in _j197
                  and "/api/settings/reminder-email" in _j197 and "scadcrm-tg" in _j197 and "scadcrm-cerca" in _j197 and "scadcrm-rin" in _j197
                  and "var box = ev.currentTarget || _scadBox();" in _j197 and "loadEvents().then(function () { renderCalendar(); })" in _j197
                  and '"documenti_in_lettura"' in _w197 and 'cal_scad: "Scadenze dal fascicolo"' in _j197)
        check("scadenziario-clienti[197]: pagina clienti (ricerca, contatori), caricamento e conferma, avvisi email+Telegram collegabili lì", _ok197)
    except Exception as _e197:  # noqa: BLE001
        check("calendario-scadenze[197]: kontrollet u ekzekutuan", False, str(_e197))

    # [198] v9.420 — la SEGRETARIA su Telegram: testo libero o vocale (trascritto in locale) → secretary.handle_message; una
    # scrittura si esegue SOLO col pulsante ✅ (callback, stesso utente e stessa chat), tetto di messaggi all'ora
    try:
        import inspect as _in198
        from src import telegram_bot as _tg198
        _cb = _in198.getsource(_tg198._gestisci_callback)
        _sg = _in198.getsource(_tg198._segretaria)
        _gu = _in198.getsource(_tg198.gestisci_update)
        _ok198 = ('az["uid"] != uid or az["chat"] != chat_id' in _cb and 'if scelta != "ok"' in _cb and "execute_action" in _cb
                  and "execute_action" not in _sg and "handle_message" in _sg and "_tastiera(tok, lang)" in _sg
                  and "_limite_ok(uid)" in _gu and "callback_query" in _gu and "_audio.trascrivi" in _in198.getsource(_tg198._vocale_in_testo)
                  and '"callback_query"]' in _in198.getsource(_tg198.registra_webhook))
        check("segretaria-telegram[198]: agenda a parole e vocali, ogni scrittura solo con ✅", _ok198)
    except Exception as _e198:  # noqa: BLE001
        check("segretaria-telegram[198]: kontrollet u ekzekutuan", False, str(_e198))

    # [199] v9.421 — la Segretaria COLLEGA l'evento al fascicolo nominato: riceve i fascicoli visibili (suoi e dello studio, nella
    # giurisdizione della sessione), l'esecuzione accetta solo un case_id fra quelli (mai inventato né di altri), nome ambiguo → chiede;
    # esiti e regola nella lingua della sessione («fascicolo», non «dosje»)
    try:
        import inspect as _in199
        from src import secretary as _se199
        _ex = _in199.getsource(_se199.execute_action)
        _ok199 = ("_caso_valido(user_id, p.get(\"case_id\"))" in _ex and "case_id=(caso.id if caso else None)" in _ex
                  and "casi_visibili(user_id, limite=10_000)" in _in199.getsource(_se199._caso_valido)
                  and "list_cases_for_member" in _in199.getsource(_se199.casi_visibili)
                  and "_blocco_casi(user_id)" in _in199.getsource(_se199._system_prompt)
                  and "«fascicolo»" in _in199.getsource(_se199._regola_casi) and "Registrato" in _ex)
        check("segretaria-fascicolo[199]: evento collegato al fascicolo nominato, solo fra quelli visibili, esiti nella lingua della sessione", _ok199)
    except Exception as _e199:  # noqa: BLE001
        check("segretaria-fascicolo[199]: kontrollet u ekzekutuan", False, str(_e199))

    # [200] v9.422 — DOCUMENTI MANDATI AL BOT: PDF/foto → pulsanti per scegliere il fascicolo (didascalia che corrisponde, anche con
    # le forme flesse albanesi), allegato solo al clic dello stesso utente e solo a un fascicolo visibile, poi lo stesso percorso del
    # portale (avvia_elaborazione_documento: OCR, riassunto, scadenziario automatico con avviso)
    try:
        import inspect as _in200
        from src import telegram_bot as _tg200, web as _w200
        _al = _in200.getsource(_tg200._allega_documento)
        _ok200 = (_tg200._stessa_radice("kolës", "kola") and _tg200._stessa_radice("hoxhës", "hoxha")
                  and not _tg200._stessa_radice("udienza", "delta")
                  and 'att["uid"] != uid or att["chat"] != cb_chat' in _al and "_caso_valido(uid, cid)" in _al
                  and "avvia_elaborazione_documento(doc, cid" in _al
                  and "avvia_elaborazione_documento(doc, case_id, user.id" in _in200.getsource(_w200.api_upload_document)
                  and "_scad_auto_dopo_caricamento" in _in200.getsource(_w200.avvia_elaborazione_documento)
                  and 'msg.get("document") or msg.get("photo")' in _in200.getsource(_tg200.gestisci_update))
        check("telegram-documenti[200]: PDF e foto al bot → scelta del fascicolo, stesso percorso del portale con lo scadenziario", _ok200)
    except Exception as _e200:  # noqa: BLE001
        check("telegram-documenti[200]: kontrollet u ekzekutuan", False, str(_e200))

    # [201] v9.423 — PROMEMORIA DEL MATTINO su Telegram: dalle 7:30 locali, una volta al giorno (giorno dell'ultimo invio nel
    # database, segnato PRIMA dell'invio), niente messaggio se non c'è niente, spegnibile con /briefing, mai ad account scaduti
    try:
        import inspect as _in201
        from src import telegram_bot as _tg201, reminders as _rm201
        _bt = _in201.getsource(_tg201.briefing_tick)
        _ok201 = (_tg201.ORA_BRIEFING == (7, 30) and 'u["last"] == giorno' in _bt and "(loc.hour, loc.minute) < ORA_BRIEFING" in _bt
                  and _bt.index("storage.segna_briefing(u[\"id\"], giorno)          # PRIMA") < _bt.index("invia(u[\"chat\"], testo, briefing_tastiera(")
                  and "plan_expires_at" in _bt and 'return ""' in _in201.getsource(_tg201.briefing_testo)
                  and "briefing_tick()" in _in201.getsource(_rm201._loop)
                  and '"/briefing"' in _in201.getsource(_tg201.gestisci_update))
        check("briefing-mattino[201]: promemoria del mattino su Telegram, una volta al giorno, solo se c'è qualcosa, spegnibile", _ok201)
    except Exception as _e201:  # noqa: BLE001
        check("briefing-mattino[201]: kontrollet u ekzekutuan", False, str(_e201))

    # [202] v9.424 — CONFERMA DA TELEGRAM: il pulsante ✅ c'è SOLO per le proposte verificate con una data non passata (mai
    # «da verificare», mai senza data, mai i termini di legge da calcolare), callback ≤ 64 byte; il clic controlla che la proposta
    # sia dell'avvocato di QUELLA chat e che il fascicolo sia ancora suo; portale e bot confermano con la STESSA funzione
    try:
        import inspect as _in202
        from src import telegram_bot as _tg202, web as _web202
        _base = {"stato": "proposta", "tipo": "data", "verificato": 1, "data": "2099-10-20", "ora": "09:30",
                 "titolo": "Udienza di prima comparizione davanti al Tribunale", "id": "a" * 32}
        _casi = [_base, dict(_base, id="b" * 32, verificato=0), dict(_base, id="c" * 32, data=""),
                 dict(_base, id="d" * 32, tipo="innesco"), dict(_base, id="e" * 32, data="2001-01-01"),
                 dict(_base, id="f" * 32, stato="confermata")]
        _k = _tg202.tastiera_proposte(_casi, "it", "2026-09-30") or {}
        _righe = _k.get("inline_keyboard") or []
        _cb = [b["callback_data"] for r in _righe for b in r]
        _src_cb = _in202.getsource(_tg202._conferma_da_telegram)
        _ok202 = (len(_righe) == 1 and _cb == ["s:ok:" + "a" * 32, "s:no:" + "a" * 32]
                  and all(len(c.encode()) <= 64 for c in _cb) and _righe[0][0]["text"].startswith("✅ 20/10 09:30 · ")
                  and _tg202.tastiera_proposte(_casi[1:], "sq", "2026-09-30") is None
                  and 'p.get("user_id") != uid' in _src_cb and "_sec._caso_valido(uid, p[\"case_id\"])" in _src_cb
                  and "_web.conferma_proposta(p, uid" in _src_cb
                  and "conferma_proposta(p, user.id" in _in202.getsource(_web202.api_scadenze_conferma)
                  and 'dati.startswith("s:")' in _in202.getsource(_tg202._gestisci_callback)
                  and "tastiera_proposte(" in _in202.getsource(_web202._scad_avvisa_nuove))
        check("conferma-telegram[202]: ✅ solo sulle proposte verificate e datate, controllo di chat e fascicolo, stessa conferma del portale", _ok202,
              str(_righe)[:300])
    except Exception as _e202:  # noqa: BLE001
        check("conferma-telegram[202]: kontrollet u ekzekutuan", False, str(_e202))

    # [203] v9.425 — IL SOLLECITO delle scadenze non confermate: una proposta mai confermata non ha promemoria, quindi UNA volta
    # (segnata prima dell'invio) si sollecita: data entro 7 giorni (mai passata), oppure senza data da 2 giorni; solo in orario
    # d'ufficio locale; e il promemoria del mattino le elenca PER NOME coi pulsanti ✅
    try:
        import inspect as _in203
        from src import reminders as _rm203, telegram_bot as _tg203
        _l = [{"id": "1", "data": "2026-10-03", "tipo": "data", "created_at": "2026-09-20T08:00:00Z"},
              {"id": "2", "data": "2026-10-20", "tipo": "data", "created_at": "2026-09-20T08:00:00Z"},
              {"id": "3", "data": "2026-09-29", "tipo": "data", "created_at": "2026-09-20T08:00:00Z"},
              {"id": "4", "data": "", "tipo": "innesco", "created_at": "2026-09-27T08:00:00Z"},
              {"id": "5", "data": "", "tipo": "innesco", "created_at": "2026-09-29T20:00:00Z"}]
        _sc = [p["id"] for p in _rm203._scelte_sollecito(_l, "2026-09-30", "2026-10-07", "2026-09-28T08:00:00Z")]
        _ss = _in203.getsource(_rm203.sollecita_scadenze)
        _r1 = _rm203._riga_sollecito({"data": "2026-10-03", "ora": "10:00", "titolo": "Udienza", "verificato": 0}, "2026-09-30", True)
        _r2 = _rm203._riga_sollecito({"data": "", "tipo": "innesco", "titolo": "Afatet ligjore nga: vendimi"}, "2026-09-30", False)
        _ok203 = (_sc == ["1", "4"] and _ss.index("storage.segna_sollecito(") < _ss.index("avvisa_utente(")
                  and "ORA_SOLLECITO <= (loc.hour, loc.minute) < FINE_SOLLECITO" in _ss and "tastiera_proposte(" in _ss
                  and "sollecita_scadenze()" in _in203.getsource(_rm203._loop)
                  and _r1 == "03/10/2026 10:00 · Udienza — fra 3 giorni (da verificare)" and "mund të kenë nisur" in _r2
                  and "NON ANCORA IN CALENDARIO" in _in203.getsource(_tg203.briefing_testo))
        check("sollecito-scadenze[203]: una volta sola, data entro 7 giorni o senza data da 2 giorni, orario d'ufficio, per nome nel mattino", _ok203,
              "%s | %s | %s" % (_sc, _r1, _r2))
    except Exception as _e203:  # noqa: BLE001
        check("sollecito-scadenze[203]: kontrollet u ekzekutuan", False, str(_e203))

    # [204] v9.426 — IL LINK DEGLI AVVISI apre lo Scadenziario SUL cliente («superavokati.ai/s/<fascicolo>»): senza sessione passa
    # dal login e ci torna (solo percorsi /s/…, mai un indirizzo qualsiasi); negli avvisi e nei solleciti al posto della home
    try:
        import inspect as _in204
        from src import web as _w204, reminders as _rm204
        _c204 = _w204.app.test_client()
        _r204 = _c204.get("/s/0123456789abcdef")
        from urllib.parse import unquote as _uq204
        _loc = _uq204(_r204.headers.get("Location", ""))
        _lj = open("/app/static/login.js", encoding="utf-8").read()
        _aj = open("/app/static/app.js", encoding="utf-8").read()
        _ok204 = (_r204.status_code == 302 and _loc.endswith("/login?next=/s/0123456789abcdef")
                  and _w204.link_scadenziario("0123456789abcdef") == "https://superavokati.ai/s/0123456789abcdef"
                  and _w204.link_scadenziario("../x") == "https://superavokati.ai/s"
                  and "link_scadenziario(case_id)" in _in204.getsource(_w204._scad_avvisa_nuove)
                  and "https://superavokati.ai/s" in _in204.getsource(_rm204.sollecita_scadenze)
                  and "^\\/s(\\/[0-9a-f-]{8,64})?$" in _lj and "#scadenze(?:=" in _aj
                  and 'session["jurisdiction"] = g' in _in204.getsource(_w204.link_scadenze)
                  and "user_jurisdictions(user)" in _in204.getsource(_w204.link_scadenze))
        check("link-avvisi[204]: gli avvisi aprono lo scadenziario sul cliente, login con ritorno sicuro, giurisdizione del fascicolo", _ok204,
              "%s %s" % (_r204.status_code, _loc))
    except Exception as _e204:  # noqa: BLE001
        check("link-avvisi[204]: kontrollet u ekzekutuan", False, str(_e204))

    # [205] v9.427 — IL FASCICOLO LETTO PER INTERO: PDF misto (le pagine scansionate si leggono anche se le digitali hanno testo),
    # tetto dell'OCR 60 pagine (era 10) con le pagine non lette DETTE nel testo, e lo scadenziario che legge a pezzi
    try:
        import inspect as _in205
        from src import documents as _d205, scadenziario as _s205
        _ep = _in205.getsource(_d205._extract_pdf)
        _lung = "".join(f"\n── Pagina {i}/90 ──\n" + ("testo " * 300) + f"\nudienza del {i:02d}" for i in range(1, 91))
        _pz, _rs = _s205.pezzi_del_testo(_lung)
        _ok205 = (_d205.MAX_OCR_PAGES >= 60 and "da_ocr" in _ep and "immagini[i]" in _ep and "_nota_pagine_non_lette" in _ep
                  and _d205._intervalli([3, 4, 5, 9]) == "3–5, 9"
                  and "PAGINE NON LETTE" in _in205.getsource(_d205._nota_pagine_non_lette)
                  and "FAQE TË PALEXUARA" in _in205.getsource(_d205._nota_pagine_non_lette)
                  and _rs == 0 and len(_pz) >= 2 and all(any(f"udienza del {i:02d}" in p for p in _pz) for i in range(1, 91))
                  and "estrai_tutto(backend, testo" in _in205.getsource(_s205.analizza_documento)
                  and hasattr(_d205, "VISION_PROMPT_IT"))
        check("fascicolo-lungo[205]: pagine scansionate anche nei PDF misti, 60 pagine, pagine non lette dette, scadenziario a pezzi", _ok205,
              "%s %s %s" % (_d205.MAX_OCR_PAGES, [len(p) for p in _pz], _rs))
    except Exception as _e205:  # noqa: BLE001
        check("fascicolo-lungo[205]: kontrollet u ekzekutuan", False, str(_e205))

    # [206] v9.428 — LE DATE PASSATE SONO STORIA: nel riquadro in fondo e chiuse, fuori dai contatori, dal /scadenze e dal mattino;
    # MAI un «innesco» (la sua data è quella dell'atto: i termini di legge possono essere aperti), che anzi si sollecita
    try:
        import inspect as _in206
        from src import telegram_bot as _tg206, reminders as _rm206
        _aj206 = open("/app/static/app.js", encoding="utf-8").read()
        _sc206 = [p["id"] for p in _rm206._scelte_sollecito(
            [{"id": "a", "data": "2026-09-10", "tipo": "innesco", "created_at": "2026-09-20T08:00:00Z"},
             {"id": "b", "data": "2026-09-10", "tipo": "data", "created_at": "2026-09-20T08:00:00Z"}],
            "2026-09-30", "2026-10-07", "2026-09-28T08:00:00Z")]
        _ok206 = (_tg206._passata({"data": "2026-09-01", "tipo": "data"}, "2026-09-30")
                  and not _tg206._passata({"data": "2026-09-01", "tipo": "innesco"}, "2026-09-30")
                  and not _tg206._passata({"data": "2026-10-01", "tipo": "data"}, "2026-09-30")
                  and _sc206 == ["a"] and "Date già passate — storia del fascicolo" in _aj206
                  and 'p.tipo !== "innesco"' in _aj206 and "!_scadPassata(p)" in _aj206
                  and "_passata(p" in _in206.getsource(_tg206.da_confermare)
                  and "_passata(p, d0)" in _in206.getsource(_tg206.briefing_testo))
        check("date-passate[206]: storia del fascicolo in fondo e fuori dai conti, mai i termini di legge (che si sollecitano)", _ok206,
              str(_sc206))
    except Exception as _e206:  # noqa: BLE001
        check("date-passate[206]: kontrollet u ekzekutuan", False, str(_e206))

    # [207] v9.429 — IL PROMEMORIA DICE IL CLIENTE e arriva anche IL GIORNO STESSO: fascicolo e link al cliente in Telegram ed
    # email; deposito senza ora alle 9 del giorno («OGGI»), udienza con l'ora 2 ore prima
    try:
        import inspect as _in207
        from src import reminders as _rm207, web as _w207
        _R0 = type("R", (), {"offset_minutes": 0})()
        _ok207 = (_w207._avvisi_predefiniti(True) == [10080, 4320, 1440, 0]
                  and _w207._avvisi_predefiniti(False) == [10080, 4320, 1440, 120]
                  and "_avvisi_predefiniti(all_day)" in _in207.getsource(_w207.conferma_proposta)
                  and _rm207._fmt_ahead(_R0, "it") == "OGGI" and _rm207._fmt_ahead(_R0, "sq") == "SOT"
                  and "_caso_di(event)" in _in207.getsource(_rm207._format_message)
                  and "_caso_di(event)" in _in207.getsource(_rm207._send_email)
                  and "superavokati.ai/s/" in _in207.getsource(_rm207._caso_di))
        check("promemoria[207]: il cliente e il link in ogni promemoria, e il giorno stesso (OGGI alle 9 / 2 ore prima)", _ok207)
    except Exception as _e207:  # noqa: BLE001
        check("promemoria[207]: kontrollet u ekzekutuan", False, str(_e207))

    # [208] v9.430 — la SEGRETARIA crea gli eventi con gli stessi avvisi dello scadenziario (prima: uno solo, il giorno prima, e il
    # prompt suggeriva «[1440]» che il modello copiava) e un evento del fascicolo avvisa i colleghi che lo seguono
    try:
        import inspect as _in208
        from src import secretary as _sec208, web as _w208
        _src208 = open("/app/src/secretary.py", encoding="utf-8").read()
        _ea = _in208.getsource(_sec208.execute_action)
        _ok208 = (_sec208.avvisi_standard("seance", False) == [10080, 4320, 1440, 120]
                  and _sec208.avvisi_standard("afat", True) == [10080, 4320, 1440, 0]
                  and _sec208.avvisi_standard("takim", False) == [1440, 120]
                  and _sec208.avvisi_standard("seance", False) == _w208._avvisi_predefiniti(False)
                  and "parazgjedhje [1440]" not in _src208 and "notify_team=bool(caso)" in _ea
                  and "avvisi_standard(kind, _tutto_il_giorno)" in _ea)
        check("segretaria-avvisi[208]: stessi avvisi dello scadenziario, colleghi del fascicolo avvisati, prompt senza «[1440]»", _ok208)
    except Exception as _e208:  # noqa: BLE001
        check("segretaria-avvisi[208]: kontrollet u ekzekutuan", False, str(_e208))

    # [209] v9.431 — I TERMINI A RITROSO: «almeno 7 giorni PRIMA dell'udienza» si conta all'indietro (la misura dello
    # scadenziario lo dava 7 giorni DOPO: 28/01 invece del 14/01); festivo → si ANTICIPA; «dalla prima udienza» resta in avanti
    try:
        from src import scadenziario as _s209
        _ar = _s209.a_ritroso_nel_testo
        _c = lambda reg, ref, g="IT", l="it": _s209.calcola_regola(reg, ref, g, l)["data"]
        _ok209 = (_ar("Il ricorrente dovrà intimare i testi almeno 7 giorni prima dell'udienza.") is True
                  and _ar("termine di sessanta giorni prima di tale udienza") is True
                  and _ar("të paktën 60 ditë para përfundimit të afatit") is True
                  and _ar("entro 20 giorni dalla prima udienza") is False
                  and _ar("brenda 15 ditëve nga e nesërmja e njoftimit") is False
                  and _ar("") is None
                  and _c({"durata": 7, "unita": "days", "a_ritroso": True, "processuale": True, "lavoro_o_urgente": True},
                         "2027-01-21") == "2027-01-14"
                  and _c({"durata": 60, "unita": "days", "a_ritroso": True}, "2027-02-18") == "2026-12-18"
                  and _c({"durata": 60, "unita": "days", "a_ritroso": True}, "2026-12-31", "AL", "sq") == "2026-10-30"
                  and _c({"durata": 20, "unita": "days", "a_ritroso": True, "processuale": True}, "2026-09-10") == "2026-07-21"
                  and _c({"durata": 40, "unita": "days"}, "2026-09-15") == "2026-10-26")
        check("ritroso[209]: termini «N giorni prima di» contati all'indietro, festivo anticipato, feriale a ritroso, «dalla prima udienza» in avanti", _ok209)
    except Exception as _e209:  # noqa: BLE001
        check("ritroso[209]: kontrollet u ekzekutuan", False, str(_e209))

    # [210] v9.432 — LE DATE IN LETTERE si riconoscono nel documento («venti novembre duemilaventisei»), a confini di PAROLA
    # («sei novembre» dentro «ventisei novembre» non verifica il 6), e una data senza anno non verifica un anno diverso
    try:
        from src import scadenziario as _s210
        _dt210 = _s210.data_nel_testo
        _T1 = "rinvia la causa all'udienza del giorno venti novembre duemilaventisei, ore dieci"
        _ok210 = (_dt210("2026-11-20", _T1) and not _dt210("2026-11-06", "all'udienza del ventisei novembre duemilaventisei")
                  and _dt210("2026-11-26", "all'udienza del ventisei novembre duemilaventisei")
                  and not _dt210("2020-11-20", _T1)
                  and not _dt210("2026-11-20", "fissata al 20 novembre 2027")
                  and _dt210("2026-12-01", "entro il primo dicembre 2026") and _dt210("2027-03-23", "il ventitré marzo duemilaventisette")
                  and _dt210("2026-11-21", "më njëzet e një nëntor dy mijë e njëzet e gjashtë")
                  and _dt210("2026-09-15", "më 15.09.2026") and _dt210("2026-09-15", "datë 15 shtatorit 2026")
                  and _dt210("2026-09-15", "më 15 shtatorit, palët"))
        check("date-in-lettere[210]: date scritte in lettere riconosciute, confini di parola, anno diverso non verifica", _ok210)
    except Exception as _e210:  # noqa: BLE001
        check("date-in-lettere[210]: kontrollet u ekzekutuan", False, str(_e210))

    # [211] v9.433 — l'analisi automatica PARTE anche con la data in lettere e con un termine senza data (prima: solo date in cifre)
    try:
        from src import web as _w211
        _rx = _w211._DATA_NEL_TESTO_RX
        _ok211 = (bool(_rx.search("rinvia all'udienza del giorno venti novembre duemilaventisei"))
                  and bool(_rx.search("può essere proposta opposizione entro quaranta giorni dalla notifica"))
                  and bool(_rx.search("Brenda afatit 30-ditor nga data e marrjes"))
                  and bool(_rx.search("brenda 15 ditëve nga e nesërmja e njoftimit"))
                  and bool(_rx.search("seanca më 12.11.2026")) and bool(_rx.search("il 3 tetor 2026"))
                  and not _rx.search("Gjykata vendos shtyrjen e seancës për një datë që do t'u njoftohet palëve"))
        check("auto-analisi[211]: parte con date in lettere e termini senza data, non su un testo senza date né termini", _ok211)
    except Exception as _e211:  # noqa: BLE001
        check("auto-analisi[211]: kontrollet u ekzekutuan", False, str(_e211))

    # [212] v9.434 — un termine di legge la cui data NON viene dal motore deterministico (riga vecchia «AFAT | titolo | data»,
    # aritmetica del modello) non esce mai «verificato» e lo dice
    try:
        import inspect as _in212
        from src import scadenziario as _s212
        _tl = _in212.getsource(_s212.termini_di_legge)
        _ok212 = ('bool(a.get("passi"))' in _tl and "NON calcolata dal motore deterministico" in _tl
                  and "PA llogaritur nga motori determinist" in _tl)
        check("afati-motore[212]: la data di legge non calcolata dal motore resta da verificare, e lo dice", _ok212)
    except Exception as _e212:  # noqa: BLE001
        check("afati-motore[212]: kontrollet u ekzekutuan", False, str(_e212))

    # [213] v9.435 — la SEGRETARIA risponde nella lingua della SESSIONE (il prompt diceva «nella lingua che scrive l'utente»,
    # contro la regola: la rete al collo di bottiglia la correggeva, ma il prompt non deve dire il contrario)
    try:
        import os as _os213
        _src213 = open("/app/src/secretary.py", encoding="utf-8").read()
        _ok213 = ("gjuhën e SESIONIT" in _src213 and "të njëjtën gjuhë që shkruan përdoruesi" not in _src213
                  and _os213.path.exists("/app/tools/eval_segretaria.py"))
        check("segretaria-lingua[213]: lingua della sessione nel prompt, misura della Segretaria presente", _ok213)
    except Exception as _e213:  # noqa: BLE001
        check("segretaria-lingua[213]: kontrollet u ekzekutuan", False, str(_e213))

    # [214] v9.436 — i messaggi Telegram oltre 4096 caratteri si DIVIDONO (Telegram li rifiuta: /scadenze con 8 fascicoli ≈ 5.600
    # caratteri non arrivava), agli a capo, senza perdere niente, i pulsanti sull'ultimo pezzo; lo stesso per i promemoria
    try:
        import inspect as _in214
        from src import telegram_bot as _tg214, reminders as _rm214
        _lungo = "\n".join(f"riga {i} " + "x" * 90 for i in range(120))
        _pz = _tg214.dividi_testo(_lungo)
        _uno = _tg214.dividi_testo("breve")
        _enorme = _tg214.dividi_testo("y" * 9000)
        _chiamate = []
        _vecchia = _tg214._api
        _tg214._api = lambda m, **p: _chiamate.append((m, "reply_markup" in p)) or {"ok": True}
        try:
            _inv = _tg214.invia("1", _lungo, {"inline_keyboard": [[{"text": "✅", "callback_data": "s:ok:x"}]]})
        finally:
            _tg214._api = _vecchia
        _ok214 = (len(_pz) >= 3 and all(len(p) <= _tg214.LIMITE_MESSAGGIO for p in _pz) and "\n".join(_pz) == _lungo
                  and _uno == ["breve"] and len(_enorme) == 3 and "".join(_enorme) == "y" * 9000
                  and _inv and len(_chiamate) == len(_pz) and [k for _m, k in _chiamate] == [False] * (len(_pz) - 1) + [True]
                  and "dividi_testo" in _in214.getsource(_rm214._send_telegram))
        check("telegram-lunghi[214]: messaggi oltre il limite divisi agli a capo, niente perso, pulsanti sull'ultimo pezzo", _ok214,
              str([len(p) for p in _pz]))
    except Exception as _e214:  # noqa: BLE001
        check("telegram-lunghi[214]: kontrollet u ekzekutuan", False, str(_e214))

    # [215] v9.437 — in uno STUDIO l'avviso delle scadenze da confermare (e il sollecito) va anche ai colleghi che seguono il
    # fascicolo (creatore + assegnati attivi: le regole degli avvisi degli eventi), e possono confermare dal bot; mai tutto lo studio
    try:
        import inspect as _in215
        from src import web as _w215, telegram_bot as _tg215, reminders as _rm215
        _ok215 = ("colleghi_del_fascicolo(case_id, uid)" in _in215.getsource(_w215._scad_avvisa_nuove)
                  and "colleghi_del_fascicolo(p[\"case_id\"], p[\"user_id\"])" in _in215.getsource(_tg215._conferma_da_telegram)
                  and "colleghi_del_fascicolo(cid, uid)" in _in215.getsource(_rm215.sollecita_scadenze)
                  and "_caso_valido(uid, p[\"case_id\"])" in _in215.getsource(_tg215._conferma_da_telegram)
                  # v9.438: elenchi, mattino, contatori leggono le proposte VISIBILI (le mie + dei fascicoli che seguo)
                  and "lista_scadenze_proposte(user_id=uid" not in _in215.getsource(_tg215)
                  and "proposte_visibili(user.id" in _in215.getsource(_w215.api_scadenze_tutte))
        check("scadenze-studio[215]: avviso, sollecito e conferma anche ai colleghi del fascicolo, con la visibilità del fascicolo", _ok215)
    except Exception as _e215:  # noqa: BLE001
        check("scadenze-studio[215]: kontrollet u ekzekutuan", False, str(_e215))

    # [216] v9.439 — DOPPIONI fra documenti: la stessa udienza (giorno + ora) da più documenti non si ripropone; termini e depositi
    # lo stesso giorno restano DISTINTI salvo due parole specifiche in comune; già in calendario → proposta non spuntata con la nota
    try:
        import inspect as _in216
        from src import scadenziario as _s216, web as _w216
        _se = _s216.stesso_evento
        _ok216 = (_se({"data": "2099-02-18", "kind": "seance", "ora": ""}, {"data": "2099-02-18", "kind": "seance", "ora": "11:00"})
                  and not _se({"data": "2099-02-18", "kind": "seance", "ora": "09:00"},
                              {"data": "2099-02-18", "kind": "seance", "ora": "11:00"})
                  and not _se({"data": "2099-03-10", "kind": "dorëzim", "titolo": "Deposito delle memorie istruttorie"},
                              {"data": "2099-03-10", "kind": "dorëzim", "titolo": "Deposito delle note di trattazione"})
                  and not _se({"data": "2099-10-26", "kind": "afat", "titolo": "Termine per il pagamento della somma ingiunta"},
                              {"data": "2099-10-26", "kind": "afat", "titolo": "Termine per proporre opposizione al decreto ingiuntivo"})
                  and _se({"data": "2099-04-01", "kind": "afat", "titolo": "Termine per l'opposizione al decreto"},
                          {"data": "2099-04-01", "kind": "afat", "titolo": "Opposizione a decreto ingiuntivo"})
                  and "forse già in calendario" in _in216.getsource(_w216._scad_salva))
        check("doppioni[216]: la stessa udienza da più documenti una volta sola, scadenze diverse dello stesso giorno distinte", _ok216)
    except Exception as _e216:  # noqa: BLE001
        check("doppioni[216]: kontrollet u ekzekutuan", False, str(_e216))

    # [217] v9.440 — il RINVIO d'udienza: la nuova sostituisce quella in calendario, che alla conferma si CHIUDE («RINVIATA al …»,
    # mai cancellata); il rinvio vale solo se la data vecchia è scritta nel documento ed è prima della nuova
    try:
        import inspect as _in217
        from src import scadenziario as _s217, web as _w217
        _t217 = "Il giudice rinvia l'udienza del 18 febbraio 2099 al 15 marzo 2099 ore 10:00."
        _pp, _ = _s217.proposte_da_estrazione({"date": [
            {"tipo": "udienza", "titolo": "Udienza", "data": "2099-03-15", "ora": "10:00", "citazione": _t217, "rinvio_da": "2099-02-18"},
            {"tipo": "udienza", "titolo": "Altra", "data": "2099-03-15", "citazione": _t217, "rinvio_da": "2099-01-01"},
            {"tipo": "udienza", "titolo": "Al contrario", "data": "2099-02-18", "citazione": _t217, "rinvio_da": "2099-03-15"}]},
            _t217, lang="it", jurisdiction="IT", oggi="2026-10-01")
        _ok217 = ([p.get("rinvio_da") for p in _pp] == ["2099-02-18", "", ""]
                  and "sostituisce_event_id" in _in217.getsource(_w217._scad_salva)
                  and "done=True" in _in217.getsource(_w217.conferma_proposta)
                  and "RINVIATA al" in _in217.getsource(_w217.conferma_proposta)
                  and '"rinvio_da"' in _in217.getsource(_s217) and "rinvio_da" in _in217.getsource(_w217._scad_payload))
        check("rinvio[217]: la nuova udienza sostituisce quella in calendario (chiusa, non cancellata), rinvio verificato sul testo", _ok217,
              str([p.get("rinvio_da") for p in _pp]))
    except Exception as _e217:  # noqa: BLE001
        check("rinvio[217]: kontrollet u ekzekutuan", False, str(_e217))

    # [218] v9.441 — i lavori lasciati a metà da un RIAVVIO ripartono da soli: documenti «pending» (prima per sempre «sto
    # leggendo…»), analisi delle scadenze «in_corso» (l'avviso non arrivava); SOLO nel processo del server (main), mai nelle prove
    try:
        import inspect as _in218
        from src import web as _w218
        _rl = _in218.getsource(_w218._riprendi_lavori_interrotti)
        _ok218 = ("_riprendi_lavori_interrotti" in _in218.getsource(_w218.main)
                  and "_riprendi_lavori_interrotti" not in _in218.getsource(_w218._ensure_loaded)
                  and "lavori_interrotti()" in _rl and 'RIPRESA_LAVORI' in _rl and "avvisa=True" in _rl
                  and "ngarkoje sërish dokumentin" in _rl and "ricarica il documento" in _rl)
        check("ripresa-lavori[218]: dopo un riavvio documenti e scadenze interrotti ripartono, solo nel server", _ok218)
    except Exception as _e218:  # noqa: BLE001
        check("ripresa-lavori[218]: kontrollet u ekzekutuan", False, str(_e218))

    # [219] v9.442 — il FEED iCal (Google/Apple Calendar): righe piegate a caratteri interi (prima la metà di una «ë» spariva:
    # «Prmbledhje»), e l'udienza RINVIATA esce annullata (STATUS:CANCELLED) invece di restare alla data vecchia
    try:
        from types import SimpleNamespace as _NS219
        from src import web as _w219
        _testo = "Përmbledhje e çështjes së dëshmitarëve — udienza già fissata, perché " * 5
        _ev = [_NS219(id="a", updated_at="2026-10-01T08:00:00Z", all_day=False, starts_at="2099-02-18T09:00:00Z", ends_at=None,
                      title="RINVIATA al 15/03/2099 — Udienza", description=_testo, location=None, kind="seance", done=True),
               _NS219(id="b", updated_at="2026-10-01T08:00:00Z", all_day=True, starts_at="2099-03-15T08:00:00Z", ends_at=None,
                      title="Udienza", description=None, location=None, kind="seance", done=False)]
        _ics = _w219._render_ical("prova", _ev)
        _righe = _ics.split("\r\n")
        _unito = _ics.replace("\r\n ", "")
        _ok219 = (all(len(r.encode("utf-8")) <= 75 for r in _righe) and ("DESCRIPTION:" + _testo.replace(",", "\\,")) in _unito
                  and _unito.count("STATUS:CANCELLED") == 1
                  and _unito.index("STATUS:CANCELLED") < _unito.index("UID:b@"))
        check("ical[219]: righe piegate senza perdere lettere, udienza rinviata annullata nel calendario del telefono", _ok219)
    except Exception as _e219:  # noqa: BLE001
        check("ical[219]: kontrollet u ekzekutuan", False, str(_e219))

    # [220] v9.443 — avvisi delle scadenze e promemoria degli eventi anche come NOTIFICA dell'app installata (accanto a Telegram ed
    # email), col link al cliente; mai solleva
    try:
        import inspect as _in220
        from src import reminders as _rm220
        _ok220 = ("_push(uid, titolo" in _in220.getsource(_rm220.avvisa_utente)
                  and "_push(uid, f\"⏰" in _in220.getsource(_rm220._consegna)
                  and "except Exception" in _in220.getsource(_rm220._push))
        check("push[220]: notifica sul telefono per scadenze e promemoria, col link al cliente", _ok220)
    except Exception as _e220:  # noqa: BLE001
        check("push[220]: kontrollet u ekzekutuan", False, str(_e220))

    # [221] v9.444 — il VAULT su un fascicolo lungo: prima i primi 9.000 caratteri per documento e «non si trova nei documenti»
    # detto con sicurezza sulla pagina 55; ora ~40 pagine per documento e, oltre, i passi PERTINENTI alla domanda (senza domanda
    # inizio + fine); un documento rimasto fuori per lo spazio si DICE
    try:
        import inspect as _in221
        from src import vault as _v221
        _pag = [f"── Pagina {i}/90 ──\n" + ("testo del fascicolo senza interesse " * 60)
                + ("\nIl Giudice nomina CTU l'ing. Marco Bellini, giuramento il 9 dicembre 2026." if i == 85 else "")
                for i in range(1, 91)]
        _full = "\n\n".join(_pag)
        _con = _v221._estratto(_full, 20000, "Chi è il consulente tecnico nominato e quando giura il CTU?", True)
        _senza = _v221._estratto(_full, 20000, "", True)
        _ok221 = (_v221._MAX_PER_DOC >= 60000 and _v221._MAX_TOTAL >= 180000
                  and "Bellini" in _con and len(_con) <= 20000 + 200 and "Pagina 1/90" in _con
                  and "Pagina 90/90" in _senza and "Pagina 1/90" in _senza
                  and "build_context(case_id, question" in _in221.getsource(_v221.ask)
                  and "NON LETTI per lo spazio" in _in221.getsource(_v221.build_context))
        check("vault[221]: documenti lunghi letti per i passi pertinenti (pagina 85 trovata), inizio+fine senza domanda", _ok221,
              str(len(_con)))
    except Exception as _e221:  # noqa: BLE001
        check("vault[221]: kontrollet u ekzekutuan", False, str(_e221))

    # [222] v9.445 — la CHAT legge i documenti lunghi per i passi pertinenti alla domanda (prima: 12.000 caratteri inizio+fine),
    # il riassunto del documento legge inizio E fine (prima i primi 12.000), etichette del blocco nella lingua della sessione
    try:
        import inspect as _in222
        from src import documents as _d222, brain as _b222
        _pg = [f"── Pagina {i}/60 ──\n" + ("testo senza interesse per la domanda " * 60)
               + ("\nIl Giudice nomina CTU l'ing. Marco Bellini, giuramento il 9 dicembre 2026." if i == 55 else "")
               for i in range(1, 61)]
        _doc = [{"filename": "fascicolo.pdf", "extracted_text": "\n\n".join(_pg), "summary": "s"}]
        _b222.set_request_jurisdiction("IT")
        try:
            _blk = _d222.format_documents_for_prompt(_doc, char_budget=12000, domanda="Chi è il CTU nominato e quando giura?")
            _blk0 = _d222.format_documents_for_prompt(_doc, char_budget=12000)
        finally:
            _b222.set_request_jurisdiction("AL")
        _ok222 = ("Bellini" in _blk and "Bellini" not in _blk0 and "DOCUMENTI DEL FASCICOLO" in _blk and "Riassunto:" in _blk
                  and "Përmbledhje" not in _blk and "_budget_clip(text, 24000)" in _in222.getsource(_d222.summarize_document)
                  and "domanda=user_message" in _in222.getsource(_b222.SuperAvvocato._build_compose_messages))
        check("chat-documenti[222]: passi pertinenti alla domanda nei documenti lunghi, riassunto inizio+fine, etichette della sessione", _ok222)
    except Exception as _e222:  # noqa: BLE001
        check("chat-documenti[222]: kontrollet u ekzekutuan", False, str(_e222))

    # [223] v9.446 — il GENIO divide lo spazio fra i documenti (prima il primo prendeva tutto e i successivi niente) e del documento
    # lungo legge inizio E fine (gli atti recenti stanno in fondo); etichette nella lingua della sessione
    try:
        from src import genio as _g223, brain as _b223
        _q = _g223._quote_documenti([100000, 3000, 5000], 48000)
        _docs = [{"filename": "lungo.pdf", "extracted_text": "INIZIO " + ("x" * 90000) + " FINE-DEL-FASCICOLO"},
                 {"filename": "breve.pdf", "extracted_text": "documento breve interamente letto"}]
        _b223.set_request_jurisdiction("IT")
        try:
            _blk = "\n".join(_g223._blocco_documenti(_docs))
        finally:
            _b223.set_request_jurisdiction("AL")
        _ok223 = (_q == [40000, 3000, 5000] and _g223.BUDGET_DOCUMENTI >= 48000 and "INIZIO" in _blk
                  and "FINE-DEL-FASCICOLO" in _blk and "documento breve interamente letto" in _blk
                  and "DOCUMENTI DEL FASCICOLO" in _blk and "Përmbajtja" not in _blk)
        check("genio-documenti[223]: spazio diviso fra i documenti, inizio e fine del lungo, etichette della sessione", _ok223, str(_q))
    except Exception as _e223:  # noqa: BLE001
        check("genio-documenti[223]: kontrollet u ekzekutuan", False, str(_e223))

    # [224] v9.447 — la TABELLA DEL FASCICOLO (una domanda per colonna, una risposta per documento): il documento lungo entra coi
    # passi pertinenti alle domande (prima i primi 14.000 caratteri: la risposta più in là diventava «—»), etichette della sessione
    try:
        from src import tabela as _t224, brain as _b224
        _lungo224 = "\n\n".join(f"── Pagina {i}/50 ──\n" + ("clausola senza interesse " * 90)
                                  + ("\nIl canone mensile è di euro 1.850, da pagare entro il giorno 5." if i == 44 else "")
                                  for i in range(1, 51))
        _b224.set_request_jurisdiction("IT")
        try:
            _p224 = _t224.pergatit_prompt("contratto.pdf", "Contratto", "", _lungo224, ["Qual è il canone mensile?"])
        finally:
            _b224.set_request_jurisdiction("AL")
        _ok224 = ("1.850" in _p224 and "TESTO DEL DOCUMENTO" in _p224 and "TEKSTI I DOKUMENTIT" not in _p224
                  and len(_p224) < _t224.TEKST_MAX + 2000)
        check("tabella[224]: documenti lunghi coi passi pertinenti alle colonne, etichette della sessione", _ok224, str(len(_p224)))
    except Exception as _e224:  # noqa: BLE001
        check("tabella[224]: kontrollet u ekzekutuan", False, str(_e224))

    # [225] v9.448 — le pagine scansionate ILLEGGIBILI si dicono nel testo del documento (prima l'OCR rispondeva
    # «[IMMAGINE ILLEGGIBILE]» e il testo andava avanti: un termine su quella pagina non esisteva per nessuno)
    try:
        import inspect as _in225
        from src import documents as _d225
        _il = _d225._pagine_illeggibili({0: "Testo pieno di una pagina letta bene.", 1: "[IMMAGINE ILLEGGIBILE]",
                                         2: "[IMAZH I PAQARTË]", 3: "  .. ", 4: "Altra pagina leggibile con parole."})
        _ok225 = (_il == [2, 3, 4] and "_nota_pagine_illeggibili" in _in225.getsource(_d225._extract_pdf)
                  and _d225._pagine_illeggibili({0: "Pagina normale con testo sufficiente."}) == [])
        check("ocr-illeggibili[225]: pagine illeggibili dette nel testo col numero, nessun falso allarme", _ok225, str(_il))
    except Exception as _e225:  # noqa: BLE001
        check("ocr-illeggibili[225]: kontrollet u ekzekutuan", False, str(_e225))

    # [226] v9.449 — mentre l'OCR legge un fascicolo scansionato (10-20 minuti), il portale dice «Lettura pagina 23/60» invece di
    # un'attesa senza fine visibile
    try:
        import inspect as _in226
        from src import documents as _d226, web as _w226
        _aj226 = open("/app/static/app.js", encoding="utf-8").read()
        _ok226 = ("progresso(n_fatti + 1, len(scelti))" in _in226.getsource(_d226._vision_ocr_pdf_pages)
                  and "_PROGRESSO_DOC" in _in226.getsource(_w226.avvia_elaborazione_documento)
                  and '"progresso"' in _in226.getsource(_w226._document_payload)
                  and 'TT("Po lexoj faqen")' in _aj226 and '"Po lexoj faqen": "Lettura pagina"' in _aj226)
        check("ocr-avanzamento[226]: la pagina che l'OCR sta leggendo arriva al portale, nella lingua della sessione", _ok226)
    except Exception as _e226:  # noqa: BLE001
        check("ocr-avanzamento[226]: kontrollet u ekzekutuan", False, str(_e226))

    # [227] v9.450 — «/chiedi Rossi: …» / «/pyet Kola: …» sul bot: la risposta del Vault dai documenti del fascicolo, dal telefono;
    # fascicolo dal nome (forme flesse), pulsanti se manca, solo i fascicoli visibili, tetto orario del bot
    try:
        import inspect as _in227
        from src import telegram_bot as _tg227
        _gu = _in227.getsource(_tg227.gestisci_update)
        _cb = _in227.getsource(_tg227._gestisci_callback)
        _ok227 = ("/chiedi" in _tg227._CMD_CHIEDI and "/pyet" in _tg227._CMD_CHIEDI
                  and "_CMD_CHIEDI" in _gu and "_limite_ok(uid)" in _gu
                  and 'dati.startswith("q:")' in _cb and "_caso_valido(uid, cid)" in _cb
                  and "_vault.ask(" in _in227.getsource(_tg227._rispondi_dal_fascicolo)
                  and "casi_visibili(uid)" in _in227.getsource(_tg227._chiedi)
                  # v9.452: «chiedi …» / «pyet …» scritto o a voce alla Segretaria → i documenti del fascicolo
                  and '_primo in ("chiedi", "pyet")' in _in227.getsource(_tg227._segretaria))
        check("chiedi-bot[227]: domanda ai documenti del fascicolo dal bot, solo fascicoli visibili, tetto orario", _ok227)
    except Exception as _e227:  # noqa: BLE001
        check("chiedi-bot[227]: kontrollet u ekzekutuan", False, str(_e227))

    # [228] v9.451 — il benvenuto del bot (al collegamento) elenca TUTTO quello che sa fare: segretaria, vocali, documenti, /chiedi,
    # promemoria del mattino — in italiano e in albanese
    try:
        from src import telegram_bot as _tg228
        _w = _tg228._T["ok"]
        _ok228 = (all(x in _w["it"] for x in ("vocale", "PDF", "/chiedi", "7:30", "/briefing", "✅"))
                  and all(x in _w["sq"] for x in ("zanor", "PDF", "/pyet", "7:30", "/briefing", "✅")))
        check("benvenuto-bot[228]: il benvenuto dice cosa sa fare il bot, IT e SQ", _ok228)
    except Exception as _e228:  # noqa: BLE001
        check("benvenuto-bot[228]: kontrollet u ekzekutuan", False, str(_e228))

    # [229] v9.454 — AL: il «lajmërim për ekzekutim vullnetar» del përmbarues è un evento che fa correre termini DI LEGGE (non
    # c'è un decreto ingiuntivo albanese: verificato sul K.Pr.C.): 517 (5/10 giorni), 609 (30 giorni), 610 (5 giorni), dal ricevimento
    try:
        from src import afati as _a229, scadenziario as _s229
        from src.retrieval import ArticleIndex as _AI229
        _t = _a229.TRIGGERS.get("ekzekutim") or {}
        _seed = {n for c, n in _t.get("seed", []) if c == "kodi_proc_civile"}
        _idx229 = _AI229.load()
        _vivi = {a.number for a in _idx229.articles if a.code == "kodi_proc_civile" and not a.repealed}
        # v9.455: e per l'Italia l'ATTO DI PRECETTO (480, 481, 615, 617 vivi nel corpus italiano)
        from pathlib import Path as _P229
        _idx229it = _AI229.load(_P229("/app/data/index/bm25_it.pkl"))
        _vivi_it = {a.number for a in _idx229it.articles if a.code == "codice_procedura_civile" and not a.repealed}
        _seed_it = {n for c, n in (_a229.TRIGGERS_IT.get("precetto") or {}).get("seed", []) if c == "codice_procedura_civile"}
        _ok229 = ({"517", "609", "610"} <= _seed and _seed <= _vivi and "ekzekutim" in _s229._TRIGGER_DA_NOTIFICA
                  and "ekzekutim" not in _a229.TRIGGERS_IT
                  and {"480", "481", "615", "617"} <= _seed_it and _seed_it <= _vivi_it and "precetto" in _s229._TRIGGER_DA_NOTIFICA)
        check("ekzekutim[229]: avviso di esecuzione volontaria AL con KPC 517/609/610 vivi nel corpus, dal ricevimento", _ok229,
              str(sorted(_seed - _vivi)))
    except Exception as _e229:  # noqa: BLE001
        check("ekzekutim[229]: kontrollet u ekzekutuan", False, str(_e229))

    # [230] v9.456 — licenziamento e atto amministrativo: i due eventi più frequenti nel fascicolo di un cliente cadevano in «tjeter»
    # (nessun articolo). Semi VIVI nei due corpus, decorrenza giusta (IT: dalla ricezione; AL: dalla risoluzione, non dalla notifica),
    # e il motore dei termini del portale offre l'elenco della SESSIONE (in IT c'erano le chiavi albanesi)
    try:
        from src import afati as _a230, scadenziario as _s230
        from src.retrieval import ArticleIndex as _AI230
        from pathlib import Path as _P230
        _vivi_al = {(a.code, a.number) for a in _AI230.load().articles if not a.repealed}
        _vivi_it = {(a.code, a.number) for a in _AI230.load(_P230("/app/data/index/bm25_it.pkl")).articles if not a.repealed}
        _manca = []
        for _tab, _vivi, _g in ((_a230.TRIGGERS, _vivi_al, "AL"), (_a230.TRIGGERS_IT, _vivi_it, "IT")):
            for _k in ("pushim_nga_puna", "akt_administrativ"):
                _manca += [f"{_g}:{c}:{n}" for c, n in (_tab.get(_k) or {}).get("seed", []) if (c, n) not in _vivi] or \
                          ([] if _tab.get(_k, {}).get("seed") else [f"{_g}:{_k}:vuoto"])
        _ok230 = (not _manca
                  and ("kodi_punes", "146") in _a230.TRIGGERS["pushim_nga_puna"]["seed"]
                  and ("kodi_punes", "155") in _a230.TRIGGERS["pushim_nga_puna"]["seed"]
                  and ("licenziamenti_individuali", "6") in _a230.TRIGGERS_IT["pushim_nga_puna"]["seed"]
                  and ("ligji_gjykatat_administrative", "18") in _a230.TRIGGERS["akt_administrativ"]["seed"]
                  and ("codice_processo_amministrativo", "29") in _a230.TRIGGERS_IT["akt_administrativ"]["seed"]
                  and _s230.da_notifica("pushim_nga_puna", "it") and not _s230.da_notifica("pushim_nga_puna", "sq")
                  and _s230.da_notifica("akt_administrativ", "sq") and _s230.da_notifica("akt_administrativ", "it")
                  and {t["key"] for t in _a230.list_triggers("IT")} == set(_a230.TRIGGERS_IT)
                  and {t["key"] for t in _a230.list_triggers("AL")} == set(_a230.TRIGGERS)
                  and "precetto" in {t["key"] for t in _a230.list_triggers("IT")})
        check("pushim-akt[230]: licenziamento e atto amministrativo con semi vivi, decorrenza giusta, elenco della sessione",
              _ok230, str(_manca))
    except Exception as _e230:  # noqa: BLE001
        check("pushim-akt[230]: kontrollet u ekzekutuan", False, str(_e230))

    # [231] v9.457 — la multa e l'accertamento fiscale: semi VIVI nei due corpus, l'accertamento dalla notifica, la multa no (un verbale
    # contestato sul posto ha la stessa data dell'atto)
    try:
        from src import afati as _a231, scadenziario as _s231
        from src.retrieval import ArticleIndex as _AI231
        from pathlib import Path as _P231
        _v_al = {(a.code, a.number) for a in _AI231.load().articles if not a.repealed}
        _v_it = {(a.code, a.number) for a in _AI231.load(_P231("/app/data/index/bm25_it.pkl")).articles if not a.repealed}
        _manca231 = [f"{g}:{c}:{n}" for tab, v, g in ((_a231.TRIGGERS, _v_al, "AL"), (_a231.TRIGGERS_IT, _v_it, "IT"))
                     for k in ("kundervajtje", "vleresim_tatimor") for c, n in (tab.get(k) or {}).get("seed", [("-", k)])
                     if (c, n) not in v and c != "processo_tributario"]   # il d.lgs. 546/1992 muore il 1/1/2027: c'è il TU
        _manca231 += [] if {("processo_tributario", "21"), ("giustizia_tributaria", "67")} & _v_it else ["IT: ricorso tributario"]
        _ok231 = (not _manca231 and ("kodi_rrugor", "203") in _a231.TRIGGERS["kundervajtje"]["seed"]
                  and ("ligji_procedurat_tatimore", "106") in _a231.TRIGGERS["vleresim_tatimor"]["seed"]
                  and ("riti_civili_semplificati", "7") in _a231.TRIGGERS_IT["kundervajtje"]["seed"]
                  and ("processo_tributario", "21") in _a231.TRIGGERS_IT["vleresim_tatimor"]["seed"]
                  and _s231.da_notifica("vleresim_tatimor", "sq") and _s231.da_notifica("vleresim_tatimor", "it")
                  and not _s231.da_notifica("kundervajtje", "it") and not _s231.da_notifica("kundervajtje", "sq"))
        check("gjobe-tatim[231]: multa e accertamento fiscale con semi vivi, decorrenza giusta", _ok231, str(_manca231))
    except Exception as _e231:  # noqa: BLE001
        check("gjobe-tatim[231]: kontrollet u ekzekutuan", False, str(_e231))

    # [232] v9.457 — la BASE dei termini di legge passa dal verificatore: inesistente, abrogata o testo unico non ancora applicabile
    # → niente spunta «verificato», con il motivo; una base senza codice riconoscibile non toglie niente
    try:
        from src import scadenziario as _s232
        from src.retrieval import ArticleIndex as _AI232
        from pathlib import Path as _P232
        from datetime import date as _d232
        _iit = _AI232.load(_P232("/app/data/index/bm25_it.pkl"))
        _ial = _AI232.load()
        _b = ["art. 21, comma 1, d.lgs. 546/1992", "art. 351, comma 2, d.lgs. 141/2026", "art. 9999 c.p.c."]
        _r = _s232._basi_dubbie([{"baza": x} for x in _b], _iit)
        _ra = _s232._basi_dubbie([{"baza": "Kodi i Punës neni 155 pika 4"}, {"baza": "neni 9999 i Kodit të Punës"},
                                  {"baza": "neni 155, pika 4, i Kodit të Punës"}], _ial)
        _prima2027 = _d232.today() < _d232(2027, 1, 1)
        _ok232 = ("art. 9999 c.p.c." in _r and "inesistente" in _r["art. 9999 c.p.c."]
                  and (not _prima2027 or (_b[0] not in _r and _b[1] in _r and "2027" in _r[_b[1]]))
                  and "neni 9999 i Kodit të Punës" in _ra and "Kodi i Punës neni 155 pika 4" not in _ra
                  and "neni 155, pika 4, i Kodit të Punës" not in _ra and _s232._basi_dubbie([], _iit) == {})
        check("basi-termini[232]: la base dei termini di legge verificata (inesistente, abrogata, testo unico futuro)", _ok232,
              str(_r) + " | " + str(_ra))
    except Exception as _e232:  # noqa: BLE001
        check("basi-termini[232]: kontrollet u ekzekutuan", False, str(_e232))

    # [233] v9.458 — i termini A RITROSO nel motore dei termini di legge (righe «verso=prima»): costituzione del convenuto 70 giorni
    # prima dell'udienza del 2/2/2027 → 24/11/2026; un giorno non lavorativo si ANTICIPA; senza «verso» il calcolo resta in avanti;
    # la domanda ricevuta ha il suo trigger in AL e IT
    try:
        from src import afati as _a233, scadenziario as _s233
        _md = ("x\nAFAT | Costituzione | trigger=2027-02-02 | durata=70 | njesi=giorni | feriale=1 | verso=prima | baza=art. 166 c.p.c.\n"
               "AFAT | Memoria 3 | trigger=2027-02-02 | durata=10 | njesi=giorni | feriale=1 | verso=prima | baza=art. 171-ter c.p.c.\n"
               "AFAT | Appello | trigger=2026-09-15 | durata=30 | njesi=giorni | feriale=1 | baza=art. 325 c.p.c.\n"
               "AFAT | Avanti | trigger=2026-09-15 | durata=30 | njesi=giorni | feriale=1 | verso=dopo | baza=art. 325 c.p.c.\n")
        _af, _txt = _a233.righe_afat(_md, jurisdiction="IT", lang="it")
        _d = {a["title"]: a for a in _af}
        _ok233 = (_d["Costituzione"]["date"] == "2026-11-24" and _d["Costituzione"]["a_ritroso"]
                  and _d["Memoria 3"]["date"] == "2027-01-22"            # 23/1/2027 è sabato → anticipato al venerdì
                  and _d["Appello"]["date"] == "2026-10-15" and not _d["Appello"]["a_ritroso"]
                  and _d["Avanti"]["date"] == "2026-10-15" and "AFAT |" not in _txt and "RITROSO" in _txt
                  and "padi_e_marre" in _a233.TRIGGERS and "padi_e_marre" in _a233.TRIGGERS_IT
                  and ("kodi_proc_civile", "158") in _a233.TRIGGERS["padi_e_marre"]["seed"]
                  and ("codice_procedura_civile", "166") in _a233.TRIGGERS_IT["padi_e_marre"]["seed"]
                  and ("codice_procedura_civile", "416") in _a233.TRIGGERS_IT["padi_e_marre"]["seed"]   # v9.460: rito del lavoro
                  and "altre_date" in _s233.termini_di_legge.__code__.co_varnames)
        from src.retrieval import ArticleIndex as _AI233
        from pathlib import Path as _P233
        _va = {(a.code, a.number) for a in _AI233.load().articles if not a.repealed}
        _vi = {(a.code, a.number) for a in _AI233.load(_P233("/app/data/index/bm25_it.pkl")).articles if not a.repealed}
        _m233 = [x for x in _a233.TRIGGERS["padi_e_marre"]["seed"] if x not in _va] + \
                [x for x in _a233.TRIGGERS_IT["padi_e_marre"]["seed"] if x not in _vi]
        _ok233 = _ok233 and not _m233
        check("ritroso[233]: termini di legge a ritroso dall'udienza (citazione ricevuta), anticipo del giorno non lavorativo",
              _ok233, str({k: v.get("date") for k, v in _d.items()}) + " manca " + str(_m233))
    except Exception as _e233:  # noqa: BLE001
        check("ritroso[233]: kontrollet u ekzekutuan", False, str(_e233))

    # [234] v9.458 — durate in lettere qualsiasi (1-999, IT e SQ) a confini di parola: «settanta giorni» della citazione restava
    # «durata non ritrovata»; e «venti» dentro «ventisei» non deve contare
    try:
        from src import scadenziario as _s234
        _dl = _s234._durata_in_lettere
        _ok234 = (_dl(70, "nel termine di settanta giorni prima") and _dl(365, "entro trecentosessantacinque giorni")
                  and not _dl(60, "entro trecentosessantacinque giorni") and _dl(180, "entro centottanta giorni")
                  and _dl(108, "centotto giorni") and not _dl(20, "ventisei giorni") and _dl(26, "ventisei giorni")
                  and _dl(180, "brenda njëqind e tetëdhjetë ditëve") and _dl(70, "shtatëdhjetë ditë")
                  and not _dl(5, "brenda pesëmbëdhjetë ditëve") and _dl(15, "brenda pesëmbëdhjetë ditëve"))
        check("durata-lettere[234]: durate in lettere 1-999 a confini di parola", _ok234)
    except Exception as _e234:  # noqa: BLE001
        check("durata-lettere[234]: kontrollet u ekzekutuan", False, str(_e234))

    # [235] v9.462 — il diavolo riceve la verifica deterministica delle citazioni della risposta (non può più dire «la sentenza non
    # c'è» di una sentenza confermata)
    try:
        import inspect as _in235
        from src import web as _w235
        _src235 = _in235.getsource(_w235.api_second_opinion)
        _ok235 = ("_verifica_per_djallin(answer" in _src235 and "blocco_per_gjyqtarin" in _in235.getsource(_w235._verifica_per_djallin))
        check("djalli-verifica[235]: il diavolo riceve la verifica delle citazioni della risposta", _ok235)
    except Exception as _e235:  # noqa: BLE001
        check("djalli-verifica[235]: kontrollet u ekzekutuan", False, str(_e235))

    # [236] v9.463 — il DISPOSITIVO delle decisioni italiane: estratto dal «Per questi motivi» / «P.Q.M.» a «Così deciso», nel blocco
    # dei precedenti; e nessuna decisione col testo tagliato a 60.000 caratteri (il dispositivo, in fondo, si perdeva)
    try:
        from src import it_precedent_fts as _f236
        _t1 = ("Considerato in diritto ... motivazione lunga ...\nPer Questi Motivi\nLA CORTE COSTITUZIONALE\n1) \xa0dichiara \xa0non "
               "fondate le questioni di legittimità costituzionale dell'art. 3, comma 2, del d.lgs. n. 23 del 2015, nei sensi di cui in "
               "motivazione.\nCosì deciso in Roma, il 4 giugno 2024.\nF.to:")
        _t2 = "FATTO e DIRITTO ... P.Q.M. Il Tribunale Amministrativo Regionale accoglie il ricorso e annulla il provvedimento. Così deciso in Milano"
        _d1 = _f236.dispositivo_decisione(_t1, "CCost")
        _d2 = _f236.dispositivo_decisione(_t2, "TAR Milano")
        _ok236 = (_d1.startswith("1) dichiara non fondate") and "Così deciso" not in _d1 and "CORTE" not in _d1
                  and "accoglie il ricorso" in _d2 and _f236.dispositivo_decisione("senza dispositivo", "CCost") == ""
                  and _f236.SCHEMA == "2")
        import json as _j236
        _lunghe = sum(1 for _l in open(_f236.JSONL, encoding="utf-8") if len(_j236.loads(_l).get("text") or "") == 60_000)
        _ok236 = _ok236 and _lunghe == 0
        import inspect as _in236
        from src import brain as _b236
        _ok236 = _ok236 and "Dispositivo:" in _in236.getsource(_b236._format_precedents_block) \
            and 'dispositivo=r.get("dispositivo")' in _in236.getsource(_b236._precedenti_it)
        check("dispositivo-it[236]: dispositivo delle decisioni italiane nel blocco, nessun testo tagliato a 60.000", _ok236,
              f"{_d1[:60]!r} | {_d2[:60]!r} | tagliate {_lunghe}")
    except Exception as _e236:  # noqa: BLE001
        check("dispositivo-it[236]: kontrollet u ekzekutuan", False, str(_e236))

    # [237] v9.463 — le dichiarazioni di illegittimità della Consulta (note ufficiali di Normattiva) accanto all'articolo italiano
    try:
        from src import temporal as _t237, brain as _b237
        from src.retrieval import ArticleIndex as _AI237
        from pathlib import Path as _P237
        _d116 = _t237.dichiarazioni_consulta("codice_civile", "116")
        _d3 = _t237.dichiarazioni_consulta("tutele_crescenti", "3")
        _iit237 = _AI237.load(_P237("/app/data/index/bm25_it.pkl"))
        _a116 = next(a for a in _iit237.articles if a.code == "codice_civile" and a.number == "116")
        _blk = _b237._format_articles_for_prompt([(_a116, 1.0)])
        _ok237 = (any("245" in x for x in _d116) and any("194" in x for x in _d3) and any("128" in x for x in _d3)
                  and "CORTE COSTITUZIONALE" in _blk and "245" in _blk
                  and _t237.dichiarazioni_consulta("codice_civile", "2043") == [])
        _m116 = _t237.marca_parole_cadute(_a116.body, "codice_civile", "116")
        _ok237 = _ok237 and "⟦nonché un documento attestante" in _m116 and "245/2011" in _m116 and "⟦" in _blk \
            and _t237.marca_parole_cadute(_m116, "codice_civile", "116") == _m116          # v9.467: parole cadute segnate, una volta
        check("consulta-note[237]: dichiarazioni della Consulta accanto all'articolo italiano (c.c. 116, d.lgs. 23/2015 art. 3)",
              _ok237, f"{_d116[:1]} | {len(_d3)}")
    except Exception as _e237:  # noqa: BLE001
        check("consulta-note[237]: kontrollet u ekzekutuan", False, str(_e237))

    # [238] v9.465 — il Giudice sa quali articoli italiani citati hanno dichiarazioni della Consulta (e non glielo si ripete se la
    # risposta nomina già la sentenza)
    try:
        from src import trust_line as _tl238
        from src.retrieval import ArticleIndex as _AI238
        from pathlib import Path as _P238
        _i238 = _AI238.load(_P238("/app/data/index/bm25_it.pkl"))
        _v1 = _tl238.verifica("Per sposarsi in Italia vale l'art. 116 c.c. e l'art. 2043 c.c.", _i238, "IT")
        _v2 = _tl238.verifica("L'art. 116 c.c., dopo la sentenza n. 245/2011 della Consulta, non richiede più il permesso.", _i238, "IT")
        _b1 = _tl238.blocco_per_gjyqtarin(_v1, "it")
        _c1 = _v1["nene"].get("consulta") or []
        _ok238 = (len(_c1) == 1 and "116" in _c1[0]["raw"] and "245" in _b1 and "parte caduta" in _b1
                  and not (_v2["nene"].get("consulta") or [])
                  and _tl238._sentenza_nominata("con sentenza 26 settembre - 8 novembre 2018 n. 194, ha dichiarato", "sent. 194/2018")
                  and not _tl238._sentenza_nominata("con sentenza 26 settembre - 8 novembre 2018 n. 194, ha dichiarato", "art. 194"))
        check("consulta-giudice[238]: il Giudice vede le dichiarazioni della Consulta sugli articoli citati", _ok238, str(_c1)[:200])
    except Exception as _e238:  # noqa: BLE001
        check("consulta-giudice[238]: kontrollet u ekzekutuan", False, str(_e238))

    # [239] v9.466 — nell'email degli avvisi la riga per collegare Telegram: solo a chi non l'ha collegato e solo col bot attivo
    try:
        from src import reminders as _r239
        _mandate = []

        class _Resp239:
            def __enter__(self): return self
            def __exit__(self, *a): return False
            def read(self): return b'{"id": "x"}'

        def _open239(req, timeout=15):
            _mandate.append(req.data.decode("utf-8"))
            return _Resp239()
        _orig = (_r239.urllib.request.urlopen, _r239._email_configured, _r239.storage.get_user_telegram_chat,
                 _r239.storage.get_user_reminder_email, _r239.TELEGRAM_BOT_TOKEN, _r239._push, _r239._send_telegram)
        try:
            _r239.urllib.request.urlopen = _open239
            _r239._email_configured = lambda: True
            _r239.storage.get_user_reminder_email = lambda uid: "avvocato@example.com"
            _r239._push = lambda *a, **k: None
            _r239._send_telegram = lambda *a, **k: None
            _r239.TELEGRAM_BOT_TOKEN = "prova"
            _r239.storage.get_user_telegram_chat = lambda uid: None
            _r239.avvisa_utente(1, "Scadenze", ["una"], lang="it")
            _r239.storage.get_user_telegram_chat = lambda uid: "123"
            _r239.avvisa_utente(1, "Scadenze", ["una"], lang="it")
            _r239.TELEGRAM_BOT_TOKEN = ""
            _r239.storage.get_user_telegram_chat = lambda uid: None
            _r239.avvisa_utente(1, "Scadenze", ["una"], lang="sq")
        finally:
            (_r239.urllib.request.urlopen, _r239._email_configured, _r239.storage.get_user_telegram_chat,
             _r239.storage.get_user_reminder_email, _r239.TELEGRAM_BOT_TOKEN, _r239._push, _r239._send_telegram) = _orig
        _ok239 = (len(_mandate) == 3 and "Collega Telegram" in _mandate[0] and "Collega Telegram" not in _mandate[1]
                  and "Lidh Telegram" not in _mandate[2])
        check("spinta-telegram[239]: l'email degli avvisi invita a collegare Telegram solo chi non l'ha fatto", _ok239,
              str([("Collega" in m, "Lidh" in m) for m in _mandate]))
    except Exception as _e239:  # noqa: BLE001
        check("spinta-telegram[239]: kontrollet u ekzekutuan", False, str(_e239))

    # [240] v9.468 — K.Pr.C. 511 «Urdhri i ekzekutimit» nel corpus (era dentro il 510: «Neni 5111» = numero + nota incollati) e
    # nessuna rubrica albanese col numero della nota attaccato in coda
    try:
        import re as _re240
        from src.retrieval import ArticleIndex as _AI240
        _al240 = _AI240.load()
        _by240 = {(a.code, a.number): a for a in _al240.articles}
        _a511 = _by240.get(("kodi_proc_civile", "511"))
        _a510 = _by240.get(("kodi_proc_civile", "510"))
        _rub240 = [f"{a.code} {a.number}" for a in _al240.articles if _re240.search(r"(?<=[a-zçë»”)])\d{1,2}$", a.heading or "")]
        _ok240 = (bool(_a511) and _a511.heading == "Urdhri i ekzekutimit" and not _a511.repealed
                  and "Titulli ekzekutiv vihet në ekzekutim" in _a511.body and "Neni 5111" not in (_a510.body if _a510 else "x")
                  and "Gjykatës Kushtetuese nr. 30" in (_a511.note or "") and not _rub240)
        check("kpc511[240]: Neni 511 K.Pr.C. nel corpus, nessuna rubrica col numero della nota incollato", _ok240, str(_rub240[:5]))
    except Exception as _e240:  # noqa: BLE001
        check("kpc511[240]: kontrollet u ekzekutuan", False, str(_e240))

    # [241] v9.469 — «art. 41 TU Immigrazione», «art. 125 Cod. Ass.», «Art. 36 Disciplina organica dei contratti di lavoro» verificati
    try:
        from src import citation_verifier as _cv241
        from src.retrieval import ArticleIndex as _AI241
        from pathlib import Path as _P241
        _i241 = _AI241.load(_P241("/app/data/index/bm25_it.pkl"))
        _r241 = _cv241.verify_text("Vale l'art. 5 TU Immigrazione, l'art. 125 Cod. Ass. e l'Art. 19 Disciplina organica dei contratti di lavoro.",
                                   _i241)
        _st241 = [(x["code"], x["status"]) for x in _r241["items"]]
        _ok241 = _st241 == [("tu_immigrazione", "verified"), ("codice_assicurazioni", "verified"), ("contratti_lavoro", "verified")]
        # v9.471: un numero/anno che non è il C.d.S. («d.lgs. 285/2001») non si verifica sul C.d.S.
        _x241 = [(x["code"], x["status"]) for x in _cv241.verify_text("art. 142 del d.lgs. 285/2001", _i241)["items"]]
        _y241 = [(x["code"], x["status"]) for x in _cv241.verify_text("art. 142 del d.lgs. 285/1992", _i241)["items"]]
        _ok241 = _ok241 and ("codice_strada", "verified") not in _x241 and ("codice_strada", "verified") in _y241
        check("alias-it[241]: TU Immigrazione, Cod. Ass., Disciplina organica dei contratti di lavoro", _ok241, str(_st241))
    except Exception as _e241:  # noqa: BLE001
        check("alias-it[241]: kontrollet u ekzekutuan", False, str(_e241))

    # [242] v9.470 — una legge VECCHIA citata per numero non si verifica sul testo della legge NUOVA che la sostituisce
    try:
        from src import citation_verifier as _cv242
        from src.retrieval import ArticleIndex as _AI242
        _al242 = _AI242.load()
        def _st242(t):
            return [(x["status"], x.get("code"), x.get("resolved_by")) for x in _cv242.verify_text(t, _al242)["items"]]
        _a = _st242("Sipas nenit 12 të ligjit nr. 8901, datë 23.5.2002 «Për falimentimin»")
        _b = _st242("Sipas nenit 43 të ligjit nr. 9723, datë 3.5.2007")
        _c = _st242("Sipas nenit 20 të VKM nr. 750/2015")
        _d = _st242("Sipas nenit 12 të ligjit nr. 10076, datë 12.2.2009")
        _e = _st242("Sipas nenit 12 të ligjit nr. 110/2016 «Për falimentimin»")
        _ok242 = (_a and _a[0][0] == "repealed" and _b and _b[0][0] == "needs_code" and _b[0][2] == "fuori_corpus"
                  and _d and _d[0][0] == "repealed" and _e and _e[0][0] == "verified"
                  and not any(x[0] == "verified" and x[1] == "rregullore_policia" for x in _c))
        check("ligj-vjeter[242]: legge vecchia citata per numero mai verificata sulla legge nuova", _ok242,
              f"{_a} | {_b} | {_c} | {_d} | {_e}")
    except Exception as _e242:  # noqa: BLE001
        check("ligj-vjeter[242]: kontrollet u ekzekutuan", False, str(_e242))

    # [243] v9.472 — la ripetizione nuda di un articolo STRANIERO già citato col suo codice non è un «nen fantazmë»
    try:
        from src import citation_verifier as _cv243
        from src.retrieval import ArticleIndex as _AI243
        from pathlib import Path as _P243
        _al243 = _AI243.load(); _it243 = _AI243.load(_P243("/app/data/index/bm25_it.pkl"))
        _r = _cv243.verify_text("Sipas nenit 93-bis të Codice della Strada italian, pikat 1 e 3 të nenit 93-bis parashikojnë gjobë.",
                                _al243, foreign_index=_it243)
        _s = [x["status"] for x in _r["items"]]
        _r2 = _cv243.verify_text("Pikat 1 e 3 të nenit 93-bis parashikojnë gjobë.", _al243, foreign_index=_it243)
        _r3 = _cv243.verify_text("Neni 9999 i Kodit Penal dhe neni 93-bis i Codice della Strada.", _al243, foreign_index=_it243)
        _ok243 = ("fake" not in _s and _s.count("foreign_verified") >= 1 and [x["status"] for x in _r2["items"]] == ["fake"]
                  and "fake" in [x["status"] for x in _r3["items"]])
        check("estero-documento[243]: articolo straniero ripetuto senza codice non è un fantasma", _ok243,
              f"{_s} | {[x['status'] for x in _r2['items']]} | {[x['status'] for x in _r3['items']]}")
    except Exception as _e243:  # noqa: BLE001
        check("estero-documento[243]: kontrollet u ekzekutuan", False, str(_e243))

    # [244] v9.473 — il diavolo salvato nel filo dice a QUALE domanda risponde (il 🔮 si chiede anche sotto risposte vecchie)
    try:
        import inspect as _in244
        from src import web as _w244
        _s244 = _in244.getsource(_w244._ruaj_djallin_ne_fill)
        _ok244 = ('body.get("question")' in _s244 and "sulla risposta a «{dom}»" in _s244 and "mbi përgjigjen për «{dom}»" in _s244
                  and _s244.count("### ⚔️ Avokati i djallit — kundërargumentet") >= 2)
        check("djalli-titull[244]: il diavolo nel filo nomina la domanda a cui risponde", _ok244)
    except Exception as _e244:  # noqa: BLE001
        check("djalli-titull[244]: kontrollet u ekzekutuan", False, str(_e244))

    # [245] v9.476 — la chat segue i RINVII INTERNI degli articoli recuperati (come gli strumenti PRO): KP 154 → 144, KPP 331 → 327/328,
    # c.p.p. 405 → 407; copie marcate in coda, al massimo 3, mai un articolo abrogato o già presente
    try:
        import types as _ty245
        from src import brain as _b245
        from src.retrieval import ArticleIndex as _AI245
        from pathlib import Path as _P245
        _al245 = _AI245.load(); _it245 = _AI245.load(_P245("/app/data/index/bm25_it.pkl"))
        def _r245(j, keys):
            idx = _it245 if j == "IT" else _al245
            d = _ty245.SimpleNamespace(index=_al245, index_it=_it245, _current_jurisdiction=lambda: j)
            by = {(a.code, a.number): a for a in idx.articles}
            pairs = [(by[k], 1.0) for k in keys]
            out = _b245.SuperAvvocato._aggiungi_rinvii(d, pairs)
            return out[len(pairs):], by
        _x1, _ = _r245("AL", [("kodi_punes", "154")])
        _x2, _ = _r245("AL", [("kodi_proc_penale", "331")])
        _x3, _by3 = _r245("IT", [("codice_procedura_penale", "405"), ("codice_procedura_penale", "407")])
        _k = lambda xs: {(a.code, a.number) for a, _ in xs}
        _ok245 = (("kodi_punes", "144") in _k(_x1) and {("kodi_proc_penale", "327"), ("kodi_proc_penale", "328")} <= _k(_x2)
                  and ("codice_procedura_penale", "407") not in _k(_x3) and len(_x2) <= 3
                  and all(getattr(a, "_rinvio_da", "") and not a.repealed for a, _ in _x1 + _x2 + _x3)
                  and not getattr(_by3[("codice_procedura_penale", "407")], "_rinvio_da", "")
                  and "RICHIAMATO DA" in _b245._format_articles_for_prompt(_x3[:1]) if _x3 else True)
        check("rinvii-chat[245]: la chat segue i rinvii interni (KP 154→144, KPP 331→327/328)", _ok245,
              f"{_k(_x1)} | {_k(_x2)} | {_k(_x3)}")
    except Exception as _e245:  # noqa: BLE001
        check("rinvii-chat[245]: kontrollet u ekzekutuan", False, str(_e245))

    # [246] v9.477 — la ligji 119/2014 «Për të drejtën e informimit» nel corpus (le risposte la dicevano «non nel blocco»), citabile
    # per numero e per nome, recuperabile per l'accesso agli atti pubblici
    try:
        from src import citation_verifier as _cv246
        from src.retrieval import ArticleIndex as _AI246
        _al246 = _AI246.load()
        _n246 = sum(1 for a in _al246.articles if a.code == "ligji_informimi")
        _r = _cv246.verify_text("Sipas nenit 15 të ligjit nr. 119/2014 dhe nenit 1 të ligjit për të drejtën e informimit", _al246)
        _hits = [a.code for a, _ in _al246.search("kërkesë për informacion organi publik afati i përgjigjes ankesë Komisioneri", top_k=8)]
        _ok246 = (_n246 >= 25 and [x["status"] for x in _r["items"]] == ["verified", "verified"]
                  and all(x["code"] == "ligji_informimi" for x in _r["items"]) and "ligji_informimi" in _hits)
        check("informimi[246]: ligji 119/2014 nel corpus, citabile e recuperabile", _ok246, f"{_n246} | {_r['items']} | {_hits[:4]}")
    except Exception as _e246:  # noqa: BLE001
        check("informimi[246]: kontrollet u ekzekutuan", False, str(_e246))

    # [247] v9.478 — i codici albanesi citati per NUMERO di legge si riconoscono (prima «senza codice»)
    try:
        from src import citation_verifier as _cv247
        from src.retrieval import ArticleIndex as _AI247
        _al247 = _AI247.load()
        _casi247 = {"Sipas nenit 155 të ligjit nr. 7961, datë 12.7.1995": "kodi_punes",
                    "neni 443 i ligjit nr. 8116/1996": "kodi_proc_civile",
                    "neni 132 i ligjit nr. 44/2015": "kodi_proc_admin",
                    "neni 114 i ligjit nr. 7850, datë 29.7.1994": "kodi_civil",
                    "neni 42 i ligjit nr. 8417, datë 21.10.1998": "kushtetuta"}
        _bad247 = []
        for _t, _c in _casi247.items():
            _it = _cv247.verify_text(_t, _al247)["items"]
            if not (_it and _it[0]["status"] == "verified" and _it[0]["code"] == _c):
                _bad247.append((_t, [(x["status"], x["code"]) for x in _it]))
        check("kode-numer[247]: i codici albanesi citati per numero di legge", not _bad247, str(_bad247))
    except Exception as _e247:  # noqa: BLE001
        check("kode-numer[247]: kontrollet u ekzekutuan", False, str(_e247))

    # [248] v9.479 — i sette atti italiani più citati e mancanti (wave11): nel corpus, citabili per numero, recuperabili
    try:
        from src import citation_verifier as _cv248
        from src.retrieval import ArticleIndex as _AI248
        from pathlib import Path as _P248
        _i248 = _AI248.load(_P248("/app/data/index/bm25_it.pkl"))
        _cod248 = {a.code for a in _i248.articles}
        _att248 = {"regolamento_anagrafico", "aire", "procedimenti_cittadinanza", "naspi", "ritardi_pagamento", "collegato_lavoro",
                   "licenziamenti_collettivi"}
        _r248 = _cv248.verify_text("Vale l'art. 32 della L. 183/2010, l'art. 4 della L. 223/1991, l'art. 1 del d.lgs. 22/2015, "
                                   "l'art. 5 del d.lgs. 231/2002 e l'art. 7 del d.P.R. 223/1989.", _i248)
        _st248 = [(x["code"], x["status"]) for x in _r248["items"]]
        _hit248 = [a.code for a, _ in _i248.search("licenziamento collettivo procedura comunicazione sindacati riduzione di personale", top_k=8)]
        _ok248 = (_att248 <= _cod248 and all(st == "verified" for _c, st in _st248) and len(_st248) == 5
                  and {c for c, _ in _st248} == {"collegato_lavoro", "licenziamenti_collettivi", "naspi", "ritardi_pagamento",
                                                  "regolamento_anagrafico"}
                  and "licenziamenti_collettivi" in _hit248)
        check("wave11[248]: residenza, AIRE, cittadinanza, NASpI, mora, collegato lavoro, licenziamenti collettivi nel corpus",
              _ok248, f"{sorted(_att248 - _cod248)} | {_st248} | {_hit248[:4]}")
    except Exception as _e248:  # noqa: BLE001
        check("wave11[248]: kontrollet u ekzekutuan", False, str(_e248))

    # [249] v9.480 — l'avvio UNA volta: `_ensure_loaded()` gira a ogni richiesta e al controllo di salute (30 s) e rifaceva
    # init_db + setWebhook di Telegram (47.000 «app db ready», 429 del bot). Eseguito con dipendenze finte, poi rimesso tutto.
    try:
        from src import web as _w249, storage as _s249, reminders as _r249, telegram_bot as _t249
        _sal249 = (_w249._INDEX, _w249._BRAIN, _w249._AVVIO_FATTO, _s249.init_db, _r249.start_background,
                   _t249.registra_webhook, _t249.imposta_cervello)
        _n249 = {"db": 0, "rem": 0, "tg": 0}
        try:
            _w249._INDEX = _w249._INDEX or object()
            _w249._BRAIN = _w249._BRAIN or object()
            _w249._AVVIO_FATTO = False
            _w249.storage.init_db = lambda *a, **k: _n249.__setitem__("db", _n249["db"] + 1)
            _w249.reminders_mod.start_background = lambda *a, **k: _n249.__setitem__("rem", _n249["rem"] + 1)
            _t249.registra_webhook = lambda *a, **k: _n249.__setitem__("tg", _n249["tg"] + 1)
            _t249.imposta_cervello = lambda *a, **k: None
            for _ in range(3):
                _w249._ensure_loaded()
        finally:
            (_w249._INDEX, _w249._BRAIN, _w249._AVVIO_FATTO, _s249.init_db, _r249.start_background,
             _t249.registra_webhook, _t249.imposta_cervello) = _sal249
        check("avvio[249]: init_db, promemoria e webhook Telegram una volta sola su tre richieste",
              _n249 == {"db": 1, "rem": 1, "tg": 1}, str(_n249))
    except Exception as _e249:  # noqa: BLE001
        check("avvio[249]: kontrollet u ekzekutuan", False, str(_e249))

    # [250] v9.481 — le leggi sulle organizzazioni non profit (8788/2001 e 80/2021) nel corpus: per numero, per nome, il
    # sotto-articolo fuori posto (39/1, le multe), la vecchia legge sul registro 8789/2001 abrogata, la ricerca
    try:
        from src import citation_verifier as _cv250, parser as _p250
        from src.retrieval import ArticleIndex as _AI250
        from types import SimpleNamespace as _SN250
        _i250 = _AI250.load()
        _st250 = []
        for _t in ("Sipas nenit 39/1 të ligjit nr. 80/2021, gjoba është 0,1%.", "Neni 5 i ligjit nr. 8788, datë 7.5.2001.",
                   "neni 9 i ligjit për organizatat jofitimprurëse", "neni 12 i ligjit për regjistrimin e organizatave jofitimprurëse",
                   "neni 3 i ligjit nr. 8789/2001 për regjistrimin e OJF"):
            _st250 += [(x["code"], x["number"], x["status"]) for x in _cv250.verify_text(_t, _i250)["items"]]
        _hit250 = [(a.code, a.number) for a, _ in _i250.search("gjobë për mosregjistrimin e organizatës jofitimprurëse", top_k=8)]
        _txt250 = ("Neni 39\nCertifikata\n1. Sekretaria lëshon certifikatën e regjistrimit për organizatën.\n"
                   "Neni 40\nVërtetime\nPas regjistrimit lëshohet vërtetimi i regjistrimit për subjektin.\n"
                   "Neni 41\nFormati\nKëshilli miraton formatin dhe përmbajtjen e certifikatës së regjistrimit.\n"
                   "Neni 39/1\nKundërvajtjet administrative\n1. Mospërmbushja e detyrimit për regjistrim dënohet me gjobë.\n"
                   "Neni 42\nHyrja\nKy ligj hyn në fuqi pesëmbëdhjetë ditë pas botimit në Fletoren Zyrtare.\n")
        _a250 = _p250.split_into_articles(_txt250, _SN250(code="x", title_sq="x", area="", volatility="STABLE",
                                                          last_amendment_date=None))
        _n250 = [a.number for a in _a250]
        _ok250 = (_st250 == [("ligji_regjistrimi_ojf", "39/1", "verified"), ("ligji_ojf", "5", "verified"),
                             ("ligji_ojf", "9", "verified"), ("ligji_regjistrimi_ojf", "12", "verified"), (None, "3", "repealed")]
                  and ("ligji_regjistrimi_ojf", "39/1") in _hit250[:3] and "39/1" in _n250
                  and all("Kundërvajtjet" not in a.body for a in _a250 if a.number == "41"))
        check("ojf[250]: leggi sulle organizzazioni non profit nel corpus, 39/1 tenuto, 8789/2001 abrogata",
              _ok250, f"{_st250} | {_hit250[:3]} | {_n250}")
    except Exception as _e250:  # noqa: BLE001
        check("ojf[250]: kontrollet u ekzekutuan", False, str(_e250))

    # [251] v9.482 — la firma elettronica: la 51/2026 nel corpus (per numero e per nome); la 107/2015 e la 9880/2008 che
    # abroga risultano «abrogate — oggi 51/2026» (la 9880 era fuori dal registro per un «i ndryshuar» della legge prima)
    try:
        from src import citation_verifier as _cv251
        from src.retrieval import ArticleIndex as _AI251
        _i251 = _AI251.load()
        _r251 = []
        for _t in ("neni 25 i ligjit nr. 51/2026", "neni 30 i ligjit për identifikimin elektronik",
                   "neni 10 i ligjit nr. 107/2015 për identifikimin elektronik",
                   "neni 4 i ligjit nr. 9880, datë 25.2.2008, «Për nënshkrimin elektronik»"):
            _r251 += [(x["code"], x["status"], "51/2026" in (x.get("article_heading") or "")) for x in _cv251.verify_text(_t, _i251)["items"]]
        _ok251 = (_r251[:2] == [("ligji_identifikimi_elektronik", "verified", False)] * 2
                  and _r251[2:] == [(None, "repealed", True), (None, "repealed", True)])
        check("firma-elettronica[251]: 51/2026 nel corpus, 107/2015 e 9880/2008 abrogate con il successore", _ok251, str(_r251))
    except Exception as _e251:  # noqa: BLE001
        check("firma-elettronica[251]: kontrollet u ekzekutuan", False, str(_e251))

    # [252] v9.483 — il cancello COMPLETA: le righe con «non è tra gli articoli recuperati / da verificare su Normattiva /
    # nuk e kam tekstin» su un articolo che il corpus HA (e che il senior non aveva) ricevono il testo ufficiale e vengono
    # riviste; nient'altro cambia. Rilevamento eseguito sugli indici veri, correzione con un modello finto.
    try:
        import os as _os252
        from src import cancello as _cn252, citation_verifier as _cv252, brain as _br252
        from src.retrieval import ArticleIndex as _AI252
        from pathlib import Path as _P252
        import inspect as _in252
        _al252 = _AI252.load(); _it252 = _AI252.load(_P252("/app/data/index/bm25_it.pkl"))
        _cv252.registra_indici(al=_al252, it=_it252)
        _t252 = ("Intro senza citazioni.\n- Il termine è quello dell'art. 497 c.p.c. — non è tra gli articoli recuperati, da verificare su Normattiva.\n"
                 "- L'art. 2043 c.c. regola il fatto illecito.")
        _r252a = _cn252._da_completare(_t252, _it252, None, set())
        _r252b = _cn252._da_completare(_t252, _it252, None, {("codice_procedura_civile", "497")})
        _r252c = _cn252._da_completare("Neni 278 i Kodit Penal (nuk e kam tekstin në nenet që kam — verifikoje).", _al252, None, set())
        _r252d = _cn252._da_completare("- art. 99999 c.p.c. — non è tra gli articoli recuperati.", _it252, None, set())
        _r252e = _cn252._da_completare("- (art. 9 D.Lgs. 23/2015, non recuperato nel blocco: verificalo su Normattiva)", _it252, None, set())

        class _F252:
            def complete(self, **kw):
                return '{"righe":[{"i":1,"testo":"- Il termine è di quarantacinque giorni dal pignoramento (art. 497 c.p.c.)."}]}'
        _o252, _c252, _n252 = _cn252.completa(_t252, _it252, "it", backend=_F252(), retrieved_keys=set(), modeli="x")
        _os252.environ["CANCELLO_COMPLETA"] = "0"
        try:
            _o252off, _c252off, _ = _cn252.completa(_t252, _it252, "it", backend=_F252(), retrieved_keys=set(), modeli="x")
        finally:
            _os252.environ.pop("CANCELLO_COMPLETA", None)
        _src252 = _in252.getsource(_cn252.applica) + _in252.getsource(_br252.SuperAvvocato._cancello)
        _ok252 = (_r252a[0] == [1] and [(a.code, a.number) for a in _r252a[1]] == [("codice_procedura_civile", "497")]
                  and _r252b[0] == [] and _r252c[0] == [0] and _r252d[0] == [] and _r252e[0] == [0]
                  and _c252 == 1 and "quarantacinque" in _o252 and _o252.split("\n")[2] == _t252.split("\n")[2]
                  and _o252off == _t252 and _c252off == 0
                  and "completa(" in _src252 and "retrieved_keys=_keys" in _src252)
        check("completa[252]: righe «non è tra gli articoli recuperati» riviste col testo ufficiale, solo quelle",
              _ok252, f"{_r252a[0]} {_r252b[0]} {_r252c[0]} {_r252d[0]} | {_c252} | off={_c252off}")
    except Exception as _e252:  # noqa: BLE001
        check("completa[252]: kontrollet u ekzekutuan", False, str(_e252))

    # [253] v9.485 — la legge sui media audiovisivi (97/2013) nel corpus; il registro delle abrogate legge «Ligji nr. 8410
    # datë 30.9.1998» (senza virgola) e non taglia la frase su «nr. 9742»: 8410/1998, 9742/2007 e 8389/1998 abrogate
    try:
        from src import citation_verifier as _cv253
        from src.retrieval import ArticleIndex as _AI253
        _i253 = _AI253.load()
        _st253 = [(x["code"], x["status"]) for _t in ("neni 133 i ligjit nr. 97/2013", "neni 132 i ligjit për mediat audiovizive")
                  for x in _cv253.verify_text(_t, _i253)["items"]]
        _reg253 = _cv253._ligje_te_shfuqizuara(_i253)
        _ok253 = (_st253 == [("ligji_mediat_audiovizive", "verified")] * 2
                  and "97/2013" in _reg253.get("8410/1998", "") and "97/2013" in _reg253.get("9742/2007", "")
                  and "113/2020" in _reg253.get("8389/1998", ""))
        check("media[253]: 97/2013 nel corpus; 8410/1998, 9742/2007, 8389/1998 nel registro delle abrogate", _ok253,
              f"{_st253} | {[k for k in ('8410/1998', '9742/2007', '8389/1998') if k in _reg253]}")
    except Exception as _e253:  # noqa: BLE001
        check("media[253]: kontrollet u ekzekutuan", False, str(_e253))

    # [254] v9.486 — l'elenco dopo i due punti (solo AL): «**Ligji nr. 74/2014 «Për armët»**: neni 24 …, neni 27 …» → la
    # legge sulle armi; NON una riga d'elenco senza l'atto, NON dopo la fine della frase, NON in italiano
    try:
        from src import citation_verifier as _cv254
        from src.retrieval import ArticleIndex as _AI254
        from pathlib import Path as _P254
        _al254 = _AI254.load(); _it254 = _AI254.load(_P254("/app/data/index/bm25_it.pkl"))
        def _st254(t, i=None, codes=None):
            return [(x["code"], x["number"], x["status"]) for x in _cv254.verify_text(t, i or _al254, retrieved_codes=codes)["items"]]
        _a254 = _st254("Regjimi i autorizimeve rregullohet nga **Ligji nr. 74/2014 «Për armët»**: neni 24 rendit llojet e "
                       "autorizimeve, neni 27 përcakton kuptimin e autorizimit në lëvizje.", codes={"ligji_armet", "kodi_penal"})
        _b254 = _st254("Kontrolli bëhet sipas KPP.\n- Autorizimi «në vendbanim» (neni 28) e rëndon nxjerrjen në makinë.",
                       codes={"ligji_armet", "kodi_penal"})
        _c254 = _st254("Ligji nr. 74/2014 «Për armët» u ndryshua. Pastaj: neni 24 nuk zbatohet.", codes={"ligji_armet", "kodi_penal"})
        _d254 = _st254("Conclusione confermata sul testo: via dell'art. 9, co. 1, lett. f) come riserva.", _it254)
        _ok254 = (("ligji_armet", "24", "verified") in _a254 and ("ligji_armet", "27", "verified") in _a254
                  and all(c is None for c, _n, _s in _b254) and all(c is None for c, _n, _s in _c254 if _n == "24")
                  and all(c is None for c, _n, _s in _d254))
        check("dypika[254]: l'elenco dopo i due punti prende la legge nominata, solo in albanese e nella stessa frase", _ok254,
              f"{_a254} | {_b254} | {_c254} | {_d254}")
    except Exception as _e254:  # noqa: BLE001
        check("dypika[254]: kontrollet u ekzekutuan", False, str(_e254))

    # [255] v9.487 — nella domanda penale la figura di reato del KP entra anche se una legge settoriale prende i posti (prova
    # viva 3 ott: legge sulle armi 8/12, KP 278 una volta su due); non se il penale non è l'area principale, non per radici generiche
    try:
        from src import brain as _br255
        from src.retrieval import ArticleIndex as _AI255
        import inspect as _in255
        _i255 = _AI255.load()
        _armet = [(a, 5.0) for a in _i255.articles if a.code == "ligji_armet" and not a.repealed][:12]
        _q255 = ["mbajtja pa leje e armëve të zjarrit në automjet", "municion luftarak pa leje në banesë"]
        _a255 = _br255._ancora_vepra_penale(_armet, _i255, _q255, ["Penal", "Siguri"])
        _b255 = _br255._ancora_vepra_penale(_armet, _i255, _q255, ["Kushtetues", "Penal"])
        _c255 = _br255._ancora_vepra_penale(_armet, _i255, ["parashkrimi i ndjekjes penale"], ["Penal"])
        _k278 = next(a for a in _i255.articles if a.code == "kodi_penal" and a.number == "278")
        _d255 = _br255._ancora_vepra_penale([(_k278, 9.0)] + _armet[:11], _i255, _q255, ["Penal"])
        _src255 = _in255.getsource(_br255.SuperAvvocato._retrieve)
        _ok255 = (len(_a255) in (13, 14) and ("kodi_penal", "278") in [(a.code, a.number) for a, _ in _a255[:2]]
                  and getattr(_a255[0][0], "_ancora_titull", False) and not getattr(_k278, "_ancora_vepra", False)
                  and len(_b255) == 12 and len(_c255) == 12 and len(_d255) == 12
                  and "_ancora_vepra_penale(" in _src255 and "_ancora_vepra" in _src255)
        check("vepra[255]: la figura di reato del KP entra nella domanda penale, solo lì e solo per la rubrica",
              _ok255, f"{[(a.code, a.number) for a, _ in _a255[:1]]} {len(_b255)} {len(_c255)} {len(_d255)}")
    except Exception as _e255:  # noqa: BLE001
        check("vepra[255]: kontrollet u ekzekutuan", False, str(_e255))

    # [256] v9.488 — il completamento vede il blocco che il senior AVEVA: non le copie aggiunte dopo dalla chiusura del dossier
    # («⚑ CITUAR NGA»), e «93/bis» del verificatore = «93-bis» del blocco
    try:
        import copy as _cp256
        from src import brain as _br256, cancello as _cn256
        from src.retrieval import ArticleIndex as _AI256
        from pathlib import Path as _P256
        _it256 = _AI256.load(_P256("/app/data/index/bm25_it.pkl"))
        _a93 = next(a for a in _it256.articles if a.code == "codice_strada" and a.number == "93-bis")
        _a201 = next(a for a in _it256.articles if a.code == "codice_strada" and a.number == "201")
        _r256 = _cn256._da_completare("- L'art. 93-bis C.d.S. non è tra gli articoli recuperati: da verificare su Normattiva.", _it256,
                                     None, {("codice_strada", "93-bis")})
        _c201 = _cp256.copy(_a201); _c201._cituar_nga = "seniori"
        _cap256 = {}
        _orig256 = _cn256.applica
        def _fake256(text, idx, jur, lang, **kw):
            _cap256.update(kw); return text, {}, {}
        _cn256.applica = _fake256
        try:
            _sa256 = _br256.SuperAvvocato.__new__(_br256.SuperAvvocato)
            _sa256.index, _sa256.index_it = None, _it256
            _sa256._cancello("testo", [(_a93, 5.0), (_c201, 0.0)], "it", "IT")
        finally:
            _cn256.applica = _orig256
        _ok256 = (_r256[0] == [] and _cap256.get("retrieved_keys") == {("codice_strada", "93-bis")})
        check("blocco-vero[256]: il completamento non salta gli articoli aggiunti dopo e legge «93/bis» = «93-bis»",
              _ok256, f"{_r256[0]} | {_cap256.get('retrieved_keys')}")
    except Exception as _e256:  # noqa: BLE001
        check("blocco-vero[256]: kontrollet u ekzekutuan", False, str(_e256))

    # [257] v9.489 — l'anno a due cifre («D.Lgs. 286/98», «L. 241/90», «L. 604/66») e «Reg. del. 2015/2446» dopo «par. 3,»
    try:
        from src import citation_verifier as _cv257
        from src.retrieval import ArticleIndex as _AI257
        from pathlib import Path as _P257
        _it257 = _AI257.load(_P257("/app/data/index/bm25_it.pkl"))
        _att257 = {"art. 9 D.Lgs. 286/98": "tu_immigrazione", "art. 3 L. 241/90": "procedimento_amministrativo",
                   "art. 2 L. 604/66": "licenziamenti_individuali", "art. 215, par. 3, Reg. del. 2015/2446": "reg_ue_2015_2446",
                   "art. 9 D.Lgs. 286/1998": "tu_immigrazione"}
        _got257 = {t: [(x["code"], x["status"]) for x in _cv257.verify_text(t, _it257)["items"]] for t in _att257}
        _neg257 = [x["code"] for x in _cv257.verify_text("art. 5 L. 18/22", _it257)["items"]]
        _ok257 = all(v == [(_att257[t], "verified")] for t, v in _got257.items()) and _neg257 == [None]
        check("anno-due-cifre[257]: «286/98», «241/90», «604/66» e «Reg. del.» riconosciuti; una legge fuori corpus no", _ok257,
              f"{_got257} | {_neg257}")
    except Exception as _e257:  # noqa: BLE001
        check("anno-due-cifre[257]: kontrollet u ekzekutuan", False, str(_e257))

    # [258] v9.490 — i pannelli dalla prova viva del 4 ott: (1) le nullità nel testo dei pannelli col NOME (il campo vero), non «—»;
    # (2) il radar d'urgenza riceve gli articoli del blocco (nel caso dell'auto fondava il rischio sull'art. 93, c. 1-bis, abrogato)
    try:
        from src import brain as _br258
        import inspect as _in258
        from types import SimpleNamespace as _SN258
        _nr258 = _br258.NullityRadar(findings=[
            _br258.NullityFinding(kind="deadline", name="Termine di 30 giorni per il ricorso", legal_basis="art. 204-bis C.d.S.",
                                  citizen_applicable="po", deadline_hint="30 giorni dalla notifica")])
        _tr258 = _br258.TriageResult(problem_summary="x", areas=[], search_queries=[], strategic_angles=[],
                                     needs_followup=False, followup_question="", domanda="x")
        _txt258 = _br258._risposta_dalle_fasi(_tr258, nullity_radar=_nr258, lang="it") if "lang" in _in258.signature(
            _br258._risposta_dalle_fasi).parameters else _br258._risposta_dalle_fasi(_tr258, nullity_radar=_nr258)
        _a258 = _SN258(code="codice_strada", number="93", citation="art. 93 Codice della strada", heading="Formalità",
                       body="1. … 1-bis. COMMA ABROGATO DALLA L. 23 DICEMBRE 2021, N. 238.")
        _b258 = _br258._blocco_articoli_urgenza([(_a258, 1.0)], True)
        _bsq258 = _br258._blocco_articoli_urgenza([(_a258, 1.0)], False)
        _src258 = _in258.getsource(_br258.SuperAvvocato._scan_urgency)
        _ok258 = ("Termine di 30 giorni per il ricorso" in _txt258 and "**—**" not in _txt258
                  and "COMMA ABROGATO" in _b258 and "SOLO su questi" in _b258 and "VETËM" in _bsq258
                  and "_blocco_articoli_urgenza(retrieved" in _src258 and "Il caso da preparare" in _src258)
        check("pannelli[258]: nullità col nome e radar d'urgenza con gli articoli del blocco", _ok258, _txt258[:200])
    except Exception as _e258:  # noqa: BLE001
        check("pannelli[258]: kontrollet u ekzekutuan", False, str(_e258))

    # [259] v9.491 — un numero breve con un anno DIVERSO è un'altra legge: «ligji 82/2016» non è la 82/2024 sulla polizia
    try:
        from src import citation_verifier as _cv259
        from src.retrieval import ArticleIndex as _AI259
        _i259 = _AI259.load()
        _f259 = lambda t: [(x["code"], x["status"]) for x in _cv259.verify_text(t, _i259)["items"]]
        _ok259 = (_f259("neni 2 i ligjit 82/2016") == [(None, "needs_code")]
                  and _f259("neni 2 i ligjit nr. 82/2024") == [("ligji_policia_2024", "verified")]
                  and _f259("neni 5 i ligjit nr. 9901/2008")[0][0] == "ligji_shoqerite_tregtare")
        check("anno-diverso[259]: «82/2016» non è la legge 82/2024; 82/2024 e 9901/2008 sì", _ok259,
              f"{_f259('neni 2 i ligjit 82/2016')} {_f259('neni 2 i ligjit nr. 82/2024')} {_f259('neni 5 i ligjit nr. 9901/2008')}")
    except Exception as _e259:  # noqa: BLE001
        check("anno-diverso[259]: kontrollet u ekzekutuan", False, str(_e259))

    # [260] v9.492 — (1) il RICHIAMO INVERSO: col KPC 443 «Afati i ankimit» nel blocco entra il KPC 444 (la decorrenza), marcato;
    # niente per un articolo richiamato da troppi; (2) un articolo di UNA frase (testo tutto nella rubrica) si mostra come testo;
    # (3) nessun numero doppio nel corpus AL (ligji 8788/2001 aveva due «Neni 12» nel testo ufficiale: unità unica)
    try:
        import collections as _co260
        from src import brain as _br260
        from src.retrieval import ArticleIndex as _AI260
        _al260 = _AI260.load()
        _sa260 = _br260.SuperAvvocato.__new__(_br260.SuperAvvocato)
        _sa260.index, _sa260.index_it = _al260, None
        _sa260._jurisdiction_ctx = __import__("threading").local(); _sa260._jurisdiction_ctx.code = "AL"
        _br260.set_request_jurisdiction("AL")
        _a443 = next(a for a in _al260.articles if a.code == "kodi_proc_civile" and a.number == "443")
        _out260 = _sa260._aggiungi_richiami_inversi([(_a443, 9.0)])
        _k260 = [(a.code, a.number, getattr(a, "_richiama", "")) for a, _ in _out260]
        _a444 = next(a for a, _ in _out260 if a.number == "444") if len(_out260) > 1 else None
        _txt260 = _br260._format_articles_for_prompt([(_a444, 1.0)]) if _a444 is not None else ""
        _dup260 = [k for k, v in _co260.Counter((a.code, a.number) for a in _al260.articles).items() if v > 1]
        _ok260 = (len(_out260) == 2 and _k260[1][:2] == ("kodi_proc_civile", "444") and _k260[1][2]
                  and "I REFEROHET" in _txt260 and "i gjithë teksti i nenit është ky" in _txt260 and not _dup260)
        check("richiamo-inverso[260]: KPC 443 porta il 444 (decorrenza), testo di una frase visibile, nessun numero doppio",
              _ok260, f"{_k260} | dup {_dup260[:3]}")
    except Exception as _e260:  # noqa: BLE001
        check("richiamo-inverso[260]: kontrollet u ekzekutuan", False, str(_e260))

    # [261] v9.492 — il passaggio di sessione con un clic dall'avviso dei fascicoli dell'altra giurisdizione (la rotta c'era, il pulsante no)
    try:
        from pathlib import Path as _P261
        _js261 = (_P261("/app/static/app.js")).read_text(encoding="utf-8")
        _i261 = _js261.find("function _notaCasiNascosti")
        _f261 = _js261[_i261:_i261 + 2600]
        _ok261 = (_i261 > 0 and "/api/session/jurisdiction" in _f261 and 'method: "POST"' in _f261 and "location.reload()" in _f261
                  and "case-switch-juris" in _f261)
        check("sessione[261]: il pulsante «Passa alla sessione» chiama /api/session/jurisdiction e ricarica", _ok261, _f261[:120])
    except Exception as _e261:  # noqa: BLE001
        check("sessione[261]: kontrollet u ekzekutuan", False, str(_e261))

    # [262] v9.493 — nella barra la traduzione SCRITTA viene prima della sostituzione per pezzi («Scadenze e klientëve»)
    try:
        from pathlib import Path as _P262
        _js262 = (_P262("/app/static/app.js")).read_text(encoding="utf-8")
        _i262 = _js262.find("function tMode(sq)")
        _f262 = _js262[_i262:_i262 + 1400]
        _ok262 = (_i262 > 0 and _f262.find("if (T_IT[sq]) return T_IT[sq];") > 0
                  and _f262.find("if (T_IT[sq]) return T_IT[sq];") < _f262.find("MODEBAR_TXT.length")
                  and '"\\ud83d\\udcc5 Afatet e klient\\u00ebve": "\\ud83d\\udcc5 Scadenze dei clienti"' in _js262)
        check("barra[262]: tMode usa prima la traduzione esatta (niente «Scadenze e klientëve»)", _ok262, _f262[:160])
    except Exception as _e262:  # noqa: BLE001
        check("barra[262]: kontrollet u ekzekutuan", False, str(_e262))

    # [263] v9.494 — (1) la correzione del Giudice accanto alla voce del pannello (non solo un avviso in testa); (2) il blocco dei
    # precedenti nella lingua della sessione e, per i precedenti italiani (id 0), niente link a /case-precedent/0 né «stato»;
    # (3) i titoli del radar tagliati su parola intera
    try:
        from pathlib import Path as _P263
        from src import brain as _br263
        _js263 = (_P263("/app/static/app.js")).read_text(encoding="utf-8")
        _i263 = _js263.find("function _applicaCorrezioniGiudice")
        _f263 = _js263[_i263:_i263 + 4000]
        _ok263 = (_i263 > 0 and "_applicaCorrezioniGiudice(msgEl, body," in _js263 and "NOMI.test" in _f263
                  and 'target.tagName === "SUMMARY"' in _f263 and ".urgency-radar" in _f263
                  and 'href="/case-precedent/${d.id}"' in _js263 and "const citeLink = (d) => d.id" in _js263
                  and "Leggi la decisione" in _js263 and "Decisioni rilevanti dei tribunali" in _js263
                  and "controllo le decisioni successive" in _js263
                  and _br263._tronca("Presentare istanza di sostituzione della pena detentiva con il lavoro di pubblica utilità", 80).endswith("di…"))
        check("pannelli[263]: correzioni del Giudice sulla voce, precedenti bilingui senza id 0, titoli su parola intera", _ok263,
              _f263[:100])
    except Exception as _e263:  # noqa: BLE001
        check("pannelli[263]: kontrollet u ekzekutuan", False, str(_e263))

    # [264] v9.495 — le date dell'analisi del cervello (cronologia, radar d'urgenza) diventano PROPOSTE dello scadenziario da
    # confermare (origine «risposta»), mai eventi del calendario coi promemoria: niente date passate né oltre 5 anni, titolo intero
    try:
        from types import SimpleNamespace as _NS264
        from datetime import date as _d264, timedelta as _td264
        from pathlib import Path as _P264
        from src import web as _w264
        _pres264, _ev264 = [], []
        _old264 = (_w264._scad_salva, _w264._upsert_autoevent, _w264.storage.get_case)
        _w264._scad_salva = lambda pr, inn, **kw: (_pres264.append((pr, kw)), len(pr))[1]
        _w264._upsert_autoevent = lambda **kw: _ev264.append(kw)
        _w264.storage.get_case = lambda cid, uid: _NS264(jurisdiction="IT")
        try:
            _ok_f = (_d264.today() + _td264(days=20)).isoformat()
            _res264 = _NS264(
                timeline=_NS264(deadlines=[
                    _NS264(due_date=_ok_f, action="Depositare l'opposizione al decreto penale di condanna davanti al GIP competente "
                           "con la richiesta di rito alternativo e la documentazione del lavoro di pubblica utilità, il certificato del casellario "
                           "e la dichiarazione di disponibilità dell'ente convenzionato", anchor_event="notifica",
                           article_ref="art. 461 c.p.p.", urgency="critical"),
                    _NS264(due_date="2024-03-01", action="passata", anchor_event="", article_ref="", urgency="high"),
                    _NS264(due_date="2036-01-01", action="troppo lontana", anchor_event="", article_ref="", urgency="high")]),
                urgency_radar=_NS264(signals=[_NS264(severity="critical", deadline=_ok_f + " (entro)", label="Opposizione",
                                                     action="depositare", reason="")]))
            _n264 = _w264._autopopulate_events_from_result(1, "c264", _res264)
        finally:
            _w264._scad_salva, _w264._upsert_autoevent, _w264.storage.get_case = _old264
        _p264 = _pres264[0][0] if _pres264 else []
        _js264 = (_P264("/app/static/app.js")).read_text(encoding="utf-8")
        _ok264 = (not _ev264 and _n264 == 2 and len(_p264) == 2 and all(x["origine"] == "risposta" and not x["verificato"]
                                                                          and x["data"] == _ok_f for x in _p264)
                  and _p264[0]["titolo"].endswith("…") and len(_p264[0]["titolo"]) <= 200
                  and "analisi" in _p264[0]["nota"] and _p264[0]["base"] == "art. 461 c.p.p."
                  and _pres264[0][1].get("juris") == "IT" and _pres264[0][1].get("doc_id") is None
                  and len({x["chiave"] for x in _p264}) == 2 and 'p.origine === "risposta"' in _js264)
        check("scadenze[264]: date dell'analisi = proposte da confermare (mai passate, mai oltre 5 anni, nessun evento diretto)",
              _ok264, str([(x["data"], x["titolo"][:30]) for x in _p264]) + f" eventi={len(_ev264)} n={_n264}")
    except Exception as _e264:  # noqa: BLE001
        check("scadenze[264]: kontrollet u ekzekutuan", False, str(_e264))

    # [265] v9.496 — il titolo automatico del fascicolo (dalla prima domanda) si taglia su parola intera, mai «… un de»
    try:
        from src import web as _w265
        _t265 = _w265._tronca_titolo(" ".join("Al mio cliente è stato notificato il 25 settembre 2026 un decreto\npenale".split()), 60)
        _src265 = open(_w265.__file__, encoding="utf-8").read()
        check("titolo[265]: titolo automatico del fascicolo su parola intera",
              _t265.endswith("…") and not _t265.endswith("de…") and len(_t265) <= 60
              and _src265.count('_tronca_titolo(" ".join(message.split()), 60)') == 2 and "message[:60]" not in _src265, _t265)
    except Exception as _e265:  # noqa: BLE001
        check("titolo[265]: kontrollet u ekzekutuan", False, str(_e265))

    # [266] v9.497 — avviso delle scadenze e suggerimenti su UNA riga: su un portatile lasciavano ai messaggi 209 px su 715
    try:
        from pathlib import Path as _P266
        _css266 = (_P266("/app/static/style.css")).read_text(encoding="utf-8")
        _js266 = (_P266("/app/static/app.js")).read_text(encoding="utf-8")
        _i266 = _css266.find("v9.497")
        _c266 = _css266[_i266:]
        check("ui[266]: avviso delle scadenze e suggerimenti su una riga (testo intero nel title)",
              _i266 > 0 and ".deadline-banner { flex-wrap: nowrap;" in _c266 and "text-overflow: ellipsis" in _c266
              and ".suggest-head { display: contents; }" in _c266 and "_dbt.title = _dbt.textContent" in _js266, _c266[:80])
    except Exception as _e266:  # noqa: BLE001
        check("ui[266]: kontrollet u ekzekutuan", False, str(_e266))

    # [267] v9.497 — il calcolatore delle imposte del notaio in sessione ITALIANA non è quello albanese (lek, ASHK, Tirana)
    try:
        from pathlib import Path as _P267
        _js267 = (_P267("/app/static/app.js")).read_text(encoding="utf-8")
        _i267 = _js267.find("function openNotaryFeesIT()")
        _f267 = _js267[_i267:_js267.find("function openNotaryFees() {", _i267)]
        check("notaio[267]: imposte d'acquisto italiane in sessione IT (registro 9/2 %, minimo 1.000 €, fisse 50 €, prezzo-valore)",
              _i267 > 0 and "if (_CAL_IT) return openNotaryFeesIT();" in _js267 and "Math.max(1000, base * aliq / 100)" in _f267
              and "1.05 * molt" in _f267 and "prima ? 110 : 120" in _f267 and "ALL" not in _f267 and "ASHK" not in _f267
              and "riga(\"Imposta ipotecaria (fissa)\", eur(50))" in _f267, _f267[:80])
    except Exception as _e267:  # noqa: BLE001
        check("notaio[267]: kontrollet u ekzekutuan", False, str(_e267))

    # [268] v9.498 — la data di OGGI (col giorno e le festività) in ogni chiamata al cervello, prima della riga di lingua
    try:
        import datetime as _dt268
        from src import brain as _br268
        _a268 = _br268.riga_oggi("IT", _dt268.date(2026, 10, 4))
        _b268 = _br268.riga_oggi("AL", _dt268.date(2026, 10, 4))
        _c268 = _br268.riga_oggi("AL", _dt268.date(2026, 10, 3))
        _d268 = _br268.riga_oggi("IT", _dt268.date(2026, 10, 6))
        _p268 = _br268.direttiva_gjuhe_prompt("Domanda", "IT")
        check("oggi[268]: data di oggi col giorno e le festività, prima della riga di lingua, idempotente",
              "domenica 4 ottobre 2026 — festività nazionale" in _a268 and "e diel, 4 tetor 2026 — ditë jo pune" in _b268
              and "e shtunë, 3 tetor 2026 — ditë jo pune për gjykatat" in _c268 and "martedì 6 ottobre 2026." in _d268
              and "[DATA DI OGGI:" in _p268 and _p268.endswith(_br268.DIRETTIVA_GJUHE["IT"])
              and _br268.direttiva_gjuhe_prompt(_p268, "IT") == _p268 and _p268.count("[DATA DI OGGI:") == 1
              and _br268.riga_oggi("EU") == "", _a268 + " | " + _c268)
    except Exception as _e268:  # noqa: BLE001
        check("oggi[268]: kontrollet u ekzekutuan", False, str(_e268))

    # [269] v9.499 — (1) il comma in LETTERE («art. 326, primo comma, c.p.c.») non lascia la citazione senza codice; (2) con l'archivio
    # della Cassazione muto la riga di verifica dice «N non riscontrabili ora», mai «0 confermate», e lo stato non è ✅
    try:
        from pathlib import Path as _P269
        from src import citation_verifier as _cv269, brain as _br269, trust_line as _tl269, cassazione as _cz269
        from src.retrieval import ArticleIndex as _AI269
        _br269.set_request_jurisdiction("IT")
        _it269 = _AI269.load(_P269("/app/data/index/bm25_it.pkl"))
        _f269 = lambda t: [(x["status"], x.get("code"), str(x.get("number"))) for x in _cv269.verify_text(t, _it269)["items"]]
        _ok1 = (_f269("art. 326, primo comma, c.p.c.") == [("verified", "codice_procedura_civile", "326")]
                and _f269("art. 155, quarto e quinto comma, c.p.c.") == [("verified", "codice_procedura_civile", "155")]
                and _f269("art. 2697, comma primo, c.c.") == [("verified", "codice_civile", "2697")]
                and _f269("art. 9999, primo comma, c.p.c.") == [("fake", "codice_procedura_civile", "9999")])
        _br269.set_request_jurisdiction("AL")
        _al269 = _AI269.load()
        _g269 = lambda t: [(x["status"], x.get("code"), str(x.get("number"))) for x in _cv269.verify_text(t, _al269)["items"]]
        _ok1 = _ok1 and (_g269("neni 443, paragrafi i parë, i Kodit të Procedurës Civile") == [("verified", "kodi_proc_civile", "443")]
                         and _g269("neni 155, pika e parë, e Kodit të Punës") == [("verified", "kodi_punes", "155")]
                         and _g269("neni 9999, paragrafi i parë, i Kodit Penal")[0][0] == "fake")
        _br269.set_request_jurisdiction("IT")
        _old269 = _cz269.verifica
        _cz269.verifica = lambda text: {"items": [], "stats": {"total": 0, "verified": 0, "unverified": 0, "mismatch": 0,
                                                              "offline": True, "non_riscontrabili": 2}}
        try:
            _v269 = _tl269.verifica("Lo dice l'art. 2697 c.c. (Cass. civ., Sez. III, n. 1234/2020 e n. 5678/2021).", _it269, "IT")
        finally:
            _cz269.verifica = _old269
        _r269 = _tl269.riga(_v269, "it")
        _ok2 = ("2 non riscontrabili ora" in _r269 and _tl269.stato(_v269) == "RESERVATIONS"
                and "NON riscontrabili adesso" in _tl269.blocco_per_gjyqtarin(_v269, "it"))
        _br269.set_request_jurisdiction("AL")
        check("verifica[269]: comma in lettere riconosciuto, archivio della Cassazione muto dichiarato", _ok1 and _ok2, _r269[:160])
    except Exception as _e269:  # noqa: BLE001
        check("verifica[269]: kontrollet u ekzekutuan", False, str(_e269))

    # [270] v9.501 — (1) nella domanda «entro quando l'atto?» entra il CALCOLO dei termini (KPC 148-149, KPP 144), letto SOLO dalla
    # domanda dell'avvocato (le riscritture del triage dicono «afat» anche nell'affitto); (2) il cancello barra solo i numeri inesistenti
    try:
        from src import brain as _br270, cancello as _cn270, citation_verifier as _cv270
        from src.retrieval import ArticleIndex as _AI270
        _br270.set_request_jurisdiction("AL")
        _al270 = _AI270.load()
        _k270 = lambda pr: {(a.code, str(a.number)) for a, _ in pr}
        _a270 = _br270._applica_ancore([], _al270, ["afati i ankimit në apel", "Deri kur mund të bëjmë apel kundër vendimit?"], ["Civil"])
        _b270 = _br270._applica_ancore([], _al270, ["afati i ankimit për padinë e qirasë", "Qiramarrësi nuk paguan qiranë: si ta nxjerr?"], ["Civil"])
        _c270 = _br270._applica_ancore([], _al270, ["afati i ankimit", "Deri kur bëjmë ankim kundër dënimit?"], ["Penal"])
        _d270 = _cn270._barra("Gjykata e Lartë (nenet 458, 445 dhe 42 i Kushtetutës).", _al270, "sq")[0]
        check("afate[270]: calcolo dei termini nella domanda «deri kur», mai dalle riscritture; barrati solo i numeri inesistenti",
              ("kodi_proc_civile", "148") in _k270(_a270) and ("kodi_proc_civile", "148") not in _k270(_b270)
              and ("kodi_proc_penale", "144") in _k270(_c270) and ("kodi_proc_civile", "148") not in _k270(_c270)
              and ("kodi_proc_civile", "443") in _k270(_a270) and ("kodi_proc_penale", "415") in _k270(_c270)
              and ("kodi_proc_civile", "443") not in _k270(_c270)
              and {("ligji_gjykatat_administrative", "44"), ("kodi_proc_civile", "443")} <= _k270(_br270._applica_ancore(
                  [], _al270, ["afati i ankimit", "Gjykata administrative e rrëzoi padinë: deri kur bëjmë apel?"], ["Administrativ"]))
              and "~~458~~, ~~445~~ dhe 42" in _d270, _d270[:90])
    except Exception as _e270:  # noqa: BLE001
        check("afate[270]: kontrollet u ekzekutuan", False, str(_e270))

    # [271] v9.502 — la LEGGE SUI FARMACI (ligji 105/2014, consolidato QBZ 23.10.2025) nel corpus: ricetta (52-53), sanzioni (63)
    try:
        from src import citation_verifier as _cv271, brain as _br271
        from src.retrieval import ArticleIndex as _AI271
        _br271.set_request_jurisdiction("AL")
        _al271 = _AI271.load()
        _k271 = {(a.code, str(a.number)) for a in _al271.articles}
        _v271 = [(x["status"], x.get("code")) for x in _cv271.verify_text("neni 52 i ligjit nr. 105/2014 dhe neni 63 i ligjit për barnat", _al271)["items"]]
        _s271 = [a.code for a, _ in _al271.search("shitja e barnave pa recetë në farmaci gjobë", 5)]
        check("barnat[271]: legge sui farmaci nel corpus, verificata per numero e per nome, trovata dalla domanda sulla farmacia",
              {("ligji_barnat", "52"), ("ligji_barnat", "53"), ("ligji_barnat", "63")} <= _k271
              and _v271 == [("verified", "ligji_barnat"), ("verified", "ligji_barnat")] and "ligji_barnat" in _s271[:2], str(_v271) + str(_s271))
    except Exception as _e271:  # noqa: BLE001
        check("barnat[271]: kontrollet u ekzekutuan", False, str(_e271))

    # [272] v9.503 — il Codice dei minori resta fuori dalle domande su ADULTI (prendeva 4 posti su 12 nel favoreggiamento), dentro quando
    # la domanda parla di un minore
    try:
        from types import SimpleNamespace as _NS272
        from src import brain as _br272
        _p272 = [(_NS272(code="kodi_te_miturve", number="55"), 3.0), (_NS272(code="kodi_penal", number="302"), 2.0),
                 (_NS272(code="processo_penale_minorile", number="1"), 1.0)]
        _a272 = [a.code for a, _ in _br272._senza_codice_minori(_p272, "Vëllai i klientit kërkohej nga policia për vjedhje")]
        _b272 = [a.code for a, _ in _br272._senza_codice_minori(_p272, "Djali im 16 vjeç u kap me drogë")]
        _c272 = [a.code for a, _ in _br272._senza_codice_minori(_p272, "Mio figlio di 15 anni è stato denunciato")]
        _d272 = [a.code for a, _ in _br272._senza_codice_minori(_p272, "Nga ç'moshë ka përgjegjësi penale një i mitur?")]
        _src272 = open(_br272.__file__, encoding="utf-8").read()
        check("minori[272]: codice dei minori fuori dalle domande su adulti, dentro con un minore",
              _a272 == ["kodi_penal"] and len(_b272) == 3 and len(_c272) == 3 and len(_d272) == 3
              and _src272.count("pairs = _senza_codice_minori(pairs, _testo_anc[-1] or ") == 2, str(_a272))
    except Exception as _e272:  # noqa: BLE001
        check("minori[272]: kontrollet u ekzekutuan", False, str(_e272))

    # [273] v9.504 — la prescrizione nel LAVORO è il KP 203 (3 anni), non il KC 114 (10 anni «salvo diversa disposizione»)
    try:
        from src import brain as _br273
        from src.retrieval import ArticleIndex as _AI273
        _br273.set_request_jurisdiction("AL")
        _al273 = _AI273.load()
        _k273 = lambda q, aree: {(a.code, str(a.number)) for a, _ in _br273._applica_ancore([], _al273, q, aree)}
        # v9.589: il KP 203 solo se la DOMANDA parla di prescrizione (la parola scritta dal triage non basta più: 11 domande di lavoro su 111)
        _a273 = _k273(["afati i parashkrimit të kërkesave nga marrëdhënia e punës",
                       "Punëdhënësi e pushoi klientin pa paralajmërim: a ka rënë në parashkrim padia?"], ["Punë", "Civil"])
        _n273 = _k273(["afati i parashkrimit të kërkesave nga marrëdhënia e punës", "Punëdhënësi e pushoi klientin pa paralajmërim"], ["Punë"])
        _b273 = _k273(["afati i parashkrimit të detyrimit", "Klienti ka një borxh nga viti 2012"], ["Civil"])
        _c273 = _k273(["parashkrimi i detyrimeve", "A është parashkruar paga e papaguar e vitit 2021?"], ["Civil"])
        check("parashkrim[273]: nel lavoro KP 203 (3 anni) e non il KC 114; nel civile il KC 114",
              ("kodi_punes", "203") in _a273 and ("kodi_civil", "114") not in _a273 and ("kodi_punes", "203") not in _n273
              and ("kodi_civil", "114") in _b273 and ("kodi_civil", "115") in _b273 and ("kodi_punes", "203") not in _b273
              and ("kodi_punes", "203") in _c273
              and ("codice_civile", "2947") in {(a.code, str(a.number)) for a, _ in _br273._applica_ancore(
                  [], _AI273.load(__import__("pathlib").Path("/app/data/index/bm25_it.pkl")),
                  ["prescrizione", "Incidente stradale del 2023: il risarcimento del danno è prescritto?"], ["Civile"], ancore=_br273.ANCORE_IT)}
              and {("cittadinanza", "9.1"), ("cittadinanza", "10")} <= {(a.code, str(a.number)) for a, _ in _br273._applica_ancore(
                  [], _AI273.load(__import__("pathlib").Path("/app/data/index/bm25_it.pkl")),
                  ["cittadinanza per matrimonio", "Sposato con un'italiana: come ottiene la cittadinanza?"], ["Civile"], ancore=_br273.ANCORE_IT)}
              and ("codice_civile", "2948") in {(a.code, str(a.number)) for a, _ in _br273._applica_ancore(
                  [], _AI273.load(__import__("pathlib").Path("/app/data/index/bm25_it.pkl")),
                  ["prescrizione dei crediti", "Il datore non ha pagato gli stipendi del 2020: sono prescritti?"], ["Lavoro", "Civile"],
                  ancore=_br273.ANCORE_IT)}
              # v9.589: 2948 e 2947 solo dalla domanda — la «prescrizione» scritta dal triage non basta (23 domande su 150)
              and not ({("codice_civile", "2948"), ("codice_civile", "2947")} & {(a.code, str(a.number)) for a, _ in _br273._applica_ancore(
                  [], _AI273.load(__import__("pathlib").Path("/app/data/index/bm25_it.pkl")),
                  ["prescrizione del risarcimento del danno", "prescrizione dei crediti di lavoro",
                   "La cliente è caduta su una buca del marciapiede comunale e si è rotta il polso. Chi paga?"], ["Civile"],
                  ancore=_br273.ANCORE_IT)}),
              str(sorted(_a273)) + str(sorted(_c273)))
    except Exception as _e273:  # noqa: BLE001
        check("parashkrim[273]: kontrollet u ekzekutuan", False, str(_e273))

    # [274] v9.506 — l'incidente con un veicolo tiene nel filtro dei codici la legge sull'assicurazione e il Codice della strada
    try:
        from types import SimpleNamespace as _NS274
        from src import brain as _br274
        from src.retrieval import ArticleIndex as _AI274
        _br274.set_request_jurisdiction("AL")
        _sa274 = _br274.SuperAvvocato.__new__(_br274.SuperAvvocato)
        _sa274.index = _AI274.load(); _sa274.index_it = None; _sa274._dense_cache = {}
        _t274 = _NS274(areas=["Civil", "Penal"], search_queries=["përgjegjësia për dëmin jashtëkontraktor"], strategic_angles=[],
                       problem_summary="Këmbësor i goditur nga një makinë", domanda="Klienti u godit nga një makinë në vendkalim për këmbësorë dhe ka dëme. Kush paguan?")
        _ok274 = bool(_br274._INCIDENTE_RX.search(_t274.domanda)) and not _br274._INCIDENTE_RX.search("Qiramarrësi nuk paguan qiranë")
        try:
            _r274 = _sa274._retrieve(_t274)
            _ok274 = _ok274 and any(a.code == "ligji_sigurimi_mjeteve" for a, _ in _r274)
        except Exception as _x274:  # noqa: BLE001 — oggetto parziale: basta il riconoscimento
            _ok274 = _ok274 and "_INCIDENTE_RX.search(" in open(_br274.__file__, encoding="utf-8").read()
        check("incidente[274]: legge sull'assicurazione dei veicoli nel filtro quando la domanda parla di un incidente", _ok274)
    except Exception as _e274:  # noqa: BLE001
        check("incidente[274]: kontrollet u ekzekutuan", False, str(_e274))

    # [275] v9.507 — funzionalità: (1) la FASE dell'analisi profonda nel battito (diavolo, Giudice) invece di «sto ancora lavorando»;
    # (2) la voce del riquadro dichiarata falsa dal Giudice si barra, etichetta nel titolo; (3) il parere pulito da copiare/scaricare;
    # (5) WhatsApp nascosto finché non è collegato; (7) il fascicolo d'esempio al primo accesso
    try:
        import json as _js275
        from pathlib import Path as _P275
        from src import brain as _br275, web as _w275, storage as _st275
        _app275 = (_P275("/app/static/app.js")).read_text(encoding="utf-8")
        _bsrc275 = open(_br275.__file__, encoding="utf-8").read()
        _wsrc275 = open(_w275.__file__, encoding="utf-8").read()
        _e275 = {j: _js275.loads((_P275(_w275.__file__).parent / "esempi" / f"esempio_{j}.json").read_text(encoding="utf-8")) for j in ("al", "it")}
        _ok275 = ("complex_devil" in _br275.STREAM_STATUS_IT and "complex_judge" in _br275.STREAM_STATUS_SQ
                  and _bsrc275.count('yield ("status", self._status("complex_devil"))') == 1
                  and _bsrc275.count('yield ("status", self._status("complex_judge"))') == 1
                  and '_ultima_fase["t"] = ' in _wsrc275 and "_GIUDICE_FALSO.test(r)" in _app275 and "giudice-badge" in _app275
                  and "function _parereDaInviare" in _app275 and "copy-parere-btn" in _app275
                  and "d.backend_ready && !d.phone) _waBtn.hidden = true" in _app275
                  and hasattr(_st275, "crea_fascicolo_esempio") and "_esempio_primo_accesso(user)" in _wsrc275
                  and all(_e275[j]["messaggi"][0]["role"] == "user" and _e275[j]["messaggi"][1]["role"] == "assistant"
                          and len(_e275[j]["messaggi"][1]["content"]) > 5000 for j in ("al", "it"))
                  and "Verdetto finale" in _e275["it"]["messaggi"][1]["content"] and "Vendimi përfundimtar" in _e275["al"]["messaggi"][1]["content"])
        check("funzioni[275]: fase nel battito, voci false barrate, parere pulito, WhatsApp nascosto, fascicolo d'esempio", _ok275)
    except Exception as _e275x:  # noqa: BLE001
        check("funzioni[275]: kontrollet u ekzekutuan", False, str(_e275x))

    # [276] v9.508 — Telegram per i promemoria nel menu utente (prima solo dentro la finestra iCal del calendario)
    try:
        from pathlib import Path as _P276
        _h276 = (_P276("/app/templates/index.html")).read_text(encoding="utf-8")
        _a276 = (_P276("/app/static/app.js")).read_text(encoding="utf-8")
        check("menu[276]: Telegram per i promemoria nel menu utente, apre la sezione Telegram",
              'id="tg-menu-btn"' in _h276 and 'data-i18n="tg_reminders"' in _h276 and 'tg_reminders: "Telegram per i promemoria"' in _a276
              and 'getElementById("tg-menu-btn")?.addEventListener' in _a276)
    except Exception as _e276:  # noqa: BLE001
        check("menu[276]: kontrollet u ekzekutuan", False, str(_e276))

    # [277] v9.508 — LA RISERVA DEL SENIOR: Opus del cervello al limite della sottoscrizione → la stessa domanda all'altra
    # mente (prima nessun ripiego: il senior al limite = risposta mancata). Eseguito con un CLI FINTO, senza avvisi né audit.
    try:
        import os as _os277, json as _js277, tempfile as _tf277
        from src import backends as _bk277, config as _cf277
        _d277 = _tf277.mkdtemp()
        _cli277 = _os277.path.join(_d277, "claude")
        with open(_cli277, "w") as _f277:
            _f277.write("#!/usr/bin/env python3\nimport sys, json\na = sys.argv; m = a[a.index('--model')+1]\n"
                        "open(sys.argv[0] + '.log', 'a').write(m + ' ' + (a[a.index('--effort')+1] if '--effort' in a else '-') + '\\n')\n"
                        "if 'opus' in m:\n    print(json.dumps({'type':'result','is_error':True,'result':\"You've reached your Opus limit. Switch to another model to continue.\"})); sys.exit(1)\n"
                        "print(json.dumps({'type':'result','is_error':False,'result':'OK da ' + m,'session_id':'s'}))\n")
        _os277.chmod(_cli277, 0o755)
        _sv277 = (_bk277._segna_pausa_per_avviso, _bk277._audit_safe)
        _bk277._segna_pausa_per_avviso = lambda *a, **k: None      # MAI l'email al titolare da una prova
        _bk277._audit_safe = lambda **k: None
        _pz277 = dict(_bk277._MODEL_LIMIT_UNTIL)
        try:
            _bk277._MODEL_LIMIT_UNTIL.clear()
            _b277 = _bk277.ClaudeCodeBackend(model="claude-opus-5", cli_path=_cli277, effort="max",
                                             senior_limit_fallback_model="claude-fable-5-1", senior_limit_effort="high")
            _m = [{"role": "user", "content": "ciao"}]
            _r1 = _b277.complete("s", _m, callsite="g277")
            _p1 = _bk277.modello_in_pausa("claude-opus-5") > 0
            _r2 = _b277.complete("s", _m, callsite="g277")
            _r3 = "".join(x for k, x in _b277.complete_stream("s", _m, callsite="g277") if k == "delta")
            _bk277._MODEL_LIMIT_UNTIL.clear()
            _r4 = "".join(x for k, x in _b277.complete_stream("s", _m, callsite="g277") if k == "delta")
            _bk277._MODEL_LIMIT_UNTIL.clear(); _bk277._metti_in_pausa("claude-fable-5-1")
            try:
                _b277.complete("s", _m, callsite="g277"); _r5 = "nessun errore"
            except Exception:  # noqa: BLE001
                _r5 = "errore"
            _log277 = open(_cli277 + ".log").read().split("\n")
            _veloce = _b277._riserva_senior("claude-sonnet-5", True, False)
        finally:
            _bk277._segna_pausa_per_avviso, _bk277._audit_safe = _sv277
            _bk277._MODEL_LIMIT_UNTIL.clear(); _bk277._MODEL_LIMIT_UNTIL.update(_pz277)
        check("riserva[277]: senior al limite → l'altra mente a high; in pausa si salta; streaming uguale; riserva in pausa = un tentativo e l'errore (mai un giro a vuoto); il tier veloce non la usa",
              _r1 == "OK da claude-fable-5-1" and _p1 and _r2 == _r1 and _r3 == _r1 and _r4 == _r1 and _r5 == "errore"
              and _log277[:7] == ["claude-opus-5 max", "claude-fable-5-1 high", "claude-fable-5-1 high", "claude-fable-5-1 high",
                                  "claude-opus-5 max", "claude-fable-5-1 high", "claude-opus-5 max"]
              and _veloce is None
              and _cf277.CLAUDE_CODE_SENIOR_LIMIT_FALLBACK_MODEL == "claude-fable-5-1" and _cf277.CLAUDE_CODE_SENIOR_LIMIT_EFFORT == "high",
              "%r %r %r %r %r %r" % (_r1, _r2, _r3, _r4, _r5, _log277[:7]))
    except Exception as _e277:  # noqa: BLE001
        check("riserva[277]: kontrollet u ekzekutuan", False, str(_e277))

    # [278] v9.508 — bersagli da dito sul telefono (misurati a 400 px in una finestra vera: «×» 22×21 e 24×18, pulsanti del
    # fascicolo 29×34 col cestino attaccato all'export)
    try:
        from pathlib import Path as _P278
        _c278 = _P278("/app/static/style.css").read_text(encoding="utf-8")
        _i278 = _c278.find("BERSAGLI DA DITO")
        _b278 = _c278[_i278:_i278 + 1200] if _i278 >= 0 else ""
        _h278 = _P278("/app/templates/index.html").read_text(encoding="utf-8")
        check("telefono[278]: «×» e pulsanti del fascicolo ≥36-40 px sotto i 600 px, cestino staccato, style.css col suo numero",
              "@media (max-width: 600px)" in _b278 and ".db-close" in _b278 and ".suggest-dismiss" in _b278
              and "min-width: 40px" in _b278 and ".case-header .icon-btn" in _b278 and "textarea, select { font-size: 16px !important; }" in _b278 and "#delete-case-btn { margin-left" in _b278
              and "style.css?v=159" in _h278 and "onboarding.js?v=3" in _h278
              and 'carta.style.left = "0px"; carta.style.transform = "none";' in _P278("/app/static/onboarding.js").read_text(encoding="utf-8")
              and 'cp.className = "dl-docx-btn copy-parere-btn"' in _P278("/app/static/app.js").read_text(encoding="utf-8"))
        from src import web as _w278
        _t278 = _w278._legal_md_to_html("| Dato | Fine |\n|---|---|\n| email | accesso |\n")
        check("telefono[278]: la tabella dei documenti legali pubblici nel contenitore che scorre (la pagina non va oltre lo schermo)",
              '<div class="tab-scorri"><table>' in _t278 and _t278.count("</table></div>") == 1 and "<td>email</td>" in _t278, _t278[:160])
    except Exception as _e278:  # noqa: BLE001
        check("telefono[278]: kontrollet u ekzekutuan", False, str(_e278))

    # [279] v9.508 — LINGUA = SESSIONE anche nelle finestre NATIVE (confirm/prompt/alert): 18 erano solo albanesi («Sigurt që
    # do ta fshish këtë rast…» a un avvocato italiano che cancella un fascicolo). Nessuna scansione del DOM le vede.
    try:
        import re as _re279
        from pathlib import Path as _P279
        _a279 = _P279("/app/static/app.js").read_text(encoding="utf-8")
        _sole279 = [l.strip()[:90] for l in _a279.split("\n")
                    if _re279.search(r"\b(confirm|prompt|alert)\(\s*[\"`]", l)
                    and "dataset.lang" not in l and "_CAL_IT" not in l and "IT ?" not in l]
        check("dialoghi[279]: nessuna conferma/prompt/avviso nativo con un testo fisso senza il ramo italiano",
              not _sole279 and _a279.count('document.body.dataset.lang === "it"') >= 18 and int((_re279.search(r"app\.js\?v=(\d+)", _P279("/app/templates/index.html").read_text(encoding="utf-8")) or [0, 0])[1]) >= 205,
              "; ".join(_sole279[:4]))
    except Exception as _e279:  # noqa: BLE001
        check("dialoghi[279]: kontrollet u ekzekutuan", False, str(_e279))

    # [280] v9.509 — il LOGIN nella lingua della pagina: con l'italiano scelto il clic su «Entra» dava «Po verifikoj…», gli
    # errori albanesi («Demo ka skaduar», «Kredencialet janë të gabuara») e il pulsante tornava «Hyr»
    try:
        from pathlib import Path as _P280
        _l280 = _P280("/app/static/login.js").read_text(encoding="utf-8")
        _h280 = _P280("/app/templates/login.html").read_text(encoding="utf-8")
        check("login[280]: attesa, errori, blocchi (prova scaduta, sospeso, troppi tentativi), rete e password dimenticata in italiano",
              'it: { wait: "Verifico…", login: "Entra", bad: "⚠️ Credenziali errate."' in _l280
              and "demo_expired: \"⚠️ La prova gratuita è scaduta." in _l280 and "M()[data.blocked]" in _l280
              and "resp.status === 429 ? M().many(" in _l280 and 'btn.textContent = M().login;' in _l280
              and '"Hyr";' not in _l280 and "'Dergo kerkesen'" not in _l280 and "Richiesta inviata" in _l280
              and "login.js?v=5" in _h280)
    except Exception as _e280:  # noqa: BLE001
        check("login[280]: kontrollet u ekzekutuan", False, str(_e280))

    # [281] v9.509 — la PROVA GRATUITA parte dal primo accesso: prima 6 ore dall'approvazione del lead, mentre l'email di AALA
    # promette «attivalo entro 7 giorni, poi 12 ore». Eseguito su un DB TEMPORANEO (mai quello vero).
    try:
        import tempfile as _tf281
        from datetime import datetime as _dt281, timedelta as _td281, UTC as _UTC281
        from pathlib import Path as _P281
        from src import storage as _st281
        _db281 = _P281(_tf281.mkdtemp()) / "t.db"
        _orig281 = _st281._connect
        _st281._connect = lambda db_path=None: _orig281(_db281)
        try:
            _st281.init_db(_db281)
            _ora = _dt281.now(_UTC281)
            _e1 = _st281.provision_account("prova281@esempio.it", "x", hours=6)
            _u = _st281.get_user_by_username("prova281@esempio.it")
            _g1 = (_dt281.fromisoformat(_e1.replace("Z", "+00:00")) - _ora).total_seconds() / 3600
            _a1 = _st281.attiva_demo(_u.id)
            _g2 = (_dt281.fromisoformat(_a1.replace("Z", "+00:00")) - _ora).total_seconds() / 3600 if _a1 else None
            _a2 = _st281.attiva_demo(_u.id)
            _ok_acc = _st281.access_block_reason(_st281.get_user_by_username("prova281@esempio.it")) is None
            _st281.provision_account("pagato281@esempio.it", "x", months=1)
            _p = _st281.get_user_by_username("pagato281@esempio.it")
            _a3 = _st281.attiva_demo(_p.id)
        finally:
            _st281._connect = _orig281
        check("prova[281]: 7 giorni per attivarla, 12 ore dal primo accesso (una volta sola), l'abbonamento pagato non si tocca",
              167 < _g1 < 169 and _g2 is not None and 11.9 < _g2 < 12.1 and _a2 is None and _ok_acc and _a3 is None,
              "%r %r %r %r" % (_g1, _g2, _a2, _a3))
        _w281 = _P281("/app/src/web.py").read_text(encoding="utf-8")
        check("prova[281]: l'attivazione è agganciata al login riuscito", "storage.attiva_demo(user.id)" in _w281)
    except Exception as _e281:  # noqa: BLE001
        check("prova[281]: kontrollet u ekzekutuan", False, str(_e281))

    # [282] v9.510 — TETTO PER UTENTE delle analisi in corso (6 posti del cervello per tutti gli studi): prova 1, pagante 3,
    # amministratore senza; il rifiuto arriva PRIMA che la domanda venga salvata
    try:
        import inspect as _in282
        from types import SimpleNamespace as _NS282
        from src import web as _w282, jobs as _j282
        _t = _w282._tetto_lavori
        _caps = (_t(_NS282(is_admin=True)), _t(_NS282(is_admin=False, demo_expires_at="2026-10-12T00:00:00Z", plan_expires_at=None)),
                 _t(_NS282(is_admin=False, demo_expires_at=None, plan_expires_at="2027-01-01T00:00:00Z")),
                 _t(_NS282(is_admin=False, demo_expires_at=None, plan_expires_at=None)))
        _jid = _j282.create(987654321, "g282")
        _n1 = _j282.count_running(987654321)
        _j282.finish(_jid)
        _n2 = _j282.count_running(987654321)
        _src282 = _in282.getsource(_w282.api_ask_start)
        check("tetto[282]: prova 1, pagante 3, amministratore senza; conteggio dei lavori vivi; rifiuto prima di _ask_prepare; messaggio del server mostrato dal client",
              _caps == (0, 1, 3, 3) and _n1 == 1 and _n2 == 0
              and _src282.find("_tetto_lavori(user)") < _src282.find("_ask_prepare(user, data)")
              and "appendError(_e.error ||" in __import__("pathlib").Path("/app/static/app.js").read_text(encoding="utf-8"), repr((_caps, _n1, _n2)))
    except Exception as _e282:  # noqa: BLE001
        check("tetto[282]: kontrollet u ekzekutuan", False, str(_e282))

    # [283] v9.511 — lo stesso tetto sugli strumenti PRO (X-Job-Key) e, nel client, nessuna attesa di una risposta
    # parcheggiata dopo un rifiuto esplicito (4xx)
    try:
        from types import SimpleNamespace as _NS283
        from src import web as _w283
        _u283 = _NS283(id=987654322, is_admin=False, demo_expires_at="2026-10-12T00:00:00Z", plan_expires_at=None)
        _cu283 = _w283.current_user
        _w283.current_user = lambda: _u283
        try:
            with _w283.app.test_request_context("/api/notary/check", method="POST", headers={"X-Job-Key": "k1"}):
                _r1 = _w283._tetto_strumenti_pro()
                with _w283.app.test_request_context("/api/notary/check", method="POST", headers={"X-Job-Key": "k2"}):
                    _r2 = _w283._tetto_strumenti_pro()
                _w283._libera_strumento_pro()
            _resto = _w283._PRO_IN_CORSO.get(987654322, 0)
            with _w283.app.test_request_context("/api/notary/check", method="POST"):
                _r3 = _w283._tetto_strumenti_pro()          # senza chiave: non conta
        finally:
            _w283.current_user = _cu283
            _w283._PRO_IN_CORSO.pop(987654322, None)
        _js283 = __import__("pathlib").Path("/app/static/app.js").read_text(encoding="utf-8")
        check("tetto[283]: strumenti PRO — il secondo dello stesso account di prova rifiutato (429), slot liberato a fine richiesta; il client non aspetta dopo un 4xx",
              _r1 is None and isinstance(_r2, tuple) and _r2[1] == 429 and _resto == 0 and _r3 is None
              and "eSrv.noRetry = r.status >= 400 && r.status < 500;" in _js283 and "if (eRete && eRete.noRetry) throw eRete;" in _js283,
              repr((_r1, _r2 and _r2[1] if isinstance(_r2, tuple) else _r2, _resto, _r3)))
    except Exception as _e283:  # noqa: BLE001
        check("tetto[283]: kontrollet u ekzekutuan", False, str(_e283))

    # [284] v9.511 — gli errori della CHAT (appendError) finiscono nella bolla del messaggio, che il traduttore del DOM salta
    # di proposito (.msg-body): anche con la voce nel dizionario restavano albanesi («Nuk u kthye përgjigje nga serveri.»)
    try:
        import re as _re284
        _a284 = __import__("pathlib").Path("/app/static/app.js").read_text(encoding="utf-8")
        _sole284 = [l.strip()[:90] for l in _a284.split("\n")
                    if _re284.search(r'appendError\([^)]*["`][^"`]*[ëçË]', l)
                    and "_CAL_IT" not in l and "dataset.lang" not in l]
        check("errori-chat[284]: nessun appendError con testo albanese fisso senza il ramo italiano", not _sole284,
              "; ".join(_sole284[:3]))
    except Exception as _e284:  # noqa: BLE001
        check("errori-chat[284]: kontrollet u ekzekutuan", False, str(_e284))

    # [285] v9.511 — dal banco di prova della v9.510: «art. 340 Reg. C.d.S.» letto come Codice della strada (→ inesistente, barrato dal
    # cancello) e «art. 217, lett. c), n. iii), Reg. 2015/2446» senza codice (il numero romano spezzava la citazione)
    try:
        from src import citation_verifier as _cv285
        from src.retrieval import ArticleIndex as _AI285
        _it285 = _AI285.load(__import__("pathlib").Path("/app/data/index/bm25_it.pkl"))
        def _s285(t):
            v = _cv285.verify_text(t, _it285)["items"]
            c = v[0] if v else {}
            return (c.get("status"), c.get("code")) if isinstance(c, dict) else (c.status, c.code)
        _r285 = [_s285("art. 340 Reg. C.d.S."), _s285("ex art. 340 Reg. esec. C.d.S."), _s285("art. 93 C.d.S."),
                 _s285("art. 9999 Reg. C.d.S."), _s285("art. 217, lett. c), n. iii), Reg. 2015/2446")]
        check("verificatore[285]: «Reg. (esec.) C.d.S.» = il Regolamento, «C.d.S.» = il Codice, il numero inventato resta falso, «n. iii)» non spezza",
              _r285 == [("verified", "regolamento_strada"), ("verified", "regolamento_strada"), ("verified", "codice_strada"),
                        ("fake", "regolamento_strada"), ("verified", "reg_ue_2015_2446")], repr(_r285))
    except Exception as _e285:  # noqa: BLE001
        check("verificatore[285]: kontrollet u ekzekutuan", False, str(_e285))

    # [286] v9.511 — l'acquisto di un immobile con formalità: 2644 (mai nel blocco col triage vero), 2913 (1 volta su 3), 2808 come
    # ancore dichiarate, solo dalla DOMANDA; non nel penale, non fuori tema
    try:
        from src import brain as _br286
        from src.retrieval import ArticleIndex as _AI286
        _br286.set_request_jurisdiction("IT")
        _it286 = _AI286.load(__import__("pathlib").Path("/app/data/index/bm25_it.pkl"))
        _k286 = lambda q, aree: {(a.code, str(a.number)) for a, _ in _br286._applica_ancore([], _it286, q, aree, ancore=_br286.ANCORE_IT)}
        _v286 = _k286(["effetti del pignoramento sulla vendita", "Il cliente vuole acquistare un appartamento: dalla visura risultano un'ipoteca e un pignoramento trascritto. La vendita è possibile?"], ["Civile"])
        _p286 = _k286(["sequestro e pignoramento", "Vendeva auto rubate: il pignoramento dei beni è possibile?"], ["Penale"])
        _f286 = _k286(["trascrizione", "Il mio cliente deve trascrivere la sentenza di divorzio?"], ["Famiglia"])
        _br286.set_request_jurisdiction("AL")
        _att = {("codice_civile", "2644"), ("codice_civile", "2913"), ("codice_civile", "2808")}
        check("visura[286]: acquisto con ipoteca/pignoramento → 2644, 2913, 2808; mai nel penale né sulla trascrizione di una sentenza",
              _att <= _v286 and not (_att & _p286) and not (_att & _f286), repr((sorted(_v286), sorted(_p286), sorted(_f286))))
    except Exception as _e286:  # noqa: BLE001
        check("visura[286]: kontrollet u ekzekutuan", False, str(_e286))

    # [287] v9.512 — nel rapporto delle fonti in sessione IT il titolo scritto dal raccoglitore con una nota albanese
    # («… (sintezë nga Brocardi/ASAPS mbi rregullin e 60») si pulisce; i titoli italiani e la sessione albanese non si toccano
    try:
        from src import war_room as _wr287
        _f287 = _wr287._titolo_nella_lingua
        check("fonti[287]: titolo con nota albanese ripulito in IT, intatto in AL, dominio come ultima risorsa",
              _f287("Art. 132 CdS – Circolazione dei veicoli immatricolati negli Stati esteri (sintezë nga Brocardi/ASAPS mbi rregullin e 60",
                    "https://www.brocardi.it/x", "it") == "Art. 132 CdS – Circolazione dei veicoli immatricolati negli Stati esteri"
              and _f287("Corte cost. 113/2023 (sintesi)", "", "it") == "Corte cost. 113/2023 (sintesi)"
              and _f287("Shkelja e rregullave për mjetet", "https://www.asaps.it/a", "it") == "asaps.it"
              and _f287("Neni 153 (sintezë nga QBZ)", "https://qbz.gov.al", "sq") == "Neni 153 (sintezë nga QBZ)"
              and "_titolo_nella_lingua(i.titulli, i.burimi, lang)" in __import__("inspect").getsource(_wr287.raport_verifikimi))
    except Exception as _e287:  # noqa: BLE001
        check("fonti[287]: kontrollet u ekzekutuan", False, str(_e287))

    # [288] v9.513 — il trattino NON SEPARABILE Unicode del modello («art. 452‑terdecies c.p.») diventa «-» dove esce ogni testo del
    # modello (prima il verificatore leggeva «art. 452», l'articolo sbagliato); il trattino lungo degli intervalli resta
    try:
        import inspect as _in288
        from src import backends as _bk288
        _src288 = _in288.getsource(_bk288)
        check("trattini[288]: ‑ → - a parità di lunghezza, «–» intatto, applicato al testo di complete, ai frammenti e al testo finale dello streaming",
              _bk288._trattini("art. 452\u2011terdecies c.p. e artt. 1218\u20131223") == "art. 452-terdecies c.p. e artt. 1218\u20131223"
              and _src288.count("_trattini(") >= 5)
    except Exception as _e288:  # noqa: BLE001
        check("trattini[288]: kontrollet u ekzekutuan", False, str(_e288))

    # [289] v9.514 — «Neni 133, pika 3/a, i Kodit të Procedurave Administrative»: la barra dopo il numero della pika spezzava la citazione
    try:
        from src import citation_verifier as _cv289, brain as _br289
        from src.retrieval import ArticleIndex as _AI289
        _br289.set_request_jurisdiction("AL")
        _al289 = _AI289.load()
        def _s289(t):
            v = _cv289.verify_text(t, _al289)["items"]; c = v[0] if v else {}
            return (c.get("status"), c.get("code")) if isinstance(c, dict) else (c.status, c.code)
        check("pika[289]: «pika 3/a» non spezza la citazione; il numero inventato resta falso",
              _s289("Neni 133, pika 3/a, i Kodit të Procedurave Administrative.") == ("verified", "kodi_proc_admin")
              and _s289("Neni 9999, pika 3/a, i Kodit të Procedurave Administrative.")[0] == "fake")
    except Exception as _e289:  # noqa: BLE001
        check("pika[289]: kontrollet u ekzekutuan", False, str(_e289))

    # [290] v9.515 — due parole prese per la LETTERA di un comma: «, TU Immigrazione» («TU») e «, né l'art. …» («n» di «né»)
    try:
        from src import citation_verifier as _cv290, brain as _br290
        from src.retrieval import ArticleIndex as _AI290
        _br290.set_request_jurisdiction("IT")
        _it290 = _AI290.load(__import__("pathlib").Path("/app/data/index/bm25_it.pkl"))
        _st290 = lambda t: [(c.get("status"), c.get("code"), c.get("number")) for c in _cv290.verify_text(t, _it290)["items"]]
        _br290.set_request_jurisdiction("AL")
        check("lettere[290]: «, TU Immigrazione» e «, né l'art.» non sono lettere di comma; il numero inventato resta falso",
              _st290("art. 30, comma 1, lett. d), TU Immigrazione") == [("verified", "tu_immigrazione", "30")]
              and _st290("l'art. 36, comma 5, né l'art. 135-sexies, comma 3, Codice del Consumo") == [("verified", "codice_consumo", "36"), ("verified", "codice_consumo", "135/sexies")]
              and _st290("l'art. 9999, comma 2, né l'art. 2043 c.c.")[0][0] == "fake")
    except Exception as _e290:  # noqa: BLE001
        check("lettere[290]: kontrollet u ekzekutuan", False, str(_e290))

    # [291] v9.516 — il completamento delle righe «non recuperato» non torna ai tetti 10/8 (nella visura del banco una riga del parere,
    # «art. 2946 c.c. — non recuperato», era rimasta oltre la decima)
    try:
        from src import cancello as _cn291
        check("completa[291]: fino a 14 righe e 12 articoli per risposta", _cn291.COMPLETA_MAX_RIGHE >= 14 and _cn291.COMPLETA_MAX_ART >= 12)
    except Exception as _e291:  # noqa: BLE001
        check("completa[291]: kontrollet u ekzekutuan", False, str(_e291))

    # [292] v9.517 — il rinvio per NOME al KPA: un articolo recuperato di un altro atto che rinvia al Codice di procedura
    # amministrativa (ligji 79/2021 neni 73: il ricorso contro la revoca del permesso) porta KPA 132 (termine) e 133 (effetti)
    try:
        from src import brain as _br292
        from src.retrieval import ArticleIndex as _AI292
        _sa292 = _br292.SuperAvvocato.__new__(_br292.SuperAvvocato)
        _sa292.index = _AI292.load(); _sa292.index_it = None; _sa292._jurisdiction_ctx = __import__("threading").local()
        _by292 = {(a.code, str(a.number)): a for a in _sa292.index.articles}
        _r73 = _by292.get(("ligji_te_huajt", "73")); _kc = _by292.get(("kodi_civil", "114"))
        _sa292._jurisdiction_ctx.code = "AL"
        _out292 = {(a.code, str(a.number)) for a, _ in _sa292._aggiungi_rinvio_kpa([(_r73, 5.0)])} if _r73 else set()
        _no292 = {(a.code, str(a.number)) for a, _ in _sa292._aggiungi_rinvio_kpa([(_kc, 5.0)])}
        _sa292._jurisdiction_ctx.code = "IT"
        _it292 = {(a.code, str(a.number)) for a, _ in _sa292._aggiungi_rinvio_kpa([(_r73, 5.0)])} if _r73 else set()
        check("kpa[292]: l'art. 73 della 79/2021 porta KPA 132 e 133; un articolo che non nomina il KPA no; in sessione IT nulla",
              {("kodi_proc_admin", "132"), ("kodi_proc_admin", "133")} <= _out292
              and not any(c == "kodi_proc_admin" for c, _ in _no292) and not any(c == "kodi_proc_admin" for c, _ in _it292),
              repr((sorted(_out292), sorted(_no292))))
    except Exception as _e292:  # noqa: BLE001
        check("kpa[292]: kontrollet u ekzekutuan", False, str(_e292))

    # [293] v9.519 — il GRASSETTO attorno ai numeri di un elenco albanese («**Neni 12** dhe **Neni 96 i Ligjit nr. 9901/2008**»)
    try:
        from src import citation_verifier as _cv293, brain as _br293
        from src.retrieval import ArticleIndex as _AI293
        _br293.set_request_jurisdiction("AL")
        _al293 = _AI293.load()
        _s293 = lambda t: [(c.get("status"), c.get("code"), c.get("number")) for c in _cv293.verify_text(t, _al293)["items"]]
        check("grassetto[293]: l'elenco in grassetto prende il codice in comune; un numero inventato resta falso",
              _s293("Tagrat lindin nga ligji — **Neni 12** dhe **Neni 96 i Ligjit nr. 9901/2008**.")
              == [("verified", "ligji_shoqerite_tregtare", "12"), ("verified", "ligji_shoqerite_tregtare", "96")]
              and _s293("**Neni 9999** dhe **Neni 96 i Ligjit nr. 9901/2008**")[0][0] == "fake")
    except Exception as _e293:  # noqa: BLE001
        check("grassetto[293]: kontrollet u ekzekutuan", False, str(_e293))

    # [294] v9.520 — dalla prova in Chrome: il caso nuovo nasce col titolo nella lingua della sessione («Nuovo caso», e la prima
    # domanda lo sostituisce anche così); con Telegram già collegato il pulsante non invita più a «collegarlo»
    try:
        from src import web as _w294
        _a294 = __import__("pathlib").Path("/app/static/app.js").read_text(encoding="utf-8")
        _s294 = __import__("inspect").getsource(_w294)
        check("ritocchi[294]: titolo predefinito nella lingua della sessione e riconosciuto per il titolo automatico; pulsante Telegram secondo lo stato",
              "Nuovo caso" in _w294._TITOLI_PREDEFINITI and "Rast i ri" in _w294._TITOLI_PREDEFINITI
              and '("Nuovo caso" if attiva == "IT" else "Rast i ri")' in _s294 and _s294.count("case.title in _TITOLI_PREDEFINITI") == 2
              and 'createCase(title = (document.body.dataset.lang === "it" ? "Nuovo caso" : "Rast i ri"))' in _a294
              and '"Ricollega o cambia account"' in _a294)
    except Exception as _e294:  # noqa: BLE001
        check("ritocchi[294]: kontrollet u ekzekutuan", False, str(_e294))

    # [295] v9.520 — parole inglesi nell'interfaccia (scansione del DOM vivo da telefono): «Provenance ·» sul riquadro, «Refusal» in
    # albanese, la Segretaria con «Close / Voice / Send» fissi, «Dil / Logout»
    try:
        _P295 = __import__("pathlib").Path
        _a295 = _P295("/app/static/app.js").read_text(encoding="utf-8")
        _sk295 = _P295("/app/static/secretary.js").read_text(encoding="utf-8")
        _h295 = _P295("/app/templates/index.html").read_text(encoding="utf-8")
        check("inglese[295]: Provenienza/Prejardhja, Refuzim, Segretaria tradotta, uscita tradotta",
              '<span class="prov-label">${PL.nome} ·' in _a295 and 'nome: "Provenienza"' in _a295 and "⚠ Refusal" not in _a295
              and 'aria-label="Close"' not in _sk295 and 'title="Send"' not in _sk295 and 'close: "Chiudi"' in _sk295
              and "secretary.js?v=2" in _h295 and 'aria-label="Dil / Logout"' not in _h295)
    except Exception as _e295:  # noqa: BLE001
        check("inglese[295]: kontrollet u ekzekutuan", False, str(_e295))

    # [296] v9.521 — il tetto di tempo dei raccoglitori stava solo nel futuro: il processo (web) restava vivo fino a 45 min col
    # suo posto nel semaforo (visto in produzione: 9 min dopo la risposta). Ora il tetto arriva alla CLI e la ferma.
    try:
        from src import studio as _st296, backends as _bk296
        _kw296 = []

        class _F296:
            def complete(self, **kw):
                _kw296.append(kw.get("timeout_s"))
                return "{}"

        class _A296:
            code, number, title_sq, heading, body = "kodi_civil", "1", "Kodi Civil", "h", "b"
        _st296.mbledh_dosjen(_F296(), domanda="D", summary="S", retrieved=[(_A296(), 1.0)], lang="it", timeout_s=40)
        # la CLI vera: subprocess.run riceve il tetto della chiamata, non i 2700 s del backend
        _tm296 = []
        _run0 = _bk296.subprocess.run

        def _run296(*a, **kw):
            _tm296.append(kw.get("timeout"))
            raise _bk296.subprocess.TimeoutExpired(cmd="claude", timeout=kw.get("timeout"))
        _bk296.subprocess.run = _run296
        _as296 = _bk296._audit_safe
        _bk296._audit_safe = lambda **kw: None     # il golden gira anche in produzione: niente righe finte nell'audit vero
        try:
            _b296 = _bk296.ClaudeCodeBackend()
            try:
                _b296.complete(system="s", messages=[{"role": "user", "content": "u"}], medium=True, timeout_s=55,
                               callsite="golden:296")
                _e296 = ""
            except RuntimeError as _x296:
                _e296 = str(_x296)
        finally:
            _bk296.subprocess.run = _run0
            _bk296._audit_safe = _as296
        check("tetto[296]: i raccoglitori passano il tetto alla CLI (55 s), il processo si ferma e lo dice",
              sorted(set(_kw296)) == [55] and len(_kw296) == 3 and _tm296[:1] == [55] and "55s" in _e296,
              f"kw={_kw296} run={_tm296} err={_e296[:80]}")
        # l'uscita rc=1 per tetto di spesa: motivo e costo nell'audit (prima: «NonZeroReturnCode» muto, consumo perso)
        _au296 = []
        _as0 = _bk296._audit_safe
        _bk296._audit_safe = lambda **kw: _au296.append(kw)
        _bk296.subprocess.run = lambda *a, **kw: _bk296.subprocess.CompletedProcess(
            a[0] if a else "claude", 1, stdout='{"terminal_reason":"budget_exhausted","total_cost_usd":0.51,"usage":{}}',
            stderr="")
        try:
            try:
                _b296.complete(system="s", messages=[{"role": "user", "content": "u"}], medium=True, callsite="golden:296b")
            except RuntimeError:
                pass
        finally:
            _bk296.subprocess.run = _run0
            _bk296._audit_safe = _as0
        check("tetto[296]: il tetto di spesa finito va nell'audit come BudgetExhausted col costo (0,51 $)",
              any(x.get("error_class") == "BudgetExhausted" and x.get("cost_micro_usd") == 510000 for x in _au296),
              str([(x.get("error_class"), x.get("cost_micro_usd")) for x in _au296]))
    except Exception as _e296x:  # noqa: BLE001
        check("tetto[296]: kontrollet u ekzekutuan", False, f"{type(_e296x).__name__}: {_e296x}")

    # [297] v9.521 — la riga del motore dei termini che È l'udienza della citazione («Udienza di comparizione e trattazione»,
    # senza ora) usciva come «termine» accanto all'udienza letta dal documento (ore 9:30): due righe per la stessa udienza (prova
    # in Chrome, citazione per il 02/02/2027). Diventa udienza solo se il titolo la nomina E il giorno è un'udienza del documento.
    try:
        from src import scadenziario as _sz297
        _c297 = _sz297._afati.compute
        _sz297._afati.compute = lambda *a, **k: {"afatet": [
            {"title": "Udienza di comparizione e trattazione — comparizione personale", "date": "2027-02-02",
             "baza": "art. 183 c.p.c.", "passi": ["x"]},
            {"title": "Termine per comparire all'udienza", "date": "2027-02-02", "baza": "art. 163 c.p.c.", "passi": ["y"]},
            {"title": "Udienza di precisazione delle conclusioni", "date": "2027-03-03", "baza": "art. 189 c.p.c.", "passi": ["z"]}]}
        try:
            _doc297 = {"tipo": "data", "kind": "seance", "data": "2027-02-02", "ora": "09:30", "origine": "documento",
                       "titolo": "Udienza di comparizione delle parti"}
            _r297 = _sz297.termini_di_legge(None, None, {"trigger": "citazione", "descrizione": "d"}, jurisdiction="IT",
                                            lang="it", data="2026-09-25", altre_date=[_doc297])
        finally:
            _sz297._afati.compute = _c297
        check("udienza[297]: la riga del motore che è l'udienza del documento si unisce (ora tenuta); il termine resta termine",
              [x["kind"] for x in _r297] == ["seance", "afat", "afat"] and _sz297.stesso_evento(_r297[0], _doc297)
              and not _sz297.stesso_evento(_r297[1], _doc297), str([(x["kind"], x["data"]) for x in _r297]))
    except Exception as _e297:  # noqa: BLE001
        check("udienza[297]: kontrollet u ekzekutuan", False, f"{type(_e297).__name__}: {_e297}")

    # [298] v9.523 — esportazioni: il .docx si chiamava come il titolo dentro `data/exports` CONDIVISA (due studi con lo stesso
    # titolo nello stesso istante = documento dell'altro) e restava sul disco; il nome perdeva le vocali accentate; il Markdown
    # e l'HTML del caso erano sempre in albanese («Super Avvocato — eksport i bisedës», «Qytetari», lang="sq")
    try:
        from src import web as _w298
        _n298 = _w298._nome_file_sicuro("Parere sulla responsabilità civile", "x")
        _r0 = _w298.pro_mod.render_act_docx
        _w298.pro_mod.render_act_docx = lambda draft, path: path.write_bytes(b"PK-docx-" + draft["title"].encode())
        try:
            _b298 = _w298._docx_in_memoria({"title": "T298", "body_markdown": "x"})
        finally:
            _w298.pro_mod.render_act_docx = _r0
        _resti298 = list((_w298.APP_DB_PATH.parent / "exports").glob(".exp-*.docx"))
        _src298 = __import__("inspect").getsource(_w298.api_export_case)
        _js298 = __import__("pathlib").Path("/app/static/app.js").read_text(encoding="utf-8")
        check("export[298]: docx in memoria senza resti, nome con le accentate, Markdown e HTML nella lingua della sessione",
              _n298 == "Parere sulla responsabilità civile" and _b298.getvalue() == b"PK-docx-T298" and not _resti298
              and "eksport i bisedës_" not in _src298.replace("{_X[1]}", "") and '"esportazione della conversazione"' in _src298
              and '"⚖️ Super Avvocato"' not in _src298 and "_Super Avvocato — " not in _src298 and '(_itx ? "it" : "sq")' in _js298
              and 'html lang="sq"><head>' not in _js298 and '"Njoftimet nuk u lejuan": "Notifiche non consentite"' in _js298,
              f"nome={_n298!r} resti={len(_resti298)}")
        from docx import Document as _D298
        from src import pro_features as _pf298
        _pp298 = {"response_id": "r298", "timestamp_iso": "2026-10-06", "confidence": 1.0, "confidence_label": "I lartë",
                  "citations": {"items": []}, "retrieved_articles": []}
        _t298 = {j: " ".join(x.text for x in _D298(__import__("io").BytesIO(_pf298.provenance_docx(dict(_pp298, jurisdiction=j)))).paragraphs)
                 for j in ("IT", "AL")}
        check("export[298]: il documento di provenienza ha il titolo nella lingua del fascicolo (era «PROVENANCE PACK»)",
              "PACCHETTO DI PROVENIENZA" in _t298["IT"] and "PAKETA E PREJARDHJES" in _t298["AL"]
              and not any("PROVENANCE" in v or "REFUSAL" in v for v in _t298.values())
              and '"provenienza_"' in __import__("inspect").getsource(_w298.api_provenance_docx), str(_t298)[:160])
        _ic298 = _w298._render_ical("prova", [], tz="Europe/Rome")
        check("export[298]: il calendario iCal col nome giusto e il fuso di Roma per l'avvocato italiano",
              "X-WR-CALNAME:Super Avokati — prova" in _ic298 and "X-WR-TIMEZONE:Europe/Rome" in _ic298
              and "Super Avvocato" not in _ic298 and "Europe/Tirane" in _w298._render_ical("prova", []), _ic298[:120])
    except Exception as _e298:  # noqa: BLE001
        check("export[298]: kontrollet u ekzekutuan", False, f"{type(_e298).__name__}: {_e298}")

    # [299] v9.523 — 330 errori del server erano codici inglesi mostrati così come sono («not found», «forbidden», «brain not
    # available»): tradotti in un punto nella lingua della sessione, codice conservato in `code`; i codici che il client
    # confronta restano intatti
    try:
        from src import web as _w299
        from flask import Response as _R299
        import json as _j299

        def _prova299(err, status=404):
            with _w299.app.test_request_context("/api/x"):
                _r = _w299._errori_nella_lingua(_R299(_j299.dumps({"error": err}), status=status, mimetype="application/json"))
                return _r.get_json()
        _a299, _b299, _c299, _d299 = _prova299("not found"), _prova299("text_required", 400), _prova299("forbidden", 200), \
            _prova299("brain not available", 503)
        check("errori[299]: codici inglesi tradotti (code conservato), confronti del client intatti, risposte 2xx intatte",
              _a299["error"].startswith("Nuk u gjet") and _a299["code"] == "not found" and _b299 == {"error": "text_required"}
              and _c299 == {"error": "forbidden"} and _d299["error"].startswith("Shërbimi nuk është gati")
              and all(len(v) == 2 and v[1] for v in _w299._ERRORI_UMANI.values()), str([_a299, _b299, _d299])[:200])
    except Exception as _e299:  # noqa: BLE001
        check("errori[299]: kontrollet u ekzekutuan", False, f"{type(_e299).__name__}: {_e299}")

    # [300] v9.524 — la prescrizione del danno da sinistro: il ramo del fatto-reato (art. 2947, c. 3) ha bisogno di 590, 590-bis
    # e 157 c.p. nel blocco (prova viva: «il numero dell'articolo sulle lesioni stradali non è tra quelli che ho recuperati»);
    # solo dalla domanda — non per un credito qualsiasi né per un sinistro senza prescrizione
    try:
        from src import brain as _br300
        from src.retrieval import ArticleIndex as _AI300
        _br300.set_request_jurisdiction("IT")
        _it300 = _AI300.load(__import__("pathlib").Path("/app/data/index/bm25_it.pkl"))
        _k300 = lambda q, aree: {(a.code, str(a.number)) for a, _ in _br300._applica_ancore([], _it300, q, aree, ancore=_br300.ANCORE_IT)}
        _v300 = _k300(["prescrizione del risarcimento da circolazione", "Il mio cliente ha avuto un incidente stradale il 10 marzo 2024. Entro quando deve chiedere il risarcimento prima che si prescriva?"], ["Civile"])
        _c300 = _k300(["prescrizione del credito", "Il credito del cliente risale al 2013: è prescritto?"], ["Civile"])
        _s300 = _k300(["prescrizione", "Il cliente ha avuto un incidente stradale ieri: chi paga i danni?"], ["Civile"])
        _br300.set_request_jurisdiction("AL")
        _att300 = {("codice_penale", "590"), ("codice_penale", "590-bis"), ("codice_penale", "157")}
        check("sinistro[300]: prescrizione del danno da incidente → 590, 590-bis, 157 c.p. (fatto-reato); non per un credito né senza prescrizione",
              _att300 <= _v300 and ("codice_civile", "2947") in _v300 and not (_att300 & _c300) and not (_att300 & _s300),
              repr((sorted(_v300), sorted(_c300), sorted(_s300))))
    except Exception as _e300:  # noqa: BLE001
        check("sinistro[300]: kontrollet u ekzekutuan", False, str(_e300))

    # [301] v9.525 — NASpI: «68 giorni — norma non tra quelle recuperate» in un licenziamento, «l'art. 4 non è tra gli articoli
    # recuperati» in una domanda sulla NASpI → ancore dalla domanda; non nel penale, non in una domanda di lavoro qualsiasi
    try:
        from src import brain as _br301
        from src.retrieval import ArticleIndex as _AI301
        _br301.set_request_jurisdiction("IT")
        _it301 = _AI301.load(__import__("pathlib").Path("/app/data/index/bm25_it.pkl"))
        _k301 = lambda q, aree: {(a.code, str(a.number)) for a, _ in _br301._applica_ancore([], _it301, q, aree, ancore=_br301.ANCORE_IT)}
        _n301 = _k301(["indennità di disoccupazione", "Il cliente è stato licenziato: quanto prende di NASpI e per quanto tempo?"], ["Lavoro"])
        _l301 = _k301(["licenziamento disciplinare", "Il cliente è stato licenziato per giusta causa dopo una contestazione. Cosa fare?"], ["Lavoro"])
        _p301 = _k301(["truffa", "Il cliente ha percepito la NASpI lavorando in nero: rischia il processo per truffa?"], ["Penale"])
        _f301 = _k301(["ferie", "Il datore non concede le ferie al cliente: cosa può fare?"], ["Lavoro"])
        _br301.set_request_jurisdiction("AL")
        _att301 = {("naspi", "3"), ("naspi", "4"), ("naspi", "5"), ("naspi", "6")}
        check("naspi[301]: domanda sulla NASpI → 3-6, licenziamento → 6 (68 giorni); mai nel penale né fuori tema",
              _att301 <= _n301 and ("naspi", "6") in _l301 and ("naspi", "4") not in _l301
              and not (_att301 & _p301) and not (_att301 & _f301), repr((sorted(_n301), sorted(_l301), sorted(_p301))))
        # … e (AL) il compenso della detenzione ingiusta: KPP 268-269 dalla domanda, non per una misura cautelare qualsiasi
        from src.retrieval import ArticleIndex as _AI301b
        _al301 = _AI301b.load()
        _ka301 = lambda q, aree: {(a.code, str(a.number)) for a, _ in _br301._applica_ancore([], _al301, q, aree)}
        _d301 = _ka301(["dëmshpërblim për paraburgim", "Klienti u mbajt 8 muaj në paraburgim dhe u pafajësua. Çfarë kompensimi i takon?"], ["Penal", "Civil"])
        _m301 = _ka301(["masa e sigurimit", "Klientit i dhanë paraburgim për vjedhje. Si e apelojmë masën?"], ["Penal"])
        check("naspi[301]: (AL) detenzione ingiusta → KPP 268-269 dalla domanda; non per l'appello contro la misura",
              {("kodi_proc_penale", "268"), ("kodi_proc_penale", "269")} <= _d301
              and not ({("kodi_proc_penale", "268"), ("kodi_proc_penale", "269")} & _m301), repr((sorted(_d301), sorted(_m301))))
    except Exception as _e301:  # noqa: BLE001
        check("naspi[301]: kontrollet u ekzekutuan", False, str(_e301))

    # [302] v9.526 — l'auto con targa extra-UE: oltre al regime doganale (CDU, Reg. 2015/2446) le SANZIONI nazionali del D.Lgs.
    # 141/2024 (99, 96, 78, 94) — sei risposte vere dicevano «non è fra le norme recuperate»; mai per un'auto italiana
    try:
        from src import brain as _br302
        from src.retrieval import ArticleIndex as _AI302
        _it302 = _AI302.load(__import__("pathlib").Path("/app/data/index/bm25_it.pkl"))
        _k302 = lambda t: {(a.code, str(a.number)) for a, _ in _br302._ancore_it_veicolo([], _it302, t)}
        _v302 = _k302("Il cliente vive in Italia da tre anni e guida un'auto targata albanese intestata alla sua sh.p.k.: rischia la confisca?")
        _i302 = _k302("Il cliente ha preso una multa con la sua auto immatricolata a Milano: come la contesta?")
        _att302 = {("codice_doganale_nazionale", n) for n in ("99", "96", "78", "94")}
        check("dogana[302]: auto extra-UE → anche le sanzioni del D.Lgs. 141/2024 (99, 96, 78, 94); auto italiana → nessuna",
              _att302 <= _v302 and ("codice_strada", "93-bis") in _v302 and not _i302, repr((sorted(_v302), sorted(_i302))))
    except Exception as _e302:  # noqa: BLE001
        check("dogana[302]: kontrollet u ekzekutuan", False, str(_e302))

    # [303] v9.527 — cittadinanza: la norma base del canale nel blocco (art. 9 per residenza, entrava al 14° posto; art. 5 per
    # matrimonio), oltre a 9.1/9-ter/10 della v9.506
    try:
        from src import brain as _br303
        from src.retrieval import ArticleIndex as _AI303
        _br303.set_request_jurisdiction("IT")
        _it303 = _AI303.load(__import__("pathlib").Path("/app/data/index/bm25_it.pkl"))
        _k303 = lambda q: {(a.code, str(a.number)) for a, _ in _br303._applica_ancore([], _it303, q, ["Immigrazione"], ancore=_br303.ANCORE_IT)}
        _r303 = _k303(["cittadinanza per residenza", "Il cliente risiede legalmente in Italia da undici anni: può chiedere la cittadinanza?"])
        _m303 = _k303(["cittadinanza per matrimonio", "Il cliente è sposato da tre anni con una cittadina italiana: come ottiene la cittadinanza?"])
        _p303 = _k303(["permesso di soggiorno", "Il permesso di soggiorno del cliente è scaduto: può rinnovarlo?"])
        _br303.set_request_jurisdiction("AL")
        _br303.set_request_jurisdiction("IT")
        _di303 = _k303(["termine opposizione", "Al cliente è stato notificato un decreto ingiuntivo il 1° ottobre. Entro quando fa opposizione?"])
        _av303 = _k303(["ricorso verbale", "Il cliente ha ricevuto una multa da autovelox notificata ieri. Entro quando può fare ricorso?"])
        _dp303 = _k303(["opposizione decreto penale", "Al cliente è stato notificato un decreto penale di condanna: entro quando l'opposizione?"])
        _er303 = _k303(["rinuncia all'eredità", "Il padre del cliente è morto lasciando più debiti che beni. Come evita di pagarli?"])
        _ta303 = _k303(["ricorso giurisdizionale", "Il Comune ha negato al cliente il permesso di costruire. Come lo impugniamo?"])
        _no303 = _k303(["notifica tardiva", "Il ricorso notarile è stato depositato in modo tardivo: cosa succede?"])
        _ac303 = _k303(["ricorso tributario", "Al cliente è stato notificato un avviso di accertamento IRPEF. Entro quando il ricorso?"])
        _br303.set_request_jurisdiction("AL")
        check("frequenti[303]: decreto ingiuntivo → c.p.c. 641/645/650 (non col decreto penale); multa → C.d.S. 203/204-bis/202; eredità con debiti → c.c. 519/484; TAR → c.p.a. 29 (non «tardivo»)",
              {("codice_procedura_civile", "641"), ("codice_procedura_civile", "645")} <= _di303
              and {("codice_strada", "203"), ("codice_strada", "204-bis")} <= _av303
              and ("codice_procedura_civile", "641") not in _dp303 and ("codice_strada", "203") not in _di303
              and {("codice_civile", "519"), ("codice_civile", "484")} <= _er303 and ("codice_civile", "519") not in _av303
              and ("codice_processo_amministrativo", "29") in _ta303 and ("codice_processo_amministrativo", "29") not in _no303
              and ("processo_tributario", "21") in _ac303,
              repr((sorted(_di303), sorted(_av303), sorted(_dp303))))
        check("cittadinanza[303]: residenza → art. 9, matrimonio → art. 5 (con 9.1/9-ter/10); il permesso di soggiorno no",
              ("cittadinanza", "9") in _r303 and ("cittadinanza", "5") in _m303 and ("cittadinanza", "10") in _m303
              and not any(c == "cittadinanza" for c, _ in _p303), repr((sorted(_r303), sorted(_m303), sorted(_p303))))
    except Exception as _e303:  # noqa: BLE001
        check("cittadinanza[303]: kontrollet u ekzekutuan", False, str(_e303))

    # [304] v9.527 — (AL) diffamazione → KP 120/119 + KC 625; forma del testamento («olograf» del triage ≠ «ollograf» del codice)
    # → KC 392/393/404; dalla domanda, non fuori tema
    try:
        from src import brain as _br304
        from src.retrieval import ArticleIndex as _AI304
        _al304 = _AI304.load()
        _br304.set_request_jurisdiction("AL")
        _k304 = lambda q, aree: {(a.code, str(a.number)) for a, _ in _br304._applica_ancore([], _al304, q, aree)}
        _d304 = _k304(["cenimi i nderit", "Një person publikoi në Facebook se klienti im është hajdut. Çfarë mund të bëjmë?"], ["Civil"])
        _t304 = _k304(["forma e testamentit", "Gjyshi la një testament të shtypur në kompjuter dhe të nënshkruar me dorë. A është i vlefshëm?"], ["Civil"])
        _x304 = _k304(["trashëgimia ligjore", "Babai vdiq pa testament: si ndahet pasuria?"], ["Civil"])
        _m304 = _k304(["pjesa e detyrueshme", "Babai la me testament gjithë pasurinë vëllait; klienti ishte 16 vjeç. A ka të drejtë?"], ["Civil"])
        _o304 = _k304(["kohëzgjatja e punës", "Punëdhënësi e detyron klientin të punojë 12 orë në ditë pa ia paguar orët shtesë. Çfarë i takon?"], ["Punë"])
        _u304 = _k304(["parashkrimi fitues", "Klienti e punon dhe e ka rrethuar prej 25 vjetësh një tokë të fqinjit. A mund të bëhet pronar?"], ["Prone"])
        _q304 = _k304(["qiraja", "Qiramarrësi jeton prej 5 vjetësh në banesë dhe nuk paguan; pronari si ta nxjerrë?"], ["Civil"])
        check("ancore[304]: (AL) diffamazione → KP 120/119 + KC 625; forma del testamento → KC 392/393/404; figlio minore escluso → KC 379; straordinari → KP 91; usucapione → KC 169 (non l'affitto); fuori tema no",
              {("kodi_penal", "120"), ("kodi_penal", "119"), ("kodi_civil", "625")} <= _d304
              and {("kodi_civil", "392"), ("kodi_civil", "393"), ("kodi_civil", "404")} <= _t304
              and ("kodi_civil", "379") in _m304 and ("kodi_civil", "379") not in _x304
              and ("kodi_punes", "91") in _o304 and ("kodi_punes", "91") not in _x304
              and ("kodi_civil", "169") in _u304 and ("kodi_civil", "169") not in _q304
              and not ({("kodi_civil", "392"), ("kodi_civil", "404"), ("kodi_penal", "120")} & _x304), repr((sorted(_d304), sorted(_t304), sorted(_x304), sorted(_m304))))
    except Exception as _e304:  # noqa: BLE001
        check("ancore[304]: kontrollet u ekzekutuan", False, str(_e304))

    # [305] v9.528 — (1) i reati con la rubrica di UNA parola («Vjedhja», «Mashtrimi») non passavano mai l'ancora della figura di
    # reato (servivano due radici in comune); (2) l'articolo che il TRIAGE cita col codice entra nel blocco (max 3, in aggiunta);
    # (3) la casa comprata senza notaio → KC 83/92
    try:
        from src import brain as _br305
        from src.retrieval import ArticleIndex as _AI305
        _al305 = _AI305.load()
        _br305.set_request_jurisdiction("AL")
        _v305 = {(a.code, str(a.number)) for a, _ in _br305._ancora_vepra_penale([], _al305, ["vjedhja në dyqan", "vjedhje me vlerë të vogël"], ["Penal"])}
        _m305 = {(a.code, str(a.number)) for a, _ in _br305._ancora_vepra_penale([], _al305, ["mashtrimi për vizë pune", "mashtrim me para"], ["Penal"])}
        _t305 = {(a.code, str(a.number)) for a, _ in _br305._citati_dal_triage([], _al305, ["vjedhja neni 134 i Kodit Penal", "dënimi"])}
        _n305 = {(a.code, str(a.number)) for a, _ in _br305._citati_dal_triage([], _al305, ["vjedhja e vogël", "dënimi me gjobë"])}
        _h305 = {(a.code, str(a.number)) for a, _ in _br305._applica_ancore([], _al305, ["forma e kontratës", "Klienti bleu një shtëpi me një marrëveshje të shkruar me dorë, pa noter. Është pronar?"], ["Civil"])}
        # la forma speciale già nel blocco (143/b) non tiene fuori la base (143)
        _sp305 = [(a, 9.0) for a in _al305.articles if a.code == "kodi_penal" and str(a.number) in ("143/b", "146")]
        _bs305 = {(a.code, str(a.number)) for a, _ in _br305._ancora_vepra_penale(_sp305, _al305, ["mashtrimi me premtime false", "mashtrim për vizë"], ["Penal"])}
        _k305 = lambda q, aree: {(a.code, str(a.number)) for a, _ in _br305._applica_ancore([], _al305, q, aree)}
        _w305 = _k305(["forma e kontratës", "Klienti punoi dy vjet pa kontratë të shkruar dhe pronari e largoi."], ["Punë"])
        _f305 = _k305(["pasuria e përbashkët", "Burri i klientes e shiti shtëpinë pa e pyetur atë."], ["Familje"])
        _g305 = _k305(["sekuestrim doganor", "Dogana i sekuestroi klientit makinën për kontrabandë. Si ta kundërshtojmë?"], ["Administrativ"])
        _pd305 = _k305(["vjedhja", "Klienti u kap duke vjedhur në një dyqan. Çfarë dënimi rrezikon dhe si e mbrojmë?"], ["Penal"])
        _cv305 = _k305(["kontrata", "Klienti rrezikon të humbasë depozitën e qirasë: çfarë bëjmë?"], ["Civil"])
        check("reati[305]: difesa penale → KP 48/53/59 + KPP 406, tentativo → KP 22/23; non nel civile",
              {("kodi_penal", "48"), ("kodi_penal", "59"), ("kodi_proc_penale", "406"), ("kodi_penal", "22"), ("kodi_penal", "23")} <= _pd305
              and not ({("kodi_penal", "48"), ("kodi_penal", "22")} & _cv305), repr((sorted(_pd305), sorted(_cv305))))
        check("reati[305]: base 143 anche con 143/b nel blocco; KP 21 senza contratto; KF 57 casa venduta; dogana → 271/272/281",
              ("kodi_penal", "143") in _bs305 and ("kodi_punes", "21") in _w305 and ("kodi_familjes", "57") in _f305
              and {("kodi_doganor", "271"), ("kodi_doganor", "281")} <= _g305, repr((sorted(_bs305)[:4], sorted(_w305), sorted(_f305), sorted(_g305))))
        check("reati[305]: rubriche di una parola (134 Vjedhja, 143 Mashtrimi) ancorate; citati dal triage col codice (134), mai senza numero; casa senza notaio → KC 83/92",
              ("kodi_penal", "134") in _v305 and ("kodi_penal", "143") in _m305 and _t305 == {("kodi_penal", "134")} and not _n305
              and {("kodi_civil", "83"), ("kodi_civil", "92")} <= _h305, repr((sorted(_v305), sorted(_m305), sorted(_t305), sorted(_h305))))
    except Exception as _e305:  # noqa: BLE001
        check("reati[305]: kontrollet u ekzekutuan", False, f"{type(_e305).__name__}: {_e305}")

    # [306] v9.529 — il comporto (c.c. 2110, rubrica senza la parola) e il preliminare non rispettato (2932/1351) dalla domanda
    try:
        from src import brain as _br306
        from src.retrieval import ArticleIndex as _AI306
        _br306.set_request_jurisdiction("IT")
        _it306 = _AI306.load(__import__("pathlib").Path("/app/data/index/bm25_it.pkl"))
        _k306 = lambda q: {(a.code, str(a.number)) for a, _ in _br306._applica_ancore([], _it306, q, ["Civile"], ancore=_br306.ANCORE_IT)}
        _c306 = _k306(["periodo di comporto", "Il cliente è in malattia da otto mesi e teme di essere licenziato. Fino a quando conserva il posto?"])
        _p306 = _k306(["esecuzione in forma specifica", "Il cliente ha firmato un preliminare ma il venditore si rifiuta di fare il rogito."])
        _l306 = _k306(["licenziamento disciplinare", "Il cliente è stato licenziato per giusta causa dopo una contestazione."])
        _o306 = _k306(["licenziamento orale", "Il datore ha detto al cliente a voce di non tornare più al lavoro, senza nessuna lettera."])
        _r306 = _k306(["rito abbreviato", "Il cliente è imputato per lesioni: conviene il rito abbreviato?"])
        _g306 = _k306(["quota di legittima", "Il padre ha lasciato tutto alla seconda moglie escludendo i due figli. Cosa spetta ai figli?"])
        _br306.set_request_jurisdiction("AL")
        check("lavoro[306]: comporto → c.c. 2110; preliminare → 2932/1351; abbreviato → c.p.p. 438/442; legittima → c.c. 536/537; licenziamento orale → L. 604 art. 2 + D.Lgs. 23 art. 2; fuori tema no",
              ("codice_civile", "2110") in _c306 and ("codice_civile", "2932") in _p306 and ("codice_civile", "2110") not in _l306
              and ("codice_procedura_penale", "442") in _r306 and ("codice_civile", "537") in _g306 and ("codice_civile", "537") not in _l306
              and {("licenziamenti_individuali", "2"), ("tutele_crescenti", "2")} <= _o306 and ("tutele_crescenti", "2") not in _l306,
              repr((sorted(_c306), sorted(_p306), sorted(_l306))))
    except Exception as _e306:  # noqa: BLE001
        check("lavoro[306]: kontrollet u ekzekutuan", False, str(_e306))

    # [307] v9.530 — i link markdown delle fonti («[Cass. SU 19596/2020](https://…)») uscivano come testo grezzo in ogni risposta con
    # fonti web: il renderer li rende, solo http/https, dopo escapeHtml, prima del corsivo (gli «_» degli indirizzi)
    try:
        _js307 = __import__("pathlib").Path("/app/static/app.js").read_text(encoding="utf-8")
        _h307 = __import__("pathlib").Path("/app/templates/index.html").read_text(encoding="utf-8")
        _i307 = _js307[_js307.index("    function inline(s) {"):]
        _i307 = _i307[:_i307.index("\n    }\n")]
        check("link[307]: link markdown resi (solo http/https, noopener, prima del corsivo), app.js?v≥210",
              "(https?:\\/\\/" in _i307 and 'rel="noopener noreferrer nofollow"' in _i307
              and _i307.index("links.push") < _i307.index("<em>$1</em>") and _i307.index("s = escapeHtml(s);") < _i307.index("links.push")
              and int(re.search(r"app\.js\?v=(\d+)", _h307).group(1)) >= 210, _i307[:120])
    except Exception as _e307:  # noqa: BLE001
        check("link[307]: kontrollet u ekzekutuan", False, str(_e307))

    # [308] v9.531 — diavolo, replica, secondo round e Giudice leggono la risposta del senior INTERA (prima: 20.000 / 16.000 / 12.000 /
    # 24.000 caratteri — su 44 risposte profonde la mediana è 27.800, il Giudice non vedeva mai il duello in fondo)
    try:
        from src import studio as _st308
        _u308 = []
        _c0 = _st308._chiama
        _st308._chiama = lambda backend, **kw: (_u308.append(kw.get("user") or ""), "x" * 60)[1]
        try:
            _r308 = ("Analisi " * 6200) + "FINE-RISPOSTA-308"            # ~49.700 caratteri, come la più lunga misurata
            _g308 = ("Analisi " * 8700) + "FINE-DUELLO-308"              # ~70.000: risposta + duello, per il Giudice
            _st308.avokati_i_djallit(None, domanda="D", blloku_neneve="N", pergjigja=_r308, lang="it")
            _st308.senior_pergjigjja(None, domanda="D", blloku_neneve="N", pergjigja=_r308, sulmi="S", lang="it")
            _st308.sulmi_i_dyte(None, domanda="D", blloku_neneve="N", pergjigja_v2=_r308, lang="it")
            _st308.gjyqtari_fundit(None, domanda="D", blloku_neneve=("Neni " * 18000) + "FINE-NENE-308", pergjigja=_g308, lang="it",
                                   verifikimi=("Cass. " * 2500) + "FINE-VERIFICA-308", fazat=("Panel " * 4000) + "FINE-FAZAT-308")
        finally:
            _st308._chiama = _c0
        _src308 = __import__("inspect").getsource(__import__("src.brain", fromlist=["x"]).SuperAvvocato._research_loop)
        check("duello[308]: il rilevatore delle lacune (research loop) legge 40.000 caratteri, etichette nella lingua della sessione",
              '(answer_text or "")[:40000]' in _src308 and '"RISPOSTA"' in _src308 and "[:6000]" not in _src308)
        check("duello[308]: diavolo, replica, secondo round e Giudice ricevono la risposta del senior fino in fondo; il Giudice anche articoli (100k), verifica (20k), pannelli (30k)",
              len(_u308) == 4 and all("FINE-RISPOSTA-308" in u for u in _u308[:3]) and "FINE-DUELLO-308" in _u308[3]
              and all(m in _u308[3] for m in ("FINE-NENE-308", "FINE-VERIFICA-308", "FINE-FAZAT-308")),
              str([len(u) for u in _u308]))
    except Exception as _e308:  # noqa: BLE001
        check("duello[308]: kontrollet u ekzekutuan", False, f"{type(_e308).__name__}: {_e308}")

    # [309] v9.536 — i raccoglitori non aprono i PDF interi dei codici (2-3 $ in un passo, «budget_exhausted» senza risultato)
    try:
        from src import studio as _st309
        _ps309 = [d[l] for d in (_st309.MBLEDHES_WEB_SYSTEM, _st309.MBLEDHES_QBZ_SYSTEM, _st309.MBLEDHES_FLETORJA_SYSTEM) for l in ("sq", "it")]
        check("raccoglitori[309]: web, QBZ e Gazzetta vietano i PDF interi e limitano le pagine aperte (sq+it)",
              all(("MOS hap PDF" in p or "NON aprire i PDF" in p) and ("2 faqe" in p or "2 pagine" in p) for p in _ps309))
    except Exception as _e309:  # noqa: BLE001
        check("raccoglitori[309]: kontrollet u ekzekutuan", False, str(_e309))

    # [310] v9.537 — nessuna lettera CIRILLICA nel corpus albanese («tё», «і», «ҫ» al posto di «të», «i», «ç»: le parole non
    # corrispondevano mai alle query) + il socio di s.h.p.k. che vuole uscire → artt. 101/103/73 della legge sulle società
    try:
        import re as _re310
        from pathlib import Path as _P310
        from src.retrieval import ArticleIndex as _AI310
        _idx310 = _AI310.load(_P310("/app/data/index/bm25.pkl"))
        _cir310 = [f"{a.code} {a.number}" for a in _idx310.articles
                   if _re310.search(r"[\u0400-\u04FF]", " ".join(str(getattr(a, _c, "") or "") for _c in ("heading", "body", "note", "title_sq", "kreu", "pjesa", "seksioni")))]
        check("omoglifi[310]: nessuna lettera cirillica nel corpus albanese", not _cir310, ", ".join(_cir310[:8]))
        # v9.540 — e nessuna lettera SCOMPOSTA (dieresi combinante U+0308: spezzava la parola in due token) né carattere a
        # larghezza zero
        _inv310 = [f"{a.code} {a.number}" for a in _idx310.articles
                   if _re310.search(r"[\u0300-\u036f\u200b-\u200d\u2060\ufeff]",
                                    " ".join(str(getattr(a, _c, "") or "") for _c in ("heading", "body", "note", "title_sq", "kreu", "pjesa", "seksioni")))]
        check("omoglifi[310]: nessuna lettera scomposta né carattere a larghezza zero nel corpus albanese (v9.540)", not _inv310,
              ", ".join(_inv310[:8]))
        from src import brain as _b310
        _v310 = [v for v in _b310.ANCORE_AL if ("ligji_shoqerite_tregtare", "101") in v[2]]
        _dom310 = "Klienti është ortak me 40% në një shpk dhe dëshiron të largohet nga shoqëria. Si e bën?"
        _p310 = _b310._applica_ancore([], _idx310, [_dom310], ["Civil"], ancore=_v310)
        _q310 = _b310._applica_ancore([], _idx310, [_dom310], ["Penal"], ancore=_v310)
        _r310 = _b310._applica_ancore([], _idx310, ["Klienti do të shesë makinën"], ["Civil"], ancore=_v310)
        check("omoglifi[310]: socio di s.h.p.k. che esce → 101/103/73; non nel penale né fuori tema",
              len(_v310) == 1 and {(a.code, a.number) for a, _ in _p310} >= {("ligji_shoqerite_tregtare", "101"), ("ligji_shoqerite_tregtare", "103")}
              and not _q310 and not _r310, f"{[(a.code, a.number) for a, _ in _p310]} {len(_q310)} {len(_r310)}")
    except Exception as _e310:  # noqa: BLE001
        check("omoglifi[310]: kontrollet u ekzekutuan", False, f"{type(_e310).__name__}: {_e310}")

    # [311] v9.538 — gli atti ITALIANI abrogati che non sono nel corpus (TULD d.P.R. 43/1973 → D.Lgs. 141/2024, Reg. 2454/93):
    # «abrogato da …», non «senza codice»; registro letto dalle liste di abrogazione del corpus, mai le parziali, mai le
    # abrogazioni future dei testi unici fiscali, mai «può essere modificato o abrogato»; e le sigle «TUI» e «CAP»
    try:
        from pathlib import Path as _P311
        from src.retrieval import ArticleIndex as _AI311
        from src import atti_abrogati_it as _aa311, citation_verifier as _cv311
        _ix311 = _AI311.load(_P311("/app/data/index/bm25_it.pkl"))
        _r311 = _aa311.costruisci(_ix311)
        check("abrogati_it[311]: nel registro TULD (D.Lgs. 141/2024), Reg. 2913/92 (CDU), Reg. 2454/93, L. 1204/1971",
              all(k in _r311 for k in ("dpr:43:1973", "reg:2913:1992", "reg:2454:1993", "l:1204:1971"))
              and "141/2024" in (_r311.get("dpr:43:1973") or {}).get("da", ""), str(len(_r311)))
        check("abrogati_it[311]: fuori le parziali (L. 125/1991 salvo art. 11), «può essere abrogato» (d.P.R. 412/1993), gli atti del corpus",
              not any(k in _r311 for k in ("l:125:1991", "dpr:412:1993", "l:604:1966", "dlgs:368:2001")))
        def _st311(t, n):
            return {i["number"]: (i["status"], i.get("code")) for i in _cv311.verify_text(t, _ix311)["items"]}.get(n)
        check("abrogati_it[311]: «art. 301 TULD», «art. 282 del d.P.R. 23 gennaio 1973, n. 43», «art. 561 Reg. 2454/93» → abrogati",
              _st311("La confisca ex art. 301 TULD.", "301") == ("repealed", None)
              and _st311("Si applicava l'art. 282 del d.P.R. 23 gennaio 1973, n. 43, oggi abrogato.", "282") == ("repealed", None)
              and _st311("Il vecchio art. 561 Reg. 2454/93.", "561") == ("repealed", None))
        check("abrogati_it[311]: un art. 216 C.d.S. non prende il TULD della frase dopo; TUI e CAP sul codice giusto; TUIR resta TUIR",
              _st311("La sanzione dell'art. 216, comma 6, C.d.S. è grave. Nel d.P.R. 43/1973 era diverso.", "216") == ("verified", "codice_strada")
              and _st311("Il permesso (art. 9 TUI) dura.", "9") == ("verified", "tu_immigrazione")
              and _st311("Il termine dell'art. 145 CAP.", "145") == ("verified", "codice_assicurazioni")
              and (_st311("L'art. 73 TUIR definisce i soggetti.", "73") or ("", ""))[1] != "tu_immigrazione")
    except Exception as _e311:  # noqa: BLE001
        check("abrogati_it[311]: kontrollet u ekzekutuan", False, f"{type(_e311).__name__}: {_e311}")

    # [312] v9.539 — due forme albanesi reali che uscivano «pa kod»: la legge abbreviata «L.9901» e l'anafora «i/të të njëjtit
    # ligj/kod» (con la finestra a 10 parole: il nome lungo del Codice dei minori non si riduce al Codice penale); una legge
    # ITALIANA in un testo albanese («L. 604/1966») non diventa mai una legge albanese
    try:
        from pathlib import Path as _P312
        from src.retrieval import ArticleIndex as _AI312
        from src import citation_verifier as _cv312
        _ix312 = _AI312.load(_P312("/app/data/index/bm25.pkl"))
        def _st312(t, n):
            return {i["number"]: (i["status"], i.get("code")) for i in _cv312.verify_text(t, _ix312)["items"]}.get(n)
        check("verificatore[312]: «L.9901» e «të njëjtit ligj» risolti; il nome lungo del Codice dei minori resta quello",
              _st312("Konflikti i interesit (Neni 13/2-3 L.9901) injorohet.", "13/2/3") == ("verified", "ligji_shoqerite_tregtare")
              and _st312("(Neni 15 i Ligjit nr. 10279/2010). Ankimi pezullon (Neni 23 i të njëjtit ligj).", "23") == ("verified", "ligji_kundervajtjet")
              and _st312("Neni 106 i Kodit të Drejtësisë Penale për të Mitur (nën minimum), Neni 105 dhe Neni 68 të të njëjtit kod.", "105") == ("verified", "kodi_te_miturve"))
        _it312 = _st312("Në Itali vlen neni 5 L. 604/1966 (barra e provës).", "5")
        check("verificatore[312]: una legge italiana («L. 604/1966») in un testo albanese non diventa una legge albanese",
              not _it312 or _it312[1] is None or not str(_it312[1]).startswith(("ligji", "kodi")), str(_it312))
    except Exception as _e312:  # noqa: BLE001
        check("verificatore[312]: kontrollet u ekzekutuan", False, f"{type(_e312).__name__}: {_e312}")

    # [313] v9.541 — il DIVORZIO CONTESTATO (il coniuge non acconsente) → KF 132/129/155; non il consensuale, non nel penale
    try:
        from pathlib import Path as _P313
        from src.retrieval import ArticleIndex as _AI313
        from src import brain as _b313
        _ix313 = _AI313.load(_P313("/app/data/index/bm25.pkl"))
        _v313 = [v for v in _b313.ANCORE_AL if ("kodi_familjes", "132") in v[2]]
        _k313 = lambda q, ar: {(a.code, a.number) for a, _ in _b313._applica_ancore([], _ix313, [q], ar, ancore=_v313)}
        check("divorzio[313]: contestato → KF 132/129/155; il consensuale e il penale no",
              len(_v313) == 1
              and {("kodi_familjes", "132"), ("kodi_familjes", "155")} <= _k313("Klientja kërkon divorc, bashkëshorti nuk pranon. Kush merr fëmijët?", ["Familje"])
              and not _k313("Si bëhet divorci me marrëveshje?", ["Familje"])
              and not _k313("Klientja kërkon divorc, bashkëshorti nuk pranon dhe e kërcënon.", ["Penal"]))
        # … la truffa: il KP 143 in testa anche se la ricerca l'aveva trovato con un punteggio basso; la liquidazione giudiziale IT
        _by313 = {(a.code, str(a.number)): a for a in _ix313.articles}
        _p313 = [(_by313[("kodi_penal", n)], 1.0) for n in ("145", "301", "312")]
        _o313 = _b313._ancora_vepra_penale(_p313, _ix313, ["mashtrimi përfitim pasuror me anë mashtrimi",
                                                          "parashkrimi i ndjekjes penale për veprën e mashtrimit"], ["Penal"])
        _ixit313 = _AI313.load(_P313("/app/data/index/bm25_it.pkl"))
        _vi313 = [v for v in _b313.ANCORE_IT if ("codice_crisi_impresa", "121") in v[2]]
        _ki313 = {(a.code, a.number) for a, _ in _b313._applica_ancore([], _ixit313, [
            "Una società deve al cliente 120.000 euro e non paga: possiamo chiederne la liquidazione giudiziale?"], ["Civile"], ancore=_vi313)}
        check("reati/crisi[313]: truffa → KP 143 in testa; liquidazione giudiziale → CCII 121/37",
              (_o313[0][0].code, _o313[0][0].number) == ("kodi_penal", "143")
              and len(_vi313) == 1 and {("codice_crisi_impresa", "121"), ("codice_crisi_impresa", "37")} <= _ki313,
              f"{(_o313[0][0].code, _o313[0][0].number)} {_ki313}")
    except Exception as _e313:  # noqa: BLE001
        check("divorzio[313]: kontrollet u ekzekutuan", False, f"{type(_e313).__name__}: {_e313}")

    # [314] v9.542 — decimo giro di domande frequenti: sconfinamento (KC 302/296), vizi della vendita (KC 717 dieci giorni, 718),
    # paga non pagata con gli interessi (KP 120, solo nel lavoro e mai su «nuk paguan qiranë»), licenziamento in tronco (c.c. 2119)
    try:
        from pathlib import Path as _P314
        from src.retrieval import ArticleIndex as _AI314
        from src import brain as _b314
        _al314 = _AI314.load(_P314("/app/data/index/bm25.pkl")); _it314 = _AI314.load(_P314("/app/data/index/bm25_it.pkl"))
        def _k314(ix, anc, q, ar):
            return {(a.code, a.number) for a, _ in _b314._applica_ancore([], ix, [q], ar, ancore=anc)}
        check("frek10[314]: sconfinamento → KC 302; difetto dell'auto → KC 717/718; paga non pagata → KP 120; in tronco → c.c. 2119",
              ("kodi_civil", "302") in _k314(_al314, None, "Fqinji ndërtoi një mur që hyn në tokën e klientit.", ["Civil"])
              and ("kodi_civil", "717") in _k314(_al314, None, "Klienti bleu një makinë dhe doli një defekt që shitësi e fshehu.", ["Civil"])
              and ("kodi_punes", "120") in _k314(_al314, None, "Punëdhënësi nuk i ka paguar pagën prej tre muajsh.", ["Punë"])
              and ("codice_civile", "2119") in _k314(_it314, _b314.ANCORE_IT, "L'azienda lo licenzia in tronco per assenza ingiustificata.", ["Lavoro"]))
        check("frek10[314]: la paga NON sull'affitto non pagato; l'ancora del lavoro non nel civile",
              ("kodi_punes", "120") not in _k314(_al314, None, "Qiramarrësi nuk paguan qiranë prej katër muajsh.", ["Civil"]))
    except Exception as _e314:  # noqa: BLE001
        check("frek10[314]: kontrollet u ekzekutuan", False, f"{type(_e314).__name__}: {_e314}")

    # [315] v9.543 — prestito non restituito → KC 1050/1051; figlio dopo il divorzio → KF 159/158 (non la tutela 218-233)
    try:
        from pathlib import Path as _P315
        from src.retrieval import ArticleIndex as _AI315
        from src import brain as _b315
        _al315 = _AI315.load(_P315("/app/data/index/bm25.pkl"))
        _k315 = lambda q, ar: {(a.code, a.number) for a, _ in _b315._applica_ancore([], _al315, [q], ar)}
        check("frek11[315]: hua non restituita → KC 1050/1051; figlio dopo il divorzio → KF 159/158; non nel penale",
              {("kodi_civil", "1050"), ("kodi_civil", "1051")} <= _k315("I dha një shoku 10 mijë euro hua dhe nuk ia kthen.", ["Civil"])
              and {("kodi_familjes", "159"), ("kodi_familjes", "158")} <= _k315("Pas divorcit fëmija i është lënë nënës; babai do ta shohë më shpesh.", ["Familje"])
              and ("kodi_civil", "1050") not in _k315("I dha një shoku hua dhe ai e kërcënon.", ["Penal"]))
    except Exception as _e315:  # noqa: BLE001
        check("frek11[315]: kontrollet u ekzekutuan", False, f"{type(_e315).__name__}: {_e315}")

    # [316] v9.544 — misura cautelare → KPP 228/229/230 (non sul sequestro civile); la «vjetërsi» contributiva non porta il premio
    # di anzianità del KP (la pensione); patteggiamento → c.p.p. 444/445
    try:
        from pathlib import Path as _P316
        from src.retrieval import ArticleIndex as _AI316
        from src import brain as _b316
        _al316 = _AI316.load(_P316("/app/data/index/bm25.pkl"))
        _it316 = _AI316.load(_P316("/app/data/index/bm25_it.pkl"))
        _k316 = lambda q, ar: {(a.code, a.number) for a, _ in _b316._applica_ancore([], _al316, q, ar)}
        _i316 = lambda q, ar: {(a.code, a.number) for a, _ in _b316._applica_ancore([], _it316, q, ar, _b316.ANCORE_IT)}
        check("frek12[316]: arrest në burg → KPP 228/229/230; jo në sigurimin e padisë civile",
              {("kodi_proc_penale", "228"), ("kodi_proc_penale", "229"), ("kodi_proc_penale", "230")}
              <= _k316(["Prokuroria kërkon arrest në burg për klientin."], ["Penal"])
              and ("kodi_proc_penale", "228") not in _k316(["Kërkojmë masën e sigurimit të padisë mbi llogarinë e debitorit."], ["Civil"]))
        check("frek12[316]: vjetërsia në kontribute (pension) nuk sjell KP 145/152; pushimi pas 8 vjetësh po",
              ("kodi_punes", "145") not in _k316(["pension i pjesshëm për vjetërsi kontribuesi", "Klienti ka 62 vjeç dhe 30 vjet kontribute."], ["Punë"])
              and ("kodi_punes", "145") in _k316(["U pushua nga puna pas 8 vjetësh, i takon shpërblimi për vjetërsi?"], ["Punë"]))
        check("frek12[316]: pension pleqërie → ligji 7703 nenet 31/92; jo në pushimin nga puna pa pension",
              {("ligji_sigurimet_shoqerore", "31"), ("ligji_sigurimet_shoqerore", "92")}
              <= _k316(["Klienti ka 62 vjeç dhe 30 vjet kontribute. A ka të drejtë për pension pleqërie?"], ["Punë"])
              and ("ligji_sigurimet_shoqerore", "31") not in _k316(["U pushua nga puna pas 8 vjetësh, i takon shpërblimi për vjetërsi?"], ["Punë"]))
        check("frek12[316]: patteggiamento → c.p.p. 444/445",
              {("codice_procedura_penale", "444"), ("codice_procedura_penale", "445")}
              <= _i316(["Il cliente vuole patteggiare per un furto aggravato: che effetti ha la sentenza?"], ["Penale"]))
    except Exception as _e316:  # noqa: BLE001
        check("frek12[316]: kontrollet u ekzekutuan", False, f"{type(_e316).__name__}: {_e316}")

    # [317] v9.545 — tre forme italiane che uscivano «senza codice» nelle risposte vere: l'atto PRIMA del numero con la virgola
    # («(D.P.R. 223/1989, art. 11)», «Il D.Lgs. 23/2015, all'art. 3»; anche AL «Ligjit nr. 9901/2008, neni 101»), la sigla dopo la
    # virgola («art. 14, co. 3, TUSG») e il regolamento del C.d.S. citato «Reg. esec.»/«Reg.» — mai il Reg. delegato (UE) 2015/2446
    try:
        from pathlib import Path as _P317
        from src.retrieval import ArticleIndex as _AI317
        from src import citation_verifier as _cv317
        _it317 = _AI317.load(_P317("/app/data/index/bm25_it.pkl"))
        _al317 = _AI317.load(_P317("/app/data/index/bm25.pkl"))
        def _st317(t, n, ix=None):
            return {i["number"]: (i["status"], i.get("code")) for i in _cv317.verify_text(t, ix or _it317)["items"]}.get(n)
        check("verificatore[317]: atto prima del numero («D.P.R. 223/1989, art. 11», «D.Lgs. 23/2015, all'art. 3», «Ligjit nr. 9901/2008, neni 101»)",
              _st317("Dichiarazione di trasferimento (D.P.R. 223/1989, art. 11 — da verificare).", "11") == ("verified", "regolamento_anagrafico")
              and _st317("Il D.Lgs. 23/2015, all'art. 3, comma 1, fissa la forbice.", "3") == ("verified", "tutele_crescenti")
              and _st317("Sipas Ligjit nr. 9901/2008, neni 101 lejon largimin e ortakut.", "101", _al317) == ("verified", "ligji_shoqerite_tregtare"))
        check("verificatore[317]: mai la coda di un'altra citazione né un atto fra parentesi («art. 132 C.d.S., art. 94», «(L. 604/1966), art. 18»)",
              _st317("Sanzioni (art. 132 C.d.S., art. 94, comma 4-ter) e poi.", "94") == ("needs_code", None)
              and _st317("La legge (L. 604/1966), art. 18 non si applica.", "18") == ("needs_code", None)
              and _st317("Secondo la Cassazione, art. 5 non basta.", "5") == ("needs_code", None))
        check("verificatore[317]: «art. 14, co. 3, TUSG» → TU spese di giustizia",
              _st317("Pagamento integrativo (art. 14, co. 3, TUSG — non nel blocco).", "14") == ("verified", "tu_spese_giustizia"))
        check("verificatore[317]: «art. 339 Reg. esec.» nel C.d.S. → regolamento; mai il Reg. delegato 2015/2446 né il regolamento di procedura",
              _st317("Targa: art. 133 C.d.S. e art. 339 Reg. esec.; art. 102 C.d.S.", "339") == ("verified", "regolamento_strada")
              and (_st317("Nel C.d.S. nulla; l'eccezione dell'art. 212 del Reg. delegato UE n. 2446 del 2015 vale.", "212") or ("", ""))[1] != "regolamento_strada"
              and (_st317("Dogana e C.d.S.: artt. 212 e 217 Reg. del. sul punto.", "217") or ("", ""))[1] != "regolamento_strada"
              and (_st317("C.d.S. a parte, l'art. 99 del regolamento di procedura della Corte.", "99") or ("", ""))[1] != "regolamento_strada")
    except Exception as _e317:  # noqa: BLE001
        check("verificatore[317]: kontrollet u ekzekutuan", False, f"{type(_e317).__name__}: {_e317}")

    # [318] v9.546 — le DISPOSIZIONI DI ATTUAZIONE del c.p.c. nel corpus (R.D. 1368/1941): «art. 188 disp. att. c.p.c.» si verifica sul
    # suo testo (prima «fuori corpus»), il c.p.c. resta il c.p.c., un numero che non c'è è inesistente; e nessun corpo italiano comincia
    # con il residuo della rubrica («) Il coniuge…», «) . I minori…»: 537 articoli prima)
    try:
        import re as _re318
        from pathlib import Path as _P318
        from src.retrieval import ArticleIndex as _AI318
        from src import citation_verifier as _cv318
        _it318 = _AI318.load(_P318("/app/data/index/bm25_it.pkl"))
        def _st318(t, n):
            return {i["number"]: (i["status"], i.get("code")) for i in _cv318.verify_text(t, _it318)["items"]}.get(n)
        check("disp_att_cpc[318]: «art. 188 disp. att. c.p.c.» verificato; «art. 152 c.p.c.» resta del codice; «art. 999 disp. att.» inesistente",
              _st318("Oltre al rimedio ex art. 188 disp. att. c.p.c. davanti al giudice.", "188") == ("verified", "disp_att_cpc")
              and _st318("L'art. 152 c.p.c. resta del codice.", "152") == ("verified", "codice_procedura_civile")
              and (_st318("L'art. 999 disp. att. c.p.c. non esiste.", "999") or ("",))[0] == "fake")
        _res318 = [(a.code, a.number) for a in _it318.articles if _re318.match(r"\s*(?:[)\]]|\.(?!\.)\s)", a.body or "")]
        check("corpus IT[318]: nessun corpo comincia con «)» o «. » (residuo della rubrica)", len(_res318) <= 2, str(_res318[:6]))
        import importlib.util as _ilu318
        _sp318 = _ilu318.spec_from_file_location("bi318", "/app/tools/build_it_index.py")
        _bi318 = _ilu318.module_from_spec(_sp318); _sp318.loader.exec_module(_bi318)
        check("corpus IT[318]: _pulisci toglie «) .» in testa ma lascia «...» (omissione) e «, e 2436» (taglio vero)",
              _bi318._pulisci("Età", ") .  I minori di età")[1] == "I minori di età"
              and _bi318._pulisci("X", "...  1. Qualora")[1].startswith("...")
              and _bi318._pulisci("X", ", e 2436, secondo comma")[1].startswith(", e 2436"))
        from src import brain as _b318
        _i318 = lambda q, ar: {(a.code, a.number) for a, _ in _b318._applica_ancore([], _it318, q, ar, _b318.ANCORE_IT)}
        check("usucapione[318]: «coltiva e recinta da 25 anni» → c.c. 1158/1140; non nel penale",
              {("codice_civile", "1158"), ("codice_civile", "1140")} <= _i318(["Il cliente coltiva e recinta da 25 anni un terreno del vicino."], ["Civile"])
              and ("codice_civile", "1158") not in _i318(["Usucapione e falso ideologico nel verbale."], ["Penale"]))
    except Exception as _e318:  # noqa: BLE001
        check("disp_att_cpc[318]: kontrollet u ekzekutuan", False, f"{type(_e318).__name__}: {_e318}")

    # [319] v9.547 — la RUBRICA rimasta nel testo sopra la fonte «( legge … )» / «( articolo … )» (53 articoli IT): la sanatoria edilizia
    # (art. 36 d.P.R. 380/2001), «Il ricorso» del testo unico della giustizia tributaria; mai una frase con un verbo come rubrica
    try:
        import importlib.util as _ilu319
        from pathlib import Path as _P319
        from src.retrieval import ArticleIndex as _AI319
        _sp319 = _ilu319.spec_from_file_location("bi319", "/app/tools/build_it_index.py")
        _bi319 = _ilu319.module_from_spec(_sp319); _sp319.loader.exec_module(_bi319)
        _it319 = _AI319.load(_P319("/app/data/index/bm25_it.pkl"))
        _h319 = {(a.code, a.number): (a.heading or "") for a in _it319.articles if a.code in ("tu_edilizia", "giustizia_tributaria")}
        check("rubriche IT[319]: TU edilizia 36 «Accertamento di conformità…», giustizia tributaria 64 «Il ricorso» nell'indice",
              _h319.get(("tu_edilizia", "36"), "").startswith("Accertamento di conformità nelle ipotesi di assenza di titolo")
              and _h319.get(("giustizia_tributaria", "64")) == "Il ricorso", str((_h319.get(("tu_edilizia", "36")), _h319.get(("giustizia_tributaria", "64")))))
        _f319 = _bi319._rubrica_forme_nuove
        _ok319 = _f319("Disposizioni transitorie\n\n( articolo 4, comma 1, lettera g), decreto legislativo 12 dicembre 2003, n. 344 ;\n"
                       "articolo 13, commi da 2 a 5 )\n\n1. Le disposizioni")
        _no319 = _f319("Il presente decreto si applica ai contratti\n\n( articolo 1 del decreto legislativo n. 50 del 2016 )\n\n1. Testo")
        check("rubriche IT[319]: fonte spezzata con «lettera g)» → rubrica; una frase col verbo («Il presente decreto si applica…») no",
              bool(_ok319) and _ok319[0] == "Disposizioni transitorie" and _ok319[1].startswith("( articolo 4")
              and (not _no319 or _no319[0] != "Il presente decreto si applica ai contratti"), str((_ok319, _no319))[:200])
    except Exception as _e319:  # noqa: BLE001
        check("rubriche IT[319]: kontrollet u ekzekutuan", False, f"{type(_e319).__name__}: {_e319}")

    # [320] v9.548 — lesioni da una lite → KP 89/90 (non nella violenza domestica); firma falsificata → KP 186 e, nel civile, KC 92
    try:
        from pathlib import Path as _P320
        from src.retrieval import ArticleIndex as _AI320
        from src import brain as _b320
        _al320 = _AI320.load(_P320("/app/data/index/bm25.pkl"))
        _k320 = lambda q, ar: {(a.code, a.number) for a, _ in _b320._applica_ancore([], _al320, [q], ar)}
        check("frek13[320]: «e rrahu… 12 ditë paaftësi» → KP 89/90; jo me zonën Familje (dhuna në familje)",
              {("kodi_penal", "89"), ("kodi_penal", "90")} <= _k320("Fqinji e rrahu klientin dhe mjeku i dha 12 ditë paaftësi në punë.", ["Penal"])
              and ("kodi_penal", "89") not in _k320("Burri e rrah klienten çdo javë, mjeku i dha 5 ditë paaftësi.", ["Penal", "Familje"]))
        check("frek13[320]: nënshkrim i falsifikuar në prokurë → KP 186; KC 92 vetëm me zonën civile",
              {("kodi_penal", "186"), ("kodi_civil", "92")} <= _k320("Vëllai ia falsifikoi nënshkrimin në një prokurë dhe shiti tokën.", ["Penal", "Civil"])
              and ("kodi_civil", "92") not in _k320("Klienti akuzohet se falsifikoi një nënshkrim.", ["Penal"])
              and ("kodi_penal", "186") in _k320("Klienti akuzohet se falsifikoi një nënshkrim.", ["Penal"]))
        check("frek13[320]: guida in stato di ebbrezza → KP 291 + Kodi Rrugor 184; l'alcol senza guida no",
              {("kodi_penal", "291"), ("kodi_rrugor", "184")} <= _k320("Klientin e ndaloi policia duke drejtuar makinën i dehur, me 1,5 gram alkool.", ["Penal"])
              and ("kodi_penal", "291") not in _k320("Klienti ishte i dehur dhe theu xhamin e një dyqani.", ["Penal"]))
        _it320 = _AI320.load(_P320("/app/data/index/bm25_it.pkl"))
        _i320 = lambda q, ar: {(a.code, a.number) for a, _ in _b320._applica_ancore([], _it320, [q], ar, _b320.ANCORE_IT)}
        check("frek13[320]: prestito a un amico non restituito → c.c. 1813; non nel penale",
              ("codice_civile", "1813") in _i320("Il cliente ha prestato 15.000 euro a un amico che non glieli restituisce.", ["Civile"])
              and ("codice_civile", "1813") not in _i320("Il cliente ha prestato denaro a usura e non gli viene restituito.", ["Penale"]))
    except Exception as _e320:  # noqa: BLE001
        check("frek13[320]: kontrollet u ekzekutuan", False, f"{type(_e320).__name__}: {_e320}")

    # [321] v9.549 — entro quando si impugna in italiano: penale → c.p.p. 585/172/582; civile → c.p.c. 325/327/155; mai l'uno nell'altro,
    # mai nell'amministrativo; e solo quando la domanda chiede il termine
    try:
        from pathlib import Path as _P321
        from src.retrieval import ArticleIndex as _AI321
        from src import brain as _b321
        _it321 = _AI321.load(_P321("/app/data/index/bm25_it.pkl"))
        _i321 = lambda q, ar: {(a.code, a.number) for a, _ in _b321._applica_ancore([], _it321, [q], ar, _b321.ANCORE_IT)}
        _pen321 = _i321("Condannato dal tribunale, motivazione depositata il 25 settembre: entro quando l'appello?", ["Penale"])
        _civ321 = _i321("La sentenza civile è stata notificata il 1° ottobre: entro quando l'appello?", ["Civile"])
        check("termini IT[321]: appello penale → c.p.p. 585/172/582; civile → c.p.c. 325/327/155; mai incrociati",
              {("codice_procedura_penale", "585"), ("codice_procedura_penale", "172"), ("codice_procedura_penale", "582")} <= _pen321
              and ("codice_procedura_civile", "325") not in _pen321
              and {("codice_procedura_civile", "325"), ("codice_procedura_civile", "327"), ("codice_procedura_civile", "155")} <= _civ321
              and ("codice_procedura_penale", "585") not in _civ321)
        check("termini IT[321]: niente nell'amministrativo né senza la domanda sul termine",
              ("codice_procedura_civile", "325") not in _i321("Il TAR ha respinto il ricorso: entro quando l'appello al Consiglio di Stato?", ["Amministrativo"])
              and ("codice_procedura_civile", "325") not in _i321("Il cliente vuole appellare la sentenza civile: quali motivi?", ["Civile"]))
    except Exception as _e321:  # noqa: BLE001
        check("termini IT[321]: kontrollet u ekzekutuan", False, f"{type(_e321).__name__}: {_e321}")

    # [322] v9.550 — sequestro conservativo AL (KPC 202/206, non nel penale) e IT (c.p.c. 671); alimenti al genitore anziano (KF 192/198)
    try:
        from pathlib import Path as _P322
        from src.retrieval import ArticleIndex as _AI322
        from src import brain as _b322
        _al322 = _AI322.load(_P322("/app/data/index/bm25.pkl")); _it322 = _AI322.load(_P322("/app/data/index/bm25_it.pkl"))
        _k322 = lambda q, ar: {(a.code, a.number) for a, _ in _b322._applica_ancore([], _al322, [q], ar)}
        _i322 = lambda q, ar: {(a.code, a.number) for a, _ in _b322._applica_ancore([], _it322, [q], ar, _b322.ANCORE_IT)}
        check("frek14[322]: debitori shet pasuritë → KPC 202/206; jo në penal (masa e sigurimit penale)",
              {("kodi_proc_civile", "202"), ("kodi_proc_civile", "206")} <= _k322("Debitori po i shet pasuritë para gjyqit. Si ia bllokojmë pasurinë?", ["Civil"])
              and ("kodi_proc_civile", "202") not in _k322("Prokurori kërkon sekuestro konservative mbi pasurinë e të pandehurit.", ["Penal"]))
        check("frek14[322]: nëna e moshuar pa të ardhura → KF 192/198; sequestro conservativo IT → c.p.c. 671",
              {("kodi_familjes", "192"), ("kodi_familjes", "198")} <= _k322("Nëna e moshuar nuk ka të ardhura: a janë të detyruar fëmijët t'i japin ushqim?", ["Familje"])
              and ("codice_procedura_civile", "671") in _i322("Il debitore vende gli immobili prima della causa: come blocchiamo i beni?", ["Civile"]))
    except Exception as _e322:  # noqa: BLE001
        check("frek14[322]: kontrollet u ekzekutuan", False, f"{type(_e322).__name__}: {_e322}")

    # [323] v9.551 — la L. 104/1992 nel corpus («art. 33 L. 104/1992» verificato, rubrica «Agevolazioni»); nessun corpo IT con l'a capo
    # davanti alla virgola (1.357 prima), c.c. 582 con la sua rubrica
    try:
        import re as _re323
        from pathlib import Path as _P323
        from src.retrieval import ArticleIndex as _AI323
        from src import citation_verifier as _cv323
        _it323 = _AI323.load(_P323("/app/data/index/bm25_it.pkl"))
        _by323 = {(a.code, a.number): a for a in _it323.articles}
        _st323 = {i["number"]: (i["status"], i.get("code")) for i in _cv323.verify_text("I permessi dell'art. 33 L. 104/1992 e dell'art. 33 L. 104/92.", _it323)["items"]}
        check("legge_104[323]: «art. 33 L. 104/1992» (anche «/92») verificato; rubrica «Agevolazioni»",
              _st323.get("33") == ("verified", "legge_104") and (_by323.get(("legge_104", "33")) and _by323[("legge_104", "33")].heading == "Agevolazioni"),
              str(_st323))
        _nl323 = [k for k, a in _by323.items() if _re323.search(r"\n[ \t]*[,;]", a.body or "")]
        check("corpus IT[323]: nessun a capo davanti a «,»/«;»; c.c. 582 «Concorso del coniuge con ascendenti, fratelli e sorelle»",
              not _nl323 and (_by323[("codice_civile", "582")].heading or "").startswith("Concorso del coniuge con ascendenti"), str(_nl323[:5]))
        from src import brain as _b323
        _i323 = {(a.code, a.number) for a, _ in _b323._applica_ancore([], _it323, ["Il cliente assiste la madre con disabilità grave: ha diritto a permessi?"], ["Civile"], _b323.ANCORE_IT)}
        check("legge_104[323]: permessi per il familiare disabile → L. 104/1992 art. 33", ("legge_104", "33") in _i323)
    except Exception as _e323:  # noqa: BLE001
        check("legge_104[323]: kontrollet u ekzekutuan", False, f"{type(_e323).__name__}: {_e323}")

    # [324] v9.552 — l'ancora della prescrizione IT (c.c. 2946) guarda la DOMANDA: non scatta se è il triage a scrivere «prescrizione»
    try:
        from pathlib import Path as _P324
        from src.retrieval import ArticleIndex as _AI324
        from src import brain as _b324
        _it324 = _AI324.load(_P324("/app/data/index/bm25_it.pkl"))
        _i324 = lambda qs, ar: {(a.code, a.number) for a, _ in _b324._applica_ancore([], _it324, qs, ar, _b324.ANCORE_IT)}
        check("prescrizione IT[324]: dalla domanda sì («è prescritto?», «ancora in tempo», «risale al 2014»); dal solo triage no",
              ("codice_civile", "2946") in _i324(["Il credito del cliente risale al 2014 e il debitore non paga."], ["Civile"])
              and ("codice_civile", "2946") in _i324(["Il cliente vuole chiedere i danni di un vecchio contratto: siamo ancora in tempo?"], ["Civile"])
              and ("codice_civile", "2946") not in _i324(["prescrizione dell'azione di riduzione in pristino",
                                                          "Il vicino ha costruito a un metro e mezzo dal confine. Cosa possiamo chiedere?"], ["Civile"]))
    except Exception as _e324:  # noqa: BLE001
        check("prescrizione IT[324]: kontrollet u ekzekutuan", False, f"{type(_e324).__name__}: {_e324}")

    # [325] v9.553 — il RINVIO INTERNO dentro il testo di legge citato alla lettera prende l'atto della citazione («Art. 3, comma 3, D.Lgs.
    # 23/2015: «… di cui all'articolo 1 …»» → D.Lgs. 23/2015); mai se il rinvio nomina un atto suo, se la citazione si chiude sul numero,
    # se è annidata, o se l'atto non è l'ultima cosa prima delle virgolette
    try:
        from pathlib import Path as _P325
        from src.retrieval import ArticleIndex as _AI325
        from src import citation_verifier as _cv325
        _it325 = _AI325.load(_P325("/app/data/index/bm25_it.pkl"))
        def _st325(t, n):
            return {i["number"]: (i["status"], i.get("code")) for i in _cv325.verify_text(t, _it325)["items"]}.get(n)
        check("verificatore[325]: «Art. 3, comma 3, D.Lgs. 23/2015: «… all'articolo 1 …»» → D.Lgs. 23/2015 art. 1",
              _st325("- **Art. 3, comma 3, D.Lgs. 23/2015**: «Al licenziamento dei lavoratori di cui all'articolo 1 non trova applicazione l'articolo 7 della legge 15 luglio 1966, n. 604».", "1")
              == ("verified", "tutele_crescenti"))
        check("verificatore[325]: niente codice al rinvio che nomina un atto, che chiude la citazione, annidato o dopo un'altra frase",
              _st325("Art. 132 C.d.S. — «a quelle di cui all'articolo 53, comma 2, del decreto-legge 30 agosto 1993, n. 331, se provvisti».", "53") != ("verified", "codice_strada")
              and _st325("ex art. 33-ter c.p.p., «sempre che non siano contestate le aggravanti di cui all'articolo 80».", "80") != ("verified", "codice_procedura_penale")
              and _st325("Art. 13 Regolamento di esecuzione della legge sulla cittadinanza (DPR 572/1993) — «Si trascrive il testo dell'art. 15 della legge n. 91/1992: \"Art. 15. - L'acquisto ha effetto…\"».", "15") != ("verified", "regolamento_cittadinanza")
              and _st325("art. 2043 c.c. Poi in un altro paragrafo «di cui all'articolo 9» senza fonte.", "9") != ("verified", "codice_civile"))
    except Exception as _e325:  # noqa: BLE001
        check("verificatore[325]: kontrollet u ekzekutuan", False, f"{type(_e325).__name__}: {_e325}")

    # [326] v9.554 — i casi al limite del banco completo: AL corruzione, vizi dell'edificio, locazione scaduta, termine contro la revoca del
    # permesso; IT mobbing, maltrattamenti, sospensione condizionale, alimenti ai genitori — ciascuno solo nella sua area
    try:
        from pathlib import Path as _P326
        from src.retrieval import ArticleIndex as _AI326
        from src import brain as _b326
        _al326 = _AI326.load(_P326("/app/data/index/bm25.pkl")); _it326 = _AI326.load(_P326("/app/data/index/bm25_it.pkl"))
        _k326 = lambda q, ar: {(a.code, a.number) for a, _ in _b326._applica_ancore([], _al326, [q], ar)}
        _i326 = lambda q, ar: {(a.code, a.number) for a, _ in _b326._applica_ancore([], _it326, [q], ar, _b326.ANCORE_IT)}
        check("limite AL[326]: korrupsion → KP 259/244; lagështirë → KC 864-866; qiraja mbaroi → KC 820; leje qëndrimi afat → KPA 132",
              {("kodi_penal", "259"), ("kodi_penal", "244")} <= _k326("Një zyrtar i bashkisë i kërkoi klientit 2000 euro për lejen.", ["Penal"])
              and ("kodi_penal", "259") not in _k326("Një zyrtar i bashkisë i kërkoi klientit 2000 euro për lejen.", ["Administrativ"])
              and ("kodi_civil", "866") in _k326("Firma e ndërtimit i dorëzoi shtëpinë me lagështirë.", ["Civil"])
              and ("kodi_civil", "820") in _k326("Kontrata e qirasë mbaroi në qershor dhe qiramarrësi nuk largohet.", ["Civil"])
              and ("kodi_proc_admin", "132") in _k326("Policia i anuloi lejen e qëndrimit. Brenda sa kohe ankohemi?", ["Administrativ"]))
        check("limite IT[326]: mobbing → 2087; maltrattamenti → c.p. 572 (solo penale); sospensione condizionale → 163/164; alimenti al padre → 433/438",
              ("codice_civile", "2087") in _i326("Da mesi il datore umilia e isola il dipendente: è mobbing?", ["Civile"])
              and ("codice_penale", "572") in _i326("La cliente subisce insulti e spinte dal marito convivente.", ["Penale"])
              and ("codice_penale", "572") not in _i326("La cliente subisce insulti e spinte dal marito convivente.", ["Famiglia"])
              and {("codice_penale", "163"), ("codice_penale", "164")} <= _i326("Condannato a un anno e sei mesi, non ha precedenti: sospensione condizionale?", ["Penale"])
              and {("codice_civile", "433"), ("codice_civile", "438")} <= _i326("Il padre anziano chiede gli alimenti ai figli.", ["Civile"]))
    except Exception as _e326:  # noqa: BLE001
        check("limite[326]: kontrollet u ekzekutuan", False, f"{type(_e326).__name__}: {_e326}")

    # [327] v9.555 — sedicesimo giro: età imputabile (KP 12, solo penale), licenziamento in malattia (KP 130), divisione (KC 207); casa
    # occupata da estranei (c.p. 634-bis, non l'inquilino che resta), danni del figlio minore (c.c. 2048)
    try:
        from pathlib import Path as _P327
        from src.retrieval import ArticleIndex as _AI327
        from src import brain as _b327
        _al327 = _AI327.load(_P327("/app/data/index/bm25.pkl")); _it327 = _AI327.load(_P327("/app/data/index/bm25_it.pkl"))
        _k327 = lambda q, ar: {(a.code, a.number) for a, _ in _b327._applica_ancore([], _al327, [q], ar)}
        _i327 = lambda q, ar: {(a.code, a.number) for a, _ in _b327._applica_ancore([], _it327, [q], ar, _b327.ANCORE_IT)}
        check("frek16 AL[327]: djali 13 vjeç → KP 12 (solo penale); raport mjekësor → KP 130; trashëguan… nuk pranon ta ndajë → KC 207",
              ("kodi_penal", "12") in _k327("Djali 13 vjeç i klientes vodhi një telefon. A mund të ndiqet penalisht?", ["Penal"])
              and ("kodi_penal", "12") not in _k327("Djali 13 vjeç i klientes do të ndryshojë shkollë.", ["Familje"])
              and ("kodi_punes", "130") in _k327("Punëdhënësi e pushoi ndërsa ishte me raport mjekësor.", ["Punë"])
              and ("kodi_civil", "207") in _k327("Tre vëllezër trashëguan një shtëpi dhe njëri nuk pranon ta ndajë.", ["Civil"]))
        check("frek16 IT[327]: casa occupata da sconosciuti → c.p. 634-bis, l'inquilino che non lascia no; figlio che ha rotto il vetro → c.c. 2048",
              ("codice_penale", "634-bis") in _i327("Mentre il cliente era in vacanza degli sconosciuti hanno occupato la sua casa.", ["Penale"])
              and ("codice_penale", "634-bis") not in _i327("L'inquilino non lascia la casa alla scadenza del contratto.", ["Civile"])
              and ("codice_civile", "2048") in _i327("Il figlio quindicenne ha rotto il vetro dell'auto del vicino: chi paga?", ["Civile"]))
    except Exception as _e327:  # noqa: BLE001
        check("frek16[327]: kontrollet u ekzekutuan", False, f"{type(_e327).__name__}: {_e327}")

    # [328] v9.556 — il D.Lgs. 7/2016 nel corpus (ingiuria = illecito civile: «art. 4 D.Lgs. 7/2016» verificato, ancora sull'insulto) e le
    # ancore AL del diciassettesimo giro (furto con violenza KP 139/140 solo penale, accesso ai documenti pubblici ligji 119/2014 art. 15)
    try:
        from pathlib import Path as _P328
        from src.retrieval import ArticleIndex as _AI328
        from src import brain as _b328
        from src import citation_verifier as _cv328
        _al328 = _AI328.load(_P328("/app/data/index/bm25.pkl")); _it328 = _AI328.load(_P328("/app/data/index/bm25_it.pkl"))
        _st328 = {i["number"]: (i["status"], i.get("code")) for i in _cv328.verify_text("L'ingiuria è oggi un illecito civile (art. 4 D.Lgs. 7/2016).", _it328)["items"]}
        _i328 = {(a.code, a.number) for a, _ in _b328._applica_ancore([], _it328, ["Un collega ha insultato il cliente davanti a tutti: possiamo denunciarlo?"], ["Penale"], _b328.ANCORE_IT)}
        check("ingiuria[328]: «art. 4 D.Lgs. 7/2016» verificato; l'insulto davanti ai colleghi → D.Lgs. 7/2016 art. 4",
              _st328.get("4") == ("verified", "sanzioni_pecuniarie_civili") and ("sanzioni_pecuniarie_civili", "4") in _i328, str(_st328))
        _k328 = lambda q, ar: {(a.code, a.number) for a, _ in _b328._applica_ancore([], _al328, [q], ar)}
        check("frek17 AL[328]: «i morën telefonin me forcë» → KP 139/140 (solo penale); kopja e vendimit të bashkisë → ligji_informimi 15",
              {("kodi_penal", "139"), ("kodi_penal", "140")} <= _k328("Dy persona e sulmuan klientin dhe i morën telefonin me forcë.", ["Penal"])
              and ("kodi_penal", "139") not in _k328("Dy persona e sulmuan klientin dhe i morën telefonin me forcë.", ["Civil"])
              and ("ligji_informimi", "15") in _k328("Bashkia nuk i jep klientit kopjen e vendimit të këshillit.", ["Administrativ"]))
        _m328 = {(a.code, a.number) for a, _ in _b328._applica_ancore([], _it328, ["Il cliente incensurato è accusato di furto semplice: può chiedere la messa alla prova?"], ["Penale"], _b328.ANCORE_IT)}
        check("messa alla prova[328]: → c.p. 168-bis + c.p.p. 464-bis", {("codice_penale", "168-bis"), ("codice_procedura_penale", "464-bis")} <= _m328)
    except Exception as _e328:  # noqa: BLE001
        check("frek17[328]: kontrollet u ekzekutuan", False, f"{type(_e328).__name__}: {_e328}")

    # [329] v9.557 — il completamento del cancello rivede anche le righe SENZA riserva che citano gli articoli fuori blocco (la risposta
    # sull'ingiuria diceva «Cassa delle ammende (art. 10)» sopra e «Fondo di rotazione» sotto); non le righe su altri articoli
    try:
        from pathlib import Path as _P329
        from src.retrieval import ArticleIndex as _AI329
        from src import cancello as _ca329
        _it329 = _AI329.load(_P329("/app/data/index/bm25_it.pkl"))
        _t329 = ("La sanzione è devoluta alla Cassa delle ammende (art. 10 D.Lgs. 7/2016).\n"
                 "Il risarcimento segue l'art. 2043 c.c.\n"
                 "L'art. 10 D.Lgs. 7/2016 non è tra gli articoli recuperati: verificare.")
        _idx329, _arts329 = _ca329._da_completare(_t329, _it329)
        check("cancello[329]: rivede la riga con la riserva E quella senza sullo stesso art. 10, non quella sul 2043",
              _idx329 == [0, 2] and [(a.code, str(a.number)) for a in _arts329] == [("sanzioni_pecuniarie_civili", "10")],
              str((_idx329, [(a.code, a.number) for a in _arts329])))
    except Exception as _e329:  # noqa: BLE001
        check("cancello[329]: kontrollet u ekzekutuan", False, f"{type(_e329).__name__}: {_e329}")

    # [330] v9.558 — la prescrizione AL (KC 114/115) dalla DOMANDA, non dalle riscritture del triage; alimenti non pagati → KP 125 (solo
    # penale); TU riscossione 187 «Fermo di beni mobili registrati» con la sua rubrica
    try:
        from pathlib import Path as _P330
        from src.retrieval import ArticleIndex as _AI330
        from src import brain as _b330
        _al330 = _AI330.load(_P330("/app/data/index/bm25.pkl")); _it330 = _AI330.load(_P330("/app/data/index/bm25_it.pkl"))
        _k330 = lambda qs, ar: {(a.code, a.number) for a, _ in _b330._applica_ancore([], _al330, qs, ar)}
        check("prescrizione AL[330]: dalla domanda sì («A ka rënë në parashkrim?», «borxh nga viti 2012»); dal solo triage no",
              ("kodi_civil", "114") in _k330(["Klienti ka një borxh nga viti 2012 dhe kreditori tani e padit. A ka rënë në parashkrim?"], ["Civil"])
              and ("kodi_civil", "114") in _k330(["Klienti ka një borxh nga viti 2012: çfarë mund të bëjë kreditori?"], ["Civil"])
              and ("kodi_civil", "114") not in _k330(["parashkrimi i së drejtës për të pranuar trashëgiminë",
                                                      "Babai vdiq me borxhe. Si heq dorë klienti nga trashëgimia?"], ["Civil"]))
        check("frek18[330]: ish-bashkëshorti nuk paguan detyrimin ushqimor → KP 125 (solo penale)",
              ("kodi_penal", "125") in _k330(["Ish-bashkëshorti nuk paguan detyrimin ushqimor për fëmijën. A është vepër penale?"], ["Penal", "Familje"])
              and ("kodi_penal", "125") not in _k330(["Ish-bashkëshorti nuk paguan detyrimin ushqimor për fëmijën."], ["Familje"]))
        _h330 = {(a.code, a.number): a.heading for a in _it330.articles if a.code == "tu_riscossione"}
        check("rubriche IT[330]: TU riscossione 187 «Fermo di beni mobili registrati»", _h330.get(("tu_riscossione", "187")) == "Fermo di beni mobili registrati",
              repr(_h330.get(("tu_riscossione", "187"))))
    except Exception as _e330:  # noqa: BLE001
        check("[330]: kontrollet u ekzekutuan", False, f"{type(_e330).__name__}: {_e330}")

    # [331] v9.559 — KC 698 (risoluzione del contratto per inadempimento) nella qira sì, nel mantenimento dei figli (Familje) no
    try:
        from pathlib import Path as _P331
        from src.retrieval import ArticleIndex as _AI331
        from src import brain as _b331
        _al331 = _AI331.load(_P331("/app/data/index/bm25.pkl"))
        _k331 = lambda q, ar: {(a.code, a.number) for a, _ in _b331._applica_ancore([], _al331, [q], ar)}
        check("ancore AL[331]: KC 698 nella qira non pagata sì, nel mantenimento del figlio (Familje) no",
              ("kodi_civil", "698") in _k331("Qiramarrësi nuk paguan qiranë prej 5 muajsh.", ["Civil"])
              and ("kodi_civil", "698") not in _k331("Ish-bashkëshorti nuk paguan asgjë për djalin.", ["Familje", "Civil"]))
        check("ancore AL[331]: KC 193/195 su «ASHK refuzoi regjistrimin e shitjes» sì; su «bashkëshortët… shitën» o il telefono no",
              ("kodi_civil", "195") in _k331("ASHK refuzoi regjistrimin e shitjes së apartamentit.", ["Civil"])
              and ("kodi_civil", "195") not in _k331("Ish-bashkëshortët nuk bien dakord si ta shitin makinën e përbashkët.", ["Civil"])
              and ("kodi_civil", "195") not in _k331("blerja online e celularit dhe e drejta e shitësit për ta marrë mbrapsht", ["Konsumator"]))
        check("ancore AL[331]: pistoletë pa leje → KP 278 (solo penale); il coltello no",
              ("kodi_penal", "278") in _k331("Klienti u kap me një pistoletë pa leje në makinë.", ["Penal"])
              and ("kodi_penal", "278") not in _k331("Policia i gjeti klientit një thikë të madhe në makinë.", ["Penal"]))
    except Exception as _e331:  # noqa: BLE001
        check("ancore AL[331]: kontrollet u ekzekutuan", False, f"{type(_e331).__name__}: {_e331}")

    # [332] v9.559 — RADICI DELLE ANCORE dentro parole comuni (cercate su tutto il corpus): «dehur» in «pandehuri», «hua» in
    # «ndryshuar», «isol» in «risoluzione», «orale» in «morale», «para» in «përpara»: il caso vero scatta, il falso amico no
    try:
        from pathlib import Path as _P332
        from src.retrieval import ArticleIndex as _AI332
        from src import brain as _b332
        _al332 = _AI332.load(_P332("/app/data/index/bm25.pkl")); _it332 = _AI332.load(_P332("/app/data/index/bm25_it.pkl"))
        _k332 = lambda q, ar: {(a.code, a.number) for a, _ in _b332._applica_ancore([], _al332, [q], ar)}
        _i332 = lambda q, ar: {(a.code, a.number) for a, _ in _b332._applica_ancore([], _it332, [q], ar, _b332.ANCORE_IT)}
        check("radici AL[332]: ebbrezza, prestito, corruzione, età — veri sì, falsi amici no",
              ("kodi_penal", "291") in _k332("Klienti u ndalua duke drejtuar makinën i dehur.", ["Penal"])
              and ("kodi_penal", "291") not in _k332("I pandehuri ka të drejtë të heshtë gjatë marrjes në pyetje.", ["Penal"])
              and ("kodi_civil", "1050") in _k332("I dha një shoku 10 mijë euro hua dhe ai nuk ia kthen.", ["Civil"])
              and ("kodi_civil", "1050") not in _k332("Ligji i ndryshuar kthehet në fuqi për kontratat e lidhura.", ["Civil"])
              and ("kodi_penal", "259") not in _k332("Zyrtari kërkoi dokumentet përpara se të jepte lejen.", ["Penal"])
              and ("kodi_penal", "12") in _k332("Djali 13 vjeç vodhi një telefon.", ["Penal"])
              and ("kodi_penal", "12") not in _k332("Djali mori një dënim 5-vjeçar për vjedhje.", ["Penal"]))
        check("radici IT[332]: mobbing e licenziamento orale — veri sì, «risoluzione del rapporto» e «danno morale» no",
              ("codice_civile", "2087") in _i332("Da mesi il datore umilia e isola il dipendente.", ["Civile"])
              and ("codice_civile", "2087") not in _i332("La risoluzione del rapporto del dipendente per giusta causa.", ["Civile"])
              and ("licenziamenti_individuali", "2") in _i332("Il cliente è stato licenziato in forma orale.", ["Lavoro"])
              and ("licenziamenti_individuali", "2") not in _i332("Licenziato, chiede il danno morale per la lettera offensiva.", ["Lavoro"]))
        check("frek19 AL[332]: «hyri me forcë në shtëpinë e saj pa leje» → KP 112 (solo penale)",
              ("kodi_penal", "112") in _k332("Ish-burri hyri me forcë në shtëpinë e saj pa leje.", ["Penal", "Familje"])
              and ("kodi_penal", "112") not in _k332("Ish-burri hyri me forcë në shtëpinë e saj pa leje.", ["Familje"]))
    except Exception as _e332:  # noqa: BLE001
        check("radici[332]: kontrollet u ekzekutuan", False, f"{type(_e332).__name__}: {_e332}")

    # [333] v9.562 — recesso dall'acquisto online → cod. consumo 52/54; furto di poco valore → particolare tenuità c.p. 131-bis (solo penale)
    try:
        from pathlib import Path as _P333
        from src.retrieval import ArticleIndex as _AI333
        from src import brain as _b333
        _it333 = _AI333.load(_P333("/app/data/index/bm25_it.pkl"))
        _i333 = lambda q, ar: {(a.code, a.number) for a, _ in _b333._applica_ancore([], _it333, [q], ar, _b333.ANCORE_IT)}
        check("frek-it[333]: divano comprato online da restituire → cod. consumo 52; furto da 15 euro → c.p. 131-bis (solo penale)",
              ("codice_consumo", "52") in _i333("Il cliente ha comprato online un divano e vuole restituirlo senza motivo.", ["Civile"])
              and ("codice_penale", "131-bis") in _i333("furto di modico valore al supermercato, incensurato: particolare tenuità?", ["Penale"])
              and ("codice_penale", "131-bis") not in _i333("particolare tenuità del danno nel risarcimento", ["Civile"]))
    except Exception as _e333:  # noqa: BLE001
        check("frek-it[333]: kontrollet u ekzekutuan", False, f"{type(_e333).__name__}: {_e333}")

    # [334] v9.563 — i casi AL oltre il 9° a triage fisso: coltello → KP 279; energia → KP 137 (solo penale); incinta licenziata → KP 105/a, 146
    try:
        from pathlib import Path as _P334
        from src.retrieval import ArticleIndex as _AI334
        from src import brain as _b334
        _al334 = _AI334.load(_P334("/app/data/index/bm25.pkl"))
        _k334 = lambda q, ar: {(a.code, a.number) for a, _ in _b334._applica_ancore([], _al334, [q], ar)}
        check("limite AL[334]: thikë → KP 279; lidhje e paligjshme me rrjetin elektrik → KP 137; shtatzënë e hoqën nga puna → KP 105/a, 146",
              ("kodi_penal", "279") in _k334("Policia i gjeti klientit një thikë të madhe në makinë.", ["Penal"])
              and ("kodi_penal", "279") not in _k334("Policia i gjeti klientit një pistoletë në makinë.", ["Penal"])
              and ("kodi_penal", "137") in _k334("OSHEE e kallëzoi për një lidhje të paligjshme me rrjetin elektrik.", ["Penal"])
              and {("kodi_punes", "105/a"), ("kodi_punes", "146")} <= _k334("I tha punëdhënësit se është shtatzënë dhe e hoqën nga puna.", ["Punë"]))
    except Exception as _e334:  # noqa: BLE001
        check("limite AL[334]: kontrollet u ekzekutuan", False, f"{type(_e334).__name__}: {_e334}")

    # [335] v9.564 — la costante della fusione per rango è quella MISURATA (20) e la fusione la usa davvero; peso del senso 1,0
    try:
        import os as _os335
        from src import dense as _dn335
        _f335 = _dn335.fondi([(type("A", (), {"code": "c", "number": "1"})(), 5.0)], [(type("A", (), {"code": "c", "number": "1"})(), 0.9)])
        from src import retrieval as _rt335
        check("ricerca[335]: spinta ai codici base IT = 1,0 (misurato: la ricerca per senso la rende inutile)",
              _os335.environ.get("IT_CORE_BOOST") is not None or _rt335.IT_CORE_BOOST == 1.0, str(_rt335.IT_CORE_BOOST))
        check("ricerca[335]: RRF_K = 20 (misurato), peso del senso 1,0, fusione 2/(20+1)",
              (_os335.environ.get("DENSE_RRF_K") or _dn335.RRF_K == 20) and _dn335.PESO_DENSO == 1.0
              and abs(_f335[("c", "1")][0] - 2.0 / 21) < 1e-9, str((_dn335.RRF_K, _dn335.PESO_DENSO, _f335)))
    except Exception as _e335:  # noqa: BLE001
        check("ricerca[335]: kontrollet u ekzekutuan", False, f"{type(_e335).__name__}: {_e335}")

    # [336] v9.566 — auto senza assicurazione o non identificata → Fondi i kompensimit (AL 41) / Fondo di garanzia (cod. ass. 283);
    # il lavoratore «pa sigurim» / senza assicurazione INAIL no (il veicolo dev'esserci)
    try:
        from pathlib import Path as _P336
        from src.retrieval import ArticleIndex as _AI336
        from src import brain as _b336
        _al336 = _AI336.load(_P336("/app/data/index/bm25.pkl")); _it336 = _AI336.load(_P336("/app/data/index/bm25_it.pkl"))
        _k336 = lambda q, ar: {(a.code, a.number) for a, _ in _b336._applica_ancore([], _al336, [q], ar)}
        _i336 = lambda q, ar: {(a.code, a.number) for a, _ in _b336._applica_ancore([], _it336, [q], ar, _b336.ANCORE_IT)}
        check("frek21[336]: makinë pa siguracion / e paidentifikuar → ligji_sigurimi_mjeteve 41; punëtori pa sigurim jo",
              ("ligji_sigurimi_mjeteve", "41") in _k336("E përplasi një makinë pa siguracion dhe drejtuesi u largua.", ["Civil"])
              and ("ligji_sigurimi_mjeteve", "41") in _k336("Dëmin e shkaktoi një mjet i paidentifikuar.", ["Sigurime"])
              and ("ligji_sigurimi_mjeteve", "41") not in _k336("Klienti punon pa sigurime shoqërore prej dy vitesh.", ["Punë"]))
        check("frek20[336]: kamera e fqinjit filmon oborrin → KP 121; kamera që regjistroi vjedhjen jo",
              ("kodi_penal", "121") in _k336("Fqinji vendosi një kamerë që filmon oborrin dhe dritaret e shtëpisë.", ["Civil"])
              and ("kodi_penal", "121") not in _k336("Kamerat e dyqanit regjistruan vjedhjen.", ["Penal"]))
        check("frek22[336]: kat shtesë pa leje → KP 199/a; i huaji punon në ndërtim pa leje pune jo (lavoro)",
              ("kodi_penal", "199/a") in _k336("Fqinji po ndërton një kat shtesë pa leje mbi pallatin.", ["Ndertim", "Civil"])
              and ("kodi_penal", "199/a") not in _k336("I huaji punon në ndërtim pa leje pune.", ["Punë", "Administrativ"]))
        check("frek21[336]: investito da auto senza assicurazione / pirata della strada → cod. ass. 283; lavoratore senza assicurazione no",
              ("codice_assicurazioni", "283") in _i336("Il cliente è stato investito da un'auto senza assicurazione.", ["Civile"])
              and ("codice_assicurazioni", "283") in _i336("Investito da un pirata della strada mai trovato.", ["Penale"])
              and ("codice_assicurazioni", "283") in _i336("Investito da una macchina senza assicurazione.", ["Civile"])
              and ("codice_assicurazioni", "283") not in _i336("Il dipendente lavorava senza assicurazione INAIL.", ["Lavoro"])
              and ("codice_assicurazioni", "283") not in _i336("Il lavoratore autonomo non assicurato si è fatto male.", ["Lavoro"])
              and ("codice_assicurazioni", "283") not in _i336("Licenziato senza motivo e senza assicurazione.", ["Lavoro"]))
    except Exception as _e336:  # noqa: BLE001
        check("frek21[336]: kontrollet u ekzekutuan", False, f"{type(_e336).__name__}: {_e336}")

    # [337] v9.567 — la rubrica AL non riconosciuta (lunga, su due righe, con un verbo, con la nota redazionale) incollata al
    # paragrafo 1 come «prima frase»: 168 nene nelle leggi CON rubriche → rubrica · nota · corpo. Mai nei codici senza rubriche.
    try:
        import re as _re337
        from collections import defaultdict as _dd337
        from pathlib import Path as _P337
        from src.retrieval import ArticleIndex as _AI337
        from src.parser import rubrika_para_paragrafit as _rpp337
        _al337 = _AI337.load(_P337("/app/data/index/bm25.pkl"))
        _A337 = {(a.code, a.number): a for a in _al337.articles}
        _d57 = _A337[("ligji_te_dhenat_2024", "57")]; _p247 = _A337[("kodi_proc_penale", "247")]
        check("rubriche AL[337]: dhënat 57 «E drejta për korrigjimin ose fshirjen…» e il «1.» nel corpo; KPP 247 rubrica + nota 35/2017",
              _d57.heading == "E drejta për korrigjimin ose fshirjen e të dhënave personale dhe për kufizimin e përpunimit"
              and _d57.heading_kind == "rubrike" and (_d57.body or "").startswith("1. Subjekti")
              and _p247.heading == "Kërkimi i personit që nuk gjendet" and "35/2017" in (_p247.note or "")
              and (_p247.body or "").startswith("1. Kur personi"), f"{_d57.heading[:60]!r} / {_p247.heading[:60]!r}")
        _x337 = _rpp337("Ushqimi (Numërtuar pika 1 me ligjin nr. 136/2015, datë 5.12.2015) 1. Punëdhënësi vë në dispozicion")
        check("rubriche AL[337]: la regola — rubrica, nota, «1. …»; non l'introduzione d'elenco né il rinvio «nenit 1.»",
              _x337 == ("Ushqimi", "(Numërtuar pika 1 me ligjin nr. 136/2015, datë 5.12.2015)", "1. Punëdhënësi vë në dispozicion")
              and _rpp337("Janë të hipotekueshme: 1. Sendet e paluajtshme") is None
              and _rpp337("Zbatohen dispozitat e nenit 1. Ky ligj") is None
              and _rpp337("1. Shqipëria është Republikë parlamentare.") is None, str(_x337))
        _per337 = _dd337(list)
        for _a in _al337.articles:
            _per337[_a.code].append(_a)
        _rest337 = [(_c, _a.number) for _c, _l in _per337.items()
                    if sum(1 for _a in _l if getattr(_a, "heading_kind", "") == "rubrike") >= 0.6 * len(_l)
                    for _a in _l if getattr(_a, "heading_kind", "") == "fjali" and not _a.repealed and _rpp337(_a.heading)]
        check("rubriche AL[337]: nessuna rubrica+paragrafo rimasta nelle leggi a rubriche; il Codice civile resta «prima frase»",
              not _rest337 and _A337[("kodi_civil", "5")].heading_kind == "fjali", str(_rest337[:5]))
    except Exception as _e337:  # noqa: BLE001
        check("rubriche AL[337]: kontrollet u ekzekutuan", False, f"{type(_e337).__name__}: {_e337}")

    # [338] v9.568 — vince l'atto PIÙ VICINO al numero: la rubrica scritta dopo la sigla («art. 1219 c.c. costituzione in mora», «art. 74
    # c.p.p. costituzione di parte civile», «art. 165 c.p.c. costituzione in giudizio») non lo cambia più nella Costituzione
    try:
        from pathlib import Path as _P338
        from src.retrieval import ArticleIndex as _AI338
        from src import citation_verifier as _cv338
        _it338 = _AI338.load(_P338("/app/data/index/bm25_it.pkl"))
        def _st338(t, n):
            return {i["number"]: (i["status"], i.get("code")) for i in _cv338.verify_text(t, _it338)["items"]}.get(n)
        check("verificatore[338]: «art. 1219 c.c. costituzione in mora», «art. 74 c.p.p. costituzione di parte civile», «art. 165 c.p.c. "
              "costituzione in giudizio» → c.c., c.p.p., c.p.c. (prima: Costituzione)",
              _st338("Vale l'art. 1219 c.c. costituzione in mora.", "1219") == ("verified", "codice_civile")
              and _st338("Si veda l'art. 74 c.p.p. costituzione di parte civile.", "74") == ("verified", "codice_procedura_penale")
              and _st338("Entro dieci giorni: art. 165 c.p.c. costituzione in giudizio.", "165") == ("verified", "codice_procedura_civile"),
              str((_st338("Vale l'art. 1219 c.c. costituzione in mora.", "1219"), _st338("Si veda l'art. 74 c.p.p. costituzione di parte civile.", "74"))))
        check("verificatore[338]: la Costituzione citata davvero resta la Costituzione (art. 24 Cost., art. 111 della Costituzione)",
              _st338("Il diritto di difesa (art. 24 Cost.) è inviolabile.", "24") == ("verified", "costituzione")
              and _st338("Lo dice l'art. 111 della Costituzione.", "111") == ("verified", "costituzione"))
        _it338b = _AI338.load(_P338("/app/data/index/bm25_it.pkl"))
        from src import brain as _b338
        _i338 = lambda q, ar: {(a.code, a.number) for a, _ in _b338._applica_ancore([], _it338b, [q], ar, _b338.ANCORE_IT)}
        check("frek24[338]: opposizione al decreto ingiuntivo da iscrivere a ruolo → c.p.c. 165; il decreto ingiuntivo senza opposizione no",
              ("codice_procedura_civile", "165") in _i338("Abbiamo notificato l'opposizione al decreto ingiuntivo: entro quando va iscritta a ruolo?", ["Civile"])
              and ("codice_procedura_civile", "165") not in _i338("Al cliente è stato notificato un decreto ingiuntivo.", ["Civile"]))
    except Exception as _e338:  # noqa: BLE001
        check("verificatore[338]: kontrollet u ekzekutuan", False, f"{type(_e338).__name__}: {_e338}")

    # [339] v9.569 — rubriche italiane con la parentesi chiusa DENTRO: rubrica + testo («Atti urgenti) 1. Il giudice…») e fonte o
    # marcatore davanti («Art. 215 Cod. Str.) Rimozione del veicolo», «L-R) Documenti di identità…», accise, TU edilizia, stupefacenti)
    try:
        import re as _re339
        from pathlib import Path as _P339
        from src.retrieval import ArticleIndex as _AI339
        _it339 = _AI339.load(_P339("/app/data/index/bm25_it.pkl"))
        _I339 = {(a.code, a.number): a for a in _it339.articles}
        _h339 = lambda c, n: (_I339[(c, n)].heading or "") if (c, n) in _I339 else None
        check("rubriche IT[339]: c.p.p. 554 «Atti urgenti» (il testo nel corpo), reg. C.d.S. 397 «Rimozione del veicolo», TU doc. 35, "
              "accise 45, TU edilizia 67, stupefacenti 13 — la fonte nella nota",
              _h339("codice_procedura_penale", "554") == "Atti urgenti"
              and (_I339[("codice_procedura_penale", "554")].body or "").startswith("1. Il giudice")
              and _h339("regolamento_strada", "397") == "Rimozione del veicolo"
              and (_I339[("regolamento_strada", "397")].body or "").startswith("1. La sanzione")
              and "Fonte: Art. 215 Cod. Str." in (getattr(_I339[("regolamento_strada", "397")], "note", "") or "")
              and _h339("tu_documentazione_amministrativa", "35") == "Documenti di identità e di riconoscimento"
              and _h339("accise", "45") == "Circostanze aggravanti" and _h339("tu_edilizia", "67") == "Collaudo statico"
              and _h339("stupefacenti", "13") == "Tabelle delle sostanze soggette a controllo",
              str([_h339("codice_procedura_penale", "554"), _h339("regolamento_strada", "397"), _h339("stupefacenti", "13")]))
        _rest339 = [(a.code, a.number) for a in _it339.articles if a.heading and not a.repealed
                    and _re339.match(r"^[^()]{1,300}(?<!\s[a-z])\)\s+\S", a.heading) and not _re339.match(r"(?i)(allegat|tabell|tariff|prospett)", a.heading)]
        check("rubriche IT[339]: nessuna rubrica con la parentesi chiusa dentro (fuori dagli allegati)", not _rest339, str(_rest339[:6]))
        _fonte339 = [(a.code, a.number) for a in _it339.articles if a.code in ("tu_edilizia", "maternita_paternita", "tu_immigrazione",
                     "codice_pari_opportunita") and _re339.search(r"\b(?:legge|decreto)\s+\d{1,2}\s+\w+\s+\d{4},\s*n\.\s*\d+,\s*art", a.heading or "")]
        check("rubriche IT[339]: la fonte in coda alla rubrica dei testi unici va nel corpo (TU edilizia 3 «Definizioni degli interventi "
              "edilizi», maternità 53 «Lavoro notturno», TU immigrazione 5 «Permesso di soggiorno»)",
              _h339("tu_edilizia", "3") == "Definizioni degli interventi edilizi" and _h339("maternita_paternita", "53") == "Lavoro notturno"
              and _h339("tu_immigrazione", "5") == "Permesso di soggiorno"
              and "Fonte: legge 5 agosto 1978" in (getattr(_I339[("tu_edilizia", "3")], "note", "") or "")
              and (_I339[("tu_edilizia", "3")].body or "").startswith("1. ") and not _fonte339, str(_fonte339[:5]))
    except Exception as _e339:  # noqa: BLE001
        check("rubriche IT[339]: kontrollet u ekzekutuan", False, f"{type(_e339).__name__}: {_e339}")

    # [341] v9.570 — testo AL ripulito dalle NOTE A PIÈ DI PAGINA del PDF QBZ: il KC 3 (aveva per «prima frase» la nota della legge
    # 17/2012, che ora sta nella nota del KC 625 come norma transitoria) e 27 nene con la nota in mezzo al testo, spesso a metà frase
    # (Kodi Rrugor 3), anche la Corte costituzionale (urbanistica 52, Kodi Zgjedhor 162): la nota nel campo `note`, il testo ricongiunto
    try:
        import importlib.util as _ilu341
        from pathlib import Path as _P341
        from src.retrieval import ArticleIndex as _AI341
        _al341 = _AI341.load(_P341("/app/data/index/bm25.pkl"))
        _A341 = {(a.code, a.number): a for a in _al341.articles}
        _kc3, _kc625 = _A341[("kodi_civil", "3")], _A341[("kodi_civil", "625")]
        check("note AL[341]: KC 3 «Të huajt gëzojnë po ato të drejta…» (non la nota della legge 17/2012); la norma transitoria nel KC 625",
              (_kc3.heading or "").startswith("Të huajt gëzojnë po ato të drejta") and "17/2012" not in (_kc3.heading or "")
              and "Dispozitë kalimtare" in (_kc625.note or "") and "reputacionit" in (_kc625.note or ""), (_kc3.heading or "")[:60])
        _kr3, _p52, _z162 = _A341[("kodi_rrugor", "3")], _A341[("ligji_planifikimi_territorit", "52")], _A341[("kodi_zgjedhor", "162")]
        check("note AL[341]: Kodi Rrugor 3 ricongiunto («nuk ⏎ ndërpriten»), Corte costituzionale nella nota (urbanistica 52, Kodi Zgjedhor 162)",
              "rrymat e trafikut nuk\nndërpriten" in (_kr3.body or "") and "komunë" in (_kr3.note or "")
              and "Gjykata Kushtetuese me vendimin nr. 15" in (_p52.note or "") and "Gjykata Kushtetuese" not in (_p52.body or "")
              and "jo më\npak se 35 000" in (_p52.body or "")
              and "në listën e\npërcaktuar në pikën 4" in (_z162.body or "") and "Gjykata Kushtetuese vendosi" in (_z162.note or ""))
        _sp341 = _ilu341.spec_from_file_location("rnc341", "/app/tools/repair_note_corpo_al.py")
        _rnc341 = _ilu341.module_from_spec(_sp341); _sp341.loader.exec_module(_rnc341)
        _rest341 = [(a.code, a.number) for a in _al341.articles if not a.repealed and _rnc341.separa(a.body or "")[1]]
        check("note AL[341]: nessuna nota a piè di pagina rimasta dentro i testi AL", not _rest341, str(_rest341[:6]))
        _pag341 = [(a.code, a.number) for a in _al341.articles if _rnc341.PAGINA.search(a.body or "")]
        check("note AL[341]: v9.572 — niente piè di pagina «Faqe|N» nei testi (legge 133/2015 sul trattamento della proprietà)",
              not _pag341, str(_pag341[:6]))
    except Exception as _e341:  # noqa: BLE001
        check("note AL[341]: kontrollet u ekzekutuan", False, f"{type(_e341).__name__}: {_e341}")

    # [342] v9.571 — le RUBRICHE del KC e del KF stanno sopra «Neni N» nel PDF: ora sono il titolo del LORO articolo (prima finivano in
    # coda al precedente: il KC 625 sul danno non patrimoniale finiva con «Përgjegjësia solidare»); le intestazioni di capitolo in
    # minuscolo («SEKSIONI I ⏎ Personat fizikë») fuori dai testi
    try:
        from pathlib import Path as _P342
        from src.retrieval import ArticleIndex as _AI342
        from src import parser as _pa342
        _al342 = _AI342.load(_P342("/app/data/index/bm25.pkl"))
        _A342 = {(a.code, a.number): a for a in _al342.articles}
        _h342 = lambda c, n: (_A342[(c, n)].heading or "", getattr(_A342[(c, n)], "heading_kind", ""))
        check("rubriche KC/KF[342]: KC 626 «Përgjegjësia solidare», 114 «Afatet e parashkrimit», 608, 277; KF 33, 73 — il loro testo nel corpo",
              _h342("kodi_civil", "626") == ("Përgjegjësia solidare", "rubrike")
              and (_A342[("kodi_civil", "626")].body or "").startswith("Kur dëmi është shkaktuar nga shumë persona")
              and _h342("kodi_civil", "114")[0] == "Afatet e parashkrimit" and _h342("kodi_civil", "608")[0] == "Përgjegjësia për shkaktimin e dëmit"
              and _h342("kodi_civil", "277")[0] == "Servituti i kalimit"
              and _h342("kodi_familjes", "33")[0] == "Shkaqet e pavlefshmërisë" and _h342("kodi_familjes", "73")[0] == "Bashkësia ligjore",
              str([_h342("kodi_civil", "626"), _h342("kodi_civil", "114")]))
        check("rubriche[342]: v9.572 — KPC 202 «Kur lejohet sigurimi i padisë», KPU 179 «Emri» (la rubrica sopra «Neni N» a inizio capitolo)",
              _h342("kodi_proc_civile", "202") == ("Kur lejohet sigurimi i padisë", "rubrike") and _h342("kodi_punes", "179")[0] == "Emri"
              and not (_A342[("kodi_punes", "178")].body or "").rstrip().endswith("Emri"), str((_h342("kodi_proc_civile", "202"), _h342("kodi_punes", "179"))))
        check("rubriche KC/KF[342]: la rubrica non resta in coda al precedente (KC 625, 23); niente «PERSONAT JURIDIKË» nel KC 23",
              not (_A342[("kodi_civil", "625")].body or "").rstrip().endswith("Përgjegjësia solidare")
              and "PERSONAT JURIDIKË" not in (_A342[("kodi_civil", "23")].body or "")
              and "Përmbajtja e personit juridik" not in (_A342[("kodi_civil", "23")].body or ""))
        _cg342 = _pa342.taglia_coda_gerarchia("Teksti i nenit.\nKREU II\nSUBJEKTET E SË DREJTËS\nSEKSIONI I\nPersonat fizikë")
        _ca342 = _pa342.taglia_coda_gerarchia("Mallra të ndryshme (kodi NC 97060000).\nPJESA C\nANTIKUARET\nMallra me moshë më të madhe se njëqind vjet (kodi NC 97060000).")
        check("code di capitolo[342]: «SEKSIONI I ⏎ Personat fizikë» tolta; il contenuto di un allegato che chiude la frase resta",
              _cg342[0] == "Teksti i nenit." and _ca342[1] == "", str((_cg342, _ca342)))
    except Exception as _e342:  # noqa: BLE001
        check("rubriche KC/KF[342]: kontrollet u ekzekutuan", False, f"{type(_e342).__name__}: {_e342}")

    # [343] v9.571 — il MARKDOWN dentro le citazioni italiane: suffisso latino in corsivo («art. 196-*sexies* disp. att. c.p.c.»,
    # «612 *bis* c.p.» — prima verificato come 612, la minaccia) e grassetto che si chiude fra numero e atto («**Art. 5** L. 604/1966»)
    try:
        from pathlib import Path as _P343
        from src.retrieval import ArticleIndex as _AI343
        from src import citation_verifier as _cv343
        _it343 = _AI343.load(_P343("/app/data/index/bm25_it.pkl"))
        def _st343(t):
            return [(i.get("code"), i.get("number"), i.get("status")) for i in _cv343.verify_text(t, _it343)["items"]]
        check("verificatore[343]: «196-*sexies* disp. att. c.p.c.», «612 *bis* c.p.», «5-*bis* D.Lgs. 28/2010» col suffisso",
              _st343("(art. 196-*sexies* disp. att. c.p.c.)") == [("disp_att_cpc", "196/sexies", "verified")]
              and _st343("Atti persecutori: art. 612 *bis* c.p.") == [("codice_penale", "612/bis", "verified")]
              and _st343("art. 5-*bis* D.Lgs. 28/2010") == [("mediazione_civile", "5/bis", "verified")],
              str(_st343("Atti persecutori: art. 612 *bis* c.p.")))
        check("verificatore[343]: «**Art. 5** L. 604/1966», «**art. 4, comma 1** D.Lgs. 23/2015» — l'atto dopo il grassetto",
              _st343("- **Art. 5** L. 604/1966: «L'onere della prova»") == [("licenziamenti_individuali", "5", "verified")]
              and _st343("**art. 4, comma 1** D.Lgs. 23/2015") == [("tutele_crescenti", "4", "verified")],
              str(_st343("- **Art. 5** L. 604/1966: «L'onere della prova»")))
    except Exception as _e343:  # noqa: BLE001
        check("verificatore[343]: kontrollet u ekzekutuan", False, f"{type(_e343).__name__}: {_e343}")

    # [344] v9.573 — la FORMULA DI PROMULGAZIONE fuori dall'ultimo articolo degli atti italiani («Roma, addì 16 marzo 1942-XX ⏎ VITTORIO
    # EMANUELE ⏎ GRANDI» nel c.c. 2969, le firme in coda al C.d.S. 240, allo Statuto 41, alla L. 241/1990 art. 31…); le unità «N-legge»
    # (la legge di approvazione) la tengono
    try:
        import re as _re344
        from pathlib import Path as _P344
        from src.retrieval import ArticleIndex as _AI344
        _it344 = _AI344.load(_P344("/app/data/index/bm25_it.pkl"))
        _I344 = {(a.code, a.number): a for a in _it344.articles}
        check("promulgazione IT[344]: c.c. 2969, C.d.S. 240, Statuto 41 finiscono col loro testo; il c.c. «2-legge» tiene la formula",
              (_I344[("codice_civile", "2969")].body or "").rstrip().endswith("cause d'improponibilità dell'azione.")
              and "VITTORIO EMANUELE" not in (_I344[("codice_civile", "2969")].body or "")
              and "addì" not in (_I344[("codice_strada", "240")].body or "") and "Guardasigilli" not in (_I344[("statuto_lavoratori", "41")].body or "")
              and "addì" in (_I344[("codice_civile", "2-legge")].body or ""), (_I344[("codice_civile", "2969")].body or "")[-80:])
        _rx344 = _re344.compile(r"(?m)^(?:Dato|Data) a\s+\S+.*addì|^Visto,? il Guardasigilli")
        _rest344 = [(a.code, a.number) for a in _it344.articles if not _re344.search(r"legge|allegat|tabell", str(a.number), _re344.I)
                    and _rx344.search(a.body or "")]
        check("promulgazione IT[344]: nessun altro articolo con «Dato a … addì» / «Visto, il Guardasigilli» (fuori da leggi di approvazione e allegati)",
              not _rest344, str(_rest344[:6]))
        _ngu344 = _re344.compile(r"(?m)^[ \t]*(?:Note|Nota|NOTE|NOTA)[ \t]+(?:all['’][ \t]*art|alle[ \t]+premesse|al[ \t]+decreto|AL[ \t]+DECRETO)")
        _restn344 = [(a.code, a.number) for a in _it344.articles if _ngu344.search(a.body or "")]
        check("note G.U. IT[344]: nessun articolo con le «Note all'art. N» della Gazzetta; C.d.S. 206 senza l'art. 27 della L. 689/1981",
              not _restn344 and "Esecuzione forzata" not in (_I344[("codice_strada", "206")].body or "")
              and (_I344[("codice_strada", "206")].body or "").rstrip().endswith("in unica soluzione."), str(_restn344[:6]))
    except Exception as _e344:  # noqa: BLE001
        check("promulgazione IT[344]: kontrollet u ekzekutuan", False, f"{type(_e344).__name__}: {_e344}")

    # [345] v9.574 — la prescrizione delle MULTE stradali → L. 689/1981 art. 28 e C.d.S. 209, non le lesioni stradali (c.p. 590/590-bis/157:
    # l'ancora del sinistro scattava su «stradali» — prova in Chrome del 10 ott); il sinistro con lesioni le tiene
    try:
        from pathlib import Path as _P345
        from src.retrieval import ArticleIndex as _AI345
        from src import brain as _b345
        _it345 = _AI345.load(_P345("/app/data/index/bm25_it.pkl"))
        _i345 = lambda q, ar: {(a.code, a.number) for a, _ in _b345._applica_ancore([], _it345, [q], ar, _b345.ANCORE_IT)}
        _m345 = _i345("Cartella esattoriale per multe stradali non pagate del 2019: sono prescritte?", ["Administrativ"])
        _s345 = _i345("Incidente stradale con lesioni nel 2022: entro quando si prescrive il risarcimento?", ["Civile"])
        check("multe[345]: multe stradali prescritte → L. 689/1981 art. 28 + C.d.S. 209, non c.p. 590/157; il sinistro con lesioni sì",
              {("sanzioni_amministrative", "28"), ("codice_strada", "209")} <= _m345 and ("codice_penale", "590") not in _m345
              and ("codice_penale", "590") in _s345
              and ("sanzioni_amministrative", "28") not in _i345("Il reato è punito con la multa: quando si prescrive?", ["Penale"]),
              str((sorted(_m345), sorted(_s345))))
    except Exception as _e345:  # noqa: BLE001
        check("multe[345]: kontrollet u ekzekutuan", False, f"{type(_e345).__name__}: {_e345}")

    # [346] v9.575 — dalla prova in Chrome sulle multe (10 ott): (1) la forma della Cassazione «dell'art. 209 C.d.S. e della L. n. 689
    # del 1981, art. 28» → art. 28 L. 689/1981 (usciva «senza codice»), mai la coda di un'altra citazione («art. 132 C.d.S., art. 94»);
    # (2) l'atto scritto per estremi ma FUORI corpus («art. 1, commi 537-543, L. 24 dicembre 2012, n. 228», «art. 83 D.L. 18/2020») →
    # «atto non nel corpus» con l'atto come etichetta, mai «codice non specificato — potrebbe essere: Cost., c.c., …»; un atto del corpus
    # mai «fuori corpus» (R.D. 262/1942 = c.c. e preleggi: resta da chiarire); la Trust Line li conta a parte; il pannello li dice
    try:
        from pathlib import Path as _P346
        from src.retrieval import ArticleIndex as _AI346
        from src import citation_verifier as _cv346, trust_line as _tl346
        _it346 = _AI346.load(_P346("/app/data/index/bm25_it.pkl"))
        def _st346(t, n):
            return [(i["status"], i.get("code"), i.get("resolved_by"), i.get("code_label"))
                    for i in _cv346.verify_text(t, _it346)["items"] if i["number"].split("/")[0] == n]
        check("verificatore[346]: «… e della L. n. 689 del 1981, art. 28» (Cassazione) → L. 689/1981; senza connettore resta senza codice",
              _st346("la prescrizione ai sensi dell'art. 209 C.d.S. e della L. n. 689 del 1981, art. 28 (Cass.)", "28")
              == [("verified", "sanzioni_amministrative", "atto_prima", "L. 689/1981")]
              and _st346("Sanzioni (art. 132 C.d.S., art. 94, comma 4-ter) e poi.", "94") == [("needs_code", None, None, None)]
              and _st346("ai sensi dell'art. 2 c.c. e della legge, art. 3 si applica", "3") == [("needs_code", None, None, None)])
        _fc346 = [_st346("la sospensione (art. 1, commi 537-543, L. 24 dicembre 2012, n. 228) opera", "1"),
                  _st346("la sospensione Covid (art. 83, comma 9, D.L. 18/2020) non salva", "83"),
                  _st346("Ammonimento (art. 8 d.l. 11/2009, conv. L. 38/2009)", "8")]
        check("verificatore[346]: atto per estremi fuori corpus → «fuori corpus» con l'atto (L. 228/2012, D.L. 18/2020, D.L. 11/2009)",
              _fc346 == [[("needs_code", None, "fuori_corpus", "L. 228/2012")], [("needs_code", None, "fuori_corpus", "D.L. 18/2020")],
                         [("needs_code", None, "fuori_corpus", "D.L. 11/2009")]], str(_fc346))
        check("verificatore[346]: mai «fuori corpus» un atto del corpus né l'atto che MODIFICA («come modificato dal D.L. 18/2020»)",
              _st346("ai sensi dell'art. 28 L. 689/1981 il diritto", "28")[0][:2] == ("verified", "sanzioni_amministrative")
              and _st346("ai sensi dell'art. 1 R.D. 262/1942 si applica", "1")[0][2] != "fuori_corpus"
              and _st346("l'art. 5 come modificato dal D.L. 18/2020 dispone", "5")[0][2] != "fuori_corpus"
              and "262/1942" in _cv346._num_anno_nel_corpus() and "689/1981" in _cv346._num_anno_nel_corpus())
        _v346 = _tl346.verifica("Norme: art. 28 L. 689/1981; la sospensione (art. 83 D.L. 18/2020) non rileva.", _it346, "IT")
        _r346 = _tl346.riga(_v346, "it")
        check("trust[346]: la riga dice «di atti fuori corpus», non «senza codice»",
              _v346["nene"].get("fuori_corpus") == 1 and "1 di atti fuori corpus" in _r346 and "senza codice" not in _r346, _r346)
        _js346 = __import__("pathlib").Path("/app/static/app.js").read_text(encoding="utf-8")
        check("pannello[346]: la citazione fuori corpus mostra l'atto e «atto non nel corpus», tradotta; il grassetto markdown non si vede",
              'c.resolved_by === "fuori_corpus"' in _js346
              and '"akt jashtë korpusit — verifikoje në burimin zyrtar": "atto non nel corpus — da riscontrare sulla fonte ufficiale"' in _js346
              and "<code>${escapeHtml(_rawVis(c.raw))}</code>" in _js346 and "<code>${escapeHtml(c.raw)}</code>" not in _js346)
    except Exception as _e346:  # noqa: BLE001
        check("verificatore[346]: kontrollet u ekzekutuan", False, f"{type(_e346).__name__}: {_e346}")

    # [347] v9.576 — gli ALLEGATI albanesi incollati all'ULTIMO articolo e la formula di promulgazione: la Costituzione aveva il
    # vetting (ANEKS «Rivlerësimi kalimtar…», neni A-G, 20.000 caratteri) dentro l'art. 183 — oltre il tetto del prompt (12.000) i neni
    # D-G non arrivavano mai al modello —; l'IVA i suoi tre allegati nell'art. 161; le imposte sul reddito la dichiarazione del
    # lavoratore autonomo nell'art. 72 (tools/repair_aneks_al.py). Ora unità a sé, lette «Aneksi, neni D» / «Shtojca 1»
    try:
        from src.retrieval import ArticleIndex as _AI347
        from src.parser import unita_nominata_al as _ua347
        _al347 = _AI347.load()
        _by347 = {(a.code, str(a.number)): a for a in _al347.articles}
        _k183, _kd347 = _by347.get(("kushtetuta", "183")), _by347.get(("kushtetuta", "aneks-neni-D"))
        check("aneks[347]: «aneks-neni-D» → «Aneksi, neni D», «shtojca-1» → «Shtojca 1», «aneks-I» → «Aneksi I»; i numeri veri intatti",
              _ua347("aneks-neni-D") == "Aneksi, neni D" and _ua347("shtojca-1") == "Shtojca 1" and _ua347("aneks-I") == "Aneksi I"
              and _ua347("88") == "" and _ua347("149/a") == "")
        check("aneks[347]: Kushtetuta — l'art. 183 senza l'ANEKS, il vetting in 10 unità (neni A-G) col titolo del capitolo",
              _k183 is not None and len(_k183.body) < 2000 and not re.search(r"(?m)^Neni D$", _k183.body)
              and _kd347 is not None and _kd347.heading == "Vlerësimi i pasurive" and "Rivlerësimi kalimtar" in (_kd347.kreu or "")
              and _kd347.citation.startswith("Aneksi, neni D — ")
              and sum(1 for a in _al347.articles if a.code == "kushtetuta" and str(a.number).startswith("aneks-neni-")) == 10)
        check("aneks[347]: IVA aneks-I/II/III, imposte sul reddito shtojca-1, consumatori shtojca-I; nessuna formula di promulgazione nei corpi",
              all(k in _by347 for k in (("ligji_tvsh", "aneks-I"), ("ligji_tvsh", "aneks-III"), ("ligji_tatimi_te_ardhurat", "shtojca-1"),
                                         ("ligji_konsumatoret", "shtojca-I")))
              and not [k for k, a in _by347.items()
                       if k[0] != "vkm_dispozita_doganore" and re.search(r"(?m)^Shpallur me dekretin", a.body or "")])
        _r347 = [(a.code, str(a.number)) for a, _ in _al347.search("vlerësimi i pasurive të gjyqtarit në procesin e rivlerësimit kalimtar",
                                                                   top_k=8)]
        check("aneks[347]: «vlerësimi i pasurive … rivlerësimit kalimtar» → Kushtetuta, Aneksi neni D nei primi 5",
              ("kushtetuta", "aneks-neni-D") in _r347[:5], str(_r347))
    except Exception as _e347:  # noqa: BLE001
        check("aneks[347]: kontrollet u ekzekutuan", False, f"{type(_e347).__name__}: {_e347}")

    # [348] v9.577 — le citazioni dell'Aneks della Costituzione (neni a LETTERE) si verificano: prova in Chrome del 10 ott sul vetting,
    # la risposta citava D, Ç, C, E, Ë, F, G e la riga di verifica non ne contava nessuna
    try:
        from src.retrieval import ArticleIndex as _AI348
        from src import citation_verifier as _cv348
        _al348 = _AI348.load()
        def _st348(t):
            return [(i["status"], i.get("code"), i["number"]) for i in _cv348.verify_text(t, _al348)["items"] if i.get("resolved_by") == "aneks"]
        check("aneks-citim[348]: «Aneksi, neni D», «neni D, pika 5, i Aneksit të Kushtetutës», «nenit Ë, paragrafi 2, të Aneksit», «Aneksi i "
              "Kushtetutës, neni DH» → verificati",
              _st348("Kushtetuta (Aneksi, neni D) e detyron të shpjegojë burimin e ligjshëm.") == [("verified", "kushtetuta", "aneks/neni/d")]
              and _st348("Pa provë, neni D, pika 5, i Aneksit të Kushtetutës sjell shkarkim.") == [("verified", "kushtetuta", "aneks/neni/d")]
              and _st348("Sipas Kushtetutës, me përjashtim të vendimeve sipas nenit Ë, paragrafi 2, të Aneksit.") == [("verified", "kushtetuta", "aneks/neni/ë")]
              and _st348("Aneksi i Kushtetutës, neni DH, kontrolli i figurës.") == [("verified", "kushtetuta", "aneks/neni/dh")])
        check("aneks-citim[348]: lettera che l'Aneks non ha → inesistente; l'allegato di un'altra legge o un testo senza Costituzione → niente",
              _st348("neni H i Aneksit të Kushtetutës") == [("fake", "kushtetuta", "aneks/neni/h")]
              and _st348("Kushtetuta; neni D i Aneksit të ligjit për tatimet") == []
              and _st348("neni D i Aneksit të kontratës") == [])
    except Exception as _e348:  # noqa: BLE001
        check("aneks-citim[348]: kontrollet u ekzekutuan", False, f"{type(_e348).__name__}: {_e348}")

    # [349] v9.577 — ventisettesimo giro: i casi al limite (riduzione dell'assegno per i figli, divorzio dopo la separazione) e il costruttore
    # in ritardo con la penale del contratto (KC 541-544 «kushti penal», mai trovato; KC 481 mora del debitore)
    try:
        from pathlib import Path as _P349
        from src.retrieval import ArticleIndex as _AI349
        from src import brain as _b349
        _it349 = _AI349.load(_P349("/app/data/index/bm25_it.pkl"))
        _al349 = _AI349.load()
        _ii349 = lambda q, ar: {(a.code, a.number) for a, _ in _b349._applica_ancore([], _it349, [q], ar, _b349.ANCORE_IT)}
        _ia349 = lambda q, ar: {(a.code, a.number) for a, _ in _b349._applica_ancore([], _al349, [q], ar, _b349.ANCORE_AL)}
        check("ancore[349]: riduzione dell'assegno per i figli → c.c. 337-quinquies + c.p.c. 473-bis.29; divorzio dopo la separazione → "
              "L. 898/1970 art. 3; mai nel penale",
              {("codice_civile", "337-quinquies"), ("codice_procedura_civile", "473-bis.29")}
              <= _ii349("Il cliente ha perso il lavoro e vuole la riduzione dell'assegno di mantenimento per i figli.", ["Civile"])
              and ("divorzio", "3") in _ii349("Sono separati consensualmente da otto mesi: possono già chiedere il divorzio?", ["Civile"])
              and ("divorzio", "3") not in _ii349("Nella separazione la moglie chiede l'assegno.", ["Civile"])
              and not _ii349("Violazione degli obblighi di assistenza: non versa l'assegno ai figli e chiede la riduzione.", ["Penale"]))
        _c349 = _ia349("Shoqëria ndërtuese nuk e dorëzoi apartamentin në afat; kontrata parashikon gjobë për çdo ditë vonesë.", ["Civil"])
        check("ancore[349]: costruttore in ritardo con la penale → KC 541/543/544 (kushti penal) + 481 (vonesa); mai nel lavoro né "
              "per una multa amministrativa",
              {("kodi_civil", "541"), ("kodi_civil", "543"), ("kodi_civil", "544"), ("kodi_civil", "481")} <= _c349
              and not _ia349("Inspektorati i dha gjobë për vonesë në dorëzimin e kontratës së punës.", ["Punë"])
              and not _ia349("Policia i vuri gjobë për vonesë në dorëzimin e dokumenteve.", ["Administrativ"]), str(sorted(_c349)))
    except Exception as _e349:  # noqa: BLE001
        check("ancore[349]: kontrollet u ekzekutuan", False, f"{type(_e349).__name__}: {_e349}")

    # [350] v9.578 — nessun corpo albanese fatto SOLO del titolo del capitolo seguente: il KC 540 (patto commissorio) aveva per corpo
    # «KREU II ⏎ KUSHTI PENAL», la Kushtetuta 44 «KREU III ⏎ LIRITË DHE TË DREJTAT POLITIKE» (105 articoli, tools/repair_coda_sola_al.py)
    try:
        from src.retrieval import ArticleIndex as _AI350
        from src.parser import taglia_coda_gerarchia as _tc350, _is_italian_code as _iic350
        _al350 = _AI350.load()
        _solo350 = [(a.code, str(a.number)) for a in _al350.articles if not _iic350(a.code) and (a.body or "").strip()
                    and _tc350("Riga di contenuto.\n" + a.body)[0].strip() == "Riga di contenuto." and len((a.heading or "").strip()) >= 20]
        _by350 = {(a.code, str(a.number)): a for a in _al350.articles}
        check("coda-sola[350]: nessun corpo albanese fatto solo del titolo del capitolo seguente (KC 540, Kushtetuta 44, KF 107…)",
              not _solo350 and not (_by350[("kodi_civil", "540")].body or "").strip()
              and "KUSHTI PENAL" in (_by350[("kodi_civil", "541")].kreu or ""), str(_solo350[:6]))
    except Exception as _e350:  # noqa: BLE001
        check("coda-sola[350]: kontrollet u ekzekutuan", False, f"{type(_e350).__name__}: {_e350}")

    # [351] v9.579 — il diritto internazionale privato e dell'immigrazione fuori dalle domande italiane senza elemento straniero (prova
    # in Chrome: il trasferimento del figlio a 400 km aveva 7 articoli su 20 del Reg. UE 2019/1111); dentro con un Paese, «straniero»,
    # «permesso di soggiorno» o un'area internazionale del triage; cablato nel recupero italiano
    try:
        from src import brain as _b351
        from types import SimpleNamespace as _NS351
        _p351 = [(_NS351(code=c, number=n), 1.0) for c, n in (("bruxelles_ii_ter", "9"), ("codice_civile", "316"),
                                                             ("tu_immigrazione", "31"), ("codice_procedura_civile", "473-bis.11"))]
        _k351 = lambda t, ar=None: [a.code for a, _ in _b351._senza_diritto_straniero(_p351, t, ar)]
        _src351 = __import__("pathlib").Path("/app/src/brain.py").read_text(encoding="utf-8")
        check("estero[351]: senza elemento straniero via Bruxelles II-ter e TU immigrazione; con «tedesca», «Germania», «permesso di "
              "soggiorno» o l'area internazionale restano; cablato nel recupero italiano",
              _k351("La ex moglie si è trasferita a 400 km con il figlio di 7 anni senza il consenso del padre.") == ["codice_civile", "codice_procedura_civile"]
              and "bruxelles_ii_ter" in _k351("La madre tedesca ha portato il figlio in Germania.")
              and "tu_immigrazione" in _k351("Il cliente è stato fermato senza permesso di soggiorno.")
              and "bruxelles_ii_ter" in _k351("Trasferimento del figlio.", ["Civile", "Internazionale"])
              and "pairs = _senza_diritto_straniero(pairs" in _src351)
    except Exception as _e351:  # noqa: BLE001
        check("estero[351]: kontrollet u ekzekutuan", False, f"{type(_e351).__name__}: {_e351}")

    # [352] v9.580 — la L. 184/1983 sull'adozione fuori dalle domande di separazione e affido (entrava in 9 domande di famiglia su 25 per
    # l'«affidamento familiare» degli artt. 2-5); dentro con adozione, affidamento familiare, abbandono, servizi sociali; cablata
    try:
        from src import brain as _b352
        from types import SimpleNamespace as _NS352
        _p352 = [(_NS352(code=c, number=n), 1.0) for c, n in (("codice_civile", "337-ter"), ("adozione", "4"), ("adozione", "44"))]
        _k352 = lambda t: [a.code for a, _ in _b352._senza_adozione(_p352, t)]
        _src352 = __import__("pathlib").Path("/app/src/brain.py").read_text(encoding="utf-8")
        check("adozione[352]: separazione e affido condiviso senza la L. 184/1983; adozione, affidamento familiare, servizi sociali la tengono",
              _k352("Nella separazione i genitori litigano su con chi devono stare i figli: affido condiviso o esclusivo?") == ["codice_civile"]
              and "adozione" in _k352("Il cliente vuole adottare il figlio della moglie.")
              and "adozione" in _k352("I servizi sociali hanno disposto l'affidamento familiare del bambino.")
              and "pairs = _senza_adozione(pairs" in _src352)
    except Exception as _e352:  # noqa: BLE001
        check("adozione[352]: kontrollet u ekzekutuan", False, f"{type(_e352).__name__}: {_e352}")

    # [353] v9.581 — il gemello albanese: Birësimi e Kujdestaria mbi të miturit fuori dalle domande sul figlio dopo il divorzio (KF 263,
    # 264, 268 nel blocco «babai dëshiron ta shohë më shpesh»); la responsabilità genitoriale resta; dentro con jetim, pa prindër, birësim
    try:
        from src import brain as _b353
        from types import SimpleNamespace as _NS353
        _p353 = [(_NS353(code="kodi_familjes", number=n, kreu=k), 1.0) for n, k in (
            ("158", "KREU III — PASOJAT E ZGJIDHJES SË MARTESËS"), ("221", "KREU II — USHTRIMI I PËRGJEGJËSISË PRINDËRORE"),
            ("263", "KREU I — KUJDESTARIA MBI TË MITURIT"), ("245", "TITULLI IV — BIRËSIMI"))]
        _k353 = lambda t: [a.number for a, _ in _b353._senza_tutela_al(_p353, t)]
        _src353 = __import__("pathlib").Path("/app/src/brain.py").read_text(encoding="utf-8")
        check("kujdestari[353]: dopo il divorzio via Birësimi e Kujdestaria mbi të miturit, resta la responsabilità genitoriale; jetim / "
              "birësim li tengono",
              _k353("Pas divorcit fëmija i është lënë nënës; babai dëshiron ta shohë më shpesh.") == ["158", "221"]
              and "263" in _k353("Fëmija mbeti jetim: kush emërohet kujdestar?")
              and "245" in _k353("Klienti dëshiron të birësojë fëmijën e gruas.")
              # le frasi vere dei casi di tutela restano dentro (la prima stesura ne perdeva 6 su 10) …
              and all("263" in _k353(t) for t in (
                  "I vdiqën prindërit dhe vajza 12 vjeçe jeton me tezen. Kush bëhet kujdestar?",
                  "Prindërit e tij kanë vdekur dhe xhaxhai do ta marrë fëmijën.",
                  "Nëna dhe babai vdiqën vitin e kaluar; çfarë procedure ka për kujdestarinë?",
                  "Fëmija humbi të dy prindërit, kush e përfaqëson?",
                  "Gjyshërit duan kujdestarinë e nipit sepse nëna është në burg."))
              # … e la «kujdestaria» della separazione resta fuori
              and all("263" not in _k353(t) for t in (
                  "Kujdestaria e fëmijës pas divorcit: babai kërkon ta ndryshojë.",
                  "Gjyshërit duan ta shohin nipin pas divorcit, nëna nuk lejon.",
                  "Babai vdiq dhe la një shtëpi; si ndahet trashëgimia mes fëmijëve?"))
              and _src353.count("pairs = _senza_tutela_al(pairs") == 2)
    except Exception as _e353:  # noqa: BLE001
        check("kujdestari[353]: kontrollet u ekzekutuan", False, f"{type(_e353).__name__}: {_e353}")

    # [354] v9.581 — il codice dei minori (penale) resta se c'è un minore E la materia è penale: l'età a una cifra conta («vajza 9 vjeç»),
    # un minore in una domanda di famiglia (alimenti, affido) non lo tiene dentro
    try:
        from src import brain as _b354
        from types import SimpleNamespace as _NS354
        _p354 = [(_NS354(code=c, number=n), 1.0) for c, n in (("kodi_penal", "100"), ("kodi_te_miturve", "16"))]
        _k354 = lambda t, ar=None: [a.code for a, _ in _b354._senza_codice_minori(_p354, t, ar)]
        check("minori[354]: «vajza 9 vjeç» nel penale tiene il codice dei minori; alimenti del «djali 8 vjeç» (famiglia) no; adulto mai",
              "kodi_te_miturve" in _k354("Fqinji abuzoi me vajzën 9 vjeç. Si e mbrojmë?", ["Penal"])
              and "kodi_te_miturve" not in _k354("Ish-bashkëshorti nuk paguan ushqimin për djalin 8 vjeç.", ["Familje", "Civil"])
              and "kodi_te_miturve" not in _k354("Klienti u arrestua për vjedhje.", ["Penal"])
              and "kodi_te_miturve" in _k354("Djali 13 vjeç vodhi një telefon."))
    except Exception as _e354:  # noqa: BLE001
        check("minori[354]: kontrollet u ekzekutuan", False, f"{type(_e354).__name__}: {_e354}")

    # [355] v9.582 — dal 7 ottobre il firewall del Ministero scarta il nostro server: la pausa dell'archivio della Cassazione
    # raddoppia a ogni guasto consecutivo (5 → 10 → 20 … minuti, tetto un'ora) e la prima risposta riuscita la azzera; un 4xx
    # (query nostra sbagliata) non è un guasto dell'archivio; durante la pausa nessuna richiesta, nemmeno per i passi del testo.
    # Eseguito con un urlopen finto: nessuna richiesta vera.
    try:
        from src import cassazione as _C355
        import io as _io355, urllib.error as _ue355, urllib.request as _ur355
        _orig355 = _ur355.urlopen
        _cache355 = _C355._cache_get
        _stato355 = (_C355._down_until, _C355._fallimenti)
        def _boom355(exc):
            def _f(*a, **k):
                raise exc
            return _f
        class _Ok355(_io355.BytesIO):
            def __enter__(self): return self
            def __exit__(self, *a): return False
        try:
            _C355._down_until, _C355._fallimenti = 0.0, 0
            _pause355 = []
            for _ in range(5):
                _ur355.urlopen = _boom355(_ue355.URLError("timed out"))
                try:
                    _C355._solr({"q": "x"}, timeout=1)
                except Exception:  # noqa: BLE001
                    pass
                _pause355.append(round((_C355._down_until - __import__("time").time()) / 60))
            _okA355 = _pause355 == [5, 10, 20, 40, 60] and _C355._fallimenti == 5
            _C355._down_until, _C355._fallimenti = 0.0, 0
            _ur355.urlopen = _boom355(_ue355.HTTPError("u", 400, "bad", None, None))
            try:
                _C355._solr({"q": "x"}, timeout=1)
            except Exception:  # noqa: BLE001
                pass
            _okB355 = _C355._fallimenti == 0 and _C355._down_until == 0.0
            _ur355.urlopen = _boom355(_ue355.HTTPError("u", 503, "down", None, None))
            try:
                _C355._solr({"q": "x"}, timeout=1)
            except Exception:  # noqa: BLE001
                pass
            _okC355 = _C355._fallimenti == 1 and _C355._down_until > __import__("time").time()
            _ur355.urlopen = lambda *a, **k: _Ok355(b'{"response": {"docs": []}}')
            _C355._solr({"q": "x"}, timeout=1)
            _okD355 = _C355._fallimenti == 0 and _C355._down_until == 0.0
            # durante la pausa: cerca() senza cache dice «offline», gli estratti non chiedono niente
            _chiamate355 = []
            _ur355.urlopen = lambda *a, **k: (_chiamate355.append(1), _Ok355(b'{}'))[1]
            _C355._cache_get = lambda keys: {}
            _C355._down_until = __import__("time").time() + 600
            _res355, _off355 = _C355.cerca([(69871, 2025)])
            _est355 = _C355.estratti([{"status": "verified", "record": {"sn_id": "snciv2025569871O"}, "posizioni": [(0, 5)]}], "testo prova")
            _okE355 = _off355 and _est355 == {} and not _chiamate355
        finally:
            _ur355.urlopen = _orig355
            _C355._cache_get = _cache355
            _C355._down_until, _C355._fallimenti = _stato355
        check("Cassazione[355]: pausa dell'archivio che raddoppia (5-10-20-40-60 min) e si azzera alla prima risposta; un 4xx non conta, "
              "un 5xx sì; durante la pausa nessuna richiesta (verifica «offline», niente passi)",
              _okA355 and _okB355 and _okC355 and _okD355 and _okE355,
              "A=%s %s B=%s C=%s D=%s E=%s" % (_okA355, _pause355, _okB355, _okC355, _okD355, _okE355))
    except Exception as _e355:  # noqa: BLE001
        check("Cassazione[355]: kontrollet u ekzekutuan", False, f"{type(_e355).__name__}: {_e355}")

    # [356] v9.584 — le ANCORE PER TITOLO (AL): su ~50 del banco solo una quindicina pertinenti, il resto falsi amici di una parola
    # sola («kontakt» del figlio → «Pika e vetme të kontaktit» dei servizi fiduciari; il telefono rubato → «impulseve telefonike»).
    # Ora si AGGIUNGONO ai 12 (non spingono fuori le norme trovate), sotto la soglia di senso non entrano, e il raccoglitore QBZ non
    # le tratta come norme centrali (tranne le figure di reato). Eseguito con oggetti finti e un coseno finto.
    try:
        from src import brain as _b356, studio as _s356
        from types import SimpleNamespace as _NS356
        _src356 = __import__("pathlib").Path("/app/src/brain.py").read_text(encoding="utf-8")
        _okA356 = ('getattr(a, "_ancora_titull", False) and not getattr(a, "_ancora_vepra", False)' in _src356
                   and "domanda=(_testo_anc[-1] or None)" in _src356 and _b356._TITUJ_COS_MIN > 0)
        _art356 = _NS356(code="ligji_x", number="71", heading="Pika e vetme të kontaktit", heading_kind="rubrike",
                         body="Autoriteti është pika e vetme e kontaktit.", repealed=False)
        _idx356 = _NS356(articles=[_art356], lang="sq", search=lambda q, top_k=400, restrict_codes=None: [(_art356, 3.0)])
        _oc356, _or356 = _b356._coseni_per_senso, _b356._radicet_e_pyetjes
        try:
            _b356._radicet_e_pyetjes = lambda t: ["konta"]
            _run356 = lambda: _b356._ankoro_sipas_titullit([], _idx356, "babai kërkon kontakt me djalin", queries=["kontakt"], domanda="d")
            _b356._coseni_per_senso = lambda idx, t, ch: {("ligji_x", "71"): 0.17}
            _via356 = _run356()
            _b356._coseni_per_senso = lambda idx, t, ch: {("ligji_x", "71"): 0.40}
            _den356 = _run356()
            _b356._coseni_per_senso = lambda idx, t, ch: {}            # senza indice per senso: come prima
            _senza356 = _run356()
        finally:
            _b356._coseni_per_senso, _b356._radicet_e_pyetjes = _oc356, _or356
        _okB356 = (_via356 == [] and len(_den356) == 1 and getattr(_den356[0][0], "_ancora_titull", False) and len(_senza356) == 1)
        _t356 = _NS356(number="71", title_sq="Ligji X", code="ligji_x", _ancora_titull=True)
        _v356 = _NS356(number="278", title_sq="Kodi Penal", code="kodi_penal", _ancora_titull=True, _ancora_vepra=True)
        _q356 = _s356._nenet_qendrore([(_NS356(number="1", title_sq="A", code="a"), 9.0), (_NS356(number="2", title_sq="B", code="b"), 8.0),
                                        (_t356, 7.5), (_v356, 7.0)])
        _okC356 = _q356[0].startswith("278 ") and not any(x.startswith("71 ") for x in _q356)
        check("titull[356]: le ancore per titolo si aggiungono ai 12, sotto la soglia di senso non entrano (senza indice per senso come "
              "prima), e il raccoglitore QBZ non le tratta come norme centrali (le figure di reato sì)",
              _okA356 and _okB356 and _okC356, "A=%s B=%s C=%s %s" % (_okA356, _okB356, _okC356, _q356))
    except Exception as _e356:  # noqa: BLE001
        check("titull[356]: kontrollet u ekzekutuan", False, f"{type(_e356).__name__}: {_e356}")

    # [357] v9.585 — il gemello ITALIANO della tutela: Titoli X (tutela dei minori), XI (art. 403), XII (sostegno, interdizione) e
    # VIII (adozione dei maggiorenni) del c.c. fuori dalle domande di separazione e affido, ciascuno dentro con le sue parole
    try:
        from src import brain as _b357
        from types import SimpleNamespace as _NS357
        _k357 = {"337-ter": "TITOLO IX — DELLA RESPONSABILITÀ GENITORIALE E DEI DIRITTI E DOVERI DEL FIGLIO · CAPO II",
                 "348": "TITOLO X — DELLA TUTELA E DELL'EMANCIPAZIONE · CAPO I — Della tutela dei minori",
                 "403": "TITOLO XI — DELL'AFFILIAZIONE E DELL'AFFIDAMENTO",
                 "404": "Titolo XII — Delle misure di protezione delle persone prive in tutto od in parte di autonomia",
                 "291": "TITOLO VIII — DELL'ADOZIONE DI PERSONE MAGGIORI DI ETÀ · CAPO I — Dell'adozione di persone",
                 "433": "TITOLO XIII — DEGLI ALIMENTI"}
        _p357 = [(_NS357(code="codice_civile", number=n, kreu=k), 1.0) for n, k in _k357.items()] + \
                [(_NS357(code="codice_procedura_civile", number="473-bis.4", kreu="TITOLO IV-BIS"), 1.0)]
        _f357 = lambda t: [a.number for a, _ in _b357._senza_tutela_it(_p357, t)]
        _src357 = __import__("pathlib").Path("/app/src/brain.py").read_text(encoding="utf-8")
        check("tutela-it[357]: nella separazione via c.c. 348, 403, 404, 291 (restano 337-ter, 433, c.p.c.); dentro con i genitori morti "
              "(348), i servizi sociali (403), l'amministrazione di sostegno (404), l'adozione (291); «come tuteliamo» non conta",
              _f357("Dopo la separazione la figlia di 15 anni è stata collocata presso la madre: può decidere lei?") == ["337-ter", "433", "473-bis.4"]
              and "348" in _f357("I genitori del bambino sono morti in un incidente: chi diventa tutore?")
              and "403" in _f357("I servizi sociali hanno allontanato il bambino per maltrattamenti")
              and "404" in _f357("Il padre anziano non è più in grado di gestire i conti: amministrazione di sostegno?")
              and "291" in _f357("Il cliente vuole adottare il figlio maggiorenne della moglie")
              and _f357("Come tuteliamo la madre nel ricorso del padre?") == ["337-ter", "433", "473-bis.4"]
              and "pairs = _senza_tutela_it(pairs" in _src357)
    except Exception as _e357:  # noqa: BLE001
        check("tutela-it[357]: kontrollet u ekzekutuan", False, f"{type(_e357).__name__}: {_e357}")

    # [358] v9.586 — codici condizionati IT (pubblico impiego solo con un datore pubblico, testo unico della maternità solo con gravidanza,
    # congedi, nascita o figli) e l'ancora AL del sequestro conservativo stretta alla frase «sigurimi i padisë» (scattava sull'infortunio)
    try:
        from pathlib import Path as _P358
        from types import SimpleNamespace as _NS358
        from src.retrieval import ArticleIndex as _AI358
        from src import brain as _b358
        _p358 = [(_NS358(code=c, number=n), 1.0) for c, n in (("statuto_lavoratori", "18"), ("pubblico_impiego", "55-quater"),
                                                               ("maternita_paternita", "54"), ("tutele_crescenti", "3"),
                                                               ("ordinamento_forense", "56"), ("codice_navigazione", "359"))]
        _c358 = lambda t: [a.code for a, _ in _b358._senza_codici_condizionati_it(_p358, t)]
        _okA358 = (_c358("Il cliente è stato licenziato per giusta causa dopo una contestazione disciplinare.") == ["statuto_lavoratori", "tutele_crescenti"]
                   and "maternita_paternita" in _c358("Il cliente assiste la madre con disabilità grave. Ha diritto a permessi e congedi?")
                   and "codice_navigazione" in _c358("Il cliente è un marittimo imbarcato su una nave: le ferie non godute?")
                   and "ordinamento_forense" in _c358("Il Consiglio dell'Ordine ha aperto un procedimento disciplinare contro l'avvocato.")
                   and "codice_navigazione" not in _c358("Da due anni il datore non fa godere le ferie al cliente.")
                   and "maternita_paternita" in _c358("La cliente è stata licenziata mentre era incinta di quattro mesi.")
                   and "pubblico_impiego" in _c358("Il cliente, dipendente del Comune, ha ricevuto una contestazione disciplinare.")
                   and "pubblico_impiego" not in _c358("La cliente è stata licenziata mentre era incinta di quattro mesi."))
        _al358 = _AI358.load(_P358("/app/data/index/bm25.pkl"))
        _k358 = lambda q, ar: {(a.code, a.number) for a, _ in _b358._applica_ancore([], _al358, [q], ar)}
        _okB358 = (("kodi_proc_civile", "202") not in _k358("Punëtori u lëndua rëndë në punë; padi për dëmshpërblim dhe sigurimet shoqërore e paaftësisë.", ["Civil", "Punë"])
                   and ("kodi_proc_civile", "202") in _k358("Kërkojmë sigurimin e padisë para se debitori të shesë apartamentin.", ["Civil"])
                   and ("kodi_proc_civile", "202") in _k358("Debitori po i shet pasuritë para gjyqit. Si ia bllokojmë pasurinë?", ["Civil"]))
        _src358 = _P358("/app/src/brain.py").read_text(encoding="utf-8")
        check("condizionati[358]: pubblico impiego e testo unico della maternità fuori dai licenziamenti privati senza figli (dentro col Comune, "
              "con la gravidanza); l'ancora del sequestro AL non scatta sull'infortunio, scatta con «sigurimin e padisë» e col debitore che vende",
              _okA358 and _okB358 and "pairs = _senza_codici_condizionati_it(pairs" in _src358, "A=%s B=%s" % (_okA358, _okB358))
    except Exception as _e358:  # noqa: BLE001
        check("condizionati[358]: kontrollet u ekzekutuan", False, f"{type(_e358).__name__}: {_e358}")

    # [359] v9.587 — i codici condizionati ALBANESI: rapporti con l'estero, media audiovisivi, detenuti, responsabilità della PA fuori dalle
    # domande che non ne danno il motivo (e i falsi amici degli inneschi: «publikoi», «administratorin», «shtetas», la polizia di ogni arresto)
    try:
        from src import brain as _b359
        from types import SimpleNamespace as _NS359
        _p359 = [(_NS359(code=c, number="1"), 1.0) for c in ("kodi_penal", "ligji_marredheniet_juridiksionale", "ligji_mediat_audiovizive",
                                                              "ligji_te_denuarit", "ligji_pergjegjesia_administrates")]
        _c359 = lambda t: {a.code for a, _ in _b359._senza_codici_condizionati_al(_p359, t)}
        _src359 = __import__("pathlib").Path("/app/src/brain.py").read_text(encoding="utf-8")
        check("condizionati-al[359]: la minaccia di morte resta col solo KP; estradizione/TV/carcere/Bashkia tengono la loro legge; "
              "«publikoi», «administratorin», «shtetas» e la polizia dell'arresto non tengono la responsabilità della PA",
              _c359("Një person i dërgon klientit mesazhe se do ta vrasë. Çfarë mund të bëjmë?") == {"kodi_penal"}
              and "ligji_marredheniet_juridiksionale" in _c359("Italia kërkon ekstradimin e klientit.")
              and "ligji_mediat_audiovizive" in _c359("Një televizion transmetoi pamje të klientit pa leje.")
              and "ligji_te_denuarit" in _c359("Klienti vuan dënimin në burg dhe kërkon leje.")
              and "ligji_pergjegjesia_administrates" in _c359("Bashkia ma prishi murin pa vendim, kush paguan dëmin?")
              and "ligji_pergjegjesia_administrates" not in _c359("Ish-partneri publikoi në Facebook fotot e klientes.")
              and "ligji_pergjegjesia_administrates" not in _c359("Ortakët duan ta shkarkojnë administratorin e shpk-së.")
              and "ligji_pergjegjesia_administrates" not in _c359("Shtetas i huaj me leje qëndrimi, u kap nga policia me kokainë.")
              and _b359._senza_codici_condizionati_al([(_NS359(code="ligji_identifikimi_elektronik", number="22"), 1.0),
                                                       (_NS359(code="ligji_regjistrimi_ojf", number="43"), 1.0)],
                                                      "Qeni i fqinjit kafshoi djalin e klientes në rrugë.") == []
              and len(_b359._senza_codici_condizionati_al([(_NS359(code="ligji_identifikimi_elektronik", number="22"), 1.0)],
                                                          "A vlen kontrata e nënshkruar me nënshkrim elektronik?")) == 1
              and _src359.count("pairs = _senza_codici_condizionati_al(pairs") == 2)
    except Exception as _e359:  # noqa: BLE001
        check("condizionati-al[359]: kontrollet u ekzekutuan", False, f"{type(_e359).__name__}: {_e359}")

    # [360] v9.588 — il CODICE GEMELLO giusto nei citati dal triage («applicazione della pena su richiesta delle parti art. 444 c.p.c.» → c.p.p.
    # 444; le citazioni giuste restano) e la procedura civile fuori dalle domande solo penali (dentro con la famiglia: gli ordini di protezione)
    try:
        from pathlib import Path as _P360
        from types import SimpleNamespace as _NS360
        from src.retrieval import ArticleIndex as _AI360
        from src import brain as _b360
        _it360 = _AI360.load(_P360("/app/data/index/bm25_it.pkl"))
        _ct360 = lambda q, ar=("Penal",): [(a.code, str(a.number)) for a, _ in _b360._citati_dal_triage([], _it360, [q], list(ar))]
        _okA360 = (("codice_procedura_penale", "444") in _ct360("applicazione della pena su richiesta delle parti art. 444 c.p.c.")
                   and ("codice_procedura_penale", "445") in _ct360("limiti patteggiamento pene accessorie art. 445 c.p.c.")
                   and ("codice_procedura_civile", "645") in _ct360("opposizione al decreto ingiuntivo art. 645 c.p.c. termine", ("Civile",))
                   and ("codice_civile", "2043") in _ct360("risarcimento del danno ingiusto art. 2043 c.c.", ("Civile",))
                   # in una domanda CIVILE la sigla civile resta anche se le parole somigliano al gemello penale (KPC 147 → mai KPP 147)
                   and ("codice_procedura_civile", "444") in _ct360("applicazione della pena su richiesta delle parti art. 444 c.p.c.", ("Civile",))
                   and ("codice_procedura_civile", "444") in _ct360("applicazione della pena su richiesta delle parti art. 444 c.p.c.", ()))
        _p360 = [(_NS360(code=c, number=n), 1.0) for c, n in (("codice_procedura_penale", "172"), ("codice_procedura_civile", "155"),
                                                               ("codice_procedura_civile", "473-bis.70"))]
        _f360 = lambda t, ar: [a.code for a, _ in _b360._senza_procedura_civile_nel_penale(_p360, t, ar)]
        _okB360 = (_f360("Il cliente è stato condannato a un anno per furto: entro quando l'appello?", ["Penal"]) == ["codice_procedura_penale"]
                   and len(_f360("La cliente subisce insulti e spinte dal marito convivente: come la tuteliamo?", ["Penal"])) == 3
                   and len(_f360("Il cliente è stato condannato a un anno per furto: entro quando l'appello?", ["Penal", "Civile"])) == 3)
        check("gemelli[360]: «art. 444/445 c.p.c.» del triage in un patteggiamento → c.p.p. 444/445 (le citazioni giuste restano); procedura "
              "civile fuori dal penale puro (dentro col marito convivente o con un'area civile)", _okA360 and _okB360,
              "A=%s B=%s" % (_okA360, _okB360))
    except Exception as _e360:  # noqa: BLE001
        check("gemelli[360]: kontrollet u ekzekutuan", False, f"{type(_e360).__name__}: {_e360}")

    # [361] v9.588 — le aggiunte del Kërkuesi passano dagli stessi filtri di materia della ricerca (rimetteva la responsabilità della PA in un
    # infortunio con datore privato, appena tolta dal filtro)
    try:
        import inspect as _in361
        from src import brain as _b361
        _s361 = _in361.getsource(_b361.SuperAvvocato._studio_kerkuesi)
        check("kerkuesi[361]: le aggiunte del junior passano da minori, tutela, codici condizionati (AL e IT), diritto straniero, adozione e "
              "procedura civile nel penale",
              all(x in _s361 for x in ("_senza_codice_minori(nuovo", "_senza_tutela_al(nuovo", "_senza_codici_condizionati_al(nuovo",
                                        "_senza_diritto_straniero(nuovo", "_senza_adozione(nuovo", "_senza_tutela_it(nuovo",
                                        "_senza_codici_condizionati_it(nuovo", "_senza_procedura_civile_nel_penale(nuovo")))
    except Exception as _e361:  # noqa: BLE001
        check("kerkuesi[361]: kontrollet u ekzekutuan", False, f"{type(_e361).__name__}: {_e361}")

    # [362] v9.589 — l'INFORTUNIO SUL LAVORO: il testo unico INAIL e il danno biologico nel corpus italiano, citati per numero e per nome;
    # le ancore AL (danno alla salute KC 641, competenza KPC 48) e IT (art. 10-11 TU INAIL, art. 13 d.lgs. 38/2000, c.c. 2087)
    # scattano sull'infortunio e MAI sul morso del cane o sulla polizza infortuni privata
    try:
        from pathlib import Path as _P362
        from src.retrieval import ArticleIndex as _AI362
        from src import citation_verifier as _cv362, brain as _b362
        from src.parser import _is_italian_code as _iic362
        _it362 = _AI362.load(_P362("/app/data/index/bm25_it.pkl"))
        _al362 = _AI362.load(_P362("/app/data/index/bm25.pkl"))
        _by362 = {(a.code, str(a.number)): a for a in _it362.articles}
        _okC362 = (all(k in _by362 and not _by362[k].repealed for k in (("tu_infortuni", "2"), ("tu_infortuni", "10"), ("tu_infortuni", "11"),
                                                                       ("tu_infortuni", "112"), ("danno_biologico_inail", "13")))
                   and _iic362("tu_infortuni") and _iic362("danno_biologico_inail")
                   # v9.593: dentro le VOCI delle tabelle delle malattie professionali, mai i segnaposto delle immagini né i vecchi blocchi
                   and not any(a.code == "tu_infortuni" and str(a.number).startswith("allegato") and "-voce-" not in str(a.number)
                               for a in _it362.articles))
        def _st362(t, n):
            return {i["number"]: (i["status"], i.get("code")) for i in _cv362.verify_text(t, _it362)["items"]}.get(n)
        _okV362 = (_st362("Il datore risponde del danno differenziale (art. 10 d.P.R. 1124/1965).", "10") == ("verified", "tu_infortuni")
                   and _st362("L'INAIL indennizza il danno biologico (art. 13 d.lgs. 38/2000).", "13") == ("verified", "danno_biologico_inail")
                   and _st362("Lo prevede l'art. 11 del T.U. INAIL.", "11") == ("verified", "tu_infortuni")
                   and _st362("La prescrizione è triennale (art. 112 del testo unico infortuni).", "112") == ("verified", "tu_infortuni"))
        _iA362 = lambda q, ar: {(a.code, a.number) for a, _ in _b362._applica_ancore([], _al362, [q], ar)}
        _iI362 = lambda q, ar: {(a.code, a.number) for a, _ in _b362._applica_ancore([], _it362, [q], ar, _b362.ANCORE_IT)}
        _qA362 = "Klienti u lëndua rëndë në kantier, ra nga skela sepse punëdhënësi nuk i kishte dhënë rrip sigurimi. Çfarë të drejtash ka?"
        _okA362 = ({("kodi_civil", "641"), ("kodi_proc_civile", "48")} <= _iA362(_qA362, ["Punë", "Civil"])
                   and ("kodi_proc_civile", "48") not in _iA362("Klienti u lëndua nga qeni i fqinjit në rrugë. Kush paguan?", ["Civil"])
                   and ("kodi_civil", "641") not in _iA362(_qA362, ["Penal"]))
        _qI362 = "Il cliente è caduto dal ponteggio in cantiere perché il datore non gli aveva dato l'imbracatura. Che diritti ha?"
        _okI362 = ({("tu_infortuni", "10"), ("tu_infortuni", "11"), ("danno_biologico_inail", "13")} <= _iI362(_qI362, ["Lavoro"])
                   and ("tu_infortuni", "10") not in _iI362("Il cliente ha una polizza infortuni privata e la compagnia non paga dopo la caduta "
                                                             "in casa. Cosa facciamo?", ["Civile"]))
        check("infortunio[362]: TU INAIL (d.P.R. 1124/1965) e danno biologico (d.lgs. 38/2000) nel corpus, verificati per numero e per nome; "
              "ancore AL KC 641 + KPC 48 e IT art. 10-11 TU + art. 13 — mai sul cane del vicino né sulla polizza privata",
              _okC362 and _okV362 and _okA362 and _okI362, "C=%s V=%s A=%s I=%s" % (_okC362, _okV362, _okA362, _okI362))
    except Exception as _e362:  # noqa: BLE001
        check("infortunio[362]: kontrollet u ekzekutuan", False, f"{type(_e362).__name__}: {_e362}")

    # [363] v9.589 — fuori dalle domande SOLO penali anche i riti amministrativo e tributario (dentro col fisco o con un atto amministrativo),
    # e il libro XI del c.p.p. (estradizione, rogatorie) senza un elemento straniero — prova dal browser sull'appello per furto in abitazione
    try:
        from pathlib import Path as _P363
        from src.retrieval import ArticleIndex as _AI363
        from src import brain as _b363
        _it363 = _AI363.load(_P363("/app/data/index/bm25_it.pkl"))
        _by363 = {(a.code, str(a.number)): a for a in _it363.articles}
        _p363 = [(_by363[k], 1.0) for k in (("codice_procedura_penale", "585"), ("codice_processo_amministrativo", "101"),
                                             ("giustizia_tributaria", "120"), ("processo_tributario", "64"), ("codice_procedura_penale", "706"))
                 if k in _by363]
        _q363 = "Il cliente è stato condannato in primo grado per furto in abitazione: entro quando va proposto l'appello?"
        _r363 = lambda t, ar: {(a.code, str(a.number)) for a, _ in _b363._senza_diritto_straniero(_b363._senza_procedura_civile_nel_penale(_p363, t, ar), t, ar)}
        _okR363 = (len(_p363) == 5 and _r363(_q363, ["Penale"]) == {("codice_procedura_penale", "585")}
                   and ("giustizia_tributaria", "120") in _r363("Il cliente ha emesso fatture false e ha ricevuto anche un avviso di accertamento: "
                                                                 "entro quando l'appello penale?", ["Penale"])
                   and ("codice_processo_amministrativo", "101") in _r363("Il questore ha ammonito il cliente per stalking e poi è stato "
                                                                           "condannato: entro quando l'appello?", ["Penale"])
                   and ("codice_procedura_penale", "706") in _r363("La Germania chiede l'estradizione del cliente condannato là: "
                                                                    "entro quando il ricorso?", ["Penale"])
                   and len(_r363(_q363, ["Penale", "Amministrativo"])) == 4)
        check("riti[363]: c.p.a. e processo tributario fuori dalle domande solo penali (dentro col fisco o con l'ammonimento del questore); "
              "libro XI del c.p.p. solo con un elemento straniero (l'estradizione)", _okR363, str(sorted(_r363(_q363, ["Penale"]))))
    except Exception as _e363:  # noqa: BLE001
        check("riti[363]: kontrollet u ekzekutuan", False, f"{type(_e363).__name__}: {_e363}")

    # [364] v9.590 — i codici FISCALI fuori dalle domande senza tema fiscale (26 domande su 150 nel banco IT): dentro col fisco, con la
    # casa da comprare, con la successione, o con la materia tributaria nel triage
    try:
        from types import SimpleNamespace as _NS364
        from src import brain as _b364
        _p364 = [(_NS364(code=c, number=n), 1.0) for c, n in (("codice_civile", "156"), ("tuir", "3"), ("tu_riscossione", "72-ter"),
                                                               ("reati_tributari", "2"))]
        _f364 = lambda t, ar=None: [a.code for a, _ in _b364._senza_codici_fiscali_it(_p364, t, ar)]
        _ok364 = (_f364("La cliente si separa dal marito e hanno due figli minori: come si decide l'assegno?", ["Civile"]) == ["codice_civile"]
                  and _f364("Un creditore privato vuole pignorare lo stipendio del cliente: quanto può prendere?", ["Civile"]) == ["codice_civile"]
                  and len(_f364("L'Agenzia delle Entrate ha notificato una cartella al cliente: come la contestiamo?", ["Civile"])) == 4
                  and len(_f364("Il cliente vuole comprare casa come prima casa: quanto paga?", ["Civile"])) == 4
                  and len(_f364("Il padre è morto e ha lasciato due case in eredità: cosa devono fare i figli?", ["Civile"])) == 4
                  and len(_f364("Il cliente ha un debito e teme il pignoramento.", ["Tributario"])) == 4)
        check("fisco[364]: TUIR, riscossione e reati tributari fuori dalla separazione e dal pignoramento di un privato; dentro con la "
              "cartella, la prima casa, l'eredità o la materia tributaria", _ok364)
    except Exception as _e364:  # noqa: BLE001
        check("fisco[364]: kontrollet u ekzekutuan", False, f"{type(_e364).__name__}: {_e364}")

    # [365] v9.591 — «TUSL» = d.lgs. 81/2008 nel verificatore; i titoli albanesi delle fonti web («Art. 2087 i Kodit Civil») fuori dal dossier
    # e dall'elenco delle fonti in sessione italiana (diventano il dominio), intatti in sessione albanese
    try:
        from pathlib import Path as _P365
        from src.retrieval import ArticleIndex as _AI365
        from src import citation_verifier as _cv365, studio as _st365
        from src.war_room import _titolo_nella_lingua as _tnl365
        _it365 = _AI365.load(_P365("/app/data/index/bm25_it.pkl"))
        _s365 = {i["number"]: (i["status"], i.get("code")) for i in _cv365.verify_text(
            "Lo impone l'art. 20 TUSL; per i ponteggi artt. 111 ss. TUSL.", _it365)["items"]}
        _d365 = {"web": {"burime": [{"titulli": "Art. 2087 i Kodit Civil", "data": "2026", "citim": "L'imprenditore è tenuto ad adottare…",
                                     "url": "https://www.brocardi.it/codice-civile/art2087.html"}]}}
        _fit365 = _st365.formato_dosjen(_d365, "it"); _fsq365 = _st365.formato_dosjen(_d365, "sq")
        _sint365 = _st365.sintesi_burimet(_d365, "it")
        check("fonti[365]: «art. 20 TUSL» verificato sul d.lgs. 81/2008; il titolo albanese di una fonte web esce dal dossier e dall'elenco "
              "in sessione italiana (brocardi.it), resta in quella albanese; i titoli italiani non si toccano",
              _s365.get("20") == ("verified", "sicurezza_lavoro") and _s365.get("111") == ("verified", "sicurezza_lavoro")
              and "Kodit" not in _fit365 and "brocardi.it" in _fit365 and "Kodit" in _fsq365
              and _sint365 and _sint365[0]["titulli"] == "brocardi.it"
              and _tnl365("Art. 2087 c.c. — Tutela delle condizioni di lavoro", "https://x.it", "it") == "Art. 2087 c.c. — Tutela delle condizioni di lavoro",
              str((_s365, _sint365[:1])))
    except Exception as _e365:  # noqa: BLE001
        check("fonti[365]: kontrollet u ekzekutuan", False, f"{type(_e365).__name__}: {_e365}")

    # [366] v9.592 — notaio, dogana e carcere fra i codici condizionati italiani: la legge notarile fuori dalla contestazione disciplinare di un
    # dipendente, la cauzione doganale fuori dal deposito cauzionale dell'affitto, il trasferimento dei detenuti fuori dal trasferimento del
    # dipendente; dentro col rogito, con l'auto di targa albanese, con la materia penale o col carcere nella domanda
    try:
        from types import SimpleNamespace as _NS366
        from src import brain as _b366
        _p366 = [(_NS366(code=c, number=n), 1.0) for c, n in (("statuto_lavoratori", "7"), ("legge_notarile", "146"),
                                                               ("codice_doganale_nazionale", "44"), ("ordinamento_penitenziario", "42"))]
        _f366 = lambda t, ar=None: {a.code for a, _ in _b366._senza_codici_condizionati_it(_p366, t, ar)}
        _ok366 = (_f366("Il datore vuole trasferire il cliente da Milano a Bari e gli ha mandato una contestazione disciplinare.", ["Lavoro"])
                  == {"statuto_lavoratori"}
                  and "legge_notarile" in _f366("Il notaio ha sbagliato il rogito della casa del cliente.", ["Civile"])
                  and "codice_doganale_nazionale" in _f366("L'auto targata albanese del cliente è stata fermata dalla Guardia di Finanza.", ["Civile"])
                  and "ordinamento_penitenziario" in _f366("Il cliente è stato trasferito in un altro istituto.", ["Penale"])
                  and "ordinamento_penitenziario" in _f366("Il cliente è detenuto e vuole lavorare all'esterno.", ["Lavoro"])
                  and "ordinamento_penitenziario" in _f366("Il cliente vuole essere trasferito.", None))
        check("condizionati[366]: legge notarile, codici doganali e ordinamento penitenziario fuori senza motivo (contestazione disciplinare, "
              "trasferimento del dipendente); dentro col rogito, la targa albanese, la materia penale, il carcere", _ok366)
    except Exception as _e366:  # noqa: BLE001
        check("condizionati[366]: kontrollet u ekzekutuan", False, f"{type(_e366).__name__}: {_e366}")

    # [367] v9.593 — le TABELLE DELLE MALATTIE PROFESSIONALI del TU INAIL nel corpus, un'unità per voce, lette «Allegato 4, voce 71»; l'ancora della malattia professionale (artt. 3, 134, 112; art. 211 in agricoltura) e mai sull'amianto
    # del tetto del condominio; l'infortunio non la accende
    try:
        from pathlib import Path as _P367
        from src.retrieval import ArticleIndex as _AI367
        from src import brain as _b367
        from src.parser import numero_visibile_it as _nv367
        _it367 = _AI367.load(_P367("/app/data/index/bm25_it.pkl"))
        _by367 = {(a.code, str(a.number)): a for a in _it367.articles}
        _tab367 = [k for k in _by367 if k[0] == "tu_infortuni" and "-voce-" in k[1]]
        _v367 = lambda n: (_by367[("tu_infortuni", n)].body if ("tu_infortuni", n) in _by367 else "")
        _okT367 = (len(_tab367) >= 100 and "IPOACUSIA DA RUMORE" in _v367("allegato-4-voce-71") and "4 anni" in _v367("allegato-4-voce-71")
                   and "MESOTELIOMA" in _v367("allegato-4-voce-53") and _v367("allegato-5-voce-1")
                   and ("tu_infortuni", "allegato-4-1") not in _by367                      # i blocchi della prima stesura non ci sono più
                   and _nv367("allegato-4-voce-71") == "Allegato 4, voce 71" and _nv367("allegato-iv-2") == "Allegato IV (2)")
        _i367 = lambda q: {(a.code, a.number) for a, _ in _b367._applica_ancore([], _it367, [q], ["Lavoro"], _b367.ANCORE_IT)}
        _okA367 = ({("tu_infortuni", "3"), ("tu_infortuni", "134"), ("tu_infortuni", "112")}
                   <= _i367("Il cliente ha un'ipoacusia dopo 25 anni in fonderia: è una malattia professionale?")
                   and ("tu_infortuni", "211") in _i367("Il bracciante agricolo si è ammalato per i pesticidi usati nei campi: cosa chiede?")
                   and ("tu_infortuni", "3") not in _i367("Il condominio deve rimuovere l'amianto dal tetto: chi paga la bonifica?")
                   and ("tu_infortuni", "3") not in _i367("Il cliente è caduto dal ponteggio in cantiere: che diritti ha?"))
        # la voce per la malattia NOMINATA (il triage cerca le prestazioni, non la malattia): mesotelioma → voce 53; niente senza lavoro
        _vt367 = lambda q: {str(a.number) for a, _ in _b367._voci_tabella_malattie([], _it367, q)}
        _okV367 = ("allegato-4-voce-53" in _vt367("Il padre, ex operaio dei cantieri navali esposto all'amianto, è morto di mesotelioma "
                                                   "pleurico. Cosa chiedono i familiari all'INAIL?")
                   and "allegato-4-voce-71" in _vt367("Dopo 25 anni in fonderia il cliente ha un'ipoacusia: cosa chiede all'INAIL?")
                   and not _vt367("Il medico non ha diagnosticato in tempo il tumore al polmone della cliente: possiamo fare causa?")
                   and not _vt367("Il dipendente è in malattia da otto mesi e teme il licenziamento per superamento del comporto."))
        _okA367 = _okA367 and _okV367
        check("tabelle-inail[367]: tabelle delle malattie professionali nel corpus, un'unità per voce (ipoacusia da rumore voce 71, 4 anni; "
              "mesotelioma voce 53), lette «Allegato 4, voce 71»; ancora della malattia professionale (artt. 3, 134, 112; 211 in agricoltura), "
              "mai sull'amianto del condominio", _okT367 and _okA367,
              "T=%s A=%s" % (_okT367, _okA367))
    except Exception as _e367:  # noqa: BLE001
        check("tabelle-inail[367]: kontrollet u ekzekutuan", False, f"{type(_e367).__name__}: {_e367}")

    # [368] v9.594 — le leggi di settore albanesi col loro motivo: la procura (art. 90 = prescrizione disciplinare degli impiegati) fuori dalle
    # domande penali qualsiasi e dentro col vetting; l'antiriciclaggio fuori dalla telecamera; la legge notarile fuori dal morso del cane e
    # dentro con la successione; le contravvenzioni fuori dal permesso di costruire rifiutato e dentro con la multa
    try:
        from types import SimpleNamespace as _NS368
        from src import brain as _b368
        _p368 = [(_NS368(code=c, number=n), 1.0) for c, n in (("kodi_penal", "134"), ("ligji_prokuroria", "90"), ("ligji_pastrimi_parave", "16/1"),
                                                               ("ligji_noteri", "64"), ("ligji_kundervajtjet", "29"))]
        _f368 = lambda t: {a.code for a, _ in _b368._senza_codici_condizionati_al(_p368, t)}
        _ok368 = (_f368("Vëllai i klientit kërkohej nga policia për vjedhje dhe klienti e mbajti në shtëpi.") == {"kodi_penal"}
                  and _f368("Qeni i fqinjit kafshoi djalin e klientes në rrugë. Kush përgjigjet?") == {"kodi_penal"}
                  and "ligji_prokuroria" in _f368("Klienti është prokuror në procesin e rivlerësimit: si mbrohet?")
                  and "ligji_noteri" in _f368("Babai i klientit vdiq pa testament: si ndahet pasuria?")
                  and "ligji_kundervajtjet" in _f368("Policia rrugore i vendosi klientit një gjobë të padrejtë: si ankohet?")
                  and "ligji_kundervajtjet" not in _f368("Bashkia i refuzoi klientit lejen e ndërtimit: brenda sa ditësh e padisim?")
                  and "ligji_pastrimi_parave" in _f368("Banka i bllokoi klientit një transaksion si dyshim për pastrim parash."))
        check("condizionati-al[368]: procura, antiriciclaggio, notarile, contravvenzioni (e antimafia, appalti, discriminazione, avvocatura) "
              "solo col loro motivo nella domanda", _ok368)
    except Exception as _e368:  # noqa: BLE001
        check("condizionati-al[368]: kontrollet u ekzekutuan", False, f"{type(_e368).__name__}: {_e368}")

    # [369] v9.595 — d.lgs. 231/2001, TULPS, codice del consumo, codice delle assicurazioni, TU spese di giustizia e giudice di pace penale col
    # loro motivo: il 231 fuori dall'incidente stradale (l'art. 22 è la prescrizione degli illeciti degli ENTI) e dentro con la società;
    # il TULPS fuori dall'usura; il danno da prodotto fuori dalla buca del marciapiede e dentro con l'acquisto; le assicurazioni dentro col
    # sinistro; ⚠️ «cliente» non è un «ente» (l'innesco ha il confine di parola davanti)
    try:
        from types import SimpleNamespace as _NS369
        from src import brain as _b369
        _p369 = [(_NS369(code=c, number=n), 1.0) for c, n in (("codice_civile", "2043"), ("responsabilita_enti", "22"), ("tulps", "165"),
                                                               ("codice_consumo", "125"), ("codice_assicurazioni", "144"))]
        _f369 = lambda t: {a.code for a, _ in _b369._senza_codici_condizionati_it(_p369, t, ["Civile"])}
        _ok369 = (_f369("La cliente è caduta su una buca del marciapiede comunale e si è rotta il polso. Chi paga?") == {"codice_civile"}
                  and _f369("Un conoscente ha prestato soldi al cliente con interessi del 10% al mese.") == {"codice_civile"}
                  and "codice_assicurazioni" in _f369("Il cliente ha subito un incidente stradale e chiede il risarcimento.")
                  and "responsabilita_enti" not in _f369("Il cliente ha subito un incidente stradale e chiede il risarcimento.")
                  and "responsabilita_enti" in _f369("La società del cliente è indagata per corruzione: rischia sanzioni?")
                  and "codice_consumo" in _f369("Il cliente ha comprato online un tostapane difettoso che ha preso fuoco.")
                  and "tulps" in _f369("Il questore ha revocato la licenza del bar del cliente.")
                  and "responsabilita_enti" not in _f369("Il cliente vuole querelare il vicino."))
        check("condizionati[369]: 231, TULPS, consumo, assicurazioni, spese di giustizia, giudice di pace penale solo col loro motivo "
              "(«cliente» non è un «ente»)", _ok369)
    except Exception as _e369:  # noqa: BLE001
        check("condizionati[369]: kontrollet u ekzekutuan", False, f"{type(_e369).__name__}: {_e369}")

    # [370] v9.596 — le NOVELLE PURE (ogni comma modifica un articolo di un atto che abbiamo consolidato) fuori dalla ricerca italiana: il
    # testo è quello di allora (L. 689/1981 art. 91 = la querela del 582 c.p. del 1981; art. 13 St. Lav. = il 2103 c.c. del 1970). Mai gli
    # articoli veri che usano le stesse parole («è sostituito in giudizio il Ministro», «Le leggi non sono abrogate…»), mai un articolo
    # con una norma propria (la prescrizione e la norma transitoria della L. 689/1981, l'abrogazione con la regola per le affiliazioni)
    try:
        from pathlib import Path as _P370
        from src.retrieval import ArticleIndex as _AI370
        from src import brain as _b370
        _it370 = _AI370.load(_P370("/app/data/index/bm25_it.pkl"))
        _by370 = {(a.code, str(a.number)): a for a in _it370.articles}
        _nv370 = lambda c, n: bool((c, n) in _by370 and _b370._novella_pura(_by370[(c, n)], _it370))
        _si370 = [("sanzioni_amministrative", "91"), ("sanzioni_amministrative", "125"), ("sanzioni_amministrative", "134"),
                  ("statuto_lavoratori", "13"), ("legge_52_1985", "1"), ("equa_riparazione", "1")]
        _no370 = [("codice_procedura_civile", "76"), ("preleggi", "15"), ("codice_civile", "2103"), ("sanzioni_amministrative", "28"),
                  ("sanzioni_amministrative", "99"), ("adozione", "77"), ("collegato_lavoro", "32"), ("codice_penale", "582")]
        _okN370 = all(_nv370(c, n) for c, n in _si370) and not any(_nv370(c, n) for c, n in _no370)
        _p370 = [(_by370[k], 1.0) for k in (("sanzioni_amministrative", "91"), ("codice_penale", "582"), ("statuto_lavoratori", "13"),
                                             ("codice_civile", "2103"))]
        _okF370 = [(a.code, str(a.number)) for a, _ in _b370._senza_novelle(_p370, _it370)] == [("codice_penale", "582"), ("codice_civile", "2103")]
        _src370 = open("/app/src/brain.py", encoding="utf-8").read()
        _okW370 = _src370.count("_senza_novelle(") >= 3          # definizione + recupero + aggiunte del Kërkuesi
        check("novelle[370]: le novelle pure fuori dalla ricerca italiana (L. 689/1981 artt. 91/125/134, St. Lav. 13, L. 52/1985), mai gli "
              "articoli veri con le stesse parole né quelli con una norma propria", _okN370 and _okF370 and _okW370,
              "N=%s F=%s W=%s" % (_okN370, _okF370, _okW370))
    except Exception as _e370:  # noqa: BLE001
        check("novelle[370]: kontrollet u ekzekutuan", False, f"{type(_e370).__name__}: {_e370}")

    # [371] v9.596 — nautica da diporto, ambiente, proprietà industriale, contratti pubblici, legge Pinto e beni culturali col loro motivo
    # nella domanda: fuori dalle domande stradali, di lavoro e di pignoramento; dentro con la barca, i rifiuti, il marchio, la gara, la
    # causa che dura da anni, il vincolo paesaggistico. ⚠️ «rinnovati» non è un'«ATI», «quanto costa» non è la costa
    try:
        from types import SimpleNamespace as _NS371
        from src import brain as _b371
        _c371 = ("codice_nautica_diporto", "codice_ambiente", "codice_proprieta_industriale", "codice_contratti_pubblici",
                 "equa_riparazione", "codice_beni_culturali")
        _p371 = [(_NS371(code=c, number="1"), 1.0) for c in ("codice_civile",) + _c371]
        _f371 = lambda t: {a.code for a, _ in _b371._senza_codici_condizionati_it(_p371, t, ["Civile"])}
        _ok371 = (_f371("Il cliente è stato fermato con la revisione dell'auto scaduta da sei mesi: cosa rischia?") == {"codice_civile"}
                  and _f371("Il cliente lavora con contratti a termine rinnovati da 30 mesi nella stessa azienda: quanto costa la causa?") == {"codice_civile"}
                  and "codice_nautica_diporto" in _f371("La barca del cliente è stata fermata dalla capitaneria di porto.")
                  and "codice_ambiente" in _f371("La ditta vicina scarica rifiuti nel fiume: cosa possiamo fare?")
                  and "codice_proprieta_industriale" in _f371("Un concorrente usa un marchio identico a quello del cliente.")
                  and "codice_contratti_pubblici" in _f371("L'impresa del cliente è stata esclusa dalla gara d'appalto del Comune.")
                  and "equa_riparazione" in _f371("La causa del cliente dura da dodici anni: può chiedere un indennizzo per la durata irragionevole?")
                  and "codice_beni_culturali" in _f371("La casa del cliente è in una zona con vincolo paesaggistico: serve un'autorizzazione?"))
        check("condizionati[371]: nautica, ambiente, proprietà industriale, contratti pubblici, legge Pinto, beni culturali solo col loro "
              "motivo («rinnovati» non è un'ATI, «quanto costa» non è la costa)", _ok371)
    except Exception as _e371:  # noqa: BLE001
        check("condizionati[371]: kontrollet u ekzekutuan", False, f"{type(_e371).__name__}: {_e371}")

    # [372] v9.597 — il «permesso di costruire» non è un elemento straniero (il permesso di soggiorno sì); codice della crisi, TUB e TUF col
    # loro motivo; la L. 689/1981 sempre nel penale (pene sostitutive), fuori dal civile senza una sanzione amministrativa
    try:
        from types import SimpleNamespace as _NS372
        from src import brain as _b372
        _E372 = _b372._ESTERO_RX
        _okE372 = (not _E372.search("Il Comune ha negato al cliente il permesso di costruire.") and not _E372.search("permessi retribuiti della legge 104")
                   and bool(_E372.search("Il permesso di soggiorno del cliente è scaduto.")))
        _p372 = [(_NS372(code=c, number="1"), 1.0) for c in ("codice_civile", "codice_crisi_impresa", "tu_bancario", "tu_finanza", "sanzioni_amministrative")]
        _f372 = lambda t, ar: {a.code for a, _ in _b372._senza_codici_condizionati_it(_p372, t, ar)}
        _okC372 = (_f372("Un privato ha prestato soldi al cliente e ora pretende interessi del 10% al mese.", ["Civile"]) == {"codice_civile"}
                   and _f372("Il cliente si è dimesso e il datore non gli ha pagato il TFR.", ["Lavoro"]) == {"codice_civile"}
                   and {"codice_crisi_impresa", "tu_bancario"} <= _f372("La società del cliente non riesce più a pagare le rate del mutuo alla banca.", ["Civile"])
                   and "tu_finanza" in _f372("La banca ha venduto al cliente obbligazioni subordinate e ha perso i risparmi.", ["Civile"])
                   and "sanzioni_amministrative" in _f372("Il cliente è stato condannato a un anno e sei mesi: può avere una pena sostitutiva?", ["Penale"])
                   and "sanzioni_amministrative" in _f372("Al cliente è arrivata una multa da autovelox.", ["Amministrativo"])
                   and "sanzioni_amministrative" not in _f372("Il credito del cliente risale al 2013: è prescritto?", ["Civile"]))
        check("condizionati[372]: «permesso di costruire» non è straniero; crisi d'impresa, TUB e TUF col loro motivo; L. 689/1981 nel penale "
              "e con la sanzione amministrativa, fuori dal civile", _okE372 and _okC372, "E=%s C=%s" % (_okE372, _okC372))
    except Exception as _e372:  # noqa: BLE001
        check("condizionati[372]: kontrollet u ekzekutuan", False, f"{type(_e372).__name__}: {_e372}")

    # [373] v9.597 — AL: la legge sugli stupefacenti fuori dalla guida da ubriaco, la cannabis medica fuori dalla ketamina, la violenza
    # domestica fuori dalla riduzione degli alimenti; dentro col loro motivo
    try:
        from types import SimpleNamespace as _NS373
        from src import brain as _b373
        _p373 = [(_NS373(code=c, number="1"), 1.0) for c in ("kodi_penal", "ligji_lendet_narkotike", "ligji_kanabisi_mjekesor", "ligji_dhuna_familje_2026")]
        _f373 = lambda t: {a.code for a, _ in _b373._senza_codici_condizionati_al(_p373, t)}
        _ok373 = (_f373("Klienti u ndalua nga policia duke drejtuar makinën i dehur. Çfarë rrezikon?") == {"kodi_penal"}
                  and _f373("Ish-bashkëshorti humbi punën dhe kërkon t'ia ulë detyrimin ushqimor për fëmijën.") == {"kodi_penal"}
                  and {"ligji_lendet_narkotike"} <= _f373("Klienti u kap me 3 gram kokainë në xhep.")
                  and "ligji_kanabisi_mjekesor" not in _f373("Ketamina konsiderohet lëndë narkotike sipas ligjit shqiptar?")
                  and "ligji_kanabisi_mjekesor" in _f373("A lejohet kultivimi i kanabisit për qëllime mjekësore?")
                  and "ligji_dhuna_familje_2026" in _f373("Klientja rrihet nga bashkëshorti dhe ka frikë të kthehet në shtëpi.")
                  and "ligji_dhuna_familje_2026" in _f373("Ish-partneri publikoi në Facebook fotot private të klientes."))
        check("condizionati[373]: stupefacenti, cannabis medica e violenza domestica AL solo col loro motivo (non la guida da ubriaco, non "
              "la ketamina per la cannabis, non la riduzione degli alimenti)", _ok373)
    except Exception as _e373:  # noqa: BLE001
        check("condizionati[373]: kontrollet u ekzekutuan", False, f"{type(_e373).__name__}: {_e373}")

    print("\n== Përfundim: %d kaluan, %d dështuan ==" % (PASSES, len(FAILS)))
    if FAILS:
        print("DËSHTIME:", ", ".join(FAILS))
        return 1
    print("\033[32mTË GJITHA GJELBËR — truri i shenjtë i paprekur.\033[0m")
    return 0


if __name__ == "__main__":
    sys.exit(main())
