import React, { useState, useMemo, useRef, useEffect, useCallback } from 'react';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { cn } from '@/lib/utils';
import { useProjectStore } from '../../stores/useProjectStore';
import { useToastStore } from '../../stores/useToastStore';
import { SYSTEM_PROJECT_ID } from '../../stores/useCardStore';
import { useCards, usePatchCard, useDeleteCard, useMoveCard, cardKeys } from '../../hooks/api/useCards';
import { AGENT_TYPE_EMOJI, AGENT_PERSONAS } from '../../lib/constants';
import type { Card } from '../../types';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '../ui/dropdown-menu';

// ── Color config ──────────────────────────────────────────────────────────────

type CardColor = 'yellow' | 'blue' | 'green' | 'pink' | 'purple' | 'orange';

const COLOR_OPTIONS: { value: CardColor | null; label: string }[] = [
  { value: null,     label: 'None'   },
  { value: 'yellow', label: 'Yellow' },
  { value: 'blue',   label: 'Blue'   },
  { value: 'green',  label: 'Green'  },
  { value: 'pink',   label: 'Pink'   },
  { value: 'purple', label: 'Purple' },
  { value: 'orange', label: 'Orange' },
];

const COLOR_CARD_CLASSES: Record<CardColor, string> = {
  yellow: 'bg-yellow-500/10 border-yellow-500/30',
  blue:   'bg-blue-500/10   border-blue-500/30',
  green:  'bg-green-500/10  border-green-500/30',
  pink:   'bg-pink-500/10   border-pink-500/30',
  purple: 'bg-purple-500/10 border-purple-500/30',
  orange: 'bg-orange-500/10 border-orange-500/30',
};

const COLOR_DOT_CLASSES: Record<CardColor, string> = {
  yellow: 'bg-yellow-400',
  blue:   'bg-blue-400',
  green:  'bg-green-400',
  pink:   'bg-pink-400',
  purple: 'bg-purple-400',
  orange: 'bg-orange-400',
};

const COLOR_SWATCH_CLASSES: Record<CardColor, string> = {
  yellow: 'bg-yellow-400 hover:ring-yellow-400',
  blue:   'bg-blue-400   hover:ring-blue-400',
  green:  'bg-green-400  hover:ring-green-400',
  pink:   'bg-pink-400   hover:ring-pink-400',
  purple: 'bg-purple-400 hover:ring-purple-400',
  orange: 'bg-orange-400 hover:ring-orange-400',
};

// ── Status labels ─────────────────────────────────────────────────────────────

const CARD_STATUS_LABELS: Record<string, string> = {
  todo:        'To Do',
  'in-progress': 'In Progress',
  done:        'Done',
  archived:    'Archived',
};

// ── Sub-components ────────────────────────────────────────────────────────────

interface FreeBoardCardProps {
  card: Card;
  onCardClick: (cardId: string) => void;
  onMoveToKanban: (card: Card) => void;
  onDelete: (card: Card) => void;
  otherProjects: Array<{ id: string; name: string; emoji?: string }>;
  onAssignToProject: (card: Card, projectId: string, projectName: string) => void;
  onNewProject: (card: Card) => void;
}

