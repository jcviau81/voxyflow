"""
Application configuration via environment variables + keyring.

Config hierarchy (highest priority wins):
  1. Environment variables (e.g. DATABASE_URL=...)
  2. .env file (backend/.env — loaded by pydantic-settings)
  3. Defaults defined below (XDG-compliant paths)

What goes WHERE:
  - .env / env vars  → Infrastructure: DB path, host, port, API keys, external URLs
  - DB app_settings  → App preferences: LLM models, TTS config, UI settings
  - This file         → Sensible defaults only (never instance-specific paths)
"""

import os
from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict
from functools import lru_cache

# Canonical data directory — follows XDG user data pattern
_VOXYFLOW_HOME = Path.home() / ".voxyflow"

# Resolve .env relative to the backend/ directory (works regardless of cwd)
_BACKEND_DIR = Path(__file__).resolve().parent.parent
_ENV_FILE = _BACKEND_DIR / ".env"


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
    """Voxyflow configuration. Loaded from keyring → env → .env → defaults."""

    model_config = SettingsConfigDict(
        env_file=str(_ENV_FILE),
        env_file_encoding="utf-8",
    )

    # App
    app_name: str = "Voxyflow"
    debug: bool = False
    host: str = "0.0.0.0"
    port: int = 8000

    # Database — default: ~/.voxyflow/voxyflow.db (XDG user data dir pattern)
    database_url: str = f"sqlite+aiosqlite:///{_VOXYFLOW_HOME / 'voxyflow.db'}"

    # Claude API — native Anthropic SDK (preferred)
    claude_use_native: bool = False   # False = OpenAI-compatible proxy (claude-max-api). True requires direct API access.
    claude_api_key: str = ""         # Loaded from keyring / env ANTHROPIC_API_KEY
    claude_api_base: str = ""        # Empty = default api.anthropic.com

    # Claude API via proxy (OpenAI-compatible, fallback when claude_use_native=False)
    claude_proxy_url: str = "http://localhost:3457/v1"
    claude_fast_model: str = "claude-haiku-4-6"
    claude_sonnet_model: str = "claude-sonnet-4-6"
    claude_deep_model: str = "claude-opus-4-6"
    claude_analyzer_model: str = "claude-sonnet-4-6"
    claude_max_tokens: int = 1024           # Legacy fallback — prefer model-specific below
    claude_max_tokens_haiku: int = 8192
    claude_max_tokens_sonnet: int = 16000
    claude_max_tokens_opus: int = 32000

    # TTS/STT — now 100% client-side (Whisper WASM + Web Speech API + browser speechSynthesis)
    # Legacy config kept for scheduler health check compatibility
    tts_service_url: str = ""  # No longer used — TTS is browser-side

    # Conversation
    fast_context_messages: int = 20
    deep_context_messages: int = 100
    chat_window_size: int = 10  # sliding window: keep N recent messages verbatim, summarize older
    analyzer_enabled: bool = True
    delegate_safety_net_enabled: bool = True

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        # Ensure the data directory exists
        _VOXYFLOW_HOME.mkdir(parents=True, exist_ok=True)
        # Load claude_api_key from keyring → env if not already set
        if not self.claude_api_key or self.claude_api_key in ("placeholder", "not-needed"):
            keyring_key = _get_secret(
                "voxyflow", "claude_api_key", "ANTHROPIC_API_KEY"
            )
            if keyring_key:
                self.claude_api_key = keyring_key


@lru_cache
def get_settings() -> Settings:
    return Settings()
