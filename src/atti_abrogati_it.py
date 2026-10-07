"""v9.538 — GLI ATTI ITALIANI ABROGATI CHE NON SONO NEL CORPUS.

«art. 301 TULD» / «art. 301 d.P.R. 43/1973» (il vecchio testo unico doganale, abrogato dal D.Lgs. 141/2024), «art. 561 Reg.
2454/93» (le vecchie disposizioni d'applicazione del codice doganale comunitario): il verificatore li lasciava «senza codice» —
cioè «da chiarire» — e chi leggeva non sapeva che l'atto non c'è più. Il gemello del registro albanese della v9.399.

Il registro si legge dal CORPUS STESSO: gli articoli vigenti che elencano gli atti abrogati PER INTERO («Sono abrogati: … f) il
decreto del Presidente della Repubblica 23 gennaio 1973, n. 43 ;», «Il regolamento (CEE) n. 2913/92 … sono abrogati»). Si
scartano, di proposito:
  · le abrogazioni PARZIALI («ad eccezione degli articoli…», «fatta salva…», «gli articoli 125-128 del decreto…»): chi cita uno
    degli articoli salvati riceverebbe «abrogato» su una norma vigente;
  · le abrogazioni dei testi unici fiscali che si applicano dal 1° gennaio 2027 (oggi l'atto vecchio è vigente);
  · le frasi che non dicono «abrogato» («… si applica, in quanto compatibile»);
  · gli atti che sono nel corpus (lì vale l'articolo).
Più poche voci a mano, verificate sulla fonte, dove l'atto che abroga non è nel corpus. Mai un'eccezione: in caso di dubbio
nessun esito (la citazione resta «da chiarire», mai «abrogata» per sbaglio)."""
from __future__ import annotations

import re

_MESI = r"(?:gennaio|febbraio|marzo|aprile|maggio|giugno|luglio|agosto|settembre|ottobre|novembre|dicembre)"

# il TIPO dell'atto (il primo che combacia; l'ordine conta: «regio decreto-legge» prima di «regio decreto»)
_TIPI = (
    (r"regio\s+decreto[\s-]+legge|\br\.?\s?d\.?\s?l\b\.?", "rdl"),
    (r"regio\s+decreto|\br\.\s?d\b\.?", "rd"),
    (r"decreto\s+del\s+presidente\s+della\s+repubblica|\bd\.?\s?p\.?\s?r\b\.?", "dpr"),
    (r"decreto[\s-]+legislativo|\bd\.?\s?lgs\b\.?", "dlgs"),
    (r"decreto[\s-]+legge|\bd\.?\s?l\b\.?(?!\s?gs)", "dl"),
    (r"decreto\s+(?:del\s+)?minist|\bd\.?\s?m\b\.?", "dm"),
    (r"regolamento\s*\(\s*(?:cee|ce|ue)\s*\)|\breg\.?\s*\(\s*(?:cee|ce|ue)\s*\)|\breg(?:olamento)?\.?(?=\s*(?:n\.\s*)?\d{3,4}\s*/\s*\d{2,4})", "reg"),
    (r"\blegge\b|\bl\.\s", "l"),
)
_TIPI_RX = [(re.compile(p, re.I), t) for p, t in _TIPI]
_ETICHETTA = {"rdl": "R.D.L.", "rd": "R.D.", "dpr": "d.P.R.", "dlgs": "d.lgs.", "dl": "d.l.", "dm": "d.m.",
              "reg": "Reg.", "l": "L."}

_NUM_DATA = re.compile(r"\d{1,2}°?\s+" + _MESI + r"\s+(\d{4})\s*,?\s*n\.?\s*(\d{1,5})(?!\d)", re.I)
_NUM_DEL = re.compile(r"n\.?\s*(\d{1,5})\s+del(?:l['’])?\s*(?:anno\s+)?(\d{4})\b", re.I)
_NUM_BARRA = re.compile(r"(?:n\.?\s*)?\b(\d{1,5})\s*/\s*(\d{4}|\d{2})(?![\d/])")

# un atto scritto per NOME, senza numero
_NOMI = (
    (re.compile(r"(?<![a-z])tuld(?![a-z])|testo\s+unico\s+(?:delle\s+disposizioni\s+legislative\s+)?in\s+materia\s+doganale",
                re.I), "dpr:43:1973"),
)

