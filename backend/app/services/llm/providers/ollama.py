"""Ollama provider.

Extends OpenAICompatProvider with:
  - Ollama-native model listing via /api/tags
  - Automatic base_url normalisation (adds /v1 if missing)
  - Reachability probe via /api/tags instead of /models
"""

from __future__ import annotations

import asyncio
import logging
import time

import httpx

from app.services.llm.providers.openai_compat import OpenAICompatProvider

logger = logging.getLogger("voxyflow.providers.ollama")

# Default Ollama address
DEFAULT_OLLAMA_URL = "http://localhost:11434"

# Cache TTL for /api/tags responses (seconds)
_TAGS_CACHE_TTL = 10.0


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
        self._tags_cache: dict | None = None
        self._tags_cache_ts: float = 0.0
        super().__init__(provider_url=openai_url, api_key=api_key or "ollama")

    # ------------------------------------------------------------------
    # Shared /api/tags fetch with TTL cache
    # ------------------------------------------------------------------

    async def _fetch_tags(self) -> dict:
        """Fetch /api/tags with a 10-second TTL cache."""
        now = time.monotonic()
        if self._tags_cache is not None and (now - self._tags_cache_ts) < _TAGS_CACHE_TTL:
            return self._tags_cache
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(f"{self._native_url}/api/tags")
                resp.raise_for_status()
                self._tags_cache = resp.json()
                self._tags_cache_ts = now
                return self._tags_cache
        except Exception as exc:
            logger.debug("[Ollama] _fetch_tags failed (%s): %s", self._native_url, exc)
            raise

    # ------------------------------------------------------------------
    # Override model listing — use Ollama's native /api/tags endpoint
    # which returns richer metadata than /v1/models
    # ------------------------------------------------------------------

    async def list_models(self) -> list[str]:
        """Return model names from Ollama's /api/tags."""
        try:
            data = await self._fetch_tags()
            return [m["name"] for m in data.get("models", [])]
        except Exception:
            return []

    async def list_models_with_size(self) -> list[dict]:
        """Return models with size info for the UI."""
        try:
            data = await self._fetch_tags()
            result = []
            for m in data.get("models", []):
                size_bytes = m.get("size", 0)
                result.append({
                    "name": m["name"],
                    "size_gb": round(size_bytes / 1_073_741_824, 1),
                    "modified_at": m.get("modified_at", ""),
                })
            return result
        except Exception:
            return []

    async def is_reachable(self) -> bool:
        try:
            await self._fetch_tags()
            return True
        except Exception:
            return False
