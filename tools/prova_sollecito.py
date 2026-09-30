"""v9.425 — prova del SOLLECITO delle scadenze non confermate su un database di PROVA (mai quello vivo), orari finti, Telegram
simulato. Si lancia come tools/prova_conferma_telegram.py (container usa-e-getta, `APP_DB_PATH` su una COPIA)."""
from __future__ import annotations

import os
import sys
import uuid
from datetime import UTC, datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src import storage, reminders as rm, telegram_bot as tg  # noqa: E402

INVIATI: list = []
rm.TELEGRAM_BOT_TOKEN = "prova"
tg.TELEGRAM_BOT_TOKEN = "prova"
rm._send_telegram = lambda chat, testo, tastiera=None: INVIATI.append((chat, testo, tastiera)) or None
rm._email_configured = lambda: False
ESITI: list = []
storage.init_db()          # la migrazione v9.425 (colonna sollecito_at), come all'avvio dell'app


def ok(nome: str, cond: bool, extra: str = "") -> None:
    ESITI.append(cond)
    print(("✓ " if cond else "✗ ") + nome + (f" — {extra}" if extra and not cond else ""))


suf = uuid.uuid4().hex[:6]
u1 = storage.create_user(f"prova.sol.{suf}", "x", profession="avokat")
u2 = storage.create_user(f"prova.sol2.{suf}", "x", profession="avokat")
try:
    storage.set_user_telegram_chat(u1.id, "990011")
    storage.set_user_telegram_chat(u2.id, "990012")
    with storage.db() as conn:
        conn.execute("UPDATE users SET suspended = 1 WHERE id = ?", (u2.id,))
    caso = storage.create_case(u1.id, "Kola kundër Bankës", jurisdiction="AL")
    caso2 = storage.create_case(u2.id, "Sospeso", jurisdiction="AL")
    vecchio = "2026-09-26T08:00:00Z"
    b = {"case_id": caso.id, "user_id": u1.id, "tipo": "data", "kind": "seance", "verificato": 1, "jurisdiction": "AL",
         "origine": "documento", "created_at": vecchio}
    storage.aggiungi_scadenza_proposta(dict(b, titolo="Seanca përgatitore", data="2026-10-03", ora="10:00", chiave="s1"))
    storage.aggiungi_scadenza_proposta(dict(b, titolo="Seanca e largët", data="2026-10-20", chiave="s2"))
    storage.aggiungi_scadenza_proposta(dict(b, titolo="Afat i kaluar", data="2026-09-29", chiave="s3"))
    storage.aggiungi_scadenza_proposta(dict(b, titolo="Afatet ligjore nga: vendimi i apelit", tipo="innesco", data="", chiave="s4"))
    storage.aggiungi_scadenza_proposta(dict(b, titolo="Afatet ligjore nga: vendimi i gjykatës", tipo="innesco",
                                            data="2026-09-10", chiave="s7"))        # v9.428: data dell'atto, termini mai calcolati
    storage.aggiungi_scadenza_proposta(dict(b, titolo="Afat i ri", data="2026-10-02", chiave="s5",
                                            created_at="2026-09-30T05:30:00Z"))      # nata stamattina: l'avviso è già partito
    storage.aggiungi_scadenza_proposta(dict(b, case_id=caso2.id, user_id=u2.id, titolo="Del sospeso", data="2026-10-02",
                                            chiave="s6"))

    ore6 = datetime(2026, 9, 30, 4, 0, tzinfo=UTC)          # 06:00 a Tirana
    ore9 = datetime(2026, 9, 30, 7, 0, tzinfo=UTC)          # 09:00
    ore7_35 = datetime(2026, 9, 30, 5, 35, tzinfo=UTC)

    testo_b = tg.briefing_testo(u1.id, "sq", ore7_35)
    k_b = tg.briefing_tastiera(u1.id, "sq", ore7_35) or {}
    ok("il mattino elenca per nome quelle non in calendario", "ENDE JO NË KALENDAR" in testo_b and "Seanca përgatitore" in testo_b
       and "Afatet ligjore nga: vendimi" in testo_b and "Seanca e largët" not in testo_b, testo_b)
    ok("il mattino porta i pulsanti ✅ (solo le verificate con data vicina)",
       len(k_b.get("inline_keyboard") or []) == 2, str(k_b)[:200])

    n6 = rm.sollecita_scadenze(ore6)
    ok("alle 6 di mattina nessun sollecito", n6 == 0 and not INVIATI)
    n9 = rm.sollecita_scadenze(ore9)
    ok("alle 9 parte UN sollecito (e non per l'account sospeso)", n9 == 1 and len(INVIATI) == 1 and INVIATI[0][0] == "990011",
       str([c for c, *_ in INVIATI]))
    t = INVIATI[0][1] if INVIATI else ""
    ok("dentro: la data entro 7 giorni e la sentenza senza notifica", "Seanca përgatitore" in t and "pas 3 ditësh" in t
       and "mund të kenë nisur" in t, t)
    ok("dentro anche la sentenza CON la data dell'atto ma termini mai calcolati", "vendimi i gjykatës" in t
       and "ende pa u llogaritur" in t, t)
    ok("fuori: la data lontana, quella passata, quella nata stamattina",
       "Seanca e largët" not in t and "Afat i kaluar" not in t and "Afat i ri" not in t, t)
    righe = ((INVIATI[0][2] if INVIATI else None) or {}).get("inline_keyboard") or []
    ok("un pulsante ✅ sulla sola proposta verificata con data", len(righe) == 1 and "Seanca" in righe[0][0]["text"], str(righe))
    n9b = rm.sollecita_scadenze(datetime(2026, 9, 30, 7, 5, tzinfo=UTC))
    ok("un minuto dopo: niente doppione", n9b == 0 and len(INVIATI) == 1)
    s6 = next(p for p in storage.lista_scadenze_proposte(user_id=u2.id))
    ok("l'account sospeso resta da sollecitare (non segnato)", not s6.get("sollecito_at"))
    lista_bot = tg.da_confermare(u1.id, "sq")
    ok("/afatet: le date passate non si elencano, si contano come storia", "Afat i kaluar" not in lista_bot
       and "data të kaluara" in lista_bot and "vendimi i gjykatës" in lista_bot, lista_bot)
finally:
    for u in (u1, u2):
        try:
            storage.delete_user(u.username)
        except Exception as exc:  # noqa: BLE001
            print("pulizia:", exc)

print(f"\n{sum(ESITI)}/{len(ESITI)} ok")
sys.exit(0 if all(ESITI) else 1)
