"""Plain-text extraction from scraped decision artefacts.

Input: a path saved by the scrapers into ``data/raw/jurisprudence/…``.
Extension tells us the format:

- ``.pdf``        → pdfplumber (Gjykata e Lartë has a minority of PDFs)
- ``.doc``        → antiword (Word 97-2003 binary; majority for G. e Lartë)
- ``.docx``       → python-docx (rare on this corpus, still supported)
- ``.html/.htm``  → selectolax strip_tags (HUDOC judgment bodies)
- ``.rtf/.txt``   → read as-is

``read_text(path)`` returns a ``ReadResult`` so downstream callers can
tell an empty decision from an extraction failure.
"""
from __future__ import annotations

import logging
import subprocess
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger(__name__)


ANTIWORD_BIN = "/usr/local/bin/antiword"


@dataclass
class ReadResult:
    text: str
    source_format: str
    pages: int | None = None
    # True if extraction ran without raising; the text itself may still
    # be empty (e.g. a scanned PDF with no embedded text).
    ok: bool = True
    error: str | None = None


def _read_pdf(path: Path) -> ReadResult:
    import pdfplumber  # heavy import; defer
    try:
        pieces: list[str] = []
        with pdfplumber.open(path) as pdf:
            for page in pdf.pages:
                pieces.append(page.extract_text() or "")
            pages = len(pdf.pages)
        return ReadResult(
            text="\n".join(pieces).strip(),
            source_format="pdf",
            pages=pages,
        )
    except Exception as e:
        return ReadResult(text="", source_format="pdf", ok=False, error=str(e))


def _read_doc(path: Path) -> ReadResult:
    # antiword is a tiny C tool tuned for Word 97-2003 binary .doc files.
    # `-w 0` disables word wrap so we preserve paragraph structure.
    try:
        result = subprocess.run(
            [ANTIWORD_BIN, "-w", "0", str(path)],
            capture_output=True,
            timeout=30,
            check=False,
        )
        if result.returncode != 0:
            return ReadResult(
                text="",
                source_format="doc",
                ok=False,
                error=result.stderr.decode("utf-8", "replace")[:300],
            )
        return ReadResult(
            text=result.stdout.decode("utf-8", "replace").strip(),
            source_format="doc",
        )
    except Exception as e:
        return ReadResult(text="", source_format="doc", ok=False, error=str(e))


def _read_docx(path: Path) -> ReadResult:
    try:
        from docx import Document
        doc = Document(str(path))
        text = "\n".join(p.text for p in doc.paragraphs)
        return ReadResult(text=text.strip(), source_format="docx")
    except Exception as e:
        return ReadResult(text="", source_format="docx", ok=False, error=str(e))


def _read_html(path: Path) -> ReadResult:
    try:
        from selectolax.parser import HTMLParser
        raw = path.read_text(encoding="utf-8", errors="replace")
        tree = HTMLParser(raw)
        # HUDOC ships inline <style> blocks — drop them first.
        for tag in ("style", "script"):
            for node in tree.css(tag):
                node.decompose()
        text = tree.body.text(separator="\n", strip=True) if tree.body else tree.text(separator="\n", strip=True)
        return ReadResult(text=text.strip(), source_format="html")
    except Exception as e:
        return ReadResult(text="", source_format="html", ok=False, error=str(e))


def _read_plain(path: Path) -> ReadResult:
    try:
        return ReadResult(
            text=path.read_text(encoding="utf-8", errors="replace").strip(),
            source_format=path.suffix.lstrip(".").lower() or "txt",
        )
    except Exception as e:
        return ReadResult(text="", source_format="txt", ok=False, error=str(e))


def read_text(path: str | Path) -> ReadResult:
    p = Path(path)
    if not p.exists():
        return ReadResult(
            text="", source_format="missing", ok=False, error="file not found"
        )
    ext = p.suffix.lower()
    if ext == ".pdf":
        return _read_pdf(p)
    if ext == ".doc":
        return _read_doc(p)
    if ext == ".docx":
        return _read_docx(p)
    if ext in {".html", ".htm"}:
        return _read_html(p)
    if ext in {".txt", ".rtf"}:
        return _read_plain(p)
    return ReadResult(
        text="", source_format=ext or "unknown", ok=False,
        error=f"unsupported extension: {ext}",
    )
