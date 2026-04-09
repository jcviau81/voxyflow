/**
 * FreeBoard — board/inbox view using the same KanbanCard component as Kanban.
 *
 * Shows cards with status === 'card' (inbox/backlog). Uses the exact same
 * card rendering as KanbanBoard for consistent UX (checkbox, dropdown, etc).
 */

import React, { useMemo, useCallback, useState, useEffect } from 'react';
import { createPortal } from 'react-dom';
import { Archive, RotateCcw, ChevronRight, Trash2 } from 'lucide-react';
import {
  DndContext,
  DragOverlay,
  PointerSensor,
  useSensor,
  useSensors,
  useDraggable,
  useDroppable,
  type DragStartEvent,
  type DragEndEvent,
} from '@dnd-kit/core';
import { CSS } from '@dnd-kit/utilities';
import { cn } from '@/lib/utils';
import type { Card, CardStatus } from '../../types';
import { useProjectStore } from '../../stores/useProjectStore';
import { useToastStore } from '../../stores/useToastStore';
import { useCardStore, SYSTEM_PROJECT_ID } from '../../stores/useCardStore';
import { useCards, useArchivedCards, useCreateCard, useRestoreCard, useDeleteCard, usePatchCard } from '../../hooks/api/useCards';
import { useExportProject, useImportProject } from '../../hooks/api/useProjects';
import { KanbanCard } from '../Kanban/KanbanCard';
import { DepGraphOverlay } from '../Kanban/KanbanBoard';
import { BoardHeader, useDebounce } from './BoardHeader';

// ── DnD helpers ───────────────────────────────────────────────────────────────

const KANBAN_DROP_TARGETS: { status: CardStatus; label: string }[] = [
  { status: 'todo', label: 'Todo' },
  { status: 'in-progress', label: 'In Progress' },
  { status: 'done', label: 'Done' },
];

interface DraggableBacklogCardProps {
  card: Card;
  children: React.ReactNode;
}

function DraggableBacklogCard({ card, children }: DraggableBacklogCardProps) {
  const { attributes, listeners, setNodeRef, transform, isDragging } = useDraggable({
    id: card.id,
    data: { type: 'card', card },
  });

  const style: React.CSSProperties = {
    transform: CSS.Translate.toString(transform),
    opacity: isDragging ? 0.4 : undefined,
  };

  return (
    <div ref={setNodeRef} style={style} {...attributes} {...listeners}>
      {children}
    </div>
  );
}

interface KanbanDropZoneProps {
  status: CardStatus;
  label: string;
}

function KanbanDropZone({ status, label }: KanbanDropZoneProps) {
  const { setNodeRef, isOver } = useDroppable({ id: `freeboard-drop-${status}`, data: { status } });
  return (
    <div
      ref={setNodeRef}
      className={cn(
        'flex-1 rounded-lg border-2 border-dashed px-3 py-4 text-center text-sm font-medium transition-colors',
        isOver
          ? 'border-primary bg-primary/10 text-primary'
          : 'border-border/60 bg-muted/30 text-muted-foreground',
      )}
    >
      Move to {label}
    </div>
  );
}

// ── Main component ────────────────────────────────────────────────────────────

export interface FreeBoardProps {
  projectId?: string;
}

