"""v9.537 — OMOGLIFI CIRILLICI nel corpus albanese. 46 articoli (ligji_konsumatoret 9, ligji_kadastra 8, procedurat tatimore 7,
prokurimi publik 5, shoqëritë tregtare 4: «Largimi і ortakut», …) avevano lettere CIRILLICHE al posto di quelle latine — soprattutto
«ё» (U+0451) al posto di «ë» («tё lidhura nё largësi», «higjienёs»). La piegatura dei diacritici della ricerca fa «ë» → «e», ma non
tocca «ё»: quelle parole non corrispondevano MAI alle query, e il testo citato «fjalë për fjalë» le portava con sé.
Si sostituisce una lettera cirillica SOLO dentro una parola latina (preceduta o seguita da una lettera latina): il cirillico vero
(non ce n'è nel corpus AL; nei regolamenti UE italiani c'è il bulgaro e lì non si tocca — questo strumento è solo per il corpus AL).
jsonl E pickle (stessi parametri di costruzione), backup, idempotente; il numero di articoli non cambia (embedding allineati).
Nel container con /app/data scrivibile:  python3 tools/repair_omoglifi_al.py [--apply]"""
import json, re, shutil, sys, unicodedata
from datetime import datetime
from pathlib import Path
sys.path.insert(0, "/app")
from src.retrieval import ArticleIndex, Article  # noqa: E402

JSONL = Path("/app/data/processed/all_articles.jsonl")
PKL = Path("/app/data/index/bm25.pkl")
MAPPA = {"ё": "ë", "Ё": "Ë", "і": "i", "І": "I", "ј": "j", "а": "a", "А": "A", "е": "e", "Е": "E", "о": "o", "О": "O",
         "р": "p", "Р": "P", "с": "c", "С": "C", "х": "x", "Х": "X", "у": "y", "к": "k", "К": "K", "Т": "T", "Н": "H",
         "В": "B", "М": "M", "ѕ": "s", "ҫ": "ç", "Ҫ": "Ç"}
_LAT = r"A-Za-zÀ-ÿËëÇç"
_RX = re.compile(r"(?<=[" + _LAT + r"])[" + "".join(MAPPA) + r"]|[" + "".join(MAPPA) + r"](?=[" + _LAT + r"])")
# … e la lettera cirillica che è una PAROLA intera fra due parole latine («Largimi і ortakut», «… а …»): in albanese «i», «e», «a»,
# «o» sono parole
_RX_SOLA = re.compile(r"(?<=[" + _LAT + r"][ \t\xa0])[" + "".join(MAPPA) + r"](?=[ \t\xa0,;.:][ \t\xa0]?[" + _LAT + r"])")
# … e la lettera ISOLATA senza altre cirilliche accanto: lettere d'elenco a inizio riga («а) …», «ё) …», «ҫ) …»), dopo una virgola
# («, і cili»), fra virgolette («“і”»). Nel corpus AL non c'è cirillico vero (misurato: i resti erano tutti omoglifi)
_RX_ISOLATA = re.compile(r"(?<![Ѐ-ӿ])[" + "".join(MAPPA) + r"](?![Ѐ-ӿ])")
CAMPI = ("heading", "body", "note", "title_sq", "kreu", "pjesa", "seksioni")   # anche i titoli di capitolo e di parte: entrano nella ricerca


_ZERO = re.compile(r"[\u200b-\u200d\u2060\ufeff]")


def pulisci(s):
    if not isinstance(s, str) or not s:
        return s, 0
    n = [0]
    # v9.540 — lettere SCOMPOSTE («E» + dieresi combinante U+0308 al posto di «Ë»: 62 articoli, legge sui consumatori, procura…):
    # a schermo identiche, ma il segno combinante spezza la parola in due token («PË|RGJITHSHME» → «pe» + «rgjithshme»).
    # NFC le ricompone; via anche i caratteri a larghezza zero
    _nfc = unicodedata.normalize("NFC", s)
    # dopo NFC un segno combinante rimasto è rumore («garancisë̈»: una «ë» già composta con una seconda dieresi)
    _nz = re.sub(r"[\u0300-\u036f]", "", _ZERO.sub("", _nfc))
    if _nz != s:
        n[0] += 1
    s = _nz

    def _r(m):
        n[0] += 1
        return MAPPA[m.group(0)]
    # due passate: «ёs» in mezzo a due cirilliche vicine si scioglie alla seconda
    out = _RX.sub(_r, s)
    out = _RX.sub(_r, out)
    out = _RX_SOLA.sub(_r, out)
    out = _RX_ISOLATA.sub(_r, out)
    return out, n[0]


def main() -> int:
    apply = "--apply" in sys.argv
    righe = JSONL.read_text(encoding="utf-8").splitlines()
    dati = [json.loads(r) for r in righe]
    tocchi, tot = [], 0
    for d in dati:
        nd = 0
        for c in CAMPI:
            if c in d:
                d[c], k = pulisci(d[c])
                nd += k
        if isinstance(d.get("paragrafet"), list):
            nuovi = []
            for p in d["paragrafet"]:
                q, k = pulisci(p)
                nuovi.append(q); nd += k
            d["paragrafet"] = nuovi
        if nd:
            tocchi.append(f"{d.get('code')} {d.get('number')} ({nd})"); tot += nd
    print(f"jsonl: {len(tocchi)} articoli, {tot} lettere"); print("  " + ", ".join(tocchi[:60]))
    idx = ArticleIndex.load(PKL)
    arts, tocchi_p = [], 0
    campi = set(Article.__dataclass_fields__)
    for a in idx.articles:
        kw = {k: getattr(a, k) for k in campi if hasattr(a, k)}
        nd = 0
        for c in CAMPI:
            if c in kw:
                kw[c], k = pulisci(kw[c])
                nd += k
        tocchi_p += bool(nd)
        arts.append(Article(**kw))
    print(f"pickle: {tocchi_p} articoli toccati su {len(arts)}")
    resti = []
    for a in arts:
        t = " ".join(str(getattr(a, c, "") or "") for c in CAMPI)
        m = re.search(r"[\u0400-\u04FF]", t)
        if m:
            resti.append(f"{a.code} {a.number}: …{t[max(0, m.start() - 20):m.start() + 20]!r}")
    print(f"cirillico rimasto dopo la pulizia: {len(resti)}"); print("  " + "\n  ".join(resti[:12]))
    if not apply:
        return 0
    if not tocchi and not tocchi_p:
        print("niente da fare (già pulito)"); return 0
    stamp = datetime.now().strftime("%Y%m%d-%H%M")
    shutil.copy2(JSONL, str(JSONL) + f".bak-{stamp}-omoglifi")
    shutil.copy2(PKL, str(PKL) + f".bak-{stamp}-omoglifi")
    JSONL.write_text("\n".join(json.dumps(d, ensure_ascii=False) for d in dati) + "\n", encoding="utf-8")
    ArticleIndex.build(arts, lang="sq", stem=bool(getattr(idx, "stem", False)), fold=bool(getattr(idx, "fold", True))).save(PKL)
    print("FATTO: jsonl e pickle, backup", stamp)
    return 0


if __name__ == "__main__":
    sys.exit(main())
