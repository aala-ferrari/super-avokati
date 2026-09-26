# -*- coding: utf-8 -*-
"""BENCHMARK LAB (v9.332, roadmap v3 P0) — misura se il cervello è DAVVERO migliore, non se sembra.

Tre strati, dal più economico al più caro:
  STRATO 1 — deterministico, senza modello, secondi: `tools/benchmark/layer1_auto.jsonl` (generato dal
    corpus con `gen`: la query di un articolo deve riportare QUELL'articolo nei primi 12; gli abrogati
    devono uscire «repealed», i numeri oltre il massimo «fake») + `layer1_manual.jsonl` (risolutore
    delle sigle, REGRESSIONI = ogni errore vero già trovato diventa un test permanente, recupero del
    cervello con ancore su triage sintetico). Gate: soglie per tipo + nessun calo > 2 punti rispetto
    all'ultimo giro (storico in data/benchmark/layer1_history.jsonl).
  STRATO 2 — casi verificati da avvocati (`tools/golden_cases/*.json`), col cervello vero via HTTP
    (come il browser): must_cite / must_not_cite / key_points / verdetto / lingua / Trust Line / tempo.
    Costa una domanda al cervello per caso (3-30 min): `--limit N`, di notte, mai in CI.
  STRATO 3 — il golden_check (struttura), già esistente.
Regola: un nuovo cervello ESCE solo se lo strato 1 non regredisce e lo strato 2 non peggiora.

    python3 tools/benchmark_lab.py gen                       # rigenera layer1_auto dal corpus vivo
    python3 tools/benchmark_lab.py run                       # strato 1 (gate: exit 1 se regredisce)
    python3 tools/benchmark_lab.py run --layer 2 --limit 3   # strato 2 sul cervello vero (HTTP)
    python3 tools/benchmark_lab.py history                   # gli ultimi giri
"""
from __future__ import annotations

import glob
import hashlib
import json
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.retrieval import ArticleIndex, INDEX_FILE  # noqa: E402

BENCH_DIR = ROOT / "tools" / "benchmark"
AUTO = BENCH_DIR / "layer1_auto.jsonl"
MANUAL = BENCH_DIR / "layer1_manual.jsonl"
CASES_DIR = ROOT / "tools" / "golden_cases"
DATA_DIR = Path(os.environ.get("BENCH_DATA_DIR", str(INDEX_FILE.parent.parent / "benchmark")))
HISTORY = DATA_DIR / "layer1_history.jsonl"
K = 12

# soglie del gate (strato 1) — misurate il 16 set 2026 (audit: self-retrieval AL 97%, IT 89%)
SOGLIE = {"retrieval:al": 0.93, "retrieval:it": 0.85, "status": 1.0, "resolver": 1.0,
          "regression": 1.0, "brain_retrieve": 0.90}
CALO_MAX = 0.02

# come si scrive la citazione di un codice (per generare i test di stato)
CITE_AL = {"kodi_civil": "neni {n} i Kodit Civil", "kodi_penal": "neni {n} i Kodit Penal",
           "kodi_proc_civile": "neni {n} i Kodit të Procedurës Civile", "kodi_proc_penale": "neni {n} i Kodit të Procedurës Penale",
           "kodi_punes": "neni {n} i Kodit të Punës", "kodi_familjes": "neni {n} i Kodit të Familjes",
           "kodi_rrugor": "neni {n} i Kodit Rrugor", "kushtetuta": "neni {n} i Kushtetutës",
           "ligji_te_huajt": "neni {n} i ligjit nr. 79/2021", "ligji_tvsh": "neni {n} i ligjit nr. 92/2014"}
CITE_IT = {"codice_civile": "art. {n} c.c.", "codice_penale": "art. {n} c.p.", "codice_procedura_civile": "art. {n} c.p.c.",
           "codice_procedura_penale": "art. {n} c.p.p.", "codice_strada": "art. {n} C.d.S.", "costituzione": "art. {n} Cost.",
           "cittadinanza": "art. {n} L. 91/1992", "riscossione": "art. {n} DPR 602/1973", "tu_iva": "art. {n} D.Lgs. 10/2026",
           "reg_ue_2015_2446": "art. {n} Reg. (UE) 2015/2446"}


def _idx():
    al = ArticleIndex.load()
    it = None
    p = INDEX_FILE.parent / "bm25_it.pkl"
    if p.exists():
        it = ArticleIndex.load(p)
    return al, it


def _num_int(n) -> int:
    m = re.match(r"(\d+)", str(n))
    return int(m.group(1)) if m else -1


