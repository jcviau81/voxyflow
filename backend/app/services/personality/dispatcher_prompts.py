"""Dispatcher / autonomy system prompt builders (DispatcherPromptsMixin)."""

import logging
from typing import Optional

logger = logging.getLogger(__name__)

# NOTE: TONE/WARMTH/LANGUAGE modifiers + build_system_prompt() are NOT on the
# dispatcher path — they serve the worker/agent path (worker_prompts.py
# build_agent_prompt) and are re-exported by personality_service. Keep them.
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


class DispatcherPromptsMixin:
    """build_system_prompt + dispatcher/fast/deep/autonomy prompt builders."""

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
            style = "Deep tier — thoughtful, precise, depth when helpful."
        else:
            style = "Fast tier — respond briefly (1–3 sentences)."
        # The inline-vs-delegate boundary lives ONCE in the delegate core rules
        # (and DISPATCHER.md) — keep this header to tier/mode/style only.
        init_block = (
            f"\n\n## Dispatcher ({tier}) — {mode_label}\n"
            f"{style} Match the user's language."
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
            tail += self._build_proxy_delegate_instructions()
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
            "**This REPLACES the interactive Decision Table's confirmation rows.** Those "
            "confirmations protect a present user; here no user is present — the directive is "
            "the only authority, and anything it doesn't authorize is a no-op."
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
