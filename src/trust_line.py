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


_ART_MAPS: dict = {}


def _art_map(index) -> dict:
    """(code, number) → Article, una volta per indice (id): serve a leggere il testo dell'articolo."""
    k = id(index)
    m = _ART_MAPS.get(k)
    if m is None:
        m = {(a.code, str(a.number)): a for a in getattr(index, "articles", [])}
        if len(_ART_MAPS) > 4:
            _ART_MAPS.clear()
        _ART_MAPS[k] = m
    return m


def vuota() -> dict:
    return {"nene": {"verified": 0, "repealed": 0, "fake": 0, "needs_code": 0, "unconstitutional": 0, "total": 0, "bad": [],
                     "foreign_verified": 0, "foreign_unverified": 0, "foreign": []},
            "sentenze": {"verified": 0, "unverified": 0, "quashed": 0, "total": 0, "bad": [], "quashed_list": []},
            "fatti_da_precisare": 0}


def verifica(text: str, index, jurisdiction: str = "AL", retrieved_codes=None, foreign_index=None) -> dict:
    """Calcolo puro sul testo già prodotto: non chiama mai il modello, non solleva mai.
    `foreign_index` (v9.350): il corpus dell'altra giurisdizione per le citazioni di diritto straniero
    dichiarato (se None, il verificatore usa il registro `citation_verifier.INDICI`)."""
    out = vuota()
    text = text or ""
    if not text.strip() or index is None:
        return out
    try:
        from . import citation_verifier as cv
        r = cv.verify_text(text, index, retrieved_codes=retrieved_codes, foreign_index=foreign_index)
        st = r.get("stats") or {}
        for k in ("verified", "repealed", "fake", "needs_code", "total"):
            out["nene"][k] = int(st.get(k) or 0)
        out["nene"]["foreign_verified"] = int(st.get("foreign_verified") or 0)
        out["nene"]["foreign_unverified"] = int(st.get("foreign_unverified") or 0) + int(st.get("foreign_repealed") or 0)
        for it in r.get("items") or []:
            if str(it.get("status") or "").startswith("foreign_"):
                out["nene"]["foreign"].append({"raw": (it.get("raw") or "")[:70], "code": it.get("code_label") or it.get("code") or "",
                                               "status": it.get("status"), "heading": (it.get("article_heading") or "")[:70]})
                continue
            if it.get("status") in ("fake", "repealed"):
                out["nene"]["bad"].append({
                    "raw": (it.get("raw") or "")[:70], "number": it.get("number"),
                    "code": it.get("code_label") or it.get("code") or "",
                    "status": it.get("status"), "heading": (it.get("article_heading") or "")[:70]})
        # v9.339 — norme DICHIARATE INCOSTITUZIONALI dalla Gjykata Kushtetuese (grafo delle sentenze):
        # un articolo «verificato» nel corpus può essere stato annullato da un vendim GjK
        try:
            from . import case_graph as _cg
            _inc = _cg.norme_incostituzionali() if (jurisdiction or "AL").upper() != "IT" else {}
        except Exception:  # noqa: BLE001
            _inc = {}
        if _inc:
            _by = _art_map(index)
            for it in r.get("items") or []:
                k = (it.get("code"), str(it.get("number") or "").split("/")[0])
                if it.get("status") != "verified" or k not in _inc:
                    continue
                art = _by.get((it.get("code"), str(it.get("number") or ""))) or _by.get(k)
                st = _cg.stato_incostituzionale(art) if art is not None else ("tërësisht", _inc[k]["key"])
                if not st or st[0] == "konsoliduar":
                    continue            # il testo che teniamo è già quello dopo la decisione: nessun allarme
                q = st[1].split("|")
                # v9.351 — se la risposta NOMINA la decisione della GjK (numero/anno), la citazione è
                # consapevole («vendimi 37/2022 shfuqizoi fjalinë e dytë të pikës 8 të nenit 10»): non
                # è un allarme, è la ragione per cui la norma viene citata (prova viva del 19 set)
                if len(q) > 2 and re.search(r"\b%s\s*/\s*%s\b" % (re.escape(q[2]), re.escape(q[1])), text):
                    out["nene"].setdefault("unconstitutional_noted", 0)
                    out["nene"]["unconstitutional_noted"] += 1
                    continue
                out["nene"]["unconstitutional"] += 1
                out["nene"]["bad"].append({
                    "raw": (it.get("raw") or "")[:70], "number": it.get("number"),
                    "code": it.get("code_label") or it.get("code") or "",
                    "status": "unconstitutional" if st[0] == "tërësisht" else "unconstitutional_partial",
                    "heading": f"GjK vendimi nr. {q[2]}/{q[1]}"})
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
        out["sentenze"]["quashed"] = int(st.get("quashed") or 0)
        out["sentenze"]["total"] = int(st.get("total") or 0)
        for it in pay.get("items") or []:
            if it.get("status") == "unverified":
                out["sentenze"]["bad"].append((it.get("raw") or "")[:60])
            elif it.get("status") == "quashed":
                q = (it.get("quashed_by") or "||").split("|")
                out["sentenze"]["quashed_list"].append(f"{(it.get('raw') or '')[:40]} ← GjK nr. {q[2] if len(q) > 2 else '?'}/{q[1] if len(q) > 1 else '?'}")
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
    if n["fake"] or n["repealed"] or n.get("unconstitutional") or s.get("quashed"):
        return "FLAGS"
    # «senza codice» (neni 155 nudo, col codice nominato poco prima) non è un errore: resta nel
    # conteggio della riga ma non abbassa lo stato (prova viva 16 set: 19 «pa kod» su un verdetto giusto)
    if s["unverified"] or v.get("fatti_da_precisare") or n.get("foreign_unverified"):
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


