"""Crisis kernel entrypoint. uvicorn kernel.main:app --port 8100"""

import asyncio
import contextlib
import subprocess
from contextlib import asynccontextmanager

from fastapi import FastAPI

from .config import settings
from .db import current_run_id, pool, q
from .routers import (actions, entities, perceptions, runs, signals, situation,
                      state, tripwires, world)
from .services import outbox, reflexes


def _sweep_once():
    reflexes.sweep_silence()
    _fire_due_timers()
    outbox.sweep()


async def sweep_loop():
    while True:
        try:
            # blocking DB and webhook work runs off the event loop
            await asyncio.to_thread(_sweep_once)
        except Exception as e:  # the sweep must never die
            print(f"sweep error: {e}")
        await asyncio.sleep(settings.sweep_interval_s)


def _fire_due_timers():
    rid = current_run_id()
    if not rid:
        return
    newest = q("select max(t) as m from signals where run_id=%s", (rid,), one=True)
    if not newest or not newest["m"]:
        return
    due = q("""update events set status='pending'
               where run_id=%s and status='timer' and due_t <= %s
               returning pk""", (rid, newest["m"]))
    if due:
        outbox.dispatch_coordinator()


@asynccontextmanager
async def lifespan(app: FastAPI):
    pool.open()
    task = asyncio.create_task(sweep_loop())
    yield
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task
    pool.close()


app = FastAPI(title="Valte crisis kernel", lifespan=lifespan)
for r in (runs, state, entities, signals, perceptions, actions, situation, tripwires, world):
    app.include_router(r.router)


@app.get("/healthz")
def healthz():
    db_ok = bool(q("select 1 as ok", one=True))
    commit = subprocess.run(["git", "rev-parse", "--short", "HEAD"],
                            capture_output=True, text=True).stdout.strip()
    return {"ok": db_ok, "commit": commit or "unknown"}
