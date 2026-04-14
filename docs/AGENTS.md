# Specialized Agents — BMAD-Lite for Voxyflow

## Overview

Voxyflow uses a lightweight agent system inspired by BMAD (but simpler). Instead of separate sub-agents, each "agent" is a Claude API call with a specialized system prompt overlay. Same model, different hat.

## Agent Types

| Type | Name | Emoji | When It's Used |
|------|------|-------|----------------|
| `general` | General | ⚡ | Default. General tasks, conversation, coordination |
| `researcher` | Recherchiste | 🔍 | Deep analysis, fact-checking, market research |
| `coder` | Codeuse | 💻 | Code generation, debugging, refactoring |
| `designer` | Designer | 🎨 | UI/UX, wireframes, visual design guidance |
| `architect` | Architecte | 🏗️ | System design, PRDs, architecture decisions |
| `writer` | Rédactrice | ✍️ | Blog posts, docs, marketing copy |
| `qa` | QA | 🧪 | Test plans, edge cases, quality assurance |

## How Routing Works

### Automatic (on card creation)

When a card is created (manually or via AI suggestion), the **AgentRouter** scores it:

```
Card: "Refactor the authentication API"
    │
    ├── Keyword scan:
    │   "refactor" → Coder (strong: +3) + Architect (moderate: +1)
    │   "api"      → Coder (strong: +3)
    │   "authentication" → no specific match
    │
    ├── Scores:
    │   Coder:     0.5 + (6 × 0.05) = 0.80 ✓ winner
    │   Architect: 0.35 + (1 × 0.05) = 0.40
    │
    └── Result: agent_type = "coder", confidence = 0.80
```

### Manual (user override)

Users can reassign any card to a different agent:

```
POST /api/cards/{card_id}/assign
{
    "agent_type": "architect",
    "agent_context": "Focus on the migration path from monolith to microservices"
}
```

### LLM-Assisted

Claude can determine the agent type as part of card extraction. The keyword router cross-validates: if they disagree and the router has high confidence (>0.7), the router wins.

## Agent Prompt Architecture

Each agent gets a layered system prompt:

```
Personality (SOUL + IDENTITY)     ← Same everywhere
    +
User context (USER.md)           ← Same everywhere  
    +
Memory (MEMORY.md + daily)       ← Same everywhere
    +
Agent Persona                    ← DIFFERENT per agent
    +
Task instructions                ← DIFFERENT per card
```

The personality is **always present**. An Architect agent still sounds like Voxy — just wearing an architecture hat.

## Example System Prompts

### Coder Persona (excerpt)
```
You are a Code Specialist.

Your approach:
- Write clean, well-structured code. No spaghetti.
- Include error handling. Think about edge cases.
- Comment non-obvious logic. Don't comment the obvious.
- Prefer simplicity over cleverness.
- If refactoring, explain what changed and why.

Output style:
- Working code with clear file paths
- Brief explanation of approach before code
- Note any dependencies or setup needed
- Suggest tests for critical paths
```

### Architect Persona (excerpt)
```
You are a System Architecture Specialist.

Your approach:
- Think in systems. Every piece connects to something.
- Start with constraints, not solutions.
- Consider scalability, but don't over-engineer for MVP.
- Make tradeoffs explicit. There's always a tradeoff.
- Document decisions and their rationale (ADR-style).

Output style:
- Architecture diagrams (ASCII/Mermaid)
- Component breakdown with responsibilities
- Data flow descriptions
- Decision records (context → decision → consequences)
```

## Data Model

Cards now include agent fields:

```python
class Card:
    # ... existing fields ...
    agent_type: str       # general|researcher|coder|designer|architect|writer|qa
    agent_assigned: str   # Display: "💻 Codeuse"
    agent_context: str    # Relevant docs/requirements for the agent
```

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/projects/{id}/cards` | Create card (auto-routes to agent) |
| `PATCH` | `/cards/{id}` | Update card (can change agent_type) |
| `POST` | `/cards/{id}/assign` | Assign/reassign to specific agent |
| `GET` | `/cards/{id}/routing` | Get routing suggestion without applying |
| `GET` | `/projects/{id}/cards?agent_type=coder` | Filter cards by agent |

## End-to-End Flow

```
1. User says: "Je veux refactor mon API backend"
   │
2. Haiku responds (personality-infused):
   "Cool, on peut faire ça. Tu veux attaquer quoi en premier?"
   │
3. Opus analyzes (background):
   Suggests splitting into phases, identifies dependencies
   │
4. AI detects actionable item:
   ├── title: "Refactor API backend"
   ├── confidence: 0.75
   ├── agent_type: "architect" (design-heavy task)
   └── agent_name: "🏗️ Architecte"
   │
5. WebSocket pushes card suggestion to UI:
   User sees: "Refactor API backend — assigned to 🏗️ Architecte"
   │
6. User confirms → card created in project board
   │
7. User clicks card → "Work with Architecte"
   │
8. Claude called with:
   ├── Personality (SOUL + IDENTITY + USER)
   ├── Memory (MEMORY + daily logs)
   ├── Architect persona prompt
   └── Card context + conversation history
   │
9. Voxy (as Architecte): "J'ai analysé ton API. Voici ma proposition..."
   │
10. Decision logged to memory/YYYY-MM-DD.md
    Next session remembers what was decided.
```

## Design Decisions

### Why not actual sub-agents?
Complexity. Sub-agents need orchestration, state management, and error handling. Claude-with-a-different-prompt achieves 90% of the value with 10% of the complexity. We can always add true sub-agents later.

### Why keyword routing instead of always-LLM?
Speed + cost. Keyword routing is instant and free. LLM routing is smarter but costs tokens and adds latency. We use keywords as the fast path and LLM as the quality path, with cross-validation when both run.

### Why a General default?
Most tasks don't need a specialist. General conversation, quick questions, coordination — these don't require specialization. The specialist personas only kick in when the task clearly benefits from focused expertise.

### Why bilingual persona names?
JC works in French and English. Persona names reflect that: Recherchiste, Codeuse, Architecte, Rédactrice. It's a small detail, but it makes the agents feel native to the user's world.

## Future Enhancements

- **Agent chaining**: Architect creates spec → Coder implements → QA validates
- **Agent memory**: Per-agent notes (what the Architect decided last time)
- **Confidence threshold tuning**: Learn from user overrides
- **Custom agents**: User-defined personas via config file
- **Agent collaboration**: Multiple agents on same card (Designer + Coder)
