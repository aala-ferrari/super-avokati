#!/usr/bin/env python3
"""v9.483 — i BUCHI DEL RECUPERO visti dalle risposte vere: dove il senior ha scritto «non è tra gli articoli recuperati» /
«nuk e kam tekstin» accanto a un articolo che il corpus HA, si prende la domanda dell'avvocato e si rifà il recupero di
OGGI (triage vero → `_retrieve` → nene chiesti → previgenti → rinvii [→ Kërkuesi con --kerkuesi]): l'articolo ora entra
nel blocco del senior? Una chiamata al modello veloce per domanda (il triage); nessuna risposta viene scritta.
DB di PROVA (`APP_DB_PATH` su una COPIA).

    docker run --rm … -e APP_DB_PATH=/tqa/app.db … super-avvocato:vX python3 tools/eval_buchi_chat.py [--giorni 30] [--kerkuesi] [-v]
"""
from __future__ import annotations

import os
import re
import sqlite3
import sys
import time
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src import brain as B  # noqa: E402
from src import citation_verifier as cv  # noqa: E402
from src.retrieval import ArticleIndex  # noqa: E402

FRASE = re.compile(
    r"(non (?:è|e|sono) (?:tra|fra) gli articoli|non (?:è|e) nel (?:corpus|blocco|fascicolo)|fuori dal corpus|"
    r"non (?:ho|abbiamo) (?:il testo|sottomano)|non (?:mi )?(?:è stato|sono stati) fornit|"
    r"nuk e kam (?:tekstin|në nenet|ndër nenet|në bllok)|nuk (?:është|eshte) (?:në|ne) bllok|jashtë korpusit|"
    r"nuk (?:është|eshte) ndër nenet|nuk (?:më )?(?:është|janë) dhënë)", re.I)


def _casi(db_path: str, giorni: int, idx: dict) -> list[tuple[str, str, list[tuple[str, str]]]]:
    db = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    righe = db.execute(
        "select m.case_id, m.id, m.content, coalesce(c.jurisdiction,'AL') from messages m join cases c on c.id=m.case_id "
        "where m.role='assistant' and m.created_at > datetime('now', ?) order by m.case_id, m.id", (f"-{giorni} days",)).fetchall()
    out: dict[tuple[str, str], set] = {}
    for case_id, mid, testo, jur in righe:
        testo = testo or ""
        voluti = set()
        for m in FRASE.finditer(testo):
            pezzo = testo[max(0, m.start() - 260): m.start()]
            try:
                its = cv.verify_text(pezzo, idx[jur])["items"]
            except Exception:  # noqa: BLE001
                continue
            its = [x for x in its if x.get("status") == "verified" and x.get("code")]
            if its:
                voluti.add((its[-1]["code"], str(its[-1]["number"]).split("/")[0] if jur == "IT" else str(its[-1]["number"])))
        if not voluti:
            continue
        dom = db.execute("select content from messages where case_id=? and role='user' and id<? order by id desc limit 1",
                         (case_id, mid)).fetchone()
        if dom and dom[0] and len(dom[0]) < 4000:
            out.setdefault((jur, dom[0].strip()), set()).update(voluti)
    return [(j, q, sorted(v)) for (j, q), v in out.items()]


def main() -> int:
    giorni = int(sys.argv[sys.argv.index("--giorni") + 1]) if "--giorni" in sys.argv else 30
    sa = B.SuperAvvocato()
    if getattr(sa, "index_it", None) is None:
        sa.index_it = ArticleIndex.load(Path("/app/data/index/bm25_it.pkl"))
    cv.registra_indici(al=sa.index, it=sa.index_it)
    casi = _casi(os.environ.get("APP_DB_PATH", "/app/data/app.db"), giorni, {"AL": sa.index, "IT": sa.index_it})
    print(f"{len(casi)} domande con articoli «non recuperati» ({sum(len(v) for *_, v in casi)} articoli)", flush=True)
    tot = trovati = 0
    t0 = time.time()
    for jur, q, voluti in casi:
        B.set_request_jurisdiction(jur)
        try:
            sa._jurisdiction_ctx.code = jur
        except Exception:  # noqa: BLE001
            pass
        try:
            tr = sa._triage(q, [], None)
            ret = sa._retrieve(tr)
            ret = sa._ankoro_citimet(q, ret, areas=getattr(tr, "areas", None))
            ret = sa._aggiungi_previgenti(ret)
            ret = sa._aggiungi_rinvii(ret)
            if "--kerkuesi" in sys.argv:
                ret = sa._studio_kerkuesi(q, tr, ret)
        except Exception as exc:  # noqa: BLE001
            print(f"  ! [{jur}] {q[:60]}: {type(exc).__name__} {exc}", flush=True)
            continue
        got = {(a.code, str(a.number)) for a, _ in ret}
        for v in voluti:
            tot += 1
            ok = v in got
            trovati += ok
            print(f"{'✓' if ok else '✗'} [{jur}] {v[0]} {v[1]:8s} | {q[:90]}", flush=True)
        if "-v" in sys.argv:
            print("      blocco:", [f"{c}:{n}" for c, n in [(a.code, a.number) for a, _ in ret][:14]], "| query:",
                  [x[:40] for x in tr.search_queries[:4]], flush=True)
    print(f"\nORA NEL BLOCCO: {trovati}/{tot} articoli · {int((time.time() - t0) / max(len(casi), 1))} s/domanda")
    return 0


if __name__ == "__main__":
    sys.exit(main())
