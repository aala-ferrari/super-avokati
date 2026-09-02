"""Pluggable LLM backends.

Three providers are supported:

- **Tetramorph (subscription)** — headless `claude -p` CLI. No API key, no
  per-token billing; auth lives in the Tetramorph login. Best answer quality
  plus native conversation sessions via `--resume`.
- **Anthropic (Claude Opus 4.8 + Sonnet 4.6)** — API key, paid per call.
- **Google Gemini (2.5 Pro / 2.5 Flash)** — free tier (~1500 req/day on Flash).

The brain uses the `LLMBackend` interface so it never cares which provider
served the call. Selection order:

  1. `BRAIN_BACKEND` env var (`claude_code` | `anthropic` | `gemini`);
  2. `auto` (default): Tetramorph CLI if logged in, else Gemini if key,
     else Anthropic if key, else error.

`session_id` is an optional kwarg on `complete()`:
  - Tetramorph: when provided, uses `--resume <id>` so the CLI carries the
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


def _apply_juris(system):
    """Rete di sicurezza: la giurisdizione della sessione applicata a OGNI
    chiamata al cervello.

    I moduli separati (notaio, perizie, intake, scadenze, segretaria…) non
    la applicavano tutti a mano: in sessione IT rispondevano in albanese con
    diritto albanese. Qui passa tutto, quindi il vincolo non puo' sfuggire.
    apply_jurisdiction e' idempotente, percio' chi la applica gia' a monte
    non viene toccato. Import differito: brain importa backends."""
    if not isinstance(system, str) or not system:
        return system
    try:
        from .brain import apply_current
        return apply_current(system)
    except Exception:  # noqa: BLE001 - non deve mai bloccare una risposta
        return system



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


def _uso_da_risposta(data: dict) -> dict:
    """Estrae il consumo dalla risposta del CLI.

    Il CLI lo restituisce da sempre in `--output-format json`; noi leggevamo
    solo `result` e `session_id`. Quattro numeri distinti, che NON vanno
    sommati come se fossero la stessa cosa:

    - `input_tokens`  — testo nuovo, tariffa piena
    - `cache_write`   — contesto messo in cache, tariffa +25%
    - `cache_read`    — contesto riletto dalla cache, tariffa 10%
    - `output_tokens` — la risposta

    Per questo il costo NON lo ricalcoliamo: `total_cost_usd` arriva gia'
    fatto dal fornitore e tiene conto delle tre tariffe diverse.

    Non solleva mai: un consumo non misurato non deve far fallire una
    risposta legale gia' pronta.
    """
    try:
        u = data.get("usage") or {}
        inp = int(u.get("input_tokens") or 0)
        out = int(u.get("output_tokens") or 0)
        c_w = int(u.get("cache_creation_input_tokens") or 0)
        c_r = int(u.get("cache_read_input_tokens") or 0)
        costo = data.get("total_cost_usd")
        return {
            "input_tokens": inp or None,
            "output_tokens": out or None,
            "cache_write_tokens": c_w or None,
            "cache_read_tokens": c_r or None,
            # micro-dollari interi: si sommano per settimane senza deriva
            "cost_micro_usd": int(round(float(costo) * 1_000_000)) if costo else None,
            # quanto contesto ha davvero occupato la chiamata (punto 5)
            "context_tokens": (inp + c_w + c_r) or None,
        }
    except Exception:  # noqa: BLE001
        return {}


def _audit_safe(**kw) -> None:
    """Best-effort audit log. Never raises."""
    if not kw.get("callsite") or kw.get("callsite") == "unknown":
        kw["callsite"] = _infer_callsite()
    # ⚠️ RIPIEGO, non sostituzione: se il chiamante ha passato l'utente vince
    # lui. Un contesto rimasto appeso in un thread riusato attribuirebbe il
    # lavoro all'utente sbagliato, e un numero falso lo si crede.
    if kw.get("user_id") is None:
        try:
            from .brain import request_user_id
            kw["user_id"] = request_user_id()
        except Exception:  # noqa: BLE001
            pass
    # ⚠️ Vicino al tetto: se una chiamata lo sfonda, il CLI compatta o tronca
    # a META' di un'analisi legale e la risposta arriva lo stesso, costruita
    # su un contesto riassunto. Un errore invisibile e' peggio di un errore.
    # Qui non si blocca nulla: si lascia una traccia leggibile PRIMA che
    # diventi un fallimento.
    try:
        _ctx = int(kw.get("context_tokens") or 0)
        if _ctx:
            from .config import CONTEXT_ALERT_TOKENS
            if _ctx >= CONTEXT_ALERT_TOKENS:
                log.warning(
                    "contesto vicino al tetto: %s token (%s) — soglia %s",
                    f"{_ctx:,}", kw.get("callsite"), f"{CONTEXT_ALERT_TOKENS:,}",
                )
    except Exception:  # noqa: BLE001
        pass
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

        Tier selection (V9.x lawyer-first, Haiku rimosso):
          • default (fast=False, medium=False) → main Opus model + max effort
          • medium=True → Sonnet 4.6 (lawyer-facing intermediate tasks)
          • fast=True → Sonnet 4.6 (scaffolding: parse JSON, BM25 lookup)
            takes precedence over medium when both are True (backwards compat).

        `attachments`, when provided, is a list of file paths (PDF/JPG/PNG/
        etc.) that the model should read natively — same spirit as a user
        pasting an image into a chat. Backends that don't support it will
        ignore the argument and rely on any OCR text already in `messages`.
        """

    def ocr_image(self, path: Path, mimetype: str, prompt: str,
                  istruzione_finale: str | None = None) -> str:
        """OCR an image file. Backends that don't support vision raise.

        `istruzione_finale` sostituisce la riga di coda predefinita («restituisci
        solo il testo estratto»). Serve a chi non vuole estrarre testo ma
        **descrivere** l'immagine — i fotogrammi di un video: con la coda
        predefinita il modello riceve due istruzioni opposte, se ne accorge, e
        scrive un paragrafo sul conflitto invece della scena.

        Default: unsupported. Override in subclasses that have vision.
        """
        raise NotImplementedError(
            f"backend '{self.name}' does not support vision OCR"
        )


