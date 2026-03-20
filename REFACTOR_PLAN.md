I see there's already a detailed refactoring plan in `REFACTOR_PLAN.md`. Having read through the codebase, I can confirm this plan is well-structured and covers the key changes needed. Here's a summary:

## Plan Overview

The existing plan in `/home/jcviau/voxyflow/REFACTOR_PLAN.md` is comprehensive and addresses the target architecture:

### Key Backend Changes
1. **Strip tools from chat layers** — Remove `tool_callback` from `chat_fast_stream()` and `chat_deep_stream()`
2. **Add `model` field to `ActionIntent`** — Routes delegates to haiku/sonnet/opus workers
3. **New `execute_worker_task()` method** — Model-specific execution with appropriate tool sets
4. **Delete dead code** — `_handle_fallback_tool_calls()`, `_flush_tool_events()`

### Prompt Architecture
- **Chat prompts** — Zero tools, just DISPATCHER.md rules
- **Worker prompts** — Three variants: Haiku (CRUD), Sonnet (research), Opus (complex)

### Frontend Updates
- **WorkerPanel** — Add model badge (emoji indicators)
- **ModelStatusBar** — Clarify Fast/Deep are chat models, not worker models

### Migration Path
4 phases, 14 steps, each testable independently.

---

**The plan is ready to execute.** Would you like me to:
1. **Start implementation** of Phase 1 (backend foundation)?
2. **Expand any section** of the plan with more detail?
3. **Create agent-ready task files** for parallel implementation?
llback_tool_calls()`
- `_flush_tool_events()`

---

### 1.2 Extend Delegate Block Schema

**File: `backend/app/services/event_bus.py`**

```python
@dataclass
class ActionIntent:
    task_id: str
    intent_type: str        # "crud_simple", "research", "complex"
    intent: str             
    summary: str
    data: dict = field(default_factory=dict)
    session_id: str = ""
    complexity: str = "simple"
    model: str = "sonnet"   # NEW: "haiku" | "sonnet" | "opus"
```

**File: `backend/app/services/chat_orchestration.py`**

Update `_parse_and_emit_delegates()` (line ~392-430):

```python
# Add model extraction from delegate JSON
model = data.get("model", "sonnet")  # Default to sonnet

# Validate model
if model not in ("haiku", "sonnet", "opus"):
    model = "sonnet"

event = ActionIntent(
    ...
    model=model,
)
```

---

### 1.3 Model-Routed DeepWorkerPool

**File: `backend/app/services/claude_service.py`**

Add new models to `__init__`:
```python
# Line ~280-293: Add worker-specific models
# Haiku worker
self.haiku_model = _resolve_model("claude-haiku-4")
self.haiku_client = self.fast_client  # Can share client
self.haiku_client_type = self.fast_client_type

# Worker Sonnet (same as fast_model for now)
self.worker_sonnet_model = self.fast_model
self.worker_sonnet_client = self.fast_client

# Worker Opus (same as deep_model)
self.worker_opus_model = self.deep_model
self.worker_opus_client = self.deep_client
```

Add new executor method:
```python
async def execute_worker_task(
    self,
    chat_id: str,
    prompt: str,
    model: str,  # "haiku" | "sonnet" | "opus"
    chat_level: str = "general",
    project_context: dict | None = None,
    card_context: dict | None = None,
    project_id: str | None = None,
) -> str:
    """Execute a delegated task with the specified worker model."""
    # Select client/model based on model param
    if model == "haiku":
        client, client_type, model_name = (
            self.haiku_client, self.haiku_client_type, self.haiku_model
        )
        layer = "analyzer"  # Uses TOOLS_VOXYFLOW_CRUD
    elif model == "opus":
        client, client_type, model_name = (
            self.worker_opus_client, self.deep_client_type, self.worker_opus_model
        )
        layer = "deep"  # Uses TOOLS_FULL
    else:  # sonnet (default)
        client, client_type, model_name = (
            self.worker_sonnet_client, self.fast_client_type, self.worker_sonnet_model
        )
        layer = "deep"  # Sonnet worker gets full tools for research
    
    # Build worker-specific prompt
    system_prompt = self.personality.build_worker_prompt(
        model=model,
        chat_level=chat_level,
        project=project_context,
        card=card_context,
    )
    
    return await self._call_api(
        model=model_name,
        system=system_prompt,
        messages=[{"role": "user", "content": prompt}],
        client=client,
        client_type=client_type,
        use_tools=True,
        layer=layer,
        chat_level=chat_level,
    )
