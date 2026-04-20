import React, { useState, useMemo, useCallback, useRef, useEffect } from 'react';
import { createPortal } from 'react-dom';
import {
  Archive, Play, Square, Link2, Trash2, X,
  AlertCircle, ChevronRight, ArrowUpDown,
} from 'lucide-react';
import {
  DndContext,
  DragOverlay,
  pointerWithin,
  PointerSensor,
  useSensor,
  useSensors,
  useDroppable,
  type DragStartEvent,
  type DragEndEvent,
  type DragOverEvent,
} from '@dnd-kit/core';
import {
  SortableContext,
  verticalListSortingStrategy,
  useSortable,
  arrayMove,
} from '@dnd-kit/sortable';
import { CSS } from '@dnd-kit/utilities';
import { cn } from '@/lib/utils';
import type { Card, CardStatus } from '../../types';
import { useCardStore } from '../../stores/useCardStore';
import { useProjectStore } from '../../stores/useProjectStore';
import { useToastStore } from '../../stores/useToastStore';
import { useCards, useDeleteCard, usePatchCard, useReorderCards, useCreateCard } from '../../hooks/api/useCards';
import { useExportProject, useImportProject, useExecuteBoardPlan } from '../../hooks/api/useProjects';
import { useWS } from '../../providers/WebSocketProvider';
import { useWorkerStatus } from '../../hooks/useWorkerStatus';
import { KanbanCard } from './KanbanCard';
import { Button } from '../ui/button';
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '../ui/dialog';
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from '../ui/dropdown-menu';
import { BoardHeader, useDebounce } from '../Board/BoardHeader';

// ── Constants ──────────────────────────────────────────────────────────────────

const COLUMN_STATUSES: CardStatus[] = ['todo', 'in-progress', 'done'];

const COLUMN_LABELS: Record<string, string> = {
  todo: 'Todo',
  'in-progress': 'In Progress',
  done: 'Done',
};

const COLUMN_DOT_COLORS: Record<string, string> = {
  todo: 'bg-slate-400',
  'in-progress': 'bg-orange-500',
  done: 'bg-emerald-500',
};

// ── Column sort ───────────────────────────────────────────────────────────────────────────────────

type SortOption = 'default' | 'newest' | 'oldest' | 'priority' | 'alpha';

const SORT_LABELS: Record<SortOption, string> = {
  default: 'Default',
  newest: 'Newest first',
  oldest: 'Oldest first',
  priority: 'Priority (high→low)',
  alpha: 'Alphabetical',
};

function sortCards(cards: Card[], sort: SortOption): Card[] {
  if (sort === 'default') return cards;
  const arr = [...cards];
  switch (sort) {
    case 'newest': return arr.sort((a, b) => b.createdAt - a.createdAt);
    case 'oldest': return arr.sort((a, b) => a.createdAt - b.createdAt);
    case 'priority': return arr.sort((a, b) => b.priority - a.priority);
    case 'alpha': return arr.sort((a, b) => a.title.localeCompare(b.title));
    default: return arr;
  }
}

// ── Sortable Card Wrapper ──────────────────────────────────────────────────────

interface SortableCardProps {
  card: Card;
  selectMode: boolean;
  isSelected: boolean;
  onSelectChange: (id: string, selected: boolean) => void;
  query: string;
  priorityFilter: number | null;
  agentFilter: string | null;
  tagFilter: string | null;
  onTagClick: (tag: string) => void;
  onCardClick: (cardId: string) => void;
  isExecuting: boolean;
  isWorkerActive: boolean;
}

function SortableCard({
  card,
  selectMode,
  isSelected,
  onSelectChange,
  query,
  priorityFilter,
  agentFilter,
  tagFilter,
  onTagClick,
  onCardClick,
  isExecuting,
  isWorkerActive,
}: SortableCardProps) {
  const { attributes, listeners, setNodeRef, transform, transition, isDragging } = useSortable({
    id: card.id,
    disabled: selectMode,
    data: { type: 'card', card },
  });

  const style: React.CSSProperties = {
    transform: CSS.Transform.toString(transform),
    transition,
    opacity: isDragging ? 0.4 : undefined,
  };

  return (
    <div ref={setNodeRef} style={style} {...attributes} {...listeners}>
      <div className={cn(isExecuting && 'ring-2 ring-yellow-400/60 rounded-lg animate-pulse')}>
        <KanbanCard
          card={card}
          selectMode={selectMode}
          isSelected={isSelected}
          onSelectChange={onSelectChange}
          query={query}
          priorityFilter={priorityFilter}
          agentFilter={agentFilter}
          tagFilter={tagFilter}
          onTagClick={onTagClick}
          onCardClick={onCardClick}
          isWorkerActive={isWorkerActive}
        />
      </div>
    </div>
  );
}

