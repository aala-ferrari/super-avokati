"""Base scraper for courts published on the unified gjykata.gov.al portal.

The portal follows a common layout for every court:

- each court has a path prefix (e.g. ``/apel-tirane``)
- decisions are listed under ``<prefix>/vendime/`` with query
  parameters ``viti=YYYY&faqja=N`` for year and page
- each row links to a detail page that may (or may not) include a PDF
- the CSS class names drift between courts, so the selectors below
  try a series of candidates rather than a single fixed one

Concrete scrapers set the five attributes marked with ``TODO`` below
and optionally override ``LISTING_SELECTORS``, ``DETAIL_FIELDS``, and
``PDF_SELECTORS`` if a court uses something unusual.
"""
from __future__ import annotations

import logging
import re
from datetime import date, datetime
from typing import Iterator, Sequence
from urllib.parse import urljoin

from selectolax.parser import HTMLParser

from src.scrapers.base import BaseScraper, ScrapedCase

log = logging.getLogger(__name__)


_MONTHS_SQ = {
    "janar": 1, "shkurt": 2, "mars": 3, "prill": 4, "maj": 5, "qershor": 6,
    "korrik": 7, "gusht": 8, "shtator": 9, "tetor": 10, "nëntor": 11,
    "nentor": 11, "dhjetor": 12,
}


