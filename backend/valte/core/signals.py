"""Perception intake: turn what a source said into a Signal with an honest,
logged confidence, and keep each zone's estimated severity up to date.

This is the answer to "which information matters": noise is kept (the
dashboard shows it as discarded) but never reaches the brains.
"""

import json
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from valte.core.events import append_event
from valte.core.world import next_id, resolve_zone, scenario_now, signal_dict, zone_dict, zones_of
from valte.models import Crisis, Entity, RawInput, Signal, Zone

LEVELS = ["low", "medium", "high"]
CHANNEL_MODALITY = {"call": "call_transcript", "social": "text", "news": "broadcast",
                    "sensor": "sensor_reading", "operator": "text", "other": "text"}
CORROBORATION_WINDOW = timedelta(minutes=15)
ESTIMATE_WINDOW = timedelta(minutes=30)
HAZARD_BAND = 5  # severity from which a zone threatens its downstream neighbours


def loose_bool(v: Any) -> bool:
    if isinstance(v, bool):
        return v
    return str(v).strip().lower() in ("true", "1", "yes", "y", "si", "sí")


def loose_json(v: Any, default: Any) -> Any:
    """HappyRobot POST nodes may deliver arrays/objects as strings."""
    if v is None or v == "":
        return default
    if isinstance(v, (list, dict)):
        return v
    try:
        return json.loads(v)
    except (TypeError, ValueError):
        return default


def parse_t(v: Any, fallback: datetime) -> datetime:
    try:
        dt = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=fallback.tzinfo)
    except (TypeError, ValueError):
        return fallback


def _norm_claims(raw: Any) -> list[dict[str, Any]]:
    claims = []
    for c in loose_json(raw, []):
        c = loose_json(c, None) if isinstance(c, str) else c
        if not isinstance(c, dict):
            continue
        try:
            sev = max(0, min(10, int(float(c.get("severity_hint", 0)))))
        except (TypeError, ValueError):
            sev = 0
        claims.append({"hazard_type": str(c.get("hazard_type") or "unknown"), "severity_hint": sev})
    return claims


def raw_text(raw: "RawInput | None") -> str:
    """What the source actually said, whatever shape its payload has."""
    p = (raw.payload if raw else None) or {}
    if p.get("headline") or p.get("body"):
        return " — ".join(x for x in (p.get("headline"), p.get("body")) if x)
    return str(p.get("transcript") or p.get("text") or p.get("content") or "")


def compute_confidence(db: Session, c: Crisis, sig: Signal) -> tuple[str | None, dict[str, Any]]:
    """Prior from the source, moved by corroboration and location precision.
    Every input is logged: it is what the supervisor audits."""
    if sig.is_noise:
        return None, {"reason": "noise"}
    base = sig.source_trust if sig.source_trust in LEVELS else "medium"
    level = LEVELS.index(base)
    inputs: dict[str, Any] = {"base": base}

    corroborating: list[Signal] = []
    if sig.zone_id:
        hazards = {cl["hazard_type"] for cl in sig.claims}
        for other in db.scalars(select(Signal).where(
            Signal.crisis_id == c.id, Signal.zone_id == sig.zone_id, Signal.is_noise.is_(False),
            Signal.id != sig.id, Signal.t >= sig.t - CORROBORATION_WINDOW, Signal.t <= sig.t + CORROBORATION_WINDOW)):
            if not hazards or hazards & {cl["hazard_type"] for cl in other.claims}:
                corroborating.append(other)
    from valte.core.incidents import origin_key

    other_channels = sorted({o.channel for o in corroborating if o.channel != sig.channel})
    # Independent witnesses, not messages: twenty reposts of one rumour corroborate nothing.
    origins = {origin_key(db, o) for o in corroborating} - {origin_key(db, sig)}
    inputs["corroborating_signals"] = [o.id for o in corroborating][:6]
    inputs["corroborating_channels"] = other_channels
    inputs["independent_origins"] = len(origins)
    if other_channels:
        level += 1
    if len(origins) >= 3 and len({o.channel for o in corroborating} | {sig.channel}) >= 2:
        level += 1

    precision = (sig.location or {}).get("precision", "unknown")
    inputs["precision"] = precision
    if precision in ("unknown", "region") and sig.channel != "sensor":
        level -= 1

    result = LEVELS[max(0, min(2, level))]
    inputs["result"] = result
    return result, inputs


