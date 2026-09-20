from fastapi import APIRouter, Body, Depends, HTTPException, Request

from ..auth import require_token
from ..db import current_run_id, js, q

router = APIRouter(dependencies=[Depends(require_token)])


@router.get("/situation")
def get_situation():
    row = q("select doc, updated_at from situation where run_id=%s", (current_run_id(),), one=True)
    if not row:
        raise HTTPException(409, "no active run")
    return {"situation": row["doc"], "updated_at": row["updated_at"].isoformat()}


@router.put("/situation")
def put_situation(request: Request, doc: dict | None = Body(None)):
    if not doc:
        import json as _json
        raw = request.query_params.get("situation_json", "")
        try:
            doc = _json.loads(raw)
        except Exception:
            raise HTTPException(422, "situation_json is not valid JSON")
    if not isinstance(doc, dict):
        raise HTTPException(422, "situation must be a JSON object")
    rid = current_run_id()
    q("update situation set doc=%s, updated_at=now() where run_id=%s", (js(doc), rid))
    newest = q("select max(t) as m from signals where run_id=%s", (rid,), one=True)
    hist = {**doc, "scenario_t": newest["m"].isoformat() if newest and newest["m"] else None}
    q("insert into situation_history (run_id, doc) values (%s, %s)", (rid, js(hist)))
    return {"situation": doc}
