"""Builds valte/sim/packs/riada-paiporta.json (kept as a script because the
timeline is easier to edit as calls than as raw JSON)."""

import json
from pathlib import Path

Z = ["chiva", "torrent", "cheste", "paiporta", "picanya", "massanassa"]


def fb(zone, sev, precision, loc, summary, noise=False, hazard="flood"):
    # Scripted perception, used only if HappyRobot does not answer in time.
    return {"is_noise": noise, "claims": [] if noise else [{"hazard_type": hazard, "severity_hint": sev}],
            "zone": zone or "", "precision": precision, "location_text": loc, "summary": summary}


def call(at, caller, transcript, **f):
    return {"at_min": at, "kind": "raw_input", "channel": "call", "source": "112",
            "payload": {"caller": caller, "transcript": transcript}, "fallback": fb(**f)}


def social(at, author, text, **f):
    return {"at_min": at, "kind": "raw_input", "channel": "social", "source": "social-media",
            "payload": {"author": author, "text": text}, "fallback": fb(**f)}


def news(at, src, outlet, head, body, **f):
    return {"at_min": at, "kind": "raw_input", "channel": "news", "source": src,
            "payload": {"outlet": outlet, "headline": head, "body": body}, "fallback": fb(**f)}


def sensor(at, zone, sev, content):
    return {"at_min": at, "kind": "sensor", "source": "chj-gauges", "zone": zone, "severity": sev, "content": content}


def world(at, op, **kw):
    return {"at_min": at, "kind": "world", "op": op, **kw}


NOISE = dict(zone=None, sev=0, precision="unknown", loc="", noise=True)

