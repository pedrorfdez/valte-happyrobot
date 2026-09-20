"""What the dashboard reads and the ways a human intervenes."""

import asyncio
import json
from typing import Any

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import select

from valte import bus, geo
from valte.api.deps import crisis_tx
from valte.core import actions, declare, incidents, learning, reports, views, world, world_parse
from valte.core.events import append_event, event_dict
from valte.core.intake import submit_raw_input
from valte.core.signals import upsert_signal
from valte.db import session_scope
from valte.models import Action, Contact, Crisis, Entity, Event, Incident, Lesson, Manual, Tripwire, Zone
from valte.sim.runner import apply_world_op, timeline_for

router = APIRouter(tags=["dashboard"])


# ── crises ───────────────────────────────────────────────────────────────


class ZoneIn(BaseModel):
    id: str | None = None
    name: str
    population: int | str | None = None
    hab: int | str | None = None
    is_origin: bool | str = False
    origin: bool | str | None = None
    to: list[Any] = []
    downstream: list[Any] = []
    notes: str = ""


class SourceIn(BaseModel):
    name: str
    link: str = ""
    desc: str = ""
    description: str = ""
    trust: str = "medium"


class ResourceIn(BaseModel):
    name: str
    qty: float | str | None = None
    total: float | None = None
    unit: str = ""
    desc: str = ""
    description: str = ""


class DeclaredFactIn(BaseModel):
    zone: str
    severity: int = 6
    text: str
    place: str = ""
    people: int = 0


class CrisisIn(BaseModel):
    """What `POST /crises/draft` understood from the free-text description (or a hand-made spec): scenario, zones,
    data sources, resources."""

    name: str | None = None
    region: str | None = None
    scenario: str | None = Field(None, description="flood|fire|blackout|infra|mci|other")
    hazard_type: str | None = None
    pack: str | None = Field(None, description="Scenario pack that brings entities and a live timeline.")
    zones: list[ZoneIn] = []
    sources: list[SourceIn] = []
    resources: list[ResourceIn] = []
    speed: float | None = None
    start: bool = True
    transcript: str | None = Field(None, description="The description the person wrote or dictated, kept as the crisis briefing.")
    source: str | None = Field(None, description="text when it was declared from a free-text description")
    reports: list[DeclaredFactIn] = Field([], description="What the description says is already happening (from POST /crises/draft): "
                                                          "the first data of the crisis, before any call or sensor.")
    external_feed: bool = Field(False, description="True when an outside app sends the data (the kernel does not play the pack timeline).")


@router.get("/packs")
def get_packs() -> list[dict[str, Any]]:
    return world.list_packs()


@router.get("/packs/{pack_id}")
def get_pack(pack_id: str) -> dict[str, Any]:
    """Prefill for the wizard."""
    try:
        pack = world.load_pack(pack_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="unknown pack")
    return {k: v for k, v in pack.items() if k != "timeline"}


@router.get("/packs/{pack_id}/timeline")
def get_pack_timeline(pack_id: str) -> list[dict[str, Any]]:
    """The scripted outside world, for the feeder app."""
    try:
        return sorted(world.load_pack(pack_id).get("timeline") or [], key=lambda i: i["at_min"])
    except KeyError:
        raise HTTPException(status_code=404, detail="unknown pack")


@router.get("/crises/{crisis_id}/timeline")
def get_crisis_timeline(crisis_id: str, hazard: str | None = Query(None, pattern="^(flood|fire|blackout|infra|mci|other)$")) -> list[dict[str, Any]]:
    """What the outside world will do to THIS crisis: its pack's script when it fits, else one generated from its zones.
    `hazard` asks for a given kind of world (the feeder app simulates flood or fire on whatever crisis it is told)."""
    with crisis_tx(crisis_id) as (db, c):
        return timeline_for(db, c, hazard)


@router.get("/crises")
def list_crises(status: str | None = None) -> list[dict[str, Any]]:
    with session_scope() as db:
        q = select(Crisis).order_by(Crisis.created_at.desc())
        if status:
            q = q.where(Crisis.status == status)
        return [{**views.crisis_card(db, c), "num": f"{i + 1:02d}"} for i, c in enumerate(db.scalars(q))]