# rubriche GENERICHE condivise da decine di atti («Ambito di applicazione», «Definizioni»…): da sole
# non identificano l'articolo, quindi la query prende anche le prime parole del corpo
_GENERIC_RE = re.compile(r"^\W*(ambito|campo|oggetto|finalit|definizion|disposizion|entrata in vigore|abrogazion|norme|"
                         r"principi|scopo|qëllimi|objekti|fusha|përkufizim|dispozita|hyrja në fuqi|shfuqizim|parime)", re.I)


def _query_of(a, heading_count: int = 1) -> str:
    h = re.sub(r"\(\(|\)\)", " ", (a.heading or "")).strip(" ().\n\t")
    h = re.sub(r"\s+", " ", h)
    b = " ".join(re.sub(r"\(\(|\)\)", " ", (a.body or "")).split()[:14])
    if len(h.split()) >= 3 and heading_count == 1 and not _GENERIC_RE.match(h):
        return h if len(h) < 160 else " ".join(h.split()[:20])
    return (h + " " + b).strip()


# ── gen ─────────────────────────────────────────────────────────────────────
def gen() -> int:
    al, it = _idx()
    out: list[dict] = []
    for lang, idx in (("al", al), ("it", it)):
        if idx is None:
            continue
        by: dict[str, list] = {}
        hc: dict[str, int] = {}
        for a in idx.articles:
            if a.repealed or not ((a.heading or "").strip() or (a.body or "").strip()):
                continue
            if _num_int(a.number) < 1 or str(a.number).lower().startswith("allegato"):
                continue                                   # allegati/tabelle: non sono «articoli» da citare
            by.setdefault(a.code, []).append(a)
            hk = re.sub(r"\W+", " ", (a.heading or "").lower()).strip()
            hc[hk] = hc.get(hk, 0) + 1
        ncodes = max(1, len(by))
        per = max(2, min(8, 320 // ncodes))
        for code in sorted(by):
            arts = sorted(by[code], key=lambda a: (_num_int(a.number), str(a.number)))
            if len(arts) <= per:
                pick = arts
            else:
                step = len(arts) / per
                pick = [arts[int(i * step)] for i in range(per)]
            for a in pick:
                q = _query_of(a, hc.get(re.sub(r"\W+", " ", (a.heading or "").lower()).strip(), 1))
                if len(q) < 12:
                    continue
                out.append({"id": f"{lang}-ret-{code}-{a.number}", "lang": lang, "kind": "retrieval",
                            "query": q, "expect": [[code, str(a.number)]], "k": K})
        # stato del verificatore: verificato / abrogato / inesistente per i codici con sigla nota
        cite = CITE_AL if lang == "al" else CITE_IT
        all_by: dict[str, list] = {}
        for a in idx.articles:
            all_by.setdefault(a.code, []).append(a)
        for code, fmt in cite.items():
            arts = all_by.get(code) or []
            if not arts:
                continue
            live = sorted([a for a in arts if not a.repealed], key=lambda a: _num_int(a.number))
            dead = sorted([a for a in arts if a.repealed], key=lambda a: _num_int(a.number))
            for a in (live[len(live) // 3], live[(2 * len(live)) // 3]) if len(live) >= 3 else live[:1]:
                if _num_int(a.number) > 0:
                    out.append({"id": f"{lang}-st-{code}-{a.number}", "lang": lang, "kind": "status",
                                "citation": fmt.format(n=a.number), "expect": "verified", "code": code})
            for a in dead[:2]:
                if _num_int(a.number) > 0:
                    out.append({"id": f"{lang}-st-{code}-{a.number}-rep", "lang": lang, "kind": "status",
                                "citation": fmt.format(n=a.number), "expect": "repealed", "code": code})
            mx = max(_num_int(a.number) for a in arts)
            out.append({"id": f"{lang}-st-{code}-fake", "lang": lang, "kind": "status",
                        "citation": fmt.format(n=mx + 137), "expect": "fake", "code": code})
    dest = AUTO
    if "--out" in sys.argv:
        dest = Path(sys.argv[sys.argv.index("--out") + 1])
    try:
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in out) + "\n", encoding="utf-8")
    except PermissionError:
        # nel container /app/tools non è scrivibile: si scrive nel volume e si riporta nel repo
        dest = DATA_DIR / "layer1_auto.jsonl"
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in out) + "\n", encoding="utf-8")
    kinds = {}
    for r in out:
        kinds[r["kind"] + ":" + r["lang"]] = kinds.get(r["kind"] + ":" + r["lang"], 0) + 1
    print(f"generati {len(out)} test → {dest}: {kinds}")
    return 0