timeline = [
    news(0, "aemet", "AEMET", "Aviso rojo por lluvias torrenciales en el interior norte de Valencia", "AEMET eleva a rojo el aviso: más de 180 l/m² en 12 horas en la Hoya de Buñol. Riesgo extremo de crecidas súbitas en ramblas y barrancos.", zone=None, sev=4, precision="region", loc="interior norte de Valencia, Hoya de Buñol", summary="AEMET issues a red warning for torrential rain over the upstream basin."),
    sensor(2, "chiva", 3, "Caudal 320 m³/s · Rambla del Poyo, Chiva"),
    social(5, "@vicent_vlc", "Qué día más gris, a ver si para para el partido.", summary="NOISE: weather small talk.", **NOISE),
    social(8, "@marta_chiva", "En Chiva está cayendo el diluvio universal, la rambla baja marrón y con muchísima fuerza. Nunca la había visto así.", zone="chiva", sev=4, precision="zone", loc="Chiva, la rambla", summary="Resident reports the Chiva ravine running brown and strong."),
    sensor(12, "chiva", 5, "Caudal 610 m³/s y subiendo · Rambla del Poyo, Chiva"),
    news(15, "local-news", "À Punt", "Carreteras cortadas en la Hoya de Buñol", "À Punt: varias carreteras comarcales de la Hoya de Buñol cortadas por acumulación de agua. Se pide evitar desplazamientos.", zone=None, sev=4, precision="region", loc="Hoya de Buñol", summary="Regional TV reports roads closed by water upstream."),
    social(18, "@pepa_pai", "¿Alguien sabe si abren el Mercadona de Paiporta esta tarde?", summary="NOISE: shopping question.", **NOISE),
    call(20, "+34 6XX XXX 120", "Llamo desde Chiva, el barranco se está saliendo por la calle Ramón y Cajal, el agua ya entra en los bajos. Hay vecinos mayores en las plantas bajas.", zone="chiva", sev=6, precision="street", loc="calle Ramón y Cajal, Chiva", summary="Caller in Chiva reports the ravine overflowing into ground floors on Ramón y Cajal street."),
    sensor(24, "chiva", 7, "Caudal 1.150 m³/s y subiendo · Rambla del Poyo, Chiva"),
    social(26, "@joan_cheste", "En Cheste el barranco ya se ha salido, esto va para abajo muy rápido.", zone="cheste", sev=6, precision="zone", loc="Cheste", summary="Resident reports the ravine has overflowed in Cheste and is moving downstream fast."),
    social(28, "@memesvlc", "Yo viendo llover desde el sofá con mi mantita 😂", summary="NOISE: joke.", **NOISE),
    call(30, "+34 6XX XXX 233", "Estamos en Cheste, en la avenida hay coches arrastrados por el agua, no sabemos si hay gente dentro.", zone="cheste", sev=7, precision="street", loc="la avenida, Cheste", summary="Caller in Cheste reports cars swept away on the avenue, occupants unknown."),
    sensor(33, "torrent", 5, "Nivel 2,1 m y subiendo · Barranc de l'Horteta, Torrent"),
    sensor(36, "chiva", 8, "Caudal 1.640 m³/s y subiendo · Rambla del Poyo, Chiva"),
    world(38, "source_silent", source="chj-gauges", note="El aforo de Chiva ha sido arrastrado por la riada."),
    call(40, "+34 6XX XXX 871", "Avenida del Vedat en Torrent, el barranco se ha desbordado, hay un autobús parado con el agua por las ruedas y gente dentro.", zone="torrent", sev=6, precision="street", loc="avenida del Vedat, Torrent", summary="Caller reports the Horteta ravine overflowing on Vedat avenue with a stranded bus."),
    world(42, "entity_unreachable", entity="policia-local-torrent", note="Repetidor caído: la Policía Local de Torrent no contesta."),
    news(45, "levante-emv", "Levante-EMV", "El barranco del Poyo se desborda en Chiva y Cheste", "Levante-EMV: el barranco del Poyo se ha desbordado a su paso por Chiva y Cheste. La CHJ ha perdido la señal del aforo de Chiva.", zone="chiva", sev=7, precision="zone", loc="Chiva y Cheste", summary="Newspaper confirms overflow in Chiva and Cheste and the loss of the Chiva gauge."),
    social(48, "@tiosam", "Llueve. Qué novedad en octubre.", summary="NOISE: sarcasm.", **NOISE),
    social(50, "@laia_picanya", "Desde Picanya: el barranco viene muy cargado, los vecinos de la calle Mayor están sacando los coches de los garajes.", zone="picanya", sev=5, precision="street", loc="calle Mayor, Picanya", summary="Resident reports the ravine rising in Picanya and neighbours emptying garages."),
    social(52, "@alertas_fake", "DICEN que ha reventado la presa de Forata!!! Difundid!!!", zone=None, sev=3, precision="unknown", loc="presa de Forata", summary="Unverified secondhand rumour of a dam failure at Forata."),
    call(55, "+34 6XX XXX 402", "El agua ya entra en el garaje de la calle Mestre Serrano, hay dos personas dentro de un coche.", zone="paiporta", sev=8, precision="street", loc="garaje de la calle Mestre Serrano", summary="Caller reports water entering a garage on Mestre Serrano street with two people trapped in a car."),
    social(58, "@voluntaris_picanya", "Somos un grupo de voluntarios en Picanya con 12 furgonetas y una zodiac. Decidnos dónde hacemos falta. Tel. 600 123 456.", zone="picanya", sev=2, precision="zone", loc="Picanya", summary="A volunteer group in Picanya offers 12 vans and a boat; contact 600 123 456."),
    call(60, "+34 6XX XXX 518", "Estamos en un bajo de la calle Mayor, el agua nos llega por la rodilla, hay una persona mayor que no puede subir escaleras.", zone="picanya", sev=7, precision="street", loc="bajo en la calle Mayor", summary="Caller in Picanya reports knee-high water in a ground floor with an elderly person who cannot climb stairs."),
    world(63, "road_cut", zone="paiporta", note="Puente de la calle Sant Antoni hundido: acceso sur a Paiporta cortado."),
    news(64, "local-news", "À Punt", "Cortes de luz en Picanya y Paiporta", "À Punt: cortes de luz en Picanya y Paiporta, calles anegadas en la zona baja.", zone=None, sev=6, precision="region", loc="Picanya y Paiporta", summary="Regional TV reports power cuts and flooded streets in Picanya and Paiporta."),
    social(66, "@runner_vlc", "Pues yo he salido a correr y tampoco es para tanto, exagerados.", summary="NOISE: opinion.", **NOISE),
    call(70, "+34 6XX XXX 077", "Llamo de la residencia de mayores de Paiporta: la planta baja se está inundando, tenemos 50 residentes y no podemos subirlos a todos. Necesitamos evacuar ya.", zone="paiporta", sev=9, precision="street", loc="residencia de mayores, Paiporta", summary="A care home in Paiporta reports its ground floor flooding with 50 residents who cannot be moved upstairs."),
    world(75, "resource_loss", resource="bombas-achique", qty=4, note="Un camión con 4 bombas de achique queda atrapado en la CV-36."),
    call(80, "+34 6XX XXX 655", "En Massanassa empieza a entrar agua por la carretera de Paiporta, viene muy rápido.", zone="massanassa", sev=5, precision="street", loc="carretera de Paiporta, Massanassa", summary="Caller reports water entering Massanassa along the Paiporta road."),
    social(85, "@laia_picanya", "Picanya sin luz y el pont vell cerrado por la policía. No bajéis a los garajes.", zone="picanya", sev=6, precision="street", loc="pont vell, Picanya", summary="Resident reports a blackout in Picanya and the old bridge closed."),
    news(90, "levante-emv", "Levante-EMV", "Cientos de vehículos atrapados en la V-31", "Levante-EMV: la Generalitat pide no circular por la V-31; cientos de vehículos atrapados entre Massanassa y Alfafar.", zone="massanassa", sev=7, precision="zone", loc="V-31, Massanassa", summary="Newspaper reports hundreds of vehicles trapped on the V-31 near Massanassa."),
    call(100, "+34 6XX XXX 910", "Estamos seis personas en el tejado de una nave en el polígono de Paiporta, el agua sigue subiendo.", zone="paiporta", sev=9, precision="street", loc="polígono industrial, Paiporta", summary="Six people report being on a warehouse roof in the Paiporta industrial estate with water rising."),
    social(104, "@pepa_pai", "¿A alguien más le va fatal el 4G?", summary="NOISE: connectivity complaint.", **NOISE),
    social(120, "@marta_chiva", "En Chiva parece que el agua empieza a bajar. Todo lleno de barro.", zone="chiva", sev=3, precision="zone", loc="Chiva", summary="Resident reports the water starting to recede in Chiva."),
    news(135, "local-news", "À Punt", "El nivel desciende en Chiva y Cheste", "À Punt: el nivel desciende en Chiva y Cheste; la punta de la riada avanza hacia l'Albufera.", zone="cheste", sev=3, precision="zone", loc="Chiva y Cheste", summary="Regional TV reports levels dropping in Chiva and Cheste while the peak moves towards l'Albufera."),
]


