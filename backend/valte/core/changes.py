"""Telling the system how the world really is, through the same channel that reports incidents.

A plan written half an hour ago is always out of date: a town nobody listed is under water, a lorry of blankets
arrives, a volunteer group turns up with its own boats, and a mayor cuts a road without asking anybody. Until now
only the agent could change the world model (`register_entity`, `transfer_resource`…) and the people on the ground
could only report damage. Here they can also say what has CHANGED, in the same two-field form: one line of text
and a kind. Everything else — the zone, the amounts, who owns what, which verb — is read out of the line, and what
had to be assumed is written back in the effects so whoever typed it can see it.

Only the crisis's own authorities and responders may do this (a neighbour's word is a lead, not a fact), every
change is an event with a digest so the brains find out on their next wake-up, and nothing here bypasses the
kernel's rules: `action_done` goes through the same validation as anything the agent proposes.
"""

import re
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from valte.core.declare import quantities, spoken_to_digits
from valte.core.events import append_event
from valte.core.world import (
    VERB_LABELS,
    entities_of,
    entity_dict,
    resource_dict,
    resources_of,
    scenario_now,
    slugify,
    zone_dict,
    zones_of,
)
from valte.models import Action, Crisis, Entity, Resource, Zone

# Words that are never a place and never a thing worth counting as stock.
_STOP = {"el", "la", "los", "las", "un", "una", "unos", "unas", "de", "del", "al", "en", "y", "e", "o", "u", "que", "con", "sin",
         "por", "para", "se", "ha", "han", "hay", "esta", "estan", "es", "son", "ya", "muy", "nos", "nuestro", "nuestra", "todo",
         "toda", "todos", "todas", "zona", "pueblo", "barrio", "municipio", "casco", "calle", "agua", "fuego", "gente", "vecinos",
         "personas", "habitantes", "ahora", "aqui", "alli", "tambien", "nueva", "nuevo", "afectada", "afectado", "inundada",
         "inundado", "ardiendo", "entra", "llega", "empieza", "sumando", "suma", "une", "aviso", "minutos", "min", "horas",
         "mas", "menos", "abajo", "arriba", "cerca", "lejos", "norte", "sur", "este", "oeste", "otra", "otro", "parte", "lado",
         # what the sentence DOES, never what it is about: these must never be mistaken for a place or a name
         "inunda", "inundan", "quema", "queman", "arde", "arden", "desborda", "desbordan", "corta", "cortan", "afecta",
         "afectan", "sube", "suben", "baja", "alcanza", "cubre", "hemos", "tenemos", "vamos", "esta", "estamos", "dice",
         "avisa", "avisan", "manda", "mandan", "pide", "piden", "queda", "quedan", "ahora", "todavia", "solo",
         "aislada", "aislado", "aisladas", "aislados", "incomunicada", "incomunicado"}
_WORD = r"[A-Za-zÀ-ÿ][\wÀ-ÿ'’-]*"
_PLACE_AFTER = rf"\b(?:en|a|hacia|sobre|hasta)\s+((?:{_WORD})(?:\s+(?:de\s+la\s+|de\s+los\s+|de\s+las\s+|del\s+|de\s+|l['’])?{_WORD}){{0,2}})"
_POP = r"(\d[\d.\s]*)\s*(?:mil\s+)?(?:habitantes|hab\b\.?|vecinos|residentes|personas)"
# «se inunda alfafar», «afecta a benetússer»: what the hazard is doing, and right after it the place it does it to.
_PLACE_VERB = (r"\b(?:se\s+(?:inunda\w*|quema\w*|desborda\w*|extiende\s+a)|inunda\w*|arde\w*|afecta\s+a|llega\s+a|alcanza\w*|"
               r"entra\s+(?:el\s+)?agua\s+en|cubre\w*)\s+"
               r"((?:[A-Za-zÀ-ÿ][\wÀ-ÿ'’-]*)(?:\s+(?:de\s+la\s+|de\s+los\s+|del\s+|de\s+|l['’])?[A-Za-zÀ-ÿ][\wÀ-ÿ'’-]*){0,3})")
