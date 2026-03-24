/**
 * WorkerPanel — Live view of Deep Worker tasks.
 *
 * Sits between the chat area and the Opportunities panel.
 * Shows active, queued, and recently completed worker tasks
 * with real-time progress updates via the event bus.
 */

import { eventBus } from '../../utils/EventBus';
import { EVENTS, SYSTEM_PROJECT_ID } from '../../utils/constants';
import { createElement } from '../../utils/helpers';
import { apiClient } from '../../services/ApiClient';
import { appState } from '../../state/AppState';

interface WorkerTask {
  taskId: string;
  intent: string;
  summary: string;
  status: 'queued' | 'started' | 'executing' | 'completed' | 'failed' | 'cancelled' | 'timeout' | 'stale';
  startedAt: number;
  completedAt?: number;
  result?: string;
  success?: boolean;
  progressMessage?: string;
  model?: 'haiku' | 'sonnet' | 'opus';
  sessionId?: string;
}

export class WorkerPanel {
  private container: HTMLElement;
  private tasks: Map<string, WorkerTask> = new Map();
  private purgedTaskIds: Set<string> = new Set(); // prevent re-hydration of purged tasks
  private lastUpdate: Map<string, number> = new Map(); // taskId → last WS update timestamp
  private unsubscribers: (() => void)[] = [];
  private cleanupTimer: ReturnType<typeof setInterval> | null = null;
  private elapsedTimer: ReturnType<typeof setInterval> | null = null;
  private staleTimer: ReturnType<typeof setInterval> | null = null;
  private collapsed = false;
  private onVisibilityChange = () => {
    if (document.visibilityState === 'visible') this.cleanupCompleted();
  };

  constructor(private parentElement: HTMLElement) {
    this.container = createElement('div', {
      className: 'worker-panel',
      'data-testid': 'worker-panel',
    });
    this.parentElement.appendChild(this.container);
    this.render();
    this.setupListeners();

    // Hydrate from backend on initial load and reconnect
    this.hydrateFromBackend();
    this.unsubscribers.push(
      eventBus.on(EVENTS.WS_CONNECTED, () => this.hydrateFromBackend())
    );

    // Cleanup completed tasks after 5 minutes (fallback timer)
    this.cleanupTimer = setInterval(() => this.cleanupCompleted(), 30000);
    // Live-update elapsed time for running tasks every second
    this.elapsedTimer = setInterval(() => this.updateElapsedTimes(), 1000);
    // Detect stale workers every 15 seconds
    this.staleTimer = setInterval(() => this.detectStaleWorkers(), 15000);
    // Also cleanup when tab regains focus (mobile throttles setInterval)
    document.addEventListener('visibilitychange', this.onVisibilityChange);
  }

  // ── Listeners ───────────────────────────────────────────────────────────────

  private setupListeners(): void {
    this.unsubscribers.push(
      eventBus.on(EVENTS.TASK_STARTED, (payload: any) => {
        this.tasks.set(payload.taskId, {
          taskId: payload.taskId,
          intent: payload.intent || 'unknown',
          summary: payload.summary || '',
          status: 'started',
          startedAt: Date.now(),
          model: payload.model || 'sonnet',
          sessionId: payload.sessionId,
        });
        this.lastUpdate.set(payload.taskId, Date.now());
        this.render();
      })
    );

    this.unsubscribers.push(
      eventBus.on(EVENTS.TASK_PROGRESS, (payload: any) => {
        const task = this.tasks.get(payload.taskId);
        if (task) {
          task.status = 'executing';
          task.progressMessage = payload.message || payload.status || 'Working...';
          this.lastUpdate.set(payload.taskId, Date.now());
          this.render();
        }
      })
    );

    this.unsubscribers.push(
      eventBus.on(EVENTS.TASK_COMPLETED, (payload: any) => {
        const task = this.tasks.get(payload.taskId);
        if (task) {
          task.status = payload.success ? 'completed' : 'failed';
          task.completedAt = Date.now();
          task.result = payload.result;
          task.success = payload.success;
          this.render();
        }
      })
    );

    this.unsubscribers.push(
      eventBus.on(EVENTS.TASK_CANCELLED, (payload: any) => {
        const task = this.tasks.get(payload.taskId);
        if (task) {
          task.status = 'cancelled';
          task.completedAt = Date.now();
          this.render();
        }
      })
    );

    this.unsubscribers.push(
      eventBus.on(EVENTS.TASK_TIMEOUT, (payload: any) => {
        const task = this.tasks.get(payload.taskId);
        if (task) {
          task.status = 'timeout';
          task.completedAt = Date.now();
          this.render();
        }
      })
    );
  }

