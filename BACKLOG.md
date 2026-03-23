
## ✅ Recently Completed

### ReactiveCardStore — Single Source of Truth (frontend)
- Centralized Map-based store for all cards (`frontend/src/state/ReactiveCardStore.ts`)
- Components subscribe to global or per-card changes → auto re-render
- Replaces ad-hoc fetch patterns, eliminates stale data and duplicate API calls
- Backward compat: emits legacy eventBus events for unmigrated components

### WebSocket `cards:changed` Broadcast — Live Sync
- Backend broadcasts `cards:changed` to ALL connected WS clients on every card mutation (create/update/move/delete)
- `WSBroadcast` service (`backend/app/services/ws_broadcast.py`) manages connection registry
- Frontend receives → re-fetches project cards → updates ReactiveCardStore → components re-render
- Gives real-time multi-tab sync and instant worker feedback without polling

### Card Execution Pipeline E2E (execute → worker → tools → result → done)
- "Execute" button in card modal → `POST /api/cards/{id}/execute` → builds `[CARD EXECUTION]` prompt
- Prompt sent through 3-layer pipeline as regular chat message
- Workers execute with full tools (web.search, card.update, card.move, file.write, etc.)
- Card auto-moved to "in-progress" on execution start
- Board execution endpoint for bulk sequential card execution

### Auto-Append Worker Results to Card Description
- When a deep worker finishes card execution, result is appended to card description
- Format: `📋 **Execution Result** (timestamp)\n{result}`
- Creates persistent audit trail directly on the card
- Triggers `cards:changed` → ReactiveCardStore re-syncs → modal updates live

### Live Modal Updates During Execution
- `subscribeToCard(id, fn)` on ReactiveCardStore fires on each card mutation
- Combined with `cards:changed` WS broadcast, the card modal re-renders in real-time
- User sees execution progress, result append, and status changes as they happen

### Agent Routing — Keyword-Based Smart Assignment
- 7 agent types: General, Researcher, Coder, Designer, Architect, Writer, QA
- Two-pass routing: pattern+persona keywords → weighted ROUTING_WEIGHTS → confidence scoring
- Auto-routes on card creation if no agent_type specified
- Manual override via `POST /cards/{id}/assign`, preview via `GET /cards/{id}/routing`

---

## Worker Steering (conversational workers)
- Workers are conversational agents, not fire-and-forget
- Two steering paths:
  1. Via main chat: Ember detects worker context, routes `task:steer` event to right worker
  2. Via WorkerPanel: click active worker → opens mini-chat sidebar → direct messages
- Backend: each worker has `task_id` + dedicated queue, `task:steer` WS event injects message as LLM context
- This makes workers fundamentally different from typical background jobs

## Rich Text Editor in Card Modal
- Nice text editor for card description/notes
- Markdown with live preview OR WYSIWYG
- Code highlighting (Monaco or CodeMirror lite)
- Could use CodeMirror 6 (lightweight, tree-sitter based) — already have hljs so syntax highlighting foundation is there

## Code View + Diff Tool in Chat
- Code blocks already rendered with hljs ✅
- Diff tool: show before/after when executor modifies files
  - Option 1: ```diff blocks (hljs diff language already registered)
  - Option 2: side-by-side DiffViewer component (GitHub style)
- Backend generates diff via Python `difflib` when patching files
- Frontend: collapsible diff block with "Expand" → full side-by-side view

## Hidden Features (deferred — not deleted)

These features exist in the codebase but are hidden from the UI until the core flow is solid:

### Project tabs (hidden in ProjectHeader.ts)
- **Stats** (📊) — velocity, burndown, card completion metrics
- **Roadmap** (📅) — timeline view, milestone planning
- **Sprints** (🏃) — sprint planning, backlog grooming

To re-enable: uncomment the relevant lines in `frontend/src/components/Projects/ProjectHeader.ts`

### Slash commands (hidden in SlashCommands.ts)
- **/standup** — AI-generated daily standup summary for current project

To re-enable: uncomment in `frontend/src/components/Chat/SlashCommands.ts`

### Why hidden
JC decision (2026-03-20): Focus on core kanban flow + concrete tools first.
Agile methodology features (sprints, roadmaps, standups, velocity) are premature until
the base interface is fluid and functional. These are not deleted — just deferred.

## Embedding Memory — Multi-Scope Search (2026-03-20 brainstorm)

### Concept
Intégrer le `openclaw-embeddings` service (port 18790/18791) dans Voxyflow avec support multi-scope.

### Scope parameter
- `scope=project:voxyflow` → query seulement la collection du projet
- `scope=project:voxyflow,project:openclaw-embeddings` → cross-projet
- `scope=project:*` → tous les projets
- `scope=global` → mémoire partagée (identité, préférences)
- Default: `scope=project:{current},global`

### Changements requis
1. **embedding_server.py** — ajouter paramètre `scope` qui map vers une collection ChromaDB
   - Créer la collection à la volée si elle existe pas
   - Multi-scope = query chaque collection, merge par score de similarité
2. **openai_proxy.py** — forward le scope param
3. **Voxyflow tools** — `memory.search(query, scope)` et `memory.save(content, scope)`
4. **Auto-scope expansion** — le dispatcher détecte quand une question touche un autre projet

### Data isolation
- Par défaut: un projet voit seulement ses propres embeddings
- Cross-projet: choix explicite (pas un default)
- Global: toujours accessible (préférences, identité)

### Dépend de
- Server-side tool system (implémenté ✅)

## Memory Context Pollution Protection (2026-03-21 brainstorm)

### Problem
Users may talk off-topic in project chats (especially at 4am with beer 🍺). This pollutes project memory/embeddings with irrelevant data.

### Solutions to explore
1. **Chat général as default** — the safe "catch-all" channel, always the landing page
2. **Off-topic detection** — Analyzer detects messages unrelated to project context, suggests moving to general chat
3. **Selective indexing** — not every message gets embedded. Filter: technical/decision content → long-term memory. Small talk → session history only, not indexed
4. **"Wrong chat" button** — UX to move recent messages to the correct chat
5. **Context-based auto-routing** — system determines scope from active chat, user never picks manually

### Design principle
The system must be **tolerant of user error** — don't blame the user, build forgiveness into the architecture. Same as the dispatcher: structural enforcement > behavioral expectations.

### Depends on
- Multi-scope embedding memory (backlog item above)
- Server-side tool system (implemented ✅)
