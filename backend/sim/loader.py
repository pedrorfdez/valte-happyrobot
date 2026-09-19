"""Load and validate a scenario pack into an in-memory world."""

import json
from pathlib import Path

import jsonschema

REPO_ROOT = Path(__file__).resolve().parents[2]
SCHEMAS_DIR = REPO_ROOT / "schemas"
SCENARIOS_DIR = REPO_ROOT / "scenarios"


def _load_json(path: Path):
    with open(path) as f:
        return json.load(f)


def load_schemas() -> dict:
    return {p.stem.removesuffix(".schema"): _load_json(p) for p in SCHEMAS_DIR.glob("*.schema.json")}


def load_scenario(scenario_id: str) -> dict:
    """Return {"scenario", "zones", "entities", "timeline", "noise"} validated
    against the JSON Schemas and cross-checked for reference integrity.
    Raises ValueError with all problems at once."""
    pack_dir = SCENARIOS_DIR / scenario_id
    if not pack_dir.is_dir():
        raise ValueError(f"scenario pack not found: {pack_dir}")

    schemas = load_schemas()
    world = _load_json(pack_dir / "world.json")
    entities = _load_json(pack_dir / "entities.json")["entities"]
    timeline_doc = _load_json(pack_dir / "timeline.json")
    messages = _load_json(pack_dir / "messages.json")

    errs: list[str] = []

    def check(obj, schema_name, label):
        v = jsonschema.Draft7Validator(schemas[schema_name])
        errs.extend(f"{label}: {e.message}" for e in v.iter_errors(obj))

    for z in world["zones"]:
        check(z, "zone", f"zone {z.get('id')}")
    for e in entities:
        check(e, "entity", f"entity {e.get('id')}")
    check(timeline_doc, "timeline", "timeline")
    check(messages, "messages", "messages")

    REQUIRED_BUCKETS = [
        "call.witness.rising", "call.trapped.severe", "call.warned.severe_warned",
        "social.witness.rising", "social.witness.severe", "social.warned.severe_warned",
        "social.rumor", "news.report.severe",
    ]
    for b in REQUIRED_BUCKETS:
        if b not in messages["buckets"]:
            errs.append(f"messages: missing required bucket {b}")
    for n in timeline_doc["noise"]["sources"]:
        if n["bucket"] not in messages["buckets"]:
            errs.append(f"noise: unknown bucket {n['bucket']}")

    zone_ids = {z["id"] for z in world["zones"]}
    entity_ids = {e["id"] for e in entities}

    for e in entities:
        for zid in e.get("jurisdiction", []):
            if zid not in zone_ids:
                errs.append(f"entity {e['id']}: unknown jurisdiction zone {zid}")
        if e.get("zone") and e["zone"] not in zone_ids:
            errs.append(f"entity {e['id']}: unknown zone {e['zone']}")

    prev_t = ""
    for i, entry in enumerate(timeline_doc["timeline"]):
        label = f"timeline[{i}] t={entry.get('t')}"
        if entry["t"] < prev_t:
            errs.append(f"{label}: out of chronological order")
        prev_t = entry["t"]
        kind = entry["type"]
        if kind == "signal":
            check(entry["signal"], "signal", label)
            if entry["signal"]["source"] not in entity_ids:
                errs.append(f"{label}: unknown source {entry['signal']['source']}")
            z = entry["signal"]["location"].get("zone")
            if z and z not in zone_ids:
                errs.append(f"{label}: unknown zone {z}")
        elif kind == "hazard":
            check(entry["hazard"], "hazard", label)
            if entry["hazard"]["zone"] not in zone_ids:
                errs.append(f"{label}: unknown zone {entry['hazard']['zone']}")
        elif kind == "world_patch":
            if entry["patch"]["entity"] not in entity_ids:
                errs.append(f"{label}: unknown entity {entry['patch']['entity']}")

    for n in timeline_doc["noise"]["sources"]:
        if n["source"] not in entity_ids:
            errs.append(f"noise: unknown source {n['source']}")
        for z in n.get("zones", []):
            if z not in zone_ids:
                errs.append(f"noise: unknown zone {z}")

    if errs:
        raise ValueError("scenario pack invalid:\n" + "\n".join(f"  - {e}" for e in errs))

    return {
        "scenario": world["scenario"],
        "zones": {z["id"]: z for z in world["zones"]},
        "entities": {e["id"]: e for e in entities},
        "initial_hazards": world.get("initial_hazards", []),
        "timeline": timeline_doc["timeline"],
        "noise": timeline_doc["noise"],
        "messages": messages["buckets"],
    }
