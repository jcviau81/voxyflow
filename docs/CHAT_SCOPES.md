# CHAT SCOPES — The 3 Chat Levels

> How context changes what Voxy can see, do, and suggest at each level.

---

## Overview

Voxyflow has three chat levels. The level is determined automatically by what the user has selected in the UI.

```
┌─────────────────────────────────────────────┐
│  GENERAL CHAT                               │
│  No project selected. Main tab active.      │
│  Broad scope: all projects, Main Board.     │
├─────────────────────────────────────────────┤
│  PROJECT CHAT                               │
│  Project tab selected. No card selected.    │
│  Scoped to one project and its cards.       │
├─────────────────────────────────────────────┤
│  CARD CHAT                                  │
│  Card selected within a project.            │
│  Focused on one specific card/task.         │
└─────────────────────────────────────────────┘
```

---

## Level Detection

The frontend determines chat level with this logic:

```typescript
getChatLevel(): 'general' | 'project' | 'card' {
    if (selectedCardId) return 'card'
    if (activeTab !== 'main') return 'project'
    return 'general'
}
```

The `chatLevel` is sent with every WebSocket message to the backend.

---

## General Chat

**Trigger:** No project selected. Active tab is `main`.

### What Voxy Can Do
- Create/list/manage Main Board cards
- Create/list/manage projects
- Web search, file operations, system commands
- General conversation
- Job scheduling

### Tools Available (Fast layer)
From `_GENERAL_CONTEXT_TOOLS`:
- `voxyflow.card.create_unassigned`, `voxyflow.card.list_unassigned`
- `voxyflow.project.create`, `voxyflow.project.list`, `voxyflow.project.get`
- `voxyflow.health`
- `system.exec`, `web.search`, `web.fetch`
- `file.read`, `file.write`, `file.list`
- `git.status`, `git.log`, `git.diff`, `git.branches`, `git.commit`
- `tmux.*` (all tmux tools)
- `voxyflow.jobs.list`, `voxyflow.jobs.create`
- `voxyflow.doc.list`, `voxyflow.doc.delete`

### Session Model
- Separate `generalSessions[]` array (not tied to project sessions)
- Chat ID format: `general:{sessionId}`
- Multiple sessions supported (separate from project/card sessions)

### WelcomePrompt

```
🔥 Hey! Qu'est-ce qu'on fait?

[💬 Just chatting]
[🏗️ Work on an existing project]
[💡 Brainstorm a new project]
[📋 Review my tasks]

Or just start typing...
```

### SmartSuggestions
- "Create a new project"
- "What can you help me with?"
- "Show my projects"

---

## Project Chat

**Trigger:** A project tab is active. No card is selected.

### What Voxy Can Do
Everything from General, PLUS:
- Create/list/update/move project cards
- Manage wiki pages
- Manage documents (RAG)
- AI operations (standup, brief, health, prioritize)
- Card enrichment, duplication
- Sprint management

