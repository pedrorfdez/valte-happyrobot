"""Plantillas de prompts dinámicos y generador procedimental de transcripciones (Faker y Anti-Clonado)."""

import json
import random
from typing import Dict, Any, List
from faker import Faker

# Instancia de Faker configurada para España
fake = Faker("es_ES")

# Sistema de instrucciones para el LLM con directiva anti-clonado estricta (en caso de uso con API)
SYSTEM_PROMPT = """Eres un simulador ultra-realista de llamadas de emergencias al 112 durante la catástrofe de la DANA en la provincia de Valencia.
Tu objetivo es producir una transcripción textual única, hiperrealista, caótica y profundamente humana.

DIRECTIVAS CRÍTICAS DE ESTILO Y DIVERSIDAD:
- PROHIBIDO REPETIR PLANTILLAS O FRASES TÍPICAS. Cada llamada debe ser totalmente distinta en contenido, vocabulario, entonación y duración.
- Varía edades, personalidades, perfiles (ancianos desorientados, jóvenes asustados, padres angustiados, camioneros atrapados, vecinos furiosos, llamadas entrecortadas, etc.).
- Incluye el municipio exacto asignado y términos geográficos o de contexto reales (barranco del Poyo, CV-36, V-30, polígonos, calles reales).
- Utiliza giros y expresiones naturales del habla española/valenciana ("mare de déu", "escúchame una cosa", "xe", "por favor venid", "se lo está tragando", "se va la cobertura").
- Incorpora acotaciones de audio coherentes entre corchetes cuando sea pertinente: [pitido], [estática], [crujido de madera], [gritos de fondo], [respiración entrecortada], [agua torrencial], [corte].

Reglas estrictas de formato:
- Si el tipo es 'monologo_centralita': Devuelve ÚNICAMENTE un string de texto continuo (lo que grita, balbucea o dice el ciudadano al buzón/contestador saturado). NADA DE JSON, SOLO EL TEXTO DEL CIUDADANO.
- Si el tipo es 'dialogo_operador': Devuelve ÚNICAMENTE un array JSON válido con la conversación entre el llamante y el operador del 112.
  Ejemplo:
  [
    {"hablante": "operador", "texto": "112 Emergencias, dígame."},
    {"hablante": "llamante", "texto": "¡Por favor, el agua acaba de reventar la puerta del bajo en Massanassa!"},
    {"hablante": "operador", "texto": "¿Hay personas mayores o niños con usted?"}
  ]
No incluyas explicaciones adicionales, ni introducciones ni bloques markdown como ```json o ```text. Devuelve únicamente el contenido bruto.
"""

SCENARIOS_CRITICA = [
    "Persona de edad avanzada subida al capó de un vehículo con la corriente arrastrando coches a su alrededor.",
    "Familia con bebés atrapados en una planta baja donde el agua supera ya los dos metros y solo queda un altillo estrecho.",
    "Conductor atrapado en un túnel o paso subterráneo anegado con el agua cubriendo las ventanillas.",
    "Derrumbe parcial de vivienda antigua en planta baja; personas atrapadas bajo escombros con agua en ascenso continuo.",
    "Mujer embarazada sola en bajo comercial mientras la persiana metálica cede ante el empuje de la corriente de fango.",
    "Personas refugiadas en un tejado de chapa que empieza a doblarse por la fuerza de la corriente y troncos arrastrados.",
    "Persona dependiente electro-asistida (oxígeno/respirador) en planta baja que se ha quedado sin luz y el agua entra a borbotones.",
    "Joven atrapado en su vehículo con las puertas bloqueadas por la presión del agua, que ya le llega al pecho.",
    "Vecinos alertando de gritos de auxilio en un garaje subterráneo inundado tras bajar a retirar vehículos.",
    "Residencia de ancianos o centro de día con la planta baja inundada y pacientes en sillas de ruedas sin movilidad."
]