_VERBISH = re.compile(r"(?:ad[oa]s?|id[oa]s?|and[oa]|iend[oa]|mos|ron|aba|ando)$")
_DELAY = r"(\d+)\s*(min(?:utos?)?|h(?:oras?)?)\b"
# People an entity can put on the ground, as opposed to the material it brings.
_CREW = r"volunt\w+|efectivos?|dotaciones?|equipos?|unidades?|patrullas?|brigadas?|sanitarios?|agentes?|bomberos?|personas?"
# Capability the words of the report imply. Order matters: the first hit wins, `wellness_check` is the floor.
_CAPS = [("rescue", r"rescat|salvament|bomber|excarcel|b[uú]squeda"),
         ("pump_water", r"achiqu|bombe|bomba|desag|lodo|barro"),
         ("shelter", r"albergu|acog|realoj|alojar"),
         ("supplies", r"suministr|repart|comida|v[ií]ver|manta|agua potable|log[ií]stic")]
# What a human may tell the system they have already done, by the words they use for it.
_DONE = [("close_road", r"cortad|cortamos|cerrad|cerramos|precint"),
         ("order_evacuation", r"evacu|desaloj"),
         ("open_shelter", r"abiert\w+ (?:el |la )?(?:albergue|polideportivo|pabell|colegio)|habilitad|montad\w+ (?:el |un )?albergue"),
         ("send_es_alert", r"avisad|alertad|meg[aá]fon|bando|es-?alert|mandad\w+ (?:el )?aviso"),
         ("rescue", r"rescatad|rescatamos|sacad\w+ a|evacuad\w+ a mano"),
         ("pump_water", r"achicad|achicamos|bombead"),
         ("wellness_check", r"comprobad|visitad|puerta a puerta|pasad\w+ lista"),
         ("supplies", r"repartid|repartimos|entregad"),
         ("shelter", r"realojad|alojad|acogid")]


class Refused(ValueError):
    """What the person typed cannot be turned into a change; the message says what is missing."""


def _int(s: str) -> int:
    return int(re.sub(r"\D", "", s) or 0)


def _known_place(db: Session, c: Crisis, name: str) -> bool:
    slug = slugify(name)
    return any(slugify(z.name) == slug or z.id == slug for z in zones_of(db, c.id))


def _clean(name: str) -> str:
    """Trim the filler around a name without touching its inside: «Agrupación de Voluntarios de Alaquàs» keeps its «de»."""
    words = name.strip(" .,;:·-").split()
    while words and slugify(words[0]) in _STOP and not words[0][:1].isupper():
        words.pop(0)
    while words and slugify(words[-1]) in _STOP:
        words.pop()
    return " ".join(words).strip(" .,;:·-")


def place_name(db: Session, c: Crisis, text: str, *, known_ok: bool = False) -> str | None:
    """The place a line of text is about, when it is not one of the zones we already hold."""
    body = re.sub(_POP, " ", spoken_to_digits(text), flags=re.I)
    caps = rf"[A-ZÀ-Ý][\wÀ-ÿ'’-]*(?:\s+(?:de\s+la\s+|de\s+los\s+|del\s+|de\s+|l['’])?[A-ZÀ-Ý][\wÀ-ÿ'’-]*){{0,4}}"
    for rx in (rf"\b(?:en|a|hacia|sobre|hasta)\s+({caps})", rf"\b({caps})", _PLACE_VERB, _PLACE_AFTER):
        lower_ok = rx in (_PLACE_AFTER, _PLACE_VERB)  # typed in a hurry, all lowercase: never a short word
        for m in re.finditer(rx, body, re.I if lower_ok else 0):
            name = _clean(m.group(1))
            if len(name) >= (4 if lower_ok else 3) and (known_ok or not _known_place(db, c, name)):
                return name[:60] if name[:1].isupper() else name[:60].title()
    # last resort: the only word left once the verbs, the fillers and the zones we already hold are out of the way
    for w in re.findall(r"[a-zà-ÿ'’-]{4,}", body.lower()):
        if slugify(w) not in _STOP and not _VERBISH.search(w) and (known_ok or not _known_place(db, c, w)):
            return w.title()
    return None


def _owner_of(c: Crisis, reporter: Entity) -> str:
    return (c.config or {}).get("coordination_entity", "cecopi") if reporter.role == "coordination" else reporter.id