@router.post("/crises/{crisis_id}/locate")
def locate(crisis_id: str, background: BackgroundTasks) -> dict[str, Any]:
    """Put the zones on the map (pack coordinates, else a lookup by name). Idempotent; runs in the background."""
    with crisis_tx(crisis_id) as (db, c):
        missing = [z.id for z in world.zones_of(db, c.id) if not (z.extra or {}).get("centroid")]
    if missing:
        background.add_task(geo.locate_zones, crisis_id)
    return {"locating": missing}


class DraftIn(BaseModel):
    text: str = Field(..., min_length=1, max_length=8000, description="Everything the person knows, written or dictated.")


@router.post("/crises/draft")
async def draft_crisis(body: DraftIn) -> dict[str, Any]:
    """Free text → the crisis it describes, for the person to look over. Creates nothing."""
    if len(body.text.strip()) < 12:
        raise HTTPException(status_code=422, detail="Cuenta algo más: qué pasa, dónde y a quién afecta.")
    return await declare.draft(body.text)


@router.post("/crises", status_code=201)
def create_crisis(body: CrisisIn, background: BackgroundTasks) -> dict[str, Any]:
    spec = body.model_dump(exclude_none=True)
    for r in spec.get("resources", []):
        if r.get("qty") not in (None, ""):
            try:
                r["total"] = float(str(r["qty"]).replace(",", "."))
            except ValueError:
                r["total"] = 0
    with session_scope() as db:
        try:
            c = world.create_crisis(db, spec)
        except KeyError as e:
            raise HTTPException(status_code=404, detail=str(e))
        learning.apply_lessons(db, c)
        if body.start:
            world.start_crisis(db, c)
        # The declaration is the first data: risk per zone, incidents and the brains' first actions follow from it at
        # once, and whatever arrives later (calls, sensors, media) corrects it.
        declare.seed(db, c, spec.get("reports") or [])
        background.add_task(geo.locate_zones, c.id)
        return views.header(db, c)


@router.get("/crises/{crisis_id}")
def get_crisis(crisis_id: str, entity_id: str | None = None) -> dict[str, Any]:
    """`entity_id` = who is looking: inventories (the Recursos KPI) are scoped to what that entity owns."""
    with crisis_tx(crisis_id) as (db, c):
        return views.header(db, c, viewer=db.get(Entity, (c.id, entity_id)) if entity_id else None)


@router.post("/crises/{crisis_id}/start")
def start(crisis_id: str) -> dict[str, Any]:
    with crisis_tx(crisis_id) as (db, c):
        world.start_crisis(db, c)
        return views.header(db, c)


@router.post("/crises/{crisis_id}/close")
def close(crisis_id: str, background: BackgroundTasks) -> dict[str, Any]:
    """Closes the crisis and carries what it taught to the next ones of its kind. An LLM post-mortem
    (PedroD-crisis-review) adds up to 4 more lessons in the background when HappyRobot is available."""
    with crisis_tx(crisis_id) as (db, c):
        lessons = learning.close_crisis(db, c)
        background.add_task(learning.review_with_hr, crisis_id)
        return {"status": c.status, "lessons": [learning.lesson_dict(l) for l in lessons]}


# ── screens ──────────────────────────────────────────────────────────────


@router.get("/crises/{crisis_id}/overview")
def overview(crisis_id: str, role: str = Query("coordination", pattern="^(coordination|authority|responder)$"),
             entity_id: str | None = None) -> dict[str, Any]:
    with crisis_tx(crisis_id) as (db, c):
        return views.overview(db, c, role=role, entity_id=entity_id)


def _viewer(db, c: Crisis, entity_id: str | None) -> Entity | None:
    """`entity_id` = who is looking. Every screen shows what concerns that entity, like its role panel does."""
    return db.get(Entity, (c.id, entity_id)) if entity_id else None


