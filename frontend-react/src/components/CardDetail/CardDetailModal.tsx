/**
 * CardDetailModal — React port of the vanilla CardDetailModal.
 *
 * Three-column layout:
 *   LEFT:   DescriptionEditor (CodeMirror-backed)
 *   CENTER: CardChat (embedded per-card chat)
 *   RIGHT:  Metadata sidebar (status, agent, tags, color, people, deps, etc.)
 *
 * Opens when useProjectStore.selectedCardId is set.
 * Mobile: tabs switch between the three columns.
 */

import { useState, useCallback, useEffect, useMemo, useRef } from 'react';
import { cn } from '@/lib/utils';
import {
  Dialog,
  DialogContent,
  DialogTitle,
} from '../ui/dialog';
import type { Card, CardStatus } from '../../types';
import { useProjectStore } from '../../stores/useProjectStore';
import { useCardStore, SYSTEM_PROJECT_ID } from '../../stores/useCardStore';
import { useToastStore } from '../../stores/useToastStore';
import {
  usePatchCard,
  useDuplicateCard,
  useArchiveCard,
  useDeleteCard,
  useExecuteCard,
} from '../../hooks/api/useCards';

// Sub-components (step 11a)
import { StatusButtons } from './StatusButtons';
import { AgentSelector } from './AgentSelector';
import { TagsSection } from './TagsSection';
import { ColorPicker } from './ColorPicker';
import { VoteSection } from './VoteSection';
import { ProjectPicker } from './ProjectPicker';
import { DependenciesSection } from './DependenciesSection';

// Section components (step 11b)
import { TimeTracking } from './sections/TimeTracking';
import { ChecklistSection } from './sections/Checklist';
import { AttachmentsSection } from './sections/Attachments';
import { LinkedFiles } from './sections/LinkedFiles';

// 11c sections
import { RelationsSection } from './Relations';
import { HistorySection } from './History';
import { ChatWindow } from '../Chat/ChatWindow';
import { DescriptionEditor } from './DescriptionEditor';
import { Copy, Archive } from 'lucide-react';

// ── Color class map ─────────────────────────────────────────────────────────

const COLOR_RING: Record<string, string> = {
  yellow: 'ring-yellow-400/30',
  blue: 'ring-blue-400/30',
  green: 'ring-emerald-400/30',
  pink: 'ring-pink-400/30',
  purple: 'ring-purple-400/30',
  orange: 'ring-orange-400/30',
};

// ── Mobile tab keys ─────────────────────────────────────────────────────────

type MobileTab = 'description' | 'chat' | 'details';

// ── Helpers ─────────────────────────────────────────────────────────────────

function formatTime(ts: number): string {
  return new Date(ts).toLocaleDateString(undefined, {
    month: 'short',
    day: 'numeric',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  });
}

// ── Component ───────────────────────────────────────────────────────────────

