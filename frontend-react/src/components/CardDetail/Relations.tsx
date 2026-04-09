/**
 * RelationsSection — card relations (relates_to, blocks, is_blocked_by, duplicates, cloned_from).
 * Port of the vanilla buildRelationsSection().
 */

import { useState, useMemo, useRef, useEffect } from 'react';
import { X, Link2, Copy, ShieldAlert, ShieldX, GitBranch, Search, Plus, type LucideIcon } from 'lucide-react';
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

const RELATION_ICON: Record<string, LucideIcon> = {
  duplicates:   Copy,
  duplicated_by: Copy,
  blocks:       ShieldAlert,
  is_blocked_by: ShieldX,
  relates_to:   Link2,
  cloned_from:  GitBranch,
  cloned_to:    GitBranch,
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
  card: 'bg-slate-400',
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

  const [search, setSearch] = useState('');
  const [selectedType, setSelectedType] = useState<CardRelationType>('relates_to');
  const [showDropdown, setShowDropdown] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  // Already-related card IDs for filtering
  const relatedIds = useMemo(
    () => new Set(relations.map((r) => r.relatedCardId)),
    [relations],
  );

  const projectCards = useMemo(
    () => projectId
      ? Object.values(cardsById).filter((c) => c.projectId === projectId && c.id !== cardId && !relatedIds.has(c.id))
      : [],
    [cardsById, projectId, cardId, relatedIds],
  );

  const filtered = useMemo(() => {
    if (!search.trim()) return projectCards;
    const q = search.toLowerCase();
    return projectCards.filter((c) => c.title.toLowerCase().includes(q));
  }, [projectCards, search]);

  // Close dropdown on outside click
  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        setShowDropdown(false);
      }
    };
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, []);

  const handleAdd = (targetCardId: string) => {
    addRelation.mutate(
      { cardId, targetCardId, relationType: selectedType },
      {
        onSuccess: () => {
          setSearch('');
          setShowDropdown(false);
        },
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
      <span className="flex items-center gap-1 text-xs font-medium text-muted-foreground">
        <Link2 size={11} /> Related Cards ({relations.length})
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
            {(() => { const Icon = RELATION_ICON[rel.relationType] ?? Link2; return <Icon size={11} className="shrink-0 text-muted-foreground" />; })()}
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
              <X size={10} />
            </button>
          </div>
        ))}
      </div>

      {/* Add relation */}
      {projectCards.length > 0 || search ? (
        <div className="space-y-1" ref={containerRef}>
          <div className="flex items-center gap-1">
            <select
              value={selectedType}
              onChange={(e) => setSelectedType(e.target.value as CardRelationType)}
              className="shrink-0 rounded-md border border-border bg-card text-foreground px-1.5 py-1 text-xs outline-none"
            >
              {RELATION_TYPES.map((t) => (
                <option key={t} value={t}>
                  {RELATION_LABEL[t]}
                </option>
              ))}
            </select>
            <div className="relative flex-1">
              <Search size={11} className="pointer-events-none absolute left-2 top-1/2 -translate-y-1/2 text-muted-foreground/60" />
              <input
                ref={inputRef}
                type="text"
                value={search}
                onChange={(e) => { setSearch(e.target.value); setShowDropdown(true); }}
                onFocus={() => setShowDropdown(true)}
                placeholder="Search cards…"
                className="w-full rounded-md border border-border bg-card text-foreground pl-6 pr-2 py-1 text-xs outline-none placeholder:text-muted-foreground/40 focus:border-accent"
              />
              {/* Dropdown */}
              {showDropdown && (
                <div className="absolute left-0 right-0 top-full z-50 mt-1 max-h-40 overflow-y-auto rounded-md border border-border bg-card shadow-lg">
                  {filtered.length === 0 ? (
                    <p className="px-2 py-2 text-xs text-muted-foreground/60">No matching cards</p>
                  ) : (
                    filtered.map((c) => (
                      <button
                        key={c.id}
                        type="button"
                        onClick={() => handleAdd(c.id)}
                        disabled={addRelation.isPending}
                        className="flex w-full items-center gap-1.5 px-2 py-1.5 text-left text-xs hover:bg-muted transition-colors disabled:opacity-50"
                      >
                        <Plus size={10} className="shrink-0 text-muted-foreground/60" />
                        <span className={cn('h-2 w-2 shrink-0 rounded-full', STATUS_DOT[c.status] ?? 'bg-gray-500')} />
                        <span className="truncate">{c.title}</span>
                      </button>
                    ))
                  )}
                </div>
              )}
            </div>
          </div>
        </div>
      ) : (
        <p className="text-xs text-muted-foreground/60">No other cards in this project</p>
      )}
    </div>
  );
}
