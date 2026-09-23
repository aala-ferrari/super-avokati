#!/usr/bin/env python3
"""v9.372 — Misura della ricerca dei PRECEDENTI come la fa il cervello: più query (domanda + fatti), filtro per area,
nene recuperati come indizio. Pertinente = il precedente parla davvero del tema (regex sul contenuto: objekti +
estratto del ragionamento, senza dieresi) OPPURE cita uno dei nene attesi. Confronta configurazioni."""
import sys, re, collections, time, importlib
sys.path.insert(0, "/app")
import src.retrieval_kb as K
from src import brain as B, dense as DN
from src.retrieval import fold_sq, ArticleIndex
kb = K.LegalKBRetriever.load()
arts = ArticleIndex.load()
print("casi:", len(kb.cases), "tipi:", collections.Counter(c.type for c in kb.cases).most_common())
T = [  # (domanda, fatti, area, regex contenuto, nene attesi)
 ("pushim nga puna pa shkak të justifikuar dëmshpërblim", "Punëdhënësi e pushoi punëmarrësin pa paralajmërim dhe pa shkak, kërkon dëmshpërblim", "Punë", r"pushim\w* nga puna|zgjidhj\w* \w* kontrat\w* \w* pun|marrëdhëni\w* pune|punëmarrës", [("kodi_punes", r".")]),
 ("zgjidhja e martesës dhe kujdestaria e fëmijëve", "Bashkëshortët kërkojnë zgjidhjen e martesës, fëmija i mitur, kujdestaria dhe detyrimi ushqimor", "Familje", r"zgjidhj\w* \w* martes|kujdestari|ushqimor|femij", [("kodi_familjes", r".")]),
 ("detyrimi ushqimor per femijen pas divorcit", "Pas divorcit babai nuk paguan detyrimin ushqimor për fëmijën", "Familje", r"ushqimor|femij|martes", [("kodi_familjes", r".")]),
 ("vrasje me paramendim", "I pandehuri akuzohet për vrasje me paramendim të viktimës", "Penal", r"vrasj", [("kodi_penal", r"^7[6-9]")]),
 ("vjedhje me dhunë grabitje", "I pandehuri akuzohet për vjedhje me dhunë (grabitje) me armë", "Penal", r"vjedhj\w* me dhun|grabit|neni 13[4-9]", [("kodi_penal", r"^1(3[4-9]|40)")]),
 ("plagosje e rëndë me dashje", "I pandehuri plagosi rëndë viktimën me thikë", "Penal", r"plagos", [("kodi_penal", r"^8[8-9]")]),
 ("masë sigurimi arrest në burg ankim", "I pandehuri ankimon masën e sigurimit arrest në burg", "Penal", r"mas\w* \w* sigurim|arrest\w* n\w* burg", [("kodi_proc_penale", r"^2(2[8-9]|[3-6][0-9])")]),
 ("rivendosje në afat të ankimit penal", "I pandehuri nuk ishte njoftuar për vendimin dhe kërkon rivendosjen në afat të ankimit", "Penal", r"rivendosj\w* n\w* afat", [("kodi_proc_penale", r"^14[7-8]")]),
 ("sigurimi i padisë sekuestro konservative", "Paditësi kërkon sigurimin e padisë me sekuestro konservative mbi pasurinë e të paditurit", "Civil", r"sigurim\w* \w* padi|sekuestro", [("kodi_proc_civile", r"^20[2-9]|^21[0-9]")]),
 ("kundërshtim veprimesh përmbarimore", "Debitori kundërshton veprimet e përmbaruesit gjyqësor në ekzekutim", "Civil", r"permbar|ekzekutim", [("kodi_proc_civile", r"^6[0-1][0-9]")]),
 ("pavlefshmëria e kontratës së shitjes së pasurisë", "Paditësi kërkon konstatimin e pavlefshmërisë absolute të kontratës së shitjes së apartamentit", "Civil", r"pavlefshm\w*|kontrat\w* \w* shitj", [("kodi_civil", r"^(92|93|94|95|96|97|98|99|10[0-9]|11[0-3])$")]),
 ("fitimi i pronësisë me parashkrim fitues", "Paditësi ka zotëruar tokën për 20 vjet dhe kërkon njohjen e pronësisë me parashkrim fitues", "Civil", r"parashkrim\w* fitues|fitim\w* \w* pronesi", [("kodi_civil", r"^1(6[6-9]|7[0-9])$")]),
 ("detyrimi për shpërblimin e dëmit jashtëkontraktor", "Paditësi kërkon shpërblimin e dëmit nga aksidenti i shkaktuar nga i padituri", "Civil", r"shperblim\w* \w* dem|dem\w* jashtekontrakt|demshperblim", [("kodi_civil", r"^6(0[8-9]|[1-4][0-9])$")]),
 ("akt administrativ shfuqizim gjykata administrative", "Paditësi kërkon shfuqizimin e aktit administrativ të institucionit publik", "Administrativ", r"akt\w* administrativ|shfuqizim\w* \w* akt", [("kodi_proc_admin", r"."), ("ligji_gjykatat_administrative", r".")]),
 ("detyrime tatimore njoftim vlerësimi", "Tatimpaguesi kundërshton njoftimin e vlerësimit tatimor dhe gjobat e administratës tatimore", "Administrativ", r"tatim", [("ligji_procedurat_tatimore", r".")]),
 ("gjobë doganore kontrabandë mallrash", "Dogana vendosi gjobë dhe konfiskim të mallrave për kontrabandë", "Doganor", r"dogan|kontraband", [("kodi_doganor", r".")]),
 ("mosekzekutimi i vendimit gjyqësor të formës së prerë", "Vendimi i formës së prerë në favor të kërkuesit nuk ekzekutohet prej vitesh nga administrata", None, r"mosekzekutim|ekzekutim\w* \w* vendim|forme\w* \w* prere", [("convention", r"^6"), ("kushtetuta", r"^42$")]),
 ("zgjatja e procesit gjyqësor afati i arsyeshëm", "Procesi gjyqësor ka zgjatur mbi 8 vjet, kërkuesi ankohet për afatin e arsyeshëm", None, r"afat\w* \w* arsyesh|zgjatj\w* \w* proces|kohezgjatj", [("convention", r"^6"), ("kushtetuta", r"^42$")]),
 ("e drejta e pronës kompensimi i pronarëve", "Ish-pronarët kërkojnë kompensimin e pronës së shpronësuar, vendimi i AKKP nuk zbatohet", None, r"kompensim|pron\w* \w* shpronesu|AKKP|AKP|kthim\w* \w* pron", [("convention", r"P1"), ("kushtetuta", r"^41$")]),
 ("procesi i rregullt ligjor standardi i arsyetimit të vendimit", "Kërkuesi pretendon se vendimi i gjykatës nuk ishte i arsyetuar dhe iu cenua procesi i rregullt", None, r"proces\w* \w* rregullt|arsyetim", [("kushtetuta", r"^42$"), ("convention", r"^6")]),
 ("tortura në polici deklarata e marrë me dhunë", "I arrestuari u rrah në komisariat dhe deklarata iu mor me dhunë", None, r"tortur|keqtrajtim|trajtim\w* \w* cnjerezor|dhun\w* \w* polic", [("convention", r"^3$")]),
 ("dëmshpërblim nga burgimi i padrejtë", "Kërkuesi u mbajt në paraburgim dhe u pafajësua, kërkon dëmshpërblim", None, r"paraburgim|burgim\w* \w* padrejt|pafajes", [("kodi_proc_penale", r"^26[7-9]"), ("convention", r"^5")]),
]
FT = [(re.compile(fold_sq(rx).lower()), exp) for _q, _f, _a, rx, exp in T]
def rel(c, i):
    rx, exp = FT[i]
    txt = fold_sq((c.summary or "") + " " + (c.excerpt or "")).lower()
    if rx.search(txt):
        return True
    for code, r in exp:
        for cc, art in c.articles_cited:
            if cc == code and re.search(r, str(art)):
                return True
    return False
