"""Scenario-agnostic hazard propagation plus derived signals.

Propagation: when a propagating hazard reaches a new severity in zone Z,
every zone that lists Z in downstream_of receives that severity after its
propagation_delay_min. The core rule knows nothing about water.

Derived signals are state-conditioned: content is sampled from the
message bucket that matches the zone's current phase (rising / severe /
severe_warned), so the agent's own actions change what the world says
(a warned town calls about meeting points, not about garages). Media
report severe zones with a realistic lag."""

import random
from datetime import datetime, timedelta

from .world import World

# phase -> (call bucket, social bucket)
PHASE_BUCKETS = {
    "rising": ("call.witness.rising", "social.witness.rising"),
    "severe": ("call.trapped.severe", "social.witness.severe"),
    "severe_warned": ("call.warned.severe_warned", "social.warned.severe_warned"),
}
NEWS_LAG_MIN = (20, 40)


class Dynamics:
    def __init__(self, world: World, buckets: dict, rng: random.Random):
        self.world = world
        self.buckets = buckets
        self.rng = rng
        self._scheduled: dict[tuple[str, str], int] = {}
        self._pending: list[tuple[datetime, str, dict]] = []
        self._news_due: dict[str, datetime] = {}   # zone -> scheduled bulletin time
        self._news_sent: set[str] = set()
        self._derived_seq = 0

    def hazard_updated(self, hazard: dict, t: datetime):
        self.world.set_hazard(hazard)
        if not hazard.get("propagating"):
            return
        for child in self.world.zones.values():
            if hazard["zone"] not in child.get("downstream_of", []):
                continue
            key = (hazard["zone"], child["id"])
            if hazard["severity"] <= self._scheduled.get(key, 0):
                continue
            self._scheduled[key] = hazard["severity"]
            arrival = t + timedelta(minutes=child["propagation_delay_min"])
            self._pending.append((arrival, child["id"], {
                "id": f"{hazard['id']}-{child['id']}",
                "type": hazard["type"],
                "zone": child["id"],
                "severity": hazard["severity"],
                "trend": hazard["trend"],
                "propagating": True,
            }))

    def _mk_signal(self, source: str, trust: str, modality: str, content: str,
                   zone_id: str, t: datetime, severity: int, hazard_type: str) -> dict:
        self._derived_seq += 1
        return {
            "id": f"sig-d{self._derived_seq:04d}",
            "t": t.isoformat(),
            "source": source,
            "source_trust": trust,
            "modality": modality,
            "content": content,
            "claims": [{"hazard_type": hazard_type, "severity_hint": severity}],
            "location": {"text": self.world.zones[zone_id]["name"],
                         "zone": zone_id, "precision": "zone"},
        }

    def _pick(self, bucket: str, zone_id: str) -> str:
        tpl = self.rng.choice(self.buckets[bucket])
        return tpl.replace("{zone}", self.world.zones[zone_id]["name"])

    def step(self, t: datetime, dt_minutes: float) -> list[dict]:
        due = [p for p in self._pending if p[0] <= t]
        self._pending = [p for p in self._pending if p[0] > t]
        for _, _zone, hazard in due:
            self.hazard_updated(hazard, t)

        self.world.drift_population(dt_minutes)

        signals = []
        for zone_id, pop in self.world.population.items():
            phase = self.world.zone_phase(zone_id)
            if phase == "calm" or pop["total"] == 0:
                continue
            h = self.world.hazard_in_zone(zone_id)
            call_bucket, social_bucket = PHASE_BUCKETS[phase]

            # 112 volume scales with severity; warned zones call less
            call_rate = h["severity"] * (0.01 if phase == "severe_warned" else 0.02)
            if self.rng.random() < call_rate * dt_minutes:
                signals.append(self._mk_signal(
                    "112-calls", "medium", "call_transcript",
                    self._pick(call_bucket, zone_id), zone_id, t, h["severity"], h["type"]))

            # social chatter, a bit denser than calls
            if self.rng.random() < h["severity"] * 0.025 * dt_minutes:
                signals.append(self._mk_signal(
                    "social-media", "low", "text",
                    self._pick(social_bucket, zone_id), zone_id, t, h["severity"], h["type"]))

            # media pick a severe zone up once, with a lag
            if phase in ("severe", "severe_warned") and zone_id not in self._news_sent:
                if zone_id not in self._news_due:
                    self._news_due[zone_id] = t + timedelta(minutes=self.rng.uniform(*NEWS_LAG_MIN))
                elif t >= self._news_due[zone_id]:
                    self._news_sent.add(zone_id)
                    signals.append(self._mk_signal(
                        "local-news", "medium", "broadcast",
                        self._pick("news.report.severe", zone_id), zone_id, t,
                        h["severity"], h["type"]))
        return signals
