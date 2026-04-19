import React, { useState, useMemo, useCallback, useRef, useEffect } from 'react';
import { createPortal } from 'react-dom';
import {
  Archive, Play, Square, Link2, Trash2, RotateCcw, X,
  AlertCircle, ChevronRight, Search,
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
import { useCards, useArchivedCards, useRestoreCard, useDeleteCard, usePatchCard, useReorderCards, useCreateCard } from '../../hooks/api/useCards';
import { useExportProject, useImportProject, useExecuteBoardPlan } from '../../hooks/api/useProjects';
import { useWS } from '../../providers/WebSocketProvider';
import { useWorkerStatus } from '../../hooks/useWorkerStatus';
import { KanbanCard } from './KanbanCard';
import { Button } from '../ui/button';
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '../ui/dialog';
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
  query: string;
  priorityFilter: number | null;
  agentFilter: string | null;
  tagFilter: string | null;
  onTagClick: (tag: string) => void;
  onCardClick: (cardId: string) => void;
  executingCardId: string | null;
  isCardActive: (cardId: string) => boolean;
}

function KanbanColumn({
  status,
  label,
  cards,
  selectMode,
  selectedIds,
  onSelectChange,
  query,
  priorityFilter,
  agentFilter,
  tagFilter,
  onTagClick,
  onCardClick,
  executingCardId,
  isCardActive,
}: KanbanColumnProps) {
  const cardIds = useMemo(() => cards.map((c) => c.id), [cards]);
  const { setNodeRef } = useDroppable({ id: status });

  return (
    <div
      ref={setNodeRef}
      className="flex flex-col min-w-40 flex-1 rounded-xl bg-muted/40 border border-border/40"
      data-status={status}
      data-testid={`kanban-column-${status}`}
    >
      {/* Column header */}
      <div className="flex items-center justify-between px-3 py-2.5 border-b border-border/30">
        <div className="flex items-center gap-2">
          <span className={cn('w-2 h-2 rounded-full flex-shrink-0', COLUMN_DOT_COLORS[status])} />
          <span className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">{label}</span>
        </div>
        <span className="text-xs text-muted-foreground tabular-nums bg-muted/60 px-1.5 py-0.5 rounded-full min-w-[20px] text-center">{cards.length}</span>
      </div>

      {/* Droppable card list */}
      <SortableContext items={cardIds} strategy={verticalListSortingStrategy}>
        <div className="flex flex-col gap-2 p-2 min-h-[80px] overflow-y-auto max-h-[calc(100vh-320px)]">
          {cards.length === 0 && (
            <div className="py-8 text-center text-xs text-muted-foreground">No cards</div>
          )}
          {cards.map((card) => (
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

// ── Archived Section helpers ──────────────────────────────────────────────────

const PRIORITY_LABELS: Record<number, { label: string; color: string; bg: string }> = {
  0: { label: 'Low',      color: 'text-green-400',  bg: 'bg-green-500/10'  },
  1: { label: 'Medium',   color: 'text-yellow-400', bg: 'bg-yellow-500/10' },
  2: { label: 'High',     color: 'text-orange-400', bg: 'bg-orange-500/10' },
  3: { label: 'Critical', color: 'text-red-400',    bg: 'bg-red-500/10'    },
};

const ARCHIVE_COLOR_CLASSES: Record<string, string> = {
  yellow: 'border-yellow-500/30 bg-yellow-500/5',
  blue:   'border-blue-500/30   bg-blue-500/5',
  green:  'border-green-500/30  bg-green-500/5',
  pink:   'border-pink-500/30   bg-pink-500/5',
  purple: 'border-purple-500/30 bg-purple-500/5',
  orange: 'border-orange-500/30 bg-orange-500/5',
};

const ARCHIVE_COLOR_DOT: Record<string, string> = {
  yellow: 'bg-yellow-400',
  blue:   'bg-blue-400',
  green:  'bg-green-400',
  pink:   'bg-pink-400',
  purple: 'bg-purple-400',
  orange: 'bg-orange-400',
};

const ARCHIVE_TAG_COLORS: Array<[string, string]> = [
  ['rgba(255,107,107,0.18)', '#ff6b6b'],
  ['rgba(78,205,196,0.18)',  '#4ecdc4'],
  ['rgba(255,183,77,0.18)',  '#ffb74d'],
  ['rgba(66,165,245,0.18)',  '#42a5f5'],
  ['rgba(171,145,249,0.18)', '#ab91f9'],
  ['rgba(102,187,106,0.18)', '#66bb6a'],
  ['rgba(255,138,101,0.18)', '#ff8a65'],
  ['rgba(236,64,122,0.18)',  '#ec407a'],
];

function archiveTagColor(tag: string): [string, string] {
  let h = 0;
  for (let i = 0; i < tag.length; i++) h = (h * 31 + tag.charCodeAt(i)) >>> 0;
  return ARCHIVE_TAG_COLORS[h % ARCHIVE_TAG_COLORS.length];
}

function timeAgo(dateStr: string | null | undefined): string {
  if (!dateStr) return '';
  const diff = Date.now() - new Date(dateStr).getTime();
  const mins  = Math.floor(diff / 60_000);
  const hours = Math.floor(diff / 3_600_000);
  const days  = Math.floor(diff / 86_400_000);
  if (days > 0)  return `archivé il y a ${days} jour${days > 1 ? 's' : ''}`;
  if (hours > 0) return `archivé il y a ${hours} heure${hours > 1 ? 's' : ''}`;
  if (mins > 0)  return `archivé il y a ${mins} min`;
  return "archivé à l'instant";
}

type ArchiveSortKey = 'archivedAt' | 'priority' | 'title';

// ── Archived Section ──────────────────────────────────────────────────────────

interface ArchivedSectionProps {
  projectId: string;
}

function ArchivedSection({ projectId }: ArchivedSectionProps) {
  const [open, setOpen] = useState(false);
  const [searchQuery, setSearchQuery] = useState('');
  const [priorityFilter, setPriorityFilter] = useState<number | null>(null);
  const [dateFilter, setDateFilter] = useState<'all' | '7d' | '30d' | '90d'>('all');
  const [sortKey, setSortKey] = useState<ArchiveSortKey>('archivedAt');

  const { data: archivedCards, isLoading } = useArchivedCards(projectId);
  const restoreCard = useRestoreCard();
  const deleteCard = useDeleteCard();
  const showToast = useToastStore((s) => s.showToast);

  const filteredAndSorted = useMemo(() => {
    if (!archivedCards) return [];
    const now = Date.now();
    const thresholds: Record<string, number> = {
      '7d':  now - 7  * 86_400_000,
      '30d': now - 30 * 86_400_000,
      '90d': now - 90 * 86_400_000,
    };
    return [...archivedCards]
      .filter((card) => {
        if (searchQuery && !card.title.toLowerCase().includes(searchQuery.toLowerCase())) return false;
        if (priorityFilter !== null && card.priority !== priorityFilter) return false;
        if (dateFilter !== 'all' && card.archivedAt) {
          if (new Date(card.archivedAt).getTime() < thresholds[dateFilter]) return false;
        }
        return true;
      })
      .sort((a, b) => {
        if (sortKey === 'title')    return a.title.localeCompare(b.title);
        if (sortKey === 'priority') return (b.priority ?? 0) - (a.priority ?? 0);
        const at = a.archivedAt ? new Date(a.archivedAt).getTime() : 0;
        const bt = b.archivedAt ? new Date(b.archivedAt).getTime() : 0;
        return bt - at;
      });
  }, [archivedCards, searchQuery, priorityFilter, dateFilter, sortKey]);

  return (
    <div className="mt-4 border-t border-border/30 pt-3">
      {/* Toggle row */}
      <button
        className="flex items-center gap-2 text-sm text-muted-foreground hover:text-foreground transition-colors px-2 py-1 w-full"
        onClick={() => setOpen((o) => !o)}
      >
        <Archive size={14} />
        <span>Archived Cards</span>
        {archivedCards && archivedCards.length > 0 && (
          <span className="text-xs bg-muted/60 px-1.5 py-0.5 rounded-full tabular-nums ml-0.5">
            {archivedCards.length}
          </span>
        )}
        <ChevronRight size={12} className={cn('transition-transform ml-auto', open && 'rotate-90')} />
      </button>

      {open && (
        <div className="mt-3 space-y-3 px-2 pb-4">

          {/* ── Toolbar ── */}
          <div className="flex flex-wrap gap-2 items-center">
            {/* Search */}
            <div className="relative flex-1 min-w-[160px]">
              <Search size={13} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-muted-foreground pointer-events-none" />
              <input
                type="text"
                placeholder="Rechercher…"
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                className="w-full pl-7 pr-7 py-1.5 text-xs bg-muted/40 border border-border/40 rounded-md text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-1 focus:ring-primary/40"
              />
              {searchQuery && (
                <button
                  onClick={() => setSearchQuery('')}
                  className="absolute right-2 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground"
                >
                  <X size={11} />
                </button>
              )}
            </div>

            {/* Priority filter */}
            <select
              value={priorityFilter ?? ''}
              onChange={(e) => setPriorityFilter(e.target.value === '' ? null : Number(e.target.value))}
              className="px-2 py-1.5 text-xs bg-muted/40 border border-border/40 rounded-md text-foreground focus:outline-none focus:ring-1 focus:ring-primary/40 cursor-pointer"
            >
              <option value="">Toutes priorités</option>
              <option value="3">Critical</option>
              <option value="2">High</option>
              <option value="1">Medium</option>
              <option value="0">Low</option>
            </select>

            {/* Date filter */}
            <select
              value={dateFilter}
              onChange={(e) => setDateFilter(e.target.value as typeof dateFilter)}
              className="px-2 py-1.5 text-xs bg-muted/40 border border-border/40 rounded-md text-foreground focus:outline-none focus:ring-1 focus:ring-primary/40 cursor-pointer"
            >
              <option value="all">Toute la période</option>
              <option value="7d">7 derniers jours</option>
              <option value="30d">30 derniers jours</option>
              <option value="90d">90 derniers jours</option>
            </select>

            {/* Sort */}
            <select
              value={sortKey}
              onChange={(e) => setSortKey(e.target.value as ArchiveSortKey)}
              className="px-2 py-1.5 text-xs bg-muted/40 border border-border/40 rounded-md text-foreground focus:outline-none focus:ring-1 focus:ring-primary/40 cursor-pointer"
            >
              <option value="archivedAt">Trier: Date archivage</option>
              <option value="priority">Trier: Priorité</option>
              <option value="title">Trier: Titre</option>
            </select>
          </div>

          {/* Match count when filters active */}
          {(searchQuery || priorityFilter !== null || dateFilter !== 'all') && (
            <div className="text-xs text-muted-foreground px-0.5">
              {filteredAndSorted.length} / {archivedCards?.length ?? 0} carte{filteredAndSorted.length !== 1 ? 's' : ''}
            </div>
          )}

          {/* Loading */}
          {isLoading && <div className="text-xs text-muted-foreground py-2 px-1">Chargement…</div>}

          {/* Empty state */}
          {!isLoading && filteredAndSorted.length === 0 && (
            <div className="text-xs text-muted-foreground py-6 text-center">
              {archivedCards?.length === 0
                ? 'Aucune carte archivée'
                : 'Aucune carte ne correspond aux filtres'}
            </div>
          )}

          {/* ── Card grid ── */}
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-2">
            {filteredAndSorted.map((card) => {
              const pri = PRIORITY_LABELS[card.priority ?? 0];
              const visibleTags = card.tags.slice(0, 3);
              const hiddenTagCount = card.tags.length - visibleTags.length;

              return (
                <div
                  key={card.id}
                  className={cn(
                    'group relative rounded-lg border border-border/40 bg-card/60 p-3',
                    'transition-all duration-150 hover:border-border/70 hover:shadow-md hover:shadow-black/10',
                    card.color && ARCHIVE_COLOR_CLASSES[card.color],
                  )}
                >
                  {/* Header: color dot + title */}
                  <div className="flex items-start gap-2">
                    {card.color && ARCHIVE_COLOR_DOT[card.color] && (
                      <span className={cn('mt-1.5 flex-shrink-0 w-2 h-2 rounded-full', ARCHIVE_COLOR_DOT[card.color])} />
                    )}
                    <span className="flex-1 text-[0.8125rem] font-medium text-foreground/80 leading-snug break-words line-clamp-2">
                      {card.title}
                    </span>
                  </div>

                  {/* Priority + tags row */}
                  <div className="mt-1.5 flex flex-wrap items-center gap-1.5">
                    {pri && (
                      <span className={cn('px-1.5 py-0.5 rounded text-[0.625rem] font-medium leading-none', pri.bg, pri.color)}>
                        {pri.label}
                      </span>
                    )}
                    {visibleTags.map((tag) => {
                      const [bg, color] = archiveTagColor(tag);
                      return (
                        <span
                          key={tag}
                          title={tag}
                          style={{ background: bg, color }}
                          className="px-1.5 py-0.5 rounded text-[0.625rem] font-medium leading-none"
                        >
                          {tag}
                        </span>
                      );
                    })}
                    {hiddenTagCount > 0 && (
                      <span className="text-[0.625rem] text-muted-foreground font-medium">+{hiddenTagCount}</span>
                    )}
                  </div>

                  {/* Archive date */}
                  {card.archivedAt && (
                    <div className="mt-1.5 text-[0.625rem] text-muted-foreground/70 leading-none">
                      {timeAgo(card.archivedAt)}
                    </div>
                  )}

                  {/* Hover overlay with action buttons */}
                  <div className={cn(
                    'absolute inset-0 rounded-lg flex items-center justify-center gap-2',
                    'opacity-0 group-hover:opacity-100 transition-opacity duration-150',
                    'bg-card/85 backdrop-blur-[2px]',
                  )}>
                    <Button
                      variant="outline"
                      size="sm"
                      className="h-7 px-2.5 text-xs gap-1.5 text-emerald-400 border-emerald-500/40 hover:bg-emerald-500/10 hover:border-emerald-500/60"
                      onClick={async (e) => {
                        e.stopPropagation();
                        try {
                          await restoreCard.mutateAsync({ cardId: card.id, projectId });
                          showToast(`"${card.title}" restored`, 'success');
                        } catch {
                          showToast('Restore failed', 'error');
                        }
                      }}
                    >
                      <RotateCcw size={12} /> Restore
                    </Button>
                    <Button
                      variant="outline"
                      size="sm"
                      className="h-7 px-2.5 text-xs gap-1.5 text-destructive border-destructive/30 hover:bg-destructive/10"
                      onClick={async (e) => {
                        e.stopPropagation();
                        if (!confirm(`Permanently delete "${card.title}"? This cannot be undone.`)) return;
                        try {
                          await deleteCard.mutateAsync({ cardId: card.id, projectId });
                          showToast(`"${card.title}" permanently deleted`, 'success');
                        } catch {
                          showToast('Delete failed', 'error');
                        }
                      }}
                    >
                      <Trash2 size={12} /> Delete
                    </Button>
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      )}
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

  // Reset filters on project change
  useEffect(() => {
    setSearchInput('');
    setPriorityFilter(null);
    setAgentFilter(null);
    setTagFilter(null);
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
      showToast(`Moved ${selectedIds.size} cards to ${status}`, 'success');
      clearSelection();
    },
    [selectedIds, patchCard, updateCardStore, showToast, clearSelection, projectId],
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
              query={query}
              priorityFilter={priorityFilter}
              agentFilter={agentFilter}
              tagFilter={tagFilter}
              onTagClick={handleTagClick}
              onCardClick={handleCardClickInternal}
              executingCardId={executingCardId}
              isCardActive={isCardActive}
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

      {/* Archived cards */}
      <ArchivedSection projectId={projectId} />

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
