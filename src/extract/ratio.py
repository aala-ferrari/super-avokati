"""Extract structured *ratio decidendi* from court decisions for the
Precedent Pattern Analyzer.

For every ``Case`` row with ``extraction_status='complete'`` and no
matching ``CaseAnalysis`` row, we ask Opus to identify, in shqip:

  * **winning_argument**   — the single argument that won the case
  * **losing_mistake**     — the mistake the loser made (if identifiable)
  * **dispositive_fact**   — the fact that pendulated the balance
  * **transferable_lesson** — 1-2 sentences of actionable lesson
  * **case_archetype**     — short label like "kontestim_testamenti"

We use ``claude -p`` (CLI, headless, JSON-schema enforced) — same
infrastructure as ``src/extract/run.py``. Idempotent: cases that already
have a ``CaseAnalysis`` are skipped, so re-running picks up where we
left off.

Cost (Opus 4.7, Apr 2026): ~$0.05–0.20 per call. For 815 cases the
worst-case is ~$160 but typical run lands around $80 thanks to caching.

Usage::

    ./venv/bin/python -m src.extract.ratio                     # all
    ./venv/bin/python -m src.extract.ratio --court ecthr_albania --limit 10
    ./venv/bin/python -m src.extract.ratio -w 4                # 4 workers
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential_jitter,
)

from src.db import Case, CaseAnalysis, Court, session_scope

log = logging.getLogger("ratio")

CLAUDE_BIN = os.getenv("CLAUDE_BIN", "/Users/mac/.local/bin/claude")
RATIO_MODEL = "opus"  # Opus 4.7 — depth matters for ratio extraction

# Same head+tail truncation strategy as src/extract/llm.py: keep the
# header (parties, articles cited) AND the operative part (which is at
# the end). Opus context is generous; we go higher than the extractor's MAX.
MAX_CHARS = 60_000


RATIO_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "winning_argument": {
            "type": "string",
            "description": (
                "Argumenti i vetëm vendimtar që e fitoi çështjen për palën "
                "fituese. 1-3 fjali në shqip, i ankoruar te një nen "
                "specifik ose te një fakt konkret. NUK është një përmbledhje "
                "e dispozitivit — është LEVA që zhvendosi peshoren."
            ),
        },
        "losing_mistake": {
            "type": "string",
            "description": (
                "Gabimi procedural ose substancial që bëri pala humbëse "
                "(p.sh. afati i humbur, mungesa e provës kryesore, "
                "argumenti i gabuar i bazës ligjore). Lëre BOSH '' nëse "
                "vendimi është vendosur thjesht në bazë substanciale, pa "
                "një 'gabim' specifik nga pala humbëse."
            ),
        },
        "dispositive_fact": {
            "type": "string",
            "description": (
                "Fakti i vetëm pa të cilin rezultati do të ishte ndryshe "
                "(një datë, një dokument, një provë e caktuar, një sjellje "
                "e palës). Specifik dhe i shkurtër. Bosh '' nëse nuk ka "
                "një fakt unik vendimtar."
            ),
        },
        "transferable_lesson": {
            "type": "string",
            "description": (
                "1-2 fjali në shqip për një avokat që merr një çështje "
                "të ngjashme: çfarë DUHET të bëjë (imitojë) ose çfarë "
                "DUHET të shmangë. Konkrete, jo trajni — p.sh. 'Mblidh "
                "noterizimin e testamentit para datës X' jo 'kujdes me "
                "afatet'."
            ),
        },
        "case_archetype": {
            "type": "string",
            "description": (
                "Etiketa e shkurtër (lowercase + underscores) që përshkruan "
                "tipologjinë e çështjes për matching me çështje të reja. "
                "Shembuj: 'kontestim_testamenti', 'ankim_jashteafati', "
                "'shpronesim_publik', 'ndarje_pasurie_bashkeshortore', "
                "'pushim_nga_puna_pa_arsye', 'liria_shprehjes_shtypi'. "
                "Maks 60 karaktere."
            ),
        },
    },
    "required": [
        "winning_argument", "losing_mistake", "dispositive_fact",
        "transferable_lesson", "case_archetype",
    ],
}


SYSTEM_PROMPT = (
    "Ti je një asistent ekspert për nxjerrjen e *ratio decidendi* nga "
    "vendime gjyqësore shqiptare ose nga vendime të GJEDNJ-së për Shqipërinë. "
    "Marrim si input tekstin e plotë të një vendimi. Detyra jote: identifiko "
    "ARGUMENTIN VENDIMTAR që e fitoi çështjen, gabimin e palës humbëse, "
    "faktin e pakthyeshëm, mësimin e transferueshëm dhe arketipin. "
    "RREGULLA: (1) Përgjigja vetëm në shqip. (2) Bazohu vetëm në tekstin "
    "e vendimit, mos shpik fakte. (3) Asnjë doktrinë italo-franceze ose e "
    "huaj — vetëm baza shqiptare ose Konventa Evropiane. (4) Output JSON "
    "i pastër sipas schema-së. Pa prozë shtesë, pa markdown."
)


DISALLOWED_TOOLS = (
    "Bash,Edit,Write,Read,Glob,Grep,Agent,TaskCreate,TaskUpdate,TaskList,"
    "TaskGet,TaskStop,TaskOutput,WebFetch,WebSearch,NotebookEdit,"
    "ToolSearch,ScheduleWakeup,Skill,PushNotification,CronCreate,"
    "CronList,CronDelete,RemoteTrigger,Monitor,ExitPlanMode,EnterPlanMode,"
    "EnterWorktree,ExitWorktree,AskUserQuestion"
)


class LLMError(RuntimeError):
    pass


@dataclass
class RatioExtraction:
    winning_argument: str = ""
    losing_mistake: str = ""
    dispositive_fact: str = ""
    transferable_lesson: str = ""
    case_archetype: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    model: str = RATIO_MODEL


def _truncate(text: str) -> str:
    if len(text) <= MAX_CHARS:
        return text
    half = MAX_CHARS // 2
    return text[:half] + "\n\n[...TRUNCATED...]\n\n" + text[-half:]


@retry(
    reraise=True,
    stop=stop_after_attempt(3),
    wait=wait_exponential_jitter(initial=4, max=40),
    retry=retry_if_exception_type(LLMError),
)
def _call_claude(decision_text: str, hint: str = "", timeout_s: int = 240) -> RatioExtraction:
    text = _truncate(decision_text)
    user_input = f"Konteksti: {hint}\n\n---\n\n{text}" if hint else text

    cmd = [
        CLAUDE_BIN,
        "-p",
        "--model", RATIO_MODEL,
        "--no-session-persistence",
        "--output-format", "json",
        "--system-prompt", SYSTEM_PROMPT,
        "--json-schema", json.dumps(RATIO_SCHEMA),
        "--disallowedTools", DISALLOWED_TOOLS,
    ]

    try:
        proc = subprocess.run(
            cmd, input=user_input, capture_output=True,
            text=True, timeout=timeout_s,
        )
    except subprocess.TimeoutExpired as e:
        raise LLMError(f"claude CLI timed out after {timeout_s}s") from e

    if proc.returncode != 0:
        raise LLMError(
            f"claude CLI exit={proc.returncode} stderr={proc.stderr[:300]}"
        )

    try:
        payload = json.loads(proc.stdout)
    except json.JSONDecodeError as e:
        raise LLMError(f"claude CLI returned non-JSON: {proc.stdout[:200]}") from e

    if payload.get("is_error"):
        raise LLMError(
            f"claude CLI is_error=True: {payload.get('result', '')[:200]}"
        )

    data = payload.get("structured_output")
    if not isinstance(data, dict):
        raw = payload.get("result", "")
        if isinstance(raw, str) and raw.strip().startswith("{"):
            try:
                data = json.loads(raw)
            except json.JSONDecodeError as e:
                raise LLMError("no structured_output and result not JSON") from e
        else:
            raise LLMError(
                f"no structured_output in response: {json.dumps(payload)[:300]}"
            )

    usage = payload.get("usage") or {}
    return RatioExtraction(
        winning_argument=(data.get("winning_argument") or "").strip(),
        losing_mistake=(data.get("losing_mistake") or "").strip(),
        dispositive_fact=(data.get("dispositive_fact") or "").strip(),
        transferable_lesson=(data.get("transferable_lesson") or "").strip(),
        case_archetype=(data.get("case_archetype") or "").strip()[:80],
        input_tokens=usage.get("input_tokens") or 0,
        output_tokens=usage.get("output_tokens") or 0,
        cost_usd=float(payload.get("total_cost_usd") or 0.0),
    )


def _candidate_case_ids(
    court_code: str | None,
    retry_failed: bool,
    limit: int | None,
) -> list[int]:
    """Cases ready for ratio extraction: extraction_status='complete' AND
    no CaseAnalysis row yet (idempotent resume)."""
    with session_scope() as sess:
        q = (
            select(Case.id)
            .outerjoin(CaseAnalysis, CaseAnalysis.case_id == Case.id)
            .where(Case.extraction_status == "complete")
            .where(Case.full_text.is_not(None))
        )
        if retry_failed:
            q = q.where(
                (CaseAnalysis.id.is_(None))
                | (CaseAnalysis.extraction_status == "failed")
            )
        else:
            q = q.where(CaseAnalysis.id.is_(None))
        if court_code:
            q = q.join(Court, Court.id == Case.court_id).where(Court.code == court_code)
        q = q.order_by(Case.id)
        if limit:
            q = q.limit(limit)
        return list(sess.scalars(q).all())


def _run_one(case_id: int) -> tuple[str, int, int, float]:
    """Process one case. Returns (status, in_tokens, out_tokens, cost_usd)."""
    with session_scope() as sess:
        case = sess.get(Case, case_id)
        if case is None:
            return "missing_case", 0, 0, 0.0
        if not case.full_text or len(case.full_text) < 300:
            return "skipped_short", 0, 0, 0.0

        # If a stale failed row exists, reuse it; else create fresh.
        analysis = sess.scalar(
            select(CaseAnalysis).where(CaseAnalysis.case_id == case_id)
        )
        if analysis is None:
            analysis = CaseAnalysis(case_id=case_id, extraction_status="pending")
            sess.add(analysis)
            sess.flush()

        court_code = case.court.code if case.court else ""
        hint = (
            f"Gjykata: {case.court.name if case.court else ''} "
            f"({court_code}). Numri i çështjes: {case.case_number}. "
            f"Tipi: {case.type}. Outcome: {case.outcome or 'i panjohur'}."
        )

        try:
            ratio = _call_claude(case.full_text, hint=hint)
        except Exception as exc:  # noqa: BLE001
            analysis.extraction_status = "failed"
            analysis.extraction_notes = f"llm failed: {exc}"[:500]
            analysis.extracted_at = datetime.now(UTC).replace(tzinfo=None)
            log.warning(
                "[%s] ratio extract failed case_id=%d: %s",
                court_code, case_id, exc,
            )
            return "failed_llm", 0, 0, 0.0

        analysis.winning_argument = ratio.winning_argument
        analysis.losing_mistake = ratio.losing_mistake
        analysis.dispositive_fact = ratio.dispositive_fact
        analysis.transferable_lesson = ratio.transferable_lesson
        analysis.case_archetype = ratio.case_archetype
        analysis.model = ratio.model
        analysis.input_tokens = ratio.input_tokens
        analysis.output_tokens = ratio.output_tokens
        analysis.cost_usd = Decimal(f"{ratio.cost_usd:.4f}")
        analysis.extraction_status = "complete"
        analysis.extraction_notes = None
        analysis.extracted_at = datetime.now(UTC).replace(tzinfo=None)
        return "complete", ratio.input_tokens, ratio.output_tokens, ratio.cost_usd


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        prog="src.extract.ratio",
        description="Extract ratio decidendi (winning argument / losing mistake / ...) into case_analyses.",
    )
    p.add_argument("--court", help="restrict to a single court code (e.g. gjykata_elarte, ecthr_albania)")
    p.add_argument("--limit", type=int, default=None, help="process at most N cases")
    p.add_argument("--retry-failed", action="store_true",
                   help="also re-process case_analyses with extraction_status='failed'")
    p.add_argument("-w", "--workers", type=int, default=3,
                   help="parallel CLI workers (default 3)")
    p.add_argument("--sleep", type=float, default=0.0,
                   help="seconds between calls in single-worker mode")
    p.add_argument("-v", "--verbose", action="store_true")
    args = p.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
    )
    for noisy in ("pdfminer", "pdfplumber", "httpx", "httpcore", "urllib3", "sqlalchemy"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    if not os.path.exists(CLAUDE_BIN):
        log.error("claude CLI not at %s — set CLAUDE_BIN env or install Claude Code", CLAUDE_BIN)
        return 1

    ids = _candidate_case_ids(args.court, args.retry_failed, args.limit)
    log.info("candidate cases for ratio extraction: %d", len(ids))
    if not ids:
        return 0

    counts = {"complete": 0, "failed_llm": 0, "skipped_short": 0, "missing_case": 0}
    tokens_in = tokens_out = 0
    total_cost = 0.0
    start = time.monotonic()

    try:
        if args.workers > 1:
            with ThreadPoolExecutor(max_workers=args.workers) as pool:
                futs = {pool.submit(_run_one, cid): cid for cid in ids}
                done = 0
                for fut in as_completed(futs):
                    status, ti, to, cost = fut.result()
                    counts[status] = counts.get(status, 0) + 1
                    tokens_in += ti
                    tokens_out += to
                    total_cost += cost
                    done += 1
                    if done % 5 == 0 or done == len(ids):
                        elapsed = time.monotonic() - start
                        log.info(
                            "progress %d/%d — complete=%d failed=%d skipped=%d "
                            "cost=$%.3f (%.1fs, $%.4f/case)",
                            done, len(ids), counts["complete"],
                            counts["failed_llm"], counts["skipped_short"],
                            total_cost, elapsed,
                            total_cost / max(counts["complete"], 1),
                        )
        else:
            for i, cid in enumerate(ids, 1):
                status, ti, to, cost = _run_one(cid)
                counts[status] = counts.get(status, 0) + 1
                tokens_in += ti
                tokens_out += to
                total_cost += cost
                if i % 5 == 0 or i == len(ids):
                    elapsed = time.monotonic() - start
                    log.info(
                        "progress %d/%d — complete=%d failed=%d cost=$%.3f (%.1fs)",
                        i, len(ids), counts["complete"], counts["failed_llm"],
                        total_cost, elapsed,
                    )
                if args.sleep:
                    time.sleep(args.sleep)
    except KeyboardInterrupt:
        log.warning("Ctrl-C — DB consistent (per-case commits)")

    log.info(
        "done — complete=%d failed=%d skipped=%d cost=$%.3f tokens=%d/%d",
        counts["complete"], counts["failed_llm"], counts["skipped_short"],
        total_cost, tokens_in, tokens_out,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
