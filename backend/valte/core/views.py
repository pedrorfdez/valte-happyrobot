"""Read models shaped for the dashboard screens.

Items mirror the props of the design's components: ActionItem takes
{action, time, verbLabel, actorName, deadline}, SignalItem takes
{signal, time, sourceName, noise}.
"""

from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from valte.core.world import (
    ACTION_STATES,
    VERB_LABELS,
    action_dict,
    action_state,
    active_plan,
    clock_dict,
    contact_dict,
    entities_of,
    entity_dict,
    hhmm,
    incident_dict,
    plan_dict,
    resource_dict,
    resources_of,
    scenario_now,
    signal_dict,
    zone_dict,
    zones_of,
)
from valte.core.outreach import contactable
from valte.models import Action, Contact, Crisis, Entity, Incident, Plan, Signal, Zone, utcnow

KIND_LABEL = {"information_source": "Fuente", "authority": "Autoridad", "responder": "Respuesta",
              "population": "Población"}
CONTACT_LABEL = {"queued": "En cola", "sending": "Enviando", "ringing": "Llamando", "in_progress": "En curso",
                 "delivered": "Entregado", "completed": "Completada", "no_answer": "Sin respuesta",
                 "failed": "Fallido", "superseded": "Resuelto por otra vía"}


def operational(e: Entity) -> bool:
    """Units that are hours away (UME before it is requested and arrives) are not 'free units'."""
    return not ((e.activation or {}).get("delay_min", 0) >= 60 and not (e.units_available or 0))


def _names(db: Session, cid: str) -> dict[str, str]:
    return {e.id: e.name for e in entities_of(db, cid)} | {"system": "Agente"}


def _countdown(deadline_wall: str | None) -> str | None:
    if not deadline_wall:
        return None
    left = int((datetime.fromisoformat(deadline_wall) - utcnow()).total_seconds())
    return f"{max(0, left) // 60:02d}:{max(0, left) % 60:02d}"


def action_item(c: Crisis, a: Action, names: dict[str, str]) -> dict[str, Any]:
    return {"action": action_dict(a), "time": hhmm(c, a.t), "verbLabel": a.verb_label,
            "actorName": names.get(a.actor, a.actor),
            "deadline": _countdown((a.approval or {}).get("deadline_wall")) if a.status == "pending_approval" else None}


def signal_item(c: Crisis, s: Signal, names: dict[str, str]) -> dict[str, Any]:
    return {"signal": signal_dict(s), "time": hhmm(c, s.t), "sourceName": names.get(s.source, s.source),
            "noise": s.is_noise}


def sees_everything(viewer: Entity | None) -> bool:
    """Inventories belong to whoever owns them. Coordination (CECOPI) sees all of them; any other entity
    sees its own units and its own supplies, never a neighbour's."""
    return viewer is None or viewer.role == "coordination"


def own_inventory_kpi(db: Session, c: Crisis, viewer: Entity | None) -> dict[str, Any]:
    if sees_everything(viewer):
        ents = [e for e in entities_of(db, c.id) if e.units_total is not None and operational(e)]
        return {"available": sum(e.units_available or 0 for e in ents), "total": sum(e.units_total or 0 for e in ents),
                "label": "unidades libres"}
    if viewer.units_total is not None:
        return {"available": viewer.units_available or 0, "total": viewer.units_total, "label": "unidades propias libres"}
    owned = sorted((r for r in resources_of(db, c.id) if r.owner_entity_id == viewer.id), key=lambda r: -r.total)
    if owned:
        return {"available": round(owned[0].available), "total": round(owned[0].total), "label": owned[0].name.lower()}
    return {"available": 0, "total": 0, "label": "sin recursos propios"}


