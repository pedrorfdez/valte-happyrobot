"""Scripts the outside world for a crisis that has no hand-written pack.

The wizard can declare any crisis (wildfire, blackout, infrastructure
failure, mass casualty…) over any set of zones. This builds a coherent
timeline from that crisis's own zone graph: the hazard starts at the
origins, reaches each zone after the propagation delays the user drew,
and things go wrong along the way (a sensor dies, someone stops
answering, a road is cut, resources are lost). Deterministic per crisis.
"""

import math
import random
from typing import Any

PLACES = ["la calle Mayor", "la avenida de la Constitución", "la plaza del Ayuntamiento", "el polígono industrial",
          "el colegio público", "la residencia de mayores", "el centro de salud", "la urbanización de las afueras",
          "el camping municipal", "la estación"]

NOISE = ["Qué tarde más rara, a ver si puedo ver el partido tranquilo.", "¿Alguien sabe si abre el súper esta tarde?",
         "Yo desde el sofá con mi mantita viendo el panorama 😂", "Pues tampoco es para tanto, qué exagerados sois.",
         "¿A alguien más le va fatal el 4G?", "Vendo bici casi nueva, interesados por privado.",
         "Menudo lunes llevamos… y es sábado."]

HAZARDS: dict[str, dict[str, Any]] = {
    "fire": {
        "claim": "wildfire",
        "official": ("AEMET", "Aviso rojo por riesgo extremo de incendio forestal",
                     "Temperaturas de 39 °C, humedad por debajo del 15 % y rachas de poniente de 60 km/h en {region}. Riesgo extremo de propagación."),
        "sensor": ["Columna de humo detectada · torre de vigilancia de {zone}", "Frente activo de 40 ha avanzando · {zone}",
                   "Frente de 180 ha, llamas de copa y viento rolando · {zone}", "Frente de 450 ha fuera de capacidad de extinción · {zone}"],
        "early": ["Huele muchísimo a humo en {zone}, se ve una columna enorme detrás de {place}.",
                  "En {zone} está cayendo ceniza y el cielo se ha puesto naranja."],
        "mid": ["Llamo desde {zone}: las llamas están llegando a las casas junto a {place} y los vecinos están sacando los coches."],
        "arrive": ["El fuego ha saltado la carretera y ya está en {zone}, arde el pinar pegado a {place}."],
        "severe": ["Estamos en {place} de {zone}, el fuego ha cortado el camino de salida. Somos {n} personas y hay dos mayores que no pueden andar.",
                   "Hay una familia atrapada en una casa de campo junto a {place}, en {zone}. El humo no deja ver nada."],
        "road": "Carretera de acceso a {zone} cortada por el fuego a la altura de {place}.",
        "update": ("El incendio obliga a desalojar viviendas", "El frente avanza empujado por el viento hacia {zone}. Varias carreteras comarcales cortadas por el humo."),
        "rumor": "DICEN que el incendio ha sido provocado y que hay otro foco al otro lado del monte!!! Difundid!!!",
        "volunteers": "Somos un grupo de agricultores de {zone} con 6 tractores y cubas de agua. Decidnos dónde hacemos falta. Tel. 600 123 456.",
        "recovery": ["En {zone} ha caído el viento y el frente parece que ya no avanza. Todo negro.",
                     ("El incendio queda estabilizado", "Los medios aéreos logran frenar el frente en {zone}. Siguen los trabajos de remate.")],
    },
    "blackout": {
        "claim": "blackout",
        "official": ("Red Eléctrica", "Cero energético en la red de distribución",
                     "Una avería en cascada deja sin suministro a {region}. No hay previsión de reposición. Se pide reducir el uso del teléfono."),
        "sensor": ["Subestación de {zone}: tensión inestable", "Subestación de {zone} fuera de servicio · carga 0 %",
                   "Grupos electrógenos del hospital de {zone} al 40 % de combustible", "Repetidores de telefonía de {zone} en batería: 30 min de autonomía"],
        "early": ["Se ha ido la luz en todo {zone}, no funcionan ni los semáforos de {place}.", "{zone} a oscuras. ¿Alguien sabe qué pasa?"],
        "mid": ["Llamo desde {zone}: hay gente atrapada en un ascensor en el edificio junto a {place}."],
        "arrive": ["El apagón ya ha llegado a {zone}. Los semáforos de {place} están apagados y ha habido un choque."],
        "severe": ["Mi madre depende de un respirador en casa, en {zone}, junto a {place}. La batería le dura veinte minutos.",
                   "En {place} de {zone} hay {n} personas dependientes y se ha parado el grupo electrógeno. Necesitamos ayuda ya."],
        "road": "Túnel de acceso a {zone} cerrado: sin ventilación ni iluminación junto a {place}.",
        "update": ("El apagón se extiende", "La caída de la red alcanza ya {zone}. Hospitales funcionando con generadores y telefonía degradada."),
        "rumor": "Me dicen que ha sido un ciberataque y que va a durar UNA SEMANA. Sacad dinero y llenad la bañera!!!",
        "volunteers": "Asociación de vecinos de {zone}: tenemos 3 generadores portátiles y 10 personas para ir casa por casa. Tel. 600 123 456.",
        "recovery": ["Ha vuelto la luz en parte de {zone}. Parpadea pero aguanta.",
                     ("Se recupera el suministro por fases", "Red Eléctrica repone el servicio en {zone} y avanza hacia el resto de la zona afectada.")],
    },
    "infra": {
        "claim": "infrastructure_failure",
        "official": ("Protección Civil", "Aviso por fallo en infraestructura crítica",
                     "Rotura en la red principal de abastecimiento y gas en {region}. Se investiga el alcance. Eviten la zona."),
        "sensor": ["Presión de la red en {zone}: caída del 30 %", "Detector de gas de {zone}: concentración en aumento",
                   "Presión de la red en {zone}: 0 bar · depósito vaciándose", "Detector de gas de {zone}: nivel de evacuación"],
        "early": ["En {zone} no sale agua del grifo y huele a gas cerca de {place}.", "Socavón enorme junto a {place}, en {zone}. Sale agua a presión."],
        "mid": ["Llamo desde {zone}: huele muchísimo a gas en el portal junto a {place} y hay gente mareada."],
        "arrive": ["El corte ya afecta a {zone}. En {place} no hay agua ni gas y el suelo se está hundiendo."],
        "severe": ["Ha habido una explosión en un bajo junto a {place}, en {zone}. Hay {n} heridos y gente bajo los cascotes.",
                   "En {place} de {zone} hay {n} personas que no pueden salir: la escalera se ha venido abajo."],
        "road": "Socavón en el acceso a {zone} junto a {place}: calzada hundida y cortada.",
        "update": ("La avería deja sin servicio a miles de vecinos", "El fallo de la red alcanza {zone}. Los técnicos no pueden acceder al punto de rotura."),
        "rumor": "Dicen que el agua del grifo está ENVENENADA, no la bebáis ni hervida!!! Pasadlo!!!",
        "volunteers": "Somos fontaneros y gasistas de {zone}, 8 personas con furgonetas. Decidnos dónde cortar llaves. Tel. 600 123 456.",
        "recovery": ["En {zone} ya han cortado el gas y no huele. Siguen sin agua pero tranquilos.",
                     ("Controlada la fuga principal", "Los técnicos aíslan el tramo dañado en {zone}. El servicio se repondrá por sectores.")],
    },
    "mci": {
        "claim": "mass_casualty",
        "official": ("112", "Accidente con múltiples víctimas",
                     "Colisión múltiple con un autobús implicado en {region}. Se activa el plan de víctimas múltiples."),
        "sensor": ["Hospital de {zone}: urgencias al 70 %", "Hospital de {zone}: urgencias al 95 %, sin camas de críticos",
                   "Hospital de {zone}: saturado, deriva pacientes", "Banco de sangre de {zone}: reservas bajas de 0 negativo"],
        "early": ["Accidente gordísimo en {zone}, cerca de {place}. Hay un autobús volcado.", "Se oyen sirenas sin parar en {zone}."],
        "mid": ["Llamo desde {zone}: hay muchos heridos en el suelo junto a {place}, algunos no se mueven."],
        "arrive": ["Están llegando heridos por su cuenta a {place}, en {zone}. No damos abasto."],
        "severe": ["Hay {n} personas atrapadas dentro del autobús junto a {place}, en {zone}. Una está inconsciente y sangra mucho.",
                   "En {place} de {zone} tenemos {n} heridos graves y una sola ambulancia. Necesitamos más medios ya."],
        "road": "Acceso a {zone} colapsado junto a {place}: las ambulancias no pueden pasar.",
        "update": ("Decenas de heridos en el accidente", "Los hospitales de {zone} activan su plan de emergencia. Se piden donaciones de sangre."),
        "rumor": "Dicen que hay más de CIEN muertos y que lo están ocultando!!! Compartid!!!",
        "volunteers": "Somos sanitarios fuera de servicio en {zone}, 9 personas con material básico. Decidnos dónde ir. Tel. 600 123 456.",
        "recovery": ["En {zone} ya se han llevado a los últimos heridos. Queda la grúa.",
                     ("Evacuados todos los heridos", "El último herido grave sale de {zone}. Los hospitales recuperan la normalidad.")],
    },
    "flood": {
        "claim": "flood",
        "official": ("AEMET", "Aviso rojo por lluvias torrenciales", "Más de 180 l/m² en 12 horas en {region}. Riesgo extremo de crecidas súbitas en ramblas y barrancos."),
        "sensor": ["Caudal 320 m³/s · aforo de {zone}", "Caudal 610 m³/s y subiendo · aforo de {zone}",
                   "Caudal 1.150 m³/s y subiendo · aforo de {zone}", "Caudal 1.640 m³/s y subiendo · aforo de {zone}"],
        "early": ["En {zone} está cayendo el diluvio universal, el barranco baja marrón junto a {place}.", "El agua ya corre por las calles de {zone}."],
        "mid": ["Llamo desde {zone}: el barranco se está saliendo junto a {place} y el agua entra en los bajos."],
        "arrive": ["El agua ya ha llegado a {zone}, entra en los garajes junto a {place}."],
        "severe": ["El agua entra en el garaje junto a {place}, en {zone}. Hay {n} personas dentro de un coche.",
                   "Estamos en un bajo junto a {place}, en {zone}, con el agua por la rodilla y una persona mayor que no puede subir."],
        "road": "Puente de acceso a {zone} hundido junto a {place}: acceso cortado.",
        "update": ("El barranco se desborda", "La crecida alcanza {zone}. Calles anegadas y cortes de luz en la zona baja."),
        "rumor": "DICEN que ha reventado la presa de arriba!!! Difundid!!!",
        "volunteers": "Somos un grupo de voluntarios de {zone} con 12 furgonetas y una zodiac. Decidnos dónde hacemos falta. Tel. 600 123 456.",
        "recovery": ["En {zone} parece que el agua empieza a bajar. Todo lleno de barro.",
                     ("El nivel desciende", "La punta de la crecida ya ha pasado por {zone}. Comienza el recuento de daños.")],
    },
}
HAZARDS["other"] = {**HAZARDS["infra"], "claim": "incident",
                    "official": ("Protección Civil", "Aviso de emergencia", "Situación de emergencia en desarrollo en {region}. Sigan las indicaciones oficiales.")}

