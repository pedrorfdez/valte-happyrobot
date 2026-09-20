"""Learning, inside a crisis and from one crisis to the next.

INSIDE: while a crisis runs the kernel watches what its own decisions ran into — an entity that does not answer,
an authority that takes long to sign, an order a person rejected, a source whose alarms were false, serious
incidents that wait too long — and turns each into a lesson that applies AT ONCE: the brains read it on the next
wake-up and the kernel enforces the ones it can (it stops asking whoever does not answer, refuses a rejected order
proposed again without new evidence, lowers the trust of a source that cried wolf).

ACROSS: when the crisis closes, what it learned is carried to the next crises of its kind. A lesson seen again
gains weight, one the facts contradict loses it and retires. Optionally an LLM post-mortem adds qualitative
lessons (`PedroD-crisis-review`).

Two rules, both borrowed from a teammate's design: a lesson cites EVIDENCE (ids of real actions, contacts,
incidents or signals of the crisis that taught it) or it is not stored, and every decision that leans on a lesson
says so (`lesson_uses`), which is what lets a supervisor see that the system really learned.
"""

import json
import logging
import re
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from valte.core.events import append_event
from valte.core.world import scenario_now
from valte.models import Action, Contact, Crisis, Entity, Incident, Lesson, LessonUse, Signal, Zone, utcnow

log = logging.getLogger("valte.learning")

KIND_ES = {"entity_response": "quién no contesta", "approval_latency": "lo que tardan las firmas", "rejection": "lo que un humano rechazó",
           "source_reliability": "fiabilidad de las fuentes", "response_time": "lo que espera una incidencia grave",
           "warning_lead": "aviso aguas abajo", "failure": "acciones fallidas", "human": "dicho por una persona", "review": "revisión de la crisis"}
CARRIED = ("entity_response", "approval_latency", "source_reliability", "response_time", "warning_lead", "failure", "human", "review")
TRUST = ("low", "medium", "high")


def public_id(l: Lesson) -> str:
    return f"L-{l.id}"


def lesson_dict(l: Lesson, *, crisis_id: str | None = None) -> dict[str, Any]:
    return {"id": public_id(l), "kind": l.kind, "kind_label": KIND_ES.get(l.kind, l.kind), "subject": l.subject, "text": l.text,
            "scope": l.scope, "from_this_crisis": bool(crisis_id) and l.scope == "crisis" and l.source_crisis_id == crisis_id,
            "evidence": l.evidence or [], "rule": l.rule or {}, "weight": l.weight, "status": l.status, "origin": l.origin,
            "applied": l.applied, "stats": l.stats or {}, "source_crisis_id": l.source_crisis_id}


def lessons_for(db: Session, c: Crisis, *, limit: int = 14) -> list[Lesson]:
    """What applies to this crisis: what it has learned itself, then what earlier crises of its kind left."""
    own = list(db.scalars(select(Lesson).where(Lesson.scope == "crisis", Lesson.source_crisis_id == c.id, Lesson.status == "active")
                          .order_by(Lesson.id.desc())))
    past = list(db.scalars(select(Lesson).where(Lesson.scope == "global", Lesson.hazard_type == c.hazard_type, Lesson.status == "active",
                                                Lesson.source_crisis_id != c.id).order_by(Lesson.weight.desc(), Lesson.id.desc())))
    return (own + past)[:limit]


def brain_view(db: Session, c: Crisis) -> list[dict[str, Any]]:
    return [{"id": public_id(l), "learned": "in_this_crisis" if l.scope == "crisis" else f"in_{l.weight}_previous_crisis(es)",
             "lesson": l.text, "evidence": (l.evidence or [])[:4]} for l in lessons_for(db, c)]


# ── storing a lesson ─────────────────────────────────────────────────────