// ── KanbanColumn ───────────────────────────────────────────────────────────────

interface KanbanColumnProps {
  status: CardStatus;
  label: string;
  cards: Card[];
  selectMode: boolean;
  selectedIds: Set<string>;
  onSelectChange: (id: string, selected: boolean) => void;
  onSelectAll: (ids: string[]) => void;
  onClearAll: () => void;
  query: string;
  priorityFilter: number | null;
  agentFilter: string | null;
  tagFilter: string | null;
  onTagClick: (tag: string) => void;
  onCardClick: (cardId: string) => void;
  executingCardId: string | null;
  isCardActive: (cardId: string) => boolean;
  sortOption: SortOption;
  onSortChange: (sort: SortOption) => void;
}

function KanbanColumn({
  status,
  label,
  cards,
  selectMode,
  selectedIds,
  onSelectChange,
  onSelectAll,
  onClearAll,
  query,
  priorityFilter,
  agentFilter,
  tagFilter,
  onTagClick,
  onCardClick,
  executingCardId,
  isCardActive,
  sortOption,
  onSortChange,
}: KanbanColumnProps) {
  const sortedCards = useMemo(() => sortCards(cards, sortOption), [cards, sortOption]);
  const cardIds = useMemo(() => sortedCards.map((c) => c.id), [sortedCards]);
  const { setNodeRef } = useDroppable({ id: status });

  const allSelected = sortedCards.length > 0 && sortedCards.every((c) => selectedIds.has(c.id));
  const someSelected = sortedCards.some((c) => selectedIds.has(c.id));

  const selectAllRef = useRef<HTMLInputElement>(null);
  useEffect(() => {
    if (selectAllRef.current) {
      selectAllRef.current.indeterminate = someSelected && !allSelected;
    }
  }, [someSelected, allSelected]);

  const handleSelectAllToggle = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      e.stopPropagation();
      if (e.target.checked) {
        onSelectAll(sortedCards.map((c) => c.id));
      } else {
        sortedCards.forEach((c) => onSelectChange(c.id, false));
      }
    },
    [sortedCards, onSelectAll, onSelectChange],
  );

  const handleCardListClick = useCallback(
    (e: React.MouseEvent<HTMLDivElement>) => {
      if (!selectMode) return;
      const target = e.target as HTMLElement;
      // Deselect all when clicking the column background (not on a card)
      if (!target.closest('[data-testid="kanban-card"]')) {
        onClearAll();
      }
    },
    [selectMode, onClearAll],
  );

  return (
    <div
      ref={setNodeRef}
      className="group/col flex flex-col min-w-40 flex-1 rounded-xl bg-muted/40 border border-border/40"
      data-status={status}
      data-testid={`kanban-column-${status}`}
    >
      {/* Column header */}
      <div className="flex items-center justify-between px-3 py-2.5 border-b border-border/30">
        <div className="flex items-center gap-2">
          {/* Select All checkbox — hidden until hover or selectMode is active */}
          <div
            className={cn(
              'transition-opacity',
              selectMode || someSelected ? 'opacity-100' : 'opacity-0 group-hover/col:opacity-50',
            )}
            onClick={(e) => e.stopPropagation()}
            title={allSelected ? 'Deselect all in column' : 'Select all in column'}
          >
            <input
              ref={selectAllRef}
              type="checkbox"
              aria-label={`Select all cards in ${label}`}
              checked={allSelected}
              onChange={handleSelectAllToggle}
              className="w-3 h-3 rounded border-border accent-primary cursor-pointer"
            />
          </div>
          <span className={cn('w-2 h-2 rounded-full flex-shrink-0', COLUMN_DOT_COLORS[status])} />
          <span className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">{label}</span>
        </div>
        <div className="flex items-center gap-1">
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <button
                className={cn(
                  'p-0.5 rounded hover:bg-muted transition-colors focus:outline-none',
                  sortOption !== 'default' && 'text-primary',
                )}
                title="Sort column"
              >
                <ArrowUpDown size={12} className={cn('text-muted-foreground', sortOption !== 'default' && 'text-primary')} />
              </button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end" className="w-44">
              {(Object.keys(SORT_LABELS) as SortOption[]).map((opt) => (
                <DropdownMenuItem
                  key={opt}
                  onClick={() => onSortChange(opt)}
                  className={cn('text-xs cursor-pointer', sortOption === opt && 'font-semibold text-primary')}
                >
                  {SORT_LABELS[opt]}
                </DropdownMenuItem>
              ))}
            </DropdownMenuContent>
          </DropdownMenu>
          <span className="text-xs text-muted-foreground tabular-nums bg-muted/60 px-1.5 py-0.5 rounded-full min-w-[20px] text-center">{cards.length}</span>
        </div>
      </div>

      {/* Droppable card list */}
      <SortableContext items={cardIds} strategy={verticalListSortingStrategy}>
        <div
          className="flex flex-col gap-2 p-2 min-h-[80px] overflow-y-auto max-h-[calc(100vh-320px)]"
          onClick={handleCardListClick}
        >
          {sortedCards.length === 0 && (
            <div className="py-8 text-center text-xs text-muted-foreground">No cards</div>
          )}
          {sortedCards.map((card) => (
            <SortableCard
              key={card.id}
              card={card}
              selectMode={selectMode}
              isSelected={selectedIds.has(card.id)}
              onSelectChange={onSelectChange}
              query={query}
              priorityFilter={priorityFilter}
              agentFilter={agentFilter}
              tagFilter={tagFilter}
              onTagClick={onTagClick}
              onCardClick={onCardClick}
              isExecuting={executingCardId === card.id}
              isWorkerActive={isCardActive(card.id)}
            />
          ))}
        </div>
      </SortableContext>
    </div>
  );
}

