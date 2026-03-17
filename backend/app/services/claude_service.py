"""Claude API integration — Haiku (fast) and Opus (deep) layers, personality-infused."""

import logging
from typing import Optional

import httpx

from app.config import get_settings
from app.services.personality_service import get_personality_service
from app.services.memory_service import get_memory_service
from app.services.agent_personas import AgentType, get_persona_prompt

logger = logging.getLogger(__name__)


class ClaudeService:
    """
    Handles Claude API calls for both conversation layers.

    All calls are personality-infused via PersonalityService:
    - SOUL.md + USER.md + IDENTITY.md = consistent Ember personality
    - Memory context from MEMORY.md + daily logs = continuity
    - Agent personas = specialized behavior when needed
    """

    def __init__(self):
        settings = get_settings()
        self.api_key = settings.claude_api_key
        self.haiku_model = settings.claude_haiku_model
        self.opus_model = settings.claude_opus_model
        self.max_tokens = settings.claude_max_tokens
        self.base_url = "https://api.anthropic.com/v1"

        self.personality = get_personality_service()
        self.memory = get_memory_service()

        # In-memory conversation history (MVP — move to DB later)
        self._histories: dict[str, list[dict]] = {}

    def _get_history(self, chat_id: str) -> list[dict]:
        if chat_id not in self._histories:
            self._histories[chat_id] = []
        return self._histories[chat_id]

    async def chat_haiku(
        self,
        chat_id: str,
        user_message: str,
        project_name: Optional[str] = None,
    ) -> str:
        """Layer 1: Fast conversational response via Haiku, personality-infused."""
        history = self._get_history(chat_id)
        history.append({"role": "user", "content": user_message})

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

        history.append({"role": "assistant", "content": response_text})
        return response_text

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
        history = self._get_history(chat_id)
        history.append({"role": "user", "content": user_message})

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

        history.append({"role": "assistant", "content": response_text})
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
            model=self.haiku_model,  # Use Haiku for speed
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
        """Make a Claude API call."""
        if not self.api_key:
            logger.warning("No Claude API key configured — returning placeholder")
            return "[Claude API key not configured]"

        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                f"{self.base_url}/messages",
                headers={
                    "x-api-key": self.api_key,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json={
                    "model": model,
                    "max_tokens": self.max_tokens,
                    "system": system,
                    "messages": messages,
                },
            )
            response.raise_for_status()
            data = response.json()

            content_blocks = data.get("content", [])
            texts = [b["text"] for b in content_blocks if b.get("type") == "text"]
            return " ".join(texts)
