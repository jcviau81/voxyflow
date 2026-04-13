import { useState, useEffect } from 'react';
import { CheckCircle2, XCircle, Loader2 } from 'lucide-react';
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
} from '@/components/ui/dialog';
import type { NotificationEntry } from '../../types';

interface Props {
  notification: NotificationEntry | null;
  onClose: () => void;
}

function formatTime(ts: number): string {
  return new Date(ts).toLocaleString();
}

export function NotificationDetailDialog({ notification, onClose }: Props) {
  const [fullResult, setFullResult] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!notification) {
      setFullResult(null);
      return;
    }

    if (notification.type === 'worker_completed' && notification.taskId) {
      setLoading(true);
      fetch(`/api/worker-tasks/${notification.taskId}/artifact`)
        .then((r) => (r.ok ? r.json() : null))
        .then((data) => {
          if (data?.content) {
            setFullResult(data.content);
          } else {
            // Try DB result_summary as fallback
            return fetch(`/api/worker-tasks/${notification.taskId}`)
              .then((r) => (r.ok ? r.json() : null))
              .then((task) => {
                setFullResult(
                  task?.result_summary ||
                    task?.error ||
                    'Full result no longer available (cleaned up after 24h).',
                );
              });
          }
        })
        .catch(() => {
          setFullResult('Failed to load result.');
        })
        .finally(() => setLoading(false));
    } else if (notification.type === 'system_job') {
      setFullResult(notification.details || notification.message);
    } else {
      setFullResult(notification.message);
    }
  }, [notification]);

  return (
    <Dialog
      open={!!notification}
      onOpenChange={(open) => {
        if (!open) onClose();
      }}
    >
      <DialogContent className="max-w-2xl max-h-[80vh] flex flex-col">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            {notification?.success === false ? (
              <XCircle size={16} className="text-red-400 shrink-0" />
            ) : (
              <CheckCircle2 size={16} className="text-green-500 shrink-0" />
            )}
            <span className="truncate">
              {notification?.type === 'worker_completed'
                ? 'Worker Result'
                : 'System Job Result'}
            </span>
          </DialogTitle>
          <DialogDescription>
            {notification && formatTime(notification.timestamp)}
            {notification?.type === 'worker_completed' && notification.taskId && (
              <span className="ml-2 text-[10px] text-muted-foreground font-mono">
                {notification.taskId.slice(0, 8)}
              </span>
            )}
          </DialogDescription>
        </DialogHeader>

        {/* Summary line */}
        <div className="text-sm text-foreground">{notification?.message}</div>

        {/* Full result body */}
        <div className="flex-1 overflow-y-auto min-h-0 max-h-[60vh] text-xs font-mono whitespace-pre-wrap bg-muted/30 rounded p-3 border border-border">
          {loading ? (
            <div className="flex items-center gap-2 text-muted-foreground">
              <Loader2 size={14} className="animate-spin" />
              Loading full result...
            </div>
          ) : (
            fullResult || 'No details available.'
          )}
        </div>
      </DialogContent>
    </Dialog>
  );
}
