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

# WhatsApp Business Cloud API (Meta) — reminders channel. Dormant until
# all three are set + a message template is approved in Meta Business.
WHATSAPP_TOKEN = os.getenv("WHATSAPP_TOKEN", "")
WHATSAPP_PHONE_NUMBER_ID = os.getenv("WHATSAPP_PHONE_NUMBER_ID", "")
WHATSAPP_TEMPLATE_NAME = os.getenv("WHATSAPP_TEMPLATE_NAME", "")
WHATSAPP_TEMPLATE_LANG = os.getenv("WHATSAPP_TEMPLATE_LANG", "sq")

# Email reminders via Resend (fallback channel). Each studio receives on
# its own registered address. Dormant until BOTH are set + a sending
# domain is verified in Resend (test mode delivers only to the account owner).
RESEND_API_KEY = os.getenv("RESEND_API_KEY", "")
REMINDER_EMAIL_FROM = os.getenv("REMINDER_EMAIL_FROM", "")

# "auto" picks Gemini if its key is set (free tier), otherwise Anthropic.
# Force a specific provider with BRAIN_BACKEND=anthropic or BRAIN_BACKEND=gemini.
BRAIN_BACKEND = os.getenv("BRAIN_BACKEND", "auto")

CLAUDE_MODEL = os.getenv("CLAUDE_MODEL", "claude-opus-4-8")
# V9.x tier (Haiku rimosso): in uno strumento legale non vogliamo
# modelli "piccoli". Solo Opus (risposta legale) + Sonnet (tutto il
# resto: medium E fast — intake, Q&A udienza, jargon→qytetar, wizard,
# scaffolding/parse JSON/BM25 lookup).
CLAUDE_MEDIUM_MODEL = os.getenv("CLAUDE_MEDIUM_MODEL", "claude-sonnet-4-6")
CLAUDE_FAST_MODEL = os.getenv("CLAUDE_FAST_MODEL", "claude-sonnet-4-6")
# Extended thinking budget (tokens) for the main model on hard legal
# reasoning — pavlefshmëria, parashkrimi, konflikte ndërmjet neneve.
# Applies only to the final answer stage; triage/strategic stay fast.
# Default is generous: a lawyer defending a client needs the model to
# think deeply before answering. Set to 0 to disable.
CLAUDE_THINKING_BUDGET = int(os.getenv("CLAUDE_THINKING_BUDGET", "16000"))
# Claude Code CLI accepts full model IDs or aliases.
# We pin the full ID so we're GUARANTEED to run the smartest model
# available — Opus 4.8 (current flagship). Aliases like
# "opus" auto-resolve to the latest, but pinning makes the choice
# explicit and survives CLI alias remapping. This assistant gives
# legal advice to people who cannot afford a lawyer: accuracy and
# strategic depth beat latency every time.
CLAUDE_CODE_MODEL = os.getenv("CLAUDE_CODE_MODEL", "claude-opus-4-8")
CLAUDE_CODE_MEDIUM_MODEL = os.getenv("CLAUDE_CODE_MEDIUM_MODEL", "claude-sonnet-4-6")
CLAUDE_CODE_FAST_MODEL = os.getenv("CLAUDE_CODE_FAST_MODEL", "claude-sonnet-4-6")
# Effort level for the main answer stage: low / medium / high / xhigh /
# max. Default "max" — we want the lawyer's edge, not a quick reply.
# Ignored on fast-model calls (triage/strategic stay fast).
CLAUDE_CODE_EFFORT = os.getenv("CLAUDE_CODE_EFFORT", "max")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-pro")
GEMINI_FAST_MODEL = os.getenv("GEMINI_FAST_MODEL", "gemini-2.5-flash")

RAW_DATA_PATH = Path(os.getenv("RAW_DATA_PATH", ROOT / "data" / "raw"))
PROCESSED_DATA_PATH = Path(os.getenv("PROCESSED_DATA_PATH", ROOT / "data" / "processed"))
INDEX_PATH = Path(os.getenv("INDEX_PATH", ROOT / "data" / "index"))
LOG_PATH = Path(os.getenv("LOG_PATH", ROOT / "logs" / "super_avvocato.log"))
# SQLite database for users + cases + messages.
APP_DB_PATH = Path(os.getenv("APP_DB_PATH", ROOT / "data" / "app.db"))
# Postgres legal knowledge base: court decisions, judges, prosecutors,
# lawyers, vetting records, disciplinary actions, asset declarations.
# Separate from APP_DB_PATH: this is the shared, growing corpus that
# every user's brain queries; the SQLite app.db holds only per-user
# operational data (accounts, cases, messages, uploaded documents).
LEGALKB_URL = os.getenv(
    "LEGALKB_URL",
    "postgresql+psycopg://super_avvocato:super_avvocato_dev@localhost:5432/legalkb",
)
# User-uploaded case documents (PDF/JPG/PNG/SVG) live here, one folder per
# case. Files never leave the server — the lawyer and the brain are the
# only consumers.
UPLOAD_PATH = Path(os.getenv("UPLOAD_PATH", ROOT / "data" / "uploads"))
# Court decisions live under RAW_DATA_PATH/jurisprudence/{court_code}/{year}/
JURISPRUDENCE_PATH = RAW_DATA_PATH / "jurisprudence"

