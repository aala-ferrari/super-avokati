"""Scraper for Gjykata e Apelit e Juridiksionit të Përgjithshëm Tiranë.

Post-2022 judicial reform unified most second-instance courts into
"Gjykata e Apelit e Juridiksionit të Përgjithshëm" divided by seat.
The Tiranë seat handles cases from Tiranë, Krujë, Kurbin, Kavajë and
several other rrethe.

Portal path below is a best guess — if the scraper returns zero URLs
on listing, adjust ``LISTING_PATH`` to match the current portal layout.
Every request is cached on disk, so re-running after a selector tweak
is free.
"""
from __future__ import annotations

from src.scrapers.gjykata_portal import GjykataPortalScraper


class ApelTiraneScraper(GjykataPortalScraper):
    COURT_CODE = "apel_tirane"
    COURT_NAME = (
        "Gjykata e Apelit e Juridiksionit të Përgjithshëm Tiranë"
    )
    COURT_LEVEL = "apel"
    COURT_CITY = "Tiranë"
    LISTING_PATH = (
        "/gjykata-e-apelit-te-juridiksionit-te-pergjithshem-tirane/vendime/"
    )