```

**File: `backend/app/services/chat_orchestration.py`**

Update `_execute_event()` in DeepWorkerPool (line ~109-176):

```python
async def _execute_event(self, event: ActionIntent) -> None:
    # ... existing start notification ...
    
    # Use model from event (NEW)
    model = event.data.get("model", "sonnet")
    
    result_content = await self._claude.execute_worker_task(
        chat_id=task_chat_id,
        prompt=execution_prompt,
        model=model,  # Route by model
        chat_level=event.data.get("chat_level", "general"),
        project_context=event.data.get("project_context"),
        card_context=event.data.get("card_context"),
        project_id=event.data.get("project_id"),
    )
```

---

### 1.4 Simplifications (Now Possible)

**File: `backend/app/services/chat_orchestration.py`**

**Delete entire methods:**
- `_handle_fallback_tool_calls()` (lines 640-666)
- `_flush_tool_events()` (lines 668-720)

**Simplify `_run_fast_layer()`:**
```python
# Remove these lines:
pending_tool_events: list[dict] = []
def on_tool_executed(...): ...
tool_callback=on_tool_executed,  # Remove from stream call
self._handle_fallback_tool_calls(...)
await self._flush_tool_events(...)
```

---

## 2. Prompt Changes

### 2.1 Chat Prompts — Pure Dispatcher (No Tools)

**File: `backend/app/services/personality_service.py`**

Update `build_fast_prompt()` (line ~421-459):

```python
def build_fast_prompt(self, ...) -> str:
    # ... existing context building ...
    
    # REMOVE: tool_section and _build_tool_section() call
    # REMOVE: lines 441-452 entirely
    
    voice_instructions = (
        "\n\n## Voice Instructions\n"
        "You speak naturally and concisely — this is a voice conversation.\n"
        "Keep responses short (1-3 sentences). Be helpful, direct, friendly.\n"
        "Your personality comes through in HOW you say things.\n"
    )
    
    # Dispatcher rules loaded last (highest priority)
    dispatcher = self.load_dispatcher()
    if dispatcher:
        voice_instructions += "\n\n" + dispatcher
    
    return base + voice_instructions
```

Update `build_deep_prompt()` for `is_chat_responder=True` path (line ~472-525):

```python
# REMOVE: lines 485-495 (read-only tools section)
# KEEP: delegation instructions (lines 498-523)
```

### 2.2 Worker Prompts — Three Variants

**File: `backend/app/services/personality_service.py`**

Add new method:

```python
def build_worker_prompt(
    self,
    model: str,  # "haiku" | "sonnet" | "opus"
    chat_level: str = "general",
    project: dict | None = None,
    card: dict | None = None,
) -> str:
    """Build system prompt for background worker execution."""
    
    if model == "haiku":
        return self._build_haiku_worker_prompt(chat_level, project, card)
    elif model == "opus":
        return self._build_opus_worker_prompt(chat_level, project, card)
    else:
        return self._build_sonnet_worker_prompt(chat_level, project, card)

def _build_haiku_worker_prompt(self, chat_level, project, card) -> str:
    """Haiku: Simple CRUD only. Fast, cheap, no ambiguity."""
    from app.services.claude_service import TOOLS_VOXYFLOW_CRUD
    tool_list = self._build_tool_section(TOOLS_VOXYFLOW_CRUD, chat_level)
    
    return f"""## Worker: Haiku (CRUD Executor)
You execute simple, single-step CRUD operations in Voxyflow.

## Rules
- Execute the requested action immediately using the appropriate tool
- Do NOT ask for confirmation — the user already confirmed via the chat layer
- After executing, respond with a brief (1 sentence) summary
- If the action fails, explain why briefly
- Respond in the same language the user used

## Available Tools
{tool_list}

## Context
{self._build_context_section(chat_level, project, card)}
"""

def _build_sonnet_worker_prompt(self, chat_level, project, card) -> str:
    """Sonnet: Research, web, file analysis. Balanced speed/capability."""
    from app.services.claude_service import TOOLS_FULL
    tool_list = self._build_tool_section(TOOLS_FULL, chat_level)
    
    return f"""## Worker: Sonnet (Research & Analysis)
You execute research tasks, web searches, and file analysis for Voxyflow.

## Rules
- Execute the requested research/analysis task thoroughly
- ALWAYS include source URLs for every fact, price, or recommendation
- ALWAYS include exact values (not ranges) when found
- Format: 'Item — $X.XX at StoreName (url)'
- If you cannot find a real source URL, say 'Source not verified'
- Never fabricate URLs or data — if uncertain, state it clearly
- Include timestamp of research so the user knows how fresh the info is
- Respond in the same language the user used

## Available Tools
{tool_list}

## Context
{self._build_context_section(chat_level, project, card)}
"""

