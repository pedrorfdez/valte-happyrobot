# Schemas

The team contract. All components (simulator, HappyRobot workflows,
dashboard) build against these shapes. The core is scenario-agnostic:
no field is specific to floods.

**Source of truth: the JSON Schema files in `schemas/`.** Every field
carries a `description`; those descriptions are written to be injected
into agent prompts, so agents and code always share one definition. Do
not document fields here; document them in the schema files.

- `schemas/entity.schema.json`: an actor. Kinds: `information_source`,
  `authority`, `responder`, `population`. Key fields: `weight`
  (authority prior), `trust` (reporting prior), `jurisdiction`,
  `channel` (real contact), `capabilities`, `units`, `activation`
  (delay + cost; high cost requires human approval), `escalation_to`,
  `provenance` (`plan` from the scenario pack, `discovered` at
  runtime).
- `schemas/zone.schema.json`: geographic unit and canonical location
  key. Everything references locations by zone id. Zones hold the rich
  geodata once: text names (name, municipality, province, country) and
  `centroid` coordinates for the map and rough distances. The zone
  graph (`downstream_of` + `propagation_delay_min`) is the hazard
  propagation model and the honest distance metric.
- `schemas/hazard.schema.json`: ground truth danger, owned by the
  simulator. The agent never reads hazards; it infers them from
  signals.
- Channel payload schemas (`call_record`, `social_post`,
  `news_bulletin`): the native shapes each channel really delivers, and
  the input contract of the HappyRobot ingest workflows. They carry no
  claims, no trust, no resolved zone: perception extracts those and
  produces the normalized signal. Structured sources (`ingest.mode:
  direct`, e.g. sensors) skip perception and POST normalized signals to
  the kernel, keeping the reflex path fast. The call channel contract
  is identical across the three call levels: simulated transcripts
  (level 1), voice-agent citizens (level 2), live human calls (level 3);
  timeline `call` personas are the shared script for all three.
- `schemas/signal.schema.json`: one piece of incoming information,
  post-perception (the normalized internal form). In the timeline, its
  `claims`/`location` are ground truth for scoring perception; channel
  adapters strip them from native payloads.
  Carries location evidence at whatever precision the source provides
  (`location.text`, optional `location.coords`, resolved
  `location.zone`, honest `location.precision` label). Ingestion
  computes per-signal `confidence` from source trust, corroboration,
  consistency, and age, and logs the inputs.
- `schemas/action.schema.json`: one agent decision. `evidence` (typed
  refs: `sig-*` signals, `act-*` prior actions, `evt-*` timer or system
  events) and `reasoning` are mandatory. `status: pending_approval` is
  the human-intervention hook; `in_progress` covers async execution
  (a call ringing). `real_interaction` records the actual call, email,
  or SMS produced. System verbs are a closed set enforced by the
  crisis kernel: `register_entity`, `update_entity`, `set_tripwire`,
  `clear_tripwire`, `schedule_check`. Tripwires are standing rules the
  agent installs so the kernel reacts in milliseconds without
  deliberation; see `docs/backend.md`.

## Design decisions embedded in the schemas

- One canonical location key (zone id); coordinates are zone metadata
  and optional signal evidence, never a parallel truth. Signals carry
  the most precise location the source can give, labeled with its
  precision.
- Two separate priors on entities: `weight` (authority) and `trust`
  (reporting reliability). Per-signal `confidence` computed from
  corroboration is what decisions use; priors only seed it.
- The entity registry is pre-loaded from the scenario pack (the
  emergency plan) but open: agents register discovered entities with
  low trust and low-risk capabilities.
- Scarcity and latency (`units`, `activation.delay_min`) are data, so
  prioritization pressure comes from the scenario pack, not from code.
- Enum policy, three tiers. Tier 1, closed enum: code branches on the
  value (kind, channel.kind, statuses, cost, precision, provenance).
  Tier 2, open in schema but closed at runtime: scenario vocabulary
  validated against the pack registry at write time (capabilities,
  world verbs, hazard types, zone and entity references). Tier 3,
  fully open: only the LLM produces and consumes it (content, notes,
  reasoning, params, zone attributes). All schemas set
  additionalProperties false so undeclared fields fail validation.
