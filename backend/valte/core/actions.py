"""The action pipeline: propose → validate → (approve) → execute → effects.

Brains only propose. Nothing reaches the world without passing through
here, which is what makes the system supervisable: every rejection has a
reason the LLM can read, every approval has a human or an escalation.
"""

import json
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from valte.core import incidents, logistics
from valte.core.events import append_event
from valte.core.world import (
    DEFAULT_APPROVAL_VERBS,
    SYSTEM_VERBS,
    UNIT_VERBS,
    VERB_LABELS,
    action_dict,
    entity_dict,
    next_id,
    resolve_zone,
    resource_dict,
    scenario_now,
    slugify,
    tripwire_dict,
    zone_dict,
)
from valte.models import Action, Crisis, Entity, Incident, Resource, ScheduledCheck, Signal, Tripwire, Zone, utcnow
from valte.settings import settings

REPEATABLE = {"rescue", "pump_water", "supplies", "shelter", "wellness_check"}
DEDUP_WINDOW = timedelta(minutes=60)
TERMINAL_BAD = ("rejected", "failed")
BRAINS = ("coordinator", "local-brain", "proactive")  # origins that must justify themselves with evidence


class Rejected(Exception):
    pass


def _label(verb: str, params: dict[str, Any]) -> str:
    label = VERB_LABELS.get(verb, verb.replace("_", " ").capitalize())
    if verb in UNIT_VERBS and params.get("units"):
        n = int(params["units"])
        label += f" · {n} unidad{'es' if n != 1 else ''}"
    if verb == "close_road" and params.get("road"):
        label = f"Cortar {params['road']}"
    if verb == "activate_emergency_level" and params.get("level") is not None:
        label += f" {params['level']}"
    return label


def _units(params: dict[str, Any]) -> int:
    try:
        return max(1, int(params.get("units", 1)))
    except (TypeError, ValueError):
        return 1


def _dedup_key(actor: str, verb: str, zones: list[str], params: dict[str, Any], evidence: list[str] | None = None) -> str:
    key = f"{actor}|{verb}|{','.join(sorted(zones))}"
    if verb == "activate_emergency_level":
        key += f"|{params.get('level')}"  # level 1 and level 2 are different decisions
    if verb in REPEATABLE:
        # Two reports from the same zone are two jobs; the same report served twice is a duplicate.
        key += "|" + (",".join(sorted(evidence)) if evidence else json.dumps(params, sort_keys=True, ensure_ascii=False))
    return key


