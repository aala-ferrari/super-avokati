# -*- coding: utf-8 -*-
"""Ri-valuta i giri dello strato 2 già fatti con il verificatore ATTUALE (stessa formula di
`benchmark_lab.run_layer2`), leggendo i testi salvati in data/benchmark/layer2/<run>/<caso>.md.
Serve quando il verificatore cambia dopo la misura (v9.357: «St. Lav.») e i giri vanno confrontati alla pari.

    docker run … super-avvocato:vNEW python3 tools/rescore_l2.py 20260921-013932-fable 20260921-040528-deep
"""
import glob, json, os, re, sys
sys.path.insert(0, "/app")
from pathlib import Path

CASES_DIR = Path("/app/tools/golden_cases")
L2 = Path("/app/data/benchmark/layer2")


def main(runs):
    from src.retrieval import ArticleIndex
    from src import citation_verifier as cv
    al = ArticleIndex.load(); it = ArticleIndex.load(Path("/app/data/index/bm25_it.pkl"))
    cases = {}
    for p in glob.glob(str(CASES_DIR / "*.json")):
        c = json.load(open(p, encoding="utf-8")); cases[c["id"]] = c
    for run in runs:
        d = L2 / run
        summ = json.load(open(d / "summary.json", encoding="utf-8")) if (d / "summary.json").exists() else {"results": []}
        secs = {r["id"]: r.get("secs") for r in summ.get("results", [])}
        giud = {r["id"]: (r.get("giudice"), r.get("giudice_mendja")) for r in summ.get("results", [])}
        print(f"\n=== {run} ===")
        tot = []
        for md in sorted(d.glob("*.md")):
            cid = md.stem; c = cases.get(cid)
            if not c:
                continue
            juris = (c.get("jurisdiction") or "AL").upper(); idx = it if juris == "IT" else al
            final = md.read_text(encoding="utf-8")
            r = cv.verify_text(final, idx)
            cited_ok = {(i["code"], i["number"]) for i in r["items"] if i["status"] == "verified"}
            cited_any = {(i.get("code"), i["number"]) for i in r["items"]}
            exp = [(e["code"], str(e["number"])) for e in (c.get("expected_laws") or [])]
            must_not = [(e["code"], str(e["number"])) for e in (c.get("must_not_cite") or [])]
            found = [e for e in exp if e in cited_ok or e in cited_any]
            # numeri citati SENZA codice che combaciano con un atteso: informazione, non punteggio
            pa_kod = [e for e in exp if e not in found and any(x[0] is None and x[1] == e[1] for x in cited_any)]
            viol = [e for e in must_not if e in cited_any]
            kps = c.get("key_points") or []; kp_ok = [k for k in kps if re.search(k, final, re.I)]
            head_ok = final.lstrip().startswith("### ⚖️"); trust = "🔎" in final[:600]
            impur = len(re.findall(r"[ëç]|\b(nuk|është|janë|sipas|nenit|neni)\b", final)) if juris == "IT" else \
                    len(re.findall(r"\b(art\.|articolo|comma|sentenza|tribunale|avvocato|verdetto)\b", final))
            score = (0.45 * (len(found) / len(exp) if exp else 1.0) + 0.25 * (len(kp_ok) / len(kps) if kps else 1.0)
                     + 0.15 * (1.0 if not viol else 0.0) + 0.10 * (1.0 if head_ok else 0.0) + 0.05 * (1.0 if impur == 0 else 0.0))
            tot.append(score)
            print(f"{'✓' if score >= 0.8 else '~' if score >= 0.6 else '✗'} {cid}: score {score:.2f} · norme {len(found)}/{len(exp)}"
                  f"{(' (+%d citate pa kod: %s)' % (len(pa_kod), [e[1] for e in pa_kod])) if pa_kod else ''} · punti {len(kp_ok)}/{len(kps)} · "
                  f"fake {r['stats']['fake']} · verificati {r['stats']['verified']} · pa kod {r['stats']['needs_code']} · testa {head_ok} · trust {trust} · "
                  f"giudice {giud.get(cid)} · {secs.get(cid)}s · {len(final)} chr")
        if tot:
            print(f"media {sum(tot)/len(tot):.3f} su {len(tot)} casi")


if __name__ == "__main__":
    main(sys.argv[1:])
