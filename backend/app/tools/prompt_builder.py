"""Tool Prompt Builder — generates tool instruction blocks for system prompts.

Builds the text that tells the LLM how to call tools via <tool_call> blocks
and lists the available tools with their parameters.

Tool access is role-based (dispatcher vs worker), NOT model-based.
Fast vs deep is purely a model selection — both get the same dispatcher tools.
"""

import functools
import logging
from typing import Optional

from app.tools.registry import ToolRegistry, ToolDefinition, get_registry

logger = logging.getLogger(__name__)


# Context-based secondary filter — narrows the role-based set by chat level.
# "general" context = Main project (system-main) — gets both unassigned aliases AND project card tools.
# NOTE: worker-only tools (system.exec, file.*, git.*, tmux.*, etc.) are NOT
# listed here — they are gated by the role set in the registry, not by context.
_GENERAL_CONTEXT_TOOLS = {
    "voxyflow.card.create_unassigned", "voxyflow.card.list_unassigned",
    "voxyflow.card.create", "voxyflow.card.list", "voxyflow.card.get",
    "voxyflow.card.update", "voxyflow.card.move", "voxyflow.card.archive",
    "voxyflow.project.create", "voxyflow.project.list", "voxyflow.project.get",
    "voxyflow.health",
    "voxyflow.jobs.list", "voxyflow.jobs.create", "voxyflow.jobs.update", "voxyflow.jobs.delete",
    "voxyflow.heartbeat.read", "voxyflow.heartbeat.write",
    "voxyflow.doc.list",
    "memory.search", "knowledge.search", "memory.save",
}

_PROJECT_EXCLUDED_TOOLS: set[str] = set()  # No longer excluding unassigned tools — they're aliases


class ToolPromptBuilder:
    """Generates tool definition + usage instruction blocks for system prompts."""

    def __init__(self, registry: Optional[ToolRegistry] = None):
        self._registry = registry or get_registry()

    @functools.lru_cache(maxsize=32)
    def build_tool_prompt(self, role: str = "dispatcher", chat_level: str = "general") -> str:
        """Generate tool definitions + usage instructions for the system prompt.

        Result is cached per (role, chat_level) — tool definitions are static at runtime.

        Args:
            role: "dispatcher" or "worker" (legacy "fast"/"deep" both map to dispatcher)
            chat_level: "general", "project", or "card"

        Returns:
            Formatted tool instruction block, or empty string if no tools.
        """
        # Get role-allowed tools
        layer_tools = self._registry.get_by_role(role)

        # Apply context filter
        filtered = self._filter_by_context(layer_tools, chat_level)

        if not filtered:
            return ""

        return self._format_tool_block(filtered)

    def build_tool_list_text(self, tool_names: set[str], chat_level: str = "general") -> str:
        """Build a simple tool list (for backward compat with personality_service).

        Returns a plain list without the <tool_call> instructions header.
        """
        tools = [self._registry.get(n) for n in tool_names]
        tools = [t for t in tools if t is not None]
        filtered = self._filter_by_context(tools, chat_level)

        if not filtered:
            return ""

        lines = []
        for t in filtered:
            params = t.parameters.get("properties", {})
            param_str = ", ".join(f'{k}: {v.get("type", "")}' for k, v in params.items())
            lines.append(f'- **{t.name}**({param_str}) -- {t.description}')
        return "\n".join(lines)

    def _filter_by_context(
        self, tools: list[ToolDefinition], chat_level: str
    ) -> list[ToolDefinition]:
        """Apply chat_level context filtering."""
        if chat_level == "general":
            return [t for t in tools if t.name in _GENERAL_CONTEXT_TOOLS]
        elif chat_level == "project":
            return [t for t in tools if t.name not in _PROJECT_EXCLUDED_TOOLS]
        else:
            # card level — all tools pass
            return tools

    def _format_tool_block(self, tools: list[ToolDefinition]) -> str:
        """Format the full tool instruction block with <tool_call> format."""
        parts = [
            "## Tools",
            "Call with:",
            "<tool_call>",
            '{"name": "tool.name", "arguments": {...}}',
            "</tool_call>",
            "",
            "Chain tools when one result feeds the next; call independent tools in parallel. "
            "Use exact IDs from <tool_result> — never invent.",
            "",
            "For an existing card: call card.list, then card.move (status) or card.update (content). "
            "Use card.create only for genuinely new cards.",
            "",
            "### Available",
            "",
        ]

        for t in sorted(tools, key=lambda x: x.name):
            parts.append(f"**{t.name}** — {t.description}")
            props = t.parameters.get("properties", {})
            required = set(t.parameters.get("required", []))
            if props:
                for pname, pschema in props.items():
                    ptype = pschema.get("type", "any")
                    req_mark = "*" if pname in required else ""
                    desc = pschema.get("description", "")
                    suffix = f" — {desc}" if desc else ""
                    parts.append(f"  - {pname}{req_mark} ({ptype}){suffix}")
            parts.append("")

        return "\n".join(parts)


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_prompt_builder: Optional[ToolPromptBuilder] = None


def get_prompt_builder() -> ToolPromptBuilder:
    global _prompt_builder
    if _prompt_builder is None:
        _prompt_builder = ToolPromptBuilder()
    return _prompt_builder
