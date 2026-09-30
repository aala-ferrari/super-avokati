"""Background reminder scheduler.

Polls the reminders table every ``POLL_SECONDS`` and delivers anything
whose ``fire_at`` has passed. Two channels are supported:

* **WhatsApp** (Meta Cloud API) — proactive/business-initiated messages
  must use a *pre-approved template* (24h-window rule), so we send a
  template with 3 body params: {{1}}=sa para, {{2}}=titulli, {{3}}=kur.
  Requires WHATSAPP_TOKEN + WHATSAPP_PHONE_NUMBER_ID + WHATSAPP_TEMPLATE_NAME.
* **Telegram** (Bot API sendMessage) — free-form Markdown, needs
  TELEGRAM_BOT_TOKEN and a linked chat_id.

Per reminder we pick: the reminder's own ``channel`` if that channel is
linked+configured, else WhatsApp if the user linked a number, else
Telegram. Reminders for users with no linked channel are marked
sent-with-error so the scheduler doesn't keep retrying.

Direct HTTPS POSTs (not the python-telegram-bot Application loop) keep the
scheduler decoupled from the bot's event loop and safe inside Flask.
"""
from __future__ import annotations

import json
import logging
import re
import threading
import urllib.error
import urllib.parse
import urllib.request
from datetime import UTC, datetime

from html import escape as _html_escape

from . import storage
from .config import (
    REMINDER_EMAIL_FROM,
    RESEND_API_KEY,
    TELEGRAM_BOT_TOKEN,
    WHATSAPP_PHONE_NUMBER_ID,
    WHATSAPP_TEMPLATE_LANG,
    WHATSAPP_TEMPLATE_NAME,
    WHATSAPP_TOKEN,
)

from .logging_utils import get_logger  # v9.337: getLogger(__name__) non aveva handler → INFO persi
log = get_logger(__name__)

POLL_SECONDS = 60
TG_API = "https://api.telegram.org"
WA_API = "https://graph.facebook.com/v21.0"
RESEND_API = "https://api.resend.com/emails"
_KIND_EMOJI = {
    "seance": "⚖️",
    "afat": "🔴",
    "takim": "👤",
    "dorëzim": "📨",
    "tjetër": "📌",
}


_thread: threading.Thread | None = None
_stop = threading.Event()


def _wa_configured() -> bool:
    return bool(WHATSAPP_TOKEN and WHATSAPP_PHONE_NUMBER_ID and WHATSAPP_TEMPLATE_NAME)


def _email_configured() -> bool:
    return bool(RESEND_API_KEY and REMINDER_EMAIL_FROM)


# ── formatting helpers (shared by both channels) ──────────────────────────

def _fmt_when(event) -> str:
    # v9.414: in ORA LOCALE della giurisdizione (Tirana / Roma, con l'ora legale). Prima `astimezone()` usava il fuso del
    # container, che è UTC: un'udienza delle 10:00 arrivava nell'avviso come «08:00»
    try:
        g = storage.giurisdizione_evento(event)
    except Exception:  # noqa: BLE001
        g = getattr(event, "jurisdiction", None)
    fmt = "%d/%m/%Y" if getattr(event, "all_day", False) else "%d/%m/%Y %H:%M"
    when = storage.ora_locale(event.starts_at, g, fmt)
    if event.location:
        when = f"{when} · {event.location}"
    return when


def _lingua(event) -> str:
    """v9.395 — il promemoria parla la lingua della giurisdizione dell'EVENTO (quella del suo
    fascicolo): prima era sempre albanese, anche per gli avvocati italiani."""
    try:
        from . import storage as _st
        return "it" if _st.giurisdizione_evento(event) == "IT" else "sq"
    except Exception:  # noqa: BLE001
        return "sq"


_T_PROMEMORIA = {
    "sq": {"kujtese": "Kujtesë", "auto": "Super Avokati · kujtesë automatike e agjendës"},
    "it": {"kujtese": "Promemoria", "auto": "Super Avokati · promemoria automatico dell'agenda"},
}


