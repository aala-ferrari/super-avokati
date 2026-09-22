# -*- coding: utf-8 -*-
"""GRAFO DELLE SENTENZE (v9.339, roadmap v3 P6) — chi cita chi, chi è stata annullata, chi «fa
giurisprudenza». Deterministico, senza modello, costruito dai 1.407 precedenti del pickle
(`tools/build_case_graph.py` → `data/index/case_graph.json`) e letto a runtime.

Tre segnali, tutti misurabili:
  • CITES / CITED_BY — nel ragionamento le decisioni citano «vendimi nr. N, datë dd.mm.aaaa» (Gjykata
    Kushtetuese) e «00-AAAA-N» (Gjykata e Lartë): 7.804 riferimenti, 2.853 risolvibili dentro il
    corpus (misurato il 16 set). Una decisione citata da molte altre è un'autorità consolidata;
    una isolata no. Il numero entra nel blocco dei precedenti («cituar nga 12 vendime»).
  • QUASHED_BY (trattamento negativo) — la Gjykata Kushtetuese, su ricorso individuale, SHFUQIZON
    vendime della Gjykata e Lartë (vendim nr. X i Kolegjit Civil/Penal). Se la decisione annullata è
    nel corpus, va marcata: un avvocato che la cita come precedente favorevole porta in aula una
    sentenza annullata. Si legge SOLO dal dispositivo («Shfuqizimin e vendimit nr. …») delle decisioni
    con esito pranim/pjesërisht — mai dall'oggetto o dalla richiesta («kërkesë për shfuqizimin» non
    è una decisione).
  • UNIFYING — «Kolegjet e Bashkuara të Gjykatës së Lartë»: decisione unificatrice, vincolante per i
    collegi (neni 141/2 Kushtetuta): forza massima nel ranking.
Regola: «non trovato ≠ falso» resta; il grafo AGGIUNGE avvisi e pesi, non censura.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from .logging_utils import get_logger

log = get_logger(__name__)

_RX_K = re.compile(r"[Vv]endim(?:i|in|it|e|et)?\s+(?:nr\.?\s*)?(\d{1,4})\s*,?\s*dat[ëe]\s*(\d{1,2})[./](\d{1,2})[./](\d{4})")
_RX_GJL = re.compile(r"\b(\d{2})-(\d{4})-(\d{1,5})\b")
_RX_LOWER = re.compile(r"Gjykat[ëe]s?\s+s[ëe]\s+(?:Rrethit|Apelit|Administrativ)|Gjykata e (?:Rrethit|Apelit)|Apelit", re.I)
_RX_KUSH = re.compile(r"Kushtetues", re.I)
_RX_GJL_CTX = re.compile(r"Gjykat[ëe]s?\s+s[ëe]\s+Lart[ëe]|Kolegj", re.I)
_RX_UNI = re.compile(r"Kolegje(?:t|ve)\s+t[ëe]\s+Bashkuar", re.I)
_RX_SHF = re.compile(r"[Ss]hfuqiz\w*\s+(?:e\s+|të\s+)?vendim\w*")
# dispositivo: «Shfuqizimin si të papajtueshëm me Kushtetutën … të vendimit nr. 00-2015-965, datë … të
# Kolegjit Civil të Gjykatës së Lartë» (annulla un vendim GjL) / «… të nenit 4 të ligjit nr. 143/2015»
# (annulla una norma). Una frase che comincia con «Rrëzimin» è un rigetto: non conta.
_RX_SENT = re.compile(r"(?<=[.;])\s+(?=[A-ZÇË])")
_RX_LAW = re.compile(r"ligjit\s+nr\.?\s*(\d[\d ]{0,6}(?:/\d{4})?)", re.I)
_RX_ARTS = re.compile(r"nen(?:it|eve|i|et)\s+((?:\d+(?:/[a-zë\d]+)?(?:\s*(?:[-–]|deri(?:\s+n[ëe])?)\s*\d+)?(?:\s*,\s*|\s+dhe\s+)?)+)", re.I)


def _espandi_nene(s: str) -> list[str]:
    out: list[str] = []
    for m in re.finditer(r"(\d+(?:/[a-zë\d]+)?)(?:\s*(?:[-–]|deri(?:\s+n[ëe])?)\s*(\d+))?", s or ""):
        a, b = m.group(1), m.group(2)
        if b and a.isdigit() and int(b) > int(a) and int(b) - int(a) <= 60:
            out.extend(str(x) for x in range(int(a), int(b) + 1))
        else:
            out.append(a)
    return out


def key(court_code: str, year, number) -> str:
    n = str(number or "").strip()
    if court_code == "kushtetuese":
        n = re.sub(r"\D", "", n).lstrip("0") or "0"
    return f"{court_code}|{int(year) if year else 0}|{n}"


def _refs(text: str, own_court: str) -> list[str]:
    """Riferimenti ad altre decisioni nel testo, come chiavi (non ancora filtrate sull'esistenza)."""
    out: list[str] = []
    for m in _RX_K.finditer(text or ""):
        n, _d, _mo, y = m.groups()
        ctx_before = text[max(0, m.start() - 110): m.start()]
        ctx_after = text[m.end(): m.end() + 110]
        if _RX_LOWER.search(ctx_before[-60:]) or _RX_LOWER.search(ctx_after[:60]):
            continue                                      # vendim di un grado inferiore
        if _RX_KUSH.search(ctx_before) or _RX_KUSH.search(ctx_after) or own_court == "kushtetuese":
            out.append(key("kushtetuese", y, n))
    for m in _RX_GJL.finditer(text or ""):
        p, y, n = m.groups()
        if p == "00":
            out.append(key("gjykata_elarte", y, f"00-{y}-{n}"))
    return out


def negativi_dal_dispositivo(disp: str) -> tuple[list[str], list[dict]]:
    """Dal DISPOSITIVO di una decisione Kushtetuese: (vendime GjL annullati, norme dichiarate
    incostituzionali). Il campo `outcome` del pickle non basta (K 60/2016: «Pranimin e kërkesës…»
    ma outcome='rrëzim'): si leggono le frasi. «Rrëzimin e kërkesës për shfuqizimin…» non conta."""
    quashed: list[str] = []
    inval: list[dict] = []
    for sent in _RX_SENT.split(disp or ""):
        s = sent.strip()
        if not s or s.lower().startswith(("rrëzimin", "rrezimin", "mospranimin", "pushimin")):
            continue
        if not re.match(r"(?:-\s*)?(?:shfuqizim|shpallj)", s, re.I):
            continue
        if "kërkesës për shfuqizimin" in s.lower() or "kerkeses per shfuqizimin" in s.lower():
            continue
        if _RX_GJL_CTX.search(s):
            for m in _RX_GJL.finditer(s):
                p, y, n = m.groups()
                if p == "00":
                    quashed.append(key("gjykata_elarte", y, f"00-{y}-{n}"))
        ml = _RX_LAW.search(s)
        if ml:
            law = re.sub(r"\s+", "", ml.group(1) or "")
            # «Shfuqizimin e nenit 4 të VENDIMIT nr. 753 … të Këshillit të Ministrave “Për dispozitat
            # zbatuese të ligjit nr. 29/2023”» → l'articolo è della VKM, non della legge citata nel
            # titolo (misurato: tatimi_te_ardhurat 4 finiva «tërësisht antikushtetues» per sbaglio)
            mv = re.search(r"vendimit\s+nr\.?\s*(\d+)|K[ëe]shillit\s+t[ëe]\s+Ministrave|\bVKM\b", s[: ml.start()], re.I)
            if mv:
                law = f"vkm:{mv.group(1) or '?'}"
            arts: list[str] = []
            for ma in _RX_ARTS.finditer(s[: ml.start()]):
                arts.extend(_espandi_nene(ma.group(1)))
            # PARZIALE («të fjalisë së fundit të pikës 1 të nenit 26», «të shkronjës “b” të nenit 4»)
            # contro TOTALE («të nenit 4 të ligjit»): un nen vivo con una frase caduta NON è un nen
            # incostituzionale — dirlo sarebbe il falso negativo peggiore (noteria 26, misurato)
            pre = s[: ml.start()].lower()
            partial = bool(re.search(r"pik[ëa]s?\b|pikave|fjali|shkronj|paragraf|germ|togfjal|fjal[ëe]v?e?\b", pre))
            inval.append({"law": law, "articles": list(dict.fromkeys(arts))[:40], "partial": partial,
                          "text": " ".join(s.split())[:240]})
    return quashed, inval


def build(decisions) -> dict:
    nodes: dict[str, dict] = {}
    for d in decisions:
        k = key(d.court_code, d.year, d.number)
        nodes[k] = {"court": d.court_code, "year": int(d.year or 0), "number": str(d.number),
                    "date": d.date or "", "outcome": d.outcome or "", "cites": [], "cited_by": 0,
                    "quashed_by": [], "quashes": [], "invalidates": [], "unifying": False}
    for d in decisions:
        k = key(d.court_code, d.year, d.number)
        text = (d.reasoning or "") + "\n" + (d.dispositif or "")
        head = (d.court_title_sq or "") + " " + (d.objekti or "") + " " + (d.kerkues or "") + " " + (d.reasoning or "")[:600]
        if d.court_code == "gjykata_elarte" and _RX_UNI.search(head):
            nodes[k]["unifying"] = True
        refs = [r for r in dict.fromkeys(_refs(text, d.court_code)) if r in nodes and r != k]
        nodes[k]["cites"] = refs
        for r in refs:
            nodes[r]["cited_by"] += 1
        if d.court_code == "kushtetuese":
            quashed, inval = negativi_dal_dispositivo(d.dispositif or "")
            nodes[k]["quashes"] = quashed              # anche se il vendim GjL non è (ancora) nel corpus
            nodes[k]["invalidates"] = inval
            for r in quashed:
                if r in nodes and r != k:
                    nodes[r]["quashed_by"].append(k)
    return {"nodes": nodes, "n": len(nodes),
            "edges": sum(len(v["cites"]) for v in nodes.values()),
            "quashed": sum(1 for v in nodes.values() if v["quashed_by"]),
            "quashes_total": sum(len(v["quashes"]) for v in nodes.values()),
            "invalidations": sum(len(v["invalidates"]) for v in nodes.values()),
            "unifying": sum(1 for v in nodes.values() if v["unifying"])}


_INCOST: dict | None = None


def norme_incostituzionali() -> dict:
    """(codice del corpus, numero di articolo) → chiave del vendim Kushtetuese che l'ha dichiarato
    incostituzionale. La legge «108/2014» diventa il codice del corpus attraverso gli alias per
    numero/anno del verificatore (`_LAW_NUMBER_ALIASES`); i codici principali per nome."""
    global _INCOST
    if _INCOST is not None:
        return _INCOST
    out: dict = {}
    try:
        from .citation_verifier import _LAW_NUMBER_ALIASES
        for k, v in (load().get("nodes") or {}).items():
            for inv in v.get("invalidates") or []:
                law = inv.get("law") or ""
                code = _LAW_NUMBER_ALIASES.get(law) or _LAW_NUMBER_ALIASES.get(law.split("/")[0])
                if not code:
                    continue
                for n in inv.get("articles") or []:
                    out.setdefault((code, str(n)), {"key": k, "partial": bool(inv.get("partial")),
                                                    "text": (inv.get("text") or "")[:200]})
    except Exception:  # noqa: BLE001
        log.warning("case_graph: norme incostituzionali non mappate", exc_info=True)
    _INCOST = out
    return out


_RX_NOTE_GJK = re.compile(r"vendimi?n?\w*\s+(?:e|të)?\s*Gjykat[ëe]s\s+Kushtetuese|Gjykat[ëe]s\s+Kushtetuese\s+nr", re.I)


def stato_incostituzionale(article) -> tuple[str, str] | None:
    """Per un articolo del corpus: None (non toccato) o (livello, chiave GjK) con livello
    «konsoliduar» (il testo QBZ porta già la nota «…me vendimin e Gjykatës Kushtetuese nr. …»:
    ciò che teniamo è GIÀ il testo dopo la decisione — nessun allarme, solo informazione),
    «pjesërisht» (una parte del nen, e il testo NON porta la nota: verificare quali punti) o
    «tërësisht» (l'intero nen, senza nota nel testo: non applicarlo come norma in vigore)."""
    hit = norme_incostituzionali().get((getattr(article, "code", ""), str(getattr(article, "number", "")).split("/")[0]))
    if not hit:
        return None
    txt = (getattr(article, "heading", "") or "") + " " + (getattr(article, "note", "") or "") + " " + (getattr(article, "body", "") or "")   # v9.362: la nota GjK sta nel campo `note`
    if _RX_NOTE_GJK.search(txt) or getattr(article, "repealed", False):
        return "konsoliduar", hit["key"]
    return ("pjesërisht" if hit["partial"] else "tërësisht"), hit["key"]


def dispositivo_incostituzionale(code: str, number) -> str:
    """La frase del dispositivo («Shfuqizimin e fjalisë së dytë në pikën 8 të nenit 10…»), per dire
    QUALE parte è caduta."""
    hit = norme_incostituzionali().get((code, str(number).split("/")[0]))
    return (hit or {}).get("text") or ""


def annullati_gjl() -> dict[str, str]:
    """«00-AAAA-N» → chiave della decisione Kushtetuese che l'ha annullato — anche per vendime GjL
    NON nel corpus (il verificatore delle sentenze può così avvisare su un numero citato)."""
    out: dict[str, str] = {}
    for k, v in (load().get("nodes") or {}).items():
        for q in v.get("quashes") or []:
            out[q.split("|")[2]] = k
    return out


# ── runtime ──────────────────────────────────────────────────────────────────
_GRAPH: dict | None = None


def path() -> Path:
    from .config import INDEX_PATH
    return Path(INDEX_PATH) / "case_graph.json"


def load() -> dict:
    global _GRAPH
    if _GRAPH is None:
        try:
            p = path()
            _GRAPH = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {"nodes": {}}
        except Exception:  # noqa: BLE001
            log.warning("case_graph: non caricato", exc_info=True)
            _GRAPH = {"nodes": {}}
    return _GRAPH


def info(court_code: str, year, number) -> dict | None:
    return (load().get("nodes") or {}).get(key(court_code, year, number))


def nota(court_code: str, year, number, lang: str = "sq") -> str:
    """Una riga per il prompt / il badge: autorità e trattamento negativo."""
    i = info(court_code, year, number)
    if not i:
        return ""
    parts = []
    if i.get("quashed_by"):
        q = i["quashed_by"][0].split("|")
        parts.append(("⚠ ANNULLATA dalla Corte costituzionale (vendim nr. %s/%s): non citarla come precedente valido"
                      if lang == "it" else
                      "⚠ E SHFUQIZUAR nga Gjykata Kushtetuese (vendimi nr. %s/%s): mos e cito si precedent të vlefshëm") % (q[2], q[1]))
    if i.get("unifying"):
        parts.append("Kolegjet e Bashkuara — vendim unifikues (forcë detyruese për kolegjet)" if lang != "it"
                     else "Sezioni Unite (Kolegjet e Bashkuara) — decisione unificatrice, vincolante per i collegi")
    if i.get("cited_by"):
        parts.append((f"cituar nga {i['cited_by']} vendime të tjera" if lang != "it" else f"citata da {i['cited_by']} altre decisioni"))
    return "; ".join(parts)
