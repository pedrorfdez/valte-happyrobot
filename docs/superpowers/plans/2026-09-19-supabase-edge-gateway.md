# Supabase Edge Gateway Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the Azure-hosted Gateway with one public Supabase Edge Function while preserving the existing Gateway contract and preventing automatic retries of ambiguous live Coordination dispatches.

**Architecture:** A small Edge adapter converts the standard Web `Request` into the request/context shape already used by the three Azure handlers, so the business logic is not copied. The adapter routes the existing `/api/snapshot`, `/api/commands` and `/api/event-router` suffixes beneath one stable Supabase function URL. The local dashboard appends those suffixes without discarding the function path, and HappyRobot development variables point to the same public base URL.

**Tech Stack:** Supabase Edge Functions/Deno, existing JavaScript Azure handlers, PostgreSQL RPCs, HappyRobot API v2 EU, vanilla browser JavaScript, Node.js 24, Supabase CLI through `npx`.

**Implementation style:** The user explicitly requested no TDD and minimum code. Implement each focused change first, then run the listed static, contract and connected smoke checks. Do not add a test framework.

---

## File structure

| Path | Responsibility |
| --- | --- |
| `api/_shared/supabase.mjs` | Runtime-neutral environment lookup and Supabase privileged REST/RPC client. |
| `api/event-router/index.mjs` | Existing HappyRobot dispatch plus live/non-live retry decision. |
| `supabase/config.toml` | Local/deployed Edge Function configuration with platform JWT verification disabled. |
| `supabase/functions/gateway/index.ts` | Thin CORS, path-routing and Web-to-Azure request adapter. |
| `supabase/migrations/202609190002_non_retryable_live_dispatch.sql` | Adds `p_retryable` to `finish_outbox` without changing tables. |
| `app/app.js` | Builds Gateway endpoint URLs without losing the Supabase function prefix. |
| `.env.example` | Documents the stable Edge Gateway base URL. |
| `README.md` | Replaces the Azure/local Gateway launch path with Supabase Edge deployment and local dashboard steps. |
| `docs/contracts/gateway-api.md` | Records the hosted URL shape, public-demo access and non-retryable live failure behavior. |
| `docs/demo-runbook.md` | Uses the Supabase Edge URL during rehearsal. |

The separate HappyRobot Email-node installation is not part of this plan. This plan must finish with the existing end-to-end suite passing in `dry-run`; the native Email branch is the next independently verifiable workstream.

### Task 1: Make the existing Gateway modules run in Node and Deno

**Files:**

- Modify: `api/_shared/supabase.mjs`
- Modify: `api/event-router/index.mjs`

- [ ] **Step 1: Add runtime-neutral environment helpers and modern Supabase secret-key support**

Replace the local `required` helper at the top of `api/_shared/supabase.mjs` with:

```js
export function readEnv(name) {
  return globalThis.Deno?.env?.get?.(name)
    ?? globalThis.process?.env?.[name];
}

export function requiredEnv(name) {
  const value = readEnv(name);
  if (!value) throw new Error(`${name} is required`);
  return value;
}

function supabaseSecretKey() {
  const rawKeys = readEnv("SUPABASE_SECRET_KEYS");
  if (rawKeys) {
    let keys;
    try {
      keys = JSON.parse(rawKeys);
    } catch {
      throw new Error("SUPABASE_SECRET_KEYS must be valid JSON");
    }
    if (typeof keys?.default === "string" && keys.default) return keys.default;
    throw new Error("SUPABASE_SECRET_KEYS.default is required");
  }
  return requiredEnv("SUPABASE_SERVICE_ROLE_KEY");
}
```

Replace the complete `requireGatewayAuth` function with:

```js
export function requireGatewayAuth(req, context) {
  const token = readEnv("GATEWAY_TOKEN");
  if (!token) return;
  const provided = req.headers?.["x-gateway-token"] ?? req.headers?.["X-Gateway-Token"];
  if (provided !== token) {
    context.log.warn?.("gateway auth failed");
    const err = new Error("gateway auth required");
    err.status = 401;
    err.exposeMessage = true;
    throw err;
  }
}
```