def _upsert(db: Session, c: Crisis, *, kind: str, subject: str, text: str, evidence: list[str], stats: dict[str, Any],
            rule: dict[str, Any] | None = None, scope: str = "crisis", origin: str = "kernel") -> tuple[Lesson, bool]:
    """One lesson per thing learned (kind + subject). Returns (lesson, it is new or says something new)."""
    evidence = list(dict.fromkeys(str(e) for e in evidence if e))
    if not evidence:
        raise ValueError("a lesson needs evidence")
    key = f"{kind}:{subject}"
    q = select(Lesson).where(Lesson.key == key, Lesson.scope == scope, Lesson.status == "active")
    q = q.where(Lesson.source_crisis_id == c.id) if scope == "crisis" else q.where(Lesson.hazard_type == c.hazard_type)
    l = db.scalars(q).first()
    created = l is None
    if created:
        l = Lesson(hazard_type=c.hazard_type, pack_id=c.pack_id, kind=kind, subject=subject, key=key, scope=scope, origin=origin,
                   source_crisis_id=c.id, text=text, evidence=evidence, stats=stats, rule=rule or {}, weight=1)
        db.add(l)
        db.flush()
    changed = created or l.text != text
    l.text, l.stats, l.rule, l.updated_at = text, stats, rule or {}, utcnow()
    l.evidence = list(dict.fromkeys([*(l.evidence or []), *evidence]))[-12:]
    if changed and scope == "crisis":
        append_event(db, c, "lesson.learned" if created else "lesson.updated", lesson_dict(l, crisis_id=c.id), material=created,
                     digest=f"LESSON {public_id(l)} learned in this crisis ({kind}): {text} Evidence: {', '.join(evidence[:4])}. "
                            f"Apply it from now on and cite {public_id(l)} in the actions it shapes." if created else None)
    return l, changed


def record_use(db: Session, c: Crisis, lesson: Lesson, *, by: str, ref: str = "", note: str = "") -> None:
    if db.scalars(select(LessonUse).where(LessonUse.lesson_id == lesson.id, LessonUse.crisis_id == c.id, LessonUse.ref == ref,
                                          LessonUse.by == by)).first():
        return
    db.add(LessonUse(lesson_id=lesson.id, crisis_id=c.id, t=scenario_now(c), by=by, ref=ref, note=note))
    lesson.applied = (lesson.applied or 0) + 1
    append_event(db, c, "lesson.applied", {"lesson": lesson_dict(lesson, crisis_id=c.id), "by": by, "ref": ref, "note": note,
                                           "applied": [f"{public_id(lesson)} · {note or lesson.text}"]})


def cite(db: Session, c: Crisis, ids: Any, *, by: str, ref: str) -> list[str]:
    """A brain says which lessons a decision leaned on. Only the real ones that apply here are kept."""
    wanted = {str(i).strip().upper() for i in (ids if isinstance(ids, list) else [ids] if ids else [])}
    ok = []
    for l in lessons_for(db, c, limit=60):
        if public_id(l) in wanted:
            record_use(db, c, l, by=by, ref=ref)
            ok.append(public_id(l))
    return ok


def add_human_lesson(db: Session, c: Crisis, *, text: str, by: str, evidence: list[str] | None = None) -> Lesson:
    """A supervisor tells the system something it could not know ("no contéis con el puente de la CV-36")."""
    seq = int((c.counters or {}).get("human_lesson", 0)) + 1
    c.counters = {**(c.counters or {}), "human_lesson": seq}
    l, _ = _upsert(db, c, kind="human", subject=f"{by}-{seq}", text=text.strip(), evidence=evidence or [f"dicho por {by}"],
                   stats={"by": by}, origin="human")
    return l


# ── inside the crisis ────────────────────────────────────────────────────


def _rule(db: Session, c: Crisis, kind: str, subject: str | None = None) -> list[Lesson]:
    return [l for l in lessons_for(db, c, limit=60) if (l.rule or {}).get("type") == kind
            and (subject is None or (l.rule or {}).get("entity") == subject or (l.rule or {}).get("source") == subject)]


def reroute_approver(db: Session, c: Crisis, approver: Entity, *, ref: str = "") -> Entity:
    """Learned: this authority does not answer. Ask whoever it escalates to, now, instead of waiting for the ring to time out."""
    for l in _rule(db, c, "route_around", approver.id):
        to = db.get(Entity, (c.id, (l.rule or {}).get("to") or ""))
        if to is not None and to.status != "unreachable":
            record_use(db, c, l, by="kernel", ref=ref, note=f"la firma se pide a {to.name} y no a {approver.name}, que no contesta")
            return to
    return approver