def _fmt_ahead(reminder, lang: str = "sq") -> str:
    off = reminder.offset_minutes
    if off <= 0:                                   # v9.429: il promemoria del giorno stesso (alle 9, per le scadenze senza ora)
        return "OGGI" if lang == "it" else "SOT"
    if lang == "it":
        if off >= 1440:
            days = off // 1440
            return f"{days} giorni prima" if days > 1 else "1 giorno prima"
        if off >= 60:
            hours = off // 60
            return f"{hours} ore prima" if hours > 1 else "1 ora prima"
        return f"{off} minuti prima"
    if off >= 1440:
        days = off // 1440
        return f"{days} ditë para" if days > 1 else "1 ditë para"
    if off >= 60:
        hours = off // 60
        return f"{hours} orë para" if hours > 1 else "1 orë para"
    return f"{off} minuta para"


def _md_escape(s: str) -> str:
    return s.replace("_", r"\_").replace("*", r"\*").replace("[", r"\[").replace("`", r"\`")


def _caso_di(event) -> tuple[str, str]:
    """v9.429 — (titolo del fascicolo, link che lo apre) per un evento: il promemoria diceva «Udienza — 04/11 10:00» e un
    avvocato con trenta clienti non sapeva di chi fosse."""
    cid = getattr(event, "case_id", None)
    if not cid:
        return "", ""
    try:
        with storage.db() as conn:
            r = conn.execute("SELECT title FROM cases WHERE id = ?", (cid,)).fetchone()
        titolo = ((r["title"] if r else "") or "").strip()[:80]
    except Exception:  # noqa: BLE001
        titolo = ""
    return titolo, "https://superavokati.ai/s/" + cid


def _format_message(event, reminder) -> str:
    """Telegram Markdown message."""
    emoji = _KIND_EMOJI.get(event.kind, "📌")
    _lg = _lingua(event)
    caso, link = _caso_di(event)
    lines = [
        f"{emoji} *{_T_PROMEMORIA[_lg]['kujtese']}* ({_fmt_ahead(reminder, _lg)})",
        f"*{_md_escape(event.title)}*",
        f"🗓 {_md_escape(_fmt_when(event))}",
    ]
    if caso:
        lines.append(f"📁 {_md_escape(caso)}")
    if getattr(event, "location", None):
        lines.append(f"📍 {_md_escape(event.location)}")
    if event.description:
        snippet = event.description.strip().splitlines()[0][:200]
        lines.append(f"\n{_md_escape(snippet)}")
    if link:
        lines.append(f"\n{_md_escape(link)}")
    return "\n".join(lines)


# ── Telegram channel ──────────────────────────────────────────────────────

