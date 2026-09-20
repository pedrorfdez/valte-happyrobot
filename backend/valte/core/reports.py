"""Incident channel: the system's own actors tell it what they see.

A town hall reporting "the CV-36 bridge has just collapsed" is not one more
message to be perceived and doubted: it is a trusted, located fact, and it
has consequences. Each report becomes a high-trust signal (so the brains,
the open needs and the reflexes all see it) and its kind-specific effects
are applied at once: access to the zone gets slower, stock disappears,
units drop out, a shelter stops taking people. The plan dies if the picture
changed, and the coordinator is woken with what was done.

Whoever reports only gives a name ("se hunde el puente de la CV-36 en
Paiporta") and a kind. Where it is, which stock and how many are worked out
of that name here; the API still takes them explicitly for scripted callers.

The same channel also takes what has CHANGED and not just what is broken
(`core/changes.py`): a zone nobody had listed, stock that arrives, a
volunteer group that turns up with its own material, an action a person
already took by themselves. The plan is always behind the street, and this
is how the street corrects it.

The population reports through the same channel, but a neighbour is a lead,
not a fact: the signal comes in with the low trust of its source, nothing is
applied to the world, and it only weighs more once other sources corroborate
it (the kernel's usual confidence rule).
"""

import re
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from valte.core import changes
from valte.core.events import append_event
from valte.core.signals import upsert_signal
from valte.core.world import (
    entities_of,
    entity_dict,
    hhmm,
    next_id,
    resolve_zone,
    resource_dict,
    resources_of,
    scenario_now,
    slugify,
    zone_dict,
    zones_of,
)
from valte.models import Crisis, Entity, Report, Resource, Signal, Zone

ACCESS_STEP_MIN, ACCESS_MAX_MIN = 15, 45

NUMBER_WORDS = {"dos": 2, "tres": 3, "cuatro": 4, "cinco": 5, "seis": 6, "siete": 7, "ocho": 8, "nueve": 9, "diez": 10}
ZONE_KINDS = ("road_cut", "people_trapped", "building_damage", "power_out", "shelter_full")  # mean nothing without a zone
CIVILIAN_KINDS = ("road_cut", "people_trapped", "building_damage", "power_out", "other")  # what a neighbour can witness
# Changes to the world model instead of damage to report (core/changes.py). Only the apparatus, never a neighbour.
WORLD_KINDS = ("zone_new", "resource_new", "entity_new", "action_done")
# ...of which these are not an incident at all: no signal, no need, just the change and its digest.
SILENT_KINDS = ("resource_new", "entity_new", "action_done")
CONFIDENCE_ES = {"low": "baja", "medium": "media", "high": "alta"}

