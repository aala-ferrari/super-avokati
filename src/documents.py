"""Dossier processing — turn a lawyer's uploaded files into structured context.

Two stages per document:

  1. EXTRACTION — pull raw text out of the file.
     • PDF     → pdfplumber text layer; if the layer is sparse (<200 chars
                 across the whole doc) we treat the PDF as scanned and fall
                 back to vision OCR on each page image.
     • Image   → vision OCR via the current LLM backend (Claude Code CLI,
                 Anthropic, or Gemini — each implements `ocr_image()`).
     • SVG     → XML text-node extraction (no OCR needed).

  2. AI ANALYSIS (fast model) — classify the document and extract the facts
     that matter for a legal case: parties, dates, amounts, what was asked /
     decided / signed. This output is what the brain actually reads when
     composing an answer — the raw text is kept for fidelity.

Vision routes through the brain's backend, so a Claude Code subscription
user gets image OCR out of the box — no extra API key needed.
"""
from __future__ import annotations

import json
import mimetypes
import re
import tempfile
import uuid
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path

from .config import (
    ALLOWED_UPLOAD_EXTENSIONS,
    DOC_CONTEXT_CHAR_BUDGET,
    MAX_UPLOAD_SIZE_MB,
    UPLOAD_PATH,
)
from .logging_utils import get_logger

def _juris(system_prompt: str) -> str:
    """System prompt adattato alla giurisdizione della richiesta.

    Import differito: brain.py importa alcuni di questi moduli, quindi un
    import in testa creerebbe un ciclo."""
    try:
        from .brain import apply_current
        return apply_current(system_prompt)
    except Exception:  # noqa: BLE001
        return system_prompt



log = get_logger(__name__)

MAX_UPLOAD_BYTES = MAX_UPLOAD_SIZE_MB * 1024 * 1024

# When a PDF's text layer has less than this many characters total we assume
# the PDF is a scanned image and attempt OCR page by page.
SCANNED_PDF_THRESHOLD = 200

# Hard cap on vision OCR — we don't want to spend 40 API calls on a 200-page
# PDF. For longer scans, the first N pages usually contain the operative
# part (cover, parties, dispositif); the lawyer can still upload the rest
# as separate files.
MAX_OCR_PAGES = 10


@dataclass(frozen=True)
class ValidationResult:
    ok: bool
    ext: str
    mimetype: str
    error: str = ""


def validate_upload(filename: str, size_bytes: int) -> ValidationResult:
    """Pre-flight check before we ever write to disk."""
    if size_bytes <= 0:
        return ValidationResult(False, "", "", "Skedar bosh")
    if size_bytes > MAX_UPLOAD_BYTES:
        return ValidationResult(
            False, "", "",
            f"Skedari tejkalon {MAX_UPLOAD_SIZE_MB} MB",
        )
    ext = Path(filename).suffix.lower()
    if ext not in ALLOWED_UPLOAD_EXTENSIONS:
        allowed = ", ".join(sorted(ALLOWED_UPLOAD_EXTENSIONS))
        return ValidationResult(
            False, "", "",
            f"Lloji i skedarit '{ext or 'i panjohur'}' nuk mbështetet. "
            f"Lejohen: {allowed}",
        )
    mimetype, _ = mimetypes.guess_type(filename)
    if not mimetype:
        # Sensible defaults for the extensions we accept.
        mimetype = {
            ".pdf": "application/pdf",
            ".svg": "image/svg+xml",
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".png": "image/png",
            ".webp": "image/webp",
            ".tif": "image/tiff",
            ".tiff": "image/tiff",
        }.get(ext, "application/octet-stream")
    return ValidationResult(True, ext, mimetype)


def storage_path_for(case_id: str, ext: str) -> Path:
    """Where on disk a new upload lives. Filename is a UUID so user-supplied
    names never touch the filesystem."""
    case_dir = UPLOAD_PATH / case_id
    case_dir.mkdir(parents=True, exist_ok=True)
    return case_dir / f"{uuid.uuid4().hex}{ext}"


# ── extraction ─────────────────────────────────────────────────────────────


