"""Ollama provider.

Extends OpenAICompatProvider with:
  - Ollama-native model listing via /api/tags
  - Automatic base_url normalisation (adds /v1 if missing)
  - Reachability probe via /api/tags instead of /models
"""

from __future__ import annotations

import asyncio
import logging

import httpx

from app.services.llm.providers.openai_compat import OpenAICompatProvider

logger = logging.getLogger("voxyflow.providers.ollama")

# Default Ollama address
DEFAULT_OLLAMA_URL = "http://localhost:11434"


class OllamaProvider(OpenAICompatProvider):
    """Provider for a local (or remote) Ollama instance."""

    provider_label = "Ollama"
    provider_type = "ollama"

    def __init__(self, base_url: str = DEFAULT_OLLAMA_URL, api_key: str = ""):
        # Normalise URL — Ollama's OpenAI-compat endpoint lives at /v1
        base_url = base_url.rstrip("/")
        if not base_url.endswith("/v1"):
            openai_url = f"{base_url}/v1"
        else:
            openai_url = base_url
            base_url = base_url[:-3]  # strip /v1 for native API calls

        self._native_url = base_url  # e.g. http://localhost:11434
        super().__init__(provider_url=openai_url, api_key=api_key or "ollama")

    # ------------------------------------------------------------------
    # Override model listing — use Ollama's native /api/tags endpoint
    # which returns richer metadata than /v1/models
    # ------------------------------------------------------------------

    async def list_models(self) -> list[str]:
        """Return model names from Ollama's /api/tags."""
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(f"{self._native_url}/api/tags")
                resp.raise_for_status()
                data = resp.json()
                return [m["name"] for m in data.get("models", [])]
        except Exception as exc:
            logger.debug("[Ollama] list_models failed (%s): %s", self._native_url, exc)
            return []

    async def list_models_with_size(self) -> list[dict]:
        """Return models with size info for the UI."""
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(f"{self._native_url}/api/tags")
                resp.raise_for_status()
                data = resp.json()
                result = []
                for m in data.get("models", []):
                    size_bytes = m.get("size", 0)
                    result.append({
                        "name": m["name"],
                        "size_gb": round(size_bytes / 1_073_741_824, 1),
                        "modified_at": m.get("modified_at", ""),
                    })
                return result
        except Exception as exc:
            logger.debug("[Ollama] list_models_with_size failed: %s", exc)
            return []

    async def is_reachable(self) -> bool:
        try:
            async with httpx.AsyncClient(timeout=3.0) as client:
                resp = await client.get(f"{self._native_url}/api/tags")
                return resp.status_code == 200
        except Exception:
            return False
