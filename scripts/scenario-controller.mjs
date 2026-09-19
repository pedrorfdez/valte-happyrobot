#!/usr/bin/env node

import { readFile } from "node:fs/promises";
import { resolve } from "node:path";

const modes = new Set(["run", "advance", "pause", "resume", "inject"]);

const usage = () => {
  console.error([
    "Usage:",
    "  scenario-controller.mjs --pack <dir> --dry-run",
    "  scenario-controller.mjs --pack <dir> --run-id <id> --gateway-url <origin> --connected --json",
    "Manual: --mode run|advance|pause|resume|inject --to-seconds <N> --source-input <json-file>",
    "Common: --state-version <N> --operation-id <id> --until-seconds <N>"
  ].join("\n"));
};

function parseArgs(args) {
  const parsed = { dryRun: false, connected: false, json: false };
  for (let index = 0; index < args.length; index += 1) {
    const token = args[index];
    if (["--dry-run", "--connected", "--json"].includes(token)) {
      const key = token.slice(2).replace(/-([a-z])/g, (_, letter) => letter.toUpperCase());
      parsed[key] = true;
      continue;
    }
    if (!token.startsWith("--")) throw new Error(`unexpected argument: ${token}`);
    const key = token.slice(2).replace(/-([a-z])/g, (_, letter) => letter.toUpperCase());
    const value = args[index + 1];
    if (!value || value.startsWith("--")) throw new Error(`${token} requires a value`);
    parsed[key] = value;
    index += 1;
  }
  return parsed;
}

const options = parseArgs(process.argv.slice(2));
if (!options.pack) {
  usage();
  process.exit(2);
}
if (options.dryRun === options.connected) failMode("choose exactly one of --dry-run or --connected");
if (options.connected && !options.json) failMode("connected mode requires --json");
const mode = options.mode ?? "run";
if (!modes.has(mode)) failMode(`unsupported --mode: ${mode}`);

function failMode(message) {
  console.error(`[scenario-controller] ${message}`);
  usage();
  process.exit(2);
}

const readJson = async (path) => JSON.parse(await readFile(path, "utf8"));
const unique = (items) => new Set(items).size === items.length;
const fail = (message) => { throw new Error(message); };
const log = (message) => console.error(`[scenario-controller] ${message}`);
const isObject = (value) => value !== null && typeof value === "object" && !Array.isArray(value);
const signalIdentityFields = ["signal_id", "revision"];
const sourceInputFields = [
  "source_input_id", "modality", "content", "reporter_id",
  "origin_reference", "declared_location"
];
const injectionFields = ["signal_identity", "source_input"];
const sourceModalities = new Set(["text", "call_transcript", "sensor_reading", "broadcast", "webhook"]);
const privateKeyPattern = /^(?:hidden|private|ground|scenario)?truth$|canary/;

function requireExactObject(value, fields, context) {
  if (!isObject(value)) fail(`${context} must be an object`);
  const missing = fields.filter((field) => !Object.hasOwn(value, field));
  if (missing.length) fail(`${context} is missing required fields: ${missing.join(", ")}`);
  if (Object.keys(value).some((field) => !fields.includes(field))) {
    fail(`${context} contains unexpected properties`);
  }
}

function containsPrivateData(value, knownCanary = null) {
  if (typeof value === "string") {
    return (knownCanary !== null && value.includes(knownCanary)) || /truth_canary/i.test(value);
  }
  if (Array.isArray(value)) return value.some((item) => containsPrivateData(item, knownCanary));
  if (!isObject(value)) return false;
  return Object.entries(value).some(([key, nested]) => {
    const normalizedKey = key.toLowerCase().replace(/[^a-z0-9]/g, "");
    return privateKeyPattern.test(normalizedKey) || containsPrivateData(nested, knownCanary);
  });
}

function validateSignalIdentity(signalIdentity, context) {
  requireExactObject(signalIdentity, signalIdentityFields, context);
  if (typeof signalIdentity.signal_id !== "string" || !signalIdentity.signal_id) {
    fail(`${context}.signal_id must be a non-empty string`);
  }
  if (signalIdentity.revision !== 1) fail(`${context}.revision must be 1`);
}

function validateSourceInput(sourceInput, context, entityIds, zoneIds) {
  requireExactObject(sourceInput, sourceInputFields, context);
  if (typeof sourceInput.source_input_id !== "string" || !sourceInput.source_input_id) {
    fail(`${context}.source_input_id must be a non-empty string`);
  }
  if (!sourceModalities.has(sourceInput.modality)) fail(`${context}.modality is unsupported`);
  if (typeof sourceInput.content !== "string" || !sourceInput.content.startsWith("SIMULACIÓN:")) {
    fail(`${context}.content must start with SIMULACIÓN:`);
  }
  if (typeof sourceInput.reporter_id !== "string" || !entityIds.has(sourceInput.reporter_id)) {
    fail(`${context}.reporter_id is not in the active pack`);
  }
  if (typeof sourceInput.origin_reference !== "string" || !sourceInput.origin_reference) {
    fail(`${context}.origin_reference must be a non-empty string`);
  }
  if (typeof sourceInput.declared_location !== "string" || !zoneIds.has(sourceInput.declared_location)) {
    fail(`${context}.declared_location is not in the active pack`);
  }
}

