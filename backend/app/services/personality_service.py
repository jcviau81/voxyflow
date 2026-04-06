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
VOXYFLOW_DIR = Path(os.environ.get("VOXYFLOW_DIR", os.path.expanduser("~/voxyflow")))
PERSONALITY_DIR = VOXYFLOW_DIR / "personality"

# Personality files — isolated to Voxyflow
SOUL_FILE = PERSONALITY_DIR / "SOUL.md"
USER_FILE = PERSONALITY_DIR / "USER.md"
IDENTITY_FILE = PERSONALITY_DIR / "IDENTITY.md"
AGENTS_FILE = PERSONALITY_DIR / "AGENTS.md"
DISPATCHER_FILE = PERSONALITY_DIR / "DISPATCHER.md"
WORKER_FILE = PERSONALITY_DIR / "WORKER.md"
ANALYZER_FILE = PERSONALITY_DIR / "ANALYZER.md"
ARCHITECTURE_FILE = PERSONALITY_DIR / "ARCHITECTURE.md"

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

LANGUAGE_INSTRUCTIONS = {
    "en": "Always respond in English, regardless of the user's language.",
    "fr": "Réponds toujours en français, peu importe la langue de l'utilisateur.",
    "both": "Respond in the same language the user speaks (French or English).",
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

    def load_dispatcher(self) -> str:
        return self._read_if_changed(DISPATCHER_FILE)

    def load_worker(self) -> str:
        return self._read_if_changed(WORKER_FILE)

    def load_analyzer(self) -> str:
        return self._read_if_changed(ANALYZER_FILE)

    def load_architecture(self) -> str:
        return self._read_if_changed(ARCHITECTURE_FILE)

    # ------------------------------------------------------------------
    # Chat Init block builders (injected FIRST in all system prompts)
    # ------------------------------------------------------------------

    def build_general_chat_init(self, project_names: Optional[list] = None) -> str:
        """Build the Chat Init block for Main project chat (system-main).

        This is now just a project chat for the system "Main" project.
        Kept as a separate method for backward compatibility.
        The static base omits project_names — inject dynamically via build_dynamic_context_block().
        """
        return (
            "## Who You Are\n"
            "You are Voxy. This is your home — Voxyflow. You are not a generic AI exploring an unfamiliar system. "
            "You live here. You know this place. You are already present, already oriented, already ready.\n\n"
            "Do not start by orienting yourself. Do not explain what you could do. Just be here and act.\n\n"
            "## How You Work\n"
            "When the user says something, you respond and act — in that order. "
            "If they ask you to create a card, you create it. If they want to brainstorm, you brainstorm. "
            "You don't ask for permission to do what you were clearly asked to do.\n"
            "You use your tools silently and naturally — like someone who knows their workspace.\n\n"
            "## Right Now\n"
            "You are in the Main project — the default workspace for ideas, cards, and conversation. "
            "If the user mentions a different project by name, pivot to it. "
            "Cards created here belong to the Main project.\n\n"
            "Do NOT say 'welcome back' on a first conversation. Greet naturally based on what they said."
        )

    def build_project_chat_init(self, project: dict) -> str:
        """Build the static Chat Init block for Project Chat mode.

        Dynamic details (description, card counts, recent activity) are intentionally
        omitted here to keep the system prompt cacheable. Inject them via
        build_dynamic_context_block() into the messages[] dynamic context instead.
        """
        name = project.get("title", "Untitled")

        return (
            f"## Project: {name}\n"
            f"You are Voxy, working on **{name}**. This is your context right now — you know this project, you're inside it.\n\n"
            f"You can create cards, move them, update them, assign agents, write wiki pages. "
            f"When the user asks you to do something in this project, do it — don't explain that you can. "
            f"Stay focused here unless they explicitly ask about something else."
        )

    def build_card_chat_init(self, project: dict, card: dict) -> str:
        """Build the static Chat Init block for Card Chat mode.

        Dynamic details (description, status, checklist) are intentionally omitted here
        to keep the system prompt cacheable. Inject them via build_dynamic_context_block()
        into the messages[] dynamic context instead.
        """
        project_name = project.get("title", "Untitled")
        card_title = card.get("title", "Untitled")

        return (
            f"## Chat Init — Card: {card_title}\n"
            f"Mode: Card Chat\n"
            f"## Card: {card_title}\n"
            f"You are Voxy, focused on this card in **{project_name}**. This is your current task — you're already inside it.\n\n"
            f"You are here to work on this task — not to describe what you could do. "
            f"If the user says 'implement this', you start. If they say 'write the PRD', you write it. "
            f"Act with the confidence of someone who knows exactly what they're doing."
        )

    def build_dynamic_context_block(
        self,
        chat_level: str = "general",
        project: Optional[dict] = None,
        card: Optional[dict] = None,
        project_names: Optional[list] = None,
        memory_context: Optional[str] = None,
        active_workers_context: Optional[str] = None,
    ) -> str:
        """Build the DYNAMIC context block — injected into messages[], NOT the system prompt.

        Contains everything that changes call-to-call:
        - memory_context (per-query vector search results)
        - project description, tech stack, github, card counts, recent activity
        - card description, status, checklist details
        - project names list (for main/general chat)

        By keeping this OUT of the system prompt, the static base_prompt stays
        identical across calls → Anthropic KV cache hits.
        """
        parts: list[str] = []

        if chat_level == "general" or not project:
            # Main/general chat: inject project names
            if project_names:
                projects_list = "\n".join(f"- {name}" for name in project_names)
            else:
                projects_list = "  (no projects yet)"
            parts.append(f"## Your Projects\n{projects_list}")

        elif chat_level in ("project", "general") and project:
            # Project chat: inject full project state
            name = project.get("title", "Untitled")
            description = project.get("description") or "No description"
            tech_stack = project.get("tech_stack") or "Not specified"
            github_url = project.get("github_url") or "Not linked"
            all_cards = project.get("cards", [])
            cards = [c for c in all_cards if c.get("status") != "archived"]
            total = len(cards)
            done = sum(1 for c in cards if c.get("status") == "done")
            in_progress_cards = [c for c in cards if c.get("status") == "in_progress"]
            todo_cards = [c for c in cards if c.get("status") == "todo"]
            idea_cards = [c for c in cards if c.get("status") == "idea"]

            state_line = (
                f"State: {total} cards — {done} done, {len(in_progress_cards)} in progress, "
                f"{len(todo_cards)} todo, {len(idea_cards)} ideas"
            )

            # In-progress titles
            if in_progress_cards:
                ip_lines = "\n".join(f"  - {c.get('title', 'Untitled')}" for c in in_progress_cards)
                in_progress_block = f"In progress:\n{ip_lines}"
            else:
                in_progress_block = "In progress: (none)"

            # Todo titles
            if todo_cards:
                td_lines = "\n".join(f"  - {c.get('title', 'Untitled')}" for c in todo_cards)
                todo_block = f"Todo:\n{td_lines}"
            else:
                todo_block = "Todo: (none)"

            # Idea titles (top 5)
            if idea_cards:
                top_ideas = idea_cards[:5]
                id_lines = "\n".join(f"  - {c.get('title', 'Untitled')}" for c in top_ideas)
                ideas_block = f"Ideas (top {len(top_ideas)}):\n{id_lines}"
                if len(idea_cards) > 5:
                    ideas_block += f"\n  … and {len(idea_cards) - 5} more"
            else:
                ideas_block = "Ideas: (none)"

            parts.append(
                f"## Project Context: {name} (LIVE — this overrides any earlier data in the conversation)\n"
                f"Description: {description}\n"
                f"Tech Stack: {tech_stack}\n"
                f"GitHub: {github_url}\n\n"
                f"{state_line}\n\n"
                f"{in_progress_block}\n{todo_block}\n{ideas_block}"
            )

        if chat_level == "card" and card:
            # Card chat: inject full card details
            card_title = card.get("title", "Untitled")
            card_id = card.get("id", "")
            status = card.get("status", "idea")
            priority = card.get("priority", "medium")
            agent_type = card.get("agent_type") or "general"
            description = card.get("description") or "No description"
            assignee = card.get("assignee") or "Unassigned"

            checklist = card.get("checklist_items", [])
            total_items = len(checklist)
            completed_items = sum(1 for item in checklist if item.get("done") or item.get("completed"))

            id_part = f" ({card_id})" if card_id else ""
            parts.append(
                f"## Card Details: {card_title}\n"
                f"Card: {card_title}{id_part}\n"
                f"Status: {status} | Priority: {priority} | Agent: {agent_type} | Assignee: {assignee}\n"
                f"Description: {description}\n"
                f"Checklist: {completed_items}/{total_items} items done"
            )

        if memory_context:
            parts.append(f"## Relevant Memory\n{memory_context}")

        if active_workers_context:
            parts.append(f"## Background Workers Status\n{active_workers_context}")

        return "\n\n".join(parts)

    # ------------------------------------------------------------------
    # Context-isolated prompt builders (general / project / card)
    # ------------------------------------------------------------------

    def build_general_prompt(self, project_names: Optional[list] = None) -> str:
        """Build STATIC system prompt for General Chat — no project context.

        project_names is accepted for backward compat but no longer embedded here.
        Dynamic context (project names, memory) must be injected via build_dynamic_context_block().
        """
        soul = self.load_soul()
        user = self.load_user()
        identity = self.load_identity()
        agents = self.load_agents()

        sections = []

        # Chat Init FIRST — before personality files (static only)
        sections.append(self.build_general_chat_init())

        if identity:
            sections.append(identity)
        if soul:
            sections.append(soul)
        if agents:
            sections.append(agents)
        if user:
            sections.append(user)

        return "\n\n".join(sections)

    def build_project_prompt(self, project: dict) -> str:
        """Build STATIC system prompt for Project Chat — scoped to one project.

        Dynamic project details (description, recent cards) must be injected
        via build_dynamic_context_block().
        """
        soul = self.load_soul()
        user = self.load_user()
        agents = self.load_agents()

        sections = []

        # Chat Init FIRST — before personality files (static only)
        sections.append(self.build_project_chat_init(project))

        if soul:
            sections.append(soul)
        if agents:
            sections.append(agents)
        if user:
            sections.append(user)

        return "\n\n".join(sections)

    def build_card_prompt(self, project: dict, card: dict, agent_persona: Optional[dict] = None) -> str:
        """Build STATIC system prompt for Card Chat — scoped to a specific task.

        Dynamic card details (description, status, checklist) must be injected
        via build_dynamic_context_block().
        """
        soul = self.load_soul()

        sections = []

        # Chat Init FIRST — before agent persona and personality (static only)
        sections.append(self.build_card_chat_init(project, card))

        # Agent persona after Chat Init (if provided)
        if agent_persona and agent_persona.get("system_prompt"):
            sections.append(agent_persona["system_prompt"])

        if soul:
            sections.append(soul)

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

        preferred_language = ps.get("preferred_language", "both")

        style_parts = []
        if tone in TONE_MODIFIERS:
            style_parts.append(TONE_MODIFIERS[tone])
        if warmth in WARMTH_MODIFIERS:
            style_parts.append(WARMTH_MODIFIERS[warmth])
        if preferred_language in LANGUAGE_INSTRUCTIONS:
            style_parts.append(LANGUAGE_INSTRUCTIONS[preferred_language])
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

    def _build_tool_section(self, tool_names: set, chat_level: str = "general") -> str:
        """Build a tool instruction text block for a given set of tool names.

        Delegates to ToolPromptBuilder for consistent tool listing.
        Returns an empty string if no tools match.
        """
        try:
            from app.tools.prompt_builder import get_prompt_builder
            return get_prompt_builder().build_tool_list_text(tool_names, chat_level)
        except Exception:
            return ""

    def build_fast_prompt(self, memory_context: Optional[str] = None, chat_level: str = "general", project: Optional[dict] = None, card: Optional[dict] = None, agent_persona: Optional[dict] = None, project_names: Optional[list] = None, native_tools: bool = False) -> str:
        """Build the STATIC system prompt for the fast (dispatcher) layer.

        IMPORTANT — Cache stability contract:
        This method must return an IDENTICAL string for the same
        (chat_level, project.id, card.id, native_tools) tuple.
        Dynamic data (memory_context, project description, recent_cards,
        project_names) must NOT be embedded here — use build_dynamic_context_block()
        and inject the result into dynamic_parts / messages[] in the caller.

        The memory_context and project_names params are accepted for backward
        compatibility but are intentionally NOT embedded in the returned prompt.
        """
        voice_instructions = (
            "\n\n## Voice Instructions\n"
            "You speak naturally and concisely -- this is a voice conversation, not a text chat.\n"
            "Keep responses short (1-3 sentences for voice). Be helpful, direct, and friendly.\n"
            "You help manage projects, tasks, and ideas through conversation.\n"
            "Respond in the same language the user speaks (French or English).\n"
            "Your personality comes through in HOW you say things -- tone, word choice, energy.\n"
            "Be yourself. Not a corporate bot."
        )

        # Build context-appropriate base prompt (STATIC — no dynamic data)
        # "general" is now just the system-main project — use project prompt path
        if chat_level == "card" and card and project:
            base = self.build_card_prompt(project, card, agent_persona)
        elif project:
            base = self.build_project_prompt(project)
        else:
            # Fallback: no project context available (general/main)
            base = self.build_general_prompt()

        # Chat layers have ZERO tools — they converse and delegate only.
        # Architecture self-knowledge — loaded from ARCHITECTURE.md
        architecture = self.load_architecture()
        if architecture:
            voice_instructions += "\n\n" + architecture

        # Dispatcher rules — loaded from DISPATCHER.md, injected LAST (highest priority)
        dispatcher = self.load_dispatcher()
        if dispatcher:
            voice_instructions += "\n\n" + dispatcher

        # Delegate instructions — different for native tool_use vs CLI+MCP vs XML fallback
        if native_tools == "cli_mcp":
            voice_instructions += self._build_cli_mcp_delegate_instructions()
        elif native_tools:
            voice_instructions += self._build_native_delegate_instructions()
        else:
            voice_instructions += self._build_xml_delegate_instructions()

        # Log system prompt length for debugging delegate issues
        full_prompt = base + voice_instructions
        logger.info(f"[PersonalityService] Fast prompt built: {len(full_prompt)} chars, chat_level={chat_level}, native_tools={native_tools}")

        return full_prompt

    def _build_native_delegate_instructions(self) -> str:
        """Delegate instructions when native tool_use is available (Anthropic SDK)."""
        return (
            "\n\n## ⚡ Action Dispatch — delegate_action Tool\n"
            "When the user asks you to DO something (not just chat), you MUST call the "
            "delegate_action tool. This is the ONLY way to trigger worker execution.\n\n"
            "Call delegate_action with:\n"
            "- action: what to do (create_card, search_web, run_command, etc.)\n"
            "- summary: brief description of the task\n"
            "- model: haiku (simple CRUD), sonnet (research/balanced), opus (complex)\n"
            "- complexity: simple or complex\n\n"
            "WITHOUT calling delegate_action, NO worker will execute. "
            "Just saying \"I'll do it\" does NOTHING.\n"
            "When in doubt, call delegate_action.\n\n"
            "## 🚫 ENVIRONMENT CONSTRAINT\n"
            "You are running INSIDE Voxyflow's chat layer. You are NOT in a terminal. You are NOT Claude Code.\n"
            "You may notice you have access to CLI tools (Bash, Read, Write, WebSearch, etc.) — DO NOT USE THEM.\n"
            "Those are the underlying runtime's tools, NOT yours.\n\n"
            "YOUR tools are: natural language responses + delegate_action. NOTHING ELSE.\n\n"
            "If the user asks you to search the web → delegate_action(action='web_research', model='sonnet')\n"
            "If the user asks you to create a card → delegate_action(action='create_card', model='haiku')\n"
            "If the user asks you to run a command → delegate_action(action='run_command', model='sonnet')\n"
            "NEVER use Bash(), WebSearch(), Read(), Write(), or any CLI tool directly.\n"
            "NEVER say 'I don't have access to tools' — you DO, via delegate_action.\n"
            "NEVER say 'my knowledge cuts off at...' — delegate a web search instead."
        )

    def _build_cli_mcp_delegate_instructions(self) -> str:
        """Delegate instructions for CLI+MCP mode: inline tools via MCP + XML delegates."""
        return (
            "\n\n## ⚡ Your Tools — Inline MCP + Delegate\n"
            "You have TWO ways to act:\n\n"
            "### 1. Inline MCP Tools (use directly for fast operations)\n"
            "You can call these tools directly — they execute immediately:\n"
            "- `memory.search` / `knowledge.search` — search memory and knowledge base\n"
            "- `voxyflow.card.list` / `voxyflow.card.get` / `voxyflow.card.create` / "
            "`voxyflow.card.update` / `voxyflow.card.move` / `voxyflow.card.archive` — card operations\n"
            "- `voxyflow.workers.list` / `voxyflow.workers.get_result` — check worker status\n"
            "- `voxyflow.project.list` / `voxyflow.project.get` — project info\n"
            "- `voxyflow.wiki.list` / `voxyflow.wiki.get` — wiki pages\n\n"
            "Use these for quick lookups and simple CRUD. No delegation needed.\n\n"
            "### 2. <delegate> Blocks (for complex/long-running tasks)\n"
            "For tasks that need research, multi-step execution, web access, or code work — "
            "include a <delegate> block at the END of your response:\n"
            "<delegate>\n"
            '{"action": "...", "model": "haiku|sonnet|opus", "description": "..."}\n'
            "</delegate>\n\n"
            "Examples of when to delegate:\n"
            "- Web search/research → <delegate> with model=sonnet\n"
            "- Running commands or code → <delegate> with model=sonnet or opus\n"
            "- Complex multi-step tasks → <delegate> with model=opus\n\n"
            "WITHOUT the <delegate> block, complex tasks will NOT execute.\n"
            "When in doubt about complexity, DELEGATE.\n\n"
            "## 🚫 ENVIRONMENT CONSTRAINT\n"
            "You are running INSIDE Voxyflow's chat layer via Claude Code CLI.\n"
            "You may see CLI tools (Bash, Read, Write, WebSearch) — DO NOT USE THEM.\n"
            "Use ONLY: your MCP tools (listed above) + <delegate> blocks + natural language."
        )

    def _build_xml_delegate_instructions(self) -> str:
        """Delegate instructions for XML fallback (proxy mode)."""
        return (
            "\n\n## ⚠️ CRITICAL REMINDER — DO NOT FORGET ⚠️\n"
            "When the user asks you to DO something (not just chat), you MUST include a <delegate> block "
            "at the END of your response. This is the ONLY way to trigger worker execution.\n\n"
            "Format — include this EXACTLY:\n"
            "<delegate>\n"
            '{"action": "...", "model": "haiku|sonnet|opus", "description": "..."}\n'
            "</delegate>\n\n"
            "WITHOUT this block, NO worker will execute. Just saying \"I'll do it\" does NOTHING.\n"
            "If you said you would do something but didn't include <delegate>, YOU FAILED.\n"
            "When in doubt, INCLUDE the delegate block.\n\n"
            "## 🚫 ENVIRONMENT CONSTRAINT — READ THIS CAREFULLY\n"
            "You are running INSIDE Voxyflow's chat layer. You are NOT in a terminal. You are NOT Claude Code.\n"
            "You may notice you have access to CLI tools (Bash, Read, Write, WebSearch, etc.) — DO NOT USE THEM.\n"
            "Those are the underlying runtime's tools, NOT yours. Using them directly bypasses Voxyflow's "
            "worker architecture and breaks the user experience.\n\n"
            "YOUR tools are: natural language responses + <delegate> blocks. NOTHING ELSE.\n\n"
            "If the user asks you to search the web → <delegate> with model=sonnet, action=web_research.\n"
            "If the user asks you to create a file → <delegate> with model=haiku or sonnet.\n"
            "If the user asks you to run a command → <delegate> with model=sonnet or opus.\n"
            "NEVER use Bash(), WebSearch(), Read(), Write(), or any CLI tool directly.\n"
            "NEVER say 'I don't have access to tools' — you DO, via <delegate>.\n"
            "NEVER say 'my knowledge cuts off at...' — delegate a web search instead."
        )

    def build_deep_prompt(self, memory_context: Optional[str] = None, chat_level: str = "general", project: Optional[dict] = None, card: Optional[dict] = None, project_names: Optional[list] = None, has_delegation: bool = False, is_chat_responder: bool = False, native_tools: bool = False) -> str:
        """Build the STATIC system prompt for the deep layer.

        IMPORTANT — Cache stability contract:
        Same as build_fast_prompt — dynamic data (memory_context, project description,
        recent_cards, project_names) must NOT be embedded here.
        Use build_dynamic_context_block() and inject into dynamic_parts / messages[].
        Params memory_context and project_names are kept for backward compatibility
        but are intentionally NOT embedded in the returned prompt.
        """
        # Build context-appropriate base (STATIC — no dynamic data)
        # "general" is now the system-main project
        if chat_level == "card" and card and project:
            base = self.build_card_prompt(project, card)
        elif project:
            base = self.build_project_prompt(project)
        else:
            base = self.build_general_prompt()

        mode_label = f"Project Chat: {project.get('title', 'Main')}" if project else "Main Chat"

        # --- Chat responder mode: dispatcher pattern (same as Fast layer) ---
        if is_chat_responder:
            voice_instructions = (
                f"\n\n## Layer Init — Deep (Primary Chat Responder)\n"
                f"Context: {mode_label}\n"
                "You are the DEEP layer responding directly to the user in chat.\n"
                "You are Opus — thoughtful, precise, and thorough.\n"
                "Respond conversationally with depth and nuance.\n\n"
                "Keep responses focused but don't shy away from detail when the user needs it.\n"
                "Match the user's language and energy.\n"
            )

            # Chat layers have ZERO tools — they converse and delegate only.
            # Architecture self-knowledge
            architecture = self.load_architecture()
            if architecture:
                voice_instructions += "\n\n" + architecture

            # Dispatcher constraint + delegate instructions
            voice_instructions += (
                "\n\n## ⚡ ABSOLUTE RULE — You Are a Dispatcher, Not an Executor\n"
                "You are the DEEP layer. Your job is to SPEAK and READ. Period.\n\n"
                "YOU CANNOT:\n"
                "- Create, update, delete, or move any data\n"
                "- Execute commands or write files\n"
                "- Use any tool that modifies state\n\n"
                "When the user asks you to DO something, you DISPATCH — always.\n"
                "You NEVER say 'I'll do that' and then do it yourself.\n"
                "You NEVER execute an action directly, even if you think you can.\n"
                "If you're about to use a write/execute tool — STOP. Delegate instead.\n\n"
                "EXCEPTION: If the user is just chatting or asking a question — respond normally, no delegation."
            )

            # Delegate format instructions — native tool_use vs CLI+MCP vs XML fallback
            if native_tools == "cli_mcp":
                voice_instructions += self._build_cli_mcp_delegate_instructions()
            elif native_tools:
                voice_instructions += self._build_native_delegate_instructions()
            else:
                voice_instructions += self._build_xml_delegate_instructions()

            full_prompt = base + voice_instructions
            logger.info(f"[PersonalityService] Deep chat prompt built: {len(full_prompt)} chars, chat_level={chat_level}, native_tools={native_tools}")
            return full_prompt

        # Legacy supervisor/background-executor mode removed — fast/deep are the
        # same dispatcher layer at different model tiers.  If we reach here it
        # means is_chat_responder=False was passed; return the base prompt as-is.
        return base

    # ------------------------------------------------------------------
    # Worker prompts — model-routed (haiku/sonnet/opus)
    # ------------------------------------------------------------------

    def build_worker_prompt(
        self,
        model: str = "sonnet",
        chat_level: str = "general",
        project: Optional[dict] = None,
        card: Optional[dict] = None,
    ) -> str:
        """Build system prompt for background worker execution."""
        if model == "haiku":
            return self._build_haiku_worker_prompt(chat_level, project, card)
        elif model == "opus":
            return self._build_opus_worker_prompt(chat_level, project, card)
        else:
            return self._build_sonnet_worker_prompt(chat_level, project, card)

    def _build_worker_context_section(self, chat_level: str, project: Optional[dict], card: Optional[dict]) -> str:
        """Build context section for worker prompts with full IDs and details."""
        parts = []
        if chat_level == "card" and card and project:
            parts.append(f"Project: {project.get('title', '?')} (project_id: {project.get('id', '?')})")
            if project.get("local_path"):
                parts.append(f"Project workspace: {project['local_path']} (CWD is set here)")
            parts.append(f"Card: {card.get('title', '?')} (card_id: {card.get('id', '?')})")
            parts.append(f"Card status: {card.get('status', '?')} | Priority: {card.get('priority', '?')}")
            if card.get("description"):
                parts.append(f"Card description: {card['description'][:300]}")
            parts.append(
                f"\nYou are operating on this specific card. "
                f"Use card_id={card.get('id', '?')} for any card operations. "
                f"Use project_id={project.get('id', '?')} for any project operations. "
                f"Do NOT ask the user which card — you already know."
            )
            return "\n".join(parts)
        elif project:
            parts.append(f"Project: {project.get('title', '?')} (project_id: {project.get('id', '?')})")
            if project.get("local_path"):
                parts.append(f"Project workspace: {project['local_path']} (CWD is set here)")
            if project.get("description"):
                parts.append(f"Description: {project['description'][:200]}")
            parts.append(
                f"\nYou are operating in this project's context. "
                f"Use project_id={project.get('id', '?')} for any project/card operations. "
                f"Do NOT ask the user which project — you already know."
            )
            return "\n".join(parts)
        from app.config import VOXYFLOW_WORKSPACE_DIR
        ws_dir = str(VOXYFLOW_WORKSPACE_DIR)
        return (
            "Context: Main project (default workspace, project_id=system-main)\n"
            f"Workspace: {ws_dir}\n"
            f"CWD is set to {ws_dir} — use relative paths for workspace files.\n"
            "Voxyflow app codebase: ~/voxyflow/ (do NOT write project files here)."
        )

    def _build_haiku_worker_prompt(self, chat_level: str, project: Optional[dict], card: Optional[dict]) -> str:
        """Haiku: Simple CRUD only. Fast, cheap, no ambiguity."""
        from app.tools.registry import TOOLS_VOXYFLOW_CRUD
        tool_list = self._build_tool_section(TOOLS_VOXYFLOW_CRUD, chat_level)
        context = self._build_worker_context_section(chat_level, project, card)
        worker_rules = self.load_worker()

        return (
            f"{worker_rules}\n\n"
            f"## Active Role: Haiku (CRUD Executor)\n\n"
            f"## Available Tools\n{tool_list}\n\n"
            f"## Context\n{context}"
        )

    def _build_sonnet_worker_prompt(self, chat_level: str, project: Optional[dict], card: Optional[dict]) -> str:
        """Sonnet: Research, web, file analysis. Balanced speed/capability."""
        from app.tools.registry import TOOLS_FULL
        tool_list = self._build_tool_section(TOOLS_FULL, chat_level)
        context = self._build_worker_context_section(chat_level, project, card)
        worker_rules = self.load_worker()

        return (
            f"{worker_rules}\n\n"
            f"## Active Role: Sonnet (Research & Analysis)\n\n"
            f"## Available Tools\n{tool_list}\n\n"
            f"## Context\n{context}"
        )

    def _build_opus_worker_prompt(self, chat_level: str, project: Optional[dict], card: Optional[dict]) -> str:
        """Opus: Complex multi-step, architecture, code analysis."""
        from app.tools.registry import TOOLS_FULL
        tool_list = self._build_tool_section(TOOLS_FULL, chat_level)
        context = self._build_worker_context_section(chat_level, project, card)
        worker_rules = self.load_worker()

        return (
            f"{worker_rules}\n\n"
            f"## Active Role: Opus (Complex Execution)\n\n"
            f"## Available Tools\n{tool_list}\n\n"
            f"## Context\n{context}"
        )

    def build_analyzer_prompt(self, memory_context: Optional[str] = None, chat_level: str = "general", project_names: Optional[list] = None, delegation: Optional[dict] = None) -> str:
        analyzer_rules = self.load_analyzer()

        context_note = ""
        if chat_level == "general":
            projs = ", ".join(project_names or []) or "none"
            context_note = (
                f"\n\nCurrent context: MAIN PROJECT (default workspace, project_id=system-main).\n"
                f"User's projects: {projs}\n"
                "In Main project, suggest CARDS for the Main Board (reminders/quick thoughts).\n"
                "If the user mentions something that belongs in another project, suggest a CARD with the project name.\n"
                "If the project doesn't exist yet, suggest creating it.\n"
            )
        elif chat_level == "project":
            context_note = "\n\nCurrent context: PROJECT CHAT. Suggest CARDS for this project.\n"

        mode_label = "Main Project" if chat_level == "general" else "Project Chat"

        # Delegation mode: Analyzer received a simple CRUD action to suggest-then-execute
        if delegation:
            base = (
                f"{analyzer_rules}\n\n"
                f"## Active Mode: Delegated Action\n"
                f"Context: {mode_label}\n"
                "The Fast layer delegated a simple action to you.\n\n"
                f"## Delegated Intent\n"
                f"Intent: {delegation.get('intent', 'unknown')}\n"
                f"Summary: {delegation.get('summary', '')}\n"
            )
            # Add available CRUD tools
            from app.tools.registry import TOOLS_VOXYFLOW_CRUD
            tool_list_text = self._build_tool_section(TOOLS_VOXYFLOW_CRUD, chat_level)
            if tool_list_text:
                base += f"\n## Available CRUD Tools\n{tool_list_text}\n"
            base += context_note
            return self.build_system_prompt(base_prompt=base, include_user=True, include_memory_context=memory_context)

        # Standard mode: Analyzer runs in parallel to detect actionable items
        base = (
            f"{analyzer_rules}\n\n"
            f"## Active Mode: Action Item Extraction\n"
            f"Context: {mode_label}\n"
            + context_note
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