SCENARIOS_URGENTE = [
    "Vecinos aislados en primer piso con portal anegado, sin luz ni agua y un enfermo crónico que requiere medicación.",
    "Refugio o clínica veterinaria con animales en jaulas y agua a 70 cm en ascenso.",
    "Grupo de trabajadores atrapados en la planta alta de una nave del polígono, sin peligro inmediato pero incomunicados.",
    "Comunidad de vecinos con grietas estructurales severas en la fachada tras el embate de vehículos arrastrados.",
    "Turismo inmovilizado en una balsa de agua de 40 cm; ocupantes no pueden salir pero no hay corriente de arrastre.",
    "Avería grave en caja de contadores semisumergida con chispazos eléctricos continuos y olor a humo o gas.",
    "Vivienda anegada por lodo con pérdidas materiales totales pero residentes a salvo en terraza comunitaria."
]

SCENARIOS_RUIDO = [
    "Llamada que se corta tras pocos segundos debido a pérdida severa de cobertura en la zona.",
    "Llamada accidental de bolsillo donde se percibe ambiente de lluvia torrencial y voces de fondo.",
    "Vecino indignado exigiendo saber cuándo restablecerán el suministro eléctrico o la cobertura móvil.",
    "Ciudadano preguntando si mañana abrirán colegios, comercios o si circularán trenes de cercanías.",
    "Pregunta impertinente sobre trámites con el seguro o el Consorcio por daños en chapa por granizo.",
    "Consulta por contenedores de basura desplazados o ramas caídas en calles sin riesgo de inundación."
]


def build_prompt_payload(categoria: str, tipo_transcripcion: str, town: str = "Valencia") -> Dict[str, Any]:
    """Construye el payload para llamadas con LLM garantizando la inyección del municipio asignado."""
    if categoria == "critica":
        escenario = random.choice(SCENARIOS_CRITICA)
        instruccion = (
            f"SITUACIÓN CRÍTICA (RIESGO VITAL INMINENTE) localizada estrictamente en {town}: {escenario}. "
            f"El llamante está en peligro de muerte inmediata. Debe mencionar de forma explícita que se encuentra en {town}."
        )
    elif categoria == "urgente":
        escenario = random.choice(SCENARIOS_URGENTE)
        instruccion = (
            f"SITUACIÓN URGENTE (DAÑOS GRAVES O ASISTENCIA) localizada estrictamente en {town}: {escenario}. "
            f"Tensión alta pero sin ahogamiento instantáneo. Debe mencionar claramente el municipio de {town}."
        )
    else:
        escenario = random.choice(SCENARIOS_RUIDO)
        instruccion = (
            f"LLAMADA DE RUIDO O SATURACIÓN en el municipio de {town}: {escenario}. "
            f"Consulta no urgente, corte o queja. Debe situarse en {town}."
        )

    if tipo_transcripcion == "monologo_centralita":
        tipo_inst = (
            "La centralita está saturada: salta el contestador o buzón directo. "
            "Devuelve ÚNICAMENTE el texto que pronuncia el ciudadano, sin JSON ni encabezados."
        )
    else:
        tipo_inst = (
            "Llamada atendida por un operador del 112. "
            "Devuelve un array JSON válido con los turnos de diálogo entre 'operador' y 'llamante'."
        )

    seed_entropy = random.randint(1000, 9999)
    user_message = (
        f"{instruccion}\nModalidad: {tipo_inst}\n"
        f"[IMPORTANTE: Haz este diálogo completamente único, distintivo e irrepetible. Localización obligatoria: {town}. Entropía: #{seed_entropy}]"
    )

    return {
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_message}
        ]
    }


# =====================================================================
# GENERADORES PROCEDIMENTALES LOCALES (FAKER + ANTI-CLONADO + INYECCIÓN)
# =====================================================================

def _random_street() -> str:
    """Genera un nombre de vía realista en español."""
    tipo = random.choice(["calle", "calle", "avenida", "camino", "plaza", "travesía", "paseo"])
    nombre = fake.street_name()
    num = random.randint(1, 160)
    return f"{tipo} {nombre}, número {num}"


def _random_audio_tag() -> str:
    """Genera una acotación sonora realista contextual."""
    tags = [
        "[gritos de auxilio y agua torrencial]",
        "[crujidos de madera y corriente violenta]",
        "[respiración entrecortada y llantos]",
        "[sonido de persiana metálica golpeada por el agua]",
        "[golpes secos contra el techo y estática]",
        "[pitido agudo de línea telefónica saturada]",
        "[sonido de cristales rompiéndose y corriente]",
        "[viento huracanado y estática intermitente]",
        "[gritos desesperados de fondo y corte brusco]",
        "[bocinas de coches sonando de forma continua]"
    ]
    return random.choice(tags)


