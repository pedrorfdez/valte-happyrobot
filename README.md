# Valte Crisis Orchestrator

Team Valte's entry for the HappyRobot track at HackSpain 2026. The system turns noisy crisis reports into a traceable operational chain:

```text
Signal → Incident → Plan → Action → Outcome
```

It is scenario-neutral: the same contracts and HappyRobot workflows run a DANA/flood demo and a wildfire demo. All external communication is a **SIMULACIÓN** and the default interaction mode contacts nobody.

- [Track brief](docs/track.md)
- [Proposal](PROPOSAL.md)
- [HappyRobot API notes](docs/happyrobot-api.md)
- [Architecture design](docs/superpowers/specs/2026-09-19-generalist-crisis-agent-workflows-design.md)
- [Parallel delivery plan](docs/superpowers/plans/2026-09-19-crisis-parallel-orchestration.md)

## 1. What works now

| Capability | Status |
| --- | --- |
| Generic v2 contracts | Available now |
| DANA and wildfire contract examples | Available now |
| Contract validator | Available now |
| Supabase State Gateway | Connected DANA and wildfire E2E passed against Supabase; local demo needs no Azure deployment |
| Scenario Controller and packs | Implemented; DANA and wildfire dry-runs available |
| Three HappyRobot workflows | Published in HappyRobot `development`; connected E2E passed |
| Local dashboard | Implemented and verified against the Supabase Edge Gateway |
| Controlled interaction and E2E runner | Connected E2E passed in `dry-run`; live external channels intentionally not exercised |

## 2. Quick contract check

Prerequisite: Node.js 24 and npm.

```bash
npm ci
npm run contracts:check
```

Expected output:

```text
PASS dana-demo: Signal → Incident → Plan → Action → Outcome
PASS wildfire-demo: Signal → Incident → Plan → Action → Outcome
PASS real-interaction: callback → Outcome v2 → record_outcome
```

The original prototypes remain in `schemas/v1/`. New work uses `schemas/v2/`.

## 3. Full local demo

> The connected local demo has passed end to end with Supabase and the three published HappyRobot `development` workflows. It uses the deployed Supabase Edge Gateway and a local static dashboard; Azure Functions Core Tools and an Azure deployment are not required. External communication remains in `dry-run`.

### Step 1 — Check prerequisites

Use macOS/Linux with `zsh` or `bash`.

```bash
node --version
npm --version
deno --version
npx --version
psql --version
curl --version
jq --version
python3 --version
```

You also need:

- a Supabase project;
- access to the HappyRobot EU workspace;
- Python 3 for the zero-build static dashboard.

Continue only when every command above succeeds.

### Step 2 — Configure local variables

```bash
cp .env.example .env
```

Fill `.env` without committing it:

```dotenv
SUPABASE_URL=https://your-project-ref.supabase.co
SUPABASE_ANON_KEY=your_public_anon_key
SUPABASE_SERVICE_ROLE_KEY=your_server_only_service_role_key
SUPABASE_ACCESS_TOKEN=your_management_api_personal_access_token
DATABASE_URL=postgresql://your_connection_string

GATEWAY_URL=https://your-project-ref.supabase.co/functions/v1/gateway

HAPPYROBOT_KEY=your_api_key
HAPPYROBOT_BASE_URL=https://platform.eu.happyrobot.ai/api/v2
HAPPYROBOT_ENV=development
HAPPYROBOT_INTAKE_WORKFLOW_ID=your_intake_workflow_id
HAPPYROBOT_COMMAND_WORKFLOW_ID=your_command_workflow_id
HAPPYROBOT_COORDINATION_WORKFLOW_ID=your_coordination_workflow_id

DANA_RUN_ID=run-dana-demo
WILDFIRE_RUN_ID=run-wildfire-demo
DEMO_INTERACTION_MODE=dry-run
DEMO_ALLOWED_CONTACT_IDS=demo-field-lead
DEMO_CONTACT_ID=demo-field-lead
DEMO_CONTACT_NAME=demo-field-lead
```

Load the variables into each terminal that needs them:

```bash
set -a
source ./.env
set +a
```

`SUPABASE_ANON_KEY` is public and used only for dashboard notifications. `SUPABASE_SERVICE_ROLE_KEY`, `SUPABASE_ACCESS_TOKEN`, `DATABASE_URL`, `HAPPYROBOT_KEY`, and real recipient details must remain outside browser code and Git. The access token is used only by the demo reset script.
Configure `DEMO_CONTACT_EMAIL` and `DEMO_CONTACT_PHONE` only as hidden HappyRobot development variables; do not place real contact values in the repository.

### Step 3 — Prepare Supabase

From the repository root:

```bash
psql "$DATABASE_URL" -v ON_ERROR_STOP=1 --single-transaction \
  --file supabase/migrations/202609190001_crisis_core.sql
psql "$DATABASE_URL" -v ON_ERROR_STOP=1 \
  --file supabase/seed.sql
```

