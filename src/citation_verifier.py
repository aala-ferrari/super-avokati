"""V7.13 — Provenance lock: verify every legal citation in the model output.

For a lawyer, an unverified citation is a landmine. After the brain produces
its Albanian answer, we extract every ``Neni N <kodi>`` pattern and check it
against the BM25 index. Each citation gets one of three statuses:

    verified        — exact (code, number) match in the corpus
    fake            — code given but article number not in that code
    needs_code      — number given without code; we list candidate codes

The result is attached to the API response as ``citations`` so the UI can
show a trust badge ("✓ 4 të verifikuara · ⚠ 1 e paverifikuar") and turn each
citation into a clickable provenance link to the source article.

The verifier is a pure function of (text, index) — no side effects, no LLM.
"""
from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import asdict, dataclass

from .retrieval import ArticleIndex

# ── Code aliases ────────────────────────────────────────────────────────────
# Maps the spoken/written form Albanian lawyers use → the internal corpus key.
# Order matters for the regex (longer phrases first), but the lookup is a
# straight dict so we just normalise via lower() + strip first.
#
# Genitive/dative endings (-it, -ës, -in, -ut) are normalised here so that
# "Kodit Penal", "Kodi Penal", "Kodin Penal" all resolve the same.

CODE_ALIASES: dict[str, str] = {
    # Short abbreviations (uppercase or lowercase in source — we lowercase)
    "kp": "kodi_penal",
    "kpp": "kodi_proc_penale",
    "kpr.p": "kodi_proc_penale",
    "kpr p": "kodi_proc_penale",
    "kc": "kodi_civil",
    "kpc": "kodi_proc_civile",
    "kpr.c": "kodi_proc_civile",
    "kpr c": "kodi_proc_civile",
    "kpa": "kodi_proc_admin",
    "kf": "kodi_familjes",
    "kpu": "kodi_punes",
    "kpun": "kodi_punes",
    "kr": "kodi_rrugor",
    "kd": "kodi_doganor",
    "kdog": "kodi_doganor",
    "kdt": "kodi_detar",
    "kdet": "kodi_detar",
    "kz": "kodi_zgjedhor",
    "kzgj": "kodi_zgjedhor",
    "ka": "kodi_ajror",

    # Spelled-out — keep all common case-form variants
    "kodi penal": "kodi_penal",
    "kodit penal": "kodi_penal",
    "kodin penal": "kodi_penal",

    "kodi civil": "kodi_civil",
    "kodit civil": "kodi_civil",
    "kodin civil": "kodi_civil",

    "kodi i procedurës penale": "kodi_proc_penale",
    "kodit të procedurës penale": "kodi_proc_penale",
    "kodi i procedures penale": "kodi_proc_penale",
    "kodit te procedures penale": "kodi_proc_penale",

    "kodi i procedurës civile": "kodi_proc_civile",
    "kodit të procedurës civile": "kodi_proc_civile",
    "kodi i procedures civile": "kodi_proc_civile",
    "kodit te procedures civile": "kodi_proc_civile",

    "kodi i procedurave administrative": "kodi_proc_admin",
    "kodit të procedurave administrative": "kodi_proc_admin",
    "kodi procedures administrative": "kodi_proc_admin",

    "kodi i familjes": "kodi_familjes",
    "kodit të familjes": "kodi_familjes",

    "kodi i punës": "kodi_punes",
    "kodit të punës": "kodi_punes",
    "kodi i punes": "kodi_punes",
    "kodit te punes": "kodi_punes",

    "kodi rrugor": "kodi_rrugor",
    "kodit rrugor": "kodi_rrugor",
    "kodi doganor": "kodi_doganor",
    "kodit doganor": "kodi_doganor",
    "kodi detar": "kodi_detar",
    "kodit detar": "kodi_detar",
    "kodi zgjedhor": "kodi_zgjedhor",
    "kodit zgjedhor": "kodi_zgjedhor",
    "kodi ajror": "kodi_ajror",
    "kodit ajror": "kodi_ajror",

    "kushtetuta": "kushtetuta",
    "kushtetutës": "kushtetuta",
    "kushtetutes": "kushtetuta",
    "kushtetutën": "kushtetuta",
    "kushtetuten": "kushtetuta",

    # The 4 special ligji — citation form usually quotes the law number,
    # but lawyers also use these short names colloquially.
    "ligji i falimentimit": "ligji_falimentimi",
    "ligji i shoqërive tregtare": "ligji_shoqerite_tregtare",
    "ligji shoqërive tregtare": "ligji_shoqerite_tregtare",
    "ligji i konsumatorëve": "ligji_konsumatoret",
    "ligji per mbrojtjen e konsumatoreve": "ligji_konsumatoret",
    "ligji i të dhënave personale": "ligji_te_dhenat",
    "ligji i te dhenave personale": "ligji_te_dhenat",
    "ligji i qkb": "ligji_qkb",
    "ligji per qkb": "ligji_qkb",
}

