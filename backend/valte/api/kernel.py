"""Kernel contract — what the PedroD-ingest-* and PedroD-coordinator
workflows talk to: POST /perceptions, GET /state, POST /decisions."""

import json
from typing import Any

from fastapi import APIRouter, Depends, Query, Request

from valte.api.deps import crisis_tx, log_callback, loose_body, require_hr_bearer, resolve_crisis_id
from valte.core import actions
from valte.core.signals import ingest_perception, loose_json
from valte.core.world import build_state
from valte.engine import reconcile, wake

router = APIRouter(tags=["kernel"], dependencies=[Depends(require_hr_bearer)])


@router.post("/perceptions")
async def post_perception(request: Request) -> dict[str, Any]:
    body = await loose_body(request)
    log_callback("/perceptions", body)
    cid = resolve_crisis_id(body.get("crisis_id"))

    def work() -> dict[str, Any]:
        with crisis_tx(cid) as (db, c):
            run_id = body.get("hr_run_id")
            res = ingest_perception(db, c, body, hr_run_id=run_id)
            reconcile.mark_done(db, run_id)
            return {"id": res["id"], "noise": res["noise"], "confidence": res["confidence"]}

    from fastapi.concurrency import run_in_threadpool

    return await run_in_threadpool(work)


@router.get("/state")
def get_state(crisis_id: str | None = None, format: str = Query("json", pattern="^(json|string)$")) -> dict[str, Any]:
    cid = resolve_crisis_id(crisis_id)
    with crisis_tx(cid) as (db, c):
        state = build_state(db, c)
    # HappyRobot's GET node exposes top-level keys as variables: one string is easiest to prompt with.
    return {"state_json": json.dumps(state, ensure_ascii=False)} if format == "string" else state


@router.post("/decisions")
async def post_decisions(request: Request) -> dict[str, Any]:
    body = await loose_body(request)
    log_callback("/decisions", body)
    if "actions" not in body and body.get("decisions_json"):
        body.update(loose_json(body["decisions_json"], {}) or {})
    cid = resolve_crisis_id(body.get("crisis_id"))

    def work() -> dict[str, Any]:
        with crisis_tx(cid) as (db, c):
            wake.coordinator_done(c)
            reconcile.mark_done(db, body.get("hr_run_id"))
            return actions.submit_decisions(db, c, loose_json(body.get("actions"), []) or [],
                                            str(body.get("situation_note") or ""), body.get("emergency_level"))

    from fastapi.concurrency import run_in_threadpool

    return await run_in_threadpool(work)
