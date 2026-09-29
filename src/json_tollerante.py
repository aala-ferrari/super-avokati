# -*- coding: utf-8 -*-
"""Lettura TOLLERANTE del JSON prodotto dal modello (v9.402).

Misurato (29 set 2026, prova viva della bozza d'atto in sessione IT): il ricorso — 18 mila caratteri di Markdown DENTRO
il campo `body_markdown` — conteneva virgolette non protette («Expecting ',' delimiter: line 9 column 17949») e
l'avvocato riceveva un errore 500 dopo nove minuti di attesa; nei log di produzione la fase «strategic» è andata persa
per una virgola finale. `carica()` prova prima la lettura normale (per un JSON valido NON cambia nulla) e solo se fallisce
ripara i difetti tipici di un modello, senza inventare contenuto:
  1. a capo e tabulazioni crudi dentro le stringhe (`strict=False`);
  2. virgolette INTERNE non protette: dentro una stringa, una «"» è una chiusura vera solo se dopo (spazi a parte) viene
     `}` `]` `:` la fine, oppure una virgola seguita da ciò che in JSON può seguire una virgola (`"`, `{`, `[`, un
     numero, `true`/`false`/`null`, `]`, `}`); altrimenti è una virgoletta del testo e si protegge;
  3. virgole finali prima di `}`/`]`, tolte SOLO fuori dalle stringhe.
Se anche la riparazione fallisce si solleva l'errore ORIGINALE: chi chiama resta com'era."""
from __future__ import annotations

import json
import re

_DOPO_VIRGOLA_OK = re.compile(r'\s*(?:["{\[\]}\-0-9]|true\b|false\b|null\b)')


def _chiusura_vera(s: str, i: int) -> bool:
    """La virgoletta in posizione i chiude davvero la stringa?"""
    j = i + 1
    n = len(s)
    while j < n and s[j] in " \t\r\n":
        j += 1
    if j >= n:
        return True
    c = s[j]
    if c in "}]:":
        return True
    if c == ",":
        return bool(_DOPO_VIRGOLA_OK.match(s, j + 1))
    return False


def ripara(s: str) -> str:
    """Una sola passata: protegge le virgolette interne e toglie le virgole finali fuori dalle stringhe."""
    out: list[str] = []
    in_str = False
    i = 0
    n = len(s)
    while i < n:
        ch = s[i]
        if in_str:
            if ch == "\\" and i + 1 < n:
                out.append(ch)
                out.append(s[i + 1])
                i += 2
                continue
            if ch == '"':
                if _chiusura_vera(s, i):
                    in_str = False
                    out.append(ch)
                else:
                    out.append('\\"')
                i += 1
                continue
            out.append(ch)
            i += 1
            continue
        if ch == '"':
            in_str = True
            out.append(ch)
            i += 1
            continue
        if ch == ",":
            j = i + 1
            while j < n and s[j] in " \t\r\n":
                j += 1
            if j < n and s[j] in "}]":          # virgola finale
                i += 1
                continue
        out.append(ch)
        i += 1
    return "".join(out)


def carica(blob: str):
    """`json.loads`, e se fallisce la stessa lettura dopo la riparazione; altrimenti l'errore originale."""
    try:
        return json.loads(blob)
    except json.JSONDecodeError as orig:
        errore = orig
    try:
        return json.loads(blob, strict=False)
    except json.JSONDecodeError:
        pass
    try:
        return json.loads(ripara(blob), strict=False)
    except json.JSONDecodeError:
        raise errore
