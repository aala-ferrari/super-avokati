"""Scrapers for Albanian court decisions and judicial-integrity records.

Each concrete scraper inherits from :class:`src.scrapers.base.BaseScraper`
and yields :class:`src.scrapers.base.ScrapedCase` objects. The scraper
itself is stateless — persisting to Postgres is the caller's job, so the
same scraper can be used for a full backfill or an incremental run.
"""
