"""Where the zones are, so the dashboard can draw them on a map.

Pack zones carry their coordinates. Zones typed into the wizard are looked
up by name (OpenStreetMap Nominatim: one request per second, as its usage
policy asks). A zone nobody can locate simply stays off the map.
"""

import asyncio
import logging

import httpx

from valte.core.events import append_event
from valte.core.world import load_pack, zone_dict, zones_of
from valte.db import crisis_lock, session_scope
from valte.models import Crisis, Zone
from valte.settings import settings

log = logging.getLogger("valte.geo")
NOMINATIM = "https://nominatim.openstreetmap.org/search"


def _missing(crisis_id: str) -> tuple[list[tuple[str, str]], str, dict[str, dict[str, float]]]:
    with session_scope() as db:
        c = db.get(Crisis, crisis_id)
        if c is None:
            return [], "", {}
        known: dict[str, dict[str, float]] = {}
        if c.pack_id:
            try:
                known = {z["id"]: z["centroid"] for z in load_pack(c.pack_id).get("zones", []) if z.get("centroid")}
            except KeyError:
                pass
        return [(z.id, z.name) for z in zones_of(db, crisis_id) if not (z.extra or {}).get("centroid")], c.region, known


def _store(crisis_id: str, zone_id: str, centroid: dict[str, float]) -> None:
    with crisis_lock(crisis_id), session_scope() as db:
        c, z = db.get(Crisis, crisis_id), db.get(Zone, (crisis_id, zone_id))
        if c is None or z is None:
            return
        z.extra = {**(z.extra or {}), "centroid": centroid}
        append_event(db, c, "zone.updated", zone_dict(z))


async def locate_zones(crisis_id: str) -> int:
    missing, region, known = await asyncio.to_thread(_missing, crisis_id)
    found = 0
    async with httpx.AsyncClient(timeout=12.0, headers={"User-Agent": "valte-hackspain2026/0.2 (crisis dashboard demo)"}) as http:
        for zone_id, name in missing:
            centroid = known.get(zone_id)
            if centroid is None and settings.valte_geocode:
                try:
                    r = await http.get(NOMINATIM, params={"q": f"{name}, {region}, España" if region else f"{name}, España",
                                                          "format": "jsonv2", "limit": 1, "countrycodes": "es"})
                    hits = r.json() if r.status_code == 200 else []
                    if hits:
                        centroid = {"lat": round(float(hits[0]["lat"]), 5), "lng": round(float(hits[0]["lon"]), 5)}
                except (httpx.HTTPError, ValueError, KeyError) as e:
                    log.warning("could not locate %s: %s", name, e)
                await asyncio.sleep(1.1)  # Nominatim usage policy: at most one request per second
            if centroid:
                await asyncio.to_thread(_store, crisis_id, zone_id, centroid)
                found += 1
    log.info("located %d of %d zones for %s", found, len(missing), crisis_id)
    return found
