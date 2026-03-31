import { useState, useCallback } from 'react';
import { cn } from '@/lib/utils';
import { useNotificationStore } from '../../stores/useNotificationStore';
import { useProjectStore } from '../../stores/useProjectStore';
import { useCardStore } from '../../stores/useCardStore';
import type { NotificationEntry, NotificationType } from '../../types';
import type { CardSuggestion } from '../../contexts/ChatProvider';

// ── Types ────────────────────────────────────────────────────────────────────

type RightPanelTab = 'opportunities' | 'notifications';

// ── Helpers ──────────────────────────────────────────────────────────────────

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

// ── Sub-components ───────────────────────────────────────────────────────────

interface OpportunityCardProps {
  opp: CardSuggestion;
  onAccept: (id: string) => void;
  onDismiss: (id: string) => void;
}

function OpportunityCard({ opp, onAccept, onDismiss }: OpportunityCardProps) {
  return (
    <div className="opportunity-card" data-id={opp.id}>
      <div className="opp-agent">
        {opp.agentEmoji || '🤖'} {opp.agentName || 'Ember'}
      </div>
      <div className="opp-title">{opp.title}</div>
      {opp.description && (
        <div className="opp-description">{opp.description}</div>
      )}
      <div className="opp-actions">
        <button className="opp-accept" onClick={() => onAccept(opp.id)}>
          Create Card
        </button>
        <button className="opp-dismiss" onClick={() => onDismiss(opp.id)}>
          ✕
        </button>
      </div>
    </div>
  );
}

interface NotificationItemActionsProps {
  notif: NotificationEntry;
  onMarkRead: () => void;
  onSwitchTab: (tab: RightPanelTab) => void;
  selectCard: (id: string | null) => void;
}

function NotificationItemActions({
  notif,
  onMarkRead,
  onSwitchTab,
  selectCard,
}: NotificationItemActionsProps) {
  const type = notif.type as NotificationType;

  if (type === 'opportunity') {
    const suggestionMatch = notif.message.match(/[Ss]uggestion[:\s]+(.+)/);
    const suggestionText = suggestionMatch
      ? suggestionMatch[1].trim()
      : notif.message;

    return (
      <div className="notification-item-actions">
        <button
          className="notification-action-btn"
          onClick={(e) => {
            e.stopPropagation();
            onSwitchTab('opportunities');
            onMarkRead();
          }}
        >
          ✅ Create Card
        </button>
        <button
          className="notification-action-btn"
          onClick={(e) => {
            e.stopPropagation();
            onSwitchTab('opportunities');
            onMarkRead();
          }}
        >
          💡 View
        </button>
      </div>
    );
    // eslint-disable-next-line @typescript-eslint/no-unused-expressions
    void suggestionText;
  }

  if (
    (type === 'card_created' || type === 'card_moved' || type === 'card_enriched') &&
    notif.link
  ) {
    return (
      <div className="notification-item-actions">
        <button
          className="notification-action-btn"
          onClick={(e) => {
            e.stopPropagation();
            selectCard(notif.link!);
            onMarkRead();
          }}
        >
          📋 Open Card
        </button>
      </div>
    );
  }

  return null;
}

interface NotificationItemProps {
  notif: NotificationEntry;
  onMarkRead: () => void;
  onSwitchTab: (tab: RightPanelTab) => void;
  selectCard: (id: string | null) => void;
}

function NotificationItem({
  notif,
  onMarkRead,
  onSwitchTab,
  selectCard,
}: NotificationItemProps) {
  return (
    <div
      className={cn('notification-item', !notif.read && 'unread')}
      data-id={notif.id}
    >
      <span className="notification-item-icon">
        {TYPE_ICONS[notif.type] || '💡'}
      </span>
      <div className="notification-item-content">
        <span className="notification-item-message">{notif.message}</span>
        <span className="notification-meta">
          {formatRelativeTime(notif.timestamp)}
        </span>
        <NotificationItemActions
          notif={notif}
          onMarkRead={onMarkRead}
          onSwitchTab={onSwitchTab}
          selectCard={selectCard}
        />
      </div>
    </div>
  );
}

// ── Main component ───────────────────────────────────────────────────────────

export interface RightPanelProps {
  opportunities: CardSuggestion[];
  onOpportunityAccepted: (id: string) => void;
  onOpportunityDismissed: (id: string) => void;
  defaultTab?: RightPanelTab;
}

