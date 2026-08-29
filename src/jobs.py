"""In-process registry for long answers that must outlive the connection.

The brain takes minutes. Until now that work ran *inside* the HTTP request:
the browser held an open connection for the whole thing, and if the
connection died the work died with it. On a phone that is not an edge case,
it is the normal case — the moment the user switches to WhatsApp the OS
suspends the tab, the socket drops, and the lawyer gets a red "network
error" for an answer the server was perfectly capable of producing.

So the work moves here. `POST /api/ask/start` registers a job and returns
immediately; a thread runs the brain and appends the SSE frames it produces
to the job. `GET /api/ask/events` replays the frames from any index and then
follows the live ones. Reconnecting is just asking again from where you
stopped — which means a dropped connection costs a second, not an answer.

The frames are stored already formatted (`data: {...}\n\n`). Replaying is
then a copy, with no chance of serialising them differently the second time
around than the first.

Kept in memory on purpose: a job is worth something for the minutes it runs
and the short while after, and the answer itself is persisted by the brain's
own finalisation into the case. Losing a job registry on restart loses
nothing that matters. What it does buy is that this file cannot corrupt the
database.
"""
from __future__ import annotations

import logging
import threading
import time
import uuid
from dataclasses import dataclass, field

log = logging.getLogger(__name__)

# How long a finished job stays available for a client that comes back late
# (phone in a pocket, tab reopened tomorrow morning). Long enough to be
# useful, short enough that memory cannot creep.
KEEP_FINISHED_S = 30 * 60

# A job that never finishes — a thread wedged on a hung backend — must not
# stay in memory forever.
KEEP_RUNNING_S = 2 * 60 * 60


@dataclass
class Job:
    id: str
    user_id: int
    case_id: str
    frames: list[str] = field(default_factory=list)
    done: bool = False
    started: float = field(default_factory=time.monotonic)
    finished: float | None = None


_jobs: dict[str, Job] = {}
_lock = threading.Lock()


def _purge_locked() -> None:
    now = time.monotonic()
    dead = [
        j.id for j in _jobs.values()
        if (j.done and j.finished is not None and now - j.finished > KEEP_FINISHED_S)
        or (not j.done and now - j.started > KEEP_RUNNING_S)
    ]
    for jid in dead:
        _jobs.pop(jid, None)
    if dead:
        log.info("jobs: purged %d stale job(s)", len(dead))


def create(user_id: int, case_id: str) -> str:
    jid = uuid.uuid4().hex
    with _lock:
        _purge_locked()
        _jobs[jid] = Job(id=jid, user_id=user_id, case_id=case_id)
    return jid


def push(job_id: str, frame: str) -> None:
    """Append one already-formatted SSE frame."""
    with _lock:
        job = _jobs.get(job_id)
        if job is not None and not job.done:
            job.frames.append(frame)


def finish(job_id: str) -> None:
    with _lock:
        job = _jobs.get(job_id)
        if job is not None and not job.done:
            job.done = True
            job.finished = time.monotonic()


def get(job_id: str) -> Job | None:
    with _lock:
        return _jobs.get(job_id)


def slice_from(job_id: str, since: int) -> tuple[list[str], bool, int]:
    """Frames from `since` onward, whether the job is over, and the new index.

    Returned together under one lock so a client can never be told "nothing
    new, and it is finished" while a frame is being appended between the two
    questions — which would silently truncate the last piece of an answer.
    """
    with _lock:
        job = _jobs.get(job_id)
        if job is None:
            return [], True, since
        chunk = job.frames[since:]
        return chunk, job.done, since + len(chunk)


def find_active(user_id: int, case_id: str) -> str | None:
    """Il lavoro ancora in corso per questo fascicolo, se c'e'.

    Serve a distinguere i due casi che dal client sembrano identici: una
    domanda senza risposta perche' il cervello sta ancora pensando (e allora
    ci si riattacca) e una senza risposta perche' il lavoro e' morto con un
    riavvio (e allora si dice e si offre di rilanciare).

    Vincolato all'utente di proposito: il registro dei lavori e' un elenco di
    chi sta chiedendo cosa, e non deve poterlo leggere nessun altro.

    Il piu' recente se per caso ce ne fossero due — e' quello che l'avvocato
    si aspetta di vedere.
    """
    with _lock:
        vivi = [j for j in _jobs.values()
                if not j.done and j.user_id == user_id and j.case_id == case_id]
        if not vivi:
            return None
        vivi.sort(key=lambda j: j.started, reverse=True)
        return vivi[0].id


def stats() -> dict:
    with _lock:
        running = sum(1 for j in _jobs.values() if not j.done)
        return {"jobs": len(_jobs), "running": running}
