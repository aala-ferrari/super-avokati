# -*- coding: utf-8 -*-
"""TRUST LINE — la verifica deterministica PRIMA del Giudice e la riga di fiducia in testa
alla risposta (v9.331, 16 set 2026; roadmap v3, passo 1).

Prima: lo scudo delle citazioni girava in web.py DOPO il cervello, quindi il Giudice Finale
decideva senza sapere quali articoli erano inesistenti o abrogati e quali sentenze non erano
confermate; l'avvocato lo scopriva dal badge, a verdetto già dato. Ora:
  1. `verifica(testo)` — calcolo puro sul testo (nessuna chiamata al modello): articoli
     (verificati / abrogati / non trovati / senza codice) via `citation_verifier`, sentenze
     (confermate / da riscontrare) via `case_citation_verifier`, fatti da precisare (le righe
     «Per precisione: …» / «Për saktësi: …» che il cervello mette in coda).
  2. `blocco_per_gjyqtarin` — il resoconto consegnato al Giudice PRIMA del verdetto, con
     l'elenco puntuale degli articoli inesistenti/abrogati: li corregge o li esclude lui.
  3. `riga` — la riga di fiducia CATEGORICA (mai percentuali: un «95%» invita a fidarsi
     ciecamente) inserita subito sotto il titolo del verdetto, nella lingua della sessione:
     ✅ verificata · 🟡 con riserve (sentenze da riscontrare, fatti da precisare, sigle senza
     codice) · 🔴 con segnalazioni (articoli inesistenti o abrogati, marcati ⚠ nel corpo).
Regola: «non trovato ≠ falso» per le sentenze (archivi parziali); per gli articoli dei codici
il corpus è completo e «non trovato» pesa. Mai censura, mai blocco: si segnala.
"""
from __future__ import annotations

import re

from .logging_utils import get_logger

log = get_logger(__name__)   # con logging.getLogger le righe INFO non arrivavano al log (vedi temporal.py)

_DEC_IDX = None
_DEC_TRIED = False
_FATTI_RE = re.compile(r"(?im)^\s*[>*\-\s]*(?:\*\*)?\s*(?:Per precisione|Për saktësi)\s*(?:\*\*)?\s*:")


def dec_index():
    """L'indice dei precedenti AL (pickle, 33 MB): caricato UNA volta per processo."""
    global _DEC_IDX, _DEC_TRIED
    if _DEC_IDX is None and not _DEC_TRIED:
        _DEC_TRIED = True
        try:
            from .retrieval import DecisionIndex, DECISIONS_INDEX_FILE
            _DEC_IDX = DecisionIndex.load(DECISIONS_INDEX_FILE)
        except Exception:  # noqa: BLE001
            log.debug("trust_line: indice decisioni non caricato", exc_info=True)
    return _DEC_IDX


def vuota() -> dict:
    return {"nene": {"verified": 0, "repealed": 0, "fake": 0, "needs_code": 0, "total": 0, "bad": []},
            "sentenze": {"verified": 0, "unverified": 0, "total": 0, "bad": []},
            "fatti_da_precisare": 0}


