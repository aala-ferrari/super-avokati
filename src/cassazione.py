# -*- coding: utf-8 -*-
"""v9.385 — CASSAZIONE: le sentenze citate si riscontrano sull'ARCHIVIO UFFICIALE della Corte (Italgiure / SentenzeWeb).

Perché (misurato il 24 set sulle 44 risposte italiane salvate): il cervello cita la Cassazione in quasi ogni risposta
(«Cass. civ., Sez. V, ord. n. 10383/2026») e il verificatore italiano conosceva solo la Corte costituzionale → nessuna di
queste citazioni veniva riscontrata. Riscontrate a mano sull'archivio: 20 su 20 VERE (una sola data sbagliata) — ma
senior, diavolo e Giudice, non trovandole «negli archivi della verifica deterministica», le marcavano «da riscontrare»,
e in un caso hanno fatto ESPUNGERE la Cass. 10383/2026, il precedente identico al caso del cliente (auto targata Albania
dell'amministratore di una shpk: «Non la citi»). Un precedente vero buttato è un danno quanto uno inventato che passa.

La fonte è il motore di ricerca pubblico di SentenzeWeb (senza login), con tre raccolte:
  sic    i METADATI di tutti i provvedimenti civili e penali dal 2009: id = «sic» + anno + sezione + numero a 5 cifre +
         tipo + n.r.g. (sic2026510383O021202 = 2026 · Sez. 5 · n. 10383 · Ordinanza); date di udienza e di deposito,
         materia (solo civile), parti;
  snciv  il TESTO INTEGRALE civile degli ultimi ~5 anni (numdec, szdec, tipoprov, datdec, datdep, materia, ocr,
         ocrdis = il P.Q.M.);
  snpen  idem, penale.
La numerazione è PER ANNO e PER RAMO: la stessa «n. 6543/2024» esiste una volta nel civile e una nel penale. Il ramo di
un record «sic» si deduce così (misurato su 6.026 record con la verità di snciv/snpen: 6.026 su 6.026; sul 2009-2019
nessuna contraddizione con le autorità inequivocabili — Comm. trib. / Trib. libertà, GIP, Assise, Sorveglianza):
Sez. 4 / 7 / F → penale; L → civile; con materia / ricorrente / contro / intimato → civile; altrimenti penale.

⚠️ I numeri sono DENSI: quasi ogni «n. X/Y» con X sotto ~30.000 esiste, e in entrambi i rami. «Esiste» da solo dice
poco: il riscontro vero è sugli ESTREMI che la citazione dichiara — ramo, sezione, data, tipo — più la materia e (dal
2021) il dispositivo e il testo, che vanno al Giudice. Esiti, mai «falsa» («non lo trovo ≠ è falso»):
  verified    esiste nel ramo giusto e la sezione dichiarata corrisponde (date/tipo diversi → «correzioni»);
  mismatch    quel numero esiste, ma non con il ramo / la sezione dichiarati → estremi da correggere o da riscontrare;
  unverified  nessun provvedimento con quel numero in quell'anno (anno coperto) → da riscontrare.
Anno prima del 2009 o futuro → fuori copertura: la citazione NON entra negli esiti (la regola della Consulta).
Rete: UNA richiesta per risposta (tutti i numeri in OR), cache su disco, tetto di 5 s; se l'archivio non risponde non
si dice nulla (fail-silent: nessuna citazione marcata per un guasto nostro o loro).

TLS: il server non manda l'intermedio «TI Trust Technologies OV CA» (catena incompleta: curl e Python falliscono).
Verifica vera con l'intermedio pubblico incorporato qui sotto (emesso da USERTrust RSA, scade il 29/07/2029; sha256
1B:FD:87:02:…:08:63) — mai verify=False.
"""
from __future__ import annotations

import datetime as _dt
import json
import os
import re
import sqlite3
import ssl
import threading
import time
import urllib.parse
import urllib.request

from .config import PROCESSED_DATA_PATH
from .logging_utils import get_logger

log = get_logger(__name__)

SOLR = ("https://www.italgiure.giustizia.it/sncass/isapi/hc.dll/sn.solr/sn-collection/select?app.query")
PDF = "https://www.italgiure.giustizia.it/xway/application/nif/clean/hc.dll?verbo=attach&db={db}&id={fid}"
ANNO_MIN = 2009                   # primo anno dei metadati «sic» (n. 1 del 2009 depositato il 02/01/2009)
TIMEOUT_S = float(os.environ.get("CASS_TIMEOUT_S", "5"))
ENABLED = os.environ.get("CASS_VERIFY", "1").strip().lower() not in ("0", "off", "false", "no")
CACHE_DB = PROCESSED_DATA_PATH.parent / "cache" / "cassazione.sqlite"
TTL_NEG_S = 24 * 3600             # «non trovata»: si riprova dopo un giorno (pubblicazione in ritardo)
TTL_POS_S = 180 * 24 * 3600

