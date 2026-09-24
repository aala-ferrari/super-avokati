#!/usr/bin/env python3
"""v9.390 — LE TABELLE DELLE SOSTANZE STUPEFACENTI E PSICOTROPE (d.P.R. 309/1990, testo vigente) da Normattiva.

Perché (misurato il 25 set): la tabella decide la pena dell'art. 73 (Tabelle I e III → comma 1; II e IV → comma 4) o se
il fatto è reato, e il cervello a memoria sbaglia la tabella di 6 sostanze su 30 (ketamina, GHB, buprenorfina, metaqualone,
tramadolo «non inclusa» mentre è in Tabella I, 1cP-LSD). Le tabelle cambiano per decreto ministeriale più volte l'anno (78
aggiornamenti su Normattiva). Il sito del Ministero della Salute risponde ai programmi con una verifica anti-robot; la stessa
tabella consolidata sta su Normattiva come allegato del d.P.R. — «Tabelle (parte 1/2/3)», gruppo `flagTipoArticolo=4`, una
pagina per parte distinta da `art.progressivo` — in TABELLE HTML (`<span class="table-akn">`) che il lettore degli articoli
scartava (leggeva solo gli `attachment-just-text`: restava «TABELLA I / SOSTANZE», 19 caratteri).

Uscita: `data/processed/it_tabelle_stupefacenti.json` = {fonte, versione, vigenza, scaricato, righe: [{tabella, sezione,
nome, chimica, altri}]} — Tabella I/II/III/IV e «MED» (Tabella dei medicinali, sezioni A-E). Da rilanciare quando il
controllo di freschezza segnala il d.P.R. 309/1990 aggiornato (mai in automatico: la legge entra quando la guardiamo).
Sull'HOST (come gli altri ingest Normattiva):

    python3 tools/ingest_tabelle_stupefacenti.py [--out PATH]
"""
import html as _h
import json
import os
import re
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import normattiva_lib as N  # noqa: E402

ACT = Path(os.environ.get("IT_ACTS_DIR", "/var/www/apps/super-avvocato/data/processed/it_acts")) / "stupefacenti.json"
OUT = Path(sys.argv[sys.argv.index("--out") + 1]) if "--out" in sys.argv else \
    Path("/var/www/apps/super-avvocato/data/processed/it_tabelle_stupefacenti.json")
_SPAN = re.compile(r'<span class="(attachment-just-text|table-akn)">(.*?)</span>(?=\s*<span class="(?:attachment-just-text|table-akn)">|\s*$|\s*</div>)', re.S)


def _testo(frammento: str) -> str:
    t = _h.unescape(re.sub(r"<[^>]+>", " ", frammento or ""))
    t = re.sub(r"\(\(|\)\)", " ", t)                     # la marcatura del testo modificato «((…))»
    t = re.sub(r"(?<=\w)- (?=\w)", "-", t)               # «esaidro- indolo» → «esaidro-indolo» (a capo della cella)
    return re.sub(r"\s+", " ", t).strip()


def parse(pagine: list[str]) -> tuple[list[dict], dict]:
    righe: list[dict] = []
    tab, sez = "", ""
    note: dict = {}
    for page in pagine:
        i = page.find('class="bodyTesto"')
        j = page.find('<div class="d-flex justify-content-between', i)
        reg = page[i: j if j > i else len(page)]
        for m in _SPAN.finditer(reg):
            kind, corpo = m.group(1), m.group(2)
            if kind == "attachment-just-text":
                t = _testo(corpo)
                mt = re.search(r"TABELLA\s+(?:DEI\s+)?(MEDICINALI|IV|I{1,3})\b", t)
                if mt:
                    tab = "MED" if mt.group(1) == "MEDICINALI" else mt.group(1)
                    sez = ""
                ms = re.search(r"SEZIONE\s+([A-E])\b", t)
                if ms and tab == "MED":
                    sez = ms.group(1)
                continue
            for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", corpo, re.S):
                c = [_testo(td) for td in re.findall(r"<td[^>]*>(.*?)</td>", tr, re.S)]
                if not c or not c[0] or c[0].upper().startswith("DENOMINAZIONE"):
                    continue
                if not tab:
                    continue
                c = (c + ["", "", ""])[:3]
                # le righe-nota («I sali delle sostanze…», «Le preparazioni contenenti…», «Composizioni…»): regole della
                # tabella, non sostanze
                if re.match(r"^(?:I sali|Le preparazioni|Gli isomeri|Composizioni|COMPOSIZIONI|Medicinali soggetti|\"Composizioni)", c[0]):
                    note.setdefault(f"{tab}{('-' + sez) if sez else ''}", []).append(c[0][:400])
                    continue
                righe.append({"tabella": tab, "sezione": sez, "nome": c[0], "chimica": c[1], "altri": c[2]})
    return righe, note


def main() -> int:
    atto = json.loads(ACT.read_text(encoding="utf-8"))
    s = N.Normattiva(delay=1.0)
    page = s.open_act(atto["urn"])
    links = [(_h.unescape(u), lab.strip()) for u, lab in N.LINK_RE.findall(page)
             if re.match(r"^Tabelle\(parte \d\)$", lab.strip()) and "imUpdate=true" not in u]
    links.sort(key=lambda x: x[1])
    if not links:
        print("✗ nessun link «Tabelle(parte N)» nella pagina dell'atto: la struttura di Normattiva è cambiata"); return 1
    pagine, vig, versione = [], "", ""
    for u, lab in links:
        pg = s.fetch_article(u)
        pagine.append(pg)
        mv = N.VIGENZA_RE.search(pg)
        vig = vig or (mv.group(1).strip() if mv else "")
        versione = versione or (re.search(r"art\.versione=(\d+)", u) or [None, ""])[1]
        print(f"  {lab}: {len(pg)} byte", flush=True)
    righe, note = parse(pagine)
    per = {}
    for r in righe:
        k = r["tabella"] + (("-" + r["sezione"]) if r["sezione"] else "")
        per[k] = per.get(k, 0) + 1
    if per.get("I", 0) < 300 or not per.get("II") or not per.get("IV"):
        print(f"✗ tabelle incomplete ({per}): non scrivo nulla"); return 1
    OUT.write_text(json.dumps({"fonte": "Normattiva — d.P.R. 9 ottobre 1990, n. 309, Tabelle (testo vigente)", "urn": atto["urn"],
                               "versione": versione, "vigenza": vig, "scaricato": time.strftime("%Y-%m-%d"),
                               "righe": righe, "note": note}, ensure_ascii=False), encoding="utf-8")
    try:
        os.chown(OUT, 1000, 1000)
    except Exception:  # noqa: BLE001
        pass
    print(f"✓ {len(righe)} sostanze · {per} · versione {versione} · vigenza «{vig}» → {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
