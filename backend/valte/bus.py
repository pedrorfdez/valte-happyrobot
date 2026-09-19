"""In-process pub/sub that feeds the dashboard's SSE stream.

publish() is called from worker threads (routes, engine); subscribers
live on the event loop, so delivery hops through call_soon_threadsafe.
"""

import asyncio
from collections import defaultdict
from typing import Any

_loop: asyncio.AbstractEventLoop | None = None
_subs: dict[str, set[asyncio.Queue]] = defaultdict(set)


def bind_loop(loop: asyncio.AbstractEventLoop) -> None:
    global _loop
    _loop = loop


def subscribe(crisis_id: str) -> asyncio.Queue:
    q: asyncio.Queue = asyncio.Queue(maxsize=1000)
    _subs[crisis_id].add(q)
    return q


def unsubscribe(crisis_id: str, q: asyncio.Queue) -> None:
    _subs[crisis_id].discard(q)


def _deliver(crisis_id: str, event: dict[str, Any]) -> None:
    for q in list(_subs.get(crisis_id, ())):
        if q.full():
            q.get_nowait()  # a slow client loses the oldest event, never blocks the world
        q.put_nowait(event)


def publish(crisis_id: str, event: dict[str, Any]) -> None:
    if _loop is None or not _subs.get(crisis_id):
        return
    try:
        _loop.call_soon_threadsafe(_deliver, crisis_id, event)
    except RuntimeError:
        pass  # loop closed during shutdown