_INTERMEDIO = """-----BEGIN CERTIFICATE-----
MIIGBjCCA+6gAwIBAgIRAN/taPn0qYs3uaR/m7ZGGIEwDQYJKoZIhvcNAQEMBQAw
gYgxCzAJBgNVBAYTAlVTMRMwEQYDVQQIEwpOZXcgSmVyc2V5MRQwEgYDVQQHEwtK
ZXJzZXkgQ2l0eTEeMBwGA1UEChMVVGhlIFVTRVJUUlVTVCBOZXR3b3JrMS4wLAYD
VQQDEyVVU0VSVHJ1c3QgUlNBIENlcnRpZmljYXRpb24gQXV0aG9yaXR5MB4XDTE5
MDczMDAwMDAwMFoXDTI5MDcyOTIzNTk1OVowezELMAkGA1UEBhMCSVQxDTALBgNV
BAgTBFJvbWExEDAOBgNVBAcTB1BvbWV6aWExJTAjBgNVBAoTHFRJIFRydXN0IFRl
Y2hub2xvZ2llcyBTLlIuTC4xJDAiBgNVBAMTG1RJIFRydXN0IFRlY2hub2xvZ2ll
cyBPViBDQTCCASIwDQYJKoZIhvcNAQEBBQADggEPADCCAQoCggEBAM/P5VGAQQhE
suVfPA7oCgVSFNi4kIytdOOxb4hqGoBtTxexnHwyT0bGwxOSuvsKhfmhSxAn0plO
nCzUoQW3AOddLODQt8IbSdKGMSniTiG522TZUoyFDeEfPn2ASeivHMlhCg7a1qEr
LBSeriiuZpfEADqSZBW6EOg54KprewjMjabY+SWqH+WObgYa5K+9tuEjfjYqf1Zt
BKXxys84GprQn0zl93PAVEZ3Yo1OF4zuF5QzSuD6l933gGebq0EX/JWmikUcQwsf
0RnlkwH+4Yq3m4uzV0BXulqEDMQuURINVDK9/0GsijMjO8j53cHEgIOgOx11SsUh
0ppkQpRXo6cCAwEAAaOCAXUwggFxMB8GA1UdIwQYMBaAFFN5v1qqK0rPVIDh2JvA
nfKyA2bLMB0GA1UdDgQWBBRj5T/4zyexMRkqK1zN/y5x+yk43zAOBgNVHQ8BAf8E
BAMCAYYwEgYDVR0TAQH/BAgwBgEB/wIBADAdBgNVHSUEFjAUBggrBgEFBQcDAQYI
KwYBBQUHAwIwIgYDVR0gBBswGTANBgsrBgEEAbIxAQICSTAIBgZngQwBAgIwUAYD
VR0fBEkwRzBFoEOgQYY/aHR0cDovL2NybC51c2VydHJ1c3QuY29tL1VTRVJUcnVz
dFJTQUNlcnRpZmljYXRpb25BdXRob3JpdHkuY3JsMHYGCCsGAQUFBwEBBGowaDA/
BggrBgEFBQcwAoYzaHR0cDovL2NydC51c2VydHJ1c3QuY29tL1VTRVJUcnVzdFJT
QUFkZFRydXN0Q0EuY3J0MCUGCCsGAQUFBzABhhlodHRwOi8vb2NzcC51c2VydHJ1
c3QuY29tMA0GCSqGSIb3DQEBDAUAA4ICAQBHwDEaXKg/u+srk31kfi1GJOYs3fQD
QTT1FIj0IQ02M9zbmNipVMhamFYfH0RoD5/v4tc0Eyg81zMbmWpgn5R+ixXpAvjL
WYzzSeE/pAlf1BuVNPXjnNNCf6tl6Ik6MsW5jGrJ7ivyUbiBQqWce0+gJfnzgEUT
1j4APOwuolLtqEKzqz099vqwuhJA5JYQEtSPaBEoRSlNS6kSraar9BaL6oSqhPrV
mQSIx962dqJCxbm8Bk5tN9NzH93np4YJuIuGE2mx7K44lqdXYERWdm8EpFzo9Nak
cq5MsVs1yiLdRdaZAiMSOvxpOECxxcuh/Pno0VYG2GRpQcgm3Fwi30O2OzLJ7eOI
cQBItHxOo3JCu1cNfy8X36SFP8prZPXTqHSRI09Z9nMDzB0KF2iTHsG+doTUvCIj
rTcwLehnYCeivpFiHvWmCiue451NeWf43PFH8mWwSdvhSJI6KMsO2AmoiqQh3VBv
WNIrGWIrzvBNCWrDp8DBY7wq8CgNU56mKCjT0Es17AA7mlcc0qL7zaib0DMJodiD
rarDI5LTPf8ifIU+kkWKEAuSxiBnnXvRmdw/X9G7KuHJ/43G3Lpu55srP6jsKA2m
0fRZDZkytVB5a2yijWm76QDk1+ZP8n1rYVKqivlYZM6vwVVVp3E67vB42PeiNwnh
n6nkJcD6enyN6Q==
-----END CERTIFICATE-----
"""

# ══════════════════════════════════════════════════════════════════════════════════════════════════════════
# 1. LEGGERE LE CITAZIONI (come le scrive davvero il cervello: 306 forme lette sulle risposte salvate)
# ══════════════════════════════════════════════════════════════════════════════════════════════════════════
#   Cass. civ., Sez. V, ord. n. 10383/2026            Cass., Sez. Un., 4 luglio 2024, n. 18286
#   Cass. civ., Sez. VI-3, ord. 5 gennaio 2023, n. 194 Cass. civ., Sez. Lav., ord. n. 28927 dell'11 novembre 2024
#   Cass. SS.UU. nn. 18284 e 18286 del 4 luglio 2024   Cass. n. 194/2023 e n. 16160/2024      Cass. 6221/2025
#   Cass. pen., Sez. III, sent. 29 luglio 2026, n. 28668                                      SS.UU. 141/2006
#   Cass. civ., Sez. I, n. 27928/2025 (dep. 20 ottobre 2025)   Cass., Sez. Un., ord. 4 luglio 2024, r.o. n. 167/2024 (✗)
_MESI = {"gennaio": 1, "febbraio": 2, "marzo": 3, "aprile": 4, "maggio": 5, "giugno": 6, "luglio": 7, "agosto": 8,
         "settembre": 9, "ottobre": 10, "novembre": 11, "dicembre": 12}
_DATA_RX = (r"(\d{1,2})\s*(?:°|º)?\s*(?:(" + "|".join(_MESI) + r")\s+|[./-]\s*(\d{1,2})\s*[./-]\s*)((?:19|20)\d{2})")

_ANCORA = re.compile(
    r"(?<![\w/.\-])(?:Cass(?:azione)?\b\.?|Corte\s+(?:[Ss]uprema\s+)?di\s+[Cc]assazione\b|SS\.\s?UU\.|"
    r"S\.\s?U\.(?!\s?[A-Z]\.)|[Ss]ez(?:ioni\s+|\.\s*)[Uu]n(?:ite\b|\.))")
_SEP = re.compile(r"[\s,]*")
_C_RAMO = re.compile(r"(civ(?:ile|ili)?|pen(?:ale|ali)?)\b\.?", re.I)
_C_SU = re.compile(r"(?:SS\.\s?UU\.|S\.\s?U\.(?!\s?[A-Z]\.)|SU\b|[Ss]ez(?:ioni\s+|\.\s*)[Uu]n(?:ite\b|\.)|[Ss]ezioni\s+[Uu]nite\b)"
                   r"(?:\s*(civ(?:ili|ile)?|pen(?:ali|ale)?)\b\.?)?")
_C_SEZ = re.compile(
    r"[Ss]ez(?:ione\b|\.)?\s*(lav(?:oro\b|\.)|L\b|trib(?:utaria\b|\.)|T\b|fer(?:iale\b|\.)|F\b|"
    r"(?:VI|6)\s*[-–]\s*(?:[1-5]|L|T|lav\.?|trib\.?)(?![\w])|[IVX]{1,4}\b|[1-7]\b|prima\b|seconda\b|terza\b|quarta\b|"
    r"quinta\b|sesta\b|settima\b)(?:\s*\((?:civile|penale|tributaria|lavoro|trib\.?|lav\.?)\))?", re.I)
_C_TIPO = re.compile(r"(ord(?:inanza|\.)?\s*interloc(?:utoria\b|\.)|ord(?:inanza\b|\.)|sent(?:enza\b|\.)|decr(?:eto\b|\.))", re.I)
_C_DATA = re.compile(r"(?:(dep(?:\.|osit(?:ata|o)\b)(?:\s*il)?|cam\.?\s*cons\.?|ud(?:ienza\b|\.)|del(?:l['’]|\b)|in\s+data)\s*)?"
                     + _DATA_RX, re.I)
_C_NUM = re.compile(r"(nn?\.|n\.ro\b|numero\b)?\s*(\d{1,6})(?:\s*/\s*((?:19|20)\d{2}))?(?![\d/])")
_C_ALTRI = re.compile(r"\s*(?:,|\be\b|\bed\b|\bnonché\b)\s*(?:(?:ord\.|sent\.|ordinanza|sentenza)\s*)?(nn?\.)?\s*(\d{1,6})"
                      r"(?:\s*/\s*((?:19|20)\d{2}))?(?![\d/])")