def parse_sq_date(raw: str | None) -> date | None:
    """Parse a date in any of the formats Albanian court portals use."""
    if not raw:
        return None
    s = raw.strip().lower()
    for fmt in ("%d.%m.%Y", "%d/%m/%Y", "%Y-%m-%d", "%d-%m-%Y"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            pass
    m = re.match(r"(\d{1,2})\s+([a-zëç]+)\s+(\d{4})", s)
    if m:
        day, mon_name, yr = m.groups()
        mon = _MONTHS_SQ.get(mon_name)
        if mon:
            try:
                return date(int(yr), mon, int(day))
            except ValueError:
                return None
    return None


def normalize_case_type(raw: str | None) -> str:
    """Map whatever the portal calls it onto our fixed set of codes."""
    if not raw:
        return "other"
    s = raw.lower()
    if "penal" in s:
        return "penal"
    if "familj" in s:
        return "family"
    if "civil" in s:
        return "civil"
    if "administrativ" in s:
        return "administrative"
    if "tregtar" in s or "biznes" in s:
        return "commercial"
    if "pun" in s:  # "punë", "puna"
        return "labor"
    return "other"


class GjykataPortalScraper(BaseScraper):
    """Shared scraper for any court hosted on gjykata.gov.al.

    Subclasses only need to set ``COURT_CODE``, ``COURT_NAME``,
    ``COURT_LEVEL``, ``COURT_CITY``, and ``LISTING_PATH``. Everything
    else (listing, detail parsing, PDF download) is inherited.
    """

    BASE_URL = "https://www.gjykata.gov.al"

    # Subclasses override this to the court-specific path prefix, e.g.
    # "/apel-tirane/vendime/" or "/rrethi-gjyqesor-tirane/vendime/".
    LISTING_PATH: str = ""

    # CSS selectors applied in order — the first one that returns rows
    # wins. Let me know if a court uses a wildly different HTML and I'll
    # add a new selector rather than branching.
    LISTING_SELECTORS: Sequence[str] = (
        "a[href*='/vendim/']",
        "a.decision-link",
        "table a[href*='vendim']",
        "div.decisions a",
        "ul.listing a",
    )

    PDF_SELECTORS: Sequence[str] = (
        "a[href$='.pdf']",
        "a[href*='.pdf?']",
        "a[href*='/uploads/'][href*='pdf']",
    )

    # Each tuple is (field_name, list_of_css_selectors). First matching
    # selector wins. None values are silently dropped.
    DETAIL_FIELDS: Sequence[tuple[str, Sequence[str]]] = (
        (
            "case_number",
            (".case-number", "span.numri", "h1.title", "h2.title"),
        ),
        (
            "decision_date",
            (".decision-date", "span.data", "time[datetime]"),
        ),
        (
            "case_type",
            (".case-type", "span.fusha", ".field-type"),
        ),
        (
            "summary",
            (".summary", ".permbajtja", "div.summary", "p.abstract"),
        ),
    )

    JUDGE_SELECTORS: Sequence[str] = (
        ".judge", ".gjyqtar", "span.trupi-gjykues",
        "div.trupi-gjykues a", "li.judge",
    )
    PARTY_SELECTORS: Sequence[str] = (
        ".party", ".palet", "span.palet", "li.party", ".subject",
    )

    def __init__(
        self,
        raw_root,
        years: list[int] | None = None,
        **kwargs,
    ) -> None:
        super().__init__(raw_root, **kwargs)
        current_year = datetime.now().year
        self.years = years or list(range(2020, current_year + 1))

    # ── URL discovery ───────────────────────────────────────────────

    def _build_listing_url(self, year: int, page: int) -> str:
        path = self.LISTING_PATH
        if not path:
            raise ValueError(
                f"{type(self).__name__} must set LISTING_PATH"
            )
        if not path.startswith("/"):
            path = "/" + path
        sep = "&" if "?" in path else "?"
        return f"{self.BASE_URL}{path}{sep}viti={year}&faqja={page}"

    def _extract_listing_links(self, html: str) -> list[str]:
        tree = HTMLParser(html)
        for selector in self.LISTING_SELECTORS:
            nodes = tree.css(selector)
            hrefs = [
                n.attributes.get("href")
                for n in nodes
                if n.attributes.get("href")
            ]
            if hrefs:
                return hrefs
        return []

    def list_case_urls(self) -> Iterator[str]:
        seen: set[str] = set()
        for year in self.years:
            page = 1
            while True:
                url = self._build_listing_url(year, page)
                try:
                    html = self.fetch_html(url)
                except Exception as e:
                    log.info(
                        "[%s] listing unreachable year=%d page=%d — %s",
                        self.COURT_CODE, year, page, e,
                    )
                    break
                hrefs = self._extract_listing_links(html)
                if not hrefs:
                    log.info(
                        "[%s] end of listing year=%d page=%d",
                        self.COURT_CODE, year, page,
                    )
                    break
                before = len(seen)
                for href in hrefs:
                    full = urljoin(self.BASE_URL, href)
                    if full in seen:
                        continue
                    seen.add(full)
                    yield full
                if len(seen) == before:
                    break
                page += 1

    # ── Detail parsing ──────────────────────────────────────────────

    def parse_case(self, url: str) -> ScrapedCase | None:
        html = self.fetch_html(url)
        tree = HTMLParser(html)

        fields = {}
        for name, selectors in self.DETAIL_FIELDS:
            fields[name] = self._first_text(tree, selectors)

        # Fallback to regex if the structured selectors missed the
        # case number — almost every court puts it somewhere in the text.
        case_number = fields.get("case_number") or self._regex_first(
            html, r"[Nn]r\.?\s*[ç:]?\s*([\w\-\/\.]+)"
        )
        if not case_number:
            return None

        decision_date = parse_sq_date(fields.get("decision_date")) or \
            parse_sq_date(
                self._regex_first(
                    html,
                    r"[Dd]atë\s*[:\-]?\s*"
                    r"(\d{1,2}[.\-\/]\d{1,2}[.\-\/]\d{4})",
                )
            )
        case_type = normalize_case_type(fields.get("case_type"))

        # Try to find a PDF — optional
        pdf_url: str | None = None
        for selector in self.PDF_SELECTORS:
            pdf_node = tree.css_first(selector)
            if pdf_node and pdf_node.attributes.get("href"):
                pdf_url = urljoin(self.BASE_URL, pdf_node.attributes["href"])
                break

        pdf_path: str | None = None
        if pdf_url:
            year = decision_date.year if decision_date else None
            safe_number = case_number.replace("/", "_").replace(" ", "_")
            filename = f"{safe_number}.pdf"
            try:
                pdf_path = str(self.fetch_pdf(pdf_url, filename, year))
            except Exception as e:
                log.warning(
                    "[%s] pdf fetch failed %s: %s",
                    self.COURT_CODE, pdf_url, e,
                )

        judges = self._collect_texts(tree, self.JUDGE_SELECTORS)
        parties = self._collect_texts(tree, self.PARTY_SELECTORS)

        return ScrapedCase(
            source_url=url,
            court_code=self.COURT_CODE,
            court_name=self.COURT_NAME,
            court_level=self.COURT_LEVEL,
            court_city=self.COURT_CITY,
            case_number=case_number.strip(),
            decision_date=decision_date,
            type=case_type,
            raw_html=html,
            pdf_url=pdf_url,
            pdf_path=pdf_path,
            metadata={
                "judges": judges,
                "parties": parties,
                "summary": fields.get("summary"),
                "raw_type": fields.get("case_type"),
            },
        )

    # ── small utilities ─────────────────────────────────────────────

    @staticmethod
    def _first_text(tree: HTMLParser, selectors: Sequence[str]) -> str | None:
        for sel in selectors:
            node = tree.css_first(sel)
            if node:
                txt = node.text(strip=True)
                if txt:
                    return txt
        return None

    @staticmethod
    def _collect_texts(
        tree: HTMLParser, selectors: Sequence[str]
    ) -> list[str]:
        out: list[str] = []
        for sel in selectors:
            for n in tree.css(sel):
                txt = n.text(strip=True)
                if txt and txt not in out:
                    out.append(txt)
        return out

    @staticmethod
    def _regex_first(html: str, pattern: str) -> str | None:
        m = re.search(pattern, html)
        return m.group(1) if m else None
