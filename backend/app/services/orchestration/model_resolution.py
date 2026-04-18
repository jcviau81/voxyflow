"""Worker model resolution — card preferred_model + coding/lightweight guards.

Both the native tool_use delegate path and the XML delegate path in
``chat_orchestration`` run the same sequence of overrides to pick the model /
worker class for a delegated task. Keeping the logic in one helper avoids
drift (the two sites were copy-pasted; a bugfix in one silently lost on the
other).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from app.services.direct_executor import CRUD_SIMPLE_INTENTS
from app.services.orchestration.worker_pool import LIGHTWEIGHT_INTENTS

logger = logging.getLogger("voxyflow.orchestration.model_resolution")


_VALID_MODELS = ("haiku", "sonnet", "opus")

# Keywords in a delegate description that force a haiku → sonnet upgrade.
# Haiku is not reliable enough to pick the right MCP tool for code-editing
# tasks (see GitHub issue #4) — we upgrade defensively when we see these.
_CODING_KEYWORDS = frozenset({
    "fix", "implement", "refactor", "write", "code", "debug",
    "build", "create function", "add feature", "patch",
})


@dataclass(frozen=True)
class ResolvedWorker:
    model: str  # "haiku" | "sonnet" | "opus"
    worker_class_id: str | None  # set when ``card.preferred_model`` is a UUID, not a tier
    intent_type: str  # "complex" | "crud_simple"


def _is_coding_description(description: str | None) -> bool:
    if not description:
        return False
    lower = description.lower()
    return any(kw in lower for kw in _CODING_KEYWORDS)


def resolve_worker_model(
    *,
    data: dict,
    card_context: dict | None,
    intent: str,
    complexity: str,
) -> ResolvedWorker:
    """Pick the model + intent_type for a delegated task.

    Ordering (matches the original inlined logic in chat_orchestration):
      1. Start with ``data.model`` (clamped to haiku/sonnet/opus, default sonnet).
      2. If the card has ``preferred_model``, it wins — either a direct tier
         or a worker-class UUID (the pool resolves UUIDs later).
      3. Coding-keyword detection: haiku → sonnet on obvious code tasks,
         unless a worker-class override is in effect.
      4. Lightweight-intent guard: haiku is only allowed for intents in
         ``LIGHTWEIGHT_INTENTS`` (enrich/summarize/research/review).
      5. intent_type = "complex" when model=opus or complexity=complex,
         "crud_simple" for create/move/update_card, else "complex".
    """
    model = data.get("model") or "sonnet"
    if model not in _VALID_MODELS:
        model = "sonnet"

    worker_class_id: str | None = None
    card_preferred = card_context.get("preferred_model") if card_context else None
    if card_preferred:
        if card_preferred in _VALID_MODELS:
            logger.info(f"[ModelOverride] Card preferred_model={card_preferred} (was {model})")
            model = card_preferred
        else:
            worker_class_id = card_preferred
            logger.info(f"[ModelOverride] Card preferred_model is worker class id={card_preferred}")

    if not worker_class_id and model == "haiku" and _is_coding_description(data.get("description")):
        logger.info(f"[ModelUpgrade] Upgraded haiku → sonnet (coding task detected: {intent})")
        model = "sonnet"

    if not worker_class_id and model == "haiku" and intent.lower() not in LIGHTWEIGHT_INTENTS:
        logger.info(f"[ModelUpgrade] Upgraded haiku → sonnet (intent '{intent}' not in LIGHTWEIGHT_INTENTS)")
        model = "sonnet"

    if complexity == "complex" or model == "opus":
        intent_type = "complex"
    elif intent in CRUD_SIMPLE_INTENTS:
        intent_type = "crud_simple"
    else:
        intent_type = "complex"

    return ResolvedWorker(model=model, worker_class_id=worker_class_id, intent_type=intent_type)