def validate_action(db: Session, c: Crisis, a: dict[str, Any], origin: str) -> None:
    """Raises Rejected with a message written for the brain that proposed it."""
    actor = db.get(Entity, (c.id, a["actor"]))
    if actor is None:
        raise Rejected(f"unknown actor '{a['actor']}'. Use an entity id from state.entities.")
    if a["verb"] not in (actor.capabilities or []):
        raise Rejected(f"{actor.id} cannot '{a['verb']}'. Its capabilities: {actor.capabilities}.")
    if actor.jurisdiction:
        outside = [z for z in a["target_zones"] if z not in actor.jurisdiction]
        if outside:
            raise Rejected(f"{actor.id} has no jurisdiction in {outside}. Its jurisdiction: {actor.jurisdiction}.")
    if actor.status == "unreachable" and origin != "human":
        raise Rejected(f"{actor.id} is unreachable. Use its escalation_to: {actor.escalation_to}.")

    if origin in BRAINS:
        if not a["evidence"]:
            raise Rejected("evidence is mandatory: cite signal ids from state.recent_signals or the digest.")
        # pat-* are the findings of a proactive round (engine/patrol.py): state nobody reported, but still checkable.
        real = [e for e in a["evidence"] if db.get(Signal, (c.id, e)) or db.get(Incident, (c.id, e))
                or str(e).startswith(("tw-", "act-", "evt-", "plan-", "pat-"))]
        if not real:
            raise Rejected(f"none of the evidence ids {a['evidence']} exist. Cite real signal ids.")

    if origin in BRAINS:
        from valte.core import learning

        learned = learning.blocked_by_rejection(db, c, a["verb"], a["target_zones"], a["evidence"])
        if learned:
            raise Rejected(learned)

    key = _dedup_key(a["actor"], a["verb"], a["target_zones"], a["params"], a["evidence"])
    since = scenario_now(c) - DEDUP_WINDOW
    for dup in db.scalars(select(Action).where(Action.crisis_id == c.id, Action.dedup_key == key)):
        if dup.status in TERMINAL_BAD:
            continue
        if dup.status == "executed" and dup.t < since:
            continue
        raise Rejected(f"duplicate: {dup.id} already {dup.status} for {a['actor']} {a['verb']} on the same zones. "
                       f"Do not repeat it; act again only if conditions changed materially.")

    if a["verb"] == "supplies" and a["params"].get("resource"):
        res = db.get(Resource, (c.id, slugify(str(a["params"]["resource"]))))
        if res is None:
            raise Rejected(f"unknown resource '{a['params']['resource']}'. Use an id from state.resources.")
        if res.owner_entity_id and res.owner_entity_id != actor.id:
            raise Rejected(f"{res.id} belongs to {res.owner_entity_id}, not to {actor.id}. "
                           f"The owner must be the actor of a supplies action.")

    if a["verb"] in REPEATABLE and a["evidence"] and origin in BRAINS:
        for other in db.scalars(select(Action).where(Action.crisis_id == c.id, Action.verb == a["verb"],
                                                     Action.status.not_in(TERMINAL_BAD))):
            if other.actor != a["actor"] and set(other.evidence or []) == set(a["evidence"]):
                raise Rejected(f"{other.id}: {other.actor} is already on {a['evidence']} ({other.verb}, "
                               f"{(other.params or {}).get('units', 1)} units). To reinforce it, send a different "
                               f"responder citing that action id too, e.g. evidence {a['evidence'] + [other.id]}.")

    if a["verb"] in UNIT_VERBS and actor.units_total is not None:
        need = _units(a["params"])
        if (actor.units_available or 0) < need:
            raise Rejected(f"{actor.id} has {actor.units_available or 0} units free, {need} requested. "
                           f"Reassign, reduce units, or use another responder.")


def _needs_approval(c: Crisis, actor: Entity, verb: str) -> bool:
    verbs = (c.config or {}).get("approval_verbs") or DEFAULT_APPROVAL_VERBS
    return verb in verbs or (actor.activation or {}).get("cost") == "high"


def find_approver(db: Session, c: Crisis, actor: Entity, zones: list[str]) -> Entity | None:
    """Who signs: the actor if it is an authority, else the heaviest
    authority whose jurisdiction covers the target zones."""
    if actor.kind == "authority" and actor.role != "coordination":
        return actor
    best: Entity | None = None
    for e in db.scalars(select(Entity).where(Entity.crisis_id == c.id, Entity.kind == "authority")):
        if e.role == "coordination":
            continue
        covers = not e.jurisdiction or all(z in e.jurisdiction for z in zones)
        if covers and (best is None or e.weight > best.weight):
            best = e
    return best


