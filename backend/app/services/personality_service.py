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

    def build_general_chat_init(self, workspace_names: Optional[list] = None) -> str:
        """Build the Chat Init block for Home workspace chat (system-main).

        This is the system "Home" workspace's chat.
        The static base omits workspace_names — inject dynamically via build_dynamic_context_block().
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
            "You are in the Home workspace — the default workspace for cards, tasks, and conversation. "
            "If the user mentions a different workspace by name, pivot to it. "
            "Cards created here belong to the Home workspace.\n\n"
            "Do NOT say 'welcome back' on a first conversation. Greet naturally based on what they said."
        )

    def build_workspace_chat_init(self, workspace: dict) -> str:
        """Build the static Chat Init block for Workspace Chat mode.

        Dynamic details (description, card counts, recent activity) are intentionally
        omitted here to keep the system prompt cacheable. Inject them via
        build_dynamic_context_block() into the messages[] dynamic context instead.
        """
        name = workspace.get("title", "Untitled")
        bot_name = self.get_bot_name()

        return (
            f"## Workspace: {name}\n"
            f"You are {bot_name}, working on **{name}**. This is your context right now — you know this workspace, you're inside it.\n\n"
            f"You can create cards, move them, update them, assign agents, write wiki pages. "
            f"When the user asks you to do something in this workspace, do it — don't explain that you can. "
            f"Stay focused here unless they explicitly ask about something else."
        )

    def build_card_chat_init(self, workspace: dict, card: dict) -> str:
        """Build the static Chat Init block for Card Chat mode.

        Dynamic details (description, status, checklist) are intentionally omitted here
        to keep the system prompt cacheable. Inject them via build_dynamic_context_block()
        into the messages[] dynamic context instead.
        """
        workspace_name = workspace.get("title", "Untitled")
        card_title = card.get("title", "Untitled")
        bot_name = self.get_bot_name()

        return (
            f"## Chat Init — Card: {card_title}\n"
            f"Mode: Card Chat\n"
            f"## Card: {card_title}\n"
            f"You are {bot_name}, focused on this card in **{workspace_name}**. This is your current task — you're already inside it.\n\n"
            f"You are here to work on this task — not to describe what you could do. "
            f"If the user says 'implement this', you start. If they say 'write the PRD', you write it. "
            f"Act with the confidence of someone who knows exactly what they're doing."
        )

    def build_dynamic_context_block(
        self,
        chat_level: str = "general",
        workspace: Optional[dict] = None,
        card: Optional[dict] = None,
        workspace_names: Optional[list] = None,
        memory_context: Optional[str] = None,
        active_workers_context: Optional[str] = None,
        worker_classes: Optional[list[dict]] = None,
        live_state: Optional[str] = None,
        worker_events: Optional[str] = None,
        session_handoff: Optional[str] = None,
    ) -> str:
        """Build the DYNAMIC context block — injected into messages[], NOT the system prompt.

        Contains everything that changes call-to-call:
        - memory_context (per-query vector search results)
        - workspace description, tech stack, github, card counts, recent activity
        - card description, status, checklist details
        - workspace names list (for main/general chat)

        By keeping this OUT of the system prompt, the static base_prompt stays
        identical across calls → Anthropic KV cache hits.
        """
        parts: list[str] = []

        # Wall-clock "now" — first thing the model reads in dynamic context.
        # Without this, the dispatcher hallucinates the hour ("à demain"
        # mid-afternoon) and can't anchor relative phrases like "il y a 2h".
        try:
            from app.services.time_context import format_now_block
            parts.append(format_now_block())
        except Exception as e:  # pragma: no cover — defensive
            logger.debug("format_now_block failed: %s", e)

        # Live-state heartbeat + worker activity (ambient signals) render next
        # so Voxy reads "what's the environment right now" before per-workspace
        # context. These are short, bounded blocks.
        if live_state:
            parts.append(live_state.rstrip())
        if worker_events:
            parts.append(worker_events.rstrip())
        if session_handoff:
            parts.append(session_handoff.rstrip())

        if chat_level in ("workspace", "general") and workspace:
            # Workspace chat: inject full workspace state.
            # Main/general chat with no workspace pulls the list via voxyflow.workspace.list on demand.
            name = workspace.get("title", "Untitled")
            workspace_id = workspace.get("id") or ""
            description = workspace.get("description") or "No description"
            tech_stack = workspace.get("tech_stack") or "Not specified"
            github_url = workspace.get("github_url") or "Not linked"
            all_cards = workspace.get("cards", [])
            cards = [c for c in all_cards if c.get("status") != "archived"]
            total = len(cards)
            done = sum(1 for c in cards if c.get("status") == "done")
            in_progress_cards = [c for c in cards if c.get("status") == "in_progress"]
            todo_cards = [c for c in cards if c.get("status") == "todo"]
            backlog_cards = [c for c in cards if c.get("status") == "backlog"]

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
            id_line = f"Workspace ID: {workspace_id}\n" if workspace_id else ""
            parts.append(
                f"## Workspace Context: {name} (LIVE — this overrides any earlier data in the conversation)\n"
                f"{id_line}"
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
            status = card.get("status", "backlog")
            priority = card.get("priority", "medium")
            agent_type = card.get("agent_type") or "general"
            description = card.get("description") or "No description"
            assignee = card.get("assignee") or "Unassigned"

            checklist = card.get("checklist_items", [])
            total_items = len(checklist)
            completed_items = sum(1 for item in checklist if item.get("done") or item.get("completed"))

            # #8 card_id inherit: if we resolved a parent workspace, surface a
            # compact header so Voxy knows the surrounding board exists. Full
            # workspace rollup stays hidden — a card chat shouldn't flood with
            # siblings — but a name + 1-line state keeps orientation.
            parent_line = ""
            if workspace:
                p_cards = [c for c in (workspace.get("cards") or []) if c.get("status") != "archived"]
                p_done = sum(1 for c in p_cards if c.get("status") == "done")
                p_ip = sum(1 for c in p_cards if c.get("status") == "in_progress")
                parent_line = (
                    f"Parent workspace: {workspace.get('title', 'Untitled')} "
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
    # Context-isolated prompt builders (general / workspace / card)
    # ------------------------------------------------------------------

    def build_general_prompt(self, workspace_names: Optional[list] = None) -> str:
        """Build STATIC system prompt for General Chat — no workspace context.

        workspace_names is accepted for backward compat but no longer embedded here.
        Dynamic context (workspace names, memory) must be injected via build_dynamic_context_block().
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

    def build_workspace_prompt(self, workspace: dict) -> str:
        """Build STATIC system prompt for Workspace Chat — scoped to one workspace.

        Dynamic workspace details (description, recent cards) must be injected
        via build_dynamic_context_block().
        """
        soul = self.load_soul()
        user = self.load_user()
        agents = self.load_agents()

        sections = []

        # Chat Init FIRST — before personality files (static only)
        sections.append(self.build_workspace_chat_init(workspace))

        if soul:
            sections.append(soul)
        if agents:
            sections.append(agents)
        if user:
            sections.append(user)

        return "\n\n".join(sections)

    def build_card_prompt(self, workspace: dict, card: dict, agent_persona: Optional[dict] = None) -> str:
        """Build STATIC system prompt for Card Chat — scoped to a specific task.

        Dynamic card details (description, status, checklist) must be injected
        via build_dynamic_context_block().
        """
        soul = self.load_soul()

        sections = []

        # Chat Init FIRST — before agent persona and personality (static only)
        sections.append(self.build_card_chat_init(workspace, card))

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
        workspace: Optional[dict] = None,
        card: Optional[dict] = None,
        agent_persona: Optional[dict] = None,
        native_tools: bool = False,
    ) -> str:
        """Build the STATIC dispatcher system prompt.

        Fast and Deep are the SAME layer (the dispatcher). Only the style hint
        differs (brief vs thoughtful). Keep this single source of truth — any
        new behaviour belongs here, not in tier-specific copies.

        Cache stability contract: returns an IDENTICAL string for the same
        (tier, chat_level, workspace.id, card.id, native_tools) tuple. Dynamic
        data lives in build_dynamic_context_block() / messages[], not here.
        """
        if chat_level == "card" and card and workspace:
            base = self.build_card_prompt(workspace, card, agent_persona)
        elif workspace:
            base = self.build_workspace_prompt(workspace)
        else:
            base = self.build_general_prompt()

        mode_label = f"Workspace Chat: {workspace.get('title', 'Home')}" if workspace else "Home Chat"
        if tier == "deep":
            style = "Opus — thoughtful, precise, depth when helpful."
        else:
            style = "Haiku — respond briefly (1–3 sentences)."
        if native_tools == "codex_mcp":
            action_rule = (
                "**Read-only dispatcher.** Use MCP only to inspect memory, knowledge, "
                "session state, and worker results. Any action work = delegate. "
                "Do not do card/workspace/wiki/doc writes, code, research, web, shell, files, "
                "long analysis, or multi-step execution inline."
            )
        else:
            action_rule = (
                "**Instant + local = inline. Needs subprocess (shell, web, multi-file code, "
                "heavy AI) = delegate.** Single-user local DB + undo journal makes inline "
                "writes/deletes safe. When in doubt: would this take >1s or touch the OS? → delegate."
            )
        init_block = (
            f"\n\n## Dispatcher ({tier}) — {mode_label}\n"
            f"{style} Match the user's language. {action_rule}"
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
        workspace: Optional[dict] = None,
        card: Optional[dict] = None,
        agent_persona: Optional[dict] = None,
        workspace_names: Optional[list] = None,
        native_tools: bool = False,
    ) -> str:
        """Compat wrapper — delegates to build_dispatcher_prompt(tier="fast")."""
        return self.build_dispatcher_prompt(
            tier="fast",
            chat_level=chat_level,
            workspace=workspace,
            card=card,
            agent_persona=agent_persona,
            native_tools=native_tools,
        )

    def build_autonomy_prompt(
        self,
        workspace: Optional[dict],
        directive_path: str,
        native_tools: bool = False,
    ) -> str:
        """Build the system prompt for an autonomy heartbeat tick.

        Same toolset as the dispatcher (read + CRUD + delegate), but with the
        interactive "wait for go" gate replaced by autonomy operating rules.
        The heartbeat has no user present — the directive file IS the go signal.
        """
        base = self.build_workspace_prompt(workspace) if workspace else self.build_general_prompt()
        workspace_title = (workspace or {}).get("title") or "?"
        init_block = (
            f"\n\n## Autonomy Heartbeat — {workspace_title}\n"
            "You run on a cron, not from a user message. The directive you receive "
            "IS the instruction. You have the eyes on the board; workers have the hands. "
            "Your job: read → decide → delegate or no-op. Be concise."
        )
        tail = ""
        architecture = self.load_architecture()
        if architecture:
            tail += "\n\n" + architecture
        tail += self._build_autonomy_operating_rules(directive_path)
        if native_tools == "codex_mcp":
            tail += self._build_codex_mcp_delegate_instructions()
        elif native_tools == "claude_cli_mcp":
            tail += self._build_cli_mcp_delegate_instructions()
        elif native_tools:
            tail += self._build_native_delegate_instructions()
        else:
            tail += self._build_xml_delegate_instructions()
        full_prompt = base + init_block + tail
        logger.info(
            f"[PersonalityService] Autonomy prompt built: {len(full_prompt)} chars, "
            f"workspace={workspace_title}, native_tools={native_tools}"
        )
        return full_prompt

    def _build_autonomy_operating_rules(self, directive_path: str) -> str:
        """Autonomy-specific rules that replace the dispatcher 'wait for go' gate."""
        return (
            "\n\n## Autonomy Operating Rules\n"
            "**No user is present.** This execution was fired by a scheduler. "
            "The directive you receive in the user message IS the go signal.\n\n"
            "- **Delegate freely.** No 'wait for go' gate — the directive is the confirmation. "
            "Call the `voxyflow.delegate` tool or `voxyflow.jobs.create` without asking.\n"
            "- **Act in one cycle.** Do not present a plan and wait — there is no one to confirm. "
            "Either act now or log a no-op.\n"
            "- **Eyes on the board, hands on the workers.** Decide what to do, then delegate with a "
            "focused self-contained brief. You CANNOT `system.exec`, `file.write`, `git.*` yourself — "
            "those are worker-only tools. Always delegate for anything touching the filesystem or shell.\n"
            "- **No-op discipline.** If the directive is empty, ambiguous, already satisfied, or would "
            "require clarification from a user: respond with exactly `[AUTONOMY-NOOP] <one-line reason>` "
            "and stop. Do NOT brainstorm, do NOT save speculative `memory.save` notes, do NOT invent "
            "product ideas on a no-op cycle.\n"
            f"- **Chain cycles via the directive file.** To continue work on the next tick, delegate a "
            f"worker to rewrite `{directive_path}` below its `---` divider. `file.write` is worker-only.\n"
            "- **One concise response per tick.** Each cycle either delegates, updates cards, rewrites "
            "the directive, or logs a no-op. Nothing else.\n\n"
            "**This REPLACES the 'ACT, DON'T ASK' and 'Worker Delegation Gate' sections from the "
            "interactive dispatcher protocol.** Those rules protect real users from unsolicited "
            "delegations; they do not apply when the user is the scheduler itself."
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
        tail += "\n\n" + self._build_reserved_ports_rule(role="dispatcher")
        if native_tools == "codex_mcp":
            tail += self._build_codex_mcp_delegate_instructions()
        elif native_tools == "claude_cli_mcp":
            tail += self._build_cli_mcp_delegate_instructions()
        elif native_tools:
            tail += self._build_native_delegate_instructions()
        else:
            tail += self._build_xml_delegate_instructions()
        return tail

    def _build_reserved_ports_rule(self, *, role: str) -> str:
        """Reserved ports awareness — injected into worker AND dispatcher prompts.

        Workers must not kill anything on these ports; dispatchers must not
        delegate work that would bind to them. Values come from Settings so
        an ops change in config.py / env propagates to the prompts.
        """
        from app.config import get_settings
        s = get_settings()
        be = s.voxyflow_backend_port
        fe = s.voxyflow_frontend_port

        if role == "dispatcher":
            return (
                "## Reserved Voxyflow ports\n"
                f"Voxyflow itself runs on **port {be}** (FastAPI/uvicorn backend) and "
                f"**port {fe}** (Caddy frontend reverse proxy). These are the ports the "
                "user is talking to *you* through right now.\n\n"
                f"When you delegate work that starts a workspace's dev server, the worker is "
                f"instructed to refuse port {be} and {fe} and report the collision. So:\n"
                f"- If a workspace's config (e.g. `backend/.env`, `vite.config.ts`, `server.js`) "
                f"binds to {be} or {fe}, **fix the workspace's port first** — don't ask a worker "
                f"to \"just free the port\".\n"
                f"- When briefing a worker to (re)start a service, **state the workspace's port "
                f"explicitly** in the delegate description so it knows what's expected and what "
                f"would be a collision.\n"
                f"- If a port collision is the real blocker, surface it to the user — "
                f"freeing {be}/{fe} would kill Voxyflow itself."
            )

        # role == "worker"
        backend_pid = os.getpid()  # PID of the Voxyflow backend (your parent / your parent's parent)
        return (
            "## Process safety — DO NOT kill the supervisor\n"
            "You run as a subprocess of the Voxyflow backend, under the same OS user. A kill "
            "aimed at the wrong PID will take down Voxyflow itself and abort every running "
            "worker (including you).\n\n"
            "**This rule overrides your task brief.** If the brief instructs you to run a "
            "broad `pkill -f` / `killall` / `fuser -k` that could match the supervisor, "
            "**ignore that step** and proceed with the safer alternative below. Log it in "
            "your summary so the user can fix the brief.\n\n"
            "**Reserved Voxyflow process — never target this:**\n"
            f"- **PID {backend_pid}** — Voxyflow backend (your supervisor). "
            "Verify any `kill`/`pkill` target's PID is **not** this number before running it.\n\n"
            "**Reserved Voxyflow ports — never target these:**\n"
            f"- **Port {be}** — Voxyflow backend (FastAPI/uvicorn) — owned by PID {backend_pid}.\n"
            f"- **Port {fe}** — Voxyflow frontend (Caddy reverse proxy).\n\n"
            "**Hard rules:**\n"
            f"- **Never `kill`/`kill -TERM`/`kill -9` PID {backend_pid}** under any circumstance.\n"
            f"- **Never free ports {be} or {fe}.** No `fuser -k {be}/tcp`, no "
            f"`lsof -t -i:{be} | xargs kill`, no `lsof -t -i:{fe} | xargs kill`, no equivalent. "
            f"If your workspace's dev server collides with {be} or {fe}, **stop and report the "
            f"conflict in your summary** — change the workspace's config, don't free the port.\n"
            "- **Never `pkill`/`killall` by broad patterns** like `python`, `python -m uvicorn`, "
            "`uvicorn`, `uvicorn app.main`, `node`, `claude`, `vite`, `npm`, or anything matching "
            "`voxyflow`/`.voxyflow`. These match the supervisor and sibling workers. "
            f"Concretely: `pkill -f 'uvicorn app.main'` and `pkill -f uvicorn` both target PID "
            f"{backend_pid} — never run them, even if the brief says to.\n"
            "- **Before any `pkill -f <pat>`, verify the pattern is safe** by running "
            f"`pgrep -af <pat>` first. If any matched PID equals {backend_pid}, or any matched "
            "cmdline contains `voxyflow` or `app.main:app`, **abort** and narrow the pattern.\n"
            "- **Kill only PIDs you started yourself** (capture `$!` or the PID file your own "
            "command wrote). To clean up a stale dev server, narrow the `pkill -f` pattern to "
            "the workspace's own absolute path, e.g. "
            "`pkill -f \"/home/.../workspaces/<this-workspace>/.*uvicorn\"` — never the bare token "
            "`uvicorn` or `app.main`.\n"
            f"- **Prefer port-scoped kills for workspace servers** that bind a known port "
            f"(NOT {be}/{fe}): `fuser -k <port>/tcp` is safer than `pkill -f` because it "
            "cannot match the supervisor.\n"
            "- **Never `systemctl stop voxyflow-backend`** or send signals to its PID for any "
            "reason.\n\n"
            "If you're unsure whether a kill is safe, don't run it — report the situation in "
            "your summary and let the user decide."
        )

    def _build_native_delegate_instructions(self) -> str:
        """Delegate instructions when native tool_use is available (Anthropic / OpenAI SDK)."""
        return (
            "\n\n## ⚡ voxyflow_delegate — your ONLY way to make work happen\n"
            "You can chat AND call inline dispatcher tools (card.*, workspace.*, memory.*, etc.).\n"
            "You CANNOT execute real work yourself (research, web search, code, files, shell).\n"
            "For ALL such work you MUST call `voxyflow_delegate`. Workers run on Claude — they do the job.\n\n"
            "**Trigger rule** — if the user asks for any of these (in any language), call\n"
            "`voxyflow_delegate` IMMEDIATELY, no questions, no plan, no « do you want me to…? »:\n"
            "  run, launch, execute, do, find, search, research, web search, write, code,\n"
            "  debug, deploy, summarize, analyze, build, fix, implement, scrape, crawl.\n\n"
            "**Few-shot examples — copy this pattern verbatim**:\n\n"
            "User: \"run the research on gold rivers\"\n"
            "→ call `voxyflow_delegate({\"action\":\"research\",\"description\":\"Research gold-bearing rivers in Quebec — compile main rivers, historical finds, and modern prospecting tips.\","
            "\"complexity\":\"complex\"})`\n"
            "Then reply: \"🚀 Worker launched on the research.\"\n\n"
            "User: \"do a web search on X\"\n"
            "→ call `voxyflow_delegate({\"action\":\"web_research\",\"description\":\"Search the web for X and return a clear summary with sources.\"})`\n"
            "Then reply: \"🚀 Worker launched.\"\n\n"
            "User: \"work on the card / execute card Y\"\n"
            "→ call `voxyflow_delegate({\"action\":\"execute_card\",\"description\":\"Execute card Y — read its description, implement the task, update the card with results.\","
            "\"complexity\":\"complex\"})`\n"
            "Then reply: \"🚀 Worker launched on the card.\"\n\n"
            "User: \"write the code for Z\"\n"
            "→ call `voxyflow_delegate({\"action\":\"complex_coding\",\"description\":\"Implement Z — full implementation, tests, commit.\","
            "\"complexity\":\"complex\"})`\n\n"
            "User: \"summarize this report\"\n"
            "→ call `voxyflow_delegate({\"action\":\"summarize\",\"description\":\"Summarize the attached report into 5 bullet points.\"})`\n\n"
            "**Schema** — `voxyflow_delegate` takes:\n"
            "  - `action` (required string): short English verb phrase\n"
            "  - `description` (required string): full task brief for the worker\n"
            "  - `complexity` (optional): \"simple\" | \"standard\" | \"complex\"\n"
            "  - `card_id` (optional uuid): card this task belongs to\n"
            "  - `context` (optional string): extra ambient context\n"
            "No other fields are allowed (strict schema).\n\n"
            "**Anti-patterns to AVOID**:\n"
            "- ❌ \"Do you want me to launch a worker?\"           → just call voxyflow_delegate.\n"
            "- ❌ \"Here are the steps: 1. … 2. … 3. …\"          → just call voxyflow_delegate.\n"
            "- ❌ Long markdown explaining what you would do      → just call voxyflow_delegate.\n"
            "- ✅ One voxyflow_delegate call + one short confirmation line.\n\n"
            "Set `complexity:\"complex\"` for multi-step or destructive work, otherwise omit it.\n"
            "Reply to the user in their own language, but the action verbs stay in English.\n"
            "Without voxyflow_delegate, nothing executes. Asking for confirmation = failure.\n\n"
            "## 📖 Reading worker output — NEVER spawn a worker just to read another worker\n"
            "Worker callbacks only carry a ~10K preview. The full verbatim output is on disk\n"
            "and YOU read it yourself, in chunks, via `workers_read_artifact(task_id, offset?, length?)`.\n"
            "- Output too large / 'truncated' / 'the report is in the card' →\n"
            "  call `workers_read_artifact` repeatedly with growing offsets. No re-delegation.\n"
            "- Always check `workers_read_artifact` BEFORE re-running a delegate: an artifact\n"
            "  on disk means the worker really did finish, even if `workers_list` lost track.\n"
            "- Before relaunching the same task, also call `workers_list` — if a worker is still\n"
            "  active on the same card, wait for it instead of spawning a parallel run.\n\n"
            "## 🚫 Not your tools\n"
            "You run inside Voxyflow's chat, not in a terminal. You may see Bash/Read/Write/WebSearch — "
            "those belong to the runtime. Use ONLY `voxyflow_delegate` + natural language. "
            "Never claim you can't access tools or that your knowledge is cut off — delegate instead."
        )

    def _build_cli_mcp_delegate_instructions(self) -> str:
        """Delegate instructions for CLI+MCP mode: inline tools via MCP + voxyflow.delegate tool."""
        return (
            "\n\n## ⚡ Two ways to act\n"
            "**Inline MCP tools** (direct, fast — instant + local): memory, knowledge "
            "graph (kg.*), all card/workspace/wiki/doc CRUD incl. deletes, "
            "checklists/relations/time, sessions, workers.list/read_artifact, "
            "task.peek/cancel/steer, jobs, autonomy, heartbeat, endpoints, focus, undo. "
            "See docs/TOOLS.md or backend/app/tools/registry.py for the canonical full list.\n\n"
            "**Worker-only** (need a subprocess): voxyflow.ai.standup/brief/health/"
            "prioritize/review_code, voxyflow.card.enrich, file.*, system.exec, "
            "web.search/web.fetch, git.*, tmux.*, anything touching files or the OS.\n\n"
            "## 📖 Reading worker output — the ambient block IS the deliverable\n"
            "The `## Worker activity since your last turn` block in your prompt contains the\n"
            "worker's full structured `voxyflow.worker.complete` payload: summary, findings,\n"
            "pointers, next_step. **That's the deliverable — read it directly and answer.**\n"
            "Don't call `workers.list` or `workers.get_result` just to find what's already in\n"
            "the block, and don't pretend you're « fetching the result » — you have it.\n"
            "NOTE: every `workers.X(...)` below is ONE MCP tool — call `voxyflow.workers` with\n"
            "`action` set to `list` / `get_result` / `read_artifact` / `ack_artifact` /\n"
            "`list_unread` (plus `task_id` / `offset` / `length` as needed), not a separate\n"
            "tool per operation.\n"
            "- Call `workers.get_result(task_id)` only when you need fields the block omitted\n"
            "  (e.g. pointers offsets to read with `read_artifact`, or full unsummarised text).\n"
            "- Call `workers.read_artifact(task_id, offset, length)` when the block points to a\n"
            "  specific section you need verbatim (logs, file content, command output). Page\n"
            "  with growing offsets if the artifact is large. NEVER re-delegate to read.\n"
            "- An artifact on disk means the worker really did finish, even if `workers.list`\n"
            "  no longer shows it. Don't say « il a expiré » — try `read_artifact` first.\n"
            "- Before delegating again on the same card: call `voxyflow.workers.list` — if a\n"
            "  worker is still active for that card, wait for it. The dispatcher will refuse\n"
            "  to spawn a parallel one anyway.\n"
            "- **After consuming a worker result** (reading artifact, saving to memory/wiki/cards):\n"
            "  call `workers.ack_artifact(task_id)` to close the loop and free disk.\n"
            "  This is ALWAYS the last step after consuming any worker deliverable.\n"
            "- At session start: `workers.list_unread()` shows artifacts from past workers\n"
            "  you have not acked yet — pick up where you left off.\n\n"
            "**Workspace scoping is automatic**: memory/knowledge tools are scoped to the current "
            "workspace by the runtime. Don't pass workspace_id manually. Main/general chat falls back "
            "to global + system-main memory.\n\n"
            "**Inline memory.search is expected, not stalling.** If you need a fact you don't "
            "have, call it mid-response — that's normal. Don't self-censor or apologise for a "
            "quick lookup; it's part of how you think.\n\n"
            "**Worker delegation**: call the `voxyflow.delegate` MCP tool for research, "
            "multi-step code, web fetch, shell commands, or any heavy AI feature "
            "(voxyflow.ai.standup/brief/health/prioritize/review_code).\n"
            "Required fields: `action` (string) + `description` (string — full self-contained "
            "task brief). Optional: `complexity` (simple|standard|complex), `card_id` (uuid), "
            "`context` (string). No other fields. "
            "The runtime picks the actual worker model — don't name a specific model. "
            "Without this tool call, complex tasks do not execute. "
            "**Default to inline for anything that's instant + local** — only delegate "
            "when you need shell access, web fetching, multi-file code edits, long "
            "reasoning passes, or one of the heavy AI features listed above.\n\n"
            "## 🚫 Not your tools\n"
            "You run inside Voxyflow's chat via Claude Code CLI. You may see Bash/Read/Write/WebSearch — "
            "those belong to the runtime. Use ONLY inline MCP tools + `voxyflow.delegate` + natural language."
        )

    def _build_codex_mcp_delegate_instructions(self) -> str:
        """Delegate instructions for Codex CLI: read-only MCP + voxyflow.delegate tool."""
        return (
            "\n\n## ⚡ Codex dispatcher contract — read-only eyes, worker hands\n"
            "You are the dispatcher, not the worker. Your default reflex for action requests "
            "is to call the `voxyflow.delegate` MCP tool, then give one short confirmation.\n\n"
            "**Your MCP tools are read-only dispatcher tools**: memory.search, memory.get, "
            "knowledge.search, kg.query/timeline/stats, voxyflow.session.read, "
            "voxyflow.sessions.list, voxyflow.workers.list/get_result/read_artifact, "
            "and voxyflow.task.peek. Use them only to inspect state or read worker output.\n\n"
            "**Never do these inline**: implementation, debugging, refactoring, writing files, "
            "shell commands, web search/fetch, research, long analysis, card/workspace/wiki/doc writes, "
            "jobs/autonomy changes, endpoint changes, deletes, or multi-step execution. Delegate them.\n\n"
            "**Trigger rule** — if the user asks you to run, launch, execute, do, find, search, "
            "research, write, code, debug, deploy, summarize, analyze, build, fix, implement, "
            "scrape, crawl, modify a workspace/card, or perform any multi-step task: call exactly "
            "one `voxyflow.delegate` tool at the end of the response. Do not solve it yourself.\n\n"
            "**Worker delegation**: call the `voxyflow.delegate` MCP tool with:\n"
            "- `action` (string, required) — intent keyword (e.g. `implement_auth`, `research_deps`)\n"
            "- `description` (string, required) — fully self-contained task brief including card/workspace context\n"
            "- `complexity` (optional) — `simple` for tiny tasks, `standard` (default), `complex` for "
            "multi-step reasoning or multi-file code\n"
            "The runtime picks the worker model from Worker Classes config; don't name a model.\n\n"
            "## 📖 Reading worker output — the ambient block IS the deliverable\n"
            "The `## Worker activity since your last turn` block in your prompt already contains\n"
            "the worker's full structured `voxyflow.worker.complete` payload: summary, findings,\n"
            "pointers, next_step. **That's the deliverable — read it directly and answer.**\n"
            "Don't call `workers.list` or `workers.get_result` just to find what's already in\n"
            "the block, and don't pretend you're « fetching the result » — you have it.\n"
            "All worker-output operations are actions of ONE MCP tool, `voxyflow.workers`:\n"
            "call it with `action` = `list` / `get_result` / `read_artifact` / `ack_artifact` /\n"
            "`list_unread` (plus `task_id` / `offset` / `length`). There is no separate\n"
            "`workers.ack_artifact` tool — it's `voxyflow.workers` with `action:\"ack_artifact\"`.\n"
            "Use `action:\"get_result\"` (task_id) only for fields the block omitted (long summary,\n"
            "full findings when truncated), and `action:\"read_artifact\"` (task_id, offset, length)\n"
            "when you need verbatim sections. Reading results is dispatcher work; doing new work is\n"
            "not — never re-delegate just to read.\n"
            "After consuming a result (memory/wiki/cards), call `action:\"ack_artifact\"` (task_id)\n"
            "to close the loop and free disk. `action:\"list_unread\"` at session start shows\n"
            "pending deliverables from previous workers.\n\n"
            "## 🚫 Not your tools\n"
            "You run inside Voxyflow's chat via Codex CLI. You may see Codex shell/file/web abilities, "
            "but those are worker responsibilities in Voxyflow. Use only read-only MCP tools, "
            "natural language, and the `voxyflow.delegate` tool."
        )

    def _build_xml_delegate_instructions(self) -> str:
        """Delegate instructions for proxy mode (no native MCP tools available).

        NOTE (2026-05-27): The legacy <delegate> XML markup parser has been removed.
        Proxy mode no longer supports worker delegation. Upgrade to a CLI or API provider
        that exposes native MCP tools (voxyflow.delegate) to re-enable worker dispatch.
        """
        return (
            "\n\n## ⚡ Worker delegation\n"
            "To dispatch background work (research, multi-step code, web fetch, shell), call the "
            "`voxyflow.delegate` tool with required `action` (string), `description` (string), "
            "and optional `complexity` (simple|standard|complex). The runtime picks the right "
            "worker model based on the action keyword. Without this tool call, complex tasks "
            "do not execute.\n\n"
            "**Note**: worker delegation requires native MCP tool support. If you do not have "
            "the `voxyflow.delegate` tool available in your context, inform the user that this "
            "provider does not support worker dispatch and suggest switching to a CLI or API "
            "provider that exposes MCP tools.\n\n"
            "## 🚫 Not your tools\n"
            "You run inside Voxyflow's chat, not in a terminal. You may see Bash/Read/Write/WebSearch — "
            "those belong to the runtime. Use ONLY `voxyflow.delegate` + natural language. "
            "Never claim you can't access tools or that your knowledge is cut off — delegate instead."
        )

    def build_deep_prompt(
        self,
        memory_context: Optional[str] = None,
        chat_level: str = "general",
        workspace: Optional[dict] = None,
        card: Optional[dict] = None,
        workspace_names: Optional[list] = None,
        has_delegation: bool = False,
        is_chat_responder: bool = False,
        native_tools: bool = False,
    ) -> str:
        """Compat wrapper — delegates to build_dispatcher_prompt(tier="deep").

        is_chat_responder=False returns the static base only (no dispatcher tail),
        preserving the legacy supervisor/background-executor escape hatch.
        """
        if not is_chat_responder:
            if chat_level == "card" and card and workspace:
                return self.build_card_prompt(workspace, card)
            if workspace:
                return self.build_workspace_prompt(workspace)
            return self.build_general_prompt()
        return self.build_dispatcher_prompt(
            tier="deep",
            chat_level=chat_level,
            workspace=workspace,
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
        workspace: Optional[dict] = None,
        card: Optional[dict] = None,
    ) -> str:
        """Build system prompt for background worker execution.

        All workers get the same tools and prompt structure regardless of model.
        The model only affects speed/capability, not the role or tool access.
        """
        from app.tools.registry import TOOLS_WORKER
        tool_list = self._build_tool_section(TOOLS_WORKER, chat_level)
        context = self._build_worker_context_section(chat_level, workspace, card)
        worker_rules = self.load_worker()

        web_search_rule = (
            "## Web Search\n"
            "You have access to two web search tools:\n"
            "- `voxyflow.web.search` — our self-hosted SearXNG instance. **Always use this one.**\n"
            "- Built-in `WebSearch` — Claude Code's default (DuckDuckGo). **Never use this.**\n\n"
            "Always call `voxyflow.web.search` for any web search task. Never use the built-in WebSearch tool."
        )

        process_safety_rule = self._build_reserved_ports_rule(role="worker")

        return (
            f"{worker_rules}\n\n"
            f"## Active Role: Worker (Task Executor)\n\n"
            f"## Available Tools\n{tool_list}\n\n"
            f"{web_search_rule}\n\n"
            f"{process_safety_rule}\n\n"
            f"## Context\n{context}"
        )

    def _build_worker_context_section(self, chat_level: str, workspace: Optional[dict], card: Optional[dict]) -> str:
        """Build context section for worker prompts with full IDs and details."""
        parts = []
        if chat_level == "card" and card and workspace:
            parts.append(f"Workspace: {workspace.get('title', '?')} (workspace_id: {workspace.get('id', '?')})")
            if workspace.get("local_path"):
                parts.append(f"Workspace path: {workspace['local_path']} (CWD is set here)")
            parts.append(f"Card: {card.get('title', '?')} (card_id: {card.get('id', '?')})")
            parts.append(f"Card status: {card.get('status', '?')} | Priority: {card.get('priority', '?')}")
            if card.get("description"):
                parts.append(f"Card description: {card['description'][:300]}")
            parts.append(
                f"\nYou are operating on this specific card. "
                f"Use card_id={card.get('id', '?')} for any card operations. "
                f"Use workspace_id={workspace.get('id', '?')} for any workspace operations. "
                f"Do NOT ask the user which card — you already know."
            )
            return "\n".join(parts)
        elif workspace:
            parts.append(f"Workspace: {workspace.get('title', '?')} (workspace_id: {workspace.get('id', '?')})")
            if workspace.get("local_path"):
                parts.append(f"Workspace path: {workspace['local_path']} (CWD is set here)")
            if workspace.get("description"):
                parts.append(f"Description: {workspace['description'][:200]}")
            parts.append(
                f"\nYou are operating in this workspace's context. "
                f"Use workspace_id={workspace.get('id', '?')} for any workspace/card operations. "
                f"Do NOT ask the user which workspace — you already know."
            )
            return "\n".join(parts)
        from app.config import VOXYFLOW_SANDBOX_DIR
        sb_dir = str(VOXYFLOW_SANDBOX_DIR)
        return (
            "Context: Home workspace (default, workspace_id=system-main)\n"
            f"Sandbox: {sb_dir}\n"
            f"CWD is set to {sb_dir} — use relative paths for sandbox files.\n"
            "Voxyflow app codebase: ~/voxyflow/ (do NOT write app files here)."
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


def build_session_handoff_block(
    recent_messages: Optional[list[dict]] = None,
    *,
    gap_minutes: int = 30,
    min_history: int = 4,
) -> str:
    """Render a "where we left off" block when the dispatcher resumes cold.

    *recent_messages* is the persisted session history (ordered oldest →
    newest) — each item should carry ``role``, ``content``, and a
    ``timestamp`` ISO string. Only triggers when the last **conversational**
    assistant turn is older than *gap_minutes* AND history has at least
    *min_history* messages. Silent otherwise.

    Skips ``type=enrichment`` (memory/system injections) and any other
    non-user-visible messages so an autonomy heartbeat or worker
    enrichment doesn't reset the resume anchor and falsely shrink the gap.

    Timestamp parsing goes through ``time_context.parse_iso_to_aware``,
    which interprets naive legacy timestamps as **local** time, not UTC.
    The previous local-as-UTC bug inflated gaps by the local offset.

    Hard cap: last user + last assistant turn, ~400 chars each.
    """
    if not recent_messages or len(recent_messages) < min_history:
        return ""

    from datetime import datetime, timezone
    from app.services.time_context import parse_iso_to_aware

    def _is_conversational(m: dict) -> bool:
        # Only real chat turns count: skip enrichments, system, and any
        # message that looks like an autonomy/worker side-channel.
        if m.get("type") in ("enrichment", "autonomy", "worker_event", "system"):
            return False
        if not m.get("content"):
            return False
        return m.get("role") in ("user", "assistant")

    last_assistant = None
    last_user = None
    for m in reversed(recent_messages):
        if not _is_conversational(m):
            continue
        role = m.get("role")
        if role == "assistant" and last_assistant is None:
            last_assistant = m
        elif role == "user" and last_user is None:
            last_user = m
        if last_assistant and last_user:
            break

    if not last_assistant:
        return ""

    ts = parse_iso_to_aware(last_assistant.get("timestamp"))
    if not ts:
        return ""
    now = datetime.now(timezone.utc)
    delta_sec = (now - ts).total_seconds()
    if delta_sec < gap_minutes * 60:
        return ""

    def _truncate(text: str, n: int = 400) -> str:
        text = (text or "").strip().replace("\n", " ")
        return text if len(text) <= n else text[: n - 1].rstrip() + "…"

    lines: list[str] = [
        f"## Session handoff (resumed after {_fmt_delta_seconds(int(delta_sec))})",
    ]
    user_name = get_personality_service().get_user_name() or "User"
    if last_user:
        lines.append(f"- Last {user_name} said: {_truncate(last_user.get('content', ''))}")
    lines.append(f"- Last you said: {_truncate(last_assistant.get('content', ''))}")
    lines.append(
        "- Treat this as memory, not an unread message — don't apologise for the gap, "
        "just pick up if the user resumes the thread."
    )
    return "\n".join(lines)


_WORKER_BLOCK_MAX_CHARS = 8000
_PER_WORKER_FINDINGS_MAX = 7
_PER_FINDING_MAX_CHARS = 280
_PER_POINTER_MAX_CHARS = 160


def build_worker_events_block(events: list[dict]) -> str:
    """Render completed worker events with their structured deliverable.

    NOT a turn — an ambient context block prepended to the next dispatcher
    prompt. Each event includes the worker's ``voxyflow.worker.complete``
    payload (summary + findings + pointers + next_step) so Voxy sees the
    actual deliverable up front. Without this, Fast-tier dispatchers tend to
    skip ``workers.get_result`` and answer from the one-line summary alone.

    Hard cap _WORKER_BLOCK_MAX_CHARS protects context budget when many
    workers complete in the same window.
    """
    if not events:
        return ""

    lines: list[str] = ["## Worker activity since your last turn"]
    for ev in events[:10]:
        status = (ev.get("status") or "success").lower()
        glyph = _STATUS_GLYPH.get(status, "•")
        intent = ev.get("intent") or "unknown"
        task_id = ev.get("task_id") or "?"
        completion = ev.get("completion") or None

        # Header line — task identity at a glance.
        lines.append(f"- {glyph} {task_id} — {intent} ({status})")

        if completion:
            summary = (completion.get("summary") or "").strip()
            if summary:
                # Keep summary readable but cap to avoid runaway workers
                # blowing the block. Workers are told (WORKER.md §2a) to
                # write 2–4 compressed sentences.
                if len(summary) > 1200:
                    summary = summary[:1180].rstrip() + "…"
                lines.append(f"  Summary: {summary}")

            findings = completion.get("findings") or []
            if findings:
                lines.append(f"  Findings ({len(findings)}):")
                for f in findings[:_PER_WORKER_FINDINGS_MAX]:
                    text = str(f).strip() if not isinstance(f, dict) else _summarize_finding_dict(f)
                    if len(text) > _PER_FINDING_MAX_CHARS:
                        text = text[: _PER_FINDING_MAX_CHARS - 1].rstrip() + "…"
                    lines.append(f"    • {text}")
                if len(findings) > _PER_WORKER_FINDINGS_MAX:
                    extra = len(findings) - _PER_WORKER_FINDINGS_MAX
                    lines.append(
                        f"    • [+{extra} more — use workers.get_result for full list]"
                    )

            pointers = completion.get("pointers") or []
            if pointers:
                ptr_strs: list[str] = []
                for p in pointers[:6]:
                    if isinstance(p, dict):
                        label = (p.get("label") or "section").strip()
                        offset = p.get("offset")
                        length = p.get("length")
                        bits = [f"`{label}`"]
                        if offset is not None:
                            bits.append(f"@{offset}")
                        if length is not None:
                            bits.append(f"+{length}")
                        chunk = " ".join(bits)
                    else:
                        chunk = str(p)
                    if len(chunk) > _PER_POINTER_MAX_CHARS:
                        chunk = chunk[: _PER_POINTER_MAX_CHARS - 1] + "…"
                    ptr_strs.append(chunk)
                lines.append("  Pointers: " + " · ".join(ptr_strs))

            next_step = (completion.get("next_step") or "").strip()
            if next_step:
                if len(next_step) > 400:
                    next_step = next_step[:380].rstrip() + "…"
                lines.append(f"  Next step: {next_step}")
        else:
            # No structured payload (e.g. failure event) — fall back to the
            # one-line summary so the dispatcher at least knows what happened.
            summary = (ev.get("summary_line") or "").strip()
            tail = summary if summary else "use workers.get_result for details"
            lines.append(f"  {tail[:600]}")

    rendered = "\n".join(lines)
    if len(rendered) > _WORKER_BLOCK_MAX_CHARS:
        rendered = (
            rendered[: _WORKER_BLOCK_MAX_CHARS - 100].rstrip()
            + "\n[... worker block truncated — use workers.list / workers.get_result for the rest ...]"
        )
    return rendered


def _summarize_finding_dict(d: dict) -> str:
    """Render a finding dict as one compact line."""
    # Prefer the most natural keys first; fall back to JSON.
    for key in ("text", "summary", "title", "label"):
        if key in d and d[key]:
            return str(d[key]).strip()
    try:
        import json as _json

        return _json.dumps(d, ensure_ascii=False)
    except Exception:
        return str(d)


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
