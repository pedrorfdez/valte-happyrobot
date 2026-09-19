"""Per-signal confidence: deterministic, explainable, computed at ingress.

base tier   = source_trust (low/medium/high)
+1 tier     if >=2 DISTINCT SOURCE CHANNELS claim the same hazard type in
             the same zone within the last 15 scenario minutes. Counting
             distinct source entities (channels), not individual posts or
             callers, is the echo defense: an unverified channel
             corroborates at most once, however many copies it carries.
-1 tier     if the signal is older than 30 scenario minutes at ingress
             (relative to the newest signal seen, our scenario-time proxy).

The inputs are stored on the signal (doc.confidence_inputs) so the
dashboard can show why the kernel believed it."""

from datetime import datetime, timedelta

from ..db import q

TIERS = ["low", "medium", "high"]
CORROBORATION_WINDOW_MIN = 15
STALE_MIN = 30


def compute(run_id: str, signal: dict) -> tuple[str, dict]:
    tier = TIERS.index(signal.get("source_trust", "low"))
    inputs = {"base": signal.get("source_trust", "low")}

    zone = signal["location"].get("zone")
    claims = signal.get("claims") or []
    corroborators = []
    if zone and claims:
        t = datetime.fromisoformat(signal["t"])
        window = t - timedelta(minutes=CORROBORATION_WINDOW_MIN)
        rows = q("""
            select distinct source from signals
            where run_id = %s and zone = %s and source <> %s
              and t between %s and %s
              and jsonb_array_length(doc->'claims') > 0
        """, (run_id, zone, signal["source"], window, t))
        corroborators = [r["source"] for r in rows]
        if len(corroborators) >= 1:
            tier += 1
    inputs["corroborating_channels"] = corroborators

    newest = q("select max(t) as m from signals where run_id = %s", (run_id,), one=True)
    if newest and newest["m"]:
        age = (newest["m"] - datetime.fromisoformat(signal["t"])).total_seconds() / 60
        if age > STALE_MIN:
            tier -= 1
            inputs["stale_min"] = round(age)

    tier = max(0, min(2, tier))
    inputs["result"] = TIERS[tier]
    return TIERS[tier], inputs
