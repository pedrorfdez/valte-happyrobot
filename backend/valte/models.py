"""World state tables.

Shapes follow the v1 JSON schemas (signal, action, entity, zone) because
the dashboard components consume exactly those. Everything nested is a
portable JSON column so the move from SQLite to Supabase/Postgres is a
URL change.
"""

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import JSON, Boolean, DateTime, Float, Integer, String, Text
from sqlalchemy.types import TypeDecorator
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from valte.db import Base

Json = JSON().with_variant(JSONB(), "postgresql")


class UtcDateTime(TypeDecorator):
    """Always aware UTC in Python. SQLite drops tzinfo on the way back, and
    mixing naive and aware datetimes is the classic way to crash a clock."""

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Crisis(Base):
    __tablename__ = "crises"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    code: Mapped[str] = mapped_column(String, index=True)
    name: Mapped[str] = mapped_column(String)
    hazard_type: Mapped[str] = mapped_column(String, default="other")
    region: Mapped[str] = mapped_column(String, default="")
    status: Mapped[str] = mapped_column(String, default="active", index=True)  # active|contained|closed
    pack_id: Mapped[str | None] = mapped_column(String, nullable=True)
    source: Mapped[str] = mapped_column(String, default="wizard")  # wizard|voice|pack

    # Scenario clock: now = anchor_scenario + (wall - anchor_wall) * speed.
    t0_scenario: Mapped[datetime] = mapped_column(UtcDateTime())
    anchor_wall: Mapped[datetime] = mapped_column(UtcDateTime(), default=utcnow)
    anchor_scenario: Mapped[datetime] = mapped_column(UtcDateTime())
    speed: Mapped[float] = mapped_column(Float, default=20.0)
    paused: Mapped[bool] = mapped_column(Boolean, default=True)
    slowmo: Mapped[bool] = mapped_column(Boolean, default=False)
    sim_cursor_min: Mapped[float] = mapped_column(Float, default=-1.0)

    state_version: Mapped[int] = mapped_column(Integer, default=0)
    plan_version: Mapped[int] = mapped_column(Integer, default=0)
    emergency_level: Mapped[int] = mapped_column(Integer, default=0)
    severity: Mapped[int] = mapped_column(Integer, default=0)
    trend: Mapped[str] = mapped_column(String, default="stable")
    situation_note: Mapped[str] = mapped_column(Text, default="")
    config: Mapped[dict[str, Any]] = mapped_column(Json, default=dict)  # approval_verbs, doctrine, ...
    counters: Mapped[dict[str, Any]] = mapped_column(Json, default=dict)  # next ids
    wake: Mapped[dict[str, Any]] = mapped_column(Json, default=dict)  # engine bookkeeping
    transcript: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(UtcDateTime(), default=utcnow)
    started_at: Mapped[datetime | None] = mapped_column(UtcDateTime(), nullable=True)
    closed_at: Mapped[datetime | None] = mapped_column(UtcDateTime(), nullable=True)


class Zone(Base):
    __tablename__ = "zones"

    crisis_id: Mapped[str] = mapped_column(String, primary_key=True)
    id: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str] = mapped_column(String)
    population: Mapped[int] = mapped_column(Integer, default=0)
    is_origin: Mapped[bool] = mapped_column(Boolean, default=False)
    elevation: Mapped[str] = mapped_column(String, default="medium")
    notes: Mapped[str] = mapped_column(Text, default="")
    # [{"to": zone_id, "delay_min": int}]
    downstream: Mapped[list[dict[str, Any]]] = mapped_column(Json, default=list)
    sort_index: Mapped[int] = mapped_column(Integer, default=0)

    severity_est: Mapped[int] = mapped_column(Integer, default=0)
    trend: Mapped[str] = mapped_column(String, default="stable")
    crossed_at: Mapped[datetime | None] = mapped_column(UtcDateTime(), nullable=True)
    eta_min: Mapped[int | None] = mapped_column(Integer, nullable=True)
    warned: Mapped[bool] = mapped_column(Boolean, default=False)
    warned_at: Mapped[datetime | None] = mapped_column(UtcDateTime(), nullable=True)
    evacuating: Mapped[bool] = mapped_column(Boolean, default=False)
    evacuated_pct: Mapped[float] = mapped_column(Float, default=0.0)
    base_at_risk_pct: Mapped[float] = mapped_column(Float, default=20.0)
    at_risk_pct: Mapped[float] = mapped_column(Float, default=0.0)
    road_closed: Mapped[bool] = mapped_column(Boolean, default=False)
    extra: Mapped[dict[str, Any]] = mapped_column(Json, default=dict)


