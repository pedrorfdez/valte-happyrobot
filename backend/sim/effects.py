"""Closing the causal loop: executed actions change ground truth, and
ground truth flows back to the kernel for the dashboard.

The simulator polls the kernel for executed actions it has not applied
yet and mutates the world:

- send_es_alert / order_evacuation: population warned; evacuation starts.
- close_road: vehicle exposure in the zone stops growing and drops once.
- rescue: assigned units reduce at_risk_pct while active.

It also pushes ground truth back: scripted world patches, population
state (silent, no coordinator wake-up), and hazards (for the dashboard
truth-vs-belief view). If KERNEL is not configured, effects are off and
the sim behaves as the no-agent baseline."""

import json
import os
import sys
import urllib.request

from .world import World


class KernelLink:
    def __init__(self):
        url = os.environ.get("KERNEL_SIGNALS_URL", "")
        self.base = url.rsplit("/signals", 1)[0] if url else ""
        self.token = os.environ.get("WORLD_API_TOKEN", "")
        self.enabled = bool(self.base)

    def _req(self, method: str, path: str, body: dict | None = None):
        req = urllib.request.Request(
            self.base + path,
            data=json.dumps(body).encode() if body is not None else None,
            headers={"Content-Type": "application/json",
                     "Authorization": f"Bearer {self.token}"},
            method=method)
        try:
            with urllib.request.urlopen(req, timeout=5) as r:
                return json.loads(r.read())
        except Exception as e:
            print(f"kernel link {method} {path} failed: {e}", file=sys.stderr)
            return None

    def executed_actions(self) -> list[dict]:
        """Actions with world effects: executed, plus in_progress (unit
        operations like rescue act while they run)."""
        done = self._req("GET", "/actions?status=executed&limit=100")
        active = self._req("GET", "/actions?status=in_progress&limit=100")
        return (done["actions"] if done else []) + (active["actions"] if active else [])

    def patch_entity(self, entity_id: str, fields: dict, silent: bool = False):
        self._req("POST", "/world/patches",
                  {"entity": entity_id, "set": fields, "silent": silent})

    def push_hazard(self, hazard: dict):
        self._req("POST", "/world/hazards", hazard)


class Effects:
    def __init__(self, world: World, link: KernelLink):
        self.world = world
        self.link = link
        self._applied: set[str] = set()
        self._sync_countdown = 0

    def apply_action(self, action: dict):
        verb = action["verb"]
        zones = action.get("target_zones") or []
        params = action.get("params") or {}
        if verb == "send_es_alert":
            for z in zones:
                self.world.warn_zone(z)
        elif verb == "order_evacuation":
            for z in zones:
                self.world.warn_zone(z)
                self.world.start_evacuation(z)
        elif verb == "close_road":
            for z in zones:
                self.world.close_road(z)
        elif verb == "rescue":
            units = int(params.get("units", 1))
            for z in zones:
                self.world.add_rescue(z, units)
        # shelter/supplies/wellness_check: sustainment, no at-risk model effect

    def step(self, dt_minutes: float):
        """Called every engine tick when the link is enabled."""
        if not self.link.enabled:
            return
        for a in self.link.executed_actions():
            if a["id"] in self._applied:
                continue
            self._applied.add(a["id"])
            self.apply_action(a)

        self._sync_countdown -= 1
        if self._sync_countdown <= 0:
            self._sync_countdown = 5  # every 5 ticks
            for zone_id, pop in self.world.population.items():
                eid = f"civilians-{zone_id}"
                if eid in self.world.entities:
                    self.link.patch_entity(eid, {"population": {
                        "total": pop["total"], "warned": pop["warned"],
                        "evacuated_pct": round(pop["evacuated_pct"], 1),
                        "at_risk_pct": round(pop["at_risk_pct"], 1)}}, silent=True)
            for h in self.world.hazards.values():
                self.link.push_hazard(h)

    def forward_world_patch(self, entity_id: str, fields: dict):
        """Scripted timeline patches must reach the kernel too (loud)."""
        if self.link.enabled:
            self.link.patch_entity(entity_id, fields, silent=False)