@router.get("/crises/{crisis_id}/zones")
def zones(crisis_id: str, entity_id: str | None = None) -> dict[str, Any]:
    with crisis_tx(crisis_id) as (db, c):
        return views.zones_screen(db, c, viewer=_viewer(db, c, entity_id))


@router.get("/crises/{crisis_id}/zones/{zone_id}")
def zone(crisis_id: str, zone_id: str) -> dict[str, Any]:
    with crisis_tx(crisis_id) as (db, c):
        z = db.get(Zone, (c.id, zone_id))
        if z is None:
            raise HTTPException(status_code=404, detail="zone not found")
        return views.zone_view(db, c, z, world.zones_of(db, c.id), world.entities_of(db, c.id))


@router.get("/crises/{crisis_id}/actions")
def list_actions(crisis_id: str, status: str | None = None, actor: str | None = None, zone: str | None = None,
                 entity_id: str | None = None) -> dict[str, Any]:
    with crisis_tx(crisis_id) as (db, c):
        return views.actions_screen(db, c, status=status, actor=actor, zone=zone, viewer=_viewer(db, c, entity_id))


class IncidentDecisionIn(BaseModel):
    by: str = "operador"
    reason: str = ""
    into: str | None = Field(None, description="merge: the incident that stays")


@router.get("/crises/{crisis_id}/incidents")
def list_incidents(crisis_id: str, state: str | None = None, zone: str | None = None, entity_id: str | None = None,
                   limit: int = 100) -> dict[str, Any]:
    """What is happening: one or several signals make an incident. `state` = open (default view adds what is over) |
    unattended | candidate | active | attended | resolved | dismissed | closed | all. `entity_id` scopes it to that
    entity's jurisdiction."""
    with crisis_tx(crisis_id) as (db, c):
        ent = db.get(Entity, (c.id, entity_id)) if entity_id else None
        scope = (ent.jurisdiction or None) if ent is not None and not views.sees_everything(ent) else None
        return views.incidents_screen(db, c, state=state, zone=zone, zone_ids=scope, limit=limit)


def _incident(db, c: Crisis, incident_id: str) -> Incident:
    inc = db.get(Incident, (c.id, incident_id))
    if inc is None:
        raise HTTPException(status_code=404, detail="incident not found")
    return inc


@router.get("/crises/{crisis_id}/incidents/{incident_id}")
def get_incident(crisis_id: str, incident_id: str) -> dict[str, Any]:
    """The incident with the evidence behind it (its signals) and who is on it (its actions)."""
    with crisis_tx(crisis_id) as (db, c):
        return views.incident_item(db, c, _incident(db, c, incident_id), views._names(db, c.id), detail=True)


@router.post("/crises/{crisis_id}/incidents/{incident_id}/dismiss")
def dismiss_incident(crisis_id: str, incident_id: str, body: IncidentDecisionIn) -> dict[str, Any]:
    """A person says it is not true (a false alarm, a hoax). The kernel remembers which sources said it."""
    with crisis_tx(crisis_id) as (db, c):
        inc = _incident(db, c, incident_id)
        if inc.state not in incidents.OPEN:
            raise HTTPException(status_code=409, detail=f"la incidencia ya está {incidents.STATE_ES.get(inc.state, inc.state).lower()}")
        incidents.dismiss(db, c, inc, by=body.by, reason=body.reason)
        return views.incident_item(db, c, inc, views._names(db, c.id))


@router.post("/crises/{crisis_id}/incidents/{incident_id}/merge")
def merge_incident(crisis_id: str, incident_id: str, body: IncidentDecisionIn) -> dict[str, Any]:
    """`incident_id` is the same event as `into`: its signals and actions move there."""
    with crisis_tx(crisis_id) as (db, c):
        drop, keep = _incident(db, c, incident_id), _incident(db, c, body.into or "")
        if drop.id == keep.id or keep.state not in incidents.OPEN:
            raise HTTPException(status_code=409, detail="elige otra incidencia abierta como destino")
        return views.incident_item(db, c, incidents.merge(db, c, keep, drop, by=body.by), views._names(db, c.id))


