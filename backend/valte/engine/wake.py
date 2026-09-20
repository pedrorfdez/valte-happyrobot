"""When to spend a HappyRobot run on thinking.

Tactical brain (coordinator): woken by material events, debounced and
single-flight. Strategic brain (crisis-command): woken only when the plan
no longer describes the world. Both are rate limited: a run costs credits.
"""

import json
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from valte.core import plan as plan_core
from valte.core.events import append_event
from valte.core.world import active_plan, build_snapshot, build_state, environment_of, scenario_now
from valte.engine import local_brain
from valte.hr import registry
from valte.models import Crisis, Event, Incident, Outbox, Zone, utcnow
from valte.settings import public_base_url

# Decisions follow the data: a short debounce to coalesce a burst, then think. Single-flight keeps the cost bounded.
COORD_DEBOUNCE_S, COORD_MIN_INTERVAL_S, COORD_TIMEOUT_S = 2, 8, 45
CMD_MIN_INTERVAL_S, CMD_TIMEOUT_S = 45, 70
MAX_WAKES = 150  # credit guard per crisis


def _age(iso: str | None) -> float:
    return (utcnow() - datetime.fromisoformat(iso)).total_seconds() if iso else 1e9


def _save(c: Crisis, w: dict[str, Any]) -> None:
    c.wake = dict(w)


def coordinator_done(c: Crisis) -> None:
    w = dict(c.wake or {})
    w.pop("coord_inflight", None)
    _save(c, w)


def command_done(c: Crisis) -> None:
    w = dict(c.wake or {})
    w.pop("cmd_inflight", None)
    _save(c, w)


def _instruction(db: Session, c: Crisis) -> str:
    from valte.core.needs import open_needs

    waiting = open_needs(db, c)
    line = "Decide what to do NOW given the digest and the state. Output only new actions."
    if waiting:
        line += (f" {len(waiting)} open need(s) have nobody assigned: "
                 + ", ".join(f"{n['signal_id']} ({n['zone']}, sev {n['severity']}, {n['waiting_min']} min waiting)" for n in waiting[:6])
                 + ". Assign resources to each, most severe first, or say who waits and why.")
    return line


def maybe_wake_coordinator(db: Session, c: Crisis) -> None:
    w = dict(c.wake or {})
    if w.get("coord_inflight"):
        if _age(w.get("coord_since")) < COORD_TIMEOUT_S:
            return
        append_event(db, c, "hr.error", {"what": "coordinator did not answer", "dispatch": w["coord_inflight"]})
        w.pop("coord_inflight")
        _save(c, w)

    events = list(db.scalars(select(Event).where(Event.crisis_id == c.id, Event.material.is_(True),
                                                 Event.seq > int(w.get("coord_seq", 0)))
                             .order_by(Event.seq).limit(30)))
    if not events:
        return
    if (utcnow() - events[0].wall).total_seconds() < COORD_DEBOUNCE_S and len(events) < 6:
        return  # let the burst finish: one wake for the whole cluster
    if _age(w.get("coord_last")) < COORD_MIN_INTERVAL_S or int(w.get("wakes", 0)) >= MAX_WAKES:
        return

    digest = [{"type": e.type, "t": e.t.isoformat(), "detail": e.digest or ""} for e in events]
    w.update(coord_seq=events[-1].seq, coord_last=utcnow().isoformat(), wakes=int(w.get("wakes", 0)) + 1)
    dispatch_id = f"coord-{uuid.uuid4().hex[:10]}"
    use_hr = registry.usable(db, registry.COORDINATOR)
    append_event(db, c, "brain.wake", {"brain": "coordinator", "dispatch_id": dispatch_id, "digest": digest,
                                      "via": "happyrobot" if use_hr else "local"})
    if use_hr:
        w.update(coord_inflight=dispatch_id, coord_since=utcnow().isoformat())
        db.add(Outbox(crisis_id=c.id, kind="hr_run", workflow=registry.COORDINATOR, purpose="coordinator",
                      ref_id=dispatch_id, payload={
                          "crisis_id": c.id, "dispatch_id": dispatch_id, "callback_base": public_base_url(),
                          "kind": "wakeup", "pending_events": len(digest), "digest": digest,
                          "instruction": _instruction(db, c), "environment": environment_of(db, c),
                          "state_json": json.dumps(build_state(db, c), ensure_ascii=False)}))
        _save(c, w)
    else:
        _save(c, w)
        local_brain.decide(db, c)


def _replan_reason(db: Session, c: Crisis) -> str | None:
    w = c.wake or {}
    if w.get("replan_requested"):
        return f"human requested a re-plan: {w['replan_requested']}"
    current = active_plan(db, c.id)
    if current is None:
        hot = db.scalars(select(Zone).where(Zone.crisis_id == c.id, Zone.severity_est >= 4)).first()
        return "first plan: a zone reached severity 4" if hot else None
    if current.invalidated_reason:
        return current.invalidated_reason
    due = db.scalars(select(Incident).where(Incident.crisis_id == c.id, Incident.state == "active",
                                            Incident.revisit_at.is_not(None),
                                            Incident.revisit_at <= scenario_now(c))).first()
    return f"incident {due.id} is due for revisit" if due else None


def maybe_wake_command(db: Session, c: Crisis) -> None:
    plan_core.check_plan_validity(db, c)
    w = dict(c.wake or {})
    if w.get("cmd_inflight"):
        if _age(w.get("cmd_since")) < CMD_TIMEOUT_S:
            return
        append_event(db, c, "hr.error", {"what": "crisis-command did not answer", "dispatch": w["cmd_inflight"]})
        w.pop("cmd_inflight")
        _save(c, w)
    reason = _replan_reason(db, c)
    if not reason or _age(w.get("cmd_last")) < CMD_MIN_INTERVAL_S:
        return

    dispatch_id = f"cmd-{uuid.uuid4().hex[:10]}"
    w.pop("replan_requested", None)
    w.update(cmd_last=utcnow().isoformat())
    use_hr = registry.usable(db, registry.COMMAND)
    append_event(db, c, "brain.wake", {"brain": "command", "dispatch_id": dispatch_id, "reason": reason,
                                      "via": "happyrobot" if use_hr else "local"})
    if use_hr:
        w.update(cmd_inflight=dispatch_id, cmd_since=utcnow().isoformat())
        _save(c, w)
        db.add(Outbox(crisis_id=c.id, kind="hr_run", workflow=registry.COMMAND, purpose="command",
                      ref_id=dispatch_id, payload={
                          "dispatch_id": dispatch_id, "run_id": c.id, "callback_base": public_base_url(),
                          "expected_plan_version": c.plan_version, "environment": environment_of(db, c),
                          "event": {"event_id": dispatch_id, "type": "replan", "reason": reason},
                          "snapshot_json": json.dumps(build_snapshot(db, c), ensure_ascii=False)}))
    else:
        _save(c, w)
        local_brain.make_plan(db, c)
