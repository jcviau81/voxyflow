"""Personality Service — loads SOUL/USER/IDENTITY and injects Ember's persona into all Claude calls.

Reads personality configuration from settings.json (saved via Settings UI) and
applies custom_instructions, environment_notes, tone, and warmth to system prompts.
"""

import json
import logging
import os
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# Default workspace path (OpenClaw convention)
WORKSPACE_DIR = Path(os.environ.get("OPENCLAW_WORKSPACE", os.path.expanduser("~/.openclaw/workspace")))

# Voxyflow's own personality files directory
PERSONALITY_DIR = Path(os.environ.get("VOXYFLOW_PERSONALITY_DIR",
    os.path.expanduser("~/.openclaw/workspace/voxyflow/personality")))

# Personality files (defaults — Voxyflow's own copies, not dependent on OpenClaw)
SOUL_FILE = PERSONALITY_DIR / "SOUL.md"
USER_FILE = PERSONALITY_DIR / "USER.md"
IDENTITY_FILE = PERSONALITY_DIR / "IDENTITY.md"
AGENTS_FILE = PERSONALITY_DIR / "AGENTS.md"

# Settings file (written by the Settings UI)
SETTINGS_FILE = os.path.expanduser("~/.openclaw/workspace/voxyflow/settings.json")

# Cache TTL: how often to re-read personality files (seconds)
_CACHE_TTL = 300  # 5 minutes

# Tone/warmth prompt modifiers
TONE_MODIFIERS = {
    "casual": "Use a casual, conversational tone. Be relaxed and natural.",
    "balanced": "Use a balanced tone — professional but approachable.",
    "formal": "Use a formal, polished tone. Be precise and structured.",
}

WARMTH_MODIFIERS = {
    "cold": "Keep responses professional and objective. Minimal emotional language.",
    "warm": "Be warm and friendly. Show genuine interest and care.",
    "hot": "Be very warm, affectionate, and expressive. Full personality, maximum charm.",
}