Inside the existing `supabaseRequest` function, replace exactly its first two declarations and leave the remainder unchanged:

```js
const baseUrl = requiredEnv("SUPABASE_URL").replace(/\/$/, "");
const serviceKey = supabaseSecretKey();
```

- [ ] **Step 2: Reuse the shared required-environment helper in the Router**

Change the first import in `api/event-router/index.mjs` and delete its local `required` function:

```js
import {
  callRpc,
  jsonResponse,
  requireGatewayAuth,
  requiredEnv
} from "../_shared/supabase.mjs";
```

Replace every `required(...)` call in that file with `requiredEnv(...)`. The resulting credential lookups must be:

```js
const baseUrl = requiredEnv("HAPPYROBOT_BASE_URL").replace(/\/$/, "");
authorization: `Bearer ${requiredEnv("HAPPYROBOT_KEY")}`,
const workflowId = requiredEnv(settingName);
environment: requiredEnv("HAPPYROBOT_ENV"),
```

- [ ] **Step 3: Run static and contract checks**

Run:

```bash
node --check api/_shared/supabase.mjs
node --check api/event-router/index.mjs
npm run contracts:check
```

Expected: both syntax checks exit silently with code `0`; the contract command prints PASS for DANA, wildfire and real-interaction fixtures.

- [ ] **Step 4: Commit only the runtime-neutral changes**

```bash
git add api/_shared/supabase.mjs api/event-router/index.mjs
git commit -m "refactor: share gateway runtime configuration"
```

### Task 2: Disable automatic retry after a failed live Coordination launch

**Files:**

- Create: `supabase/migrations/202609190002_non_retryable_live_dispatch.sql`
- Modify: `api/event-router/index.mjs`

- [ ] **Step 1: Add the backward-compatible RPC migration**

Create `supabase/migrations/202609190002_non_retryable_live_dispatch.sql` with:

```sql
drop function if exists finish_outbox(uuid, uuid, boolean, text);

create or replace function finish_outbox(
  p_outbox_id uuid,
  p_dispatch_id uuid,
  p_succeeded boolean,
  p_error text default null,
  p_retryable boolean default true
) returns jsonb
language plpgsql
security definer
set search_path = public
as $$
declare
  v_row outbox%rowtype;
begin
  update outbox
  set status = case
        when p_succeeded then 'dispatched'
        when not p_retryable then 'failed'
        when attempts >= 3 then 'failed'
        else 'pending'
      end,
      available_at = case
        when p_succeeded or not p_retryable then available_at
        else now() + interval '5 seconds'
      end,
      lease_until = null,
      dispatched_at = case when p_succeeded then now() else null end,
      last_error = case
        when p_succeeded then null
        else left(coalesce(p_error, 'dispatch failed'), 1000)
      end
  where outbox_id = p_outbox_id
    and dispatch_id = p_dispatch_id
    and status = 'claimed'
    and lease_until > now()
  returning * into v_row;

  if not found then
    return jsonb_build_object('error', 'outbox_lease_not_found');
  end if;

  return jsonb_build_object(
    'outbox_id', v_row.outbox_id,
    'status', v_row.status,
    'attempts', v_row.attempts
  );
end;
$$;

revoke all on function finish_outbox(uuid, uuid, boolean, text, boolean)
from public, anon, authenticated;
grant execute on function finish_outbox(uuid, uuid, boolean, text, boolean)
to service_role;
```

- [ ] **Step 2: Pass the retry policy from the Router**

Immediately before the `finish_outbox` RPC in `api/event-router/index.mjs`, add:

```js
const retryable = !(
  job.destination === "crisis-response-coordination"
  && interactionMode !== "dry-run"
);
```

Make the complete RPC call:

```js
const receipt = await callRpc("finish_outbox", {
  p_outbox_id: job.outbox_id,
  p_dispatch_id: job.dispatch_id,
  p_succeeded: succeeded,
  p_error: errorMessage,
  p_retryable: retryable
});
```

This flag is ignored on success. On a failed `email`, `web_voice` or `pstn` Coordination launch it moves the claimed row directly to `failed`; all dry-run and upstream workflow failures preserve the existing retry policy.

- [ ] **Step 3: Verify syntax and migration shape**

