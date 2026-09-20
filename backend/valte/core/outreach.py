"""Real contacts with the people who have to act or sign.

Two channels work in this org today: email (HappyRobot "Send email") and
browser voice calls (LiveKit tokens). A contact that nobody answers is
not a dead end: it escalates, and the brain hears about it.
"""

import re
import uuid
from datetime import timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from valte.core.events import append_event
from valte.core.world import contact_dict, hhmm, scenario_now, set_clock
from valte.models import Action, Contact, Crisis, Entity, Outbox, Signal, Zone, utcnow
from valte.settings import public_base_url, settings

OPEN = ("queued", "sending", "ringing", "in_progress")
YES = r"\b(s[ií]|apruebo|aprobad[oa]|aprobamos|autorizo|autorizad[oa]|adelante|de acuerdo|proced[ae]|hazlo|h[aá]galo|conforme|recibido|entendido|vamos)\b"
NO = r"\b(no|rechazo|rechazad[oa]|deniego|denegad[oa]|todav[ií]a no|espera|esperad|negativo)\b"


def dry_run() -> bool:
    return settings.valte_outreach_mode != "real"


def set_status(db: Session, c: Crisis, k: Contact, status: str, *, outcome: dict[str, Any] | None = None,
               error: str | None = None) -> None:
    k.status = status
    if outcome is not None:
        k.outcome = {**(k.outcome or {}), **outcome}
    if error:
        k.error = error
    if status not in OPEN and k.ended_wall is None:
        k.ended_wall = utcnow()
        if k.started_wall:
            k.duration_s = int((k.ended_wall - k.started_wall).total_seconds())
    append_event(db, c, "contact.updated", contact_dict(k))
    _sync_slowmo(db, c)
    if k.channel == "voice" and status not in OPEN:
        _ring_next(db, c, k.entity_id)


def _line_busy(db: Session, c: Crisis, entity_id: str, but: str | None = None) -> bool:
    """A person answers one call at a time."""
    return any(x.id != but for x in db.scalars(select(Contact).where(
        Contact.crisis_id == c.id, Contact.entity_id == entity_id, Contact.channel == "voice",
        Contact.status.in_(("ringing", "in_progress")))))


def _ring(db: Session, c: Crisis, k: Contact, entity: Entity | None) -> None:
    gone = bool(entity is not None and (entity.extra or {}).get("sim_unreachable"))
    k.status = "ringing"
    k.started_wall = utcnow() if gone else k.started_wall
    k.ring_deadline_wall = utcnow() + timedelta(seconds=12 if gone else settings.valte_ring_timeout_s)
    append_event(db, c, "contact.updated", contact_dict(k))


def _ring_next(db: Session, c: Crisis, entity_id: str) -> None:
    """The line is free: ring the oldest call still waiting for this entity, if it still makes sense."""
    if _line_busy(db, c, entity_id):
        return
    for k in db.scalars(select(Contact).where(Contact.crisis_id == c.id, Contact.entity_id == entity_id,
                                              Contact.channel == "voice", Contact.status == "queued").order_by(Contact.seq)):
        act = db.get(Action, (c.id, k.action_id)) if k.action_id else None
        moot = act is not None and (act.status in ("rejected", "failed", "executed") or (
            k.purpose == "approval" and (act.status != "pending_approval" or (act.approval or {}).get("approver") != entity_id)))
        if moot:  # decided, escalated or withdrawn while it waited: do not bother the person with it
            k.status, k.ended_wall = "superseded", utcnow()
            k.outcome = {**(k.outcome or {}), "note": "ya no hacía falta cuando quedó libre la línea"}
            append_event(db, c, "contact.updated", contact_dict(k))
            continue
        _ring(db, c, k, db.get(Entity, (c.id, entity_id)))
        return


def _sync_slowmo(db: Session, c: Crisis) -> None:
    live = db.scalars(select(Contact).where(Contact.crisis_id == c.id, Contact.status == "in_progress")).first()
    if bool(live) != bool(c.slowmo):
        set_clock(db, c, slowmo=bool(live))


def build_brief(db: Session, c: Crisis, entity: Entity, act: Action, purpose: str) -> dict[str, Any]:
    zones = [z.name for z in (db.get(Zone, (c.id, zid)) for zid in act.target_zones) if z]
    evidence = []
    for sid in act.evidence[:4]:
        s = db.get(Signal, (c.id, sid))
        if s:
            evidence.append(f"{s.id} · {hhmm(c, s.t)} · {s.source}: {(s.summary or s.content)[:180]}")
    esc = db.get(Entity, (c.id, entity.escalation_to)) if entity.escalation_to else None
    ask = {
        "approval": f"Necesitamos su aprobación para: {act.verb_label} en {', '.join(zones) or 'la zona afectada'}.",
        "order": f"Orden para ejecutar ya: {act.verb_label} en {', '.join(zones) or 'la zona afectada'}.",
        "notify": f"Aviso: {act.verb_label} en {', '.join(zones) or 'la zona afectada'}.",
    }[purpose]
    return {
        "crisis": c.name, "crisis_code": c.code, "hazard": c.hazard_type, "clock": hhmm(c, scenario_now(c)), "entity": entity.name,
        "purpose": purpose, "action_id": act.id, "verb": act.verb, "verb_label": act.verb_label,
        "zones": zones, "params": act.params, "reasoning": act.reasoning, "evidence": evidence, "ask": ask,
        "escalates_to": esc.name if esc else None,
    }


