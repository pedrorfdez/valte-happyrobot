"""The PedroD-* workflows, as code.

Three layouts cover everything:
  webhook → Extract → POST          (perception, brains, outcomes)
  webhook → Extract → Send email → POST   (outreach)
  Web call → Inbound Voice Agent + Prompt (voice)

Prompts are scenario-neutral on purpose: zones, doctrine and verbs travel
in the trigger payload, because the wizard can declare any crisis.
`environment` is a plain-language card (hazard, graph, playbook) so a fire
or a blackout is not handled with flood habits. State also travels in the
payload (push): a tunnel outage then costs us the callback, not the run —
the engine reads the run's output instead.
"""

import json
from dataclasses import dataclass, field
from typing import Any, Callable

from valte.hr.plate import Var, doc, p, static, text

EV_WEBHOOK = "b329e750-2e0e-4618-ba65-e04bb6a93c5f"
EV_EXTRACT = "01926f30-36a3-7394-8f73-eeead5d7f948"
EV_POST = "01926f2b-2973-7ebf-ada1-e984251e27ec"
EV_SEND_EMAIL = "0194f7c4-7a82-7bb2-a528-2277ac75be5b"
EV_WEB_CALL = "6e32e01e-722f-4b8b-9372-500b845686d1"
EV_INBOUND_VOICE = "0192e5dc-08df-78bf-a549-f43c6bf9f087"
MODEL = static("gpt-5.6-luna", "GPT-5.6 Luna")
# Person-waiting extracts: no reasoning chain. Small prompt + this model should answer in a few seconds.
FAST = static("gpt-4.1-mini", "GPT-4.1 Mini")
VOICE_ES = static("31hktsdrgix8", "Ana HR")

Ids = dict[str, str]


@dataclass
class NodeSpec:
    name: str
    type: str
    event_id: str
    parent: str | None = None
    config: Callable[[Ids, "Ctx"], dict[str, Any]] = lambda ids, ctx: {}
    webhook_payload: dict[str, Any] | None = None
    custom_output: dict[str, Any] | None = None
    prompt: dict[str, Any] | None = None  # agent nodes: auto-created prompt child

    def prompt_for(self, ids: Ids) -> dict[str, Any] | None:
        if self.prompt is None:
            return None
        return {k: (v(ids) if callable(v) else v) for k, v in self.prompt.items()}


@dataclass
class Ctx:
    secret: str            # bearer our callbacks expect
    static_base: str = ""  # only used when HappyRobot rejects a variable at the start of a URL


@dataclass
class WorkflowSpec:
    name: str
    icon: str
    nodes: list[NodeSpec] = field(default_factory=list)

    def fingerprint(self, ctx: Ctx) -> str:
        import hashlib

        fake = {n.name: n.name for n in self.nodes}
        blob = json.dumps([[n.name, n.type, n.event_id, n.parent, n.config(fake, ctx), n.prompt_for(fake)] for n in self.nodes],
                          sort_keys=True, ensure_ascii=False)
        return hashlib.sha1(blob.encode()).hexdigest()[:16]


def _url(ids: Ids, ctx: Ctx, path: str) -> list[dict[str, Any]]:
    if ctx.static_base:
        return doc(p(ctx.static_base + path))
    return doc(p(Var(ids["trigger"], "callback_base"), path))


def _post(path: str, params: Callable[[Ids], list[tuple[str, Any]]], body_var: str | None = None):
    """HappyRobot sends `params` as the query string. Anything long (decisions,
    plans) goes as the raw body instead: one Extract field holding a whole JSON document."""

    def build(ids: Ids, ctx: Ctx) -> dict[str, Any]:
        rows = [("hr_run_id", Var("current", "run_id")), *params(ids)]
        cfg: dict[str, Any] = {"url": _url(ids, ctx, path), "authType": "bearer", "token": ctx.secret,
                               "contentType": "application/json", "ignore5XX": True,
                               "params": [{"key": k, "value": doc(v if isinstance(v, dict) else p(v))} for k, v in rows]}
        if body_var:
            cfg["body"] = {"raw": "{{$var:%s.%s}}" % (ids["extract"], body_var.replace(".", "#")),
                           "contentType": "application/json", "schemaVersion": 2}
            cfg["webhookSchemaVersion"] = 2
        return cfg

    return build


def _extract(input_doc: Callable[[Ids], list[dict[str, Any]]], prompt: str, schema: dict[str, Any],
             model: dict[str, Any] | None = None):
    chosen = model or MODEL

    def build(ids: Ids, ctx: Ctx) -> dict[str, Any]:
        return {"input": input_doc(ids), "prompt": text(prompt), "model": chosen,
                "json_schema": doc(p(json.dumps(schema, ensure_ascii=False)))}

    return build


def _webhook(params: list[str]) -> NodeSpec:
    sample = {k: f"<{k}>" for k in params}
    return NodeSpec("trigger", "trigger", EV_WEBHOOK, config=lambda ids, ctx: {"params": params},
                    webhook_payload=sample, custom_output=sample)


# ── perception (Kernel family) ───────────────────────────────────────────

PERCEPTION_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "properties": {
        "is_noise": {"type": "boolean", "description": "True if the input has no crisis-relevant information"},
        "claims": {"type": "array", "items": {"type": "object", "additionalProperties": False, "properties": {
            "hazard_type": {"type": "string", "description": "e.g. flood, wildfire, blackout, road_cut, medical"},
            "severity_hint": {"type": "integer", "description": "0-10 per the scale"}},
            "required": ["hazard_type", "severity_hint"]}},
        "location_text": {"type": "string", "description": "Location as written in the input, or empty string"},
        "zone": {"type": "string", "description": "A zone id from the ZONES list, or empty string if unresolvable"},
        "precision": {"type": "string", "description": "exact|street|zone|region|unknown"},
        "summary": {"type": "string", "description": "One factual English sentence: who reports what, where"}},
    "required": ["is_noise", "claims", "location_text", "zone", "precision", "summary"]}