def propose_action(db: Session, c: Crisis, raw: dict[str, Any] | str, *, origin: str = "coordinator",
                   by: str | None = None) -> dict[str, Any]:
    """Returns {id, status} or {id, error}. Never raises on bad input: the
    caller is usually an LLM and the error text is its feedback."""
    from valte.core import outreach

    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except ValueError:
            return {"id": None, "error": "action is not valid JSON"}
    if not isinstance(raw, dict) or not raw.get("verb") or not raw.get("actor"):
        return {"id": (raw or {}).get("id") if isinstance(raw, dict) else None, "error": "action needs actor and verb"}

    params = raw.get("params") if isinstance(raw.get("params"), dict) else {}
    zones = [z for z in (resolve_zone(db, c.id, z) for z in (raw.get("target_zones") or [])) if z]
    a = {
        "actor": slugify(str(raw["actor"])) if raw["actor"] != "system" else "system",
        "verb": str(raw["verb"]).strip(),
        "target_zones": zones,
        "params": params,
        "evidence": [str(e) for e in (raw.get("evidence") or [])],
        "reasoning": str(raw.get("reasoning") or ""),
    }
    proposed_id = str(raw.get("id") or "")

    if a["actor"] == "system" or a["verb"] in SYSTEM_VERBS:
        return _run_system_verb(db, c, a, origin)

    try:
        validate_action(db, c, a, origin)
    except Rejected as e:
        append_event(db, c, "action.rejected_by_kernel", {"proposed": {**a, "id": proposed_id}, "error": str(e)})
        return {"id": proposed_id or None, "error": str(e)}

    actor = db.get(Entity, (c.id, a["actor"]))
    seq = int((c.counters or {}).get("act", 0)) + 1
    act = Action(
        crisis_id=c.id, id=next_id(c, "act"), seq=seq, t=scenario_now(c), actor=a["actor"], verb=a["verb"],
        verb_label=_label(a["verb"], params), target_zones=zones, params=params, status="approved",
        evidence=a["evidence"], reasoning=a["reasoning"], origin=origin,
        dedup_key=_dedup_key(a["actor"], a["verb"], zones, params, a["evidence"]), plan_version=c.plan_version,
        incident_id=raw.get("incident_id"), escalated_from=raw.get("escalated_from"),
    )
    db.add(act)
    incidents.link_action(db, c, act)
    from valte.core import learning

    act.lessons = learning.cite(db, c, raw.get("lessons") or raw.get("applied_lesson_ids"), by=origin, ref=act.id)

    approver = find_approver(db, c, actor, zones) if _needs_approval(c, actor, a["verb"]) else None
    if approver is not None and not (origin == "human" and by == approver.id):
        approver = learning.reroute_approver(db, c, approver, ref=act.id)  # learned in this crisis: who does not pick up
    human_signs = origin == "human" and approver is not None and by == approver.id
    if approver is not None and not human_signs:
        floor = timedelta(seconds=settings.valte_approval_floor_s)
        act.status = "pending_approval"
        act.approval = {
            "approver": approver.id, "approver_name": approver.name, "level": 1,
            "deadline_wall": (utcnow() + floor).isoformat(),
            "deadline_t": (scenario_now(c) + timedelta(minutes=10)).isoformat(),
            "escalates_to": approver.escalation_to,
        }
        db.flush()
        append_event(db, c, "action.created", action_dict(act))
        append_event(db, c, "approval.requested", {"action_id": act.id, "approver": approver.id})
        outreach.queue_contact(db, c, entity=approver, action=act, purpose="approval")
        return {"id": act.id, "status": act.status}

    if human_signs:
        act.approval = {"approver": approver.id, "decided_by": by, "decision": "approved",
                        "decided_at": utcnow().isoformat()}
    db.flush()
    append_event(db, c, "action.created", action_dict(act))
    execute_action(db, c, act)
    return {"id": act.id, "status": act.status}


def submit_decisions(db: Session, c: Crisis, actions: list[Any], situation_note: str = "",
                     emergency_level: Any = None, *, origin: str = "coordinator") -> dict[str, Any]:
    """Kernel contract for POST /decisions."""
    results = []
    for i, raw in enumerate(actions or []):
        res = propose_action(db, c, raw, origin=origin)
        results.append({"index": i, **res})
    if situation_note:
        c.situation_note = str(situation_note)[:1200]
    try:
        level = int(emergency_level) if emergency_level is not None else None
    except (TypeError, ValueError):
        level = None
    if level is not None and level > c.emergency_level:
        # The brain reports the level; raising it for real is an action.
        append_event(db, c, "brain.note", {"claimed_emergency_level": level})
    accepted = sum(1 for r in results if not r.get("error"))
    append_event(db, c, "brain.result", {"origin": origin, "accepted": accepted,
                                        "rejected": len(results) - accepted, "situation_note": c.situation_note,
                                        "results": results})
    return {"results": results, "accepted": accepted, "rejected": len(results) - accepted}


# ── approval ─────────────────────────────────────────────────────────────


