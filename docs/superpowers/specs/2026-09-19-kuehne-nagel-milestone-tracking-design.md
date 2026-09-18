# Kuehne+Nagel milestone tracking example

## Purpose

Create one executable REST API example inspired by the public Kuehne+Nagel and
HappyRobot Healthcare HyperCare case. The example models outbound carrier
follow-up for a temperature-controlled healthcare shipment and decides whether
the result should be recorded or escalated.

The implementation is an original demonstration. No public source code for the
Kuehne+Nagel deployment was found.

## Scope

The example will cover three carrier outcomes:

1. `confirmed`: the carrier confirms the milestone, ETA, and acceptable
   temperature. The event is recorded without escalation.
2. `delayed`: the carrier reports a delay or a temperature outside the allowed
   range. The event is marked critical and escalated immediately.
3. `no_answer`: the carrier does not answer. Attempts are incremented; reaching
   the configured maximum triggers escalation to the control tower.

The script will not place the telephone call itself. It will construct and send
the event that starts an appropriately configured HappyRobot workflow. Voice
behavior belongs to that workflow.

## Interface

The script will follow the existing examples and accept the workflow ID as its
first argument. Scenario data will be configurable through environment
variables so the demo remains readable from the command line.

Required runtime dependency and authentication behavior will come from
`examples/_lib/happyrobot.sh`.

Primary inputs:

- `CARRIER_STATUS`: `confirmed`, `delayed`, or `no_answer`.
- `SHIPMENT_ID`: shipment correlation identifier.
- `CARRIER_NAME`: carrier being contacted.
- `MILESTONE`: operational checkpoint being confirmed.
- `EXPECTED_AT`: planned milestone time in ISO 8601 format.
- `REPORTED_ETA`: ETA reported by the carrier when available.
- `TEMPERATURE_C`: latest reported cargo temperature.
- `TEMPERATURE_MIN_C` and `TEMPERATURE_MAX_C`: allowed range.
- `CONTACT_ATTEMPT` and `MAX_CONTACT_ATTEMPTS`: retry state.
- `LANGUAGE`: preferred contact language.
- `DRY_RUN`: defaults to `true`.

## Decision rules

| Carrier status | Additional condition | Severity | Action |
| --- | --- | --- | --- |
| `confirmed` | Temperature inside range | `normal` | Record confirmation |
| `confirmed` | Temperature outside range | `critical` | Escalate immediately |
| `delayed` | Any | `critical` | Escalate immediately |
| `no_answer` | Attempt below maximum | `warning` | Schedule another attempt |
| `no_answer` | Attempt reaches maximum | `critical` | Escalate to control tower |

Temperature values will be validated as numbers. Attempt counters will be
validated as positive integers, and carrier status will be restricted to the
three supported values.

## API payload

The script will reuse `POST /workflows/{workflow_id}/runs` and send:

- the HappyRobot environment at the top level;
- shipment and carrier identity;
- milestone timing;
- temperature measurement and permitted range;
- carrier response and contact-attempt state;
- computed severity, escalation flag, and recommended action;
- a deterministic incident ID for correlation;
- source and observation timestamp.

The payload will contain operational shipment metadata only. It will not
include patient or other personal health information.

## Safety and side effects

`DRY_RUN=true` will print the computed payload and make no API request. A real
workflow run requires explicitly setting `DRY_RUN=false`.

The shared helper defaults to the HappyRobot `development` environment. API
keys remain server-side and will never be printed.

## Verification

Validation will cover:

1. Shell syntax and static analysis.
2. `confirmed` with temperature inside range.
3. `confirmed` with temperature outside range.
4. `delayed`.
5. `no_answer` before the maximum attempt.
6. `no_answer` at the maximum attempt.
7. Invalid carrier status, temperature, and attempt values.

All behavioral checks will run in dry-run mode or in a path that exits before
the API request. No live carrier contact or workflow execution is part of the
verification.

## Documentation

`examples/README.md` will include commands for the main scenarios and links to
the public HappyRobot customer story and Kuehne+Nagel HyperCare information
used to shape the example.
