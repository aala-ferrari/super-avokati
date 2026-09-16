# -*- coding: utf-8 -*-
"""Leggi albanesi da QBZ (archivio WebDAV, testi consolidati) → corpus AL.

Fonti in tools/al_sources.json (trovate il 16 set 2026: QBZ espone
https://qbz.gov.al/alfresco/webdav/Aktet/ligj/kuvendi-i-shqiperise/AAAA/MM/GG/NUM/
con «base» = originale e «cons-AAAA-MM-GG» = testo consolidato).

Metodo (quello di kadastra/noteri, v9.30x): PDF pulito → extract_full_text →
split_into_articles → APPEND a all_articles.jsonl → ArticleIndex.from_jsonl().save().
⚠️ parse_all() riscrive il jsonl SOLO dai LEGAL_DOCUMENTS di config.py e perderebbe
gli atti aggiunti così: mai lanciarlo.

Gira DENTRO il container (pdfplumber + src.parser):
    python3 /app/tools/ingest_al_qbz.py probe            # scarica, misura, NON tocca il corpus
    python3 /app/tools/ingest_al_qbz.py probe ligji_dnp  # un solo atto
    python3 /app/tools/ingest_al_qbz.py apply            # aggiunge al jsonl + ricostruisce bm25.pkl
Gate di qualità (dalla memoria kadastra/noteri: space% ≈ 0.12): 0.08 ≤ space% ≤ 0.25,
≥ 8 articoli, numerazione che parte da 1; un atto fuori gate NON entra e viene stampato.
"""
import json, os, re, shutil, sys, time, urllib.request
from dataclasses import asdict
from pathlib import Path

sys.path.insert(0, "/app")
from src.config import LegalDocument, RAW_DATA_PATH, PROCESSED_DATA_PATH, INDEX_PATH  # noqa: E402
from src.parser import extract_full_text, split_into_articles  # noqa: E402

SRC = Path(os.environ.get("AL_SOURCES", "/app/tools/al_sources.json"))
RAW = RAW_DATA_PATH / "al_qbz"
OUT = PROCESSED_DATA_PATH / "al_qbz"
JSONL = PROCESSED_DATA_PATH / "all_articles.jsonl"
INDEX = INDEX_PATH / "bm25.pkl"
UA = "Mozilla/5.0 (X11; Linux x86_64) SuperAvokati-corpus/1.0"
SUPERSEDED = {"ligji_te_dhenat": "ligji_te_dhenat_2024",   # vecchio → nuovo (il vecchio resta, marcato abrogato)
              "ligji_policia": "ligji_policia_2024"}       # 108/2014 shfuqizuar nga 82/2024


def _download(url: str, dest: Path) -> None:
    if dest.exists() and dest.stat().st_size > 10_000:
        return
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=300) as r:
        data = r.read()
    if not data.startswith(b"%PDF"):
        raise RuntimeError(f"non e' un PDF ({data[:12]!r})")
    dest.write_bytes(data)


def _extract(pdf: Path, x_tol: float) -> str:
    """parser.extract_text_smart (una o due colonne, scelta automatica) con x_tolerance
    regolabile: il PDF QBZ della TVSH (e in parte altri) INCOLLA le parole con la tolleranza
    di default (3): «Kyligjvendostatimin» → space% 0.06, parole medie 11,9 chr; con 1.5
    torna normale (0.14 / 5,3 chr)."""
    from src.parser import extract_text_smart
    return extract_text_smart(pdf, x_tolerance=x_tol)


def _quality(text: str) -> dict:
    words = text.split()
    n = max(len(words), 1)
    return {"space": round(text.count(" ") / max(len(text), 1), 3),
            "avg_word": round(sum(len(w) for w in words) / n, 1),
            "long_ratio": round(sum(1 for w in words if len(w) > 25) / n, 4),
            # «ligjrregullon», «Neni1»: parole di 16+ lettere sono rare in albanese (~0,3%);
            # e' il rilevatore fine delle parole incollate
            "glue_ratio": round(sum(1 for w in words if len(w) > 15) / n, 4),
            "short_ratio": round(sum(1 for w in words if len(w) == 1) / n, 3)}


