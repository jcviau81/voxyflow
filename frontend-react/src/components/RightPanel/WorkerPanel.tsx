/**
 * WorkerPanel — Live view of Deep Worker tasks.
 *
 * Polling via TanStack Query (GET /api/worker-tasks, 3-second interval) with
 * real-time updates from WebSocket task events.
 */

import { useState, useEffect, useRef, useCallback } from 'react';
import { Loader2 } from 'lucide-react';
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
      return <Loader2 size={14} className="text-muted-foreground animate-spin" />;
    case 'running':
      return <div className="w-3.5 h-3.5 border-2 border-accent border-t-transparent rounded-full animate-spin [animation-duration:0.5s]" />;
    case 'done':
      return <span className="inline-flex items-center justify-center w-3.5 h-3.5 text-[10px] font-bold text-green-500">✓</span>;
    case 'failed':
      return <span className="inline-flex items-center justify-center w-3.5 h-3.5 text-[10px] font-bold text-red-500">✕</span>;
    case 'cancelled':
      return <span className="inline-flex items-center justify-center w-3.5 h-3.5 text-[10px] font-bold text-muted-foreground">⊘</span>;
    default:
      return <span className="inline-flex items-center justify-center w-3.5 h-3.5 text-[10px] font-bold" />;
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
  const elapsed = getElapsed(task);

  const statusClasses =
    task.status === 'running' ? 'border-accent border-l-[3px]'
    : task.status === 'done' ? 'opacity-65 border-green-500 border-l-[3px]'
    : task.status === 'failed' ? 'opacity-75 border-red-500 border-l-[3px]'
    : task.status === 'cancelled' ? 'opacity-65 border-muted-foreground border-l-[3px]'
    : '';

  const modelBgClass =
    task.model === 'haiku' ? 'bg-yellow-500/20'
    : task.model === 'opus' ? 'bg-purple-500/20'
    : 'bg-blue-500/20';

  return (
    <div
      className={cn(
        'flex items-start gap-2 p-2 bg-muted/50 rounded-lg border border-border transition-all duration-200',
        statusClasses,
      )}
      data-task-id={task.taskId}
    >
      {/* Status indicator */}
      <div className="shrink-0">
        <StatusIndicator status={task.status} />
      </div>

      {/* Model badge */}
      <span className={cn('inline-flex items-center justify-center w-5 h-5 rounded text-xs shrink-0 mt-px', modelBgClass)}>
        {getModelEmoji(task.model)}
      </span>

      {/* Content */}
      <div className="flex-1 min-w-0">
        <div className="text-xs font-semibold text-foreground truncate">{formatAction(task.action)}</div>
        <div className="text-xs text-muted-foreground truncate">{task.description.substring(0, 60)}</div>

        {/* Error message */}
        {task.status === 'failed' && task.error && (
          <div className="text-xs mt-1 text-red-400">
            {task.error.substring(0, 200)}
          </div>
        )}

        {/* Expandable result summary */}
        {task.completedAt && task.resultSummary && task.status !== 'failed' && (
          <div
            className={cn(
              'text-xs mt-1 text-muted-foreground',
              task.resultSummary.length > 60 && 'cursor-pointer hover:text-foreground',
            )}
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
      <div className="shrink-0 text-[10px] text-muted-foreground tabular-nums">
        {task.completedAt ? elapsed : `${elapsed}…`}
      </div>

      {/* Cancel button for active tasks */}
      {!task.completedAt && (
        <button
          className="shrink-0 text-xs text-muted-foreground hover:text-red-400 transition-colors"
          title="Cancel task"
          onClick={(e) => { e.stopPropagation(); onCancel(task.taskId, task.sessionId); }}
        >
          &times;
        </button>
      )}

      {/* Dismiss button for failed/cancelled tasks */}
      {(task.status === 'failed' || task.status === 'cancelled') && (
        <button
          className="shrink-0 text-xs text-muted-foreground hover:text-red-400 transition-colors"
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
      className={cn(
        'flex flex-col h-full bg-secondary border-l border-r border-border shrink-0 overflow-hidden transition-all duration-200',
        collapsed ? 'w-[42px]' : 'w-60',
      )}
      data-testid="worker-panel"
    >
      {/* Header */}
      <div className="flex items-center justify-between px-3 py-2 border-b border-border shrink-0">
        <div className="flex items-center gap-2">
          <span className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">Workers</span>
          {activeCount > 0 && (
            <span className="bg-primary text-primary-foreground text-xs font-bold px-1.5 rounded-full min-w-[18px] text-center">{activeCount}</span>
          )}
        </div>

        {terminalCount > 0 && (
          <button
            className="text-xs text-muted-foreground hover:text-foreground transition-colors cursor-pointer"
            title="Clear finished tasks"
            onClick={clearTerminalTasks}
          >
            Clear ({terminalCount})
          </button>
        )}

        <button
          className="text-xs text-muted-foreground hover:text-foreground transition-colors cursor-pointer"
          title={collapsed ? 'Expand' : 'Collapse'}
          onClick={() => setCollapsed((c) => !c)}
        >
          {collapsed ? '◀' : '▶'}
        </button>
      </div>

      {/* Body */}
      {!collapsed && (
        <div className="flex-1 overflow-y-auto p-2 flex flex-col gap-2">
          {sorted.length === 0 ? (
            <div className="text-xs text-muted-foreground text-center py-8">No active workers</div>
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