def contactable(entity: Entity) -> bool:
    """The directory: entities we can reach. Every communication leaves through one of these."""
    return (entity.channel or {}).get("kind", "none") != "none" and entity.role != "coordination"


def message_brief(c: Crisis, entity: Entity, message: str, by: str) -> dict[str, Any]:
    """A communication a person starts from the directory, not tied to an agent action."""
    return {
        "crisis": c.name, "crisis_code": c.code, "hazard": c.hazard_type, "clock": hhmm(c, scenario_now(c)), "entity": entity.name,
        "purpose": "notify", "action_id": "", "verb": "", "verb_label": "Mensaje directo", "zones": [], "params": {},
        "reasoning": f"Mensaje enviado por {by or 'el operador'} desde el directorio de contactos.", "evidence": [],
        "ask": message, "escalates_to": None, "from": by or "operador",
    }


def queue_contact(db: Session, c: Crisis, *, entity: Entity, action: Action | None = None, purpose: str,
                  attempt: int = 1, message: str = "", by: str = "") -> Contact | None:
    if not contactable(entity):
        return None  # that is us, or a source with no way in: nobody to call
    kind = (entity.channel or {}).get("kind", "none")
    channel = "voice" if kind == "voice" else "email"  # no phone numbers in the org: SMS rides on email
    seq = int((c.counters or {}).get("contact_seq", 0)) + 1
    c.counters = {**(c.counters or {}), "contact_seq": seq}
    k = Contact(
        id=str(uuid.uuid4()), crisis_id=c.id, seq=seq, action_id=action.id if action else None, entity_id=entity.id,
        entity_name=entity.name, channel=channel, address=(entity.channel or {}).get("address", ""),
        purpose=purpose, attempt=attempt, status="queued",
        brief=build_brief(db, c, entity, action, purpose) if action else message_brief(c, entity, message, by),
        token=uuid.uuid4().hex, t=scenario_now(c),
    )
    db.add(k)
    db.flush()
    append_event(db, c, "contact.created", contact_dict(k))

    if dry_run():
        set_status(db, c, k, "delivered", outcome={"simulated": True})
        _on_delivered(db, c, k, real=False)
        return k

    # Ground truth the system cannot see: it only learns the entity is
    # unreachable by trying and getting no answer.
    if channel == "voice":
        if _line_busy(db, c, entity.id, but=k.id):
            return k  # stays queued: it rings when the call ahead of it ends
        _ring(db, c, k, entity)
        return k

    if (entity.extra or {}).get("sim_unreachable"):
        k.status = "sending"
        k.started_wall = utcnow()
        k.ring_deadline_wall = utcnow() + timedelta(seconds=12)
        append_event(db, c, "contact.updated", contact_dict(k))
        return k

    if not settings.demo_email_to:
        # No mailbox configured: nothing is sent, and the contact says so instead of pretending or failing the run.
        set_status(db, c, k, "delivered", outcome={"simulated": True, "note": "DEMO_EMAIL_TO sin configurar: email no enviado"})
        _on_delivered(db, c, k, real=False)
        return k
    base = public_base_url()
    db.add(Outbox(crisis_id=c.id, kind="hr_run", workflow="PedroD-outreach", purpose="outreach", ref_id=k.id, payload={
        "contact_id": k.id, "crisis_id": c.id, "callback_base": base, "to": settings.demo_email_to,
        "entity_name": entity.name, "purpose": purpose, "brief_json": k.brief,
        "environment": f"{c.hazard_type} crisis '{c.name}' ({c.code}). Write for THIS hazard, not a flood by default.",
        "approve_url": f"{base}/a/{k.token}?d=approve" if purpose == "approval" else "",
        "reject_url": f"{base}/a/{k.token}?d=reject" if purpose == "approval" else "",
    }))
    return k


# ── lifecycle ────────────────────────────────────────────────────────────


def mark_sending(db: Session, c: Crisis, k: Contact, hr_run_id: str) -> None:
    k.hr_run_id = hr_run_id
    k.started_wall = utcnow()
    set_status(db, c, k, "sending")


