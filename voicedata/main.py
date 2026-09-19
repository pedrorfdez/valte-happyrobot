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

# Cargar variables de entorno desde .env
load_dotenv()

from tqdm.asyncio import tqdm_asyncio

from traffic import generate_call_timeline, calculate_duration_from_text
from metadata import enrich_call_metadata
from llm_client import LLMClient
from config import DEFAULT_MODEL, DEFAULT_CONCURRENCY, DEFAULT_IMMINENT_CALLS

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S"
)
logger = logging.getLogger("voicemock")

CSV_FIELDNAMES = [
    "id_llamada",
    "inicio",
    "fin",
    "duracion_segundos",
    "origen",
    "receptor",
    "latitud",
    "longitud",
    "categoria",
    "tipo_transcripcion",
    "transcripcion",
]


async def process_call(
    call: Dict[str, Any],
    llm_client: LLMClient
) -> Dict[str, Any]:
    """Genera la transcripción para una llamada y calcula duración y fin coherentes."""
    town = call.get("town", "Valencia")
    transcripcion = await llm_client.generate_transcription(
        categoria=call["categoria"],
        tipo_transcripcion=call["tipo_transcripcion"],
        town=town
    )

    duracion = calculate_duration_from_text(
        transcription=transcripcion,
        tipo_transcripcion=call["tipo_transcripcion"],
        categoria=call["categoria"],
        t_norm=call.get("_t_norm", 0.5)
    )
    inicio = round(float(call["inicio"]), 2)
    duracion_sec = int(duracion)
    fin = round(inicio + duracion_sec, 2)
    
    return {
        "id_llamada": str(call["id_llamada"]),
        "inicio": inicio,
        "fin": fin,
        "duracion_segundos": duracion_sec,
        "origen": str(call["origen"]),
        "receptor": str(call["receptor"]),
        "latitud": float(call["latitud"]),
        "longitud": float(call["longitud"]),
        "categoria": str(call["categoria"]),
        "tipo_transcripcion": str(call["tipo_transcripcion"]),
        "transcripcion": str(transcripcion),
    }


async def generate_dataset(
    num_calls: int,
    output_csv: str,
    client: LLMClient,
    dataset_name: str = "Histórico"
):
    """Genera un lote específico de llamadas y lo guarda en CSV asegurando orden temporal."""
    logger.info(f"== Generando lote [{dataset_name}]: {num_calls} llamadas en '{output_csv}' ==")

    # 1. Planificar timeline y distribución con T enteros
    raw_calls = generate_call_timeline(num_calls)
    
    # 2. Asignar metadatos (IDs, teléfonos, latitud/longitud numéricos)
    prepared_calls = [enrich_call_metadata(c) for c in raw_calls]

    # 3. Directorio de destino
    output_dir = os.path.dirname(output_csv)
    if output_dir:
        os.makedirs(output_dir, exist_ok=True)

    # 4. Generación concurrente
    tasks = [process_call(call, client) for call in prepared_calls]
    completed_calls = []

    for task_coro in tqdm_asyncio.as_completed(tasks, total=len(tasks), desc=f"Llamadas [{dataset_name}]"):
        result = await task_coro
        completed_calls.append(result)

    # 5. Ordenar cronológicamente por T de inicio
    completed_calls.sort(key=lambda x: (x["inicio"], x["fin"]))

    # 6. Escribir CSV asegurando que todos los textos estén entrecomillados y números limpios
    with open(output_csv, mode="w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDNAMES, quoting=csv.QUOTE_NONNUMERIC)
        writer.writeheader()
        for call_data in completed_calls:
            writer.writerow(call_data)

    logger.info(f"== Guardado exitoso: {len(completed_calls)} registros en '{output_csv}' ==")


async def run_generation(
    num_calls: int,
    output_csv: str,
    num_imminent: int,
    output_imminent: str,
    mock: bool,
    concurrency: int,
    model: str
):
    """Orquesta la preparación y generación tanto del banco histórico como de llamadas inminentes."""
    logger.info(f"== Iniciando pipeline voicemock ==")
    logger.info(f"Modo: {'MOCK (local)' if mock else f'LLM ({model})'}")

    client = LLMClient(
        model=model,
        concurrency=concurrency,
        force_mock=mock
    )

    # Banco 1: Llamadas simuladas base / históricas
    await generate_dataset(
        num_calls=num_calls,
        output_csv=output_csv,
        client=client,
        dataset_name="Histórico"
    )

    # Banco 2: Llamadas inminentes (eventos que saltan durante la ejecución del producto)
    if num_imminent > 0 and output_imminent:
        await generate_dataset(
            num_calls=num_imminent,
            output_csv=output_imminent,
            client=client,
            dataset_name="Inminentes"
        )

    logger.info("== Todos los datasets han sido generados exitosamente ==")


def main():
    parser = argparse.ArgumentParser(
        description="Generador de datasets sintéticos de llamadas al 112 (DANA Valencia) para voicemock."
    )
    parser.add_argument(
        "--num-calls", "-n",
        type=int,
        default=100,
        help="Número de llamadas para el dataset base/histórico (por defecto: 100)"
    )
    parser.add_argument(
        "--output", "-o",
        type=str,
        default="llamadas_112_dana.csv",
        help="Ruta del archivo CSV para el dataset base (por defecto: llamadas_112_dana.csv)"
    )
    parser.add_argument(
        "--num-imminent", "-ni",
        type=int,
        default=DEFAULT_IMMINENT_CALLS,
        help=f"Número de llamadas inminentes para el segundo dataset (por defecto: {DEFAULT_IMMINENT_CALLS})"
    )
    parser.add_argument(
        "--output-imminent", "-oi",
        type=str,
        default="llamadas_inminentes.csv",
        help="Ruta del archivo CSV para llamadas inminentes (por defecto: llamadas_inminentes.csv)"
    )
    parser.add_argument(
        "--no-imminent",
        action="store_true",
        help="Omitir la generación del dataset de llamadas inminentes"
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
        help=f"Modelo a utilizar (por defecto: {DEFAULT_MODEL})"
    )

    args = parser.parse_args()

    # Si no hay OPENAI_API_KEY y no se especificó --mock, avisar y cambiar a mock
    if not os.getenv("OPENAI_API_KEY") and not args.mock:
        logger.warning(
            "AVISO: No se ha detectado la variable de entorno OPENAI_API_KEY en el sistema ni en .env. "
            "Activando modo --mock automáticamente."
        )
        args.mock = True

    imminent_count = 0 if args.no_imminent else args.num_imminent

    try:
        asyncio.run(run_generation(
            num_calls=args.num_calls,
            output_csv=args.output,
            num_imminent=imminent_count,
            output_imminent=args.output_imminent,
            mock=args.mock,
            concurrency=args.concurrency,
            model=args.model
        ))
    except KeyboardInterrupt:
        logger.info("\nGeneración interrumpida por el usuario.")
        sys.exit(0)


if __name__ == "__main__":
    main()