# kind -> label, default severity, claim ("hazard" = the crisis's own), which details it takes ("place": the name is the spot)
KINDS: dict[str, dict[str, Any]] = {
    "road_cut": {"label": "Carretera cortada o hundida", "severity": 7, "claim": "road_cut", "needs": ["place"],
                 "hint": "El acceso a la zona se ralentiza para quien venga de fuera y las unidades tardan más en volver."},
    "people_trapped": {"label": "Personas atrapadas", "severity": 9, "claim": "hazard", "needs": ["place"],
                       "hint": "Entra como aviso de máxima prioridad: salen unidades en el acto."},
    "building_damage": {"label": "Edificio dañado o colapsado", "severity": 8, "claim": "hazard", "needs": ["place"],
                        "hint": "Aviso grave con ubicación: el sistema asigna rescate."},
    "power_out": {"label": "Sin luz o sin comunicaciones", "severity": 5, "claim": "blackout", "needs": [],
                  "hint": "La zona queda marcada; el agente revisa a las personas dependientes."},
    "resource_lost": {"label": "Recurso perdido o agotado", "severity": 4, "claim": "resource_loss", "needs": ["resource", "qty"],
                      "hint": "Se descuenta del inventario de su propietario."},
    "units_down": {"label": "Unidades fuera de servicio", "severity": 5, "claim": "resource_loss", "needs": ["units"],
                   "hint": "Se descuentan de tus unidades disponibles."},
    "shelter_full": {"label": "Albergue lleno", "severity": 5, "claim": "shelter_full", "needs": [],
                     "hint": "Las plazas de albergue de la zona pasan a cero."},
    "other": {"label": "Otra incidencia", "severity": 5, "claim": "hazard", "needs": [],
              "hint": "Entra como aviso fiable para el agente."},
    # ── what has changed in the dispositivo, not what is broken ──
    "zone_new": {"label": "Zona afectada nueva", "severity": 6, "claim": "hazard", "needs": ["zone_name", "population"],
                 "hint": "Entra en el mapa aguas abajo de la tuya, con su ayuntamiento y sus vecinos, y empieza a contar su llegada."},
    "resource_new": {"label": "Llegan recursos (o corregir existencias)", "severity": 2, "claim": "logistics", "needs": ["resource", "qty"],
                     "hint": "Se suman a tu inventario; si dices «solo quedan…» se corrige la cuenta."},
    "entity_new": {"label": "Se suma quien ayuda", "severity": 2, "claim": "logistics", "needs": ["entity", "units"],
                   "hint": "Queda registrada con sus unidades y su material, y el agente ya puede darle trabajo."},
    "action_done": {"label": "Ya lo hemos hecho", "severity": 3, "claim": "logistics", "needs": ["verb"],
                    "hint": "Queda como acción tuya ya ejecutada: el agente deja de pedirla y cuenta con ella."},
}
GROUP = {k: ("world" if k in WORLD_KINDS else "incident") for k in KINDS}


class BadReport(ValueError):
    pass


def reliability(reporter: Entity | None) -> str:
    """An authority or a responder states a fact; a neighbour gives a lead that has to be corroborated."""
    return "low" if reporter is not None and reporter.kind == "population" else "high"


def kinds(reporter: Entity | None = None) -> list[dict[str, Any]]:
    """`group`: incident = something is broken; world = the dispositivo changed and the model has to follow."""
    civilian = reliability(reporter) == "low"
    return [{"id": k, **{x: v[x] for x in ("label", "severity", "needs")}, "group": GROUP[k],
             "hint": "Entra como aviso ciudadano de fiabilidad baja: pesa más cuando otra fuente lo corrobora." if civilian else v["hint"]}
            for k, v in KINDS.items() if not civilian or k in CIVILIAN_KINDS]


def report_dict(c: Crisis, r: Report, names: dict[str, str] | None = None, zones: dict[str, str] | None = None, *,
                reporter: Entity | None = None, signal: Signal | None = None) -> dict[str, Any]:
    return {"id": r.id, "time": hhmm(c, r.t), "t": r.t.isoformat(), "by": r.by, "by_name": (names or {}).get(r.by, r.by),
            "kind": r.kind, "label": KINDS.get(r.kind, KINDS["other"])["label"], "zone": r.zone_id,
            "zone_name": (zones or {}).get(r.zone_id or "", r.zone_id), "place": r.place, "text": r.text,
            "severity": r.severity, "signal_id": r.signal_id, "effects": r.effects,
            # reliability: what the reporter is; confidence: where the signal stands now (corroboration moves it)
            "reliability": reliability(reporter), "confidence": signal.confidence if signal else None}