def _build_opus_worker_prompt(self, chat_level, project, card) -> str:
    """Opus: Complex multi-step, architecture, code analysis."""
    from app.services.claude_service import TOOLS_FULL
    tool_list = self._build_tool_section(TOOLS_FULL, chat_level)
    
    return f"""## Worker: Opus (Complex Execution)
You execute complex, multi-step operations that require deep reasoning.

## Rules
- Think through the problem before acting
- Break complex tasks into logical steps
- Execute carefully — you have full tool access including destructive operations
- For code changes: read before writing, explain what you changed
- For file operations: verify paths before writing/deleting
- After executing, provide a thorough summary of what you did
- If any step fails, explain why and what recovery was attempted
- Respond in the same language the user used

## Available Tools
{tool_list}

## Context
{self._build_context_section(chat_level, project, card)}
"""

def _build_context_section(self, chat_level, project, card) -> str:
    """Build context section for worker prompts."""
    if chat_level == "card" and card and project:
        return f"Project: {project.get('title', '?')} | Card: {card.get('title', '?')}"
    elif chat_level == "project" and project:
        return f"Project: {project.get('title', '?')}"
    return "Context: Main Chat"
```

### 2.3 Update DISPATCHER.md

**File: `personality/DISPATCHER.md`**

Replace entire contents:

```markdown
# Dispatcher Rules — Chat Layer

## You Are a Dispatcher, Not an Executor

You are the conversational interface. You CONVERSE and DELEGATE. 
You have ZERO tools. You cannot execute anything directly.

## What You Do

1. **Respond to the user** — naturally, conversationally, helpfully
2. **Decide if action is needed** — does the user want something done?
3. **Dispatch to a worker** — emit a `<delegate>` block with the right model

## The <delegate> Format

When action is needed, end your response with:

<delegate>
{"action": "ACTION", "model": "MODEL", "description": "...", "context": "..."}
</delegate>

### Model Selection

| Task Type | Model | Use When |
|-----------|-------|----------|
| `haiku` | Simple CRUD | create/update/delete card, add note, move card |
| `sonnet` | Research | web search, file analysis, git operations, reading code |
| `opus` | Complex | multi-step tasks, architecture, code writing, destructive ops |

### Examples

```xml
<!-- Simple CRUD → haiku -->
<delegate>
{"action": "create_card", "model": "haiku", "description": "Create card 'Fix login bug' in project X", "context": "priority: high"}
</delegate>

<!-- Research → sonnet -->
<delegate>
{"action": "web_research", "model": "sonnet", "description": "Find best laptop deals under $1000", "context": "User wants specific prices and URLs"}
</delegate>

<!-- Complex → opus -->
<delegate>
{"action": "code_analysis", "model": "opus", "description": "Analyze auth module and propose refactoring plan", "context": "Project: VoxyflowBackend"}
</delegate>
```

## Conversation Pattern

1. User asks for something
2. You acknowledge briefly: "Je vais m'en occuper" / "On it!"
3. End with `<delegate>` block
4. Done — worker handles the rest

## NEVER

- Do NOT try to use tools — you have none
- Do NOT say "I'll do that" and then fail silently
- Do NOT apologize for delegating — it IS the correct behavior
- Do NOT explain what you could do — just do it (dispatch it)
```

---

## 3. Frontend Changes

### 3.1 Mode Pill Clarification

**File: `frontend/src/components/Navigation/ModelStatusBar.ts`**

Update button titles (lines 92-102):

```typescript
fastBtn.title = 'Fast mode — Sonnet responds in chat, workers execute actions';
// ...
deepBtn.title = 'Deep mode — Opus responds in chat, workers execute actions';
```

### 3.2 WorkerPanel Model Badge

**File: `frontend/src/components/RightPanel/WorkerPanel.ts`**

Update `WorkerTask` interface (line ~13-23):

```typescript
interface WorkerTask {
  taskId: string;
  intent: string;
  summary: string;
  status: 'queued' | 'started' | 'executing' | 'completed' | 'failed';
  startedAt: number;
  completedAt?: number;
  result?: string;
  success?: boolean;
  progressMessage?: string;
  model?: 'haiku' | 'sonnet' | 'opus';  // NEW
}
```

Update `TASK_STARTED` listener (line ~49-58):

```typescript
this.tasks.set(payload.taskId, {
  // ... existing fields ...
  model: payload.model || 'sonnet',  // NEW
});
```

Add model badge in `renderTask()` (line ~160-204):

```typescript
private renderTask(task: WorkerTask): HTMLElement {
  const el = createElement('div', {
    className: `worker-task worker-task--${task.status}`,
  });

  // Model badge (NEW)
  const modelBadge = createElement('span', {
    className: `worker-model-badge worker-model-badge--${task.model || 'sonnet'}`,
  }, this.getModelEmoji(task.model));
  el.appendChild(modelBadge);

  // ... rest of existing code ...
}

