"""
Application configuration via environment variables + keyring.

== TWO-TIER CONFIG SYSTEM ==

Tier 1 — Infrastructure (this file, pydantic-settings):
  Priority: env vars > .env file > defaults here
  Contains: DB path, host/port, API keys, external URLs
  Loaded once at startup via get_settings().

Tier 2 — App settings (routes/settings.py, DB app_settings table):
  Priority: DB > settings.json (auto-migrated into DB on first load) > defaults
  Contains: LLM model choices, TTS config, personality, UI preferences
  Managed via the Settings UI; DB is the source of truth after first run.

== CANONICAL PATHS (import from here, don't redefine) ==

  VOXYFLOW_DIR  — app directory (source code, personality/ system prompts)
                  Override: VOXYFLOW_DIR env var
                  Default: ~/voxyflow

  VOXYFLOW_DATA_DIR — data directory (SQLite DB, settings.json, worker sessions, jobs)
                       Override: VOXYFLOW_DATA_DIR env var
                       Default: ~/.voxyflow  ← settings.json, voxyflow.db live here (never in the repo)

  VOXYFLOW_WORKSPACE_DIR — workspace for projects and file operations
                            Override: VOXYFLOW_WORKSPACE_DIR env var
                            Default: ~/.voxyflow/workspace
"""

import logging
import os
from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict
from functools import lru_cache

logger = logging.getLogger(__name__)

# Canonical path constants — import these instead of recomputing in each module
VOXYFLOW_DIR = Path(os.environ.get("VOXYFLOW_DIR", str(Path.home() / ".voxyflow")))
VOXYFLOW_DATA_DIR = Path(os.environ.get("VOXYFLOW_DATA_DIR", str(Path.home() / ".voxyflow")))
VOXYFLOW_WORKSPACE_DIR = Path(os.environ.get("VOXYFLOW_WORKSPACE_DIR", str(VOXYFLOW_DATA_DIR / "workspace")))
SETTINGS_FILE = VOXYFLOW_DATA_DIR / "settings.json"  # lives in data dir (outside repo)

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
    except Exception as e:
        logger.debug("keyring not available (%s) — skipping", e)

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

    # Database — default: ~/.voxyflow/voxyflow.db (respects VOXYFLOW_DATA_DIR)
    database_url: str = f"sqlite+aiosqlite:///{VOXYFLOW_DATA_DIR / 'voxyflow.db'}"

    # Claude Code CLI — spawn `claude -p` subprocesses (uses Max subscription)
    claude_use_cli: bool = False     # True = CLI subprocess path (takes precedence over native/proxy)
    claude_cli_path: str = "claude"  # Path to claude CLI binary
    cli_max_concurrent: int = 10        # DEPRECATED — use cli_session_concurrent + cli_worker_concurrent
    cli_min_spacing_ms: int = 0         # Min ms between CLI calls (CliRateGate)
    cli_session_concurrent: int = 5     # Chat/dispatcher CLI slots
    cli_worker_concurrent: int = 15     # Worker CLI slots
    max_workers: int = 15               # Max parallel workers in DeepWorkerPool

    # Claude API — native Anthropic SDK (preferred)
    claude_use_native: bool = False   # False = OpenAI-compatible proxy (claude-max-api). True requires direct API access.
    claude_api_key: str = ""         # Loaded from keyring / env ANTHROPIC_API_KEY
    claude_api_base: str = ""        # Empty = default api.anthropic.com

    # Claude API via proxy (OpenAI-compatible, fallback when claude_use_native=False)
    claude_proxy_url: str = "http://localhost:3457/v1"
    claude_fast_model: str = "claude-haiku-4-6"
    claude_sonnet_model: str = "claude-sonnet-4-6"
    claude_deep_model: str = "claude-opus-4-6"
    claude_max_tokens: int = 1024           # Legacy fallback — prefer model-specific below
    claude_max_tokens_haiku: int = 8192
    claude_max_tokens_sonnet: int = 16000
    claude_max_tokens_opus: int = 32000

    # Conversation
    fast_context_messages: int = 20
    deep_context_messages: int = 100
    chat_window_size: int = 6  # sliding window: keep N recent messages verbatim, summarize older

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        # Ensure all directories exist
        VOXYFLOW_DIR.mkdir(parents=True, exist_ok=True)
        VOXYFLOW_DATA_DIR.mkdir(parents=True, exist_ok=True)
        VOXYFLOW_WORKSPACE_DIR.mkdir(parents=True, exist_ok=True)
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
