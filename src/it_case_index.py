"""Indice leggero delle decisioni italiane — per il verificatore.

Legge `it_decisions.jsonl` (harvester giurcost) e il meta di copertura.
Cache su mtime: il cron notturno aggiunge righe e l'app le vede al giro
dopo senza riavvii.

⚠️ La COPERTURA e' per (corte, anno) e significa «anno CHIUSO
dall'harvester»: solo li' il verificatore ha il diritto di dire ⚠.
"""
from __future__ import annotations

import json
import os
import threading

from .config import PROCESSED_DATA_PATH

FILE_DECISIONI = PROCESSED_DATA_PATH / "it_decisions.jsonl"
FILE_META = PROCESSED_DATA_PATH / "it_decisions_meta.json"

_lock = threading.Lock()
_cache: dict = {"mtime": None, "chiavi": set(), "coperti": {}}


def _ricarica() -> None:
    chiavi: set = set()
    if FILE_DECISIONI.exists():
        with FILE_DECISIONI.open(encoding="utf-8") as f:
            for riga in f:
                try:
                    d = json.loads(riga)
                    chiavi.add((d["court"], int(d["number"]), int(d["year"])))
                except Exception:  # noqa: BLE001
                    continue
    coperti: dict = {}
    if FILE_META.exists():
        try:
            m = json.load(FILE_META.open(encoding="utf-8"))
            for corte, info in m.items():
                if isinstance(info, dict):
                    coperti[corte] = set(int(a) for a in
                                         info.get("complete_years", []))
        except Exception:  # noqa: BLE001
            pass
    _cache["chiavi"] = chiavi
    _cache["coperti"] = coperti


def _mtime() -> tuple:
    def m(p):
        try:
            return os.path.getmtime(p)
        except OSError:
            return 0
    return (m(FILE_DECISIONI), m(FILE_META))


def indice() -> tuple[set, dict]:
    """(chiavi, coperti) — ricaricato quando i file cambiano."""
    with _lock:
        mt = _mtime()
        if _cache["mtime"] != mt:
            _ricarica()
            _cache["mtime"] = mt
        return _cache["chiavi"], _cache["coperti"]


def esiste(corte: str, numero: int, anno: int) -> bool:
    chiavi, _ = indice()
    return (corte, numero, anno) in chiavi


def anno_coperto(corte: str, anno: int) -> bool:
    _, coperti = indice()
    return anno in coperti.get(corte, set())
