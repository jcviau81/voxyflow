/**
 * WorkerPanel — Live view of Deep Worker tasks.
 *
 * Sits between the chat area and the Opportunities panel.
 * Shows active, queued, and recently completed worker tasks
 * with real-time progress updates via the event bus.
 */

import { eventBus } from '../../utils/EventBus';
import { EVENTS } from '../../utils/constants';
import { createElement } from '../../utils/helpers';
import { apiClient } from '../../services/ApiClient';

interface WorkerTask {
  taskId: string;
  intent: string;
  summary: string;
  status: 'queued' | 'started' | 'executing' | 'completed' | 'failed' | 'cancelled' | 'timeout';
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
  private unsubscribers: (() => void)[] = [];
  private cleanupTimer: ReturnType<typeof setInterval> | null = null;
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

    // Cleanup completed tasks after 15 seconds (fallback timer)
    this.cleanupTimer = setInterval(() => this.cleanupCompleted(), 3000);
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
        this.render();
      })
    );

    this.unsubscribers.push(
      eventBus.on(EVENTS.TASK_PROGRESS, (payload: any) => {
        const task = this.tasks.get(payload.taskId);
        if (task) {
          task.status = 'executing';
          task.progressMessage = payload.message || payload.status || 'Working...';
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

  // ── Actions ────────────────────────────────────────────────────────────────

  private cancelTask(taskId: string, sessionId?: string): void {
    if (!sessionId) return;
    apiClient.send('task:cancel', { taskId, sessionId });
  }

  // ── Cleanup ─────────────────────────────────────────────────────────────────

  /** Remove expired tasks from the map (no render). */
  private purgeExpired(): void {
    const now = Date.now();
    for (const [taskId, task] of this.tasks) {
      if (task.completedAt && now - task.completedAt > 15000) {
        this.tasks.delete(taskId);
      }
    }
  }

  private cleanupCompleted(): void {
    const sizeBefore = this.tasks.size;
    this.purgeExpired();
    if (this.tasks.size !== sizeBefore) this.render();
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

    // Elapsed time
    const elapsed = this.getElapsed(task);
    const timeEl = createElement('div', { className: 'worker-task-time' }, elapsed);
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
    document.removeEventListener('visibilitychange', this.onVisibilityChange);
    this.container.remove();
  }
}
