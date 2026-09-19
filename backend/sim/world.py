"""In-memory ground truth. The kernel never sees this module: the agent
observes the world only through emitted signals."""

from datetime import datetime


class World:
    def __init__(self, pack: dict):
        self.scenario = pack["scenario"]
        self.zones = pack["zones"]
        self.entities = pack["entities"]
        self.hazards: dict[str, dict] = {h["id"]: h for h in pack["initial_hazards"]}
        # population ground truth, keyed by zone id
        self.population: dict[str, dict] = {}
        for e in self.entities.values():
            if e["kind"] == "population":
                self.population[e["zone"]] = dict(e["population"])
        self.roads_closed: set[str] = set()
        self.rescue_units: dict[str, int] = {}   # zone -> active units
        self.evacuating: set[str] = set()

    def set_hazard(self, hazard: dict):
        self.hazards[hazard["id"]] = hazard

    def patch_entity(self, entity_id: str, fields: dict):
        """Overwrite entity ground-truth fields (deep merge one level for dicts)."""
        e = self.entities[entity_id]
        for k, v in fields.items():
            if isinstance(v, dict) and isinstance(e.get(k), dict):
                e[k] = {**e[k], **v}
            else:
                e[k] = v

    def hazard_in_zone(self, zone_id: str) -> dict | None:
        active = [h for h in self.hazards.values() if h["zone"] == zone_id]
        return max(active, key=lambda h: h["severity"]) if active else None

    def zone_phase(self, zone_id: str) -> str:
        """The narrative phase of a zone, used to pick message buckets.
        calm -> rising (hazard building) -> severe (hazard hit, unwarned)
        -> severe_warned (hazard hit, population warned)."""
        h = self.hazard_in_zone(zone_id)
        if not h or h["severity"] < 3:
            return "calm"
        if h["severity"] < 6:
            return "rising"
        pop = self.population.get(zone_id)
        return "severe_warned" if pop and pop["warned"] else "severe"

    def warn_zone(self, zone_id: str):
        pop = self.population.get(zone_id)
        if pop and not pop["warned"]:
            pop["warned"] = True
            # immediate effect: people leave garages and ground floors
            pop["at_risk_pct"] = max(2.0, pop["at_risk_pct"] * 0.7)

    def start_evacuation(self, zone_id: str):
        self.evacuating.add(zone_id)

    def close_road(self, zone_id: str):
        if zone_id not in self.roads_closed:
            self.roads_closed.add(zone_id)
            pop = self.population.get(zone_id)
            if pop:  # vehicles stop entering the water path
                pop["at_risk_pct"] = max(2.0, pop["at_risk_pct"] - 2.0)

    def add_rescue(self, zone_id: str, units: int):
        self.rescue_units[zone_id] = self.rescue_units.get(zone_id, 0) + units

    def drift_population(self, scenario_minutes: float):
        """Unwarned people in a severe-hazard zone drift into danger
        (going down to garages for their cars). Warnings stop the drift
        and start recovery; evacuation, closed roads, and rescue units
        pull at_risk_pct down further."""
        for zone_id, pop in self.population.items():
            h = self.hazard_in_zone(zone_id)
            hazard_on = bool(h and h["severity"] >= 6)
            if hazard_on and not pop["warned"]:
                rate = 0.2 * (0.5 if zone_id in self.roads_closed else 1.0)
                pop["at_risk_pct"] = min(100.0, pop["at_risk_pct"] + rate * scenario_minutes)
            elif pop["warned"]:
                pop["at_risk_pct"] = max(2.0, pop["at_risk_pct"] - 0.15 * scenario_minutes)
            if zone_id in self.evacuating and pop["evacuated_pct"] < 80.0:
                pop["evacuated_pct"] = min(80.0, pop["evacuated_pct"] + 1.0 * scenario_minutes)
                pop["at_risk_pct"] = max(1.0, pop["at_risk_pct"] - 0.2 * scenario_minutes)
            rescue = self.rescue_units.get(zone_id, 0)
            if rescue and pop["at_risk_pct"] > 1.0:
                pop["at_risk_pct"] = max(1.0, pop["at_risk_pct"] - 0.25 * rescue * scenario_minutes)

    def summary(self, t: datetime) -> dict:
        return {
            "t": t.isoformat(),
            "hazards": list(self.hazards.values()),
            "population": self.population,
            "entities_status": {
                e["id"]: e["status"] for e in self.entities.values() if e["status"] != "available"
            },
        }