def generate_critica_monologue(town: str) -> str:
    """Genera un monólogo procedimental único para situación crítica con inyección de town."""
    street = _random_street()
    name = fake.first_name()
    relative = random.choice([
        f"mi madre de {random.randint(70, 92)} años",
        f"mi padre de {random.randint(72, 89)} años",
        f"mi hijo pequeño",
        f"un bebé de {random.randint(2, 18)} meses",
        f"mi marido",
        f"mi mujer",
        f"mi vecina impedida"
    ])
    water_level = random.choice([
        f"más de {random.randint(180, 240)} centímetros",
        "por el cuello",
        "por encima del pecho",
        "rozando el techo del bajo",
        "más de dos metros"
    ])
    exclamation = random.choice([
        "¡Por el amor de Dios!", "¡Mare de Déu!", "¡Por favor, socorro!",
        "¡Nos estamos ahogando!", "¡Ayuda urgente!", "¡No podemos salir!"
    ])
    tag = _random_audio_tag()

    archetype = random.randint(1, 7)

    if archetype == 1:
        return (
            f"¡{exclamation}! ¡Estamos en {town}, en {street}! ¡El agua nos llega {water_level}! "
            f"¡Tengo a {relative} encima de una mesa que ya está flotando! ¡La corriente ha reventado la puerta de entrada y entra fango sin parar! "
            f"¡Me llamo {name}, por favor mandad a los bomberos a {town} que nos morimos aquí dentro! {tag}"
        )
    elif archetype == 2:
        return (
            f"¡Socorro, 112! ¡Estoy en {town}, en {street}! ¡Soy {name} y la riada se ha llevado mi coche, estoy subido al techo! "
            f"¡El agua cubre {water_level} y la corriente tira con una fuerza descomunal! ¡Hay troncos y contenedores chocando contra el vehículo! "
            f"¡No sé cuánto más podré aguantar agarrado, me resbalo! ¡{exclamation}! {tag}"
        )
    elif archetype == 3:
        people_count = random.randint(3, 8)
        return (
            f"¡Auxilio! ¡Somos {people_count} personas en el tejado de una vivienda en {town}, {street}! ¡Me llamo {name}! "
            f"¡El agua ya ha sumergido toda la planta baja y el primer piso! ¡El muro lateral ha colapsado hace diez minutos! "
            f"¡Tenemos a {relative} con hipotermia severa y no para de llover! ¡Que venga un helicóptero a {town} inmediatamente! {tag}"
        )
    elif archetype == 4:
        return (
            f"¡Emergencias, por favor! ¡Llamo desesperado desde {town}, en {street}! ¡Soy {name} y {relative} está con oxígeno, el generador acaba de morir bajo el agua! "
            f"¡El agua sube {random.randint(5, 20)} centímetros por minuto y ya cubre las camas! ¡No podemos moverlo en brazos por la corriente! "
            f"¡Necesitamos una lancha o rescate médico en {town} ya, se nos asfixia! {tag}"
        )
    elif archetype == 5:
        return (
            f"¡{exclamation}! ¡Ha cedido la compuerta del garaje en {town}, {street}! ¡Soy {name} y bajó {relative} a sacar el coche, el fango ha sellado el portón! "
            f"¡El sótano está totalmente anegado hasta el dintel! ¡Oigo golpes desesperados desde dentro pero no abre la puerta! "
            f"¡Traigan equipo pesado a {town}, por favor! {tag}"
        )
    elif archetype == 6:
        return (
            f"¡112, no me cuelguen! ¡Estoy enganchado a una verja en {town}, cerca de {street}! "
            f"¡El torrente me ha arrancado la ropa y la corriente me lleva las piernas! ¡Tengo las manos congeladas y no hago pie! "
            f"¡{name} es mi nombre! ¡Ayuda en {town}, me suelto, me suelto! {tag}"
        )
    else:
        return (
            f"¡Tragedia en {town}! ¡El barranco ha desbordado en {street}! ¡Soy {name} y la pared maestra de la casa acaba de caerse entera! "
            f"¡{relative} ha quedado atrapado bajo los escombros y el agua sube con fuerza negra! ¡Apenas saca la cabeza para respirar! "
            f"¡{exclamation}! ¡Venid a {town} antes de que se tape del todo! {tag}"
        )


