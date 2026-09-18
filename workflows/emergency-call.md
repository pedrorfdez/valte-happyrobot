# Workflow: emergency-call (example)

First HappyRobot workflow. Handles one inbound call from a citizen
reporting a possible emergency. Kept intentionally minimal — we grow it
once this one works end-to-end.

Created via `POST /api/v2/workflows/` from template `inbound-voice-agent`.

- Workflow id: `01a0b67c-f87e-728d-ae0f-66edf0451c6b`
- Slug: `p73en2kz4jny`
- Version 1 id: `01a0b67c-f88b-7e97-bf17-29b2b15b2680` (draft, unpublished)
- Org: `HackSpain - Team 2` (`01a0b58b-9030-724a-94dc-8c17003e3c45`)

## Trigger

Inbound voice call to a HappyRobot phone number.

## Agent goal

Extract, in under 60 seconds, four fields:

- `incident_type` — fire, injury, flood, blackout, other.
- `location` — address or landmark.
- `people_affected` — how many.
- `severity` — low, medium, high, critical.

## Persona

- Voice: female, calm, Spanish (es-ES).
- Tone: brief, directive, no filler.
- First line: "Emergencias Valte, ¿me dice qué ocurre?"

## Guardrails

- Never promise ETAs.
- If the caller is in immediate danger, keep them on the line.
- If information is unclear after two follow-ups, mark `severity = high`
  and hand off.

## Output

At end of call, POST the extracted fields to our backend (URL TBD once
we have the tunnel up). Payload:

```json
{
  "source": "emergency-call",
  "incident_type": "fire",
  "location": "Rúa do Vilar 12, Santiago",
  "people_affected": 2,
  "severity": "high",
  "transcript_url": "..."
}
```

## Open questions

- Exact HR node types for "extract structured fields at end of call".
- Where in the HR console we set the webhook URL.
- Whether HR exposes a Spanish voice out of the box.