# voci a mano: l'atto che abroga NON è nel corpus (verificato sulla fonte ufficiale)
_MANUALI = {
    # Reg. di esecuzione (UE) 2016/481, art. 1 (EUR-Lex): abrogato dal 1° maggio 2016
    "reg:2454:1993": {"da": "Reg. di esecuzione (UE) 2016/481, art. 1 (dal 1° maggio 2016)",
                      "oggi": "Reg. delegato (UE) 2015/2446 e Reg. di esecuzione (UE) 2015/2447"},
}

_PARZIALE = re.compile(r"\b(?:ad?\s+eccezione|fatt[ao]\s+(?:eccezione|salv)|fatti\s+salvi|salvo|salvi|ad\s+esclusione|"
                       r"limitatamente|per\s+quanto\s+(?:non|riguarda|concerne|attiene)|nella\s+parte|ad\s+esclusione|"
                       r"tranne|eccetto|esclus[oi])\b", re.I)
_PARTE_DI = re.compile(r"\b(?:articol[oi]|art\.|artt\.|comm[ai]|allegat[oi]|tabell[ae]|capo|titolo|sezione|parte|"
                       r"paragraf[oi]|disposizion[ei])\b", re.I)
_ABROGAT = re.compile(r"\babrogat[oiae]\b", re.I)
# l'abrogazione DETTA, non possibile: «è/sono/restano abrogati», «… n. 1393/2007 è abrogato» — mai «può essere modificato o
# abrogato con i decreti…» (APE: il d.P.R. 412/1993 si applica ancora)
_ABROGATO_DETTO = re.compile(r"\b(?:è|e'|sono|resta(?:no)?|vengono|viene|risulta(?:no)?)\s+(?:altresì\s+|pertanto\s+|"
                             r"inoltre\s+|comunque\s+|in\s+particolare\s+)?abrogat[oiae]\b", re.I)


def tipo(testo: str):
    """(tipo, posizione) del primo tipo d'atto nel testo, o (None, -1)."""
    best = None
    for rx, t in _TIPI_RX:
        m = rx.search(testo or "")
        if m and (best is None or m.start() < best[1]):
            best = (t, m.start())
    return best or (None, -1)


def _anno(a: str) -> str:
    return a if len(a) == 4 else ("19" if int(a) >= 46 else "20") + a


def numero_anno(testo: str):
    """Il PRIMO «numero/anno» dell'atto nel testo (forme: «23 gennaio 1973, n. 43», «n. 43 del 1973», «43/1973», «2454/93»)."""
    trovati = []
    for rx, ordine in ((_NUM_DATA, "an"), (_NUM_DEL, "na"), (_NUM_BARRA, "na")):
        m = rx.search(testo or "")
        if m:
            num, anno = (m.group(2), m.group(1)) if ordine == "an" else (m.group(1), m.group(2))
            trovati.append((m.start(), int(num), _anno(anno)))
    if not trovati:
        return None
    _, n, a = min(trovati)
    return str(n), a


def chiave(testo: str) -> str | None:
    """«d.P.R. 23 gennaio 1973, n. 43» → «dpr:43:1973»; «TULD» → «dpr:43:1973». None se manca il tipo o il numero."""
    for rx, k in _NOMI:
        if rx.search(testo or ""):
            return k
    t, pos = tipo(testo)
    if not t:
        return None
    na = numero_anno((testo or "")[pos:pos + 160])
    return f"{t}:{na[0]}:{na[1]}" if na else None


def _propri() -> set[str]:
    """Le chiavi «numero+anno» degli atti che SONO nel corpus italiano (verificatore delle citazioni)."""
    try:
        from .citation_verifier import _IT_CODE_NUM_CHECKS
        return {k for k, _ in _IT_CODE_NUM_CHECKS}
    except Exception:  # noqa: BLE001
        return set()