Verify the two clean demo runs:

```bash
psql "$DATABASE_URL" -Atc \
  "select run_id || '|' || pack_id || '|' || state_version from scenario_runs order by run_id;"
```

Expected:

```text
run-dana-demo|dana-demo|0
run-wildfire-demo|wildfire-demo|0
```

Continue only when both runs exist at version `0`.

Detailed plan: [Supabase and Gateway](docs/superpowers/plans/2026-09-19-supabase-gateway.md).

### Step 4 — Deploy the Supabase Edge Gateway

Load `.env`, derive the project reference, apply the compatibility migration, upload only the six HappyRobot secrets, and deploy:

```bash
set -a; source ./.env; set +a
: "${SUPABASE_URL:?SUPABASE_URL is required}"
VALTE_SUPABASE_ORIGIN="${SUPABASE_URL%/}"
VALTE_PROJECT_REF="${VALTE_SUPABASE_ORIGIN#https://}"
VALTE_PROJECT_REF="${VALTE_PROJECT_REF%.supabase.co}"
export GATEWAY_URL="${VALTE_SUPABASE_ORIGIN}/functions/v1/gateway"

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

Verify:

```bash
curl -fsS "$GATEWAY_URL/api/snapshot?run_id=$DANA_RUN_ID" \
  | jq -e '.run.run_id == env.DANA_RUN_ID'
```

Continue when `jq` prints `true`. The Gateway remains stable and publicly reachable in Supabase while the dashboard runs locally.

### Step 5 — Configure HappyRobot

The connected demo already has these three workflows published in HappyRobot `development`. Repeat the setup below only for a fresh workspace or after changing workflow definitions:

1. `crisis-intake`
2. `crisis-command`
3. `crisis-response-coordination`

For each workflow:

1. create or fork the named development version;
2. copy its prompt and JSON input/output contracts from `happyrobot/<workflow>/`;
3. set `GATEWAY_URL` as a workflow environment variable;
4. run the two isolated fixtures;
5. run native `test-all`;
6. publish only to `development`;
7. put its workflow ID in `.env` and reload the shell.

Do not configure direct Supabase writes. Workflows read snapshots and submit commands only through the Gateway.

The files under `happyrobot/` and `happyrobot/integrations/` are sanitized declarative blueprints, not proof of publication. Install the interaction extension into `crisis-response-coordination`, exercise its failure branches, run native `test-all`, and export the resulting development version before the connected E2E.

Detailed plan: [HappyRobot workflows](docs/superpowers/plans/2026-09-19-happyrobot-workflows.md).

### Step 6 — Verify both Scenario Packs without network

```bash
node scripts/scenario-controller.mjs \
  --pack scenario-packs/dana-demo \
  --run-id "$DANA_RUN_ID" \
  --state-version 0 \
  --operation-id readme-dana \
  --dry-run > /tmp/valte-dana.jsonl

node scripts/scenario-controller.mjs \
  --pack scenario-packs/wildfire-demo \
  --run-id "$WILDFIRE_RUN_ID" \
  --state-version 0 \
  --operation-id readme-wildfire \
  --dry-run > /tmp/valte-wildfire.jsonl

wc -l /tmp/valte-dana.jsonl /tmp/valte-wildfire.jsonl
```

Expected: `9` commands for each pack. The wildfire stream must not contain DANA-only IDs or vocabulary.

Detailed plan: [Scenario Controller](docs/superpowers/plans/2026-09-19-scenario-controller.md).

### Step 7 — Start the dashboard

From the repository root:

```bash
make up
```

The command loads `.env`, verifies the selected run through the Supabase Edge Gateway, preserves the `/functions/v1/gateway` base path, starts the dashboard on port `4173`, and opens the correctly configured URL. It stays attached to the terminal; press `Ctrl-C` to stop it.

To show the wildfire run or select another port:

```bash
make up RUN_ID="$WILDFIRE_RUN_ID"
make up PORT=4174
```

The local Python server exposes the dashboard at the root URL. To enable Realtime notifications, append URL-encoded `supabase_url` and `supabase_anon_key` query parameters. Without them, polling remains active and the UI reports `degraded` rather than failing.

Continue when the page shows `SIMULACIÓN`, the DANA run, and Gateway status.

### Step 8 — Run the complete DANA → wildfire preflight

Both seeded runs must still be clean.

```bash
node scripts/e2e-demo.mjs \
  --gateway "$GATEWAY_URL" \
  --dana-run "$DANA_RUN_ID" \
  --wildfire-run "$WILDFIRE_RUN_ID" \
  --preflight-only
