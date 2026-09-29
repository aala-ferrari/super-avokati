# -*- coding: utf-8 -*-
"""Le CORRISPONDENZE fra gli articoli delle vecchie leggi fiscali e quelli dei TESTI UNICI 2024-2026 (v9.403).

Ogni articolo dei nuovi testi unici (TUIR, IVA, accertamento, riscossione, registro, sanzioni tributarie, giustizia
tributaria) porta sotto la rubrica la sua FONTE, testo ufficiale: «( articolo 8 del decreto legislativo n. 74 del 2000 )».
Dalle fonti si ricava, per ogni vecchio articolo, dove sta oggi. Misurato (29 set 2026) sulle risposte italiane salvate:
«art. 73, comma 3, TUIR» (l'esterovestizione, numerazione del d.P.R. 917/1986) il verificatore lo dava VERIFICATO sull'art. 73
del TUIR vigente, che parla d'altro («Norme generali sulle componenti del reddito d'impresa»); «art. 8 d.lgs. 74/2000» usciva
«abrogato» senza dire che oggi è l'art. 79 del testo unico delle sanzioni tributarie. Qui:
  - `leggi_fonte(testo)`: dalla riga della fonte le coppie (atto, [articoli]);
  - `costruisci(articoli)`: la mappa {atto: {articolo vecchio: [[codice, articolo nuovo], …]}} (si scrive con l'indice IT);
  - `successori(atto, numero)`: dove sta oggi quel vecchio articolo.
L'atto è una chiave «tipo:numero:anno» («dpr:917:1986», «dlgs:74:2000», «l:190:2014», «dl:331:1993»). Fail-silent: senza
file la mappa è vuota e il verificatore resta com'era."""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

# IT_CORR_PATH: solo per le prove (un indice italiano di prova con la sua mappa, senza toccare i dati della produzione)
FILE = Path(os.environ.get("IT_CORR_PATH") or "/app/data/processed/it_corrispondenze.json")

# I testi unici che portano la fonte sotto la rubrica (gli altri atti non la hanno)
CODICI_TU = ("tuir", "tu_iva", "tu_accertamento", "tu_riscossione", "tu_registro", "tu_sanzioni_tributarie",
             "giustizia_tributaria")

# I vecchi atti che i testi unici ABROGANO dal 1° gennaio 2027 (dal v9.405 il corpus ha il loro testo vigente fino al
# 31/12/2026 e, in `futuro`, la nota «ARTICOLO ABROGATO…»): codice → chiave
CODICE_VECCHIO = {"reati_tributari": "dlgs:74:2000", "iva": "dpr:633:1972", "accertamento_imposte": "dpr:600:1973",
                  "riscossione": "dpr:602:1973", "imposta_registro": "dpr:131:1986", "imposta_successioni": "dlgs:346:1990",
                  "sanzioni_tributarie": "dlgs:472:1997",
                  # v9.409 — i vecchi atti vigenti fino al 31/12/2026 che prima erano fuori corpus («trasfuso»)
                  "tuir_1986": "dpr:917:1986", "processo_tributario": "dlgs:546:1992",
                  "sanzioni_tributarie_amministrative": "dlgs:471:1997", "imposta_ipotecaria_catastale": "dlgs:347:1990",
                  "imposta_bollo": "dpr:642:1972", "adempimento_unico": "dlgs:463:1997"}

# Un testo unico citato col NOME che portava anche il vecchio atto («TUIR» era il d.P.R. 917/1986; «testo unico dell'imposta
# di registro» il d.P.R. 131/1986): se la vecchia numerazione porta a un ALTRO articolo, lo si dice
TU_AMBIGUI = {"tuir": "dpr:917:1986"}

