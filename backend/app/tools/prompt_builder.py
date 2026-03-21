"""Tool Prompt Builder — generates tool instruction blocks for system prompts.

Builds the text that tells the LLM how to call tools via <tool_call> blocks
and lists the available tools with their parameters.
"""

import logging
from typing import Optional

from app.tools.registry import ToolRegistry, ToolDefinition, get_registry, _LAYER_TOOL_SETS, TOOLS_READ_ONLY

logger = logging.getLogger(__name__)


# Context-based secondary filter (mirrors get_claude_tools logic)
_GENERAL_CONTEXT_TOOLS = {
    "voxyflow.note.add", "voxyflow.note.list",
    "voxyflow.project.create", "voxyflow.project.list", "voxyflow.project.get",
    "voxyflow.health",
    "system.exec", "web.search", "web.fetch",
    "file.read", "file.write", "file.list",
    "git.status", "git.log", "git.diff", "git.branches", "git.commit",
    "tmux.list", "tmux.capture", "tmux.run", "tmux.send", "tmux.new", "tmux.kill",
    "voxyflow.jobs.list", "voxyflow.jobs.create",
    "voxyflow.doc.list", "voxyflow.doc.delete",
}

_PROJECT_EXCLUDED_TOOLS = {"voxyflow.note.add", "voxyflow.note.list"}


class ToolPromptBuilder:
    """Generates tool definition + usage instruction blocks for system prompts."""

    def __init__(self, registry: Optional[ToolRegistry] = None):
        self._registry = registry or get_registry()

    def build_tool_prompt(self, layer: str, chat_level: str = "general") -> str:
        """Generate tool definitions + usage instructions for the system prompt.

        Args:
            layer: "fast", "analyzer", or "deep"
            chat_level: "general", "project", or "card"

        Returns:
            Formatted tool instruction block, or empty string if no tools.
        """
        # Get layer-allowed tools
        layer_tools = self._registry.get_by_layer(layer)

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
            "## Available Tools\n",
            "You have access to the following tools. To use a tool, include a <tool_call> block in your response.\n",
            "### Format",
            "<tool_call>",
            '{"name": "tool.name", "arguments": {"param1": "value1", "param2": "value2"}}',
            "</tool_call>\n",
            "### Rules",
            "- You can call multiple tools in a single response",
            "- After each tool call, you will receive the result in a <tool_result> block",
            "- Use the result to continue your response or call another tool",
            "- Always explain what you're doing before/after tool calls\n",
            "### Tools\n",
        ]

        for t in sorted(tools, key=lambda x: x.name):
            parts.append(f"**{t.name}** — {t.description}")
            props = t.parameters.get("properties", {})
            required = set(t.parameters.get("required", []))
            if props:
                parts.append("Parameters:")
                for pname, pschema in props.items():
                    ptype = pschema.get("type", "any")
                    req_mark = ", required" if pname in required else ""
                    desc = pschema.get("description", "")
                    parts.append(f"  - {pname} ({ptype}{req_mark}): {desc}")
            parts.append("")  # blank line between tools

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
