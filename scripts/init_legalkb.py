"""Initialize the Postgres legal knowledge base.

One-time setup: creates every table declared in src.db.models on the
database pointed to by LEGALKB_URL. Safe to re-run — ``create_all`` is
idempotent.

Also enables the ``vector`` extension (pgvector) when available, so the
forthcoming embedding columns can be added later without a migration.

Usage:
    ./venv/bin/python -m scripts.init_legalkb

Requires either:
    - ``docker compose up -d postgres``     (pgvector/pgvector:pg16), or
    - a local Postgres running on :5432 with the ``super_avvocato`` role
      and ``legalkb`` database already created.
"""
from __future__ import annotations

import logging
import sys

from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, OperationalError

from src.db.engine import engine
from src.db.models import Base

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
)
log = logging.getLogger("init_legalkb")


def main() -> int:
    eng = engine()
    url_safe = eng.url.render_as_string(hide_password=True)
    log.info("target: %s", url_safe)

    # Probe connectivity first — distinguishes "can't reach Postgres" from
    # "Postgres is up but pgvector isn't installed".
    try:
        with eng.connect() as conn:
            conn.execute(text("SELECT 1"))
    except OperationalError as e:
        log.error("cannot connect to Postgres: %s", e.orig)
        log.error(
            "start it first with:\n"
            "    docker compose up -d postgres\n"
            "or, on this laptop, with Homebrew:\n"
            "    /usr/local/opt/postgresql@14/bin/pg_ctl -D "
            "/usr/local/var/postgresql@14 -l /tmp/pg14.log start"
        )
        return 2

    try:
        with eng.begin() as conn:
            conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        log.info("pgvector extension enabled")
    except DBAPIError as e:
        # pgvector not bundled with this Postgres install — fine for
        # structural tables; semantic-search columns come later.
        log.warning(
            "pgvector not installed (OK for now) — %s",
            str(e.orig).splitlines()[0] if e.orig else e,
        )

    Base.metadata.create_all(eng)
    with eng.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT tablename FROM pg_tables "
                "WHERE schemaname='public' ORDER BY tablename"
            )
        ).fetchall()
    log.info(
        "schema ready — %d tables: %s",
        len(rows),
        ", ".join(r[0] for r in rows),
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
