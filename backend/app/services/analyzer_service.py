"""Analyzer Agent — detects actionable items, suggests cards, and routes to agents."""

import json
import logging
from typing import Optional

from app.models.card import CardSuggestion
from app.services.agent_personas import AgentType, PERSONAS
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


# Title/description patterns for agent type detection.
# Each entry: (agent_type, set_of_trigger_words)
# Pattern match = 2 points (stronger signal than a persona keyword match = 1 point).
TITLE_PATTERNS: list[tuple[AgentType, frozenset]] = [
    (AgentType.QA,         frozenset(["fix", "bug", "test", "debug", "error", "regression", "validate", "verify", "qa"])),
    (AgentType.DESIGNER,   frozenset(["design", "ui", "ux", "layout", "color", "style", "wireframe", "mockup", "icon", "theme"])),
    (AgentType.CODER,      frozenset(["code", "implement", "function", "api", "endpoint", "build", "refactor", "script", "class", "module"])),
    (AgentType.ARCHITECT,  frozenset(["plan", "architecture", "system", "structure", "diagram", "spec", "prd", "schema", "infrastructure"])),
    (AgentType.RESEARCHER, frozenset(["research", "analyze", "analyse", "compare", "review", "investigate", "benchmark", "survey", "evaluate"])),
    (AgentType.WRITER,     frozenset(["write", "content", "doc", "blog", "copy", "readme", "documentation", "article", "rédiger", "blogue"])),
]