async function loadPack(directory) {
  const root = resolve(directory);
  const [manifest, zonesFile, entitiesFile, resourcesFile, timelineFile, hiddenTruth] = await Promise.all([
    readJson(resolve(root, "manifest.json")),
    readJson(resolve(root, "zones.json")),
    readJson(resolve(root, "entities.json")),
    readJson(resolve(root, "resources.json")),
    readJson(resolve(root, "timeline.json")),
    readJson(resolve(root, "hidden-truth.json"))
  ]);

  if (!manifest.pack_id || !manifest.pack_version) fail("manifest pack identity is required");
  if (!/^[a-f0-9]{64}$/.test(manifest.pack_digest)) fail("manifest pack_digest must be 64 lowercase hex characters");
  if (!Number.isInteger(manifest.duration_seconds) || manifest.duration_seconds <= 0) fail("duration_seconds must be a positive integer");
  if (Number.isNaN(Date.parse(manifest.scenario_start))) fail("scenario_start must be an ISO timestamp");
  if (!Array.isArray(zonesFile.zones) || !Array.isArray(entitiesFile.entities)) fail("zones and entities arrays are required");
  if (!Array.isArray(resourcesFile.resources) || !Array.isArray(timelineFile.events)) fail("resources and timeline arrays are required");
  if (hiddenTruth.visibility !== "postmortem_only" || !hiddenTruth.canary) fail("hidden truth needs postmortem_only visibility and a canary");

  const publicPack = { manifest, zones: zonesFile.zones, entities: entitiesFile.entities, resources: resourcesFile.resources, events: timelineFile.events };
  if (containsPrivateData(publicPack, hiddenTruth.canary)) fail("public pack contains private evaluator data");

  const zoneIds = zonesFile.zones.map((item) => item.zone_id);
  const entityIds = entitiesFile.entities.map((item) => item.entity_id);
  const resourceIds = resourcesFile.resources.map((item) => item.resource_id);
  const eventIds = timelineFile.events.map((item) => item.event_id);
  const sourceInputIds = timelineFile.events.map((item) => item.source_input?.source_input_id);
  const signalIds = timelineFile.events.map((item) => item.signal_identity?.signal_id);
  if (![zoneIds, entityIds, resourceIds, eventIds, sourceInputIds, signalIds].every(unique)) fail("pack IDs must be unique inside their collection");

  const zones = new Set(zoneIds);
  const entities = new Set(entityIds);
  for (const entity of entitiesFile.entities) {
    if (!zones.has(entity.zone_id)) fail(`unknown entity zone: ${entity.zone_id}`);
  }
  for (const resource of resourcesFile.resources) {
    if (!zones.has(resource.initial_zone_id)) fail(`unknown resource zone: ${resource.initial_zone_id}`);
  }
  for (const event of timelineFile.events) {
    if (!Number.isInteger(event.due_seconds) || event.due_seconds < 0 || event.due_seconds > manifest.duration_seconds) {
      fail(`invalid due_seconds for ${event.event_id}`);
    }
    validateSignalIdentity(event.signal_identity, `${event.event_id}.signal_identity`);
    validateSourceInput(event.source_input, `${event.event_id}.source_input`, entities, zones);
  }

  return {
    manifest,
    events: [...timelineFile.events].sort((left, right) =>
      left.due_seconds - right.due_seconds || left.event_id.localeCompare(right.event_id)
    ),
    zones: zonesFile.zones.map(({ zone_id, name }) => ({ zone_id, label: name })),
    zoneIds: zones,
    entityIds: entities
  };
}

const pack = await loadPack(options.pack);
const runId = options.runId ?? `run-${pack.manifest.pack_id}`;
let stateVersion = Number(options.stateVersion ?? 0);
if (!Number.isInteger(stateVersion) || stateVersion < 0) fail("--state-version must be a non-negative integer");
const operationId = options.operationId ?? mode;
if (!/^[a-zA-Z0-9._-]+$/.test(operationId)) fail("--operation-id may contain letters, numbers, dot, underscore, and dash");
const gatewayUrl = (options.gatewayUrl ?? process.env.GATEWAY_URL ?? "").replace(/\/$/, "");
if (options.connected && !gatewayUrl) fail("GATEWAY_URL or --gateway-url is required in connected mode");
log(`pack=${pack.manifest.pack_id} run=${runId} mode=${mode} transport=${options.dryRun ? "dry-run" : "connected"}`);