```

Expected:

```text
PASS config: DANA and wildfire use distinct runs and packs
PASS preflight: DANA run-dana-demo ready
PASS preflight: Incendio forestal run-wildfire-demo ready
```

### Step 9 — Run the complete demo safely

```bash
node scripts/e2e-demo.mjs \
  --gateway "$GATEWAY_URL" \
  --dana-run "$DANA_RUN_ID" \
  --wildfire-run "$WILDFIRE_RUN_ID" \
  --effects dry-run
```

The runner executes one common pipeline twice:

```text
Scenario Controller → Intake → Command → human approval
→ Coordination → Outcome → replan → abort run
```

Expected final summary:

```text
PASS DANA: Signal → Intake → Command → approval → Coordination → Outcome → replan
PASS DANA abort: operator abort_run → run.status=aborted
PASS wildfire: same contracts and workflows
PASS wildfire abort: operator abort_run → run.status=aborted
PASS isolation: no DANA IDs or terms in wildfire
```

Artifacts are written under `artifacts/e2e/` without secrets. See the [E2E plan](docs/superpowers/plans/2026-09-19-crisis-e2e-demo.md) and [demo runbook](docs/demo-runbook.md).

## 4. Controlled real interaction

Stay in dry-run unless the recipient is present, has consented, and is allowlisted.

```bash
export DEMO_INTERACTION_MODE=dry-run
```

The runner sends its exact `--effects` mode through the Router to Coordination and rejects an Outcome that reports another mode. `dry-run` is the default. A live rehearsal must choose exactly `web_voice`, `email`, or `pstn`, add `--confirm-live-contact SIMULACION`, and use an allowlisted recipient alias in HappyRobot `development`.

Before changing it to `web_voice` or `email`:

1. complete `docs/demo-contacts.md`;
2. verify the Action is still `approved` in the latest snapshot;
3. confirm the message starts with `SIMULACIÓN —`;
4. use only the hidden recipient configured in HappyRobot `development`;
5. never retry automatically when the external result is `unknown`.

Detailed plan: [controlled interaction](docs/superpowers/plans/2026-09-19-real-interaction.md).

## 5. Deployment boundary

Azure is not used by this demo. The Gateway is the deployed Supabase Edge Function, and the dashboard remains local for development and rehearsal. CI/CD and infrastructure-as-code are intentionally outside this demo increment.

## 6. Stop and reset

Stop the local dashboard with `Ctrl-C` in its terminal. The Supabase Edge Gateway remains deployed.

To preview the reset scope, load `.env` and run:

```bash
node scripts/reset-demo.mjs
```

It verifies the reviewed seed's SHA-256 digest and validates that `supabase/seed.sql` only targets `run-dana-demo` and `run-wildfire-demo`. To apply that reset through the Supabase Management API:

```bash
set -a; source ./.env; set +a
node scripts/reset-demo.mjs --apply
```

The apply command requires `SUPABASE_ACCESS_TOKEN` with database write permission. Never broaden the seed's deletion targets beyond those two demo runs.

## 7. Troubleshooting

| Symptom | Action |
| --- | --- |
| `npm run contracts:check` fails | Run `npm ci`, then inspect the first schema/fixture error. |
| `SUPABASE_*` or `HAPPYROBOT_* is required` | Reload `.env` with `set -a; source ./.env; set +a`. |
| Snapshot returns `run_not_found` | Run `node scripts/reset-demo.mjs --apply` and use the two fixed run IDs. |
| E2E says the run is not clean | Run the reset script; the runner intentionally never deletes data automatically. |
| Direct `psql` reset hangs | Use `node scripts/reset-demo.mjs --apply` with the Management API token loaded from `.env`. |
| Gateway returns `version_conflict` | Refresh the snapshot and retry the human decision with a new command ID. |
| Router reports workflow not found | Verify the three workflow IDs and `HAPPYROBOT_ENV=development`. |
| Dashboard says `degraded` | Realtime is unavailable; confirm snapshots still refresh by polling. |
| External result is `unknown` | Stop the retry chain and reconcile it manually. |

## 8. Implementation plans

- [Coordinator and integration gates](docs/superpowers/plans/2026-09-19-crisis-parallel-orchestration.md)
- [Supabase and State Gateway](docs/superpowers/plans/2026-09-19-supabase-gateway.md)
- [Scenario Controller](docs/superpowers/plans/2026-09-19-scenario-controller.md)
- [HappyRobot workflows](docs/superpowers/plans/2026-09-19-happyrobot-workflows.md)
- [Azure Static Web Apps dashboard](docs/superpowers/plans/2026-09-19-swa-dashboard.md)
- [Controlled real interaction](docs/superpowers/plans/2026-09-19-real-interaction.md)
- [Sequential E2E and demo runbook](docs/superpowers/plans/2026-09-19-crisis-e2e-demo.md)

## Working agreements

- Hackathon mode: prefer working code over polish. Cut scope, not the demo.
- Keep decisions in `docs/decisions.md` when that log is introduced.
- Do not push implementation branches without team review.
