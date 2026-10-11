"""v9.622 — prova del 👍/👎 sulle risposte, del cambio password dell'avvocato e del conto alla rovescia della prova, su un database
di PROVA (client di test di Flask, nessuna richiesta vera; l'avviso al titolare è simulato: niente Telegram, email o notifiche).
Si lancia come tools/prova_link_scadenze.py (container usa-e-getta, `APP_DB_PATH` su una COPIA)."""
from __future__ import annotations

import os
import sys
import time
import uuid

os.environ["FEEDBACK_ALERT_DELAY_S"] = "0.3"

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src import storage  # noqa: E402

storage.init_db()
from src import web  # noqa: E402
from src.auth import authenticate, hash_password  # noqa: E402

ESITI: list = []


def ok(nome: str, cond: bool, extra: str = "") -> None:
    cond = bool(cond)
    ESITI.append(cond)
    print(("✓ " if cond else "✗ ") + nome + (f" — {extra}" if extra and not cond else ""))


AVVISI: list = []
web.reminders_mod.avvisa_utente = lambda uid, titolo, righe, **kw: AVVISI.append((uid, titolo, list(righe), kw)) or []

suf = uuid.uuid4().hex[:6]
u1 = storage.create_user(f"prova.fb.{suf}@esempio.it", hash_password("vecchia-123"), profession="avokat")
u2 = storage.create_user(f"prova.fb2.{suf}@esempio.it", hash_password("x-1234567"), profession="avokat")
adm = storage.create_user(f"prova.fbadm.{suf}@esempio.it", hash_password("y-1234567"), is_admin=True)
prova = None
os.environ["FEEDBACK_ALERT_UID"] = str(adm.id)
try:
    storage.set_user_jurisdictions(u1.id, ["AL", "IT"])
    caso = storage.create_case(u1.id, "Kola — pushim", jurisdiction="AL")
    DOMANDA = "Klienti u pushua pa paralajmërim pas 9 vitesh: brenda sa ditësh bëjmë padi?"
    RISPOSTA = "🔎 **Verifikimi:** nene 3 të verifikuara — ✅\n\nPadia ngrihet brenda 180 ditëve (neni 146 i Kodit të Punës)."
    storage.add_message(caso.id, "user", DOMANDA)
    m_ans = storage.add_message(caso.id, "assistant", RISPOSTA, kind="answer")
    m_err = storage.add_message(caso.id, "assistant", "gabim", kind="error")
    app = web.app
    app.config["TESTING"] = True
    cl = app.test_client()
    with cl.session_transaction() as s:
        s["user_id"] = u1.id
        s["jurisdiction"] = "AL"

    def fb(client, mid, **body):
        r = client.post(f"/api/messages/{mid}/feedback", json=body)
        return r.status_code, (r.get_json(silent=True) or {})

    st, d = fb(cl, m_ans.id, rating=1)
    ok("👍 salvato", st == 200 and d.get("rating") == 1, f"{st} {d}")
    c = cl.get(f"/api/cases/{caso.id}").get_json()
    giudizi = [m.get("feedback") for m in c["messages"] if m["role"] == "assistant"]
    ok("riaprendo il fascicolo il 👍 resta acceso", giudizi[0] == {"rating": 1, "comment": ""}, repr(giudizi))
    st, d = fb(cl, m_ans.id, rating=-1)
    ok("👎 salvato subito (il commento arriva dopo)", st == 200 and d.get("rating") == -1, f"{st} {d}")
    st, d = fb(cl, m_ans.id, rating=-1, comment="Manca il preavviso del neni 143.")
    ok("il commento si aggiunge al 👎", st == 200 and d.get("comment") == "Manca il preavviso del neni 143.", f"{st} {d}")
    time.sleep(1.2)
    ok("un avviso al titolare, col commento, all'amministratore scelto", len(AVVISI) == 1 and AVVISI[0][0] == adm.id
       and any("Manca il preavviso" in r for r in AVVISI[0][2]), repr(AVVISI))
    testo_avviso = " ".join([AVVISI[0][1]] + AVVISI[0][2]) if AVVISI else ""
    ok("nell'avviso NON vanno la domanda né la risposta del fascicolo",
       "pushua" not in testo_avviso and "180" not in testo_avviso and "Kola" not in testo_avviso, testo_avviso)
    fb(cl, m_ans.id, rating=-1, comment="Ancora una riga.")
    time.sleep(1.0)
    ok("un secondo 👎 sulla stessa risposta non riavvisa", len(AVVISI) == 1, repr(len(AVVISI)))
    st, d = fb(cl, m_ans.id, rating=1)
    c = cl.get(f"/api/cases/{caso.id}").get_json()
    giudizi = [m.get("feedback") for m in c["messages"] if m["role"] == "assistant"]
    ok("passando al 👍 il commento del 👎 si toglie", giudizi[0] == {"rating": 1, "comment": ""}, repr(giudizi))
    st, d = fb(cl, m_ans.id, rating=0)
    c = cl.get(f"/api/cases/{caso.id}").get_json()
    ok("0 toglie il giudizio", st == 200 and d.get("rating") == 0
       and [m.get("feedback") for m in c["messages"] if m["role"] == "assistant"][0] is None, f"{st} {d}")
    ok("un voto strano → 400", fb(cl, m_ans.id, rating=5)[0] == 400)
    ok("una domanda dell'avvocato o un errore non si votano → 404",
       fb(cl, m_ans.id - 1, rating=1)[0] == 404 and fb(cl, m_err.id, rating=1)[0] == 404)
    ok("un messaggio che non esiste → 404", fb(cl, 99999999, rating=1)[0] == 404)

    cl2 = app.test_client()
    with cl2.session_transaction() as s:
        s["user_id"] = u2.id
        s["jurisdiction"] = "AL"
    ok("un altro avvocato non vota sul fascicolo altrui → 404", fb(cl2, m_ans.id, rating=-1)[0] == 404)
    with cl.session_transaction() as s:
        s["jurisdiction"] = "IT"
    ok("in sessione italiana il fascicolo albanese non esiste → 404", fb(cl, m_ans.id, rating=1)[0] == 404)
    with cl.session_transaction() as s:
        s["jurisdiction"] = "AL"
    ok("anonimo → 401", app.test_client().post(f"/api/messages/{m_ans.id}/feedback", json={"rating": 1}).status_code == 401)

    fb(cl, m_ans.id, rating=-1, comment="Termine sbagliato.")
    ok("l'elenco per l'amministratore è solo suo → 403 all'avvocato", cl.get("/api/admin/feedback").status_code == 403)
    ca = app.test_client()
    with ca.session_transaction() as s:
        s["user_id"] = adm.id
    j = ca.get("/api/admin/feedback?rating=-1").get_json() or {}
    mio = [x for x in j.get("items", []) if x.get("message_id") == m_ans.id]
    ok("l'amministratore vede chi, la domanda, l'inizio della risposta e il commento",
       len(mio) == 1 and mio[0]["question"] == DOMANDA and "180" in (mio[0]["answer_head"] or "")
       and mio[0]["comment"] == "Termine sbagliato." and mio[0]["username"] == u1.username, repr(mio)[:300])
    ok("riepilogo di 30 giorni", (j.get("summary") or {}).get("giu", 0) >= 1, repr(j.get("summary")))
    storage.set_user_reminder_email(u1.id, "studio@esempio.it")
    r = ca.get("/api/admin/users")
    righe = [x for x in ((r.get_json(silent=True) or {}).get("items") or []) if x.get("id") == u1.id]
    ok("l'elenco degli utenti dell'amministratore risponde, con l'email (era 500 dal v9.248)",
       r.status_code == 200 and righe and righe[0].get("email") == "studio@esempio.it", f"{r.status_code} {righe}")

    # cambio password dell'avvocato
    def pw(client, **body):
        r = client.post("/api/me/password", json=body)
        return r.status_code, (r.get_json(silent=True) or {})
    st, d = pw(cl, current="sbagliata", new="nuova-password-1")
    ok("password attuale sbagliata → 403", st == 403 and d.get("code") == "wrong_current", f"{st} {d}")
    st, d = pw(cl, current="vecchia-123", new="corta")
    ok("nuova password corta → 400", st == 400 and d.get("code") == "too_short", f"{st} {d}")
    st, d = pw(cl, current="vecchia-123", new="vecchia-123")
    ok("nuova uguale alla vecchia → 400", st == 400 and d.get("code") == "same", f"{st} {d}")
    altro = app.test_client()              # lo stesso avvocato su un altro dispositivo
    with altro.session_transaction() as s:
        s["user_id"] = u1.id
        s["jurisdiction"] = "AL"
    ok("l'altro dispositivo è dentro prima del cambio", altro.get("/api/me").status_code == 200)
    st, d = pw(cl, current="vecchia-123", new="nuova-password-1")
    ok("cambio riuscito, si entra con la nuova e non con la vecchia",
       st == 200 and authenticate(u1.username, "nuova-password-1") is not None
       and authenticate(u1.username, "vecchia-123") is None, f"{st} {d}")
    ok("dopo il cambio l'altro dispositivo esce, questo resta dentro",
       altro.get("/api/me").status_code == 401 and cl.get("/api/me").status_code == 200)
    ok("senza sessione → 401", app.test_client().post("/api/me/password", json={"current": "a", "new": "b"}).status_code == 401)

    # la prova: conto alla rovescia, e l'abbonamento che la sostituisce
    prova = f"prova.trial.{suf}@esempio.it"
    storage.provision_account(prova, hash_password("codice-1"), hours=6)
    pu = storage.get_user_by_username(prova)
    storage.attiva_demo(pu.id)
    cp = app.test_client()
    with cp.session_transaction() as s:
        s["user_id"] = pu.id
    me = cp.get("/api/me").get_json() or {}
    sec = (me.get("trial") or {}).get("seconds_left", 0)
    ok("/api/me dà le ore rimaste della prova (72)", 71.9 * 3600 < sec <= 72 * 3600 and me.get("plan") is None, repr(me))
    with storage.db() as conn:
        conn.execute("UPDATE users SET demo_expires_at = '2020-01-01T00:00:00Z' WHERE id = ?", (pu.id,))
    ok("prova scaduta → bloccato", storage.access_block_reason(storage.get_user_by_id(pu.id)) == "demo_expired")
    r = ca.patch(f"/api/admin/users/{pu.id}/plan", json={"months": 1})
    pu2 = storage.get_user_by_id(pu.id)
    ok("l'amministratore dà un mese: la prova sparisce e l'account entra",
       r.status_code == 200 and pu2.demo_expires_at is None and pu2.plan_expires_at
       and storage.access_block_reason(pu2) is None, f"{r.status_code} {pu2}")
    me = cp.get("/api/me").get_json() or {}
    ok("/api/me con un mese di abbonamento: nessun conto alla rovescia", me.get("trial") is None and me.get("plan") is None, repr(me))
    with storage.db() as conn:
        conn.execute("UPDATE users SET plan_expires_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now', '+5 days') WHERE id = ?", (pu.id,))
    me = cp.get("/api/me").get_json() or {}
    ok("abbonamento che scade fra 5 giorni → il conto alla rovescia del rinnovo",
       me.get("trial") is None and 4.9 * 86400 < (me.get("plan") or {}).get("seconds_left", 0) <= 5 * 86400, repr(me))
    from types import SimpleNamespace as _NS
    ok("un abbonamento valido vince su una prova scaduta rimasta scritta",
       storage.access_block_reason(_NS(is_admin=False, suspended=False, demo_expires_at="2020-01-01T00:00:00Z",
                                       plan_expires_at="2099-01-01T00:00:00Z")) is None
       and storage.access_block_reason(_NS(is_admin=False, suspended=False, demo_expires_at="2020-01-01T00:00:00Z",
                                           plan_expires_at=None)) == "demo_expired")
    ok("l'amministratore non ha conto alla rovescia", (ca.get("/api/me").get_json() or {}).get("trial") is None)
finally:
    for nome in [u1.username, u2.username, adm.username] + ([prova] if prova else []):
        try:
            storage.delete_user(nome)
        except Exception as exc:  # noqa: BLE001
            print("pulizia:", exc)
    with storage.db() as conn:
        resto = conn.execute("SELECT COUNT(*) AS n FROM answer_feedback WHERE user_id IN (?, ?, ?)",
                             (u1.id, u2.id, adm.id)).fetchone()["n"]
    ok("cancellando l'utente i suoi giudizi spariscono", resto == 0, str(resto))

print(f"\n{sum(ESITI)}/{len(ESITI)} ok")
sys.exit(0 if all(ESITI) else 1)
