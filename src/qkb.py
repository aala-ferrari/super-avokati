"""Ricerca LIVE sul Registro Tregtar albanese (QKB — qkb.gov.al / format.qkb.gov.al).

Il portale è PUBBLICO per legge (Ligji 9723 «Për regjistrimin e biznesit»): chiunque
ha diritto all'estratto dei dati registrati. Endpoint scoperto con una cattura di rete
(Claude-in-Chrome, 11 set 2026):

    POST https://format.qkb.gov.al/kerko-per-subjekt/   (application/x-www-form-urlencoded)
    campi: nipt · emriISubjektit · emriTregtar · administrator · aksionerOrtak ·
           formeLigjore · pronesia · qarku · qyteti · dataNga · dataNe · numriId ·
           sektoriIVeprimtarise · adresa · orderColumn · orderDir
    → HTML con card risultato (list.js), classi: .nipti .emriISubjektit
       .dataERegjistrimit .formaLigjore .qyteti .statusiISubjektit .adminOrtakAksionar

⚠️ SCELTE DI PROGETTO (senza rompere nulla):
 • Il sito è dietro un WAF F5 (header-based): si passa con header da browser veri.
 • NON è un mirror aggressivo dell'intero registro (sarebbe hammering del loro server):
   è FETCH-ON-DEMAND + cache breve. Dato sempre FRESCO e ufficiale, richieste poche
   e gentili (rate-limit interno).
 • **Fail-silent**: se QKB non risponde/blocca/cambia, torna {ok:False} e il chiamante
   ripiega su «incolla il risultato manualmente». Non spaccia mai un dato incerto.
 • **NON autoritativo**: è un aiuto; per un atto il professionista conferma sul
   portale ufficiale (o scarica l'estratto sigillato via e-Albania).
"""
from __future__ import annotations

import json
import logging
import re
import threading
import time

import requests

log = logging.getLogger(__name__)

SEARCH_URL = "https://format.qkb.gov.al/kerko-per-subjekt/"

# Header da browser reale: necessari per passare il WAF F5 (verificato dal VPS).
_HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"),
    "Accept": "*/*",
    "Accept-Language": "sq-AL,sq;q=0.9,en;q=0.8",
    "Referer": "https://format.qkb.gov.al/kerko-per-subjekt/",
    "Origin": "https://format.qkb.gov.al",
    "X-Requested-With": "XMLHttpRequest",
    "Content-Type": "application/x-www-form-urlencoded",
}

_TIMEOUT = 15
_CACHE: dict[str, tuple[float, list]] = {}
_CACHE_TTL = 1800          # 30 min: fresco ma evita ri-fetch ravvicinati
_CACHE_MAX = 400
_LOCK = threading.Lock()
_LAST = [0.0]
_MIN_INTERVAL = 1.0        # ≥1s tra due richieste a QKB (gentile)

def _parse(html: str) -> list[dict]:
    """La pagina incorpora i risultati come `response = JSON.parse("[...]")` (JSON
    doppio-codificato) e li rende con list.js. Parsiamo direttamente quel JSON —
    più robusto e più ricco del markup (include i red-flag propri di QKB)."""
    m = re.search(r'JSON\.parse\("((?:[^"\\]|\\.)*)"\)', html)
    if not m:
        return []
    try:
        arr = json.loads(json.loads('"' + m.group(1) + '"'))
    except Exception:  # noqa: BLE001
        return []
    if not isinstance(arr, list):
        return []
    out = []
    for o in arr:
        if not isinstance(o, dict):
            continue
        red = [str(o.get(f) or "").strip()
               for f in ("rppRedFlagText", "bilanciRedFlagText", "adminRedFlagText")
               if str(o.get(f) or "").strip()]
        out.append({
            "nipt": o.get("nipti") or "",
            "emri": o.get("emriISubjektit") or "",
            "tregtar": o.get("emriTregtar") or "",
            "forma": o.get("formaLigjore") or "",
            "status": o.get("statusiISubjektit") or "",
            "data_regjistrimit": o.get("dataERegjistrimit") or "",
            "qyteti": o.get("qyteti") or "",
            "shtetesia": o.get("shtetesia") or "",
            "admin_ortak": o.get("adminOrtakAksionar") or "",
            "objekti": (o.get("sektoriIVeprimtarise") or "")[:500],
            "red_flags": red,
            "show_red_flag": str(o.get("showRedFlag") or "").strip().lower() == "true",
        })
    return out