_C_ANNO = re.compile(r"del(?:l['’]|\b)\s*((?:19|20)\d{2})\b(?!\s*[./-]\d)")
_C_PAREN = re.compile(r"\s*\(([^()]{0,90})\)")
_C_DEP_ANNO = re.compile(r"dep\.?\s*((?:19|20)\d{2})\b")
# «le Sezioni Unite, con la sentenza n. …» / «nell'ordinanza n. …»: parole di raccordo prima del tipo
_C_RACCORDO = re.compile(r"(?:con|nella|nell['’]|colla|mediante|in)\s+(?:la\s+|l['’]\s*)?(?=(?:sent|ord|decr))", re.I)
# una parentesi che parla della CONSULTAZIONE della fonte non porta la data del provvedimento
_PAREN_DATA = re.compile(r"\s*(dep(?:\.|osit(?:ata|o)\b)(?:\s*il)?|cam\.?\s*cons\.?|ud(?:ienza\b|\.)|decisa(?:\s+il)?|del(?:l['’]|\b))?\s*"
                         + _DATA_RX, re.I)
_PAREN_NON_DATA = re.compile(r"consult|accesso|visitat|reperit|fonte|\blett[oa]\b|(?<!cam\.\s)(?<!cam\.)\bcons\.\s*\d", re.I)
_ROM = {"I": "1", "II": "2", "III": "3", "IV": "4", "V": "5", "VI": "6", "VII": "7"}
_ORD = {"prima": "1", "seconda": "2", "terza": "3", "quarta": "4", "quinta": "5", "sesta": "6", "settima": "7"}
_URL = re.compile(r"\]\([^)\s]*\)|https?://\S+")
_PEN_CUE = re.compile(r"\b(?:reat[oi]|imputat[oi]|c\.p\.p\.|codice\s+penale|dibattimento|querela|indagat[oi]|pubblico\s+ministero|"
                      r"procura\s+della\s+repubblica|custodia\s+cautelare|condanna\s+penale)\b", re.I)
_CIV_CUE = re.compile(r"\b(?:c\.c\.|c\.p\.c\.|codice\s+civile|risarciment\w+|contratt\w+|locazion\w+|lavorator\w+|licenziament\w+|"
                      r"tribut\w+|doganal\w+|sanzion\w+\s+amministrativ\w+|condomin\w+|separazione|divorzio|ricorrente)\b", re.I)


def _norm_sez(s: str) -> str:
    s = (s or "").strip().rstrip(".").strip()
    low = s.lower()
    if low.startswith("lav") or s == "L":
        return "L"
    if low.startswith("trib") or s == "T":
        return "5"
    if low.startswith("fer") or s == "F":
        return "F"
    m = re.match(r"(?:VI|6)\s*[-–]", s, re.I)
    if m:
        return "6"
    if low in _ORD:
        return _ORD[low]
    if s.upper() in _ROM:
        return _ROM[s.upper()]
    return s if s in "1234567" else ""


def _data(m: re.Match, off: int = 0) -> str | None:
    """ISO da un match di _DATA_RX (gruppi a partire da off+1: giorno, mese-parola, mese-numero, anno)."""
    try:
        g = m.groups()[off:off + 4]
        mese = _MESI[g[1].lower()] if g[1] else int(g[2])
        return _dt.date(int(g[3]), mese, int(g[0])).isoformat()
    except Exception:  # noqa: BLE001
        return None


def _pulito(text: str) -> str:
    """Stessa lunghezza del testo (gli offset restano validi): via i link, via enfasi e virgolette del markdown."""
    t = _URL.sub(lambda m: " " * len(m.group(0)), text or "")
    return re.sub(r"[*_`«»“”\"]", " ", t)


def trova(text: str) -> list[dict]:
    """Le citazioni di Cassazione del testo, una per numero (le liste «nn. 18284 e 18286» ne danno due).

    Ogni voce: raw, start, end, numero, anno, anno_da_data (l'anno viene da una data, non da «/AAAA»), ramo
    (civ|pen|None), sezione ("U", "1"…"7", "L", "F" o ""), tipo (S|O|I|D|""), date [(iso, tipo: dep|dec|?)].
    Pura: nessuna rete."""
    t = _pulito(text)
    out: list[dict] = []
    fine_prec = -1
    for a in _ANCORA.finditer(t):
        if a.start() < fine_prec:
            continue
        st: dict = {"ramo": None, "sezione": "", "tipo": "", "date": []}
        tok = a.group(0)
        if re.match(r"SS\.|S\.\s?U\.|[Ss]ez", tok):
            st["sezione"] = "U"
        p = a.end()
        numeri: list[tuple] = []
        for _giro in range(12):
            q = _SEP.match(t, p).end()
            m = _C_RAMO.match(t, q)
            if m and not numeri:
                st["ramo"] = "civ" if m.group(1).lower().startswith("civ") else "pen"
                p = m.end(); continue
            m = _C_SU.match(t, q)
            if m and not numeri:
                st["sezione"] = "U"
                if m.group(1):
                    st["ramo"] = "civ" if m.group(1).lower().startswith("civ") else "pen"
                p = m.end(); continue
            m = _C_SEZ.match(t, q)
            if m and not numeri:
                sz = _norm_sez(m.group(1))
                if sz:
                    st["sezione"] = sz
                    # solo il civile ha la Lavoro, la tributaria e le sottosezioni della sesta (VI-3, 6-L…);
                    # solo il penale ha la quarta, la settima e la feriale (misurato: 0 civili su 2.926 della Sez. 4)
                    if sz == "L" or re.match(r"(?:VI|6)\s*[-–]|trib|T\b", m.group(1), re.I):
                        st["ramo"] = st["ramo"] or "civ"
                    elif sz in ("4", "7", "F"):
                        st["ramo"] = st["ramo"] or "pen"
                p = m.end(); continue
            m = _C_RACCORDO.match(t, q)
            if m and not numeri:
                p = m.end(); continue
            m = _C_TIPO.match(t, q)
            if m and not numeri:        # dopo il numero «, ordinanza del Tribunale…» non è più la citazione
                w = m.group(1).lower()
                st["tipo"] = "I" if "interloc" in w else ("O" if w.startswith("ord") else ("S" if w.startswith("sent") else "D"))
                p = m.end(); continue
            m = _C_DATA.match(t, q)
            if m and m.group(2):
                iso = _data(m, 1)
                if iso:
                    k = (m.group(1) or "").lower()
                    st["date"].append((iso, "dep" if k.startswith("dep") else ("dec" if k.startswith(("cam", "ud")) else "?")))
                p = m.end(); continue
            m = _C_NUM.match(t, q)
            if m and not numeri and (m.group(1) or m.group(3)):
                n = int(m.group(2))
                if not 0 < n < 70000:
                    break
                numeri.append((n, int(m.group(3)) if m.group(3) else None, q, m.end()))
                p = m.end()
                while True:
                    m2 = _C_ALTRI.match(t, p)
                    if not m2 or not (m2.group(1) or m2.group(3) or (m.group(1) or "").lower() == "nn."):
                        break
                    n2 = int(m2.group(2))
                    if not 0 < n2 < 70000:
                        break
                    numeri.append((n2, int(m2.group(3)) if m2.group(3) else None, q, m2.end()))
                    p = m2.end()
                continue
            if numeri:
                m = _C_ANNO.match(t, q)
                if m:
                    numeri = [(n, y or int(m.group(1)), s0, e0) for n, y, s0, e0 in numeri]
                    p = m.end(); continue
                m = _C_PAREN.match(t, p)
                if m and not _PAREN_NON_DATA.search(m.group(1)):
                    dentro = m.group(1)
                    # la data vale solo IN TESTA alla parentesi («(24 luglio 2009)», «(dep. 20 ottobre 2025)»,
                    # «(cam. cons. 25 febbraio 2026; …)»): «(yacht …, su ordinanza del Tribunale 24 febbraio 2026)» no
                    md = _C_DEP_ANNO.match(dentro.strip())
                    mm = _PAREN_DATA.match(dentro)
                    if md and not mm:
                        numeri = [(n, y or int(md.group(1)), s0, e0) for n, y, s0, e0 in numeri]
                    if mm:
                        iso = _data(mm, 1)
                        if iso:
                            pre = (mm.group(1) or "").lower()
                            st["date"].append((iso, "dep" if "dep" in pre else ("dec" if ("cam" in pre or "ud" in pre) else "?")))
                    if md or mm:
                        p = m.end(); continue
            break
        if not numeri:
            continue
        fine_prec = p
        raw = re.sub(r"\s+", " ", (text or "")[a.start():p]).strip(" ,;")
        for n, y, s0, e0 in numeri:
            anno, da_data = y, False
            if anno is None and st["date"]:
                anno, da_data = int(st["date"][0][0][:4]), True
            if anno is None:
                continue
            out.append({"raw": raw[:140], "start": a.start(), "end": p, "numero": n, "anno": anno, "anno_da_data": da_data,
                        "ramo": st["ramo"], "sezione": st["sezione"], "tipo": st["tipo"], "date": list(st["date"])})
    return out


