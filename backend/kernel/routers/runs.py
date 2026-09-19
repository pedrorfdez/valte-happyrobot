"""Run lifecycle: a run instantiates a scenario pack (git) into the DB."""

import json
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException

from ..auth import require_token
from ..db import current_run_id, js, q

router = APIRouter(dependencies=[Depends(require_token)])
SCENARIOS_DIR = Path(__file__).resolve().parents[3] / "scenarios"


@router.post("/runs")
def create_run(body: dict):
    scenario_id = body.get("scenario_id")
    pack_dir = SCENARIOS_DIR / (scenario_id or "")
    if not pack_dir.is_dir():
        raise HTTPException(404, f"scenario pack not found: {scenario_id}")
    world = json.loads((pack_dir / "world.json").read_text())
    entities = json.loads((pack_dir / "entities.json").read_text())["entities"]

    run = q("insert into runs (scenario_id, seed, notes) values (%s,%s,%s) returning id",
            (scenario_id, body.get("seed"), body.get("notes", "")), one=True)
    run_id = str(run["id"])
    for z in world["zones"]:
        q("insert into zones (run_id,id,doc) values (%s,%s,%s)", (run_id, z["id"], js(z)))
    for e in entities:
        q("insert into entities (run_id,id,kind,status,provenance,units_available,doc) values (%s,%s,%s,%s,%s,%s,%s)",
          (run_id, e["id"], e["kind"], e["status"], e["provenance"],
           (e.get("units") or {}).get("available"), js(e)))
    q("insert into situation (run_id, doc) values (%s, %s)",
      (run_id, js({"assessment": {}, "plan": [], "notes": "run start"})))
    return {"run_id": run_id, "scenario": world["scenario"]["id"],
            "zones": len(world["zones"]), "entities": len(entities)}


@router.get("/runs/current")
def get_current():
    rid = current_run_id()
    if not rid:
        raise HTTPException(404, "no runs yet")
    row = q("select * from runs where id=%s", (rid,), one=True)
    row["id"] = str(row["id"])
    return row
