"""Reflexes the brain arms in advance: they fire without waiting for an
LLM round-trip. A silent gauge is an escalation, not an absence of news."""

from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from valte.core.events import append_event
from valte.core.world import scenario_now, tripwire_dict
from valte.models import Crisis, Entity, Signal, Tripwire, Zone


def _fire(db: Session, c: Crisis, tw: Tripwire, detail: str, evidence: list[str], sig: Signal | None = None) -> None:
    from valte.core.actions import propose_action
    from valte.core.needs import pick_responder

    tw.last_fired_t = scenario_now(c)
    if not tw.repeat:
        tw.active = False  # one shot: the brain re-arms it if it still wants it
    append_event(db, c, "tripwire.fired", {**tripwire_dict(tw), "detail": detail}, material=True,
                 digest=f"Tripwire {tw.id} FIRED: {detail}. Reason it was set: {tw.reason}")
    for then in tw.then or []:
        zones = then.get("target_zones") or []
        if zones in ("signal", ["signal"], ["$signal"]):  # act where the report comes from
            zones = [sig.zone_id] if sig is not None and sig.zone_id else []
        actor, params = then.get("actor"), dict(then.get("params") or {})
        if actor == "auto":  # whoever is nearest with units to spare
            best = pick_responder(db, c, then.get("verb"), zones[0] if zones else None, int(params.get("units", 1)))
            if best is None:
                append_event(db, c, "need.unserved", {"tripwire": tw.id, "signal": sig.id if sig else None, "zones": zones},
                             material=True, digest=f"NO FREE UNITS for {then.get('verb')} in {zones} "
                                                   f"(reflex {tw.id}, evidence {evidence}). Reassign or escalate.")
                continue
            actor = best.id
        propose_action(db, c, {
            "actor": actor, "verb": then.get("verb"), "target_zones": zones, "params": params,
            "evidence": evidence or [tw.id],
            "reasoning": f"Reflejo {tw.id}: {detail}. {tw.reason}",
        }, origin="tripwire")


def _matches(cond: dict, sig: Signal) -> bool:
    if cond.get("source") and cond["source"] != sig.source:
        return False
    if cond.get("zone") and cond["zone"] != sig.zone_id:
        return False
    if cond.get("not_channel") and cond["not_channel"] == sig.channel:
        return False
    if cond.get("precision_in") and (sig.location or {}).get("precision") not in cond["precision_in"]:
        return False
    rank = {"low": 0, "medium": 1, "high": 2}
    if cond.get("min_confidence") and rank.get(sig.confidence or "low", 0) < rank.get(cond["min_confidence"], 0):
        return False
    return sig.severity_hint >= int(cond.get("min_severity", 0))


def evaluate_on_signal(db: Session, c: Crisis, sig: Signal) -> list[str]:
    fired = []
    for tw in db.scalars(select(Tripwire).where(Tripwire.crisis_id == c.id, Tripwire.active.is_(True))):
        cond = tw.cond or {}
        if cond.get("type") == "silence" or not _matches(cond, sig):
            continue
        if tw.repeat and sig.revision > 1:
            continue  # a re-scored report is the same report: a standing reflex serves it once
        if tw.repeat and sig.incident_id:
            from valte.core import incidents
            from valte.models import Incident

            inc = db.get(Incident, (c.id, sig.incident_id))
            if inc is not None and incidents.covering_actions(db, inc):
                continue  # a second call about the same incident: somebody is already on it
        # Read verbatim by the human supervisor (it becomes the action's reasoning), hence Spanish and real names.
        src, zone = db.get(Entity, (c.id, sig.source)), db.get(Zone, (c.id, sig.zone_id or ""))
        _fire(db, c, tw, f"{src.name if src else sig.source} avisa de severidad {sig.severity_hint} en "
                         f"{zone.name if zone else 'zona sin ubicar'}"
                         + (f" ({(sig.location or {}).get('text')})" if (sig.location or {}).get("text") else ""),
              [sig.id], sig)
        fired.append(tw.id)
    return fired


def evaluate_silence(db: Session, c: Crisis, now_s: datetime) -> list[str]:
    fired = []
    for tw in db.scalars(select(Tripwire).where(Tripwire.crisis_id == c.id, Tripwire.active.is_(True))):
        cond = tw.cond or {}
        if cond.get("type") != "silence" or not cond.get("source"):
            continue
        last = db.scalars(select(Signal).where(Signal.crisis_id == c.id, Signal.source == cond["source"])
                          .order_by(Signal.t.desc())).first()
        if last is None:
            continue  # never spoke: nothing to miss yet
        quiet = now_s - last.t
        if quiet >= timedelta(minutes=int(cond.get("silence_min", 20))):
            src = db.get(Entity, (c.id, cond["source"]))
            _fire(db, c, tw, f"{src.name if src else cond['source']} lleva {int(quiet.total_seconds() // 60)} min en silencio "
                             f"(última lectura: severidad {last.severity_hint})", [last.id])
            fired.append(tw.id)
    return fired
