"""Gateway contract: a small command bus over the same world.

Envelope: {command_id, run_id, command_type, expected_plan_version?,
actor, causation_id?, payload | payload_json}. command_id makes every
command idempotent; only replace_plan is subject to optimistic
concurrency, and against plan_version (state_version moves with every
signal and would reject every plan)."""

from typing import Any

from sqlalchemy.orm import Session

from valte.core import actions, plan
from valte.core.events import append_event
from valte.core.signals import _norm_claims, loose_bool, loose_json, upsert_signal
from valte.core.world import scenario_now
from valte.models import Action, Command, Contact, Crisis, Outcome, RawInput


class BadCommand(ValueError):
    pass


def apply_command(db: Session, c: Crisis, cmd: dict[str, Any], *, hr_run_id: str | None = None) -> dict[str, Any]:
    command_id = str(cmd.get("command_id") or "")
    ctype = str(cmd.get("command_type") or "")
    if not command_id or not ctype:
        raise BadCommand("command_id and command_type are required")
    prior = db.get(Command, command_id)
    if prior is not None:
        return {**(prior.result or {}), "duplicate": True}

    if ctype not in ("upsert_signal", "replace_plan", "record_outcome"):
        raise BadCommand(f"unknown command_type '{ctype}'")
    payload = loose_json(cmd.get("payload"), None)
    if not isinstance(payload, dict):
        payload = loose_json(cmd.get("payload_json"), None)
    if not isinstance(payload, dict):
        raise BadCommand("payload (object) or payload_json (JSON string) is required")

    if ctype == "upsert_signal":
        result = _upsert_signal(db, c, payload, hr_run_id)
    elif ctype == "replace_plan":
        expected = str(cmd.get("expected_plan_version", "")).strip()
        expected = int(expected) if expected.lstrip("-").isdigit() else None  # "0" is a version too
        p = plan.replace_plan(db, c, payload, expected_plan_version=expected, origin="command")
        result = {"plan_version": p.version}
    else:
        result = _record_outcome(db, c, payload.get("outcome") or payload)

    result = {"accepted": True, "command_id": command_id, "state_version": c.state_version,
              "plan_version": c.plan_version, **result}
    db.add(Command(command_id=command_id, crisis_id=c.id, command_type=ctype, accepted=True, result=result))
    return result


def _upsert_signal(db: Session, c: Crisis, payload: dict[str, Any], hr_run_id: str | None) -> dict[str, Any]:
    s = payload.get("signal") or payload
    sig_id = str(s.get("signal_id") or s.get("id") or "") or None
    raw = db.get(RawInput, (c.id, sig_id)) if sig_id else None
    loc = s.get("location") or {}
    content = s.get("content") or (" ".join(str(v) for v in (raw.payload or {}).values()) if raw else "")
    sig, created = upsert_signal(
        db, c, sig_id=sig_id, t=raw.t if raw else scenario_now(c),
        source=str(s.get("source") or (raw.source if raw else "unknown")),
        channel=str(s.get("channel") or (raw.channel if raw else "other")), content=str(content),
        is_noise=loose_bool(s.get("is_noise")), claims=_norm_claims(s.get("claims")),
        zone=loc.get("zone_id") or loc.get("zone") or s.get("zone"),
        precision=str(loc.get("precision") or s.get("precision") or "unknown"),
        location_text=str(loc.get("text") or s.get("location_text") or ""), summary=str(s.get("summary") or ""),
        perceived_by="hr", hr_run_id=hr_run_id, modality=s.get("modality"))
    return {"signal_id": sig.id, "created": created, "confidence": sig.confidence, "noise": sig.is_noise}


def _record_outcome(db: Session, c: Crisis, o: dict[str, Any]) -> dict[str, Any]:
    oid = str(o.get("outcome_id") or f"outcome:{o.get('attempt_id') or o.get('action_id')}")
    row = db.get(Outcome, (c.id, oid)) or Outcome(crisis_id=c.id, id=oid, t=scenario_now(c))
    row.action_id, row.attempt_id = o.get("action_id"), o.get("attempt_id")
    row.status = str(o.get("status") or "unknown")
    row.summary = str(o.get("summary") or "")
    row.observed_effects = loose_json(o.get("observed_effects"), []) or []
    row.evidence = loose_json(o.get("evidence"), []) or []
    db.merge(row)

    decision = str(o.get("decision") or "").lower()
    contact = db.get(Contact, str(o.get("attempt_id") or ""))
    if contact is not None:
        contact.outcome = {**(contact.outcome or {}), "summary": row.summary, "hr_decision": decision or None}
    act = db.get(Action, (c.id, str(o.get("action_id") or "")))
    applied = None
    if act is not None and act.status == "pending_approval" and contact is not None and contact.purpose == "approval":
        if decision in ("approved", "approve"):
            actions.approve_action(db, c, act, by=contact.entity_id, via=f"{contact.channel}+happyrobot", note=row.summary)
            applied = "approved"
        elif decision in ("rejected", "reject"):
            actions.reject_action(db, c, act, by=contact.entity_id, via=f"{contact.channel}+happyrobot", reason=row.summary)
            applied = "rejected"
    append_event(db, c, "outcome.recorded", {"outcome_id": oid, "action_id": row.action_id, "status": row.status,
                                            "summary": row.summary, "applied": applied})
    return {"outcome_id": oid, "applied": applied}
