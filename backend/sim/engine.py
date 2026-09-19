"""The tick loop: advance the clock, release scripted entries, generate
noise, evolve hazards, adapt signals to their channel's native payload,
emit. Optionally logs the normalized ground-truth signals so perception
(the HappyRobot ingest workflows) can be scored against them."""

import json
import random
import time
from datetime import datetime, timedelta

from .channels import ChannelRouter
from .clock import ScenarioClock
from .dynamics import Dynamics
from .timeline import NoiseGenerator, TimelinePlayer
from .world import World


class Engine:
    def __init__(self, pack: dict, speed: float, seed: int, emitter,
                 tick_wall_s: float = 1.0, truth_path: str | None = None):
        self.world = World(pack)
        self.clock = ScenarioClock(pack["scenario"]["time"]["start"],
                                   pack["scenario"]["time"]["end"], speed)
        rng = random.Random(seed)
        self.rng = rng
        self.buckets = pack["messages"]
        self.player = TimelinePlayer(pack["timeline"])
        self.noise = NoiseGenerator(pack["noise"], self.buckets, list(pack["zones"]), rng)
        self.dynamics = Dynamics(self.world, self.buckets, rng)
        self.router = ChannelRouter(self.world.entities, rng)
        self._pending_echoes: list[tuple[object, dict]] = []  # (release_t, signal)
        self._echo_seq = 0
        self.emitter = emitter
        self.tick_wall_s = tick_wall_s
        self._truth = open(truth_path, "a") if truth_path else None
        self.emitted = 0
        self.markers: list[dict] = []

    def _emit(self, signal: dict, call_meta: dict | None = None):
        channel, mode, payload = self.router.adapt(signal, call_meta)
        self.emitter.emit(channel, mode, payload)
        if self._truth:
            self._truth.write(json.dumps(signal, ensure_ascii=False) + "\n")
            self._truth.flush()  # survive hard kills; this log is the eval ground truth
        self.emitted += 1
        self._maybe_cascade(signal)

    def _maybe_cascade(self, signal: dict):
        """A dramatic true report spawns 1-3 delayed, distorted social echoes.
        Echoes are the corroboration rule's adversary: many copies, one witness."""
        if signal.get("echo_of") or not signal.get("claims"):
            return
        if signal["source"] not in ("112-calls", "social-media"):
            return
        sev = max(c.get("severity_hint", 0) for c in signal["claims"])
        if sev < 6 or self.rng.random() > 0.5:
            return
        zone_id = signal["location"].get("zone")
        if not zone_id:
            return
        zone_name = self.world.zones[zone_id]["name"]
        snippet = signal["content"][:70]
        t0 = datetime.fromisoformat(signal["t"])
        for _ in range(self.rng.randint(1, 3)):
            self._echo_seq += 1
            tpl = self.rng.choice(self.buckets["social.rumor"])
            release = t0 + timedelta(minutes=self.rng.uniform(2, 12))
            self._pending_echoes.append((release, {
                "id": f"sig-e{self._echo_seq:04d}",
                "t": release.isoformat(),
                "source": "social-media",
                "source_trust": "low",
                "modality": "text",
                "content": tpl.replace("{zone}", zone_name).replace("{original}", snippet),
                "claims": [{"hazard_type": signal["claims"][0]["hazard_type"],
                            "severity_hint": min(10, sev + 1)}],  # rumors exaggerate
                "location": {"text": zone_name, "zone": zone_id, "precision": "zone"},
                "echo_of": signal["id"],
            }))

    def _apply_entry(self, entry: dict, t: datetime):
        kind = entry["type"]
        if kind == "signal":
            self._emit(entry["signal"], entry.get("call"))
        elif kind == "hazard":
            self.dynamics.hazard_updated(entry["hazard"], datetime.fromisoformat(entry["t"]))
        elif kind == "world_patch":
            self.world.patch_entity(entry["patch"]["entity"], entry["patch"]["set"])
        elif kind == "marker":
            self.markers.append(entry)
            print(f"\033[1m== MARKER {entry['t'][11:16]}: {entry.get('note', '')}\033[0m")

    def run(self):
        self.clock.start_running()
        last_t = self.clock.start
        try:
            while not self.clock.finished():
                t = self.clock.now()
                dt_minutes = (t - last_t).total_seconds() / 60.0
                last_t = t

                for entry in self.player.due(t):
                    self._apply_entry(entry, t)
                for sig in self.noise.due(t, dt_minutes):
                    self._emit(sig)
                for sig in self.dynamics.step(t, dt_minutes):
                    self._emit(sig)
                due_echoes = [e for e in self._pending_echoes if e[0] <= t]
                self._pending_echoes = [e for e in self._pending_echoes if e[0] > t]
                for _, echo in due_echoes:
                    self._emit(echo)

                time.sleep(self.tick_wall_s)
            # final drain: release anything scheduled inside the window that
            # the last tick jumped over (matters at high compression)
            end = self.clock.end
            for entry in self.player.due(end):
                self._apply_entry(entry, end)
            for _, echo in [e for e in self._pending_echoes if e[0] <= end]:
                self._emit(echo)
        finally:
            if self._truth:
                self._truth.close()
        return self.world.summary(self.clock.end)
