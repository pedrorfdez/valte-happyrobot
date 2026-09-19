"""Cliente asíncrono para interactuar con la API de OpenAI con control de concurrencia y backoff."""

import os
import re
import json
import random
import logging
import asyncio
from typing import Optional, Dict, Any, List

from config import DEFAULT_MODEL, DEFAULT_CONCURRENCY
from prompts import build_prompt_payload, generate_mock_transcription

logger = logging.getLogger(__name__)

OPERATOR_GREETINGS = [
    "112 Emergencias Valencia, ¿cuál es su urgencia?",
    "112 Emergencias, dígame.",
    "112 Emergencias, ¿dónde se encuentra?",
    "112 Emergencias, le escucho. Indique su localización exacta.",
    "Centro de Coordinación de Emergencias 112, dígame."
]

CALLER_CUTOFF_REPLACEMENTS = [
    "¡Hola! ¿Me oyen? ¡Se corta la llamada!",
    "¡Ayuda, por favor! ¿Hay alguien ahí?",
    "¡Hola! ¡Se está cortando la línea!",
    "¡Hola, 112! ¡No les escucho bien por el ruido del agua!",
    "¡Oiga! ¡Se pierde la señal!"
]


def sanitize_dialogue_artifacts(dialogue_json_str: str) -> str:
    """Elimina artefactos mudos ('...', '[Silencio]') en diálogos JSON y los reemplaza por texto válido."""
    try:
        dialogue = json.loads(dialogue_json_str)
        if isinstance(dialogue, list):
            changed = False
            for turn in dialogue:
                txt = turn.get("texto", "").strip()
                is_artifact = (
                    txt in ["...", "..", ".", "…", "[Silencio]", "[silencio]", "[Silencio...]", ""]
                    or set(txt).issubset({".", " ", "…", "-", "_"})
                )
                if is_artifact:
                    changed = True
                    speaker = turn.get("hablante", "operador")
                    if speaker == "operador":
                        turn["texto"] = random.choice(OPERATOR_GREETINGS)
                    else:
                        turn["texto"] = random.choice(CALLER_CUTOFF_REPLACEMENTS)
            if changed:
                return json.dumps(dialogue, ensure_ascii=False)
    except Exception:
        pass
    return dialogue_json_str


def sanitize_text_artifacts(text: str) -> str:
    """Elimina artefactos mudos ('...', '[Silencio]') en textos y monólogos."""
    cleaned = text.strip()
    is_artifact = (
        cleaned in ["...", "..", ".", "…", "[Silencio]", "[silencio]", "[Silencio...]", ""]
        or set(cleaned).issubset({".", " ", "…", "-", "_"})
    )
    if is_artifact:
        return "[Centralita 112: Línea temporalmente saturada. Si está en peligro inminente permanezca en zonas altas.]"
    return text


GROQ_MODEL_ALIASES = {
    "mixtral-8x7b-32768": "qwen/qwen3.8-27b",
    "mixtral-8x7b": "qwen/qwen3.8-27b",
    "llama-3.1-8b-instant": "qwen/qwen3.8-27b",
    "llama-3.3-70b-versatile": "openai/gpt-oss-120b",
    "llama3-8b-8192": "qwen/qwen3.8-27b",
    "llama3-70b-8192": "openai/gpt-oss-120b",
}


