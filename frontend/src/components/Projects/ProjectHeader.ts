import { ViewMode } from '../../types';
import { eventBus } from '../../utils/EventBus';
import { EVENTS } from '../../utils/constants';
import { createElement } from '../../utils/helpers';
import { appState } from '../../state/AppState';

interface ProjectTab {
  view: ViewMode;
  emoji: string;
  label: string;
}

const PROJECT_TABS: ProjectTab[] = [
  { view: 'chat', emoji: '💬', label: 'Chat' },
  { view: 'kanban', emoji: '📋', label: 'Kanban' },
  { view: 'stats', emoji: '📊', label: 'Stats' },
  { view: 'roadmap', emoji: '📅', label: 'Roadmap' },
  { view: 'wiki', emoji: '📖', label: 'Wiki' },
  { view: 'sprint', emoji: '🏃', label: 'Sprints' },
  { view: 'docs', emoji: '📚', label: 'Docs' },
];

export class ProjectHeader {
  private container: HTMLElement;
  private parentElement: HTMLElement;
  private tabButtons: Map<ViewMode, HTMLElement> = new Map();
  private nameEl: HTMLElement | null = null;
  private emojiEl: HTMLElement | null = null;
  private unsubscribers: (() => void)[] = [];

  constructor(parentElement: HTMLElement) {
    this.parentElement = parentElement;
    this.container = createElement('div', { className: 'project-header' });
    this.render();
    this.setupListeners();
    this.parentElement.appendChild(this.container);
    this.updateVisibility();
  }

  private render(): void {
    this.container.innerHTML = '';
    this.tabButtons.clear();

    // Left: project icon + name
    const projectInfo = createElement('div', { className: 'project-header-info' });
    this.emojiEl = createElement('span', { className: 'project-header-emoji' });
    this.nameEl = createElement('span', { className: 'project-header-name' });
    projectInfo.appendChild(this.emojiEl);
    projectInfo.appendChild(this.nameEl);

    // Tab bar
    const tabBar = createElement('div', { className: 'project-header-tabs' });

    for (const tab of PROJECT_TABS) {
      const btn = createElement('button', {
        className: 'project-header-tab',
        'data-view': tab.view,
      }, `${tab.emoji} ${tab.label}`);

      btn.addEventListener('click', () => {
        appState.setView(tab.view);
      });

      tabBar.appendChild(btn);
      this.tabButtons.set(tab.view, btn);
    }

    this.container.appendChild(projectInfo);
    this.container.appendChild(tabBar);

    this.updateProjectInfo();
    this.updateActiveTab();
  }

  private setupListeners(): void {
    this.unsubscribers.push(
      eventBus.on(EVENTS.VIEW_CHANGE, () => {
        this.updateActiveTab();
      }),
      eventBus.on(EVENTS.PROJECT_SELECTED, () => {
        this.updateProjectInfo();
        this.updateVisibility();
      }),
      eventBus.on(EVENTS.PROJECT_UPDATED, () => {
        this.updateProjectInfo();
      }),
      eventBus.on(EVENTS.TAB_SWITCH, () => {
        this.updateProjectInfo();
        this.updateVisibility();
      }),
      eventBus.on(EVENTS.STATE_CHANGED, (payload: unknown) => {
        const data = payload as { key: string };
        if (data?.key === 'activeTab' || data?.key === 'currentProjectId') {
          this.updateProjectInfo();
          this.updateVisibility();
        }
      }),
    );
  }

  private updateProjectInfo(): void {
    const projectId = appState.get('currentProjectId');
    const project = projectId ? appState.getProject(projectId) : null;

    if (this.emojiEl) {
      this.emojiEl.textContent = project?.emoji || '📁';
    }
    if (this.nameEl) {
      this.nameEl.textContent = project?.name || '';
    }
  }

  private updateActiveTab(): void {
    const currentView = appState.get('currentView');
    this.tabButtons.forEach((btn, view) => {
      btn.classList.toggle('active', view === currentView);
    });
  }

  private updateVisibility(): void {
    const activeTab = appState.getActiveTab();
    const isProjectMode = activeTab !== 'main';
    this.container.style.display = isProjectMode ? 'flex' : 'none';
  }

  destroy(): void {
    this.unsubscribers.forEach((unsub) => unsub());
    this.container.remove();
  }
}