def generate_critica_dialogue(town: str) -> List[Dict[str, str]]:
    """Genera un diálogo procedimental de alta tensión para situación crítica."""
    street = _random_street()
    name = fake.first_name()
    op_greet = random.choice([
        "112 Emergencias Valencia, ¿cuál es su urgencia?",
        "112 Emergencias, dígame.",
        "Centro de Emergencias 112, indique su localización exacta."
    ])
    relative = random.choice(["mi madre", "mis hijos", "mi marido", "mi abuelo enfermo", "un bebé"])
    water_cm = random.randint(160, 230)

    variant = random.randint(1, 4)

    if variant == 1:
        return [
            {"hablante": "operador", "texto": op_greet},
            {"hablante": "llamante", "texto": f"¡Por favor, manden a los bomberos a {town}! ¡Estamos atrapados en {street} y el agua supera {water_cm} centímetros en la planta baja!"},
            {"hablante": "operador", "texto": f"Tranquilícese, le escucho. ¿Tienen posibilidad de subir a una planta superior o a la terraza del edificio en {town}?"},
            {"hablante": "llamante", "texto": f"¡No! ¡La escalera comunitaria está colapsada por el agua y no podemos salir! ¡Tengo a {relative} sobre los hombros y el agua sigue subiendo!"},
            {"hablante": "operador", "texto": f"Mantenga a {relative} lo más alto posible sobre muebles o altillos. No intente salir a la corriente de la calle bajo ningún concepto. Doy aviso de prioridad máxima a las unidades de rescate en {town}."},
            {"hablante": "llamante", "texto": f"¡Dense prisa por Dios, la luz se ha ido y el agua entra a presión por las ventanas! ¡Soy {name}!"},
            {"hablante": "operador", "texto": "Su aviso está cursado con código rojo. Permanezcan agrupados y aguanten, los equipos están intentando acceder."},
            {"hablante": "llamante", "texto": "[Crujido violento de la puerta cediendo y gritos de socorro. Se interrumpe la comunicación]"}
        ]
    elif variant == 2:
        veh = random.choice(["furgoneta", "coche", "turismo", "camioneta"])
        return [
            {"hablante": "operador", "texto": op_greet},
            {"hablante": "llamante", "texto": f"¡Socorro! ¡Soy {name} y estoy subido al techo de mi {veh} en {town}, en {street}! ¡La corriente del agua se está llevando los coches alrededor!"},
            {"hablante": "operador", "texto": f"Cálmese señor/a, no se tire al agua. ¿Tiene algún punto de amarre fijo o edificación donde agarrarse en esa zona de {town}?"},
            {"hablante": "llamante", "texto": f"¡No hay nada cerca, solo agua torrencial y ramas! ¡El {veh} empieza a cabecear por la fuerza de la riada!"},
            {"hablante": "operador", "texto": "Estamos triangulando su posición por la antena. Agárrese con firmeza y hágase visible. Los servicios de rescate están desplegados en la zona."},
            {"hablante": "llamante", "texto": "¡Tengo las piernas sin fuerza por el agua helada! ¡Venid ya, por favor!"}
        ]
    elif variant == 3:
        people = random.randint(3, 6)
        return [
            {"hablante": "operador", "texto": op_greet},
            {"hablante": "llamante", "texto": f"¡Emergencias! ¡El agua ha roto la persiana de nuestra vivienda en {town}, calle {street}! ¡Soy {name} y {relative} no puede caminar, está en cama sumergida!"},
            {"hablante": "operador", "texto": f"¿Cuántas personas se encuentran dentro de la vivienda en {town} ahora mismo?"},
            {"hablante": "llamante", "texto": f"¡Somos {people} personas! ¡El nivel del agua sube muy rápido, ya pasa de la cintura!"},
            {"hablante": "operador", "texto": "Coloquen mantas y sostengan a la persona impedida sobre colchones o mesas altas. Despacho lancha de evacuación hacia su dirección."},
            {"hablante": "llamante", "texto": "¡Rápido, que los cristales del fondo acaban de estallar por la presión del fango! [Llantos de fondo]"}
        ]
    else:
        minors = random.randint(1, 3)
        return [
            {"hablante": "operador", "texto": op_greet},
            {"hablante": "llamante", "texto": f"¡Auxilio en {town}! ¡El tejado donde nos hemos refugiado en {street} está cediendo por el peso del agua y la caída de un árbol! ¡Me llamo {name}!"},
            {"hablante": "operador", "texto": "¿Están en peligro de caída inmediata? ¿Hay menores con ustedes?"},
            {"hablante": "llamante", "texto": f"¡Sí, hay {minors} niños y la viga central está rajada! ¡Si cede caemos directos a la corriente que arrastra la calle!"},
            {"hablante": "operador", "texto": f"Repartan el peso lejos de la viga fracturada y permanezcan agachados. Notifico inmediatamente a los equipos de rescate aéreo y terrestre en {town}."},
            {"hablante": "llamante", "texto": "¡Por favor, no tarden que esto va a romper! ¡Ayuda!"}
        ]


