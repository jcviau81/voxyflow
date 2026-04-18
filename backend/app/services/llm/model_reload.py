"""Hot-reload helper for ClaudeService layer configuration.

Extracted from ``claude_service.py`` so the reload logic — which fans out
across the multi-provider factory, native Anthropic SDK, and OpenAI-compat
proxy paths — lives in one focused module.

The ``reload_layer_models(service)`` function mutates attributes on the
provided ``ClaudeService`` instance: ``{layer}_model``, ``{layer}_client``,
``{layer}_client_type``, ``{layer}_provider``, ``{layer}_context_1m`` for
each of fast/deep/haiku.
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from app.config import get_settings
from app.services.llm.client_factory import (
    _make_anthropic_client,
    _make_openai_client,
)
from app.services.llm.model_utils import _resolve_model
from app.services.llm.tool_defs import (
    _get_api_key_from_settings,
    _load_model_overrides,
)

if TYPE_CHECKING:
    from app.services.claude_service import ClaudeService

logger = logging.getLogger(__name__)


def reload_layer_models(service: "ClaudeService") -> None:
    """Hot-reload model/provider config from settings.json without restarting.

    Supports the multi-provider architecture: when a layer config contains
    an explicit ``provider_type`` (e.g. "ollama", "groq", "openai"), the
    matching ``LLMProvider`` is instantiated and the raw SDK client is
    configured to point at the right endpoint.  The existing ``client_type``
    attribute is kept for backward compatibility with api_caller.py dispatch.
    """
    from app.services.llm.provider_factory import get_provider, infer_provider_type

    config = get_settings()
    overrides = _load_model_overrides()
    default_api_key = config.claude_api_key

    # Update default worker model from settings
    from app.services.settings_loader import set_default_worker_model
    dwm = overrides.get("default_worker_model", "")
    if dwm:
        set_default_worker_model(dwm)

    for layer, attr_prefix, default_model in [
        ("fast", "fast", config.claude_sonnet_model),
        ("deep", "deep", config.claude_deep_model),
        ("haiku", "haiku", "claude-haiku-4"),
    ]:
        cfg = overrides.get(layer, {})
        model_raw = cfg.get("model", "").strip()
        model = _resolve_model(model_raw or default_model)
        key = _get_api_key_from_settings(cfg) or default_api_key
        purl = cfg.get("provider_url", "")

        # Explicit provider_type in settings takes precedence over env-var flags
        explicit_ptype = cfg.get("provider_type", "").strip().lower()

        if explicit_ptype == "cli" or (service.use_cli and not explicit_ptype):
            # CLI mode — explicit "cli" type or env flag with no override
            client = None
            client_type = "cli"
            provider = None

        elif explicit_ptype and explicit_ptype != "cli":
            # New multi-provider path — use provider_factory
            try:
                provider = get_provider(
                    provider_type=explicit_ptype,
                    url=purl,
                    api_key=key,
                )
                # For OpenAI-compatible providers (ollama, groq, mistral, etc.)
                # we reuse the existing openai client_type so api_caller.py
                # dispatches via _call_api_openai() without any changes.
                if explicit_ptype == "anthropic":
                    client = _make_anthropic_client(key, purl or config.claude_api_base)
                    client_type = "anthropic"
                else:
                    # All OpenAI-compat providers: set up client pointing at their URL
                    from app.services.llm.client_factory import _make_openai_client as _mkoa
                    effective_url = purl or getattr(provider, "_url", config.claude_proxy_url)
                    client = _mkoa(effective_url, key or "not-needed")
                    client_type = "openai"
            except Exception as exc:
                logger.warning(
                    "[ClaudeService] Failed to init provider '%s' for %s layer: %s — falling back to proxy",
                    explicit_ptype, layer, exc,
                )
                client = _make_openai_client(purl or config.claude_proxy_url, key or default_api_key)
                client_type = "openai"
                provider = None

        elif service.use_native and key and ("claude" in model.lower() or "anthropic" in purl.lower()):
            # Native Anthropic SDK
            client = _make_anthropic_client(key, purl or config.claude_api_base)
            client_type = "anthropic"
            provider = None

        else:
            # Auto-detect from URL/model for backward compat
            auto_ptype = infer_provider_type(purl, model)
            try:
                provider = get_provider(
                    provider_type=auto_ptype,
                    url=purl or config.claude_proxy_url,
                    api_key=key or default_api_key,
                )
            except Exception:
                provider = None
            client = _make_openai_client(purl or config.claude_proxy_url, key or default_api_key)
            client_type = "openai"

        setattr(service, f"{attr_prefix}_model", model)
        setattr(service, f"{attr_prefix}_client", client)
        setattr(service, f"{attr_prefix}_client_type", client_type)
        # Store provider instance for future direct calls (capability checks, etc.)
        setattr(service, f"{attr_prefix}_provider", provider)
        setattr(service, f"{attr_prefix}_context_1m", bool(cfg.get("context_1m", False)))

    # Log effective URLs for layers that use a non-default provider
    layer_details = []
    for lbl, attr_prefix in [("fast", "fast"), ("deep", "deep"), ("haiku", "haiku")]:
        m = getattr(service, f"{attr_prefix}_model")
        ct = getattr(service, f"{attr_prefix}_client_type")
        layer_details.append(f"{lbl}={m}({ct})")
    logger.info(f"ClaudeService reloaded — {' | '.join(layer_details)}")
