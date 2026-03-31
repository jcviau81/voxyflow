import { useState, useCallback, useEffect } from 'react';
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
    <div className="bg-muted/50 rounded-lg border border-border p-3" data-id={opp.id}>
      <div className="text-xs text-muted-foreground mb-1 uppercase tracking-wide font-medium">
        {opp.agentEmoji || '🤖'} {opp.agentName || 'Ember'}
      </div>
      <div className="text-sm font-semibold text-foreground mb-1 leading-tight">{opp.title}</div>
      {opp.description && (
        <div className="text-xs text-muted-foreground mb-2.5 leading-relaxed">{opp.description}</div>
      )}
      <div className="flex gap-1.5">
        <button className="flex-1 px-3 py-1.5 bg-primary text-primary-foreground rounded text-xs font-semibold cursor-pointer transition-all hover:-translate-y-px hover:shadow-md" onClick={() => onAccept(opp.id)}>
          Create Card
        </button>
        <button className="px-2 py-1.5 bg-transparent text-muted-foreground border border-border rounded text-xs cursor-pointer transition-all hover:text-red-400 hover:border-red-400/30 hover:bg-red-400/5" onClick={() => onDismiss(opp.id)}>
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
      <div className="flex gap-1.5 mt-1.5">
        <button
          className="text-xs text-muted-foreground hover:text-foreground transition-colors cursor-pointer"
          onClick={(e) => {
            e.stopPropagation();
            onSwitchTab('opportunities');
            onMarkRead();
          }}
        >
          ✅ Create Card
        </button>
        <button
          className="text-xs text-muted-foreground hover:text-foreground transition-colors cursor-pointer"
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
      <div className="flex gap-1.5 mt-1.5">
        <button
          className="text-xs text-muted-foreground hover:text-foreground transition-colors cursor-pointer"
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
      className={cn('flex items-start gap-2.5 px-4 py-2.5 border-b border-border transition-colors hover:bg-accent/50', !notif.read && 'bg-accent/5 border-l-[3px] border-l-accent')}
      data-id={notif.id}
    >
      <span className="shrink-0 text-sm">
        {TYPE_ICONS[notif.type] || '💡'}
      </span>
      <div className="flex-1 min-w-0">
        <span className="text-xs text-foreground leading-relaxed">{notif.message}</span>
        <span className="text-[10px] text-muted-foreground mt-0.5 block">
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
  onClose?: () => void;
}

export function RightPanel({
  opportunities,
  onOpportunityAccepted,
  onOpportunityDismissed,
  defaultTab = 'opportunities',
  onClose,
}: RightPanelProps) {
  const [activeTab, setActiveTab] = useState<RightPanelTab>(defaultTab);

  // Sync active tab when the trigger icon changes it
  useEffect(() => {
    setActiveTab(defaultTab);
  }, [defaultTab]);

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
    <div className="flex flex-col h-full bg-secondary overflow-hidden" data-testid="right-panel">
      {/* Tab bar */}
      <div className="flex items-center border-b border-border shrink-0">
        <button
          className={cn('flex flex-1 items-center justify-center gap-1.5 px-3 py-2 text-xs font-medium text-muted-foreground hover:text-foreground transition-colors cursor-pointer border-b-2 border-transparent', activeTab === 'opportunities' && 'text-foreground border-primary')}
          data-tab="opportunities"
          title="Opportunities"
          onClick={() => switchTab('opportunities')}
        >
          💡 Opportunities
          {opportunities.length > 0 && (
            <span className="bg-primary text-primary-foreground text-[10px] font-bold px-1.5 rounded-full min-w-[16px] text-center">{opportunities.length}</span>
          )}
        </button>
        <button
          className={cn('flex flex-1 items-center justify-center gap-1.5 px-3 py-2 text-xs font-medium text-muted-foreground hover:text-foreground transition-colors cursor-pointer border-b-2 border-transparent', activeTab === 'notifications' && 'text-foreground border-primary')}
          data-tab="notifications"
          title="Notifications"
          onClick={() => switchTab('notifications')}
        >
          🔔 Notifications
          {notificationUnreadCount > 0 && (
            <span className="bg-red-500 text-primary-foreground text-[10px] font-bold px-1.5 rounded-full min-w-[16px] text-center">
              {notificationUnreadCount > 99 ? '99+' : notificationUnreadCount}
            </span>
          )}
        </button>
        {onClose && (
          <button
            className="flex items-center justify-center w-7 h-7 mr-1 rounded text-muted-foreground hover:text-foreground hover:bg-accent transition-colors flex-shrink-0"
            title="Close"
            onClick={onClose}
          >
            ×
          </button>
        )}
      </div>

      {/* Body */}
      <div className="flex-1 overflow-y-auto p-3">
        {activeTab === 'opportunities' ? (
          <>
            <div className="flex justify-between items-center mb-3.5 pb-2.5 border-b border-border">
              <h3 className="text-sm font-semibold text-foreground">💡 Opportunities</h3>
              <span className="bg-primary text-primary-foreground text-xs font-bold px-2 py-0.5 rounded-full min-w-[18px] text-center">{opportunities.length}</span>
            </div>
            <div className="flex flex-col gap-2.5">
              {opportunities.length === 0 ? (
                <div className="text-xs text-muted-foreground text-center py-10 px-4 leading-relaxed">
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
            <div className="flex justify-between items-center px-3 py-2 border-b border-border">
              <h3 className="text-sm font-semibold text-foreground">🔔 Notifications</h3>
              {notifications.length > 0 && (
                <div className="flex gap-2">
                  <button
                    className="text-xs text-muted-foreground hover:text-foreground transition-colors cursor-pointer"
                    title="Mark all as read"
                    onClick={() => markAllNotificationsRead()}
                  >
                    Mark all read
                  </button>
                  <button
                    className="text-xs text-muted-foreground hover:text-red-400 transition-colors cursor-pointer"
                    title="Clear all notifications"
                    onClick={() => clearNotifications()}
                  >
                    Clear all
                  </button>
                </div>
              )}
            </div>
            <div className="flex-1 overflow-y-auto">
              {notifications.length === 0 ? (
                <div className="text-xs text-muted-foreground text-center py-10">✨ All caught up!</div>
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
