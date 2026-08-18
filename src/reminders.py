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

log = logging.getLogger(__name__)

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
    try:
        dt = datetime.fromisoformat(event.starts_at.replace("Z", "+00:00"))
        when = dt.astimezone().strftime("%d/%m/%Y %H:%M")
    except Exception:  # noqa: BLE001
        when = event.starts_at
    if event.location:
        when = f"{when} · {event.location}"
    return when


def _fmt_ahead(reminder) -> str:
    off = reminder.offset_minutes
    if off >= 1440:
        days = off // 1440
        return f"{days} ditë para" if days > 1 else "1 ditë para"
    if off >= 60:
        hours = off // 60
        return f"{hours} orë para" if hours > 1 else "1 orë para"
    return f"{off} minuta para"


def _md_escape(s: str) -> str:
    return s.replace("_", r"\_").replace("*", r"\*").replace("[", r"\[").replace("`", r"\`")


def _format_message(event, reminder) -> str:
    """Telegram Markdown message."""
    emoji = _KIND_EMOJI.get(event.kind, "📌")
    lines = [
        f"{emoji} *Kujtesë* ({_fmt_ahead(reminder)})",
        f"*{_md_escape(event.title)}*",
        f"🗓 {_md_escape(_fmt_when(event))}",
    ]
    if event.description:
        snippet = event.description.strip().splitlines()[0][:200]
        lines.append(f"\n{_md_escape(snippet)}")
    return "\n".join(lines)


# ── Telegram channel ──────────────────────────────────────────────────────

def _send_telegram(chat_id: str, text: str) -> str | None:
    if not TELEGRAM_BOT_TOKEN:
        return "TELEGRAM_BOT_TOKEN not set"
    url = f"{TG_API}/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = urllib.parse.urlencode({
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "Markdown",
        "disable_web_page_preview": "true",
    }).encode("utf-8")
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
    ahead = _fmt_ahead(reminder)
    when = _fmt_when(event)
    title = event.title or "Kujtesë"
    kind = _KIND_EMOJI.get(event.kind, "📌")
    desc = ""
    if event.description:
        snippet = event.description.strip().splitlines()[0][:300]
        desc = f'<p style="color:#555;margin:10px 0 0">{_html_escape(snippet)}</p>'
    subject = f"⏰ Kujtesë ({ahead}): {title}"
    html = (
        '<div style="font-family:Georgia,serif;max-width:520px;margin:0 auto;color:#1a1a1a">'
        '<div style="background:#0f2540;color:#f3e6c4;padding:14px 18px;border-radius:12px 12px 0 0">'
        f'<b>{kind} Kujtesë</b> · {_html_escape(ahead)}</div>'
        '<div style="border:1px solid #e3d3a5;border-top:none;border-radius:0 0 12px 12px;padding:16px 18px">'
        f'<h2 style="margin:0 0 6px;color:#0f2540">{_html_escape(title)}</h2>'
        f'<p style="margin:0;color:#6b5836">🗓 {_html_escape(when)}</p>'
        f'{desc}'
        '<p style="margin:16px 0 0;font-size:12px;color:#999">Super Avokati · kujtesë automatike e agjendës</p>'
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

def _deliver(event, reminder) -> str | None:
    wa_phone = storage.get_user_whatsapp(event.user_id) if _wa_configured() else None
    tg_chat = storage.get_user_telegram_chat(event.user_id)
    email = storage.get_user_reminder_email(event.user_id) if _email_configured() else None
    pref = (getattr(reminder, "channel", "") or "").strip().lower()
    if pref == "whatsapp" and wa_phone:
        return _send_whatsapp(wa_phone, event, reminder)
    if pref == "telegram" and tg_chat:
        return _send_telegram(tg_chat, _format_message(event, reminder))
    if pref == "email" and email:
        return _send_email(email, event, reminder)
    # auto priority: WhatsApp (read most) > Telegram > Email (fallback)
    if wa_phone:
        return _send_whatsapp(wa_phone, event, reminder)
    if tg_chat:
        return _send_telegram(tg_chat, _format_message(event, reminder))
    if email:
        return _send_email(email, event, reminder)
    return "no channel linked (whatsapp/telegram/email)"


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
