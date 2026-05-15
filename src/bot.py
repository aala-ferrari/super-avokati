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

from . import storage
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
    "💼 *A të duhet një avokat i vërtetë?* Shkruaj /intake — kërkesa jote do t'i shkojë "
    "një avokati nga ekipi ynë që do të të kontaktojë drejtpërdrejt.\n\n"
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
    "/about — për misionin tonë\n"
    "/intake — kërko një konsultë me një avokat të vërtetë"
)


# /intake conversation prompts — the citizen submits a lead that lands
# in the lawyer's inbox in the web app.
INTAKE_INTRO = (
    "📥 *Kërkesë për një avokat të vërtetë*\n\n"
    "Do të të bëj 3 pyetje të shkurtra dhe pastaj kërkesën do ta marrë "
    "një avokat. Shkruaj /cancel për të anuluar.\n\n"
    "*1/3* — Si quhesh? (emri dhe mbiemri)"
)
INTAKE_ASK_CONTACT = (
    "*2/3* — Si mund të të kontaktojë avokati? Lëre një numër telefoni "
    "ose email (ose të dyja, të ndara me presje)."
)
INTAKE_ASK_PROBLEM = (
    "*3/3* — Tani përshkruaj problemin tënd me fjalët e tua. "
    "Sa më shumë detaje (data, palët, dokumentet që ke), aq më mirë.\n\n"
    "_Minimumi: 20 karaktere._"
)
INTAKE_DONE = (
    "✅ *Kërkesa u dërgua!*\n\n"
    "Avokati do të të kontaktojë sa më shpejt të jetë e mundur. "
    "Faleminderit që na zgjodhe."
)
INTAKE_CANCEL = "❎ Kërkesa u anulua. Mund të nisësh përsëri me /intake."

INTAKE_SYSTEM_PROMPT = (
    "Je një bot pranues hyrjesh. Ke marrë mesazhin e qytetarit. Detyra:\n"
    "1) Shkruaj një PËRMBLEDHJE 1-2 fjali (neutrale).\n"
    "2) Klasifiko ai_area: familjare|pune|penale|civile|tregtare|administrative|trashëgimi|banimore|konsumatore|tjeter\n"
    "3) Cakto ai_urgency: high|medium|low\n"
    "4) 2-4 pyetje që mungojnë.\n\n"
    "Kthe vetëm JSON: {\"summary\":\"...\",\"area\":\"...\",\"urgency\":\"...\",\"missing_questions\":[...]}\n"
    "Asgjë jashtë JSON-it."
)


# Per-chat intake state machine
@dataclass
class IntakeState:
    step: str = "name"  # name → contact → problem → done
    name: str = ""
    phone: str | None = None
    email: str | None = None


_INTAKE: dict[int, IntakeState] = {}

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
    _INTAKE.pop(update.effective_chat.id, None)
    await update.message.reply_text(
        "✅ Biseda u rivendos. Më trego problemin tënd."
    )


async def intake_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    _INTAKE[chat_id] = IntakeState(step="name")
    await update.message.reply_text(INTAKE_INTRO, parse_mode=ParseMode.MARKDOWN)


async def cancel_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    if chat_id in _INTAKE:
        _INTAKE.pop(chat_id, None)
        await update.message.reply_text(INTAKE_CANCEL)
    else:
        await update.message.reply_text("S'ke ndonjë veprim aktiv për të anuluar.")


def _parse_contact(text: str) -> tuple[str | None, str | None]:
    """Loose: anything with @ → email, else digits/+ → phone."""
    phone, email = None, None
    for chunk in [c.strip() for c in text.replace(";", ",").split(",") if c.strip()]:
        if "@" in chunk:
            email = chunk
        elif any(ch.isdigit() for ch in chunk):
            phone = chunk
    if not phone and not email:
        # whole text is a single value
        if "@" in text:
            email = text.strip()
        elif any(ch.isdigit() for ch in text):
            phone = text.strip()
    return phone, email


def _classify_via_brain(brain: SuperAvvocato, problem_text: str) -> dict:
    try:
        raw = brain.backend.complete(
            system=INTAKE_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": problem_text[:4000]}],
            max_tokens=600,
            medium=True,  # V8.10 Sonnet — lawyer reads classification output
        )
        import json as _json
        # robust extraction of the first JSON object
        start = raw.find("{")
        end = raw.rfind("}")
        if start != -1 and end != -1 and end > start:
            return _json.loads(raw[start:end + 1])
    except Exception as exc:
        log.warning("telegram intake classify failed: %s", exc)
    return {}


async def _handle_intake_step(
    update: Update, context: ContextTypes.DEFAULT_TYPE, state: IntakeState
) -> bool:
    """Returns True if the message was consumed by the intake flow."""
    chat_id = update.effective_chat.id
    text = (update.message.text or "").strip()
    if state.step == "name":
        if len(text) < 2:
            await update.message.reply_text(
                "Më duhet të paktën emri yt. Provo përsëri:"
            )
            return True
        state.name = text[:120]
        state.step = "contact"
        await update.message.reply_text(INTAKE_ASK_CONTACT, parse_mode=ParseMode.MARKDOWN)
        return True
    if state.step == "contact":
        phone, email = _parse_contact(text)
        if not phone and not email:
            await update.message.reply_text(
                "Më duhet një numër telefoni ose email që avokati të të kontaktojë:"
            )
            return True
        state.phone = phone
        state.email = email
        state.step = "problem"
        await update.message.reply_text(INTAKE_ASK_PROBLEM, parse_mode=ParseMode.MARKDOWN)
        return True
    if state.step == "problem":
        if len(text) < 20:
            await update.message.reply_text(
                "Përshkrimi është shumë i shkurtër. Shkruaj të paktën 20 karaktere:"
            )
            return True
        problem_text = text[:6000]
        brain: SuperAvvocato = context.application.bot_data["brain"]
        classification = await asyncio.to_thread(
            _classify_via_brain, brain, problem_text
        )
        summary = (classification.get("summary") or "")[:300] or None
        area = (classification.get("area") or "tjeter")[:40]
        urgency = classification.get("urgency") or "medium"
        if urgency not in storage.LEAD_URGENCIES:
            urgency = "medium"
        missing = classification.get("missing_questions") or []
        if not isinstance(missing, list):
            missing = []
        try:
            await asyncio.to_thread(
                storage.create_lead,
                source="telegram",
                contact_name=state.name,
                contact_phone=state.phone,
                contact_email=state.email,
                problem_text=problem_text,
                firm_id=None,  # no firm slug from Telegram → goes to global inbox
                telegram_chat_id=chat_id,
                ai_summary=summary,
                ai_area=area,
                ai_urgency=urgency,
                ai_missing=missing,
            )
        except Exception as exc:
            log.exception("telegram intake create_lead failed: %s", exc)
            await update.message.reply_text(
                "⚠️ Pata një problem teknik. Provo përsëri pas pak ose dërgo /intake."
            )
            _INTAKE.pop(chat_id, None)
            return True
        _INTAKE.pop(chat_id, None)
        await update.message.reply_text(INTAKE_DONE, parse_mode=ParseMode.MARKDOWN)
        return True
    return False


async def on_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    text = (update.message.text or "").strip()
    if not text:
        return

    # If the user is mid-intake flow, route the message to the lead handler
    # instead of the legal-advice brain.
    intake_state = _INTAKE.get(chat_id)
    if intake_state is not None:
        await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)
        consumed = await _handle_intake_step(update, context, intake_state)
        if consumed:
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
    app.add_handler(CommandHandler("intake", intake_cmd))
    app.add_handler(CommandHandler("cancel", cancel_cmd))
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
