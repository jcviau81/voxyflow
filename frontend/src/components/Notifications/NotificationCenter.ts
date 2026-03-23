import { NotificationEntry } from '../../types';
import { eventBus } from '../../utils/EventBus';
import { EVENTS } from '../../utils/constants';
import { createElement } from '../../utils/helpers';
import { appState } from '../../state/AppState';

function formatRelativeTime(timestamp: number): string {
  const diff = Date.now() - timestamp;
  const seconds = Math.floor(diff / 1000);
  if (seconds < 60) return 'just now';
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  return `${days}d ago`;
}

const TYPE_ICONS: Record<string, string> = {
  card_moved: '📋',
  card_created: '✅',
  card_deleted: '🗑️',
  card_enriched: '✨',
  opportunity: '🔔',
  service_down: '⚠️',
  document_indexed: '📄',
  focus_completed: '🎯',
  system: '💡',
};

export class NotificationCenter {
  private panel: HTMLElement;
  private isOpen = false;
  private unsubscribers: (() => void)[] = [];

  constructor(private parentElement: HTMLElement) {
    this.panel = createElement('div', {
      className: 'notification-center',
      'data-testid': 'notification-center',
      'aria-label': 'Notification Center',
      role: 'dialog',
    });
    this.render();
    this.setupListeners();
    this.parentElement.appendChild(this.panel);
  }

  private render(): void {
    this.panel.innerHTML = '';

    const notifications = appState.getNotifications();

    // Header
    const header = createElement('div', { className: 'notification-center-header' });

    const title = createElement('h3', { className: 'notification-center-title' }, '🔔 Notifications');

    const actions = createElement('div', { className: 'notification-center-actions' });

    if (notifications.length > 0) {
      const markReadBtn = createElement('button', {
        className: 'notification-action-btn',
        title: 'Mark all as read',
      }, 'Mark all read');
      markReadBtn.addEventListener('click', () => {
        appState.markAllNotificationsRead();
        this.render();
      });

      const clearBtn = createElement('button', {
        className: 'notification-action-btn notification-action-btn--danger',
        title: 'Clear all notifications',
      }, 'Clear all');
      clearBtn.addEventListener('click', () => {
        appState.clearNotifications();
        this.render();
      });

      actions.appendChild(markReadBtn);
      actions.appendChild(clearBtn);
    }

    const closeBtn = createElement('button', {
      className: 'notification-close-btn',
      title: 'Close notification center',
      'aria-label': 'Close',
    }, '✕');
    closeBtn.addEventListener('click', () => this.hide());
    actions.appendChild(closeBtn);

    header.appendChild(title);
    header.appendChild(actions);
    this.panel.appendChild(header);

    // Body
    const body = createElement('div', { className: 'notification-center-body' });

    if (notifications.length === 0) {
      const empty = createElement('div', { className: 'notification-empty' }, '✨ All caught up!');
      body.appendChild(empty);
    } else {
      notifications.forEach((notif) => {
        const item = this.renderItem(notif);
        body.appendChild(item);
      });
    }

    this.panel.appendChild(body);
  }

