/**
 * WorkspaceList — React port of frontend/src/components/Workspaces/WorkspaceList.ts
 *
 * Sections:
 *   - Header: "Workspaces" title + "+ New Workspace" button
 *   - Summary bar: workspace/card/done counts
 *   - Filter chips: All | Active | Completed | Archived
 *   - Workspace grid: cards with emoji, name, description, tech stack,
 *     progress bar, stats, activity, quick actions
 */

import { useState, useCallback, useEffect } from 'react';
import { Star, Archive, Folder, LayoutGrid, CheckCircle2, BarChart2, Send, Pencil } from 'lucide-react';
import { useNavigate, useSearchParams, useOutletContext } from 'react-router-dom';
import { PageHeader } from '../layout/PageHeader';
import { cn } from '../../lib/utils';
import { useWorkspaces, useArchiveWorkspace, useDeleteWorkspace, useToggleFavorite, useExportWorkspace } from '../../hooks/api/useWorkspaces';
import { useWorkspaceStore } from '../../stores/useWorkspaceStore';
import { useCardStore } from '../../stores/useCardStore';
import { SYSTEM_WORKSPACE_ID } from '../../lib/constants';
import { WorkspaceForm } from './WorkspaceForm';
import type { Workspace } from '../../types';

// ─── Types ────────────────────────────────────────────────────────────────────

type FilterMode = 'all' | 'active' | 'completed' | 'archived';

interface CardStats {
  total: number;
  done: number;
  inProgress: number;
  todo: number;
  backlog: number;
  pct: number;
}

// ─── helpers ──────────────────────────────────────────────────────────────────

function formatTime(ts: number): string {
  const diff = Date.now() - ts;
  const minutes = Math.floor(diff / 60_000);
  if (minutes < 1) return 'just now';
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  return `${Math.floor(hours / 24)}d ago`;
}

// ─── Sub-component: WorkspaceCard ───────────────────────────────────────────────

interface WorkspaceCardProps {
  workspace: Workspace;
  isActive: boolean;
  stats: CardStats;
  onOpen: (workspace: Workspace) => void;
  onEdit: (workspace: Workspace) => void;
  onExport: (workspace: Workspace) => void;
  onToggleFavorite: (workspace: Workspace) => void;
  onArchive: (workspace: Workspace) => void;
  onRestore: (workspace: Workspace) => void;
  onDelete: (workspace: Workspace) => void;
}

