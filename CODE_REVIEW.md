# Voxyflow Code Review

**Date:** 2026-03-21
**Scope:** Backend (Python/FastAPI), Frontend (TypeScript), Personality, Config
**Reviewer:** Claude Opus 4.6

---

## RED CRITICAL — Will crash or break functionality

### CR-01: UI-created project cards never persist to database
**Files:** `frontend/src/services/CardService.ts:69-78`, `backend/app/main.py:264-270`
**Impact:** Data loss on page reload

`CardService.create()` adds the card to local state (localStorage) and sends a `card:create` WebSocket message. However, the backend WebSocket handler (`main.py:264`) only handles `ping`, `chat:message`, and `session:reset` — all other message types receive a generic `ack` and are silently discarded. No REST `POST /api/projects/{project_id}/cards` call is ever made.

The same applies to:
- `CardService.update()` (line 85) — sends `card:update` WS, never calls REST PATCH
- `CardService.delete()` (line 90) — sends `card:delete` WS, never calls REST DELETE
- `CardService.move()` (line 95) — sends `card:move` WS, never calls REST PATCH

Cards created via the UI CardForm exist only in localStorage. On reload, `ApiClient.fetchCards()` fetches from the REST API and the cards are gone.

Compare with `MainBoardService` which correctly uses REST for all CRUD — the project card path is missing this.

**Suggested fix:** Either:
1. Add REST calls in `CardService` (like `MainBoardService` does), or
2. Implement WebSocket message handlers in `main.py` that call the existing REST endpoints

---

### CR-02: Follow-up REST calls on non-existent cards (404 cascade)
**Files:** `frontend/src/App.ts:566-570`, `frontend/src/App.ts:579-581`
**Impact:** Silent failures after card creation

After `cardService.create()` (which never persists — see CR-01), `App.ts` uses `setTimeout` to call:
- `apiClient.patchCard(newCard.id, patchData)` at line 570 (500ms delay)
- `apiClient.enrichCard(cardIdToEnrich)` at line 581 (1200ms delay)

Both hit `PATCH /api/cards/{id}` and `POST /api/cards/{id}/enrich` respectively. Since the card doesn't exist in the DB, these return 404. The errors are caught but only logged to console — no user feedback.

**Suggested fix:** Fix CR-01 first. Then chain the follow-up calls to the creation response instead of using setTimeout.

---

### CR-03: Status format mismatch — `"in-progress"` (hyphen) vs `"in_progress"` (underscore)
**Files:** `backend/app/routes/projects.py:642,717,962,1472,1518,1578`, `backend/app/models/card.py:13,36`, `frontend/src/types/index.ts:4`
**Impact:** AI standup, health check, and prioritization logic silently skip all in-progress cards

The backend has two conflicting conventions:
- **Pydantic models** (`card.py:13`): `pattern="^(note|idea|todo|in_progress|done|archived)$"` — underscore
- **Database schema** (`database.py:223`): Comment says `in_progress` — underscore
- **MCP tool** (`mcp_server.py:232`): `enum: ["idea", "todo", "in_progress", "done", "archived"]` — underscore
- **projects.py** (6 locations): Compares against `"in-progress"` — hyphen
- **Frontend** (`types/index.ts:4`, `constants.ts:30`): Uses `'in-progress'` — hyphen

Result: `projects.py` AI endpoints (standup, health, prioritize) filter cards with `c.status == "in-progress"` but the DB stores `in_progress`. Zero cards match, making these features silently return empty/wrong results.

**Suggested fix:** Standardize on one format. If the DB uses `in_progress`, fix `projects.py` (6 lines). If the frontend convention is canonical, update Pydantic models and MCP tool enums.

---

### CR-04: Pydantic validation rejects frontend status values
**Files:** `backend/app/models/card.py:13,36`
**Impact:** 422 Unprocessable Entity when updating card status via REST

The Pydantic `CardUpdate` model validates status with pattern `^(note|idea|todo|in_progress|done|archived)$`. If the frontend sends `{"status": "in-progress"}` (which is what `CardStatus` type defines), the regex won't match and FastAPI returns 422.

**Suggested fix:** Either update the regex to accept hyphens: `^(note|idea|todo|in[_-]progress|done|archived)$`, or normalize at the API boundary.

---

## YELLOW IMPORTANT — Should fix soon, causes bugs or confusion

### CR-05: Incomplete note-to-card nomenclature migration
**Files:** Multiple locations
**Impact:** Confusion, user-facing leakage of internal "note" terminology

SOUL.md explicitly says "NEVER say 'note' when referring to cards," but "note" persists in:

| File | Line | Usage |
|------|------|-------|
| `frontend/src/types/index.ts` | 4 | `CardStatus` includes `'note'` |
| `frontend/src/utils/constants.ts` | 31 | `ALL_CARD_STATUSES` includes `'note'` |
| `frontend/src/utils/constants.ts` | 33 | `CARD_STATUS_LABELS['note']` = `'Card'` |
| `frontend/src/services/MainBoardService.ts` | 204 | Default fallback `status: 'note'` |
| `backend/app/models/card.py` | 13, 36 | Pydantic pattern includes `note` |
| `backend/app/routes/cards.py` | 165, 171, 201, 233, 236 | Internal status set to `"note"` |
| `backend/app/mcp_server.py` | 48 | "Status defaults to 'note' internally" |
| `backend/app/database.py` | 223 | Comment lists `note` as valid |
| `backend/app/routes/cards.py` | 1225 | Deprecated `/notes` endpoint still exists |

**Suggested fix:** Decide if "note" status is truly needed internally (for unassigned cards) or if it should be renamed to something else (e.g., "unassigned"). Remove from frontend types and constants entirely.

---

### CR-06: XSS risk in markdown-to-HTML conversion
**File:** `frontend/src/utils/helpers.ts:42-78`
**Impact:** Potential XSS via crafted link URLs

`markdownToHtml()` converts markdown links to `<a href="$2">` where `$2` is user content. If `$2` contains `javascript:alert(1)` or `data:text/html,...`, it executes. The `escapeHtml()` call at the top escapes `<>&"` but doesn't sanitize URL schemes.

**Suggested fix:** Validate URL schemes in the link regex replacement:
```typescript
if (!/^https?:\/\//i.test(url)) return text; // Only allow http/https
```

---

### CR-07: Event listener memory leaks in VoiceInput
**File:** `frontend/src/components/Chat/VoiceInput.ts:35-49`
**Impact:** Memory leak, duplicate event handlers on re-render

Five event listeners (`mousedown`, `mouseup`, `mouseleave`, `touchstart`, `touchend`) are added in the constructor but never removed. No `removeEventListener` calls exist. If the component is destroyed and recreated, listeners accumulate.

**Suggested fix:** Store bound references and remove in `destroy()`:
```typescript
private boundStart = () => this.startRecording();
// In destroy(): this.button.removeEventListener('mousedown', this.boundStart);
```

---

### CR-08: Event listener memory leaks in ChatWindow
**File:** `frontend/src/components/Chat/ChatWindow.ts:81, 129-134`
**Impact:** Same as CR-07

Scroll listener (`line 81`) and multiple input listeners use `.bind(this)` which creates new function references each time — impossible to remove later. No cleanup in `destroy()`.

**Suggested fix:** Store bound references as class properties and remove in `destroy()`.

---

### CR-09: Race condition in card creation flow
**File:** `frontend/src/App.ts:564-621`
**Impact:** Agent type and enrichment data may be lost

Card creation uses cascading `setTimeout` calls (500ms for agent type, 1200ms for enrichment). If the user navigates away, closes the modal, or the backend is slow, the callbacks fire against stale state. No cancellation mechanism exists.

**Suggested fix:** Use `AbortController` or store timeout IDs for cleanup. Chain operations with `async/await` instead of arbitrary delays.

---

### CR-10: No debounce on Kanban search input
**File:** `frontend/src/components/Kanban/KanbanBoard.ts:86-99`
**Impact:** DOM thrashing on every keystroke

The search input calls `applyFilters()` synchronously on every `input` event. With many cards, this causes excessive DOM manipulation.

**Suggested fix:** Add a debounce (150-300ms) to the input handler.

---

### CR-11: Duplicate MCP config files with different Python paths
**Files:** `mcp.json:5` vs `.mcp.json:4`
**Impact:** Confusion about which is canonical, potential runtime errors

- `mcp.json`: `"command": "/home/jcviau/voxyflow/backend/venv/bin/python"`
- `.mcp.json`: `"command": "/home/jcviau/voxyflow/backend/venv/bin/python3"`

**Suggested fix:** Delete the redundant file. Use `python3` (more portable).

---

### CR-12: Broad exception catch in enrich_card
**File:** `backend/app/routes/cards.py:1220`
**Impact:** Masks real errors (API failures, network issues)

```python
except (json.JSONDecodeError, KeyError, Exception) as e:
```

Catching bare `Exception` makes debugging impossible. API key issues, network timeouts, and rate limits all get the same generic error.

**Suggested fix:** Catch specific exceptions. Let unexpected errors propagate to FastAPI's error handler.

---

### CR-13: Unchecked array access in AppState
**File:** `frontend/src/state/AppState.ts:673, 708`
**Impact:** Potential undefined access