PERCEPTION_PROMPT = """You are the perception layer of an emergency management system. You receive ONE raw {kind}. Extract a normalized signal. Do not decide actions; extract only what the input states.

Read ENVIRONMENT / CRISIS CONTEXT first: it names THIS crisis's hazard. Extract claims for that hazard. Flood, wildfire, blackout, infrastructure failure and mass casualty are different events — do not label a smoke report as flood, or a blackout as a flood, unless the input itself is about water.

The CRISIS CONTEXT and the ZONES list come with the input. Zones are given as `id (name) -> downstream zones`. Resolve the location only from location evidence in the input, never from the hazard, and only to an id present in ZONES. No resolvable place: zone is an empty string and precision is unknown or region.

Severity scale 0-10: 1-3 unusual conditions, no danger; 4-5 property at risk, the hazard starts to affect the area; 6-7 people in danger; 8-9 people trapped, life-threatening; 10 mass casualty.

Precision: exact = coordinates; street = a street, building or landmark; zone = a town or district; region = wider than one zone; unknown = no usable location.

Rules: {rules} Uncertainty lowers severity, never raises it. If the input contains no crisis-relevant information, is_noise is true, claims is empty, and summary starts with NOISE:."""

CHANNEL_RULES = {
    "call": ("emergency call record (112)", "callers are sincere but often wrong about scale and origin; report what they SEE, not their theories. Panic and fragments are normal; extract the facts inside them.", ["caller", "transcript"], "transcript"),
    "social": ("public social media post (unverified)", "posts are unverified and mostly noise; jokes, opinions, questions and small talk are noise. Secondhand rumours ('dicen que', 'they say') get severity 3 at most. An offer of help is relevant: severity 1-2 and say so in the summary.", ["author", "text"], "text"),
    "news": ("news bulletin from a media outlet", "media report with delay and at coarse precision; prefer the body over the headline and do not inflate severity from dramatic wording. A forecast or an official warning about what MAY happen is severity 4 at most: it is a reason to prepare, not an observed impact.", ["outlet", "headline", "body"], "body"),
}


def ingest_spec(channel: str) -> WorkflowSpec:
    kind, rules, fields, content_field = CHANNEL_RULES[channel]
    common = ["crisis_id", "callback_base", "id", "t", "channel", "source", "hazard_context", "zone_catalog"]

    def input_doc(ids: Ids) -> list[dict[str, Any]]:
        t = ids["trigger"]
        return doc(p("ENVIRONMENT: ", Var(t, "hazard_context")), p("ZONES:"), p(Var(t, "zone_catalog")), p(""),
                   p(f"RAW {channel.upper()} INPUT"), p("id: ", Var(t, "id")), p("t: ", Var(t, "t")),
                   *[p(f"{f}: ", Var(t, f)) for f in fields])

    def params(ids: Ids) -> list[tuple[str, Any]]:
        t, e = ids["trigger"], ids["extract"]
        return [("crisis_id", Var(t, "crisis_id")), ("channel", channel), ("id", Var(t, "id")), ("t", Var(t, "t")),
                ("source", Var(t, "source")),
                *[(k, Var(e, f"response.{k}")) for k in ("is_noise", "claims", "location_text", "zone", "precision", "summary")]]

    sample = {"is_noise": False, "claims": [{"hazard_type": "flood", "severity_hint": 6}], "location_text": "",
              "zone": "", "precision": "unknown", "summary": ""}
    return WorkflowSpec(f"PedroD-ingest-{'calls' if channel == 'call' else channel}",
                        {"call": "phone", "social": "comment", "news": "newspaper"}[channel], [
        _webhook(common + fields),
        NodeSpec("extract", "action", EV_EXTRACT, "trigger",
                 _extract(input_doc, PERCEPTION_PROMPT.format(kind=kind, rules=rules), PERCEPTION_SCHEMA),
                 custom_output={"response": sample}),
        NodeSpec("post", "action", EV_POST, "extract", _post("/perceptions", params),
                 custom_output={"id": "sig-0000", "noise": False, "confidence": "medium"}),
    ])


# ── tactical brain (Kernel family) ───────────────────────────────────────

COORDINATOR_PROMPT = """You are the emergency coordinator of a crisis management system. The kernel woke you with a DIGEST of new events and the full WORLD STATE. Decide what to do NOW and output a batch of actions. You are not a chatbot: your output is executed, and real people are contacted because of it.

YOU ARE IN THIS CRISIS, NOT A GENERIC FLOOD. Read ENVIRONMENT first (the ENVIRONMENT block and state.environment). It names the hazard, how it moves and the playbook. Follow that playbook. Flood advice (garages, upper floors, pump_water, barrancos) is wrong for fire, blackout, infrastructure failure or mass casualty.

READ THE STATE FIRST:
- state.doctrine is the emergency plan for this crisis. Follow it.
- state.lessons is what experience taught us, each with an id (`L-12`) and the evidence behind it. `learned: in_this_crisis` lessons come from what YOUR earlier decisions ran into an hour ago (who does not pick up, who takes long to sign, what a person rejected, which source cried wolf): they outrank habits and older lessons. The kernel already enforces some of them (it will refuse a rejected order proposed again without newer evidence). When a lesson shapes an action, add its id to that action's `lessons`.
- state.situation.incidents is WHAT IS HAPPENING: the kernel groups one or several signals about the same thing in the same place into one incident (`signal_ids`, `sources` = independent sources: reposts count once, `people`, `attended_by`). Decide per incident, not per signal: five calls about one care home are one job. `state: candidate` is a single unverified voice: verify it (wellness_check), prepare something reversible or ask for approval, but do not commit scarce units to it irreversibly; `active` is believable and nobody is on it; `attended` already has someone (reinforce only if `people` or severity ask for more).
- state.zones is a propagation graph: each zone lists `downstream` zones with a delay in minutes, plus `eta_min` (minutes until the hazard arrives). DECIDE ON THE GRAPH, NEVER ON LOCAL CONDITIONS: a calm zone downstream of an affected one has a countdown, not safety.
- state.situation.plan is the current strategy (objectives by priority). Work under it. If the digest says PLAN INVALIDATED, stop serving the old objectives and act on what changed.
- state.entities lists who can act: `capabilities` (verbs), `jurisdiction` (zone ids; empty = everywhere), `units.available`, `status`, `escalation_to`. state.verbs explains every verb, its params and which ones need human approval.
- state.recent_actions, state.pending_approval, state.open_contacts and state.active_tripwires are what is already in motion. NEVER repeat it. The kernel REJECTS duplicates (same actor + verb + zones), verbs outside an actor's capabilities, zones outside its jurisdiction and responders with no free units. Do not fight a rejection: adjust or move on.

HOW TO DECIDE:
- Prioritise: life-threatening reports with precise location first, then warnings to zones the hazard has not reached yet, then property. Say in the reasoning why this goes before the rest.
- ALLOCATE ON EVERY WAKE-UP. state.open_needs lists the incidents that ask for help and that nobody covers yet (a need is covered when an action in its zone that commits resources cites its signal_id or its incident_id in evidence). Go through it top to bottom and, for EACH need, either assign resources now or say in situation_note who waits and why. Size params.units to the people involved (2 by default, more for a group such as a care home or a bus), use suggested_verb unless the content says otherwise, and ALWAYS cite the need's signal_id in evidence.
- state.resource_board is the supply: free and total units per responder, where they are deployed, what each can do and where. Resources belong to their entity: pick the responder that has jurisdiction in the zone, the shortest activation_min and units to spare; keep a small reserve while downstream zones are still calm; never assign more than `free`. When needs exceed free units, serve by severity, then people, then location precision; move on to mutual aid (another responder with jurisdiction, then the slow costly ones) before leaving a life-threatening need uncovered. You will be woken again the moment units are freed.
- Standing reflexes (active_tripwires with repeat=true) already sent 2 units to life-threatening, precisely located reports before you woke up: they appear in recent_actions with origin tripwire. Do not duplicate them; REINFORCE them when the report needs more (send another responder and cite both the signal_id and that action id as evidence).
- Request slow or costly resources EARLY, on incomplete evidence: approval and activation take time. A false alarm costs minutes; a late alarm costs lives. With ambiguity, act higher.
- Trust the kernel's `confidence` on each signal. Rumours and single low-confidence posts never justify action alone; corroboration across channels does.
- An entity that did not answer, or is unreachable: use its `escalation_to`. New actors that offer help: register_entity first, then use them only for low-risk verbs.
- A source that went silent is an escalation, not an absence of news: assume its last trend continued. Arm tripwires (set_tripwire) for thresholds you would otherwise have to poll. Use schedule_check sparingly: at most one pending check, and only when nothing else would wake you (every wake-up costs money; new signals, failures and approvals already wake you).
- If everything needed is already in motion, return an empty actions list and explain why in situation_note.

OUTPUT. Return decisions_json: ONE JSON document serialized as a string (no markdown), of the form {"actions":[...],"situation_note":"...","emergency_level":0}. Each item of "actions" is an object of exactly this shape:
{"actor":"<entity id, or system>","verb":"<verb>","target_zones":["<zone ids>"],"params":{},"evidence":["<signal ids or incident ids from the digest or the state>"],"lessons":["<ids of the state.lessons that shaped this action, or empty>"],"reasoning":"<1-2 sentences in Spanish, read verbatim by a human supervisor; if a lesson shaped it, say so>"}
Evidence is mandatory for world verbs and must be real signal or incident ids. Write alert messages and reasoning in Spanish. situation_note: your assessment and plan in 2-4 sentences in Spanish, shown on the dashboard and given back to you at the next wake-up."""

