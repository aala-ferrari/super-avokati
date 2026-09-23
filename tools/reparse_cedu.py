#!/usr/bin/env python3
"""Re-parse dei precedenti CEDU (Gjykata Evropiane e të Drejtave të Njeriut, kundër Shqipërisë) — un documento alla
volta, con metadati UFFICIALI da HUDOC, traduzione albanese ufficiale quando esiste, verifica e caricamento.

Perché (audit 22 set 2026): i 424 record CEDU erano i primi 8.000 caratteri della pagina HUDOC in inglese (l'operativo
restava fuori in 410), 224 non erano decisioni (167 comunicazioni di cause pendenti, 36 risoluzioni del Comitato dei
Ministri, 21 Information Note), 150 senza data, esiti da un enum inglese tradotto a caso.

Fonte di verità per i metadati: l'API pubblica di HUDOC (`hudoc.echr.coe.int/app/query/results`, campi appno, kpdate,
docname, doctype, documentcollectionid2, conclusion, article, violation, nonviolation, ecli). Testi: il corpo HTML
già scaricato (`ecthr_albania/<anno>/<itemid>.html`) e, quando c'è, la traduzione albanese (`languageisocode:ALB`)
scaricata in `ecthr_albania/alb/<itemid>.html`.

Regole: entrano SOLO sentenze (JUDGMENTS) e decisioni (DECISIONS); comunicazioni, risoluzioni CM, Information Note
sono ESCLUSE (non decidono nulla). Esito dai metadati: shkelje → pranim, pa shkelje → rrëzim, entrambi → pjesërisht,
e papranueshme → papranueshme, hequr nga lista → pushim, zgjidhje miqësore → marrëveshje; l'etichetta letterale sta
fra parentesi quadre in testa al dispositivo, come per la Gjykata e Lartë.

Modalità: probe (nulla scritto) · run (uno per uno: riga in data/processed/cedu_decisions_v2.jsonl, poi pickle
ricostruito da AL + CEDU) · one <itemid> · report · rebuild.
Variabili: RAW_DIR, OUT_JSONL, AL_JSONL, OUT_PKL, OLD_PKL, VERDICTS, ONLY (prefisso itemid), LIMIT, NO_ALB=1.
"""
from __future__ import annotations

import collections
import html as htmlmod
import json
import os
import pickle
import re
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

sys.path.insert(0, "/app")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

RAW = Path(os.environ.get("RAW_DIR", "/app/data/raw/jurisprudence")) / "ecthr_albania"
META_DIR = RAW / "_meta"
ALB_DIR = RAW / "alb"
OUT_JSONL = Path(os.environ.get("OUT_JSONL", "/app/data/processed/cedu_decisions_v2.jsonl"))
AL_JSONL = Path(os.environ.get("AL_JSONL", "/app/data/processed/al_decisions_v2.jsonl"))
OUT_PKL = Path(os.environ.get("OUT_PKL", "/app/data/index/bm25_decisions_v2.pkl"))
OLD_PKL = Path(os.environ.get("OLD_PKL", "/app/data/index/bm25_decisions.pkl"))
VERDICTS = Path(os.environ.get("VERDICTS", "/tmp/reparse_cedu_verdicts.jsonl"))
FIELDS = ("court_code", "court_title_sq", "court_short_sq", "year", "number", "date", "citation", "short_id",
          "objekti", "kerkues", "subjekte_interesuara", "baza_ligjore", "judges", "cited_articles", "outcome",
          "dispositif", "reasoning", "source_file", "source_url", "kind")
COURT_TITLE = "Gjykata Evropiane e të Drejtave të Njeriut"
COURT_SHORT = "GJEDNJ"
HUDOC = "https://hudoc.echr.coe.int/app/query/results"
SELECT = "itemid,docname,doctype,documentcollectionid2,kpdate,appno,languageisocode,conclusion,article,violation,nonviolation,ecli,respondent,importance"
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36", "Accept": "application/json, text/html;q=0.9, */*;q=0.8", "Accept-Language": "en-GB,en;q=0.9"}
_last_call = [0.0]


def _sleep():
    d = time.time() - _last_call[0]
    if d < 0.5:
        time.sleep(0.5 - d)
    _last_call[0] = time.time()


def hudoc_query(query: str, length: int = 10) -> dict:
    for attempt in range(3):
        try:
            _sleep()
            url = HUDOC + "?" + urllib.parse.urlencode({"query": query, "select": SELECT, "sort": "", "start": 0, "length": length})
            return json.load(urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=60))
        except Exception as exc:  # noqa: BLE001
            if attempt == 2:
                raise
            time.sleep(3 * (attempt + 1))
    return {}


def hudoc_body_html(itemid: str) -> str:
    _sleep()
    url = f"https://hudoc.echr.coe.int/app/conversion/docx/html/body?library=ECHR&id={itemid}&filename=x.html"
    return urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=90).read().decode("utf-8", "replace")


def html_to_text(raw: str) -> str:
    raw = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", raw)
    raw = re.sub(r"(?i)<br\s*/?>|</p>|</div>|</tr>|</h\d>|</li>", "\n", raw)
    raw = re.sub(r"(?s)<[^>]+>", " ", raw)
    raw = htmlmod.unescape(raw).replace("\xa0", " ").replace("‑", "-")
    raw = re.sub(r"[ \t]+", " ", raw)
    raw = re.sub(r" *\n *", "\n", raw)
    raw = re.sub(r"\n{2,}", "\n", raw)
    # intestazioni di pagina ripetute («VENDIMI LULI KUNDËR SHQIPËRISË» a ogni pagina nelle traduzioni da PDF)
    lines = raw.split("\n")
    cnt = collections.Counter(ln.strip() for ln in lines if 6 <= len(ln.strip()) <= 100)
    rep = {ln for ln, c in cnt.items() if c >= 3 and not re.match(r"^\d+\.", ln) and not re.search(r"[.;:!?»”)]$", ln)}
    if rep:
        lines = [ln for ln in lines if ln.strip() not in rep]
    return "\n".join(lines).strip()


