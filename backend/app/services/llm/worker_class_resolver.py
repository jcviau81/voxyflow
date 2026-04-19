"""Resolve a worker class by id or intent keyword matching."""
from __future__ import annotations

import logging
import re
from functools import lru_cache
from typing import Optional

logger = logging.getLogger(__name__)

# Intent matches outweigh summary matches: a clean intent like "research"
# is a much stronger signal than a stray keyword in a long description
# (e.g. "Quick-start steps" in a research task's summary used to route
# to the Quick class under first-match-wins).
_INTENT_WEIGHT = 3
_SUMMARY_WEIGHT = 1

# Tiebreak: when scores are equal, prefer the heavier model. Bias is
# "if unsure, spend more and get a better answer" rather than silently
# downgrading to a cheap class.
_MODEL_TIER = (("opus", 3), ("sonnet", 2), ("haiku", 1))


def _model_weight(model: str) -> int:
    s = (model or "").lower()
    for token, weight in _MODEL_TIER:
        if token in s:
            return weight
    return 2


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


def _score_class(wc: dict, intent: str, summary: str) -> int:
    score = 0
    for pattern in wc.get("intent_patterns", []):
        pat = (pattern or "").strip()
        if not pat:
            continue
        rx = _word_pattern(pat)
        if intent and rx.search(intent):
            score += _INTENT_WEIGHT
        if summary and rx.search(summary):
            score += _SUMMARY_WEIGHT
    return score


async def resolve_by_intent(intent: str, summary: str = "") -> Optional[dict]:
    """Return the best-matching worker class for the task's text.

    Scoring: each pattern that matches ``intent`` adds 3 points; each match
    in ``summary`` adds 1. Highest total wins. Ties broken by model weight
    (opus > sonnet > haiku).

    Replaces an earlier first-match-wins scheme that mis-routed research
    tasks to the Quick class because the dispatcher injects delivery-format
    words like "Quick-start steps" into the summary.
    """
    if not intent and not summary:
        return None
    classes = await _load_worker_classes()

    scored: list[tuple[int, int, dict]] = []
    for wc in classes:
        s = _score_class(wc, intent, summary)
        if s > 0:
            scored.append((s, _model_weight(wc.get("model", "")), wc))

    if not scored:
        return None

    scored.sort(key=lambda t: (t[0], t[1]), reverse=True)
    best_score, best_weight, best_wc = scored[0]
    logger.info(
        "[WorkerClassResolver] intent=%r → class=%r (score=%d, model_weight=%d, candidates=%d)",
        intent or summary[:60], best_wc.get("name"), best_score, best_weight, len(scored),
    )
    return best_wc


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
