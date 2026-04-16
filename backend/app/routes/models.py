"""Model discovery and provider detection endpoints."""

import asyncio
import json
import logging
import time

import httpx
from fastapi import APIRouter, Query
from pydantic import BaseModel

from app.config import get_settings
from app.services.llm.provider_factory import infer_provider_type, list_known_providers

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/models", tags=["models"])

# ---------------------------------------------------------------------------
# Default worker classes — returned when nothing is saved in DB yet.
# Must stay in sync with frontend defaults in Settings → Models.
# ---------------------------------------------------------------------------

DEFAULT_WORKER_CLASSES = [
    {
        "id": "00000000-0000-0000-0000-000000000001",
        "name": "Quick",
        "description": "Fast, lightweight tasks — summaries, simple Q&A, formatting",
        "endpoint_id": "",
        "provider_type": "cli",
        "model": "claude-haiku-4-5-20251001",
        "intent_patterns": ["summarize", "format", "quick", "simple", "short"],
    },
    {
        "id": "00000000-0000-0000-0000-000000000002",
        "name": "Coding",
        "description": "Code writing, debugging, refactoring, code review",
        "endpoint_id": "",
        "provider_type": "cli",
        "model": "claude-opus-4-7",
        "intent_patterns": ["code", "debug", "refactor", "implement", "fix", "test"],
    },
    {
        "id": "00000000-0000-0000-0000-000000000003",
        "name": "Research",
        "description": "Deep research, analysis, multi-step investigation",
        "endpoint_id": "",
        "provider_type": "cli",
        "model": "claude-opus-4-7",
        "intent_patterns": ["research", "analyze", "investigate", "compare", "explain"],
    },
    {
        "id": "00000000-0000-0000-0000-000000000004",
        "name": "Creative",
        "description": "Writing, brainstorming, ideation, narrative",
        "endpoint_id": "",
        "provider_type": "cli",
        "model": "claude-sonnet-4-6",
        "intent_patterns": ["write", "brainstorm", "creative", "story", "draft"],
    },
]


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

async def _load_models_cfg() -> dict:
    """Load the models section from settings (DB-backed)."""
    from app.routes.settings import _load_settings_from_db
    data = await _load_settings_from_db()
    if data:
        return data.get("models", {})
    return {}


# ---------------------------------------------------------------------------
# Reachability cache (Fix #14)
# ---------------------------------------------------------------------------

_reachability_cache: dict = {}   # {"providers": {...}, "ts": float}
_REACHABILITY_TTL = 30.0


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("/worker-classes")
async def list_worker_classes():
    """Return saved worker classes."""
    models_cfg = await _load_models_cfg()
    classes = models_cfg.get("worker_classes", [])
    return classes if classes else DEFAULT_WORKER_CLASSES


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
    endpoint_id: str = Query(default="", description="Named endpoint id — resolves url/api_key/type from saved endpoints"),
):
    """List available models for a given provider or named endpoint.

    Returns a list of model name strings. Empty list if unreachable or unsupported.
    Pass either (provider_type, url) OR endpoint_id.
    API keys are resolved server-side from saved endpoints — never sent in query strings.
    """
    from app.services.llm.provider_factory import get_provider

    api_key = ""

    # Resolve named endpoint — key is resolved server-side, never from query params
    if endpoint_id:
        models_cfg = await _load_models_cfg()
        for ep in models_cfg.get("endpoints", []):
            if ep.get("id") == endpoint_id:
                provider_type = ep.get("provider_type", provider_type)
                url = ep.get("url", url)
                api_key = ep.get("api_key", "")
                break

    if not provider_type:
        return []

    if provider_type == "cli":
        return ["claude-haiku-4-5-20251001", "claude-sonnet-4-6", "claude-opus-4-6", "claude-opus-4-7"]

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
    models_cfg = await _load_models_cfg()

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

    # Check reachability cache for built-in providers
    now = time.monotonic()
    cached_ts = _reachability_cache.get("ts", 0.0)
    cached_providers = _reachability_cache.get("providers", {})
    if (now - cached_ts) < _REACHABILITY_TTL and cached_providers:
        # Use cached provider reachability
        for pt, (lbl, u) in urls_to_probe.items():
            if pt in cached_providers:
                providers[pt] = cached_providers[pt]
            else:
                # New provider not in cache — probe it
                try:
                    _, info = await _probe_provider(pt, lbl, u)
                    providers[pt] = info
                except Exception:
                    pass
    else:
        # Cache miss — probe all providers
        provider_tasks = [_probe_provider(pt, lbl, u) for pt, (lbl, u) in urls_to_probe.items()]
        provider_results = await asyncio.gather(*provider_tasks, return_exceptions=True)
        for result in provider_results:
            if isinstance(result, Exception):
                continue
            ptype, info = result
            providers[ptype] = info
        # Update cache
        _reachability_cache["providers"] = dict(providers)
        _reachability_cache["ts"] = now

    # --- Probe named user endpoints (always fresh) ---
    saved_endpoints: list[dict] = models_cfg.get("endpoints", [])
    endpoint_tasks = [_probe_endpoint(ep) for ep in saved_endpoints if ep.get("url")]
    endpoint_results = await asyncio.gather(*endpoint_tasks, return_exceptions=True)

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
        result = await provider.complete(req)
        elapsed_ms = round((time.monotonic() - start) * 1000)
        return {
            "success": True,
            "latency_ms": elapsed_ms,
            "reply": result.content[:100],
            "model": model,
            "provider_type": provider_type,
        }
    except Exception as e:
        elapsed_ms = round((time.monotonic() - start) * 1000)
        return {"success": False, "error": str(e), "latency_ms": elapsed_ms}


