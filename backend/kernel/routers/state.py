"""GET /state: the prompt-sized world view for the agent."""

from fastapi import APIRouter, Depends, HTTPException

from ..auth import require_token
from ..db import current_run_id, q

router = APIRouter(dependencies=[Depends(require_token)])


def _run() -> str:
    rid = current_run_id()
    if not rid:
        raise HTTPException(409, "no active run; POST /runs first")
    return rid


@router.get("/zones")
def zones():
    return {"zones": [r["doc"] for r in q("select doc from zones where run_id=%s", (_run(),))]}


@router.get("/state")
def state(format: str = "json"):
    """format=string wraps the whole state as one JSON string field, so a
    HappyRobot GET node exposes it as a single template variable."""
    rid = _run()
    ents = q("select doc, units_available from entities where run_id=%s", (rid,))
    assignments = q("""select entity_id, action_id, units, zone from assignments
                       where run_id=%s and status='active'""", (rid,))
    by_entity: dict[str, list] = {}
    for a in assignments:
        by_entity.setdefault(a["entity_id"], []).append(
            {"action": a["action_id"], "units": a["units"], "zone": a["zone"]})
    entities = []
    for r in ents:
        d = dict(r["doc"])
        if d.get("units"):
            d["units"]["available"] = r["units_available"]
        if d["id"] in by_entity:
            d["active_assignments"] = by_entity[d["id"]]
        entities.append(d)

    recent = q("""select doc, confidence from signals where run_id=%s
                  and ((confidence in ('medium','high') and jsonb_array_length(doc->'claims') > 0)
                       or (doc->'perception'->>'is_noise') = 'false' and jsonb_array_length(doc->'claims') = 0)
                  order by t desc limit 12""", (rid,))
    situation = q("select doc, updated_at from situation where run_id=%s", (rid,), one=True)
    tws = q("select doc, set_by, status from tripwires where run_id=%s and status='active'", (rid,))
    pending = q("""select doc from actions where run_id=%s and status='pending_approval'
                   order by t desc limit 10""", (rid,))
    recent_actions = q("""select doc from actions where run_id=%s
                          order by created_at desc limit 15""", (rid,))
    out = {
        "recent_actions": [r["doc"] for r in recent_actions],
        "zones": [r["doc"] for r in q("select doc from zones where run_id=%s", (rid,))],
        "entities": entities,
        "situation": situation["doc"] if situation else {},
        "active_tripwires": [{**r["doc"], "set_by": r["set_by"]} for r in tws],
        "recent_signals": [dict(r["doc"], confidence=r["confidence"]) for r in recent],
        "pending_approval": [r["doc"] for r in pending],
    }
    if format == "string":
        import json as _json
        return {"state_json": _json.dumps(out, ensure_ascii=False, default=str)}
    return out
