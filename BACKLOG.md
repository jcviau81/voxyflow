
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
