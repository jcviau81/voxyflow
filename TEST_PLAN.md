# Voxyflow — Functional Test Plan v3

_Target: `https://thething:3000` | Backend: `:8000` | Proxy: `:3457`_
_Revised: 2026-03-21 — Full functional E2E testing, all scopes, all tool sequences_

---

## Scope Definitions

| Scope | Trigger | Tools Available | Session Format |
|-------|---------|----------------|----------------|
| **General** | Main tab active, no project | `card.create_unassigned`, `project.create/list/get`, `web.*`, `file.*`, `git.*`, `tmux.*`, `jobs.*` | `general:{sessionId}` |
| **Project** | Project tab active, no card | All tools EXCEPT `card.create_unassigned`, `card.list_unassigned` | `project:{projectId}` |
| **Card** | Card selected in project | ALL tools — no filtering | `card:{cardId}` |

---

## TEST 1: App Bootstrap

| # | Step | Expected | Verify |
|---|------|----------|--------|
| 1.1 | Open app | Page loads, sidebar visible, WebSocket connected (green indicator) | No console errors, no 404s |
| 1.2 | Check Main Chat | WelcomePrompt renders with 4 buttons: Just chatting, Existing project, Brainstorm, Review tasks | Buttons clickable |
| 1.3 | Sidebar state | Lists all existing projects (from API `/api/projects?archived=false`) | Count matches API |
| 1.4 | Theme persistence | Reload page → same theme (dark/light) | localStorage check |

---

## TEST 2: General Scope — Conversation

| # | Step | Expected | Verify |
|---|------|----------|--------|
| 2.1 | Type "Hey, how are you?" | Voxy responds conversationally. No `<delegate>` visible. No XML leak. | Chat bubble, streaming tokens |
| 2.2 | Type "Salut, ça va?" | Response in French. Language matched. | FR content |
| 2.3 | Type long message (500+ chars) | Proportional response. Not a one-liner. | Response length |
| 2.4 | `/new` | Chat clears. New WelcomePrompt. Fresh session. | No old messages visible |
| 2.5 | After `/new`, type "What did I just say?" | Voxy has NO memory of pre-`/new` conversation | No reference to old content |

---

## TEST 3: General Scope — Main Board Card Creation

_Scope: General. Tools: `voxyflow.card.create_unassigned`_

| # | Step | Expected | Verify |
|---|------|----------|--------|
| 3.1 | "Add a card to my board: Weekly Meal Plan" | Dispatcher emits 1 delegate → worker uses `card.create_unassigned` | Backend log: `POST /api/cards/unassigned` → 201 |
| 3.2 | Check Main Board | Card "Weekly Meal Plan" visible on board | Navigate to 📝 tab |
| 3.3 | "Add a note called 'Quick Idea'" | Treated as card. Uses `card.create_unassigned`. Voxy never says "note". | Nomenclature: "card" only |
| 3.4 | "Create a card with details about camping gear I need" | Card created with rich description (not just title) | Description field populated |

---

## TEST 4: General Scope — Project Creation

_Scope: General. Tools: `voxyflow.project.create`_

| # | Step | Expected | Verify |
|---|------|----------|--------|
| 4.1 | "Create a project called 'Smart Garden'" | Worker: `project.create` → 201. Project in sidebar. | `POST /api/projects` → 201, sidebar updates |
| 4.2 | "Create a project 'Home Lab' with 4 cards: Setup DNS, Install Docker, Configure VPN, Setup Monitoring" | **Sequence:** Round 1: `project.create` → get UUID. Round 2+: `card.create` × 4 with REAL UUID. All 201. | No fake `proj_` IDs. All cards in correct project. |
| 4.3 | Open "Home Lab" project | Kanban shows 4 cards in Idea column | Cards fetched from backend API |
| 4.4 | Verify sidebar update | "Home Lab" visible without page refresh | `tool:executed` → `syncProjectsFromBackend()` |

---

## TEST 5: General Scope — Research + Card Combo

_Dependency chain: research THEN create — single delegate, sequential_

| # | Step | Expected | Verify |
|---|------|----------|--------|
| 5.1 | "Research the best camping spots near Montreal and make a card with the results" | ONE delegate emitted. Worker does `web.search` first, then `card.create_unassigned` with research results in description. | Log: single task, research content IN the card description |
| 5.2 | Check card content | Description contains actual research data (locations, details), not "Recherche en cours..." | Card detail modal |
| 5.3 | "Find the top 5 Python web frameworks and create a project card about it" | Same pattern: research → create. Not two parallel workers. | Log: no parallel task IDs for dependent work |

---

## TEST 6: General Scope — Web Search (No Card)

_Scope: General. Tools: `web.search`, `web.fetch`_

