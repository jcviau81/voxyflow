# Tool Architecture — Server-Side Tool System for Voxyflow

> **Status:** PLAN — not yet implemented  
> **Date:** 2026-03-20  
> **Goal:** Make tools work with ANY model/provider by handling them server-side (prompt injection + response parsing), like OpenClaw does.

---

## Table of Contents

1. [Problem Statement](#1-problem-statement)
2. [Current Architecture Analysis](#2-current-architecture-analysis)
3. [Proposed Architecture](#3-proposed-architecture)
4. [Tool Registry](#4-tool-registry)
5. [Prompt Injection](#5-prompt-injection)
6. [Response Parser](#6-response-parser)
7. [Tool Executor](#7-tool-executor)
8. [Result Injection & Multi-Turn Loop](#8-result-injection--multi-turn-loop)
9. [Model Agnostic Design](#9-model-agnostic-design)
10. [Priority Tools](#10-priority-tools)
11. [Migration Path](#11-migration-path)
12. [Implementation Plan](#12-implementation-plan)

---

## 1. Problem Statement

Voxyflow supports multiple AI backends:

| Path | Client | Tools? |
|------|--------|--------|
| **Native Anthropic SDK** | `anthropic.Anthropic` | ✅ Native `tool_use` blocks |
| **OpenAI-compatible proxy** (port 3457) | `openai.OpenAI` → `claude --print` | ❌ Proxy strips tools, passes text only |
| **Future: Ollama, vLLM, any OpenAI-compat** | `openai.OpenAI` | ❌ No guarantee of tool support |

The proxy at port 3457 wraps Claude Code CLI as an OpenAI-compatible API. It converts everything to text and passes to `claude --print`. **Tools defined in the API request are silently ignored.**

This means:
- Workers dispatched via `<delegate>` blocks that use the proxy path **cannot execute tools**
- The native Anthropic SDK path works fine but requires an API key
- Any non-Anthropic model (Ollama, vLLM, Mistral, etc.) has zero tool access

**Solution:** Handle tools entirely server-side — inject available tools into the system prompt, parse `<tool_call>` blocks from the LLM response, execute them in the backend, and feed results back. The LLM never needs native tool support.

---

## 2. Current Architecture Analysis

### Files & Roles

| File | Role |
|------|------|
| `backend/app/services/claude_service.py` | API dispatcher — routes to Anthropic native or OpenAI proxy. Tool-use loop for native path. |
| `backend/app/services/personality_service.py` | Builds system prompts. Already injects tool lists for workers via `_build_tool_section()`. |
| `backend/app/services/chat_orchestration.py` | WebSocket orchestrator. Parses `<delegate>` blocks, routes to `DeepWorkerPool`. |
| `backend/app/services/event_bus.py` | Per-session async queue for Fast→Worker communication. |
| `backend/app/tools/system_tools.py` | Direct execution: `system.exec`, `web.search`, `web.fetch`, `file.*`, `git.*`, `tmux.*` |
| `backend/app/mcp_server.py` | MCP tool definitions wrapping REST API. `_call_api()` for Voxyflow CRUD via HTTP. |
| `personality/DISPATCHER.md` | Instructions for chat layers: converse + delegate via `<delegate>` blocks. |

### Current Flow (Native Anthropic Path — Working)

```
User → WebSocket → ChatOrchestrator
  → ClaudeService.chat_fast_stream() → Anthropic SDK (streaming, zero tools)
  → Response contains <delegate> block
  → ChatOrchestrator._parse_and_emit_delegates() → EventBus
  → DeepWorkerPool._execute_event()
  → ClaudeService.execute_worker_task()
  → _call_api_anthropic() with tools=True
  → Anthropic SDK tool_use loop (10 rounds max)
  → _call_mcp_tool() → REST API or system_tools handler
  → Result back to user via task:completed WebSocket event
```

### Current Flow (Proxy Path — Broken for Tools)

```
User → WebSocket → ChatOrchestrator
  → ClaudeService.chat_fast_stream() → OpenAI proxy (streaming, zero tools)
  → Response contains <delegate> block
  → DeepWorkerPool._execute_event()
  → ClaudeService.execute_worker_task()
  → _call_api_openai() with tools=True
  → OpenAI proxy IGNORES tool definitions ❌
  → LLM responds with text only, no tool calls
  → Worker fails silently
```

### What Already Exists (Partial)

`personality_service.py` already has `_build_tool_section()` that generates a text list of available tools:

```
- **voxyflow.card.create**(title: string, project_id: string, ...) -- Create a new card
- **system.exec**(command: string, cwd: string, ...) -- Run a shell command
```

This is injected into worker prompts (haiku/sonnet/opus) via `build_worker_prompt()`. But:
- No instruction telling the LLM HOW to call a tool (what format to emit)
- No response parser looking for tool calls in the text
- No execution loop feeding results back

---

## 3. Proposed Architecture

### Core Concept

```
┌──────────────────────────────────────────────────┐
│                  System Prompt                     │
│  [personality] + [context] + [TOOL DEFINITIONS]   │
│  + [TOOL CALL FORMAT INSTRUCTIONS]                │
└──────────────────────────────────────────────────┘
                      ↓
              LLM (any model)
                      ↓
┌──────────────────────────────────────────────────┐
│              LLM Response (text)                   │
│  "I'll create that card for you."                 │
│  <tool_call>                                       │
│  {"name":"voxyflow.card.create",                  │
│   "arguments":{"title":"Fix bug","project_id":"x"}}│
│  </tool_call>                                      │
└──────────────────────────────────────────────────┘
                      ↓
           ToolResponseParser (regex)
                      ↓
           ToolExecutor (dispatch + run)
                      ↓
┌──────────────────────────────────────────────────┐
│              Injected as next message              │
│  <tool_result name="voxyflow.card.create">        │
│  {"success": true, "card": {"id": "abc", ...}}   │
│  </tool_result>                                    │
└──────────────────────────────────────────────────┘
                      ↓
              LLM (continuation)
                      ↓
         "Done! Created card 'Fix bug'."
```

### New Components

| Component | File | Purpose |
|-----------|------|---------|
| `ToolRegistry` | `backend/app/tools/registry.py` | Central registry: name → schema + handler |
| `ToolPromptBuilder` | `backend/app/tools/prompt_builder.py` | Generates tool definitions + instructions for system prompt |
| `ToolResponseParser` | `backend/app/tools/response_parser.py` | Extracts `<tool_call>` blocks from LLM text |
| `ToolExecutor` | `backend/app/tools/executor.py` | Dispatches parsed calls to handlers, manages multi-turn loop |

### Modified Components

| File | Change |
|------|--------|
| `claude_service.py` | Add `_call_api_server_tools()` — new path for server-side tool handling |
| `personality_service.py` | Replace `_build_tool_section()` with `ToolPromptBuilder` |
| `chat_orchestration.py` | No changes needed — delegate pattern stays the same |

---

## 4. Tool Registry

### `backend/app/tools/registry.py`

```python
@dataclass
class ToolDefinition:
    name: str                    # "voxyflow.card.create"
    description: str             # "Create a new card in a project"
    parameters: dict             # JSON Schema for arguments
    handler: Callable            # async function(params: dict) -> dict
    category: str = "voxyflow"   # "voxyflow" | "system" | "web" | "file" | "git" | "tmux"
    dangerous: bool = False      # Requires extra confirmation?

class ToolRegistry:
    _tools: dict[str, ToolDefinition]
    
    def register(self, tool: ToolDefinition) -> None
    def get(self, name: str) -> ToolDefinition | None
    def list_tools(self, categories: set[str] | None = None) -> list[ToolDefinition]
    def get_by_layer(self, layer: str) -> list[ToolDefinition]
```

### Registration

Tools are registered at import time. Two sources:

1. **System tools** — from `system_tools.py` (exec, web, file, git, tmux)
2. **MCP/API tools** — from `mcp_server.py` (voxyflow CRUD via REST)

```python
# In registry.py — auto-registration
def _register_system_tools(registry: ToolRegistry):
    """Register system tools from system_tools.py"""
    from app.tools.system_tools import system_exec, web_search, web_fetch, ...
    
    registry.register(ToolDefinition(
        name="system.exec",
        description="Run a shell command on the local machine",
        parameters={...},
        handler=system_exec,
        category="system",
        dangerous=True,
    ))
    # ... etc

def _register_mcp_tools(registry: ToolRegistry):
    """Register MCP tools from mcp_server.py tool definitions"""
    from app.mcp_server import get_tool_list, _find_tool, _call_api as mcp_call_api
    
    for tool_def in get_tool_list():
        async def handler(params, _td=tool_def):
            return await mcp_call_api(_td, params)
        
        registry.register(ToolDefinition(
            name=tool_def["name"],
            description=tool_def["description"],
            parameters=tool_def["inputSchema"],
            handler=handler,
            category="voxyflow",
        ))
```

### Layer Filtering

Reuses the existing sets from `claude_service.py`:

```python
# Existing sets — moved to registry.py
TOOLS_READ_ONLY = {"voxyflow.health", "voxyflow.note.list", ...}
TOOLS_VOXYFLOW_CRUD = TOOLS_READ_ONLY | {"voxyflow.note.add", ...}
TOOLS_FULL = TOOLS_VOXYFLOW_CRUD | {"system.exec", "file.write", ...}
```

---

## 5. Prompt Injection

### `backend/app/tools/prompt_builder.py`

Generates the tool instruction block to append to system prompts.

```python
class ToolPromptBuilder:
    def __init__(self, registry: ToolRegistry):
        self._registry = registry
    
    def build_tool_prompt(self, layer: str, chat_level: str = "general") -> str:
        """Generate tool definitions + usage instructions for the system prompt."""
        tools = self._registry.get_by_layer(layer)
        # Apply chat_level context filtering (same logic as current)
        tools = self._filter_by_context(tools, chat_level)
        
        if not tools:
            return ""
        
        return self._format_tool_block(tools)
```

### Prompt Format

```markdown
## Available Tools

You have access to the following tools. To use a tool, include a <tool_call> block in your response.

### Format
<tool_call>
{"name": "tool.name", "arguments": {"param1": "value1", "param2": "value2"}}
</tool_call>

### Rules
- You can call multiple tools in a single response
- After each tool call, you will receive the result in a <tool_result> block
- Use the result to continue your response or call another tool
- Always explain what you're doing before/after tool calls

### Tools

**voxyflow.card.create** — Create a new card in a project
Parameters:
  - title (string, required): Card title
  - project_id (string, required): Target project ID
  - description (string): Card description
  - priority (integer): Priority 0-3
  - status (string): idea|todo|in_progress|review|done

**voxyflow.card.list** — List cards in a project
Parameters:
  - project_id (string, required): Project ID
  - status (string): Filter by status

**system.exec** — Run a shell command
Parameters:
  - command (string, required): The command to execute
  - cwd (string): Working directory
  - timeout (integer): Timeout in seconds (max 300)

[... etc for all available tools ...]
```

### Key Design Decisions

1. **XML tags** (`<tool_call>`, `<tool_result>`) — same pattern as the existing `<delegate>` blocks. LLMs already understand this format.
2. **JSON inside tags** — structured, parseable, unambiguous.
3. **Separate from `<delegate>`** — `<delegate>` is for chat-layer→worker dispatch. `<tool_call>` is for worker→backend tool execution. Different concerns.
4. **Parameters documented inline** — the LLM sees the full schema in the prompt so it can construct valid calls.

---

## 6. Response Parser

### `backend/app/tools/response_parser.py`

```python
import re
import json

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
    def parse(self, response_text: str) -> tuple[str, list[ParsedToolCall]]:
        """Parse tool calls from LLM response.
        
        Returns:
            (text_before_tools, list_of_tool_calls)
            
        text_before_tools is the conversational content (everything outside <tool_call> blocks).
        """
        tool_calls = []
        
        for match in TOOL_CALL_PATTERN.finditer(response_text):
            try:
                data = json.loads(match.group(1))
                name = data.get("name", "")
                arguments = data.get("arguments", {})
                
                if not name:
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
```

### Error Handling

- **Invalid JSON**: Log warning, skip that tool call, continue processing others
- **Unknown tool name**: Return error result to LLM so it can self-correct
- **Missing required params**: Return validation error result to LLM
- **No tool calls found**: Return response as-is (pure conversation)

---

## 7. Tool Executor

### `backend/app/tools/executor.py`

```python
class ToolExecutor:
    def __init__(self, registry: ToolRegistry):
        self._registry = registry
    
    async def execute(self, tool_call: ParsedToolCall) -> dict:
        """Execute a single tool call and return the result."""
        tool_def = self._registry.get(tool_call.name)
        
        if tool_def is None:
            return {
                "success": False,
                "error": f"Unknown tool: {tool_call.name}. Available: {self._list_names()}"
            }
        
        # Validate required parameters
        validation_error = self._validate_params(tool_def, tool_call.arguments)
        if validation_error:
            return {"success": False, "error": validation_error}
        
        try:
            result = await tool_def.handler(tool_call.arguments)
            return result
        except Exception as e:
            logger.error(f"Tool execution failed: {tool_call.name} → {e}")
            return {"success": False, "error": str(e)}
    
    async def execute_batch(self, tool_calls: list[ParsedToolCall]) -> list[dict]:
        """Execute multiple tool calls sequentially."""
        results = []
        for tc in tool_calls:
            result = await self.execute(tc)
            results.append(result)
        return results
```

---

## 8. Result Injection & Multi-Turn Loop

### How Results Are Fed Back

After tool execution, results are injected as a user message in the conversation:

```
<tool_result name="voxyflow.card.create">
{"success": true, "id": "card-abc123", "title": "Fix login bug", "status": "todo"}
</tool_result>
```

If multiple tools were called:

```
<tool_result name="voxyflow.project.list">
{"success": true, "projects": [{"id": "p1", "title": "Voxyflow"}, ...]}
</tool_result>

<tool_result name="voxyflow.card.list">
{"success": true, "cards": [{"id": "c1", "title": "Fix bug", "status": "todo"}, ...]}
</tool_result>
```

### Multi-Turn Loop

The server-side tool loop lives in `claude_service.py` as a new method:

```python
async def _call_api_server_tools(
    self,
    model: str,
    system: str,
    messages: list[dict],
    client,                    # OpenAI-compatible client
    layer: str = "fast",
    chat_level: str = "general",
    max_rounds: int = 10,
) -> str:
    """Server-side tool execution loop for providers without native tool support.
    
    1. Call LLM with tools described in system prompt
    2. Parse <tool_call> blocks from response
    3. Execute tools
    4. Inject <tool_result> blocks as next user message
    5. Loop until no more tool calls or max_rounds reached
    6. Return final text response
    """
    from app.tools.prompt_builder import get_prompt_builder
    from app.tools.response_parser import ToolResponseParser
    from app.tools.executor import ToolExecutor, get_executor
    
    parser = ToolResponseParser()
    executor = get_executor()
    
    # Inject tool definitions into system prompt
    tool_prompt = get_prompt_builder().build_tool_prompt(layer, chat_level)
    augmented_system = system + "\n\n" + tool_prompt if tool_prompt else system
    
    api_messages = [{"role": "system", "content": augmented_system}]
    api_messages.extend(messages)
    
    for round_num in range(max_rounds):
        # Call LLM (no native tools — they're in the prompt)
        response = await asyncio.to_thread(
            lambda: client.chat.completions.create(
                model=model,
                max_tokens=self.max_tokens,
                messages=api_messages,
            )
        )
        
        response_text = response.choices[0].message.content or ""
        
        # Parse tool calls
        text_content, tool_calls = parser.parse(response_text)
        
        if not tool_calls:
            # No tool calls — return the text response
            return response_text
        
        # Execute tools
        results = await executor.execute_batch(tool_calls)
        
        # Build result injection
        result_blocks = []
        for tc, result in zip(tool_calls, results):
            result_json = json.dumps(result, default=str, ensure_ascii=False)
            result_blocks.append(
                f'<tool_result name="{tc.name}">\n{result_json}\n</tool_result>'
            )
        
        # Append assistant response + tool results to conversation
        api_messages.append({"role": "assistant", "content": response_text})
        api_messages.append({"role": "user", "content": "\n\n".join(result_blocks)})
        
        logger.info(f"[ServerTools] Round {round_num+1}: {len(tool_calls)} tool calls executed")
    
    logger.warning("_call_api_server_tools: tool loop exceeded max rounds")
    return response_text  # Return last response even if we hit the limit
```

### Streaming Variant

For streaming calls, the approach is:

1. Stream text tokens to the frontend normally
2. Buffer the full response
3. After stream completes, check for `<tool_call>` blocks
4. If found: execute tools, make a second (non-streaming) call with results, yield the final response

This matches the existing `_call_api_stream_anthropic()` pattern for native tool_use.

---

## 9. Model Agnostic Design

### Why This Works With Any Model

| Model | Native Tools? | Server-Side Tools? |
|-------|--------------|-------------------|
| Claude (Anthropic SDK) | ✅ `tool_use` | ✅ (fallback) |
| Claude via proxy (3457) | ❌ | ✅ |
| GPT-4 via OpenAI | ✅ `function_calling` | ✅ (fallback) |
| Llama 3 (Ollama) | ❌ | ✅ |
| Mistral (vLLM) | ❌ | ✅ |
| Any OpenAI-compatible | Maybe | ✅ Always |

The server-side approach works because:

1. **Tools are in the prompt** — any model that can follow instructions can emit `<tool_call>` blocks
2. **XML/JSON is universal** — every competent LLM can produce structured output when instructed
3. **The backend does the work** — parsing, validation, execution, result injection are all Python
4. **No API-level tool support needed** — the model just needs to generate text

### Provider Detection & Routing

```python
# In _call_api():
if client_type == "anthropic":
    # Native SDK → use built-in tool_use (existing path)
    return await self._call_api_anthropic(...)
elif self._supports_native_tools(client):
    # OpenAI-compatible with real tool support → use function_calling
    return await self._call_api_openai(...)
else:
    # Fallback → server-side tool handling
    return await self._call_api_server_tools(...)
```

For now, the heuristic is simple:
- **Anthropic SDK** → native tools
- **OpenAI proxy on 3457** → server-side tools (we KNOW it strips tools)
- **Other OpenAI-compatible** → try native first, fall back to server-side on failure

Later, this can be configured per-provider in `settings.json`:

```json
{
  "models": {
    "fast": {
      "model": "claude-sonnet-4",
      "provider_url": "http://localhost:3457/v1",
      "tool_mode": "server"
    },
    "deep": {
      "model": "claude-opus-4",
      "provider_url": "https://api.anthropic.com",
      "tool_mode": "native"
    }
  }
}
```

---

## 10. Priority Tools

### Tier 1 — Already Implemented (just need registry wiring)

These exist in `system_tools.py` and `mcp_server.py`:

| Tool | Handler | Source |
|------|---------|--------|
| `voxyflow.card.create` | REST API `/api/cards` | mcp_server.py |
| `voxyflow.card.update` | REST API `/api/cards/{id}` | mcp_server.py |
| `voxyflow.card.delete` | REST API `/api/cards/{id}` | mcp_server.py |
| `voxyflow.card.list` | REST API `/api/cards` | mcp_server.py |
| `voxyflow.card.move` | REST API `/api/cards/{id}/move` | mcp_server.py |
| `voxyflow.project.create` | REST API `/api/projects` | mcp_server.py |
| `voxyflow.project.list` | REST API `/api/projects` | mcp_server.py |
| `voxyflow.project.get` | REST API `/api/projects/{id}` | mcp_server.py |
| `voxyflow.note.add` | REST API `/api/cards/unassigned` | mcp_server.py |
| `voxyflow.note.list` | REST API `/api/cards/unassigned` | mcp_server.py |
| `system.exec` | Direct async | system_tools.py |
| `web.search` | Brave API | system_tools.py |
| `web.fetch` | httpx + HTML extract | system_tools.py |
| `file.read` / `file.write` / `file.list` | Direct filesystem | system_tools.py |
| `git.status` / `git.log` / `git.diff` / `git.commit` | Direct git CLI | system_tools.py |
| `tmux.list` / `tmux.run` / `tmux.send` / `tmux.capture` | Direct tmux CLI | system_tools.py |

### Tier 2 — New Tools to Add Later

| Tool | Description | Handler |
|------|-------------|---------|
| `memory.search` | Search conversation memory / long-term memory | New — query memory_service |
| `memory.save` | Save a fact to long-term memory | New — write to memory_service |
| `voxyflow.wiki.create` | Create a wiki page | Already in mcp_server.py |
| `voxyflow.wiki.update` | Update a wiki page | Already in mcp_server.py |
| `voxyflow.ai.standup` | Generate project standup | Already in mcp_server.py |
| `voxyflow.ai.brief` | Generate project brief | Already in mcp_server.py |

---

## 11. Migration Path

### What Changes

| Component | Before | After |
|-----------|--------|-------|
| **Tool definitions** | Scattered in `mcp_server.py` + `system_tools.py` | Centralized in `ToolRegistry` |
| **Tool prompt text** | `_build_tool_section()` in personality_service.py | `ToolPromptBuilder.build_tool_prompt()` |
| **Tool execution (native)** | `_call_mcp_tool()` in claude_service.py | `ToolExecutor.execute()` (wraps same handlers) |
| **Tool execution (proxy)** | ❌ Broken | `_call_api_server_tools()` in claude_service.py |
| **Layer filtering** | `TOOLS_READ_ONLY` / `TOOLS_FULL` sets in claude_service.py | Same sets, moved to `registry.py` |

### What Stays the Same

| Component | Why |
|-----------|-----|
| **`<delegate>` pattern** | Chat layers still delegate to workers — unchanged |
| **ChatOrchestrator** | Still parses `<delegate>`, emits ActionIntent, routes to workers |
| **DeepWorkerPool** | Still consumes events, calls `execute_worker_task()` |
| **EventBus** | No changes |
| **WebSocket protocol** | No changes to frontend |
| **Native Anthropic path** | Still works via `_call_api_anthropic()` — server-side tools are a FALLBACK |
| **MCP server** | Still exposes tools for external MCP clients (Claude Code, Cursor) |
| **Proxy on port 3457** | Zero changes to the proxy itself |

### The `<delegate>` Pattern Integration

The flow remains:

```
Chat Layer (Fast/Deep) → <delegate> block → Orchestrator parses
  → EventBus → DeepWorkerPool → execute_worker_task()
    → _call_api() dispatches to:
       - _call_api_anthropic() (native tools) — existing, unchanged
       - _call_api_openai() (native tools via OpenAI SDK) — existing, unchanged
       - _call_api_server_tools() (NEW — prompt-injected tools) — for proxy/generic providers
```

The ONLY change is adding a third execution path (`_call_api_server_tools`) that handles tools server-side when the provider doesn't support them natively.

---

## 12. Implementation Plan

### Phase 1: Core Infrastructure (4 files, ~300 lines)

**Step 1.1** — Create `backend/app/tools/registry.py`
- `ToolDefinition` dataclass
- `ToolRegistry` class with `register()`, `get()`, `list_tools()`, `get_by_layer()`
- Auto-registration functions for system_tools and mcp_server tools
- Move `TOOLS_READ_ONLY`, `TOOLS_VOXYFLOW_CRUD`, `TOOLS_FULL` from claude_service.py
- Singleton `get_registry()`

**Step 1.2** — Create `backend/app/tools/prompt_builder.py`
- `ToolPromptBuilder` class
- `build_tool_prompt(layer, chat_level)` → returns formatted tool instruction block
- Uses registry to get filtered tool list
- Singleton `get_prompt_builder()`

**Step 1.3** — Create `backend/app/tools/response_parser.py`
- `ParsedToolCall` dataclass
- `ToolResponseParser` class
- `parse(response_text)` → `(text_content, list[ParsedToolCall])`
- Regex: `r'<tool_call>\s*(\{.*?\})\s*</tool_call>'`

**Step 1.4** — Create `backend/app/tools/executor.py`
- `ToolExecutor` class
- `execute(ParsedToolCall)` → `dict` (result)
- `execute_batch(list[ParsedToolCall])` → `list[dict]`
- Parameter validation against JSON Schema
- Singleton `get_executor()`

### Phase 2: Integration into ClaudeService (1 file, ~80 lines)

**Step 2.1** — Add `_call_api_server_tools()` to `claude_service.py`
- Non-streaming multi-turn tool loop
- Uses `ToolPromptBuilder` for prompt injection
- Uses `ToolResponseParser` for response parsing
- Uses `ToolExecutor` for tool execution
- Max 10 rounds (same as existing)

**Step 2.2** — Add `_call_api_stream_server_tools()` to `claude_service.py`
- Streaming variant: stream first response, then tool loop if needed
- Same pattern as `_call_api_stream_anthropic()` tool handling

**Step 2.3** — Update `_call_api()` and `_call_api_stream()` dispatchers
- Add routing logic: if `client_type == "openai"` and provider is proxy → use server-side tools
- Configurable via `settings.json` (`tool_mode: "native" | "server" | "auto"`)

### Phase 3: Cleanup & Consolidation (2 files modified)

**Step 3.1** — Update `personality_service.py`
- Replace `_build_tool_section()` calls with `ToolPromptBuilder` usage
- Remove inline tool set definitions (moved to registry)
- `build_worker_prompt()` now calls `get_prompt_builder().build_tool_prompt()`

**Step 3.2** — Update `claude_service.py`
- Remove `TOOLS_READ_ONLY`, `TOOLS_VOXYFLOW_CRUD`, `TOOLS_FULL` (moved to registry)
- Remove `get_claude_tools()` function (replaced by registry + prompt builder)
- Clean up `_call_mcp_tool()` (now handled by executor)

### Phase 4: Settings UI Integration (optional, later)

**Step 4.1** — Add `tool_mode` to `settings.json` schema
- Per-layer setting: `"fast": {"tool_mode": "server"}` / `"deep": {"tool_mode": "native"}`
- Frontend Settings page: dropdown per model layer

### File Summary

| Action | File | Lines (est.) |
|--------|------|-------------|
| **CREATE** | `backend/app/tools/registry.py` | ~120 |
| **CREATE** | `backend/app/tools/prompt_builder.py` | ~80 |
| **CREATE** | `backend/app/tools/response_parser.py` | ~60 |
| **CREATE** | `backend/app/tools/executor.py` | ~70 |
| **MODIFY** | `backend/app/services/claude_service.py` | +120, -40 |
| **MODIFY** | `backend/app/services/personality_service.py` | +10, -30 |
| **Total** | 4 new + 2 modified | ~420 net new lines |

### Order of Operations

1. **registry.py** — foundation, everything depends on it
2. **prompt_builder.py** — needs registry
3. **response_parser.py** — standalone, no dependencies
4. **executor.py** — needs registry
5. **claude_service.py** — integrate server-side tool loop
6. **personality_service.py** — switch to prompt_builder

Each step is independently testable. The existing native Anthropic path is never broken.

---

## Appendix: Example Full Flow

### User says: "Crée une carte 'Fix login bug' dans le projet Voxyflow"

**1. Chat Layer (Fast/Sonnet) streams:**
> "Je m'en occupe tout de suite!"
> 
> `<delegate>{"action": "create_card", "model": "haiku", "description": "Create card 'Fix login bug' in project Voxyflow"}</delegate>`

**2. Orchestrator parses `<delegate>`, emits to EventBus**

**3. DeepWorkerPool picks up event, calls `execute_worker_task(model="haiku")`**

**4. ClaudeService routes to `_call_api_server_tools()` (proxy path)**

**5. System prompt includes:**
```
## Worker: Haiku (CRUD Executor)
Execute the requested action immediately.

## Available Tools
<tool_call> format instructions...

**voxyflow.card.create** — Create a new card in a project
Parameters:
  - title (string, required)
  - project_id (string, required)
  ...
```

**6. Haiku responds:**
```
<tool_call>
{"name": "voxyflow.card.create", "arguments": {"title": "Fix login bug", "project_id": "proj-voxyflow-123", "priority": 2, "status": "todo"}}
</tool_call>
```

**7. Backend parses, executes via REST API**

**8. Result injected:**
```
<tool_result name="voxyflow.card.create">
{"success": true, "id": "card-abc123", "title": "Fix login bug", "status": "todo", "project_id": "proj-voxyflow-123"}
</tool_result>
```

**9. Haiku responds:**
> "Done! Created card 'Fix login bug' in project Voxyflow with high priority."

**10. Result sent to frontend via `task:completed` WebSocket event**
