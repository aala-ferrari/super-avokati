# -*- coding: utf-8 -*-
"""Fotografia content-hash del corpus + rilevamento cambi (fondazione §1-2-4/§34-35).

Cosa fa: calcola un'impronta SHA-256 per ogni articolo (AL + IT) e la confronta con
la fotografia precedente nel volume dati. Dice cosa è NUOVO, cosa è CAMBIATO (testo/
titolo/abrogazione) e cosa è RIMOSSO. È la base per accorgersi quando un testo
ufficiale cambia tra due ingest — oggi NON lo rileviamo (un URL uguale ≠ contenuto
uguale).

Uso:
  docker exec super-avvocato python3 tools/snapshot_corpus.py           # dry-run: confronta e RIPORTA
  docker exec super-avvocato python3 tools/snapshot_corpus.py --write   # salva la nuova fotografia (baseline/aggiornamento)

La fotografia vive in data/index/corpus_hashes.json (volume → sopravvive ai deploy,
accanto ai pickle). NON si committa: è un artefatto di runtime, rigenerabile.

⚠️ REGOLA (§5): 'rimosso' NON significa 'abrogato', 'cambiato' NON si auto-applica
a niente — è un SEGNALE da ispezionare. Mai auto-ingest (regola sacra).
"""
from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src import corpus_hash as _ch  # noqa: E402
from src.retrieval import ArticleIndex, INDEX_FILE  # noqa: E402

SNAP_PATH = INDEX_FILE.parent / "corpus_hashes.json"


def _build_current() -> dict:
    cur: dict = {}
    al = ArticleIndex.load()
    cur.update(_ch.snapshot_map(al, corpus="AL"))
    it_path = INDEX_FILE.parent / "bm25_it.pkl"
    if it_path.exists():
        try:
            it = ArticleIndex.load(it_path)
            cur.update(_ch.snapshot_map(it, corpus="IT"))
        except Exception as e:  # noqa: BLE001
            print(f"[warn] indice IT non caricato: {e}")
    return cur


def main(argv) -> int:
    write = "--write" in argv
    cur = _build_current()
    print("Corpus attuale: %d articoli con impronta." % len(cur))

    old = {}
    if os.path.exists(SNAP_PATH):
        try:
            old = json.load(open(SNAP_PATH, encoding="utf-8")).get("articles", {})
        except Exception as e:  # noqa: BLE001
            print(f"[warn] fotografia precedente illeggibile: {e}")

    if not old:
        print("Nessuna fotografia precedente: questo sarà la BASELINE.")
    else:
        d = _ch.diff(old, cur)
        print("=" * 60)
        print("NUOVI:     %d" % len(d["new"]))
        print("CAMBIATI:  %d" % len(d["changed"]))
        print("RIMOSSI:   %d" % len(d["removed"]))
        print("INVARIATI: %d" % d["unchanged"])
        for k in d["changed"][:40]:
            print("   ~ cambiato:", k, "—", cur[k].get("title", ""))
        for k in d["removed"][:40]:
            print("   - rimosso:", k)
        for k in d["new"][:40]:
            print("   + nuovo:", k, "—", cur[k].get("title", ""))
        print("=" * 60)
        print("⚠ 'cambiato/rimosso' = SEGNALE da ispezionare, mai auto-applicato (§5).")

    if write:
        import datetime as _dt
        payload = {"generated_at": _dt.datetime.now(_dt.timezone.utc).isoformat(),
                   "count": len(cur), "articles": cur}
        tmp = str(SNAP_PATH) + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False)
        os.replace(tmp, SNAP_PATH)
        print("Fotografia salvata in %s (%d articoli)." % (SNAP_PATH, len(cur)))
    else:
        print("(dry-run — usa --write per salvare la fotografia)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
