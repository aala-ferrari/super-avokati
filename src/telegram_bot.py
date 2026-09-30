# -*- coding: utf-8 -*-
"""v9.410 — il BOT TELEGRAM di Super Avokati: collegamento a un tocco e comandi minimi.

Prima il collegamento chiedeva all'avvocato il proprio «chat_id» numerico (scrivere a @userinfobot, copiare un numero,
incollarlo): nessuno dei 17 utenti l'aveva fatto, e sul server il bot non esisteva nemmeno. Ora:
  1. l'app crea un CODICE personale monouso (2 giorni, `storage.crea_token_telegram`) e apre
     `https://t.me/<bot>?start=<codice>`;
  2. l'avvocato preme «Avvia»: Telegram manda al nostro webhook «/start <codice>» con il suo chat_id;
  3. il codice diventa l'utente, il chat_id si salva, il bot risponde nella lingua dell'avvocato.
`/stop` scollega. Il webhook vive su una rotta segreta (derivata dal token del bot) e Telegram firma ogni chiamata con
l'intestazione `X-Telegram-Bot-Api-Secret-Token`: una chiamata senza firma giusta non tocca niente.
Senza `TELEGRAM_BOT_TOKEN` tutto è spento e l'interfaccia lo dice.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import threading
import time
import urllib.parse
import urllib.request

from .config import TELEGRAM_BOT_TOKEN
from .logging_utils import get_logger

log = get_logger(__name__)

TG_API = "https://api.telegram.org"
PUBBLICO = os.getenv("SUPERAVOKATI_PUBLIC_URL", "https://superavokati.ai").rstrip("/")
_cache: dict = {}


def attivo() -> bool:
    return bool(TELEGRAM_BOT_TOKEN)


def segreto() -> str:
    """Parte della rotta del webhook e firma attesa da Telegram: derivata dal token, mai scritta da nessuna parte."""
    return hmac.new(TELEGRAM_BOT_TOKEN.encode(), b"superavokati-webhook-v1", hashlib.sha256).hexdigest()[:48]


def _api(metodo: str, **param) -> dict:
    url = f"{TG_API}/bot{TELEGRAM_BOT_TOKEN}/{metodo}"
    dati = urllib.parse.urlencode({k: (json.dumps(v) if isinstance(v, (list, dict)) else v)
                                   for k, v in param.items()}).encode("utf-8")
    with urllib.request.urlopen(urllib.request.Request(url, data=dati, method="POST"), timeout=15) as r:
        return json.loads(r.read().decode("utf-8", errors="ignore"))


def nome_bot() -> str:
    """Lo username del bot (getMe), in cache un'ora: serve a costruire il link t.me."""
    if not attivo():
        return ""
    c = _cache.get("me")
    if c and time.time() - c[1] < 3600:
        return c[0]
    try:
        u = (_api("getMe").get("result") or {}).get("username") or ""
    except Exception as exc:  # noqa: BLE001
        log.warning("telegram getMe: %s", exc)
        return (c or ("", 0))[0]
    _cache["me"] = (u, time.time())
    return u


def link_collegamento(user_id: int) -> str:
    from . import storage
    bot = nome_bot()
    if not bot:
        return ""
    return f"https://t.me/{bot}?start={storage.crea_token_telegram(user_id)}"


def invia(chat_id: str, testo: str) -> bool:
    try:
        return bool(_api("sendMessage", chat_id=chat_id, text=testo, disable_web_page_preview="true").get("ok"))
    except Exception as exc:  # noqa: BLE001
        log.warning("telegram sendMessage: %s", exc)
        return False


def _lingua_utente(user_id: int | None) -> str:
    """L'italiano solo per chi lavora SOLO in Italia; altrimenti albanese (con la riga italiana sotto, se ha anche l'IT)."""
    try:
        from . import storage
        u = storage.get_user_by_id(user_id) if user_id else None
        giur = [g.strip().upper() for g in (getattr(u, "jurisdictions", "") or "AL").split(",") if g.strip()]
        return "it" if giur == ["IT"] else "sq"
    except Exception:  # noqa: BLE001
        return "sq"