  // ── Hydration ──────────────────────────────────────────────────────────────

  private async hydrateFromBackend(): Promise<void> {
    try {
      // Prefer project_id (stable across reconnects), fall back to session_id
      const activeTab = appState.get('activeTab') as string | undefined;
      const projectId = appState.get('currentProjectId') as string | undefined;
      const contextTabId = activeTab === 'main' ? SYSTEM_PROJECT_ID : (activeTab || SYSTEM_PROJECT_ID);
      const chatId = appState.getActiveChatId(contextTabId);

      let url: string;
      if (projectId) {
        url = `/api/workers/sessions?project_id=${encodeURIComponent(projectId)}`;
      } else if (chatId) {
        url = `/api/workers/sessions?session_id=${encodeURIComponent(chatId)}`;
      } else {
        url = '/api/workers/sessions';
      }

      const resp = await fetch(url);
      if (!resp.ok) {
        console.warn(`[WorkerPanel] Hydration fetch failed: ${resp.status} ${resp.statusText}`);
        return;
      }
      const data = await resp.json();
      const sessions: Array<{
        task_id: string;
        session_id: string;
        status: string;
        model: string;
        intent: string;
        summary: string;
        start_time: number;
        end_time: number | null;
        result_summary: string | null;
      }> = data.sessions || [];

      console.log(`[WorkerPanel] Hydrated ${sessions.length} sessions from backend`);
      if (sessions.length === 0) return;

      const TERMINAL_STATES = new Set(['completed', 'failed', 'cancelled', 'timeout']);

      const statusMap: Record<string, WorkerTask['status']> = {
        running: 'started',
        completed: 'completed',
        failed: 'failed',
        timed_out: 'timeout',
        cancelled: 'cancelled',
      };

      for (const s of sessions) {
        // Never re-add tasks that were already purged locally
        if (this.purgedTaskIds.has(s.task_id)) continue;

        const existing = this.tasks.get(s.task_id);

        // If we already have this task locally in a terminal state, don't overwrite
        // with a stale "running" from the backend
        if (existing && TERMINAL_STATES.has(existing.status)) continue;

        // If we have a live local state that's fresher, skip
        if (existing && existing.status === 'executing') continue;

        const mappedStatus = statusMap[s.status] || 'started';
        const isTerminal = TERMINAL_STATES.has(mappedStatus);
        // Always set completedAt for terminal tasks (fallback to now if backend lacks end_time)
        const completedAt = s.end_time ? s.end_time * 1000
          : isTerminal ? Date.now()
          : undefined;

        this.tasks.set(s.task_id, {
          taskId: s.task_id,
          intent: s.intent || 'unknown',
          summary: s.summary || '',
          status: mappedStatus,
          startedAt: s.start_time * 1000,
          completedAt,
          result: s.result_summary || undefined,
          success: s.status === 'completed',
          model: (s.model as WorkerTask['model']) || 'sonnet',
          sessionId: s.session_id,
        });
      }
      this.render();
    } catch (e) {
      console.warn('[WorkerPanel] Failed to hydrate from backend:', e);
    }
  }

  // ── Actions ────────────────────────────────────────────────────────────────

  private cancelTask(taskId: string, sessionId?: string): void {
    if (!sessionId) return;
    apiClient.send('task:cancel', { taskId, sessionId });
  }

  // ── Staleness Detection ─────────────────────────────────────────────────────

  private static readonly STALE_THRESHOLD_MS = 2 * 60 * 1000; // 2 minutes

  /** Mark running workers as stale if no WS update in 2 minutes. */
  private detectStaleWorkers(): void {
    const now = Date.now();
    let changed = false;
    for (const task of this.tasks.values()) {
      if (task.status !== 'started' && task.status !== 'executing') continue;
      const lastSeen = this.lastUpdate.get(task.taskId) || task.startedAt;
      if (now - lastSeen > WorkerPanel.STALE_THRESHOLD_MS) {
        task.status = 'stale';
        task.completedAt = now;
        task.result = 'No heartbeat — worker appears dead';
        task.success = false;
        this.lastUpdate.delete(task.taskId);
        changed = true;
      }
    }
    if (changed) this.render();
  }

  /** Dismiss a single task from the panel. */
  private dismissTask(taskId: string): void {
    this.tasks.delete(taskId);
    this.lastUpdate.delete(taskId);
    this.purgedTaskIds.add(taskId);
    this.render();
  }

