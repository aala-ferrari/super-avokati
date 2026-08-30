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
    "kodi i procedurës administrative": "kodi_proc_admin",
    "kodit të procedurës administrative": "kodi_proc_admin",
    "kodi i procedures administrative": "kodi_proc_admin",
    "kodit te procedures administrative": "kodi_proc_admin",

    "kodi i familjes": "kodi_familjes",
    "kodit të familjes": "kodi_familjes",
    "kodin e familjes": "kodi_familjes",

    "kodi i punës": "kodi_punes",
    "kodit të punës": "kodi_punes",
    "kodi i punes": "kodi_punes",
    "kodit te punes": "kodi_punes",
    "kodin e punës": "kodi_punes",
    "kodin e punes": "kodi_punes",

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
    "ligji i policisë së shtetit": "ligji_policia_2024",
    "ligji per policine e shtetit": "ligji_policia_2024",
    "ligji i policise se shtetit": "ligji_policia_2024",
    "ligji i policisë": "ligji_policia_2024",
    "ligji i policise": "ligji_policia_2024",
    "ligji per policine": "ligji_policia_2024",
    "policinë e shtetit": "ligji_policia_2024",
    "policisë së shtetit": "ligji_policia_2024",
    "policia e shtetit": "ligji_policia_2024",
    "rregullorja e policisë së shtetit": "rregullore_policia",
    "rregullore e policisë së shtetit": "rregullore_policia",
    "rregullorja e policisë": "rregullore_policia",
    "rregullore e policisë": "rregullore_policia",
    "rregullores së policisë": "rregullore_policia",
    "rregullorja e policise": "rregullore_policia",
    "ligji për policinë e shtetit": "ligji_policia_2024",
    "ligjit për policinë e shtetit": "ligji_policia_2024",
    "ligjit i policisë": "ligji_policia_2024",
    "ligji i policise": "ligji_policia_2024",
}

# The 5 special laws are most often cited by statute number ("ligji nr. 9901"),
# not by name. Map the canonical numbers to the corpus keys.
_LAW_NUMBER_ALIASES: dict[str, str] = {
    "9901": "ligji_shoqerite_tregtare",   # shoqëritë tregtare
    "8901": "ligji_falimentimi",          # falimentimi (klasik)
    "9887": "ligji_te_dhenat",            # mbrojtja e të dhënave personale
    "9902": "ligji_konsumatoret",         # mbrojtja e konsumatorëve
    "9723": "ligji_qkb",                  # QKB
    "108": "ligji_policia",              # Policia e Shtetit (108/2014)
    "750": "rregullore_policia",         # Rregullore Policia (VKM 750/2015)
    "82": "ligji_policia_2024",          # Policia e Shtetit (aktual, 82/2024)
}
_LAW_NUM_RE = re.compile(r"ligj\w*\s+(?:nr\.?\s*)?(\d{2,5})", re.IGNORECASE)

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
    "ligji_policia": "Ligji Policia 108/2014",
    "ligji_policia_2024": "Ligji Policia 82/2024",
    "rregullore_policia": "Rregullore Policia",
    # ── corpus italiano ──
    "codice_civile": "c.c.",
    "codice_penale": "c.p.",
    "codice_procedura_civile": "c.p.c.",
    "codice_procedura_penale": "c.p.p.",
    "costituzione": "Cost.",
    "disp_att_cc": "disp. att. c.c.",
    "disp_att_cpp": "disp. att. c.p.p.",
    "codice_strada": "C.d.S.",
    "regolamento_strada": "Reg. C.d.S.",
    "codice_consumo": "Cod. Consumo",
    "codice_crisi_impresa": "CCII",
    "ordinamento_polizia": "L. 121/1981",
    "tulps": "TULPS",
    "statuto_lavoratori": "Stat. Lav.",
    "sicurezza_lavoro": "TU Sicurezza",
    "tu_bancario": "TUB",
    "tu_finanza": "TUF",
    "codice_proprieta_industriale": "C.P.I.",
    "codice_terzo_settore": "CTS",
    "codice_assicurazioni": "Cod. Ass.",
    "responsabilita_enti": "D.Lgs 231/2001",
    "procedimento_amministrativo": "L. 241/1990",
    "codice_processo_amministrativo": "c.p.a.",
    "codice_amministrazione_digitale": "CAD",
    "tu_documentazione_amministrativa": "DPR 445/2000",
    "codice_contratti_pubblici": "Cod. Contratti",
    "sanzioni_amministrative": "L. 689/1981",
    "tu_spese_giustizia": "TU Spese Giust.",
    "codice_privacy": "Cod. Privacy",
    "codice_ambiente": "TUA",
    "tu_edilizia": "TU Edilizia",
    "tu_immigrazione": "TU Immigrazione",
    "codice_antimafia": "Cod. Antimafia",
    "tuir": "TUIR",
    "codice_beni_culturali": "Cod. Beni Cult.",
    "codice_navigazione": "Cod. Nav.",
    "stupefacenti": "DPR 309/1990",
    "ordinamento_penitenziario": "Ord. Pen.",
    "codice_pari_opportunita": "Cod. Pari Opp.",
    "codice_protezione_civile": "Cod. Prot. Civ.",
    "divorzio": "L. 898/1970",
    "adozione": "L. 184/1983",
    "equa_riparazione": "Legge Pinto",
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