export function FreeBoard({ projectId: projectIdProp }: FreeBoardProps = {}) {
  const storeProjectId = useProjectStore((s) => s.currentProjectId);
  const currentProjectId = projectIdProp ?? storeProjectId ?? SYSTEM_PROJECT_ID;
  const selectCard = useProjectStore((s) => s.selectCard);
  const showToast = useToastStore((s) => s.showToast);
  const cardsById = useCardStore((s) => s.cardsById);

  const { data: cards = [], isLoading } = useCards(currentProjectId);

  const boardCards = useMemo(
    () =>
      cards
        .filter((c) => c.status === 'card')
        .sort((a, b) => b.createdAt - a.createdAt),
    [cards],
  );

  const createCard = useCreateCard();
  const patchCard = usePatchCard();
  const exportProject = useExportProject();
  const importProject = useImportProject();

  // ── Filter state ─────────────────────────────────────────────────────────

  const [searchInput, setSearchInput] = useState('');
  const query = useDebounce(searchInput, 200);
  const [priorityFilter, setPriorityFilter] = useState<number | null>(null);
  const [agentFilter, setAgentFilter] = useState<string | null>(null);
  const [tagFilter, setTagFilter] = useState<string | null>(null);

  // Reset filters on project change
  useEffect(() => {
    setSearchInput('');
    setPriorityFilter(null);
    setAgentFilter(null);
    setTagFilter(null);
  }, [currentProjectId]);

  const allTags = useMemo(() => {
    const tags = new Set<string>();
    boardCards.forEach((c) => c.tags.forEach((t) => { if (t) tags.add(t); }));
    return Array.from(tags).sort();
  }, [boardCards]);

  const filterMatchInfo = useMemo(() => {
    const isFiltered = query || priorityFilter !== null || agentFilter !== null || tagFilter !== null;
    if (!isFiltered) return null;
    const total = boardCards.length;
    const visible = boardCards.filter((card) => {
      if (query && !card.title.toLowerCase().includes(query.toLowerCase())) return false;
      if (priorityFilter !== null && card.priority !== priorityFilter) return false;
      if (agentFilter && (card.agentType || 'general') !== agentFilter) return false;
      if (tagFilter && !card.tags.some((t) => t.toLowerCase() === tagFilter.toLowerCase())) return false;
      return true;
    }).length;
    return { visible, total };
  }, [query, priorityFilter, agentFilter, tagFilter, boardCards]);

  // ── Dep graph overlay ─────────────────────────────────────────────────────

  const [depGraphOpen, setDepGraphOpen] = useState(false);

  // ── Multi-select state ────────────────────────────────────────────────────

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

  // ── Action handlers ───────────────────────────────────────────────────────

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

  const handleExport = useCallback(async () => {
    try {
      const data = await exportProject.mutateAsync(currentProjectId);
      const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `project-${currentProjectId}.json`;
      a.click();
      URL.revokeObjectURL(url);
      showToast('✅ Project exported', 'success');
    } catch {
      showToast('Export failed', 'error');
    }
  }, [currentProjectId, exportProject, showToast]);

  const handleImport = useCallback(async (file: File) => {
    try {
      const text = await file.text();
      const data = JSON.parse(text) as unknown;
      const result = await importProject.mutateAsync(data);
      showToast(`✅ Project imported: ${result.project_title}`, 'success');
    } catch {
      showToast('Import failed — check file format', 'error');
    }
  }, [importProject, showToast]);

  const handleCardClick = useCallback(
    (cardId: string) => selectCard(cardId),
    [selectCard],
  );

  const handleTagClick = useCallback(
    (tag: string) => setTagFilter((prev) => (prev === tag ? null : tag)),
    [],
  );

  // ── DnD: drag backlog card onto a Kanban drop zone ───────────────────────

  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 5 } }),
  );

  const [activeCard, setActiveCard] = useState<Card | null>(null);

  const handleDragStart = useCallback((event: DragStartEvent) => {
    const card = event.active.data.current?.card as Card | undefined;
    if (card) setActiveCard(card);
  }, []);

  const handleDragEnd = useCallback(
    async (event: DragEndEvent) => {
      const { active, over } = event;
      const draggedCard = active.data.current?.card as Card | undefined;
      setActiveCard(null);

      if (!draggedCard || !over) return;
      const targetStatus = over.data.current?.status as CardStatus | undefined;
      if (!targetStatus) return;
      if (draggedCard.status === targetStatus) return;

      // Optimistic update — mirrors KanbanBoard.handleDragOver pattern
      useCardStore.getState().moveCard(draggedCard.id, targetStatus);

      try {
        await patchCard.mutateAsync({
          cardId: draggedCard.id,
          updates: { status: targetStatus },
          projectId: draggedCard.projectId ?? currentProjectId,
        } as { cardId: string; updates: Record<string, unknown>; projectId?: string });
        showToast(`Moved to ${targetStatus}`, 'success');
      } catch {
        // Rollback
        useCardStore.getState().moveCard(draggedCard.id, 'card');
        showToast('Move failed', 'error');
      }
    },
    [patchCard, showToast, currentProjectId],
  );

  // Portal: render BoardHeader into the page-level slot when available (desktop split layout)
  const headerSlot = document.getElementById('board-header-slot');

  const boardHeader = (
    <BoardHeader
      searchInput={searchInput}
      onSearchChange={setSearchInput}
      priorityFilter={priorityFilter}
      onPriorityChange={setPriorityFilter}
      agentFilter={agentFilter}
      onAgentChange={setAgentFilter}
      tagFilter={tagFilter}
      onTagChange={setTagFilter}
      allTags={allTags}
      filterMatchInfo={filterMatchInfo}
      onNewCard={handleAddCard}
      onDepGraph={() => setDepGraphOpen(true)}
      onExport={handleExport}
      onImport={handleImport}
    />
  );

  return (
    <div className="flex flex-col h-full" data-testid="freeboard">
      {/* BoardHeader: portaled above split on desktop, inline on mobile */}
      {headerSlot ? createPortal(boardHeader, headerSlot) : boardHeader}

      <DndContext sensors={sensors} onDragStart={handleDragStart} onDragEnd={handleDragEnd}>
        {/* Kanban drop zones — only visible while dragging a backlog card */}
        {activeCard && (
          <div className="flex gap-2 px-4 pt-3">
            {KANBAN_DROP_TARGETS.map((t) => (
              <KanbanDropZone key={t.status} status={t.status} label={t.label} />
            ))}
          </div>
        )}

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
                <DraggableBacklogCard key={card.id} card={card}>
                  <KanbanCard
                    card={card}
                    selectMode={selectMode}
                    isSelected={selectedIds.has(card.id)}
                    onSelectChange={handleSelectChange}
                    query={query}
                    priorityFilter={priorityFilter}
                    agentFilter={agentFilter}
                    tagFilter={tagFilter}
                    onTagClick={handleTagClick}
                    onCardClick={handleCardClick}
                  />
                </DraggableBacklogCard>
              ))
            )}
          </div>

          {/* Archived cards */}
          <FreeBoardArchived projectId={currentProjectId} />
        </div>

        {/* Drag overlay — ghost of dragged card */}
        <DragOverlay>
          {activeCard ? (
            <div className="opacity-80 rotate-2 scale-105">
              <KanbanCard card={activeCard} query={query} />
            </div>
          ) : null}
        </DragOverlay>
      </DndContext>

      {/* Dependency graph overlay */}
      {depGraphOpen && (
        <DepGraphOverlay
          cards={boardCards}
          cardsById={cardsById}
          onClose={() => setDepGraphOpen(false)}
        />
      )}
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
