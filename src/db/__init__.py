"""Legal knowledge base (Postgres) — schema, engine, session helpers."""
from src.db.engine import engine, session_scope, SessionLocal
from src.db.models import (
    Base,
    Court,
    Person,
    Affiliation,
    Case,
    Participation,
    ArticleCited,
    VettingRecord,
    DisciplinaryAction,
    AssetDeclaration,
    CriminalProceeding,
    ScrapeJob,
)

__all__ = [
    "engine",
    "session_scope",
    "SessionLocal",
    "Base",
    "Court",
    "Person",
    "Affiliation",
    "Case",
    "Participation",
    "ArticleCited",
    "VettingRecord",
    "DisciplinaryAction",
    "AssetDeclaration",
    "CriminalProceeding",
    "ScrapeJob",
]
