from typing import Any

from sqlalchemy.orm import Session

from valte.models import Crisis, Event, utcnow


def append_event(
    db: Session,
    crisis: Crisis,
    type: str,
    payload: dict[str, Any] | None = None,
    *,
    material: bool = False,
    digest: str | None = None,
) -> Event:
    """Record something that happened. Material events wake the coordinator
    and `digest` is the line it reads about them."""
    from valte.core.world import scenario_now

    crisis.state_version = (crisis.state_version or 0) + 1
    ev = Event(
        crisis_id=crisis.id,
        t=scenario_now(crisis),
        wall=utcnow(),
        type=type,
        payload=payload or {},
        material=material,
        digest=digest,
    )
    db.add(ev)
    db.flush()
    db.info.setdefault("pending_events", []).append(event_dict(ev))
    return ev


def event_dict(ev: Event) -> dict[str, Any]:
    return {
        "seq": ev.seq,
        "crisis_id": ev.crisis_id,
        "type": ev.type,
        "t": ev.t.isoformat(),
        "wall": ev.wall.isoformat(),
        "material": ev.material,
        "digest": ev.digest,
        "payload": ev.payload,
    }
