"""Crisis lifecycle, scenario clock, and the two read models the
HappyRobot brains consume: `state` (Kernel) and `snapshot` (Gateway)."""

import json
import random
import re
import unicodedata
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from valte.core.events import append_event
from valte.core.playbook import doctrine as hazard_doctrine
from valte.core.playbook import environment_brief as _environment_brief
from valte.models import (
    Action,
    Contact,
    Crisis,
    Entity,
    Event,
    Incident,
    Lesson,
    Manual,
    Outbox,
    Outcome,
    Plan,
    Resource,
    Signal,
    Tripwire,
    Zone,
    utcnow,
)
from valte.settings import settings

PACKS_DIR = Path(__file__).resolve().parents[1] / "sim" / "packs"

VERB_LABELS = {
    "send_es_alert": "Enviar ES-Alert",
    "order_evacuation": "Ordenar evacuación",
    "close_road": "Cortar carretera",
    "rescue": "Rescate",
    "pump_water": "Achique de agua",
    "shelter": "Alojar en albergue",
    "supplies": "Repartir suministros",
    "wellness_check": "Comprobar estado de vecinos",
    "request_ume": "Solicitar la UME",
    "activate_emergency_level": "Activar nivel de emergencia",
    "open_shelter": "Abrir albergue",
    "set_tripwire": "Armar disparador",
    "clear_tripwire": "Desarmar disparador",
    "schedule_check": "Programar revisión",
    "register_entity": "Registrar entidad descubierta",
    "update_entity": "Actualizar entidad",
    "recall_units": "Retirar unidades",
    "transfer_resource": "Mover recursos entre entidades",
    "request_resupply": "Pedir reposición",
}

# Verbs that commit a responder's finite units.
UNIT_VERBS = {"rescue", "pump_water", "wellness_check"}
SYSTEM_VERBS = {"set_tripwire", "clear_tripwire", "schedule_check", "register_entity", "update_entity",
                "recall_units", "transfer_resource", "request_resupply"}  # the last three: core/logistics.py
DEFAULT_APPROVAL_VERBS = ["order_evacuation", "request_ume"]


def slugify(text: str) -> str:
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-") or "x"


# ── clock ────────────────────────────────────────────────────────────────


def effective_speed(c: Crisis) -> float:
    # A human on a real call cannot keep up with 20x: the world waits.
    return 1.0 if c.slowmo else float(c.speed or 1.0)


def scenario_now(c: Crisis, wall: datetime | None = None) -> datetime:
    if c.paused:
        return c.anchor_scenario
    wall = wall or utcnow()
    return c.anchor_scenario + (wall - c.anchor_wall) * effective_speed(c)


def elapsed_min(c: Crisis) -> float:
    return (scenario_now(c) - c.t0_scenario).total_seconds() / 60.0


def set_clock(
    db: Session,
    c: Crisis,
    *,
    speed: float | None = None,
    paused: bool | None = None,
    slowmo: bool | None = None,
) -> None:
    """Re-anchor before changing the rate so time never jumps."""
    now_s = scenario_now(c)
    c.anchor_scenario = now_s
    c.anchor_wall = utcnow()
    if speed is not None:
        c.speed = max(0.1, min(float(speed), 600.0))
    if paused is not None:
        c.paused = paused
    if slowmo is not None:
        c.slowmo = slowmo
    append_event(db, c, "clock.changed", clock_dict(c))


def tz_of(c: Crisis) -> ZoneInfo:
    try:
        return ZoneInfo((c.config or {}).get("tz") or "Europe/Madrid")
    except Exception:
        return ZoneInfo("Europe/Madrid")


def hhmm(c: Crisis, dt: datetime | None) -> str:
    return dt.astimezone(tz_of(c)).strftime("%H:%M") if dt else ""


