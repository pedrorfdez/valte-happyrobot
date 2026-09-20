"""What is actually happening, as opposed to what people say.

One or several signals that talk about the same thing in the same place are ONE incident: five calls about the
same care home are one job, not five. The kernel forms incidents as signals arrive (no LLM, no credits): same
zone, same kind of problem and, for the kinds where the exact spot matters, the same spot. What a supervisor sees,
what the brains prioritise and what the reflexes serve is the incident; its signals are the evidence behind it.

An incident knows how far to be believed: reposts of one origin count once, so a rumour repeated twenty times is
still a `candidate` (one unverified report) until an independent source says the same.
"""

import re
from datetime import timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from valte.core.events import append_event
from valte.core.world import next_id, scenario_now, slugify
from valte.models import Action, Crisis, Incident, RawInput, Signal, Zone

OPEN = ("candidate", "active", "attended")
STATE_ES = {"candidate": "Sin confirmar", "active": "Sin atender", "attended": "Atendida", "resolved": "Resuelta",
            "dismissed": "Descartada", "merged": "Fusionada", "closed": "Resuelta"}
# Verbs that put someone or something on an incident (same list as the needs).
COVER_VERBS = {"rescue", "pump_water", "wellness_check", "shelter", "supplies", "order_evacuation", "open_shelter", "close_road"}
VERIFY_VERBS = {"wellness_check"}  # going to look is not dealing with it
JOIN_WINDOW = timedelta(minutes=90)
RANK = {"low": 0, "medium": 1, "high": 2}
LEVEL = ("low", "medium", "high")

# kind, label, does the exact spot tell two of them apart, labels a perception may use, words in the report
KINDS: list[tuple[str, str, bool, set[str], str]] = [
    ("accident", "Accidente", True, {"accident", "crash", "aircraft_crash", "helicopter_crash", "plane_crash", "traffic_accident", "explosion"},
     r"helic[oó]ptero|avioneta|\bavi[oó]n\b|\bdron\b|accidente|colisi[oó]n|choque|chocad|descarril|volcad|estrellad|estampad|"
     r"explosi[oó]n|explotad"),
    ("people", "Personas en peligro", True, {"people_trapped", "trapped", "rescue", "medical", "casualties", "injured"},
     r"atrapad|rescat|socorro|auxilio|no (?:puede|pueden|podemos|puedo) salir|tejado|azotea|subid[oa]s? a|arrastra|desaparecid|"
     r"residencia|ancian|mayores|discapacit|silla de ruedas|herid|inconscient|infarto|embarazad|beb[eé]|ni[ñn][oa]s"),
    ("road", "Vía cortada", True, {"road_cut", "road_closed", "bridge_collapse"},
     r"puente|carretera|\bcv-?\d+|\ba-?\d+\b|autov[ií]a|v[ií]a cortad|paso inferior|t[uú]nel|socav[oó]n|cortad[oa] al tr[aá]fico|"
     r"intransitable|no se puede pasar"),
    ("power", "Sin suministro", False, {"blackout", "power_out", "outage"},
     r"sin luz|apag[oó]n|sin electricidad|sin suministro|transformador|sin agua potable|sin cobertura|grupo electr[oó]geno"),
    ("building", "Daños en edificio", True, {"building_damage", "collapse", "structural"},
     r"derrumb|colaps|grieta|fachada|muro ca[ií]do|se ha hundido|garaje|s[oó]tano|bajo inundado|nave"),
    ("shelter", "Albergue", False, {"shelter_full", "shelter"}, r"albergue|refugio|sin plazas|polideportivo lleno"),
    ("offer", "Ofrecimiento de ayuda", True, {"offer", "help_offer", "volunteer"},
     r"ofrec|voluntari|pongo a disposici|puedo ayudar|podemos ayudar|a vuestra disposici"),
]
HAZARD_ES = {"flood": "Inundación", "fire": "Incendio", "wildfire": "Incendio", "blackout": "Apagón",
             "infra": "Fallo de infraestructura", "mci": "Víctimas múltiples", "other": "Emergencia"}
