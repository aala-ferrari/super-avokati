"""v9.434 — MISURA dei TERMINI DI LEGGE che partono da un evento del documento (`afati.compute`: articoli del corpus → righe
AFAT → data dal motore deterministico), la strada che lo scadenziario usa per sentenze, decreti, licenziamenti. Casi con la risposta
scritta prima e verificata sul codice: la data attesa deve uscire, con la BASE (l'articolo) giusta. Nessun database, nessun avviso.

    docker run --rm --env-file … -v <copia credenziali>:/home/avvocato/.claude super-avvocato:vX python3 tools/eval_afati.py
"""
from __future__ import annotations

import os
import re
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

CASI = [
    {"id": "al_vendim_civil", "g": "AL", "trigger": "vendim_civil", "data": "18.09.2026",
     "fatti": "Vendim i Gjykatës së Rrethit Gjyqësor Durrës, datë 10.09.2026, njoftuar mbrojtësit të të paditurës më 18.09.2026.",
     "attesa": ("2026-10-05", r"\b443\b")},
    {"id": "al_vendim_penal", "g": "AL", "trigger": "vendim_penal", "data": "10.09.2026",
     "fatti": "Vendim i Gjykatës së Shkallës së Parë, shpallur në seancë më 10.09.2026 në prani të të pandehurit dhe të mbrojtësit.",
     "attesa": ("2026-09-25", r"\b415\b")},
    {"id": "it_decreto_ingiuntivo", "g": "IT", "trigger": "decreto_ingiuntivo", "data": "15.09.2026",
     "fatti": "Decreto ingiuntivo n. 8812/2026 del Tribunale di Milano, notificato a mezzo PEC il 15.09.2026.",
     "attesa": ("2026-10-26", r"\b641\b")},
    {"id": "it_sentenza_appello", "g": "IT", "trigger": "vendim_civil", "data": "15.07.2026",
     "fatti": "Sentenza civile di primo grado del Tribunale di Roma (materia contrattuale, non lavoro), notificata su istanza della "
              "controparte il 15.07.2026.",
     "attesa": ("2026-09-14", r"\b325\b")},
]


def main() -> int:
    from src import web, brain, afati
    web._ensure_loaded()
    ok_tot = 0
    for c in CASI:
        brain.set_request_jurisdiction(c["g"])
        idx = web._INDEX_IT if c["g"] == "IT" else web._INDEX
        t0 = time.time()
        try:
            r = afati.compute(web._BRAIN.backend, idx, trigger=c["trigger"], event_date=c["data"], facts=c["fatti"],
                              jurisdiction=c["g"])
        except Exception as exc:  # noqa: BLE001
            print(f"✗ {c['id']}: {type(exc).__name__}: {exc}")
            continue
        data, rx = c["attesa"]
        righe = r.get("afatet") or []
        trovata = [a for a in righe if a.get("date") == data]
        base_ok = any(re.search(rx, a.get("baza") or "") for a in trovata)
        senza_motore = [a for a in righe if not a.get("passi")]
        ok = bool(trovata) and base_ok
        ok_tot += ok
        print(f"{'✓' if ok else '✗'} {c['id']:<22} attesa {data} ({rx}) · trovata {bool(trovata)} base {base_ok} · "
              f"righe {len(righe)} · senza motore {len(senza_motore)} · {time.time() - t0:.0f} s")
        for a in righe:
            print(f"      {a.get('date')}  {a.get('baza') or '-':<28} {a.get('title', '')[:70]}")
    print(f"\nTOTALE: {ok_tot}/{len(CASI)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
