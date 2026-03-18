"""Claude API integration via claude-max-api-proxy (OpenAI-compatible)."""

import asyncio
import json
import logging
from typing import AsyncIterator, Callable, Optional

import httpx
from openai import OpenAI

from app.config import get_settings
from app.services.personality_service import get_personality_service
from app.services.memory_service import get_memory_service
from app.services.agent_personas import AgentType, get_persona_prompt
from app.services.session_store import session_store
from app.services.rag_service import get_rag_service

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# MCP Tool bridge — converts Voxyflow MCP tools to Claude native tool_use
# ---------------------------------------------------------------------------

def get_claude_tools(chat_level: str = "general", project_id: Optional[str] = None) -> list[dict]:
    """Convert Voxyflow MCP tool definitions to Claude API tool_use format.

    Filters tools based on chat_level to prevent the LLM from offering
    actions that are not applicable in the current context:
      - general: only note and project management tools
      - project: all tools except note tools (use cards instead)
      - card:    all tools (full access)

    Returns an empty list (graceful degradation) if the MCP module is
    unavailable or the tool list cannot be loaded.
    """
    try:
        from app.mcp_server import get_tool_list
        all_tools = get_tool_list()

        if chat_level == "general":
            # General chat: only note board + project creation + health check
            allowed = {
                "voxyflow.note.add",
                "voxyflow.note.list",
                "voxyflow.project.create",
                "voxyflow.project.list",
                "voxyflow.health",
            }
        elif chat_level == "project":
            # Project chat: all tools except note board tools
            allowed = {t["name"] for t in all_tools} - {
                "voxyflow.note.add",
                "voxyflow.note.list",
            }
        else:
            # Card chat or fallback: full access
            allowed = {t["name"] for t in all_tools}

        tools = []
        for tool in all_tools:
            if tool["name"] in allowed:
                tools.append({
                    "name": tool["name"].replace(".", "_"),  # Claude forbids dots in tool names
                    "description": tool["description"],
                    "input_schema": tool["inputSchema"],
                })
        return tools
    except Exception as e:
        logger.warning(f"Could not load MCP tools for Claude: {e}")
        return []


def _mcp_tool_name_from_claude(claude_name: str) -> str:
    """Convert a Claude tool name back to its MCP equivalent.

    voxyflow_card_create → voxyflow.card.create
    Only the first underscore-separated segment is the namespace; subsequent
    underscores are replaced with dots starting from index 1, e.g.:
      voxyflow_ai_review_code → voxyflow.ai.review_code  (last part kept as-is)
    """
    # Strategy: split on "_", re-join keeping first segment as-is and joining
    # the remainder with dots.  Since all voxyflow tools have exactly 3 parts
    # (namespace.group.action), split into at most 3 pieces.
    parts = claude_name.split("_", 2)  # ['voxyflow', 'card', 'create']
    return ".".join(parts)


async def _call_mcp_tool(tool_mcp_name: str, arguments: dict) -> dict:
    """Call the Voxyflow REST API via the MCP _call_api helper."""
    try:
        from app.mcp_server import _find_tool, _call_api as mcp_call_api
        tool_def = _find_tool(tool_mcp_name)
        if tool_def is None:
            return {"success": False, "error": f"Unknown MCP tool: {tool_mcp_name}"}
        result = await mcp_call_api(tool_def, arguments or {})
        return result
    except Exception as e:
        logger.error(f"MCP tool call failed: {tool_mcp_name} → {e}")
        return {"success": False, "error": str(e)}


def _load_model_overrides() -> dict:
    """Load model layer overrides from settings.json if it exists. Returns empty dict on failure."""
    import os
    from pathlib import Path

    settings_path = Path(os.environ.get("VOXYFLOW_DIR", os.path.expanduser("~/.openclaw/workspace/voxyflow"))) / "settings.json"
    if not settings_path.exists():
        return {}
    try:
        with open(settings_path) as f:
            data = json.load(f)
        return data.get("models", {})
    except Exception as e:
        logger.warning(f"Failed to load model overrides from settings.json: {e}")
        return {}


