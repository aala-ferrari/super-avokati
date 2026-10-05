#!/usr/bin/env python3
"""v9.509 — il web serve agli strumenti italiani del procuratore? Gli stessi fatti (quelli dell'audit) con e senza
WebSearch/WebFetch: tempo, citazioni verificate / inesistenti / senza codice, sentenze di Cassazione citate, norme decisive.
DB di PROVA (APP_DB_PATH su una copia). Esiti e testi in /tmp/mwp/. Uso:
    docker run --rm … super-avvocato:vX python3 tools/misura_web_procuratore.py
"""
from __future__ import annotations

import json
import os
import re
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src import brain as B, citation_verifier as cv, prosecutor  # noqa: E402
from src.retrieval import ArticleIndex  # noqa: E402

CASI = [
    ("sollecito", "delay_complaint", "Ho denunciato una truffa online nel marzo 2025 e da allora non ho saputo più nulla.",
     ["335", "405", "407", "413"]),
    ("misura", "coercive_measure", "Indagato arrestato in flagranza mentre cedeva 50 grammi di cocaina; precedente specifico; ha tentato la fuga.",
     ["73", "274", "275", "280"]),
    ("piano", "investigation_plan", "Denuncia per truffa aggravata: la vittima ha versato 50.000 euro per un investimento inesistente.",
     ["640", "321", "359", "266"]),
]


class _SenzaWeb:
    def __init__(self, b):
        self._b = b

    def __getattr__(self, k):
        return getattr(self._b, k)

    def complete(self, *a, **kw):
        kw["no_web"] = True
        return self._b.complete(*a, **kw)


def main() -> int:
    al = ArticleIndex.load()
    it = ArticleIndex.load(Path("/app/data/index/bm25_it.pkl"))
    cv.registra_indici(al=al, it=it)
    sa = B.SuperAvvocato(index=al, index_it=it)
    out = Path("/tmp/mwp"); out.mkdir(exist_ok=True)
    ris = {}

    def giro(nome, fn, fatti, attese, modo):
        B.set_request_jurisdiction("IT")
        be = sa.backend if modo == "web" else _SenzaWeb(sa.backend)
        t0 = time.time()
        try:
            r = getattr(prosecutor, fn)(be, it, facts=fatti)
            md = r.get("markdown") or ""
        except Exception as e:  # noqa: BLE001
            md = f"ERRORE {e}"
        dt = time.time() - t0
        v = cv.verify_text(md, it)
        st = v["stats"]
        cass = len(set(re.findall(r"Cass\.[^\n]{0,60}?n\.\s*\d+", md)))
        trovate = [a for a in attese if re.search(r"art(?:t)?\.\s*[^\n]{0,40}?\b%s\b" % re.escape(a), md)]
        (out / f"{nome}_{modo}.md").write_text(md, encoding="utf-8")
        ris[(nome, modo)] = dict(sec=round(dt), chr=len(md), verificate=st["verified"], inesistenti=st["fake"],
                                 senza_codice=st["needs_code"], cassazione=cass, decisive=f"{len(trovate)}/{len(attese)}")
        print(nome, modo, ris[(nome, modo)], flush=True)

    th = [threading.Thread(target=giro, args=(n, f, x, a, m)) for n, f, x, a in CASI for m in ("web", "senza")]
    for t in th:
        t.start()
    for t in th:
        t.join()
    print("\nRIEPILOGO")
    for n, *_ in CASI:
        for m in ("web", "senza"):
            print(f"  {n:10s} {m:6s} {ris.get((n, m))}")
    (out / "esito.json").write_text(json.dumps({f"{k[0]}_{k[1]}": v for k, v in ris.items()}, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
