/**
 * CommandPalette — global Cmd/Ctrl+K fuzzy command palette (cmdk-backed).
 *
 * Sources:
 *   - Navigation: workspaces (cached react-query data), pages (settings/jobs/…)
 *   - Views: kanban / chat / freeboard / stats / knowledge
 *   - Actions: new card (with typed title), toggle sidebar, new chat session
 *   - Cards in the CURRENT workspace by title (from the store, synced from
 *     react-query — no extra polling)
 *
 * Recent-first: the last used commands are persisted in localStorage and shown
 * in a "Recent" group while the query is empty. Fully keyboard operable
 * (arrows + Enter via cmdk, Escape closes).
 */

import { useCallback, useEffect, useMemo, useState } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import { Command } from 'cmdk';
import {
  Clock,
  Folder,
  FolderOpen,
  Home,
  Kanban,
  LayoutGrid,
  MessageSquare,
  MessagesSquare,
  PanelLeft,
  Plus,
  Search,
  Settings,
  SquareKanban,
  BarChart3,
  BrainCircuit,
} from 'lucide-react';
import { cn } from '@/lib/utils';
import type { ViewMode } from '../../types';
import { useWorkspaces } from '../../hooks/api/useWorkspaces';
import { useCreateCard } from '../../hooks/api/useCards';
import { useCardStore } from '../../stores/useCardStore';
import { useWorkspaceStore } from '../../stores/useWorkspaceStore';
import { useViewStore } from '../../stores/useViewStore';
import { useTabStore } from '../../stores/useTabStore';
import { useSessionStore } from '../../stores/useSessionStore';
import { useToastStore } from '../../stores/useToastStore';

// ── Recent commands (localStorage) ──────────────────────────────────────────

const RECENT_KEY = 'voxyflow_palette_recent';
const RECENT_MAX = 6;

function readRecent(): string[] {
  try {
    const raw = localStorage.getItem(RECENT_KEY);
    const arr: unknown = raw ? JSON.parse(raw) : [];
    return Array.isArray(arr) ? (arr.filter((v) => typeof v === 'string') as string[]) : [];
  } catch {
    return [];
  }
}

function pushRecent(id: string): string[] {
  const next = [id, ...readRecent().filter((r) => r !== id)].slice(0, RECENT_MAX);
  try {
    localStorage.setItem(RECENT_KEY, JSON.stringify(next));
  } catch {
    /* ignore */
  }
  return next;
}

// ── Views shown in the palette ───────────────────────────────────────────────

const VIEW_COMMANDS: Array<{ view: ViewMode; label: string; icon: typeof Kanban }> = [
  { view: 'kanban', label: 'Kanban board', icon: SquareKanban },
  { view: 'chat', label: 'Chat', icon: MessageSquare },
  { view: 'freeboard', label: 'Free board', icon: LayoutGrid },
  { view: 'stats', label: 'Stats', icon: BarChart3 },
  { view: 'knowledge', label: 'Knowledge', icon: BrainCircuit },
];

// ── Shared item styling ──────────────────────────────────────────────────────

const ITEM_CLASS = cn(
  'flex cursor-pointer items-center gap-2.5 rounded-md px-2.5 py-2 text-sm text-foreground/90',
  'select-none outline-none',
  'data-[selected=true]:bg-accent data-[selected=true]:text-accent-foreground',
);

const GROUP_HEADING_CLASS =
  '[&_[cmdk-group-heading]]:px-2.5 [&_[cmdk-group-heading]]:py-1.5 [&_[cmdk-group-heading]]:text-[10px] [&_[cmdk-group-heading]]:font-semibold [&_[cmdk-group-heading]]:uppercase [&_[cmdk-group-heading]]:tracking-wider [&_[cmdk-group-heading]]:text-muted-foreground/70';

// ── Component ────────────────────────────────────────────────────────────────

export interface CommandPaletteProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onToggleSidebar: () => void;
}

interface PaletteEntry {
  id: string;
  label: string;
  keywords?: string;
  icon: React.ReactNode;
  hint?: string;
  perform: () => void;
}

