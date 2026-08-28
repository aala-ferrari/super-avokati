"""Notifications for answers that finish while nobody is watching.

The brain takes minutes. Before this, a lawyer who asked a question had to
keep the tab open and look at it — which is exactly what nobody does with a
phone. Now the work survives the page (see `jobs.py`), so the last missing
piece is telling the user it is ready.

Nothing here is allowed to break an answer. Every send is wrapped, failures
are logged and swallowed, and a subscription that the push service rejects as
gone (404/410) is deleted rather than retried forever. If this whole file
throws, the lawyer still gets the answer — they just have to look for it.
"""
from __future__ import annotations

import json
import logging
import os
import threading

log = logging.getLogger(__name__)

VAPID_PRIVATE_KEY = os.environ.get("VAPID_PRIVATE_KEY", "")
VAPID_PUBLIC_KEY = os.environ.get("VAPID_PUBLIC_KEY", "")
VAPID_SUBJECT = os.environ.get("VAPID_SUBJECT", "mailto:info@aala.global")


def configurato() -> bool:
    """True when the server can actually sign a push."""
    if not (VAPID_PRIVATE_KEY and VAPID_PUBLIC_KEY):
        return False
    try:
        import pywebpush  # noqa: F401
    except Exception:
        return False
    return True


def _invia_una(sub: dict, payload: dict) -> str:
    """Send to one subscription. Returns 'ok', 'gone' or 'error'."""
    from pywebpush import WebPushException, webpush

    try:
        webpush(
            subscription_info={
                "endpoint": sub["endpoint"],
                "keys": {"p256dh": sub["p256dh"], "auth": sub["auth"]},
            },
            data=json.dumps(payload, ensure_ascii=False),
            vapid_private_key=VAPID_PRIVATE_KEY,
            vapid_claims={"sub": VAPID_SUBJECT},
            timeout=10,
        )
        return "ok"
    except WebPushException as exc:
        stato = getattr(getattr(exc, "response", None), "status_code", None)
        # 404/410: the browser threw the subscription away (app uninstalled,
        # notifications revoked). Keeping it would mean failing forever.
        if stato in (404, 410):
            return "gone"
        log.warning("push failed (%s): %s", stato, str(exc)[:200])
        return "error"
    except Exception as exc:  # noqa: BLE001
        log.warning("push failed: %s", str(exc)[:200])
        return "error"


def avvisa(storage, user_id: int, titolo: str, corpo: str,
           url: str = "/", tag: str = "sa") -> None:
    """Notify every device the user registered. Never raises.

    Runs in its own thread: a push service that takes ten seconds to answer
    must not hold up whatever finished the work.
    """
    if not configurato():
        return

    def _lavora() -> None:
        try:
            subs = storage.list_push_subscriptions(user_id)
        except Exception as exc:  # noqa: BLE001
            log.warning("push: cannot read subscriptions: %s", exc)
            return
        if not subs:
            return
        payload = {"title": titolo, "body": corpo, "url": url, "tag": tag}
        for sub in subs:
            esito = _invia_una(sub, payload)
            if esito == "gone":
                try:
                    storage.delete_push_subscription(sub["endpoint"])
                    log.info("push: dropped dead subscription for user %s", user_id)
                except Exception:
                    pass

    threading.Thread(target=_lavora, name="push-%s" % user_id,
                     daemon=True).start()