def email_result(db: Session, c: Crisis, k: Contact, *, ok: bool, subject: str = "", body: str = "",
                 error: str = "") -> None:
    if k.status not in ("queued", "sending"):
        return  # callback and reconciliation both reported it
    if ok:
        k.transcript = [{"who": "Agente", "text": f"{subject}\n\n{body}".strip()}]
        set_status(db, c, k, "delivered", outcome={"subject": subject})
        _on_delivered(db, c, k, real=True)
    else:
        set_status(db, c, k, "failed", error=error or "HappyRobot no pudo enviar el email")
        _on_unanswered(db, c, k, "fallo de envío")


def answer_contact(db: Session, c: Crisis, k: Contact, *, hr_run_id: str) -> None:
    k.hr_run_id = hr_run_id
    k.started_wall = utcnow()
    set_status(db, c, k, "in_progress")


def decide_from_transcript(lines: list[dict[str, Any]]) -> str:
    """Stand-in until PedroD-crisis-response-coordination reads the call:
    the last clear yes/no the human said wins."""
    decision = "unclear"
    for ln in lines:
        if ln.get("who") == "Agente":
            continue
        text = str(ln.get("text", "")).lower()
        if re.search(NO, text) and not re.search(r"\bno (hay|tengo) (problema|inconveniente)\b", text):
            decision = "rejected"
        elif re.search(YES, text):
            decision = "approved"
    return decision


def finish_call(db: Session, c: Crisis, k: Contact, lines: list[dict[str, Any]], *,
                decision: str | None = None, summary: str = "") -> None:
    if k.status not in ("in_progress", "ringing"):
        return
    k.transcript = lines
    spoke = any(ln.get("who") != "Agente" for ln in lines)
    if not spoke:
        set_status(db, c, k, "no_answer", outcome={"note": "nadie habló en la llamada"})
        _on_unanswered(db, c, k, "llamada sin respuesta")
        return
    decision = decision or decide_from_transcript(lines)
    set_status(db, c, k, "completed", outcome={"decision": decision, "summary": summary})
    _on_delivered(db, c, k, real=True, decision=decision)


def expire_rings(db: Session, c: Crisis) -> None:
    now = utcnow()
    for k in db.scalars(select(Contact).where(Contact.crisis_id == c.id, Contact.status.in_(("ringing", "sending")))):
        if k.ring_deadline_wall and now >= k.ring_deadline_wall:
            set_status(db, c, k, "no_answer", outcome={"note": "no descolgó"})
            _on_unanswered(db, c, k, "llamada sin respuesta")


def _real_interaction(k: Contact) -> dict[str, Any]:
    return {"kind": k.channel, "to": k.address, "contact_id": k.id, "hr_run_id": k.hr_run_id}


def _on_delivered(db: Session, c: Crisis, k: Contact, *, real: bool, decision: str | None = None) -> None:
    from valte.core import actions

    act = db.get(Action, (c.id, k.action_id)) if k.action_id else None
    if act is None:
        return
    if real:
        act.real_interaction = _real_interaction(k)
    if k.purpose == "approval":
        if decision == "approved":
            actions.approve_action(db, c, act, by=k.entity_id, via=k.channel)
        elif decision == "rejected":
            actions.reject_action(db, c, act, by=k.entity_id, via=k.channel, reason="rechazada en la llamada")
        return  # email: the signature comes later through its link
    if k.channel == "voice" and decision == "rejected":
        actions.fail_action(db, c, act, f"{k.entity_name} rechaza la orden en la llamada.", escalate=False)
        return
    actions.complete_action(db, c, act, real_interaction=_real_interaction(k) if real else None)


def _on_unanswered(db: Session, c: Crisis, k: Contact, why: str) -> None:
    from valte.core import actions

    ent = db.get(Entity, (c.id, k.entity_id))
    if ent is not None and ent.status != "unreachable" and k.channel == "voice":
        ent.status = "unreachable"
    append_event(db, c, "contact.unanswered", contact_dict(k), material=True,
                 digest=f"{k.entity_id} did not answer ({why}) about {k.action_id} [{k.purpose}].")
    act = db.get(Action, (c.id, k.action_id)) if k.action_id else None
    if act is None:
        return
    if k.purpose == "approval":
        if act.status == "pending_approval":  # do not wait for the deadline: move up now
            act.approval = {**(act.approval or {}), "deadline_wall": utcnow().isoformat(),
                            "deadline_t": scenario_now(c).isoformat()}
        return
    actions.fail_action(db, c, act, f"{k.entity_name}: {why}.")


def decide_by_link(db: Session, c: Crisis, k: Contact, decision: str) -> str:
    from valte.core import actions

    act = db.get(Action, (c.id, k.action_id)) if k.action_id else None
    if act is None or act.status != "pending_approval":
        return "already_decided"
    k.outcome = {**(k.outcome or {}), "decision": decision, "via": "email-link"}
    if decision == "approve":
        actions.approve_action(db, c, act, by=k.entity_id, via="email")
    else:
        actions.reject_action(db, c, act, by=k.entity_id, via="email", reason="rechazada desde el email")
    append_event(db, c, "contact.updated", contact_dict(k))
    return "ok"
