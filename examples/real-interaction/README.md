# Controlled real-interaction demo

The safe default is `dry-run`. Complete the steps in order. Do not run a live step merely because
the local fixtures validate.

## Step 0 — Validate locally

From the repository root:

```bash
jq -e '
  .default_interaction_mode == "dry-run"
  and .message_prefix == "SIMULACIÓN — "
  and .channels[0].id == "web_voice"
  and .channels[1].id == "email"
  and .safety.retry_unknown == false
' happyrobot/integrations/channel-policy.json
```

Validate the dispatch, all three callbacks (including `callback-dry-run.json`), the Router input and
the complete Outcome v2 command, then run `npm run contracts:check`. These checks do not contact
anyone.

## Step 1 — Trigger a dry-run

Keep the development variable at `DEMO_INTERACTION_MODE=dry-run`, then run:

```bash
set -a && source ./.env && set +a
: "${HAPPYROBOT_COORDINATION_WORKFLOW_ID:?missing workflow id}"
test "${DEMO_INTERACTION_MODE:-dry-run}" = dry-run

jq -n \
  --arg environment development \
  --slurpfile payload examples/real-interaction/approved-action.json \
  '{environment: $environment, payload: $payload[0]}' \
| curl --fail-with-body --silent --show-error \
    -X POST \
    -H "Authorization: Bearer $HAPPYROBOT_KEY" \
    -H 'Content-Type: application/json' \
    --data-binary @- \
    "$HAPPYROBOT_BASE_URL/workflows/$HAPPYROBOT_COORDINATION_WORKFLOW_ID/runs" \
| jq -e '{run_id, status}'
```

Check the completed run in Platform, one item at a time:

- `Build Dispatch Envelope` equals `dispatch.json` field for field.
- `dispatch_id` remains `dispatch-demo-001`.
- Prefix, subject and body begin with `SIMULACIÓN —`.
- `demo-field-lead` passes the exact allowlist check.
- The callback matches `callback-dry-run.json`: it is `partial`, includes a valid `received_at` and
  has `interaction_mode=dry-run`.
- Web Voice, Email and PSTN nodes have no invocation, output or usage.
- The Gateway contains one dry-run Outcome for the dispatch.

Stop if any channel node ran. Dry-run must have zero external effects.

The dry-run Outcome consumes this Action/dispatch pair. Never reuse `act-demo-contact-001` or
`dispatch-demo-001` for a later live effect.

## Step 2 — Complete the human gate for a live run

Obtain a newly approved Action event from the Gateway/outbox and save its Coordination wrapper to
a local, unversioned file. It must have a new Action ID, a new dispatch ID and the desired trigger
mode. For example, before Web Voice:

```bash
: "${LIVE_APPROVED_ACTION_FILE:?path to the new unversioned Coordination payload}"
: "${LIVE_ACTION_ID:?newly approved Action id}"
: "${LIVE_DISPATCH_ID:?new dispatch id}"

test "$LIVE_ACTION_ID" != act-demo-contact-001
test "$LIVE_DISPATCH_ID" != dispatch-demo-001
jq -e \
  --arg action_id "$LIVE_ACTION_ID" \
  --arg dispatch_id "$LIVE_DISPATCH_ID" '
    .interaction_mode == "web_voice"
    and .dispatch_id == $dispatch_id
    and .event.event_type == "action.approved"
    and .event.payload.action.action_id == $action_id
  ' "$LIVE_APPROVED_ACTION_FILE"
```

Open `docs/demo-contacts.md` and verbally verify every checkbox immediately before the effect.
Also fetch the latest Gateway snapshot and confirm:

1. the run is still active;
2. `act-demo-contact-001` is still `approved`;
3. run, Action and dispatch have the same pack identity;
4. the state version is current;
5. the recipient has consented and is still allowlisted;
6. no Outcome or started attempt exists for the new Action, dispatch or `attempt_id`;
7. the rendered message is correct.

If any answer is uncertain, return to `dry-run`. Do not commit the checklist as completed.

## Step 3 — Run one Web Voice interaction

Only after Step 2, trigger the workflow with the new payload. `Build Dispatch Envelope` reads
`trigger.interaction_mode`; if the field is absent it deliberately uses `dry-run`. The native
`Web Voice Session` node opens the session and the authorized HappyRobot UI/client attaches to it;
the shell does not need to print or transform session credentials:

```bash
set -a && source ./.env && set +a
jq -n \
  --arg environment development \
  --slurpfile payload "$LIVE_APPROVED_ACTION_FILE" \
  '{environment: $environment, payload: $payload[0]}' \
| curl --fail-with-body --silent --show-error \
    -X POST \
    -H "Authorization: Bearer $HAPPYROBOT_KEY" \
    -H 'Content-Type: application/json' \
    --data-binary @- \
    "$HAPPYROBOT_BASE_URL/workflows/$HAPPYROBOT_COORDINATION_WORKFLOW_ID/runs" \
| jq -e '{run_id, status}'
```