def blocked_by_rejection(db: Session, c: Crisis, verb: str, zones: list[str], evidence: list[str]) -> str | None:
    """Learned: a person said no to this. The same order with nothing new behind it is refused."""
    for l in _rule(db, c, "avoid"):
        r = l.rule or {}
        if r.get("verb") != verb or not (set(r.get("zones") or []) & set(zones) or (not r.get("zones") and not zones)):
            continue
        since = datetime.fromisoformat(r["since"])
        fresh = [s for s in (db.get(Signal, (c.id, e)) for e in evidence) if s is not None and s.t > since]
        if not fresh:
            record_use(db, c, l, by="kernel", ref=f"{verb}:{','.join(zones)}", note="orden rechazada propuesta otra vez sin evidencia nueva: no se admite")
            return (f"lesson {public_id(l)}: {l.text} Propose it again only with evidence newer than the rejection "
                    f"({r['since'][:16]}), or choose another measure.")
    return None


def learn_now(db: Session, c: Crisis) -> list[Lesson]:
    """One pass over what has happened so far. Cheap and idempotent: the engine runs it every few ticks."""
    ents = {e.id: e for e in db.scalars(select(Entity).where(Entity.crisis_id == c.id))}
    zones = {z.id: z for z in db.scalars(select(Zone).where(Zone.crisis_id == c.id))}
    name = lambda eid: ents[eid].name if eid in ents else eid  # noqa: E731
    out: list[Lesson] = []

    def learned(**kw: Any) -> None:
        l, changed = _upsert(db, c, **kw)
        if changed:
            out.append(l)

    # 1 · who does not answer → the kernel stops waiting for them
    contacts = list(db.scalars(select(Contact).where(Contact.crisis_id == c.id).order_by(Contact.t)))
    for eid in {k.entity_id for k in contacts}:
        done = [k for k in contacts if k.entity_id == eid and k.status not in ("queued", "sending", "ringing", "in_progress")]
        missed = [k for k in done if k.status in ("no_answer", "failed")]
        esc = ents[eid].escalation_to if eid in ents else None
        if len(missed) >= 2 and len(missed) / len(done) >= 0.5:
            learned(kind="entity_response", subject=eid, evidence=[k.id for k in missed],
                    text=f"{name(eid)} no ha contestado {len(missed)} de {len(done)} contactos en esta crisis: "
                         + (f"dirígete a {name(esc)} directamente, sin esperar." if esc else "no cuentes con su respuesta."),
                    stats={"missed": len(missed), "total": len(done), "escalation_to": esc},
                    rule={"type": "route_around", "entity": eid, "to": esc} if esc else {})

    # 2 · how long each authority takes to sign → ask earlier
    acts = list(db.scalars(select(Action).where(Action.crisis_id == c.id).order_by(Action.seq)))
    by_approver: dict[str, list[tuple[Action, float]]] = {}
    for a in acts:
        ap = a.approval or {}
        if ap.get("decided_t") and ap.get("decided_by") and ap.get("decision") in ("approved", "rejected"):
            # scenario minutes between asking and signing (wall time would count every pause of the simulation)
            mins = max(0.0, (datetime.fromisoformat(ap["decided_t"]) - a.t).total_seconds() / 60.0)
            by_approver.setdefault(ap.get("approver") or ap["decided_by"], []).append((a, mins))
    for eid, rows in by_approver.items():
        avg = sum(m for _, m in rows) / len(rows)
        if len(rows) >= 2 and avg >= 8:
            learned(kind="approval_latency", subject=eid, evidence=[a.id for a, _ in rows],
                    text=f"{name(eid)} tarda unos {_span(avg)} de escenario en firmar ({len(rows)} firmas): pídele las aprobaciones "
                         f"en cuanto haya evidencia, sin esperar a confirmarla del todo.",
                    stats={"avg_min": round(avg, 1), "n": len(rows)}, rule={"type": "lead_time", "entity": eid, "minutes": round(avg)})

    # 3 · what a person rejected → not again without something new
    for a in acts:
        ap = a.approval or {}
        if a.status == "rejected" and ap.get("decision") == "rejected" and ap.get("decided_by"):
            where = ", ".join(zones[z].name if z in zones else z for z in a.target_zones) or "toda la crisis"
            why = (ap.get("note") or a.error or "").strip()
            since = _existing_since(db, c, a) or scenario_now(c).isoformat()  # the pass right after the "no" fixes the moment
            learned(kind="rejection", subject=f"{a.verb}:{','.join(sorted(a.target_zones))}", evidence=[a.id],
                    text=f"{name(ap['decided_by'])} rechazó «{a.verb_label or a.verb}» en {where}" + (f": «{why}»" if why else "")
                         + ". No lo propongas de nuevo sin evidencia nueva; busca otra medida.",
                    stats={"by": ap["decided_by"], "reason": why},
                    rule={"type": "avoid", "verb": a.verb, "zones": sorted(a.target_zones), "since": since})

    # 4 · sources that cried wolf (or that turned out right) → their trust moves now
    incs = list(db.scalars(select(Incident).where(Incident.crisis_id == c.id, Incident.origin == "kernel")))
    wolf: dict[str, list[str]] = {}
    right: dict[str, list[str]] = {}
    for inc in incs:
        sigs = [s for s in (db.get(Signal, (c.id, sid)) for sid in inc.signal_ids or []) if s is not None]
        if not sigs:
            continue
        first = min(sigs, key=lambda s: s.t)
        if inc.state == "dismissed" and "ruido" not in (inc.closed_reason or ""):
            for src in {s.source for s in sigs}:
                wolf.setdefault(src, []).append(inc.id)
        elif first.source_trust == "low" and inc.confidence == "high" and len(inc.origins or []) >= 2:
            right.setdefault(first.source, []).append(inc.id)
    for src, ids in wolf.items():
        ent = ents.get(src)
        if len(ids) >= 2 and ent is not None and ent.trust != "low":
            lower = TRUST[max(0, TRUST.index(ent.trust) - 1)] if ent.trust in TRUST else "low"
            learned(kind="source_reliability", subject=src, evidence=ids,
                    text=f"{name(src)} ha dado {len(ids)} falsas alarmas en esta crisis: su fiabilidad baja a {_trust_es(lower)} "
                         f"y sus avisos necesitan otra fuente antes de mover recursos.",
                    stats={"false_alarms": len(ids), "suggest_trust": lower}, rule={"type": "trust", "source": src, "trust": lower})
    for src, ids in right.items():
        ent = ents.get(src)
        if len(ids) >= 2 and ent is not None and ent.trust == "low" and src not in wolf:
            learned(kind="source_reliability", subject=src, evidence=ids,
                    text=f"{name(src)} avisó primero de {len(ids)} incidencias que luego confirmaron otras fuentes: su fiabilidad "
                         f"sube a media; prepara recursos con su primer aviso.",
                    stats={"confirmed_first": len(ids), "suggest_trust": "medium"}, rule={"type": "trust", "source": src, "trust": "medium"})
    for l in _rule(db, c, "trust"):  # enforce: the next report from that source is weighed with what we now know
        if l.scope != "crisis":
            continue
        ent = ents.get((l.rule or {}).get("source"))
        if ent is not None and ent.trust != l.rule["trust"]:
            record_use(db, c, l, by="kernel", ref=ent.id, note=f"fiabilidad de {ent.name}: {_trust_es(ent.trust)} → {_trust_es(l.rule['trust'])}")
            ent.trust = l.rule["trust"]

    # 5 · how long serious incidents wait until somebody goes → keep a reserve
    from valte.core.incidents import covering_actions

    waits: list[tuple[Incident, float]] = []
    for inc in incs:
        if inc.priority in ("P0", "P1") and inc.first_t and inc.kind != "hazard":
            on_it = [a for a in covering_actions(db, inc) if a.status != "pending_approval"]
            if on_it:
                waits.append((inc, max(0.0, (min(a.t for a in on_it) - inc.first_t).total_seconds() / 60.0)))
    slow = [(i, w) for i, w in waits if w >= 10]
    if len(waits) >= 3 and len(slow) / len(waits) >= 0.4:
        avg = sum(w for _, w in slow) / len(slow)
        learned(kind="response_time", subject="serious-incidents", evidence=[i.id for i, _ in slow],
                text=f"{len(slow)} de {len(waits)} incidencias graves esperaron unos {avg:.0f} min hasta que salió alguien: mantén unidades "
                     f"libres en reserva y adelanta refuerzos a las zonas donde se acumulan.",
                stats={"slow": len(slow), "total": len(waits), "avg_wait_min": round(avg, 1)}, rule={"type": "reserve"})
    return out


