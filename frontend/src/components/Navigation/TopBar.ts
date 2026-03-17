import { createElement } from '../../utils/helpers';
import { eventBus } from '../../utils/EventBus';
import { EVENTS } from '../../utils/constants';
import { appState } from '../../state/AppState';

export class TopBar {
  private container: HTMLElement;
  private unsubscribers: (() => void)[] = [];

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

    this.container.appendChild(menuBtn);
    this.container.appendChild(title);
    this.container.appendChild(voiceIndicator);

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
      appState.subscribe('voiceActive', () => this.render())
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
