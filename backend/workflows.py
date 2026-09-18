import logging
from typing import Any

import httpx

from config import settings

log = logging.getLogger("valte.workflows")


async def trigger_ticket_workflow(ticket: dict[str, Any]) -> None:
    """Fire the HappyRobot workflow attached to new tickets.

    No-op until TICKET_WORKFLOW_ID and HAPPYROBOT_API_KEY are set — we just
    log the intent so the ingestion path is exercisable end-to-end.
    """
    if not settings.ticket_workflow_id or not settings.happyrobot_api_key:
        log.info("workflow trigger skipped (not configured) ticket=%s", ticket.get("id"))
        return

    url = f"{settings.happyrobot_base_url}/workflows/{settings.ticket_workflow_id}/runs"
    headers = {
        "Authorization": f"Bearer {settings.happyrobot_api_key}",
        "Content-Type": "application/json",
    }
    async with httpx.AsyncClient(timeout=10.0) as client:
        r = await client.post(url, headers=headers, json={"input": ticket})
        r.raise_for_status()
        log.info("workflow triggered ticket=%s run=%s", ticket.get("id"), r.text[:200])