Run:

```bash
node --check api/event-router/index.mjs
rg -n "p_retryable|not p_retryable|to service_role" \
  supabase/migrations/202609190002_non_retryable_live_dispatch.sql
```

Expected: syntax exits `0`; the search shows the parameter, both non-retryable branches and the service-role grant.

- [ ] **Step 4: Commit the dispatch guard**

```bash
git add api/event-router/index.mjs \
  supabase/migrations/202609190002_non_retryable_live_dispatch.sql
git commit -m "fix: prevent retry of ambiguous live dispatch"
```

### Task 3: Add the public Supabase Edge Function adapter

**Files:**

- Create: `supabase/config.toml`
- Create: `supabase/functions/gateway/index.ts`

- [ ] **Step 1: Configure the Edge Function**

Create `supabase/config.toml` with:

```toml
project_id = "valte-happyrobot"

[functions.gateway]
verify_jwt = false
entrypoint = "./functions/gateway/index.ts"
```

- [ ] **Step 2: Implement the thin request adapter**

Create `supabase/functions/gateway/index.ts` with:

```ts
import snapshot from "../../../api/snapshot/index.mjs";
import commands from "../../../api/commands/index.mjs";
import eventRouter from "../../../api/event-router/index.mjs";

type AzureResponse = {
  status: number;
  headers?: Record<string, string>;
  body?: string;
};

type AzureContext = {
  res?: AzureResponse;
  log: {
    error: (...args: unknown[]) => void;
    warn: (...args: unknown[]) => void;
  };
};

type AzureRequest = {
  query: Record<string, string>;
  headers: Record<string, string>;
  body?: string;
};

type AzureHandler = (
  context: AzureContext,
  request: AzureRequest
) => Promise<void>;

const CORS_HEADERS = {
  "access-control-allow-origin": "*",
  "access-control-allow-methods": "GET, POST, OPTIONS",
  "access-control-allow-headers": "accept, content-type",
  "access-control-max-age": "86400"
};

const ROUTES = new Map<string, AzureHandler>([
  ["GET /api/snapshot", snapshot],
  ["POST /api/commands", commands],
  ["POST /api/event-router", eventRouter]
]);

const KNOWN_PATHS = new Set([
  "/api/snapshot",
  "/api/commands",
  "/api/event-router"
]);

function json(status: number, body: Record<string, unknown>): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: {
      ...CORS_HEADERS,
      "content-type": "application/json; charset=utf-8"
    }
  });
}

function gatewayPath(pathname: string): string | null {
  const marker = "/gateway";
  const markerIndex = pathname.lastIndexOf(marker);
  if (markerIndex === -1) return null;
  return pathname.slice(markerIndex + marker.length) || "/";
}

async function azureRequest(request: Request): Promise<AzureRequest> {
  const url = new URL(request.url);
  const body = request.method === "GET" ? undefined : await request.text();
  return {
    query: Object.fromEntries(url.searchParams.entries()),
    headers: Object.fromEntries(request.headers.entries()),
    body: body || undefined
  };
}

Deno.serve(async (request) => {
  if (request.method === "OPTIONS") {
    return new Response(null, { status: 204, headers: CORS_HEADERS });
  }

  const url = new URL(request.url);
  const path = gatewayPath(url.pathname);
  if (!path) return json(404, { error: "route_not_found" });

  const handler = ROUTES.get(`${request.method} ${path}`);
  if (!handler) {
    return KNOWN_PATHS.has(path)
      ? json(405, { error: "method_not_allowed" })
      : json(404, { error: "route_not_found" });
  }

  const context: AzureContext = {
    log: {
      error: (...args) => console.error(...args),
      warn: (...args) => console.warn(...args)
    }
  };

  try {
    await handler(context, await azureRequest(request));
    if (!context.res) {
      return json(500, { error: "gateway_response_missing" });
    }

    const headers = new Headers(context.res.headers);
    for (const [name, value] of Object.entries(CORS_HEADERS)) {
      headers.set(name, value);
    }
    return new Response(context.res.body ?? "", {
      status: context.res.status,
      headers
    });
  } catch (error) {
    console.error(error);
    return json(500, { error: "gateway_failure", message: "internal error" });
  }
});
```