def verifica(text: str, index, jurisdiction: str = "AL", retrieved_codes=None) -> dict:
    """Calcolo puro sul testo già prodotto: non chiama mai il modello, non solleva mai."""
    out = vuota()
    text = text or ""
    if not text.strip() or index is None:
        return out
    try:
        from . import citation_verifier as cv
        r = cv.verify_text(text, index, retrieved_codes=retrieved_codes)
        st = r.get("stats") or {}
        for k in ("verified", "repealed", "fake", "needs_code", "total"):
            out["nene"][k] = int(st.get(k) or 0)
        for it in r.get("items") or []:
            if it.get("status") in ("fake", "repealed"):
                out["nene"]["bad"].append({
                    "raw": (it.get("raw") or "")[:70], "number": it.get("number"),
                    "code": it.get("code_label") or it.get("code") or "",
                    "status": it.get("status"), "heading": (it.get("article_heading") or "")[:70]})
    except Exception:  # noqa: BLE001
        log.debug("trust_line: verifica nene fallita", exc_info=True)
    try:
        from . import case_citation_verifier as ccv
        if (jurisdiction or "AL").upper() == "IT":
            pay = ccv.verify_cases_it(text)
        else:
            idx = dec_index()
            pay = ccv.verify_cases(text, idx) if idx is not None else {"items": [], "stats": {}}
        st = pay.get("stats") or {}
        out["sentenze"]["verified"] = int(st.get("verified") or 0)
        out["sentenze"]["unverified"] = int(st.get("unverified") or 0)
        out["sentenze"]["total"] = int(st.get("total") or 0)
        for it in pay.get("items") or []:
            if it.get("status") == "unverified":
                out["sentenze"]["bad"].append((it.get("raw") or "")[:60])
    except Exception:  # noqa: BLE001
        log.debug("trust_line: verifica sentenze fallita", exc_info=True)
    try:
        out["fatti_da_precisare"] = len(_FATTI_RE.findall(text))
    except Exception:  # noqa: BLE001
        pass
    return out


def stato(v: dict) -> str:
    """VERIFIED / RESERVATIONS / FLAGS — categorico, mai un numero."""
    n, s = v["nene"], v["sentenze"]
    if n["fake"] or n["repealed"]:
        return "FLAGS"
    # «senza codice» (neni 155 nudo, col codice nominato poco prima) non è un errore: resta nel
    # conteggio della riga ma non abbassa lo stato (prova viva 16 set: 19 «pa kod» su un verdetto giusto)
    if s["unverified"] or v.get("fatti_da_precisare"):
        return "RESERVATIONS"
    return "VERIFIED"


_STATO = {
    "it": {"VERIFIED": "✅ verificata", "RESERVATIONS": "🟡 con riserve", "FLAGS": "🔴 con segnalazioni"},
    "sq": {"VERIFIED": "✅ e verifikuar", "RESERVATIONS": "🟡 me rezerva", "FLAGS": "🔴 me sinjalizime"},
}


def _tempo(tempo: dict | None, lang: str) -> str:
    """L'asse «tempo» (v9.333): data del fatto letta e articoli/leggi con testo diverso allora."""
    if not tempo or not tempo.get("data"):
        return ""
    try:
        from datetime import date as _d
        dd = _d.fromisoformat(tempo["data"]).strftime("%d/%m/%Y" if lang == "it" else "%d.%m.%Y")
    except Exception:  # noqa: BLE001
        dd = str(tempo.get("data"))
    diversi, uguali = int(tempo.get("diversi") or 0), int(tempo.get("uguali") or 0)
    if lang == "it":
        if diversi:
            esito = f"{diversi} {'articolo' if diversi == 1 else 'articoli'} con testo diverso allora"
        elif uguali:
            esito = "testo identico a oggi"
        else:
            esito = "non verificabile"
        return f" | tempo: fatto del {dd}{' (anno)' if tempo.get('approx') else ''} · {esito}"
    if diversi:
        esito = f"{diversi} {'ligj i ndryshuar' if diversi == 1 else 'ligje të ndryshuara'} pas asaj date"
    elif uguali:
        esito = "pa ndryshime"
    else:
        esito = "e paverifikueshme"
    return f" | koha: fakti i {dd}{' (viti)' if tempo.get('approx') else ''} · {esito}"


