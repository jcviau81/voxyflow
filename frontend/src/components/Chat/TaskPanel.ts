/**
 * TaskPanel — Shows active Deep Worker tasks in real-time.
 *
 * Listens for task:started, task:progress, task:completed, task:cancelled,
 * and task:timeout events from the event bus and displays them as a compact
 * panel above the chat input area.
 */

import { eventBus } from '../../utils/EventBus';
import { EVENTS } from '../../utils/constants';
import { createElement } from '../../utils/helpers';
import { apiClient } from '../../services/ApiClient';

interface ActiveTask {
  taskId: string;
  intent: string;
  summary: string;
  status: 'started' | 'executing' | 'completed' | 'failed' | 'cancelled' | 'timeout';
  startedAt: number;
  completedAt?: number;
  result?: string;
  success?: boolean;
  sessionId?: string;
}

export class TaskPanel {
  private container: HTMLElement;
  private taskList: HTMLElement;
  private tasks: Map<string, ActiveTask> = new Map();
  private unsubscribers: (() => void)[] = [];
  private cleanupTimer: ReturnType<typeof setInterval> | null = null;

  constructor(private parentElement: HTMLElement) {
    this.container = createElement('div', { className: 'task-panel' });
    this.container.style.display = 'none'; // Hidden when no tasks
    this.taskList = createElement('div', { className: 'task-panel-list' });
    this.container.appendChild(this.taskList);
    this.parentElement.appendChild(this.container);
    this.setupListeners();

    // Cleanup completed tasks after 8 seconds
    this.cleanupTimer = setInterval(() => this.cleanupCompleted(), 2000);
  }

  private setupListeners(): void {
    this.unsubscribers.push(
      eventBus.on(EVENTS.TASK_STARTED, (payload: any) => {
        const task: ActiveTask = {
          taskId: payload.taskId,
          intent: payload.intent || 'unknown',
          summary: payload.summary || '',
          status: 'started',
          startedAt: Date.now(),
          sessionId: payload.sessionId,
        };
        this.tasks.set(task.taskId, task);
        this.render();
      })
    );

    this.unsubscribers.push(
      eventBus.on(EVENTS.TASK_PROGRESS, (payload: any) => {
        const task = this.tasks.get(payload.taskId);
        if (task) {
          task.status = 'executing';
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

  private cancelTask(taskId: string, sessionId?: string): void {
    if (!sessionId) return;
    apiClient.send('task:cancel', { taskId, sessionId });
  }

  private cleanupCompleted(): void {
    const now = Date.now();
    let changed = false;
    for (const [taskId, task] of this.tasks) {
      if (task.completedAt && now - task.completedAt > 8000) {
        this.tasks.delete(taskId);
        changed = true;
      }
    }
    if (changed) this.render();
  }

  private render(): void {
    if (this.tasks.size === 0) {
      this.container.style.display = 'none';
      return;
    }
    this.container.style.display = 'block';
    this.taskList.innerHTML = '';

    for (const task of this.tasks.values()) {
      const el = createElement('div', {
        className: `task-item task-${task.status}`,
      });

      const icon = this.getStatusIcon(task.status);
      const elapsed = task.completedAt
        ? `${((task.completedAt - task.startedAt) / 1000).toFixed(1)}s`
        : `${((Date.now() - task.startedAt) / 1000).toFixed(0)}s`;

      el.innerHTML = `
        <span class="task-icon">${icon}</span>
        <span class="task-intent">${this.formatIntent(task.intent)}</span>
        <span class="task-summary">${this.escapeHtml(task.summary).substring(0, 60)}</span>
        <span class="task-elapsed">${elapsed}</span>
      `;

      // Add cancel button for active tasks
      if (!task.completedAt) {
        const cancelBtn = createElement('button', {
          className: 'task-cancel-btn',
          title: 'Cancel task',
        });
        cancelBtn.innerHTML = '&times;';
        cancelBtn.addEventListener('click', (e) => {
          e.stopPropagation();
          this.cancelTask(task.taskId, task.sessionId);
        });
        el.appendChild(cancelBtn);
      }

      this.taskList.appendChild(el);
    }
  }

  private getStatusIcon(status: string): string {
    switch (status) {
      case 'started':
        return '<div class="task-spinner"></div>';
      case 'executing':
        return '<div class="task-spinner task-spinner-fast"></div>';
      case 'completed':
        return '✅';
      case 'failed':
        return '❌';
      case 'cancelled':
        return '🚫';
      case 'timeout':
        return '⏱️';
      default:
        return '⏳';
    }
  }

  private formatIntent(intent: string): string {
    return intent.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase());
  }

  private escapeHtml(text: string): string {
    const el = document.createElement('span');
    el.textContent = text;
    return el.innerHTML;
  }

  destroy(): void {
    this.unsubscribers.forEach((unsub) => unsub());
    if (this.cleanupTimer) clearInterval(this.cleanupTimer);
    this.container.remove();
  }
}
