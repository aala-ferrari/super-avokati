"""V8.11 Citation Shield V2 — benchmark eval runner.

Runs the queries in ``legal_queries_<lang>.jsonl`` against Super Avvocato,
extracts the citations the model produced, verifies them against the BM25
index, and scores each row on three axes:

  * **citation_present**: did the model cite at least one article? (the
    "no answer" rate — too many false negatives is silent failure)
  * **expected_code_hit**: does any cited article belong to one of the
    codes the ground-truth row tagged as relevant?
  * **fake_count**: how many citations resolved to "fake" (article number
    that doesn't exist in the cited code) — the hallucination floor.

Output is a single JSON-lines run file under ``benchmarks/runs/`` plus a
human-readable summary. The runner uses the *retrieval-only* path of the
brain when ``--no-llm`` is passed so the same dataset can be re-run for
free against retrieval changes; with ``--llm`` it actually composes
answers (slow, expensive — use during model upgrades only).

Run:
    ./venv/bin/python benchmarks/run_eval.py --no-llm
    ./venv/bin/python benchmarks/run_eval.py --llm --limit 10
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src import citation_shield as cs_mod
from src import citation_verifier as cv_mod
from src.retrieval import ArticleIndex


BENCHMARK_DIR = Path(__file__).resolve().parent
RUNS_DIR = BENCHMARK_DIR / "runs"
RUNS_DIR.mkdir(parents=True, exist_ok=True)


def load_dataset(path: Path) -> list[dict]:
    rows: list[dict] = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            rows.append(json.loads(line))
    return rows


def retrieval_only_answer(query: str, index: ArticleIndex) -> tuple[str, list]:
    """Build a synthetic 'answer' that just lists retrieved articles.

    This lets the eval probe whether retrieval surfaces the right code
    even before any LLM composition. The synthetic answer text contains
    "Neni N (Code)" for each top-K article, which then gets scored by
    ``citation_verifier`` exactly like a real answer would be.
    """
    hits = index.search(query, top_k=8)
    parts = []
    for art, score in hits:
        # Build a clean Albanian-style citation so the regex picks it up.
        parts.append(f"Neni {art.number} ({art.citation})")
    return ". ".join(parts), hits


def llm_answer(query: str, brain) -> tuple[str, list]:
    """Real composition path — slow and expensive."""
    result = brain.answer(query, history=[], dossier_documents=[])
    return result.text or "", result.retrieved


def score_row(
    row: dict,
    answer_text: str,
    retrieved: list,
    index: ArticleIndex,
) -> dict:
    retrieved_codes = {a.code for a, _ in retrieved}
    cv = cv_mod.verify_text(answer_text, index, retrieved_codes=retrieved_codes)
    stats = cv.get("stats") or {}
    items = cv.get("items") or []

    expected_codes = set(row.get("expected_codes") or [])
    cited_codes = {it.get("code") for it in items if it.get("code")}
    code_hit = bool(expected_codes & cited_codes) if expected_codes else None

    citation_present = stats.get("total", 0) > 0
    fake_count = stats.get("fake", 0)
    confidence = cs_mod.confidence_from_stats(stats)
    refused = cs_mod.should_refuse(cv)

    return {
        "id": row.get("id"),
        "area": row.get("area"),
        "query": row.get("query"),
        "expected_codes": list(expected_codes),
        "cited_codes": list(cited_codes),
        "citation_present": citation_present,
        "expected_code_hit": code_hit,
        "fake_count": fake_count,
        "verified_count": stats.get("verified", 0),
        "needs_code_count": stats.get("needs_code", 0),
        "total_citations": stats.get("total", 0),
        "confidence": confidence,
        "refused": refused,
    }


def aggregate(scored: list[dict]) -> dict:
    n = len(scored)
    if n == 0:
        return {"queries": 0}
    cit_present = sum(1 for r in scored if r["citation_present"])
    code_hits = [r["expected_code_hit"] for r in scored if r["expected_code_hit"] is not None]
    fake_total = sum(r["fake_count"] for r in scored)
    refusals = sum(1 for r in scored if r["refused"])
    avg_conf = round(sum(r["confidence"] for r in scored) / n, 3)
    return {
        "queries": n,
        "citation_present_rate": round(cit_present / n, 3),
        "expected_code_hit_rate": round(sum(code_hits) / len(code_hits), 3) if code_hits else None,
        "fake_total": fake_total,
        "refusal_count": refusals,
        "avg_confidence": avg_conf,
    }


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--dataset", default=str(BENCHMARK_DIR / "legal_queries_al.jsonl"))
    p.add_argument("--no-llm", action="store_true",
                   help="retrieval-only mode (default; no LLM cost)")
    p.add_argument("--llm", action="store_true",
                   help="run real LLM composition (slow, expensive)")
    p.add_argument("--limit", type=int, default=0,
                   help="cap number of queries (0 = all)")
    p.add_argument("--label", default="",
                   help="label for the run file name")
    args = p.parse_args()

    rows = load_dataset(Path(args.dataset))
    if args.limit > 0:
        rows = rows[: args.limit]

    print(f"[eval] loaded {len(rows)} queries from {args.dataset}")
    index = ArticleIndex.load()
    print(f"[eval] index: {len(index.articles)} articles")

    brain = None
    use_llm = bool(args.llm)
    if use_llm:
        from src.brain import SuperAvvocato
        brain = SuperAvvocato(index=index)
        print("[eval] LLM mode (slow)")

    t0 = time.time()
    scored: list[dict] = []
    for i, row in enumerate(rows, 1):
        try:
            if use_llm:
                answer_text, retrieved = llm_answer(row["query"], brain)
            else:
                answer_text, retrieved = retrieval_only_answer(row["query"], index)
            scored.append(score_row(row, answer_text, retrieved, index))
        except Exception as exc:
            print(f"[eval] {row.get('id')} FAILED: {exc}", file=sys.stderr)
            scored.append({
                "id": row.get("id"),
                "error": str(exc),
                "citation_present": False,
                "expected_code_hit": False,
                "fake_count": 0,
                "confidence": 0.0,
                "refused": False,
            })
        if i % 10 == 0 or i == len(rows):
            print(f"[eval] {i}/{len(rows)}")

    elapsed = round(time.time() - t0, 1)
    summary = aggregate(scored)
    summary["elapsed_seconds"] = elapsed
    summary["mode"] = "llm" if use_llm else "retrieval"
    summary["timestamp"] = datetime.now(timezone.utc).isoformat(timespec="seconds")

    label = args.label or ("llm" if use_llm else "retr")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    run_file = RUNS_DIR / f"run_{stamp}_{label}.jsonl"
    with open(run_file, "w", encoding="utf-8") as f:
        f.write(json.dumps({"_summary": summary}, ensure_ascii=False) + "\n")
        for r in scored:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    print()
    print("─── SUMMARY ───")
    for k, v in summary.items():
        print(f"  {k}: {v}")
    print(f"  run_file: {run_file}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
