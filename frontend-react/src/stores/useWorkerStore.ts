/**
 * useWorkerStore — Zustand store for worker task and CLI session state.
 *
 * Populated via WebSocket events + initial REST snapshot.
 * Not persisted — worker state is ephemeral.
 */

import { create } from 'zustand';
import { immer } from 'zustand/middleware/immer';

// ── Types ────────────────────────────────────────────────────────────────────

export interface WorkerInfo {
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
  error?: string;
  toolCount: number;
  lastTool?: string;
}

export interface CliSessionInfo {
  id: string;
  pid: number;
  chatId: string;
  projectId: string | null;
  model: string;
  type: 'chat' | 'worker';
  startedAt: number;
  taskId: string;
}

// TTLs for auto-purging completed tasks
const TTL_DONE_MS = 90_000;       // 90 seconds
const TTL_ERROR_MS = 5 * 60_000;  // 5 minutes

// ── Store interface ──────────────────────────────────────────────────────────

export interface WorkerState {
  workers: Record<string, WorkerInfo>;
  cliSessions: Record<string, CliSessionInfo>;
  /** Set of task IDs the user has manually dismissed */
  _dismissed: Set<string>;

  // Snapshot
  loadSnapshot: (projectId: string | null) => Promise<void>;

  // WS event handlers
  handleTaskStarted: (payload: Record<string, unknown>) => void;
  handleTaskProgress: (payload: Record<string, unknown>) => void;
  handleTaskCompleted: (payload: Record<string, unknown>) => void;
  handleTaskCancelled: (payload: Record<string, unknown>) => void;
  handleToolExecuted: (payload: Record<string, unknown>) => void;
  handleCliSessionStarted: (payload: Record<string, unknown>) => void;
  handleCliSessionEnded: (payload: Record<string, unknown>) => void;

  // Actions
  dismissTask: (taskId: string) => void;
  clearTerminal: () => void;
  purgeExpired: () => void;

  // Selectors (computed from state)
  getWorkersByProject: (projectId: string) => WorkerInfo[];
  getWorkersByCard: (cardId: string) => WorkerInfo[];
  getGeneralWorkers: () => WorkerInfo[];
  getActiveCount: () => number;
}

// ── Helpers ──────────────────────────────────────────────────────────────────

const TERMINAL_STATUSES = new Set(['done', 'failed', 'cancelled']);

function normalizeStatus(status: string): WorkerInfo['status'] {
  const map: Record<string, WorkerInfo['status']> = {
    pending: 'pending',
    running: 'running',
    done: 'done',
    completed: 'done',
    failed: 'failed',
    cancelled: 'cancelled',
    timed_out: 'failed',
    timeout: 'failed',
  };
  return map[status] ?? 'running';
}

function normalizeModel(model?: string): WorkerInfo['model'] {
  if (model === 'haiku' || model === 'sonnet' || model === 'opus') return model;
  return 'sonnet';
}

// ── Store ────────────────────────────────────────────────────────────────────