_T = {
    "ok": {"sq": "✅ U lidh me Super Avokati. Këtu do të marrësh kujtesat e seancave dhe të afateve të dosjeve.\n"
                 "/sot — agjenda e sotme · /java — 7 ditët · /afatet — për t'u konfirmuar · /stop — shkëput",
           "it": "✅ Collegato a Super Avokati. Qui riceverai gli avvisi di udienze e scadenze dei fascicoli.\n"
                 "/oggi — agenda di oggi · /settimana — 7 giorni · /scadenze — da confermare · /stop — scollega"},
    "ko": {"sq": "⚠️ Kodi nuk vlen ose ka skaduar. Hap Super Avokati → Kalendari → «Lidh Telegram» dhe provo sërish.\n"
                 "⚠️ Codice non valido o scaduto: apri Super Avokati → Calendario → «Collega Telegram» e riprova.",
           "it": "⚠️ Codice non valido o scaduto: apri Super Avokati → Calendario → «Collega Telegram» e riprova."},
    "info": {"sq": "Ky është bot-i i Super Avokati (superavokati.ai). Lidhu nga aplikacioni: Kalendari → «Lidh Telegram».\n"
                   "Questo è il bot di Super Avokati: collegati dall'app → Calendario → «Collega Telegram».",
             "it": "Questo è il bot di Super Avokati: collegati dall'app → Calendario → «Collega Telegram»."},
    "stop": {"sq": "U shkëpute. Nuk do të marrësh më kujtesa këtu.",
             "it": "Scollegato. Non riceverai più avvisi qui."},
    "comandi": {"sq": "Komandat: /sot — seancat dhe afatet e sotme dhe të nesërme · /java — 7 ditët e ardhshme · "
                      "/afatet — afatet nga dokumentet për t'u konfirmuar · /stop — shkëput",
                "it": "Comandi: /oggi — udienze e scadenze di oggi e domani · /settimana — i prossimi 7 giorni · "
                      "/scadenze — scadenze dai documenti da confermare · /stop — scollega"},
}


# v9.416 — COMANDI dell'avvocato collegato: l'agenda e le scadenze da confermare, nella sua lingua e in ORA LOCALE (Tirana/Roma).
# Solo in chat privata e solo per il Telegram collegato a un account (`utente_da_chat_telegram`): nessun dato a chi non è collegato.
_ICONA = {"seance": "⚖️", "afat": "⏰", "dorëzim": "📤", "takim": "🤝", "tjetër": "📌"}
_CMD_OGGI, _CMD_SETT, _CMD_SCAD = {"/oggi", "/sot"}, {"/settimana", "/java"}, {"/scadenze", "/afatet"}


def _titoli_casi(case_ids) -> dict:
    from . import storage
    ids = [c for c in set(case_ids) if c]
    if not ids:
        return {}
    with storage.db() as conn:
        rows = conn.execute("SELECT id, title FROM cases WHERE id IN (" + ",".join("?" * len(ids)) + ")", ids).fetchall()
    return {r["id"]: (r["title"] or "").strip()[:60] for r in rows}


def agenda(uid: int, giorni: int, lang: str) -> str:
    from datetime import datetime, timedelta, timezone
    from . import storage
    it = lang == "it"
    fuso = storage.fuso_di("IT" if it else "AL")
    inizio_loc = datetime.now(fuso).replace(hour=0, minute=0, second=0, microsecond=0)
    da = inizio_loc.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    a = (inizio_loc + timedelta(days=giorni)).astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    eventi = [e for e in storage.list_events(uid, start=da, end=a) if not e.done]
    titoli = _titoli_casi(e.case_id for e in eventi)
    quando = (("oggi e domani" if giorni == 2 else f"i prossimi {giorni} giorni") if it else
              ("sot dhe nesër" if giorni == 2 else f"{giorni} ditët e ardhshme"))
    if not eventi:
        testo = (f"Nessuna udienza o scadenza per {quando}." if it else f"Asnjë seancë apo afat për {quando}.")
    else:
        righe = []
        for e in eventi[:25]:
            g = storage.giurisdizione_evento(e)
            fmt = "%d/%m" if e.all_day else "%d/%m %H:%M"
            caso = titoli.get(e.case_id or "", "")
            righe.append(f"{_ICONA.get(e.kind, '📌')} {storage.ora_locale(e.starts_at, g, fmt)} · {e.title}"
                         + (f" — «{caso}»" if caso else "") + (f" · {e.location}" if e.location else ""))
        testo = (f"📅 Agenda — {quando} ({len(eventi)}):\n" if it else f"📅 Agjenda — {quando} ({len(eventi)}):\n") + "\n".join(righe)
        if len(eventi) > 25:
            testo += f"\n… +{len(eventi) - 25}"
    n = len(storage.lista_scadenze_proposte(user_id=uid, stati=("proposta",)))
    if n:
        testo += (f"\n\n🟡 {n} scadenz{'a' if n == 1 else 'e'} dai documenti da confermare: /scadenze" if it else
                  f"\n\n🟡 {n} afat{'' if n == 1 else 'e'} nga dokumentet për t'u konfirmuar: /afatet")
    return testo


