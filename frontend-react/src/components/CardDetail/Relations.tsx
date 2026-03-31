/**
 * RelationsSection — card relations (relates_to, blocks, is_blocked_by, duplicates, cloned_from).
 * Port of the vanilla buildRelationsSection().
 */

import { useState, useMemo } from 'react';
import { cn } from '@/lib/utils';
import type { CardRelation, CardRelationType } from '../../types';
import { useRelations, useAddRelation, useDeleteRelation } from '../../hooks/api/useCards';
import { useCardStore } from '../../stores/useCardStore';
import { useToastStore } from '../../stores/useToastStore';

// ── Constants ────────────────────────────────────────────────────────────────

const RELATION_TYPES: CardRelationType[] = [
  'relates_to',
  'blocks',
  'is_blocked_by',
  'duplicates',
  'cloned_from',
];

const RELATION_ICON: Record<string, string> = {
  duplicates: '📋',
  duplicated_by: '📋',
  blocks: '🚫',
  is_blocked_by: '⛔',
  relates_to: '🔗',
  cloned_from: '🧬',
  cloned_to: '🧬',
};

const RELATION_LABEL: Record<string, string> = {
  duplicates: 'Duplicates',
  duplicated_by: 'Duplicated by',
  blocks: 'Blocks',
  is_blocked_by: 'Blocked by',
  relates_to: 'Relates to',
  cloned_from: 'Cloned from',
  cloned_to: 'Cloned to',
};

const BADGE_COLOR: Record<string, string> = {
  duplicates: 'bg-amber-500/15 text-amber-400',
  duplicated_by: 'bg-amber-500/15 text-amber-400',
  blocks: 'bg-red-500/15 text-red-400',
  is_blocked_by: 'bg-orange-500/15 text-orange-400',
  relates_to: 'bg-blue-500/15 text-blue-400',
  cloned_from: 'bg-purple-500/15 text-purple-400',
  cloned_to: 'bg-purple-500/15 text-purple-400',
};

const STATUS_DOT: Record<string, string> = {
  idea: 'bg-slate-400',
  todo: 'bg-blue-400',
  'in-progress': 'bg-amber-400',
  done: 'bg-emerald-400',
  archived: 'bg-gray-500',
};

// ── Component ────────────────────────────────────────────────────────────────

interface Props {
  cardId: string;
  projectId?: string;
}

export function RelationsSection({ cardId, projectId }: Props) {
  const { data: relations = [], isLoading } = useRelations(cardId);
  const addRelation = useAddRelation();
  const deleteRelation = useDeleteRelation();
  const cardsById = useCardStore((s) => s.cardsById);
  const showToast = useToastStore((s) => s.showToast);

  const [selectedCard, setSelectedCard] = useState('');
  const [selectedType, setSelectedType] = useState<CardRelationType>('relates_to');

  const projectCards = useMemo(
    () => projectId
      ? Object.values(cardsById).filter((c) => c.projectId === projectId && c.id !== cardId)
      : [],
    [cardsById, projectId, cardId],
  );

  const handleAdd = () => {
    if (!selectedCard) return;
    addRelation.mutate(
      { cardId, targetCardId: selectedCard, relationType: selectedType },
      {
        onSuccess: () => setSelectedCard(''),
        onError: () => showToast('Could not add relation', 'error'),
      },
    );
  };

  const handleDelete = (rel: CardRelation) => {
    deleteRelation.mutate(
      { cardId, relationId: rel.id },
      { onError: () => showToast('Could not remove relation', 'error') },
    );
  };

  return (
    <div className="space-y-2">
      <span className="text-xs font-medium text-muted-foreground">
        🔗 Related Cards ({relations.length})
      </span>

      {/* List */}
      <div className="space-y-1">
        {isLoading && (
          <p className="text-xs text-muted-foreground/60">Loading…</p>
        )}
        {!isLoading && relations.length === 0 && (
          <p className="text-xs text-muted-foreground/60">No relations yet.</p>
        )}
        {relations.map((rel) => (
          <div
            key={rel.id}
            className="flex items-center gap-1.5 rounded-md border border-border px-2 py-1 text-xs"
          >
            <span>{RELATION_ICON[rel.relationType] ?? '🔗'}</span>
            <span
              className={cn(
                'rounded px-1.5 py-0.5 text-[10px] font-medium',
                BADGE_COLOR[rel.relationType] ?? 'bg-muted text-muted-foreground',
              )}
            >
              {RELATION_LABEL[rel.relationType] ?? rel.relationType}
            </span>
            <span
              className={cn('h-2 w-2 rounded-full', STATUS_DOT[rel.relatedCardStatus] ?? 'bg-gray-500')}
              title={rel.relatedCardStatus}
            />
            <span className="flex-1 truncate text-foreground">{rel.relatedCardTitle}</span>
            <button
              type="button"
              onClick={() => handleDelete(rel)}
              className="ml-auto text-muted-foreground/60 hover:text-red-400"
              title="Remove relation"
            >
              ×
            </button>
          </div>
        ))}
      </div>

      {/* Add row */}
      {projectCards.length > 0 ? (
        <div className="flex items-center gap-1">
          <select
            value={selectedCard}
            onChange={(e) => setSelectedCard(e.target.value)}
            className="flex-1 rounded-md border border-border bg-transparent px-1.5 py-1 text-xs outline-none"
          >
            <option value="" disabled>
              Select card…
            </option>
            {projectCards.map((c) => (
              <option key={c.id} value={c.id}>
                {c.status === 'done' ? '✅' : '⏳'} {c.title}
              </option>
            ))}
          </select>
          <select
            value={selectedType}
            onChange={(e) => setSelectedType(e.target.value as CardRelationType)}
            className="rounded-md border border-border bg-transparent px-1.5 py-1 text-xs outline-none"
          >
            {RELATION_TYPES.map((t) => (
              <option key={t} value={t}>
                {RELATION_ICON[t]} {RELATION_LABEL[t]}
              </option>
            ))}
          </select>
          <button
            type="button"
            onClick={handleAdd}
            disabled={!selectedCard || addRelation.isPending}
            className="rounded-md border border-border px-2 py-1 text-xs font-medium text-muted-foreground transition-colors hover:bg-muted disabled:opacity-50"
          >
            {addRelation.isPending ? '…' : '+ Add'}
          </button>
        </div>
      ) : (
        <p className="text-xs text-muted-foreground/60">No other cards in this project</p>
      )}
    </div>
  );
}
