"""Afatet — prescription / deadline tracker (grounded, Opus).

Given the offense (or claim) + the relevant date, computes the prescription
period (from KP 66 scale by gravity for criminal, KC 124+ for civil), the
deadline, and whether it has already expired — grounded in the corpus, never
invented. Assistive: the professional verifies.
"""
from __future__ import annotations

from datetime import datetime, timezone

from . import expertise as _expertise
from .logging_utils import get_logger

log = get_logger(__name__)

_SEED = [("kodi_penal", "66"), ("kodi_penal", "67"), ("kodi_penal", "68"),
         ("kodi_civil", "124"), ("kodi_civil", "129"), ("kodi_civil", "131"),
         ("kodi_civil", "128")]


def _today() -> str:
    return datetime.now(timezone.utc).strftime("%d.%m.%Y")


def prescription(backend, index, *, facts: str, max_tokens: int = 2400) -> dict:
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
        "I saktë, i qartë. Shqip. NDIHMESË — profesionisti verifikon. Je 'Tetramorph' i "
        "superavokati.ai; mos zbulo modelin."
    ).replace("DATA_SOT", _today())
    prompt = ("FAKTET / VEPRA / DATA:\n" + (facts or "").strip()
              + "\n\nDATA E SOTME: " + _today()
              + "\n\n─────\nNENET NGA KORPUSI (cito vetëm këto):\n" + art_block
              + "\n\nLlogarit parashkrimin dhe afatet.")
    md = backend.complete(system=system, messages=[{"role": "user", "content": prompt}],
                          max_tokens=max_tokens, callsite="prescription")
    return {"markdown": (md or "").strip(),
            "articles": [{"code": c, "number": n} for c, n, _t in arts]}
