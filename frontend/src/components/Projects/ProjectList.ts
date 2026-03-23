import { Project } from '../../types';
import { eventBus } from '../../utils/EventBus';
import { EVENTS } from '../../utils/constants';
import { createElement, formatTime } from '../../utils/helpers';
import { appState } from '../../state/AppState';
import { projectService } from '../../services/ProjectService';
import { apiClient } from '../../services/ApiClient';

type FilterMode = 'all' | 'active' | 'completed' | 'archived';

export class ProjectList {
  private container: HTMLElement;
  private listEl: HTMLElement | null = null;
  private summaryEl: HTMLElement | null = null;
  private filterEl: HTMLElement | null = null;
  private currentFilter: FilterMode = 'all';
  private unsubscribers: (() => void)[] = [];

  constructor(private parentElement: HTMLElement) {
    this.container = createElement('div', { className: 'project-list', 'data-testid': 'project-list' });
    this.render();
    this.setupListeners();
  }

  render(): void {
    this.container.innerHTML = '';

    // ── Header ──────────────────────────────────────────────────────────
    const header = createElement('div', { className: 'project-list-header' });
    const title = createElement('h2', {}, 'Projects');
    const addBtn = createElement('button', {
      className: 'project-add-btn',
      'data-testid': 'new-project-btn',
    }, '+ New Project');
    addBtn.addEventListener('click', () => {
      eventBus.emit(EVENTS.PROJECT_FORM_SHOW, { mode: 'create' });
    });
    header.appendChild(title);
    header.appendChild(addBtn);

    // ── Summary bar ─────────────────────────────────────────────────────
    this.summaryEl = createElement('div', { className: 'project-summary-bar' });

    // ── Filter chips ────────────────────────────────────────────────────
    this.filterEl = createElement('div', { className: 'project-filter-chips' });
    this.renderFilterChips(this.filterEl);

    // ── Grid ────────────────────────────────────────────────────────────
    this.listEl = createElement('div', { className: 'project-list-grid' });

    this.refreshProjects();

    this.container.appendChild(header);
    this.container.appendChild(this.summaryEl);
    this.container.appendChild(this.filterEl);
    this.container.appendChild(this.listEl);
    this.parentElement.appendChild(this.container);
  }

  private renderFilterChips(container: HTMLElement): void {
    container.innerHTML = '';
    const filters: { key: FilterMode; label: string }[] = [
      { key: 'all', label: 'All' },
      { key: 'active', label: 'Active' },
      { key: 'completed', label: 'Completed' },
      { key: 'archived', label: '📦 Archived' },
    ];
    filters.forEach(({ key, label }) => {
      const chip = createElement('button', {
        className: `project-filter-chip ${this.currentFilter === key ? 'active' : ''}`,
        'data-filter': key,
      }, label);
      chip.addEventListener('click', () => {
        this.currentFilter = key;
        this.refreshProjects();
        // Update chip active states
        container.querySelectorAll('.project-filter-chip').forEach((el) => {
          el.classList.toggle('active', (el as HTMLElement).dataset.filter === key);
        });
      });
      container.appendChild(chip);
    });
  }

  private setupListeners(): void {
    this.unsubscribers.push(
      eventBus.on(EVENTS.PROJECT_CREATED, () => this.refreshProjects())
    );
    this.unsubscribers.push(
      eventBus.on(EVENTS.PROJECT_UPDATED, () => this.refreshProjects())
    );
    this.unsubscribers.push(
      eventBus.on(EVENTS.PROJECT_DELETED, () => this.refreshProjects())
    );
    this.unsubscribers.push(
      eventBus.on(EVENTS.CARD_CREATED, () => this.refreshProjects())
    );
    this.unsubscribers.push(
      eventBus.on(EVENTS.CARD_UPDATED, () => this.refreshProjects())
    );
    this.unsubscribers.push(
      eventBus.on(EVENTS.CARD_DELETED, () => this.refreshProjects())
    );
    this.unsubscribers.push(
      eventBus.on(EVENTS.CARD_MOVED, () => this.refreshProjects())
    );
    // Listen for filter switch from sidebar archived link
    this.unsubscribers.push(
      eventBus.on('PROJECT_LIST_FILTER' as any, (payload: unknown) => {
        const { filter } = payload as { filter: FilterMode };
        this.currentFilter = filter;
        this.refreshProjects();
        // Update chip active states
        if (this.filterEl) {
          this.filterEl.querySelectorAll('.project-filter-chip').forEach((el) => {
            el.classList.toggle('active', (el as HTMLElement).dataset.filter === filter);
          });
        }
      })
    );
  }