OFFLINE = bool(os.environ.get("HUDOC_OFFLINE"))   # nel container il WAF di HUDOC risponde 403: la cache la riempie l'host


def meta_for(itemid: str) -> dict | None:
    META_DIR.mkdir(exist_ok=True)
    p = META_DIR / f"{itemid}.json"
    if p.exists():
        return json.loads(p.read_text(encoding="utf-8")) or None
    if OFFLINE:
        return None
    r = hudoc_query(f"itemid:{itemid}", 1)
    res = (r.get("results") or [])
    m = res[0]["columns"] if res else {}
    p.write_text(json.dumps(m, ensure_ascii=False), encoding="utf-8")
    return m or None


def alb_version(appno: str, coll: str) -> dict | None:
    """La traduzione albanese ufficiale (HUDOC languageisocode ALB) del caso: preferita quella integrale (non «summary»)."""
    if os.environ.get("NO_ALB"):
        return None
    META_DIR.mkdir(exist_ok=True); ALB_DIR.mkdir(exist_ok=True)
    first = (appno or "").split(";")[0].strip()
    if not first:
        return None
    cache = META_DIR / ("alb_" + first.replace("/", "_") + ".json")
    if cache.exists():
        d = json.loads(cache.read_text(encoding="utf-8"))
        if d and "summary" in (d.get("docname") or "").lower():
            return None            # un «[Albanian Translation] summary» è un riassunto, non il testo: si resta sull'originale
        return d or None
    if OFFLINE:
        return None
    r = hudoc_query(f"(appno:{first}) AND (languageisocode:ALB) AND (documentcollectionid2:{coll})", 10)
    cands = [x["columns"] for x in (r.get("results") or []) if (x["columns"].get("appno") or "").split(";")[0].strip() == first]
    cands = [c for c in cands if "summary" not in (c.get("docname") or "").lower()]
    chosen = None
    best_len = 0
    for c in cands[:3]:
        iid = c["itemid"]
        f = ALB_DIR / f"{iid}.html"
        if not f.exists():
            try:
                f.write_text(hudoc_body_html(iid), encoding="utf-8")
            except Exception:  # noqa: BLE001
                continue
        n = len(html_to_text(f.read_text(encoding="utf-8")))
        if n > best_len:
            best_len, chosen = n, dict(c, chars=n, file=str(f.relative_to(RAW.parent)))
    cache.write_text(json.dumps(chosen or {}, ensure_ascii=False), encoding="utf-8")
    return chosen


# ── classificazione ────────────────────────────────────────────────────────

def classify(meta: dict) -> tuple[str, str]:
    """→ (kind, exclude_reason)"""
    coll = (meta.get("documentcollectionid2") or "").upper()
    dt = (meta.get("doctype") or "").upper()
    if "JUDGMENTS" in coll or dt.startswith("HEJUD") or dt.startswith("HFJUD"):
        return "judgment", ""
    if "DECISIONS" in coll or dt.startswith("HEDEC") or dt.startswith("HFDEC"):
        return "decision", ""
    if "COMMUNICATEDCASES" in coll or dt.startswith("HECOM"):
        return "communicated", "komunikim i një çështjeje në pritje (asnjë vendim)"
    if "RESOLUTIONS" in coll or "RES" in dt:
        return "resolution", "rezolutë e Komitetit të Ministrave (jo vendim i Gjykatës)"
    if "CLIN" in coll or dt == "CLIN":
        return "note", "Information Note / përmbledhje ligjore (jo teksti i vendimit)"
    return "?", f"tipo sconosciuto: {coll} / {dt}"


_ART_RX = re.compile(r"^(?:P(\d+)-)?(\d+)(?:-(\d+))?(?:-([a-z]))?$")


def art_label(code: str) -> str:
    """«6-1» → «neni 6 § 1», «6-3-c» → «neni 6 § 3 (c)», «P1-1» → «neni 1 i Protokollit 1», «P1-1-1» → «neni 1 § 1 i Protokollit 1»."""
    m = _ART_RX.match(code.strip())
    if not m:
        return code
    prot, art, para, let = m.groups()
    s = f"neni {art}"
    if para:
        s += f" § {para}"
    if let:
        s += f" ({let})"
    if prot:
        s += f" i Protokollit {prot}"
    return s


def split_arts(field: str) -> list[str]:
    out: list[str] = []
    for tok in re.split(r"[;]", field or ""):
        for a in tok.split("+"):
            a = a.strip()
            if a and a not in out:
                out.append(a)
    return out


