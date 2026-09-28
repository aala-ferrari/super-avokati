"""Modele Ekspertize — case-type expertise templates (Phase 1).

For a chosen case type, produces a GROUNDED playbook: relevant Albanian
articles (retrieved from the corpus, never invented), the elements to prove
with GAP detection, evidence checklist, deadlines, defenses, valuation, and —
for criminal cases — BOTH perspectives at once (prosecutor vs. lawyer, the
"two opposing minds"). Reuses the legal brain + Verifikuar. Assistive only:
draft, the professional decides.
"""
from __future__ import annotations

import re

from .logging_utils import get_logger

def _juris(system_prompt: str) -> str:
    """System prompt adattato alla giurisdizione della richiesta.

    Import differito: brain.py importa alcuni di questi moduli, quindi un
    import in testa creerebbe un ciclo."""
    try:
        from .brain import apply_current
        return apply_current(system_prompt)
    except Exception:  # noqa: BLE001
        return system_prompt



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
                             ("kodi_penal", "290"), ("kodi_penal", "291"),
                             # v9.399: la responsabilità per il veicolo (attività pericolosa, KC 622), la prescrizione del danno
                             # extracontrattuale (KC 115/dh: tre anni), il danno non patrimoniale e patrimoniale (625, 640, 641) e
                             # la richiesta all'assicuratore del responsabile — nell'audit del 28 set la perizia li dava «non nel corpus»
                             ("kodi_civil", "622"), ("kodi_civil", "115"), ("kodi_civil", "625"),
                             ("kodi_civil", "640"), ("kodi_civil", "641"), ("ligji_sigurimi_mjeteve", "9")],
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


# v9.397 — l'estrazione dei termini nella lingua dell'INDICE. Prima il prompt era solo albanese e in sessione
# italiana il vincolo di giurisdizione sopra gli imponeva la ricerca della Cassazione: tornava un paragrafo («Nota
# preliminare: in questa sessione non mi è stato concesso l'accesso…») al posto dei nomi dei reati, e la ricerca per
# titolo girava su parole vuote — per perizie, notaio, scadenze, prescrizione, lettere e procuratore. È una lista di
# parole: niente preambolo (raw_system), e le righe che non sono un termine si scartano.
_ESPANDI = {
    "sq": ("Nga faktet e një çështjeje, listo 2-6 EMRA veprash penale ose koncepte ligjore shqip me terminologjinë "
           "FORMALE të Kodit (p.sh. 'vjedhje', 'vjedhje me dhunë', 'plagosje e rëndë', 'mashtrim', 'dhunë në familje', "
           "'korrupsion pasiv', 'drejtim i automjetit'), një për rresht, pa numra nenesh, pa asnjë tekst tjetër."),
    "it": ("Dai fatti di una questione elenca 2-6 NOMI di reati o istituti giuridici in italiano, con la terminologia "
           "FORMALE del codice (per esempio 'furto', 'rapina', 'lesioni personali', 'truffa', 'maltrattamenti contro "
           "familiari e conviventi', 'concussione', 'risoluzione del contratto'), uno per riga, senza numeri di "
           "articolo e senza nessun altro testo."),
}


def _pulisci_termini(raw: str) -> list:
    out = []
    for l in (raw or "").splitlines():
        l = l.strip().strip("-*•·0123456789.) \t").strip().strip("'\"«»").strip()
        if not l or len(l) > 70 or l.endswith(":") or "**" in l or l.count(" ") > 8:
            continue
        out.append(l)
    return out[:6]


def _expand_terms(backend, facts, lang: str = "sq"):
    try:
        raw = backend.complete(
            system=_ESPANDI.get(lang, _ESPANDI["sq"]),
            messages=[{"role": "user", "content": (facts or "")[:2000]}],
            max_tokens=100, fast=True, callsite="expand_terms", raw_system=True)
        return _pulisci_termini(raw)
    except Exception:  # noqa: BLE001
        return []


def _radice(w: str) -> str:
    """Radice per il confronto dei titoli: 4 lettere per le parole brevi («dhuna»/«dhunë»), 5 per le altre."""
    return w[:4] if len(w) <= 6 else w[:5]


