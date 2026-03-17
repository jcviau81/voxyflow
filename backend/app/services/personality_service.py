"""Personality Service — loads SOUL/USER/IDENTITY and injects Ember's persona into all Claude calls."""

import logging
import os
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# Default workspace path (OpenClaw convention)
WORKSPACE_DIR = Path(os.environ.get("OPENCLAW_WORKSPACE", os.path.expanduser("~/.openclaw/workspace")))

# Personality files
SOUL_FILE = WORKSPACE_DIR / "SOUL.md"
USER_FILE = WORKSPACE_DIR / "USER.md"
IDENTITY_FILE = WORKSPACE_DIR / "IDENTITY.md"

# Cache TTL: how often to re-read personality files (seconds)
_CACHE_TTL = 300  # 5 minutes


class PersonalityService:
    """
    Loads and caches SOUL.md, USER.md, and IDENTITY.md to build a
    personality-infused system prompt for all Claude API calls.

    Ember = same voice, same values, everywhere.
    """

    def __init__(self):
        self._cache: dict[str, tuple[float, str]] = {}  # path → (mtime, content)

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

    def load_soul(self) -> str:
        """Load SOUL.md — core personality, values, vibe."""
        return self._read_if_changed(SOUL_FILE)

    def load_user(self) -> str:
        """Load USER.md — who the human is, preferences, context."""
        return self._read_if_changed(USER_FILE)

    def load_identity(self) -> str:
        """Load IDENTITY.md — name, creature type, emoji, avatar."""
        return self._read_if_changed(IDENTITY_FILE)

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
        2. User context (USER.md)
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

        # --- Layer 2: Who is the human? ---
        if include_user:
            user = self.load_user()
            if user:
                sections.append("## About Your Human\n")
                sections.append(user + "\n")

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