# ══════════════════════════════════════════════════════════════════════════════════════════════════════════
# 2. L'ARCHIVIO: una richiesta per tutti i numeri, cache, e il ramo di ogni record
# ══════════════════════════════════════════════════════════════════════════════════════════════════════════
_ctx_lock = threading.Lock()
_ctx: ssl.SSLContext | None = None
_net_sem = threading.Semaphore(2)
_down_until = 0.0
_mem: dict = {}
_mem_lock = threading.Lock()
_FL = ("id,kind,szdec,tipoprov,datdec,datdep,materia,filename,ocrdis,sic-materia,sic-data_ud,sic-datdep,sic-ricorrente,"
       "sic-contro,sic-intimato,sic-altro,sic-autorita,sic-localita")


def _ssl_ctx() -> ssl.SSLContext:
    global _ctx
    with _ctx_lock:
        if _ctx is None:
            c = ssl.create_default_context()
            c.load_verify_locations(cadata=_INTERMEDIO)
            _ctx = c
        return _ctx


def _solr(params: dict, timeout: float = TIMEOUT_S) -> dict:
    body = urllib.parse.urlencode(dict({"wt": "json", "start": 0}, **params), doseq=True).encode()
    req = urllib.request.Request(SOLR, data=body, headers={
        "User-Agent": "Mozilla/5.0 (compatible; SuperAvokati-verifica/1.0)",
        "Referer": "https://www.italgiure.giustizia.it/sncass/",
        "Content-Type": "application/x-www-form-urlencoded"})
    with _net_sem:
        with urllib.request.urlopen(req, context=_ssl_ctx(), timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8", "replace"))


def _db():
    CACHE_DB.parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(str(CACHE_DB), timeout=5)
    c.execute("CREATE TABLE IF NOT EXISTS cass (k TEXT PRIMARY KEY, ts REAL, recs TEXT)")
    return c


def _cache_get(keys: list[str]) -> dict:
    now, out = time.time(), {}
    with _mem_lock:
        for k in keys:
            v = _mem.get(k)
            if v and now - v[0] < (TTL_POS_S if v[1] else TTL_NEG_S):
                out[k] = v[1]
    manca = [k for k in keys if k not in out]
    if manca:
        try:
            c = _db()
            try:
                for k, ts, recs in c.execute("SELECT k, ts, recs FROM cass WHERE k IN (%s)" % ",".join("?" * len(manca)), manca):
                    r = json.loads(recs)
                    if now - ts < (TTL_POS_S if r else TTL_NEG_S):
                        out[k] = r
                        with _mem_lock:
                            _mem[k] = (ts, r)
            finally:
                c.close()
        except Exception:  # noqa: BLE001
            log.debug("cassazione: cache su disco non leggibile", exc_info=True)
    return out


def _cache_put(vals: dict) -> None:
    now = time.time()
    with _mem_lock:
        for k, r in vals.items():
            _mem[k] = (now, r)
        if len(_mem) > 5000:
            for k in sorted(_mem, key=lambda x: _mem[x][0])[:1000]:
                _mem.pop(k, None)
    try:
        c = _db()
        try:
            c.executemany("INSERT OR REPLACE INTO cass (k, ts, recs) VALUES (?, ?, ?)",
                          [(k, now, json.dumps(r, ensure_ascii=False)) for k, r in vals.items()])
            c.commit()
        finally:
            c.close()
    except Exception:  # noqa: BLE001
        log.debug("cassazione: cache su disco non scrivibile", exc_info=True)


def _iso8(s) -> str:
    s = (s[0] if isinstance(s, list) and s else s) or ""
    s = str(s)
    m = re.match(r"^(\d{4})(\d{2})(\d{2})$", s)
    if m:
        return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
    m = re.match(r"^(\d{2})/(\d{2})/(\d{4})$", s)
    if m:
        return f"{m.group(3)}-{m.group(2)}-{m.group(1)}"
    return ""


def _ramo_sic(d: dict, sez: str) -> str:
    if sez in ("4", "7", "F"):
        return "pen"
    if sez == "L":
        return "civ"
    if d.get("sic-materia") or d.get("sic-ricorrente") or d.get("sic-contro") or d.get("sic-intimato"):
        return "civ"
    return "pen"


_ESITI = [
    (r"rimett\w*\b.{0,80}\bsezioni\s+unite|rimett\w*\b.{0,60}\bprimo\s+presidente", "rimessione alle Sezioni Unite"),
    (r"non\s+manifestamente\s+infondat", "questione di legittimità costituzionale sollevata"),
    (r"267\s*,?\s*(?:par\.|paragrafo)?\s*3?\s*,?\s*TFUE|corte\s+di\s+giustizia\s+dell['’]\s*unione\s+europea\s+di\s+pronunciarsi|"
     r"rinvio\s+pregiudiziale", "rinvio pregiudiziale alla Corte di giustizia UE"),
    (r"dichiara\s+inammissibil|inammissibil\w*\s+i\s+ricors|inammissibil\w*\s+il\s+ricors", "ricorso inammissibile"),
    (r"annulla\s+senza\s+rinvio", "annulla senza rinvio"),
    (r"annulla\b.{0,120}\bcon\s+rinvio|annulla\b.{0,80}\brinvia", "annulla con rinvio"),
    (r"cassa\b.{0,60}\bsenza\s+rinvio", "cassa senza rinvio"),
    (r"accoglie|cassa\b.{0,160}\brinvia", "accoglie (cassa con rinvio)"),
    (r"rigetta", "rigetta il ricorso"),
    (r"dichiara\s+(?:l['’]\s*)?estint|estinzione\s+del\s+giudizio", "estinzione del giudizio"),
    (r"dichiara\s+la\s+giurisdizione|regola\w*\s+la\s+giurisdizione", "regolamento di giurisdizione"),
    (r"dichiara\s+la\s+competenza", "regolamento di competenza"),
]


def _esito(pqm: str) -> str:
    t = re.sub(r"\s+", " ", pqm or "")
    m = re.search(r"P\.?\s*Q\.?\s*M\.?", t)
    t = t[m.end():] if m else t
    t = t[:600]
    for rx, lab in _ESITI:
        if re.search(rx, t, re.I):
            return lab
    return ""


def _record(d: dict) -> dict | None:
    """Un documento dell'archivio → record uniforme; None se l'id non ha la forma attesa."""
    i = d.get("id") or ""
    kind = d.get("kind") or ""
    if kind == "sic":
        m = re.match(r"^sic(\d{4})([0-9A-Z])(\d{5})([A-Z])(\d*)$", i)
        if not m:
            return None
        sez = m.group(2)
        return {"anno": int(m.group(1)), "sezione": sez, "numero": int(m.group(3)), "tipo": m.group(4),
                "ramo": _ramo_sic(d, sez), "datdep": _iso8(d.get("sic-datdep") or d.get("datdep")),
                "datdec": _iso8(d.get("sic-data_ud")), "materia": ((d.get("sic-materia") or [""])[0] or "").strip(" *"),
                "autorita": ((d.get("sic-autorita") or [""])[0] or "").strip(), "fonte": "sic"}
    if kind in ("snciv", "snpen"):
        m = re.match(r"^(?:snciv|snpen)(\d{4})([0-9A-Z])(\d{5})([A-Z])$", i)
        if not m:
            return None
        fn = (d.get("filename") or [""])[0] or ""
        url = ""
        if fn:
            fid = fn if ".clean." in fn else fn.replace(".pdf", ".clean.pdf")
            url = PDF.format(db=kind, fid=urllib.parse.quote(fid, safe="./@"))
        return {"anno": int(m.group(1)), "sezione": m.group(2), "numero": int(m.group(3)), "tipo": m.group(4),
                "ramo": "civ" if kind == "snciv" else "pen", "datdep": _iso8(d.get("datdep")), "datdec": _iso8(d.get("datdec")),
                "materia": ((d.get("materia") or [""])[0] or "").strip(" *"), "esito": _esito((d.get("ocrdis") or [""])[0]),
                "sn_id": i, "url": url, "fonte": kind}
    return None


def _unisci(recs: list[dict]) -> list[dict]:
    """Un provvedimento = (ramo, sezione, numero, tipo): i ricorsi riuniti danno più righe «sic», il testo integrale una."""
    per: dict = {}
    for r in recs:
        k = (r["ramo"], r["sezione"], r["numero"], r["tipo"])
        v = per.setdefault(k, {"ramo": r["ramo"], "sezione": r["sezione"], "numero": r["numero"], "tipo": r["tipo"], "anno": r["anno"]})
        for f in ("datdep", "datdec", "materia", "esito", "sn_id", "url", "autorita"):
            if r.get(f) and not v.get(f):
                v[f] = r[f]
    return list(per.values())


def cerca(coppie: list[tuple[int, int]]) -> tuple[dict, bool]:
    """({(numero, anno): [record…]}, offline). Le coppie che l'archivio non ha potuto dire MANCANO dal dizionario
    (fail-silent: nessun esito per loro); una lista vuota vuol dire «l'archivio ha risposto: non c'è»."""
    global _down_until
    oggi = _dt.date.today().year
    coppie = sorted({(int(n), int(y)) for n, y in coppie if ANNO_MIN <= int(y) <= oggi and 0 < int(n) < 70000})
    if not coppie:
        return {}, False
    keys = {f"{n}/{y}": (n, y) for n, y in coppie}
    got = _cache_get(list(keys))
    manca = [k for k in keys if k not in got]
    offline = False
    if manca and time.time() < _down_until:
        offline = True
    elif manca:
        nuovi: dict = {}
        try:
            for i in range(0, len(manca), 12):
                parte = manca[i:i + 12]
                q = " OR ".join(f"id:{kind}{keys[k][1]}?{keys[k][0]:05d}*" for k in parte for kind in ("sic", "snciv", "snpen"))
                d = _solr({"q": q, "rows": 40 * len(parte), "fl": _FL})
                trovati = {k: [] for k in parte}
                for doc in (d.get("response") or {}).get("docs") or []:
                    r = _record(doc)
                    if r:
                        k = f"{r['numero']}/{r['anno']}"
                        if k in trovati:
                            trovati[k].append(r)
                nuovi.update({k: _unisci(v) for k, v in trovati.items()})
        except Exception as exc:  # noqa: BLE001
            _down_until = time.time() + 300
            offline = True
            log.warning("cassazione: archivio non raggiungibile (%s) — nessun riscontro per 5 minuti", str(exc)[:120])
        if nuovi:
            _cache_put(nuovi)
            got.update(nuovi)
    return {keys[k]: v for k, v in got.items()}, offline


# ══════════════════════════════════════════════════════════════════════════════════════════════════════════
# 3. IL CONFRONTO fra ciò che la citazione dichiara e ciò che l'archivio dice
# ══════════════════════════════════════════════════════════════════════════════════════════════════════════
_TIPO_IT = {"S": "sentenza", "O": "ordinanza", "I": "ordinanza interlocutoria", "D": "decreto"}
_ROM_INV = {v: k for k, v in _ROM.items()}


def sezione_label(sez: str, ramo: str) -> str:
    base = {"U": "Sezioni Unite", "L": "Sez. Lavoro", "F": "Sez. feriale"}.get(sez) or f"Sez. {_ROM_INV.get(sez, sez)}"
    return f"{base} {'civile' if ramo == 'civ' else 'penale'}" if ramo else base


def _gma(iso: str) -> str:
    return f"{iso[8:10]}/{iso[5:7]}/{iso[:4]}" if iso and len(iso) == 10 else ""


def descrivi(r: dict) -> str:
    """«Cass. civ., Sez. V, ordinanza n. 10383/2026, dep. 20/04/2026 (decisa 25/02/2026) — Tributi e dazi doganali»."""
    s = (f"Cass. {'civ.' if r['ramo'] == 'civ' else 'pen.'}, {sezione_label(r['sezione'], '')}, "
         f"{_TIPO_IT.get(r['tipo'], 'provvedimento')} n. {r['numero']}/{r['anno']}")
    if r.get("datdep"):
        s += f", dep. {_gma(r['datdep'])}"
    if r.get("datdec"):
        s += f" (decisa {_gma(r['datdec'])})"
    if r.get("materia"):
        s += f" — {r['materia'].capitalize()}"
    return s


def _ramo_testo(text: str) -> str:
    p, c = len(_PEN_CUE.findall(text or "")), len(_CIV_CUE.findall(text or ""))
    return "pen" if p > 1.5 * c and p >= 2 else "civ"


def valuta(menzioni: list[dict], recs: list[dict], ramo_testo: str = "civ") -> dict:
    """Esito per un numero/anno a partire da tutte le sue menzioni nel testo (la stessa decisione citata più volte:
    «Cass. civ., Sez. V, n. 15208/2024» e poi «Cass. 15208/2024» — gli estremi dichiarati si sommano)."""
    ramo = next((m["ramo"] for m in menzioni if m.get("ramo")), None)
    sezioni = {m["sezione"] for m in menzioni if m.get("sezione")}
    tipi = {m["tipo"] for m in menzioni if m.get("tipo")}
    date = [d for m in menzioni for d in m.get("date") or []]
    dedotto = False
    if not recs:
        return {"status": "unverified", "ramo": ramo, "record": None, "correzioni": [], "alternative": []}
    if ramo is None:
        rami = {r["ramo"] for r in recs}
        if sezioni & {"L"}:
            ramo = "civ"
        elif sezioni & {"4", "7", "F"}:
            ramo = "pen"
        elif len(rami) == 1:
            ramo = next(iter(rami))
        else:
            ramo, dedotto = ramo_testo, True
    cand = [r for r in recs if r["ramo"] == ramo]
    altre = [r for r in recs if r["ramo"] != ramo]
    if not cand:
        return {"status": "mismatch", "ramo": ramo, "record": None, "correzioni": [], "dedotto": dedotto,
                "motivo": "ramo", "alternative": [descrivi(r) for r in altre[:3]]}
    corr_sez = ""
    if sezioni:
        ok = [r for r in cand if r["sezione"] in sezioni]
        if not ok:
            if dedotto:
                ok2 = [r for r in altre if r["sezione"] in sezioni]
                if ok2:                                  # il ramo era solo dedotto: la sezione decide
                    cand, altre, ramo = ok2, cand, ok2[0]["ramo"]
                    ok = ok2
            if not ok and date:
                # la DATA dichiarata coincide: è lo stesso provvedimento con la sezione sbagliata (tipico: un'ordinanza
                # della «sesta-3» citata «Sez. III» — prova viva del 24 set, Cass. 3882/2015) → correzione, non «togli»
                per_data = [r for r in cand if any(_data_ok(d, k, r) for d, k in date)]
                if per_data:
                    ok = per_data
                    corr_sez = (f"sezione: {sezione_label(per_data[0]['sezione'], '')}, non "
                                + ", ".join(sezione_label(x, "") for x in sorted(sezioni)))
            if not ok:
                # ramo dichiarato («Cass. civ.») → si mostrano solo i provvedimenti di quel ramo: il penale con lo
                # stesso numero è un'altra serie e non aiuta a correggere
                return {"status": "mismatch", "ramo": ramo, "record": cand[0], "correzioni": [], "dedotto": dedotto,
                        "motivo": "sezione", "dichiarata": sorted(sezioni),
                        "alternative": [descrivi(r) for r in ((cand + altre) if dedotto else cand)[:3]]}
        cand = ok
    best = sorted(cand, key=lambda r: (not _date_ok(date, r), not r.get("sn_id"), r["tipo"] != "S"))[0]
    corr = [corr_sez] if corr_sez else []
    sbagliate = [d for d, k in date if not _data_ok(d, k, best)]
    if sbagliate and (best.get("datdep") or best.get("datdec")):
        corr.append(f"data: depositata il {_gma(best.get('datdep') or '')}"
                    + (f" (decisa il {_gma(best['datdec'])})" if best.get("datdec") else "")
                    + f", non il {_gma(sbagliate[0])}")
    if tipi:
        t = best["tipo"]
        compat = {"S": {"S"}, "O": {"O", "I"}, "I": {"I", "O"}, "D": {"D"}}
        if not any(t in compat.get(x, {x}) for x in tipi):
            dich = _TIPO_IT.get(sorted(tipi)[0], "")
            corr.append(f"tipo: {_TIPO_IT.get(t, t)}" + (f", non {dich}" if dich else ""))
    return {"status": "verified", "ramo": ramo, "record": best, "correzioni": corr, "dedotto": dedotto,
            "alternative": [descrivi(r) for r in altre[:2]] if dedotto else []}


def _data_ok(d: str, k: str, r: dict) -> bool:
    """«dep.» si confronta col deposito, «cam. cons.»/«ud.» con la decisione; una data senza etichetta con l'una o l'altra
    (il civile cita di solito il deposito, il penale l'udienza)."""
    if k == "dep":
        return d == r.get("datdep")
    if k == "dec":
        return d == r.get("datdec")
    return d in (r.get("datdep"), r.get("datdec"))


def _date_ok(date: list, r: dict) -> bool:
    return bool(date) and all(_data_ok(d, k, r) for d, k in date)


def verifica(text: str) -> dict:
    """{items, stats} per le citazioni di Cassazione del testo. Mai solleva; archivio giù → quelle non dette mancano."""
    vuoto = {"items": [], "stats": {"total": 0, "verified": 0, "unverified": 0, "mismatch": 0}}
    if not ENABLED:
        return vuoto
    try:
        cit = trova(text)
    except Exception:  # noqa: BLE001
        log.debug("cassazione: lettura citazioni fallita", exc_info=True)
        return vuoto
    anno_oggi = _dt.date.today().year
    per: dict = {}
    for c in cit:
        if ANNO_MIN <= c["anno"] <= anno_oggi:
            per.setdefault((c["numero"], c["anno"]), []).append(c)
    if not per:
        return vuoto
    # l'anno preso da una data di UDIENZA può essere quello prima del deposito (dicembre → gennaio): si prova anche +1,
    # e vince l'anno il cui provvedimento ha QUELLA data (i numeri sono densi: nell'anno sbagliato ne esiste un altro)
    extra = [(n, y + 1) for (n, y), ms in per.items() if all(m["anno_da_data"] for m in ms) and y + 1 <= anno_oggi]
    try:
        trovati, offline = cerca(list(per) + extra)
    except Exception:  # noqa: BLE001
        log.debug("cassazione: ricerca fallita", exc_info=True)
        trovati, offline = {}, True
    ramo_t = _ramo_testo(text)
    items = []
    for (n, y), ms in per.items():
        recs = trovati.get((n, y))
        if all(m["anno_da_data"] for m in ms) and trovati.get((n, y + 1)):
            date = [d for m in ms for d in m.get("date") or []]
            if not any(_date_ok(date, r) for r in recs or []) and any(_date_ok(date, r) for r in trovati[(n, y + 1)]):
                recs, y = trovati[(n, y + 1)], y + 1
        if recs is None:
            continue                                  # l'archivio non l'ha potuta dire: nessun esito
        v = valuta(ms, recs, ramo_t)
        items.append({"raw": ms[0]["raw"], "court": "Cass", "number": n, "year": y, "status": v["status"],
                      "ramo": v.get("ramo"), "ramo_dedotto": bool(v.get("dedotto")), "record": v.get("record"),
                      "correzioni": v.get("correzioni") or [], "alternative": v.get("alternative") or [],
                      "motivo": v.get("motivo"), "dichiarata": v.get("dichiarata"),
                      "posizioni": [(m["start"], m["end"]) for m in ms][:4]})
    st = {"total": len(items), "verified": sum(1 for i in items if i["status"] == "verified"),
          "mismatch": sum(1 for i in items if i["status"] == "mismatch")}
    st["unverified"] = st["total"] - st["verified"]
    if offline:
        st["offline"] = True
    return {"items": items, "stats": st}


# ══════════════════════════════════════════════════════════════════════════════════════════════════════════
# 4. PER IL GIUDICE: il passo del testo più vicino all'uso che la risposta ne fa (solo dal 2021: testo integrale)
# ══════════════════════════════════════════════════════════════════════════════════════════════════════════
_STOP = set("della delle degli dello dalla dalle dagli nella nelle negli sulla sulle sugli come anche quando questo questa "
            "quello quella sono essere stato stata ogni altro altra loro dove cosa fatto fatti ancora sempre prima dopo "
            "tutto tutti tutte perché mentre però quindi infatti invece senza verso entro oltre circa presso".split())
_est_cache: dict = {}


def _termini(text: str, pos: tuple[int, int]) -> list[str]:
    s, e = pos
    zona = (text or "")[max(0, s - 160): e + 320]
    zona = _URL.sub(" ", zona)
    parole = [w.lower() for w in re.findall(r"[A-Za-zÀ-ÿ]{5,}", zona)]
    fuori = {"cass", "cassazione", "sezione", "sezioni", "unite", "civile", "penale", "ordinanza", "sentenza", "gennaio",
             "febbraio", "marzo", "aprile", "maggio", "giugno", "luglio", "agosto", "settembre", "ottobre", "novembre",
             "dicembre", "riscontrare", "verificare", "italgiure", "fonte", "secondaria", "estremi", "lexced"}
    out = []
    for w in parole:
        if w in _STOP or w in fuori or w in out:
            continue
        out.append(w)
    return out[:14]


_INTESTAZIONE_PAGINA = re.compile(r"Numero\s+registro\s+generale\s+\d+/\d+|Numero\s+sezionale\s+\d+/\d+|"
                                  r"Numero\s+di\s+raccolta\s+generale\s+\d+/\d+|Data\s+pubblicazione\s+\d+/\d+/\d+", re.I)


def _pulisci_hl(s: str) -> str:
    s = re.sub(r"</?em>", "", s or "")
    s = _INTESTAZIONE_PAGINA.sub(" ", s)          # l'intestazione di pagina del PDF finisce in mezzo al testo
    return re.sub(r"\s+", " ", s).strip()


def blocco_dossier(text: str) -> str:
    """Per il dossier dei raccoglitori (prima che il senior scriva): le sentenze di Cassazione che il web ha portato,
    riscontrate sull'archivio — solo estremi, nessuna richiesta del testo. Vuoto se non ce ne sono."""
    try:
        v = verifica(text)
    except Exception:  # noqa: BLE001
        return ""
    return blocco(v.get("items") or [], text, "it", con_passi=False,
                  testa=("⚖️ CASSAZIONE — le sentenze del dossier riscontrate sull'ARCHIVIO UFFICIALE della Corte (Italgiure, "
                         "completo dal 2009). CONFERMATA = esiste con quegli estremi: puoi fondarci il ragionamento citando "
                         "gli estremi ufficiali. ESTREMI DIVERSI / NON TROVATA = non fondarci nulla senza dirlo."))


def estratti(items: list[dict], text: str, massimo: int = 6, tetto_s: float = 6.0) -> dict:
    """{sn_id: passo} per le citazioni CONFERMATE con testo integrale; tempo e numero limitati, mai solleva."""
    out: dict = {}
    t0 = time.time()
    for it in items:
        if len(out) >= massimo or time.time() - t0 > tetto_s:
            break
        r = it.get("record") or {}
        sid = r.get("sn_id")
        if it.get("status") != "verified" or not sid:
            continue
        termini = []
        for pos in it.get("posizioni") or []:
            for w in _termini(text, tuple(pos)):
                if w not in termini:
                    termini.append(w)
        termini = termini[:16]
        if not termini:
            continue
        k = (sid, tuple(termini))
        if k in _est_cache:
            out[sid] = _est_cache[k]
            continue
        try:
            d = _solr({"q": f'id:"{sid}"', "rows": 1, "fl": "id", "hl": "true", "hl.fl": "ocr",
                       "hl.q": "ocr:(" + " OR ".join(termini) + ")", "hl.snippets": 2, "hl.fragsize": 320},
                      timeout=min(TIMEOUT_S, max(1.0, tetto_s - (time.time() - t0))))
            frs = ((d.get("highlighting") or {}).get(sid) or {}).get("ocr") or []
            passo = " […] ".join(_pulisci_hl(f) for f in frs[:2])
        except Exception:  # noqa: BLE001
            log.debug("cassazione: estratto non disponibile per %s", sid, exc_info=True)
            passo = ""
        if passo:
            _est_cache[k] = passo[:700]
            out[sid] = passo[:700]
        if len(_est_cache) > 2000:
            _est_cache.clear()
    return out


def blocco(items: list[dict], text: str, lang: str = "it", con_passi: bool = True, testa: str | None = None) -> str:
    """Il resoconto per il Giudice (solo sessione italiana): confermate con estremi ufficiali, esito e passo del testo;
    estremi diversi; non trovate. Vuoto se non ci sono citazioni di Cassazione riscontrabili. `con_passi=False` (il
    dossier dei raccoglitori): niente richieste in più, solo gli estremi."""
    cass = [i for i in items or [] if i.get("court") == "Cass"]
    if not cass or lang != "it":
        return ""
    try:
        passi = estratti(cass, text) if con_passi else {}
    except Exception:  # noqa: BLE001
        passi = {}
    r = [testa or ("CASSAZIONE — riscontro sull'ARCHIVIO UFFICIALE della Corte (Italgiure: metadati di tutti i provvedimenti "
                   "dal 2009, testo integrale degli ultimi 5 anni). Una sentenza CONFERMATA qui non va espunta né marcata «da "
                   "riscontrare»: cita gli estremi ufficiali; se la risposta la usa per un principio che il passo del testo "
                   "non sostiene, dillo.")]
    for it in cass:
        rec = it.get("record") or {}
        if it["status"] == "verified":
            s = f"- CONFERMATA «{it['raw'][:90]}» → {descrivi(rec)}"
            if rec.get("esito"):
                s += f"; esito: {rec['esito']}"
            if it.get("correzioni"):
                s += "; ESTREMI DA CORREGGERE: " + "; ".join(it["correzioni"])
            if it.get("ramo_dedotto") and it.get("alternative"):
                s += f" (ramo non indicato: esiste anche {it['alternative'][0]})"
            p = passi.get(rec.get("sn_id") or "")
            if p:
                s += f"; passo del testo: «{p}»"
            r.append(s)
        elif it["status"] == "mismatch":
            if it.get("motivo") == "sezione":
                dich = ", ".join(sezione_label(x, "") for x in it.get("dichiarata") or [])
                r.append(f"- ESTREMI DIVERSI «{it['raw'][:90]}» → nell'archivio la n. {it['number']}/{it['year']} NON è della "
                         f"{dich}: " + "; ".join(it.get("alternative") or []) + ". Numero o sezione sbagliati: correggi o togli.")
            else:
                r.append(f"- ESTREMI DIVERSI «{it['raw'][:90]}» → nel ramo {'civile' if it.get('ramo') == 'civ' else 'penale'} "
                         f"non c'è la n. {it['number']}/{it['year']}; esiste solo: " + "; ".join(it.get("alternative") or []) + ".")
        else:
            r.append(f"- NON TROVATA «{it['raw'][:90]}» → nessun provvedimento n. {it['number']}/{it['year']} nell'archivio "
                     f"ufficiale (anno coperto): da riscontrare — non presentarla come certa.")
    return "\n".join(r)


# ══════════════════════════════════════════════════════════════════════════════════════════════════════════
# 5. I PRECEDENTI DI CASSAZIONE PER LA DOMANDA (ricerca viva sul testo integrale, come un avvocato su SentenzeWeb)
# ══════════════════════════════════════════════════════════════════════════════════════════════════════════
# Misurato il 24 set: sul caso dell'auto targata Albania i precedenti italiani (Consulta/TAR/CdS in FTS locale) davano
# ZERO decisioni, mentre la ricerca per parole sul testo integrale della Cassazione («ammissione temporanea veicolo
# residente legale rappresentante») mette in testa la 15208/2024 e la 10383/2026 — le due decisioni sul caso.
# NON è un archivio copiato: una richiesta per domanda, i record non si conservano (solo la cache degli estremi).
# Entrano solo decisioni sul merito: fuori inammissibilità, ordinanze interlocutorie e decreti (regola del titolare:
# «entra solo ciò che migliora»).
_GENERICHE = set("""ricorso ricorsi ricorrente ricorrenti controricorrente controricorrenti intimato intimata corte cassazione
sentenza sentenze ordinanza ordinanze decreto decreti giudice giudici giudizio giudizi appello tribunale motivo motivi articolo
articoli comma commi legge leggi norma norme codice civile penale procedura diritto diritti caso casi questione questioni parte
parti italia italiano italiana quale quali come dove quando perché anche solo sempre ogni tutti tutte essere avere fare stato
stata stati state cliente clienti avvocato mio mia suoi sue loro altro altra altri nuovo nuova prima dopo senza entro circa
cosa cose rischio rischi possibile possibilità vale valgono serve servono deve devono può possono""".split())


def _termini_query(q: str, massimo: int = 8) -> list[str]:
    out = []
    for w in re.findall(r"[A-Za-zÀ-ÿ]{4,}", q or ""):
        w = w.lower()
        if w in _GENERICHE or w in _STOP or w in out:
            continue
        out.append(w)
    return out[:massimo]


# la MATERIA del provvedimento deve toccare il caso (domanda, riassunto, codici recuperati): misurato sulle 10 domande
# salvate, via così «Fallimento» su una locazione, «Successioni» su una separazione, «Irpeg» su un consumatore; resta
# «Tributi e dazi doganali» sull'auto targata Albania (il codice doganale è fra i recuperati). Senza materia (penale):
# il passo evidenziato deve contenere almeno 2 parole della ricerca.
_RADICI_VUOTE = {"altro", "altri", "altre", "gener", "diver", "legge", "civil", "priva", "pubbl", "rappo", "tutti", "codic",
                 "norme", "dirit", "senza", "della", "delle", "nella", "sulla", "ipote"}


def _radici(t: str) -> set[str]:
    return {w[:5] for w in re.findall(r"[a-zà-ÿ]{5,}", (t or "").lower())} - _RADICI_VUOTE


def _tocca_il_caso(r: dict, passo: str, termini: list[str], ctx_radici: set) -> bool:
    mat = _radici(r.get("materia") or "")
    if mat:
        return bool(mat & ctx_radici)
    p = (passo or "").lower()
    return sum(1 for t in termini if t in p) >= 2


def cerca_precedenti(domande: list[str], ramo: str = "civ", k: int = 3, tetto_s: float = 6.0, termini: int = 8,
                     contesto: str | None = None, consenso: int = 1) -> list[dict]:
    """Le decisioni di merito più vicine alla domanda nel testo integrale (ultimi ~5 anni), fuse fra le query del
    triage (RRF). Ogni voce: il record uniforme + «passo» (il testo evidenziato) + «termini». Mai solleva; archivio
    muto → []."""
    global _down_until
    if not ENABLED or time.time() < _down_until or not domande:
        return []
    kind = "snpen" if ramo == "pen" else "snciv"
    fq = ['-tipoprov:Decreto', '-tipoprov:"Ordinanza Interlocutoria"', '-ocrdis:inammissibil*']
    t0 = time.time()
    punti: dict = {}
    voti: dict = {}                 # in quante ricerche il provvedimento è fra i primi 5
    docs: dict = {}
    tutti_termini: list[str] = []
    for dq in [d for d in domande if d][:3]:
        parole = _termini_query(dq, termini)
        if len(parole) < 2:
            continue
        tutti_termini += [t for t in parole if t not in tutti_termini]
        resto = max(1.0, tetto_s - (time.time() - t0))
        try:
            d = _solr({"q": f"kind:{kind} AND ocr:(" + " OR ".join(parole) + ")", "rows": 8, "sort": "score desc",
                       "fl": _FL + ",score", "fq": fq}, timeout=min(TIMEOUT_S, resto))
        except Exception as exc:  # noqa: BLE001
            _down_until = time.time() + 300
            log.warning("cassazione: ricerca dei precedenti non riuscita (%s)", str(exc)[:120])
            return []
        for r, doc in enumerate((d.get("response") or {}).get("docs") or []):
            i = doc.get("id")
            if not i:
                continue
            docs[i] = doc
            punti[i] = punti.get(i, 0.0) + 1.0 / (60 + r)
            if r < 5:
                voti[i] = voti.get(i, 0) + 1
        if time.time() - t0 > tetto_s:
            break
    if not punti:
        return []
    migliori = [i for i in sorted(punti, key=lambda i: -punti[i]) if voti.get(i, 0) >= consenso][:max(k * 3, 6)]
    if not migliori:
        return []
    passi: dict = {}
    try:
        d = _solr({"q": "id:(" + " OR ".join(migliori) + ")", "rows": len(migliori), "fl": "id", "hl": "true", "hl.fl": "ocr",
                   "hl.q": "ocr:(" + " OR ".join(tutti_termini[:16]) + ")", "hl.snippets": 2, "hl.fragsize": 320},
                  timeout=min(TIMEOUT_S, max(1.0, tetto_s - (time.time() - t0))))
        for i, v in (d.get("highlighting") or {}).items():
            passi[i] = " […] ".join(_pulisci_hl(f) for f in (v.get("ocr") or [])[:2])[:700]
    except Exception:  # noqa: BLE001
        log.debug("cassazione: passi dei precedenti non disponibili", exc_info=True)
    ctx = _radici(contesto) if contesto is not None else None
    out = []
    for i in migliori:
        r = _record(docs[i])
        if not r:
            continue
        r["passo"] = passi.get(i, "")
        r["termini"] = tutti_termini[:16]
        if ctx is not None and not _tocca_il_caso(r, r["passo"], tutti_termini, ctx):
            continue
        out.append(r)
        if len(out) >= k:
            break
    return out