def approve_action(db: Session, c: Crisis, act: Action, *, by: str, via: str = "dashboard", note: str = "") -> Action:
    if act.status != "pending_approval":
        return act
    act.approval = {**(act.approval or {}), "decided_by": by, "decision": "approved", "via": via,
                    "note": note, "decided_at": utcnow().isoformat(), "decided_t": scenario_now(c).isoformat()}
    act.status = "approved"
    act.updated_at = utcnow()
    append_event(db, c, "approval.decided", {"action_id": act.id, "decision": "approved", "by": by, "via": via},
                 material=True, digest=f"{act.id} ({act.verb} {act.target_zones}) APPROVED by {by} via {via}.")
    _close_approval_contacts(db, c, act, "approved")
    execute_action(db, c, act)
    return act


def reject_action(db: Session, c: Crisis, act: Action, *, by: str, via: str = "dashboard", reason: str = "") -> Action:
    if act.status != "pending_approval":
        return act
    act.approval = {**(act.approval or {}), "decided_by": by, "decision": "rejected", "via": via,
                    "note": reason, "decided_at": utcnow().isoformat(), "decided_t": scenario_now(c).isoformat()}
    act.status = "rejected"
    act.error = reason or None
    act.updated_at = utcnow()
    append_event(db, c, "action.updated", action_dict(act))
    append_event(db, c, "approval.decided", {"action_id": act.id, "decision": "rejected", "by": by, "via": via},
                 material=True,
                 digest=f"{act.id} ({act.verb} {act.target_zones}) REJECTED by {by}: {reason or 'no reason given'}. "
                        f"Adapt: do not propose it again unchanged.")
    _close_approval_contacts(db, c, act, "rejected")
    return act


def _close_approval_contacts(db: Session, c: Crisis, act: Action, decision: str) -> None:
    from valte.core import outreach
    from valte.models import Contact

    for k in db.scalars(select(Contact).where(Contact.crisis_id == c.id, Contact.action_id == act.id,
                                              Contact.purpose == "approval",
                                              Contact.status.in_(("queued", "sending", "ringing")))):
        outreach.set_status(db, c, k, "superseded", outcome={"decision": decision, "note": "decidido por otra vía"})


def expire_approvals(db: Session, c: Crisis) -> None:
    """A signature that does not arrive moves up the chain of command."""
    from valte.core import outreach

    now_w, now_s = utcnow(), scenario_now(c)
    for act in db.scalars(select(Action).where(Action.crisis_id == c.id, Action.status == "pending_approval")):
        ap = act.approval or {}
        if not ap.get("deadline_wall"):
            continue
        if now_w < datetime.fromisoformat(ap["deadline_wall"]) or now_s < datetime.fromisoformat(ap["deadline_t"]):
            continue
        current = db.get(Entity, (c.id, ap.get("approver", "")))
        nxt = db.get(Entity, (c.id, current.escalation_to)) if current and current.escalation_to else None
        if nxt is None:
            append_event(db, c, "approval.stalled", {"action_id": act.id}, material=True,
                         digest=f"{act.id} ({act.verb}) has no one left to approve it. A human must decide on the dashboard.")
            act.approval = {**ap, "deadline_wall": None, "stalled": True}
            append_event(db, c, "action.updated", action_dict(act))
            continue
        act.approval = {
            **ap, "approver": nxt.id, "approver_name": nxt.name, "level": int(ap.get("level", 1)) + 1,
            "escalated_from": (ap.get("escalated_from") or []) + [current.id if current else "?"],
            "deadline_wall": (now_w + timedelta(seconds=settings.valte_approval_floor_s)).isoformat(),
            "deadline_t": (now_s + timedelta(minutes=10)).isoformat(), "escalates_to": nxt.escalation_to,
        }
        append_event(db, c, "action.updated", action_dict(act))
        append_event(db, c, "approval.escalated", {"action_id": act.id, "from": current.id if current else None, "to": nxt.id},
                     material=True, digest=f"Approval of {act.id} ({act.verb}) escalated to {nxt.id}: "
                                           f"{current.id if current else 'approver'} did not answer in time.")
        outreach.queue_contact(db, c, entity=nxt, action=act, purpose="approval",
                               attempt=int(act.approval["level"]))


