#!/usr/bin/env python3
"""Voxyflow MCP Server — stdio transport.

Entry point for CLI-based MCP clients:
  - Claude Code (claude mcp add)
  - Cursor
  - Continue.dev
  - Any MCP-compatible IDE or tool

Usage:
    python backend/mcp_stdio.py

MCP client config (mcp.json or claude_desktop_config.json):
    {
      "mcpServers": {
        "voxyflow": {
          "command": "python",
          "args": ["backend/mcp_stdio.py"],
          "cwd": "/path/to/voxyflow"
        }
      }
    }

The server connects to the Voxyflow REST API at localhost:8000 by default.
Override with: VOXYFLOW_API_BASE=http://localhost:8000
"""

import asyncio
import logging
import os
import sys

# ---------------------------------------------------------------------------
# Logging — write to stderr only (stdout is reserved for MCP protocol)
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.WARNING,  # Keep quiet on stdio; MCP clients read stdout
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    stream=sys.stderr,
)
logger = logging.getLogger("voxyflow.mcp.stdio")

# ---------------------------------------------------------------------------
# Ensure the backend package is importable when run from repo root
# ---------------------------------------------------------------------------

_script_dir = os.path.dirname(os.path.abspath(__file__))
if _script_dir not in sys.path:
    sys.path.insert(0, _script_dir)


async def main() -> None:
    """Run the Voxyflow MCP server over stdio transport."""
    try:
        from mcp.server.stdio import stdio_server
    except ImportError:
        logger.error(
            "mcp package not found. Install it with:\n"
            "  pip install mcp>=1.0.0"
        )
        sys.exit(1)

    try:
        from app.mcp_server import server
    except ImportError as e:
        logger.error(f"Failed to import Voxyflow MCP server: {e}")
        sys.exit(1)

    if server is None:
        logger.error("MCP server could not be initialized (mcp package missing)")
        sys.exit(1)

    api_base = os.environ.get("VOXYFLOW_API_BASE", "http://localhost:8000")
    logger.info(f"Voxyflow MCP stdio server starting (API: {api_base})")

    async with stdio_server() as (read_stream, write_stream):
        init_options = server.create_initialization_options()
        await server.run(read_stream, write_stream, init_options)


if __name__ == "__main__":
    asyncio.run(main())
