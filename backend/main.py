from datetime import datetime, timezone
from typing import Any, Literal
from uuid import uuid4

from fastapi import BackgroundTasks, FastAPI, HTTPException
from pydantic import BaseModel, Field

from db import supabase
from workflows import trigger_ticket_workflow

app = FastAPI(title="Valte backend", version="0.1.0")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


TicketKind = Literal["report", "proposal"]
TicketStatus = Literal["open", "processing", "done", "failed"]


class TicketIn(BaseModel):
    user_id: str = Field(..., description="User submitting the ticket.")
    entity_id: str = Field(..., description="Entity the user is assigned to.")
    kind: TicketKind = Field(..., description="'report' (this is happening) or 'proposal' (let's do this).")
    content: str = Field(..., min_length=1, description="Body read by the entity workflow.")
    subject: str | None = Field(None, description="Optional short summary for the UI.")
    payload: dict[str, Any] = Field(default_factory=dict)


class TicketOut(TicketIn):
    id: str
    status: TicketStatus
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
        "status": "open",
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