# Human-readable label per code → shown in the UI badge.
CODE_LABELS: dict[str, str] = {
    "kodi_penal": "Kodi Penal",
    "kodi_proc_penale": "K. Proc. Penale",
    "kodi_civil": "Kodi Civil",
    "kodi_proc_civile": "K. Proc. Civile",
    "kodi_proc_admin": "K. Proc. Adm.",
    "kodi_familjes": "Kodi i Familjes",
    "kodi_punes": "Kodi i Punës",
    "kodi_rrugor": "Kodi Rrugor",
    "kodi_doganor": "Kodi Doganor",
    "kodi_detar": "Kodi Detar",
    "kodi_zgjedhor": "Kodi Zgjedhor",
    "kodi_ajror": "Kodi Ajror",
    "kushtetuta": "Kushtetuta",
    "ligji_falimentimi": "Ligji Falimentimi",
    "ligji_shoqerite_tregtare": "Ligji Shoq. Tregtare",
    "ligji_konsumatoret": "Ligji Konsumatorët",
    "ligji_te_dhenat": "Ligji Mbr. Dhënash",
    "ligji_qkb": "Ligji QKB",
}


# ── Citation regex ─────────────────────────────────────────────────────────
# Matches "neni|nenin|nenit|nenet  N(/sub)?  [optional code-tail]".
# The article number admits common Albanian forms:
#   simple:    132
#   slash:     132/a, 132/1, 132-a
#   sub-list:  132 paragrafi 2 (we just capture 132 here; the model usually
#              writes the paragraph spelled out which we ignore for matching)
#
# We deliberately keep the tail-capture small (≤ 60 chars) so we don't drag
# the next sentence in as if it were the code. The tail is then probed for
# a known code alias.

CITATION_RE = re.compile(
    r"\bnen(?:i|in|it|et|eve|ve)?\b\s+(\d+(?:[/\-][a-zA-Z0-9]{1,4})?)"
    r"(?P<tail>(?:\s+[^.,;:\n()]{0,60})?)",
    re.IGNORECASE,
)

# Detect a code alias inside the tail. We use word boundaries so "kpc" inside
# "skpcial" wouldn't match (no risk in practice but cheap insurance).
# The alias keys are sorted longest-first so multi-word forms win over short
# abbreviations when both appear in the same tail.
_ALIAS_PATTERNS = sorted(CODE_ALIASES.keys(), key=len, reverse=True)
_ALIAS_RE = re.compile(
    r"\b(" + "|".join(re.escape(a) for a in _ALIAS_PATTERNS) + r")\b",
    re.IGNORECASE,
)


@dataclass
class Citation:
    raw: str                 # the matched substring, e.g. "neni 132 KP"
    number: str              # "132" or "132/a"
    code: str | None         # canonical key, e.g. "kodi_penal", or None
    code_label: str | None   # human label for the badge, or None
    status: str              # "verified" | "fake" | "needs_code"
    candidates: list[dict]   # for needs_code: which codes contain this number
    article_heading: str | None = None  # populated when verified


def _normalise_number(n: str) -> str:
    """Normalise '132/A' / '132-a' / '132 / a' → '132/a' (lowercase)."""
    s = n.strip().lower().replace(" ", "")
    s = s.replace("-", "/")
    return s


def _build_lookup(index: ArticleIndex) -> dict[tuple[str, str], object]:
    """(code, normalised_number) → Article. Cached on the index instance."""
    cached = getattr(index, "_citation_lookup", None)
    if cached is not None:
        return cached
    table: dict[tuple[str, str], object] = {}
    for art in index.articles:
        if art.repealed:
            continue
        table[(art.code, _normalise_number(art.number))] = art
    index._citation_lookup = table
    return table


