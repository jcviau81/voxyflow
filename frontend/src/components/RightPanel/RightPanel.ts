import { CardSuggestion, NotificationEntry } from '../../types';
import { eventBus } from '../../utils/EventBus';
import { EVENTS } from '../../utils/constants';
import { createElement } from '../../utils/helpers';
import { appState } from '../../state/AppState';

// ─── Notification helpers (from old NotificationCenter) ───────────────────────

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

type RightPanelTab = 'opportunities' | 'notifications';

// ─── RightPanel ───────────────────────────────────────────────────────────────

export class RightPanel {
  private container: HTMLElement;
  private activeTab: RightPanelTab = 'opportunities';
  private opportunities: CardSuggestion[] = [];
  private unsubscribers: (() => void)[] = [];

  constructor(private parentElement: HTMLElement) {
    this.container = createElement('div', {
      className: 'right-panel',
      'data-testid': 'right-panel',
    });
    this.parentElement.appendChild(this.container);
    this.render();
    this.setupListeners();
  }

  // ── Public API ──────────────────────────────────────────────────────────────

  switchTab(tab: RightPanelTab): void {
    this.activeTab = tab;
    if (tab === 'notifications') {
      // Mark all as read when switching to the notifications tab
      appState.markAllNotificationsRead();
      eventBus.emit(EVENTS.NOTIFICATION_COUNT, 0);
    }
    this.render();
  }

  addOpportunity(suggestion: CardSuggestion): void {
    this.opportunities.push(suggestion);
    this.render();
    this.emitOpportunityCount();
  }

  removeOpportunity(id: string): void {
    this.opportunities = this.opportunities.filter((o) => o.id !== id);
    this.render();
    this.emitOpportunityCount();
  }

  // ── Internal ────────────────────────────────────────────────────────────────

  private emitOpportunityCount(): void {
    eventBus.emit(EVENTS.OPPORTUNITIES_COUNT, this.opportunities.length);
  }

  private render(): void {
    this.container.innerHTML = '';

    // Tab bar
    const unreadCount = appState.getNotificationUnreadCount();
    const tabBar = this.renderTabBar(unreadCount);
    this.container.appendChild(tabBar);

    // Body
    const body = createElement('div', { className: 'right-panel-body' });

    if (this.activeTab === 'opportunities') {
      this.renderOpportunitiesContent(body);
    } else {
      this.renderNotificationsContent(body);
    }

    this.container.appendChild(body);
  }

  private renderTabBar(unreadCount: number): HTMLElement {
    const bar = createElement('div', { className: 'right-panel-tabs' });

    const oppTab = createElement('button', {
      className: `right-panel-tab${this.activeTab === 'opportunities' ? ' active' : ''}`,
      'data-tab': 'opportunities',
      title: 'Opportunities',
    });
    oppTab.textContent = '💡 Opportunities';
    if (this.opportunities.length > 0) {
      const badge = createElement('span', { className: 'right-panel-tab-badge' }, String(this.opportunities.length));
      oppTab.appendChild(badge);
    }
    oppTab.addEventListener('click', () => this.switchTab('opportunities'));

    const notifTab = createElement('button', {
      className: `right-panel-tab${this.activeTab === 'notifications' ? ' active' : ''}`,
      'data-tab': 'notifications',
      title: 'Notifications',
    });
    notifTab.textContent = '🔔 Notifications';
    if (unreadCount > 0) {
      const badge = createElement('span', { className: 'right-panel-tab-badge unread' },
        unreadCount > 99 ? '99+' : String(unreadCount)
      );
      notifTab.appendChild(badge);
    }
    notifTab.addEventListener('click', () => this.switchTab('notifications'));

    bar.appendChild(oppTab);
    bar.appendChild(notifTab);
    return bar;
  }

  // ── Opportunities tab ───────────────────────────────────────────────────────

  private renderOpportunitiesContent(body: HTMLElement): void {
    const header = createElement('div', { className: 'opportunities-header' });
    const title = createElement('h3', {}, '💡 Opportunities');
    const badge = createElement('span', { className: 'opportunities-badge' }, String(this.opportunities.length));
    header.appendChild(title);
    header.appendChild(badge);
    body.appendChild(header);

    const list = createElement('div', { className: 'opportunities-list' });

    if (this.opportunities.length === 0) {
      const empty = createElement('div', { className: 'opportunities-empty' }, 'No suggestions yet. Start chatting!');
      list.appendChild(empty);
    } else {
      this.opportunities.forEach((opp) => {
        const card = this.renderOpportunityCard(opp);
        list.appendChild(card);
      });
    }

    body.appendChild(list);
  }

  private renderOpportunityCard(opp: CardSuggestion): HTMLElement {
    const card = createElement('div', {
      className: 'opportunity-card',
      'data-id': opp.id,
    });

    const agent = createElement('div', { className: 'opp-agent' },
      `${opp.agentEmoji || '🤖'} ${opp.agentName || 'Ember'}`
    );
    const title = createElement('div', { className: 'opp-title' }, opp.title);
    card.appendChild(agent);
    card.appendChild(title);

    if (opp.description) {
      const desc = createElement('div', { className: 'opp-description' }, opp.description);
      card.appendChild(desc);
    }

    const actions = createElement('div', { className: 'opp-actions' });
    const acceptBtn = createElement('button', { className: 'opp-accept', 'data-id': opp.id }, 'Create Card');
    acceptBtn.addEventListener('click', () => this.acceptOpportunity(opp.id));

    const dismissBtn = createElement('button', { className: 'opp-dismiss', 'data-id': opp.id }, '✕');
    dismissBtn.addEventListener('click', () => this.removeOpportunity(opp.id));

    actions.appendChild(acceptBtn);
    actions.appendChild(dismissBtn);
    card.appendChild(actions);

    return card;
  }

