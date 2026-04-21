"""Scraper for Gjykata e Shkallës së Parë e Juridiksionit të Përgjithshëm Durrës.

First-instance court for the Durrës jurisdiction. Handles the full
spectrum of non-administrative cases originating in the Durrës region.
"""
from __future__ import annotations

from src.scrapers.gjykata_portal import GjykataPortalScraper


class ShkallaPareDurresScraper(GjykataPortalScraper):
    COURT_CODE = "shkalla_pare_durres"
    COURT_NAME = (
        "Gjykata e Shkallës së Parë e Juridiksionit të Përgjithshëm Durrës"
    )
    COURT_LEVEL = "shkalla_pare"
    COURT_CITY = "Durrës"
    LISTING_PATH = (
        "/gjykata-e-shkalles-se-pare-e-juridiksionit-te-pergjithshem-durres/"
        "vendime/"
    )
