# Voxyflow — Architecture Document

## Overview

Voxyflow is a voice-first project management assistant. You talk to it, it understands, responds with voice, and auto-generates project cards/tasks from the conversation. Under the hood, multiple Claude models collaborate: Haiku for fast conversational responses, Opus for deep analysis and supervision.

## Tech Stack

| Layer        | Choice                        | Rationale |
|--------------|-------------------------------|-----------|
| **Frontend** | Vanilla JS PWA + WebSocket    | No build step for MVP. Web Speech API for STT in-browser. React/Vue later if complexity warrants it. PWA gives installable app feel with offline shell. |
| **Backend**  | FastAPI (Python 3.11+)        | JC's primary language. Async-native, WebSocket first-class, auto-generated OpenAPI docs. Excellent ecosystem for AI/ML integration. |
| **Database** | SQLite → Postgres migration path | SQLite for MVP (zero config, file-based, plenty fast for single-user). SQLAlchemy ORM means switching to Postgres later is a config change, not a rewrite. |
| **STT**      | Web Speech API (primary) + Whisper Turbo CPU (fallback) | Browser-native STT = zero latency, zero cost, works offline. Whisper Turbo on thething as fallback for browsers without Web Speech API or for higher accuracy when needed. |
| **LLM**      | Claude API direct (Haiku + Opus) | Separate service, not through OpenClaw. Haiku for fast voice responses (<1s). Opus for background analysis, card generation, enrichment. |
| **TTS**      | Sherpa-ONNX on thething (CPU) | Runs locally, no GPU needed for VITS/MMS models. Low latency for short responses. Corsair GPU forwarding as future option for higher quality voices. |
| **Transport**| WebSocket                     | Full-duplex real-time audio streaming. Single persistent connection per session. Binary frames for audio, text frames for JSON control messages. |
| **Host**     | thething                      | Always-on server. Proxies to Claude API, runs TTS locally, serves the PWA. Single point of deployment for MVP. |

## Architecture Diagram

```
┌─────────────────────────────────────────────────────────────────────┐
│                         BROWSER (PWA)                                │
│                                                                      │
│  ┌──────────────┐  ┌──────────────┐  ┌───────────────────────────┐  │
│  │  Voice Input  │  │  Chat UI     │  │  Project/Card Board       │  │
│  │  (mic capture)│  │  (messages)  │  │  (kanban-style)           │  │
│  └──────┬───────┘  └──────┬───────┘  └───────────┬───────────────┘  │
│         │                  │                       │                  │
│  ┌──────▼───────┐          │                       │                  │
│  │ Web Speech   │          │                       │                  │
│  │ API (STT)    │          │                       │                  │
│  └──────┬───────┘          │                       │                  │
│         │ transcript       │                       │                  │
│         └────────┬─────────┘                       │                  │
│                  │                                  │                  │
│          ┌───────▼────────┐                         │                  │
│          │   WebSocket    │◄────────────────────────┘                  │
│          │   Client       │                                           │
│          └───────┬────────┘                                           │
│                  │ ws://thething:8000/ws/voice/{chat_id}              │
└──────────────────┼───────────────────────────────────────────────────┘
                   │
                   │ WebSocket (binary: audio, text: JSON)
                   │
┌──────────────────┼───────────────────────────────────────────────────┐
│  thething        │              BACKEND (FastAPI)                     │
│                  │                                                    │
│          ┌───────▼────────┐                                          │
│          │  WebSocket     │                                          │
│          │  Voice Handler │                                          │
│          └──┬──────────┬──┘                                          │
│             │          │                                              │
│    ┌────────▼──┐  ┌────▼─────────┐                                   │
│    │ Whisper   │  │ Conversation │                                   │
│    │ Fallback  │  │ Router       │                                   │
│    │ (STT)     │  └──┬────────┬──┘                                   │
│    └───────────┘     │        │                                      │
│                      │        │                                      │
│         ┌────────────▼─┐  ┌──▼──────────────┐                       │
│         │  Layer 1:    │  │  Layer 2:        │                       │
│         │  Haiku       │  │  Opus            │                       │
│         │  (fast resp) │  │  (bg supervisor) │                       │
│         └──────┬───────┘  └──┬──────────────┘                       │
│                │             │                                       │
│                │             ├──► Layer 3: Analyzer                   │
│                │             │    (card detection)                    │
│                │             │                                       │
│         ┌──────▼───────┐    │    ┌───────────────┐                  │
│         │  TTS Service │    └───►│  Card/Project  │                  │
│         │  (Sherpa-ONNX│         │  Service       │                  │
│         │   local CPU) │         └───────┬───────┘                  │
│         └──────┬───────┘                 │                           │
│                │                         │                           │
│                │              ┌──────────▼─────────┐                │
│                │              │  SQLite Database    │                │
│                │              │  (voxyflow.db)      │                │
│                │              │                     │                │
│                │              │  • chats            │                │
│                │              │  • messages          │                │
│                │              │  • projects          │                │
│                │              │  • cards             │                │
│                │              └─────────────────────┘                │
│                │                                                     │
└────────────────┼─────────────────────────────────────────────────────┘
                 │
                 │ audio bytes (PCM/opus)
                 ▼
          Back to browser
          (AudioContext playback)

─────────────────────────────────────────────
 External Services
─────────────────────────────────────────────

  thething ──HTTPS──► api.anthropic.com
                      (Claude Haiku + Opus)

  thething ──HTTP───► Corsair (future)
                      (GPU TTS for premium voices)

  thething ──HTTP───► Mattermost (future)
                      (webhook notifications)
```

