"""Worker execution mixin for ClaudeService — delegated background tasks.

Extracted verbatim from app.services.claude_service.

WorkerExecutionMixin expects the composing class to provide (created in
ClaudeService.__init__): the fast/deep/haiku layer attributes
(``*_model``/``*_client``/``*_client_type``), ``self.personality``, and
``self._call_api`` from ApiCallerMixin.

The worker-lifecycle prompt text (Phase 1/2/3 contract) lives here as named
constants so other copies of the contract (e.g. worker_pool's
execution_prompt) can converge on them later.
"""

import asyncio
import logging
from typing import Callable, Optional

from app.config import get_settings, workspace_workdir
from app.services.llm.client_factory import _make_async_anthropic_client
from app.services.llm.model_utils import (
    _strip_think_tags,
    _is_thinking_model,
    _inject_no_think,
)
from app.services.llm.prompt_cache import _make_cached_system

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Worker lifecycle prompt text (Phase 1/2/3 contract) — named constants.
# Moved VERBATIM from execute_worker_task; do not reword without checking the
# other copies of this contract (worker_pool execution_prompt).
# ---------------------------------------------------------------------------

WORKER_LIFECYCLE_PROMPT = (
    "## Worker Lifecycle (MANDATORY)\n"
    "You operate under a strict 3-phase protocol. The orchestrator enforces it.\n\n"
    "**Phase 1 — Claim.** As your FIRST action, call voxyflow.worker.claim with "
    "your task_id and a one-sentence plan describing what you intend to do. "
    "Do NOT run any other tool before claim.\n\n"
    "**Phase 2 — Work.** Use any tools needed to complete the task. "
    "Save full raw output (file contents, stdout/stderr, data) — it will be persisted "
    "to an artifact that the dispatcher can read on demand.\n\n"
    "**Phase 3 — Complete.** As your LAST action, call voxyflow.worker.complete "
    "with: task_id, status (success/partial/failed), summary (2–4 sentences of what you "
    "did and why it matters — NOT the raw output), findings (3–7 short bullets of the "
    "key results), pointers (labelled offsets into the artifact for important detail), "
    "and next_step (optional). Stop immediately after.\n\n"
    "The summary is the ONLY thing the dispatcher sees directly — write it for a reader "
    "who has NOT seen the raw output. Do not truncate the artifact itself; the "
    "dispatcher will fetch specific sections via read_artifact using your pointers."
)

CODEX_WORKER_LIFECYCLE_PROMPT = (
    "## Codex Voxyflow lifecycle\n"
    "You have Voxyflow MCP tools through Codex. Use the real tools when they are available: "
    "first call voxyflow.worker.claim, then do the work, and as your last action call "
    "voxyflow.worker.complete. Do not merely print lifecycle JSON when the MCP tools are available.\n\n"
    "Only if the lifecycle MCP tools are unavailable, include fallback fenced JSON blocks "
    "named voxyflow_worker_claim and voxyflow_worker_complete in your final answer with the "
    "same fields. The complete block must include task_id, status, summary, findings, "
    "pointers, and next_step."
)

CODEX_LIGHTWEIGHT_LIFECYCLE_PROMPT = (
    "\n\nCodex lifecycle: use the real Voxyflow MCP lifecycle tools when available: "
    "first voxyflow.worker.claim, last voxyflow.worker.complete. Only if those tools "
    "are unavailable, include fallback fenced JSON blocks named voxyflow_worker_claim "
    "and voxyflow_worker_complete in your final answer. The complete block must include "
    "task_id, status, summary, findings, pointers, and next_step."
)


