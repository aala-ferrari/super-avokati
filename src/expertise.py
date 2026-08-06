"""Modele Ekspertize — case-type expertise templates (Phase 1).

For a chosen case type, produces a GROUNDED playbook: relevant Albanian
articles (retrieved from the corpus, never invented), the elements to prove
with GAP detection, evidence checklist, deadlines, defenses, valuation, and —
for criminal cases — BOTH perspectives at once (prosecutor vs. lawyer, the
"two opposing minds"). Reuses the legal brain + Verifikuar. Assistive only:
draft, the professional decides.
"""
from __future__ import annotations

from .logging_utils import get_logger

log = get_logger(__name__)

_LABEL = {
    "kodi_penal": "Kodi Penal", "kodi_civil": "Kodi Civil",
    "kodi_proc_penale": "K. Pr. Penale", "kodi_proc_civile": "K. Pr. Civile",
    "kodi_familjes": "Kodi i Familjes", "kodi_rrugor": "Kodi Rrugor",
}

# Curated case-type templates. `primary_articles` are VERIFIED (code, number)
# pairs from our corpus; everything else is durable legal scaffolding. Article
# text is filled from the corpus at runtime (grounded), never from memory.
TEMPLATES = {
    "aksident_rrugor": {
        "label": "Aksident rrugor / dëmi",
        "emoji": "\U0001f697",
        "domain": "civil",
        "primary_articles": [("kodi_civil", "608"), ("kodi_civil", "609"),
                             ("kodi_penal", "290"), ("kodi_penal", "291")],
        "elements": ["Veprimi/pakujdesia (shkelje e kodit rrugor)", "Faji",
                     "Lidhja shkakësore me dëmin", "Dëmi konkret (pasuror + jopasuror)"],
        "evidence": ["Raport i policisë rrugore / procesverbal", "Dëshmitarë okularë",
                     "Foto/video (dashcam, CCTV)", "Ekspertizë mjeko-ligjore për dëmtimet",
                     "Fatura mjekësore + vërtetim page për humbjet", "Ekspertizë e dëmit të automjetit"],
        "deadlines": ["Parashkrimi i padisë civile (kontrollo afatin nga Kodi Civil)",
                      "Njoftimi i sigurimit (RCA)"],
        "defenses": ["Faj i përbashkët / kontribut i të dëmtuarit", "Forcë madhore",
                     "Mospakësim i dëmit nga i dëmtuari", "Gjendje paraekzistuese (kontesto kauzalitetin)"],
        "valuation": "Dëmi = dëmi pasuror (fatura + humbje page + dëm automjeti) + dëmi jopasuror (vuajtje). Krahaso me precedentë.",
        "questions": ["Data, ora dhe vendi i aksidentit?",
                      "A ka raport policie dhe kush u konsiderua fajtor?",
                      "Cilat janë dëmtimet trupore dhe sa ditë paaftësie?",
                      "Totali i faturave mjekësore dhe ditët e punës të humbura?"],
    },
    "vjedhje": {
        "label": "Vjedhje",
        "emoji": "\U0001f4b0",
        "domain": "penal",
        "primary_articles": [("kodi_penal", "134"), ("kodi_penal", "135"),
                             ("kodi_penal", "137")],
        "elements": ["Marrja/përvetësimi i pasurisë së luajtshme", "Pasuria i përket tjetrit",
                     "Pa pëlqimin e pronarit", "Dashja për përvetësim përfundimtar (dolus)"],
        "evidence": ["Kallëzimi i të dëmtuarit + listë sendesh", "CCTV / dëshmitarë",
                     "Gjurmë (ADN, gjurmë gishtash)", "Recuperim i sendit të vjedhur",
                     "Vlerësim i vlerës së sendit"],
        "deadlines": ["Parashkrimi sipas rëndësisë së veprës", "Afati i ankimit 15 ditë"],
        "defenses": ["Alibi / identifikim i gabuar", "Mungesë dashjeje", "Pëlqim i pronarit",
                     "Provë e marrë në kundërshtim me ligjin (kërkesë përjashtimi)"],
        "valuation": "Dënimi sipas tierit (vlerë, rrethana). Lehtësuese: kthim sendi, dëmshpërblim, mungesë precedentësh.",
        "questions": ["Cila është akuza e saktë (neni)?",
                      "A ka CCTV/dëshmitarë që identifikojnë autorin?",
                      "A u kthye sendi ose a ka dëmshpërblim?",
                      "A ka precedentë penalë i pandehuri?"],
    },
    "grabitje": {
        "label": "Grabitje (vjedhje me dhunë)",
        "emoji": "\U0001f52b",
        "domain": "penal",
        "primary_articles": [("kodi_penal", "139"), ("kodi_penal", "140"),
                             ("kodi_penal", "141")],
        "elements": ["Elementet e vjedhjes", "Përdorim force ose kanosje ndaj personit",
                     "Rrethana rënduese (armë, grup, natë, dëmtim)"],
        "evidence": ["Dëshmi e viktimës", "Raport mjeko-ligjor për dëmtimet/kanosjen",
                     "CCTV / dëshmitarë", "Sekuestrim i armës + zinxhir ruajtjeje", "ADN/gjurmë"],
        "deadlines": ["Parashkrimi", "Afati i ankimit 15 ditë", "Afatet e paraburgimit"],
        "defenses": ["Identifikim i gabuar / alibi", "Kontestim i përdorimit të forcës (rikualifikim si vjedhje e thjeshtë 134)",
                     "Mungesë dashjeje", "Chain-of-custody i armës / provë e paligjshme"],
        "valuation": "Dënim i rëndë sipas rrethanave. Kontesto rrethanat rënduese për ulje tieri.",
        "questions": ["A u përdor forcë apo armë, dhe si u provua?",
                      "A ka dëmtim trupor (raport mjeko-ligjor)?",
                      "A veproi vetëm apo në grup?",
                      "Si u sekuestrua arma?"],
    },
    "vrasje": {
        "label": "Vrasje",
        "emoji": "\u26b0\ufe0f",
        "domain": "penal",
        "primary_articles": [("kodi_penal", "76"), ("kodi_penal", "78"),
                             ("kodi_penal", "79"), ("kodi_penal", "82")],
        "elements": ["Veprimi që shkakton vdekjen", "Lidhja shkakësore", "Dashja (ose paramendimi për 78)",
                     "Rrethana (viktimë e mbrojtur, motive, mjete)"],
        "evidence": ["Autopsia / ekspertiza mjeko-ligjore", "Vendi i ngjarjes + provat materiale",
                     "Balistikë / arma", "Dëshmitarë", "ADN, gjurmë", "Motivi (komunikime, histori konflikti)"],
        "deadlines": ["Afatet e paraburgimit dhe të hetimit", "Afati i ankimit"],
        "defenses": ["Vetëmbrojtje / kapërcim i kufijve (ulje)", "Mungesë dashjeje (rikualifikim në vrasje nga pakujdesia)",
                     "Provokim i rëndë", "Alibi / identifikim i gabuar", "Papërgjegjshmëri (ekspertizë psikiatrike)"],
        "valuation": "Dënim i rëndë; paramendimi/rrethanat rrisin. Kontesto dashjen dhe paramendimin.",
        "questions": ["A ka paramendim (planifikim, mjete të përgatitura)?",
                      "Çfarë tregon autopsia për shkakun dhe mënyrën?",
                      "A kishte kanosje/provokim nga viktima?",
                      "A ka çështje të papërgjegjshmërisë?"],
    },
    "plagosje": {
        "label": "Plagosje (dëmtim trupor / thikë)",
        "emoji": "\U0001fa78",
        "domain": "penal",
        "primary_articles": [("kodi_penal", "88"), ("kodi_penal", "89"),
                             ("kodi_penal", "90")],
        "elements": ["Veprim i kundërligjshëm", "Dëmtim trupor ndaj tjetrit",
                     "Dashje ose pakujdesi", "Rëndësia e plagës (tier: e rëndë 88 / e lehtë 89)"],
        "evidence": ["Raport mjeko-ligjor (ditë paaftësie → tieri)", "Foto plagësh / dosje spitalore",
                     "Arma (thika) + sekuestrim", "Dëshmitarë / CCTV për fillimin e konfliktit"],
        "deadlines": ["Parashkrimi sipas tierit", "Afati i ankimit 15 ditë"],
        "defenses": ["Vetëmbrojtje / mbrojtje e domosdoshme (proporcionaliteti)", "Provokim",
                     "Kontestim i rëndësisë së plagës (ulje tieri 88→89)", "Identifikim i gabuar",
                     "Chain-of-custody i armës"],
        "valuation": "Dënimi sipas tierit të plagës. Beteja kryesore: rëndësia e plagës + vetëmbrojtja.",
        "questions": ["Sa ditë paaftësie tregon raporti mjeko-ligjor?",
                      "Kush e filloi konfliktin / a kishte kanosje ndaj klientit?",
                      "A u përdor thikë/armë dhe si u sekuestrua?",
                      "A ka pajtim ose dëmshpërblim me viktimën?"],
    },
    "mashtrim": {
        "label": "Mashtrim",
        "emoji": "\U0001f3ad",
        "domain": "penal",
        "primary_articles": [("kodi_penal", "143"), ("kodi_penal", "186")],
        "elements": ["Veprime mashtruese / gënjeshtër", "Vënia në lajthim e viktimës",
                     "Dëmi pasuror", "Dashja për përfitim të padrejtë"],
        "evidence": ["Dokumente/kontrata", "Komunikime (email, mesazhe)", "Transaksione bankare",
                     "Dëshmi e viktimës", "Ekspertizë kontabël/financiare"],
        "deadlines": ["Parashkrimi", "Afati i ankimit 15 ditë"],
        "defenses": ["Mosmarrëveshje thjesht civile (jo penale)", "Mungesë dashjeje mashtruese",
                     "Mungesë e lidhjes shkakësore me dëmin"],
        "valuation": "Dënim sipas vlerës së dëmit. Argumento natyrën civile për të shmangur penalen.",
        "questions": ["Cili ishte mashtrimi konkret dhe si u vu në lajthim viktima?",
                      "Sa është dëmi pasuror dhe si provohet?",
                      "A ka prova të dashjes që në fillim (jo thjesht mospërmbushje kontrate)?"],
    },
    "mosmarreveshje_civile": {
        "label": "Mosmarrëveshje civile / kontratë",
        "emoji": "\U0001f4dc",
        "domain": "civil",
        "primary_articles": [("kodi_civil", "698"), ("kodi_civil", "699"),
                             ("kodi_civil", "450"), ("kodi_civil", "608")],
        "elements": ["Ekzistenca e detyrimit (kontratë e vlefshme)", "Mospërmbushja e detyrimit",
                     "Dëmi nga mospërmbushja", "Lidhja shkakësore"],
        "evidence": ["Kontrata + anekset", "Prova të përmbushjes/mospërmbushjes", "Korrespondenca",
                     "Fatura/pagesa", "Ekspertizë e dëmit"],
        "deadlines": ["Parashkrimi i padisë", "Afatet kontraktore të njoftimit"],
        "defenses": ["Përmbushje e kryer", "Mospërmbushje e justifikuar (exceptio non adimpleti)",
                     "Pavlefshmëri e kontratës", "Forcë madhore", "Parashkrim"],
        "valuation": "Dëmi = humbja efektive + fitimi i munguar. Kontrollo klauzolat penale.",
        "questions": ["Cila është kontrata dhe detyrimi i shkelur?",
                      "Si u shkel dhe çfarë dëmi solli?",
                      "A ka klauzolë penaliteti ose afat?",
                      "A u njoftua pala tjetër për mospërmbushjen?"],
    },
    "abuzim_policor": {
        "label": "Abuzim policor / posto blloku",
        "emoji": "\U0001f6a8",
        "domain": "penal",
        "primary_articles": [("ligji_policia_2024", "10"), ("ligji_policia_2024", "11"),
                             ("ligji_policia_2024", "18"), ("ligji_policia_2024", "19"),
                             ("ligji_policia_2024", "21"), ("ligji_policia_2024", "22"),
                             ("ligji_policia_2024", "27"), ("ligji_policia_2024", "32"),
                             ("kodi_proc_penale", "253"), ("kodi_proc_penale", "255"),
                             ("kodi_penal", "250"), ("kodi_penal", "248"),
                             ("kodi_penal", "86"), ("kodi_penal", "88"),
                             ("kodi_penal", "314")],
        "elements": ["Cilësia e agjentit (punonjës policie/RENEA) dhe baza ligjore e ndërhyrjes",
                     "Identifikimi i detyrueshëm para masës (Ligji 82/2024, neni 10/18)",
                     "Ligjshmëria e kontrollit të personit/mjetit (autorizim, dyshim i arsyeshëm)",
                     "Ligjshmëria dhe kohëzgjatja e ndalimit/shoqërimit",
                     "Proporcionaliteti i forcës (neni 11/32) dhe pasoja (plagosje/torturë)",
                     "Cenimi i të drejtave procedurale (avokat, njoftim i arsyes së ndalimit)"],
        "evidence": ["Raport mjeko-ligjor për lëndimet — URGJENT, bëje menjëherë",
                     "Foto/video të lëndimeve me datë",
                     "Procesverbali i kontrollit/shoqërimit (kërkoje zyrtarisht)",
                     "Regjistrimet e kamerave të posto-bllokut / body-cam",
                     "Urdhri i shërbimit dhe emrat/numrat e identifikimit të agjentëve",
                     "Dëshmitarë okularë",
                     "Regjistri i ndalimit të përkohshëm policor (neni 36, Ligji 82/2024)"],
        "deadlines": ["Kallëzimi penal — sa më shpejt (provat zhduken, lëndimet zbehen)",
                      "Ekzaminimi mjeko-ligjor brenda 24-48 orësh",
                      "Ankesa te Shërbimi i Kontrollit të Brendshëm (SHÇBA) dhe Prokuroria"],
        "defenses": ["Pretendim i 'dyshimit të arsyeshëm' për kontroll — kundërshto: mungon baza konkrete",
                     "Pretendim 'kundërshtim/rrezik' për të justifikuar forcën — kundërshto me video",
                     "Pretendim se u identifikuan — kundërshto: maskim, pa teserë/numër",
                     "Pretendim se ndalimi ishte brenda afateve — kontrollo kohëzgjatjen reale"],
        "valuation": "Ndaj përgjegjësitë: (a) PENALE e agjentëve (neni 250 veprime arbitrare / 248 shpërdorim detyre / 86 torturë / 88-89 plagosje / 314 dhunë gjatë hetimeve), (b) DISIPLINORE (SHÇBA), (c) DëMSHPëRBLIM civil (padi civile brenda procesit penal, neni 61 KPP, ose ndaj shtetit). Vlerëso dëmin pasuror + jopasuror.",
        "questions": ["Data, ora dhe vendi i saktë i posto-bllokut?",
                      "A u identifikuan agjentët dhe a treguan teserë/numër identifikimi?",
                      "A ke lëndime dhe a ke bërë raport mjeko-ligjor?",
                      "Sa zgjati mbajtja dhe a të lejuan të kontaktoje avokat/familjar?",
                      "A të dhanë ndonjë procesverbal ose akt me shkrim?"],
        "dual": ("\n\nKY RAST KA DY MENDJE TË KUNDëRTA — bëji të dyja të mprehta:\n"
                 "### \U0001f6e1\ufe0f MENDJA E QYTETARIT (AVOKATI YT) — cilat të drejta u shkelën, cilat nene i mbrojnë, si e ndërton kallëzimin dhe padinë, cilat prova të duhen para se të zhduken.\n"
                 "### \U0001f46e MENDJA E MBROJTJES SË POLICISË — si do ta justifikojë policia ndërhyrjen (dyshim i arsyeshëm, rrezik, proporcionalitet), ku është pika e tyre e fortë — që ta parandalosh dhe ta rrëzosh.\n"
                 "Kush e njeh mbrojtjen e tjetrit fiton."),
    },
}

