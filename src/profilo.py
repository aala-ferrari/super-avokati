"""Profili i Studios — pulizia e formattazione, senza Flask e senza cervello.

Separato per la regola di casa: le guardie golden lo PROVANO eseguendolo.
"""
from __future__ import annotations

CAMPI = ("stili", "gjuha", "intestazione", "foro", "rregulla", "toni")
MAX_RREGULLA = 10
MAX_BLLOK = 1400          # il profilo e' un prefisso, non un trattato


def pastro(grezzo) -> dict:
    """Tiene solo i campi noti, taglia gli eccessi, butta il vuoto."""
    if not isinstance(grezzo, dict):
        return {}
    fuori: dict = {}
    for k in CAMPI:
        v = grezzo.get(k)
        if k == "rregulla":
            if isinstance(v, str):
                v = v.splitlines()
            righe = [str(r).strip()[:200] for r in (v or []) if str(r).strip()]
            if righe:
                fuori[k] = righe[:MAX_RREGULLA]
        else:
            v = str(v or "").strip()
            if v:
                fuori[k] = v[:300]
    return fuori


def formato_blloku(d: dict | None) -> str:
    """Il blocco che si antepone al prompt. Vuoto se non c'e' profilo.

    ⚠️ Dice esplicitamente al cervello che queste sono REGOLE DI STILE, non
    fonti di diritto: una riga scritta male dall'admin non deve mai poter
    diventare una base giuridica.
    """
    d = pastro(d or {})
    if not d:
        return ""
    p = ["── PROFILI I STUDIOS (stil dhe rregulla shtëpie — JO burim ligjor) ──"]
    if d.get("intestazione"):
        p.append("• Studioja: " + d["intestazione"])
    if d.get("foro"):
        p.append("• Gjykata/foroja kryesore: " + d["foro"])
    if d.get("stili"):
        p.append("• Stili i shkrimit: " + d["stili"])
    if d.get("gjuha"):
        p.append("• Gjuha e akteve: " + d["gjuha"])
    if d.get("toni"):
        p.append("• Toni me klientët: " + d["toni"])
    for r in d.get("rregulla", []):
        p.append("• Rregull: " + r)
    p.append("Zbatoji këto si preferenca formulimi. Ligji dhe faktet fitojnë "
             "GJITHMONË mbi çdo rregull shtëpie.")
    out = "\n".join(p)
    return out[:MAX_BLLOK] + ("\n" if not out.endswith("\n") else "")
