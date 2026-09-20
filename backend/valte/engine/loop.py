"""One tick per second per running crisis: advance the scenario, run the
timers, decide whether a brain must wake, then do the HTTP work."""

import asyncio
import logging
from datetime import datetime

from sqlalchemy import select

from valte import bus
from valte.core import actions, incidents, learning, logistics, outreach, tripwires
from valte.core.events import append_event
from valte.core.world import clock_dict, scenario_now
from valte.db import crisis_lock, session_scope
from valte.engine import dispatch, patrol, reconcile, wake
from valte.models import Crisis, ScheduledCheck
from valte.sim.runner import sim_step

log = logging.getLogger("valte.engine")


def _active_ids() -> list[str]:
    with session_scope() as db:
        return list(db.scalars(select(Crisis.id).where(Crisis.status == "active", Crisis.started_at.is_not(None))))


def tick(crisis_id: str) -> None:
    with crisis_lock(crisis_id), session_scope() as db:
        c = db.get(Crisis, crisis_id)
        if c is None or c.status != "active":
            return
        if not (c.wake or {}).get("inc_backfill"):  # crises older than the incident model get theirs from their signals
            incidents.backfill(db, c)
            c.wake = {**(c.wake or {}), "inc_backfill": True}
        if not (c.wake or {}).get("inc_regroup"):  # once: untangle what the first grouping rules lumped together
            incidents.regroup(db, c)
            c.wake = {**(c.wake or {}), "inc_regroup": True}
        # People keep answering (or not) even while the scenario is paused.
        outreach.expire_rings(db, c)
        actions.expire_approvals(db, c)
        if c.paused:
            return

        now_s = scenario_now(c)
        w = dict(c.wake or {})
        if not w.get("reflexes"):  # crises declared before the standing reflexes existed get them too
            from valte.core.needs import add_default_reflexes

            add_default_reflexes(db, c)
            w["reflexes"] = True
        last = datetime.fromisoformat(w["last_tick_s"]) if w.get("last_tick_s") else now_s
        w["last_tick_s"] = now_s.isoformat()
        c.wake = w

        sim_step(db, c)
        tripwires.evaluate_silence(db, c, now_s)
        for chk in db.scalars(select(ScheduledCheck).where(ScheduledCheck.crisis_id == c.id,
                                                           ScheduledCheck.done.is_(False),
                                                           ScheduledCheck.due_t <= now_s)):
            chk.done = True
            append_event(db, c, "check.due", {"note": chk.note}, material=True,
                         digest=f"Scheduled check is due: {chk.note}")
        freed = actions.release_due_units(db, c)
        if freed:
            from valte.core.needs import open_needs

            waiting = open_needs(db, c)
            if waiting:  # scarcity eased: whoever had to wait gets another look, now
                append_event(db, c, "needs.retry", {"freed_units": freed, "waiting": [n["signal_id"] for n in waiting]},
                             material=True, digest=f"{freed} unit(s) are free again and {len(waiting)} need(s) still wait: "
                                                   + ", ".join(n["signal_id"] for n in waiting[:6]) + ". Reassign now.")
        actions.tick_world(db, c, max(0.0, (now_s - last).total_seconds() / 60.0))
        incidents.sync(db, c)  # attended / resolved follow the actions and the hazard
        n = int(w.get("learn_n", 0)) + 1
        c.wake = {**(c.wake or {}), "learn_n": n}
        if n % 5 == 0:
            learning.learn_now(db, c)  # what this crisis has taught so far applies from now on
        logistics.deliver_due(db, c, now_s)
        wake.maybe_wake_command(db, c)
        wake.maybe_wake_coordinator(db, c)
        patrol.maybe_patrol(db, c)  # nobody woke it: it does the rounds
        bus.publish(c.id, {"type": "clock.tick", "crisis_id": c.id, "payload": clock_dict(c)})


async def run_forever() -> None:
    log.info("engine loop started")
    n = 0
    while True:
        try:
            for cid in await asyncio.to_thread(_active_ids):
                await asyncio.to_thread(tick, cid)
            await dispatch.drain_outbox()
            n += 1
            if n % 2 == 0:
                await reconcile.poll_runs()
            if n % 3 == 0:
                await reconcile.poll_calls()
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("engine tick failed")
        await asyncio.sleep(1.0)
