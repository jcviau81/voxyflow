"""Tool Executor — dispatches parsed tool calls to their registered handlers.

Validates parameters, executes tools, and returns structured results.
"""

import asyncio
import logging
from typing import Optional

from app.tools.registry import ToolRegistry, ToolDefinition, get_registry
from app.tools.response_parser import ParsedToolCall

logger = logging.getLogger(__name__)


class ToolExecutor:
    """Dispatches parsed tool calls to handlers and manages execution."""

    def __init__(self, registry: Optional[ToolRegistry] = None):
        self._registry = registry or get_registry()

    async def execute(self, tool_call: ParsedToolCall, timeout: int = 30) -> dict:
        """Execute a single tool call and return the result."""
        tool_def = self._registry.get(tool_call.name)

        if tool_def is None:
            available = sorted(self._registry.get_names())
            return {
                "success": False,
                "error": f"Unknown tool: {tool_call.name}. Available tools: {', '.join(available[:20])}",
            }

        # Validate required parameters
        validation_error = self._validate_params(tool_def, tool_call.arguments)
        if validation_error:
            return {"success": False, "error": validation_error}

        try:
            result = await asyncio.wait_for(
                tool_def.handler(tool_call.arguments),
                timeout=timeout,
            )
            return result
        except asyncio.TimeoutError:
            logger.error(f"Tool execution timed out: {tool_call.name} (timeout={timeout}s)")
            return {"success": False, "error": f"Tool execution timed out after {timeout}s"}
        except Exception as e:
            logger.error(f"Tool execution failed: {tool_call.name} → {e}")
            return {"success": False, "error": str(e)}

    async def execute_batch(
        self,
        tool_calls: list[ParsedToolCall],
        timeout: int = 30,
    ) -> list[dict]:
        """Execute multiple tool calls sequentially."""
        results = []
        for tc in tool_calls:
            logger.info(f"[ToolExecutor] Executing: {tc.name}({tc.arguments})")
            result = await self.execute(tc, timeout=timeout)
            results.append(result)
        return results

    def _validate_params(self, tool_def: ToolDefinition, arguments: dict) -> Optional[str]:
        """Validate required parameters against the tool's JSON Schema.

        Returns an error message string, or None if valid.
        """
        schema = tool_def.parameters
        required = schema.get("required", [])
        missing = [r for r in required if r not in arguments]

        if missing:
            return (
                f"Missing required parameters for {tool_def.name}: {', '.join(missing)}. "
                f"Required: {required}"
            )

        return None


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_executor: Optional[ToolExecutor] = None


def get_executor() -> ToolExecutor:
    global _executor
    if _executor is None:
        _executor = ToolExecutor()
    return _executor