def outcome_from_meta(meta: dict, kind: str) -> tuple[str, str]:
    """→ (outcome nel vocabolario dell'indice, etichetta letterale in shqip)."""
    concl = (meta.get("conclusion") or "")
    low = concl.lower()
    viol = [a for a in split_arts(meta.get("violation") or "") if not re.search(r"-\d+$", a) or True]
    nonv = split_arts(meta.get("nonviolation") or "")
    viol_l = [art_label(a) for a in viol if a not in ("41", "46")]
    nonv_l = [art_label(a) for a in nonv]
    # articoli con sotto-paragrafo doppio («P1-1-1») restano; dedup per etichetta
    viol_l = list(dict.fromkeys(viol_l)); nonv_l = list(dict.fromkeys(nonv_l))
    if "friendly settlement" in low or "règlement amiable" in low:
        return "marrëveshje", "hequr nga lista: zgjidhje miqësore"
    if kind == "decision":
        if "struck out" in low or "radiation" in low:
            return "pushim", "hequr nga lista"
        if low.startswith("inadmissible") or "inadmissible" in low and "admissible" not in low.replace("inadmissible", ""):
            return "papranueshme", "e papranueshme"
        if "partly inadmissible" in low or "partly admissible" in low:
            return "pranim", "pjesërisht e pranueshme"
        if "admissible" in low:
            return "pranim", "e pranueshme"
        if "irrecevable" in low:
            return "papranueshme", "e papranueshme"
        return "", ""
    # sentenze
    if viol_l and nonv_l:
        return "pjesërisht", "shkelje: " + ", ".join(viol_l) + " · pa shkelje: " + ", ".join(nonv_l)
    if viol_l:
        return "pranim", "shkelje: " + ", ".join(viol_l)
    if nonv_l:
        return "rrëzim", "pa shkelje: " + ", ".join(nonv_l)
    if "struck out" in low or "radiation" in low:
        return "pushim", "hequr nga lista"
    if "just satisfaction" in low or "damage - award" in low or "satisfaction équitable" in low:
        return "pranim", "shpërblim i drejtë (neni 41)"
    if "revision" in low:
        return "ndryshim", "rishikim i vendimit"
    if "inadmissible" in low and "violation" not in low:
        return "papranueshme", "e papranueshme"
    return "", ""


def outcome_from_operative(oper: str, kind: str) -> tuple[str, str]:
    """Quando HUDOC non ha compilato «conclusion» (decisioni vecchie o recenti): l'esito si legge dall'operativo."""
    low = (oper or "").lower()
    if not low:
        return "", ""
    if "strike" in low or "struck" in low or "radi" in low or "heq" in low and "list" in low:
        if "friendly settlement" in low or "article 39" in low or "règlement amiable" in low or "zgjidhje miqësore" in low:
            return "marrëveshje", "hequr nga lista: zgjidhje miqësore"
        return "pushim", "hequr nga lista"
    viol = bool(re.search(r"has been a violation|there has been a breach|y a eu violation|ka pasur shkelje", low))
    nonv = bool(re.search(r"has been no violation|no violation of|n.y a pas eu violation|nuk ka pasur shkelje", low))
    if kind == "judgment":
        if viol and nonv: return "pjesërisht", "shkelje e pjesshme (nga operativi)"
        if viol: return "pranim", "shkelje (nga operativi)"
        if nonv: return "rrëzim", "pa shkelje (nga operativi)"
        if "just satisfaction" in low or "pecuniary damage" in low or "shpërblim" in low: return "pranim", "shpërblim i drejtë (neni 41)"
        return "", ""
    if re.search(r"declares? (?:the (?:application|remainder|complaints?)[^.]{0,80})?inadmissible|irrecevable|papranueshme", low):
        if re.search(r"declares? [^.]{0,80}admissible(?! ?\w)", low.replace("inadmissible", "")):
            return "pranim", "pjesërisht e pranueshme"
        return "papranueshme", "e papranueshme"
    if re.search(r"declares? [^.]{0,80}\badmissible|recevable|e pranueshme", low):
        return "pranim", "e pranueshme"
    return "", ""


# ── testo: intestazioni, sezioni ───────────────────────────────────────────