- [ ] **Step 3: Format and type-check the function**

Run:

```bash
deno fmt supabase/functions/gateway/index.ts
deno check supabase/functions/gateway/index.ts
npx --yes supabase --version
```

Expected: formatting and type-checking exit `0`; the CLI prints a version.

- [ ] **Step 4: Serve the function locally with Deno**

Load `.env` and start the Deno-compatible handler in terminal 1:

```bash
set -a
source ./.env
set +a
deno run --allow-env --allow-net supabase/functions/gateway/index.ts
```

In terminal 2 run:

```bash
curl -fsS \
  "http://127.0.0.1:8000/gateway/api/snapshot?run_id=$DANA_RUN_ID" \
  | jq -e '.run.run_id == env.DANA_RUN_ID'

curl -isS -X OPTIONS \
  "http://127.0.0.1:8000/gateway/api/commands" \
  -H 'Origin: http://localhost:4173' \
  -H 'Access-Control-Request-Method: POST' \
  | rg -i "HTTP/.* 204|access-control-allow-origin: \*|access-control-allow-methods: GET, POST, OPTIONS"
```

Expected: snapshot prints `true`; preflight shows HTTP 204 and the open CORS headers. Stop Deno after the checks. The hosted deployment later uses `supabase functions deploy --use-api`, which bundles the complete imported module graph without Docker.

- [ ] **Step 5: Commit the Edge adapter**

```bash
git add supabase/config.toml supabase/functions/gateway/index.ts
git commit -m "feat: add Supabase Edge Gateway adapter"
```

### Task 4: Preserve the Edge Function prefix in dashboard requests

**Files:**

- Modify: `app/app.js`

- [ ] **Step 1: Add one endpoint builder**

Add this function immediately after `normalizeUrl` in `app/app.js`:

```js
function gatewayApiUrl(path) {
  const cleanPath = String(path).replace(/^\/+/, "");
  return new URL(`${state.config.gatewayUrl}/${cleanPath}`);
}
```

- [ ] **Step 2: Use the builder for reads and writes**

In `fetchSnapshot`, replace the root-relative constructor with:

```js
const url = gatewayApiUrl("api/snapshot");
url.searchParams.set("run_id", state.config.runId);
```

In `sendCommand`, replace the root-relative constructor with:

```js
const url = gatewayApiUrl("api/commands");
```

Update the two comments in `readConfig` to:

```js
// The dashboard may run locally while the Gateway uses a stable public Edge URL.
// gateway_url is an explicit override; same-origin remains useful for other hosts.
```

- [ ] **Step 3: Verify the frontend script and exact URL construction**

Run:

```bash
node --check app/app.js
node -e 'const base="https://demo.supabase.co/functions/v1/gateway"; console.log(new URL(`${base}/api/snapshot`).pathname)'
```

Expected output:

```text
/functions/v1/gateway/api/snapshot
```

- [ ] **Step 4: Commit the dashboard compatibility change**

```bash
git add app/app.js
git commit -m "fix: preserve Edge Gateway path in dashboard"
```

### Task 5: Update the launch documentation without overwriting existing dirty work

**Files:**

- Modify: `.env.example`
- Modify: `README.md`
- Modify: `docs/contracts/gateway-api.md`
- Modify: `docs/demo-runbook.md`

The worktree already contains unrelated uncommitted edits in `.env.example`, `README.md` and `scripts/reset-demo.mjs`. Preserve them. Do not stage `scripts/reset-demo.mjs`; use interactive staging for the two overlapping documentation files.

- [ ] **Step 1: Document the Edge base URL in `.env.example`**

Replace only the Gateway block with:

```dotenv
# Stable public Supabase Edge Gateway. Hosted Edge Functions receive project keys automatically.
GATEWAY_URL=https://your-project-ref.supabase.co/functions/v1/gateway
```

Keep the existing `SUPABASE_ACCESS_TOKEN` and reset-demo changes intact.

- [ ] **Step 2: Replace the Azure launch instructions in `README.md`**

Make the prerequisite list require `deno`, `npx`, `curl`, `jq` and Python 3; remove Docker and Azure Functions Core Tools. Replace the local-Gateway step with this hosted flow:

