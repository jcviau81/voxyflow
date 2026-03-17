"""Analyzer Agent — detects actionable items, suggests cards, and routes to agents."""

import json
import logging
from typing import Optional

from app.models.card import CardSuggestion
from app.services.agent_personas import AgentType
from app.services.agent_router import get_agent_router

logger = logging.getLogger(__name__)

# Action signal keywords (expand over time)
ACTION_SIGNALS = {
    "fr": [
        "il faut", "on doit", "à faire", "créer", "implémenter", "corriger",
        "refactorer", "ajouter", "supprimer", "tester", "déployer", "migrer",
        "résoudre", "planifier", "préparer", "configurer", "installer",
    ],
    "en": [
        "need to", "should", "must", "have to", "let's", "gonna",
        "create", "implement", "fix", "refactor", "add", "remove",
        "test", "deploy", "migrate", "resolve", "plan", "set up",
        "configure", "install", "build", "design",
    ],
}


class AnalyzerService:
    """
    Layer 3: Watches conversation for task/card opportunities.

    Enhanced with agent routing: when a card is detected, the analyzer
    also determines which specialized agent should handle it.

    Pipeline:
    1. Keyword-based detection (fast, cheap)
    2. Card extraction (heuristic → LLM-powered)
    3. Agent routing (keyword scoring → smart assignment)
    """

    def __init__(self):
        self._min_confidence = 0.5
        self._router = get_agent_router()

    async def analyze(
        self,
        chat_id: str,
        message: str,
        project_context: str = "",
    ) -> Optional[CardSuggestion]:
        """
        Analyze a message for actionable content.

        Returns a CardSuggestion with agent_type if an action item is detected.
        """
        # Step 1: Quick keyword check (cheap, fast)
        confidence = self._keyword_score(message)
        if confidence < self._min_confidence:
            return None

        # Step 2: Extract card details
        card = self._extract_card(message, confidence, project_context)

        if card:
            logger.info(
                f"Card suggestion detected (confidence={confidence:.2f}, "
                f"agent={card.agent_type}): {card.title}"
            )

        return card

    async def analyze_with_llm(
        self,
        chat_id: str,
        message: str,
        llm_response: Optional[str] = None,
        project_context: str = "",
    ) -> Optional[CardSuggestion]:
        """
        LLM-powered analysis (uses Claude response from claude_service.analyze_for_cards).

        Parses the structured JSON response and enriches with agent routing.
        """
        if not llm_response:
            return None

        try:
            # Extract JSON from response (handle markdown code blocks)
            json_str = llm_response
            if "```json" in json_str:
                json_str = json_str.split("```json")[1].split("```")[0]
            elif "```" in json_str:
                json_str = json_str.split("```")[1].split("```")[0]

            data = json.loads(json_str.strip())

            if not data.get("has_action", False):
                return None

            # Get agent type from LLM suggestion
            agent_type_str = data.get("agent_type", "ember")
            try:
                agent_type = AgentType(agent_type_str)
            except ValueError:
                agent_type = AgentType.EMBER

            # Cross-validate with keyword router
            router_agent, router_confidence = self._router.route(
                title=data.get("title", ""),
                description=data.get("description", ""),
                context=project_context,
            )

            # If router strongly disagrees, prefer router (it's more deterministic)
            if router_confidence > 0.7 and router_agent != agent_type:
                logger.info(
                    f"Router override: LLM suggested {agent_type.value}, "
                    f"router prefers {router_agent.value} (conf={router_confidence:.2f})"
                )
                agent_type = router_agent

            return CardSuggestion(
                title=data.get("title", "Untitled"),
                description=data.get("description", message),
                priority=min(4, max(0, data.get("priority", 0))),
                source_message_id="",  # Set by caller
                confidence=min(1.0, max(0.0, data.get("confidence", 0.5))),
                agent_type=agent_type.value,
                agent_name=self._get_agent_display(agent_type),
            )

        except (json.JSONDecodeError, KeyError, IndexError) as e:
            logger.warning(f"Failed to parse LLM analysis response: {e}")
            # Fall back to heuristic analysis
            return await self.analyze(chat_id, message, project_context)

    def _keyword_score(self, text: str) -> float:
        """Score message for action-likelihood based on keywords."""
        text_lower = text.lower()
        hits = 0

        for lang_keywords in ACTION_SIGNALS.values():
            for keyword in lang_keywords:
                if keyword in text_lower:
                    hits += 1

        if hits == 0:
            return 0.0

        return min(0.3 + (hits * 0.2), 1.0)

    def _extract_card(
        self,
        message: str,
        confidence: float,
        project_context: str = "",
    ) -> Optional[CardSuggestion]:
        """
        Extract card details from message text, including agent assignment.
        """
        # Simple title extraction: first sentence or first 80 chars
        sentences = message.replace("!", ".").replace("?", ".").split(".")
        title = sentences[0].strip()
        if len(title) > 80:
            title = title[:77] + "..."
        if len(title) < 5:
            return None

        # Route to appropriate agent
        agent_type, agent_confidence = self._router.route(
            title=title,
            description=message,
            context=project_context,
        )

        return CardSuggestion(
            title=title,
            description=message,
            priority=1 if confidence > 0.7 else 0,
            source_message_id="",  # Set by caller
            confidence=confidence,
            agent_type=agent_type.value,
            agent_name=self._get_agent_display(agent_type),
        )

    def _get_agent_display(self, agent_type: AgentType) -> str:
        """Get display name with emoji for an agent type."""
        from app.services.agent_personas import get_persona
        persona = get_persona(agent_type)
        return f"{persona.emoji} {persona.name}"
