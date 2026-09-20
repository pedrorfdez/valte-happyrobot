"""How this hazard moves and what to do — so a workflow declared for any
crisis does not fall back to flood habits (garages, upstairs, pumps).

Packs may replace the doctrine; this is what a wizard-declared fire,
blackout or infrastructure failure still gets, and what every brain is
shown in plain language before the world JSON."""

from typing import Any

# claim = the hazard_type perception should put on a report about THIS event.
HAZARDS: dict[str, dict[str, Any]] = {
    "flood": {
        "label": "flood / riada",
        "claim": "flood",
        "moves": "Water follows the zone graph downhill. A dry town downstream has a countdown, not safety.",
        "alert": ("Riada inminente. No baje a garajes ni sótanos, suba a plantas altas y no coja el coche. / "
                  "Riuada imminent. No baixeu a garatges ni soterranis, pugeu a plantes altes i no agafeu el cotxe."),
        "doctrine": [
            "Decide on the propagation graph, never on local weather: a dry town downstream of a flooding zone has a countdown, not safety.",
            "When an upstream zone reaches severity 7: activate_emergency_level 2, send_es_alert to that zone AND every zone downstream in one action, and request_ume early.",
            "ES-Alert: no garages or basements, go to upper floors, do not take the car.",
            "Use pump_water and rescue for people trapped by water; keep a small reserve while downstream is still dry.",
            "A river gauge that goes silent is an escalation, not an absence of news.",
        ],
    },
    "fire": {
        "label": "wildfire / incendio",
        "claim": "wildfire",
        "moves": "Fire and smoke travel along the zone graph with the wind. A calm town downwind has a countdown, not safety. Smoke kills before flames.",
        "alert": ("Incendio acercándose. Abandone ahora, no vuelva a por pertenencias, cierre ventanas y no use el coche si hay humo. / "
                  "Incendi a prop. Marxe ara, no torne a per objectes, tanque finestres i no agafe el cotxe si hi ha fum."),
        "doctrine": [
            "Decide on the graph with the wind: a town downwind of the front has a countdown, not safety.",
            "ES-Alert: leave now, do not go back, close windows, stay low in smoke. NEVER send people upstairs — that is flood advice.",
            "Do not use pump_water. Prefer rescue, close_road (smoke-cut roads) and order_evacuation of the front and the next zone.",
            "Request slow aerial / UME resources early, on incomplete evidence.",
            "A lookout tower or sensor that goes silent on the front is an escalation.",
        ],
    },
    "blackout": {
        "label": "blackout / apagón",
        "claim": "blackout",
        "moves": "The outage spreads through the grid along the zone graph. A town still lit that sits downstream of a dark one has a countdown, not safety.",
        "alert": ("Apagón en extensión. No use el ascensor. Si depende de un dispositivo médico, llame al 112. Reduzca llamadas. / "
                  "Apagada en extensió. No use l'ascensor. Si depèn d'un aparell mèdic, truche al 112."),
        "doctrine": [
            "Decide on the graph: the next zone on the grid will go dark; do not wait for local reports to warn it.",
            "Do NOT order a town-wide evacuation unless a secondary hazard (fire, collapse, medical isolation) says so.",
            "Priority: people on medical devices, lifts, hospitals on generators, dark traffic lights (close_road or wellness_check).",
            "Use supplies and request_resupply for fuel and generators BEFORE they run out; wellness_check for dependents.",
            "A substation or hospital generator going silent is an escalation.",
        ],
    },
    "infra": {
        "label": "infrastructure failure",
        "claim": "infrastructure_failure",
        "moves": "The failure (gas, water, collapse) spreads along the zone graph from the origin. Nearby zones are at risk even if they look calm.",
        "alert": ("Fallo de infraestructura. Aléjese de la zona afectada, no encienda llamas si huele a gas, no beba el agua si se indica. / "
                  "Fallada d'infraestructura. Allunyeu-vos, no encengueu flames si fa olor a gas."),
        "doctrine": [
            "Isolate the origin: close_road, order_evacuation of the immediate zone if gas, collapse or contamination, then warn downstream.",
            "Do not treat this as a flood: no upstairs/garage advice, no pump_water unless the text is actually about water.",
            "Rescue and wellness_check at the failure point; request slow specialists early.",
            "A sensor on the failed asset going silent is an escalation.",
        ],
    },
    "mci": {
        "label": "mass casualty",
        "claim": "mass_casualty",
        "moves": "The scene is local; load then hits hospitals along the zone graph. A hospital still quiet downstream will fill.",
        "alert": ("Accidente con múltiples víctimas. No se acerque. Deje los accesos libres para ambulancias. / "
                  "Accident amb múltiples víctimes. No us acosteu. Deixeu lliures els accessos."),
        "doctrine": [
            "Do NOT evacuate whole towns. Concentrate rescue at the scene and keep roads in open for ambulances (close_road only if it blocks access).",
            "Hospital capacity is the scarce resource: watch downstream hospitals and request_ume / extra responders early.",
            "Rumours of casualty counts are noise until an official or 112 report corroborates them.",
        ],
    },
    "other": {
        "label": "emergency",
        "claim": "incident",
        "moves": "The hazard follows the zone graph the coordinator drew. A calm zone downstream has a countdown, not safety.",
        "alert": ("Emergencia en curso. Siga las indicaciones oficiales y no se acerque a la zona afectada. / "
                  "Emergència en curs. Seguiu les indicacions oficials."),
        "doctrine": [
            "Decide on the propagation graph, never on local calm.",
            "Warn the origin and everything downstream together. Request slow costly resources early.",
            "Do not copy flood-specific advice (garages, upper floors, pumps) unless the reports are actually about water.",
        ],
    },
}


def of(hazard: str) -> dict[str, Any]:
    return HAZARDS.get(hazard) or HAZARDS["other"]


def doctrine(hazard: str) -> list[str]:
    return list(of(hazard)["doctrine"])


def alert_copy(hazard: str) -> str:
    return str(of(hazard)["alert"])


def perception_context(c: Any) -> str:
    """One paragraph the ingest workflows read before the raw input."""
    h = of(c.hazard_type)
    return (f"{c.hazard_type} crisis '{c.name}' in {c.region}. {h['moves']} "
            f"This is NOT a generic flood unless hazard_type is flood. "
            f"When the input is about this event, claims.hazard_type is {h['claim']}. "
            "Resolve locations only to ids in ZONES.")


def environment_brief(c: Any, zones: list[Any], *, doctrine_lines: list[str] | None = None) -> str:
    """Plain-language card the brains read first. Capped: it is a prompt prefix."""
    h = of(c.hazard_type)
    lines = [
        "THIS CRISIS — adapt every decision to this environment; do not default to a flood.",
        f"{c.code} · {c.name} · hazard={c.hazard_type} ({h['label']}) · {c.region}",
        f"How it moves: {h['moves']}",
    ]
    said = (c.transcript or "").strip()
    if getattr(c, "source", "") == "text" and said:
        lines.append("Declared as: " + said[:400])
    lines.append("GRAPH:")
    for z in zones:
        down = ", ".join(f"{e['to']} in {e['delay_min']} min" for e in (z.downstream or [])) or "end of path"
        origin = "; origin" if z.is_origin else ""
        eta = f", eta {z.eta_min} min" if z.eta_min is not None else ""
        lines.append(f"  {z.id} ({z.name}{origin}, sev {z.severity_est}{eta}) -> {down}")
    lines.append("PLAYBOOK (beats generic habits):")
    for d in (doctrine_lines or doctrine(c.hazard_type))[:8]:
        lines.append(f"- {d}")
    return "\n".join(lines)