# ── Da dove parte il cervello ──────────────────────────────────────────
#
# NON da `ROOT` (cioe' `/app`). La cartella di lavoro di un processo e'
# sempre leggibile dai suoi strumenti, qualunque limite si metta a `Read`:
# partendo da `/app` il modello arrivava a `src/` (il sorgente) e a
# `data/app.db` (le cause di tutti gli studi). Verificato in produzione —
# «Il file /app/src/config.py ha 422 righe».
#
# Da una cartella vuota, con lo stesso identico comando, la risposta diventa
# «Non ho i permessi per leggere quel file». Gli allegati non ne soffrono:
# arrivano con percorso assoluto e sono autorizzati uno per uno.
#
# Fissa e riusabile invece che una per chiamata: la CLI ci scrive i suoi file
# di sessione, e una cartella nuova a ogni richiesta lascerebbe rifiuti a ogni
# giro. Dentro non c'e' niente da rubare.
_CWD_CERVELLO = Path(os.environ.get("BRAIN_CWD", "/tmp/brain-cwd"))
try:
    _CWD_CERVELLO.mkdir(parents=True, exist_ok=True)
except OSError:  # sistema in sola lettura: si ripiega su una temporanea
    import tempfile
    _CWD_CERVELLO = Path(tempfile.mkdtemp(prefix="brain-cwd-"))


# ── Tetramorph (headless CLI, subscription auth) ─────────────────────────

