# Worker Panel Redesign — WebSocket-First Monitoring

> Replace polling-heavy worker monitoring with WebSocket push + structured hierarchy view.

---

## Problem

The frontend polls 4 REST endpoints every ~3 seconds per browser tab:

| Endpoint | Interval | Hits DB? |
|----------|----------|----------|
| `GET /api/worker-tasks?status=pending&project_id=...` | 3s | Yes (SQLite) |
| `GET /api/worker-tasks?status=running&project_id=...` | 3s | Yes (SQLite) |
| `GET /api/workers/sessions?project_id=...` | 3s | No (in-memory) |
| `GET /api/cli-sessions/active` | 5s | No (in-memory) |

That's **~100 HTTP requests/minute** per tab. This saturated the SQLite connection pool (forced StaticPool workaround), floods logs, and the UI has no structured hierarchy view.

Meanwhile, the backend **already emits** rich WebSocket events (`task:started`, `task:progress`, `task:completed`, `tool:executed`) that the frontend only uses as supplements.

---

## Target Architecture

```
Current:  Polling (primary) → REST → SQLite / in-memory
Target:   Initial load (once) → REST snapshot
          WebSocket (primary) → push all updates
          Visibility resume → REST re-sync
```

---

## Phase 1: Backend — Snapshot Endpoint + CLI Events

### 1.1 New Consolidated Snapshot Endpoint

**File:** `backend/app/routes/workers.py`

```
GET /api/workers/snapshot?project_id=<id>
```

Returns the complete worker state in one call. Reads from in-memory stores only (WorkerSessionStore + CliSessionRegistry), never SQLite.

Response:
```json
{
  "workers": [{
    "taskId": "task-abc12345",
    "projectId": "proj-123",
    "cardId": "card-456",
    "chatId": "project:proj-123",
    "action": "implement_feature",
    "description": "Add authentication...",
    "model": "sonnet",
    "status": "running",
    "startedAt": 1712345678000,
    "completedAt": null,
    "toolCount": 12,
    "lastTool": "file_write"
  }],
  "cliSessions": [{
    "id": "cli-abc123",
    "pid": 12345,
    "chatId": "project:proj-123",
    "model": "sonnet",
    "type": "worker",
    "startedAt": 1712345678,
    "taskId": "task-abc12345"
  }],
  "timestamp": 1712345678000
}
```

### 1.2 CLI Session WebSocket Events

**File:** `backend/app/services/cli_session_registry.py`

Add broadcasts on register/deregister:
- `cli:session:started` — emitted in `register()` via `ws_broadcast.emit_sync()`
- `cli:session:ended` — emitted in `deregister()` via `ws_broadcast.emit_sync()`

### 1.3 Enrich Existing Task Events

**File:** `backend/app/services/orchestration/worker_pool.py`

- Add `projectId` to `task:started` event payload (line ~433)
- Add `toolCount` to `task:progress` event payload (line ~500)
- Make inline tool callback (line ~538) use `_send_task_event` for broadcast consistency

---

## Phase 2: Frontend — New Store + Sync Hook

### 2.1 Zustand Store: `useWorkerStore.ts`

**New file:** `frontend-react/src/stores/useWorkerStore.ts`

```typescript
interface WorkerInfo {
  taskId: string;
  projectId: string | null;
  cardId: string | null;
  chatId: string | null;
  action: string;
  description: string;
  model: 'haiku' | 'sonnet' | 'opus';
  status: 'pending' | 'running' | 'done' | 'failed' | 'cancelled';
  startedAt: number;
  completedAt?: number;
  resultSummary?: string;
  toolCount: number;
  lastTool?: string;
}

interface CliSessionInfo {
  id: string;
  pid: number;
  chatId: string;
  projectId: string | null;
  model: string;
  type: 'chat' | 'worker';
  startedAt: number;
  taskId: string;
}

interface WorkerState {
  workers: Record<string, WorkerInfo>;       // keyed by taskId
  cliSessions: Record<string, CliSessionInfo>; // keyed by CLI session id

  // Actions
  loadSnapshot: (projectId: string) => Promise<void>;
  handleTaskStarted: (payload) => void;
  handleTaskProgress: (payload) => void;
  handleTaskCompleted: (payload) => void;
  handleTaskCancelled: (payload) => void;
  handleToolExecuted: (payload) => void;
  handleCliSessionStarted: (payload) => void;
  handleCliSessionEnded: (payload) => void;

  // Selectors
  getWorkersByProject: (projectId: string) => WorkerInfo[];
  getWorkersByCard: (cardId: string) => WorkerInfo[];
  getGeneralWorkers: () => WorkerInfo[];
  getActiveCount: () => number;
}
```

