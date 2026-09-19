"""The action pipeline: validation, invariants, units ledger, approval
gate, system verbs. The kernel does not trust the agent: everything is
checked, and rejections explain themselves so the LLM can re-plan."""

import json
from datetime import datetime

from fastapi import APIRouter, Body, Depends, Header, HTTPException, Request
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


def _body_or_query(request: Request, body: dict | None, json_param: str) -> dict:
    """HappyRobot webhook actions deliver tool arguments as query params;
    accept a JSON document either as the request body or as one param."""
    if body:
        return body
    raw = request.query_params.get(json_param)
    if raw:
        import json as _json
        try:
            return _json.loads(raw)
        except Exception:
            raise HTTPException(422, f"{json_param} is not valid JSON")
    return dict(request.query_params)


@router.post("/actions", status_code=201)
def create_action(request: Request, body: dict | None = Body(None),
                  idempotency_key: str | None = Header(default=None)):
    action = _body_or_query(request, body, "action_json")
    return submit_action(_run(), action, idempotency_key)


def _extract_json_objects(s: str) -> list[str]:
    """Pull balanced top-level {...} JSON objects out of any wrapper text
    (HappyRobot serializes object variables in Go map format, but the
    action strings inside remain valid JSON)."""
    out, depth, start, in_str, esc = [], 0, None, False, False
    for i, ch in enumerate(s):
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == "{":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0 and start is not None:
                out.append(s[start:i + 1])
                start = None
    return out


@router.post("/decisions", status_code=201)
def submit_decisions(request: Request, req_body: dict | None = Body(None)):
    """Batch ingress for the coordinator: one LLM turn returns several
    actions (each a JSON string, strict-schema friendly) plus a situation
    note. Invalid actions are reported per item, valid ones proceed."""
    body = _body_or_query(request, req_body, "decisions_json")
    rid = _run()
    hr_run_id = body.get("hr_run_id") or request.query_params.get("hr_run_id")
    raw_actions = body.get("actions") or []
    if isinstance(raw_actions, str):
        try:
            parsed = json.loads(raw_actions)
            raw_actions = parsed if isinstance(parsed, list) else [parsed]
        except Exception:
            raw_actions = _extract_json_objects(raw_actions)
    results = []
    for i, raw in enumerate(raw_actions):
        try:
            action = json.loads(raw) if isinstance(raw, str) else raw
        except Exception:
            results.append({"index": i, "error": "not valid JSON"})
            continue
        try:
            results.append({"index": i, "id": action.get("id"),
                            **submit_action(rid, action, None)})
            if hr_run_id:
                q("update actions set hr_run_id=%s where run_id=%s and id=%s",
                  (hr_run_id, rid, action["id"]))
        except HTTPException as e:
            results.append({"index": i, "id": action.get("id"), "error": str(e.detail)})
            # a refused decision is part of the story; keep it
            q("insert into events (run_id, type, lane, payload, status) values (%s,'action_rejected','audit',%s,'logged')",
              (rid, js({"attempted": action, "reason": str(e.detail),
                        "hr_run_id": hr_run_id})))
    situation_note = body.get("situation_note")
    if situation_note:
        row = q("select doc from situation where run_id=%s", (rid,), one=True)
        doc = row["doc"] if row else {}
        doc["notes"] = situation_note
        if body.get("emergency_level") not in (None, ""):
            try:
                doc["emergency_level"] = int(body["emergency_level"])
            except (TypeError, ValueError):
                pass
        if hr_run_id:
            doc["hr_run_id"] = hr_run_id
        q("update situation set doc=%s, updated_at=now() where run_id=%s", (js(doc), rid))
        q("insert into situation_history (run_id, doc) values (%s, %s)", (rid, js(doc)))
    mark_agent_responded()  # reopen the coordinator wake-up gate
    accepted = sum(1 for r in results if "error" not in r)
    return {"accepted": accepted, "rejected": len(results) - accepted, "results": results}


def submit_action(rid: str, action: dict, idempotency_key: str | None) -> dict:
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

    # duplicate guard: same actor+verb+zones in flight, or completed too
    # recently for conditions to have changed. Operations are repeatable:
    # a finished rescue does not block a new one later.
    zones_key = json.dumps(sorted(action.get("target_zones") or []))
    dup = q("""select id, status, t from actions
               where run_id=%s and actor=%s and verb=%s
                 and status in ('pending_approval','approved','in_progress','executed')
                 and coalesce((select json_agg(z order by z)::text
                               from jsonb_array_elements_text(doc->'target_zones') z), '[]') = %s
               order by created_at desc limit 1""",
            (rid, actor_id, verb, zones_key), one=True)
    if dup:
        blocked = dup["status"] != "executed"
        if not blocked:
            window_min = 30 if verb in UNIT_VERBS else 90
            newest = q("select max(t) as m from signals where run_id=%s", (rid,), one=True)
            if newest and newest["m"]:
                age_min = (newest["m"] - dup["t"]).total_seconds() / 60
                blocked = age_min < window_min
        if blocked:
            raise HTTPException(409,
                f"duplicate: {dup['id']} is already {dup['status']} for {actor_id} {verb} on the same zones. "
                f"Do not repeat it; act again only when it completes or conditions change materially.")

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
def patch_action(action_id: str, request: Request, body: dict | None = Body(None)):
    patch = _body_or_query(request, body, "patch_json")
    if patch.get("real_kind"):  # flattened query form
        patch["real_interaction"] = {"kind": patch.pop("real_kind"),
                                     "to": patch.pop("real_to", "")}
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
