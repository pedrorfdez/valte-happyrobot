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


async def create_voice_token(data: dict[str, Any] | None = None) -> dict[str, Any]:
    """Mint a LiveKit token so the browser can talk to the crisis-start agent.

    HappyRobot's `POST /voice/tokens/` wants the API key, so it has to be
    called from here and never from the dashboard.
    """
    if not settings.crisis_workflow_id or not settings.happyrobot_api_key:
        raise RuntimeError("set HAPPYROBOT_API_KEY and CRISIS_WORKFLOW_ID")

    url = f"{settings.happyrobot_base_url}/voice/tokens/"
    body = {"workflow_id": settings.crisis_workflow_id, "data": data or {}}
    async with httpx.AsyncClient(timeout=15.0) as client:
        r = await client.post(
            url,
            headers={"Authorization": f"Bearer {settings.happyrobot_api_key}"},
            json=body,
        )
        r.raise_for_status()
        token = r.json()
        log.info("voice token minted run=%s room=%s", token.get("run_id"), token.get("room_name"))
        return token


async def fetch_run_transcript(run_id: str) -> str:
    """Read back what was actually said, from HappyRobot's own record.

    The browser's live transcriptions are a convenience for the operator,
    not a source of truth: they are empty whenever STT drops a turn. HR
    keeps the real transcript on the run's sessions.
    """
    if not settings.happyrobot_api_key:
        raise RuntimeError("set HAPPYROBOT_API_KEY")

    headers = {"Authorization": f"Bearer {settings.happyrobot_api_key}"}
    base = settings.happyrobot_base_url
    async with httpx.AsyncClient(timeout=20.0, headers=headers) as client:
        r = await client.get(f"{base}/runs/{run_id}/sessions")
        r.raise_for_status()
        sessions = r.json().get("data", [])

        lines: list[str] = []
        for session in sessions:
            r = await client.get(f"{base}/sessions/{session['id']}/messages")
            r.raise_for_status()
            for m in r.json().get("data", []):
                content = (m.get("content") or "").strip()
                # `event` rows are join/leave plumbing and the agent's own
                # <Thoughts> are not speech.
                if m.get("role") not in ("user", "assistant") or not content:
                    continue
                if content.startswith("<Thoughts>"):
                    continue
                who = "Operador" if m["role"] == "assistant" else "Mando"
                lines.append(f"{who}: {content}")

    log.info("transcript fetched run=%s lines=%d", run_id, len(lines))
    return "\n".join(lines)