class Entity(Base):
    __tablename__ = "entities"

    crisis_id: Mapped[str] = mapped_column(String, primary_key=True)
    id: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str] = mapped_column(String)
    kind: Mapped[str] = mapped_column(String)  # information_source|authority|responder|population
    role: Mapped[str] = mapped_column(String, default="")  # coordination|authority|responder
    weight: Mapped[int] = mapped_column(Integer, default=5)
    trust: Mapped[str] = mapped_column(String, default="medium")
    jurisdiction: Mapped[list[str]] = mapped_column(Json, default=list)
    channel: Mapped[dict[str, Any]] = mapped_column(Json, default=dict)  # {kind, address}
    capabilities: Mapped[list[str]] = mapped_column(Json, default=list)
    units_total: Mapped[int | None] = mapped_column(Integer, nullable=True)
    units_available: Mapped[int | None] = mapped_column(Integer, nullable=True)
    deployed: Mapped[dict[str, Any]] = mapped_column(Json, default=dict)  # zone -> units
    activation: Mapped[dict[str, Any]] = mapped_column(Json, default=dict)  # {delay_min, cost}
    escalation_to: Mapped[str | None] = mapped_column(String, nullable=True)
    zone: Mapped[str | None] = mapped_column(String, nullable=True)
    status: Mapped[str] = mapped_column(String, default="available")
    provenance: Mapped[str] = mapped_column(String, default="plan")
    notes: Mapped[str] = mapped_column(Text, default="")
    extra: Mapped[dict[str, Any]] = mapped_column(Json, default=dict)  # link, description, modality...


class Resource(Base):
    __tablename__ = "resources"

    crisis_id: Mapped[str] = mapped_column(String, primary_key=True)
    id: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str] = mapped_column(String)
    unit: Mapped[str] = mapped_column(String, default="")
    description: Mapped[str] = mapped_column(Text, default="")
    total: Mapped[float] = mapped_column(Float, default=0)
    available: Mapped[float] = mapped_column(Float, default=0)
    owner_entity_id: Mapped[str | None] = mapped_column(String, nullable=True)
    sort_index: Mapped[int] = mapped_column(Integer, default=0)


class RawInput(Base):
    """What a data source emitted, before perception."""

    __tablename__ = "raw_inputs"

    crisis_id: Mapped[str] = mapped_column(String, primary_key=True)
    id: Mapped[str] = mapped_column(String, primary_key=True)  # becomes the signal id
    t: Mapped[datetime] = mapped_column(UtcDateTime())
    channel: Mapped[str] = mapped_column(String)  # call|social|news|sensor|operator|other
    source: Mapped[str] = mapped_column(String)
    payload: Mapped[dict[str, Any]] = mapped_column(Json, default=dict)
    fallback: Mapped[dict[str, Any] | None] = mapped_column(Json, nullable=True)
    state: Mapped[str] = mapped_column(String, default="queued")  # queued|sent|perceived|fallback|failed
    hr_run_id: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime(), default=utcnow)


