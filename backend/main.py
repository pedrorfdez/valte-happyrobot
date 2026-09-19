from datetime import datetime, timezone
from typing import Any, Literal
from uuid import uuid4

from fastapi import BackgroundTasks, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from config import settings
from db import supabase
from crisis import CrisisIn, CrisisOut, declare_crisis
from workflows import create_voice_token, trigger_ticket_workflow

app = FastAPI(title="Valte backend", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in settings.cors_origins.split(",") if o.strip()],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


TicketKind = Literal["report", "proposal"]


class TicketIn(BaseModel):
    user_id: str = Field(..., description="User submitting the ticket.")
    entity_id: str = Field(..., description="Entity the user is assigned to.")
    kind: TicketKind = Field(..., description="'report' (this is happening) or 'proposal' (let's do this).")
    content: str = Field(..., min_length=1, description="Body read by the entity workflow.")
    subject: str | None = Field(None, description="Optional short summary for the UI.")
    payload: dict[str, Any] = Field(default_factory=dict)


class TicketOut(TicketIn):
    id: str
    workflow_run_id: str | None
    created_at: str


@app.post("/tickets", response_model=TicketOut, status_code=201)
async def create_ticket(ticket: TicketIn, background: BackgroundTasks) -> TicketOut:
    row = {
        "id": str(uuid4()),
        "user_id": ticket.user_id,
        "entity_id": ticket.entity_id,
        "kind": ticket.kind,
        "subject": ticket.subject,
        "content": ticket.content,
        "payload": ticket.payload,
        "workflow_run_id": None,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }

    try:
        result = supabase().table("tickets").insert(row).execute()
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"supabase insert failed: {e}") from e

    if not result.data:
        raise HTTPException(status_code=502, detail="supabase returned no row")

    saved = result.data[0]
    background.add_task(trigger_ticket_workflow, saved)
    return TicketOut(**saved)


class VoiceTokenIn(BaseModel):
    data: dict[str, Any] = Field(
        default_factory=dict, description="Extra context handed to the voice agent."
    )


class VoiceTokenOut(BaseModel):
    url: str
    token: str
    room_name: str
    run_id: str


@app.post("/crisis/voice-token", response_model=VoiceTokenOut)
async def crisis_voice_token(body: VoiceTokenIn | None = None) -> VoiceTokenOut:
    """Start a crisis intake: the dashboard's big button calls this, then
    joins the returned LiveKit room and talks to the `crisis-start` agent."""
    try:
        token = await create_voice_token((body.data if body else None) or {})
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"happyrobot voice token failed: {e}") from e
    return VoiceTokenOut(**token)


@app.post("/crisis", response_model=CrisisOut, status_code=201)
async def post_crisis(body: CrisisIn) -> CrisisOut:
    """Declare a crisis: save it to Supabase, then search the web for the
    official protocols that cover it and save those alongside it."""
    try:
        return await declare_crisis(body)
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"supabase insert failed: {e}") from e