def generate_urgente_monologue(town: str) -> str:
    """Genera un monólogo procedimental único para situación urgente con inyección de town."""
    street = _random_street()
    name = fake.first_name()
    hours = random.randint(3, 16)
    cm = random.randint(40, 95)
    people = random.randint(4, 15)

    archetype = random.randint(1, 6)

    if archetype == 1:
        return (
            f"Buenas tardes, grabo este mensaje para el 112. Soy {name}, estamos aislados en el primer piso en {town}, en {street}. "
            f"El portal tiene {cm} centímetros de lodo acumulado y las puertas no abren. Llevamos {hours} horas sin luz eléctrica ni agua corriente. "
            f"En la vivienda somos {people} personas y tenemos a una persona mayor que necesita medicación para el corazón. "
            f"No corremos riesgo de ahogarnos arriba, pero necesitamos suministros y evacuación cuando puedan acceder a {town}."
        )
    elif archetype == 2:
        return (
            f"Aviso urgente para los bomberos en {town}. Soy {name}, residente en {street}. Tras la fuerza del agua de esta tarde, han aparecido grietas enormes en el muro de carga. "
            f"Varios coches arrastrados han chocado contra la fachada y tememos que el edificio no sea seguro. "
            f"Estamos {people} vecinos refugiados en la azotea esperando que alguien técnico venga a revisar la estructura de la finca en {town}."
        )
    elif archetype == 3:
        return (
            f"Llamo desde {town}, calle {street}. Me llamo {name}. El agua en la calle está a medio metro pero la caja general de contadores del edificio está echando chispas "
            f"y hay un olor penetrante a gas o plástico quemado en todo el hueco de la escalera. "
            f"Nos da pánico que salte una chispa y haya una explosión. Por favor, avisen a la compañía y a bomberos para cortar la acometida en {town}."
        )
    elif archetype == 4:
        return (
            f"Hola, soy {name}, aviso de dos personas atrapadas en vehículo en {town}, en la rotonda cerca de {street}. "
            f"El coche ha quedado calado y atascado en una balsa de {cm} cm de barro. No hay corriente violenta que nos arrastre, "
            f"pero el agua cubre los escapes y las puertas están trabadas por el fango. Estamos empapados y hace mucho frío. Por favor, auxilio en carretera en {town}."
        )
    elif archetype == 5:
        animals = random.randint(12, 35)
        return (
            f"Urgencia para Protección Civil en {town}. Soy {name}, en las instalaciones con {animals} animales cercanas a {street}. "
            f"El agua inunda la planta a {cm} centímetros. Hemos logrado subir a los animales a jaulas altas pero si vuelve a llover con fuerza no aguantarán. "
            f"Nosotros estamos en el altillo a salvo pero necesitamos apoyo logístico o furgonetas altas en {town}."
        )
    else:
        return (
            f"Mensaje para emergencias desde {town}. En {street}, una pared medianera de una nave antigua se ha derrumbado sobre el callejón. "
            f"No hay heridos directos pero ha dejado bloqueada la única salida de tres familias que residen al fondo. "
            f"El nivel del agua no sube ahora mismo pero están totalmente incomunicados. Mi nombre es {name}, rogamos despeje de paso."
        )


