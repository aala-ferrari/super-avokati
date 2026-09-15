# -*- coding: utf-8 -*-
"""Ingest EU regulations from EUR-Lex (consolidated Italian text) into the same
JSON shape as the Normattiva acts, so build_it_index.py indexes them together.

Why: Normattiva has no EU law. The customs case (auto targata AL) turned on
artt. 212/215 Reg. delegato (UE) 2015/2446 and art. 5 CDU — the brain had to
browse for them (1.4M tokens). With the text in the corpus it reads it verbatim.

Runs on the HOST (a deploy would kill it in the container). Resume-safe:
    IT_ACTS_DIR=/var/www/apps/super-avvocato/data/processed/it_acts python3 /tmp/ingest_eurlex.py
    python3 /tmp/ingest_eurlex.py reg_ue_2015_2446      # one act only

Latest consolidated version is discovered from the "ALL" page (the CELEX with
the newest -YYYYMMDD suffix); falls back to the original act.
Markup (consolidated HTML): <p class="title-article-norm">Articolo N</p>,
<p class="stitle-article-norm">Rubrica</p>, then <p class="norm">/tables.
"""
import html as H
import json
import os
import re
import sys
import time
import urllib.request
from pathlib import Path

OUT = Path(os.environ.get("IT_ACTS_DIR", "/app/data/processed/it_acts"))
OUT.mkdir(parents=True, exist_ok=True)
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/124 Safari/537.36"

# (id, title, area, base CELEX of the original act)
ACTS_EU = [
    ("codice_doganale_ue", "Codice Doganale dell'Unione (Reg. UE 952/2013)", "Doganale", "32013R0952"),
    ("reg_ue_2015_2446", "Regolamento delegato (UE) 2015/2446 — integrazione del CDU (ammissione temporanea, regimi speciali)", "Doganale", "32015R2446"),
    ("reg_ue_2015_2447", "Regolamento di esecuzione (UE) 2015/2447 — modalità di applicazione del CDU", "Doganale", "32015R2447"),
    ("gdpr", "Regolamento (UE) 2016/679 — protezione dei dati personali (GDPR)", "Privacy", "32016R0679"),
    ("bruxelles_i_bis", "Regolamento (UE) 1215/2012 — competenza giurisdizionale e riconoscimento delle decisioni civili (Bruxelles I-bis)", "Procedura Civile", "32012R1215"),
    ("roma_i", "Regolamento (CE) 593/2008 — legge applicabile alle obbligazioni contrattuali (Roma I)", "Civile", "32008R0593"),
    ("roma_ii", "Regolamento (CE) 864/2007 — legge applicabile alle obbligazioni extracontrattuali (Roma II)", "Civile", "32007R0864"),
    ("bruxelles_ii_ter", "Regolamento (UE) 2019/1111 — matrimonio, responsabilità genitoriale, sottrazione di minori (Bruxelles II-ter)", "Famiglia", "32019R1111"),
    ("successioni_ue", "Regolamento (UE) 650/2012 — successioni transfrontaliere e certificato successorio europeo", "Notarile", "32012R0650"),
]


def fetch(url: str, timeout: int = 120) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Language": "it"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", "replace")


def consolidated_versions(base: str) -> list[str]:
    """'32015R2446' -> ['02015R2446-20260701', '02015R2446-20250225', …] (newest first)."""
    try:
        page = fetch(f"https://eur-lex.europa.eu/legal-content/IT/ALL/?uri=CELEX:{base}")
        cons = sorted(set(re.findall(r"0" + re.escape(base[1:]) + r"-(\d{8})", page)), reverse=True)
        return ["0" + base[1:] + "-" + d for d in cons]
    except Exception as exc:  # noqa: BLE001
        print(f"    (ALL page non letta: {exc})", flush=True)
        return []


_TAG = re.compile(r"<[^>]+>")
_WS = re.compile(r"[ \t\r\f\v]+")


def _text(fragment: str) -> str:
    """HTML -> plain text keeping paragraph breaks; table cells joined by a space."""
    s = fragment
    s = re.sub(r"</t[dh]>\s*<t[dh][^>]*>", " ", s)          # cell | cell -> one line
    s = re.sub(r"</(p|tr|div|li)>", "\n", s)
    s = re.sub(r"<br\s*/?>", "\n", s)
    s = _TAG.sub("", s)
    s = H.unescape(s)
    lines = []
    for ln in s.split("\n"):
        ln = _WS.sub(" ", ln).strip()
        if not ln:
            continue
        if re.fullmatch(r"▼[A-Z]\d*|►[A-Z]\d*|◄", ln):     # amendment markers of consolidated texts
            continue
        ln = re.sub(r"\s*(▼[A-Z]\d*|►[A-Z]\d*|◄)\s*", " ", ln).strip()
        lines.append(ln)
    return "\n".join(lines).strip()


