"""Resolve a worker class by id or intent keyword matching."""
from __future__ import annotations

import logging
from typing import Optional

logger = logging.getLogger(__name__)


async def _load_worker_classes() -> list[dict]:
    """Load worker classes from settings DB, falling back to defaults."""
    from app.routes.settings import _load_settings_from_db
    from app.routes.models import DEFAULT_WORKER_CLASSES
    data = await _load_settings_from_db()
    if data:
        classes = data.get("models", {}).get("worker_classes", [])
        if classes:
            return classes
    return list(DEFAULT_WORKER_CLASSES)


async def resolve_by_id(worker_class_id: str) -> Optional[dict]:
    """Return worker class config dict by id, or None."""
    if not worker_class_id:
        return None
    classes = await _load_worker_classes()
    for wc in classes:
        if wc.get("id") == worker_class_id:
            return wc
    return None


async def resolve_by_intent(intent: str) -> Optional[dict]:
    """Return first worker class whose intent_patterns match the intent string (case-insensitive).

    Each pattern is checked as a substring of the intent.
    """
    if not intent:
        return None
    classes = await _load_worker_classes()
    intent_lower = intent.lower()
    for wc in classes:
        for pattern in wc.get("intent_patterns", []):
            if pattern.lower() in intent_lower:
                logger.info(
                    "[WorkerClassResolver] Matched intent %r to worker class %r (pattern=%r)",
                    intent, wc.get("name"), pattern,
                )
                return wc
    return None


async def resolve_endpoint_for_class(wc: dict) -> dict:
    """Given a worker class dict, resolve its endpoint_id to url/api_key/provider_type.

    Returns a dict with keys: provider_type, url, api_key, model.
    """
    result = {
        "provider_type": wc.get("provider_type", ""),
        "url": "",
        "api_key": "",
        "model": wc.get("model", ""),
    }

    endpoint_id = wc.get("endpoint_id", "")
    if endpoint_id:
        from app.routes.settings import _load_settings_from_db
        data = await _load_settings_from_db()
        if data:
            for ep in data.get("models", {}).get("endpoints", []):
                if ep.get("id") == endpoint_id:
                    result["provider_type"] = ep.get("provider_type", result["provider_type"])
                    result["url"] = ep.get("url", "")
                    result["api_key"] = ep.get("api_key", "")
                    break

    return result
