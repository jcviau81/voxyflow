# MEMORY — How Voxy Remembers

> The systems that give Voxy persistent memory across conversations and sessions.

---

## Memory Systems Overview

Voxyflow has 4 memory/persistence layers:

| System | Technology | Scope | Purpose |
|--------|-----------|-------|---------|
| **Chat Sessions** | File-based JSON | Per-context | Conversation history |
| **RAG** | ChromaDB | Per-project | Document retrieval, knowledge base |
| **Semantic Memory** | ChromaDB | Global + per-project | Decisions, lessons, preferences |
| **Personality Files** | Markdown | Global | Core identity, operating rules |

---

## Chat History (Session Store)

### How It Works

- **Storage:** `~/.voxyflow/data/sessions/` (JSON files)
- **Format:** One JSON file per chat ID, containing an array of messages
- **Thread safety:** Per-chat_id threading locks for file-level atomicity
- **Writes:** Atomic (temp file + `os.rename()`)

### Chat ID → File Path Mapping

| Chat ID | File Path |
|---------|-----------|
| `general:abc123` | `sessions/general/abc123.json` |
| `project:proj-xyz` | `sessions/project/proj-xyz.json` |
| `card:card-abc` | `sessions/card/card-abc.json` |

### Operations

| Method | What It Does |
|--------|-------------|
| `save_message(chat_id, message)` | Append message to session file |
| `load_session(chat_id)` | Load all messages for a session |
| `get_recent_messages(chat_id, limit)` | Get last N messages |
| `get_history_for_claude(chat_id, limit)` | Format messages for Claude API |
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

ChromaDB-backed retrieval-augmented generation for project knowledge.

- **Embedding model:** `all-MiniLM-L6-v2` (local, no API calls)
- **Persistence:** `~/.voxyflow/chroma/`
- **Graceful degradation:** If `chromadb` not installed, RAG silently disables

### Per-Project Collections

Each project gets 3 ChromaDB collections:

| Collection | Name Pattern | Content |
|-----------|-------------|---------|
| **Documents** | `voxyflow_project_{id}_docs` | Uploaded files (PDF, text, code) |
| **History** | `voxyflow_project_{id}_history` | Conversation history embeddings |
| **Workspace** | `voxyflow_project_{id}_workspace` | Cards, board data, project metadata |

### What Gets Embedded

| Source | When | What |
|--------|------|------|
| Document upload | On `POST /api/projects/{id}/documents` | File chunked into segments, each embedded |
| RAG indexer job | Every 15 minutes (scheduler) | Re-indexes active project data |
| Conversation | During chat (if enabled) | Message content embedded into history collection |

### How Context Is Built

When a user sends a message in a project context:

1. Message text is used as a similarity query against project collections
2. Top-K relevant chunks retrieved from documents, history, workspace
3. Retrieved context injected into the system prompt under a "Relevant Context" section
4. LLM uses this context to give informed, project-aware responses

### Operations

| Method | What It Does |
|--------|-------------|
| `index_document(project_id, doc)` | Chunk and embed document |
| `delete_document(project_id, doc_id)` | Remove from index |
| `query(project_id, text, k)` | Similarity search across collections |
| `enabled` | Property: whether ChromaDB is available |

---

## Semantic Memory (Memory Service)

### How It Works

ChromaDB-backed hierarchical memory with file-based fallback.

### Collections

| Collection | Scope | Content |
|-----------|-------|---------|
| `memory-global` | Cross-project | Universal decisions, preferences, lessons |
| `memory-project-{slug}` | Per-project | Project-specific context and decisions |

### Memory Types

| Type | What It Stores |
|------|---------------|
| `decision` | Architectural or strategic decisions made |
| `preference` | User preferences and working style |
| `lesson` | Lessons learned from past work |
| `fact` | Factual information about the project/user |
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
   - General: project list, Main Board summary
   - Project: project details, cards, wiki
   - Card: card details, agent persona, checklist
7. Add tool definitions (filtered by layer + chat_level)
8. Add RAG context (if project level, if available)
9. Add session history (last 20 or 100 messages)
```

---

## Session Management (Frontend)

### Session Model

| Context | Storage | Max Sessions | Session ID Source |
|---------|---------|-------------|------------------|
| General | `generalSessions[]` | Separate | `general:{uuid}` |
| Project | `sessions[projectId]` | 5 per project | `project:{projectId}::{uuid}` |
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