def _auto_path() -> Path:
    """Il file generato: nel repo (tools/benchmark) o, se lì non c'è, nel volume dati."""
    if AUTO.exists():
        return AUTO
    alt = DATA_DIR / "layer1_auto.jsonl"
    return alt if alt.exists() else AUTO


# ── run: strato 1 ───────────────────────────────────────────────────────────
def _load_jsonl(p: Path) -> list[dict]:
    if not p.exists():
        return []
    return [json.loads(ln) for ln in p.read_text(encoding="utf-8").splitlines() if ln.strip()]


def _brain_retrieve(sa, lang: str, case: dict):
    from src.brain import TriageResult, set_request_jurisdiction
    jur = "IT" if lang == "it" else "AL"
    set_request_jurisdiction(jur)
    try:
        sa._jurisdiction_ctx.code = jur      # è ciò che legge `_current_jurisdiction` (per-istanza)
    except Exception:  # noqa: BLE001
        pass
    t = TriageResult(problem_summary=case.get("summary") or "", areas=list(case.get("areas") or []),
                     search_queries=list(case.get("queries") or []), strategic_angles=list(case.get("angles") or []))
    return [(a.code, str(a.number)) for a, _ in sa._retrieve(t)]


def run_layer1(verbose: bool = True) -> dict:
    from src import citation_verifier as cv
    al, it = _idx()
    tests = _load_jsonl(_auto_path()) + _load_jsonl(MANUAL)
    if not tests:
        print("nessun test: lancia prima `gen`")
        return {}
    sa = None
    res: dict[str, list[int]] = {}
    fails: list[str] = []
    t0 = time.time()
    for c in tests:
        lang = c.get("lang", "al")
        idx = it if (lang == "it" and it is not None) else al
        kind = c["kind"]
        key = f"{kind}:{lang}" if kind == "retrieval" else kind
        ok = False
        try:
            if kind == "retrieval":
                hits = {(a.code, str(a.number)) for a, _ in idx.search(c["query"], top_k=int(c.get("k") or K))}
                ok = all(tuple(e) in hits for e in c["expect"])
            elif kind == "status":
                r = cv.verify_text(c["citation"], idx)
                items = r.get("items") or []
                st = items[0]["status"] if items else "none"
                ok = st == c["expect"] and (not c.get("code") or st == "fake" or items[0].get("code") == c["code"])
                if not ok:
                    fails.append(f"{c['id']}: atteso {c['expect']} ({c.get('code')}), avuto {st} ({items[0].get('code') if items else '-'})")
            elif kind == "resolver":
                got = cv._resolve_code_it(c["label"]) if lang == "it" else cv._resolve_code(c["label"])
                ok = got == c["expect"]
                if not ok:
                    fails.append(f"{c['id']}: «{c['label']}» → {got}, atteso {c['expect']}")
            elif kind == "regression":
                ok = _regression(c, idx, cv)
                if not ok:
                    fails.append(f"{c['id']}: {c.get('note', '')}")
            elif kind == "brain_retrieve":
                if sa is None:
                    from src.brain import SuperAvvocato
                    sa = SuperAvvocato(index=al, index_it=it)   # come web.py: senza index_it l'IT userebbe l'indice AL
                got = _brain_retrieve(sa, lang, c)
                ok = all(tuple(e) in got for e in c["expect"])
                if not ok:
                    fails.append(f"{c['id']}: attesi {c['expect']}, recuperati {got[:8]}")
            else:
                continue
        except Exception as exc:  # noqa: BLE001
            fails.append(f"{c['id']}: ERRORE {type(exc).__name__}: {str(exc)[:80]}")
        if kind == "retrieval" and not ok:
            fails.append(f"{c['id']}: «{c['query'][:60]}» non porta {c['expect']}")
        res.setdefault(key, []).append(1 if ok else 0)
    rates = {k: (sum(v) / len(v)) for k, v in res.items()}
    summary = {"ts": datetime.now().isoformat(timespec="seconds"), "n": len(tests),
               "rates": {k: round(r, 4) for k, r in rates.items()},
               "counts": {k: [sum(v), len(v)] for k, v in res.items()}, "secs": round(time.time() - t0, 1)}
    if verbose:
        print("=" * 72)
        for k in sorted(rates):
            s, n = summary["counts"][k]
            soglia = SOGLIE.get(k, SOGLIE.get(k.split(":")[0], 0))
            flag = "✓" if rates[k] >= soglia else "✗"
            print(f"  {flag} {k:16s} {s:4d}/{n:<4d} = {rates[k]:6.1%}   (soglia {soglia:.0%})")
        print(f"  {len(tests)} test in {summary['secs']}s")
        for f in fails[:40]:
            print("   ·", f)
        if len(fails) > 40:
            print(f"   · … e altri {len(fails) - 40}")
    return summary


