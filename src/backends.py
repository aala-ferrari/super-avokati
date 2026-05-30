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
import hashlib
import json
import os
import shutil
import subprocess
import threading
import time
from abc import ABC, abstractmethod
from collections.abc import Iterator
from pathlib import Path
from typing import Literal

from .logging_utils import get_logger

log = get_logger(__name__)

Role = Literal["user", "assistant"]
Message = dict[str, str]  # {"role": "user"|"assistant", "content": "..."}


# ── V8.12 EU AI Act audit logging ─────────────────────────────────────────
#
# Every LLM call is appended to ``ai_audit_log`` (see storage.py) so the
# system can satisfy AI Act art. 12 (automated logs for high-risk systems)
# and Annex IV traceability. The hook is best-effort: audit failures must
# never break a user request, so all storage interactions are wrapped in
# a try/except that logs at WARNING level and swallows.
#
# Raw prompt/response are NOT stored by default — only short SHA-256[:16]
# hashes — to keep the DB compact and avoid GDPR concerns. Set
# ``AI_AUDIT_STORE_RAW=1`` in the environment to also persist truncated
# raw text (useful during debugging / regulator audits).

_AUDIT_STORE_RAW = os.getenv("AI_AUDIT_STORE_RAW", "").strip() in ("1", "true", "yes")
_AUDIT_RAW_TRUNCATE = int(os.getenv("AI_AUDIT_RAW_TRUNCATE", "4000"))