_SUFFIX = r"(?:bis|ter|quater|quinquies|sexies|septies|octies|novies|decies)"
# due markup: testi consolidati («title-article-norm») e Gazzetta ufficiale UE («oj-ti-art»)
# tre markup: consolidati («title-article-norm»), GU UE recente («oj-ti-art»), GU UE vecchia («ti-art»)
_ART = re.compile(
    r'<p[^>]*class="(?:title-article-norm|oj-ti-art|ti-art)"[^>]*>\s*Articolo\s+(\d+)\s*(' + _SUFFIX + r'?)\s*</p>',
    re.I)
_STITLE = re.compile(r'<p[^>]*class="(?:stitle-article-norm|oj-sti-art|sti-art)"[^>]*>(.*?)</p>', re.S)
_DIVISION = re.compile(r'<p[^>]*class="(?:title-division-\d|oj-ti-section-\d|oj-ti-grseq-\d|oj-doc-ti|ti-section-\d|ti-grseq-\d|doc-ti)"')


def _dedup(arts: list[dict]) -> list[dict]:
    # duplicates (the TOC repeats titles in some layouts): keep the richest occurrence
    seen: dict[str, dict] = {}
    for a in arts:
        if a["number"] in seen and len(seen[a["number"]]["body"]) >= len(a["body"]):
            continue
        seen[a["number"]] = a
    return list(seen.values())


def _mk(num: str, suffix: str, heading: str, body: str) -> dict:
    number = num + ("-" + suffix.lower() if suffix else "")
    repealed = bool(re.match(r"^\s*\(?(soppresso|abrogato)\)?\s*\.?\s*$", body, re.I)) or body == ""
    return {"number": number, "heading": heading[:300], "body": body,
            "repealed": str(repealed), "in_force_from": ""}


def parse(html_text: str) -> list[dict]:
    hits = list(_ART.finditer(html_text))
    arts: list[dict] = []
    for i, m in enumerate(hits):
        start = m.end()
        end = hits[i + 1].start() if i + 1 < len(hits) else len(html_text)
        chunk = html_text[start:end]
        cut = _DIVISION.search(chunk)          # stop at the next chapter/section title
        if cut:
            chunk = chunk[:cut.start()]
        hm = _STITLE.search(chunk)
        heading = _text(hm.group(1)) if hm else ""
        if hm:
            chunk = chunk[hm.end():]
        arts.append(_mk(m.group(1), m.group(2), heading, _text(chunk)))
    return _dedup(arts)


# ── ripiego: PDF consolidato (EUR-Lex non serve l'HTML dei testi molto grandi) ──
_PDF_ART = re.compile(r"^\s*Articolo\s+(\d+)\s*(" + _SUFFIX + r"?)\s*$", re.I | re.M)
_PDF_NOISE = re.compile(r"^\s*(02015R2446|0201\dR\d{4}|\d{4}R\d{4})[^\n]*—\s*IT\s*—[^\n]*$|^\s*▼[A-Z]\d*\s*$|^\s*\d+\s*$", re.M)


