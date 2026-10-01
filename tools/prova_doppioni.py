"""v9.439 — prova dei DOPPIONI fra documenti dello stesso fascicolo (nessun modello: si salvano proposte finte con
`web._scad_salva`). Database di PROVA (`APP_DB_PATH` su una COPIA)."""
from __future__ import annotations

import os
import sys
import uuid

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src import storage  # noqa: E402

storage.init_db()
from src import web, scadenziario as sz  # noqa: E402

ESITI: list = []


def ok(nome: str, cond: bool, extra: str = "") -> None:
    ESITI.append(cond)
    print(("✓ " if cond else "✗ ") + nome + (f" — {extra}" if extra and not cond else ""))


def prop(titolo, data, kind="seance", ora="", **k):
    return dict({"tipo": "data", "kind": kind, "titolo": titolo, "data": data, "ora": ora, "origine": "documento",
                 "citazione": titolo, "verificato": True, "nota": "", "chiave": uuid.uuid4().hex[:20]}, **k)


u = storage.create_user(f"prova.dop.{uuid.uuid4().hex[:6]}", "x", profession="avokat")
try:
    c = storage.create_case(u.id, "Rossi contro Alfa", jurisdiction="IT")
    web._scad_salva([prop("Udienza di precisazione delle conclusioni", "2099-02-18")], [], case_id=c.id, uid=u.id, doc_id=None,
                    juris="IT")
    n2 = web._scad_salva([prop("Rinvio all'udienza per le conclusioni", "2099-02-18", ora="11:00")], [], case_id=c.id, uid=u.id,
                         doc_id=None, juris="IT")
    tutte = storage.lista_scadenze_proposte(case_id=c.id)
    ok("la stessa udienza da un secondo documento non si ripropone", n2 == 0 and len(tutte) == 1, str(len(tutte)))
    ok("… e l'ora del secondo documento completa la prima", tutte[0].get("ora") == "11:00", str(tutte[0].get("ora")))
    web._scad_salva([prop("Deposito delle memorie istruttorie", "2099-03-10", kind="dorëzim"),
                     prop("Deposito delle note di trattazione", "2099-03-10", kind="dorëzim")], [], case_id=c.id, uid=u.id,
                    doc_id=None, juris="IT")
    dep = [p for p in storage.lista_scadenze_proposte(case_id=c.id) if p["data"] == "2099-03-10"]
    ok("due depositi DIVERSI lo stesso giorno restano due", len(dep) == 2, str([p["titolo"] for p in dep]))
    web._scad_salva([prop("Termine per l'opposizione al decreto", "2099-04-01", kind="afat"),
                     prop("Opposizione a decreto ingiuntivo", "2099-04-01", kind="afat", origine="legge")], [], case_id=c.id,
                    uid=u.id, doc_id=None, juris="IT")
    opp = [p for p in storage.lista_scadenze_proposte(case_id=c.id) if p["data"] == "2099-04-01"]
    ok("lo stesso termine dal documento e dalla legge: uno solo", len(opp) == 1, str([p["titolo"] for p in opp]))
    storage.create_event(u.id, "Udienza Rossi (inserita a mano)", "seance", "2099-05-20T09:30:00", case_id=c.id,
                         jurisdiction="IT")
    web._scad_salva([prop("Udienza per l'escussione dei testi", "2099-05-20", ora="09:30")], [], case_id=c.id, uid=u.id,
                    doc_id=None, juris="IT")
    cal = [p for p in storage.lista_scadenze_proposte(case_id=c.id) if p["data"] == "2099-05-20"]
    ok("già in calendario a mano: proposta, ma non spuntata e con la nota", len(cal) == 1 and not cal[0]["verificato"]
       and "forse già in calendario" in (cal[0].get("nota") or ""), str(cal))
    ok("pagare o opporsi al decreto (stesso giorno, due azioni) restano due",
       not sz.stesso_evento({"data": "2099-10-26", "kind": "afat", "titolo": "Termine per il pagamento della somma ingiunta"},
                            {"data": "2099-10-26", "kind": "afat", "titolo": "Termine per proporre opposizione al decreto ingiuntivo"}))
    ok("udienze diverse lo stesso giorno a ore diverse restano due",
       not sz.stesso_evento({"data": "2099-06-01", "kind": "seance", "ora": "09:00"},
                            {"data": "2099-06-01", "kind": "seance", "ora": "12:00"}))
finally:
    try:
        storage.delete_user(u.username)
    except Exception as exc:  # noqa: BLE001
        print("pulizia:", exc)

print(f"\n{sum(ESITI)}/{len(ESITI)} ok")
sys.exit(0 if all(ESITI) else 1)
