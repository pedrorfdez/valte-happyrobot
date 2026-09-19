import json
import logging
from contextlib import contextmanager
from typing import Any, Iterator
from urllib.parse import parse_qs

from fastapi import Header, HTTPException, Request
from sqlalchemy.orm import Session

from valte.core.world import get_crisis
from valte.db import crisis_lock, session_scope
from valte.models import Crisis, HrCallback
from valte.settings import settings

log = logging.getLogger("valte.api")


def require_hr_bearer(authorization: str | None = Header(default=None)) -> None:
    """HappyRobot nodes send the shared secret. No secret configured = open
    (first local run), and the log says so."""
    secret = settings.happyrobot_webhook_secret
    if not secret:
        return
    if authorization != f"Bearer {secret}":
        raise HTTPException(status_code=401, detail="bad or missing bearer token")


def form_dict(raw: bytes) -> dict[str, str]:
    """application/x-www-form-urlencoded without pulling in python-multipart."""
    return {k: v[-1] for k, v in parse_qs(raw.decode("utf-8", "replace"), keep_blank_values=True).items()}


async def loose_body(request: Request) -> dict[str, Any]:
    """HappyRobot's POST node sends `params` in the query string and, when
    configured, a raw JSON body. Accept both (body wins), plus form posts."""
    merged: dict[str, Any] = dict(request.query_params)
    raw = await request.body()
    if raw:
        try:
            body = json.loads(raw)
        except ValueError:
            body = form_dict(raw) or {"raw": raw.decode("utf-8", "replace")}
        if isinstance(body, str):  # a JSON document that was itself a JSON string
            try:
                body = json.loads(body)
            except ValueError:
                body = {"raw": body}
        if isinstance(body, dict):
            merged.update(body)
        else:
            merged["value"] = body
    return merged


def log_callback(path: str, body: Any, status_code: int = 200) -> None:
    try:
        with session_scope() as db:
            db.add(HrCallback(path=path, body=body, status_code=status_code))
    except Exception:  # never let bookkeeping break a callback
        log.exception("could not log callback")


def resolve_crisis_id(ref: str | None) -> str:
    with session_scope() as db:
        c = get_crisis(db, ref)
        if c is None:
            raise HTTPException(status_code=404, detail="no such crisis (and no active crisis to default to)")
        return c.id


@contextmanager
def crisis_tx(crisis_id: str) -> Iterator[tuple[Session, Crisis]]:
    """Lock the crisis, open a transaction, 404 if it is not there."""
    with crisis_lock(crisis_id), session_scope() as db:
        c = db.get(Crisis, crisis_id)
        if c is None:
            raise HTTPException(status_code=404, detail="crisis not found")
        yield db, c
