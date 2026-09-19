"""Timeline player (scripted entries) and noise generator."""

import random
from datetime import datetime


class TimelinePlayer:
    def __init__(self, entries: list[dict]):
        self._entries = sorted(entries, key=lambda e: e["t"])
        self._idx = 0

    def due(self, t: datetime) -> list[dict]:
        out = []
        while self._idx < len(self._entries):
            entry = self._entries[self._idx]
            if datetime.fromisoformat(entry["t"]) > t:
                break
            out.append(entry)
            self._idx += 1
        return out

    @property
    def exhausted(self) -> bool:
        return self._idx >= len(self._entries)


class NoiseGenerator:
    """Emits claimless noise signals per source at rate_per_min (scenario
    time), sampling content from the pack's message buckets."""

    def __init__(self, noise_cfg: dict, buckets: dict, zone_ids: list[str], rng: random.Random):
        self.sources = noise_cfg["sources"]
        self.buckets = buckets
        self.zone_ids = zone_ids
        self.rng = rng
        self._seq = 0

    def due(self, t: datetime, dt_minutes: float) -> list[dict]:
        signals = []
        for src in self.sources:
            if self.rng.random() >= src["rate_per_min"] * dt_minutes:
                continue
            self._seq += 1
            zone = self.rng.choice(src.get("zones") or self.zone_ids)
            modality = "call_transcript" if src["source"] == "112-calls" else (
                "broadcast" if src["source"] == "local-news" else "text")
            signals.append({
                "id": f"sig-n{self._seq:04d}",
                "t": t.isoformat(),
                "source": src["source"],
                "source_trust": "low" if src["source"] == "social-media" else "medium",
                "modality": modality,
                "content": self.rng.choice(self.buckets[src["bucket"]]),
                "claims": [],
                "location": {"zone": zone, "precision": "zone"},
            })
        return signals
