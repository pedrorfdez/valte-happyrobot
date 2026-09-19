"""Pull-based safety net. Callbacks are the fast path; if one never
arrives (tunnel down, HR node error) the engine reads the run's output
itself, and if HappyRobot gave nothing, falls back visibly."""

import asyncio
import json
import logging
from typing import Any

from sqlalchemy import select

from valte.core import actions, commands, outreach
from valte.core.events import append_event
from valte.core.intake import apply_fallback
from valte.core.plan import Conflict
from valte.core.signals import ingest_perception, loose_json, raw_text
from valte.core.world import contact_dict
from valte.db import crisis_lock, session_scope
from valte.engine import local_brain, patrol, wake
from valte.hr import registry
from valte.hr.client import hr
from valte.models import Contact, Crisis, HrRun, Outbox, RawInput, utcnow

log = logging.getLogger("valte.reconcile")
GRACE_S = {"ingest": 6, "intake": 8, "coordinator": 10, "proactive": 12, "command": 20, "outcome": 12, "outreach": 12}
TIMEOUT_S = {"ingest": 30, "intake": 35, "coordinator": 45, "proactive": 60, "command": 70, "outcome": 60, "outreach": 60}
DONE = ("completed", "succeeded")
DEAD = ("failed", "canceled", "skipped")


def mark_done(db, run_id: str | None) -> None:
    """Called by callback handlers: this run has reported by itself."""
    if run_id:
        run = db.get(HrRun, run_id)
        if run and run.status == "running":
            run.status, run.finished_at = "done", utcnow()


def _pending() -> list[dict[str, Any]]:
    with session_scope() as db:
        out = []
        for r in db.scalars(select(HrRun).where(HrRun.status == "running").limit(40)):
            wf = registry.get(db, r.workflow)
            out.append({"run_id": r.run_id, "crisis_id": r.crisis_id, "purpose": r.purpose, "ref_id": r.ref_id,
                        "age": (utcnow() - r.created_at).total_seconds(),
                        "extract": (wf.node_ids or {}).get("extract") if wf else None})
        return out


def _apply(r: dict[str, Any], response: dict[str, Any]) -> None:
    with crisis_lock(r["crisis_id"]), session_scope() as db:
        run, c = db.get(HrRun, r["run_id"]), db.get(Crisis, r["crisis_id"])
        if run is None or c is None or run.status != "running":
            return  # the callback won the race
        run.status, run.finished_at, run.result = "reconciled", utcnow(), response
        purpose = r["purpose"]
        if purpose == "ingest":
            raw = db.get(RawInput, (c.id, r["ref_id"]))
            content = raw_text(raw)
            ingest_perception(db, c, {**response, "id": r["ref_id"], "content": content}, hr_run_id=r["run_id"])
        elif purpose == "coordinator":
            wake.coordinator_done(c)
            if response.get("decisions_json"):
                response = loose_json(response["decisions_json"], {}) or {}
            actions.submit_decisions(db, c, response.get("actions") or [], response.get("situation_note", ""),
                                     response.get("emergency_level"))
        elif purpose == "proactive":
            patrol.apply_result(db, c, loose_json(response.get("decisions_json"), {}) or response)
        elif purpose in ("intake", "command", "outcome"):
            ctype = {"intake": "upsert_signal", "command": "replace_plan", "outcome": "record_outcome"}[purpose]
            ob = db.scalars(select(Outbox).where(Outbox.ref_id == r["ref_id"], Outbox.purpose == purpose)).first()
            if purpose == "command":
                wake.command_done(c)
            try:
                commands.apply_command(db, c, {
                    "command_id": f"{purpose}:{r['ref_id']}", "command_type": ctype,
                    "expected_plan_version": (ob.payload or {}).get("expected_plan_version") if ob else None,
                    "payload_json": response.get("payload_json") or response.get("command_json")}, hr_run_id=r["run_id"])
            except (commands.BadCommand, Conflict) as e:
                append_event(db, c, "hr.error", {"what": f"{purpose} result rejected", "error": str(e)})
        elif purpose == "outreach":
            k = db.get(Contact, r["ref_id"])
            if k:
                outreach.email_result(db, c, k, ok=True, subject=str(response.get("subject", "")),
                                      body=str(response.get("body", "")))