def _good(q: dict) -> bool:
    # albanese normale: space% 0.10-0.20, parola media 4.5-7.5 chr, quasi nessuna parola >25 chr,
    # poche parole >15 chr, non troppe lettere isolate (segno di parole SPEZZATE da una
    # tolleranza troppo bassa). In albanese «e», «i», «a» sono particelle frequentissime:
    # ~10-12% di parole di 1 lettera e' normale; oltre il 20% e' spezzatura.
    return (0.08 <= q["space"] <= 0.25 and 4.3 <= q["avg_word"] <= 7.5 and q["long_ratio"] < 0.003
            and q["glue_ratio"] < 0.012 and q["short_ratio"] < 0.20)


def probe_one(law: dict) -> tuple[dict, list]:
    code = law["code"]
    pdf = RAW / f"{code}.pdf"
    _download(law["url"], pdf)
    # tolleranza adattiva: si provano default, 1.5 e 1.0 e vince quella con MENO parole
    # incollate (glue_ratio) tra quelle che passano la qualità; a parità la più vicina
    # alla default (per non spezzare parole). Il PDF della TVSH passa da 0.063 a 0.146 di
    # spazi; «ligjrregullon»/«Neni1» spariscono con 1.5.
    cands = []
    for cand in (float(law.get("x_tolerance", 3)), 1.5, 1.0):
        t = _extract(pdf, cand)
        cands.append((t, _quality(t), cand))
    good = [c for c in cands if _good(c[1])]
    text, q, tol = min(good or cands, key=lambda c: (c[1]["glue_ratio"], c[1]["long_ratio"]))
    chars = max(len(text), 1)
    neni = len(re.findall(r"(?m)^[ \t]*Neni[ \t]+\d+", text))
    doc = LegalDocument(code=code, title_sq=law["title_sq"], title_en=code, area=law.get("area", ""),
                        url=law["url"], local_pdf=f"al_qbz/{code}.pdf", volatility=law.get("volatility", "MEDIUM"))
    arts = split_into_articles(text, doc)
    nums = [a.number for a in arts]
    first_ok = bool(nums) and str(nums[0]).split("/")[0] in ("1", "01")
    ok = _good(q) and len(arts) >= 8 and first_ok
    info = {"code": code, "kb": pdf.stat().st_size // 1024, "chars": chars, "x_tolerance": tol, **q,
            "neni_headers": neni, "articles": len(arts), "first": nums[0] if nums else "-",
            "last": nums[-1] if nums else "-", "ok": ok}
    return info, arts


def cmd_probe(only: str | None) -> int:
    laws = json.loads(SRC.read_text(encoding="utf-8"))["laws"]
    RAW.mkdir(parents=True, exist_ok=True); OUT.mkdir(parents=True, exist_ok=True)
    bad = 0
    force = "--force" in sys.argv
    for law in laws:
        if "code" not in law:          # voci di commento («_refresh»)
            continue
        if only and law["code"] != only:
            continue
        if not only and not force and (OUT / f"{law['code']}.json").exists():
            print(f"  = {law['code']:28s} già misurato (usa --force per rifare)", flush=True)
            continue
        if not only and law.get("kb", 0) > 5000:
            # VKM 651/2017 = 16 MB (centinaia di pagine con allegati): 3 estrazioni durano
            # decine di minuti e bloccano il giro — si lancia da sola: `probe vkm_dispozita_doganore`
            print(f"  · {law['code']:28s} {law['kb']:>6} KB  saltato nel giro (grande): lanciare da solo", flush=True)
            continue
        t0 = time.time()
        try:
            info, arts = probe_one(law)
        except Exception as exc:  # noqa: BLE001
            print(f"  ✗ {law['code']:28s} ERRORE {type(exc).__name__}: {str(exc)[:80]}", flush=True)
            bad += 1
            continue
        (OUT / f"{law['code']}.json").write_text(
            json.dumps([asdict(a) for a in arts], ensure_ascii=False), encoding="utf-8")
        print(f"  {'✓' if info['ok'] else '✗'} {info['code']:28s} {info['kb']:>6} KB  tol={info['x_tolerance']}  "
              f"space={info['space']:.3f} avg={info['avg_word']} glue={info['glue_ratio']} long={info['long_ratio']}  "
              f"Neni={info['neni_headers']:>4}  art={info['articles']:>4} ({info['first']}..{info['last']})  {time.time() - t0:.0f}s", flush=True)
        if arts:
            a = arts[0]
            print(f"      art.{a.number}: {a.heading[:50]!r} | {a.body[:70]!r}")
        bad += 0 if info["ok"] else 1
    print(f"\nfuori gate: {bad}")
    return 1 if bad else 0


