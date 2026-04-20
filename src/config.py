"""Central configuration for Super Avvocato.

Loads environment variables and declares the 14 Albanian legal documents
(the 13 codes plus the Constitution) that power the RAG index.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

ROOT = Path(__file__).resolve().parent.parent

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "") or os.getenv("GOOGLE_API_KEY", "")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")

# "auto" picks Gemini if its key is set (free tier), otherwise Anthropic.
# Force a specific provider with BRAIN_BACKEND=anthropic or BRAIN_BACKEND=gemini.
BRAIN_BACKEND = os.getenv("BRAIN_BACKEND", "auto")

CLAUDE_MODEL = os.getenv("CLAUDE_MODEL", "claude-opus-4-7")
CLAUDE_FAST_MODEL = os.getenv("CLAUDE_FAST_MODEL", "claude-haiku-4-5-20251001")
# Claude Code CLI uses aliases ("opus", "sonnet", "haiku") or full names.
# Aliases auto-resolve to the latest model under your subscription.
# Default is sonnet: citizens waiting for a legal answer need <40s replies,
# and Sonnet 4.6 is plenty strong for Albanian legal reasoning.
# Switch to "opus" via env for hardest cases at the cost of 2-3x latency.
CLAUDE_CODE_MODEL = os.getenv("CLAUDE_CODE_MODEL", "sonnet")
CLAUDE_CODE_FAST_MODEL = os.getenv("CLAUDE_CODE_FAST_MODEL", "haiku")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-pro")
GEMINI_FAST_MODEL = os.getenv("GEMINI_FAST_MODEL", "gemini-2.5-flash")

RAW_DATA_PATH = Path(os.getenv("RAW_DATA_PATH", ROOT / "data" / "raw"))
PROCESSED_DATA_PATH = Path(os.getenv("PROCESSED_DATA_PATH", ROOT / "data" / "processed"))
INDEX_PATH = Path(os.getenv("INDEX_PATH", ROOT / "data" / "index"))
LOG_PATH = Path(os.getenv("LOG_PATH", ROOT / "logs" / "super_avvocato.log"))
# SQLite database for users + cases + messages.
APP_DB_PATH = Path(os.getenv("APP_DB_PATH", ROOT / "data" / "app.db"))
# Court decisions live under RAW_DATA_PATH/jurisprudence/{court_code}/{year}/
JURISPRUDENCE_PATH = RAW_DATA_PATH / "jurisprudence"

TOP_K_ARTICLES = int(os.getenv("TOP_K_ARTICLES", "12"))
# How many precedent decisions to retrieve alongside articles (added to the
# ANSWER prompt as persuasive weight). Keep small — each one costs tokens.
TOP_K_DECISIONS = int(os.getenv("TOP_K_DECISIONS", "4"))
MAX_CONVERSATION_TURNS = int(os.getenv("MAX_CONVERSATION_TURNS", "20"))

for path in (RAW_DATA_PATH, PROCESSED_DATA_PATH, INDEX_PATH, LOG_PATH.parent,
             JURISPRUDENCE_PATH):
    path.mkdir(parents=True, exist_ok=True)


@dataclass(frozen=True)
class LegalDocument:
    """A single Albanian legal document tracked by the pipeline."""

    code: str           # short machine id, e.g. "kodi_civil"
    title_sq: str       # Albanian title shown to users
    title_en: str       # English title for logs
    area: str           # broad legal area for classification
    url: str = ""       # official source URL (filled by downloader)
    local_pdf: str = "" # path on disk relative to RAW_DATA_PATH


LEGAL_DOCUMENTS: tuple[LegalDocument, ...] = (
    LegalDocument(
        code="kushtetuta",
        title_sq="Kushtetuta e Republikës së Shqipërisë",
        title_en="Constitution of Albania",
        area="Kushtetues",
        url="https://www.qsut.gov.al/wp-content/uploads/2020/02/Kushtetuta-e-Republikes-se-Shqiperise.pdf",
        local_pdf="kushtetuta.pdf",
    ),
    LegalDocument(
        code="kodi_civil",
        title_sq="Kodi Civil i Republikës së Shqipërisë",
        title_en="Civil Code",
        area="Civil",
        url="https://www.drejtesia.gov.al/wp-content/uploads/2019/02/kodi-civil-2016.pdf",
        local_pdf="kodi_civil.pdf",
    ),
    LegalDocument(
        code="kodi_proc_civile",
        title_sq="Kodi i Procedurës Civile i Republikës së Shqipërisë",
        title_en="Civil Procedure Code",
        area="Civil",
        url="https://www.drejtesia.gov.al/wp-content/uploads/2017/11/Kodi_i_Procedures_Civile-2014-perf-1.pdf",
        local_pdf="kodi_proc_civile.pdf",
    ),
    LegalDocument(
        code="kodi_penal",
        title_sq="Kodi Penal i Republikës së Shqipërisë",
        title_en="Criminal Code",
        area="Penal",
        url="https://fiu.gov.al/wp-content/uploads/2024/02/Kodi-Penal-RSH.pdf",
        local_pdf="kodi_penal.pdf",
    ),
    LegalDocument(
        code="kodi_proc_penale",
        title_sq="Kodi i Procedurës Penale i Republikës së Shqipërisë",
        title_en="Criminal Procedure Code",
        area="Penal",
        url="https://dpp.gov.al/wp-content/uploads/2025/05/Kodi_i_Procedures_Penale.pdf",
        local_pdf="kodi_proc_penale.pdf",
    ),
    LegalDocument(
        code="kodi_punes",
        title_sq="Kodi i Punës i Republikës së Shqipërisë",
        title_en="Labor Code",
        area="Punë",
        url="https://inspektoriatipunes.gov.al/wp-content/uploads/2024/08/Kodi-i-punes-perditesuar-2024.pdf",
        local_pdf="kodi_punes.pdf",
    ),
    LegalDocument(
        code="kodi_familjes",
        title_sq="Kodi i Familjes i Republikës së Shqipërisë",
        title_en="Family Code",
        area="Familje",
        url="https://www.drejtesia.gov.al/wp-content/uploads/2019/02/Kodi-i-familjes-Ligj_9062_08.05.2003-1.pdf",
        local_pdf="kodi_familjes.pdf",
    ),
    LegalDocument(
        code="kodi_proc_admin",
        title_sq="Kodi i Procedurave Administrative i Republikës së Shqipërisë",
        title_en="Administrative Procedure Code",
        area="Administrativ",
        url="https://www.drejtesia.gov.al/wp-content/uploads/2019/02/Kodi_i_Procedurave_Administrative_2015.pdf",
        local_pdf="kodi_proc_admin.pdf",
    ),
    LegalDocument(
        code="kodi_doganor",
        title_sq="Kodi Doganor i Republikës së Shqipërisë",
        title_en="Customs Code",
        area="Doganor",
        url="https://www.dogana.gov.al/dokument/1179/ligj-nr-102-2014-date-3172014-i-ndryshuar",
        local_pdf="kodi_doganor.pdf",
    ),
    LegalDocument(
        code="kodi_rrugor",
        title_sq="Kodi Rrugor i Republikës së Shqipërisë",
        title_en="Road Code",
        area="Rrugor",
        url="https://qeverisjavendore.gov.al/wp-content/uploads/2024/08/Ligj-nr.-8378-date-22.7.1998-Kodi-rrugor-i-Republikes-se-Shqiperise.pdf",
        local_pdf="kodi_rrugor.pdf",
    ),
    LegalDocument(
        code="kodi_zgjedhor",
        title_sq="Kodi Zgjedhor i Republikës së Shqipërisë",
        title_en="Electoral Code",
        area="Zgjedhor",
        url="https://www.osce.org/files/f/documents/5/7/477547.pdf",
        local_pdf="kodi_zgjedhor.pdf",
    ),
    LegalDocument(
        code="kodi_detar",
        title_sq="Kodi Detar i Republikës së Shqipërisë",
        title_en="Maritime Code",
        area="Detar",
        url="https://qkb.gov.al/wp-content/uploads/2025/04/ligji-nr-9251-date-872004-kodi-detar-i-republikes-se-shqiperise.pdf",
        local_pdf="kodi_detar.pdf",
    ),
    LegalDocument(
        code="kodi_ajror",
        title_sq="Kodi Ajror i Republikës së Shqipërisë",
        title_en="Air Code",
        area="Ajror",
        url="https://www.infrastruktura.gov.al/wp-content/uploads/2020/10/Kodi-Ajror_ligj-2020-07-23-96.pdf",
        local_pdf="kodi_ajror.pdf",
    ),
)


def doc_by_code(code: str) -> LegalDocument | None:
    for d in LEGAL_DOCUMENTS:
        if d.code == code:
            return d
    return None


# ── Jurisprudence (court decisions) ───────────────────────────────────────
# Public records — names of judges/prosecutors/lawyers are public. Personal
# data of private parties is typically anonymized at source by the court;
# we preserve that anonymization and do not try to re-identify anyone.

@dataclass(frozen=True)
class Court:
    """A court whose decisions we mirror locally for precedent retrieval."""

    code: str                   # machine id, e.g. "kushtetuese"
    title_sq: str               # Albanian name shown in citations
    short_sq: str               # shortened form used inline ("GJK", "Gjykata e Lartë")
    # URL pattern where `{year}` is the decision year. If the pattern returns
    # an HTML listing page with links to individual decision files, the
    # downloader will scrape those links. Leave empty if a court needs a
    # custom scraper.
    year_index_url: str
    # Years actually available on the court's site.
    years: tuple[int, ...]


# Constitutional Court decisions are the most valuable precedents because
# they decide fundamental-rights cases (labour, property, penal procedure,
# family, etc.) and bind every lower court. We start with 2015–2024 where
# files are PDFs (older years use legacy .doc binaries we'd need pandoc for).
COURTS: tuple[Court, ...] = (
    Court(
        code="kushtetuese",
        title_sq="Gjykata Kushtetuese e Republikës së Shqipërisë",
        short_sq="Gjykata Kushtetuese",
        year_index_url="https://www.gjykatakushtetuese.gov.al/vendime-perfundimtare-{year}/",
        years=tuple(range(2015, 2025)),  # 2015…2024 (PDFs)
    ),
)


def court_by_code(code: str) -> Court | None:
    for c in COURTS:
        if c.code == code:
            return c
    return None
