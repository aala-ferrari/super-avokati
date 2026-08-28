#!/usr/bin/env python3
"""Freshness checker for Gjykata e Lartë — compares the court's live archive
against what we already have indexed, and reports genuinely NEW decisions.

Runs inside the super-avvocato container (has httpx + the scraper + the
index). Safe: read-only, no downloads, never touches the index. Meant to be
run monthly by cron so we know the moment the court publishes new rulings
(e.g. the still-missing 2024-2025) and can add them deliberately."""
import collections
import datetime
import json
import sys

import httpx

from src.scrapers.gjykata_elarte import SECTIONS, _parse_title
import pickle

BASE = "https://gjykataelarte.gov.al"


def load_have() -> set:
    d = pickle.load(open("data/index/bm25_decisions.pkl", "rb"))
    return {o.get("number") for o in d["decisions"]
            if o.get("court_short_sq") == "Gjykata e Lartë"}


def fetch_site() -> dict:
    site = {}
    with httpx.Client(timeout=30, headers={"User-Agent": "SuperAvokatiBot/1.0"}) as cl:
        for sec in SECTIONS:
            try:
                body = cl.get(f"{BASE}/page-data/sq/{sec}/page-data.json").json(
                )["result"]["data"]["api"]["article"]["body"] or []
            except Exception as e:  # noqa: BLE001
                print(f"[warn] section {sec}: {e}", file=sys.stderr)
                continue
            for block in body:
                for v in (block.get("vendim") or []):
                    num, dt = _parse_title((v.get("title") or {}).get("text_sq") or "")
                    if num:
                        site[num] = dt.year if dt else 0
    return site


def main() -> None:
    have = load_have()
    site = fetch_site()
    new = {n: y for n, y in site.items() if n not in have}
    stamp = datetime.date(2000, 1, 1)  # placeholder; real date passed by cron via arg
    if len(sys.argv) > 1:
        stamp = sys.argv[1]
    by_year = dict(collections.Counter(new.values()))
    report = {
        "date": str(stamp),
        "have_indexed": len(have),
        "on_site": len(site),
        "new_count": len(new),
        "new_by_year": by_year,
        "new_numbers": sorted(new.keys())[:50],
    }
    print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    main()