_TIPO = (
    (re.compile(r"decreto\s+del\s+presidente\s+della\s+repubblica|\bd\.?\s?p\.?\s?r\b\.?", re.I), "dpr"),
    (re.compile(r"decreto[\s-]+legislativo|\bd\.?\s?lgs\b\.?", re.I), "dlgs"),
    (re.compile(r"decreto[\s-]+legge|\bd\.?\s?l\b\.?(?!\s?gs)", re.I), "dl"),
    (re.compile(r"\blegge\b|\bl\.\s", re.I), "l"),
)
_MESI = r"(?:gennaio|febbraio|marzo|aprile|maggio|giugno|luglio|agosto|settembre|ottobre|novembre|dicembre)"
_ATTO_ANNO_NUM = re.compile(r"(?:\d{1,2}°?\s+" + _MESI + r"\s+(?:del\s+)?)?(\d{4})\s*,?\s*n\.\s*(\d{1,5})\b", re.I)
_ATTO_NUM_ANNO = re.compile(r"n\.\s*(\d{1,5})\s+del(?:l['’])?\s*(?:anno\s+)?(\d{4})\b", re.I)
_ATTO_BARRA = re.compile(r"\b(\d{1,5})\s*/\s*(\d{4})\b")
_SUFFISSO = r"(?:bis|ter|quater|quinquies|sexies|septies|octies|novies|decies|undecies|duodecies|terdecies|quaterdecies|" \
            r"quinquiesdecies|sexiesdecies|septiesdecies|octiesdecies|noviesdecies|vicies\w*|tricies\w*)"
_NUM_ART = re.compile(r"^\s*(\d{1,4}(?:\s*-\s*" + _SUFFISSO + r")?(?:\s*\.\s*\d{1,2})?)\s*$", re.I)
_SOTTO = re.compile(r"^\s*(?:comm[ai]|lettera|lettere|numero|numeri|periodo|periodi|primo|secondo|terzo|quarto|quinto|"
                    r"sesto|settimo|ultimo|capoverso|punto|punti|da|fino|alinea|parole)\b", re.I)


def _norm_num(s: str) -> str:
    s = re.sub(r"\s+", "", (s or "").lower())
    return s.replace("-", "/").replace("–", "/")


def _tipo(seg: str):
    for rx, t in _TIPO:
        m = rx.search(seg)
        if m:
            return t, m.start()
    return None, -1


def leggi_fonte(testo: str) -> list[tuple[str, list[str]]]:
    """La riga della fonte in testa al corpo di un articolo di testo unico → [(chiave_atto, [articoli normalizzati])].
    Vuota se il corpo non comincia con «( articolo … )». Mai un'eccezione."""
    try:
        t = (testo or "").lstrip()
        if not re.match(r"\(\s*(?:articol[oi]|art\.)\s", t, re.I):
            return []
        # la fonte finisce dove comincia il testo dell'articolo: «\n\n1.», «\n\n01.», «\n\nLa…»
        fine = re.search(r"\n\s*\n\s*(?:0?1\s*\.|[A-ZÀ-Ü])", t)
        fonte = t[: fine.start() if fine else 900][:900]
        fonte = re.sub(r"\s+", " ", fonte).strip().lstrip("(").rstrip(") .")
        out: list[tuple[str, list[str]]] = []
        for seg in fonte.split(";"):
            seg = re.sub(r",?\s*convertit\w*.*$", "", seg, flags=re.I).strip()   # «…, convertito dalla legge …» non è la fonte
            tipo, pos = _tipo(seg)
            if not tipo or pos < 0:
                continue
            atto = seg[pos:]
            m = _ATTO_NUM_ANNO.search(atto)
            if m:
                num, anno = m.group(1), m.group(2)
            else:
                m = _ATTO_ANNO_NUM.search(atto)
                if m:
                    anno, num = m.group(1), m.group(2)
                else:
                    m = _ATTO_BARRA.search(atto)
                    if not m:
                        continue
                    num, anno = m.group(1), m.group(2)
            testa = seg[:pos]
            mm = re.search(r"\barticol[oi]\b|\bart\.", testa, re.I)
            if not mm:
                continue
            testa = re.sub(r"\s+(?:del|della|dello|dei|degli|delle|dal|dalla|di)\s*$", "", testa[mm.end():].strip(), flags=re.I)
            pezzi = re.split(r",|\s+e\s+", testa)
            arts: list[str] = []
            prec_sotto = False
            for p in pezzi:
                p = p.strip()
                if not p:
                    continue
                if _SOTTO.match(p):
                    prec_sotto = True
                    continue
                mn = _NUM_ART.match(p)
                if mn and not prec_sotto:
                    n = _norm_num(mn.group(1))
                    if n not in arts:
                        arts.append(n)
                elif not mn:
                    prec_sotto = False
                # un numero dopo «comma 1» / «commi 3» resta un comma, non un articolo
            if arts:
                out.append((f"{tipo}:{int(num)}:{anno}", arts))
        return out
    except Exception:  # noqa: BLE001
        return []


_DECORRENZA_RE = re.compile(r"disposizioni del presente testo unico si applicano\s+(?:a\s+decorrere\s+)?dal\s+(\d{1,2})°?\s+("
                            + _MESI[3:-1] + r")\s+(\d{4})", re.I)
