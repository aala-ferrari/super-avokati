"""v9.424 — prova della CONFERMA DA TELEGRAM su un database di PROVA (mai quello vivo): Telegram simulato, nessun messaggio vero.

Si lancia in un container usa-e-getta con `APP_DB_PATH` su una COPIA del DB:
    docker run --rm -e APP_DB_PATH=/tqa/app.db -v /tmp/tqa:/tqa -v …/data:/app/data:ro <immagine> python3 tools/prova_conferma_telegram.py
Controlla: pulsanti solo sulle proposte verificate e datate · il clic crea l'evento con gli avvisi 7/3/1 · toglie il pulsante
dal messaggio · 🗑 scarta · il secondo clic non crea un doppione · un'altra chat NON può confermare · /afatet porta i pulsanti.
"""
from __future__ import annotations

import os
import sys
import uuid

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src import storage, reminders as rm, telegram_bot as tg  # noqa: E402

INVIATI: list = []      # (chat, testo, tastiera) — dall'avviso
API: list = []          # (metodo, parametri) — dal bot

rm.TELEGRAM_BOT_TOKEN = "prova"
tg.TELEGRAM_BOT_TOKEN = "prova"
rm._send_telegram = lambda chat, testo, tastiera=None: INVIATI.append((chat, testo, tastiera)) or None
rm._email_configured = lambda: False
tg._api = lambda metodo, **p: API.append((metodo, p)) or {"ok": True, "result": {}}

from src import web  # noqa: E402

ESITI: list = []
storage.init_db()          # le migrazioni (v9.425: sollecito_at), come all'avvio dell'app


def ok(nome: str, cond: bool, extra: str = "") -> None:
    ESITI.append(cond)
    print(("✓ " if cond else "✗ ") + nome + (f" — {extra}" if extra and not cond else ""))


def ultimo_testo() -> str:
    for m, p in reversed(API):
        if m == "sendMessage":
            return p.get("text") or ""
    return ""


