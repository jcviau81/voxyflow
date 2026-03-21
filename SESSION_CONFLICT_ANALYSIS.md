# Session Conflict Analysis — Voxyflow Multi-Chat

**Analyzed:** 2026-03-21  
**Files reviewed:** `claude_service.py`, `session_store.py`, `memory_service.py`, `chat_orchestration.py`, `main.py`, `ChatService.ts`, `ChatWindow.ts`

---

## Summary

The session isolation architecture is **fundamentally sound** — chat_ids are properly namespaced (`general:*`, `project:*`, `card:*`) and the file-based session store maps these to separate files. However, there are **several real concurrency bugs** and a few edge cases that could cause cross-context contamination.

---

## Issue 1: Double User Message in History (Fast + Deep Parallel Streams)

**Severity:** 🔴 CRITICAL  
**File:** `backend/app/services/claude_service.py` — lines 381, 439  

### Problem

When `chat_deep_stream()` is called (deep_enabled=True mode), it calls `_append_and_persist(chat_id, "user", user_message)` at line 439. But looking at `chat_orchestration.py`, the orchestrator's `handle_message()` calls EITHER `_run_fast_layer` OR `_run_deep_chat_layer` — **never both simultaneously for chat output**.

However, the **`chat_deep_supervisor()`** method (lines 482-540) reads `self._get_history(chat_id)` which shares the **same** `_histories[chat_id]` list that was just written to by `chat_fast_stream()`. The supervisor doesn't call `_append_and_persist` for the user message (correct), but it does:

```python
eval_messages = [*recent, {"role": "user", "content": user_message}]
```

This means the user message appears **twice** in `eval_messages`: once from `history` (persisted by `chat_fast_stream`) and once explicitly added. This is a design choice, not a bug — BUT if the supervisor method were to run concurrently with the fast stream before `_append_and_persist` completes, the history could be inconsistent.

**Actual Critical Issue:** In the old 3-layer mode (if both fast and deep were ever called on the same chat_id), `chat_fast_stream` at line 381 and `chat_deep_stream` at line 439 would BOTH call `_append_and_persist(chat_id, "user", user_message)`, resulting in the user message appearing **twice** in the session file and in-memory history.

The current orchestrator prevents this (Fast XOR Deep), but there's no guard in `ClaudeService` itself.

### Recommended Fix

Add a guard in `_append_and_persist` or use a per-chat_id lock:

```python
def _append_and_persist(self, chat_id: str, role: str, content: str, ...):
    history = self._get_history(chat_id)
    # Guard: don't append duplicate consecutive messages
    if history and history[-1].get("role") == role and history[-1].get("content") == content:
        return
    history.append({"role": role, "content": content})
    ...
```

---

## Issue 2: No Async Locking on `_histories` Dict

**Severity:** 🔴 CRITICAL  
**File:** `backend/app/services/claude_service.py` — lines 288-310  

### Problem

`_histories` is a plain `dict`. Multiple async tasks can interleave operations on it:

1. **`get_history()`** (line 288): Checks `if chat_id not in self._histories`, then loads from disk. If two async tasks call this simultaneously for the same chat_id before either completes, both will load from disk and the second will overwrite the first's in-memory state (losing any messages appended by the first).

2. **`_append_and_persist()`** (line 299): Does `history.append()` which is safe for Python lists (GIL protects the append), BUT `session_store.save_message()` reads the full file, appends, and writes — if two persists race, messages can be **lost** because both read the same base state.

```python
# session_store.py line 38-53:
def save_message(self, chat_id: str, message: dict):
    path = self._get_session_path(chat_id)
    messages = self.load_session(chat_id)    # ← reads file
    messages.append(message)                  # ← appends locally
    with open(path, "w") as f:               # ← writes ALL messages
        json.dump(...)                        # If another save_message runs
                                              # between load and write, its
                                              # message is LOST
```

### Scenario

1. Analyzer task calls `_append_and_persist("project:abc", "assistant", "card suggestion...")` 
2. Simultaneously, Deep worker finishes and appends to the same chat_id
3. Both load 10 messages from disk
4. Both append their message (now each has 11 messages in memory)
5. First writes [1..10, A] to disk
6. Second writes [1..10, B] to disk — message A is lost

### Recommended Fix

Add an `asyncio.Lock` per chat_id:

```python
import asyncio

class ClaudeService:
    def __init__(self):
        ...
        self._history_locks: dict[str, asyncio.Lock] = {}
    
    def _get_lock(self, chat_id: str) -> asyncio.Lock:
        if chat_id not in self._history_locks:
            self._history_locks[chat_id] = asyncio.Lock()
        return self._history_locks[chat_id]
```

And use file-level locking in `session_store.py` (e.g., `fcntl.flock` or atomic writes with temp files).

---

## Issue 3: `session:reset` Doesn't Reset Card Chat

**Severity:** 🟡 MEDIUM  
**File:** `backend/app/main.py` — lines 227-243  

### Problem

