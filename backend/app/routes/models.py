"""Model discovery and provider detection endpoints."""

import logging
from fastapi import APIRouter, Query
from pydantic import BaseModel

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/models", tags=["models"])


class OllamaModel(BaseModel):
    name: str
    size_gb: float


class ProviderInfo(BaseModel):
    type: str  # "claude", "ollama", "openai_compatible"
    reachable: bool
    url: str


class LayerInfo(BaseModel):
    model: str
    provider_type: str
    provider_url: str
    enabled: bool


class AvailableModelsResponse(BaseModel):
    layers: dict[str, LayerInfo]
    providers: dict[str, ProviderInfo]


def detect_provider_type(provider_url: str, model: str) -> str:
    """Infer provider type from URL and model name."""
    url = (provider_url or "").lower()
    mdl = (model or "").lower()
    if "11434" in url or (mdl and "claude" not in mdl and ("ollama" in url or "11434" in url)):
        return "ollama"
    if "3457" in url or "claude" in mdl or "anthropic" in url:
        return "claude"
    return "openai_compatible"


@router.get("/ollama", response_model=list[OllamaModel])
async def list_ollama_models(url: str = Query(default="http://192.168.1.59:11434")):
    """Fetch available models from an Ollama instance. Returns empty list if unreachable."""
    import httpx

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


@router.get("/available", response_model=AvailableModelsResponse)
async def get_available_models():
    """Return current model config per layer + detected provider availability."""
    import httpx
    import json
    import os
    from pathlib import Path

    voxyflow_dir = Path(os.environ.get("VOXYFLOW_DIR", os.path.expanduser("~/voxyflow")))
    settings_path = voxyflow_dir / "settings.json"

    models_cfg: dict = {}
    ollama_url = "http://192.168.1.59:11434"
    if settings_path.exists():
        try:
            with open(settings_path) as f:
                stored = json.load(f)
            models_cfg = stored.get("models", {})
            # Try to detect ollama URL from any layer
            for layer_cfg in models_cfg.values():
                u = layer_cfg.get("provider_url", "")
                if "11434" in u:
                    # Strip /v1 suffix for base URL
                    ollama_url = u.replace("/v1", "").rstrip("/")
                    break
        except Exception as e:
            logger.warning("Failed to read settings.json for ollama URL detection: %s", e)

    # Build layers info
    layers: dict[str, LayerInfo] = {}
    for layer_name in ("fast", "deep", "analyzer"):
        cfg = models_cfg.get(layer_name, {})
        purl = cfg.get("provider_url", "")
        mdl = cfg.get("model", "")
        layers[layer_name] = LayerInfo(
            model=mdl,
            provider_type=detect_provider_type(purl, mdl),
            provider_url=purl,
            enabled=cfg.get("enabled", True),
        )

    # Detect provider availability
    providers: dict[str, ProviderInfo] = {}

    # Check Claude proxy
    claude_reachable = False
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            resp = await client.get("http://localhost:3457/v1/models")
            claude_reachable = resp.status_code == 200
    except Exception as e:
        logger.debug("Claude proxy not reachable: %s", e)
    providers["claude"] = ProviderInfo(type="claude", reachable=claude_reachable, url="http://localhost:3457/v1")

    # Check Ollama
    ollama_reachable = False
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            resp = await client.get(ollama_url + "/api/tags")
            ollama_reachable = resp.status_code == 200
    except Exception as e:
        logger.debug("Ollama not reachable: %s", e)
    providers["ollama"] = ProviderInfo(type="ollama", reachable=ollama_reachable, url=ollama_url)

    return AvailableModelsResponse(layers=layers, providers=providers)


@router.post("/test")
async def test_model_layer(body: dict):
    """Send a quick test message to a model layer and return latency."""
    import httpx
    import time

    provider_url = body.get("provider_url", "").strip()
    api_key = body.get("api_key", "").strip()
    model = body.get("model", "").strip()

    if not provider_url or not model:
        return {"success": False, "error": "provider_url and model are required"}

    headers: dict[str, str] = {"Content-Type": "application/json"}
    if api_key and api_key != "ollama":
        headers["Authorization"] = f"Bearer {api_key}"

    payload = {
        "model": model,
        "messages": [{"role": "user", "content": "Say hi in 3 words."}],
        "max_tokens": 20,
        "stream": False,
    }

    start = time.monotonic()
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(
                provider_url.rstrip("/") + "/chat/completions",
                json=payload,
                headers=headers,
            )
            resp.raise_for_status()
            data = resp.json()
        elapsed_ms = round((time.monotonic() - start) * 1000)
        reply = ""
        choices = data.get("choices", [])
        if choices:
            reply = choices[0].get("message", {}).get("content", "")
        return {"success": True, "latency_ms": elapsed_ms, "reply": reply[:100], "model": model}
    except Exception as e:
        elapsed_ms = round((time.monotonic() - start) * 1000)
        return {"success": False, "error": str(e), "latency_ms": elapsed_ms}