# One article-number token: "132", "132/a", "132/1", "132-a", "4/1/2".
_NUM_TOKEN = r"\d+(?:[/\-\u2013][a-zA-Z\u00e7\u00eb\u00c7\u00cb0-9]{1,4})*"
# Enumerated-list separators: "nenet 134, 135 dhe 136 të Kodit Penal".
_LIST_SEP = r"(?:\s*(?:,|;|\bdhe\b|\be\b)\s*)"

CITATION_RE = re.compile(
    r"\bnen(?:i|in|it|et|eve|ve)?\b\s+"
    r"(?P<nums>" + _NUM_TOKEN + r"(?:" + _LIST_SEP + _NUM_TOKEN + r")*)"
    # Tail = up to 8 words, but never crossing "dhe" or another "nen..." —
    # otherwise one citation swallows the next and steals its code.
    r"(?P<tail>(?:\s+(?!nen(?:i|in|it|et|eve|ve)?\b)(?!dhe\b)[^\s,;:\n()]+){0,8})",
    re.IGNORECASE,
)
# Pull each individual number out of a (possibly enumerated) nums block.
_NUM_RE = re.compile(_NUM_TOKEN)

# Detect a code alias inside the tail. We use word boundaries so "kpc" inside
# "skpcial" wouldn't match (no risk in practice but cheap insurance).
# The alias keys are sorted longest-first so multi-word forms win over short
# abbreviations when both appear in the same tail.
_ALIAS_PATTERNS = sorted(CODE_ALIASES.keys(), key=len, reverse=True)
_ALIAS_RE = re.compile(
    r"\b(" + "|".join(re.escape(a) for a in _ALIAS_PATTERNS) + r")\b",
    re.IGNORECASE,
)


