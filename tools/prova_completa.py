#!/usr/bin/env python3
"""v9.483 — prova del CANCELLO CHE COMPLETA sulle risposte vere salvate: righe con «non è tra gli articoli recuperati /
da verificare / nuk e kam tekstin» accanto a un articolo che il corpus ha → il testo ufficiale al modello del Giudice →
la riga rivista. Stampa prima/dopo. DB di PROVA (`APP_DB_PATH` su una COPIA). Senza `--vero` solo il conteggio (nessuna
chiamata al modello); con `--vero N` rivede le prime N risposte.

    docker run --rm … -e APP_DB_PATH=/tqa/app.db … super-avvocato:vX python3 tools/prova_completa.py [--giorni 30] [--vero 3]
"""
from __future__ import annotations

import json
import os
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src import brain as B, cancello, citation_verifier as cv  # noqa: E402
from src.retrieval import ArticleIndex  # noqa: E402


def main() -> int:
    giorni = int(sys.argv[sys.argv.index("--giorni") + 1]) if "--giorni" in sys.argv else 30
    vero = int(sys.argv[sys.argv.index("--vero") + 1]) if "--vero" in sys.argv else 0
    ids = {int(x) for x in sys.argv[sys.argv.index("--ids") + 1].split(",")} if "--ids" in sys.argv else None
    if ids:
        vero = vero or len(ids)
    al = ArticleIndex.load()
    it = ArticleIndex.load(Path("/app/data/index/bm25_it.pkl"))
    cv.registra_indici(al=al, it=it)
    db = sqlite3.connect(f"file:{os.environ.get('APP_DB_PATH', '/app/data/app.db')}?mode=ro", uri=True)
    righe = db.execute("select m.id, m.content, m.articles_json, coalesce(c.jurisdiction,'AL') from messages m join cases c "
                       "on c.id=m.case_id where m.role='assistant' and m.created_at > datetime('now', ?) order by m.id",
                       (f"-{giorni} days",)).fetchall()
    sa = B.SuperAvvocato(index=al, index_it=it) if vero else None
    from src.config import STUDIO_GJYQTARI_MODEL
    n_risp = n_righe = fatte = 0
    for mid, testo, aj, jur in righe:
        idx = it if jur == "IT" else al
        try:
            arts = json.loads(aj or "[]")
        except Exception:  # noqa: BLE001
            arts = []
        keys = {(str(a.get("code")), str(a.get("number"))) for a in arts if isinstance(a, dict)}
        codes = {c for c, _ in keys} or None
        r_idx, r_arts = cancello._da_completare(testo or "", idx, codes, keys)
        if not r_idx or (ids and mid not in ids):
            continue
        n_risp += 1; n_righe += len(r_idx)
        print(f"\n## msg {mid} [{jur}] — {len(r_idx)} righe, articoli: {[f'{a.code} {a.number}' for a in r_arts]}", flush=True)
        if vero and fatte < vero:
            fatte += 1
            B.set_request_jurisdiction(jur)
            lang = "it" if jur == "IT" else "sq"
            nuovo, cambi, _n = cancello.completa(testo, idx, lang, backend=sa.backend, retrieved_codes=codes,
                                                 retrieved_keys=keys, modeli=STUDIO_GJYQTARI_MODEL, effort="high")
            vecchie, nuove = (testo or "").split("\n"), nuovo.split("\n")
            for i in r_idx:
                if i < len(nuove) and nuove[i] != vecchie[i]:
                    print(f"  PRIMA: {vecchie[i][:600]}\n  DOPO : {nuove[i][:600]}\n", flush=True)
            print(f"  → righe riviste {cambi}/{len(r_idx)}", flush=True)
    print(f"\nTOTALE: {n_risp} risposte su {len(righe)} con righe da completare, {n_righe} righe")
    return 0


if __name__ == "__main__":
    sys.exit(main())