````markdown
### Step 4 — Deploy the Supabase Edge Gateway

Load `.env`, derive the project reference, apply the compatibility migration and deploy:

```bash
set -a; source ./.env; set +a
VALTE_PROJECT_REF="${SUPABASE_URL#https://}"
VALTE_PROJECT_REF="${VALTE_PROJECT_REF%.supabase.co}"
export GATEWAY_URL="${SUPABASE_URL%/}/functions/v1/gateway"

psql "$DATABASE_URL" -v ON_ERROR_STOP=1 --single-transaction \
  --file supabase/migrations/202609190002_non_retryable_live_dispatch.sql

npx --yes supabase secrets set --project-ref "$VALTE_PROJECT_REF" \
  HAPPYROBOT_KEY="$HAPPYROBOT_KEY" \
  HAPPYROBOT_BASE_URL="$HAPPYROBOT_BASE_URL" \
  HAPPYROBOT_ENV="$HAPPYROBOT_ENV" \
  HAPPYROBOT_INTAKE_WORKFLOW_ID="$HAPPYROBOT_INTAKE_WORKFLOW_ID" \
  HAPPYROBOT_COMMAND_WORKFLOW_ID="$HAPPYROBOT_COMMAND_WORKFLOW_ID" \
  HAPPYROBOT_COORDINATION_WORKFLOW_ID="$HAPPYROBOT_COORDINATION_WORKFLOW_ID"

npx --yes supabase functions deploy gateway \
  --project-ref "$VALTE_PROJECT_REF" \
  --no-verify-jwt \
  --use-api
```

Verify the stable endpoint:

```bash
curl -fsS "$GATEWAY_URL/api/snapshot?run_id=$DANA_RUN_ID" \
  | jq -e '.run.run_id == env.DANA_RUN_ID'
```
````

Replace the dashboard URL example with this command, which constructs the exact encoded URL from the loaded environment:

```bash
node -e 'const g=process.env.GATEWAY_URL; console.log(`http://localhost:4173/?run_id=run-dana-demo&gateway_url=${encodeURIComponent(g)}`)'
```

- [ ] **Step 3: Amend the Gateway contract and demo runbook**

Add this deployment section to `docs/contracts/gateway-api.md`:

```markdown
## Supabase Edge deployment

The demo deploys one public Edge Function at
`$SUPABASE_URL/functions/v1/gateway`. Consumers keep the contract suffixes,
for example `$GATEWAY_URL/api/snapshot`. Platform JWT verification and custom
Gateway authentication are disabled for the demo. The privileged Supabase key
remains inside the Edge runtime.

A failed non-dry-run Coordination launch is finalized as `failed` and is not
claimed again automatically. Dry-run and upstream workflow launch failures keep
the existing bounded retry behavior.
```

In `docs/demo-runbook.md`, set `GATEWAY_URL` from `SUPABASE_URL`:

```bash
export GATEWAY_URL="${SUPABASE_URL%/}/functions/v1/gateway"
```

Add a preflight item confirming `GET $GATEWAY_URL/api/snapshot` returns the selected run before opening the dashboard.

- [ ] **Step 4: Check docs and stage only Gateway-related hunks**

Run:

```bash
git diff --check
rg -n "functions/v1/gateway|non-dry-run Coordination|Supabase Edge" \
  .env.example README.md docs/contracts/gateway-api.md docs/demo-runbook.md