def clock_dict(c: Crisis) -> dict[str, Any]:
    now_s = scenario_now(c)
    mins = max(0, int((now_s - c.t0_scenario).total_seconds() // 60))
    return {
        "scenario_now": now_s.isoformat(),
        "clock": hhmm(c, now_s),
        "elapsed": f"T+{mins // 60:02d}:{mins % 60:02d}",
        "elapsed_min": mins,
        "speed": c.speed,
        "effective_speed": 0 if c.paused else effective_speed(c),
        "paused": c.paused,
        "slowmo": c.slowmo,
    }


# ── ids ──────────────────────────────────────────────────────────────────


def next_id(c: Crisis, prefix: str) -> str:
    counters = dict(c.counters or {})
    n = int(counters.get(prefix, 0)) + 1
    counters[prefix] = n
    c.counters = counters  # reassign: JSON columns do not track in-place edits
    return f"{prefix}-{n:04d}"


# ── lookups ──────────────────────────────────────────────────────────────


def get_crisis(db: Session, crisis_id: str | None) -> Crisis | None:
    """HappyRobot callbacks may omit the id: fall back to the live crisis."""
    if crisis_id and crisis_id not in ("", "null", "None", "undefined"):
        c = db.get(Crisis, crisis_id)
        if c:
            return c
        c = db.scalars(select(Crisis).where(Crisis.code == crisis_id)).first()
        if c:
            return c
    return db.scalars(
        select(Crisis).where(Crisis.status == "active").order_by(Crisis.created_at.desc())
    ).first()


def zones_of(db: Session, cid: str) -> list[Zone]:
    return list(db.scalars(select(Zone).where(Zone.crisis_id == cid).order_by(Zone.sort_index)))


def entities_of(db: Session, cid: str) -> list[Entity]:
    return list(db.scalars(select(Entity).where(Entity.crisis_id == cid).order_by(Entity.weight.desc(), Entity.id)))


def resources_of(db: Session, cid: str) -> list[Resource]:
    return list(db.scalars(select(Resource).where(Resource.crisis_id == cid).order_by(Resource.sort_index)))


def resolve_zone(db: Session, cid: str, ref: str | None) -> str | None:
    """Accept a zone id, a name, or any spelling an LLM may produce."""
    if not ref or str(ref).lower() in ("null", "none", "unknown", ""):
        return None
    key = slugify(str(ref))
    for z in zones_of(db, cid):
        if key in (z.id, slugify(z.name)):
            return z.id
    return None


# ── packs ────────────────────────────────────────────────────────────────


def list_packs() -> list[dict[str, Any]]:
    out = []
    for p in sorted(PACKS_DIR.glob("*.json")):
        pack = json.loads(p.read_text(encoding="utf-8"))
        out.append({k: pack.get(k) for k in ("id", "name", "hazard_type", "region", "description")})
    return out


def load_pack(pack_id: str) -> dict[str, Any]:
    path = PACKS_DIR / f"{slugify(pack_id)}.json"
    if not path.exists():
        raise KeyError(f"unknown pack {pack_id}")
    return json.loads(path.read_text(encoding="utf-8"))


# ── crisis creation ──────────────────────────────────────────────────────


def _default_entities(zones: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The wizard asks for zones, sources and resources but not for actors.
    A crisis with nobody to notify cannot be managed, so it gets a minimal
    chain of command; the agent can extend it with register_entity."""
    all_zones = [z["id"] for z in zones]
    ents: list[dict[str, Any]] = [
        {"id": "cecopi", "name": "CECOPI", "kind": "authority", "role": "coordination", "weight": 10,
         "trust": "high", "jurisdiction": [], "channel": {"kind": "none"},
         "capabilities": ["send_es_alert", "activate_emergency_level", "request_ume"],
         "activation": {"delay_min": 0, "cost": "low"}},
        {"id": "delegacion-gobierno", "name": "Delegación del Gobierno", "kind": "authority", "role": "authority",
         "weight": 9, "trust": "high", "jurisdiction": [], "channel": {"kind": "email", "address": "delegacion@demo.valte"},
         "capabilities": ["order_evacuation", "close_road", "open_shelter", "request_ume"],
         "activation": {"delay_min": 0, "cost": "low"}},
        {"id": "bomberos", "name": "Bomberos", "kind": "responder", "role": "responder", "weight": 7, "trust": "high",
         "jurisdiction": all_zones, "channel": {"kind": "email", "address": "bomberos@demo.valte"},
         "capabilities": ["rescue", "pump_water"], "units": {"total": 20, "available": 20},
         "activation": {"delay_min": 0, "cost": "low"}, "escalation_to": "delegacion-gobierno"},
        {"id": "policia", "name": "Policía", "kind": "responder", "role": "responder", "weight": 6, "trust": "high",
         "jurisdiction": all_zones, "channel": {"kind": "email", "address": "policia@demo.valte"},
         "capabilities": ["close_road", "wellness_check"], "units": {"total": 12, "available": 12},
         "activation": {"delay_min": 0, "cost": "low"}, "escalation_to": "delegacion-gobierno"},
        {"id": "proteccion-civil", "name": "Protección Civil", "kind": "responder", "role": "responder", "weight": 5,
         "trust": "high", "jurisdiction": all_zones, "channel": {"kind": "email", "address": "pc@demo.valte"},
         "capabilities": ["shelter", "supplies", "wellness_check"], "units": {"total": 10, "available": 10},
         "activation": {"delay_min": 10, "cost": "low"}, "escalation_to": "delegacion-gobierno"},
            # Outside reinforcements: far away and costly, so they must be requested early and signed by a human.
        {"id": "ume", "name": "UME · refuerzo estatal", "kind": "responder", "role": "responder", "weight": 8, "trust": "high",
         "jurisdiction": all_zones, "channel": {"kind": "email", "address": "ume@demo.valte"},
         "capabilities": ["rescue", "pump_water", "wellness_check"], "units": {"total": 60, "available": 0},
         "activation": {"delay_min": 180, "cost": "high"}, "escalation_to": "delegacion-gobierno",
         "notes": "Not operational until request_ume is approved and 180 minutes pass."},
    ]
    for z in zones:
        ents.append(
            {"id": f"ayto-{z['id']}", "name": f"Ayuntamiento de {z['name']}", "kind": "authority", "role": "authority",
             "weight": 7, "trust": "high", "jurisdiction": [z["id"]],
             "channel": {"kind": "email", "address": f"alcaldia-{z['id']}@demo.valte"},
             "capabilities": ["order_evacuation", "open_shelter", "close_road"],
             "activation": {"delay_min": 0, "cost": "low"}, "escalation_to": "delegacion-gobierno"})
        ents.append(
            {"id": f"poblacion-{z['id']}", "name": f"Vecinos · {z['name']}", "kind": "population", "weight": 1,
             "trust": "low", "jurisdiction": [z["id"]], "channel": {"kind": "none"}, "capabilities": [],
             "zone": z["id"]})
    return ents


def _norm_zones(raw: list[dict[str, Any]]) -> list[dict[str, Any]]:
    zones = []
    for i, z in enumerate(raw):
        name = z.get("name") or z.get("id") or f"Zona {i + 1}"
        pop = z.get("population", z.get("hab", 0))
        if isinstance(pop, str):
            pop = int(re.sub(r"\D", "", pop) or 0)
        zones.append({**z, "id": z.get("id") or slugify(name), "name": name, "population": int(pop or 0)})
    by_name = {slugify(z["name"]): z["id"] for z in zones}
    for z in zones:
        edges = []
        # The wizard sends "to": ["Cheste · 25 min"]; packs send downstream objects.
        for e in z.get("downstream") or z.get("to") or []:
            if isinstance(e, str):
                m = re.match(r"\s*(.+?)\s*[·:\-–]\s*(\d+)", e)
                target, delay = (m.group(1), int(m.group(2))) if m else (e, 30)
            else:
                target, delay = e.get("to") or e.get("zone") or e.get("name"), int(e.get("delay_min", 30))
            tid = by_name.get(slugify(str(target)), slugify(str(target)))
            if tid in {x["id"] for x in zones} and tid != z["id"]:
                edges.append({"to": tid, "delay_min": delay})
        z["downstream"] = edges
        z["is_origin"] = any(str(z.get(k, "")).lower() in ("true", "1") for k in ("is_origin", "origin"))
    return zones


def create_crisis(db: Session, spec: dict[str, Any]) -> Crisis:
    pack: dict[str, Any] = load_pack(spec["pack"]) if spec.get("pack") else {}
    name = spec.get("name") or pack.get("name") or "Crisis sin nombre"
    region = spec.get("region") or pack.get("region") or ""
    hazard = spec.get("hazard_type") or spec.get("scenario") or pack.get("hazard_type") or "other"

    zones = _norm_zones(spec.get("zones") or pack.get("zones") or [])
    entities = spec.get("entities") or pack.get("entities") or _default_entities(zones)
    resources = spec.get("resources") or pack.get("resources") or []
    sources = spec.get("sources") or []

    t0_raw = spec.get("t0") or pack.get("t0")
    if t0_raw:
        t0 = datetime.fromisoformat(t0_raw)
    elif pack.get("t0_time"):  # "14:05" today, in the pack's timezone
        hh, mm = (int(x) for x in pack["t0_time"].split(":"))
        t0 = datetime.now(ZoneInfo(pack.get("tz") or "Europe/Madrid")).replace(hour=hh, minute=mm, second=0, microsecond=0)
    else:
        t0 = utcnow()
    if t0.tzinfo is None:
        t0 = t0.replace(tzinfo=timezone.utc)

    prefix = (pack.get("code_prefix") or "".join(w[0] for w in re.findall(r"[A-Za-zÀ-ÿ]+", region or name))[:3] or "VLT").upper()
    cid = str(uuid.uuid4())
    crisis = Crisis(
        id=cid,
        code=f"{prefix}-{random.randint(1000, 9999)}",
        name=name,
        hazard_type=hazard,
        region=region,
        pack_id=pack.get("id"),
        source=spec.get("source") or ("pack" if pack else "wizard"),
        t0_scenario=t0,
        anchor_scenario=t0,
        anchor_wall=utcnow(),
        speed=float(spec.get("speed") or settings.valte_sim_speed),
        paused=True,
        config={
            "tz": pack.get("tz") or spec.get("tz") or "Europe/Madrid",
            "approval_verbs": pack.get("approval_verbs") or DEFAULT_APPROVAL_VERBS,
            "doctrine": pack.get("doctrine") or hazard_doctrine(hazard),
            "coordination_entity": pack.get("coordination_entity") or "cecopi",
            # True: the outside-world app feeds this crisis; the kernel does not play the pack timeline itself.
            "external_feed": bool(spec.get("external_feed")),
        },
        transcript=spec.get("transcript"),
    )
    db.add(crisis)

    for i, z in enumerate(zones):
        db.add(Zone(
            crisis_id=cid, id=z["id"], name=z["name"], population=z["population"], is_origin=z["is_origin"],
            elevation=z.get("elevation", "medium"), notes=z.get("notes", ""), downstream=z["downstream"],
            sort_index=i, base_at_risk_pct=float(z.get("base_at_risk_pct", 20)), extra={**(z.get("extra") or {}), **({"centroid": z["centroid"]} if z.get("centroid") else {})},
        ))

    for e in entities:
        units = e.get("units") or {}
        db.add(Entity(
            crisis_id=cid, id=e["id"], name=e["name"], kind=e["kind"], role=e.get("role", ""),
            weight=int(e.get("weight", 5)), trust=e.get("trust", "medium"), jurisdiction=e.get("jurisdiction") or [],
            channel=e.get("channel") or {"kind": "none"}, capabilities=e.get("capabilities") or [],
            units_total=units.get("total"), units_available=units.get("available", units.get("total")),
            activation=e.get("activation") or {}, escalation_to=e.get("escalation_to"), zone=e.get("zone"),
            status=e.get("status", "available"), provenance=e.get("provenance", "plan"), notes=e.get("notes", ""),
            extra=e.get("extra") or {},
        ))

    known = {e["id"] for e in entities}
    for s in sources:  # wizard step 3: data sources become information_source entities
        sid = s.get("id") or slugify(s.get("name", "fuente"))
        if sid in known:
            continue
        known.add(sid)
        db.add(Entity(
            crisis_id=cid, id=sid, name=s.get("name", sid), kind="information_source", weight=3,
            trust=s.get("trust", "medium"), channel={"kind": "none"}, capabilities=[],
            extra={"link": s.get("link") or "", "description": s.get("desc") or s.get("description") or ""},
        ))

    for i, r in enumerate(resources):
        total = float(r.get("total", r.get("qty", 0)) or 0)
        db.add(Resource(
            crisis_id=cid, id=r.get("id") or slugify(r.get("name", f"recurso-{i}")), name=r.get("name", ""),
            unit=r.get("unit", ""), description=r.get("desc") or r.get("description") or "", total=total,
            available=float(r.get("available", total)), sort_index=i,
            # Nothing is "general": what the wizard adds without an owner is the coordination centre's own stock.
            owner_entity_id=r.get("owner_entity_id") or crisis.config["coordination_entity"],
        ))

    for tw in pack.get("tripwires") or []:
        db.add(Tripwire(crisis_id=cid, id=tw["id"], cond=tw["if"], then=tw.get("then") or [],
                        reason=tw.get("reason", ""), set_by="plan", created_t=t0))

    db.flush()
    from valte.core.needs import add_default_reflexes  # lazy: needs imports this module

    add_default_reflexes(db, crisis)
    append_event(db, crisis, "crisis.created", {"id": cid, "name": name, "code": crisis.code})
    return crisis


def start_crisis(db: Session, c: Crisis) -> None:
    if c.started_at is None:
        c.started_at = utcnow()
    set_clock(db, c, paused=False)
    append_event(db, c, "crisis.started", {"id": c.id}, material=True,
                 digest=f"Crisis declared: {c.name} ({c.hazard_type}) in {c.region}.")


def environment_of(db: Session, c: Crisis) -> str:
    """Plain-language card every HappyRobot brain reads before the world JSON."""
    return _environment_brief(c, zones_of(db, c.id), doctrine_lines=(c.config or {}).get("doctrine") or [])


# ── serializers (v1 schema shapes) ───────────────────────────────────────


def zone_dict(z: Zone) -> dict[str, Any]:
    return {
        "id": z.id, "name": z.name, "population": z.population, "is_origin": z.is_origin,
        "elevation": z.elevation, "notes": z.notes, "downstream": z.downstream,
        "severity": z.severity_est, "trend": z.trend, "eta_min": z.eta_min, "warned": z.warned,
        "warned_at": z.warned_at.isoformat() if z.warned_at else None, "evacuating": z.evacuating,
        "evacuated_pct": round(z.evacuated_pct), "at_risk_pct": round(z.at_risk_pct),
        "road_closed": z.road_closed, "centroid": (z.extra or {}).get("centroid"),
        # reported by the people on the ground (incident channel)
        "road_cut": (z.extra or {}).get("road_cut"), "access_penalty_min": int((z.extra or {}).get("access_penalty_min", 0)),
        "power_out": bool((z.extra or {}).get("power_out")),
    }


def entity_dict(e: Entity) -> dict[str, Any]:
    d: dict[str, Any] = {
        "id": e.id, "name": e.name, "kind": e.kind, "role": e.role, "weight": e.weight, "trust": e.trust,
        "jurisdiction": e.jurisdiction, "channel": e.channel, "capabilities": e.capabilities,
        "activation": e.activation, "escalation_to": e.escalation_to, "zone": e.zone, "status": e.status,
        "provenance": e.provenance, "notes": e.notes,
    }
    if e.units_total is not None:
        d["units"] = {"total": e.units_total, "available": e.units_available or 0}
        d["deployed"] = e.deployed or {}
    if e.extra:
        d.update({k: v for k, v in e.extra.items() if k in ("link", "description")})
    return d


def signal_dict(s: Signal) -> dict[str, Any]:
    return {
        "id": s.id, "t": s.t.isoformat(), "source": s.source, "source_trust": s.source_trust,
        "modality": s.modality, "channel": s.channel, "content": s.content, "summary": s.summary,
        "claims": s.claims, "location": s.location, "confidence": s.confidence,
        "confidence_inputs": s.confidence_inputs, "is_noise": s.is_noise, "revision": s.revision,
        "perceived_by": s.perceived_by,
    }


ACTION_STATES = ("pending_approval", "waiting", "in_progress", "done", "failed", "rejected")


def action_state(a: Action) -> str:
    """What a person reads on the dashboard. `status` is the kernel's lifecycle; between the signature and
    the end an action can be in two places: ordered but its actor has not acknowledged it (waiting), or
    acknowledged with the work still going on in the field (in_progress: units out, UME on its way)."""
    if a.status == "approved":
        return "waiting"
    if a.status == "executed":
        res = a.reserved or {}
        return "in_progress" if (res.get("units") or res.get("until_t")) and not res.get("released") else "done"
    return a.status


def action_dict(a: Action) -> dict[str, Any]:
    return {
        "id": a.id, "t": a.t.isoformat(), "actor": a.actor, "verb": a.verb, "target_zones": a.target_zones,
        "params": a.params, "status": a.status, "state": action_state(a), "evidence": a.evidence, "reasoning": a.reasoning,
        "real_interaction": a.real_interaction, "origin": a.origin, "approval": a.approval,
        "escalated_from": a.escalated_from, "error": a.error, "plan_version": a.plan_version,
        "incident_id": a.incident_id, "lessons": a.lessons or [],
    }


def resource_dict(r: Resource) -> dict[str, Any]:
    return {"id": r.id, "name": r.name, "label": r.name, "unit": r.unit, "description": r.description,
            "total": r.total, "available": r.available, "owner_entity_id": r.owner_entity_id}


def tripwire_dict(t: Tripwire) -> dict[str, Any]:
    return {"id": t.id, "if": t.cond, "then": t.then, "reason": t.reason, "set_by": t.set_by,
            "active": t.active, "repeat": bool(t.repeat), "last_fired_t": t.last_fired_t.isoformat() if t.last_fired_t else None}


def contact_dict(k: Contact) -> dict[str, Any]:
    return {
        "id": k.id, "action_id": k.action_id, "entity_id": k.entity_id, "entity_name": k.entity_name,
        "channel": k.channel, "address": k.address, "purpose": k.purpose, "attempt": k.attempt,
        "status": k.status, "brief": k.brief, "hr_run_id": k.hr_run_id, "hr_session_id": k.hr_session_id,
        "transcript": k.transcript, "outcome": k.outcome, "t": k.t.isoformat(),
        "duration_s": k.duration_s, "error": k.error,
    }


def incident_dict(i: Incident) -> dict[str, Any]:
    return {"incident_id": i.id, "state": i.state, "priority": i.priority, "confidence": i.confidence,
            "title": i.title, "summary": i.summary, "hazard_types": i.hazard_types, "zone_ids": i.zone_ids,
            "evidence": i.evidence, "revisit_at": i.revisit_at.isoformat() if i.revisit_at else None,
            "plan_version": i.plan_version}


def plan_dict(p: Plan | None) -> dict[str, Any] | None:
    if p is None:
        return None
    return {"version": p.version, "t": p.t.isoformat(), "summary": p.summary, "objectives": p.objectives,
            "origin": p.origin, "active": p.active, "invalidated_reason": p.invalidated_reason,
            "material": p.material, "lessons": p.lessons or []}


def active_plan(db: Session, cid: str) -> Plan | None:
    return db.scalars(select(Plan).where(Plan.crisis_id == cid, Plan.active.is_(True))
                      .order_by(Plan.version.desc())).first()


# ── read models for the brains ───────────────────────────────────────────


def verb_catalog(c: Crisis) -> dict[str, Any]:
    return {
        "world": {
            "send_es_alert": "params.message (castellano y valenciano si aplica). Mass alert to target_zones.",
            "order_evacuation": "Evacuate target_zones. Needs human approval.",
            "close_road": "params.road optional.",
            "rescue": "params.units int. Commits responder units.",
            "pump_water": "params.units int.",
            "open_shelter": "params.capacity int optional.",
            "shelter": "params.people int.",
            "supplies": "params.resource id, params.qty number. The actor must be the `owner` of that resource.",
            "wellness_check": "params.units int.",
            "request_ume": "Long activation delay: request EARLY. Needs human approval.",
            "activate_emergency_level": "params.level 0-2.",
        },
        "system": {
            "set_tripwire": 'params.tripwire {"id","repeat"?:bool,"if":{"source"?,"zone"?,"min_severity","precision_in"?,"min_confidence"?} | {"type":"silence","source","silence_min"},"then":[{"actor"|"auto","verb","target_zones"|"signal","params"?}],"reason"}. actor "auto" = nearest responder with free units; target_zones "signal" = where the report comes from; repeat true = standing reflex.',
            "clear_tripwire": "params.id",
            "schedule_check": "params.delay_min, params.note — wake me again later.",
            "register_entity": "params.entity (full entity object; starts trust low).",
            "update_entity": "params.id plus fields to change (trust, status, notes).",
            "recall_units": "params.action_id of an executed unit action: its crew (and material) is free again at once. "
                            "Use it when the zone calmed down or a worse need waits and nobody else has units.",
            "transfer_resource": "params.resource id, params.to entity id, params.qty. Stock changes owner; "
                                 "the lender keeps 25 % of its own.",
            "request_resupply": "params.resource id, params.qty, params.eta_min (>= 20). More stock from outside the "
                                "crisis; it arrives later, so ask BEFORE it runs out. One order per resource at a time.",
        },
        "needs_approval": (c.config or {}).get("approval_verbs") or DEFAULT_APPROVAL_VERBS,
    }


def build_state(db: Session, c: Crisis, *, compact: bool = True) -> dict[str, Any]:
    """Everything the tactical brain may know. Capped: it is a prompt."""
    from valte.core.needs import open_needs, resource_board  # lazy: needs imports this module

    cid = c.id
    n_sig, n_act = (25, 15) if compact else (200, 100)
    signals = list(db.scalars(select(Signal).where(Signal.crisis_id == cid, Signal.is_noise.is_(False))
                              .order_by(Signal.seq.desc()).limit(n_sig)))
    actions = list(db.scalars(select(Action).where(Action.crisis_id == cid).order_by(Action.seq.desc()).limit(n_act)))
    pending = list(db.scalars(select(Action).where(Action.crisis_id == cid, Action.status == "pending_approval")))
    tripwires = list(db.scalars(select(Tripwire).where(Tripwire.crisis_id == cid, Tripwire.active.is_(True))))
    open_contacts = list(db.scalars(select(Contact).where(
        Contact.crisis_id == cid, Contact.status.in_(("queued", "sending", "ringing", "in_progress")))))
    all_sig = list(db.execute(select(Signal.source, Signal.is_noise).where(Signal.crisis_id == cid)))
    plan = active_plan(db, cid)
    from valte.core.incidents import brain_view  # lazy: incidents imports this module

    incidents = brain_view(db, c)
    from valte.core.learning import brain_view as lessons_view
    manuals = list(db.scalars(select(Manual).where(Manual.crisis_id == cid).limit(3)))

    def slim_action(a: Action) -> dict[str, Any]:
        d = {k: v for k, v in action_dict(a).items()
             if k in ("id", "t", "actor", "verb", "target_zones", "params", "status", "evidence", "reasoning", "error")}
        return d

    def slim_signal(s: Signal) -> dict[str, Any]:
        return {"id": s.id, "t": s.t.isoformat(), "source": s.source, "modality": s.modality,
                "content": s.content[:280], "claims": s.claims, "location": s.location,
                "confidence": s.confidence,
                "corroborated_by": (s.confidence_inputs or {}).get("corroborating_channels", [])}

    return {
        "environment": environment_of(db, c),
        "crisis": {"id": cid, "code": c.code, "name": c.name, "hazard_type": c.hazard_type, "region": c.region,
                   **{k: v for k, v in clock_dict(c).items() if k in ("scenario_now", "clock", "elapsed_min")},
                   "severity": c.severity, "trend": c.trend,
                   # what the person who declared it said, in their own words: context no signal carries
                   **({"declared_by_human_as": c.transcript[:700]} if c.source == "text" and c.transcript else {})},
        "doctrine": ((c.config or {}).get("doctrine") or [])
        + [f"Official protocol — {m.title}: {' '.join(m.highlights)[:400]}" for m in manuals],
        # learned in this crisis (apply at once) and in earlier ones of its kind; cite the id in what they shape
        "lessons": lessons_view(db, c),
        "verbs": verb_catalog(c),
        "zones": [zone_dict(z) for z in zones_of(db, cid)],
        "entities": [
            {k: v for k, v in entity_dict(e).items() if k not in ("role", "zone") and v not in (None, "", [], {})}
            for e in entities_of(db, cid) if e.kind != "population"
        ],
        "resources": [{"id": r.id, "name": r.name, "available": r.available, "total": r.total, "unit": r.unit,
                       "owner": r.owner_entity_id} for r in resources_of(db, cid)],
        "incoming_resupply": (c.wake or {}).get("deliveries") or [],  # ordered with request_resupply, not here yet
        "situation": {"emergency_level": c.emergency_level, "notes": c.situation_note,
                      "plan": plan_dict(plan), "incidents": incidents},
        # Demand vs supply, recomputed on every wake-up: what is waiting for help and who still has units.
        "open_needs": open_needs(db, c),
        "resource_board": resource_board(db, c),
        "active_tripwires": [tripwire_dict(t) for t in tripwires],
        "recent_signals": [slim_signal(s) for s in signals],
        "signal_counts": {"total": len(all_sig), "noise_discarded": sum(1 for _, n in all_sig if n)},
        "recent_actions": [slim_action(a) for a in actions],
        "pending_approval": [slim_action(a) for a in pending],
        "open_contacts": [{"id": k.id, "entity": k.entity_id, "channel": k.channel, "status": k.status,
                           "action_id": k.action_id, "purpose": k.purpose} for k in open_contacts],
    }


def build_snapshot(db: Session, c: Crisis) -> dict[str, Any]:
    """Gateway read model: same world, command-bus vocabulary."""
    cid = c.id
    state = build_state(db, c)
    outcomes = list(db.scalars(select(Outcome).where(Outcome.crisis_id == cid).order_by(Outcome.t.desc()).limit(20)))
    events = list(db.scalars(select(Event).where(Event.crisis_id == cid, Event.material.is_(True))
                             .order_by(Event.seq.desc()).limit(25)))
    outbox = list(db.scalars(select(Outbox).where(Outbox.crisis_id == cid, Outbox.status == "pending").limit(20)))
    return {
        "environment": state["environment"],
        "run": {"run_id": cid, "code": c.code, "name": c.name, "hazard_type": c.hazard_type, "region": c.region,
                "state_version": c.state_version, "plan_version": c.plan_version,
                "scenario_now": scenario_now(c).isoformat(), "updated_at": utcnow().isoformat(),
                "emergency_level": c.emergency_level, "severity": c.severity, "trend": c.trend,
                "doctrine": state["doctrine"], "lessons": state["lessons"]},
        "zone_catalog": state["zones"],
        "entities": state["entities"],
        "signals": state["recent_signals"],
        "signal_counts": state["signal_counts"],
        "incidents": state["situation"]["incidents"],
        "plan": state["situation"]["plan"],
        "actions": state["recent_actions"],
        "pending_approval": state["pending_approval"],
        "outcomes": [{"outcome_id": o.id, "action_id": o.action_id, "attempt_id": o.attempt_id,
                      "status": o.status, "summary": o.summary, "observed_effects": o.observed_effects,
                      "t": o.t.isoformat()} for o in outcomes],
        "resources": state["resources"],
        "events": [{"event_id": e.seq, "type": e.type, "t": e.t.isoformat(), "digest": e.digest} for e in events],
        "outbox": [{"id": o.id, "workflow": o.workflow, "purpose": o.purpose} for o in outbox],
    }


def zone_catalog_text(db: Session, cid: str) -> str:
    """Compact zone list handed to the perception workflows."""
    lines = []
    for z in zones_of(db, cid):
        down = ", ".join(f"{e['to']} in {e['delay_min']} min" for e in z.downstream) or "end of path"
        lines.append(f"{z.id} ({z.name}{'; origin' if z.is_origin else ''}) -> {down}")
    return "\n".join(lines)

