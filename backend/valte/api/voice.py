"""Browser voice calls. The API key never leaves the backend: the front
asks us for a LiveKit token and joins the room with livekit-client."""

import asyncio
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from valte.api.deps import crisis_tx
from valte.core import outreach, world
from valte.core.events import append_event
from valte.core.intake import submit_raw_input
from valte.db import session_scope
from valte.engine.reconcile import _queue_outcome
from valte.hr import registry
from valte.hr.client import hr
from valte.models import Contact, Entity

router = APIRouter(tags=["voice"])


def _workflow_id(name: str) -> str:
    with session_scope() as db:
        wf = registry.get(db, name)
        if wf is None:
            raise HTTPException(status_code=503, detail=f"{name} no está aprovisionado en HappyRobot")
        return wf.workflow_id


def _flat(brief: dict[str, Any]) -> dict[str, str]:
    """Web-call `data` travels as participant attributes: strings only."""
    return {k: (", ".join(map(str, v)) if isinstance(v, list) else "" if v is None else str(v)) for k, v in brief.items()}


@router.post("/crises/{crisis_id}/contacts/{contact_id}/answer")
async def answer(crisis_id: str, contact_id: str) -> dict[str, Any]:
    """The human playing the entity picks up: start the call with the agent."""
    def check() -> dict[str, Any]:
        with crisis_tx(crisis_id) as (db, c):
            k = db.get(Contact, contact_id)
            if k is None or k.crisis_id != c.id:
                raise HTTPException(status_code=404, detail="contact not found")
            if k.channel != "voice" or k.status != "ringing":
                raise HTTPException(status_code=409, detail=f"contact is {k.channel}/{k.status}, cannot be answered")
            ent = db.get(Entity, (c.id, k.entity_id))
            if ent is not None and (ent.extra or {}).get("sim_unreachable"):
                raise HTTPException(status_code=409, detail="esta entidad no contesta (no se puede descolgar)")
            return k.brief

    brief = await asyncio.to_thread(check)
    token = await hr().voice_token(workflow_id=_workflow_id(registry.OUTREACH_CALL),
                                   data={"contact_id": contact_id, **_flat(brief)})

    def mark() -> None:
        with crisis_tx(crisis_id) as (db, c):
            k = db.get(Contact, contact_id)
            if k and k.status == "ringing":
                outreach.answer_contact(db, c, k, hr_run_id=token["run_id"])

    await asyncio.to_thread(mark)
    return token


async def _session_token(crisis_id: str, contact_id: str, takeover: bool) -> dict[str, Any]:
    def load() -> tuple[str | None, str | None]:
        with crisis_tx(crisis_id) as (db, c):
            k = db.get(Contact, contact_id)
            if k is None or k.status != "in_progress":
                raise HTTPException(status_code=409, detail="no hay llamada en curso")
            return k.hr_session_id, k.hr_run_id

    session_id, run_id = await asyncio.to_thread(load)
    if not session_id and run_id:
        sessions = await hr().run_sessions(run_id)
        session_id = sessions[-1]["id"] if sessions else None
    if not session_id:
        raise HTTPException(status_code=409, detail="la sesión de voz aún no existe")
    token = await hr().voice_token(session_id=session_id, takeover=takeover)

    def note() -> None:
        with crisis_tx(crisis_id) as (db, c):
            append_event(db, c, "contact.supervised", {"contact_id": contact_id, "mode": "takeover" if takeover else "listen"})

    await asyncio.to_thread(note)
    return token


@router.post("/crises/{crisis_id}/contacts/{contact_id}/listen")
async def listen(crisis_id: str, contact_id: str) -> dict[str, Any]:
    """Hidden, subscribe-only: the agent keeps talking."""
    return await _session_token(crisis_id, contact_id, takeover=False)