def _make_client(provider_url: str, api_key: str) -> OpenAI:
    """Create an OpenAI-compatible client."""
    return OpenAI(
        base_url=provider_url or "http://localhost:3456/v1",
        api_key=api_key if api_key else "not-needed",
    )


class ClaudeService:
    """
    Handles Claude API calls for both conversation layers.

    Uses claude-max-api-proxy (OpenAI-compatible) at localhost:3456 by default.
    Model/provider overrides can be configured via the Settings UI (settings.json).

    All calls are personality-infused via PersonalityService:
    - SOUL.md + USER.md + IDENTITY.md = consistent Ember personality
    - Memory context from MEMORY.md + daily logs = continuity
    - Agent personas = specialized behavior when needed
    """

    def __init__(self):
        config = get_settings()
        self.max_tokens = config.claude_max_tokens

        # Load overrides from settings.json (UI-configured models)
        overrides = _load_model_overrides()

        # --- Fast layer ---
        fast_cfg = overrides.get("fast", {})
        fast_model = fast_cfg.get("model", "").strip()
        if fast_model:
            self.fast_model = fast_model
            self.fast_client = _make_client(
                fast_cfg.get("provider_url", config.claude_proxy_url),
                fast_cfg.get("api_key", ""),
            )
        else:
            self.fast_model = config.claude_sonnet_model
            self.fast_client = OpenAI(base_url=config.claude_proxy_url, api_key=config.claude_api_key)

        # --- Deep layer ---
        deep_cfg = overrides.get("deep", {})
        deep_model = deep_cfg.get("model", "").strip()
        if deep_model:
            self.deep_model = deep_model
            self.deep_client = _make_client(
                deep_cfg.get("provider_url", config.claude_proxy_url),
                deep_cfg.get("api_key", ""),
            )
        else:
            self.deep_model = config.claude_deep_model
            self.deep_client = OpenAI(base_url=config.claude_proxy_url, api_key=config.claude_api_key)

        # --- Analyzer layer ---
        analyzer_cfg = overrides.get("analyzer", {})
        analyzer_model = analyzer_cfg.get("model", "").strip()
        if analyzer_model:
            self.analyzer_model = analyzer_model
            self.analyzer_client = _make_client(
                analyzer_cfg.get("provider_url", config.claude_proxy_url),
                analyzer_cfg.get("api_key", ""),
            )
        else:
            self.analyzer_model = config.claude_analyzer_model
            self.analyzer_client = OpenAI(base_url=config.claude_proxy_url, api_key=config.claude_api_key)

        # Legacy single client kept for backward compat (points to default proxy)
        self.client = OpenAI(base_url=config.claude_proxy_url, api_key=config.claude_api_key)

        self.personality = get_personality_service()
        self.memory = get_memory_service()

        # In-memory cache backed by disk persistence via session_store
        self._histories: dict[str, list[dict]] = {}

    def _get_history(self, chat_id: str) -> list[dict]:
        if chat_id not in self._histories:
            # Load from disk on first access
            self._histories[chat_id] = session_store.get_history_for_claude(chat_id, limit=40)
        return self._histories[chat_id]

    def _append_and_persist(self, chat_id: str, role: str, content: str,
                            model: str | None = None, msg_type: str | None = None,
                            session_id: str | None = None):
        """Append to in-memory history and persist to disk."""
        history = self._get_history(chat_id)
        history.append({"role": role, "content": content})

        # Persist to disk
        msg = {"role": role, "content": content}
        if model:
            msg["model"] = model
        if msg_type:
            msg["type"] = msg_type
        if session_id:
            msg["session_id"] = session_id
        session_store.save_message(chat_id, msg)

    async def chat_fast(
        self,
        chat_id: str,
        user_message: str,
        project_name: Optional[str] = None,
        project_id: Optional[str] = None,
        chat_level: str = "general",
        project_context: Optional[dict] = None,
        card_context: Optional[dict] = None,
    ) -> str:
        """Layer 1: Fast conversational response, personality-infused."""
        self._append_and_persist(chat_id, "user", user_message, model="fast")
        history = self._get_history(chat_id)

        settings = get_settings()
        recent = history[-settings.fast_context_messages:]

        # Build memory context (lightweight for fast layer — speed matters)
        memory_context = self.memory.build_memory_context(
            project_name=project_name,
            include_long_term=False,  # Skip long-term for speed
            include_daily=True,       # Recent context is valuable
        )

        # Build personality-infused system prompt
        system_prompt = self.personality.build_fast_prompt(
            memory_context=memory_context,
            chat_level=chat_level,
            project=project_context,
            card=card_context,
        )

        # Inject RAG context if project_id is provided (failure is non-fatal)
        if project_id:
            try:
                rag_context = await get_rag_service().build_rag_context(project_id, user_message)
                if rag_context:
                    system_prompt += (
                        "\n\n## Relevant Context from Project Knowledge Base\n"
                        + rag_context
                    )
            except Exception as e:
                logger.warning(f"RAG context injection failed (chat_fast): {e}")

        response_text = await self._call_api(
            model=self.fast_model,
            system=system_prompt,
            messages=recent,
            client=self.fast_client,
            chat_level=chat_level,
        )

        self._append_and_persist(chat_id, "assistant", response_text, model="fast")
        return response_text

    async def chat_fast_stream(
        self,
        chat_id: str,
        user_message: str,
        project_name: Optional[str] = None,
        chat_level: str = "general",
        project_context: Optional[dict] = None,
        card_context: Optional[dict] = None,
        project_id: Optional[str] = None,
        tool_callback: Optional[Callable[[str, dict, dict], None]] = None,
        project_names: Optional[list] = None,
    ) -> AsyncIterator[str]:
        """Layer 1 (streaming): Yield tokens as they arrive from the fast layer."""
        self._append_and_persist(chat_id, "user", user_message, model="fast")
        history = self._get_history(chat_id)

        settings = get_settings()
        recent = history[-settings.fast_context_messages:]

        memory_context = self.memory.build_memory_context(
            project_name=project_name,
            include_long_term=False,
            include_daily=True,
        )

        system_prompt = self.personality.build_fast_prompt(
            memory_context=memory_context,
            chat_level=chat_level,
            project=project_context,
            card=card_context,
            project_names=project_names,
        )

        # Inject RAG context if project_id is provided (failure is non-fatal)
        if project_id:
            try:
                rag_context = await get_rag_service().build_rag_context(project_id, user_message)
                if rag_context:
                    system_prompt += (
                        "\n\n## Relevant Context from Project Knowledge Base\n"
                        + rag_context
                    )
            except Exception as e:
                logger.warning(f"RAG context injection failed (chat_fast_stream): {e}")

        full_response = ""
        async for token in self._call_api_stream(
            model=self.fast_model,
            system=system_prompt,
            messages=recent,
            client=self.fast_client,
            tool_callback=tool_callback,
            chat_level=chat_level,
        ):
            full_response += token
            yield token

        self._append_and_persist(chat_id, "assistant", full_response, model="fast")

    async def chat_deep_supervisor(
        self,
        chat_id: str,
        user_message: str,
        fast_response: str = "",
        project_name: Optional[str] = None,
        chat_level: str = "general",
        project_context: Optional[dict] = None,
        card_context: Optional[dict] = None,
        project_id: Optional[str] = None,
    ) -> dict:
        """
        Layer 2: Deep supervisor — decides whether to enrich or correct the fast layer's response.

        Waits for the fast layer to finish, then evaluates its response. Returns:
        { "action": "enrich"|"correct"|"none", "content": "..." }
        """
        history = self._get_history(chat_id)

        settings = get_settings()
        recent = history[-settings.deep_context_messages:]

        # Build full memory context for deep layer
        memory_context = self.memory.build_memory_context(
            project_name=project_name,
            include_long_term=True,
            include_daily=True,
        )

        # Supervisor-specific system prompt — conservative by design
        supervisor_base = (
            "You are the deep-thinking supervisor layer of Voxyflow.\n"
            "The user sent a message, and the fast layer already responded.\n"
            "You can see the fast layer's full response below.\n"
            "Your job: decide if the fast response needs improvement.\n\n"
            "Decide one of:\n"
            '- "enrich": Add valuable context, deeper insight, or important nuance the fast layer missed\n'
            '- "correct": Fix a factual error or significant oversight in the fast layer\'s response\n'
            '- "none": The fast layer\'s response was fine, no need to add anything\n\n'
            "BIAS STRONGLY TOWARD 'none'.\n"
            "- If the conversation is casual → \"none\"\n"
            "- If the question is simple → \"none\"\n"
            "- If the fast layer answered reasonably → \"none\"\n"
            "- Simple greetings, acknowledgments, small talk → ALWAYS \"none\"\n"
            "- Only speak up if you have genuinely valuable insight the fast layer missed\n"
            "- Think: \"Would a thoughtful person interrupt to add this?\" If no → \"none\"\n\n"
            "If action is 'enrich' or 'correct', write a natural follow-up message.\n"
            "Make it sound like the same person thinking deeper:\n"
            '- "Actually, now that I think about it..."\n'
            '- "Oh wait, I should also mention..."\n'
            '- "Hmm, let me nuance that..."\n\n'
            "Respond ONLY with valid JSON (no markdown, no code blocks):\n"
            '{"action": "enrich"|"correct"|"none", "content": "..."}\n'
            'If "none", content can be empty string.\n'
            "Respond in the same language the user used."
        )

        system_prompt = self.personality.build_system_prompt(
            base_prompt=supervisor_base,
            include_memory_context=memory_context,
        )

        # Inject RAG context if project_id is provided (failure is non-fatal)
        if project_id:
            try:
                rag_context = await get_rag_service().build_rag_context(project_id, user_message)
                if rag_context:
                    system_prompt += (
                        "\n\n## Relevant Context from Project Knowledge Base\n"
                        + rag_context
                    )
            except Exception as e:
                logger.warning(f"RAG context injection failed (chat_deep_supervisor): {e}")

        # Build messages: conversation history + user message + fast layer's response for evaluation
        eval_messages = [*recent, {"role": "user", "content": user_message}]
        if fast_response:
            eval_messages.append(
                {"role": "assistant", "content": f"[Fast layer's response]: {fast_response}"}
            )
            eval_messages.append(
                {"role": "user", "content": "Evaluate the fast layer's response above. Should you enrich, correct, or stay silent?"}
            )

        try:
            response_text = await self._call_api(
                model=self.deep_model,
                system=system_prompt,
                messages=eval_messages,
                client=self.deep_client,
            )

            # Parse JSON response
            result = json.loads(response_text.strip())
            if result.get("action") in ("enrich", "correct", "none"):
                return result
            return {"action": "none", "content": ""}
        except (json.JSONDecodeError, Exception) as e:
            logger.warning(f"Deep supervisor failed to parse response: {e}")
            return {"action": "none", "content": ""}

    async def chat_deep(
        self,
        chat_id: str,
        user_message: str,
        project_name: Optional[str] = None,
        project_id: Optional[str] = None,
    ) -> Optional[str]:
        """
        Layer 2: Deep analysis, personality-infused.
        Returns None or enrichment text.
        """
        history = self._get_history(chat_id)

        settings = get_settings()
        recent = history[-settings.deep_context_messages:]

        # Build full memory context for deep layer (deeper thinking, more context)
        memory_context = self.memory.build_memory_context(
            project_name=project_name,
            include_long_term=True,
            include_daily=True,
        )

        system_prompt = self.personality.build_deep_prompt(
            memory_context=memory_context,
        )

        # Inject RAG context if project_id is provided (failure is non-fatal)
        if project_id:
            try:
                rag_context = await get_rag_service().build_rag_context(project_id, user_message)
                if rag_context:
                    system_prompt += (
                        "\n\n## Relevant Context from Project Knowledge Base\n"
                        + rag_context
                    )
            except Exception as e:
                logger.warning(f"RAG context injection failed (chat_deep): {e}")

        response_text = await self._call_api(
            model=self.deep_model,
            system=system_prompt,
            messages=recent,
            client=self.deep_client,
        )

        if not response_text or response_text.strip().upper() == "EMPTY":
            return None

        return response_text

    async def chat_with_agent(
        self,
        chat_id: str,
        user_message: str,
        agent_type: AgentType,
        task_context: str = "",
        project_name: Optional[str] = None,
    ) -> str:
        """
        Call Claude with a specialized agent persona.

        Used when a card is assigned to a specific agent type.
        The agent gets: personality + persona + task context + memory.
        """
        self._append_and_persist(chat_id, "user", user_message, model="deep")
        history = self._get_history(chat_id)

        settings = get_settings()
        recent = history[-settings.deep_context_messages:]

        # Get agent persona prompt
        agent_persona_prompt = get_persona_prompt(agent_type)

        # Full memory for specialized work
        memory_context = self.memory.build_memory_context(
            project_name=project_name,
            include_long_term=True,
            include_daily=True,
        )

        # Build combined prompt: personality + agent persona + task
        system_prompt = self.personality.build_agent_prompt(
            agent_persona=agent_persona_prompt,
            task_context=task_context or "Complete the task described in the conversation.",
            memory_context=memory_context,
        )

        # Use deep model for specialized agents (they need deeper thinking)
        response_text = await self._call_api(
            model=self.deep_model,
            system=system_prompt,
            messages=recent,
            client=self.deep_client,
        )

        self._append_and_persist(chat_id, "assistant", response_text, model="deep")
        return response_text

    async def generate_brief(
        self,
        prompt: str,
    ) -> str:
        """One-shot project brief generation using the deep model (Opus). No history, no persistence."""
        system_prompt = (
            "You are a senior product manager and technical architect generating a comprehensive "
            "project brief / PRD. Produce well-structured, professional markdown. "
            "Be thorough, specific, and actionable. Use clear headings, bullet points, and "
            "tables where appropriate. Infer technical details from context when not explicitly provided."
        )
        response = await self._call_api(
            model=self.deep_model,
            system=system_prompt,
            messages=[{"role": "user", "content": prompt}],
            client=self.deep_client,
        )
        return response

    async def generate_health_summary(
        self,
        prompt: str,
    ) -> str:
        """One-shot health check summary using the fast model. No history, no persistence."""
        system_prompt = (
            "You are a project health analyst. Given a project's stats and issues, "
            "write a concise, honest 2-3 sentence summary of the project's health. "
            "Be direct, specific, and actionable. No filler. Use plain text only."
        )
        response = await self._call_api(
            model=self.fast_model,
            system=system_prompt,
            messages=[{"role": "user", "content": prompt}],
            client=self.fast_client,
        )
        return response

    async def generate_standup(
        self,
        prompt: str,
    ) -> str:
        """One-shot standup generation using the fast model. No history, no persistence."""
        system_prompt = (
            "You are a project assistant generating a concise daily standup summary. "
            "Be direct and brief. Use markdown bullet points. No filler words.\n"
            "Format:\n"
            "**✅ Done**\n- ...\n\n**🔨 In Progress**\n- ...\n\n**🚧 Blocked / Risks**\n- ...\n\n**📌 Today's Goals**\n- ..."
        )
        response = await self._call_api(
            model=self.fast_model,
            system=system_prompt,
            messages=[{"role": "user", "content": prompt}],
            client=self.fast_client,
        )
        return response

    async def generate_meeting_notes(
        self,
        notes: str,
    ) -> dict:
        """One-shot meeting notes extraction using the fast model. Returns cards + summary."""
        system_prompt = (
            "You are a project assistant that extracts action items from meeting notes. "
            "Respond ONLY with valid JSON — no markdown, no code blocks, no commentary.\n"
            "The JSON must have two keys:\n"
            '  "cards": an array of objects with keys: title (str), description (str), priority (int 0-3), agent_type (str)\n'
            '  "summary": a brief 1-2 sentence summary of the meeting.\n'
            "Priority scale: 0=low, 1=medium, 2=high, 3=critical.\n"
            "agent_type must be one of: ember, researcher, coder, designer, architect, writer, qa.\n"
            "Auto-detect the most appropriate agent_type based on the action item content."
        )
        prompt = (
            "Extract action items from these meeting notes as structured tasks. "
            "Return JSON with cards array and a brief summary.\n\n"
            f"Meeting notes:\n{notes}"
        )
        response = await self._call_api(
            model=self.fast_model,
            system=system_prompt,
            messages=[{"role": "user", "content": prompt}],
            client=self.fast_client,
        )
        # Strip markdown code fences if any
        text = response.strip()
        if text.startswith("```"):
            text = text.split("```", 2)[1]
            if text.startswith("json"):
                text = text[4:]
            text = text.rsplit("```", 1)[0].strip()
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            # Fallback: return empty structure
            data = {"cards": [], "summary": "Could not parse meeting notes."}
        return data

    async def generate_priority_reasoning(
        self,
        prompt: str,
    ) -> str:
        """One-shot priority reasoning for top-3 cards using the fast model. Returns JSON string."""
        system_prompt = (
            "You are a project prioritization assistant. "
            "Given the top prioritized cards with their scores and attributes, "
            "write a short, specific one-sentence reasoning for why each card is ranked where it is. "
            "Respond ONLY with valid JSON array — no markdown, no code blocks, no commentary."
        )
        response = await self._call_api(
            model=self.fast_model,
            system=system_prompt,
            messages=[{"role": "user", "content": prompt}],
            client=self.fast_client,
        )
        return response

    async def analyze_for_cards(
        self,
        chat_id: str,
        message: str,
        project_name: Optional[str] = None,
    ) -> Optional[str]:
        """
        Call Claude to analyze a message for card suggestions + agent routing.

        Returns structured JSON string or None.
        Used by AnalyzerService for LLM-powered card detection.
        """
        memory_context = self.memory.build_memory_context(
            project_name=project_name,
            include_long_term=False,
            include_daily=True,
        )

        system_prompt = self.personality.build_analyzer_prompt(
            memory_context=memory_context,
        )

        analysis_prompt = (
            "Analyze this message for actionable items. If you detect a task, respond with JSON:\n"
            "```json\n"
            '{\n'
            '  "has_action": true,\n'
            '  "title": "concise action title",\n'
            '  "description": "fuller context",\n'
            '  "priority": 0-4,\n'
            '  "agent_type": "ember|researcher|coder|designer|architect|writer|qa",\n'
            '  "confidence": 0.0-1.0\n'
            '}\n'
            "```\n"
            "If no actionable item, respond: {\"has_action\": false}\n\n"
            f"Message to analyze:\n{message}"
        )

        response = await self._call_api(
            model=self.analyzer_model,
            system=system_prompt,
            messages=[{"role": "user", "content": analysis_prompt}],
            client=self.analyzer_client,
        )

        return response

    async def _call_api(
        self,
        model: str,
        system: str,
        messages: list[dict],
        client: Optional[OpenAI] = None,
        use_tools: bool = True,
        tool_callback: Optional[Callable[[str, dict, dict], None]] = None,
        chat_level: str = "general",
    ) -> str:
        """Make an API call via the OpenAI-compatible proxy.

        When use_tools=True, Claude native tool_use is enabled.  Any tool_use
        blocks are automatically dispatched to the MCP REST layer and the
        results fed back to Claude in an agentic loop until Claude returns a
        final text-only response.

        tool_callback(tool_name, arguments, result) is called after each tool
        execution — callers can use this to emit WebSocket events.
        """
        api_client = client or self.client
        api_messages = [{"role": "system", "content": system}]
        api_messages.extend(messages)

        claude_tools = get_claude_tools(chat_level=chat_level) if use_tools else []

        try:
            # Agentic tool-use loop (max 10 rounds to prevent runaway)
            for _ in range(10):
                kwargs: dict = {
                    "model": model,
                    "max_tokens": self.max_tokens,
                    "messages": api_messages,
                }
                if claude_tools:
                    kwargs["tools"] = claude_tools

                response = await asyncio.to_thread(
                    lambda: api_client.chat.completions.create(**kwargs)
                )

                choice = response.choices[0]
                finish_reason = choice.finish_reason

                # OpenAI SDK flattens tool_calls into .message.tool_calls
                # Check both content and tool_calls
                tool_calls = getattr(choice.message, "tool_calls", None) or []

                if finish_reason == "tool_calls" or (tool_calls and finish_reason in ("stop", "tool_calls", None)):
                    # Append the assistant's tool_call message to history
                    api_messages.append(choice.message.model_dump(exclude_unset=True))

                    # Execute each tool call and collect results
                    tool_results = []
                    for tc in tool_calls:
                        claude_tool_name = tc.function.name
                        try:
                            arguments = json.loads(tc.function.arguments or "{}")
                        except json.JSONDecodeError:
                            arguments = {}

                        mcp_name = _mcp_tool_name_from_claude(claude_tool_name)
                        logger.info(f"[MCP] tool_use: {claude_tool_name} → {mcp_name}({arguments})")

                        result = await _call_mcp_tool(mcp_name, arguments)

                        if tool_callback:
                            try:
                                tool_callback(mcp_name, arguments, result)
                            except Exception:
                                pass  # Callbacks must not crash the pipeline

                        tool_results.append({
                            "role": "tool",
                            "tool_call_id": tc.id,
                            "content": json.dumps(result, default=str),
                        })

                    api_messages.extend(tool_results)
                    # Continue loop — feed results back to Claude
                    continue

                # No tool calls — return final text
                return choice.message.content or ""

            # Exceeded loop limit — return whatever we have
            logger.warning("_call_api: tool loop exceeded 10 rounds, returning empty")
            return ""

        except Exception as e:
            logger.error(f"Claude proxy API call failed: {e}")
            raise

    async def _call_api_stream(
        self,
        model: str,
        system: str,
        messages: list[dict],
        client: Optional[OpenAI] = None,
        use_tools: bool = True,
        tool_callback: Optional[Callable[[str, dict, dict], None]] = None,
        chat_level: str = "general",
    ) -> AsyncIterator[str]:
        """Make a streaming API call via the OpenAI-compatible proxy.

        Yields content tokens as they arrive from the SSE stream.
        When Claude emits tool_use blocks mid-stream, they are buffered,
        executed via MCP, and a second non-streaming call is made so Claude
        can generate its final response (which is then yielded as tokens).

        tool_callback(tool_name, arguments, result) is called after each tool
        execution — callers can use this to emit WebSocket events.
        """
        import asyncio
        import queue
        import threading

        api_client = client or self.client
        api_messages = [{"role": "system", "content": system}]
        api_messages.extend(messages)

        claude_tools = get_claude_tools(chat_level=chat_level) if use_tools else []

        # ---- Streaming first pass ------------------------------------------
        try:
            kwargs: dict = {
                "model": model,
                "max_tokens": self.max_tokens,
                "messages": api_messages,
                "stream": True,
            }
            if claude_tools:
                kwargs["tools"] = claude_tools

            stream = api_client.chat.completions.create(**kwargs)

            token_queue: queue.Queue[str | None] = queue.Queue()
            # Accumulate tool_call data (streamed in fragments)
            streamed_tool_calls: list[dict] = []
            finish_reason_holder: list[str] = []
            content_text_holder: list[str] = []

            def _consume_stream():
                try:
                    for chunk in stream:
                        if not chunk.choices:
                            continue
                        delta = chunk.choices[0].delta
                        finish_reason = chunk.choices[0].finish_reason

                        # Accumulate regular text tokens
                        if delta.content:
                            content_text_holder.append(delta.content)
                            token_queue.put(delta.content)

                        # Accumulate tool call fragments
                        if delta.tool_calls:
                            for tc_delta in delta.tool_calls:
                                idx = tc_delta.index
                                while len(streamed_tool_calls) <= idx:
                                    streamed_tool_calls.append({
                                        "id": None,
                                        "type": "function",
                                        "function": {"name": "", "arguments": ""},
                                    })
                                if tc_delta.id:
                                    streamed_tool_calls[idx]["id"] = tc_delta.id
                                if tc_delta.function:
                                    if tc_delta.function.name:
                                        streamed_tool_calls[idx]["function"]["name"] += tc_delta.function.name
                                    if tc_delta.function.arguments:
                                        streamed_tool_calls[idx]["function"]["arguments"] += tc_delta.function.arguments

                        if finish_reason:
                            finish_reason_holder.append(finish_reason)

                except Exception as e:
                    logger.error(f"Stream consumption error: {e}")
                finally:
                    token_queue.put(None)  # Sentinel

            thread = threading.Thread(target=_consume_stream, daemon=True)
            thread.start()

            # Yield text tokens as they arrive
            while True:
                token = await asyncio.to_thread(token_queue.get)
                if token is None:
                    break
                yield token

            finish_reason = finish_reason_holder[0] if finish_reason_holder else "stop"

            # ---- If Claude requested tool calls, handle them ----------------
            if finish_reason == "tool_calls" or streamed_tool_calls:
                # Build assistant message with tool_calls list
                assistant_msg: dict = {"role": "assistant", "content": "".join(content_text_holder) or None}
                if streamed_tool_calls:
                    assistant_msg["tool_calls"] = [
                        {
                            "id": tc["id"] or f"call_{i}",
                            "type": "function",
                            "function": {
                                "name": tc["function"]["name"],
                                "arguments": tc["function"]["arguments"],
                            },
                        }
                        for i, tc in enumerate(streamed_tool_calls)
                    ]
                api_messages.append(assistant_msg)

                # Execute tools and collect results
                tool_results = []
                for tc in streamed_tool_calls:
                    claude_tool_name = tc["function"]["name"]
                    try:
                        arguments = json.loads(tc["function"]["arguments"] or "{}")
                    except json.JSONDecodeError:
                        arguments = {}

                    mcp_name = _mcp_tool_name_from_claude(claude_tool_name)
                    logger.info(f"[MCP stream] tool_use: {claude_tool_name} → {mcp_name}({arguments})")

                    result = await _call_mcp_tool(mcp_name, arguments)

                    if tool_callback:
                        try:
                            tool_callback(mcp_name, arguments, result)
                        except Exception:
                            pass

                    tool_results.append({
                        "role": "tool",
                        "tool_call_id": tc["id"] or f"call_0",
                        "content": json.dumps(result, default=str),
                    })

                api_messages.extend(tool_results)

                # Second call — non-streaming final response
                final_text = await self._call_api(
                    model=model,
                    system=system,
                    messages=api_messages[1:],  # drop system (re-added inside)
                    client=api_client,
                    use_tools=False,  # no further tool loops on final pass
                )
                if final_text:
                    yield final_text

        except Exception as e:
            logger.error(f"Claude proxy streaming API call failed: {e}")
            raise
