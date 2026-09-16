# -*- coding: utf-8 -*-
"""A/B dello stemming albanese: indice attuale contro indice ricostruito con stem=True (in /tmp).
Misure: test di recupero dello strato 1 (retrieval:al), query «difficili» note (Neni 114, 153 senza
ancore), e le 4 prove del cervello a triage sintetico SENZA ancore (raw search)."""
import json, sys, time
sys.path.insert(0, "/app")
from pathlib import Path
from src.retrieval import ArticleIndex, ARTICLES_JSONL
K = 12
t0 = time.time()
old = ArticleIndex.load(Path("/app/data/index/bm25.pkl"))
new = ArticleIndex.from_jsonl(ARTICLES_JSONL, lang="sq", stem=True)
print(f"indici pronti in {time.time()-t0:.0f}s: old stem={getattr(old,'stem',None)} new stem={new.stem}")
tests = [json.loads(l) for l in open("/app/data/benchmark/layer1_auto.jsonl", encoding="utf-8") if l.strip()]
tests = [t for t in tests if t["kind"] == "retrieval" and t["lang"] == "al"]
def hits(idx, q, exp, k=K):
    got = {(a.code, str(a.number)) for a, _ in idx.search(q, top_k=k)}
    return all(tuple(e) in got for e in exp)
o = sum(hits(old, t["query"], t["expect"]) for t in tests); n = sum(hits(new, t["query"], t["expect"]) for t in tests)
print(f"strato 1 retrieval:al — old {o}/{len(tests)}  new {n}/{len(tests)}")
hard = [
 ("afati i parashkrimit", ("kodi_civil", "114")), ("sa është afati i parashkrimit të padisë", ("kodi_civil", "114")),
 ("parashkrimi i përgjithshëm dhjetë vjet", ("kodi_civil", "114")),
 ("makina bën zhurmë marmita", ("kodi_rrugor", "153")), ("zhurmë e tepërt nga automjeti gjoba", ("kodi_rrugor", "153")),
 ("kufizimi i zhurmave", ("kodi_rrugor", "153")),
 ("pushimi nga puna pa paralajmërim dëmshpërblimi", ("kodi_punes", "155")), ("afati i njoftimit për zgjidhjen e kontratës së punës", ("kodi_punes", "143")),
 ("shpërblimi për vjetërsi në punë", ("kodi_punes", "152")), ("trashëgimia ligjore rendi i parë fëmijët bashkëshorti", ("kodi_civil", "361")),
 ("anulimi i lejes së qëndrimit të huajt", ("ligji_te_huajt", "73")), ("hipoteka mbi pasurinë e paluajtshme", ("kodi_civil", "560")),
 ("zgjidhja e menjëhershme e pajustifikuar e kontratës", ("kodi_punes", "155")), ("dëmi jashtëkontraktor shpërblimi", ("kodi_civil", "608")),
 ("kontrata e qirasë afati", ("kodi_civil", "801")), ("divorci me pëlqim reciprok", ("kodi_familjes", "125")),
]
def rank(idx, q, key, depth=200):
    for i, (a, s) in enumerate(idx.search(q, top_k=depth), 1):
        if (a.code, str(a.number)) == key:
            return i
    return None
print("query difficili (posizione, None = oltre 200):")
wins = 0
for q, key in hard:
    ro, rn = rank(old, q, key), rank(new, q, key)
    mark = "▲" if (rn or 999) < (ro or 999) else ("▼" if (rn or 999) > (ro or 999) else "=")
    wins += 1 if mark == "▲" else (-1 if mark == "▼" else 0)
    print(f"  {mark} {q[:52]:52s} {key[0]:14s} {key[1]:>4}  old={ro}  new={rn}")
print("bilancio difficili:", wins)
