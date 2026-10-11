"""v9.623 — prova della PASSWORD DIMENTICATA col codice via email, su un database di PROVA (client di test di Flask; l'email è
simulata: nessuna richiesta vera a Resend). Si lancia come tools/prova_link_scadenze.py (container usa-e-getta, `APP_DB_PATH` su una
COPIA)."""
from __future__ import annotations

import os
import re
import sys
import uuid

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src import storage  # noqa: E402

storage.init_db()
from src import web  # noqa: E402
from src.auth import authenticate, hash_password  # noqa: E402

ESITI: list = []


def ok(nome: str, cond: bool, extra: str = "") -> None:
    ESITI.append(cond)
    print(("✓ " if cond else "✗ ") + nome + (f" — {extra}" if extra and not cond else ""))


POSTA: list = []
web.reminders_mod.manda_email = lambda to, subject, html: POSTA.append((to, subject, html)) or None
web._RESET_SINCRONO = True       # l'invio gira in sottofondo: qui lo si aspetta, per contare le email


def codice_di(html: str) -> str:
    m = re.search(r">(\d{6})<", html or "")
    return m.group(1) if m else ""


suf = uuid.uuid4().hex[:6]
EMAIL = f"prova.reset.{suf}@esempio.it"
u = storage.create_user(EMAIL, hash_password("vecchia-123"))
u2 = storage.create_user(f"mario.rossi.{suf}", hash_password("x-1234567"))
u3 = storage.create_user(f"anna.{suf}", hash_password("x-1234567"))
u4 = storage.create_user(f"luca.{suf}", hash_password("x-1234567"))
try:
    app = web.app
    app.config["TESTING"] = True
    cl = app.test_client()

    def chiedi(email, lang="sq"):
        r = cl.post("/api/password-reset/request", json={"email": email, "lang": lang})
        return r.status_code, (r.get_json(silent=True) or {})

    def conferma(email, code, new, lang="sq"):
        r = cl.post("/api/password-reset/confirm", json={"email": email, "code": code, "new": new, "lang": lang})
        return r.status_code, (r.get_json(silent=True) or {})

    st, d = chiedi(EMAIL.upper())
    ok("la richiesta risponde ok e parte un'email col codice a quell'indirizzo",
       st == 200 and d.get("ok") and len(POSTA) == 1 and POSTA[0][0] == EMAIL and len(codice_di(POSTA[0][2])) == 6,
       f"{st} {d} {[(p[0], p[1]) for p in POSTA]}")
    ok("l'email in albanese, col codice e la nota «se non l'hai chiesto tu»",
       POSTA and "Kodi për fjalëkalimin e ri" in POSTA[0][1] and "injorojeni" in POSTA[0][2])
    c1 = codice_di(POSTA[0][2]) if POSTA else ""
    st, d = chiedi(f"nessuno.{suf}@esempio.it")
    ok("un indirizzo sconosciuto: stessa risposta, nessuna email", st == 200 and d.get("ok") and len(POSTA) == 1)
    st, d = conferma(EMAIL, "000000" if c1 != "000000" else "111111", "nuova-password-1")
    ok("codice sbagliato → 400, la password non cambia", st == 400 and d.get("code") == "bad_code"
       and authenticate(EMAIL, "vecchia-123") is not None, f"{st} {d}")
    st, d = conferma(EMAIL, c1, "corta")
    ok("nuova password corta → 400 (il codice non si consuma)", st == 400 and d.get("code") == "too_short", f"{st} {d}")
    aperto = app.test_client()             # un dispositivo rimasto aperto con la password vecchia
    with aperto.session_transaction() as s:
        s["user_id"] = u.id
    ok("il dispositivo rimasto aperto è dentro prima del recupero", aperto.get("/api/me").status_code == 200)
    st, d = conferma(EMAIL, c1, "nuova-password-1")
    ok("codice giusto → password cambiata, si entra con la nuova",
       st == 200 and d.get("username") == EMAIL and authenticate(EMAIL, "nuova-password-1") is not None
       and authenticate(EMAIL, "vecchia-123") is None, f"{st} {d}")
    ok("dopo il recupero il dispositivo rimasto aperto esce", aperto.get("/api/me").status_code == 401)
    nuovo_login = app.test_client()
    r = nuovo_login.post("/api/login", json={"username": EMAIL, "password": "nuova-password-1"})
    ok("un accesso nuovo dopo il recupero resta dentro", r.status_code == 200 and nuovo_login.get("/api/me").status_code == 200,
       str(r.status_code))
    st, d = conferma(EMAIL, c1, "altra-password-2")
    ok("lo stesso codice non vale due volte", st == 400 and authenticate(EMAIL, "nuova-password-1") is not None, f"{st} {d}")

    web._RESET_RICHIESTE.clear()
    POSTA.clear()
    chiedi(EMAIL, "it")
    chiedi(EMAIL, "it")
    vecchio, nuovo = codice_di(POSTA[0][2]), codice_di(POSTA[1][2])
    ok("l'email in italiano", "Il codice per la nuova password" in POSTA[0][1] and "ignora questa email" in POSTA[0][2])
    st, d = conferma(EMAIL, vecchio, "terza-password-3", "it") if vecchio != nuovo else (400, {})
    ok("un codice nuovo annulla il vecchio (messaggio in italiano)", st == 400 and "Codice non valido" in (d.get("error") or "x")
       or vecchio == nuovo, f"{st} {d}")
    st, d = conferma(EMAIL, nuovo, "terza-password-3", "it")
    ok("l'ultimo codice vale", st == 200 and authenticate(EMAIL, "terza-password-3") is not None, f"{st} {d}")

    web._RESET_RICHIESTE.clear()
    POSTA.clear()
    for _ in range(4):
        chiedi(EMAIL)
    ok("al massimo 3 email l'ora per indirizzo", len(POSTA) == 3, str(len(POSTA)))
    c_scad = codice_di(POSTA[-1][2])
    with storage.db() as conn:
        conn.execute("UPDATE password_resets SET expires_at = '2020-01-01T00:00:00Z' WHERE user_id = ? AND used_at IS NULL", (u.id,))
    st, d = conferma(EMAIL, c_scad, "quarta-password-4")
    ok("un codice scaduto non vale", st == 400 and authenticate(EMAIL, "terza-password-3") is not None, f"{st} {d}")

    # 5 tentativi sbagliati: anche il codice giusto smette di valere (prova sul database, il freno dell'accesso a parte)
    storage.crea_reset_password(u.id, hash_password("424242"))
    from src.auth import verify_password
    esiti = [storage.usa_reset_password(u.id, lambda h: verify_password("999999", h)) for _ in range(5)]
    ok("dopo 5 codici sbagliati la richiesta non vale più",
       esiti == ["sbagliato"] * 5 and storage.usa_reset_password(u.id, lambda h: verify_password("424242", h)) == "nessuno",
       repr(esiti))

    # l'email dei promemoria quando il nome utente non è un'email: solo se è di UN account
    web._RESET_RICHIESTE.clear()
    POSTA.clear()
    storage.set_user_reminder_email(u2.id, f"studio.rossi.{suf}@esempio.it")
    chiedi(f"studio.rossi.{suf}@esempio.it")
    ok("nome utente senza @ → il codice va all'email dei promemoria", len(POSTA) == 1
       and POSTA[0][0] == f"studio.rossi.{suf}@esempio.it", repr([p[0] for p in POSTA]))
    st, d = conferma(f"studio.rossi.{suf}@esempio.it", codice_di(POSTA[0][2]) if POSTA else "", "rossi-nuova-1")
    ok("e il codice cambia la password di quell'account", st == 200 and d.get("username") == u2.username
       and authenticate(u2.username, "rossi-nuova-1") is not None, f"{st} {d}")
    storage.set_user_reminder_email(u3.id, f"condivisa.{suf}@esempio.it")
    storage.set_user_reminder_email(u4.id, f"condivisa.{suf}@esempio.it")
    POSTA.clear()
    chiedi(f"condivisa.{suf}@esempio.it")
    ok("un'email di due account → nessun codice (non si indovina)", POSTA == [], repr(POSTA))
    with storage.db() as conn:
        conn.execute("UPDATE users SET suspended = 1 WHERE id = ?", (u.id,))
    POSTA.clear()
    web._RESET_RICHIESTE.clear()
    chiedi(EMAIL)
    ok("account sospeso → nessun codice", POSTA == [], repr(POSTA))
    ok("la pagina di accesso ha i due passaggi", 'id="forgot-step2"' in cl.get("/login").get_data(as_text=True))
finally:
    for nome in (u.username, u2.username, u3.username, u4.username):
        try:
            storage.delete_user(nome)
        except Exception as exc:  # noqa: BLE001
            print("pulizia:", exc)
    with storage.db() as conn:
        resto = conn.execute("SELECT COUNT(*) AS n FROM password_resets WHERE user_id IN (?, ?)", (u.id, u2.id)).fetchone()["n"]
    ok("cancellando l'utente i codici spariscono", resto == 0, str(resto))

print(f"\n{sum(ESITI)}/{len(ESITI)} ok")
sys.exit(0 if all(ESITI) else 1)
