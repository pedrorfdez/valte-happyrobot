"""Judge-facing dashboard: GET /dashboard serves the page, GET
/dashboard-state serves everything it renders, run-scoped. The page is a
single static HTML file polling every 1.5 s; approvals POST back to the
kernel with the same key."""

from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, HTMLResponse

from ..config import settings
from ..db import current_run_id, q

router = APIRouter()
PAGE = Path(__file__).resolve().parents[2] / "dashboard" / "index.html"

UNIT_VERBS = {"rescue", "pump_water", "shelter", "supplies", "wellness_check", "heavy_equipment"}


@router.get("/dashboard")
def dashboard(key: str = ""):
    if key != settings.world_api_token:
        raise HTTPException(401, "add ?key=<WORLD_API_TOKEN> to the URL")
    html = PAGE.read_text().replace("__API_KEY__", settings.world_api_token)
    return HTMLResponse(html)


@router.get("/dashboard/basin.jpg")
def basin_image():
    return FileResponse(PAGE.parent / "basin.jpg", media_type="image/jpeg")


@router.get("/dashboard-state")
def dashboard_state(key: str = "", run_id: str = ""):
    if key != settings.world_api_token:
        raise HTTPException(401, "key required")
    rid = run_id or current_run_id()
    if not rid:
        raise HTTPException(409, "no runs yet")

    run = q("select id, scenario_id, notes, started_at, scenario_doc from runs where id=%s", (rid,), one=True)
    zones = [r["doc"] for r in q("select doc from zones where run_id=%s order by id", (rid,))]
    hazards = [dict(r) for r in q(
        "select id, zone, severity, trend from hazards where run_id=%s", (rid,))]
    entities = []
    for r in q("select doc, units_available, status from entities where run_id=%s order by id", (rid,)):
        d = dict(r["doc"])
        if d.get("units"):
            d["units"]["available"] = r["units_available"]
        d["status"] = r["status"]
        entities.append(d)
    assignments = q("""select entity_id, action_id, units, zone from assignments
                       where run_id=%s and status='active'""", (rid,))
    situation = q("select doc, updated_at from situation where run_id=%s", (rid,), one=True)
    sit_history = q("""select doc, written_at from situation_history
                       where run_id=%s order by pk desc limit 12""", (rid,))
    tripwires = q("select id, status, set_by, doc from tripwires where run_id=%s order by created_at, id", (rid,))
    actions = q("""select doc, hr_run_id, created_at from actions
                   where run_id=%s order by t desc, created_at desc limit 40""", (rid,))
    pending = [r["doc"] for r in q(
        "select doc from actions where run_id=%s and status='pending_approval' order by created_at desc", (rid,))]
    signals = q("""select doc, confidence from signals where run_id=%s
                   and (jsonb_array_length(doc->'claims') > 0
                        or (doc->'perception'->>'is_noise') = 'false')
                   order by t desc, received_at desc, id desc limit 18""", (rid,))
    rejected = q("""select payload, created_at from events
                    where run_id=%s and type='action_rejected'
                    order by pk desc limit 10""", (rid,))
    counts = q("""select
        (select count(*) from signals where run_id=%s) as signals_total,
        (select count(*) from signals where run_id=%s and jsonb_array_length(doc->'claims')=0) as noise,
        (select count(*) from actions where run_id=%s) as actions_total,
        (select count(*) from events where run_id=%s and type='action_rejected') as rejected_total,
        (select max(t) from signals where run_id=%s) as scenario_t""",
        (rid, rid, rid, rid, rid), one=True)

    latest = current_run_id()
    return {
        "latest_run_id": latest,
        "scenario": run["scenario_doc"] or {},
        "run": {"id": str(run["id"]), "scenario": run["scenario_id"],
                "notes": run["notes"], "started_at": run["started_at"].isoformat()},
        "scenario_t": counts["scenario_t"].isoformat() if counts["scenario_t"] else None,
        "zones": zones,
        "hazards": hazards,
        "entities": entities,
        "assignments": [dict(a) for a in assignments],
        "situation": situation["doc"] if situation else {},
        "situation_history": [
            {"t": r["doc"].get("scenario_t") or r["written_at"].isoformat(),
             "notes": r["doc"].get("notes", ""),
             "level": r["doc"].get("emergency_level")} for r in sit_history],
        "tripwires": [{**r["doc"], "id": r["id"], "status": r["status"], "set_by": r["set_by"]}
                      for r in tripwires],
        "actions": [dict(r["doc"], hr_run_id=r["hr_run_id"],
                         received_at=r["created_at"].isoformat()) for r in actions],
        "pending_approval": pending,
        "signals": [dict(r["doc"], confidence=r["confidence"]) for r in signals],
        "rejected": [{**r["payload"], "at": r["created_at"].isoformat()} for r in rejected],
        "counts": {k: counts[k] for k in ("signals_total", "noise", "actions_total", "rejected_total")},
    }
