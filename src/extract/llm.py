"""Structured-metadata extraction from a decision text.

We invoke the Claude Code CLI in headless mode (``claude -p``) rather
than calling the Anthropic API directly, because Romeo's setup is
already logged in via OAuth and we want zero extra configuration.

Flow per call:

1. Spawn ``claude -p --model haiku --output-format json --json-schema <S>``
   with the decision text on stdin.
2. Parse the ``structured_output`` field from the JSON response — that
   is the schema-validated extraction result.
3. Map the dict into an :class:`Extraction` dataclass.

The CLI enforces the JSON schema server-side, so we never need to
defensively parse free-form LLM prose.

Cost per call (Haiku 4.5, Apr 2026): ~$0.01–0.04 depending on cache
reuse. For 815 decisions we budget ~$10–15 worst case.
"""
from __future__ import annotations

import json
import logging
import os
import subprocess
from dataclasses import dataclass, field
from typing import Any

from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential_jitter,
)

log = logging.getLogger(__name__)


CLAUDE_BIN = os.getenv("CLAUDE_BIN", "/Users/mac/.local/bin/claude")
EXTRACTION_MODEL = "haiku"  # alias — Claude Code CLI resolves to latest

# Truncate decisions beyond this so we stay well inside Haiku's window
# and keep cost predictable. We keep head + tail so the judges block
# (top) and the "VENDOSI:" dispositivo (bottom) both survive.
MAX_CHARS = 40_000


# Source of truth for the extraction schema. We keep it as a plain
# JSON-schema dict (no Anthropic tool wrapper) because the CLI's
# ``--json-schema`` flag takes exactly this shape.
EXTRACTION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "judges": {
            "type": "array",
            "description": (
                "Judges on the panel (trupi gjykues / kolegji). "
                "Full names exactly as printed."
            ),
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "presiding": {
                        "type": "boolean",
                        "description": "True if labelled Kryesues/Kryetar.",
                    },
                },
                "required": ["name", "presiding"],
            },
        },
        "prosecutors": {
            "type": "array",
            "description": "Prosecutor(s) representing the state.",
            "items": {"type": "string"},
        },
        "lawyers": {
            "type": "array",
            "description": "Defence or civil-side attorneys.",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "representing": {"type": "string"},
                },
                "required": ["name"],
            },
        },
        "parties": {
            "type": "array",
            "description": "Plaintiff/defendant/appellant/respondent names.",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "role": {
                        "type": "string",
                        "enum": [
                            "plaintiff", "defendant", "appellant",
                            "respondent", "third_party", "unknown",
                        ],
                    },
                },
                "required": ["name", "role"],
            },
        },
        "articles_cited": {
            "type": "array",
            "description": (
                "Legal articles cited. Use the Albanian code slug: "
                "kushtetuta, kodi_civil, kodi_proc_civile, kodi_penal, "
                "kodi_proc_penale, kodi_punes, kodi_familjes, "
                "kodi_proc_admin, kodi_doganor, kodi_rrugor, "
                "kodi_zgjedhor, kodi_detar, kodi_ajror. For ECHR "
                "Convention articles use 'convention'."
            ),
            "items": {
                "type": "object",
                "properties": {
                    "code": {"type": "string"},
                    "article": {"type": "string"},
                    "paragraph": {
                        "type": "string",
                        "description": (
                            "Short paragraph/letter reference only "
                            "(e.g. '2', 'a', '3/b'). Max 20 chars. "
                            "DO NOT put law names, dates, or 'Ligji nr...' "
                            "here — omit the field if unknown."
                        ),
                    },
                },
                "required": ["code", "article"],
            },
        },
        "outcome": {
            "type": "string",
            "enum": [
                "convicted", "acquitted", "dismissed",
                "partially_accepted", "accepted", "rejected",
                "remanded", "modified", "settled", "other", "unknown",
            ],
        },
        "summary_sq": {
            "type": "string",
            "description": "One-sentence summary in Albanian, max 300 chars.",
        },
    },
    "required": [
        "judges", "prosecutors", "lawyers", "parties",
        "articles_cited", "outcome", "summary_sq",
    ],
}


SYSTEM_PROMPT = (
    "You are a legal information extraction assistant. You receive the "
    "plain text of a single court decision (Albanian domestic court or "
    "European Court of Human Rights, Albania respondent). Extract the "
    "structured metadata. Rules: (1) Names exactly as written — do not "
    "translate, normalize, or invent. (2) If a field is not stated, "
    "return an empty array or 'unknown'. (3) Output ONLY the JSON "
    "object matching the provided schema. No prose, no markdown."
)