def suggest_agent_type(title: str, description: str) -> str:
    """
    Suggest the best agent type string for a card based on its title + description.

    Scoring:
    - Pattern match (TITLE_PATTERNS word in title/description): +2 pts per agent
    - Keyword match (AgentPersona.keywords in title/description): +1 pt per hit,
      normalized by keyword list length to avoid agents with longer lists dominating

    Returns the highest-scoring agent type value (e.g. "coder", "qa", …),
    or "ember" as fallback when no matches or there is a tie.
    """
    combined = f"{title} {description}".lower()
    # Tokenise on word boundaries for pattern matching
    words = set(combined.replace("-", " ").split())

    scores: dict[AgentType, float] = {}

    # --- Pattern matching (2 pts each) ---
    for agent_type, trigger_words in TITLE_PATTERNS:
        hits = len(words & trigger_words)
        if hits:
            scores[agent_type] = scores.get(agent_type, 0.0) + hits * 2

    # --- Persona keyword matching (1 pt each, normalised) ---
    for agent_type, persona in PERSONAS.items():
        if agent_type == AgentType.EMBER or not persona.keywords:
            continue
        kw_hits = sum(1 for kw in persona.keywords if kw in combined)
        if kw_hits:
            # Normalise: divide by sqrt(keyword_count) so big lists don't dominate
            import math
            normalized = kw_hits / math.sqrt(len(persona.keywords))
            scores[agent_type] = scores.get(agent_type, 0.0) + normalized

    if not scores:
        return AgentType.EMBER.value

    best_score = max(scores.values())
    # Collect all agents tied at the top score
    best_agents = [at for at, s in scores.items() if s == best_score]

    # Tie-break: prefer deterministic order (TITLE_PATTERNS order), fall back to EMBER
    if len(best_agents) == 1:
        return best_agents[0].value

    # Multiple agents tied → pick the one that appears first in TITLE_PATTERNS order
    pattern_order = [at for at, _ in TITLE_PATTERNS]
    for at in pattern_order:
        if at in best_agents:
            return at.value

    return AgentType.EMBER.value


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

    # Casual/throwaway messages that should never generate cards
    SKIP_MESSAGES = frozenset([
        'hi', 'hello', 'hey', 'salut', 'allo', 'bonjour', 'bonsoir',
        'ping', 'test', 'ok', 'oui', 'non', 'yes', 'no', 'thanks',
        'merci', 'bye', 'ciao', 'yo', 'sup', 'lol', 'haha', 'hmm',
        'cool', 'nice', 'wow', 'k', 'kk', 'np', 'thx', 'ty',
    ])

    async def analyze(
        self,
        chat_id: str,
        message: str,
        project_context: str = "",
    ) -> Optional[CardSuggestion]:
        """
        Analyze a message for actionable content.

        Returns a CardSuggestion with agent_type if an action item is detected.
        Skips casual/short messages that aren't actionable.
        """
        # Step 0: Skip casual/short messages
        stripped = message.strip()
        if len(stripped) < 15 or stripped.lower().rstrip('!?.') in self.SKIP_MESSAGES:
            return None

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

            card_title = data.get("title", "")
            card_desc = data.get("description", "")

            # Cross-validate with keyword router
            router_agent, router_confidence = self._router.route(
                title=card_title,
                description=card_desc,
                context=project_context,
            )

            # Cross-validate with pattern + persona-keyword scorer
            pattern_agent_str = suggest_agent_type(card_title, card_desc)
            pattern_agent = AgentType(pattern_agent_str)

            # Resolution priority:
            # 1. High-confidence router result (very deterministic)
            # 2. Pattern scorer non-EMBER result (lightweight but accurate)
            # 3. LLM suggestion (may hallucinate agent names)
            if router_confidence > 0.7 and router_agent != agent_type:
                logger.info(
                    f"Router override: LLM suggested {agent_type.value}, "
                    f"router prefers {router_agent.value} (conf={router_confidence:.2f})"
                )
                agent_type = router_agent
            elif pattern_agent != AgentType.EMBER and agent_type == AgentType.EMBER:
                logger.info(
                    f"Pattern override: LLM returned ember, "
                    f"pattern scorer prefers {pattern_agent.value}"
                )
                agent_type = pattern_agent

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

        Agent selection uses a two-pass strategy:
        1. suggest_agent_type() — pattern + persona-keyword scoring (lightweight)
        2. AgentRouter.route() — weighted ROUTING_WEIGHTS scoring (more detailed)

        The router wins if its confidence is high (≥ 0.6); otherwise suggest_agent_type
        wins if it produced a non-EMBER result; final fallback is the router result.
        """
        # Simple title extraction: first sentence or first 80 chars
        sentences = message.replace("!", ".").replace("?", ".").split(".")
        title = sentences[0].strip()
        if len(title) > 80:
            title = title[:77] + "..."
        if len(title) < 5:
            return None

        # Pass 1: pattern + persona-keyword suggestion (always fast)
        suggested_type_str = suggest_agent_type(title, message)
        suggested_type = AgentType(suggested_type_str)

        # Pass 2: router (weighted ROUTING_WEIGHTS)
        router_type, router_confidence = self._router.route(
            title=title,
            description=message,
            context=project_context,
        )

        # Resolution: high-confidence router result takes priority
        if router_confidence >= 0.6:
            agent_type = router_type
        elif suggested_type != AgentType.EMBER:
            # suggest_agent_type found a strong signal; prefer it
            agent_type = suggested_type
        else:
            agent_type = router_type

        return CardSuggestion(
            title=title,
            description=message,
            priority=1 if confidence > 0.7 else 0,
            source_message_id="",  # Set by caller
            confidence=confidence,
            agent_type=agent_type.value,
            agent_name=self._get_agent_display(agent_type),
        )

    async def analyze_for_cards(
        self,
        chat_id: str,
        message: str,
        project_context: str = "",
    ) -> list[dict]:
        """
        Layer 3: Analyze a message for actionable items and return card suggestions.

        Returns a list of card suggestion dicts:
        [{"title": "...", "description": "...", "agent_type": "...", "agent_name": "..."}]

        Uses heuristic analysis first. If LLM-based analysis is available via
        ClaudeService, it enriches the result. Returns empty list if nothing detected.
        """
        # Step 1: Heuristic analysis (fast, no API call)
        card = await self.analyze(chat_id, message, project_context)

        if not card:
            return []

        return [
            {
                "title": card.title,
                "description": card.description,
                "agent_type": card.agent_type,
                "agent_name": card.agent_name,
                "priority": card.priority,
                "confidence": card.confidence,
            }
        ]

    def _get_agent_display(self, agent_type: AgentType) -> str:
        """Get display name with emoji for an agent type."""
        from app.services.agent_personas import get_persona
        persona = get_persona(agent_type)
        return f"{persona.emoji} {persona.name}"
