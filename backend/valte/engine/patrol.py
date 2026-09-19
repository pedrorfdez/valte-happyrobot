"""The proactive brain: nothing wakes it, it does the rounds.

The coordinator reacts: a material event arrives, it decides. Whatever
produces no event is nobody's job — a calm zone whose countdown keeps
running with no alert sent, an evacuation with nowhere to lodge people,
crews parked in a zone that calmed down while a rescue waits elsewhere,
pumps running out at one entity while another has plenty.

Every `VALTE_PROACTIVE_EVERY_S` seconds the kernel sweeps each running
crisis for that kind of thing and hands the findings, with the full state,
to PedroD-proactive. Its answer goes through the same pipeline as every
other decision (validation, approvals, real contacts) with
origin=proactive. A round only costs a HappyRobot run when the sweep found
something new, plus a quiet round now and then: rules do not see everything.
Without HappyRobot the suggested actions of the sweep are applied as they are.
"""

import json
import math
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from valte.core import actions, logistics
from valte.core.events import append_event
from valte.core.needs import open_needs, pick_responder
from valte.core.world import VERB_LABELS, build_state, entities_of, resources_of, scenario_now, zones_of
from valte.hr import registry
from valte.models import Action, Crisis, Entity, Outbox, Signal, Zone, utcnow
from valte.settings import public_base_url, settings

TIMEOUT_S = 60
QUIET_EVERY = 4      # nothing new to report: still think every N rounds
MAX_RUNS = 60        # credit guard per crisis
MAX_ACTIONS = 5      # per round
REMEMBER_ROUNDS = 6  # a finding handed over this recently is `seen_before`
WARN_ETA_MIN, SHELTER_ETA_MIN, STALE_NEED_MIN, RECALL_AFTER_MIN = 45, 40, 15, 10
LOW_STOCK = 0.25
CLOSED = ("executed", *actions.TERMINAL_BAD)
PRIORITY = {"high": 0, "medium": 1, "low": 2}
HAZARD_ES = {"flood": "riada", "fire": "incendio", "blackout": "apagón", "infra": "fallo de infraestructura",
             "mci": "incidente con múltiples víctimas"}


def _age(iso: str | None) -> float:
    return (utcnow() - datetime.fromisoformat(iso)).total_seconds() if iso else 1e9


def done(c: Crisis) -> None:
    c.wake = {k: v for k, v in (c.wake or {}).items() if k not in ("patrol_inflight", "patrol_since")}


# ── the sweep: what a duty officer would notice with nobody asking ───────


def _who_can(ents: list[Entity], verb: str, zone: str | None, prefer_role: str = "") -> Entity | None:
    """Whoever is closest to the zone, unless a role is preferred (one alert from the coordination centre beats six)."""
    options = [e for e in ents if verb in (e.capabilities or []) and e.status != "unreachable"
               and (not e.jurisdiction or zone is None or zone in e.jurisdiction)]
    return min(options, key=lambda e: (e.role != prefer_role, len(e.jurisdiction or []) or 99, -e.weight), default=None)


def _evidence(db: Session, c: Crisis, zones: dict[str, Zone], zid: str) -> list[str]:
    """The strongest reports from the zone; for a zone that is still calm, from whatever is upstream of it."""
    def top(z: str) -> list[str]:
        return [s.id for s in db.scalars(select(Signal).where(Signal.crisis_id == c.id, Signal.zone_id == z,
                                                              Signal.is_noise.is_(False))
                                         .order_by(Signal.severity_hint.desc(), Signal.seq.desc()).limit(3))]

    upstream = [u.id for u in zones.values() if any(d["to"] == zid for d in u.downstream or [])]
    return top(zid) or [i for u in upstream for i in top(u)][:3]


