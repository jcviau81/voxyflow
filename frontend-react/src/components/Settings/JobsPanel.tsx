/**
 * JobsPanel — Scheduled jobs scheduler UI.
 *
 * Features:
 *  - List scheduled jobs with rich details (type descriptions, payload summaries)
 *  - Toggle enabled/disabled per job
 *  - Run job now / Delete job
 *  - Create/Edit with type-specific payload configuration
 *  - Schedule presets + cron validation
 */

import { useState, useCallback, useMemo } from 'react';
import {
  Clock, Play, Trash2, Plus, Loader2, X, Pencil,
  Bell, GitBranch, Database, LayoutGrid, Cog, Bot, Square,
  ChevronDown, ChevronUp, Calendar, Info, Eye, EyeOff,
  HeartPulse, RefreshCw, FileX, HardDrive,
} from 'lucide-react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { useToastStore } from '../../stores/useToastStore';
import { cn } from '../../lib/utils';

// ── Types ──────────────────────────────────────────────────────────────────

interface Job {
  id: string;
  name: string;
  type: 'reminder' | 'github_sync' | 'rag_index' | 'custom' | 'board_run' | 'execute_board' | 'execute_card' | 'agent_task' | 'heartbeat' | 'recurrence' | 'session_cleanup' | 'chromadb_backup';
  schedule: string;
  enabled: boolean;
  payload: Record<string, unknown>;
  last_run?: string;
  next_run?: string;
}

type JobType = Job['type'];

interface SimpleProject {
  id: string;
  name: string;
}

// ── Job type metadata ─────────────────────────────────────────────────────

// Job types shown in the create/edit type selector (ordered)
const JOB_TYPE_CREATE_ORDER: JobType[] = [
  'agent_task', 'execute_card', 'execute_board',
  'reminder', 'rag_index', 'github_sync', 'custom',
];

const JOB_TYPE_META: Record<JobType, {
  label: string;
  description: string;
  icon: typeof Clock;
  color: string;
}> = {
  agent_task: {
    label: 'Agent Task',
    description: 'Send a freeform instruction to the AI agent',
    icon: Bot,
    color: 'text-cyan-400',
  },
  execute_card: {
    label: 'Execute Card',
    description: 'Run a specific card through the AI pipeline',
    icon: Square,
    color: 'text-indigo-400',
  },
  execute_board: {
    label: 'Execute Board',
    description: 'Execute all matching cards from a project board',
    icon: LayoutGrid,
    color: 'text-blue-400',
  },
  board_run: {
    label: 'Execute Board',
    description: 'Execute all matching cards from a project board',
    icon: LayoutGrid,
    color: 'text-blue-400',
  },
  reminder: {
    label: 'Reminder',
    description: 'Send a notification with a custom message',
    icon: Bell,
    color: 'text-amber-400',
  },
  rag_index: {
    label: 'RAG Index',
    description: 'Re-index project documents in the vector store',
    icon: Database,
    color: 'text-emerald-400',
  },
  github_sync: {
    label: 'GitHub Sync',
    description: 'Synchronize with a GitHub repository',
    icon: GitBranch,
    color: 'text-purple-400',
  },
  heartbeat: {
    label: 'Heartbeat',
    description: 'System health checks (backend, ChromaDB, XTTS, resources)',
    icon: HeartPulse,
    color: 'text-rose-400',
  },
  recurrence: {
    label: 'Recurrence',
    description: 'Generate recurring cards based on card schedules',
    icon: RefreshCw,
    color: 'text-teal-400',
  },
  session_cleanup: {
    label: 'Session Cleanup',
    description: 'Remove stale session files older than 30 days',
    icon: FileX,
    color: 'text-orange-400',
  },
  chromadb_backup: {
    label: 'ChromaDB Backup',
    description: 'Daily backup of all ChromaDB collections',
    icon: HardDrive,
    color: 'text-slate-400',
  },
  custom: {
    label: 'Custom',
    description: 'Custom job with user-defined behavior',
    icon: Cog,
    color: 'text-muted-foreground',
  },
};

const BOARD_STATUSES = ['todo', 'in_progress', 'review', 'done', 'card'] as const;

const BOARD_STATUS_LABELS: Record<string, string> = {
  todo: 'To Do',
  in_progress: 'In Progress',
  review: 'Review',
  done: 'Done',
  card: 'Backlog',
};

// ── Schedule presets ──────────────────────────────────────────────────────

const SCHEDULE_PRESETS: { value: string; label: string }[] = [
  { value: 'every_30min', label: 'Every 30 minutes' },
  { value: 'every_hour', label: 'Every hour' },
  { value: 'every_2h', label: 'Every 2 hours' },
  { value: 'every_day', label: 'Every day (midnight)' },
  { value: '0 9 * * 1-5', label: 'Weekdays at 9 AM' },
  { value: '0 9 * * *', label: 'Daily at 9 AM' },
  { value: '0 */6 * * *', label: 'Every 6 hours' },
  { value: '0 0 * * 0', label: 'Weekly (Sunday midnight)' },
];