## Data Flow: Voice Conversation

```
1. User speaks into mic
   │
2. Browser: Web Speech API → transcript (text)
   │  (or: raw audio → WebSocket → thething Whisper fallback)
   │
3. WebSocket sends JSON: { "type": "transcript", "text": "..." }
   │
4. Backend: Conversation Router
   │
   ├─► Layer 1 (Haiku): Immediate response (<1s)
   │   │
   │   ├─► TTS: text → audio bytes
   │   │
   │   └─► WebSocket: send audio + transcript to browser
   │
   ├─► Layer 2 (Opus): Background analysis (2-5s)
   │   │
   │   ├─► If correction needed:
   │   │   TTS: "Actually, let me refine that..." → audio
   │   │   WebSocket: send enrichment
   │   │
   │   └─► Layer 3 (Analyzer): Check for actionable items
   │       │
   │       └─► If card detected:
   │           WebSocket: { "type": "card_suggestion", ... }
   │           (user confirms in UI → card created)
   │
5. All messages stored in SQLite with full metadata
```

## Multi-Layer Conversation Model

### Layer 1: Haiku (Fast Responder)
- **Role:** Conversational partner, immediate voice responses
- **Latency target:** < 1 second from transcript to audio start
- **Context:** Last 10-20 messages + active project summary
- **System prompt:** Friendly PM assistant, focuses on understanding and acknowledging
- **When it speaks:** Every user message gets a Haiku response

