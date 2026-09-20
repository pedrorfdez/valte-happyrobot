"""Plays a scenario pack in accelerated scenario time.

The simulator owns ground truth. It never writes what the system is meant
to *find out* (a dead gauge, an entity that stopped answering): it only
makes the world behave that way and lets perception and outreach notice.
"""

from functools import lru_cache
from typing import Any

from sqlalchemy.orm import Session

from valte.core.events import append_event
from valte.core.intake import submit_raw_input
from valte.core.signals import upsert_signal
from valte.core.world import elapsed_min, entity_dict, load_pack, resource_dict, scenario_now, zone_dict
from valte.models import Crisis, Entity, Resource, Zone


@lru_cache(maxsize=8)
def _timeline(pack_id: str) -> tuple[dict[str, Any], ...]:
    return tuple(sorted(load_pack(pack_id).get("timeline") or [], key=lambda i: i["at_min"]))


def timeline_for(db: Session, c: Crisis, hazard: str | None = None) -> list[dict[str, Any]]:
    """The hand-written pack script when it fits this crisis; otherwise one generated from its own zones.
    `hazard` = what the outside world is asked to simulate (the feeder app picks flood or fire); by default, the crisis's own."""
    from valte.core.world import entities_of, resources_of, zones_of
    from valte.sim import generator

    hazard = hazard or c.hazard_type
    zones = zones_of(db, c.id)
    zone_ids = {z.id for z in zones}
    if c.pack_id:
        pack = load_pack(c.pack_id)
        script = _timeline(c.pack_id)
        used = {i["zone"] for i in script if i.get("zone")} | {i["fallback"]["zone"] for i in script if (i.get("fallback") or {}).get("zone")}
        if pack.get("hazard_type") == hazard and used and len(used & zone_ids) >= len(used) / 2:
            return [i for i in script if (i.get("zone") or (i.get("fallback") or {}).get("zone") or "") in zone_ids | {""}]
    own = hazard == c.hazard_type
    cached = (c.config or {}).get("generated_timeline") if own else ((c.config or {}).get("generated_timelines") or {}).get(hazard)
    if cached:
        return cached
    ensure_sources(db, c)
    ents = entities_of(db, c.id)
    script = generator.generate(
        hazard=hazard, region=c.region,
        zones=[{"id": z.id, "name": z.name, "population": z.population, "is_origin": z.is_origin, "downstream": z.downstream} for z in zones],
        responders=[{"id": e.id, "name": e.name, "escalation_to": e.escalation_to, "channel": e.channel} for e in ents if e.kind == "responder"],
        resources=[{"id": r.id, "name": r.name, "total": r.total} for r in resources_of(db, c.id)], seed=f"{c.id}:{hazard}" if not own else c.id)
    # stable for the whole run (and for a re-attached feeder), one script per simulated hazard
    c.config = {**(c.config or {}), **({"generated_timeline": script} if own else
                                       {"generated_timelines": {**((c.config or {}).get("generated_timelines") or {}), hazard: script}})}
    return script


def ensure_sources(db: Session, c: Crisis) -> None:
    """A crisis declared from the wizard may have no 112, no sensors, no media: add what is missing, plus the
    standing reflex that treats a silent sensor network as an escalation."""
    from valte.models import Tripwire
    from valte.sim.generator import BASE_SOURCES

    for src in BASE_SOURCES:
        if db.get(Entity, (c.id, src["id"])) is None:
            db.add(Entity(crisis_id=c.id, id=src["id"], name=src["name"], kind="information_source", weight=3,
                          trust=src["trust"], channel={"kind": "none"}, capabilities=[], notes=src["notes"]))
    coord = (c.config or {}).get("coordination_entity") or "cecopi"
    if db.get(Tripwire, (c.id, "tw-sensores-silencio")) is None and db.get(Entity, (c.id, coord)) is not None:
        db.add(Tripwire(crisis_id=c.id, id="tw-sensores-silencio", set_by="plan", created_t=c.t0_scenario,
                        cond={"type": "silence", "source": "sensores", "silence_min": 20},
                        then=[{"actor": coord, "verb": "activate_emergency_level", "target_zones": [], "params": {"level": 2}}],
                        reason="Si la red de sensores enmudece con tendencia ascendente, se asume lo peor."))
    db.flush()


