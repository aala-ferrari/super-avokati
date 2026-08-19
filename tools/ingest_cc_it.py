# -*- coding: utf-8 -*-
"""Ingest the Italian Codice Civile from Wikisource (license-free: Italian
statutes are outside copyright, Art. 5 L. 633/1941) into a BM25 index
bm25_it.pkl with the SAME Article structure as the Albanian corpus.

Runs INSIDE the container: python3 /app/data/ingest_cc_it.py
"""
import json, re, time, urllib.parse, urllib.request
from pathlib import Path
import sys
sys.path.insert(0, "/app")
from src.parser import Article
from src.retrieval import ArticleIndex

API = "https://it.wikisource.org/w/api.php"
UA = "SuperAvokati-legal-indexer/1.0 (https://superavokati.ai; info@aala.global)"
PREFIX = "Codice civile/"


def _get(params):
    params = {**params, "format": "json"}
    url = API + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def list_subpages():
    pages, cont = [], None
    while True:
        p = {"action": "query", "list": "allpages", "apprefix": PREFIX,
             "apnamespace": "0", "aplimit": "500"}
        if cont:
            p["apcontinue"] = cont
        d = _get(p)
        pages += [x["title"] for x in d["query"]["allpages"]]
        cont = d.get("continue", {}).get("apcontinue")
        if not cont:
            break
    return pages


def fetch_wikitext(titles):
    """Batch fetch up to 50 titles -> {title: wikitext}."""
    out = {}
    for i in range(0, len(titles), 40):
        batch = titles[i:i + 40]
        d = _get({"action": "query", "prop": "revisions", "rvslots": "main",
                  "rvprop": "content", "titles": "|".join(batch)})
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


HEADER = re.compile(r"^={2,6}\s*Art\.?\s*([0-9]+[\w\-]*)\s*[\.–\-]?\s*(.*?)\s*={2,6}\s*$", re.M)


def parse_page(title, wikitext):
    parts = title.replace(PREFIX, "").split("/")
    libro = parts[0] if parts else ""
    titolo = parts[1] if len(parts) > 1 else ""
    if libro.lower().startswith("disposizioni"):
        libro, titolo = "Disposizioni sulla legge in generale", ""
    arts = []
    ms = list(HEADER.finditer(wikitext))
    for i, m in enumerate(ms):
        num = m.group(1).strip().rstrip(".")
        heading = clean(m.group(2)).strip()
        start = m.end()
        end = ms[i + 1].start() if i + 1 < len(ms) else len(wikitext)
        body = clean(wikitext[start:end])
        if not num or len(body) < 3:
            continue
        arts.append(Article(
            code="codice_civile", title_sq="Codice Civile", area="Civile",
            number=num, heading=heading[:300], body=body,
            pjesa=libro, kreu=titolo, seksioni="",
            repealed=("abrogat" in body.lower()[:60] or "soppress" in body.lower()[:60]),
            volatility="STABLE",
        ))
    return arts


def main():
    print("listing subpages ...")
    subs = [t for t in list_subpages() if t.startswith(PREFIX)]
    print(f"  {len(subs)} subpages")
    wt = fetch_wikitext(subs)
    print(f"  fetched {len(wt)} pages")
    seen, articles = {}, []
    for title, text in wt.items():
        for a in parse_page(title, text):
            if a.number not in seen:  # first wins
                seen[a.number] = True
                articles.append(a)
    articles.sort(key=lambda a: (int(re.match(r"\d+", a.number).group()), a.number))
    print(f"  parsed {len(articles)} unique articles")

    out_jsonl = Path("/app/data/processed/all_articles_it.jsonl")
    out_jsonl.parent.mkdir(parents=True, exist_ok=True)
    from dataclasses import asdict
    with out_jsonl.open("w", encoding="utf-8") as fh:
        for a in articles:
            fh.write(json.dumps(asdict(a), ensure_ascii=False) + "\n")
    print(f"  jsonl -> {out_jsonl}")

    idx = ArticleIndex.build(articles)
    idx.save(Path("/app/data/index/bm25_it.pkl"))
    print(f"  index -> /app/data/index/bm25_it.pkl ({len(articles)} articles)")

    # spot-checks
    by_num = {a.number: a for a in articles}
    for n in ["1", "1321", "2043", "2697", "832", "2909"]:
        a = by_num.get(n)
        print(f"  art.{n}: " + (f"{a.heading[:55]!r} | {a.body[:60]!r}" if a else "MANCANTE"))


if __name__ == "__main__":
    main()
