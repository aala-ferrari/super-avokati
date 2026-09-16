# -*- coding: utf-8 -*-
"""TEMPO — «quale versione della norma valeva alla data del fatto?» (v9.333, roadmap v3 P3,
versione economica: multivigenza ON DEMAND, senza riscrivere il corpus).

Il corpus è il testo vigente OGGI. Ma contenzioso, penale, tributario, successioni e contratti
vivono di tempus regit actum: la legge da applicare è quella in vigore alla data del fatto (nel
penale con il favor rei). Qui:
  1. `data_fatto(testo)` — legge dalla domanda le date esplicite (17/03/2021, 17 marzo 2021, më
     17.3.2021, «nel 2021», «në vitin 2021»), scarta le date di nascita e quelle recenti (< 1 anno:
     il testo è quello di oggi) e sceglie la PIÙ VECCHIA come data del fatto.
  2. IT — `versione_it(code, number, data)`: Normattiva multivigenza (la stessa URN con
     «!vig=AAAA-MM-GG»; verificato il 16 set: L. 91/1992 art. 9-ter → «quarantotto mesi» al
     2019, «ventiquattro… trentasei» oggi). Per gli articoli recuperati (≤6, ≤45 s) si confronta il
     testo storico col nostro: se DIVERSO entra nel dossier con il testo integrale di allora.
  3. AL — QBZ non ha la multivigenza per articolo: si legge dalla REST aperta la lista degli atti
     che hanno MODIFICATO la legge (`qbz:actChanges`) e si avvisa quali modifiche sono POSTERIORI
     alla data del fatto (il testo nostro è quello consolidato oggi).
  4. Il blocco «⏳ TESTO VIGENTE AL …» entra nel dossier dei raccoglitori → lo leggono il senior e il
     Giudice (regola nel prompt del Giudice); la Trust Line mostra l'asse «tempo».
Mai bloccare, mai inventare: se Normattiva non risponde, il blocco non c'è e la risposta esce
com'era; «testo uguale a oggi» è un'informazione (certezza temporale), non silenzio.
"""
from __future__ import annotations

import importlib.util
import json
import re
import threading
import time
import urllib.parse
import urllib.request
from datetime import date, timedelta
from pathlib import Path

from .logging_utils import get_logger

# ⚠️ get_logger, non logging.getLogger: solo i logger creati da logging_utils hanno gli handler
# (file + stdout); con getLogger(__name__) le righe INFO sparivano (misurato il 16 set: nessun
# «temporal:» nel log della prova viva, mentre il blocco era stato costruito davvero)
log = get_logger(__name__)

_MESI_IT = {"gennaio": 1, "febbraio": 2, "marzo": 3, "aprile": 4, "maggio": 5, "giugno": 6, "luglio": 7,
            "agosto": 8, "settembre": 9, "ottobre": 10, "novembre": 11, "dicembre": 12}
_MESI_SQ = {"janar": 1, "shkurt": 2, "mars": 3, "prill": 4, "maj": 5, "qershor": 6, "korrik": 7,
            "gusht": 8, "shtator": 9, "tetor": 10, "nëntor": 11, "nentor": 11, "dhjetor": 12}
_DATE_NUM = re.compile(r"(?<!\d)(\d{1,2})[./-](\d{1,2})[./-]((?:19|20)\d{2})(?!\d)")
_DATE_IT = re.compile(r"(?<!\w)(\d{1,2})[°º]?\s+(" + "|".join(_MESI_IT) + r")\s+((?:19|20)\d{2})(?!\d)", re.I)
_DATE_SQ = re.compile(r"(?<!\w)(\d{1,2})\s+(" + "|".join(_MESI_SQ) + r")\s+((?:19|20)\d{2})(?!\d)", re.I)
_YEAR = re.compile(r"(?<![\w/.-])(?:nel|del|dal|dall'|in|anno|nell'anno|në vitin|vitin|gjatë vitit|që nga|prej|më)\s+((?:19|20)\d{2})(?![\d/.-])", re.I)
_NASCITA = re.compile(r"(nat[oa]|nascit|lindur|datëlindj|datelindj|i lindur|e lindur)", re.I)


