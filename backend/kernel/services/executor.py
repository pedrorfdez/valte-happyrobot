"""Interim execution layer. Approved world actions must actually happen;
until the HappyRobot voice/SMS tools are wired in, the kernel executes
them itself after a short delay and records a stubbed real_interaction
(marked stubbed: true so the dashboard and judges see the difference).

Non-unit verbs (alerts, road closures, orders) become executed.
Unit verbs (rescue, ...) become in_progress: the units stay committed
while the operation runs; a later PATCH to executed releases them."""

from ..db import current_run_id, js, q

UNIT_VERBS = {"rescue", "pump_water", "shelter", "supplies", "wellness_check", "heavy_equipment"}
EXECUTE_DELAY_S = 5


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