def _copertura(cov: dict | None, lang: str) -> str:
    """L'asse «copertura» (v9.340): temi del triage senza alcuna norma trovata nel corpus."""
    if not cov or not cov.get("temi"):
        return ""
    t, miss = int(cov["temi"]), list(cov.get("senza_norma") or [])
    if lang == "it":
        return f" | copertura: {t - len(miss)}/{t} temi con norma" + (f" (senza: «{miss[0][:40]}»)" if miss else "")
    return f" | mbulimi: {t - len(miss)}/{t} tema me normë" + (f" (pa normë: «{miss[0][:40]}»)" if miss else "")


def riga(v: dict, lang: str = "sq", tempo: dict | None = None, coverage: dict | None = None) -> str:
    """La riga di fiducia sotto il titolo del verdetto (markdown, una riga)."""
    n, s = v["nene"], v["sentenze"]
    f = int(v.get("fatti_da_precisare") or 0)
    if lang == "it":
        a = [f"norme {n['verified']} verificate"]
        if n["repealed"]:
            a.append(f"{n['repealed']} abrogate")
        if n["fake"]:
            a.append(f"{n['fake']} non trovate nel corpus")
        if n.get("unconstitutional"):
            a.append(f"{n['unconstitutional']} dichiarate incostituzionali")
        if n["needs_code"]:
            a.append(f"{n['needs_code']} senza codice")
        b = [f"sentenze {s['verified']} confermate"]
        if s.get("quashed"):
            b.append(f"{s['quashed']} ANNULLATE")
        if s["unverified"]:
            b.append(f"{s['unverified']} da riscontrare")
        c = f"fatti {f} da precisare" if f else "fatti: nessuno da precisare"
        if n.get("foreign_verified") or n.get("foreign_unverified"):
            c += f" | diritto straniero/internazionale {n.get('foreign_verified', 0)} verificato"
            if n.get("foreign_unverified"):
                c += f" · {n['foreign_unverified']} non verificato"
        lab = "Verifica"
    else:
        a = [f"nene {n['verified']} të verifikuara"]
        if n["repealed"]:
            a.append(f"{n['repealed']} të shfuqizuara")
        if n["fake"]:
            a.append(f"{n['fake']} nuk u gjetën në korpus")
        if n.get("unconstitutional"):
            a.append(f"{n['unconstitutional']} të shpallura antikushtetuese")
        if n["needs_code"]:
            a.append(f"{n['needs_code']} pa kod")
        b = [f"vendime {s['verified']} të konfirmuara"]
        if s.get("quashed"):
            b.append(f"{s['quashed']} TË SHFUQIZUARA")
        if s["unverified"]:
            b.append(f"{s['unverified']} për t'u verifikuar")
        c = f"fakte {f} për t'u saktësuar" if f else "fakte: asnjë për t'u saktësuar"
        if n.get("foreign_verified") or n.get("foreign_unverified"):
            c += f" | e drejtë e huaj/ndërkombëtare {n.get('foreign_verified', 0)} e verifikuar"
            if n.get("foreign_unverified"):
                c += f" · {n['foreign_unverified']} e paverifikuar"
        lab = "Verifikimi"
    st = _STATO.get(lang, _STATO["sq"])[stato(v)]
    return f"> 🔎 **{lab}:** {' · '.join(a)} | {' · '.join(b)} | {c}{_tempo(tempo, lang)}{_copertura(coverage, lang)} — **{st}**"