| # | Step | Expected | Verify |
|---|------|----------|--------|
| 6.1 | "Search the web for the latest NHL scores" | Dispatcher delegates to worker. Worker uses `web.search`. Result appears as message in chat. | Chat shows search results |
| 6.2 | While worker runs, type "What's 2+2?" | Voxy responds immediately. Chat NOT blocked. | Fast layer responds, worker still running |
| 6.3 | "Fetch the content of https://example.com" | Worker uses `web.fetch`. Page content returned in chat. | Response contains "Example Domain" |

---

## TEST 7: Project Scope — Context Awareness

_Navigate INTO a project, then chat_

| # | Step | Expected | Verify |
|---|------|----------|--------|
| 7.1 | Click project "Smart Garden" in sidebar | Project view loads. Kanban visible. Chat context switches. | `chatLevel: "project"` in WS messages |
| 7.2 | Type "What project am I in?" | Voxy knows: "Smart Garden". States project name. | Correct project name |
| 7.3 | "Add a card called 'Buy Seeds'" | Worker uses `card.create` with Smart Garden's UUID. NOT `card.create_unassigned`. | Log: `POST /api/projects/{smart-garden-uuid}/cards` → 201 |
| 7.4 | Card appears in kanban | "Buy Seeds" visible in Idea column without refresh | Real-time via `tool:executed` → `syncCardsFromBackend` |
| 7.5 | "List my cards" | Worker uses `card.list` for THIS project. Shows project cards only. | No Main Board cards mixed in |
| 7.6 | "Move 'Buy Seeds' to In Progress" | Worker uses `card.move` with correct card_id and status | Card moves to In Progress column |

---

## TEST 8: Project Scope — Tool Scoping

_Verify tools are correctly filtered in project context_

| # | Step | Expected | Verify |
|---|------|----------|--------|
| 8.1 | In project chat: "Add a card to my main board" | Voxy should either: (a) explain you're in a project, or (b) switch to general context. Should NOT have `card.create_unassigned` tool. | `_PROJECT_EXCLUDED_TOOLS` filtering |
| 8.2 | In project chat: "Search the web for X" | Worker dispatched with `web.search`. Works fine in project scope. | Web tools available in project |
| 8.3 | In project chat: "Delete this project" | Dangerous operation. Worker should confirm or refuse. | `voxyflow.project.delete` flagged as dangerous |

---

## TEST 9: Card Scope — Context Deep Dive

_Click a card to enter card-level chat_

| # | Step | Expected | Verify |
|---|------|----------|--------|
| 9.1 | Click card "Buy Seeds" in kanban | Card detail modal opens. Chat panel visible. No auto-message from Voxy. | WelcomePrompt with card-specific buttons |
| 9.2 | Type "What's in this card?" | Voxy knows card title, description, status, priority. Responds with card details. | Does NOT ask "which card?" |
| 9.3 | "Update the description to include seed varieties" | Worker uses `card.update` with THIS card's ID. | Log: `PATCH /api/cards/{buy-seeds-uuid}` → 200 |
| 9.4 | "Add a checklist: Tomatoes, Peppers, Herbs" | Worker uses `card.checklist` to add 3 items | `POST /api/cards/{id}/checklist` × 3 |
| 9.5 | "Move this card to Done" | Worker uses `card.move` with THIS card_id. Status → done. | Card moves in kanban |
| 9.6 | "What project is this card in?" | Voxy knows the project name from context | Correct project name |

---

## TEST 10: Card Scope — Execution Prompt Verification

| # | Step | Expected | Verify |
|---|------|----------|--------|
| 10.1 | Chat in a card, check backend logs | Execution prompt contains `## Current Context` block | Log: `card_id`, `project_id`, card title, description |
| 10.2 | Worker prompt includes card details | System prompt has card title, status, priority, description | `personality_service._build_worker_context_section()` |
| 10.3 | Worker uses correct IDs | All tool calls use the card's real UUID and project's real UUID | No fake/invented IDs |

---

## TEST 11: Kanban Real-Time Updates

| # | Step | Expected | Verify |
|---|------|----------|--------|
| 11.1 | Create cards via chat (in project) | Cards appear in kanban WITHOUT page refresh | `tool:executed` WS event → `CARD_CREATED` → `refreshCards()` |
| 11.2 | Manually create card via "+" button | Card appears immediately | Direct API call + appState update |
| 11.3 | Drag card to new column | Status updates. Persists on refresh. | `PATCH /api/cards/{id}` with new status |
| 11.4 | Refresh page (F5) | All cards still visible. Loaded from backend API. | `fetchAndSyncCards()` on KanbanBoard render |
| 11.5 | Switch between projects | Kanban shows correct project's cards each time | Cards fetched per-project |

