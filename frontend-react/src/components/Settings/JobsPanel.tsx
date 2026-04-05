/**
 * JobsPanel — Scheduled jobs scheduler UI.
 *
 * Mirrors renderJobsSection() + renderJobItem() + renderAddJobForm() + all job event handlers
 * from frontend/src/components/Settings/SettingsPage.ts (lines 1135–1367).
 *
 * Features:
 *  - List scheduled jobs (GET /api/jobs)
 *  - Toggle enabled/disabled per job
 *  - Run job now
 *  - Delete job (with confirmation)
 *  - Add job form (name, type, schedule, enabled)
 */

import { useState, useCallback } from 'react';
import { Clock, Play, Trash2, Plus, Loader2, X } from 'lucide-react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { useToastStore } from '../../stores/useToastStore';
import { cn } from '../../lib/utils';

// ── Types ──────────────────────────────────────────────────────────────────

interface Job {
  id: string;
  name: string;
  type: 'reminder' | 'github_sync' | 'rag_index' | 'custom';
  schedule: string;
  enabled: boolean;
  payload: Record<string, unknown>;
  last_run?: string;
  next_run?: string;
}

type JobType = Job['type'];

interface NewJobForm {
  name: string;
  type: JobType;
  schedule: string;
  enabled: boolean;
}

// ── Cron validator ────────────────────────────────────────────────────────

