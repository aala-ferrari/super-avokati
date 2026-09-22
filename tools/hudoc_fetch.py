#!/usr/bin/env python3
"""Sull'HOST (stdlib): scarica da HUDOC i metadati ufficiali di ogni documento CEDU che abbiamo (itemid dal nome del
file) e, per sentenze e decisioni, la traduzione albanese integrale se esiste (languageisocode ALB).
Cache: ecthr_albania/_meta/<itemid>.json, _meta/alb_<appno>.json, alb/<itemid>.html. Ripartibile (salta ciò che c'è).
Il WAF di HUDOC risponde 403 dal container: per questo gira sull'host."""
import json, re, os, sys, time, html, urllib.parse, urllib.request
from pathlib import Path
RAW = Path("/var/www/apps/super-avvocato/data/raw/jurisprudence/ecthr_albania")
META = RAW / "_meta"; ALB = RAW / "alb"; META.mkdir(exist_ok=True); ALB.mkdir(exist_ok=True)
H = "https://hudoc.echr.coe.int/app/query/results"
SEL = "itemid,docname,doctype,documentcollectionid2,kpdate,appno,languageisocode,conclusion,article,violation,nonviolation,ecli,respondent,importance"
UA = {"User-Agent": "Mozilla/5.0"}
last = [0.0]
def pause():
    d = time.time() - last[0]
    if d < 0.6: time.sleep(0.6 - d)
    last[0] = time.time()
def q(query, length=10):
    for attempt in range(4):
        try:
            pause()
            url = H + "?" + urllib.parse.urlencode({"query": query, "select": SEL, "sort": "", "start": 0, "length": length})
            return json.load(urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=60))
        except Exception as exc:
            if attempt == 3: raise
            time.sleep(5 * (attempt + 1))
def body(itemid):
    pause()
    url = f"https://hudoc.echr.coe.int/app/conversion/docx/html/body?library=ECHR&id={itemid}&filename=x.html"
    return urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=90).read().decode("utf-8", "replace")
def strip(raw):
    raw = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", raw); raw = re.sub(r"(?s)<[^>]+>", " ", raw); return html.unescape(raw)
ids = sorted({m.group(1) for p in RAW.rglob("*.html") if not any(x in p.parts for x in ("_cache", "_meta", "alb")) for m in [re.match(r"^(00[12]-\d+)\.html$", p.name)] if m})
print("itemid:", len(ids), flush=True)
t0 = time.time(); n_meta = n_alb = n_body = 0
for i, iid in enumerate(ids, 1):
    mp = META / f"{iid}.json"
    if mp.exists():
        m = json.loads(mp.read_text(encoding="utf-8"))
    else:
        r = q(f"itemid:{iid}", 1); res = r.get("results") or []
        m = res[0]["columns"] if res else {}
        mp.write_text(json.dumps(m, ensure_ascii=False), encoding="utf-8"); n_meta += 1
    coll = (m.get("documentcollectionid2") or "").upper()
    kind = "JUDGMENTS" if "JUDGMENTS" in coll else "DECISIONS" if "DECISIONS" in coll else None
    if kind:
        first = (m.get("appno") or "").split(";")[0].strip()
        cp = META / ("alb_" + first.replace("/", "_") + ".json")
        if first and not cp.exists():
            r = q(f"(appno:{first}) AND (languageisocode:ALB) AND (documentcollectionid2:{kind})", 10); n_alb += 1
            cands = [x["columns"] for x in (r.get("results") or []) if (x["columns"].get("appno") or "").split(";")[0].strip() == first]
            cands = [c for c in cands if "summary" not in (c.get("docname") or "").lower()] or cands
            chosen, best = None, 0
            for c in cands[:3]:
                f = ALB / f"{c['itemid']}.html"
                if not f.exists():
                    try: f.write_text(body(c["itemid"]), encoding="utf-8"); n_body += 1
                    except Exception as exc: print("  corpo ALB fallito", c["itemid"], exc, flush=True); continue
                n = len(strip(f.read_text(encoding="utf-8")))
                if n > best: best, chosen = n, dict(c, chars=n, file=f"ecthr_albania/alb/{c['itemid']}.html")
            cp.write_text(json.dumps(chosen or {}, ensure_ascii=False), encoding="utf-8")
    if i % 25 == 0: print(f"  … {i}/{len(ids)} ({int(time.time()-t0)} s) meta {n_meta} ricerche ALB {n_alb} corpi {n_body}", flush=True)
for p in list(META.iterdir()) + list(ALB.iterdir()):
    os.chown(p, 1000, 1000)
os.chown(META, 1000, 1000); os.chown(ALB, 1000, 1000)
kinds = {}
for iid in ids:
    m = json.loads((META / f"{iid}.json").read_text(encoding="utf-8")); k = (m.get("documentcollectionid2") or "?").split(";")[1] if ";" in (m.get("documentcollectionid2") or "") else (m.get("doctype") or "?"); kinds[k] = kinds.get(k, 0) + 1
albs = sum(1 for p in META.glob("alb_*.json") if p.read_text(encoding="utf-8").strip() not in ("{}", ""))
print(f"FETCH_DONE in {int(time.time()-t0)} s: tipi {kinds}; traduzioni ALB trovate {albs}")