private getModelEmoji(model?: string): string {
  switch (model) {
    case 'haiku': return '🟡';  // Fast, cheap
    case 'sonnet': return '🔵';  // Balanced
    case 'opus': return '🟣';    // Powerful
    default: return '🔵';
  }
}
```

### 3.3 Add CSS for Model Badge

**File: `frontend/src/styles/components/_worker-panel.scss`** (or equivalent)

```scss
.worker-model-badge {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 20px;
  height: 20px;
  border-radius: 4px;
  font-size: 12px;
  margin-right: 8px;
  
  &--haiku { background: rgba(255, 215, 0, 0.2); }
  &--sonnet { background: rgba(59, 130, 246, 0.2); }
  &--opus { background: rgba(147, 51, 234, 0.2); }
}
```

---

## 4. Migration Steps (Ordered, Testable)

### Phase 1: Backend Foundation (No Breaking Changes)

1. **Add `model` field to `ActionIntent`** — `event_bus.py`
   - Test: Existing code still works (model defaults to "sonnet")

2. **Add `execute_worker_task()` method** — `claude_service.py`
   - Test: Can call with model="haiku"/"sonnet"/"opus", returns expected results

3. **Add `build_worker_prompt()` and variants** — `personality_service.py`
   - Test: Each variant produces expected tool lists

### Phase 2: Worker Routing

4. **Update `_parse_and_emit_delegates()` to extract model field** — `chat_orchestration.py`
   - Test: Delegate JSON with `model: "haiku"` creates ActionIntent with model="haiku"

5. **Update `_execute_event()` to use `execute_worker_task()`** — `chat_orchestration.py`
   - Test: Worker tasks route to correct model

### Phase 3: Strip Tools from Chat

6. **Remove `tool_callback` from `chat_fast_stream()`** — `claude_service.py`
   - Test: Fast layer streams without attempting tool execution

7. **Remove `tool_callback` from `chat_deep_stream()`** — `claude_service.py`
   - Test: Deep layer streams without tool execution

8. **Remove fallback tool handling** — `chat_orchestration.py`
   - Delete `_handle_fallback_tool_calls()`, `_flush_tool_events()`
   - Simplify `_run_fast_layer()`
   - Test: Fast layer works, no tool events emitted

### Phase 4: Prompt Cleanup

9. **Update `build_fast_prompt()` — remove tool section** — `personality_service.py`
   - Test: System prompt contains no tool definitions

10. **Update `build_deep_prompt()` for is_chat_responder — remove tool section** — `personality_service.py`
    - Test: Deep chat system prompt contains no tool definitions

11. **Replace `DISPATCHER.md` with new version** — `personality/DISPATCHER.md`
    - Test: Dispatcher rules mention model selection, not tools

### Phase 5: Frontend

12. **Update `ModelStatusBar` titles** — `ModelStatusBar.ts`
    - Test: Hover shows new explanatory text

13. **Add model field to `WorkerTask` and badge rendering** — `WorkerPanel.ts`
    - Test: Worker tasks show colored emoji badge

14. **Add CSS for model badge** — SCSS file
    - Test: Badges render with correct colors

---

## 5. New/Deleted Files

### New Files
- None (all changes in existing files)

### Deleted Methods
- `chat_orchestration.py`: `_handle_fallback_tool_calls()`
- `chat_orchestration.py`: `_flush_tool_events()`

### Deleted Code Blocks
- `personality_service.py`: Tool section in `build_fast_prompt()` (lines ~441-452)
- `personality_service.py`: Tool section in `build_deep_prompt()` is_chat_responder path (lines ~485-495)

### Modified Files Summary

| File | Changes |
|------|---------|
| `backend/app/services/event_bus.py` | Add `model` field to ActionIntent |
| `backend/app/services/claude_service.py` | Add worker models, `execute_worker_task()`, remove tool params from streaming |
| `backend/app/services/chat_orchestration.py` | Model routing, delete fallback tool handlers |
| `backend/app/services/personality_service.py` | `build_worker_prompt()` + variants, strip tools from chat prompts |
| `personality/DISPATCHER.md` | Complete rewrite with model selection |
| `frontend/src/components/Navigation/ModelStatusBar.ts` | Update button titles |
| `frontend/src/components/RightPanel/WorkerPanel.ts` | Add model badge |
| `frontend/src/styles/...` | Add model badge CSS |

---

## Verification Checklist

After implementation:

- [ ] Fast chat: No tools in system prompt, delegate blocks parse correctly
- [ ] Deep chat: No tools in system prompt, delegate blocks parse correctly  
- [ ] Delegate `model: "haiku"` → Haiku worker with CRUD tools
- [ ] Delegate `model: "sonnet"` → Sonnet worker with full tools
- [ ] Delegate `model: "opus"` → Opus worker with full tools
- [ ] WorkerPanel shows model badge (🟡/🔵/🟣)
- [ ] No tool:executed events from chat layers
- [ ] task:started events include model field