  /** Dismiss all stale/dead workers. */
  private clearDeadWorkers(): void {
    const DEAD_STATUSES = new Set(['stale', 'failed', 'timeout', 'cancelled']);
    for (const [taskId, task] of this.tasks) {
      if (DEAD_STATUSES.has(task.status)) {
        this.tasks.delete(taskId);
        this.lastUpdate.delete(taskId);
        this.purgedTaskIds.add(taskId);
      }
    }
    this.render();
  }

  // ── Cleanup ─────────────────────────────────────────────────────────────────

  /** Remove expired tasks from the map (no render). Differentiated TTLs. */
  private purgeExpired(): void {
    const now = Date.now();
    const TTL_COMPLETED_MS = 90 * 1000;      // 90 seconds for successful completions
    const TTL_ERROR_MS = 5 * 60 * 1000;      // 5 minutes for failed/stale/timeout/cancelled
    for (const [taskId, task] of this.tasks) {
      if (!task.completedAt) continue;
      const ttl = task.status === 'completed' ? TTL_COMPLETED_MS : TTL_ERROR_MS;
      if (now - task.completedAt > ttl) {
        this.tasks.delete(taskId);
        this.lastUpdate.delete(taskId);
        this.purgedTaskIds.add(taskId);
      }
    }
  }

  private cleanupCompleted(): void {
    const sizeBefore = this.tasks.size;
    this.purgeExpired();
    if (this.tasks.size !== sizeBefore) this.render();
  }

  /** Update elapsed time displays for running tasks without full re-render. */
  private updateElapsedTimes(): void {
    for (const task of this.tasks.values()) {
      if (task.completedAt) continue;
      const timeEl = this.container.querySelector(
        `.worker-task[data-task-id="${task.taskId}"] .worker-task-time`
      );
      if (timeEl) timeEl.textContent = this.getElapsed(task);
    }
  }

  // ── Render ──────────────────────────────────────────────────────────────────

  private render(): void {
    // Eagerly clean expired tasks on every render (immune to timer throttling)
    this.purgeExpired();

    this.container.innerHTML = '';

    // Header
    const header = createElement('div', { className: 'worker-panel-header' });

    const titleRow = createElement('div', { className: 'worker-panel-title-row' });
    const activeCount = this.getActiveCount();
    const title = createElement('span', { className: 'worker-panel-title' }, 'Workers');
    titleRow.appendChild(title);

    if (activeCount > 0) {
      const badge = createElement('span', { className: 'worker-panel-badge' }, String(activeCount));
      titleRow.appendChild(badge);
    }

    const collapseBtn = createElement('button', {
      className: 'worker-panel-collapse',
      title: this.collapsed ? 'Expand' : 'Collapse',
    }, this.collapsed ? '◀' : '▶');
    collapseBtn.addEventListener('click', () => {
      this.collapsed = !this.collapsed;
      this.render();
    });

    header.appendChild(titleRow);

    // "Clear dead" button when stale/failed/timeout workers exist
    const deadCount = this.getDeadCount();
    if (deadCount > 0) {
      const clearBtn = createElement('button', {
        className: 'worker-panel-clear-dead',
        title: 'Clear dead workers',
      }, `Clear dead (${deadCount})`);
      clearBtn.addEventListener('click', () => this.clearDeadWorkers());
      header.appendChild(clearBtn);
    }

    header.appendChild(collapseBtn);
    this.container.appendChild(header);

    if (this.collapsed) {
      this.container.classList.add('collapsed');
      return;
    }
    this.container.classList.remove('collapsed');

    // Task list
    const body = createElement('div', { className: 'worker-panel-body' });

    if (this.tasks.size === 0) {
      const empty = createElement('div', { className: 'worker-panel-empty' }, 'No active workers');
      body.appendChild(empty);
    } else {
      // Active tasks first, then completed
      const sorted = [...this.tasks.values()].sort((a, b) => {
        const aActive = !a.completedAt ? 0 : 1;
        const bActive = !b.completedAt ? 0 : 1;
        if (aActive !== bActive) return aActive - bActive;
        return b.startedAt - a.startedAt;
      });

      for (const task of sorted) {
        body.appendChild(this.renderTask(task));
      }
    }

    this.container.appendChild(body);
  }

