"""Plantillas de prompts dinámicos y generador de transcripciones (LLM y Mock Fallback)."""

import json
import random
from typing import Dict, Any, List

# Sistema de instrucciones para el LLM
SYSTEM_PROMPT = """Eres un simulador ultra-realista de llamadas de emergencias al 112 durante la catástrofe de la DANA en Valencia.
Tu objetivo es producir la transcripción textual hiperrealista, caótica y humana de la llamada.
Debes reflejar el acento o expresiones locales valencianas/españolas cuando sea natural ("mare meua", "escúchame", "por favor", "se lo está llevando todo", "el barranco"), respiraciones agitadas, sollozos, ruidos entre corchetes si aplica (ej. [crujido], [llanto], [pitido de corte], [estática]).

Reglas estrictas de formato:
- Si el tipo es 'monologo_centralita': Devuelve ÚNICAMENTE un string de texto continuo (lo que dice el ciudadano ante una centralita saturada o contestador de emergencias). NADA DE JSON, SOLO EL TEXTO DEL CIUDADANO.
- Si el tipo es 'dialogo_operador': Devuelve ÚNICAMENTE un array JSON válido con la conversación entre el llamante y el operador del 112.
  Ejemplo exacto de formato para diálogo:
  [
    {"hablante": "operador", "texto": "112 Emergencias, dígame."},
    {"hablante": "llamante", "texto": "¡Ayuda por favor! ¡El agua nos llega al cuello!"},
    {"hablante": "operador", "texto": "Tranquilo, mantenga la calma. ¿En qué planta se encuentra?"}
  ]
No incluyas explicaciones adicionales, ni introducciones ni bloques markdown como ```json o ```text. Devuelve únicamente el contenido bruto.
"""

SCENARIOS_CRITICA = [
    "Persona atrapada en el techo de un coche mientras la corriente del barranco sube rápidamente.",
    "Familia con dos niños pequeños y un anciano con el agua superando el metro y medio en una planta baja.",
    "Hombre atrapado en un túnel o paso subterráneo dentro de una furgoneta casi sumergida.",
    "Colapso inminente de un muro medianero en una vivienda baja con el agua entrando con violencia.",
    "Persona con movilidad reducida en cama mientras el agua entra por las ventanas y no puede moverse.",
]

SCENARIOS_URGENTE = [
    "Vecino refugiado en el segundo piso, pero con el garaje inundado y teme que ceda la estructura del edificio.",
    "Dueña de un bajo comercial con varios perros y gatos atrapados en un altillo, pidiendo rescate.",
    "Coche averiado en medio de una calle con medio metro de agua, sin corriente fuerte pero no puede abrir la puerta.",
    "Comunidad de vecinos con personas mayores en un primer piso sin luz, sin agua potable y medicación agotándose.",
    "Comercio inundado, el dueño pide ayuda para evitar saqueos o evaluar daños materiales.",
]

SCENARIOS_RUIDO = [
    "Llamada muda donde solo se escucha estática, respiración agitada y un corte abrupto a los 3 segundos.",
    "Vecino muy enfadado llamando al 112 para quejarse de que se ha ido la luz en toda la calle y se le descongela la carne.",
    "Persona preguntando al 112 si mañana habrá autobuses o metro para ir a trabajar a Valencia.",
    "Usuario preguntando qué papeles necesita presentar al Consorcio de Compensación de Seguros por su coche.",
    "Llamada de 2 segundos donde alguien dice '¿Hola? ¿Es el 112? Se me corta...' y cuelga.",
    "Insultos al operador por la tardanza de las alertas de Protección Civil en sonar en los móviles.",
]