def _regression(c: dict, idx, cv) -> bool:
    """Un errore vero già trovato = un test per sempre. Forme: status / resolver / retrieval / exists."""
    t = c.get("test", {})
    if t.get("kind") == "exists":
        by = {(a.code, str(a.number)): a for a in idx.articles}
        a = by.get((t["code"], str(t["number"])))
        if a is None:
            return False
        if t.get("live") and a.repealed:
            return False
        if t.get("repealed") and not a.repealed:
            return False
        if t.get("heading_has") and t["heading_has"].lower() not in (a.heading or "").lower():
            return False
        return True
    if t.get("kind") == "status":
        r = cv.verify_text(t["text"], idx, retrieved_codes=set(t.get("ctx") or []) or None)
        by = {i["number"]: i for i in r.get("items") or []}
        i = by.get(t["number"])
        return i is not None and i["status"] == t["expect"] and (not t.get("code") or i.get("code") == t["code"])
    if t.get("kind") == "resolver":
        got = cv._resolve_code_it(t["label"]) if c.get("lang") == "it" else cv._resolve_code(t["label"])
        return got == t["expect"]
    if t.get("kind") == "retrieval":
        hits = {(a.code, str(a.number)) for a, _ in idx.search(t["query"], top_k=int(t.get("k") or K))}
        return all(tuple(e) in hits for e in t["expect"])
    return False


def gate(summary: dict, prev: dict | None) -> tuple[bool, list[str]]:
    problemi = []
    for k, r in (summary.get("rates") or {}).items():
        soglia = SOGLIE.get(k, SOGLIE.get(k.split(":")[0], 0))
        if r < soglia:
            problemi.append(f"{k} {r:.1%} < soglia {soglia:.0%}")
        if prev and k in (prev.get("rates") or {}) and r < prev["rates"][k] - CALO_MAX:
            problemi.append(f"{k} regredisce: {prev['rates'][k]:.1%} → {r:.1%}")
    return (not problemi), problemi


def _last_history() -> dict | None:
    rows = _load_jsonl(HISTORY)
    return rows[-1] if rows else None


def _save_history(summary: dict, ok: bool, versione: str) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    row = dict(summary, gate="pass" if ok else "FAIL", version=versione)
    with HISTORY.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, ensure_ascii=False) + "\n")


def _versione() -> str:
    if "--version" in sys.argv:
        return sys.argv[sys.argv.index("--version") + 1]
    for p in (ROOT / "run.sh", Path("/app/run.sh")):
        if p.exists():
            m = re.search(r"super-avvocato:(v[\d.]+)", p.read_text(encoding="utf-8", errors="replace"))
            if m:
                return m.group(1)
    return os.environ.get("SA_VERSION", "?")


