"""Telegram interface for Super Avvocato.

Features:
  /start   — welcome + disclaimer
  /help    — how to use
  /reset   — clear the current conversation
  /about   — credits and mission
  any text — legal question, routed through the brain

Conversation history per chat is kept in memory (with a hard cap so memory
can't grow unbounded). For production on the VPS, swap `_STATE` with Redis or
SQLite if you want persistence across restarts.
"""
from __future__ import annotations

import asyncio
import html
import signal
from dataclasses import dataclass, field
from typing import Any

from telegram import Update
from telegram.constants import ChatAction, ParseMode
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from .brain import SuperAvvocato
from .config import MAX_CONVERSATION_TURNS, TELEGRAM_BOT_TOKEN
from .logging_utils import get_logger
from .retrieval import ArticleIndex

log = get_logger(__name__)


WELCOME = (
    "🇦🇱 *Mirë se erdhe te Super Avokati* 💙\n\n"
    "Jam një asistent ligjor *falas* për qytetarët shqiptarë. Mund të të ndihmoj me:\n"
    "• probleme familjare (martesa, divorci, kujdestaria)\n"
    "• probleme në punë (pagat, pushimi nga puna)\n"
    "• çështje penale (viktimë e një krimi, kallëzim)\n"
    "• çështje administrative, doganore, rrugore, zgjedhore\n"
    "• të drejtat e tua kushtetuese\n\n"
    "Thjesht *më trego problemin tënd me fjalët e tua* — unë do t'i gjej nenet e duhura "
    "nga kodet shqiptare dhe do të të jap një përgjigje të qartë.\n\n"
    "_Shkruaj /reset për të nisur një bisedë të re, /help për ndihmë._\n\n"
    "⚠️ *Kujdes:* informacioni këtu është ligjor dhe i bazuar në kodet, por "
    "nuk zëvendëson një avokat të vërtetë në raste të rënda."
)

HELP_TEXT = (
    "*Si funksionon Super Avokati*\n\n"
    "1. Më trego problemin tënd me fjalët e tua.\n"
    "2. Nëse më duhen më shumë detaje, do të bëj një pyetje.\n"
    "3. Do të marr një përgjigje me 4 seksione:\n"
    "   📜 Çfarë thotë ligji  \n"
    "   ⚖️ Të drejtat e tua  \n"
    "   🛠️ Çfarë duhet të bësh  \n"
    "   ⏰ Afatet ligjore\n\n"
    "Komandat:\n"
    "/start — mesazhi i mirëseardhjes\n"
    "/help — kjo ndihmë\n"
    "/reset — fshij bisedën e tanishme\n"
    "/about — për misionin tonë"
)

ABOUT_TEXT = (
    "💙 *Super Avokati* është projekt humanitar pa pagesë.\n\n"
    "Misioni: qasje në drejtësi për çdo qytetar, pavarësisht nga të ardhurat.\n\n"
    "Baza ligjore: 13 kodet zyrtare shqiptare + Kushtetuta (mbi 6,600 nene të indeksuara).\n\n"
    "Ndërtuar me dashuri për shqiptarët. 🇦🇱"
)


# ── state ──────────────────────────────────────────────────────────────────


@dataclass
class Session:
    history: list[dict[str, str]] = field(default_factory=list)

    def add(self, role: str, content: str) -> None:
        self.history.append({"role": role, "content": content})
        # keep only the most recent turns so the context doesn't blow up
        if len(self.history) > MAX_CONVERSATION_TURNS * 2:
            self.history = self.history[-MAX_CONVERSATION_TURNS * 2 :]


_STATE: dict[int, Session] = {}


def _session(chat_id: int) -> Session:
    if chat_id not in _STATE:
        _STATE[chat_id] = Session()
    return _STATE[chat_id]


# ── handlers ───────────────────────────────────────────────────────────────


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    _STATE.pop(update.effective_chat.id, None)
    await update.message.reply_text(WELCOME, parse_mode=ParseMode.MARKDOWN)


async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(HELP_TEXT, parse_mode=ParseMode.MARKDOWN)


async def about_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(ABOUT_TEXT, parse_mode=ParseMode.MARKDOWN)


async def reset_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    _STATE.pop(update.effective_chat.id, None)
    await update.message.reply_text(
        "✅ Biseda u rivendos. Më trego problemin tënd."
    )


async def on_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    text = (update.message.text or "").strip()
    if not text:
        return

    await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)
    sess = _session(chat_id)

    brain: SuperAvvocato = context.application.bot_data["brain"]
    try:
        result = await asyncio.to_thread(brain.answer, text, list(sess.history))
    except Exception as exc:
        log.exception("brain failure")
        await update.message.reply_text(
            "⚠️ Më fal, pata një problem teknik. Provo përsëri pas pak.\n\n"
            f"<i>({html.escape(type(exc).__name__)})</i>",
            parse_mode=ParseMode.HTML,
        )
        return

    sess.add("user", text)
    sess.add("assistant", result.text)

    await _send_long(update, result.text)


async def _send_long(update: Update, text: str) -> None:
    """Telegram limits each message to 4096 chars. Split on paragraphs if needed."""
    LIMIT = 4000
    if len(text) <= LIMIT:
        await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)
        return
    parts: list[str] = []
    buf: list[str] = []
    size = 0
    for para in text.split("\n\n"):
        plen = len(para) + 2
        if size + plen > LIMIT and buf:
            parts.append("\n\n".join(buf))
            buf, size = [], 0
        buf.append(para)
        size += plen
    if buf:
        parts.append("\n\n".join(buf))
    for p in parts:
        await update.message.reply_text(p, parse_mode=ParseMode.MARKDOWN)


async def on_error(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    log.error("update %s caused error: %s", update, context.error)


# ── lifecycle ──────────────────────────────────────────────────────────────


def _install_signal_handlers(app: Application) -> None:
    loop = asyncio.get_event_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, lambda: asyncio.create_task(app.stop()))
        except NotImplementedError:
            pass  # Windows


def build_app(brain: SuperAvvocato) -> Application:
    if not TELEGRAM_BOT_TOKEN:
        raise RuntimeError(
            "TELEGRAM_BOT_TOKEN is not set — get one from @BotFather on Telegram."
        )
    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    app.bot_data["brain"] = brain

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("about", about_cmd))
    app.add_handler(CommandHandler("reset", reset_cmd))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_message))
    app.add_error_handler(on_error)
    return app


def main() -> None:
    index = ArticleIndex.load()
    brain = SuperAvvocato(index=index)
    log.info("brain ready with %d articles", len(index.articles))

    app = build_app(brain)
    log.info("starting Telegram polling ...")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
