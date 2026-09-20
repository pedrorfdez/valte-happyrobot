"""Strategy: incidents, priorities, objectives — and knowing when the plan
no longer describes the world ("cuándo tirar el plan")."""

import hashlib
import json
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from valte.core.events import append_event
from valte.core.world import active_plan, incident_dict, plan_dict, scenario_now, zones_of
from valte.models import Action, Crisis, Entity, Incident, Plan, Resource, Tripwire


class Conflict(Exception):
    pass


def _band(sev: int) -> str:
    return "high" if sev >= 7 else "mid" if sev >= 4 else "low"


def material_fingerprint(db: Session, c: Crisis) -> tuple[str, dict[str, Any]]:
    """What must stay true for the plan to still make sense. Signals bump
    state_version all the time; only a change here invalidates a plan."""
    zones = zones_of(db, c.id)
    for z in zones:  # a plan dies when things get worse, not every time a reading wobbles
        if z.severity_est > int((z.extra or {}).get("peak_sev", 0)):
            z.extra = {**(z.extra or {}), "peak_sev": z.severity_est}
    peaks = {z.id: int((z.extra or {}).get("peak_sev", 0)) for z in zones}
    material = {
        "zones": {z.id: _band(peaks[z.id]) for z in zones},
        "receding": bool(zones) and max(peaks.values()) >= 7 and all(z.severity_est < 4 for z in zones),
        "roads_cut": sorted(z.id for z in zones_of(db, c.id) if (z.extra or {}).get("road_cut")),
        "unreachable": sorted(e.id for e in db.scalars(select(Entity).where(
            Entity.crisis_id == c.id, Entity.status == "unreachable"))),
        "exhausted": sorted(r.id for r in db.scalars(select(Resource).where(Resource.crisis_id == c.id))
                            if r.total and r.available / r.total <= 0.1),
        "silences": sorted(t.id for t in db.scalars(select(Tripwire).where(Tripwire.crisis_id == c.id))
                           if (t.cond or {}).get("type") == "silence" and t.last_fired_t is not None),
        "failed_actions": len(list(db.scalars(select(Action.id).where(
            Action.crisis_id == c.id, Action.status == "failed")))) // 2,
    }
    fp = hashlib.sha1(json.dumps(material, sort_keys=True).encode()).hexdigest()[:12]
    return fp, material


def diff_material(old: dict[str, Any], new: dict[str, Any]) -> list[str]:
    reasons = []
    for zid, band in new.get("zones", {}).items():
        was = (old.get("zones") or {}).get(zid)
        if was and was != band:
            reasons.append(f"zone {zid} severity band {was} -> {band}")
    for key, label in (("roads_cut", "road cut in"), ("unreachable", "entity unreachable:"),
                       ("exhausted", "resource exhausted:"), ("silences", "source went silent:")):
        for item in sorted(set(new.get(key, [])) - set(old.get(key, []))):
            reasons.append(f"{label} {item}")
    if new.get("receding") and not old.get("receding"):
        reasons.append("the hazard is receding everywhere: switch from rescue to recovery")
    if new.get("failed_actions", 0) > old.get("failed_actions", 0):
        reasons.append("two more actions failed")
    return reasons


def check_plan_validity(db: Session, c: Crisis) -> list[str]:
    """Returns the reasons the active plan just died, or []."""
    plan = active_plan(db, c.id)
    fp, material = material_fingerprint(db, c)
    if plan is None or plan.material_fp == fp or plan.invalidated_reason:
        return []
    reasons = diff_material(plan.material or {}, material)
    if not reasons:
        plan.material_fp, plan.material = fp, material
        return []
    plan.invalidated_reason = "; ".join(reasons)
    append_event(db, c, "plan.invalidated", plan_dict(plan), material=True,
                 digest=f"PLAN v{plan.version} INVALIDATED: {plan.invalidated_reason}. Re-plan.")
    return reasons