# ---------------------------------------------------------------------------
# Benchmark: Worker Class LLM comparison with LLM-as-judge evaluation
# ---------------------------------------------------------------------------

class BenchmarkRequest(BaseModel):
    worker_class_id: str = ""
    worker_class_name: str = ""
    worker_class_description: str = ""
    intent_patterns: list[str] = []
    model_a: dict  # { provider_type, provider_url, model, endpoint_id? }
    model_b: dict  # { provider_type, provider_url, model, endpoint_id? }
    custom_prompt: str = ""  # if empty, auto-generate from worker class


def _generate_test_prompt(name: str, description: str, intent_patterns: list[str]) -> str:
    """Generate a test prompt based on worker class metadata."""
    name_lower = name.lower()
    if "cod" in name_lower or "code" in name_lower or "debug" in name_lower:
        return "Write a Python function that parses a markdown table into a list of dicts. Handle missing values gracefully. Include type hints and a brief docstring."
    elif "research" in name_lower or "analyz" in name_lower or "investigat" in name_lower:
        return "Compare the trade-offs between PostgreSQL and MongoDB for a real-time collaborative document editing application. Structure your answer with pros/cons and a recommendation."
    elif "creat" in name_lower or "writ" in name_lower or "story" in name_lower:
        return "Write the opening scene of a short story where a software engineer discovers their AI assistant has been secretly learning to paint. Make it vivid and surprising."
    elif "quick" in name_lower or "fast" in name_lower or "summar" in name_lower:
        return "Summarize this in exactly 3 bullet points, each under 15 words: 'Large language models have revolutionized NLP by enabling few-shot learning, but they require significant compute resources and careful prompt engineering to perform reliably across diverse tasks.'"
    else:
        task_hint = description or (", ".join(intent_patterns[:3]) if intent_patterns else name)
        return f"You are a {name} assistant. Demonstrate your capabilities by completing this task: {task_hint}. Provide a clear, well-structured response."


