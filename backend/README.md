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

Required for `/crisis/voice-token`:

- `HAPPYROBOT_API_KEY`
- `CRISIS_WORKFLOW_ID`

Required for `/crisis/manuals`:

- `EXA_API_KEY` (https://dashboard.exa.ai)

Optional:

- `TICKET_WORKFLOW_ID` (the ticket workflow trigger stays a logged no-op
  until it and the API key are set)
- `CORS_ORIGINS` (defaults to the Vite dev server)

## Supabase setup

Run `sql/001_tickets.sql` and `sql/002_crises.sql` in the Supabase SQL
editor once each.

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

- `POST /crisis/voice-token` — start a crisis intake call. Mints a
  LiveKit token for the HappyRobot `crisis-start` voice agent so the
  dashboard can talk to it from the browser; the API key never leaves
  the backend. See `workflows/crisis-start.md`.

  ```bash
  curl -X POST http://localhost:8000/crisis/voice-token \
    -H 'Content-Type: application/json' \
    -d '{"data": {"source": "dashboard"}}'
  # => {"url": "wss://livekit.platform.eu.happyrobot.ai", "token": "...",
  #     "room_name": "...", "run_id": "..."}
  ```

- `POST /crisis` — declare a crisis. Saves it to Supabase (`crises`),
  then searches the web (Exa) for the official management protocols that
  cover it and saves those too (`crisis_manuals`). `transcript` is free
  text — the intake transcript works as-is; the structured fields are
  optional until the intake agent extracts them.

  A failed manual search does not lose the crisis: the row is already
  committed and the reason comes back in `manuals_error`.

  ```bash
  curl -X POST http://localhost:8000/crisis \
    -H 'Content-Type: application/json' \
    -d '{
      "transcript": "Mando: incendio forestal, viento fuerte, evacuar un camping",
      "run_id": "<happyrobot run id>",
      "crisis_type": "incendio forestal",
      "location": "Sierra de Madrid"
    }'
  # => {"id": "...", "manuals": [{"title": "...", "url": "..."}], "manuals_error": null}
  ```
