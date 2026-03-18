"""Personality Service — loads personality files and builds context-isolated system prompts.

Reads personality configuration from settings.json (saved via Settings UI) and
applies custom_instructions, environment_notes, tone, and warmth to system prompts.

IMPORTANT: Personality files are loaded from voxyflow/personality/ by default,
NOT from the OpenClaw workspace. This prevents context leakage between systems.
"""

import json
import logging
import os
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# Voxyflow's own personality directory (NOT OpenClaw workspace)
VOXYFLOW_DIR = Path(os.environ.get("VOXYFLOW_DIR", os.path.expanduser("~/.openclaw/workspace/voxyflow")))
PERSONALITY_DIR = VOXYFLOW_DIR / "personality"

# Personality files — isolated to Voxyflow
SOUL_FILE = PERSONALITY_DIR / "SOUL.md"
USER_FILE = PERSONALITY_DIR / "USER.md"
IDENTITY_FILE = PERSONALITY_DIR / "IDENTITY.md"
AGENTS_FILE = PERSONALITY_DIR / "AGENTS.md"

# Settings file (written by the Settings UI)
SETTINGS_FILE = VOXYFLOW_DIR / "settings.json"

_CACHE_TTL = 300  # 5 minutes

TONE_MODIFIERS = {
    "casual": "Use a casual, conversational tone. Be relaxed and natural.",
    "balanced": "Use a balanced tone -- professional but approachable.",
    "formal": "Use a formal, polished tone. Be precise and structured.",
}

WARMTH_MODIFIERS = {
    "cold": "Keep responses professional and objective. Minimal emotional language.",
    "warm": "Be warm and friendly. Show genuine interest and care.",
    "hot": "Be very warm, affectionate, and expressive. Full personality, maximum charm.",
}


