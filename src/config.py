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

# Segue il modello che gira DAVVERO (backend CLI). Erano due costanti
# scollegate, e la vecchia finiva nel provenance pack: dichiarava
# opus-4-8 mentre rispondeva opus-5. Un certificato che dice il modello
# sbagliato e' peggio di uno che non lo dice.
CLAUDE_MODEL = os.getenv("CLAUDE_MODEL",
                         os.getenv("CLAUDE_CODE_MODEL", "claude-opus-5"))
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
# Effort delle FASI JUNIOR (medium=True: analisi preliminari su Sonnet).
# Misurato l'8 set 2026: a «max» Sonnet 5 scrive 30-56k token di ragionamento
# per fase (7-13 min l'una, ~44 min a domanda complex); a «high» 45-120 s con
# la stessa sostanza, a «medium» la qualità cala. Il senior (Opus, tier
# default) resta a CLAUDE_CODE_EFFORT. Vuoto = come il senior.
CLAUDE_CODE_MEDIUM_EFFORT = os.getenv("CLAUDE_CODE_MEDIUM_EFFORT", "high")
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
# Il budget della COMPOSIZIONE e' piu' generoso: da quando i documenti
# entrano inline (una passata sola) invece che come file da leggere col
# Read agentico (un giro di modello per apertura), i caratteri sono
# economici — erano i giri a costare 14+ minuti sui fascicoli grossi.
COMPOSE_DOC_CHAR_BUDGET = int(os.getenv("COMPOSE_DOC_CHAR_BUDGET", "12000"))
# .docx/.doc/.txt/.rtf: il lettore (extract/readers.py) li gestisce gia'; il
# .doc binario passa da antiword, installato nel Dockerfile. Servono per
# allegare cio' che arriva davvero da controparti e tribunali.
# I video sono una PROVA, non un allegato qualsiasi: in una rapina o in un
# omicidio la videosorveglianza e' spesso l'elemento decisivo. `.dav` e' il
# formato delle telecamere Dahua — cioe' di gran parte dei negozi e delle
# banche in Albania: e' il caso d'uso vero, non un extra.
VIDEO_EXTENSIONS = frozenset({".mp4", ".mov", ".avi", ".mkv", ".m4v",
                              ".webm", ".mpg", ".mpeg", ".wmv", ".flv",
                              ".ts", ".mts", ".m2ts", ".3gp",
                              ".dav"})   # Dahua CCTV

# Registrazioni depositate come prova: una telefonata, un vocale, l'audio di
# una telecamera. Sono prove frequenti quanto le foto, e finora entravano solo
# se qualcuno le trascriveva a mano.
AUDIO_EXTENSIONS = frozenset({".mp3", ".wav", ".m4a", ".aac", ".ogg", ".oga",
                              ".opus", ".flac", ".wma", ".amr", ".3ga", ".caf",
                              ".aiff", ".aif"})
MAX_AUDIO_SIZE_MB = int(os.getenv("MAX_AUDIO_SIZE_MB", "200"))

ALLOWED_UPLOAD_EXTENSIONS = frozenset({".pdf", ".jpg", ".jpeg", ".png", ".svg",
                                       ".webp", ".tif", ".tiff",
                                       ".heic", ".heif",   # foto iPhone
                                       ".docx", ".doc", ".txt", ".rtf"}) | VIDEO_EXTENSIONS | AUDIO_EXTENSIONS

# ⚠️ Soglia SEPARATA per i video. 25 MB vanno bene per un atto scansionato e
# sono ridicoli per un video (tre minuti di telefono li superano). Ma alzare
# il limite per tutti sarebbe sbagliato: un PDF da 400 MB non e' un atto, e'
# un errore o un attacco.
MAX_VIDEO_SIZE_MB = int(os.getenv("MAX_VIDEO_SIZE_MB", "500"))