def build_prompt_payload(categoria: str, tipo_transcripcion: str) -> Dict[str, Any]:
    """Construye las instrucciones específicas para cada registro."""
    if categoria == "critica":
        escenario = random.choice(SCENARIOS_CRITICA)
        instruccion = (
            f"SITUACIÓN CRÍTICA (RIESGO VITAL INMINENTE): {escenario}. "
            f"Tono de pánico extremo, desesperación, agua subiendo velozmente."
        )
    elif categoria == "urgente":
        escenario = random.choice(SCENARIOS_URGENTE)
        instruccion = (
            f"SITUACIÓN URGENTE (DAÑOS MATERIALES / RESCATE PREVENTIVO): {escenario}. "
            f"Tono de angustia y nerviosismo, pero sin riesgo inminente de ahogamiento en este segundo."
        )
    else:  # ruido
        escenario = random.choice(SCENARIOS_RUIDO)
        instruccion = (
            f"LLAMADA DE RUIDO / SATURACIÓN: {escenario}. "
            f"Puede ser un corte rápido de pocos segundos, una queja administrativa, o una llamada inoportuna."
        )

    if tipo_transcripcion == "monologo_centralita":
        tipo_inst = (
            "El servicio 112 está saturado. El llamante habla desesperado a un buzón/centralita automática. "
            "Devuelve únicamente el texto continuo de lo que grita o dice el ciudadano."
        )
    else:
        tipo_inst = (
            "La llamada ha sido atendida por un operador del 112. "
            "Devuelve un array JSON con el diálogo entre 'operador' y 'llamante'."
        )

    user_message = f"{instruccion}\nModalidad: {tipo_inst}"
    return {
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_message}
        ]
    }


# Fallback / Mock Generator para pruebas rápidas y funcionamiento sin cuotas de LLM
MOCK_MONOLOGUES_CRITICA = [
    "¡Por favor! ¡Que alguien venga! ¡El agua nos llega por el cuello en el bajo! ¡Mis hijos están encima del armario! ¡Se va la luz, mare de Déu, ayudaaaa! [Gritos de fondo y corte]",
    "¡Socorro! ¡Estoy encima de la furgoneta en la rotonda! ¡La riada se está llevando los coches! ¡No puedo aguantar más la fuerza del agua! ¡Por favor mandad un helicóptero!",
    "¡112 por favor cogedlo! ¡Ha caído la pared del patio y está entrando todo el barro de golpe! ¡Mi madre no puede caminar! ¡Estamos en el altillo atrapados!",
]

MOCK_MONOLOGUES_URGENTE = [
    "Miren, llamo porque tengo el bajo del negocio anegado con medio metro de agua. No corre peligro mi vida pero esto sigue entrando por la puerta. ¿Va a venir alguna patrulla a cortar la calle?",
    "Hola, estamos en el segundo piso, de momento estamos bien de agua pero hay un coche flotando en la puerta que está golpeando la finca. Necesitamos que lo tengan en cuenta cuando puedan.",
    "Oigan, en la calle Mayor tenemos a tres perros atrapados en una caseta del patio. El agua no sube más pero no podemos llegar a ellos. Avísenme si viene Protección Civil.",
]

MOCK_MONOLOGUES_RUIDO = [
    "[Estática] ... ¿Hola? ¿Hay alguien ahí? ... [Corte de llamada]",
    "Llamo para protestar porque llevamos cuatro horas sin luz en el barrio. ¡Esto es una vergüenza, que me voy a perder todo lo que tengo en el congelador!",
    "Buenas tardes, ¿saben si mañana va a funcionar la línea 1 de metro o estará cortada? Es que tengo turno a las siete.",
    "[Silencio prolongado] ... [Respiración agitada] ... [Ruido sordo de caída y pitido de desconexión]",
    "¿Oiga? ¿El consorcio de seguros se encarga si me ha entrado agua en el maletero? Porque mi aseguradora no me contesta.",
    "¡Son unos sinvergüenzas! ¡La alarma ha sonado cuando ya teníamos el agua hasta las rodillas! ¡Dimisión es lo que tenéis que hacer!",
]

