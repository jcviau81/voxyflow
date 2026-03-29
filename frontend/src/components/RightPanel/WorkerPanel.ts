/**
 * WorkerPanel — Live view of Deep Worker tasks via the Worker Ledger API.
 *
 * Sits between the chat area and the Opportunities panel.
 * Shows active and recently completed worker tasks with real-time
 * updates via WebSocket events, backed by periodic polling of
 * GET /api/worker-tasks for consistency.
 */

import { eventBus } from '../../utils/EventBus';
import { EVENTS, SYSTEM_PROJECT_ID } from '../../utils/constants';
import { createElement } from '../../utils/helpers';
import { apiClient } from '../../services/ApiClient';
import { appState } from '../../state/AppState';

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
  expanded?: boolean;    // whether the result detail is expanded
}

/** Maps backend status strings to our canonical WorkerTask statuses. */
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

export class WorkerPanel {
  private container: HTMLElement;
  private tasks: Map<string, WorkerTask> = new Map();
  private dismissedTaskIds: Set<string> = new Set();
  private unsubscribers: (() => void)[] = [];
  private pollTimer: ReturnType<typeof setInterval> | null = null;
  private cleanupTimer: ReturnType<typeof setInterval> | null = null;
  private elapsedTimer: ReturnType<typeof setInterval> | null = null;
  private collapsed = false;
  private onVisibilityChange = () => {
    if (document.visibilityState === 'visible') {
      this.pollLedger();
      this.cleanupCompleted();
    }
  };

  constructor(private parentElement: HTMLElement) {
    this.container = createElement('div', {
      className: 'worker-panel',
      'data-testid': 'worker-panel',
    });
    this.parentElement.appendChild(this.container);
    this.render();
    this.setupListeners();

    // Initial fetch + start polling every 3 seconds
    this.pollLedger();
    this.pollTimer = setInterval(() => this.pollLedger(), 3000);

    // Also re-fetch on WS reconnect for immediate consistency
    this.unsubscribers.push(
      eventBus.on(EVENTS.WS_CONNECTED, () => this.pollLedger())
    );

    // Cleanup completed tasks periodically (fallback)
    this.cleanupTimer = setInterval(() => this.cleanupCompleted(), 30000);
    // Live-update elapsed time for running tasks every second
    this.elapsedTimer = setInterval(() => this.updateElapsedTimes(), 1000);
    // Re-sync when tab regains focus (mobile throttles setInterval)
    document.addEventListener('visibilitychange', this.onVisibilityChange);
  }

  // ── Listeners (real-time via WebSocket) ────────────────────────────────────

  private setupListeners(): void {
    this.unsubscribers.push(
      eventBus.on(EVENTS.TASK_STARTED, (payload: any) => {
        if (this.dismissedTaskIds.has(payload.taskId)) return;
        this.tasks.set(payload.taskId, {
          taskId: payload.taskId,
          action: payload.intent || 'unknown',
          description: payload.summary || '',
          status: 'running',
          startedAt: Date.now(),
          model: payload.model || 'sonnet',
          sessionId: payload.sessionId,
        });
        this.render();
      })
    );

    this.unsubscribers.push(
      eventBus.on(EVENTS.TASK_PROGRESS, (payload: any) => {
        const task = this.tasks.get(payload.taskId);
        if (task && !TERMINAL_STATUSES.has(task.status)) {
          task.status = 'running';
          this.render();
        }
      })
    );

    this.unsubscribers.push(
      eventBus.on(EVENTS.TASK_COMPLETED, (payload: any) => {
        const task = this.tasks.get(payload.taskId);
        if (task) {
          task.status = payload.success ? 'done' : 'failed';
          task.completedAt = Date.now();
          task.resultSummary = payload.result || undefined;
          task.error = payload.success ? undefined : (payload.result || 'Task failed');
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
          task.status = 'failed';
          task.completedAt = Date.now();
          task.error = `Timed out after ${payload.timeout_seconds || '?'}s`;
          this.render();
        }
      })
    );
  }