@router.get("/crises/{crisis_id}/signals")
def list_signals(crisis_id: str, modality: str | None = None, noise: bool | None = None, zone: str | None = None,
                 precise: bool = False, limit: int = 100, entity_id: str | None = None) -> dict[str, Any]:
    with crisis_tx(crisis_id) as (db, c):
        return views.signals_screen(db, c, modality=modality, noise=noise, zone=zone, precise=precise, limit=limit,
                                    viewer=_viewer(db, c, entity_id))


@router.get("/crises/{crisis_id}/signals/stats")
def signal_stats(crisis_id: str) -> dict[str, Any]:
    with crisis_tx(crisis_id) as (db, c):
        return views.signals_stats(db, c)


@router.get("/crises/{crisis_id}/entities")
def list_entities(crisis_id: str, kind: str | None = None, entity_id: str | None = None) -> list[dict[str, Any]]:
    with crisis_tx(crisis_id) as (db, c):
        viewer = db.get(Entity, (c.id, entity_id)) if entity_id else None
        out = []
        for e in world.entities_of(db, c.id):
            if kind and e.kind != kind:
                continue
            d = world.entity_dict(e)
            if not views.sees_everything(viewer) and e.id != viewer.id:
                d.pop("units", None)      # how many units someone else has left is theirs (and CECOPI's) to know
                d.pop("deployed", None)
            out.append(d)
        return out


@router.get("/crises/{crisis_id}/resources")
def resources(crisis_id: str, entity_id: str | None = None) -> dict[str, Any]:
    with crisis_tx(crisis_id) as (db, c):
        return views.resources_screen(db, c, viewer=db.get(Entity, (c.id, entity_id)) if entity_id else None)


@router.get("/crises/{crisis_id}/directory")
def directory(crisis_id: str, entity_id: str | None = None) -> dict[str, Any]:
    """Contacts = the entities we can communicate with, each with its communications (a neighbour gets only who to turn to)."""
    with crisis_tx(crisis_id) as (db, c):
        return views.directory_screen(db, c, viewer=db.get(Entity, (c.id, entity_id)) if entity_id else None)


class MessageIn(BaseModel):
    message: str = Field(..., min_length=1)
    by: str = Field("operador", description="Who is sending it (operator or the entity the human acts as).")


@router.post("/crises/{crisis_id}/entities/{entity_id}/contact", status_code=201)
def contact_entity(crisis_id: str, entity_id: str, body: MessageIn) -> dict[str, Any]:
    """A person starts a communication from the directory; it leaves through the entity's own channel
    (real email or a real voice call by the agent), like every other communication."""
    from valte.core import outreach
    from valte.models import Entity

    with crisis_tx(crisis_id) as (db, c):
        ent = db.get(Entity, (c.id, entity_id))
        if ent is None:
            raise HTTPException(status_code=404, detail="entity not found")
        if not outreach.contactable(ent):
            raise HTTPException(status_code=409, detail=f"{ent.name} no tiene canal de contacto")
        if not views.access(db.get(Entity, (c.id, body.by)))["can_contact"]:  # `by` is an operator's name or an entity id
            raise HTTPException(status_code=403, detail="la población no puede pedir al agente que contacte con una entidad")
        k = outreach.queue_contact(db, c, entity=ent, purpose="notify", message=body.message.strip(), by=body.by)
        append_event(db, c, "human.contact", {"contact_id": k.id, "entity": ent.id, "by": body.by}, material=True,
                     digest=f"A human ({body.by}) contacted {ent.id} directly: {body.message.strip()[:160]}")
        return views.contact_row(c, k)


@router.get("/crises/{crisis_id}/contacts")
def contacts(crisis_id: str, entity_id: str | None = None) -> dict[str, Any]:
    with crisis_tx(crisis_id) as (db, c):
        return views.contacts_screen(db, c, entity=entity_id)


