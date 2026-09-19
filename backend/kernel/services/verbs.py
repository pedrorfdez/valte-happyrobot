"""System verbs: the closed set the kernel implements itself. Each entry
validates params and executes inline inside POST /actions."""

from fastapi import HTTPException

from ..db import js, q
from ..validation import validate

DISCOVERED_ALLOWED_CAPABILITIES = {"supplies", "wellness_check"}
UPDATABLE_FIELDS = {"status", "trust", "zone", "notes", "units"}


ENTITY_FIELDS = {"id", "name", "kind", "weight", "trust", "jurisdiction", "channel",
                 "ingest", "capabilities", "units", "population", "activation",
                 "escalation_to", "zone", "status", "provenance", "notes"}


def register_entity(run_id: str, params: dict) -> dict:
    ent = params.get("entity")
    if not isinstance(ent, dict):
        raise HTTPException(422, "register_entity: params.entity object required")
    ent = {**ent, "provenance": "discovered", "trust": "low"}
    ent["capabilities"] = [c for c in ent.get("capabilities", [])
                           if c in DISCOVERED_ALLOWED_CAPABILITIES]
    # normalize LLM-composed entities instead of rejecting them
    ent.setdefault("kind", "responder")
    ent.setdefault("weight", 2)
    ent.setdefault("status", "available")
    contact = ent.pop("contact", None) or ent.pop("phone", None)
    if contact and not ent.get("channel"):
        ent["channel"] = {"kind": "sms", "address": str(contact)}
    extras = {k: ent.pop(k) for k in list(ent) if k not in ENTITY_FIELDS}
    if extras:
        ent["notes"] = (ent.get("notes", "") + " " +
                        " ".join(f"{k}: {v}" for k, v in extras.items())).strip()
    validate(ent, "entity")
    if q("select 1 from entities where run_id=%s and id=%s", (run_id, ent["id"]), one=True):
        raise HTTPException(409, f"entity {ent['id']} already exists; use update_entity")
    q("insert into entities (run_id,id,kind,status,provenance,units_available,doc) values (%s,%s,%s,%s,%s,%s,%s)",
      (run_id, ent["id"], ent["kind"], ent["status"], "discovered",
       (ent.get("units") or {}).get("available"), js(ent)))
    return {"registered": ent["id"]}


def update_entity(run_id: str, params: dict) -> dict:
    eid, fields = params.get("entity_id"), params.get("set") or {}
    bad = set(fields) - UPDATABLE_FIELDS
    if not eid or not fields or bad:
        raise HTTPException(422, f"update_entity: entity_id and set required; updatable: {sorted(UPDATABLE_FIELDS)}; bad: {sorted(bad)}")
    row = q("select doc from entities where run_id=%s and id=%s", (run_id, eid), one=True)
    if not row:
        raise HTTPException(404, f"entity {eid} not found")
    doc = row["doc"]
    for k, v in fields.items():
        doc[k] = {**doc[k], **v} if isinstance(v, dict) and isinstance(doc.get(k), dict) else v
    validate(doc, "entity")
    q("update entities set doc=%s, status=%s, units_available=%s where run_id=%s and id=%s",
      (js(doc), doc["status"], (doc.get("units") or {}).get("available"), run_id, eid))
    return {"updated": eid, "fields": sorted(fields)}


def set_tripwire(run_id: str, params: dict, set_by: str) -> dict:
    tw = params.get("tripwire")
    if not isinstance(tw, dict) or "id" not in tw or "if" not in tw or "then" not in tw:
        raise HTTPException(422, "set_tripwire: params.tripwire {id, if, then, reason} required")
    cond = tw["if"]
    ctype = cond.get("type", "signal")
    if ctype not in ("signal", "silence"):
        raise HTTPException(422, "tripwire if.type must be signal or silence")
    if ctype == "silence" and not cond.get("source"):
        raise HTTPException(422, "silence tripwire requires if.source")
    q("""insert into tripwires (run_id,id,set_by,doc) values (%s,%s,%s,%s)
         on conflict (run_id,id) do update set doc=excluded.doc, status='active', set_by=excluded.set_by""",
      (run_id, tw["id"], set_by, js(tw)))
    return {"tripwire": tw["id"], "status": "active"}


def clear_tripwire(run_id: str, params: dict) -> dict:
    twid = params.get("tripwire_id")
    if not twid:
        raise HTTPException(422, "clear_tripwire: params.tripwire_id required")
    q("update tripwires set status='cleared' where run_id=%s and id=%s", (run_id, twid))
    return {"tripwire": twid, "status": "cleared"}


def schedule_check(run_id: str, params: dict) -> dict:
    delay = params.get("delay_min")
    if not isinstance(delay, (int, float)) or delay <= 0:
        raise HTTPException(422, "schedule_check: params.delay_min > 0 required")
    newest = q("select max(t) as m from signals where run_id=%s", (run_id,), one=True)
    if not newest["m"]:
        raise HTTPException(409, "schedule_check: no signals yet, scenario clock unknown")
    q("""insert into events (run_id,type,lane,payload,status,due_t)
         values (%s,'timer_fired','coordinator',%s,'timer', %s + make_interval(mins => %s))""",
      (run_id, js({"note": params.get("note", "")}), newest["m"], int(delay)))
    return {"scheduled_in_min": delay}


SYSTEM_VERBS = {
    "register_entity": register_entity,
    "update_entity": update_entity,
    "set_tripwire": set_tripwire,
    "clear_tripwire": clear_tripwire,
    "schedule_check": schedule_check,
}