If an authorized Web Voice client requires the access response directly, retain the complete
response in a private temporary file instead of piping it through a projection that discards the
URL or access value:

```bash
set -a && source ./.env && set +a
umask 077
web_voice_response="$(mktemp)"
trap 'rm -f "$web_voice_response"' EXIT
jq -n \
  --arg workflow_id "$HAPPYROBOT_COORDINATION_WORKFLOW_ID" \
  --slurpfile data "$LIVE_APPROVED_ACTION_FILE" \
  '{workflow_id: $workflow_id, env: "development", ttl_seconds: 900, data: $data[0]}' \
| curl --fail-with-body --silent --show-error \
    -X POST \
    -H "Authorization: Bearer $HAPPYROBOT_KEY" \
    -H 'Content-Type: application/json' \
    --data-binary @- \
    --output "$web_voice_response" \
    "$HAPPYROBOT_BASE_URL/voice/tokens/"
jq -e '
  (.run_id | type == "string" and length > 0)
  and (.room_name | type == "string" and length > 0)
  and (.token | type == "string" and length > 0)
  and (.url | type == "string" and length > 0)
' "$web_voice_response" >/dev/null
```

Pass that file directly to the authorized client while the same shell remains open; do not echo,
log or copy its contents. The `trap` removes it when the shell exits. The recipient must hear
`SIMULACIÓN —` before the mission and answer accept or reject. Verify exactly one session, a
callback carrying `$LIVE_DISPATCH_ID` and `$LIVE_DISPATCH_ID:web_voice:1`, and exactly one
correlated Outcome.

## Step 4 — Use Email only for a known preflight failure

Use Email only when Web Voice is known to be unavailable before opening a session and before a Web
Voice `attempt_id` exists.

1. Preserve the new `$LIVE_DISPATCH_ID` selected in Step 2.
2. Before triggering, set `interaction_mode=email` in the new Coordination payload.
3. Confirm the hidden Email destination belongs to `demo-field-lead`.
4. Run the same approved Action.
5. Verify `attempt_id=$LIVE_DISPATCH_ID:email:1`.
6. Verify exactly one native Email invocation and one Outcome.

Do not perform this fallback after starting Web Voice. Do not perform it after any `unknown`
result. Subject and body must both start with `SIMULACIÓN —`.

## Step 5 — Verify callback idempotency

Use a seeded or connected run whose identity matches `record-outcome-command.json`. Update only
`expected_state_version` before the first request, then submit the same file twice:

```bash
set -a && source ./.env && set +a
for attempt in 1 2; do
  curl --fail-with-body --silent --show-error \
    -X POST \
    -H 'Content-Type: application/json' \
    --data-binary @examples/real-interaction/record-outcome-command.json \
    "$GATEWAY_URL/api/commands" \
    | jq -c '{command_id, state_version, result}'
done
```

Both responses must have the same `command_id`, `state_version` and `result`; the second request
must not advance state. Count Outcomes for the logical dispatch:

```bash
curl --fail-with-body --silent --show-error \
  "$GATEWAY_URL/api/snapshot?run_id=run-wildfire-demo" \
| jq -e '[.outcomes[] | select(.attempt_id | startswith("dispatch-demo-001:"))] | length == 1'
```

Expected output: `true`.

## Step 6 — Exercise the uncertain-effect stop path

Inject `callback-unknown.json` only as the custom output of the callback-normalization node in a
controlled Platform test. Confirm all three results:

- the Outcome status is `unknown` and is persisted before routing onward;
- no second Voice, Email or PSTN invocation occurs;
- the run routes to human review and does not release or retry anything automatically.

For a normal callback, confirm persistence succeeds and the flow reaches
`Complete Normal Callback` without human review.

## Step 7 — Platform verification and sanitized export

This step requires valid HappyRobot development credentials. If they are unavailable, stop here;
the repository export remains `declarative_only` and nothing has been published.

Resolve the isolated version by name and run its native tests:

```bash
set -a && source ./.env && set +a
coordination_version_id="$(
  curl --fail-with-body --silent --show-error \
    -H "Authorization: Bearer $HAPPYROBOT_KEY" \
    "$HAPPYROBOT_BASE_URL/workflows/$HAPPYROBOT_COORDINATION_WORKFLOW_ID/versions?page=1&page_size=100&sort=desc" \
  | jq -er '[.data[] | select(.name == "crisis-response-coordination-real-interaction-1.0.0")][0].id'
)"
curl --fail-with-body --silent --show-error \
  -X POST \
  -H "Authorization: Bearer $HAPPYROBOT_KEY" \
  -H 'Content-Type: application/json' \
  -d '{"environment":"development"}' \
  "$HAPPYROBOT_BASE_URL/versions/$coordination_version_id/test-all" \
| jq -e '.results | length > 0 and all(.status == "success")'
```

Expected output: `true`. Only then may an operator replace the live **development** version from
Platform UI. Never change production from this procedure. Follow the sanitized export procedure in
`happyrobot/integrations/README.md`; never fetch or version environment variable values.