# Trascrittore. `small` scelto MISURANDO (31 ago 2026): in italiano trascrive
# parola per parola a 0,73× la durata; `medium` costa 2,6 volte tanto e in
# albanese non migliora di niente.
WHISPER_MODEL = os.getenv("WHISPER_MODEL", "small")
# Meta' macchina. Sopra ci sono altri cinque siti: prendersi tutti i core per
# minuti interi li affamerebbe. Una trascrizione alla volta (semaforo in
# `audio.py`) e' l'altra meta' della stessa precauzione.
WHISPER_THREADS = int(os.getenv("WHISPER_THREADS", "3"))
# Nel volume dati, non nell'immagine: sopravvive ai deploy e non aggiunge
# mezzo giga a ogni build.
WHISPER_DIR = os.getenv("WHISPER_DIR", str(ROOT / "data" / "whisper"))

# Quanti fotogrammi al massimo finiscono davanti al cervello. Non e' un
# risparmio: e' che un video di dieci minuti a un fotogramma al secondo fa 600
# immagini, che in nessun contesto ci stanno. Meglio pochi fotogrammi scelti
# sui cambi di scena che tanti presi a caso.
VIDEO_MAX_FRAMES = int(os.getenv("VIDEO_MAX_FRAMES", "24"))
# Sensibilita' del rilevamento cambio scena (0-1). Piu' basso = piu' fotogrammi.
VIDEO_SCENE_THRESHOLD = float(os.getenv("VIDEO_SCENE_THRESHOLD", "0.25"))

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
        title_sq="Kodi Ajror i Republikës së Shqipërisë (Ligji nr. 96/2020)",
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
        title_sq="Rregullore e Policisë së Shtetit (VKM nr. 112/2025, zëvendëson VKM 750/2015)",
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
    # ── 16 set 2026: 29 leggi da QBZ (archivio WebDAV, testi consolidati) — fonti e misure
    # in tools/al_sources.json, ingestione con tools/ingest_al_qbz.py (probe → apply). Stanno
    # qui perché il cervello legge CODES_INDEX da questa tupla (altrimenti non sa che esistono)
    # e pro_features/web contano i codici da qui. I PDF vivono in data/raw/al_qbz/ (volume).
    # kadastra e noteria c'erano nel corpus dal v9.30x (PDF FAOLEX/nchb.al) ma NON in questa tupla:
    # il cervello non li vedeva nell'indice dei codici. Ora dai consolidati QBZ.
    LegalDocument(code="ligji_kadastra", title_sq="Ligji nr. 111/2018 «Për kadastrën»", title_en="Cadastre Law", area="Prone", url="https://qbz.gov.al/alfresco/webdav/Aktet/ligj/kuvendi-i-shqiperise/2019/02/07/111/base/ligj-2019-02-07-111.pdf", local_pdf="al_qbz/ligji_kadastra.pdf", volatility="MEDIUM"),
    LegalDocument(code="ligji_noteri", title_sq="Ligji nr. 110/2018 «Për noterinë»", title_en="Notary Law", area="Civil", url="https://qbz.gov.al/alfresco/webdav/Aktet/ligj/kuvendi-i-shqiperise/2018/12/20/110/cons-2022-02-16/ligj-2018-12-20-110.pdf", local_pdf="al_qbz/ligji_noteri.pdf", volatility="MEDIUM", last_amendment_date="2022-01-26"),
    LegalDocument(code="ligji_dnp", title_sq="Ligji nr. 10428/2011 «Për të drejtën ndërkombëtare private»", title_en="Private International Law", area="Nderkombetar", url="https://qbz.gov.al/alfresco/webdav/Aktet/ligj/kuvendi-i-shqiperise/2011/06/02/10428/base/ligj-2011-06-02-10428.pdf", local_pdf="al_qbz/ligji_dnp.pdf", volatility="STABLE"),
    LegalDocument(code="ligji_te_huajt", title_sq="Ligji nr. 79/2021 «Për të huajt»", title_en="Law on Foreigners", area="Imigracion", url="https://qbz.gov.al/alfresco/webdav/Aktet/ligj/kuvendi-i-shqiperise/2021/06/24/79/cons-2025-07-14/ligj-2021-06-24-79-perditesuar.pdf", local_pdf="al_qbz/ligji_te_huajt.pdf", volatility="MEDIUM", last_amendment_date="2025-06-26"),
    LegalDocument(code="ligji_shtetesia", title_sq="Ligji nr. 113/2020 «Për shtetësinë»", title_en="Citizenship Law", area="Shtetesi", url="https://qbz.gov.al/alfresco/webdav/Aktet/ligj/kuvendi-i-shqiperise/2020/07/29/113/cons-2026-06-08/ligj-2020-07-29-113%20-p%c3%abrdit%c3%absuar.pdf", local_pdf="al_qbz/ligji_shtetesia.pdf", volatility="MEDIUM", last_amendment_date="2026-05-08"),
    LegalDocument(code="kodi_te_miturve", title_sq="Kodi i Drejtësisë Penale për të Mitur (Ligji nr. 37/2017)", title_en="Juvenile Criminal Justice Code", area="Penal", url="https://qbz.gov.al/alfresco/webdav/Aktet/ligj/kuvendi-i-shqiperise/2017/03/30/37-2017/base/ligj-2017-03-30-37-2017.pdf", local_pdf="al_qbz/kodi_te_miturve.pdf", volatility="STABLE"),
    LegalDocument(code="ligji_procedurat_tatimore", title_sq="Ligji nr. 9920/2008 «Për procedurat tatimore në Republikën e Shqipërisë»", title_en="Tax Procedures Law", area="Tatimor", url="https://qbz.gov.al/alfresco/webdav/Aktet/ligj/kuvendi-i-shqiperise/2008/05/19/9920/cons-2026-01-16/ligj-2008-05-19-9920-i%20p%c3%abrdit%c3%absuar%201.pdf", local_pdf="al_qbz/ligji_procedurat_tatimore.pdf", volatility="VOLATILE", last_amendment_date="2026-01-16"),
    LegalDocument(code="ligji_tatimi_te_ardhurat", title_sq="Ligji nr. 29/2023 «Për tatimin mbi të ardhurat»", title_en="Income Tax Law", area="Tatimor", url="https://qbz.gov.al/alfresco/webdav/Aktet/ligj/kuvendi-i-shqiperise/2023/03/30/29/cons-2026-01-16/ligj-2023-03-30-29%20-%20i%20p%c3%abrdit%c3%absuar%204.pdf", local_pdf="al_qbz/ligji_tatimi_te_ardhurat.pdf", volatility="VOLATILE", last_amendment_date="2026-01-16"),
    LegalDocument(code="ligji_tvsh", title_sq="Ligji nr. 92/2014 «Për tatimin mbi vlerën e shtuar»", title_en="VAT Law", area="Tatimor", url="https://qbz.gov.al/alfresco/webdav/Aktet/ligj/kuvendi-i-shqiperise/2014/07/24/92/cons-2026-01-16/ligj-2014-07-24-92-p%c3%abrdit%c3%absuar%201.pdf", local_pdf="al_qbz/ligji_tvsh.pdf", volatility="VOLATILE", last_amendment_date="2026-01-16"),
    LegalDocument(code="ligji_sigurimi_mjeteve", title_sq="Ligji nr. 32/2021 «Për sigurimin e detyrueshëm në sektorin e transportit» (shfuqizon 10076/2009)", title_en="Compulsory Motor Insurance Law", area="Sigurime", url="https://qbz.gov.al/alfresco/webdav/Aktet/ligj/kuvendi-i-shqiperise/2021/03/16/32/base/ligj-2021-03-16-32.pdf", local_pdf="al_qbz/ligji_sigurimi_mjeteve.pdf", volatility="MEDIUM", last_amendment_date="2021-03-16"),
    LegalDocument(code="vkm_dispozita_doganore", title_sq="VKM nr. 651/2017 «Për dispozitat zbatuese të Kodit Doganor» (i përditësuar 2019)", title_en="Customs Code Implementing Provisions", area="Doganor", url="https://qbz.gov.al/alfresco/webdav/Aktet/vendim/keshilli-i-ministrave/2017/11/10/651/cons-2019-10-08/Dispozitat%20e%20Kodit%20Doganor%20-2019%20i%20perditesuar.pdf", local_pdf="al_qbz/vkm_dispozita_doganore.pdf", volatility="VOLATILE", last_amendment_date="2019-10-08"),
    LegalDocument(code="ligji_ndihma_juridike", title_sq="Ligji nr. 111/2017 «Për ndihmën juridike të garantuar nga shteti»", title_en="Legal Aid Law", area="Procedure", url="https://qbz.gov.al/alfresco/webdav/Aktet/ligj/kuvendi-i-shqiperise/2017/12/14/111/base/ligj-2017-12-14-111.pdf", local_pdf="al_qbz/ligji_ndihma_juridike.pdf", volatility="MEDIUM"),
    LegalDocument(code="ligji_kundervajtjet", title_sq="Ligji nr. 10279/2010 «Për kundërvajtjet administrative»", title_en="Administrative Offences Law", area="Administrativ", url="https://qbz.gov.al/alfresco/webdav/Aktet/ligj/kuvendi-i-shqiperise/2010/05/20/10279/base/ligj-2010-05-20-10279.pdf", local_pdf="al_qbz/ligji_kundervajtjet.pdf", volatility="STABLE"),
    LegalDocument(code="ligji_permbarimi_privat", title_sq="Ligji nr. 26/2019 «Për shërbimin përmbarimor gjyqësor privat»", title_en="Private Bailiff Service Law", area="Procedure", url="https://qbz.gov.al/alfresco/webdav/Aktet/ligj/kuvendi-i-shqiperise/2019/05/08/26/base/ligj-2019-05-08-26.pdf", local_pdf="al_qbz/ligji_permbarimi_privat.pdf", volatility="MEDIUM"),
    LegalDocument(code="ligji_dhuna_familje_2026", title_sq="Ligji nr. 11/2026 «Për parandalimin dhe mbrojtjen nga dhuna ndaj grave dhe dhuna në familje» (shfuqizon 9669/2006)", title_en="Violence against Women and Domestic Violence Law 2026", area="Familje", url="https://qbz.gov.al/alfresco/webdav/Aktet/ligj/kuvendi-i-shqiperise/2026/01/28/11/base/ligj-2026-01-28-11.pdf", local_pdf="al_qbz/ligji_dhuna_familje_2026.pdf", volatility="MEDIUM", last_amendment_date="2026-01-28"),
    LegalDocument(code="ligji_dhuna_familje", title_sq="Ligji nr. 9669/2006 «Për masa ndaj dhunës në marrëdhëniet familjare» (shfuqizuar nga ligji 11/2026)", title_en="Domestic Violence Law", area="Familje", url="https://qbz.gov.al/alfresco/webdav/Aktet/ligj/kuvendi-i-shqiperise/2006/12/18/9669/cons-2020-11-04/ligj_9669_18122006_perditesuar.pdf", local_pdf="al_qbz/ligji_dhuna_familje.pdf", volatility="MEDIUM", last_amendment_date="2020-11-04"),
    LegalDocument(code="ligji_gjendja_civile", title_sq="Ligji nr. 10129/2009 «Për gjendjen civile»", title_en="Civil Status Law", area="Civil", url="https://qbz.gov.al/alfresco/webdav/Aktet/ligj/kuvendi-i-shqiperise/2009/05/11/10129/cons-2024-07-08/ligj-2009-05-11-10129%20-i%20p%c3%abrdit%c3%absuar.pdf", local_pdf="al_qbz/ligji_gjendja_civile.pdf", volatility="MEDIUM", last_amendment_date="2024-06-06"),
    LegalDocument(code="ligji_antimafia", title_sq="Ligji nr. 10192/2009 «Për parandalimin dhe goditjen e krimit të organizuar, trafikimit, korrupsionit dhe krimeve të tjera nëpërmjet masave parandaluese kundër pasurisë»", title_en="Anti-Mafia Law", area="Penal", url="https://qbz.gov.al/alfresco/webdav/Aktet/ligj/kuvendi-i-shqiperise/2009/12/03/10192/cons-2020-08-07/ligj-2009-12-03-10192-perditesuar.pdf", local_pdf="al_qbz/ligji_antimafia.pdf", volatility="MEDIUM", last_amendment_date="2020-08-07"),
    LegalDocument(code="ligji_te_dhenat_2024", title_sq="Ligji nr. 124/2024 «Për mbrojtjen e të dhënave personale» (shfuqizon 9887/2008; në fuqi 1.2.2025)", title_en="Personal Data Protection Law 2024", area="Privatesi", url="https://qbz.gov.al/alfresco/webdav/Aktet/ligj/kuvendi-i-shqiperise/2024/12/19/124/cons-2025-06-20/ligj-2024-12-19-124-korrigjuar.pdf", local_pdf="al_qbz/ligji_te_dhenat_2024.pdf", volatility="MEDIUM", last_amendment_date="2025-06-20"),
    LegalDocument(code="ligji_sigurimet_shoqerore", title_sq="Ligji nr. 7703/1993 «Për sigurimet shoqërore në Republikën e Shqipërisë»", title_en="Social Insurance Law", area="Punë", url="https://qbz.gov.al/alfresco/webdav/Aktet/ligj/kuvendi-i-shqiperise/1993/05/11/7703/cons-2023-08-07/LIGJ%20Nr.%207703%2c%20dat%c3%ab%2011.05.1993.pdf", local_pdf="al_qbz/ligji_sigurimet_shoqerore.pdf", volatility="VOLATILE", last_amendment_date="2023-08-07"),
    LegalDocument(code="ligji_avokatia", title_sq="Ligji nr. 55/2018 «Për profesionin e avokatit në Republikën e Shqipërisë»", title_en="Advocacy Law", area="Procedure", url="https://qbz.gov.al/alfresco/webdav/Aktet/ligj/kuvendi-i-shqiperise/2018/07/23/55/base/ligj-2018-07-23-55.pdf", local_pdf="al_qbz/ligji_avokatia.pdf", volatility="STABLE"),
    LegalDocument(code="ligji_ndermjetesimi", title_sq="Ligji nr. 10385/2011 «Për ndërmjetësimin në zgjidhjen e mosmarrëveshjeve»", title_en="Mediation Law", area="Procedure", url="https://qbz.gov.al/alfresco/webdav/Aktet/ligj/kuvendi-i-shqiperise/2011/02/24/10385/cons-2018-06-27/ligj-2011-02-24-10385.pdf", local_pdf="al_qbz/ligji_ndermjetesimi.pdf", volatility="MEDIUM", last_amendment_date="2018-06-27"),
    LegalDocument(code="ligji_arbitrazhi", title_sq="Ligji nr. 52/2023 «Për arbitrazhin në Republikën e Shqipërisë»", title_en="Arbitration Law", area="Procedure", url="https://qbz.gov.al/alfresco/webdav/Aktet/ligj/kuvendi-i-shqiperise/2023/07/06/52/base/ligj-2023-07-06-52.pdf", local_pdf="al_qbz/ligji_arbitrazhi.pdf", volatility="STABLE"),
    LegalDocument(code="ligji_planifikimi_territorit", title_sq="Ligji nr. 107/2014 «Për planifikimin dhe zhvillimin e territorit»", title_en="Territorial Planning Law", area="Ndertim", url="https://qbz.gov.al/alfresco/webdav/Aktet/ligj/kuvendi-i-shqiperise/2014/07/31/107/cons-2025-10-07/ligj-107-31-07-2014-i%20p%c3%abrdit%c3%absuar.pdf", local_pdf="al_qbz/ligji_planifikimi_territorit.pdf", volatility="MEDIUM", last_amendment_date="2025-10-07"),
    LegalDocument(code="ligji_te_denuarit", title_sq="Ligji nr. 81/2020 «Për të drejtat dhe trajtimin e të dënuarve me burgim dhe të paraburgosurve»", title_en="Prisoners' Rights Law", area="Penal", url="https://qbz.gov.al/alfresco/webdav/Aktet/ligj/kuvendi-i-shqiperise/2020/06/25/81/cons-2024-12-30/ligj-2020-06-25-81-i%20p%c3%abrdit%c3%absuar.pdf", local_pdf="al_qbz/ligji_te_denuarit.pdf", volatility="MEDIUM", last_amendment_date="2024-12-19"),
    LegalDocument(code="ligji_prokuroria", title_sq="Ligji nr. 97/2016 «Për organizimin dhe funksionimin e Prokurorisë»", title_en="Prosecution Office Law", area="Penal", url="https://qbz.gov.al/alfresco/webdav/Aktet/ligj/kuvendi-i-shqiperise/2016/10/06/97-2016/cons-2021-05-17/ligj-2016-10-06-97-2016%20_perditesuar1.pdf", local_pdf="al_qbz/ligji_prokuroria.pdf", volatility="MEDIUM", last_amendment_date="2021-05-17"),
    LegalDocument(code="ligji_diskriminimi", title_sq="Ligji nr. 10221/2010 «Për mbrojtjen nga diskriminimi»", title_en="Anti-Discrimination Law", area="Kushtetues", url="https://qbz.gov.al/alfresco/webdav/Aktet/ligj/kuvendi-i-shqiperise/2010/02/04/10221/cons-2026-02-24/ligj-2010-02-04-10221-perditesuar.pdf", local_pdf="al_qbz/ligji_diskriminimi.pdf", volatility="MEDIUM", last_amendment_date="2026-02-03"),
    LegalDocument(code="ligji_armet", title_sq="Ligji nr. 74/2014 «Për armët»", title_en="Weapons Law", area="Siguri", url="https://qbz.gov.al/alfresco/webdav/Aktet/ligj/kuvendi-i-shqiperise/2014/07/10/74/cons-2023-10-11/ligj-2014-07-10-74-perditesuar.pdf", local_pdf="al_qbz/ligji_armet.pdf", volatility="MEDIUM", last_amendment_date="2023-10-11"),
    LegalDocument(code="ligji_transportet_rrugore", title_sq="Ligji nr. 8308/1998 «Për transportet rrugore»", title_en="Road Transport Law", area="Rrugor", url="https://qbz.gov.al/alfresco/webdav/Aktet/ligj/kuvendi-i-shqiperise/1998/03/18/8308/cons-2016-03-23/ligj%20nr.%208303.pdf", local_pdf="al_qbz/ligji_transportet_rrugore.pdf", volatility="MEDIUM", last_amendment_date="2016-03-23"),
    LegalDocument(code="ligji_prokurimi_publik", title_sq="Ligji nr. 162/2020 «Për prokurimin publik»", title_en="Public Procurement Law", area="Administrativ", url="https://qbz.gov.al/alfresco/webdav/Aktet/ligj/kuvendi-i-shqiperise/2020/12/23/162/cons-2024-03-05/ligj-2020-12-23-162-p%c3%abrdit%c3%absuar.pdf", local_pdf="al_qbz/ligji_prokurimi_publik.pdf", volatility="MEDIUM", last_amendment_date="2024-03-05"),
    LegalDocument(code="ligji_trajtimi_prones", title_sq="Ligji nr. 133/2015 «Për trajtimin e pronës dhe përfundimin e procesit të kompensimit të pronave»", title_en="Property Treatment and Compensation Law", area="Prone", url="https://qbz.gov.al/alfresco/webdav/Aktet/ligj/kuvendi-i-shqiperise/2015/12/05/133/cons-2025-03-04/ligj-2015-12-05-133-%20i%20perditesuar.pdf", local_pdf="al_qbz/ligji_trajtimi_prones.pdf", volatility="MEDIUM", last_amendment_date="2025-02-17"),
    LegalDocument(code="ligji_proceset_kalimtare", title_sq="Ligji nr. 20/2020 «Për përfundimin e proceseve kalimtare të pronësisë në Republikën e Shqipërisë»", title_en="Completion of Transitional Property Processes Law", area="Prone", url="https://qbz.gov.al/alfresco/webdav/Aktet/ligj/kuvendi-i-shqiperise/2020/03/04/20/base/ligj-2020-03-04-20.pdf", local_pdf="al_qbz/ligji_proceset_kalimtare.pdf", volatility="MEDIUM"),
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

