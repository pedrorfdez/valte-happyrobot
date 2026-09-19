"""Configuración global para la generación sintética de llamadas al 112 (DANA Valencia)."""

import os
from dotenv import load_dotenv

# Cargar variables de entorno desde .env inmediatamente
load_dotenv()
from dataclasses import dataclass
from typing import Tuple

# Distribución estricta de categorías (15% Críticas, 25% Urgentes, 60% Ruido)
RATIO_CRITICA = 0.15
RATIO_URGENTE = 0.25
RATIO_RUIDO = 0.60

# Probabilidad de que la llamada sea atendida por operador (diálogo) vs saturada (monólogo buzón/centralita)
# En el pico de saturación, muchas quedan como monólogo
RATIO_DIALOGO_OPERADOR = 0.45
RATIO_MONOLOGO_CENTRALITA = 0.55

# Bounding box ampliado de todas las zonas cero reales afectadas por la DANA (Letur, Utiel, Chiva, l'Horta Sud, Algemesí)
LAT_MIN = 38.3000
LAT_MAX = 39.6000
LON_MIN = -2.1500
LON_MAX = -0.3500

# Fecha base para la simulación
SIMULATION_DATE = "2024-12-20"

# Franjas horarias y pesos de intensidad (Simulación de picos, llanos y valles)
# Horarios: (hora_inicio, hora_fin, peso_intensidad)
TIME_SLICES = [
    (8, 13, 0.15),   # Valle matutino: llovizna, pocas alertas
    (13, 16, 0.35),  # Repunte: subida de cauces, primeras incidencias
    (16, 21, 1.00),  # PICO MÁXIMO / COLAPSO: desbordamiento masivo, avalancha de llamadas
    (21, 24, 0.40),  # Valle/Llano nocturno: zonas aisladas, llamadas persistentes
]

# Rangos de duración en segundos según la categoría y tipo
DURATION_RANGES = {
    "ruido_corte": (2, 12),              # Cortes inmediatos, llamadas mudas
    "ruido_admin": (15, 60),             # Preguntas sobre seguros, cortes de luz
    "monologo_saturado": (10, 45),       # Ciudadano hablando desesperado ante la máquina
    "dialogo_urgente": (35, 120),        # Operador recopilando datos de urgencia
    "dialogo_critico": (45, 240),        # Operador gestionando situación de riesgo vital
}

# Configuración del LLM
DEFAULT_MODEL = os.getenv("OPENAI_MODEL", "mixtral-8x7b-32768")
DEFAULT_CONCURRENCY = int(os.getenv("MAX_CONCURRENCY", "2"))
DEFAULT_IMMINENT_CALLS = 100