Not persisted — worker state is ephemeral.

### 2.2 Sync Hook: `useWorkerSync.ts`

**New file:** `frontend-react/src/hooks/useWorkerSync.ts`

Wires WebSocket subscriptions to the Zustand store. Mounted once in AppShell.

- `loadSnapshot()` fires: on mount, on project change, on WS reconnect, on tab visibility resume
- Subscribes to: `task:started`, `task:progress`, `task:completed`, `task:cancelled`, `tool:executed`, `cli:session:started`, `cli:session:ended`

---

## Phase 3: Redesigned WorkerPanel

### 3.1 Hierarchy View

**File:** `frontend-react/src/components/RightPanel/WorkerPanel.tsx`

Complete rewrite. Pure view over Zustand store — no local state, no polling.

```
Workers (3 active)
├── Project: MyApp
│   ├── Chat: "Help me fix auth"
│   │   └── 🔵 sonnet — implement_feature — 45s… [cancel]
│   ├── Card: "Fix login bug"
│   │   └── 🟣 opus — fix_bug — 2m 12s… [cancel]
│   └── Direct
│       └── 🟡 haiku — enrich_card — 8s ✓
└── General
    └── 🔵 sonnet — research — 1m 30s…
```

Grouping logic:
1. Group by `projectId` (null = "General")
2. Within project: group by `cardId` (card context) or `chatId` (chat context) or "Direct"
3. Within group: running first, then by startedAt descending

### 3.2 Remove CLI Sessions Panel from Sidebar

**Files:**
- `frontend-react/src/components/Navigation/CliSessionsBadge.tsx` — **Delete entirely**
- `frontend-react/src/components/Navigation/Sidebar.tsx` — Remove `<CliSessionsBadge />` import (line 46) and usage (line 417)

The CLI sessions mini-panel in the sidebar is redundant once the WorkerPanel shows the full hierarchy with CLI process info. All CLI session data (pid, model, duration, linked taskId) moves into the WorkerPanel hierarchy as sub-items under their corresponding worker tasks.

Replace with a simple active worker count badge in the sidebar if needed (reading `useWorkerStore.getActiveCount()`).

---

## Phase 4: Cleanup

1. Delete `frontend-react/src/hooks/useCliSessions.ts`
2. Delete `frontend-react/src/components/Navigation/CliSessionsBadge.tsx`
3. Remove `<CliSessionsBadge />` from `Sidebar.tsx`
4. Gut `frontend-react/src/hooks/api/useWorkerTasks.ts` (keep types only)
5. Add deprecation headers to old polling endpoints
6. Monitor logs for remaining polling calls

---

## Edge Cases

| Scenario | Solution |
|----------|----------|
| Initial page load | `loadSnapshot()` — 1 REST call instead of 5 every 3s |
| WS disconnect | Re-fetch snapshot on `ws:connected` event |
| Tab hidden long time | `visibilitychange` handler re-fetches snapshot |
| Multiple tabs | `ws_broadcast.emit_to_others()` already handles this |
| No project context | Group under "General" section (`projectId = null`) |
| Missed events | Backend `pending_store` mechanism + snapshot re-sync |

---

## Impact

| Metric | Before | After |
|--------|--------|-------|
| HTTP requests/min (idle) | ~100/tab | ~0 (WS push) |
| HTTP requests on page load | 4 | 1 |
| SQLite queries for monitoring | ~40/min | 0 (in-memory only) |
| Real-time latency | 3s polling delay | Instant (WS push) |

---

## Critical Files

**Backend (modify):**
- `backend/app/routes/workers.py` — add snapshot endpoint
- `backend/app/services/cli_session_registry.py` — add WS events
- `backend/app/services/orchestration/worker_pool.py` — enrich event payloads

**Frontend (create):**
- `frontend-react/src/stores/useWorkerStore.ts` — new store
- `frontend-react/src/hooks/useWorkerSync.ts` — new sync hook

**Frontend (rewrite):**
- `frontend-react/src/components/RightPanel/WorkerPanel.tsx` — hierarchy view

**Frontend (delete):**
- `frontend-react/src/hooks/useCliSessions.ts` — polling hook
- `frontend-react/src/hooks/api/useWorkerTasks.ts` — polling hook (keep types)
- `frontend-react/src/components/Navigation/CliSessionsBadge.tsx` — sidebar mini-panel (replaced by WorkerPanel hierarchy)

**Frontend (modify):**
- `frontend-react/src/components/Navigation/Sidebar.tsx` — remove `<CliSessionsBadge />` (lines 46, 417)
