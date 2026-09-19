"""Bonus requirement: look back at a finished run and change how the next
one starts. Lessons are plain sentences (the brains read them in `state`)
backed by stats (the kernel applies them to priors when a crisis opens)."""

from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from valte.core.events import append_event
from valte.models import Action, Contact, Crisis, Entity, Lesson, Signal, Zone, utcnow


def close_crisis(db: Session, c: Crisis) -> list[Lesson]:
    if c.status == "closed":
        return []
    lessons: list[Lesson] = []

    def add(kind: str, subject: str, text: str, stats: dict[str, Any]) -> None:
        l = Lesson(hazard_type=c.hazard_type, pack_id=c.pack_id, kind=kind, subject=subject, text=text,
                   stats=stats, source_crisis_id=c.id)
        db.add(l)
        lessons.append(l)

    signals = list(db.scalars(select(Signal).where(Signal.crisis_id == c.id)))
    ents = {e.id: e for e in db.scalars(select(Entity).where(Entity.crisis_id == c.id))}
    for src in {s.source for s in signals}:
        mine = [s for s in signals if s.source == src]
        if len(mine) < 4:
            continue
        noise = sum(1 for s in mine if s.is_noise) / len(mine)
        confirmed = sum(1 for s in mine if s.confidence == "high") / len(mine)
        prior = ents[src].trust if src in ents else "low"
        if noise >= 0.5 and prior != "low":
            add("source_reliability", src, f"La fuente {src} fue ruido en un {noise:.0%} la última vez: trata sus avisos con fiabilidad baja "
                f"hasta que otro canal los corrobore.", {"noise": noise, "confirmed": confirmed, "suggest_trust": "low"})
        elif confirmed >= 0.6 and prior == "low":
            add("source_reliability", src, f"La fuente {src} quedó corroborada el {confirmed:.0%} de las veces pese a su fiabilidad baja de partida: "
                f"actúa antes con ella.", {"noise": noise, "confirmed": confirmed, "suggest_trust": "medium"})

    contacts = list(db.scalars(select(Contact).where(Contact.crisis_id == c.id)))
    for eid in {k.entity_id for k in contacts}:
        mine = [k for k in contacts if k.entity_id == eid]
        missed = [k for k in mine if k.status in ("no_answer", "failed")]
        if missed and len(missed) / len(mine) >= 0.5:
            esc = ents[eid].escalation_to if eid in ents else None
            add("entity_response", eid, f"{eid} no contestó {len(missed)} de {len(mine)} contactos la última vez: "
                f"contacta con {esc or 'su escalado'} en paralelo en vez de esperar.",
                {"missed": len(missed), "total": len(mine), "escalation_to": esc})

    decided = [a for a in db.scalars(select(Action).where(Action.crisis_id == c.id))
               if (a.approval or {}).get("decided_at")]
    if decided:
        lat = [(datetime.fromisoformat(a.approval["decided_at"]) - a.created_at).total_seconds() for a in decided]
        avg = sum(lat) / len(lat)
        add("approval_latency", "approvals", f"Las aprobaciones humanas tardaron {avg:.0f} s de media la última vez: pide las aprobaciones "
            f"(evacuación, UME) en cuanto la evidencia lo permita.", {"avg_s": avg, "n": len(lat)})

    first = min((s.t for s in signals if not s.is_noise and s.severity_hint >= 5), default=None)
    for z in db.scalars(select(Zone).where(Zone.crisis_id == c.id)):
        if first and z.warned_at and not z.is_origin:
            lead = (z.warned_at - first).total_seconds() / 60
            if lead > 20:
                add("warning_lead", z.id, f"{z.name} fue avisada {lead:.0f} min después de la primera señal seria aguas arriba: "
                    f"avisa a las zonas aguas abajo en cuanto una zona aguas arriba llegue a severidad 5.", {"lead_min": lead})

    failed = [a for a in db.scalars(select(Action).where(Action.crisis_id == c.id, Action.status == "failed"))]
    if failed:
        add("failure", "actions", f"{len(failed)} acciones fallaron la última vez ({', '.join(sorted({a.verb for a in failed}))}): "
            f"mantén una unidad en reserva y nombra un actor alternativo.", {"n": len(failed)})

    c.status, c.closed_at, c.paused = "closed", utcnow(), True
    append_event(db, c, "crisis.closed", {"lessons": [l.text for l in lessons]})
    for l in lessons:
        append_event(db, c, "lesson.created", {"kind": l.kind, "subject": l.subject, "text": l.text})
    return lessons


def apply_lessons(db: Session, c: Crisis) -> list[str]:
    """Called when a crisis opens: past runs of the same hazard move the priors."""
    applied = []
    for l in db.scalars(select(Lesson).where(Lesson.hazard_type == c.hazard_type).order_by(Lesson.id.desc()).limit(30)):
        ent = db.get(Entity, (c.id, l.subject))
        if ent is None:
            continue
        if l.kind == "source_reliability" and l.stats.get("suggest_trust") and ent.trust != l.stats["suggest_trust"]:
            applied.append(f"{ent.id}: trust {ent.trust} → {l.stats['suggest_trust']} (aprendido)")
            ent.trust = l.stats["suggest_trust"]
        if l.kind == "entity_response" and "aprendido" not in (ent.notes or ""):
            ent.notes = (ent.notes + " " if ent.notes else "") + "(aprendido) No contestó en la ejecución anterior: escalar en paralelo."
            applied.append(f"{ent.id}: marcado como poco fiable al teléfono (aprendido)")
    if applied:
        append_event(db, c, "lesson.applied", {"applied": applied})
    return applied