  // ── Ledger Polling ─────────────────────────────────────────────────────────

  private async pollLedger(): Promise<void> {
    try {
      const projectId = appState.get('currentProjectId') as string | undefined;
      const activeTab = appState.get('activeTab') as string | undefined;
      const contextTabId = activeTab === 'main' ? SYSTEM_PROJECT_ID : (activeTab || SYSTEM_PROJECT_ID);
      const chatId = appState.getActiveChatId(contextTabId);

      const params = new URLSearchParams({ limit: '20' });
      if (projectId) params.set('project_id', projectId);
      else if (chatId) params.set('session_id', chatId);

      const resp = await fetch(`/api/worker-tasks?${params}`);
      if (!resp.ok) return;

      const data: {
        tasks: Array<{
          id: string;
          session_id: string;
          project_id: string | null;
          action: string;
          description: string;
          model: string;
          status: string;
          result_summary: string | null;
          error: string | null;
          started_at: string | null;
          completed_at: string | null;
          created_at: string;
        }>;
        count: number;
      } = await resp.json();

      let changed = false;
      for (const t of data.tasks) {
        if (this.dismissedTaskIds.has(t.id)) continue;

        const existing = this.tasks.get(t.id);
        const apiStatus = STATUS_MAP[t.status] || 'running';

        // Don't overwrite a locally-terminal task with a stale poll result
        if (existing && TERMINAL_STATUSES.has(existing.status)) continue;

        // Skip terminal tasks from the API if they aren't already tracked locally.
        // Terminal tasks (done/failed/cancelled) should only appear in the panel
        // when they arrive via real-time WS events during the current session.
        // This prevents old completed tasks from reappearing on page refresh.
        if (!existing && TERMINAL_STATUSES.has(apiStatus)) continue;

        const startedAt = t.started_at ? new Date(t.started_at).getTime()
          : new Date(t.created_at).getTime();
        const completedAt = t.completed_at ? new Date(t.completed_at).getTime()
          : TERMINAL_STATUSES.has(apiStatus) ? Date.now()
          : undefined;

        const updated: WorkerTask = {
          taskId: t.id,
          action: t.action || 'unknown',
          description: t.description || '',
          status: apiStatus,
          startedAt,
          completedAt,
          resultSummary: t.result_summary || undefined,
          error: t.error || undefined,
          model: (t.model as WorkerTask['model']) || 'sonnet',
          sessionId: t.session_id,
          expanded: existing?.expanded,
        };

        this.tasks.set(t.id, updated);
        changed = true;
      }

      if (changed) this.render();
    } catch {
      // Silently ignore poll failures — WS events are the primary source
    }
  }

  // ── Actions ────────────────────────────────────────────────────────────────

  private cancelTask(taskId: string, sessionId?: string): void {
    if (!sessionId) return;
    apiClient.send('task:cancel', { taskId, sessionId });
  }

  private dismissTask(taskId: string): void {
    this.tasks.delete(taskId);
    this.dismissedTaskIds.add(taskId);
    this.render();
  }

  private clearTerminalTasks(): void {
    for (const [taskId, task] of this.tasks) {
      if (TERMINAL_STATUSES.has(task.status)) {
        this.tasks.delete(taskId);
        this.dismissedTaskIds.add(taskId);
      }
    }
    this.render();
  }

  // ── Cleanup ─────────────────────────────────────────────────────────────────

  private purgeExpired(): void {
    const now = Date.now();
    const TTL_DONE_MS = 90 * 1000;
    const TTL_ERROR_MS = 5 * 60 * 1000;
    for (const [taskId, task] of this.tasks) {
      if (!task.completedAt) continue;
      const ttl = task.status === 'done' ? TTL_DONE_MS : TTL_ERROR_MS;
      if (now - task.completedAt > ttl) {
        this.tasks.delete(taskId);
        this.dismissedTaskIds.add(taskId);
      }
    }
  }

  private cleanupCompleted(): void {
    const sizeBefore = this.tasks.size;
    this.purgeExpired();
    if (this.tasks.size !== sizeBefore) this.render();
  }

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
    this.purgeExpired();
    this.container.innerHTML = '';