def date_nel_testo(text: str) -> list[tuple[date, str, bool]]:
    """Tutte le date (data, testo grezzo, approssimata=solo anno) in ordine di apparizione."""
    out: list[tuple[date, str, bool]] = []
    text = text or ""
    for m in _DATE_NUM.finditer(text):
        d, mo, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
        try:
            out.append((date(y, mo, d), m.group(0), False))
        except ValueError:
            pass
    for rx, mesi in ((_DATE_IT, _MESI_IT), (_DATE_SQ, _MESI_SQ)):
        for m in rx.finditer(text):
            try:
                out.append((date(int(m.group(3)), mesi[m.group(2).lower()], int(m.group(1))), m.group(0), False))
            except (ValueError, KeyError):
                pass
    for m in _YEAR.finditer(text):
        y = int(m.group(1))
        out.append((date(y, 7, 1), m.group(0), True))
    return out


def data_fatto(text: str, oggi: date | None = None) -> tuple[date, str, bool] | None:
    """La data del fatto: la più vecchia fra quelle esplicite, ≥ 1990, ≥ 365 giorni fa, non di nascita."""
    oggi = oggi or date.today()
    cand = []
    for d, raw, approx in date_nel_testo(text):
        if d.year < 1990 or d > oggi - timedelta(days=365):
            continue
        pos = (text or "").find(raw)
        if pos >= 0 and _NASCITA.search((text or "")[max(0, pos - 40):pos]):
            continue
        cand.append((d, raw, approx))
    if not cand:
        return None
    cand.sort(key=lambda c: c[0])
    return cand[0]


# ── IT: Normattiva multivigenza ──────────────────────────────────────────────
_LOCK = threading.Lock()
_ACT_CACHE: dict[tuple[str, str], tuple[float, object, str]] = {}   # (urn, vig) → (ts, sessione, html)
_URN_MAP: dict[str, str] | None = None
_LIB = None


def _lib():
    global _LIB
    if _LIB is None:
        p = Path(__file__).resolve().parent.parent / "tools" / "normattiva_lib.py"
        spec = importlib.util.spec_from_file_location("normattiva_lib", str(p))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        _LIB = mod
    return _LIB


def _urn_map() -> dict[str, str]:
    global _URN_MAP
    if _URN_MAP is None:
        m: dict[str, str] = {}
        try:
            from .config import PROCESSED_DATA_PATH
            for f in (Path(PROCESSED_DATA_PATH) / "it_acts").glob("*.json"):
                try:
                    d = json.loads(f.read_text(encoding="utf-8"))
                    if d.get("urn"):
                        m[d.get("id") or f.stem] = d["urn"]
                except Exception:  # noqa: BLE001
                    pass
        except Exception:  # noqa: BLE001
            log.debug("temporal: mappa urn non caricata", exc_info=True)
        _URN_MAP = m
    return _URN_MAP


def _norm_num(s: str) -> str:
    return re.sub(r"[\s\-\.]", "", (s or "").lower())


def _norm_body(s: str) -> str:
    """Testo confrontabile: via le marcature «((…))» di Normattiva e i NUMERI DI NOTA a sé
    («((13))» nel testo storico, «13» su una riga nel nostro corpus pulito): l'art. 5 L. 91/1992
    risultava «DIVERSO» al 2019 per un «13» di troppo (misurato il 16 set)."""
    s = re.sub(r"\(\(\s*\d{1,3}\s*\)\)", " ", s or "")
    s = re.sub(r"(?m)^\s*\d{1,3}\s*$", " ", s)
    s = re.sub(r"\(\(|\)\)", " ", s)
    # la punteggiatura non è una modifica normativa: la versione storica arriva senza il punto
    # finale («…dai coniugi ))» contro «…dai coniugi.») e risultava «DIVERSA»
    s = re.sub(r"[.,;:()\[\]«»\"“”'’]", " ", s)
    return re.sub(r"\s+", " ", s).strip().lower()


def _act_page(urn: str, vig: date):
    key = (urn, vig.isoformat())
    with _LOCK:
        hit = _ACT_CACHE.get(key)
        if hit and time.time() - hit[0] < 6 * 3600:
            return hit[1], hit[2]
    lib = _lib()
    n = lib.Normattiva(delay=0.45)
    html = n.open_act(f"{urn}!vig={vig.isoformat()}")
    with _LOCK:
        if len(_ACT_CACHE) > 64:
            _ACT_CACHE.clear()
        _ACT_CACHE[key] = (time.time(), n, html)
    return n, html


