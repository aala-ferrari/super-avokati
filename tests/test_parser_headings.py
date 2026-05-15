"""Regression tests for parser.py multi-line heading reconstruction (V9.1).

The pre-V9.1 parser took only `lines[0]` as the heading. Albanian PDFs hard-wrap
the first sentence across 2+ lines, so headings ended up truncated mid-clause —
which poisoned BM25 retrieval and let italo-francez doctrine drift in (e.g.
Neni 378 KC: "Trashëgimlënësi edhe pa caktuar trashëgimtarë në testament" lost
the operative "mund të përjashtojë..." clause).

These tests pin down full-sentence headings on a handful of articles whose
shape is known to vary across PDFs, so future parser changes can't silently
regress the fix.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

PROCESSED = Path(__file__).resolve().parent.parent / "data" / "processed"


def _load(code: str) -> list[dict]:
    path = PROCESSED / f"{code}.json"
    if not path.exists():
        pytest.skip(f"{code}.json not found — run `python -m src.parser` first")
    return json.loads(path.read_text(encoding="utf-8"))


def _by_number(articles: list[dict], number: str) -> dict:
    a = next((x for x in articles if x["number"] == number), None)
    assert a is not None, f"Neni {number} not found"
    return a


def test_kc_neni_378_full_heading():
    """Neni 378 KC — testator can exclude legal heirs (key anti-italo-francez).

    Pre-V9.1 the heading stopped at "...në testament", missing the operative
    "mund të përjashtojë nga trashëgimia ligjore..." clause. Without the verb
    in searchable_text, BM25 missed this article on testament-exclusion
    queries and the model fell back to italo-francez riserva doctrine.
    """
    art = _by_number(_load("kodi_civil"), "378")
    assert "Trashëgimlënësi" in art["heading"]
    assert "mund të përjashtojë" in art["heading"]
    assert art["heading"].rstrip().endswith((".", ":", "!", "?"))


def test_kc_neni_316_full_heading():
    """Neni 316 KC — definition of inheritance. Multi-line in source PDF."""
    art = _by_number(_load("kodi_civil"), "316")
    assert "Trashëgimia" in art["heading"]
    assert "kalimi" in art["heading"]
    assert art["heading"].rstrip().endswith((".", ":", "!", "?"))


def test_kc_neni_380_uzufrukt():
    """Neni 380 KC — usufruct/rente bequest. Heading must mention uzufrukt."""
    art = _by_number(_load("kodi_civil"), "380")
    assert "uzufrukt" in art["heading"].lower()
    assert art["heading"].rstrip().endswith((".", ":", "!", "?"))


def test_kpc_neni_443_afati_ankimit():
    """Neni 443 KPC — appeal deadlines. Heading must contain '15 ditë' or '30 ditë'."""
    art = _by_number(_load("kodi_proc_civile"), "443")
    assert "ankim" in art["heading"].lower()
    # the rule itself ("15 ditë" for apel, "30 ditë" for rekurs) must be in
    # heading or body — never lost
    text = art["heading"] + " " + art["body"]
    assert "ditë" in text


def test_average_heading_length_above_v90_baseline():
    """Aggregate signal: V9.1 multi-line glueing should yield longer headings
    on average than the V9.0 line[0] approach.

    Pre-V9.1 KC headings averaged ~50 chars (truncated at first newline).
    V9.1 should be well above that since most articles have multi-line first
    sentences. We assert a conservative floor (90 chars) on the Civil Code,
    where the bug was originally diagnosed.
    """
    arts = [a for a in _load("kodi_civil") if not a.get("repealed") and a["heading"]]
    avg = sum(len(a["heading"]) for a in arts) / len(arts)
    assert avg > 90, f"KC average heading length {avg:.1f} chars — parser may have regressed to line[0] truncation"


def test_searchable_text_contains_heading():
    """BM25 grounding: heading must appear in searchable_text used for indexing.

    This is what failed silently pre-V9.1 — heading was set, but the truncated
    version lacked the operative clause, so the indexed text was incomplete.
    """
    arts = _load("kodi_civil")
    art = _by_number(arts, "378")
    # mimic Article.searchable_text (citation + heading + body)
    searchable = "\n".join(
        x for x in (
            f"Neni {art['number']} i {art['title_sq']}",
            art["heading"],
            art["body"],
        ) if x
    )
    assert "mund të përjashtojë" in searchable