LAW_EN = re.compile(r"^\s*(?:[IVX]+\.\s*)?(?:THE LAW|AS TO THE LAW|THE COURT.S ASSESSMENT|LAW)\s*$", re.M)
LAW_FR = re.compile(r"^\s*(?:[IVX]+\.\s*)?EN DROIT\s*$", re.M)
LAW_SQ = re.compile(r"^\s*(?:[IVX]+\.\s*)?(?:LIGJI|E DREJTA|NË LIGJ|SA I PËRKET LIGJIT|VLERËSIMI I GJYKATËS)\s*$", re.M)
LAW_SQ_ALT = re.compile(r"^\s*[IVX]+\.\s*(?:KUNDËRSHTIM\w*\s+PARAPRAK\w*|SHKELJ\w* E PRETENDUAR\w*|PRETENDIM\w* PËR SHKELJE|SHKELJET E PRETENDUARA|SHKELJE\w*\s+T[ËE]\s+PRETENDUAR\w*)", re.M)
# l'operativo sta a INIZIO RIGA: un «Për këto arsye, Gjykata hedh poshtë kundërshtimin…» dentro un paragrafo del
# ragionamento non lo è (Beshiri, traduzione shqip); le decisioni recenti lo scrivono in minuscolo («For these reasons, the Court, unanimously,»)
OPER_EN = re.compile(r"^[ ]*(?:FOR THESE REASONS|For these reasons)\b", re.M)
OPER_FR = re.compile(r"^[ ]*(?:PAR CES MOTIFS|Par ces motifs)\b", re.M)
OPER_SQ = re.compile(r"^[ ]*(?:P[ËE]RK?\s+K[ËE]TO\s+ARSYE|Për këto arsye)\b", re.M)   # anche il refuso «PËRK KËTO ARSYE» (Luli)
OPER_END = re.compile(r"\n\s*(?:Done in (?:English|French)|Fait en (?:anglais|français)|Bërë në (?:anglisht|frëngjisht)|Hartuar në|In accordance with Article 45|Në përputhje me Nenin 45|Conformément à l.article 45|ANNEX|SHTOJCA|ANNEXE|Registrar\b|Sekretar\b|Greffi)", re.I)
FACTS_EN = re.compile(r"^\s*(?:[IVX]+\.\s*)?(?:THE FACTS|THE CIRCUMSTANCES OF THE CASE|EN FAIT|FAKTET|RRETHANAT E ÇËSHTJES)\s*$", re.M)


def judges_of(text: str) -> list[str]:
    m = re.search(r"(?:composed of|composée de|e përbërë nga|i përbërë nga|përbërë nga)\s*:?\s*\n", text[:6000], re.I)
    if not m:
        return []
    block = text[m.end(): m.end() + 1500]
    stop = re.search(r"\n[^\n]*(?:Registrar|greffi|Sekretar|Registr)[^\n]*\n", block, re.I)
    if stop:
        block = block[:stop.start()]
    names: list[str] = []
    for ln in block.split("\n"):
        s = re.sub(r"\b(?:President|Présidente?|Kryetar\w*|judges?|juges?|gjyqtar\w*|ad hoc judge|juge ad hoc|and|et|dhe)\b", " ", ln, flags=re.I)
        s = re.sub(r"[,;]+", " ", s).strip()
        toks = [t for t in s.split() if t[:1].isupper() or t[:1] in "ÇËÉÁÜÖ"]
        if 2 <= len(toks) <= 5 and not re.search(r"\d", s) and "Section" not in s:
            nm = " ".join(toks)
            if nm not in names:
                names.append(nm)
    return names[:17]


def cut_operative(text: str, rx: re.Pattern) -> str:
    m = rx.search(text)
    if not m:
        return ""
    # se ce n'è più d'uno a inizio riga (rarissimo), vale l'ULTIMO: l'operativo chiude il documento
    ms = list(rx.finditer(text))
    m = ms[-1] if ms else m
    seg = text[m.start(): m.start() + 6000]
    e = OPER_END.search(seg, 40)
    if e:
        seg = seg[:e.start()]
    seg = re.sub(r"\s+", " ", seg).strip()
    return seg[:3000]


def law_section(text: str, lang: str) -> tuple[str, str]:
    """(ragionamento, come_trovato). La sezione «THE LAW» (o equivalente) fino all'operativo."""
    oper = (OPER_SQ if lang == "sq" else OPER_FR if lang == "fr" else OPER_EN).search(text)
    end = oper.start() if oper else len(text)
    rx = LAW_SQ if lang == "sq" else LAW_FR if lang == "fr" else LAW_EN
    facts = [m.start() for m in FACTS_EN.finditer(text)]
    start_min = facts[0] if facts else 0
    cands = [m for m in rx.finditer(text) if start_min <= m.start() < end]
    if cands:
        return text[cands[-1].start() if lang != "sq" else cands[0].start(): end].strip(), "heading"
    if lang == "sq":
        cands = [m for m in LAW_SQ_ALT.finditer(text) if start_min <= m.start() < end]
        if cands:
            return text[cands[0].start(): end].strip(), "heading-alt"
    # decisioni nuove: «THE COURT’S ASSESSMENT» già coperto; vecchie decisioni: «THE LAW» assente → «COMPLAINTS» poi «THE LAW»?
    m = re.search(r"^\s*(?:[IVX]+\.\s*)?(?:COMPLAINTS?|GRIEFS|ANKESAT?)\s*$", text, re.M)
    if m and m.start() < end:
        return text[m.start(): end].strip(), "complaints"
    return "", ""


DOMESTIC_EN = re.compile(r"Article\s+(\d+[a-z]?)\s*(?:§\s*\d+\s*)?(?:\([a-z]\)\s*)?of\s+the\s+(Civil Code|Code of Civil Procedure|Criminal Code|Code of Criminal Procedure|Constitution|Family Code|Labour Code|Code of Administrative Procedure)", re.I)
DOMESTIC_MAP = {"civil code": "kodi_civil", "code of civil procedure": "kodi_proc_civile", "criminal code": "kodi_penal",
                "code of criminal procedure": "kodi_proc_penale", "constitution": "kushtetuta", "family code": "kodi_familjes",
                "labour code": "kodi_punes", "code of administrative procedure": "kodi_proc_admin"}


