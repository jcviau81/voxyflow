"""Application configuration via environment variables."""

from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    """Voxyflow configuration. Loaded from .env or environment."""

    # App
    app_name: str = "Voxyflow"
    debug: bool = False
    host: str = "0.0.0.0"
    port: int = 8000

    # Database
    database_url: str = "sqlite+aiosqlite:///./voxyflow.db"

    # Claude API
    claude_api_key: str = ""
    claude_haiku_model: str = "claude-haiku-4-5-20250315"
    claude_opus_model: str = "claude-opus-4-20250514"
    claude_max_tokens: int = 1024

    # TTS
    tts_service_url: str = "http://localhost:5500"
    tts_engine: str = "sherpa-onnx"  # sherpa-onnx | remote

    # STT (Whisper fallback)
    whisper_model: str = "turbo"
    stt_engine: str = "browser"  # browser | whisper

    # Voice
    voice_sample_rate: int = 16000
    voice_channels: int = 1

    # Conversation
    haiku_context_messages: int = 20
    opus_context_messages: int = 100
    analyzer_enabled: bool = True

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


@lru_cache
def get_settings() -> Settings:
    return Settings()