def _build_judge_prompt(worker_class_name: str, task_prompt: str, reply_a: str, reply_b: str) -> str:
    """Build the LLM-as-judge evaluation prompt."""
    return f"""You are an expert evaluator comparing two AI responses for a "{worker_class_name}" task.

TASK GIVEN TO BOTH MODELS:
{task_prompt}

MODEL A RESPONSE:
{reply_a[:2000]}

MODEL B RESPONSE:
{reply_b[:2000]}

Evaluate both responses on these criteria (score each 1-10):
1. Relevance — Does it directly address the task?
2. Quality — Is it accurate, well-structured, complete?
3. Clarity — Is it easy to understand?
4. Conciseness — Does it avoid unnecessary verbosity?

Respond in this exact JSON format (no markdown, no explanation outside the JSON):
{{
  "score_a": <total 1-40>,
  "score_b": <total 1-40>,
  "criteria": [
    {{"name": "Relevance", "score_a": <1-10>, "score_b": <1-10>}},
    {{"name": "Quality", "score_a": <1-10>, "score_b": <1-10>}},
    {{"name": "Clarity", "score_a": <1-10>, "score_b": <1-10>}},
    {{"name": "Conciseness", "score_a": <1-10>, "score_b": <1-10>}}
  ],
  "winner": "<a|b|tie>",
  "summary": "<2-3 sentences explaining the key differences>",
  "recommendation": "<one sentence: which model to use for this worker class and why>"
}}"""


async def _run_model(slot: dict, prompt: str, models_cfg: dict) -> dict:
    """Run a single model slot and return result dict."""
    from app.services.llm.provider_factory import get_provider
    from app.services.llm.providers.base import CompletionRequest

    provider_type = slot.get("provider_type", "").strip()
    provider_url = slot.get("provider_url", "").strip()
    model = slot.get("model", "").strip()
    endpoint_id = slot.get("endpoint_id", "").strip()
    api_key = ""

    # Resolve endpoint
    if endpoint_id:
        for ep in models_cfg.get("endpoints", []):
            if ep.get("id") == endpoint_id:
                provider_type = ep.get("provider_type", provider_type)
                provider_url = ep.get("url", provider_url)
                api_key = ep.get("api_key", "")
                break

    if not provider_type:
        provider_type = infer_provider_type(provider_url, model)

    if not model:
        return {"success": False, "error": "model is required", "reply": "", "latency_ms": 0, "model": "", "provider_type": provider_type}

    start = time.monotonic()
    try:
        # CLI is managed by ClaudeCliBackend, not LLMProvider
        if provider_type == "cli":
            from app.services.llm.cli_backend import ClaudeCliBackend
            cli = ClaudeCliBackend()
            reply, _usage = await cli.call(
                model=model,
                system="You are a helpful assistant.",
                messages=[{"role": "user", "content": prompt}],
            )
            elapsed_ms = round((time.monotonic() - start) * 1000)
            return {"success": True, "reply": reply, "latency_ms": elapsed_ms, "model": model, "provider_type": provider_type}

        provider = get_provider(provider_type=provider_type, url=provider_url, api_key=api_key)
        req = CompletionRequest(
            messages=[{"role": "user", "content": prompt}],
            model=model,
            max_tokens=1024,
        )
        result = await provider.complete(req)
        elapsed_ms = round((time.monotonic() - start) * 1000)
        return {
            "success": True,
            "reply": result.content,
            "latency_ms": elapsed_ms,
            "model": model,
            "provider_type": provider_type,
        }
    except Exception as e:
        elapsed_ms = round((time.monotonic() - start) * 1000)
        return {
            "success": False,
            "error": str(e),
            "reply": "",
            "latency_ms": elapsed_ms,
            "model": model,
            "provider_type": provider_type,
        }


@router.post("/benchmark")
async def benchmark_models(body: BenchmarkRequest):
    """Run a Worker Class benchmark: test two models on the same prompt, then evaluate with LLM-as-judge."""
    models_cfg = await _load_models_cfg()

    # Step 1: Generate or use custom prompt
    prompt_used = body.custom_prompt.strip()
    if not prompt_used:
        prompt_used = _generate_test_prompt(
            body.worker_class_name,
            body.worker_class_description,
            body.intent_patterns,
        )

    # Step 2: Run both models in parallel
    result_a, result_b = await asyncio.gather(
        _run_model(body.model_a, prompt_used, models_cfg),
        _run_model(body.model_b, prompt_used, models_cfg),
    )

    # Step 3: LLM-as-judge evaluation
    evaluation = await _run_judge_evaluation(
        body.worker_class_name or "General",
        prompt_used,
        result_a,
        result_b,
        models_cfg,
    )

    return {
        "prompt_used": prompt_used,
        "result_a": result_a,
        "result_b": result_b,
        "evaluation": evaluation,
    }


