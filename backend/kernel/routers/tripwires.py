from fastapi import APIRouter, Depends

from ..auth import require_token
from ..db import current_run_id, q

router = APIRouter(dependencies=[Depends(require_token)])


@router.get("/tripwires")
def list_tripwires(status: str = ""):
    sql = "select id, status, set_by, doc, created_at from tripwires where run_id=%s"
    params: list = [current_run_id()]
    if status:
        sql += " and status=%s"; params.append(status)
    rows = q(sql + " order by created_at", tuple(params))
    return {"tripwires": [
        {**r["doc"], "id": r["id"], "status": r["status"], "set_by": r["set_by"]}
        for r in rows]}
