"""Dictation for the "declare a crisis" box. The browser records, this machine transcribes (faster-whisper):
Brave and Firefox ship no speech recognition of their own, and a control room's audio should not leave the room.
The dependency is optional (`stt` group): without it the endpoints say so and the form keeps working by typing."""

import asyncio
import io
import logging
import re
import threading
import time
from typing import Any

from fastapi import APIRouter, HTTPException, Request

from valte.settings import settings

log = logging.getLogger("valte.stt")
router = APIRouter(tags=["dashboard"])

MAX_BYTES = 25 * 1024 * 1024
# Whisper spells what it has been shown: the words a coordinator is likely to say.
VOCABULARY = ("Centro de coordinación de emergencias, CECOPI. Riada, DANA, barranco del Poyo, incendio forestal, apagón. "
              "Paiporta, Picanya, Massanassa, Chiva, Cheste, Torrent, Alfafar, Catarroja, Horta Sud. AEMET, CHJ, 112, UME, "
              "autobombas, bombas de achique, embarcaciones, mantas, habitantes.")

GHOSTS = re.compile(r"amara\.org|subt[ií]tulos (?:realizados|por)|gracias por ver", re.I)

_model: Any = None
_loading = threading.Lock()
_busy = threading.Lock()  # one transcription at a time: they are CPU-bound


def available() -> bool:
    try:
        import faster_whisper  # noqa: F401
    except ImportError:
        return False
    return True


def _load() -> Any:
    global _model
    with _loading:
        if _model is None:
            from faster_whisper import WhisperModel

            t0 = time.monotonic()
            _model = WhisperModel(settings.valte_stt_model, device="cpu", compute_type="int8")
            log.info("stt: model %s ready in %.1fs", settings.valte_stt_model, time.monotonic() - t0)
    return _model


def _transcribe(audio: bytes, lang: str, hint: str) -> dict[str, Any]:
    model = _load()
    with _busy:
        t0 = time.monotonic()
        segments, info = model.transcribe(io.BytesIO(audio), language=lang or None, vad_filter=True, beam_size=5,
                                          condition_on_previous_text=False,
                                          initial_prompt=(VOCABULARY + " " + hint[-200:]).strip())
        text = " ".join(s.text.strip() for s in segments if s.no_speech_prob < 0.6).strip()
    if GHOSTS.search(text) and len(text) < 90:  # what Whisper "hears" in noise: subtitle credits from its training data
        text = ""
    return {"text": text, "language": info.language, "audio_s": round(info.duration, 1),
            "took_s": round(time.monotonic() - t0, 1), "model": settings.valte_stt_model}


@router.get("/stt")
async def stt_status(warm: bool = False) -> dict[str, Any]:
    """Asked by the form when it opens: says whether dictation works here; `warm` starts loading the model."""
    ok = available()
    if warm and ok and _model is None and not _loading.locked():
        asyncio.get_running_loop().run_in_executor(None, _load)
    return {"available": ok, "ready": _model is not None, "model": settings.valte_stt_model}


@router.post("/stt")
async def stt(request: Request, lang: str = "es", hint: str = "") -> dict[str, Any]:
    """Body = the recording as the browser made it (webm/ogg/mp4/wav). `hint` = what is already written, so names keep their spelling."""
    if not available():
        raise HTTPException(status_code=501, detail="El dictado no está instalado en este servidor (uv sync --group stt).")
    audio = await request.body()
    if not audio:
        raise HTTPException(status_code=422, detail="No ha llegado audio.")
    if len(audio) > MAX_BYTES:
        raise HTTPException(status_code=413, detail="Grabación demasiado larga.")
    try:
        return await asyncio.to_thread(_transcribe, audio, lang, hint)
    except Exception as e:
        log.warning("stt failed: %s", e)
        raise HTTPException(status_code=422, detail=f"No he podido transcribir la grabación: {e}")
