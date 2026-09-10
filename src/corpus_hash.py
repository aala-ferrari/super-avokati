# -*- coding: utf-8 -*-
"""Content-hash del corpus + rilevamento cambi (fondazione §1-2-4, §34-35).

IL PIENO di §1-2 (versioning temporale: testo storico di ogni articolo con
valid_from/valid_to) è un problema di DATI — Normattiva/QBZ danno il testo di
OGGI, non la storia degli emendamenti — e resta NORD. Questa è la PRIMA pietra
che serve SUBITO e usa il corpus che già abbiamo: un'impronta SHA-256 per ogni
articolo, così quando un harvester ri-scarica una norma si può DIRE se il testo
ufficiale è cambiato (SOURCE_CHANGED, §4/§34/§35) invece di assumere che un URL
uguale significhi contenuto uguale.

Deterministico e puro. Non tocca il cervello né il runtime dell'app: è alimentato
da un tool (`tools/snapshot_corpus.py`) e la fotografia vive nel volume dati.
"""
from __future__ import annotations

import hashlib


def _norm(s) -> str:
    """Normalizza il testo: collassa gli spazi, così un semplice riformattamento
    non è un falso 'cambio'; un emendamento vero (parole diverse) sì."""
    return " ".join(str(s or "").split())


def article_hash(article) -> str:
    """SHA-256 esadecimale del contenuto CANONICO di un articolo.
    Copre: codice, numero, rubrica/titolo, stato di abrogazione e corpo — un
    cambio in uno qualsiasi di questi è un cambio della norma."""
    parts = [
        _norm(getattr(article, "code", "")),
        _norm(getattr(article, "number", "")),
        _norm(getattr(article, "title_sq", "")),
        _norm(getattr(article, "heading", "")),
        "REPEALED" if getattr(article, "repealed", False) else "INFORCE",
        _norm(getattr(article, "body", "")),
    ]
    raw = "␟".join(parts)  # separatore improbabile nel testo (UNIT SEPARATOR glyph)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _key(article) -> str:
    return "%s|%s" % (_norm(getattr(article, "code", "")), _norm(getattr(article, "number", "")))


def snapshot_map(index, *, corpus: str = "") -> dict:
    """{ 'corpus:code|number': {'hash':…, 'len':…, 'title':…, 'repealed':bool} }
    per tutti gli articoli dell'indice. `corpus` (es. 'AL'/'IT') distingue i due."""
    out: dict = {}
    for a in getattr(index, "articles", []) or []:
        k = (corpus + ":" if corpus else "") + _key(a)
        out[k] = {
            "hash": article_hash(a),
            "len": len(_norm(getattr(a, "body", ""))),
            "title": _norm(getattr(a, "title_sq", ""))[:80],
            "repealed": bool(getattr(a, "repealed", False)),
        }
    return out


def diff(old: dict, new: dict) -> dict:
    """Confronta due fotografie. Ritorna liste di chiavi:
      new      — presenti ora, non prima (norme aggiunte)
      changed  — hash diverso (testo/titolo/abrogazione cambiati)
      removed  — c'erano, ora non più
      unchanged (conteggio)
    Il PRINCIPIO §5: 'removed' NON significa 'abrogato' — può essere un
    riallineamento del corpus; va ISPEZIONATO, mai auto-applicato."""
    old = old or {}
    new = new or {}
    new_keys = [k for k in new if k not in old]
    removed = [k for k in old if k not in new]
    changed = [k for k in new if k in old and new[k].get("hash") != old[k].get("hash")]
    unchanged = sum(1 for k in new if k in old and new[k].get("hash") == old[k].get("hash"))
    return {
        "new": sorted(new_keys),
        "changed": sorted(changed),
        "removed": sorted(removed),
        "unchanged": unchanged,
    }
