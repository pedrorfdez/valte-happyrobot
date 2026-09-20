"""Raw inputs from the outside world, before anyone has understood them."""

from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from valte.core.events import append_event
from valte.core.playbook import perception_context
from valte.core.signals import ingest_perception, raw_text, upsert_signal
from valte.core.world import next_id, scenario_now, zone_catalog_text
from valte.hr import registry
from valte.models import Crisis, Outbox, RawInput
from valte.settings import public_base_url


def submit_raw_input(db: Session, c: Crisis, *, channel: str, source: str, payload: dict[str, Any],
                     fallback: dict[str, Any] | None = None, t: datetime | None = None) -> RawInput:
    """Hand one raw input to the perception layer in HappyRobot. The
    channel picks the workflow; anything unusual goes to crisis-intake."""
    t = t or scenario_now(c)
    raw = RawInput(crisis_id=c.id, id=next_id(c, "sig"), t=t, channel=channel, source=source,
                   payload=payload, fallback=fallback)
    db.add(raw)
    db.flush()
    append_event(db, c, "raw_input.received", {"id": raw.id, "channel": channel, "source": source})

    workflow = registry.INGEST.get(channel, registry.INTAKE)
    if not registry.usable(db, workflow):
        apply_fallback(db, c, raw, reason="HappyRobot no disponible")
        return raw

    base = {"crisis_id": c.id, "callback_base": public_base_url(), "id": raw.id, "t": t.isoformat(),
            "channel": channel, "source": source,
            "hazard_context": perception_context(c),
            "zone_catalog": zone_catalog_text(db, c.id)}
    if workflow == registry.INTAKE:
        body = {"dispatch_id": raw.id, "run_id": c.id, "callback_base": base["callback_base"],
                "environment": base["hazard_context"], "event": {**base, "source_input": payload}}
    else:
        body = {**base, **payload}
    db.add(Outbox(crisis_id=c.id, kind="hr_run", workflow=workflow,
                  purpose="intake" if workflow == registry.INTAKE else "ingest", ref_id=raw.id, payload=body))
    return raw


def apply_fallback(db: Session, c: Crisis, raw: RawInput, *, reason: str) -> None:
    """Scripted perception, clearly labelled, so an outage never stalls the run."""
    content = raw_text(raw)
    if raw.fallback:
        ingest_perception(db, c, {**raw.fallback, "id": raw.id, "t": raw.t.isoformat(), "channel": raw.channel,
                                  "source": raw.source, "content": content}, perceived_by="fallback")
    else:
        sev = int((raw.payload or {}).get("severity", 0) or 0)
        upsert_signal(db, c, sig_id=raw.id, t=raw.t, source=raw.source, channel=raw.channel, content=content,
                      is_noise=False, claims=[{"hazard_type": c.hazard_type, "severity_hint": sev}],
                      zone=(raw.payload or {}).get("zone"), precision="zone" if (raw.payload or {}).get("zone") else "unknown",
                      perceived_by="operator" if raw.channel == "operator" else "fallback")
    append_event(db, c, "hr.fallback", {"ref": raw.id, "reason": reason})