def cmd_apply() -> int:
    from src.retrieval import ArticleIndex
    laws = json.loads(SRC.read_text(encoding="utf-8"))["laws"]
    lines = JSONL.read_text(encoding="utf-8").splitlines()
    have = {json.loads(ln)["code"] for ln in lines if ln.strip()}
    added, skipped, replaced = [], [], []
    new_lines: list[str] = []
    drop_codes: set[str] = set()
    for law in laws:
        if "code" not in law:
            continue
        code = law["code"]
        f = OUT / f"{code}.json"
        if code in have and not law.get("replace"):
            skipped.append(code); continue
        if not f.exists():
            print(f"  ! {code}: manca il probe — salto"); continue
        arts = json.loads(f.read_text(encoding="utf-8"))
        if len(arts) < 8:
            print(f"  ! {code}: solo {len(arts)} articoli — salto"); continue
        if code in have:
            # «replace»: il codice c'era già da un PDF vecchio (ministeri, 2014-2016) e viene
            # RISCRITTO dal testo consolidato QBZ — via le righe vecchie
            drop_codes.add(code); replaced.append((code, len(arts)))
        else:
            added.append((code, len(arts)))
        for a in arts:
            new_lines.append(json.dumps(a, ensure_ascii=False))
    if drop_codes:
        lines = [ln for ln in lines if ln.strip() and json.loads(ln).get("code") not in drop_codes]
    # vecchie leggi sostituite: restano nel corpus ma marcate abrogate (il verificatore dice «superata»)
    marked = 0
    for i, ln in enumerate(lines):
        if not ln.strip():
            continue
        d = json.loads(ln)
        if d.get("code") in SUPERSEDED and not d.get("repealed"):
            d["repealed"] = True
            lines[i] = json.dumps(d, ensure_ascii=False)
            marked += 1
    if not added and not marked and not replaced:
        print("niente da fare"); return 0
    if replaced:
        print(f"riscritti da QBZ: {', '.join(f'{c} ({n})' for c, n in replaced)}")
    bak = JSONL.with_suffix(f".jsonl.bak-{time.strftime('%Y%m%d-%H%M%S')}")
    shutil.copy2(JSONL, bak)
    JSONL.write_text("\n".join(lines + new_lines) + "\n", encoding="utf-8")
    print(f"aggiunti: {', '.join(f'{c} ({n})' for c, n in added)} | gia' presenti: {', '.join(skipped) or '-'} | "
          f"marcati abrogati: {marked} | backup jsonl: {bak.name}")
    if INDEX.exists():
        ibak = INDEX.with_suffix(f".pkl.bak-{time.strftime('%Y%m%d-%H%M%S')}")
        shutil.copy2(INDEX, ibak)
        print(f"backup indice: {ibak.name}")
    idx = ArticleIndex.from_jsonl(JSONL, lang="sq")
    idx.save(INDEX)
    idx2 = ArticleIndex.load(INDEX)
    codes = {}
    for a in idx2.articles:
        codes[a.code] = codes.get(a.code, 0) + 1
    print(f"indice AL: {len(idx2.articles)} nene / {len(codes)} kode")
    return 0


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "probe"
    if mode == "probe":
        _only = next((a for a in sys.argv[2:] if not a.startswith("--")), None)   # «--force» non e' un id
        sys.exit(cmd_probe(_only))
    if mode == "apply":
        sys.exit(cmd_apply())
    print(__doc__); sys.exit(2)
