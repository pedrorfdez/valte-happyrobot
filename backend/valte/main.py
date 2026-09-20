import asyncio
import logging
from contextlib import asynccontextmanager
from typing import Any

from fastapi import BackgroundTasks, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import select

from valte import bus, manuals
from valte.api.gate import ExternalGate
from valte.api import dashboard, gateway, hr_callbacks, kernel, stt, voice
from valte.db import init_db, session_scope
from valte.engine import loop
from valte.hr.client import hr
from valte.models import HrWorkflow
from valte.settings import ROOT_DIR, public_base_url, settings

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("valte")


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    bus.bind_loop(asyncio.get_running_loop())
    if not settings.happyrobot_webhook_secret:
        log.warning("HAPPYROBOT_WEBHOOK_SECRET is empty: HappyRobot callbacks are NOT authenticated")
    if settings.valte_outreach_mode == "real" and not settings.demo_email_to:
        log.warning("DEMO_EMAIL_TO is empty: email contacts will fail instead of being sent")
    engine_task = asyncio.create_task(loop.run_forever())
    try:
        yield
    finally:
        engine_task.cancel()
        await hr().aclose()


app = FastAPI(title="Valte v2 — crisis kernel", version="0.2.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in settings.cors_origins.split(",") if o.strip()],
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(ExternalGate)  # added last = outermost: nothing from outside gets past it unchecked
for r in (kernel.router, gateway.router, dashboard.router, voice.router, stt.router, hr_callbacks.router):
    app.include_router(r)


class FreshStaticFiles(StaticFiles):
    """The front is rebuilt all the time. Without this a browser may keep yesterday's valte-live.js under today's page
    (heuristic caching on Last-Modified), which breaks the page. no-cache = always revalidate; the ETag keeps it a 304."""

    async def get_response(self, path: str, scope):
        response = await super().get_response(path, scope)
        response.headers["Cache-Control"] = "no-cache"
        return response


FRONT_DIR = ROOT_DIR / "frontend" / "dist"
if FRONT_DIR.exists():
    app.mount("/app", FreshStaticFiles(directory=str(FRONT_DIR), html=True), name="front")


@app.get("/", include_in_schema=False)
def root() -> RedirectResponse:
    return RedirectResponse("/app/" if FRONT_DIR.exists() else "/docs")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/meta")
def meta() -> dict[str, Any]:
    """What is wired: handy on stage when something looks off."""
    with session_scope() as db:
        workflows = {w.name: w.workflow_id for w in db.scalars(select(HrWorkflow))}
    return {"public_base_url": public_base_url(), "brain": settings.valte_brain,
            "outreach_mode": settings.valte_outreach_mode, "email_configured": bool(settings.demo_email_to),
            "callbacks_authenticated": bool(settings.happyrobot_webhook_secret),
            "hr_api_key": bool(settings.happyrobot_api_key), "workflows": workflows,
            "dictation": stt.available()}


@app.post("/crises/{crisis_id}/manuals/lookup", tags=["dashboard"])
async def lookup_manuals(crisis_id: str, background: BackgroundTasks, q: str | None = None) -> dict[str, Any]:
    """Official protocols for this crisis (Exa). Runs in the background."""
    with session_scope() as db:
        from valte.models import Crisis

        c = db.get(Crisis, crisis_id)
        situation = q or (f"{c.hazard_type} {c.name} {c.region}" if c else "")
    background.add_task(manuals.lookup_for, crisis_id, situation)
    return {"queued": True, "query": situation}