class Signal(Base):
    __tablename__ = "signals"

    crisis_id: Mapped[str] = mapped_column(String, primary_key=True)
    id: Mapped[str] = mapped_column(String, primary_key=True)
    seq: Mapped[int] = mapped_column(Integer, default=0, index=True)
    t: Mapped[datetime] = mapped_column(UtcDateTime(), index=True)
    source: Mapped[str] = mapped_column(String, index=True)
    source_trust: Mapped[str] = mapped_column(String, default="medium")
    channel: Mapped[str] = mapped_column(String, default="other")
    modality: Mapped[str] = mapped_column(String, default="text")
    content: Mapped[str] = mapped_column(Text, default="")
    summary: Mapped[str] = mapped_column(Text, default="")
    claims: Mapped[list[dict[str, Any]]] = mapped_column(Json, default=list)
    location: Mapped[dict[str, Any]] = mapped_column(Json, default=dict)
    zone_id: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    severity_hint: Mapped[int] = mapped_column(Integer, default=0)
    confidence: Mapped[str | None] = mapped_column(String, nullable=True)
    confidence_inputs: Mapped[dict[str, Any]] = mapped_column(Json, default=dict)
    is_noise: Mapped[bool] = mapped_column(Boolean, default=False)
    revision: Mapped[int] = mapped_column(Integer, default=1)
    perceived_by: Mapped[str] = mapped_column(String, default="hr")  # hr|fallback|direct|operator
    hr_run_id: Mapped[str | None] = mapped_column(String, nullable=True)
    received_at: Mapped[datetime] = mapped_column(UtcDateTime(), default=utcnow)
    # The incident this report is evidence of (core/incidents.py). Noise belongs to none.
    incident_id: Mapped[str | None] = mapped_column(String, nullable=True, index=True)


class Action(Base):
    __tablename__ = "actions"

    crisis_id: Mapped[str] = mapped_column(String, primary_key=True)
    id: Mapped[str] = mapped_column(String, primary_key=True)
    seq: Mapped[int] = mapped_column(Integer, default=0, index=True)
    t: Mapped[datetime] = mapped_column(UtcDateTime())
    actor: Mapped[str] = mapped_column(String, index=True)
    verb: Mapped[str] = mapped_column(String)
    verb_label: Mapped[str] = mapped_column(String, default="")
    target_zones: Mapped[list[str]] = mapped_column(Json, default=list)
    params: Mapped[dict[str, Any]] = mapped_column(Json, default=dict)
    status: Mapped[str] = mapped_column(String, index=True)  # pending_approval|approved|executed|rejected|failed
    evidence: Mapped[list[str]] = mapped_column(Json, default=list)
    reasoning: Mapped[str] = mapped_column(Text, default="")
    real_interaction: Mapped[dict[str, Any] | None] = mapped_column(Json, nullable=True)

    origin: Mapped[str] = mapped_column(String, default="coordinator")  # coordinator|tripwire|human|system|local-brain|escalation
    dedup_key: Mapped[str] = mapped_column(String, default="", index=True)
    approval: Mapped[dict[str, Any]] = mapped_column(Json, default=dict)
    reserved: Mapped[dict[str, Any]] = mapped_column(Json, default=dict)
    plan_version: Mapped[int] = mapped_column(Integer, default=0)
    incident_id: Mapped[str | None] = mapped_column(String, nullable=True)
    escalated_from: Mapped[str | None] = mapped_column(String, nullable=True)
    lessons: Mapped[list[str]] = mapped_column(Json, default=list)  # "L-12": lessons this decision leaned on
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime(), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UtcDateTime(), default=utcnow)


class Tripwire(Base):
    __tablename__ = "tripwires"

    crisis_id: Mapped[str] = mapped_column(String, primary_key=True)
    id: Mapped[str] = mapped_column(String, primary_key=True)
    cond: Mapped[dict[str, Any]] = mapped_column("if_cond", Json, default=dict)
    then: Mapped[list[dict[str, Any]]] = mapped_column(Json, default=list)
    reason: Mapped[str] = mapped_column(Text, default="")
    set_by: Mapped[str] = mapped_column(String, default="system")
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    # A standing reflex: stays armed after firing (one-shot tripwires disarm themselves).
    repeat: Mapped[bool] = mapped_column(Boolean, default=False)
    last_fired_t: Mapped[datetime | None] = mapped_column(UtcDateTime(), nullable=True)
    created_t: Mapped[datetime | None] = mapped_column(UtcDateTime(), nullable=True)


class ScheduledCheck(Base):
    __tablename__ = "scheduled_checks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    crisis_id: Mapped[str] = mapped_column(String, index=True)
    due_t: Mapped[datetime] = mapped_column(UtcDateTime())
    note: Mapped[str] = mapped_column(Text, default="")
    done: Mapped[bool] = mapped_column(Boolean, default=False)