class PersonalityService:
    """
    Loads and caches SOUL.md, USER.md, and IDENTITY.md to build a
    personality-infused system prompt for all Claude API calls.

    Ember = same voice, same values, everywhere.
    """

    def __init__(self):
        self._cache: dict[str, tuple[float, str]] = {}  # path → (mtime, content)
        self._settings_cache: tuple[float, dict] | None = None  # (mtime, data)

    def _read_if_changed(self, path: Path) -> str:
        """Read file, using mtime cache to avoid unnecessary I/O."""
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
        """Load settings.json with mtime caching."""
        if not os.path.exists(SETTINGS_FILE):
            return {}
        try:
            mtime = os.path.getmtime(SETTINGS_FILE)
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
        """Get the personality section from settings."""
        settings = self._load_settings()
        return settings.get("personality", {})

    def load_soul(self) -> str:
        """Load SOUL.md — core personality, values, vibe. Respects settings override."""
        ps = self.get_personality_settings()
        soul_path = ps.get("soul_file")
        if soul_path:
            return self._read_if_changed(Path(os.path.expanduser(soul_path)))
        return self._read_if_changed(SOUL_FILE)

    def load_user(self) -> str:
        """Load USER.md — who the human is, preferences, context. Respects settings override."""
        ps = self.get_personality_settings()
        user_path = ps.get("user_file")
        if user_path:
            return self._read_if_changed(Path(os.path.expanduser(user_path)))
        return self._read_if_changed(USER_FILE)

    def load_identity(self) -> str:
        """Load IDENTITY.md — name, creature type, emoji, avatar."""
        return self._read_if_changed(IDENTITY_FILE)

    def load_agents(self) -> str:
        """Load AGENTS.md — operating directives. Respects settings override."""
        ps = self.get_personality_settings()
        agents_path = ps.get("agents_file")
        if agents_path:
            return self._read_if_changed(Path(os.path.expanduser(agents_path)))
        return self._read_if_changed(AGENTS_FILE)

    def build_system_prompt(
        self,
        base_prompt: str,
        include_user: bool = True,
        include_memory_context: Optional[str] = None,
        agent_persona: Optional[str] = None,
    ) -> str:
        """
        Build a complete system prompt by layering:
        1. Personality core (SOUL + IDENTITY)
        1b. Operating directives (AGENTS.md)
        2. User context (USER.md)
        2b. Custom instructions, environment notes, tone/warmth from settings
        3. Memory context (recent relevant memories)
        4. Agent persona overlay (if specialized agent)
        5. Base prompt (task-specific instructions)

        The personality is ALWAYS present — agents get it too.
        """
        sections = []

        # --- Layer 1: Who am I? ---
        soul = self.load_soul()
        identity = self.load_identity()
        if soul or identity:
            sections.append("## Who You Are\n")
            if identity:
                sections.append(identity + "\n")
            if soul:
                sections.append(soul + "\n")

        # --- Layer 1b: Operating directives ---
        agents = self.load_agents()
        if agents:
            sections.append("## Operating Directives\n")
            sections.append(agents + "\n")

        # --- Layer 2: Who is the human? ---
        if include_user:
            user = self.load_user()
            if user:
                sections.append("## About Your Human\n")
                sections.append(user + "\n")

        # --- Layer 2b: Custom instructions & environment from settings ---
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

        # --- Layer 3: Memory context ---
        if include_memory_context:
            sections.append("## Relevant Memory\n")
            sections.append(include_memory_context + "\n")

        # --- Layer 4: Agent persona overlay ---
        if agent_persona:
            sections.append("## Specialized Role\n")
            sections.append(agent_persona + "\n")

        # --- Layer 5: Task instructions ---
        sections.append("## Your Current Task\n")
        sections.append(base_prompt)

        return "\n".join(sections)

    def build_haiku_prompt(self, memory_context: Optional[str] = None) -> str:
        """Build personality-infused system prompt for Haiku (fast voice layer)."""
        base = (
            "You are the fast voice layer of Voxyflow — a voice-first project management assistant.\n"
            "You speak naturally and concisely — this is a voice conversation, not a text chat.\n"
            "Keep responses short (1-3 sentences for voice). Be helpful, direct, and friendly.\n"
            "You help manage projects, tasks, and ideas through conversation.\n"
            "When the user describes work to do, acknowledge it naturally.\n"
            "Respond in the same language the user speaks (French or English).\n"
            "Your personality comes through in HOW you say things — tone, word choice, energy.\n"
            "Be yourself. Not a corporate bot."
        )
        return self.build_system_prompt(
            base_prompt=base,
            include_memory_context=memory_context,
        )

    def build_opus_prompt(self, memory_context: Optional[str] = None) -> str:
        """Build personality-infused system prompt for Opus (deep thinking layer)."""
        base = (
            "You are the deep-thinking layer of Voxyflow, a voice PM assistant.\n"
            "You receive the full conversation context and the fast response already given (by Haiku).\n"
            "Your job: only speak if you have something substantively better or different to add.\n"
            "If the Haiku response was fine, return EMPTY (literally the word EMPTY).\n"
            "If you have a correction, better approach, or important nuance, provide it briefly.\n"
            "Start naturally: 'Actually...' or 'One thing to consider...' — this will be spoken aloud.\n"
            "Keep it concise (2-4 sentences max). Respond in the user's language.\n"
            "Your personality is the same as Haiku's — you're one being, thinking deeper."
        )
        return self.build_system_prompt(
            base_prompt=base,
            include_memory_context=memory_context,
        )

    def build_analyzer_prompt(self, memory_context: Optional[str] = None) -> str:
        """Build personality-infused system prompt for the Analyzer (card detection)."""
        base = (
            "You are the analyzer layer of Voxyflow.\n"
            "Your job: detect actionable items in conversation and suggest project cards.\n"
            "You also determine which specialized agent should handle each card.\n"
            "Output structured JSON. No personality in output — just analysis."
        )
        return self.build_system_prompt(
            base_prompt=base,
            include_user=True,
            include_memory_context=memory_context,
        )

    def build_agent_prompt(
        self,
        agent_persona: str,
        task_context: str,
        memory_context: Optional[str] = None,
    ) -> str:
        """Build a specialized agent prompt with personality + persona overlay."""
        return self.build_system_prompt(
            base_prompt=task_context,
            include_memory_context=memory_context,
            agent_persona=agent_persona,
        )


# Module-level singleton
_personality_service: Optional[PersonalityService] = None


def get_personality_service() -> PersonalityService:
    """Get or create the personality service singleton."""
    global _personality_service
    if _personality_service is None:
        _personality_service = PersonalityService()
    return _personality_service
