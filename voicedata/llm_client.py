"""Cliente asíncrono para interactuar con la API de OpenAI con control de concurrencia y backoff."""

import os
import re
import json
import logging
import asyncio
from typing import Optional, Dict, Any

from config import DEFAULT_MODEL, DEFAULT_CONCURRENCY
from prompts import build_prompt_payload, generate_mock_transcription

logger = logging.getLogger(__name__)


def clean_llm_json_output(raw_text: str) -> str:
    """Limpia posibles bloques markdown (```json ... ```) del resultado devuelto por el LLM."""
    cleaned = raw_text.strip()
    # Eliminar bloques markdown ```json ... ``` si los hubiese
    match = re.search(r"```(?:json)?\s*(.*?)\s*```", cleaned, re.DOTALL)
    if match:
        cleaned = match.group(1).strip()
    
    # Validar que sea JSON válido
    try:
        parsed = json.loads(cleaned)
        # Asegurar formato string compacto o legible
        return json.dumps(parsed, ensure_ascii=False)
    except Exception:
        # Si falló el parseo, intentar envolverlo en una estructura de diálogo básica
        logger.warning("El LLM no devolvió un JSON estricto para el diálogo. Reestructurando.")
        fallback_dialogue = [
            {"hablante": "llamante", "texto": cleaned}
        ]
        return json.dumps(fallback_dialogue, ensure_ascii=False)


class LLMClient:
    """Cliente asíncrono con control de concurrencia, reintentos y soporte mock."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: str = DEFAULT_MODEL,
        concurrency: int = DEFAULT_CONCURRENCY,
        force_mock: bool = False,
    ):
        self.api_key = api_key or os.getenv("OPENAI_API_KEY")
        self.model = model
        self.semaphore = asyncio.Semaphore(concurrency)
        self.force_mock = force_mock or not bool(self.api_key)
        self.client = None

        if not self.force_mock:
            try:
                from openai import AsyncOpenAI
                self.client = AsyncOpenAI(api_key=self.api_key)
                logger.info(f"Cliente OpenAI inicializado con modelo '{self.model}' (Concurrencia: {concurrency})")
            except ImportError:
                logger.warning("Librería 'openai' no disponible. Activando modo mock.")
                self.force_mock = True
        else:
            logger.info("Modo Mock activado (sin llamadas a API externa).")

    async def generate_transcription(
        self,
        categoria: str,
        tipo_transcripcion: str,
        max_retries: int = 4
    ) -> str:
        """Genera la transcripción de una llamada con manejo de concurrencia y reintentos."""
        if self.force_mock:
            # Simular una ligera latencia para testear concurrencia
            await asyncio.sleep(0.01)
            return generate_mock_transcription(categoria, tipo_transcripcion)

        payload = build_prompt_payload(categoria, tipo_transcripcion)

        async with self.semaphore:
            backoff = 1.0
            for attempt in range(1, max_retries + 1):
                try:
                    response = await self.client.chat.completions.create(
                        model=self.model,
                        messages=payload["messages"],
                        temperature=0.85,
                        max_tokens=450,
                    )
                    raw_content = response.choices[0].message.content or ""

                    if tipo_transcripcion == "dialogo_operador":
                        return clean_llm_json_output(raw_content)
                    else:
                        return raw_content.strip()

                except Exception as e:
                    err_msg = str(e)
                    logger.warning(f"[Intento {attempt}/{max_retries}] Error LLM: {err_msg}")
                    if attempt == max_retries:
                        logger.error("Agotados los reintentos con el LLM. Aplicando mock de emergencia.")
                        return generate_mock_transcription(categoria, tipo_transcripcion)
                    
                    await asyncio.sleep(backoff)
                    backoff *= 2  # Exponential backoff