function FreeBoardCard({
  card,
  onCardClick,
  onMoveToKanban,
  onDelete,
  otherProjects,
  onAssignToProject,
  onNewProject,
}: FreeBoardCardProps) {
  const color = card.color as CardColor | null | undefined;

  let agentEmoji: string | null = null;
  if (card.agentType && card.agentType !== 'general') {
    agentEmoji = AGENT_TYPE_EMOJI[card.agentType] ?? null;
  } else if (!card.agentType && card.assignedAgent) {
    agentEmoji = AGENT_PERSONAS[card.assignedAgent]?.emoji ?? null;
  }

  const handleClick = (e: React.MouseEvent) => {
    // Don't open modal when clicking action buttons
    if ((e.target as HTMLElement).closest('[data-actions]')) return;
    onCardClick(card.id);
  };

  return (
    <div
      className={cn(
        'group/fbc relative rounded-lg border bg-card p-3 cursor-pointer select-none',
        'transition-all duration-150 hover:shadow-md hover:shadow-black/20',
        color ? COLOR_CARD_CLASSES[color] : 'border-border/60 hover:border-border',
      )}
      data-card-id={card.id}
      onClick={handleClick}
    >
      {/* Title row with optional color dot */}
      <div className="flex items-start gap-1.5 min-w-0">
        {color && (
          <span
            className={cn('mt-1 flex-shrink-0 w-2 h-2 rounded-full', COLOR_DOT_CLASSES[color])}
          />
        )}
        <span className="text-[13px] font-medium text-foreground leading-snug break-words flex-1">
          {card.title}
        </span>
      </div>

      {/* Description */}
      {card.description && (
        <p className="mt-1.5 text-[11px] text-muted-foreground leading-relaxed line-clamp-3">
          {card.description}
        </p>
      )}

      {/* Footer badges */}
      {(
        (card.status !== 'card' && card.status !== 'idea') ||
        agentEmoji ||
        (card.checklistProgress && card.checklistProgress.total > 0)
      ) && (
        <div className="mt-2 flex flex-wrap items-center gap-1.5">
          {card.status !== 'card' && card.status !== 'idea' && (
            <span
              className={cn(
                'px-1.5 py-0.5 rounded text-[10px] font-medium',
                card.status === 'done'
                  ? 'bg-green-500/20 text-green-400'
                  : card.status === 'in-progress'
                  ? 'bg-blue-500/20 text-blue-400'
                  : 'bg-muted text-muted-foreground',
              )}
            >
              {CARD_STATUS_LABELS[card.status] ?? card.status}
            </span>
          )}

          {agentEmoji && (
            <span title={card.agentType ?? card.assignedAgent ?? ''} className="text-sm leading-none">
              {agentEmoji}
            </span>
          )}

          {card.checklistProgress && card.checklistProgress.total > 0 && (
            <span
              title={`Checklist: ${card.checklistProgress.completed}/${card.checklistProgress.total}`}
              className={cn(
                'text-[10px] font-medium',
                card.checklistProgress.completed === card.checklistProgress.total
                  ? 'text-green-400'
                  : 'text-muted-foreground',
              )}
            >
              ☑ {card.checklistProgress.completed}/{card.checklistProgress.total}
            </span>
          )}
        </div>
      )}

      {/* Hover actions */}
      <div
        data-actions="true"
        className={cn(
          'absolute top-2 right-2 flex gap-1',
          'opacity-0 group-hover/fbc:opacity-100 transition-opacity',
        )}
      >
        {/* Assign to project */}
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <button
              onClick={(e) => e.stopPropagation()}
              className="w-6 h-6 flex items-center justify-center rounded text-sm hover:bg-accent transition-colors"
              title="Assign to Project"
            >
              🚀
            </button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end" className="w-44">
            {otherProjects.length === 0 ? (
              <DropdownMenuItem disabled>No projects yet</DropdownMenuItem>
            ) : (
              otherProjects.map((p) => (
                <DropdownMenuItem
                  key={p.id}
                  onSelect={() => onAssignToProject(card, p.id, p.name)}
                >
                  <span>{p.emoji ?? '📁'}</span> {p.name}
                </DropdownMenuItem>
              ))
            )}
            <DropdownMenuSeparator />
            <DropdownMenuItem onSelect={() => onNewProject(card)}>
              + New Project
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>

        {/* Move to Kanban */}
        <button
          onClick={(e) => { e.stopPropagation(); onMoveToKanban(card); }}
          className="w-6 h-6 flex items-center justify-center rounded text-sm hover:bg-accent transition-colors"
          title="Move to Kanban"
        >
          📋
        </button>

        {/* Delete */}
        <button
          onClick={(e) => { e.stopPropagation(); onDelete(card); }}
          className="w-6 h-6 flex items-center justify-center rounded text-sm hover:bg-destructive/20 hover:text-destructive transition-colors text-muted-foreground"
          title="Delete"
        >
          ✕
        </button>
      </div>
    </div>
  );
}

// ── Add form ──────────────────────────────────────────────────────────────────

interface AddCardFormProps {
  onSubmit: (title: string, description: string, color: CardColor | null) => void;
  onCancel: () => void;
}

