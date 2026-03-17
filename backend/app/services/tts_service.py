"""Text-to-Speech service — local Sherpa-ONNX or remote endpoint."""

import base64
import logging
from typing import Optional

import httpx

from app.config import get_settings

logger = logging.getLogger(__name__)


class TTSService:
    """
    TTS abstraction layer.

    Supports:
    - sherpa-onnx: Local CPU inference (default for MVP)
    - remote: Forward to an HTTP TTS endpoint (e.g., Corsair GPU)
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

    async def _synthesize_sherpa(self, text: str) -> Optional[str]:
        """
        Local Sherpa-ONNX TTS.

        TODO: Initialize sherpa-onnx with a VITS model.
        For MVP, this is a stub that returns None.
        """
        # Placeholder — requires sherpa-onnx installation and model download
        # Example setup:
        #
        # import sherpa_onnx
        # if not self._onnx_tts:
        #     self._onnx_tts = sherpa_onnx.OfflineTts(
        #         model=sherpa_onnx.OfflineTtsModelConfig(
        #             vits=sherpa_onnx.OfflineTtsVitsModelConfig(
        #                 model="path/to/model.onnx",
        #                 tokens="path/to/tokens.txt",
        #             )
        #         )
        #     )
        # audio = self._onnx_tts.generate(text, sid=0, speed=1.0)
        # return base64.b64encode(audio.samples.tobytes()).decode()

        logger.info("Sherpa-ONNX TTS stub — no audio generated")
        return None

    async def _synthesize_remote(self, text: str) -> Optional[str]:
        """Forward TTS request to a remote HTTP endpoint."""
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(
                    f"{self.remote_url}/tts",
                    json={"text": text, "format": "pcm", "sample_rate": 22050},
                )
                response.raise_for_status()

                # Expect raw audio bytes in response
                audio_bytes = response.content
                return base64.b64encode(audio_bytes).decode()
        except Exception as e:
            logger.error(f"Remote TTS failed: {e}")
            return None
