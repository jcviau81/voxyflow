"""WebSocket voice handler — the core real-time voice pipeline."""

import asyncio
import json
import logging
import time

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db, Chat, Message, new_uuid, utcnow
from app.models.voice import (
    WSTranscript,
    WSAssistantText,
    WSAssistantAudio,
    WSCardSuggestion,
    WSError,
    WSStatus,
)
from app.services.chat_service import ChatService
from app.services.claude_service import ClaudeService
from app.services.tts_service import TTSService
from app.services.analyzer_service import AnalyzerService

logger = logging.getLogger(__name__)

router = APIRouter(tags=["voice"])


@router.websocket("/ws/voice/{chat_id}")
async def voice_websocket(websocket: WebSocket, chat_id: str):
    """
    Full-duplex voice conversation over WebSocket.

    Protocol:
    - Client sends JSON text frames (WSTranscript, WSAudioChunk)
    - Server sends JSON text frames (WSAssistantText, WSAssistantAudio, WSCardSuggestion, WSStatus)
    - Binary frames reserved for future raw audio streaming
    """
    await websocket.accept()

    # Services (will be properly injected when wired up)
    claude = ClaudeService()
    tts = TTSService()
    analyzer = AnalyzerService()

    logger.info(f"Voice WebSocket connected: chat_id={chat_id}")

    try:
        # Send initial status
        await websocket.send_json(WSStatus(state="listening").model_dump())

        while True:
            raw = await websocket.receive_text()
            data = json.loads(raw)
            msg_type = data.get("type")

            if msg_type == "transcript":
                await _handle_transcript(
                    websocket=websocket,
                    chat_id=chat_id,
                    transcript=WSTranscript(**data),
                    claude=claude,
                    tts=tts,
                    analyzer=analyzer,
                )
            elif msg_type == "audio_chunk":
                # TODO: Whisper fallback STT
                await websocket.send_json(
                    WSError(message="Server-side STT not yet implemented").model_dump()
                )
            else:
                await websocket.send_json(
                    WSError(message=f"Unknown message type: {msg_type}").model_dump()
                )

    except WebSocketDisconnect:
        logger.info(f"Voice WebSocket disconnected: chat_id={chat_id}")
    except Exception as e:
        logger.exception(f"Voice WebSocket error: {e}")
        try:
            await websocket.send_json(WSError(message=str(e)).model_dump())
        except Exception:
            pass


async def _handle_transcript(
    websocket: WebSocket,
    chat_id: str,
    transcript: WSTranscript,
    claude: ClaudeService,
    tts: TTSService,
    analyzer: AnalyzerService,
):
    """
    Process a user transcript through the multi-layer pipeline.

    1. Store user message
    2. Layer 1 (Fast): fast response → TTS → send
    3. Layer 2 (Deep): background enrichment (async)
    4. Layer 3 (Analyzer): card detection (async)
    """
    user_text = transcript.text.strip()
    if not user_text:
        return

    # Notify client we're processing
    await websocket.send_json(WSStatus(state="processing").model_dump())

    t0 = time.monotonic()

    # --- Layer 1: Fast response ---
    try:
        fast_response = await claude.chat_fast(
            chat_id=chat_id,
            user_message=user_text,
            project_id=transcript.project_id,
        )
        latency_ms = (time.monotonic() - t0) * 1000

        # Send text response
        await websocket.send_json(
            WSAssistantText(
                text=fast_response,
                model="fast",
                is_enrichment=False,
            ).model_dump()
        )

        # Generate and send TTS audio
        await websocket.send_json(WSStatus(state="speaking").model_dump())
        try:
            audio_b64 = await tts.synthesize(fast_response)
            if audio_b64:
                await websocket.send_json(
                    WSAssistantAudio(data=audio_b64).model_dump()
                )
        except Exception as e:
            logger.warning(f"TTS failed: {e}")

    except Exception as e:
        logger.error(f"Fast layer response failed: {e}")
        await websocket.send_json(WSError(message=f"LLM error: {e}").model_dump())
        return

    # --- Layer 2 + 3: Deep supervisor + Analyzer (background, non-blocking) ---
    # Deep layer receives fast layer's response so it can evaluate before enriching
    async def _background_enrichment():
        try:
            deep_result = await claude.chat_deep_supervisor(
                chat_id=chat_id,
                user_message=user_text,
                fast_response=fast_response,
                project_id=transcript.project_id,
            )
            if deep_result.get("action") in ("enrich", "correct") and deep_result.get("content"):
                await websocket.send_json(
                    WSAssistantText(
                        text=deep_result["content"],
                        model="deep",
                        is_enrichment=True,
                    ).model_dump()
                )

                # TTS for enrichment
                try:
                    audio_b64 = await tts.synthesize(deep_result["content"])
                    if audio_b64:
                        await websocket.send_json(
                            WSAssistantAudio(data=audio_b64).model_dump()
                        )
                except Exception:
                    pass
        except Exception as e:
            logger.warning(f"Deep supervisor failed: {e}")

    async def _background_analysis():
        try:
            suggestion = await analyzer.analyze(chat_id=chat_id, message=user_text)
            if suggestion:
                await websocket.send_json(
                    WSCardSuggestion(
                        title=suggestion.title,
                        description=suggestion.description,
                        priority=suggestion.priority,
                        source_message_id="",  # TODO: wire up actual message ID
                        confidence=suggestion.confidence,
                    ).model_dump()
                )
        except Exception as e:
            logger.warning(f"Analyzer failed: {e}")

    # Fire and forget background tasks
    asyncio.create_task(_background_enrichment())
    asyncio.create_task(_background_analysis())

    # Back to listening
    await websocket.send_json(WSStatus(state="listening").model_dump())