def riga(v: dict, lang: str = "sq", tempo: dict | None = None) -> str:
    """La riga di fiducia sotto il titolo del verdetto (markdown, una riga)."""
    n, s = v["nene"], v["sentenze"]
    f = int(v.get("fatti_da_precisare") or 0)
    if lang == "it":
        a = [f"norme {n['verified']} verificate"]
        if n["repealed"]:
            a.append(f"{n['repealed']} abrogate")
        if n["fake"]:
            a.append(f"{n['fake']} non trovate nel corpus")
        if n["needs_code"]:
            a.append(f"{n['needs_code']} senza codice")
        b = [f"sentenze {s['verified']} confermate"]
        if s["unverified"]:
            b.append(f"{s['unverified']} da riscontrare")
        c = f"fatti {f} da precisare" if f else "fatti: nessuno da precisare"
        lab = "Verifica"
    else:
        a = [f"nene {n['verified']} të verifikuara"]
        if n["repealed"]:
            a.append(f"{n['repealed']} të shfuqizuara")
        if n["fake"]:
            a.append(f"{n['fake']} nuk u gjetën në korpus")
        if n["needs_code"]:
            a.append(f"{n['needs_code']} pa kod")
        b = [f"vendime {s['verified']} të konfirmuara"]
        if s["unverified"]:
            b.append(f"{s['unverified']} për t'u verifikuar")
        c = f"fakte {f} për t'u saktësuar" if f else "fakte: asnjë për t'u saktësuar"
        lab = "Verifikimi"
    st = _STATO.get(lang, _STATO["sq"])[stato(v)]
    return f"> 🔎 **{lab}:** {' · '.join(a)} | {' · '.join(b)} | {c}{_tempo(tempo, lang)} — **{st}**"


def blocco_per_gjyqtarin(v: dict, lang: str = "sq") -> str:
    """Il resoconto per il Giudice: numeri + elenco puntuale di ciò che non regge."""
    n, s = v["nene"], v["sentenze"]
    r: list[str] = []
    if lang == "it":
        r.append(f"Articoli citati nella risposta: {n['verified']} verificati nel corpus ufficiale, "
                 f"{n['repealed']} ABROGATI, {n['fake']} INESISTENTI nel corpus, {n['needs_code']} senza codice indicato.")
        for b in n["bad"][:14]:
            tag = "ABROGATO" if b["status"] == "repealed" else "NON ESISTE nel corpus"
            extra = f" ({b['code']}: {b['heading']})" if b.get("heading") else (f" ({b['code']})" if b.get("code") else "")
            r.append(f"- «{b['raw']}» → {tag}{extra}")
        r.append(f"Sentenze citate: {s['verified']} confermate negli archivi, {s['unverified']} NON confermate "
                 f"(archivi parziali: da riscontrare, non necessariamente false).")
        for b in s["bad"][:8]:
            r.append(f"- «{b}» → non confermata")
        if v.get("fatti_da_precisare"):
            r.append(f"La risposta segnala {v['fatti_da_precisare']} fatto/i da precisare («Per precisione»).")
    else:
        r.append(f"Nenet e cituara në përgjigje: {n['verified']} të verifikuara në korpusin zyrtar, "
                 f"{n['repealed']} TË SHFUQIZUARA, {n['fake']} NUK EKZISTOJNË në korpus, {n['needs_code']} pa kod të treguar.")
        for b in n["bad"][:14]:
            tag = "I SHFUQIZUAR" if b["status"] == "repealed" else "NUK EKZISTON në korpus"
            extra = f" ({b['code']}: {b['heading']})" if b.get("heading") else (f" ({b['code']})" if b.get("code") else "")
            r.append(f"- «{b['raw']}» → {tag}{extra}")
        r.append(f"Vendime të cituara: {s['verified']} të konfirmuara në arkiva, {s['unverified']} TË PAKONFIRMUARA "
                 f"(arkivat janë të pjesshme: për t'u verifikuar, jo domosdo të rreme).")
        for b in s["bad"][:8]:
            r.append(f"- «{b}» → e pakonfirmuar")
        if v.get("fatti_da_precisare"):
            r.append(f"Përgjigja sinjalizon {v['fatti_da_precisare']} fakt(e) për t'u saktësuar («Për saktësi»).")
    return "\n".join(r)


def inserisci_riga(text: str, line: str, titolo: str) -> str:
    """Mette la riga subito sotto il titolo del verdetto se c'è, altrimenti in testa."""
    if not line:
        return text
    if titolo and (text or "").startswith(titolo):
        return titolo + line + "\n\n" + text[len(titolo):]
    return line + "\n\n" + (text or "")
