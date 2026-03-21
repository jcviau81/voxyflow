"""Tool Response Parser — extracts <tool_call> blocks from LLM text responses.

Parses the LLM's text output to find structured tool call blocks and
separates conversational text from tool invocations.
"""

import json
import logging
import re
from dataclasses import dataclass

logger = logging.getLogger(__name__)

TOOL_CALL_PATTERN = re.compile(
    r'<tool_call>\s*(\{.*?\})\s*</tool_call>',
    re.DOTALL,
)


@dataclass
class ParsedToolCall:
    name: str
    arguments: dict
    raw_match: str      # Original matched text (for replacement)
    start_pos: int
    end_pos: int


class ToolResponseParser:
    """Extracts <tool_call> blocks from LLM response text."""

    def parse(self, response_text: str) -> tuple[str, list[ParsedToolCall]]:
        """Parse tool calls from LLM response.

        Returns:
            (text_content, list_of_tool_calls)

        text_content is the conversational content (everything outside <tool_call> blocks).
        """
        tool_calls: list[ParsedToolCall] = []

        for match in TOOL_CALL_PATTERN.finditer(response_text):
            try:
                data = json.loads(match.group(1))
                name = data.get("name", "")
                arguments = data.get("arguments", {})

                if not name:
                    logger.warning("Empty tool name in <tool_call> block, skipping")
                    continue

                tool_calls.append(ParsedToolCall(
                    name=name,
                    arguments=arguments,
                    raw_match=match.group(0),
                    start_pos=match.start(),
                    end_pos=match.end(),
                ))
            except json.JSONDecodeError as e:
                logger.warning(f"Invalid JSON in <tool_call>: {e}")
                continue

        # Extract text content (everything outside tool_call blocks)
        text_content = TOOL_CALL_PATTERN.sub("", response_text).strip()

        return text_content, tool_calls
