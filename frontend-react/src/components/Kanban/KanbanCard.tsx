import React, { useMemo, useCallback, useState } from 'react';
import { Pin, Copy, Pencil, FolderInput, Archive, Timer, Play, CheckSquare, Link2, Folder } from 'lucide-react';
import { cn } from '@/lib/utils';
import type { Card } from '../../types';
import { useCardStore } from '../../stores/useCardStore';
import { useProjectStore } from '../../stores/useProjectStore';
import { useToastStore } from '../../stores/useToastStore';
import { useChatService } from '../../contexts/useChatService';
import {
  usePatchCard,
  useDuplicateCard,
  useArchiveCard,
  useCloneCard,
  useMoveCard,
  useExecuteCard,
} from '../../hooks/api/useCards';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuSub,
  DropdownMenuSubContent,
  DropdownMenuSubTrigger,
  DropdownMenuTrigger,
} from '../ui/dropdown-menu';
import { Bot, Search, Code2, Paintbrush, Building2, PenLine, FlaskConical, type LucideIcon } from 'lucide-react';

const AGENT_ICONS: Record<string, LucideIcon> = {
  general:    Bot,
  researcher: Search,
  coder:      Code2,
  designer:   Paintbrush,
  architect:  Building2,
  writer:     PenLine,
  qa:         FlaskConical,
};

const AGENT_COLORS: Record<string, string> = {
  general:    'text-slate-400',
  researcher: 'text-blue-400',
  coder:      'text-emerald-400',
  designer:   'text-pink-400',
  architect:  'text-orange-400',
  writer:     'text-violet-400',
  qa:         'text-amber-400',
};

// ── Card color classes ───────────────────────────────────────────────────────

const CARD_COLOR_CLASSES: Record<string, string> = {
  yellow: 'bg-yellow-500/10 border-yellow-500/30',
  blue:   'bg-blue-500/10   border-blue-500/30',
  green:  'bg-green-500/10  border-green-500/30',
  pink:   'bg-pink-500/10   border-pink-500/30',
  purple: 'bg-purple-500/10 border-purple-500/30',
  orange: 'bg-orange-500/10 border-orange-500/30',
};

const CARD_COLOR_DOT: Record<string, string> = {
  yellow: 'bg-yellow-400',
  blue:   'bg-blue-400',
  green:  'bg-green-400',
  pink:   'bg-pink-400',
  purple: 'bg-purple-400',
  orange: 'bg-orange-400',
};

// ── Tag color helpers ────────────────────────────────────────────────────────

const TAG_COLORS: Array<[string, string]> = [
  ['rgba(255, 107, 107, 0.18)', '#ff6b6b'],
  ['rgba(78, 205, 196, 0.18)', '#4ecdc4'],
  ['rgba(255, 183, 77, 0.18)', '#ffb74d'],
  ['rgba(66, 165, 245, 0.18)', '#42a5f5'],
  ['rgba(171, 145, 249, 0.18)', '#ab91f9'],
  ['rgba(102, 187, 106, 0.18)', '#66bb6a'],
  ['rgba(255, 138, 101, 0.18)', '#ff8a65'],
  ['rgba(236, 64, 122, 0.18)', '#ec407a'],
];

function stringHash(s: string): number {
  let hash = 0;
  for (let i = 0; i < s.length; i++) {
    hash = (hash * 31 + s.charCodeAt(i)) >>> 0;
  }
  return hash;
}

function getTagColor(tag: string): [string, string] {
  return TAG_COLORS[stringHash(tag) % TAG_COLORS.length];
}

function highlightText(text: string, query: string): React.ReactNode {
  if (!query) return text;
  const escaped = query.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  const parts = text.split(new RegExp(`(${escaped})`, 'gi'));
  return parts.map((part, i) =>
    i % 2 === 1 ? (
      <mark key={i} className="bg-yellow-400/40 text-inherit rounded-sm">
        {part}
      </mark>
    ) : (
      part
    )
  );
}

