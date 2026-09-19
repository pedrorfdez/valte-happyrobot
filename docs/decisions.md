# Decisions

## 2026-09-18: Scenario-agnostic core, scenario as data pack

Decided: the core system (schemas, agent workflows, dashboard) knows
nothing about a concrete crisis type. A scenario is a data pack: world
definition, event timeline, hazard dynamics, and response playbooks.
Reason: the six judged questions are scenario-independent, and loading a
second scenario into an unchanged system is strong proof of real agentic
reasoning. Rejected: hardcoding one scenario (faster start, but weaker
originality score and brittle design).

## 2026-09-18: First scenario is the Valencia DANA flood

Decided: scenario pack #1 recreates the DANA flood of 2024-10-29 in
Valencia (Rambla del Poyo overflow; Paiporta, Catarroja, Alfafar,
Torrent; 224 deaths; ES-Alert sent at 20:11, too late). The demo shows
our system sending the alert hours earlier. Reason: the real event was
an information and coordination failure, which is exactly what the
system solves; strong emotional and local relevance for a Spanish jury.
Rejected: wildfire as first scenario (kept as stretch-goal pack #2).

## 2026-09-18: HappyRobot access via REST API

Decided: use the REST API at `https://platform.eu.happyrobot.ai/api/v2`
with the bearer key in `.env`. Rejected: HappyRobot MCP servers (OAuth
flow not needed once the key existed). See `docs/happyrobot-api.md`.
