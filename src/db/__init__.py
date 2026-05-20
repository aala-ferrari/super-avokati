"""Legal knowledge base (Postgres) — schema, engine, session helpers."""
from src.db.engine import SessionLocal, engine, session_scope
from src.db.models import (
    Affiliation,
    ArticleCited,
    AssetDeclaration,
    Base,
    Case,
    CaseAnalysis,
    Court,
    CriminalProceeding,
    DisciplinaryAction,
    Participation,
    Person,
    ScrapeJob,
    VettingRecord,
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
    "CaseAnalysis",
    "Participation",
    "ArticleCited",
    "VettingRecord",
    "DisciplinaryAction",
    "AssetDeclaration",
    "CriminalProceeding",
    "ScrapeJob",
]
