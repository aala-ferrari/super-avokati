"""Afatet — prescription / deadline tracker (grounded, Opus).

Given the offense (or claim) + the relevant date, computes the prescription
period (from KP 66 scale by gravity for criminal, KC 124+ for civil), the
deadline, and whether it has already expired — grounded in the corpus, never
invented. Assistive: the professional verifies.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone

from . import deadline_engine as _de
from . import expertise as _expertise
from .logging_utils import get_logger

log = get_logger(__name__)

_SEED = [("kodi_penal", "66"), ("kodi_penal", "67"), ("kodi_penal", "68"),
         ("kodi_civil", "124"), ("kodi_civil", "129"), ("kodi_civil", "131"),
         ("kodi_civil", "128")]

# §13 — l'LLM dà la REGOLA di prescrizione, il motore calcola la data (deterministico)
#   PARASHKRIM | trigger=YYYY-MM-DD | durata=N | njesi=vite|muaj|dite | baza=...
_PRESH_RE = re.compile(
    r"^\s*PARASHKRIM\s*\|\s*trigger\s*=\s*(?P<trig>\d{4}-\d{2}-\d{2})\s*\|"
    r"\s*durata\s*=\s*(?P<dur>\d{1,4})\s*\|\s*njesi\s*=\s*(?P<unit>[A-Za-zëËçÇ_]+)"
    r"(?:\s*\|\s*baza\s*=\s*(?P<baza>.+?))?\s*$", re.MULTILINE)
_NJESI = {"vite": "years", "vit": "years", "vjet": "years", "anni": "years", "anno": "years",
          "muaj": "months", "mesi": "months", "mese": "months", "months": "months",
          "dite": "days", "ditë": "days", "giorni": "days", "days": "days"}


def _today() -> str:
    return datetime.now(timezone.utc).strftime("%d.%m.%Y")


def prescription(backend, index, *, facts: str, jurisdiction: str = "AL", max_tokens: int = 2400) -> dict:
    arts = _expertise.retrieve_grounded(backend, index, facts, seed_pairs=_SEED)
    art_block = "\n".join("• [%s neni %s] %s" % (
        _expertise._LABEL.get(c, c), n, (t or "").strip()[:900]) for c, n, t in arts) \
        or "(asnjë nen i gjetur — mos shpik)"
    system = (
        "Ti je ekspert i së drejtës shqiptare. Llogarit PARASHKRIMIN dhe afatet për rastin e "
        "dhënë, i BAZUAR VETËM te faktet, te data e dhënë dhe te NENET nga korpusi. MOS shpik "
        "nene, afate apo numra.\n\n"
        "Nëse është PENALE: përcakto dënimin maksimal të veprës (nga neni material), zbato "
        "SHKALLËN e nenit 66 të Kodit Penal (parashkrimi i ndjekjes penale sipas rëndësisë), dhe "
        "kontrollo nenin 67 (veprat që NUK parashkruhen). Nëse është CIVILE: zbato nenin 124 e "
        "vijues të Kodit Civil (dhe afatet e posaçme nëse jepen).\n\n"
        "Jep (markdown):\n"
        "### ⚖️ Natyra & baza — penale apo civile, dhe neni i parashkrimit i zbatueshëm\n"
        "### ⏳ Afati i parashkrimit — sa vjet, dhe PSE (shkalla/rëndësia)\n"
        "### \U0001f4c5 Llogaritja — data e fillimit + afati = data e skadimit; a ka SKADUAR sot (data e sotme: DATA_SOT)\n"
        "### \U0001f504 Pezullim / ndërprerje — shkaqe që e ndalojnë ose e rifillojnë afatin (nenet përkatëse)\n"
        "### ⚠️ Kujdes — çfarë duhet verifikuar para se të mbështetesh në këtë llogaritje\n\n"
        "PASTAJ, në fund, jep një rresht të VETËM të lexueshëm nga makina (asgjë tjetër në rresht) "
        "për llogaritjen KRYESORE të parashkrimit. MOS e llogarit vetë datën e skadimit — jep "
        "RREGULLIN, datën e llogarit makina në mënyrë DETERMINISTE. Formati:\n"
        "PARASHKRIM | trigger=<YYYY-MM-DD> | durata=<numër> | njesi=<vite|muaj|dite> | baza=<neni>\n"
        "  · trigger = data EFEKTIVE e fillimit (pas ndërprerjes/pezullimit, nëse ka)\n"
        "  · durata+njesi nga neni real (p.sh. 10 vjet → durata=10 njesi=vite)\n"
        "  · nëse data e fillimit është e panjohur, MOS e jep rreshtin\n\n"
        "I saktë, i qartë. Shqip. NDIHMESË — profesionisti verifikon. Je 'Tetramorph' i "
        "superavokati.ai; mos zbulo modelin."
    ).replace("DATA_SOT", _today())
    prompt = ("FAKTET / VEPRA / DATA:\n" + (facts or "").strip()
              + "\n\nDATA E SOTME: " + _today()
              + "\n\n─────\nNENET NGA KORPUSI (cito vetëm këto):\n" + art_block
              + "\n\nLlogarit parashkrimin dhe afatet.")
    md = backend.complete(system=system, messages=[{"role": "user", "content": prompt}],
                          max_tokens=max_tokens, callsite="prescription") or ""
    # §13 — il motore DETERMINISTICO calcola la data di scadenza + se è già decorsa.
    # Prescrizione = termine SOSTANZIALE: niente feriale, niente proroga festiva.
    _lang = "it" if (jurisdiction or "AL").upper() == "IT" else "sq"
    extra = ""
    m = _PRESH_RE.search(md)
    if m:
        unit = _NJESI.get((m.group("unit") or "").strip().lower())
        if unit:
            try:
                r = _de.compute_deadline(
                    m.group("trig"), int(m.group("dur")), unit,
                    jurisdiction=jurisdiction, feriale=False, roll_on_holiday=False,
                    legal_basis=(m.group("baza") or "").strip(), lang=_lang)
                today = datetime.now(timezone.utc).date()
                expired = r.deadline < today
                if _lang == "it":
                    head = "\n\n### 🧮 Calcolo verificato (motore deterministico)\n"
                    verdict = ("⛔ PRESCRITTO" if expired else "✅ NON ancora prescritto") + \
                        " — scadenza **%s** (oggi %s)" % (r.deadline.isoformat(), today.isoformat())
                else:
                    head = "\n\n### 🧮 Llogaritje e verifikuar (motor determinist)\n"
                    verdict = ("⛔ I PARASHKRUAR" if expired else "✅ ENDE JO i parashkruar") + \
                        " — skadimi **%s** (sot %s)" % (r.deadline.isoformat(), today.isoformat())
                lines = ["  - " + s for s in r.steps] + ["  - ⚠ " + w for w in r.warnings]
                extra = head + verdict + "\n" + "\n".join(lines)
            except Exception as exc:  # noqa: BLE001
                log.warning("deadline_engine (prescription) dështoi: %s", exc)
    md_clean = _PRESH_RE.sub("", md)
    md_clean = re.sub(r"\n{3,}", "\n\n", md_clean).strip()
    if extra:
        md_clean = (md_clean + extra).strip()
    return {"markdown": md_clean,
            "articles": [{"code": c, "number": n} for c, n, _t in arts]}