def _segmenti(body: str):
    """Le voci di un elenco di abrogazioni → (voce, intestazione dell'elenco). L'intestazione è il testo fra l'ultimo
    «… abrogat…:» e la voce, SOLO se in mezzo non comincia un altro periodo o un altro comma (lì la voce non è nell'elenco)."""
    flat = re.sub(r"\s+", " ", body or "")
    pos = 0
    for seg in re.split(r"(;|\.\s+(?=[A-Z])|(?<=\s)[a-z]{1,2}\)\s|(?<=\s)\d{1,2}\)\s)", flat):
        inizio = pos
        pos += len(seg)
        s = seg.strip()
        if not s or re.fullmatch(r";|\.\s+|[a-z]{1,2}\)\s|\d{1,2}\)\s", seg):
            continue
        prima = flat[:inizio]
        h = None
        for h in re.finditer(r"(?:abrogat[ie]|abrogano)\b[^.;:]{0,90}:", prima, re.I):
            pass
        nell_elenco = bool(h) and not re.search(r"\.\s+[A-Z]|\s\d{1,2}\.\s", prima[h.end():])
        # più atti nella stessa voce («Il regolamento (CEE) n. 3925/91, il regolamento (CEE) n. 2913/92 e il … sono abrogati»)
        for pezzo in re.split(r",\s*(?=(?:il|la|l['’])\s*(?:regio|decret|legge|regolament))|\s+e\s+(?=(?:il|la|l['’])\s*(?:regio|decret|legge|regolament))", s):
            yield pezzo.strip(), s, nell_elenco


_INIZIO = re.compile(r"^(?:\d+\.\s*)?(?:(?:sono|è|e')\s+(?:altresì\s+)?abrogat[ie]\s*:?\s*)?(?:il|la|l['’]|i)\s*", re.I)


def costruisci(index) -> dict:
    """Il registro {chiave: {"da": atto che abroga (articolo), "oggi": None}} dal corpus italiano. Cache sull'indice."""
    cached = getattr(index, "_atti_abrogati_it", None)
    if cached is not None:
        return cached
    out: dict = {}
    try:
        from . import corrispondenze_tu as _ctu
        from .citation_verifier import CODE_LABELS
        propri = _propri()
        for a in index.articles:
            body = getattr(a, "body", "") or ""
            if getattr(a, "repealed", False) or not _ABROGAT.search(body):
                continue
            try:
                if _ctu.futuro(a.code):          # testo unico fiscale applicabile dal 2027: l'atto vecchio è vigente oggi
                    continue
            except Exception:  # noqa: BLE001
                pass
            for seg, voce, nell_elenco in _segmenti(body):
                m0 = _INIZIO.match(seg)
                if not m0:
                    continue
                resto = seg[m0.end():]
                t, pos = tipo(resto)
                if not t or pos > 2:                  # la voce deve COMINCIARE con l'atto («il decreto…»), non «gli articoli…»
                    continue
                if _PARTE_DI.search(seg[:m0.end() + pos]) or _PARZIALE.search(voce):
                    continue
                # «abrogat…» nella voce stessa, o la voce sta nell'elenco aperto da «Sono abrogati:»
                if not (_ABROGATO_DETTO.search(voce) or nell_elenco):
                    continue
                na = numero_anno(resto[pos:pos + 160])
                if not na:
                    continue
                k = f"{t}:{na[0]}:{na[1]}"
                if f"{na[0]}{na[1]}" in propri:
                    continue
                lab = CODE_LABELS.get(a.code, a.code)
                num = str(getattr(a, "number", ""))
                if num.endswith("-legge"):            # l'articolo del decreto che approva il codice, non del codice
                    num_vis = num[:-len("-legge")] + " del decreto"
                else:
                    try:
                        from .parser import numero_visibile_it
                        num_vis = numero_visibile_it(num)
                    except Exception:  # noqa: BLE001
                        num_vis = num
                out.setdefault(k, {"da": f"{lab}, art. {num_vis}", "oggi": None})
    except Exception:  # noqa: BLE001
        out = {}
    for k, v in _MANUALI.items():
        out.setdefault(k, dict(v))
    try:
        index._atti_abrogati_it = out
    except Exception:  # noqa: BLE001
        pass
    return out


def cerca(coda: str, index) -> tuple[str, dict] | None:
    """La coda della citazione nomina un atto italiano abrogato fuori corpus? → (chiave, voce). Mai un'eccezione."""
    try:
        k = chiave(coda)
        if not k:
            return None
        reg = costruisci(index)
        return (k, reg[k]) if k in reg else None
    except Exception:  # noqa: BLE001
        return None


def etichetta(k: str) -> str:
    """«dpr:43:1973» → «d.P.R. 43/1973»."""
    try:
        t, n, a = k.split(":")
        return f"{_ETICHETTA.get(t, t)} {n}/{a}"
    except Exception:  # noqa: BLE001
        return k


def testo(k: str, voce: dict) -> str:
    """La riga per il pannello e per il Giudice: «atto abrogato da D.Lgs. 141/2024, art. 8 — oggi …»."""
    s = f"atto abrogato da {voce.get('da')}"
    if voce.get("oggi"):
        s += f" — oggi {voce['oggi']}"
    return s