// ── Cron validator ────────────────────────────────────────────────────────

function validateCronOrShorthand(expr: string): { valid: boolean; description: string } {
  const shorthands: Record<string, string> = {
    'every_30min': 'Every 30 minutes',
    'every_60min': 'Every 60 minutes',
    'every_hour': 'Every hour',
    'every_2h': 'Every 2 hours',
    'every_day': 'Every day at midnight',
  };
  // Match dynamic shorthands like every_15min, every_4h
  const minMatch = expr.match(/^every_(\d+)min$/);
  if (minMatch) return { valid: true, description: `Every ${minMatch[1]} minutes` };
  const hrMatch = expr.match(/^every_(\d+)h$/);
  if (hrMatch) return { valid: true, description: `Every ${hrMatch[1]} hours` };

  if (shorthands[expr]) return { valid: true, description: shorthands[expr] };

  const parts = expr.trim().split(/\s+/);
  if (parts.length !== 5) return { valid: false, description: 'Expected 5 fields: min hour dom month dow' };

  const cronFieldPattern = /^[\d,\-\*\/]+$/;
  for (const part of parts) {
    if (!cronFieldPattern.test(part)) return { valid: false, description: `Invalid field: "${part}"` };
  }

  return { valid: true, description: describeCron(parts) };
}

/** Best-effort human-readable description for a 5-field cron expression. */
function describeCron(parts: string[]): string {
  const [min, hour, dom, mon, dow] = parts;
  const pieces: string[] = [];

  // Time
  if (min === '0' && hour !== '*') {
    if (hour.includes('/')) {
      pieces.push(`Every ${hour.split('/')[1]} hours`);
    } else {
      pieces.push(`At ${hour.padStart(2, '0')}:00`);
    }
  } else if (min.includes('/')) {
    pieces.push(`Every ${min.split('/')[1]} minutes`);
  } else if (hour === '*' && min === '*') {
    pieces.push('Every minute');
  } else if (hour === '*') {
    pieces.push(`At minute ${min} of every hour`);
  } else {
    pieces.push(`At ${hour.padStart(2, '0')}:${min.padStart(2, '0')}`);
  }

  // Day of week
  const dowMap: Record<string, string> = {
    '0': 'Sun', '1': 'Mon', '2': 'Tue', '3': 'Wed',
    '4': 'Thu', '5': 'Fri', '6': 'Sat', '7': 'Sun',
    '1-5': 'weekdays', '0,6': 'weekends',
  };
  if (dow !== '*') {
    pieces.push(dowMap[dow] ? `on ${dowMap[dow]}` : `(dow: ${dow})`);
  }

  // Day of month
  if (dom !== '*') {
    pieces.push(`on day ${dom}`);
  }

  // Month
  if (mon !== '*') {
    pieces.push(`in month ${mon}`);
  }

  return pieces.join(' ') || `Cron: ${parts.join(' ')}`;
}

// ── API helpers ─────────────────────────────────────────────────────────────

async function fetchJobs(): Promise<Job[]> {
  const res = await fetch('/api/jobs');
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  const data = await res.json();
  return Array.isArray(data) ? data : (data.jobs ?? []);
}

async function createJob(job: Partial<Job>): Promise<Job> {
  const res = await fetch('/api/jobs', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(job),
  });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.json();
}

