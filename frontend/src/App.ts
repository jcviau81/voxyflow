import { ViewMode } from './types';
import { eventBus } from './utils/EventBus';
import { EVENTS } from './utils/constants';
import { createElement } from './utils/helpers';
import { appState } from './state/AppState';
import { apiClient } from './services/ApiClient';
import { Sidebar } from './components/Navigation/Sidebar';
import { TopBar } from './components/Navigation/TopBar';
import { TabBar } from './components/Navigation/TabBar';
import { ChatWindow } from './components/Chat/ChatWindow';
import { KanbanBoard } from './components/Kanban/KanbanBoard';
import { CardDetailModal } from './components/Kanban/CardDetailModal';
import { ProjectList } from './components/Projects/ProjectList';
import { Toast } from './components/Shared/Toast';
import { OpportunitiesPanel } from './components/Opportunities/OpportunitiesPanel';

export class App {
  private root: HTMLElement;
  private mainContent: HTMLElement;
  private sidebar: Sidebar | null = null;
  private topBar: TopBar | null = null;
  private tabBar: TabBar | null = null;
  private toast: Toast | null = null;
  private cardModal: CardDetailModal | null = null;
  private opportunitiesPanel: OpportunitiesPanel | null = null;
  private currentView: { component: { destroy(): void } | null; view: ViewMode | null } = {
    component: null,
    view: null,
  };
  private unsubscribers: (() => void)[] = [];

  constructor(rootElement: HTMLElement) {
    this.root = rootElement;
    this.mainContent = createElement('main', { className: 'main-content' });
    this.init();
  }

  private init(): void {
    this.root.innerHTML = '';
    this.root.className = 'app-container';

    // Tab bar (full width, above everything)
    const tabBarContainer = createElement('div', { className: 'tab-bar-container' });
    this.tabBar = new TabBar(tabBarContainer);

    // Layout (below tab bar)
    const layout = createElement('div', { className: 'app-layout' });

    // Sidebar
    const sidebarContainer = createElement('aside', { className: 'sidebar-container' });
    this.sidebar = new Sidebar(sidebarContainer);

    // Main area
    const mainArea = createElement('div', { className: 'main-area' });

    // Top bar
    const topBarContainer = createElement('div', { className: 'top-bar-container' });
    this.topBar = new TopBar(topBarContainer);

    mainArea.appendChild(topBarContainer);
    mainArea.appendChild(this.mainContent);

    // Opportunities panel (right sidebar)
    const opportunitiesContainer = createElement('aside', { className: 'opportunities-container' });
    this.opportunitiesPanel = new OpportunitiesPanel(opportunitiesContainer);

    layout.appendChild(sidebarContainer);
    layout.appendChild(mainArea);
    layout.appendChild(opportunitiesContainer);

    this.root.appendChild(tabBarContainer);
    this.root.appendChild(layout);

    // Toast container
    this.toast = new Toast(this.root);

    // Card detail modal
    this.cardModal = new CardDetailModal(this.root);

    // Setup listeners
    this.setupListeners();

    // Render initial view
    this.switchView(appState.get('currentView'));

    // Connect to backend
    apiClient.connect();

    // Register keyboard shortcuts
    this.setupShortcuts();

    // Register PWA install prompt
    this.setupPWA();
  }

  private setupListeners(): void {
    this.unsubscribers.push(
      eventBus.on(EVENTS.VIEW_CHANGE, (view: unknown) => {
        this.switchView(view as ViewMode);
      })
    );

    this.unsubscribers.push(
      eventBus.on(EVENTS.SIDEBAR_TOGGLE, () => {
        this.root.classList.toggle('sidebar-collapsed');
      })
    );

    this.unsubscribers.push(
      eventBus.on(EVENTS.OPPORTUNITIES_TOGGLE, () => {
        const oppContainer = this.root.querySelector('.opportunities-container');
        if (oppContainer) {
          oppContainer.classList.toggle('open');
        }
      })
    );
  }