def versione_it(code: str, number: str, when: date) -> dict | None:
    """Il testo dell'articolo in vigore alla data `when` (Normattiva). None se non determinabile."""
    urn = _urn_map().get(code)
    if not urn:
        return None
    lib = _lib()
    n, html = _act_page(urn, when)
    want = _norm_num(number)
    href = None
    for u, label, _grp in lib.Normattiva.article_links_all(html):
        if _norm_num(label.replace("art.", "")) == want:
            href = u
            break
    if not href:
        return None
    page = n.fetch_article(href)
    parsed = lib.parse_article_page(page, fallback_number=number)
    if not isinstance(parsed, dict):
        return None
    return {"number": number, "heading": parsed.get("heading") or "", "body": parsed.get("body") or "",
            "repealed": bool(parsed.get("repealed")), "vig": when.isoformat()}


_IT_NOTES: dict | None = None


def _it_notes() -> dict:
    """code -> number -> [note] scritto da build_it_index (P3b-IT): storia + disciplina transitoria."""
    global _IT_NOTES
    if _IT_NOTES is None:
        try:
            from .config import PROCESSED_DATA_PATH
            p = Path(PROCESSED_DATA_PATH) / "it_notes.json"
            _IT_NOTES = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
        except Exception:  # noqa: BLE001
            _IT_NOTES = {}
    return _IT_NOTES


def note_articolo_it(code: str, number: str) -> list[dict]:
    return list((_it_notes().get(code) or {}).get(str(number)) or [])


def blocco_it(retrieved, quando: date, raw: str, approx: bool, lang: str = "it",
              max_art: int = 6, budget_s: float = 45.0) -> tuple[str, dict]:
    """Confronta gli articoli recuperati con la versione alla data del fatto; aggiunge le note di
    aggiornamento (atti modificanti + disciplina transitoria) posteriori al fatto, se le abbiamo."""
    t0 = time.time()
    diversi, uguali, saltati, note = [], [], [], []
    seen = set()
    for a, _s in retrieved:
        if len(seen) >= max_art or time.time() - t0 > budget_s:
            break
        k = (a.code, str(a.number))
        if k in seen or a.repealed:
            continue
        seen.add(k)
        post = [n for n in note_articolo_it(a.code, str(a.number)) if (n.get("date") or "") > quando.isoformat()]
        if post:
            note.append((a, post))
        try:
            v = versione_it(a.code, str(a.number), quando)
        except Exception as exc:  # noqa: BLE001
            log.info("temporal: %s %s non letto (%s)", a.code, a.number, type(exc).__name__)
            v = None
        if v is None:
            saltati.append(k)
            continue
        if _norm_body(v["body"]) == _norm_body(a.body):
            uguali.append(k)
        else:
            diversi.append((a, v))
    info = {"data": quando.isoformat(), "raw": raw, "approx": approx, "diversi": len(diversi),
            "uguali": len(uguali), "saltati": len(saltati), "note": len(note)}
    if not diversi and not uguali and not note:
        return "", info
    d = quando.strftime("%d/%m/%Y")
    righe = [f"⏳ TESTO VIGENTE AL {d} — data del fatto letta dalla domanda: «{raw}»"
             + (" (solo l'anno: presa la metà dell'anno)" if approx else "")
             + ". Regola: tempus regit actum (nel penale, favor rei). Fonti: Normattiva multivigenza + note di aggiornamento."]
    for a, v in diversi:
        righe.append(f"\n• art. {a.number} {a.title_sq} — il testo in vigore al {d} era DIVERSO da quello di oggi:\n"
                     f"{(v['heading'] + chr(10)) if v['heading'] else ''}{v['body'][:1800]}")
    for a, post in note:
        righe.append(f"\n• art. {a.number} {a.title_sq} — modificato DOPO la data del fatto; note di aggiornamento (Normattiva):")
        for n in post[:3]:
            righe.append(f"   - [{n.get('date') or '?'}] {', '.join(n.get('acts') or [])}: {(n.get('text') or '')[:500]}")
    if uguali:
        righe.append("\n• Testo identico a quello di oggi al " + d + ": "
                     + ", ".join(f"art. {n} {c}" for c, n in uguali) + ".")
    if saltati:
        righe.append("• Non verificabili su Normattiva: " + ", ".join(f"{c} {n}" for c, n in saltati) + ".")
    return "\n".join(righe), info


