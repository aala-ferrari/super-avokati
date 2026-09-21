# -*- coding: utf-8 -*-
"""RI-PARSE della STRUTTURA dei nene AL (v9.362, 21 set 2026): rubrica · note · paragrafi, dai PDF/DOCX QBZ
originali già sul disco (data/raw/al_qbz), SENZA riscaricare e SENZA toccare numeri, abrogazioni e date.

    docker exec super-avvocato python3 tools/reparse_al_rubrika.py            # rapporto a secco
    docker exec super-avvocato python3 tools/reparse_al_rubrika.py --apply    # riscrive jsonl (backup) + bm25.pkl

Regole di sicurezza: un codice si aggiorna SOLO se l'insieme dei numeri ri-parsati è IDENTICO a quello del
jsonl (altrimenti resta com'è e viene segnalato); si cambiano solo heading/body/note/paragrafet — repealed,
last_amendment_date, volatility, area, titolo e gerarchia restano quelli del jsonl. Dopo `--apply`:
tools/build_dense.py --force (segmenti) e riavvio guardato (ops/restart_when_idle.sh).
"""
import argparse, importlib.util, json, shutil, sys, time
sys.path.insert(0, "/app")
from pathlib import Path

from src.config import LegalDocument, PROCESSED_DATA_PATH
from src.parser import split_into_articles
from src.retrieval import ArticleIndex, INDEX_FILE

JSONL = PROCESSED_DATA_PATH / "all_articles.jsonl"
RAW = Path("/app/data/raw/al_qbz")
ESEMPI = {("kodi_penal", "302"), ("kodi_penal", "88"), ("kodi_penal", "1"), ("ligji_konsumatoret", "1"), ("kodi_civil", "378"),
          ("kodi_familjes", "125"), ("kodi_punes", "155"), ("kodi_proc_penale", "49"), ("kodi_proc_civile", "420"), ("kushtetuta", "42")}


def _ingest():
    spec = importlib.util.spec_from_file_location("ing", "/app/tools/ingest_al_qbz.py")
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m); return m


