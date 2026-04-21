"""HUDOC — European Court of Human Rights cases against Albania.

Why this matters: ECHR judgments against Albania are authoritative
reviews of Albanian state conduct (fair trial, property, liberty,
discrimination). Knowing which Albanian practices Strasbourg has
struck down gives a defence lawyer precedent the domestic courts
are bound to respect.

API shape (reverse-engineered — HUDOC exposes it even though it's
not publicly documented):

- Listing: ``/app/query/results?query=((respondent:"ALB")) AND
  (languageisocode:"ENG")&select=<comma list>&sort=judgementdate:desc
  &start=<N>&length=<N>`` returns JSON with ``resultcount`` + ``results``.
- Full text: ``/app/conversion/docx/html/body?library=ECHR&id=<itemid>``
  returns rendered HTML of the judgment body.

We only pull the English corpus — many decisions are bilingual
(ENG/FRE) and the application number (``appno``) is the same across
languages, which would cause duplicate-insert churn. If a case is
French-only, we miss it for now; acceptable trade-off at v1.
"""
from __future__ import annotations

import json
import logging
import re
from datetime import date
from typing import Iterator
from urllib.parse import urlencode

from src.scrapers.base import BaseScraper, ScrapedCase

log = logging.getLogger(__name__)


# ECLI:CE:ECHR:YYYY:MMDDTYPEAPPLICATION…
# Example: ECLI:CE:ECHR:2024:0507JUD002422818 → 2024-05-07
_ECLI_DATE_RE = re.compile(
    r"ECLI:CE:ECHR:(?P<year>\d{4}):(?P<mm>\d{2})(?P<dd>\d{2})"
)

# Fields we ask the API to return. Keeping this explicit means a HUDOC
# backend change surfaces as a missing field at parse time, not as
# silently dropped metadata.
_SELECT_FIELDS = ",".join([
    "itemid",
    "docname",
    "languageisocode",
    "kpthesaurus",
    "article",
    "appno",
    "ecli",
    "originatingbody",
    "respondent",
    "documentcollectionid2",
    "judgementdate",
    "importance",
])

# "DECISIONS" = admissibility decisions; "JUDGMENTS" = merits judgments.
# We keep both: for an Albanian lawyer, even inadmissible-found-manifestly
# cases are useful precedent on Strasbourg's threshold.
_QUERY = '((respondent:"ALB")) AND (languageisocode:"ENG")'


def _ecli_to_date(ecli: str | None) -> date | None:
    if not ecli:
        return None
    m = _ECLI_DATE_RE.match(ecli)
    if not m:
        return None
    try:
        return date(
            int(m.group("year")),
            int(m.group("mm")),
            int(m.group("dd")),
        )
    except ValueError:
        return None


def _classify(doc_collection: str | None) -> tuple[str, str]:
    """Return (type, subtype) from HUDOC's documentcollectionid2 string.

    Examples:
      "CASELAW;JUDGMENTS;GRANDCHAMBER;ENG" → ("cedu", "grand_chamber_judgment")
      "CASELAW;DECISIONS;ADMISSIBILITYCOM;ENG" → ("cedu", "admissibility")
      "CASELAW;COMMUNICATEDCASES;ENG" → ("cedu", "communicated")
    """
    s = (doc_collection or "").upper()
    if "GRANDCHAMBER" in s:
        return "cedu", "grand_chamber"
    if "JUDGMENTS" in s:
        return "cedu", "judgment"
    if "ADMISSIBILITY" in s or "DECISIONS" in s:
        return "cedu", "admissibility_decision"
    if "COMMUNICATEDCASES" in s:
        return "cedu", "communicated"
    return "cedu", "other"


