#!/usr/bin/env python3
"""Sull'HOST (stdlib): elenco COMPLETO da HUDOC delle sentenze e decisioni contro l'Albania (inglese; il francese solo
quando per quel ricorso non c'è l'inglese) e scaricamento dei corpi che non abbiamo in ecthr_albania/<anno>/<itemid>.html.
Poi `tools/hudoc_fetch.py` completa metadati e traduzioni albanesi, e `reparse_cedu.py run` li carica uno per uno.
Il container riceve 403 da HUDOC: gira sull'host."""
import json, re, os, time, urllib.parse, urllib.request
from pathlib import Path
RAW = Path("/var/www/apps/super-avvocato/data/raw/jurisprudence/ecthr_albania")
H = "https://hudoc.echr.coe.int/app/query/results"
UA = {"User-Agent": "Mozilla/5.0"}
SEL = "itemid,appno,kpdate,languageisocode,documentcollectionid2,docname"
def q(query, start, length=500):
    url = H + "?" + urllib.parse.urlencode({"query": query, "select": SEL, "sort": "kpdate Descending", "start": start, "length": length})
    for a in range(4):
        try:
            return json.load(urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=90))
        except Exception:
            time.sleep(5 * (a + 1))
    raise RuntimeError("HUDOC non risponde")
have = {m.group(1) for p in RAW.rglob("*.html") if not any(x in p.parts for x in ("_cache", "_meta", "alb")) for m in [re.match(r"^(00[12]-\d+)\.html$", p.name)] if m}
items = []
for coll in ("JUDGMENTS", "DECISIONS"):
    for lang in ("ENG", "FRE"):
        start = 0
        while True:
            r = q(f"contentsitename:ECHR AND (respondent:ALB) AND (documentcollectionid2:{coll}) AND (languageisocode:{lang})", start)
            res = [x["columns"] for x in r.get("results") or []]
            items += [dict(c, _coll=coll) for c in res]
            start += len(res)
            if not res or start >= int(r.get("resultcount") or 0): break
            time.sleep(0.6)
        print(coll, lang, "→", sum(1 for i in items if i["_coll"] == coll and i["languageisocode"] == lang), flush=True)
eng_apps = {(i["_coll"], (i.get("appno") or "").split(";")[0]) for i in items if i["languageisocode"] == "ENG"}
todo = [i for i in items if i["itemid"] not in have and (i["languageisocode"] == "ENG" or ((i["_coll"], (i.get("appno") or "").split(";")[0]) not in eng_apps))]
# un ricorso già presente con un altro itemid (es. versione FRE che abbiamo) non si riscarica
print("totale HUDOC:", len(items), "· già nostri:", len(have), "· da scaricare:", len(todo), flush=True)
ok = 0
for i in todo:
    y = (i.get("kpdate") or "")[:4] or "unknown"
    d = RAW / y; d.mkdir(exist_ok=True); os.chown(d, 1000, 1000)
    f = d / f"{i['itemid']}.html"
    try:
        url = f"https://hudoc.echr.coe.int/app/conversion/docx/html/body?library=ECHR&id={i['itemid']}&filename=x.html"
        body = urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=90).read()
        if len(body) < 1500: raise ValueError(f"corpo vuoto ({len(body)} byte)")
        f.write_bytes(body); os.chown(f, 1000, 1000); ok += 1
    except Exception as exc:
        print("  ERRORE", i["itemid"], exc, flush=True)
    time.sleep(0.6)
print("HUDOC_LIST_DONE scaricati", ok, flush=True)
