import { ViewMode, ProjectFormShowEvent, ProjectFormData } from './types';
import { eventBus } from './utils/EventBus';
import { EVENTS } from './utils/constants';
import { createElement } from './utils/helpers';
import { appState } from './state/AppState';
import { apiClient } from './services/ApiClient';
import { projectService } from './services/ProjectService';
import { Sidebar } from './components/Navigation/Sidebar';
import { TopBar } from './components/Navigation/TopBar';
import { TabBar } from './components/Navigation/TabBar';
import { ChatWindow } from './components/Chat/ChatWindow';
import { KanbanBoard } from './components/Kanban/KanbanBoard';
import { CardDetailModal } from './components/Kanban/CardDetailModal';
import { ProjectList } from './components/Projects/ProjectList';
import { ProjectForm } from './components/Projects/ProjectForm';
import { Toast } from './components/Shared/Toast';
import { OpportunitiesPanel } from './components/Opportunities/OpportunitiesPanel';
import { SettingsPage } from './components/Settings/SettingsPage';

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
  private projectForm: ProjectForm | null = null;
  private viewBeforeForm: ViewMode | null = null;
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

    // Tab bar goes inside main area (above top bar, not full width)
    mainArea.appendChild(tabBarContainer);
    mainArea.appendChild(topBarContainer);
    mainArea.appendChild(this.mainContent);

    // Opportunities panel (right sidebar)
    const opportunitiesContainer = createElement('aside', { className: 'opportunities-container' });
    this.opportunitiesPanel = new OpportunitiesPanel(opportunitiesContainer);

    layout.appendChild(sidebarContainer);
    layout.appendChild(mainArea);
    layout.appendChild(opportunitiesContainer);

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

    // Project form events
    this.unsubscribers.push(
      eventBus.on(EVENTS.PROJECT_FORM_SHOW, (event: unknown) => {
        this.showProjectForm(event as ProjectFormShowEvent);
      })
    );

    this.unsubscribers.push(
      eventBus.on(EVENTS.PROJECT_FORM_SUBMIT, (payload: unknown) => {
        this.handleProjectFormSubmit(payload as { mode: string; data: ProjectFormData; projectId?: string });
      })
    );

    this.unsubscribers.push(
      eventBus.on(EVENTS.PROJECT_FORM_CANCEL, () => {
        this.hideProjectForm();
      })
    );
  }

  private showProjectForm(event: ProjectFormShowEvent): void {
    // Remember current view to return to on cancel
    this.viewBeforeForm = this.currentView.view;

    // Destroy current view
    if (this.currentView.component) {
      this.currentView.component.destroy();
      this.currentView = { component: null, view: null };
    }
    this.mainContent.innerHTML = '';

    // Destroy existing form if any
    if (this.projectForm) {
      this.projectForm.destroy();
    }

    this.projectForm = new ProjectForm(this.mainContent, event);
  }

  private hideProjectForm(): void {
    if (this.projectForm) {
      this.projectForm.destroy();
      this.projectForm = null;
    }

    // Return to previous view
    const returnView = this.viewBeforeForm || 'projects';
    this.viewBeforeForm = null;
    this.currentView = { component: null, view: null }; // Reset so switchView works
    this.switchView(returnView);
  }

  private handleProjectFormSubmit(payload: { mode: string; data: ProjectFormData; projectId?: string }): void {
    const { mode, data, projectId } = payload;

    if (mode === 'create') {
      const project = projectService.create(data.title, data.description || '');
      // Update with emoji and color
      if (data.emoji || data.color) {
        projectService.update(project.id, {
          ...(data.emoji ? { emoji: data.emoji } : {}),
          ...(data.color ? { color: data.color } : {}),
        } as Partial<import('./types').Project>);
      }
      // Open project tab
      appState.openProjectTab(project.id, project.name, data.emoji);
    } else if (mode === 'edit' && projectId) {
      const updates: Record<string, unknown> = {
        name: data.title,
        description: data.description || '',
      };
      if (data.emoji) updates.emoji = data.emoji;
      if (data.color) updates.color = data.color;
      if (data.status) updates.archived = data.status === 'archived';

      projectService.update(projectId, updates as Partial<import('./types').Project>);
    }

    // Hide form and go back
    if (this.projectForm) {
      this.projectForm.destroy();
      this.projectForm = null;
    }
    this.viewBeforeForm = null;
    this.currentView = { component: null, view: null };

    if (mode === 'create') {
      // Tab was already opened by openProjectTab, switch to kanban
      this.switchView('kanban');
    } else {
      this.switchView('projects');
    }
  }

  private switchView(view: ViewMode): void {
    if (this.currentView.view === view) return;

    // Destroy current view
    if (this.currentView.component) {
      this.currentView.component.destroy();
    }
    this.mainContent.innerHTML = '';

    // Destroy form if showing
    if (this.projectForm) {
      this.projectForm.destroy();
      this.projectForm = null;
    }

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
        component = new SettingsPage(this.mainContent);
        break;
    }

    this.currentView = { component, view };
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
    this.projectForm?.destroy();
    apiClient.close();
    this.root.innerHTML = '';
  }
}