def domestic_articles(text: str, lang: str, aidx) -> list[str]:
    out: list[str] = []
    if aidx is None:
        return out
    keys = {(a.code, str(a.number)) for a in aidx.articles}
    if lang == "sq":
        try:
            from src.citation_verifier import verify_text
            res = verify_text(text[:150_000], aidx)
            for ct in (res.get("citations") or []):
                code = getattr(ct, "code", None); num = getattr(ct, "number", None); st = getattr(ct, "status", "")
                if code and num and st in ("verified", "repealed", "stale") and f"{code}:{num}" not in out:
                    out.append(f"{code}:{num}")
        except Exception:  # noqa: BLE001
            pass
        return out[:40]
    for m in DOMESTIC_EN.finditer(text):
        code = DOMESTIC_MAP.get(m.group(2).lower()); num = m.group(1).lower()
        if code and (code, num) in keys and f"{code}:{num}" not in out:
            out.append(f"{code}:{num}")
    return out[:40]


def detect_lang(text: str) -> str:
    s = text[:8000]
    sq = len(re.findall(r"\b(dhe|të|së|nga|për|gjykata|nenit|neni|ankues\w*)\b", s, re.I))
    en = len(re.findall(r"\b(the|of|and|court|applicant)\b", s, re.I))
    fr = len(re.findall(r"\b(le|la|les|des|cour|requérant\w*)\b", s, re.I))
    best = max(("sq", sq), ("en", en), ("fr", fr), key=lambda kv: kv[1])
    return best[0] if best[1] > 15 else "?"


def case_name(meta: dict, alb_text: str | None) -> str:
    if alb_text:
        m = re.search(r"^\s*ÇËSHTJA\s+(.+?)\s*$", alb_text[:600], re.M)
        if m:
            s = re.sub(r"[“”\"«»]", "", m.group(1)).strip()
            s = re.sub(r"\s+K\.\s+", " KUNDËR ", s)
            return s.title().replace(" Kundër ", " kundër ").replace(" Dhe ", " dhe ").replace(" Etj.", " etj.")
    dn = meta.get("docname") or ""
    dn = re.sub(r"^\s*(?:CASE OF|AFFAIRE)\s+", "", dn, flags=re.I)
    dn = re.sub(r"\s+\[.*?\]\s*$", "", dn)
    dn = re.sub(r"[“”\"«»]", "", dn)
    dn = re.sub(r"\s+(?:v\.|c\.|against|contre)\s+", " kundër ", dn, flags=re.I)
    dn = dn.replace("ALBANIA", "Shqipërisë").replace("ALBANIE", "Shqipërisë").replace("L'Shqipërisë", "Shqipërisë")
    out = dn.title().replace(" Kundër ", " kundër ").replace(" And ", " and ").replace(" Dhe ", " dhe ").replace(" Of ", " of ").replace(" The ", " the ")
    return out.replace("Shqipërisë", "Shqipërisë").strip()


