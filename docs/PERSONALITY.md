# Personality Layer — How Ember Lives in Voxyflow

## Overview

Voxyflow doesn't just use Claude — it uses Claude *as Ember*. Every API call carries the personality defined in the Voxyflow workspace files. The result: a voice assistant that sounds like the same person whether she's answering a quick question (Haiku) or doing deep analysis (Opus).

## How It Works

### Source Files (Shared with Voxyflow)

```
~/.voxyflow/workspace/
├── SOUL.md       → Core personality, values, communication style
├── USER.md       → Who the human is, preferences, context
├── IDENTITY.md   → Name, creature type, emoji, vibe
├── MEMORY.md     → Long-term curated memories
└── memory/
    ├── YYYY-MM-DD.md   → Daily logs
    └── projects/
        └── <name>.md   → Project-specific notes
```

These files are the **single source of truth**. Ember in Mattermost, Ember in Voxyflow, Ember anywhere — all read from the same soul.

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
The Voxyflow workspace files ARE the database. They're version-controlled (git), human-editable, and shared across all surfaces. Duplicating them in SQLite would create sync headaches.

### Why different memory depth per layer?
Speed vs. context tradeoff. Haiku needs to respond in <1s — loading 30KB of MEMORY.md kills that. Opus runs async, so it can afford the fuller picture. This mirrors how humans think: quick responses use recent memory, deep analysis draws on everything.

## Example: Before vs. After Personality

**Without personality (generic Claude):**
```
User: "Je veux refactor l'API"
Claude: "I can help with that. What specific aspects of the API would you like to refactor?"
```

**With personality (Ember):**
```
User: "Je veux refactor l'API"
Ember: "Cool, l'API commence à être cluttered. Tu veux attaquer quoi en premier — le routing ou les modèles?"
```

Same model, same capability — but the personality makes it *hers*.