The `session:reset` handler derives `chat_id` from `projectId` and `sessionId`, but **never from `cardId`**:

```python
elif msg_type == "session:reset":
    project_id = payload.get("projectId")
    session_id = payload.get("sessionId")

    if project_id:
        chat_id = f"project:{project_id}"
    else:
        chat_id = f"general:{session_id}" if session_id else "general"
    
    _orchestrator.reset_session(chat_id)
```

If a user resets from a card chat context, the card's session (`card:{card_id}`) is **never cleared**. The frontend would need to send `cardId` in the reset payload, and the backend would need to handle it:

```python
card_id = payload.get("cardId")
if card_id:
    chat_id = f"card:{card_id}"
elif project_id:
    chat_id = f"project:{project_id}"
else:
    chat_id = f"general:{session_id}" if session_id else "general"
```

### Recommended Fix

Add `cardId` handling to the `session:reset` handler in `main.py`.

---

## Issue 4: General Chat Without sessionId Falls Back to Global "general"

**Severity:** 🟡 MEDIUM  
**File:** `backend/app/main.py` — line 205  

### Problem

```python
chat_id = f"general:{session_id}" if session_id else "general"
```

If `sessionId` is `undefined`/`None` from the frontend (e.g., first message before ChatWindow initializes), the chat_id becomes just `"general"` — a **single shared session** for all connections without session IDs.

The frontend (`ChatWindow.ts` line 44) initializes `activeSessionId = 'session-1'` immediately, so in practice this is rare. But if the WebSocket reconnects or if `sendMessage()` is called before `activeSessionId` is set, messages could land in the global "general" bucket.

### Evidence from Frontend

`ChatService.ts` line 218:
```typescript
sendMessage(content: string, projectId?: string, cardId?: string, sessionId?: string): Message {
```

The `sessionId` parameter is optional. Voice transcripts (line 198) pass `this.activeSessionId`, which is always set. But `sendSystemInit()` (line 236) has a fallback chain:
```typescript
sessionId: sessionId || this.activeSessionId || undefined
```

If both are falsy, `sessionId` would be `undefined` → backend gets no sessionId → chat_id = "general".

### Recommended Fix

Make `sessionId` required in the WebSocket protocol, or generate a UUID on the backend if missing:

```python
session_id = payload.get("sessionId") or str(uuid4())
```

---

## Issue 5: Memory Service is NOT Scoped Per Chat Context

**Severity:** 🟡 MEDIUM  
**File:** `backend/app/services/memory_service.py` — lines 87-117  

### Problem

`build_memory_context()` takes an optional `project_name` parameter and loads project-specific memory if provided. But memory is **not** scoped by `chat_id` or `card_id` — it's scoped only by project name:

```python
def build_memory_context(self, project_name=None, include_long_term=True, include_daily=True):
```

This means:
1. **General Chat** gets long-term memory + daily logs (no project filter) ✅ correct
2. **Project Chat** gets long-term memory + daily logs + project notes ✅ correct  
3. **Card Chat** gets the same as Project Chat (via `project_name` passed from the project) — but there's **no card-specific memory scoping**

The real issue: **daily logs and long-term memory are always included regardless of which project you're chatting about**. If you're working on Project A and switch to Project B, Voxy still sees Project A's recent daily log entries.

This isn't really a "conflict" but it means the AI might reference information from the wrong project context in its responses.

### Recommended Fix

Consider adding a `card_id` or `context_filter` parameter to `build_memory_context()` to optionally restrict daily logs to entries tagged with the relevant project.

---

## Issue 6: `session_store.save_message()` File Write is Not Atomic

**Severity:** 🟡 MEDIUM  
**File:** `backend/app/services/session_store.py` — lines 38-53  

### Problem

The `save_message` method does read-modify-write without any locking:

```python
def save_message(self, chat_id: str, message: dict):
    path = self._get_session_path(chat_id)
    messages = self.load_session(chat_id)    # READ from disk
    messages.append(message)
    with open(path, "w") as f:              # WRITE (truncates first!)
        json.dump(...)
```

Between the `load_session()` and `open(path, "w")`, another coroutine could:
- Also load the same file (seeing the same state)
- Write its version (with one new message)
- Then this coroutine writes its version, **overwriting the other message**

This directly ties to Issue 2. Both the in-memory history and the disk persistence can lose messages under concurrent access.

### Recommended Fix

Use atomic writes (write to temp file, then `os.rename`) + file locking:

```python
import tempfile

def save_message(self, chat_id: str, message: dict):
    path = self._get_session_path(chat_id)
    # Use file lock for concurrent access
    with self._lock(chat_id):
        messages = self.load_session(chat_id)
        messages.append(message)
        # Atomic write
        fd, tmp = tempfile.mkstemp(dir=path.parent, suffix='.tmp')
        try:
            with os.fdopen(fd, 'w') as f:
                json.dump({...}, f, indent=2, ensure_ascii=False)
            os.rename(tmp, path)
        except:
            os.unlink(tmp)
            raise
```

