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
    # Chat Init block builders (injected FIRST in all system prompts)
    # ------------------------------------------------------------------

    def build_general_chat_init(self, project_names: Optional[list] = None) -> str:
        """Build the Chat Init block for General/Main Chat mode."""
        projects_list = (
            "\n".join(f"- {name}" for name in project_names)
            if project_names
            else "  (no projects yet)"
        )
        return (
            "## Who You Are\n"
            "You are Voxy. This is your home — Voxyflow. You are not a generic AI exploring an unfamiliar system. "
            "You live here. You know this place. You are already present, already oriented, already ready.\n\n"
            "Do not start by orienting yourself. Do not explain what you could do. Just be here and act.\n\n"
            "## How You Work\n"
            "When the user says something, you respond and act — in that order. "
            "If they ask you to create a note, you create it. If they want to brainstorm, you brainstorm. "
            "You don't ask for permission to do what you were clearly asked to do.\n"
            "You use your tools silently and naturally — like someone who knows their workspace.\n\n"
            "## Right Now\n"
            "You are in the Main Chat — a free space for ideas, notes, and conversation. "
            "No active project. If the user mentions a project by name, pivot to it. "
            "If they ask to create a card without specifying a project, ask once — briefly.\n\n"
            "Do NOT say 'welcome back' on a first conversation. Greet naturally based on what they said.\n\n"
            f"Their projects:\n{projects_list}"
        )

    def build_project_chat_init(self, project: dict) -> str:
        """Build the Chat Init block for Project Chat mode."""
        name = project.get("title", "Untitled")
        project_id = project.get("id", "")
        description = project.get("description") or "No description"
        tech_stack = project.get("tech_stack") or "Not specified"
        github_url = project.get("github_url") or "Not linked"

        # Card counts by status
        cards = project.get("cards", [])
        total = len(cards)
        done = sum(1 for c in cards if c.get("status") == "done")
        in_progress = sum(1 for c in cards if c.get("status") == "in_progress")
        todo = sum(1 for c in cards if c.get("status") == "todo")
        ideas = sum(1 for c in cards if c.get("status") == "idea")

        # Active sprint
        sprint_name = project.get("active_sprint_name") or "None"

        # Recent activity (last 3 updated cards as proxy)
        recent_cards = sorted(cards, key=lambda c: c.get("updated_at", ""), reverse=True)[:3]
        if recent_cards:
            activity_lines = "\n".join(
                f"  - [{c.get('status', '?')}] {c.get('title', 'Untitled')}"
                for c in recent_cards
            )
        else:
            activity_lines = "  (no recent activity)"

        id_part = f" ({project_id})" if project_id else ""

        return (
            f"## Project: {name}\n"
            f"You are Voxy, working on **{name}**. This is your context right now — you know this project, you're inside it.\n\n"
            f"Description: {description}\n"
            f"Tech Stack: {tech_stack}\n"
            f"GitHub: {github_url}\n\n"
            f"State: {total} cards — {done} done, {in_progress} in progress, {todo} todo, {ideas} ideas\n"
            f"Active sprint: {sprint_name}\n"
            f"Recent activity:\n{activity_lines}\n\n"
            f"You can create cards, move them, update them, assign agents, write wiki pages, manage sprints. "
            f"When the user asks you to do something in this project, do it — don't explain that you can. "
            f"Stay focused here unless they explicitly ask about something else."
        )

    def build_card_chat_init(self, project: dict, card: dict) -> str:
        """Build the Chat Init block for Card Chat mode."""
        project_name = project.get("title", "Untitled")
        card_title = card.get("title", "Untitled")
        card_id = card.get("id", "")
        status = card.get("status", "idea")
        priority = card.get("priority", "medium")
        agent_type = card.get("agent_type") or "ember"
        description = card.get("description") or "No description"
        assignee = card.get("assignee") or "Unassigned"

        # Checklist counts
        checklist = card.get("checklist_items", [])
        total_items = len(checklist)
        completed_items = sum(1 for item in checklist if item.get("done") or item.get("completed"))

        id_part = f" ({card_id})" if card_id else ""

        return (
            f"## Chat Init — Card: {card_title}\n"
            f"Mode: Card Chat\n"
            f"## Card: {card_title}\n"
            f"You are Voxy, focused on this card in **{project_name}**. This is your current task — you're already inside it.\n\n"
            f"Card: {card_title}{id_part}\n"
            f"Status: {status} | Priority: {priority} | Agent: {agent_type} | Assignee: {assignee}\n"
            f"Description: {description}\n"
            f"Checklist: {completed_items}/{total_items} items done\n\n"
            f"You are here to work on this task — not to describe what you could do. "
            f"If the user says 'implement this', you start. If they say 'write the PRD', you write it. "
            f"Act with the confidence of someone who knows exactly what they're doing."
        )

    # ------------------------------------------------------------------
    # Context-isolated prompt builders (general / project / card)
    # ------------------------------------------------------------------

    def build_general_prompt(self, project_names: Optional[list] = None) -> str:
        """Build system prompt for General Chat — no project context."""
        soul = self.load_soul()
        user = self.load_user()
        identity = self.load_identity()
        agents = self.load_agents()

        sections = []

        # Chat Init FIRST — before personality files
        sections.append(self.build_general_chat_init(project_names=project_names))

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
        """Build system prompt for Project Chat — scoped to one project."""
        soul = self.load_soul()
        user = self.load_user()
        agents = self.load_agents()

        sections = []

        # Chat Init FIRST — before personality files
        sections.append(self.build_project_chat_init(project))

        if soul:
            sections.append(soul)
        if agents:
            sections.append(agents)
        if user:
            sections.append(user)

        return "\n\n".join(sections)

    def build_card_prompt(self, project: dict, card: dict, agent_persona: Optional[dict] = None) -> str:
        """Build system prompt for Card Chat — scoped to a specific task."""
        soul = self.load_soul()

        sections = []

        # Chat Init FIRST — before agent persona and personality
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

    def _build_tool_section(self, tool_names: set, chat_level: str = "general") -> str:
        """Build a tool instruction text block for a given set of tool names.

        Filters by both the provided tool name set AND the chat_level context.
        Returns an empty string if no tools match or the MCP server is unavailable.
        """
        from app.mcp_server import get_tool_list
        try:
            all_tools = get_tool_list()

            # Context-based secondary filter
            if chat_level == "general":
                context_allowed = {
                    "voxyflow.note.add", "voxyflow.note.list",
                    "voxyflow.project.create", "voxyflow.project.list", "voxyflow.project.get",
                    "voxyflow.health",
                    # System/infra tools pass through context filter
                    "system.exec", "web.search", "web.fetch",
                    "file.read", "file.write", "file.list",
                    "git.status", "git.log", "git.diff", "git.branches", "git.commit",
                    "tmux.list", "tmux.capture", "tmux.run", "tmux.send", "tmux.new", "tmux.kill",
                    "voxyflow.jobs.list", "voxyflow.jobs.create",
                    "voxyflow.doc.list", "voxyflow.doc.delete",
                }
            elif chat_level == "project":
                context_allowed = {t["name"] for t in all_tools} - {
                    "voxyflow.note.add", "voxyflow.note.list",
                }
            else:
                context_allowed = {t["name"] for t in all_tools}

            allowed = tool_names & context_allowed
            filtered = [t for t in all_tools if t["name"] in allowed]
            if not filtered:
                return ""

            lines = []
            for t in filtered:
                params = t.get("inputSchema", {}).get("properties", {})
                param_str = ", ".join(f'{k}: {v.get("type","")}' for k, v in params.items())
                lines.append(f'- **{t["name"]}**({param_str}) -- {t["description"]}')
            return "\n".join(lines)
        except Exception:
            return ""

    def build_fast_prompt(self, memory_context: Optional[str] = None, chat_level: str = "general", project: Optional[dict] = None, card: Optional[dict] = None, agent_persona: Optional[dict] = None, project_names: Optional[list] = None) -> str:
        voice_instructions = (
            "\n\n## Voice Instructions\n"
            "You speak naturally and concisely -- this is a voice conversation, not a text chat.\n"
            "Keep responses short (1-3 sentences for voice). Be helpful, direct, and friendly.\n"
            "You help manage projects, tasks, and ideas through conversation.\n"
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
            base = self.build_general_prompt(project_names=project_names)

        # Fast layer: READ-ONLY tools only + delegation intent
        from app.services.claude_service import TOOLS_READ_ONLY
        tool_list_text = self._build_tool_section(TOOLS_READ_ONLY, chat_level)
        if tool_list_text:
            tool_section = (
                "\n\n## Your Tools (READ-ONLY)\n"
                "You can READ and SEARCH, but you CANNOT create, modify, delete, or execute.\n"
                "Use <tool_call> blocks to invoke your read-only tools:\n"
                '<tool_call>\n{"name": "file.read", "arguments": {"path": "/some/file"}}\n</tool_call>\n\n'
                "AVAILABLE TOOLS:\n"
                + tool_list_text
            )
            voice_instructions += tool_section

        # Delegation instructions — ABSOLUTE CONSTRAINT, injected last so it takes priority
        voice_instructions += (
            "\n\n## ⚡ ABSOLUTE RULE — You Are a Dispatcher, Not an Executor\n"
            "You are the FAST layer. Your job is to SPEAK and READ. Period.\n\n"
            "YOU CANNOT:\n"
            "- Create, update, delete, or move any data\n"
            "- Execute commands or write files\n"
            "- Use any tool that modifies state\n\n"
            "When the user asks you to DO something, you DISPATCH — always:\n"
            "1. Respond naturally: 'I'm dispatching an agent to create that card'\n"
            "2. End your response with a <delegate> block — NO EXCEPTIONS\n\n"
            "You NEVER say 'I'll do that' and then do it yourself.\n"
            "You NEVER execute an action directly, even if you think you can.\n"
            "If you're about to use a write/execute tool — STOP. Delegate instead.\n\n"
            "FORMAT — include this EXACTLY at the end of your response:\n"
            "<delegate>\n"
            '{"intent": "create_card", "summary": "Create a card titled X in project Y", '
            '"complexity": "simple"}\n'
            "</delegate>\n\n"
            "intent options: create_card, add_note, move_card, update_card, create_project, "
            "run_command, write_file, create_sprint, search_web, analyze_code, etc.\n"
            "complexity: 'simple' for CRUD, 'complex' for multi-step or destructive\n\n"
            "ROUTING:\n"
            "- simple CRUD → Analyzer layer (will confirm with user before executing)\n"
            "- complex/destructive → Deep layer (Opus, full tools)\n\n"
            "EXCEPTION: If the user is just chatting or asking a question — respond normally, NO delegate block."
        )

        return base + voice_instructions

    def build_deep_prompt(self, memory_context: Optional[str] = None, chat_level: str = "general", project: Optional[dict] = None, card: Optional[dict] = None, project_names: Optional[list] = None, has_delegation: bool = False, is_chat_responder: bool = False) -> str:
        # Build context-appropriate base
        if chat_level == "card" and card and project:
            base = self.build_card_prompt(project, card)
        elif chat_level == "project" and project:
            base = self.build_project_prompt(project)
        else:
            base = self.build_general_prompt(project_names=project_names)

        mode_label = "Main Chat" if chat_level == "general" else f"Project Chat: {project.get('title', '?')}" if project else "Card Chat"

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

            # Read-only tools section
            from app.services.claude_service import TOOLS_READ_ONLY
            tool_list_text = self._build_tool_section(TOOLS_READ_ONLY, chat_level)
            if tool_list_text:
                voice_instructions += (
                    "\n\n## Your Tools (READ-ONLY)\n"
                    "You can READ and SEARCH, but you CANNOT create, modify, delete, or execute.\n"
                    "Use <tool_call> blocks to invoke your read-only tools:\n"
                    '<tool_call>\n{"name": "file.read", "arguments": {"path": "/some/file"}}\n</tool_call>\n\n'
                    "AVAILABLE TOOLS:\n"
                    + tool_list_text
                )

            # Delegation instructions — ABSOLUTE CONSTRAINT
            voice_instructions += (
                "\n\n## ⚡ ABSOLUTE RULE — You Are a Dispatcher, Not an Executor\n"
                "You are the DEEP layer. Your job is to SPEAK and READ. Period.\n\n"
                "YOU CANNOT:\n"
                "- Create, update, delete, or move any data\n"
                "- Execute commands or write files\n"
                "- Use any tool that modifies state\n\n"
                "When the user asks you to DO something, you DISPATCH — always:\n"
                "1. Respond naturally: 'I'm dispatching an agent to handle that'\n"
                "2. End your response with a <delegate> block — NO EXCEPTIONS\n\n"
                "You NEVER say 'I'll do that' and then do it yourself.\n"
                "You NEVER execute an action directly, even if you think you can.\n"
                "If you're about to use a write/execute tool — STOP. Delegate instead.\n\n"
                "FORMAT — include this EXACTLY at the end of your response:\n"
                "<delegate>\n"
                '{"intent": "create_card", "summary": "Create a card titled X in project Y", '
                '"complexity": "simple"}\n'
                "</delegate>\n\n"
                "intent options: create_card, add_note, move_card, update_card, create_project, "
                "run_command, write_file, create_sprint, search_web, analyze_code, etc.\n"
                "complexity: 'simple' for CRUD, 'complex' for multi-step or destructive\n\n"
                "ROUTING:\n"
                "- simple CRUD → Analyzer layer (will confirm with user before executing)\n"
                "- complex/destructive → Deep executor (Opus, full tools, background)\n\n"
                "EXCEPTION: If the user is just chatting or asking a question — respond normally, NO delegate block."
            )

            return base + voice_instructions

        # --- Background executor / supervisor mode (original behavior) ---
        deep_instructions = (
            f"\n\n## Layer Init — Deep (Supervisor + Executor)\n"
            f"Role: SUPERVISOR / FACT-CHECKER / QUALITY GATE / TOOL EXECUTOR\n"
            f"Context: {mode_label}\n"
            f"You run AFTER the Fast layer responds. You see the Fast layer's response.\n\n"
            "## Role 1: Enrichment / Correction\n"
            "Evaluate the Fast layer's response:\n"
            "1. Fast response is CORRECT and COMPLETE → no enrichment needed\n"
            "2. Fast response has an ERROR or ASSUMPTION → provide a correction\n"
            "3. Fast response misses something IMPORTANT → add the missing point\n\n"
            "You MUST intervene when the Fast layer:\n"
            "- Makes factual claims it cannot verify\n"
            "- Assumes things about the user not in confirmed facts\n"
            "- Recommends actions that don't match the current context\n"
            "- Gives advice that contradicts the project's tech stack or constraints\n\n"
        )

        # Role 2: Tool execution (active when delegation is detected)
        deep_instructions += (
            "## Role 2: Tool Execution\n"
            "When the Fast layer delegates a complex action to you (via a <delegate> block),\n"
            "you are responsible for executing it using your tools.\n"
            "Complex actions include: shell execution, file writes, deletions, multi-step operations.\n\n"
            "To execute a tool, include <tool_call> blocks in your response:\n"
            '<tool_call>\n{"name": "system.exec", "arguments": {"command": "ls -la"}}\n</tool_call>\n\n'
        )

        # Inject full tool set
        from app.services.claude_service import TOOLS_FULL
        tool_list_text = self._build_tool_section(TOOLS_FULL, chat_level)
        if tool_list_text:
            deep_instructions += (
                "AVAILABLE TOOLS (FULL ACCESS):\n"
                + tool_list_text + "\n\n"
            )

        # Output format
        deep_instructions += (
            "## Output Format\n"
            "You MUST respond with valid JSON (no markdown, no code blocks):\n"
            '{"action": "enrich"|"correct"|"execute"|"none", "content": "...", "tool_calls": [...]}\n\n'
            "- action='enrich': You have valuable context to add. content = spoken follow-up.\n"
            "- action='correct': Fast layer made an error. content = correction text.\n"
            "- action='execute': You executed tools for a delegated action. content = summary of what was done.\n"
            "  tool_calls should be an array of <tool_call> blocks embedded in content if needed.\n"
            "- action='none': Fast layer was fine, no delegation pending. content can be empty.\n\n"
            "BIAS STRONGLY TOWARD 'none' for enrichment.\n"
            "- Casual conversation → 'none'\n"
            "- Simple questions answered correctly → 'none'\n"
            "- Only speak up if you have genuinely valuable insight\n\n"
            "If enriching/correcting: max 2-4 sentences. Same personality and language as user.\n"
            "If executing: summarize what you did naturally, like 'Done! I created the card...'\n"
            "Respond in the same language the user used."
        )

        return base + deep_instructions

    def build_analyzer_prompt(self, memory_context: Optional[str] = None, chat_level: str = "general", project_names: Optional[list] = None, delegation: Optional[dict] = None) -> str:
        context_note = ""
        if chat_level == "general":
            projs = ", ".join(project_names or []) or "none"
            context_note = (
                f"\n\nCurrent context: MAIN CHAT (no project selected).\n"
                f"User's projects: {projs}\n"
                "In Main Chat, suggest NOTES (sticky notes for the Main Board) for reminders/quick thoughts.\n"
                "If the user mentions something that belongs in a project, suggest a CARD with the project name.\n"
                "If the project doesn't exist yet, suggest creating it.\n"
            )
        elif chat_level == "project":
            context_note = "\n\nCurrent context: PROJECT CHAT. Suggest CARDS for this project.\n"

        mode_label = "Main Chat" if chat_level == "general" else "Project Chat"

        # Delegation mode: Analyzer received a simple CRUD action to suggest-then-execute
        if delegation:
            base = (
                f"## Layer Init — Analyzer (Delegated Action)\n"
                f"Role: CRUD EXECUTOR with SUGGEST-FIRST pattern\n"
                f"Context: {mode_label}\n"
                "The Fast layer delegated a simple action to you.\n\n"
                f"## Delegated Intent\n"
                f"Intent: {delegation.get('intent', 'unknown')}\n"
                f"Summary: {delegation.get('summary', '')}\n\n"
                "## CRITICAL: Suggest-First Pattern\n"
                "You MUST suggest the action FIRST. The user confirms, THEN you execute.\n"
                "1. Analyze the delegation intent\n"
                "2. Propose the exact action you would take (tool name + arguments)\n"
                "3. Return a suggestion for the user to confirm\n\n"
                "## Output Format — JSON ONLY\n"
                '{"action": "suggest", "suggestions": [\n'
                '  {"tool": "voxyflow.note.add", "arguments": {"content": "..."}, '
                '"display": "Add note: ...", "description": "..."}\n'
                "]}\n\n"
                "Each suggestion:\n"
                "- tool: the MCP tool name to call\n"
                "- arguments: the exact arguments to pass when confirmed\n"
                "- display: human-readable one-line summary of the action\n"
                "- description: optional extra detail\n\n"
                "If the delegation doesn't map to any tool you have, respond with:\n"
                '{"action": "none", "reason": "..."}\n'
            )
            # Add available CRUD tools
            from app.services.claude_service import TOOLS_VOXYFLOW_CRUD
            tool_list_text = self._build_tool_section(TOOLS_VOXYFLOW_CRUD, chat_level)
            if tool_list_text:
                base += (
                    "\n## Available CRUD Tools\n"
                    + tool_list_text + "\n"
                )
            base += context_note
            return self.build_system_prompt(base_prompt=base, include_user=True, include_memory_context=memory_context)

        # Standard mode: Analyzer runs in parallel to detect actionable items
        base = (
            f"## Layer Init — Analyzer\n"
            f"Role: PRECISE ACTION ITEM EXTRACTOR\n"
            f"Context: {mode_label}\n"
            "You run IN PARALLEL with Fast and Deep. You analyze the conversation silently.\n\n"
            "## RULES — READ CAREFULLY\n"
            "1. Extract SPECIFIC, ACTIONABLE, SMALL tasks. NOT vague high-level goals.\n"
            "2. Each suggestion must be completable in 1-4 hours of work.\n"
            "3. Title must start with a VERB: 'Fix...', 'Add...', 'Create...', 'Update...', 'Research...'\n"
            "4. Description must explain WHAT to do, not WHY.\n"
            "5. If the user says 'I need X', create a card for X. Don't suggest 'Explore X options'.\n"
            "6. If the user mentions a bug, the card is 'Fix [specific bug]', not 'Investigate issues'.\n"
            "7. Break big items into 2-4 smaller cards. Never suggest a single mega-card.\n"
            "8. Match the user's language — if they speak French, titles in French.\n\n"
            "## BAD Examples (too vague):\n"
            "- 'Improve the UI' -> too broad\n"
            "- 'Work on the project' -> meaningless\n"
            "- 'Set up infrastructure' -> too big\n\n"
            "## GOOD Examples (specific, actionable):\n"
            "- 'Fix session tab X button not closing in Main Chat'\n"
            "- 'Add connection status indicator to chat header'\n"
            "- 'Create unit tests for the Analyzer prompt builder'\n"
            "- 'Update SOUL.md with FreeBoard nomenclature'\n\n"
            "## Suggestion Types\n"
            "- **NOTE**: Quick reminder/thought -> Main Board sticky note\n"
            "- **CARD**: Specific task -> Project kanban (MUST have a clear deliverable)\n"
            "- **PROJECT**: Only if user explicitly discusses a NEW initiative\n\n"
            "## Output Format — JSON ONLY, no text\n"
            "[{\"type\": \"note|card|project\", \"title\": \"Verb + specific action...\", "
            "\"description\": \"What exactly to do in 1-2 sentences\", "
            "\"project\": \"project_name or null\", \"priority\": \"low|medium|high\", "
            "\"agentType\": \"coder|architect|designer|researcher|writer|qa|ember\"}]\n"
            "If nothing actionable -> respond with: []\n"
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