def parse_pdf(path: Path) -> list[dict]:
    import pdfplumber  # nel container c'e' (OCR); sull'host puo' mancare
    parts: list[str] = []
    with pdfplumber.open(str(path)) as pdf:
        for page in pdf.pages:
            parts.append(page.extract_text() or "")
    text = "\n".join(parts)
    text = _PDF_NOISE.sub("", text)
    # sillabazione del PDF: «com-\nprende» → «comprende» (trattino morbido U+00AD o '-')
    text = re.sub(r"­\s*\n\s*", "", text)
    text = re.sub(r"(\w)-\n(?=[a-zà-ú])", r"\1", text)
    hits = list(_PDF_ART.finditer(text))
    arts: list[dict] = []
    for i, m in enumerate(hits):
        start = m.end()
        end = hits[i + 1].start() if i + 1 < len(hits) else len(text)
        chunk = text[start:end].strip("\n")
        lines = [ln.strip() for ln in chunk.split("\n") if ln.strip()]
        # la rubrica: prima riga corta senza punto finale e senza numerazione di comma
        heading = ""
        if lines and len(lines[0]) <= 160 and not re.match(r"^\d+\.|^\(?[a-z]\)", lines[0]) and not lines[0].endswith("."):
            heading = lines.pop(0)
        body = "\n".join(lines)
        # taglia al primo titolo di capo/sezione/allegato che segue
        cut = re.search(r"\n(CAPO|SEZIONE|TITOLO|ALLEGATO)\s+[IVXLC\d]+[^\n]*\n", "\n" + body)
        if cut and cut.start() > 0:
            body = body[:cut.start()].rstrip()
        # righe del PDF (≈60 caratteri) → paragrafi: si va a capo solo prima di un comma
        # numerato, di una lettera «a)» o di un punto «i)»; il resto si unisce con uno spazio
        body = re.sub(r"\n(?!\s*(?:\d+\.\s|\(?[a-z]{1,2}\)\s|[ivxl]+\)\s|—|-\s))", " ", body)
        body = re.sub(r"[ \t]{2,}", " ", body).strip()
        heading = re.sub(r"\s+", " ", heading).strip()
        arts.append(_mk(m.group(1), m.group(2), heading, body))
    return _dedup(arts)


def main() -> None:
    want = sys.argv[1] if len(sys.argv) > 1 else None
    todo = [a for a in ACTS_EU if not want or a[0] == want]
    print(f"atti UE da scaricare: {len(todo)}", flush=True)
    for cid, title, area, base in todo:
        dest = OUT / f"{cid}.json"
        if dest.exists():
            try:
                n = len(json.loads(dest.read_text(encoding="utf-8"))["articles"])
                print(f"= {cid:24s} già scaricato ({n} art) — salto", flush=True)
                continue
            except Exception:  # noqa: BLE001
                pass
        t0 = time.time()
        print(f"\n▶ {cid}  ({title})", flush=True)
        arts: list[dict] = []
        src, celex = "", base
        # 1) consolidati, dal più recente: HTML, poi PDF (EUR-Lex non serve l'HTML dei
        #    testi molto grandi e non tutte le versioni hanno il PDF) — ogni tentativo
        #    e' isolato: un 404 non deve far saltare l'atto (roma_ii, 16 set)
        for cx in consolidated_versions(base)[:4]:
            try:
                arts = parse(fetch(f"https://eur-lex.europa.eu/legal-content/IT/TXT/HTML/?uri=CELEX:{cx}"))
                if len(arts) >= 5:
                    src, celex = "html-consolidato", cx
                    break
                print(f"    {cx}: HTML vuoto → provo il PDF", flush=True)
                pdf_path = Path(f"/tmp/eurlex_{cx}.pdf")
                req = urllib.request.Request(
                    f"https://eur-lex.europa.eu/legal-content/IT/TXT/PDF/?uri=CELEX:{cx}", headers={"User-Agent": UA})
                with urllib.request.urlopen(req, timeout=300) as r:
                    pdf_path.write_bytes(r.read())
                arts = parse_pdf(pdf_path)
                if len(arts) >= 5:
                    src, celex = "pdf-consolidato", cx
                    break
            except Exception as exc:  # noqa: BLE001
                print(f"    {cx}: {type(exc).__name__}: {str(exc)[:70]}", flush=True)
                arts = []
        # 2) atto originale (Gazzetta ufficiale UE, senza modifiche successive)
        if len(arts) < 5:
            try:
                arts = parse(fetch(f"https://eur-lex.europa.eu/legal-content/IT/TXT/HTML/?uri=CELEX:{base}"))
                src, celex = "html-originale", base
            except Exception as exc:  # noqa: BLE001
                print(f"  ✗ {cid} FALLITO: {type(exc).__name__}: {str(exc)[:120]}", flush=True)
                continue
        if len(arts) < 5:
            print(f"  ✗ {cid}: nessun articolo riconosciuto", flush=True)
            continue
        print(f"    fonte: {src} ({celex})", flush=True)
        payload = {"id": cid, "title": title, "area": area, "urn": f"eurlex:{celex}",
                   "wave": "eurlex", "source": src, "articles": arts, "failures": []}
        dest.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        rep = sum(1 for a in arts if a["repealed"] == "True")
        print(f"  ✓ {cid}: {len(arts)} articoli ({rep} soppressi), {time.time()-t0:.0f}s -> {dest.name}", flush=True)
        time.sleep(2)


if __name__ == "__main__":
    main()
