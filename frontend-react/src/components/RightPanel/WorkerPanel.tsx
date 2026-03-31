/**
 * WorkerPanel — Live view of Deep Worker tasks.
 *
 * Polling via TanStack Query (GET /api/worker-tasks, 3-second interval) with
 * real-time updates from WebSocket task events.
 */

import { useState, useEffect, useRef, useCallback } from 'react';
import { cn } from '@/lib/utils';
import { useWS } from '../../providers/WebSocketProvider';
import { useWorkerTasksQuery } from '../../hooks/api/useWorkerTasks';
import { useProjectStore } from '../../stores/useProjectStore';

// ── Types ────────────────────────────────────────────────────────────────────

interface WorkerTask {
  taskId: string;
  action: string;
  description: string;
  status: 'pending' | 'running' | 'done' | 'failed' | 'cancelled';
  startedAt: number;
  completedAt?: number;
  resultSummary?: string;
  error?: string;
  model?: 'haiku' | 'sonnet' | 'opus';
  sessionId?: string;
  expanded: boolean;
}

// ── Constants ────────────────────────────────────────────────────────────────

const STATUS_MAP: Record<string, WorkerTask['status']> = {
  pending: 'pending',
  running: 'running',
  done: 'done',
  completed: 'done',
  failed: 'failed',
  cancelled: 'cancelled',
  timed_out: 'failed',
  timeout: 'failed',
};

const TERMINAL_STATUSES = new Set<WorkerTask['status']>(['done', 'failed', 'cancelled']);

const TTL_DONE_MS = 90_000;      // 90 seconds
const TTL_ERROR_MS = 5 * 60_000; // 5 minutes

// ── Helpers ──────────────────────────────────────────────────────────────────

function getElapsed(task: WorkerTask): string {
  const end = task.completedAt ?? Date.now();
  const ms = end - task.startedAt;
  if (ms < 1000) return '<1s';
  const s = Math.floor(ms / 1000);
  if (s < 60) return `${s}s`;
  const m = Math.floor(s / 60);
  return `${m}m ${s % 60}s`;
}

function formatAction(action: string): string {
  return action.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase());
}

function getModelEmoji(model?: string): string {
  switch (model) {
    case 'haiku': return '🟡';
    case 'sonnet': return '🔵';
    case 'opus': return '🟣';
    default: return '🔵';
  }
}

function purgeExpired(tasks: Record<string, WorkerTask>): Record<string, WorkerTask> {
  const now = Date.now();
  let changed = false;
  const next = { ...tasks };
  for (const [id, task] of Object.entries(next)) {
    if (!task.completedAt) continue;
    const ttl = task.status === 'done' ? TTL_DONE_MS : TTL_ERROR_MS;
    if (now - task.completedAt > ttl) {
      delete next[id];
      changed = true;
    }
  }
  return changed ? next : tasks;
}

// ── Sub-components ────────────────────────────────────────────────────────────

interface StatusIndicatorProps {
  status: WorkerTask['status'];
}

function StatusIndicator({ status }: StatusIndicatorProps) {
  switch (status) {
    case 'pending':
      return <span className="worker-dot worker-dot--queued">⏳</span>;
    case 'running':
      return <div className="worker-spinner worker-spinner--fast" />;
    case 'done':
      return <span className="worker-dot worker-dot--done">✓</span>;
    case 'failed':
      return <span className="worker-dot worker-dot--failed">✕</span>;
    case 'cancelled':
      return <span className="worker-dot worker-dot--cancelled">⊘</span>;
    default:
      return <span className="worker-dot" />;
  }
}

interface TaskRowProps {
  task: WorkerTask;
  onCancel: (taskId: string, sessionId?: string) => void;
  onDismiss: (taskId: string) => void;
  onToggleExpand: (taskId: string) => void;
  /** Incremented every second to force elapsed-time re-renders */
  tick: number;
}