git add -p .env.example README.md
git add docs/contracts/gateway-api.md docs/demo-runbook.md
git diff --cached --check
```

During `git add -p`, stage only hunks about the Edge Gateway. Reject the pre-existing `SUPABASE_ACCESS_TOKEN`, status-table and reset-demo hunks. Confirm `git diff --cached --name-only` does not list `scripts/reset-demo.mjs`.

- [ ] **Step 5: Commit the Gateway documentation**

```bash
git commit -m "docs: document Supabase Edge Gateway launch"
```

### Task 6: Deploy the Gateway and point HappyRobot development variables to it

**Files:**

- No repository files; this task changes the existing Supabase project and three HappyRobot development variables.

- [ ] **Step 1: Load credentials without printing them and derive the stable URL**

```bash
set -a
source ./.env
set +a
VALTE_PROJECT_REF="${SUPABASE_URL#https://}"
VALTE_PROJECT_REF="${VALTE_PROJECT_REF%.supabase.co}"
export GATEWAY_URL="${SUPABASE_URL%/}/functions/v1/gateway"
test -n "$SUPABASE_ACCESS_TOKEN"
test -n "$DATABASE_URL"
test -n "$HAPPYROBOT_KEY"
```

Expected: all commands exit `0` and print no credential values. Keep using this shell for the remaining deployment steps so the derived variables stay available.

- [ ] **Step 2: Apply the retry-policy migration**

```bash
psql "$DATABASE_URL" -v ON_ERROR_STOP=1 --single-transaction \
  --file supabase/migrations/202609190002_non_retryable_live_dispatch.sql

psql "$DATABASE_URL" -Atc \
  "select pg_get_function_identity_arguments('public.finish_outbox'::regproc);"
```

Expected: the identity arguments include `p_retryable boolean`.

- [ ] **Step 3: Upload only the HappyRobot server secrets required by the Edge Function**

```bash
npx --yes supabase secrets set --project-ref "$VALTE_PROJECT_REF" \
  HAPPYROBOT_KEY="$HAPPYROBOT_KEY" \
  HAPPYROBOT_BASE_URL="$HAPPYROBOT_BASE_URL" \
  HAPPYROBOT_ENV="$HAPPYROBOT_ENV" \
  HAPPYROBOT_INTAKE_WORKFLOW_ID="$HAPPYROBOT_INTAKE_WORKFLOW_ID" \
  HAPPYROBOT_COMMAND_WORKFLOW_ID="$HAPPYROBOT_COMMAND_WORKFLOW_ID" \
  HAPPYROBOT_COORDINATION_WORKFLOW_ID="$HAPPYROBOT_COORDINATION_WORKFLOW_ID"

npx --yes supabase secrets list --project-ref "$VALTE_PROJECT_REF" \
  | rg "HAPPYROBOT_(KEY|BASE_URL|ENV|INTAKE_WORKFLOW_ID|COMMAND_WORKFLOW_ID|COORDINATION_WORKFLOW_ID)"
```

Expected: the six names are present. Do not upload the root `.env` wholesale.

- [ ] **Step 4: Deploy and smoke-test the Edge Function**

```bash
npx --yes supabase functions deploy gateway \
  --project-ref "$VALTE_PROJECT_REF" \
  --no-verify-jwt \
  --use-api

curl -fsS "$GATEWAY_URL/api/snapshot?run_id=$DANA_RUN_ID" \
  | jq -e '.run.run_id == env.DANA_RUN_ID and (.run.state_version | type == "number")'

curl -fsS "$GATEWAY_URL/api/snapshot?run_id=$WILDFIRE_RUN_ID" \
  | jq -e '.run.run_id == env.WILDFIRE_RUN_ID and (.run.state_version | type == "number")'
```

Expected: both commands print `true`.

- [ ] **Step 5: Update `GATEWAY_URL` in all three HappyRobot development workflows**

Run this loop; it reads only IDs and writes only `value_development`:

```bash
for VALTE_WORKFLOW_ID in \
  "$HAPPYROBOT_INTAKE_WORKFLOW_ID" \
  "$HAPPYROBOT_COMMAND_WORKFLOW_ID" \
  "$HAPPYROBOT_COORDINATION_WORKFLOW_ID"
do
  VALTE_VARIABLE_ID="$(
    curl -fsS \
      -H "Authorization: Bearer $HAPPYROBOT_KEY" \
      "$HAPPYROBOT_BASE_URL/workflows/$VALTE_WORKFLOW_ID/variables?page_size=100" \
      | jq -er '.data[] | select(.key == "GATEWAY_URL") | .id'
  )"

  jq -n --arg value "$GATEWAY_URL" '{value_development: $value}' \
    | curl -fsS -X PATCH \
        -H "Authorization: Bearer $HAPPYROBOT_KEY" \
        -H 'Content-Type: application/json' \
        --data-binary @- \
        "$HAPPYROBOT_BASE_URL/workflows/$VALTE_WORKFLOW_ID/variables/$VALTE_VARIABLE_ID" \
    | jq -e '.key == "GATEWAY_URL" and .value_development == env.GATEWAY_URL'
