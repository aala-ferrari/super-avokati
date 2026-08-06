"""Act quality control — verify a drafted legal document before filing.

Reuses the Citation Verifier to scan every "Neni N <Kod>" reference and flag:
  • fake      — the article does not exist in that code
  • repealed  — the article exists but is repealed (shfuqizuar)
  • needs_code — an article number without a clear code (ambiguous)
Deterministic (no LLM): fast and trustworthy. The lawyer sees exactly which
citations are safe and which must be fixed before depositing the act.
"""
from __future__ import annotations

from .citation_verifier import verify_text
from .logging_utils import get_logger

log = get_logger(__name__)


def check_act(index, text: str) -> dict:
    text = text or ""
    if len(text.strip()) < 10:
        return {"total": 0, "verified": 0, "fake": [], "repealed": [],
                "needs_code": [], "clean": True, "empty": True}
    v = verify_text(text, index)
    fake, needs_code, repealed, ok = [], [], [], 0
    for i in v.get("items", []):
        st = i.get("status")
        if st == "fake":
            fake.append(i)
        elif st == "repealed":
            repealed.append(i)
        elif st == "needs_code":
            needs_code.append(i)
        elif st == "verified":
            ok += 1
    total = len(v.get("items", []))
    return {
        "total": total,
        "verified": ok,
        "fake": fake,
        "repealed": repealed,
        "needs_code": needs_code,
        "clean": (total > 0 and not fake and not repealed and not needs_code),
    }
