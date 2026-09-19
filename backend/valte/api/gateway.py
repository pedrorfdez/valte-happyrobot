"""Gateway contract — what PedroD-crisis-intake / -command /
-response-coordination talk to: GET /api/snapshot, POST /api/commands."""

from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from fastapi.concurrency import run_in_threadpool

from valte.api.deps import crisis_tx, log_callback, loose_body, require_hr_bearer, resolve_crisis_id
from valte.core import commands
from valte.core.plan import Conflict
from valte.core.world import build_snapshot
from valte.engine import reconcile, wake

router = APIRouter(prefix="/api", tags=["gateway"], dependencies=[Depends(require_hr_bearer)])


@router.get("/snapshot")
def get_snapshot(run_id: str | None = None) -> dict[str, Any]:
    cid = resolve_crisis_id(run_id)
    with crisis_tx(cid) as (db, c):
        return build_snapshot(db, c)


@router.post("/commands")
async def post_command(request: Request) -> JSONResponse:
    body = await loose_body(request)
    log_callback("/api/commands", body)
    if "payload" not in body and "payload_json" not in body:
        # Our workflows put the envelope in the query string and POST the payload as the raw body.
        envelope = ("command_id", "run_id", "command_type", "expected_plan_version", "actor", "causation_id", "hr_run_id")
        body = {**{k: body[k] for k in envelope if k in body},
                "payload": {k: v for k, v in body.items() if k not in envelope}}
    cid = resolve_crisis_id(body.get("run_id"))

    def work() -> tuple[int, dict[str, Any]]:
        # Errors are returned, not raised, so the bookkeeping above them commits.
        with crisis_tx(cid) as (db, c):
            run_id = body.get("hr_run_id")
            reconcile.mark_done(db, run_id)
            if body.get("command_type") == "replace_plan":
                wake.command_done(c)
            try:
                return 200, commands.apply_command(db, c, body, hr_run_id=run_id)
            except Conflict as e:
                return 409, {"accepted": False, "error": str(e), "plan_version": c.plan_version}
            except commands.BadCommand as e:
                return 422, {"accepted": False, "error": str(e)}

    status, payload = await run_in_threadpool(work)
    return JSONResponse(status_code=status, content=payload)
