import { cn } from '@/lib/utils';
import type { CardStatus } from '../../types';

const CARD_STATUSES: CardStatus[] = ['idea', 'todo', 'in-progress', 'done'];

const STATUS_LABELS: Record<string, string> = {
  idea: 'Idea',
  todo: 'To Do',
  'in-progress': 'In Progress',
  done: 'Done',
};

const STATUS_COLORS: Record<string, string> = {
  idea: 'bg-slate-500/20 text-slate-400 border-slate-500/30',
  todo: 'bg-blue-500/20 text-blue-400 border-blue-500/30',
  'in-progress': 'bg-amber-500/20 text-amber-400 border-amber-500/30',
  done: 'bg-emerald-500/20 text-emerald-400 border-emerald-500/30',
};

const STATUS_ACTIVE: Record<string, string> = {
  idea: 'bg-slate-500/40 text-slate-200 border-slate-400',
  todo: 'bg-blue-500/40 text-blue-200 border-blue-400',
  'in-progress': 'bg-amber-500/40 text-amber-200 border-amber-400',
  done: 'bg-emerald-500/40 text-emerald-200 border-emerald-400',
};

interface StatusButtonsProps {
  current: CardStatus;
  onChange: (status: CardStatus) => void;
}

export function StatusButtons({ current, onChange }: StatusButtonsProps) {
  return (
    <div className="flex flex-wrap gap-1.5">
      {CARD_STATUSES.map((status) => (
        <button
          key={status}
          type="button"
          onClick={() => onChange(status)}
          className={cn(
            'rounded-md border px-2.5 py-1 text-xs font-medium transition-colors cursor-pointer',
            current === status ? STATUS_ACTIVE[status] : STATUS_COLORS[status],
            'hover:opacity-80',
          )}
        >
          {STATUS_LABELS[status]}
        </button>
      ))}
    </div>
  );
}
