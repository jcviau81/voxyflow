"""Voice/WebSocket message schemas."""

from typing import Optional, Literal
from pydantic import BaseModel


# ---------------------------------------------------------------------------
# WebSocket message types (JSON text frames)
# ---------------------------------------------------------------------------

class WSMessage(BaseModel):
    """Base WebSocket JSON message."""
    type: str


class WSTranscript(WSMessage):
    """Client → Server: user speech transcript from browser STT."""
    type: Literal["transcript"] = "transcript"
    text: str
    is_final: bool = True
    language: str = "fr"


class WSAudioChunk(WSMessage):
    """Client → Server: raw audio for server-side STT (Whisper fallback)."""
    type: Literal["audio_chunk"] = "audio_chunk"
    data: str  # base64-encoded PCM audio
    sample_rate: int = 16000


class WSAssistantText(WSMessage):
    """Server → Client: assistant text response."""
    type: Literal["assistant_text"] = "assistant_text"
    text: str
    model: str  # haiku | opus
    is_enrichment: bool = False  # True if Opus correction/addition


class WSAssistantAudio(WSMessage):
    """Server → Client: TTS audio response."""
    type: Literal["assistant_audio"] = "assistant_audio"
    data: str  # base64-encoded audio
    format: str = "pcm"  # pcm | opus | mp3
    sample_rate: int = 22050


class WSCardSuggestion(WSMessage):
    """Server → Client: analyzer detected a potential card."""
    type: Literal["card_suggestion"] = "card_suggestion"
    title: str
    description: str
    priority: int = 0
    source_message_id: str
    confidence: float = 0.0


class WSError(WSMessage):
    """Server → Client: error notification."""
    type: Literal["error"] = "error"
    message: str
    code: Optional[str] = None


class WSStatus(WSMessage):
    """Server → Client: status update (processing, listening, etc.)."""
    type: Literal["status"] = "status"
    state: str  # listening | processing | speaking | idle