# ── Dossier (lawyer's case file) ─────────────────────────────────────────
# Hard limits protect both disk and LLM context.
MAX_UPLOAD_SIZE_MB = int(os.getenv("MAX_UPLOAD_SIZE_MB", "25"))
MAX_DOCUMENTS_PER_CASE = int(os.getenv("MAX_DOCUMENTS_PER_CASE", "20"))
# Characters from each document fed into the brain prompt. The brain merges
# extracted_text + AI summary; if a document is longer than this we use the
# summary in full + a head-and-tail slice of the raw text.
DOC_CONTEXT_CHAR_BUDGET = int(os.getenv("DOC_CONTEXT_CHAR_BUDGET", "6000"))
ALLOWED_UPLOAD_EXTENSIONS = frozenset({".pdf", ".jpg", ".jpeg", ".png", ".svg",
                                       ".webp", ".tif", ".tiff"})

TOP_K_ARTICLES = int(os.getenv("TOP_K_ARTICLES", "12"))
# How many precedent decisions to retrieve alongside articles (added to the
# ANSWER prompt as persuasive weight). Keep small — each one costs tokens.
TOP_K_DECISIONS = int(os.getenv("TOP_K_DECISIONS", "4"))
MAX_CONVERSATION_TURNS = int(os.getenv("MAX_CONVERSATION_TURNS", "20"))

# Albanian post-processing (V7.0): the editor pass rewrites the final
# answer in shqipe standarde juridike via a fast-model call, then a
# deterministic invariant check falls back to the original if the
# editor mutated any protected token (case links, article numbers,
# currency, dates). Disabling this skips the LLM rewrite but keeps
# the deterministic word/phrase corrections (those are always on).
# V7.8 — disabled by default. The editor pass over Opus's output was
# adding ~10s wall-clock for a median +1-char diff (observed in prod logs),
# i.e. almost always a no-op, and when it DID rewrite it risked introducing
# its own Albanian errors (the small editor model is weaker than Opus on
# shqipe standarde).
# Opus writes clean legal Albanian on its own; keep the deterministic
# `_apply_corrections` pass which is cheap and safe. Set to 1 to re-enable.
ALBANIAN_EDITOR_ENABLED = os.getenv("ALBANIAN_EDITOR_ENABLED", "0") == "1"

# V7.2: run the nine analytical stages (strategic, timeline, comparison,
# missing_facts, premortem, distinguishing, evidence_map, nullity_radar,
# contradictions) concurrently instead of sequentially. They are
# independent (none feed into each other) so the latency drops roughly
# from N×fast_call to max(fast_call)+overhead. Urgency radar and action
# plan still run sequentially after because they consume the outputs.
BRAIN_PARALLEL_STAGES = os.getenv("BRAIN_PARALLEL_STAGES", "1") == "1"
BRAIN_PARALLEL_WORKERS = int(os.getenv("BRAIN_PARALLEL_WORKERS", "3"))

# V7.5 — fast path for short follow-ups in an active Claude Code session.
# When the session already has the context (≥2 prior turns) and the message
# is below this threshold with no new dossier, skip triage + retrieval +
# the 11 analytical stages and resume straight to compose. Set to 0 to
# disable the fast path entirely.
FOLLOWUP_FASTPATH_MAX_CHARS = int(os.getenv("FOLLOWUP_FASTPATH_MAX_CHARS", "200"))

# V7.6 — simple-query fast path. Triage classifies each question as
# "simple" (informative, no adversary, no deadline) or "complex"
# (litigation, strategy, dossier). On "simple" we skip the 11 analytical
# stages + precedent retrieval + urgency radar + action plan, and go
# straight to compose on Opus. Mirrors how a real lawyer handles easy
# questions on the spot. Set to 0 to force the full pipeline on every
# fresh query (e.g. for debugging).
SIMPLE_FASTPATH_ENABLED = os.getenv("SIMPLE_FASTPATH_ENABLED", "1") == "1"