def sim_step(db: Session, c: Crisis) -> int:
    if (c.config or {}).get("external_feed"):
        return 0
    now_min = elapsed_min(c)
    due = [i for i in timeline_for(db, c) if c.sim_cursor_min < i["at_min"] <= now_min]
    for item in due:
        emit(db, c, item)
    c.sim_cursor_min = now_min
    return len(due)


def emit(db: Session, c: Crisis, item: dict[str, Any]) -> None:
    kind = item.get("kind")
    if kind == "raw_input":
        submit_raw_input(db, c, channel=item["channel"], source=item["source"], payload=item["payload"],
                         fallback=item.get("fallback"))
    elif kind == "sensor":
        if item["source"] in ((c.config or {}).get("silent_sources") or []):
            return  # the gauge is gone: nothing arrives, and nobody announces it
        upsert_signal(db, c, sig_id=None, t=scenario_now(c), source=item["source"], channel="sensor",
                      content=item["content"], is_noise=False,
                      claims=[{"hazard_type": c.hazard_type, "severity_hint": int(item["severity"])}],
                      zone=item.get("zone"), precision="exact", perceived_by="direct")
    elif kind == "world":
        apply_world_op(db, c, item)


def apply_world_op(db: Session, c: Crisis, item: dict[str, Any]) -> None:
    op, note = item.get("op"), item.get("note", "")
    if op == "source_silent":
        silent = set((c.config or {}).get("silent_sources") or []) | {item["source"]}
        c.config = {**(c.config or {}), "silent_sources": sorted(silent)}
    elif op == "entity_unreachable":
        ent = db.get(Entity, (c.id, item["entity"]))
        if ent is not None:
            ent.extra = {**(ent.extra or {}), "sim_unreachable": True}
    elif op == "entity_reachable":
        ent = db.get(Entity, (c.id, item["entity"]))
        if ent is not None:
            ent.extra = {k: v for k, v in (ent.extra or {}).items() if k != "sim_unreachable"}
            ent.status = "available"
            append_event(db, c, "entity.updated", entity_dict(ent))
    elif op == "road_cut":
        z = db.get(Zone, (c.id, item["zone"]))
        if z is not None:
            z.extra = {**(z.extra or {}), "road_cut": note or True}
            append_event(db, c, "zone.updated", zone_dict(z))
            # Known at once because a patrol reports it: an official, precise signal.
            upsert_signal(db, c, sig_id=None, t=scenario_now(c), source=item.get("source", "112"), channel="call",
                          content=note or f"Carretera cortada en {z.name}", is_noise=False,
                          claims=[{"hazard_type": "road_cut", "severity_hint": int(item.get("severity", 7))}],
                          zone=z.id, precision="street", location_text=note, perceived_by="direct",
                          summary=f"Road cut in {z.name}: {note}")
    elif op == "resource_loss":
        r = db.get(Resource, (c.id, item["resource"]))
        if r is not None:
            r.available = max(0.0, r.available - float(item.get("qty", 0)))
            append_event(db, c, "resource.updated", resource_dict(r), material=True,
                         digest=f"Resource loss: {note or r.name}. {r.name} now {r.available:g}/{r.total:g}.")
    elif op == "hazard_jump":
        upsert_signal(db, c, sig_id=None, t=scenario_now(c), source=item.get("source", "112"), channel="call",
                      content=note or "Empeoramiento súbito", is_noise=False,
                      claims=[{"hazard_type": c.hazard_type, "severity_hint": int(item.get("severity", 8))}],
                      zone=item.get("zone"), precision="zone", perceived_by="direct", summary=note)
    append_event(db, c, "sim.event", {"op": op, "note": note, **{k: v for k, v in item.items()
                                                                  if k in ("zone", "entity", "source", "resource", "qty")}})
