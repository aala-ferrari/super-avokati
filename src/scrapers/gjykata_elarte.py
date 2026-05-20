"""Scraper for Gjykata e Lartë (Supreme Court of Albania).

The site is a Gatsby static build backed by an S3 origin behind
CloudFront. Every page has a sibling ``/page-data/<path>/page-data.json``
endpoint that returns the *raw* CMS payload — no HTML parsing needed.

The six sections we care about:

- juridiksione-administrative        (administrative jurisdiction)
- juridiksione-civile                (civil jurisdiction)
- ankime-te-vecanta-penale           (special criminal appeals)
- ankime-te-vecanta-administrative   (special administrative appeals)
- ankime-te-vecanta-civile           (special civil appeals)
- vendime-kolegjet-e-bashkuara       (united chambers — binding precedent)

Each section returns a block of ``vendim`` records, each shaped as::

    {
      "id": "503",
      "title": {"text_sq": "Vendim Nr.00-2020-1, datë 04.05.2020", ...},
      "file":  {"url": "https://.../<hash>.pdf", "ext": ".pdf",
                 "mime": "...", "size": 303.11, "created_at": "..."}
    }

We use the ``title.text_sq`` to recover case number + decision date, and
the ``file.url`` as the raw artefact (PDF or DOC).
"""
from __future__ import annotations

import json
import logging
import re
from collections.abc import Iterator, Sequence
from datetime import date, datetime
from urllib.parse import urlparse

from src.scrapers.base import BaseScraper, ScrapedCase

log = logging.getLogger(__name__)


# Section slug → (normalized case type, human label for metadata).
# "united_chambers" is not one of our standard case types; we keep it in
# metadata so downstream filters can spot precedent-setting decisions.
SECTIONS: dict[str, tuple[str, str]] = {
    "juridiksione-administrative":      ("administrative", "juridiksione_administrative"),
    "juridiksione-civile":              ("civil",          "juridiksione_civile"),
    "ankime-te-vecanta-penale":         ("penal",          "ankime_te_vecanta_penale"),
    "ankime-te-vecanta-administrative": ("administrative", "ankime_te_vecanta_administrative"),
    "ankime-te-vecanta-civile":         ("civil",          "ankime_te_vecanta_civile"),
    "vendime-kolegjet-e-bashkuara":     ("other",          "kolegjet_e_bashkuara"),
}


# Examples the regex must cover:
#   "Vendim Nr.00-2020-1, datë 04.05.2020"
#   "Vendim nr.00-2020-199 datë 03.06.2020"
#   "Vendim nr.2, datë 18.11.2022"
_TITLE_RE = re.compile(
    r"[Vv]endim\s+[Nn]r\.?\s*(?P<num>\S+?)[,\s]+dat[ëe]\s*(?P<date>[\d./\-]+)",
)


def _parse_title(title_sq: str) -> tuple[str | None, date | None]:
    """Extract (case_number, decision_date) from an Albanian title string."""
    if not title_sq:
        return None, None
    m = _TITLE_RE.search(title_sq)
    if not m:
        return None, None
    num = m.group("num").rstrip(",.")
    raw_date = m.group("date").replace("/", ".").replace("-", ".")
    parsed: date | None = None
    for fmt in ("%d.%m.%Y", "%Y.%m.%d"):
        try:
            parsed = datetime.strptime(raw_date, fmt).date()
            break
        except ValueError:
            continue
    return num, parsed