BASE_SOURCES = [  # what any crisis needs in order to be told anything
    {"id": "112", "name": "112", "trust": "high", "notes": "Callers are sincere but often wrong about scale and origin."},
    {"id": "sensores", "name": "Red de sensores", "trust": "high", "notes": "Instrument readings. Silence means the sensor is gone."},
    {"id": "avisos-oficiales", "name": "Avisos oficiales", "trust": "high", "notes": ""},
    {"id": "local-news", "name": "Medios locales", "trust": "medium", "notes": ""},
    {"id": "social-media", "name": "Redes sociales", "trust": "low", "notes": "Unverified. Heavy noise. Useful for early, street-level hints."},
]


def _es(text: str) -> str:
    """Spanish contractions the templates cannot know about in advance."""
    return text.replace(" a el ", " al ").replace(" de el ", " del ")


def _fb(claim: str, zone: str | None, sev: int, precision: str, loc: str, summary: str, noise: bool = False) -> dict[str, Any]:
    return {"is_noise": noise, "claims": [] if noise else [{"hazard_type": claim, "severity_hint": sev}],
            "zone": zone or "", "precision": precision, "location_text": loc, "summary": summary}


def generate(*, hazard: str, region: str, zones: list[dict[str, Any]], responders: list[dict[str, Any]],
             resources: list[dict[str, Any]], seed: str) -> list[dict[str, Any]]:
    """zones: [{id, name, population, is_origin, downstream:[{to, delay_min}]}]."""
    rnd = random.Random(seed)
    H = HAZARDS.get(hazard) or HAZARDS["other"]
    claim = H["claim"]
    by_id = {z["id"]: z for z in zones}
    origins = [z for z in zones if z.get("is_origin")] or zones[:1]
    items: list[dict[str, Any]] = []
    place = lambda: rnd.choice(PLACES)  # noqa: E731

    def call(at: float, z: dict[str, Any], text: str, sev: int) -> None:
        text = _es(text)
        loc = text.split("junto a ")[-1].split(",")[0].rstrip(".") if "junto a " in text else z["name"]
        items.append({"at_min": round(at), "kind": "raw_input", "channel": "call", "source": "112",
                      "payload": {"caller": f"+34 6XX XXX {rnd.randint(100, 999)}", "transcript": text},
                      "fallback": _fb(claim, z["id"], sev, "street", loc, f"Caller in {z['name']} reports: {text[:120]}")})

    def social(at: float, z: dict[str, Any] | None, text: str, sev: int, noise: bool = False, precision: str = "zone") -> None:
        text = _es(text)
        items.append({"at_min": round(at), "kind": "raw_input", "channel": "social", "source": "social-media",
                      "payload": {"author": f"@vecino_{rnd.randint(10, 99)}", "text": text},
                      "fallback": _fb(claim, z["id"] if z else None, sev, "unknown" if noise or z is None else precision,
                                      z["name"] if z else "", ("NOISE: " if noise else "Post: ") + text[:120], noise)})

    def news(at: float, source: str, outlet: str, head: str, body: str, z: dict[str, Any] | None, sev: int) -> None:
        items.append({"at_min": round(at), "kind": "raw_input", "channel": "news", "source": source,
                      "payload": {"outlet": outlet, "headline": head, "body": body},
                      "fallback": _fb(claim, z["id"] if z else None, sev, "zone" if z else "region", z["name"] if z else region,
                                      f"{outlet}: {head}")})

    def sensor(at: float, z: dict[str, Any], sev: int, text: str) -> None:
        items.append({"at_min": round(at), "kind": "sensor", "source": "sensores", "zone": z["id"], "severity": sev, "content": text})

    # When the hazard gets where: origins build up, then the graph's own delays.
    cross: dict[str, float] = {}
    outlet, head, body = H["official"]
    news(0, "avisos-oficiales", outlet, head, body.format(region=region or "la zona"), None, 4)
    for i, o in enumerate(origins):
        base = 2 + 5 * i
        fmt = {"zone": o["name"], "place": place(), "n": rnd.randint(2, 6)}
        sensor(base, o, 3, H["sensor"][0].format(**fmt))
        social(base + 5, o, H["early"][0].format(**fmt), 4)
        sensor(base + 9, o, 5, H["sensor"][1].format(**fmt))
        call(base + 13, o, H["mid"][0].format(**fmt), 6)
        sensor(base + 17, o, 7, H["sensor"][2].format(**fmt))
        sensor(base + 24, o, 8, H["sensor"][3].format(**fmt))
        cross[o["id"]] = base + 17
    for _ in zones:  # relax along the edges
        for z in zones:
            for e in z.get("downstream") or []:
                if z["id"] in cross and e["to"] in by_id:
                    t = cross[z["id"]] + float(e["delay_min"])
                    if t < cross.get(e["to"], math.inf):
                        cross[e["to"]] = t
    reached = sorted((z for z in zones if z["id"] in cross and z not in origins), key=lambda z: cross[z["id"]])
    for z in reached:
        t = min(cross[z["id"]], 160)
        fmt = {"zone": z["name"], "place": place(), "n": rnd.randint(2, 6)}
        social(max(1, t - 9), z, H["early"][1].format(**fmt), 4 + rnd.randint(0, 1))
        call(t, z, H["arrive"][0].format(**fmt), 7)
    exposed = sorted(reached or origins, key=lambda z: -int(z.get("population") or 0))
    for k, z in enumerate(exposed[:2]):
        t = min(cross[z["id"]], 160)
        call(t + 10 + 6 * k, z, H["severe"][k % 2].format(zone=z["name"], place=place(), n=rnd.randint(2, 6)), 8 + k)
    if exposed:
        call(min(cross[exposed[0]["id"]], 160) + 28, exposed[0],
             H["severe"][0].format(zone=exposed[0]["name"], place="la residencia de mayores", n=50), 9)

    end = min(175, max([i["at_min"] for i in items]) + 35)
    first = cross[origins[0]["id"]] if origins else 20

    # Things that go wrong mid-run: the system has to notice and re-plan.
    items.append({"at_min": round(first + 22), "kind": "world", "op": "source_silent", "source": "sensores",
                  "note": "La red de sensores de la zona de origen deja de transmitir."})
    flaky = next((r for r in responders if r.get("escalation_to") and r.get("channel", {}).get("kind") != "none"), None)
    if flaky:
        items.append({"at_min": round(first + 26), "kind": "world", "op": "entity_unreachable", "entity": flaky["id"],
                      "note": f"{flaky['name']} deja de contestar."})
    if exposed:
        z = exposed[0]
        items.append({"at_min": round(min(cross[z["id"]], 160) + 6), "kind": "world", "op": "road_cut", "zone": z["id"],
                      "note": _es(H["road"].format(zone=z["name"], place=place()))})
    lost = next((r for r in resources if float(r.get("total") or 0) >= 4), None)
    if lost:
        items.append({"at_min": round(end * 0.6), "kind": "world", "op": "resource_loss", "resource": lost["id"],
                      "qty": math.ceil(float(lost["total"]) * 0.3), "note": f"Se pierde parte de «{lost['name']}» en un acceso cortado."})
    mid_zone = (reached or origins)[len(reached or origins) // 2]
    head, body = H["update"]
    news(first + 12, "local-news", "Medios locales", head, body.format(zone=mid_zone["name"]), mid_zone, 6)
    social(end * 0.4, None, H["rumor"], 3, precision="unknown")
    social(end * 0.45, mid_zone, H["volunteers"].format(zone=mid_zone["name"]), 2)
    for k in range(int(end // 12)):
        social(4 + 12 * k + rnd.randint(0, 5), None, NOISE[k % len(NOISE)], 0, noise=True)
    o = origins[0]
    social(end - 22, o, H["recovery"][0].format(zone=o["name"]), 3)
    head, body = H["recovery"][1]
    news(end - 8, "local-news", "Medios locales", head, body.format(zone=o["name"]), o, 3)
    return sorted(items, key=lambda i: i["at_min"])