class HudocEchrScraper(BaseScraper):
    """Strasbourg judgments with Albania as respondent state."""

    COURT_CODE = "ecthr_albania"
    COURT_NAME = "European Court of Human Rights (Albania cases)"
    COURT_LEVEL = "cedu"
    COURT_CITY = "Strasbourg"
    BASE_URL = "https://hudoc.echr.coe.int"

    # Page size for the listing call. HUDOC accepts up to 500; we stay
    # conservative to avoid timeouts.
    PAGE_SIZE = 200

    def __init__(
        self,
        raw_root,
        years: list[int] | None = None,
        **kwargs,
    ) -> None:
        super().__init__(raw_root, **kwargs)
        self.years = years  # client-side filter after fetch

    # ── Discovery ──────────────────────────────────────────────────

    def _query_url(self, start: int, length: int) -> str:
        params = {
            "query": _QUERY,
            "select": _SELECT_FIELDS,
            "sort": "judgementdate:desc",
            "start": str(start),
            "length": str(length),
        }
        return f"{self.BASE_URL}/app/query/results?{urlencode(params)}"

    def _body_url(self, itemid: str) -> str:
        return (
            f"{self.BASE_URL}/app/conversion/docx/html/body"
            f"?library=ECHR&id={itemid}"
        )

    def _source_url(self, itemid: str) -> str:
        # Canonical human-readable URL on the HUDOC SPA.
        return f"{self.BASE_URL}/eng?i={itemid}"

    def _fetch_page(self, start: int) -> list[dict]:
        url = self._query_url(start, self.PAGE_SIZE)
        raw = self.fetch_html(url)
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as e:
            log.error("[%s] malformed JSON at start=%d: %s",
                      self.COURT_CODE, start, e)
            return []
        return [r.get("columns") or {} for r in payload.get("results") or []]

    def list_case_urls(self) -> Iterator[str]:
        self._records: dict[str, dict] = {}
        seen_appno: set[str] = set()
        start = 0
        while True:
            batch = self._fetch_page(start)
            if not batch:
                break
            for cols in batch:
                itemid = cols.get("itemid")
                appno = cols.get("appno") or itemid
                if not itemid:
                    continue
                # Dedup across admissibility / judgment for the same
                # application: keep the first we see (API is sorted
                # judgementdate:desc, so typically the final judgment).
                if appno in seen_appno:
                    continue
                seen_appno.add(appno)
                src = self._source_url(itemid)
                self._records[src] = cols
                yield src
            if len(batch) < self.PAGE_SIZE:
                break
            start += self.PAGE_SIZE

    # ── Parsing ────────────────────────────────────────────────────

    def parse_case(self, url: str) -> ScrapedCase | None:
        cols = getattr(self, "_records", {}).get(url)
        if cols is None:
            return None

        itemid = cols.get("itemid")
        appno = cols.get("appno") or itemid
        decision_date = _ecli_to_date(cols.get("ecli"))
        case_type, subtype = _classify(cols.get("documentcollectionid2"))

        if self.years and decision_date and decision_date.year not in self.years:
            return None

        # Pull the full judgment HTML so we have it on disk for later
        # LLM extraction (judges, facts, holding). Treat fetch failure
        # as non-fatal — the summary metadata is still worth keeping.
        body_url = self._body_url(itemid)
        body_path: str | None = None
        try:
            body_html = self.fetch_html(body_url)
            year = decision_date.year if decision_date else None
            safe_id = itemid.replace("/", "_")
            year_dir = self.raw_root / (str(year) if year else "unknown")
            year_dir.mkdir(parents=True, exist_ok=True)
            target = year_dir / f"{safe_id}.html"
            if not target.exists():
                target.write_text(body_html, encoding="utf-8")
            body_path = str(target)
        except Exception as e:
            log.warning(
                "[%s] body fetch failed %s: %s",
                self.COURT_CODE, body_url, e,
            )

        return ScrapedCase(
            source_url=url,
            court_code=self.COURT_CODE,
            court_name=self.COURT_NAME,
            court_level=self.COURT_LEVEL,
            court_city=self.COURT_CITY,
            case_number=appno,
            decision_date=decision_date,
            type=case_type,
            raw_html=None,
            pdf_url=body_url,
            pdf_path=body_path,
            metadata={
                "subtype": subtype,
                "docname": cols.get("docname"),
                "itemid": itemid,
                "ecli": cols.get("ecli"),
                "articles_violated": (cols.get("article") or "").split(";") if cols.get("article") else [],
                "kpthesaurus": (cols.get("kpthesaurus") or "").split(";") if cols.get("kpthesaurus") else [],
                "originating_body": cols.get("originatingbody"),
                "importance": cols.get("importance"),
                "language": cols.get("languageisocode"),
                "documentcollectionid2": cols.get("documentcollectionid2"),
                "judges": [],  # extracted later from body_path
                "parties": [cols.get("docname")] if cols.get("docname") else [],
            },
        )
