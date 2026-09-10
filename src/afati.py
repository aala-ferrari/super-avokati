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

from . import deadline_engine as _de
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

# formato VECCHIO (fallback / retro-compatibilità): AFAT | titolo | YYYY-MM-DD
_AFAT_RE = re.compile(r"^\s*AFAT\s*\|\s*(.+?)\s*\|\s*(\d{4}-\d{2}-\d{2})\s*$", re.MULTILINE)
# formato NUOVO (§13): l'LLM dà la REGOLA, il motore calcola la data
#   AFAT | titolo | trigger=YYYY-MM-DD | durata=N | njesi=... | feriale=0|1 | baza=...
_AFAT_RULE_RE = re.compile(
    r"^\s*AFAT\s*\|\s*(?P<title>.+?)\s*\|\s*trigger\s*=\s*(?P<trig>\d{4}-\d{2}-\d{2})\s*\|"
    r"\s*durata\s*=\s*(?P<dur>\d{1,6})\s*\|\s*njesi\s*=\s*(?P<unit>[A-Za-zëËçÇ_]+)\s*\|"
    r"\s*feriale\s*=\s*(?P<fer>[01])\s*(?:\|\s*baza\s*=\s*(?P<baza>.+?))?\s*$",
    re.MULTILINE)
# sinonimi unità → unità del motore (accetta sq e it, robusto)
_NJESI = {
    "dite": "days", "ditë": "days", "dit": "days", "ditë_solare": "days", "giorni": "days",
    "dite_pune": "business_days", "ditë_pune": "business_days", "ditepune": "business_days",
    "giorni_lavorativi": "business_days", "business_days": "business_days",
    "muaj": "months", "mesi": "months", "mese": "months", "months": "months",
    "vite": "years", "vjet": "years", "vit": "years", "anni": "years", "anno": "years", "years": "years",
}


def list_triggers():
    return [{"key": k, "label": v["label"]} for k, v in TRIGGERS.items()]


def _today() -> str:
    return datetime.now(timezone.utc).strftime("%d.%m.%Y")


def compute(backend, index, *, trigger: str, event_date: str = "", facts: str = "",
            jurisdiction: str = "AL", max_tokens: int = 2600) -> dict:
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
        "MOS e llogarit VETË datën e skadimit: jep RREGULLIN (nga-data + sa ditë/muaj/vjet), "
        "datën e llogarit makina në mënyrë DETERMINISTE. Jep (markdown):\n"
        "### 📅 Afatet që lindin nga kjo ngjarje\n"
        "| Afati | Baza ligjore (neni) | Nga cila datë | Ditë/muaj | Data e skadimit | Veprimi |\n"
        "|---|---|---|---|---|---|\n"
        "…një rresht për çdo afat; te 'Data e skadimit' shkruaj '→ shih Llogaritjen e verifikuar', "
        "MOS vendos datë të llogaritur vetë…\n\n"
        "### ⚠️ Kujdes — pezullime/rivendosje në afat dhe çfarë duhet verifikuar\n\n"
        "PASTAJ, në fund, për ÇDO afat jep një rresht të VETËM të lexueshëm nga makina (asgjë tjetër "
        "në rresht). Jep RREGULLIN, jo datën e skadimit. Formati i saktë:\n"
        "AFAT | <titulli i shkurtër> | trigger=<YYYY-MM-DD> | durata=<numër> | njesi=<dite|dite_pune|muaj|vite> | feriale=<0|1> | baza=<neni>\n"
        "  · trigger = data nga e cila nis afati (data e ngjarjes/njoftimit)\n"
        "  · durata+njesi MERRI nga teksti REAL i nenit (p.sh. '10 ditë' → durata=10 njesi=dite)\n"
        "  · feriale=1 VETËM për afate procedurale ITALIANE (pezullimi 1–31 gusht); për Shqipërinë feriale=0\n"
        "  · nëse data e trigger-it është e panjohur, MOS e jep rreshtin AFAT (përshkruaje vetëm në tabelë)\n\n"
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
    _lang = "it" if (jurisdiction or "AL").upper() == "IT" else "sq"
    afatet: list[dict] = []
    calc: list[str] = []
    # 1) rreshtat me RREGULL → il motore DETERMINISTICO calcola la data
    for m in _AFAT_RULE_RE.finditer(md):
        title = (m.group("title") or "").strip()
        unit = _NJESI.get((m.group("unit") or "").strip().lower())
        if not unit:
            log.warning("afati: njësi e panjohur '%s' — anashkaloj", m.group("unit"))
            continue
        try:
            r = _de.compute_deadline(
                m.group("trig"), int(m.group("dur")), unit,
                jurisdiction=jurisdiction, feriale=(m.group("fer") == "1"),
                legal_basis=(m.group("baza") or "").strip(), lang=_lang)
        except Exception as exc:  # noqa: BLE001
            log.warning("deadline_engine dështoi për '%s': %s", title, exc)
            continue
        afatet.append({"title": title, "date": r.deadline.isoformat()})
        lines = ["  - " + s for s in r.steps] + ["  - ⚠ " + w for w in r.warnings]
        calc.append("**%s → %s**\n%s" % (title, r.deadline.isoformat(), "\n".join(lines)))
    # 2) fallback retro-compatibile: vecchio formato AFAT | titolo | YYYY-MM-DD (senza motore)
    for m in _AFAT_RE.finditer(md):
        afatet.append({"title": m.group(1).strip(), "date": m.group(2)})
    # rimuovi le righe macchina dal testo mostrato
    md_clean = _AFAT_RULE_RE.sub("", md)
    md_clean = _AFAT_RE.sub("", md_clean)
    md_clean = re.sub(r"\n{3,}", "\n\n", md_clean).strip()
    # appendi la sezione di calcolo VERIFICATO (i passi deterministici)
    if calc:
        head = ("\n\n### 🧮 Llogaritje e verifikuar (motor determinist)\n"
                if _lang == "sq" else
                "\n\n### 🧮 Calcolo verificato (motore deterministico)\n")
        md_clean = (md_clean + head + "\n\n".join(calc)).strip()
    return {"markdown": md_clean, "afatet": afatet,
            "articles": [{"code": c, "number": n} for c, n, _t in arts]}
