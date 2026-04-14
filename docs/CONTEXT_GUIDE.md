# Voxyflow — Context & Workflow Guide

> How Voxyflow always knows _what_ you're talking about, and how to make the most of it.

---

## The concept of context

When you talk to Voxy, she is never in a vacuum. She always knows where you are in the interface — and she adapts what she can do, what she sees, and how she responds.

There are three levels of context. The active level is determined automatically based on what you have open in the interface:

```
You are on the Home tab (main tab)
→ GENERAL CONTEXT — Voxy sees all your projects and Home cards, nothing specific.

You have opened a project
→ PROJECT CONTEXT — Voxy sees all the project's cards, the wiki, the history.

You have opened a card
→ CARD CONTEXT — Voxy is focused on that specific task, its content, its agent.
```

**You don't configure anything.** You navigate the interface, and the context follows.

---

## What context changes in practice

### General context — overview

When no project is selected (you are on the **Home** tab):

- Voxy can create projects, list your existing projects, manage Home cards
- She can run web searches, execute system commands
- She schedules tasks (cron jobs, reminders)
- She doesn't "see" the inside of a specific project — if you ask her for info about a project, she has to open it first

**Good for:** Starting a new project, getting a high-level overview, tasks that aren't tied to a specific project.

### Project context — working on a project

When you are in a project's tab:

- Voxy sees all the project's cards (title, status, priority, assigned agent)
- She has access to the project's wiki and documents indexed in RAG
- She can create, edit, and move cards directly
- She can generate a standup, a brief, or a project health analysis
- The project description and context are injected into her system prompt

**Good for:** Managing project tasks, brainstorming, creating cards, getting a status report.

### Card context — executing a task

When you open a specific card:

- Voxy sees the title, description, status, priority, checklist, and comments
- She adapts her personality based on the agent assigned to the card (Coder, Researcher, Writer, etc.)
- She can update the checklist, log time, add comments
- She has access to all tools — this is the most powerful level

**Good for:** Working on a specific task, asking for implementation help, enriching details, pair programming.

---

## Memory is isolated by context

Each context has its own conversation history:

- The conversation in **project A** is not visible in **project B**
- The conversation on the **"Refactor auth" card** is not mixed with the project's conversation
- The **Home** tab has its own conversation, separate from any project

You can have 5 parallel sessions per context (tabs in the chat panel). Histories persist between sessions — you can close the app and pick up your conversation right where you left off.

---

## Practical example: creating a DailyOps project

DailyOps is a typical use case: a project for managing recurring daily tasks — morning standup, weekly review, idea inbox. Here's how to set it up from start to finish.

---

### Step 1 — Create the project (general context)

From the **Home** tab, tell Voxy:

> "Create a project called DailyOps. It's for managing my recurring daily tasks — morning standup, weekly review, idea capture."

Voxy will create the project and take you there. You can also create it manually via the **+** button in the sidebar.

---

### Step 2 — Configure the project context (project context)

Once inside DailyOps, take a moment to describe the project to Voxy. This description is injected into her system prompt with every message:

> "Update the project description: DailyOps is my daily routine system. The goal is to have recurring tasks that regenerate automatically, and a space to capture random ideas without interrupting my flow."

You can also do this via the **project edit icon** in the interface.

---

### Step 3 — Create recurring cards

#### Card 1: Morning Standup

From the project context, say:

> "Create a card 'Morning Standup' with the Researcher agent. Description: review what's planned for today — check cards in progress, blockers, priorities. Checklist: What was planned yesterday? What's planned today? Blockers? Make the card recurring every day (weekdays)."

Or create the card manually, then configure the recurrence in the card detail (**Recurrence** field).

**Available recurrences:**

| Value | Frequency |
|--------|-----------|
| `daily` | Every day |
| `weekdays` | Monday–Friday (weekends skipped) |
| `weekly` | Every week |
| `biweekly` | Every two weeks |
| `monthly` | Every month |
| `hourly` | Every hour |
| `6hours` | Every 6 hours |

When the next occurrence date is reached, the scheduler automatically creates a fresh copy of the card (status `todo`, title and description preserved) and reschedules the next occurrence.

#### Card 2: Weekly Review

> "Create a card 'Weekly Review' with the Architect agent. Description: full review of the week — completed cards, pending items, decisions made. Weekly recurrence, every Friday."

#### Card 3: Inbox

> "Create a card 'Inbox — ideas and captures' with status Todo, no agent. Description: temporary drop for all ideas that come up during the week. To be sorted every Friday during the Weekly Review."

