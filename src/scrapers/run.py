"""CLI runner that executes a scraper and persists results to Postgres.

Usage:

    ./venv/bin/python -m src.scrapers.run <court_code> [--year YYYY]...
                                          [--limit N] [--throttle-s 1.5]
                                          [--no-pdf]

Examples:

    python -m src.scrapers.run apel_tirane --year 2024 --limit 20
    python -m src.scrapers.run shkalla_pare_durres --year 2023 --year 2024

Behaviour:

- Upserts the ``Court`` row (keyed by ``code``).
- Opens a ``ScrapeJob`` row in ``running`` status.
- For each scraped case:
    * skip if ``(court_id, case_number)`` already exists
    * otherwise insert a ``Case`` row with ``extraction_status='pending'``
    * upsert each judge / party name into ``persons`` and add a
      ``participations`` row. Name matching here is exact-string only;
      deduplication/fuzzy matching is a separate pass.
- Closes the ``ScrapeJob`` with counts + status.

Crash-safe: a Ctrl-C or exception mid-run marks the job as
``interrupted`` and records ``last_url`` so a re-run can resume.
"""
from __future__ import annotations

import argparse
import logging
import signal
import sys
from collections.abc import Iterable
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.config import RAW_DATA_PATH
from src.db import (
    Case,
    Court,
    Participation,
    Person,
    ScrapeJob,
    session_scope,
)
from src.scrapers.base import BaseScraper, ScrapedCase
from src.scrapers.registry import get_scraper_class, list_court_codes

log = logging.getLogger("scrape")


# ──────────────────────────────────────────────────────────────────────
# Upserts
# ──────────────────────────────────────────────────────────────────────


def upsert_court(sess: Session, scraper: BaseScraper) -> Court:
    court = sess.scalar(
        select(Court).where(Court.code == scraper.COURT_CODE)
    )
    if court is None:
        court = Court(
            code=scraper.COURT_CODE,
            name=scraper.COURT_NAME,
            level=scraper.COURT_LEVEL,
            city=scraper.COURT_CITY,
            source_url=scraper.BASE_URL,
        )
        sess.add(court)
        sess.flush()
        log.info("registered court: %s (id=%d)", court.name, court.id)
    return court


def upsert_person(
    sess: Session,
    name: str,
    role: str,
    name_cache: dict[str, Person],
) -> Person:
    """Exact-string match for now. Fuzzy dedup is a later pass."""
    key = name.strip()
    if key in name_cache:
        return name_cache[key]
    person = sess.scalar(
        select(Person).where(Person.canonical_name == key)
    )
    if person is None:
        person = Person(canonical_name=key, aliases=[key], roles=[role])
        sess.add(person)
        sess.flush()
    elif role and role not in (person.roles or []):
        person.roles = list(person.roles or []) + [role]
    name_cache[key] = person
    return person


# ──────────────────────────────────────────────────────────────────────
# Persistence of a single scraped case
# ──────────────────────────────────────────────────────────────────────


def persist_case(
    sess: Session,
    court: Court,
    scraped: ScrapedCase,
    name_cache: dict[str, Person],
) -> tuple[Case | None, bool]:
    """Return (case, created). ``created=False`` means it already existed."""
    existing = sess.scalar(
        select(Case).where(
            Case.court_id == court.id,
            Case.case_number == scraped.case_number,
        )
    )
    if existing is not None:
        return existing, False

    case = Case(
        court_id=court.id,
        case_number=scraped.case_number,
        decision_date=scraped.decision_date,
        type=scraped.type,
        summary=scraped.metadata.get("summary"),
        raw_path=scraped.pdf_path,
        source_url=scraped.source_url,
        extraction_status="pending",
    )
    sess.add(case)
    sess.flush()

    for judge_name in scraped.metadata.get("judges") or []:
        if not judge_name:
            continue
        person = upsert_person(sess, judge_name, "judge", name_cache)
        sess.add(
            Participation(
                case_id=case.id,
                person_id=person.id,
                role="judge",
            )
        )

    # Parties are left to the LLM-extraction stage: the HTML rarely
    # labels them clearly as "plaintiff" vs "defendant", so we'd just
    # be persisting noise. Scraper-level judges are usually reliable.
    return case, True


