from fastapi import APIRouter, Depends, HTTPException

from ..auth import require_token
from ..db import current_run_id, q

router = APIRouter(dependencies=[Depends(require_token)])


@router.get("/entities")
def list_entities():
    rid = current_run_id()
    rows = q("select doc, units_available from entities where run_id=%s", (rid,))
    out = []
    for r in rows:
        d = dict(r["doc"])
        if d.get("units"):
            d["units"]["available"] = r["units_available"]
        out.append(d)
    return {"entities": out}


@router.get("/entities/{entity_id}")
def get_entity(entity_id: str):
    row = q("select doc, units_available from entities where run_id=%s and id=%s",
            (current_run_id(), entity_id), one=True)
    if not row:
        raise HTTPException(404, f"entity {entity_id} not found")
    d = dict(row["doc"])
    if d.get("units"):
        d["units"]["available"] = row["units_available"]
    return d