let sequence = 0;
let eventsSent = 0;
const commandId = (suffix) => {
  sequence += 1;
  return `cmd-${runId}-${operationId}-${String(sequence).padStart(3, "0")}-${suffix}`;
};

const atScenarioSecond = (seconds) =>
  new Date(Date.parse(pack.manifest.scenario_start) + seconds * 1000).toISOString();

function command(commandType, payload, suffix, causationId = null) {
  return {
    command_id: commandId(suffix),
    run_id: runId,
    pack_id: pack.manifest.pack_id,
    pack_version: pack.manifest.pack_version,
    pack_digest: pack.manifest.pack_digest,
    expected_state_version: stateVersion,
    actor: "scenario-controller",
    command_type: commandType,
    payload,
    causation_id: causationId
  };
}

async function emit(nextCommand) {
  if (options.dryRun) {
    process.stdout.write(`${JSON.stringify(nextCommand)}\n`);
    stateVersion += 1;
    return;
  }

  const response = await fetch(`${gatewayUrl}/api/commands`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(nextCommand)
  });
  const text = await response.text();
  let body;
  try {
    body = text ? JSON.parse(text) : {};
  } catch {
    body = { message: text };
  }
  if (!response.ok || body.error) {
    fail(`command ${nextCommand.command_id} failed (${response.status}): ${JSON.stringify(body)}`);
  }
  if (!Number.isInteger(body.state_version)) fail(`command ${nextCommand.command_id} returned no state_version`);
  stateVersion = body.state_version;
  process.stdout.write(`${JSON.stringify({
    command_id: body.command_id,
    state_version: body.state_version,
    replayed: body.replayed,
    status: "accepted"
  })}\n`);
}

async function advanceTo(seconds, suffix) {
  if (!Number.isInteger(seconds) || seconds < 0 || seconds > pack.manifest.duration_seconds) {
    fail(`scenario second must be between 0 and ${pack.manifest.duration_seconds}`);
  }
  const next = command("advance_clock", { scenario_at: atScenarioSecond(seconds) }, suffix);
  await emit(next);
  return next.command_id;
}

async function emitSourceInput(event, causationId) {
  const scenarioAt = atScenarioSecond(event.due_seconds);
  const payload = {
    signal_identity: event.signal_identity,
    source_input: event.source_input,
    scenario_at: scenarioAt,
    received_at: scenarioAt,
    correlation_id: `corr-${event.event_id}`,
    zone_catalog: pack.zones
  };
  await emit(command("receive_source_input", payload, event.event_id, causationId));
  eventsSent += 1;
}

if (mode === "run") {
  const untilSeconds = Number(options.untilSeconds ?? pack.manifest.duration_seconds);
  if (!Number.isInteger(untilSeconds) || untilSeconds < 0 || untilSeconds > pack.manifest.duration_seconds) {
    fail(`--until-seconds must be between 0 and ${pack.manifest.duration_seconds}`);
  }
  await emit(command("resume_run", {}, "resume"));
  for (const event of pack.events.filter((item) => item.due_seconds <= untilSeconds)) {
    const clockCommandId = await advanceTo(event.due_seconds, `clock-${event.event_id}`);
    await emitSourceInput(event, clockCommandId);
  }
} else if (mode === "advance") {
  await advanceTo(Number(options.toSeconds), "clock-manual");
} else if (mode === "pause") {
  await emit(command("pause_run", {}, "pause"));
} else if (mode === "resume") {
  await emit(command("resume_run", {}, "resume"));
} else if (mode === "inject") {
  if (!options.sourceInput) fail("--mode inject requires --source-input <json-file>");
  const injected = await readJson(resolve(options.sourceInput));
  if (containsPrivateData(injected)) fail("injection contains private evaluator data");
  requireExactObject(injected, injectionFields, "injection");
  validateSignalIdentity(injected.signal_identity, "injection.signal_identity");
  validateSourceInput(injected.source_input, "injection.source_input", pack.entityIds, pack.zoneIds);
  const dueSeconds = Number(options.toSeconds);
  const event = {
    event_id: `injected-${operationId}`,
    due_seconds: dueSeconds,
    signal_identity: injected.signal_identity,
    source_input: injected.source_input
  };
  const clockCommandId = await advanceTo(dueSeconds, "clock-injected");
  await emitSourceInput(event, clockCommandId);
}

if (options.connected && options.json && mode === "run") {
  process.stdout.write(`${JSON.stringify({
    run_id: runId,
    pack_id: pack.manifest.pack_id,
    pack_version: pack.manifest.pack_version,
    pack_digest: pack.manifest.pack_digest,
    events_sent: eventsSent,
    state_version: stateVersion,
    status: "timeline_complete"
  })}\n`);
}
