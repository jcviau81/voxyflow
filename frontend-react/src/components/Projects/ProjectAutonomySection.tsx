import { useEffect, useState } from 'react';
import { useToastStore } from '../../stores/useToastStore';
import {
  useDisableProjectAutonomy,
  useProjectAutonomy,
  useRunProjectAutonomyNow,
  useUpsertProjectAutonomy,
} from '../../hooks/api/useProjectAutonomy';

interface Props {
  projectId: string;
}

const SCHEDULE_OPTIONS = [
  { value: 'every_5min', label: 'Every 5 minutes' },
  { value: 'every_15min', label: 'Every 15 minutes' },
  { value: 'every_30min', label: 'Every 30 minutes' },
  { value: 'every_1h', label: 'Every hour' },
  { value: 'every_2h', label: 'Every 2 hours' },
  { value: 'every_day', label: 'Every day' },
];

export function ProjectAutonomySection({ projectId }: Props) {
  const { showToast } = useToastStore();
  const { data, isLoading } = useProjectAutonomy(projectId);
  const upsert = useUpsertProjectAutonomy();
  const disable = useDisableProjectAutonomy();
  const runNow = useRunProjectAutonomyNow();

  const [enabled, setEnabled] = useState(false);
  const [schedule, setSchedule] = useState('every_5min');
  const [directive, setDirective] = useState('');
  const [dirty, setDirty] = useState(false);

  useEffect(() => {
    if (!data) return;
    setEnabled(data.enabled);
    setSchedule(data.schedule || 'every_5min');
    setDirective(data.directive || '');
    setDirty(false);
  }, [data]);

  const onSave = async () => {
    try {
      await upsert.mutateAsync({ projectId, enabled, schedule, directive });
      showToast(enabled ? 'Autonomy saved' : 'Autonomy paused', 'success');
      setDirty(false);
    } catch (e) {
      showToast(`Could not save autonomy: ${(e as Error).message}`, 'error');
    }
  };

  const onRunNow = async () => {
    try {
      const res = await runNow.mutateAsync(projectId);
      const status = res?.result?.status ?? 'ok';
      if (status === 'skipped') {
        showToast('Heartbeat skipped — no directive below the divider', 'info');
      } else if (status === 'error') {
        showToast(res?.result?.message || 'Heartbeat failed', 'error');
      } else {
        showToast('Heartbeat triggered', 'success');
      }
    } catch (e) {
      showToast(`Could not run heartbeat: ${(e as Error).message}`, 'error');
    }
  };

  const onRemove = async () => {
    if (!confirm('Remove the autonomy heartbeat for this project?')) return;
    try {
      await disable.mutateAsync(projectId);
      showToast('Autonomy removed', 'success');
    } catch (e) {
      showToast(`Could not remove autonomy: ${(e as Error).message}`, 'error');
    }
  };

  const jobExists = !!data?.job_exists;
  const nextRun = data?.next_run ? new Date(data.next_run).toLocaleString() : null;

  return (
    <div className="form-group space-y-3 border border-border rounded-md p-3 bg-muted/20">
      <div className="flex items-center justify-between">
        <div>
          <div className="text-sm font-medium text-foreground">Project Autonomy</div>
          <p className="text-xs text-muted-foreground">
            Run a scheduled heartbeat with this project's memory, KG, and ledger scope.
            Voxy reads the directive below the <code>---</code> divider; an empty directive is a no-op.
          </p>
        </div>
      </div>

      <div className="flex items-center gap-2">
        <input
          type="checkbox"
          id="autonomy-enabled"
          checked={enabled}
          onChange={(e) => {
            setEnabled(e.target.checked);
            setDirty(true);
          }}
          disabled={isLoading}
          className="setting-checkbox w-4 h-4 rounded border-border accent-primary"
          data-testid="autonomy-enabled-toggle"
        />
        <label htmlFor="autonomy-enabled" className="text-sm text-foreground cursor-pointer">
          Enable heartbeat
        </label>
      </div>

      <div className="form-group space-y-1">
        <label className="text-sm font-medium text-foreground">Schedule</label>
        <select
          value={schedule}
          onChange={(e) => {
            setSchedule(e.target.value);
            setDirty(true);
          }}
          disabled={isLoading}
          className="form-input w-full px-3 py-2 rounded-md border border-border bg-background text-foreground text-sm focus:outline-none focus:ring-2 focus:ring-primary/50"
          data-testid="autonomy-schedule"
        >
          {SCHEDULE_OPTIONS.map((o) => (
            <option key={o.value} value={o.value}>
              {o.label}
            </option>
          ))}
        </select>
        {nextRun && enabled && (
          <p className="text-xs text-muted-foreground">Next run: {nextRun}</p>
        )}
      </div>

      <div className="form-group space-y-1">
        <label className="text-sm font-medium text-foreground">Directive</label>
        <textarea
          value={directive}
          onChange={(e) => {
            setDirective(e.target.value);
            setDirty(true);
          }}
          disabled={isLoading}
          rows={5}
          placeholder="What should Voxy do on the next heartbeat? Leave empty to pause between cycles."
          className="w-full px-3 py-2 rounded-md border border-border bg-background text-sm font-mono focus:outline-none focus:ring-2 focus:ring-primary/50"
          data-testid="autonomy-directive"
        />
        {data?.file_path && (
          <p className="text-xs text-muted-foreground truncate" title={data.file_path}>
            File: <code>{data.file_path}</code>
          </p>
        )}
      </div>

      <div className="flex items-center gap-2 flex-wrap">
        <button
          type="button"
          onClick={onSave}
          disabled={!dirty || upsert.isPending || isLoading}
          className="btn-primary px-3 py-1.5 rounded-md bg-primary text-primary-foreground text-sm font-medium hover:opacity-90 disabled:opacity-50"
          data-testid="autonomy-save"
        >
          {upsert.isPending ? 'Saving…' : 'Save'}
        </button>
        <button
          type="button"
          onClick={onRunNow}
          disabled={!enabled || !data?.actionable || runNow.isPending}
          className="btn-ghost px-3 py-1.5 rounded-md border border-border text-sm hover:bg-accent disabled:opacity-50"
          title={
            !enabled
              ? 'Enable autonomy first'
              : !data?.actionable
              ? 'Directive is empty — nothing to run'
              : 'Trigger the heartbeat immediately'
          }
          data-testid="autonomy-run-now"
        >
          {runNow.isPending ? 'Running…' : 'Run now'}
        </button>
        {jobExists && (
          <button
            type="button"
            onClick={onRemove}
            disabled={disable.isPending}
            className="btn-ghost px-3 py-1.5 rounded-md border border-destructive/30 text-destructive text-sm hover:bg-destructive/10 disabled:opacity-50 ml-auto"
            data-testid="autonomy-remove"
          >
            {disable.isPending ? 'Removing…' : 'Remove'}
          </button>
        )}
      </div>
    </div>
  );
}

export default ProjectAutonomySection;