@router.get("/crises/{crisis_id}/contacts/{contact_id}")
def contact(crisis_id: str, contact_id: str) -> dict[str, Any]:
    with crisis_tx(crisis_id) as (db, c):
        k = db.get(Contact, contact_id)
        if k is None or k.crisis_id != c.id:
            raise HTTPException(status_code=404, detail="contact not found")
        return views.contact_detail(db, c, k)


@router.get("/crises/{crisis_id}/plan")
def plan(crisis_id: str) -> dict[str, Any]:
    with crisis_tx(crisis_id) as (db, c):
        return views.plan_screen(db, c)


@router.get("/crises/{crisis_id}/tripwires")
def tripwires(crisis_id: str) -> list[dict[str, Any]]:
    with crisis_tx(crisis_id) as (db, c):
        return [world.tripwire_dict(t) for t in db.scalars(select(Tripwire).where(Tripwire.crisis_id == c.id))]


class LessonIn(BaseModel):
    text: str = Field(..., min_length=8, max_length=400)
    by: str = "cecopi"
    evidence: list[str] = []


@router.get("/crises/{crisis_id}/lessons")
def lessons(crisis_id: str) -> dict[str, Any]:
    """`now` = learned while this crisis runs (already applied to it); `before` = what earlier crises of its kind left.
    Each lesson carries its evidence and where it was applied here."""
    with crisis_tx(crisis_id) as (db, c):
        if c.status == "active":
            learning.learn_now(db, c)
        return learning.lessons_screen(db, c)


@router.post("/crises/{crisis_id}/lessons", status_code=201)
def teach(crisis_id: str, body: LessonIn) -> dict[str, Any]:
    """A supervisor tells the system something it could not know; the brains read it on their next wake-up."""
    with crisis_tx(crisis_id) as (db, c):
        l = learning.add_human_lesson(db, c, text=body.text, by=body.by, evidence=body.evidence)
        return learning.lesson_dict(l, crisis_id=c.id)


@router.get("/crises/{crisis_id}/manuals")
def manuals(crisis_id: str) -> list[dict[str, Any]]:
    with crisis_tx(crisis_id) as (db, c):
        return [{"title": m.title, "url": m.url, "published_date": m.published_date, "highlights": m.highlights}
                for m in db.scalars(select(Manual).where(Manual.crisis_id == c.id))]


# ── human intervention ───────────────────────────────────────────────────


class DecisionIn(BaseModel):
    by: str = Field("operador", description="Entity id or operator name taking the decision.")
    note: str = ""


class ManualActionIn(BaseModel):
    actor: str
    verb: str
    target_zones: list[str] = []
    params: dict[str, Any] = {}
    reasoning: str = ""
    evidence: list[str] = []
    by: str | None = Field(None, description="Entity the human is acting as (role panel).")


class NoteIn(BaseModel):
    content: str
    zone: str | None = None
    severity: int = 0
    source: str = "operador"


class RawInputIn(BaseModel):
    """One thing the outside world says: a 112 call, a post, a bulletin, a sensor reading."""

    channel: str = Field(..., description="call|social|news|sensor|other")
    source: str
    payload: dict[str, Any] = {}
    fallback: dict[str, Any] | None = Field(None, description="Scripted perception used only if HappyRobot does not answer.")
    zone: str | None = None        # sensors
    severity: int | None = None    # sensors
    content: str = ""              # sensors
    hazard: str | None = None      # sensors: what it measures when the outside world plays a hazard of its own choosing


class ReportIn(BaseModel):
    """What one of the crisis's own actors tells the system: an incident ('the CV-36 bridge has just collapsed') or a
    change in the dispositivo ('se inunda Alfafar', 'nos llegan 200 mantas', 'se suma Cruz Roja', 'ya hemos cortado…')."""

    by: str = Field(..., description="Entity id of who reports (authority, responder, or population: low reliability).")
    kind: str = Field("other", description="Damage: road_cut|people_trapped|building_damage|power_out|resource_lost|units_down|"
                                           "shelter_full|other. Changes to the world: zone_new|resource_new|entity_new|action_done.")
    name: str = Field("", description="What happened, in one line. With the kind, all the form asks for: zone, place, stock, "
                                      "amounts, who joins and what was done are worked out of it unless given below.")
    text: str = Field("", description="Same as name (older callers).")
    zone: str | None = None
    place: str = ""
    severity: int | None = None
    resource: str | None = None
    qty: float | None = None
    units: int | None = None
    population: int | None = Field(None, description="zone_new: inhabitants of the new zone.")
    entity: str | None = Field(None, description="entity_new: name of whoever joins.")
    verb: str | None = Field(None, description="action_done: the verb, when the text does not make it obvious.")