def _find_resource(db: Session, c: Crisis, reporter: Entity, name: str) -> Resource | None:
    """Whose stock this line is about. Coordination manages everybody's; anyone else only their own."""
    words = [w for w in slugify(name).split("-") if len(w) > 3]

    def score(r: Resource) -> int:
        return sum(1 for w in slugify(r.name).split("-") if len(w) > 3 and any(x.startswith(w[:5]) or w.startswith(x[:5]) for x in words))

    mine = [r for r in resources_of(db, c.id)
            if reporter.role == "coordination" or r.owner_entity_id in (None, _owner_of(c, reporter))]
    best = max(mine, key=score, default=None)
    return best if best is not None and score(best) > 0 else None


# ── the four changes ─────────────────────────────────────────────────────


def new_zone(db: Session, c: Crisis, reporter: Entity, text: str, *, zone: str | None = None,
             population: int | None = None) -> tuple[str, list[str]]:
    """A town or district nobody had listed is in it. It enters the map, hangs off the zone it comes from, and from
    then on it has a severity, a countdown and entities of its own."""
    name = zone or place_name(db, c, text)
    if not name:  # the only place it names may be one we already hold: say so instead of asking again
        known = place_name(db, c, text, known_ok=True)
        raise Refused(f"{known} ya está en el mapa de la crisis" if known and _known_place(db, c, known)
                      else "dime cómo se llama la zona: «se inunda Alfafar, 21.000 habitantes»")
    if _known_place(db, c, name):
        raise Refused(f"{name} ya está en el mapa de la crisis")
    zid = slugify(name)
    pop = population if population is not None else (lambda m: _int(m.group(1)) if m else 0)(re.search(_POP, spoken_to_digits(text), re.I))

    zones = zones_of(db, c.id)
    parent = next((z for z in zones if z.id in (reporter.jurisdiction or [])), None) \
        or (max(zones, key=lambda z: z.severity_est) if zones else None)
    m = re.search(_DELAY, text, re.I)
    delay = (int(m.group(1)) * (60 if m.group(2).lower().startswith("h") else 1)) if m else 20

    z = Zone(crisis_id=c.id, id=zid, name=name, population=pop, is_origin=parent is None, downstream=[],
             sort_index=len(zones), base_at_risk_pct=20.0, notes=f"Añadida sobre la marcha por {reporter.name}: {text[:120]}")
    db.add(z)
    effects = [f"{name} entra en el mapa" + (f" con {pop:,} habitantes".replace(",", " ") if pop else " (sin dato de habitantes)")]
    if parent is not None:
        parent.downstream = [*(parent.downstream or []), {"to": zid, "delay_min": delay}]
        effects.append(f"Aguas abajo de {parent.name}: la amenaza llega en +{delay} min" +
                       (" (supuesto: dilo en el texto si es otro)" if not m else ""))
        append_event(db, c, "zone.updated", zone_dict(parent))
    db.flush()

    # The town hall and the neighbours of a zone are what let the agent talk to it at all.
    for eid, kind, cap in ((f"ayto-{zid}", "authority", ["order_evacuation", "open_shelter", "close_road"]),
                           (f"poblacion-{zid}", "population", [])):
        if db.get(Entity, (c.id, eid)) is None:
            db.add(Entity(crisis_id=c.id, id=eid, name=f"Ayuntamiento de {name}" if kind == "authority" else f"Vecinos · {name}",
                          kind=kind, role="authority" if kind == "authority" else "", weight=7 if kind == "authority" else 1,
                          trust="high" if kind == "authority" else "low", jurisdiction=[zid],
                          channel={"kind": "email", "address": f"alcaldia-{zid}@demo.valte"} if kind == "authority" else {"kind": "none"},
                          capabilities=cap, activation={"delay_min": 0, "cost": "low"},
                          escalation_to="delegacion-gobierno" if kind == "authority" else None,
                          zone=None if kind == "authority" else zid, provenance="discovered"))
    for e in entities_of(db, c.id):  # whoever covers the whole crisis covers this too
        if e.kind == "responder" and e.jurisdiction and len(e.jurisdiction) >= max(2, len(zones) - 1) and zid not in e.jurisdiction:
            e.jurisdiction = [*e.jurisdiction, zid]
    append_event(db, c, "zone.updated", zone_dict(z))
    return zid, effects