def da_confermare(uid: int, lang: str) -> str:
    from . import storage
    it = lang == "it"
    pr = storage.lista_scadenze_proposte(user_id=uid, stati=("proposta",))
    if not pr:
        return ("Nessuna scadenza da confermare." if it else "Asnjë afat për t'u konfirmuar.")
    titoli = _titoli_casi(p["case_id"] for p in pr)
    per_caso: dict = {}
    for p in pr:
        per_caso.setdefault(p["case_id"], []).append(p)
    righe = []
    for cid, lista in list(per_caso.items())[:8]:
        righe.append(f"\n📁 {titoli.get(cid) or '—'}")
        for p in lista[:6]:
            d = "/".join(reversed(p["data"].split("-"))) if p.get("data") else ("senza data" if it else "pa datë")
            righe.append(f"  {_ICONA.get(p['kind'], '📌')} {d} · {p['titolo'][:90]}" + ("" if p.get("verificato") else " ⚠️"))
    return ((f"🟡 Da confermare ({len(pr)}) — aprili nel fascicolo su superavokati.ai:" if it else
             f"🟡 Për t'u konfirmuar ({len(pr)}) — hapi në dosje te superavokati.ai:") + "\n".join(righe))


def gestisci_update(upd: dict) -> None:
    """Un messaggio arrivato al bot. Mai solleva: il webhook risponde sempre 200 a Telegram (altrimenti ritenta all'infinito)."""
    from . import storage
    try:
        msg = upd.get("message") or upd.get("edited_message") or {}
        chat = msg.get("chat") or {}
        if chat.get("type") != "private":
            return                                    # mai nei gruppi: gli avvisi sono dati riservati del fascicolo
        chat_id = str(chat.get("id") or "")
        testo = (msg.get("text") or "").strip()
        if not chat_id or not testo:
            return
        if testo.startswith("/start"):
            codice = testo.split(maxsplit=1)[1].strip() if len(testo.split(maxsplit=1)) > 1 else ""
            uid = storage.usa_token_telegram(codice) if codice else None
            if uid:
                vecchio = storage.utente_da_chat_telegram(chat_id)
                if vecchio and vecchio != uid:
                    storage.set_user_telegram_chat(vecchio, None)     # un telefono = un avvocato
                storage.set_user_telegram_chat(uid, chat_id)
                invia(chat_id, _T["ok"][_lingua_utente(uid)])
                log.info("telegram: collegato l'utente %s", uid)
            else:
                invia(chat_id, _T["ko"]["sq"] if codice else _T["info"]["sq"])
            return
        if testo.startswith("/stop"):
            uid = storage.utente_da_chat_telegram(chat_id)
            if uid:
                storage.set_user_telegram_chat(uid, None)
            invia(chat_id, _T["stop"][_lingua_utente(uid)])
            return
        uid = storage.utente_da_chat_telegram(chat_id)
        comando = testo.split()[0].split("@")[0].lower()
        if uid and comando in _CMD_OGGI | _CMD_SETT | _CMD_SCAD:
            lg = _lingua_utente(uid)
            if comando in _CMD_SCAD:
                invia(chat_id, da_confermare(uid, lg))
            else:
                invia(chat_id, agenda(uid, 2 if comando in _CMD_OGGI else 7, lg))
            return
        invia(chat_id, (_T["comandi"][_lingua_utente(uid)] if uid else _T["info"]["sq"]))
    except Exception:  # noqa: BLE001
        log.exception("telegram: update non gestito")


def registra_webhook() -> None:
    """Dice a Telegram dove mandare i messaggi (idempotente). Gira in un thread all'avvio: se Telegram non risponde, l'app
    parte lo stesso e si riprova al prossimo avvio."""
    if not attivo():
        return

    def _fai():
        try:
            url = f"{PUBBLICO}/telegram/webhook/{segreto()}"
            r = _api("setWebhook", url=url, secret_token=segreto(), allowed_updates=["message"],
                     drop_pending_updates="true")
            log.info("telegram setWebhook: %s", "ok" if r.get("ok") else r.get("description"))
            try:
                _api("setMyCommands", commands=[
                    {"command": "sot", "description": "Agjenda e sotme dhe e nesërme"},
                    {"command": "java", "description": "7 ditët e ardhshme"},
                    {"command": "afatet", "description": "Afatet për t'u konfirmuar"},
                    {"command": "stop", "description": "Shkëput"}])
                _api("setMyCommands", language_code="it", commands=[
                    {"command": "oggi", "description": "Agenda di oggi e domani"},
                    {"command": "settimana", "description": "I prossimi 7 giorni"},
                    {"command": "scadenze", "description": "Scadenze da confermare"},
                    {"command": "stop", "description": "Scollega"}])
            except Exception:  # noqa: BLE001
                pass
        except Exception as exc:  # noqa: BLE001
            log.warning("telegram setWebhook: %s", exc)

    threading.Thread(target=_fai, name="tg-webhook", daemon=True).start()
