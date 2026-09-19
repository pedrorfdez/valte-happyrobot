import { readFile } from "node:fs/promises";
import { resolve } from "node:path";

import Ajv2020 from "ajv/dist/2020.js";
import addFormats from "ajv-formats";

const schemaRoot = resolve("schemas/v2");
const schemaFiles = {
  signal: "signal.schema.json",
  incident: "incident.schema.json",
  plan: "plan.schema.json",
  action: "action.schema.json",
  outcome: "outcome.schema.json"
};
const exampleFiles = [
  "examples/contracts/dana-chain.json",
  "examples/contracts/wildfire-chain.json"
];
const interactionOutcomeCommandFile = "examples/real-interaction/record-outcome-command.json";
const identityFields = [
  "contract_version",
  "run_id",
  "pack_id",
  "pack_version",
  "pack_digest"
];

const load = async (file) => JSON.parse(await readFile(file, "utf8"));
const ajv = new Ajv2020({ allErrors: true, strict: true });
addFormats(ajv);
ajv.addSchema(await load(resolve(schemaRoot, "common.schema.json")));
for (const file of Object.values(schemaFiles)) {
  ajv.addSchema(await load(resolve(schemaRoot, file)));
}

const failures = [];
const signalEvidenceMatches = (evidence, signal) =>
  Array.isArray(evidence) && evidence.some((item) =>
    item.kind === "signal"
    && item.signal_id === signal.signal_id
    && item.revision === signal.revision
  );

for (const exampleFile of exampleFiles) {
  const chain = await load(resolve(exampleFile));
  const failureCountBeforeChain = failures.length;

  for (const [kind, schemaFile] of Object.entries(schemaFiles)) {
    const validate = ajv.getSchema(`https://valte.dev/schemas/v2/${schemaFile}`);
    if (!validate(chain[kind])) {
      failures.push(`${exampleFile} ${kind}: ${ajv.errorsText(validate.errors)}`);
    }
  }

  for (const kind of Object.keys(schemaFiles).filter((kind) => kind !== "signal")) {
    for (const field of identityFields) {
      if (chain[kind][field] !== chain.signal[field]) {
        failures.push(`${exampleFile}: ${kind}.${field} differs from Signal`);
      }
    }
  }

  for (const kind of ["incident", "plan", "action", "outcome"]) {
    if (!signalEvidenceMatches(chain[kind].evidence, chain.signal)) {
      failures.push(`${exampleFile}: ${kind} lacks exact Signal revision evidence`);
    }
  }

  if (!chain.plan.incident_ids.includes(chain.incident.incident_id)) {
    failures.push(`${exampleFile}: Plan does not include Incident`);
  }
  if (!chain.plan.action_ids.includes(chain.action.action_id)) {
    failures.push(`${exampleFile}: Plan does not include Action`);
  }
  if (chain.action.plan_id !== chain.plan.plan_id) {
    failures.push(`${exampleFile}: Action does not reference Plan`);
  }
  if (chain.action.incident_id !== chain.incident.incident_id) {
    failures.push(`${exampleFile}: Action does not reference Incident`);
  }
  if (chain.outcome.action_id !== chain.action.action_id) {
    failures.push(`${exampleFile}: Outcome does not reference Action`);
  }

  if (failures.length === failureCountBeforeChain) {
    console.log(`PASS ${chain.signal.pack_id}: Signal → Incident → Plan → Action → Outcome`);
  }
}

const interactionCommand = await load(resolve(interactionOutcomeCommandFile));
const validateOutcome = ajv.getSchema("https://valte.dev/schemas/v2/outcome.schema.json");
const interactionFailureCount = failures.length;
if (interactionCommand.command_type !== "record_outcome") {
  failures.push(`${interactionOutcomeCommandFile}: command_type must be record_outcome`);
}
if (!validateOutcome(interactionCommand.payload?.outcome)) {
  failures.push(`${interactionOutcomeCommandFile} outcome: ${ajv.errorsText(validateOutcome.errors)}`);
}
if (failures.length === interactionFailureCount) {
  console.log("PASS real-interaction: callback → Outcome v2 → record_outcome");
}

if (failures.length > 0) {
  console.error(failures.join("\n"));
  process.exitCode = 1;
}
