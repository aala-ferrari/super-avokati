"""Base scraper — polite HTTP, retries, caching, PDF download.

Subclasses implement just two hooks:

- :meth:`list_case_urls`   yield URLs of individual case detail pages
- :meth:`parse_case`       parse one case detail page into a ScrapedCase

The base class provides:

- Per-request rate limiting (default 1.5 s between hits)
- Exponential-backoff retries on transient HTTP errors
- On-disk HTML cache keyed by URL hash (so re-runs skip the network)
- PDF download to ``data/raw/jurisprudence/<court_slug>/<year>/<file>``
"""
from __future__ import annotations

import hashlib
import logging
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Iterator

import httpx
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential_jitter,
)

log = logging.getLogger(__name__)


@dataclass
class ScrapedCase:
    """Raw data pulled from a single court-decision page.

    This is intentionally flat and free of DB concerns. A downstream
    step turns this into ``Case`` + ``Participation`` + ``ArticleCited``
    rows after LLM extraction fills in the structured fields.
    """

    source_url: str
    court_code: str
    court_name: str
    court_level: str
    court_city: str | None
    case_number: str
    decision_date: date | None
    type: str  # penal | civil | administrative | ...
    raw_html: str | None = None
    pdf_url: str | None = None
    pdf_path: str | None = None
    # Anything the scraper can read off the listing/detail page without
    # needing a PDF parse: judges, parties, short summary, etc.
    metadata: dict = field(default_factory=dict)


class BaseScraper(ABC):
    """Subclass this to add a new court or intelligence source.

    Required class attributes:

    - ``COURT_CODE``   machine slug, used as directory name under
                       ``data/raw/jurisprudence/`` and as key in the DB
    - ``COURT_NAME``   Albanian display name
    - ``COURT_LEVEL``  one of kushtetuese | larte | apel | shkalla_pare |
                       administrative | ushtarake
    - ``BASE_URL``     root of the court's public portal
    """

    COURT_CODE: str = ""
    COURT_NAME: str = ""
    COURT_LEVEL: str = ""
    COURT_CITY: str | None = None
    BASE_URL: str = ""

    USER_AGENT = (
        "SuperAvvocato/1.0 (+humanitarian legal aid; romeoredi@libero.it)"
    )

    def __init__(
        self,
        raw_root: Path,
        throttle_s: float = 1.5,
        timeout_s: float = 30,
    ) -> None:
        if not (self.COURT_CODE and self.COURT_NAME and self.BASE_URL):
            raise ValueError(
                f"{type(self).__name__} must set COURT_CODE, COURT_NAME, BASE_URL"
            )
        self.raw_root = Path(raw_root) / "jurisprudence" / self.COURT_CODE
        self.raw_root.mkdir(parents=True, exist_ok=True)
        self.throttle_s = throttle_s
        self.client = httpx.Client(
            headers={"User-Agent": self.USER_AGENT},
            timeout=timeout_s,
            follow_redirects=True,
        )
        self._last_fetch_at: float = 0.0

    # ── context manager sugar ────────────────────────────────────────

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()

    def close(self) -> None:
        self.client.close()

    # ── HTTP plumbing ────────────────────────────────────────────────

    def _respect_rate(self) -> None:
        delta = time.monotonic() - self._last_fetch_at
        if delta < self.throttle_s:
            time.sleep(self.throttle_s - delta)
        self._last_fetch_at = time.monotonic()

    @retry(
        reraise=True,
        stop=stop_after_attempt(4),
        wait=wait_exponential_jitter(initial=2, max=30),
        retry=retry_if_exception_type(
            (httpx.HTTPError, httpx.ReadTimeout, httpx.ConnectError)
        ),
    )
    def _fetch(self, url: str) -> httpx.Response:
        self._respect_rate()
        resp = self.client.get(url)
        resp.raise_for_status()
        return resp

    def fetch_html(self, url: str, use_cache: bool = True) -> str:
        """Download a page; cache locally by URL hash."""
        cache_dir = self.raw_root / "_cache"
        key = hashlib.sha1(url.encode("utf-8")).hexdigest()[:16]
        cache_path = cache_dir / f"{key}.html"
        if use_cache and cache_path.exists():
            return cache_path.read_text(encoding="utf-8")
        resp = self._fetch(url)
        cache_dir.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(resp.text, encoding="utf-8")
        return resp.text

    def fetch_pdf(
        self,
        url: str,
        filename: str,
        year: int | None = None,
    ) -> Path:
        """Download a PDF to the raw tree; skip if already there."""
        return self.fetch_file(url, filename, year, default_ext=".pdf")

    def fetch_file(
        self,
        url: str,
        filename: str,
        year: int | None = None,
        default_ext: str = ".pdf",
    ) -> Path:
        """Download any binary (pdf/doc/docx) to the raw tree; skip if present.

        Gjykata e Lartë publishes many decisions as .doc — we take whatever
        extension the URL carries and fall back to ``default_ext``.
        """
        year_dir = self.raw_root / (str(year) if year else "unknown")
        year_dir.mkdir(parents=True, exist_ok=True)
        url_tail = url.split("?")[0].split("/")[-1]
        url_ext = "." + url_tail.rsplit(".", 1)[-1].lower() if "." in url_tail else ""
        if url_ext in {".pdf", ".doc", ".docx", ".rtf"}:
            ext = url_ext
        else:
            ext = default_ext
        safe_name = filename.split("?")[0].split("/")[-1] or "case"
        if not safe_name.lower().endswith(ext):
            safe_name = safe_name.rsplit(".", 1)[0] + ext
        target = year_dir / safe_name
        if target.exists() and target.stat().st_size > 0:
            return target
        resp = self._fetch(url)
        target.write_bytes(resp.content)
        return target

    # ── hooks subclasses must implement ──────────────────────────────

    @abstractmethod
    def list_case_urls(self) -> Iterator[str]:
        """Yield URLs of individual case detail pages."""

    @abstractmethod
    def parse_case(self, url: str) -> ScrapedCase | None:
        """Parse one case detail page. Return None to skip silently."""

    # ── orchestration ────────────────────────────────────────────────

    def run(self, limit: int | None = None) -> Iterator[ScrapedCase]:
        """Walk every URL; yield cases. Caller persists them."""
        count = 0
        for url in self.list_case_urls():
            if limit is not None and count >= limit:
                break
            try:
                case = self.parse_case(url)
            except Exception as exc:  # scraping is inherently flaky
                log.warning("parse failed: %s — %s", url, exc)
                continue
            if case is None:
                continue
            count += 1
            yield case