_MESI_N = {m: i for i, m in enumerate(("gennaio", "febbraio", "marzo", "aprile", "maggio", "giugno", "luglio", "agosto",
                                        "settembre", "ottobre", "novembre", "dicembre"), 1)}


def _chiave_da_urn(urn: str) -> str | None:
    """«decreto.legislativo:2024-11-05;173» → «dlgs:173:2024»."""
    m = re.match(r"(decreto\.legislativo|decreto\.presidente\.repubblica|decreto\.legge|legge):(\d{4})-\d{2}-\d{2};(\d+)", urn or "")
    if not m:
        return None
    t = {"decreto.legislativo": "dlgs", "decreto.presidente.repubblica": "dpr", "decreto.legge": "dl", "legge": "l"}[m.group(1)]
    return f"{t}:{int(m.group(3))}:{m.group(2)}"


def costruisci(articoli, urns: dict | None = None) -> dict:
    """Dagli articoli dell'indice IT (Article con code/number/body) la mappa delle corrispondenze.
    v9.404: anche `_decorrenza` (codice del testo unico → data da cui si applica, letta dal suo articolo «Decorrenza»: per tutti
    e sette «dal 1° gennaio 2027») e `_atto_tu` (codice → chiave dell'atto che lo approva, dalla URN), perché un articolo
    vecchio «ABROGATO DAL D.LGS. 5 NOVEMBRE 2024, N. 173» è in vigore fino al giorno prima."""
    mappa: dict = {"_decorrenza": {}, "_atto_tu": {}}
    for code, urn in (urns or {}).items():
        if code in CODICI_TU:
            k = _chiave_da_urn(urn)
            if k:
                mappa["_atto_tu"][code] = k
    for a in articoli:
        if getattr(a, "code", "") in CODICI_TU and not getattr(a, "repealed", False):
            m = _DECORRENZA_RE.search(getattr(a, "body", "") or "")
            if m and m.group(2).lower() in _MESI_N:
                mappa["_decorrenza"][a.code] = f"{int(m.group(3)):04d}-{_MESI_N[m.group(2).lower()]:02d}-{int(m.group(1)):02d}"
    for a in articoli:
        if getattr(a, "code", "") not in CODICI_TU or getattr(a, "repealed", False):
            continue
        for chiave, arts in leggi_fonte(getattr(a, "body", "") or ""):
            d = mappa.setdefault(chiave, {})
            for n in arts:
                lst = d.setdefault(n, [])
                v = [a.code, str(a.number)]
                if v not in lst:
                    lst.append(v)
    return mappa


_CACHE: dict = {"mtime": None, "mappa": {}}


def carica() -> dict:
    try:
        mt = FILE.stat().st_mtime
    except OSError:
        return {}
    if _CACHE["mtime"] != mt:
        try:
            _CACHE["mappa"] = json.loads(FILE.read_text(encoding="utf-8")) or {}
        except Exception:  # noqa: BLE001
            _CACHE["mappa"] = {}
        _CACHE["mtime"] = mt
    return _CACHE["mappa"]


# ── v9.404: LA DATA. I testi unici fiscali si applicano dal 1° gennaio 2027 e le abrogazioni dei vecchi atti decorrono da lì;
# Normattiva, aperta senza data, mostra già la versione futura («ARTICOLO ABROGATO DAL D.LGS. …»: verificato — con «!vig=» di oggi
# l'art. 8 d.lgs. 74/2000 ha il testo «in vigore dal 27-10-2019 al 31-12-2026»). Fino al giorno prima la norma vecchia è VIGENTE.
from datetime import date as _date, timedelta as _td

_OGGI_FORZATO = None           # solo per le prove (golden): una data finta


def oggi() -> _date:
    return _OGGI_FORZATO or _date.today()


def decorrenza(code: str) -> _date | None:
    """La data da cui si applica il testo unico `code` (None se non la conosciamo)."""
    try:
        d = (carica().get("_decorrenza") or {}).get(code)
        return _date.fromisoformat(d) if d else None
    except Exception:  # noqa: BLE001
        return None


def futuro(code: str) -> _date | None:
    """La decorrenza del testo unico `code` se è ancora da venire, altrimenti None."""
    d = decorrenza(code)
    return d if d and d > oggi() else None


