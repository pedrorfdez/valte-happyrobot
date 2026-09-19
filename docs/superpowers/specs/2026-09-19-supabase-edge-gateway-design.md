# Supabase Edge Gateway design

## Goal

Replace the Azure Functions host with one Supabase Edge Function while preserving the existing
Gateway HTTP contract. The deployed function must provide a stable public URL that the dashboard,
scenario controller, E2E runner and HappyRobot development workflows can all reach.

This migration does not itself send Email, Web Voice or PSTN traffic. It removes the hosting
blocker so a subsequent, explicitly selected HappyRobot channel can perform one controlled live
interaction.

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

## Components

### Edge entry point

`supabase/functions/gateway/index.ts` owns HTTP routing, CORS preflight handling and conversion of
handler results to standard `Response` objects. Unknown routes return a JSON 404 and unsupported
methods return a JSON 405.

### Shared Gateway core

Framework-neutral modules under `supabase/functions/gateway/` contain:

- authentication with the existing `x-gateway-token` header;
- REST/RPC calls to the existing `get_run_snapshot`, `apply_command`, `claim_outbox` and
  `finish_outbox` database functions;
- current command envelope and domain-identity validation;
- current HappyRobot outbox dispatch logic.

The behavior and status codes remain consistent with `docs/contracts/gateway-api.md`.

### Supabase configuration

`supabase/config.toml` configures the `gateway` function with platform JWT verification disabled.
Authentication remains the Gateway's explicit `x-gateway-token` check because HappyRobot and the
demo scripts are not Supabase users and do not carry Supabase access tokens.

The deployed function reads these server-side secrets:

- `GATEWAY_TOKEN`
- `HAPPYROBOT_KEY`
- `HAPPYROBOT_BASE_URL`
- `HAPPYROBOT_ENV`
- `HAPPYROBOT_INTAKE_WORKFLOW_ID`
- `HAPPYROBOT_COMMAND_WORKFLOW_ID`
- `HAPPYROBOT_COORDINATION_WORKFLOW_ID`

The Edge runtime already provides `SUPABASE_URL` and `SUPABASE_SERVICE_ROLE_KEY`; neither is sent
to browsers or committed.

## Request flow

1. A caller sends `x-gateway-token` to the stable Edge Function URL.
2. The entry point validates CORS, route, method and authentication.
3. Snapshot and command routes call the existing database RPCs using the service role.
4. The event router claims at most one outbox item, starts the allowlisted HappyRobot workflow and
   records the dispatch receipt through `finish_outbox`.
5. HappyRobot callbacks continue returning domain commands through `/api/commands`.

No database schema or workflow payload contract changes are required.

## CORS and authentication

The dashboard requires browser access, so the function responds to `OPTIONS` and returns explicit
CORS headers. For the demo, allowed origins are configured with `GATEWAY_ALLOWED_ORIGINS` as a
comma-separated list. Requests without an `Origin` header remain valid for scripts and HappyRobot.

All three data routes require `x-gateway-token`. The token is configured in trusted callers and
as an Edge Function secret. The service-role key never leaves the function.

## Error handling

- Missing or invalid Gateway credentials return 401.
- CORS rejection returns 403.
- Invalid command envelopes return 400.
- Missing runs return 404.
- State conflicts and idempotency conflicts return 409.
- Rate limiting returns 429.
- Provider or database failures return a stable JSON 500 response without leaking credentials or
  upstream response bodies.
- The event router always finalizes a claimed outbox item as dispatched or failed.

The existing in-memory rate limit is retained for demo parity. It is instance-local and is not
presented as a distributed production control.

## Verification

Before changing HappyRobot configuration:

1. Run static/type checks for the Edge Function.
2. Serve it locally with the Supabase CLI and verify authentication, validation and route behavior.
3. Deploy `gateway` and smoke-test `GET /api/snapshot` against one seeded demo run.
4. Execute the existing DANA and wildfire E2E runner in `dry-run` against the deployed URL.
5. Only after that passes, configure a newly approved Action and run one explicit `email`
   interaction with the existing live-contact confirmation guard.

## Documentation changes

Update `.env.example`, the launch README and the Gateway contract with the deployed base URL shape,
required Edge secrets, deploy commands and the separation between hosting mode and
`interaction_mode`.

## Scope boundaries

Included: Edge Gateway implementation, deployment configuration, contract-preserving tests and
runbook updates.

Excluded: deleting Azure files, changing the database schema, publishing HappyRobot production
workflows, provisioning PSTN credentials, or contacting a real recipient during implementation.
