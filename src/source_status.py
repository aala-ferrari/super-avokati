# -*- coding: utf-8 -*-
"""Vocabolario CANONICO degli stati delle fonti (spec §5).

Oggi gli stati vivono sparsi in moduli diversi:
  - citation_verifier (nene):       verified | fake | repealed | needs_code (+stale)
  - case_citation_verifier (sentenze): verified | unverified
  - war_room (dossier):             VERIFIED | PARTIAL | SOURCE_NOT_RETRIEVED | UNVERIFIED
                                    + qualità PRIMARY_OFFICIAL/AUTHORITATIVE_DATABASE/…

Questo modulo è la SINGOLA DEFINIZIONE condivisa: i valori canonici, le etichette
BILINGUI (sq/it, LINGUA=SESSIONE), la severità per la UI, e un MAPPER che porta
gli stati sparsi a quelli canonici. Additivo: non cambia la logica dei verificatori
esistenti (i badge e i golden dipendono dalle loro stringhe) — stabilisce il
vocabolario di riferimento che il codice nuovo usa e a cui i vecchi stati mappano.
L'unificazione dell'OUTPUT dei 3 verificatori è un refactor incrementale successivo.

PRINCIPIO FERREO (§5, §33): NOT_FOUND_IN_SEARCH ≠ DOES_NOT_EXIST. «Non trovato»
significa «non esiste» SOLO quando il corpus è completo (i nene). Per la
giurisprudenza (corpus incompleto) «non trovato» = «da controllare a mano», mai
«è falso». Questo è codificato in `means_absent()`.
"""
from __future__ import annotations

# ── stati canonici (spec §5) ─────────────────────────────────────────────────
VERIFIED = "VERIFIED"                        # confermato in una fonte autorevole
PARTIAL = "PARTIAL"                          # parzialmente confermato / da disambiguare
UNVERIFIED = "UNVERIFIED"                    # non verificato (stato neutro di default)
SOURCE_NOT_RETRIEVED = "SOURCE_NOT_RETRIEVED"  # la fonte non è stata raggiunta (timeout/errore)
SOURCE_CHANGED = "SOURCE_CHANGED"            # la fonte ufficiale è cambiata dall'ultima lettura
SOURCE_CONFLICT = "SOURCE_CONFLICT"          # testo interno ≠ testo ufficiale
NOT_FOUND_IN_SEARCH = "NOT_FOUND_IN_SEARCH"  # non trovato nella ricerca (≠ non esiste!)
REPEALED = "REPEALED"                        # esiste ma è abrogato
SUPERSEDED = "SUPERSEDED"                    # esiste ma sostituito da norma successiva
HISTORICAL_VERSION = "HISTORICAL_VERSION"    # versione storica (non quella vigente)

# set di verifica (coerente con war_room.VERIF) e qualità della fonte
VERIF = (VERIFIED, PARTIAL, SOURCE_NOT_RETRIEVED, UNVERIFIED)
QUALITY = ("PRIMARY_OFFICIAL", "AUTHORITATIVE_DATABASE", "INSTITUTIONAL",
           "SECONDARY", "UNVERIFIED")

ALL = (VERIFIED, PARTIAL, UNVERIFIED, SOURCE_NOT_RETRIEVED, SOURCE_CHANGED,
       SOURCE_CONFLICT, NOT_FOUND_IN_SEARCH, REPEALED, SUPERSEDED, HISTORICAL_VERSION)

# ── etichette bilingui + severità (per badge UI) ─────────────────────────────
# severity: "ok" (verde), "warn" (ambra), "bad" (rosso)
LABELS = {
    VERIFIED:             {"sq": "e verifikuar", "it": "verificata", "severity": "ok"},
    PARTIAL:              {"sq": "pjesërisht", "it": "parziale", "severity": "warn"},
    UNVERIFIED:           {"sq": "e paverifikuar", "it": "non verificata", "severity": "warn"},
    SOURCE_NOT_RETRIEVED: {"sq": "burimi s'u arrit", "it": "fonte non recuperata", "severity": "warn"},
    SOURCE_CHANGED:       {"sq": "burimi ka ndryshuar", "it": "fonte cambiata", "severity": "bad"},
    SOURCE_CONFLICT:      {"sq": "konflikt burimesh", "it": "conflitto di fonti", "severity": "bad"},
    NOT_FOUND_IN_SEARCH:  {"sq": "s'u gjet në kërkim", "it": "non trovata nella ricerca", "severity": "warn"},
    REPEALED:             {"sq": "e shfuqizuar", "it": "abrogata", "severity": "bad"},
    SUPERSEDED:           {"sq": "e zëvendësuar", "it": "superata/sostituita", "severity": "bad"},
    HISTORICAL_VERSION:   {"sq": "version historik", "it": "versione storica", "severity": "warn"},
}

# ── mapper: stati sparsi dei verificatori → canonico ─────────────────────────
_MAP = {
    "verified": VERIFIED,
    "repealed": REPEALED,
    "superseded": SUPERSEDED,
    "needs_code": PARTIAL,
    "partial": PARTIAL,
    "fake": NOT_FOUND_IN_SEARCH,        # + corpus completo ⇒ means_absent True
    "unverified": NOT_FOUND_IN_SEARCH,  # sentenze: corpus incompleto ⇒ da controllare
    "not_found": NOT_FOUND_IN_SEARCH,
    "not_found_in_search": NOT_FOUND_IN_SEARCH,
    "source_not_retrieved": SOURCE_NOT_RETRIEVED,
    "source_changed": SOURCE_CHANGED,
    "source_conflict": SOURCE_CONFLICT,
    "historical_version": HISTORICAL_VERSION,
    # valori già canonici (war_room) → se stessi
    "primary_official": VERIFIED, "authoritative_database": VERIFIED,
}


def canonicalize(raw: str) -> str:
    """Porta uno stato grezzo (di qualunque verificatore) al vocabolario canonico.
    Ignoto → UNVERIFIED (stato neutro, mai una conclusione di assenza)."""
    r = (raw or "").strip()
    if r in ALL:          # già canonico
        return r
    return _MAP.get(r.lower(), UNVERIFIED)


def means_absent(status: str, *, corpus_complete: bool = False) -> bool:
    """PRINCIPIO §5/§33: «non trovato» = «non esiste» SOLO se il corpus è completo.
    Per i nene (corpus completo) NOT_FOUND_IN_SEARCH ⇒ davvero assente/fantasma.
    Per la giurisprudenza (corpus incompleto) ⇒ mai 'assente', solo 'da controllare'."""
    return canonicalize(status) == NOT_FOUND_IN_SEARCH and bool(corpus_complete)


def label(status: str, lang: str = "sq") -> str:
    """Etichetta bilingue dello stato canonico (LINGUA = SESSIONE)."""
    info = LABELS.get(canonicalize(status))
    if not info:
        return status or ""
    return info.get("it" if lang == "it" else "sq", status)


def severity(status: str) -> str:
    """'ok' | 'warn' | 'bad' — per il colore del badge."""
    info = LABELS.get(canonicalize(status))
    return info["severity"] if info else "warn"
