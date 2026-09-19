# Controlled real-interaction extension

This directory describes a native extension of `crisis-response-coordination`; it is not a fourth
workflow and it contains no channel-sending implementation. HappyRobot's Web Voice, Email and
optional PSTN nodes own the external effects. `platform-export.json` is a sanitized declarative
blueprint because no authenticated Platform export was available when it was created.

## 1. What is safe by default

- The optional Coordination input `interaction_mode` selects the channel. A missing value always
  resolves to `dry-run` inside `Build Dispatch Envelope`.
- Dry-run renders the same immutable dispatch envelope as live modes, but invokes no Voice, Email
  or PSTN node.
- Every spoken subject/body begins with `SIMULACIÓN —`.
- A contact must be an exact member of `DEMO_ALLOWED_CONTACT_IDS`.
- The run, Action approval, pack identity and state are fetched again immediately before any
  external effect.
- A selected channel gets one immutable `attempt_id` in the form
  `<dispatch_id>:<channel>:1`.

The stable `dispatch_id` identifies the logical interaction. The `attempt_id` identifies the one
channel actually attempted. A known Web Voice preflight failure may select Email before an attempt
exists; it preserves `dispatch_id` and then creates the Email attempt. Once an attempt starts, there
is no channel fallback.

## 2. Development variables

Configure these in the HappyRobot `development` environment. Do not export the variables endpoint
or copy its values into this repository.

| Variable | Visibility | Purpose |
| --- | --- | --- |
| `GATEWAY_URL` | visible | State Gateway base URL |
| `DEMO_INTERACTION_MODE` | visible | Operator-side guard/label; not the dispatch channel source |
| `DEMO_ALLOWED_CONTACT_IDS` | visible | Exact logical contact allowlist |
| `DEMO_CONTACT_ID` | visible | Selected logical contact ID |
| `DEMO_CONTACT_NAME` | visible | Non-sensitive display alias |
| `DEMO_CONTACT_EMAIL` | hidden | Consented Email destination |
| `DEMO_CONTACT_PHONE` | hidden | Optional existing verified PSTN destination |

Start with the operator guard `DEMO_INTERACTION_MODE=dry-run`,
`DEMO_ALLOWED_CONTACT_IDS=demo-field-lead` and `DEMO_CONTACT_ID=demo-field-lead`. PSTN remains
disabled unless an operator explicitly selects an already verified development credential and
destination; this workstream does not buy, provision or verify a number. The Gateway injects
`interaction_mode` only into Coordination dispatches. The workflow does not read the mutable
environment label to select a channel.

## 3. Install the native extension

1. Open the workflow identified by `HAPPYROBOT_COORDINATION_WORKFLOW_ID`.
2. Fork the current development version as
   `crisis-response-coordination-real-interaction-1.0.0`, engine v3.
3. Keep the existing `Get Snapshot` and `Revalidate Action` nodes unchanged.
4. Reproduce the nodes in `platform-export.json` after `Revalidate Action` using HappyRobot native
   Conditions, variable mappings, Web Voice/Voice Agent, Email and HTTP actions.
5. Connect the existing false revalidation branch to `Stop And Route To Human Review`.
6. Keep `Render Dispatch Only` isolated from all channel nodes.
7. Run `test-all` in development before replacing the development live version. Do not publish to
   production from this runbook.

The declarative export deliberately has `publication_status=not_published_without_credentials`.
Change that only by replacing the file with a sanitized export fetched from an authenticated
development workspace after successful checks.

## 4. Preflight immediately before an effect

Follow this order for every run:

1. Fetch `GET {{GATEWAY_URL}}/api/snapshot?run_id={{dispatch.run_id}}`.
2. Require `run.status=running` and the referenced Action still `approved`.
3. Require exact `run_id`, `pack_id`, `pack_version`, `pack_digest` and `action_id` equality across
   trigger, immutable dispatch and fresh snapshot.
4. Require the snapshot state version not to precede the dispatch state version.
5. Re-check exact logical contact membership in `DEMO_ALLOWED_CONTACT_IDS`.
6. Re-check the prefix, subject and body all start with `SIMULACIÓN —`.
7. Verify `attempt_id=<dispatch_id>:<selected_channel>:1`.
8. Reject the dispatch if any snapshot Outcome already has the same `action_id`, `dispatch_id`
   causation or `attempt_id`, or if any prior attempt starts with the same `dispatch_id`.
9. Reject the dispatch if snapshot events/outbox already mark the dispatch, Action or attempt as
   started.
10. Only then enter the native channel node.

If any check fails, stop with `needs_human_review`; do not contact anyone.

A completed dry-run records an Outcome, so its Action and dispatch are consumed. A later live run
must start from a newly approved Action and a new `dispatch_id`; changing only
`interaction_mode` is intentionally rejected by the idempotency guard.

## 5. Channel selection and fallback

The Gateway sets the optional trigger `interaction_mode` explicitly for live dispatches. When the
field is absent, the workflow takes `dry-run` regardless of the environment label:

- `dry-run`: render and normalize a `partial` callback with
  `observed_effects.interaction_mode=dry-run`; invoke no external channel.
- `web_voice`: use native Web Voice as the primary live channel. The first utterance is the exact
  simulation prefix, followed by the mission and an accept/reject request.
- `email`: use the native Email node. Both subject and body carry the exact simulation prefix.
- `pstn`: use the native Voice Agent PSTN transport only behind the existing-credential gate.

One fallback is allowed only for a known Web Voice availability failure detected before opening a
session and before creating a Web Voice attempt. In that case select Email, preserve `dispatch_id`
and create `<dispatch_id>:email:1`. A result of `unknown` means an effect may have occurred: record
the `unknown` Outcome, route to human review, and never retry or switch channels automatically.

## 6. Callback and Outcome mapping

Each selected branch emits exactly one object matching `callback.schema.json`. Correlation is
relational as well as structural:

- `callback.dispatch_id == dispatch.dispatch_id`;
- `callback.attempt_id == <dispatch_id>:<callback.channel>:1`;
- callback run and Action IDs equal the dispatch IDs;
- the status maps without reinterpretation: `success`, `partial`, `failed`, `no_response` or
  `unknown` becomes the homonymous Outcome status.

Before writing the Outcome, fetch another snapshot and revalidate the callback correlation and
pack identity. Build `command_id=callback:<provider_event_id>` and preserve it on redelivery. The
Outcome is a complete v2 object: contract version, run/pack identity, scenario and receipt times,
correlation/causation, Action and attempt IDs, status, summary, observed effects and evidence are
all populated. Its stable identity is
`outcome:<attempt_id>:<provider_event_id>`, avoiding collisions across attempts/providers while
remaining identical on redelivery.

Both callback paths persist first. Normal statuses continue to `Complete Normal Callback` only
after `record_outcome` succeeds. `unknown` is also persisted, then routes to human review; it never
retries or falls back to another channel.

## 7. Sanitized export procedure

After authenticated `test-all` passes in development:

1. Resolve the version ID by the exact version name.
2. Fetch only version metadata and nodes.
3. Do not request the workflow variables endpoint.
4. Scrub keys matching credentials, authorization material, webhook destinations, email or phone.
5. Confirm the result has one `version` object and a `nodes` array.
6. Scan the result for real addresses, phone numbers and credential-like values before replacing
   `platform-export.json`.

The repository alone does not prove a Platform version was created, tested or published. Record
those facts only from authenticated Platform responses and keep the base version available in
history.
