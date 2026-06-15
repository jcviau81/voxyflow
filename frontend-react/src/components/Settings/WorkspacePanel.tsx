/**
 * StoragePanel — read-only view of where Voxyflow stores things on disk.
 *
 * Replaces the old WorkspacePanel, whose single `workspace_path` setting was
 * write-only (nothing in the backend ever read it). Real locations come from
 * GET /api/sandbox/info. The per-workspace working directory is a property of
 * each workspace (set in the workspace form), not a global setting.
 */

import { HardDrive, Loader2 } from 'lucide-react';
import { useQuery } from '@tanstack/react-query';

interface StorageInfo {
  data_dir: string;
  sandbox_root: string;
  workspace_areas: string;
  memory_dir: string;
}

const ROWS: Array<{ key: keyof StorageInfo; label: string; description: string }> = [
  {
    key: 'data_dir',
    label: 'Data directory',
    description: 'SQLite database, settings, worker sessions, jobs.',
  },
  {
    key: 'sandbox_root',
    label: 'Worker sandbox',
    description: 'Default working area for files workers create.',
  },
  {
    key: 'workspace_areas',
    label: 'Per-workspace areas',
    description:
      'Each workspace gets its own folder in the sandbox. A workspace can instead point at any local directory via its “local path” (workspace form) — workers then run there.',
  },
  {
    key: 'memory_dir',
    label: 'Memory store',
    description: 'ChromaDB vector store for long-term memory.',
  },
];

export function WorkspacePanel() {
  const { data, isLoading, isError } = useQuery<StorageInfo>({
    queryKey: ['storage-info'],
    queryFn: () => fetch('/api/sandbox/info').then((r) => r.json()),
    staleTime: Infinity,
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
      <div>
        <h3 className="flex items-center gap-2 text-base font-semibold mb-1">
          <HardDrive size={16} />
          Storage
        </h3>
        <p className="text-xs text-muted-foreground mb-4">
          Where Voxyflow keeps its data on this machine. These locations are configured by the
          backend (environment variables), not editable here.
        </p>

        {isError || !data ? (
          <p className="text-xs text-muted-foreground">Could not load storage locations.</p>
        ) : (
          <div className="space-y-4">
            {ROWS.map(({ key, label, description }) => (
              <div key={key} className="setting-row flex items-start gap-4">
                <div className="setting-info flex-1 space-y-0.5">
                  <div className="setting-label text-sm font-medium">{label}</div>
                  <div className="setting-description text-xs text-muted-foreground">
                    {description}
                  </div>
                  <div className="font-mono text-xs text-muted-foreground/70 break-all">
                    {data[key]}
                  </div>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
