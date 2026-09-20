"""Tripwires: standing rules the agent installs so the kernel reacts in
milliseconds without deliberation. Two condition types:

signal:  matched synchronously on every signal ingress against simple
         predicates (source, zone, min_severity, min_confidence).
silence: matched by the sweep loop: no signal from a source for N
         scenario minutes (scenario time proxied by the newest signal t).

A firing tripwire inserts a kernel-executed action (actor from the rule,
evidence = the triggering signal or evt id) and emits a coordinator event."""

import json
from datetime import datetime, timedelta

from ..db import current_run_id, js, q
from .outbox import emit_event

TIER = {"low": 0, "medium": 1, "high": 2}


def _scenario_now(run_id: str) -> str:
    row = q("select max(t) as m from signals where run_id=%s", (run_id,), one=True)
    return row["m"].isoformat() if row and row["m"] else datetime.utcnow().isoformat() + "+00:00"


def _fire(run_id: str, tw: dict, evidence_id: str, detail: str):
    now_t = _scenario_now(run_id)
    seq = q("select count(*) as c from actions where run_id=%s", (run_id,), one=True)["c"]
    for i, then in enumerate(tw["doc"].get("then", [])):
        action_id = f"act-tw{seq + i:04d}"
        doc = {
            "id": action_id,
            "t": now_t,
            "actor": then.get("actor", "system"),
            "verb": then.get("verb", "notify"),
            "target_zones": then.get("target_zones", []),
            "params": then.get("params", {}),
            "status": "executed",
            "evidence": [evidence_id],
            "reasoning": f"Tripwire {tw['id']} fired: {detail}. Rule set by {tw['set_by']}.",
        }
        q("insert into actions (run_id,id,t,actor,verb,status,doc) values (%s,%s,%s,%s,%s,%s,%s)",
          (run_id, action_id, doc["t"], doc["actor"], doc["verb"], "executed", js(doc)))
        from .executor import _apply_level
        _apply_level(run_id, doc["verb"], doc)
    tw["doc"]["last_fired_t"] = now_t
    q("update tripwires set doc=%s where run_id=%s and id=%s",
      (js(tw["doc"]), run_id, tw["id"]))
    emit_event(run_id, "tripwire_fired",
               {"tripwire": tw["id"], "evidence": evidence_id, "detail": detail,
                "reason": tw["doc"].get("reason", "")})


def _in_cooldown(run_id: str, tw: dict) -> bool:
    """One firing per cooldown window (scenario time), so a tripwire does
    not re-execute its actions on every matching signal."""
    last = tw["doc"].get("last_fired_t")
    if not last:
        return False
    cooldown = tw["doc"].get("cooldown_min", 45)
    now = datetime.fromisoformat(_scenario_now(run_id))
    return (now - datetime.fromisoformat(last)).total_seconds() / 60 < cooldown


def on_signal(run_id: str, signal: dict, confidence: str) -> list[str]:
    """Synchronous evaluation on ingress. Returns fired tripwire ids."""
    fired = []
    rows = q("select * from tripwires where run_id=%s and status='active'", (run_id,))
    sev = max((c.get("severity_hint", 0) for c in signal.get("claims") or []), default=0)
    for tw in rows:
        cond = tw["doc"].get("if", {})
        if cond.get("type", "signal") != "signal":
            continue
        if cond.get("source") and cond["source"] != signal["source"]:
            continue
        if cond.get("zone") and cond["zone"] != signal["location"].get("zone"):
            continue
        if sev < cond.get("min_severity", 0):
            continue
        if TIER[confidence] < TIER[cond.get("min_confidence", "low")]:
            continue
        if _in_cooldown(run_id, tw):
            continue
        _fire(run_id, tw, signal["id"], f"signal {signal['id']} sev={sev} conf={confidence}")
        fired.append(tw["id"])
    return fired


def sweep_silence():
    """Called by the background sweep: fire silence tripwires when a source
    has emitted nothing for silence_min scenario minutes."""
    run_id = current_run_id()
    if not run_id:
        return
    newest = q("select max(t) as m from signals where run_id=%s", (run_id,), one=True)
    if not newest or not newest["m"]:
        return
    now = newest["m"]
    rows = q("select * from tripwires where run_id=%s and status='active'", (run_id,))
    for tw in rows:
        cond = tw["doc"].get("if", {})
        if cond.get("type") != "silence" or not cond.get("source"):
            continue
        last = q("select max(t) as m from signals where run_id=%s and source=%s",
                 (run_id, cond["source"]), one=True)
        if not last["m"]:
            continue
        gap_min = (now - last["m"]).total_seconds() / 60
        if gap_min >= cond.get("silence_min", 20):
            _fire(run_id, tw, f"evt-silence-{cond['source']}",
                  f"source {cond['source']} silent for {round(gap_min)} scenario minutes")
            q("update tripwires set status='fired' where run_id=%s and id=%s",
              (run_id, tw["id"]))  # silence rules fire once, then the agent re-arms