### Layer 2: Opus (Background Supervisor)
- **Role:** Deep thinker, quality checker, strategic advisor
- **Latency:** 2-10 seconds (runs async, doesn't block voice)
- **Context:** Full conversation history + all project context
- **System prompt:** Senior PM/architect, catches what Haiku misses
- **When it speaks:** Only when it has something substantively different to add
- **UX pattern:** "Hmm, actually—I thought about it more and..." (feels natural)

### Layer 3: Analyst Agent (Card Detector)
- **Role:** Watches conversation for task/card opportunities
- **Trigger:** Runs after every Opus analysis
- **Output:** Card suggestions pushed to UI (not voice)
- **Algorithm:** See Card Generation section below

### Interaction Pattern
```
User: "We need to refactor the auth module, it's getting messy"

Haiku (immediate): "Yeah, the auth module has grown quite a bit. 
  Want to break that down into specific tasks?"

Opus (3s later): "I'd suggest splitting this into three phases: 
  first extract the JWT logic, then separate OAuth providers, 
  then add the refresh token rotation we discussed last week."

Analyzer (background): → suggests card: "Refactor auth module"
  with sub-cards for each phase Opus identified
```

## Card Generation Algorithm

### Detection Pipeline
```
1. Message Analysis
   - Opus reviews conversation for "action signals"
   - Signals: verbs (build, fix, refactor, add, remove, test)
   - Context: mentions of deadlines, priorities, dependencies

2. Card Extraction
   - Title: concise action (imperative mood)
   - Description: context from conversation
   - Priority: inferred from urgency words + project context
   - Dependencies: if mentions other cards/tasks, auto-link

3. Suggestion
   - Push card suggestion to UI via WebSocket
   - User sees: title, description, "Create card?" button
   - No card created without user confirmation

4. Linking
   - On creation, scan existing cards for:
     - Keyword overlap (TF-IDF similarity)
     - Explicit references ("related to X", "blocks Y")
   - Auto-suggest dependencies
   - Store source_message_id for full audit trail
```

### Card States
```
idea → todo → in_progress → done
  │                           │
  └── archived ◄──────────────┘
```

## Database Schema (SQLAlchemy)

```
┌─────────────┐     ┌─────────────────┐
│   chats     │     │    messages      │
├─────────────┤     ├─────────────────┤
│ id (UUID PK)│◄────│ chat_id (FK)    │
│ title       │     │ id (UUID PK)    │
│ project_id  │     │ role            │
│ created_at  │     │ content         │
│ updated_at  │     │ audio_url       │
└──────┬──────┘     │ model_used      │
       │            │ tokens_used     │
       │            │ latency_ms      │
       │            │ created_at      │
       │            └─────────────────┘
       │
       │ (optional link)
       │
┌──────▼──────┐     ┌─────────────────┐
│  projects   │     │     cards       │
├─────────────┤     ├─────────────────┤
│ id (UUID PK)│◄────│ project_id (FK) │
│ title       │     │ id (UUID PK)    │
│ description │     │ title           │
│ status      │     │ description     │
│ context     │     │ status          │
│ created_at  │     │ priority        │
│ updated_at  │     │ source_msg_id   │
└─────────────┘     │ auto_generated  │
                    │ position        │
                    │ created_at      │
                    │ updated_at      │
                    └────────┬────────┘
                             │
                    ┌────────▼────────┐
                    │ card_dependencies│
                    ├─────────────────┤
                    │ card_id (FK)    │
                    │ depends_on (FK) │
                    └─────────────────┘
```

## Personality Layer (NEW)

Voxyflow integrates with the OpenClaw workspace personality files to maintain a consistent voice across all interactions.

### Architecture

```
~/.openclaw/workspace/
├── SOUL.md          ──┐
├── USER.md          ──┤── PersonalityService
├── IDENTITY.md      ──┘   └── build_system_prompt()
├── MEMORY.md        ──┐       ├── Layer 1: Who You Are (SOUL + IDENTITY)
└── memory/          ──┤       ├── Layer 2: About Your Human (USER)
    ├── YYYY-MM-DD.md──┘       ├── Layer 3: Relevant Memory
    └── projects/              ├── Layer 4: Agent Persona (if specialized)
        └── <name>.md          └── Layer 5: Task Instructions
```

### Services

| Service | File | Responsibility |
|---------|------|----------------|
| **PersonalityService** | `services/personality_service.py` | Load SOUL/USER/IDENTITY, build layered prompts |
| **MemoryService** | `services/memory_service.py` | Read/write workspace memory files |

### Data Flow

```
PersonalityService                    MemoryService
    │                                     │
    ├── load_soul()                       ├── load_long_term_memory()
    ├── load_user()                       ├── load_daily_logs()
    ├── load_identity()                   ├── load_project_memory()
    │                                     ├── search_memory()
    └── build_system_prompt()             └── append_to_daily_log()
            │
            ▼
    ClaudeService._call_api(system=...) ← personality-infused prompt
```

See [PERSONALITY.md](PERSONALITY.md) for full details.

## Specialized Agents Layer (NEW)

A lightweight BMAD-inspired agent system. Each "agent" is a Claude call with a specialized persona overlay — same personality, different expertise.

### Agent Types

| Type | Name | Emoji | Specialty |
|------|------|-------|-----------|
| ember | Ember | 🔥 | Default — general tasks |
| researcher | Recherchiste | 🔍 | Deep analysis, research |
| coder | Codeuse | 💻 | Code, debugging, APIs |
| designer | Designer | 🎨 | UI/UX, wireframes |
| architect | Architecte | 🏗️ | System design, planning |
| writer | Rédactrice | ✍️ | Content, docs, copy |
| qa | QA | 🧪 | Testing, validation |

### Architecture

```
Message analyzed by AnalyzerService
    │
    ├── Keyword detection (fast)
    ├── LLM analysis (optional, richer)
    │
    ▼
AgentRouter.route(title, description, context)
    │
    ├── Score each agent type via weighted keywords
    ├── Cross-validate with LLM suggestion
    │
    ▼
CardSuggestion {
    title, description, priority,
    agent_type: "architect",
    agent_name: "🏗️ Architecte"
}
    │
    ▼
Card created → User can reassign agent
    │
    ▼
ClaudeService.chat_with_agent(agent_type, task_context)
    │
    └── System prompt = Personality + Memory + Agent Persona + Task
```

### Services

| Service | File | Responsibility |
|---------|------|----------------|
| **AgentRouter** | `services/agent_router.py` | Score and route cards to agents |
| **AgentPersonas** | `services/agent_personas.py` | Define persona prompts + metadata |

### Card Data Model (Updated)

```
cards table:
  + agent_type     (string)  — ember|researcher|coder|designer|architect|writer|qa
  + agent_context  (text)    — relevant docs/requirements for the agent
```

See [AGENTS.md](AGENTS.md) for full details.

## Updated Backend Service Map

```
backend/app/services/
├── claude_service.py          ← API calls (personality-infused)
├── personality_service.py     ← SOUL/USER/IDENTITY loading (NEW)
├── memory_service.py          ← workspace memory read/write (NEW)
├── analyzer_service.py        ← card detection + agent routing (UPDATED)
├── agent_router.py            ← smart agent assignment (NEW)
├── agent_personas.py          ← persona definitions (NEW)
├── chat_service.py            ← conversation management
└── tts_service.py             ← text-to-speech
```

## Future Considerations

- **Auth:** JWT-based when multi-user needed
- **Postgres:** Swap SQLAlchemy URL, add alembic migrations
- **Mattermost:** Webhook integration for card notifications
- **Corsair GPU TTS:** Higher quality voices via network forward
- **Mobile:** PWA already works, but native wrapper possible
- **Agent chaining:** Architect → Coder → QA pipeline
- **Agent memory:** Per-agent notes and learning
- **Custom personas:** User-defined agents via config
- **Semantic memory search:** Embeddings for better memory retrieval

## Next Steps (Post-Scaffold)

1. **Frontend PWA** — Voice capture UI, chat interface, card board
2. **Claude integration** — Wire up Haiku/Opus with real API calls (personality-infused)
3. **TTS integration** — Sherpa-ONNX setup on thething
4. **WebSocket protocol** — Define message types and binary audio format
5. **Card UI** — Kanban board with drag-drop + agent badges
6. **Agent assignment UI** — Agent picker on cards, routing transparency
7. **Memory write-back** — Daily log entries from Voxyflow conversations

---

## Model Responsibility Rules (CRITICAL)

### Haiku = Voice Only
- **NEVER** uses tools
- **NEVER** does deep thinking
- **ONLY** conversational responses (fast, personality-infused)
- Response target: < 1s
- Role: The **mouth** — speaks to the user

### Sonnet = Worker
- Executes tools (file ops, web, exec, code generation)
- Handles mechanical/repetitive tasks
- Used as sub-agent when Haiku detects work is needed
- Medium complexity tasks

### Opus = Brain
- Deep thinking, analysis, architecture
- Supervisor layer (enriches/corrects Haiku in background)
- Complex reasoning, design decisions
- Used as sub-agent for high-complexity work

### Tool Delegation Pattern
```
User speaks
  ↓
Haiku responds (conversation only, NO tools)
  ↓
If tool/work needed:
  ↓
Haiku delegates → Sonnet sub-agent (simple tools)
              OR → Opus sub-agent (complex work)
  ↓
Sub-agent executes (tools, code, analysis)
  ↓
Result returns to Haiku
  ↓
Haiku delivers result naturally to user
```

### Key Principle
Haiku is the **interface layer**. It NEVER touches tools directly.
All tool use goes through Sonnet/Opus sub-agents based on complexity:
- Simple/mechanical → Sonnet
- Complex/architectural → Opus
- Conversation/voice → Haiku (always)

This separation ensures:
1. Voice responses are always fast (Haiku never blocked by tools)
2. Tool work is done by capable models (not Haiku)
3. User experience is seamless (Haiku delivers results naturally)