@router.post("/crises/{crisis_id}/contacts/{contact_id}/takeover")
async def takeover(crisis_id: str, contact_id: str) -> dict[str, Any]:
    """The supervisor takes the call; the agent drops."""
    return await _session_token(crisis_id, contact_id, takeover=True)


async def _finish(crisis_id: str, contact_id: str, cancel: bool) -> dict[str, Any]:
    def load() -> str | None:
        with crisis_tx(crisis_id) as (db, c):
            k = db.get(Contact, contact_id)
            if k is None:
                raise HTTPException(status_code=404, detail="contact not found")
            return k.hr_run_id if k.status == "in_progress" else None

    run_id = await asyncio.to_thread(load)
    if run_id is None:
        return {"status": "not_in_progress"}
    if cancel:
        try:
            await hr().cancel_run(run_id)
        except Exception:
            pass  # already over, or nobody ever joined: both fine
    try:
        lines, session_id = await hr().transcript(run_id)
    except Exception:
        lines, session_id = [], None  # no record of the call = nobody spoke

    def done() -> dict[str, Any]:
        with crisis_tx(crisis_id) as (db, c):
            k = db.get(Contact, contact_id)
            k.hr_session_id = session_id or k.hr_session_id
            outreach.finish_call(db, c, k, lines)
            _queue_outcome(db, c, k)
            return world.contact_dict(k)

    return await asyncio.to_thread(done)


@router.post("/crises/{crisis_id}/contacts/{contact_id}/hangup")
async def hangup(crisis_id: str, contact_id: str) -> dict[str, Any]:
    return await _finish(crisis_id, contact_id, cancel=True)


@router.post("/crises/{crisis_id}/contacts/{contact_id}/ended")
async def ended(crisis_id: str, contact_id: str) -> dict[str, Any]:
    """The browser left the room: read the transcript now instead of waiting for the poll."""
    return await _finish(crisis_id, contact_id, cancel=False)


# ── inbound voice: declare a crisis, or call 112 as a citizen ────────────


class TokenIn(BaseModel):
    data: dict[str, Any] = {}


class FinishIn(BaseModel):
    kind: str  # crisis-start | emergency-call
    crisis_id: str | None = None


@router.post("/voice/crisis-start/token")
async def crisis_start_token(body: TokenIn | None = None) -> dict[str, Any]:
    return await hr().voice_token(workflow_id=_workflow_id(registry.CRISIS_START), data=_flat((body.data if body else {}) or {}))


@router.post("/voice/emergency-call/token")
async def emergency_call_token(body: TokenIn | None = None) -> dict[str, Any]:
    return await hr().voice_token(workflow_id=_workflow_id(registry.EMERGENCY_CALL), data=_flat((body.data if body else {}) or {}))


@router.post("/voice/calls/{run_id}/finish")
async def finish_voice(run_id: str, body: FinishIn) -> dict[str, Any]:
    lines, _ = await hr().transcript(run_id, agent="Operador", human="Llamante")
    text = "\n".join(f"{ln['who']}: {ln['text']}" for ln in lines)
    said = " ".join(ln["text"] for ln in lines if ln["who"] != "Operador")

    def work() -> dict[str, Any]:
        if body.kind == "emergency-call":
            if not body.crisis_id:
                raise HTTPException(status_code=422, detail="crisis_id is required for emergency-call")
            with crisis_tx(body.crisis_id) as (db, c):
                raw = submit_raw_input(db, c, channel="call", source="112",
                                       payload={"caller": "llamada web", "transcript": said or text})
                return {"kind": body.kind, "signal_id": raw.id, "transcript": text}
        with session_scope() as db:  # crisis-start: a draft the wizard completes
            c = world.create_crisis(db, {"name": (said[:60] or "Crisis declarada por voz"), "source": "voice",
                                         "transcript": text})
            return {"kind": body.kind, "crisis": {"id": c.id, "code": c.code, "name": c.name}, "transcript": text}

    return await asyncio.to_thread(work)
