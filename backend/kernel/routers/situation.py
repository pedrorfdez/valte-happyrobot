from fastapi import APIRouter, Depends, HTTPException, Request

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
async def put_situation(request: Request):
    doc = await request.json()
    if not isinstance(doc, dict):
        raise HTTPException(422, "situation must be a JSON object")
    q("update situation set doc=%s, updated_at=now() where run_id=%s",
      (js(doc), current_run_id()))
    return {"situation": doc}