  private acceptOpportunity(id: string): void {
    const opp = this.opportunities.find((o) => o.id === id);
    if (opp) {
      const projectId = appState.get('currentProjectId');
      if (projectId) {
        eventBus.emit(EVENTS.MODAL_OPEN, { type: 'card-detail', mode: 'create', projectId, prefillTitle: opp.title, prefillAgentType: opp.agentType });
      } else {
        eventBus.emit(EVENTS.CREATE_CARD_FROM_SUGGESTION, {
          title: opp.title,
          description: opp.description,
          agentType: opp.agentType,
          agentName: opp.agentName,
        });
      }
      this.removeOpportunity(id);
    }
  }

  // ── Notifications tab ───────────────────────────────────────────────────────

  private renderNotificationsContent(body: HTMLElement): void {
    const notifications = appState.getNotifications();

    // Header row with actions
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
        eventBus.emit(EVENTS.NOTIFICATION_COUNT, 0);
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

    header.appendChild(title);
    header.appendChild(actions);
    body.appendChild(header);

    // Notification list
    const list = createElement('div', { className: 'notification-center-body' });

    if (notifications.length === 0) {
      const empty = createElement('div', { className: 'notification-empty' }, '✨ All caught up!');
      list.appendChild(empty);
    } else {
      notifications.forEach((notif) => {
        list.appendChild(this.renderNotificationItem(notif));
      });
    }

    body.appendChild(list);
  }

  private renderNotificationItemActions(notif: NotificationEntry): HTMLElement | null {
    const type = notif.type;

    if (type === 'opportunity') {
      const container = createElement('div', { className: 'notification-item-actions' });
      const suggestionMatch = notif.message.match(/[Ss]uggestion[:\s]+(.+)/);
      const suggestionText = suggestionMatch ? suggestionMatch[1].trim() : notif.message;

      const createBtn = createElement('button', { className: 'notification-action-btn' }, '✅ Create Card');
      createBtn.addEventListener('click', (e) => {
        e.stopPropagation();
        this.switchTab('opportunities');
        eventBus.emit(EVENTS.MODAL_OPEN, { type: 'card-detail', mode: 'create', prefillTitle: suggestionText });
        appState.markAllNotificationsRead();
        this.render();
      });

      const viewBtn = createElement('button', { className: 'notification-action-btn' }, '💡 View');
      viewBtn.addEventListener('click', (e) => {
        e.stopPropagation();
        this.switchTab('opportunities');
        appState.markAllNotificationsRead();
        this.render();
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
        eventBus.emit(EVENTS.CARD_SELECTED, { cardId: notif.link });
        appState.markAllNotificationsRead();
        this.render();
      });
      container.appendChild(openBtn);
      return container;
    }

    if (type === 'document_indexed') {
      const container = createElement('div', { className: 'notification-item-actions' });
      const docsBtn = createElement('button', { className: 'notification-action-btn' }, '📚 Open Docs');
      docsBtn.addEventListener('click', (e) => {
        e.stopPropagation();
        eventBus.emit(EVENTS.DOCS_OPEN);
        appState.markAllNotificationsRead();
        this.render();
      });
      container.appendChild(docsBtn);
      return container;
    }

    if (type === 'service_down') {
      const container = createElement('div', { className: 'notification-item-actions' });
      const retryBtn = createElement('button', { className: 'notification-action-btn' }, '🔄 Retry');
      retryBtn.addEventListener('click', (e) => {
        e.stopPropagation();
        eventBus.emit(EVENTS.SETTINGS_OPEN);
        appState.markAllNotificationsRead();
        this.render();
      });
      container.appendChild(retryBtn);
      return container;
    }

    return null;
  }

  private renderNotificationItem(notif: NotificationEntry): HTMLElement {
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

    const itemActions = this.renderNotificationItemActions(notif);
    if (itemActions) {
      content.appendChild(itemActions);
    }

    item.appendChild(icon);
    item.appendChild(content);
    return item;
  }

  // ── Listeners ───────────────────────────────────────────────────────────────

  private setupListeners(): void {
    // New opportunity suggestion
    this.unsubscribers.push(
      eventBus.on(EVENTS.CARD_SUGGESTION, (data: unknown) => {
        this.addOpportunity(data as CardSuggestion);
      })
    );

    // Notifications changed → re-render to update badge / list
    this.unsubscribers.push(
      eventBus.on(EVENTS.NOTIFICATION_ADDED, () => this.render())
    );
    this.unsubscribers.push(
      eventBus.on(EVENTS.NOTIFICATION_CLEARED, () => this.render())
    );

    // Bell button in sidebar now switches to Notifications tab
    this.unsubscribers.push(
      eventBus.on(EVENTS.NOTIFICATION_PANEL_TOGGLE, () => {
        this.switchTab('notifications');
      })
    );

    // Legacy OPPORTUNITIES_TOGGLE — switch to Opportunities tab
    this.unsubscribers.push(
      eventBus.on(EVENTS.OPPORTUNITIES_TOGGLE, () => {
        this.switchTab('opportunities');
        appState.clearOpportunityBadge();
      })
    );
  }

  destroy(): void {
    this.unsubscribers.forEach((u) => u());
    this.unsubscribers = [];
    this.container.remove();
  }
}
