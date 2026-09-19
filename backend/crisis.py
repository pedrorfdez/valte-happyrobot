"""Persist a declared crisis and the manuals found for it.

The voice intake produces free text; this is where that text and the
protocols Exa found for it stop being ephemeral.
"""

import logging
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field

from db import supabase
from manuals import Manual, search_manuals
from workflows import fetch_run_transcript

log = logging.getLogger("valte.crisis")


class CrisisIn(BaseModel):
    # Either is enough: with a run_id we read the transcript back from
    # HappyRobot, which is the record that actually survives.
    transcript: str | None = Field(None, description="What was said during the intake.")
    run_id: str | None = Field(None, description="HappyRobot run of the intake call.")

    # Filled by the caller when known. The intake agent does not extract
    # them yet, so they are all optional.
    crisis_type: str | None = None
    location: str | None = None
    started_at: str | None = None
    scope: str | None = None
    people_affected: int | None = None
    immediate_needs: str | None = None


class CrisisOut(BaseModel):
    id: str
    run_id: str | None
    crisis_type: str | None
    location: str | None
    started_at: str | None
    scope: str | None
    people_affected: int | None
    immediate_needs: str | None
    transcript: str | None
    created_at: str
    manuals: list[Manual] = []
    manuals_error: str | None = None


def _search_text(crisis: CrisisIn) -> str:
    """Best description of the situation we can hand to the search.

    The structured fields make a far sharper query, so they win when
    present. Falling back to the transcript, the agent's own questions
    are dropped: they are the same boilerplate every call and they
    drown out what the caller actually reported.
    """
    parts = [crisis.crisis_type, crisis.location, crisis.scope, crisis.immediate_needs]
    known = " ".join(p for p in parts if p).strip()
    if known:
        return known

    transcript = crisis.transcript or ""
    reported = [
        line.split(":", 1)[1].strip()
        for line in transcript.splitlines()
        if line.startswith("Mando:")
    ]
    return " ".join(reported).strip() or transcript


async def declare_crisis(crisis: CrisisIn, manual_limit: int = 5) -> CrisisOut:
    """Save the crisis, then look up and save its management manuals.

    Neither a missing transcript nor a failed manual search loses the
    crisis: the row goes in first and the errors come back on it.
    """
    if not crisis.transcript and crisis.run_id:
        try:
            crisis = crisis.model_copy(
                update={"transcript": await fetch_run_transcript(crisis.run_id)}
            )
        except Exception as e:
            log.warning("transcript fetch failed run=%s: %s", crisis.run_id, e)

    db = supabase()
    row: dict[str, Any] = {
        "id": str(uuid4()),
        "run_id": crisis.run_id,
        "crisis_type": crisis.crisis_type,
        "location": crisis.location,
        "started_at": crisis.started_at,
        "scope": crisis.scope,
        "people_affected": crisis.people_affected,
        "immediate_needs": crisis.immediate_needs,
        "transcript": crisis.transcript,
        "source": "crisis-start",
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    saved = db.table("crises").insert(row).execute().data[0]
    log.info("crisis declared id=%s run=%s", saved["id"], saved.get("run_id"))

    found: list[Manual] = []
    error: str | None = None
    if not _search_text(crisis).strip():
        return CrisisOut(**saved, manuals=[], manuals_error="sin transcripción: nada que buscar")

    try:
        found = await search_manuals(_search_text(crisis), manual_limit)
        if found:
            db.table("crisis_manuals").upsert(
                [
                    {
                        "id": str(uuid4()),
                        "crisis_id": saved["id"],
                        "title": m.title,
                        "url": m.url,
                        "published_date": m.published_date,
                        "highlights": m.highlights,
                    }
                    for m in found
                ],
                on_conflict="crisis_id,url",
            ).execute()
            log.info("manuals stored crisis=%s count=%d", saved["id"], len(found))
    except Exception as e:
        error = str(e)
        log.warning("manual lookup failed crisis=%s: %s", saved["id"], e)

    return CrisisOut(**saved, manuals=found, manuals_error=error)