def blocco_per_gjyqtarin(v: dict, lang: str = "sq", coverage: dict | None = None) -> str:
    """Il resoconto per il Giudice: numeri + elenco puntuale di ciò che non regge."""
    n, s = v["nene"], v["sentenze"]
    r: list[str] = []
    if coverage and coverage.get("senza_norma"):
        miss = "; ".join(f"«{m}»" for m in coverage["senza_norma"][:4])
        r.append(("COPERTURA DELLA RICERCA: per questi temi il recupero NON ha trovato alcuna norma nel corpus: %s. "
                  "Se la risposta cita una norma su questi temi, non viene dal corpus (preparazione del modello o web): trattala come da verificare."
                  if lang == "it" else
                  "MBULIMI I KËRKIMIT: për këto tema kërkimi NUK gjeti asnjë normë në korpus: %s. "
                  "Nëse përgjigja citon një normë për këto tema, nuk vjen nga korpusi (përgatitja e modelit ose web): trajtoje si për t'u verifikuar.") % miss)
    _tag_it = {"repealed": "ABROGATO", "fake": "NON ESISTE nel corpus", "unconstitutional": "DICHIARATO INCOSTITUZIONALE dalla Corte costituzionale",
               "unconstitutional_partial": "IN PARTE dichiarato incostituzionale (il testo potrebbe non rifletterlo: verificare quali punti)"}
    _tag_sq = {"repealed": "I SHFUQIZUAR", "fake": "NUK EKZISTON në korpus", "unconstitutional": "I SHPALLUR ANTIKUSHTETUES nga Gjykata Kushtetuese",
               "unconstitutional_partial": "PJESËRISHT i shpallur antikushtetues (teksti mund të mos e pasqyrojë: verifiko cilat pika)"}
    if lang == "it":
        r.append(f"Articoli citati nella risposta: {n['verified']} verificati nel corpus ufficiale, "
                 f"{n['repealed']} ABROGATI, {n['fake']} INESISTENTI nel corpus, {n.get('unconstitutional', 0)} dichiarati incostituzionali, "
                 f"{n['needs_code']} senza codice indicato.")
        for b in n["bad"][:14]:
            tag = _tag_it.get(b["status"], b["status"])
            extra = f" ({b['code']}: {b['heading']})" if b.get("heading") else (f" ({b['code']})" if b.get("code") else "")
            r.append(f"- «{b['raw']}» → {tag}{extra}")
        r.append(f"Sentenze citate: {s['verified']} confermate negli archivi, {s.get('quashed', 0)} ANNULLATE dalla Corte costituzionale, "
                 f"{s['unverified']} NON confermate (archivi parziali: da riscontrare, non necessariamente false).")
        for b in s.get("quashed_list") or []:
            r.append(f"- {b} → ANNULLATA: non è un precedente valido")
        for b in s["bad"][:8]:
            r.append(f"- «{b}» → non confermata")
        if v.get("fatti_da_precisare"):
            r.append(f"La risposta segnala {v['fatti_da_precisare']} fatto/i da precisare («Per precisione»).")
        if n.get("foreign"):
            r.append(f"Citazioni di DIRITTO STRANIERO dichiarato: {n.get('foreign_verified', 0)} verificate nel corpus dell'altra giurisdizione, "
                     f"{n.get('foreign_unverified', 0)} non verificate — fonte straniera, mai base della decisione in questa giurisdizione.")
            for b in n["foreign"][:8]:
                r.append(f"- «{b['raw']}» → {'verificata' if b['status'] == 'foreign_verified' else ('ABROGATA nel suo corpus' if b['status'] == 'foreign_repealed' else 'NON verificata')}"
                         + (f" ({b['code']}: {b['heading']})" if b.get("heading") else ""))
    else:
        r.append(f"Nenet e cituara në përgjigje: {n['verified']} të verifikuara në korpusin zyrtar, "
                 f"{n['repealed']} TË SHFUQIZUARA, {n['fake']} NUK EKZISTOJNË në korpus, {n.get('unconstitutional', 0)} të shpallura antikushtetuese, "
                 f"{n['needs_code']} pa kod të treguar.")
        for b in n["bad"][:14]:
            tag = _tag_sq.get(b["status"], b["status"])
            extra = f" ({b['code']}: {b['heading']})" if b.get("heading") else (f" ({b['code']})" if b.get("code") else "")
            r.append(f"- «{b['raw']}» → {tag}{extra}")
        r.append(f"Vendime të cituara: {s['verified']} të konfirmuara në arkiva, {s.get('quashed', 0)} TË SHFUQIZUARA nga Gjykata Kushtetuese, "
                 f"{s['unverified']} TË PAKONFIRMUARA (arkivat janë të pjesshme: për t'u verifikuar, jo domosdo të rreme).")
        for b in s.get("quashed_list") or []:
            r.append(f"- {b} → I SHFUQIZUAR: nuk është precedent i vlefshëm")
        for b in s["bad"][:8]:
            r.append(f"- «{b}» → e pakonfirmuar")
        if v.get("fatti_da_precisare"):
            r.append(f"Përgjigja sinjalizon {v['fatti_da_precisare']} fakt(e) për t'u saktësuar («Për saktësi»).")
        if n.get("foreign"):
            r.append(f"Citime nga E DREJTA E HUAJ e deklaruar: {n.get('foreign_verified', 0)} të verifikuara në korpusin e juridiksionit tjetër, "
                     f"{n.get('foreign_unverified', 0)} të paverifikuara — burim i huaj, kurrë bazë vendimi në këtë juridiksion.")
            for b in n["foreign"][:8]:
                r.append(f"- «{b['raw']}» → {'e verifikuar' if b['status'] == 'foreign_verified' else ('E SHFUQIZUAR në korpusin e vet' if b['status'] == 'foreign_repealed' else 'E PAVERIFIKUAR')}"
                         + (f" ({b['code']}: {b['heading']})" if b.get("heading") else ""))
    return "\n".join(r)


def inserisci_riga(text: str, line: str, titolo: str) -> str:
    """Mette la riga subito sotto il titolo del verdetto se c'è, altrimenti in testa."""
    if not line:
        return text
    if titolo and (text or "").startswith(titolo):
        return titolo + line + "\n\n" + text[len(titolo):]
    return line + "\n\n" + (text or "")
