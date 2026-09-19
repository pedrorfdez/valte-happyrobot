# HappyRobot crisis workflows

## Runtime boundary

- Environment: `development` only.
- Region: EU (`https://platform.eu.happyrobot.ai/api/v2`).
- State reads: `GET $GATEWAY_URL/api/snapshot?run_id=<id>`.
- State writes: `POST $GATEWAY_URL/api/commands`.
- Direct Supabase writes are forbidden.
- REST/Webhooks are used; MCP is not used.

## Workflow chain

1. `crisis-intake`: source input → Signal v2 → `upsert_signal`.
2. `crisis-command`: observable snapshot → Incidents + Plan + Actions → `replace_plan`.
3. `crisis-response-coordination`: approved Action → Outcome v2 → `record_outcome`.

Workflows never call one another synchronously. The persisted outbox and Event Router
dispatch the allowlisted events. No workflow keeps a long wait or shared in-memory state.

## Concurrency and relational guards

- Every write uses `expected_state_version` from the latest Gateway snapshot, never from a
  historical trigger event.
- Intake reads a snapshot immediately before `upsert_signal`. A `409` causes one fresh
  snapshot, full Signal revalidation and one retry. A second conflict stops the run and leaves
  the execution for human review; workflows never spin or retry indefinitely.
  This optimistic-concurrency path prevents competing workflow executions from continuing with
  a stale state version.
- Before `upsert_signal`, a native guard proves that the normalized Signal identity equals
  `event.payload.signal_identity`, and that run/pack identity and envelope fields equal the
  trigger and current snapshot.
- Before `replace_plan`, a native guard proves that every Incident, Plan and Action belongs to
  the same run/pack as the snapshot; Plan references resolve exactly to the emitted Incidents
  and Actions; every Action points to that Plan and an emitted Incident; and evidence revisions
  resolve to current observable evidence.
- Coordination proceeds only while the Action is still `approved`, belongs to the active Plan,
  is listed by that Plan, and has `evidence_status: valid` with resolvable current evidence.
- Before `record_outcome`, a native guard proves that `outcome.action_id` equals the approved
  trigger Action, `outcome.attempt_id` equals `dispatch_id`, and Outcome run/pack identity equals
  the revalidated snapshot.
- Any failed guard stops before the HTTP write and routes the execution to human review. JSON
  Schema validation remains necessary but is not treated as
  sufficient for these cross-object invariants.

## Required local IDs

Use only `HAPPYROBOT_INTAKE_WORKFLOW_ID`, `HAPPYROBOT_COMMAND_WORKFLOW_ID` and
`HAPPYROBOT_COORDINATION_WORKFLOW_ID` for shared workflow IDs. Resolve version/node IDs
ephemerally by name through the API. Never commit API keys, recipient addresses, tokens,
generated webhook URLs or raw variable values.

## Platform workflow versioning

1. Fork an unpublished development version.
2. Configure native nodes in the Platform UI.
3. Set trigger custom output from the matching repository fixture.
4. Run the output-node smoke and `test-all`.
5. Exercise the validation-failure branches and Intake's bounded `409` retry.
6. Publish only to `development`.
7. Export and scrub metadata/nodes into each `platform-export.json`.

## Pack isolation

Every trigger, prompt, HTTP body and output carries `run_id`, `pack_id`, `pack_version`,
`pack_digest` and `state_version`. `hidden_truth` is forbidden before postmortem. Prompt
templates remain scenario-neutral; pack-specific vocabulary lives only in the runtime context.
