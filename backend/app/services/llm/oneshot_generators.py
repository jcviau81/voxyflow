"""One-shot generation mixin for ClaudeService (brief/standup/meeting-notes/...).

Extracted verbatim from app.services.claude_service.

OneShotMixin expects the composing class to provide the fast/deep layer
attributes (``*_model``/``*_client``/``*_client_type``) and ``self._call_api``
from ApiCallerMixin.
"""

import json


class OneShotMixin:
    """One-shot generators — no history, no persistence."""

    async def generate_brief(self, prompt: str) -> str:
        """One-shot workspace brief generation using the deep model. No history, no persistence."""
        system_prompt = (
            "You are a senior product manager and technical architect generating a comprehensive "
            "workspace brief / PRD. Produce well-structured, professional markdown. "
            "Be thorough, specific, and actionable. Use clear headings, bullet points, and "
            "tables where appropriate. Infer technical details from context when not explicitly provided."
        )
        return await self._call_api(
            model=self.deep_model,
            system=system_prompt,
            messages=[{"role": "user", "content": prompt}],
            client=self.deep_client,
            client_type=self.deep_client_type,
            use_tools=False,
        )

    async def generate_health_summary(self, prompt: str) -> str:
        """One-shot health check summary using the fast model."""
        system_prompt = (
            "You are a workspace health analyst. Given a workspace's stats and issues, "
            "write a concise, honest 2-3 sentence summary of the workspace's health. "
            "Be direct, specific, and actionable. No filler. Use plain text only."
        )
        return await self._call_api(
            model=self.fast_model,
            system=system_prompt,
            messages=[{"role": "user", "content": prompt}],
            client=self.fast_client,
            client_type=self.fast_client_type,
            use_tools=False,
        )

    async def generate_standup(self, prompt: str) -> str:
        """One-shot standup generation using the fast model."""
        system_prompt = (
            "You are a workspace assistant generating a concise daily standup summary. "
            "Be direct and brief. Use markdown bullet points. No filler words.\n"
            "Format:\n"
            "**✅ Done**\n- ...\n\n**🔨 In Progress**\n- ...\n\n**🚧 Blocked / Risks**\n- ...\n\n**📌 Today's Goals**\n- ..."
        )
        return await self._call_api(
            model=self.fast_model,
            system=system_prompt,
            messages=[{"role": "user", "content": prompt}],
            client=self.fast_client,
            client_type=self.fast_client_type,
            use_tools=False,
        )

    async def generate_meeting_notes(self, notes: str) -> dict:
        """One-shot meeting notes extraction. Returns cards + summary."""
        system_prompt = (
            "You are a workspace assistant that extracts action items from meeting notes. "
            "Respond ONLY with valid JSON — no markdown, no code blocks, no commentary.\n"
            "The JSON must have two keys:\n"
            '  "cards": an array of objects with keys: title (str), description (str), priority (int 0-3), agent_type (str)\n'
            '  "summary": a brief 1-2 sentence summary of the meeting.\n'
            "Priority scale: 0=low, 1=medium, 2=high, 3=critical.\n"
            "agent_type must be one of: general, researcher, coder, designer, architect, writer, qa.\n"
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
            client_type=self.fast_client_type,
            use_tools=False,
        )
        text = response.strip()
        if text.startswith("```"):
            text = text.split("```", 2)[1]
            if text.startswith("json"):
                text = text[4:]
            text = text.rsplit("```", 1)[0].strip()
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return {"cards": [], "summary": "Could not parse meeting notes."}

    async def generate_priority_reasoning(self, prompt: str) -> str:
        """One-shot priority reasoning for top-3 cards. Returns JSON string."""
        system_prompt = (
            "You are a workspace prioritization assistant. "
            "Given the top prioritized cards with their scores and attributes, "
            "write a short, specific one-sentence reasoning for why each card is ranked where it is. "
            "Respond ONLY with valid JSON array — no markdown, no code blocks, no commentary."
        )
        return await self._call_api(
            model=self.fast_model,
            system=system_prompt,
            messages=[{"role": "user", "content": prompt}],
            client=self.fast_client,
            client_type=self.fast_client_type,
            use_tools=False,
        )
