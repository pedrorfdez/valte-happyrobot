# Kuehne+Nagel milestone tracking example

## Purpose

Create one executable REST API example inspired by the public Kuehne+Nagel and
HappyRobot Healthcare HyperCare case. The script represents an upstream TMS: it
submits a pending milestone follow-up to HappyRobot, while the HappyRobot
workflow owns carrier contact, response interpretation, retries, and escalation.

The implementation is an original demonstration. No public source code for the
Kuehne+Nagel deployment was found.

## Scope

One script will support two execution modes:

1. `simulate`: sends a fictional carrier response so a development workflow can
   exercise its decision branches without placing a telephone call.
2. `live`: sends a pending follow-up with a carrier contact reference so a
   configured HappyRobot voice workflow can contact the carrier.

`simulate` is the default. Both modes remain subject to `DRY_RUN`, which defaults
to `true` and prevents every API request.

The script will not decide severity, schedule a retry, or escalate an incident.
Those actions belong to the HappyRobot workflow. The script only validates and
transmits facts plus the policy limits that the workflow must apply.

## Architecture and ownership

```text
TMS / example script
  -> pending milestone facts
  -> HappyRobot workflow
       -> simulation branch OR outbound voice call
       -> extract carrier response
       -> evaluate temperature, delay, and attempt policy
       -> record confirmation, schedule retry, or escalate
       -> persist outcome using event_id
  -> dashboard / run inspection
```

Responsibilities are separated as follows:

- The TMS owns shipment identity, planned milestones, carrier contact reference,
  and the initial contact-attempt count.
- HappyRobot owns communication, response extraction, severity classification,
  next action, and multilingual interaction.
- The incident store used by the workflow owns processed `event_id` values and
  the latest attempt state. The example defines this contract but does not
  implement the production database or scheduler.
- The dashboard reads run and incident state and allows a human operator to
  override or acknowledge an escalation.

## Interface

The script will accept the workflow ID as its first argument and use environment
variables for scenario data. Authentication and REST behavior come from
`examples/_lib/happyrobot.sh`.

Common inputs:

- `RUN_MODE`: `simulate` or `live`; defaults to `simulate`.
- `EVENT_ID`: idempotency and correlation identifier. It is mandatory in live
  mode and gets a deterministic demo value in simulation mode.
- `SHIPMENT_ID`: shipment correlation identifier.
- `CARRIER_NAME`: carrier being contacted.
- `CARRIER_CONTACT_ID`: server-side contact reference; mandatory in live mode.
- `MILESTONE`: operational checkpoint being confirmed.
- `EXPECTED_AT`: planned milestone time in ISO 8601 format.
- `TEMPERATURE_MIN_C` and `TEMPERATURE_MAX_C`: permitted range.
- `CONTACT_ATTEMPT`: current attempt, starting at one.
- `MAX_CONTACT_ATTEMPTS`: maximum attempts before escalation.
- `RETRY_DELAY_MINUTES`: delay before another attempt.
- `LANGUAGE`: preferred contact language: `en`, `es`, `de`, `fr`, or `zh`.
- `DRY_RUN`: defaults to `true`.

Simulation-only response inputs:

- `SIMULATED_CARRIER_STATUS`: `confirmed`, `delayed`, or `no_answer`.
- `SIMULATED_REPORTED_ETA`: optional reported ETA.
- `SIMULATED_TEMPERATURE_C`: optional reported cargo temperature.

Temperature and reported ETA are response data, not request facts. They are
therefore nullable. They must be absent for `no_answer` and are validated only
when supplied.

The payload will not contain a raw telephone number. Live mode uses a server-side
contact identifier so repositories, terminal history, and run payloads do not
expose personal contact data.

## Workflow decision policy

The script sends the policy inputs; the HappyRobot workflow applies these rules:

| Carrier outcome | Additional condition | Severity | Workflow action |
| --- | --- | --- | --- |
| `confirmed` | Temperature inside inclusive range | `normal` | Record confirmation |
| `confirmed` | Temperature below minimum or above maximum | `critical` | Escalate immediately |
| `delayed` | Any | `critical` | Escalate immediately |
| `no_answer` | Attempt below maximum | `warning` | Schedule another attempt |
| `no_answer` | Attempt reaches maximum | `critical` | Escalate to control tower |

The inclusive temperature range means values equal to the configured minimum or
maximum remain valid.

For `no_answer` below the limit, the workflow increments the attempt count and
sets `next_attempt_at` using `RETRY_DELAY_MINUTES`. The incident store is the
source of truth across runs; command-line values only seed or simulate that
state.

## API payload

The script will reuse `POST /workflows/{workflow_id}/runs` and send:

- the HappyRobot environment at the top level;
- `event_id`, shipment, carrier, and milestone facts;
- the carrier contact reference only in live mode;
- permitted temperature range and retry-policy limits;
- current attempt state and preferred language;
- a `simulation` object only in simulation mode;
- source and observation timestamp.

The script will not send computed severity, escalation flags, or recommended
actions. These are workflow outputs.

The workflow must check whether `event_id` has already been processed before it
places a call or emits an escalation. A duplicate becomes a no-op and returns the
existing incident reference. HappyRobot's REST endpoint does not advertise an
idempotency header, so deduplication belongs to workflow-backed persistence.

The payload contains operational shipment metadata only. It must not include
patient or other personal health information.

## Output and observability

In dry-run mode, the script prints the exact request payload. On a real API call,
it prints the HappyRobot response, including the run identifier when returned.

The run can then be inspected with `04-list-workflow-runs.sh`. The workflow is
responsible for exposing the final carrier outcome, severity, action, attempt
count, and incident reference to the dashboard or incident store.

Human intervention is explicit: an escalation remains open until an operator
acknowledges, overrides, or resolves it in the supervising application.

## Validation and error handling

The script will reject:

- unsupported run modes, simulated statuses, or languages;
- missing live contact references or live event IDs;
- malformed numeric temperatures and retry values;
- a minimum temperature greater than the maximum;
- an attempt count greater than the configured maximum;
- response fields supplied with `no_answer`.

The shared API helper surfaces non-successful HTTP responses. Automatic retries
for HTTP failures are excluded because retrying a workflow trigger without an
API-level idempotency guarantee could create duplicate external actions.

## Safety and side effects

`DRY_RUN=true` prints the payload and makes no API request. A workflow run
requires explicitly setting `DRY_RUN=false`.

The shared helper defaults to the HappyRobot `development` environment. Live
mode additionally requires an explicit carrier contact reference. API keys stay
server-side and are never printed.

## Verification

Validation will cover:

1. Shell syntax and static analysis.
2. Dry-run payloads for simulation and live modes.
3. `confirmed` with temperature inside the inclusive range.
4. `confirmed` with temperature outside the range.
5. `delayed` with optional ETA and temperature.
6. `no_answer` before and at the maximum attempt.
7. Invalid modes, status, language, temperature range, and attempt values.
8. Rejection of response data combined with `no_answer`.
9. Rejection of live mode without contact reference or event ID.

All behavioral checks will run in dry-run mode or exit before the API request.
No live carrier contact or workflow execution is part of verification.

## Documentation

`examples/README.md` will include commands for simulation and live payload
preview, explain the required HappyRobot workflow behavior, and link to the
public HappyRobot customer story and Kuehne+Nagel HyperCare information used to
shape the example.