function TaskRow({ task, onCancel, onDismiss, onToggleExpand }: TaskRowProps) {
  const statusClass =
    task.status === 'done' ? 'completed'
    : task.status === 'running' ? 'executing'
    : task.status;

  const elapsed = getElapsed(task);

  return (
    <div
      className={cn('worker-task', `worker-task--${statusClass}`)}
      data-task-id={task.taskId}
    >
      {/* Status indicator */}
      <div className="worker-task-status">
        <StatusIndicator status={task.status} />
      </div>

      {/* Model badge */}
      <span className={cn('worker-model-badge', `worker-model-badge--${task.model ?? 'sonnet'}`)}>
        {getModelEmoji(task.model)}
      </span>

      {/* Content */}
      <div className="worker-task-content">
        <div className="worker-task-intent">{formatAction(task.action)}</div>
        <div className="worker-task-summary">{task.description.substring(0, 60)}</div>

        {/* Error message */}
        {task.status === 'failed' && task.error && (
          <div className="worker-task-result worker-task-result--error">
            {task.error.substring(0, 200)}
          </div>
        )}

        {/* Expandable result summary */}
        {task.completedAt && task.resultSummary && task.status !== 'failed' && (
          <div
            className="worker-task-result worker-task-result--expandable"
            style={task.resultSummary.length > 60 ? { cursor: 'pointer' } : undefined}
            onClick={
              task.resultSummary.length > 60
                ? (e) => { e.stopPropagation(); onToggleExpand(task.taskId); }
                : undefined
            }
          >
            {task.expanded
              ? task.resultSummary.substring(0, 200)
              : task.resultSummary.substring(0, 60) +
                (task.resultSummary.length > 60 ? '…' : '')}
          </div>
        )}
      </div>

      {/* Elapsed time */}
      <div className="worker-task-time">
        {task.completedAt ? elapsed : `${elapsed}…`}
      </div>

      {/* Cancel button for active tasks */}
      {!task.completedAt && (
        <button
          className="worker-task-cancel"
          title="Cancel task"
          onClick={(e) => { e.stopPropagation(); onCancel(task.taskId, task.sessionId); }}
        >
          &times;
        </button>
      )}

      {/* Dismiss button for failed/cancelled tasks */}
      {(task.status === 'failed' || task.status === 'cancelled') && (
        <button
          className="worker-task-dismiss"
          title="Dismiss"
          onClick={(e) => { e.stopPropagation(); onDismiss(task.taskId); }}
        >
          ✕
        </button>
      )}
    </div>
  );
}

// ── Main component ────────────────────────────────────────────────────────────