def kpis(db: Session, c: Crisis, *, zone_ids: list[str] | None = None, entity: Entity | None = None,
         viewer: Entity | None = None) -> dict[str, Any]:
    cid = c.id
    zones = [z for z in zones_of(db, cid) if zone_ids is None or z.id in zone_ids]
    pop = sum(z.population for z in zones) or 1
    act_q = select(Action.status, func.count()).where(Action.crisis_id == cid)
    if entity is not None:
        act_q = act_q.where(Action.actor == entity.id)
    by_status = dict(db.execute(act_q.group_by(Action.status)).all())
    sig_q = select(func.count()).select_from(Signal).where(Signal.crisis_id == cid)
    if zone_ids is not None:
        sig_q = sig_q.where(Signal.zone_id.in_(zone_ids))
    window = scenario_now(c) - timedelta(minutes=10)
    con_q = select(Contact.status, func.count()).where(Contact.crisis_id == cid)
    if entity is not None:
        con_q = con_q.where(Contact.entity_id == entity.id)
    contacts = dict(db.execute(con_q.group_by(Contact.status)).all())
    directory = [e for e in entities_of(db, cid) if contactable(e)]
    return {
        "zones": {"total": len(zones), "origins": sum(1 for z in zones if z.is_origin),
                  "warned": sum(1 for z in zones if z.warned),
                  "at_risk_pct": round(sum(z.population * z.at_risk_pct for z in zones) / pop)},
        "actions": {"total": sum(by_status.values()), **{k: by_status.get(k, 0) for k in
                    ("pending_approval", "approved", "executed", "rejected", "failed")}},
        "signals": {"total": db.scalar(sig_q) or 0,
                    "noise": db.scalar(sig_q.where(Signal.is_noise.is_(True))) or 0,
                    "per_min": round((db.scalar(sig_q.where(Signal.t >= window)) or 0) / 10, 1)},
        "units": own_inventory_kpi(db, c, viewer or entity),
        # Contacts are the entities we can talk to; `total`/`unanswered` count the communications with them.
        "contacts": {"entities": sum(1 for e in directory if entity is None or e.id == entity.id),
                     "unreachable": sum(1 for e in directory if e.status == "unreachable" and (entity is None or e.id == entity.id)),
                     "total": sum(contacts.values()), "unanswered": contacts.get("no_answer", 0),
                     "live": contacts.get("in_progress", 0) + contacts.get("ringing", 0)},
    }


def crisis_card(db: Session, c: Crisis) -> dict[str, Any]:
    return {"id": c.id, "code": c.code, "name": c.name, "hazard": c.hazard_type, "status": c.status,
            "severity": c.severity, "trend": c.trend, "zone": c.region,
            "startedAt": hhmm(c, c.t0_scenario), "started": c.started_at is not None, "operators": 1}


def header(db: Session, c: Crisis, viewer: Entity | None = None) -> dict[str, Any]:
    ents = entities_of(db, c.id)
    roles = [{"role": "coordination", "entity_id": e.id, "label": e.name} for e in ents if e.role == "coordination"]
    roles += [{"role": "authority", "entity_id": e.id, "label": e.name} for e in ents
              if e.kind == "authority" and e.role != "coordination"]
    roles += [{"role": "responder", "entity_id": e.id, "label": e.name} for e in ents if e.kind == "responder"]
    return {**crisis_card(db, c), "region": c.region, "hazard_type": c.hazard_type,
            "emergency_level": c.emergency_level, "situation_note": c.situation_note,
            "clock": clock_dict(c), "state_version": c.state_version, "plan_version": c.plan_version,
            "roles": roles, "kpis": kpis(db, c, viewer=viewer),
            "viewer": {"entity_id": viewer.id, "name": viewer.name, "sees_everything": sees_everything(viewer)} if viewer else None,
            "ringing": [contact_row(c, k) for k in db.scalars(select(Contact).where(
                Contact.crisis_id == c.id, Contact.status.in_(("ringing", "in_progress"))).order_by(Contact.seq))]}


def zone_view(db: Session, c: Crisis, z: Zone, all_zones: list[Zone], ents: list[Entity]) -> dict[str, Any]:
    names = {x.id: x.name for x in all_zones}
    come_from = [{"zone": u.id, "name": u.name, "d": f"+{e['delay_min']} min", "delay_min": e["delay_min"]}
                 for u in all_zones for e in (u.downstream or []) if e["to"] == z.id]
    go_to = [{"zone": e["to"], "name": names.get(e["to"], e["to"]), "d": f"+{e['delay_min']} min",
              "delay_min": e["delay_min"]} for e in (z.downstream or [])]
    if z.is_origin:
        eta = "Origen · activo" if z.crossed_at else "Origen"
    elif z.crossed_at:
        eta = "Afectada"
    elif z.eta_min == 0:
        eta = "llegada estimada: ya"
    elif z.eta_min is not None:
        eta = f"llega en +{z.eta_min} min"
    else:
        eta = "sin amenaza aguas arriba"
    return {
        **zone_dict(z), "eta": eta, "peak": z.eta_min,
        "trendLabel": {"rising": "↑ subiendo", "falling": "↓ bajando"}.get(z.trend, "→ estable"),
        "warnLabel": f"Avisada {hhmm(c, z.warned_at)}" if z.warned else "Sin avisar",
        "warnTone": "success" if z.warned else "warning-solid", "warnGlyph": "✓" if z.warned else "◐",
        "from": come_from, "to": go_to, "hasFrom": bool(come_from), "hasTo": bool(go_to),
        "ents": [{"id": e.id, "name": e.name, "status": e.status,
                  "kind": KIND_LABEL.get(e.kind, e.kind) + (" · descubierta" if e.provenance == "discovered" else "")}
                 for e in ents if e.kind != "information_source" and (z.id in (e.jurisdiction or []))],
        "note": z.notes,
    }


