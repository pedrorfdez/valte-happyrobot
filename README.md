# Valte - Crisis Command

Team Valte's entry for the HappyRobot track at HackSpain 2026.

Valte is an agentic crisis management system. It recreates the DANA
flood of 2024-10-29 in Valencia and shows what an AI coordinator could
have done that day: read thousands of noisy signals, alert every town
before the wave, dispatch finite rescue crews, and keep a human in
control. In 2024 the mass alert went out at 20:11, after the wave. Our
system sends it hours earlier, and the dashboard shows the difference
live.

## Where to find it

- Dashboard (live system): `https://kernel-production-c1a9.up.railway.app/dashboard?key=<WORLD_API_TOKEN>`.
  The token is `WORLD_API_TOKEN` in the team `.env`.
- The kernel API runs at the same host. Health check: `/healthz`.
- The AI workflows run on the HappyRobot platform (EU):
  `ingest-calls`, `ingest-social`, `ingest-news`, `coordinator`.

## Run a demo

1. Open the dashboard URL in a browser.
2. Pick a speed. `x60` runs the full crisis in about 5 minutes.
3. Press `Start scenario`. The dashboard follows the new run.
4. When a yellow card asks for approval (the military request), press
   `Approve` or `Reject`. That is the human-in-the-loop moment.
5. The run ends at scenario time 20:30. Press `Restart scenario` to
   run it again.

What to watch: the alert time in the header against the real 20:11,
the wave moving down the basin map, crews deploying and returning in
the Zones table, the agent registering volunteer groups it discovers,
and the reflex rules it arms for itself.

## How it works

```
Simulator            Perception              Crisis kernel            Coordinator
(fake world)         (HappyRobot)            (FastAPI + Postgres)     (HappyRobot LLM)
tweets, 112 calls,   3 ingest workflows      validates, scores        reads the state,
sensor readings  ->  extract claims and  ->  confidence, enforces ->  decides actions,
per channel          location per signal     rules, fires reflexes    doctrine-guided
                                             in milliseconds          (the playbook)
```

- The simulator replays the historic timeline plus generated noise,
  rumor cascades, and per-zone incident clusters. Every payload takes
  the shape a real channel would deliver.
- Perception is one HappyRobot workflow per channel. It filters noise
  and produces normalized signals. Sensors skip perception and post
  directly, so the fast path never waits for an LLM.
- The kernel is the safety layer. It computes per-signal confidence
  from cross-channel corroboration, enforces capabilities,
  jurisdiction, and a transactional crew ledger, executes the standing
  reflex rules (tripwires) the agent arms, and gates high-cost actions
  behind human approval.
- The coordinator is the deliberating agent. The kernel wakes it with
  a digest of new events; it reads the full state and submits a batch
  of actions with evidence and reasoning. The playbook it follows is
  `scenarios/dana-valencia/playbook.md`.
- Every run is stored in Postgres with full traceability: raw
  payloads, signals, decisions, rejections, and the agent's assessment
  history.

## Repository layout

- `schemas/`: JSON Schemas, the team contract. Every field has a
  description written to feed agent prompts.
- `scenarios/dana-valencia/`: the scenario pack: world, entities,
  timeline, message pools, playbook. The core system is
  scenario-agnostic; a new crisis is a new folder.
- `backend/kernel/`: the crisis kernel (FastAPI).
- `backend/sim/`: the world simulator.
- `backend/dashboard/`: the single-file dashboard the kernel serves.
- `backend/scripts/`: migrations, scenario loader, run scorecard
  (`evaluate_run.py`), terminal watcher (`watch.py`).
- `docs/`: design decisions, backend plan, HappyRobot API recipes,
  phase plan.

## Run locally

```bash
set -a; . ./.env; set +a          # loads tokens and URLs
cd backend
uvicorn kernel.main:app --port 8100   # local kernel (uses Supabase)
python3 -m sim run --scenario dana-valencia --speed 60 --emit live
python3 scripts/watch.py              # terminal view
python3 -m pytest tests/ -q           # invariant test suite
```

`--emit live` sends channels to the URLs in `.env`. `--emit console`
prints payloads instead and touches nothing.

## Operating notes

- One simulation runs at a time. One demo equals one run; old runs
  stay in the database and the dashboard can replay any of them with
  `?run_id=<id>`.
- The seed fixes the noise pattern. Seed 42 is the rehearsed demo run.
- Deploys: `railway up --service kernel --ci` from the repo root. The
  scenario pack and dashboard ship inside the container image.
- HappyRobot workflow edits follow the fork, edit, force-publish
  recipe in `docs/happyrobot-api.md`.

## Documents

- `docs/track.md`: the challenge brief.
- `docs/schemas.md`: data model overview and design decisions.
- `docs/backend.md`: kernel and simulator architecture.
- `docs/happyrobot-api.md`: platform recipes learned by testing.
- `docs/decisions.md`: decision log with reasons.
- `scenarios/dana-valencia/playbook.md`: the response doctrine.