---

## Issue 7: DeepWorkerPool Uses Separate `task-{id}` Chat IDs (Isolates Correctly)

**Severity:** ✅ LOW (informational — this is actually good)  
**File:** `backend/app/services/chat_orchestration.py` — line 141  

```python
task_chat_id = f"task-{event.task_id}"
```

Worker tasks use unique, ephemeral chat IDs. This means delegated actions **never** pollute the main chat history. This is correct behavior.

However, the worker results are stored in session files like `data/sessions/task-abc123.json` and **never cleaned up**. Over time, this could accumulate thousands of small files.

### Recommended Fix

Add a cleanup mechanism (e.g., delete task session files after 24h, or don't persist them at all since they're ephemeral).

---

## Issue 8: Frontend Session ID is Client-Side Only, Hardcoded Initial Value

**Severity:** 🟢 LOW  
**File:** `frontend/src/components/Chat/ChatWindow.ts` — line 44  

```typescript
private activeSessionId = 'session-1';
```

All users/tabs start with `session-1` as their general chat session ID. If two browser tabs open simultaneously, they share the same `general:session-1` chat history on the backend. This is arguably a feature (sessions persist across refreshes) but could be confusing if multiple people use the app.

### Recommended Fix

For multi-user scenarios, include a user identifier in the session ID. For single-user (current design), this is acceptable.

---

## Issue 9: History Load Limit Mismatch

**Severity:** 🟢 LOW  
**File:** `backend/app/services/claude_service.py` line 293 vs `session_store.py` line 68  

```python
# claude_service.py
self._histories[chat_id] = session_store.get_history_for_claude(chat_id, limit=40)

# session_store.py
def get_history_for_claude(self, chat_id: str, limit: int = 20) -> List[dict]:
```

`get_history` always passes `limit=40`, while the default in session_store is 20. This is fine (40 overrides 20), but the `fast_context_messages` and `deep_context_messages` settings further slice the history:

```python
recent = history[-settings.fast_context_messages:]  # e.g., last 10
```

So the full chain is: load 40 from disk → store in memory → slice last N for API call. This is correct, but note that the in-memory history only ever contains the **last 40 messages**. Older messages exist on disk but are invisible to the API. If a user references something from message #50, the model won't see it.

---

## Issue 10: `chat_deep_supervisor` Adds Synthetic Messages to the Shared History Slice

**Severity:** 🟢 LOW  
**File:** `backend/app/services/claude_service.py` — lines 507-517  

```python
eval_messages = [*recent, {"role": "user", "content": user_message}]
if fast_response:
    eval_messages.append(
        {"role": "assistant", "content": f"[Fast layer's response]: {fast_response}"}
    )
    eval_messages.append(
        {"role": "user", "content": "Evaluate the fast layer's response above..."}
    )
```

This creates a **local copy** (`[*recent, ...]`) so it doesn't mutate the shared history. This is correct. However, the supervisor result is never persisted — meaning its decision (`enrich`/`correct`/`none`) is ephemeral. If the supervisor decides to enrich, the enrichment content flows through a different path (the orchestrator would need to handle it). Currently, `chat_deep_supervisor` is not called in the new architecture (replaced by direct deep streaming + delegate pattern), so this is legacy code.

---

## Architecture Diagram: Chat ID Derivation

```
Frontend sends: { content, projectId?, cardId?, sessionId? }
                          ↓
Backend main.py derives chat_id:
  card_id present?     → "card:{card_id}"
  project_id present?  → "project:{project_id}"  
  session_id present?  → "general:{session_id}"
  nothing?             → "general"        ← potential shared bucket

chat_id maps to file:
  "card:abc123"        → data/sessions/card/abc123.json
  "project:xyz789"     → data/sessions/project/xyz789.json  
  "general:session-1"  → data/sessions/general/session-1.json
  "general"            → data/sessions/general.json  ← shared!
```

---

## Priority Summary

| # | Issue | Severity | Impact |
|---|-------|----------|--------|
| 1 | Double user message if both layers write | 🔴 Critical | Duplicate messages in history |
| 2 | No async locking on `_histories` dict | 🔴 Critical | Lost messages under concurrent access |
| 6 | Non-atomic file writes in session_store | 🟡 Medium | Data loss on concurrent saves |
| 3 | `session:reset` ignores card context | 🟡 Medium | Card sessions can't be reset |
| 4 | Missing sessionId → global "general" bucket | 🟡 Medium | Messages routed to wrong session |
| 5 | Memory not scoped per card/context | 🟡 Medium | Cross-project memory bleed in prompts |
| 7 | Task session files never cleaned up | 🟢 Low | Disk space accumulation |
| 8 | Hardcoded `session-1` ID | 🟢 Low | Multi-tab/multi-user shared state |
| 9 | History load limit mismatch | 🟢 Low | Cosmetic, no actual bug |
| 10 | Legacy supervisor code | 🟢 Low | Dead code, no current impact |
