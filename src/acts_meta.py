# -*- coding: utf-8 -*-
"""Numero, data e consolidamento dell'ATTO accanto a ogni articolo (roadmap v4, punto 6, 20 set 2026).

`data/index/acts_meta.json` lo scrive `tools/build_acts_meta.py` (AL dagli URL QBZ, IT dalla URN
Normattiva). Qui: caricamento pigro con cache, e la riga per il prompt nella lingua della sessione:
  «📜 Ligji nr. 79/2021, datë 24.6.2021 — teksti i konsoliduar 2025-07-14 (ndryshuar nga ligji 43/2025)»
  «📜 D.Lgs. 30 aprile 1992, n. 285 — testo vigente Normattiva, scaricato 2026-09-17»
Senza il file (o senza voce) la riga è vuota: mai un errore, mai un dato inventato.
"""
from __future__ import annotations

import json
import os
import threading
from pathlib import Path

from .config import INDEX_PATH

META_PATH = Path(os.environ.get("ACTS_META", str(INDEX_PATH / "acts_meta.json")))
_LOCK = threading.Lock()
_CACHE: dict | None = None
_MTIME = 0.0


def carica() -> dict:
    global _CACHE, _MTIME
    try:
        st = META_PATH.stat().st_mtime
    except OSError:
        return {}
    with _LOCK:
        if _CACHE is None or st != _MTIME:
            try:
                _CACHE = json.loads(META_PATH.read_text(encoding="utf-8"))
            except Exception:  # noqa: BLE001
                _CACHE = {}
            _MTIME = st
        return _CACHE or {}


def info(code: str) -> dict | None:
    return carica().get(code or "")


def etichetta(code: str) -> str:
    """«Ligji nr. 79/2021» / «D.Lgs. 285/1992» — corta, per badge e verificatore."""
    m = info(code)
    if not m or not m.get("numero"):
        return ""
    if m.get("jur") == "IT":
        return f"{m.get('tipo') or ''} {m['numero']}/{m.get('anno')}".strip()
    return f"{m.get('tipo') or 'Akti'} nr. {m['numero']}/{m.get('anno')}"


def riga(code: str, lang: str = "sq") -> str:
    """La riga per il prompt degli articoli; vuota se non sappiamo niente di certo."""
    m = info(code)
    if not m:
        return ""
    if m.get("jur") == "IT":
        if not m.get("numero"):
            return f"📜 {m.get('titolo') or ''} — fonte {m.get('fonte') or '?'}".strip() if m.get("titolo") else ""
        base = f"📜 {m.get('tipo') or ''} {m.get('data') or ''}, n. {m['numero']}".replace("  ", " ")
        if m.get("consolidato"):
            base += f" — testo vigente {m.get('fonte') or 'Normattiva'}, scaricato {m['consolidato']}"
        return base
    if not m.get("numero"):
        return ""
    if lang == "it":
        base = f"📜 {('Legge' if m.get('tipo') == 'Ligji' else m.get('tipo') or 'Atto')} n. {m['numero']}/{m.get('anno')}, del {m.get('data') or '?'}"
        if m.get("consolidato") and m["consolidato"] != "base":
            base += f" — testo consolidato QBZ {m['consolidato']}" + (f" (modificato da {m['modificato_da'].replace('ligji', 'legge')})" if m.get("modificato_da") else "")
        elif m.get("consolidato") == "base":
            base += " — testo originale (mai modificato)"
        return base
    base = f"📜 {m.get('tipo') or 'Akti'} nr. {m['numero']}/{m.get('anno')}, datë {m.get('data') or '?'}"
    if m.get("consolidato") and m["consolidato"] != "base":
        base += f" — teksti i konsoliduar QBZ {m['consolidato']}" + (f" (ndryshuar nga {m['modificato_da']})" if m.get("modificato_da") else "")
    elif m.get("consolidato") == "base":
        base += " — teksti bazë (i pandryshuar)"
    return base
