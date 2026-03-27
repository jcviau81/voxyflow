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
  lastActivity: number;
}

export class TaskPanel {
  private container: HTMLElement;
  private taskList: HTMLElement;
  private tasks: Map<string, ActiveTask> = new Map();
  private unsubscribers: (() => void)[] = [];
  private cleanupTimer: ReturnType<typeof setInterval> | null = null;
  private onVisibilityChange = () => {
    if (document.visibilityState === 'visible') this.cleanupCompleted();
  };

  constructor(private parentElement: HTMLElement) {
    this.container = createElement('div', { className: 'task-panel' });
    this.container.style.display = 'none'; // Hidden when no tasks
    this.taskList = createElement('div', { className: 'task-panel-list' });
    this.container.appendChild(this.taskList);
    this.parentElement.appendChild(this.container);
    this.setupListeners();

    // Hydrate from backend on initial load and reconnect
    this.hydrateFromBackend();
    this.unsubscribers.push(
      eventBus.on(EVENTS.WS_CONNECTED, () => this.hydrateFromBackend())
    );

    // Cleanup completed tasks after 8 seconds (fallback timer)
    this.cleanupTimer = setInterval(() => this.cleanupCompleted(), 2000);
    // Also cleanup when tab regains focus (mobile throttles setInterval)
    document.addEventListener('visibilitychange', this.onVisibilityChange);
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
          lastActivity: Date.now(),
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

    // Track tool executions to update last activity
    this.unsubscribers.push(
      eventBus.on(EVENTS.TOOL_EXECUTED, (payload: any) => {
        const taskId = payload.taskId;
        if (taskId) {
          const task = this.tasks.get(taskId);
          if (task && !task.completedAt) {
            task.lastActivity = Date.now();
            this.render();
          }
        }
      })
    );

    // Direct action flash — brief inline indicator for fast-path CRUD
    this.unsubscribers.push(
      eventBus.on(EVENTS.ACTION_COMPLETED, (payload: any) => {
        const { taskId, action, success, duration_ms } = payload;
        const labels: Record<string, string> = {
          'card.create': 'Card created',
          'create_card': 'Card created',
          'card.update': 'Card updated',
          'update_card': 'Card updated',
          'card.move': 'Card moved',
          'move_card': 'Card moved',
          'card.delete': 'Card deleted',
          'delete_card': 'Card deleted',
          'card.list': 'Cards listed',
        };
        const label = labels[action] || action;
        const now = Date.now();
        this.tasks.set(taskId, {
          taskId,
          intent: label,
          summary: `${duration_ms}ms`,
          status: success ? 'completed' : 'failed',
          startedAt: now,
          completedAt: now,
          success,
          lastActivity: now,
        });
        this.render();
      })
    );
  }

  private async hydrateFromBackend(): Promise<void> {
    try {
      const resp = await fetch('/api/workers/sessions');
      if (!resp.ok) return;
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

      // Only show running tasks in the compact TaskPanel
      const running = sessions.filter((s) => s.status === 'running');
      if (running.length === 0) return;

      for (const s of running) {
        if (this.tasks.has(s.task_id)) continue;
        this.tasks.set(s.task_id, {
          taskId: s.task_id,
          intent: s.intent || 'unknown',
          summary: s.summary || '',
          status: 'started',
          startedAt: s.start_time * 1000,
          sessionId: s.session_id,
          lastActivity: Date.now(),
        });
      }
      this.render();
    } catch (e) {
      console.warn('[TaskPanel] Failed to hydrate from backend:', e);
    }
  }

  private cancelTask(taskId: string, sessionId?: string): void {
    if (!sessionId) return;
    apiClient.send('task:cancel', { taskId, sessionId });
  }

  /** Remove expired tasks from the map (no render). */
  private purgeExpired(): void {
    const now = Date.now();
    for (const [taskId, task] of this.tasks) {
      if (task.completedAt && now - task.completedAt > 8000) {
        this.tasks.delete(taskId);
      }
    }
  }

  private cleanupCompleted(): void {
    const sizeBefore = this.tasks.size;
    this.purgeExpired();
    if (this.tasks.size !== sizeBefore) this.render();
  }

  private render(): void {
    // Eagerly clean expired tasks on every render (immune to timer throttling)
    this.purgeExpired();

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
      // Show different timing info based on task state
      let elapsed = '';
      if (task.completedAt) {
        // Completed tasks show total duration
        elapsed = `${((task.completedAt - task.startedAt) / 1000).toFixed(1)}s`;
      } else {
        // Active tasks show time since last activity
        const idleTime = (Date.now() - task.lastActivity) / 1000;
        elapsed = idleTime < 5 ? 'active' : `idle ${idleTime.toFixed(0)}s`;
      }

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
    document.removeEventListener('visibilitychange', this.onVisibilityChange);
    this.container.remove();
  }
}
