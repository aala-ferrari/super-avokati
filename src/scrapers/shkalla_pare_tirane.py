"""Scraper for Gjykata e Shkallës së Parë e Juridiksionit të Përgjithshëm Tiranë.

First-instance court of Tiranë (the busiest in Albania by volume). Handles
penal, civil, family, labor, and commercial matters — everything except
administrative (which goes to the separate Gjykata Administrative).

The volume here is an order of magnitude larger than appellate courts,
so prefer narrow backfills (``years=[2024]``) for the first full run.
"""
from __future__ import annotations

from src.scrapers.gjykata_portal import GjykataPortalScraper


class ShkallaPareTiraneScraper(GjykataPortalScraper):
    COURT_CODE = "shkalla_pare_tirane"
    COURT_NAME = (
        "Gjykata e Shkallës së Parë e Juridiksionit të Përgjithshëm Tiranë"
    )
    COURT_LEVEL = "shkalla_pare"
    COURT_CITY = "Tiranë"
    LISTING_PATH = (
        "/gjykata-e-shkalles-se-pare-e-juridiksionit-te-pergjithshem-tirane/"
        "vendime/"
    )
