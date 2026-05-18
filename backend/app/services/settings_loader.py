"""Settings loader — pure service module for DB-backed app settings.

Lives below the routes layer so services can depend on it without reaching
up into ``app.routes.*``. The HTTP adapter (``routes/settings.py``) re-exports
the helpers for backward compatibility with any caller that still imports
from the route module.
"""

from __future__ import annotations

import json
import logging

from sqlalchemy import select

from app.database import AppSettings, async_session

logger = logging.getLogger(__name__)


_default_worker_model: str = "sonnet"
_default_worker_provider_type: str = ""
_default_worker_endpoint_id: str = ""

_SETTINGS_KEY = "app_settings"


def get_default_worker_model() -> str:
    """Return the default worker model (from settings or 'sonnet' fallback)."""
    return _default_worker_model


def set_default_worker_model(model: str) -> None:
    """Update the cached default worker model (called when settings are loaded)."""
    global _default_worker_model
    if model:
        _default_worker_model = model
        logger.info(f"[Settings] Default worker model set to: {model}")


def get_default_worker_provider_type() -> str:
    """Return the explicit provider override for the default worker (empty = layer alias)."""
    return _default_worker_provider_type


def set_default_worker_provider_type(provider_type: str) -> None:
    """Update the cached default worker provider type. Empty string clears the override."""
    global _default_worker_provider_type
    _default_worker_provider_type = (provider_type or "").strip().lower()


def get_default_worker_endpoint_id() -> str:
    """Return the saved-endpoint id for the default worker (empty = no machine ref)."""
    return _default_worker_endpoint_id


def set_default_worker_endpoint_id(endpoint_id: str) -> None:
    """Update the cached default worker endpoint id. Empty string clears the override."""
    global _default_worker_endpoint_id
    _default_worker_endpoint_id = (endpoint_id or "").strip()


def load_mcp_servers_sync() -> list[dict]:
    """Sync-load user-defined MCP server configs from the app_settings row.

    Called from ``cli_backend._build_mcp_config`` which is sync. Returns the
    raw list (real api_keys — DB has secrets, not the '***' redaction). Empty
    list on any error or when nothing's configured.
    """
    try:
        from app.services.llm.tool_defs import (
            _read_settings_from_db_sync,
            _read_settings_from_file_sync,
        )
        data = _read_settings_from_db_sync() or _read_settings_from_file_sync()
        if not data:
            return []
        servers = data.get("mcp_servers") or []
        return [s for s in servers if isinstance(s, dict)]
    except Exception:
        logger.exception("Failed to load mcp_servers from settings")
        return []


async def _load_settings_from_db() -> dict | None:
    """Load settings from SQLite. Returns None if not found."""
    try:
        async with async_session() as session:
            result = await session.execute(
                select(AppSettings.value).where(AppSettings.key == _SETTINGS_KEY)
            )
            value = result.scalar_one_or_none()
            if value:
                return json.loads(value)
    except Exception:
        logger.exception("Failed to load settings from DB")
    return None
