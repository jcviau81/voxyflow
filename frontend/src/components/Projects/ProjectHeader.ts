import { ViewMode } from '../../types';
import { createElement } from '../../utils/helpers';
import { appState } from '../../state/AppState';
import { eventBus } from '../../utils/EventBus';
import { EVENTS, SYSTEM_PROJECT_ID } from '../../utils/constants';

export interface ProjectTab {
  view: ViewMode;
  emoji: string;
  label: string;
}

const PROJECT_TABS: ProjectTab[] = [
  { view: 'chat',       emoji: '💬', label: 'Chat' },
  { view: 'kanban',     emoji: '📋', label: 'Kanban' },
  { view: 'freeboard',  emoji: '📌', label: 'Board' },
  { view: 'knowledge',  emoji: '🧠', label: 'Knowledge' },
  // Deferred (hidden, not deleted): stats, roadmap, wiki, sprint, docs
];

// Subset of tabs shown for the Main tab
const MAIN_TABS: ViewMode[] = ['chat', 'kanban', 'freeboard'];

export class ProjectHeader {
  private container: HTMLElement;
  private unsubscribers: (() => void)[] = [];

  constructor(private parentElement: HTMLElement) {
    this.container = createElement('div', {
      className: 'project-header',
      'data-testid': 'project-header',
    });
    this.render();
    this.setupListeners();
  }

  private render(): void {
    this.container.innerHTML = '';

    const activeTab = appState.getActiveTab();
    const isMainTab = activeTab === 'main';
    const projectId = appState.get('currentProjectId');
    const project = projectId ? appState.getProject(projectId) : null;
    const currentView = appState.get('currentView');

    // Visible for both Main tab and project tabs (with a project loaded)
    if (!isMainTab && !project) {
      this.container.style.display = 'none';
      if (!this.container.parentElement) {
        this.parentElement.appendChild(this.container);
      }
      return;
    }

    this.container.style.display = '';

    // Left: project icon + name (clickable → opens project properties)
    // For Main tab, show a simple title without click-to-edit
    const titleSection = createElement('div', { className: 'project-header__title' });
    if (isMainTab) {
      const emoji = createElement('span', { className: 'project-header__emoji' });
      emoji.textContent = '🏠';
      const name = createElement('span', { className: 'project-header__name' });
      name.textContent = 'Main';
      titleSection.appendChild(emoji);
      titleSection.appendChild(name);
    } else {
      titleSection.style.cursor = 'pointer';
      titleSection.title = 'Project properties';
      titleSection.addEventListener('click', () => {
        if (projectId) {
          eventBus.emit(EVENTS.PROJECT_PROPERTIES_OPEN, { projectId });
        }
      });
      const emoji = createElement('span', { className: 'project-header__emoji' });
      emoji.textContent = project!.emoji || '📁';
      const name = createElement('span', { className: 'project-header__name' });
      name.textContent = project!.name;
      titleSection.appendChild(emoji);
      titleSection.appendChild(name);
    }

    // Right: navigation tabs — Main gets a subset, projects get all
    const tabBar = createElement('nav', { className: 'project-header__tabs' });
    const visibleTabs = isMainTab
      ? PROJECT_TABS.filter(t => MAIN_TABS.includes(t.view))
      : PROJECT_TABS;

    for (const tab of visibleTabs) {
      const isActive = currentView === tab.view;
      const btn = createElement('button', {
        className: `project-header__tab${isActive ? ' project-header__tab--active' : ''}`,
        'data-view': tab.view,
      });
      btn.textContent = `${tab.emoji} ${tab.label}`;
      btn.addEventListener('click', () => {
        if (currentView !== tab.view) {
          appState.setView(tab.view);
        }
      });
      tabBar.appendChild(btn);
    }

    this.container.appendChild(titleSection);
    this.container.appendChild(tabBar);

    if (!this.container.parentElement) {
      this.parentElement.appendChild(this.container);
    }
  }

  private setupListeners(): void {
    // Re-render when view changes (active tab highlight)
    this.unsubscribers.push(
      eventBus.on(EVENTS.VIEW_CHANGE, () => this.render())
    );
    // Re-render when switching project tabs
    this.unsubscribers.push(
      eventBus.on(EVENTS.TAB_SWITCH, () => this.render())
    );
    // Re-render when project is updated (name/emoji change)
    this.unsubscribers.push(
      eventBus.on(EVENTS.PROJECT_UPDATED, () => this.render())
    );
    // Re-render when project is selected
    this.unsubscribers.push(
      eventBus.on(EVENTS.PROJECT_SELECTED, () => this.render())
    );
  }

  destroy(): void {
    this.unsubscribers.forEach((unsub) => unsub());
    this.unsubscribers = [];
    this.container.remove();
  }
}