# ── run: strato 2 (cervello vero, via HTTP come il browser) ─────────────────
def run_layer2(limit: int, only: str | None, mode: str = "normal", ids: list[str] | None = None) -> dict:
    import http.cookiejar
    import urllib.request
    from src import citation_verifier as cv
    base = os.environ.get("BENCH_BASE", "http://127.0.0.1:5050")
    cases = []
    for p in sorted(glob.glob(str(CASES_DIR / "*.json"))):
        try:
            c = json.load(open(p, encoding="utf-8"))
            if only and only not in c.get("id", ""):
                continue
            if ids and c.get("id") not in ids:
                continue
            cases.append(c)
        except Exception as e:  # noqa: BLE001
            print(f"[warn] caso illeggibile {p}: {e}")
    cases = cases[:limit] if limit else cases
    al, it = _idx()
    # v9.356 — «mode»: normal = il triage decide; deep = 🔬 Analizë e thellë (force_complex);
    # fable = ⚡ Skuadra maksimale (senior Fable max + deep). Per misurare i due pulsanti profondi.
    mode = (mode or "normal").strip().lower()
    payload_extra = {"deep": True} if mode == "deep" else ({"deep": True, "mendja": "fable"} if mode == "fable" else {})
    run_id = datetime.now().strftime("%Y%m%d-%H%M%S") + ("-" + mode if mode != "normal" else "")
    out_dir = DATA_DIR / "layer2" / run_id
    out_dir.mkdir(parents=True, exist_ok=True)
    results = []
    for c in cases:
        juris = (c.get("jurisdiction") or "AL").upper()
        idx = it if (juris == "IT" and it is not None) else al
        cj = http.cookiejar.CookieJar()
        op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))

        def post(path, payload, headers=None, timeout=120):
            h = {"Content-Type": "application/json"}
            h.update(headers or {})
            req = urllib.request.Request(base + path, data=json.dumps(payload).encode(), headers=h)
            with op.open(req, timeout=timeout) as r:
                return json.loads(r.read().decode())
        try:
            if juris == "IT":
                post("/api/login", {"username": os.environ.get("BENCH_IT_USER", "admin.it"),
                                    "password": os.environ.get("BENCH_IT_PASS", "AdminIT2026!"), "lang": "it"})
            else:
                ts = int(time.time())
                email, code = f"bench-{ts}@superavokati.test", f"Bench-{ts}"
                # v9.369: l'account di prova si cancella SEMPRE all'uscita (anche su errore): ne erano rimasti 19 e il digest ci scriveva
                __import__('atexit').register(lambda _e=email: (__import__('sys').path.insert(0, '/app'), __import__('src.storage', fromlist=['delete_user']).delete_user(_e)))
                post("/api/provision-demo", {"email": email, "code": code, "hours": 6},
                     headers={"X-Provision-Secret": os.environ.get("DEMO_PROVISION_SECRET", "")})
                post("/api/login", {"username": email, "password": code, "lang": "sq"})
            case = post("/api/cases", {"title": f"Benchmark {c['id']}", "jurisdiction": juris})
            q = c.get("question") or c.get("facts") or ""
            t0 = time.time()
            job = post("/api/ask/start", {"case_id": case["id"], "message": q, **payload_extra}).get("job_id")
            final, audit = "", {}
            with op.open(urllib.request.Request(f"{base}/api/ask/events?job={job}&from=0"), timeout=3600) as r:
                for raw in r:
                    line = raw.decode("utf-8", "replace").strip()
                    if not line.startswith("data:"):
                        continue
                    try:
                        evt = json.loads(line[5:].strip())
                    except Exception:  # noqa: BLE001
                        continue
                    if evt.get("type") == "final":
                        final = evt.get("text") or ""
                        audit = ((evt.get("provenance") or {}).get("extra") or {}).get("audit") or {}
                    elif evt.get("type") == "done":
                        break
            secs = time.time() - t0
        except Exception as exc:  # noqa: BLE001
            results.append({"id": c["id"], "error": f"{type(exc).__name__}: {str(exc)[:100]}"})
            print(f"✗ {c['id']}: ERRORE {exc}")
            continue
        (out_dir / f"{c['id']}.md").write_text(final, encoding="utf-8")
        # v9.357 — come in produzione: i codici RECUPERATI (dall'audit) sciolgono i numeri nudi
        # («neni 152» in un caso di lavoro); senza, il benchmark contava «senza codice» = mancante
        _rc = {a.get("code") for a in ((audit.get("recupero") or {}).get("articoli") or []) if a.get("code")} or None
        r = cv.verify_text(final, idx, retrieved_codes=_rc)
        cited_ok = {(i["code"], i["number"]) for i in r["items"] if i["status"] == "verified"}
        cited_any = {(i.get("code"), i["number"]) for i in r["items"]}
        exp = [(e["code"], str(e["number"])) for e in (c.get("expected_laws") or [])]
        must_not = [(e["code"], str(e["number"])) for e in (c.get("must_not_cite") or [])]
        found = [e for e in exp if e in cited_ok or any(x[1] == e[1] and x[0] == e[0] for x in cited_any)]
        viol = [e for e in must_not if e in cited_any]
        kps = c.get("key_points") or []
        kp_ok = [k for k in kps if re.search(k, final, re.I)]
        head_ok = final.lstrip().startswith("### ⚖️")
        trust = "🔎" in final[:600]
        if juris == "IT":
            impur = len(re.findall(r"[ëç]|\b(nuk|është|janë|sipas|nenit|neni)\b", final))
        else:
            impur = len(re.findall(r"\b(art\.|articolo|comma|sentenza|tribunale|avvocato|verdetto)\b", final))
        score = (0.45 * (len(found) / len(exp) if exp else 1.0) + 0.25 * (len(kp_ok) / len(kps) if kps else 1.0)
                 + 0.15 * (1.0 if not viol else 0.0) + 0.10 * (1.0 if head_ok else 0.0) + 0.05 * (1.0 if impur == 0 else 0.0))
        _cl = audit.get("claims") or {}
        row = {"id": c["id"], "juris": juris, "secs": round(secs), "chars": len(final),
               # v9.342 — claim binding in ombra: quante proposizioni materiali senza sostegno
               "claims": {"materiali": _cl.get("materiali", 0), "unsupported": _cl.get("unsupported", 0),
                          "contradicted": _cl.get("contradicted", 0), "high_unsupported": _cl.get("high_unsupported", 0)} if _cl else None,
               "giudice": (audit.get("giudice") or {}).get("esito"), "giudice_mendja": (audit.get("giudice") or {}).get("mendja"),
               "cancello": audit.get("cancello"), "mode": mode,
               "must_cite": f"{len(found)}/{len(exp)}", "missing": [e for e in exp if e not in found],
               "must_not_violations": viol, "key_points": f"{len(kp_ok)}/{len(kps)}", "kp_missing": [k for k in kps if k not in kp_ok],
               "verdict_head": head_ok, "trust_line": trust, "fake": r["stats"]["fake"], "repealed": r["stats"]["repealed"],
               "lang_impurity": impur, "score": round(score, 3), "validated_by": c.get("validated_by")}
        results.append(row)
        if juris == "IT":
            # v9.393 — il fascicolo di prova nell'account italiano (admin.it) si cancella a fine caso: dal 21 set se ne erano
            # accumulati 47 «Benchmark …» nell'elenco del titolare (l'account albanese di prova si cancella già all'uscita)
            try:
                op.open(urllib.request.Request(f"{base}/api/cases/{case['id']}", method="DELETE"), timeout=30).read()
            except Exception:  # noqa: BLE001
                pass
        print(f"{'✓' if score >= 0.8 else '~' if score >= 0.6 else '✗'} {c['id']}: score {score:.2f} · norme {row['must_cite']} · punti {row['key_points']} · "
              f"vietate {len(viol)} · fake {row['fake']} · {secs:.0f}s")
    if results:
        scored = [x["score"] for x in results if "score" in x]
        agg = {"run": run_id, "mode": mode, "n": len(results), "mean_score": round(sum(scored) / len(scored), 3) if scored else 0,
               "mean_secs": round(sum(x.get("secs", 0) for x in results if "secs" in x) / max(1, len([x for x in results if "secs" in x]))),
               "errors": sum(1 for x in results if "error" in x), "version": _versione()}
        (out_dir / "summary.json").write_text(json.dumps({"agg": agg, "results": results}, ensure_ascii=False, indent=1), encoding="utf-8")
        with (DATA_DIR / "layer2_history.jsonl").open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(agg, ensure_ascii=False) + "\n")
        print(f"strato 2: {agg}  → {out_dir}")
        return agg
    return {}


