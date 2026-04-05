/**
 * FreeBoard — board/inbox view using the same KanbanCard component as Kanban.
 *
 * Shows cards with status === 'card' (inbox/backlog). Uses the exact same
 * card rendering as KanbanBoard for consistent UX (checkbox, dropdown, etc).
 */

import { useMemo, useCallback, useState } from 'react';
import { Archive, RotateCcw, ChevronRight, Trash2 } from 'lucide-react';
import { cn } from '@/lib/utils';
import { useProjectStore } from '../../stores/useProjectStore';
import { useToastStore } from '../../stores/useToastStore';
import { useCardStore, SYSTEM_PROJECT_ID } from '../../stores/useCardStore';
import { useCards, useArchivedCards, useCreateCard, useRestoreCard, useDeleteCard } from '../../hooks/api/useCards';
import { KanbanCard } from '../Kanban/KanbanCard';

// ── Main component ────────────────────────────────────────────────────────────

export interface FreeBoardProps {
  projectId?: string;
}

export function FreeBoard({ projectId: projectIdProp }: FreeBoardProps = {}) {
  const storeProjectId = useProjectStore((s) => s.currentProjectId);
  const currentProjectId = projectIdProp ?? storeProjectId ?? SYSTEM_PROJECT_ID;
  const selectCard = useProjectStore((s) => s.selectCard);
  const showToast = useToastStore((s) => s.showToast);

  const { data: cards = [], isLoading } = useCards(currentProjectId);

  const boardCards = useMemo(
    () =>
      cards
        .filter((c) => c.status === 'card')
        .sort((a, b) => b.createdAt - a.createdAt),
    [cards],
  );

  const createCard = useCreateCard();

  // Multi-select state (same pattern as KanbanBoard)
  const [selectMode] = useState(false);
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());

  const handleSelectChange = useCallback((id: string, selected: boolean) => {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (selected) next.add(id);
      else next.delete(id);
      return next;
    });
  }, []);

  const handleAddCard = useCallback(async () => {
    if (!currentProjectId) return;
    try {
      const newCard = await createCard.mutateAsync({
        projectId: currentProjectId,
        title: 'New card',
        status: 'card',
      });
      useCardStore.setState((state) => ({
        cardsById: { ...state.cardsById, [newCard.id]: newCard },
      }));
      selectCard(newCard.id);
    } catch {
      showToast('Failed to create card', 'error');
    }
  }, [currentProjectId, createCard, selectCard, showToast]);

  const handleCardClick = useCallback(
    (cardId: string) => selectCard(cardId),
    [selectCard],
  );

  return (
    <div className="flex flex-col h-full" data-testid="freeboard">
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-2 border-b border-border/40">
        <button
          onClick={handleAddCard}
          disabled={createCard.isPending}
          data-testid="freeboard-add-btn"
          className={cn(
            'px-3 py-1.5 text-[13px] rounded border border-border/60',
            'text-muted-foreground hover:text-foreground hover:border-border',
            'hover:bg-accent transition-all disabled:opacity-50',
          )}
        >
          + Add Card
        </button>
      </div>

      {/* Grid — uses KanbanCard for consistent rendering */}
      <div className="flex-1 overflow-y-auto p-4">
        <div className="grid grid-cols-[repeat(auto-fill,minmax(220px,1fr))] gap-3">
          {isLoading ? (
            <div className="col-span-full flex flex-col items-center justify-center py-16 text-muted-foreground">
              <div className="text-sm">Loading...</div>
            </div>
          ) : boardCards.length === 0 ? (
            <div className="col-span-full flex flex-col items-center justify-center py-16 text-muted-foreground">
              <div className="text-sm">No cards yet. Add one!</div>
            </div>
          ) : (
            boardCards.map((card) => (
              <KanbanCard
                key={card.id}
                card={card}
                selectMode={selectMode}
                isSelected={selectedIds.has(card.id)}
                onSelectChange={handleSelectChange}
                onCardClick={handleCardClick}
              />
            ))
          )}
        </div>

        {/* Archived cards */}
        <FreeBoardArchived projectId={currentProjectId} />
      </div>
    </div>
  );
}

// ── Archived section ─────────────────────────────────────────────────────────

function FreeBoardArchived({ projectId }: { projectId: string }) {
  const [open, setOpen] = useState(false);
  const { data: archivedCards, isLoading } = useArchivedCards(projectId);
  const restoreCard = useRestoreCard();
  const deleteCard = useDeleteCard();
  const showToast = useToastStore((s) => s.showToast);

  return (
    <div className="mt-6">
      <button
        className="flex items-center gap-2 text-sm text-muted-foreground hover:text-foreground transition-colors py-1"
        onClick={() => setOpen(!open)}
      >
        <Archive size={14} /> Archived Cards
        <ChevronRight size={12} className={cn('transition-transform', open && 'rotate-90')} />
      </button>

      {open && (
        <div className="mt-2 space-y-1">
          {isLoading && <div className="text-xs text-muted-foreground py-2">Loading...</div>}
          {archivedCards && archivedCards.length === 0 && (
            <div className="text-xs text-muted-foreground py-2">No archived cards</div>
          )}
          {archivedCards?.map((card) => (
            <div key={card.id} className="flex items-center justify-between rounded border border-border/40 px-3 py-2 text-sm">
              <span className="flex-1 min-w-0 font-medium text-foreground truncate">{card.title}</span>
              <div className="flex items-center gap-1 ml-2 shrink-0">
                <button
                  className="inline-flex items-center gap-1 px-2 py-1 rounded text-xs text-emerald-400 hover:bg-accent transition-colors"
                  onClick={async () => {
                    try {
                      await restoreCard.mutateAsync({ cardId: card.id, projectId });
                      showToast(`"${card.title}" restored`, 'success');
                    } catch {
                      showToast('Restore failed', 'error');
                    }
                  }}
                >
                  <RotateCcw size={12} /> Restore
                </button>
                <button
                  className="inline-flex items-center gap-1 px-2 py-1 rounded text-xs text-destructive hover:bg-destructive/20 transition-colors"
                  onClick={async () => {
                    if (!confirm(`Permanently delete "${card.title}"?`)) return;
                    try {
                      await deleteCard.mutateAsync({ cardId: card.id, projectId });
                      showToast(`"${card.title}" deleted`, 'success');
                    } catch {
                      showToast('Delete failed', 'error');
                    }
                  }}
                >
                  <Trash2 size={12} /> Delete
                </button>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
