#!/usr/bin/env node

import { spawn } from "node:child_process";
import { randomUUID } from "node:crypto";
import { appendFile, mkdir, readFile, writeFile } from "node:fs/promises";
import { resolve } from "node:path";

const POLL_MS = 1_000;
const ROUTER_MS = 1_500;
const DEFAULT_TIMEOUT_MS = 180_000;
const MAX_SNAPSHOTS = 300;
const HTTP_TIMEOUT_MS = 30_000;
const SPECIAL_SNAPSHOT_REASONS = new Set(["initial", "timeline_complete", "aborted", "error"]);
const DOMAIN_COLLECTIONS = ["signals", "incidents", "actions", "outcomes"];
const ID_KEYS = new Set([
  "run_id", "signal_id", "incident_id", "plan_id", "action_id", "outcome_id",
  "attempt_id", "reservation_id", "resource_id", "entity_id", "zone_id"
]);
const OUTCOME_STATUSES = new Set(["success", "partial", "failed", "no_response", "unknown"]);
const REQUESTED_RESPONSES = new Set(["accept_or_reject", "acknowledge"]);
const PRIORITY = new Map([["P0", 0], ["P1", 1], ["P2", 2], ["P3", 3]]);
const SECRET_KEY = /authorization|api[_-]?key|anon[_-]?key|service[_-]?role|secret|token|phone|email|raw[_-]?payload/i;
const PRIVATE_KEY = /^(?:hidden_truth|scenario_truth|ground_truth|truth_canary)$/i;
const EMAIL = /\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b/i;
const BEARER = /\bbearer\s+[A-Za-z0-9._~+/=-]+/i;
const JWT = /\beyJ[A-Za-z0-9_-]*\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\b/;
const PHONE = /(?:\+\d[\d\s().-]{7,}\d|\b[6789]\d{2}[ .-]?\d{3}[ .-]?\d{3}\b)/;
const SECRET_IN_STRING = /(?:authorization|api[_-]?key|anon[_-]?key|service[_-]?role|secret|token)\s*[=:]\s*["']?[^\s,"'}]+/i;

const delay = (ms) => new Promise((resolveDelay) => setTimeout(resolveDelay, ms));
const now = () => new Date().toISOString();
const isObject = (value) => value !== null && typeof value === "object" && !Array.isArray(value);
const stableEqual = (left, right) => JSON.stringify(left) === JSON.stringify(right);

class CliError extends Error {}

class HttpTimeoutError extends Error {
  constructor(method, url) {
    super(`${method} ${url} timed out after ${HTTP_TIMEOUT_MS} ms; request state is uncertain. Do not retry the mutation automatically: reconcile the command receipt, snapshot state_version, and visible outbox first.`);
    this.name = "HttpTimeoutError";
    this.code = "http_timeout_uncertain";
  }
}

class E2EAssertionError extends Error {
  constructor(code, details) {
    super(`${code}: ${details}`);
    this.name = "E2EAssertionError";
    this.code = code;
    this.details = details;
  }
}

function assert(condition, code, details) {
  if (!condition) throw new E2EAssertionError(code, details);
}

function usage() {
  return [
    "Usage:",
    "  node scripts/e2e-demo.mjs --gateway <origin> --dana-run <id> --wildfire-run <id> [options]",
    "",
    "Required (or matching environment variable):",
    "  --gateway <origin>                  GATEWAY_URL",
    "  --dana-run <id>                    DANA_RUN_ID",
    "  --wildfire-run <id>                WILDFIRE_RUN_ID",
    "",
    "Options:",
    "  --effects dry-run|web_voice|email|pstn   default: dry-run",
    "  --confirm-live-contact SIMULACION        required for non-dry-run modes",
    "  --timeout-ms <n>                   default: 180000; minimum: 30000",
    "  --artifacts-dir <path>             default: artifacts/e2e",
    "  --preflight-only                   validate clean runs without mutations",
    "  --help"
  ].join("\n");
}

function parseArgs(argv, env = process.env) {
  const valueFlags = new Map([
    ["--gateway", "gateway"],
    ["--dana-run", "danaRun"],
    ["--wildfire-run", "wildfireRun"],
    ["--effects", "effects"],
    ["--confirm-live-contact", "liveConfirmation"],
    ["--timeout-ms", "timeoutMs"],
    ["--artifacts-dir", "artifactsDir"]
  ]);
  const booleanFlags = new Map([["--preflight-only", "preflightOnly"], ["--help", "help"]]);
  const parsed = {};
  const seen = new Set();

  for (let index = 0; index < argv.length; index += 1) {
    const token = argv[index];
    if (seen.has(token)) throw new CliError(`duplicate flag: ${token}`);
    if (booleanFlags.has(token)) {
      parsed[booleanFlags.get(token)] = true;
      seen.add(token);
      continue;
    }
    const key = valueFlags.get(token);
    if (!key) throw new CliError(`unknown argument: ${token}`);
    const value = argv[index + 1];
    if (!value || value.startsWith("--")) throw new CliError(`${token} requires a value`);
    parsed[key] = value;
    seen.add(token);
    index += 1;
  }

  if (parsed.help) return { help: true };
  const gateway = parsed.gateway ?? env.GATEWAY_URL;
  const danaRun = parsed.danaRun ?? env.DANA_RUN_ID;
  const wildfireRun = parsed.wildfireRun ?? env.WILDFIRE_RUN_ID;
  if (!gateway) throw new CliError("--gateway or GATEWAY_URL is required");
  if (!danaRun) throw new CliError("--dana-run or DANA_RUN_ID is required");
  if (!wildfireRun) throw new CliError("--wildfire-run or WILDFIRE_RUN_ID is required");
  if (danaRun === wildfireRun) throw new CliError("DANA and wildfire require distinct run IDs");

  let gatewayUrl;
  try {
    gatewayUrl = new URL(gateway);
  } catch {
    throw new CliError("gateway must be a valid http: or https: URL");
  }
  if (!["http:", "https:"].includes(gatewayUrl.protocol)) {
    throw new CliError("gateway must use http: or https:");
  }
  if (gatewayUrl.username || gatewayUrl.password) throw new CliError("gateway URL must not contain credentials");

  const timeoutMs = Number(parsed.timeoutMs ?? DEFAULT_TIMEOUT_MS);
  if (!Number.isSafeInteger(timeoutMs) || timeoutMs < 30_000) {
    throw new CliError("--timeout-ms must be an integer of at least 30000");
  }
  const effects = parsed.effects ?? "dry-run";
  if (!["dry-run", "web_voice", "email", "pstn"].includes(effects)) {
    throw new CliError("--effects must be dry-run, web_voice, email, or pstn");
  }
  if (effects !== "dry-run" && parsed.liveConfirmation !== "SIMULACION") {
    throw new CliError("live modes require --confirm-live-contact SIMULACION");
  }

  return {
    gateway: gateway.replace(/\/+$/, ""),
    danaRun,
    wildfireRun,
    effects,
    liveConfirmation: parsed.liveConfirmation,
    timeoutMs,
    artifactsDir: parsed.artifactsDir ?? "artifacts/e2e",
    preflightOnly: parsed.preflightOnly ?? false,
    help: false
  };
}

function scenarioConfigs(args) {
  return [
    {
      name: "dana",
      label: "DANA",
      packPath: "scenario-packs/dana-demo",
      runId: args.danaRun,
      forbiddenInNextRun: ["Paiporta", "Catarroja", "rescate acuático", "inundación"]
    },
    {
      name: "wildfire",
      label: "Incendio forestal",
      packPath: "scenario-packs/wildfire-demo",
      runId: args.wildfireRun,
      forbiddenInNextRun: []
    }
  ];
}

async function loadPack(config) {
  const root = resolve(config.packPath);
  const [manifest, hiddenTruth] = await Promise.all([
    readJson(resolve(root, "manifest.json")),
    readJson(resolve(root, "hidden-truth.json"))
  ]);
  assert(typeof manifest.pack_id === "string" && manifest.pack_id, "pack_manifest", `${config.label} has no pack_id`);
  assert(typeof manifest.pack_version === "string" && manifest.pack_version, "pack_manifest", `${config.label} has no pack_version`);
  if (manifest.pack_digest !== undefined) {
    assert(/^[a-f0-9]{64}$/.test(manifest.pack_digest), "pack_manifest", `${config.label} pack_digest is invalid`);
  }
  assert(typeof hiddenTruth.canary === "string" && hiddenTruth.canary, "hidden_truth_config", `${config.label} has no evaluator canary`);
  return { manifest, hiddenCanary: hiddenTruth.canary };
}

async function readJson(path) {
  return JSON.parse(await readFile(path, "utf8"));
}

function redact(value, key = "") {
  if (SECRET_KEY.test(key)) return "[REDACTED]";
  if (typeof value === "string") {
    const trimmed = value.trim();
    if ((trimmed.startsWith("{") && trimmed.endsWith("}")) || (trimmed.startsWith("[") && trimmed.endsWith("]"))) {
      try {
        return JSON.stringify(redact(JSON.parse(trimmed)));
      } catch {
        // Continue with pattern redaction for non-JSON log strings.
      }
    }
    if (BEARER.test(value) || JWT.test(value) || EMAIL.test(value) || PHONE.test(value) || SECRET_IN_STRING.test(value)) {
      return "[REDACTED]";
    }
    return value;
  }
  if (Array.isArray(value)) return value.map((item) => redact(item));
  if (!isObject(value)) return value;
  return Object.fromEntries(Object.entries(value).map(([nestedKey, nested]) => [nestedKey, redact(nested, nestedKey)]));
}

function safeText(value, limit = 1_000) {
  const redacted = redact(String(value));
  return redacted.slice(0, limit);
}

function runDirectoryName(date = new Date()) {
  return date.toISOString().replace(/[-:]/g, "").replace(/\.\d{3}Z$/, "Z") + "-dana-wildfire";
}

async function createArtifacts(args, configs) {
  const root = resolve(args.artifactsDir);
  const runName = runDirectoryName();
  const runDir = resolve(root, runName);
  await mkdir(root, { recursive: true });
  await mkdir(runDir);
  const recorders = {};
  for (const config of configs) {
    const directory = resolve(runDir, config.name);
    await mkdir(directory);
    const paths = {
      directory,
      commands: resolve(directory, "commands.ndjson"),
      snapshots: resolve(directory, "snapshots.ndjson"),
      controllerStdout: resolve(directory, "controller.stdout.log"),
      controllerStderr: resolve(directory, "controller.stderr.log")
    };
    await Promise.all(Object.values(paths).slice(1).map((path) => writeFile(path, "", "utf8")));
    recorders[config.name] = {
      paths,
      history: [],
      exchanges: [],
      lastRecordedVersion: null,
      lastObservedVersion: null,
      snapshotCount: 0
    };
  }
  return {
    root,
    runDir,
    runName,
    displayDir: `${args.artifactsDir.replace(/\/$/, "")}/${runName}`,
    summaryJson: resolve(runDir, "summary.json"),
    summaryMarkdown: resolve(runDir, "summary.md"),
    recorders
  };
}

async function recordExchange(recorder, phase, request, response) {
  const safeResponse = structuredClone(response);
  if (["cross_pack_identity_rejection", "cross_pack_action_rejection"].includes(phase)
    && isObject(safeResponse.body) && typeof safeResponse.body.message === "string") {
    safeResponse.body.message = "[REDACTED FOREIGN REFERENCE]";
  }
  const entry = redact({ at: now(), phase, request, response: safeResponse });
  recorder.exchanges.push(entry);
  await appendFile(recorder.paths.commands, `${JSON.stringify(entry)}\n`, "utf8");
}

async function recordSnapshot(recorder, snapshot, reason) {
  const version = snapshot.run.state_version;
  if (version === recorder.lastRecordedVersion && !SPECIAL_SNAPSHOT_REASONS.has(reason)) return;
  if (recorder.snapshotCount >= MAX_SNAPSHOTS) {
    throw new E2EAssertionError("snapshot_limit_exceeded", `snapshot limit exceeded (${MAX_SNAPSHOTS})`);
  }
  const entry = { at: now(), reason, state_version: version, snapshot: redact(snapshot) };
  recorder.history.push(entry);
  recorder.snapshotCount += 1;
  recorder.lastRecordedVersion = version;
  await appendFile(recorder.paths.snapshots, `${JSON.stringify(entry)}\n`, "utf8");
}

function responseExcerpt(response) {
  return safeText(JSON.stringify(redact(response)), 1_200);
}

async function requestJson(args, method, path, body) {
  const url = `${args.gateway}${path}`;
  let response;
  try {
    response = await fetch(url, {
      method,
      headers: body === undefined ? undefined : { "content-type": "application/json" },
      body: body === undefined ? undefined : JSON.stringify(body),
      signal: AbortSignal.timeout(HTTP_TIMEOUT_MS)
    });
  } catch (error) {
    if (error.name === "TimeoutError" || error.name === "AbortError") throw new HttpTimeoutError(method, url);
    throw new Error(`${method} ${url} transport failure: ${safeText(error.message, 200)}`);
  }
  const text = await response.text();
  let parsed;
  try {
    parsed = text ? JSON.parse(text) : {};
  } catch {
    throw new Error(`${method} ${url} returned non-JSON (${response.status}): ${safeText(text, 200)}`);
  }
  return { ok: response.ok, status: response.status, body: parsed };
}

async function getSnapshot(args, runId) {
  const response = await requestJson(args, "GET", `/api/snapshot?run_id=${encodeURIComponent(runId)}`);
  if (!response.ok || response.body?.error) {
    throw new Error(`GET snapshot failed (${response.status}): ${responseExcerpt(response.body)}`);
  }
  assert(isObject(response.body) && isObject(response.body.run), "snapshot_shape", "snapshot.run is required");
  return response.body;
}

async function postCommand(args, recorder, command, phase) {
  const response = await requestJson(args, "POST", "/api/commands", command);
  await recordExchange(recorder, phase, { method: "POST", path: "/api/commands", body: command }, response);
  return response;
}

async function drainRouter(args, recorder, runId, phase) {
  const body = { limit: 1, run_id: runId, interaction_mode: args.effects };
  const response = await requestJson(args, "POST", "/api/event-router", body);
  await recordExchange(recorder, phase, { method: "POST", path: "/api/event-router", body }, response);
  if (!response.ok || response.body?.error) {
    throw new Error(`POST event-router failed (${response.status}): ${responseExcerpt(response.body)}`);
  }
  for (const key of ["claimed", "dispatched", "failed"]) {
    assert(Number.isInteger(response.body[key]) && response.body[key] >= 0, "router_response", `${key} must be a non-negative integer`);
  }
  assert(response.body.claimed <= 1, "router_limit", `Router claimed ${response.body.claimed} items with limit=1`);
  return response.body;
}

function assertPackIdentity(snapshot, pack, config) {
  const run = snapshot.run;
  const manifest = pack.manifest;
  assert(run.run_id === config.runId, "run_identity", `${config.label} snapshot run_id differs`);
  assert(run.pack_id === manifest.pack_id, "pack_identity", `${config.label} snapshot pack_id differs`);
  assert(run.pack_version === manifest.pack_version, "pack_identity", `${config.label} snapshot pack_version differs`);
  assert(/^[a-f0-9]{64}$/.test(run.pack_digest), "pack_identity", `${config.label} snapshot pack_digest is invalid`);
  if (manifest.pack_digest !== undefined) {
    assert(run.pack_digest === manifest.pack_digest, "pack_identity", `${config.label} manifest and run digests differ`);
  }
  assert(Number.isSafeInteger(run.state_version) && run.state_version >= 0, "state_version", `${config.label} has invalid state_version`);
}

function findPrivateData(value, canary) {
  if (typeof value === "string") return value.includes(canary);
  if (Array.isArray(value)) return value.some((item) => findPrivateData(item, canary));
  if (!isObject(value)) return false;
  return Object.entries(value).some(([key, nested]) => PRIVATE_KEY.test(key) || findPrivateData(nested, canary));
}

function assertNoHiddenTruth(snapshot, pack) {
  assert(!findPrivateData(snapshot, pack.hiddenCanary), "hidden_truth_exposed", "observable snapshot contains evaluator-only data");
}

function assertMonotonicVersions(history) {
  let previous = -1;
  for (const entry of history) {
    assert(entry.state_version >= previous, "non_monotonic_version", `${entry.state_version} followed ${previous}`);
    previous = entry.state_version;
  }
}

function assertRecordIdentity(record, run, kind) {
  assert(record.contract_version === "2.0.0", "contract_version", `${kind} is not v2`);
  for (const key of ["run_id", "pack_id", "pack_version", "pack_digest"]) {
    assert(record[key] === run[key], "record_identity", `${kind}.${key} differs from run`);
  }
}

function signalEvidence(record) {
  return (record?.evidence ?? []).filter((item) => item?.kind === "signal");
}

function evidenceKey(item) {
  return item.kind === "signal" ? `signal:${item.signal_id}:${item.revision}` : `incident:${item.incident_id}`;
}

function contractChainInSnapshot(snapshot) {
  const run = snapshot.run;
  for (const signal of snapshot.signals ?? []) assertRecordIdentity(signal, run, "Signal");
  for (const incident of snapshot.incidents ?? []) assertRecordIdentity(incident, run, "Incident");
  if (snapshot.plan) assertRecordIdentity(snapshot.plan, run, "Plan");
  for (const action of snapshot.actions ?? []) assertRecordIdentity(action, run, "Action");
  for (const outcome of snapshot.outcomes ?? []) assertRecordIdentity(outcome, run, "Outcome");
  if (!snapshot.plan) return null;

  const signals = new Map((snapshot.signals ?? []).map((item) => [`${item.signal_id}:${item.revision}`, item]));
  const incidents = new Map((snapshot.incidents ?? []).map((item) => [item.incident_id, item]));
  const actions = new Map((snapshot.actions ?? []).map((item) => [item.action_id, item]));
  for (const outcome of snapshot.outcomes ?? []) {
    const action = actions.get(outcome.action_id);
    if (!action || action.plan_id !== snapshot.plan.plan_id || !snapshot.plan.action_ids.includes(action.action_id)) continue;
    const incident = incidents.get(action.incident_id);
    if (!incident || !snapshot.plan.incident_ids.includes(incident.incident_id)) continue;
    const incidentSignalKeys = new Set(signalEvidence(incident).map((item) => `${item.signal_id}:${item.revision}`));
    if (![...incidentSignalKeys].some((key) => signals.has(key))) continue;
    const sharedSignal = signalEvidence(action).find((item) => incidentSignalKeys.has(`${item.signal_id}:${item.revision}`));
    if (!sharedSignal) continue;
    const observableEvidence = new Set([
      ...[...signals.keys()].map((key) => `signal:${key}`),
      ...[...incidents.keys()].map((key) => `incident:${key}`)
    ]);
    if (!(outcome.evidence ?? []).some((item) => observableEvidence.has(evidenceKey(item)))) continue;
    return { signal: signals.get(`${sharedSignal.signal_id}:${sharedSignal.revision}`), incident, plan: snapshot.plan, action, outcome };
  }
  return null;
}

function assertContractChain(history) {
  for (const entry of [...history].reverse()) {
    const chain = contractChainInSnapshot(entry.snapshot);
    if (chain) return chain;
  }
  throw new E2EAssertionError("contract_chain", "no complete Signal → Incident → Plan → Action → Outcome chain is observable");
}

function assertWorkflowTrail(history, exchanges) {
  const snapshot = history.at(-1)?.snapshot;
  assert(snapshot, "workflow_trail", "no snapshot history is available");
  const events = snapshot.events ?? [];
  const outbox = snapshot.outbox ?? [];
  const routes = [
    { types: new Set(["source_input.received"]), destination: "crisis-intake" },
    { types: new Set(["signal.created", "signal.revised"]), destination: "crisis-command" },
    { types: new Set(["action.approved"]), destination: "crisis-response-coordination" },
    { types: new Set(["outcome.recorded"]), destination: "crisis-command" }
  ];
  let cursor = -1;
  const destinations = [];
  const dispatches = [];
  for (const route of routes) {
    const index = events.findIndex((event, eventIndex) => eventIndex > cursor && route.types.has(event.event_type)
      && outbox.some((item) => String(item.event_id) === String(event.event_id)
        && item.destination === route.destination && item.status === "dispatched"));
    assert(index > cursor, "workflow_trail", `missing ordered route to ${route.destination}`);
    const event = events[index];
    const outboxItem = outbox.find((item) => String(item.event_id) === String(event.event_id)
      && item.destination === route.destination && item.status === "dispatched");
    const routerExchange = exchanges.find((entry) => entry.request?.path === "/api/event-router"
      && entry.response?.ok === true
      && entry.response?.body?.failed === 0
      && entry.response?.body?.results?.some((result) => result.outbox_id === outboxItem.outbox_id
        && result.destination === route.destination && result.succeeded === true));
    assert(routerExchange, "workflow_trail", `no successful Router response for ${route.destination}`);
    const routerResult = routerExchange.response.body.results.find((result) => result.outbox_id === outboxItem.outbox_id);
    if (routerResult.workflow_run_id !== null && routerResult.workflow_run_id !== undefined) {
      assert(typeof routerResult.workflow_run_id === "string" && routerResult.workflow_run_id,
        "workflow_trail", `invalid workflow_run_id for ${route.destination}`);
    }
    cursor = index;
    destinations.push(route.destination);
    dispatches.push({
      destination: route.destination,
      outbox_id: outboxItem.outbox_id,
      status: outboxItem.status,
      succeeded: routerResult.succeeded,
      workflow_run_id: routerResult.workflow_run_id ?? null
    });
  }
  return { destinations, dispatches };
}

async function observeSnapshot(config, pack, args, recorder, reason) {
  const snapshot = await getSnapshot(args, config.runId);
  assertPackIdentity(snapshot, pack, config);
  assertNoHiddenTruth(snapshot, pack);
  const version = snapshot.run.state_version;
  if (recorder.lastObservedVersion !== null) {
    assert(version >= recorder.lastObservedVersion, "non_monotonic_version", `${version} followed ${recorder.lastObservedVersion}`);
  }
  recorder.lastObservedVersion = version;
  await recordSnapshot(recorder, snapshot, reason);
  return snapshot;
}

function assertClean(snapshot, config) {
  for (const key of DOMAIN_COLLECTIONS) {
    assert(Array.isArray(snapshot[key]), "snapshot_shape", `${key} must be an array`);
    assert(snapshot[key].length === 0, "run_not_clean", `${config.label} ${config.runId} is not clean; recreate or reseed it`);
  }
  assert(snapshot.plan === null, "run_not_clean", `${config.label} ${config.runId} is not clean; recreate or reseed it`);
}

async function preflightScenario(config, pack, args, recorder = null) {
  const snapshot = recorder
    ? await observeSnapshot(config, pack, args, recorder, "initial")
    : await getSnapshot(args, config.runId);
  if (!recorder) {
    assertPackIdentity(snapshot, pack, config);
    assertNoHiddenTruth(snapshot, pack);
  }
  assert(snapshot.run.status === "ready", "run_status", `${config.label} must be ready because the Controller sends resume_run`);
  assertClean(snapshot, config);
  return snapshot;
}

function deadlineRemaining(deadline, phase) {
  const remaining = deadline - Date.now();
  if (remaining <= 0) throw new E2EAssertionError("scenario_timeout", `${phase} exceeded scenario timeout`);
  return remaining;
}

function startController(config, args) {
  return spawn(process.execPath, [
    "scripts/scenario-controller.mjs",
    "--pack", config.packPath,
    "--run-id", config.runId,
    "--gateway-url", args.gateway,
    "--connected",
    "--json"
  ], { stdio: ["ignore", "pipe", "pipe"] });
}

async function waitForController(child, config, pack, recorder, deadline) {
  let stdout = "";
  let stderr = "";
  child.stdout.setEncoding("utf8");
  child.stderr.setEncoding("utf8");
  child.stdout.on("data", (chunk) => { stdout += chunk; });
  child.stderr.on("data", (chunk) => { stderr += chunk; });

  let timedOut = false;
  const timer = setTimeout(() => {
    timedOut = true;
    child.kill("SIGTERM");
  }, deadlineRemaining(deadline, `${config.label} controller`));
  const exit = await new Promise((resolveExit, rejectExit) => {
    child.once("error", rejectExit);
    child.once("exit", (code, signal) => resolveExit({ code, signal }));
  }).finally(() => clearTimeout(timer));

  await Promise.all([
    writeFile(recorder.paths.controllerStdout, safeText(stdout, 1_000_000), "utf8"),
    writeFile(recorder.paths.controllerStderr, safeText(stderr, 1_000_000), "utf8")
  ]);
  const tail = safeText(`${stdout}\n${stderr}`).split(/\r?\n/).filter(Boolean).slice(-20).join(" | ");
  if (timedOut) throw new E2EAssertionError("controller_timeout", `${config.label} controller timed out: ${tail}`);
  if (exit.code !== 0 || exit.signal) {
    throw new E2EAssertionError("controller_failed", `${config.label} controller exit=${exit.code} signal=${exit.signal ?? "none"}: ${tail}`);
  }

  const lines = stdout.split(/\r?\n/).map((line) => line.trim()).filter(Boolean);
  let summary;
  try {
    summary = JSON.parse(lines.at(-1));
  } catch {
    throw new E2EAssertionError("controller_summary", `${config.label} controller has no final JSON summary`);
  }
  assert(summary.run_id === config.runId, "controller_summary", `${config.label} run_id differs`);
  assert(summary.pack_id === pack.manifest.pack_id, "controller_summary", `${config.label} pack_id differs`);
  assert(summary.pack_version === pack.manifest.pack_version, "controller_summary", `${config.label} pack_version differs`);
  assert(summary.pack_digest === pack.digest, "controller_summary", `${config.label} pack_digest differs`);
  assert(Number.isSafeInteger(summary.events_sent) && summary.events_sent >= 1, "controller_summary", `${config.label} sent no events`);
  assert(typeof summary.status === "string" && summary.status, "controller_summary", `${config.label} status is missing`);
  return summary;
}

function phaseDetails(snapshot, phase) {
  return `${phase}; version=${snapshot.run.state_version}; signals=${snapshot.signals.length}; incidents=${snapshot.incidents.length}; actions=${snapshot.actions.length}; outcomes=${snapshot.outcomes.length}`;
}

function initialPlanReady(snapshot, eventsSent) {
  if (snapshot.signals.length < eventsSent || snapshot.incidents.length < 1
    || snapshot.plan === null || snapshot.actions.length < 1) return false;
  const eventTypes = new Map((snapshot.events ?? []).map((event) => [String(event.event_id), event.event_type]));
  return (snapshot.outbox ?? []).every((item) => {
    const type = eventTypes.get(String(item.event_id));
    const isUpstream = item.destination === "crisis-intake"
      || (item.destination === "crisis-command" && ["signal.created", "signal.revised"].includes(type));
    return !isUpstream || item.status === "dispatched";
  });
}

async function waitForSnapshot({ config, pack, args, recorder, deadline, phase, predicate, initialSnapshot }) {
  let snapshot = initialSnapshot ?? await observeSnapshot(config, pack, args, recorder, phase);
  while (true) {
    if (predicate(snapshot)) return snapshot;
    deadlineRemaining(deadline, phase);
    const beforeVersion = snapshot.run.state_version;
    const router = await drainRouter(args, recorder, config.runId, phase);

    if (router.dispatched === 1) {
      do {
        await delay(Math.min(POLL_MS, deadlineRemaining(deadline, phase)));
        snapshot = await observeSnapshot(config, pack, args, recorder, phase);
      } while (snapshot.run.state_version <= beforeVersion);
      continue;
    }

    await delay(Math.min(ROUTER_MS, deadlineRemaining(deadline, phase)));
    snapshot = await observeSnapshot(config, pack, args, recorder, phase);
  }
}

function chooseApproval(snapshot) {
  const activeActionIds = new Set(snapshot.plan?.action_ids ?? []);
  const choices = snapshot.actions
    .filter((action) => activeActionIds.has(action.action_id)
      && action.plan_id === snapshot.plan?.plan_id
      && action.primitive === "contact_entity"
      && action.status === "pending_approval"
      && action.approval_policy === "human_required"
      && typeof action.params?.mission === "string"
      && action.params.mission.trim().length > 0
      && REQUESTED_RESPONSES.has(action.params?.requested_response))
    .sort((left, right) => (PRIORITY.get(left.priority) ?? 99) - (PRIORITY.get(right.priority) ?? 99)
      || left.action_id.localeCompare(right.action_id));
  assert(choices.length > 0, "demo_contact_action_missing",
    "active Plan has no contact_entity Action with pending_approval, human_required, a non-empty params.mission, and params.requested_response accept_or_reject or acknowledge");
  return choices[0];
}

function operatorCommand(snapshot, commandType, payload) {
  return {
    command_id: `e2e-${commandType}-${randomUUID()}`,
    run_id: snapshot.run.run_id,
    pack_id: snapshot.run.pack_id,
    pack_version: snapshot.run.pack_version,
    pack_digest: snapshot.run.pack_digest,
    expected_state_version: snapshot.run.state_version,
    actor: "operator",
    command_type: commandType,
    payload,
    causation_id: null
  };
}

function assertAccepted(response, phase) {
  assert(response.ok && response.body?.ok === true && !response.body.error, "command_rejected", `${phase}: HTTP ${response.status} ${responseExcerpt(response.body)}`);
}

async function approveWithReplay(config, pack, args, recorder, snapshot, action) {
  let command = operatorCommand(snapshot, "approve_action", { action_id: action.action_id });
  let first = await postCommand(args, recorder, command, "approve_action");
  if (first.body?.error === "version_conflict") {
    snapshot = await observeSnapshot(config, pack, args, recorder, "approval_conflict");
    command = operatorCommand(snapshot, "approve_action", { action_id: action.action_id });
    first = await postCommand(args, recorder, command, "approve_action_retry");
  }
  assertAccepted(first, "approve_action");
  const afterFirst = await observeSnapshot(config, pack, args, recorder, "approval_accepted");
  const counts = {
    stateVersion: afterFirst.run.state_version,
    events: afterFirst.events.length,
    outbox: afterFirst.outbox.length,
    outcomes: afterFirst.outcomes.length
  };

  const second = await postCommand(args, recorder, command, "approve_action_replay");
  assertAccepted(second, "approve_action replay");
  assert(second.body.command_id === first.body.command_id, "approval_idempotency", "command_id differs on replay");
  assert(second.body.state_version === first.body.state_version, "approval_idempotency", "state_version differs on replay");
  assert(stableEqual(second.body.result, first.body.result), "approval_idempotency", "result differs on replay");
  assert(second.body.replayed === true, "approval_idempotency", "second approval was not marked replayed");
  const afterReplay = await observeSnapshot(config, pack, args, recorder, "approval_replayed");
  assert(afterReplay.run.state_version === counts.stateVersion, "approval_idempotency", "replay changed state_version");
  assert(afterReplay.events.length === counts.events && afterReplay.outbox.length === counts.outbox
    && afterReplay.outcomes.length === counts.outcomes, "approval_idempotency", "replay created an event, dispatch, or Outcome");
  return { command, first, second, snapshot: afterReplay };
}

function outcomeForAction(snapshot, actionId, interactionMode) {
  const matches = snapshot.outcomes.filter((outcome) => outcome.action_id === actionId);
  if (!matches.length) return null;
  for (const outcome of matches) {
    assert(typeof outcome.attempt_id === "string" && outcome.attempt_id, "outcome_attempt", "Outcome attempt_id is missing");
    assert(OUTCOME_STATUSES.has(outcome.status), "outcome_status", `unsupported Outcome status: ${outcome.status}`);
    assert(outcome.observed_effects?.interaction_mode === interactionMode, "outcome_interaction_mode",
      `Outcome interaction_mode=${outcome.observed_effects?.interaction_mode ?? "missing"}; expected ${interactionMode}`);
  }
  const pairs = matches.map((outcome) => `${outcome.action_id}\u0000${outcome.attempt_id}`);
  assert(new Set(pairs).size === pairs.length, "duplicate_outcome", "duplicate Outcome for action_id + attempt_id");
  return matches[0];
}

function outcomeEvent(snapshot, outcome) {
  return snapshot.events.find((event) => event.event_type === "outcome.recorded"
    && event.payload?.outcome_id === outcome.outcome_id);
}

function materialPlanView(snapshot) {
  const incidentIds = new Set(snapshot.plan?.incident_ids ?? []);
  const actionIds = new Set(snapshot.plan?.action_ids ?? []);
  return {
    objectives: snapshot.plan?.objectives ?? [],
    evidence: snapshot.plan?.evidence ?? [],
    incidents: snapshot.incidents.filter((incident) => incidentIds.has(incident.incident_id)).map((incident) => ({
      priority: incident.priority,
      confidence: incident.confidence,
      hazard_types: incident.hazard_types,
      zone_ids: incident.zone_ids,
      evidence: incident.evidence
    })),
    actions: snapshot.actions.filter((action) => actionIds.has(action.action_id)).map((action) => ({
      primitive: action.primitive,
      target: action.target,
      params: action.params,
      evidence: action.evidence,
      reasoning: action.reasoning,
      priority: action.priority,
      risk: action.risk,
      approval_policy: action.approval_policy
    }))
  };
}

function replansFromOutcome(snapshot, outcome, initialPlan) {
  if (!snapshot.plan || snapshot.plan.plan_version <= initialPlan.version
    || snapshot.plan.supersedes_plan_id !== initialPlan.id) return false;
  const recorded = outcomeEvent(snapshot, outcome);
  if (!recorded) return false;
  const causalReplan = snapshot.events.some((event) => event.event_type === "plan.replaced"
    && String(event.causation_id) === String(recorded.event_id)
    && event.payload?.plan_id === snapshot.plan.plan_id
    && event.state_version > recorded.state_version);
  return causalReplan && !stableEqual(materialPlanView(snapshot), initialPlan.material);
}

function preservesIds(before, after, collection, idKey) {
  const current = new Set(after[collection].map((item) => item[idKey]));
  return before[collection].every((item) => current.has(item[idKey]));
}

async function abortRun(config, pack, args, recorder, snapshot, deadline) {
  const before = snapshot;
  let command = operatorCommand(snapshot, "abort_run", {});
  let response = await postCommand(args, recorder, command, "abort_run");
  if (response.body?.error === "version_conflict") {
    snapshot = await observeSnapshot(config, pack, args, recorder, "abort_conflict");
    command = operatorCommand(snapshot, "abort_run", {});
    response = await postCommand(args, recorder, command, "abort_run_retry");
  }
  assertAccepted(response, "abort_run");
  let aborted;
  do {
    await delay(Math.min(POLL_MS, deadlineRemaining(deadline, `${config.label} abort visibility`)));
    aborted = await observeSnapshot(config, pack, args, recorder, "aborted");
  } while (aborted.run.status !== "aborted");

  assert(aborted.run.state_version > before.run.state_version, "abort_version", "abort_run did not increase state_version");
  assert(preservesIds(before, aborted, "signals", "signal_id"), "abort_projection", "Signals disappeared after abort");
  assert(preservesIds(before, aborted, "incidents", "incident_id"), "abort_projection", "Incidents disappeared after abort");
  assert(preservesIds(before, aborted, "actions", "action_id"), "abort_projection", "Actions disappeared after abort");
  assert(preservesIds(before, aborted, "outcomes", "outcome_id"), "abort_projection", "Outcomes disappeared after abort");
  assert(aborted.plan?.plan_id === before.plan?.plan_id, "abort_projection", "Plan disappeared after abort");
  return { command, response, aborted };
}

function collectPackSpecificIds(value, collected = new Set(), key = "") {
  if (typeof value === "string" && ID_KEYS.has(key)) collected.add(value);
  if (Array.isArray(value)) value.forEach((item) => collectPackSpecificIds(item, collected, key));
  else if (isObject(value)) Object.entries(value).forEach(([nestedKey, nested]) => collectPackSpecificIds(nested, collected, nestedKey));
  return collected;
}

function collectStrings(value, collected = []) {
  if (typeof value === "string") collected.push(value);
  else if (Array.isArray(value)) value.forEach((item) => collectStrings(item, collected));
  else if (isObject(value)) Object.values(value).forEach((nested) => collectStrings(nested, collected));
  return collected;
}

function assertNoCrossPackValues(wildfireSnapshot, danaIds, danaTerms) {
  const wildfireStrings = collectStrings(wildfireSnapshot);
  const values = new Set(wildfireStrings);
  const shared = [...danaIds].filter((id) => values.has(id));
  assert(shared.length === 0, "cross_pack_contamination", `wildfire contains ${shared.length} exact DANA IDs`);
  const text = wildfireStrings.join("\n").toLocaleLowerCase("es-ES");
  const terms = danaTerms.filter((term) => text.includes(term.toLocaleLowerCase("es-ES")));
  assert(terms.length === 0, "cross_pack_contamination", `wildfire contains DANA-only terms: ${terms.join(", ")}`);
}

function withoutNegativeProbeRequests(exchanges) {
  const negativePhases = new Set(["cross_pack_identity_rejection", "cross_pack_action_rejection"]);
  return exchanges.map((entry) => negativePhases.has(entry.phase)
    ? { ...entry, request: "[EXCLUDED NEGATIVE CROSS-PACK PROBE REQUEST]" }
    : entry);
}

async function assertNoCrossPackArtifacts(dana, wildfireConfig, context) {
  const recorder = context.artifacts.recorders[wildfireConfig.name];
  const danaValues = new Set([...dana.ids, dana.pack.id, dana.pack.digest]);
  const danaTerms = [...context.configs[0].forbiddenInNextRun, context.configs[0].label];
  const [stdout, stderr, commandText, snapshotText] = await Promise.all([
    readFile(recorder.paths.controllerStdout, "utf8"),
    readFile(recorder.paths.controllerStderr, "utf8"),
    readFile(recorder.paths.commands, "utf8"),
    readFile(recorder.paths.snapshots, "utf8")
  ]);
  const diskCommands = commandText.split(/\r?\n/).filter(Boolean).map((line) => JSON.parse(line));
  const diskSnapshots = snapshotText.split(/\r?\n/).filter(Boolean).map((line) => JSON.parse(line));
  assertNoCrossPackValues({ history: recorder.history, exchanges: withoutNegativeProbeRequests(recorder.exchanges) }, danaValues, danaTerms);
  assertNoCrossPackValues({ snapshots: diskSnapshots, commands: withoutNegativeProbeRequests(diskCommands), stdout, stderr }, danaValues, danaTerms);
}

function contractVersions(snapshot) {
  const versions = new Set();
  for (const key of DOMAIN_COLLECTIONS) for (const item of snapshot[key]) versions.add(item.contract_version);
  if (snapshot.plan) versions.add(snapshot.plan.contract_version);
  return [...versions].sort();
}

async function runScenario(config, context) {
  const { args, artifacts, packs } = context;
  const pack = packs[config.name];
  const recorder = artifacts.recorders[config.name];
  const startedAt = Date.now();
  const deadline = startedAt + args.timeoutMs;
  const initialSnapshot = await preflightScenario(config, pack, args, recorder);
  pack.digest = initialSnapshot.run.pack_digest;

  const controller = startController(config, args);
  const controllerSummary = await waitForController(controller, config, pack, recorder, deadline);
  let snapshot = await observeSnapshot(config, pack, args, recorder, "timeline_complete");
  const timelineCompleteVersion = snapshot.run.state_version;

  snapshot = await waitForSnapshot({
    config, pack, args, recorder, deadline, phase: "evidence_and_plan", initialSnapshot: snapshot,
    predicate: (current) => initialPlanReady(current, controllerSummary.events_sent)
  });
  const initialPlan = {
    id: snapshot.plan.plan_id,
    version: snapshot.plan.plan_version,
    material: materialPlanView(snapshot)
  };
  const approvedAction = chooseApproval(snapshot);
  const approval = await approveWithReplay(config, pack, args, recorder, snapshot, approvedAction);
  snapshot = approval.snapshot;

  snapshot = await waitForSnapshot({
    config, pack, args, recorder, deadline, phase: "coordination_and_outcome", initialSnapshot: snapshot,
    predicate: (current) => outcomeForAction(current, approvedAction.action_id, args.effects) !== null
  });
  const outcome = outcomeForAction(snapshot, approvedAction.action_id, args.effects);
  const outcomeVersion = snapshot.run.state_version;

  snapshot = await waitForSnapshot({
    config, pack, args, recorder, deadline, phase: "outcome_replan", initialSnapshot: snapshot,
    predicate: (current) => replansFromOutcome(current, outcome, initialPlan)
  });
  assert(snapshot.plan.plan_id !== initialPlan.id, "replan_identity", "replan reused the initial plan_id");
  assert(snapshot.plan.supersedes_plan_id === initialPlan.id, "replan_supersedes", "replan does not supersede the approved Action's Plan exactly");
  assert(!stableEqual(materialPlanView(snapshot), initialPlan.material), "replan_material", "outcome-driven replan has no material Plan/Action change");
  const replanVersion = snapshot.run.state_version;
  const beforeAbort = snapshot;
  const aborted = await abortRun(config, pack, args, recorder, snapshot, deadline);

  assertMonotonicVersions(recorder.history);
  const chain = assertContractChain(recorder.history);
  const workflow = assertWorkflowTrail(recorder.history, recorder.exchanges);
  return {
    name: config.name,
    label: config.label,
    runId: config.runId,
    pack: { id: pack.manifest.pack_id, version: pack.manifest.pack_version, digest: pack.digest },
    versions: {
      initial: initialSnapshot.run.state_version,
      timelineComplete: timelineCompleteVersion,
      outcome: outcomeVersion,
      replan: replanVersion,
      aborted: aborted.aborted.run.state_version
    },
    approvedActionId: approvedAction.action_id,
    outcomeId: outcome.outcome_id,
    ids: collectPackSpecificIds(aborted.aborted),
    abortedSnapshot: aborted.aborted,
    beforeAbort,
    abortCommand: aborted.command,
    abortResponse: aborted.response,
    approvalCommandId: approval.command.command_id,
    idempotency: true,
    contractVersions: contractVersions(aborted.aborted),
    classes: ["Signal", "Incident", "Plan", "Action", "Outcome"],
    workflowTrail: workflow.destinations,
    workflowDispatches: workflow.dispatches,
    replan: {
      initialPlanId: initialPlan.id,
      finalPlanId: snapshot.plan.plan_id,
      supersedesPlanId: snapshot.plan.supersedes_plan_id,
      materialChange: true
    },
    chain: {
      signalId: chain.signal.signal_id,
      incidentId: chain.incident.incident_id,
      planId: chain.plan.plan_id,
      actionId: chain.action.action_id,
      outcomeId: chain.outcome.outcome_id
    },
    controllerSummary,
    durationMs: Date.now() - startedAt
  };
}

function assertScenarioAborted(result, recorder) {
  const logged = recorder.exchanges.some((entry) => entry.request?.body?.actor === "operator"
    && entry.request?.body?.command_type === "abort_run" && entry.response?.body?.ok === true);
  assert(logged, "abort_log", `${result.label} has no accepted operator abort_run in command log`);
  assert(result.abortCommand.actor === "operator" && result.abortResponse.body?.ok === true, "abort_acceptance", `${result.label} abort was not accepted`);
  assert(result.abortedSnapshot.run.status === "aborted", "abort_status", `${result.label} is not aborted`);
  assert(result.versions.aborted > result.versions.replan, "abort_order", `${result.label} abort did not follow replan`);
}

async function assertCrossPackRejections(dana, wildfireConfig, context) {
  const { args, artifacts, packs } = context;
  const recorder = artifacts.recorders[wildfireConfig.name];
  const pack = packs[wildfireConfig.name];
  let snapshot = await preflightScenario(wildfireConfig, pack, args, recorder);
  pack.digest = snapshot.run.pack_digest;
  const initialVersion = snapshot.run.state_version;

  const wrongPack = {
    command_id: `e2e-cross-pack-${randomUUID()}`,
    run_id: wildfireConfig.runId,
    pack_id: dana.pack.id,
    pack_version: dana.pack.version,
    pack_digest: dana.pack.digest,
    expected_state_version: initialVersion,
    actor: "operator",
    command_type: "approve_action",
    payload: { action_id: dana.approvedActionId },
    causation_id: null
  };
  const mismatch = await postCommand(args, recorder, wrongPack, "cross_pack_identity_rejection");
  assert(mismatch.body?.error === "pack_context_mismatch", "cross_pack_rejection", `expected pack_context_mismatch, got ${responseExcerpt(mismatch.body)}`);
  snapshot = await observeSnapshot(wildfireConfig, pack, args, recorder, "cross_pack_identity_checked");
  assert(snapshot.run.state_version === initialVersion, "cross_pack_mutation", "pack mismatch changed wildfire state_version");

  const foreignAction = operatorCommand(snapshot, "approve_action", { action_id: dana.approvedActionId });
  const actionMismatch = await postCommand(args, recorder, foreignAction, "cross_pack_action_rejection");
  assert(actionMismatch.body?.error === "action_not_in_active_pack", "cross_pack_rejection", `expected action_not_in_active_pack, got ${responseExcerpt(actionMismatch.body)}`);
  snapshot = await observeSnapshot(wildfireConfig, pack, args, recorder, "cross_pack_action_checked");
  assert(snapshot.run.state_version === initialVersion, "cross_pack_mutation", "foreign Action changed wildfire state_version");
  assertClean(snapshot, wildfireConfig);
  assertNoCrossPackValues(snapshot, dana.ids, context.configs[0].forbiddenInNextRun);
  return true;
}

function assertSamePipeline(dana, wildfire) {
  assert(stableEqual(dana.contractVersions, wildfire.contractVersions), "pipeline_contracts", "contract versions differ between scenarios");
  assert(stableEqual(dana.classes, wildfire.classes), "pipeline_classes", "domain classes differ between scenarios");
  assert(stableEqual(dana.workflowTrail, wildfire.workflowTrail), "pipeline_workflows", "workflow sequence differs between scenarios");
  assert(dana.runId !== wildfire.runId, "scenario_identity", "run IDs must differ");
  assert(dana.pack.id !== wildfire.pack.id && dana.pack.digest !== wildfire.pack.digest, "scenario_identity", "pack IDs and digests must differ");
  assert(dana.versions.replan > dana.versions.outcome && wildfire.versions.replan > wildfire.versions.outcome,
    "replan_order", "each scenario must replan after its Outcome");
  assert(Boolean(dana.outcomeId) && Boolean(wildfire.outcomeId), "outcome_missing", "each scenario must produce an Outcome");
}

function serializableResult(result) {
  if (!result) return null;
  return {
    label: result.label,
    run_id: result.runId,
    pack: result.pack,
    versions: result.versions,
    approved_action_id: result.approvedActionId,
    outcome_id: result.outcomeId,
    approval_command_id: result.approvalCommandId,
    workflow_trail: result.workflowTrail,
    workflow_dispatches: result.workflowDispatches,
    replan: {
      initial_plan_id: result.replan.initialPlanId,
      final_plan_id: result.replan.finalPlanId,
      supersedes_plan_id: result.replan.supersedesPlanId,
      material_change: result.replan.materialChange
    },
    contract_chain: result.chain,
    duration_ms: result.durationMs
  };
}

function summaryMarkdown(summary) {
  const lines = [
    `# E2E DANA → incendio: ${summary.status}`,
    "",
    `- Efectos: \`${summary.effects}\``,
    `- Duración: ${summary.duration_ms} ms`,
    `- Generado: ${summary.finished_at}`,
    "",
    "| Escenario | Run | Pack | Versiones | Replan | Outcome |",
    "| --- | --- | --- | --- | --- | --- |"
  ];
  for (const result of [summary.dana, summary.wildfire]) {
    if (!result) continue;
    lines.push(`| ${result.label} | \`${result.run_id}\` | \`${result.pack.id}@${result.pack.version}\` | ${result.versions.initial} → ${result.versions.aborted} | \`${result.replan.initial_plan_id}\` → \`${result.replan.final_plan_id}\` (material) | \`${result.outcome_id}\` |`);
  }
  lines.push("", "## Aserciones", "");
  for (const item of summary.assertions) lines.push(`- ${item.status} ${item.name}`);
  if (summary.error) lines.push("", "## Fallo", "", `- Código: \`${summary.error.code}\``, `- Detalle: ${summary.error.message}`);
  return `${lines.join("\n")}\n`;
}

async function writeSummary(artifacts, summary) {
  const clean = redact(summary);
  await writeFile(artifacts.summaryJson, `${JSON.stringify(clean, null, 2)}\n`, "utf8");
  await writeFile(artifacts.summaryMarkdown, summaryMarkdown(clean), "utf8");
}

async function main() {
  let args;
  try {
    args = parseArgs(process.argv.slice(2));
  } catch (error) {
    console.error(`ERROR config: ${safeText(error.message, 400)}`);
    console.error(usage());
    process.exitCode = 2;
    return;
  }
  if (args.help) {
    console.log(usage());
    return;
  }

  const configs = scenarioConfigs(args);
  const loaded = await Promise.all(configs.map(loadPack));
  const packs = Object.fromEntries(configs.map((config, index) => [config.name, loaded[index]]));
  assert(packs.dana.manifest.pack_id !== packs.wildfire.manifest.pack_id, "pack_identity", "DANA and wildfire pack IDs must differ");
  assert(packs.dana.manifest.pack_digest !== packs.wildfire.manifest.pack_digest, "pack_identity", "DANA and wildfire pack digests must differ");
  console.log("PASS config: DANA and wildfire use distinct runs and packs");

  if (args.preflightOnly) {
    for (const config of configs) {
      const snapshot = await preflightScenario(config, packs[config.name], args);
      console.log(`PASS preflight: ${config.label} ${config.runId} ${snapshot.run.status}`);
    }
    return;
  }

  const artifacts = await createArtifacts(args, configs);
  const context = { args, configs, packs, artifacts };
  const startedAt = Date.now();
  let dana = null;
  let wildfire = null;
  const assertions = [];
  try {
    dana = await runScenario(configs[0], context);
    assertScenarioAborted(dana, artifacts.recorders.dana);
    assertions.push({ name: "DANA Signal → Intake → Command → approval → Coordination → Outcome → replan", status: "PASS" });
    assertions.push({ name: "DANA operator abort_run → run.status=aborted", status: "PASS" });

    await assertCrossPackRejections(dana, configs[1], context);
    assertions.push({ name: "cross-pack rejects pack context and foreign Action", status: "PASS" });
    wildfire = await runScenario(configs[1], context);
    assertScenarioAborted(wildfire, artifacts.recorders.wildfire);
    assertions.push({ name: "wildfire uses the same contracts and workflows", status: "PASS" });
    assertions.push({ name: "wildfire operator abort_run → run.status=aborted", status: "PASS" });

    assertNoCrossPackValues(wildfire.abortedSnapshot, dana.ids, configs[0].forbiddenInNextRun);
    await assertNoCrossPackArtifacts(dana, configs[1], context);
    assertSamePipeline(dana, wildfire);
    assertions.push({ name: "no DANA IDs or terms in wildfire state/artifacts outside the two negative probe requests", status: "PASS" });
    assertions.push({ name: "duplicate approvals are idempotent", status: "PASS" });

    const summary = {
      status: "PASS",
      effects: args.effects,
      started_at: new Date(startedAt).toISOString(),
      finished_at: now(),
      duration_ms: Date.now() - startedAt,
      artifacts: { directory: artifacts.displayDir, summary: `${artifacts.displayDir}/summary.md` },
      dana: serializableResult(dana),
      wildfire: serializableResult(wildfire),
      assertions
    };
    await writeSummary(artifacts, summary);
    console.log("PASS DANA: Signal → Intake → Command → approval → Coordination → Outcome → replan");
    console.log("PASS DANA abort: operator abort_run → run.status=aborted");
    console.log("PASS wildfire: same contracts and workflows");
    console.log("PASS wildfire abort: operator abort_run → run.status=aborted");
    console.log("PASS isolation: no DANA IDs or terms in wildfire state/artifacts outside negative probe requests");
    console.log(`Artifacts: ${artifacts.displayDir}/summary.md`);
  } catch (error) {
    const code = error.code ?? error.name ?? "e2e_failure";
    const message = safeText(error.message, 1_200);
    assertions.push({ name: `${code}: ${message}`, status: "FAIL" });
    for (const config of configs) {
      const recorder = artifacts.recorders[config.name];
      const pack = packs[config.name];
      try {
        const snapshot = await getSnapshot(args, config.runId);
        assertNoHiddenTruth(snapshot, pack);
        await recordSnapshot(recorder, snapshot, "error");
      } catch {
        // The original failure remains authoritative; diagnostics are best-effort only.
      }
    }
    await writeSummary(artifacts, {
      status: "FAIL",
      effects: args.effects,
      started_at: new Date(startedAt).toISOString(),
      finished_at: now(),
      duration_ms: Date.now() - startedAt,
      artifacts: { directory: artifacts.displayDir, summary: `${artifacts.displayDir}/summary.md` },
      dana: serializableResult(dana),
      wildfire: serializableResult(wildfire),
      assertions,
      error: { code, message }
    });
    console.error(`FAIL E2E: ${code}: ${message}`);
    console.error(`Artifacts: ${artifacts.displayDir}/summary.md`);
    process.exitCode = 1;
  }
}

await main().catch((error) => {
  console.error(`ERROR: ${safeText(error.message, 1_200)}`);
  process.exitCode = error instanceof CliError ? 2 : 1;
});
