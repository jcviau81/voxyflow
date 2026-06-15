"""Worker model/provider routing for delegated tasks.

Covers worker-class match, effort resolution, the default-worker provider
override, the haiku→sonnet coding guard, and the Claude-alias-on-non-Claude-
provider remap. Extracted verbatim from worker_pool._execute_event.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from app.services.event_bus import ActionIntent
from app.services.settings_loader import get_default_worker_model

logger = logging.getLogger("voxyflow.orchestration")


@dataclass
class ExecutionPlan:
    """Resolved execution parameters for one delegated worker task."""
    effective_model: str
    endpoint_config: dict | None
    effort: str
    worker_class: dict | None


async def resolve_worker_class(event: ActionIntent) -> dict | None:
    """Try to resolve a worker class for this event.

    Checks event.data["worker_class_id"] first, then tries intent-based matching.
    Returns the resolved worker class dict, or None for default behavior.
    """
    try:
        from app.services.llm.worker_class_resolver import resolve_by_id, resolve_by_intent

        # Explicit worker_class_id takes priority
        wc_id = event.data.get("worker_class_id", "")
        if wc_id:
            wc = await resolve_by_id(wc_id)
            if wc:
                logger.info(
                    "[DeepWorkerPool] Task %s routed to worker class %r (explicit id)",
                    event.task_id, wc.get("name"),
                )
                return wc

        # Try intent-based keyword matching. Pass summary too so long code-name
        # intents like "execute_secu1_real_ssh" still match when the relevant
        # keywords only appear in the task description.
        wc = await resolve_by_intent(event.intent or "", event.summary or "")
        if wc:
            logger.info(
                "[DeepWorkerPool] Task %s routed to worker class %r (intent match: %r)",
                event.task_id, wc.get("name"), event.intent,
            )
            return wc
    except Exception as e:
        logger.warning("[DeepWorkerPool] Worker class resolution failed: %s", e)

    return None


async def resolve_execution_plan(event: ActionIntent) -> ExecutionPlan:
    """Resolve the model / endpoint / effort / worker class for an ActionIntent.

    Precedence: worker_class.model (if matched) > default_worker_model (fallback).
    event.model is the dispatcher's LLM-suggested hint — kept only for logging;
    user-configured Worker Classes and Default Worker Model are authoritative.

    Mutates ``event.data`` with the ``_resolved_worker_class*`` keys exactly as
    the original inlined code did (downstream closeout reads them).
    """
    # Resolve worker class (if any) before registering, so we log the right model.
    _worker_class = await resolve_worker_class(event)

    # Worker reasoning-effort: the matched worker class's effort wins,
    # else the configured default_worker_effort. "" = model/CLI default
    # (no --effort / model_reasoning_effort emitted — historical behavior).
    _effort = ((_worker_class or {}).get("effort") or "").strip()
    if not _effort:
        from app.services.settings_loader import get_default_worker_effort
        _effort = (get_default_worker_effort() or "").strip()

    _explicit_model = event.model  # what the dispatcher explicitly requested
    _effective_model = _explicit_model or get_default_worker_model()
    _endpoint_config: dict | None = None  # resolved endpoint for worker class
    if _worker_class:
        # Worker class with endpoint_id ALWAYS takes precedence — the whole
        # point of a worker class is to route matching intents to a specific
        # endpoint+model. Exception: an explicit "opus" request signals the
        # user/dispatcher wants maximum reasoning power — honour that over
        # the worker class.
        _wc_has_endpoint = bool(_worker_class.get("endpoint_id"))
        _wc_has_model = bool(_worker_class.get("model"))
        _honour_worker_class = (_wc_has_endpoint or _wc_has_model) and _explicit_model != "opus"

        if _honour_worker_class or not _explicit_model:
            _effective_model = _worker_class.get("model") or _effective_model

        # Store worker_class_id in event data for downstream use
        event.data["_resolved_worker_class"] = _worker_class

        # Resolve endpoint config so we can route to the correct provider.
        # Done even without endpoint_id when provider_type is set on the worker
        # class (e.g. "cli") — otherwise downstream falls through to the layer
        # aliases (fast/haiku/opus) which now follow whatever provider the user
        # configured for those layers, ignoring the worker class entirely.
        _wc_has_provider = bool((_worker_class.get("provider_type") or "").strip())
        if (_wc_has_endpoint or _wc_has_provider) and _explicit_model != "opus":
            from app.services.llm.worker_class_resolver import resolve_endpoint_for_class
            _endpoint_config = await resolve_endpoint_for_class(_worker_class)
            if _endpoint_config and (_endpoint_config.get("url") or _endpoint_config.get("provider_type")):
                logger.info(
                    "[DeepWorkerPool] Task %s using worker class %r (%s @ %s, model=%s)",
                    event.task_id, _worker_class.get("name"),
                    _endpoint_config.get("provider_type"),
                    _endpoint_config.get("url") or "(no url)",
                    _effective_model,
                )
                # Forward to closeout so the meta-task uses the same provider.
                event.data["_resolved_worker_class_endpoint"] = _endpoint_config
                event.data["_resolved_worker_model"] = _effective_model

    # Default worker provider override: when no worker_class matched but the
    # user configured an explicit provider for the "default worker" in
    # Settings, route there. Without this, the default worker always falls
    # back to the Fast layer's provider — there'd be no way to e.g. run the
    # default worker on Claude CLI while Fast/Dispatcher runs on Ollama.
    if _endpoint_config is None and _explicit_model != "opus":
        from app.services.settings_loader import (
            get_default_worker_endpoint_id,
            get_default_worker_provider_type,
        )
        _dw_ptype = get_default_worker_provider_type()
        _dw_eid = get_default_worker_endpoint_id()
        if _dw_ptype or _dw_eid:
            from app.services.llm.worker_class_resolver import resolve_endpoint_for_class
            _synthetic_wc = {
                "endpoint_id": _dw_eid,
                "provider_type": _dw_ptype,
                "model": _effective_model,
            }
            _endpoint_config = await resolve_endpoint_for_class(_synthetic_wc)
            if _endpoint_config and (_endpoint_config.get("url") or _endpoint_config.get("provider_type")):
                logger.info(
                    "[DeepWorkerPool] Task %s using default worker override (%s @ %s, model=%s)",
                    event.task_id,
                    _endpoint_config.get("provider_type"),
                    _endpoint_config.get("url") or "(no url)",
                    _effective_model,
                )
                event.data["_resolved_worker_class_endpoint"] = _endpoint_config
                event.data["_resolved_worker_model"] = _effective_model
            else:
                _endpoint_config = None

    # Safety guard: coding intents must never run on Haiku — upgrade to sonnet minimum.
    # Applies regardless of user-configured Worker Classes or Default Worker Model,
    # so even if the user misconfigured the Coding class with Haiku, it gets upgraded.
    # Also catches Quick-class mis-routing (e.g. intent "summarize_code_fixes" matched
    # Quick but is actually coding work) by scanning intent+summary+description.
    from app.services.orchestration.model_resolution import _is_coding_text
    _is_coding_intent = _is_coding_text(
        event.intent,
        event.summary,
        (event.data or {}).get("description"),
    )
    _is_coding_worker_class = (_worker_class or {}).get("name", "").lower() in {
        "coding", "complex coding", "architecture",
    }
    if "haiku" in _effective_model.lower() and (_is_coding_intent or _is_coding_worker_class):
        _effective_model = "claude-sonnet-4-6"
        logger.warning(
            "[ModelGuard] Upgraded haiku → sonnet for coding task "
            "(intent=%r, worker_class=%r, task=%s)",
            event.intent, (_worker_class or {}).get("name"), event.task_id,
        )

    # Final remap: Claude tier aliases ("haiku"/"sonnet"/"opus" and the
    # "claude-*" canonical names) only make sense on a Claude backend.
    # If the resolved provider is something else (codex, openai, ollama, …),
    # the alias becomes a literal model name the provider won't recognise
    # (e.g. Codex CLI rejects "sonnet": "The 'sonnet' model is not
    # supported when using Codex with a ChatGPT account."). Drop the alias
    # and use the worker class's model — or the default worker model — so
    # the user's configured provider model wins.
    _CLAUDE_PROVIDERS = {"cli", "anthropic"}
    _resolved_provider = (_endpoint_config or {}).get("provider_type", "").lower()
    _eff_lower = _effective_model.lower()
    _is_claude_alias = (
        _eff_lower in {"haiku", "sonnet", "opus"}
        or _eff_lower.startswith("claude-")
    )
    if (
        _is_claude_alias
        and _resolved_provider
        and _resolved_provider not in _CLAUDE_PROVIDERS
    ):
        _fallback = (_worker_class or {}).get("model") or get_default_worker_model()
        _fb_lower = (_fallback or "").lower()
        # Only remap if the fallback is a real provider-native model name,
        # not itself a Claude alias (which would just re-trigger the bug).
        if _fallback and _fb_lower not in {"haiku", "sonnet", "opus"} and not _fb_lower.startswith("claude-"):
            logger.info(
                "[ModelRemap] %r is a Claude alias but provider is %r — "
                "using %r instead (task=%s, worker_class=%r)",
                _effective_model, _resolved_provider, _fallback,
                event.task_id, (_worker_class or {}).get("name"),
            )
            _effective_model = _fallback
            if _endpoint_config is not None:
                event.data["_resolved_worker_model"] = _effective_model

    return ExecutionPlan(
        effective_model=_effective_model,
        endpoint_config=_endpoint_config,
        effort=_effort,
        worker_class=_worker_class,
    )