def fino_al(d: _date) -> str:
    return (d - _td(days=1)).strftime("%d/%m/%Y")


_STUB_RE = re.compile(r"(?:ARTICOLO|PROVVEDIMENTO)\s+ABROGATO\s+DA(?:L|LLA)?\s+(D\.\s?LGS\.|D\.\s?P\.\s?R\.|D\.\s?L\.|L\.)\s*"
                      r"(\d{1,2})°?\s+(\w+)\s+(\d{4})\s*,?\s*N\.\s*(\d+)", re.I)


def abrogazione_differita(body: str):
    """L'articolo abrogato da un testo unico che non si applica ancora → (codice del testo unico, decorrenza); altrimenti None.
    «ARTICOLO ABROGATO DALLA L. 30 DICEMBRE 1991, N.413» resta abrogato davvero."""
    try:
        m = _STUB_RE.search((body or "")[:400])
        if not m:
            return None
        tipo = {"dlgs": "dlgs", "dpr": "dpr", "dl": "dl", "l": "l"}.get(re.sub(r"[^a-z]", "", m.group(1).lower()), "")
        k = f"{tipo}:{int(m.group(5))}:{m.group(4)}"
        for code, kk in (carica().get("_atto_tu") or {}).items():
            if kk == k:
                d = futuro(code)
                return (code, d) if d else None
        return None
    except Exception:  # noqa: BLE001
        return None


def nota_decorrenza(code: str, lang: str = "it") -> str:
    """La riga per il blocco degli articoli: il testo unico non si applica ancora (vuota se si applica o non è un testo unico)."""
    d = futuro(code)
    if not d:
        return ""
    return (f"⚠ TESTO UNICO APPLICABILE DAL {d:%d/%m/%Y}: per fatti, atti e dichiarazioni fino al {fino_al(d)} si applica la norma "
            f"previgente indicata fra parentesi sotto la rubrica (questo testo la trasfonde): cita quella, e il numero nuovo solo "
            f"come «dal {d:%d/%m/%Y}»")


def vigenza(code: str, numero: str) -> dict | None:
    """v9.405 — la vigenza di un articolo il cui testo cambia (o che si abroga, o che non c'è ancora) più avanti:
    {"fino", "dal", "futuro_abrogato", "futuro_rubrica", "futuro_testo", "non_in_vigore_dal"} se la data è ancora da venire,
    altrimenti None (il build successivo avrà già il testo giusto)."""
    try:
        v = ((carica().get("_vigenze") or {}).get(code) or {}).get(str(numero))
        if not v:
            return None
        oggi_iso = oggi().isoformat()
        if v.get("non_in_vigore_dal") and v["non_in_vigore_dal"] > oggi_iso:
            return v
        if v.get("dal") and v["dal"] > oggi_iso:
            return v
        return None
    except Exception:  # noqa: BLE001
        return None


def vigenza_scaduta(code: str, numero: str) -> dict | None:
    """v9.405 — l'indice è stato costruito PRIMA della data da cui l'articolo cambia (o si abroga), e quella data è passata:
    il testo nell'indice non è più quello vigente. Le voci di `_vigenze` si scrivono solo per date future al momento del
    build, quindi una voce con la data già passata = indice da ricostruire (il cron del 1° gennaio lo fa; questa è la rete)."""
    try:
        v = ((carica().get("_vigenze") or {}).get(code) or {}).get(str(numero))
        if not v or v.get("non_in_vigore_dal") or not v.get("dal"):
            return None
        return v if v["dal"] <= oggi().isoformat() else None
    except Exception:  # noqa: BLE001
        return None


def _gg(iso: str) -> str:
    try:
        return _date.fromisoformat(iso).strftime("%d/%m/%Y")
    except Exception:  # noqa: BLE001
        return iso or ""


