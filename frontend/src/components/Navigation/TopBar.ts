import { ViewMode } from '../../types';
import { createElement } from '../../utils/helpers';
import { eventBus } from '../../utils/EventBus';
import { EVENTS } from '../../utils/constants';
import { appState } from '../../state/AppState';

export class TopBar {
  private container: HTMLElement;
  private unsubscribers: (() => void)[] = [];
  private opportunitiesCount: number = 0;
  private currentProjectView: 'chat' | 'kanban' = 'chat';

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

    // Context indicator — shows what you're in
    const contextIndicator = createElement('div', {
      className: 'context-indicator',
      'data-testid': 'context-indicator',
    });

    const activeTab = appState.getActiveTab();
    const isProject = activeTab !== 'main';
    const projectId = appState.get('currentProjectId');
    const project = projectId ? appState.getProject(projectId) : null;

    if (isProject && project) {
      // Project context: "🎙 Voxyflow — Chat" or "🎙 Voxyflow — Kanban"
      const emoji = createElement('span', { className: 'context-emoji' }, project.emoji || '📁');
      const name = createElement('span', {}, project.name);
      const sep = createElement('span', { className: 'context-sep' }, '—');
      const viewLabel = createElement('span', { className: 'context-view-label' },
        this.currentProjectView === 'kanban' ? 'Kanban' : 'Chat');
      contextIndicator.appendChild(emoji);
      contextIndicator.appendChild(name);
      contextIndicator.appendChild(sep);
      contextIndicator.appendChild(viewLabel);
    } else {
      // General context
      const emoji = createElement('span', { className: 'context-emoji' }, '💬');
      const label = createElement('span', {}, 'General Chat');
      contextIndicator.appendChild(emoji);
      contextIndicator.appendChild(label);
    }

    // View toggle (Chat / Kanban) — only meaningful in project mode
    const viewToggle = createElement('div', {
      className: 'view-toggle',
      'data-testid': 'view-toggle',
    });

    const chatBtn = createElement('button', {
      className: `view-btn ${this.currentProjectView === 'chat' ? 'active' : ''}`,
      'data-view': 'chat',
    }, '💬 Chat');
    chatBtn.addEventListener('click', () => {
      this.currentProjectView = 'chat';
      appState.setView('chat');
      this.render();
    });

    const kanbanBtn = createElement('button', {
      className: `view-btn ${this.currentProjectView === 'kanban' ? 'active' : ''}`,
      'data-view': 'kanban',
    }, '📋 Kanban');
    kanbanBtn.addEventListener('click', () => {
      this.currentProjectView = 'kanban';
      appState.setView('kanban');
      this.render();
    });

    viewToggle.appendChild(chatBtn);
    viewToggle.appendChild(kanbanBtn);

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
    this.container.appendChild(contextIndicator);
    this.container.appendChild(viewToggle);
    this.container.appendChild(voiceIndicator);
    this.container.appendChild(oppToggle);

    this.parentElement.appendChild(this.container);
  }

  private setupListeners(): void {
    this.unsubscribers.push(
      eventBus.on(EVENTS.VIEW_CHANGE, (view: unknown) => {
        const v = view as ViewMode;
        if (v === 'chat' || v === 'kanban') {
          this.currentProjectView = v;
        }
        this.render();
      })
    );
    this.unsubscribers.push(
      eventBus.on(EVENTS.PROJECT_SELECTED, () => {
        // Reset to chat view when switching projects
        this.currentProjectView = 'chat';
        this.render();
      })
    );
    this.unsubscribers.push(
      eventBus.on(EVENTS.TAB_SWITCH, () => {
        // Reset to chat view on tab switch
        this.currentProjectView = 'chat';
        this.render();
      })
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
