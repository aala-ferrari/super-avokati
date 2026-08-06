"""Verify decision citations in an answer against the LIVE corpus.

Conservative by design: a decision is "verified" only if it exists in our
corpus (definitely real); otherwise "unverified" — we NEVER call a decision
"fake" just because it falls outside our 1258 decisions (the corpus is
incomplete). This powers the "Verifikuar" trust seal alongside article
verification, directly attacking the industry's #1 problem: hallucinated
case law.
"""
from __future__ import annotations

import re

# "Vendim(i/it) nr. <num>/<year>"  — the way Albanian decisions are cited.
_DEC_RE = re.compile(
    r"vendim(?:i|it|in|et|eve)?\s+nr\.?\s*([0-9][0-9A-Za-z\-\/]{0,18})\s*[/\-\u2013]\s*(20\d{2}|19\d{2})",
    re.IGNORECASE,
)


def _norm(n: str) -> str:
    """Digits-only, leading zeros stripped — robust across number formats."""
    d = re.sub(r"[^0-9]", "", n or "")
    return d.lstrip("0") or ("0" if d else "")


def verify_decisions(text: str, kb) -> dict:
    if not text or kb is None or not getattr(kb, "cases", None):
        return {"items": [], "stats": {"verified": 0, "unverified": 0, "total": 0}}

    by_year: dict[int, set[str]] = {}
    for c in kb.cases:
        yr = c.decision_date.year if getattr(c, "decision_date", None) else None
        num = _norm(getattr(c, "case_number", ""))
        if yr and num:
            by_year.setdefault(yr, set()).add(num)

    seen: set[tuple[str, int]] = set()
    items = []
    for m in _DEC_RE.finditer(text):
        num = _norm(m.group(1))
        yr = int(m.group(2))
        key = (num, yr)
        if key in seen or not num:
            continue
        seen.add(key)
        raw = text[m.start():m.end()].strip()
        if len(raw) > 48:
            raw = raw[:48].rstrip() + "…"
        pool = by_year.get(yr, set())
        # exact match, or the cited number contained in a stored one (or vice
        # versa) for the same year — tolerates short vs long number formats.
        # EXACT match only. A substring test ("23" in "123") green-lit
        # hallucinated decisions against any longer real number in that year.
        found = num in pool
        items.append({
            "raw": raw, "number": m.group(1), "year": yr,
            "status": "verified" if found else "unverified",
        })

    v = sum(1 for i in items if i["status"] == "verified")
    return {"items": items,
            "stats": {"verified": v, "unverified": len(items) - v, "total": len(items)}}
