# Voxyflow — User Interface Guide

> This guide describes each view in Voxyflow: what it shows, how to access it, and the available actions. It is designed for new users, contributors, and the built-in AI assistant (Voxy), which uses it to answer questions like "how do I do X?".

---

## Table of Contents

1. [Navigation and Overall Structure](#1-navigation-and-overall-structure)
2. [Chat View](#2-chat-view)
3. [Kanban View](#3-kanban-view)
4. [Backlog View](#4-backlog-view)
5. [Knowledge View (Documents, Wiki, RAG)](#5-knowledge-view-documents-wiki-rag)
6. [Stats View (projects only)](#6-stats-view-projects-only)
7. [Card Detail Modal](#7-card-detail-modal)
8. [Opportunities and Notifications](#8-opportunities-and-notifications)
9. [WorkerPanel — Worker Monitoring](#9-workerpanel--worker-monitoring)
10. [Settings](#10-settings)
11. [Onboarding](#11-onboarding)
12. [Jobs and Scheduler](#12-jobs-and-scheduler)
13. [Keyboard Shortcuts — Full Reference](#13-keyboard-shortcuts--full-reference)

---

## 1. Navigation and Overall Structure

### Overall Structure (AppShell)

The interface is made up of four fixed areas:

- **Sidebar** — left column, main navigation
- **TabBar** — horizontal bar at the top, open tabs
- **ProjectHeader** — below the TabBar, project title and view tabs
- **Main content** — central area, changes depending on the active view
- **Right drawers** — sliding panels (Opportunities, Notifications)

### Sidebar

The sidebar is the main navigation column, toggled with `Ctrl+B` to show or hide it. On mobile, it appears as an overlay and closes automatically after a tap.

**Sections from top to bottom:**

| Section | Description |
|---------|-------------|
| Logo | Voxyflow — application identifier |
| Home | Link to the main tab (🏠 general view, system project) |
| Jobs | Link to the scheduled tasks management page |
| Projects | Link to the full project list |
| Favorites | Projects marked as favorites, with a colored progress dot |
| New Project | Quick project creation button |
| WorkerPanel | Tree of active sessions and workers (see section 9) |
| Connection status | Colored dot: green = connected, yellow = reconnecting, red = disconnected |
| Footer | Notification bell, theme toggle, Settings, Documentation, Help |

**Progress dots (favorites):**

Each favorite project displays a colored dot indicating overall progress:
- Green: 100% of cards completed
- Yellow: 50% or more completed
- Blue: at least one card completed
- Gray: no cards completed

On hover, a tooltip shows the details: number of cards, done, in progress, percentage.

**Sidebar footer:**
- Bell with red badge = unread notifications (click → Notifications drawer)
- Sun/Moon = light/dark theme toggle
- Gear = Settings
- Book = Documentation
- Question mark = Help

### TabBar

The TabBar is the horizontal bar at the top of the screen. It manages open tabs.

- **Home tab** (🏠) — always present, cannot be closed, gives access to the system project's general views
- **Project tabs** — open when clicking on a project (sidebar or list), closable with `×` or `Ctrl+W`
- **"+" button** — opens the project list to add a tab
- **Opportunities badge** — shows the number of pending AI suggestions
- **Bell** — quick access to notifications

Navigate between tabs: `Ctrl+Tab`

### ProjectHeader

Displayed below the TabBar when a project or Home is active. Contains:
- Emoji and project name (or "Home" for the main tab)
- View tabs depending on context:
  - **Home**: Chat, Kanban, Board, Knowledge
  - **Project**: Chat, Kanban, Board, Knowledge, Stats

Clicking a view tab changes the main content without switching tabs.

---

## 2. Chat View

### Access

- **General chat**: Home tab → "Chat" tab in the ProjectHeader
- **Project chat**: a project tab → "Chat" tab
- **Card chat**: from the Card Detail Modal (center column)

### Chat Contexts — The 3 Levels

The chat context changes automatically based on what is selected in the interface. There is nothing to configure manually.

| Level | Trigger | What Voxy can do |
|-------|---------|------------------|
| **General** | Home tab active, no card selected | Manage Home cards, create projects, web search, system commands, schedule jobs |
| **Project** | A project tab active, no card selected | Everything the general level does + manage project cards, wiki, documents, AI operations (standup, brief, health, prioritize) |
| **Card** | A card is open in the Card Detail Modal | Everything the project level does + targeted task assistance, checklist management, implementation |

Each level has its own isolated history. Switching contexts does not delete the previous history.

### Chat Components

- **MessageList** — list of messages in the active thread, with markdown rendering
- **ChatInput** — input area at the bottom, supports text and slash commands
- **SessionTabBar** — session tabs (up to 5 per context), visible below the header
- **ModePill** — toggle between analysis modes:
  - **Deep** — activates the deep reasoning model
- **SmartSuggestions** — quick suggestion chips, contextual (change depending on the chat level)
- **VoiceInput** — push-to-talk voice input (`Alt+V` held)

### Welcome Message (WelcomePrompt)

Each context displays a tailored welcome message with quick action buttons:

- **General**: "Hey! What are we doing?" + 4 options (Just chatting, Work on a project, Brainstorm, Review tasks)
- **Project**: project name + status (X in progress, Y todo) + resume buttons for in-progress cards
- **Card**: card title + assigned agent + status + priority + targeted actions (Start working, Enrich, Research, Edit, Discuss)

### Sessions

Each context (general, project, card) supports multiple independent sessions, accessible via the SessionTabBar. A session = a separate conversation thread. Limit: 5 sessions per context.

Session actions:
- Create a new session: `/new` or "+" button in the SessionTabBar
- Clear the current session history: `/clear`

### Slash Commands

Type `/` in the input field to trigger a command:

| Command | Action |
|---------|--------|
| `/new` | Creates a new session in the current context |
| `/clear` | Clears the current session history |
| `/help` | Shows help for available commands |
| `/agent [name]` | Changes the active AI agent for the session |
| `/meeting` | Launches a meeting note-taking assistant |
| `/standup` | Generates a standup from the active project's cards |

### Keyboard Shortcuts (Chat View)

| Shortcut | Action |
|----------|--------|
| `Alt+V` (held) | Push-to-Talk — voice input |
| `Ctrl+Shift+F` | Search in chat history |

---

## 3. Kanban View

### Access

- Home tab → "Kanban" in the ProjectHeader
- A project tab → "Kanban"

### What It Shows

A 4-column board representing the card lifecycle:

| Column | Description |
|--------|-------------|
| **Backlog** | Cards on hold, not yet planned |
| **Todo** | Planned tasks, ready to start |
| **In Progress** | Tasks in progress |
| **Done** | Completed tasks |

Each card displays: title, priority, assigned agent, tags, and visual indicators (background color, recurrence badge, checklist progress).

### Main Actions

- **Move a card** — drag & drop between columns, or via status buttons in the Card Detail Modal
- **Open a card** — click a card → Card Detail Modal
- **Create a card** — "+" button in a column header
- **Filter cards** — filter bar at the top: text search, priority, assigned agent, tags
- **Bulk actions** — select multiple cards (checkbox) → move, delete, or assign an agent in bulk
- **Kanban header** — quick action buttons: create a card, launch an AI analysis, sort

---

## 4. Backlog View

### Access

- Home tab → "Backlog" in the ProjectHeader
- A project tab → "Backlog"

### What It Shows

A whiteboard-style space with colored sticky notes. Each note is independent from the Kanban. It is a quick brainstorming space with no imposed workflow.

**6 available colors**: yellow, blue, green, pink, purple, orange.

### Main Actions

- **Create a note** — quick input form at the top (title + color + click "Add")
- **Delete a note** — delete button on the note
- **Promote a note to a Kanban card** — "Promote" button on the note → transforms the sticky note into a full Kanban card in the "Idea" column
- **Filter notes** — same filter bar as the Kanban (search, priority, agent, tags)

---

## 5. Knowledge View (Documents, Wiki, RAG)

### Access

- Home tab → "Knowledge" in the ProjectHeader
- A project tab → "Knowledge"

### What It Shows

Three tabs for managing the knowledge base:

#### Documents

File upload and management. Supported formats: `.txt`, `.md`, `.pdf`, `.docx`, `.xlsx`.

Actions:
- Drag and drop a file into the upload area, or click to select
- View the list of indexed documents with their status
- Delete a document

Uploaded documents are automatically indexed into the RAG collection for the current context (general or project), allowing Voxy to cite them when answering questions.

#### Wiki

Editable markdown pages, organized by project. Each project has its own wiki.

Actions:
- Create a new page
- Edit an existing page (built-in markdown editor)
- Navigate between pages

#### RAG Status

Vector collection dashboard:
- Number of indexed documents
- Number of chunks
- Collection status (active, empty, indexing)
- Usage statistics

---

## 6. Stats View (projects only)

### Access

A project tab → "Stats" in the ProjectHeader. This view is not available in the Home tab.

### What It Shows

An analytics dashboard for the project, organized into sections:

| Section | Content |
|---------|---------|
| **Progress ring** | Overall progress ring (% of cards completed) |
| **Distribution** | Card distribution by column (Backlog / Todo / In Progress / Done) |
| **Velocity** | Velocity charts over recent periods |
| **Standup** | Auto-generated daily summary. "Generate" button to launch the AI |
| **Brief** | AI-generated executive summary of the project |
| **Health** | Project health score + prioritized recommendations |
| **Priority** | AI-prioritized backlog — cards to tackle first based on dependencies and value |
| **Focus** | Pomodoro statistics — focus time, completed sessions |

The Standup, Brief, Health score, and backlog prioritization are generated on demand via their respective buttons.

---

## 7. Card Detail Modal

### Access

Clicking on any card (Kanban or Backlog) opens the Card Detail Modal.

### What It Shows

**On desktop: 3 side-by-side columns**

| Column | Content |
|--------|---------|
| **Left — Description** | Description editor (CodeMirror), full markdown |
| **Center — Card chat** | Built-in chat, scoped to this card only. Voxy can see the card content |
| **Right — Metadata** | Card configuration sidebar |

**On mobile: 3 tabs** (Description / Chat / Details) to navigate between the same content.

### Metadata Sidebar (right column)

| Element | Description |
|---------|-------------|
| **Title** | Inline editable text field |
| **StatusButtons** | Status buttons: Idea → Todo → In Progress → Done |
| **AgentSelector** | Choose which AI agent is assigned to the card |
| **Tags** | Add/remove free-form tags |
| **Color** | 6 background colors for the card |
| **ProjectPicker** | Move the card to another project |
| **RecurrenceSection** | Set up recurrence: 15min, 30min, hourly, 6hours, daily, weekdays, weekly, biweekly, monthly, or custom cron |
| **ChecklistSection** | Internal task list for the card, with a progress bar |
| **AttachmentsSection** | Drag-and-drop attachments |
| **LinkedFiles** | Linked files (referenced, not uploaded) |
| **DependenciesSection** | Dependencies between cards |
| **RelationsSection** | Typed relations: blocks, blocked_by, relates_to, duplicates |
| **HistorySection** | Audit log — all timestamped modifications |

### Actions in the Modal

- **Archive** — Archive button (icon) → removes the card from the Kanban without deleting it
- **Execute** — Play button → launches an AI worker on the card
- **Close** — `Escape` key or click outside the modal

---

## 8. Opportunities and Notifications

### Opportunities Drawer

**Access**: badge in the TabBar (number of pending suggestions), or via the dedicated button.

**What it shows**: card suggestions automatically generated by the AI. The system analyzes the project context and proposes missing tasks, risks, or actions to take.

**Actions**:
- **Create Card** — directly creates the suggested card in the project
- **Dismiss** — ignores the suggestion

### Notifications Drawer

**Access**: bell in the sidebar footer (with red badge if unread) or bell in the TabBar.

**What it shows**: list of recent events:
- Card created, moved, enriched
- Document indexed
- Focus session completed
- Worker result

**Actions**:
- **Open Card** — directly opens the relevant card
- **View in Opportunities** — switches to the Opportunities drawer
- **Mark all read** — marks all notifications as read
- **Clear all** — clears all notifications

---

## 9. WorkerPanel — Worker Monitoring

### Access

The WorkerPanel is built into the sidebar, below the main navigation section. It is always visible when the sidebar is open.

### What It Shows

A hierarchical tree of ongoing activities:

```
Project A
  └── Session #1
        ├── Worker: [claude] Enriching card "Build auth module"  [2m 14s]  running
        └── Worker: [haiku] Indexing document                   [0m 45s]  done
Project B
  └── Session #2
        └── Worker: [opus] Deep analysis                        [5m 02s]  running
```

For each worker, you can see:
- Emoji indicating the model used
- Action type (enrichment, indexing, analysis, execution...)
- Elapsed time since start
- Status: `running` (in progress), `done` (completed), `failed` (error)

### Worker Actions

- **Steer** — send an instruction to a running worker to guide or correct its work
- **Cancel** — cancel a running worker

---

## 10. Settings

### Access

- Gear icon in the sidebar footer
- Route `/settings`

### What It Shows

Full configuration page, with an internal navigation sidebar on the left and 9 panels:

| Panel | Content |
|-------|---------|
| **Appearance** | Theme (light/dark), font size (small/medium/large) |
| **Personality** | Assistant name, tone, warmth, preferred language. File editor: SOUL.md, USER.md, AGENTS.md, IDENTITY.md |
| **Models** | Configuration of the 2 AI layers: Fast (quick responses), Deep (reasoning). For each layer: provider URL, API key, model |
| **Voice & STT** | Voice recognition configuration (STT engine) |
| **GitHub** | GitHub integration: token, default repo |
| **Workspace** | Workspace settings |
| **Data** | Data export and import (projects, cards, history) |
| **Jobs** | Scheduled task scheduler (alias for the Jobs panel) |
| **About** | Version, system information, licenses |

**Personality panel — editable files**:

| File | Role |
|------|------|
| `SOUL.md` | Core personality of the assistant |
| `USER.md` | Information about the user (preferences, context) |
| `AGENTS.md` | Definition of available AI agents |
| `IDENTITY.md` | Identity and behaviors of the assistant |

---

## 11. Onboarding

### Access

Automatic on first application launch, before access to the main interface. Not manually accessible from the UI once completed (settings can then be changed from Settings).

### What It Shows

Initial configuration form on a single scrollable page:

| Field | Description |
|-------|-------------|
| **Your name** | Used by the assistant to address you |
| **Assistant name** | Name of Voxy (default: "Voxy") |
| **API URL** | LLM backend URL (default: local proxy) |
| **API Key** | API access key |
| **Fast model** | Fast model for short responses |
| **Deep model** | Reasoning model for complex tasks |
| **Theme** | Light or dark |
| **Font size** | Small, Medium, Large |

Once the form is submitted, the application starts and redirects to the main view.

---

## 12. Jobs and Scheduler

### Access

- "Jobs" link in the sidebar
- Route `/jobs`
- "Jobs" panel in Settings

### What It Shows

List of all scheduled tasks (jobs). Each job can be triggered manually or run on a cron schedule.

### Job Types

| Type | Description |
|------|-------------|
| `agent_task` | Free-form instruction sent to the AI agent (the most flexible) |
| `execute_card` | Execution of a specific card via the AI pipeline |
| `execute_board` | Sequential execution of all cards on a board based on selected statuses |
| `reminder` | Reminder at a given time |
| `rag_index` | Automatic document reindexing |
| `github_sync` | Synchronization with a GitHub repository |
| `custom` | Custom job with an arbitrary command |
| `board_run` | Legacy alias for `execute_board` |

### Actions

- **Create** — "New Job" button → form: name, type, cron schedule, parameters
- **Edit** — modify an existing job
- **Delete** — permanently delete a job
- **Run manually** — "Run" button on a job → immediate execution without waiting for the next occurrence

---

## 13. Keyboard Shortcuts — Full Reference

| Shortcut | Action |
|----------|--------|
| `Ctrl+B` | Show / hide the sidebar |
| `Ctrl+K` | Open the command palette |
| `Ctrl+W` | Close the active project tab (not applicable to the Home tab) |
| `Ctrl+Tab` | Navigate to the next tab |
| `Alt+V` (held) | Push-to-Talk — voice input in chat |
| `Ctrl+Shift+F` | Search in the active chat history |
| `?` | Open the keyboard shortcuts modal (full list) |
| `Escape` | Close the active modal or drawer |

> Press `?` from any view to display the full list of shortcuts available in the current context.

---

_Guide generated for Voxyflow — April 2026._
