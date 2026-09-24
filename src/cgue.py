# -*- coding: utf-8 -*-
"""v9.389 — LA CORTE DI GIUSTIZIA UE: le cause citate («C-274/20») si riscontrano sull'archivio ufficiale dell'Ufficio delle
pubblicazioni (CELLAR), la stessa fonte del testo dei regolamenti UE (v9.384).

Perché (misurato il 25 set sulle 44 risposte italiane salvate): 61 citazioni di cause CGUE, 10 distinte, e il verificatore
non ne guardava nessuna — la C-274/20 (Prefettura di Massa Carrara) è citata 31 volte, quasi sempre con «estremi da
confermare su curia.europa.eu». Riscontrate: esiste, sentenza del 16 dicembre 2021, e l'oggetto è proprio il veicolo
immatricolato in un altro Stato membro messo a disposizione di un residente.

La fonte: `publications.europa.eu/resource/celex/<CELEX>` con Accept: application/xhtml+xml e Accept-Language: ita. La causa
C-NNN/AA ha il CELEX 6 + anno del ruolo + tipo + numero: «CJ» sentenza, «CO» ordinanza (Tribunale: «TJ»/«TO»). Tre risposte:
  200 + testo            → esiste: intestazione («SENTENZA DELLA CORTE (Sesta Sezione) 16 dicembre 2021») e oggetto («…»);
  404 «does not hold a content datastream» → la causa ESISTE ma non c'è il testo italiano in quel formato (cause vecchie);
  404 «Resource … not found» → non c'è quel documento (si prova l'ordinanza; se manca anche quella: da riscontrare).
Esiti: verified (+ correzione della data se quella dichiarata non torna) / unverified — mai «falsa». Rete: tetto di tempo,
cache su disco, archivio muto → nessun esito (fail-silent), come per la Cassazione.
"""
from __future__ import annotations

import datetime as _dt
import html as _html
import json
import os
import re
import sqlite3
import threading
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor

from .config import PROCESSED_DATA_PATH
from .logging_utils import get_logger

log = get_logger(__name__)

CELLAR = "http://publications.europa.eu/resource/celex/"
ENABLED = os.environ.get("CGUE_VERIFY", "1").strip().lower() not in ("0", "off", "false", "no")
TIMEOUT_S = float(os.environ.get("CGUE_TIMEOUT_S", "6"))
CACHE_DB = PROCESSED_DATA_PATH.parent / "cache" / "cgue.sqlite"
TTL_NEG_S = 24 * 3600
_down_until = 0.0
_lock = threading.Lock()

_MESI = {"gennaio": 1, "febbraio": 2, "marzo": 3, "aprile": 4, "maggio": 5, "giugno": 6, "luglio": 7, "agosto": 8,
         "settembre": 9, "ottobre": 10, "novembre": 11, "dicembre": 12}
# «C-274/20», «C‑274/20» (trattino non separabile), «causa C 274/20», «cause riunite C-717/22 e C-372/23», «T-123/19»
_CAUSA = re.compile(r"(?<![\w/])([CT])\s*[-‑–]\s*(\d{1,4})\s*/\s*(\d{2})(?![\d/])")
_DATA = re.compile(r"(\d{1,2})\s*(?:°|º)?\s+(" + "|".join(_MESI) + r")\s+((?:19|20)\d{2})|(\d{1,2})[./](\d{1,2})[./]((?:19|20)\d{2})", re.I)
_URL = re.compile(r"\]\([^)\s]*\)|https?://\S+")


def _celex(lettera: str, num: str, aa: str, tipo: str) -> str:
    anno = int(aa)
    anno = anno + (1900 if anno >= 50 else 2000)
    return f"6{anno}{('C' if lettera == 'C' else 'T')}{tipo}{int(num):04d}"