def zones_screen(db: Session, c: Crisis) -> dict[str, Any]:
    zones, ents = zones_of(db, c.id), entities_of(db, c.id)
    return {"zones": [zone_view(db, c, z, zones, ents) for z in zones]}


def actions_screen(db: Session, c: Crisis, *, status: str | None = None, actor: str | None = None,
                   zone: str | None = None, limit: int = 200) -> dict[str, Any]:
    names = _names(db, c.id)
    q = select(Action).where(Action.crisis_id == c.id)
    if actor:
        q = q.where(Action.actor == actor)
    scoped = [a for a in db.scalars(q.order_by(Action.seq.desc()).limit(limit)) if not zone or zone in (a.target_zones or [])]
    rows = [a for a in scoped if not status or status in (action_state(a), a.status)]
    every = [action_state(a) for a in scoped]  # the tab counts describe what the list can show (same actor/zone scope)
    return {"pending": [action_item(c, a, names) for a in rows if a.status == "pending_approval"],
            "log": [action_item(c, a, names) for a in rows],
            "counts": {"all": len(every), **{s: every.count(s) for s in ACTION_STATES}}}


def signals_screen(db: Session, c: Crisis, *, modality: str | None = None, noise: bool | None = None,
                   zone: str | None = None, precise: bool = False, limit: int = 100) -> dict[str, Any]:
    names = _names(db, c.id)
    q = select(Signal).where(Signal.crisis_id == c.id)
    if modality:
        q = q.where(Signal.modality == modality)
    if noise is not None:
        q = q.where(Signal.is_noise.is_(noise))
    if zone:
        q = q.where(Signal.zone_id == zone)
    rows = list(db.scalars(q.order_by(Signal.seq.desc()).limit(limit)))
    if precise:
        rows = [s for s in rows if (s.location or {}).get("precision") in ("exact", "street")]
    return {"signals": [signal_item(c, s, names) for s in rows]}


def signals_stats(db: Session, c: Crisis) -> dict[str, Any]:
    rows = list(db.scalars(select(Signal).where(Signal.crisis_id == c.id)))
    ents = {e.id: e for e in entities_of(db, c.id)}
    sources: dict[str, dict[str, Any]] = {}
    for s in rows:
        src = sources.setdefault(s.source, {"id": s.source, "name": ents[s.source].name if s.source in ents else s.source,
                                            "trust": ents[s.source].trust if s.source in ents else "low",
                                            "count": 0, "noise": 0, "last_t": s.t})
        src["count"] += 1
        src["noise"] += int(s.is_noise)
        src["last_t"] = max(src["last_t"], s.t)
    order = {"high": 0, "medium": 1, "low": 2}
    precision = {p: 0 for p in ("exact", "street", "zone", "region", "unknown")}
    for s in rows:
        precision[(s.location or {}).get("precision", "unknown")] = precision.get((s.location or {}).get("precision", "unknown"), 0) + 1
    modality: dict[str, int] = {}
    for s in rows:
        modality[s.modality] = modality.get(s.modality, 0) + 1
    return {"total": len(rows), "noise": sum(1 for s in rows if s.is_noise), "by_modality": modality,
            "precision": precision,
            "fallback_perceptions": sum(1 for s in rows if s.perceived_by == "fallback"),
            "sources": [{**v, "last": hhmm(c, v.pop("last_t"))} for v in
                        sorted(sources.values(), key=lambda v: (order.get(v["trust"], 3), -v["count"]))]}