# ── AL: le note editoriali PER ARTICOLO (P3b) — «(Ndryshuar … me ligjin nr. 48/2012, datë 26.4.2012)» ──
# Nei consolidati QBZ ogni articolo modificato porta la nota con l'atto e la data (1.665 note nel
# corpus, spesso con le parole incollate: «ligjinnr.48/2012,datë 26.4.2012»). Sono la storia
# dell'articolo, gratis e precisa: prima si guarda qui, poi l'atto intero su QBZ.
_NOTE_RE = re.compile(r"(?:ligjin|vendimin|aktin|dekretin|ligj\.?)\s*nr\.?\s*(\d[\d ]{0,5}(?:/\d{4})?)\s*,?\s*dat[ëe]\s*(\d{1,2})\.(\d{1,2})\.(\d{4})", re.I)


def modifiche_nene(article) -> list[tuple[date, str]]:
    """(data, «ligji nr. X») per ogni atto citato nelle note editoriali dell'articolo, in ordine."""
    txt = (getattr(article, "heading", "") or "") + "\n" + (getattr(article, "body", "") or "")
    out: dict[tuple[date, str], None] = {}
    for m in _NOTE_RE.finditer(txt):
        try:
            d = date(int(m.group(4)), int(m.group(3)), int(m.group(2)))
        except ValueError:
            continue
        num = re.sub(r"\s+", "", m.group(1))
        out[(d, f"nr. {num}")] = None
    return sorted(out)


def ultima_modifica(article) -> str:
    """La data (ISO) dell'ultima modifica nota dell'articolo, o «»."""
    mods = modifiche_nene(article)
    return mods[-1][0].isoformat() if mods else ""


# ── AL: QBZ — modifiche posteriori alla data del fatto ───────────────────────
_QBZ = "https://qbz.gov.al/alfresco/api/-default-/public/alfresco/versions/1"
_QBZ_URL = re.compile(r"webdav/Aktet/(?P<kind>ligj|vendim)/(?P<inst>[^/]+)/(?P<y>\d{4})/(?P<m>\d{2})/(?P<d>\d{2})/(?P<num>[^/]+)/")
_AL_SRC: dict | None = None
_CHG_CACHE: dict[str, tuple[float, list]] = {}


def _qbz(path: str, **params) -> dict:
    url = f"{_QBZ}/{path}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read().decode("utf-8", "replace"))


def _al_sources() -> dict:
    global _AL_SRC
    if _AL_SRC is None:
        m: dict = {}
        try:
            p = Path(__file__).resolve().parent.parent / "tools" / "al_sources.json"
            for law in json.loads(p.read_text(encoding="utf-8")).get("laws", []):
                if "code" in law:
                    m[law["code"]] = law
        except Exception:  # noqa: BLE001
            log.debug("temporal: al_sources non letto", exc_info=True)
        _AL_SRC = m
    return _AL_SRC


def modifiche_al(code: str) -> list[tuple[date, str, str]]:
    """Gli atti che hanno modificato la legge `code` (QBZ actChanges): (data, numero, titolo)."""
    with _LOCK:
        hit = _CHG_CACHE.get(code)
        if hit and time.time() - hit[0] < 24 * 3600:
            return hit[1]
    law = _al_sources().get(code)
    out: list[tuple[date, str, str]] = []
    m = _QBZ_URL.search((law or {}).get("url") or "")
    if m:
        g = m.groupdict()
        rel = f"Aktet/{g['kind']}/{g['inst']}/{g['y']}/{g['m']}/{g['d']}/{g['num']}/base"
        base = _qbz("nodes/-root-/children", relativePath=rel, include="properties")["list"]["entries"]
        node = next((e["entry"] for e in base if e["entry"].get("nodeType") == "qbz:act"), None)
        if node:
            chg = _qbz(f"nodes/{node['id']}/sources", where="(assocType='qbz:actChanges')",
                       include="properties", maxItems=100)["list"]["entries"]
            for c in chg:
                p = c["entry"].get("properties", {})
                ds = (p.get("qbz:actDate") or "")[:10]
                try:
                    out.append((date.fromisoformat(ds), str(p.get("qbz:actNumber") or ""), (p.get("qbz:actTitle") or "")[:120]))
                except ValueError:
                    pass
    out.sort()
    with _LOCK:
        _CHG_CACHE[code] = (time.time(), out)
    return out