  private switchView(view: ViewMode): void {
    if (this.currentView.view === view) return;

    // Destroy current view
    if (this.currentView.component) {
      this.currentView.component.destroy();
    }
    this.mainContent.innerHTML = '';

    // Create new view
    let component: { destroy(): void } | null = null;

    switch (view) {
      case 'chat':
        component = new ChatWindow(this.mainContent);
        break;
      case 'kanban':
        component = new KanbanBoard(this.mainContent);
        break;
      case 'projects':
        component = new ProjectList(this.mainContent);
        break;
      case 'settings':
        this.renderSettings();
        component = { destroy: () => {} };
        break;
    }

    this.currentView = { component, view };
  }

  private renderSettings(): void {
    const container = createElement('div', { className: 'settings-view' });
    const title = createElement('h2', {}, '⚙️ Settings');

    // Volume
    const volumeSection = createElement('div', { className: 'settings-section' });
    const volumeLabel = createElement('label', {}, 'Volume');
    const volumeInput = createElement('input', {
      type: 'range',
      min: '0',
      max: '100',
      value: (appState.get('volume') * 100).toString(),
    }) as HTMLInputElement;
    volumeInput.addEventListener('input', () => {
      appState.set('volume', parseInt(volumeInput.value) / 100);
    });
    volumeSection.appendChild(volumeLabel);
    volumeSection.appendChild(volumeInput);

    // Connection info
    const connSection = createElement('div', { className: 'settings-section' });
    const connLabel = createElement('label', {}, 'Connection');
    const connStatus = createElement('div', {}, `Status: ${appState.get('connectionState')}`);
    const reconnectBtn = createElement('button', { className: 'settings-btn' }, 'Reconnect');
    reconnectBtn.addEventListener('click', () => {
      apiClient.close();
      apiClient.connect();
    });
    connSection.appendChild(connLabel);
    connSection.appendChild(connStatus);
    connSection.appendChild(reconnectBtn);

    // Data management
    const dataSection = createElement('div', { className: 'settings-section' });
    const dataLabel = createElement('label', {}, 'Data');
    const clearBtn = createElement('button', { className: 'settings-btn danger' }, 'Clear All Data');
    clearBtn.addEventListener('click', () => {
      if (confirm('This will delete all local data. Are you sure?')) {
        appState.reset();
        location.reload();
      }
    });
    dataSection.appendChild(dataLabel);
    dataSection.appendChild(clearBtn);

    // About
    const aboutSection = createElement('div', { className: 'settings-section' });
    aboutSection.innerHTML = `
      <h3>About Voxyflow</h3>
      <p>Voice-first project assistant</p>
      <p>Version: 1.0.0</p>
    `;

    container.appendChild(title);
    container.appendChild(volumeSection);
    container.appendChild(connSection);
    container.appendChild(dataSection);
    container.appendChild(aboutSection);
    this.mainContent.appendChild(container);
  }

  private setupShortcuts(): void {
    document.addEventListener('keydown', (e) => {
      if (e.ctrlKey && e.key === '1') {
        e.preventDefault();
        appState.setView('chat');
      } else if (e.ctrlKey && e.key === '2') {
        e.preventDefault();
        appState.setView('kanban');
      } else if (e.ctrlKey && e.key === '3') {
        e.preventDefault();
        appState.setView('projects');
      }
    });
  }

  private setupPWA(): void {
    let deferredPrompt: unknown = null;

    window.addEventListener('beforeinstallprompt', (e) => {
      e.preventDefault();
      deferredPrompt = e;

      eventBus.emit(EVENTS.TOAST_SHOW, {
        message: 'Install Voxyflow as an app?',
        type: 'info',
        duration: 10000,
        action: {
          label: 'Install',
          callback: () => {
            if (deferredPrompt) {
              (deferredPrompt as { prompt: () => void }).prompt();
            }
          },
        },
      });
    });
  }

  destroy(): void {
    this.unsubscribers.forEach((unsub) => unsub());
    this.sidebar?.destroy();
    this.topBar?.destroy();
    this.tabBar?.destroy();
    this.toast?.destroy();
    this.cardModal?.destroy();
    this.opportunitiesPanel?.destroy();
    this.currentView.component?.destroy();
    apiClient.close();
    this.root.innerHTML = '';
  }
}
