"""Scraper for Gjykata e Apelit e Juridiksionit të Përgjithshëm Durrës.

The Durrës seat of the appellate court handles cases from Durrës, Krujë
(partially), Laç, Lezhë and related rrethe. Second-instance review of
first-instance decisions from the Durrës region's lower courts.
"""
from __future__ import annotations

from src.scrapers.gjykata_portal import GjykataPortalScraper


class ApelDurresScraper(GjykataPortalScraper):
    COURT_CODE = "apel_durres"
    COURT_NAME = (
        "Gjykata e Apelit e Juridiksionit të Përgjithshëm Durrës"
    )
    COURT_LEVEL = "apel"
    COURT_CITY = "Durrës"
    LISTING_PATH = (
        "/gjykata-e-apelit-te-juridiksionit-te-pergjithshem-durres/vendime/"
    )
