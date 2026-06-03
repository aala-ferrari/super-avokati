"""Run LLM extraction over ``Case`` rows with ``extraction_status='pending'``.

Usage::

    ./venv/bin/python -m src.extract.run                   # all courts
    ./venv/bin/python -m src.extract.run --court gjykata_elarte --limit 10
    ./venv/bin/python -m src.extract.run --retry-failed    # re-process failed

For each pending case we:

1. Read the raw file (``Case.raw_path``) into plain text via readers.
2. Call the extraction model (Sonnet) with the tool → structured metadata.
3. Upsert ``Person`` rows (exact canonical_name match; fuzzy dedup is
   a separate later pass to keep this idempotent).
4. Insert ``Participation`` rows (judge, prosecution, defense, party).
5. Insert ``ArticleCited`` rows.
6. Update ``Case.outcome``, ``.summary``, ``.full_text``,
   ``.extracted_at``, ``.extraction_status='complete'``.

Crash-safe: each case is a separate transaction. Interrupting halfway
leaves some cases done, the rest still ``pending`` — re-run picks up
from there.
"""
from __future__ import annotations

import argparse
import logging
import sys
import time
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from src.db import (
    ArticleCited,
    Case,
    Court,
    Participation,
    Person,
    session_scope,
)
from src.extract.llm import Extraction, LLMClient
from src.extract.readers import read_text

log = logging.getLogger("extract")


# ──────────────────────────────────────────────────────────────────────
# Person upserts (exact match on canonical_name)
# ──────────────────────────────────────────────────────────────────────


def _upsert_person(
    sess: Session,
    name: str,
    role: str,
    cache: dict[str, Person],
) -> Person | None:
    """Case-insensitive upsert keyed on canonical_name.

    'Ilir Panda' and 'ILIR PANDA' resolve to the same Person row.
    The first spelling seen becomes canonical; all observed variants
    accumulate in ``aliases``. A later rapidfuzz pass will merge
    near-miss rows (typos, diacritic differences).
    """
    raw = (name or "").strip()
    if not raw:
        return None
    lower = raw.lower()
    if lower in cache:
        person = cache[lower]
    else:
        # LOWER() on canonical_name scans the whole table, but persons
        # stays under a few thousand rows for the forseeable future —
        # fine without a functional index.
        person = sess.scalar(
            select(Person).where(func.lower(Person.canonical_name) == lower)
        )
        if person is None:
            person = Person(canonical_name=raw, aliases=[raw], roles=[role])
            sess.add(person)
            sess.flush()
        cache[lower] = person
    # Record the observed spelling + role if new.
    aliases = list(person.aliases or [])
    if raw not in aliases:
        person.aliases = aliases + [raw]
    if role and role not in (person.roles or []):
        person.roles = list(person.roles or []) + [role]
    return person


# ──────────────────────────────────────────────────────────────────────
# Persisting one extraction
# ──────────────────────────────────────────────────────────────────────


def _apply_extraction(
    sess: Session,
    case: Case,
    extraction: Extraction,
    full_text: str,
) -> None:
    # Replace any existing participations / articles_cited: a re-run
    # should overwrite, not accumulate duplicates. The ORM cascade
    # ``delete-orphan`` on ``Case`` handles this when we clear the list.
    case.participations.clear()
    case.articles_cited.clear()
    sess.flush()

    name_cache: dict[str, Person] = {}

    for j in extraction.judges:
        person = _upsert_person(sess, j.get("name", ""), "judge", name_cache)
        if person is None:
            continue
        sess.add(Participation(
            case_id=case.id,
            person_id=person.id,
            role="judge",
            presiding=bool(j.get("presiding")),
        ))

    for name in extraction.prosecutors:
        person = _upsert_person(sess, name, "prosecutor", name_cache)
        if person is None:
            continue
        sess.add(Participation(
            case_id=case.id, person_id=person.id, role="prosecution",
        ))

    for lw in extraction.lawyers:
        person = _upsert_person(sess, lw.get("name", ""), "lawyer", name_cache)
        if person is None:
            continue
        sess.add(Participation(
            case_id=case.id, person_id=person.id, role="defense",
            representing=lw.get("representing"),
        ))

    for party in extraction.parties:
        person = _upsert_person(
            sess, party.get("name", ""), "party", name_cache
        )
        if person is None:
            continue
        raw_role = party.get("role") or "unknown"
        # Participation.role is a free string; we keep the LLM's label.
        sess.add(Participation(
            case_id=case.id, person_id=person.id, role=raw_role,
        ))

    for art in extraction.articles_cited:
        code = (art.get("code") or "").strip()
        article = (art.get("article") or "").strip()
        if not (code and article):
            continue
        raw_para = (art.get("paragraph") or "").strip()
        # LLM occasionally dumps a whole law citation here ("Ligji nr.9920
        # datë 19.05.2008"). The column is String(20); truncate defensively
        # and drop anything that clearly isn't a paragraph ref.
        paragraph = raw_para[:20] if raw_para else None
        sess.add(ArticleCited(
            case_id=case.id,
            code=code[:40],
            article=article[:30],
            paragraph=paragraph,
        ))

    case.outcome = extraction.outcome
    case.summary = extraction.summary_sq or case.summary
    case.full_text = full_text
    case.extracted_at = datetime.now(UTC).replace(tzinfo=None)
    case.extraction_status = "complete"
    case.extraction_notes = None