def _extract(ing, f: Path) -> str:
    cands = []
    for cand in ((3.0,) if f.suffix == ".docx" else (3.0, 1.5, 1.0)):
        t = ing._extract(f, cand); cands.append((t, ing._quality(t), cand))
    good = [c for c in cands if ing._good(c[1])]
    text, q, tol = min(good or cands, key=lambda c: (c[1]["glue_ratio"], c[1]["long_ratio"]))
    return text


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--only", default="")
    a = ap.parse_args()
    ing = _ingest()
    rows = [json.loads(l) for l in JSONL.read_text(encoding="utf-8").splitlines() if l.strip()]
    by_code: dict[str, list[dict]] = {}
    for r in rows:
        by_code.setdefault(r["code"], []).append(r)
    only = {c for c in a.only.split(",") if c}
    tot = {"codici": 0, "aggiornati": 0, "saltati": [], "nene": 0, "rubrika_cambiata": 0, "note": 0, "body_vuoti_prima": 0, "body_vuoti_dopo": 0, "rubriche_lunghe_prima": 0, "rubriche_lunghe_dopo": 0}
    esempi = []
    nuovi_per_code: dict[str, dict[str, dict]] = {}
    for code, olds in sorted(by_code.items()):
        if only and code not in only:
            continue
        f = RAW / f"{code}.pdf"
        if not f.exists():
            f = RAW / f"{code}.docx"
        if not f.exists():
            tot["saltati"].append(f"{code} (nessun file in raw/al_qbz)"); continue
        tot["codici"] += 1
        try:
            text = _extract(ing, f)
            o = olds[0]
            doc = LegalDocument(code=code, title_sq=o["title_sq"], title_en=code, area=o.get("area", ""), url="", local_pdf=f"al_qbz/{f.name}",
                                volatility=o.get("volatility", "MEDIUM"))
            arts = split_into_articles(text, doc)
        except Exception as exc:  # noqa: BLE001
            tot["saltati"].append(f"{code} (parse fallito: {exc})"); continue
        new = {str(x.number): x for x in arts}
        old_nums = {str(r["number"]) for r in olds}
        if set(new) != old_nums:
            d1, d2 = sorted(old_nums - set(new))[:6], sorted(set(new) - old_nums)[:6]
            tot["saltati"].append(f"{code} (numeri diversi: solo jsonl {d1}, solo nuovo {d2})"); continue
        cambiati = note_n = 0
        for r in olds:
            x = new[str(r["number"])]
            tot["nene"] += 1
            if not (r.get("body") or "").strip(): tot["body_vuoti_prima"] += 1
            if not (x.body or "").strip(): tot["body_vuoti_dopo"] += 1
            if len(r.get("heading") or "") > 120: tot["rubriche_lunghe_prima"] += 1
            if len(x.heading or "") > 120: tot["rubriche_lunghe_dopo"] += 1
            if (x.heading or "") != (r.get("heading") or ""): cambiati += 1
            if x.note: note_n += 1
            if (code, str(r["number"])) in ESEMPI:
                esempi.append((code, str(r["number"]), (r.get("heading") or "")[:100], x.heading, x.note[:90], (x.body or "")[:110].replace("\n", " "), len(x.paragrafet)))
        tot["rubrika_cambiata"] += cambiati; tot["note"] += note_n; tot["aggiornati"] += 1
        nuovi_per_code[code] = new
        print(f"[{code:28s}] nene {len(olds):5d} · rubrica cambiata {cambiati:5d} · note {note_n:4d} · corpo vuoto prima→dopo "
              f"{sum(1 for r in olds if not (r.get('body') or '').strip())}→{sum(1 for x in new.values() if not (x.body or '').strip())}", flush=True)
    print("\nTOTALE:", json.dumps({k: v for k, v in tot.items() if k != "saltati"}, ensure_ascii=False))
    print("SALTATI:", tot["saltati"] or "-")
    print("\n=== ESEMPI (prima → rubrica | note | corpo | n. paragrafi) ===")
    for c, n, prima, rub, note, corpo, npar in esempi:
        print(f"\n[{c} {n}]\n  PRIMA  : {prima}\n  RUBRIKA: {rub}\n  NOTE   : {note or '—'}\n  CORPO  : {corpo}\n  PARAGR.: {npar}")
    if not a.apply:
        return 0
    # ── APPLY: jsonl (solo i campi di struttura) + bm25.pkl, con backup ──
    stamp = time.strftime("%Y%m%d-%H%M%S")
    bak = JSONL.with_suffix(f".jsonl.bak-{stamp}"); shutil.copy2(JSONL, bak)
    out_lines = []
    for r in rows:
        new = nuovi_per_code.get(r["code"])
        if new and str(r["number"]) in new:
            x = new[str(r["number"])]
            r = dict(r); r["heading"], r["body"], r["note"], r["paragrafet"] = x.heading, x.body, x.note, list(x.paragrafet)
        out_lines.append(json.dumps(r, ensure_ascii=False))
    JSONL.write_text("\n".join(out_lines) + "\n", encoding="utf-8")
    print(f"\njsonl riscritto ({len(out_lines)} righe) · backup {bak.name}")
    if INDEX_FILE.exists():
        ibak = INDEX_FILE.with_suffix(f".pkl.bak-{stamp}"); shutil.copy2(INDEX_FILE, ibak); print(f"backup indice: {ibak.name}")
    idx = ArticleIndex.from_jsonl(JSONL, lang="sq"); idx.save(INDEX_FILE)
    idx2 = ArticleIndex.load(INDEX_FILE)
    print(f"indice AL: {len(idx2.articles)} nene / {len({x.code for x in idx2.articles})} kode · abrogati {sum(1 for x in idx2.articles if x.repealed)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