// ── Dependency Graph Overlay ───────────────────────────────────────────────────

interface DepGraphOverlayProps {
  cards: Card[];
  cardsById: Record<string, Card>;
  onClose: () => void;
}

export function DepGraphOverlay({ cards, cardsById, onClose }: DepGraphOverlayProps) {
  const blockedCards = useMemo(
    () =>
      cards.filter(
        (c) =>
          c.dependencies.length > 0 &&
          c.dependencies.some((d) => {
            const dep = cardsById[d];
            return dep && dep.status !== 'done';
          }),
      ),
    [cards, cardsById],
  );

  const readyCards = useMemo(
    () =>
      cards.filter((c) => {
        if (c.status === 'done') return false;
        if (c.dependencies.length === 0) return true;
        return c.dependencies.every((d) => {
          const dep = cardsById[d];
          return dep && dep.status === 'done';
        });
      }),
    [cards, cardsById],
  );

  return (
    <Dialog open onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="max-w-lg max-h-[80vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2"><Link2 size={15} className="text-sky-400" /> Dependency Map</DialogTitle>
        </DialogHeader>

        {/* Blocked */}
        <div className="space-y-2">
          <h4 className="text-sm font-medium text-destructive flex items-center gap-1.5">
            <AlertCircle size={13} /> Blocked dependencies ({blockedCards.length})
          </h4>
          {blockedCards.length === 0 ? (
            <p className="text-xs text-muted-foreground">No blocked cards — great!</p>
          ) : (
            blockedCards.map((card) => (
              <div key={card.id} className="rounded border border-border/60 p-2 text-sm">
                <span className="font-medium">{card.title}</span>
                <ul className="mt-1 ml-4 list-disc text-xs text-muted-foreground">
                  {card.dependencies.map((depId) => {
                    const dep = cardsById[depId];
                    if (!dep || dep.status === 'done') return null;
                    return <li key={depId}>{dep.title}</li>;
                  })}
                </ul>
              </div>
            ))
          )}
        </div>

        {/* Ready */}
        <div className="space-y-2 mt-4">
          <h4 className="text-sm font-medium text-green-500 flex items-center gap-1.5">
            <Play size={13} /> Ready to work on ({readyCards.length})
          </h4>
          {readyCards.length === 0 ? (
            <p className="text-xs text-muted-foreground">No ready cards.</p>
          ) : (
            readyCards.map((card) => (
              <div key={card.id} className="rounded border border-border/60 p-2 text-sm">
                {card.title}
                {card.dependencies.length === 0 ? (
                  <span className="text-xs text-muted-foreground"> (no deps)</span>
                ) : (
                  <span className="text-xs text-muted-foreground"> (all deps done)</span>
                )}
              </div>
            ))
          )}
        </div>
      </DialogContent>
    </Dialog>
  );
}