  private getProjectStats(project: Project): {
    total: number;
    done: number;
    inProgress: number;
    todo: number;
    ideas: number;
    pct: number;
  } {
    const cards = appState.getCardsByProject(project.id);
    const total = cards.length;
    const done = cards.filter((c) => c.status === 'done').length;
    const inProgress = cards.filter((c) => c.status === 'in-progress').length;
    const todo = cards.filter((c) => c.status === 'todo').length;
    const ideas = cards.filter((c) => c.status === 'idea').length;
    const pct = total > 0 ? Math.round((done / total) * 100) : 0;
    return { total, done, inProgress, todo, ideas, pct };
  }

  private isProjectCompleted(project: Project): boolean {
    const { total, done, pct } = this.getProjectStats(project);
    return total > 0 && pct === 100;
  }

  private refreshProjects(): void {
    if (!this.listEl || !this.summaryEl) return;
    this.listEl.innerHTML = '';

    const isArchivedView = this.currentFilter === 'archived';
    const allProjects = isArchivedView ? projectService.listArchived() : projectService.list();

    // ── Summary stats ───────────────────────────────────────────────────
    const totalCards = allProjects.reduce((sum, p) => {
      return sum + appState.getCardsByProject(p.id).length;
    }, 0);
    const totalDone = allProjects.reduce((sum, p) => {
      return sum + appState.getCardsByProject(p.id).filter((c) => c.status === 'done').length;
    }, 0);

    this.summaryEl.innerHTML = '';
    const stats = isArchivedView
      ? [{ label: 'Archived', value: String(allProjects.length), icon: '📦' }]
      : [
          { label: 'Projects', value: String(allProjects.length), icon: '📁' },
          { label: 'Total cards', value: String(totalCards), icon: '🃏' },
          { label: 'Done', value: String(totalDone), icon: '✅' },
          { label: 'Completion', value: totalCards > 0 ? `${Math.round((totalDone / totalCards) * 100)}%` : '—', icon: '📊' },
        ];
    stats.forEach(({ label, value, icon }) => {
      const stat = createElement('div', { className: 'project-summary-stat' });
      stat.appendChild(createElement('span', { className: 'project-summary-icon' }, icon));
      stat.appendChild(createElement('span', { className: 'project-summary-value' }, value));
      stat.appendChild(createElement('span', { className: 'project-summary-label' }, label));
      this.summaryEl!.appendChild(stat);
    });

    // ── Filter ──────────────────────────────────────────────────────────
    let projects = allProjects;
    if (this.currentFilter === 'active') {
      projects = allProjects.filter((p) => !this.isProjectCompleted(p));
    } else if (this.currentFilter === 'completed') {
      projects = allProjects.filter((p) => this.isProjectCompleted(p));
    }

    if (projects.length === 0) {
      const empty = createElement(
        'div',
        { className: 'empty-state' },
        allProjects.length === 0
          ? 'No projects yet. Create one to get started!'
          : 'No projects match this filter.'
      );
      this.listEl.appendChild(empty);
      return;
    }

    const currentId = appState.get('currentProjectId');
    projects.forEach((project) => {
      const card = this.renderProjectCard(project, project.id === currentId);
      this.listEl!.appendChild(card);
    });
  }

