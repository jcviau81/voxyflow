import { useState, useRef, useEffect } from 'react';
import { Rocket } from 'lucide-react';
import { useProjectStore } from '../../stores/useProjectStore';
import { useMoveCard } from '../../hooks/api/useCards';
import { useToastStore } from '../../stores/useToastStore';
import { SYSTEM_PROJECT_ID } from '../../lib/constants';

interface ProjectPickerProps {
  cardId: string;
  onMoved: () => void;
}

export function ProjectPicker({ cardId, onMoved }: ProjectPickerProps) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  const projects = useProjectStore((s) => s.projects).filter(
    (p) => p.id !== SYSTEM_PROJECT_ID && !p.archived,
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

  const handleSelect = (projectId: string, projectName: string) => {
    setOpen(false);
    moveCard.mutate(
      { cardId, targetProjectId: projectId, sourceProjectId: SYSTEM_PROJECT_ID },
      {
        onSuccess: () => {
          showToast(`Card moved to ${projectName}`, 'success');
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
        Assign to Project
      </button>

      {open && (
        <div className="absolute left-0 top-full z-50 mt-1 w-56 rounded-lg border border-border bg-popover py-1 shadow-lg">
          {projects.length === 0 ? (
            <div className="px-3 py-2 text-xs text-muted-foreground">No projects yet</div>
          ) : (
            projects.map((p) => (
              <button
                key={p.id}
                type="button"
                onClick={() => handleSelect(p.id, p.name)}
                className="flex w-full items-center gap-2 px-3 py-1.5 text-left text-xs hover:bg-muted"
              >
                <span>{p.emoji || '📁'}</span>
                <span className="truncate">{p.name}</span>
              </button>
            ))
          )}
        </div>
      )}
    </div>
  );
}
