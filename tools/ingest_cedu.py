# -*- coding: utf-8 -*-
"""CEDU + protocolli dal PDF ufficiale del Consiglio d'Europa (italiano).

Normattiva ha solo la legge di ratifica (L. 848/1955, 2 articoli): il testo della
Convenzione sta nel PDF della Corte EDU, impaginato a DUE COLONNE — estratto per
intero pdfplumber mischia le colonne («ARTICOLO 11 ARTICOLO 14»). Qui ogni pagina
si legge colonna per colonna (crop a meta' larghezza): 126 titoli puliti, 0 mischiati.

Produce un atto per la Convenzione (art. 1-59) e uno per ogni protocollo (n. 1
addizionale, 4, 6, 7, 12, 13, 16) — la numerazione riparte da 1 in ciascuno, e in
pratica si cita «art. 1 Prot. 1 CEDU» / «art. 4 Prot. 7 CEDU».

Gira DENTRO il container (pdfplumber):
    docker exec super-avvocato python3 /app/tools/ingest_cedu.py
"""
import json, os, re, sys, time, urllib.request
from pathlib import Path

URL = "https://www.echr.coe.int/documents/d/echr/convention_ita"
OUT = Path(os.environ.get("IT_ACTS_DIR", "/app/data/processed/it_acts"))
PDF = Path("/tmp/cedu_ita.pdf")

ACTS = {
    "cedu": ("CEDU — Convenzione europea per la salvaguardia dei diritti dell'uomo e delle libertà fondamentali (L. 848/1955)", "cedu"),
    "cedu_protocollo_1": ("Protocollo addizionale n. 1 alla CEDU — proprietà, istruzione, libere elezioni", "cedu-p1"),
    "cedu_protocollo_4": ("Protocollo n. 4 alla CEDU — imprigionamento per debiti, libertà di circolazione, espulsioni", "cedu-p4"),
    "cedu_protocollo_6": ("Protocollo n. 6 alla CEDU — abolizione della pena di morte", "cedu-p6"),
    "cedu_protocollo_7": ("Protocollo n. 7 alla CEDU — espulsione di stranieri, doppio grado penale, ne bis in idem, parità dei coniugi", "cedu-p7"),
    "cedu_protocollo_12": ("Protocollo n. 12 alla CEDU — divieto generale di discriminazione", "cedu-p12"),
    "cedu_protocollo_13": ("Protocollo n. 13 alla CEDU — abolizione della pena di morte in ogni circostanza", "cedu-p13"),
    "cedu_protocollo_16": ("Protocollo n. 16 alla CEDU — pareri consultivi della Corte", "cedu-p16"),
}
_SECTION = re.compile(r"^\s*Protocollo\s+(addizionale|n\.\s*(\d+))\s*$", re.I)
_ARTICLE = re.compile(r"^\s*ARTICOLO\s+(\d+)\s*$")
_BODY_START = re.compile(r"^\s*(?:\d+\.\s|\(?[a-z]\)\s)")
_NOISE = re.compile(r"^\s*\d+\s*$|^\s*Convenzione europea dei Diritti dell.Uomo\s*$", re.I)
_HEAD_OPEN = re.compile(r"(,|\b(?:di|del|della|dei|delle|e|ed|a|al|alla|in|per|con|tra|fra|o|od|dell[’']|all[’']))$", re.I)


def column_lines(pdf: Path) -> list[str]:
    import pdfplumber
    out: list[str] = []
    with pdfplumber.open(str(pdf)) as doc:
        for p in doc.pages:
            w, h = p.width, p.height
            for box in ((0, 0, w / 2, h), (w / 2, 0, w, h)):
                for ln in (p.crop(box).extract_text() or "").split("\n"):
                    ln = ln.rstrip()
                    if ln and not _NOISE.match(ln):
                        out.append(ln)
    return out


def _join(lines: list[str]) -> str:
    body = "\n".join(lines)
    body = re.sub(r"(\w)-\n(?=[a-zà-ú])", r"\1", body)               # sillabazione
    body = re.sub(r"\n(?!\s*(?:\d+\.\s|\(?[a-z]\)\s|—))", " ", body)   # righe → paragrafi
    return re.sub(r"[ \t]{2,}", " ", body).strip()


def parse(lines: list[str]) -> dict[str, list[dict]]:
    acts: dict[str, list[dict]] = {k: [] for k in ACTS}
    # si parte dal primo «ARTICOLO 1» seguito da «Obbligo di rispettare…» (prima c'e' l'indice)
    start = next(i for i, ln in enumerate(lines)
                 if _ARTICLE.match(ln) and i + 1 < len(lines) and lines[i + 1].startswith("Obbligo di rispettare"))
    cur_act, cur = "cedu", None
    heading_lines: list[str] = []
    body_lines: list[str] = []

    def flush():
        if cur is not None:
            acts[cur_act].append({"number": cur, "heading": " ".join(heading_lines)[:300],
                                  "body": _join(body_lines), "repealed": False, "in_force_from": ""})

    i = start
    while i < len(lines):
        ln = lines[i]
        ms = _SECTION.match(ln)
        if ms:
            flush(); cur = None
            cur_act = "cedu_protocollo_1" if ms.group(1).lower().startswith("addizionale") else f"cedu_protocollo_{ms.group(2)}"
            i += 1
            continue
        ma = _ARTICLE.match(ln)
        if ma:
            flush()
            cur, heading_lines, body_lines = ma.group(1), [], []
            # rubrica: 1-2 righe corte subito dopo, senza inizio di comma e senza punto finale
            # (il Protocollo n. 16 non ha rubriche: la prima riga e' gia' testo)
            j = i + 1
            while (cur_act != "cedu_protocollo_16"
                   and j < len(lines) and len(heading_lines) < 2 and len(lines[j]) <= 80
                   and not _BODY_START.match(lines[j]) and not lines[j].endswith(".")
                   and not _ARTICLE.match(lines[j]) and not _SECTION.match(lines[j])
                   and (not heading_lines or _HEAD_OPEN.search(heading_lines[-1]))):
                heading_lines.append(lines[j].strip())
                j += 1
            i = j
            continue
        if cur is not None:
            body_lines.append(ln)
        i += 1
    flush()
    return acts


def main() -> int:
    if not (PDF.exists() and PDF.stat().st_size > 100_000):
        req = urllib.request.Request(URL, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=120) as r:
            PDF.write_bytes(r.read())
    t0 = time.time()
    acts = parse(column_lines(PDF))
    OUT.mkdir(parents=True, exist_ok=True)
    bad = 0
    for cid, arts in acts.items():
        title, short = ACTS[cid]
        nums = [a["number"] for a in arts]
        ok = nums == [str(k) for k in range(1, len(nums) + 1)] and len(nums) >= 4
        bad += 0 if ok else 1
        print(f"  {'✓' if ok else '✗'} {cid:20s} {len(arts):>3} art  (1..{nums[-1] if nums else '-'})  es. art.1 {arts[0]['heading'][:40]!r}" if arts else f"  ✗ {cid}: 0 articoli")
        if ok:
            (OUT / f"{cid}.json").write_text(json.dumps({
                "id": cid, "title": title, "area": "Internazionale", "urn": "coe:convention_ita",
                "wave": "wave8", "source": "pdf-coe-colonne", "articles": arts, "failures": []},
                ensure_ascii=False), encoding="utf-8")
    print(f"fatto in {time.time() - t0:.0f}s, atti non validi: {bad}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