_GENERIC = {"calle", "carrer", "avenida", "avda", "avinguda", "plaza", "placa", "camino", "cami", "numero", "num", "junto", "cerca",
            "frente", "zona", "barrio", "pueblo", "casco", "urbano", "altura", "esquina", "entre", "del", "las", "los", "una", "uno",
            "por", "con", "sin", "que", "para", "desde", "hasta", "sobre"}


def origin_key(db: Session, sig: Signal) -> str:
    """Who is really behind this report. Social posts collapse into one origin: a repost is not a second witness."""
    raw = db.get(RawInput, (sig.crisis_id, sig.id))
    p = (raw.payload if raw else None) or {}
    if sig.channel == "social":
        return "social"
    if sig.channel == "call":
        caller = str(p.get("caller") or "")
        return f"call:{slugify(caller if caller and caller != 'inyectado' else sig.id)}"  # typed in by hand: nobody's number
    if sig.channel == "news":
        return f"news:{slugify(str(p.get('outlet') or sig.source))}"
    return f"{sig.channel}:{sig.source}"


def kind_of(c: Crisis, sig: Signal) -> str:
    text = f"{sig.content} {sig.summary} {(sig.location or {}).get('text', '')}".lower()
    labels = {str(cl.get("hazard_type") or "").lower() for cl in sig.claims or []}
    for kind, _, _, tags, words in KINDS:
        if labels & tags or re.search(words, text):
            if kind == "people" and sig.channel == "sensor":
                continue  # a gauge does not see people
            return kind
    # Life-threatening and pinned to a street: it is about people, whatever words were used.
    if sig.channel != "sensor" and sig.severity_hint >= 8 and (sig.location or {}).get("precision") in ("street", "exact"):
        return "people"
    return "hazard"


def _place_tokens(text: str, zone_name: str = "") -> set[str]:
    skip = _GENERIC | set(slugify(zone_name).split("-"))
    return {t for t in slugify(text).split("-") if (len(t) >= 3 or t.isdigit()) and t not in skip}


def _same_place(a: str, b: str, zone_name: str) -> bool:
    ta, tb = _place_tokens(a, zone_name), _place_tokens(b, zone_name)
    if not ta or not tb:
        return not ta and not tb  # reports without a spot share the "somewhere in town" bucket
    shared = ta & tb
    return bool(shared) and len(shared) / min(len(ta), len(tb)) >= 0.5


# Words any report of an emergency uses: sharing them says nothing about being the same event.
_COMMON = {"estamos", "tenemos", "personas", "persona", "gente", "atrapados", "atrapadas", "atrapado", "atrapada", "ayuda", "socorro",
           "auxilio", "fuego", "llamas", "salir", "puede", "pueden", "podemos", "favor", "urgente", "rapido", "vengan", "manden",
           "necesitamos", "mucha", "mucho", "muchos", "estan", "dicen", "parece", "vecinos", "vecino", "familia", "ahora", "mismo",
           "donde", "cuando", "porque", "todavia", "algunos", "varias", "varios", "dentro", "fuera", "arriba", "abajo", "cerca",
           "nivel", "subiendo", "sigue", "siguen", "hemos", "tiene", "tienen", "hacia", "desde", "entre", "sobre", "camino", "salida",
           "mayores", "heridos", "herido", "grave", "graves", "peligro", "llamada", "aviso", "avisan", "inundacion", "incendio"}


def _subject_tokens(text: str, zone_name: str = "") -> set[str]:
    skip = _GENERIC | _COMMON | set(slugify(zone_name).split("-"))
    return {t[:-1] if t.endswith("s") else t for t in slugify(text).split("-") if len(t) >= 5 and t not in skip}


def _same_subject(db: Session, inc: Incident, sig: Signal, zone_name: str) -> bool:
    """A crashed helicopter and a care home cut off by the fire are both "people in danger in Paiporta" and have
    nothing to do with each other: with no spot to compare, the reports must share a distinctive word."""
    mine = _subject_tokens(f"{sig.content} {(sig.location or {}).get('text', '')}", zone_name)
    theirs = _subject_tokens(inc.place or "", zone_name)
    for s in signals_of(db, inc):
        theirs |= _subject_tokens(f"{s.content} {(s.location or {}).get('text', '')}", zone_name)
    return bool(mine & theirs)