function validateCronOrShorthand(expr: string): { valid: boolean; description: string } {
  const shorthands: Record<string, string> = {
    'every_30min': 'Every 30 minutes',
    'every_hour': 'Every hour',
    'every_2h': 'Every 2 hours',
    'every_day': 'Every day at midnight',
  };
  if (shorthands[expr]) return { valid: true, description: shorthands[expr] };

  const parts = expr.trim().split(/\s+/);
  if (parts.length !== 5) return { valid: false, description: 'Expected 5 fields: min hour dom month dow' };

  const cronFieldPattern = /^[\d,\-\*\/]+$/;
  for (const part of parts) {
    if (!cronFieldPattern.test(part)) return { valid: false, description: `Invalid field: "${part}"` };
  }

  return { valid: true, description: `Cron: ${expr}` };
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

// ── JobItem ────────────────────────────────────────────────────────────────

function JobItem({ job, onToggle, onRun, onDelete }: {
  job: Job;
  onToggle: (id: string, enabled: boolean) => void;
  onRun: (id: string) => void;
  onDelete: (id: string, name: string) => void;
}) {
  const lastRunText = job.last_run
    ? `Last: ${new Date(job.last_run).toLocaleString()}`
    : 'Never run';

  const nextRunText = job.next_run && job.enabled
    ? `Next: ${new Date(job.next_run).toLocaleString()}`
    : null;

  return (
    <div className="job-item flex items-center gap-3 py-2.5 px-3 rounded-md hover:bg-muted/40 border border-transparent hover:border-border transition-colors">
      <input
        type="checkbox"
        checked={job.enabled}
        onChange={(e) => onToggle(job.id, e.target.checked)}
        className="h-4 w-4 rounded border-input accent-primary cursor-pointer"
        title="Enable/disable"
      />
      <div className="flex-1 min-w-0">
        <div className="text-sm font-medium truncate">{job.name}</div>
        <div className="flex items-center gap-2 mt-0.5">
          <span className="text-xs text-muted-foreground bg-muted px-1.5 py-0.5 rounded">
            {job.type}
          </span>
          <span className="text-xs font-mono text-muted-foreground">{job.schedule}</span>
          <span className="text-xs text-muted-foreground">{lastRunText}</span>
        </div>
        {nextRunText && (
          <div className="text-xs text-muted-foreground mt-0.5">{nextRunText}</div>
        )}
      </div>
      <div className="flex items-center gap-1 shrink-0">
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
          title="Delete"
          className="h-7 w-7 flex items-center justify-center rounded hover:bg-destructive/10 transition-colors text-muted-foreground hover:text-destructive"
        >
          <Trash2 size={13} />
        </button>
      </div>
    </div>
  );
}

// ── AddJobForm ─────────────────────────────────────────────────────────────

function AddJobForm({ onCancel, onSubmit }: {
  onCancel: () => void;
  onSubmit: (data: NewJobForm) => void;
}) {
  const [form, setForm] = useState<NewJobForm>({
    name: '',
    type: 'reminder',
    schedule: '',
    enabled: true,
  });
  const [error, setError] = useState('');
  const [scheduleError, setScheduleError] = useState('');
  const [scheduleDesc, setScheduleDesc] = useState('');

  const validateSchedule = (value: string) => {
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

  const handleScheduleChange = (value: string) => {
    setForm((f) => ({ ...f, schedule: value }));
    validateSchedule(value);
  };

  const handleSubmit = () => {
    if (!form.name.trim()) { setError('Name is required'); return; }
    if (!form.schedule.trim()) { setError('Schedule is required'); return; }
    const result = validateCronOrShorthand(form.schedule);
    if (!result.valid) { setError(result.description); return; }
    setError('');
    onSubmit(form);
  };

  return (
    <div className="job-add-form rounded-md border border-border bg-muted/20 p-4 space-y-3 mt-3">
      <div className="flex items-center justify-between">
        <div className="text-sm font-medium">New Scheduled Job</div>
        <button type="button" onClick={onCancel} className="text-muted-foreground hover:text-foreground">
          <X size={14} />
        </button>
      </div>

      <div className="grid grid-cols-[auto_1fr] items-center gap-x-4 gap-y-2.5 text-sm">
        <label className="text-muted-foreground text-right">Name</label>
        <input
          type="text"
          value={form.name}
          onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))}
          placeholder="Daily standup reminder"
          className="h-7 px-2.5 text-sm rounded-md border border-input bg-background"
        />

        <label className="text-muted-foreground text-right">Type</label>
        <select
          value={form.type}
          onChange={(e) => setForm((f) => ({ ...f, type: e.target.value as JobType }))}
          className="h-7 px-2 text-sm rounded-md border border-input bg-background"
        >
          <option value="reminder">reminder</option>
          <option value="github_sync">github_sync</option>
          <option value="rag_index">rag_index</option>
          <option value="custom">custom</option>
        </select>

        <label className="text-muted-foreground text-right">Schedule</label>
        <div className="space-y-0.5">
          <input
            type="text"
            value={form.schedule}
            onChange={(e) => handleScheduleChange(e.target.value)}
            onBlur={() => validateSchedule(form.schedule)}
            placeholder="0 9 * * 1-5"
            className={cn(
              "h-7 w-full px-2.5 text-sm rounded-md border bg-background",
              scheduleError ? "border-red-400" : scheduleDesc ? "border-emerald-400" : "border-input"
            )}
          />
          {scheduleDesc && (
            <div className="text-emerald-400 text-[11px]">{scheduleDesc}</div>
          )}
          {scheduleError && (
            <div className="text-red-400 text-[11px]">{scheduleError}</div>
          )}
          {!scheduleDesc && !scheduleError && (
            <div className="text-xs text-muted-foreground">
              Cron or: every_30min, every_hour, every_day
            </div>
          )}
        </div>

        <label className="text-muted-foreground text-right">Enabled</label>
        <input
          type="checkbox"
          checked={form.enabled}
          onChange={(e) => setForm((f) => ({ ...f, enabled: e.target.checked }))}
          className="h-4 w-4 rounded border-input accent-primary"
        />
      </div>

      <div className="flex items-center gap-2 pt-1">
        <button
          type="button"
          onClick={handleSubmit}
          className="btn-primary h-7 px-3 text-xs rounded-md bg-primary text-primary-foreground hover:bg-primary/90"
        >
          Create Job
        </button>
        <button
          type="button"
          onClick={onCancel}
          className="btn-ghost h-7 px-3 text-xs rounded-md hover:bg-accent"
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
  const [_runningIds, setRunningIds] = useState<Set<string>>(new Set());

  const { data: jobs = [], isLoading } = useQuery<Job[]>({
    queryKey: ['jobs'],
    queryFn: fetchJobs,
  });

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
    mutationFn: (data: NewJobForm) => createJob({ ...data, payload: {} }),
    onSuccess: (job) => {
      queryClient.invalidateQueries({ queryKey: ['jobs'] });
      setShowForm(false);
      showToast(`Job "${job.name}" created!`, 'success', 2000);
    },
    onError: (e) => showToast(`Failed to create job: ${e}`, 'error', 3000),
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
    <div className="settings-panel-content p-6 space-y-4" data-testid="settings-jobs">
      <h3 className="flex items-center gap-2 text-base font-semibold">
        <Clock size={16} />
        Scheduled Jobs
      </h3>

      {isLoading ? (
        <div className="flex items-center gap-2 text-sm text-muted-foreground py-2">
          <Loader2 size={14} className="animate-spin" />
          Loading jobs…
        </div>
      ) : jobs.length === 0 ? (
        <p className="text-sm text-muted-foreground py-2">
          No scheduled jobs. Add one to automate tasks.
        </p>
      ) : (
        <div className="space-y-1">
          {jobs.map((job) => (
            <JobItem
              key={job.id}
              job={job}
              onToggle={(id, enabled) => toggleMutation.mutate({ id, enabled })}
              onRun={handleRun}
              onDelete={handleDelete}
            />
          ))}
        </div>
      )}

      {showForm && (
        <AddJobForm
          onCancel={() => setShowForm(false)}
          onSubmit={(data) => createMutation.mutate(data)}
        />
      )}

      {!showForm && (
        <button
          type="button"
          onClick={() => setShowForm(true)}
          className="flex items-center gap-1.5 h-8 px-3 text-sm rounded-md border border-border hover:bg-accent transition-colors mt-2"
        >
          <Plus size={14} />
          Add Job
        </button>
      )}
    </div>
  );
}