def blocco_al(retrieved, quando: date, raw: str, approx: bool, max_codes: int = 4,
              budget_s: float = 25.0) -> tuple[str, dict]:
    """AL: prima le note editoriali PER ARTICOLO (gratis, precise), poi l'atto intero su QBZ per i
    codici i cui articoli recuperati non portano note."""
    t0 = time.time()
    titoli = {a.code: a.title_sq for a, _ in retrieved}
    nene_dopo, nene_prima = [], []
    seen: set = set()
    for a, _s in retrieved:
        k = (a.code, str(a.number))
        if k in seen:
            continue
        seen.add(k)
        mods = modifiche_nene(a)
        post = [m for m in mods if m[0] > quando]
        if post:
            nene_dopo.append((a, post))
        elif mods:
            nene_prima.append(a)
    codes: list[str] = []
    for a, _s in retrieved:
        if a.code not in codes:
            codes.append(a.code)
        if len(codes) >= max_codes:
            break
    dopo, prima, saltati = [], [], []
    for code in codes:
        if any(a.code == code for a, _p in nene_dopo):
            continue                      # già detto per articolo, più preciso
        if time.time() - t0 > budget_s:
            saltati.append(code); continue
        try:
            chg = modifiche_al(code)
        except Exception as exc:  # noqa: BLE001
            log.info("temporal: QBZ %s non letto (%s)", code, type(exc).__name__)
            saltati.append(code); continue
        post = [c for c in chg if c[0] > quando]
        (dopo if post else prima).append((code, post))
    info = {"data": quando.isoformat(), "raw": raw, "approx": approx,
            "diversi": len(nene_dopo) + len(dopo), "uguali": len(nene_prima) + len(prima), "saltati": len(saltati)}
    if not (nene_dopo or nene_prima or dopo or prima):
        return "", info
    d = quando.strftime("%d.%m.%Y")
    righe = [f"⏳ LIGJI NË FUQI MË {d} — data e faktit e lexuar nga pyetja: «{raw}»"
             + (" (vetëm viti: marrë mesi i vitit)" if approx else "")
             + ". Rregulli: tempus regit actum (në penale, ligji më i favorshëm). Burimet: notat e neneve "
               "në tekstin e konsoliduar + QBZ (aktet ndryshuese)."]
    for a, post in nene_dopo:
        righe.append(f"\n• Neni {a.number} i {a.title_sq}: NDRYSHUAR pas datës së faktit me "
                     + "; ".join(f"ligjin {n} ({dt.strftime('%d.%m.%Y')})" for dt, n in post[:4])
                     + " — teksti ynë është ai i sotëm; për faktin zbatohet versioni i atëhershëm, verifikoje.")
    for code, post in dopo:
        righe.append(f"\n• {titoli.get(code, code)}: nenet e gjetura nuk kanë nota, por ligji është NDRYSHUAR pas "
                     f"datës së faktit nga: " + "; ".join(f"ligji nr. {n} ({dt.strftime('%d.%m.%Y')})" for dt, n, _t in post[:6])
                     + ". Verifiko cili version zbatohet për faktin.")
    if nene_prima or prima:
        righe.append("\n• Pa ndryshime pas datës së faktit: "
                     + ", ".join([f"neni {a.number} {a.title_sq}" for a in nene_prima[:8]] + [titoli.get(c, c) for c, _ in prima]) + ".")
    if saltati:
        righe.append("• Nuk u verifikuan në QBZ: " + ", ".join(saltati) + ".")
    return "\n".join(righe), info


# ── punto d'innesto ──────────────────────────────────────────────────────────
_CTX = threading.local()


def ultimo_info() -> dict | None:
    return getattr(_CTX, "info", None)


def imposta_info(info: dict | None) -> None:
    """Riporta nel thread della richiesta l'info calcolata in un worker (stage «skuadra_gather»)."""
    _CTX.info = info


def arricchisci_dosje(dosja: str, user_message: str, retrieved, jurisdiction: str, lang: str) -> str:
    """Appende al dossier il blocco temporale se la domanda porta una data del fatto."""
    _CTX.info = None
    df = data_fatto(user_message)
    if not df:
        return dosja
    quando, raw, approx = df
    try:
        if (jurisdiction or "AL").upper() == "IT":
            blocco, info = blocco_it(retrieved, quando, raw, approx, lang=lang)
        else:
            blocco, info = blocco_al(retrieved, quando, raw, approx)
    except Exception as exc:  # noqa: BLE001
        log.warning("temporal: blocco non costruito (non-fatal): %s", exc)
        return dosja
    _CTX.info = info
    log.info("temporal: data del fatto %s (%s) — diversi %s, uguali %s, saltati %s", info["data"], raw,
             info["diversi"], info["uguali"], info["saltati"])
    if not blocco:
        return dosja
    return (dosja + "\n\n" + blocco) if (dosja or "").strip() else blocco
