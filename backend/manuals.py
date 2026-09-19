"""Look up real crisis-management protocols on the web via Exa.

The `crisis-start` intake tells us what is happening; this turns that
into the handbooks the system should be following. Search only — we do
not invent procedure.
"""

import logging
from typing import Any

import httpx
from pydantic import BaseModel

from config import settings

log = logging.getLogger("valte.manuals")

EXA_URL = "https://api.exa.ai/search"

# Steers Exa towards official procedure documents instead of news
# coverage of the incident.
QUERY_PREFIX = "protocolo oficial de actuación y manual de gestión de emergencias:"


class Manual(BaseModel):
    title: str
    url: str
    published_date: str | None = None
    highlights: list[str] = []


async def search_manuals(situation: str, limit: int = 5) -> list[Manual]:
    """Find management handbooks for the situation described in `situation`.

    `situation` is free text — the crisis intake transcript works as-is.
    """
    if not settings.exa_api_key:
        raise RuntimeError("set EXA_API_KEY to search for manuals")

    body: dict[str, Any] = {
        "query": f"{QUERY_PREFIX} {situation.strip()}",
        "type": "auto",
        "numResults": limit,
        "contents": {"highlights": {"numSentences": 3, "highlightsPerUrl": 2}},
    }
    async with httpx.AsyncClient(timeout=30.0) as client:
        r = await client.post(
            EXA_URL,
            headers={"x-api-key": settings.exa_api_key, "Content-Type": "application/json"},
            json=body,
        )
        r.raise_for_status()
        results = r.json().get("results", [])

    log.info("manuals found=%d situation=%r", len(results), situation[:80])
    return [
        Manual(
            title=x.get("title") or x.get("url", ""),
            url=x["url"],
            published_date=x.get("publishedDate"),
            highlights=x.get("highlights", []),
        )
        for x in results
        if x.get("url")
    ]
