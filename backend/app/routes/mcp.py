"""MCP (Model Context Protocol) SSE transport endpoints.

GET  /mcp/sse       → SSE stream for MCP web clients
POST /mcp/messages  → Handle incoming MCP JSON-RPC messages
GET  /mcp/tools     → List available MCP tools (JSON, for debugging)

This module provides the HTTP transport layer for the MCP server.
The actual tool logic lives in app/mcp_server.py.
"""

import json
import logging
from typing import AsyncGenerator

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, StreamingResponse

logger = logging.getLogger("voxyflow.mcp.routes")

router = APIRouter(prefix="/mcp", tags=["mcp"])


# ---------------------------------------------------------------------------
# Lazy import helpers — MCP package is optional
# ---------------------------------------------------------------------------

def _get_mcp_server():
    try:
        from app.mcp_server import server
        return server
    except ImportError:
        return None


def _get_tool_list():
    try:
        from app.mcp_server import get_tool_list
        return get_tool_list()
    except ImportError:
        return []


# ---------------------------------------------------------------------------
# SSE Transport
# ---------------------------------------------------------------------------

@router.get("/sse")
async def mcp_sse(request: Request):
    """
    SSE endpoint for MCP web clients (e.g. browser-based Claude, custom UIs).

    The MCP protocol over SSE works as follows:
    1. Client connects to /mcp/sse → receives server-sent events
    2. Client sends JSON-RPC requests to /mcp/messages
    3. Server pushes responses back over the SSE stream

    If the mcp package is not installed, returns a JSON error.
    """
    server = _get_mcp_server()
    if server is None:
        return JSONResponse(
            status_code=503,
            content={
                "error": "MCP server not available",
                "detail": "Install the mcp package: pip install mcp>=1.0.0",
            },
        )

    try:
        from mcp.server.sse import SseServerTransport
    except ImportError:
        return JSONResponse(
            status_code=503,
            content={
                "error": "MCP SSE transport not available",
                "detail": "Install the mcp package: pip install mcp>=1.0.0",
            },
        )

    # The SSE transport handles the full MCP session lifecycle
    sse_transport = SseServerTransport("/mcp/messages")

    async def event_generator() -> AsyncGenerator[str, None]:
        async with sse_transport.connect_sse(
            request.scope, request.receive, request._send
        ) as (read_stream, write_stream):
            init_options = server.create_initialization_options()
            await server.run(read_stream, write_stream, init_options)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # Disable Nginx buffering
        },
    )


@router.post("/messages")
async def mcp_messages(request: Request):
    """
    Handle incoming MCP JSON-RPC messages from SSE clients.

    This endpoint receives POST requests from MCP clients that are
    connected via the SSE stream at /mcp/sse.
    """
    try:
        from mcp.server.sse import SseServerTransport
    except ImportError:
        return JSONResponse(
            status_code=503,
            content={"error": "MCP package not installed"},
        )

    # The SSE transport handles message routing internally
    # This endpoint is called by the transport itself
    sse_transport = SseServerTransport("/mcp/messages")
    await sse_transport.handle_post_message(
        request.scope, request.receive, request._send
    )
    return JSONResponse(content={"ok": True})


# ---------------------------------------------------------------------------
# Debug / introspection
# ---------------------------------------------------------------------------

@router.get("/tools")
async def list_mcp_tools():
    """
    List all MCP tools exposed by this server.

    Returns the tool definitions without the internal HTTP routing metadata.
    Useful for debugging, documentation, and client configuration.
    """
    tools = _get_tool_list()
    return {
        "count": len(tools),
        "tools": tools,
        "transport": {
            "sse": "/mcp/sse",
            "messages": "/mcp/messages",
            "stdio": "python backend/mcp_stdio.py",
        },
    }


@router.get("/status")
async def mcp_status():
    """Check MCP server status and availability."""
    server = _get_mcp_server()
    try:
        import mcp
        mcp_version = getattr(mcp, "__version__", "unknown")
        mcp_available = True
    except ImportError:
        mcp_version = None
        mcp_available = False

    return {
        "mcp_available": mcp_available,
        "mcp_version": mcp_version,
        "server_name": "voxyflow",
        "server_ready": server is not None,
        "tool_count": len(_get_tool_list()),
        "endpoints": {
            "sse": "/mcp/sse",
            "messages": "/mcp/messages",
            "tools": "/mcp/tools",
            "stdio_command": "python backend/mcp_stdio.py",
        },
    }
