# -*- coding: utf-8 -*-
"""Ingest Italian codes from Wikisource into ONE bm25_it.pkl (lang=it).
License-free (Italian statutes outside copyright, Art. 5 L. 633/1941).
Robust parsing: article headers may carry prefixes like ''[abrogato]'' before
"Art.", and single-page codes (Costituzione) have no rubrica.
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

CODES = [  # prefix-based (multi subpage)
    {"id": "codice_civile", "title": "Codice Civile", "area": "Civile", "prefix": "Codice civile/"},
    {"id": "codice_penale", "title": "Codice Penale", "area": "Penale", "prefix": "Codice penale/"},
    {"id": "codice_procedura_civile", "title": "Codice di Procedura Civile", "area": "Procedura Civile", "prefix": "Codice di Procedura Civile/"},
    {"id": "codice_procedura_penale", "title": "Codice di Procedura Penale", "area": "Procedura Penale", "prefix": "Codice di procedura penale/"},
]
SINGLE = [  # single-page
    {"id": "costituzione", "title": "Costituzione della Repubblica Italiana", "area": "Costituzionale", "page": "Italia, Repubblica - Costituzione"},
]

HEADER_LINE = re.compile(r"^={2,6}\s*(.+?)\s*={2,6}\s*$", re.M)
ART_IN = re.compile(r"Art\.?\s*([0-9]+[\w\-]*)\.?\s*(.*)", re.I)


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
    prefix = spec.get("prefix", "")
    rel = title.replace(prefix, "").split("/") if prefix else []
    libro = rel[0] if rel and rel[0] != title else ("Costituzione" if not prefix else "")
    titolo = rel[1] if len(rel) > 1 else ""
    arts = []
    hs = list(HEADER_LINE.finditer(wikitext))
    for i, m in enumerate(hs):
        content = m.group(1)
        am = ART_IN.search(content)
        if not am:
            continue  # chapter/section header, not an article
        num = am.group(1).strip().rstrip(".")
        heading = clean(am.group(2)).strip().strip("()").strip()[:300]
        repealed = ("abrogat" in content.lower() or "soppress" in content.lower())
        end = hs[i + 1].start() if i + 1 < len(hs) else len(wikitext)
        body = clean(wikitext[m.end():end])
        if not body:
            body = "[Articolo abrogato o senza testo]" if repealed else ""
        if not num or len(body) < 3:
            continue
        arts.append(Article(
            code=spec["id"], title_sq=spec["title"], area=spec["area"],
            number=num, heading=heading, body=body,
            pjesa=libro, kreu=titolo, seksioni="",
            repealed=repealed, volatility="STABLE"))
    return arts


def main():
    seen, all_articles = set(), []
    for spec in CODES:
        subs = [t for t in list_subpages(spec["prefix"]) if t.startswith(spec["prefix"])]
        wt = fetch_wikitext(subs)
        n0 = len(all_articles)
        for title, text in wt.items():
            for a in parse_page(spec, title, text):
                if (a.code, a.number) not in seen:
                    seen.add((a.code, a.number))
                    all_articles.append(a)
        print(f"  {spec['id']}: {len(subs)} pages -> {len(all_articles) - n0} articles")
    for spec in SINGLE:
        wt = fetch_wikitext([spec["page"]])
        n0 = len(all_articles)
        for title, text in wt.items():
            for a in parse_page(spec, title, text):
                if (a.code, a.number) not in seen:
                    seen.add((a.code, a.number))
                    all_articles.append(a)
        print(f"  {spec['id']}: 1 page -> {len(all_articles) - n0} articles")
    print(f"TOTAL: {len(all_articles)} articles")

    out_jsonl = Path("/app/data/processed/all_articles_it.jsonl")
    with out_jsonl.open("w", encoding="utf-8") as fh:
        for a in all_articles:
            fh.write(json.dumps(asdict(a), ensure_ascii=False) + "\n")
    ArticleIndex.build(all_articles, lang="it").save(Path("/app/data/index/bm25_it.pkl"))
    print(f"  index -> bm25_it.pkl ({len(all_articles)} articles, lang=it)")

    idx = {(a.code, a.number): a for a in all_articles}
    for code, n in [("codice_civile", "2043"), ("codice_penale", "575"),
                    ("codice_procedura_civile", "163"), ("codice_procedura_penale", "273"),
                    ("costituzione", "1"), ("costituzione", "21"), ("costituzione", "139")]:
        a = idx.get((code, n))
        print(f"  {code} art.{n}: " + (f"{(a.heading or a.body[:40])[:45]!r}" if a else "MANCANTE"))


if __name__ == "__main__":
    main()
