import { useEffect, useState } from 'react';
import {
  Bell,
  X,
  Lightbulb,
  ExternalLink,
  CheckCircle2,
  Trash2,
  AlertTriangle,
  FileText,
  Target,
  Sparkles,
  Cpu,
  Clock,
  ChevronRight,
  XCircle,
} from 'lucide-react';
import { cn } from '@/lib/utils';
import { useNotificationStore } from '../../stores/useNotificationStore';
import { useProjectStore } from '../../stores/useProjectStore';
import type { NotificationEntry } from '../../types';
import { NotificationDetailDialog } from './NotificationDetailDialog';

function NotifIcon({ type, success }: { type: string; success?: boolean }) {
  switch (type) {
    case 'card_moved':
      return <ExternalLink size={13} />;
    case 'card_created':
      return <CheckCircle2 size={13} className="text-green-500" />;
    case 'card_deleted':
      return <Trash2 size={13} className="text-red-400" />;
    case 'card_enriched':
      return <Sparkles size={13} className="text-yellow-400" />;
    case 'service_down':
      return <AlertTriangle size={13} className="text-orange-400" />;
    case 'document_indexed':
      return <FileText size={13} />;
    case 'focus_completed':
      return <Target size={13} className="text-blue-400" />;
    case 'worker_completed':
      return success === false ? (
        <XCircle size={13} className="text-red-400" />
      ) : (
        <Cpu size={13} className="text-blue-400" />
      );
    case 'system_job':
      return success === false ? (
        <AlertTriangle size={13} className="text-orange-400" />
      ) : (
        <Clock size={13} className="text-muted-foreground" />
      );
    default:
      return <Lightbulb size={13} />;
  }
}

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

const DETAIL_TYPES = new Set(['worker_completed', 'system_job']);

interface NotificationItemProps {
  notif: NotificationEntry;
  selectCard: (id: string | null) => void;
  onDetailClick: (notif: NotificationEntry) => void;
}

function NotificationItem({ notif, selectCard, onDetailClick }: NotificationItemProps) {
  const hasDetail = DETAIL_TYPES.has(notif.type);
  const isCardType =
    notif.type === 'card_created' || notif.type === 'card_moved' || notif.type === 'card_enriched';

  return (
    <div
      className={cn(
        'flex items-start gap-2.5 px-4 py-2.5 border-b border-border transition-colors',
        !notif.read && 'bg-accent/5 border-l-[3px] border-l-accent',
        hasDetail && 'cursor-pointer hover:bg-accent/50',
        !hasDetail && 'hover:bg-accent/30',
      )}
      onClick={() => {
        if (hasDetail) onDetailClick(notif);
      }}
    >
      <span className="shrink-0 mt-0.5 text-muted-foreground">
        <NotifIcon type={notif.type} success={notif.success} />
      </span>
      <div className="flex-1 min-w-0">
        <span className="text-xs text-foreground leading-relaxed">{notif.message}</span>
        <span className="text-[10px] text-muted-foreground mt-0.5 block">
          {formatRelativeTime(notif.timestamp)}
        </span>

        {isCardType && notif.link && (
          <div className="flex gap-1.5 mt-1.5">
            <button
              className="flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground transition-colors cursor-pointer"
              onClick={(e) => {
                e.stopPropagation();
                selectCard(notif.link!);
              }}
            >
              <ExternalLink size={11} /> Open Card
            </button>
          </div>
        )}
      </div>
      {hasDetail && (
        <ChevronRight size={13} className="shrink-0 mt-1 text-muted-foreground" />
      )}
    </div>
  );
}

export interface NotificationsPanelProps {
  onClose: () => void;
}

export function NotificationsPanel({ onClose }: NotificationsPanelProps) {
  const notifications = useNotificationStore((s) => s.notifications);
  const markAllNotificationsRead = useNotificationStore((s) => s.markAllNotificationsRead);
  const clearNotifications = useNotificationStore((s) => s.clearNotifications);
  const selectCard = useProjectStore((s) => s.selectCard);
  const [detailNotif, setDetailNotif] = useState<NotificationEntry | null>(null);

  // Mark all read when panel opens
  useEffect(() => {
    markAllNotificationsRead();
  }, [markAllNotificationsRead]);

  return (
    <div className="flex flex-col h-full bg-secondary overflow-hidden" data-testid="notifications-panel">
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-3 border-b border-border shrink-0">
        <span className="flex items-center gap-1.5 text-sm font-semibold text-foreground">
          <Bell size={15} /> Notifications
        </span>
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
            <X size={15} />
          </button>
        </div>
      </div>

      {/* Body */}
      <div className="flex-1 overflow-y-auto">
        {notifications.length === 0 ? (
          <div className="text-xs text-muted-foreground text-center py-10">All caught up!</div>
        ) : (
          notifications.map((notif) => (
            <NotificationItem
              key={notif.id}
              notif={notif}
              selectCard={selectCard}
              onDetailClick={setDetailNotif}
            />
          ))
        )}
      </div>

      {/* Detail dialog */}
      <NotificationDetailDialog
        notification={detailNotif}
        onClose={() => setDetailNotif(null)}
      />
    </div>
  );
}
