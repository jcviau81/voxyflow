"""Model discovery and provider detection endpoints."""

import json
import logging
import os
import time
from pathlib import Path

import httpx
from fastapi import APIRouter, Query
from pydantic import BaseModel

from app.config import get_settings
from app.services.llm.provider_factory import infer_provider_type, list_known_providers

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/models", tags=["models"])

_VOXYFLOW_DATA_DIR = Path(os.environ.get("VOXYFLOW_DATA_DIR", str(Path.home() / ".voxyflow")))
_SETTINGS_FILE = _VOXYFLOW_DATA_DIR / "settings.json"


# ---------------------------------------------------------------------------
# Pydantic response models
# ---------------------------------------------------------------------------

class OllamaModel(BaseModel):
    name: str
    size_gb: float


class ProviderInfo(BaseModel):
    type: str
    label: str
    reachable: bool
    url: str


class EndpointInfo(BaseModel):
    """Reachability status for a named user endpoint."""
    id: str
    name: str
    provider_type: str
    url: str
    reachable: bool


class LayerInfo(BaseModel):
    model: str
    provider_type: str
    provider_url: str
    enabled: bool
    endpoint_id: str = ""


class AvailableModelsResponse(BaseModel):
    layers: dict[str, LayerInfo]
    providers: dict[str, ProviderInfo]
    endpoints: list[EndpointInfo] = []


class ModelCapabilities(BaseModel):
    model: str
    provider: str
    supports_tools: bool
    supports_vision: bool
    context_window: int
    max_output_tokens: int


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load_models_cfg() -> dict:
    """Load the models section from settings (DB-backed settings.json)."""
    if _SETTINGS_FILE.exists():
        try:
            with open(_SETTINGS_FILE) as f:
                return json.load(f).get("models", {})
        except Exception as e:
            logger.warning("Failed to read settings.json: %s", e)
    return {}


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("/providers")
async def list_providers():
    """Return metadata for all supported LLM providers."""
    return list_known_providers()


@router.get("/ollama", response_model=list[OllamaModel])
async def list_ollama_models(url: str = Query(default="http://localhost:11434")):
    """Fetch available models from an Ollama instance. Returns empty list if unreachable."""
    api_url = url.rstrip("/") + "/api/tags"
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(api_url)
            resp.raise_for_status()
            data = resp.json()
    except Exception as e:
        logger.debug("Ollama unreachable at %s: %s", api_url, e)
        return []

    models = []
    for m in data.get("models", []):
        size_bytes = m.get("size", 0)
        size_gb = round(size_bytes / (1024 ** 3), 1) if size_bytes else 0.0
        models.append(OllamaModel(name=m.get("name", "unknown"), size_gb=size_gb))
    return models


@router.get("/list")
async def list_models_for_provider(
    provider_type: str = Query(default="", description="Provider type, e.g. 'ollama', 'openai'"),
    url: str = Query(default="", description="Provider base URL"),
    api_key: str = Query(default="", description="API key (optional)"),
    endpoint_id: str = Query(default="", description="Named endpoint id — resolves url/api_key/type from saved endpoints"),
):
    """List available models for a given provider or named endpoint.

    Returns a list of model name strings. Empty list if unreachable or unsupported.
    Pass either (provider_type, url) OR endpoint_id.
    """
    from app.services.llm.provider_factory import get_provider

    # Resolve named endpoint
    if endpoint_id:
        models_cfg = _load_models_cfg()
        for ep in models_cfg.get("endpoints", []):
            if ep.get("id") == endpoint_id:
                provider_type = ep.get("provider_type", provider_type)
                url = ep.get("url", url)
                api_key = ep.get("api_key", api_key)
                break

    if not provider_type:
        return []

    if provider_type == "cli":
        return ["claude-haiku-4-5-20251001", "claude-sonnet-4-6", "claude-opus-4-6"]

    if provider_type == "anthropic":
        from app.services.llm.providers.anthropic_provider import _KNOWN_MODELS
        return _KNOWN_MODELS

    try:
        provider = get_provider(provider_type=provider_type, url=url, api_key=api_key)
        return await provider.list_models()
    except Exception as e:
        logger.warning("[models/list] Failed to list models for %s: %s", provider_type, e)
        return []


@router.get("/capabilities", response_model=ModelCapabilities)
async def get_model_capabilities(model: str = Query(...)):
    """Return capability info for a model name (uses static registry)."""
    from app.services.llm import capability_registry as caps

    entry = caps.lookup(model)
    provider = infer_provider_type("", model)
    return ModelCapabilities(
        model=model,
        provider=provider,
        supports_tools=entry.supports_tools,
        supports_vision=entry.supports_vision,
        context_window=entry.context_window,
        max_output_tokens=entry.max_output_tokens,
    )


