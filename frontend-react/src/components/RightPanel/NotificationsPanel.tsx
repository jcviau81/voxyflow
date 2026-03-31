import { useEffect } from 'react';
import { cn } from '@/lib/utils';
import { useNotificationStore } from '../../stores/useNotificationStore';
import { useProjectStore } from '../../stores/useProjectStore';
import type { NotificationEntry, NotificationType } from '../../types';

const TYPE_ICONS: Record<string, string> = {
  card_moved:       '📋',
  card_created:     '✅',
  card_deleted:     '🗑️',
  card_enriched:    '✨',
  opportunity:      '🔔',
  service_down:     '⚠️',
  document_indexed: '📄',
  focus_completed:  '🎯',
  system:           '💡',
};

function formatRelativeTime(timestamp: number): string {
  const diff = Date.now() - timestamp;
  const seconds = Math.floor(diff / 1000);
  if (seconds < 60) return 'just now';
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  return `${Math.floor(hours / 24)}d ago`;
}

interface NotificationItemProps {
  notif: NotificationEntry;
  onOpenOpportunities: () => void;
  selectCard: (id: string | null) => void;
}

function NotificationItem({ notif, onOpenOpportunities, selectCard }: NotificationItemProps) {
  const type = notif.type as NotificationType;

  return (
    <div
      className={cn(
        'flex items-start gap-2.5 px-4 py-2.5 border-b border-border transition-colors hover:bg-accent/50',
        !notif.read && 'bg-accent/5 border-l-[3px] border-l-accent',
      )}
    >
      <span className="shrink-0 text-sm">{TYPE_ICONS[notif.type] || '💡'}</span>
      <div className="flex-1 min-w-0">
        <span className="text-xs text-foreground leading-relaxed">{notif.message}</span>
        <span className="text-[10px] text-muted-foreground mt-0.5 block">
          {formatRelativeTime(notif.timestamp)}
        </span>

        {/* Actions */}
        {type === 'opportunity' && (
          <div className="flex gap-1.5 mt-1.5">
            <button
              className="text-xs text-muted-foreground hover:text-foreground transition-colors cursor-pointer"
              onClick={(e) => { e.stopPropagation(); onOpenOpportunities(); }}
            >
              💡 View in Opportunities
            </button>
          </div>
        )}

        {(type === 'card_created' || type === 'card_moved' || type === 'card_enriched') && notif.link && (
          <div className="flex gap-1.5 mt-1.5">
            <button
              className="text-xs text-muted-foreground hover:text-foreground transition-colors cursor-pointer"
              onClick={(e) => { e.stopPropagation(); selectCard(notif.link!); }}
            >
              📋 Open Card
            </button>
          </div>
        )}
      </div>
    </div>
  );
}

export interface NotificationsPanelProps {
  onClose: () => void;
  onOpenOpportunities: () => void;
}

export function NotificationsPanel({ onClose, onOpenOpportunities }: NotificationsPanelProps) {
  const notifications = useNotificationStore((s) => s.notifications);
  const markAllNotificationsRead = useNotificationStore((s) => s.markAllNotificationsRead);
  const clearNotifications = useNotificationStore((s) => s.clearNotifications);
  const selectCard = useProjectStore((s) => s.selectCard);

  // Mark all read when panel opens
  useEffect(() => {
    markAllNotificationsRead();
  }, [markAllNotificationsRead]);

  return (
    <div className="flex flex-col h-full bg-secondary overflow-hidden" data-testid="notifications-panel">
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-3 border-b border-border shrink-0">
        <span className="text-sm font-semibold text-foreground">🔔 Notifications</span>
        <div className="flex items-center gap-1">
          {notifications.length > 0 && (
            <>
              <button
                className="text-xs text-muted-foreground hover:text-foreground transition-colors cursor-pointer px-1.5"
                onClick={markAllNotificationsRead}
              >
                Mark all read
              </button>
              <button
                className="text-xs text-muted-foreground hover:text-red-400 transition-colors cursor-pointer px-1.5"
                onClick={clearNotifications}
              >
                Clear
              </button>
            </>
          )}
          <button
            className="flex items-center justify-center w-7 h-7 rounded text-muted-foreground hover:text-foreground hover:bg-accent transition-colors"
            title="Close"
            onClick={onClose}
          >
            ×
          </button>
        </div>
      </div>

      {/* Body */}
      <div className="flex-1 overflow-y-auto">
        {notifications.length === 0 ? (
          <div className="text-xs text-muted-foreground text-center py-10">✨ All caught up!</div>
        ) : (
          notifications.map((notif) => (
            <NotificationItem
              key={notif.id}
              notif={notif}
              onOpenOpportunities={() => { onClose(); onOpenOpportunities(); }}
              selectCard={selectCard}
            />
          ))
        )}
      </div>
    </div>
  );
}