# ──────────────────────────────────────────────────────────────────────
# Orchestration
# ──────────────────────────────────────────────────────────────────────


def _pending_case_ids(
    court_code: str | None,
    retry_failed: bool,
    limit: int | None,
) -> list[int]:
    with session_scope() as sess:
        statuses = ["pending"]
        if retry_failed:
            statuses.append("failed")
        q = (
            select(Case.id)
            .where(Case.extraction_status.in_(statuses))
            .order_by(Case.id)
        )
        if court_code:
            q = q.join(Court).where(Court.code == court_code)
        if limit:
            q = q.limit(limit)
        return list(sess.scalars(q).all())


def _run_one(client: LLMClient, case_id: int) -> tuple[str, int, int, float]:
    """Return (status, in_tokens, out_tokens, cost_usd)."""
    with session_scope() as sess:
        case = sess.get(Case, case_id)
        if case is None or not case.raw_path:
            return "skipped_no_file", 0, 0, 0.0

        read = read_text(case.raw_path)
        if not read.ok or not read.text:
            case.extraction_status = "failed"
            case.extraction_notes = (
                f"reader failed ({read.source_format}): {read.error}"
                if read.error else "reader produced empty text"
            )
            return "failed_read", 0, 0, 0.0

        court_code = case.court.code if case.court else ""
        hint = (
            f"Court: {case.court.name if case.court else ''}. "
            f"Case number: {case.case_number}. "
            f"Type: {case.type}."
        )

        try:
            extraction = client.extract(read.text, hint_context=hint)
        except Exception as exc:
            case.extraction_status = "failed"
            case.extraction_notes = f"llm failed: {exc}"[:500]
            log.warning(
                "[%s] extract failed case_id=%d: %s",
                court_code, case_id, exc,
            )
            return "failed_llm", 0, 0, 0.0

        _apply_extraction(sess, case, extraction, read.text)
        return (
            "complete",
            extraction.input_tokens,
            extraction.output_tokens,
            extraction.cost_usd,
        )


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        prog="src.extract.run",
        description="Run LLM extraction over pending cases.",
    )
    p.add_argument("--court", help="restrict to a single court code")
    p.add_argument(
        "--limit", type=int, default=None,
        help="process at most N cases",
    )
    p.add_argument(
        "--retry-failed", action="store_true",
        help="also re-process cases with extraction_status='failed'",
    )
    p.add_argument(
        "--sleep", type=float, default=0.2,
        help="seconds to sleep between LLM calls (default 0.2, ignored when --workers>1)",
    )
    p.add_argument(
        "--workers", "-w", type=int, default=1,
        help="parallel LLM extractions (default 1). 4-6 gives the best "
             "throughput without hammering Claude's rate limits.",
    )
    p.add_argument(
        "-v", "--verbose", action="store_true",
    )
    args = p.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
    )
    # Third-party libraries are DEBUG-spammy; keep them quiet even
    # when the user asked for our own verbose logging.
    for noisy in ("pdfminer", "pdfplumber", "httpx", "httpcore", "urllib3"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    ids = _pending_case_ids(args.court, args.retry_failed, args.limit)
    log.info("pending cases: %d", len(ids))
    if not ids:
        return 0

    client = LLMClient()
    counts = {"complete": 0, "failed_read": 0, "failed_llm": 0, "skipped_no_file": 0}
    tokens_in = tokens_out = 0
    total_cost = 0.0

    start = time.monotonic()
    try:
        if args.workers > 1:
            from concurrent.futures import ThreadPoolExecutor, as_completed
            with ThreadPoolExecutor(max_workers=args.workers) as pool:
                futs = {pool.submit(_run_one, client, cid): cid for cid in ids}
                done = 0
                for fut in as_completed(futs):
                    status, ti, to, cost = fut.result()
                    counts[status] = counts.get(status, 0) + 1
                    tokens_in += ti
                    tokens_out += to
                    total_cost += cost
                    done += 1
                    if done % 10 == 0 or done == len(ids):
                        elapsed = time.monotonic() - start
                        log.info(
                            "progress %d/%d — complete=%d failed_read=%d "
                            "failed_llm=%d cost=$%.3f (%.1fs)",
                            done, len(ids), counts["complete"],
                            counts["failed_read"], counts["failed_llm"],
                            total_cost, elapsed,
                        )
        else:
            for i, cid in enumerate(ids, 1):
                status, ti, to, cost = _run_one(client, cid)
                counts[status] = counts.get(status, 0) + 1
                tokens_in += ti
                tokens_out += to
                total_cost += cost
                if i % 10 == 0 or i == len(ids):
                    elapsed = time.monotonic() - start
                    log.info(
                        "progress %d/%d — complete=%d failed_read=%d "
                        "failed_llm=%d cost=$%.3f (%.1fs)",
                        i, len(ids), counts["complete"],
                        counts["failed_read"], counts["failed_llm"],
                        total_cost, elapsed,
                    )
                if args.sleep:
                    time.sleep(args.sleep)
    except KeyboardInterrupt:
        log.warning("Ctrl-C — stopping, DB is consistent (per-case commits)")

    log.info(
        "done — complete=%d failed_read=%d failed_llm=%d skipped=%d "
        "cost=$%.3f tokens=%d in + %d out",
        counts["complete"], counts["failed_read"], counts["failed_llm"],
        counts["skipped_no_file"], total_cost, tokens_in, tokens_out,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
