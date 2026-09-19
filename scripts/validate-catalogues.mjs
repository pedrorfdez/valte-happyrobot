import { readFile } from "node:fs/promises";
const packs = ["dana-demo", "wildfire-demo"];
for (const p of packs) {
  const rawZones = JSON.parse(await readFile(`scenario-packs/${p}/zones.json`, "utf8"));
  const rawEnts = JSON.parse(await readFile(`scenario-packs/${p}/entities.json`, "utf8"));
  const rawRes = JSON.parse(await readFile(`scenario-packs/${p}/resources.json`, "utf8"));
  // support both raw array and wrapped {zones:[]}/{entities:[]}/{resources:[]}
  const zones = Array.isArray(rawZones) ? rawZones : rawZones.zones;
  const ents = Array.isArray(rawEnts) ? rawEnts : rawEnts.entities;
  const resources = Array.isArray(rawRes) ? rawRes : rawRes.resources;
  if (!Array.isArray(zones) || !zones.every((z) => z.zone_id && z.display?.x != null && z.display?.y != null))
    throw new Error(`${p} zone missing display`);
  if (!ents.some((e) => e.role === "coordination")) throw new Error(`${p} missing coordination`);
  if (!ents.every((e) => ["coordination", "authority", "responder", "source"].includes(e.role)))
    throw new Error(`${p} bad role`);
  const zoneIds = new Set(zones.map((z) => z.zone_id));
  const entityIds = new Set(ents.map((e) => e.entity_id));
  for (const e of ents.filter((e) => e.role !== "source")) {
    if (!e.jurisdiction_zone_ids || !Array.isArray(e.jurisdiction_zone_ids) || e.jurisdiction_zone_ids.length === 0)
      throw new Error(`${p} ${e.entity_id} missing jurisdiction`);
    if (e.jurisdiction_zone_ids.some((id) => !zoneIds.has(id))) throw new Error(`${p} ${e.entity_id} bad jurisdiction`);
  }
  if (!Array.isArray(resources) || resources.length === 0) throw new Error(`${p} missing resources`);
  for (const r of resources) {
    if (!r.resource_id) throw new Error(`${p} resource missing resource_id`);
    if (!r.owner_entity_id) throw new Error(`${p} ${r.resource_id} missing owner_entity_id`);
    if (!entityIds.has(r.owner_entity_id)) throw new Error(`${p} ${r.resource_id} bad owner_entity_id ${r.owner_entity_id}`);
    if (!r.initial_zone_id) throw new Error(`${p} ${r.resource_id} missing initial_zone_id`);
    if (!zoneIds.has(r.initial_zone_id)) throw new Error(`${p} ${r.resource_id} bad initial_zone_id ${r.initial_zone_id}`);
  }
}
console.log("PASS catalogues");
