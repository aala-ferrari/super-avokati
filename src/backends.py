"""Pluggable LLM backends.

Three providers are supported:

- **Claude Code (subscription)** — headless `claude -p` CLI. No API key, no
  per-token billing; auth lives in the Claude Code login. Best answer quality
  plus native conversation sessions via `--resume`.
- **Anthropic (Claude 4.7 Opus + Haiku 4.5)** — API key, paid per call.
- **Google Gemini (2.5 Pro / 2.5 Flash)** — free tier (~1500 req/day on Flash).

The brain uses the `LLMBackend` interface so it never cares which provider
served the call. Selection order:

  1. `BRAIN_BACKEND` env var (`claude_code` | `anthropic` | `gemini`);
  2. `auto` (default): Claude Code CLI if logged in, else Gemini if key,
     else Anthropic if key, else error.

`session_id` is an optional kwarg on `complete()`:
  - Claude Code: when provided, uses `--resume <id>` so the CLI carries the
    conversation natively; the new/updated id is exposed via
    `backend.last_session_id` after each call.
  - Other backends: ignored (they rely on the caller to pass full history).
"""
from __future__ import annotations

import base64
import json
import os
import shutil
import subprocess
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Literal

from .logging_utils import get_logger

log = get_logger(__name__)

Role = Literal["user", "assistant"]
Message = dict[str, str]  # {"role": "user"|"assistant", "content": "..."}


class LLMBackend(ABC):
    name: str = "abstract"
    last_session_id: str | None = None  # set by session-aware backends

    @abstractmethod
    def complete(
        self,
        system: str,
        messages: list[Message],
        max_tokens: int = 1500,
        fast: bool = False,
        session_id: str | None = None,
        attachments: list[Path] | None = None,
    ) -> str:
        """Return the assistant's text for the given system + message history.

        `attachments`, when provided, is a list of file paths (PDF/JPG/PNG/
        etc.) that the model should read natively — same spirit as a user
        pasting an image into a chat. Backends that don't support it will
        ignore the argument and rely on any OCR text already in `messages`.
        """

    def ocr_image(self, path: Path, mimetype: str, prompt: str) -> str:
        """OCR an image file. Backends that don't support vision raise.

        Default: unsupported. Override in subclasses that have vision.
        """
        raise NotImplementedError(
            f"backend '{self.name}' does not support vision OCR"
        )


# ── Claude Code (headless CLI, subscription auth) ─────────────────────────