def resources_screen(db: Session, c: Crisis, viewer: Entity | None = None) -> dict[str, Any]:
    """Units and supplies the viewer is entitled to see: everything for coordination, only its own otherwise."""
    zones = {z.id: z.name for z in zones_of(db, c.id)}
    every, all_ents = sees_everything(viewer), entities_of(db, c.id)
    names = {e.id: e.name for e in all_ents}
    ents = [e for e in all_ents if every or e.id == viewer.id]
    units = [{"id": e.id, "name": e.name, "kind": KIND_LABEL.get(e.kind, e.kind) +
              (" · descubierta" if e.provenance == "discovered" else ""),
              "available": e.units_available or 0, "total": e.units_total,
              "status": e.status if operational(e) else "busy",  # hours away is not "available"
              "zones": [zones.get(z, z) for z in (e.jurisdiction or [])],
              "deployed": [{"zone": zones.get(z, z), "units": n} for z, n in (e.deployed or {}).items()],
              "activation_min": (e.activation or {}).get("delay_min", 0),
              "arrives": hhmm(c, datetime.fromisoformat(e.extra["arrives_t"])) if (e.extra or {}).get("arrives_t") else None}
             for e in ents if e.units_total is not None]
    requested = [action_item(c, a, _names(db, c.id)) for a in db.scalars(
        select(Action).where(Action.crisis_id == c.id, Action.verb == "request_ume").order_by(Action.seq.desc()))
        if every or a.actor == viewer.id]
    supplies = [{**resource_dict(r), "owner_name": names.get(r.owner_entity_id or "", "—")}
                for r in resources_of(db, c.id) if every or r.owner_entity_id == viewer.id]
    live = [e for e in ents if e.units_total is not None and operational(e)]
    return {"units": units, "requested": requested, "supplies": supplies,
            "scope": {"all": every, "entity_id": viewer.id if viewer else None, "name": viewer.name if viewer else None},
            "totals": {"available": sum(e.units_available or 0 for e in live), "total": sum(e.units_total for e in live)}}


def contact_row(c: Crisis, k: Contact) -> dict[str, Any]:
    dur = f"{k.duration_s // 60:02d}:{k.duration_s % 60:02d}" if k.duration_s is not None and k.channel == "voice" else "—"
    return {**contact_dict(k), "time": hhmm(c, k.t), "statusLabel": CONTACT_LABEL.get(k.status, k.status),
            "duration": dur, "simulated": bool((k.outcome or {}).get("simulated")),
            "real_badge": None if (k.outcome or {}).get("simulated") else f"real_{k.channel}"}


def contacts_screen(db: Session, c: Crisis, *, entity: str | None = None) -> dict[str, Any]:
    q = select(Contact).where(Contact.crisis_id == c.id)
    if entity:
        q = q.where(Contact.entity_id == entity)
    rows = list(db.scalars(q.order_by(Contact.seq.desc())))
    return {"contacts": [contact_row(c, k) for k in rows],
            "counts": {"all": len(rows), "voice": sum(1 for k in rows if k.channel == "voice"),
                       "email": sum(1 for k in rows if k.channel == "email"),
                       "no_answer": sum(1 for k in rows if k.status == "no_answer")}}


def directory_screen(db: Session, c: Crisis) -> dict[str, Any]:
    """Contactos = who we can communicate with. Each entity carries its communications, newest first."""
    zones = {z.id: z.name for z in zones_of(db, c.id)}
    ents = entities_of(db, c.id)
    names = {e.id: e.name for e in ents}
    comms: dict[str, list[Contact]] = {}
    for k in db.scalars(select(Contact).where(Contact.crisis_id == c.id).order_by(Contact.seq.desc())):
        comms.setdefault(k.entity_id, []).append(k)
    rows = []
    for e in ents:
        if not contactable(e):
            continue
        mine = comms.get(e.id, [])
        live = next((k for k in mine if k.status in ("ringing", "in_progress")), None)
        rows.append({
            **entity_dict(e), "kind_label": KIND_LABEL.get(e.kind, e.kind) + (" · descubierta" if e.provenance == "discovered" else ""),
            "zones": [zones.get(z, z) for z in (e.jurisdiction or [])],
            "can": [VERB_LABELS.get(v, v) for v in (e.capabilities or [])],
            "escalates_to_name": names.get(e.escalation_to) if e.escalation_to else None,
            "comms": {"total": len(mine), "unanswered": sum(1 for k in mine if k.status in ("no_answer", "failed")),
                      "live": live.status if live else None, "last": hhmm(c, mine[0].t) if mine else None},
            "communications": [contact_row(c, k) for k in mine],
        })
    # Whoever is on the line comes first, then whoever we talked to last, then by weight.
    rows.sort(key=lambda r: (r["comms"]["live"] is None, -(len(r["communications"]) and 1), -r["weight"], r["name"]))
    return {"contacts": rows,
            "counts": {"all": len(rows), "authority": sum(1 for r in rows if r["kind"] == "authority"),
                       "responder": sum(1 for r in rows if r["kind"] == "responder"),
                       "unreachable": sum(1 for r in rows if r["status"] == "unreachable"),
                       "communications": sum(r["comms"]["total"] for r in rows)}}