_ORDER = ["aksident_rrugor", "vjedhje", "grabitje", "vrasje", "plagosje",
          "mashtrim", "mosmarreveshje_civile", "abuzim_policor"]


def list_templates() -> list[dict]:
    out = []
    for k in _ORDER:
        t = TEMPLATES[k]
        out.append({"key": k, "label": t["label"], "emoji": t["emoji"],
                    "domain": t["domain"], "questions": t["questions"],
                    "elements": t["elements"], "evidence": t["evidence"],
                    "defenses": t["defenses"], "deadlines": t["deadlines"]})
    return out


def _fold(s):
    import unicodedata
    return "".join(ch for ch in unicodedata.normalize("NFKD", (s or "").lower())
                   if not unicodedata.combining(ch))


def _full(a):
    """Full article text = heading (title + intro) + body (the actual content)."""
    return ((getattr(a, "heading", "") or "") + " " + (getattr(a, "body", "") or "")).strip()


def _article_text(index, code, number):
    for a in getattr(index, "articles", []):
        if a.code == code and a.number == number:
            return _full(a)
    return None


def _heading_scan(index, term, limit=5):
    """Match articles whose heading TITLE begins with the term's stem. Uses a
    5-char stem + diacritic folding to tolerate declension AND accents
    (vjedhje/vjedhja, trashëgimi/trashegimia, çështje/ceshtje)."""
    words = _fold(term).split()
    if not words or len(words[0]) < 5:
        return []
    key = words[0][:5]
    out = []
    for a in getattr(index, "articles", []):
        hw = _fold(getattr(a, "heading", "") or "").split()
        if hw and hw[0].startswith(key):
            out.append((a.code, a.number, _full(a)))
    return out[:limit]


