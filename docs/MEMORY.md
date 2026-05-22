# MEMORY — How Voxy Remembers

> The systems that give Voxy persistent memory across conversations and sessions.
>
> **Path conventions:** Paths shown use default install locations. Override with `VOXYFLOW_DIR` (app) and `VOXYFLOW_DATA_DIR` (data) — see [SETUP.md](SETUP.md#path-conventions).

---

## Memory Systems Overview

Voxyflow has 4 memory/persistence layers:

| System | Technology | Scope | Purpose |
|--------|-----------|-------|---------|
| **Chat Sessions** | File-based JSON | Per-context | Conversation history |
| **RAG** | ChromaDB | Per-workspace | Document retrieval, knowledge base |
| **Semantic Memory** | ChromaDB | Global + per-workspace | Decisions, lessons, preferences |
| **Personality Files** | Markdown | Global | Core identity, operating rules |

---

## Chat History (Session Store)

### How It Works

- **Storage:** `~/.voxyflow/sessions/` (JSON files)
- **Format:** One JSON file per chat ID, containing an array of messages
- **Thread safety:** Per-chat_id threading locks for file-level atomicity
- **Writes:** Atomic (temp file + `os.rename()`)

### Chat ID → File Path Mapping

| Chat ID | File Path |
|---------|-----------|
| `general:abc123` | `sessions/general/abc123.json` |
| `workspace:proj-xyz` | `sessions/workspace/proj-xyz.json` |
| `card:card-abc` | `sessions/card/card-abc.json` |

### Operations

| Method | What It Does |
|--------|-------------|
| `save_message(chat_id, message)` | Append message to session file |
| `load_session(chat_id)` | Load all messages for a session |
| `get_recent_messages(chat_id, limit)` | Get last N messages |
| `get_history_for_claude(chat_id, limit)` | Format messages for LLM provider |
| `clear_session(chat_id)` | Archive session (timestamped backup), create fresh file |

### Session Lifecycle

1. **Created** — When first message is sent in a context
2. **Accumulated** — Messages appended over time
3. **Cleared/Archived** — User resets session → old file backed up with timestamp
4. **History loaded** — On WebSocket connect, backend can serve recent history

### Context Limits

- Fast layer: last **20 messages** from session
- Deep layer: last **100 messages** from session

---

## RAG System (ChromaDB)

### How It Works

ChromaDB-backed retrieval-augmented generation for workspace knowledge.

- **Embedding model:** `intfloat/multilingual-e5-large` (~470MB, local, no API calls)
- **Persistence:** `~/.voxyflow/chroma/`
- **Relevance cutoff:** `0.82` cosine similarity (calibrated for e5-large score distribution)
- **Cross-lingual:** Native — the model maps 100+ languages into a shared vector space, so FR queries retrieve EN documents and vice versa without translation
- **Graceful degradation:** If `chromadb` not installed, RAG silently disables

### Per-Workspace Collections

Each workspace gets 3 ChromaDB collections:

| Collection | Name Pattern | Content |
|-----------|-------------|---------|
| **Documents** | `voxyflow_workspace_{id}_docs` | Uploaded files (PDF, text, code) |
| **History** | `voxyflow_workspace_{id}_history` | Conversation history embeddings |
| **Workspace** | `voxyflow_workspace_{id}_workspace` | Cards, board data, workspace metadata |

### What Gets Embedded

| Source | When | What |
|--------|------|------|
| Document upload | On `POST /api/workspaces/{id}/documents` | File chunked into segments, each embedded |
| RAG indexer job | Every 15 minutes (scheduler) | Re-indexes active workspace data |
| Conversation | During chat (if enabled) | Message content embedded into history collection |

### How Context Is Built

When a user sends a message in a workspace context:

1. Message text is used as a similarity query against workspace collections
2. Top-K relevant chunks retrieved from documents, history, workspace
3. Chunks below the `0.82` cosine similarity cutoff are discarded
4. Retrieved context injected into the system prompt under a "Relevant Context" section
5. LLM uses this context to give informed, workspace-aware responses

### Operations

| Method | What It Does |
|--------|-------------|
| `index_document(workspace_id, doc)` | Chunk and embed document |
| `delete_document(workspace_id, doc_id)` | Remove from index |
| `query(workspace_id, text, k)` | Similarity search across collections |
| `enabled` | Property: whether ChromaDB is available |

---

## Semantic Memory (Memory Service)

### How It Works

ChromaDB-backed hierarchical memory with file-based fallback.

- **Embedding model:** Same as RAG — `intfloat/multilingual-e5-large`
- **Dedup threshold:** `0.93` cosine similarity (memories scoring above this are considered duplicates and skipped)

### Similarity Thresholds

| Threshold | Value | Purpose |
|-----------|-------|---------|
| RAG relevance cutoff | `0.82` | Minimum score to include a chunk in context |
| Memory dedup | `0.93` | Score above which a new memory is considered duplicate |

### Collections

Collections are keyed by **workspace UUID** (never slug or title — slugs change on
rename and would orphan data). The special `system-main` pseudo-id is used for
the general / main chat when no workspace is selected.

| Collection | Scope | Content |
|-----------|-------|---------|
| `memory-global` | Cross-workspace | Universal decisions, preferences, lessons. **General chat only** — workspace chats never query this collection. |
| `memory-workspace-{workspace_id}` | Per-workspace | Workspace-specific context and decisions. Keyed by the workspace UUID. |
| `memory-workspace-system-main` | General chat | Per-"workspace" store for the general chat pseudo-workspace |

Invariants (see CLAUDE.md §"Workspace Isolation" and
`backend/scripts/smoke_test_isolation.py`):

- `search_memory()` requires explicit `collections=[...]` — there is no silent
  global fallback.
- MCP tools (`memory.search`, `memory.save`, `knowledge.search`) auto-scope via
  the `VOXYFLOW_WORKSPACE_ID` env var set by `cli_backend._build_mcp_config(...)`.
  The schemas **do not expose** `workspace_id` — the LLM cannot override scope.
- `chat_id` is server-canonical (`card:{card_id}`, `workspace:{workspace_id}`,
  `workspace:{SYSTEM_MAIN_WORKSPACE_ID}`). A stale or spoofed frontend `chatId` is
  rejected and replaced.

### Memory Types

| Type | What It Stores |
|------|---------------|
| `decision` | Architectural or strategic decisions made |
| `preference` | User preferences and working style |
| `lesson` | Lessons learned from past work |
| `fact` | Factual information about the workspace/user |
| `context` | Background context for ongoing work |

### Importance Levels

`high`, `medium`, `low` — affects retrieval priority.

### Auto-Extraction

The memory service uses regex patterns to automatically detect and store:
- **Decisions:** "we decided...", "let's go with...", "the approach is..."
- **Bug patterns:** "the bug was...", "root cause..."
- **Tech choices:** "we're using...", "switched to..."
- **Lessons:** "learned that...", "next time..."

### File-Based Fallback

If ChromaDB is unavailable:
- Global memory: `~/voxyflow/personality/MEMORY.md`
- Daily memories: `~/voxyflow/personality/memory/YYYY-MM-DD.md`
- One-time migration from file to ChromaDB when available

---

## Personality Files

Static identity files loaded at session start:

| File | Purpose |
|------|---------|
| `SOUL.md` | Core identity & behavioral contract |
| `IDENTITY.md` | Name, role, gender, mandatory traits |
| `USER.md` | User profile and preferences |
| `AGENTS.md` | Operating directives (7 rules) |
| `DISPATCHER.md` | Chat layer protocol (7 rules) |
| `MEMORY.md` | Long-term memory fallback file |

### Loading & Caching

- **Service:** `PersonalityService`
- **Path:** `~/voxyflow/personality/`
- **Caching:** File mtime-based cache (reloads only when file changes)
- **Settings cache:** `settings.json` also cached by mtime

### How Context Is Built Per Message

For every chat message, the system prompt is assembled:

```
1. Load SOUL.md → core identity
2. Load IDENTITY.md → name, traits
3. Load USER.md → user preferences
4. Load AGENTS.md → operating rules
5. Apply tone/warmth modifiers from settings.json
6. Add chat-level context:
   - General: workspace list, Home cards summary
   - Workspace: workspace details, cards, wiki
   - Card: card details, agent persona, checklist
7. Add tool definitions (filtered by layer + chat_level)
8. Add RAG context (if workspace level, if available)
9. Add session history (last 20 or 100 messages)
```

---

## Session Management (Frontend)

### Session Model

| Context | Storage | Max Sessions | Session ID Source |
|---------|---------|-------------|------------------|
| General | `generalSessions[]` | Separate | `general:{uuid}` |
| Workspace | `sessions[workspaceId]` | 5 per workspace | `workspace:{workspaceId}::{uuid}` |
| Card | `sessions[cardId]` | 5 per card | `card:{cardId}::{uuid}` |

### Session Operations

| Action | Effect |
|--------|--------|
| Create session | New session added (max 5 per context) |
| Switch session | Active session changes, messages reloaded |
| Close session | Session removed (can't close last one) |
| Reset session | Session history cleared, backed up on backend |

### Message Routing

Every message has a `sessionId`. Messages are only displayed if their `sessionId` matches the active session for the current context. This ensures complete isolation between sessions.

---

_Four memory layers. Persistent, contextual, hierarchical._