class Incident(Base):
    __tablename__ = "incidents"

    crisis_id: Mapped[str] = mapped_column(String, primary_key=True)
    id: Mapped[str] = mapped_column(String, primary_key=True)
    state: Mapped[str] = mapped_column(String, default="active")
    priority: Mapped[str] = mapped_column(String, default="P2")
    confidence: Mapped[str] = mapped_column(String, default="unknown")
    title: Mapped[str] = mapped_column(String, default="")
    summary: Mapped[str] = mapped_column(Text, default="")
    hazard_types: Mapped[list[str]] = mapped_column(Json, default=list)
    zone_ids: Mapped[list[str]] = mapped_column(Json, default=list)
    evidence: Mapped[list[Any]] = mapped_column(Json, default=list)
    revisit_at: Mapped[datetime | None] = mapped_column(UtcDateTime(), nullable=True)
    plan_version: Mapped[int] = mapped_column(Integer, default=0)
    updated_at: Mapped[datetime] = mapped_column(UtcDateTime(), default=utcnow)
    # kernel = formed from signals by core/incidents.py (state: candidate|active|attended|resolved|dismissed|merged);
    # command = a strategic grouping written by crisis-command through replace_plan.
    origin: Mapped[str] = mapped_column(String, default="command")
    seq: Mapped[int] = mapped_column(Integer, default=0)
    kind: Mapped[str] = mapped_column(String, default="")
    zone_id: Mapped[str | None] = mapped_column(String, nullable=True)
    place: Mapped[str] = mapped_column(String, default="")
    severity: Mapped[int] = mapped_column(Integer, default=0)
    people: Mapped[int] = mapped_column(Integer, default=0)
    signal_ids: Mapped[list[str]] = mapped_column(Json, default=list)
    origins: Mapped[list[str]] = mapped_column(Json, default=list)   # independent sources: reposts count once
    channels: Mapped[list[str]] = mapped_column(Json, default=list)
    first_t: Mapped[datetime | None] = mapped_column(UtcDateTime(), nullable=True)
    last_t: Mapped[datetime | None] = mapped_column(UtcDateTime(), nullable=True)
    canonical_id: Mapped[str | None] = mapped_column(String, nullable=True)  # merged into
    closed_reason: Mapped[str] = mapped_column(Text, default="")
    note: Mapped[str] = mapped_column(Text, default="")  # what the strategist added


class Plan(Base):
    __tablename__ = "plans"

    crisis_id: Mapped[str] = mapped_column(String, primary_key=True)
    version: Mapped[int] = mapped_column(Integer, primary_key=True)
    t: Mapped[datetime] = mapped_column(UtcDateTime())
    summary: Mapped[str] = mapped_column(Text, default="")
    objectives: Mapped[list[dict[str, Any]]] = mapped_column(Json, default=list)
    material_fp: Mapped[str] = mapped_column(String, default="")
    material: Mapped[dict[str, Any]] = mapped_column(Json, default=dict)
    origin: Mapped[str] = mapped_column(String, default="command")
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    invalidated_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    lessons: Mapped[list[str]] = mapped_column(Json, default=list)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime(), default=utcnow)


class Contact(Base):
    """One real contact attempt with an entity (email or web voice call)."""

    __tablename__ = "contacts"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    crisis_id: Mapped[str] = mapped_column(String, index=True)
    seq: Mapped[int] = mapped_column(Integer, default=0)
    action_id: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    entity_id: Mapped[str] = mapped_column(String)
    entity_name: Mapped[str] = mapped_column(String, default="")
    channel: Mapped[str] = mapped_column(String)  # voice|email
    address: Mapped[str] = mapped_column(String, default="")
    purpose: Mapped[str] = mapped_column(String, default="order")  # approval|order|notify
    attempt: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[str] = mapped_column(String, default="queued", index=True)
    brief: Mapped[dict[str, Any]] = mapped_column(Json, default=dict)
    token: Mapped[str | None] = mapped_column(String, nullable=True, index=True)  # email approval link
    hr_run_id: Mapped[str | None] = mapped_column(String, nullable=True)
    hr_session_id: Mapped[str | None] = mapped_column(String, nullable=True)
    transcript: Mapped[list[dict[str, Any]]] = mapped_column(Json, default=list)
    outcome: Mapped[dict[str, Any] | None] = mapped_column(Json, nullable=True)
    t: Mapped[datetime] = mapped_column(UtcDateTime())
    ring_deadline_wall: Mapped[datetime | None] = mapped_column(UtcDateTime(), nullable=True)
    started_wall: Mapped[datetime | None] = mapped_column(UtcDateTime(), nullable=True)
    ended_wall: Mapped[datetime | None] = mapped_column(UtcDateTime(), nullable=True)
    duration_s: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime(), default=utcnow)