def trova(text: str) -> list[dict]:
    """Le cause citate, una per numero: {raw, lettera, numero, anno_ruolo, date: [iso], start, end}. Pura."""
    t = _URL.sub(lambda m: " " * len(m.group(0)), text or "")
    out: dict = {}
    for m in _CAUSA.finditer(t):
        k = (m.group(1), int(m.group(2)), m.group(3))
        # la data della sentenza sta accanto al numero («CGUE, 19 dicembre 2024, cause riunite C-717/22», «sentenza del 16
        # dicembre 2021 (causa C-274/20»): si prende SOLO la più vicina, e mai una data di consultazione della fonte
        base = max(0, m.start() - 70)
        zona = t[base: m.end() + 40]
        vicine = []
        for d in _DATA.finditer(zona):
            if re.search(r"consult|cons\.|accesso|visitat|aggiornat|scaric", zona[max(0, d.start() - 25): d.start()], re.I):
                continue
            try:
                if d.group(2):
                    iso = _dt.date(int(d.group(3)), _MESI[d.group(2).lower()], int(d.group(1))).isoformat()
                else:
                    iso = _dt.date(int(d.group(6)), int(d.group(5)), int(d.group(4))).isoformat()
            except Exception:  # noqa: BLE001
                continue
            dist = min(abs(base + d.start() - m.end()), abs(base + d.end() - m.start()))
            vicine.append((dist, iso))
        date = [min(vicine)[1]] if vicine else []
        v = out.setdefault(k, {"raw": re.sub(r"\s+", " ", (text or "")[m.start():m.end()]).strip(), "lettera": k[0],
                               "numero": k[1], "anno_ruolo": k[2], "date": [], "posizioni": []})
        v["date"] += [d for d in date if d not in v["date"]]
        v["posizioni"].append((m.start(), m.end()))
    # CAUSE RIUNITE: la sentenza sta sotto il PRIMO numero («cause riunite C-717/22 e C-372/23», «C-578/10–C-580/10»): per
    # CELLAR la C-372/23 da sola non esiste. Il secondo numero eredita l'esito del primo (misurato: 2 false «non trovate»)
    ordine = sorted(out.values(), key=lambda v: v["posizioni"][0][0])
    for a_, b_ in zip(ordine, ordine[1:]):
        fra = t[a_["posizioni"][0][1]: b_["posizioni"][0][0]]
        prima = t[max(0, a_["posizioni"][0][0] - 40): a_["posizioni"][0][0]]
        if len(fra) <= 12 and (re.fullmatch(r"\s*(?:[–‑-]|a|al|e|ed)\s*", fra) and re.search(r"riunit", prima + fra, re.I)
                               or re.fullmatch(r"\s*[–‑-]\s*", fra)):
            b_["riunita_con"] = f"{a_['lettera']}-{a_['numero']}/{a_['anno_ruolo']}"
            b_["_capo"] = (a_["lettera"], a_["numero"], a_["anno_ruolo"])
    return list(out.values())


def _db():
    CACHE_DB.parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(str(CACHE_DB), timeout=5)
    c.execute("CREATE TABLE IF NOT EXISTS cgue (k TEXT PRIMARY KEY, ts REAL, rec TEXT)")
    return c


def _cache_get(k: str):
    try:
        c = _db()
        try:
            r = c.execute("SELECT ts, rec FROM cgue WHERE k=?", (k,)).fetchone()
        finally:
            c.close()
        if r:
            rec = json.loads(r[1])
            if rec.get("esiste") or time.time() - r[0] < TTL_NEG_S:
                return rec
    except Exception:  # noqa: BLE001
        log.debug("cgue: cache non leggibile", exc_info=True)
    return None


def _cache_put(k: str, rec: dict) -> None:
    try:
        c = _db()
        try:
            c.execute("INSERT OR REPLACE INTO cgue (k, ts, rec) VALUES (?, ?, ?)", (k, time.time(), json.dumps(rec, ensure_ascii=False)))
            c.commit()
        finally:
            c.close()
    except Exception:  # noqa: BLE001
        log.debug("cgue: cache non scrivibile", exc_info=True)


def _get(celex: str) -> tuple[int, str]:
    req = urllib.request.Request(CELLAR + celex, headers={"User-Agent": "Mozilla/5.0 (compatible; SuperAvokati-verifica/1.0)",
                                                          "Accept": "application/xhtml+xml", "Accept-Language": "ita"})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_S) as r:
            return r.status, r.read(400_000).decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        try:
            corpo = e.read(4000).decode("utf-8", "replace")
        except Exception:  # noqa: BLE001
            corpo = ""
        return e.code, corpo


def _intestazione(xhtml: str) -> dict:
    t = _html.unescape(re.sub(r"<[^>]+>", " ", xhtml or ""))
    t = re.sub(r"\s+", " ", t)
    m = re.search(r"(SENTENZA|ORDINANZA|CONCLUSIONI)\s+(?:DELLA\s+CORTE|DEL\s+TRIBUNALE|DELL['’]AVVOCATO)[^«]{0,160}", t)
    testa = m.group(0).strip() if m else ""
    testa = re.sub(r"\(\s*\*\s*\d+\s*\)", "", testa).strip()
    d = _DATA.search(testa)
    data = ""
    if d and d.group(2):
        try:
            data = _dt.date(int(d.group(3)), _MESI[d.group(2).lower()], int(d.group(1))).isoformat()
        except Exception:  # noqa: BLE001
            data = ""
    ogg = ""
    if m:
        # l'oggetto può superare i 600 caratteri e contenere il nome della causa fra «» (C-717/22 «SISTEM LUX»): si prende
        # il PRIMO blocco dopo l'intestazione, anche lungo, e lo si taglia dopo
        mo = re.search(r"«([^»]{10,3000})»", t[m.end() - 5: m.end() + 3200])
        ogg = mo.group(1).strip() if mo else ""
    return {"intestazione": testa[:160], "data": data, "oggetto": ogg[:420]}