def auth(id, name, zone, weight=7, channel=None, esc="delegacion-gobierno",
         caps=("order_evacuation", "open_shelter", "close_road", "send_es_alert")):
    return {"id": id, "name": name, "kind": "authority", "role": "authority", "weight": weight, "trust": "high",
            "jurisdiction": [zone] if zone else [], "channel": channel or {"kind": "email", "address": f"{id}@demo.valte"},
            "capabilities": list(caps), "activation": {"delay_min": 0, "cost": "low"}, "escalation_to": esc}


def resp(id, name, zones, units, caps, channel=None, esc="delegacion-gobierno", delay=0, cost="low", available=None, notes=""):
    return {"id": id, "name": name, "kind": "responder", "role": "responder", "weight": 6, "trust": "high",
            "jurisdiction": zones, "channel": channel or {"kind": "email", "address": f"{id}@demo.valte"},
            "capabilities": caps, "units": {"total": units, "available": units if available is None else available},
            "activation": {"delay_min": delay, "cost": cost}, "escalation_to": esc, "notes": notes}


def src(id, name, trust, notes=""):
    return {"id": id, "name": name, "kind": "information_source", "weight": 3, "trust": trust, "jurisdiction": [],
            "channel": {"kind": "none"}, "capabilities": [], "notes": notes}


