import { useState, useRef, useEffect } from 'react';
import { Rocket, Folder } from 'lucide-react';
import { useWorkspaceStore } from '../../stores/useWorkspaceStore';
import { useMoveCard } from '../../hooks/api/useCards';
import { useToastStore } from '../../stores/useToastStore';
import { SYSTEM_WORKSPACE_ID } from '../../lib/constants';

interface WorkspacePickerProps {
  cardId: string;
  onMoved: () => void;
}

export function WorkspacePicker({ cardId, onMoved }: WorkspacePickerProps) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  const workspaces = useWorkspaceStore((s) => s.workspaces).filter(
    (p) => p.id !== SYSTEM_WORKSPACE_ID && !p.archived,
  );
  const moveCard = useMoveCard();
  const showToast = useToastStore((s) => s.showToast);

  // Close on outside click
  useEffect(() => {
    if (!open) return;
    const handler = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) {
        setOpen(false);
      }
    };
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, [open]);

  const handleSelect = (workspaceId: string, workspaceName: string) => {
    setOpen(false);
    moveCard.mutate(
      { cardId, targetWorkspaceId: workspaceId, sourceWorkspaceId: SYSTEM_WORKSPACE_ID },
      {
        onSuccess: () => {
          showToast(`Card moved to ${workspaceName}`, 'success');
          onMoved();
        },
        onError: () => {
          showToast('Failed to assign card', 'error');
        },
      },
    );
  };

  return (
    <div ref={ref} className="relative">
      <button
        type="button"
        onClick={() => setOpen(!open)}
        className="flex items-center gap-1.5 rounded-md border border-border bg-muted/40 px-3 py-1.5 text-xs font-medium text-muted-foreground transition-colors hover:bg-muted"
      >
        <Rocket className="h-3.5 w-3.5" />
        Assign to Workspace
      </button>

      {open && (
        <div className="absolute left-0 top-full z-50 mt-1 w-56 rounded-lg border border-border bg-popover py-1 shadow-lg">
          {workspaces.length === 0 ? (
            <div className="px-3 py-2 text-xs text-muted-foreground">No workspaces yet</div>
          ) : (
            workspaces.map((p) => (
              <button
                key={p.id}
                type="button"
                onClick={() => handleSelect(p.id, p.name)}
                className="flex w-full items-center gap-2 px-3 py-1.5 text-left text-xs hover:bg-muted"
              >
                {p.emoji
                  ? <span>{p.emoji}</span>
                  : <Folder size={13} className="text-muted-foreground" />}
                <span className="truncate">{p.name}</span>
              </button>
            ))
          )}
        </div>
      )}
    </div>
  );
}
