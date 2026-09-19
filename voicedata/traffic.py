"""Generador de tráfico, distribución y marcas temporales continuas con modelos matemáticos avanzados."""

import json
import random
import math
import re
from typing import List, Dict, Any


def calculate_duration_from_text(
    transcription: str,
    tipo_transcripcion: str,
    categoria: str,
    t_norm: float = 0.5
) -> int:
    """Calcula la duración en segundos coherente con la longitud real del habla."""
    clean_text = re.sub(r'\[.*?\]', '', transcription).strip()
    clean_text = re.sub(r'\s+', ' ', clean_text)
    txt_lower = clean_text.lower()

    # BUGFIX: Llamadas de bolsillo / Cortes / Degradación técnica
    is_pocket_or_cut = (
        "bolsillo" in txt_lower
        or "involuntaria" in txt_lower
        or "corte" in txt_lower
        or "cobertura" in txt_lower
        or "señal" in txt_lower
        or "oye " in txt_lower
        or "¡oye" in txt_lower
        or "¿hola?" in txt_lower
        or "se entrecorta" in txt_lower
        or "estática" in txt_lower
    )

    if categoria == "ruido" or categoria == "ruido_degradado":
        if is_pocket_or_cut or categoria == "ruido_degradado" or (t_norm > 0.85 and len(clean_text) < 120):
            # Forzar duración corta, ignorando la fórmula de caracteres
            return random.randint(3, 12)

    text_to_measure = clean_text
    turn_pauses = 0

    if tipo_transcripcion == "dialogo_operador":
        try:
            turns = json.loads(transcription)
            if isinstance(turns, list):
                text_to_measure = " ".join(
                    [re.sub(r'\[.*?\]', '', t.get("texto", "")).strip() for t in turns if isinstance(t, dict)]
                )
                turn_pauses = len(turns) * random.randint(1, 3)
        except Exception:
            text_to_measure = clean_text
            turn_pauses = 4

    # len(texto) * factor + pausas de locución + pausa inicial/final
    base_duration = int(len(text_to_measure) * 0.13) + turn_pauses + random.randint(2, 6)
    return max(5, base_duration)


def gaussian(x: float, mu: float, sigma: float) -> float:
    return math.exp(-0.5 * ((x - mu) / sigma) ** 2)

def sigmoid(x: float, k: float, x0: float) -> float:
    # Prevenir overflow
    try:
        return 1.0 / (1.0 + math.exp(-k * (x - x0)))
    except OverflowError:
        return 0.0 if x < x0 else 1.0


def generate_call_timeline(
    total_calls: int,
    max_t: int = 1800,
    start_offset: float = 1.0
) -> List[Dict[str, Any]]:
    """Genera la lista base de llamadas con marcas temporales y categorías dinámicas (NHPP + Sigmoides)."""
    calls = []
    
    # 1. NHPP simulado usando Beta(6.0, 1.5) para volumen de llamadas (El Subidón)
    times_norm = [random.betavariate(6.0, 1.5) for _ in range(total_calls)]
    times_norm.sort()

    # 2. Asignación cronológica de reglas
    for t_norm in times_norm:
        t_inicio = (t_norm * max_t) + (start_offset - 1.0)
        
        # A. Curvas de Gravedad (Gauss)
        w_ruido = gaussian(t_norm, mu=0.1, sigma=0.2) + gaussian(t_norm, mu=0.95, sigma=0.1)
        w_urgente = gaussian(t_norm, mu=0.5, sigma=0.2)
        w_critica = gaussian(t_norm, mu=0.9, sigma=0.15)
        
        cat = random.choices(
            ["ruido", "urgente", "critica"], 
            weights=[w_ruido, w_urgente, w_critica]
        )[0]
        
        # B. Degradación Técnica (Sigmoide)
        if cat == "ruido":
            prob_deg = sigmoid(t_norm, k=25.0, x0=0.85)
            if random.random() < prob_deg:
                cat = "ruido"  # Lo mantenemos como ruido para los prompts, pero forzamos el tipo_transcripcion a monologo de colapso en el paso C. 
                               # El "ruido_degradado" conceptual es simplemente un ruido_colapso
                               
        # C. Saturación del Receptor (Sigmoide)
        prob_monologo = sigmoid(t_norm, k=15.0, x0=0.75)
        if random.random() < prob_monologo:
            tipo = "monologo_centralita"
        else:
            tipo = "dialogo_operador"

        # Guardamos el t_norm para poder usarlo en el cálculo de duración
        calls.append({
            "categoria": cat,
            "tipo_transcripcion": tipo,
            "inicio": round(t_inicio, 2),
            "_t_norm": t_norm
        })

    return calls