class Outcome(Base):
    __tablename__ = "outcomes"

    crisis_id: Mapped[str] = mapped_column(String, primary_key=True)
    id: Mapped[str] = mapped_column(String, primary_key=True)
    action_id: Mapped[str | None] = mapped_column(String, nullable=True)
    attempt_id: Mapped[str | None] = mapped_column(String, nullable=True)
    status: Mapped[str] = mapped_column(String, default="unknown")
    summary: Mapped[str] = mapped_column(Text, default="")
    observed_effects: Mapped[list[Any]] = mapped_column(Json, default=list)
    evidence: Mapped[list[Any]] = mapped_column(Json, default=list)
    t: Mapped[datetime] = mapped_column(UtcDateTime())


class Event(Base):
    __tablename__ = "events"

    seq: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    crisis_id: Mapped[str] = mapped_column(String, index=True)
    t: Mapped[datetime] = mapped_column(UtcDateTime())
    wall: Mapped[datetime] = mapped_column(UtcDateTime(), default=utcnow)
    type: Mapped[str] = mapped_column(String, index=True)
    payload: Mapped[dict[str, Any]] = mapped_column(Json, default=dict)
    # Material events are what wakes the coordinator and fills its digest.
    material: Mapped[bool] = mapped_column(Boolean, default=False)
    digest: Mapped[str | None] = mapped_column(Text, nullable=True)


class Command(Base):
    """Gateway command log: command_id is the idempotency key."""

    __tablename__ = "commands"

    command_id: Mapped[str] = mapped_column(String, primary_key=True)
    crisis_id: Mapped[str] = mapped_column(String, index=True)
    command_type: Mapped[str] = mapped_column(String)
    accepted: Mapped[bool] = mapped_column(Boolean, default=True)
    result: Mapped[dict[str, Any]] = mapped_column(Json, default=dict)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime(), default=utcnow)


class Outbox(Base):
    """Side effects the sync core wants; the async engine performs them."""

    __tablename__ = "outbox"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    crisis_id: Mapped[str] = mapped_column(String, index=True)
    kind: Mapped[str] = mapped_column(String)  # hr_run
    workflow: Mapped[str] = mapped_column(String, default="")
    purpose: Mapped[str] = mapped_column(String, default="")  # ingest|coordinator|command|intake|outcome|outreach
    ref_id: Mapped[str | None] = mapped_column(String, nullable=True)
    payload: Mapped[dict[str, Any]] = mapped_column(Json, default=dict)
    status: Mapped[str] = mapped_column(String, default="pending", index=True)  # pending|sent|failed|skipped
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime(), default=utcnow)


class HrWorkflow(Base):
    __tablename__ = "hr_workflows"

    name: Mapped[str] = mapped_column(String, primary_key=True)
    workflow_id: Mapped[str] = mapped_column(String)
    version_id: Mapped[str] = mapped_column(String, default="")
    slug: Mapped[str] = mapped_column(String, default="")
    spec_hash: Mapped[str] = mapped_column(String, default="")
    node_ids: Mapped[dict[str, Any]] = mapped_column(Json, default=dict)  # node name -> persistent id
    updated_at: Mapped[datetime] = mapped_column(UtcDateTime(), default=utcnow)


class HrRun(Base):
    __tablename__ = "hr_runs"

    run_id: Mapped[str] = mapped_column(String, primary_key=True)
    crisis_id: Mapped[str] = mapped_column(String, index=True)
    workflow: Mapped[str] = mapped_column(String)
    purpose: Mapped[str] = mapped_column(String)
    ref_id: Mapped[str | None] = mapped_column(String, nullable=True)
    status: Mapped[str] = mapped_column(String, default="running", index=True)  # running|done|reconciled|fallback|failed
    result: Mapped[dict[str, Any] | None] = mapped_column(Json, nullable=True)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime(), default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(UtcDateTime(), nullable=True)