def nota_vigenza(code: str, numero: str) -> str:
    """La riga per il blocco degli articoli: testo vigente fino a …, poi abrogato / modificato / non ancora in vigore."""
    v = vigenza(code, numero)
    if not v:
        vs = vigenza_scaduta(code, numero)
        if not vs:
            return ""
        if vs.get("futuro_abrogato"):
            return (f"⚠ ARTICOLO ABROGATO DAL {_gg(vs['dal'])}: il testo qui sotto era vigente fino ad allora — si applica "
                    f"solo a fatti e atti anteriori")
        return (f"⚠ TESTO CAMBIATO DAL {_gg(vs['dal'])}: il testo qui sotto è quello anteriore — oggi vige: "
                f"«{(vs.get('futuro_testo') or '')[:400]}…»")
    if v.get("non_in_vigore_dal"):
        return f"⚠ ARTICOLO NON ANCORA IN VIGORE: si applica dal {_gg(v['non_in_vigore_dal'])} — non citarlo come norma vigente"
    fino = f"fino al {_gg(v['fino'])}" if v.get("fino") else f"fino al giorno prima del {_gg(v['dal'])}"
    if v.get("futuro_abrogato"):
        return (f"ℹ TESTO VIGENTE {fino.upper()}: dal {_gg(v['dal'])} l'articolo è ABROGATO — per fatti e atti fino ad allora "
                f"si applica questo testo")
    return (f"ℹ TESTO VIGENTE {fino.upper()}: dal {_gg(v['dal'])} cambia" +
            (f" («{v['futuro_rubrica']}»)" if v.get("futuro_rubrica") else "") +
            (f": «{v['futuro_testo'][:300]}…»" if v.get("futuro_testo") else ""))


_INV: dict = {"mtime": None, "mappa": {}}


def previgenti(code: str, numero: str) -> list[tuple[str, str]]:
    """v9.405 — l'inverso di `successori`: l'articolo del testo unico → gli articoli dei vecchi atti DEL CORPUS che trasfonde
    («art. 79 TU sanzioni tributarie» → («reati_tributari», "8")). Prima del 1° gennaio 2027 sono quelli che si applicano."""
    try:
        m = carica()
        if _INV["mtime"] is not _CACHE.get("mtime") or not _INV["mappa"]:
            inv: dict = {}
            vecchio_per_chiave = {v: k for k, v in CODICE_VECCHIO.items()}
            for chiave, arts in m.items():
                if chiave.startswith("_") or chiave not in vecchio_per_chiave or not isinstance(arts, dict):
                    continue
                for num, lst in arts.items():
                    for c, n in (lst or []):
                        inv.setdefault((c, str(n)), []).append((vecchio_per_chiave[chiave], str(num)))
            _INV["mappa"], _INV["mtime"] = inv, _CACHE.get("mtime")
        return list(dict.fromkeys(_INV["mappa"].get((code, str(numero)), [])))
    except Exception:  # noqa: BLE001
        return []


def successori(chiave: str, numero: str) -> list[tuple[str, str]]:
    """Dove sta oggi l'art. `numero` del vecchio atto `chiave` («dlgs:74:2000», «8») → [(codice, articolo)], al massimo 3."""
    try:
        d = carica().get(chiave) or {}
        return [(c, n) for c, n in (d.get(_norm_num(numero)) or [])][:3]
    except Exception:  # noqa: BLE001
        return []


_ETICHETTA = {"dpr": "d.P.R.", "dlgs": "d.lgs.", "dl": "d.l.", "l": "l."}


def etichetta_atto(chiave: str) -> str:
    """«dpr:917:1986» → «d.P.R. 917/1986»."""
    try:
        t, n, a = chiave.split(":")
        return f"{_ETICHETTA.get(t, t)} {n}/{a}"
    except Exception:  # noqa: BLE001
        return chiave


def chiave_da_coda(coda: str) -> str | None:
    """Nella coda di una citazione («… del d.P.R. 22 dicembre 1986, n. 917», «d.lgs. 471/1997») la chiave dell'atto SE è
    uno dei vecchi atti trasfusi nei testi unici (cioè presente nella mappa); altrimenti None."""
    try:
        mappa = carica()
        if not mappa:
            return None
        c = (coda or "")[:220]
        tipo, pos = _tipo(c)
        if not tipo:
            return None
        atto = c[pos:]
        # il PRIMO numero d'atto dopo il tipo (non il primo tipo di scrittura: «d.P.R. 22 dicembre 1986, n. 917 e d.lgs.
        # n. 471 del 1997» è il 917)
        trovati = []
        for rx, ordine in ((_ATTO_NUM_ANNO, "na"), (_ATTO_BARRA, "na"), (_ATTO_ANNO_NUM, "an")):
            m = rx.search(atto)
            if m:
                num, anno = (m.group(1), m.group(2)) if ordine == "na" else (m.group(2), m.group(1))
                trovati.append((m.start(), f"{tipo}:{int(num)}:{anno}"))
        if not trovati:
            return None
        k = min(trovati)[1]
        return k if k in mappa else None
    except Exception:  # noqa: BLE001
        return None