def _existing_since(db: Session, c: Crisis, a: Action) -> str | None:
    """A rejection lesson keeps the moment of the rejection, not of the last pass over it."""
    key = f"rejection:{a.verb}:{','.join(sorted(a.target_zones))}"
    l = db.scalars(select(Lesson).where(Lesson.key == key, Lesson.scope == "crisis", Lesson.source_crisis_id == c.id)).first()
    return (l.rule or {}).get("since") if l else None


def _span(minutes: float) -> str:
    return f"{minutes:.0f} min" if minutes < 120 else f"{minutes / 60:.0f} h"


def _short(evidence_id: str) -> str:
    """Contacts are uuids: nobody reads those."""
    return f"contacto {evidence_id[:8]}" if re.fullmatch(r"[0-9a-f]{8}-[0-9a-f-]{27}", evidence_id) else evidence_id


def _trust_es(t: str) -> str:
    return {"low": "baja", "medium": "media", "high": "alta"}.get(t, t)


# ── from one crisis to the next ──────────────────────────────────────────


def close_crisis(db: Session, c: Crisis) -> list[Lesson]:
    """Look back at the whole run, then carry what it taught to the next crises of its kind."""
    if c.status == "closed":
        return []
    learn_now(db, c)
    ents = {e.id: e for e in db.scalars(select(Entity).where(Entity.crisis_id == c.id))}
    signals = list(db.scalars(select(Signal).where(Signal.crisis_id == c.id)))

    def add(kind: str, subject: str, text: str, stats: dict[str, Any], evidence: list[str], rule: dict[str, Any] | None = None) -> None:
        if evidence:
            _upsert(db, c, kind=kind, subject=subject, text=text, stats=stats, evidence=evidence, rule=rule)

    # Whole-run statistics that only make sense at the end.
    for src in {s.source for s in signals}:
        mine = [s for s in signals if s.source == src]
        if len(mine) < 4:
            continue
        noise = sum(1 for s in mine if s.is_noise) / len(mine)
        confirmed = sum(1 for s in mine if s.confidence == "high") / len(mine)
        prior = ents[src].trust if src in ents else "low"
        if noise >= 0.5 and prior != "low":
            add("source_reliability", src, f"{ents[src].name if src in ents else src} fue ruido en un {noise:.0%} de sus avisos: trátalos con "
                f"fiabilidad baja hasta que otro canal los corrobore.", {"noise": noise, "confirmed": confirmed, "suggest_trust": "low"},
                [s.id for s in mine if s.is_noise][:6], {"type": "trust", "source": src, "trust": "low"})
        elif confirmed >= 0.6 and prior == "low":
            add("source_reliability", src, f"{ents[src].name if src in ents else src} quedó corroborada el {confirmed:.0%} de las veces pese a "
                f"su fiabilidad baja de partida: actúa antes con ella.", {"noise": noise, "confirmed": confirmed, "suggest_trust": "medium"},
                [s.id for s in mine if s.confidence == "high"][:6], {"type": "trust", "source": src, "trust": "medium"})

    for eid in {k.entity_id for k in db.scalars(select(Contact).where(Contact.crisis_id == c.id))}:
        mine = list(db.scalars(select(Contact).where(Contact.crisis_id == c.id, Contact.entity_id == eid)))
        missed = [k for k in mine if k.status in ("no_answer", "failed")]
        esc = ents[eid].escalation_to if eid in ents else None
        if missed and len(missed) / len(mine) >= 0.5:
            add("entity_response", eid, f"{ents[eid].name if eid in ents else eid} no contestó {len(missed)} de {len(mine)} contactos: "
                f"contacta con {ents[esc].name if esc in ents else 'su escalado'} en paralelo en vez de esperar.",
                {"missed": len(missed), "total": len(mine), "escalation_to": esc}, [k.id for k in missed],
                {"type": "route_around", "entity": eid, "to": esc} if esc else None)

    first = min((s for s in signals if not s.is_noise and s.severity_hint >= 5), key=lambda s: s.t, default=None)
    for z in db.scalars(select(Zone).where(Zone.crisis_id == c.id)):
        if first and z.warned_at and not z.is_origin:
            lead = (z.warned_at - first.t).total_seconds() / 60
            if lead > 20:
                add("warning_lead", z.id, f"{z.name} fue avisada {lead:.0f} min después de la primera señal seria aguas arriba: avisa a las "
                    f"zonas aguas abajo en cuanto una zona aguas arriba llegue a severidad 5.", {"lead_min": lead}, [first.id])

    failed = list(db.scalars(select(Action).where(Action.crisis_id == c.id, Action.status == "failed")))
    if failed:
        add("failure", "actions", f"{len(failed)} acciones fallaron ({', '.join(sorted({a.verb_label or a.verb for a in failed}))}): "
            f"mantén una unidad en reserva y nombra un actor alternativo.", {"n": len(failed)}, [a.id for a in failed][:6])

    carried = carry_forward(db, c)
    c.status, c.closed_at, c.paused = "closed", utcnow(), True
    append_event(db, c, "crisis.closed", {"lessons": [l.text for l in carried]})
    return carried