class ClockIn(BaseModel):
    speed: float | None = None
    paused: bool | None = None


class InjectIn(BaseModel):
    kind: str = Field(..., description="situation|signal|entity_unreachable|entity_reachable|source_silent|road_cut|hazard_jump|resource_loss")
    zone: str | None = None
    entity: str | None = None
    source: str | None = None
    resource: str | None = None
    qty: float | None = None
    severity: int | None = None
    note: str = ""
    channel: str = "call"
    content: str = ""


def _action_or_404(db, c: Crisis, action_id: str) -> Action:
    act = db.get(Action, (c.id, action_id))
    if act is None:
        raise HTTPException(status_code=404, detail="action not found")
    return act


@router.post("/crises/{crisis_id}/actions/{action_id}/approve")
def approve(crisis_id: str, action_id: str, body: DecisionIn) -> dict[str, Any]:
    with crisis_tx(crisis_id) as (db, c):
        act = _action_or_404(db, c, action_id)
        if act.status != "pending_approval":
            raise HTTPException(status_code=409, detail=f"action is {act.status}, not pending approval")
        actions.approve_action(db, c, act, by=body.by, via="dashboard", note=body.note)
        return world.action_dict(act)


@router.post("/crises/{crisis_id}/actions/{action_id}/reject")
def reject(crisis_id: str, action_id: str, body: DecisionIn) -> dict[str, Any]:
    with crisis_tx(crisis_id) as (db, c):
        act = _action_or_404(db, c, action_id)
        if act.status != "pending_approval":
            raise HTTPException(status_code=409, detail=f"action is {act.status}, not pending approval")
        actions.reject_action(db, c, act, by=body.by, via="dashboard", reason=body.note)
        return world.action_dict(act)


@router.post("/crises/{crisis_id}/actions", status_code=201)
def manual_action(crisis_id: str, body: ManualActionIn) -> dict[str, Any]:
    """The 'Tus capacidades' buttons: a human acts directly, through the same pipeline."""
    with crisis_tx(crisis_id) as (db, c):
        res = actions.propose_action(db, c, {
            **body.model_dump(exclude={"by"}),
            "reasoning": body.reasoning or f"Acción manual de {body.by or 'operador'} desde el panel.",
        }, origin="human", by=body.by or body.actor)
        if res.get("error"):
            raise HTTPException(status_code=422, detail=res["error"])
        act = db.get(Action, (c.id, res["id"]))
        append_event(db, c, "human.action", {"action_id": res["id"], "by": body.by or body.actor}, material=True,
                     digest=f"A human ({body.by or body.actor}) ordered {body.verb} on {body.target_zones}: do not duplicate it.")
        return world.action_dict(act)


@router.post("/crises/{crisis_id}/signals", status_code=201)
def operator_note(crisis_id: str, body: NoteIn) -> dict[str, Any]:
    """Something the operator knows and the sources do not."""
    with crisis_tx(crisis_id) as (db, c):
        raw = submit_raw_input(db, c, channel="operator", source=world.slugify(body.source),
                               payload={"content": body.content, "zone": body.zone, "severity": body.severity,
                                        "modality": "text"})
        return {"id": raw.id, "state": raw.state}