  private renderItemActions(notif: NotificationEntry): HTMLElement | null {
    const type = notif.type;

    if (type === 'opportunity') {
      const container = createElement('div', { className: 'notification-item-actions' });

      // Extract suggestion text from message (e.g. "Suggestion: <text>")
      const suggestionMatch = notif.message.match(/[Ss]uggestion[:\s]+(.+)/);
      const suggestionText = suggestionMatch ? suggestionMatch[1].trim() : notif.message;

      const createBtn = createElement('button', { className: 'notification-action-btn' }, '✅ Create Card');
      createBtn.addEventListener('click', (e) => {
        e.stopPropagation();
        this.hide();
        eventBus.emit(EVENTS.MODAL_OPEN, { type: 'card-detail', mode: 'create', prefillTitle: suggestionText });
        this.markItemRead(notif.id);
      });

      const viewBtn = createElement('button', { className: 'notification-action-btn' }, '👁 View Panel');
      viewBtn.addEventListener('click', (e) => {
        e.stopPropagation();
        this.hide();
        eventBus.emit(EVENTS.OPPORTUNITIES_TOGGLE);
        this.markItemRead(notif.id);
      });

      container.appendChild(createBtn);
      container.appendChild(viewBtn);
      return container;
    }

    if ((type === 'card_created' || type === 'card_moved' || type === 'card_enriched') && notif.link) {
      const container = createElement('div', { className: 'notification-item-actions' });
      const openBtn = createElement('button', { className: 'notification-action-btn' }, '📋 Open Card');
      openBtn.addEventListener('click', (e) => {
        e.stopPropagation();
        this.hide();
        eventBus.emit(EVENTS.CARD_SELECTED, { cardId: notif.link });
        this.markItemRead(notif.id);
      });
      container.appendChild(openBtn);
      return container;
    }

    if (type === 'document_indexed') {
      const container = createElement('div', { className: 'notification-item-actions' });
      const docsBtn = createElement('button', { className: 'notification-action-btn' }, '📚 Open Docs');
      docsBtn.addEventListener('click', (e) => {
        e.stopPropagation();
        this.hide();
        eventBus.emit(EVENTS.DOCS_OPEN);
        this.markItemRead(notif.id);
      });
      container.appendChild(docsBtn);
      return container;
    }

    if (type === 'service_down') {
      const container = createElement('div', { className: 'notification-item-actions' });
      const retryBtn = createElement('button', { className: 'notification-action-btn' }, '🔄 Retry');
      retryBtn.addEventListener('click', (e) => {
        e.stopPropagation();
        this.hide();
        eventBus.emit(EVENTS.SETTINGS_OPEN);
        this.markItemRead(notif.id);
      });
      container.appendChild(retryBtn);
      return container;
    }

    return null;
  }

  private renderItem(notif: NotificationEntry): HTMLElement {
    const item = createElement('div', {
      className: `notification-item${notif.read ? '' : ' unread'}`,
      'data-id': notif.id,
    });

    const icon = createElement('span', { className: 'notification-item-icon' },
      TYPE_ICONS[notif.type] || '💡'
    );

    const content = createElement('div', { className: 'notification-item-content' });
    const msg = createElement('span', { className: 'notification-item-message' }, notif.message);
    const meta = createElement('span', { className: 'notification-meta' }, formatRelativeTime(notif.timestamp));

    content.appendChild(msg);
    content.appendChild(meta);

    const actions = this.renderItemActions(notif);
    if (actions) {
      content.appendChild(actions);
    }

    item.appendChild(icon);
    item.appendChild(content);

    return item;
  }

  private markItemRead(id: string): void {
    // Use markAllRead as the public API and re-render; individual mark-read
    // can be added to AppState later. For now, clicking a linked notification
    // marks all as read (panel is already open, so unread count = 0 anyway).
    appState.markAllNotificationsRead();
    this.render();
  }

  private setupListeners(): void {
    this.unsubscribers.push(
      eventBus.on(EVENTS.NOTIFICATION_ADDED, () => {
        if (this.isOpen) this.render();
      })
    );
    this.unsubscribers.push(
      eventBus.on(EVENTS.NOTIFICATION_CLEARED, () => {
        if (this.isOpen) this.render();
      })
    );
    this.unsubscribers.push(
      eventBus.on(EVENTS.NOTIFICATION_PANEL_TOGGLE, () => {
        this.toggle();
      })
    );

    // Close on click outside
    document.addEventListener('mousedown', this.handleOutsideClick);
  }

  private handleOutsideClick = (e: MouseEvent): void => {
    if (!this.isOpen) return;
    const target = e.target as Node;
    if (!this.panel.contains(target) && !(target as HTMLElement).closest('.notification-bell')) {
      this.hide();
    }
  };

  toggle(): void {
    if (this.isOpen) {
      this.hide();
    } else {
      this.show();
    }
  }

  show(): void {
    this.isOpen = true;
    this.render();
    this.panel.classList.add('open');
    // Mark as read when opened
    appState.markAllNotificationsRead();
    eventBus.emit(EVENTS.NOTIFICATION_COUNT, 0);
  }

  hide(): void {
    this.isOpen = false;
    this.panel.classList.remove('open');
  }

  destroy(): void {
    this.unsubscribers.forEach(u => u());
    document.removeEventListener('mousedown', this.handleOutsideClick);
    this.panel.remove();
  }
}