def carry_forward(db: Session, c: Crisis) -> list[Lesson]:
    """What this crisis learned becomes what the next one starts with. Seen again: more weight. Contradicted: less, then retired."""
    out = []
    own = list(db.scalars(select(Lesson).where(Lesson.scope == "crisis", Lesson.source_crisis_id == c.id, Lesson.status == "active")))
    for l in own:
        if l.kind not in CARRIED:
            continue  # "the mayor rejected evacuating Paiporta today" is about today
        g = db.scalars(select(Lesson).where(Lesson.scope == "global", Lesson.key == l.key, Lesson.hazard_type == c.hazard_type,
                                            Lesson.status == "active")).first()
        if g is None:
            g = Lesson(hazard_type=c.hazard_type, pack_id=c.pack_id, kind=l.kind, subject=l.subject, key=l.key, scope="global",
                       origin=l.origin, source_crisis_id=c.id, text=l.text, evidence=l.evidence, stats={**(l.stats or {}), "crises": [c.code]},
                       rule=l.rule or {}, weight=1)
            db.add(g)
        else:
            seen = list(dict.fromkeys([*((g.stats or {}).get("crises") or []), c.code]))
            g.weight, g.text, g.rule, g.evidence = len(seen) if len(seen) > g.weight else g.weight + 1, l.text, l.rule or g.rule, l.evidence
            g.stats, g.source_crisis_id, g.updated_at = {**(l.stats or {}), "crises": seen}, c.id, utcnow()
        db.flush()
        out.append(g)
        append_event(db, c, "lesson.created", {**lesson_dict(g), "kind": g.kind, "subject": g.subject, "text": g.text})

    # What we were told before and the facts of this crisis did not bear out.
    ents = {e.id: e for e in db.scalars(select(Entity).where(Entity.crisis_id == c.id))}
    for g in db.scalars(select(Lesson).where(Lesson.scope == "global", Lesson.hazard_type == c.hazard_type, Lesson.status == "active",
                                             Lesson.source_crisis_id != c.id)):
        if g.kind == "entity_response" and g.subject in ents:
            mine = list(db.scalars(select(Contact).where(Contact.crisis_id == c.id, Contact.entity_id == g.subject)))
            if len(mine) >= 2 and not any(k.status in ("no_answer", "failed") for k in mine):
                g.weight -= 1
                g.status = "retired" if g.weight <= 0 else "active"
                append_event(db, c, "lesson.weakened", {**lesson_dict(g), "why": f"{ents[g.subject].name} contestó a todo en esta crisis"})
    return out