# ── Guardia sul contesto ───────────────────────────────────────────────
# Misurato sulle 874 sessioni vere: il picco reale e' 583.773 token, e 128
# chiamate hanno superato i 150k. Il consumo grosso NON viene dalle domande
# degli avvocati ma dai sotto-agenti di verifica web, che dentro una sola
# chiamata aprono pagine e accumulano.
#
# La soglia non blocca: segna nel registro quando una chiamata si avvicina
# al tetto, perche' se lo sfonda il CLI compatta o tronca a meta' di
# un'analisi legale — e la risposta arriva lo stesso, costruita su un
# contesto riassunto, senza che l'avvocato lo sappia.
CONTEXT_ALERT_TOKENS = int(os.environ.get("CONTEXT_ALERT_TOKENS", "400000"))

# Valvola SPENTA per scelta. `--max-budget-usd` ferma la chiamata quando
# supera una cifra: fermare un'analisi a meta' per risparmiare centesimi, su
# una causa vera, e' un cattivo affare. Vuoto = disattivata.
TETRAMORPH_MAX_BUDGET_USD = (os.environ.get("TETRAMORPH_MAX_BUDGET_USD") or "").strip()


# ── Studio ligjor: ruoli e modelli dei juristi giovani (v9.267) ─────────
# «sonnet» = mente veloce; «opus» = il modello del senior (id vero); altro =
# id esplicito (es. claude-fable-5-1). Effort vuoto = default del tier.
STUDIO_KERKUES_ENABLED = os.getenv("STUDIO_KERKUES_ENABLED", "1") == "1"
STUDIO_KERKUES_MODEL = os.getenv("STUDIO_KERKUES_MODEL", "sonnet")
STUDIO_KERKUES_EFFORT = os.getenv("STUDIO_KERKUES_EFFORT", "")
STUDIO_KERKUES_MAX_NENE = int(os.getenv("STUDIO_KERKUES_MAX_NENE", "4"))
STUDIO_DJALLI_ENABLED = os.getenv("STUDIO_DJALLI_ENABLED", "1") == "1"
STUDIO_RED2_ENABLED = os.getenv("STUDIO_RED2_ENABLED", "1") == "1"  # 2° round avversarial condizionale
WAR_ROOM_LOOP_ENABLED = os.getenv("WAR_ROOM_LOOP_ENABLED", "1") == "1"  # research loop (max-mode)
STUDIO_DJALLI_MODEL = os.getenv("STUDIO_DJALLI_MODEL", "claude-fable-5-1")  # esplicito: CLI >= 2.1.251
# 20 set 2026 — scelta del titolare: il diavolo a HIGH (misurato: 11 min a max + 3 del secondo giro;
# «pensando più del dovuto rompe le idee»). Il Giudice resta a MAX (ultimo arbitro, ~2 min).
STUDIO_DJALLI_EFFORT = os.getenv("STUDIO_DJALLI_EFFORT", "high")

