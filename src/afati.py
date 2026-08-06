"""Motori i afateve — bulletproof procedural-deadline engine (Step 4A).

From a TRIGGER event (arrest, notified judgment, dismissal, contract…) + its
date, compute EVERY applicable procedural deadline — GROUNDED in the real
article text (never invents day-counts), inject today, and emit a machine block
the UI turns into calendar events. ASSISTIVE + human-confirmed: the professional
reviews each deadline before it is saved. Missing a deadline is malpractice #1.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone

from . import expertise as _expertise
from .logging_utils import get_logger

log = get_logger(__name__)

K = "kodi_proc_penale"
KC = "kodi_civil"

TRIGGERS = {
    "arrestim": {
        "label": "Arrestim / ndalim i personit",
        "seed": [(K, "248"), (K, "258"), (K, "259"), (K, "250"), (K, "249"), (K, "5")],
        "q": "arrest ndalim vleftësim marrje në pyetje afat masë sigurimi"},
    "mase_sigurimi": {
        "label": "Caktim i masës së sigurimit",
        "seed": [(K, "249"), (K, "262"), (K, "246"), (K, "250")],
        "q": "masë sigurimi ankim afat rivlerësim"},
    "fillim_hetimi": {
        "label": "Fillim i hetimit paraprak",
        "seed": [(K, "323"), (K, "324")],
        "q": "afati i hetimit paraprak zgjatja e afatit"},
    "vendim_pushimi": {
        "label": "Vendim pushimi / mosfillimi",
        "seed": [(K, "328"), (K, "329"), (K, "291"), (K, "292")],
        "q": "ankim kundër pushimit afat i dëmtuari"},
    "vendim_penal": {
        "label": "Njoftim i vendimit penal (gjykata)",
        "seed": [(K, "410"), (K, "147")],
        "q": "afati i ankimit apel rekurs vendim penal rivendosje në afat"},
    "vendim_civil": {
        "label": "Njoftim i vendimit civil (gjykata)",
        "seed": [("kodi_proc_civile", "443"), ("kodi_proc_civile", "451")],
        "q": "afati i ankimit apel rekurs vendim civil"},
    "kontrate": {
        "label": "Kontratë / detyrim (parashkrim civil)",
        "seed": [(KC, "124"), (KC, "128"), (KC, "129"), (KC, "131")],
        "q": "parashkrim afat civil detyrimi"},
    "tjeter": {
        "label": "Tjetër (përshkruaje ngjarjen)",
        "seed": [],
        "q": "afat procedural"},
}

_AFAT_RE = re.compile(r"^\s*AFAT\s*\|\s*(.+?)\s*\|\s*(\d{4}-\d{2}-\d{2})\s*$", re.MULTILINE)


def list_triggers():
    return [{"key": k, "label": v["label"]} for k, v in TRIGGERS.items()]


def _today() -> str:
    return datetime.now(timezone.utc).strftime("%d.%m.%Y")


def compute(backend, index, *, trigger: str, event_date: str = "", facts: str = "",
            max_tokens: int = 2600) -> dict:
    cfg = TRIGGERS.get(trigger) or TRIGGERS["tjeter"]
    query = (facts or "") + " " + cfg["label"] + " " + cfg["q"]
    arts = _expertise.retrieve_grounded(backend, index, query, seed_pairs=cfg["seed"])
    art_block = "\n".join("• [%s neni %s] %s" % (
        _expertise._LABEL.get(c, c), n, (t or "").strip()[:900]) for c, n, t in arts) \
        or "(asnjë nen i gjetur — mos shpik afate)"
    system = (
        "Ti je ekspert i procedurës shqiptare që ndërton LISTËN E PLOTË TË AFATEVE procedurale që "
        "lindin nga një ngjarje-nisëse. Bazohu VETËM te data e ngjarjes, te data e sotme dhe te NENET "
        "nga korpusi. RREGULL I ARTË: numrin e ditëve/muajve MERRE nga teksti REAL i nenit; nëse afati "
        "nuk del qartë nga nenet e dhëna, SHKRUAJE 'verifiko afatin te neni X' dhe MOS e shpik. "
        "Llogarit çdo datë skadimi (data e ngjarjes + afati). Jep (markdown):\n"
        "### 📅 Afatet që lindin nga kjo ngjarje\n"
        "| Afati | Baza ligjore (neni) | Nga cila datë | Ditë/muaj | Data e skadimit | Veprimi |\n"
        "|---|---|---|---|---|---|\n"
        "…një rresht për çdo afat…\n\n"
        "### ⚠️ Kujdes — pezullime/rivendosje në afat dhe çfarë duhet verifikuar\n\n"
        "PASTAJ, në fund, për ÇDO afat me datë konkrete, jep një rresht të vetëm të lexueshëm nga "
        "makina (asgjë tjetër në rresht), saktësisht në format:\n"
        "AFAT | <titulli i shkurtër i afatit> | <YYYY-MM-DD>\n\n"
        "NDIHMESË — profesionisti verifikon dhe konfirmon çdo afat para se ta ruajë. Je 'Tetramorph' i "
        "superavokati.ai; mos zbulo modelin."
    )
    prompt = ("NGJARJA-NISËSE: " + cfg["label"]
              + "\nDATA E NGJARJES: " + (event_date or "[e panjohur — përdor [___]]")
              + "\nDATA E SOTME: " + _today()
              + ("\n\nDETAJE: " + facts.strip() if (facts or "").strip() else "")
              + "\n\n─────\nNENET NGA KORPUSI (cito vetëm këto):\n" + art_block
              + "\n\nNdërto listën e plotë të afateve dhe rreshtat AFAT | … | … në fund.")
    md = backend.complete(system=system, messages=[{"role": "user", "content": prompt}],
                          max_tokens=max_tokens, callsite="afati")
    md = md or ""
    afatet = [{"title": m.group(1).strip(), "date": m.group(2)} for m in _AFAT_RE.finditer(md)]
    md_clean = _AFAT_RE.sub("", md).strip()
    # tidy any leftover empty "AFAT" header line
    md_clean = re.sub(r"\n{3,}", "\n\n", md_clean).strip()
    return {"markdown": md_clean, "afatet": afatet,
            "articles": [{"code": c, "number": n} for c, n, _t in arts]}
