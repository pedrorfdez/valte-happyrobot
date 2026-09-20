"""Demand side of the crisis: what is being asked for, right now, that
nobody has been assigned to yet — and who should go.

Every report that implies people need help becomes an *open need* until
an action cites it as evidence. The brains read the list on every
wake-up, the standing reflexes dispatch the life-threatening ones at once,
and freed units are re-offered to whatever is still waiting: decisions
and resources follow the data as it arrives, not a plan written earlier.
"""

from datetime import timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from valte.core.world import entities_of, scenario_now
from valte.models import Action, Crisis, Entity, Signal, Tripwire

# Verbs that put someone or something on a need.
COVER_VERBS = {"rescue", "pump_water", "wellness_check", "shelter", "supplies", "order_evacuation", "open_shelter", "close_road"}
NEED_WINDOW = timedelta(minutes=120)
NEED_MIN_SEVERITY = 6
CONF_RANK = {"high": 0, "medium": 1, "low": 2, None: 3}

# Reflexes every crisis starts with (the agent may clear them or arm more with set_tripwire).
# actor "auto" = nearest responder with free units; target_zones "signal" = where the report comes from.
DEFAULT_REFLEXES = [
    {"id": "tw-triaje-rescate", "repeat": True,
     "if": {"min_severity": 8, "precision_in": ["street", "exact"], "min_confidence": "medium", "not_channel": "sensor"},
     "then": [{"actor": "auto", "verb": "rescue", "target_zones": "signal", "params": {"units": 2}}],
     "reason": "Plan de emergencias: personas en peligro inmediato con ubicación precisa → salen 2 unidades del recurso "
               "más cercano sin esperar al análisis; el coordinador refuerza o reasigna después."},
]


def add_default_reflexes(db: Session, c: Crisis) -> None:
    for tw in DEFAULT_REFLEXES:
        if db.get(Tripwire, (c.id, tw["id"])) is None:
            db.add(Tripwire(crisis_id=c.id, id=tw["id"], cond=tw["if"], then=tw["then"], reason=tw["reason"],
                            set_by="plan", repeat=True, created_t=c.t0_scenario))


def suggested_verb(sig: Signal) -> str:
    hazards = {cl.get("hazard_type") for cl in sig.claims or []}
    if "road_cut" in hazards:
        return "close_road"
    if sig.severity_hint >= 8 or (sig.location or {}).get("precision") in ("street", "exact"):
        return "rescue"
    return "wellness_check"


def open_needs(db: Session, c: Crisis, *, limit: int = 12) -> list[dict[str, Any]]:
    """Incidents that ask for help and that no live action covers. Five calls about the same care home are ONE
    need. It is covered when an action that puts resources on it cites any of its signals (or the incident id).
    `signal_id` is the report to cite: the most precise and most believable of the incident."""
    from valte.core import incidents

    now_s = scenario_now(c)
    out = []
    for inc in incidents.open_incidents(db, c):
        if inc.state not in ("candidate", "active") or (inc.severity or 0) < NEED_MIN_SEVERITY or not inc.zone_id:
            continue
        sigs = [s for s in incidents.signals_of(db, inc) if not s.is_noise and s.channel != "sensor"]
        if not sigs or (inc.last_t and inc.last_t < now_s - NEED_WINDOW):
            continue
        best = sorted(sigs, key=lambda s: ((s.location or {}).get("precision") not in ("street", "exact"),
                                           CONF_RANK.get(s.confidence, 3), -s.severity_hint, s.t))[0]
        out.append({
            "incident_id": inc.id, "signal_id": best.id, "signal_ids": inc.signal_ids, "sources": len(inc.origins or []),
            "state": inc.state, "zone": inc.zone_id, "severity": inc.severity, "confidence": inc.confidence, "people": inc.people,
            "precision": (best.location or {}).get("precision"), "where": inc.place or (best.location or {}).get("text", ""),
            "waiting_min": max(0, int((now_s - (inc.first_t or best.t)).total_seconds() // 60)),
            "what": inc.summary[:200],
            # one unverified voice: check it or prepare, do not commit scarce units to it yet
            "suggested_verb": "wellness_check" if inc.state == "candidate" else (
                "rescue" if incidents.verified(db, inc) and suggested_verb(best) == "wellness_check" else suggested_verb(best)),
            "verified": incidents.verified(db, inc),
        })
    out.sort(key=lambda n: (-n["severity"], CONF_RANK.get(n["confidence"], 3), -n["waiting_min"]))
    return out[:limit]


def pick_responder(db: Session, c: Crisis, verb: str, zone: str | None, units: int = 1, *,
                   reserve: int = 1) -> Entity | None:
    """Nearest responder that can do `verb` in `zone` and still has units.
    Local jurisdiction beats a regional one, short activation beats long,
    and nobody is drained to zero while another option exists."""
    options = [e for e in entities_of(db, c.id)
               if e.kind == "responder" and verb in (e.capabilities or []) and e.status != "unreachable"
               and (not e.jurisdiction or zone is None or zone in e.jurisdiction)
               and (e.units_available or 0) >= units]
    if not options:
        return None

    penalty = access_penalty(db, c, [zone] if zone else [])

    def rank(e: Entity) -> tuple:
        keeps_reserve = (e.units_available or 0) - units >= reserve
        local = (e.jurisdiction or []) == [zone]  # already inside: a collapsed access road does not slow them down
        return (not keeps_reserve, int((e.activation or {}).get("delay_min", 0)) + (0 if local else penalty),
                len(e.jurisdiction or []) or 99, -(e.units_available or 0))

    return sorted(options, key=rank)[0]


def access_penalty(db: Session, c: Crisis, zone_ids: list[str]) -> int:
    """Extra minutes to get into these zones because of reported road cuts."""
    from valte.models import Zone

    return max([int(((db.get(Zone, (c.id, z)) or Zone()).extra or {}).get("access_penalty_min", 0)) for z in zone_ids] or [0])


def resource_board(db: Session, c: Crisis) -> list[dict[str, Any]]:
    """Supply side, as compact as a prompt needs it."""
    return [{"entity": e.id, "free": e.units_available or 0, "total": e.units_total, "deployed": e.deployed or {},
             "can": e.capabilities, "zones": e.jurisdiction or "all", "status": e.status,
             "activation_min": (e.activation or {}).get("delay_min", 0)}
            for e in entities_of(db, c.id) if e.units_total is not None]