def _heading_scan_rank(index, term, limit=3):
    """v9.397 — ricerca per titolo ORDINATA per quante parole del termine compaiono nel titolo (non solo la prima,
    e non in ordine di codice: «Prodhimi…» prendeva i primi 5 titoli del codice e il KP 283 restava fuori; la rubrica
    dell'art. 73 d.P.R. 309/1990 comincia con «Legge 26 giugno 1990…»). Salta gli abrogati."""
    words = _fold(term).split()
    ks = {_radice(w) for w in words if len(w) >= 5}
    if not ks or not words:
        return []
    scored = []
    for a in getattr(index, "articles", []):
        if getattr(a, "repealed", False):
            continue
        hw = _fold(getattr(a, "heading", "") or "").split()
        if not hw:
            continue
        ov = len(ks & {_radice(w) for w in hw if len(w) >= 4})
        first = len(words[0]) >= 5 and hw[0].startswith(_radice(words[0]))
        if first or ov >= max(1, min(2, len(ks))):
            scored.append((ov + (0.5 if first else 0.0), a))
    scored.sort(key=lambda x: -x[0])
    return [(a.code, a.number, _full(a)) for _s, a in scored[:limit]]


_TESTE_CACHE: dict = {}


def _teste_di_sezione(index, term, limit=1):
    """v9.399 — il PRIMO articolo della sezione (o del capitolo) il cui TITOLO contiene il termine: la figura generale del
    reato. «mashtrim» → «SEKSIONI II — MASHTRIMET» → KP 143: la ricerca per titolo dava le truffe speciali (143/b
    informatica, 144 sovvenzioni… cominciano con «Mashtrimi») e la figura generale, che nel consolidato non ha rubrica,
    restava fuori (il caso mancato della misura v9.397). Il codice mette la figura generale in testa alla sezione."""
    ks = {_radice(w) for w in _fold(term).split() if len(w) >= 5}
    if not ks:
        return []
    key = id(index)
    teste = _TESTE_CACHE.get(key)
    if teste is None:
        teste = {}
        for a in getattr(index, "articles", []):
            if getattr(a, "repealed", False):
                continue
            for lvl in ("seksioni", "kreu"):
                t = (getattr(a, lvl, "") or "").strip()
                if t and (a.code, lvl, t) not in teste:
                    teste[(a.code, lvl, t)] = a
        _TESTE_CACHE[key] = teste
    trovate = []
    for (code, lvl, t), a in teste.items():
        titolo = re.sub(r"^\S+\s+[IVXLCDM\d]+[A-Z]?\s*(?:—|-)?\s*", "", t)       # «SEKSIONI II — MASHTRIMET» → «MASHTRIMET»
        tw = {_radice(w) for w in _fold(titolo).split() if len(w) >= 4}
        if tw and ks <= tw:              # TUTTE le parole del termine nel titolo: «shitje narkotikësh» ≠ la sezione civile «SHITJA»
            trovate.append((0 if lvl == "seksioni" else 1, len(titolo), a))
    trovate.sort(key=lambda x: (x[0], x[1]))
    return [(a.code, a.number, _full(a)) for _l, _n, a in trovate[:limit]]


# v9.399 — i RINVII INTERNI espliciti degli articoli dati («prokurori vendos sipas paragrafit 6, të nenit 327, të këtij
# Kodi», «dall'art. 309 del presente codice»): nell'audit AL del 28 set il procuratore scriveva tre volte «il neni 327 / 75/a
# non è nel corpus» — c'erano, ma nessuno li portava. Solo il rinvio ESPLICITO allo stesso atto, solo articoli esistenti e
# in vigore, al massimo 4, in coda al blocco.
_RINVIO_AL = re.compile(r"\bnen(?:it|in|i)\s+(\d+(?:/[a-zçë]{1,2})?)\s*,?\s*(?:t[ëe]|i|e)\s+k[ëe]tij\s+(?:Kodi|ligji)\b", re.I)
_RINVIO_IT = re.compile(r"\bart(?:icol[oi]|\.)\s*(\d+(?:-(?:bis|ter|quater|quinquies|sexies|septies|octies|novies|decies))?)"
                        r"(?:\s*,\s*comm[ai]\s*\d+(?:-bis)?)?\s*,?\s*(?:del|dello|della)\s+presente\s+"
                        r"(?:codice|decreto|testo\s+unico|legge|regolamento)\b", re.I)