# ── Il Giudice Finale (Gjyqtari i Fundit) — arbitro finale (v9.309) ──────
# Spec del titolare (11 set 2026): tutti gli agenti (Opus senior, i raccoglitori
# web/QBZ/Fletorja Zyrtare, l'avvocato del diavolo) consegnano il loro lavoro a
# Fable 5.1 max effort, che dà il VERDETTO FINALE — conferma o corregge, cerca
# l'ago nel pagliaio. Le leggi/nenet gli arrivano VERBATIM, mai riassunte. Gira
# sul percorso complesso; quando il senior è già Fable (⚡) si salta (ridondante).
# Additivo, fail-silent: se non produce, la risposta resta com'è.
STUDIO_GJYQTARI_ENABLED = os.getenv("STUDIO_GJYQTARI_ENABLED", "1") == "1"
STUDIO_GJYQTARI_MODEL = os.getenv("STUDIO_GJYQTARI_MODEL", "claude-fable-5-1")
STUDIO_GJYQTARI_EFFORT = os.getenv("STUDIO_GJYQTARI_EFFORT", "max")
# v9.356 — sul percorso ⚡ (senior Fable max) il Giudice NON si salta più: senior e diavolo sono la
# stessa mente, quindi l'arbitro deve essere un'ALTRA — «opus» = il modello del senior di default
# (Opus 5) a effort max, con gli stessi nene verbatim del corpus. «off» = comportamento vecchio
# (nessun Giudice in ⚡). Env E fallback.
STUDIO_GJYQTARI_SKUADRA_MODEL = os.getenv("STUDIO_GJYQTARI_SKUADRA_MODEL", "opus")
# v9.358 — «GJYQTARI SUPREM» (scelta del titolare, 21 set: «meglio uno fatto bene, esatto, che combina le
# menti»): UN solo percorso profondo = senior Opus max + research loop e Source Verifier (prima solo in ⚡)
# + diavolo Fable (2 round) + Giudice Fable max con RISERVA dell'altra mente (Opus max) anche quando è
# «impegnato», non solo sul limite. «0» = comportamento v9.357 (loop/raport solo in ⚡, nessuna riserva).
GJYQTARI_SUPREM_ENABLED = os.getenv("GJYQTARI_SUPREM_ENABLED", "1") == "1"
# v9.361 — tetto al corpo di UN articolo nel prompt (34 «articoli» IT oltre 30.000 chr: leggi di
# approvazione e allegati incollati; uno da 211.000). Il taglio è DICHIARATO nel blocco («… karaktere të
# hequra»), mai silenzioso, e non vale MAI per il nene chiesto per numero dall'avvocato.
PROMPT_BODY_MAX_CHARS = int(os.getenv("PROMPT_BODY_MAX_CHARS", "12000"))

