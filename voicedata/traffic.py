"""Generador de tráfico, distribución y marcas temporales basadas en T entero."""

import json
import random
import re
from typing import List, Dict, Any

from config import (
    RATIO_CRITICA,
    RATIO_URGENTE,
    RATIO_RUIDO,
    RATIO_DIALOGO_OPERADOR,
)


def calculate_category_distribution(total_calls: int) -> List[str]:
    """Genera la lista exacta de categorías cumpliendo la distribución 15% / 25% / 60%."""
    n_critica = int(round(total_calls * RATIO_CRITICA))
    n_urgente = int(round(total_calls * RATIO_URGENTE))
    n_ruido = total_calls - n_critica - n_urgente

    categories = (
        ["critica"] * n_critica
        + ["urgente"] * n_urgente
        + ["ruido"] * n_ruido
    )
    random.shuffle(categories)
    return categories


def determine_transcription_type(categoria: str) -> str:
    """Determina si la llamada es atendida (diálogo) o desatendida/buzón (monólogo)."""
    if categoria == "ruido":
        # En ruido, muchas son cortes inmediatos o quejas directas al contestador
        return random.choices(
            ["monologo_centralita", "dialogo_operador"],
            weights=[0.70, 0.30],
            k=1
        )[0]
    else:
        # En críticas y urgentes, se simula que algunas logran entrar con operador
        # pero debido al colapso, una parte significativa queda grabada en centralita
        return random.choices(
            ["dialogo_operador", "monologo_centralita"],
            weights=[RATIO_DIALOGO_OPERADOR, 1 - RATIO_DIALOGO_OPERADOR],
            k=1
        )[0]


def sample_start_tick(max_t: int = 1800) -> int:
    """Muestrea un tiempo de inicio T (entero) simulando picos de saturación."""
    # Fases de llegada de llamadas:
    # 1. Inicio del temporal (20% volumen)
    # 2. Pico de desbordamiento y colapso (65% volumen)
    # 3. Llamadas persistentes tardías (15% volumen)
    phases = [
        (1, int(max_t * 0.25), 0.20),
        (int(max_t * 0.25) + 1, int(max_t * 0.75), 0.65),
        (int(max_t * 0.75) + 1, max_t, 0.15),
    ]
    weights = [p[2] for p in phases]
    chosen_phase = random.choices(phases, weights=weights, k=1)[0]
    return random.randint(chosen_phase[0], chosen_phase[1])


def calculate_duration_from_text(
    transcription: str,
    tipo_transcripcion: str,
    categoria: str
) -> int:
    """Calcula la duración en segundos coherente con la longitud real del texto generado.
    
    Aplica una tasa de habla realista (~7-10 caracteres/segundo en situaciones de estrés),
    sumando pausas entre turnos de diálogo y variabilidad estocástica.
    Para llamadas de bolsillo o cortes en categoría ruido, ignora la longitud del texto descriptivo
    y asigna una duración breve coherente (3 a 12 segundos, sincronizada con el texto si lo explicita).
    """
    if categoria == "ruido":
        txt_lower = transcription.lower()
        is_pocket_or_cut = (
            "bolsillo" in txt_lower
            or "marcación involuntaria" in txt_lower
            or "corte de llamada" in txt_lower
            or "pitido de fin de llamada" in txt_lower
            or "caída técnica de antena" in txt_lower
            or "pérdida técnica de señal" in txt_lower
            or "sonido ambiental" in txt_lower
            or "ruido de roce" in txt_lower
        )
        if is_pocket_or_cut:
            # Si el texto describe segundos específicos (ej. "corte de llamada tras 8 segundos"), sincronizar exactamente
            match = re.search(r'(?:tras|a los|durante)\s+(\d+)\s+segundos', transcription, re.IGNORECASE)
            if match:
                return int(match.group(1))
            return random.randint(3, 12)

    text_to_measure = transcription
    turn_pauses = 0

    if tipo_transcripcion == "dialogo_operador":
        try:
            turns = json.loads(transcription)
            if isinstance(turns, list):
                text_to_measure = " ".join(
                    [t.get("texto", "") for t in turns if isinstance(t, dict)]
                )
                turn_pauses = len(turns) * random.randint(1, 3)
        except Exception:
            text_to_measure = transcription
            turn_pauses = 4

    # len(texto) * factor + pausas de locución + pausa inicial/final
    base_duration = int(len(text_to_measure) * 0.13) + turn_pauses + random.randint(2, 6)

    if categoria == "ruido" and len(text_to_measure) < 45:
        # Cortes abruptos o estática breve
        return max(2, min(base_duration, random.randint(3, 10)))

    return max(5, base_duration)


def generate_call_timeline(
    total_calls: int,
    max_t: int = 1800,
    start_offset: int = 1
) -> List[Dict[str, Any]]:
    """Genera la lista base de llamadas con marcas temporales T en enteros ordenadas cronológicamente."""
    categories = calculate_category_distribution(total_calls)
    calls = []

    for cat in categories:
        tipo_trans = determine_transcription_type(cat)
        t_inicio = sample_start_tick(max_t=max_t) + (start_offset - 1)
        calls.append({
            "categoria": cat,
            "tipo_transcripcion": tipo_trans,
            "inicio": int(t_inicio),
        })

    # Ordenar cronológicamente por T de inicio
    calls.sort(key=lambda x: x["inicio"])
    return calls