MOCK_DIALOGUES_CRITICA = [
    [
        {"hablante": "operador", "texto": "112 Emergencias Valencia, dígame."},
        {"hablante": "llamante", "texto": "¡Ayuda por favor! ¡El agua está entrando por las ventanas y estamos atrapados!"},
        {"hablante": "operador", "texto": "Tranquilicese, mantenga la calma. ¿Tienen acceso a un piso superior o terraza?"},
        {"hablante": "llamante", "texto": "¡No, es una planta baja! ¡El agua nos llega al pecho ya!"},
        {"hablante": "operador", "texto": "Suban sobre mesas o encimeras inmediatamente. Priorizo su aviso a rescate acuático. No cuelgue."},
        {"hablante": "llamante", "texto": "¡Rápido por favor, que se apagan las luces!"}
    ],
    [
        {"hablante": "operador", "texto": "112 Emergencias, ¿cuál es su emergencia?"},
        {"hablante": "llamante", "texto": "¡Estoy subido al techo de mi coche! ¡La corriente del barranco me está arrastrando!"},
        {"hablante": "operador", "texto": "Señor, no intente nadar en la corriente. Agárrese con fuerza a cualquier punto fijo si puede."},
        {"hablante": "llamante", "texto": "¡No hay nada! ¡Solo coches flotando! ¡Por favor venid ya!"},
        {"hablante": "operador", "texto": "Estamos triangulando su posición. Manténgase visible y sujeto al vehículo."}
    ]
]

MOCK_DIALOGUES_URGENTE = [
    [
        {"hablante": "operador", "texto": "112 Emergencias."},
        {"hablante": "llamante", "texto": "Buenas noches, mire, tenemos el garaje comunitario completamente inundado con dos metros."},
        {"hablante": "operador", "texto": "¿Hay alguna persona atrapada dentro del garaje o en peligro?"},
        {"hablante": "llamante", "texto": "No, que sepamos no, solo los vehículos. Pero el agua está empezando a filtrar al portal."},
        {"hablante": "operador", "texto": "De acuerdo. Nadie debe bajar al sótano bajo ningún concepto. Anoto la incidencia con prioridad técnica."}
    ],
    [
        {"hablante": "operador", "texto": "112 Emergencias, dígame."},
        {"hablante": "llamante", "texto": "Hola, estoy en mi casa en una primera planta. El agua está en el portal y no puedo salir."},
        {"hablante": "operador", "texto": "¿Está subiendo el agua a su vivienda?"},
        {"hablante": "llamante", "texto": "No, está estancada abajo, pero no tengo comida ni luz."},
        {"hablante": "operador", "texto": "Permanezca en la planta alta y no intente cruzar el agua. Los equipos de auxilio están en la zona priorizando rescates vitales."}
    ]
]

MOCK_DIALOGUES_RUIDO = [
    [
        {"hablante": "operador", "texto": "112 Emergencias, dígame."},
        {"hablante": "llamante", "texto": "Mire, es que no tenemos luz en toda la manzana y la nevera se va a estropear."},
        {"hablante": "operador", "texto": "Caballero, esta línea es exclusivamente para emergencias con riesgo para las personas. Contacte con su compañía eléctrica."},
        {"hablante": "llamante", "texto": "¡Pero es que nadie coge el teléfono allí!"},
        {"hablante": "operador", "texto": "Debo liberar la línea para llamadas vitales. Buenas noches. [Cuelga]"}
    ],
    [
        {"hablante": "operador", "texto": "112 Emergencias, dígame."},
        {"hablante": "llamante", "texto": "¿Oiga? ¿Mañana abren los colegios o qué hacemos?"},
        {"hablante": "operador", "texto": "Señora, sigan los canales oficiales de la Generalitat. Por favor mantenga la línea despejada."},
        {"hablante": "llamante", "texto": "Vaya atención... [Corte]"}
    ]
]


def generate_mock_transcription(categoria: str, tipo_transcripcion: str) -> str:
    """Genera una transcripción realista prefabricada (para pruebas rápidas sin coste de LLM)."""
    if tipo_transcripcion == "monologo_centralita":
        if categoria == "critica":
            return random.choice(MOCK_MONOLOGUES_CRITICA)
        elif categoria == "urgente":
            return random.choice(MOCK_MONOLOGUES_URGENTE)
        else:
            return random.choice(MOCK_MONOLOGUES_RUIDO)
    else:
        # Diálogo devuelto como string JSON
        if categoria == "critica":
            dialogo = random.choice(MOCK_DIALOGUES_CRITICA)
        elif categoria == "urgente":
            dialogo = random.choice(MOCK_DIALOGUES_URGENTE)
        else:
            dialogo = random.choice(MOCK_DIALOGUES_RUIDO)
        return json.dumps(dialogo, ensure_ascii=False)
