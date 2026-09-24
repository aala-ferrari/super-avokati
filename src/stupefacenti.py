# -*- coding: utf-8 -*-
"""v9.390 — LE TABELLE DEGLI STUPEFACENTI (d.P.R. 309/1990, testo vigente da Normattiva) al senior, al Giudice e alla verifica.

Perché (misurato il 25 set, 30 sostanze): a memoria il cervello sbaglia la tabella di 6 — ketamina (è nella I, diceva
medicinali B), GHB (IV, diceva I), buprenorfina (IV, diceva I), metaqualone (III, diceva I), tramadolo (I, diceva «non
inclusa»), 1cP-LSD (I, diceva «non inclusa») — e la tabella decide l'art. 73: Tabelle I e III → comma 1, II e IV → comma 4,
o se il fatto è reato. Un dizionario, non 1.000 «articoli» nella ricerca: le denominazioni chimiche non somigliano a
nessuna domanda e un'unità con 688 sostanze vincerebbe ogni ricerca per parole.

Dati: `data/processed/it_tabelle_stupefacenti.json` (`tools/ingest_tabelle_stupefacenti.py`, sull'host, da rilanciare
quando il d.P.R. 309/1990 risulta aggiornato). Tre usi: `trova` (le sostanze nominate in un testo, anche coi nomi di strada
più comuni: hashish, marijuana, ecstasy, crack, fentanyl…), `blocco` (per il dossier del senior e del Giudice) e
`verifica` (una risposta che mette una sostanza nella tabella sbagliata → correzione). Mai solleva.
"""
from __future__ import annotations

import json
import os
import re
import threading
import unicodedata

from .config import PROCESSED_DATA_PATH
from .logging_utils import get_logger

log = get_logger(__name__)

FILE = PROCESSED_DATA_PATH / "it_tabelle_stupefacenti.json"
_lock = threading.Lock()
_stato: dict = {"mtime": None, "dati": None, "nomi": {}, "rx": None}

# nomi di strada e grafie correnti → la denominazione della tabella (solo sinonimi univoci; «erba», «spice» no: ambigui)
_ALIAS = {"hashish": "Cannabis (resina)", "hascisc": "Cannabis (resina)", "marijuana": "Cannabis (foglie e infiorescenza)",
          "marihuana": "Cannabis (foglie e infiorescenza)", "cannabis": "Cannabis (foglie e infiorescenza)",
          "olio di cannabis": "Cannabis (olio)", "crack": "Cocaina", "cocaina base": "Cocaina", "ecstasy": "MDMA",
          "fentanyl": "Fentanil", "tramadol": "Tramadolo", "kratom": "MITRAGININA", "funghi allucinogeni": "Psilocibina",
          "metanfetamina": "Metamfetamina", "shaboo": "Metamfetamina", "shabu": "Metamfetamina", "ossicodone": "Ossicodone",
          "oxycodone": "Ossicodone", "ghb": "Acido gamma-idrossibutirrico", "oxibato": "Acido gamma-idrossibutirrico",
          "lsd": "LSD", "mdma": "MDMA", "mefedrone": "Mefedrone"}
_NOMI_TAB = {"I": "Tabella I", "II": "Tabella II", "III": "Tabella III", "IV": "Tabella IV"}
# sigle delle tabelle che nel testo di un avvocato sono ALTRO (documento, determina, AMT = azienda di trasporti…)
_SIGLE_AMBIGUE = {"doc", "dom", "dot", "det", "mal", "bod", "dpt", "ept", "amt", "dob", "iso-", "fenil"}


def _piega(s: str) -> str:
    s = unicodedata.normalize("NFKD", (s or "").lower())
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", s.replace("*", "")).strip()