@router.get("/available", response_model=AvailableModelsResponse)
async def get_available_models():
    """Return current model config per layer + detected provider availability."""
    import asyncio
    models_cfg = _load_models_cfg()

    # Build layers info
    layers: dict[str, LayerInfo] = {}
    for layer_name in ("fast", "deep"):
        cfg = models_cfg.get(layer_name, {})
        purl = cfg.get("provider_url", "")
        mdl = cfg.get("model", "")
        ptype = cfg.get("provider_type", "") or infer_provider_type(purl, mdl)
        layers[layer_name] = LayerInfo(
            model=mdl,
            provider_type=ptype,
            provider_url=purl,
            enabled=cfg.get("enabled", True),
            endpoint_id=cfg.get("endpoint_id", ""),
        )

    from app.services.llm.provider_factory import get_provider

    async def _probe_provider(ptype: str, label: str, url: str) -> tuple[str, ProviderInfo]:
        reachable = False
        try:
            if ptype == "anthropic":
                cfg = get_settings()
                reachable = bool(cfg.claude_api_key and cfg.claude_api_key not in ("placeholder", "not-needed"))
            else:
                provider = get_provider(provider_type=ptype, url=url)
                reachable = await provider.is_reachable()
        except Exception:
            reachable = False
        return ptype, ProviderInfo(type=ptype, label=label, reachable=reachable, url=url)

    async def _probe_endpoint(ep: dict) -> EndpointInfo:
        reachable = False
        try:
            provider = get_provider(provider_type=ep["provider_type"], url=ep["url"], api_key=ep.get("api_key", ""))
            reachable = await provider.is_reachable()
        except Exception:
            reachable = False
        return EndpointInfo(
            id=ep.get("id", ""),
            name=ep.get("name", ep.get("url", "")),
            provider_type=ep.get("provider_type", ""),
            url=ep.get("url", ""),
            reachable=reachable,
        )

    # --- Probe built-in provider types (one per type, default URL) ---
    providers: dict[str, ProviderInfo] = {}
    known = list_known_providers()

    urls_to_probe: dict[str, tuple[str, str]] = {}  # type → (label, url)
    for p in known:
        ptype = p["type"]
        if ptype == "cli":
            continue
        custom_url = ""
        for layer_cfg in models_cfg.values():
            if isinstance(layer_cfg, dict):
                layer_ptype = layer_cfg.get("provider_type", "")
                if layer_ptype == ptype:
                    custom_url = layer_cfg.get("provider_url", "")
                    break
        url = custom_url or p["default_url"]
        urls_to_probe[ptype] = (p["label"], url)

    provider_tasks = [_probe_provider(pt, lbl, u) for pt, (lbl, u) in urls_to_probe.items()]

    # --- Probe named user endpoints ---
    saved_endpoints: list[dict] = models_cfg.get("endpoints", [])
    endpoint_tasks = [_probe_endpoint(ep) for ep in saved_endpoints if ep.get("url")]

    all_results = await asyncio.gather(*provider_tasks, *endpoint_tasks, return_exceptions=True)

    provider_results = all_results[:len(provider_tasks)]
    endpoint_results = all_results[len(provider_tasks):]

    for result in provider_results:
        if isinstance(result, Exception):
            continue
        ptype, info = result
        providers[ptype] = info

    endpoint_infos: list[EndpointInfo] = [r for r in endpoint_results if not isinstance(r, Exception)]

    return AvailableModelsResponse(layers=layers, providers=providers, endpoints=endpoint_infos)


@router.post("/test")
async def test_model_layer(body: dict):
    """Send a quick test message to a model layer and return latency + reply."""
    from app.services.llm.provider_factory import get_provider
    from app.services.llm.providers.base import CompletionRequest

    provider_type = body.get("provider_type", "").strip()
    provider_url = body.get("provider_url", "").strip()
    api_key = body.get("api_key", "").strip()
    model = body.get("model", "").strip()

    if not model:
        return {"success": False, "error": "model is required"}

    # Auto-detect provider type if not given
    if not provider_type:
        provider_type = infer_provider_type(provider_url, model)

    start = time.monotonic()
    try:
        provider = get_provider(provider_type=provider_type, url=provider_url, api_key=api_key)
        req = CompletionRequest(
            messages=[{"role": "user", "content": "Say hi in 3 words."}],
            model=model,
            max_tokens=20,
        )
        reply = await provider.complete(req)
        elapsed_ms = round((time.monotonic() - start) * 1000)
        return {
            "success": True,
            "latency_ms": elapsed_ms,
            "reply": reply[:100],
            "model": model,
            "provider_type": provider_type,
        }
    except Exception as e:
        elapsed_ms = round((time.monotonic() - start) * 1000)
        return {"success": False, "error": str(e), "latency_ms": elapsed_ms}