# Tools we deny so the CLI cannot accidentally try to read files, run
# bash, or call any other agent loop during extraction. Keeping this
# list tight also shrinks the injected tool catalogue and cost.
DISALLOWED_TOOLS = (
    "Bash,Edit,Write,Read,Glob,Grep,Agent,TaskCreate,TaskUpdate,TaskList,"
    "TaskGet,TaskStop,TaskOutput,WebFetch,WebSearch,NotebookEdit,"
    "ToolSearch,ScheduleWakeup,Skill,PushNotification,CronCreate,"
    "CronList,CronDelete,RemoteTrigger,Monitor,ExitPlanMode,EnterPlanMode,"
    "EnterWorktree,ExitWorktree,AskUserQuestion"
)


class LLMError(RuntimeError):
    pass


@dataclass
class Extraction:
    judges: list[dict] = field(default_factory=list)
    prosecutors: list[str] = field(default_factory=list)
    lawyers: list[dict] = field(default_factory=list)
    parties: list[dict] = field(default_factory=list)
    articles_cited: list[dict] = field(default_factory=list)
    outcome: str = "unknown"
    summary_sq: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    model: str = EXTRACTION_MODEL


def _truncate(text: str) -> str:
    if len(text) <= MAX_CHARS:
        return text
    half = MAX_CHARS // 2
    return text[:half] + "\n\n[...TRUNCATED...]\n\n" + text[-half:]


class LLMClient:
    """Shells out to ``claude -p`` for each extraction call."""

    def __init__(
        self,
        model: str = EXTRACTION_MODEL,
        claude_bin: str = CLAUDE_BIN,
        timeout_s: int = 120,
    ) -> None:
        if not os.path.exists(claude_bin):
            raise LLMError(f"claude binary not found at {claude_bin}")
        self.model = model
        self.claude_bin = claude_bin
        self.timeout_s = timeout_s

    @retry(
        reraise=True,
        stop=stop_after_attempt(3),
        wait=wait_exponential_jitter(initial=3, max=30),
        retry=retry_if_exception_type(LLMError),
    )
    def extract(self, decision_text: str, hint_context: str = "") -> Extraction:
        text = _truncate(decision_text)
        user_input = text
        if hint_context:
            user_input = f"Context: {hint_context}\n\n---\n\n{text}"

        cmd = [
            self.claude_bin,
            "-p",
            "--model", self.model,
            "--no-session-persistence",
            "--output-format", "json",
            "--system-prompt", SYSTEM_PROMPT,
            "--json-schema", json.dumps(EXTRACTION_SCHEMA),
            "--disallowedTools", DISALLOWED_TOOLS,
        ]

        try:
            proc = subprocess.run(
                cmd,
                input=user_input,
                capture_output=True,
                text=True,
                timeout=self.timeout_s,
            )
        except subprocess.TimeoutExpired as e:
            raise LLMError(f"claude CLI timed out after {self.timeout_s}s") from e

        if proc.returncode != 0:
            raise LLMError(
                f"claude CLI exit={proc.returncode} stderr={proc.stderr[:300]}"
            )

        try:
            payload = json.loads(proc.stdout)
        except json.JSONDecodeError as e:
            raise LLMError(f"claude CLI returned non-JSON: {proc.stdout[:200]}") from e

        if payload.get("is_error"):
            raise LLMError(
                f"claude CLI reported is_error=True: {payload.get('result', '')[:200]}"
            )

        data = payload.get("structured_output")
        if not isinstance(data, dict):
            # Edge case: some runs put the JSON in `result` as a string.
            # Fall back to that before giving up.
            raw = payload.get("result", "")
            if isinstance(raw, str) and raw.strip().startswith("{"):
                try:
                    data = json.loads(raw)
                except json.JSONDecodeError as e:
                    raise LLMError(f"no structured_output and result not JSON") from e
            else:
                raise LLMError(
                    f"no structured_output in response: {json.dumps(payload)[:300]}"
                )

        usage = payload.get("usage") or {}
        return Extraction(
            judges=data.get("judges") or [],
            prosecutors=data.get("prosecutors") or [],
            lawyers=data.get("lawyers") or [],
            parties=data.get("parties") or [],
            articles_cited=data.get("articles_cited") or [],
            outcome=data.get("outcome") or "unknown",
            summary_sq=data.get("summary_sq") or "",
            input_tokens=usage.get("input_tokens") or 0,
            output_tokens=usage.get("output_tokens") or 0,
            cost_usd=float(payload.get("total_cost_usd") or 0.0),
            model=self.model,
        )
