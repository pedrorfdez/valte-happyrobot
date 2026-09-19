# Valte - HackSpain 2026

Team Valte's entry for the HappyRobot track at HackSpain 2026 (September
18-20 2026, UPM ETSIT, Madrid).

- Track page: https://hackspain2026.happyrobot.ai/
- Full track brief: [docs/track.md](docs/track.md)
- Our proposal: [PROPOSAL.md](PROPOSAL.md)

## The challenge in one line

Build an agentic system that manages an evolving crisis (fire, blackout,
flood, ...). The system must decide, act on the real world, and adapt as
the situation changes.

## Hard requirements (from the track)

All of these are mandatory:

1. Agentic: the system decides and acts on its own. A chatbot that only
   answers questions does not qualify.
2. Dynamic scenario: the situation evolves while the system runs.
3. Multi-step: chains of actions toward objectives, not isolated actions.
4. Real interaction: actual calls, messages, tickets, or API calls. Not
   proposals of actions.
5. UI: a dashboard that shows the situation, the system's actions, and
   lets a human intervene.
6. Bonus: learning from past executions.

## Evaluation (three equal blocks)

- Decision-making: good decisions with incomplete data, prioritization,
  adaptation to change.
- Execution: coordination of people, information, and resources; real
  external actions.
- Supervision: transparency, human intervention, scenario originality.
  Learning is a bonus.

The live demo counts as much as the system itself.

## Platform

We build on the HappyRobot platform (voice, chat, and email agent
workflows). Docs at https://docs.happyrobot.ai/ are behind an access
code; the organizers give access and on-site support during the event.

## Our proposal (draft, see PROPOSAL.md)

A crisis management system with:

- Entities: actors that can execute actions and have a weight (mayor,
  police, firefighters, civilians).
- Data sources: social networks, emergency calls, sensors, news media.
- HappyRobot workflows: one workflow per data source; incident and
  disaster playbooks; persistence to a database or knowledge store.
- Resources: human resources and basic supplies (medicine, food, water).
- States: for example "fire active in zone X".
- UI: dashboard for status, actions, and human intervention.
- Integrations: the real external actions.

## What runs today

```bash
cd backend && uv run uvicorn main:app --reload --port 8000   # API
cd frontend && npm install && npm run dev                    # http://localhost:5173
```

One screen: the big **CREAR CRISIS** button. It opens a browser voice
call against the HappyRobot `crisis-start` agent
([workflows/crisis-start.md](workflows/crisis-start.md)), which
interviews you about the crisis in Spanish and shows the transcript
live. On hang-up the crisis is saved to Supabase together with the official
management protocols the backend finds for it on the web (Exa).

## Working agreements

- Hackathon mode: prefer working code over polish. Cut scope, not the
  demo.
- Keep decisions in `docs/decisions.md`: what was decided, why, and what
  was rejected.
- Do not push without asking.
