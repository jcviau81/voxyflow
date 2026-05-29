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

  VOXYFLOW_SANDBOX_DIR — workers' sandbox for file operations (cwd for system.exec)
                          Override: VOXYFLOW_SANDBOX_DIR env var
                          Default: ~/.voxyflow/sandbox
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
VOXYFLOW_SANDBOX_DIR = Path(os.environ.get("VOXYFLOW_SANDBOX_DIR", str(VOXYFLOW_DATA_DIR / "sandbox")))
SETTINGS_FILE = VOXYFLOW_DATA_DIR / "settings.json"  # lives in data dir (outside repo)


def workspace_workdir(workspace_id: str | None) -> Path:
    """Per-workspace working directory under the sandbox, keyed by workspace ID.

    Workers default here so files they create (via ``system.exec`` shell
    commands or ``file.write``) land inside their own workspace area instead of
    scattering into ``/tmp`` or the shared sandbox root. Keyed by the stable
    workspace **ID** (UUID or ``"system-main"``), never the title — consistent
    with the workspace-isolation invariant (titles change on rename and orphan
    data). The directory is created on demand; on failure we fall back to the
    sandbox root so callers always get a usable, in-sandbox path.
    """
    import re as _re

    sandbox = Path(VOXYFLOW_SANDBOX_DIR).expanduser().resolve()
    ws_id = (workspace_id or "").strip() or "system-main"
    safe = _re.sub(r"[^A-Za-z0-9._-]", "-", ws_id) or "system-main"
    workdir = sandbox / "workspaces" / safe
    try:
        workdir.mkdir(parents=True, exist_ok=True)
    except OSError:
        return sandbox
    return workdir

# Resolve .env relative to the backend/ directory (works regardless of cwd)
_BACKEND_DIR = Path(__file__).resolve().parent.parent
_ENV_FILE = _BACKEND_DIR / ".env"


def _keyring_get_with_timeout(service: str, key: str, timeout: float) -> str | None:
    """Call keyring.get_password in a daemon thread and bail after `timeout`.

    Why: on Linux the default backend is SecretService over D-Bus. If the
    user-session keyring (gnome-keyring-daemon / secret-service) is wedged,
    keyring.get_password blocks indefinitely — which froze backend startup
    in the past since this is called at import time. Hard timeout + env-var
    fallback keeps startup unblockable.
    """
    import threading
    result: dict[str, str | None] = {"val": None}

    def _call() -> None:
        try:
            import keyring
            result["val"] = keyring.get_password(service, key)
        except Exception as e:
            logger.debug("keyring not available (%s) — skipping", e)

    t = threading.Thread(target=_call, daemon=True)
    t.start()
    t.join(timeout)
    if t.is_alive():
        logger.warning(
            "keyring.get_password(%s, %s) hung > %.1fs — falling back to env",
            service, key, timeout,
        )
        return None
    return result["val"]


def _get_secret(service: str, key: str, env_var: str = None, default: str = "") -> str:
    """Get secret from keyring → env var → default (in order of priority)."""
    val = _keyring_get_with_timeout(service, key, timeout=1.5)
    if val:
        return val

    if env_var:
        val = os.environ.get(env_var)
        if val:
            return val

    return default


class Settings(BaseSettings):
    """Voxyflow configuration. Loaded from keyring → env → .env → defaults."""

    model_config = SettingsConfigDict(
        env_file=str(_ENV_FILE),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # App
    app_name: str = "Voxyflow"
    debug: bool = False
    host: str = "0.0.0.0"
    port: int = 8000

    # Reserved ports — surfaced into dispatcher + worker prompts so neither
    # delegates a workspace that would collide with the supervisor.
    # `port` above IS the backend port; we keep a separate name here so the
    # prompt text reads naturally ("backend on 8000, frontend on 18789").
    voxyflow_backend_port: int = 8000     # uvicorn — same as `port`, exposed for prompts
    voxyflow_frontend_port: int = 18789   # Caddy reverse proxy serving the React build

    # Database — default: ~/.voxyflow/voxyflow.db (respects VOXYFLOW_DATA_DIR)
    database_url: str = f"sqlite+aiosqlite:///{VOXYFLOW_DATA_DIR / 'voxyflow.db'}"

    # Claude Code CLI — spawn `claude -p` subprocesses (uses Max subscription)
    claude_use_cli: bool = False     # True = CLI subprocess path (takes precedence over native/proxy)
    claude_cli_path: str = "claude"  # Path to claude CLI binary
    cli_max_concurrent: int = 10        # DEPRECATED — use cli_session_concurrent + cli_worker_concurrent
    cli_min_spacing_ms: int = 0         # Min ms between CLI calls (CliRateGate)
    cli_session_concurrent: int = 5     # Chat/dispatcher CLI slots (global, shared across all sessions)
    cli_worker_concurrent: int = 15     # Worker CLI slots (global, shared across all sessions)
    max_workers: int = 15               # Per-session DeepWorkerPool concurrency cap (one pool per chat session)

    # Claude API — native Anthropic SDK (preferred)
    claude_use_native: bool = False   # False = OpenAI-compatible proxy (claude-max-api). True requires direct API access.
    claude_api_key: str = ""         # Loaded from keyring / env ANTHROPIC_API_KEY
    claude_api_base: str = ""        # Empty = default api.anthropic.com

    # Claude via OpenAI-compatible HTTP endpoint (fallback when claude_use_native=False).
    # The historical `voxyflow-proxy` Claude-Max proxy (port 3457) is retired
    # — see docs/CONFIG.md. Override `claude_proxy_url` only if you point the
    # client at a self-hosted OpenAI-compatible endpoint.
    claude_proxy_url: str = "http://localhost:3457/v1"
    searxng_url: str = "http://localhost:8888"
    claude_fast_model: str = "claude-haiku-4-6"
    claude_sonnet_model: str = "claude-sonnet-4-6"
    claude_deep_model: str = "claude-opus-4-7"
    claude_max_tokens: int = 1024           # Legacy fallback — prefer model-specific below
    claude_max_tokens_haiku: int = 8192
    claude_max_tokens_sonnet: int = 16000
    claude_max_tokens_opus: int = 32000

    # Startup pre-warm — eagerly load ChromaDB HNSW indexes + KG pinned cache
    # so the first user message doesn't pay the cold-start cost (~500–800 ms).
    # Disable if you want a minimal-footprint startup (e.g. short-lived test runs).
    voxyflow_warmup_on_startup: bool = True

    # Conversation
    fast_context_messages: int = 20
    deep_context_messages: int = 100
    chat_window_size: int = 6  # sliding window: keep N recent messages verbatim, summarize older

    # Time / locale — used to render "current time" in the dispatcher prompt and
    # to anchor per-message timestamps so the model can talk about "ce matin",
    # "tantôt", "il y a 2h" without hallucinating the hour.
    voxyflow_timezone: str = "America/Toronto"

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        # Ensure all directories exist
        VOXYFLOW_DIR.mkdir(parents=True, exist_ok=True)
        VOXYFLOW_DATA_DIR.mkdir(parents=True, exist_ok=True)
        VOXYFLOW_SANDBOX_DIR.mkdir(parents=True, exist_ok=True)
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
