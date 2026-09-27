# -*- coding: utf-8 -*-
"""Motore DETERMINISTICO delle quote successorie — VERIFICA aritmetica.

Come il motore afati (§13): l'LLM fa l'ANALISI giuridica (chi eredita, quale
ordine, rappresentazione, testamento, riserva); questo modulo fa l'ARITMETICA —
le frazioni sommano a 1? i casi CHIARI di divisione in parti uguali tornano?

NON codifica tutta la successione albanese (orari, rappresentazione a più gradi,
riserva, collazione): quelle restano all'analisi del notaio, e l'engine le SEGNALA
invece di indovinare (stesso onesto limite del Bajram nel motore afati). Ciò che
fa, lo fa con `fractions.Fraction` (esatto, niente errori di virgola):
  1. VALIDA che le quote proposte sommino a 1 (l'errore più comune);
  2. per il caso CERTO di 1° ordine (Neni 361 KC: coniuge + figli in PARTI
     UGUALI, il coniuge eredita come un figlio), calcola le frazioni e le
     confronta con quelle proposte.

KUFI JURIDIKSIONAL: divisione per STRUTTURA secondo la legge della SESSIONE — in AL il KC
albanese (Neni 361), MAI quote trapiantate (riserva 50%/75% italo-francese); in IT il codice civile
italiano (artt. 566, 581), mai la regola albanese (v9.395). La riserva (Neni 393 KC / artt. 536 ss.
c.c.) è materia del notaio, non la calcola questo modulo.
"""
from __future__ import annotations

import re
from fractions import Fraction

# righe macchina emesse dall'LLM:
#   PJESA | <trashëgimtari> | <1/3 oppure 33% >
#   STRUKTURA | bashkeshort=0|1 | femije=N | rend=1|2|tjeter
_PJESA_RE = re.compile(
    r"^\s*PJESA\s*\|\s*(?P<heir>.+?)\s*\|\s*(?P<frac>\d+\s*/\s*\d+|\d+(?:[.,]\d+)?\s*%?)\s*$",
    re.MULTILINE)
_STRUKT_RE = re.compile(
    r"^\s*STRUKTURA\s*\|\s*bashkeshort\s*=\s*(?P<sp>[01])\s*\|\s*femije\s*=\s*(?P<ch>\d+)"
    r"\s*\|\s*rend\s*=\s*(?P<rend>[A-Za-zëËçÇ0-9_]+)\s*$", re.MULTILINE)


def to_fraction(s: str):
    """'1/3' → Fraction(1,3); '33%' → Fraction(33,100); '0.5' → Fraction(1,2).
    None se non parsabile o denominatore 0."""
    s = (s or "").strip()
    try:
        if "/" in s:
            a, b = s.split("/", 1)
            b = int(b.strip())
            return Fraction(int(a.strip()), b) if b else None
        if s.endswith("%"):
            return Fraction(s[:-1].strip().replace(",", ".")).limit_denominator(10000) / 100
        return Fraction(s.replace(",", ".")).limit_denominator(10000)
    except (ValueError, ZeroDivisionError):
        return None


def parse_shares(text: str):
    """[(heir, Fraction), ...] dalle righe PJESA."""
    out = []
    for m in _PJESA_RE.finditer(text or ""):
        fr = to_fraction(m.group("frac"))
        if fr is not None:
            out.append((m.group("heir").strip(), fr))
    return out


def parse_structure(text: str):
    """{'spouse':bool,'children':int,'rend':str} o None."""
    m = _STRUKT_RE.search(text or "")
    if not m:
        return None
    return {"spouse": m.group("sp") == "1", "children": int(m.group("ch")),
            "rend": m.group("rend").lower()}


def first_order_shares(spouse: bool, children: int):
    """Caso CERTO (Neni 361 KC): 1° ordine = coniuge + figli in parti UGUALI
    (il coniuge eredita come un figlio). children-only → 1/N ciascuno.
    None se la struttura non è calcolabile con certezza.
    v9.395: senza figli NON è un caso certo — il KC 361 chiama gli ordini successivi e al coniuge
    spetta 1/2 (tutto solo se non c'è nessun altro erede): lo decide il notaio, non l'aritmetica."""
    if int(children) < 1:
        return None
    n = int(children) + (1 if spouse else 0)
    if n <= 0:
        return None
    each = Fraction(1, n)
    out = {}
    if spouse:
        out["Bashkëshorti/ja"] = each
    for i in range(int(children)):
        out["Fëmija %d" % (i + 1)] = each
    return out