def contact_detail(db: Session, c: Crisis, k: Contact) -> dict[str, Any]:
    ent = db.get(Entity, (c.id, k.entity_id))
    act = db.get(Action, (c.id, k.action_id)) if k.action_id else None
    esc = db.get(Entity, (c.id, ent.escalation_to)) if ent and ent.escalation_to else None
    return {**contact_row(c, k), "entity": entity_dict(ent) if ent else None,
            "action": action_item(c, act, _names(db, c.id)) if act else None,
            "escalates_to": esc.name if esc else None}


def plan_screen(db: Session, c: Crisis) -> dict[str, Any]:
    history = list(db.scalars(select(Plan).where(Plan.crisis_id == c.id).order_by(Plan.version.desc()).limit(10)))
    incidents = list(db.scalars(select(Incident).where(Incident.crisis_id == c.id).order_by(Incident.priority)))
    return {"plan": _plan_es(plan_dict(active_plan(db, c.id))), "history": [_plan_es(plan_dict(p)) for p in history],
            "incidents": [incident_dict(i) for i in incidents]}


REASONS_ES = [(r"zone (\S+) severity band (\w+) -> (\w+)", lambda m: f"{m.group(1)} pasa de severidad {BAND_ES.get(m.group(2), m.group(2))} a {BAND_ES.get(m.group(3), m.group(3))}"),
              (r"road cut in ([^;\s]+)", lambda m: f"carretera cortada en {m.group(1)}"),
              (r"entity unreachable: ([^;\s]+)", lambda m: f"{m.group(1)} no contesta"),
              (r"resource exhausted: ([^;\s]+)", lambda m: f"recurso agotado: {m.group(1)}"),
              (r"source went silent: ([^;\s]+)", lambda m: f"fuente en silencio: {m.group(1)}"),
              (r"two more actions failed", lambda m: "dos acciones más han fallado"),
              (r"the hazard is receding everywhere: switch from rescue to recovery", lambda m: "el peligro remite: de rescate a recuperación"),
              (r"human requested a re-plan: ?", lambda m: "replanificación pedida por un humano: ")]
BAND_ES = {"low": "baja", "mid": "media", "high": "alta"}


def reasons_es(text: str | None) -> str:
    """Plan invalidation reasons are written for the LLM (English); the supervisor reads Spanish."""
    import re

    out = text or ""
    for pattern, repl in REASONS_ES:
        out = re.sub(pattern, repl, out)
    return out


def _plan_es(p: dict[str, Any] | None) -> dict[str, Any] | None:
    return {**p, "invalidated_reason_es": reasons_es(p.get("invalidated_reason"))} if p else None