for path in (RAW_DATA_PATH, PROCESSED_DATA_PATH, INDEX_PATH, LOG_PATH.parent,
             JURISPRUDENCE_PATH, UPLOAD_PATH):
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

    # V7.4 — volatility tagging so the compose layer can warn when citing
    # fast-moving statutes (tax, customs, data protection secondary acts).
    # STABLE    = codes and foundational statutes, safe to cite verbatim
    # MEDIUM    = amended every few years (consumer, bankruptcy, business reg)
    # VOLATILE  = rewritten often (tax, customs tariffs, VAT thresholds)
    volatility: str = "STABLE"
    last_amendment_date: str = ""  # ISO date of the most recent amendment we indexed


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
    # ── V7.4 — sectoral commercial / consumer / data statutes ────────────
    LegalDocument(
        code="ligji_shoqerite_tregtare",
        title_sq="Ligji nr. 9901/2008 «Për tregtarët dhe shoqëritë tregtare»",
        title_en="Law on Traders and Commercial Companies (SHPK/SHA)",
        area="Tregtare",
        # portavendore.al version — PDF bundles the law + implementing acts;
        # parser truncates on numbering restart to keep only the main statute.
        url="https://portavendore.al/wp-content/uploads/2018/05/Ligji-nr.9901-dat%C3%AB-14.4.2008-%E2%80%9CP%C3%ABr-tregtar%C3%ABt-dhe-shoq%C3%ABrit%C3%AB-tregtare%E2%80%9D-dhe-aktet-e-dala-n%C3%AB-zbatim-t%C3%AB-tij.pdf",
        local_pdf="ligji_shoqerite_tregtare.pdf",
        volatility="STABLE",
        last_amendment_date="2018-05-01",
    ),
    LegalDocument(
        code="ligji_falimentimi",
        title_sq="Ligji nr. 110/2016 «Për falimentimin»",
        title_en="Bankruptcy Law",
        area="Tregtare",
        url="https://portavendore.al/wp-content/uploads/2018/05/Ligji-nr.1102016-P%C3%ABr-falimentimin-dhe-aktet-n%C3%ABnligjore-t%C3%AB-dala-n%C3%AB-zbatim-tij.pdf",
        local_pdf="ligji_falimentimi.pdf",
        volatility="MEDIUM",
        last_amendment_date="2018-05-01",
    ),
    LegalDocument(
        code="ligji_konsumatoret",
        title_sq="Ligji nr. 9902/2008 «Për mbrojtjen e konsumatorëve»",
        title_en="Consumer Protection Law",
        area="Konsumator",
        url="https://erru.al/doc/Ligji_9902_per_mbrojten_e_konsumatoreve_2018_vf.pdf",
        local_pdf="ligji_konsumatoret.pdf",
        volatility="STABLE",
        last_amendment_date="2018-10-18",
    ),
    LegalDocument(
        code="ligji_te_dhenat",
        title_sq="Ligji nr. 9887/2008 «Për mbrojtjen e të dhënave personale»",
        title_en="Personal Data Protection Law",
        area="Data",
        url="https://idp.al/wp-content/uploads/2024/02/Ligj-2008-03-10-9887-perditesuar-nga-QBZ-1.pdf",
        local_pdf="ligji_te_dhenat.pdf",
        volatility="STABLE",
        last_amendment_date="2024-02-01",
    ),
    LegalDocument(
        code="ligji_qkb",
        title_sq="Ligji nr. 131/2015 «Për Qendrën Kombëtare të Biznesit»",
        title_en="National Business Center (QKB) Law",
        area="Tregtare",
        url="https://bashkiaskrapar.gov.al/wp-content/uploads/2019/12/ligj-2015-11-26-131.pdf",
        local_pdf="ligji_qkb.pdf",
        volatility="STABLE",
        last_amendment_date="2015-11-26",
    ),
    LegalDocument(
        code="ligji_policia",
        title_sq="Ligji nr. 108/2014 «Për Policinë e Shtetit»",
        title_en="State Police Law",
        area="Administrativ",
        url="https://asp.gov.al/wp-content/uploads/2025/08/Ligji-Nr.108.2014-Per-Policine-e-Shtetit.pdf",
        local_pdf="ligji_policia.pdf",
        volatility="MEDIUM",
        last_amendment_date="2017-06-01",
    ),
    LegalDocument(
        code="rregullore_policia",
        title_sq="Rregullore e Policisë së Shtetit (VKM nr. 750/2015)",
        title_en="State Police Regulation",
        area="Administrativ",
        url="https://www.asp.gov.al/wp-content/uploads/2022/12/Rregullore_PSH.pdf",
        local_pdf="rregullore_policia.pdf",
        volatility="MEDIUM",
        last_amendment_date="2015-09-16",
    ),
    LegalDocument(
        code="ligji_policia_2024",
        title_sq="Ligji nr. 82/2024 «Për Policinë e Shtetit» (aktual)",
        title_en="State Police Law 2024",
        area="Administrativ",
        url="https://akademiaesigurise.asp.gov.al/wp-content/uploads/2024/08/Ligji-nr.-82-dt.-26.7.2024.pdf",
        local_pdf="ligji_policia_2024.pdf",
        volatility="MEDIUM",
        last_amendment_date="2024-07-26",
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
