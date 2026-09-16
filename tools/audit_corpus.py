# -*- coding: utf-8 -*-
"""Audit d'integrità del corpus AL + IT — «la correttezza è prima di tutto» (titolare, 16 set 2026).

Per ogni corpus (dagli indici CARICATI, cioè quello che il cervello vede davvero):
  • numerazione: massimo, numeri mancanti nell'intervallo 1..max (buchi), duplicati
  • corpi vuoti/monconi, rubriche che hanno ingoiato il testo (>200 chr), placeholder «senza testo»
  • parole incollate (parole >15 chr) e abrogati (quota)
  • SELF-RETRIEVAL: un campione di articoli deve ritrovare se stesso con le prime 15 parole
    (misura tokenizzazione/indice: il bug «repealed» e quello «Neni» sarebbero usciti qui)
  • RISOLUTORE: il corpus deve essere riconosciuto citando la sua etichetta (IT) / il suo nome (AL)
Stampa una tabella e un elenco ANOMALIE. Gira dentro il container:
    python3 /app/tools/audit_corpus.py [it|al] [--sample 40]
"""
import random, re, sys
from pathlib import Path

sys.path.insert(0, "/app")
from src.retrieval import ArticleIndex, tokenize_for  # noqa: E402
from src import citation_verifier as cv  # noqa: E402

_NUM = re.compile(r"^(\d+)")
_SUFFIX_SKIP = re.compile(r"-(legge|all\d+)$")


def audit(lang: str, sample: int) -> list[str]:
    path = Path("/app/data/index/bm25_it.pkl" if lang == "it" else "/app/data/index/bm25.pkl")
    idx = ArticleIndex.load(path)
    by_code: dict[str, list] = {}
    for a in idx.articles:
        by_code.setdefault(a.code, []).append(a)
    anomalies: list[str] = []
    print(f"\n=== {lang.upper()}: {len(idx.articles)} articoli / {len(by_code)} corpora ===")
    print(f"{'corpus':32s} {'art':>5} {'abr%':>5} {'max':>5} {'buchi':>5} {'dup':>4} {'vuoti':>5} {'rub>200':>7} {'glue%':>6} {'self':>6}  {'risolve':7}")
    rng = random.Random(7)
    tot_hit = tot_try = 0
    for code in sorted(by_code):
        arts = by_code[code]
        nums = []
        for a in arts:
            n = str(a.number)
            if _SUFFIX_SKIP.search(n):
                continue
            m = _NUM.match(n)
            if m:
                nums.append(int(m.group(1)))
        mx = max(nums) if nums else 0
        present = set(nums)
        holes = [i for i in range(1, mx + 1) if i not in present] if mx else []
        plain = [str(a.number) for a in arts]
        dup = len(plain) - len(set(plain))
        # (nel corpus AL la «rubrica» è la prima frase intera e spesso contiene TUTTO il testo
        # dell'articolo: vuoto = rubrica+corpo insieme sotto i 25 caratteri)
        empty = sum(1 for a in arts if len(a.heading) + len(a.body) < 25 and not a.repealed)
        rub = sum(1 for a in arts if len(a.heading) > 200)
        words = " ".join(a.body for a in arts).split()
        glue = 100 * sum(1 for w in words if len(w) > 15) / max(len(words), 1)
        abr = 100 * sum(1 for a in arts if a.repealed) / max(len(arts), 1)
        # self-retrieval
        cand = [a for a in arts if not a.repealed and len(a.body) >= 120]
        pick = rng.sample(cand, min(sample, len(cand))) if cand else []
        hit = 0
        for a in pick:
            q = " ".join(a.body.split()[:15])
            top = idx.search(q, top_k=3)
            if any(t.code == a.code and str(t.number) == str(a.number) for t, _ in top):
                hit += 1
        rate = f"{100 * hit / len(pick):5.0f}%" if pick else "   -"
        tot_hit += hit; tot_try += len(pick)
        # risolutore: si cita come lo scriverebbe il cervello — «art. N <titolo dell'atto>»
        # (il titolo dell'indice contiene numero/anno: «Codice dell'Ambiente (D.Lgs 152/2006)»);
        # la label corta della UI non basta e non è una citazione
        title = arts[0].title_sq
        if lang == "it":
            res = cv._resolve_code_it(title) if title else None
            if res != code:   # seconda chance: la label
                label = cv.CODE_LABELS.get(code, "")
                res = cv._resolve_code_it(label) if label else res
        else:
            res = cv._resolve_code(title.lower()) if title else None
        ok_res = "ok" if res == code else ("NO" if res is None else f"→{res[:12]}")
        print(f"{code:32s} {len(arts):>5} {abr:>5.0f} {mx:>5} {len(holes):>5} {dup:>4} {empty:>5} {rub:>7} {glue:>6.2f} {rate:>6}  {ok_res}")
        # anomalie
        if len(holes) > max(3, mx * 0.03):
            anomalies.append(f"{lang}:{code}: {len(holes)} numeri mancanti su {mx} (es. {holes[:8]})")
        if dup:
            anomalies.append(f"{lang}:{code}: {dup} numeri duplicati")
        if empty > max(2, len(arts) * 0.02):
            anomalies.append(f"{lang}:{code}: {empty} articoli vivi con corpo <25 chr")
        if rub > len(arts) * 0.2 and lang == "it":
            anomalies.append(f"{lang}:{code}: {rub} rubriche >200 chr (testo ingoiato dalla rubrica)")
        if glue > 1.2:
            anomalies.append(f"{lang}:{code}: parole incollate {glue:.1f}% (>15 chr)")
        if pick and hit / len(pick) < 0.7:
            anomalies.append(f"{lang}:{code}: self-retrieval {hit}/{len(pick)} — l'articolo non ritrova se stesso")
        if ok_res != "ok":
            anomalies.append(f"{lang}:{code}: il risolutore non riconosce la sua etichetta/nome ({ok_res})")
        if abr >= 50 and len(arts) >= 5:
            anomalies.append(f"{lang}:{code}: {abr:.0f}% abrogato (legge morta? deve avere il successore nel corpus)")
    print(f"self-retrieval totale {lang}: {tot_hit}/{tot_try} = {100 * tot_hit / max(tot_try, 1):.0f}%")
    return anomalies


if __name__ == "__main__":
    sample = int(sys.argv[sys.argv.index("--sample") + 1]) if "--sample" in sys.argv else 40
    langs = [a for a in sys.argv[1:] if a in ("it", "al")] or ["it", "al"]
    out: list[str] = []
    for lg in langs:
        out += audit(lg, sample)
    print(f"\n=== ANOMALIE: {len(out)} ===")
    for s in out:
        print("  · " + s)