def _expand_terms(backend, facts):
    try:
        raw = backend.complete(
            system=("Nga faktet e një çështjeje, listo 2-6 EMRA veprash penale ose "
                    "koncepte ligjore shqip me terminologjinë FORMALE të Kodit (p.sh. "
                    "'vjedhje', 'vjedhje me dhunë', 'plagosje e rëndë', 'mashtrim', "
                    "'drejtim i automjetit'), një për rresht, pa numra nenesh."),
            messages=[{"role": "user", "content": (facts or "")[:2000]}],
            max_tokens=100, fast=True, callsite="expand_terms")
        return [l.strip("-*• 	").strip() for l in (raw or "").splitlines() if l.strip()][:6]
    except Exception:  # noqa: BLE001
        return []


def retrieve_grounded(backend, index, facts, seed_pairs=None, max_arts=16):
    """Robust grounded retrieval: curated seeds + heading-scan on model-extracted
    offense terms (reliable anchor) + BM25 context fill. Never invents."""
    arts, seen = [], set()
    def add(code, num, txt):
        if (code, num) not in seen:
            seen.add((code, num)); arts.append((code, num, txt))
    for code, num in (seed_pairs or []):
        t = _article_text(index, code, num)
        if t:
            add(code, num, t)
    terms = _expand_terms(backend, facts)
    for term in terms:
        for c, n, h in _heading_scan(index, term):
            add(c, n, h)
            if len(arts) >= max_arts:
                break
        if len(arts) >= max_arts:
            break
    if len(arts) < max_arts:
        try:
            for a, _s in index.search((facts or "") + " " + " ".join(terms), top_k=10):
                add(a.code, a.number, _full(a))
                if len(arts) >= max_arts:
                    break
        except Exception:  # noqa: BLE001
            pass
    return arts