// ── Props ────────────────────────────────────────────────────────────────────

export interface KanbanCardProps {
  card: Card;
  /** Multi-select mode: checkbox visible, drag disabled */
  selectMode?: boolean;
  isSelected?: boolean;
  onSelectChange?: (id: string, selected: boolean) => void;
  /** Search/filter criteria — card returns null when it doesn't match */
  query?: string;
  priorityFilter?: number | null;
  agentFilter?: string | null;
  tagFilter?: string | null;
  onTagClick?: (tag: string) => void;
  /** Called when the card body or Edit menu item is clicked */
  onCardClick?: (cardId: string) => void;
  /** True when a worker is actively executing this card */
  isWorkerActive?: boolean;
}

// ── Component ────────────────────────────────────────────────────────────────

export function KanbanCard({
  card,
  selectMode = false,
  isSelected = false,
  onSelectChange,
  query = '',
  priorityFilter = null,
  agentFilter = null,
  tagFilter = null,
  onTagClick,
  onCardClick,
  isWorkerActive = false,
}: KanbanCardProps) {
  const [isDragging, setIsDragging] = useState(false);

  const showToast = useToastStore((s) => s.showToast);
  const { executeCard: executeCardWS } = useChatService();
  const projects = useProjectStore((s) => s.projects);
  const { selectCard } = useProjectStore();
  const cardsById = useCardStore((s) => s.cardsById);
  const deleteCardStore = useCardStore((s) => s.deleteCard);

  const patchCard = usePatchCard();
  const duplicateCard = useDuplicateCard();
  const archiveCard = useArchiveCard();

  const cloneCard = useCloneCard();
  const moveCard = useMoveCard();
  const executeCard = useExecuteCard();

  // ── Visibility filter ────────────────────────────────────────────────────

  const isVisible = useMemo(() => {
    if (query && !card.title.toLowerCase().includes(query.toLowerCase())) return false;
    if (priorityFilter !== null && card.priority !== priorityFilter) return false;
    if (agentFilter && (card.agentType || 'general') !== agentFilter) return false;
    if (tagFilter && !card.tags.some((t) => t.toLowerCase() === tagFilter.toLowerCase())) return false;
    return true;
  }, [card, query, priorityFilter, agentFilter, tagFilter]);

  // ── Dependency / blocked state ────────────────────────────────────────────

  const isBlocked = useMemo(() => {
    return card.dependencies.some((id) => {
      const dep = cardsById[id];
      return dep && dep.status !== 'done';
    });
  }, [card.dependencies, cardsById]);

  const depTooltip = useMemo(() => {
    return card.dependencies
      .map((id) => {
        const dep = cardsById[id];
        return dep ? `${dep.status === 'done' ? '✓' : '○'} ${dep.title}` : '(unknown card)';
      })
      .join('\n');
  }, [card.dependencies, cardsById]);

  // ── Other projects for Clone/Move submenus ───────────────────────────────

  const otherProjects = useMemo(
    () => projects.filter((p) => p.id !== card.projectId && !p.archived),
    [projects, card.projectId]
  );

  // ── Event handlers ────────────────────────────────────────────────────────

  const handleCardClick = useCallback(
    (e: React.MouseEvent) => {
      if ((e.target as HTMLElement).closest('[data-checkbox]')) return;
      if (selectMode) {
        onSelectChange?.(card.id, !isSelected);
        return;
      }
      selectCard(card.id);
      onCardClick?.(card.id);
    },
    [selectMode, isSelected, onSelectChange, card.id, selectCard, onCardClick]
  );

  const handleDragStart = useCallback(
    (e: React.DragEvent) => {
      if (selectMode) {
        e.preventDefault();
        return;
      }
      e.dataTransfer.setData('text/plain', card.id);
      e.dataTransfer.effectAllowed = 'move';
      setIsDragging(true);
    },
    [selectMode, card.id]
  );

  const handleExecute = async () => {
    try {
      await executeCard.mutateAsync(card.id);
      executeCardWS(card.id, card.projectId || undefined);
      showToast(`Executing: "${card.title}"`, 'success');
    } catch {
      showToast('Execution failed', 'error');
    }
  };

  const handleMoveToBacklog = async () => {
    try {
      await patchCard.mutateAsync({
        cardId: card.id,
        updates: { status: 'card' },
        projectId: card.projectId ?? undefined,
      });
      showToast('Card moved to Backlog', 'success');
    } catch {
      showToast('Move failed', 'error');
    }
  };

  const handleMoveToKanban = async () => {
    try {
      await patchCard.mutateAsync({
        cardId: card.id,
        updates: { status: 'todo' },
        projectId: card.projectId ?? undefined,
      });
      showToast('Card moved to Kanban (Todo)', 'success');
    } catch {
      showToast('Move failed', 'error');
    }
  };

  const handleDuplicate = async () => {
    try {
      await duplicateCard.mutateAsync({ cardId: card.id, projectId: card.projectId ?? undefined });
      showToast(`Duplicated: "${card.title}"`, 'success');
    } catch {
      showToast('Duplication failed', 'error');
    }
  };

  const handleCopyId = async () => {
    try {
      await navigator.clipboard.writeText(card.id);
      showToast('Card ID copied!', 'success');
    } catch {
      showToast('Failed to copy ID', 'error');
    }
  };

  const handleArchive = async () => {
    try {
      deleteCardStore(card.id);
      await archiveCard.mutateAsync({ cardId: card.id, projectId: card.projectId ?? undefined });
      showToast(`"${card.title}" archived`, 'success');
    } catch {
      showToast('Archive failed', 'error');
    }
  };


  const handleCloneTo = async (projectId: string, projectTitle: string) => {
    try {
      await cloneCard.mutateAsync({
        cardId: card.id,
        targetProjectId: projectId,
        sourceProjectId: card.projectId ?? undefined,
      });
      showToast(`Cloned to "${projectTitle}"`, 'success');
    } catch {
      showToast('Clone failed', 'error');
    }
  };

  const handleMoveTo = async (projectId: string, projectTitle: string) => {
    try {
      await moveCard.mutateAsync({
        cardId: card.id,
        targetProjectId: projectId,
        sourceProjectId: card.projectId ?? undefined,
      });
      showToast(`✈️ Moved to "${projectTitle}"`, 'success');
    } catch {
      showToast('Move failed', 'error');
    }
  };

  // ── Hidden when filtered out ──────────────────────────────────────────────

  if (!isVisible) return null;

  // ── Derived display values ────────────────────────────────────────────────

  const agentType = card.agentType || 'general';
  const AgentIcon = AGENT_ICONS[agentType] ?? null;
  const agentIconColor = AGENT_COLORS[agentType] ?? 'text-muted-foreground';
  const showAgentBadge = agentType !== 'general';

  const visibleTags = card.tags.slice(0, 3);
  const hiddenTagCount = card.tags.length - visibleTags.length;

  let timeLabel: string | null = null;
  if (card.totalMinutes && card.totalMinutes > 0) {
    const h = Math.floor(card.totalMinutes / 60);
    const m = card.totalMinutes % 60;
    timeLabel = h > 0 ? `${h}h${m > 0 ? ` ${m}m` : ''}` : `${m}m`;
  }

  // ── Render ────────────────────────────────────────────────────────────────

  return (
    <div
      className={cn(
        'group/card relative rounded-lg border border-border/60 bg-card p-3',
        'cursor-pointer select-none transition-all duration-150',
        'hover:shadow-md hover:shadow-black/20',
        card.color && CARD_COLOR_CLASSES[card.color],
        !card.color && 'hover:border-border',
        isDragging && 'opacity-40 scale-95',
        isSelected && 'border-primary/60 ring-1 ring-primary/40 bg-primary/5',
        isBlocked && 'border-orange-500/40 bg-orange-500/5',
      )}
      draggable={!selectMode}
      data-testid="kanban-card"
      data-card-id={card.id}
      data-card-status={card.status}
      onClick={handleCardClick}
      onDragStart={handleDragStart}
      onDragEnd={() => setIsDragging(false)}
    >
      {/* Worker execution indicator badge */}
      {isWorkerActive && (
        <div className="absolute top-1.5 right-1.5 flex items-center gap-1 z-20">
          <span className="relative flex h-2.5 w-2.5">
            <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-75"></span>
            <span className="relative inline-flex rounded-full h-2.5 w-2.5 bg-emerald-500"></span>
          </span>
        </div>
      )}

      {/* Header: title + actions button */}
      <div className={cn('flex items-start gap-2', selectMode && 'checked')}>
        {/* Selection checkbox — always visible in selectMode, shown on hover otherwise */}
        <div
          data-checkbox="true"
          className={cn(
            'transition-opacity z-10',
            selectMode ? 'opacity-100' : 'opacity-60',
          )}
          onClick={(e) => e.stopPropagation()}
        >
          <input
            type="checkbox"
            aria-label={`Select card: ${card.title}`}
            checked={isSelected}
            onChange={(e) => {
              e.stopPropagation();
              onSelectChange?.(card.id, e.target.checked);
            }}
            className="w-3.5 h-3.5 rounded border-border accent-primary cursor-pointer"
          />
        </div>
        {card.color && CARD_COLOR_DOT[card.color] && (
          <span className={cn('mt-1.5 flex-shrink-0 w-2 h-2 rounded-full', CARD_COLOR_DOT[card.color])} />
        )}
        <div className="flex-1 min-w-0">
          <div
            data-testid="kanban-card-title"
            className="text-[0.8125rem] font-medium text-foreground leading-snug break-words"
          >
            {query ? highlightText(card.title, query) : card.title}
          </div>
        </div>

        {/* ··· actions button — visible on hover */}
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <button
              onPointerDown={(e) => e.stopPropagation()}
              onClick={(e) => e.stopPropagation()}
              className={cn(
                'flex-shrink-0 px-1.5 py-0.5 rounded text-muted-foreground text-sm',
                'opacity-60 hover:opacity-100 transition-opacity',
                'hover:bg-accent hover:text-accent-foreground',
              )}
              title="Card actions"
            >
              ···
            </button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end" className="w-48">
            <DropdownMenuItem onSelect={handleExecute}>
              <Play size={13} className="text-emerald-400" /> Execute
            </DropdownMenuItem>
            {card.status !== 'card' && (
              <DropdownMenuItem onSelect={handleMoveToBacklog}>
                <Pin size={13} className="text-blue-400" /> Move to Backlog
              </DropdownMenuItem>
            )}
            {card.status === 'card' && (
              <DropdownMenuItem onSelect={handleMoveToKanban}>
                <Pin size={13} className="text-blue-400" /> Move to Kanban
              </DropdownMenuItem>
            )}
            <DropdownMenuItem onSelect={handleDuplicate}>
              <Copy size={13} className="text-violet-400" /> Duplicate
            </DropdownMenuItem>
            <DropdownMenuItem onSelect={handleCopyId}>
              <Copy size={13} className="text-muted-foreground" /> Copy Card ID
            </DropdownMenuItem>
            <DropdownMenuItem
              onSelect={() => {
                selectCard(card.id);
                onCardClick?.(card.id);
              }}
            >
              <Pencil size={13} className="text-amber-400" /> Edit
            </DropdownMenuItem>
            <DropdownMenuSeparator />

            {/* Clone to Project */}
            <DropdownMenuSub>
              <DropdownMenuSubTrigger disabled={otherProjects.length === 0}>
                <Copy size={13} className="text-violet-400" /> Clone to Project
              </DropdownMenuSubTrigger>
              <DropdownMenuSubContent>
                {otherProjects.map((p) => (
                  <DropdownMenuItem key={p.id} onSelect={() => handleCloneTo(p.id, p.name)}>
                    {p.emoji ? <span>{p.emoji}</span> : <Folder size={13} />} {p.name}
                  </DropdownMenuItem>
                ))}
              </DropdownMenuSubContent>
            </DropdownMenuSub>

            {/* Move to Project */}
            <DropdownMenuSub>
              <DropdownMenuSubTrigger disabled={otherProjects.length === 0}>
                <FolderInput size={13} className="text-orange-400" /> Move to Project
              </DropdownMenuSubTrigger>
              <DropdownMenuSubContent>
                {otherProjects.map((p) => (
                  <DropdownMenuItem key={p.id} onSelect={() => handleMoveTo(p.id, p.name)}>
                    {p.emoji ? <span>{p.emoji}</span> : <Folder size={13} />} {p.name}
                  </DropdownMenuItem>
                ))}
              </DropdownMenuSubContent>
            </DropdownMenuSub>

            <DropdownMenuSeparator />

            <DropdownMenuItem onSelect={handleArchive}>
              <Archive size={13} className="text-muted-foreground" /> Archive
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      </div>

      {/* Description preview */}
      {card.description && (
        <p className="mt-1.5 text-[0.6875rem] text-muted-foreground leading-relaxed line-clamp-4">
          {card.description}
        </p>
      )}

      {/* Footer: badges */}
      {(showAgentBadge ||
        card.tags.length > 0 ||
        timeLabel ||
        (card.checklistProgress && card.checklistProgress.total > 0) ||
        card.dependencies.length > 0) && (
        <div className="mt-2 flex flex-wrap items-center gap-1.5">
          {/* Agent badge */}
          {showAgentBadge && AgentIcon && (
            <span title={agentType} className="leading-none">
              <AgentIcon size={13} className={agentIconColor} />
            </span>
          )}

          {/* Tag pills — max 3 visible, then "+N" */}
          {visibleTags.map((tag) => {
            const [bg, color] = getTagColor(tag);
            return (
              <span
                key={tag}
                title={tag}
                style={{ background: bg, color }}
                className="px-1.5 py-0.5 rounded text-[0.625rem] font-medium cursor-pointer leading-none"
                onClick={(e) => {
                  e.stopPropagation();
                  onTagClick?.(tag);
                }}
              >
                {tag}
              </span>
            );
          })}
          {hiddenTagCount > 0 && (
            <span className="text-[0.625rem] text-muted-foreground font-medium">
              +{hiddenTagCount}
            </span>
          )}

          {/* Time tracking badge */}
          {timeLabel && (
            <span
              title={`${card.totalMinutes} minutes logged`}
              className="flex items-center gap-0.5 text-[0.625rem] text-muted-foreground font-medium"
            >
              <Timer size={10} /> {timeLabel}
            </span>
          )}

          {/* Checklist progress badge */}
          {card.checklistProgress && card.checklistProgress.total > 0 && (
            <span
              title={`Checklist: ${card.checklistProgress.completed}/${card.checklistProgress.total} completed`}
              className={cn(
                'text-[0.625rem] font-medium',
                card.checklistProgress.completed === card.checklistProgress.total
                  ? 'text-green-400'
                  : 'text-muted-foreground',
              )}
            >
              <CheckSquare size={10} className="inline-block" /> {card.checklistProgress.completed}/{card.checklistProgress.total}
            </span>
          )}

          {/* Dependencies badge */}
          {card.dependencies.length > 0 && (
            <span
              title={depTooltip}
              className={cn(
                'text-[0.625rem] font-medium',
                isBlocked ? 'text-orange-400' : 'text-muted-foreground',
              )}
            >
              <Link2 size={10} className="inline-block" /> {card.dependencies.length}
            </span>
          )}
        </div>
      )}
    </div>
  );
}
