"""Application configuration via environment variables + keyring."""

import os
from pydantic_settings import BaseSettings
from functools import lru_cache


def _get_secret(service: str, key: str, env_var: str = None, default: str = "") -> str:
    """Get secret from keyring → env var → default (in order of priority)."""
    # 1. Try keyring first
    try:
        import keyring

        val = keyring.get_password(service, key)
        if val:
            return val
    except Exception:
        pass  # keyring not available (headless, docker, etc.)

    # 2. Try environment variable
    if env_var:
        val = os.environ.get(env_var)
        if val:
            return val

    # 3. Fall back to default
    return default


class Settings(BaseSettings):
    """Voxyflow configuration. Loaded from keyring → env → .env."""

    # App
    app_name: str = "Voxyflow"
    debug: bool = False
    host: str = "0.0.0.0"
    port: int = 8000

    # Database
    database_url: str = "sqlite+aiosqlite:///./voxyflow.db"

    # Claude API — loaded from keyring → env → .env
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

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        # Override claude_api_key from keyring if available
        if not self.claude_api_key or self.claude_api_key == "placeholder":
            keyring_key = _get_secret(
                "voxyflow", "claude_api_key", "ANTHROPIC_API_KEY"
            )
            if keyring_key:
                self.claude_api_key = keyring_key


@lru_cache
def get_settings() -> Settings:
    return Settings()
