"""Generador de tráfico, distribución y marcas temporales (inicio, fin, duración)."""

import random
from datetime import datetime, timedelta
from typing import List, Dict, Any, Tuple

from config import (
    RATIO_CRITICA,
    RATIO_URGENTE,
    RATIO_RUIDO,
    RATIO_DIALOGO_OPERADOR,
    SIMULATION_DATE,
    TIME_SLICES,
    DURATION_RANGES,
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


def sample_start_time(date_str: str = SIMULATION_DATE) -> datetime:
    """Muestrea una hora de inicio según la curva de intensidad (picos y valles)."""
    # Elegir franja horaria según el peso de intensidad
    slices = TIME_SLICES
    weights = [s[2] for s in slices]
    chosen_slice = random.choices(slices, weights=weights, k=1)[0]
    
    start_hour, end_hour, _ = chosen_slice
    start_sec = start_hour * 3600
    end_sec = end_hour * 3600 - 1
    random_second = random.randint(start_sec, end_sec)

    base_date = datetime.strptime(date_str, "%Y-%m-%d")
    return base_date + timedelta(seconds=random_second)


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


def calculate_duration(categoria: str, tipo_transcripcion: str) -> int:
    """Calcula la duración en segundos según la criticidad y el tipo de llamada."""
    if categoria == "ruido":
        # Subtipo: corte inmediato vs queja
        if random.random() < 0.45:
            r = DURATION_RANGES["ruido_corte"]
        else:
            r = DURATION_RANGES["ruido_admin"]
    elif tipo_transcripcion == "monologo_centralita":
        r = DURATION_RANGES["monologo_saturado"]
    elif categoria == "urgente":
        r = DURATION_RANGES["dialogo_urgente"]
    else:  # critica
        r = DURATION_RANGES["dialogo_critico"]

    return random.randint(r[0], r[1])


def generate_call_timeline(total_calls: int) -> List[Dict[str, Any]]:
    """Genera la lista base de llamadas con sus marcas temporales ordenadas cronológicamente."""
    categories = calculate_category_distribution(total_calls)
    calls = []

    for cat in categories:
        hora_inicio = sample_start_time()
        tipo_trans = determine_transcription_type(cat)
        duracion = calculate_duration(cat, tipo_trans)
        hora_fin = hora_inicio + timedelta(seconds=duracion)

        calls.append({
            "categoria": cat,
            "tipo_transcripcion": tipo_trans,
            "hora_inicio_dt": hora_inicio,
            "hora_fin_dt": hora_fin,
            "duracion_segundos": duracion,
        })

    # Ordenar cronológicamente por hora de inicio
    calls.sort(key=lambda x: x["hora_inicio_dt"])

    # Formatear strings ISO 8601
    for c in calls:
        c["hora_inicio"] = c["hora_inicio_dt"].isoformat()
        c["hora_fin"] = c["hora_fin_dt"].isoformat()

    return calls