    // Header
    const header = createElement('div', { className: 'worker-panel-header' });
    const titleRow = createElement('div', { className: 'worker-panel-title-row' });
    const activeCount = this.getActiveCount();
    titleRow.appendChild(createElement('span', { className: 'worker-panel-title' }, 'Workers'));

    if (activeCount > 0) {
      titleRow.appendChild(createElement('span', { className: 'worker-panel-badge' }, String(activeCount)));
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

    // "Clear finished" button when terminal tasks exist
    const terminalCount = this.getTerminalCount();
    if (terminalCount > 0) {
      const clearBtn = createElement('button', {
        className: 'worker-panel-clear-dead',
        title: 'Clear finished tasks',
      }, `Clear (${terminalCount})`);
      clearBtn.addEventListener('click', () => this.clearTerminalTasks());
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
      body.appendChild(createElement('div', { className: 'worker-panel-empty' }, 'No active workers'));
    } else {
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
    const statusClass = task.status === 'done' ? 'completed'
      : task.status === 'running' ? 'executing'
      : task.status;
    const el = createElement('div', {
      className: `worker-task worker-task--${statusClass}`,
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

    content.appendChild(createElement('div', { className: 'worker-task-intent' },
      this.formatAction(task.action)
    ));

    content.appendChild(createElement('div', { className: 'worker-task-summary' },
      task.description.substring(0, 60)
    ));

    // Error message for failed tasks
    if (task.status === 'failed' && task.error) {
      content.appendChild(createElement('div', {
        className: 'worker-task-result worker-task-result--error',
      }, task.error.substring(0, 200)));
    }

    // Result summary — collapsed by default, expandable on click
    if (task.completedAt && task.resultSummary && task.status !== 'failed') {
      const resultText = task.expanded
        ? task.resultSummary.substring(0, 200)
        : task.resultSummary.substring(0, 60) + (task.resultSummary.length > 60 ? '…' : '');
      const result = createElement('div', {
        className: 'worker-task-result worker-task-result--expandable',
      }, resultText);
      if (task.resultSummary.length > 60) {
        result.style.cursor = 'pointer';
        result.addEventListener('click', (e) => {
          e.stopPropagation();
          task.expanded = !task.expanded;
          this.render();
        });
      }
      content.appendChild(result);
    }

    el.appendChild(content);

    // Duration
    const elapsed = this.getElapsed(task);
    el.appendChild(createElement('div', { className: 'worker-task-time' },
      task.completedAt ? elapsed : `${elapsed}…`
    ));

    // Cancel button for active tasks
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

    // Dismiss button for failed/cancelled tasks
    if (task.status === 'failed' || task.status === 'cancelled') {
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

  private getTerminalCount(): number {
    let count = 0;
    for (const task of this.tasks.values()) {
      if (TERMINAL_STATUSES.has(task.status)) count++;
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

  private getStatusIndicator(status: WorkerTask['status']): string {
    switch (status) {
      case 'pending':
        return '<span class="worker-dot worker-dot--queued">⏳</span>';
      case 'running':
        return '<div class="worker-spinner worker-spinner--fast"></div>';
      case 'done':
        return '<span class="worker-dot worker-dot--done">✓</span>';
      case 'failed':
        return '<span class="worker-dot worker-dot--failed">✕</span>';
      case 'cancelled':
        return '<span class="worker-dot worker-dot--cancelled">⊘</span>';
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

  private formatAction(action: string): string {
    return action.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase());
  }

  destroy(): void {
    this.unsubscribers.forEach((u) => u());
    this.unsubscribers = [];
    if (this.pollTimer) clearInterval(this.pollTimer);
    if (this.cleanupTimer) clearInterval(this.cleanupTimer);
    if (this.elapsedTimer) clearInterval(this.elapsedTimer);
    document.removeEventListener('visibilitychange', this.onVisibilityChange);
    this.container.remove();
  }
}