- Line 673: `updatedList[0].id` — `updatedList` could be empty after filtering
- Line 708: `sessions[0]` fallback — `sessions` could be empty

**Suggested fix:** Add length checks before accessing index 0.

---

### CR-14: `any` types in ChatService tool handlers
**File:** `frontend/src/services/ChatService.ts:92, 436`
**Impact:** No type safety for tool result data or UI action payloads

```typescript
data: any;  // line 92
private handleToolUiAction(uiAction: string, data: any): void  // line 436
```

**Suggested fix:** Define interfaces for `ToolResultPayload` and `UIActionData`.

---

### CR-15: Frontend API URL inconsistency
**Files:** `frontend/src/services/ProjectService.ts:19-20`, `frontend/src/services/MainBoardService.ts:13-14`, `frontend/src/services/ApiClient.ts`
**Impact:** Breaks if app is deployed behind a non-root path

`ProjectService` uses hardcoded `/api/` paths. `MainBoardService` and `ApiClient` use `API_URL_BASE` from env. Inconsistent.

**Suggested fix:** All services should use `API_URL_BASE` for the base URL.

---

### CR-16: Double normalization of project name/title
**Files:** `frontend/src/state/AppState.ts:123-127`, `frontend/src/services/ProjectService.ts:169`
**Impact:** Confusion about where normalization happens

Both `AppState.loadFromStorage()` and `ProjectService.mapRawProject()` normalize backend `title` to frontend `name`. If one changes, the other masks it.

**Suggested fix:** Normalize in exactly one place (API boundary in `ProjectService`).

---

## GREEN MINOR — Nice to have, cleanup, style

### CR-17: Deprecated `/notes` endpoint returns mock data
**File:** `backend/app/routes/cards.py:1225-1239`

```python
@router.post("/notes", deprecated=True)
```

Returns a mock response and doesn't save anything. Either implement or remove.

---

### CR-18: Duplicate function-scoped imports in projects.py
**File:** `backend/app/routes/projects.py:253, 261`

`from sqlalchemy import func` and `from fastapi import HTTPException` are imported inside a function body despite being available at module level.

---

### CR-19: Hardcoded IP in settings.json
**File:** `settings.json:46`

```json
"tts_url": "http://192.168.1.59:5500"
```

Network-specific. Should use localhost or env var for portability.

---

### CR-20: restart.sh hardcoded user paths
**File:** `restart.sh:13, 18, 22`

Uses `~/voxyflow` and `~/voxyflow-proxy-fork` — breaks for other users or deployment contexts. Should use `$(dirname "$0")` or env vars.

---

### CR-21: restart.sh missing error handling
**File:** `restart.sh:6-8`

`kill $(lsof -ti:8000)` — if `lsof` returns empty, `kill` gets no args. Harmless but noisy. Should guard with `[ -n "$PID" ] && kill $PID`.

---

### CR-22: TODO stubs in SttService (incomplete Whisper integration)
**File:** `frontend/src/services/SttService.ts:228, 244`

```typescript
// TODO: Pass reader.result (ArrayBuffer) to the Whisper WebWorker
// TODO: Actual Whisper WASM loading logic goes here.
```

Dead code path — local Whisper never actually processes audio.

---

### CR-23: Inconsistent error feedback patterns
**Files:** Backend routes (various)

Some endpoints log errors before raising HTTPException, others don't. Frontend shows toast on some failures but silently swallows others (e.g., `catch(() => {/* fallback already set */})` in `CardDetailModal.ts:76`).

---

### CR-24: CSS class uses underscore while frontend uses hyphen
**File:** `frontend/src/styles/components.css:5600`

```css
.relation-status-dot--in_progress { background: #3b82f6; }
```

Frontend generates `in-progress` (hyphen). This CSS class would never match unless the status is normalized to underscore somewhere in the DOM.

---

### CR-25: Placeholder API keys in settings.json
**File:** `settings.json:17, 23, 29`

```json
"api_key": "sk-any"
```

Harmless placeholder but could accidentally be committed with real keys. Consider `.env` file with `.gitignore`.

---

## Summary

| Severity | Count | Key Theme |
|----------|-------|-----------|
| RED CRITICAL | 4 | Card persistence gap, status format mismatch |
| YELLOW IMPORTANT | 12 | Nomenclature, XSS, memory leaks, race conditions |
| GREEN MINOR | 9 | Dead code, config hardcoding, style |
| **Total** | **25** | |

**Top 3 priorities:**
1. **CR-01** — Fix card persistence (WebSocket CRUD is silently dropped)
2. **CR-03/CR-04** — Standardize status format (`in-progress` vs `in_progress`)
3. **CR-05** — Complete the note-to-card nomenclature migration