@router.post("/crises/{crisis_id}/inputs", status_code=201)
def raw_input(crisis_id: str, body: RawInputIn) -> dict[str, Any]:
    """Where data sources deliver. Text goes to HappyRobot for perception; a sensor reading is already structured."""
    with crisis_tx(crisis_id) as (db, c):
        if c.status != "active":
            raise HTTPException(status_code=409, detail="crisis is closed")
        if body.channel == "sensor":
            if body.source in ((c.config or {}).get("silent_sources") or []):
                return {"dropped": "source is silent"}
            sig, _ = upsert_signal(db, c, sig_id=None, t=world.scenario_now(c), source=body.source, channel="sensor",
                                   content=body.content, is_noise=False,
                                   claims=[{"hazard_type": body.hazard or c.hazard_type, "severity_hint": int(body.severity or 0)}],
                                   zone=body.zone, precision="exact", perceived_by="direct")
            return {"id": sig.id, "state": "perceived"}
        raw = submit_raw_input(db, c, channel=body.channel, source=body.source, payload=body.payload, fallback=body.fallback)
        return {"id": raw.id, "state": raw.state}


class FeedIn(BaseModel):
    external: bool = True


@router.post("/crises/{crisis_id}/feed")
def set_feed(crisis_id: str, body: FeedIn) -> dict[str, Any]:
    """The outside-world app takes over (or hands back) the data feed of a crisis."""
    with crisis_tx(crisis_id) as (db, c):
        c.config = {**(c.config or {}), "external_feed": body.external}
        return {"external_feed": body.external, "pack": c.pack_id}


@router.get("/crises/{crisis_id}/reports")
def list_reports(crisis_id: str, by: str | None = None) -> dict[str, Any]:
    with crisis_tx(crisis_id) as (db, c):
        reporter = db.get(Entity, (c.id, by)) if by else None  # the kinds a neighbour can report are fewer
        return {"kinds": reports.kinds(reporter), "reliability": reports.reliability(reporter),
                "reports": reports.list_reports(db, c, by=by)}


@router.post("/crises/{crisis_id}/reports", status_code=201)
async def file_report(crisis_id: str, body: ReportIn, background: BackgroundTasks) -> dict[str, Any]:
    """The incident channel: trusted, located, and with consequences applied at once (access, stock, units, shelter),
    and the same channel for what CHANGED — a zone nobody had listed, stock that arrives, somebody who joins with their
    own material, an action a person already took. From the population it is a low-reliability lead instead: a signal,
    no consequences until it is corroborated. A trusted reporter's free text is read (HappyRobot when available) so the
    kind, zone and amounts come out of the line."""
    text = (body.name or body.text or "").strip()
    extras = body.model_dump(exclude={"name", "text", "by", "kind"})
    kind, by = body.kind, body.by
    with crisis_tx(crisis_id) as (db, c):
        if c.status != "active":
            raise HTTPException(status_code=409, detail="la crisis está cerrada")
        reporter = db.get(Entity, (c.id, by))
        trusted = reports.reliability(reporter) == "high"
    if trusted and text:
        parsed = await world_parse.interpret(crisis_id, text, hint_kind=kind, by=by)
        extras = world_parse.fill({**extras, "kind": kind}, parsed, hint_kind=kind)
        kind = extras.pop("kind", kind)
    with crisis_tx(crisis_id) as (db, c):
        extras = {k: extras[k] for k in ("zone", "place", "severity", "resource", "qty", "units", "population", "entity", "verb")
                  if k in extras}
        try:
            out = reports.file_report(db, c, by=by, kind=kind, text=text, **extras)
        except reports.BadReport as e:
            raise HTTPException(status_code=422, detail=str(e))
    if out["kind"] == "zone_new":
        background.add_task(geo.locate_zones, crisis_id)  # put the new zone on the map without making anybody wait
    return out


@router.post("/crises/{crisis_id}/replan")
def replan(crisis_id: str, body: DecisionIn) -> dict[str, Any]:
    with crisis_tx(crisis_id) as (db, c):
        c.wake = {**(c.wake or {}), "replan_requested": body.note or f"pedido por {body.by}", "cmd_last": None}
        return {"queued": True}


@router.post("/crises/{crisis_id}/clock")
def clock(crisis_id: str, body: ClockIn) -> dict[str, Any]:
    with crisis_tx(crisis_id) as (db, c):
        world.set_clock(db, c, speed=body.speed, paused=body.paused)
        return world.clock_dict(c)


