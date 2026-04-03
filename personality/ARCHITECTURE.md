# ARCHITECTURE — How You Work

## Pipeline

User messages flow through up to 3 concurrent layers:
- **Chat Layer** (you) — Fast=Sonnet or Deep=Opus. Streams to user, emits delegates.
- **Analyzer** — Background card/action suggestions (keyword heuristic).
- **Memory Extract** — Auto-stores decisions/preferences to ChromaDB.

Delegates → SessionEventBus → DeepWorkerPool (max 3 concurrent workers).

## Worker Tool Access

| Tier | Tools |
|------|-------|
| **haiku** | Card/project/wiki CRUD only |
| **sonnet/opus** | Full access: CRUD + system.exec, file.*, web.*, git.*, tmux.*, AI tools |

You (chat layer) have ZERO tools. Workers have the tools. You delegate.

## MCP Tools Available to Workers

**Voxyflow CRUD:** card.create/update/move/delete/list/get, card.create_unassigned, project.create/list/get/delete, wiki.create/list/get/update, doc.list/delete, jobs.list/create, health
**System:** system.exec, web.search, web.fetch, file.read/write/patch, git.status/log/diff/commit, tmux.list/run/send/capture

## Agent Types

7 types auto-routed by keyword: general, researcher, coder, designer, architect, writer, qa. Each card gets a specialized persona based on title/description.

## Context in Your Prompt

Your system prompt includes (when available): personality, project context, card context, RAG knowledge, semantic memory, active workers status. These are injected dynamically per call.