def replace_plan(db: Session, c: Crisis, payload: dict[str, Any], *, expected_plan_version: int | None = None,
                 origin: str = "command") -> Plan:
    if expected_plan_version is not None and int(expected_plan_version) != c.plan_version:
        raise Conflict(f"plan_version is {c.plan_version}, command expected {expected_plan_version}")
    now_s = scenario_now(c)
    old = active_plan(db, c.id)
    if old is not None:
        old.active = False

    from valte.core import incidents as inc_core

    c.plan_version += 1
    keep: set[str] = set()
    for pair in payload.get("merge") or []:  # [["inc-0003", "inc-0007"]]: the same event seen twice
        found = [db.get(Incident, (c.id, str(i))) for i in (pair if isinstance(pair, list) else [])]
        if len(found) >= 2 and all(i is not None and i.origin == "kernel" for i in found):
            for other in found[1:]:
                inc_core.merge(db, c, found[0], other, by=origin)
    for raw in payload.get("incidents") or []:
        iid = str(raw.get("incident_id") or raw.get("id") or f"inc-{len(keep) + 1}")
        keep.add(iid)
        known = db.get(Incident, (c.id, iid))
        if known is not None and known.origin == "kernel":
            # Formed from signals: the strategist may re-prioritise it, say why, set a revisit and close it. Nothing else.
            if raw.get("priority") in ("P0", "P1", "P2", "P3") and known.state != "candidate":
                known.priority = raw["priority"]
            known.note = str(raw.get("summary") or raw.get("note") or known.note or "")[:400]
            if raw.get("state") in ("closed", "resolved") and known.state in inc_core.OPEN:
                known.state, known.closed_reason = "resolved", f"cerrada por el plan v{c.plan_version}"
            try:
                known.revisit_at = datetime.fromisoformat(str(raw["revisit_at"]).replace("Z", "+00:00")) if raw.get("revisit_at") else None
            except ValueError:
                known.revisit_at = None
            known.plan_version = c.plan_version
            continue
        inc = known or Incident(crisis_id=c.id, id=iid)
        inc.state = raw.get("state", "active")
        inc.priority = raw.get("priority", "P2")
        inc.confidence = raw.get("confidence", "unknown")
        inc.title = str(raw.get("title") or "")
        inc.summary = str(raw.get("summary") or "")
        inc.hazard_types = raw.get("hazard_types") or [c.hazard_type]
        inc.zone_ids = raw.get("zone_ids") or []
        inc.evidence = raw.get("evidence") or []
        try:
            inc.revisit_at = datetime.fromisoformat(str(raw["revisit_at"]).replace("Z", "+00:00")) if raw.get("revisit_at") else None
        except ValueError:
            inc.revisit_at = None
        inc.plan_version = c.plan_version
        db.merge(inc)
    for inc in db.scalars(select(Incident).where(Incident.crisis_id == c.id, Incident.origin != "kernel",
                                                 Incident.state.in_(("candidate", "active")))):
        if inc.id not in keep and payload.get("incidents") is not None:
            inc.state = "closed"  # only what a strategist wrote dies by omission; the kernel's follow the world

    body = payload.get("plan") or {}
    fp, material = material_fingerprint(db, c)
    plan = Plan(crisis_id=c.id, version=c.plan_version, t=now_s, summary=str(body.get("summary") or ""),
                objectives=body.get("objectives") or [], material_fp=fp, material=material, origin=origin)
    db.add(plan)
    db.flush()
    from valte.core import learning

    plan.lessons = learning.cite(db, c, body.get("lessons") or payload.get("applied_lesson_ids"), by=origin, ref=f"plan-v{plan.version}")

    # Pending work for incidents that no longer exist is withdrawn, visibly.
    superseded = []
    for act in db.scalars(select(Action).where(Action.crisis_id == c.id, Action.status == "pending_approval")):
        dropped = db.get(Incident, (c.id, act.incident_id)) if act.incident_id else None
        if dropped is not None and dropped.origin != "kernel" and act.incident_id not in keep:
            act.status, act.error = "rejected", f"plan v{c.plan_version} sustituye al anterior"
            superseded.append(act.id)
    append_event(db, c, "plan.replaced", {**plan_dict(plan), "replaced": old.version if old else None,
                                          "why": old.invalidated_reason if old else None,
                                          "superseded_actions": superseded,
                                          "incidents": [incident_dict(i) for i in db.scalars(
                                              select(Incident).where(Incident.crisis_id == c.id))]},
                 material=True, digest=f"New plan v{plan.version}: {plan.summary[:240]}")
    return plan