// ── Bulk Action Toolbar ────────────────────────────────────────────────────────

interface BulkToolbarProps {
  selectedIds: Set<string>;
  onClear: () => void;
  onBulkMove: (status: CardStatus) => void;
  onBulkArchive: () => void;
  onBulkDelete: () => void;
}

function BulkToolbar({ selectedIds, onClear, onBulkMove, onBulkArchive, onBulkDelete }: BulkToolbarProps) {
  if (selectedIds.size === 0) return null;

  return (
    <div className="fixed bottom-4 left-1/2 -translate-x-1/2 z-50 flex items-center gap-2 rounded-xl border border-border bg-popover px-4 py-2.5 shadow-xl">
      <span className="text-sm font-medium text-foreground">{selectedIds.size} selected</span>
      <div className="h-4 w-px bg-border" />
      {(['todo', 'in-progress', 'done'] as CardStatus[]).map((s) => (
        <Button key={s} variant="ghost" size="sm" className="flex items-center gap-1" onClick={() => onBulkMove(s)}>
          <ChevronRight size={12} /> {COLUMN_LABELS[s]}
        </Button>
      ))}
      <div className="h-4 w-px bg-border" />
      <Button variant="ghost" size="sm" onClick={onBulkArchive} className="flex items-center gap-1.5">
        <Archive size={13} /> Archive
      </Button>
      <Button variant="ghost" size="sm" className="flex items-center gap-1.5 text-destructive" onClick={onBulkDelete}>
        <Trash2 size={13} /> Delete
      </Button>
      <div className="h-4 w-px bg-border" />
      <Button variant="ghost" size="sm" onClick={onClear} className="flex items-center gap-1.5">
        <X size={13} /> Clear
      </Button>
    </div>
  );
}


// ── Execution Progress Bar ─────────────────────────────────────────────────────

interface ExecutionProgressProps {
  index: number;
  total: number;
  cardTitle: string;
  onStop: () => void;
}

function ExecutionProgress({ index, total, cardTitle, onStop }: ExecutionProgressProps) {
  const pct = ((index + 1) / total) * 100;
  return (
    <div className="rounded-lg border border-yellow-500/40 bg-yellow-500/5 px-4 py-2 mb-3">
      <div className="flex items-center justify-between text-sm">
        <span className="text-foreground">
          Executing card {index + 1}/{total}: <strong>{cardTitle}</strong>
        </span>
        <Button variant="ghost" size="sm" onClick={onStop} className="flex items-center gap-1.5">
          <Square size={13} className="text-destructive" /> Stop
        </Button>
      </div>
      <div className="mt-1.5 h-1.5 rounded-full bg-muted overflow-hidden">
        <div
          className="h-full bg-yellow-500 transition-all duration-300"
          style={{ width: `${pct}%` }}
        />
      </div>
    </div>
  );
}

// ── Main KanbanBoard Component ─────────────────────────────────────────────────

export interface KanbanBoardProps {
  projectId?: string;
  onCardClick?: (cardId: string) => void;
}

