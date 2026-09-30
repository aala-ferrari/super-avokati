"""v9.430 — gli eventi creati dalla SEGRETARIA (portale e Telegram) hanno gli stessi avvisi dello scadenziario e avvisano i
colleghi del fascicolo. Database di PROVA (`APP_DB_PATH` su una COPIA), nessun modello: si chiama direttamente execute_action."""
from __future__ import annotations

import os
import sys
import uuid

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src import storage, brain, secretary  # noqa: E402

storage.init_db()
ESITI: list = []


def ok(nome: str, cond: bool, extra: str = "") -> None:
    ESITI.append(cond)
    print(("✓ " if cond else "✗ ") + nome + (f" — {extra}" if extra and not cond else ""))


def avvisi(eid: str) -> tuple[list[int], int]:
    with storage.db() as conn:
        off = sorted(r[0] for r in conn.execute("SELECT offset_minutes FROM reminders WHERE event_id = ?", (eid,)))
        nt = conn.execute("SELECT notify_team FROM events WHERE id = ?", (eid,)).fetchone()[0]
    return off, nt


u = storage.create_user(f"prova.seg.{uuid.uuid4().hex[:6]}", "x", profession="avokat")
try:
    brain.set_request_user(u.id)
    brain.set_request_jurisdiction("AL")
    caso = storage.create_case(u.id, "Kola kundër Bankës", jurisdiction="AL")
    r1 = secretary.execute_action(u.id, {"type": "create_event", "params": {
        "title": "Seanca përgatitore", "kind": "seance", "case_id": caso.id, "starts_at_local": "2099-11-04 10:00"}})
    o1, n1 = avvisi(r1.get("event_id") or "")
    ok("udienza dalla Segretaria: 7/3/1 giorni + 2 ore prima, colleghi avvisati", r1.get("ok") and o1 == [120, 1440, 4320, 10080]
       and n1 == 1, f"{r1} {o1} {n1}")
    r2 = secretary.execute_action(u.id, {"type": "create_event", "params": {
        "title": "Dorëzim dokumentesh", "kind": "dorëzim", "case_id": caso.id, "starts_at_local": "2099-11-20 09:00",
        "all_day": True}})
    o2, _n2 = avvisi(r2.get("event_id") or "")
    ok("deposito senza ora: anche il giorno stesso", o2 == [0, 1440, 4320, 10080], str(o2))
    r3 = secretary.execute_action(u.id, {"type": "create_event", "params": {
        "title": "Takim me klientin", "kind": "takim", "starts_at_local": "2099-11-05 16:00"}})
    o3, n3 = avvisi(r3.get("event_id") or "")
    ok("appuntamento senza fascicolo: giorno prima + 2 ore, nessun collega", o3 == [120, 1440] and n3 == 0, f"{o3} {n3}")
    r4 = secretary.execute_action(u.id, {"type": "create_event", "params": {
        "title": "Seanca", "kind": "seance", "starts_at_local": "2099-11-06 10:00", "reminders": [60]}})
    o4, _n4 = avvisi(r4.get("event_id") or "")
    ok("avvisi chiesti dall'avvocato: si rispettano", o4 == [60], str(o4))
    ok("il prompt non suggerisce più un solo avviso", "parazgjedhje [1440]" not in secretary.SYSTEM_PROMPT
       if hasattr(secretary, "SYSTEM_PROMPT") else True)
finally:
    try:
        storage.delete_user(u.username)
    except Exception as exc:  # noqa: BLE001
        print("pulizia:", exc)

print(f"\n{sum(ESITI)}/{len(ESITI)} ok")
sys.exit(0 if all(ESITI) else 1)