def recent_changes(db: Session, c: Crisis, *, limit: int = 8, zone_ids: list[str] | None = None) -> list[dict[str, Any]]:
    """'What changed in the last few minutes', one line each, newest first: only things that alter the picture."""
    from valte.models import Event

    names = _names(db, c.id)
    zone_names = {z.id: z.name for z in zones_of(db, c.id)}
    rows = db.scalars(select(Event).where(Event.crisis_id == c.id, Event.material.is_(True))
                      .order_by(Event.seq.desc()).limit(limit * 4))
    out: list[dict[str, Any]] = []
    for e in rows:
        p, tone, glyph, text, href = e.payload or {}, "info", "•", "", None
        if e.type == "signal.created":
            if p.get("channel") == "report":
                continue  # told by its report line
            zid = (p.get("location") or {}).get("zone")
            if zone_ids is not None and zid not in zone_ids:
                continue
            sev = max([cl.get("severity_hint", 0) for cl in p.get("claims") or []], default=0)
            tone, glyph = ("critical", "▲") if sev >= 7 else ("warning", "◆") if sev >= 4 else ("info", "•")
            text = f"{names.get(p.get('source'), p.get('source'))} · {zone_names.get(zid, 'sin ubicar')} · severidad {sev}: {(p.get('content') or p.get('summary') or '')[:110]}"
            href = "Senales.dc.html"
        elif e.type == "report.received":
            if zone_ids is not None and p.get("zone") not in zone_ids:
                continue
            sev = int(p.get("severity") or 0)
            tone, glyph, href = ("critical" if sev >= 7 else "warning"), "⚑", "Senales.dc.html"
            text = f"{p.get('by_name')} reporta · {p.get('label')}" + (f" en {p.get('zone_name')}" if p.get("zone_name") else "") \
                + f": {(p.get('text') or '')[:90]}" + (f" → {p['effects'][0]}" if p.get("effects") else "")
        elif e.type == "tripwire.fired":
            cond = p.get("if") or {}
            src = names.get(cond.get("source"), cond.get("source") or "una fuente")
            text = (f"Disparador {p.get('id')}: {src} lleva ≥{cond.get('silence_min')} min en silencio, se asume escalada"
                    if cond.get("type") == "silence" else
                    f"Disparador {p.get('id')}: {src} alcanza severidad ≥{cond.get('min_severity')}"
                    + (f" en {zone_names.get(cond.get('zone'), cond.get('zone'))}" if cond.get("zone") else ""))
            tone, glyph = "agent", "⚡"
        elif e.type == "approval.decided":
            ok = p.get("decision") == "approved"
            text = f"{names.get(p.get('by'), p.get('by'))} {'aprueba' if ok else 'rechaza'} {p.get('action_id')} (vía {p.get('via')})"
            tone, glyph, href = ("success" if ok else "neutral"), ("✓" if ok else "✕"), "Acciones.dc.html"
        elif e.type == "approval.escalated":
            text = f"Aprobación de {p.get('action_id')} escalada a {names.get(p.get('to'), p.get('to'))}: {names.get(p.get('from'), p.get('from'))} no responde"
            tone, glyph, href = "warning", "↗", "Acciones.dc.html"
        elif e.type == "approval.stalled":
            text, tone, glyph, href = f"{p.get('action_id')} no tiene a nadie que la apruebe: decide un humano", "critical", "!", "Acciones.dc.html"
        elif e.type == "plan.replaced":
            text, tone, glyph = f"Nuevo plan v{p.get('version')}: {(p.get('summary') or '')[:120]}", "agent", "↻"
        elif e.type == "plan.invalidated":
            text, tone, glyph = f"Plan v{p.get('version')} invalidado: {reasons_es(p.get('invalidated_reason'))}", "warning", "↻"
        elif e.type == "action.updated" and p.get("status") == "failed":
            text = f"Falla «{VERB_LABELS.get(p.get('verb'), p.get('verb'))}» de {names.get(p.get('actor'), p.get('actor'))}: {p.get('error') or ''}"
            tone, glyph, href = "critical", "!", "Acciones.dc.html"
        elif e.type == "contact.unanswered":
            text, tone, glyph, href = f"{p.get('entity_name')} no contesta ({'llamada' if p.get('channel') == 'voice' else 'email'})", "critical", "✕", "Contactos.dc.html"
        elif e.type == "entity.updated":
            free = (p.get("units") or {}).get("available")
            text = f"{p.get('name')} se queda sin unidades libres" if free == 0 else f"{p.get('name')} ya está operativa ({free} unidades)"
            tone, glyph, href = ("critical" if free == 0 else "success"), "◆", "Recursos.dc.html"
        elif e.type == "resource.updated":
            text, tone, glyph, href = f"{p.get('name')}: quedan {p.get('available', 0):g} de {p.get('total', 0):g}", "warning", "▼", "Recursos.dc.html"
        elif e.type == "check.due":
            text, tone, glyph = f"Revisión programada por el agente: {p.get('note') or ''}", "agent", "◷"
        elif e.type in ("human.action", "human.contact"):
            text, tone, glyph = f"Intervención humana de {names.get(p.get('by'), p.get('by') or 'operador')}", "info", "☝"
        elif e.type == "patrol.result":
            text = f"Ronda proactiva del agente, sin que nadie lo pidiera: {', '.join(p.get('did') or [])}"
            tone, glyph, href = "agent", "◎", "Acciones.dc.html"
        elif e.type == "resupply.arrived":
            text = f"Llega la reposición: +{p.get('qty', 0):g} {p.get('name')} ({p.get('available', 0):g} de {p.get('total', 0):g})"
            tone, glyph, href = "success", "▲", "Recursos.dc.html"
        elif e.type == "needs.retry":
            text, tone, glyph = f"Vuelven {p.get('freed_units')} unidades: se reasignan a lo que seguía esperando", "agent", "↺"
        elif e.type == "crisis.started":
            text, tone, glyph = "Crisis declarada: el sistema empieza a escuchar", "info", "●"
        elif e.digest and "NO FREE UNITS" in e.digest:
            text, tone, glyph, href = "No quedan unidades libres para un aviso grave: el agente tiene que reasignar", "critical", "!", "Recursos.dc.html"
        if text:
            out.append({"seq": e.seq, "time": hhmm(c, e.t), "tone": tone, "glyph": glyph, "text": text, "href": href or "#"})
        if len(out) >= limit:
            break
    return out


