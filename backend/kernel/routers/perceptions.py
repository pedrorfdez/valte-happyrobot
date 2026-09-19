"""Perception ingress: what the HappyRobot ingest workflows POST after
extraction. Field values arrive as builder template output, so types are
coerced defensively (booleans and arrays may come as strings). The kernel
composes the normalized signal and runs the same ingest pipeline as
POST /signals."""

import json

from fastapi import APIRouter, Body, Depends, HTTPException, Request

from ..auth import require_token
from ..db import current_run_id, js, q
from .signals import ingest_signal

router = APIRouter(dependencies=[Depends(require_token)])

CHANNEL_MAP = {
    "call": {"source": "112-calls", "source_trust": "medium", "modality": "call_transcript"},
    "social": {"source": "social-media", "source_trust": "low", "modality": "text"},
    "news": {"source": "local-news", "source_trust": "medium", "modality": "broadcast"},
}


def _bool(v) -> bool:
    if isinstance(v, bool):
        return v
    return str(v).strip().lower() in ("true", "1", "yes")


def _jsonish(v):
    if isinstance(v, (list, dict)):
        return v
    try:
        return json.loads(v)
    except Exception:
        return None


@router.post("/perceptions", status_code=201)
def ingest_perception(request: Request, p: dict | None = Body(None)):
    if not p:
        # HappyRobot webhook POST actions deliver params as query string
        p = dict(request.query_params)
    rid = current_run_id()
    if not rid:
        raise HTTPException(409, "no active run; POST /runs first")
    channel = p.get("channel")
    if channel not in CHANNEL_MAP:
        raise HTTPException(422, f"channel must be one of {sorted(CHANNEL_MAP)}")

    claims = _jsonish(p.get("claims")) or []
    if _bool(p.get("is_noise")):
        claims = []
    zone = (p.get("zone") or "").strip() or None
    known_zones = {r["id"] for r in q("select id from zones where run_id=%s", (rid,))}
    if zone and zone not in known_zones:
        zone = None  # perception guessed a place we do not model; keep text only

    signal = {
        "id": p.get("id") or "",
        "t": p.get("t") or "",
        **CHANNEL_MAP[channel],
        "content": p.get("content") or "",
        "claims": [c for c in claims if isinstance(c, dict)
                   and "hazard_type" in c and "severity_hint" in c],
        "location": {
            "zone": zone,
            "precision": p.get("precision") or "unknown",
            **({"text": p["location_text"]} if p.get("location_text") else {}),
        },
    }
    result = ingest_signal(rid, signal)
    # perception extras stored on the signal doc for the audit trail
    is_noise = _bool(p.get("is_noise"))
    q("""update signals set doc = doc || %s::jsonb where run_id=%s and id=%s""",
      (js({"perception": {"summary": p.get("summary", ""),
                          "secondhand": _bool(p.get("secondhand")),
                          "is_noise": is_noise,
                          "channel": channel}}), rid, signal["id"]))
    # relevant but claimless (a resource offer, a status report) is NOT noise:
    # it gets base confidence and wakes the coordinator as informational
    if not is_noise and not signal["claims"] and result.get("confidence") is None:
        q("update signals set confidence='low' where run_id=%s and id=%s", (rid, signal["id"]))
        from ..services.outbox import emit_event
        emit_event(rid, "signal", {
            "signal_id": signal["id"], "zone": signal["location"].get("zone"),
            "confidence": "low",
            "detail": "INFORMATIONAL (no hazard claim): " + (p.get("summary") or signal["content"])[:110]})
        result["confidence"] = "low"
    return result