class GjykataELarteScraper(BaseScraper):
    """Supreme Court (Gjykata e Lartë) — pulls the Gatsby page-data JSON.

    No HTML parsing; no pagination. The CMS dumps the entire section as
    one JSON blob, so we iterate all six sections in order.
    """

    COURT_CODE = "gjykata_elarte"
    COURT_NAME = "Gjykata e Lartë"
    COURT_LEVEL = "larte"
    COURT_CITY = "Tiranë"
    BASE_URL = "https://gjykataelarte.gov.al"

    # httpx default UA looks fine to CloudFront; keep the identifying UA
    # from BaseScraper so the operator (us) is visible in logs.

    def __init__(
        self,
        raw_root,
        years: list[int] | None = None,
        sections: Sequence[str] | None = None,
        **kwargs,
    ) -> None:
        super().__init__(raw_root, **kwargs)
        # ``years`` is accepted for runner symmetry but unused: the API
        # returns the full archive in one go, so we filter post-hoc.
        self.years = years
        unknown = [s for s in (sections or []) if s not in SECTIONS]
        if unknown:
            raise ValueError(
                f"unknown sections: {unknown}. Valid: {sorted(SECTIONS)}"
            )
        self.sections = list(sections) if sections else list(SECTIONS)

    # ── URL helpers ─────────────────────────────────────────────────

    def _page_data_url(self, section: str) -> str:
        return f"{self.BASE_URL}/page-data/sq/{section}/page-data.json"

    def _case_source_url(self, section: str, vendim_id: str) -> str:
        # The site has no per-decision detail page; we synthesise a
        # stable URL that points back to the section + the CMS record id.
        return f"{self.BASE_URL}/sq/{section}#vendim-{vendim_id}"

    # ── Discovery ───────────────────────────────────────────────────

    def _fetch_section(self, section: str) -> list[dict]:
        url = self._page_data_url(section)
        raw = self.fetch_html(url)  # the method just downloads text + caches
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as e:
            log.error("[%s] malformed JSON at %s: %s", self.COURT_CODE, url, e)
            return []
        try:
            body = payload["result"]["data"]["api"]["article"]["body"] or []
        except (KeyError, TypeError):
            log.warning("[%s] unexpected JSON shape at %s", self.COURT_CODE, url)
            return []
        out: list[dict] = []
        for block in body:
            for v in block.get("vendim") or []:
                out.append(v)
        log.info(
            "[%s] section '%s': %d vendime",
            self.COURT_CODE, section, len(out),
        )
        return out

    # ``list_case_urls`` is required by BaseScraper. We expose the
    # synthesised per-vendim URL and stash the section + file url so
    # ``parse_case`` can reconstruct everything without refetching.
    def list_case_urls(self) -> Iterator[str]:
        self._records: dict[str, tuple[str, dict]] = {}
        for section in self.sections:
            for v in self._fetch_section(section):
                src = self._case_source_url(section, v["id"])
                self._records[src] = (section, v)
                yield src

    # ── Parsing ─────────────────────────────────────────────────────

    def parse_case(self, url: str) -> ScrapedCase | None:
        record = getattr(self, "_records", {}).get(url)
        if record is None:
            return None
        section, v = record
        case_type, section_label = SECTIONS[section]

        title_sq = (v.get("title") or {}).get("text_sq") or ""
        case_number, decision_date = _parse_title(title_sq)
        if not case_number:
            # Fall back to CMS id so we don't silently drop the row. It
            # still goes into `Case`, but with a synthetic number so a
            # human can spot it and fix the regex later.
            case_number = f"cms-{v.get('id')}"

        # Year filter (the API returns the whole archive in one call).
        if self.years and decision_date and decision_date.year not in self.years:
            return None

        file_info = v.get("file") or {}
        file_url = file_info.get("url")

        pdf_path: str | None = None
        if file_url:
            year = decision_date.year if decision_date else None
            safe_num = case_number.replace("/", "_").replace(" ", "_")
            ext = urlparse(file_url).path.rsplit(".", 1)[-1].lower()
            filename = f"{safe_num}.{ext}" if ext and len(ext) <= 5 else f"{safe_num}.pdf"
            try:
                pdf_path = str(
                    self.fetch_file(file_url, filename, year)
                )
            except Exception as e:
                log.warning(
                    "[%s] file fetch failed %s: %s",
                    self.COURT_CODE, file_url, e,
                )

        return ScrapedCase(
            source_url=url,
            court_code=self.COURT_CODE,
            court_name=self.COURT_NAME,
            court_level=self.COURT_LEVEL,
            court_city=self.COURT_CITY,
            case_number=case_number,
            decision_date=decision_date,
            type=case_type,
            raw_html=None,
            pdf_url=file_url,
            pdf_path=pdf_path,
            metadata={
                "section": section_label,
                "title_sq": title_sq,
                "title_en": (v.get("title") or {}).get("text_en"),
                "cms_id": v.get("id"),
                "file_ext": file_info.get("ext"),
                "file_mime": file_info.get("mime"),
                "file_created_at": file_info.get("created_at"),
                "is_binding_precedent": section == "vendime-kolegjet-e-bashkuara",
                "judges": [],   # only in the PDF body; LLM pass fills these
                "parties": [],
            },
        )
