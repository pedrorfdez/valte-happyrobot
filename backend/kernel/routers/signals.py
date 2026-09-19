"""World-facing ingress: normalized signals in, confidence computed,
tripwires evaluated synchronously, coordinator woken."""

from fastapi import APIRouter, Depends, HTTPException, Request

from ..auth import require_token
from ..db import current_run_id, js, q
from ..services import confidence, reflexes
from ..services.outbox import emit_event
from ..validation import validate

router = APIRouter(dependencies=[Depends(require_token)])


@router.post("/signals", status_code=201)
async def ingest(request: Request):
    signal = await request.json()
    rid = current_run_id()
    if not rid:
        raise HTTPException(409, "no active run; POST /runs first")
    validate(signal, "signal")
    if q("select 1 from signals where run_id=%s and id=%s", (rid, signal["id"]), one=True):
        return {"id": signal["id"], "status": "duplicate_ignored"}

    q("insert into payloads (run_id, signal_id, channel, payload) values (%s,%s,%s,%s)",
      (rid, signal["id"], signal.get("modality"), js(signal)))

    conf, inputs = confidence.compute(rid, signal)
    signal["confidence"] = conf
    signal["confidence_inputs"] = inputs  # doc-only; not part of the schema contract
    stored = dict(signal)
    q("insert into signals (run_id,id,t,source,zone,confidence,doc) values (%s,%s,%s,%s,%s,%s,%s)",
      (rid, signal["id"], signal["t"], signal["source"],
       signal["location"].get("zone"), conf, js(stored)))

    fired = reflexes.on_signal(rid, signal, conf)

    is_noise = not (signal.get("claims") or [])
    if not is_noise and conf in ("medium", "high"):
        emit_event(rid, "signal", {
            "signal_id": signal["id"], "zone": signal["location"].get("zone"),
            "confidence": conf, "detail": signal.get("content", "")[:120]})
    return {"id": signal["id"], "confidence": conf,
            "tripwires_fired": fired, "noise": is_noise}


@router.get("/signals")
def list_signals(since: str = "", zone: str = "", limit: int = 50):
    rid = current_run_id()
    sql = "select doc, confidence from signals where run_id=%s"
    params: list = [rid]
    if since:
        sql += " and t > %s"; params.append(since)
    if zone:
        sql += " and zone = %s"; params.append(zone)
    sql += " order by t desc limit %s"; params.append(min(limit, 200))
    return {"signals": [dict(r["doc"], confidence=r["confidence"]) for r in q(sql, tuple(params))]}