def list_reports(db: Session, c: Crisis, *, by: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
    ents = {e.id: e for e in entities_of(db, c.id)}
    names = {e.id: e.name for e in ents.values()}
    zones = {z.id: z.name for z in zones_of(db, c.id)}
    q = select(Report).where(Report.crisis_id == c.id)
    if by:
        q = q.where(Report.by == by)
    rows = list(db.scalars(q.order_by(Report.t.desc(), Report.id.desc()).limit(limit)))
    sigs = {s.id: s for s in db.scalars(select(Signal).where(
        Signal.crisis_id == c.id, Signal.id.in_([r.signal_id for r in rows if r.signal_id])))}
    return [report_dict(c, r, names, zones, reporter=ents.get(r.by), signal=sigs.get(r.signal_id or "")) for r in rows]


def _number_in(text: str) -> int | None:
    """'Cinco dotaciones aisladas' -> 5, 'perdemos 4 bombas' -> 4; the 36 of 'CV-36' is not a quantity."""
    for w in re.findall(r"(?<![\w-])(?:\d+|[a-z]+)(?![\w-])", text.lower()):
        n = int(w) if w.isdigit() else NUMBER_WORDS.get(w)
        if n:
            return n
    return None


def _zone_for(db: Session, c: Crisis, reporter: Entity, text: str, *, needed: bool,
              newest_added: bool = False) -> str | None:
    """The zone the name mentions, else the reporter's own town, else (if the kind needs one) the worst-off zone it answers for."""
    mine = [z for z in zones_of(db, c.id) if not reporter.jurisdiction or z.id in reporter.jurisdiction]
    hay = f"-{slugify(text)}-"
    named = next((z.id for z in mine if f"-{slugify(z.name)}-" in hay), None)
    if named or len(reporter.jurisdiction or []) == 1:
        return named or reporter.jurisdiction[0]  # a town hall talks about its own town
    # "está aislada" right after adding a town: that town, not the origin that is already worst-off.
    if newest_added:
        added = [z for z in mine if "Añadida sobre la marcha" in (z.notes or "")]
        if added:
            return max(added, key=lambda z: z.sort_index or 0).id
    return max(mine, key=lambda z: z.severity_est).id if needed and mine else None


def _isolate(db: Session, c: Crisis, z: Zone, note: str, effects: list[str]) -> None:
    penalty = min(ACCESS_MAX_MIN, int((z.extra or {}).get("access_penalty_min", 0)) + ACCESS_STEP_MIN)
    z.extra = {**(z.extra or {}), "road_cut": note[:120], "access_penalty_min": penalty}
    effects.append(f"Acceso a {z.name}: +{penalty} min para las unidades que vienen de fuera, y tardan {penalty} min más en quedar libres")
    append_event(db, c, "zone.updated", zone_dict(z))


def _resource_named_in(db: Session, c: Crisis, reporter: Entity, text: str) -> Resource:
    own = [r for r in resources_of(db, c.id) if reporter.role == "coordination" or r.owner_entity_id in (None, reporter.id)]
    words = slugify(text).split("-")

    def score(r: Resource) -> int:
        return sum(1 for w in slugify(r.name).split("-") if len(w) > 3 and any(x.startswith(w[:5]) for x in words))

    best = max(own, key=score, default=None)
    if best is not None and score(best) > 0:
        return best
    if len(own) == 1:
        return own[0]
    raise BadReport(f"no sé qué recurso es: nómbralo ({', '.join(r.name for r in own)})" if own
                    else f"{reporter.name} no tiene suministros propios en el inventario")


def file_report(db: Session, c: Crisis, *, by: str, kind: str, text: str, zone: str | None = None, place: str = "",
                severity: int | None = None, resource: str | None = None, qty: float | None = None,
                units: int | None = None, population: int | None = None, entity: str | None = None,
                verb: str | None = None) -> dict[str, Any]:
    spec = KINDS.get(kind)
    if spec is None:
        raise BadReport(f"tipo de incidencia desconocido: {kind}")
    reporter = db.get(Entity, (c.id, by))
    if reporter is None or reporter.kind == "information_source":
        raise BadReport("solo una autoridad, una unidad de respuesta o la población de esta crisis puede reportar incidencias")
    trusted = reliability(reporter) == "high"
    if not trusted and kind not in CIVILIAN_KINDS:
        raise BadReport(f"«{spec['label']}» solo lo puede reportar quien gestiona ese recurso")
    text = (text or "").strip()
    if not text:
        raise BadReport("ponle un nombre a la incidencia")
    zone_id = resolve_zone(db, c.id, zone)
    if zone_id and reporter.jurisdiction and zone_id not in reporter.jurisdiction:
        raise BadReport(f"{reporter.name} solo puede reportar sobre su jurisdicción")
    if kind not in ("zone_new", "entity_new"):  # those two name a place that is NOT one of the zones we hold
        cut_off = bool(re.search(r"aislad|incomunicad|sin acceso", text, re.I))
        zone_id = zone_id or _zone_for(db, c, reporter, text, needed=kind in ZONE_KINDS,
                                      newest_added=kind == "road_cut" and cut_off)
    if zone_id is None and kind in ZONE_KINDS:
        raise BadReport("indica la zona de la incidencia")
    if not place and "place" in spec["needs"]:
        place = text[:120]  # the name is the spot: street-level, so units can be sent at once
    sev = max(1, min(10, int(severity if severity is not None and trusted else spec["severity"])))

    # 0. What changed in the world, before anything is perceived: the new zone must exist for the signal to land in it.
    world_effects: list[str] = []
    if kind in WORLD_KINDS:
        try:
            if kind == "zone_new":
                zone_id, world_effects = changes.new_zone(db, c, reporter, text, zone=zone or place, population=population)
            elif kind == "resource_new":
                world_effects = changes.new_resources(db, c, reporter, text, resource=resource, qty=qty)
            elif kind == "entity_new":
                _, world_effects = changes.new_entity(db, c, reporter, text, entity=entity, units=units)
            else:
                _, world_effects = changes.action_done(db, c, reporter, text, zone_id=zone_id, verb=verb)
        except changes.Refused as e:
            raise BadReport(str(e))
    z = db.get(Zone, (c.id, zone_id)) if zone_id else None

    # 1. A located signal: needs, reflexes and both brains see it like any other — as credible as whoever tells it
    #    (the source's trust is the prior: high for an authority or a responder, low for a neighbour).
    claim = c.hazard_type if spec["claim"] == "hazard" else spec["claim"]
    sig = None
    if kind not in SILENT_KINDS:  # logistics is not an incident: it changes the world and is told in the digest, nothing more
        sig, _ = upsert_signal(
            db, c, sig_id=None, t=scenario_now(c), source=reporter.id, channel="report",
            content=text if not place or text.startswith(place) else f"{text} ({place})", is_noise=False,
            claims=[{"hazard_type": claim, "severity_hint": sev}], zone=zone_id,
            precision="street" if place else "zone", location_text=place,
            summary=(f"{reporter.name} reports ({kind}): {text}" if trusted else
                     f"UNVERIFIED neighbour report from {reporter.name} ({kind}): {text}")[:240],
            perceived_by="entity")

    # 2. Consequences, applied now — only on a trusted reporter's word.
    effects: list[str] = list(world_effects)
    isolate = trusted and z is not None and (
        kind == "road_cut" or (kind == "zone_new" and bool(re.search(r"aislad|incomunicad|sin acceso", text, re.I))))
    if isolate:
        _isolate(db, c, z, place or text, effects)
    elif kind in WORLD_KINDS:
        pass  # already applied above, before the signal
    elif not trusted:
        others = (sig.confidence_inputs or {}).get("corroborating_signals") or []
        effects.append("Aviso ciudadano de fiabilidad baja: no cambia nada hasta que otra fuente lo corrobore" if sig.confidence == "low"
                       else f"Aviso ciudadano corroborado por {len(others)} señales de la zona: fiabilidad {CONFIDENCE_ES.get(sig.confidence, sig.confidence)}")
    elif kind == "power_out" and z is not None:
        z.extra = {**(z.extra or {}), "power_out": True}
        effects.append(f"{z.name} queda marcada sin suministro")
        append_event(db, c, "zone.updated", zone_dict(z))
    elif kind == "resource_lost":
        res = db.get(Resource, (c.id, slugify(resource))) if resource else _resource_named_in(db, c, reporter, text)
        if res is None:
            raise BadReport("indica qué recurso se ha perdido")
        if res.owner_entity_id not in (None, reporter.id) and reporter.role != "coordination":
            raise BadReport(f"«{res.name}» no es de {reporter.name}")
        lost = min(res.available, float(qty or _number_in(text) or 0)) or res.available
        res.available, res.total = res.available - lost, max(0.0, res.total - lost)
        effects.append(f"{res.name}: −{lost:g} (quedan {res.available:g} de {res.total:g})")
        append_event(db, c, "resource.updated", resource_dict(res), material=True,
                     digest=f"Resource loss reported by {reporter.id}: {res.name} now {res.available:g}/{res.total:g}.")
    elif kind == "units_down":
        if reporter.units_total is None:
            raise BadReport(f"{reporter.name} no tiene unidades que dar de baja")
        n = max(1, int(units or _number_in(text) or 1))
        free = min(n, reporter.units_available or 0)
        reporter.units_available = (reporter.units_available or 0) - free
        reporter.units_total = max(0, (reporter.units_total or 0) - n)
        if reporter.units_available == 0:
            reporter.status = "busy"
        effects.append(f"{reporter.name}: −{n} unidades (libres {reporter.units_available} de {reporter.units_total})")
        append_event(db, c, "entity.updated", entity_dict(reporter), material=True,
                     digest=f"{reporter.id} lost {n} units: {reporter.units_available}/{reporter.units_total} free.")
    elif kind == "shelter_full":
        for res in db.scalars(select(Resource).where(Resource.crisis_id == c.id, Resource.id.like("plazas-albergue%"))):
            owner = db.get(Entity, (c.id, res.owner_entity_id or ""))
            if res.owner_entity_id == reporter.id or (owner is not None and zone_id in (owner.jurisdiction or [])) or res.owner_entity_id is None:
                res.available = 0
                effects.append(f"{res.name}: sin plazas libres")
                append_event(db, c, "resource.updated", resource_dict(res), material=True,
                             digest=f"Shelter full reported by {reporter.id}: {res.name} has 0 places left.")
    if trusted and kind in ("people_trapped", "building_damage"):
        effects.append("Entra como necesidad abierta de máxima prioridad: el reflejo de triaje asigna unidades en el acto")
    if trusted and sev >= 6 and kind not in ("people_trapped", "building_damage"):
        effects.append("Queda como necesidad abierta hasta que una acción la cubra")

    rep = Report(crisis_id=c.id, id=next_id(c, "rep"), t=scenario_now(c), by=reporter.id, kind=kind, zone_id=zone_id,
                 place=place, text=text, severity=sev, signal_id=sig.id if sig else None, effects=effects)
    db.add(rep)
    db.flush()
    out = report_dict(c, rep, {reporter.id: reporter.name}, {z.id: z.name} if z else {}, reporter=reporter, signal=sig)
    if kind in WORLD_KINDS:
        append_event(db, c, "report.received", out, material=True,
                     digest=f"THE WORLD CHANGED — {reporter.id} reports [{kind}]: {text[:200]}. The kernel already applied it: "
                            f"{'; '.join(effects) or 'nothing'}. Work with the new picture: the zones, stock, responders and "
                            f"actions in your state already include it; do not propose again what is marked as done.")
    elif trusted:
        append_event(db, c, "report.received", out, material=True,
                     digest=f"INCIDENT REPORT from {reporter.id} [{kind}] in {zone_id or 'no zone'} (signal {sig.id}, severity {sev}): "
                            f"{text[:200]}. Already applied by the kernel: {'; '.join(effects) or 'nothing'}. Adapt the response.")
    else:  # as material as any other low-trust signal: worth a wake-up when severe or once corroborated
        append_event(db, c, "report.received", out, material=sig.confidence in ("medium", "high") or sev >= 6,
                     digest=f"UNVERIFIED NEIGHBOUR REPORT from {reporter.id} [{kind}] in {zone_id or 'no zone'} (signal {sig.id}, "
                            f"severity {sev}, confidence {sig.confidence}): {text[:200]}. Nothing was applied by the kernel. "
                            f"Low reliability: corroborate it (another source, the town hall, a wellness check) before committing resources.")
    return out
