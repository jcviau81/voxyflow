/**
 * ProjectList — React port of frontend/src/components/Projects/ProjectList.ts
 *
 * Sections:
 *   - Header: "Projects" title + "+ New Project" button
 *   - Summary bar: project/card/done counts
 *   - Filter chips: All | Active | Completed | Archived
 *   - Project grid: cards with emoji, name, description, tech stack,
 *     progress bar, stats, activity, quick actions
 */

import { useState, useCallback, useEffect } from 'react';
import { Star, Archive, Folder, LayoutGrid, CheckCircle2, BarChart2, Send, Pencil } from 'lucide-react';
import { useNavigate, useSearchParams, useOutletContext } from 'react-router-dom';
import { PageHeader } from '../layout/PageHeader';
import { cn } from '../../lib/utils';
import { useProjects, useArchiveProject, useDeleteProject, useToggleFavorite, useExportProject } from '../../hooks/api/useProjects';
import { useProjectStore } from '../../stores/useProjectStore';
import { useCardStore } from '../../stores/useCardStore';
import { ProjectForm } from './ProjectForm';
import type { Project } from '../../types';

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

// ─── Sub-component: ProjectCard ───────────────────────────────────────────────

interface ProjectCardProps {
  project: Project;
  isActive: boolean;
  stats: CardStats;
  onOpen: (project: Project) => void;
  onEdit: (project: Project) => void;
  onExport: (project: Project) => void;
  onToggleFavorite: (project: Project) => void;
  onArchive: (project: Project) => void;
  onRestore: (project: Project) => void;
  onDelete: (project: Project) => void;
}