def _people(text: str) -> int:
    from valte.core.declare import spoken_to_digits

    found = [int(re.sub(r"\D", "", m.group(1))) for m in re.finditer(
        r"(\d[\d.]*)\s+(?:personas?|vecinos?|ancianos?|mayores|residentes?|ni[ñn]os?|heridos?|atrapad[oa]s?|pacientes?|trabajadores)",
        spoken_to_digits(text.lower()))]
    return max([n for n in found if n < 100000], default=0)


def priority_of(severity: int, state: str) -> str:
    p = "P0" if severity >= 8 else "P1" if severity >= 6 else "P2" if severity >= 4 else "P3"
    return "P1" if p == "P0" and state == "candidate" else p  # one unverified voice does not get the top slot


def signals_of(db: Session, inc: Incident) -> list[Signal]:
    rows = [db.get(Signal, (inc.crisis_id, sid)) for sid in inc.signal_ids or []]
    return [s for s in rows if s is not None]


def _by_spot(kind: str) -> bool:
    return next((sp for k, _, sp, *_ in KINDS if k == kind), False)


def covering_actions(db: Session, inc: Incident) -> list[Action]:
    """Who is on it. Citing its reports is not enough: an evacuation downstream justified by what happens here
    works on the town downstream, not on this incident."""
    cites = set(inc.signal_ids or []) | {inc.id}
    return [a for a in db.scalars(select(Action).where(Action.crisis_id == inc.crisis_id, Action.verb.in_(tuple(COVER_VERBS)),
                                                       Action.status.not_in(("rejected", "failed"))).order_by(Action.seq))
            if a.incident_id == inc.id
            or (cites & set(a.evidence or []) and (not inc.zone_id or not a.target_zones or inc.zone_id in a.target_zones))]


def verified(db: Session, inc: Incident) -> bool:
    from valte.core.world import action_state

    return any(a.verb in VERIFY_VERBS and action_state(a) == "done" for a in covering_actions(db, inc))


def _refresh(db: Session, c: Crisis, inc: Incident) -> dict[str, Any]:
    """Recompute everything an incident derives from its signals. Returns what changed, for the event and the digest."""
    before = {"state": inc.state, "priority": inc.priority, "confidence": inc.confidence, "signals": len(inc.signal_ids or [])}
    sigs = [s for s in signals_of(db, inc) if not s.is_noise]
    zone = db.get(Zone, (c.id, inc.zone_id or ""))
    if not sigs:
        if inc.state in OPEN:
            inc.state, inc.closed_reason = "dismissed", "todos sus avisos resultaron ser ruido"
        return {k: v for k, v in before.items() if getattr(inc, k, None) != v}

    inc.origins = sorted({origin_key(db, s) for s in sigs})
    inc.channels = sorted({s.channel for s in sigs})
    level = max(RANK.get(s.confidence or "low", 0) for s in sigs)
    if len(inc.origins) >= 3 or (len(inc.origins) >= 2 and len(inc.channels) >= 2):
        level = min(2, level + 1)
    if inc.origins == ["social"]:
        level = 0
    inc.confidence = LEVEL[level]
    inc.severity = max(s.severity_hint for s in sigs)
    inc.people = max([_people(f"{s.content} {s.summary}") for s in sigs] + [inc.people or 0])
    inc.first_t, inc.last_t = min(s.t for s in sigs), max(s.t for s in sigs)
    inc.evidence = [{"kind": "signal", "signal_id": s.id} for s in sigs]
    inc.hazard_types = sorted({cl["hazard_type"] for s in sigs for cl in s.claims or []}) or [c.hazard_type]

    best = sorted(sigs, key=lambda s: (-RANK.get(s.confidence or "low", 0), -s.severity_hint, s.t))[0]
    inc.summary = (best.content or best.summary)[:280]  # the words of whoever reported it, not the perception's gloss
    if not inc.place and (_by_spot(inc.kind) or zone is None):  # the hazard in a town is the town's, not one street's
        inc.place = next(((s.location or {}).get("text", "") for s in sigs if (s.location or {}).get("text")), "")[:80]
    label = next((lb for k, lb, *_ in KINDS if k == inc.kind), HAZARD_ES.get(c.hazard_type, "Emergencia"))
    spot = bool(_place_tokens(inc.place or "", zone.name if zone else ""))
    where = inc.place if spot or zone is None else zone.name
    inc.title = f"{label} · {where or 'zona sin ubicar'}" + (f" ({zone.name})" if zone and spot and zone.name.lower() not in inc.place.lower() else "")
    if _by_spot(inc.kind) and not spot:  # nowhere to point at: the title says what it is, in the reporter's words
        words = re.split(r"(?<=[.!?])\s", (best.content or best.summary).strip())[0]
        inc.title += ": " + (words if len(words) <= 64 else words[:61].rsplit(" ", 1)[0] + "…")

    if inc.state in ("candidate", "active"):
        inc.state = "candidate" if level == 0 else "active"
    inc.priority = priority_of(inc.severity, inc.state)
    inc.updated_at = best.received_at
    return {k: v for k, v in before.items() if (len(inc.signal_ids or []) if k == "signals" else getattr(inc, k)) != v}


