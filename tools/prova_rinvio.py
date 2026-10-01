"""v9.440 — prova del RINVIO d'udienza: la nuova udienza «sostituisce» quella in calendario, che alla conferma si CHIUDE (non si
cancella: «RINVIATA al …»); una proposta vecchia non confermata resta ma non spuntata. Nessun modello. DB di PROVA."""
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


u = storage.create_user(f"prova.rin.{uuid.uuid4().hex[:6]}", "x", profession="avokat")
try:
    c = storage.create_case(u.id, "Rossi contro Alfa", jurisdiction="IT")
    vecchio = storage.create_event(u.id, "Udienza di discussione", "seance", "2099-02-18T10:00:00", case_id=c.id,
                                   jurisdiction="IT", reminders=[1440])
    testo = "Il giudice rinvia l'udienza del 18 febbraio 2099 al 15 marzo 2099 ore 10:00 per la discussione."
    est = {"date": [{"tipo": "udienza", "titolo": "Udienza di discussione (rinvio)", "data": "2099-03-15", "ora": "10:00",
                     "citazione": "rinvia l'udienza del 18 febbraio 2099 al 15 marzo 2099 ore 10:00", "rinvio_da": "2099-02-18"},
                    {"tipo": "udienza", "titolo": "Udienza inventata", "data": "2099-04-10",
                     "citazione": "rinvia", "rinvio_da": "2099-01-01"}]}
    proposte, _inn = sz.proposte_da_estrazione(est, testo, lang="it", jurisdiction="IT", oggi="2026-10-01")
    ok("il rinvio si legge (data vecchia scritta nel documento)", proposte[0].get("rinvio_da") == "2099-02-18")
    ok("un rinvio con una data vecchia NON scritta si scarta", proposte[1].get("rinvio_da") == "")
    storage.aggiungi_scadenza_proposta({"case_id": c.id, "user_id": u.id, "tipo": "data", "kind": "seance", "titolo":
                                        "Udienza di discussione", "data": "2099-02-18", "verificato": 1, "origine": "documento",
                                        "chiave": "vecchia", "jurisdiction": "IT"})
    web._scad_salva([dict(proposte[0], verificato=True)], [], case_id=c.id, uid=u.id, doc_id=None, juris="IT")
    tutte = {p["data"]: p for p in storage.lista_scadenze_proposte(case_id=c.id)}
    nuova = tutte.get("2099-03-15") or {}
    ok("la nuova udienza sa quale evento sostituisce", nuova.get("sostituisce_event_id") == vecchio.id, str(nuova)[:200])
    ok("… e lo dice nella nota", "si chiude" in (nuova.get("nota") or ""))
    vp = tutte.get("2099-02-18") or {}
    ok("la proposta vecchia non confermata: non spuntata, con «RINVIATA»", not vp.get("verificato") and "RINVIATA" in (vp.get("nota") or ""),
       str(vp)[:200])
    r = web.conferma_proposta(nuova, u.id, {})
    ev_v = storage.get_event(vecchio.id, u.id)
    ok("alla conferma: nuova udienza in calendario", r.get("ok") and bool(r.get("event_id")))
    ok("… e quella vecchia CHIUSA (non cancellata), col titolo «RINVIATA al 15/03/2099»",
       ev_v is not None and ev_v.done and ev_v.title.startswith("RINVIATA al 15/03/2099"), str(ev_v and (ev_v.done, ev_v.title)))
    ok("l'esito lo riporta", (r.get("chiusa") or {}).get("id") == vecchio.id)
    # v9.453: la PROROGA di un termine salvato come «afat», letta come «dorëzim» → collegata e chiusa
    t_vecchio = storage.create_event(u.id, "Deposito memorie", "afat", "2099-12-10T09:00:00", case_id=c.id, jurisdiction="IT",
                                     all_day=True)
    tp = "proroga il termine per il deposito delle memorie, già fissato al 10 dicembre 2099, al 20 dicembre 2099."
    pp, _i = sz.proposte_da_estrazione({"date": [{"tipo": "deposito", "titolo": "Deposito memorie (prorogato)", "data": "2099-12-20",
                                                  "citazione": tp, "rinvio_da": "2099-12-10"}]}, tp, lang="it", jurisdiction="IT",
                                       oggi="2026-10-01")
    web._scad_salva(pp, [], case_id=c.id, uid=u.id, doc_id=None, juris="IT")
    pr2 = next(p for p in storage.lista_scadenze_proposte(case_id=c.id) if p["data"] == "2099-12-20")
    ok("v9.453: la proroga di un termine è collegata al vecchio anche se letto come deposito",
       pr2.get("sostituisce_event_id") == t_vecchio.id, str(pr2)[:200])
    web.conferma_proposta(pr2, u.id, {})
    tv = storage.get_event(t_vecchio.id, u.id)
    ok("… e alla conferma il termine vecchio si chiude", tv.done and tv.title.startswith("PROROGATO al 20/12/2099"), str((tv.done, tv.title)))
finally:
    try:
        storage.delete_user(u.username)
    except Exception as exc:  # noqa: BLE001
        print("pulizia:", exc)

print(f"\n{sum(ESITI)}/{len(ESITI)} ok")
sys.exit(0 if all(ESITI) else 1)