def _fail(r: dict[str, Any], why: str) -> None:
    with crisis_lock(r["crisis_id"]), session_scope() as db:
        run, c = db.get(HrRun, r["run_id"]), db.get(Crisis, r["crisis_id"])
        if run is None or c is None or run.status != "running":
            return
        run.status, run.finished_at, run.result = "failed", utcnow(), {"error": why}
        append_event(db, c, "hr.error", {"run_id": r["run_id"], "purpose": r["purpose"], "error": why})
        purpose = r["purpose"]
        if purpose in ("ingest", "intake"):
            raw = db.get(RawInput, (c.id, r["ref_id"]))
            if raw and raw.state in ("queued", "sent"):
                apply_fallback(db, c, raw, reason=why)
        elif purpose == "coordinator":
            wake.coordinator_done(c)
            local_brain.decide(db, c)
        elif purpose == "command":
            wake.command_done(c)
            local_brain.make_plan(db, c)
        elif purpose == "proactive":
            patrol.fallback(db, c)
        elif purpose == "outreach":
            k = db.get(Contact, r["ref_id"])
            if k:
                outreach.email_result(db, c, k, ok=False, error=why)


async def poll_runs() -> None:
    for r in await asyncio.to_thread(_pending):
        if r["age"] < GRACE_S.get(r["purpose"], 8):
            continue
        try:
            run = await hr().get_run(r["run_id"])
            status = run.get("status")
            if status in DONE:
                out = await hr().node_output(r["run_id"], r["extract"]) if r["extract"] else None
                response = ((out or {}).get("data") or {}).get("response")
                if isinstance(response, str):
                    response = json.loads(response)
                if isinstance(response, dict):
                    await asyncio.to_thread(_apply, r, response)
                else:
                    await asyncio.to_thread(_fail, r, "el run terminó sin salida legible")
            elif status in DEAD:
                await asyncio.to_thread(_fail, r, f"run {status} en HappyRobot")
            elif r["age"] > TIMEOUT_S.get(r["purpose"], 45):
                await asyncio.to_thread(_fail, r, "HappyRobot no respondió a tiempo")
        except Exception as e:
            log.warning("reconcile %s failed: %s", r["run_id"], e)
            if r["age"] > TIMEOUT_S.get(r["purpose"], 45):
                await asyncio.to_thread(_fail, r, f"sin respuesta de HappyRobot: {e}")


# ── live voice calls ─────────────────────────────────────────────────────


JOIN_GRACE_S = 45  # token minted but nobody ever joined the room


def _live_calls() -> list[dict[str, Any]]:
    with session_scope() as db:
        return [{"id": k.id, "crisis_id": k.crisis_id, "run_id": k.hr_run_id, "lines": len(k.transcript or []),
                 "age": (utcnow() - k.started_wall).total_seconds() if k.started_wall else 0}
                for k in db.scalars(select(Contact).where(Contact.status == "in_progress", Contact.hr_run_id.is_not(None)))]


def _update_call(call: dict[str, Any], lines: list[dict[str, Any]], session_id: str | None, ended: bool) -> None:
    with crisis_lock(call["crisis_id"]), session_scope() as db:
        k, c = db.get(Contact, call["id"]), db.get(Crisis, call["crisis_id"])
        if k is None or c is None or k.status != "in_progress":
            return
        k.hr_session_id = session_id or k.hr_session_id
        if ended:
            outreach.finish_call(db, c, k, lines)
            _queue_outcome(db, c, k)
        elif len(lines) != len(k.transcript or []):
            k.transcript = lines
            append_event(db, c, "contact.transcript", contact_dict(k))


def _queue_outcome(db, c: Crisis, k: Contact) -> None:
    """Let HappyRobot read the call and record what it achieved."""
    from valte.core.world import build_snapshot
    from valte.settings import public_base_url

    if not registry.usable(db, registry.OUTCOME) or not k.transcript:
        return
    db.add(Outbox(crisis_id=c.id, kind="hr_run", workflow=registry.OUTCOME, purpose="outcome", ref_id=k.id, payload={
        "dispatch_id": k.id, "run_id": c.id, "callback_base": public_base_url(), "interaction_mode": k.channel,
        "event": {"event_id": k.id, "type": "contact.completed", "action_id": k.action_id, "purpose": k.purpose,
                  "entity": k.entity_name, "brief": k.brief,
                  "transcript": "\n".join(f"{ln['who']}: {ln['text']}" for ln in k.transcript)},
        "snapshot_json": json.dumps({"run": build_snapshot(db, c)["run"]}, ensure_ascii=False)}))


async def poll_calls() -> None:
    for call in await asyncio.to_thread(_live_calls):
        try:
            run = await hr().run_exists(call["run_id"])
            if run is None:
                if call["age"] > JOIN_GRACE_S:
                    await asyncio.to_thread(_update_call, call, [], None, True)
                continue
            lines, session_id = await hr().transcript(call["run_id"])
            ended = run.get("status") in DONE + DEAD
            await asyncio.to_thread(_update_call, call, lines, session_id, ended)
        except Exception as e:
            log.warning("call poll %s failed: %s", call["run_id"], e)
