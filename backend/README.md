# backend

FastAPI service. Endpoints grow one at a time.

## Run (dev)

```bash
cd backend
uv sync
uv run uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

Interactive docs at http://localhost:8000/docs.

## Config

Reads `../.env` (repo root) or a local `.env`. Required for `/tickets`:

- `SUPABASE_URL`
- `SUPABASE_SERVICE_ROLE_KEY`

Optional (workflow trigger stays a no-op until both are set):

- `HAPPYROBOT_API_KEY`
- `TICKET_WORKFLOW_ID`

## Supabase setup

Run `sql/001_tickets.sql` in the Supabase SQL editor once.

## Endpoints

- `GET /health` — liveness.
- `POST /tickets` — persist a user report/proposal aimed at an entity,
  then fire the ticket dispatcher workflow in the background.

  Ticket = a user assigned to an entity reports something to it. Two
  kinds: `report` ("this is happening") and `proposal` ("let's do
  this"). No priority — the workflow decides whether to escalate.

  ```bash
  curl -X POST http://localhost:8000/tickets \
    -H 'Content-Type: application/json' \
    -d '{
      "user_id": "usr_42",
      "entity_id": "firefighters-paiporta",
      "kind": "report",
      "subject": "Flooded garage on Mestre Serrano",
      "content": "Caller reports 2 people trapped in the basement.",
      "payload": {"call_id": "call_123"}
    }'
  ```
