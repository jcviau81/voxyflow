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
_briefer_model: str = "haiku"

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


def get_briefer_model() -> str:
    """Return the model used by the Briefer (post-worker synthesis)."""
    return _briefer_model


def set_briefer_model(model: str) -> None:
    """Update the cached Briefer model (called when settings are loaded)."""
    global _briefer_model
    if model:
        _briefer_model = model
        logger.info(f"[Settings] Briefer model set to: {model}")


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