class PersonalityService:
    """Loads and caches personality files to build system prompts for Claude API calls."""

    def __init__(self):
        self._cache: dict[str, tuple[float, str]] = {}
        self._settings_cache: tuple[float, dict] | None = None

    def _read_if_changed(self, path: Path) -> str:
        if not path.exists():
            return ""
        try:
            mtime = path.stat().st_mtime
            cached = self._cache.get(str(path))
            if cached and cached[0] == mtime:
                return cached[1]
            content = path.read_text(encoding="utf-8").strip()
            self._cache[str(path)] = (mtime, content)
            return content
        except Exception as e:
            logger.warning(f"Failed to read personality file {path}: {e}")
            return ""

    def _load_settings(self) -> dict:
        if not SETTINGS_FILE.exists():
            return {}
        try:
            mtime = SETTINGS_FILE.stat().st_mtime
            if self._settings_cache and self._settings_cache[0] == mtime:
                return self._settings_cache[1]
            with open(SETTINGS_FILE) as f:
                data = json.load(f)
            self._settings_cache = (mtime, data)
            return data
        except Exception as e:
            logger.warning(f"Failed to read settings.json: {e}")
            return {}

    def get_personality_settings(self) -> dict:
        settings = self._load_settings()
        return settings.get("personality", {})

    def _resolve_path(self, raw_path: str) -> Path:
        """Resolve a personality file path, relative to VOXYFLOW_DIR."""
        p = Path(raw_path)
        if p.is_absolute():
            return p
        expanded = Path(os.path.expanduser(raw_path))
        if expanded.is_absolute():
            return expanded
        return VOXYFLOW_DIR / raw_path

    def load_soul(self) -> str:
        ps = self.get_personality_settings()
        soul_path = ps.get("soul_file")
        if soul_path:
            return self._read_if_changed(self._resolve_path(soul_path))
        return self._read_if_changed(SOUL_FILE)

    def load_user(self) -> str:
        ps = self.get_personality_settings()
        user_path = ps.get("user_file")
        if user_path:
            return self._read_if_changed(self._resolve_path(user_path))
        return self._read_if_changed(USER_FILE)

    def load_identity(self) -> str:
        ps = self.get_personality_settings()
        identity_path = ps.get("identity_file")
        if identity_path:
            return self._read_if_changed(self._resolve_path(identity_path))
        return self._read_if_changed(IDENTITY_FILE)

    def load_agents(self) -> str:
        ps = self.get_personality_settings()
        agents_path = ps.get("agents_file")
        if agents_path:
            return self._read_if_changed(self._resolve_path(agents_path))
        return self._read_if_changed(AGENTS_FILE)

    # ------------------------------------------------------------------
    # Context-isolated prompt builders (general / project / card)
    # ------------------------------------------------------------------

    def build_general_prompt(self) -> str:
        """Build system prompt for General Chat — no project context."""
        soul = self.load_soul()
        user = self.load_user()
        identity = self.load_identity()
        agents = self.load_agents()

        sections = []
        if identity:
            sections.append(identity)
        if soul:
            sections.append(soul)
        if agents:
            sections.append(agents)
        if user:
            sections.append(user)

        sections.append(
            "## Context: General Chat\n"
            "You are in the General Chat. This is a free conversation space.\n"
            "Help the user brainstorm, chat, or start new projects.\n"
            "Do NOT reference specific projects unless the user brings them up.\n"
            "Do NOT assume you know the user's projects or history unless they tell you."
        )

        return "\n\n".join(sections)

    def build_project_prompt(self, project: dict) -> str:
        """Build system prompt for Project Chat — scoped to one project."""
        soul = self.load_soul()
        user = self.load_user()
        agents = self.load_agents()

        sections = []
        if soul:
            sections.append(soul)
        if agents:
            sections.append(agents)
        if user:
            sections.append(user)

        project_ctx = (
            f"## Context: Project Chat\n"
            f"CURRENT PROJECT: {project.get('title', 'Untitled')}\n"
            f"Description: {project.get('description', 'No description')}\n"
            f"Technologies: {project.get('tech_stack', 'Not detected')}\n"
            f"GitHub: {project.get('github_url', 'Not linked')}\n\n"
            f"You are working within this project. Keep all responses relevant to this project.\n"
            f"Do NOT reference other projects or unrelated topics.\n"
            f"Do NOT bring up information from other conversations or contexts."
        )
        sections.append(project_ctx)

        return "\n\n".join(sections)

    def build_card_prompt(self, project: dict, card: dict, agent_persona: Optional[dict] = None) -> str:
        """Build system prompt for Card Chat — scoped to a specific task."""
        soul = self.load_soul()

        sections = []

        # Agent persona first (if provided)
        if agent_persona and agent_persona.get("system_prompt"):
            sections.append(agent_persona["system_prompt"])

        if soul:
            sections.append(soul)

        card_ctx = (
            f"## Context: Card/Task Chat\n"
            f"PROJECT: {project.get('title', 'Untitled')}\n"
            f"CARD: {card.get('title', 'Untitled')}\n"
            f"Description: {card.get('description', '')}\n"
            f"Status: {card.get('status', 'idea')}\n"
            f"Priority: {card.get('priority', 'medium')}\n"
            f"Dependencies: {card.get('dependencies', 'None')}\n\n"
            f"You are focused on this specific task. Stay on topic.\n"
            f"Do NOT reference other projects, other cards, or unrelated topics."
        )
        sections.append(card_ctx)

        return "\n\n".join(sections)

    # ------------------------------------------------------------------
    # Legacy/generic prompt builder (used by existing layer methods)
    # ------------------------------------------------------------------

    def build_system_prompt(
        self,
        base_prompt: str,
        include_user: bool = True,
        include_memory_context: Optional[str] = None,
        agent_persona: Optional[str] = None,
    ) -> str:
        sections = []

        # Layer 1: Who am I?
        soul = self.load_soul()
        identity = self.load_identity()
        if soul or identity:
            sections.append("## Who You Are\n")
            if identity:
                sections.append(identity + "\n")
            if soul:
                sections.append(soul + "\n")

        # Layer 1b: Operating directives
        agents = self.load_agents()
        if agents:
            sections.append("## Operating Directives\n")
            sections.append(agents + "\n")

        # Layer 2: Who is the human?
        if include_user:
            user = self.load_user()
            if user:
                sections.append("## About Your Human\n")
                sections.append(user + "\n")

        # Layer 2b: Settings overrides
        ps = self.get_personality_settings()
        custom = ps.get("custom_instructions", "").strip()
        env_notes = ps.get("environment_notes", "").strip()
        tone = ps.get("tone", "casual")
        warmth = ps.get("warmth", "warm")

        style_parts = []
        if tone in TONE_MODIFIERS:
            style_parts.append(TONE_MODIFIERS[tone])
        if warmth in WARMTH_MODIFIERS:
            style_parts.append(WARMTH_MODIFIERS[warmth])
        if style_parts:
            sections.append("## Communication Style\n")
            sections.append("\n".join(style_parts) + "\n")

        if custom:
            sections.append("## Custom Instructions\n")
            sections.append(custom + "\n")

        if env_notes:
            sections.append("## Environment Notes\n")
            sections.append(env_notes + "\n")

        # Layer 3: Memory context
        if include_memory_context:
            sections.append("## Relevant Memory\n")
            sections.append(include_memory_context + "\n")

        # Layer 4: Agent persona overlay
        if agent_persona:
            sections.append("## Specialized Role\n")
            sections.append(agent_persona + "\n")

        # Layer 5: Task instructions
        sections.append("## Your Current Task\n")
        sections.append(base_prompt)

        return "\n".join(sections)

    def build_fast_prompt(self, memory_context: Optional[str] = None, chat_level: str = "general", project: Optional[dict] = None, card: Optional[dict] = None, agent_persona: Optional[dict] = None) -> str:
        from app.tools import get_tool_definitions

        tool_defs = get_tool_definitions()
        tool_section = ""
        if tool_defs:
            import json as _json
            tool_section = (
                "\n\n## Available Tools\n"
                "You can execute actions in Voxyflow using tools. To use a tool, include in your response:\n"
                "<tool_call>\n"
                '{"name": "tool_name", "params": {"key": "value"}}\n'
                "</tool_call>\n\n"
                "You can use multiple tools in one response. Write your conversational reply normally "
                "AND include tool calls where appropriate.\n\n"
                "Available tools:\n"
                + _json.dumps(tool_defs, indent=2)
            )

        voice_instructions = (
            "\n\n## Voice Instructions\n"
            "You speak naturally and concisely -- this is a voice conversation, not a text chat.\n"
            "Keep responses short (1-3 sentences for voice). Be helpful, direct, and friendly.\n"
            "You help manage projects, tasks, and ideas through conversation.\n"
            "When the user describes work to do, acknowledge it naturally.\n"
            "Respond in the same language the user speaks (French or English).\n"
            "Your personality comes through in HOW you say things -- tone, word choice, energy.\n"
            "Be yourself. Not a corporate bot."
        )

        # Build context-appropriate base prompt
        if chat_level == "card" and card and project:
            base = self.build_card_prompt(project, card, agent_persona)
        elif chat_level == "project" and project:
            base = self.build_project_prompt(project)
        else:
            base = self.build_general_prompt()

        return base + voice_instructions + tool_section

    def build_deep_prompt(self, memory_context: Optional[str] = None, chat_level: str = "general", project: Optional[dict] = None, card: Optional[dict] = None) -> str:
        # Build context-appropriate base
        if chat_level == "card" and card and project:
            base = self.build_card_prompt(project, card)
        elif chat_level == "project" and project:
            base = self.build_project_prompt(project)
        else:
            base = self.build_general_prompt()

        deep_instructions = (
            "\n\n## Deep Thinking Layer\n"
            "You are the deep-thinking layer of Voxyflow, a voice PM assistant.\n"
            "You receive the full conversation context and the fast response already given.\n"
            "Your job: only speak if you have something substantively better or different to add.\n"
            "If the fast layer's response was fine, return EMPTY (literally the word EMPTY).\n"
            "If you have a correction, better approach, or important nuance, provide it briefly.\n"
            "Start naturally: 'Actually...' or 'One thing to consider...' -- this will be spoken aloud.\n"
            "Keep it concise (2-4 sentences max). Respond in the user's language.\n"
            "Your personality is the same as the fast layer's -- you're one being, thinking deeper."
        )

        return base + deep_instructions

    def build_analyzer_prompt(self, memory_context: Optional[str] = None) -> str:
        base = (
            "You are the analyzer layer of Voxyflow.\n"
            "Your job: detect actionable items in conversation and suggest project cards.\n"
            "You also determine which specialized agent should handle each card.\n"
            "Output structured JSON. No personality in output -- just analysis."
        )
        return self.build_system_prompt(base_prompt=base, include_user=True, include_memory_context=memory_context)

    def build_agent_prompt(self, agent_persona: str, task_context: str, memory_context: Optional[str] = None) -> str:
        return self.build_system_prompt(base_prompt=task_context, include_memory_context=memory_context, agent_persona=agent_persona)


_personality_service: Optional[PersonalityService] = None


def get_personality_service() -> PersonalityService:
    global _personality_service
    if _personality_service is None:
        _personality_service = PersonalityService()
    return _personality_service
