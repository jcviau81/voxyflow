/**
 * HistorySection — collapsible card change history timeline.
 * Port of the vanilla buildHistorySection().
 */

import { useState } from 'react';
import { History, ChevronDown, ChevronRight } from 'lucide-react';
import { cn } from '@/lib/utils';
import type { CardHistoryEntry } from '../../types';
import { useCardHistory } from '../../hooks/api/useCards';

// ── Constants ────────────────────────────────────────────────────────────────

const STATUS_COLOR: Record<string, string> = {
  card: 'text-slate-400 border-slate-400',
  todo: 'text-blue-400 border-blue-400',
  'in-progress': 'text-amber-400 border-amber-400',
  done: 'text-emerald-400 border-emerald-400',
  archived: 'text-gray-500 border-gray-500',
};

const FIELD_LABELS: Record<string, string> = {
  status: 'Status',
  priority: 'Priority',
  title: 'Title',
  description: 'Description',
  assignee: 'Assignee',
  agent_type: 'Agent',
};

const PRIORITY_LABELS: Record<string, string> = {
  '0': 'None',
  '1': 'Low',
  '2': 'Medium',
  '3': 'High',
  '4': 'Critical',
};

function formatValue(field: string, value: string | null): string {
  if (value === null || value === 'None' || value === 'null') return '—';
  if (field === 'priority') return PRIORITY_LABELS[value] ?? value;
  if (field === 'description') {
    return value.length > 60 ? value.slice(0, 57) + '…' : value;
  }
  return value;
}

function formatDate(ts: string): string {
  return new Date(ts).toLocaleDateString(undefined, {
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  });
}

// ── Sub-component: single history entry ──────────────────────────────────────

function HistoryEntry({ entry }: { entry: CardHistoryEntry }) {
  const fieldLabel = FIELD_LABELS[entry.fieldChanged] ?? entry.fieldChanged;

  return (
    <div className="flex items-center gap-2 py-1 text-xs">
      <span className="shrink-0 font-medium text-muted-foreground">{fieldLabel}</span>

      {entry.fieldChanged === 'status' ? (
        <span className="flex items-center gap-1">
          <span
            className={cn(
              'rounded border px-1 py-0.5 text-[10px]',
              STATUS_COLOR[entry.oldValue ?? ''] ?? 'text-muted-foreground border-border',
            )}
          >
            {formatValue('status', entry.oldValue)}
          </span>
          <span className="text-muted-foreground/60">→</span>
          <span
            className={cn(
              'rounded border px-1 py-0.5 text-[10px] font-semibold',
              STATUS_COLOR[entry.newValue ?? ''] ?? 'text-muted-foreground border-border',
            )}
          >
            {formatValue('status', entry.newValue)}
          </span>
        </span>
      ) : (
        <span className="truncate text-muted-foreground/80">
          {formatValue(entry.fieldChanged, entry.oldValue)} →{' '}
          {formatValue(entry.fieldChanged, entry.newValue)}
        </span>
      )}

      <span className="ml-auto shrink-0 text-[10px] text-muted-foreground/50">
        {formatDate(entry.changedAt)}
      </span>
    </div>
  );
}

// ── Main component ───────────────────────────────────────────────────────────

export function HistorySection({ cardId }: { cardId: string }) {
  const [expanded, setExpanded] = useState(false);
  const { data: entries = [], isLoading } = useCardHistory(cardId);

  const shown = entries.slice(0, 20);

  return (
    <div className="space-y-1">
      {/* Collapsible header */}
      <button
        type="button"
        onClick={() => setExpanded((v) => !v)}
        className="flex w-full items-center gap-1 text-xs font-medium text-muted-foreground hover:text-foreground"
      >
        {expanded ? <ChevronDown size={11} /> : <ChevronRight size={11} />}
        <History size={11} />
        <span>History</span>
      </button>

      {/* Body */}
      {expanded && (
        <div className="space-y-0.5 pl-3">
          {isLoading && (
            <p className="text-xs text-muted-foreground/60">Loading…</p>
          )}
          {!isLoading && shown.length === 0 && (
            <p className="text-xs text-muted-foreground/60">No changes recorded yet.</p>
          )}
          {shown.map((e) => (
            <HistoryEntry key={e.id} entry={e} />
          ))}
        </div>
      )}
    </div>
  );
}
