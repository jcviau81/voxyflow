"""Agent Router — smart assignment of cards to specialized agent personas."""

import logging
from typing import Optional

from app.services.agent_personas import AgentType, get_persona

logger = logging.getLogger(__name__)

# Weighted keyword categories for smarter routing
# Higher weight = stronger signal for that agent type
ROUTING_WEIGHTS = {
    AgentType.CODER: {
        "strong": ["code", "implement", "debug", "refactor", "api", "endpoint", "function", "class",
                    "coder", "implémenter", "corriger", "bug", "database", "migration"],
        "moderate": ["build", "deploy", "script", "module", "test", "setup", "config",
                     "construire", "déployer", "configurer"],
    },
    AgentType.ARCHITECT: {
        "strong": ["architecture", "system design", "prd", "spec", "infrastructure", "schema",
                    "architecte", "système", "diagramme", "structure"],
        "moderate": ["plan", "design", "scale", "stack", "migration", "microservice",
                     "planifier", "concevoir"],
    },
    AgentType.DESIGNER: {
        "strong": ["ui", "ux", "wireframe", "mockup", "interface", "layout",
                    "maquette", "composant", "responsive"],
        "moderate": ["design", "style", "theme", "icon", "button", "form", "color",
                     "couleur", "navigation", "animation"],
    },
    AgentType.RESEARCHER: {
        "strong": ["research", "analyze", "investigate", "benchmark", "survey",
                    "recherche", "analyser", "comparer", "étudier"],
        "moderate": ["compare", "evaluate", "assess", "report", "study",
                     "évaluer", "rapport"],
    },
    AgentType.WRITER: {
        "strong": ["write", "blog", "article", "copy", "content", "documentation",
                    "écrire", "rédiger", "blogue", "contenu"],
        "moderate": ["readme", "marketing", "pitch", "story", "description",
                     "histoire", "texte"],
    },
    AgentType.QA: {
        "strong": ["test", "qa", "quality", "validate", "bug", "regression",
                    "tester", "qualité", "valider", "bogue"],
        "moderate": ["verify", "coverage", "edge case", "e2e", "integration",
                     "vérifier", "assertion"],
    },
}


class AgentRouter:
    """
    Routes cards to the most appropriate specialized agent.

    Lightweight BMAD-inspired system:
    - Analyzes card content (title + description + context)
    - Scores each agent type based on keyword matching
    - Returns best match with confidence score
    - Falls back to Ember (default) if no strong match
    """

    def __init__(self, min_confidence: float = 0.3):
        self.min_confidence = min_confidence

    def route(
        self,
        title: str,
        description: str = "",
        context: str = "",
    ) -> tuple[AgentType, float]:
        """
        Determine the best agent type for a card.

        Returns (agent_type, confidence_score).
        Confidence 0.0-1.0: below min_confidence returns Ember.
        """
        text = f"{title} {description} {context}".lower()
        scores: dict[AgentType, float] = {}

        for agent_type, weight_groups in ROUTING_WEIGHTS.items():
            score = 0.0
            strong_hits = 0
            moderate_hits = 0

            for keyword in weight_groups.get("strong", []):
                if keyword in text:
                    strong_hits += 1
                    score += 3.0

            for keyword in weight_groups.get("moderate", []):
                if keyword in text:
                    moderate_hits += 1
                    score += 1.0

            # Normalize score (rough 0-1 scale)
            if strong_hits > 0 or moderate_hits > 0:
                # At least one strong hit = high base confidence
                if strong_hits >= 2:
                    scores[agent_type] = min(0.9, 0.5 + (score * 0.05))
                elif strong_hits == 1:
                    scores[agent_type] = min(0.8, 0.35 + (score * 0.05))
                else:
                    scores[agent_type] = min(0.6, 0.15 + (score * 0.05))

        if not scores:
            return AgentType.GENERAL, 0.0

        # Get highest scoring agent
        best_agent = max(scores, key=scores.get)  # type: ignore
        best_score = scores[best_agent]

        if best_score < self.min_confidence:
            return AgentType.GENERAL, best_score

        logger.info(f"Routed to {best_agent.value} (confidence={best_score:.2f}): {title[:60]}")
        return best_agent, best_score

    def route_with_details(
        self,
        title: str,
        description: str = "",
        context: str = "",
    ) -> dict:
        """
        Route with full details — useful for UI display.

        Returns dict with agent_type, confidence, persona info, and all scores.
        """
        agent_type, confidence = self.route(title, description, context)
        persona = get_persona(agent_type)

        # Get all scores for transparency
        text = f"{title} {description} {context}".lower()
        all_scores = {}
        for at in AgentType:
            if at == AgentType.GENERAL:
                continue
            score_val = 0.0
            weights = ROUTING_WEIGHTS.get(at, {})
            for keyword in weights.get("strong", []):
                if keyword in text:
                    score_val += 3.0
            for keyword in weights.get("moderate", []):
                if keyword in text:
                    score_val += 1.0
            if score_val > 0:
                all_scores[at.value] = round(score_val, 2)

        return {
            "agent_type": agent_type.value,
            "confidence": round(confidence, 2),
            "agent_name": persona.name,
            "agent_emoji": persona.emoji,
            "agent_description": persona.description,
            "all_scores": all_scores,
        }



# Module-level singleton
_agent_router: Optional[AgentRouter] = None


def get_agent_router() -> AgentRouter:
    global _agent_router
    if _agent_router is None:
        _agent_router = AgentRouter()
    return _agent_router
