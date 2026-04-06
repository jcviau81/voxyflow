/**
 * CliSessionsBadge — shows active CLI subprocess count in the sidebar.
 *
 * Expandable list with model, context, duration, and kill button per session.
 * Polls GET /api/cli-sessions/active every 5 seconds.
 */

import { useState } from 'react';
import { Cpu, X, ChevronRight } from 'lucide-react';
import { cn } from '../../lib/utils';
import { useCliSessions } from '../../hooks/useCliSessions';

const MODEL_COLORS: Record<string, string> = {
  haiku: 'bg-green-500',
  sonnet: 'bg-blue-500',
  opus: 'bg-purple-500',
};

function formatDuration(seconds: number): string {
  if (seconds < 60) return `${Math.round(seconds)}s`;
  const m = Math.floor(seconds / 60);
  const s = Math.round(seconds % 60);
  return `${m}m${s}s`;
}

function contextLabel(chatId: string): string {
  if (!chatId) return 'Unknown';
  if (chatId.startsWith('project:')) return chatId.replace('project:', 'Project ').slice(0, 20);
  if (chatId.startsWith('card:')) return 'Card chat';
  if (chatId.startsWith('task-')) return 'Worker';
  return chatId.slice(0, 20);
}

export function CliSessionsBadge() {
  const { sessions, count, kill } = useCliSessions();
  const [expanded, setExpanded] = useState(true);

  if (count === 0) return null;

  return (
    <div className="mt-3 pt-2 border-t border-border">
      <button
        className="sidebar-section-header w-full px-5 py-1 text-[10px] font-semibold uppercase tracking-wider text-muted-foreground whitespace-nowrap flex items-center gap-1.5 hover:text-foreground transition-colors"
        onClick={() => setExpanded((v) => !v)}
      >
        <Cpu size={10} className="shrink-0" />
        CLI Processes
        <span className="ml-auto flex items-center gap-1">
          <span className="inline-flex items-center justify-center min-w-[16px] h-4 px-1 rounded-full bg-primary/20 text-primary text-[9px] font-bold tabular-nums">
            {count}
          </span>
          <ChevronRight
            size={10}
            className={cn('transition-transform', expanded && 'rotate-90')}
          />
        </span>
      </button>

      {expanded && (
        <div className="mt-1">
          {sessions.map((s) => (
            <div
              key={s.id}
              className="flex items-center gap-1.5 px-3 py-1.5 mx-2 rounded-md text-xs group hover:bg-accent hover:text-accent-foreground transition-colors"
            >
              {/* Model dot */}
              <span
                className={cn(
                  'shrink-0 w-2 h-2 rounded-full',
                  MODEL_COLORS[s.model] || 'bg-muted-foreground/30',
                )}
                title={s.model}
              />

              {/* Info */}
              <span className="flex-1 truncate">
                <span className="font-medium">{s.model}</span>
                <span className="text-muted-foreground ml-1">
                  {s.type === 'worker' ? 'worker' : contextLabel(s.chatId)}
                </span>
              </span>

              {/* Duration */}
              <span className="shrink-0 text-[10px] text-muted-foreground tabular-nums">
                {formatDuration(s.durationSeconds)}
              </span>

              {/* Kill button */}
              <button
                className="shrink-0 opacity-0 group-hover:opacity-100 transition-opacity text-muted-foreground hover:text-red-400"
                title="Kill process"
                onClick={() => kill(s.id)}
              >
                <X size={12} />
              </button>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
