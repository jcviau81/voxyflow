"""Voice routes — REMOVED.

Server-side voice processing (TTS via XTTS, STT via Whisper, voice WebSocket)
has been removed. Voice is now 100% client-side:
- STT: Whisper WASM (WebWorker) + Web Speech API
- TTS: Browser speechSynthesis

This file is kept as a stub because it's imported by app.models and other modules.
"""

from fastapi import APIRouter

router = APIRouter(tags=["voice"])

# All endpoints removed — voice is client-side only.