function AddCardForm({ onSubmit, onCancel }: AddCardFormProps) {
  const [title, setTitle] = useState('');
  const [description, setDescription] = useState('');
  const [selectedColor, setSelectedColor] = useState<CardColor | null>(null);
  const titleRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    titleRef.current?.focus();
  }, []);

  const handleSubmit = () => {
    const trimmed = title.trim();
    if (!trimmed) {
      titleRef.current?.focus();
      return;
    }
    onSubmit(trimmed, description.trim(), selectedColor);
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSubmit();
    } else if (e.key === 'Escape') {
      onCancel();
    }
  };

  return (
    <div className="rounded-lg border border-border bg-card p-3 flex flex-col gap-2">
      <input
        ref={titleRef}
        type="text"
        value={title}
        onChange={(e) => setTitle(e.target.value)}
        onKeyDown={handleKeyDown}
        placeholder="Card title..."
        className={cn(
          'w-full bg-transparent text-[13px] text-foreground placeholder:text-muted-foreground',
          'border-b border-border/60 pb-1.5 focus:outline-none focus:border-border',
        )}
      />
      <textarea
        value={description}
        onChange={(e) => setDescription(e.target.value)}
        onKeyDown={(e) => { if (e.key === 'Escape') onCancel(); }}
        placeholder="Details (optional)..."
        rows={3}
        className={cn(
          'w-full bg-transparent text-[11px] text-foreground placeholder:text-muted-foreground',
          'resize-none focus:outline-none',
        )}
      />

      {/* Color selector */}
      <div className="flex items-center gap-2">
        <span className="text-[11px] text-muted-foreground">Color:</span>
        {/* None swatch */}
        <button
          type="button"
          title="None"
          onClick={() => setSelectedColor(null)}
          className={cn(
            'w-5 h-5 rounded-full border border-border bg-muted transition-all',
            'hover:ring-2 hover:ring-offset-1 hover:ring-border',
            selectedColor === null && 'ring-2 ring-offset-1 ring-primary',
          )}
        />
        {COLOR_OPTIONS.filter(o => o.value !== null).map(({ value, label }) => (
          <button
            key={value}
            type="button"
            title={label}
            onClick={() => setSelectedColor(value)}
            className={cn(
              'w-5 h-5 rounded-full transition-all ring-offset-background',
              COLOR_SWATCH_CLASSES[value as CardColor],
              'hover:ring-2 hover:ring-offset-1',
              selectedColor === value && 'ring-2 ring-offset-1',
            )}
          />
        ))}
      </div>

      {/* Actions row */}
      <div className="flex items-center gap-2 justify-end pt-1">
        <button
          type="button"
          onClick={onCancel}
          className="px-3 py-1 text-[12px] text-muted-foreground hover:text-foreground transition-colors"
        >
          Cancel
        </button>
        <button
          type="button"
          onClick={handleSubmit}
          className={cn(
            'px-3 py-1 text-[12px] rounded bg-primary text-primary-foreground',
            'hover:bg-primary/90 transition-colors',
          )}
        >
          Add card
        </button>
      </div>
    </div>
  );
}

// ── Main component ────────────────────────────────────────────────────────────