class ClaudeCodeBackend(LLMBackend):
    """Invokes the `claude` CLI in headless `-p` mode.

    Pipeline stages wire into this as follows:
      * triage / strategic (stateless analytical JSON): `session_id=None`
        → fresh call, system prompt set via `--system-prompt`, history
        flattened into the piped prompt.
      * answer composition (conversational): `session_id=<flask-tracked>`
        → `--resume <id>` so Tetramorph preserves the thread with the
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
    _concurrency_sem: threading.Semaphore = threading.Semaphore(6)  # 6 menti parallele Genio (forzato)

    def __init__(
        self,
        model: str = "opus",
        medium_model: str = "sonnet",
        fast_model: str = "sonnet",
        cli_path: str | None = None,
        timeout_s: int = 1800,
        effort: str | None = "max",
    ):
        self.cli = cli_path or shutil.which("claude")
        if not self.cli:
            raise RuntimeError(
                "Tetramorph not found in PATH. Install Tetramorph "
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
        """V9.x tier selection: fast (Sonnet) > medium (Sonnet) > default (Opus)."""
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
                 case_id: str | None = None,
                 model_override: str | None = None) -> str:
        system = _apply_juris(system)  # giurisdizione della sessione

        # Reset per-call — only meaningful for the current complete().
        self.last_resume_failed = False
        # model_override lets an ADDITIVE feature pick a specific model (e.g.
        # Fable for the second-advisor pass) without touching tier routing.
        model = model_override or self._pick_model(fast, medium)
        tier = _tier_label(fast, medium)
        prompt_serialized = _serialize_prompt(system, messages)
        prompt_hash = _hash16(prompt_serialized)
        t0 = time.time()

        def _emit_audit(*, outcome: str, response_text: str | None,
                        error_class: str | None, uso: dict | None = None) -> None:
            _audit_safe(
                **(uso or {}),
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
        # Valvola di sicurezza, DISATTIVATA per scelta (vedi config.py):
        # fermare un'analisi legale a meta' per risparmiare centesimi e' un
        # cattivo affare. Esiste per il giorno in cui servisse.
        try:
            from .config import TETRAMORPH_MAX_BUDGET_USD as _tetto
            if _tetto:
                cmd.extend(["--max-budget-usd", _tetto])
        except Exception:  # noqa: BLE001
            pass

        # Extended thinking: Opus ragiona sulle questioni legali difficili
        # prima di scrivere. Vale anche per i modelli scelti esplicitamente
        # (Fable per Avvocato del Diavolo / secondo parere / drafter): prima
        # la condizione `not model_override` li escludeva, quindi rispondevano
        # senza ragionamento esteso. Il percorso veloce resta senza effort.
        if not fast and self.effort:
            cmd.extend(["--effort", self.effort])

        # --resume DISABILITATO: in headless -p le sessioni non persistono
        # ("No conversation found"). Sempre system-prompt + history completa,
        # cosi i follow-up mantengono il contesto e non ripetono/errorano.
        cmd.extend(["--system-prompt", system])
        prompt = _flatten_messages(messages)

        # If the caller has files to attach (dossier), hand them to Claude
        # via the Read tool — same UX as pasting an image into a chat.
        # Allow directories that contain each file so Read can access them.
        # Strumenti del cervello: per le chiamate ragionate (non-fast: Genio,
        # risposta strategica) abilita la RICERCA WEB (leggi aggiornate +
        # precedenti pubblici) e, se ci sono allegati, il Read del dossier.
        _tools = ["WebSearch", "WebFetch"] if not fast else []
        seen_dirs: set[str] = set()
        file_list_lines: list[str] = []
        if attachments:
            for p in attachments:
                ap = Path(p).resolve()
                seen_dirs.add(str(ap.parent))
                file_list_lines.append(f"- {ap}")
            # Read LIMITATO alle cartelle degli allegati di QUESTA chiamata.
            #
            # Prima era `Read` nudo con `--permission-mode bypassPermissions`,
            # e quel bypass toglie ogni confine sul filesystem: il cervello
            # leggeva /app/src/*.py (il sorgente) e qualunque altro file
            # dell'utente che lo esegue. Verificato in produzione.
            #
            # Due cose NON bastano, provate: cambiare la cartella di lavoro
            # (legge lo stesso con percorso assoluto) e limitare Read
            # lasciando il bypass (il bypass scavalca l'elenco). L'unica cosa
            # che chiude e' TOGLIERE il bypass.
            for d in sorted(seen_dirs):
                _tools.append(f"Read({d}/**)")
        if _tools:
            # niente `--permission-mode`: sarebbe il bypass a riaprire tutto.
            # `--allowedTools` e' variadico e qui resta in coda — funziona
            # perche' il prompt viaggia su stdin (`input=prompt`). Se un
            # giorno lo si passasse come argomento, la CLI se lo mangerebbe
            # come nome di tool.
            cmd.extend(["--allowedTools", *_tools])
        if attachments:
            for d in sorted(seen_dirs):
                cmd.extend(["--add-dir", d])
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
        # V9.9 — retry me backoff kur backend-i eshte i zene (rate limit/overload).
        # Genio-ja niset me 6 mendje paralele: nese kapin limitin, presim e riprovojme
        # ne vend qe te dështojmë. Saktesia para shpejtesise; jitter per te shmangur
        # thundering-herd kur te gjitha stagjet riprovojne njeheresh.
        _rl_max = int(os.environ.get("TETRAMORPH_RETRY_MAX", "4"))
        _rl_base = int(os.environ.get("TETRAMORPH_RETRY_WAIT", "20"))
        proc = None
        for _rl_try in range(_rl_max + 1):
            try:
                with self._concurrency_sem:
                    proc = subprocess.run(
                        cmd,
                        input=prompt,
                        capture_output=True,
                        text=True,
                        encoding="utf-8",
                        errors="replace",
                        timeout=self.timeout_s,
                        cwd=str(_CWD_CERVELLO),
                        check=False,
                    )
            except subprocess.TimeoutExpired as exc:
                _emit_audit(outcome="error", response_text=None,
                            error_class="TimeoutExpired")
                raise RuntimeError(
                    f"Tetramorph timed out after {self.timeout_s}s"
                ) from exc
            _rl_blob = " ".join([str(proc.stderr or ""), str(proc.stdout or "")]).lower()
            _rl_busy = proc.returncode != 0 and any(
                k in _rl_blob for k in ("usage limit", "session limit", "rate limit",
                                        "429", "quota", "overloaded", "529", "503", "overload"))
            if _rl_busy and _rl_try < _rl_max:
                _rl_wait = _rl_base * (_rl_try + 1) + (abs(hash(prompt)) % 8)
                log.warning("Tetramorph i zene (prova %d/%d) — pres %ds pastaj riprovoj",
                            _rl_try + 1, _rl_max, _rl_wait)
                time.sleep(_rl_wait)
                continue
            break

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
            raise RuntimeError(_humanize_cli_failure(
                proc.returncode, proc.stdout, proc.stderr))

        try:
            data = json.loads(proc.stdout.strip() or "{}")
        except json.JSONDecodeError as exc:
            _emit_audit(outcome="error", response_text=None,
                        error_class="JSONDecodeError")
            log.warning("Tetramorph non-JSON output: %s", proc.stdout[:500])
            raise RuntimeError(_humanize_cli_failure(stdout=proc.stdout)) from exc

        if data.get("is_error"):
            _emit_audit(outcome="error", response_text=None,
                        error_class="ClaudeCliError")
            raise RuntimeError(_humanize_cli_failure(
                result=str(data.get('result', ''))))

        new_sid = data.get("session_id")
        if new_sid:
            self.last_session_id = new_sid

        text = (data.get("result") or "").strip()
        if not text:
            _emit_audit(outcome="error", response_text=None,
                        error_class="EmptyResult")
            raise RuntimeError(
                f"Tetramorph returned empty result (session={new_sid}, "
                f"stop_reason={data.get('stop_reason')})"
            )
        # ⚠️ Il consumo si legge QUI, dall'unica risposta che ce l'ha. Se
        # non lo si prende adesso, e' perso per sempre — e' esattamente quello
        # che e' successo alle prime 1.281 chiamate.
        _emit_audit(outcome="success", response_text=text, error_class=None,
                    uso=_uso_da_risposta(data))
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
        system = _apply_juris(system)  # giurisdizione della sessione

        self.last_resume_failed = False
        model = self._pick_model(fast, medium)
        tier = _tier_label(fast, medium)
        prompt_serialized = _serialize_prompt(system, messages)
        prompt_hash = _hash16(prompt_serialized)
        t0 = time.time()
        # riempito dall'evento `result` in fondo allo stream
        _uso_finale: dict = {}

        def _emit_audit(*, outcome: str, response_text: str | None,
                        error_class: str | None, uso: dict | None = None) -> None:
            _audit_safe(
                **(uso or {}),
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
        # --resume DISABILITATO: in headless -p le sessioni non persistono
        # ("No conversation found"). Sempre system-prompt + history completa,
        # cosi i follow-up mantengono il contesto e non ripetono/errorano.
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
                encoding="utf-8",
                errors="replace",
                bufsize=1,  # line-buffered
                cwd=str(_CWD_CERVELLO),
            )
            # Drain stderr on a side thread — a chatty --verbose CLI must never
            # fill the stderr pipe and deadlock the stdout read loop.
            _stderr_buf: list[str] = []
            _st = threading.Thread(
                target=lambda p=proc.stderr: _stderr_buf.extend(p) if p else None,
                daemon=True,
            )
            _st.start()
            # Watchdog — a stalled CLI must not hold a semaphore slot forever.
            _killer = threading.Timer(
                self.timeout_s,
                lambda p=proc: p.kill() if p.poll() is None else None,
            )
            _killer.daemon = True
            _killer.start()
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
                        # Anche in streaming l'evento finale porta il
                        # consumo: si mette da parte per la riga di audit,
                        # che viene scritta piu' sotto.
                        _uso_finale.update(_uso_da_risposta(evt))
                        if evt.get("is_error"):
                            err = str(evt.get("result", ""))[:500]
                            _emit_audit(outcome="error", response_text=None,
                                        error_class="ClaudeCliError")
                            raise RuntimeError(_humanize_cli_failure(stderr=err))
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
                _st.join(timeout=2)
                if rc != 0:
                    stderr = ("".join(_stderr_buf))[:500]
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
                            _humanize_cli_failure(rc, "", stderr)
                        )
            finally:
                _killer.cancel()
                if proc.poll() is None:
                    proc.kill()
                try:
                    proc.wait(timeout=5)  # reap, avoid zombies
                except Exception:  # noqa: BLE001
                    pass

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
                f"Tetramorph stream returned no text (session={new_session_id})"
            )
        _emit_audit(outcome="success", response_text=text, error_class=None,
                    uso=dict(_uso_finale))
        yield ("final", {"text": text, "session_id": new_session_id})

    def ocr_image(self, path: Path, mimetype: str, prompt: str,
                  istruzione_finale: str | None = None) -> str:
        """OCR via `claude -p` with the Read tool. Uses the subscription —
        no API key required. The model's Read tool handles PNG/JPG natively."""
        abs_path = Path(path).resolve()
        # Allow Claude to Read files from the image's directory. This covers
        # both persistent uploads (data/uploads/<case>/) and temp-file pages
        # we write during PDF rasterization.
        extra_dir = str(abs_path.parent)
        coda = istruzione_finale or (
            "Read this file and return ONLY the extracted text. "
            "No commentary, no summary, no markdown fences."
        )
        full_prompt = f"{prompt}\n\nFile: {abs_path}\n{coda}"
        cmd = [
            self.cli, "-p",
            "--output-format", "json",
            "--model", self.fast_model,
            # stessa gabbia dell'altro percorso: Read solo dove sta
            # l'immagine, e nessun bypass che la scavalchi.
            "--allowedTools", f"Read({extra_dir}/**)",
            "--add-dir", extra_dir,
        ]
        try:
            with self._concurrency_sem:
                proc = subprocess.run(
                    cmd, input=full_prompt, capture_output=True, text=True,
                    timeout=self.timeout_s, cwd=str(_CWD_CERVELLO), check=False,
                )
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError(
                f"Tetramorph OCR timed out after {self.timeout_s}s"
            ) from exc
        if proc.returncode != 0:
            raise RuntimeError(
                f"Tetramorph OCR failed (rc={proc.returncode}): "
                f"{proc.stderr[-400:].strip() or proc.stdout[-400:].strip()}"
            )
        try:
            data = json.loads(proc.stdout.strip() or "{}")
        except json.JSONDecodeError as exc:
            raise RuntimeError(
                f"Tetramorph OCR non-JSON output: {proc.stdout[:400]}"
            ) from exc
        if data.get("is_error"):
            raise RuntimeError(
                f"Tetramorph OCR reported error: {str(data.get('result', ''))[:400]}"
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
        system = _apply_juris(system)  # giurisdizione della sessione
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
        system = _apply_juris(system)  # giurisdizione della sessione
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


# ── prompt flattening helpers (for Tetramorph -p mode) ───────────────────

def _last_user_content(messages: list[Message]) -> str:
    for m in reversed(messages):
        if m.get("role") == "user":
            return str(m.get("content", ""))
    return ""


def _humanize_cli_failure(rc=None, stdout="", stderr="", result=""):
    """Errore tecnico del CLI -> messaggio pulito per l'utente (shqip), senza
    esporre JSON grezzo o il vendor. Rileva i limiti d'uso e il sovraccarico."""
    blob = " ".join([str(stderr or ""), str(stdout or ""), str(result or "")]).lower()
    if any(k in blob for k in ("session limit", "usage limit", "rate limit", "429", "quota")):
        return ("Tetramorph eshte i zene me shume kerkesa per momentin. "
                "Te lutem provo serish pas disa minutash.")
    if any(k in blob for k in ("overloaded", "529", "503", "overload")):
        return "Tetramorph eshte perkohesisht i mbingarkuar. Provo serish pas pak."
    return "Tetramorph hasi nje problem teknik te perkohshem. Provo serish."


def _flatten_messages(messages: list[Message]) -> str:
    """Flatten a message history into one piped-stdin prompt for `claude -p`.

    Only used on FRESH sessions (no --resume). Tetramorph's -p takes a
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
        # Prefer Tetramorph CLI when available — best quality, uses the
        # user's subscription, and supports native conversation sessions.
        if cli_available:
            choice = "claude_code"
        elif GEMINI_API_KEY:
            choice = "gemini"
        elif ANTHROPIC_API_KEY:
            choice = "anthropic"
        else:
            raise RuntimeError(
                "No LLM available. Install Tetramorph (`claude /login`), "
                "or set GEMINI_API_KEY / ANTHROPIC_API_KEY in .env."
            )

    if choice in ("claude_code", "claude-code", "claudecode"):
        if not cli_available:
            raise RuntimeError(
                "BRAIN_BACKEND=claude_code but `claude` CLI is not in PATH. "
                "Install Tetramorph and run `claude /login`."
            )
        log.info("using Tetramorph backend (%s / %s / %s, effort=%s)",
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
