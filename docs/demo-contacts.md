# Demo contact allowlist

This file never contains a real email address, phone number, access value or credential.

## Logical contacts

| Contact ID | Purpose | Allowed channels | Owner confirmation |
| --- | --- | --- | --- |
| `demo-field-lead` | Controlled mission recipient | Web Voice, email | Required before every live run |

## Before enabling live mode

- [ ] The recipient is present and has explicitly consented to this demo interaction.
- [ ] `DEMO_CONTACT_ID=demo-field-lead`.
- [ ] `DEMO_ALLOWED_CONTACT_IDS` contains exactly `demo-field-lead`.
- [ ] The real address exists only in `.env` and a hidden HappyRobot development variable.
- [ ] The operator reads the rendered message before changing `DEMO_INTERACTION_MODE`.
- [ ] The run and Action are still active/approved in the latest Gateway snapshot.
- [ ] The Action and snapshot have the exact same pack identity and state is still current.
- [ ] This live run uses a newly approved Action and a new `dispatch_id`, not the Action/dispatch
      consumed by a dry-run.
- [ ] The snapshot has no existing Outcome or started attempt for the Action, dispatch or
      `attempt_id`.
- [ ] The spoken/written message begins with `SIMULACIÓN —`.
- [ ] For PSTN only: an existing verified number and credential were selected explicitly.

These boxes are an operator gate, not repository state. Do not commit them as completed. If any
item cannot be confirmed immediately before the effect, keep `DEMO_INTERACTION_MODE=dry-run`.

## Stop conditions

Stay in `dry-run` when consent, whitelist, current approval, pack identity or channel status is
uncertain. Set an uncertain external effect to `unknown`; do not retry it automatically and do not
switch channels after an attempt has started. Never turn a completed dry-run live by changing its
mode; request a new approved Action and dispatch instead.