# ──────────────────────────────────────────────────────────────────────
# Job orchestration
# ──────────────────────────────────────────────────────────────────────


class ScrapeRun:
    def __init__(self, scraper: BaseScraper, limit: int | None) -> None:
        self.scraper = scraper
        self.limit = limit
        self.interrupted = False

    def _install_sigint(self) -> None:
        def handler(signum, frame):
            log.warning("Ctrl-C received — finishing current case then exiting")
            self.interrupted = True

        signal.signal(signal.SIGINT, handler)

    def execute(self) -> dict:
        self._install_sigint()

        with session_scope() as sess:
            court = upsert_court(sess, self.scraper)
            court_id = court.id
            job = ScrapeJob(scraper=self.scraper.COURT_CODE, status="running")
            sess.add(job)
            sess.flush()
            job_id = job.id

        counts = {"found": 0, "new": 0, "skipped": 0, "failed": 0}
        last_url: str | None = None

        try:
            for scraped in self._iter_cases():
                counts["found"] += 1
                last_url = scraped.source_url
                try:
                    with session_scope() as sess:
                        court = sess.get(Court, court_id)
                        name_cache: dict[str, Person] = {}
                        _, created = persist_case(
                            sess, court, scraped, name_cache
                        )
                        if created:
                            counts["new"] += 1
                        else:
                            counts["skipped"] += 1
                except Exception as exc:
                    counts["failed"] += 1
                    log.warning(
                        "persist failed for %s: %s",
                        scraped.source_url, exc,
                    )
                if self.interrupted:
                    break
                if self.limit and counts["new"] + counts["skipped"] >= self.limit:
                    break
        finally:
            self._close_job(job_id, counts, last_url)

        return {**counts, "court_code": self.scraper.COURT_CODE}

    def _iter_cases(self) -> Iterable[ScrapedCase]:
        # BaseScraper.run already applies its own limit; we pass None
        # and stop ourselves once we've persisted the requested count.
        return self.scraper.run(limit=None)

    def _close_job(
        self, job_id: int, counts: dict, last_url: str | None
    ) -> None:
        status = (
            "interrupted" if self.interrupted
            else ("failed" if counts["failed"] == counts["found"] > 0
                  else "completed")
        )
        with session_scope() as sess:
            job = sess.get(ScrapeJob, job_id)
            if job is None:
                return
            job.finished_at = datetime.now(UTC).replace(tzinfo=None)
            job.status = status
            job.cases_found = counts["found"]
            job.cases_new = counts["new"]
            job.cases_skipped = counts["skipped"]
            job.last_url = last_url


# ──────────────────────────────────────────────────────────────────────
# Entrypoint
# ──────────────────────────────────────────────────────────────────────


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        prog="src.scrapers.run",
        description=(
            "Scrape a court portal and persist results to Postgres. "
            "Available court codes: " + ", ".join(list_court_codes())
        ),
    )
    p.add_argument("court_code", help="e.g. apel_tirane, shkalla_pare_durres")
    p.add_argument(
        "--year", "-y", action="append", type=int,
        help="year to scrape (repeatable). Default: 2020..current.",
    )
    p.add_argument(
        "--limit", "-l", type=int, default=None,
        help="stop after N cases persisted (default: no limit)",
    )
    p.add_argument(
        "--throttle-s", type=float, default=1.5,
        help="seconds between HTTP requests (default: 1.5)",
    )
    p.add_argument(
        "-v", "--verbose", action="store_true",
        help="enable DEBUG logging",
    )
    args = p.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
    )

    try:
        cls = get_scraper_class(args.court_code)
    except KeyError as e:
        log.error(str(e))
        return 2

    with cls(
        raw_root=RAW_DATA_PATH,
        years=args.year,
        throttle_s=args.throttle_s,
    ) as scraper:
        log.info(
            "scraping %s (years=%s, limit=%s)",
            scraper.COURT_NAME,
            args.year or "default 2020..",
            args.limit or "none",
        )
        summary = ScrapeRun(scraper, limit=args.limit).execute()

    log.info(
        "done — found=%d new=%d skipped=%d failed=%d",
        summary["found"], summary["new"], summary["skipped"], summary["failed"],
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
