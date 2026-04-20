/**
 * DataPanel — Data management + ChromaDB backup settings.
 *
 * Features:
 *  - ChromaDB daily backup toggle + retention config
 *  - Last backup status display
 *  - Clear all local data
 */

import { useState, useEffect } from 'react';
import { Database, Trash2, HardDrive, Loader2, CheckCircle, AlertCircle } from 'lucide-react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { useToastStore } from '../../stores/useToastStore';
import { authFetch } from '../../lib/authClient';

interface BackupSettings {
  chromadb_enabled: boolean;
  retention_days: number;
  backup_hour: number;
}

interface AppSettings {
  backup?: BackupSettings;
  [key: string]: unknown;
}

interface BackupStatus {
  last_backup: string | null;
  backup_count: number;
  total_size_mb: number;
  next_scheduled: string | null;
}

export function DataPanel() {
  const [confirming, setConfirming] = useState(false);
  const { showToast } = useToastStore();
  const queryClient = useQueryClient();

  // Load settings
  const { data: settings, isLoading } = useQuery<AppSettings>({
    queryKey: ['settings'],
    queryFn: () => fetch('/api/settings').then((r) => r.json()),
  });

  // Load backup status
  const { data: backupStatus } = useQuery<BackupStatus>({
    queryKey: ['backup-status'],
    queryFn: () => fetch('/api/backup/status').then((r) => r.json()),
    refetchInterval: 60000,
  });

  // Local state
  const [enabled, setEnabled] = useState(false);
  const [retentionDays, setRetentionDays] = useState(7);
  const [backupHour, setBackupHour] = useState(3);
  const [dirty, setDirty] = useState(false);

  useEffect(() => {
    if (settings?.backup) {
      setEnabled(settings.backup.chromadb_enabled);
      setRetentionDays(settings.backup.retention_days);
      setBackupHour(settings.backup.backup_hour);
    }
  }, [settings]);

  // Save mutation
  const saveMutation = useMutation({
    mutationFn: async () => {
      // Always fetch fresh settings to avoid overwriting changes from other panels
      const current = await fetch('/api/settings').then((r) => r.json());
      const response = await authFetch('/api/settings', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          ...current,
          backup: {
            chromadb_enabled: enabled,
            retention_days: retentionDays,
            backup_hour: backupHour,
          },
        }),
      });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      return response.json();
    },
    onSuccess: () => {
      setDirty(false);
      queryClient.invalidateQueries({ queryKey: ['settings'] });
      showToast('Backup settings saved', 'success', 2000);
    },
    onError: (e) => {
      showToast(`Failed to save: ${e}`, 'error', 3000);
    },
  });

  // Manual backup trigger
  const triggerMutation = useMutation({
    mutationFn: async () => {
      const response = await authFetch('/api/backup/trigger', { method: 'POST' });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      return response.json();
    },
    onSuccess: (data) => {
      queryClient.invalidateQueries({ queryKey: ['backup-status'] });
      showToast(data.message || 'Backup started', 'success', 3000);
    },
    onError: (e) => {
      showToast(`Backup failed: ${e}`, 'error', 3000);
    },
  });

  const handleClear = () => {
    if (confirming) {
      localStorage.clear();
      location.reload();
    } else {
      setConfirming(true);
      setTimeout(() => setConfirming(false), 4000);
    }
  };

  const markDirty = () => setDirty(true);

  if (isLoading) {
    return (
      <div className="p-6 flex items-center gap-2 text-muted-foreground text-sm">
        <Loader2 size={16} className="animate-spin" />
        Loading…
      </div>
    );
  }

  return (
    <div className="settings-panel-content p-6 space-y-6" data-testid="settings-data">
      {/* ── ChromaDB Backup ── */}
      <div>
        <h3 className="flex items-center gap-2 text-base font-semibold mb-4">
          <HardDrive size={16} />
          ChromaDB Backup
        </h3>

        {/* Enable toggle */}
        <div className="space-y-4">
          <div className="setting-row flex items-center justify-between gap-4">
            <div className="setting-info space-y-0.5">
              <div className="setting-label text-sm font-medium">Daily Backup</div>
              <div className="setting-description text-xs text-muted-foreground">
                Automatically back up all memory and knowledge collections daily.
                Protects against data corruption from unexpected shutdowns.
              </div>
            </div>
            <button
              type="button"
              role="switch"
              aria-checked={enabled}
              onClick={() => { setEnabled(!enabled); markDirty(); }}
              className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors ${
                enabled ? 'bg-primary' : 'bg-muted'
              }`}
            >
              <span
                className={`inline-block h-4 w-4 transform rounded-full bg-white transition-transform ${
                  enabled ? 'translate-x-6' : 'translate-x-1'
                }`}
              />
            </button>
          </div>

          {/* Suggestion banner when disabled */}
          {!enabled && (
            <div className="rounded-md border border-amber-500/30 bg-amber-500/5 px-4 py-3 text-xs text-amber-200">
              <strong>Recommended:</strong> Enable daily backups to protect your memory data.
              ChromaDB indexes can get corrupted by unexpected shutdowns or resource pressure.
            </div>
          )}

          {enabled && (
            <>
              {/* Retention days */}
              <div className="setting-row flex items-center justify-between gap-4">
                <div className="setting-info space-y-0.5">
                  <div className="setting-label text-sm font-medium">Retention</div>
                  <div className="setting-description text-xs text-muted-foreground">
                    Number of days to keep backups before pruning.
                  </div>
                </div>
                <div className="flex items-center gap-2">
                  <input
                    type="range"
                    min={1}
                    max={30}
                    value={retentionDays}
                    onChange={(e) => { setRetentionDays(Number(e.target.value)); markDirty(); }}
                    className="w-24 accent-primary"
                  />
                  <span className="text-sm text-muted-foreground w-12 text-right">
                    {retentionDays}d
                  </span>
                </div>
              </div>

              {/* Backup hour */}
              <div className="setting-row flex items-center justify-between gap-4">
                <div className="setting-info space-y-0.5">
                  <div className="setting-label text-sm font-medium">Backup Time</div>
                  <div className="setting-description text-xs text-muted-foreground">
                    Hour of day (UTC) to run the backup.
                  </div>
                </div>
                <select
                  value={backupHour}
                  onChange={(e) => { setBackupHour(Number(e.target.value)); markDirty(); }}
                  className="h-8 px-2 text-sm rounded-md border border-input bg-background"
                >
                  {Array.from({ length: 24 }, (_, i) => (
                    <option key={i} value={i}>
                      {String(i).padStart(2, '0')}:30 UTC
                    </option>
                  ))}
                </select>
              </div>

              {/* Status */}
              {backupStatus && (
                <div className="rounded-md border border-border bg-muted/30 px-4 py-3 text-xs space-y-1">
                  <div className="flex items-center gap-1.5">
                    {backupStatus.last_backup ? (
                      <CheckCircle size={12} className="text-green-400" />
                    ) : (
                      <AlertCircle size={12} className="text-muted-foreground" />
                    )}
                    <span>
                      Last backup:{' '}
                      {backupStatus.last_backup || 'Never'}
                    </span>
                  </div>
                  {backupStatus.backup_count > 0 && (
                    <div className="text-muted-foreground">
                      {backupStatus.backup_count} backup(s) stored ({backupStatus.total_size_mb.toFixed(1)} MB)
                    </div>
                  )}
                </div>
              )}

              {/* Manual trigger */}
              <button
                type="button"
                onClick={() => triggerMutation.mutate()}
                disabled={triggerMutation.isPending}
                className="h-8 px-4 text-sm rounded-md border border-input hover:bg-accent flex items-center gap-1.5 transition-colors"
              >
                {triggerMutation.isPending && <Loader2 size={14} className="animate-spin" />}
                Run Backup Now
              </button>
            </>
          )}
        </div>
      </div>

      {/* Save bar */}
      {dirty && (
        <div className="flex items-center gap-3 pt-2 border-t border-border">
          <button
            type="button"
            onClick={() => saveMutation.mutate()}
            disabled={saveMutation.isPending}
            className="btn-primary h-8 px-4 text-sm rounded-md bg-primary text-primary-foreground hover:bg-primary/90 disabled:opacity-50 flex items-center gap-1.5"
          >
            {saveMutation.isPending && <Loader2 size={14} className="animate-spin" />}
            Save
          </button>
          <button
            type="button"
            onClick={() => {
              if (settings?.backup) {
                setEnabled(settings.backup.chromadb_enabled);
                setRetentionDays(settings.backup.retention_days);
                setBackupHour(settings.backup.backup_hour);
              }
              setDirty(false);
            }}
            className="btn-ghost h-8 px-3 text-sm rounded-md hover:bg-accent"
          >
            Cancel
          </button>
        </div>
      )}

      {/* ── Danger Zone ── */}
      <div>
        <h3 className="flex items-center gap-2 text-base font-semibold mb-4">
          <Database size={16} />
          Data
        </h3>

        <div className="setting-row flex items-center justify-between gap-4">
          <div className="setting-info space-y-0.5">
            <div className="setting-label text-sm font-medium">Clear All Data</div>
            <div className="setting-description text-xs text-muted-foreground">
              Delete all local data and reload. This cannot be undone.
            </div>
          </div>
          <button
            type="button"
            onClick={handleClear}
            className={`h-8 px-4 text-sm rounded-md border flex items-center gap-1.5 transition-colors ${
              confirming
                ? 'bg-destructive text-destructive-foreground border-destructive hover:bg-destructive/90'
                : 'border-destructive text-destructive hover:bg-destructive/10'
            }`}
          >
            <Trash2 size={14} />
            {confirming ? 'Click again to confirm' : 'Clear All'}
          </button>
        </div>
      </div>
    </div>
  );
}
