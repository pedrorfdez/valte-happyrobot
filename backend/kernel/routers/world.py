"""World-facing ground-truth ingress: the simulator (or reality) reports
entity changes that no signal announces. Emits entity_changed so the
agent reconsiders plans built on the old truth."""

from fastapi import APIRouter, Depends, HTTPException, Request

from ..auth import require_token
from ..db import current_run_id, js, q
from ..services.outbox import emit_event
from ..validation import validate

router = APIRouter(dependencies=[Depends(require_token)])


@router.post("/world/patches")
async def world_patch(request: Request):
    body = await request.json()
    rid = current_run_id()
    if not rid:
        raise HTTPException(409, "no active run")
    eid, fields = body.get("entity"), body.get("set") or {}
    if not eid or not fields:
        raise HTTPException(422, "body must be {entity, set}")
    row = q("select doc from entities where run_id=%s and id=%s", (rid, eid), one=True)
    if not row:
        raise HTTPException(404, f"entity {eid} not found")
    doc = row["doc"]
    for k, v in fields.items():
        doc[k] = {**doc[k], **v} if isinstance(v, dict) and isinstance(doc.get(k), dict) else v
    validate(doc, "entity")
    q("update entities set doc=%s, status=%s, units_available=%s where run_id=%s and id=%s",
      (js(doc), doc["status"], (doc.get("units") or {}).get("available"), rid, eid))
    emit_event(rid, "entity_changed",
               {"entity": eid, "detail": f"ground truth changed: {sorted(fields)}"})
    return {"entity": eid, "applied": sorted(fields)}