class ClaudeCodeBackend(LLMBackend):
    """Invokes the `claude` CLI in headless `-p` mode.

    Pipeline stages wire into this as follows:
      * triage / strategic (stateless analytical JSON): `session_id=None`
        → fresh call, system prompt set via `--system-prompt`, history
        flattened into the piped prompt.
      * answer composition (conversational): `session_id=<flask-tracked>`
        → `--resume <id>` so Claude Code preserves the thread with the
        citizen across turns (no re-sending history).
    """
    name = "claude_code"

    def __init__(
        self,
        model: str = "opus",
        fast_model: str = "haiku",
        cli_path: str | None = None,
        timeout_s: int = 600,
        effort: str | None = "max",
    ):
        self.cli = cli_path or shutil.which("claude")
        if not self.cli:
            raise RuntimeError(
                "claude CLI not found in PATH. Install Claude Code "
                "(https://docs.claude.com/claude-code) and run `claude /login`."
            )
        self.model = model
        self.fast_model = fast_model
        self.timeout_s = timeout_s
        # Reasoning budget for the main (non-fast) call. Valid values:
        # low, medium, high, xhigh, max. None disables the flag.
        self.effort = effort

    def complete(self, system, messages, max_tokens=1500, fast=False,
                 session_id: str | None = None,
                 attachments: list[Path] | None = None) -> str:
        from .config import ROOT

        model = self.fast_model if fast else self.model
        cmd = [self.cli, "-p", "--output-format", "json", "--model", model]

        # Extended thinking on the main answer stage — Opus reasons
        # through hard legal questions before writing the final text.
        if not fast and self.effort:
            cmd.extend(["--effort", self.effort])

        if session_id:
            # Resume existing session — system prompt + history are baked in;
            # only pipe the latest user turn.
            cmd.extend(["--resume", session_id])
            prompt = _last_user_content(messages)
        else:
            # Fresh call — set our system prompt and flatten full history.
            cmd.extend(["--system-prompt", system])
            prompt = _flatten_messages(messages)

        # If the caller has files to attach (dossier), hand them to Claude
        # via the Read tool — same UX as pasting an image into a chat.
        # Allow directories that contain each file so Read can access them.
        if attachments:
            cmd.extend(["--allowedTools", "Read",
                        "--permission-mode", "bypassPermissions"])
            seen_dirs: set[str] = set()
            file_list_lines: list[str] = []
            for p in attachments:
                ap = Path(p).resolve()
                d = str(ap.parent)
                if d not in seen_dirs:
                    cmd.extend(["--add-dir", d])
                    seen_dirs.add(d)
                file_list_lines.append(f"- {ap}")
            prompt = (
                "DOKUMENTET E DOSJES (lexoji para se të përgjigjesh):\n"
                + "\n".join(file_list_lines)
                + "\n\nPËR SECILIN skedar më sipër: përdor toolin Read për "
                "ta hapur DIREKT me pathin e plotë. Mos u mbështet te "
                "përmbledhje; lexoji vetë dhe nxirr faktet e duhura (data, "
                "palët, shuma, dispozitivi, afate). Pasi t'i kesh lexuar, "
                "kthehu te pyetja më poshtë dhe shkruaj përgjigjen.\n\n"
                "━━━ KËRKESA ━━━\n"
                + prompt
            )

        log.debug("claude cmd: %s (prompt=%d chars)", cmd, len(prompt))

        try:
            proc = subprocess.run(
                cmd,
                input=prompt,
                capture_output=True,
                text=True,
                timeout=self.timeout_s,
                cwd=str(ROOT),
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError(
                f"claude CLI timed out after {self.timeout_s}s"
            ) from exc

        # If --resume failed (session evicted / wrong id), retry fresh once.
        if proc.returncode != 0 and session_id:
            log.warning(
                "claude --resume %s failed (rc=%d): %s — retrying fresh",
                session_id, proc.returncode, proc.stderr[-300:].strip(),
            )
            return self.complete(system, messages, max_tokens, fast, session_id=None)

        if proc.returncode != 0:
            raise RuntimeError(
                f"claude CLI failed (rc={proc.returncode}): "
                f"{proc.stderr[-500:].strip() or proc.stdout[-500:].strip()}"
            )

        try:
            data = json.loads(proc.stdout.strip() or "{}")
        except json.JSONDecodeError as exc:
            raise RuntimeError(
                f"claude CLI non-JSON output: {proc.stdout[:500]}"
            ) from exc

        if data.get("is_error"):
            raise RuntimeError(
                f"claude CLI reported error: {str(data.get('result', ''))[:500]}"
            )

        new_sid = data.get("session_id")
        if new_sid:
            self.last_session_id = new_sid

        text = (data.get("result") or "").strip()
        if not text:
            raise RuntimeError(
                f"claude CLI returned empty result (session={new_sid}, "
                f"stop_reason={data.get('stop_reason')})"
            )
        return text

    def ocr_image(self, path: Path, mimetype: str, prompt: str) -> str:
        """OCR via `claude -p` with the Read tool. Uses the subscription —
        no API key required. The model's Read tool handles PNG/JPG natively."""
        from .config import ROOT

        abs_path = Path(path).resolve()
        # Allow Claude to Read files from the image's directory. This covers
        # both persistent uploads (data/uploads/<case>/) and temp-file pages
        # we write during PDF rasterization.
        extra_dir = str(abs_path.parent)
        full_prompt = (
            f"{prompt}\n\n"
            f"File: {abs_path}\n"
            f"Read this file and return ONLY the extracted text. "
            f"No commentary, no summary, no markdown fences."
        )
        cmd = [
            self.cli, "-p",
            "--output-format", "json",
            "--model", self.fast_model,
            "--allowedTools", "Read",
            "--permission-mode", "bypassPermissions",
            "--add-dir", extra_dir,
        ]
        try:
            proc = subprocess.run(
                cmd, input=full_prompt, capture_output=True, text=True,
                timeout=self.timeout_s, cwd=str(ROOT), check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError(
                f"claude CLI OCR timed out after {self.timeout_s}s"
            ) from exc
        if proc.returncode != 0:
            raise RuntimeError(
                f"claude CLI OCR failed (rc={proc.returncode}): "
                f"{proc.stderr[-400:].strip() or proc.stdout[-400:].strip()}"
            )
        try:
            data = json.loads(proc.stdout.strip() or "{}")
        except json.JSONDecodeError as exc:
            raise RuntimeError(
                f"claude CLI OCR non-JSON output: {proc.stdout[:400]}"
            ) from exc
        if data.get("is_error"):
            raise RuntimeError(
                f"claude CLI OCR reported error: {str(data.get('result', ''))[:400]}"
            )
        return (data.get("result") or "").strip()


# ── Anthropic API ─────────────────────────────────────────────────────────

class AnthropicBackend(LLMBackend):
    name = "anthropic"

    def __init__(self, api_key: str, model: str, fast_model: str,
                 thinking_budget: int = 0):
        from anthropic import Anthropic  # lazy import
        self.client = Anthropic(api_key=api_key)
        self.model = model
        self.fast_model = fast_model
        # Token budget for extended thinking on the main model. 0 disables.
        self.thinking_budget = thinking_budget

    def complete(self, system, messages, max_tokens=1500, fast=False,
                 session_id: str | None = None,
                 attachments: list[Path] | None = None) -> str:
        # attachments: Anthropic supports images/PDFs natively via content
        # blocks. We attach each file to the LAST user message so the model
        # reads them as part of the current question.
        if attachments and messages:
            messages = [dict(m) for m in messages]
            last = messages[-1]
            if last.get("role") == "user":
                blocks = self._attachment_blocks(attachments)
                last["content"] = blocks + [
                    {"type": "text", "text": str(last.get("content", ""))}
                ]
        kwargs: dict = dict(
            model=self.fast_model if fast else self.model,
            max_tokens=max_tokens,
            system=system,
            messages=messages,
        )
        # Extended thinking on the main (non-fast) call. Max budget must
        # be less than max_tokens, so we bump max_tokens if needed.
        if not fast and self.thinking_budget > 0:
            if max_tokens <= self.thinking_budget:
                kwargs["max_tokens"] = self.thinking_budget + 2000
            kwargs["thinking"] = {
                "type": "enabled",
                "budget_tokens": self.thinking_budget,
            }
        resp = self.client.messages.create(**kwargs)
        # With thinking enabled the first block is the thinking trace;
        # grab the first text block for the actual answer.
        for block in resp.content:
            if getattr(block, "type", None) == "text":
                return block.text.strip()
        return ""

    def _attachment_blocks(self, attachments: list[Path]) -> list[dict]:
        import mimetypes
        blocks: list[dict] = []
        for p in attachments:
            ap = Path(p)
            mt, _ = mimetypes.guess_type(str(ap))
            if not mt:
                continue
            data = base64.standard_b64encode(ap.read_bytes()).decode("ascii")
            if mt == "application/pdf":
                blocks.append({"type": "document", "source": {
                    "type": "base64", "media_type": mt, "data": data,
                }})
            elif mt.startswith("image/"):
                blocks.append({"type": "image", "source": {
                    "type": "base64", "media_type": mt, "data": data,
                }})
        return blocks

    def ocr_image(self, path: Path, mimetype: str, prompt: str) -> str:
        image_bytes = Path(path).read_bytes()
        b64 = base64.standard_b64encode(image_bytes).decode("ascii")
        resp = self.client.messages.create(
            model=self.fast_model,
            max_tokens=4000,
            messages=[{
                "role": "user",
                "content": [
                    {"type": "image", "source": {
                        "type": "base64", "media_type": mimetype, "data": b64,
                    }},
                    {"type": "text", "text": prompt},
                ],
            }],
        )
        return resp.content[0].text.strip() if resp.content else ""


# ── Gemini API ────────────────────────────────────────────────────────────

class GeminiBackend(LLMBackend):
    name = "gemini"

    def __init__(self, api_key: str, model: str, fast_model: str):
        from google import genai  # lazy import
        from google.genai import types  # noqa: F401
        self._genai = genai
        self._types = types
        self.client = genai.Client(api_key=api_key)
        self.model = model
        self.fast_model = fast_model

    def complete(self, system, messages, max_tokens=1500, fast=False,
                 session_id: str | None = None,
                 attachments: list[Path] | None = None) -> str:
        contents = []
        for m in messages:
            role = "model" if m["role"] == "assistant" else "user"
            contents.append({"role": role, "parts": [{"text": m["content"]}]})

        # Attach files to the last user turn so Gemini reads them natively.
        if attachments and contents and contents[-1]["role"] == "user":
            import mimetypes
            extra_parts: list = []
            for p in attachments:
                ap = Path(p)
                mt, _ = mimetypes.guess_type(str(ap))
                if not mt:
                    continue
                extra_parts.append(self._types.Part.from_bytes(
                    data=ap.read_bytes(), mime_type=mt,
                ))
            contents[-1]["parts"] = extra_parts + contents[-1]["parts"]

        resp = self.client.models.generate_content(
            model=self.fast_model if fast else self.model,
            contents=contents,
            config=self._types.GenerateContentConfig(
                system_instruction=system,
                max_output_tokens=max_tokens,
                temperature=0.3,  # legal work wants consistency
            ),
        )
        text = (resp.text or "").strip()
        if not text:
            raise RuntimeError(
                f"Gemini returned empty response (finish_reason="
                f"{getattr(resp.candidates[0], 'finish_reason', 'unknown') if resp.candidates else 'no-candidate'})"
            )
        return text

    def ocr_image(self, path: Path, mimetype: str, prompt: str) -> str:
        image_bytes = Path(path).read_bytes()
        resp = self.client.models.generate_content(
            model=self.fast_model,
            contents=[
                self._types.Part.from_bytes(data=image_bytes, mime_type=mimetype),
                prompt,
            ],
        )
        return (resp.text or "").strip()


# ── prompt flattening helpers (for Claude Code -p mode) ───────────────────

def _last_user_content(messages: list[Message]) -> str:
    for m in reversed(messages):
        if m.get("role") == "user":
            return str(m.get("content", ""))
    return ""


def _flatten_messages(messages: list[Message]) -> str:
    """Flatten a message history into one piped-stdin prompt for `claude -p`.

    Only used on FRESH sessions (no --resume). Claude Code's -p takes a
    single prompt over stdin, so we serialize the turn tape with clear
    role markers so the model can tell prior turns from the current ask.
    """
    if not messages:
        return ""
    if len(messages) == 1 and messages[0].get("role") == "user":
        return str(messages[0].get("content", ""))
    parts: list[str] = []
    for m in messages[:-1]:
        role = "QYTETARI" if m.get("role") == "user" else "AVOKATI"
        parts.append(f"[{role}]\n{m.get('content', '')}")
    last = messages[-1]
    parts.append(f"\n━━━ Mesazhi aktual ━━━\n{last.get('content', '')}")
    return "\n\n".join(parts)


# ── factory ───────────────────────────────────────────────────────────────

def build_backend() -> LLMBackend:
    """Build the configured backend. Raises RuntimeError if nothing is available."""
    from .config import (
        ANTHROPIC_API_KEY,
        BRAIN_BACKEND,
        CLAUDE_CODE_EFFORT,
        CLAUDE_CODE_FAST_MODEL,
        CLAUDE_CODE_MODEL,
        CLAUDE_FAST_MODEL,
        CLAUDE_MODEL,
        CLAUDE_THINKING_BUDGET,
        GEMINI_API_KEY,
        GEMINI_FAST_MODEL,
        GEMINI_MODEL,
    )

    choice = (BRAIN_BACKEND or "auto").lower().strip()
    cli_available = shutil.which("claude") is not None

    if choice == "auto":
        # Prefer Claude Code CLI when available — best quality, uses the
        # user's subscription, and supports native conversation sessions.
        if cli_available:
            choice = "claude_code"
        elif GEMINI_API_KEY:
            choice = "gemini"
        elif ANTHROPIC_API_KEY:
            choice = "anthropic"
        else:
            raise RuntimeError(
                "No LLM available. Install Claude Code (`claude /login`), "
                "or set GEMINI_API_KEY / ANTHROPIC_API_KEY in .env."
            )

    if choice in ("claude_code", "claude-code", "claudecode"):
        if not cli_available:
            raise RuntimeError(
                "BRAIN_BACKEND=claude_code but `claude` CLI is not in PATH. "
                "Install Claude Code and run `claude /login`."
            )
        log.info("using Claude Code backend (%s / %s, effort=%s)",
                 CLAUDE_CODE_MODEL, CLAUDE_CODE_FAST_MODEL,
                 CLAUDE_CODE_EFFORT or "off")
        return ClaudeCodeBackend(
            model=CLAUDE_CODE_MODEL,
            fast_model=CLAUDE_CODE_FAST_MODEL,
            effort=CLAUDE_CODE_EFFORT or None,
        )

    if choice == "gemini":
        if not GEMINI_API_KEY:
            raise RuntimeError("BRAIN_BACKEND=gemini but GEMINI_API_KEY is missing.")
        log.info("using Gemini backend (%s / %s)", GEMINI_MODEL, GEMINI_FAST_MODEL)
        return GeminiBackend(GEMINI_API_KEY, GEMINI_MODEL, GEMINI_FAST_MODEL)

    if choice == "anthropic":
        if not ANTHROPIC_API_KEY:
            raise RuntimeError("BRAIN_BACKEND=anthropic but ANTHROPIC_API_KEY is missing.")
        log.info("using Anthropic backend (%s / %s, thinking=%d)",
                 CLAUDE_MODEL, CLAUDE_FAST_MODEL, CLAUDE_THINKING_BUDGET)
        return AnthropicBackend(
            ANTHROPIC_API_KEY, CLAUDE_MODEL, CLAUDE_FAST_MODEL,
            thinking_budget=CLAUDE_THINKING_BUDGET,
        )

    raise RuntimeError(
        f"Unknown BRAIN_BACKEND='{choice}'. "
        "Use 'claude_code', 'gemini', 'anthropic', or 'auto'."
    )


def detect_available_backend() -> str | None:
    """Return the name of the backend that would be selected, or None."""
    from .config import ANTHROPIC_API_KEY, BRAIN_BACKEND, GEMINI_API_KEY

    choice = (BRAIN_BACKEND or "auto").lower()
    cli_available = shutil.which("claude") is not None

    if choice in ("claude_code", "claude-code", "claudecode") and cli_available:
        return "claude_code"
    if choice == "gemini" and GEMINI_API_KEY:
        return "gemini"
    if choice == "anthropic" and ANTHROPIC_API_KEY:
        return "anthropic"
    if choice == "auto":
        if cli_available: return "claude_code"
        if GEMINI_API_KEY: return "gemini"
        if ANTHROPIC_API_KEY: return "anthropic"
    return None
