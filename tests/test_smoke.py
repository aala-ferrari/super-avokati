"""Smoke tests — verify the core modules import and the Flask app boots.

These don't exercise behavior; they catch the class of bugs that V9.6's
`currentCaseId` regression represented: code that silently breaks at boot
or first import after a refactor, with no automated signal.

If any of these fail in CI, something fundamental is wrong before any
feature-level test would even start to run.
"""
from __future__ import annotations

import importlib


def test_storage_imports():
    mod = importlib.import_module("src.storage")
    assert hasattr(mod, "init_db")


def test_brain_imports():
    importlib.import_module("src.brain")


def test_backends_imports():
    mod = importlib.import_module("src.backends")
    assert hasattr(mod, "LLMBackend")


def test_web_module_imports():
    """The Flask app object must construct without side-effect crashes."""
    web = importlib.import_module("src.web")
    assert hasattr(web, "app")


def test_flask_app_has_routes():
    """At minimum the login route must register — guards against a regression
    where blueprint wiring breaks and the app boots empty."""
    from src import web

    rules = [r.rule for r in web.app.url_map.iter_rules()]
    assert "/login" in rules
    assert "/api/cases" in rules or any(r.startswith("/api/cases") for r in rules)


def test_pro_modules_import():
    """V9.3-V9.6 modules — if these break, the new Pro features die."""
    for name in ("corporate", "bench_memo", "vigilanza", "ratio_coach",
                 "genio", "precedent", "settlement"):
        importlib.import_module(f"src.{name}")
