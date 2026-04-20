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

import json
import os
import shutil
import subprocess
from abc import ABC, abstractmethod
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
    ) -> str:
        """Return the assistant's text for the given system + message history."""


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
        timeout_s: int = 180,
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

    def complete(self, system, messages, max_tokens=1500, fast=False,
                 session_id: str | None = None) -> str:
        from .config import ROOT

        model = self.fast_model if fast else self.model
        cmd = [self.cli, "-p", "--output-format", "json", "--model", model]

        if session_id:
            # Resume existing session — system prompt + history are baked in;
            # only pipe the latest user turn.
            cmd.extend(["--resume", session_id])
            prompt = _last_user_content(messages)
        else:
            # Fresh call — set our system prompt and flatten full history.
            cmd.extend(["--system-prompt", system])
            prompt = _flatten_messages(messages)

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


# ── Anthropic API ─────────────────────────────────────────────────────────

class AnthropicBackend(LLMBackend):
    name = "anthropic"

    def __init__(self, api_key: str, model: str, fast_model: str):
        from anthropic import Anthropic  # lazy import
        self.client = Anthropic(api_key=api_key)
        self.model = model
        self.fast_model = fast_model

    def complete(self, system, messages, max_tokens=1500, fast=False,
                 session_id: str | None = None) -> str:
        resp = self.client.messages.create(
            model=self.fast_model if fast else self.model,
            max_tokens=max_tokens,
            system=system,
            messages=messages,
        )
        return resp.content[0].text.strip()


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
                 session_id: str | None = None) -> str:
        contents = []
        for m in messages:
            role = "model" if m["role"] == "assistant" else "user"
            contents.append({"role": role, "parts": [{"text": m["content"]}]})

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
        CLAUDE_CODE_FAST_MODEL,
        CLAUDE_CODE_MODEL,
        CLAUDE_FAST_MODEL,
        CLAUDE_MODEL,
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
        log.info("using Claude Code backend (%s / %s)",
                 CLAUDE_CODE_MODEL, CLAUDE_CODE_FAST_MODEL)
        return ClaudeCodeBackend(model=CLAUDE_CODE_MODEL, fast_model=CLAUDE_CODE_FAST_MODEL)

    if choice == "gemini":
        if not GEMINI_API_KEY:
            raise RuntimeError("BRAIN_BACKEND=gemini but GEMINI_API_KEY is missing.")
        log.info("using Gemini backend (%s / %s)", GEMINI_MODEL, GEMINI_FAST_MODEL)
        return GeminiBackend(GEMINI_API_KEY, GEMINI_MODEL, GEMINI_FAST_MODEL)

    if choice == "anthropic":
        if not ANTHROPIC_API_KEY:
            raise RuntimeError("BRAIN_BACKEND=anthropic but ANTHROPIC_API_KEY is missing.")
        log.info("using Anthropic backend (%s / %s)", CLAUDE_MODEL, CLAUDE_FAST_MODEL)
        return AnthropicBackend(ANTHROPIC_API_KEY, CLAUDE_MODEL, CLAUDE_FAST_MODEL)

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