def upsert_signal(
    db: Session,
    c: Crisis,
    *,
    sig_id: str | None,
    t: datetime | None,
    source: str,
    channel: str,
    content: str,
    is_noise: bool,
    claims: list[dict[str, Any]],
    zone: str | None,
    precision: str,
    location_text: str = "",
    summary: str = "",
    perceived_by: str = "hr",
    hr_run_id: str | None = None,
    modality: str | None = None,
) -> tuple[Signal, bool]:
    """Returns (signal, created). Same id again = a revision, not a copy."""
    from valte.core import incidents, tripwires

    now_s = scenario_now(c)
    sig_id = sig_id or next_id(c, "sig")
    existing = db.get(Signal, (c.id, sig_id))
    if existing and existing.perceived_by != "fallback" and perceived_by == "fallback":
        return existing, False  # HappyRobot already answered; the stand-in arrives late
    if existing and existing.hr_run_id and existing.hr_run_id == hr_run_id:
        return existing, False  # callback and reconciliation both delivered this run

    ent = db.get(Entity, (c.id, source))
    zone_id = resolve_zone(db, c.id, zone)
    if precision not in ("exact", "street", "zone", "region", "unknown"):
        precision = "zone" if zone_id else "unknown"
    if zone_id is None and precision in ("exact", "street", "zone"):
        precision = "unknown"
    location: dict[str, Any] = {"precision": precision}
    if zone_id:
        location["zone"] = zone_id
    if location_text:
        location["text"] = location_text

    sig = existing or Signal(crisis_id=c.id, id=sig_id)
    sig.seq = existing.seq if existing else int((c.counters or {}).get("sig_seq", 0)) + 1
    if not existing:
        c.counters = {**(c.counters or {}), "sig_seq": sig.seq}
    sig.t = t or now_s
    sig.source = source
    sig.source_trust = ent.trust if ent else "low"
    sig.channel = channel
    sig.modality = modality or CHANNEL_MODALITY.get(channel, "text")
    sig.content = content or ""
    sig.summary = summary or ""
    sig.is_noise = bool(is_noise) or (not claims and channel != "sensor" and perceived_by != "operator")
    sig.claims = [] if sig.is_noise else claims
    sig.location = location
    sig.zone_id = zone_id
    sig.severity_hint = max([cl["severity_hint"] for cl in sig.claims], default=0)
    sig.perceived_by = perceived_by
    sig.hr_run_id = hr_run_id
    sig.revision = (existing.revision + 1) if existing else 1
    if not existing:
        db.add(sig)
    db.flush()

    sig.confidence, sig.confidence_inputs = compute_confidence(db, c, sig)

    raw = db.get(RawInput, (c.id, sig_id))
    if raw:
        raw.state = "fallback" if perceived_by == "fallback" else "perceived"

    # One or several signals make an incident. A report that only repeats what its incident already says is
    # evidence, not news: it does not wake a brain (and does not cost a run).
    inc, news = incidents.attach_signal(db, c, sig)
    worth = sig.confidence in ("medium", "high") or sig.severity_hint >= 6 \
        or (inc is not None and inc.state != "candidate" and (inc.severity or 0) >= 6)  # a weak voice that confirms a serious incident
    material = (not sig.is_noise) and worth and (news or inc is None)
    place = sig.zone_id or "unresolved location"
    append_event(
        db, c, "signal.created" if not existing else "signal.updated", signal_dict(sig), material=material,
        digest=None if sig.is_noise else
        f"[{sig.id}] {sig.source} ({sig.modality}, confidence {sig.confidence}) in {place}: "
        f"severity {sig.severity_hint} — {(sig.summary or sig.content)[:160]}"
        + (f" → {inc.id} [{inc.priority}, {inc.state}, {len(inc.signal_ids or [])} signal(s) / "
           f"{len(inc.origins or [])} independent source(s)] {inc.title}" if inc else ""),
    )

    if not sig.is_noise:
        # A new report lifts the confidence of the ones it corroborates.
        for oid in sig.confidence_inputs.get("corroborating_signals", []):
            other = db.get(Signal, (c.id, oid))
            if other:
                conf, inputs = compute_confidence(db, c, other)
                if conf != other.confidence:
                    other.confidence, other.confidence_inputs = conf, inputs
                    append_event(db, c, "signal.updated", signal_dict(other))
        recompute_zone_estimates(db, c)
        tripwires.evaluate_on_signal(db, c, sig)
    return sig, existing is None


