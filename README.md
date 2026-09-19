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

This distinction matters: do not try to start files that have not been implemented yet.

| Capability | Status |
| --- | --- |
| Generic v2 contracts | Available now |
| DANA and wildfire contract examples | Available now |
| Contract validator | Available now |
| Supabase State Gateway | Planned; see implementation plan |
| Scenario Controller and packs | Planned; see implementation plan |
| Three HappyRobot workflows | Planned; requires platform configuration |
| Azure Static Web Apps dashboard | Planned |
| Controlled interaction and E2E runner | Planned |

## 2. Quick start available today

Prerequisite: Node.js 24 and npm.

```bash
npm ci
npm run contracts:check
```

Expected output:

```text
PASS dana-demo: Signal → Incident → Plan → Action → Outcome
PASS wildfire-demo: Signal → Incident → Plan → Action → Outcome
```

The original prototypes remain in `schemas/v1/`. New work uses `schemas/v2/`.

## 3. Full local demo

> The rest of this guide becomes runnable after the six workstreams in the parallel delivery plan are implemented. Until then, use the quick start above.

### Step 1 — Check prerequisites

Use macOS/Linux with `zsh` or `bash`.

```bash
node --version
npm --version
psql --version
func --version
curl --version
jq --version
```

You also need:

- a Supabase project;
- access to the HappyRobot EU workspace;
- Azure Functions Core Tools for the local Gateway;
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
DATABASE_URL=postgresql://your_connection_string

GATEWAY_URL=http://localhost:7071

HAPPYROBOT_KEY=your_api_key
HAPPYROBOT_BASE_URL=https://platform.eu.happyrobot.ai/api/v2
HAPPYROBOT_ENV=development
HAPPYROBOT_INTAKE_WORKFLOW_ID=your_intake_workflow_id
HAPPYROBOT_COMMAND_WORKFLOW_ID=your_command_workflow_id
HAPPYROBOT_COORDINATION_WORKFLOW_ID=your_coordination_workflow_id

DANA_RUN_ID=run-dana-demo
WILDFIRE_RUN_ID=run-wildfire-demo
DEMO_INTERACTION_MODE=dry-run
```

Load the variables into each terminal that needs them:

```bash
set -a
source ./.env
set +a
```

`SUPABASE_ANON_KEY` is public and used only for dashboard notifications. `SUPABASE_SERVICE_ROLE_KEY`, `DATABASE_URL`, `HAPPYROBOT_KEY`, and real recipient details must remain outside browser code and Git.

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

### Step 4 — Start the local Gateway

Open terminal 1, load `.env`, and start Azure Functions from the API root:

```bash
cd api
func start
```

Keep it running. In another terminal:

```bash
curl -fsS "$GATEWAY_URL/api/snapshot?run_id=$DANA_RUN_ID" \
  | jq -e '.run.run_id == "run-dana-demo" and .run.state_version == 0'
```

Continue when `jq` prints `true`.

### Step 5 — Configure HappyRobot

In the HappyRobot `development` environment, configure these three workflows from the versioned repository definitions:

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

Open terminal 2:

```bash
python3 -m http.server 4173 --directory app
```

Open:

```text
http://localhost:4173/ops?run_id=run-dana-demo&gateway_url=http://localhost:7071
```

To enable Realtime notifications, also provide the public Supabase URL and anon key as documented in the [dashboard plan](docs/superpowers/plans/2026-09-19-swa-dashboard.md). Without them, polling remains active and the UI reports `degraded` rather than failing.

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

Artifacts are written under `artifacts/e2e/` without secrets. See the [E2E plan](docs/superpowers/plans/2026-09-19-crisis-e2e-demo.md) and, once implemented, `docs/demo-runbook.md`.

## 4. Controlled real interaction

Stay in dry-run unless the recipient is present, has consented, and is allowlisted.

```bash
export DEMO_INTERACTION_MODE=dry-run
```

Before changing it to `web_voice` or `email`:

1. complete `docs/demo-contacts.md`;
2. verify the Action is still `approved` in the latest snapshot;
3. confirm the message starts with `SIMULACIÓN —`;
4. use only the hidden recipient configured in HappyRobot `development`;
5. never retry automatically when the external result is `unknown`.

Detailed plan: [controlled interaction](docs/superpowers/plans/2026-09-19-real-interaction.md).

## 5. Optional Azure deployment

Local execution is the recommended path for development and rehearsal. For the hosted demo:

- deploy `app/` as the Static Web App content;
- deploy `api/` as its managed Functions API;
- place `staticwebapp.config.json` in the deployed static artifact;
- configure server variables in Azure rather than in frontend files;
- keep the dashboard anon key public/read-only and the service-role key server-side;
- smoke-check `https://<your-host>/api/snapshot?run_id=run-dana-demo` after deployment.

CI/CD and infrastructure-as-code are intentionally outside this demo increment.

## 6. Stop and reset

Stop the local Gateway and dashboard with `Ctrl-C` in their terminals.

To reset only the two named demo runs:

```bash
psql "$DATABASE_URL" -v ON_ERROR_STOP=1 --file supabase/seed.sql
```

Never broaden the seed's deletion targets beyond `run-dana-demo` and `run-wildfire-demo`.

## 7. Troubleshooting

| Symptom | Action |
| --- | --- |
| `npm run contracts:check` fails | Run `npm ci`, then inspect the first schema/fixture error. |
| `SUPABASE_*` or `HAPPYROBOT_* is required` | Reload `.env` with `set -a; source ./.env; set +a`. |
| Snapshot returns `run_not_found` | Reapply `supabase/seed.sql` and use the two fixed run IDs. |
| E2E says the run is not clean | Reapply the seed; do not make the runner delete data automatically. |
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