@router.post("/crises/{crisis_id}/sim/inject")
async def inject(crisis_id: str, body: InjectIn, background: BackgroundTasks) -> dict[str, Any]:
    """Change the world mid-run ('¿y si se corta la carretera?'). A free-text `situation` is a fact: it is read and
    applied with consequences, not sent as an unverified 112 call."""
    if body.kind == "situation":
        text = (body.content or body.note or "").strip()
        if not text:
            raise HTTPException(status_code=422, detail="escribe qué está pasando")
        parsed = await world_parse.interpret(crisis_id, text, hint_kind="")
        with crisis_tx(crisis_id) as (db, c):
            by = (c.config or {}).get("coordination_entity") or "cecopi"
            kind = parsed.get("kind") or "other"
            extras = {k: parsed[k] for k in ("zone", "place", "severity", "resource", "qty", "units",
                                             "population", "entity", "verb") if parsed.get(k) not in (None, "")}
            if kind == "other":
                extras["severity"] = max(int(extras.get("severity") or 6), 6)
            try:
                out = reports.file_report(db, c, by=by, kind=kind, text=text, **extras)
            except reports.BadReport as e:
                raise HTTPException(status_code=422, detail=str(e))
        if out["kind"] == "zone_new":
            background.add_task(geo.locate_zones, crisis_id)
        return {"injected": "situation", **out}
    with crisis_tx(crisis_id) as (db, c):
        if body.kind == "signal":
            raw = submit_raw_input(db, c, channel=body.channel, source=body.source or {"call": "112", "social": "social-media", "news": "local-news"}.get(body.channel, "operador"),
                                   payload={"transcript": body.content, "text": body.content, "body": body.content,
                                            "headline": body.note, "caller": "inyectado", "author": "@inyectado",
                                            "outlet": body.source or "", "zone": body.zone, "severity": body.severity or 0})
            return {"injected": "signal", "id": raw.id}
        apply_world_op(db, c, {"op": body.kind, **body.model_dump(exclude={"kind", "channel", "content"}, exclude_none=True)})
        return {"injected": body.kind}


# ── live stream ──────────────────────────────────────────────────────────


@router.get("/crises/{crisis_id}/events/history")
def events_history(crisis_id: str, after: int = 0, limit: int = 200, material: bool | None = None) -> list[dict[str, Any]]:
    with crisis_tx(crisis_id) as (db, c):
        q = select(Event).where(Event.crisis_id == c.id, Event.seq > after)
        if material is not None:
            q = q.where(Event.material.is_(material))
        return [event_dict(e) for e in db.scalars(q.order_by(Event.seq).limit(min(limit, 1000)))]


@router.get("/crises/{crisis_id}/events")
async def events_stream(crisis_id: str, request: Request, after: int | None = None) -> StreamingResponse:
    last_id = request.headers.get("last-event-id")
    start = after if after is not None else (int(last_id) if last_id and last_id.isdigit() else None)

    def backlog() -> list[dict[str, Any]]:
        if start is None:
            return []
        with session_scope() as db:
            return [event_dict(e) for e in db.scalars(select(Event).where(Event.crisis_id == crisis_id, Event.seq > start)
                                                      .order_by(Event.seq).limit(500))]

    async def gen():
        q = bus.subscribe(crisis_id)
        try:
            yield ": connected\n\n"
            for ev in await asyncio.to_thread(backlog):
                yield _sse(ev)
            while True:
                if await request.is_disconnected():
                    break
                try:
                    ev = await asyncio.wait_for(q.get(), timeout=15)
                    yield _sse(ev)
                except asyncio.TimeoutError:
                    yield ": keep-alive\n\n"
        finally:
            bus.unsubscribe(crisis_id, q)

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


def _sse(ev: dict[str, Any]) -> str:
    head = f"id: {ev['seq']}\n" if ev.get("seq") is not None else ""
    return f"{head}event: {ev['type']}\ndata: {json.dumps(ev, ensure_ascii=False)}\n\n"