# i codici italiani rinviano a sé stessi SENZA nominarsi («dall'articolo 408», «ai sensi degli articoli 406 e 407»): vale il
# rinvio non seguito dal nome di un ALTRO atto (misurato: 23 su 24 esatti su un campione di c.c./c.p.c./c.p./c.p.p.; il numero
# non si taglia a metà: «articolo 71-quater delle disposizioni di attuazione» NON è l'art. 71)
_RINVIO_IT_IMPL = re.compile(
    r"\b(?:(?:dall|dell|all|nell|sull|coll|l)['’])?articol[oi]\s+(\d+(?:-(?:bis|ter|quater|quinquies|sexies|septies|octies|"
    r"novies|decies))?)(?![\w-])(?:\s*,\s*comm[ai]\s*\d+(?:-bis)?(?:\s*(?:,|e)\s*\d+)*)?"
    r"(?!\s*,?\s*(?:del|della|dello|dei|delle|degli|di\s+cui|n\.|legge|decreto|d\.\s*lgs|d\.p\.r|regolamento|codice|testo|"
    r"tuf|tub|tuir|c\.\s*c|c\.\s*p)\b)", re.I)
_OBJ_CACHE: dict = {}


def _rinvii_interni(index, arts, lang, max_add=4, gia=None):
    key = id(index)
    obj = _OBJ_CACHE.get(key)
    if obj is None:
        obj = {(a.code, str(a.number)): a for a in getattr(index, "articles", [])}
        _OBJ_CACHE[key] = obj
    rxs = (_RINVIO_IT, _RINVIO_IT_IMPL) if lang == "it" else (_RINVIO_AL,)
    seen = set(gia or ()) | {(c, str(n)) for c, n, _t in arts}
    out = []
    for c, n, t in arts[:10]:
        for m in (mm for rx in rxs for mm in rx.finditer(t or "")):
            k = (c, m.group(1).replace(" ", "").lower() if lang != "it" else m.group(1).lower())
            a = obj.get(k)
            if a is None or getattr(a, "repealed", False) or k in seen:
                continue
            seen.add(k)
            out.append((a.code, a.number, _full(a)))
            if len(out) >= max_add:
                return out
    return out


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
    lang = "it" if getattr(index, "lang", "sq") == "it" else "sq"
    # v9.399 — SOSTANZE STUPEFACENTI nominate nei fatti (lo stesso riconoscimento del cervello: le liste della 7975/1995 e le
    # tabelle del d.P.R. 309/1990): entrano le norme penali sugli stupefacenti. Nell'audit AL del 28 set la misura cautelare
    # per la vendita di 50 g di cocaina non aveva il KP 283 («Prodhimi dhe shitja e narkotikëve»: il recupero lo portava fra
    # l'8° e l'11° posto, a seconda dei termini) e il modello, onestamente, ripiegava sul 283/a (traffico).
    try:
        if lang == "it":
            from . import stupefacenti as _stp
            if _stp.trova(facts or ""):
                for code, num in (("stupefacenti", "73"),):
                    t = _article_text(index, code, num)
                    if t:
                        add(code, num, t)
        else:
            from . import narkotike_al as _nk
            if any(not x.get("jo") for x in _nk.trova(facts or "")):
                _semi_nk = [("kodi_penal", "283"), ("kodi_penal", "283/a")]
                if re.search(r"kultiv|mbjell|bim[ëe]t?\b|fidan", _fold(facts or "")):
                    _semi_nk.append(("kodi_penal", "284"))
                for code, num in _semi_nk:
                    t = _article_text(index, code, num)
                    if t:
                        add(code, num, t)
    except Exception:  # noqa: BLE001
        pass
    terms = _expand_terms(backend, facts, lang)
    query = (facts or "") + " " + " ".join(terms)
    # v9.397 — misurato su 12 casi penali tipici (6 AL, 6 IT: la norma del reato fra gli articoli dati al modello):
    # 5/12 → 11/12. Quattro posti alla ricerca per CONTENUTO prima dei titoli (prima i titoli li finivano tutti),
    # poi la ricerca per titolo ordinata, 3 per termine così ogni termine ha il suo turno.
    try:
        for a, _s in index.search(query, top_k=4):
            add(a.code, a.number, _full(a))
    except Exception:  # noqa: BLE001
        pass
    for term in terms:
        for c, n, h in _heading_scan_rank(index, term):
            add(c, n, h)
        for c, n, h in _teste_di_sezione(index, term):       # v9.399: la figura generale in testa alla sezione
            add(c, n, h)
        if len(arts) >= max_arts:
            break
    if len(arts) < max_arts:
        try:
            for a, _s in index.search(query, top_k=10):
                add(a.code, a.number, _full(a))
                if len(arts) >= max_arts:
                    break
        except Exception:  # noqa: BLE001
            pass
    arts = arts[:max_arts]
    try:
        arts = arts + _rinvii_interni(index, arts, lang)          # v9.399: i rinvii espliciti allo stesso atto
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


