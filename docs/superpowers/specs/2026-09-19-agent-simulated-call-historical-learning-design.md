# Agent-Simulated Call and Historical Learning Design

**Date:** 2026-09-19

**Status:** Approved design, pending implementation plan

## 1. Goal

Extend the crisis demo with two small capabilities:

1. replace the live Web Voice/PSTN interaction used by the demo with a reproducible conversation
   performed by a recipient-simulator agent; and
2. derive at most one internal Lesson from each terminal run and apply that Lesson automatically to
   later runs of the same Scenario Pack.

The feature must remain easy to demonstrate: the dashboard shows the simulated conversation as part
of the Outcome, while historical learning stays internal to the Gateway, database, workflows and E2E
evidence.

## 2. Scope

### 2.1 In scope

- A new interaction mode named `agent_simulation`.
- A `crisis-recipient-simulator` HappyRobot workflow.
- A deterministic, pack-defined recipient state that constrains the simulator's response.
- A short sanitized transcript stored inside the resulting Outcome.
- A `crisis-review` HappyRobot workflow invoked after a run becomes terminal.
- At most one automatically active Lesson per source run.
- Pack-scoped Lesson retrieval by future runs.
- Internal recording of which Lesson IDs influenced a Plan.
- One connected happy-path E2E containing two sequential runs.

### 2.2 Out of scope

- PSTN calls, Web Voice sessions, email delivery or any other external communication.
- Presenting an agent-to-agent conversation as a real phone call.
- A learning panel, Lesson approval controls or Lesson editing in the dashboard.
- Model training, fine-tuning, vector search or autonomous prompt rewriting.
- Confidence scores, ranking, Lesson retirement and cross-pack Lesson sharing.
- A new negative-test matrix for timeouts, malformed callbacks or injected failures.
- Changes to the existing human-approval and resource-safety rules.

## 3. Existing system fit

The current system already provides the reusable backbone:

```text
approved Action
  -> Event Router
  -> crisis-response-coordination
  -> Outcome
  -> crisis-command
  -> replacement Plan
```

The new simulator replaces only the external-effect portion of Coordination. It does not bypass the
Action approval, the fresh-snapshot revalidation, callback correlation, idempotent `record_outcome`
command or Outcome-driven replan.

Historical learning is additive. When no Lessons exist, Command behaves exactly as it does today.

## 4. Approaches considered

### 4.1 Recipient simulation

1. **Hybrid deterministic simulator — selected.** A public Scenario Pack profile determines the
   recipient's operational constraints, while the agent generates the natural-language exchange and
   structured explanation. This is reproducible and still visibly agentic.
2. Fully autonomous simulator. The model freely chooses whether to accept or reject. This is more
   variable, but makes the connected E2E unreliable and can create decisions unsupported by the pack.
3. Static fixture only. This is maximally reliable but does not demonstrate an agent performing the
   recipient role.

### 4.2 Historical learning

1. **One automatically active Lesson per run — selected.** Minimal storage and no user interface.
2. Proposed Lessons with human approval. Safer for production, but adds dashboard state and controls
   that are unnecessary for this simulation-only demo.
3. Model fine-tuning or vector memory. Rejected because it is significantly more complex and would
   not improve the two-run demonstration.

## 5. Architecture

```text
RUN 1
Scenario Controller
  -> Intake
  -> Command creates contact_entity Action
  -> operator approves Action
  -> Coordination revalidates Action
  -> Recipient Simulator returns conversation result
  -> Coordination records Outcome with transcript
  -> Command replans from Outcome
  -> run becomes terminal
  -> Review Agent creates zero or one active Lesson

RUN 2, same pack
Snapshot includes prior active Lessons
  -> Command uses applicable Lesson
  -> Gateway records Plan <-> Lesson application
  -> Plan differs in a way explained by the Lesson

RUN, different pack
Snapshot excludes the Lesson
```

The two new workflows have narrow responsibilities:

- `crisis-recipient-simulator` represents the contacted entity for one approved Action. It cannot
  write to the Gateway.
- `crisis-review` analyzes one terminal run and can submit zero or one Lesson. It cannot create or
  replace a Plan.

## 6. Recipient simulator

### 6.1 Input

The simulator receives only:

- `dispatch_id`, `attempt_id`, `run_id` and `action_id`;
- the Action mission and requested response;
- a logical recipient identity;
- a public simulator profile from the Scenario Pack; and
- the current observable constraints needed to answer the mission.

It must not receive `hidden-truth.json`, private evaluator data, a phone number, an email address or
the desired answer.

Each pack gains a public recipient-simulation document. A profile identifies the target entity and
declares observable availability, constraints and response policy. The policy constrains the business
decision; the agent supplies natural language, not an unconstrained result.

### 6.2 Output

The simulator returns one schema-validated object:

