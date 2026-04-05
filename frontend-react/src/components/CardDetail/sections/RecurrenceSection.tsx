import { cn } from '@/lib/utils';
import { Repeat } from 'lucide-react';

type RecurrenceValue = 'daily' | 'weekly' | 'monthly';

const OPTIONS: { value: RecurrenceValue | null; label: string }[] = [
  { value: null, label: 'None' },
  { value: 'daily', label: 'Daily' },
  { value: 'weekly', label: 'Weekly' },
  { value: 'monthly', label: 'Monthly' },
];

interface RecurrenceSectionProps {
  current: string | null | undefined;
  nextDate: string | null | undefined;
  onChange: (value: string | null) => void;
}

export function RecurrenceSection({ current, nextDate, onChange }: RecurrenceSectionProps) {
  const selected = (current as RecurrenceValue | null) ?? null;

  return (
    <div>
      <label className="mb-1 flex items-center gap-1 text-xs font-medium text-muted-foreground">
        <Repeat size={12} />
        Recurrence
      </label>
      <div className="flex flex-wrap gap-1.5">
        {OPTIONS.map(({ value, label }) => (
          <button
            key={label}
            type="button"
            onClick={() => onChange(value)}
            className={cn(
              'rounded-md border px-2.5 py-1 text-xs font-medium transition-colors cursor-pointer',
              selected === value
                ? 'bg-primary/20 text-primary border-primary/40'
                : 'bg-muted/40 text-muted-foreground border-border hover:bg-muted/60',
            )}
          >
            {label}
          </button>
        ))}
      </div>
      {selected && nextDate && (
        <p className="mt-1.5 text-[10px] text-muted-foreground/70">
          Next: {new Date(nextDate).toLocaleDateString(undefined, {
            month: 'short',
            day: 'numeric',
            year: 'numeric',
            hour: '2-digit',
            minute: '2-digit',
          })}
        </p>
      )}
    </div>
  );
}
