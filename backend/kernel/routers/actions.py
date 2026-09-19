"""The action pipeline: validation, invariants, units ledger, approval
gate, system verbs. The kernel does not trust the agent: everything is
checked, and rejections explain themselves so the LLM can re-plan."""

from datetime import datetime

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from psycopg.rows import dict_row

from ..auth import require_token
from ..db import current_run_id, js, pool, q
from ..services.outbox import emit_event, mark_agent_responded
from ..services.verbs import SYSTEM_VERBS
from ..validation import validate

router = APIRouter(dependencies=[Depends(require_token)])

UNIT_VERBS = {"rescue", "pump_water", "shelter", "supplies", "wellness_check", "heavy_equipment"}


def _run() -> str:
    rid = current_run_id()
    if not rid:
        raise HTTPException(409, "no active run; POST /runs first")
    return rid


@router.post("/actions", status_code=201)
async def create_action(request: Request,
                        idempotency_key: str | None = Header(default=None)):
    action = await request.json()
    rid = _run()
    validate(action, "action")

    if idempotency_key:
        dup = q("select doc from actions where run_id=%s and idempotency_key=%s",
                (rid, idempotency_key), one=True)
        if dup:
            return {"action": dup["doc"], "idempotent_replay": True}
    if q("select 1 from actions where run_id=%s and id=%s", (rid, action["id"]), one=True):
        raise HTTPException(409, f"action id {action['id']} already exists")

    # evidence refs must exist
    for ref in action["evidence"]:
        if ref.startswith("sig-") and not q(
                "select 1 from signals where run_id=%s and id=%s", (rid, ref), one=True):
            raise HTTPException(422, f"evidence {ref} does not reference a known signal")
        if ref.startswith("act-") and not q(
                "select 1 from actions where run_id=%s and id=%s", (rid, ref), one=True):
            raise HTTPException(422, f"evidence {ref} does not reference a known action")

    verb, actor_id = action["verb"], action["actor"]
    result = None

    if actor_id == "system":
        fn = SYSTEM_VERBS.get(verb)
        if not fn:
            raise HTTPException(422, f"unknown system verb {verb}; system verbs: {sorted(SYSTEM_VERBS)}")
        result = fn(rid, action.get("params", {}), action.get("actor", "agent")) \
            if verb == "set_tripwire" else fn(rid, action.get("params", {}))
        action["status"] = "executed"
        q("insert into actions (run_id,id,t,actor,verb,status,idempotency_key,doc) values (%s,%s,%s,%s,%s,%s,%s,%s)",
          (rid, action["id"], action["t"], actor_id, verb, "executed", idempotency_key, js(action)))
        mark_agent_responded()
        return {"action": action, "result": result}

    # world verb: actor invariants
    actor = q("select doc, status, units_available from entities where run_id=%s and id=%s",
              (rid, actor_id), one=True)
    if not actor:
        raise HTTPException(422, f"actor {actor_id} is not a registered entity")
    adoc = actor["doc"]
    if actor["status"] == "unreachable":
        esc = adoc.get("escalation_to")
        raise HTTPException(409, f"actor {actor_id} is unreachable; escalate to {esc or 'human supervisor'}")
    if verb not in (adoc.get("capabilities") or []):
        raise HTTPException(422, f"{actor_id} cannot {verb}; its capabilities are {adoc.get('capabilities')}")
    juris = adoc.get("jurisdiction") or []
    if juris:
        outside = [z for z in action.get("target_zones", []) if z not in juris]
        if outside:
            raise HTTPException(422, f"{actor_id} has no jurisdiction over {outside}; jurisdiction: {juris}")

    needs_approval = (adoc.get("activation") or {}).get("cost") == "high"
    status = "pending_approval" if needs_approval else "approved"
    action["status"] = status

    units = int(action.get("params", {}).get("units", 1)) if verb in UNIT_VERBS and adoc.get("units") else 0

    # transactional: lock actor row, check availability, write action + assignment
    with pool.connection() as conn:
        conn.row_factory = dict_row
        if units:
            row = conn.execute(
                "select units_available from entities where run_id=%s and id=%s for update",
                (rid, actor_id)).fetchone()
            if row["units_available"] < units:
                busy = conn.execute(
                    "select action_id, units, zone from assignments where run_id=%s and entity_id=%s and status='active'",
                    (rid, actor_id)).fetchall()
                detail = ", ".join(f"{b['units']} on {b['action_id']} ({b['zone']})" for b in busy) or "none"
                raise HTTPException(409,
                    f"{actor_id} has {row['units_available']} unit(s) available, {units} requested. "
                    f"Active assignments: {detail}. Reduce units, wait, or use another responder.")
            conn.execute("update entities set units_available = units_available - %s where run_id=%s and id=%s",
                         (units, rid, actor_id))
            conn.execute(
                "insert into assignments (run_id, action_id, entity_id, units, zone) values (%s,%s,%s,%s,%s)",
                (rid, action["id"], actor_id, units,
                 (action.get("target_zones") or [None])[0]))
        conn.execute(
            "insert into actions (run_id,id,t,actor,verb,status,idempotency_key,doc) values (%s,%s,%s,%s,%s,%s,%s,%s)",
            (rid, action["id"], action["t"], actor_id, verb, status, idempotency_key, js(action)))

    if needs_approval:
        emit_event(rid, "action_pending_approval",
                   {"action_id": action["id"], "detail": f"{actor_id} {verb} awaits human approval"})
    mark_agent_responded()
    return {"action": action, "units_committed": units}


