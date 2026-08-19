# -*- coding: utf-8 -*-
"""Ingest multiple Italian codes from Wikisource into ONE bm25_it.pkl (lang=it).
License-free (Italian statutes outside copyright, Art. 5 L. 633/1941).
Run inside the container: python3 /app/data/ingest_it_codes.py
"""
import json, re, time, urllib.parse, urllib.request
from pathlib import Path
from dataclasses import asdict
import sys
sys.path.insert(0, "/app")
from src.parser import Article
from src.retrieval import ArticleIndex

API = "https://it.wikisource.org/w/api.php"
UA = "SuperAvokati-legal-indexer/1.0 (https://superavokati.ai; info@aala.global)"

CODES = [
    {"id": "codice_civile", "title": "Codice Civile", "area": "Civile", "prefix": "Codice civile/"},
    {"id": "codice_penale", "title": "Codice Penale", "area": "Penale", "prefix": "Codice penale/"},
    {"id": "codice_procedura_civile", "title": "Codice di Procedura Civile", "area": "Procedura Civile", "prefix": "Codice di Procedura Civile/"},
    {"id": "codice_procedura_penale", "title": "Codice di Procedura Penale", "area": "Procedura Penale", "prefix": "Codice di procedura penale/"},
]

HEADER = re.compile(r"^={2,6}\s*Art\.?\s*([0-9]+[\w\-]*)\s*[\.–\-]?\s*(.*?)\s*={2,6}\s*$", re.M)


def _get(params):
    url = API + "?" + urllib.parse.urlencode({**params, "format": "json"})
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def list_subpages(prefix):
    pages, cont = [], None
    while True:
        p = {"action": "query", "list": "allpages", "apprefix": prefix,
             "apnamespace": "0", "aplimit": "500"}
        if cont:
            p["apcontinue"] = cont
        d = _get(p)
        pages += [x["title"] for x in d["query"]["allpages"]]
        cont = d.get("continue", {}).get("apcontinue")
        if not cont:
            break
        time.sleep(0.2)
    return pages


def fetch_wikitext(titles):
    out = {}
    for i in range(0, len(titles), 40):
        d = _get({"action": "query", "prop": "revisions", "rvslots": "main",
                  "rvprop": "content", "titles": "|".join(titles[i:i + 40])})
        for pg in d.get("query", {}).get("pages", {}).values():
            try:
                out[pg["title"]] = pg["revisions"][0]["slots"]["main"]["*"]
            except Exception:
                pass
        time.sleep(0.3)
    return out


def clean(text):
    text = re.sub(r"<ref[^>]*>.*?</ref>", "", text, flags=re.S)
    text = re.sub(r"<ref[^>]*/>", "", text)
    for _ in range(5):
        text = re.sub(r"\{\{[^{}]*\}\}", "", text)
    text = re.sub(r"\[\[(?:[^\]|]*\|)?([^\]]*)\]\]", r"\1", text)
    text = text.replace("'''", "").replace("''", "")
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def parse_page(spec, title, wikitext):
    rel = title.replace(spec["prefix"], "").split("/")
    libro = rel[0] if rel and rel[0] != title else ""
    titolo = rel[1] if len(rel) > 1 else ""
    arts, ms = [], list(HEADER.finditer(wikitext))
    for i, m in enumerate(ms):
        num = m.group(1).strip().rstrip(".")
        heading = clean(m.group(2)).strip()[:300]
        start, end = m.end(), (ms[i + 1].start() if i + 1 < len(ms) else len(wikitext))
        body = clean(wikitext[start:end])
        if not num or len(body) < 3:
            continue
        arts.append(Article(
            code=spec["id"], title_sq=spec["title"], area=spec["area"],
            number=num, heading=heading, body=body,
            pjesa=libro, kreu=titolo, seksioni="",
            repealed=("abrogat" in body.lower()[:60] or "soppress" in body.lower()[:60]),
            volatility="STABLE"))
    return arts


def main():
    seen, all_articles = set(), []
    for spec in CODES:
        subs = [t for t in list_subpages(spec["prefix"]) if t.startswith(spec["prefix"])]
        wt = fetch_wikitext(subs)
        n0 = len(all_articles)
        for title, text in wt.items():
            for a in parse_page(spec, title, text):
                key = (a.code, a.number)
                if key not in seen:
                    seen.add(key)
                    all_articles.append(a)
        print(f"  {spec['id']}: {len(subs)} pages -> {len(all_articles) - n0} articles")
    print(f"TOTAL: {len(all_articles)} articles across {len(CODES)} codes")

    out_jsonl = Path("/app/data/processed/all_articles_it.jsonl")
    with out_jsonl.open("w", encoding="utf-8") as fh:
        for a in all_articles:
            fh.write(json.dumps(asdict(a), ensure_ascii=False) + "\n")
    ArticleIndex.build(all_articles, lang="it").save(Path("/app/data/index/bm25_it.pkl"))
    print(f"  index -> bm25_it.pkl ({len(all_articles)} articles, lang=it)")

    idx = {(a.code, a.number): a for a in all_articles}
    for code, n, what in [("codice_civile", "2043", "fatto illecito"),
                          ("codice_penale", "575", "omicidio"),
                          ("codice_procedura_civile", "99", "principio domanda"),
                          ("codice_procedura_penale", "1", "giurisdizione")]:
        a = idx.get((code, n))
        print(f"  {code} art.{n}: " + (f"{a.heading[:45]!r}" if a else f"MANCANTE ({what})"))


if __name__ == "__main__":
    main()
