"""Background reminder scheduler.

Polls the reminders table every ``POLL_SECONDS`` and delivers anything
whose ``fire_at`` has passed via Telegram Bot API (sendMessage). Uses the
same ``TELEGRAM_BOT_TOKEN`` the chat bot uses, but issues direct HTTPS
POSTs rather than the python-telegram-bot Application loop — that keeps
the scheduler decoupled from the bot's event loop and makes it safe to
run inside the Flask process.

Users opt in by saving their Telegram ``chat_id`` on their user row
(via /api/settings/telegram). Reminders for users without a linked chat
are marked as sent-with-error so the scheduler doesn't keep retrying.
"""
from __future__ import annotations

import json
import logging
import threading
import urllib.error
import urllib.parse
import urllib.request
from datetime import UTC, datetime

from . import storage
from .config import TELEGRAM_BOT_TOKEN

log = logging.getLogger(__name__)

POLL_SECONDS = 60
TG_API = "https://api.telegram.org"
_KIND_EMOJI = {
    "seance": "⚖️",
    "afat": "🔴",
    "takim": "👤",
    "dorëzim": "📨",
    "tjetër": "📌",
}

_thread: threading.Thread | None = None
_stop = threading.Event()


def _format_message(event, reminder) -> str:
    emoji = _KIND_EMOJI.get(event.kind, "📌")
    try:
        dt = datetime.fromisoformat(event.starts_at.replace("Z", "+00:00"))
        dt_local = dt.astimezone()
        when = dt_local.strftime("%d/%m/%Y %H:%M")
    except Exception:
        when = event.starts_at
    off = reminder.offset_minutes
    if off >= 1440:
        days = off // 1440
        ahead = f"{days} ditë para" if days > 1 else "1 ditë para"
    elif off >= 60:
        hours = off // 60
        ahead = f"{hours} orë para" if hours > 1 else "1 orë para"
    else:
        ahead = f"{off} minuta para"
    lines = [
        f"{emoji} *Kujtesë* ({ahead})",
        f"*{_md_escape(event.title)}*",
        f"🗓 {when}",
    ]
    if event.location:
        lines.append(f"📍 {_md_escape(event.location)}")
    if event.description:
        snippet = event.description.strip().splitlines()[0][:200]
        lines.append(f"\n{_md_escape(snippet)}")
    return "\n".join(lines)


def _md_escape(s: str) -> str:
    # Telegram Markdown requires escaping these; conservative set.
    return s.replace("_", r"\_").replace("*", r"\*").replace("[", r"\[").replace("`", r"\`")


def _send_telegram(chat_id: str, text: str) -> str | None:
    """POST sendMessage; return error string on failure, None on success."""
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
            body = resp.read().decode("utf-8", errors="ignore")
            data = json.loads(body)
            if not data.get("ok"):
                return f"telegram error: {data.get('description', 'unknown')}"
            return None
    except urllib.error.HTTPError as e:
        try:
            err_body = e.read().decode("utf-8", errors="ignore")
        except Exception:
            err_body = str(e)
        return f"http {e.code}: {err_body[:200]}"
    except Exception as e:
        return f"{type(e).__name__}: {str(e)[:200]}"


def _tick() -> int:
    """Process one polling round. Returns count of reminders processed."""
    now_iso = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    try:
        pending = storage.list_pending_reminders(now_iso)
    except Exception as exc:
        log.error("reminder poll failed: %s", exc)
        return 0
    count = 0
    for reminder, event in pending:
        count += 1
        if event.done:
            storage.mark_reminder_sent(reminder.id, error="event done")
            continue
        chat_id = storage.get_user_telegram_chat(event.user_id)
        if not chat_id:
            storage.mark_reminder_sent(reminder.id, error="no telegram chat linked")
            continue
        text = _format_message(event, reminder)
        err = _send_telegram(chat_id, text)
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
        except Exception as exc:
            log.exception("reminder tick crashed: %s", exc)
        _stop.wait(POLL_SECONDS)
    log.info("reminder scheduler stopped")


def start_background() -> None:
    """Idempotent — safe to call from multiple web workers (only one thread)."""
    global _thread
    if _thread and _thread.is_alive():
        return
    if not TELEGRAM_BOT_TOKEN:
        log.warning("TELEGRAM_BOT_TOKEN not set — reminder scheduler disabled")
        return
    _stop.clear()
    _thread = threading.Thread(target=_loop, name="reminder-scheduler", daemon=True)
    _thread.start()


def stop_background() -> None:
    _stop.set()