def new_resources(db: Session, c: Crisis, reporter: Entity, text: str, *, resource: str | None = None,
                  qty: float | None = None, owner: str | None = None) -> list[str]:
    """Stock that arrives, or a count that was wrong. "nos llegan 200 mantas" adds; "solo quedan 3 bombas" corrects."""
    owner_id = owner or _owner_of(c, reporter)
    owner_name = (db.get(Entity, (c.id, owner_id)) or reporter).name
    correcting = bool(re.search(r"\b(?:solo|s[oó]lo)?\s*(?:quedan|queda|en realidad|realmente|corrijo|corregir|son|hay ya|ten[ií]amos mal)\b", text, re.I))
    items: list[tuple[int, str]] = [(int(qty), resource)] if resource and qty is not None else quantities(text)
    items = [(n, nm) for n, nm in items if n and not re.fullmatch(_CREW, slugify(nm).replace("-", " "), re.I)]
    if not items:
        raise Refused("dime cuántos y de qué: «nos llegan 200 mantas y 4 bombas de achique»")

    effects = []
    for n, raw_name in items:
        res = db.get(Resource, (c.id, slugify(resource))) if resource else _find_resource(db, c, reporter, raw_name)
        if res is None:
            name = raw_name[:1].upper() + raw_name[1:]
            rid, n_same = slugify(raw_name)[:40], 0
            while db.get(Resource, (c.id, rid)) is not None:
                n_same += 1
                rid = f"{slugify(raw_name)[:38]}-{n_same}"
            res = Resource(crisis_id=c.id, id=rid, name=name, unit="", description=f"Añadido por {reporter.name}",
                           total=float(n), available=float(n), owner_entity_id=owner_id,
                           sort_index=len(list(resources_of(db, c.id))))
            db.add(res)
            db.flush()
            effects.append(f"{name}: nuevo en el inventario de {owner_name} · {n}")
        elif correcting:
            res.available, res.total = float(n), max(float(n), res.total - res.available + float(n))
            effects.append(f"{res.name}: corregido a {n:g} disponibles de {res.total:g}")
        else:
            res.available, res.total = res.available + n, res.total + n
            effects.append(f"{res.name}: +{n} (ahora {res.available:g} de {res.total:g})")
        append_event(db, c, "resource.updated", resource_dict(res))
    return effects


def new_entity(db: Session, c: Crisis, reporter: Entity, text: str, *, entity: str | None = None,
               units: int | None = None) -> tuple[str, list[str]]:
    """Somebody who was not in the plan turns up and can work: a volunteer group, a neighbouring brigade, an NGO."""
    name = entity or place_name(db, c, re.sub(r"\b(?:se suma|se une|llega|ha llegado|ofrece|se ofrece|tenemos|contamos con)\b", " ", text, flags=re.I),
                                known_ok=True)
    if not name:
        raise Refused("dime quién se suma: «se suma Cruz Roja con 12 voluntarios y 2 embarcaciones»")
    eid = slugify(name)
    if db.get(Entity, (c.id, eid)) is not None:
        raise Refused(f"{name} ya está en la crisis")

    counted = quantities(text)
    crew = units if units is not None else next((n for n, nm in counted if re.fullmatch(_CREW, slugify(nm).replace("-", " "), re.I)), None)
    stock = [(n, nm) for n, nm in counted if not re.fullmatch(_CREW, slugify(nm).replace("-", " "), re.I)]
    low = text.lower()
    caps = [v for v, rx in _CAPS if re.search(rx, low)] or ["wellness_check"]
    if "supplies" not in caps and stock:
        caps.append("supplies")  # it brought material: it can hand it out
    zone_ids = reporter.jurisdiction or [z.id for z in zones_of(db, c.id)]

    ent = Entity(crisis_id=c.id, id=eid, name=name, kind="responder", role="responder", weight=4,
                 # a human from the apparatus vouches for them: better than what the agent discovers by itself, not an official body
                 trust="medium", jurisdiction=list(zone_ids), channel={"kind": "none"}, capabilities=caps,
                 units_total=crew, units_available=crew, activation={"delay_min": 15, "cost": "low"},
                 escalation_to=reporter.id, status="available", provenance="discovered",
                 notes=f"Se suma durante la crisis, lo confirma {reporter.name}: {text[:140]}")
    db.add(ent)
    db.flush()
    effects = [f"{name} queda registrada" + (f" con {crew} unidades" if crew else " (sin unidades: dilas y podrá recibir trabajo)")
               + " · puede " + ", ".join(VERB_LABELS.get(v, v).lower() for v in caps)]
    for n, nm in stock:  # "con 2 embarcaciones": the material comes with whoever brought it
        effects += new_resources(db, c, reporter, f"{n} {nm}", owner=eid)
    append_event(db, c, "entity.updated", entity_dict(ent), material=True,
                 digest=f"NEW RESPONDER registered by {reporter.id}: {name} ({eid}), {crew or 0} units, can {caps}, "
                        f"zones {zone_ids}. Use it for low-risk work; its trust is medium, not an official body.")
    return eid, effects


