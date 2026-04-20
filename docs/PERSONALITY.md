# Personality Layer — How Voxy Lives in Voxyflow

## Overview

Voxyflow doesn't just use an LLM — it runs it *with a personality*. Every dispatcher call and every worker run carries the personality defined in the repo's `personality/` files. The result: a voice assistant that sounds like the same person whether it's answering a quick question on the Fast layer, doing deep analysis on the Deep layer, or executing a task in a worker subprocess — regardless of which underlying provider (CLI / Anthropic / OpenAI / Ollama / etc.) is configured.

## How It Works

### Source Files

Personality lives in the repo at `personality/` (checked in) and in the user
data dir `~/voxyflow/personality/` (user-editable via Settings):

```
personality/                   # repo-checked baseline
├── SOUL.md         → Core personality, values, communication style
├── AGENTS.md       → Agent operating rules (dispatcher/worker/agent personas)
├── DISPATCHER.md   → Dispatcher-specific behavior
├── WORKER.md       → Worker-specific behavior
├── PROACTIVE.md    → Proactive / opportunity-detection rules
└── ARCHITECTURE.md → Architectural context shared with the bot

~/voxyflow/personality/        # user data (auto-generated at first boot)
├── USER.md         → Who the human is, preferences, context
├── IDENTITY.md     → Bot name, emoji, vibe
└── MEMORY.md       → Long-term curated memories
```

`USER.md` and `IDENTITY.md` are editable via **Settings → Personality**.
`SOUL.md`, `AGENTS.md`, and friends are checked in and edited directly.

### System Prompt Construction

Every Claude API call builds a layered system prompt:

```
┌──────────────────────────────────┐
│ Layer 1: Who You Are             │  ← IDENTITY.md + SOUL.md
│   Name, creature, values, vibe   │
├──────────────────────────────────┤
│ Layer 2: About Your Human        │  ← USER.md
│   Name, preferences, context     │
├──────────────────────────────────┤
│ Layer 3: Relevant Memory         │  ← MEMORY.md + daily logs
│   Recent context, decisions      │
├──────────────────────────────────┤
│ Layer 4: Specialized Role        │  ← Agent persona (if applicable)
│   Researcher/Coder/etc. prompt   │
├──────────────────────────────────┤
│ Layer 5: Current Task            │  ← Haiku/Opus instructions
│   What to do right now           │
└──────────────────────────────────┘
```

### Per-Layer Behavior

| Layer | Personality | Memory | Speed Priority |
|-------|-------------|--------|----------------|
| **Haiku** (voice) | Full SOUL + IDENTITY | Daily logs only | ⚡ Fast |
| **Opus** (deep) | Full SOUL + IDENTITY | Full MEMORY + daily | 🧠 Thorough |
| **Agent** (specialized) | Full + persona overlay | Full MEMORY + daily | 🧠 Thorough |

### Memory Integration

```python
# PersonalityService builds the prompt
personality = get_personality_service()
memory = get_memory_service()

# Memory context varies by layer
memory_ctx = memory.build_memory_context(
    project_name="voxyflow",      # Project-specific notes
    include_long_term=True,        # MEMORY.md
    include_daily=True,            # Recent daily logs
)

# System prompt = personality + memory + task instructions
system_prompt = personality.build_haiku_prompt(memory_context=memory_ctx)
```

### File Caching

Personality files are cached by mtime — they're only re-read when modified. This means:
- Hot path (Haiku) doesn't hit the filesystem on every call
- Changes to SOUL.md take effect within 5 minutes (or on restart)
- No external dependencies (no Redis, no DB)

## Memory Flow

```
Conversation happens in Voxyflow
    │
    ├── Decisions made → append to memory/YYYY-MM-DD.md
    ├── Project learnings → update memory/projects/<name>.md
    │
    ▼
Next session reads those files → continuity
    │
    ▼
Heartbeat cron (Voxyflow) curates → MEMORY.md
```

Voxyflow writes to daily logs. Voxyflow's heartbeat system periodically curates daily logs into MEMORY.md. This is how short-term memory becomes long-term memory.

## Design Decisions

### Why not store personality in the database?
The `personality/` files ARE the database for persona. Repo-checked files are version-controlled (git), human-editable, and shared across all surfaces; user-data files live under `~/voxyflow/personality/` and are edited via Settings → Personality. Duplicating them in SQLite would create sync headaches.

### Why different memory depth per layer?
Speed vs. context tradeoff. Haiku needs to respond in <1s — loading 30KB of MEMORY.md kills that. Opus runs async, so it can afford the fuller picture. This mirrors how humans think: quick responses use recent memory, deep analysis draws on everything.

## Example: Before vs. After Personality

**Without personality (generic Claude):**
```
User: "Je veux refactor l'API"
Claude: "I can help with that. What specific aspects of the API would you like to refactor?"
```

**With personality (Voxy):**
```
User: "Je veux refactor l'API"
Voxy: "Cool, l'API commence à être cluttered. Tu veux attaquer quoi en premier — le routing ou les modèles?"
```

Same model, same capability — but the personality makes it *hers*.