def generate_urgente_dialogue(town: str) -> List[Dict[str, str]]:
    """Genera un diálogo procedimental para situación urgente."""
    street = _random_street()
    name = fake.first_name()
    hours = random.randint(4, 18)
    cm = random.randint(50, 90)

    variant = random.randint(1, 3)

    if variant == 1:
        return [
            {"hablante": "operador", "texto": "112 Emergencias, dígame."},
            {"hablante": "llamante", "texto": f"Hola, buenas tardes. Llamo desde {town}, en {street}. El agua en la calle nos llega a las rodillas y ha anegado los bajos."},
            {"hablante": "operador", "texto": f"¿Hay alguna persona atrapada en zonas sumergidas o con riesgo vital en {town}?"},
            {"hablante": "llamante", "texto": f"No, afortunadamente todos los vecinos hemos subido al segundo piso, pero llevamos {hours} horas sin luz y hay un vecino diabético sin insulina que empieza a encontrarse mareado."},
            {"hablante": "operador", "texto": f"Entendido. Mantengan al paciente abrigado e hidratado en la zona alta. Registro el aviso médico prioritario para las brigadas de {town}."},
            {"hablante": "llamante", "texto": f"Muchas gracias. Nos llamamos familia {name}. Esperamos aquí dentro."}
        ]
    elif variant == 2:
        tree = random.choice(["Un pino de gran tamaño", "Una palmera del parque", "Un árbol de ramas gruesas", "Un poste con ramas"])
        return [
            {"hablante": "operador", "texto": "112 Emergencias Valencia, dígame."},
            {"hablante": "llamante", "texto": f"Mire, llamo desde {town}, en {street}. Soy {name}. {tree} ha caído contra el tendido eléctrico y está tocando el agua de la acera."},
            {"hablante": "operador", "texto": "¿Observa chispas continuas o humo en el agua?"},
            {"hablante": "llamante", "texto": "Sí, chisporrotea de vez en cuando y la gente en los balcones tiene miedo de que alguien que intente cruzar se electrocute."},
            {"hablante": "operador", "texto": f"Adviertan a los vecinos desde las ventanas que nadie pise el agua bajo ningún concepto. Paso aviso urgente a la compañía eléctrica y a policía local de {town} para acordonar."},
            {"hablante": "llamante", "texto": "De acuerdo, así lo hacemos. Gracias por la atención."}
        ]
    else:
        veh = random.choice(["turismo", "coche familiar", "furgoneta", "vehículo"])
        return [
            {"hablante": "operador", "texto": "112 Emergencias, dígame su consulta o emergencia."},
            {"hablante": "llamante", "texto": f"Soy {name}, estamos atrapados en nuestro {veh} en {town}, en {street}. Hay unos {cm} centímetros de balsa y el motor se ha parado."},
            {"hablante": "operador", "texto": "¿La corriente de agua tiene fuerza suficiente para desplazar el coche?"},
            {"hablante": "llamante", "texto": "No, está estancada pero no podemos abrir las puertas porque el agua llega a la mitad y somos dos personas mayores."},
            {"hablante": "operador", "texto": f"Permanezcan sentados con los cinturones abrochados y las luces de emergencia puestas. Movilizo una patrulla o grúa pesada asignada al sector de {town}."},
            {"hablante": "llamante", "texto": "Entendido agente, esperamos aquí sin movernos."}
        ]


