import { useState } from 'react';
import { useTimeEntries, useLogTime, useDeleteTimeEntry } from '../../../hooks/api/useCards';

function formatMinutes(minutes: number): string {
  if (minutes <= 0) return '0m';
  const h = Math.floor(minutes / 60);
  const m = minutes % 60;
  if (h === 0) return `${m}m`;
  if (m === 0) return `${h}h`;
  return `${h}h ${m}m`;
}

export function TimeTracking({ cardId }: { cardId: string }) {
  const { data: entries = [], isLoading } = useTimeEntries(cardId);
  const logTime = useLogTime();
  const deleteEntry = useDeleteTimeEntry();
  const [showForm, setShowForm] = useState(false);
  const [minutes, setMinutes] = useState('');
  const [note, setNote] = useState('');

  const total = entries.reduce((sum, e) => sum + e.durationMinutes, 0);

  const handleSubmit = () => {
    const mins = parseInt(minutes, 10);
    if (!mins || mins < 1) return;
    logTime.mutate(
      { cardId, durationMinutes: mins, note: note.trim() || undefined },
      {
        onSuccess: () => {
          setMinutes('');
          setNote('');
          setShowForm(false);
        },
      },
    );
  };

  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between">
        <label className="text-xs font-medium text-muted-foreground">⏱ Time Tracking</label>
        <button
          type="button"
          onClick={() => setShowForm((v) => !v)}
          className="text-xs text-muted-foreground/60 hover:text-muted-foreground"
        >
          {showForm ? '− Cancel' : '+ Log Time'}
        </button>
      </div>

      <p className="text-[11px] text-muted-foreground/60">
        {total > 0 ? `⏱ ${formatMinutes(total)} total` : '⏱ No time logged yet'}
      </p>

      {showForm && (
        <div className="flex gap-1.5">
          <input
            type="number"
            value={minutes}
            onChange={(e) => setMinutes(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter') handleSubmit();
              if (e.key === 'Escape') setShowForm(false);
            }}
            placeholder="mins"
            min="1"
            className="w-16 rounded border border-border bg-transparent px-2 py-1 text-xs outline-none focus:border-accent"
          />
          <input
            type="text"
            value={note}
            onChange={(e) => setNote(e.target.value)}
            onKeyDown={(e) => { if (e.key === 'Enter') handleSubmit(); }}
            placeholder="Note (optional)"
            className="flex-1 rounded border border-border bg-transparent px-2 py-1 text-xs outline-none focus:border-accent"
          />
          <button
            type="button"
            onClick={handleSubmit}
            disabled={logTime.isPending}
            className="rounded border border-border px-2 py-1 text-xs hover:bg-muted disabled:opacity-40"
          >
            Log
          </button>
        </div>
      )}

      {isLoading ? (
        <p className="text-[10px] text-muted-foreground/40">Loading…</p>
      ) : entries.length === 0 ? (
        <p className="text-[10px] text-muted-foreground/40">No entries yet.</p>
      ) : (
        <div className="space-y-1">
          {entries.map((entry) => (
            <div key={entry.id} className="flex items-center gap-2 text-[11px]">
              <span className="font-medium text-foreground">{formatMinutes(entry.durationMinutes)}</span>
              <span className="text-muted-foreground/60">
                {new Date(entry.loggedAt).toLocaleDateString(undefined, {
                  month: 'short',
                  day: 'numeric',
                })}
              </span>
              {entry.note && (
                <span className="flex-1 truncate text-muted-foreground/80">{entry.note}</span>
              )}
              <button
                type="button"
                onClick={() => deleteEntry.mutate({ cardId, entryId: entry.id })}
                disabled={deleteEntry.isPending}
                className="ml-auto text-muted-foreground/40 hover:text-muted-foreground"
                title="Delete entry"
              >
                ×
              </button>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
