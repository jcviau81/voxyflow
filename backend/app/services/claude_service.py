"""Claude API integration via claude-max-api-proxy (OpenAI-compatible)."""

import json
import logging
from typing import AsyncIterator, Optional

from openai import OpenAI

from app.config import get_settings
from app.services.personality_service import get_personality_service
from app.services.memory_service import get_memory_service
from app.services.agent_personas import AgentType, get_persona_prompt
from app.services.session_store import session_store

logger = logging.getLogger(__name__)


class ClaudeService:
    """
    Handles Claude API calls for both conversation layers.

    Uses claude-max-api-proxy (OpenAI-compatible) at localhost:3456.

    All calls are personality-infused via PersonalityService:
    - SOUL.md + USER.md + IDENTITY.md = consistent Ember personality
    - Memory context from MEMORY.md + daily logs = continuity
    - Agent personas = specialized behavior when needed
    """

    def __init__(self):
        settings = get_settings()
        self.client = OpenAI(
            base_url=settings.claude_proxy_url,
            api_key=settings.claude_api_key,
        )
        self.haiku_model = settings.claude_haiku_model
        self.opus_model = settings.claude_opus_model
        self.analyzer_model = settings.claude_analyzer_model
        self.max_tokens = settings.claude_max_tokens

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

    async def chat_haiku(
        self,
        chat_id: str,
        user_message: str,
        project_name: Optional[str] = None,
    ) -> str:
        """Layer 1: Fast conversational response via Haiku, personality-infused."""
        self._append_and_persist(chat_id, "user", user_message, model="haiku")
        history = self._get_history(chat_id)

        settings = get_settings()
        recent = history[-settings.haiku_context_messages:]

        # Build memory context (lightweight for Haiku — speed matters)
        memory_context = self.memory.build_memory_context(
            project_name=project_name,
            include_long_term=False,  # Skip long-term for speed
            include_daily=True,       # Recent context is valuable
        )

        # Build personality-infused system prompt
        system_prompt = self.personality.build_haiku_prompt(
            memory_context=memory_context,
        )

        response_text = await self._call_api(
            model=self.haiku_model,
            system=system_prompt,
            messages=recent,
        )

        self._append_and_persist(chat_id, "assistant", response_text, model="haiku")
        return response_text

    async def chat_haiku_stream(
        self,
        chat_id: str,
        user_message: str,
        project_name: Optional[str] = None,
        chat_level: str = "general",
        project_context: Optional[dict] = None,
        card_context: Optional[dict] = None,
    ) -> AsyncIterator[str]:
        """Layer 1 (streaming): Yield tokens as they arrive from Haiku."""
        self._append_and_persist(chat_id, "user", user_message, model="haiku")
        history = self._get_history(chat_id)

        settings = get_settings()
        recent = history[-settings.haiku_context_messages:]

        memory_context = self.memory.build_memory_context(
            project_name=project_name,
            include_long_term=False,
            include_daily=True,
        )

        system_prompt = self.personality.build_haiku_prompt(
            memory_context=memory_context,
            chat_level=chat_level,
            project=project_context,
            card=card_context,
        )

        full_response = ""
        async for token in self._call_api_stream(
            model=self.haiku_model,
            system=system_prompt,
            messages=recent,
        ):
            full_response += token
            yield token

        self._append_and_persist(chat_id, "assistant", full_response, model="haiku")

    async def chat_opus_supervisor(
        self,
        chat_id: str,
        user_message: str,
        haiku_response: str = "",
        project_name: Optional[str] = None,
        chat_level: str = "general",
        project_context: Optional[dict] = None,
        card_context: Optional[dict] = None,
    ) -> dict:
        """
        Layer 2: Opus supervisor — decides whether to enrich or correct Haiku's response.

        Waits for Haiku to finish, then evaluates its response. Returns:
        { "action": "enrich"|"correct"|"none", "content": "..." }
        """
        history = self._get_history(chat_id)

        settings = get_settings()
        recent = history[-settings.opus_context_messages:]

        # Build full memory context for Opus
        memory_context = self.memory.build_memory_context(
            project_name=project_name,
            include_long_term=True,
            include_daily=True,
        )

        # Supervisor-specific system prompt — conservative by design
        supervisor_base = (
            "You are the deep-thinking supervisor layer of Voxyflow.\n"
            "The user sent a message, and a fast AI (Haiku) already responded.\n"
            "You can see Haiku's full response below.\n"
            "Your job: decide if the fast response needs improvement.\n\n"
            "Decide one of:\n"
            '- "enrich": Add valuable context, deeper insight, or important nuance Haiku missed\n'
            '- "correct": Fix a factual error or significant oversight in Haiku\'s response\n'
            '- "none": Haiku\'s response was fine, no need to add anything\n\n'
            "BIAS STRONGLY TOWARD 'none'.\n"
            "- If the conversation is casual → \"none\"\n"
            "- If the question is simple → \"none\"\n"
            "- If Haiku answered reasonably → \"none\"\n"
            "- Simple greetings, acknowledgments, small talk → ALWAYS \"none\"\n"
            "- Only speak up if you have genuinely valuable insight Haiku missed\n"
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

        # Build messages: conversation history + user message + Haiku's response for evaluation
        eval_messages = [*recent, {"role": "user", "content": user_message}]
        if haiku_response:
            eval_messages.append(
                {"role": "assistant", "content": f"[Haiku's response]: {haiku_response}"}
            )
            eval_messages.append(
                {"role": "user", "content": "Evaluate Haiku's response above. Should you enrich, correct, or stay silent?"}
            )

        try:
            response_text = await self._call_api(
                model=self.opus_model,
                system=system_prompt,
                messages=eval_messages,
            )

            # Parse JSON response
            result = json.loads(response_text.strip())
            if result.get("action") in ("enrich", "correct", "none"):
                return result
            return {"action": "none", "content": ""}
        except (json.JSONDecodeError, Exception) as e:
            logger.warning(f"Opus supervisor failed to parse response: {e}")
            return {"action": "none", "content": ""}

    async def chat_opus(
        self,
        chat_id: str,
        user_message: str,
        project_name: Optional[str] = None,
    ) -> Optional[str]:
        """
        Layer 2: Deep analysis via Opus, personality-infused.
        Returns None or enrichment text.
        """
        history = self._get_history(chat_id)

        settings = get_settings()
        recent = history[-settings.opus_context_messages:]

        # Build full memory context for Opus (deeper thinking, more context)
        memory_context = self.memory.build_memory_context(
            project_name=project_name,
            include_long_term=True,
            include_daily=True,
        )

        system_prompt = self.personality.build_opus_prompt(
            memory_context=memory_context,
        )

        response_text = await self._call_api(
            model=self.opus_model,
            system=system_prompt,
            messages=recent,
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
        self._append_and_persist(chat_id, "user", user_message, model="opus")
        history = self._get_history(chat_id)

        settings = get_settings()
        recent = history[-settings.opus_context_messages:]

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

        # Use Opus for specialized agents (they need deeper thinking)
        response_text = await self._call_api(
            model=self.opus_model,
            system=system_prompt,
            messages=recent,
        )

        self._append_and_persist(chat_id, "assistant", response_text, model="opus")
        return response_text

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
            model=self.analyzer_model,  # Use Haiku for speed
            system=system_prompt,
            messages=[{"role": "user", "content": analysis_prompt}],
        )

        return response

    async def _call_api(
        self,
        model: str,
        system: str,
        messages: list[dict],
    ) -> str:
        """Make an API call via the OpenAI-compatible proxy."""
        # Build messages list with system prompt as first message
        api_messages = [{"role": "system", "content": system}]
        api_messages.extend(messages)

        try:
            response = self.client.chat.completions.create(
                model=model,
                max_tokens=self.max_tokens,
                messages=api_messages,
            )
            return response.choices[0].message.content or ""
        except Exception as e:
            logger.error(f"Claude proxy API call failed: {e}")
            raise

    async def _call_api_stream(
        self,
        model: str,
        system: str,
        messages: list[dict],
    ) -> AsyncIterator[str]:
        """Make a streaming API call via the OpenAI-compatible proxy.

        Yields content tokens as they arrive from the SSE stream.
        The OpenAI client's streaming is synchronous, so we iterate
        in a thread-safe manner via asyncio.to_thread for each chunk.
        """
        import asyncio

        api_messages = [{"role": "system", "content": system}]
        api_messages.extend(messages)

        try:
            # The OpenAI sync client returns a synchronous iterator for streaming
            stream = self.client.chat.completions.create(
                model=model,
                max_tokens=self.max_tokens,
                messages=api_messages,
                stream=True,
            )

            # Iterate in a thread to avoid blocking the event loop
            # (the sync OpenAI client does blocking HTTP reads)
            import queue
            import threading

            token_queue: queue.Queue[str | None] = queue.Queue()

            def _consume_stream():
                try:
                    for chunk in stream:
                        if chunk.choices and chunk.choices[0].delta.content:
                            token_queue.put(chunk.choices[0].delta.content)
                except Exception as e:
                    logger.error(f"Stream consumption error: {e}")
                finally:
                    token_queue.put(None)  # Sentinel

            thread = threading.Thread(target=_consume_stream, daemon=True)
            thread.start()

            while True:
                # Poll queue without blocking the event loop
                token = await asyncio.to_thread(token_queue.get)
                if token is None:
                    break
                yield token

        except Exception as e:
            logger.error(f"Claude proxy streaming API call failed: {e}")
            raise