export function KanbanBoard({ projectId: projectIdProp, onCardClick }: KanbanBoardProps) {
  const storeProjectId = useProjectStore((s) => s.currentProjectId);
  const selectCard = useProjectStore((s) => s.selectCard);
  const projectId = projectIdProp ?? storeProjectId;
  const cardsById = useCardStore((s) => s.cardsById);
  const setCardsForProject = useCardStore((s) => s.setCardsForProject);
  const updateCardStore = useCardStore((s) => s.updateCard);
  const deleteCardStore = useCardStore((s) => s.deleteCard);
  const showToast = useToastStore((s) => s.showToast);

  // API hooks
  const { data: fetchedCards } = useCards(projectId ?? '');
  const createCard = useCreateCard();
  const patchCard = usePatchCard();
  const reorderCards = useReorderCards();
  const exportProject = useExportProject();
  const importProject = useImportProject();
  const executeBoardPlan = useExecuteBoardPlan();
  const deleteCardMut = useDeleteCard();
  const { send: wsSend, subscribe } = useWS();

  // Worker execution status — poll every 3s to show per-card activity badges
  const { isCardActive } = useWorkerStatus(projectId ?? '');

  // Sync fetched cards into Zustand store
  useEffect(() => {
    if (projectId && fetchedCards) {
      setCardsForProject(projectId, fetchedCards);
    }
  }, [projectId, fetchedCards, setCardsForProject]);

  // ── Filter state ─────────────────────────────────────────────────────────

  const [searchInput, setSearchInput] = useState('');
  const query = useDebounce(searchInput, 200);
  const [priorityFilter, setPriorityFilter] = useState<number | null>(null);
  const [agentFilter, setAgentFilter] = useState<string | null>(null);
  const [tagFilter, setTagFilter] = useState<string | null>(null);
  const [columnSorts, setColumnSorts] = useState<Record<string, SortOption>>({});

  // Reset filters on project change
  useEffect(() => {
    setSearchInput('');
    setPriorityFilter(null);
    setAgentFilter(null);
    setTagFilter(null);
    setColumnSorts({});
  }, [projectId]);

  // ── Select mode ──────────────────────────────────────────────────────────

  const [selectMode, setSelectMode] = useState(false);
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());

  const handleSelectChange = useCallback((id: string, selected: boolean) => {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (selected) next.add(id);
      else next.delete(id);
      // Auto-enter/exit select mode based on selection count
      setSelectMode(next.size > 0);
      return next;
    });
  }, []);

  const clearSelection = useCallback(() => {
    setSelectedIds(new Set());
    setSelectMode(false);
  }, []);

  const handleSelectAll = useCallback((ids: string[]) => {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      ids.forEach((id) => next.add(id));
      setSelectMode(next.size > 0);
      return next;
    });
  }, []);

  // Escape key → clear selection
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape' && selectMode) {
        clearSelection();
      }
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [selectMode, clearSelection]);


  // ── Board execution state ────────────────────────────────────────────────

  const [executionActive, setExecutionActive] = useState(false);
  const [executionId, setExecutionId] = useState<string | null>(null);
  const [executionProgress, setExecutionProgress] = useState<{
    index: number;
    total: number;
    cardTitle: string;
    cardId: string;
  } | null>(null);

  // Listen for board execution WS events
  const executingCardId = executionProgress?.cardId ?? null;

  // ── Dep graph overlay ────────────────────────────────────────────────────

  const [depGraphOpen, setDepGraphOpen] = useState(false);

  // ── Cards by column ──────────────────────────────────────────────────────

  const projectCards = useMemo(() => {
    if (!projectId) return [];
    return Object.values(cardsById)
      .filter((c) => c.projectId === projectId && !c.archivedAt)
      .sort((a, b) => (a.position ?? 0) - (b.position ?? 0));
  }, [cardsById, projectId]);

  const cardsByColumn = useMemo(() => {
    const map: Record<string, Card[]> = {};
    for (const status of COLUMN_STATUSES) {
      map[status] = projectCards.filter((c) => c.status === status);
    }
    return map;
  }, [projectCards]);

  // All unique tags for tag filter chips
  const allTags = useMemo(() => {
    const tags = new Set<string>();
    projectCards.forEach((c) => c.tags.forEach((t) => { if (t) tags.add(t); }));
    return Array.from(tags).sort();
  }, [projectCards]);

  // Filter match count
  const filterMatchInfo = useMemo(() => {
    const isFiltered = query || priorityFilter !== null || agentFilter !== null || tagFilter !== null;
    if (!isFiltered) return null;

    let visible = 0;
    let total = 0;
    for (const status of COLUMN_STATUSES) {
      const cards = cardsByColumn[status] ?? [];
      total += cards.length;
      cards.forEach((card) => {
        if (query && !card.title.toLowerCase().includes(query.toLowerCase())) return;
        if (priorityFilter !== null && card.priority !== priorityFilter) return;
        if (agentFilter && (card.agentType || 'general') !== agentFilter) return;
        if (tagFilter && !card.tags.some((t) => t.toLowerCase() === tagFilter.toLowerCase())) return;
        visible++;
      });
    }
    return { visible, total };
  }, [query, priorityFilter, agentFilter, tagFilter, cardsByColumn]);

  // ── DnD sensors and handlers ─────────────────────────────────────────────

  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 5 } }),
  );

  const [activeCard, setActiveCard] = useState<Card | null>(null);
  const dragOriginStatusRef = useRef<CardStatus | null>(null);

  const handleDragStart = useCallback(
    (event: DragStartEvent) => {
      const card = event.active.data.current?.card as Card | undefined;
      if (card) {
        setActiveCard(card);
        dragOriginStatusRef.current = card.status;
      }
    },
    [],
  );

  const resolveTargetStatus = useCallback(
    (over: DragOverEvent['over']): CardStatus | null => {
      if (!over) return null;
      const overCard = over.data.current?.card as Card | undefined;
      const candidate = overCard?.status ?? (over.id as CardStatus);
      return COLUMN_STATUSES.includes(candidate) ? candidate : null;
    },
    [],
  );

  const handleDragOver = useCallback(
    (event: DragOverEvent) => {
      const { active, over } = event;
      if (!over || !active.data.current) return;

      const activeCard = active.data.current.card as Card | undefined;
      if (!activeCard) return;

      const targetStatus = resolveTargetStatus(over);
      if (targetStatus && activeCard.status !== targetStatus) {
        useCardStore.getState().moveCard(activeCard.id, targetStatus);
      }
    },
    [resolveTargetStatus],
  );

  const handleDragEnd = useCallback(
    async (event: DragEndEvent) => {
      const originStatus = dragOriginStatusRef.current;
      setActiveCard(null);
      dragOriginStatusRef.current = null;
      const { active, over } = event;

      const activeCardData = active.data.current?.card as Card | undefined;
      if (!activeCardData || !projectId) return;

      const targetStatus = resolveTargetStatus(over);

      // Rollback if dropped outside a valid column
      if (!targetStatus) {
        if (originStatus) {
          useCardStore.getState().moveCard(activeCardData.id, originStatus);
        }
        return;
      }

      // If moved to a new status column — persist via API
      if (originStatus && originStatus !== targetStatus) {
        try {
          await patchCard.mutateAsync({
            cardId: activeCardData.id,
            updates: { status: targetStatus },
            projectId,
          });
        } catch {
          // Roll back the optimistic status change applied in handleDragOver.
          useCardStore.getState().moveCard(activeCardData.id, originStatus);
          showToast('Move failed', 'error');
          return;
        }
        // If moved to Done, insert at the top of the Done column
        if (targetStatus === 'done') {
          const freshDoneCards = Object.values(useCardStore.getState().cardsById)
            .filter((c) => c.projectId === projectId && !c.archivedAt && c.status === 'done')
            .sort((a, b) => (a.position ?? 0) - (b.position ?? 0));
          const doneIds = [
            activeCardData.id,
            ...freshDoneCards.filter((c) => c.id !== activeCardData.id).map((c) => c.id),
          ];
          useCardStore.getState().reorderCards(doneIds);
          try { await reorderCards.mutateAsync(doneIds); } catch { /* non-critical */ }
          return;
        }
      }

      // Handle reorder within same column
      const overCard = over?.data.current?.card as Card | undefined;
      const columnCards = cardsByColumn[targetStatus] ?? [];
      const oldIndex = columnCards.findIndex((c) => c.id === activeCardData.id);
      const overIndex = overCard
        ? columnCards.findIndex((c) => c.id === overCard.id)
        : -1;

      if (oldIndex !== -1 && overIndex !== -1 && oldIndex !== overIndex) {
        const reordered = arrayMove(columnCards, oldIndex, overIndex);
        const previousOrder = columnCards.map((c) => c.id);
        const orderedIds = reordered.map((c) => c.id);
        useCardStore.getState().reorderCards(orderedIds);
        try {
          await reorderCards.mutateAsync(orderedIds);
        } catch {
          // Roll back the optimistic reorder.
          useCardStore.getState().reorderCards(previousOrder);
          showToast('Reorder failed', 'error');
        }
      }
    },
    [projectId, patchCard, reorderCards, cardsByColumn, resolveTargetStatus, showToast],
  );

  // ── Action handlers ──────────────────────────────────────────────────────

  const handleTagClick = useCallback(
    (tag: string) => {
      setTagFilter((prev) => (prev === tag ? null : tag));
    },
    [],
  );

  const handleNewCard = useCallback(async () => {
    if (!projectId) {
      showToast('Select a project first', 'info');
      return;
    }
    try {
      const newCard = await createCard.mutateAsync({ projectId, title: 'New card', status: 'todo' });
      useCardStore.setState((state) => ({
        cardsById: { ...state.cardsById, [newCard.id]: newCard },
      }));
      selectCard(newCard.id);
    } catch {
      showToast('Failed to create card', 'error');
    }
  }, [projectId, createCard, selectCard, showToast]);

  const handleExport = useCallback(async () => {
    if (!projectId) {
      showToast('Select a project first', 'info');
      return;
    }
    try {
      const data = await exportProject.mutateAsync(projectId);
      const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `project-${projectId}.json`;
      a.click();
      URL.revokeObjectURL(url);
      showToast('✅ Project exported', 'success');
    } catch {
      showToast('Export failed', 'error');
    }
  }, [projectId, exportProject, showToast]);

  const handleImport = useCallback(
    async (file: File) => {
      try {
        const text = await file.text();
        const data = JSON.parse(text) as unknown;
        const result = await importProject.mutateAsync(data);
        showToast(`✅ Project imported: ${result.project_title}`, 'success');
      } catch {
        showToast('Import failed — check file format', 'error');
      }
    },
    [importProject, showToast],
  );

  const handleExecuteBoard = useCallback(async () => {
    if (executionActive && executionId) {
      wsSend('kanban:execute:cancel', { executionId });
      return;
    }

    if (!projectId) {
      showToast('Select a project first', 'info');
      return;
    }

    try {
      const plan = await executeBoardPlan.mutateAsync(projectId);
      if (!plan || plan.total === 0) {
        showToast('No todo/in-progress cards to execute', 'info');
        return;
      }

      if (!confirm(`Execute ${plan.total} cards sequentially?\n\nCards will be processed in order and moved to Done when complete.`)) {
        return;
      }

      setExecutionActive(true);
      setExecutionId(plan.executionId);

      // Start execution via WebSocket
      const sessionId = 'board-exec-' + Date.now();
      wsSend('kanban:execute:start', { projectId, sessionId });
    } catch {
      showToast('Failed to get execution plan', 'error');
    }
  }, [executionActive, executionId, projectId, executeBoardPlan, showToast, wsSend]);

  const resetExecution = useCallback(() => {
    setExecutionActive(false);
    setExecutionId(null);
    setExecutionProgress(null);
  }, []);

  // Listen for WS board execution events
  useEffect(() => {
    const unsubs = [
      subscribe('kanban:execute:card:start', (payload) => {
        setExecutionProgress({
          index: payload.index as number,
          total: payload.total as number,
          cardTitle: payload.cardTitle as string,
          cardId: payload.cardId as string,
        });
      }),
      subscribe('kanban:execute:complete', resetExecution),
      subscribe('kanban:execute:cancelled', resetExecution),
      subscribe('kanban:execute:error', resetExecution),
    ];
    return () => unsubs.forEach((u) => u());
  }, [subscribe, resetExecution]);

  // ── Bulk actions ─────────────────────────────────────────────────────────

  const handleBulkMove = useCallback(
    (status: CardStatus) => {
      selectedIds.forEach((id) => {
        updateCardStore(id, { status });
        patchCard.mutate({ cardId: id, updates: { status }, projectId: projectId ?? undefined });
      });
      // If moving to Done, insert selected cards at the top of the Done column
      if (status === 'done') {
        const selectedArr = Array.from(selectedIds);
        const currentDoneCards = Object.values(useCardStore.getState().cardsById)
          .filter((c) => c.projectId === projectId && !c.archivedAt && c.status === 'done')
          .sort((a, b) => (a.position ?? 0) - (b.position ?? 0));
        const doneIds = [
          ...selectedArr,
          ...currentDoneCards.filter((c) => !selectedIds.has(c.id)).map((c) => c.id),
        ];
        useCardStore.getState().reorderCards(doneIds);
        reorderCards.mutate(doneIds);
      }
      showToast(`Moved ${selectedIds.size} cards to ${status}`, 'success');
      clearSelection();
    },
    [selectedIds, patchCard, reorderCards, updateCardStore, showToast, clearSelection, projectId],
  );

  const handleBulkArchive = useCallback(() => {
    selectedIds.forEach((id) => {
      deleteCardStore(id);
      patchCard.mutate({
        cardId: id,
        updates: { status: 'archived' as CardStatus },
        projectId: projectId ?? undefined,
      });
    });
    showToast(`Archived ${selectedIds.size} cards`, 'success');
    clearSelection();
  }, [selectedIds, patchCard, deleteCardStore, showToast, clearSelection, projectId]);

  const handleBulkDelete = useCallback(() => {
    if (!confirm(`Delete ${selectedIds.size} cards permanently? This cannot be undone.`)) return;
    selectedIds.forEach((id) => {
      deleteCardStore(id);
      deleteCardMut.mutate({ cardId: id, projectId: projectId ?? undefined });
    });
    showToast(`Deleted ${selectedIds.size} cards`, 'success');
    clearSelection();
  }, [selectedIds, deleteCardMut, deleteCardStore, projectId, showToast, clearSelection]);

  const handleCardClickInternal = useCallback(
    (cardId: string) => {
      onCardClick?.(cardId);
    },
    [onCardClick],
  );

  // ── Render ───────────────────────────────────────────────────────────────

  if (!projectId) {
    return (
      <div className="flex items-center justify-center h-64 text-muted-foreground text-sm">
        Select a project to view its board
      </div>
    );
  }

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
      onNewCard={handleNewCard}
      onDepGraph={() => setDepGraphOpen(true)}
      onExport={handleExport}
      onImport={handleImport}
      extraActions={
        <Button
          variant={executionActive ? 'destructive' : 'outline'}
          size="sm"
          className="h-6 px-2 shrink-0"
          title={executionActive ? 'Stop board execution' : 'Execute all todo/in-progress cards'}
          onClick={handleExecuteBoard}
        >
          {executionActive
            ? <Square size={12} />
            : <Play size={12} className="text-emerald-400" />}
        </Button>
      }
    />
  );

  return (
    <div className="flex flex-col h-full overflow-hidden" data-testid="kanban-board">
      {/* BoardHeader: portaled above split on desktop, inline on mobile */}
      {headerSlot ? createPortal(boardHeader, headerSlot) : boardHeader}

      {/* Execution progress */}
      {executionActive && executionProgress && (
        <ExecutionProgress
          index={executionProgress.index}
          total={executionProgress.total}
          cardTitle={executionProgress.cardTitle}
          onStop={() => {
            if (executionId) wsSend('kanban:execute:cancel', { executionId });
          }}
        />
      )}

      {/* Board columns with DnD */}
      <DndContext
        sensors={sensors}
        collisionDetection={pointerWithin}
        onDragStart={handleDragStart}
        onDragOver={handleDragOver}
        onDragEnd={handleDragEnd}
      >
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3 flex-1 overflow-auto p-3">
          {COLUMN_STATUSES.map((status) => (
            <KanbanColumn
              key={status}
              status={status}
              label={COLUMN_LABELS[status]}
              cards={cardsByColumn[status] ?? []}
              selectMode={selectMode}
              selectedIds={selectedIds}
              onSelectChange={handleSelectChange}
              onSelectAll={handleSelectAll}
              onClearAll={clearSelection}
              query={query}
              priorityFilter={priorityFilter}
              agentFilter={agentFilter}
              tagFilter={tagFilter}
              onTagClick={handleTagClick}
              onCardClick={handleCardClickInternal}
              executingCardId={executingCardId}
              isCardActive={isCardActive}
              sortOption={columnSorts[status] ?? 'default'}
              onSortChange={(sort) => setColumnSorts((prev) => ({ ...prev, [status]: sort }))}
            />
          ))}
        </div>

        {/* Drag overlay — renders a ghost of the dragged card */}
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
          cards={projectCards}
          cardsById={cardsById}
          onClose={() => setDepGraphOpen(false)}
        />
      )}

      {/* Bulk action toolbar */}
      {selectMode && (
        <BulkToolbar
          selectedIds={selectedIds}
          onClear={clearSelection}
          onBulkMove={handleBulkMove}
          onBulkArchive={handleBulkArchive}
          onBulkDelete={handleBulkDelete}
        />
      )}
    </div>
  );
}