def _una(lettera: str, num: int, aa: str) -> dict | None:
    """Il record della causa (cache → CELLAR). None = l'archivio non ha risposto (nessun esito)."""
    global _down_until
    k = f"{lettera}-{num}/{aa}"
    rec = _cache_get(k)
    if rec is not None:
        return rec
    if time.time() < _down_until:
        return None
    rec = {"esiste": False}
    try:
        for tipo in ("J", "O"):
            celex = _celex(lettera, num, aa, tipo)
            code, corpo = _get(celex)
            if code == 200 and corpo:
                rec = {"esiste": True, "celex": celex, "tipo": "sentenza" if tipo == "J" else "ordinanza", **_intestazione(corpo)}
                break
            if code == 404 and "content datastream" in corpo:
                rec = {"esiste": True, "celex": celex, "tipo": "sentenza" if tipo == "J" else "ordinanza",
                       "intestazione": "", "data": "", "oggetto": "", "senza_testo": True}
                break
            if code not in (404,):
                raise RuntimeError(f"HTTP {code}")
    except Exception as exc:  # noqa: BLE001
        _down_until = time.time() + 300
        log.warning("cgue: archivio non raggiungibile (%s) — nessun riscontro per 5 minuti", str(exc)[:120])
        return None
    _cache_put(k, rec)
    return rec


def verifica(text: str, tetto_s: float = 8.0) -> dict:
    """{items, stats} per le cause CGUE del testo (max 8, in parallelo a 3). Mai solleva."""
    vuoto = {"items": [], "stats": {"total": 0, "verified": 0, "unverified": 0}}
    if not ENABLED:
        return vuoto
    try:
        cause = trova(text)[:8]
    except Exception:  # noqa: BLE001
        return vuoto
    if not cause:
        return vuoto
    t0 = time.time()
    with ThreadPoolExecutor(max_workers=3) as ex:
        futs = [(c, ex.submit(_una, *(c.get("_capo") or (c["lettera"], c["numero"], c["anno_ruolo"])))) for c in cause]
        items = []
        for c, f in futs:
            try:
                rec = f.result(timeout=max(0.5, tetto_s - (time.time() - t0)))
            except Exception:  # noqa: BLE001
                rec = None
            if rec is None:
                continue
            corr = []
            if rec.get("esiste") and rec.get("data") and c["date"] and rec["data"] not in c["date"]:
                d = rec["data"]
                corr.append(f"data: {d[8:10]}/{d[5:7]}/{d[:4]}, non {c['date'][0][8:10]}/{c['date'][0][5:7]}/{c['date'][0][:4]}")
            url = f"https://eur-lex.europa.eu/legal-content/IT/TXT/?uri=CELEX:{rec['celex']}" if rec.get("celex") else ""
            if c.get("riunita_con") and rec.get("esiste"):
                rec = dict(rec, riunita_con=c["riunita_con"])
            items.append({"raw": c["raw"], "court": "CGUE", "number": c["numero"], "year": c["anno_ruolo"],
                          "status": "verified" if rec.get("esiste") else "unverified", "record": dict(rec, url=url),
                          "correzioni": corr, "posizioni": c["posizioni"][:3]})
    ver = sum(1 for i in items if i["status"] == "verified")
    return {"items": items, "stats": {"total": len(items), "verified": ver, "unverified": len(items) - ver}}


def blocco(items: list[dict]) -> str:
    """Per il Giudice: le cause CGUE con l'intestazione e l'oggetto ufficiali (per vedere se reggono l'uso che se ne fa)."""
    cz = [i for i in items or [] if i.get("court") == "CGUE"]
    if not cz:
        return ""
    r = ["CORTE DI GIUSTIZIA UE — riscontro sull'archivio ufficiale dell'Ufficio delle pubblicazioni (CELLAR). CONFERMATA = la "
         "causa esiste: non marcarla «da confermare»; se l'OGGETTO ufficiale non c'entra con l'uso che ne fa la risposta, dillo."]
    for it in cz:
        rec = it.get("record") or {}
        if it["status"] == "verified":
            s = f"- CONFERMATA «{it['raw']}» → {rec.get('intestazione') or rec.get('tipo') or 'causa esistente'}"
            if rec.get("riunita_con"):
                s += f" (causa riunita: la sentenza è sotto {rec['riunita_con']})"
            if rec.get("oggetto"):
                s += f" — oggetto: «{rec['oggetto'][:300]}»"
            if rec.get("senza_testo"):
                s += " (testo italiano non disponibile in archivio: estremi non confrontabili)"
            if it.get("correzioni"):
                s += "; ESTREMI DA CORREGGERE: " + "; ".join(it["correzioni"])
            r.append(s)
        else:
            r.append(f"- NON TROVATA «{it['raw']}» → né sentenza né ordinanza con quel numero nell'archivio ufficiale: da "
                     f"riscontrare, non presentarla come certa.")
    return "\n".join(r)
