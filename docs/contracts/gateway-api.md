# State Gateway HTTP contract

The Gateway is the only writer of operational state. Scenario Controller, HappyRobot, the dashboard, and the E2E runner use these routes:

```text
POST /api/commands
GET  /api/snapshot?run_id=<run-id>
POST /api/event-router
```

## Commands

`POST /api/commands` accepts:

```json
{
  "command_id": "cmd-unique",
  "run_id": "run-id",
  "pack_id": "pack-id",
  "pack_version": "1.0.0",
  "pack_digest": "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
  "expected_state_version": 3,
  "actor": "scenario-controller|happyrobot|operator",
  "command_type": "receive_source_input|upsert_signal|replace_plan|approve_action|reject_action|record_outcome|advance_clock|pause_run|resume_run|abort_run",
  "payload": {},
  "causation_id": null
}
```

An accepted command returns HTTP 200:

```json
{
  "ok": true,
  "command_id": "cmd-unique",
  "run_id": "run-id",
  "state_version": 4,
  "replayed": false,
  "result": {},
  "events": []
}
```

Repeating an identical `command_id` returns the persisted response with `replayed: true` and creates no new state, event, or outbox row. Reusing the ID with another body returns `idempotency_mismatch`.

A stale write returns HTTP 409:

```json
{
  "ok": false,
  "error": "version_conflict",
  "run_id": "run-id",
  "expected_state_version": 3,
  "actual_state_version": 4
}
```

Validation and missing-resource errors use HTTP 400/404 and:

```json
{
  "ok": false,
  "error": "stable_code",
  "message": "Human-readable detail"
}
```

## Snapshot

`GET /api/snapshot` returns the complete observable projection:

```json
{
  "run": {},
  "signals": [],
  "incidents": [],
  "plan": null,
  "actions": [],
  "outcomes": [],
  "resources": [],
  "events": [],
  "outbox": []
}
```

It never exposes hidden/scenario truth, service credentials, or recipient contact details.

## Event Router

`POST /api/event-router` accepts an optional run scope and interaction mode. It
claims at most one pending job per invocation, even if a legacy caller sends a
larger `limit` value:

```json
{
  "limit": 1,
  "run_id": "run-id",
  "interaction_mode": "dry-run"
}
```

`run_id` is optional for administrative draining and required by the E2E runner so DANA and wildfire cannot consume each other's pending work.
`interaction_mode` is allowlisted to `dry-run`, `web_voice`, `email`, or `pstn`; it defaults to `dry-run` and is forwarded only to Coordination dispatches.
Callers must wait for the visible state/outbox receipt before invoking the Router again. This keeps workflow effects ordered without adding another queue or lock to the demo.

It returns:

```json
{
  "claimed": 0,
  "dispatched": 0,
  "failed": 0,
  "results": []
}
```

The only routing rules are:

```text
source_input.received -> crisis-intake
signal.created         -> crisis-command
signal.revised         -> crisis-command
action.approved        -> crisis-response-coordination
outcome.recorded       -> crisis-command
```

The Router starts a HappyRobot run and never writes a domain object on its behalf. Workflow results return through `POST /api/commands`.