# ── execution and effects ────────────────────────────────────────────────


def execute_action(db: Session, c: Crisis, act: Action) -> None:
    """Commit resources, then tell the actor for real. The world only
    changes (complete_action) once the actor has the order."""
    from valte.core import outreach

    actor = db.get(Entity, (c.id, act.actor))
    if act.verb in UNIT_VERBS and actor and actor.units_total is not None:
        need = _units(act.params)
        if (actor.units_available or 0) < need:
            fail_action(db, c, act, f"{actor.name}: solo {actor.units_available or 0} unidades libres, hacen falta {need}.")
            return
        actor.units_available = (actor.units_available or 0) - need
        deployed = dict(actor.deployed or {})
        for z in act.target_zones or ["-"]:
            deployed[z] = deployed.get(z, 0) + need
        actor.deployed = deployed
        from valte.core.needs import access_penalty

        # Units sent into a zone with a collapsed access are gone for longer: scarcity gets worse.
        minutes = int(act.params.get("duration_min", 45)) + access_penalty(db, c, act.target_zones or [])
        act.reserved = {"entity": actor.id, "units": need, "zones": act.target_zones or ["-"],
                        "release_t": (scenario_now(c) + timedelta(minutes=minutes)).isoformat()}
        if actor.units_available == 0:
            actor.status = "busy"
        append_event(db, c, "entity.updated", entity_dict(actor), material=actor.units_available == 0,
                     digest=f"{actor.id} has no units left." if actor.units_available == 0 else None)
        _commit_material(db, c, act, actor, need)

    # Whoever signed it in person already has the order: do not call them twice.
    ap = act.approval or {}
    told = ap.get("decision") == "approved" and ap.get("decided_by") == act.actor and ap.get("via") != "dashboard-operator"
    contact = None if told else (outreach.queue_contact(db, c, entity=actor, action=act, purpose="order") if actor else None)
    if contact is None:
        complete_action(db, c, act)
    else:
        append_event(db, c, "action.updated", action_dict(act))


def complete_action(db: Session, c: Crisis, act: Action, *, real_interaction: dict[str, Any] | None = None) -> None:
    if act.status in ("executed", "rejected", "failed"):
        return
    act.status = "executed"
    act.updated_at = utcnow()
    if real_interaction:
        act.real_interaction = real_interaction
    apply_effects(db, c, act)
    append_event(db, c, "action.updated", action_dict(act))


def fail_action(db: Session, c: Crisis, act: Action, error: str, *, escalate: bool = True) -> None:
    if act.status in ("executed", "rejected", "failed"):
        return
    act.status = "failed"
    act.error = error
    act.updated_at = utcnow()
    _release(db, c, act)
    append_event(db, c, "action.updated", action_dict(act), material=True,
                 digest=f"{act.id} ({act.verb} by {act.actor} on {act.target_zones}) FAILED: {error}")
    actor = db.get(Entity, (c.id, act.actor))
    nxt = db.get(Entity, (c.id, actor.escalation_to)) if escalate and actor and actor.escalation_to else None
    if nxt is not None and act.verb in (nxt.capabilities or []):
        propose_action(db, c, {
            "actor": nxt.id, "verb": act.verb, "target_zones": act.target_zones, "params": act.params,
            "evidence": act.evidence or [act.id], "escalated_from": act.id,
            "reasoning": f"{actor.name} no responde ({error}). Escalo a {nxt.name} según la cadena de escalado.",
        }, origin="escalation")


