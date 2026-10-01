"""v9.435 — MISURA della SEGRETARIA (portale e Telegram): la frase dell'avvocato → l'azione proposta (tipo, genere, DATA, ora,
fascicolo). Le date relative («domani», «tra 10 giorni», «pasnesër») le calcola il modello: è il punto da misurare. Le attese si
calcolano da OGGI (ora di Tirana/Roma) al momento della prova. Database di PROVA (`APP_DB_PATH` su una COPIA), niente eseguito:
si guarda solo l'azione proposta.

    docker run --rm … -e APP_DB_PATH=/tqa/app.db … super-avvocato:vX python3 tools/eval_segretaria.py
"""
from __future__ import annotations

import os
import sys
import time
import uuid
from datetime import datetime, timedelta
from types import SimpleNamespace
from zoneinfo import ZoneInfo

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src import storage, brain, secretary  # noqa: E402
from src.backends import build_backend  # noqa: E402

storage.init_db()
OGGI = datetime.now(ZoneInfo("Europe/Tirane")).date()
G = lambda n: (OGGI + timedelta(days=n)).isoformat()   # noqa: E731
ANNO = OGGI.year if (OGGI.month, OGGI.day) <= (11, 4) else OGGI.year + 1

CASI = [
    ("IT", "Registra un'udienza per Rossi il 4 novembre alle 10", "create_event", "seance", f"{ANNO}-11-04", "10:00", "Rossi"),
    ("IT", "Fissami un appuntamento con il cliente domani alle 16:30", "create_event", "takim", G(1), "16:30", None),
    ("IT", "Metti in agenda il deposito della memoria tra 10 giorni", "create_event", ("dorëzim", "afat"), G(10), None, None),
    ("IT", "Scadenza per l'appello di Rossi fra 30 giorni", "create_event", "afat", G(30), None, "Rossi"),
    ("IT", "Cosa ho in agenda domani?", None, None, None, None, None),
    ("AL", f"Regjistro një seancë për Kolën më 12 nëntor ora 9:30", "create_event", "seance", f"{ANNO}-11-12", "09:30", "Kola"),
    ("AL", "Takim me klientin pasnesër në orën 11", "create_event", "takim", G(2), "11:00", None),
    ("AL", "Afati për ankimin e Kolës është pas 15 ditësh", "create_event", "afat", G(15), None, "Kola"),
]


def main() -> int:
    u = storage.create_user(f"prova.evseg.{uuid.uuid4().hex[:6]}", "x", profession="avokat")
    storage.set_user_jurisdictions(u.id, ["AL", "IT"])
    casi_db = {"Rossi": storage.create_case(u.id, "Rossi contro Alfa S.p.A.", jurisdiction="IT"),
               "Kola": storage.create_case(u.id, "Kola kundër Bankës", jurisdiction="AL")}
    cervello = SimpleNamespace(backend=build_backend())
    punti = tot = 0
    try:
        for giur, frase, tipo, genere, data, ora, caso in CASI:
            brain.set_request_user(u.id)
            brain.set_request_jurisdiction(giur)
            t0 = time.time()
            r = secretary.handle_message(cervello, u.id, [{"role": "user", "content": frase}])
            a = r.get("action") or {}
            p = a.get("params") or {}
            got_d, _, got_o = (str(p.get("starts_at_local") or "").partition(" "))
            errori = []
            if (a.get("type") if a else None) != tipo:
                errori.append(f"tipo {a.get('type') if a else None}")
            if tipo:
                if genere and p.get("kind") not in ((genere,) if isinstance(genere, str) else genere):
                    errori.append(f"genere {p.get('kind')}")
                if got_d != data:
                    errori.append(f"data {got_d} ≠ {data}")
                if ora and got_o[:5] != ora:
                    errori.append(f"ora {got_o} ≠ {ora}")
                cid = p.get("case_id")
                if caso and cid != casi_db[caso].id:
                    errori.append("fascicolo mancante" if not cid else "fascicolo sbagliato")
                if not caso and cid:
                    errori.append("fascicolo inventato")
            tot += 1
            punti += not errori
            print(f"{'✓' if not errori else '✗'} [{giur}] {frase[:60]:<60} {'; '.join(errori) or 'ok'}  ({time.time() - t0:.0f} s)")
            if errori:
                print("      risposta:", (r.get("reply") or "")[:160].replace("\n", " "), "| params:", p)
    finally:
        try:
            storage.delete_user(u.username)
        except Exception as exc:  # noqa: BLE001
            print("pulizia:", exc)
    print(f"\nTOTALE: {punti}/{tot}  (oggi {OGGI.isoformat()})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
