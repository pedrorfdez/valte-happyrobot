"""Coordinator event lane with coalescing.

Events are stored in the events table (audit + retry backstop). Delivery
to the coordinator webhook is a coalesced wake-up, not an event replay:
at most one wake-up is in flight; when it is time to send, ALL pending
coordinator events collapse into one POST carrying a digest and a count.
The agent reads fresh GET /state anyway; old events as individual
messages would only feed it stale reality one bite at a time.

The in-flight gate clears when the agent responds (any POST /actions
calls mark_agent_responded) or after coordinator_cooldown_s."""

import json
import threading
import time
import urllib.request

from ..config import settings
from ..db import current_run_id, js, q

_lock = threading.Lock()
_in_flight_since: float | None = None


def emit_event(run_id: str, type_: str, payload: dict, lane: str = "coordinator"):
    q("insert into events (run_id, type, lane, payload) values (%s,%s,%s,%s)",
      (run_id, type_, lane, js(payload)))
    dispatch_coordinator()  # immediate post-commit attempt


def mark_agent_responded():
    global _in_flight_since
    with _lock:
        _in_flight_since = None
    dispatch_coordinator()


def _gate_open() -> bool:
    global _in_flight_since
    with _lock:
        if _in_flight_since is None:
            return True
        if time.monotonic() - _in_flight_since > settings.coordinator_cooldown_s:
            _in_flight_since = None
            return True
        return False


def dispatch_coordinator():
    """Coalesce all pending coordinator events into one wake-up POST."""
    global _in_flight_since
    if not settings.hr_webhook_coordinator or not _gate_open():
        return
    run_id = current_run_id()
    if not run_id:
        return
    pending = q("""select pk, type, payload, created_at from events
                   where run_id=%s and lane='coordinator' and status='pending'
                   order by pk""", (run_id,))
    if not pending:
        return
    wakeup = {
        "kind": "wakeup",
        "pending_events": len(pending),
        "digest": [{"type": r["type"], **{k: v for k, v in r["payload"].items()
                                          if k in ("signal_id", "tripwire", "action_id",
                                                   "zone", "confidence", "detail", "entity")}}
                   for r in pending[-8:]],
        "instruction": "Read GET /state for current reality; decide and POST /actions.",
    }
    req = urllib.request.Request(
        settings.hr_webhook_coordinator, data=json.dumps(wakeup).encode(),
        headers={"Content-Type": "application/json"}, method="POST")
    try:
        urllib.request.urlopen(req, timeout=5).read()
    except Exception:
        q("update events set attempts = attempts + 1 where run_id=%s and lane='coordinator' and status='pending'",
          (run_id,))
        q("update events set status='dead' where run_id=%s and lane='coordinator' and status='pending' and attempts >= 5",
          (run_id,))
        return
    with _lock:
        _in_flight_since = time.monotonic()
    pks = tuple(r["pk"] for r in pending)
    q("update events set status='sent', sent_at=now() where pk = any(%s)", (list(pks),))


def sweep():
    """Backstop: retry pending events (webhook down earlier, gate expiry)."""
    dispatch_coordinator()