def parse_one(itemid: str, rel: str, text_en: str, meta: dict, old: dict | None, aidx) -> tuple[dict | None, dict]:
    v = {"status": "OK", "reasons": [], "warnings": [], "checks": {}, "lang": "en", "alb": None}
    if not meta:
        v["status"] = "FAIL"; v["reasons"].append("metadati HUDOC mancanti (cache vuota: lanciare hudoc_fetch.py sull'host)"); v["kind"] = "?"
        return None, v
    kind, excl = classify(meta)
    v["kind"] = kind
    if excl:
        v["status"] = "EXCLUDE"; v["reasons"].append(excl); return None, v
    appno = (meta.get("appno") or "").strip()
    kp = (meta.get("kpdate") or "")[:10]
    date = f"{kp[8:10]}.{kp[5:7]}.{kp[0:4]}" if re.match(r"^\d{4}-\d{2}-\d{2}", kp) else ""
    year = int(kp[:4]) if kp[:4].isdigit() else 0
    if not appno: v["status"] = "FAIL"; v["reasons"].append("numero di ricorso mancante nei metadati")
    if not date: v["status"] = "FAIL"; v["reasons"].append("data mancante nei metadati")
    outcome, label = outcome_from_meta(meta, kind)
    # testo: albanese ufficiale se c'è e ha struttura, altrimenti inglese/francese
    coll = "JUDGMENTS" if kind == "judgment" else "DECISIONS"
    alb = None
    try:
        alb = alb_version(appno, coll)
    except Exception as exc:  # noqa: BLE001
        v["warnings"].append(f"HUDOC ALB non interrogabile ({exc})")
    text, lang, src_used = text_en, detect_lang(text_en), rel
    # v9.369: la traduzione deve essere DELLO STESSO documento — stessa collezione (sentenza/decisione) e stessa data.
    # Cercandola per numero di ricorso, 5 record avevano preso il testo albanese di un'altra decisione sullo stesso
    # ricorso (merito ↔ equa soddisfazione, ammissibilità ↔ sentenza)
    if alb and alb.get("file"):
        _same_coll = ("JUDGMENTS" in (alb.get("documentcollectionid2") or "")) == (kind == "judgment")
        _same_date = (alb.get("kpdate") or "")[:10] == (meta.get("kpdate") or "")[:10]
        if not (_same_coll and _same_date):
            v["warnings"].append(f"traduzione shqip {alb.get('itemid')} di un altro documento dello stesso ricorso ({(alb.get('kpdate') or '')[:10]}): usato l'originale")
            alb = None
    if alb and alb.get("file"):
        t_alb = html_to_text((RAW.parent / alb["file"]).read_text(encoding="utf-8"))
        reas_alb, how = law_section(t_alb, "sq")
        oper_alb = cut_operative(t_alb, OPER_SQ)
        if len(reas_alb) >= 500 and len(oper_alb) >= 20:
            text, lang, src_used = t_alb, "sq", alb["file"]; v["alb"] = alb["itemid"]; v["checks"]["alb_struttura"] = how
        else:
            v["warnings"].append(f"traduzione shqip {alb['itemid']} senza struttura (ragionamento {len(reas_alb)}, operativo {len(oper_alb)}): usato l'originale")
    v["lang"] = lang
    if lang == "?":
        v["status"] = "FAIL"; v["reasons"].append("lingua del testo non riconosciuta")
    reasoning, how = law_section(text, "sq" if lang == "sq" else "fr" if lang == "fr" else "en")
    oper = cut_operative(text, OPER_SQ if lang == "sq" else OPER_FR if lang == "fr" else OPER_EN)
    v["checks"]["law_section"] = how or False
    if not outcome:
        # «conclusion» vuota nei metadati (succede): l'esito si legge dall'operativo, dichiarandolo nell'etichetta
        outcome, label = outcome_from_operative(oper, kind)
        if outcome: v["warnings"].append("esito letto dall'operativo (metadati HUDOC senza conclusione)")
    if not outcome:
        v["status"] = "FAIL"; v["reasons"].append(f"esito non riconosciuto: conclusione «{(meta.get('conclusion') or '')[:100]}», operativo «{oper[:100]}»")
    if not reasoning and len(oper) >= 20:
        # decisioni di comitato senza intestazioni maiuscole: dal fine della composizione (riga «Registrar») all'operativo
        m_reg = re.search(r"\n[^\n]*(?:Registrar|Sekretar|greffi)[^\n]*\n", text[:6000], re.I)
        om = (OPER_SQ if lang == "sq" else OPER_FR if lang == "fr" else OPER_EN).search(text)
        if m_reg and om and om.start() > m_reg.end():
            reasoning = text[m_reg.end(): om.start()].strip(); v["checks"]["law_section"] = "composizione→operativo"
            v["warnings"].append("sezione del diritto non delimitata: preso il testo dalla composizione all'operativo")
    min_reas = 150 if outcome in ("pushim", "marrëveshje") else 500      # le radiazioni dal ruolo hanno due paragrafi
    if len(reasoning) < min_reas:
        v["status"] = "FAIL"; v["reasons"].append(f"sezione del diritto non trovata o corta ({len(reasoning)} chr)")
    if len(oper) < 20:
        v["status"] = "FAIL"; v["reasons"].append("operativo («FOR THESE REASONS») non trovato")
    if "<" in reasoning and ">" in reasoning:
        v["status"] = "FAIL"; v["reasons"].append("residui HTML nel testo")
    judges = judges_of(text) or judges_of(text_en)
    if len(judges) < 3: v["warnings"].append(f"giudici trovati: {len(judges)}")
    conv = ["convention:" + a for a in split_arts(meta.get("article") or "")]
    dom = domestic_articles(text, lang, aidx)
    cited = (dom + conv)[:60]
    if not conv: v["warnings"].append("nessun articolo della Konventa nei metadati")
    name = case_name(meta, text if lang == "sq" else None)
    applicant = re.split(r"\s+kundër\s+", name)[0].strip()
    old_obj = (old or {}).get("objekti") or ""
    concl = (meta.get("conclusion") or "").replace(";", "; ")
    objekti = (old_obj.strip() + " · " if old_obj.strip() else "") + (f"{name}: {concl}" if concl else name)
    objekti = objekti[:1200]
    if old and str(old.get("number") or "").replace(" ", "") != appno.replace(" ", ""):
        v["warnings"].append(f"numero diverso dal record precedente ({old.get('number')} → {appno})")
    baza = "Konventa Evropiane e të Drejtave të Njeriut: " + ", ".join(art_label(a) for a in split_arts(meta.get("article") or "")) if conv else ""
    kind_sq = "Vendim (aktgjykim)" if kind == "judgment" else "Vendim mbi pranueshmërinë"
    citation = f"{name}, GJEDNJ, kërkesa nr. {appno}, {date}" + (" (përkthim zyrtar shqip)" if lang == "sq" else "")
    disp = f"[{label}] {oper}" if label else oper
    if lang != "sq":
        disp = f"[{label} · teksti në {'anglisht' if lang == 'en' else 'frëngjisht'}] {oper}" if label else oper
    rec = {
        "court_code": "ecthr_albania", "court_title_sq": COURT_TITLE, "court_short_sq": COURT_SHORT, "year": year,
        "number": appno, "date": date, "citation": citation, "short_id": itemid + (f"|alb:{v['alb']}" if v["alb"] else ""),
        "objekti": objekti, "kerkues": applicant, "subjekte_interesuara": "Republika e Shqipërisë (Qeveria)",
        "baza_ligjore": (kind_sq + " · " + baza)[:1500], "judges": judges, "cited_articles": cited, "outcome": outcome,
        "dispositif": disp, "reasoning": reasoning[:200_000], "source_file": src_used,
        "source_url": f"https://hudoc.echr.coe.int/eng?i={itemid}", "kind": "decision",
    }
    c = v["checks"]
    c["objekti"] = len(objekti) >= 8; c["reasoning"] = len(reasoning) >= 500; c["operative"] = len(oper) >= 20
    c["outcome"] = bool(outcome); c["judges"] = len(judges) >= 3; c["conv_articles"] = bool(conv)
    c["reasoning_mentions_court"] = bool(re.search(r"\b(?:Court|Gjykata|Cour)\b", reasoning))
    if v["status"] == "OK" and not c["reasoning_mentions_court"]:
        v["status"] = "FAIL"; v["reasons"].append("il ragionamento non nomina mai la Corte")
    return rec, v