  private renderTask(task: WorkerTask): HTMLElement {
    const el = createElement('div', {
      className: `worker-task worker-task--${task.status}`,
      'data-task-id': task.taskId,
    });

    // Status indicator
    const statusEl = createElement('div', { className: 'worker-task-status' });
    statusEl.innerHTML = this.getStatusIndicator(task.status);
    el.appendChild(statusEl);

    // Model badge
    const modelBadge = createElement('span', {
      className: `worker-model-badge worker-model-badge--${task.model || 'sonnet'}`,
    }, this.getModelEmoji(task.model));
    el.appendChild(modelBadge);

    // Content
    const content = createElement('div', { className: 'worker-task-content' });

    const intentEl = createElement('div', { className: 'worker-task-intent' },
      this.formatIntent(task.intent)
    );
    content.appendChild(intentEl);

    const summaryEl = createElement('div', { className: 'worker-task-summary' },
      task.summary.substring(0, 80)
    );
    content.appendChild(summaryEl);

    // Progress message or result
    if (task.status === 'executing' && task.progressMessage) {
      const progress = createElement('div', { className: 'worker-task-progress' },
        task.progressMessage
      );
      content.appendChild(progress);
    } else if (task.completedAt && task.result) {
      const result = createElement('div', {
        className: `worker-task-result ${task.success ? '' : 'worker-task-result--error'}`,
      }, task.result.substring(0, 120));
      content.appendChild(result);
    }

    el.appendChild(content);

    // Elapsed / total time
    const elapsed = this.getElapsed(task);
    const timeEl = createElement('div', { className: 'worker-task-time' },
      task.completedAt ? elapsed : `${elapsed}…`
    );
    el.appendChild(timeEl);

    // Cancel button for active (non-completed) tasks
    if (!task.completedAt) {
      const cancelBtn = createElement('button', {
        className: 'worker-task-cancel',
        title: 'Cancel task',
      });
      cancelBtn.innerHTML = '&times;';
      cancelBtn.addEventListener('click', (e) => {
        e.stopPropagation();
        this.cancelTask(task.taskId, task.sessionId);
      });
      el.appendChild(cancelBtn);
    }

    // Dismiss button for stale/dead workers
    if (task.status === 'stale' || task.status === 'failed' || task.status === 'timeout') {
      const dismissBtn = createElement('button', {
        className: 'worker-task-dismiss',
        title: 'Dismiss',
      });
      dismissBtn.textContent = '✕';
      dismissBtn.addEventListener('click', (e) => {
        e.stopPropagation();
        this.dismissTask(task.taskId);
      });
      el.appendChild(dismissBtn);
    }

    return el;
  }

  // ── Helpers ─────────────────────────────────────────────────────────────────

  private getActiveCount(): number {
    let count = 0;
    for (const task of this.tasks.values()) {
      if (!task.completedAt) count++;
    }
    return count;
  }

  private getDeadCount(): number {
    const DEAD = new Set(['stale', 'failed', 'timeout']);
    let count = 0;
    for (const task of this.tasks.values()) {
      if (DEAD.has(task.status)) count++;
    }
    return count;
  }

  private getElapsed(task: WorkerTask): string {
    const end = task.completedAt || Date.now();
    const ms = end - task.startedAt;
    if (ms < 1000) return '<1s';
    const s = Math.floor(ms / 1000);
    if (s < 60) return `${s}s`;
    const m = Math.floor(s / 60);
    return `${m}m ${s % 60}s`;
  }

  private getStatusIndicator(status: string): string {
    switch (status) {
      case 'queued':
        return '<span class="worker-dot worker-dot--queued"></span>';
      case 'started':
        return '<div class="worker-spinner"></div>';
      case 'executing':
        return '<div class="worker-spinner worker-spinner--fast"></div>';
      case 'completed':
        return '<span class="worker-dot worker-dot--done">✓</span>';
      case 'failed':
        return '<span class="worker-dot worker-dot--failed">✕</span>';
      case 'cancelled':
        return '<span class="worker-dot worker-dot--cancelled">⊘</span>';
      case 'timeout':
        return '<span class="worker-dot worker-dot--timeout">⏱</span>';
      case 'stale':
        return '<span class="worker-dot worker-dot--stale">☠</span>';
      default:
        return '<span class="worker-dot"></span>';
    }
  }

  private getModelEmoji(model?: string): string {
    switch (model) {
      case 'haiku': return '🟡';
      case 'sonnet': return '🔵';
      case 'opus': return '🟣';
      default: return '🔵';
    }
  }

  private formatIntent(intent: string): string {
    return intent.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase());
  }

  destroy(): void {
    this.unsubscribers.forEach((u) => u());
    this.unsubscribers = [];
    if (this.cleanupTimer) clearInterval(this.cleanupTimer);
    if (this.elapsedTimer) clearInterval(this.elapsedTimer);
    if (this.staleTimer) clearInterval(this.staleTimer);
    document.removeEventListener('visibilitychange', this.onVisibilityChange);
    this.container.remove();
  }
}