DECISIONS_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "properties": {"decisions_json": {"type": "string", "description": 'A complete JSON document serialized as a string, no markdown: {"actions":[<action objects>],"situation_note":"<2-4 sentences, Spanish>","emergency_level":<0-2>}'}},
    "required": ["decisions_json"]}


def coordinator_spec() -> WorkflowSpec:
    def input_doc(ids: Ids) -> list[dict[str, Any]]:
        t = ids["trigger"]
        return doc(p("ENVIRONMENT:"), p(Var(t, "environment")), p(""),
                   p("WAKE-UP DIGEST (new events): ", Var(t, "digest")), p("pending events: ", Var(t, "pending_events")),
                   p("instruction: ", Var(t, "instruction")), p(""), p("WORLD STATE JSON:"), p(Var(t, "state_json")))

    def params(ids: Ids) -> list[tuple[str, Any]]:
        t = ids["trigger"]
        return [("crisis_id", Var(t, "crisis_id")), ("dispatch_id", Var(t, "dispatch_id"))]

    return WorkflowSpec("PedroD-coordinator", "brain", [
        _webhook(["crisis_id", "dispatch_id", "callback_base", "kind", "pending_events", "digest", "instruction",
                  "environment", "state_json"]),
        NodeSpec("extract", "action", EV_EXTRACT, "trigger", _extract(input_doc, COORDINATOR_PROMPT, DECISIONS_SCHEMA),
                 custom_output={"response": {"decisions_json": "{\"actions\":[],\"situation_note\":\"\",\"emergency_level\":0}"}}),
        NodeSpec("post", "action", EV_POST, "extract", _post("/decisions", params, body_var="response.decisions_json"),
                 custom_output={"results": [], "accepted": 0, "rejected": 0}),
    ])


# ── proactive brain: nobody wakes it, the kernel runs it on a cadence ─────