@router.patch("/actions/{action_id}")
async def patch_action(action_id: str, request: Request):
    patch = await request.json()
    rid = _run()
    row = q("select doc, status from actions where run_id=%s and id=%s", (rid, action_id), one=True)
    if not row:
        raise HTTPException(404, f"action {action_id} not found")
    new_status = patch.get("status")
    if new_status not in ("in_progress", "executed", "failed"):
        raise HTTPException(422, "status must be in_progress, executed, or failed")
    doc = row["doc"]
    doc["status"] = new_status
    if patch.get("real_interaction"):
        doc["real_interaction"] = patch["real_interaction"]
    if patch.get("result_note"):
        doc["result_note"] = patch["result_note"]
    q("update actions set status=%s, doc=%s where run_id=%s and id=%s",
      (new_status, js(doc), rid, action_id))
    if new_status in ("executed", "failed"):
        _release_assignment(rid, action_id)
    if new_status == "failed":
        actor = q("select doc from entities where run_id=%s and id=%s", (rid, doc["actor"]), one=True)
        esc = (actor["doc"].get("escalation_to") if actor else None)
        emit_event(rid, "action_failed",
                   {"action_id": action_id, "detail": patch.get("result_note", ""),
                    "escalate_to": esc})
    return {"action": doc}


def _release_assignment(rid: str, action_id: str):
    rows = q("""update assignments set status='released', released_at=now()
                where run_id=%s and action_id=%s and status='active'
                returning entity_id, units""", (rid, action_id))
    for r in rows or []:
        q("update entities set units_available = units_available + %s where run_id=%s and id=%s",
          (r["units"], rid, r["entity_id"]))


@router.post("/actions/{action_id}/approve")
def approve(action_id: str):
    return _gate(action_id, "approved")


@router.post("/actions/{action_id}/reject")
def reject(action_id: str):
    return _gate(action_id, "rejected")


def _gate(action_id: str, new_status: str):
    rid = _run()
    row = q("select doc, status from actions where run_id=%s and id=%s", (rid, action_id), one=True)
    if not row:
        raise HTTPException(404, f"action {action_id} not found")
    if row["status"] != "pending_approval":
        raise HTTPException(409, f"action {action_id} is {row['status']}, not pending_approval")
    doc = row["doc"]
    doc["status"] = new_status
    q("update actions set status=%s, doc=%s where run_id=%s and id=%s",
      (new_status, js(doc), rid, action_id))
    if new_status == "rejected":
        _release_assignment(rid, action_id)
    emit_event(rid, f"action_{new_status}",
               {"action_id": action_id, "detail": f"human {new_status} {doc['actor']} {doc['verb']}"})
    return {"action": doc}


@router.get("/actions")
def list_actions(status: str = "", limit: int = 50):
    rid = _run()
    sql = "select doc from actions where run_id=%s"
    params: list = [rid]
    if status:
        sql += " and status=%s"; params.append(status)
    sql += " order by created_at desc limit %s"; params.append(min(limit, 200))
    return {"actions": [r["doc"] for r in q(sql, tuple(params))]}
