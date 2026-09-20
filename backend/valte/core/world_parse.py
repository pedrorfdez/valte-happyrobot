"""Turn one line of free text into a trusted change of the world.

Two demo paths share this: a new situation typed in Mundo exterior (always a
fact, always a consequence) and an incident reported by an authority or a
responder. HappyRobot reads the line when it is available (`PedroD-world-parse`,
a small extract on a fast model); `parse_local` is the labelled stand-in.
The result goes through `reports.file_report`, which applies the effects.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from typing import Any

from valte.core.world import environment_of, slugify, zones_of
from valte.db import session_scope
from valte.hr import registry
from valte.hr.client import hr
from valte.models import Crisis, Entity

log = logging.getLogger("valte.world_parse")

TIMEOUT_S = 12  # the person is waiting; a small extract should answer in a few seconds
DONE = {"completed", "success", "succeeded", "finished"}
DEAD = {"failed", "error", "cancelled", "canceled"}
KINDS = ("people_trapped", "road_cut", "building_damage", "power_out", "units_down", "resource_lost",
         "shelter_full", "zone_new", "resource_new", "entity_new", "action_done", "other")
# First match wins. `action_done` / logistics before generic damage, so "ya hemos cortado" is not a new road_cut.
KIND_RX = [
    ("action_done", r"ya hemos|ya se ha|hemos cortado|hemos evacuado|hemos avisado|hemos abierto|por nuestra cuenta"),
    ("entity_new", r"se suma |se une |llegan voluntar|cruz roja|ume se"),
    ("resource_new", r"nos llegan|hemos recibido|llegan \d|recibi\w+ \d"),
    ("zone_new", r"se inunda [A-ZÀ-Ý]|nueva zona|se suma el municipio|ahora afecta a|a[nñ]ad(?:o|a|imos|ido|ida)?"),
    ("people_trapped", r"atrapad|refugiad|personas en (?:un |el |la )|gente en el|hay \d+\s+personas|no pueden salir"),
    ("road_cut", r"puente|carretera|calzada|acceso cortad|\bhund|\bcv-|\bcorta(?:n|do)? (?:el |la )?(?:puente|acceso|carretera)"),
    ("building_damage", r"derrumb|colaps|tejado|edificio|residencia|colegio se"),
    ("power_out", r"sin luz|apag[oó]n|sin cobertura|sin radio|sin comunicaciones|sin suministro"),
    ("units_down", r"dotaciones?\s+(?:aisladas|fuera|averiad)|unidades?\s+(?:fuera|averiad|inutiliz)|se nos ha averiado"),
    ("resource_lost", r"perdemos|inutilizad|solo quedan|quedan \d|bombas|embarcacion|mantas"),
    ("shelter_full", r"albergue lleno|no admite|sin plazas|ya no cabe"),
]
FIELDS = ("kind", "zone", "place", "severity", "resource", "qty", "units", "population", "entity", "verb")
# A town "está aislada / incomunicada / sin acceso": not a 112 rumour — it is cut off.
CUT_OFF_RX = re.compile(
    r"aislad|incomunicad|sin acceso|no se puede(?:n)? (?:entrar|llegar|acceder|pasar)|"
    r"cortad[oa]s? (?:del resto|de todo|por el|por la)|queda(?:n)? (?:sin salida|incomunicad)",
    re.I)
_NOT_A_PLACE = {
    "esta", "estan", "aislado", "aislada", "aislados", "aisladas", "incomunicada", "incomunicado", "acceso",
    "dotacion", "dotaciones", "unidad", "unidades", "persona", "personas", "gente", "vecinos", "habitantes",
    "puente", "carretera", "calle", "colegio", "bajo", "garaje", "residencia", "albergue", "bomba", "bombas",
    "manta", "mantas", "zona", "pueblo", "nueva", "nuevo", "anadido", "anadida", "anado", "anadimos", "ahora",
    "tambien", "hay", "hemos", "cinco", "cuatro", "tres", "dos", "seis", "siete", "ocho", "nueve", "diez",
    "municipio", "barrio",
}


def is_cut_off(text: str) -> bool:
    return bool(CUT_OFF_RX.search(text or ""))


def unknown_place(text: str, zones: list[Any]) -> str:
    """A town named in the line that is not yet on the map. Empty if the line only talks about known zones."""
    known = {z.id for z in zones} | {slugify(z.name) for z in zones}
    hay = f"-{slugify(text)}-"
    if any(f"-{slugify(z.name)}-" in hay for z in zones):
        return ""
    for m in re.finditer(r"\b([A-ZÀ-Ý][\wÀ-ÿ'’-]{2,})\b", text):
        if slugify(m.group(1)) not in _NOT_A_PLACE | known:
            return m.group(1)
    for w in re.findall(r"[a-zà-ÿ][\wà-ÿ'’-]{3,}", (text or "").lower()):
        if slugify(w) not in _NOT_A_PLACE | known and not re.search(r"(?:ad[oa]s?|ando|iendo)$", w):
            return w[:1].upper() + w[1:]
    return ""


def parse_local(text: str, *, zones: list[Any], hint_kind: str = "") -> dict[str, Any]:
    """Rules of thumb for one Spanish sentence. Good enough offline and as a fallback."""
    low = text.lower()
    kind = hint_kind if hint_kind in KINDS and hint_kind != "other" else "other"
    if kind == "other":
        kind = next((k for k, rx in KIND_RX if re.search(rx, low)), "other")
    hay = f"-{slugify(text)}-"
    zone = next((z.id for z in zones if f"-{slugify(z.name)}-" in hay), "")
    new_name = unknown_place(text, zones)
    cut = is_cut_off(text)
    # A town that is not on the map (Begís está aislada): create it; isolation is applied after.
    if new_name and kind in ("other", "zone_new", "road_cut"):
        kind, zone, place = "zone_new", "", new_name
    else:
        place = ""
        if kind in ("people_trapped", "road_cut", "building_damage"):
            m = re.search(r"(?:en|junto a|a la altura de)\s+(.{3,80}?)(?:\.|$)", text, re.I)
            place = (m.group(1).strip(" .,") if m else text)[:120]
        if cut and kind == "other":
            kind = "road_cut"
    words = {"dos": 2, "tres": 3, "cuatro": 4, "cinco": 5, "seis": 6, "siete": 7, "ocho": 8, "nueve": 9, "diez": 10}
    n: int | None = None
    for w in re.findall(r"(?<![\w-])(?:\d+|[a-záéíóúü]+)(?![\w-])", low):
        if w.isdigit():
            n = int(w)
            break
        if w in words:
            n = words[w]
            break
    out: dict[str, Any] = {"kind": kind, "zone": zone, "place": place,
                           "severity": 9 if kind == "people_trapped" else 7 if kind in ("road_cut", "building_damage") else 6}
    if kind in ("resource_lost", "resource_new") and n:
        out["qty"] = n
    if kind in ("units_down", "entity_new") and n:
        out["units"] = n
    if kind == "zone_new" and n and n >= 50:
        out["population"] = n
    return out


def catalog(db, c: Crisis) -> str:
    lines = [f"{z.id} ({z.name}{'; origin' if z.is_origin else ''})" for z in zones_of(db, c.id)]
    return "\n".join(lines) or "(no zones)"


async def _parse_hr(payload: dict[str, Any], workflow_id: str, extract_node: str) -> dict[str, Any]:
    run_id = await hr().trigger_run(workflow_id, payload)
    t0 = time.monotonic()
    while time.monotonic() - t0 < TIMEOUT_S:
        await asyncio.sleep(0.8)
        status = str((await hr().get_run(run_id)).get("status") or "").lower()
        if status in DEAD:
            raise RuntimeError(f"run {status}")
        if status in DONE:
            out = await hr().node_output(run_id, extract_node)
            response = ((out or {}).get("data") or {}).get("response")
            if isinstance(response, str):
                response = json.loads(response)
            doc = (response or {}).get("change_json")
            doc = json.loads(doc) if isinstance(doc, str) else doc
            if not isinstance(doc, dict):
                raise RuntimeError("el run terminó sin salida legible")
            return doc
    raise TimeoutError("HappyRobot no respondió a tiempo")


async def interpret(crisis_id: str, text: str, *, hint_kind: str = "", by: str = "") -> dict[str, Any]:
    """Text → the fields `file_report` needs. HR when provisioned; local otherwise."""
    text = (text or "").strip()
    with session_scope() as db:
        c = db.get(Crisis, crisis_id)
        if c is None:
            return parse_local(text, zones=[], hint_kind=hint_kind)
        zones = list(zones_of(db, c.id))
        local = parse_local(text, zones=zones, hint_kind=hint_kind)
        env = environment_of(db, c)
        who = ""
        if by:
            e = db.get(Entity, (c.id, by))
            who = f"{e.name} ({e.kind})" if e else by
        wf = registry.get(db, registry.WORLD_PARSE) if registry.usable(db, registry.WORLD_PARSE) else None
        target = (wf.workflow_id, (wf.node_ids or {}).get("extract")) if wf else None
        payload = {"text": text, "environment": env, "zones": catalog(db, c),
                   "hint_kind": hint_kind or "", "reporter": who}
    if not (target and target[1]):
        return local
    try:
        raw = await _parse_hr(payload, target[0], target[1])
    except Exception as e:
        log.warning("world-parse failed, reading it locally: %s", e)
        return local
    return combine(raw, local, hint_kind=hint_kind)


def combine(raw: dict[str, Any], local: dict[str, Any], *, hint_kind: str = "") -> dict[str, Any]:
    """HR extract + local reading. The labelled reader wins when HR shrugged (`other`) or a new town appeared."""
    out = {k: raw[k] for k in FIELDS if raw.get(k) not in (None, "")}
    if out.get("kind") not in KINDS:
        out["kind"] = local["kind"]
    if hint_kind in KINDS and hint_kind != "other":
        out["kind"] = hint_kind
    for k, v in local.items():
        out.setdefault(k, v)
    # HappyRobot must not invent zone ids, so it often returns `other`/`road_cut` with no zone for a new town.
    if local.get("kind") == "zone_new":
        out["kind"] = "zone_new"
        if local.get("place"):
            out["place"] = local["place"]
        out.pop("zone", None)
    elif out.get("kind") in (None, "", "other") and local.get("kind") not in (None, "", "other"):
        out["kind"] = local["kind"]
        for k in ("zone", "place", "qty", "units", "severity"):
            if out.get(k) in (None, "") and local.get(k) not in (None, ""):
                out[k] = local[k]
    return out


def fill(base: dict[str, Any], parsed: dict[str, Any], *, hint_kind: str) -> dict[str, Any]:
    """Parsed fields fill gaps; an explicit kind other than `other` wins."""
    out = dict(base)
    for k in FIELDS:
        if out.get(k) in (None, "") and parsed.get(k) not in (None, ""):
            out[k] = parsed[k]
    if (not hint_kind or hint_kind == "other") and parsed.get("kind") in KINDS:
        out["kind"] = parsed["kind"]
    return out