def action_done(db: Session, c: Crisis, reporter: Entity, text: str, *, zone_id: str | None = None,
                verb: str | None = None) -> tuple[str, list[str]]:
    """"Ya hemos cortado la CV-36": what a person did on their own becomes an action of theirs, already executed, so
    the agent stops asking for it and the world model matches the street."""
    from valte.core import actions as core_actions

    low = text.lower()
    chosen = verb or next((v for v, rx in _DONE if re.search(rx, low)), None)
    if chosen is None:
        raise Refused("no sé qué habéis hecho: empieza por el verbo («hemos cortado…», «hemos abierto el albergue…», "
                      "«hemos evacuado…», «hemos avisado…»)")
    if chosen not in (reporter.capabilities or []):
        raise Refused(f"{reporter.name} no puede «{chosen}»: lo suyo es {', '.join(reporter.capabilities or []) or 'nada operativo'}")

    params: dict[str, Any] = {}
    if chosen == "close_road":  # the road number if it is there, else the thing that was cut, without the rest of the sentence
        road = re.search(r"\b(?:cv|a|v|n|ap)-?\s?\d{1,3}\b", text, re.I) or \
            re.search(r"\b(?:el |la )?((?:puente|carretera|camino|avenida|calle|paso|acceso)\s+(?:de\s+(?:la\s+|los\s+)?)?[\wÀ-ÿ'-]+(?:\s+[\wÀ-ÿ'-]+)?)", text, re.I)
        params["road"] = (road.group(0) if road and road.re.pattern.startswith(r"\b(?:cv") else
                          road.group(1) if road else text[:60]).strip(" .,")
    if chosen in ("rescue", "pump_water", "wellness_check"):
        params["units"] = min(max(1, next((n for n, _ in quantities(text)), 1)), max(1, reporter.units_available or 1))
    if chosen == "open_shelter":
        params["capacity"] = next((n for n, nm in quantities(text) if "plaza" in nm or "person" in nm), 0) or 200
    if chosen == "shelter":
        params["people"] = next((n for n, _ in quantities(text)), 20)
    if chosen == "send_es_alert":
        params["message"] = text[:240]

    res = core_actions.propose_action(db, c, {
        "actor": reporter.id, "verb": chosen, "target_zones": [zone_id] if zone_id else [], "params": params,
        "evidence": [], "reasoning": f"Lo comunica {reporter.name} por el canal de incidencias: «{text[:160]}». Ya está hecho."},
        origin="human", by=reporter.id)
    if res.get("error"):
        dup = re.match(r"duplicate: (\S+) already", res["error"])
        raise Refused(f"ya lo teníais registrado ({dup.group(1)}): el sistema cuenta con ello" if dup else res["error"])
    act = db.get(Action, (c.id, res["id"]))
    label = act.verb_label if act is not None else chosen
    pending = res.get("status") == "pending_approval"
    return res["id"], [f"«{label}» queda registrada como acción de {reporter.name} ({res['id']})"
                       + (": necesita firma y se ha pedido" if pending else ", ya ejecutada")
                       + ". El agente no volverá a proponerla."]
