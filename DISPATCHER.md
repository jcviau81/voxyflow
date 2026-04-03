# Voxyflow Dispatcher Logic

> Authoritative reference for how the dispatcher routes user intents — what it handles inline vs. what it delegates to workers.

---

## Overview

The dispatcher is the central orchestrator of Voxyflow. When a user message arrives, the dispatcher classifies the intent and decides one of two paths:

1. **Execute inline** — handle it directly, no worker spawned.
2. **Delegate to a worker** — spawn a Claude agent with the appropriate tool tier.

The core decision rule is simple:

> **Lightweight CRUD = direct. Everything else = delegate.**

---

## 1. Inline Direct Tools

These tools are executed **by the dispatcher itself**, synchronously, without spawning a worker process. They are fast, stateless CRUD operations that don't require filesystem access, shell execution, or external API calls.

| Tool | Description |
|---|---|
| `memory.read` | Search long-term memory (global + project) |
| `memory.save` | Store a fact or decision to long-term memory |
| `card.create` | Create a card/task in a project |
| `card.move` | Move a card to a different status column |
| `card.update` | Update a card's title, description, priority, or status |
| `card.list` | List cards for a project |
| `card.get` | Get details of a specific card |
| `card.delete` | Delete a card |
| `card.duplicate` | Duplicate a card |
| `project.list` | List all projects |
| `project.get` | Get project details |
| `project.create` | Create a new project |
| `wiki.list` | List wiki pages |
| `wiki.get` | Read a wiki page |
| `wiki.create` | Create a wiki page |
| `wiki.update` | Update a wiki page |

### Why inline?

- These are pure API calls to Voxyflow's own backend.
- Latency is minimal (single HTTP round-trip).
- No risk of side effects on the host system.
- No need for the full agent tool loop.

---

## 2. Delegated Tools (Worker Dispatch)

These tools require **spawning a worker agent** because they interact with the filesystem, execute commands, access external services, or require multi-step reasoning.

| Tool Category | Tools | Reason for Delegation |
|---|---|---|
| **Web** | `web.search`, `web.fetch` | External network calls, content parsing |
| **Filesystem** | `file.read`, `file.write`, `file.patch`, `file.list` | Direct host filesystem access |
| **Shell** | `system.exec` | Arbitrary command execution on host |
| **Git** | `git.commit`, `git.*` | Repository operations |
| **Tmux** | `tmux.run`, `tmux.new`, `tmux.send`, `tmux.kill` | Terminal session management |
| **AI Analysis** | `ai.standup`, `ai.brief`, `ai.health`, `ai.prioritize`, `ai.review_code` | LLM-powered analysis requiring context gathering |
| **AI Enrichment** | `card.enrich` | AI-powered card enhancement |
| **Documents** | `doc.list`, `doc.delete` | Document management operations |
| **Knowledge** | `knowledge.search` | RAG search over project knowledge base |

### Why delegate?

- These operations may take significant time (builds, searches, multi-file edits).
- They require sandboxed execution with proper error handling.
- They benefit from the full agent reasoning loop (read → think → act → verify).
- Side effects on the host system need the worker's structured lifecycle.

---

## 3. Worker Tier Routing

When the dispatcher decides to delegate, it selects a worker tier based on the complexity of the task and the tools required.

### Tier: Haiku (Lightweight)

- **Model:** Claude Haiku
- **When:** Task involves only CRUD-like operations that still need worker framing (e.g., bulk card operations, simple wiki updates with formatting).
- **Toolset:** Voxyflow API tools only (cards, projects, wiki).
- **Use case:** "Create 5 cards for this feature" — needs a loop but no filesystem access.

### Tier: Sonnet (Standard)

- **Model:** Claude Sonnet
- **When:** Task requires filesystem access, shell commands, code analysis, research, or multi-step reasoning.
- **Toolset:** Full toolset — filesystem, shell, git, tmux, web, AI tools, plus all Voxyflow API tools.
- **Use case:** "Fix the bug in the login page", "Research pricing for X", "Build the new component".

### Tier: Opus (Heavy)

- **Model:** Claude Opus
- **When:** Task requires deep architectural reasoning, comprehensive project briefs, or complex multi-file refactors.
- **Toolset:** Full toolset (same as Sonnet).
- **Use case:** "Design the new authentication system", "Generate a full project brief", "Refactor the entire API layer".

### Routing Summary

```
Task Complexity Assessment:
├── Pure CRUD, single operation     → Inline (no worker)
├── CRUD-only, multi-step           → Haiku worker
├── Filesystem/shell/web required   → Sonnet worker
└── Deep reasoning/architecture     → Opus worker
```

---

## 4. The Decision Rule

```
┌─────────────────────────────────┐
│        User Message Arrives     │
└──────────────┬──────────────────┘
               │
               ▼
┌─────────────────────────────────┐
│   Classify Intent & Tools       │
│   Needed                        │
└──────────────┬──────────────────┘
               │
               ▼
        ┌──────────────┐
        │ Needs shell,  │──── YES ───▶ Delegate to Worker
        │ filesystem,   │             (Sonnet or Opus based
        │ web, git,     │              on complexity)
        │ or tmux?      │
        └──────┬───────┘
               │ NO
               ▼
        ┌──────────────┐
        │ Multi-step    │──── YES ───▶ Delegate to Worker
        │ CRUD or AI    │             (Haiku for CRUD,
        │ analysis?     │              Sonnet for AI)
        └──────┬───────┘
               │ NO
               ▼
        ┌──────────────┐
        │ Simple CRUD   │──── YES ───▶ Execute Inline
        │ operation?    │             (dispatcher handles
        └──────┬───────┘              directly)
               │ NO
               ▼
        ┌──────────────┐
        │ Conversational│──── YES ───▶ Respond Directly
        │ / Q&A?        │             (no tools needed)
        └──────────────┘
```

### Key Principles

1. **Speed over ceremony** — If it's a single card create, don't spin up a worker. Just do it.
2. **Right-size the model** — Don't use Opus for a file read. Don't use Haiku for architecture.
3. **Full toolset for real work** — Workers doing filesystem/shell work always get the complete toolset.
4. **Inline is the fast path** — The dispatcher's inline execution avoids the overhead of worker lifecycle management.

---

## Examples

| User Says | Decision | Tier |
|---|---|---|
| "Create a card called Fix Login Bug" | Inline | — |
| "Move card X to done" | Inline | — |
| "What cards are in progress?" | Inline | — |
| "Create 10 cards from this feature spec" | Delegate | Haiku |
| "Read the package.json file" | Delegate | Sonnet |
| "Fix the CSS on the dashboard" | Delegate | Sonnet |
| "Research the best auth libraries for Node" | Delegate | Sonnet |
| "Design the complete API architecture" | Delegate | Opus |
| "Generate a project brief" | Delegate | Opus |

---

*Last updated: 2025-01-21*