# ── store ──────────────────────────────────────────────────────────────────

def old_records() -> dict:
    with OLD_PKL.open("rb") as fh:
        decs = pickle.load(fh)["decisions"]
    out = {}
    for d in decs:
        if d.get("court_code") != "ecthr_albania":
            continue
        s = (d.get("source_file") or "").replace("\\", "/")
        m = re.search(r"(00[12]-\d+)\.html", s)
        if m:
            out[m.group(1)] = dict(d)
    return out


def documents() -> list[tuple[str, str]]:
    out = []
    only = os.environ.get("ONLY", "")
    for p in sorted(RAW.rglob("*.html")):
        if any(part in ("_cache", "_meta", "alb") for part in p.parts):
            continue
        m = re.match(r"^(00[12]-\d+)\.html$", p.name)
        if not m:
            continue
        iid = m.group(1)
        if only and not iid.startswith(only):
            continue
        out.append((iid, str(p.relative_to(RAW.parent))))
    lim = int(os.environ.get("LIMIT", "0") or 0)
    return out[:lim] if lim else out


def _article_index():
    try:
        from src.retrieval import ArticleIndex
        return ArticleIndex.load()
    except Exception as exc:  # noqa: BLE001
        print("indice articoli non disponibile:", exc); return None


def _text_en(rel: str) -> str:
    return html_to_text((RAW.parent / rel).read_text(encoding="utf-8", errors="replace"))


def rebuild_pickle():
    from src.jurisprudence_parser import Decision
    from src.retrieval import DecisionIndex
    rows_al = [json.loads(l) for l in AL_JSONL.open(encoding="utf-8")] if AL_JSONL.exists() else []
    rows_ce = [json.loads(l) for l in OUT_JSONL.open(encoding="utf-8")] if OUT_JSONL.exists() else []
    decs = [Decision(**{k: d[k] for k in FIELDS if k != "kind"}) for d in rows_al + rows_ce]
    DecisionIndex.build(decs).save(OUT_PKL)
    return len(rows_al), len(rows_ce)


def cmd_probe():
    old = old_records(); aidx = _article_index(); docs = documents()
    st = collections.Counter(); reasons = collections.Counter(); ex = collections.defaultdict(list); warns = collections.Counter()
    langs = collections.Counter(); outs = collections.Counter(); t0 = time.time()
    out = Path(os.environ.get("PROBE_OUT", "/tmp/probe_cedu.jsonl")).open("w", encoding="utf-8")
    for n, (iid, rel) in enumerate(docs, 1):
        meta = meta_for(iid) or {}
        rec, v = parse_one(iid, rel, _text_en(rel), meta, old.get(iid), aidx)
        st[(v.get("kind"), v["status"])] += 1
        for r in v["reasons"]: reasons[r.split(":")[0][:70]] += 1; ex[r.split(":")[0][:70]].append(iid)
        for w in v["warnings"]: warns[w.split(":")[0].split("(")[0][:50]] += 1
        if v["status"] == "OK":
            langs[v["lang"]] += 1; outs[(v["kind"], rec["outcome"])] += 1
        out.write(json.dumps({"itemid": iid, "rel": rel, "kind": v.get("kind"), "status": v["status"], "reasons": v["reasons"], "warnings": v["warnings"],
                              "checks": v["checks"], "lang": v["lang"], "alb": v["alb"], "outcome": (rec or {}).get("outcome"), "number": (rec or {}).get("number"),
                              "date": (rec or {}).get("date"), "len_reasoning": len((rec or {}).get("reasoning") or ""), "n_judges": len((rec or {}).get("judges") or []),
                              "disp": ((rec or {}).get("dispositif") or "")[:160], "citation": (rec or {}).get("citation")}, ensure_ascii=False) + "\n")
        if n % 50 == 0: print(f"  … {n}/{len(docs)} ({int(time.time() - t0)} s)", flush=True)
    out.close()
    print("\nSTATO (tipo, esito):"); [print(f"  {c:4d}  {k}") for k, c in sorted(st.items(), key=lambda kv: (str(kv[0][0]), kv[0][1]))]
    print("\nMOTIVI:"); [print(f"  {c:4d}  {k}   es. {ex[k][:4]}") for k, c in reasons.most_common()]
    print("\nAVVISI:"); [print(f"  {c:4d}  {k}") for k, c in warns.most_common(30)]
    print("\nLINGUA dei record OK:", dict(langs)); print("ESITI dei record OK:", dict(outs.most_common()))