def generate_ruido_monologue(town: str) -> str:
    """Genera un monólogo procedimental único para llamadas de ruido/saturación con inyección de town."""
    street = _random_street()
    name = fake.first_name()
    hours = random.randint(4, 28)
    archetype = random.randint(1, 6)

    if archetype == 1:
        service = random.choice([
            "suministro eléctrico ni agua potable",
            "conexión a internet ni telefonía móvil",
            "agua corriente en los grifos",
            "luz en todo el barrio"
        ])
        complaint = random.choice([
            f"¡Se me va a estropear toda la compra del frigorífico valorada en más de {random.randint(150, 400)} euros!",
            f"¡Tengo que teletrabajar y no sé a qué hora van a reparar la línea!",
            f"¡Llevamos desde las {random.randint(6, 12)} de la mañana esperando a los técnicos y no aparece nadie!",
            f"¡Es inaceptable que en pleno siglo XXI estemos incomunicados en {town}!"
        ])
        return (
            f"Llamo muy indignado desde {town}, en {street}. Mi nombre es {name}. Llevamos ya {hours} horas sin {service}. {complaint} "
            f"Exijo que pasen aviso urgente a la empresa responsable para que den una solución en {town}."
        )
    elif archetype == 2:
        dest = random.choice(["los colegios e institutos", "el centro de salud", "los supermercados", "la guardería municipal", "las oficinas bancarias"])
        time_slot = random.choice(["a primera hora de la mañana", "durante el turno de tarde", "a lo largo del día de mañana"])
        return (
            f"Hola, buenas tardes. Les llamo desde {town}, en {street}. Me llamo {name}. Quería hacer una consulta porque no me queda claro si {time_slot} abrirán {dest} "
            f"en {town} o si el autobús hacia Valencia prestará servicio. Mi empresa me exige un justificante si no acudo al trabajo."
        )
    elif archetype == 3:
        car = random.choice(["Seat Ibiza", "Ford Focus", "Renault Megane", "Peugeot 208", "furgoneta Citroën", "Volkswagen Golf", "turismo Toyota", "Nissan Qashqai"])
        damage = random.choice([
            "varios impactos considerables por el granizo y barro acumulado en los bajos",
            "el retrovisor partido y ramas caídas sobre el techo",
            "la chapa abollada y los neumáticos cubiertos de fango"
        ])
        return (
            f"Mire, llamo desde {town}. Tengo un {car} estacionado en {street} y la tormenta le ha provocado {damage}. "
            f"Soy {name} y quisiera saber si desde el 112 me facilitan algún número de atestado o si debo acudir directamente al Consorcio de Compensación de Seguros."
        )
    elif archetype == 4:
        other_name = fake.first_name()
        seconds = random.randint(3, 12)
        ambient_phrase = random.choice([
            f"'Oye {other_name}, mira cómo baja el agua por {street}, no cruces por ahí'",
            f"'¡{other_name}, ayúdame a poner las maderas en el portal de {street}!'",
            f"'Dile a {other_name} que desconecte los enchufes de la planta baja'",
            f"'¡{other_name}, cuidado con la corriente que viene de {street}!'",
            f"'Oye {other_name}, sube los animales al primer piso rápido'",
            f"'¡{other_name}, el agua está entrando por la rejilla del garaje en {street}!'"
        ])
        return (
            f"[Sonido ambiental de lluvia torrencial y pasos acelerados sobre charcos en {town}. "
            f"Se escucha una voz que dice: {ambient_phrase}. "
            f"Roce continuo del terminal en el bolsillo, marcación involuntaria y corte de llamada tras {seconds} segundos]"
        )
    elif archetype == 5:
        cut_phrase = random.choice([
            "¡se entrecorta muchísimo y apenas escucho!",
            "¡no sé si me reciben, se va la señal de golpe!",
            "¡la cobertura va y viene por la tormenta!",
            "¡se corta la voz y hay mucho ruido de viento!"
        ])
        return (
            f"¿Hola? ¿Emergencias 112? Oiga... llamo desde {town}, en {street}. Soy {name}... {cut_phrase} "
            f"¿Me escuchan? [Estática persistente de red celular, chasquidos de línea colapsada y pitido de fin de llamada a los {random.randint(3, 9)} segundos]"
        )
    else:
        obstacle = random.choice([
            "dos contenedores de basura volcados en medio de la calzada",
            "varias ramas de gran tamaño bloqueando el carril derecho",
            "vallas metálicas de obra caídas sobre la acera",
            "unas chapas sueltas que golpean contra el suelo por el viento"
        ])
        return (
            f"Llamo para dar un aviso desde {town}. En {street} hay {obstacle}. "
            f"No hay ninguna inundación grave pero estorba el paso y los vehículos tienen que esquivarlo. Mi nombre es {name}."
        )