async def _run_judge_evaluation(
    worker_class_name: str,
    task_prompt: str,
    result_a: dict,
    result_b: dict,
    models_cfg: dict,
) -> dict:
    """Call the fast layer as LLM-as-judge to evaluate both results."""
    reply_a = result_a.get("reply", "") if result_a.get("success") else f"[MODEL FAILED: {result_a.get('error', 'unknown error')}]"
    reply_b = result_b.get("reply", "") if result_b.get("success") else f"[MODEL FAILED: {result_b.get('error', 'unknown error')}]"

    judge_prompt = _build_judge_prompt(worker_class_name, task_prompt, reply_a, reply_b)

    # Use the fast layer provider to evaluate
    try:
        from app.services.llm.provider_factory import get_provider
        from app.services.llm.providers.base import CompletionRequest

        fast_cfg = models_cfg.get("fast", {})
        fast_provider_type = fast_cfg.get("provider_type", "cli")
        fast_provider_url = fast_cfg.get("provider_url", "")
        fast_model = fast_cfg.get("model", "claude-sonnet-4")
        fast_api_key = ""

        # Resolve endpoint if fast layer uses one
        fast_endpoint_id = fast_cfg.get("endpoint_id", "")
        if fast_endpoint_id:
            for ep in models_cfg.get("endpoints", []):
                if ep.get("id") == fast_endpoint_id:
                    fast_provider_type = ep.get("provider_type", fast_provider_type)
                    fast_provider_url = ep.get("url", fast_provider_url)
                    fast_api_key = ep.get("api_key", "")
                    break

        if fast_provider_type == "cli":
            from app.services.llm.cli_backend import ClaudeCliBackend
            cli = ClaudeCliBackend()
            judge_text, _usage = await cli.call(
                model=fast_model,
                system="You are a precise AI evaluator. Always respond with valid JSON only.",
                messages=[{"role": "user", "content": judge_prompt}],
            )
            judge_text = judge_text.strip()
        else:
            provider = get_provider(
                provider_type=fast_provider_type,
                url=fast_provider_url,
                api_key=fast_api_key,
            )
            req = CompletionRequest(
                messages=[{"role": "user", "content": judge_prompt}],
                model=fast_model,
                max_tokens=1024,
                system="You are a precise AI evaluator. Always respond with valid JSON only.",
            )
            judge_result = await provider.complete(req)
            judge_text = judge_result.content.strip()

        # Try to extract JSON from the response (handle markdown code blocks)
        if "```" in judge_text:
            # Extract from code block
            import re
            match = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", judge_text, re.DOTALL)
            if match:
                judge_text = match.group(1).strip()

        evaluation = json.loads(judge_text)
        return evaluation

    except Exception as e:
        logger.warning("[benchmark] Judge evaluation failed: %s", e)
        # Fallback: latency-only evaluation
        lat_a = result_a.get("latency_ms", 99999)
        lat_b = result_b.get("latency_ms", 99999)
        ok_a = result_a.get("success", False)
        ok_b = result_b.get("success", False)

        if ok_a and not ok_b:
            winner = "a"
        elif ok_b and not ok_a:
            winner = "b"
        elif lat_a < lat_b:
            winner = "a"
        elif lat_b < lat_a:
            winner = "b"
        else:
            winner = "tie"

        return {
            "winner": winner,
            "score_a": 20 if ok_a else 0,
            "score_b": 20 if ok_b else 0,
            "criteria": [
                {"name": "Relevance", "score_a": 5, "score_b": 5},
                {"name": "Quality", "score_a": 5, "score_b": 5},
                {"name": "Clarity", "score_a": 5, "score_b": 5},
                {"name": "Conciseness", "score_a": 5, "score_b": 5},
            ],
            "summary": f"LLM judge unavailable — fallback to latency comparison. A: {lat_a}ms, B: {lat_b}ms.",
            "recommendation": f"Evaluation based on latency only (judge error: {e}).",
        }
