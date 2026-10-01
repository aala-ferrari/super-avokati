"""v9.450 — prova di «/chiedi Rossi: …» / «/pyet Kola: …» sul bot: fascicolo riconosciuto dal nome (anche flesso), pulsanti se
manca, mai i fascicoli di un altro avvocato, risposta del Vault nella lingua del fascicolo. Telegram e Vault SIMULATI. DB di PROVA."""
from __future__ import annotations

import os
import sys
import uuid
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src import storage, telegram_bot as tg, vault  # noqa: E402

storage.init_db()
API: list = []
CHIESTE: list = []
tg.TELEGRAM_BOT_TOKEN = "prova"
tg._api = lambda metodo, **p: API.append((metodo, p)) or {"ok": True, "result": {}}
vault.ask = lambda brain, case_id, q: CHIESTE.append((case_id, q)) or {"answer": "Il CTU è l'**ing. Bellini** [Doc 1].",
                                                                        "docs_used": [1], "n_docs": 1}
tg.imposta_cervello(lambda: SimpleNamespace(backend=object()))
ESITI: list = []


def ok(nome: str, cond: bool, extra: str = "") -> None:
    ESITI.append(cond)
    print(("✓ " if cond else "✗ ") + nome + (f" — {extra}" if extra and not cond else ""))


def testi() -> list[str]:
    return [p.get("text", "") for m, p in API if m == "sendMessage"]


suf = uuid.uuid4().hex[:6]
it_u = storage.create_user(f"prova.ch.it.{suf}", "x", profession="avokat")
al_u = storage.create_user(f"prova.ch.al.{suf}", "x", profession="avokat")
altro = storage.create_user(f"prova.ch.x.{suf}", "x", profession="avokat")
try:
    storage.set_user_jurisdictions(it_u.id, ["IT"])
    storage.set_user_telegram_chat(it_u.id, "1")
    rossi = storage.create_case(it_u.id, "Rossi contro Alfa S.p.A.", jurisdiction="IT")
    bianchi = storage.create_case(it_u.id, "Bianchi eredità", jurisdiction="IT")
    kola = storage.create_case(al_u.id, "Kola kundër Bankës", jurisdiction="AL")
    estraneo = storage.create_case(altro.id, "Rossi Mario (di un altro avvocato)", jurisdiction="IT")
    tg._chiedi(it_u.id, "1", "/chiedi Rossi: chi è il consulente tecnico?")
    ok("nome del fascicolo riconosciuto → risposta dal SUO fascicolo", CHIESTE[-1:] == [(rossi.id, "chi è il consulente tecnico?")],
       str(CHIESTE))
    ok("la risposta arriva col titolo e il link, senza asterischi", any("«Rossi contro Alfa S.p.A.»" in t and "ing. Bellini" in t
       and "**" not in t and f"/s/{rossi.id}" in t for t in testi()), str(testi()[-1:]))
    ok("mai il fascicolo di un altro avvocato", all(c != estraneo.id for c, _q in CHIESTE))
    tg._chiedi(al_u.id, "2", "/pyet Kolës: kush është eksperti?")
    ok("forma flessa albanese («Kolës» → Kola)", CHIESTE[-1][0] == kola.id, str(CHIESTE[-1]))
    API.clear()
    n = len(CHIESTE)
    tg._chiedi(it_u.id, "1", "/chiedi quando scade il termine?")
    kb = next((p.get("reply_markup") for m, p in API if m == "sendMessage" and p.get("reply_markup")), None)
    ok("senza nome: pulsanti per scegliere il fascicolo (solo i suoi)", kb and len(kb["inline_keyboard"]) == 2 and len(CHIESTE) == n,
       str(kb))
    dati = kb["inline_keyboard"][0][0]["callback_data"] if kb else ""
    tg._gestisci_callback({"id": "x", "data": dati, "message": {"chat": {"id": 1}, "message_id": 5}})
    ok("scelto col pulsante → risposta dal fascicolo scelto (sessione italiana)", len(CHIESTE) == n + 1
       and CHIESTE[-1][0] in (rossi.id, bianchi.id) and CHIESTE[-1][1] == "quando scade il termine?", str(CHIESTE[-1:]))
    tg._gestisci_callback({"id": "y", "data": dati, "message": {"chat": {"id": 1}, "message_id": 5}})
    ok("il pulsante vale una volta sola", len(CHIESTE) == n + 1 and "scaduta" in (testi()[-1] if testi() else ""))
    tg._chiedi(it_u.id, "1", "/chiedi")
    ok("senza domanda: spiega come si usa", "/chiedi Rossi:" in testi()[-1])
finally:
    for u in (it_u, al_u, altro):
        try:
            storage.delete_user(u.username)
        except Exception as exc:  # noqa: BLE001
            print("pulizia:", exc)

print(f"\n{sum(ESITI)}/{len(ESITI)} ok")
sys.exit(0 if all(ESITI) else 1)