async function updateJob(id: string, patch: Partial<Job>): Promise<Job> {
  const res = await fetch(`/api/jobs/${id}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(patch),
  });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.json();
}

async function deleteJob(id: string): Promise<void> {
  const res = await fetch(`/api/jobs/${id}`, { method: 'DELETE' });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
}

async function runJob(id: string): Promise<void> {
  const res = await fetch(`/api/jobs/${id}/run`, { method: 'POST' });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
}

async function fetchProjects(): Promise<SimpleProject[]> {
  const res = await fetch('/api/projects?archived=false');
  if (!res.ok) return [];
  const data = await res.json();
  return (Array.isArray(data) ? data : [])
    .filter((p: Record<string, unknown>) => p.status !== 'archived')
    .map((p: Record<string, unknown>) => ({
      id: p.id as string,
      name: ((p.title ?? p.name) ?? 'Untitled') as string,
    }));
}

// ── Payload summary helper ────────────────────────────────────────────────

function getPayloadSummary(
  job: Job,
  projectsMap: Map<string, string>,
): string | null {
  const p = job.payload;
  switch (job.type) {
    case 'board_run':
    case 'execute_board': {
      const projName = p.project_id ? (projectsMap.get(p.project_id as string) ?? 'Unknown project') : 'No project';
      const statuses = Array.isArray(p.statuses) ? p.statuses.join(', ') : 'todo';
      return `${projName} — statuses: ${statuses}`;
    }
    case 'execute_card': {
      const projName = p.project_id ? (projectsMap.get(p.project_id as string) ?? 'Unknown') : '';
      const cardLabel = p.card_title ? (p.card_title as string) : (p.card_id ? `Card ${(p.card_id as string).slice(0, 8)}…` : 'No card');
      return projName ? `${projName} — ${cardLabel}` : cardLabel;
    }
    case 'agent_task': {
      const instr = ((p.instruction ?? p.instructions) as string | undefined) ?? '';
      if (!instr) return null;
      return instr.length > 80 ? instr.slice(0, 77) + '…' : instr;
    }
    case 'reminder': {
      const msg = p.message as string | undefined;
      return msg ? `"${msg.length > 60 ? msg.slice(0, 57) + '…' : msg}"` : null;
    }
    case 'rag_index': {
      const projName = p.project_id ? (projectsMap.get(p.project_id as string) ?? 'Unknown project') : 'All active projects';
      return projName;
    }
    case 'github_sync': {
      return p.repo ? `Repo: ${p.repo}` : null;
    }
    default:
      return null;
  }
}

// ── Relative time helper ──────────────────────────────────────────────────

function relativeTime(iso: string): string {
  const diff = Date.now() - new Date(iso).getTime();
  const absDiff = Math.abs(diff);
  const future = diff < 0;
  const seconds = Math.floor(absDiff / 1000);
  const minutes = Math.floor(seconds / 60);
  const hours = Math.floor(minutes / 60);
  const days = Math.floor(hours / 24);

  let text: string;
  if (seconds < 60) text = 'just now';
  else if (minutes < 60) text = `${minutes}m`;
  else if (hours < 24) text = `${hours}h`;
  else text = `${days}d`;

  if (text === 'just now') return text;
  return future ? `in ${text}` : `${text} ago`;
}

// ── Schedule input with presets ───────────────────────────────────────────

function ScheduleInput({ value, onChange, error, description }: {
  value: string;
  onChange: (v: string) => void;
  error: string;
  description: string;
}) {
  const [showPresets, setShowPresets] = useState(false);

  return (
    <div className="space-y-1">
      <div className="flex gap-1.5">
        <input
          type="text"
          value={value}
          onChange={(e) => onChange(e.target.value)}
          placeholder="0 9 * * 1-5"
          className={cn(
            "h-8 flex-1 px-2.5 text-sm rounded-md border bg-background font-mono",
            error ? "border-red-400" : description ? "border-emerald-400/50" : "border-input"
          )}
        />
        <button
          type="button"
          onClick={() => setShowPresets(!showPresets)}
          className={cn(
            "h-8 px-2 text-xs rounded-md border border-input hover:bg-accent transition-colors flex items-center gap-1",
            showPresets && "bg-accent"
          )}
        >
          <Calendar size={12} />
          Presets
          {showPresets ? <ChevronUp size={10} /> : <ChevronDown size={10} />}
        </button>
      </div>

      {showPresets && (
        <div className="grid grid-cols-2 gap-1 p-2 rounded-md border border-border bg-muted/30">
          {SCHEDULE_PRESETS.map((preset) => (
            <button
              key={preset.value}
              type="button"
              onClick={() => { onChange(preset.value); setShowPresets(false); }}
              className={cn(
                "text-left text-xs px-2 py-1.5 rounded hover:bg-accent transition-colors",
                value === preset.value && "bg-accent font-medium"
              )}
            >
              <span className="block font-mono text-[10px] text-muted-foreground">{preset.value}</span>
              <span>{preset.label}</span>
            </button>
          ))}
        </div>
      )}

      {description && (
        <div className="text-emerald-400 text-[11px] flex items-center gap-1">
          <Clock size={10} />
          {description}
        </div>
      )}
      {error && (
        <div className="text-red-400 text-[11px]">{error}</div>
      )}
      {!description && !error && (
        <div className="text-[11px] text-muted-foreground">
          Standard cron (min hour dom mon dow) or shorthand: every_30min, every_2h, every_day
        </div>
      )}
    </div>
  );
}

// ── Type-specific payload forms ───────────────────────────────────────────

function BoardRunPayload({ payload, onChange, projects }: {
  payload: Record<string, unknown>;
  onChange: (p: Record<string, unknown>) => void;
  projects: SimpleProject[];
}) {
  const selectedStatuses = (payload.statuses as string[] | undefined) ?? ['todo'];

  const toggleStatus = (status: string) => {
    const current = new Set(selectedStatuses);
    if (current.has(status)) {
      current.delete(status);
    } else {
      current.add(status);
    }
    onChange({ ...payload, statuses: Array.from(current) });
  };

  return (
    <div className="space-y-3">
      <div>
        <label className="text-xs font-medium text-muted-foreground mb-1 block">Project</label>
        <select
          value={(payload.project_id as string) ?? ''}
          onChange={(e) => onChange({ ...payload, project_id: e.target.value || undefined })}
          className="h-8 w-full px-2 text-sm rounded-md border border-input bg-background"
        >
          <option value="">Select a project…</option>
          {projects.map((p) => (
            <option key={p.id} value={p.id}>{p.name}</option>
          ))}
        </select>
        {!payload.project_id && (
          <p className="text-[11px] text-amber-400 mt-1">A project is required for board runs</p>
        )}
      </div>

      <div>
        <label className="text-xs font-medium text-muted-foreground mb-1.5 block">Card statuses to execute</label>
        <div className="flex flex-wrap gap-1.5">
          {BOARD_STATUSES.map((status) => (
            <button
              key={status}
              type="button"
              onClick={() => toggleStatus(status)}
              className={cn(
                "text-xs px-2.5 py-1 rounded-full border transition-colors",
                selectedStatuses.includes(status)
                  ? "bg-primary/15 border-primary/40 text-primary font-medium"
                  : "border-border text-muted-foreground hover:border-primary/30 hover:text-foreground"
              )}
            >
              {BOARD_STATUS_LABELS[status] ?? status}
            </button>
          ))}
        </div>
      </div>
    </div>
  );
}

function ReminderPayload({ payload, onChange }: {
  payload: Record<string, unknown>;
  onChange: (p: Record<string, unknown>) => void;
}) {
  return (
    <div>
      <label className="text-xs font-medium text-muted-foreground mb-1 block">Message</label>
      <textarea
        value={(payload.message as string) ?? ''}
        onChange={(e) => onChange({ ...payload, message: e.target.value || undefined })}
        placeholder="Time for the daily standup!"
        rows={2}
        className="w-full px-2.5 py-1.5 text-sm rounded-md border border-input bg-background resize-none"
      />
      <p className="text-[11px] text-muted-foreground mt-0.5">
        If empty, the job name is used as the message
      </p>
    </div>
  );
}

function RagIndexPayload({ payload, onChange, projects }: {
  payload: Record<string, unknown>;
  onChange: (p: Record<string, unknown>) => void;
  projects: SimpleProject[];
}) {
  return (
    <div>
      <label className="text-xs font-medium text-muted-foreground mb-1 block">Project (optional)</label>
      <select
        value={(payload.project_id as string) ?? ''}
        onChange={(e) => onChange({ ...payload, project_id: e.target.value || undefined })}
        className="h-8 w-full px-2 text-sm rounded-md border border-input bg-background"
      >
        <option value="">All active projects</option>
        {projects.map((p) => (
          <option key={p.id} value={p.id}>{p.name}</option>
        ))}
      </select>
    </div>
  );
}

function GithubSyncPayload({ payload, onChange }: {
  payload: Record<string, unknown>;
  onChange: (p: Record<string, unknown>) => void;
}) {
  return (
    <div>
      <label className="text-xs font-medium text-muted-foreground mb-1 block">Repository</label>
      <input
        type="text"
        value={(payload.repo as string) ?? ''}
        onChange={(e) => onChange({ ...payload, repo: e.target.value || undefined })}
        placeholder="owner/repo"
        className="h-8 w-full px-2.5 text-sm rounded-md border border-input bg-background font-mono"
      />
    </div>
  );
}

function AgentTaskPayload({ payload, onChange, projects }: {
  payload: Record<string, unknown>;
  onChange: (p: Record<string, unknown>) => void;
  projects: SimpleProject[];
}) {
  return (
    <div className="space-y-3">
      <div>
        <label className="text-xs font-medium text-muted-foreground mb-1 block">Instruction</label>
        <textarea
          value={(payload.instruction as string) ?? ''}
          onChange={(e) => onChange({ ...payload, instruction: e.target.value || undefined })}
          placeholder="Describe what the agent should do…"
          rows={5}
          className="w-full px-2.5 py-1.5 text-sm rounded-md border border-input bg-background resize-y font-mono"
        />
        {!payload.instruction && (
          <p className="text-[11px] text-amber-400 mt-1">An instruction is required for agent tasks</p>
        )}
      </div>
      <div>
        <label className="text-xs font-medium text-muted-foreground mb-1 block">Project scope (optional)</label>
        <select
          value={(payload.project_id as string) ?? ''}
          onChange={(e) => onChange({ ...payload, project_id: e.target.value || undefined })}
          className="h-8 w-full px-2 text-sm rounded-md border border-input bg-background"
        >
          <option value="">No project (general context)</option>
          {projects.map((p) => (
            <option key={p.id} value={p.id}>{p.name}</option>
          ))}
        </select>
        <p className="text-[11px] text-muted-foreground mt-0.5">
          Selecting a project gives the agent access to project context and memories
        </p>
      </div>
    </div>
  );
}

function ExecuteCardPayload({ payload, onChange, projects }: {
  payload: Record<string, unknown>;
  onChange: (p: Record<string, unknown>) => void;
  projects: SimpleProject[];
}) {
  const [cards, setCards] = useState<{ id: string; title: string }[]>([]);
  const [loadingCards, setLoadingCards] = useState(false);
  const selectedProjectId = (payload.project_id as string) ?? '';

  // Fetch cards when project changes
  const fetchCards = useCallback(async (projectId: string) => {
    if (!projectId) { setCards([]); return; }
    setLoadingCards(true);
    try {
      const res = await fetch(`/api/projects/${projectId}/cards`);
      if (!res.ok) { setCards([]); return; }
      const data = await res.json();
      const list = (Array.isArray(data) ? data : [])
        .filter((c: Record<string, unknown>) => c.status !== 'done' && c.status !== 'archived')
        .map((c: Record<string, unknown>) => ({ id: c.id as string, title: (c.title ?? 'Untitled') as string }));
      setCards(list);
    } catch { setCards([]); }
    finally { setLoadingCards(false); }
  }, []);

  // Re-fetch when project changes
  useState(() => { if (selectedProjectId) fetchCards(selectedProjectId); });

  return (
    <div className="space-y-3">
      <div>
        <label className="text-xs font-medium text-muted-foreground mb-1 block">Project</label>
        <select
          value={selectedProjectId}
          onChange={(e) => {
            const pid = e.target.value || undefined;
            onChange({ ...payload, project_id: pid, card_id: undefined, card_title: undefined });
            if (pid) fetchCards(pid);
            else setCards([]);
          }}
          className="h-8 w-full px-2 text-sm rounded-md border border-input bg-background"
        >
          <option value="">Select a project…</option>
          {projects.map((p) => (
            <option key={p.id} value={p.id}>{p.name}</option>
          ))}
        </select>
      </div>
      <div>
        <label className="text-xs font-medium text-muted-foreground mb-1 block">Card</label>
        {loadingCards ? (
          <div className="flex items-center gap-2 text-xs text-muted-foreground py-1">
            <Loader2 size={12} className="animate-spin" /> Loading cards…
          </div>
        ) : (
          <select
            value={(payload.card_id as string) ?? ''}
            onChange={(e) => {
              const cid = e.target.value || undefined;
              const card = cards.find(c => c.id === cid);
              onChange({ ...payload, card_id: cid, card_title: card?.title });
            }}
            className="h-8 w-full px-2 text-sm rounded-md border border-input bg-background"
            disabled={!selectedProjectId}
          >
            <option value="">{selectedProjectId ? 'Select a card…' : 'Select a project first'}</option>
            {cards.map((c) => (
              <option key={c.id} value={c.id}>{c.title}</option>
            ))}
          </select>
        )}
        {selectedProjectId && !payload.card_id && (
          <p className="text-[11px] text-amber-400 mt-1">A card is required</p>
        )}
      </div>
    </div>
  );
}

function PayloadEditor({ type, payload, onChange, projects }: {
  type: JobType;
  payload: Record<string, unknown>;
  onChange: (p: Record<string, unknown>) => void;
  projects: SimpleProject[];
}) {
  switch (type) {
    case 'board_run':
    case 'execute_board':
      return <BoardRunPayload payload={payload} onChange={onChange} projects={projects} />;
    case 'execute_card':
      return <ExecuteCardPayload payload={payload} onChange={onChange} projects={projects} />;
    case 'agent_task':
      return <AgentTaskPayload payload={payload} onChange={onChange} projects={projects} />;
    case 'reminder':
      return <ReminderPayload payload={payload} onChange={onChange} />;
    case 'rag_index':
      return <RagIndexPayload payload={payload} onChange={onChange} projects={projects} />;
    case 'github_sync':
      return <GithubSyncPayload payload={payload} onChange={onChange} />;
    default:
      return null;
  }
}

// ── JobItem ────────────────────────────────────────────────────────────────

function JobItem({ job, projectsMap, onToggle, onRun, onDelete, onEdit }: {
  job: Job;
  projectsMap: Map<string, string>;
  onToggle: (id: string, enabled: boolean) => void;
  onRun: (id: string) => void;
  onDelete: (id: string, name: string) => void;
  onEdit: (job: Job) => void;
}) {
  const [showPayload, setShowPayload] = useState(false);
  const meta = JOB_TYPE_META[job.type] ?? JOB_TYPE_META.custom;
  const Icon = meta.icon;
  const scheduleResult = validateCronOrShorthand(job.schedule);
  const payloadSummary = getPayloadSummary(job, projectsMap);
  const hasPayload = Object.keys(job.payload).length > 0;

  const lastRunText = job.last_run ? relativeTime(job.last_run) : 'never';
  const nextRunText = job.next_run && job.enabled ? relativeTime(job.next_run) : null;

  return (
    <div className={cn(
      "group rounded-lg border transition-colors",
      job.enabled
        ? "border-border/50 hover:border-border hover:bg-muted/30"
        : "border-border/30 bg-muted/10 opacity-60"
    )}>
      <div className="flex items-start gap-3 py-3 px-3.5">
        {/* Enable toggle */}
        <div className="pt-0.5">
          <input
            type="checkbox"
            checked={job.enabled}
            onChange={(e) => onToggle(job.id, e.target.checked)}
            className="h-4 w-4 rounded border-input accent-primary cursor-pointer"
            title={job.enabled ? 'Disable job' : 'Enable job'}
          />
        </div>

        {/* Type icon */}
        <div className={cn("pt-0.5 shrink-0", meta.color)}>
          <Icon size={16} />
        </div>

        {/* Main content */}
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2">
            <span className="text-sm font-medium truncate">{job.name}</span>
            <span className={cn("text-[10px] font-medium px-1.5 py-0.5 rounded", meta.color, "bg-muted")}>
              {meta.label}
            </span>
          </div>

          {/* Schedule description */}
          <div className="flex items-center gap-1.5 mt-1 text-xs text-muted-foreground">
            <Clock size={10} className="shrink-0" />
            <span>{scheduleResult.valid ? scheduleResult.description : job.schedule}</span>
            <span className="font-mono text-[10px] opacity-60">({job.schedule})</span>
          </div>

          {/* Payload summary */}
          {payloadSummary && (
            <div className="mt-1 text-xs text-muted-foreground/80 truncate">
              {payloadSummary}
            </div>
          )}

          {/* Timing info */}
          <div className="flex items-center gap-3 mt-1.5 text-[11px] text-muted-foreground/60">
            <span title={job.last_run ? new Date(job.last_run).toLocaleString() : undefined}>
              Last run: {lastRunText}
            </span>
            {nextRunText && (
              <span title={job.next_run ? new Date(job.next_run).toLocaleString() : undefined}>
                Next: {nextRunText}
              </span>
            )}
          </div>
        </div>

        {/* Actions */}
        <div className="flex items-center gap-0.5 shrink-0 opacity-0 group-hover:opacity-100 transition-opacity">
          {hasPayload && (
            <button
              type="button"
              onClick={() => setShowPayload(!showPayload)}
              title={showPayload ? 'Hide payload' : 'Show payload'}
              className={cn(
                "h-7 w-7 flex items-center justify-center rounded hover:bg-accent transition-colors",
                showPayload ? "text-foreground" : "text-muted-foreground hover:text-foreground"
              )}
            >
              {showPayload ? <EyeOff size={13} /> : <Eye size={13} />}
            </button>
          )}
          <button
            type="button"
            onClick={() => onEdit(job)}
            title="Edit job"
            className="h-7 w-7 flex items-center justify-center rounded hover:bg-accent transition-colors text-muted-foreground hover:text-foreground"
          >
            <Pencil size={13} />
          </button>
          <button
            type="button"
            onClick={() => onRun(job.id)}
            title="Run now"
            className="h-7 w-7 flex items-center justify-center rounded hover:bg-accent transition-colors text-muted-foreground hover:text-foreground"
          >
            <Play size={13} />
          </button>
          <button
            type="button"
            onClick={() => onDelete(job.id, job.name)}
            title="Delete job"
            className="h-7 w-7 flex items-center justify-center rounded hover:bg-destructive/10 transition-colors text-muted-foreground hover:text-destructive"
          >
            <Trash2 size={13} />
          </button>
        </div>
      </div>

      {/* Expandable payload */}
      {showPayload && hasPayload && (
        <div className="px-3.5 pb-3 pt-0">
          <pre className="text-[11px] font-mono text-muted-foreground bg-muted/40 rounded-md p-2.5 overflow-x-auto whitespace-pre-wrap break-words max-h-48 overflow-y-auto">
            {JSON.stringify(job.payload, null, 2)}
          </pre>
        </div>
      )}
    </div>
  );
}

// ── Job Form (shared Create/Edit) ─────────────────────────────────────────

function JobForm({ mode, initial, projects, onCancel, onSubmit }: {
  mode: 'create' | 'edit';
  initial: {
    name: string;
    type: JobType;
    schedule: string;
    enabled: boolean;
    payload: Record<string, unknown>;
  };
  projects: SimpleProject[];
  onCancel: () => void;
  onSubmit: (data: { name: string; type: JobType; schedule: string; enabled: boolean; payload: Record<string, unknown> }) => void;
}) {
  const [name, setName] = useState(initial.name);
  const [type, setType] = useState<JobType>(initial.type);
  const [schedule, setSchedule] = useState(initial.schedule);
  const [enabled, setEnabled] = useState(initial.enabled);
  const [payload, setPayload] = useState<Record<string, unknown>>(initial.payload);
  const [error, setError] = useState('');
  const [scheduleError, setScheduleError] = useState('');
  const [scheduleDesc, setScheduleDesc] = useState(() => {
    if (!initial.schedule) return '';
    const r = validateCronOrShorthand(initial.schedule);
    return r.valid ? r.description : '';
  });

  const handleScheduleChange = (value: string) => {
    setSchedule(value);
    if (!value.trim()) {
      setScheduleError('');
      setScheduleDesc('');
      return;
    }
    const result = validateCronOrShorthand(value);
    if (result.valid) {
      setScheduleError('');
      setScheduleDesc(result.description);
    } else {
      setScheduleError(result.description);
      setScheduleDesc('');
    }
  };

  const handleTypeChange = (newType: JobType) => {
    setType(newType);
    // Reset payload when switching types to avoid stale fields
    setPayload({});
  };

  const handleSubmit = () => {
    if (!name.trim()) { setError('Name is required'); return; }
    if (!schedule.trim()) { setError('Schedule is required'); return; }
    const result = validateCronOrShorthand(schedule);
    if (!result.valid) { setError(result.description); return; }
    if ((type === 'board_run' || type === 'execute_board') && !payload.project_id) { setError('Project is required for Execute Board jobs'); return; }
    if (type === 'execute_card' && !payload.card_id) { setError('Card is required for Execute Card jobs'); return; }
    if (type === 'agent_task' && !payload.instruction) { setError('Instruction is required for Agent Task jobs'); return; }
    setError('');
    onSubmit({ name: name.trim(), type, schedule: schedule.trim(), enabled, payload });
  };

  const meta = JOB_TYPE_META[type];

  return (
    <div className={cn(
      "rounded-lg border p-4 space-y-4",
      mode === 'edit' ? "border-primary/30 bg-muted/10" : "border-border bg-muted/10"
    )}>
      {/* Header */}
      <div className="flex items-center justify-between">
        <h4 className="text-sm font-semibold">
          {mode === 'create' ? 'New Scheduled Job' : 'Edit Job'}
        </h4>
        <button type="button" onClick={onCancel} className="text-muted-foreground hover:text-foreground transition-colors">
          <X size={14} />
        </button>
      </div>

      {/* Name */}
      <div>
        <label className="text-xs font-medium text-muted-foreground mb-1 block">Job Name</label>
        <input
          type="text"
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder="e.g. Daily board sweep, Morning standup reminder"
          className="h-8 w-full px-2.5 text-sm rounded-md border border-input bg-background"
          autoFocus={mode === 'create'}
        />
      </div>

      {/* Type selector */}
      <div>
        <label className="text-xs font-medium text-muted-foreground mb-1.5 block">Job Type</label>
        <div className="grid grid-cols-2 sm:grid-cols-3 gap-1.5">
          {JOB_TYPE_CREATE_ORDER.map((key) => {
            const m = JOB_TYPE_META[key];
            const TypeIcon = m.icon;
            return (
              <button
                key={key}
                type="button"
                onClick={() => handleTypeChange(key)}
                className={cn(
                  "flex items-center gap-2 px-3 py-2 rounded-md border text-left transition-colors text-xs",
                  type === key
                    ? "border-primary/50 bg-primary/10 font-medium"
                    : "border-border/50 hover:border-border hover:bg-muted/40"
                )}
              >
                <TypeIcon size={14} className={m.color} />
                <span>{m.label}</span>
              </button>
            );
          })}
        </div>
        <p className="text-[11px] text-muted-foreground mt-1.5 flex items-center gap-1">
          <Info size={10} />
          {meta.description}
        </p>
      </div>

      {/* Type-specific payload config */}
      <PayloadEditor type={type} payload={payload} onChange={setPayload} projects={projects} />

      {/* Schedule */}
      <div>
        <label className="text-xs font-medium text-muted-foreground mb-1 block">Schedule</label>
        <ScheduleInput
          value={schedule}
          onChange={handleScheduleChange}
          error={scheduleError}
          description={scheduleDesc}
        />
      </div>

      {/* Enabled */}
      <label className="flex items-center gap-2 cursor-pointer">
        <input
          type="checkbox"
          checked={enabled}
          onChange={(e) => setEnabled(e.target.checked)}
          className="h-4 w-4 rounded border-input accent-primary"
        />
        <span className="text-sm">Start enabled</span>
      </label>

      {/* Actions */}
      <div className="flex items-center gap-2 pt-1 border-t border-border/50">
        <button
          type="button"
          onClick={handleSubmit}
          className="h-8 px-4 text-xs font-medium rounded-md bg-primary text-primary-foreground hover:bg-primary/90 transition-colors"
        >
          {mode === 'create' ? 'Create Job' : 'Save Changes'}
        </button>
        <button
          type="button"
          onClick={onCancel}
          className="h-8 px-4 text-xs rounded-md hover:bg-accent transition-colors"
        >
          Cancel
        </button>
        {error && <span className="text-xs text-destructive">{error}</span>}
      </div>
    </div>
  );
}

// ── JobsPanel ──────────────────────────────────────────────────────────────

export function JobsPanel() {
  const { showToast } = useToastStore();
  const queryClient = useQueryClient();
  const [showForm, setShowForm] = useState(false);
  const [editingJob, setEditingJob] = useState<Job | null>(null);
  const [_runningIds, setRunningIds] = useState<Set<string>>(new Set());

  const { data: jobs = [], isLoading } = useQuery<Job[]>({
    queryKey: ['jobs'],
    queryFn: fetchJobs,
  });

  const { data: projects = [] } = useQuery<SimpleProject[]>({
    queryKey: ['projects', 'list', 'for-jobs'],
    queryFn: fetchProjects,
    staleTime: 60_000,
  });

  const projectsMap = useMemo(() => {
    const m = new Map<string, string>();
    for (const p of projects) m.set(p.id, p.name);
    return m;
  }, [projects]);

  const toggleMutation = useMutation({
    mutationFn: ({ id, enabled }: { id: string; enabled: boolean }) => updateJob(id, { enabled }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['jobs'] }),
    onError: (e) => showToast(`Failed to update job: ${e}`, 'error', 3000),
  });

  const deleteMutation = useMutation({
    mutationFn: (id: string) => deleteJob(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['jobs'] });
      showToast('Job deleted', 'info', 2000);
    },
    onError: (e) => showToast(`Failed to delete job: ${e}`, 'error', 3000),
  });

  const createMutation = useMutation({
    mutationFn: (data: { name: string; type: JobType; schedule: string; enabled: boolean; payload: Record<string, unknown> }) =>
      createJob(data),
    onSuccess: (job) => {
      queryClient.invalidateQueries({ queryKey: ['jobs'] });
      setShowForm(false);
      showToast(`Job "${job.name}" created`, 'success', 2000);
    },
    onError: (e) => showToast(`Failed to create job: ${e}`, 'error', 3000),
  });

  const editMutation = useMutation({
    mutationFn: ({ id, patch }: { id: string; patch: Partial<Job> }) => updateJob(id, patch),
    onSuccess: (job) => {
      queryClient.invalidateQueries({ queryKey: ['jobs'] });
      setEditingJob(null);
      showToast(`Job "${job.name}" updated`, 'success', 2000);
    },
    onError: (e) => showToast(`Failed to update job: ${e}`, 'error', 3000),
  });

  const handleRun = useCallback(async (id: string) => {
    setRunningIds((prev) => new Set(prev).add(id));
    try {
      await runJob(id);
      showToast('Job triggered!', 'success', 2000);
      queryClient.invalidateQueries({ queryKey: ['jobs'] });
    } catch (e) {
      showToast(`Failed to run job: ${e}`, 'error', 3000);
    } finally {
      setRunningIds((prev) => {
        const next = new Set(prev);
        next.delete(id);
        return next;
      });
    }
  }, [showToast, queryClient]);

  const handleDelete = useCallback((id: string, name: string) => {
    if (!window.confirm(`Delete job "${name}"?`)) return;
    deleteMutation.mutate(id);
  }, [deleteMutation]);

  return (
    <div className="settings-panel-content p-6 space-y-4 max-w-2xl" data-testid="settings-jobs">
      <div className="flex items-center justify-between">
        <h3 className="flex items-center gap-2 text-base font-semibold">
          <Clock size={16} />
          Scheduled Jobs
        </h3>
        {!showForm && !editingJob && (
          <button
            type="button"
            onClick={() => setShowForm(true)}
            className="flex items-center gap-1.5 h-8 px-3 text-sm rounded-md bg-primary text-primary-foreground hover:bg-primary/90 transition-colors"
          >
            <Plus size={14} />
            New Job
          </button>
        )}
      </div>

      {jobs.length > 0 && !isLoading && (
        <p className="text-xs text-muted-foreground">
          {jobs.length} job{jobs.length !== 1 ? 's' : ''} — {jobs.filter(j => j.enabled).length} active
        </p>
      )}

      {/* Create form (top position) */}
      {showForm && (
        <JobForm
          mode="create"
          initial={{ name: '', type: 'reminder', schedule: '', enabled: true, payload: {} }}
          projects={projects}
          onCancel={() => setShowForm(false)}
          onSubmit={(data) => createMutation.mutate(data)}
        />
      )}

      {isLoading ? (
        <div className="flex items-center gap-2 text-sm text-muted-foreground py-4">
          <Loader2 size={14} className="animate-spin" />
          Loading jobs…
        </div>
      ) : jobs.length === 0 && !showForm ? (
        <div className="text-center py-8 text-muted-foreground">
          <Clock size={32} className="mx-auto mb-2 opacity-30" />
          <p className="text-sm">No scheduled jobs yet</p>
          <p className="text-xs mt-1">Create a job to automate board runs, reminders, and more</p>
        </div>
      ) : (
        <div className="space-y-2">
          {jobs.map((job) =>
            editingJob?.id === job.id ? (
              <JobForm
                key={job.id}
                mode="edit"
                initial={{
                  name: job.name,
                  type: job.type,
                  schedule: job.schedule,
                  enabled: job.enabled,
                  payload: job.payload,
                }}
                projects={projects}
                onCancel={() => setEditingJob(null)}
                onSubmit={(data) => editMutation.mutate({ id: job.id, patch: data })}
              />
            ) : (
              <JobItem
                key={job.id}
                job={job}
                projectsMap={projectsMap}
                onToggle={(id, enabled) => toggleMutation.mutate({ id, enabled })}
                onRun={handleRun}
                onDelete={handleDelete}
                onEdit={(j) => { setEditingJob(j); setShowForm(false); }}
              />
            )
          )}
        </div>
      )}
    </div>
  );
}