export function CommandPalette({ open, onOpenChange, onToggleSidebar }: CommandPaletteProps) {
  const navigate = useNavigate();
  const location = useLocation();
  const [search, setSearch] = useState('');
  const [recentIds, setRecentIds] = useState<string[]>([]);

  // Cached query data — staleTime keeps this from refetching; no new polling.
  const { data: workspaces } = useWorkspaces();
  const createCard = useCreateCard();
  const showToast = useToastStore((s) => s.showToast);

  const currentWorkspaceId = useWorkspaceStore((s) => s.currentWorkspaceId);
  const cardsById = useCardStore((s) => s.cardsById);

  // Reset query each time the palette opens; refresh recents.
  useEffect(() => {
    if (open) {
      setSearch('');
      setRecentIds(readRecent());
    }
  }, [open]);

  const close = useCallback(() => onOpenChange(false), [onOpenChange]);

  const run = useCallback(
    (entry: PaletteEntry) => {
      setRecentIds(pushRecent(entry.id));
      close();
      entry.perform();
    },
    [close],
  );

  // Navigate to a board page (main or workspace) if we're on a full page, then
  // switch the active view.
  const goToView = useCallback(
    (view: ViewMode) => {
      const onBoardPage = location.pathname === '/' || location.pathname.startsWith('/workspace/');
      if (!onBoardPage) {
        navigate(currentWorkspaceId ? `/workspace/${currentWorkspaceId}` : '/');
      }
      useViewStore.getState().setView(view);
    },
    [location.pathname, navigate, currentWorkspaceId],
  );

  // ── Entries ────────────────────────────────────────────────────────────────

  const workspaceEntries = useMemo<PaletteEntry[]>(
    () =>
      (workspaces ?? [])
        .filter((w) => !w.archived)
        .map((w) => ({
          id: `workspace:${w.id}`,
          label: `${w.emoji ? `${w.emoji} ` : ''}${w.name}`,
          keywords: `workspace go open ${w.description}`,
          icon: <FolderOpen size={15} className="shrink-0 text-muted-foreground" />,
          hint: 'Workspace',
          perform: () => navigate(`/workspace/${w.id}`),
        })),
    [workspaces, navigate],
  );

  const pageEntries = useMemo<PaletteEntry[]>(
    () => [
      {
        id: 'page:home',
        label: 'Home',
        keywords: 'main general root',
        icon: <Home size={15} className="shrink-0 text-muted-foreground" />,
        perform: () => navigate('/'),
      },
      {
        id: 'page:settings',
        label: 'Settings',
        keywords: 'preferences config models providers appearance voice',
        icon: <Settings size={15} className="shrink-0 text-muted-foreground" />,
        perform: () => navigate('/settings'),
      },
      {
        id: 'page:jobs',
        label: 'Jobs',
        keywords: 'scheduled recurring cron',
        icon: <Clock size={15} className="shrink-0 text-muted-foreground" />,
        perform: () => navigate('/jobs'),
      },
      {
        id: 'page:workspaces',
        label: 'All workspaces',
        keywords: 'workspaces list projects boards',
        icon: <Folder size={15} className="shrink-0 text-muted-foreground" />,
        perform: () => navigate('/workspaces'),
      },
    ],
    [navigate],
  );

  const viewEntries = useMemo<PaletteEntry[]>(
    () =>
      VIEW_COMMANDS.map(({ view, label, icon: Icon }) => ({
        id: `view:${view}`,
        label,
        keywords: `view switch show ${view}`,
        icon: <Icon size={15} className="shrink-0 text-muted-foreground" />,
        hint: 'View',
        perform: () => goToView(view),
      })),
    [goToView],
  );

  const actionEntries = useMemo<PaletteEntry[]>(() => {
    const entries: PaletteEntry[] = [
      {
        id: 'action:toggle-sidebar',
        label: 'Toggle sidebar',
        keywords: 'hide show collapse panel ctrl+b',
        icon: <PanelLeft size={15} className="shrink-0 text-muted-foreground" />,
        hint: 'Ctrl+B',
        perform: onToggleSidebar,
      },
      {
        id: 'action:new-chat',
        label: 'New chat session',
        keywords: 'conversation session start fresh',
        icon: <MessagesSquare size={15} className="shrink-0 text-muted-foreground" />,
        perform: () => {
          const tabId = useTabStore.getState().getActiveTab();
          useSessionStore.getState().createSession(tabId, tabId === 'main' ? 'general' : 'workspace');
          goToView('chat');
        },
      },
    ];
    return entries;
  }, [onToggleSidebar, goToView]);

  const cardEntries = useMemo<PaletteEntry[]>(() => {
    if (!currentWorkspaceId) return [];
    return Object.values(cardsById)
      .filter((c) => c.workspaceId === currentWorkspaceId && !c.archivedAt)
      .sort((a, b) => b.updatedAt - a.updatedAt)
      .map((c) => ({
        id: `card:${c.id}`,
        label: c.title,
        keywords: `card open ${c.tags.join(' ')}`,
        icon: <Kanban size={15} className="shrink-0 text-muted-foreground" />,
        hint: c.status,
        perform: () => useWorkspaceStore.getState().selectCard(c.id),
      }));
  }, [cardsById, currentWorkspaceId]);

  const allEntries = useMemo(() => {
    const map = new Map<string, PaletteEntry>();
    for (const e of [...workspaceEntries, ...pageEntries, ...viewEntries, ...actionEntries, ...cardEntries]) {
      map.set(e.id, e);
    }
    return map;
  }, [workspaceEntries, pageEntries, viewEntries, actionEntries, cardEntries]);

  const recentEntries = useMemo(
    () => recentIds.map((id) => allEntries.get(id)).filter((e): e is PaletteEntry => !!e),
    [recentIds, allEntries],
  );

  // ── New card (uses typed query as the title) ──────────────────────────────

  const newCardTitle = search.trim();
  const handleNewCard = useCallback(() => {
    if (!currentWorkspaceId) {
      showToast('Open a workspace first to create a card', 'info');
      return;
    }
    createCard.mutate(
      { workspaceId: currentWorkspaceId, title: newCardTitle || 'New card', status: 'todo' },
      {
        onSuccess: (card) => useWorkspaceStore.getState().selectCard(card.id),
        onError: () => showToast('Failed to create card', 'error'),
      },
    );
  }, [currentWorkspaceId, newCardTitle, createCard, showToast]);

  if (!open) return null;

  const renderItem = (entry: PaletteEntry, idPrefix = '') => (
    <Command.Item
      key={`${idPrefix}${entry.id}`}
      value={`${idPrefix}${entry.id}`}
      keywords={[entry.label, ...(entry.keywords ? [entry.keywords] : [])]}
      onSelect={() => run(entry)}
      className={ITEM_CLASS}
    >
      {entry.icon}
      <span className="min-w-0 flex-1 truncate">{entry.label}</span>
      {entry.hint && (
        <span className="shrink-0 text-[10px] uppercase tracking-wide text-muted-foreground/60">{entry.hint}</span>
      )}
    </Command.Item>
  );

  return (
    <div
      className="fixed inset-0 z-[100] flex items-start justify-center"
      data-testid="command-palette-root"
    >
      {/* Overlay */}
      <div
        className="absolute inset-0 bg-black/65 backdrop-blur-sm animate-in fade-in-0 duration-100 motion-reduce:animate-none"
        onClick={close}
        data-testid="command-palette-overlay"
      />

      {/* Panel */}
      <Command
        label="Command palette"
        loop
        className={cn(
          'relative mt-[12vh] flex w-full max-w-xl flex-col overflow-hidden rounded-xl',
          'bg-popover text-popover-foreground shadow-2xl ring-1 ring-foreground/10',
          'animate-in fade-in-0 zoom-in-95 duration-100 motion-reduce:animate-none',
          GROUP_HEADING_CLASS,
        )}
        onKeyDown={(e) => {
          if (e.key === 'Escape') {
            e.preventDefault();
            e.stopPropagation();
            close();
          }
        }}
        data-testid="command-palette"
      >
        <div className="flex items-center gap-2.5 border-b border-border px-3.5">
          <Search size={15} className="shrink-0 text-muted-foreground" />
          <Command.Input
            autoFocus
            value={search}
            onValueChange={setSearch}
            placeholder="Type a command, workspace or card…"
            className="h-11 flex-1 bg-transparent text-sm outline-none placeholder:text-muted-foreground/60"
            data-testid="command-palette-input"
          />
          <kbd className="shrink-0 rounded border border-border bg-muted/60 px-1.5 py-0.5 text-[10px] text-muted-foreground">
            Esc
          </kbd>
        </div>

        <Command.List className="max-h-[50vh] overflow-y-auto overscroll-contain p-1.5">
          <Command.Empty className="py-8 text-center text-sm text-muted-foreground">
            No results.
          </Command.Empty>

          {/* Recent (only while query is empty) */}
          {!search && recentEntries.length > 0 && (
            <Command.Group heading="Recent">
              {recentEntries.map((e) => renderItem(e, 'recent:'))}
            </Command.Group>
          )}

          <Command.Group heading="Views">{viewEntries.map((e) => renderItem(e))}</Command.Group>

          <Command.Group heading="Workspaces">{workspaceEntries.map((e) => renderItem(e))}</Command.Group>

          {cardEntries.length > 0 && (
            <Command.Group heading="Cards">{cardEntries.map((e) => renderItem(e))}</Command.Group>
          )}

          <Command.Group heading="Actions">
            {/* New card — force-mounted so the typed query becomes the title.
                Note: the query is NOT in keywords, so real matches outrank it. */}
            <Command.Item
              forceMount
              value="action:new-card"
              keywords={['new card create add task']}
              onSelect={() => {
                setRecentIds(pushRecent('action:new-card'));
                close();
                handleNewCard();
              }}
              className={ITEM_CLASS}
              data-testid="command-palette-new-card"
            >
              <Plus size={15} className="shrink-0 text-muted-foreground" />
              <span className="min-w-0 flex-1 truncate">
                New card
                {newCardTitle && (
                  <>
                    : <span className="text-primary">“{newCardTitle}”</span>
                  </>
                )}
              </span>
              {!currentWorkspaceId && (
                <span className="shrink-0 text-[10px] text-muted-foreground/60">needs workspace</span>
              )}
            </Command.Item>
            {actionEntries.map((e) => renderItem(e))}
          </Command.Group>

          <Command.Group heading="Pages">{pageEntries.map((e) => renderItem(e))}</Command.Group>
        </Command.List>
      </Command>
    </div>
  );
}