_MAX_ART_BLOCCO = 3500
_MAX_TOT_BLOCCO = 42000


def _lbl_it(c):
    try:
        from .citation_verifier import CODE_LABELS
        if CODE_LABELS.get(c):
            return CODE_LABELS[c]
    except Exception:  # noqa: BLE001
        pass
    return c.replace("_", " ")


def etichetta_al(c) -> str:
    """v9.399 — l'etichetta leggibile del codice albanese nel blocco: prima, fuori dai 6 codici di `_LABEL`, passava
    l'identificativo interno e il modello lo copiava NELL'ATTO («[ligji_kadastra neni 14]», «[ligji_procedurat_tatimore
    neni 59]» in una compravendita notarile). Riserva: le etichette del verificatore («Ligji Kadastra 111/2018»)."""
    if _LABEL.get(c):
        return _LABEL[c]
    try:
        from .citation_verifier import CODE_LABELS
        if CODE_LABELS.get(c):
            return CODE_LABELS[c]
    except Exception:  # noqa: BLE001
        pass
    return c.replace("_", " ")


def blocco_articoli(arts, lang: str = "sq", vuoto: str = "", max_art: int | None = None, max_tot: int | None = None) -> str:
    """v9.399 — il blocco degli articoli per i prompt degli strumenti PRO (notaio, lettere, perizie): il testo arriva fino a
    3.500 caratteri (prima 900: al notaio il KC 361 arrivava senza la frase sul coniuge «Në çdo rast bashkëshorti merr 1/2…» e
    la successione doveva scrivere «il testo è troncato, verificalo») con l'avviso del taglio, e le etichette della sessione
    («art.» in italiano, «neni» in albanese). Stessa regola del procuratore (v9.397)."""
    out, tot = [], 0
    _cap, _tot_max = (max_art or _MAX_ART_BLOCCO), (max_tot or _MAX_TOT_BLOCCO)
    for c, n, t in arts:
        t = (t or "").strip()
        cap = _cap if tot < _tot_max else 400
        testo = t[:cap]
        if len(t) > cap:
            testo += ((" […testo tagliato qui: altri %d caratteri — non completarlo a memoria]" if lang == "it"
                       else " […teksti u shkurtua këtu: edhe %d karaktere — mos e plotëso nga kujtesa]") % (len(t) - cap))
        tot += len(testo)
        out.append(("• [%s art. %s] %s" % (_lbl_it(c), n, testo)) if lang == "it"
                   else ("• [%s neni %s] %s" % (etichetta_al(c), n, testo)))
    if out:
        return "\n".join(out)
    return vuoto or ("(nessun articolo trovato — descrivi a parole, non inventare)" if lang == "it"
                     else "(asnjë nen i gjetur — përshkruaj me fjalë, mos shpik)")


def _lang_indice(index) -> str:
    return "it" if getattr(index, "lang", "sq") == "it" else "sq"


def analyze(backend, index, *, case_type: str, facts: str, max_tokens: int = 2800) -> dict:
    tpl = TEMPLATES.get(case_type)
    if tpl is None:
        raise ValueError("unknown case_type")
    arts = retrieve_grounded(backend, index, facts, seed_pairs=tpl.get("primary_articles"))
    art_block = blocco_articoli(arts, _lang_indice(index))      # v9.399: 3.500 caratteri, etichette della sessione
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
        system=_juris(_system(tpl)),
        messages=[{"role": "user", "content": prompt}],
        max_tokens=max_tokens, callsite="expertise",  # default = Opus effort=max (dy mendjet)
    )
    return {"markdown": (md or "").strip(),
            "articles": [{"code": c, "number": n} for c, n, _t in arts]}
