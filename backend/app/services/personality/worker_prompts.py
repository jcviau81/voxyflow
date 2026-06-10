"""Worker / agent prompt builders (WorkerPromptsMixin)."""

from typing import Optional


class WorkerPromptsMixin:
    """Worker prompts — function-based (same tools regardless of model)."""

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