def extract_text(
    path: Path, ext: str, mimetype: str, backend=None,
) -> tuple[str, bool]:
    """Return (text, used_vision_ocr) for a file we just saved to disk.

    `used_vision_ocr` is True when we had to fall back to a vision model —
    the web layer surfaces this in the UI so the lawyer knows the extraction
    was AI-OCR, not a deterministic text layer.

    `backend` is the brain's LLMBackend — when provided, image and
    scanned-PDF OCR go through `backend.ocr_image(...)`. Without a backend,
    only the deterministic paths (PDF text layer, SVG) work.
    """
    if ext == ".pdf":
        text, used_ocr = _extract_pdf(path, backend)
        return text, used_ocr
    if ext == ".svg":
        return _extract_svg(path), False
    if ext in {".jpg", ".jpeg", ".png", ".webp", ".tif", ".tiff"}:
        return _vision_ocr_image(path, mimetype, backend), True
    return "", False


def _extract_pdf(path: Path, backend) -> tuple[str, bool]:
    """Try pdfplumber's text layer; fall back to vision OCR if it's too sparse."""
    import pdfplumber  # lazy import — pdfplumber is heavy to load

    text_chunks: list[str] = []
    try:
        with pdfplumber.open(path) as pdf:
            for page in pdf.pages:
                t = (page.extract_text() or "").strip()
                if t:
                    text_chunks.append(t)
    except Exception as exc:
        log.warning("pdfplumber failed on %s (%s) — trying OCR", path.name, exc)
        text_chunks = []

    joined = "\n\n".join(text_chunks).strip()
    if len(joined) >= SCANNED_PDF_THRESHOLD:
        return joined, False

    # Text layer too thin — likely a scan. Rasterize each page and OCR it.
    log.info("PDF %s looks scanned (%d chars) — running vision OCR",
             path.name, len(joined))
    try:
        return _vision_ocr_pdf_pages(path, backend), True
    except Exception as exc:
        # If pdfplumber already pulled *some* text, keep it rather than
        # erroring — partial content is better than none.
        if joined:
            log.warning("vision OCR failed on %s (%s); using thin text layer",
                        path.name, exc)
            return joined, False
        # No text layer AND no OCR available → bubble up so the web layer
        # can mark the document status='error'. Returning a placeholder
        # string here would be fed to the triage model and derail it.
        raise RuntimeError(
            f"PDF i skanuar dhe OCR nuk funksionoi: {exc}"
        ) from exc


def _extract_svg(path: Path) -> str:
    """Grab all <text>/<tspan> nodes from an SVG. Namespace-agnostic."""
    try:
        tree = ET.parse(path)
    except ET.ParseError as exc:
        log.warning("SVG parse failed on %s: %s", path.name, exc)
        return ""
    root = tree.getroot()
    texts: list[str] = []
    for el in root.iter():
        tag = el.tag.rsplit("}", 1)[-1]  # strip namespace
        if tag in {"text", "tspan", "title", "desc"}:
            if el.text:
                s = el.text.strip()
                if s:
                    texts.append(s)
    return "\n".join(texts)


# ── vision OCR ─────────────────────────────────────────────────────────────

VISION_PROMPT = (
    "Ti je një OCR profesionist për dokumente ligjore shqiptare. "
    "Kthe VETËM tekstin e plotë të dukshëm në këtë imazh, duke ruajtur "
    "rendin e rreshtave dhe ndarjet në paragrafë. Mos shto asnjë koment, "
    "përmbledhje apo shpjegim. Nëse ka vula, nënshkrime ose stampa, "
    "shënoji në kllapa katrore (p.sh. [VULA: Gjykata e Rrethit Tiranë]). "
    "Nëse imazhi është i paqartë ose bosh, kthe vetëm '[IMAZH I PAQARTË]'."
)


def _vision_ocr_image(path: Path, mimetype: str, backend) -> str:
    """OCR a single image file via the brain's LLM backend.

    Raises RuntimeError when the backend doesn't support vision. The web
    layer catches that and marks the document status='error' so it's
    surfaced in the UI and excluded from the dossier fed into triage.
    """
    if backend is None:
        raise RuntimeError(
            "Asnjë backend LLM nuk është i disponueshëm për OCR."
        )
    return backend.ocr_image(path, mimetype, VISION_PROMPT)