# ── Italian citations (art. N c.c./c.p./c.p.c./c.p.p./Cost.) ─────────────────
_NUM_TOKEN_IT = r"\d+(?:[\-\s](?:bis|ter|quater|quinquies|sexies|septies|octies|novies|decies))?"
CITATION_RE_IT = re.compile(
    r"\bart(?:t|icol[oi])?\.?\s+"
    r"(?P<nums>" + _NUM_TOKEN_IT + r"(?:\s*(?:,|;|\be\b|\bed\b)\s*" + _NUM_TOKEN_IT + r")*)"
    r"(?P<tail>(?:\s+(?!art\b)[^\s,;:\n()]+){0,6})",
    re.IGNORECASE,
)
_NUM_RE_IT = re.compile(_NUM_TOKEN_IT)
# Ordered longest/most-specific first so cpc/cpp beat cp, codice* beats abbrevs.
_IT_CODE_CHECKS = [
    # ── full names first (most specific wins) ──
    ("ordinamentodellamministrazionedellapubblicasicurezza", "ordinamento_polizia"),
    ("testounicodocumentazioneamministrativa", "tu_documentazione_amministrativa"),
    ("testounicodelleleggidipubblicasicurezza", "tulps"),
    ("testounicodelleimpostesuiredditi", "tuir"),
    ("codicedellamministrazionedigitale", "codice_amministrazione_digitale"),
    ("codicedelprocessoamministrativo", "codice_processo_amministrativo"),
    ("codicedellaproprietaindustriale", "codice_proprieta_industriale"),
    ("codicedelleassicurazioniprivate", "codice_assicurazioni"),
    ("testounicospesedigiustizia", "tu_spese_giustizia"),
    ("codicedellaprotezionecivile", "codice_protezione_civile"),
    ("codicedellepariopportunita", "codice_pari_opportunita"),
    ("codicedeicontrattipubblici", "codice_contratti_pubblici"),
    ("codicedelleassicurazioni", "codice_assicurazioni"),
    ("codicedellacrisidimpresa", "codice_crisi_impresa"),
    ("codicedidiprocedurapenale", "codice_procedura_penale"),
    ("codicediprocedurapenale", "codice_procedura_penale"),
    ("codicediproceduracivile", "codice_procedura_civile"),
    ("ordinamentopenitenziario", "ordinamento_penitenziario"),
    ("codicedeibeniculturali", "codice_beni_culturali"),
    ("testounicosullimmigrazione", "tu_immigrazione"),
    ("regolamentodiesecuzione", "regolamento_strada"),
    ("codicedellanavigazione", "codice_navigazione"),
    ("testounicodellafinanza", "tu_finanza"),
    ("testounicostupefacenti", "stupefacenti"),
    ("testounicoimmigrazione", "tu_immigrazione"),
    ("codicedelterzosettore", "codice_terzo_settore"),
    ("statutodeilavoratori", "statuto_lavoratori"),
    ("testounicosicurezza", "sicurezza_lavoro"),
    ("testounicobancario", "tu_bancario"),
    ("testounicoedilizia", "tu_edilizia"),
    ("codicedellambiente", "codice_ambiente"),
    ("codicedellastrada", "codice_strada"),
    ("codiceantimafia", "codice_antimafia"),
    ("codicedelconsumo", "codice_consumo"),
    ("codiceambiente", "codice_ambiente"),
    ("codiceprivacy", "codice_privacy"),
    ("codicecivile", "codice_civile"),
    ("codicepenale", "codice_penale"),
    ("costituzione", "costituzione"),
    ("leggepinto", "equa_riparazione"),
    # ── abbreviations, longest first ──
    ("tulps", "tulps"),
    ("ccii", "codice_crisi_impresa"),
    ("tuir", "tuir"),
    ("cds", "codice_strada"),
    ("cpp", "codice_procedura_penale"),
    ("cpc", "codice_procedura_civile"),
    ("cpa", "codice_processo_amministrativo"),
    ("cpi", "codice_proprieta_industriale"),
    ("tub", "tu_bancario"),
    ("tuf", "tu_finanza"),
    ("cts", "codice_terzo_settore"),
    ("cp", "codice_penale"),
    ("cc", "codice_civile"),
    ("cost", "costituzione"),
]


def _resolve_code_it(tail: str):
    compact = re.sub(r"[^a-z]", "", (tail or "").lower())
    for pat, code in _IT_CODE_CHECKS:
        if pat in compact:
            return code
    return None


@dataclass
class Citation:
    raw: str                 # the matched substring, e.g. "neni 132 KP"
    number: str              # "132" or "132/a"
    code: str | None         # canonical key, e.g. "kodi_penal", or None
    code_label: str | None   # human label for the badge, or None
    status: str              # "verified" | "fake" | "needs_code"
    candidates: list[dict]   # for needs_code: which codes contain this number
    article_heading: str | None = None  # populated when verified
    volatility: str | None = None            # STABLE/MEDIUM — freshness hint
    last_amendment_date: str | None = None   # last known amendment date


def _normalise_number(n: str) -> str:
    """Normalise '132/A' / '132-a' / '132 / a' → '132/a' (lowercase)."""
    s = n.strip().lower().replace(" ", "")
    s = s.replace("-", "/").replace("\u2013", "/")
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


def _build_lookup_all(index: ArticleIndex) -> dict[tuple[str, str], object]:
    """(code, number) -> Article, INCLUDING repealed ones. Lets us tell a real
    but repealed article apart from a genuinely nonexistent (hallucinated) one."""
    cached = getattr(index, "_citation_lookup_all", None)
    if cached is not None:
        return cached
    table: dict[tuple[str, str], object] = {}
    for art in index.articles:
        table[(art.code, _normalise_number(art.number))] = art
    index._citation_lookup_all = table
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
    # Fold whitespace (newlines, double spaces) so multi-word code aliases
    # like "kodit të procedurës penale" still match when the source wraps
    # mid-phrase ("të Kodit të\nProcedurës Penale").
    flat = re.sub(r"\s+", " ", tail.lower())
    m = _ALIAS_RE.search(flat)
    if m:
        return CODE_ALIASES.get(m.group(1).lower())
    # No named code — try a special law cited by number ("ligji nr. 9901").
    lm = _LAW_NUM_RE.search(flat)
    if lm:
        return _LAW_NUMBER_ALIASES.get(lm.group(1))
    return None


