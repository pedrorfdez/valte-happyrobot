"""Rule-based stand-in for the HappyRobot brains.

Used when HappyRobot is not provisioned or does not answer, and in tests.
It follows the same doctrine in the dumbest possible way and goes through
the same pipeline, so an outage degrades the demo instead of stopping it.
Everything it does is labelled origin=local-brain.
"""

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from valte.core import actions, plan
from valte.core.playbook import alert_copy
from valte.core.world import active_plan, entities_of, zones_of
from valte.models import Crisis, Signal, Zone


def _downstream(zones: dict[str, Zone], zid: str, seen: set[str] | None = None) -> list[str]:
    seen = seen if seen is not None else set()
    for e in zones[zid].downstream or []:
        if e["to"] in zones and e["to"] not in seen:
            seen.add(e["to"])
            _downstream(zones, e["to"], seen)
    return sorted(seen)


def decide(db: Session, c: Crisis) -> dict[str, Any]:
    zones = {z.id: z for z in zones_of(db, c.id)}
    ents = entities_of(db, c.id)
    coord = next((e for e in ents if e.role == "coordination"), None)
    proposals: list[dict[str, Any]] = []

    def evidence(zid: str) -> list[str]:
        return [s.id for s in db.scalars(select(Signal).where(
            Signal.crisis_id == c.id, Signal.zone_id == zid, Signal.is_noise.is_(False))
            .order_by(Signal.severity_hint.desc(), Signal.seq.desc()).limit(3))]

    worst = max((z.severity_est for z in zones.values()), default=0)
    if coord and worst >= 4:
        level = 2 if worst >= 7 else 1
        if c.emergency_level < level:
            z = max(zones.values(), key=lambda z: z.severity_est)
            proposals.append({"actor": coord.id, "verb": "activate_emergency_level", "target_zones": [],
                              "params": {"level": level}, "evidence": evidence(z.id),
                              "reasoning": f"{z.name} alcanza severidad {z.severity_est}: nivel {level}."})
    for z in zones.values():
        if z.severity_est < 7 or coord is None:
            continue
        targets = [t for t in [z.id, *_downstream(zones, z.id)] if not zones[t].warned]
        if targets and "send_es_alert" in coord.capabilities:
            reasoning = f"Severidad {z.severity_est} en {z.name}: aviso a la zona y a todo lo que tiene aguas abajo antes de que llegue."
            if c.hazard_type == "fire":
                reasoning = f"Severidad {z.severity_est} en {z.name}: aviso a la zona y a lo que el fuego tiene a sotavento."
            elif c.hazard_type == "blackout":
                reasoning = f"Severidad {z.severity_est} en {z.name}: aviso a la zona y a lo que se quedará sin luz a continuación."
            proposals.append({"actor": coord.id, "verb": "send_es_alert", "target_zones": targets,
                              "params": {"message": alert_copy(c.hazard_type)},
                              "evidence": evidence(z.id), "reasoning": reasoning})
        if "request_ume" in coord.capabilities:
            proposals.append({"actor": coord.id, "verb": "request_ume", "target_zones": [], "params": {},
                              "evidence": evidence(z.id),
                              "reasoning": "La UME tarda 180 minutos en estar operativa: se pide ya."})

    for z in zones.values():
        if c.hazard_type in ("blackout", "mci"):
            continue  # playbook: do not evacuate a whole town for an outage or a crash
        imminent = z.eta_min is not None and z.eta_min <= 40 and z.base_at_risk_pct >= 25
        if (imminent or z.severity_est >= 7) and not z.evacuating:
            auth = next((e for e in ents if e.kind == "authority" and e.role != "coordination"
                         and z.id in (e.jurisdiction or []) and "order_evacuation" in e.capabilities), None)
            up = [u for u in zones.values() if any(d["to"] == z.id for d in u.downstream or [])]
            ev = evidence(z.id) or [i for u in up for i in evidence(u.id)][:3]
            if auth and ev:
                proposals.append({"actor": auth.id, "verb": "order_evacuation", "target_zones": [z.id], "params": {},
                                  "evidence": ev, "reasoning": f"El pico llega a {z.name} en {z.eta_min or 0} min y tiene {z.base_at_risk_pct:.0f}% de población en cota baja."})

    # Demand meets supply: every open need gets the nearest responder that still has units, worst first.
    from valte.core.needs import open_needs, pick_responder

    for need in open_needs(db, c):
        if need["confidence"] == "low" and need["severity"] < 8:
            continue  # a lone unverified report does not move scarce units
        verb = need["suggested_verb"]
        units = 3 if need["severity"] >= 9 else 2 if verb == "rescue" else 1
        resp = pick_responder(db, c, verb, need["zone"], units) or pick_responder(db, c, verb, need["zone"], 1, reserve=0)
        if resp is None:
            continue
        units = min(units, resp.units_available or 1)
        proposals.append({"actor": resp.id, "verb": verb, "target_zones": [need["zone"]], "params": {"units": units},
                          "evidence": [need["signal_id"]],
                          "reasoning": f"«{need['what'][:110].rstrip()}{'…' if len(need['what']) > 110 else ''}» Severidad {need['severity']}, {need['waiting_min']} min esperando: "
                                       f"{units} unidad(es) de {resp.name}, el recurso más cercano con unidades libres."})

    return actions.submit_decisions(
        db, c, proposals, origin="local-brain",
        situation_note=f"[cerebro local] Severidad máxima {worst}. {len(proposals)} acciones propuestas.")


HAZARD_ES = {"flood": "Inundación", "fire": "Incendio", "blackout": "Apagón", "infra": "Fallo de infraestructura",
             "mci": "Víctimas múltiples"}


def make_plan(db: Session, c: Crisis) -> None:
    zones = sorted(zones_of(db, c.id), key=lambda z: (-z.severity_est, z.eta_min if z.eta_min is not None else 999))
    incidents, objectives = [], []
    for z in zones:
        threat = z.severity_est >= 4 or z.eta_min is not None
        if not threat:
            continue
        prio = "P0" if z.severity_est >= 7 else "P1" if (z.severity_est >= 4 or (z.eta_min or 99) <= 40) else "P2"
        ev = [s.id for s in db.scalars(select(Signal).where(Signal.crisis_id == c.id, Signal.zone_id == z.id,
                                                          Signal.is_noise.is_(False)).order_by(Signal.seq.desc()).limit(3))]
        incidents.append(z.id)
        objectives.append({"priority": prio, "zone_ids": [z.id],
                           "objective": ("Rescatar y contener" if z.severity_est >= 7 else "Avisar y evacuar antes del pico"),
                           "suggested_verb": "rescue" if z.severity_est >= 7 else "send_es_alert"})
    if not incidents:
        return
    old = active_plan(db, c.id)
    plan.replace_plan(db, c, {"plan": {
        "summary": ("Replanificación: " + old.invalidated_reason + ". " if old and old.invalidated_reason else "")
        + "Prioridad a las zonas con agua ya dentro; aguas abajo, avisar antes de que llegue.",
        "objectives": objectives}}, origin="local-brain")