def _vision_ocr_pdf_pages(path: Path, backend) -> str:
    """Render each page to a temp PNG on disk and OCR it via the backend."""
    import pdfplumber

    if backend is None:
        raise RuntimeError("no backend available for vision OCR")

    # Write page images to a temp dir inside the PDF's parent so every
    # backend (including Claude Code CLI with --add-dir) can read them.
    tmp_dir = Path(tempfile.mkdtemp(prefix="ocr_", dir=str(path.parent)))
    pages_text: list[str] = []
    try:
        with pdfplumber.open(path) as pdf:
            total = len(pdf.pages)
            for i, page in enumerate(pdf.pages[:MAX_OCR_PAGES], start=1):
                img = page.to_image(resolution=150)
                page_path = tmp_dir / f"page_{i}.png"
                img.save(str(page_path), format="PNG")
                page_text = backend.ocr_image(
                    page_path, "image/png", VISION_PROMPT,
                )
                pages_text.append(f"── Faqja {i}/{total} ──\n{page_text.strip()}")
        if total > MAX_OCR_PAGES:
            pages_text.append(
                f"\n(Vetëm {MAX_OCR_PAGES} faqet e para u skanuan "
                f"automatikisht — totali: {total}. Ngarko faqet e mbetura "
                f"veçmas nëse janë të nevojshme.)"
            )
    finally:
        # Best-effort cleanup; missing files are fine.
        for f in tmp_dir.glob("*"):
            try: f.unlink()
            except OSError: pass
        try: tmp_dir.rmdir()
        except OSError: pass
    return "\n\n".join(pages_text)


# ── AI analysis (classify + summarize + extract facts) ────────────────────

ANALYSIS_SYSTEM = """Ti je asistent ligjor që analizon dokumente për një dosje gjyqësore.
Detyra jote: lexo dokumentin dhe kthe NJË objekt JSON me këtë strukturë EKZAKTE:

{
  "doc_type": "kategoria e dokumentit në shqip (p.sh. 'Vendim gjykate', 'Padi civile', 'Kontratë pune', 'Akt administrativ', 'Kërkesë', 'Fatura', 'Njoftim', 'Procesverbal', 'Raport mjeko-ligjor', etj.)",
  "summary": "përmbledhje 2-4 fjali në shqip që shpjegon çfarë është ky dokument dhe çfarë ka rëndësi ligjore. Ji konkret — mos thuaj 'dokumenti përmban informacion' por 'punëdhënësi njofton pushimin nga puna për arsye ekonomike'.",
  "key_facts": [
    "fakte të veçanta ligjore, një për element (maksimum 8 totale)",
    "DATA — çdo datë e rëndësishme me kontekstin e saj",
    "PALËT — emra, role, adresa kur janë të dukshme",
    "SHUMA — çdo vlerë monetare me kontekst",
    "NUMRA — numra vendimi, dosjeje, njoftimi",
    "AFATE — çdo afat i përmendur (ankim, pagesë, kthim)",
    "VEPRIMET — çfarë kërkohet/vendoset/nënshkruhet"
  ]
}

RREGULLA:
• Bazohu vetëm te dokumenti i dhënë. Mos shpik fakte që nuk janë aty.
• Nëse dokumenti është i paqartë ose pa përmbajtje ligjore të dukshme, kthe:
  {"doc_type": "I paqartë", "summary": "...pse nuk mund ta klasifikosh...", "key_facts": []}
• Çdo "key_fact" duhet të jetë një fjali e qartë dhe e vetme në shqip.
• Mos përdor kllapa të shumta, mos shkruaj në listë me pika — vetëm tekst i pastër brenda stringut."""