def _verify_number(lookup: dict, code: str, number: str):
    """Resolve an article, tolerant of paragraph/range notation.

    Albanian citations write paragraphs as "134/1" (paragraph 1 of art. 134)
    and ranges as "379-390". Neither is a distinct article number, so an exact
    lookup misses and a valid citation would be flagged "fake". We fall back to
    the base article and, for ranges, the range endpoints — a conservative
    move that kills false-fakes without inventing anything.
    """
    art = lookup.get((code, number))
    if art is not None:
        return art
    if "/" in number:
        parts = number.split("/")
        base, first = parts[0], parts[1]
        # Only a NUMERIC first suffix is a paragraph/range of the base article
        # ("134/1" -> 134, "379/390" -> 379, "4/1/2" -> 4). A LETTER suffix
        # ("134/a") is a DISTINCT inserted article — never collapse it to the
        # base. And never resolve the suffix itself as a standalone article:
        # that green-lit hallucinations like "480/5" -> real art. 5.
        if first.isdigit():
            art = lookup.get((code, base))
            if art is not None:
                return art
        else:
            # Suffisso-LETTERA. Due casi che si scrivono uguale:
            #
            #   «149/a» → articolo inserito a se' (Shkelja e te drejtave te
            #             pronesise industriale). Sta nel lookup, e l'abbiamo
            #             gia' trovato sopra.
            #   «432/c» → la lettera c) e' un COMMA dentro l'articolo 432
            #             («per shkelje procedurale...»). Non e' un articolo,
            #             ma la citazione e' correttissima.
            #
            # Il secondo caso finiva "fake", e all'avvocato compariva un
            # «nen fantazme» su una citazione giusta e decisiva. Per
            # distinguerli non si indovina: si guarda se quel comma c'e'
            # davvero scritto nel testo dell'articolo base.
            padre = lookup.get((code, base))
            if padre is not None and _lettera_e_un_koma(padre, first):
                return padre
            # «149/a/2» = comma 2 dell'articolo 149/a. Prima di arrendersi si
            # prova la coppia base+lettera, che puo' essere un articolo vero.
            if len(parts) > 2:
                art = lookup.get((code, base + "/" + first))
                if art is not None:
                    return art
    return None


def _lettera_e_un_koma(article, lettera: str) -> bool:
    """La lettera e' davvero un comma scritto dentro questo articolo?

    Si cerca il marcatore come lo stampa il codice — «c)» a inizio comma —
    nel corpo e nella rubrica. Se non c'e', la citazione resta falsa: cosi'
    un «neni 432/z» inventato continua a cadere, perche' nel 432 non esiste
    nessuna lettera z.
    """
    if article is None:
        return False
    lettera = (lettera or "").strip().lower()
    if not lettera or len(lettera) > 2 or not lettera.isalpha():
        return False
    testo = ((getattr(article, "body", "") or "") + " " +
             (getattr(article, "heading", "") or "")).lower()
    if not testo.strip():
        return False
    return re.search(r"(?:^|[\s;,.])%s\s*[)\]]" % re.escape(lettera),
                     testo) is not None