def cmd_one(iid: str):
    old = old_records(); aidx = _article_index()
    rel = next((r for i, r in documents() if i == iid), None)
    meta = meta_for(iid) or {}
    print("meta:", json.dumps({k: meta.get(k) for k in ("docname", "doctype", "documentcollectionid2", "kpdate", "appno", "conclusion", "article", "violation", "nonviolation")}, ensure_ascii=False)[:900])
    rec, v = parse_one(iid, rel, _text_en(rel), meta, old.get(iid), aidx)
    print(json.dumps(v, ensure_ascii=False, indent=1))
    if rec:
        for k in FIELDS:
            val = rec[k]
            if isinstance(val, str) and len(val) > 600: val = val[:600] + f" … [{len(rec[k])} chr]"
            print(f"{k:22s}: {val!r}")


def cmd_run():
    old = old_records(); aidx = _article_index()
    OUT_JSONL.parent.mkdir(parents=True, exist_ok=True)
    loaded = set()
    if OUT_JSONL.exists():
        for line in OUT_JSONL.open(encoding="utf-8"):
            loaded.add(json.loads(line)["short_id"].split("|")[0])
    keys = set()
    if OUT_JSONL.exists():
        for line in OUT_JSONL.open(encoding="utf-8"):
            d = json.loads(line); keys.add((d["number"], d["date"], d["_meta"]["kind"]))
    docs = documents(); t0 = time.time(); n_ok = n_ex = n_fail = 0
    vlog = VERDICTS.open("a", encoding="utf-8")
    print(f"ripresa: {len(loaded)} già caricati")
    for n, (iid, rel) in enumerate(docs, 1):
        if iid in loaded: continue
        meta = meta_for(iid) or {}
        rec, v = parse_one(iid, rel, _text_en(rel), meta, old.get(iid), aidx)
        # v9.369: lo stesso ricorso ha spesso DUE decisioni vere (ammissibilità e poi sentenza; merito e poi equa
        # soddisfazione ex art. 41): il duplicato è solo stesso ricorso + stessa data + stesso tipo
        if v["status"] == "OK" and (rec["number"], rec["date"], v["kind"]) in keys:
            v["status"] = "EXCLUDE"; v["reasons"].append(f"duplicato del ricorso {rec['number']} ({rec['date']}) già caricato")
        vlog.write(json.dumps({"itemid": iid, "kind": v.get("kind"), "status": v["status"], "reasons": v["reasons"], "warnings": v["warnings"], "lang": v["lang"], "alb": v["alb"], "ts": time.strftime("%H:%M:%S")}, ensure_ascii=False) + "\n"); vlog.flush()
        if v["status"] != "OK":
            if v["status"] == "EXCLUDE": n_ex += 1
            else: n_fail += 1
            print(f"[{n}/{len(docs)}] {v['status']:7s} {iid} {v.get('kind')} — {'; '.join(v['reasons'])[:150]}", flush=True)
            continue
        line = dict(rec); line["_meta"] = {"warnings": v["warnings"], "checks": v["checks"], "lang": v["lang"], "alb": v["alb"], "kind": v["kind"], "ts": time.strftime("%Y-%m-%dT%H:%M:%S")}
        with OUT_JSONL.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(line, ensure_ascii=False) + "\n")
        loaded.add(iid); keys.add((rec["number"], rec["date"], v["kind"]))
        a, c = rebuild_pickle(); n_ok += 1
        print(f"[{n}/{len(docs)}] OK      {iid} {v.get('kind')} {v['lang']}{' (shqip)' if v['alb'] else ''} → {rec['citation'][:70]} | {rec['outcome']} | ragionamento {len(rec['reasoning'])} chr, giudici {len(rec['judges'])}, nene {len(rec['cited_articles'])} | db: {a} AL + {c} CEDU"
              + (f" | avvisi: {'; '.join(v['warnings'])[:100]}" if v["warnings"] else ""), flush=True)
    vlog.close()
    print(f"\nfatto in {int(time.time() - t0)} s: OK {n_ok}, esclusi {n_ex}, falliti {n_fail}")


def cmd_report():
    rows = [json.loads(l) for l in VERDICTS.open(encoding="utf-8")] if VERDICTS.exists() else []
    print("verdetti:", dict(collections.Counter((r.get("kind"), r["status"]) for r in rows)))
    for k, c in collections.Counter(x.split(":")[0][:70] for r in rows for x in r["reasons"]).most_common(): print(f"  {c:4d}  {k}")
    n = sum(1 for _ in OUT_JSONL.open(encoding="utf-8")) if OUT_JSONL.exists() else 0
    print("record CEDU nel JSONL:", n)


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "probe"
    if cmd == "probe": cmd_probe()
    elif cmd == "run": cmd_run()
    elif cmd == "one": cmd_one(sys.argv[2])
    elif cmd == "report": cmd_report()
    elif cmd == "rebuild": print(rebuild_pickle())
    else: raise SystemExit(__doc__)
