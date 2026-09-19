"""Generador de metadatos para llamadas al 112 (IDs, teléfonos, receptores, coordenadas)."""

import uuid
import random
from typing import Dict, Any, Tuple

from config import LAT_MIN, LAT_MAX, LON_MIN, LON_MAX


def generate_origin_phone() -> str:
    """Genera un número de teléfono realista español (+34 móvil o fijo de Valencia)."""
    is_mobile = random.random() < 0.80
    if is_mobile:
        prefix = random.choice(["6", "7"])
        rest = "".join([str(random.randint(0, 9)) for _ in range(8)])
        return f"+34{prefix}{rest}"
    else:
        # Fijo Valencia (+34 96...)
        rest = "".join([str(random.randint(0, 9)) for _ in range(7)])
        return f"+3496{rest}"


def generate_receiver(tipo_transcripcion: str) -> str:
    """Genera la identificación del receptor según si fue atendida o cayó en saturación."""
    if tipo_transcripcion == "monologo_centralita":
        return random.choice([
            "centralita_automatica_saturada",
            "sistema_grabacion_espera_112",
            "servidor_buzon_emergencia_colapso"
        ])
    else:
        op_id = random.randint(101, 160)
        return f"operador_112_val_#{op_id}"


ZONAS_CERO = {
    "Utiel": (39.566, -1.200),
    "Chiva": (39.474, -0.718),
    "Paiporta": (39.428, -0.417),
    "Massanassa": (39.412, -0.399),
    "Catarroja": (39.402, -0.404),
    "Letur": (38.365, -2.100),
    "Algemesí": (39.189, -0.437),
}


def generate_location() -> Tuple[str, float, float]:
    """Selecciona una zona cero al azar y aplica un pequeño ruido aleatorio.
    
    Devuelve (pueblo, latitud, longitud) con coordenadas dispersas en el municipio sin solape.
    """
    pueblo = random.choice(list(ZONAS_CERO.keys()))
    base_lat, base_lon = ZONAS_CERO[pueblo]
    noise_lat = random.uniform(-0.004, 0.004)
    noise_lon = random.uniform(-0.004, 0.004)
    lat = round(base_lat + noise_lat, 6)
    lon = round(base_lon + noise_lon, 6)
    return pueblo, lat, lon


def generate_coordinates() -> Tuple[float, float]:
    """Genera coordenadas basadas en las zonas cero con dispersión aleatoria."""
    _, lat, lon = generate_location()
    return lat, lon


def enrich_call_metadata(call_dict: Dict[str, Any]) -> Dict[str, Any]:
    """Asigna todos los campos de metadatos requeridos a una llamada."""
    call_dict["id_llamada"] = str(uuid.uuid4())
    call_dict["origen"] = generate_origin_phone()
    call_dict["receptor"] = generate_receiver(call_dict["tipo_transcripcion"])
    pueblo, lat, lon = generate_location()
    call_dict["town"] = pueblo
    call_dict["latitud"] = lat
    call_dict["longitud"] = lon
    return call_dict