PROACTIVE_PROMPT = """You are the duty officer doing the rounds of a crisis management system. Nothing woke you: the kernel runs you every few minutes to look for what produces no event and is therefore nobody's job. A separate coordinator reacts to new reports the moment they arrive; do NOT do its work again. You look ahead and keep people and material where they are about to be needed. You are not a chatbot: your output is executed, and real people are contacted because of it.

YOU RECEIVE:
- ENVIRONMENT: this crisis's hazard, zone graph and playbook. Adapt the round to THAT. Flood logistics (pumps, upstairs) only if the hazard is flood.
- PATROL FINDINGS: a sweep the kernel just made. Each finding has an id (`pat-...`), a priority, what is wrong, and often a `suggested_action` that already passes validation. `seen_before: true` means you were given it in an earlier round: act on it only if nothing was done about it or it got worse.
- WORLD STATE: what the coordinator reads. state.doctrine and state.lessons bind you too. state.zones is a propagation graph (`downstream` with delays, `eta_min` = minutes until the hazard arrives). state.entities says who can act (`capabilities`, `jurisdiction`, `units`, `status`, `escalation_to`). state.resources is stock, each with its `owner`. state.open_needs, state.resource_board, state.recent_actions, state.pending_approval, state.open_contacts and state.active_tripwires are demand, supply and what is already in motion. state.verbs explains every verb and its params.

WHAT A GOOD ROUND LOOKS FOR, beyond the findings:
- AHEAD OF THE HAZARD. A calm zone with a countdown and no alert; an evacuation ordered or about to be needed and no shelter places for it (open_shelter BEFORE people are on the street); a slow, costly resource nobody has requested while the trend says it will be needed. Decide on the graph, never on local conditions.
- LOGISTICS. Resources and units belong to their entity. Stock close to running out: move it from an owner that has plenty (transfer_resource) and, if the whole crisis is short, ask for more from outside (request_resupply) BEFORE it reaches zero, because it takes time to arrive. Crews still committed in a zone whose severity fell while a life-threatening need waits and nobody has free units: recall_units on the least critical job, and say so; the coordinator is woken to reassign them. A responder drained to zero in a zone that is still getting worse: line up mutual aid now.
- LOOSE ENDS. A need that has been waiting far too long (assign it, citing its signal_id); an approval with nobody left to sign; an entity that stopped answering and still appears as available (update_entity, and use its escalation_to); a threshold you would otherwise have to keep checking (set_tripwire).

RULES:
- Adopt a suggested_action as it is, change it, or drop it; you may add actions of your own. At most 5 actions per round. An empty list is the right answer when everything is in hand: say why in patrol_note.
- NEVER repeat what is in recent_actions, pending_approval or open_contacts. The kernel rejects duplicates (same actor + verb + zones), verbs outside an actor's capabilities, zones outside its jurisdiction, responders with no free units, and logistics that do not add up. Do not fight a rejection.
- Evidence is mandatory on every action: real signal ids, the id of the action you build on, or the id of the finding (`pat-...`) that justifies it.
- Logistics verbs (recall_units, transfer_resource, request_resupply) and the other system verbs use actor "system". World verbs use the entity that will carry them out.

OUTPUT. Return decisions_json: ONE JSON document serialized as a string (no markdown), of the form {"actions":[...],"patrol_note":"..."}. Each item of "actions" is an object of exactly this shape:
{"actor":"<entity id, or system>","verb":"<verb>","target_zones":["<zone ids>"],"params":{},"evidence":["<signal, incident, action or finding ids>"],"lessons":["<ids of the state.lessons that shaped this action, or empty>"],"reasoning":"<1-2 sentences in Spanish, read verbatim by a human supervisor: what you noticed that nobody had asked about, and why now>"}
state.lessons carry an id and their evidence; the ones `learned: in_this_crisis` are what this operation has already run into: act on them before they bite again (an authority that signs slowly is asked earlier; an entity that does not answer is bypassed) and cite their ids. Write alert messages and reasoning in Spanish. patrol_note: what this round found and what you left alone, in 1-3 sentences in Spanish."""

PROACTIVE_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "properties": {"decisions_json": {"type": "string", "description": 'A complete JSON document serialized as a string, no markdown: {"actions":[<action objects>],"patrol_note":"<1-3 sentences, Spanish>"}'}},
    "required": ["decisions_json"]}


def proactive_spec() -> WorkflowSpec:
    def input_doc(ids: Ids) -> list[dict[str, Any]]:
        t = ids["trigger"]
        return doc(p("ENVIRONMENT:"), p(Var(t, "environment")), p(""),
                   p("ROUND ", Var(t, "round"), " — ", Var(t, "instruction")), p(""), p("PATROL FINDINGS JSON:"),
                   p(Var(t, "findings_json")), p(""), p("WORLD STATE JSON:"), p(Var(t, "state_json")))

    def params(ids: Ids) -> list[tuple[str, Any]]:
        t = ids["trigger"]
        return [("crisis_id", Var(t, "crisis_id")), ("dispatch_id", Var(t, "dispatch_id"))]

    return WorkflowSpec("PedroD-proactive", "eye", [
        _webhook(["crisis_id", "dispatch_id", "callback_base", "round", "instruction", "environment", "findings_json", "state_json"]),
        NodeSpec("extract", "action", EV_EXTRACT, "trigger", _extract(input_doc, PROACTIVE_PROMPT, PROACTIVE_SCHEMA),
                 custom_output={"response": {"decisions_json": "{\"actions\":[],\"patrol_note\":\"\"}"}}),
        NodeSpec("post", "action", EV_POST, "extract", _post("/hr/proactive", params, body_var="response.decisions_json"),
                 custom_output={"results": [], "accepted": 0, "rejected": 0}),
    ])


# ── Gateway family: command bus ──────────────────────────────────────────

PAYLOAD_SCHEMA = {"type": "object", "additionalProperties": False,
                  "properties": {"payload_json": {"type": "string", "description": "The complete payload object serialized as a JSON string. No markdown."}},
                  "required": ["payload_json"]}

INTAKE_PROMPT = """You are `crisis-intake`, a scenario-neutral evidence extraction agent. Convert ONE source input into exactly one Signal. A Signal is an observation, never ground truth. Do not create incidents, plans or actions.

The trigger EVENT carries: id, t, channel, source, hazard_context, zone_catalog (`id (name) -> downstream`) and source_input (the raw content, any shape: sensor reading, operator note, web source, message). hazard_context names THIS crisis: extract claims for that hazard, not a generic flood.

Return payload_json: a JSON string that parses to
{"signal":{"signal_id":"<event.id exactly>","source":"<event.source exactly>","channel":"<event.channel exactly>","modality":"text|call_transcript|sensor_reading|broadcast","content":"<the raw content, verbatim>","is_noise":false,"claims":[{"hazard_type":"<label>","severity_hint":0}],"location":{"zone_id":"<an id from zone_catalog or null>","precision":"exact|street|zone|region|unknown","text":"<location as written, or empty>"},"summary":"<one factual English sentence>"}}

Severity scale 0-10: 1-3 unusual, no danger; 4-5 property at risk; 6-7 people in danger; 8-9 people trapped; 10 mass casualty. Extract claims conservatively: reported, uncertain or contradictory language stays low. If source_input gives an explicit severity or zone, respect it. Resolve a location only to an id present in zone_catalog; otherwise zone_id null and precision unknown. No crisis-relevant information: is_noise true and claims empty."""

