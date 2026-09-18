# HappyRobot track brief

Source: https://hackspain2026.happyrobot.ai/ (fetched 2026-09-18).
Event: HackSpain 2026, September 18-20 2026, UPM ETSIT, Madrid.

## Challenge

Build an agentic system that manages a crisis scenario of our choice.
Examples: wildfire, blackout, flood, infrastructure failure, mass
casualty incident. The environment changes while the system operates.

## Mandatory requirements

1. Agentic system: it decides and acts autonomously. A chatbot that only
   answers questions does not qualify.
2. Dynamic scenario: the situation evolves while the system operates.
3. Multi-step response: chains of actions toward objectives, not
   isolated actions.
4. Real interaction: actual calls, messages, tickets, or API calls. Not
   proposals.
5. User interface: a dashboard that shows the situation status, the
   system's actions, and gives a human the ability to intervene.
6. Learning (bonus): the system reviews past interactions to improve
   future decisions.

## Six questions the system must answer repeatedly

1. What information matters: filter signal from noise in incoming
   messages.
2. What goes first: prioritize among simultaneous demands.
3. Who is notified and when: decide recipients, content, and timing.
4. Where do resources go: allocate limited assets across competing
   needs.
5. What is done now: name the concrete next action and who does it.
6. When to drop the plan: detect that conditions changed and the plan
   no longer works.

## Four required capabilities

- Gather information from multiple sources: calls, messages, sensors,
  APIs.
- Prioritize based on available resources.
- Coordinate the response across multiple channels.
- Adapt the plan in real time.

## Evaluation criteria (three equal blocks)

Decision-making:

- Sound decisions with incomplete data.
- Effective prioritization under urgency.
- Adaptation to changing circumstances.

Execution:

- Coordinated management of people, information, and resources.
- Real external actions, not proposals.

Supervision:

- Transparency and human intervention capability.
- Scenario originality and creative problem solving.
- Learning from previous executions (bonus).

## Deliverables

- A functional agentic system.
- A live demonstration. Presentation quality counts as much as system
  capability.
- Evidence of real interactions and integrations.

## Platform

HappyRobot provides its production platform. It handles voice, chat,
and email interactions. Docs at https://docs.happyrobot.ai/ require an
access code from the organizers. Organizers give platform access and
on-site support.

## Scenario examples from the organizers

- Forest fires with dynamic fire fronts.
- Regional blackouts with communication constraints.
- Armed conflicts with unconfirmed information.
- Floods and natural disasters.
- Critical infrastructure failures.
- Mass casualty or humanitarian emergencies.
