import { createElement } from '../../utils/helpers';
import { eventBus } from '../../utils/EventBus';
import { EVENTS } from '../../utils/constants';
import { appState } from '../../state/AppState';

export class TopBar {
  private container: HTMLElement;
  private unsubscribers: (() => void)[] = [];
  private opportunitiesCount: number = 0;

  constructor(private parentElement: HTMLElement) {
    this.container = createElement('header', { className: 'top-bar' });
    this.render();
    this.setupListeners();
  }

  render(): void {
    this.container.innerHTML = '';

    // Menu toggle (mobile)
    const menuBtn = createElement('button', { className: 'top-bar-menu-btn' }, '☰');
    menuBtn.addEventListener('click', () => {
      eventBus.emit(EVENTS.SIDEBAR_TOGGLE);
    });

    // Title / breadcrumb
    const title = createElement('div', { className: 'top-bar-title', 'data-testid': 'breadcrumbs' });
    const view = appState.get('currentView');
    const projectId = appState.get('currentProjectId');
    const project = projectId ? appState.getProject(projectId) : null;

    const viewLabel = createElement('span', { className: 'top-bar-view' }, this.getViewLabel(view));
    title.appendChild(viewLabel);

    if (project) {
      const sep = createElement('span', { className: 'top-bar-sep' }, ' / ');
      const projName = createElement('span', { className: 'top-bar-project' }, project.name);
      title.appendChild(sep);
      title.appendChild(projName);
    }

    // Voice indicator
    const voiceIndicator = createElement('div', {
      className: `top-bar-voice ${appState.get('voiceActive') ? 'active' : ''}`,
    });
    const voiceDot = createElement('span', { className: 'voice-dot' });
    const voiceLabel = createElement('span', {}, appState.get('voiceActive') ? 'Listening...' : '');
    voiceIndicator.appendChild(voiceDot);
    voiceIndicator.appendChild(voiceLabel);

    // Opportunities toggle (mobile only)
    const oppToggle = createElement('button', {
      className: 'top-bar-opp-toggle',
      'data-testid': 'opportunities-toggle',
    });
    oppToggle.innerHTML = `💡${this.opportunitiesCount > 0 ? `<span class="opp-toggle-badge">${this.opportunitiesCount}</span>` : ''}`;
    oppToggle.addEventListener('click', () => {
      eventBus.emit(EVENTS.OPPORTUNITIES_TOGGLE);
    });

    this.container.appendChild(menuBtn);
    this.container.appendChild(title);
    this.container.appendChild(voiceIndicator);
    this.container.appendChild(oppToggle);

    this.parentElement.appendChild(this.container);
  }

  private getViewLabel(view: string): string {
    const labels: Record<string, string> = {
      chat: '💬 Chat',
      kanban: '📋 Kanban',
      projects: '📁 Projects',
      settings: '⚙️ Settings',
    };
    return labels[view] || view;
  }

  private setupListeners(): void {
    this.unsubscribers.push(
      eventBus.on(EVENTS.VIEW_CHANGE, () => this.render())
    );
    this.unsubscribers.push(
      eventBus.on(EVENTS.PROJECT_SELECTED, () => this.render())
    );
    this.unsubscribers.push(
      eventBus.on(EVENTS.TAB_SWITCH, () => this.render())
    );
    this.unsubscribers.push(
      appState.subscribe('voiceActive', () => this.render())
    );
    this.unsubscribers.push(
      eventBus.on(EVENTS.OPPORTUNITIES_COUNT, (count: unknown) => {
        this.opportunitiesCount = count as number;
        this.render();
      })
    );
  }

  update(): void {
    this.render();
  }

  destroy(): void {
    this.unsubscribers.forEach((unsub) => unsub());
    this.unsubscribers = [];
    this.container.remove();
  }
}
