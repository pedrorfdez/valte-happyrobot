"""Interim execution layer. Approved world actions must actually happen;
until the HappyRobot voice/SMS tools are wired in, the kernel executes
them itself after a short delay and records a stubbed real_interaction
(marked stubbed: true so the dashboard and judges see the difference).

Non-unit verbs (alerts, road closures, orders) become executed.
Unit verbs (rescue, ...) become in_progress: the units stay committed
while the operation runs; a later PATCH to executed releases them."""

from datetime import datetime, timedelta

from ..db import current_run_id, js, q

UNIT_VERBS = {"rescue", "pump_water", "shelter", "supplies", "wellness_check", "heavy_equipment"}
EXECUTE_DELAY_S = 5

# scenario minutes an operation runs before its units come back
DEFAULT_DURATION_MIN = {"rescue": 45, "pump_water": 60, "shelter": 120,
                        "supplies": 60, "wellness_check": 30, "heavy_equipment": 90}


def execute_approved():
    rid = current_run_id()
    if not rid:
        return
    rows = q("""select a.id, a.verb, a.doc, e.doc as actor_doc
                from actions a left join entities e
                  on e.run_id = a.run_id and e.id = a.actor
                where a.run_id=%s and a.status='approved'
                  and a.created_at < now() - make_interval(secs => %s)""",
             (rid, EXECUTE_DELAY_S))
    for r in rows:
        doc = r["doc"]
        channel = (r["actor_doc"] or {}).get("channel") or {}
        kind = channel.get("kind") if channel.get("kind") in ("voice", "email", "sms") else "sms"
        new_status = "in_progress" if r["verb"] in UNIT_VERBS else "executed"
        doc["status"] = new_status
        doc["real_interaction"] = {"kind": kind,
                                   "to": channel.get("address", "unknown"),
                                   "stubbed": True}
        q("update actions set status=%s, doc=%s where run_id=%s and id=%s",
          (new_status, js(doc), rid, r["id"]))


def complete_operations():
    """Operations end: in_progress unit actions whose duration (scenario
    minutes, params.duration_min or a per-verb default) has elapsed become
    executed and their units return to the pool. Without this, every
    rescue permanently consumes its units."""
    rid = current_run_id()
    if not rid:
        return
    newest = q("select max(t) as m from signals where run_id=%s", (rid,), one=True)
    if not newest or not newest["m"]:
        return
    now = newest["m"]
    rows = q("select id, verb, t, doc from actions where run_id=%s and status='in_progress'", (rid,))
    for r in rows:
        duration = (r["doc"].get("params") or {}).get(
            "duration_min", DEFAULT_DURATION_MIN.get(r["verb"], 60))
        started = r["t"]
        if now < started + timedelta(minutes=float(duration)):
            continue
        doc = r["doc"]
        doc["status"] = "executed"
        doc["result_note"] = f"operation completed after {duration} scenario minutes"
        q("update actions set status='executed', doc=%s where run_id=%s and id=%s",
          (js(doc), rid, r["id"]))
        released = q("""update assignments set status='released', released_at=now()
                        where run_id=%s and action_id=%s and status='active'
                        returning entity_id, units""", (rid, r["id"]))
        for a in released or []:
            q("update entities set units_available = units_available + %s where run_id=%s and id=%s",
              (a["units"], rid, a["entity_id"]))