def _grounded_articles(index, tpl, facts):
    arts, seen = [], set()
    for code, num in tpl.get("primary_articles", []):
        txt = _article_text(index, code, num)
        if txt and (code, num) not in seen:
            seen.add((code, num))
            arts.append((code, num, txt))
    try:
        query = (facts or "") + " " + tpl["label"]
        for a, _s in index.search(query, top_k=10):
            if (a.code, a.number) not in seen:
                seen.add((a.code, a.number))
                arts.append((a.code, a.number, (getattr(a, "heading", "") or "")))
            if len(arts) >= 16:
                break
    except Exception:  # noqa: BLE001
        pass
    return arts


def _system(tpl) -> str:
    dual = ""
    if tpl.get("dual"):
        dual = tpl["dual"]
    elif tpl["domain"] == "penal":
        dual = (
            "\n\nKY ËSHTË RAST PENAL — jep analizën me DY MENDJE TË KUNDËRTA, që i njëjti "
            "përdorues të kuptojë të dyja anët:\n"
            "### \U0001f3db\ufe0f MENDJA E PROKURORIT — çfarë duhet të provojë për çdo element, "
            "cilat prova i duhen, ku është i fortë.\n"
            "### \u2696\ufe0f MENDJA E AVOKATIT MBROJTËS — cili element është më i dobët, ku sulmon, "
            "cilat mbrojtje ngre, cilat prova mungojnë.\n"
            "Kush e njeh mendjen e tjetrit fiton — bëji të dyja të mprehta."
        )
    return (
        "Ti je ekspert i lartë i së drejtës shqiptare. Ndërto një EKSPERTIZË të strukturuar për "
        "llojin e çështjes '" + tpl["label"] + "', bazuar VETËM te faktet e dhëna dhe te NENET "
        "e dhëna (të nxjerra nga korpusi ynë). MOS shpik nene, numra apo vendime — përdor vetëm "
        "ato që të jepen; nëse një nen nuk të jepet, përshkruaje me fjalë pa e trilluar.\n\n"
        "Jep këto seksione (markdown):\n"
        "### \U0001f4dc Baza ligjore (nenet e zbatueshme)\n"
        "### \u2705 Elementet që duhen provuar — për secilin: çfarë e provon, çfarë MUNGON (buku/gap), forca (fortë/mesatare/dobët)\n"
        "### \U0001f4cb Checklist provash (çfarë ke / çfarë të duhet)\n"
        "### \u23f0 Afatet kritike\n"
        "### \U0001f6e1\ufe0f Mbrojtjet / pikat e dobëta\n"
        "### \U0001f4b0 Vlerësimi (dëmi ose dënimi)\n"
        + dual +
        "\n\nI qartë, konkret, i veprueshëm. Shqip. Kjo është NDIHMESË — vendos dhe firmos "
        "profesionisti. Mos zbulo kurrë modelin — je 'Tetramorph' i superavokati.ai."
    )


