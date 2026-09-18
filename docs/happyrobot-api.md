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

## Decision

We use the REST API with the API key instead of the HappyRobot MCP
servers. Reason: the key was available at once and the MCP OAuth flow
was not needed. Rejected: MCP servers (`mcp.platform.happyrobot.ai`),
which require OAuth.
