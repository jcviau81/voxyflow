"""Resolve a worker class by id or intent keyword matching."""
from __future__ import annotations

import logging
import re
from functools import lru_cache
from typing import Optional

logger = logging.getLogger(__name__)


@lru_cache(maxsize=256)
def _word_pattern(keyword: str) -> re.Pattern[str]:
    """Compile a case-insensitive alphanumeric-boundary regex for *keyword*.

    Uses alphanumeric lookarounds instead of ``\\b`` so that ``_`` and ``-``
    count as separators. This lets patterns like ``"fix"`` match snake_case
    action names like ``"fix_login_bug"`` (where ``\\b`` fails because ``_``
    is a word character). Still blocks substring hits like ``'code'`` in
    ``'gcode.py'`` (the ``.`` is non-alphanumeric, the ``g`` is alphanumeric
    so ``'code'`` in ``'barcode'`` still rejects).
    """
    return re.compile(
        rf"(?<![a-zA-Z0-9]){re.escape(keyword.lower())}(?![a-zA-Z0-9])",
        re.IGNORECASE,
    )


async def _load_worker_classes() -> list[dict]:
    """Load worker classes from settings DB, falling back to defaults."""
    from app.services.settings_loader import _load_settings_from_db
    from app.services.worker_classes import DEFAULT_WORKER_CLASSES
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


async def resolve_by_intent(intent: str, summary: str = "") -> Optional[dict]:
    """Return the first worker class whose patterns match the task's text.

    Matches ``intent_patterns`` as whole words (regex ``\\b``) against the
    concatenation of ``intent`` and ``summary``. Summary is included because
    the dispatcher sometimes emits a short code-name intent (e.g.
    ``execute_secu1_real_ssh``) whose keywords only appear in the description.
    """
    if not intent and not summary:
        return None
    classes = await _load_worker_classes()
    haystack = f"{intent}\n{summary}"
    for wc in classes:
        for pattern in wc.get("intent_patterns", []):
            pat = (pattern or "").strip()
            if not pat:
                continue
            if _word_pattern(pat).search(haystack):
                logger.info(
                    "[WorkerClassResolver] Matched %r to worker class %r (pattern=%r)",
                    intent or summary[:60], wc.get("name"), pat,
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
        from app.services.settings_loader import _load_settings_from_db
        data = await _load_settings_from_db()
        if data:
            for ep in data.get("models", {}).get("endpoints", []):
                if ep.get("id") == endpoint_id:
                    result["provider_type"] = ep.get("provider_type", result["provider_type"])
                    result["url"] = ep.get("url", "")
                    result["api_key"] = ep.get("api_key", "")
                    break

    return result