def _codes_for_number(num_to_codes: dict, number: str,
                      lookup_koma: dict | None = None) -> list:
    """Candidate codes for a bare number, tolerant of paragraph/range form.

    `lookup_koma` — (code, number) → Article — serve per il caso «432/c»
    scritto senza nominare il codice: un codice diventa candidato solo se in
    quel codice l'articolo base contiene davvero la lettera come comma.
    Senza questo controllo si aprirebbe la maglia a qualunque lettera; con
    questo, «432/z» resta senza candidati e quindi falso.
    """
    codes = list(num_to_codes.get(number, []))
    if not codes and "/" in number:
        parts = number.split("/")
        base = parts[0]
        if len(parts) > 1 and parts[1].isdigit():
            codes = list(num_to_codes.get(base, []))
        elif len(parts) > 1 and lookup_koma is not None:
            lettera = parts[1]
            # prima: «149/a» come articolo inserito a se'
            codes = list(num_to_codes.get(base + "/" + lettera, []))
            if not codes:
                # poi: la lettera come comma dentro l'articolo base
                codes = [c for c in num_to_codes.get(base, [])
                         if _lettera_e_un_koma(lookup_koma.get((c, base)), lettera)]
    return codes


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
    lookup_all = _build_lookup_all(index)
    num_to_codes = _build_number_to_codes(index)
    retrieved_codes = set(retrieved_codes or [])

    # V-IT: Italian corpus -> Italian citation extraction (art. N c.c. ...).
    _lang = getattr(index, "lang", "sq")
    _cite_re = CITATION_RE_IT if _lang == "it" else CITATION_RE
    _num_re = _NUM_RE_IT if _lang == "it" else _NUM_RE
    _resolve = _resolve_code_it if _lang == "it" else _resolve_code
    _cite_prefix = "art. " if _lang == "it" else "neni "

    seen: set[tuple[str, str]] = set()  # dedupe (number, code-or-empty)
    citations: list[Citation] = []

    def _emit(number: str, code: str | None, raw: str) -> None:
        """Classify one (number, code) pair and append its Citation."""
        if code:
            art = _verify_number(lookup, code, number)
            if art is not None:
                citations.append(Citation(
                    raw=raw, number=number, code=code,
                    code_label=CODE_LABELS.get(code, code),
                    status="verified", candidates=[],
                    article_heading=getattr(art, "heading", None),
                ))
                return
            rart = _verify_number(lookup_all, code, number)
            if rart is not None:
                # exists in this code but REPEALED — real, not hallucinated
                citations.append(Citation(
                    raw=raw, number=number, code=code,
                    code_label=CODE_LABELS.get(code, code),
                    status="repealed", candidates=[],
                    article_heading=getattr(rart, "heading", None),
                ))
                return
            citations.append(Citation(
                raw=raw, number=number, code=code,
                code_label=CODE_LABELS.get(code, code),
                status="fake", candidates=[],
            ))
            return
        candidate_codes = _codes_for_number(num_to_codes, number, lookup_all)
        # Promotion via retrieval context: if exactly one candidate appears in
        # the retrieved set, we treat it as verified.
        in_ctx = [c for c in candidate_codes if c in retrieved_codes]
        if len(in_ctx) == 1:
            code_resolved = in_ctx[0]
            art = _verify_number(lookup, code_resolved, number)
            citations.append(Citation(
                raw=raw, number=number, code=code_resolved,
                code_label=CODE_LABELS.get(code_resolved, code_resolved),
                status="verified", candidates=[],
                article_heading=getattr(art, "heading", None),
            ))
        elif candidate_codes:
            citations.append(Citation(
                raw=raw, number=number, code=None, code_label=None,
                status="needs_code",
                candidates=[{"code": c, "label": CODE_LABELS.get(c, c)}
                            for c in candidate_codes[:6]],
            ))
        else:
            # Number not present in any code in our corpus → fake.
            citations.append(Citation(
                raw=raw, number=number, code=None,
                code_label=None, status="fake", candidates=[],
            ))

    for m in _cite_re.finditer(text):
        nums_block = m.group("nums")
        tail = m.group("tail") or ""
        code = _resolve(tail)              # one shared code for the list
        numbers = _num_re.findall(nums_block)
        full_raw = text[m.start():m.end()].strip()
        if len(full_raw) > 60:
            full_raw = full_raw[:60].rstrip() + "…"
        multi = len(numbers) > 1
        for number_raw in numbers:
            number = _normalise_number(number_raw)
            key = (number, code or "")
            if key in seen:
                continue
            seen.add(key)
            # In a list each article gets its own clean label; a lone citation
            # keeps the full matched span for context.
            raw = (_cite_prefix + number_raw) if multi else full_raw
            _emit(number, code, raw)

    for _c in citations:
        if _c.status in ("verified", "repealed") and _c.code:
            _a = (_verify_number(lookup, _c.code, _c.number)
                  or _verify_number(lookup_all, _c.code, _c.number))
            if _a is not None:
                _c.volatility = getattr(_a, "volatility", None)
                _c.last_amendment_date = getattr(_a, "last_amendment_date", None)
    stats = {
        "verified": sum(1 for c in citations if c.status == "verified"),
        "fake": sum(1 for c in citations if c.status == "fake"),
        "repealed": sum(1 for c in citations if c.status == "repealed"),
        "needs_code": sum(1 for c in citations if c.status == "needs_code"),
        "stale": sum(1 for c in citations if c.status == "verified"
                     and (c.volatility or "").upper() == "MEDIUM"),
        "total": len(citations),
    }
    return {
        "items": [asdict(c) for c in citations],
        "stats": stats,
    }