export function WorkerPanel() {
  const [tasks, setTasks] = useState<Record<string, WorkerTask>>({});
  const [collapsed, setCollapsed] = useState(false);
  const [tick, setTick] = useState(0);

  const dismissedIds = useRef<Set<string>>(new Set());

  const { send, subscribe } = useWS();
  const currentProjectId = useProjectStore((s) => s.currentProjectId) ?? undefined;

  // ── Polling ────────────────────────────────────────────────────────────────

  const { data: polledTasks, refetch } = useWorkerTasksQuery(currentProjectId);

  // Merge polled tasks into local state
  useEffect(() => {
    if (!polledTasks) return;
    setTasks((prev) => {
      const next = { ...prev };
      let changed = false;
      for (const t of polledTasks) {
        if (dismissedIds.current.has(t.id)) continue;
        const existing = next[t.id];
        // Don't overwrite a locally-terminal task with a stale poll result
        if (existing && TERMINAL_STATUSES.has(existing.status)) continue;

        const apiStatus: WorkerTask['status'] = STATUS_MAP[t.status] ?? 'running';
        const startedAt = t.started_at
          ? new Date(t.started_at).getTime()
          : new Date(t.created_at).getTime();
        const completedAt = t.completed_at
          ? new Date(t.completed_at).getTime()
          : TERMINAL_STATUSES.has(apiStatus)
          ? Date.now()
          : undefined;

        next[t.id] = {
          taskId: t.id,
          action: t.action || 'unknown',
          description: t.description || '',
          status: apiStatus,
          startedAt,
          completedAt,
          resultSummary: t.result_summary ?? undefined,
          error: t.error ?? undefined,
          model: (t.model as WorkerTask['model']) ?? 'sonnet',
          sessionId: t.session_id,
          expanded: existing?.expanded ?? false,
        };
        changed = true;
      }
      return changed ? next : prev;
    });
  }, [polledTasks]);

  // ── WebSocket events ───────────────────────────────────────────────────────

  const handleWsEvent = useCallback(
    (
      eventType: 'started' | 'progress' | 'completed' | 'cancelled' | 'timeout',
      payload: Record<string, unknown>,
    ) => {
      const taskId = payload.taskId as string;
      if (!taskId) return;

      setTasks((prev) => {
        if (dismissedIds.current.has(taskId)) return prev;
        const existing = prev[taskId];

        if (eventType === 'started') {
          if (existing) return prev; // already tracked
          return {
            ...prev,
            [taskId]: {
              taskId,
              action: (payload.intent as string) || 'unknown',
              description: (payload.summary as string) || '',
              status: 'running',
              startedAt: Date.now(),
              model: (payload.model as WorkerTask['model']) ?? 'sonnet',
              sessionId: payload.sessionId as string | undefined,
              expanded: false,
            },
          };
        }

        if (!existing) return prev; // unknown task — ignore

        if (eventType === 'progress') {
          if (TERMINAL_STATUSES.has(existing.status)) return prev;
          return { ...prev, [taskId]: { ...existing, status: 'running' } };
        }

        if (eventType === 'completed') {
          return {
            ...prev,
            [taskId]: {
              ...existing,
              status: (payload.success as boolean) ? 'done' : 'failed',
              completedAt: Date.now(),
              resultSummary: (payload.result as string) ?? undefined,
              error: (payload.success as boolean)
                ? undefined
                : ((payload.result as string) || 'Task failed'),
            },
          };
        }

        if (eventType === 'cancelled') {
          return {
            ...prev,
            [taskId]: { ...existing, status: 'cancelled', completedAt: Date.now() },
          };
        }

        if (eventType === 'timeout') {
          return {
            ...prev,
            [taskId]: {
              ...existing,
              status: 'failed',
              completedAt: Date.now(),
              error: `Timed out after ${(payload.timeout_seconds as number) ?? '?'}s`,
            },
          };
        }

        return prev;
      });
    },
    [],
  );

  useEffect(() => {
    const unsubs = [
      subscribe('task:started', (p) => handleWsEvent('started', p)),
      subscribe('task:progress', (p) => handleWsEvent('progress', p)),
      subscribe('task:completed', (p) => handleWsEvent('completed', p)),
      subscribe('task:cancelled', (p) => handleWsEvent('cancelled', p)),
      subscribe('task:timeout', (p) => handleWsEvent('timeout', p)),
      // Re-fetch on WS reconnect for immediate consistency
      subscribe('ws:connected', () => { void refetch(); }),
    ];
    return () => unsubs.forEach((u) => u());
  }, [subscribe, handleWsEvent, refetch]);

  // ── Elapsed time ticker ───────────────────────────────────────────────────

  useEffect(() => {
    const timer = setInterval(() => setTick((t) => t + 1), 1000);
    return () => clearInterval(timer);
  }, []);

  // ── Periodic TTL cleanup ──────────────────────────────────────────────────

  useEffect(() => {
    const timer = setInterval(() => {
      setTasks((prev) => {
        const next = purgeExpired(prev);
        if (next !== prev) {
          // Add purged IDs to dismissed set
          for (const id of Object.keys(prev)) {
            if (!(id in next)) dismissedIds.current.add(id);
          }
        }
        return next;
      });
    }, 30_000);
    return () => clearInterval(timer);
  }, []);

  // ── Visibility re-sync ────────────────────────────────────────────────────

  useEffect(() => {
    const handler = () => {
      if (document.visibilityState === 'visible') {
        void refetch();
        setTasks((prev) => purgeExpired(prev));
      }
    };
    document.addEventListener('visibilitychange', handler);
    return () => document.removeEventListener('visibilitychange', handler);
  }, [refetch]);

  // ── Actions ───────────────────────────────────────────────────────────────

  const cancelTask = useCallback(
    (taskId: string, sessionId?: string) => {
      if (!sessionId) return;
      send('task:cancel', { taskId, sessionId });
    },
    [send],
  );

  const dismissTask = useCallback((taskId: string) => {
    dismissedIds.current.add(taskId);
    setTasks((prev) => {
      const next = { ...prev };
      delete next[taskId];
      return next;
    });
  }, []);

  const clearTerminalTasks = useCallback(() => {
    setTasks((prev) => {
      const next = { ...prev };
      for (const [id, task] of Object.entries(next)) {
        if (TERMINAL_STATUSES.has(task.status)) {
          dismissedIds.current.add(id);
          delete next[id];
        }
      }
      return next;
    });
  }, []);

  const toggleExpand = useCallback((taskId: string) => {
    setTasks((prev) => {
      const task = prev[taskId];
      if (!task) return prev;
      return { ...prev, [taskId]: { ...task, expanded: !task.expanded } };
    });
  }, []);

  // ── Derived values ────────────────────────────────────────────────────────

  // Apply TTL purge before computing display
  const displayTasks = purgeExpired(tasks);
  const sorted = Object.values(displayTasks).sort((a, b) => {
    const aActive = !a.completedAt ? 0 : 1;
    const bActive = !b.completedAt ? 0 : 1;
    if (aActive !== bActive) return aActive - bActive;
    return b.startedAt - a.startedAt;
  });

  const activeCount = sorted.filter((t) => !t.completedAt).length;
  const terminalCount = sorted.filter((t) => TERMINAL_STATUSES.has(t.status)).length;

  // ── Render ────────────────────────────────────────────────────────────────

  return (
    <div
      className={cn('worker-panel', collapsed && 'collapsed')}
      data-testid="worker-panel"
    >
      {/* Header */}
      <div className="worker-panel-header">
        <div className="worker-panel-title-row">
          <span className="worker-panel-title">Workers</span>
          {activeCount > 0 && (
            <span className="worker-panel-badge">{activeCount}</span>
          )}
        </div>

        {terminalCount > 0 && (
          <button
            className="worker-panel-clear-dead"
            title="Clear finished tasks"
            onClick={clearTerminalTasks}
          >
            Clear ({terminalCount})
          </button>
        )}

        <button
          className="worker-panel-collapse"
          title={collapsed ? 'Expand' : 'Collapse'}
          onClick={() => setCollapsed((c) => !c)}
        >
          {collapsed ? '◀' : '▶'}
        </button>
      </div>

      {/* Body */}
      {!collapsed && (
        <div className="worker-panel-body">
          {sorted.length === 0 ? (
            <div className="worker-panel-empty">No active workers</div>
          ) : (
            sorted.map((task) => (
              <TaskRow
                key={task.taskId}
                task={task}
                onCancel={cancelTask}
                onDismiss={dismissTask}
                onToggleExpand={toggleExpand}
                tick={tick}
              />
            ))
          )}
        </div>
      )}
    </div>
  );
}