COMMAND_PROMPT = """You are `crisis-command`, the strategic planner of a crisis management system. You do NOT issue actions: a tactical coordinator does that under your plan. You decide which incident goes first and what the objectives are. You were woken because the plan no longer describes the world: the EVENT says why.

Read ENVIRONMENT first (hazard, graph, playbook). Then the EVENT and the SNAPSHOT (run, zone_catalog with propagation delays and eta_min, entities and their free units, signals with kernel confidence, current incidents and plan, actions, outcomes, resources). Decide on the propagation graph, not on local conditions. Follow run.doctrine and run.lessons. Do not write flood objectives (pumps, upstairs, barrancos) unless ENVIRONMENT says the hazard is flood.

THE KERNEL FORMS THE INCIDENTS, NOT YOU. snapshot.incidents lists them: each groups one or several signals about the same thing in the same place (`signal_ids`, `sources` = independent sources, `people`, `state` candidate = one unverified voice | active = believable, nobody on it | attended, `attended_by`). Never invent an incident_id. What you may do with them: re-prioritise one (the kernel's priority only looks at severity; you see the graph, the vulnerable and what is coming), say in one sentence why it matters (`summary`), set `revisit_at`, close one that is over (`state: closed`), and tell the kernel that two of them are the same event seen twice (`merge`). Incidents you leave out stay as they are.

Return payload_json: a JSON string that parses to
{"merge":[["<incident_id that stays>","<incident_id that is the same event>"]],
"incidents":[{"incident_id":"<an id from snapshot.incidents>","priority":"P0|P1|P2|P3","summary":"<1 sentence, Spanish: why it matters or what to watch>","state":"<only to close it: closed>","revisit_at":"<ISO time in scenario time, or null>"}],
"plan":{"summary":"<2-3 sentences in Spanish: what changed, what goes first and why>","lessons":["<ids of run.lessons that shaped this plan>"],"objectives":[{"priority":"P0|P1|P2|P3","zone_ids":["<zone ids>"],"incident_ids":["<incidents this objective serves>"],"objective":"<what must be true, Spanish>","suggested_verb":"<a verb from the entities' capabilities>","why":"<one sentence>"}]}}

Rules: P0 = lives at immediate risk with evidence; P1 = the hazard arrives within the warning window or people are in danger; P2 = property or secondary effects; P3 = watch. A candidate incident never gets P0: its objective is to verify it. Order objectives by what goes first given the units actually free, not the units you wish you had. run.lessons carry an id and the evidence behind them; the ones `learned: in_this_crisis` describe what this very operation has run into (who does not answer, what was rejected, which source cried wolf): plan around them and list their ids in plan.lessons. Set revisit_at when you expect the picture to change (for example when the hazard should reach the next zone)."""

OUTCOME_PROMPT = """You are `crisis-response-coordination`. A real contact with a person has just finished (a voice call or an email). Read the EVENT (the action it was about, the purpose of the contact, who was contacted, the brief, and the transcript) and record what it achieved. Do not invent effects that were not said.

Return payload_json: a JSON string that parses to
{"outcome":{"outcome_id":"outcome:<event.event_id>","action_id":"<event.action_id exactly>","attempt_id":"<event.event_id exactly>","status":"acknowledged|approved|rejected|no_answer|unclear","decision":"approved|rejected|unclear","summary":"<1-2 sentences in Spanish: what the person said and committed to>","observed_effects":["<facts the person reported, e.g. 'el puente de Sant Antoni ya está cortado'>"],"evidence":["<short verbatim quotes that support the decision>"]}}

For purpose=approval, decision is approved only on an explicit yes ('sí', 'apruebo', 'adelante', 'autorizo', 'de acuerdo'); rejected on an explicit no; anything else is unclear. For purpose=order or notify, status is acknowledged when the person confirms they will do it, rejected when they refuse or cannot, unclear otherwise; decision mirrors it (acknowledged -> approved)."""


def _command_spec(name: str, icon: str, purpose: str, command_type: str, prompt: str, extra_params: list[str],
                  extra_post: Callable[[Ids], list[tuple[str, Any]]] = lambda ids: []) -> WorkflowSpec:
    def input_doc(ids: Ids) -> list[dict[str, Any]]:
        t = ids["trigger"]
        rows = [p("ENVIRONMENT: ", Var(t, "environment")), p("DISPATCH ID: ", Var(t, "dispatch_id")),
                p("RUN ID: ", Var(t, "run_id")), p("EVENT JSON: ", Var(t, "event"))]
        if "interaction_mode" in extra_params:
            rows.append(p("INTERACTION MODE: ", Var(t, "interaction_mode")))
        if "snapshot_json" in extra_params:
            rows += [p(""), p("SNAPSHOT JSON:"), p(Var(t, "snapshot_json"))]
        return doc(*rows)

    def params(ids: Ids) -> list[tuple[str, Any]]:
        t = ids["trigger"]
        return [("command_id", p(f"{purpose}:", Var(t, "dispatch_id"))), ("run_id", Var(t, "run_id")),
                ("command_type", command_type), ("actor", "happyrobot"), ("causation_id", Var(t, "dispatch_id")),
                *extra_post(ids)]

    return WorkflowSpec(name, icon, [
        _webhook(["dispatch_id", "run_id", "callback_base", "environment", "event", *extra_params]),
        NodeSpec("extract", "action", EV_EXTRACT, "trigger", _extract(input_doc, prompt, PAYLOAD_SCHEMA),
                 custom_output={"response": {"payload_json": "{}"}}),
        NodeSpec("post", "action", EV_POST, "extract", _post("/api/commands", params, body_var="response.payload_json"),
                 custom_output={"accepted": True}),
    ])


def intake_spec() -> WorkflowSpec:
    return _command_spec("PedroD-crisis-intake", "filter", "intake", "upsert_signal", INTAKE_PROMPT, [])


def command_spec() -> WorkflowSpec:
    return _command_spec("PedroD-crisis-command", "map", "command", "replace_plan", COMMAND_PROMPT,
                         ["expected_plan_version", "snapshot_json"],
                         lambda ids: [("expected_plan_version", Var(ids["trigger"], "expected_plan_version"))])


def outcome_spec() -> WorkflowSpec:
    return _command_spec("PedroD-crisis-response-coordination", "clipboard-check", "outcome", "record_outcome",
                         OUTCOME_PROMPT, ["interaction_mode", "snapshot_json"])


# ── outreach: real email ─────────────────────────────────────────────────

EMAIL_PROMPT = """You write operational emails on behalf of CECOPI, the emergency coordination centre, during a live crisis. The recipient is an authority or a response unit. Write in Spanish (Spain), calm and directive, no filler, no greetings longer than one line, no apologies.

ENVIRONMENT names this crisis's hazard. Match it: a fire email must not tell people to go upstairs; a blackout email must not order a town-wide evacuation unless the brief says so; flood advice (garages, upper floors) only if hazard is flood.

BRIEF JSON gives: crisis, clock, entity (the recipient), purpose (approval | order | notify), verb_label and zones (what is asked), reasoning (why), evidence (signals that justify it), escalates_to (who is contacted next if there is no answer).

subject: at most 90 characters, starts with the crisis code in brackets, then the ask. Example: [VLC-4821] Aprobación urgente: ordenar evacuación en Paiporta.
body: plain text with line breaks. Line 1: what is asked, of whom, and where. Then 'Motivo:' with the reasoning in one or two sentences. Then 'Evidencia:' with the evidence lines as a short list. For purpose=approval, end with the two links exactly as given, each on its own line, labelled 'Aprobar:' and 'Rechazar:', and one line saying who will be contacted if there is no answer. For purpose=order, end with 'Confirme la recepción respondiendo a este correo.' Never promise arrival times or resources that are not in the brief. Sign as 'Valte · CECOPI'."""

