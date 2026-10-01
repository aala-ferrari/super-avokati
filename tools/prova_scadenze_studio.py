"""v9.437 — prova degli avvisi delle SCADENZE DA CONFERMARE in uno STUDIO: l'assistente carica il documento, l'avvocato che ha
creato il fascicolo riceve l'avviso e può confermare dal bot; un collega dello studio NON assegnato non riceve niente e non può
confermare. Database di PROVA (`APP_DB_PATH` su una COPIA), Telegram simulato."""
from __future__ import annotations

import os
import sys
import uuid

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src import storage, reminders as rm, telegram_bot as tg  # noqa: E402

storage.init_db()
INVIATI: list = []
API: list = []
rm.TELEGRAM_BOT_TOKEN = "prova"
tg.TELEGRAM_BOT_TOKEN = "prova"
rm._send_telegram = lambda chat, testo, tastiera=None: INVIATI.append((chat, testo, tastiera)) or None
rm._email_configured = lambda: False
tg._api = lambda metodo, **p: API.append((metodo, p)) or {"ok": True, "result": {}}
from src import web  # noqa: E402

ESITI: list = []


def ok(nome: str, cond: bool, extra: str = "") -> None:
    ESITI.append(cond)
    print(("✓ " if cond else "✗ ") + nome + (f" — {extra}" if extra and not cond else ""))


suf = uuid.uuid4().hex[:6]
avv = storage.create_user(f"prova.st.avv.{suf}", "x", profession="avokat")
ass = storage.create_user(f"prova.st.ass.{suf}", "x", profession="avokat")
est = storage.create_user(f"prova.st.est.{suf}", "x", profession="avokat")
utenti = (avv, ass, est)
try:
    for u, chat in zip(utenti, ("991001", "991002", "991003")):
        storage.set_user_telegram_chat(u.id, chat)
    studio = storage.create_firm(f"Studio prova {suf}", avv.id)
    m_ass = storage.add_member(studio.id, ass.id, "assistant")
    storage.add_member(studio.id, est.id, "lawyer")
    caso = storage.create_case(avv.id, "Kola kundër Bankës", firm_id=studio.id, jurisdiction="AL")
    storage.assign_member_to_case(caso.id, m_ass.id)
    storage.aggiungi_scadenza_proposta({"case_id": caso.id, "user_id": ass.id, "tipo": "data", "kind": "seance", "verificato": 1,
                                        "jurisdiction": "AL", "origine": "documento", "titolo": "Seanca përgatitore",
                                        "data": "2099-11-04", "ora": "10:00", "chiave": "st1"})
    nuove = storage.lista_scadenze_proposte(case_id=caso.id)
    web._scad_avvisa_nuove(caso.id, ass.id, "AL", nuove)
    chat = [c for c, *_ in INVIATI]
    ok("l'assistente che ha caricato riceve l'avviso", "991002" in chat)
    ok("l'avvocato che ha creato il fascicolo riceve l'avviso (v9.437)", "991001" in chat, str(chat))
    ok("il collega dello studio NON assegnato non riceve niente", "991003" not in chat, str(chat))
    t_avv = next((t for c, t, _k in INVIATI if c == "991001"), "")
    ok("all'avvocato dice chi ha caricato il documento", "Dokument i ngarkuar nga" in t_avv, t_avv[:200])
    k_avv = next((k for c, _t, k in INVIATI if c == "991001"), None)
    ok("anche l'avvocato ha il pulsante ✅", bool(k_avv and k_avv.get("inline_keyboard")))
    p = nuove[0]
    from datetime import UTC, datetime as _dtm
    ok("v9.438: /afatet dell'avvocato elenca la scadenza caricata dall'assistente",
       "Seanca përgatitore" in tg.da_confermare(avv.id, "sq"))
    ok("v9.438: … e quella del collega non assegnato no", "Seanca përgatitore" not in tg.da_confermare(est.id, "sq"))
    ok("v9.438: il mattino dell'avvocato la conta", "1 afat" in tg.briefing_testo(avv.id, "sq", _dtm(2099, 10, 30, 6, 0, tzinfo=UTC))
       or "Seanca përgatitore" in tg.briefing_testo(avv.id, "sq", _dtm(2099, 10, 30, 6, 0, tzinfo=UTC)))
    tg._conferma_da_telegram("991003", {"message_id": 1, "reply_markup": k_avv}, "s:ok:" + p["id"], est.id)
    ok("il collega non assegnato NON può confermare", storage.get_scadenza_proposta(p["id"])["stato"] == "proposta")
    tg._conferma_da_telegram("991001", {"message_id": 2, "reply_markup": k_avv}, "s:ok:" + p["id"], avv.id)
    q = storage.get_scadenza_proposta(p["id"])
    ok("l'avvocato del fascicolo conferma dal bot", q["stato"] == "confermata" and bool(q.get("event_id")), str(q)[:200])
finally:
    for u in (est, ass, avv):             # il titolare per ultimo: uno studio condiviso non si cancella (v9.241)
        try:
            storage.delete_user(u.username)
        except Exception as exc:  # noqa: BLE001
            print("pulizia:", exc)

print(f"\n{sum(ESITI)}/{len(ESITI)} ok")
sys.exit(0 if all(ESITI) else 1)