def _build_number_to_codes(index: ArticleIndex) -> dict[str, list[str]]:
    """normalised_number → [codes that have an article with that number]."""
    cached = getattr(index, "_citation_num_index", None)
    if cached is not None:
        return cached
    table: dict[str, list[str]] = defaultdict(list)
    for art in index.articles:
        if art.repealed:
            continue
        table[_normalise_number(art.number)].append(art.code)
    # de-dup while preserving order
    table = {k: list(dict.fromkeys(v)) for k, v in table.items()}
    index._citation_num_index = table
    return table


def _resolve_code(tail: str) -> str | None:
    """Extract a canonical code key from the text right after the article num."""
    if not tail:
        return None
    m = _ALIAS_RE.search(tail.lower())
    if not m:
        return None
    alias = m.group(1).lower()
    return CODE_ALIASES.get(alias)


def verify_text(
    text: str,
    index: ArticleIndex,
    *,
    retrieved_codes: Iterable[str] | None = None,
) -> dict:
    """Scan ``text`` for ``Neni N <code>`` patterns and verify each one.

    ``retrieved_codes`` is the set of codes that the BM25 retrieval surfaced
    for the user's query — if a "needs_code" citation has exactly one
    candidate code that's also in retrieved_codes, we promote it to "verified"
    via context (the model very likely meant that one).

    Returns:
        {
            "items": [Citation as dict, ...],
            "stats": {"verified": int, "fake": int, "needs_code": int, "total": int},
        }
    """
    lookup = _build_lookup(index)
    num_to_codes = _build_number_to_codes(index)
    retrieved_codes = set(retrieved_codes or [])

    seen: set[tuple[str, str]] = set()  # dedupe (number, code-or-empty)
    citations: list[Citation] = []

    for m in CITATION_RE.finditer(text):
        number_raw = m.group(1)
        tail = m.group("tail") or ""
        number = _normalise_number(number_raw)
        code = _resolve_code(tail)

        key = (number, code or "")
        if key in seen:
            continue
        seen.add(key)

        raw_match = text[m.start():m.end()].strip()
        # Trim raw to the article + first few words of the tail so the UI
        # has a clean label without the rest of the sentence.
        if len(raw_match) > 60:
            raw_match = raw_match[:60].rstrip() + "…"

        if code:
            art = lookup.get((code, number))
            if art is not None:
                citations.append(Citation(
                    raw=raw_match, number=number, code=code,
                    code_label=CODE_LABELS.get(code, code),
                    status="verified",
                    candidates=[],
                    article_heading=getattr(art, "heading", None),
                ))
            else:
                citations.append(Citation(
                    raw=raw_match, number=number, code=code,
                    code_label=CODE_LABELS.get(code, code),
                    status="fake",
                    candidates=[],
                ))
        else:
            candidate_codes = num_to_codes.get(number, [])
            # Promotion via retrieval context: if exactly one candidate
            # appears in the retrieved set, we treat it as verified.
            in_ctx = [c for c in candidate_codes if c in retrieved_codes]
            if len(in_ctx) == 1:
                code_resolved = in_ctx[0]
                art = lookup.get((code_resolved, number))
                citations.append(Citation(
                    raw=raw_match, number=number, code=code_resolved,
                    code_label=CODE_LABELS.get(code_resolved, code_resolved),
                    status="verified",
                    candidates=[],
                    article_heading=getattr(art, "heading", None),
                ))
            elif candidate_codes:
                citations.append(Citation(
                    raw=raw_match, number=number, code=None,
                    code_label=None,
                    status="needs_code",
                    candidates=[
                        {"code": c, "label": CODE_LABELS.get(c, c)}
                        for c in candidate_codes[:6]
                    ],
                ))
            else:
                # Number not present in any code in our corpus → fake.
                citations.append(Citation(
                    raw=raw_match, number=number, code=None,
                    code_label=None, status="fake", candidates=[],
                ))

    stats = {
        "verified": sum(1 for c in citations if c.status == "verified"),
        "fake": sum(1 for c in citations if c.status == "fake"),
        "needs_code": sum(1 for c in citations if c.status == "needs_code"),
        "total": len(citations),
    }
    return {
        "items": [asdict(c) for c in citations],
        "stats": stats,
    }