### Tools Available
All tools EXCEPT: `voxyflow.card.create_unassigned`, `voxyflow.card.list_unassigned`
(Main Board tools are excluded — you're in a project context)

### Context Injection
- Project details (title, description, context) injected into system prompt
- Project cards summary included for awareness
- RAG context from project documents if available

### Session Model
- Sessions stored in `appState.sessions[projectId]`
- Up to 5 sessions per project
- Chat ID format: `project:{projectId}`
- Session tab bar visible below header

### WelcomePrompt

```
[emoji] Project Name
📊 X in progress, Y todo

[▶️ Resume: Card 1]     (for each in-progress card)
[📋 Work on an existing task]
[💡 Brainstorm a new task]
[💬 Just chat about the project]

Or just start typing...
```

### SmartSuggestions
- "Create a card"
- "Show the kanban board"
- "What's the project status?"
- "Help me with {ProjectName}"

---

## Card Chat

**Trigger:** A card is selected (within a project).

### What Voxy Can Do
Everything from Project, PLUS:
- Focused context on the specific card
- Card implementation assistance
- Agent-specific guidance (based on assigned agent)
- Checklist management
- Time logging
- Comment management

### Tools Available
ALL tools — no filtering. Card level has full access.

### Context Injection
- Card details (title, description, status, priority, agent, checklist) in system prompt
- Project context included
- Agent persona system prompt if agent assigned
- Dependencies and relations included

### Session Model
- Sessions stored in `appState.sessions[cardId]`
- Up to 5 sessions per card
- Chat ID format: `card:{cardId}`
- Session tab bar visible below header

### WelcomePrompt

```
[emoji] Card Title
Agent: [emoji] Name · Status: status · Priority: N
Card description text

[🚀 Start working on this]
[📝 Enrich details / write PRD]
[🔍 Research before starting]
[✏️ Edit card details]
[💬 Just discuss this task]

Dependencies: [dep1] [dep2]
Tags: #tag1 #tag2
```

### SmartSuggestions
- "Help me implement this"
- "Write tests for this"
- "What are the next steps?"
- "Break this into smaller tasks"

---

## Context Switching

### What Happens When the User Navigates

```
User clicks project tab / card / main tab
    │
    ▼
appState updates:
  - switchTab(tabId)       → changes activeTab, currentProjectId
  - selectCard(cardId)     → changes selectedCardId
  - selectProject(null)    → clears to main
    │
    ▼
EventBus emits:
  - TAB_SWITCH
  - PROJECT_SELECTED
  - CARD_SELECTED
    │
    ▼
ChatWindow responds:
  1. refreshContextComponents()  → destroy/recreate SessionTabBar
  2. reloadMessages()           → clear + reload filtered history
  3. updateChatControls()       → re-render header
  4. smartSuggestions.refresh()  → update suggestion chips
    │
    ▼
getChatLevel() recalculates context
    │
    ▼
shouldRenderMessage() filters messages:
  - General:  message.sessionId === activeGeneralSessionId
  - Project:  message.sessionId === activeChatId(tabId)
  - Card:     message.sessionId === activeChatId(cardId)
    │
    ▼
loadHistoryFromBackend() fetches if empty
    │
    ▼
showWelcomePrompt() renders context-aware welcome
```

### Key Rules
1. **Context is automatic** — determined by `getChatLevel()`, never set manually
2. **Messages are isolated** — each context only shows its own messages
3. **Sessions are per-context** — general, project, and card each have independent sessions
4. **History is persistent** — switching contexts doesn't lose history
5. **Welcome prompt adapts** — shows different content per level

---

## Dispatcher Routing Per Level

The dispatcher (Fast layer) routes intents differently based on chat level:

| Intent | General | Project | Card |
|--------|---------|---------|------|
| "Create a card" | → Ask which project or Main Board | → Create in current project | → Create sub-task or ask |
| "Show status" | → List all projects | → Show project kanban | → Show card details |
| "Search for X" | → Web search or cross-project | → Search within project | → Search related to card |
| "Help me build" | → Ask what to build | → Work on project tasks | → Implement card |

---

## Backend Handling

The backend receives `chatLevel` in the WebSocket `chat:message` payload:

```json
{
  "type": "chat:message",
  "payload": {
    "content": "user message",
    "chatLevel": "general|project|card",
    "projectId": "string|null",
    "cardId": "string|null",
    "sessionId": "string",
    "messageId": "string",
    "layers": { "fast": true, "deep": true, "analyzer": true }
  }
}
```

The backend uses `chatLevel` to:
1. Build the system prompt (personality + context injection)
2. Filter available tools (via `ToolPromptBuilder.build_tool_prompt(layer, chat_level)`)
3. Route the chat to the correct session file
4. Include relevant project/card data in the AI context

---

_Three levels, three contexts, one seamless experience._