def _hash16(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()[:16]


def _serialize_prompt(system: str, messages: list[Message]) -> str:
    parts = [f"[SYSTEM]\n{system or ''}"]
    for m in messages:
        parts.append(f"[{(m.get('role') or '?').upper()}]\n{m.get('content', '')}")
    return "\n\n".join(parts)


def _tier_label(fast: bool, medium: bool) -> str:
    if fast:
        return "fast"
    if medium:
        return "medium"
    return "default"


def _truncate(text: str | None) -> str | None:
    if text is None:
        return None
    if len(text) <= _AUDIT_RAW_TRUNCATE:
        return text
    return text[:_AUDIT_RAW_TRUNCATE] + f"\n…[truncated {len(text) - _AUDIT_RAW_TRUNCATE} chars]"


def _infer_callsite() -> str:
    """Walk the stack to find the first frame outside backends.py.

    Used to auto-tag audit rows when the caller didn't pass an explicit
    ``callsite=``. Returns ``"<filename>:<function>"`` or ``"unknown"``.
    """
    import inspect
    try:
        for frame in inspect.stack()[1:8]:
            fname = frame.filename
            if fname.endswith("backends.py"):
                continue
            return f"{Path(fname).name}:{frame.function}"
    except Exception:  # noqa: BLE001
        pass
    return "unknown"


def _audit_safe(**kw) -> None:
    """Best-effort audit log. Never raises."""
    if not kw.get("callsite") or kw.get("callsite") == "unknown":
        kw["callsite"] = _infer_callsite()
    try:
        from . import storage
        storage.audit_log_call(**kw)
    except Exception as exc:  # noqa: BLE001
        log.warning("audit_log_call failed (%s): %s", kw.get("callsite"), exc)


class LLMBackend(ABC):
    name: str = "abstract"
    last_session_id: str | None = None  # set by session-aware backends
    # Set True by a session-aware backend when a resume attempt fails and
    # the call silently falls back to a fresh session. Callers should read
    # this after complete() to know the conversational thread was lost —
    # typically to invalidate the stale stored session_id.
    last_resume_failed: bool = False

    @abstractmethod
    def complete(
        self,
        system: str,
        messages: list[Message],
        max_tokens: int = 1500,
        fast: bool = False,
        medium: bool = False,
        session_id: str | None = None,
        attachments: list[Path] | None = None,
        callsite: str | None = None,
        user_id: int | None = None,
        case_id: str | None = None,
    ) -> str:
        """Return the assistant's text for the given system + message history.

        Tier selection (V8.10 lawyer-first):
          • default (fast=False, medium=False) → main Opus model + max effort
          • medium=True → Sonnet 4.6 (lawyer-facing intermediate tasks)
          • fast=True → Haiku 4.5 (scaffolding ONLY: parse JSON, BM25 lookup)
            takes precedence over medium when both are True (backwards compat).

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

    # V7.5 — class-level semaphore shared across all instances so parallel
    # stage fan-out (ThreadPoolExecutor in brain._run_stages) cannot spawn
    # more than N concurrent `claude -p` subprocesses. The CLI serialises
    # beyond a small concurrency window anyway; pushing 9 at once just
    # stretches wall-clock time to hours without improving throughput.
    # Tunable via CLAUDE_CODE_MAX_CONCURRENCY (default: 3 — empirically
    # the sweet spot on a single subscription).
    _concurrency_sem: threading.Semaphore = threading.Semaphore(
        int(os.getenv("CLAUDE_CODE_MAX_CONCURRENCY", "3"))
    )

    def __init__(
        self,
        model: str = "opus",
        medium_model: str = "sonnet",
        fast_model: str = "sonnet",
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
        self.medium_model = medium_model
        self.fast_model = fast_model
        self.timeout_s = timeout_s
        # Reasoning budget for the main (non-fast) call. Valid values:
        # low, medium, high, xhigh, max. None disables the flag.
        self.effort = effort

    def _pick_model(self, fast: bool, medium: bool) -> str:
        """V8.10 tier selection: fast (Haiku) > medium (Sonnet) > default (Opus)."""
        if fast:
            return self.fast_model
        if medium:
            return self.medium_model
        return self.model

    def complete(self, system, messages, max_tokens=1500, fast=False,
                 medium: bool = False,
                 session_id: str | None = None,
                 attachments: list[Path] | None = None,
                 callsite: str | None = None,
                 user_id: int | None = None,
                 case_id: str | None = None) -> str:
        from .config import ROOT

        # Reset per-call — only meaningful for the current complete().
        self.last_resume_failed = False
        model = self._pick_model(fast, medium)
        tier = _tier_label(fast, medium)
        prompt_serialized = _serialize_prompt(system, messages)
        prompt_hash = _hash16(prompt_serialized)
        t0 = time.time()

        def _emit_audit(*, outcome: str, response_text: str | None,
                        error_class: str | None) -> None:
            _audit_safe(
                callsite=callsite or "unknown",
                backend=self.name,
                model=model,
                tier=tier,
                prompt_hash=prompt_hash,
                response_hash=_hash16(response_text) if response_text else None,
                prompt_raw=_truncate(prompt_serialized) if _AUDIT_STORE_RAW else None,
                response_raw=_truncate(response_text) if (_AUDIT_STORE_RAW and response_text) else None,
                user_id=user_id,
                case_id=case_id,
                latency_ms=int((time.time() - t0) * 1000),
                outcome=outcome,
                error_class=error_class,
                extra={"session_id": session_id, "resumed": bool(session_id)},
            )

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

        # V7.5 — gate concurrent CLI invocations. brain._run_stages fans out
        # up to 9 parallel calls; without this, the subscription rate-limiter
        # serialises them anyway and wall-clock time balloons to ~14 min/stage.
        try:
            with self._concurrency_sem:
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
            _emit_audit(outcome="error", response_text=None,
                        error_class="TimeoutExpired")
            raise RuntimeError(
                f"claude CLI timed out after {self.timeout_s}s"
            ) from exc

        # If --resume failed (session evicted / wrong id), retry fresh once
        # and flag the failure so the caller can invalidate the stale id.
        # Logged at ERROR because the citizen loses conversational context —
        # this is data loss, not a routine warning.
        if proc.returncode != 0 and session_id:
            log.error(
                "claude --resume %s failed (rc=%d): %s — retrying fresh, "
                "conversational context lost",
                session_id, proc.returncode, proc.stderr[-300:].strip(),
            )
            # Audit the failed --resume attempt; the recursive fresh call
            # will audit itself separately on its own success/failure.
            _emit_audit(outcome="error", response_text=None,
                        error_class="ResumeFailed")
            self.last_resume_failed = True
            text = self.complete(
                system, messages, max_tokens, fast, medium=medium,
                session_id=None, attachments=attachments,
                callsite=callsite, user_id=user_id, case_id=case_id,
            )
            # The recursive call cleared the flag on entry; re-raise it so
            # the caller sees the failure signal from the outer invocation.
            self.last_resume_failed = True
            return text

        if proc.returncode != 0:
            _emit_audit(outcome="error", response_text=None,
                        error_class="NonZeroReturnCode")
            raise RuntimeError(
                f"claude CLI failed (rc={proc.returncode}): "
                f"{proc.stderr[-500:].strip() or proc.stdout[-500:].strip()}"
            )

        try:
            data = json.loads(proc.stdout.strip() or "{}")
        except json.JSONDecodeError as exc:
            _emit_audit(outcome="error", response_text=None,
                        error_class="JSONDecodeError")
            raise RuntimeError(
                f"claude CLI non-JSON output: {proc.stdout[:500]}"
            ) from exc

        if data.get("is_error"):
            _emit_audit(outcome="error", response_text=None,
                        error_class="ClaudeCliError")
            raise RuntimeError(
                f"claude CLI reported error: {str(data.get('result', ''))[:500]}"
            )

        new_sid = data.get("session_id")
        if new_sid:
            self.last_session_id = new_sid

        text = (data.get("result") or "").strip()
        if not text:
            _emit_audit(outcome="error", response_text=None,
                        error_class="EmptyResult")
            raise RuntimeError(
                f"claude CLI returned empty result (session={new_sid}, "
                f"stop_reason={data.get('stop_reason')})"
            )
        _emit_audit(outcome="success", response_text=text, error_class=None)
        return text

    # V7.7 — streaming variant. Yields (kind, payload) events:
    #   ("delta", str)   — a text chunk that can be appended to the UI
    #   ("final", dict)  — {"text": full_text, "session_id": sid} — emitted
    #                      once after the stream ends; callers use this to
    #                      persist the final answer + the (possibly new)
    #                      session id. "thinking" deltas are consumed
    #                      internally and NOT forwarded to the citizen.
    def complete_stream(
        self,
        system: str,
        messages: list[Message],
        fast: bool = False,
        medium: bool = False,
        session_id: str | None = None,
        callsite: str | None = None,
        user_id: int | None = None,
        case_id: str | None = None,
    ) -> Iterator[tuple[str, object]]:
        from .config import ROOT

        self.last_resume_failed = False
        model = self._pick_model(fast, medium)
        tier = _tier_label(fast, medium)
        prompt_serialized = _serialize_prompt(system, messages)
        prompt_hash = _hash16(prompt_serialized)
        t0 = time.time()

        def _emit_audit(*, outcome: str, response_text: str | None,
                        error_class: str | None) -> None:
            _audit_safe(
                callsite=callsite or "unknown",
                backend=self.name,
                model=model,
                tier=tier,
                prompt_hash=prompt_hash,
                response_hash=_hash16(response_text) if response_text else None,
                prompt_raw=_truncate(prompt_serialized) if _AUDIT_STORE_RAW else None,
                response_raw=_truncate(response_text) if (_AUDIT_STORE_RAW and response_text) else None,
                user_id=user_id,
                case_id=case_id,
                latency_ms=int((time.time() - t0) * 1000),
                outcome=outcome,
                error_class=error_class,
                extra={"session_id": session_id, "resumed": bool(session_id),
                       "stream": True},
            )

        cmd = [
            self.cli, "-p",
            "--output-format", "stream-json",
            "--include-partial-messages",
            "--verbose",
            "--model", model,
        ]
        if not fast and self.effort:
            cmd.extend(["--effort", self.effort])
        if session_id:
            cmd.extend(["--resume", session_id])
            prompt = _last_user_content(messages)
        else:
            cmd.extend(["--system-prompt", system])
            prompt = _flatten_messages(messages)

        log.debug("claude stream cmd: %s (prompt=%d chars)", cmd, len(prompt))

        collected: list[str] = []
        new_session_id: str | None = None

        # Same semaphore as the blocking path — streaming still holds a
        # CLI slot for its duration, so concurrent streams must queue.
        with self._concurrency_sem:
            proc = subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1,  # line-buffered
                cwd=str(ROOT),
            )
            try:
                assert proc.stdin is not None and proc.stdout is not None
                proc.stdin.write(prompt)
                proc.stdin.close()

                for line in proc.stdout:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        evt = json.loads(line)
                    except json.JSONDecodeError:
                        continue

                    etype = evt.get("type")
                    if etype == "system" and evt.get("subtype") == "init":
                        sid = evt.get("session_id")
                        if sid:
                            new_session_id = sid
                        continue

                    if etype == "stream_event":
                        inner = evt.get("event") or {}
                        if inner.get("type") == "content_block_delta":
                            delta = inner.get("delta") or {}
                            # Only forward visible text; drop thinking deltas.
                            if delta.get("type") == "text_delta":
                                chunk = delta.get("text") or ""
                                if chunk:
                                    collected.append(chunk)
                                    yield ("delta", chunk)
                        continue

                    if etype == "result":
                        if evt.get("is_error"):
                            err = str(evt.get("result", ""))[:500]
                            _emit_audit(outcome="error", response_text=None,
                                        error_class="ClaudeCliError")
                            raise RuntimeError(f"claude CLI error: {err}")
                        sid = evt.get("session_id")
                        if sid:
                            new_session_id = sid
                        # If we missed deltas (no partial messages), fall
                        # back to the full result text for collected.
                        full = evt.get("result") or ""
                        if full and not collected:
                            collected.append(full)
                            yield ("delta", full)
                        continue

                rc = proc.wait(timeout=self.timeout_s)
                if rc != 0:
                    stderr = (proc.stderr.read() if proc.stderr else "")[:500]
                    resume_failed = bool(session_id)
                    if resume_failed:
                        self.last_resume_failed = True
                    # Only raise here if there's no retry path. The resume
                    # retry is handled OUTSIDE the `with` block so the
                    # semaphore is released before we re-acquire it.
                    if not resume_failed:
                        _emit_audit(outcome="error", response_text=None,
                                    error_class="NonZeroReturnCode")
                        raise RuntimeError(
                            f"claude CLI stream failed (rc={rc}): {stderr.strip()}"
                        )
            finally:
                if proc.poll() is None:
                    proc.kill()

        # V7.9 — if --resume failed, retry fresh (same logic as complete()).
        # We do it after releasing the semaphore to avoid deadlocking when
        # the fallback call re-acquires it. The recursive yield-from keeps
        # the streaming contract intact for the caller.
        if self.last_resume_failed and session_id:
            log.error(
                "claude --resume %s stream failed — retrying fresh, "
                "conversational context lost",
                session_id,
            )
            # Audit the failed --resume stream attempt; the recursive fresh
            # call will audit itself separately.
            _emit_audit(outcome="error", response_text=None,
                        error_class="ResumeFailed")
            # Drop any partial deltas from the failed call; the fresh
            # retry will re-stream the answer from scratch.
            collected.clear()
            new_session_id = None
            yield from self.complete_stream(
                system=system, messages=messages, fast=fast, medium=medium,
                session_id=None,
                callsite=callsite, user_id=user_id, case_id=case_id,
            )
            # Re-flag after the recursive call (which reset it on entry)
            # so the outer caller sees the resume-loss signal.
            self.last_resume_failed = True
            return

        if new_session_id:
            self.last_session_id = new_session_id

        text = "".join(collected).strip()
        if not text:
            _emit_audit(outcome="error", response_text=None,
                        error_class="EmptyResult")
            raise RuntimeError(
                f"claude CLI stream returned no text (session={new_session_id})"
            )
        _emit_audit(outcome="success", response_text=text, error_class=None)
        yield ("final", {"text": text, "session_id": new_session_id})

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
            with self._concurrency_sem:
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
                 medium_model: str | None = None,
                 thinking_budget: int = 0):
        from anthropic import Anthropic  # lazy import
        self.client = Anthropic(api_key=api_key)
        self.model = model
        self.medium_model = medium_model or model
        self.fast_model = fast_model
        # Token budget for extended thinking on the main model. 0 disables.
        self.thinking_budget = thinking_budget

    def _pick_model(self, fast: bool, medium: bool) -> str:
        if fast:
            return self.fast_model
        if medium:
            return self.medium_model
        return self.model

    def complete(self, system, messages, max_tokens=1500, fast=False,
                 medium: bool = False,
                 session_id: str | None = None,
                 attachments: list[Path] | None = None,
                 callsite: str | None = None,
                 user_id: int | None = None,
                 case_id: str | None = None) -> str:
        model = self._pick_model(fast, medium)
        tier = _tier_label(fast, medium)
        prompt_serialized = _serialize_prompt(system, messages)
        prompt_hash = _hash16(prompt_serialized)
        t0 = time.time()
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
            model=model,
            max_tokens=max_tokens,
            system=system,
            messages=messages,
        )
        # Extended thinking on the main (non-fast/non-medium) call. Max budget
        # must be less than max_tokens, so we bump max_tokens if needed.
        if not fast and not medium and self.thinking_budget > 0:
            if max_tokens <= self.thinking_budget:
                kwargs["max_tokens"] = self.thinking_budget + 2000
            kwargs["thinking"] = {
                "type": "enabled",
                "budget_tokens": self.thinking_budget,
            }
        try:
            resp = self.client.messages.create(**kwargs)
        except Exception as exc:
            _audit_safe(
                callsite=callsite or "unknown", backend=self.name, model=model,
                tier=tier, prompt_hash=prompt_hash, response_hash=None,
                user_id=user_id, case_id=case_id,
                latency_ms=int((time.time() - t0) * 1000),
                outcome="error", error_class=type(exc).__name__,
                prompt_raw=_truncate(prompt_serialized) if _AUDIT_STORE_RAW else None,
            )
            raise
        # With thinking enabled the first block is the thinking trace;
        # grab the first text block for the actual answer.
        text = ""
        for block in resp.content:
            if getattr(block, "type", None) == "text":
                text = block.text.strip()
                break
        usage = getattr(resp, "usage", None)
        _audit_safe(
            callsite=callsite or "unknown", backend=self.name, model=model,
            tier=tier, prompt_hash=prompt_hash,
            response_hash=_hash16(text) if text else None,
            user_id=user_id, case_id=case_id,
            latency_ms=int((time.time() - t0) * 1000),
            input_tokens=getattr(usage, "input_tokens", None) if usage else None,
            output_tokens=getattr(usage, "output_tokens", None) if usage else None,
            outcome="success",
            prompt_raw=_truncate(prompt_serialized) if _AUDIT_STORE_RAW else None,
            response_raw=_truncate(text) if (_AUDIT_STORE_RAW and text) else None,
        )
        return text

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
                 medium: bool = False,
                 session_id: str | None = None,
                 attachments: list[Path] | None = None,
                 callsite: str | None = None,
                 user_id: int | None = None,
                 case_id: str | None = None) -> str:
        # Gemini backend: no separate medium tier — `medium=True` falls back
        # to the main Pro model (per pivot lawyer-first decision).
        model = self.fast_model if fast else self.model
        tier = _tier_label(fast, medium)
        prompt_serialized = _serialize_prompt(system, messages)
        prompt_hash = _hash16(prompt_serialized)
        t0 = time.time()

        def _emit(outcome: str, response_text: str | None,
                  error_class: str | None) -> None:
            _audit_safe(
                callsite=callsite or "unknown", backend=self.name, model=model,
                tier=tier, prompt_hash=prompt_hash,
                response_hash=_hash16(response_text) if response_text else None,
                user_id=user_id, case_id=case_id,
                latency_ms=int((time.time() - t0) * 1000),
                outcome=outcome, error_class=error_class,
                prompt_raw=_truncate(prompt_serialized) if _AUDIT_STORE_RAW else None,
                response_raw=_truncate(response_text) if (_AUDIT_STORE_RAW and response_text) else None,
            )

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

        try:
            resp = self.client.models.generate_content(
                model=model,
                contents=contents,
                config=self._types.GenerateContentConfig(
                    system_instruction=system,
                    max_output_tokens=max_tokens,
                    temperature=0.3,  # legal work wants consistency
                ),
            )
        except Exception as exc:
            _emit("error", None, type(exc).__name__)
            raise
        text = (resp.text or "").strip()
        if not text:
            _emit("error", None, "EmptyResult")
            raise RuntimeError(
                f"Gemini returned empty response (finish_reason="
                f"{getattr(resp.candidates[0], 'finish_reason', 'unknown') if resp.candidates else 'no-candidate'})"
            )
        _emit("success", text, None)
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
        CLAUDE_CODE_MEDIUM_MODEL,
        CLAUDE_CODE_MODEL,
        CLAUDE_FAST_MODEL,
        CLAUDE_MEDIUM_MODEL,
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
        log.info("using Claude Code backend (%s / %s / %s, effort=%s)",
                 CLAUDE_CODE_MODEL, CLAUDE_CODE_MEDIUM_MODEL,
                 CLAUDE_CODE_FAST_MODEL, CLAUDE_CODE_EFFORT or "off")
        return ClaudeCodeBackend(
            model=CLAUDE_CODE_MODEL,
            medium_model=CLAUDE_CODE_MEDIUM_MODEL,
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
        log.info("using Anthropic backend (%s / %s / %s, thinking=%d)",
                 CLAUDE_MODEL, CLAUDE_MEDIUM_MODEL, CLAUDE_FAST_MODEL,
                 CLAUDE_THINKING_BUDGET)
        return AnthropicBackend(
            ANTHROPIC_API_KEY, CLAUDE_MODEL, CLAUDE_FAST_MODEL,
            medium_model=CLAUDE_MEDIUM_MODEL,
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