export const useWorkerStore = create<WorkerState>()(
  immer((set, get) => ({
    workers: {},
    cliSessions: {},
    _dismissed: new Set<string>(),

    // ── Snapshot ──────────────────────────────────────────────────────────

    async loadSnapshot(projectId: string | null) {
      try {
        const params = projectId ? `?project_id=${encodeURIComponent(projectId)}` : '';
        const res = await fetch(`/api/workers/snapshot${params}`);
        if (!res.ok) return;
        const data = await res.json();

        set((state) => {
          // Merge workers from snapshot (don't overwrite locally terminal tasks)
          const nextWorkers: Record<string, WorkerInfo> = {};
          for (const w of data.workers ?? []) {
            if (state._dismissed.has(w.taskId)) continue;
            const existing = state.workers[w.taskId];
            if (existing && TERMINAL_STATUSES.has(existing.status)) {
              nextWorkers[w.taskId] = existing;
              continue;
            }
            nextWorkers[w.taskId] = {
              taskId: w.taskId,
              projectId: w.projectId ?? null,
              cardId: w.cardId ?? null,
              chatId: w.chatId ?? null,
              action: w.action || 'unknown',
              description: w.description || '',
              model: normalizeModel(w.model),
              status: normalizeStatus(w.status),
              startedAt: w.startedAt || Date.now(),
              completedAt: w.completedAt ?? undefined,
              resultSummary: w.resultSummary ?? undefined,
              toolCount: w.toolCount ?? 0,
              lastTool: w.lastTool ?? undefined,
            };
          }
          state.workers = nextWorkers;

          // Replace CLI sessions entirely from snapshot
          const nextCli: Record<string, CliSessionInfo> = {};
          for (const cs of data.cliSessions ?? []) {
            nextCli[cs.id] = {
              id: cs.id,
              pid: cs.pid,
              chatId: cs.chatId,
              projectId: cs.projectId ?? null,
              model: cs.model,
              type: cs.type as 'chat' | 'worker',
              startedAt: cs.startedAt,
              taskId: cs.taskId || '',
            };
          }
          state.cliSessions = nextCli;
        });
      } catch {
        // Silently ignore fetch errors
      }
    },

    // ── WS event handlers ────────────────────────────────────────────────

    handleTaskStarted(payload) {
      const taskId = payload.taskId as string;
      if (!taskId) return;
      set((state) => {
        if (state._dismissed.has(taskId)) return;
        if (state.workers[taskId]) return; // already tracked
        state.workers[taskId] = {
          taskId,
          projectId: (payload.projectId as string) ?? null,
          cardId: (payload.cardId as string) ?? null,
          chatId: null,
          action: (payload.intent as string) || 'unknown',
          description: (payload.summary as string) || '',
          model: normalizeModel(payload.model as string),
          status: 'running',
          startedAt: Date.now(),
          toolCount: 0,
        };
      });
    },

    handleTaskProgress(payload) {
      const taskId = payload.taskId as string;
      if (!taskId) return;
      set((state) => {
        const w = state.workers[taskId];
        if (!w || TERMINAL_STATUSES.has(w.status)) return;
        w.status = 'running';
        if (typeof payload.toolCount === 'number') {
          w.toolCount = payload.toolCount;
        }
      });
    },

    handleTaskCompleted(payload) {
      const taskId = payload.taskId as string;
      if (!taskId) return;
      set((state) => {
        const w = state.workers[taskId];
        if (!w) return;
        w.status = (payload.success as boolean) ? 'done' : 'failed';
        w.completedAt = Date.now();
        w.resultSummary = (payload.result as string) ?? undefined;
        if (!payload.success) {
          w.error = (payload.result as string) || 'Task failed';
        }
      });
    },

    handleTaskCancelled(payload) {
      const taskId = payload.taskId as string;
      if (!taskId) return;
      set((state) => {
        const w = state.workers[taskId];
        if (!w) return;
        w.status = 'cancelled';
        w.completedAt = Date.now();
      });
    },

    handleToolExecuted(payload) {
      const taskId = payload.taskId as string;
      if (!taskId) return;
      set((state) => {
        const w = state.workers[taskId];
        if (!w) return;
        w.lastTool = payload.tool as string;
        if (typeof payload.toolCount === 'number') {
          w.toolCount = payload.toolCount;
        } else {
          w.toolCount += 1;
        }
      });
    },

    handleCliSessionStarted(payload) {
      const id = payload.id as string;
      if (!id) return;
      set((state) => {
        state.cliSessions[id] = {
          id,
          pid: (payload.pid as number) ?? 0,
          chatId: (payload.chatId as string) ?? '',
          projectId: (payload.projectId as string) ?? null,
          model: (payload.model as string) ?? 'sonnet',
          type: (payload.type as 'chat' | 'worker') ?? 'worker',
          startedAt: (payload.startedAt as number) ?? Date.now() / 1000,
          taskId: (payload.taskId as string) ?? '',
        };
      });
    },

    handleCliSessionEnded(payload) {
      const id = payload.id as string;
      if (!id) return;
      set((state) => {
        delete state.cliSessions[id];
      });
    },

    // ── Actions ──────────────────────────────────────────────────────────

    dismissTask(taskId: string) {
      set((state) => {
        state._dismissed.add(taskId);
        delete state.workers[taskId];
      });
    },

    clearTerminal() {
      set((state) => {
        for (const [id, w] of Object.entries(state.workers)) {
          if (TERMINAL_STATUSES.has(w.status)) {
            state._dismissed.add(id);
            delete state.workers[id];
          }
        }
      });
    },

    purgeExpired() {
      const now = Date.now();
      set((state) => {
        for (const [id, w] of Object.entries(state.workers)) {
          if (!w.completedAt) continue;
          const ttl = w.status === 'done' ? TTL_DONE_MS : TTL_ERROR_MS;
          if (now - w.completedAt > ttl) {
            state._dismissed.add(id);
            delete state.workers[id];
          }
        }
      });
    },

    // ── Selectors ────────────────────────────────────────────────────────

    getWorkersByProject(projectId: string) {
      return Object.values(get().workers).filter((w) => w.projectId === projectId);
    },

    getWorkersByCard(cardId: string) {
      return Object.values(get().workers).filter((w) => w.cardId === cardId);
    },

    getGeneralWorkers() {
      return Object.values(get().workers).filter((w) => !w.projectId);
    },

    getActiveCount() {
      return Object.values(get().workers).filter((w) => !TERMINAL_STATUSES.has(w.status)).length;
    },
  })),
);