def generate_ruido_dialogue(town: str) -> List[Dict[str, str]]:
    """Genera un diálogo procedimental para llamadas de ruido o no emergencias."""
    street = _random_street()
    name = fake.first_name()
    variant = random.randint(1, 4)

    if variant == 1:
        road = random.choice(["la CV-36", "la CV-400", "la autovía A-3", "la V-30", "la carretera comarcal hacia Valencia"])
        vehicle = random.choice(["furgoneta de trabajo", "camión ligero", "vehículo particular", "coche"])
        return [
            {"hablante": "operador", "texto": "112 Emergencias, dígame."},
            {"hablante": "llamante", "texto": f"Buenas tardes, soy {name}. Quería consultar si {road} a la altura de {town} está transitable para salir con mi {vehicle}."},
            {"hablante": "operador", "texto": f"Señor/a, el 112 atiende rescates y emergencias con riesgo vital. Para la viabilidad de carreteras en {town} debe consultar la web de la DGT o el 012."},
            {"hablante": "llamante", "texto": "Disculpen, no pretendía entorpecer el servicio. Miro el boletín oficial de tráfico."},
            {"hablante": "operador", "texto": "Muchas gracias por colaborar. Mantenga las líneas despejadas."}
        ]
    elif variant == 2:
        hours = random.randint(5, 24)
        appliance = random.choice([
            f"toda la comida congelada valorada en {random.randint(100, 300)} euros",
            "los medicamentos que deben conservarse en frío",
            "las bombas de extracción particulares del sótano"
        ])
        return [
            {"hablante": "operador", "texto": "112 Emergencias Valencia, dígame."},
            {"hablante": "llamante", "texto": f"Oiga, llamo desde {town}, en {street}. Me llamo {name}. Llevamos {hours} horas sin suministro eléctrico y se nos va a perder {appliance}. En la compañía eléctrica no atienden."},
            {"hablante": "operador", "texto": f"Entendemos su problema, pero nuestras líneas están coordinando salvamentos en áreas anegadas de {town}. Debe tramitar la incidencia con su distribuidora cuando sea posible."},
            {"hablante": "llamante", "texto": "Comprendo la gravedad, perdonen la insistencia. Espero que se resuelva pronto."},
            {"hablante": "operador", "texto": "Por favor, libere la línea para las urgencias médicas y de bomberos. Gracias."}
        ]
    elif variant == 3:
        signal_sec = random.randint(3, 14)
        landmark = random.choice([f"en {street}", f"cerca de {street}", f"junto a {street}"])
        return [
            {"hablante": "operador", "texto": "112 Emergencias, dígame."},
            {"hablante": "llamante", "texto": f"¿Hola? ¿112? Soy {name}, llamo desde {town}, {landmark}... ¡se entrecorta la señal, no oigo casi nada!"},
            {"hablante": "operador", "texto": f"112 le escucha, indique con claridad si hay heridos o atrapados en {town}."},
            {"hablante": "llamante", "texto": f"[Ruido blanco, chasquidos continuos y voz metálica ininteligible durante {signal_sec} segundos] ... ¡Hola! ¡No hay cobertura! [Corte de señal]"},
            {"hablante": "operador", "texto": "[Llamada concluida automáticamente por caída técnica de antena de telecomunicaciones]"}
        ]
    else:
        facility = random.choice(["los colegios e institutos", "el campus universitario", "las escuelas infantiles", "los centros de formación"])
        return [
            {"hablante": "operador", "texto": "112 Emergencias, dígame."},
            {"hablante": "llamante", "texto": f"Hola, buenas tardes. Soy {name}, desde {street} en {town}. Llamaba para preguntar si mañana se suspenden las clases en {facility} por el temporal."},
            {"hablante": "operador", "texto": f"Las decisiones lectivas para el municipio de {town} se anuncian exclusivamente a través de los canales oficiales del Ayuntamiento y la Conselleria de Educación en redes sociales o radio."},
            {"hablante": "llamante", "texto": "De acuerdo, reviso las cuentas oficiales. Disculpe la molestia."},
            {"hablante": "operador", "texto": "Gracias, buenas tardes."}
        ]


def generate_mock_transcription(categoria: str, tipo_transcripcion: str, town: str = "Valencia") -> str:
    """Genera una transcripción realista procedimental con Faker y semántica de pueblo garantizada."""
    if tipo_transcripcion == "monologo_centralita":
        if categoria == "critica":
            return generate_critica_monologue(town)
        elif categoria == "urgente":
            return generate_urgente_monologue(town)
        else:
            return generate_ruido_monologue(town)
    else:
        if categoria == "critica":
            dialogue = generate_critica_dialogue(town)
        elif categoria == "urgente":
            dialogue = generate_urgente_dialogue(town)
        else:
            dialogue = generate_ruido_dialogue(town)
        return json.dumps(dialogue, ensure_ascii=False)