def apply_lessons(db: Session, c: Crisis) -> list[str]:
    """Called when a crisis opens: what earlier crises of its kind taught moves the priors before the first signal."""
    applied = []
    for l in db.scalars(select(Lesson).where(Lesson.scope == "global", Lesson.hazard_type == c.hazard_type, Lesson.status == "active")
                        .order_by(Lesson.weight.desc(), Lesson.id.desc()).limit(30)):
        ent = db.get(Entity, (c.id, l.subject))
        if ent is None:
            continue
        want = (l.rule or {}).get("trust") or (l.stats or {}).get("suggest_trust")
        if l.kind == "source_reliability" and want and ent.trust != want:
            note = f"fiabilidad de {ent.name}: {_trust_es(ent.trust)} → {_trust_es(want)} (aprendido en {l.weight} crisis)"
            ent.trust = want
            applied.append(note)
            record_use(db, c, l, by="kernel", ref=ent.id, note=note)
        if l.kind == "entity_response" and "aprendido" not in (ent.notes or ""):
            ent.notes = (ent.notes + " " if ent.notes else "") + "(aprendido) No contestó en la ejecución anterior: escalar en paralelo."
            note = f"{ent.name}: no contestó en crisis anteriores, se escalará en paralelo"
            applied.append(note)
            record_use(db, c, l, by="kernel", ref=ent.id, note=note)
    return applied


