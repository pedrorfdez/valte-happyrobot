# HappyRobot API

How we connect to the HappyRobot platform.

## Connection

- Base URL: `https://platform.eu.happyrobot.ai/api/v2` (our org is in the
  EU region; the US host rejects our key).
- Auth: `Authorization: Bearer $HAPPYROBOT_KEY`.
- The key lives in `.env` under `HAPPYROBOT_KEY`. The `.env` file is
  gitignored. Do not commit it.

## Example

```bash
set -a && . ./.env && set +a
curl -s -H "Authorization: Bearer $HAPPYROBOT_KEY" \
  "https://platform.eu.happyrobot.ai/api/v2/workflows/"
```

## API reference

- OpenAPI spec (public, no auth): `https://platform.eu.happyrobot.ai/api/v2/docs/json`.
- 179 paths. Key resources: workflows, workflow versions, variables,
  publish/unpublish, runs, sessions, templates.

## Ingest workflows (perception layer)

Three API-created workflows receive the simulator channels. Each has a
webhook trigger and an AI Extract node that produces the normalized
signal fields (is_noise, claims, zone, precision, summary; social adds
secondhand).

| Channel | Workflow | Workflow id | Webhook (production) |
|---|---|---|---|
| calls | ingest-calls | 01a0b902-3f0d-79aa-b211-155c10a5536e | https://workflows.platform.eu.happyrobot.ai/hooks/xlb4e31c4bw5 |
| social | ingest-social | 01a0b902-430c-7cc4-95e9-28b1998ef4b1 | https://workflows.platform.eu.happyrobot.ai/hooks/04bq57ewbniy |
| news | ingest-news | 01a0b902-4666-7dad-85ba-4672af280a74 | https://workflows.platform.eu.happyrobot.ai/hooks/b8xaepgupozn |

These URLs go in `.env` (`HR_WEBHOOK_CALLS`, `HR_WEBHOOK_SOCIAL`,
`HR_WEBHOOK_NEWS`). The URLs are bound to the workflow slug and
survive republishing.

## How to edit workflows via the API

1. A published version is locked. Fork it:
   `POST /versions/{live_version_id}/fork` returns the new draft id.
2. Edit nodes on the fork: `POST|PUT|DELETE /versions/{id}/nodes[/{node_id}]`.
3. Publish the fork: `POST /versions/{id}/publish` with body
   `{"force": true}` (required when another version is live).

Node facts learned by testing:

- Webhook trigger: integration Webhook, event id
  `01929b66-a335-7514-a159-cae2fe715286` (Incoming hook). Pass
  `webhook_payload` with an example payload so downstream nodes can
  reference its fields.
- Batch LLM step: integration AI, event Extract, id
  `01926f30-36a3-7394-8f73-eeead5d7f948`. Configuration fields:
  `prompt` (string), `input` (template string), `json_schema`
  (stringified JSON Schema in OpenAI strict mode: additionalProperties
  false everywhere, all properties required).
- `prompt` node types are conversational agent modules. They do not
  execute on webhook-only runs. Use AI Extract for batch processing.
- Template variables: `{{<trigger_node_id>.<field>}}`. The available
  ids come from `GET /versions/{v}/nodes/{n}/available-vars`.
- Run traces: `GET /workflows/{id}/runs`, `GET /runs/{run_id}/nodes`,
  then `GET /runs/{run_id}/outputs/{output_id}` for full node output
  (extraction JSON, token counts, errors).

## Decision

We use the REST API with the API key instead of the HappyRobot MCP
servers. Reason: the key was available at once and the MCP OAuth flow
was not needed. Rejected: MCP servers (`mcp.platform.happyrobot.ai`),
which require OAuth.