def incident_view(db: Session, c: Crisis, inc: Incident, *, with_signals: bool = False) -> dict[str, Any]:
    from valte.core.world import action_dict, signal_dict

    now_s, zone = scenario_now(c), db.get(Zone, (c.id, inc.zone_id or ""))
    acts = covering_actions(db, inc) if inc.origin == "kernel" else []
    d: dict[str, Any] = {
        "id": inc.id, "incident_id": inc.id, "origin": inc.origin, "kind": inc.kind, "title": inc.title, "summary": inc.summary,
        "note": inc.note, "zone_id": inc.zone_id, "zone_ids": inc.zone_ids, "zone_name": zone.name if zone else "", "place": inc.place,
        "state": inc.state, "state_label": STATE_ES.get(inc.state, inc.state), "open": inc.state in OPEN,
        "priority": inc.priority, "severity": inc.severity, "confidence": inc.confidence, "people": inc.people,
        "signals": len(inc.signal_ids or []), "signal_ids": inc.signal_ids or [], "sources": len(inc.origins or []),
        "origins": inc.origins or [], "channels": inc.channels or [], "hazard_types": inc.hazard_types,
        "first_t": inc.first_t.isoformat() if inc.first_t else None, "last_t": inc.last_t.isoformat() if inc.last_t else None,
        "waiting_min": max(0, int((now_s - inc.first_t).total_seconds() // 60)) if inc.first_t and inc.state in ("candidate", "active") else 0,
        "actions": [{"id": a.id, "actor": a.actor, "verb": a.verb, "verb_label": a.verb_label, "status": a.status,
                     "units": (a.params or {}).get("units")} for a in acts],
        "revisit_at": inc.revisit_at.isoformat() if inc.revisit_at else None, "canonical_id": inc.canonical_id,
        "closed_reason": inc.closed_reason, "evidence": inc.evidence,
    }
    if with_signals:
        d["signal_list"] = [signal_dict(s) for s in sorted(signals_of(db, inc), key=lambda s: s.t)]
        d["action_list"] = [action_dict(a) for a in acts]
    return d


def _digest(inc: Incident, what: str) -> str:
    return (f"INCIDENT {inc.id} {what}: [{inc.priority}, {inc.state}, confidence {inc.confidence}] {inc.title} — "
            f"{len(inc.signal_ids or [])} signal(s) from {len(inc.origins or [])} independent source(s): "
            f"{', '.join((inc.signal_ids or [])[-4:])}. {inc.summary[:140]}")


def attach_signal(db: Session, c: Crisis, sig: Signal) -> tuple[Incident | None, bool]:
    """File a signal under the incident it talks about, or open one. Returns (incident, it changed the picture):
    a report that only repeats what an incident already says is not news for the brains."""
    if sig.is_noise:
        if sig.incident_id:  # a revision turned it into noise
            inc, sig.incident_id = db.get(Incident, (c.id, sig.incident_id)), None
            if inc:
                inc.signal_ids = [s for s in inc.signal_ids or [] if s != sig.id]
                _refresh(db, c, inc)
                append_event(db, c, "incident.updated", incident_view(db, c, inc))
        return None, False

    zone = db.get(Zone, (c.id, sig.zone_id or ""))
    precise = (sig.location or {}).get("precision") in ("street", "exact")
    kind = kind_of(c, sig)
    place = (sig.location or {}).get("text", "")[:80] if precise and _by_spot(kind) else ""
    inc = db.get(Incident, (c.id, sig.incident_id)) if sig.incident_id else None
    if inc is None:
        by_spot = _by_spot(kind)
        for other in db.scalars(select(Incident).where(Incident.crisis_id == c.id, Incident.origin == "kernel", Incident.kind == kind,
                                                       Incident.zone_id == sig.zone_id, Incident.state.in_(OPEN)).order_by(Incident.seq)):
            if not by_spot:
                inc = other
                break
            zn = zone.name if zone else ""
            recent = other.last_t is None or abs(sig.t - other.last_t) <= JOIN_WINDOW
            here, there = _place_tokens(place, zn), _place_tokens(other.place, zn)
            if here and there:
                same = _same_place(other.place, place, zn)
            elif precise and not here:
                same = False  # pinned to a street but with no words for the spot: a missed rescue costs more than a doubled one
            else:
                same = _same_subject(db, other, sig, zn)  # no spot to compare: do they talk about the same thing?
            if recent and same:
                inc = other
                break
    created = inc is None
    if created:
        seq = int((c.counters or {}).get("inc", 0)) + 1
        inc = Incident(crisis_id=c.id, id=next_id(c, "inc"), origin="kernel", seq=seq, kind=kind, zone_id=sig.zone_id,
                       zone_ids=[sig.zone_id] if sig.zone_id else [], place=place, state="candidate", signal_ids=[],
                       plan_version=c.plan_version)
        db.add(inc)
    if sig.id not in (inc.signal_ids or []):
        inc.signal_ids = [*(inc.signal_ids or []), sig.id]  # reassign: JSON columns do not track in-place edits
    sig.incident_id = inc.id
    db.flush()
    changed = _refresh(db, c, inc)
    # Opening an incident, confirming it or raising its priority is news; one more voice saying the same is not.
    # The brains hear about it on the signal's own line (core/signals.py), so this event is for the dashboard only.
    news = created or bool({"state", "priority", "confidence"} & set(changed))
    append_event(db, c, "incident.opened" if created else "incident.updated", incident_view(db, c, inc))
    return inc, news


def sync(db: Session, c: Crisis) -> None:
    """Attended / resolved follow the actions and the hazard; called on every tick and after every action change."""
    from valte.core.world import action_state

    now_s = scenario_now(c)
    for inc in db.scalars(select(Incident).where(Incident.crisis_id == c.id, Incident.origin == "kernel",
                                                 Incident.state.in_(OPEN + ("resolved",)))):
        if inc.state == "resolved":
            # Closed by this function when "somebody went to look" still counted as dealing with it: judge it again.
            if not (inc.closed_reason or "").endswith("completada(s)") or any(
                    a.verb not in VERIFY_VERBS and a.status != "pending_approval" for a in covering_actions(db, inc)):
                continue
            inc.state, inc.closed_reason = "active", ""
            inc.priority = priority_of(inc.severity, inc.state)
            fresh = inc.last_t is not None and now_s - inc.last_t <= timedelta(minutes=120)
            append_event(db, c, "incident.updated", incident_view(db, c, inc), material=fresh,
                         digest=_digest(inc, "IS NOBODY'S (it was only checked, never dealt with)") if fresh else None)
            continue
        acts = covering_actions(db, inc)
        response = [a for a in acts if a.verb not in VERIFY_VERBS and a.status != "pending_approval"]
        under_way = [a for a in acts if action_state(a) != "done"]
        state = inc.state
        if response and all(action_state(a) == "done" for a in response) and inc.kind != "hazard":
            state, inc.closed_reason = "resolved", f"{', '.join(a.id for a in response)} completada(s)"
        elif response or under_way:
            state = "attended"
        elif acts:  # somebody went to look and that is all: it is confirmed, and still nobody's
            state = "active"
        elif inc.state == "attended":  # whoever was on it was rejected or failed: it is nobody's again
            state = "candidate" if inc.confidence == "low" else "active"
        if inc.kind == "hazard" and inc.state in OPEN:
            zone = db.get(Zone, (c.id, inc.zone_id or ""))
            if zone and int((zone.extra or {}).get("peak_sev", 0)) >= 6 and zone.severity_est < 3:
                state, inc.closed_reason = "resolved", "la amenaza ha remitido en la zona"
        if state != inc.state:
            inc.state = state
            inc.priority = priority_of(inc.severity, state)
            append_event(db, c, "incident.updated", incident_view(db, c, inc),
                         material=state in ("active", "candidate"),
                         digest=_digest(inc, "IS UNATTENDED AGAIN") if state in ("active", "candidate") else None)


def link_action(db: Session, c: Crisis, act: Action) -> None:
    """An action that cites a report works on that report's incident."""
    if not act.incident_id or db.get(Incident, (c.id, act.incident_id)) is None:
        act.incident_id = None
        cited = []
        for e in act.evidence or []:
            sig = db.get(Signal, (c.id, e))
            inc = db.get(Incident, (c.id, e)) if str(e).startswith("inc-") else None
            inc = inc or (db.get(Incident, (c.id, sig.incident_id)) if sig is not None and sig.incident_id else None)
            if inc is not None and inc.origin == "kernel":
                cited.append(inc)
        here = [i for i in cited if not i.zone_id or not act.target_zones or i.zone_id in act.target_zones]
        if here:
            act.incident_id = here[0].id
    if act.incident_id:
        sync(db, c)


def dismiss(db: Session, c: Crisis, inc: Incident, *, by: str, reason: str = "") -> Incident:
    """A person says it is not true (or not ours). Its sources are remembered for it (core/learning.py)."""
    inc.state, inc.closed_reason = "dismissed", f"{by}: {reason or 'falsa alarma'}"
    for act in db.scalars(select(Action).where(Action.crisis_id == c.id, Action.incident_id == inc.id,
                                               Action.status == "pending_approval")):
        act.status, act.error = "rejected", f"{inc.id} descartada por {by}"  # nobody should sign for something that is not happening
    append_event(db, c, "incident.dismissed", {**incident_view(db, c, inc), "by": by, "reason": reason}, material=True,
                 digest=f"INCIDENT {inc.id} DISMISSED by {by} ({reason or 'false alarm'}): {inc.title}. "
                        f"Withdraw what was committed to it and distrust its sources: {', '.join(inc.origins or [])}.")
    return inc


def merge(db: Session, c: Crisis, keep: Incident, drop: Incident, *, by: str = "kernel") -> Incident:
    """Two incidents turned out to be the same event (rules cannot always tell; the strategist or a person can)."""
    if keep.id == drop.id or drop.state == "merged":
        return keep
    for s in signals_of(db, drop):
        s.incident_id = keep.id
    keep.signal_ids = [*(keep.signal_ids or []), *[s for s in drop.signal_ids or [] if s not in (keep.signal_ids or [])]]
    for a in db.scalars(select(Action).where(Action.crisis_id == c.id, Action.incident_id == drop.id)):
        a.incident_id = keep.id
    drop.state, drop.canonical_id, drop.closed_reason = "merged", keep.id, f"es la misma que {keep.id} ({by})"
    _refresh(db, c, keep)
    sync(db, c)
    append_event(db, c, "incident.merged", {"kept": incident_view(db, c, keep), "merged": drop.id, "by": by})
    return keep


def backfill(db: Session, c: Crisis) -> int:
    """A crisis declared before incidents existed: file its signals, oldest first, and tie its actions to them."""
    loose = list(db.scalars(select(Signal).where(Signal.crisis_id == c.id, Signal.is_noise.is_(False),
                                                 Signal.incident_id.is_(None)).order_by(Signal.seq)))
    for sig in loose:
        attach_signal(db, c, sig)
    if loose:
        for act in db.scalars(select(Action).where(Action.crisis_id == c.id).order_by(Action.seq)):
            link_action(db, c, act)
        sync(db, c)
    return len(loose)


def regroup(db: Session, c: Crisis) -> list[Incident]:
    """Re-file what looser rules lumped together (a crashed helicopter inside a care-home incident): every incident
    starts over from its first report and today's rules file the rest, the actions follow their evidence, and what
    turns out to be nobody's is told to the brains. Idempotent: run again, nothing moves."""
    from valte.core.world import action_state  # noqa: F401  (sync needs it loaded)

    before = {i.id: (sorted(i.signal_ids or []), i.state, i.closed_reason, i.kind, i.place)
              for i in db.scalars(select(Incident).where(Incident.crisis_id == c.id))}
    touched: list[Incident] = []
    for inc in list(db.scalars(select(Incident).where(Incident.crisis_id == c.id, Incident.origin == "kernel",
                                                      Incident.state.not_in(("merged", "dismissed"))).order_by(Incident.seq))):
        sigs = sorted((s for s in signals_of(db, inc) if not s.is_noise), key=lambda s: (s.t, s.seq))
        if not sigs:
            continue
        kinds = {kind_of(c, s) for s in sigs}
        if kinds == {inc.kind} and (len(sigs) < 2 or not _by_spot(inc.kind)):
            continue  # one report, or a per-zone kind that is what it says: nothing to untangle
        anchor = sigs[0]
        precise = (anchor.location or {}).get("precision") in ("street", "exact")
        for s in sigs[1:]:
            s.incident_id = None
        inc.kind = kind_of(c, anchor)
        inc.signal_ids, inc.place = [anchor.id], ((anchor.location or {}).get("text", "")[:80] if precise and _by_spot(inc.kind) else "")
        if inc.state in ("attended", "resolved", "closed"):
            inc.state, inc.closed_reason = "active", ""  # sync decides again, with the actions that are really its own
        _refresh(db, c, inc)
        db.flush()
        for s in sigs[1:]:
            attach_signal(db, c, s)
        touched.append(inc)
    everything = list(db.scalars(select(Incident).where(Incident.crisis_id == c.id, Incident.origin == "kernel")))
    moved = [i for i in everything if i.id not in before or sorted(i.signal_ids or []) != before[i.id][0] or i.kind != before[i.id][3]]
    if not moved:  # every report went back where it was: leave the incidents exactly as they were
        for inc in touched:
            _, inc.state, inc.closed_reason, inc.kind, inc.place = before[inc.id]
        return []
    ids = {i.id for i in touched}
    for act in db.scalars(select(Action).where(Action.crisis_id == c.id, Action.incident_id.in_(ids)).order_by(Action.seq)):
        act.incident_id = None
        link_action(db, c, act)
    sync(db, c)
    for inc in moved:
        if inc.state in ("candidate", "active"):
            append_event(db, c, "incident.refiled", incident_view(db, c, inc), material=True,
                         digest=_digest(inc, "IS NOBODY'S (it was filed inside another incident until now)"))
    return moved


def open_incidents(db: Session, c: Crisis) -> list[Incident]:
    rows = list(db.scalars(select(Incident).where(Incident.crisis_id == c.id, Incident.origin == "kernel", Incident.state.in_(OPEN))))
    return sorted(rows, key=lambda i: (i.priority, i.state == "attended", -(i.severity or 0), i.first_t or scenario_now(c)))


def brain_view(db: Session, c: Crisis, limit: int = 14) -> list[dict[str, Any]]:
    """As compact as a prompt needs it."""
    out = []
    for inc in open_incidents(db, c)[:limit]:
        v = incident_view(db, c, inc)
        out.append({k: v[k] for k in ("incident_id", "state", "priority", "confidence", "title", "summary", "kind", "zone_id", "place",
                                      "severity", "people", "signal_ids", "sources", "channels", "waiting_min", "note", "revisit_at")}
                   | {"attended_by": [f"{a['id']} {a['actor']} {a['verb']}" for a in v["actions"]]})
    return out