# ── what the dashboard shows ─────────────────────────────────────────────


def lessons_screen(db: Session, c: Crisis) -> dict[str, Any]:
    rows = lessons_for(db, c, limit=60) if c.status != "closed" else list(db.scalars(select(Lesson).where(
        Lesson.source_crisis_id == c.id).order_by(Lesson.id.desc())))
    uses = list(db.scalars(select(LessonUse).where(LessonUse.crisis_id == c.id).order_by(LessonUse.id.desc()).limit(60)))
    by_lesson: dict[int, list[LessonUse]] = {}
    for u in uses:
        by_lesson.setdefault(u.lesson_id, []).append(u)
    who = {"kernel": "el kernel", "coordinator": "el coordinador", "proactive": "la ronda proactiva", "command": "el estratega",
           "local-brain": "el cerebro local", "human": "una persona"}

    def row(l: Lesson) -> dict[str, Any]:
        mine = by_lesson.get(l.id, [])
        return {**lesson_dict(l, crisis_id=c.id),
                "meta": KIND_ES.get(l.kind, l.kind) + (f" · vista en {l.weight} crisis" if l.scope == "global" and l.weight > 1 else ""),
                "evidenceLabel": (f"{len(l.evidence or [])} {'prueba' if len(l.evidence or []) == 1 else 'pruebas'}: "
                                  + ", ".join(_short(e) for e in (l.evidence or [])[:4])) if l.evidence else "sin pruebas (anterior al registro de evidencia)",
                "uses": [{"by": who.get(u.by, u.by), "ref": u.ref, "note": u.note} for u in mine],
                "usesLabel": (f"aplicada {len(mine)} {'vez' if len(mine) == 1 else 'veces'} en esta crisis" if mine else "aún sin aplicar aquí")}

    out = [row(l) for l in rows]
    return {"lessons": out, "now": [l for l in out if l["from_this_crisis"]], "before": [l for l in out if not l["from_this_crisis"]],
            "applied": sum(1 for l in out if l["uses"])}


# ── the LLM post-mortem (optional, one run per closed crisis) ────────────