def _send_telegram(chat_id: str, text: str, tastiera: dict | None = None) -> str | None:
    if not TELEGRAM_BOT_TOKEN:
        return "TELEGRAM_BOT_TOKEN not set"
    url = f"{TG_API}/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    campi = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "Markdown",
        "disable_web_page_preview": "true",
    }
    if tastiera:                                   # v9.424: i pulsanti ✅ sotto l'avviso delle scadenze da confermare
        campi["reply_markup"] = json.dumps(tastiera)
    payload = urllib.parse.urlencode(campi).encode("utf-8")
    req = urllib.request.Request(url, data=payload, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8", errors="ignore"))
            if not data.get("ok"):
                return f"telegram error: {data.get('description', 'unknown')}"
            return None
    except urllib.error.HTTPError as e:
        try:
            err_body = e.read().decode("utf-8", errors="ignore")
        except Exception:  # noqa: BLE001
            err_body = str(e)
        return f"http {e.code}: {err_body[:200]}"
    except Exception as e:  # noqa: BLE001
        return f"{type(e).__name__}: {str(e)[:200]}"


# ── WhatsApp channel (Meta Cloud API, template message) ───────────────────

def _send_whatsapp(phone: str, event, reminder) -> str | None:
    if not _wa_configured():
        return "whatsapp not configured"
    to = re.sub(r"[^\d]", "", phone or "")
    if not to:
        return "invalid whatsapp phone"
    params = [_fmt_ahead(reminder), event.title or "Kujtesë", _fmt_when(event)]
    url = f"{WA_API}/{WHATSAPP_PHONE_NUMBER_ID}/messages"
    payload = json.dumps({
        "messaging_product": "whatsapp",
        "to": to,
        "type": "template",
        "template": {
            "name": WHATSAPP_TEMPLATE_NAME,
            "language": {"code": WHATSAPP_TEMPLATE_LANG or "sq"},
            "components": [{
                "type": "body",
                "parameters": [{"type": "text", "text": p[:1000]} for p in params],
            }],
        },
    }).encode("utf-8")
    req = urllib.request.Request(
        url, data=payload, method="POST",
        headers={"Authorization": f"Bearer {WHATSAPP_TOKEN}",
                 "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8", errors="ignore"))
            if data.get("messages"):
                return None
            return f"whatsapp error: {str(data)[:200]}"
    except urllib.error.HTTPError as e:
        try:
            err_body = e.read().decode("utf-8", errors="ignore")
        except Exception:  # noqa: BLE001
            err_body = str(e)
        return f"http {e.code}: {err_body[:250]}"
    except Exception as e:  # noqa: BLE001
        return f"{type(e).__name__}: {str(e)[:200]}"


# ── Email channel (Resend HTTP API, per-studio recipient) ─────────────────

def _send_email(to_email: str, event, reminder) -> str | None:
    if not _email_configured():
        return "email not configured"
    to = (to_email or "").strip()
    if "@" not in to:
        return "invalid email"
    _lg = _lingua(event)
    _TP = _T_PROMEMORIA[_lg]
    ahead = _fmt_ahead(reminder, _lg)
    when = _fmt_when(event)
    title = event.title or _TP["kujtese"]
    kind = _KIND_EMOJI.get(event.kind, "📌")
    caso, link = _caso_di(event)
    desc = ""
    if event.description:
        snippet = event.description.strip().splitlines()[0][:300]
        desc = f'<p style="color:#555;margin:10px 0 0">{_html_escape(snippet)}</p>'
    subject = f"⏰ {_TP['kujtese']} ({ahead}): {title}" + (f" — {caso}" if caso else "")
    html = (
        '<div style="font-family:Georgia,serif;max-width:520px;margin:0 auto;color:#1a1a1a">'
        '<div style="background:#0f2540;color:#f3e6c4;padding:14px 18px;border-radius:12px 12px 0 0">'
        f'<b>{kind} {_TP["kujtese"]}</b> · {_html_escape(ahead)}</div>'
        '<div style="border:1px solid #e3d3a5;border-top:none;border-radius:0 0 12px 12px;padding:16px 18px">'
        f'<h2 style="margin:0 0 6px;color:#0f2540">{_html_escape(title)}</h2>'
        f'<p style="margin:0;color:#6b5836">🗓 {_html_escape(when)}</p>'
        + (f'<p style="margin:6px 0 0;color:#0f2540">📁 {_html_escape(caso)}</p>' if caso else "")
        + (f'<p style="margin:6px 0 0;color:#6b5836">📍 {_html_escape(event.location)}</p>' if getattr(event, "location", None) else "")
        + f'{desc}'
        + (f'<p style="margin:14px 0 0"><a href="{_html_escape(link)}">{_html_escape(link)}</a></p>' if link else "")
        +         f'<p style="margin:16px 0 0;font-size:12px;color:#999">{_TP["auto"]}</p>'
        '</div></div>'
    )
    payload = json.dumps({
        "from": REMINDER_EMAIL_FROM,
        "to": [to],
        "subject": subject,
        "html": html,
    }).encode("utf-8")
    req = urllib.request.Request(
        RESEND_API, data=payload, method="POST",
        headers={"Authorization": f"Bearer {RESEND_API_KEY}",
                 "Content-Type": "application/json",
                 "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                               "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"},
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8", errors="ignore"))
            if data.get("id"):
                return None
            return f"resend error: {str(data)[:200]}"
    except urllib.error.HTTPError as e:
        try:
            err_body = e.read().decode("utf-8", errors="ignore")
        except Exception:  # noqa: BLE001
            err_body = str(e)
        return f"http {e.code}: {err_body[:250]}"
    except Exception as e:  # noqa: BLE001
        return f"{type(e).__name__}: {str(e)[:200]}"


# ── channel selection ─────────────────────────────────────────────────────

def avvisa_utente(uid: int, titolo: str, righe: list[str], *, lang: str = "sq", link: str = "",
                  coda: str = "", tastiera: dict | None = None, coda_tastiera: str = "") -> list[tuple[str, str | None]]:
    """v9.415 — un avviso che NON è un promemoria di un evento (lo scadenziario ha trovato scadenze da confermare): stessi canali
    collegati dell'utente, Telegram ed email. Mai solleva. v9.424: `coda` = l'ultima riga (email, e Telegram senza pulsanti);
    su Telegram con `tastiera` l'ultima riga è `coda_tastiera` (i pulsanti ✅ per confermare lì)."""
    esiti: list[tuple[str, str | None]] = []
    try:
        tg_chat = storage.get_user_telegram_chat(uid)
        if tg_chat:
            ultima = (coda_tastiera or coda) if tastiera else coda
            testo = ("*" + _md_escape(titolo) + "*\n" + "\n".join("• " + _md_escape(r) for r in righe)
                     + (("\n\n" + _md_escape(ultima)) if ultima else ""))
            if link:
                testo += "\n\n" + _md_escape(link)
            esiti.append(("telegram", _send_telegram(tg_chat, testo, tastiera)))
        email = storage.get_user_reminder_email(uid) if _email_configured() else None
        if email and "@" in email and not email.strip().lower().endswith(".test"):   # account di prova: mai email vere
            corpo = "".join(f'<li style="margin:4px 0">{_html_escape(r)}</li>' for r in righe)
            html = ('<div style="font-family:Georgia,serif;max-width:560px;margin:0 auto;color:#1a1a1a">'
                    '<div style="background:#0f2540;color:#f3e6c4;padding:14px 18px;border-radius:12px 12px 0 0"><b>'
                    + _html_escape(titolo) + '</b></div>'
                    '<div style="border:1px solid #e3d3a5;border-top:none;border-radius:0 0 12px 12px;padding:16px 18px">'
                    f'<ul style="padding-left:18px;margin:0">{corpo}</ul>'
                    + (f'<p style="margin:12px 0 0">{_html_escape(coda)}</p>' if coda else "")
                    + (f'<p style="margin:14px 0 0"><a href="{_html_escape(link)}">{_html_escape(link)}</a></p>' if link else "")
                    + f'<p style="margin:16px 0 0;font-size:12px;color:#999">{_T_PROMEMORIA.get(lang, _T_PROMEMORIA["sq"])["auto"]}</p>'
                    '</div></div>')
            payload = json.dumps({"from": REMINDER_EMAIL_FROM, "to": [email.strip()], "subject": titolo, "html": html}).encode("utf-8")
            req = urllib.request.Request(RESEND_API, data=payload, method="POST",
                                         headers={"Authorization": f"Bearer {RESEND_API_KEY}", "Content-Type": "application/json",
                                                  "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                                                                "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"})
            try:
                with urllib.request.urlopen(req, timeout=15) as resp:
                    ok = bool(json.loads(resp.read().decode("utf-8", errors="ignore")).get("id"))
                esiti.append(("email", None if ok else "resend: nessun id"))
            except Exception as exc:  # noqa: BLE001
                esiti.append(("email", f"{type(exc).__name__}: {str(exc)[:150]}"))
    except Exception as exc:  # noqa: BLE001
        log.warning("avvisa_utente %s: %s", uid, exc)
    return esiti


# v9.425 — IL SOLLECITO delle scadenze non confermate. Una proposta dello scadenziario entra in calendario (e riceve i promemoria)
# SOLO dopo il clic dell'avvocato: se il clic non arriva, la scadenza passa in silenzio. Una volta sola per proposta (colonna
# `sollecito_at`, segnata PRIMA dell'invio), in orario d'ufficio locale, su tutti i canali (Telegram coi pulsanti ✅, email):
#   · una proposta CON data che cade entro 7 giorni (mai una data passata);
#   · una proposta SENZA data (manca la notifica della sentenza o la data da cui decorre) ferma da 2 giorni — i termini per
#     impugnare possono già correre.
ORA_SOLLECITO = (8, 0)
FINE_SOLLECITO = (20, 0)
GIORNI_SOLLECITO = 7


def _scelte_sollecito(proposte: list[dict], oggi: str, fino: str, due_giorni_fa: str) -> list[dict]:
    out = []
    for p in proposte:
        if p.get("data") and p.get("tipo") != "innesco":
            if oggi <= p["data"] <= fino:
                out.append(p)
        elif (p.get("created_at") or "") < due_giorni_fa:
            # senza data, o termini di legge mai calcolati (la data di un «innesco» è quella dell'atto, sempre passata:
            # proprio lì i termini per impugnare possono già correre)
            out.append(p)
    return out


def _riga_sollecito(p: dict, oggi: str, it: bool) -> str:
    from datetime import date as _d
    if p.get("data") and p.get("tipo") != "innesco":
        gg = (_d.fromisoformat(p["data"]) - _d.fromisoformat(oggi)).days
        quando = (("OGGI" if gg == 0 else "domani" if gg == 1 else f"fra {gg} giorni") if it else
                  ("SOT" if gg == 0 else "nesër" if gg == 1 else f"pas {gg} ditësh"))
        d = "/".join(reversed(p["data"].split("-")))
        return (f"{d}{(' ' + p['ora']) if p.get('ora') else ''} · {p['titolo']} — {quando}"
                + ("" if p.get("verificato") else (" (da verificare)" if it else " (për t'u verifikuar)")))
    if p.get("tipo") == "innesco":
        if p.get("data"):
            return p["titolo"] + ((" — termini di legge non ancora calcolati: potrebbero già decorrere" if it else
                                   " — afatet ligjore ende pa u llogaritur: mund të kenë nisur tashmë"))
        return p["titolo"] + ((" — manca la data di notifica: i termini per impugnare potrebbero già decorrere" if it else
                               " — mungon data e njoftimit: afatet e ankimit mund të kenë nisur tashmë"))
    return p["titolo"] + (" — manca la data da cui decorre il termine" if it else " — mungon data nga e cila nis afati")


def sollecita_scadenze(adesso: datetime | None = None) -> int:
    """Chiamato dal ciclo dei promemoria (ogni minuto). Restituisce a quanti avvocati è partito un sollecito."""
    from datetime import timedelta
    from . import telegram_bot as _tg
    adesso = adesso or datetime.now(UTC)
    z = lambda d: d.strftime("%Y-%m-%dT%H:%M:%SZ")
    gruppi: dict = {}
    for p in storage.proposte_da_sollecitare(z(adesso - timedelta(days=1))):
        gruppi.setdefault((p["user_id"], (p.get("jurisdiction") or "AL").upper()), []).append(p)
    inviati = 0
    for (uid, giur), lista in gruppi.items():
        try:
            loc = adesso.astimezone(storage.fuso_di(giur))
            if not (ORA_SOLLECITO <= (loc.hour, loc.minute) < FINE_SOLLECITO):
                continue
            oggi = loc.strftime("%Y-%m-%d")
            scelte = _scelte_sollecito(lista, oggi, (loc + timedelta(days=GIORNI_SOLLECITO)).strftime("%Y-%m-%d"),
                                       z(adesso - timedelta(days=2)))
            if not scelte:
                continue
            ut = storage.get_user_by_id(uid)
            scad = [getattr(ut, "plan_expires_at", None), getattr(ut, "demo_expires_at", None)] if ut else []
            if ut is None or getattr(ut, "suspended", False) or any(x and x < z(adesso) for x in scad):
                continue                                  # account sospeso o scaduto: nessun avviso (e resta da fare)
            storage.segna_sollecito([p["id"] for p in scelte], z(adesso))     # PRIMA dell'invio: mai due volte
            it = giur == "IT"
            titoli: dict = {}
            with storage.db() as conn:
                for cid in {p["case_id"] for p in scelte}:
                    r = conn.execute("SELECT title FROM cases WHERE id = ?", (cid,)).fetchone()
                    titoli[cid] = ((r["title"] if r else "") or "—").strip()[:60]
            righe = []
            for cid in dict.fromkeys(p["case_id"] for p in scelte):
                for p in [q for q in scelte if q["case_id"] == cid][:6]:
                    righe.append(f"«{titoli[cid]}»: " + _riga_sollecito(p, oggi, it))
            n = len(scelte)
            tit = ((f"⚠️ {n} scadenz{'a' if n == 1 else 'e'} dai documenti NON ancora in calendario") if it else
                   (f"⚠️ {n} afat{'' if n == 1 else 'e'} nga dokumentet ENDE jo në kalendar"))
            coda = ("Finché non le confermi non ricevi i promemoria: aprile nel fascicolo su Super Avokati." if it else
                    "Derisa t'i konfirmosh nuk merr kujtesat: hapi në dosje te Super Avokati.")
            tastiera = _tg.tastiera_proposte(scelte, "it" if it else "sq", oggi) if _tg.attivo() else None
            coda_t = ("Conferma qui sotto con ✅ quelle verificate (🗑 per scartare); le altre nel fascicolo. Finché non le "
                      "confermi non ricevi i promemoria." if it else
                      "Konfirmo më poshtë me ✅ ato të verifikuara (🗑 për t'i hedhur poshtë); të tjerat në dosje. Derisa t'i "
                      "konfirmosh nuk merr kujtesat.")
            _casi_s = list(dict.fromkeys(p["case_id"] for p in scelte))
            link = "https://superavokati.ai/s" + (("/" + _casi_s[0]) if len(_casi_s) == 1 else "")   # v9.426: dritto al cliente
            esiti = avvisa_utente(uid, tit, righe, lang="it" if it else "sq", link=link,
                                  coda=coda, tastiera=tastiera, coda_tastiera=coda_t)
            if any(e is None for _c, e in esiti):
                inviati += 1
            log.info("sollecito scadenze non confermate: utente %s, %d proposte → %s", uid, n, [(c, e is None) for c, e in esiti])
        except Exception as exc:  # noqa: BLE001
            log.warning("sollecito %s: %s", uid, exc)
    return inviati


def _consegna(uid: int, event, reminder, *, da_chi: str = "") -> list[tuple[str, str | None]]:
    """I canali collegati di UN utente: [(canale, errore o None)]. `da_chi` = il collega che ha messo l'evento in calendario
    (per chi riceve l'avviso come collega dello studio)."""
    wa_phone = storage.get_user_whatsapp(uid) if _wa_configured() else None
    tg_chat = storage.get_user_telegram_chat(uid)
    email = storage.get_user_reminder_email(uid) if _email_configured() else None
    if email and email.strip().lower().endswith(".test"):
        email = None                                  # account di prova (…@superavokati.test): mai email vere
    esiti = []
    if wa_phone:
        esiti.append(("whatsapp", _send_whatsapp(wa_phone, event, reminder)))
    if tg_chat:
        testo = _format_message(event, reminder)
        if da_chi:
            testo = ("👥 _" + _md_escape(("Fascicolo dello studio · in calendario per " if _lingua(event) == "it"
                                          else "Dosje e studios · në kalendar nga ") + da_chi) + "_\n") + testo
        esiti.append(("telegram", _send_telegram(tg_chat, testo)))
    if email:
        esiti.append(("email", _send_email(email, event, reminder)))
    return esiti


def _deliver(event, reminder) -> str | None:
    pref = (getattr(reminder, "channel", "") or "").strip().lower()
    if pref == "whatsapp" and _wa_configured() and storage.get_user_whatsapp(event.user_id):
        return _send_whatsapp(storage.get_user_whatsapp(event.user_id), event, reminder)
    # «telegram» è il canale scritto di default su OGNI promemoria (storage.create_event): non è una scelta, si va su tutti
    if pref == "email" and _email_configured() and storage.get_user_reminder_email(event.user_id):
        return _send_email(storage.get_user_reminder_email(event.user_id), event, reminder)
    # v9.410 — su TUTTI i canali collegati, non sul primo: un avviso doppio costa poco, una scadenza persa costa la causa
    # (e un canale può cadere in silenzio: un bot bloccato, una casella piena). Riuscito = almeno uno è arrivato.
    esiti = _consegna(event.user_id, event, reminder)
    # v9.412 — «avvisa anche i colleghi dello studio»: chi ha creato il fascicolo e gli assegnati, ricalcolati ADESSO con le
    # regole di visibilità (chi è stato tolto dal fascicolo non riceve più niente). Un collega senza canali non è un errore.
    if getattr(event, "notify_team", False) and event.case_id:
        try:
            colleghi = storage.colleghi_del_fascicolo(event.case_id, event.user_id)
            if colleghi:
                u = storage.get_user_by_id(event.user_id)
                da_chi = (getattr(u, "display_name", "") or getattr(u, "username", "") or "").strip()
                for cu in colleghi:
                    esiti += [(f"{c}@{cu}", e) for c, e in _consegna(cu, event, reminder, da_chi=da_chi)]
        except Exception as exc:  # noqa: BLE001
            log.warning("reminder %s: avvisi ai colleghi non partiti: %s", getattr(reminder, "id", "?"), exc)
    if not esiti:
        return "no channel linked (whatsapp/telegram/email)"
    if any(e is None for _, e in esiti):
        falliti = [f"{c}: {e}" for c, e in esiti if e]
        if falliti:
            log.warning("reminder %s: consegnato, ma non su %s", getattr(reminder, "id", "?"), "; ".join(falliti))
        return None
    return " | ".join(f"{c}: {e}" for c, e in esiti)


def _tick() -> int:
    now_iso = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    try:
        pending = storage.list_pending_reminders(now_iso)
    except Exception as exc:  # noqa: BLE001
        log.error("reminder poll failed: %s", exc)
        return 0
    count = 0
    for reminder, event in pending:
        count += 1
        if event.done:
            storage.mark_reminder_sent(reminder.id, error="event done")
            continue
        err = _deliver(event, reminder)
        storage.mark_reminder_sent(reminder.id, error=err)
        if err:
            log.warning("reminder %s send failed: %s", reminder.id, err)
        else:
            log.info("reminder %s sent (event=%s, offset=%dm)",
                     reminder.id, event.id, reminder.offset_minutes)
    return count


def _loop() -> None:
    log.info("reminder scheduler started (poll=%ds)", POLL_SECONDS)
    while not _stop.is_set():
        try:
            _tick()
        except Exception as exc:  # noqa: BLE001
            log.exception("reminder tick crashed: %s", exc)
        try:                                    # v9.423: il promemoria del mattino su Telegram (dalle 7:30 locali)
            from . import telegram_bot as _tg
            _tg.briefing_tick()
        except Exception as exc:  # noqa: BLE001
            log.warning("briefing tick: %s", exc)
        try:                                    # v9.425: il sollecito delle scadenze dai documenti non ancora confermate
            sollecita_scadenze()
        except Exception as exc:  # noqa: BLE001
            log.warning("sollecito tick: %s", exc)
        _stop.wait(POLL_SECONDS)
    log.info("reminder scheduler stopped")


def start_background() -> None:
    """Idempotent — safe to call from multiple web workers (only one thread)."""
    global _thread
    if _thread and _thread.is_alive():
        return
    if not (TELEGRAM_BOT_TOKEN or _wa_configured() or _email_configured()):
        log.warning("no reminder channel configured (telegram/whatsapp/email) — scheduler disabled")
        return
    channels = []
    if _wa_configured():
        channels.append("whatsapp")
    if TELEGRAM_BOT_TOKEN:
        channels.append("telegram")
    if _email_configured():
        channels.append("email")
    log.info("reminder scheduler enabled — channels: %s", ", ".join(channels))
    _stop.clear()
    _thread = threading.Thread(target=_loop, name="reminder-scheduler", daemon=True)
    _thread.start()


def stop_background() -> None:
    _stop.set()
