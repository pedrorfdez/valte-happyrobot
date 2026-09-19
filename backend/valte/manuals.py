"""Official crisis-management protocols from the web (Exa), ported from v1.
Search only: we do not invent procedure. Highlights become doctrine in the
state the brains read."""

import logging
from typing import Any

import httpx

from valte.core.events import append_event
from valte.db import crisis_lock, session_scope
from valte.models import Crisis, Manual
from valte.settings import settings

log = logging.getLogger("valte.manuals")
EXA_URL = "https://api.exa.ai/search"
# Steers Exa towards official procedure documents instead of news coverage.
QUERY_PREFIX = "protocolo oficial de actuación y manual de gestión de emergencias:"


async def search_manuals(situation: str, limit: int = 4) -> list[dict[str, Any]]:
    if not settings.exa_api_key:
        raise RuntimeError("set EXA_API_KEY to search for manuals")
    body = {"query": f"{QUERY_PREFIX} {situation.strip()}", "type": "auto", "numResults": limit,
            "contents": {"highlights": {"numSentences": 3, "highlightsPerUrl": 2}}}
    async with httpx.AsyncClient(timeout=30.0) as client:
        r = await client.post(EXA_URL, headers={"x-api-key": settings.exa_api_key}, json=body)
        r.raise_for_status()
    return [{"title": x.get("title") or x["url"], "url": x["url"], "published_date": x.get("publishedDate"),
             "highlights": x.get("highlights", [])} for x in r.json().get("results", []) if x.get("url")]


async def lookup_for(crisis_id: str, situation: str) -> None:
    try:
        found = await search_manuals(situation)
    except Exception as e:
        log.warning("manual lookup failed: %s", e)
        return
    with crisis_lock(crisis_id), session_scope() as db:
        c = db.get(Crisis, crisis_id)
        if c is None:
            return
        for m in found:
            db.add(Manual(crisis_id=crisis_id, **m))
        append_event(db, c, "manuals.found", {"count": len(found), "titles": [m["title"] for m in found]})