def sweep(db: Session, c: Crisis) -> list[dict[str, Any]]:
    now_s = scenario_now(c)
    zones = {z.id: z for z in zones_of(db, c.id)}
    ents = entities_of(db, c.id)
    stock = resources_of(db, c.id)
    acts = list(db.scalars(select(Action).where(Action.crisis_id == c.id)))
    needs = open_needs(db, c)
    hazard = HAZARD_ES.get(c.hazard_type, "emergencia")
    found: list[dict[str, Any]] = []

    def in_motion(verb: str, zone: str | None = None) -> bool:
        return any(a.verb == verb and a.status not in CLOSED and (zone is None or zone in (a.target_zones or [])) for a in acts)

    def add(kind: str, subject: str, priority: str, what: str, proposal: dict[str, Any] | None = None) -> None:
        fid = f"pat-{kind}-{subject}"
        if proposal is not None:
            proposal["evidence"] = proposal.get("evidence") or [fid]
        found.append({"id": fid, "priority": priority, "what": what, "suggested_action": proposal})

    # 1 · zones in the path of the hazard that nobody has warned: one alert per sender, not one per zone
    unwarned: dict[str, list[Zone]] = {}
    for z in zones.values():
        threatened = z.severity_est >= 5 or (z.eta_min is not None and z.eta_min <= WARN_ETA_MIN)
        if z.warned or not threatened or in_motion("send_es_alert", z.id) or in_motion("order_evacuation", z.id):
            continue
        who = _who_can(ents, "send_es_alert", z.id, "coordination")
        unwarned.setdefault(who.id if who else "", []).append(z)
    for who_id, group in unwarned.items():
        group.sort(key=lambda z: z.eta_min if z.eta_min is not None else 0)
        names = ", ".join(z.name for z in group)
        when = "; ".join(f"{z.id} ({z.population} people): " + (f"arrives in {z.eta_min} min" if z.eta_min else f"severity {z.severity_est}, already affected")
                         for z in group)
        ev = list(dict.fromkeys(i for z in group for i in _evidence(db, c, zones, z.id)))[:4]
        add("aviso", "-".join(sorted(z.id for z in group)), "high", f"Not warned and in the path of the hazard — {when}.",
            {"actor": who_id, "verb": "send_es_alert", "target_zones": [z.id for z in group], "evidence": ev, "params": {
                "message": f"Aviso de Protección Civil para {names}: {hazard} en curso, puede alcanzar su zona en los próximos minutos. "
                           "Siga las indicaciones de las autoridades, evite desplazamientos y aléjese de las zonas de riesgo."},
             "reasoning": f"Ronda proactiva: {names} sigue{'n' if len(group) > 1 else ''} sin aviso"
                          + "".join(f"; a {z.name} llega en {z.eta_min} min" for z in group if z.eta_min)[:160]
                          + ". Nadie lo había pedido: donde aún no ha pasado nada no salta ningún evento."} if who_id else None)

    # 2 · people about to be moved and nowhere to lodge them
    for z in zones.values():
        moving = z.evacuating or in_motion("order_evacuation", z.id)
        soon = z.eta_min is not None and z.eta_min <= SHELTER_ETA_MIN and z.base_at_risk_pct >= 25
        if not (moving or soon) or in_motion("open_shelter", z.id):
            continue
        owners = {e.id for e in ents if not e.jurisdiction or z.id in e.jurisdiction}
        if any(r.id.startswith("plazas-albergue") and r.available > 0 and r.owner_entity_id in owners for r in stock):
            continue
        who, ev = _who_can(ents, "open_shelter", z.id), _evidence(db, c, zones, z.id)
        places = int(max(100, min(1500, math.ceil(z.population * z.base_at_risk_pct / 100 * 0.1 / 50) * 50)))
        add("albergue", z.id, "medium",
            f"{z.id} is {'being evacuated' if moving else f'{z.eta_min} min from the hazard with {z.base_at_risk_pct:.0f}% of its people at risk'} "
            f"and there are no shelter places left for it.",
            who and {"actor": who.id, "verb": "open_shelter", "target_zones": [z.id], "params": {"capacity": places}, "evidence": ev,
                     "reasoning": f"Ronda proactiva: {z.name} {'se está evacuando' if moving else 'va a necesitar evacuar'} y no quedan "
                                  f"plazas de albergue. Se abren {places} antes de que la gente esté en la calle."})

    # 3 · a need that fell through: it has waited too long and someone could go
    starved = []
    for n in needs:
        if n["confidence"] == "low" and n["severity"] < 8:
            continue
        verb = n["suggested_verb"]
        units = 3 if n["severity"] >= 9 else 2 if verb == "rescue" else 1
        resp = pick_responder(db, c, verb, n["zone"], units) or pick_responder(db, c, verb, n["zone"], 1, reserve=0)
        if resp is None:
            starved.append(n)
        elif n["waiting_min"] >= STALE_NEED_MIN:
            units = min(units, resp.units_available or 1)
            add("espera", n["signal_id"], "high" if n["severity"] >= 8 else "medium",
                f"{n['signal_id']} ({n['zone']}, severity {n['severity']}) has waited {n['waiting_min']} min with nobody assigned; "
                f"{resp.id} has {resp.units_available} free units.",
                {"actor": resp.id, "verb": verb, "target_zones": [n["zone"]], "params": {"units": units}, "evidence": [n["signal_id"]],
                 "reasoning": f"Ronda proactiva: «{n['what'][:100].rstrip()}» lleva {n['waiting_min']} min sin nadie asignado. "
                              f"Van {units} unidad(es) de {resp.name}."})

    # 4 · crews that would be more useful elsewhere
    def job_severity(a: Action) -> int:
        return max([s.severity_hint for s in (db.get(Signal, (c.id, e)) for e in a.evidence or []) if s] or [0])

    held = [a for a in acts if a.status == "executed" and (a.reserved or {}).get("units") and not a.reserved.get("released")]
    for a in held:
        where = [zones[z] for z in a.target_zones or [] if z in zones]
        actor = next((e for e in ents if e.id == a.actor), None)
        minutes = int((now_s - a.t).total_seconds() // 60)
        calm = bool(where) and all(z.severity_est <= 3 and z.trend != "rising" for z in where)
        if calm and minutes >= RECALL_AFTER_MIN and (needs or (actor and not actor.units_available)):
            add("retirada", a.id, "low",
                f"{a.id}: {a.reserved['units']} unit(s) of {a.actor} have been in {a.target_zones} for {minutes} min and the zone is "
                f"down to severity {max(z.severity_est for z in where)} while {len(needs)} need(s) wait.",
                {"actor": "system", "verb": "recall_units", "target_zones": a.target_zones, "params": {"action_id": a.id},
                 "evidence": [a.id], "reasoning": f"Ronda proactiva: {', '.join(z.name for z in where)} se ha calmado y "
                                                  f"{actor.name if actor else a.actor} hace falta en otro sitio. Vuelven {a.reserved['units']} unidad(es)."})
    for n in starved:
        if n["severity"] < 8:
            continue
        can_go = {e.id for e in ents if n["suggested_verb"] in (e.capabilities or []) and (not e.jurisdiction or n["zone"] in e.jurisdiction)}
        lesser = sorted((a for a in held if a.actor in can_go and job_severity(a) <= n["severity"] - 2), key=job_severity)
        if lesser:
            a = lesser[0]
            add("reasignar", n["signal_id"], "high",
                f"{n['signal_id']} ({n['zone']}, severity {n['severity']}) waits and nobody who can go has free units; "
                f"{a.id} keeps {a.reserved['units']} unit(s) of {a.actor} on a severity-{job_severity(a)} job.",
                {"actor": "system", "verb": "recall_units", "target_zones": a.target_zones, "params": {"action_id": a.id},
                 "evidence": [n["signal_id"], a.id],
                 "reasoning": f"Ronda proactiva: hay un aviso de severidad {n['severity']} sin nadie libre y {a.id} ocupa "
                              f"{a.reserved['units']} unidad(es) en algo menos grave. Se retiran para reasignarlas."})

    # 5 · stock about to run out: lend it from whoever has plenty, or ask for more before it is gone
    on_its_way = {d["resource"] for d in logistics.deliveries(c)}
    for r in stock:
        if not r.total or r.available / r.total > LOW_STOCK or r.id in on_its_way or r.id.startswith("plazas-albergue"):
            continue
        lender = max((d for d in stock if d.name == r.name and d.owner_entity_id != r.owner_entity_id
                      and d.available - d.total * logistics.LENDER_FLOOR >= 1), key=lambda d: d.available, default=None)
        if lender is not None:
            qty = math.floor(min(lender.available - lender.total * logistics.LENDER_FLOOR, r.total - r.available))
            proposal = {"actor": "system", "verb": "transfer_resource", "target_zones": [],
                        "params": {"resource": lender.id, "to": r.owner_entity_id, "qty": qty},
                        "reasoning": f"Ronda proactiva: a {r.owner_entity_id} le quedan {r.available:g} de {r.total:g} {r.name.lower()} y "
                                     f"{lender.owner_entity_id} tiene {lender.available:g}. Se mueven {qty:g} antes de que se agoten."}
        else:
            qty = math.ceil(r.total / 2)
            proposal = {"actor": "system", "verb": "request_resupply", "target_zones": [],
                        "params": {"resource": r.id, "qty": qty, "eta_min": 30},
                        "reasoning": f"Ronda proactiva: quedan {r.available:g} de {r.total:g} {r.name.lower()} y nadie más tiene. "
                                     f"Se piden {qty:g} fuera ahora: tardan en llegar."}
        add("stock", r.id, "medium", f"{r.id} ({r.owner_entity_id}) is down to {r.available:g}/{r.total:g}"
                                     + (f"; {lender.id} ({lender.owner_entity_id}) has {lender.available:g}." if lender else " and no other entity holds any."),
            proposal)

    # 6 · a zone that keeps getting worse and nobody left to send
    for z in zones.values():
        if z.severity_est < 6 or z.trend == "falling":
            continue
        local = [e for e in ents if e.kind == "responder" and e.units_total is not None and e.status != "unreachable"
                 and (not e.jurisdiction or z.id in e.jurisdiction)]
        if sum(e.units_available or 0 for e in local) >= 2:
            continue
        far = next((e for e in local if (e.activation or {}).get("delay_min", 0) >= 60 and not e.units_available
                    and not (e.extra or {}).get("arrives_t")), None)
        who = _who_can(ents, "request_ume", None, "coordination")
        proposal = None
        if far is not None and who is not None and not in_motion("request_ume") \
                and not any(a.verb == "request_ume" and a.status == "executed" for a in acts):
            proposal = {"actor": who.id, "verb": "request_ume", "target_zones": [], "params": {}, "evidence": _evidence(db, c, zones, z.id),
                        "reasoning": f"Ronda proactiva: en {z.name} (severidad {z.severity_est}) no queda casi nadie libre y {far.name} "
                                     f"tarda {far.activation.get('delay_min')} min en estar operativa. Se pide ya."}
        add("sin-unidades", z.id, "high", f"{z.id} is at severity {z.severity_est} ({z.trend}) and the responders that cover it have "
                                          f"fewer than 2 free units between them.", proposal)

    # 7 · loose ends only a person or a different route can close
    for a in acts:
        if a.status == "pending_approval" and (a.approval or {}).get("stalled"):
            add("firma", a.id, "medium", f"{a.id} ({a.verb} on {a.target_zones}) has nobody left to approve it. Consider another "
                                         f"actor whose own authority covers it, or a lesser measure that needs no signature.")
    for e in ents:
        if e.status == "unreachable" and (e.units_available or 0) > 0:
            add("incomunicada", e.id, "medium", f"{e.id} does not answer and still holds {e.units_available} free units: do not count "
                                                f"on them; its escalation_to is {e.escalation_to}.")

    found.sort(key=lambda f: PRIORITY[f["priority"]])
    return found[:10]


# ── the round ────────────────────────────────────────────────────────────


def maybe_patrol(db: Session, c: Crisis) -> None:
    every = settings.valte_proactive_every_s
    if every <= 0:
        return
    w = dict(c.wake or {})
    if not w.get("patrol_last"):  # the first round comes one interval after the crisis starts moving
        c.wake = {**w, "patrol_last": utcnow().isoformat()}
        return
    if w.get("patrol_inflight"):
        if _age(w.get("patrol_since")) < TIMEOUT_S:
            return
        append_event(db, c, "hr.error", {"what": "proactive did not answer", "dispatch": w["patrol_inflight"]})
        done(c)
        w = dict(c.wake)
    if _age(w["patrol_last"]) < every:
        return

    rnd = int(w.get("patrol_round", 0)) + 1
    seen = {k: int(v) for k, v in (w.get("patrol_seen") or {}).items() if rnd - int(v) <= REMEMBER_ROUNDS}
    found = sweep(db, c)
    for f in found:
        f["seen_before"] = f["id"] in seen
    fresh = [f for f in found if not f["seen_before"]]
    use_hr = registry.usable(db, registry.PROACTIVE) and int(w.get("patrol_runs", 0)) < MAX_RUNS
    quiet_round = use_hr and rnd - int(w.get("patrol_thought", 0)) >= QUIET_EVERY
    w.update(patrol_last=utcnow().isoformat(), patrol_round=rnd)
    if not fresh and not quiet_round:
        c.wake = w
        return

    w.update(patrol_thought=rnd, patrol_seen={**seen, **{f["id"]: rnd for f in found}})
    dispatch_id = f"pat-{uuid.uuid4().hex[:10]}"
    append_event(db, c, "patrol.round", {"dispatch_id": dispatch_id, "round": rnd, "via": "happyrobot" if use_hr else "local",
                                        "findings": [{k: f[k] for k in ("id", "priority", "what", "seen_before")} for f in found]})
    if not use_hr:
        c.wake = w
        _local_round(db, c, found, rnd)
        return
    w.update(patrol_inflight=dispatch_id, patrol_since=utcnow().isoformat(), patrol_runs=int(w.get("patrol_runs", 0)) + 1)
    c.wake = w
    db.add(Outbox(crisis_id=c.id, kind="hr_run", workflow=registry.PROACTIVE, purpose="proactive", ref_id=dispatch_id, payload={
        "crisis_id": c.id, "dispatch_id": dispatch_id, "callback_base": public_base_url(), "round": rnd,
        "instruction": (f"{len(fresh)} new finding(s), {len(found) - len(fresh)} already seen." if found else
                        "The sweep found nothing: look at the state yourself for what is about to be needed.")
                       + " Output only new actions.",
        "findings_json": json.dumps(found, ensure_ascii=False),
        "state_json": json.dumps(build_state(db, c), ensure_ascii=False)}))


def _local_round(db: Session, c: Crisis, found: list[dict[str, Any]], rnd: int) -> None:
    proposals = [f["suggested_action"] for f in found if f["suggested_action"] and not f.get("seen_before")]
    if proposals:  # rules are cheap and already validated: no cap
        apply_result(db, c, {"actions": proposals, "patrol_note": f"[ronda local {rnd}] {len(found)} hallazgo(s)."},
                     via="local", cap=len(proposals))


def fallback(db: Session, c: Crisis) -> None:
    """HappyRobot could not do this round: the sweep's own suggestions are better than nothing."""
    done(c)
    found = sweep(db, c)
    _local_round(db, c, found, int((c.wake or {}).get("patrol_round", 0)))


def apply_result(db: Session, c: Crisis, decisions: dict[str, Any], *, via: str = "happyrobot",
                 cap: int = MAX_ACTIONS) -> dict[str, Any]:
    done(c)
    proposed = [a for a in (decisions.get("actions") or []) if isinstance(a, dict)][:cap]
    res = actions.submit_decisions(db, c, proposed, origin="proactive")
    did = [proposed[r["index"]] for r in res["results"] if not r.get("error")]
    note = str(decisions.get("patrol_note") or "")[:600]
    lines = [f"{a.get('verb')} by {a.get('actor')}" + (f" on {a['target_zones']}" if a.get("target_zones") else "")
             + (f" {json.dumps(a['params'], ensure_ascii=False)}" if a.get("verb") in logistics.VERBS else "") for a in did]
    append_event(db, c, "patrol.result", {
        "via": via, "note": note, "accepted": res["accepted"], "rejected": res["rejected"], "results": res["results"],
        "did": [VERB_LABELS.get(str(a.get("verb")), str(a.get("verb"))) for a in did]},
        # Only a round that changed the world is worth a coordinator wake-up.
        material=bool(did), digest=("The proactive round acted on its own: " + "; ".join(lines) + ". Do not repeat it; "
                                    "use the units or stock it freed if needs still wait.") if did else None)
    return res
