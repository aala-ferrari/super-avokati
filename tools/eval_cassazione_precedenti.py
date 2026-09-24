# -*- coding: utf-8 -*-
"""v9.386 — I PRECEDENTI DI CASSAZIONE PER LA DOMANDA: la ricerca viva sul testo integrale della Corte trova le decisioni
che il cervello ha poi citato (e che l'archivio conferma)?

Casi = le domande italiane salvate nel DB (la prima domanda di ogni fascicolo IT, una volta sola se ripetuta) e, come
«pertinenti», le Cassazione dal 2021 (testo integrale) citate nelle risposte di quel fascicolo e CONFERMATE
dall'archivio (`src/cassazione.py`). È una misura per difetto: una decisione trovata che il cervello non ha citato può
essere pertinente lo stesso (si stampa la materia per leggerla). Confronto: i precedenti italiani di oggi
(`brain._precedenti_it`: Consulta + TAR/CdS in FTS locale). Costa un triage (modello veloce) per domanda; nessuna
risposta scritta; nessun dato del DB copiato nel repository.

    python3 tools/eval_cassazione_precedenti.py [--k 3] [-v]
"""
import re
import sqlite3
import sys
import time

sys.path.insert(0, "/app")
from src import brain as B            # noqa: E402
from src import cassazione as C        # noqa: E402

K = int(sys.argv[sys.argv.index("--k") + 1]) if "--k" in sys.argv else 3
# senza --modo si misura ESATTAMENTE la produzione (brain._precedenti_cassazione: fatti + consenso di 2 ricerche, k=2);
# --modo query|fatti|misto e --consenso/--vaglio servono a rifare le varianti misurate il 24 set (1/10, 5/10, 3/10)
MODO = sys.argv[sys.argv.index("--modo") + 1] if "--modo" in sys.argv else "produzione"


def casi() -> list[tuple[str, set, str]]:
    db = sqlite3.connect("file:/app/data/app.db?mode=ro", uri=True)
    out, viste = [], set()
    for (cid,) in db.execute("SELECT id FROM cases WHERE upper(coalesce(jurisdiction,'AL'))='IT' ORDER BY created_at"):
        msgs = db.execute("SELECT role, content FROM messages WHERE case_id=? ORDER BY id", (cid,)).fetchall()
        dom = next((c for r, c in msgs if r == "user" and (c or "").strip()), "")
        risp = "\n\n".join(c for r, c in msgs if r == "assistant" and c)
        if not dom or not risp:
            continue
        chiave = re.sub(r"\W+", " ", dom.lower()).strip()[:160]
        if chiave in viste:
            continue
        v = C.verifica(risp)
        pert = {(i["record"] or {}).get("sn_id") for i in v["items"]
                if i["status"] == "verified" and (i.get("record") or {}).get("sn_id")}
        pert.discard(None)
        if pert:
            viste.add(chiave)
            out.append((dom, pert, cid))
    return out


def main() -> int:
    sa = B.SuperAvvocato()
    B.set_request_jurisdiction("IT")
    try:
        sa._jurisdiction_ctx.code = "IT"
    except Exception:  # noqa: BLE001
        pass
    elenco = casi()
    print(f"casi con Cassazione confermate dal 2021: {len(elenco)} (k={K})", flush=True)
    hit = n = 0
    base_n = 0
    t0 = time.time()
    for dom, pert, cid in elenco:
        n += 1
        tr = sa._triage(dom, [], None)
        domande = list(getattr(tr, "search_queries", []) or [])
        for a in getattr(tr, "strategic_angles", []) or []:
            if a and a not in domande:
                domande.append(a)
        if MODO == "fatti":            # i FATTI del caso (riassunto del triage + domanda), come cerca un avvocato
            domande = [getattr(tr, "problem_summary", "") or "", dom[:600]]
        elif MODO == "misto":
            domande = [getattr(tr, "problem_summary", "") or "", (domande or [""])[0], dom[:600]]
        aree = " ".join(getattr(tr, "areas", []) or []).lower()
        ramo = "pen" if ("pen" in aree and not re.search(r"civ|lav|trib|ammin", aree)) else "civ"
        t1 = time.time()
        if MODO == "produzione":
            tr.domanda = dom
            trovati = []
            for p, _s in B._precedenti_cassazione(tr, domande):
                trovati.append({"sn_id": p.source_file, "_citazione": p.citation, "_sintesi": p.summary})
            dt = time.time() - t1
            ids = [r.get("sn_id") for r in trovati]
            ok = [i for i in ids if i in pert]
            hit += bool(ok)
            base_n += len(B._precedenti_it(tr)) - len(trovati)
            print(f"{'✓' if ok else '✗'} {dom[:80]!r} | {dt:.1f}s | pertinenti {sorted(pert)[:4]}", flush=True)
            for r in trovati:
                print(f"      {'★' if r['sn_id'] in pert else ' '} {r['_sintesi'][:150]}", flush=True)
            continue
        ctx = None
        if "--vaglio" in sys.argv:          # il vaglio della materia: domanda + riassunto + query + codici recuperati
            ret = sa._retrieve(tr)
            ctx = " ".join([dom, getattr(tr, "problem_summary", "") or ""] + list(getattr(tr, "search_queries", []) or [])
                           + [a.code.replace("_", " ") for a, _ in ret])
        cons = int(sys.argv[sys.argv.index("--consenso") + 1]) if "--consenso" in sys.argv else 1
        trovati = C.cerca_precedenti(domande, ramo=ramo, k=K, termini=14 if MODO != "query" else 8, contesto=ctx, consenso=cons)
        dt = time.time() - t1
        ids = [r.get("sn_id") for r in trovati]
        ok = [i for i in ids if i in pert]
        hit += bool(ok)
        base = B._precedenti_it(tr)
        base_n += len(base)
        print(f"{'✓' if ok else '✗'} {dom[:80]!r} | ramo {ramo} | {dt:.1f}s | pertinenti {sorted(pert)[:4]}", flush=True)
        for r in trovati:
            print(f"      {'★' if r.get('sn_id') in pert else ' '} {C.descrivi(r)[:130]} | {r.get('esito') or ''}", flush=True)
        if "-v" in sys.argv:
            print(f"      query: {[q[:60] for q in domande[:3]]}", flush=True)
            print(f"      oggi (FTS Consulta/TAR/CdS): {len(base)} → {[p.citation for p, _ in base[:3]]}", flush=True)
    print(f"\nprecedenti di Cassazione pertinenti nei primi {K}: {hit}/{n} · oggi (FTS) in media {base_n / max(n, 1):.1f} "
          f"precedenti a domanda · {int((time.time() - t0) / max(n, 1))} s/domanda (triage vero)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