---

## TEST 12: Tool Execution Engine

_Multi-round server-side tool loop_

| # | Step | Expected | Verify |
|---|------|----------|--------|
| 12.1 | Create project + cards in one request | Round 1: `project.create` (1 tool). Round 2+: `card.create` × N (with real UUID). | Logs: `[ServerTools] Round 1: ... tool_calls=1`, then `Round 2: ... tool_calls=N` |
| 12.2 | No fake IDs | Worker never invents IDs like `proj_abc123`. Always uses UUIDs from tool results. | Grep logs for `proj_` prefix |
| 12.3 | Max rounds safety | After 10 rounds, loop stops. No infinite tool calling. | Config: `tools.max_rounds: 10` |
| 12.4 | Tool failure handling | If a tool returns 404/error, worker gets error in `<tool_result>`, can retry or report. | Graceful error in chat |
| 12.5 | `tool:executed` WebSocket events | After each tool execution, backend sends `tool:executed` event via WS | Frontend receives payload with tool name, args, result |
| 12.6 | `success: true` in results | All successful REST tool results include `success: true` field | `mcp_server.py` injects it |

---

## TEST 13: Identity & Personality

| # | Step | Expected | Verify |
|---|------|----------|--------|
| 13.1 | "Who are you?" | Says she's **Voxy**, running in Voxyflow. NOT "Claude" or "AI assistant". | Identity priming working |
| 13.2 | "Can you search the web?" | "Yes" — via workers/dispatch. NOT "I don't have web access". | Knows capabilities |
| 13.3 | "Can you create cards?" | "Yes" — via dispatch. | Knows card creation |
| 13.4 | `/new` then immediately ask for search | Dispatches correctly. Identity priming works on fresh session. | Priming messages injected |
| 13.5 | No `<delegate>` XML leak | User NEVER sees raw `<delegate>` blocks in chat | Frontend strips/hides them |

---

## TEST 14: Session Isolation

| # | Step | Expected | Verify |
|---|------|----------|--------|
| 14.1 | Chat in General → switch to Project → switch back | General chat history preserved. Project chat separate. | Messages filtered by session |
| 14.2 | Chat in Card A → close → open Card B | Card B chat is independent. No Card A messages. | Session per card |
| 14.3 | Multiple session tabs in project | Each tab has its own history. Switching tabs changes messages. | `appState.sessions[projectId]` |

---

## TEST 15: Edge Cases & Robustness

| # | Step | Expected | Verify |
|---|------|----------|--------|
| 15.1 | Empty message send | Nothing happens. No error. No empty bubble. | Input validation |
| 15.2 | 1000+ char message | Handled normally. No truncation. | Long text support |
| 15.3 | Rapid-fire 3 messages | All processed sequentially. No duplication. No crash. | Message dedup |
| 15.4 | Refresh mid-conversation | History preserved from backend. | `loadHistoryFromBackend()` |
| 15.5 | Open in 2 tabs | Independent sessions. No WebSocket conflict. | Separate WS connections |
| 15.6 | Worker timeout (>30s) | Graceful error message. No hang. | `timeout_per_tool_seconds: 30` |
| 15.7 | WebSocket disconnect/reconnect | Auto-reconnect. No lost state. | Connection state management |
| 15.8 | Delete project while in project chat | Graceful redirect to general. No crash. | Error handling |

---

## TEST 16: Cross-Scope Navigation

| # | Step | Expected | Verify |
|---|------|----------|--------|
| 16.1 | General → click project → click card → close card → back to general | Each transition: correct scope, correct tools, correct chat history | `getChatLevel()` updates at each step |
| 16.2 | Create project in General → navigate to it → create cards in Project scope | Full workflow: project appears in sidebar, cards appear in kanban | End-to-end CRUD |
| 16.3 | Ctrl+K → search project → click | Navigates to project. Context switches correctly. | Command palette navigation |

---

## Execution Notes

- **Backend logs:** `tail -f /tmp/voxyflow-backend.log`
- **Browser testing (ROG):** `ssh jcviau@100.67.12.87`, Playwright at `~/browser-test/`
- **After each test:** Note Status (✅ ❌ ⚠️ ⏭️) and any observations
- **Regression:** After fixing a bug, re-run the affected test + all tests in that section

---

## Status Key

| Symbol | Meaning |
|--------|---------|
| ✅ | Pass |
| ❌ | Fail — describe what happened |
| ⚠️ | Partial — works but with issues |
| ⏭️ | Skipped — feature not ready |

---

_v3 — 2026-03-21: Full functional E2E. 16 sections, ~70 tests. Covers all 3 scopes, tool sequences, context passing, real-time updates, identity, and edge cases._