def overview(db: Session, c: Crisis, *, role: str = "coordination", entity_id: str | None = None) -> dict[str, Any]:
    """One call per role panel (Coordinación / Autoridad / Respuesta)."""
    names = _names(db, c.id)
    zones, ents = zones_of(db, c.id), entities_of(db, c.id)
    ent = db.get(Entity, (c.id, entity_id)) if entity_id else None
    if ent is None and role != "coordination":
        kind = "authority" if role == "authority" else "responder"
        ent = next((e for e in ents if e.kind == kind and e.role != "coordination"), None)
    scope = (ent.jurisdiction or None) if (ent and role != "coordination") else None

    acts = list(db.scalars(select(Action).where(Action.crisis_id == c.id).order_by(Action.seq.desc()).limit(80)))
    if role == "authority" and ent:
        acts = [a for a in acts if a.actor == ent.id or (a.approval or {}).get("approver") == ent.id]
    elif role == "responder" and ent:
        acts = [a for a in acts if a.actor == ent.id]
    acts.sort(key=lambda a: (a.status != "pending_approval", -a.seq))

    sig_q = select(Signal).where(Signal.crisis_id == c.id)
    if scope:
        sig_q = sig_q.where(Signal.zone_id.in_(scope))
    sigs = list(db.scalars(sig_q.order_by(Signal.seq.desc()).limit(40)))
    if role == "responder":
        sigs = [s for s in sigs if (s.location or {}).get("precision") in ("exact", "street")] or sigs[:6]

    out: dict[str, Any] = {
        "role": role, "entity": entity_dict(ent) if ent else None, "header": header(db, c),
        "kpis": kpis(db, c, zone_ids=scope, entity=ent if role == "responder" else None,
                     viewer=ent if role != "coordination" else None),
        "zones": [zone_view(db, c, z, zones, ents) for z in zones if scope is None or z.id in scope],
        "actions": [action_item(c, a, names) for a in acts[:12]],
        "signals": [signal_item(c, s, names) for s in sigs[:12]],
        "plan": _plan_es(plan_dict(active_plan(db, c.id))),
        "changes": recent_changes(db, c, limit=6, zone_ids=scope),
        "ringing": [contact_row(c, k) for k in db.scalars(select(Contact).where(
            Contact.crisis_id == c.id, Contact.status.in_(("ringing", "in_progress"))))
                    if role == "coordination" or (ent and k.entity_id == ent.id)],
    }
    if ent:
        esc = db.get(Entity, (c.id, ent.escalation_to)) if ent.escalation_to else None
        out["capabilities"] = [{"verb": v, "label": VERB_LABELS.get(v, v)}
                               for v in (ent.capabilities or [])]
        out["escalates_to"] = esc.name if esc else None
    if ent is not None and role != "coordination":  # what this entity itself holds, nothing else
        out["supplies"] = [resource_dict(r) for r in resources_of(db, c.id) if r.owner_entity_id == ent.id]
    return out
