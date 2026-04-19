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
VOXYFLOW_DIR = Path(os.environ.get("VOXYFLOW_DIR", os.path.expanduser("~/.voxyflow")))
PERSONALITY_DIR = VOXYFLOW_DIR / "personality"

# Personality files — isolated to Voxyflow
SOUL_FILE = PERSONALITY_DIR / "SOUL.md"
USER_FILE = PERSONALITY_DIR / "USER.md"
IDENTITY_FILE = PERSONALITY_DIR / "IDENTITY.md"
AGENTS_FILE = PERSONALITY_DIR / "AGENTS.md"
DISPATCHER_FILE = PERSONALITY_DIR / "DISPATCHER.md"
WORKER_FILE = PERSONALITY_DIR / "WORKER.md"
ARCHITECTURE_FILE = PERSONALITY_DIR / "ARCHITECTURE.md"
PROACTIVE_FILE = PERSONALITY_DIR / "PROACTIVE.md"

# Settings file lives in the data dir (outside repo)
from app.config import SETTINGS_FILE  # ~/.voxyflow/settings.json

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
    "auto":  "Respond in the same language the user writes in. Detect it from their message.",
    "both":  "Respond in the same language the user writes in. Detect it from their message.",  # legacy alias
    "en":    "Always respond in English, regardless of the user's language.",
    "fr":    "Réponds toujours en français, peu importe la langue de l'utilisateur.",
    "es":    "Responde siempre en español, independientemente del idioma del usuario.",
    "de":    "Antworte immer auf Deutsch, unabhängig von der Sprache des Benutzers.",
    "it":    "Rispondi sempre in italiano, indipendentemente dalla lingua dell'utente.",
    "pt":    "Responde sempre em português, independentemente da língua do utilizador.",
    "nl":    "Antwoord altijd in het Nederlands, ongeacht de taal van de gebruiker.",
    "ja":    "ユーザーの言語に関わらず、常に日本語で応答してください。",
    "zh":    "无论用户使用何种语言，请始终用中文回复。",
    "ko":    "사용자의 언어에 관계없이 항상 한국어로 응답하세요.",
    "ar":    "أجب دائماً باللغة العربية، بغض النظر عن لغة المستخدم.",
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

    def get_bot_name(self) -> str:
        """Return configured assistant name from settings (personality.bot_name or assistant_name)."""
        settings = self._load_settings()
        name = settings.get("personality", {}).get("bot_name", "").strip()
        if not name:
            name = settings.get("assistant_name", "").strip()
        return name or "Voxy"

    def get_user_name(self) -> str:
        """Return configured user name from settings."""
        settings = self._load_settings()
        return settings.get("user_name", "").strip() or "User"

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
        content = self._read_if_changed(DISPATCHER_FILE)
        if content:
            content = content.replace("{VOXYFLOW_DIR}", str(VOXYFLOW_DIR))
        return content

    def load_worker(self) -> str:
        return self._read_if_changed(WORKER_FILE)

    def load_architecture(self) -> str:
        return self._read_if_changed(ARCHITECTURE_FILE)

    def load_proactive(self) -> str:
        return self._read_if_changed(PROACTIVE_FILE)

    # ------------------------------------------------------------------
    # Chat Init block builders (injected FIRST in all system prompts)
    # ------------------------------------------------------------------

    def build_general_chat_init(self, project_names: Optional[list] = None) -> str:
        """Build the Chat Init block for Home project chat (system-main).

        This is now just a project chat for the system "Home" project.
        Kept as a separate method for backward compatibility.
        The static base omits project_names — inject dynamically via build_dynamic_context_block().
        """
        bot_name = self.get_bot_name()
        return (
            f"## Who You Are\n"
            f"You are {bot_name}. This is your home — Voxyflow. You are not a generic AI exploring an unfamiliar system. "
            f"You live here. You know this place. You are already present, already oriented, already ready.\n\n"
            "Do not start by orienting yourself. Do not explain what you could do. Just be here and act.\n\n"
            "## How You Work\n"
            "When the user says something, you respond and act — in that order. "
            "If they ask you to create a card, you create it. If they want to brainstorm, you brainstorm. "
            "You don't ask for permission to do what you were clearly asked to do.\n"
            "You use your tools silently and naturally — like someone who knows their workspace.\n\n"
            "## Right Now\n"
            "You are in the Home project — the default workspace for cards, tasks, and conversation. "
            "If the user mentions a different project by name, pivot to it. "
            "Cards created here belong to the Home project.\n\n"
            "Do NOT say 'welcome back' on a first conversation. Greet naturally based on what they said."
        )

    def build_project_chat_init(self, project: dict) -> str:
        """Build the static Chat Init block for Project Chat mode.

        Dynamic details (description, card counts, recent activity) are intentionally
        omitted here to keep the system prompt cacheable. Inject them via
        build_dynamic_context_block() into the messages[] dynamic context instead.
        """
        name = project.get("title", "Untitled")
        bot_name = self.get_bot_name()

        return (
            f"## Project: {name}\n"
            f"You are {bot_name}, working on **{name}**. This is your context right now — you know this project, you're inside it.\n\n"
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
        bot_name = self.get_bot_name()

        return (
            f"## Chat Init — Card: {card_title}\n"
            f"Mode: Card Chat\n"
            f"## Card: {card_title}\n"
            f"You are {bot_name}, focused on this card in **{project_name}**. This is your current task — you're already inside it.\n\n"
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
        worker_classes: Optional[list[dict]] = None,
        live_state: Optional[str] = None,
        worker_events: Optional[str] = None,
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

        # Live-state heartbeat + worker activity (ambient signals) render FIRST
        # so Voxy reads "what's the environment right now" before per-project
        # context. These are short, bounded blocks.
        if live_state:
            parts.append(live_state.rstrip())
        if worker_events:
            parts.append(worker_events.rstrip())

        if chat_level in ("project", "general") and project:
            # Project chat: inject full project state.
            # Main/general chat with no project pulls the list via voxyflow.project.list on demand.
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
            backlog_cards = [c for c in cards if c.get("status") == "card"]

            state_line = (
                f"State: {total} cards — {done} done, {len(in_progress_cards)} in progress, "
                f"{len(todo_cards)} todo, {len(backlog_cards)} backlog"
            )

            # In-progress titles
            if in_progress_cards:
                ip_lines = "\n".join(f"  - {c.get('title', 'Untitled')}" for c in in_progress_cards)
                in_progress_block = f"In progress:\n{ip_lines}"
            else:
                in_progress_block = "In progress: (none)"

            # #9 Needs attention: flag cards stuck too long in a status. Heuristic:
            # in_progress > 7 days since last update, or todo > 14 days. Keep it
            # short (≤3 cards) — full board is already visible above.
            stale_lines: list[str] = []
            from datetime import datetime, timezone
            now = datetime.now(timezone.utc)
            def _parse_ts(raw: str):
                raw = str(raw or "").strip()
                if not raw:
                    return None
                try:
                    s = raw.replace(" ", "T")
                    # Strip microseconds if any — fromisoformat handles them but
                    # sqlalchemy str() can produce "2026-04-18 10:11:12.123456".
                    if "+" not in s and "Z" not in s:
                        s = s + "+00:00"
                    s = s.replace("Z", "+00:00")
                    return datetime.fromisoformat(s)
                except Exception:
                    return None
            for c in in_progress_cards:
                ts = _parse_ts(c.get("updated_at"))
                if ts and (now - ts).days > 7:
                    stale_lines.append(
                        f"  - ⚠️ {c.get('title', 'Untitled')} (in_progress, stale {((now - ts).days)}d)"
                    )
                    if len(stale_lines) >= 3:
                        break
            if len(stale_lines) < 3:
                for c in todo_cards:
                    ts = _parse_ts(c.get("updated_at"))
                    if ts and (now - ts).days > 14:
                        stale_lines.append(
                            f"  - ⚠️ {c.get('title', 'Untitled')} (todo, stale {((now - ts).days)}d)"
                        )
                        if len(stale_lines) >= 3:
                            break
            attention_block = (
                "Needs attention:\n" + "\n".join(stale_lines)
                if stale_lines else ""
            )

            # Todo titles
            if todo_cards:
                td_lines = "\n".join(f"  - {c.get('title', 'Untitled')}" for c in todo_cards)
                todo_block = f"Todo:\n{td_lines}"
            else:
                todo_block = "Todo: (none)"

            # Backlog titles (top 5)
            if backlog_cards:
                top_backlog = backlog_cards[:5]
                bl_lines = "\n".join(f"  - {c.get('title', 'Untitled')}" for c in top_backlog)
                backlog_block = f"Backlog (top {len(top_backlog)}):\n{bl_lines}"
                if len(backlog_cards) > 5:
                    backlog_block += f"\n  … and {len(backlog_cards) - 5} more"
            else:
                backlog_block = "Backlog: (none)"

            blocks_joined = f"{in_progress_block}\n{todo_block}\n{backlog_block}"
            if attention_block:
                blocks_joined += f"\n{attention_block}"
            parts.append(
                f"## Project Context: {name} (LIVE — this overrides any earlier data in the conversation)\n"
                f"Description: {description}\n"
                f"Tech Stack: {tech_stack}\n"
                f"GitHub: {github_url}\n\n"
                f"{state_line}\n\n"
                f"{blocks_joined}"
            )

        if chat_level == "card" and card:
            # Card chat: inject full card details
            card_title = card.get("title", "Untitled")
            card_id = card.get("id", "")
            status = card.get("status", "card")
            priority = card.get("priority", "medium")
            agent_type = card.get("agent_type") or "general"
            description = card.get("description") or "No description"
            assignee = card.get("assignee") or "Unassigned"

            checklist = card.get("checklist_items", [])
            total_items = len(checklist)
            completed_items = sum(1 for item in checklist if item.get("done") or item.get("completed"))

            # #8 card_id inherit: if we resolved a parent project, surface a
            # compact header so Voxy knows the surrounding board exists. Full
            # project rollup stays hidden — a card chat shouldn't flood with
            # siblings — but a name + 1-line state keeps orientation.
            parent_line = ""
            if project:
                p_cards = [c for c in (project.get("cards") or []) if c.get("status") != "archived"]
                p_done = sum(1 for c in p_cards if c.get("status") == "done")
                p_ip = sum(1 for c in p_cards if c.get("status") == "in_progress")
                parent_line = (
                    f"Parent project: {project.get('title', 'Untitled')} "
                    f"({len(p_cards)} cards, {p_done} done, {p_ip} in progress)\n"
                )

            id_part = f" ({card_id})" if card_id else ""
            parts.append(
                f"## Card Details: {card_title}\n"
                f"{parent_line}"
                f"Card: {card_title}{id_part}\n"
                f"Status: {status} | Priority: {priority} | Agent: {agent_type} | Assignee: {assignee}\n"
                f"Description: {description}\n"
                f"Checklist: {completed_items}/{total_items} items done"
            )

        if memory_context:
            parts.append(f"## Retrieved fragments (may be noisy — raw semantic hits, not curated truth; scores below ~0.20 are background noise)\n{memory_context}")

        if active_workers_context:
            parts.append(f"## Background Workers Status\n{active_workers_context}")

        if worker_classes:
            # Compact one-line-per-class format — names + intent hints only.
            # Full model/provider details are lazy-loaded via voxyflow.worker_class.list when needed.
            wc_lines = []
            for wc in worker_classes:
                name = wc.get("name", "?")
                patterns = wc.get("intent_patterns") or []
                hint = f" ({', '.join(patterns[:3])})" if patterns else ""
                wc_lines.append(f"{name}{hint}")
            parts.append("## Worker Classes\n" + " · ".join(wc_lines))

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

        preferred_language = ps.get("preferred_language", "auto")

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
            sections.append("## Retrieved fragments (may be noisy — raw semantic hits, not curated truth; scores below ~0.20 are background noise)\n")
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

    def build_dispatcher_prompt(
        self,
        tier: str = "fast",
        chat_level: str = "general",
        project: Optional[dict] = None,
        card: Optional[dict] = None,
        agent_persona: Optional[dict] = None,
        native_tools: bool = False,
    ) -> str:
        """Build the STATIC dispatcher system prompt.

        Fast and Deep are the SAME layer (the dispatcher). Only the style hint
        differs (brief vs thoughtful). Keep this single source of truth — any
        new behaviour belongs here, not in tier-specific copies.

        Cache stability contract: returns an IDENTICAL string for the same
        (tier, chat_level, project.id, card.id, native_tools) tuple. Dynamic
        data lives in build_dynamic_context_block() / messages[], not here.
        """
        if chat_level == "card" and card and project:
            base = self.build_card_prompt(project, card, agent_persona)
        elif project:
            base = self.build_project_prompt(project)
        else:
            base = self.build_general_prompt()

        mode_label = f"Project Chat: {project.get('title', 'Home')}" if project else "Home Chat"
        if tier == "deep":
            style = "Opus — thoughtful, precise, depth when helpful."
        else:
            style = "Haiku — respond briefly (1–3 sentences)."
        init_block = (
            f"\n\n## Dispatcher ({tier}) — {mode_label}\n"
            f"{style} Match the user's language. You SPEAK and READ only — every state change "
            f"is delegated. About to call a write/execute tool? STOP and delegate instead."
        )
        full_prompt = base + init_block + self._build_dispatcher_tail(native_tools)
        logger.info(
            f"[PersonalityService] Dispatcher prompt built (tier={tier}): "
            f"{len(full_prompt)} chars, chat_level={chat_level}, native_tools={native_tools}"
        )
        return full_prompt

    def build_fast_prompt(
        self,
        memory_context: Optional[str] = None,
        chat_level: str = "general",
        project: Optional[dict] = None,
        card: Optional[dict] = None,
        agent_persona: Optional[dict] = None,
        project_names: Optional[list] = None,
        native_tools: bool = False,
    ) -> str:
        """Compat wrapper — delegates to build_dispatcher_prompt(tier="fast")."""
        return self.build_dispatcher_prompt(
            tier="fast",
            chat_level=chat_level,
            project=project,
            card=card,
            agent_persona=agent_persona,
            native_tools=native_tools,
        )

    def _build_dispatcher_tail(self, native_tools) -> str:
        """Shared tail — architecture + dispatcher.md + proactive + delegate instructions."""
        tail = ""
        architecture = self.load_architecture()
        if architecture:
            tail += "\n\n" + architecture
        dispatcher = self.load_dispatcher()
        if dispatcher:
            tail += "\n\n" + dispatcher
        proactive = self.load_proactive()
        if proactive:
            tail += "\n\n" + proactive
        if native_tools == "cli_mcp":
            tail += self._build_cli_mcp_delegate_instructions()
        elif native_tools:
            tail += self._build_native_delegate_instructions()
        else:
            tail += self._build_xml_delegate_instructions()
        return tail

    def _build_native_delegate_instructions(self) -> str:
        """Delegate instructions when native tool_use is available (Anthropic SDK)."""
        return (
            "\n\n## ⚡ delegate_action tool\n"
            "To DO anything (not just chat), call `delegate_action(action, summary, model, complexity)`.\n"
            "Model: **haiku** only for enrich/summarize/research/web_search/review "
            "(others auto-upgrade). **sonnet** default. **opus** for complex reasoning or "
            "multi-file code. Without delegate_action, nothing executes.\n"
            "Large worker outputs → `workers_read_artifact(task_id, offset?, length?)` for the full raw "
            "result (callbacks only carry a ~10K preview).\n\n"
            "## 🚫 Not your tools\n"
            "You run inside Voxyflow's chat, not in a terminal. You may see Bash/Read/Write/WebSearch — "
            "those belong to the runtime. Use ONLY `delegate_action` + natural language. "
            "Never claim you can't access tools or that your knowledge is cut off — delegate instead."
        )

    def _build_cli_mcp_delegate_instructions(self) -> str:
        """Delegate instructions for CLI+MCP mode: inline tools via MCP + XML delegates."""
        return (
            "\n\n## ⚡ Two ways to act\n"
            "**Inline MCP tools** (direct, fast): memory/knowledge search+save, "
            "voxyflow.card/project/wiki/workers CRUD, workers.read_artifact for full worker output. "
            "Call them directly for lookups and simple CRUD — no delegation needed.\n\n"
            "**Project scoping is automatic**: memory/knowledge tools are scoped to the current "
            "project by the runtime. Don't pass project_id manually. Main/general chat falls back "
            "to global + system-main memory.\n\n"
            "**Inline memory.search is expected, not stalling.** If you need a fact you don't "
            "have, call it mid-response — that's normal. Don't self-censor or apologise for a "
            "quick lookup; it's part of how you think.\n\n"
            "**<delegate> block** (end of response) for research, multi-step, web, code, commands:\n"
            "<delegate>\n"
            '{"action":"...","model":"haiku|sonnet|opus","description":"..."}\n'
            "</delegate>\n"
            "Model: **haiku** only for enrich/summarize/research/web_search/review "
            "(others auto-upgrade). **sonnet** default. **opus** for complex reasoning or "
            "multi-file code. Without <delegate>, complex tasks don't execute. When in doubt, delegate.\n\n"
            "## 🚫 Not your tools\n"
            "You run inside Voxyflow's chat via Claude Code CLI. You may see Bash/Read/Write/WebSearch — "
            "those belong to the runtime. Use ONLY inline MCP tools + <delegate> + natural language."
        )

    def _build_xml_delegate_instructions(self) -> str:
        """Delegate instructions for XML fallback (proxy mode)."""
        return (
            "\n\n## ⚡ <delegate> block\n"
            "To DO anything (not just chat), include a <delegate> block at the END of your response:\n"
            "<delegate>\n"
            '{"action":"...","model":"haiku|sonnet|opus","description":"..."}\n'
            "</delegate>\n"
            "Model: **haiku** only for enrich/summarize/research/web_search/review "
            "(others auto-upgrade). **sonnet** default. **opus** for complex reasoning or "
            "multi-file code. Without <delegate>, nothing executes.\n\n"
            "## 🚫 Not your tools\n"
            "You run inside Voxyflow's chat, not in a terminal. You may see Bash/Read/Write/WebSearch — "
            "those belong to the runtime. Use ONLY <delegate> + natural language. "
            "Never claim you can't access tools or that your knowledge is cut off — delegate instead."
        )

    def build_deep_prompt(
        self,
        memory_context: Optional[str] = None,
        chat_level: str = "general",
        project: Optional[dict] = None,
        card: Optional[dict] = None,
        project_names: Optional[list] = None,
        has_delegation: bool = False,
        is_chat_responder: bool = False,
        native_tools: bool = False,
    ) -> str:
        """Compat wrapper — delegates to build_dispatcher_prompt(tier="deep").

        is_chat_responder=False returns the static base only (no dispatcher tail),
        preserving the legacy supervisor/background-executor escape hatch.
        """
        if not is_chat_responder:
            if chat_level == "card" and card and project:
                return self.build_card_prompt(project, card)
            if project:
                return self.build_project_prompt(project)
            return self.build_general_prompt()
        return self.build_dispatcher_prompt(
            tier="deep",
            chat_level=chat_level,
            project=project,
            card=card,
            native_tools=native_tools,
        )

    # ------------------------------------------------------------------
    # Worker prompts — function-based (same tools regardless of model)
    # ------------------------------------------------------------------

    def build_worker_prompt(
        self,
        model: str = "sonnet",
        chat_level: str = "general",
        project: Optional[dict] = None,
        card: Optional[dict] = None,
    ) -> str:
        """Build system prompt for background worker execution.

        All workers get the same tools and prompt structure regardless of model.
        The model only affects speed/capability, not the role or tool access.
        """
        from app.tools.registry import TOOLS_WORKER
        tool_list = self._build_tool_section(TOOLS_WORKER, chat_level)
        context = self._build_worker_context_section(chat_level, project, card)
        worker_rules = self.load_worker()

        return (
            f"{worker_rules}\n\n"
            f"## Active Role: Worker (Task Executor)\n\n"
            f"## Available Tools\n{tool_list}\n\n"
            f"## Context\n{context}"
        )

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
            "Context: Home project (default workspace, project_id=system-main)\n"
            f"Workspace: {ws_dir}\n"
            f"CWD is set to {ws_dir} — use relative paths for workspace files.\n"
            "Voxyflow app codebase: ~/voxyflow/ (do NOT write project files here)."
        )

    def build_agent_prompt(self, agent_persona: str, task_context: str, memory_context: Optional[str] = None) -> str:
        return self.build_system_prompt(base_prompt=task_context, include_memory_context=memory_context, agent_persona=agent_persona)


_personality_service: Optional[PersonalityService] = None


def get_personality_service() -> PersonalityService:
    global _personality_service
    if _personality_service is None:
        _personality_service = PersonalityService()
    return _personality_service


# ---------------------------------------------------------------------------
# Ambient context blocks (Live state + Worker activity)
#
# These render at the top of the dynamic context each turn. They replace the
# old "worker completion re-triggers a dispatcher turn" flow — Voxy now sees
# ambient signals without being forced into a response turn.
# ---------------------------------------------------------------------------

_STATUS_GLYPH = {"success": "✓", "ok": "✓", "failed": "✗", "error": "✗"}


def _fmt_delta_seconds(seconds: float) -> str:
    seconds = max(0, int(seconds))
    if seconds < 60:
        return f"{seconds}s"
    mins, sec = divmod(seconds, 60)
    if mins < 60:
        return f"{mins}m{sec:02d}s"
    hours, mins = divmod(mins, 60)
    if hours < 24:
        return f"{hours}h{mins:02d}m"
    days, hours = divmod(hours, 24)
    return f"{days}d{hours:02d}h"


def build_worker_events_block(events: list[dict]) -> str:
    """Render completed worker events as a short reference block.

    This is NOT a turn. It just tells Voxy "these finished while you were away;
    call workers.get_result if you want the detail." Hard cap ≤10 lines / 600 chars.
    """
    if not events:
        return ""
    lines: list[str] = ["## Worker activity since your last turn"]
    for ev in events[:10]:
        status = (ev.get("status") or "success").lower()
        glyph = _STATUS_GLYPH.get(status, "•")
        intent = ev.get("intent") or "unknown"
        task_id = ev.get("task_id") or "?"
        summary = (ev.get("summary_line") or "").strip()
        # Prefer the summary if present; otherwise just fall back to the hint.
        tail = summary if summary else "use workers.get_result for details"
        line = f"- {glyph} {task_id} — {intent} ({status}) — {tail}"
        lines.append(line[:140])

    rendered = "\n".join(lines)
    if len(rendered) > 600:
        rendered = rendered[:580].rstrip() + "\n[... events truncated — use workers.list ...]"
    return rendered


def build_live_state_block(
    *,
    active_workers: int,
    next_job: Optional[dict] = None,
    pending_actions: Optional[int] = None,
    cards_updated_today: Optional[int] = None,
    last_user_turn_ago: Optional[str] = None,
    running_worker_intents: Optional[list[str]] = None,
) -> str:
    """Render the ambient "what is currently running" block.

    Silent on any field we don't have data for — don't render `unknown`
    placeholders because that's noise for Voxy. Hard cap ~8 lines, ~300 chars.
    """
    lines: list[str] = ["## Live state"]
    if running_worker_intents:
        # Summarise active workers by intent (first 3) so Voxy sees *what's*
        # running, not just a number.
        brief = ", ".join(running_worker_intents[:3])
        if len(running_worker_intents) > 3:
            brief += f", +{len(running_worker_intents) - 3}"
        lines.append(f"- Active workers: {int(active_workers or 0)} ({brief})")
    else:
        lines.append(f"- Active workers: {int(active_workers or 0)}")
    if next_job and next_job.get("name"):
        eta = next_job.get("eta_seconds")
        eta_str = f"in {_fmt_delta_seconds(eta)}" if isinstance(eta, (int, float)) else "scheduled"
        lines.append(f"- Next scheduled job: {next_job['name']} {eta_str}")
    if cards_updated_today is not None and cards_updated_today > 0:
        lines.append(f"- Cards touched today: {cards_updated_today}")
    if last_user_turn_ago:
        lines.append(f"- Last user turn: {last_user_turn_ago} ago")
    if pending_actions is not None:
        if pending_actions > 0:
            lines.append(f"- Pending user actions: {pending_actions}")
        else:
            lines.append("- Pending user actions: (none)")
    return "\n".join(lines)