def summarize_document(extracted_text: str, filename: str, backend) -> dict:
    """Call the fast model to classify + summarize + extract facts.

    `backend` is a `LLMBackend` (reuses the brain's configured provider).
    Returns a dict with keys: doc_type, summary, key_facts. Falls back to
    sensible defaults on any failure — we never let analysis errors kill
    an upload, since the raw text is still usable by the brain.
    """
    text = (extracted_text or "").strip()
    if not text:
        return {"doc_type": "Bosh", "summary": "Dokumenti nuk ka tekst të lexueshëm.",
                "key_facts": []}

    # Cap the text we send to the fast tier (Sonnet/Flash) — most
    # documents fit, but a scanned 40-page file would blow the budget.
    clipped = text[:12000]
    if len(text) > 12000:
        clipped += "\n\n[… teksti i mëtejshëm u shkurtua për analizë …]"

    prompt = (
        f"Skedari: {filename}\n\n"
        f"Përmbajtja e dokumentit:\n\"\"\"\n{clipped}\n\"\"\"\n\n"
        f"Analizo dokumentin dhe kthe JSON sipas formatit të kërkuar."
    )

    try:
        raw = backend.complete(
            system=_juris(ANALYSIS_SYSTEM),
            messages=[{"role": "user", "content": prompt}],
            max_tokens=900,
            medium=True,  # V8.10 Sonnet — lawyer reads doc summary
        )
    except Exception as exc:
        log.warning("doc analysis failed for %s: %s", filename, exc)
        return {"doc_type": None, "summary": None, "key_facts": []}

    data = _parse_json_loose(raw)
    doc_type = str(data.get("doc_type") or "").strip() or None
    summary = str(data.get("summary") or "").strip() or None
    key_facts_raw = data.get("key_facts") or []
    key_facts = [str(f).strip() for f in key_facts_raw
                 if isinstance(f, str) and str(f).strip()][:8]
    return {"doc_type": doc_type, "summary": summary, "key_facts": key_facts}


def _parse_json_loose(raw: str) -> dict:
    s = (raw or "").strip()
    if s.startswith("```"):
        s = s.split("```", 2)[1]
        if s.lstrip().lower().startswith("json"):
            s = s.split("\n", 1)[1] if "\n" in s else ""
        s = s.rsplit("```", 1)[0]
    start, end = s.find("{"), s.rfind("}")
    if start == -1 or end == -1:
        return {}
    try:
        return json.loads(s[start : end + 1])
    except Exception:
        return {}


# ── rendering for the brain's prompt ──────────────────────────────────────


def format_documents_for_prompt(
    documents: list[dict], *, compact: bool = False
) -> str:
    """Turn a list of analysed docs into the 'DOKUMENTET E DOSJES' block
    that the brain injects into triage + answer prompts.

    `compact=True` — used by the TRIAGE stage. Includes only filename,
    type, summary and key facts. The full extracted text is omitted so the
    fast model isn't drowned in legal prose (and can't be derailed by
    language inside a document that reads like a direct instruction).

    `compact=False` — used by the ANSWER stage. Adds a budgeted slice of
    the raw extracted text so the main model can cite specific phrasing
    and quote directly from the document.

    Returns an empty string when no documents are present.
    """
    if not documents:
        return ""

    parts: list[str] = [
        "",
        "── DOKUMENTET E DOSJES (referencë, jo pyetje) ──",
        "Më poshtë është një përmbledhje e dokumenteve që janë "
        "bashkangjitur në këtë rast. Përdori vetëm si "
        "kontekst — pyetja e vërtetë vjen PAS bllokut 'FUND I DOKUMENTEVE'.",
        "",
    ]
    for i, d in enumerate(documents, 1):
        header = f"[{i}] {d.get('filename', 'dokument')}"
        if d.get("doc_type"):
            header += f" — {d['doc_type']}"
        parts.append(header)
        if d.get("summary"):
            parts.append(f"  Përmbledhje: {d['summary']}")
        facts = d.get("key_facts") or []
        if facts:
            parts.append("  Faktet kryesore:")
            for f in facts:
                parts.append(f"    • {f}")
        if not compact:
            text = (d.get("extracted_text") or "").strip()
            if text:
                clipped = _budget_clip(text, DOC_CONTEXT_CHAR_BUDGET)
                parts.append("  Përmbajtja tekstuale (për citim):")
                for line in clipped.splitlines():
                    parts.append(f"    {line}")
        parts.append("")
    parts.append("── FUND I DOKUMENTEVE ──")
    parts.append("")
    return "\n".join(parts)


def _budget_clip(text: str, budget: int) -> str:
    """Keep a document within `budget` chars. For long docs we take the
    first 70% + last 30% of the budget, so the cover page (parties, date,
    object) AND the dispositif/signature both survive."""
    text = re.sub(r"[ \t]+", " ", text).strip()
    if len(text) <= budget:
        return text
    head_n = int(budget * 0.7)
    tail_n = budget - head_n - 40  # 40 chars for the ellipsis marker
    return (
        text[:head_n].rstrip()
        + "\n\n[… përmbajtja ndërmjet u shkurtua …]\n\n"
        + text[-tail_n:].lstrip()
    )