```json
{
  "dispatch_id": "dispatch-123",
  "attempt_id": "dispatch-123:agent_simulation:1",
  "run_id": "run-dana-001",
  "action_id": "action-contact-01",
  "status": "success",
  "decision": "rejected",
  "summary": "The recipient cannot supply the requested ambulances.",
  "transcript": [
    {
      "speaker": "coordinator",
      "text": "SIMULACIÓN — ¿Puede aceptar la misión?"
    },
    {
      "speaker": "recipient",
      "text": "No, las ambulancias disponibles ya están asignadas."
    }
  ]
}
```

`status` uses the existing Outcome statuses. A completed conversation can have
`status=success` and `decision=rejected`: transport success and business acceptance are separate
facts. `decision` is one of `accepted`, `rejected`, `acknowledged` or `no_response`.

The transcript is short, sanitized and bounded. It is stored under
`Outcome.observed_effects.simulated_transcript`, together with
`interaction_mode=agent_simulation` and the structured decision. The dashboard already renders
Outcome observed effects, so the design does not add a new dashboard panel.

### 6.3 Coordination

The Event Router accepts `agent_simulation` and passes it only to Coordination. Coordination keeps
the existing fresh-snapshot and Action checks, creates
`<dispatch_id>:agent_simulation:1`, invokes the simulator once, normalizes its response into the
existing callback shape and persists one idempotent Outcome.

The existing `dry-run` mode remains available for infrastructure smoke checks. PSTN, Web Voice and
email are not selected by this feature.

## 7. Historical learning

### 7.1 Lesson model

A Lesson is an internal, pack-scoped instruction supported by records from one terminal run:

```text
lesson_id
pack_id
source_run_id
instruction
evidence_action_id
evidence_outcome_id
created_at
```

`source_run_id` is unique, enforcing at most one Lesson per run. A Lesson is active immediately after
the Gateway validates and stores it. There are no proposed, approved, rejected or retired states.

### 7.2 Creation

When a run becomes `completed` or `aborted`, its terminal event creates one outbox dispatch for
`crisis-review`. The review workflow receives the terminal run snapshot and returns either:

- `no_lesson`, when the run contains no supported reusable finding; or
- one Lesson instruction with an Action and Outcome from that run as evidence.

The Gateway accepts the Lesson only when:

- the source run is terminal;
- the referenced Action and Outcome exist in that run;
- the Outcome belongs to the referenced Action;
- the Lesson `pack_id` matches the source run; and
- no Lesson already exists for `source_run_id`.

The review agent cannot write a Lesson directly to Supabase. It submits through a dedicated Gateway
learning command so validation, idempotency and audit records remain centralized.

### 7.3 Application

`get_run_snapshot` includes active Lessons matching the current run's `pack_id`, excluding any Lesson
whose `source_run_id` equals the current run. Command receives this array in its validated context.

Lessons are advisory and cannot override current evidence, resource availability, required human
approval or any other hard prompt boundary. Command returns the IDs of Lessons it actually used as
command metadata outside the v2 Plan document. The Gateway validates those IDs and stores Plan-to-
Lesson application links without changing the existing Plan contract.

This makes historical learning observable in database state and E2E artifacts without exposing it in
the dashboard.

## 8. Data ownership and privacy

- The Scenario Pack owns public simulator profiles.
- The simulator owns only conversation generation; it owns no persistence.
- Coordination owns callback normalization and Outcome submission.
- The Review workflow owns Lesson proposals; it owns no persistence.
- The Gateway owns Outcome and Lesson validation, idempotency and storage.
- Command may consume active Lessons but cannot create them.

No real contact value is needed. No raw audio exists. Transcripts contain logical entity names only
and are treated as simulation data.

## 9. Minimal failure behavior

No new feature-specific recovery system is introduced. Existing run, Action, pack-identity and
idempotency guards remain in force.

- An invalid simulator result becomes a single `unknown` Outcome.
- An invalid Lesson is not stored.
- Failure to create a Lesson never blocks or changes the completed crisis run.
- Absence of Lessons leaves Command behavior unchanged.

There are no automatic retries in the selected design.

## 10. Minimal verification

The implementation adds only one feature-level connected E2E path:

1. run a DANA scenario;
2. approve one active `contact_entity` Action;
3. obtain one `agent_simulation` Outcome with a transcript;
4. observe an Outcome-driven replacement Plan;
5. close the run and persist one Lesson;
6. start a new DANA run;
7. verify that Command receives and applies the Lesson;
8. verify that the second Plan records the applied Lesson and changes accordingly; and
9. verify that a wildfire run does not receive the DANA Lesson.

Existing contract validation and launcher checks continue to run. The scope explicitly excludes a
new negative-test matrix.

## 11. Delivery truth

The demo may claim:

- a multi-agent simulated conversation;
- an idempotently persisted Outcome;
- Outcome-driven replanning inside a run; and
- evidence-based historical learning between two runs.

It must not claim that `agent_simulation` contacted a real person or placed a real phone call. The
real system interactions are the operator's Action approval and the audited Gateway/Supabase state
changes.

## 12. Implementation order

The work is split into two independently testable subprojects:

1. recipient simulator and `agent_simulation` Outcome path; then
2. internal Lesson creation and application across runs.

The implementation plan must keep this order so historical learning is built on the stable Outcome
produced by the simulator.