def review_brief(db: Session, c: Crisis) -> dict[str, Any]:
    """What the reviewer reads: the incidents, what was done about each and how long it took, and what went wrong."""
    from valte.core.incidents import covering_actions, incident_view

    incs = []
    for inc in db.scalars(select(Incident).where(Incident.crisis_id == c.id, Incident.origin == "kernel").order_by(Incident.seq)):
        v = incident_view(db, c, inc)
        acts = covering_actions(db, inc)
        first = min((a.t for a in acts if a.status != "pending_approval"), default=None)
        incs.append({k: v[k] for k in ("id", "title", "priority", "state", "confidence", "signals", "sources", "people", "closed_reason")}
                    | {"minutes_until_someone_went": round((first - inc.first_t).total_seconds() / 60) if first and inc.first_t else None,
                       "actions": [f"{a.id} {a.actor} {a.verb} {a.status}" for a in acts]})
    acts = list(db.scalars(select(Action).where(Action.crisis_id == c.id).order_by(Action.seq)))
    return {"crisis": {"code": c.code, "name": c.name, "hazard_type": c.hazard_type, "region": c.region},
            "incidents": incs[:40],
            "actions": [{"id": a.id, "actor": a.actor, "verb": a.verb, "zones": a.target_zones, "status": a.status, "origin": a.origin,
                         "error": a.error, "approval": {k: (a.approval or {}).get(k) for k in ("approver", "decision", "note", "level")}}
                        for a in acts][:60],
            "contacts": [{"id": k.id, "entity": k.entity_id, "purpose": k.purpose, "channel": k.channel, "status": k.status}
                         for k in db.scalars(select(Contact).where(Contact.crisis_id == c.id))][:40],
            "lessons_already_learned": [l.text for l in db.scalars(select(Lesson).where(Lesson.source_crisis_id == c.id))]}


def store_review(db: Session, c: Crisis, doc: dict[str, Any]) -> list[Lesson]:
    """Keep only the reviewer's lessons that cite evidence which exists in this crisis."""
    kept = []
    for i, raw in enumerate((doc.get("lessons") or [])[:4]):
        text = str(raw.get("lesson") or raw.get("text") or "").strip()
        real = [e for e in (str(x) for x in raw.get("evidence") or [])
                if db.get(Action, (c.id, e)) or db.get(Incident, (c.id, e)) or db.get(Signal, (c.id, e))
                or getattr(db.get(Contact, e), "crisis_id", None) == c.id]
        if not (10 <= len(text) <= 400) or not real:
            continue
        subject = re.sub(r"[^a-z0-9]+", "-", str(raw.get("subject") or f"review-{i + 1}").lower()).strip("-")[:40]
        l, _ = _upsert(db, c, kind="review", subject=subject, text=text, evidence=real, stats={"from": c.code}, scope="global", origin="review")
        kept.append(l)
        append_event(db, c, "lesson.created", {**lesson_dict(l), "kind": l.kind, "subject": l.subject, "text": l.text})
    return kept


async def review_with_hr(crisis_id: str) -> int:
    """Background job after a close: ask PedroD-crisis-review for up to 4 lessons, keep the ones with real evidence."""
    import asyncio
    import time

    from valte.db import crisis_lock, session_scope
    from valte.hr import registry
    from valte.hr.client import hr

    with session_scope() as db:
        c = db.get(Crisis, crisis_id)
        wf = registry.get(db, registry.CRISIS_REVIEW) if c is not None and registry.usable(db, registry.CRISIS_REVIEW) else None
        if wf is None or not (wf.node_ids or {}).get("extract"):
            return 0
        target, brief = (wf.workflow_id, wf.node_ids["extract"]), json.dumps(review_brief(db, c), ensure_ascii=False)
    try:
        run_id = await hr().trigger_run(target[0], {"brief_json": brief})
        t0 = time.monotonic()
        while time.monotonic() - t0 < 60:
            await asyncio.sleep(2)
            status = str((await hr().get_run(run_id)).get("status") or "").lower()
            if status in ("failed", "error", "cancelled", "canceled"):
                return 0
            if status in ("completed", "success", "succeeded", "finished"):
                out = await hr().node_output(run_id, target[1])
                response = ((out or {}).get("data") or {}).get("response")
                response = json.loads(response) if isinstance(response, str) else response
                doc = (response or {}).get("lessons_json")
                doc = json.loads(doc) if isinstance(doc, str) else doc
                if not isinstance(doc, dict):
                    return 0
                with crisis_lock(crisis_id), session_scope() as db:
                    return len(store_review(db, db.get(Crisis, crisis_id), doc))
    except Exception as e:
        log.warning("crisis review failed: %s", e)
    return 0