def history() -> int:
    for row in _load_jsonl(HISTORY)[-10:]:
        print(row.get("ts"), row.get("version"), row.get("gate"), row.get("rates"))
    for row in _load_jsonl(DATA_DIR / "layer2_history.jsonl")[-10:]:
        print("L2", row)
    return 0


def main(argv: list[str]) -> int:
    if not argv or argv[0] == "run":
        layer = int(argv[argv.index("--layer") + 1]) if "--layer" in argv else 1
        if layer == 2:
            limit = int(argv[argv.index("--limit") + 1]) if "--limit" in argv else 3
            only = argv[argv.index("--only") + 1] if "--only" in argv else None
            mode = argv[argv.index("--mode") + 1] if "--mode" in argv else "normal"
            ids = [x.strip() for x in argv[argv.index("--ids") + 1].split(",") if x.strip()] if "--ids" in argv else None
            run_layer2(limit, only, mode, ids)
            return 0
        summary = run_layer1()
        if not summary:
            return 2
        prev = _last_history()
        ok, problemi = gate(summary, prev)
        if "--json" in argv:
            Path(argv[argv.index("--json") + 1]).write_text(json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")
        if "--no-save" not in argv:
            _save_history(summary, ok, _versione())
        print("GATE:", "PASS" if ok else "FAIL — " + "; ".join(problemi))
        return 0 if (ok or "--no-gate" in argv) else 1
    if argv[0] == "gen":
        return gen()
    if argv[0] == "history":
        return history()
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
