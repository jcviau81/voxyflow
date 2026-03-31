import { useState } from 'react';
import { Link, X } from 'lucide-react';
import { useCardStore } from '../../../stores/useCardStore';

interface WorkspaceFile {
  name: string;
  path: string;
  is_dir: boolean;
}

export function LinkedFiles({ cardId, files }: { cardId: string; files: string[] }) {
  const updateCard = useCardStore((s) => s.updateCard);
  const [showPicker, setShowPicker] = useState(false);
  const [workspaceFiles, setWorkspaceFiles] = useState<WorkspaceFile[]>([]);
  const [loading, setLoading] = useState(false);

  const loadWorkspaceFiles = async () => {
    if (showPicker) {
      setShowPicker(false);
      return;
    }
    setLoading(true);
    try {
      const resp = await fetch('/api/workspace/files');
      if (resp.ok) {
        const data = (await resp.json()) as WorkspaceFile[];
        setWorkspaceFiles(data.filter((f) => !f.is_dir));
      }
    } catch (e) {
      console.error('[LinkedFiles] Failed to load workspace files:', e);
    } finally {
      setLoading(false);
      setShowPicker(true);
    }
  };

  const linkFile = async (path: string) => {
    try {
      const resp = await fetch(`/api/cards/${cardId}/files`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ path }),
      });
      if (resp.ok) {
        const updated = (await resp.json()) as string[];
        updateCard(cardId, { files: updated });
      }
    } catch (e) {
      console.error('[LinkedFiles] Failed to link file:', e);
    }
    setShowPicker(false);
  };

  const unlinkFile = async (path: string) => {
    try {
      const resp = await fetch(
        `/api/cards/${cardId}/files?path=${encodeURIComponent(path)}`,
        { method: 'DELETE' },
      );
      if (resp.ok) {
        const updated = (await resp.json()) as string[];
        updateCard(cardId, { files: updated });
      }
    } catch (e) {
      console.error('[LinkedFiles] Failed to unlink file:', e);
    }
  };

  const availableFiles = workspaceFiles.filter((f) => !files.includes(f.path));

  return (
    <div className="space-y-1.5">
      <div className="flex items-center justify-between">
        <label className="flex items-center gap-1 text-xs font-medium text-muted-foreground"><Link size={12} /> Linked Files</label>
        <button
          type="button"
          onClick={loadWorkspaceFiles}
          className="text-xs text-muted-foreground/60 hover:text-muted-foreground"
        >
          {loading ? '…' : showPicker ? <><X size={10} /> Close</> : '+ Link file'}
        </button>
      </div>

      {files.length === 0 ? (
        <p className="text-[10px] text-muted-foreground/40">No linked files.</p>
      ) : (
        <div className="space-y-1">
          {files.map((filePath) => (
            <div key={filePath} className="flex items-center gap-1.5 text-[11px]">
              <span className="flex-1 truncate text-foreground" title={filePath}>
                {filePath.split('/').pop() || filePath}
              </span>
              <button
                type="button"
                onClick={() => unlinkFile(filePath)}
                className="text-muted-foreground/40 hover:text-muted-foreground"
                title="Unlink file"
              >
                <X size={10} />
              </button>
            </div>
          ))}
        </div>
      )}

      {showPicker && (
        <div className="max-h-40 overflow-y-auto rounded border border-border bg-background text-[11px]">
          {availableFiles.length === 0 ? (
            <div className="px-3 py-2 text-muted-foreground/60">
              {workspaceFiles.length === 0
                ? 'Workspace is empty'
                : 'All workspace files already linked'}
            </div>
          ) : (
            availableFiles.map((f) => (
              <button
                key={f.path}
                type="button"
                onClick={() => linkFile(f.path)}
                className="block w-full px-3 py-1.5 text-left hover:bg-muted"
                title={f.path}
              >
                {f.name}
              </button>
            ))
          )}
        </div>
      )}
    </div>
  );
}