def quote_certe_it(spouse: bool, children: int):
    """Quote di legge CERTE nel diritto italiano per coniuge e/o figli (successione legittima, senza
    testamento né rappresentazione): art. 566 c.c. (solo figli: parti uguali), art. 581 c.c. (coniuge
    con un figlio: 1/2 ciascuno; con più figli: coniuge 1/3, figli 2/3 in parti uguali).
    Senza figli (coniuge con ascendenti/fratelli, art. 582-583) non è un caso certo → None."""
    ch = int(children)
    if ch < 1:
        return None
    if not spouse:
        f = Fraction(1, ch)
        return ("art. 566 c.c.", [f] * ch, "i figli succedono in parti uguali → **%s** ciascuno" % f)
    if ch == 1:
        return ("art. 581 c.c.", [Fraction(1, 2), Fraction(1, 2)], "coniuge **1/2**, figlio **1/2**")
    c = Fraction(2, 3) / ch
    return ("art. 581 c.c.", [Fraction(1, 3)] + [c] * ch,
            "coniuge **1/3**, i %d figli si dividono 2/3 → **%s** ciascuno" % (ch, c))


def check(text: str, lang: str = "sq") -> str:
    """Blocco di controllo aritmetico da accodare (o «» se non c'è nulla da dire).
    Valida la somma; per il 1° ordine certo confronta con le frazioni calcolate."""
    shares = parse_shares(text)
    struct = parse_structure(text)
    if not shares and not struct:
        return ""
    it = lang == "it"
    rows = []
    total = sum((f for _, f in shares), Fraction(0))
    if shares:
        if total == 1:
            rows.append(("✅ La somma delle quote = 1 (corretta)." if it
                         else "✅ Shuma e pjesëve = 1 (e saktë)."))
        else:
            rows.append((("⛔ La somma delle quote = %s ≠ 1 — ERRORE da correggere." % total) if it
                         else ("⛔ Shuma e pjesëve = %s ≠ 1 — GABIM për t'u korrigjuar." % total)))
    # caso certo di 1° ordine
    if it and struct and struct.get("rend") in ("1", "pare", "parë", "primo", "i_pare"):
        # v9.395 — in sessione IT valeva la regola ALBANESE (coniuge e figli in parti uguali, Neni 361 KC):
        # in Italia il coniuge ha 1/2 con un figlio e 1/3 con più figli (art. 581 c.c.), e con coniuge e
        # 3 figli il controllo dava per sbagliate le quote italiane giuste (1/3 e 2/9).
        q = quote_certe_it(struct["spouse"], struct["children"])
        if q:
            norma, attese, descr = q
            ok_q = bool(shares) and sorted(f for _, f in shares) == sorted(attese)
            rows.append("Successione legittima (%s): %s." % (norma, descr))
            if shares and not ok_q:
                rows.append("⚠ Le quote proposte NON corrispondono a quelle di legge (%s): verifica."
                            % ", ".join(str(f) for f in sorted(attese, reverse=True)))
    elif struct and struct.get("rend") in ("1", "pare", "parë", "primo", "i_pare"):
        det = first_order_shares(struct["spouse"], struct["children"])
        if det:
            proposed = {h: f for h, f in shares}
            vals_ok = shares and all(f == next(iter(det.values())) for _, f in shares) \
                and len(shares) == len(det)
            each = next(iter(det.values()))
            rows.append("Rasti i radhës së parë (Neni 361 KC): %d trashëgimtarë në pjesë të barabarta → **%s** secili."
                        % (len(det), each))
            if shares and not vals_ok:
                rows.append("⚠ Pjesët e propozuara NUK janë të gjitha %s: verifiko (radha e parë = pjesë të barabarta)." % each)
    if not rows:
        return ""
    head = ("\n\n### 🧮 Controllo aritmetico delle quote (deterministico)\n" if it
            else "\n\n### 🧮 Kontroll aritmetik i pjesëve (determinist)\n")
    note = ("\n_Verifica aritmetica; le regole complesse (rappresentazione, riserva, collazione, testamento) le valuta il notaio._" if it
            else "\n_Kontroll aritmetik; rregullat komplekse (përfaqësim, rezervë, bashkim, testament) i vlerëson noteri._")
    return head + "\n".join("- " + r for r in rows) + note
