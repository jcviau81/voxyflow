import { Project } from '../../types';
import { eventBus } from '../../utils/EventBus';
import { EVENTS } from '../../utils/constants';
import { createElement, formatTime } from '../../utils/helpers';
import { appState } from '../../state/AppState';
import { projectService } from '../../services/ProjectService';

export class ProjectList {
  private container: HTMLElement;
  private listEl: HTMLElement | null = null;
  private unsubscribers: (() => void)[] = [];

  constructor(private parentElement: HTMLElement) {
    this.container = createElement('div', { className: 'project-list' });
    this.render();
    this.setupListeners();
  }

  render(): void {
    this.container.innerHTML = '';

    // Header
    const header = createElement('div', { className: 'project-list-header' });
    const title = createElement('h2', {}, 'Projects');
    const addBtn = createElement('button', { className: 'project-add-btn' }, '+ New Project');
    addBtn.addEventListener('click', () => this.promptNewProject());
    header.appendChild(title);
    header.appendChild(addBtn);

    // List
    this.listEl = createElement('div', { className: 'project-items' });
    this.refreshProjects();

    this.container.appendChild(header);
    this.container.appendChild(this.listEl);
    this.parentElement.appendChild(this.container);
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
  }

  private refreshProjects(): void {
    if (!this.listEl) return;
    this.listEl.innerHTML = '';

    const projects = projectService.list();
    const currentId = appState.get('currentProjectId');

    if (projects.length === 0) {
      const empty = createElement(
        'div',
        { className: 'empty-state' },
        'No projects yet. Create one to get started!'
      );
      this.listEl.appendChild(empty);
      return;
    }

    projects.forEach((project) => {
      const item = this.renderProjectItem(project, project.id === currentId);
      this.listEl!.appendChild(item);
    });
  }

  private renderProjectItem(project: Project, isActive: boolean): HTMLElement {
    const item = createElement('div', {
      className: `project-item ${isActive ? 'active' : ''}`,
      'data-project-id': project.id,
    });

    const info = createElement('div', { className: 'project-item-info' });
    const name = createElement('div', { className: 'project-item-name' }, project.name);
    const desc = createElement('div', { className: 'project-item-desc' }, project.description || 'No description');
    const meta = createElement('div', { className: 'project-item-meta' });
    const cardCount = createElement('span', {}, `${project.cards.length} cards`);
    const updated = createElement('span', {}, formatTime(project.updatedAt));
    meta.appendChild(cardCount);
    meta.appendChild(updated);

    info.appendChild(name);
    info.appendChild(desc);
    info.appendChild(meta);

    const actions = createElement('div', { className: 'project-item-actions' });
    const editBtn = createElement('button', { className: 'project-edit-btn' }, '✏️');
    editBtn.addEventListener('click', (e) => {
      e.stopPropagation();
      this.promptEditProject(project);
    });
    const deleteBtn = createElement('button', { className: 'project-delete-btn' }, '🗑️');
    deleteBtn.addEventListener('click', (e) => {
      e.stopPropagation();
      if (confirm(`Delete project "${project.name}"?`)) {
        projectService.delete(project.id);
      }
    });
    actions.appendChild(editBtn);
    actions.appendChild(deleteBtn);

    item.appendChild(info);
    item.appendChild(actions);

    item.addEventListener('click', () => {
      projectService.select(project.id);
      appState.setView('kanban');
    });

    return item;
  }

  private promptNewProject(): void {
    const name = prompt('Project name:');
    if (name?.trim()) {
      const desc = prompt('Description (optional):') || '';
      projectService.create(name.trim(), desc);
    }
  }

  private promptEditProject(project: Project): void {
    const name = prompt('Project name:', project.name);
    if (name?.trim()) {
      const desc = prompt('Description:', project.description) || '';
      projectService.update(project.id, { name: name.trim(), description: desc });
    }
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
