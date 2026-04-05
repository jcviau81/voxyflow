import { useState } from 'react';
import { cn } from '@/lib/utils';
import { Repeat } from 'lucide-react';

const PRESETS: { value: string | null; label: string }[] = [
  { value: null, label: 'None' },
  { value: '15min', label: '15m' },
  { value: '30min', label: '30m' },
  { value: 'hourly', label: '1h' },
  { value: '6hours', label: '6h' },
  { value: 'daily', label: 'Day' },
  { value: 'weekdays', label: 'M-F' },
  { value: 'weekly', label: 'Week' },
  { value: 'biweekly', label: '2wk' },
  { value: 'monthly', label: 'Month' },
];

const PRESET_VALUES = new Set(PRESETS.map((p) => p.value));

interface RecurrenceSectionProps {
  current: string | null | undefined;
  nextDate: string | null | undefined;
  onChange: (value: string | null) => void;
}

export function RecurrenceSection({ current, nextDate, onChange }: RecurrenceSectionProps) {
  const selected = current ?? null;
  const isCustom = selected !== null && !PRESET_VALUES.has(selected);
  const [showCron, setShowCron] = useState(isCustom);
  const [cronInput, setCronInput] = useState(isCustom ? selected : '');

  return (
    <div>
      <label className="mb-1 flex items-center gap-1 text-xs font-medium text-muted-foreground">
        <Repeat size={12} />
        Recurrence
      </label>

      {/* Preset pills */}
      <div className="flex flex-wrap gap-1.5">
        {PRESETS.map(({ value, label }) => (
          <button
            key={label}
            type="button"
            onClick={() => { onChange(value); setShowCron(false); }}
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
        <button
          type="button"
          onClick={() => setShowCron((v) => !v)}
          className={cn(
            'rounded-md border px-2.5 py-1 text-xs font-medium transition-colors cursor-pointer',
            isCustom
              ? 'bg-primary/20 text-primary border-primary/40'
              : 'bg-muted/40 text-muted-foreground border-border hover:bg-muted/60',
          )}
        >
          Cron
        </button>
      </div>

      {/* Custom cron input */}
      {showCron && (
        <div className="mt-2 space-y-2">
          <div className="flex gap-1.5">
            <input
              type="text"
              value={cronInput}
              onChange={(e) => setCronInput(e.target.value)}
              placeholder="0 9 * * 1-5"
              className="flex-1 rounded-md border border-border bg-background px-2 py-1 text-xs text-foreground placeholder:text-muted-foreground/50 focus:outline-none focus:ring-1 focus:ring-primary/50"
            />
            <button
              type="button"
              onClick={() => { if (cronInput.trim()) onChange(`cron:${cronInput.trim()}`); }}
              className="rounded-md border border-primary/40 bg-primary/20 px-2.5 py-1 text-xs font-medium text-primary transition-colors hover:bg-primary/30 cursor-pointer"
            >
              Set
            </button>
          </div>
          <div className="flex flex-wrap gap-1">
            {[
              { cron: '0 9 * * 1-5', label: '9am weekdays' },
              { cron: '0 8,17 * * *', label: '8am & 5pm' },
              { cron: '0 0 * * 0', label: 'Sunday midnight' },
              { cron: '0 12 1 * *', label: '1st of month noon' },
              { cron: '*/10 * * * *', label: 'Every 10min' },
            ].map(({ cron, label }) => (
              <button
                key={cron}
                type="button"
                onClick={() => { setCronInput(cron); onChange(`cron:${cron}`); }}
                className="rounded border border-border/60 bg-muted/30 px-1.5 py-0.5 text-[10px] text-muted-foreground hover:bg-muted/60 hover:text-foreground transition-colors cursor-pointer"
              >
                {label}
              </button>
            ))}
          </div>
          <p className="text-[10px] text-muted-foreground/50">min hour day month weekday</p>
        </div>
      )}

      {/* Next occurrence */}
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
      {isCustom && selected && (
        <p className="mt-1 text-[10px] text-muted-foreground/70">
          Cron: {selected.replace('cron:', '')}
        </p>
      )}
    </div>
  );
}