export function RightPanel({
  opportunities,
  onOpportunityAccepted,
  onOpportunityDismissed,
  defaultTab = 'opportunities',
}: RightPanelProps) {
  const [activeTab, setActiveTab] = useState<RightPanelTab>(defaultTab);

  const notifications = useNotificationStore((s) => s.notifications);
  const notificationUnreadCount = useNotificationStore(
    (s) => s.notificationUnreadCount,
  );
  const markAllNotificationsRead = useNotificationStore(
    (s) => s.markAllNotificationsRead,
  );
  const clearNotifications = useNotificationStore((s) => s.clearNotifications);
  const currentProjectId = useProjectStore((s) => s.currentProjectId);
  const selectCard = useProjectStore((s) => s.selectCard);
  const addCard = useCardStore((s) => s.addCard);

  const switchTab = useCallback(
    (tab: RightPanelTab) => {
      setActiveTab(tab);
      if (tab === 'notifications') {
        markAllNotificationsRead();
      }
    },
    [markAllNotificationsRead],
  );

  const handleAcceptOpportunity = useCallback(
    (id: string) => {
      const opp = opportunities.find((o) => o.id === id);
      if (opp) {
        if (currentProjectId) {
          // Create a card and open it in the detail modal
          const card = addCard({
            projectId: currentProjectId,
            title: opp.title,
            description: opp.description,
            status: 'todo',
            agentType: opp.agentType,
            priority: 0,
            dependencies: [],
            tags: [],
          });
          selectCard(card.id);
        }
        onOpportunityAccepted(id);
      }
    },
    [opportunities, currentProjectId, addCard, selectCard, onOpportunityAccepted],
  );

  return (
    <div className="right-panel" data-testid="right-panel">
      {/* Tab bar */}
      <div className="right-panel-tabs">
        <button
          className={cn('right-panel-tab', activeTab === 'opportunities' && 'active')}
          data-tab="opportunities"
          title="Opportunities"
          onClick={() => switchTab('opportunities')}
        >
          💡 Opportunities
          {opportunities.length > 0 && (
            <span className="right-panel-tab-badge">{opportunities.length}</span>
          )}
        </button>
        <button
          className={cn('right-panel-tab', activeTab === 'notifications' && 'active')}
          data-tab="notifications"
          title="Notifications"
          onClick={() => switchTab('notifications')}
        >
          🔔 Notifications
          {notificationUnreadCount > 0 && (
            <span className="right-panel-tab-badge unread">
              {notificationUnreadCount > 99 ? '99+' : notificationUnreadCount}
            </span>
          )}
        </button>
      </div>

      {/* Body */}
      <div className="right-panel-body">
        {activeTab === 'opportunities' ? (
          <>
            <div className="opportunities-header">
              <h3>💡 Opportunities</h3>
              <span className="opportunities-badge">{opportunities.length}</span>
            </div>
            <div className="opportunities-list">
              {opportunities.length === 0 ? (
                <div className="opportunities-empty">
                  No suggestions yet. Start chatting!
                </div>
              ) : (
                opportunities.map((opp) => (
                  <OpportunityCard
                    key={opp.id}
                    opp={opp}
                    onAccept={handleAcceptOpportunity}
                    onDismiss={onOpportunityDismissed}
                  />
                ))
              )}
            </div>
          </>
        ) : (
          <>
            <div className="notification-center-header">
              <h3 className="notification-center-title">🔔 Notifications</h3>
              {notifications.length > 0 && (
                <div className="notification-center-actions">
                  <button
                    className="notification-action-btn"
                    title="Mark all as read"
                    onClick={() => markAllNotificationsRead()}
                  >
                    Mark all read
                  </button>
                  <button
                    className="notification-action-btn notification-action-btn--danger"
                    title="Clear all notifications"
                    onClick={() => clearNotifications()}
                  >
                    Clear all
                  </button>
                </div>
              )}
            </div>
            <div className="notification-center-body">
              {notifications.length === 0 ? (
                <div className="notification-empty">✨ All caught up!</div>
              ) : (
                notifications.map((notif) => (
                  <NotificationItem
                    key={notif.id}
                    notif={notif}
                    onMarkRead={markAllNotificationsRead}
                    onSwitchTab={switchTab}
                    selectCard={selectCard}
                  />
                ))
              )}
            </div>
          </>
        )}
      </div>
    </div>
  );
}
