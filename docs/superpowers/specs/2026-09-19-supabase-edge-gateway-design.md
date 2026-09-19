# Supabase Edge Gateway design

## Goal

Replace the Azure Functions host with one Supabase Edge Function while preserving the existing
Gateway HTTP contract. The deployed function must provide a stable public URL that the dashboard,
scenario controller, E2E runner and HappyRobot development workflows can all reach.

This migration does not itself send Email, Web Voice or PSTN traffic. It removes the hosting
blocker so a subsequent, explicitly selected HappyRobot channel can perform one controlled live
interaction.

The demo dashboard continues to run locally. Only the Gateway needs a stable public address because
HappyRobot must reach it without depending on the operator laptop or a temporary tunnel.

## Options considered

1. **Supabase Edge Function — selected.** Reuses the existing Supabase project, database RPCs and
   secrets platform. It introduces no additional hosting provider and keeps operational setup
   small for the demo.
2. **Cloudflare Worker.** Also provides a stable public URL and a small runtime, but adds another
   account, deployment configuration and secret store.
3. **Local Gateway with a tunnel.** Requires the least code, but availability and often the URL
   depend on one laptop and a running tunnel, which does not meet the stable-endpoint requirement.

## Architecture

Create one Edge Function named `gateway`. Its base URL is:

```text
https://<project-ref>.supabase.co/functions/v1/gateway
```

The function dispatches internally by method and path and preserves these suffixes:

```text
GET  /api/snapshot?run_id=<run-id>
POST /api/commands
POST /api/event-router
```

Consumers therefore configure `GATEWAY_URL` to the function base URL and continue appending the
same `/api/...` paths. The Azure implementation remains temporarily in the repository as a
reference and rollback option; it is not invoked by the Supabase deployment.

The Edge entry point strips the hosted or local prefix through the `gateway` path segment before
matching `/api/snapshot`, `/api/commands` or `/api/event-router`. The dashboard replaces its current
root-relative `new URL("/api/...", gatewayUrl)` calls with an explicit append helper so the
`/functions/v1/gateway` base path is not discarded.

## Components

### Edge entry point

`supabase/functions/gateway/index.ts` owns HTTP routing, CORS preflight handling and conversion of
handler results to standard `Response` objects. Unknown routes return a JSON 404 and unsupported
methods return a JSON 405. CORS is deliberately open for this short-lived demo.

### Shared Gateway core

Framework-neutral modules under `supabase/functions/gateway/` contain:

- REST/RPC calls to the existing `get_run_snapshot`, `apply_command`, `claim_outbox` and
  `finish_outbox` database functions;
- current command envelope and domain-identity validation;
- current HappyRobot outbox dispatch logic.

The behavior and status codes remain consistent with `docs/contracts/gateway-api.md`.

### Supabase configuration

`supabase/config.toml` configures the `gateway` function with platform JWT verification disabled.
The Gateway is public for this controlled demo: callers do not need a Supabase JWT, API key or
custom Gateway token. Domain guards still require the correct run/pack identity, current state
version and an approved Action before Coordination can perform an effect.

The deployed function reads these server-side secrets:

- `HAPPYROBOT_KEY`
- `HAPPYROBOT_BASE_URL`
- `HAPPYROBOT_ENV`
- `HAPPYROBOT_INTAKE_WORKFLOW_ID`
- `HAPPYROBOT_COMMAND_WORKFLOW_ID`
- `HAPPYROBOT_COORDINATION_WORKFLOW_ID`

The Edge runtime already provides `SUPABASE_URL` and its project keys. The implementation prefers
the `default` value from `SUPABASE_SECRET_KEYS` and falls back to the legacy
`SUPABASE_SERVICE_ROLE_KEY`. Neither is sent to browsers or committed.

## Request flow

1. A caller invokes the stable Edge Function URL.
2. The entry point handles CORS and validates the route and method.
3. Snapshot and command routes call the existing database RPCs using the service role.
4. The event router claims at most one outbox item, starts the allowlisted HappyRobot workflow and
   records the dispatch receipt through `finish_outbox`.
5. HappyRobot callbacks continue returning domain commands through `/api/commands`.

No table or workflow payload contract changes are required. One compatibility migration extends
`finish_outbox` with `p_retryable boolean default true`. Existing dry-run dispatch keeps the current
retry behavior. A failed non-dry-run Coordination launch passes `false`, transitions directly to
`failed` and requires human review instead of risking a duplicate external effect.

## CORS and demo access

The dashboard requires browser access, so the function responds to `OPTIONS` and returns explicit
CORS headers with `Access-Control-Allow-Origin: *`, `GET, POST, OPTIONS` methods and the `Accept` and
`Content-Type` request headers used by the app. Scripts and HappyRobot use the same public routes.

This intentionally favors demo simplicity over production security. The service-role/secret key
still never leaves the function. A production deployment would require a separate authentication
design and is outside this workstream.

## Error handling

- Invalid command envelopes return 400.
- Missing runs return 404.
- State conflicts and idempotency conflicts return 409.
- Rate limiting returns 429.
- Provider or database failures return a stable JSON 500 response without leaking credentials or
  upstream response bodies.
- The event router always finalizes a claimed outbox item as dispatched, pending for a permitted
  dry-run retry, or failed.
- A non-dry-run Coordination launch failure is never automatically retried; the operator must
  inspect it and create a new approved Action if another attempt is appropriate.

The existing in-memory rate limit is retained for demo parity. It is instance-local and is not
presented as a distributed production control.

## Verification and delivery sequence

Execute the work in this order:

1. Run static/type checks for the Edge Function.
2. Serve it locally with Deno and verify CORS, validation and route behavior; use the Supabase CLI
   API deployment path so the bundled module graph can include the existing handlers outside the
   function directory.
3. Deploy `gateway` and smoke-test `GET /api/snapshot` against one seeded demo run.
4. Open the local dashboard with the deployed function base as `gateway_url` and verify snapshot
   loading plus one operator command.
5. Execute the existing DANA and wildfire E2E runner in `dry-run` against the deployed URL.
6. Only after that passes, install and publish the native Email branch in the HappyRobot
   `development` Coordination workflow, configure a newly approved Action, and run one explicit
   `email` interaction with the existing live-contact confirmation guard.

## Documentation changes

Update `.env.example`, the launch README and the Gateway contract with the deployed base URL shape,
required Edge secrets, local-dashboard instructions, deploy commands and the separation between
hosting mode and `interaction_mode`.

## Scope boundaries

Included: Edge Gateway implementation, deployment configuration, the non-retryable live dispatch
guard, dashboard URL compatibility, contract-preserving tests and runbook updates.

Excluded: deleting Azure files, hosting the dashboard publicly, publishing HappyRobot production
workflows, provisioning PSTN credentials, or contacting a real recipient during the Gateway
implementation. Installing the native Email branch in HappyRobot development and performing the
single controlled email are the immediately following workstream after Gateway verification.