def clean_llm_json_output(raw_text: str) -> str:
    """Limpia y extrae de forma robusta la estructura JSON de diálogo devuelta por el LLM."""
    cleaned = raw_text.strip()
    
    # 1. Eliminar bloques markdown ```json ... ``` si existiesen
    match = re.search(r"```(?:json)?\s*(.*?)\s*```", cleaned, re.DOTALL)
    if match:
        cleaned = match.group(1).strip()

    # 2. Si hay texto previo antes del primer '[', descartarlo
    first_bracket = cleaned.find("[")
    if first_bracket != -1:
        cleaned = cleaned[first_bracket:]

    # 3. Extraer el bloque delimitado por el primer '[' y el último ']'
    bracket_match = re.search(r"(\[.*\])", cleaned, re.DOTALL)
    if bracket_match:
        try:
            parsed = json.loads(bracket_match.group(1))
            if isinstance(parsed, list) and len(parsed) > 0:
                return json.dumps(parsed, ensure_ascii=False)
        except Exception:
            pass

    # 4. Intentar parseo directo
    try:
        parsed = json.loads(cleaned)
        if isinstance(parsed, list) and len(parsed) > 0:
            return json.dumps(parsed, ensure_ascii=False)
    except Exception:
        pass

    # 5. Si el JSON quedó cortado sin cerrar el corchete final ']'
    if cleaned.startswith("[") and not cleaned.endswith("]"):
        last_brace = cleaned.rfind("}")
        if last_brace != -1:
            try:
                repaired = cleaned[:last_brace + 1] + "]"
                parsed = json.loads(repaired)
                if isinstance(parsed, list):
                    return json.dumps(parsed, ensure_ascii=False)
            except Exception:
                pass

    # 6. Extracción por expresiones regulares de objetos {"hablante": ..., "texto": ...}
    pattern = r'\{\s*"hablante"\s*:\s*"([^"]+)"\s*,\s*"texto"\s*:\s*"((?:[^"\\]|\\.)*)"\s*\}'
    turns = []
    for m in re.finditer(pattern, cleaned, re.DOTALL):
        turns.append({"hablante": m.group(1), "texto": m.group(2)})
    if turns:
        return json.dumps(turns, ensure_ascii=False)

    # 7. Fallback estructurado si falló todo
    logger.warning("El LLM no devolvió un JSON estricto para el diálogo. Reestructurando.")
    fallback_dialogue = [
        {"hablante": "llamante", "texto": cleaned}
    ]
    return sanitize_dialogue_artifacts(json.dumps(fallback_dialogue, ensure_ascii=False))


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
        self.configured_model = model
        self.model = model
        self.semaphore = asyncio.Semaphore(concurrency)
        self.force_mock = force_mock or not bool(self.api_key)
        self.client = None

        base_url = os.getenv("OPENAI_BASE_URL", "")
        if not self.force_mock:
            # Detección y adaptación para modelos deprecados en Groq
            if "groq.com" in base_url and self.model in GROQ_MODEL_ALIASES:
                target_model = GROQ_MODEL_ALIASES[self.model]
                logger.info(
                    f"Modelo configurado '{self.model}' adaptado a modelo activo en Groq: '{target_model}'."
                )
                self.model = target_model

            try:
                from openai import AsyncOpenAI
                self.client = AsyncOpenAI(api_key=self.api_key, base_url=base_url or None)
                endpoint_desc = f" [{base_url}]" if base_url else ""
                logger.info(f"Cliente LLM inicializado con modelo '{self.model}'{endpoint_desc} (Concurrencia: {concurrency})")
            except ImportError:
                logger.warning("Librería 'openai' no disponible. Activando modo mock.")
                self.force_mock = True
        else:
            logger.info("Modo Mock activado (sin llamadas a API externa).")

    async def generate_transcription(
        self,
        categoria: str,
        tipo_transcripcion: str,
        town: str = "Valencia",
        max_retries: int = 8
    ) -> str:
        """Genera la transcripción de una llamada con manejo de concurrencia y reintentos."""
        if self.force_mock:
            raw = generate_mock_transcription(categoria, tipo_transcripcion, town=town)
            if tipo_transcripcion == "dialogo_operador":
                return sanitize_dialogue_artifacts(raw)
            return sanitize_text_artifacts(raw)

        payload = build_prompt_payload(categoria, tipo_transcripcion, town=town)

        async with self.semaphore:
            backoff = 2.0
            for attempt in range(1, max_retries + 1):
                try:
                    response = await self.client.chat.completions.create(
                        model=self.model,
                        messages=payload["messages"],
                        temperature=0.85,
                        max_tokens=1200,
                    )
                    raw_content = response.choices[0].message.content or ""

                    if tipo_transcripcion == "dialogo_operador":
                        cleaned = clean_llm_json_output(raw_content)
                        return sanitize_dialogue_artifacts(cleaned)
                    else:
                        text = raw_content.strip()
                        if not text:
                            return "[llamada entrecortada / sin audio legible]"
                        return sanitize_text_artifacts(text)

                except Exception as e:
                    err_msg = str(e)
                    logger.warning(f"[Intento {attempt}/{max_retries}] Error LLM ({self.model}): {err_msg}")

                    # Fallback dinámico si el modelo no existe (404), fue decomisionado (400) o agotó cuota diaria (TPD)
                    is_unusable = any(k in err_msg.lower() for k in [
                        "404", "model_not_found", "model_decommissioned", "decommissioned", "tokens per day", "tpd"
                    ])
                    if is_unusable and attempt <= 2:
                        try:
                            models_resp = await self.client.models.list()
                            available = [m.id for m in models_resp.data]
                            preferred = ["qwen/qwen3.8-27b", "openai/gpt-oss-120b", "groq/compound", "openai/gpt-oss-20b"]
                            fallback_choice = next((c for c in preferred if c in available and c != self.model), None)
                            if fallback_choice:
                                logger.info(f"Cambiando de modelo '{self.model}' a '{fallback_choice}' por limitación o estado de modelo.")
                                self.model = fallback_choice
                                continue
                        except Exception as list_err:
                            logger.warning(f"No se pudieron listar modelos de respaldo: {list_err}")

                    if attempt == max_retries:
                        logger.error("Agotados los reintentos con el LLM. Aplicando mock de emergencia.")
                        raw = generate_mock_transcription(categoria, tipo_transcripcion, town=town)
                        if tipo_transcripcion == "dialogo_operador":
                            return sanitize_dialogue_artifacts(raw)
                        return sanitize_text_artifacts(raw)

                    # Cálculo inteligente de tiempo de espera ante rate limit (429)
                    sleep_time = backoff
                    if "429" in err_msg or "rate" in err_msg.lower():
                        match_wait = re.search(r"try again in ([\d\.]+)s", err_msg, re.IGNORECASE)
                        if match_wait:
                            sleep_time = float(match_wait.group(1)) + 1.0
                        else:
                            sleep_time = max(backoff, 5.0)

                    await asyncio.sleep(sleep_time)
                    backoff *= 1.8  # Exponential backoff
