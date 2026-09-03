"""Precedenti italiani — FTS5 su disco, con passaggio evidenziato.

Solo stdlib: gira identico nell'app e sull'host (il cron ricostruisce
l'indice subito dopo l'harvest, cosi' il primo avvocato del mattino non
paga il rebuild).
"""
from __future__ import annotations

import json
import os
import re
import sqlite3
import threading

from .config import PROCESSED_DATA_PATH

JSONL = PROCESSED_DATA_PATH / "it_decisions.jsonl"
DB = PROCESSED_DATA_PATH / "it_decisions_fts.db"

_lock = threading.Lock()

_COURT_NAME = {"CCost": "Corte costituzionale"}
# FTS5 tratta questi come operatori: nel testo di una query utente sono
# solo rumore e farebbero esplodere il MATCH con un syntax error.
_PULISCI_Q = re.compile(r'["*^:()\-]')


def rebuild_indeksi() -> int:
    """Ricostruisce l'indice dal jsonl. Ritorna il numero di decisioni."""
    DB.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(DB)
    try:
        con.executescript(
            "DROP TABLE IF EXISTS dec;"
            "CREATE VIRTUAL TABLE dec USING fts5("
            "  text, court UNINDEXED, tipo UNINDEXED, number UNINDEXED,"
            "  year UNINDEXED, data UNINDEXED, url UNINDEXED,"
            "  tokenize='unicode61 remove_diacritics 2');"
            "CREATE TABLE IF NOT EXISTS meta(k TEXT PRIMARY KEY, v TEXT);")
        n = 0
        if JSONL.exists():
            with JSONL.open(encoding="utf-8") as f, con:
                for riga in f:
                    try:
                        d = json.loads(riga)
                    except Exception:  # noqa: BLE001
                        continue
                    con.execute(
                        "INSERT INTO dec(text, court, tipo, number, year,"
                        " data, url) VALUES (?,?,?,?,?,?,?)",
                        (d.get("text") or "", d.get("court") or "",
                         d.get("type") or "", int(d.get("number") or 0),
                         int(d.get("year") or 0), d.get("date") or "",
                         d.get("url") or ""))
                    n += 1
        with con:
            con.execute(
                "INSERT OR REPLACE INTO meta(k, v) VALUES ('jsonl_mtime', ?)",
                (str(os.path.getmtime(JSONL)) if JSONL.exists() else "0",))
        return n
    finally:
        con.close()


def _fresco(con: sqlite3.Connection) -> bool:
    try:
        r = con.execute("SELECT v FROM meta WHERE k='jsonl_mtime'").fetchone()
        att = str(os.path.getmtime(JSONL)) if JSONL.exists() else "0"
        return bool(r) and r[0] == att
    except Exception:  # noqa: BLE001
        return False


def _query_fts(pyetjet: list[str]) -> str:
    """Da liste di frasi a un MATCH FTS5: frasi in virgolette, unite da OR."""
    pezzi = []
    for q in pyetjet[:6]:
        q = _PULISCI_Q.sub(" ", str(q or "")).strip()
        parole = [w for w in q.split() if len(w) > 2][:8]
        if parole:
            pezzi.append('"' + " ".join(parole) + '"')
            if len(parole) > 1:            # anche le parole sciolte, in OR:
                pezzi.extend(w for w in parole if len(w) > 3)
    visti, unici = set(), []
    for p in pezzi:
        if p.lower() not in visti:
            visti.add(p.lower())
            unici.append(p)
    return " OR ".join(unici[:24])


def kerko(pyetjet: list[str], top_k: int = 5) -> list[dict]:
    """Le decisioni piu' pertinenti, col passaggio evidenziato «...».

    Mai sollevare: zero precedenti e' una risposta valida, un crash no.
    """
    with _lock:
        try:
            if not DB.exists():
                rebuild_indeksi()
            con = sqlite3.connect(DB)
            try:
                if not _fresco(con):
                    con.close()
                    rebuild_indeksi()
                    con = sqlite3.connect(DB)
                match = _query_fts(pyetjet)
                if not match:
                    return []
                righe = con.execute(
                    "SELECT court, tipo, number, year, data, url,"
                    " snippet(dec, 0, '«', '»', ' … ', 16) AS passo,"
                    " snippet(dec, 0, '«', '»', ' … ', 42) AS brano"
                    " FROM dec WHERE dec MATCH ? ORDER BY rank LIMIT ?",
                    (match, top_k)).fetchall()
            finally:
                con.close()
        except Exception:  # noqa: BLE001
            return []
    out = []
    for court, tipo, number, year, data, url, passo, brano in righe:
        out.append({
            "court": court, "court_name": _COURT_NAME.get(court, court),
            "tipo": tipo, "number": number, "year": year,
            "date": data or "", "url": url,
            "passo": (passo or "").strip(),
            "brano": (brano or "").strip(),
        })
    return out
