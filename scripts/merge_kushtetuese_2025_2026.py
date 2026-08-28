#!/usr/bin/env python3
"""Add Constitutional Court 2025-2026 decisions to the live index.

Safe flow:
 1. parse the freshly-downloaded kushtetuese refs (rule-based, fast)
 2. keep only 2025/2026 (the genuinely new ones)
 3. append them to the COMPLETE all_decisions.jsonl (1095) → ~1258
 4. rebuild the BM25 decisions index from the complete jsonl
 5. print verification (count + by-court + a 2025 sample)

Run inside the container:  PYTHONPATH=/app python3 merge_kushtetuese_2025_2026.py
Backups are made by the caller before running. Nothing is deleted here.
"""
import json
from dataclasses import asdict

import src.jurisprudence_parser as jp
from src.config import court_by_code

JSONL = "data/processed/all_decisions.jsonl"


def norm(rel: str) -> str:
    rel = (rel or "").strip().replace("\\", "/")
    i = rel.find("jurisprudence/")
    if i >= 0:
        rel = rel[i + len("jurisprudence/"):]
    return rel.lstrip("/")


# 1-2. parse + keep only 2025/2026
decs = jp.parse_court(court_by_code("kushtetuese"))
new = [d for d in decs if str(d.year) in ("2025", "2026")]
print(f"parsed={len(decs)}  new(2025-2026)={len(new)}")

# existing numbers already in the jsonl (avoid duplicates)
have = set()
with open(JSONL, encoding="utf-8") as f:
    existing = [json.loads(l) for l in f if l.strip()]
for o in existing:
    have.add((o.get("court_code"), str(o.get("number")), str(o.get("year"))))

added = 0
with open(JSONL, "a", encoding="utf-8") as f:
    for d in new:
        rec = asdict(d) if not isinstance(d, dict) else dict(d)
        rec["source_file"] = norm(rec.get("source_file"))
        key = (rec.get("court_code"), str(rec.get("number")), str(rec.get("year")))
        if key in have:
            continue
        have.add(key)
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        added += 1
print(f"appended={added} → {JSONL}")

# 4. rebuild index from the COMPLETE jsonl
import src.retrieval as r
di = r.DecisionIndex.from_jsonl()
import collections
by = collections.Counter(getattr(x, "court_short_sq", "?") for x in di.decisions)
print("rebuilt index total:", len(di.decisions))
print("by court:", dict(by))
# persist
di.save()
print("saved new bm25_decisions.pkl")