class WorkerExecutionMixin:
    """Delegated worker task execution + endpoint-based client resolution."""

    # ------------------------------------------------------------------
    # Endpoint-based client helper (for WorkerClass with endpoint_id)
    # ------------------------------------------------------------------

    def _resolve_worker_client(
        self,
        endpoint_config: Optional[dict],
        model: str,
    ) -> tuple:
        """Pick (client, client_type, model_name) for a worker call.

        Precedence:
          1. endpoint_config with provider_type="cli" → CLI backend, worker class's model
          2. endpoint_config with url → custom endpoint (Ollama/OpenAI/etc.)
          3. model alias matching (haiku/opus/anything-else → fast) — legacy fallback

        Why this matters: when the user's Fast layer is set to a non-Claude provider,
        the layer aliases follow that provider. A worker class configured with
        provider_type="cli" must NOT be silently rerouted to the Fast layer's provider.
        """
        if endpoint_config:
            ptype = (endpoint_config.get("provider_type") or "").strip().lower()
            wc_model = (endpoint_config.get("model") or "").strip() or model
            if ptype == "cli":
                return (None, "cli", wc_model)
            if ptype == "codex":
                return (None, "codex", wc_model)
            if endpoint_config.get("url"):
                return self._make_endpoint_client(endpoint_config, model)
            # provider_type set but no url and not cli — fall through to alias.

        model_lower = (model or "").lower()
        if "haiku" in model_lower:
            return (self.haiku_client, self.haiku_client_type, self.haiku_model)
        if "opus" in model_lower:
            return (self.deep_client, self.deep_client_type, self.deep_model)
        return (self.fast_client, self.fast_client_type, self.fast_model)

    def _make_endpoint_client(
        self,
        endpoint_config: dict,
        model_hint: str,
    ) -> tuple:
        """Create a (client, client_type, model_name) tuple from a resolved endpoint config.

        ``endpoint_config`` comes from ``resolve_endpoint_for_class()`` and contains:
          - provider_type (e.g. "ollama", "openai", "groq", ...)
          - url           (e.g. "http://10.0.0.4:11434")
          - api_key       (may be empty for local providers)
          - model         (model id from the worker class, e.g. "gemma3:27b")

        For Anthropic endpoints, creates an AsyncAnthropic client.
        For all other providers, creates an AsyncOpenAI client pointed at the endpoint URL.
        CLI provider type is never reached here (CLI has no endpoint_id).
        """
        from openai import OpenAI

        provider_type = endpoint_config.get("provider_type", "openai")
        url = endpoint_config.get("url", "")
        api_key = endpoint_config.get("api_key", "")
        model_name = endpoint_config.get("model", "") or model_hint

        # Ollama needs /v1 appended for OpenAI-compat
        base_url = url.rstrip("/")
        if provider_type == "ollama" and not base_url.endswith("/v1"):
            base_url = f"{base_url}/v1"

        if provider_type == "anthropic":
            client = _make_async_anthropic_client(api_key or "not-needed", base_url)
            client_type = "anthropic"
        else:
            # Use sync OpenAI client — _call_api_openai and _call_api_server_tools
            # wrap calls in asyncio.to_thread and expect a synchronous client.
            client = OpenAI(
                base_url=base_url,
                api_key=api_key or "local",
            )
            client_type = "openai"

        logger.info(
            "[ClaudeService] Created endpoint client: provider=%s url=%s model=%s client_type=%s",
            provider_type, base_url, model_name, client_type,
        )
        return client, client_type, model_name

    async def execute_worker_task(
        self,
        chat_id: str,
        prompt: str,
        model: str = "sonnet",
        chat_level: str = "general",
        project_context: Optional[dict] = None,
        card_context: Optional[dict] = None,
        workspace_id: Optional[str] = None,
        tool_callback: Optional[Callable[[str, dict, dict], None]] = None,
        cancel_event: Optional[asyncio.Event] = None,
        message_queue: Optional[asyncio.Queue] = None,
        session_id: str = "",
        task_id: str = "",
        endpoint_config: Optional[dict] = None,
        effort: str = "",
    ) -> str:
        """Execute a delegated task with the specified worker model (haiku/sonnet/opus).

        If endpoint_config is provided (from a WorkerClass with endpoint_id),
        a provider-specific client is created for that endpoint instead of using
        the default haiku/sonnet/opus clients.
        Model can be a short name ('opus') or full ID ('claude-opus-4-6').

        ``effort`` is the canonical worker reasoning-effort level resolved by the
        pool (worker-class effort → default_worker_effort). Forwarded to the CLI
        subprocess paths; "" = model default.
        """
        card_id = card_context.get("id", "") if card_context else ""

        # If a resolved endpoint config is provided, use its provider directly.
        # CLI worker classes have provider_type="cli" with no url — route to the CLI
        # backend with the worker class's model rather than falling through to the
        # Fast/Haiku layer aliases (which may now point at a different provider).
        client, client_type, model_name = self._resolve_worker_client(endpoint_config, model)
        role = "worker"  # Workers get full MCP tool access

        # Workers always use the native Anthropic async SDK (tool_use blocks) to avoid
        # XML <tool_call> truncation issues with the OpenAI-compat proxy path.
        # Using AsyncAnthropic avoids "Streaming required for long requests" errors.
        # The client is pointed at CLIProxyAPI which supports /v1/messages.
        # CLI path: no upgrade needed — Claude CLI handles tools via MCP.
        # Endpoint config path: skip upgrade — the client is intentionally pointed
        # at a non-Anthropic provider (Ollama, Groq, etc.).
        if client_type == "openai" and not endpoint_config:
            _cfg = get_settings()
            worker_api_url = _cfg.claude_proxy_url  # e.g. http://localhost:3457/v1
            worker_api_key = _cfg.claude_api_key or "not-needed"
            # CLIProxyAPI /v1/messages expects base_url without /v1 suffix
            anthropic_base = worker_api_url.rstrip("/")
            if anthropic_base.endswith("/v1"):
                anthropic_base = anthropic_base[:-3]
            client = _make_async_anthropic_client(worker_api_key, anthropic_base)
            client_type = "anthropic"  # Same path as sync anthropic; async detected via isinstance
            logger.info(f"[execute_worker_task] Upgraded worker client to AsyncAnthropic → {anthropic_base}")

        # Build worker-specific prompt
        base_prompt = self.personality.build_worker_prompt(
            model=model,
            chat_level=chat_level,
            workspace=project_context,
            card=card_context,
        )

        dynamic_parts: list[str] = []

        # Resolve the worker's working directory up-front so we can both pass it
        # to the subprocess AND suggest it to the worker (in the prompt). Code-
        # project workspaces work in their checked-out repo; everything else gets
        # a stable per-workspace area under the sandbox. This is a suggestion for
        # organization, not a jail — the prompt steers, it doesn't forbid.
        if project_context and project_context.get("local_path"):
            worker_cwd = project_context["local_path"]
        else:
            worker_cwd = str(workspace_workdir(workspace_id))

        dynamic_parts.append(
            "## Your working directory\n"
            f"Your default working directory is `{worker_cwd}` — a stable, per-workspace "
            "area. Prefer it for output files (relative paths, or absolute paths under "
            "it) so your work stays organized and the user can find it later. "
            "Avoid `/tmp`: it's ephemeral (wiped on reboot) and a poor place to leave "
            "deliverables. If a task genuinely needs another location (e.g. a repo "
            "you're editing), that's fine — use it deliberately. Either way, when you "
            "tell the user where a file is, state the real path you actually wrote to, "
            "never a guessed one."
        )

        # Mandatory worker lifecycle — strict 3-phase contract.
        dynamic_parts.append(WORKER_LIFECYCLE_PROMPT)

        if client_type == "codex":
            dynamic_parts.append(CODEX_WORKER_LIFECYCLE_PROMPT)

        # Skills catalog — learned procedures (global + this workspace). Catalog
        # only (progressive disclosure); the worker loads full instructions on
        # demand via voxyflow.skill.get.
        try:
            from app.services.skill_service import get_skill_service
            skills_catalog = get_skill_service().build_skills_catalog(workspace_id)
            if skills_catalog:
                dynamic_parts.append(skills_catalog)
        except Exception as e:
            logger.warning(f"Skills catalog injection failed (execute_worker_task): {e}")

        if workspace_id:
            try:
                pass  # RAG disabled — use knowledge.search tool instead
            except Exception as e:
                logger.warning(f"RAG context injection failed (execute_worker_task): {e}")

        system_prompt = _make_cached_system(
            base_prompt, dynamic_parts, is_anthropic=(client_type in ("anthropic", "cli", "codex"))
        )
        system_prompt = _inject_no_think(system_prompt, model_name)

        result = await self._call_api(
            model=model_name,
            system=system_prompt,
            messages=[{"role": "user", "content": prompt}],
            client=client,
            client_type=client_type,
            use_tools=True,
            tool_callback=tool_callback,
            layer=role,
            chat_level=chat_level,
            chat_id=chat_id,
            cancel_event=cancel_event,
            message_queue=message_queue,
            session_id=session_id, workspace_id=workspace_id or "", card_id=card_id,
            session_type="worker",
            task_id=task_id,
            cwd=worker_cwd,
            effort=effort,
        )
        return (_strip_think_tags(result) if _is_thinking_model(model_name) else result) if result else result

    async def execute_lightweight_task(
        self,
        chat_id: str,
        prompt: str,
        model: str = "haiku",
        workspace_id: Optional[str] = None,
        card_context: Optional[dict] = None,
        tool_callback: Optional[Callable[[str, dict, dict], None]] = None,
        cancel_event: Optional[asyncio.Event] = None,
        message_queue: Optional[asyncio.Queue] = None,
        session_id: str = "",
        task_id: str = "",
        endpoint_config: Optional[dict] = None,
        effort: str = "",
    ) -> str:
        """Lightweight worker — minimal prompt, no personality, no workspace context.

        For tasks that need LLM judgment but not full context (enrich, summarize,
        research). Saves ~80% tokens vs execute_worker_task. ``effort`` is the
        canonical worker reasoning-effort level (forwarded to the CLI paths).
        """
        card_id = card_context.get("id", "") if card_context else ""

        client, client_type, model_name = self._resolve_worker_client(endpoint_config, model or "")

        system_prompt = (
            "You are a lightweight task worker operating under a strict lifecycle.\n\n"
            "1. FIRST: call voxyflow.worker.claim(task_id, plan) with a one-sentence plan.\n"
            "2. Then: use MCP tools to execute the task. Use web search tools directly "
            "(e.g. voxyflow.web.search) when asked to search the web. Do NOT create "
            "scheduled jobs or delegate to other systems (no voxyflow.jobs.create).\n"
            "3. LAST: call voxyflow.worker.complete(task_id, status, summary, findings, pointers, next_step?) "
            "with a real 2–4 sentence summary in your own words, not the raw output. "
            "Stop immediately after. The artifact is persisted automatically — don't inline it.\n\n"
            f"Default working directory: `{workspace_workdir(workspace_id)}` — a stable per-workspace "
            "area. Prefer it for output files; avoid `/tmp` (ephemeral, wiped on reboot). Use another "
            "location only if the task needs it, and always report the real path you wrote to, never a guess."
        )

        if client_type == "codex":
            system_prompt += CODEX_LIGHTWEIGHT_LIFECYCLE_PROMPT

        if client_type in ("anthropic", "cli", "codex"):
            system_prompt_final: str | list[dict] = [{"type": "text", "text": system_prompt}]
        else:
            system_prompt_final = system_prompt

        logger.info(f"[LightWorker] Executing lightweight task: model={model_name} prompt_len={len(prompt)}")

        result = await self._call_api(
            model=model_name,
            system=system_prompt_final,
            messages=[{"role": "user", "content": prompt}],
            client=client,
            client_type=client_type,
            use_tools=True,
            tool_callback=tool_callback,
            layer="worker",
            chat_id=chat_id,
            cancel_event=cancel_event,
            message_queue=message_queue,
            session_id=session_id, workspace_id=workspace_id or "", card_id=card_id,
            session_type="worker",
            task_id=task_id,
            cwd=str(workspace_workdir(workspace_id)),
            effort=effort,
        )
        return result or ""