  private renderProjectCard(project: Project, isActive: boolean): HTMLElement {
    const stats = this.getProjectStats(project);

    const card = createElement('div', {
      className: `project-card-overview ${isActive ? 'active' : ''}`,
      'data-project-id': project.id,
    });

    // ── Card header ─────────────────────────────────────────────────────
    const cardHeader = createElement('div', { className: 'project-card-header' });
    const emojiEl = createElement('span', { className: 'project-card-emoji' }, project.emoji || '📁');
    const titleWrap = createElement('div', { className: 'project-card-title-wrap' });
    const nameEl = createElement('div', { className: 'project-card-name' }, project.name);
    titleWrap.appendChild(nameEl);

    // GitHub link
    if (project.githubUrl) {
      const ghLink = createElement('a', {
        className: 'project-card-gh-link',
        href: project.githubUrl,
        target: '_blank',
        rel: 'noopener noreferrer',
        title: project.githubUrl,
      }, '🔗 GitHub');
      ghLink.addEventListener('click', (e) => e.stopPropagation());
      titleWrap.appendChild(ghLink);
    }

    cardHeader.appendChild(emojiEl);
    cardHeader.appendChild(titleWrap);

    // Favorite star toggle
    const starBtn = createElement('span', {
      className: 'sidebar-favorite-star',
      title: project.isFavorite ? 'Remove from favorites' : 'Add to favorites',
    }, project.isFavorite ? '⭐' : '☆');
    starBtn.style.cursor = 'pointer';
    starBtn.style.fontSize = '1.2rem';
    starBtn.style.marginLeft = 'auto';
    starBtn.addEventListener('click', async (e) => {
      e.stopPropagation();
      const { apiClient } = await import('../../services/ApiClient');
      await apiClient.toggleFavorite(project.id);
      this.render();
    });
    cardHeader.appendChild(starBtn);

    // Archived badge
    if (project.archived) {
      const badge = createElement('span', { className: 'project-archived-badge' }, '📦 Archived');
      cardHeader.appendChild(badge);
    }

    // ── Description ─────────────────────────────────────────────────────
    const descEl = createElement('div', { className: 'project-card-desc' }, project.description || 'No description');

    // ── Tech stack badges ────────────────────────────────────────────────
    let techEl: HTMLElement | null = null;
    if (project.techStack && project.techStack.technologies && project.techStack.technologies.length > 0) {
      techEl = createElement('div', { className: 'project-card-tech' });
      const techs = project.techStack.technologies.slice(0, 6);
      techs.forEach((tech) => {
        const badge = createElement('span', { className: 'project-tech-badge' }, `${tech.icon || ''} ${tech.name}`.trim());
        techEl!.appendChild(badge);
      });
      if (project.techStack.technologies.length > 6) {
        const more = createElement('span', { className: 'project-tech-badge project-tech-more' },
          `+${project.techStack.technologies.length - 6}`);
        techEl.appendChild(more);
      }
    } else if (project.githubLanguage) {
      techEl = createElement('div', { className: 'project-card-tech' });
      const badge = createElement('span', { className: 'project-tech-badge' }, project.githubLanguage);
      techEl.appendChild(badge);
    }

    // ── Progress bar ─────────────────────────────────────────────────────
    const progressWrap = createElement('div', { className: 'project-mini-progress' });
    const progressBar = createElement('div', {
      className: 'project-mini-progress-fill',
      style: `width: ${stats.pct}%`,
      title: `${stats.pct}% done`,
    });
    // Color based on progress
    if (stats.pct === 100) {
      progressBar.classList.add('done');
    } else if (stats.pct >= 50) {
      progressBar.classList.add('halfway');
    } else if (stats.pct > 0) {
      progressBar.classList.add('started');
    }
    progressWrap.appendChild(progressBar);

    const progressLabel = createElement('div', { className: 'project-mini-progress-label' }, `${stats.pct}% done`);

    // ── Card count stats ──────────────────────────────────────────────────
    const statsRow = createElement('div', { className: 'project-card-stats' });
    const statItems = [
      { label: `${stats.total} cards`, cls: '' },
      { label: `${stats.done} done`, cls: 'done' },
      { label: `${stats.inProgress} in progress`, cls: 'in-progress' },
    ];
    statItems.forEach(({ label, cls }, i) => {
      if (i > 0) {
        statsRow.appendChild(createElement('span', { className: 'project-card-stat-sep' }, '|'));
      }
      const span = createElement('span', { className: `project-card-stat ${cls}` }, label);
      statsRow.appendChild(span);
    });

    // ── Recent activity ───────────────────────────────────────────────────
    const activities = appState.getActivities(project.id, 1);
    const activityEl = createElement('div', { className: 'project-card-activity' });
    if (activities.length > 0) {
      activityEl.textContent = `Last activity: ${formatTime(activities[0].timestamp)}`;
    } else {
      activityEl.textContent = `Updated ${formatTime(project.updatedAt)}`;
    }

    // ── Quick actions ─────────────────────────────────────────────────────
    const actions = createElement('div', { className: 'project-card-actions' });

    if (project.archived) {
      // Archived project actions: Restore + Delete permanently
      const restoreBtn = createElement('button', {
        className: 'project-card-action-btn primary',
        title: 'Restore project',
      }, '↩ Restore');
      restoreBtn.addEventListener('click', (e) => {
        e.stopPropagation();
        projectService.unarchive(project.id);
      });

      const deleteBtn = createElement('button', {
        className: 'project-card-action-btn danger',
        title: 'Delete permanently',
      }, '🗑️ Delete permanently');
      deleteBtn.addEventListener('click', (e) => {
        e.stopPropagation();
        if (confirm(`Permanently delete "${project.name}"? This cannot be undone. All cards, history, and knowledge will be lost.`)) {
          projectService.delete(project.id);
        }
      });

      actions.appendChild(restoreBtn);
      actions.appendChild(deleteBtn);
    } else {
      // Active project actions
      const openBtn = createElement('button', {
        className: 'project-card-action-btn primary',
        'data-testid': `project-open-${project.id}`,
        title: 'Open project',
      }, '▶ Open');
      openBtn.addEventListener('click', (e) => {
        e.stopPropagation();
        projectService.select(project.id);
        appState.setView('kanban');
      });

      const exportBtn = createElement('button', {
        className: 'project-card-action-btn',
        title: 'Export project',
      }, '📤 Export');
      exportBtn.addEventListener('click', (e) => {
        e.stopPropagation();
        this.exportProject(project);
      });

      const editBtn = createElement('button', {
        className: 'project-card-action-btn',
        'data-testid': `project-edit-${project.id}`,
        title: 'Edit project',
      }, '✏️ Edit');
      editBtn.addEventListener('click', (e) => {
        e.stopPropagation();
        eventBus.emit(EVENTS.PROJECT_FORM_SHOW, { mode: 'edit', project });
      });

      // Hide archive/delete for system projects (Main)
      const archiveBtn = createElement('button', {
        className: 'project-card-action-btn',
        title: 'Archive project',
      }, '📦 Archive');
      archiveBtn.addEventListener('click', (e) => {
        e.stopPropagation();
        if (confirm(`Archive "${project.name}"? It will be hidden from the main list.`)) {
          projectService.archive(project.id);
        }
      });
      if (project.isSystem || project.deletable === false) {
        archiveBtn.style.display = 'none';
      }

      // No delete button on active projects — archive first, delete from Archived view only

      actions.appendChild(openBtn);
      actions.appendChild(exportBtn);
      actions.appendChild(editBtn);
      actions.appendChild(archiveBtn);
    }

    // ── Assemble card ─────────────────────────────────────────────────────
    card.appendChild(cardHeader);
    card.appendChild(descEl);
    if (techEl) card.appendChild(techEl);
    card.appendChild(progressWrap);
    card.appendChild(progressLabel);
    card.appendChild(statsRow);
    card.appendChild(activityEl);
    card.appendChild(actions);

    // Click whole card → open project (only for active projects)
    if (!project.archived) {
      card.addEventListener('click', () => {
        projectService.select(project.id);
        appState.setView('kanban');
      });
    }

    return card;
  }

  private async exportProject(project: Project): Promise<void> {
    const data = await apiClient.exportProject(project.id);
    if (!data) {
      console.error('[ProjectList] Export failed for project', project.id);
      return;
    }
    const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `${project.name.replace(/[^a-z0-9]/gi, '-').toLowerCase()}-export.json`;
    a.click();
    URL.revokeObjectURL(url);
  }

  update(): void {
    this.refreshProjects();
  }

  destroy(): void {
    this.unsubscribers.forEach((unsub) => unsub());
    this.unsubscribers = [];
    this.container.remove();
  }
}