function ProjectCard({
  project, isActive, stats,
  onOpen, onEdit, onExport, onToggleFavorite, onArchive, onRestore, onDelete,
}: ProjectCardProps) {
  const progressColorClass =
    stats.pct === 100 ? 'bg-green-500' :
    stats.pct >= 50   ? 'bg-yellow-400' :
    stats.pct > 0     ? 'bg-blue-400'   :
    'bg-muted-foreground/30';

  return (
    <div
      data-project-id={project.id}
      onClick={() => !project.archived && onOpen(project)}
      className={cn(
        'project-card-overview group relative flex flex-col gap-3 p-4 rounded-xl border bg-card',
        'transition-all duration-150',
        !project.archived && 'cursor-pointer hover:border-primary/50 hover:shadow-md',
        isActive && 'border-primary/70 ring-1 ring-primary/30'
      )}
    >
      {/* ── Card header ── */}
      <div className="project-card-header flex items-start gap-3">
        <span className="project-card-emoji text-2xl shrink-0 leading-none mt-0.5">
          {project.emoji || '📁'}
        </span>

        <div className="project-card-title-wrap flex-1 min-w-0">
          <div className="project-card-name font-semibold text-foreground truncate">
            {project.name}
          </div>
          {project.githubUrl && (
            <a
              href={project.githubUrl}
              target="_blank"
              rel="noopener noreferrer"
              title={project.githubUrl}
              onClick={(e) => e.stopPropagation()}
              className="project-card-gh-link text-xs text-primary hover:underline"
            >
              🔗 GitHub
            </a>
          )}
        </div>

        {/* Favorite star */}
        <button
          onClick={(e) => { e.stopPropagation(); onToggleFavorite(project); }}
          title={project.isFavorite ? 'Remove from favorites' : 'Add to favorites'}
          className="sidebar-favorite-star text-lg leading-none opacity-60 hover:opacity-100 transition-opacity shrink-0"
        >
          {project.isFavorite
            ? <Star size={16} className="fill-yellow-400 text-yellow-400" />
            : <Star size={16} className="text-muted-foreground" />
          }
        </button>

        {/* Archived badge */}
        {project.archived && (
          <span className="flex items-center gap-1 project-archived-badge px-2 py-0.5 rounded text-xs bg-yellow-500/10 text-yellow-600 border border-yellow-500/30 shrink-0">
            <Archive size={11} /> Archived
          </span>
        )}
      </div>

      {/* Color bar (if set) */}
      {project.color && (
        <div
          className="absolute top-0 left-0 w-1 h-full rounded-l-xl"
          style={{ background: project.color }}
        />
      )}

      {/* ── Description ── */}
      <p className="project-card-desc text-sm text-muted-foreground line-clamp-2">
        {project.description || 'No description'}
      </p>

      {/* ── Tech stack badges ── */}
      {(() => {
        const techs = project.techStack?.technologies;
        if (techs && techs.length > 0) {
          return (
            <div className="project-card-tech flex flex-wrap gap-1">
              {techs.slice(0, 6).map((t) => (
                <span
                  key={t.name}
                  className="project-tech-badge px-1.5 py-0.5 rounded text-[11px] bg-accent text-accent-foreground border border-border"
                >
                  {t.icon ? `${t.icon} ` : ''}{t.name}
                </span>
              ))}
              {techs.length > 6 && (
                <span className="project-tech-badge px-1.5 py-0.5 rounded text-[11px] bg-accent text-muted-foreground border border-border">
                  +{techs.length - 6}
                </span>
              )}
            </div>
          );
        }
        if (project.githubLanguage) {
          return (
            <div className="project-card-tech">
              <span className="project-tech-badge px-1.5 py-0.5 rounded text-[11px] bg-accent text-accent-foreground border border-border">
                {project.githubLanguage}
              </span>
            </div>
          );
        }
        return null;
      })()}

      {/* ── Progress bar ── */}
      <div>
        <div className="project-mini-progress h-1.5 w-full rounded-full bg-muted overflow-hidden">
          <div
            title={`${stats.pct}% done`}
            className={cn('project-mini-progress-fill h-full rounded-full transition-all', progressColorClass)}
            style={{ width: `${stats.pct}%` }}
          />
        </div>
        <div className="project-mini-progress-label text-xs text-muted-foreground mt-0.5">
          {stats.pct}% done
        </div>
      </div>

      {/* ── Stats row ── */}
      <div className="project-card-stats flex items-center gap-1.5 text-xs text-muted-foreground">
        <span className="project-card-stat">{stats.total} cards</span>
        <span className="project-card-stat-sep opacity-40">|</span>
        <span className="project-card-stat done text-green-500">{stats.done} done</span>
        <span className="project-card-stat-sep opacity-40">|</span>
        <span className="project-card-stat in-progress text-blue-400">{stats.inProgress} in progress</span>
      </div>

      {/* ── Last activity ── */}
      <div className="project-card-activity text-xs text-muted-foreground opacity-60">
        Updated {formatTime(project.updatedAt)}
      </div>

      {/* ── Quick actions ── */}
      <div
        className="project-card-actions flex flex-wrap gap-1.5 mt-1"
        onClick={(e) => e.stopPropagation()}
      >
        {project.archived ? (
          <>
            <ActionButton
              variant="primary"
              data-testid={`project-restore-${project.id}`}
              onClick={() => onRestore(project)}
            >
              ↩ Restore
            </ActionButton>
            <ActionButton
              variant="danger"
              onClick={() => onDelete(project)}
            >
              🗑️ Delete permanently
            </ActionButton>
          </>
        ) : (
          <>
            <ActionButton
              variant="primary"
              data-testid={`project-open-${project.id}`}
              onClick={() => onOpen(project)}
            >
              ▶ Open
            </ActionButton>
            <ActionButton onClick={() => onExport(project)}>
              <Send size={11} className="inline mr-1" /> Export
            </ActionButton>
            <ActionButton
              data-testid={`project-edit-${project.id}`}
              onClick={() => onEdit(project)}
            >
              <Pencil size={11} className="inline mr-1" /> Edit
            </ActionButton>
            {!project.isSystem && project.deletable !== false && (
              <ActionButton onClick={() => onArchive(project)}>
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
        'project-card-action-btn px-2 py-1 rounded text-xs border transition-colors',
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

export function ProjectList() {
  const [filter, setFilter] = useState<FilterMode>('all');
  const [formState, setFormState] = useState<{
    open: boolean;
    mode: 'create' | 'edit';
    project?: Project;
  }>({ open: false, mode: 'create' });

  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();
  const { data: allProjectsRaw = [], isLoading } = useProjects();

  // Auto-open form when navigating with ?new=1
  useEffect(() => {
    if (searchParams.get('new') === '1') {
      setFormState({ open: true, mode: 'create' });
      setSearchParams({}, { replace: true });
    }
  }, [searchParams, setSearchParams]);

  const { currentProjectId } = useProjectStore();
  const archiveMutation = useArchiveProject();
  const deleteMutation = useDeleteProject();
  const favoriteMutation = useToggleFavorite();
  const exportMutation = useExportProject();

  // ── Derive card stats ─────────────────────────────────────────────────────
  const getStats = useCallback((project: Project): CardStats => {
    const cards = useCardStore.getState().getCardsByProject(project.id);
    const total = cards.length;
    const done = cards.filter((c) => c.status === 'done').length;
    const inProgress = cards.filter((c) => c.status === 'in-progress').length;
    const todo = cards.filter((c) => c.status === 'todo').length;
    const backlog = cards.filter((c) => c.status === 'card').length;
    const pct = total > 0 ? Math.round((done / total) * 100) : 0;
    return { total, done, inProgress, todo, backlog, pct };
  }, []);

  const isCompleted = useCallback((p: Project) => {
    const { total, pct } = getStats(p);
    return total > 0 && pct === 100;
  }, [getStats]);

  // ── Split active vs archived ───────────────────────────────────────────────
  const activeProjects = allProjectsRaw.filter((p) => !p.archived);
  const archivedProjects = allProjectsRaw.filter((p) => p.archived);

  // ── Apply filter ──────────────────────────────────────────────────────────
  const isArchivedView = filter === 'archived';
  const baseList = isArchivedView ? archivedProjects : activeProjects;

  const filteredProjects =
    filter === 'active'    ? baseList.filter((p) => !isCompleted(p)) :
    filter === 'completed' ? baseList.filter((p) => isCompleted(p)) :
    baseList;

  // ── Summary stats ─────────────────────────────────────────────────────────
  const totalCards = baseList.reduce((sum, p) => sum + getStats(p).total, 0);
  const totalDone  = baseList.reduce((sum, p) => sum + getStats(p).done, 0);

  const summaryStats: { label: string; value: string; icon: React.ReactNode }[] = isArchivedView
    ? [{ label: 'Archived', value: String(baseList.length), icon: <Archive size={22} /> }]
    : [
        { label: 'Projects',    value: String(activeProjects.length), icon: <Folder size={22} /> },
        { label: 'Total cards', value: String(totalCards),            icon: <LayoutGrid size={22} /> },
        { label: 'Done',        value: String(totalDone),             icon: <CheckCircle2 size={22} /> },
        {
          label: 'Completion',
          value: totalCards > 0 ? `${Math.round((totalDone / totalCards) * 100)}%` : '—',
          icon: <BarChart2 size={22} />,
        },
      ];

  // ── Actions ───────────────────────────────────────────────────────────────
  function handleOpen(project: Project) {
    void navigate(`/project/${project.id}`);
  }

  function handleEdit(project: Project) {
    setFormState({ open: true, mode: 'edit', project });
  }

  async function handleExport(project: Project) {
    const data = await exportMutation.mutateAsync(project.id);
    if (!data) return;
    const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `${project.name.replace(/[^a-z0-9]/gi, '-').toLowerCase()}-export.json`;
    a.click();
    URL.revokeObjectURL(url);
  }

  function handleArchive(project: Project) {
    if (confirm(`Archive "${project.name}"? It will be hidden from the main list.`)) {
      void archiveMutation.mutateAsync({ id: project.id });
    }
  }

  function handleRestore(project: Project) {
    void archiveMutation.mutateAsync({ id: project.id, restore: true });
  }

  function handleDelete(project: Project) {
    if (confirm(`Permanently delete "${project.name}"? This cannot be undone. All cards, history, and knowledge will be lost.`)) {
      void deleteMutation.mutateAsync(project.id);
    }
  }

  function handleToggleFavorite(project: Project) {
    void favoriteMutation.mutateAsync(project.id);
  }

  // ── Render ────────────────────────────────────────────────────────────────
  const { sidebarToggle } = useOutletContext<{ sidebarToggle: () => void }>();

  return (
    <>
      <PageHeader title="Projects" onSidebarToggle={sidebarToggle} />
      <div className="project-list p-6 space-y-5" data-testid="project-list">

        {/* ── Header ── */}
        <div className="project-list-header flex items-center justify-between">
          <h2 className="text-2xl font-bold text-foreground">Projects</h2>
          <button
            type="button"
            data-testid="new-project-btn"
            onClick={() => setFormState({ open: true, mode: 'create' })}
            className="project-add-btn px-4 py-2 rounded-lg bg-primary text-primary-foreground text-sm font-medium hover:opacity-90 transition-opacity"
          >
            + New Project
          </button>
        </div>

        {/* ── Summary bar ── */}
        <div className="project-summary-bar grid grid-cols-2 sm:grid-cols-4 gap-3">
          {summaryStats.map(({ label, value, icon }) => (
            <div
              key={label}
              className="project-summary-stat flex flex-col items-center gap-0.5 p-3 rounded-xl border border-border bg-card"
            >
              <span className="project-summary-icon text-muted-foreground">{icon}</span>
              <span className="project-summary-value text-xl font-bold text-foreground">{value}</span>
              <span className="project-summary-label text-xs text-muted-foreground">{label}</span>
            </div>
          ))}
        </div>

        {/* ── Filter chips ── */}
        <div className="project-filter-chips flex gap-2 flex-wrap">
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
                'project-filter-chip px-3 py-1.5 rounded-full text-sm border transition-colors',
                filter === key
                  ? 'active border-primary bg-primary/10 text-primary font-medium'
                  : 'border-border text-muted-foreground hover:border-primary/50 hover:text-foreground'
              )}
            >
              {label}
            </button>
          ))}
        </div>

        {/* ── Project grid ── */}
        {isLoading ? (
          <div className="text-muted-foreground text-sm py-8 text-center">Loading projects…</div>
        ) : filteredProjects.length === 0 ? (
          <div className="empty-state text-muted-foreground text-sm py-8 text-center">
            {baseList.length === 0
              ? 'No projects yet. Create one to get started!'
              : 'No projects match this filter.'}
          </div>
        ) : (
          <div className="project-list-grid grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
            {filteredProjects.map((project) => (
              <ProjectCard
                key={project.id}
                project={project}
                isActive={project.id === currentProjectId}
                stats={getStats(project)}
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

      {/* ── ProjectForm modal ── */}
      {formState.open && (
        <ProjectForm
          mode={formState.mode}
          project={formState.project}
          onClose={() => setFormState((s) => ({ ...s, open: false }))}
        />
      )}
    </>
  );
}