The inbox is not recurring — it's a persistent card that you clear manually during the review.

---

### Step 4 — Work on a card (card context)

On Monday morning, you open the **Morning Standup** card (generated automatically). Voxy is now focused on this card.

You can say:

> "Run the standup."

Voxy will:
1. Look at the cards in progress in the project
2. Identify potential blockers
3. Give you a structured summary
4. Check off checklist items as she goes

Or more simply:

> "What was planned yesterday?"

She will check the conversation history on this card (previous sessions) and saved comments.

---

### Step 5 — Automate with scheduled jobs (optional)

Voxyflow offers several types of scheduled jobs. Here are the three main ones:

#### Execute Board — run an entire board

An **Execute Board** automatically executes all cards in a project with a given status — no manual intervention needed.

> "Create an Execute Board job for the DailyOps project, every day at 8am, that executes cards with status 'todo'."

```bash
curl -X POST http://localhost:8000/api/jobs \
  -H "Content-Type: application/json" \
  -d '{
    "name": "DailyOps — Morning Run",
    "type": "execute_board",
    "schedule": "0 8 * * 1-5",
    "enabled": true,
    "payload": {
      "project_id": "TON_PROJECT_ID",
      "statuses": ["todo"]
    }
  }'
```

#### Execute Card — run a specific card

An **Execute Card** runs a single card through the AI pipeline on a schedule.

```bash
curl -X POST http://localhost:8000/api/jobs \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Daily health check card",
    "type": "execute_card",
    "schedule": "0 9 * * *",
    "payload": { "card_id": "TON_CARD_ID", "project_id": "TON_PROJECT_ID" }
  }'
```

#### Agent Task — free-form instruction

An **Agent Task** sends a free-form instruction to the AI agent — the most flexible option.

```bash
curl -X POST http://localhost:8000/api/jobs \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Daily email check",
    "type": "agent_task",
    "schedule": "0 8 * * *",
    "payload": { "instruction": "Check for new emails and create cards for each one." }
  }'
```

---

### Step 6 — Use the project wiki

From the project context, the DailyOps wiki can serve as a permanent reference — review checklists, standup templates, context notes.

> "Create a wiki page 'Templates' with a standup template and a weekly review template."

Voxy will create the page. It is then available as context for workers.

---

## Useful workflow patterns

### Capture an idea without losing your train of thought

You're working on a card (card context). An idea comes up.

**Don't switch context.** Just say:

> "Note something for me outside this card: explore migrating to PostgreSQL for performance."

Voxy will create a card in the project's inbox (or in Home if specified) without pulling you out of your current context.

---

### Delegate without waiting

The Dispatcher (Voxy in conversation mode) never blocks. If you ask for something that takes time:

> "Analyze all cards in progress and tell me which ones are most at risk."

Voxy will respond immediately ("Running the analysis...") and send a **worker** in the background. You can keep talking while it works. The result arrives in the chat when the worker is done.

---

### Quickly enrich a card

Open a card with just a title. Say:

> "Enrich this card."

Voxy will generate a detailed description, acceptance criteria, and checklist suggestions based on the title and project context.

---

### Quick standup from project context

Without opening a card, from the project context:

> "Give me the project standup."

Voxy calls `voxyflow.ai.standup` and generates a structured summary: what's done, in progress, and blocked.

---

### Switch sessions

Each context (project or card) can have up to 5 parallel sessions — separate conversations on the same topic.

- **Session 1** — planning conversation
- **Session 2** — technical implementation conversation
- **Session 3** — free brainstorm

Sessions appear as tabs in the chat panel. Type `/new` to start a new session in the current context.

---

## Quick reference

| Situation | Context to use | What you can ask |
|-----------|----------------|------------------|
| Create a new project | General (Home) | "Create a project X" |
| See the status of all my projects | General | "Show me my projects" |
| Create a card | Project | "Create a card for Y" |
| See the standup | Project | "Project standup" |
| Work on a task | Card | "Get started on this task" |
| Enrich details | Card | "Enrich this card" |
| Log time | Card | "I spent 2h on this" |
| Check a checklist item | Card | "Mark 'Unit tests' as done" |
| Create a scheduled job | General | "Create a job that runs every Monday at 9am" |
| Quickly capture an idea | Any | "Note for later: ..." |

---

_For the technical reference on scopes (chat ID format, available tools per level, backend routing), see [CHAT_SCOPES.md](CHAT_SCOPES.md)._