export function CardDetailModal() {
  const selectedCardId = useProjectStore((s) => s.selectedCardId);
  const selectCard = useProjectStore((s) => s.selectCard);
  const updateCardStore = useCardStore((s) => s.updateCard);
  const cardsById = useCardStore((s) => s.cardsById);
  const showToast = useToastStore((s) => s.showToast);

  // Mutations
  const patchCard = usePatchCard();
  const duplicateCard = useDuplicateCard();
  const archiveCard = useArchiveCard();
  const deleteCard = useDeleteCard();
  const executeCard = useExecuteCard();

  // Local state
  const [mobileTab, setMobileTab] = useState<MobileTab>('description');
  const [description, setDescription] = useState('');
  const titleRef = useRef<HTMLInputElement>(null);
  const descriptionTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Resolve current card from store
  const card: Card | undefined = selectedCardId ? cardsById[selectedCardId] : undefined;
  const isOpen = !!card;

  // Determine if on main board
  const isMainBoard = !card?.projectId || card.projectId === SYSTEM_PROJECT_ID;

  // Project cards for dependency picker
  const projectCards = useMemo(
    () => card?.projectId
      ? Object.values(cardsById).filter((c) => c.projectId === card.projectId)
      : [],
    [card?.projectId, cardsById],
  );

  // Sync description when card changes
  useEffect(() => {
    if (card) setDescription(card.description ?? '');
  }, [card?.id]); // eslint-disable-line react-hooks/exhaustive-deps

  // ── Handlers ────────────────────────────────────────────────────────────────

  const close = useCallback(() => selectCard(null), [selectCard]);

  const save = useCallback(
    (updates: Record<string, unknown>) => {
      if (!card) return;
      // Optimistic local update
      updateCardStore(card.id, updates as Partial<Card>);
      // Persist to server
      patchCard.mutate({ cardId: card.id, updates });
    },
    [card, updateCardStore, patchCard],
  );

  const handleTitleBlur = useCallback(() => {
    const val = titleRef.current?.value.trim();
    if (val && card && val !== card.title) {
      save({ title: val });
    }
  }, [card, save]);

  const handleDescriptionChange = useCallback(
    (value: string) => {
      setDescription(value);
      // Debounce save
      if (descriptionTimerRef.current) clearTimeout(descriptionTimerRef.current);
      descriptionTimerRef.current = setTimeout(() => {
        if (card) save({ description: value });
      }, 800);
    },
    [card, save],
  );

  const handleStatusChange = useCallback(
    (status: CardStatus) => save({ status }),
    [save],
  );

  const handleAgentChange = useCallback(
    (agentType: string) => save({ agent_type: agentType }),
    [save],
  );

  const handleColorChange = useCallback(
    (color: string | null) => save({ color }),
    [save],
  );

  const handleTagAdd = useCallback(
    (tag: string) => {
      if (!card) return;
      save({ tags: [...card.tags, tag] });
    },
    [card, save],
  );

  const handleTagRemove = useCallback(
    (tag: string) => {
      if (!card) return;
      save({ tags: card.tags.filter((t) => t !== tag) });
    },
    [card, save],
  );

  const handleAddDep = useCallback(
    (depId: string) => {
      if (!card) return;
      save({ dependency_ids: [...card.dependencies, depId] });
    },
    [card, save],
  );

  const handleRemoveDep = useCallback(
    (depId: string) => {
      if (!card) return;
      save({ dependency_ids: card.dependencies.filter((d) => d !== depId) });
    },
    [card, save],
  );

  const handleDuplicate = useCallback(() => {
    if (!card) return;
    duplicateCard.mutate(
      { cardId: card.id, projectId: card.projectId ?? undefined },
      {
        onSuccess: () => {
          showToast(`Duplicated: "${card.title}"`, 'success');
          close();
        },
        onError: () => showToast('Duplication failed', 'error'),
      },
    );
  }, [card, duplicateCard, showToast, close]);

  const handleArchive = useCallback(() => {
    if (!card) return;
    archiveCard.mutate(
      { cardId: card.id, projectId: card.projectId ?? undefined },
      {
        onSuccess: () => {
          showToast(`"${card.title}" archived`, 'success');
          close();
        },
      },
    );
  }, [card, archiveCard, showToast, close]);

  const handleDelete = useCallback(() => {
    if (!card) return;
    if (!window.confirm(`Delete "${card.title}"?`)) return;
    deleteCard.mutate(
      { cardId: card.id, projectId: card.projectId ?? undefined },
      {
        onSuccess: () => {
          showToast(`Deleted: "${card.title}"`, 'info');
          close();
        },
      },
    );
  }, [card, deleteCard, showToast, close]);

  const handleExecute = useCallback(() => {
    if (!card) return;
    executeCard.mutate(card.id, {
      onSuccess: () => {
        showToast(`Executing: "${card.title}"`, 'success');
      },
      onError: () => showToast('Execution failed', 'error'),
    });
  }, [card, executeCard, showToast]);

  // ── Render ──────────────────────────────────────────────────────────────────

  if (!card) return null;

  const colorRing = card.color ? COLOR_RING[card.color] ?? '' : '';

  return (
    <Dialog open={isOpen} onOpenChange={(open) => { if (!open) close(); }}>
      <DialogContent
        showCloseButton
        className={cn(
          'flex h-[90vh] max-h-[90vh] w-[90vw] max-w-[90vw] flex-col overflow-hidden p-0',
          colorRing && `ring-2 ${colorRing}`,
        )}
        onPointerDownOutside={(e) => e.preventDefault()}
      >
        {/* Accessible title (visually hidden — title is in the header input) */}
        <DialogTitle className="sr-only">{card.title}</DialogTitle>

        {/* ── Header ───────────────────────────────────────────────────────── */}
        <div className="flex items-center gap-2 border-b border-border px-4 py-2.5">
          <input
            ref={titleRef}
            defaultValue={card.title}
            key={card.id} // reset on card change
            onBlur={handleTitleBlur}
            onKeyDown={(e) => {
              if (e.key === 'Enter') (e.target as HTMLInputElement).blur();
            }}
            className="flex-1 bg-transparent text-base font-semibold outline-none placeholder:text-muted-foreground/50"
            placeholder="Card title..."
          />
          <button
            type="button"
            onClick={handleExecute}
            disabled={executeCard.isPending}
            className="rounded-md border border-border px-2.5 py-1 text-xs font-medium text-muted-foreground transition-colors hover:bg-muted"
          >
            {executeCard.isPending ? '▶ Executing...' : '▶ Execute'}
          </button>
          <button
            type="button"
            onClick={handleDuplicate}
            disabled={duplicateCard.isPending}
            className="flex items-center gap-1.5 rounded-md border border-border px-2.5 py-1 text-xs font-medium text-muted-foreground transition-colors hover:bg-muted"
          >
            <Copy size={12} /> Duplicate
          </button>
          <button
            type="button"
            onClick={handleArchive}
            className="flex items-center gap-1.5 rounded-md border border-border px-2.5 py-1 text-xs font-medium text-muted-foreground transition-colors hover:bg-muted"
          >
            <Archive size={12} /> Archive
          </button>
        </div>

        {/* ── Mobile tab bar (hidden on desktop) ───────────────────────────── */}
        <div className="flex border-b border-border md:hidden">
          {(['description', 'chat', 'details'] as MobileTab[]).map((tab) => (
            <button
              key={tab}
              type="button"
              onClick={() => setMobileTab(tab)}
              className={cn(
                'flex-1 py-2 text-center text-xs font-medium capitalize transition-colors',
                mobileTab === tab
                  ? 'border-b-2 border-accent text-accent-foreground'
                  : 'text-muted-foreground',
              )}
            >
              {tab}
            </button>
          ))}
        </div>

        {/* ── Three-column body ────────────────────────────────────────────── */}
        <div className="flex min-h-0 flex-1 overflow-hidden" data-testid="card-detail-body">
          {/* LEFT: Description */}
          <div
            data-testid="card-detail-description"
            className={cn(
              'flex flex-col border-r border-border p-4 md:w-[35%]',
              mobileTab === 'description' ? 'flex' : 'hidden md:flex',
            )}
          >
            <label className="mb-2 text-xs font-medium text-muted-foreground">Description</label>
            <div className="min-h-0 flex-1 overflow-auto">
              <DescriptionEditor
                cardId={card.id}
                value={description}
                onChange={handleDescriptionChange}
              />
            </div>
          </div>

          {/* CENTER: Chat */}
          <div
            data-testid="card-detail-chat"
            className={cn(
              'flex flex-col border-r border-border md:flex-1',
              mobileTab === 'chat' ? 'flex' : 'hidden md:flex',
            )}
          >
            <ChatWindow
              tabId={`card-${card.id}`}
              chatLevel="card"
              projectId={card.projectId ?? undefined}
              cardId={card.id}
              embedded
            />
          </div>

          {/* RIGHT: Metadata sidebar */}
          <div
            data-testid="card-detail-sidebar"
            className={cn(
              'flex flex-col overflow-y-auto md:w-[400px] md:min-w-[400px]',
              mobileTab === 'details' ? 'flex' : 'hidden md:flex',
            )}
          >
            <div className="space-y-5 p-4">
              {/* Group 1: Status & Agent */}
              <section className="space-y-3">
                <StatusButtons current={card.status} onChange={handleStatusChange} />
                <div>
                  <label className="mb-1 block text-xs font-medium text-muted-foreground">Agent</label>
                  <AgentSelector current={card.agentType ?? 'general'} onChange={handleAgentChange} />
                </div>
                <VoteSection cardId={card.id} votes={card.votes ?? 0} />
              </section>

              <hr className="border-border" />

              {/* Group 2: Organization */}
              <section className="space-y-3">
                <span className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground/60">
                  Organization
                </span>
                <div>
                  <label className="mb-1 block text-xs font-medium text-muted-foreground">Tags</label>
                  <TagsSection tags={card.tags} onAdd={handleTagAdd} onRemove={handleTagRemove} />
                </div>
                <div>
                  <label className="mb-1 block text-xs font-medium text-muted-foreground">Color</label>
                  <ColorPicker
                    current={card.color as 'yellow' | 'blue' | 'green' | 'pink' | 'purple' | 'orange' | null | undefined}
                    onChange={handleColorChange}
                  />
                </div>
                {isMainBoard && <ProjectPicker cardId={card.id} onMoved={close} />}
              </section>

              <hr className="border-border" />

              {/* Group 4: Tracking */}
              <section className="space-y-3">
                <span className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground/60">
                  Tracking
                </span>
                <TimeTracking cardId={card.id} />
                <ChecklistSection cardId={card.id} />
                <LinkedFiles cardId={card.id} files={card.files ?? []} />
                <AttachmentsSection cardId={card.id} />
              </section>

              <hr className="border-border" />

              {/* Group 5: Links */}
              <section className="space-y-3">
                <span className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground/60">
                  Links
                </span>
                <div>
                  <label className="mb-1 block text-xs font-medium text-muted-foreground">Dependencies</label>
                  <DependenciesSection
                    card={card}
                    projectCards={projectCards}
                    onAdd={handleAddDep}
                    onRemove={handleRemoveDep}
                  />
                </div>
                <RelationsSection cardId={card.id} projectId={card.projectId ?? undefined} />
                <HistorySection cardId={card.id} />
              </section>

              <hr className="border-border" />

              {/* Footer: Meta & Danger zone */}
              <section className="space-y-3 pb-2">
                <div className="space-y-0.5 text-[10px] text-muted-foreground/60">
                  <div>Created: {formatTime(card.createdAt)}</div>
                  <div>Updated: {formatTime(card.updatedAt)}</div>
                </div>
                <div className="flex gap-2">
                  <button
                    type="button"
                    onClick={handleArchive}
                    className="flex items-center gap-1.5 rounded-md border border-border px-2.5 py-1 text-xs text-muted-foreground transition-colors hover:bg-muted"
                  >
                    <Archive size={12} /> Archive
                  </button>
                  <button
                    type="button"
                    onClick={handleDelete}
                    className="flex items-center gap-1.5 rounded-md border border-red-500/30 px-2.5 py-1 text-xs text-red-400 transition-colors hover:bg-red-500/10"
                  >
                    🗑️ Delete
                  </button>
                </div>
              </section>
            </div>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
}