def _dati() -> dict | None:
    with _lock:
        try:
            mt = os.path.getmtime(FILE)
        except OSError:
            return None
        if _stato["mtime"] == mt:
            return _stato["dati"]
        try:
            d = json.loads(FILE.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            log.warning("stupefacenti: tabelle non leggibili", exc_info=True)
            return None
        nomi: dict = {}
        for r in d.get("righe") or []:
            voci = [r["nome"]] + re.findall(r"\(([^()]{2,60})\)", r["nome"]) + [x for x in re.split(r"[;]", r.get("altri") or "") if x]
            for v in voci:
                base = re.sub(r"\s*\([^()]*\)\s*", " ", v) if v == r["nome"] else v
                for forma in {base, v}:
                    k = _piega(forma)
                    if 3 <= len(k) <= 60 and not re.fullmatch(r"[\d\W]+", k) and k not in _SIGLE_AMBIGUE:
                        nomi.setdefault(k, [])
                        voce = (r["tabella"], r.get("sezione") or "", r["nome"].replace("**", "").strip())
                        if voce not in nomi[k]:
                            nomi[k].append(voce)
        for a, target in _ALIAS.items():
            k = _piega(target)
            if k in nomi:
                nomi.setdefault(_piega(a), [])
                for v in nomi[k]:
                    if v not in nomi[_piega(a)]:
                        nomi[_piega(a)].append(v)
        # i nomi più lunghi prima: «olio di cannabis» vince su «cannabis», «acido gamma-idrossibutirrico» su «ghb»
        chiavi = sorted(nomi, key=len, reverse=True)
        rx = re.compile(r"(?<![\w-])(" + "|".join(re.escape(k) for k in chiavi) + r")(?![\w-])")
        _stato.update(mtime=mt, dati=d, nomi=nomi, rx=rx)
        return d


def trova(text: str) -> list[dict]:
    """Le sostanze delle tabelle nominate nel testo: [{testo, voci: [(tabella, sezione, nome ufficiale)], pos}]."""
    d = _dati()
    if not d or not text:
        return []
    t = _piega(text)
    out: dict = {}
    for m in _stato["rx"].finditer(t):
        k = m.group(1)
        # sigle brevi solo se scritte come sigle nel testo originale («LSD», «GHB»), mai dentro una parola comune
        if len(k) <= 4 and k.upper() not in (text or ""):
            continue
        v = out.setdefault(k, {"testo": k, "voci": _stato["nomi"][k], "pos": []})
        v["pos"].append((m.start(), m.end()))
    return list(out.values())


def _mostra(k: str) -> str:
    return k.upper() if len(k) <= 4 and k.isalpha() else k[:1].upper() + k[1:]


def _tabelle_penali(voci) -> list[str]:
    return sorted({t for t, s, n in voci if t in _NOMI_TAB}, key=["I", "II", "III", "IV"].index)


def _dove(voci) -> str:
    parti = []
    for t in _tabelle_penali(voci):
        parti.append(_NOMI_TAB[t])
    sez = sorted({s for t, s, n in voci if t == "MED" and s})
    if sez:
        parti.append("Tabella dei medicinali, sezione " + "/".join(sez))
    return " + ".join(parti) or "nessuna tabella"


def blocco(text: str) -> str:
    """Per il dossier (senior e Giudice): dove stanno le sostanze nominate, dal testo vigente. Vuoto se nessuna."""
    try:
        trovate = trova(text)
    except Exception:  # noqa: BLE001
        return ""
    if not trovate:
        return ""
    d = _stato["dati"] or {}
    r = [f"💊 TABELLE DELLE SOSTANZE STUPEFACENTI E PSICOTROPE — d.P.R. 309/1990, testo vigente (Normattiva, aggiornamento "
         f"n. {d.get('versione') or '?'}, scaricato il {d.get('scaricato') or '?'}). È il dato ufficiale: prevale sulla memoria. "
         f"Per l'art. 73: Tabelle I e III → comma 1; Tabelle II e IV → comma 4 (leggi il testo dell'articolo nel blocco); la "
         f"Tabella dei medicinali riguarda prescrizione e dispensazione."]
    for s in trovate[:12]:
        nomi = sorted({n for t, z, n in s["voci"]})
        r.append(f"- «{_mostra(s['testo'])}» → {_dove(s['voci'])}" + (f" (voce: {'; '.join(nomi[:2])})" if nomi else ""))
    return "\n".join(r)


_TAB_RIF = re.compile(r"\btab(?:ella|\.)\s+(iv|i{1,3})\b(?!\s*(?:e|,)\s*(?:iv|i{1,3})\b)")


def verifica(text: str) -> list[dict]:
    """Le affermazioni «<sostanza> … Tabella R» che contraddicono il testo vigente: [{sostanza, detta, vera}]."""
    errori = []
    try:
        trovate = trova(text)
    except Exception:  # noqa: BLE001
        return []
    if not trovate:
        return []
    t = _piega(text)
    tutte = sorted(((p, s) for s in trovate for p in s["pos"]), key=lambda x: x[0])
    for i, ((a, b), s) in enumerate(tutte):
        vere = _tabelle_penali(s["voci"])
        if not vere:
            continue
        fine = tutte[i + 1][0][0] if i + 1 < len(tutte) else len(t)
        finestra = t[b: min(fine, b + 60)]
        m = _TAB_RIF.search(finestra)
        if not m or re.search(r"[.;]\s", finestra[:m.start()]):
            continue
        detta = m.group(1).upper()
        if detta not in vere and not any(e["sostanza"] == _mostra(s["testo"]) and e["detta"] == detta for e in errori):
            errori.append({"sostanza": _mostra(s["testo"]), "detta": detta, "vera": _dove(s["voci"])})
    return errori


def nota(text: str) -> str:
    """La correzione da attaccare al testo (idempotente): vuota se non c'è niente da correggere."""
    errori = verifica(text)
    testa = "> ⚠️ **Tabelle degli stupefacenti — da correggere** (d.P.R. 309/1990, testo vigente su Normattiva):"
    if not errori or testa in (text or ""):
        return ""
    return ("\n\n" + testa + " " + " · ".join(f"«{e['sostanza']}» è in {e['vera']}, non nella Tabella {e['detta']}" for e in errori[:6])
            + ".\n")
