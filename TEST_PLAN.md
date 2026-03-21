# Voxyflow — Manual Test Plan

_Run these in browser at `http://thething:3000`. Backend must be on port 8000._

---

## 1. App Launch & First Load

| # | Action | Expected |
|---|--------|----------|
| 1.1 | Open `http://thething:3000` | App loads, no console errors, sidebar visible |
| 1.2 | Check Main Chat | Welcome prompt or greeting appears. Voxy says hi (1 sentence). |
| 1.3 | Check sidebar | Projects listed (if any), navigation works |

---

## 2. Chat — Basic Conversation

| # | Action | Expected |
|---|--------|----------|
| 2.1 | Type "Hey, how are you?" | Voxy responds conversationally. No `<delegate>` block. No tool usage. |
| 2.2 | Type in French "Salut, ça va?" | Voxy responds in French. Matches language. |
| 2.3 | Type a long message (3+ sentences) | Voxy responds proportionally. Not a one-liner. |
| 2.4 | Check streaming | Response streams token by token, not all at once. |

---

## 3. Chat — Dispatch & Workers

| # | Action | Expected |
|---|--------|----------|
| 3.1 | Type "Search the web for the latest NHL scores" | Voxy says "I'll handle that" or similar + dispatches. Worker runs in background. Result appears as a NEW message in chat. |
| 3.2 | While worker runs, type "What's 2+2?" | Voxy responds immediately. Chat is NOT blocked by the worker. |
| 3.3 | Type "Create a card on my board called 'Test Card'" | Voxy dispatches to haiku worker. Card appears on Main Board. |
| 3.4 | Type "Create a card in [ProjectName] called 'Bug Fix'" | Card created in the correct project's kanban. |

---

## 4. Session Management

| # | Action | Expected |
|---|--------|----------|
| 4.1 | Type `/new` | Chat clears. New greeting appears. Fresh session. |
| 4.2 | After `/new`, type something | Voxy responds without referencing old conversation. |
| 4.3 | Click session tabs (if multiple) | Switches session. Messages change. |

---

## 5. Main Board (Cards)

| # | Action | Expected |
|---|--------|----------|
| 5.1 | Navigate to Board tab (📝) | Main Board shows existing cards (if any). |
| 5.2 | Click "+" or create card | Card form appears. Can set title, description, color. |
| 5.3 | Click on a card | Card detail modal opens. Chat panel visible on right side. |
| 5.4 | In card modal, type a message | Voxy responds IN CONTEXT of that card. Knows card title/description. |
| 5.5 | Card modal: Voxy does NOT auto-chat | Opening a card = silence. Voxy waits for user to speak first. |
| 5.6 | Close card modal | Returns to board. No errors. |

---

## 6. Projects

| # | Action | Expected |
|---|--------|----------|
| 6.1 | Click "+" to create project | Project form: title, description, tech stack. |
| 6.2 | Create project "Test Project" | Project appears in sidebar. |
| 6.3 | Open project | Project view loads (kanban, chat, etc.). |
| 6.4 | In project chat, type "Hey" | Voxy responds in project context. Knows project name. |
| 6.5 | In project chat, say "Add a card called 'Feature X'" | Voxy dispatches. Card appears in project kanban. |

---

## 7. Kanban Board

| # | Action | Expected |
|---|--------|----------|
| 7.1 | Open a project with cards | Kanban shows columns: Idea / Todo / In Progress / Done |
| 7.2 | Drag card between columns | Card moves. Status updates. |
| 7.3 | Click card in kanban | Card detail modal opens with context. |
| 7.4 | Create card via kanban "+" | Card appears in correct column. |

---

## 8. Nomenclature (CRITICAL)

| # | Action | Expected |
|---|--------|----------|
| 8.1 | In main chat: "Add a card to my board" | Voxy creates card on Main Board. Does NOT say "note". |
| 8.2 | In main chat: "Add a card" (no project) | Voxy creates on Main Board OR asks which project. NEVER says "note". |
| 8.3 | In project chat: "Add a card" | Card created in that project. No confusion. |
| 8.4 | Say "Add a note" | Voxy treats it as "card". Does NOT ask "note or card?" |

---

## 9. Identity & Priming

| # | Action | Expected |
|---|--------|----------|
| 9.1 | `/new` then immediately ask for web search | Voxy dispatches via `<delegate>`. Does NOT do the search herself. Does NOT say "I don't have access". |
| 9.2 | Ask "Who are you?" | Says she's Voxy, in Voxyflow. NOT "I'm Claude" or "I'm an AI assistant". |
| 9.3 | Ask "Can you search the web?" | Says yes, via dispatch/workers. Does NOT say "I don't have web search available". |

---

## 10. Voice (if enabled)

| # | Action | Expected |
|---|--------|----------|
| 10.1 | Click 🎤 microphone button | STT activates. Browser asks for mic permission (first time). |
| 10.2 | Speak a message | Text appears in input. Sends on release. |
| 10.3 | Click 🔊 on Voxy's response | TTS reads the message aloud. |

---

## 11. Settings

| # | Action | Expected |
|---|--------|----------|
| 11.1 | Open Settings (⚙️) | Settings page loads. Model config visible. |
| 11.2 | Change tone/warmth | Saves. Next Voxy response reflects the change. |
| 11.3 | Return to chat | Navigation works. Chat state preserved. |

---

## 12. Dark/Light Theme

| # | Action | Expected |
|---|--------|----------|
| 12.1 | Toggle theme (🌙/☀️) | Theme switches immediately. All components update. |
| 12.2 | Refresh page | Theme persists. |

---

## 13. Command Palette

| # | Action | Expected |
|---|--------|----------|
| 13.1 | Press Ctrl+K | Command palette opens. |
| 13.2 | Type a project name | Fuzzy search finds it. Click → navigates. |
| 13.3 | Press Escape | Palette closes. |

---

## 14. Worker Results Display

| # | Action | Expected |
|---|--------|----------|
| 14.1 | Ask Voxy to do a web search | Worker dispatched. Result appears as message in chat (not just toast). |
| 14.2 | Ask Voxy to create a card | Worker dispatched. Confirmation message appears in chat. |
| 14.3 | Check toast notifications | Toast shows briefly (4s) as secondary notification. |

---

## 15. Edge Cases

| # | Action | Expected |
|---|--------|----------|
| 15.1 | Send empty message | Nothing happens. No error. |
| 15.2 | Send very long message (1000+ chars) | Voxy handles it. No truncation. |
| 15.3 | Rapid-fire 3 messages | All processed. No duplication. No crash. |
| 15.4 | Refresh page mid-conversation | Page reloads. Chat history preserved (loaded from backend). |
| 15.5 | Open app in second tab | Works independently. No conflicts. |

---

## Status Key

- ✅ Pass
- ❌ Fail (describe what happened)
- ⚠️ Partial (works but with issues)
- ⏭️ Skipped (feature not available/applicable)

---

_Last updated: 2026-03-21_
