"""v9.426 — prova del LINK DEGLI AVVISI «superavokati.ai/s/<fascicolo>» su un database di PROVA (client di test di Flask, nessuna
richiesta vera). Si lancia come tools/prova_conferma_telegram.py (container usa-e-getta, `APP_DB_PATH` su una COPIA)."""
from __future__ import annotations

import os
import sys
import uuid
from urllib.parse import unquote

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src import storage  # noqa: E402

storage.init_db()
from src import web  # noqa: E402

ESITI: list = []


def ok(nome: str, cond: bool, extra: str = "") -> None:
    ESITI.append(cond)
    print(("✓ " if cond else "✗ ") + nome + (f" — {extra}" if extra and not cond else ""))


def vai(client, path):
    r = client.get(path)
    return r.status_code, unquote(r.headers.get("Location", ""))


suf = uuid.uuid4().hex[:6]
u1 = storage.create_user(f"prova.link.{suf}", "x", profession="avokat")
u2 = storage.create_user(f"prova.link2.{suf}", "x", profession="avokat")
try:
    storage.set_user_jurisdictions(u1.id, ["AL", "IT"])
    c_al = storage.create_case(u1.id, "Kola", jurisdiction="AL")
    c_it = storage.create_case(u1.id, "Rossi", jurisdiction="IT")
    c_u2 = storage.create_case(u2.id, "Di un altro", jurisdiction="AL")
    app = web.app
    app.config["TESTING"] = True
    anon = app.test_client()
    st, loc = vai(anon, f"/s/{c_al.id}")
    ok("senza sessione → login e ritorno al fascicolo", st == 302 and loc.endswith(f"/login?next=/s/{c_al.id}"), loc)
    st, loc = vai(anon, "/s/../../admin")
    ok("un percorso strano non diventa un 'next'", st in (302, 404) and "admin" not in loc, f"{st} {loc}")

    cl = app.test_client()
    with cl.session_transaction() as s:
        s["user_id"] = u1.id
        s["jurisdiction"] = "AL"
    st, loc = vai(cl, f"/s/{c_al.id}")
    ok("fascicolo suo, stessa giurisdizione → lo scadenziario sul fascicolo", loc.endswith(f"/#scadenze={c_al.id}"), loc)
    st, loc = vai(cl, f"/s/{c_it.id}")
    with cl.session_transaction() as s:
        g = s.get("jurisdiction")
    ok("fascicolo italiano da sessione albanese → la sessione passa all'italiano", loc.endswith(f"/#scadenze={c_it.id}") and g == "IT",
       f"{loc} {g}")
    st, loc = vai(cl, f"/s/{c_u2.id}")
    with cl.session_transaction() as s:
        g2 = s.get("jurisdiction")
    ok("fascicolo di un altro avvocato → solo l'elenco, sessione intatta", loc.endswith("/#scadenze") and g2 == "IT", f"{loc} {g2}")
    st, loc = vai(cl, "/s")
    ok("/s → lo scadenziario", loc.endswith("/#scadenze"), loc)

    storage.set_user_jurisdictions(u1.id, ["AL"])
    with cl.session_transaction() as s:
        s["jurisdiction"] = "AL"
    st, loc = vai(cl, f"/s/{c_it.id}")
    with cl.session_transaction() as s:
        g3 = s.get("jurisdiction")
    ok("giurisdizione non abilitata → nessun cambio di sessione", loc.endswith("/#scadenze") and g3 == "AL", f"{loc} {g3}")
    ok("link degli avvisi", web.link_scadenziario(c_al.id) == f"https://superavokati.ai/s/{c_al.id}"
       and web.link_scadenziario("x/../y") == "https://superavokati.ai/s")
finally:
    for u in (u1, u2):
        try:
            storage.delete_user(u.username)
        except Exception as exc:  # noqa: BLE001
            print("pulizia:", exc)

print(f"\n{sum(ESITI)}/{len(ESITI)} ok")
sys.exit(0 if all(ESITI) else 1)