function WorkspaceCard({
  workspace, isActive, stats,
  onOpen, onEdit, onExport, onToggleFavorite, onArchive, onRestore, onDelete,
}: WorkspaceCardProps) {
  const progressColorClass =
    stats.pct === 100 ? 'bg-green-500' :
    stats.pct >= 50   ? 'bg-yellow-400' :
    stats.pct > 0     ? 'bg-primary'    :
    'bg-muted-foreground/30';

  return (
    <div
      data-workspace-id={workspace.id}
      onClick={() => !workspace.archived && onOpen(workspace)}
      className={cn(
        'workspace-card-overview group relative flex flex-col gap-3 p-4 rounded-xl border bg-card',
        'transition-all duration-150',
        !workspace.archived && 'cursor-pointer hover:border-primary/50 hover:shadow-md',
        isActive && 'border-primary/70 ring-1 ring-primary/30'
      )}
    >
      {/* ── Card header ── */}
      <div className="workspace-card-header flex items-start gap-3">
        <span className="workspace-card-emoji text-2xl shrink-0 leading-none mt-0.5">
          {workspace.emoji || '📁'}
        </span>

        <div className="workspace-card-title-wrap flex-1 min-w-0">
          <div className="workspace-card-name font-semibold text-foreground truncate">
            {workspace.name}
          </div>
          {workspace.githubUrl && (
            <a
              href={workspace.githubUrl}
              target="_blank"
              rel="noopener noreferrer"
              title={workspace.githubUrl}
              onClick={(e) => e.stopPropagation()}
              className="workspace-card-gh-link text-xs text-primary hover:underline"
            >
              🔗 GitHub
            </a>
          )}
        </div>

        {/* Favorite star */}
        <button
          onClick={(e) => { e.stopPropagation(); onToggleFavorite(workspace); }}
          title={workspace.isFavorite ? 'Remove from favorites' : 'Add to favorites'}
          className="sidebar-favorite-star text-lg leading-none opacity-60 hover:opacity-100 transition-opacity shrink-0"
        >
          {workspace.isFavorite
            ? <Star size={16} className="fill-yellow-400 text-yellow-400" />
            : <Star size={16} className="text-muted-foreground" />
          }
        </button>

        {/* Archived badge */}
        {workspace.archived && (
          <span className="flex items-center gap-1 workspace-archived-badge px-2 py-0.5 rounded text-xs bg-yellow-500/10 text-yellow-600 border border-yellow-500/30 shrink-0">
            <Archive size={11} /> Archived
          </span>
        )}
      </div>

      {/* Color bar (if set) */}
      {workspace.color && (
        <div
          className="absolute top-0 left-0 w-1 h-full rounded-l-xl"
          style={{ background: workspace.color }}
        />
      )}

      {/* ── Description ── */}
      <p className="workspace-card-desc text-sm text-muted-foreground line-clamp-2">
        {workspace.description || 'No description'}
      </p>

      {/* ── Tech stack badges ── */}
      {(() => {
        const techs = workspace.techStack?.technologies;
        if (techs && techs.length > 0) {
          return (
            <div className="workspace-card-tech flex flex-wrap gap-1">
              {techs.slice(0, 6).map((t) => (
                <span
                  key={t.name}
                  className="workspace-tech-badge px-1.5 py-0.5 rounded text-[11px] bg-accent text-accent-foreground border border-border"
                >
                  {t.icon ? `${t.icon} ` : ''}{t.name}
                </span>
              ))}
              {techs.length > 6 && (
                <span className="workspace-tech-badge px-1.5 py-0.5 rounded text-[11px] bg-accent text-muted-foreground border border-border">
                  +{techs.length - 6}
                </span>
              )}
            </div>
          );
        }
        if (workspace.githubLanguage) {
          return (
            <div className="workspace-card-tech">
              <span className="workspace-tech-badge px-1.5 py-0.5 rounded text-[11px] bg-accent text-accent-foreground border border-border">
                {workspace.githubLanguage}
              </span>
            </div>
          );
        }
        return null;
      })()}

      {/* ── Progress bar ── */}
      <div>
        <div className="workspace-mini-progress h-1.5 w-full rounded-full bg-muted overflow-hidden">
          <div
            title={`${stats.pct}% done`}
            className={cn('workspace-mini-progress-fill h-full rounded-full transition-all', progressColorClass)}
            style={{ width: `${stats.pct}%` }}
          />
        </div>
        <div className="workspace-mini-progress-label text-xs text-muted-foreground mt-0.5">
          {stats.pct}% done
        </div>
      </div>

      {/* ── Stats row ── */}
      <div className="workspace-card-stats flex items-center gap-1.5 text-xs text-muted-foreground">
        <span className="workspace-card-stat">{stats.total} cards</span>
        <span className="workspace-card-stat-sep opacity-40">|</span>
        <span className="workspace-card-stat done text-green-500">{stats.done} done</span>
        <span className="workspace-card-stat-sep opacity-40">|</span>
        <span className="workspace-card-stat in-progress text-primary">{stats.inProgress} in progress</span>
      </div>

      {/* ── Last activity ── */}
      <div className="workspace-card-activity text-xs text-muted-foreground opacity-60">
        Updated {formatTime(workspace.updatedAt)}
      </div>

      {/* ── Quick actions ── */}
      <div
        className="workspace-card-actions flex flex-wrap gap-1.5 mt-1"
        onClick={(e) => e.stopPropagation()}
      >
        {workspace.archived ? (
          <>
            <ActionButton
              variant="primary"
              data-testid={`workspace-restore-${workspace.id}`}
              onClick={() => onRestore(workspace)}
            >
              ↩ Restore
            </ActionButton>
            <ActionButton
              variant="danger"
              onClick={() => onDelete(workspace)}
            >
              🗑️ Delete permanently
            </ActionButton>
          </>
        ) : (
          <>
            <ActionButton
              variant="primary"
              data-testid={`workspace-open-${workspace.id}`}
              onClick={() => onOpen(workspace)}
            >
              ▶ Open
            </ActionButton>
            <ActionButton onClick={() => onExport(workspace)}>
              <Send size={11} className="inline mr-1" /> Export
            </ActionButton>
            <ActionButton
              data-testid={`workspace-edit-${workspace.id}`}
              onClick={() => onEdit(workspace)}
            >
              <Pencil size={11} className="inline mr-1" /> Edit
            </ActionButton>
            {!workspace.isSystem && workspace.deletable !== false && (
              <ActionButton onClick={() => onArchive(workspace)}>
                <Archive size={11} className="inline mr-1" /> Archive
              </ActionButton>
            )}
          </>
        )}
      </div>
    </div>
  );
}

// ─── Tiny helper button ───────────────────────────────────────────────────────