# ── Mbledhësit (raccoglitori) del percorso simple — gradino B (v9.271) ──
# «sonnet» = Sonnet sul tier medium (HA il web); effort basso di proposito:
# raccolgono verbatim, non ragionano. Tetto di spesa e di tempo per chiamata:
# se un raccoglitore non torna, il senior risponde senza di lui.
STUDIO_MBLEDHES_ENABLED = os.getenv("STUDIO_MBLEDHES_ENABLED", "1") == "1"
STUDIO_MBLEDHES_MODEL = os.getenv("STUDIO_MBLEDHES_MODEL", "sonnet")
STUDIO_MBLEDHES_EFFORT = os.getenv("STUDIO_MBLEDHES_EFFORT", "medium")
STUDIO_MBLEDHES_BUDGET_USD = float(os.getenv("STUDIO_MBLEDHES_BUDGET_USD", "0.30"))
STUDIO_MBLEDHES_TIMEOUT = int(os.getenv("STUDIO_MBLEDHES_TIMEOUT", "110"))
STUDIO_MBLEDHES_WEB = os.getenv("STUDIO_MBLEDHES_WEB", "1") == "1"
STUDIO_MBLEDHES_QBZ = os.getenv("STUDIO_MBLEDHES_QBZ", "1") == "1"
STUDIO_MBLEDHES_FLETORJA = os.getenv("STUDIO_MBLEDHES_FLETORJA", "1") == "1"  # Agent D: ligji i gjallë