def ingest_perception(db: Session, c: Crisis, p: dict[str, Any], *, hr_run_id: str | None = None,
                      perceived_by: str = "hr") -> dict[str, Any]:
    """Kernel contract: the flat body a PedroD-ingest-* workflow posts."""
    sig_id = str(p.get("id") or "") or None
    raw = db.get(RawInput, (c.id, sig_id)) if sig_id else None
    channel = str(p.get("channel") or (raw.channel if raw else "other"))
    source = str(p.get("source") or (raw.source if raw else {"call": "112", "social": "social-media",
                                                              "news": "local-news"}.get(channel, channel)))
    # The workflow does not echo the text back (it would not fit in a query string): we already hold it.
    content = str(p.get("content") or "") or raw_text(raw)
    sig, created = upsert_signal(
        db, c, sig_id=sig_id, t=parse_t(p.get("t"), raw.t if raw else scenario_now(c)), source=source,
        channel=channel, content=content, is_noise=loose_bool(p.get("is_noise")),
        claims=_norm_claims(p.get("claims")), zone=p.get("zone"), precision=str(p.get("precision") or "unknown"),
        location_text=str(p.get("location_text") or ""), summary=str(p.get("summary") or ""),
        perceived_by=perceived_by, hr_run_id=hr_run_id,
    )
    return {"id": sig.id, "noise": sig.is_noise, "confidence": sig.confidence, "created": created}


# ── zone estimates ───────────────────────────────────────────────────────


def _discount(sig: Signal) -> int:
    return {"high": 0, "medium": 1, "low": 2}.get(sig.confidence or "low", 2)


def recompute_zone_estimates(db: Session, c: Crisis) -> None:
    """Severity per zone from recent signals, then propagate the threat along
    the graph: a dry town below a flooding gauge has a countdown, not safety."""
    now_s = scenario_now(c)
    zones = zones_of(db, c.id)
    by_id = {z.id: z for z in zones}
    recent = list(db.scalars(select(Signal).where(
        Signal.crisis_id == c.id, Signal.is_noise.is_(False), Signal.zone_id.is_not(None),
        Signal.t >= now_s - ESTIMATE_WINDOW)))

    changed: set[str] = set()
    for z in zones:
        sigs = [s for s in recent if s.zone_id == z.id]
        if not sigs:
            continue  # no news: hold the last estimate rather than invent a recovery
        est = max(max(0, s.severity_hint - _discount(s)) for s in sigs)
        if est != z.severity_est:
            z.trend = "rising" if est > z.severity_est else "falling"
            z.severity_est = est
            changed.add(z.id)
        if z.severity_est >= HAZARD_BAND and z.crossed_at is None:
            z.crossed_at = now_s
        if z.severity_est < HAZARD_BAND:
            z.crossed_at = None

    upstream: dict[str, list[tuple[Zone, int]]] = {}
    for z in zones:
        for e in z.downstream or []:
            upstream.setdefault(e["to"], []).append((z, int(e["delay_min"])))
    for z in zones:
        etas = []
        for up, delay in upstream.get(z.id, []):
            if up.crossed_at is not None:
                etas.append(max(0, delay - int((now_s - up.crossed_at).total_seconds() // 60)))
            elif up.eta_min is not None:  # threat two hops away
                etas.append(up.eta_min + delay)
        eta = min(etas) if etas else None
        if z.crossed_at is not None:
            eta = 0
        if eta != z.eta_min:
            z.eta_min = eta
            changed.add(z.id)

        threat = z.severity_est
        if z.eta_min is not None:
            threat = max(threat, max((u.severity_est for u, _ in upstream.get(z.id, [])), default=0) - 1)
        risk = z.base_at_risk_pct * min(1.0, threat / 7.0)
        risk *= 0.6 if z.warned else 1.0
        risk *= 1.0 - min(z.evacuated_pct, 100.0) / 100.0
        if round(risk) != round(z.at_risk_pct):
            changed.add(z.id)
        z.at_risk_pct = risk

    for zid in changed:
        append_event(db, c, "zone.updated", zone_dict(by_id[zid]))

    worst = max((z.severity_est for z in zones), default=0)
    if worst != c.severity:
        c.trend = "rising" if worst > c.severity else "falling"
        c.severity = worst
        append_event(db, c, "crisis.updated", {"severity": c.severity, "trend": c.trend})
