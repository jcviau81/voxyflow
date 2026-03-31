import { useState, useCallback } from 'react';
import { X } from 'lucide-react';

const AVATAR_COLORS = [
  '#e53935', '#8e24aa', '#1e88e5', '#00897b',
  '#43a047', '#fb8c00', '#f4511e', '#6d4c41',
];

function stringHash(s: string): number {
  let hash = 0;
  for (let i = 0; i < s.length; i++) {
    hash = (hash * 31 + s.charCodeAt(i)) >>> 0;
  }
  return hash;
}

function nameToColor(name: string): string {
  return AVATAR_COLORS[stringHash(name) % AVATAR_COLORS.length];
}

function getInitials(name: string): string {
  return name
    .split(/\s+/)
    .map((w) => w[0] ?? '')
    .join('')
    .toUpperCase()
    .slice(0, 2);
}

// ── Assignee chip ────────────────────────────────────────────────────────────

interface AssigneeProps {
  assignee: string | null | undefined;
  onChange: (assignee: string | null) => void;
}

function AssigneeField({ assignee, onChange }: AssigneeProps) {
  const [editing, setEditing] = useState(false);
  const [input, setInput] = useState('');

  const commit = useCallback(
    (name: string) => {
      const trimmed = name.trim();
      if (trimmed) onChange(trimmed);
      setEditing(false);
      setInput('');
    },
    [onChange],
  );

  if (assignee && !editing) {
    return (
      <div className="flex items-center gap-2">
        <span
          className="flex h-6 w-6 items-center justify-center rounded-full text-[10px] font-bold text-white"
          style={{ background: nameToColor(assignee) }}
        >
          {getInitials(assignee)}
        </span>
        <span className="text-sm">{assignee}</span>
        <button
          type="button"
          onClick={() => onChange(null)}
          className="text-muted-foreground hover:text-foreground"
          title="Clear assignee"
        >
          <X className="h-3.5 w-3.5" />
        </button>
      </div>
    );
  }

  return (
    <input
      type="text"
      autoFocus
      value={input}
      onChange={(e) => setInput(e.target.value)}
      onKeyDown={(e) => {
        if (e.key === 'Enter') commit(input);
        if (e.key === 'Escape') { setEditing(false); setInput(''); }
      }}
      onBlur={() => {
        if (input.trim()) commit(input);
        else setEditing(false);
      }}
      placeholder="Type name and press Enter..."
      className="w-full rounded border border-border bg-transparent px-2 py-1 text-xs outline-none focus:border-accent"
    />
  );
}

// ── Watchers chips ───────────────────────────────────────────────────────────

interface WatchersProps {
  watchers: string;
  onChange: (watchers: string) => void;
}

function WatchersField({ watchers, onChange }: WatchersProps) {
  const [input, setInput] = useState('');
  const list = watchers
    .split(',')
    .map((w) => w.trim())
    .filter(Boolean);

  const remove = useCallback(
    (name: string) => {
      const next = list.filter((w) => w !== name).join(',');
      onChange(next);
    },
    [list, onChange],
  );

  const add = useCallback(
    (raw: string) => {
      const names = raw
        .split(',')
        .map((n) => n.trim())
        .filter((n) => n && !list.includes(n));
      if (names.length > 0) {
        onChange([...list, ...names].join(','));
      }
      setInput('');
    },
    [list, onChange],
  );

  return (
    <div className="flex flex-wrap items-center gap-1.5">
      {list.map((w) => (
        <span
          key={w}
          className="inline-flex items-center gap-1 rounded-full bg-muted px-2 py-0.5 text-xs"
        >
          {w}
          <button
            type="button"
            onClick={() => remove(w)}
            title={`Remove ${w}`}
            className="hover:text-foreground"
          >
            <X className="h-3 w-3" />
          </button>
        </span>
      ))}
      <input
        type="text"
        value={input}
        onChange={(e) => setInput(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === 'Enter') { e.preventDefault(); add(input); }
          if (e.key === 'Escape') setInput('');
        }}
        onBlur={() => {
          if (input.trim()) add(input);
        }}
        placeholder="Add watcher..."
        className="min-w-[80px] flex-1 border-none bg-transparent text-xs outline-none placeholder:text-muted-foreground/50"
      />
    </div>
  );
}

// ── Combined section ─────────────────────────────────────────────────────────

interface AssigneeWatchersProps {
  assignee: string | null | undefined;
  watchers: string;
  onAssigneeChange: (assignee: string | null) => void;
  onWatchersChange: (watchers: string) => void;
}

export function AssigneeWatchers({
  assignee,
  watchers,
  onAssigneeChange,
  onWatchersChange,
}: AssigneeWatchersProps) {
  return (
    <div className="space-y-3">
      <div>
        <span className="mb-1 block text-xs font-medium text-muted-foreground">Assigned to</span>
        <AssigneeField assignee={assignee} onChange={onAssigneeChange} />
      </div>
      <div>
        <span className="mb-1 block text-xs font-medium text-muted-foreground">Watchers</span>
        <WatchersField watchers={watchers} onChange={onWatchersChange} />
      </div>
    </div>
  );
}