EMAIL_SCHEMA = {"type": "object", "additionalProperties": False,
                "properties": {"subject": {"type": "string"}, "body": {"type": "string"}},
                "required": ["subject", "body"]}


def outreach_spec() -> WorkflowSpec:
    def input_doc(ids: Ids) -> list[dict[str, Any]]:
        t = ids["trigger"]
        return doc(p("ENVIRONMENT: ", Var(t, "environment")), p("RECIPIENT: ", Var(t, "entity_name")),
                   p("PURPOSE: ", Var(t, "purpose")),
                   p("APPROVE LINK: ", Var(t, "approve_url")), p("REJECT LINK: ", Var(t, "reject_url")), p(""),
                   p("BRIEF JSON:"), p(Var(t, "brief_json")))

    def email(ids: Ids, ctx: Ctx) -> dict[str, Any]:
        t, e = ids["trigger"], ids["extract"]
        return {"to": doc(p(Var(t, "to"))), "from_name": doc(p("Valte · CECOPI")),
                "subject": doc(p(Var(e, "response.subject"))), "body": doc(p(Var(e, "response.body")))}

    def params(ids: Ids) -> list[tuple[str, Any]]:
        t, e = ids["trigger"], ids["extract"]
        return [("contact_id", Var(t, "contact_id")), ("crisis_id", Var(t, "crisis_id")), ("ok", "true"),
                ("subject", Var(e, "response.subject")), ("body", Var(e, "response.body"))]

    return WorkflowSpec("PedroD-outreach", "envelope", [
        _webhook(["contact_id", "crisis_id", "callback_base", "to", "entity_name", "purpose", "brief_json",
                  "environment", "approve_url", "reject_url"]),
        NodeSpec("extract", "action", EV_EXTRACT, "trigger", _extract(input_doc, EMAIL_PROMPT, EMAIL_SCHEMA),
                 custom_output={"response": {"subject": "", "body": ""}}),
        NodeSpec("send_email", "action", EV_SEND_EMAIL, "extract", email, custom_output={"status": "sent"}),
        NodeSpec("post", "action", EV_POST, "send_email", _post("/hr/outreach/result", params),
                 custom_output={"ok": True}),
    ])


# ── voice ────────────────────────────────────────────────────────────────

OUTREACH_CALL_PROMPT = """# Identidad

Eres la voz del CECOPI, el centro de coordinación de una emergencia en curso. Llamas a una autoridad o a una unidad de respuesta. Tu primer mensaje ya ha dicho quién eres, qué pides y por qué: todo lo que sabes está en ese mensaje. No inventes datos que no estén en él. Los datos de la llamada incluyen `crisis` y `hazard`: adapta consignas a ESA amenaza (en un incendio no mandes a plantas altas; en un apagón no ordenes evacuar el pueblo).

# Objetivo

Conseguir una respuesta clara en menos de un minuto:
- Si pides una **aprobación**: un sí o un no explícito. Si dudan, repite en una frase el motivo y la evidencia y vuelve a preguntar: "¿Lo aprueba?".
- Si transmites una **orden o un aviso**: que confirmen que la han recibido y que la ejecutan, o que digan por qué no pueden.

# Cómo hablas

Español de España. Calmada y directiva. Frases cortas, sin relleno, sin disculpas. Una pregunta por turno. Si te preguntan algo que no sabes, di "no tengo ese dato" y vuelve a lo que necesitas.

# Cierre

Cuando tengas la respuesta, repítela en una frase ("Queda aprobada la evacuación de Paiporta", "Entendido, no pueden cortar la carretera"), di "Queda registrado" y cuelga. No prometas tiempos de llegada ni recursos concretos."""

CRISIS_START_PROMPT = """# Identidad

Eres el puesto de admisión de crisis del sistema Valte. Alguien con mando acaba de abrir el micro para declarar una crisis nueva.

# Cómo trabajas

Esto es un dictado, no un interrogatorio. Deja hablar.

- Abre con una sola frase y calla.
- Mientras la persona habla, no interrumpas ni comentes.
- Cuando termine, si falta el **tipo de crisis** o el **sitio**, pregunta por lo que falte, una sola vez y en una sola frase.
- Con tipo y sitio ya se puede declarar la crisis. Lo demás es mejora: no lo persigas.

# Lo que quieres que quede dicho

`crisis_type`, `location`, `started_at`, `scope`, `people_affected`, `immediate_needs`. Si algo no se sabe, queda desconocido y no pasa nada.

# Voz

Español de España. Calmada y directiva. Frases cortas, sin relleno, sin cortesías largas, sin disculpas.

# Cierre

Resume en una frase lo entendido, di "Crisis declarada." y cuelga. No prometas tiempos de llegada ni recursos concretos."""

EMERGENCY_CALL_PROMPT = """# Rol

Eres la operadora de emergencias de Valte. Atiendes una llamada entrante de un ciudadano que reporta una posible emergencia. Tono: sereno, breve, directivo. Idioma: español de España.

# Objetivo

En menos de 60 segundos saber: qué ocurre, dónde exactamente (calle, edificio o punto de referencia, y municipio), cuántas personas están afectadas y si alguien está en peligro inmediato.

# Reglas

- Confirma primero si el llamante está en peligro inmediato. Si lo está, mantenlo en línea.
- Una pregunta por turno. Si no da la ubicación, pídela: sin sitio no se puede enviar a nadie.
- Nunca prometas tiempos de llegada. La central los decide.
- No des consejos fuera de lo evidente y adapta el consejo a lo que está pasando (mantener la calma, alejarse del peligro; en inundación subir a plantas altas y no bajar a garajes; en incendio no usar el ascensor y no volver atrás; en apagón no usar el ascensor).

# Cierre

Antes de colgar repite en una frase lo que has entendido (qué, dónde, cuántas personas) y di "Aviso registrado. Siga atento al teléfono." """