function ActionButton({
  variant,
  children,
  onClick,
  ...props
}: {
  variant?: 'primary' | 'danger';
  children: React.ReactNode;
  onClick: () => void;
  [key: string]: unknown;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      {...props}
      className={cn(
        'workspace-card-action-btn px-2 py-1 rounded text-xs border transition-colors',
        variant === 'primary' && 'border-primary/50 text-primary hover:bg-primary/10',
        variant === 'danger'  && 'border-destructive/50 text-destructive hover:bg-destructive/10',
        !variant && 'border-border text-muted-foreground hover:bg-accent hover:text-foreground'
      )}
    >
      {children}
    </button>
  );
}

// ─── Main component ───────────────────────────────────────────────────────────

export function WorkspaceList() {
  const [filter, setFilter] = useState<FilterMode>('all');
  const [formState, setFormState] = useState<{
    open: boolean;
    mode: 'create' | 'edit';
    workspace?: Workspace;
  }>({ open: false, mode: 'create' });

  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();
  const { data: allWorkspacesRaw = [], isLoading } = useWorkspaces();

  // Auto-open form when navigating with ?new=1
  useEffect(() => {
    if (searchParams.get('new') === '1') {
      setFormState({ open: true, mode: 'create' });
      setSearchParams({}, { replace: true });
    }
  }, [searchParams, setSearchParams]);

  const { currentWorkspaceId } = useWorkspaceStore();
  const archiveMutation = useArchiveWorkspace();
  const deleteMutation = useDeleteWorkspace();
  const favoriteMutation = useToggleFavorite();
  const exportMutation = useExportWorkspace();

  // ── Derive card stats ─────────────────────────────────────────────────────
  const getStats = useCallback((workspace: Workspace): CardStats => {
    const cards = useCardStore.getState().getCardsByWorkspace(workspace.id);
    const total = cards.length;
    const done = cards.filter((c) => c.status === 'done').length;
    const inProgress = cards.filter((c) => c.status === 'in-progress').length;
    const todo = cards.filter((c) => c.status === 'todo').length;
    const backlog = cards.filter((c) => c.status === 'backlog').length;
    const pct = total > 0 ? Math.round((done / total) * 100) : 0;
    return { total, done, inProgress, todo, backlog, pct };
  }, []);

  const isCompleted = useCallback((p: Workspace) => {
    const { total, pct } = getStats(p);
    return total > 0 && pct === 100;
  }, [getStats]);

  // ── Split active vs archived ───────────────────────────────────────────────
  const activeWorkspaces = allWorkspacesRaw.filter((p) => !p.archived);
  const archivedWorkspaces = allWorkspacesRaw.filter((p) => p.archived);

  // ── Apply filter ──────────────────────────────────────────────────────────
  const isArchivedView = filter === 'archived';
  const baseList = isArchivedView ? archivedWorkspaces : activeWorkspaces;

  const filteredWorkspaces =
    filter === 'active'    ? baseList.filter((p) => !isCompleted(p)) :
    filter === 'completed' ? baseList.filter((p) => isCompleted(p)) :
    baseList;

  // ── Summary stats ─────────────────────────────────────────────────────────
  const totalCards = baseList.reduce((sum, p) => sum + getStats(p).total, 0);
  const totalDone  = baseList.reduce((sum, p) => sum + getStats(p).done, 0);

  const summaryStats: { label: string; value: string; icon: React.ReactNode }[] = isArchivedView
    ? [{ label: 'Archived', value: String(baseList.length), icon: <Archive size={22} /> }]
    : [
        { label: 'Workspaces',    value: String(activeWorkspaces.length), icon: <Folder size={22} /> },
        { label: 'Total cards', value: String(totalCards),            icon: <LayoutGrid size={22} /> },
        { label: 'Done',        value: String(totalDone),             icon: <CheckCircle2 size={22} /> },
        {
          label: 'Completion',
          value: totalCards > 0 ? `${Math.round((totalDone / totalCards) * 100)}%` : '—',
          icon: <BarChart2 size={22} />,
        },
      ];

  // ── Actions ───────────────────────────────────────────────────────────────
  function handleOpen(workspace: Workspace) {
    // System workspace lives on the home tab ('/'), not /workspace/system-main
    void navigate(workspace.id === SYSTEM_WORKSPACE_ID ? '/' : `/workspace/${workspace.id}`);
  }

  function handleEdit(workspace: Workspace) {
    setFormState({ open: true, mode: 'edit', workspace });
  }

  async function handleExport(workspace: Workspace) {
    const data = await exportMutation.mutateAsync(workspace.id);
    if (!data) return;
    const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `${workspace.name.replace(/[^a-z0-9]/gi, '-').toLowerCase()}-export.json`;
    a.click();
    URL.revokeObjectURL(url);
  }

  function handleArchive(workspace: Workspace) {
    if (confirm(`Archive "${workspace.name}"? It will be hidden from the main list.`)) {
      void archiveMutation.mutateAsync({ id: workspace.id });
    }
  }

  function handleRestore(workspace: Workspace) {
    void archiveMutation.mutateAsync({ id: workspace.id, restore: true });
  }

  function handleDelete(workspace: Workspace) {
    if (confirm(`Permanently delete "${workspace.name}"? This is irreversible — cards, chats, memory, knowledge graph, documents, and all sessions/workspace files for this workspace will be wiped. Use Archive if you want a safety net.`)) {
      void deleteMutation.mutateAsync(workspace.id);
    }
  }

  function handleToggleFavorite(workspace: Workspace) {
    void favoriteMutation.mutateAsync(workspace.id);
  }

  // ── Render ────────────────────────────────────────────────────────────────
  const { sidebarToggle } = useOutletContext<{ sidebarToggle: () => void }>();

  return (
    <>
      <PageHeader title="Workspaces" onSidebarToggle={sidebarToggle} />
      <div className="workspace-list p-6 space-y-5" data-testid="workspace-list">

        {/* ── Header ── */}
        <div className="workspace-list-header flex items-center justify-between">
          <h2 className="text-2xl font-bold text-foreground">Workspaces</h2>
          <button
            type="button"
            data-testid="new-workspace-btn"
            onClick={() => setFormState({ open: true, mode: 'create' })}
            className="workspace-add-btn px-4 py-2 rounded-lg bg-primary text-primary-foreground text-sm font-medium hover:opacity-90 transition-opacity"
          >
            + New Workspace
          </button>
        </div>

        {/* ── Summary bar ── */}
        <div className="workspace-summary-bar grid grid-cols-2 sm:grid-cols-4 gap-3">
          {summaryStats.map(({ label, value, icon }) => (
            <div
              key={label}
              className="workspace-summary-stat flex flex-col items-center gap-0.5 p-3 rounded-xl border border-border bg-card"
            >
              <span className="workspace-summary-icon text-muted-foreground">{icon}</span>
              <span className="workspace-summary-value text-xl font-bold text-foreground">{value}</span>
              <span className="workspace-summary-label text-xs text-muted-foreground">{label}</span>
            </div>
          ))}
        </div>

        {/* ── Filter chips ── */}
        <div className="workspace-filter-chips flex gap-2 flex-wrap">
          {([
            { key: 'all',       label: 'All' },
            { key: 'active',    label: 'Active' },
            { key: 'completed', label: 'Completed' },
            { key: 'archived',  label: 'Archived' },
          ] as { key: FilterMode; label: string }[]).map(({ key, label }) => (
            <button
              key={key}
              type="button"
              data-filter={key}
              onClick={() => setFilter(key)}
              className={cn(
                'workspace-filter-chip px-3 py-1.5 rounded-full text-sm border transition-colors',
                filter === key
                  ? 'active border-primary bg-primary/10 text-primary font-medium'
                  : 'border-border text-muted-foreground hover:border-primary/50 hover:text-foreground'
              )}
            >
              {label}
            </button>
          ))}
        </div>

        {/* ── Workspace grid ── */}
        {isLoading ? (
          <div className="text-muted-foreground text-sm py-8 text-center">Loading workspaces…</div>
        ) : filteredWorkspaces.length === 0 ? (
          <div className="empty-state text-muted-foreground text-sm py-8 text-center">
            {baseList.length === 0
              ? 'No workspaces yet. Create one to get started!'
              : 'No workspaces match this filter.'}
          </div>
        ) : (
          <div className="workspace-list-grid grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
            {filteredWorkspaces.map((workspace) => (
              <WorkspaceCard
                key={workspace.id}
                workspace={workspace}
                isActive={workspace.id === currentWorkspaceId}
                stats={getStats(workspace)}
                onOpen={handleOpen}
                onEdit={handleEdit}
                onExport={handleExport}
                onToggleFavorite={handleToggleFavorite}
                onArchive={handleArchive}
                onRestore={handleRestore}
                onDelete={handleDelete}
              />
            ))}
          </div>
        )}
      </div>

      {/* ── WorkspaceForm modal ── */}
      {formState.open && (
        <WorkspaceForm
          mode={formState.mode}
          workspace={formState.workspace}
          onClose={() => setFormState((s) => ({ ...s, open: false }))}
        />
      )}
    </>
  );
}
