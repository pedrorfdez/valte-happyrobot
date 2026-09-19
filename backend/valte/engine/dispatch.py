"""Drains the outbox: the only place the engine starts HappyRobot runs."""

import asyncio
import logging
from typing import Any

from valte.core import outreach
from valte.core.events import append_event
from valte.core.intake import apply_fallback
from valte.db import crisis_lock, session_scope
from valte.engine import local_brain, patrol, wake
from valte.hr import registry
from valte.hr.client import hr
from valte.models import Contact, Crisis, HrRun, Outbox, RawInput

log = logging.getLogger("valte.dispatch")
_sem = asyncio.Semaphore(4)


def _claim() -> list[dict[str, Any]]:
    from sqlalchemy import select

    with session_scope() as db:
        rows = list(db.scalars(select(Outbox).where(Outbox.status == "pending").order_by(Outbox.id).limit(12)))
        out = []
        for r in rows:
            wf = registry.get(db, r.workflow)
            r.status = "sending"
            out.append({"id": r.id, "crisis_id": r.crisis_id, "workflow": r.workflow, "purpose": r.purpose,
                        "ref_id": r.ref_id, "payload": r.payload, "workflow_id": wf.workflow_id if wf else None})
        return out


def _sent(row: dict[str, Any], run_id: str) -> None:
    with crisis_lock(row["crisis_id"]), session_scope() as db:
        ob = db.get(Outbox, row["id"])
        ob.status = "sent"
        db.add(HrRun(run_id=run_id, crisis_id=row["crisis_id"], workflow=row["workflow"], purpose=row["purpose"],
                     ref_id=row["ref_id"]))
        c = db.get(Crisis, row["crisis_id"])
        if row["purpose"] in ("ingest", "intake"):
            raw = db.get(RawInput, (row["crisis_id"], row["ref_id"]))
            if raw:
                raw.state, raw.hr_run_id = "sent", run_id
        elif row["purpose"] == "outreach":
            k = db.get(Contact, row["ref_id"])
            if k and c:
                outreach.mark_sending(db, c, k, run_id)


def unsent(row: dict[str, Any], error: str) -> None:
    """HappyRobot could not take the job: degrade, visibly, and keep going."""
    with crisis_lock(row["crisis_id"]), session_scope() as db:
        ob = db.get(Outbox, row["id"])
        if ob:
            ob.status, ob.error = "failed", error[:500]
        c = db.get(Crisis, row["crisis_id"])
        if c is None:
            return
        append_event(db, c, "hr.error", {"workflow": row["workflow"], "purpose": row["purpose"], "error": error[:300]})
        purpose = row["purpose"]
        if purpose in ("ingest", "intake"):
            raw = db.get(RawInput, (c.id, row["ref_id"]))
            if raw and raw.state in ("queued", "sent"):
                apply_fallback(db, c, raw, reason=error[:120])
        elif purpose == "coordinator":
            wake.coordinator_done(c)
            local_brain.decide(db, c)
        elif purpose == "command":
            wake.command_done(c)
            local_brain.make_plan(db, c)
        elif purpose == "proactive":
            patrol.fallback(db, c)
        elif purpose == "outreach":
            k = db.get(Contact, row["ref_id"])
            if k:
                outreach.email_result(db, c, k, ok=False, error=f"HappyRobot: {error[:160]}")


async def _send(row: dict[str, Any]) -> None:
    async with _sem:
        if not row["workflow_id"]:
            await asyncio.to_thread(unsent, row, f"{row['workflow']} no está aprovisionado")
            return
        try:
            run_id = await hr().trigger_run(row["workflow_id"], row["payload"])
        except Exception as e:  # network, 4xx, guard: all degrade the same way
            log.warning("dispatch failed %s: %s", row["workflow"], e)
            await asyncio.to_thread(unsent, row, str(e))
            return
        await asyncio.to_thread(_sent, row, run_id)
        log.info("dispatched %s run=%s ref=%s", row["workflow"], run_id, row["ref_id"])


async def drain_outbox() -> None:
    rows = await asyncio.to_thread(_claim)
    if rows:
        await asyncio.gather(*(_send(r) for r in rows))
