"""LLM Provider abstraction layer.

Providers implement a common interface so the rest of Voxyflow can switch
between Claude (CLI or native SDK), OpenAI, Ollama, Groq, Mistral, Gemini,
or any OpenAI-compatible endpoint without touching orchestration code.

Usage:
    from app.services.llm.providers import get_provider, ProviderCapabilities

    provider = get_provider("ollama", url="http://localhost:11434/v1", api_key="")
    caps = provider.get_capabilities("llama3.2")
    result = await provider.complete(messages, system=..., model="llama3.2")
"""

from app.services.llm.providers.base import LLMProvider, ProviderCapabilities, CompletionRequest, CompletionResponse

__all__ = ["LLMProvider", "ProviderCapabilities", "CompletionRequest", "CompletionResponse"]
