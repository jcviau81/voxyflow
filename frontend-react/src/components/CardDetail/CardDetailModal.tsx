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
import { useChatService } from '../../contexts/useChatService';

import {
  usePatchCard,
  useArchiveCard,
  useExecuteCard,
} from '../../hooks/api/useCards';

// Sub-components (step 11a)
import { StatusButtons } from './StatusButtons';
import { AgentSelector } from './AgentSelector';
import { TagsSection } from './TagsSection';
import { ColorPicker } from './ColorPicker';

import { ProjectPicker } from './ProjectPicker';
import { DependenciesSection } from './DependenciesSection';


import { ChecklistSection } from './sections/Checklist';
import { AttachmentsSection } from './sections/Attachments';
import { LinkedFiles } from './sections/LinkedFiles';
import { RecurrenceSection } from './sections/RecurrenceSection';

// 11c sections
import { RelationsSection } from './Relations';
import { HistorySection } from './History';
import { ChatWindow } from '../Chat/ChatWindow';
import { DescriptionEditor } from './DescriptionEditor';
import { Archive, Play, Loader2 } from 'lucide-react';
import { useWorkerStatus } from '../../hooks/useWorkerStatus';

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

function computeRecurrenceNext(value: string | null): string | null {
  if (!value) return null;
  const now = new Date();
  // Custom cron — approximate next as +1 day (backend computes exact)
  if (value.startsWith('cron:')) return new Date(now.getTime() + 86400_000).toISOString();
  const MS: Record<string, number> = {
    '15min': 15 * 60_000, '30min': 30 * 60_000, 'hourly': 60 * 60_000,
    '6hours': 6 * 3600_000, 'daily': 86400_000, 'weekdays': 86400_000,
    'weekly': 7 * 86400_000, 'biweekly': 14 * 86400_000, 'monthly': 30 * 86400_000,
  };
  return new Date(now.getTime() + (MS[value] ?? 86400_000)).toISOString();
}

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
  const deleteCardStore = useCardStore((s) => s.deleteCard);
  const cardsById = useCardStore((s) => s.cardsById);
  const showToast = useToastStore((s) => s.showToast);

  // Mutations
  const patchCard = usePatchCard();
  const archiveCard = useArchiveCard();
  const executeCard = useExecuteCard();
  const { executeCard: executeCardWS } = useChatService();

  // Resolve current card from store (must be before useWorkerStatus which references card)
  const card: Card | undefined = selectedCardId ? cardsById[selectedCardId] : undefined;

  // Worker status — poll to detect active workers on the current card's project
  const { isCardActive } = useWorkerStatus(card?.projectId ?? '');

  // Local state
  const [mobileTab, setMobileTab] = useState<MobileTab>('description');
  const [description, setDescription] = useState('');
  const titleRef = useRef<HTMLInputElement>(null);
  const descriptionTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Resizable columns (desktop only)
  const [leftPct, setLeftPct] = useState(35);
  const [rightPct, setRightPct] = useState(28);
  const bodyRef = useRef<HTMLDivElement>(null);
  const dragTarget = useRef<'left' | 'right' | null>(null);

  const onDragHandleDown = useCallback((target: 'left' | 'right') => (e: React.MouseEvent) => {
    e.preventDefault();
    dragTarget.current = target;
    document.body.style.cursor = 'col-resize';
    document.body.style.userSelect = 'none';
  }, []);

  useEffect(() => {
    const onMove = (e: MouseEvent) => {
      if (!dragTarget.current || !bodyRef.current) return;
      const rect = bodyRef.current.getBoundingClientRect();
      const pct = ((e.clientX - rect.left) / rect.width) * 100;
      if (dragTarget.current === 'left') {
        setLeftPct(Math.min(50, Math.max(15, pct)));
      } else {
        const rPct = ((rect.right - e.clientX) / rect.width) * 100;
        setRightPct(Math.min(40, Math.max(15, rPct)));
      }
    };
    const onUp = () => {
      if (!dragTarget.current) return;
      dragTarget.current = null;
      document.body.style.cursor = '';
      document.body.style.userSelect = '';
    };
    window.addEventListener('mousemove', onMove);
    window.addEventListener('mouseup', onUp);
    return () => {
      window.removeEventListener('mousemove', onMove);
      window.removeEventListener('mouseup', onUp);
    };
  }, []);
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

  // Sync local description only when opening a different card.
  // While the modal is open, local state is the source of truth — server/WebSocket
  // updates must not overwrite the user's in-progress edits.
  useEffect(() => {
    if (card) setDescription(card.description ?? '');
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [card?.id]);

  useEffect(() => {
    if (card && titleRef.current) {
      titleRef.current.value = card.title;
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [card?.id]);

  // ── Handlers ────────────────────────────────────────────────────────────────

  const close = useCallback(() => {
    if (descriptionTimerRef.current) clearTimeout(descriptionTimerRef.current);
    selectCard(null);
  }, [selectCard]);

  const save = useCallback(
    (updates: Record<string, unknown>) => {
      if (!card) return;
      // Optimistic local update
      updateCardStore(card.id, updates as Partial<Card>);
      // Persist to server — scoped invalidation by projectId avoids refetching all boards.
      patchCard.mutate({
        cardId: card.id,
        updates,
        projectId: card.projectId ?? undefined,
      });
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
    (agentType: string) => {
      if (!card) return;
      // Optimistic update uses camelCase (Card type); API expects snake_case
      updateCardStore(card.id, { agentType } as Partial<Card>);
      patchCard.mutate({
        cardId: card.id,
        updates: { agent_type: agentType },
        projectId: card.projectId ?? undefined,
      });
    },
    [card, updateCardStore, patchCard],
  );

  const handleColorChange = useCallback(
    (color: string | null) => save({ color }),
    [save],
  );

  const handleRecurrenceChange = useCallback(
    (value: string | null) => {
      save({ recurrence: value, recurrence_next: computeRecurrenceNext(value) });
    },
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

  const handleArchive = useCallback(() => {
    if (!card) return;
    // Optimistic: remove from store immediately so the board updates
    deleteCardStore(card.id);
    close();
    archiveCard.mutate(
      { cardId: card.id, projectId: card.projectId ?? undefined },
      {
        onSuccess: () => {
          showToast(`"${card.title}" archived`, 'success');
        },
      },
    );
  }, [card, archiveCard, deleteCardStore, showToast, close]);

  const handleExecute = useCallback(() => {
    if (!card) return;
    executeCard.mutate(card.id, {
      onSuccess: () => {
        executeCardWS(card.id, card.projectId || undefined);
        showToast(`Executing: "${card.title}"`, 'success');
      },
      onError: () => showToast('Execution failed', 'error'),
    });
  }, [card, executeCard, executeCardWS, showToast]);

  // ── Render ──────────────────────────────────────────────────────────────────

  if (!card) return null;

  const colorRing = card.color ? COLOR_RING[card.color] ?? '' : '';

  return (
    <Dialog open={isOpen} onOpenChange={(open) => { if (!open) close(); }}>
      <DialogContent
        showCloseButton
        className={cn(
          'flex flex-col overflow-hidden p-0',
          'h-[100dvh] w-full max-w-full md:h-[90vh] md:max-h-[90vh] md:w-[90vw] md:max-w-[90vw]',
          colorRing && `ring-2 ${colorRing}`,
        )}
        onPointerDownOutside={(e) => e.preventDefault()}
      >
        {/* Accessible title (visually hidden — title is in the header input) */}
        <DialogTitle className="sr-only">{card.title}</DialogTitle>

        {/* ── Header ───────────────────────────────────────────────────────── */}
        <div className="flex items-center items-center gap-2 border-b border-border px-4 py-2.5">
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
        <div ref={bodyRef} className="flex min-h-0 flex-1 overflow-hidden" data-testid="card-detail-body">
          {/* LEFT: Chat */}
          <div
            data-testid="card-detail-chat"
            style={{ width: `${leftPct}%` }}
            className={cn(
              'flex flex-col md:shrink-0',
              mobileTab === 'chat' ? 'flex' : 'hidden md:flex',
            )}
          >
            <ChatWindow
              tabId={`card-${card.id}`}
              chatLevel="card"
              projectId={card.projectId ?? undefined}
              cardId={card.id}
              embedded
              className="flex-1"
            />
          </div>

          {/* Drag handle: left | center */}
          <div
            onMouseDown={onDragHandleDown('left')}
            className="hidden md:block w-1 cursor-col-resize shrink-0 bg-border hover:bg-primary/40 active:bg-primary/60 transition-colors"
          />

          {/* CENTER: Description */}
          <div
            data-testid="card-detail-description"
            className={cn(
              'flex flex-col px-4 pb-4 md:flex-1',
              mobileTab === 'description' ? 'flex' : 'hidden md:flex',
            )}
          >
            <DescriptionEditor
              cardId={card.id}
              value={description}
              onChange={handleDescriptionChange}
            />
          </div>

          {/* Drag handle: center | right */}
          <div
            onMouseDown={onDragHandleDown('right')}
            className="hidden md:block w-1 cursor-col-resize shrink-0 bg-border hover:bg-primary/40 active:bg-primary/60 transition-colors"
          />

          {/* RIGHT: Metadata sidebar */}
          <div
            data-testid="card-detail-sidebar"
            style={{ width: `${rightPct}%` }}
            className={cn(
              'flex flex-col overflow-y-auto md:shrink-0',
              mobileTab === 'details' ? 'flex' : 'hidden md:flex',
            )}
          >
            <div className="space-y-5 px-4 pb-4">
              {/* Execute */}
              {(() => {
                const workerRunning = card ? isCardActive(card.id) : false;
                const isDisabled = executeCard.isPending || workerRunning;
                return (
                  <button
                    type="button"
                    onClick={handleExecute}
                    disabled={isDisabled}
                    title={workerRunning ? 'A worker is already executing this card' : undefined}
                    className="flex w-full items-center justify-center gap-1.5 rounded-md px-3 py-2 text-sm font-medium transition-colors disabled:opacity-50 disabled:cursor-not-allowed bg-emerald-500/15 text-emerald-400 border border-emerald-500/30 hover:bg-emerald-500/25 cursor-pointer"
                  >
                    {(executeCard.isPending || workerRunning)
                      ? <><Loader2 size={14} className="animate-spin" /> Executing…</>
                      : <><Play size={14} /> Execute</>}
                  </button>
                );
              })()}

              {/* Group 1: Status & Agent */}
              <section className="space-y-3">
                <div>
                  <label className="mb-1 block text-xs font-medium text-muted-foreground cursor-pointer">Status</label>
                  <StatusButtons current={card.status} onChange={handleStatusChange} />
                </div>
                <div>
                  <label className="mb-1 block text-xs font-medium text-muted-foreground cursor-pointer">Agent</label>
                  <AgentSelector current={card.agentType ?? 'general'} onChange={handleAgentChange} />
                </div>
                <div>
                  <label className="mb-1 block text-xs font-medium text-muted-foreground cursor-pointer">Worker Model</label>
                  <div className="flex gap-1.5">
                    {([null, 'haiku', 'sonnet', 'opus'] as const).map((m) => (
                      <button
                        key={m ?? 'auto'}
                        type="button"
                        onClick={() => save({ preferred_model: m })}
                        className={cn(
                          'rounded-md border px-2.5 py-1 text-xs font-medium transition-colors cursor-pointer',
                          (card.preferredModel ?? null) === m
                            ? 'bg-primary/20 text-primary border-primary/40'
                            : 'bg-muted/40 text-muted-foreground border-border hover:bg-muted/60',
                        )}
                      >
                        {m === null ? 'Auto' : m === 'haiku' ? 'Haiku' : m === 'sonnet' ? 'Sonnet' : 'Opus'}
                      </button>
                    ))}
                  </div>
                </div>
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
                <RecurrenceSection
                  current={card.recurrence}
                  nextDate={card.recurrenceNext}
                  onChange={handleRecurrenceChange}
                />
                <div>
                  <label className="flex items-center gap-2 text-xs text-muted-foreground cursor-pointer select-none">
                    <input
                      type="checkbox"
                      checked={card.recurring ?? false}
                      onChange={(e) => save({ recurring: e.target.checked })}
                      className="rounded border-border accent-primary cursor-pointer"
                    />
                    Recurring (reset to todo after board run)
                  </label>
                </div>
              </section>

              <hr className="border-border" />

              {/* Group 4: Tracking */}
              <section className="space-y-3">
                <ChecklistSection cardId={card.id} />
                <hr className="border-border" />
                <LinkedFiles cardId={card.id} projectId={card.projectId ?? undefined} files={card.files ?? []} />
                <AttachmentsSection cardId={card.id} />

                <hr className="border-border" />
                
                <label className="mb-1 block text-xs font-medium text-muted-foreground">Dependencies</label>
                <DependenciesSection
                  card={card}
                  projectCards={projectCards}
                  onAdd={handleAddDep}
                  onRemove={handleRemoveDep}
                />
              
                <RelationsSection cardId={card.id} projectId={card.projectId ?? undefined} />
                <hr className="border-border" />
                <HistorySection cardId={card.id} />
              </section>

              <hr className="border-border" />

              {/* Footer: Meta & Danger zone */}
              <section className="space-y-3 pb-2">
                <div className="space-y-0.5 text-[10px] text-muted-foreground/60">
                  <div>Created: {formatTime(card.createdAt)}</div>
                  <div>Updated: {formatTime(card.updatedAt)}</div>
                </div>
                <button
                  type="button"
                  onClick={handleArchive}
                  className="flex items-center gap-1.5 rounded-md border border-border px-2.5 py-1 text-xs text-muted-foreground transition-colors hover:bg-muted cursor-pointer"
                >
                  <Archive size={12} /> Archive
                </button>
              </section>
            </div>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
}
