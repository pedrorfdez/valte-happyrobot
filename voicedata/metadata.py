"""Generador de metadatos para llamadas al 112 (IDs, teléfonos, receptores, coordenadas)."""

import uuid
import random
from typing import Dict, Any

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


def generate_coordinates() -> str:
    """Genera latitud y longitud aleatorias dentro del bounding box de la zona afectada.
    
    Devuelve estrictamente las coordenadas numéricas sin nombres de localidades.
    Formato: 'lat,lon' con 6 decimales.
    """
    lat = round(random.uniform(LAT_MIN, LAT_MAX), 6)
    lon = round(random.uniform(LON_MIN, LON_MAX), 6)
    return f"{lat},{lon}"


def enrich_call_metadata(call_dict: Dict[str, Any]) -> Dict[str, Any]:
    """Asigna todos los campos de metadatos requeridos a una llamada."""
    call_dict["id_llamada"] = str(uuid.uuid4())
    call_dict["origen"] = generate_origin_phone()
    call_dict["receptor"] = generate_receiver(call_dict["tipo_transcripcion"])
    call_dict["coordenadas"] = generate_coordinates()
    return call_dict
