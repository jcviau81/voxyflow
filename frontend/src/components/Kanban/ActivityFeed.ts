import { ActivityEntry } from '../../types';
import { eventBus } from '../../utils/EventBus';
import { EVENTS } from '../../utils/constants';
import { createElement } from '../../utils/helpers';
import { appState } from '../../state/AppState';

const ACTIVITY_ICONS: Record<string, string> = {
  card_created: '✅',
  card_moved: '📋',
  card_deleted: '🗑️',
  document_uploaded: '📄',
  chat_message: '💬',
};

function relativeTime(timestamp: number): string {
  const diff = Date.now() - timestamp;
  const minutes = Math.floor(diff / 60000);
  const hours = Math.floor(diff / 3600000);
  const days = Math.floor(diff / 86400000);

  if (diff < 60000) return 'just now';
  if (minutes < 60) return `${minutes} min ago`;
  if (hours < 24) return `${hours}h ago`;
  return `${days}d ago`;
}

export class ActivityFeed {
  private container: HTMLElement;
  private collapsed = true;
  private unsubscribers: (() => void)[] = [];
  private updateTimer: ReturnType<typeof setInterval> | null = null;

  constructor(private parentElement: HTMLElement) {
    this.container = createElement('div', { className: 'activity-feed', 'data-testid': 'activity-feed' });
    this.render();
    this.setupListeners();

    // Refresh relative timestamps every minute
    this.updateTimer = setInterval(() => this.renderEntries(), 60000);
  }

  private getProjectId(): string | null {
    return appState.get('currentProjectId');
  }

  render(): void {
    this.container.innerHTML = '';

    const projectId = this.getProjectId();
    const activities = projectId ? appState.getActivities(projectId) : [];

    // Header (always visible)
    const header = createElement('div', { className: 'activity-feed-header' });
    const toggle = createElement('button', { className: 'activity-feed-toggle' });
    toggle.innerHTML = `
      <span class="activity-feed-title">📋 Recent Activity</span>
      <span class="activity-feed-count">${activities.length}</span>
      <span class="activity-feed-chevron">${this.collapsed ? '▶' : '▼'}</span>
    `;
    toggle.addEventListener('click', () => {
      this.collapsed = !this.collapsed;
      this.render();
    });
    header.appendChild(toggle);
    this.container.appendChild(header);

    // Body (collapsible)
    if (!this.collapsed) {
      const body = createElement('div', { className: 'activity-feed-body' });
      if (activities.length === 0) {
        const empty = createElement('div', { className: 'activity-feed-empty' }, 'No activity yet.');
        body.appendChild(empty);
      } else {
        activities.forEach((entry) => {
          body.appendChild(this.renderEntry(entry));
        });
      }
      this.container.appendChild(body);
    }

    if (!this.container.parentElement) {
      this.parentElement.appendChild(this.container);
    }
  }

  private renderEntries(): void {
    // Re-render just the body if expanded (to update timestamps)
    if (!this.collapsed) {
      this.render();
    }
  }

  private renderEntry(entry: ActivityEntry): HTMLElement {
    const row = createElement('div', { className: 'activity-entry' });

    const icon = createElement('span', { className: 'activity-entry-icon' },
      ACTIVITY_ICONS[entry.type] || '📌'
    );
    const text = createElement('span', { className: 'activity-entry-message' }, entry.message);
    const time = createElement('span', { className: 'activity-time' }, relativeTime(entry.timestamp));

    row.appendChild(icon);
    row.appendChild(text);
    row.appendChild(time);

    return row;
  }

  private setupListeners(): void {
    this.unsubscribers.push(
      eventBus.on(EVENTS.ACTIVITY_ADDED, (entry: unknown) => {
        const e = entry as ActivityEntry;
        const projectId = this.getProjectId();
        if (e.projectId === projectId) {
          this.render();
        }
      })
    );

    this.unsubscribers.push(
      eventBus.on(EVENTS.PROJECT_SELECTED, () => {
        this.render();
      })
    );
  }

  update(): void {
    this.render();
  }

  destroy(): void {
    this.unsubscribers.forEach((unsub) => unsub());
    this.unsubscribers = [];
    if (this.updateTimer !== null) {
      clearInterval(this.updateTimer);
      this.updateTimer = null;
    }
    this.container.remove();
  }
}