export function FreeBoard() {
  const qc = useQueryClient();

  const currentProjectId = useProjectStore((s) => s.currentProjectId) ?? SYSTEM_PROJECT_ID;
  const projects = useProjectStore((s) => s.projects);
  const selectCard = useProjectStore((s) => s.selectCard);
  const showToast = useToastStore((s) => s.showToast);

  const { data: cards = [], isLoading } = useCards(currentProjectId);

  const boardCards = useMemo(
    () =>
      cards
        .filter((c) => c.status === 'card' || c.status === 'idea')
        .sort((a, b) => b.createdAt - a.createdAt),
    [cards],
  );

  const otherProjects = useMemo(
    () =>
      projects.filter((p) => !p.archived && p.id !== SYSTEM_PROJECT_ID),
    [projects],
  );

  const [showForm, setShowForm] = useState(false);

  const patchCard = usePatchCard();
  const deleteCard = useDeleteCard();
  const moveCard = useMoveCard();

  // Create card with optional color — useCreateCard doesn't expose color, so inline
  const createCard = useMutation({
    mutationFn: async (data: { title: string; description: string; color: CardColor | null }) => {
      const res = await fetch(`/api/projects/${currentProjectId}/cards`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          title: data.title,
          description: data.description || '',
          color: data.color ?? null,
          priority: 0,
          status: 'card',
        }),
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      return res.json();
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: cardKeys.byProject(currentProjectId) });
    },
  });

  const handleFormSubmit = useCallback(
    async (title: string, description: string, color: CardColor | null) => {
      setShowForm(false);
      try {
        await createCard.mutateAsync({ title, description, color });
      } catch {
        showToast('Failed to create card', 'error');
      }
    },
    [createCard, showToast],
  );

  const handleCardClick = useCallback(
    (cardId: string) => {
      selectCard(cardId);
      // Modal wiring will be completed in a later migration step
    },
    [selectCard],
  );

  const handleMoveToKanban = useCallback(
    async (card: Card) => {
      try {
        await patchCard.mutateAsync({ cardId: card.id, updates: { status: 'todo' } });
        showToast('Card moved to Kanban', 'success');
      } catch {
        showToast('Failed to move card', 'error');
      }
    },
    [patchCard, showToast],
  );

  const handleDelete = useCallback(
    async (card: Card) => {
      if (!confirm(`Delete "${card.title}"? This cannot be undone.`)) return;
      try {
        await deleteCard.mutateAsync({ cardId: card.id, projectId: card.projectId ?? undefined });
      } catch {
        showToast('Failed to delete card', 'error');
      }
    },
    [deleteCard, showToast],
  );

  const handleAssignToProject = useCallback(
    async (card: Card, projectId: string, projectName: string) => {
      try {
        await moveCard.mutateAsync({
          cardId: card.id,
          targetProjectId: projectId,
          sourceProjectId: card.projectId ?? undefined,
        });
        showToast(`Card moved to ${projectName}`, 'success');
      } catch {
        showToast('Failed to assign card', 'error');
      }
    },
    [moveCard, showToast],
  );

  const handleNewProject = useCallback((_card: Card) => {
    // Project form integration will be wired when ProjectForm is migrated
    showToast('Use the Projects panel to create a new project', 'info');
  }, [showToast]);

  return (
    <div className="flex flex-col h-full" data-testid="freeboard">
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-2 border-b border-border/40">
        <button
          onClick={() => setShowForm((v) => !v)}
          data-testid="freeboard-add-btn"
          className={cn(
            'px-3 py-1.5 text-[13px] rounded border border-border/60',
            'text-muted-foreground hover:text-foreground hover:border-border',
            'hover:bg-accent transition-all',
            showForm && 'bg-accent text-foreground border-border',
          )}
        >
          + Add Card
        </button>
      </div>

      {/* Grid */}
      <div className="flex-1 overflow-y-auto p-4">
        <div className="grid grid-cols-[repeat(auto-fill,minmax(200px,1fr))] gap-3">
          {/* Add form at the top */}
          {showForm && (
            <AddCardForm
              onSubmit={handleFormSubmit}
              onCancel={() => setShowForm(false)}
            />
          )}

          {isLoading ? (
            <div className="col-span-full flex flex-col items-center justify-center py-16 text-muted-foreground">
              <div className="text-3xl mb-2">🗒️</div>
              <div className="text-sm">Loading...</div>
            </div>
          ) : boardCards.length === 0 && !showForm ? (
            <div className="col-span-full flex flex-col items-center justify-center py-16 text-muted-foreground">
              <div className="text-3xl mb-2">🗒️</div>
              <div className="text-sm">No cards yet. Add one!</div>
            </div>
          ) : (
            boardCards.map((card) => (
              <FreeBoardCard
                key={card.id}
                card={card}
                onCardClick={handleCardClick}
                onMoveToKanban={handleMoveToKanban}
                onDelete={handleDelete}
                otherProjects={otherProjects}
                onAssignToProject={handleAssignToProject}
                onNewProject={handleNewProject}
              />
            ))
          )}
        </div>
      </div>
    </div>
  );
}
