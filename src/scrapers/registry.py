"""Registry of available scrapers.

Adding a new source = one import + one line in ``SCRAPERS``.
The runner (``src/scrapers/run.py``) and any UI surface that lets a
user pick a source both read from this registry.

Note on disabled scrapers: the gjykata.gov.al per-court scrapers
(apel_tirane, apel_durres, shkalla_pare_tirane, shkalla_pare_durres)
are implemented but NOT registered — inspection with an Albanian IP
confirmed that gjykata.gov.al does not publish decision archives
publicly. They remain as stubs so when we get eAlbania login or a
Ligji 119/2014 data export, we can switch them back on by adding the
import + registry line below.
"""
from __future__ import annotations

from src.scrapers.base import BaseScraper
from src.scrapers.gjykata_elarte import GjykataELarteScraper
from src.scrapers.hudoc_echr import HudocEchrScraper

SCRAPERS: dict[str, type[BaseScraper]] = {
    GjykataELarteScraper.COURT_CODE: GjykataELarteScraper,
    HudocEchrScraper.COURT_CODE: HudocEchrScraper,
}


def get_scraper_class(court_code: str) -> type[BaseScraper]:
    try:
        return SCRAPERS[court_code]
    except KeyError:
        available = ", ".join(sorted(SCRAPERS))
        raise KeyError(
            f"unknown court_code '{court_code}'. Available: {available}"
        ) from None


def list_court_codes() -> list[str]:
    return sorted(SCRAPERS)