def analyze(backend, index, *, case_type: str, facts: str, max_tokens: int = 2800) -> dict:
    tpl = TEMPLATES.get(case_type)
    if tpl is None:
        raise ValueError("unknown case_type")
    arts = retrieve_grounded(backend, index, facts, seed_pairs=tpl.get("primary_articles"))
    art_block = "\n".join(
        "\u2022 [%s neni %s] %s" % (_LABEL.get(c, c), n, (t or "").strip()[:900])
        for c, n, t in arts
    ) or "(asnjë nen i gjetur — përshkruaj me fjalë, mos shpik)"
    scaffold = (
        "STRUKTURA E PRITSHME:\n"
        "- Elementet tipike: " + "; ".join(tpl["elements"]) + "\n"
        "- Provat tipike: " + "; ".join(tpl["evidence"]) + "\n"
        "- Mbrojtjet tipike: " + "; ".join(tpl["defenses"]) + "\n"
        "- Vlerësimi: " + tpl["valuation"]
    )
    prompt = (
        "LLOJI: " + tpl["label"] + "\n\nFAKTET E ÇËSHTJES:\n" + (facts or "").strip()
        + "\n\n\u2500\u2500\u2500\u2500\u2500\nNENET NGA KORPUSI (cito vetëm këto):\n" + art_block
        + "\n\n\u2500\u2500\u2500\u2500\u2500\n" + scaffold
        + "\n\nNdërto ekspertizën e plotë."
    )
    md = backend.complete(
        system=_system(tpl),
        messages=[{"role": "user", "content": prompt}],
        max_tokens=max_tokens, callsite="expertise",  # default = Opus effort=max (dy mendjet)
    )
    return {"markdown": (md or "").strip(),
            "articles": [{"code": c, "number": n} for c, n, _t in arts]}
