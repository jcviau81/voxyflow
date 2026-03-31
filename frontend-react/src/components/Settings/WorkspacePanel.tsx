/**
 * WorkspacePanel — Workspace path + Connection settings.
 *
 * Mirrors renderWorkspaceSection() + renderConnectionSection()
 * from frontend/src/components/Settings/SettingsPage.ts (lines 1022–1061).
 *
 * Features:
 *  - Workspace path input with resolved path hint
 *  - Save to /api/settings
 *  - Connection status + reconnect (via WebSocket hook)
 */

import { useState, useEffect } from 'react';
import { FolderOpen, Globe, Loader2 } from 'lucide-react';
import { useQuery, useMutation } from '@tanstack/react-query';
import { useToastStore } from '../../stores/useToastStore';

// ── Types ──────────────────────────────────────────────────────────────────

interface AppSettings {
  workspace_path?: string;
  [key: string]: unknown;
}

// ── WorkspacePanel ─────────────────────────────────────────────────────────

export function WorkspacePanel() {
  const { showToast } = useToastStore();

  const { data: settings, isLoading } = useQuery<AppSettings>({
    queryKey: ['settings'],
    queryFn: () => fetch('/api/settings').then((r) => r.json()),
  });

  const [wsPath, setWsPath] = useState('workspace');
  const [dirty, setDirty] = useState(false);

  useEffect(() => {
    if (settings?.workspace_path !== undefined) {
      setWsPath(settings.workspace_path);
    }
  }, [settings]);

  const resolvedPath = wsPath.startsWith('/') ? wsPath : `~/voxyflow/${wsPath || 'workspace'}`;

  const saveMutation = useMutation({
    mutationFn: async () => {
      const current = settings ?? {};
      const response = await fetch('/api/settings', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ ...current, workspace_path: wsPath }),
      });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      return response.json();
    },
    onSuccess: () => {
      setDirty(false);
      showToast('Workspace path saved', 'success', 2000);
    },
    onError: (e) => {
      showToast(`Failed to save: ${e}`, 'error', 3000);
    },
  });

  if (isLoading) {
    return (
      <div className="p-6 flex items-center gap-2 text-muted-foreground text-sm">
        <Loader2 size={16} className="animate-spin" />
        Loading…
      </div>
    );
  }

  return (
    <div className="settings-panel-content p-6 space-y-6">
      {/* ── Workspace path ── */}
      <div>
        <h3 className="flex items-center gap-2 text-base font-semibold mb-4">
          <FolderOpen size={16} />
          Workspace
        </h3>

        <div className="space-y-4">
          <div className="setting-row flex items-start gap-4">
            <div className="setting-info flex-1 space-y-0.5">
              <div className="setting-label text-sm font-medium">Workspace Path</div>
              <div className="setting-description text-xs text-muted-foreground">
                Directory where Voxy stores files. Relative to ~/voxyflow/ or absolute.
              </div>
            </div>
            <input
              type="text"
              value={wsPath}
              onChange={(e) => {
                setWsPath(e.target.value);
                setDirty(true);
              }}
              placeholder="workspace"
              className="setting-input w-52 h-8 px-3 text-sm rounded-md border border-input bg-background"
            />
          </div>

          <div className="setting-row flex items-start gap-4">
            <div className="setting-info flex-1 space-y-0.5">
              <div className="setting-label text-sm font-medium">Resolved Path</div>
              <div className="setting-description font-mono text-xs text-muted-foreground/70">
                {resolvedPath}
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* ── Connection ── */}
      <div>
        <h3 className="flex items-center gap-2 text-base font-semibold mb-4">
          <Globe size={16} />
          Connection
        </h3>
        <p className="text-xs text-muted-foreground">
          WebSocket connection status is shown in the status bar. Use the reconnect button if the
          connection is lost.
        </p>
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
              setWsPath(settings?.workspace_path ?? 'workspace');
              setDirty(false);
            }}
            className="btn-ghost h-8 px-3 text-sm rounded-md hover:bg-accent"
          >
            Cancel
          </button>
        </div>
      )}
    </div>
  );
}