def search(*, nipt: str = "", name: str = "", tregtar: str = "", admin: str = "",
           shareholder: str = "", forma: str = "", timeout: int = _TIMEOUT,
           max_results: int = 25) -> dict:
    """Cerca sul QKB. Almeno un criterio tra nipt/name/tregtar/admin/shareholder.
    `admin`/`shareholder` = ricerca INVERSA (in quali società è quella persona).
    Ritorna {ok, results:[{nipt,emri,status,forma,qyteti,data_regjistrimit,admin_ortak}],
    cached, error}. Fail-silent: ok=False → il chiamante ripiega su «incolla»."""
    crits = [nipt, name, tregtar, admin, shareholder]
    if not any((c or "").strip() for c in crits):
        return {"ok": False, "error": "no_criteria", "results": []}
    key = "|".join((c or "").strip().lower() for c in crits + [forma])
    now = time.time()
    with _LOCK:
        hit = _CACHE.get(key)
        if hit and now - hit[0] < _CACHE_TTL:
            return {"ok": True, "cached": True, "results": hit[1]}
    data = {
        "nipt": nipt.strip(), "emriISubjektit": name.strip(), "emriTregtar": tregtar.strip(),
        "administrator": admin.strip(), "aksionerOrtak": shareholder.strip(),
        "formeLigjore": forma.strip(), "pronesia": "", "dataNga": "", "dataNe": "",
        "numriId": "", "sektoriIVeprimtarise": "", "qarku": "", "qyteti": "", "adresa": "",
        "orderColumn": "", "orderDir": "",
    }
    try:
        with _LOCK:  # rate-limit gentile, serializza le chiamate a QKB
            dt = time.time() - _LAST[0]
            if dt < _MIN_INTERVAL:
                time.sleep(_MIN_INTERVAL - dt)
            r = requests.post(SEARCH_URL, headers=_HEADERS, data=data, timeout=timeout)
            _LAST[0] = time.time()
        if r.status_code != 200 or "Request Rejected" in r.text[:600]:
            return {"ok": False, "error": "blocked_%s" % r.status_code, "results": []}
        res = _parse(r.text)[:max_results]
        with _LOCK:
            if len(_CACHE) > _CACHE_MAX:
                _CACHE.clear()
            _CACHE[key] = (time.time(), res)
        return {"ok": True, "cached": False, "results": res}
    except Exception as e:  # noqa: BLE001 — fail-silent per il fallback «incolla»
        log.warning("qkb search failed: %s", e)
        return {"ok": False, "error": "unreachable", "results": []}


def format_results(results: list[dict]) -> str:
    """Testo strutturato da passare a notary.verify_subject per l'analisi."""
    if not results:
        return ""
    lines = ["TË DHËNA NGA QKB (kërkim live në regjistrin tregtar, publik):"]
    for r in results:
        lines.append(
            "\n• NIPT: %s | Emri: %s | Status: %s | Forma: %s | Qyteti: %s | Data reg.: %s"
            "\n  Administrator/Ortak/Aksionar: %s"
            "\n  Pronësia: %s | Objekti: %s" % (
                r.get("nipt", "[?]"), r.get("emri", ""), r.get("status") or "[?]",
                r.get("forma", ""), r.get("qyteti", ""), r.get("data_regjistrimit", ""),
                r.get("admin_ortak", "") or "[?]",
                r.get("shtetesia", "") or "[?]", (r.get("objekti", "") or "")[:200]))
        if r.get("red_flags"):
            lines.append("  ⚠️ RED-FLAG (nga vetë QKB): " + " · ".join(r["red_flags"]))
    return "\n".join(lines)