def _voice(name: str, icon: str, agent_name: str, prompt_md: str, initial: Callable[[Ids], list[dict[str, Any]]],
           params: list[str]) -> WorkflowSpec:
    def agent(ids: Ids, ctx: Ctx) -> dict[str, Any]:
        return {"agent": {"name": doc(p(agent_name)), "voices": [VOICE_ES], "languages": [static("es", "Spanish")],
                          "language_accents": [static("es-ES", "Spanish (Spain)")]},
                "business_hours_setting_name": "default", "max_call_duration": 240}

    sample = {k: f"<{k}>" for k in params}
    return WorkflowSpec(name, icon, [
        NodeSpec("trigger", "trigger", EV_WEB_CALL, config=lambda ids, ctx: {"params": params} if params else {},
                 webhook_payload=sample or None, custom_output=sample or None),
        NodeSpec("agent", "agent", EV_INBOUND_VOICE, "trigger", agent,
                 prompt={"prompt_md": prompt_md, "initial_message": initial, "model": MODEL}),
    ])


def outreach_call_spec() -> WorkflowSpec:
    fields = ["contact_id", "crisis", "hazard", "entity", "ask", "reasoning", "evidence", "escalates_to"]

    def initial(ids: Ids) -> list[dict[str, Any]]:
        t = ids["trigger"]
        return doc(p("Le llamo del CECOPI por la crisis ", Var(t, "crisis"), ". ", Var(t, "ask"), " Motivo: ",
                     Var(t, "reasoning"), " ¿Me confirma?"))

    return _voice("PedroD-outreach-call", "phone", "Valte · CECOPI", OUTREACH_CALL_PROMPT, initial, fields)


def crisis_start_spec() -> WorkflowSpec:
    return _voice("PedroD-crisis-start", "fire", "Valte · admisión de crisis", CRISIS_START_PROMPT,
                  lambda ids: doc(p("Valte, centro de crisis. Cuéntame qué está pasando.")), [])


def emergency_call_spec() -> WorkflowSpec:
    return _voice("PedroD-emergency-call", "phone", "Operadora Valte", EMERGENCY_CALL_PROMPT,
                  lambda ids: doc(p("Emergencias Valte, dígame qué ocurre.")), [])


# ── declaring a crisis from one free-text description ────────────────────

CRISIS_PARSE_PROMPT = """You set up a crisis management system from ONE free-text description written or dictated in Spanish by an emergency coordinator who is in a hurry. Dictation has no punctuation and misspells place names: restore the official spelling of Spanish towns (e.g. "pay porta" is Paiporta). Extract only what the text states; never invent zones, resources or sources.

Return crisis_json: ONE JSON document serialized as a string (no markdown) of exactly this shape:
{"name":"<short title, e.g. Incendio en la Calderona>","region":"<comarca, province>","hazard_type":"flood|fire|blackout|infra|mci|other","summary":"<one factual sentence>","zones":[{"name":"<town or district>","population":<inhabitants as an integer, 0 if not stated>,"is_origin":<true where the hazard starts or already is>,"to":[{"name":"<another zone of this list>","delay_min":<minutes the hazard takes to get there>}]}],"sources":[{"name":"<data source, e.g. AEMET, 112, Aforos CHJ, Redes sociales>","desc":"<what it provides>","trust":"high|medium|low"}],"resources":[{"name":"<material or stock, e.g. Bombas de achique>","qty":<number>,"unit":"<ud., L, kits… or empty>","desc":"<where it is or who manages it, or empty>"}],"reports":[{"zone":"<a zone name from zones>","severity":<0-10>,"text":"<one Spanish sentence: the fact, in the coordinator's words>","place":"<street, building or landmark if the text gives one, else empty>","people":<people involved, 0 if not stated>}],"assumptions":["<one Spanish sentence per thing you had to infer>"]}

Rules:
- zones are the places with people to protect: towns, districts, neighbourhoods. `to` is how the hazard spreads between them ("baja de Chiva a Cheste en 25 minutos", "llegará a Bétera en una hora" = 60). Every name in `to` must also be an item of zones. Convert hours to minutes.
- When the text gives no travel time between two zones it clearly links, estimate it from the hazard and the distance and say so in assumptions. When it gives no order at all, leave `to` empty.
- A population said as "27 mil" is 27000. Never guess a population that is not in the text: use 0.
- hazard_type: flood (riada, DANA, barranco, inundación), fire (incendio), blackout (apagón, sin suministro), infra (presa, puente, fuga, colapso), mci (accidente con muchas víctimas, explosión, atentado), else other.
- sources are who REPORTS (sensors, agencies, media, social networks), not who acts. trust: official agencies and sensors high, media medium, social networks and rumours low.
- resources are countable stock (pumps, boats, blankets, water, generators, buses). People and teams (firefighters, police, UME) are NOT resources: leave them out.
- reports is WHAT THE TEXT SAYS IS ALREADY HAPPENING: the crisis opens with them as its first data, before any call or sensor reading, and the system derives the risk per zone and its first actions from them. One entry per fact and zone: the hazard where it already is (always one for each origin zone), people trapped or in danger, vulnerable places the text names (a care home, a hospital on its backup generator, a camping site, a school), a road already cut, an outage. Only what is stated as happening now; what MAY happen later belongs to `to`, not here. severity 0-10: 1-3 unusual conditions, no danger; 4-5 property at risk, the hazard starts to affect the area; 6-7 people in danger; 8-9 people trapped, life-threatening; 10 mass casualty. Uncertainty lowers severity. `place` only when the text pins it to a spot.
- All text values in Spanish."""

CRISIS_PARSE_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "properties": {"crisis_json": {"type": "string", "description": "A complete JSON document serialized as a string, no markdown, with the keys name, region, hazard_type, summary, zones, sources, resources, assumptions"}},
    "required": ["crisis_json"]}


def crisis_parse_spec() -> WorkflowSpec:
    """webhook → Extract. No callback: the person is waiting on the form, so the backend reads the run's output."""
    sample = {"name": "", "region": "", "hazard_type": "other", "summary": "", "zones": [], "sources": [], "resources": [], "assumptions": []}
    return WorkflowSpec("PedroD-crisis-parse", "clipboard-check", [
        _webhook(["text"]),
        NodeSpec("extract", "action", EV_EXTRACT, "trigger",
                 _extract(lambda ids: doc(p("CRISIS DESCRIPTION:"), p(Var(ids["trigger"], "text"))), CRISIS_PARSE_PROMPT, CRISIS_PARSE_SCHEMA),
                 custom_output={"response": {"crisis_json": json.dumps(sample)}}),
    ])


