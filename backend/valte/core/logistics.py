"""Logistics: the verbs that move what responders work with.

Units and stock are finite and belong to entities. Keeping them where they
are needed is nobody's job unless someone looks: crews stay parked in a
zone that calmed down, pumps run out at one entity while another has
plenty. These three system verbs let a brain fix that. They go through the
action pipeline like any other decision, so each one is logged with its
reasoning and shows up on the dashboard.
"""

from datetime import datetime, timedelta
from typing import Any

from sqlalchemy.orm import Session

from valte.core.events import append_event
from valte.core.world import resource_dict, resources_of, scenario_now, slugify
from valte.models import Action, Crisis, Entity, Resource

VERBS = {"recall_units", "transfer_resource", "request_resupply"}
RESUPPLY_MIN_ETA = 20  # scenario minutes: nothing from outside arrives faster
LENDER_FLOOR = 0.25    # a lender keeps at least this share of its own stock


class Refused(Exception):
    """The message is written for the brain that proposed the verb."""


def run(db: Session, c: Crisis, verb: str, params: dict[str, Any]) -> dict[str, Any]:
    return {"recall_units": _recall, "transfer_resource": _transfer, "request_resupply": _resupply}[verb](db, c, params)


def _qty(params: dict[str, Any]) -> float:
    try:
        return float(params.get("qty") or 0)
    except (TypeError, ValueError):
        return 0.0


def _recall(db: Session, c: Crisis, params: dict[str, Any]) -> dict[str, Any]:
    """Bring a crew back before its job was due to end: the zone calmed down, or a worse need waits."""
    from valte.core.actions import _release  # lazy: actions imports this module

    act = db.get(Action, (c.id, str(params.get("action_id") or "")))
    if act is None:
        raise Refused("unknown action_id. Use the id of an executed unit action from state.recent_actions.")
    held = act.reserved or {}
    if act.status != "executed" or not held.get("units") or held.get("released"):
        raise Refused(f"{act.id} holds no units in the field (status {act.status}): nothing to recall.")
    _release(db, c, act)
    act.reserved = {**(act.reserved or {}), "recalled_t": scenario_now(c).isoformat()}
    detail = {"action_id": act.id, "entity": held["entity"], "units": int(held["units"]), "zones": held.get("zones", [])}
    append_event(db, c, "units.recalled", detail)
    return detail


def _transfer(db: Session, c: Crisis, params: dict[str, Any]) -> dict[str, Any]:
    """Stock changes hands: from the entity that owns it to the one that is running out."""
    src = db.get(Resource, (c.id, slugify(str(params.get("resource") or ""))))
    to = db.get(Entity, (c.id, slugify(str(params.get("to") or ""))))
    qty = _qty(params)
    if src is None:
        raise Refused(f"unknown resource '{params.get('resource')}'. Use an id from state.resources.")
    if to is None or to.id == src.owner_entity_id:
        raise Refused(f"'{params.get('to')}' must be another entity from state.entities (the owner is {src.owner_entity_id}).")
    spare = src.available - src.total * LENDER_FLOOR
    if qty <= 0 or qty > spare:
        raise Refused(f"{src.id} can lend at most {max(0.0, spare):g} (it has {src.available:g}/{src.total:g} and keeps "
                      f"{LENDER_FLOOR:.0%} for itself); asked for {qty:g}.")

    base = src.id.removesuffix(f"-{src.owner_entity_id}")
    dst = next((r for r in resources_of(db, c.id) if r.owner_entity_id == to.id and (r.id.startswith(base) or r.name == src.name)), None)
    if dst is None:
        dst = Resource(crisis_id=c.id, id=f"{base}-{to.id}", name=src.name, unit=src.unit, description=src.description,
                       total=0, available=0, owner_entity_id=to.id, sort_index=src.sort_index)
        db.add(dst)
    src.available, src.total = src.available - qty, src.total - qty
    dst.available, dst.total = dst.available + qty, dst.total + qty
    db.flush()
    for r in (src, dst):
        append_event(db, c, "resource.updated", resource_dict(r))
    detail = {"resource": src.id, "name": src.name, "qty": qty, "from": src.owner_entity_id, "to": to.id, "into": dst.id}
    append_event(db, c, "resource.transferred", detail)
    return detail


def deliveries(c: Crisis) -> list[dict[str, Any]]:
    return list((c.wake or {}).get("deliveries") or [])


def _resupply(db: Session, c: Crisis, params: dict[str, Any]) -> dict[str, Any]:
    """More stock from outside the crisis (provincial logistics, neighbouring consortia). It takes time to arrive."""
    res = db.get(Resource, (c.id, slugify(str(params.get("resource") or ""))))
    if res is None:
        raise Refused(f"unknown resource '{params.get('resource')}'. Use an id from state.resources.")
    due = next((d for d in deliveries(c) if d["resource"] == res.id), None)
    if due is not None:
        raise Refused(f"{due['qty']:g} of {res.id} are already on their way (due {due['due_t']}). Do not ask twice.")
    qty = min(_qty(params) or res.total / 2, max(res.total, 1.0))  # one order never exceeds the original inventory
    if qty <= 0:
        raise Refused("params.qty must be a positive number.")
    try:
        eta = max(RESUPPLY_MIN_ETA, int(params.get("eta_min") or 30))
    except (TypeError, ValueError):
        eta = 30
    detail = {"resource": res.id, "name": res.name, "qty": qty, "owner": res.owner_entity_id, "eta_min": eta,
              "due_t": (scenario_now(c) + timedelta(minutes=eta)).isoformat()}
    c.wake = {**(c.wake or {}), "deliveries": deliveries(c) + [detail]}
    append_event(db, c, "resupply.requested", detail)
    return detail


def deliver_due(db: Session, c: Crisis, now_s: datetime) -> int:
    """Engine tick: what was ordered and is due arrives in its owner's inventory."""
    ordered = deliveries(c)
    pending, arrived = [], 0
    for d in ordered:
        if datetime.fromisoformat(d["due_t"]) > now_s:
            pending.append(d)
            continue
        res = db.get(Resource, (c.id, d["resource"]))
        if res is None:
            continue
        res.available += float(d["qty"])
        res.total = max(res.total, res.available)
        arrived += 1
        append_event(db, c, "resource.updated", resource_dict(res))
        append_event(db, c, "resupply.arrived", {**d, "available": res.available, "total": res.total}, material=True,
                     digest=f"Resupply arrived: +{float(d['qty']):g} {res.name} for {res.owner_entity_id} "
                            f"({res.available:g}/{res.total:g} now).")
    if len(pending) != len(ordered):
        c.wake = {**(c.wake or {}), "deliveries": pending}
    return arrived