pack = {
    "id": "riada-paiporta", "name": "Riada en Paiporta", "hazard_type": "flood", "region": "Horta Sud, Valencia",
    "description": "Crecida súbita del barranco del Poyo: el agua baja de Chiva a l'Horta Sud en menos de una hora.",
    "code_prefix": "VLC", "tz": "Europe/Madrid", "t0_time": "14:05", "duration_min": 150,
    "coordination_entity": "cecopi", "approval_verbs": ["order_evacuation", "request_ume"],
    "doctrine": [
        "Decide on the propagation graph, never on local weather: a dry town downstream of a flooding zone has a countdown, not safety.",
        "When an upstream zone reaches severity 7 (any confidence): activate_emergency_level 2, send_es_alert to that zone AND every zone downstream of it in one action, and request_ume early (it needs 180 min and human approval).",
        "Upstream severity 4-6 with medium+ confidence: activate_emergency_level 1 and arm tripwires (gauge >= 7; gauge silence 20 min).",
        "A gauge that goes silent is an escalation, not an absence of news: assume the last trend continued.",
        "Trapped-people reports with medium+ confidence: rescue with the nearest responder that has free units; keep 2 units in reserve while zones downstream are still dry.",
        "ES-Alert message in castellano and valencià: riada inminente, no bajar a garajes ni sótanos, subir a plantas altas, no coger el coche.",
        "Secondhand rumours never raise severity on their own; corroboration across channels beats any single source.",
        "A false alarm costs minutes; a late alarm costs lives. With ambiguity, act higher.",
        "If an entity does not answer, use its escalation_to. Register new actors that offer help (register_entity) before relying on them.",
    ],
    "tripwires": [
        {"id": "tw-gauge-silence", "if": {"type": "silence", "source": "chj-gauges", "silence_min": 20},
         "then": [{"actor": "cecopi", "verb": "activate_emergency_level", "target_zones": [], "params": {"level": 2}}],
         "reason": "Plan de inundaciones: si el aforo enmudece con tendencia ascendente, se asume lo peor."}
    ],
    "zones": [
        {"id": "chiva", "centroid": {"lat": 39.4717, "lng": -0.7194}, "name": "Chiva", "population": 15800, "is_origin": True, "elevation": "high", "base_at_risk_pct": 24, "notes": "Cabecera de la rambla del Poyo. Aforo de la CHJ.", "downstream": [{"to": "cheste", "delay_min": 25}, {"to": "paiporta", "delay_min": 38}]},
        {"id": "torrent", "centroid": {"lat": 39.4371, "lng": -0.4655}, "name": "Torrent", "population": 87400, "is_origin": True, "elevation": "medium", "base_at_risk_pct": 14, "notes": "Barranc de l'Horteta; la avenida del Vedat es el punto bajo.", "downstream": [{"to": "picanya", "delay_min": 50}]},
        {"id": "cheste", "centroid": {"lat": 39.4936, "lng": -0.6833}, "name": "Cheste", "population": 8900, "is_origin": False, "elevation": "medium", "base_at_risk_pct": 18, "notes": "El barranco cruza el casco urbano.", "downstream": [{"to": "picanya", "delay_min": 19}]},
        {"id": "paiporta", "centroid": {"lat": 39.4278, "lng": -0.4172}, "name": "Paiporta", "population": 27180, "is_origin": False, "elevation": "low", "base_at_risk_pct": 40, "notes": "Cota baja junto al barranco. Muchos garajes y bajos: es donde se concentra el riesgo.", "downstream": [{"to": "massanassa", "delay_min": 17}]},
        {"id": "picanya", "centroid": {"lat": 39.4358, "lng": -0.4336}, "name": "Picanya", "population": 11700, "is_origin": False, "elevation": "low", "base_at_risk_pct": 28, "notes": "Bajos de la calle Mayor junto al barranco.", "downstream": [{"to": "massanassa", "delay_min": 11}]},
        {"id": "massanassa", "centroid": {"lat": 39.4089, "lng": -0.3986}, "name": "Massanassa", "population": 9800, "is_origin": False, "elevation": "low", "base_at_risk_pct": 22, "notes": "Última zona antes de l'Albufera. V-31 muy expuesta.", "downstream": []},
    ],
    "entities": [
        {"id": "cecopi", "name": "CECOPI", "kind": "authority", "role": "coordination", "weight": 10, "trust": "high", "jurisdiction": [], "channel": {"kind": "none"}, "capabilities": ["send_es_alert", "activate_emergency_level", "request_ume"], "activation": {"delay_min": 0, "cost": "low"}},
        auth("delegacion-gobierno", "Delegación del Gobierno", None, weight=9, esc=None, caps=("order_evacuation", "close_road", "open_shelter", "request_ume")),
        auth("alcaldia-paiporta", "Alcaldía de Paiporta", "paiporta", weight=8, channel={"kind": "voice", "address": "+34 963 971 222"}),
        auth("ayto-chiva", "Ayuntamiento de Chiva", "chiva"), auth("ayto-cheste", "Ayuntamiento de Cheste", "cheste"),
        auth("ayto-torrent", "Ayuntamiento de Torrent", "torrent"), auth("ayto-picanya", "Ayuntamiento de Picanya", "picanya"),
        auth("ayto-massanassa", "Ayuntamiento de Massanassa", "massanassa"),
        resp("bomberos-vlc", "Bomberos Consorcio", Z, 40, ["rescue", "pump_water"]),
        resp("policia-local-paiporta", "Policía Local de Paiporta", ["paiporta"], 12, ["close_road", "wellness_check"], esc="guardia-civil-torrent"),
        resp("policia-local-torrent", "Policía Local de Torrent", ["torrent"], 10, ["close_road", "wellness_check"], channel={"kind": "voice", "address": "+34 961 111 092"}, esc="guardia-civil-torrent"),
        resp("guardia-civil-torrent", "Guardia Civil · Torrent", ["torrent", "picanya", "paiporta", "massanassa"], 14, ["close_road", "rescue", "wellness_check"], delay=10),
        resp("guardia-civil-chiva", "Guardia Civil · Chiva", ["chiva", "cheste"], 8, ["close_road", "rescue", "wellness_check"], delay=10),
        resp("samu", "SAMU", ["paiporta", "picanya", "massanassa", "torrent"], 8, ["rescue", "wellness_check"], delay=5),
        resp("cruz-roja", "Cruz Roja", Z, 10, ["shelter", "supplies", "wellness_check"], delay=15),
        resp("ume", "UME · 120 efectivos", Z, 120, ["rescue", "pump_water"], delay=180, cost="high", available=0, notes="Not operational until request_ume is approved and 180 minutes pass."),
        src("112", "112 Comunitat Valenciana", "high", "Callers are sincere but often wrong about scale and origin."),
        src("chj-gauges", "Aforos CHJ", "high", "River gauges. Silence means the gauge is gone."),
        src("aemet", "AEMET", "high"), src("local-news", "À Punt", "medium"), src("levante-emv", "Levante-EMV", "medium"),
        src("social-media", "Redes sociales", "low", "Unverified. Heavy noise. Useful for early, street-level hints."),
    ] + [{"id": f"vecinos-{z}", "name": f"Vecinos · {z.capitalize()}", "kind": "population", "weight": 1, "trust": "low",
          "jurisdiction": [z], "channel": {"kind": "none"}, "capabilities": [], "zone": z} for z in Z],
    # Every stock has an owner: only that entity and the coordination centre can see or spend it.
    "resources": [
        {"id": "agua", "name": "Agua embotellada", "unit": "L", "total": 2400, "available": 2400, "owner_entity_id": "cruz-roja"},
        {"id": "raciones", "name": "Raciones de comida", "unit": "", "total": 3000, "available": 3000, "owner_entity_id": "cruz-roja"},
        {"id": "mantas", "name": "Mantas", "unit": "", "total": 800, "available": 800, "owner_entity_id": "cruz-roja"},
        {"id": "medicamentos", "name": "Medicamentos básicos", "unit": "kits", "total": 400, "available": 400, "owner_entity_id": "samu"},
        {"id": "bombas-achique", "name": "Bombas de achique", "unit": "", "total": 12, "available": 12, "owner_entity_id": "bomberos-vlc"},
        {"id": "embarcaciones", "name": "Embarcaciones", "unit": "", "total": 6, "available": 6, "owner_entity_id": "bomberos-vlc"},
        {"id": "vehiculos-gc-torrent", "name": "Todoterrenos", "unit": "", "total": 6, "available": 6, "owner_entity_id": "guardia-civil-torrent"},
    ],
    "timeline": timeline,
}

out = Path(__file__).resolve().parents[1] / "valte" / "sim" / "packs" / "riada-paiporta.json"
out.write_text(json.dumps(pack, ensure_ascii=False, indent=1), encoding="utf-8")
print(out.name, out.stat().st_size, "bytes;", len(timeline), "timeline items;",
      sum(1 for t in timeline if t["kind"] == "raw_input"), "need perception")
