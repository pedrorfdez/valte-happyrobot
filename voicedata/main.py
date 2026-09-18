"""Orquestador principal y CLI para la generación del dataset sintético de llamadas al 112."""

import os
import csv
import sys
import asyncio
import logging
import argparse
from typing import List, Dict, Any

# Compatibilidad con Windows console
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from dotenv import load_dotenv
from tqdm.asyncio import tqdm_asyncio

from traffic import generate_call_timeline
from metadata import enrich_call_metadata
from llm_client import LLMClient
from config import DEFAULT_MODEL, DEFAULT_CONCURRENCY

# Cargar variables de entorno desde .env
load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S"
)
logger = logging.getLogger("voicemock")

CSV_FIELDNAMES = [
    "id_llamada",
    "hora_inicio",
    "hora_fin",
    "duracion_segundos",
    "origen",
    "receptor",
    "coordenadas",
    "categoria",
    "tipo_transcripcion",
    "transcripcion",
]


async def process_call(
    call: Dict[str, Any],
    llm_client: LLMClient
) -> Dict[str, Any]:
    """Genera la transcripción para una llamada y prepara el registro para exportación."""
    transcripcion = await llm_client.generate_transcription(
        categoria=call["categoria"],
        tipo_transcripcion=call["tipo_transcripcion"]
    )
    
    return {
        "id_llamada": call["id_llamada"],
        "hora_inicio": call["hora_inicio"],
        "hora_fin": call["hora_fin"],
        "duracion_segundos": call["duracion_segundos"],
        "origen": call["origen"],
        "receptor": call["receptor"],
        "coordenadas": call["coordenadas"],
        "categoria": call["categoria"],
        "tipo_transcripcion": call["tipo_transcripcion"],
        "transcripcion": transcripcion,
    }


async def run_generation(
    num_calls: int,
    output_csv: str,
    mock: bool,
    concurrency: int,
    model: str
):
    """Orquesta la preparación, generación y escritura streaming del dataset en CSV."""
    logger.info(f"== Iniciando generación de {num_calls} llamadas sintéticas ==")
    logger.info(f"Destino CSV: {output_csv}")
    logger.info(f"Modo: {'MOCK (local)' if mock else f'LLM ({model})'}")

    # 1. Planificar timeline y distribución
    raw_calls = generate_call_timeline(num_calls)
    
    # 2. Asignar metadatos (IDs, teléfonos, coordenadas)
    prepared_calls = [enrich_call_metadata(c) for c in raw_calls]

    # 3. Inicializar cliente LLM
    client = LLMClient(
        model=model,
        concurrency=concurrency,
        force_mock=mock
    )

    # 4. Crear archivo CSV y escribir cabecera
    output_dir = os.path.dirname(output_csv)
    if output_dir:
        os.makedirs(output_dir, exist_ok=True)

    with open(output_csv, mode="w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDNAMES, quoting=csv.QUOTE_MINIMAL)
        writer.writeheader()

        # 5. Ejecutar generación concurrente con barra de progreso
        tasks = [process_call(call, client) for call in prepared_calls]
        
        logger.info(f"Generando transcripciones con concurrencia máxima: {concurrency}...")
        completed = 0
        for task_coro in tqdm_asyncio.as_completed(tasks, total=len(tasks), desc="Llamadas"):
            result = await task_coro
            writer.writerow(result)
            f.flush()  # Streaming directo a disco para evitar pérdida de datos
            completed += 1

    logger.info(f"== Generación finalizada exitosamente: {completed} llamadas en '{output_csv}' ==")


def main():
    parser = argparse.ArgumentParser(
        description="Generador de dataset sintético de llamadas al 112 (DANA Valencia) para voicemock."
    )
    parser.add_argument(
        "--num-calls", "-n",
        type=int,
        default=100,
        help="Número total de llamadas a generar (por defecto: 100)"
    )
    parser.add_argument(
        "--output", "-o",
        type=str,
        default="llamadas_112_dana.csv",
        help="Ruta del archivo CSV resultante (por defecto: llamadas_112_dana.csv)"
    )
    parser.add_argument(
        "--mock",
        action="store_true",
        help="Forzar modo mock (sin gastar cuota de API, ideal para desarrollo y pruebas)"
    )
    parser.add_argument(
        "--concurrency", "-c",
        type=int,
        default=DEFAULT_CONCURRENCY,
        help=f"Número máximo de llamadas concurrentes al LLM (por defecto: {DEFAULT_CONCURRENCY})"
    )
    parser.add_argument(
        "--model", "-m",
        type=str,
        default=DEFAULT_MODEL,
        help=f"Modelo de OpenAI a utilizar (por defecto: {DEFAULT_MODEL})"
    )

    args = parser.parse_args()

    # Si no hay OPENAI_API_KEY y no se especificó --mock, avisar y cambiar a mock
    if not os.getenv("OPENAI_API_KEY") and not args.mock:
        logger.warning(
            "AVISO: No se ha detectado la variable de entorno OPENAI_API_KEY en el sistema ni en .env. "
            "Activando modo --mock automáticamente."
        )
        args.mock = True

    try:
        asyncio.run(run_generation(
            num_calls=args.num_calls,
            output_csv=args.output,
            mock=args.mock,
            concurrency=args.concurrency,
            model=args.model
        ))
    except KeyboardInterrupt:
        logger.info("\nGeneración interrumpida por el usuario.")
        sys.exit(0)


if __name__ == "__main__":
    main()
