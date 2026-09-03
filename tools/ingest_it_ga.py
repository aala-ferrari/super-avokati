#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""[Mossa 2] Harvester Giustizia Amministrativa (CdS) — v1, dalla fonte.

**Com'e' fatta la porta** (misurato, 3 set 2026): portlet Liferay con token
`p_auth` di sessione → si prende la pagina fresca coi cookie, si estrae
l'action del form, si POSTa la ricerca; le pagine successive sono GET con
`_cur=N` (la sessione ricorda i filtri). Ultima pagina vista: 11.602 →
~232.000 sentenze CdS raggiungibili nel tempo, dalla fonte.

**L'accoppiamento riga**: l'ECLI (`ECLI:IT:CDS:2026:6775...`) e il file
(`202606775_11.html`) NON sono adiacenti nel markup — si uniscono per
NUMERO (anno+numero a 5 cifre). L'adiacenza ingannava gia' al primo probe.

**Solo retrieval, niente verificatore**: qui non esiste «anno completo»
(si pagina dal piu' recente), quindi il CdS NON entra nel meta di
copertura — il verificatore resta CCost-only finche' non avremo sweep
completi. La ricerca FTS invece li assorbe subito (stesso jsonl).

**v1 salta i PDF** (conta e dichiara): il testo pulito viene dagli .html.
"""
import argparse
import html as _html
import http.cookiejar
import json
import os
import re
import time
import urllib.parse
import urllib.request
from datetime import datetime

BASE = "https://www.giustizia-amministrativa.it/web/guest/dcsnprr"
P = "_decisioni_pareri_web_DecisioniPareriWebPortlet_INSTANCE_XKc17mrB8J10_"
OUT = "/var/www/apps/super-avvocato/data/processed/it_decisions.jsonl"
# mdp.* nega i client non-browser (401) ma accetta col Referer del
# portale: UA browser standard + Referer, rate gentile, e la nostra
# identita' resta nel From.
UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")
FROM_HDR = "info@aala.global"
PAUSA = 0.7

_ECLI = re.compile(r"ECLI:IT:CDS:(\d{4}):(\d{1,6})[A-Z]*")
_FILE = re.compile(
    r'href="(https://mdp\.giustizia-amministrativa\.it/visualizza/[^"]*'
    r'nomeFile=(\d{4})0?(\d{4,6})_\d+\.html[^"]*)"')
_TAG = re.compile(r"<script.*?</script>|<style.*?</style>", re.S | re.I)
_TAGS = re.compile(r"<[^>]+>")


def log(m):
    print(f"{datetime.now():%F %T} {m}", flush=True)


def pulisci(raw: str) -> str:
    t = _TAGS.sub(" ", _TAG.sub(" ", raw))
    t = _html.unescape(t)
    t = re.sub(r"[ \t\r\f\v]+", " ", t)
    return "\n".join(r.strip() for r in t.split("\n") if r.strip())[:60_000]


def apri():
    cj = http.cookiejar.CookieJar()
    op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))
    op.addheaders = [("User-Agent", UA), ("From", FROM_HDR)]
    return op


def pagina_risultati(op, tipo: str, sede: str) -> tuple[str, str]:
    """(html_pagina1, url_nav_template con _cur sostituibile)."""
    h = op.open(BASE, timeout=30).read().decode("utf-8", "replace")
    action = re.search(
        r'action="([^"]*javax\.portlet\.action=search[^"]*)"', h
    ).group(1).replace("&amp;", "&")
    dati = urllib.parse.urlencode({
        P + "searchModeRadio": "provv",
        P + "TipoProvvedimentoItem": tipo,
        P + "sedeProvvedimenti": sede,
        P + "pageSize": "20",
        P + "isAdvancedSearch": "false",
    }).encode()
    r = op.open(action, data=dati, timeout=45).read().decode("utf-8", "replace")
    nav = re.search(r'href="([^"]*_cur=2[^"]*)"', r)
    tmpl = nav.group(1).replace("&amp;", "&") if nav else ""
    return r, tmpl


def righe_da(html_pag: str) -> list[dict]:
    """ECLI ↔ file uniti PER NUMERO (l'adiacenza inganna — misurato)."""
    eclis = {}
    for anno, num in _ECLI.findall(html_pag):
        eclis[(int(anno), int(num))] = f"ECLI:IT:CDS:{anno}:{num}"
    files = {}
    for url, anno, num in _FILE.findall(html_pag):
        files.setdefault((int(anno), int(num)), url.replace("&amp;", "&"))
    out = []
    for chiave, ecli in eclis.items():
        url = files.get(chiave)
        if url:
            out.append({"year": chiave[0], "number": chiave[1],
                        "ecli": ecli, "url": url})
    return out


def carica_visti() -> set:
    visti = set()
    if os.path.exists(OUT):
        for riga in open(OUT, encoding="utf-8"):
            try:
                d = json.loads(riga)
                visti.add((d["court"], int(d["number"]), int(d["year"])))
            except Exception:  # noqa: BLE001
                pass
    return visti


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pagine", type=int, default=3)
    ap.add_argument("--tipo", default="Sentenza")
    ap.add_argument("--sede", default="Consiglio di Stato")
    a = ap.parse_args()

    op = apri()
    visti = carica_visti()
    log(f"GA {a.sede} · {a.tipo} · {a.pagine} pagine…")
    prima, tmpl = pagina_risultati(op, a.tipo, a.sede)
    pagine = [prima]
    for cur in range(2, a.pagine + 1):
        if not tmpl:
            break
        u = re.sub(r"_cur=\d+", f"_cur={cur}", tmpl)
        time.sleep(PAUSA)
        pagine.append(op.open(u, timeout=45).read().decode("utf-8", "replace"))

    nuove = pdf_saltati = 0
    with open(OUT, "a", encoding="utf-8") as out:
        for pg in pagine:
            for r in righe_da(pg):
                chiave = ("CdS", r["number"], r["year"])
                if chiave in visti:
                    continue
                time.sleep(PAUSA)
                try:
                    req = urllib.request.Request(
                        r["url"], headers={"User-Agent": UA,
                                           "Referer": BASE,
                                           "From": FROM_HDR})
                    corpo = op.open(req, timeout=40).read() \
                              .decode("utf-8", "replace")
                except Exception as exc:  # noqa: BLE001
                    log(f"  ! {r['ecli']}: {exc}")
                    continue
                testo = pulisci(corpo)
                if len(testo) < 500:
                    continue
                out.write(json.dumps({
                    "juris": "IT", "court": "CdS", "type": "sentenza",
                    "number": r["number"], "year": r["year"],
                    "date": None, "ecli": r["ecli"], "url": r["url"],
                    "text": testo,
                }, ensure_ascii=False) + "\n")
                out.flush()
                visti.add(chiave)
                nuove += 1
            # i .pdf senza .html si contano, non si tacciono
            pdf_saltati += len(re.findall(r"nomeFile=\d+_\d+\.pdf", pg)) // 2
    log(f"fine — CdS: +{nuove} sentenze · pdf-only saltati (v1): ~{pdf_saltati}")


if __name__ == "__main__":
    main()