HINTS = []
for q, f, a, rx, exp in T:
    h = []
    for qq in (q, f):
        for art, s in arts.search(qq, top_k=12):
            if (art.code, art.number) not in h:
                h.append((art.code, art.number))
    HINTS.append(h[:12])
def run(name, filt=True, hint=True):
    t0 = time.time(); p = h1 = 0; n = 0
    rows = []
    for i, (q, f, a, rx, exp) in enumerate(T):
        typ = B._area_to_case_type([a]) if (a and filt) else None
        kw = dict(top_k=5, cited_articles=HINTS[i] if hint else None)
        hits = kb.search([q, f], type=typ, **kw) if typ else []
        if not hits:
            hits = kb.search([q, f], **kw)
        k = sum(1 for c, s in hits if rel(c, i)); p += k; n += 1
        h1 += 1 if hits and rel(hits[0][0], i) else 0
        rows.append(k)
    print(f"{name:34s} P@5 {p:3d}/{5*n} = {100*p/(5*n):4.1f}%  primo {h1:2d}/{n}  {int((time.time()-t0)*1000/n)} ms  {rows}")
    return p
if __name__ == "__main__":
    orig = DN.precedenti
    run("produzione")
    run("senza filtro area", filt=False)
    run("senza nene-indizio", hint=False)
    DN.precedenti = lambda r: None; run("solo BM25"); DN.precedenti = orig
