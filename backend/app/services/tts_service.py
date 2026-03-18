"""Text-to-Speech service — local Sherpa-ONNX or remote endpoint."""

import base64
import logging
import os
import uuid
from pathlib import Path
from typing import Optional

import httpx

from app.config import get_settings

logger = logging.getLogger(__name__)

# Directory where generated audio files are stored
AUDIO_DIR = Path.home() / ".voxyflow" / "audio"


def ensure_audio_dir() -> Path:
    """Create the audio output directory if it doesn't exist."""
    AUDIO_DIR.mkdir(parents=True, exist_ok=True)
    return AUDIO_DIR


class TTSService:
    """
    TTS abstraction layer.

    Supports:
    - sherpa-onnx: Local CPU inference (stub, not implemented)
    - remote: Forward to an HTTP TTS endpoint (XTTS on Corsair GPU)
    """

    def __init__(self):
        settings = get_settings()
        self.engine = settings.tts_engine
        self.remote_url = settings.tts_service_url
        self._onnx_tts = None  # Lazy-loaded

    async def synthesize(self, text: str) -> Optional[str]:
        """
        Convert text to speech audio.

        Returns: base64-encoded audio bytes, or None on failure.
        """
        if not text.strip():
            return None

        if self.engine == "sherpa-onnx":
            return await self._synthesize_sherpa(text)
        elif self.engine == "remote":
            return await self._synthesize_remote(text)
        else:
            logger.warning(f"Unknown TTS engine: {self.engine}")
            return None

    async def synthesize_to_file(self, text: str) -> Optional[str]:
        """
        Convert text to speech audio and save to a file.

        Returns: file path string, or None on failure.
        """
        if not text.strip():
            return None

        if self.engine == "remote":
            return await self._synthesize_remote_to_file(text)
        else:
            # For sherpa-onnx stub, just return None
            return None

    async def _synthesize_sherpa(self, text: str) -> Optional[str]:
        """
        Local Sherpa-ONNX TTS.

        TODO: Initialize sherpa-onnx with a VITS model.
        For MVP, this is a stub that returns None.
        """
        logger.info("Sherpa-ONNX TTS stub — no audio generated")
        return None

    async def _synthesize_remote(self, text: str) -> Optional[str]:
        """Forward TTS request to a remote HTTP endpoint, return base64."""
        file_path = await self._synthesize_remote_to_file(text)
        if file_path is None:
            return None
        try:
            with open(file_path, "rb") as f:
                audio_bytes = f.read()
            return base64.b64encode(audio_bytes).decode()
        except Exception as e:
            logger.error(f"Failed to read TTS audio file: {e}")
            return None

    async def _synthesize_remote_to_file(self, text: str) -> Optional[str]:
        """
        Forward TTS request to the remote XTTS endpoint on Corsair.

        POSTs to {remote_url}/speak with {"text": text, "language": "en"}.
        Saves the returned WAV bytes to ~/.voxyflow/audio/<uuid>.wav.
        Returns the file path, or None on failure.
        """
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(
                    f"{self.remote_url}/speak",
                    json={"text": text, "language": "en"},
                )
                response.raise_for_status()

                audio_bytes = response.content
                if not audio_bytes:
                    logger.warning("Remote TTS returned empty audio")
                    return None

                audio_dir = ensure_audio_dir()
                filename = f"{uuid.uuid4().hex}.wav"
                file_path = audio_dir / filename

                file_path.write_bytes(audio_bytes)
                logger.info(f"TTS audio saved: {file_path}")
                return str(file_path)

        except httpx.ConnectError:
            logger.warning(f"Remote TTS server unreachable at {self.remote_url} — skipping")
            return None
        except httpx.TimeoutException:
            logger.warning(f"Remote TTS request timed out — skipping")
            return None
        except Exception as e:
            logger.error(f"Remote TTS failed: {e}")
            return None