def _commit_material(db: Session, c: Crisis, act: Action, actor: Entity, units: int) -> None:
    """Pumps go out with a pumping crew, a boat with a rescue into deep water. The crew takes them from
    its own entity's stock (resources belong to entities) and brings them back with the units."""
    kind = None
    if act.verb == "pump_water":
        kind, qty = "bombas-achique", float(units)
    elif act.verb == "rescue" and any((z := db.get(Zone, (c.id, zid))) is not None and z.severity_est >= 7
                                      for zid in act.target_zones):
        kind, qty = "embarcaciones", float(max(1, units // 2))
    if kind is None:
        return
    stock = next((r for r in db.scalars(select(Resource).where(Resource.crisis_id == c.id, Resource.available > 0))
                  if r.id.startswith(kind) and r.owner_entity_id == actor.id), None)
    if stock is None:
        return
    taken = min(qty, stock.available)
    stock.available -= taken
    scarce = bool(stock.total) and stock.available / stock.total <= 0.2
    append_event(db, c, "resource.updated", resource_dict(stock), material=scarce,
                 digest=f"{stock.name} ({actor.id}) running out: {stock.available:g}/{stock.total:g} left." if scarce else None)
    act.reserved = {**(act.reserved or {}), "materials": {stock.id: taken}}


def _release(db: Session, c: Crisis, act: Action) -> None:
    res = act.reserved or {}
    if not res.get("units") or res.get("released"):
        return
    for rid, qty in (res.get("materials") or {}).items():
        mat = db.get(Resource, (c.id, rid))
        if mat is not None:
            mat.available = min(mat.total, mat.available + float(qty))
            append_event(db, c, "resource.updated", resource_dict(mat))
    ent = db.get(Entity, (c.id, res["entity"]))
    if ent is not None:
        ent.units_available = min(ent.units_total or 0, (ent.units_available or 0) + int(res["units"]))
        deployed = dict(ent.deployed or {})
        for z in res.get("zones", []):
            deployed[z] = max(0, deployed.get(z, 0) - int(res["units"]))
            if deployed[z] == 0:
                deployed.pop(z)
        ent.deployed = deployed
        if ent.status == "busy" and ent.units_available > 0:
            ent.status = "available"
        append_event(db, c, "entity.updated", entity_dict(ent))
    act.reserved = {**res, "released": True}


def release_due_units(db: Session, c: Crisis) -> int:
    now_s, n = scenario_now(c), 0
    for act in db.scalars(select(Action).where(Action.crisis_id == c.id, Action.status == "executed",
                                               Action.verb.in_(tuple(UNIT_VERBS)))):
        res = act.reserved or {}
        if res.get("units") and not res.get("released") and datetime.fromisoformat(res["release_t"]) <= now_s:
            _release(db, c, act)
            append_event(db, c, "action.updated", action_dict(act))  # in_progress → done
            n += int(res["units"])
    return n


def apply_effects(db: Session, c: Crisis, act: Action) -> None:
    from valte.core.signals import recompute_zone_estimates

    now_s = scenario_now(c)
    zones = [z for z in (db.get(Zone, (c.id, zid)) for zid in act.target_zones) if z]
    if act.verb == "send_es_alert":
        for z in zones:
            z.warned, z.warned_at = True, z.warned_at or now_s
    elif act.verb == "order_evacuation":
        for z in zones:
            z.evacuating = True
            z.warned, z.warned_at = True, z.warned_at or now_s
    elif act.verb == "close_road":
        for z in zones:
            z.road_closed = True
    elif act.verb == "activate_emergency_level":
        try:
            c.emergency_level = max(c.emergency_level, int(act.params.get("level", c.emergency_level + 1)))
        except (TypeError, ValueError):
            c.emergency_level += 1
        append_event(db, c, "crisis.updated", {"emergency_level": c.emergency_level})
    elif act.verb == "open_shelter":
        cap = float(act.params.get("capacity", 300))
        rid = f"plazas-albergue-{act.actor}"
        res = db.get(Resource, (c.id, rid))
        if res is None:
            res = Resource(crisis_id=c.id, id=rid, name="Plazas de albergue", total=0, available=0, sort_index=99,
                           owner_entity_id=act.actor)
            db.add(res)
        res.total += cap
        res.available += cap
        append_event(db, c, "resource.updated", resource_dict(res))
    elif act.verb in ("supplies", "shelter"):
        qty = float(act.params.get("qty") or act.params.get("people") or 0)
        if act.verb == "shelter" and not act.params.get("resource"):
            res = _shelter_for(db, c, act.target_zones)
        else:
            res = db.get(Resource, (c.id, slugify(str(act.params.get("resource") or ""))))
        if res is not None and qty:
            res.available = max(0.0, res.available - qty)
            low = res.total and res.available / res.total <= 0.2
            append_event(db, c, "resource.updated", resource_dict(res), material=bool(low),
                         digest=f"Resource {res.name} is running low: {res.available:g}/{res.total:g}." if low else None)
    elif act.verb == "request_ume":
        ume = db.get(Entity, (c.id, act.actor if act.actor == "ume" else "ume"))
        if ume is not None:
            delay = int((ume.activation or {}).get("delay_min", 180))
            ume.extra = {**(ume.extra or {}), "arrives_t": (now_s + timedelta(minutes=delay)).isoformat()}
            ume.status = "busy"
            append_event(db, c, "entity.updated", entity_dict(ume))
            # The request is not finished until the UME is on the ground (tick_world closes it).
            act.reserved = {**(act.reserved or {}), "entity": ume.id, "until_t": ume.extra["arrives_t"]}
    for z in zones:
        append_event(db, c, "zone.updated", zone_dict(z))
    if zones:
        recompute_zone_estimates(db, c)


def _shelter_for(db: Session, c: Crisis, zones: list[str]) -> Resource | None:
    """Shelter places belong to the authority that opened them: lodge people where the places are,
    preferring a shelter whose owner has jurisdiction over the zone being served."""
    open_ = [r for r in db.scalars(select(Resource).where(Resource.crisis_id == c.id, Resource.available > 0))
             if r.id.startswith("plazas-albergue")]
    for r in open_:
        owner = db.get(Entity, (c.id, r.owner_entity_id or ""))
        if owner is not None and (not owner.jurisdiction or set(zones) & set(owner.jurisdiction)):
            return r
    return open_[0] if open_ else None


def tick_world(db: Session, c: Crisis, minutes: float) -> None:
    """Slow consequences of past actions: evacuations progress, the UME arrives."""
    from valte.core.signals import recompute_zone_estimates

    now_s = scenario_now(c)
    moved = False
    for z in db.scalars(select(Zone).where(Zone.crisis_id == c.id, Zone.evacuating.is_(True))):
        if z.evacuated_pct < 70:
            before = round(z.evacuated_pct)
            z.evacuated_pct = min(70.0, z.evacuated_pct + 1.5 * minutes)
            moved = moved or round(z.evacuated_pct) != before
    for e in db.scalars(select(Entity).where(Entity.crisis_id == c.id, Entity.status == "busy")):
        arrives = (e.extra or {}).get("arrives_t")
        if arrives and datetime.fromisoformat(arrives) <= now_s:
            e.extra = {k: v for k, v in e.extra.items() if k != "arrives_t"}
            e.status, e.units_available = "available", e.units_total
            append_event(db, c, "entity.updated", entity_dict(e), material=True,
                         digest=f"{e.id} is now operational with {e.units_total} units.")
            for act in db.scalars(select(Action).where(Action.crisis_id == c.id, Action.status == "executed",
                                                       Action.verb == "request_ume")):
                res = act.reserved or {}
                if res.get("until_t") and res.get("entity") == e.id and not res.get("released"):
                    act.reserved = {**res, "released": True}
                    append_event(db, c, "action.updated", action_dict(act))  # in_progress → done
    if moved:
        recompute_zone_estimates(db, c)


# ── system verbs ─────────────────────────────────────────────────────────


def _run_system_verb(db: Session, c: Crisis, a: dict[str, Any], origin: str) -> dict[str, Any]:
    verb, params, now_s = a["verb"], a["params"], scenario_now(c)
    detail: dict[str, Any] = {}
    try:
        if verb == "set_tripwire":
            tw = params.get("tripwire") or params
            if isinstance(tw, str):
                tw = json.loads(tw)
            tid = slugify(str(tw.get("id") or next_id(c, "tw")))
            existing = db.get(Tripwire, (c.id, tid))
            if existing and existing.active:
                return {"id": None, "error": f"tripwire {tid} is already active. Do not re-arm it."}
            row = existing or Tripwire(crisis_id=c.id, id=tid)
            row.cond, row.then = tw.get("if") or {}, tw.get("then") or []
            row.reason, row.set_by, row.active, row.created_t = str(tw.get("reason", "")), origin, True, now_s
            row.repeat = str(tw.get("repeat", False)).lower() in ("true", "1")
            if not existing:
                db.add(row)
            db.flush()
            detail = tripwire_dict(row)
            append_event(db, c, "tripwire.armed", detail)
        elif verb == "clear_tripwire":
            row = db.get(Tripwire, (c.id, slugify(str(params.get("id", "")))))
            if row is None:
                return {"id": None, "error": "unknown tripwire id"}
            row.active = False
            append_event(db, c, "tripwire.cleared", tripwire_dict(row))
        elif verb == "schedule_check":
            pending = db.scalars(select(ScheduledCheck).where(ScheduledCheck.crisis_id == c.id,
                                                              ScheduledCheck.done.is_(False))).first()
            if pending is not None:
                return {"id": None, "error": f"a check is already scheduled for {pending.due_t.isoformat()}; "
                                             f"new signals, failures and approvals wake you anyway."}
            delay = max(5, int(params.get("delay_min", 10)))
            db.add(ScheduledCheck(crisis_id=c.id, due_t=now_s + timedelta(minutes=delay), note=str(params.get("note", ""))))
            detail = {"delay_min": delay}
        elif verb == "register_entity":
            e = params.get("entity") or params
            eid = slugify(str(e.get("id") or e.get("name") or ""))
            if not eid or db.get(Entity, (c.id, eid)):
                return {"id": None, "error": f"entity '{eid}' already exists or has no id"}
            units = e.get("units") or {}
            ent = Entity(crisis_id=c.id, id=eid, name=str(e.get("name") or eid), kind=e.get("kind", "responder"),
                         role="responder", weight=min(int(e.get("weight", 3)), 4), trust="low",
                         jurisdiction=[z for z in (resolve_zone(db, c.id, z) for z in e.get("jurisdiction") or []) if z],
                         channel=e.get("channel") or {"kind": "none"},
                         capabilities=[v for v in (e.get("capabilities") or []) if v in ("wellness_check", "supplies", "shelter")],
                         units_total=units.get("total"), units_available=units.get("available", units.get("total")),
                         status="available", provenance="discovered", notes=str(e.get("notes", "")))
            db.add(ent)
            db.flush()
            detail = entity_dict(ent)
            append_event(db, c, "entity.updated", detail)
        elif verb == "update_entity":
            ent = db.get(Entity, (c.id, slugify(str(params.get("id", "")))))
            if ent is None:
                return {"id": None, "error": "unknown entity id"}
            for field in ("trust", "status", "notes", "weight"):
                if field in params:
                    setattr(ent, field, params[field])
            detail = entity_dict(ent)
            append_event(db, c, "entity.updated", detail)
        elif verb in logistics.VERBS:
            detail = logistics.run(db, c, verb, params)
        else:
            return {"id": None, "error": f"unknown system verb '{verb}'"}
    except logistics.Refused as e:
        return {"id": None, "error": str(e)}
    except (ValueError, TypeError, AttributeError) as e:
        return {"id": None, "error": f"malformed params for {verb}: {e}"}

    seq = int((c.counters or {}).get("act", 0)) + 1
    act = Action(crisis_id=c.id, id=next_id(c, "act"), seq=seq, t=now_s, actor="system", verb=verb,
                 verb_label=VERB_LABELS.get(verb, verb), target_zones=a["target_zones"], params=params,
                 status="executed", evidence=a["evidence"], reasoning=a["reasoning"], origin=origin,
                 plan_version=c.plan_version)
    db.add(act)
    db.flush()
    append_event(db, c, "action.created", action_dict(act))
    return {"id": act.id, "status": "executed"}