# ── a fact that always changes the world (simulator text + trusted reports) ─

WORLD_PARSE_PROMPT = """You turn ONE Spanish sentence into a structured change of a live crisis. The sentence is a FACT: it always has a consequence. Never treat it as noise, rumour or a 112 call to be doubted.

ENVIRONMENT names the hazard and the zone graph. ZONES lists valid ids. REPORTER is who said it (empty = the outside world). HINT KIND is a hint from a form; trust the TEXT more when HINT is empty or `other`.

Return change_json: ONE JSON document serialized as a string (no markdown):
{"kind":"people_trapped|road_cut|building_damage|power_out|resource_lost|units_down|shelter_full|zone_new|resource_new|entity_new|action_done|other","zone":"<an id from ZONES, or empty>","place":"<street, building or landmark if the text gives one, else empty>","severity":<1-10>,"resource":"<stock name if kind is resource_lost or resource_new, else empty>","qty":<number or 0>,"units":<crew count or 0>,"population":<inhabitants for zone_new, else 0>,"entity":"<name of who joins for entity_new, else empty>","verb":"<close_road|order_evacuation|open_shelter|send_es_alert|rescue|pump_water|wellness_check|supplies|shelter for action_done, else empty>"}

Pick the kind that applies the matching world effect. people_trapped (sev 8-9) if anyone is stuck or in immediate danger; road_cut if a road, bridge or access is gone; building_damage if a building failed; power_out if lights, radio or phones are down; resource_lost / units_down / shelter_full for stock, crews, places; zone_new if a town that is not in ZONES is now affected; resource_new / entity_new if help arrives; action_done if they already did the thing. Use `other` only if nothing else fits, and still set zone + severity >= 6.

A town named in TEXT that is NOT in ZONES is always zone_new: put its name in place, leave zone empty. Do not invent an id. A town that "está aislada / incomunicada / sin acceso" is still zone_new (the kernel isolates it after creating it). Example: "Begís está aislada" → kind=zone_new, place=Begís, zone empty. If that town IS already in ZONES and it is cut off, kind is road_cut and zone is that id.

zone must be an id from ZONES, or empty. Do not invent ids. Numbers: "cuatro" is 4, "50 personas" is people not qty. Be fast: one object, no extra keys."""

WORLD_PARSE_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "properties": {"change_json": {"type": "string", "description": "A complete JSON document serialized as a string, no markdown, with keys kind, zone, place, severity, resource, qty, units, population, entity, verb"}},
    "required": ["change_json"]}


def world_parse_spec() -> WorkflowSpec:
    """webhook → Extract on a fast model. The person is waiting; the backend reads the run."""
    sample = {"kind": "other", "zone": "", "place": "", "severity": 6, "resource": "", "qty": 0, "units": 0,
              "population": 0, "entity": "", "verb": ""}

    def input_doc(ids: Ids) -> list[dict[str, Any]]:
        t = ids["trigger"]
        return doc(p("ENVIRONMENT:"), p(Var(t, "environment")), p("ZONES:"), p(Var(t, "zones")),
                   p("REPORTER: ", Var(t, "reporter")), p("HINT KIND: ", Var(t, "hint_kind")), p(""),
                   p("TEXT:"), p(Var(t, "text")))

    return WorkflowSpec("PedroD-world-parse", "eye", [
        _webhook(["text", "environment", "zones", "hint_kind", "reporter"]),
        NodeSpec("extract", "action", EV_EXTRACT, "trigger",
                 _extract(input_doc, WORLD_PARSE_PROMPT, WORLD_PARSE_SCHEMA, model=FAST),
                 custom_output={"response": {"change_json": json.dumps(sample)}}),
    ])


# ── the post-mortem: what should the next crisis of this kind start with? ─

CRISIS_REVIEW_PROMPT = """You review a crisis that has just been closed, to leave lessons for the NEXT crisis of the same kind. You receive a BRIEF: the incidents (how believable each was, how many minutes passed until somebody went, how each ended), every action with who proposed it, who had to approve it and what happened to it, every contact with its result, and the lessons the kernel already extracted by itself (do not repeat those).

Look for what statistics cannot see: a decision that came too late and why, a resource that was in the wrong place, an approval chain that was the real bottleneck, an incident that turned out false and what gave it away, an order that worked and should become standard. Be concrete and operational: a lesson tells a coordinator what to DO differently next time.

Return lessons_json: ONE JSON document serialized as a string (no markdown): {"lessons":[{"subject":"<2-4 words, lowercase, the thing it is about>","lesson":"<one or two sentences in Spanish, imperative, under 300 characters>","evidence":["<ids copied from the BRIEF: incident ids (inc-…), action ids (act-…), contact ids or signal ids that prove it>"]}]}

Rules: at most 4 lessons, fewer is better; zero is a valid answer ({"lessons":[]}) when the run was uneventful. Every lesson needs at least one evidence id that appears in the BRIEF: a lesson without evidence is discarded. Never mention people by name. Do not restate the brief."""

CRISIS_REVIEW_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "properties": {"lessons_json": {"type": "string", "description": 'A complete JSON document serialized as a string, no markdown: {"lessons":[{"subject":"...","lesson":"...","evidence":["<ids>"]}]}'}},
    "required": ["lessons_json"]}


def crisis_review_spec() -> WorkflowSpec:
    """webhook → Extract. The kernel pulls the output after a close and keeps only lessons whose evidence exists."""
    return WorkflowSpec("PedroD-crisis-review", "clipboard-check", [
        _webhook(["brief_json"]),
        NodeSpec("extract", "action", EV_EXTRACT, "trigger",
                 _extract(lambda ids: doc(p("BRIEF JSON:"), p(Var(ids["trigger"], "brief_json"))), CRISIS_REVIEW_PROMPT, CRISIS_REVIEW_SCHEMA),
                 custom_output={"response": {"lessons_json": json.dumps({"lessons": []})}}),
    ])


def all_specs() -> list[WorkflowSpec]:
    """In order of certainty: what we understand best goes first."""
    return [ingest_spec("call"), ingest_spec("social"), ingest_spec("news"), coordinator_spec(), outreach_spec(),
            outreach_call_spec(), command_spec(), intake_spec(), outcome_spec(), emergency_call_spec(),
            crisis_start_spec(), proactive_spec(), crisis_parse_spec(), world_parse_spec(), crisis_review_spec()]