suf = uuid.uuid4().hex[:6]
u1 = storage.create_user(f"prova.tg.{suf}", "x", profession="avokat")
u2 = storage.create_user(f"prova.tg2.{suf}", "x", profession="avokat")
try:
    storage.set_user_telegram_chat(u1.id, "990001")
    storage.set_user_telegram_chat(u2.id, "990002")
    caso = storage.create_case(u1.id, "Kola kundër Bankës", jurisdiction="AL")
    base = {"case_id": caso.id, "user_id": u1.id, "tipo": "data", "kind": "seance", "verificato": 1,
            "jurisdiction": "AL", "origine": "documento"}
    storage.aggiungi_scadenza_proposta(dict(base, titolo="Seanca përgatitore", data="2099-11-04", ora="10:00", chiave="k1"))
    storage.aggiungi_scadenza_proposta(dict(base, titolo="Dorëzimi i provave", kind="dorëzim", data="2099-11-20", chiave="k2"))
    storage.aggiungi_scadenza_proposta(dict(base, titolo="Afat i paqartë", data="2099-12-01", verificato=0, chiave="k3"))
    storage.aggiungi_scadenza_proposta(dict(base, titolo="Afatet ligjore nga: vendimi", tipo="innesco", data="", chiave="k4"))
    storage.aggiungi_scadenza_proposta(dict(base, titolo="Dorëzimi i relacionit", kind="dorëzim", data="2099-12-15", chiave="k5"))
    nuove = storage.lista_scadenze_proposte(case_id=caso.id)
    web._scad_avvisa_nuove(caso.id, u1.id, "AL", nuove)
    ok("l'avviso è partito su Telegram", len(INVIATI) == 1 and INVIATI[0][0] == "990001")
    tast = INVIATI[0][2] if INVIATI else None
    righe = (tast or {}).get("inline_keyboard") or []
    ok("pulsanti SOLO sulle 3 proposte verificate e datate", len(righe) == 3, str(righe)[:200])
    ok("il testo dice di confermare lì con ✅", "✅" in (INVIATI[0][1] if INVIATI else ""))
    p1 = next(p for p in nuove if p["chiave"] == "k1")
    p2 = next(p for p in nuove if p["chiave"] == "k2")
    msg = {"message_id": 7, "reply_markup": tast}

    # un'ALTRA chat (altro avvocato) prova a confermare la proposta di u1
    tg._conferma_da_telegram("990002", msg, "s:ok:" + p1["id"], u2.id)
    ok("un altro avvocato NON può confermare", storage.get_scadenza_proposta(p1["id"])["stato"] == "proposta"
       and "nuk u gjet" in ultimo_testo().lower())

    tg._conferma_da_telegram("990001", msg, "s:ok:" + p1["id"], u1.id)
    q1 = storage.get_scadenza_proposta(p1["id"])
    ev = storage.get_event(q1.get("event_id") or "", u1.id)
    ok("✅ crea l'evento in calendario", q1["stato"] == "confermata" and ev is not None, str(q1)[:200])
    ok("con gli avvisi 7/3/1 giorni prima", "7, 3, 1 ditë" in ultimo_testo(), ultimo_testo())
    if ev:
        ok("ora locale giusta (10:00 a Tirana)", storage.ora_locale(ev.starts_at, "AL").endswith("10:00")
           or "10:00" in storage.ora_locale(ev.starts_at, "AL"), storage.ora_locale(ev.starts_at, "AL"))
    edit = [p for m, p in API if m == "editMessageReplyMarkup"]
    ok("il pulsante confermato sparisce, gli altri restano",
       bool(edit) and len(edit[-1]["reply_markup"]["inline_keyboard"]) == 2
       and p2["id"] in str(edit[-1]["reply_markup"]))
    with storage.db() as conn:
        off1 = sorted(r[0] for r in conn.execute("SELECT offset_minutes FROM reminders WHERE event_id = ?", (q1["event_id"],)))
    ok("udienza con l'ora: avvisi 7/3/1 giorni e 2 ore prima (v9.429)", off1 == [120, 1440, 4320, 10080], str(off1))
    ok("… e il messaggio lo dice", "2 orë para" in ultimo_testo(), ultimo_testo())
    if ev:
        msg_ev = rm._format_message(ev, type("R", (), {"offset_minutes": 120})())
        ok("il promemoria dice il CLIENTE e porta il link al fascicolo", "Kola kundër Bankës" in msg_ev
           and f"superavokati.ai/s/{caso.id}" in msg_ev, msg_ev)
    p5 = next(p for p in nuove if p["chiave"] == "k5")
    tg._conferma_da_telegram("990001", msg, "s:ok:" + p5["id"], u1.id)
    q5 = storage.get_scadenza_proposta(p5["id"])
    with storage.db() as conn:
        off5 = sorted(r[0] for r in conn.execute("SELECT offset_minutes FROM reminders WHERE event_id = ?", (q5["event_id"],)))
    ok("deposito senza ora: anche il promemoria del giorno stesso", off5 == [0, 1440, 4320, 10080]
       and "ditën e afatit" in ultimo_testo(), f"{off5} {ultimo_testo()}")
    ok("il promemoria del giorno stesso si legge «SOT»",
       rm._fmt_ahead(type("R", (), {"offset_minutes": 0})(), "sq") == "SOT"
       and rm._fmt_ahead(type("R", (), {"offset_minutes": 0})(), "it") == "OGGI")

    n_ev = len(storage.list_events(u1.id))
    tg._conferma_da_telegram("990001", msg, "s:ok:" + p1["id"], u1.id)
    ok("il secondo clic non crea un doppione", len(storage.list_events(u1.id)) == n_ev and "tashmë" in ultimo_testo())

    tg._conferma_da_telegram("990001", msg, "s:no:" + p2["id"], u1.id)
    ok("🗑 scarta la proposta", storage.get_scadenza_proposta(p2["id"])["stato"] == "scartata")

    p3 = next(p for p in nuove if p["chiave"] == "k3")
    tg._conferma_da_telegram("990001", msg, "s:ok:" + p3["id"], u1.id)
    ok("una proposta da verificare non si conferma dal bot", storage.get_scadenza_proposta(p3["id"])["stato"] == "proposta"
       and "portal" in ultimo_testo())

    API.clear()
    tg.gestisci_update({"message": {"chat": {"id": 990001, "type": "private"}, "text": "/afatet"}})
    sm = [p for m, p in API if m == "sendMessage"]
    ok("/afatet elenca e porta i pulsanti (nessuno: l'unica rimasta è da verificare)",
       bool(sm) and "reply_markup" not in sm[-1] and "Afat i paqartë" in sm[-1]["text"], str(sm)[:300])
finally:
    for u in (u1, u2):
        try:
            storage.delete_user(u.username)
        except Exception as exc:  # noqa: BLE001
            print("pulizia:", exc)

print(f"\n{sum(ESITI)}/{len(ESITI)} ok")
sys.exit(0 if all(ESITI) else 1)