done
```

Expected: `true` prints three times. Do not print or export any hidden contact variable.

### Task 7: Verify the deployed DANA and wildfire demo in dry-run

**Files:**

- Generated: the timestamped DANA/wildfire directory under `artifacts/e2e/` (gitignored except `.gitkeep`)

- [ ] **Step 1: Reload the demo environment and run all local static checks**

```bash
set -a; source ./.env; set +a
export GATEWAY_URL="${SUPABASE_URL%/}/functions/v1/gateway"
npm ci
npm run contracts:check
node --check api/_shared/supabase.mjs
node --check api/event-router/index.mjs
node --check app/app.js
deno check supabase/functions/gateway/index.ts
git diff --check
```

Expected: every command exits `0`; contracts show the three PASS lines.

- [ ] **Step 2: Reset only the two seeded demo runs**

```bash
node scripts/reset-demo.mjs
node scripts/reset-demo.mjs --apply
```

Expected: the preview names only `run-dana-demo` and `run-wildfire-demo`; apply prints one PASS for those exact runs.

- [ ] **Step 3: Verify the non-retryable live-failure RPC and roll the test back**

Run this transaction against the clean DANA run:

```bash
psql "$DATABASE_URL" -v ON_ERROR_STOP=1 <<'SQL'
begin;

select append_crisis_event(
  'run-dana-demo',
  0,
  'verification.live_dispatch',
  null,
  '{}'::jsonb,
  'crisis-response-coordination'
);

with claimed as (
  select *
  from claim_outbox(1, 'run-dana-demo')
  where destination = 'crisis-response-coordination'
)
select finish_outbox(
  outbox_id,
  dispatch_id,
  false,
  'simulated ambiguous launch',
  false
)
from claimed;

rollback;
SQL
```

Expected: the `finish_outbox` result contains `"status": "failed"`; the transaction ends with `ROLLBACK`, leaving the demo run clean.

- [ ] **Step 4: Verify the clean deployed preflight**

```bash
node scripts/e2e-demo.mjs \
  --gateway "$GATEWAY_URL" \
  --dana-run "$DANA_RUN_ID" \
  --wildfire-run "$WILDFIRE_RUN_ID" \
  --preflight-only
```

Expected: config, DANA and wildfire preflight all print PASS.

- [ ] **Step 5: Open the local dashboard against the stable Edge URL**

Start the dashboard:

```bash
python3 -m http.server 4173 --directory app
```

Build and open the exact browser URL without hand-editing:

```bash
node -e 'const g=process.env.GATEWAY_URL; console.log(`http://localhost:4173/?run_id=run-dana-demo&gateway_url=${encodeURIComponent(g)}`)'
```

Expected: the page shows `SIMULACIÓN`, `run-dana-demo` and a connected Gateway. Do not mutate the clean run from the dashboard; the full E2E runner verifies the POST route in the next step.

- [ ] **Step 6: Run the connected suite with no external effects**

```bash
node scripts/e2e-demo.mjs \
  --gateway "$GATEWAY_URL" \
  --dana-run "$DANA_RUN_ID" \
  --wildfire-run "$WILDFIRE_RUN_ID" \
  --effects dry-run
```

Expected final summary:

```text
PASS DANA: Signal → Intake → Command → approval → Coordination → Outcome → replan
PASS DANA abort: operator abort_run → run.status=aborted
PASS wildfire: same contracts and workflows
PASS wildfire abort: operator abort_run → run.status=aborted
PASS isolation: no DANA IDs or terms in wildfire
```

- [ ] **Step 7: Record the handoff**

Report:

- the stable `GATEWAY_URL` without credentials;
- the deployed function name `gateway`;
- the E2E artifact directory and summary;
- that the suite intentionally ended both runs as `aborted`;
- that external effects remain `dry-run` until the separate HappyRobot Email-node workstream is installed and verified.

Do not run `--effects email` in this plan.