class HrCallback(Base):
    """Raw log of everything HappyRobot sends us (types arrive loose)."""

    __tablename__ = "hr_callbacks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    path: Mapped[str] = mapped_column(String)
    body: Mapped[Any] = mapped_column(Json, nullable=True)
    status_code: Mapped[int] = mapped_column(Integer, default=200)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime(), default=utcnow)


class Report(Base):
    """An incident told to the system by one of its own actors (a town hall, a fire brigade): trusted, located,
    and with consequences applied at once."""

    __tablename__ = "reports"

    crisis_id: Mapped[str] = mapped_column(String, primary_key=True)
    id: Mapped[str] = mapped_column(String, primary_key=True)
    t: Mapped[datetime] = mapped_column(UtcDateTime())
    by: Mapped[str] = mapped_column(String, index=True)
    kind: Mapped[str] = mapped_column(String)
    zone_id: Mapped[str | None] = mapped_column(String, nullable=True)
    place: Mapped[str] = mapped_column(String, default="")
    text: Mapped[str] = mapped_column(Text, default="")
    severity: Mapped[int] = mapped_column(Integer, default=5)
    signal_id: Mapped[str | None] = mapped_column(String, nullable=True)
    effects: Mapped[list[str]] = mapped_column(Json, default=list)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime(), default=utcnow)


class Lesson(Base):
    __tablename__ = "lessons"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    hazard_type: Mapped[str] = mapped_column(String, index=True)
    pack_id: Mapped[str | None] = mapped_column(String, nullable=True)
    kind: Mapped[str] = mapped_column(String)  # source_reliability|entity_response|approval_latency|warning_lead|failure
    subject: Mapped[str] = mapped_column(String, default="")
    text: Mapped[str] = mapped_column(Text)
    stats: Mapped[dict[str, Any]] = mapped_column(Json, default=dict)
    source_crisis_id: Mapped[str] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime(), default=utcnow)
    # crisis = learned while this crisis runs and applied to it at once; global = carried to the next crises of its kind.
    scope: Mapped[str] = mapped_column(String, default="global", index=True)
    key: Mapped[str] = mapped_column(String, default="", index=True)  # kind:subject — one lesson per thing learned
    # What proves it: ids of this crisis's actions, contacts, incidents or signals. A lesson without evidence is an opinion.
    evidence: Mapped[list[str]] = mapped_column(Json, default=list)
    # What the kernel itself does about it (route_around | avoid | trust | lead_time | reserve), if anything.
    rule: Mapped[dict[str, Any]] = mapped_column(Json, default=dict)
    weight: Mapped[int] = mapped_column(Integer, default=1)  # crises (or observations) that back it; 0 = retired
    status: Mapped[str] = mapped_column(String, default="active")
    origin: Mapped[str] = mapped_column(String, default="kernel")  # kernel | review (LLM post-mortem) | human
    applied: Mapped[int] = mapped_column(Integer, default=0)
    updated_at: Mapped[datetime] = mapped_column(UtcDateTime(), default=utcnow)


class LessonUse(Base):
    """Which decision leaned on which lesson: the trace that says the system really learned."""

    __tablename__ = "lesson_uses"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    lesson_id: Mapped[int] = mapped_column(Integer, index=True)
    crisis_id: Mapped[str] = mapped_column(String, index=True)
    t: Mapped[datetime] = mapped_column(UtcDateTime())
    by: Mapped[str] = mapped_column(String, default="kernel")  # kernel | coordinator | proactive | command | local-brain
    ref: Mapped[str] = mapped_column(String, default="")       # the action, plan or entity it shaped
    note: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(UtcDateTime(), default=utcnow)


class Manual(Base):
    __tablename__ = "manuals"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    crisis_id: Mapped[str] = mapped_column(String, index=True)
    title: Mapped[str] = mapped_column(String)
    url: Mapped[str] = mapped_column(String)
    published_date: Mapped[str | None] = mapped_column(String, nullable=True)
    highlights: Mapped[list[str]] = mapped_column(Json, default=list)
