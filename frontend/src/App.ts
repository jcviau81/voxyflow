import { ViewMode, ProjectFormShowEvent, ProjectFormData, CardStatus, AgentPersona, Card, Project } from './types';
import { eventBus } from './utils/EventBus';
import { EVENTS } from './utils/constants';
import { createElement } from './utils/helpers';
import { appState } from './state/AppState';
import { apiClient } from './services/ApiClient';
import { projectService } from './services/ProjectService';
import { cardService } from './services/CardService';
import { Sidebar } from './components/Navigation/Sidebar';
import { TopBar } from './components/Navigation/TopBar';
import { TabBar } from './components/Navigation/TabBar';
import { ChatWindow } from './components/Chat/ChatWindow';
import { KanbanBoard } from './components/Kanban/KanbanBoard';
import { CardDetailModal } from './components/shared/CardDetailModal';
import { ProjectList } from './components/Projects/ProjectList';
import { ProjectForm } from './components/Projects/ProjectForm';
import { ProjectHeader } from './components/Projects/ProjectHeader';
import { Toast } from './components/Shared/Toast';
import { KeyboardShortcutsModal } from './components/Shared/KeyboardShortcutsModal';
import { CommandPalette } from './components/Shared/CommandPalette';
import { RightPanel } from './components/RightPanel/RightPanel';
import { WorkerPanel } from './components/RightPanel/WorkerPanel';
import { FreeBoard } from './components/FreeBoard/FreeBoard';
import { SettingsPage } from './components/Settings/SettingsPage';
import { FocusMode } from './components/FocusMode/FocusMode';
import { ProjectStats } from './components/Projects/ProjectStats';
import { ProjectRoadmap } from './components/Projects/ProjectRoadmap';
import { ProjectKnowledge } from './components/Projects/ProjectKnowledge';
import { SprintPlanner } from './components/Projects/SprintPlanner';
import { ProjectDocuments } from './components/Projects/ProjectDocuments';

export class App {
  private root: HTMLElement;
  private mainContent: HTMLElement;
  private sidebar: Sidebar | null = null;
  private topBar: TopBar | null = null;
  private tabBar: TabBar | null = null;
  private toast: Toast | null = null;
  private keyboardShortcutsModal: KeyboardShortcutsModal | null = null;
  private commandPalette: CommandPalette | null = null;
  private cardModal: CardDetailModal | null = null;
  private rightPanel: RightPanel | null = null;
  private workerPanel: WorkerPanel | null = null;
  private projectHeader: ProjectHeader | null = null;
  // FreeBoard is now a full-view via switchView('freeboard'), not a sidebar
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

    // Top bar first (hamburger menu on mobile — must be above tabs)
    mainArea.appendChild(topBarContainer);

    // Tab bar goes inside main area
    mainArea.appendChild(tabBarContainer);

    // Shared project header (project name + view tabs) — visible only in project mode
    const projectHeaderContainer = createElement('div', { className: 'project-header-container' });
    this.projectHeader = new ProjectHeader(projectHeaderContainer);
    mainArea.appendChild(projectHeaderContainer);

    mainArea.appendChild(this.mainContent);

    // Worker panel (between chat and opportunities — shows active Deep workers)
    const workerContainer = createElement('aside', { className: 'worker-panel-container' });
    this.workerPanel = new WorkerPanel(workerContainer);

    // Right panel (always-visible right sidebar: Opportunities + Notifications tabs)
    const opportunitiesContainer = createElement('aside', { className: 'opportunities-container' });
    this.rightPanel = new RightPanel(opportunitiesContainer);

    layout.appendChild(sidebarContainer);
    layout.appendChild(mainArea);
    layout.appendChild(workerContainer);
    layout.appendChild(opportunitiesContainer);

    // Set initial layout mode based on active tab
    this.updateLayoutMode(layout);

    this.root.appendChild(layout);

    // Toast container
    this.toast = new Toast(this.root);

    // Keyboard shortcuts modal
    this.keyboardShortcutsModal = new KeyboardShortcutsModal(this.root);

    // Command palette (Ctrl+K / Cmd+K)
    this.commandPalette = new CommandPalette(this.root);
    this.commandPalette.setShortcutsModalCallback(() => {
      this.keyboardShortcutsModal?.show();
    });

    // Card detail modal
    this.cardModal = new CardDetailModal(this.root);

    // Setup listeners
    this.setupListeners();

    // Render initial view
    this.switchView(appState.get('currentView'));

    // Connect to backend
    apiClient.connect();

    // Load projects from backend on startup
    projectService.requestSync();

    // Register keyboard shortcuts
    this.setupShortcuts();

    // Register PWA install prompt
    this.setupPWA();
  }

  private updateLayoutMode(layout?: HTMLElement): void {
    const el = layout || this.root.querySelector('.app-layout');
    if (!el) return;
    const activeTab = appState.getActiveTab();
    const isProject = activeTab !== 'main';
    if (isProject) {
      el.classList.add('project-mode');
      el.classList.remove('general-mode');
    } else {
      el.classList.add('general-mode');
      el.classList.remove('project-mode');
    }
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
        // On mobile: toggle .open class on sidebar-container for slide-in
        const sidebarEl = this.root.querySelector('.sidebar-container');
        if (sidebarEl) {
          const isOpen = sidebarEl.classList.toggle('open');
          // Add/remove overlay to close sidebar by tapping outside
          let overlay = this.root.querySelector('.sidebar-overlay') as HTMLElement | null;
          if (isOpen) {
            if (!overlay) {
              overlay = document.createElement('div');
              overlay.className = 'sidebar-overlay';
              overlay.addEventListener('click', () => {
                sidebarEl.classList.remove('open');
                this.root.classList.toggle('sidebar-collapsed');
                overlay?.remove();
              });
              this.root.appendChild(overlay);
            }
          } else {
            overlay?.remove();
          }
        }
      })
    );

    // Update layout mode when tabs switch
    this.unsubscribers.push(
      eventBus.on(EVENTS.TAB_SWITCH, () => {
        this.updateLayoutMode();
        // When switching to general mode, ensure we're in chat view
        const activeTab = appState.getActiveTab();
        if (activeTab === 'main') {
          const currentView = appState.get('currentView');
          // Main tab supports chat, kanban, freeboard — force others back to chat
          if (currentView === 'projects' || currentView === 'stats' || currentView === 'roadmap' || currentView === 'wiki' || currentView === 'sprint' || currentView === 'docs' || currentView === 'knowledge') {
            this.switchView('chat');
            appState.set('currentView', 'chat');
          }
        }
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

    // Project properties — open project form in edit mode
    this.unsubscribers.push(
      eventBus.on(EVENTS.PROJECT_PROPERTIES_OPEN, (payload: unknown) => {
        const { projectId } = payload as { projectId: string };
        const project = appState.getProject(projectId);
        if (project) {
          this.showProjectForm({ mode: 'edit', project });
        }
      })
    );



    // Project created toast
    this.unsubscribers.push(
      eventBus.on(EVENTS.PROJECT_CREATED, (project: unknown) => {
        const p = project as Project | undefined;
        if (!p?.name) return; // guard: sync events may emit without payload
        eventBus.emit(EVENTS.TOAST_SHOW, {
          message: `✅ Project '${p.name}' created`,
          type: 'success',
          duration: 3000,
        });
      })
    );

    // Card moved toast + activity + notification
    this.unsubscribers.push(
      eventBus.on(EVENTS.CARD_MOVED, (data: unknown) => {
        const { cardId, newStatus } = data as { cardId: string; newStatus: string };
        const card = appState.getCard(cardId);
        const statusLabels: Record<string, string> = {
          'idea': '💡 Idea',
          'todo': '📋 Todo',
          'in-progress': '🔨 In Progress',
          'done': '✅ Done',
        };
        const label = statusLabels[newStatus] || newStatus;
        eventBus.emit(EVENTS.TOAST_SHOW, {
          message: `📋 Moved to ${label}`,
          type: 'info',
          duration: 2500,
        });
        if (card && card.projectId) {
          appState.addActivity(card.projectId, 'card_moved', `📋 "${card.title}" moved to ${label}`);
        }
        appState.addNotification({
          type: 'card_moved',
          message: `📋 ${card ? `"${card.title}"` : 'Card'} moved to ${label}`,
        });
      })
    );

    // Card created activity tracking + notification
    this.unsubscribers.push(
      eventBus.on(EVENTS.CARD_CREATED, (card: unknown) => {
        const c = card as Card;
        if (c && c.projectId) {
          appState.addActivity(c.projectId, 'card_created', `✅ Card created: "${c.title}"`);
        }
        appState.addNotification({
          type: 'card_created',
          message: `✅ Card created: "${(card as Card).title}"`,
        });
      })
    );

    // Document uploaded toast + activity + notification
    this.unsubscribers.push(
      eventBus.on(EVENTS.DOCUMENT_UPLOADED, (data: unknown) => {
        const { filename, projectId } = data as { filename: string; projectId?: string };
        eventBus.emit(EVENTS.TOAST_SHOW, {
          message: `📄 ${filename} indexed`,
          type: 'success',
          duration: 3000,
        });
        if (projectId) {
          appState.addActivity(projectId, 'document_uploaded', `📄 Document indexed: "${filename}"`);
        }
        appState.addNotification({
          type: 'document_indexed',
          message: `📄 Document indexed: "${filename}"`,
        });
      })
    );

    // WS error toast + notification
    this.unsubscribers.push(
      eventBus.on(EVENTS.WS_ERROR, () => {
        eventBus.emit(EVENTS.TOAST_SHOW, {
          message: '⚠️ Connection lost — retrying...',
          type: 'warning',
          duration: 5000,
        });
        appState.addNotification({
          type: 'service_down',
          message: '⚠️ Connection lost — retrying...',
        });
      })
    );

    // Opportunity badge + notification: increment when new suggestion arrives
    this.unsubscribers.push(
      eventBus.on(EVENTS.CARD_SUGGESTION, (data: unknown) => {
        const oppContainer = this.root.querySelector('.opportunities-container');
        const isOpen = oppContainer?.classList.contains('open');
        if (!isOpen) {
          appState.incrementOpportunityBadge();
        }
        const suggestion = data as { title?: string };
        appState.addNotification({
          type: 'opportunity',
          message: `🔔 Opportunity detected: ${suggestion?.title || 'new suggestion'}`,
        });
      })
    );

    // Clear badge when opportunities panel is opened
    this.unsubscribers.push(
      eventBus.on(EVENTS.OPPORTUNITIES_TOGGLE, () => {
        appState.clearOpportunityBadge();
      })
    );

    // Card deleted notification
    this.unsubscribers.push(
      eventBus.on(EVENTS.CARD_DELETED, () => {
        appState.addNotification({
          type: 'card_deleted',
          message: '🗑️ Card deleted',
        });
      })
    );

    // Focus mode completed notification
    this.unsubscribers.push(
      eventBus.on(EVENTS.FOCUS_MODE_EXIT, () => {
        appState.addNotification({
          type: 'focus_completed',
          message: '🎯 Focus session completed',
        });
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

    if (mode === 'create' && data.templateId) {
      // Template flow — async via REST API
      this.handleCreateFromTemplate(data);
      return;
    }

    if (mode === 'create') {
      // Async create via REST API
      this.handleCreateProject(data);
    } else if (mode === 'edit' && projectId) {
      const updates: Record<string, unknown> = {
        name: data.title,
        description: data.description || '',
      };
      if (data.emoji) updates.emoji = data.emoji;
      if (data.color) updates.color = data.color;
      if (data.status) updates.archived = data.status === 'archived';
      if (data.localPath !== undefined) updates.localPath = data.localPath;
      if (data.githubRepo !== undefined) updates.githubRepo = data.githubRepo;
      if (data.githubUrl !== undefined) updates.githubUrl = data.githubUrl;
      if (data.githubBranch !== undefined) updates.githubBranch = data.githubBranch;
      if (data.githubLanguage !== undefined) updates.githubLanguage = data.githubLanguage;

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

  private async handleCreateProject(data: ProjectFormData): Promise<void> {
    const project = await projectService.create(data.title, data.description || '');
    // Update with all extra fields in one PATCH call
    const extraUpdates: Record<string, unknown> = {};
    if (data.emoji) extraUpdates.emoji = data.emoji;
    if (data.color) extraUpdates.color = data.color;
    if (data.localPath) extraUpdates.localPath = data.localPath;
    if (data.githubRepo) extraUpdates.githubRepo = data.githubRepo;
    if (data.githubUrl) extraUpdates.githubUrl = data.githubUrl;
    if (data.githubBranch) extraUpdates.githubBranch = data.githubBranch;
    if (data.githubLanguage) extraUpdates.githubLanguage = data.githubLanguage;
    if (Object.keys(extraUpdates).length > 0) {
      await projectService.update(project.id, extraUpdates as Partial<import('./types').Project>);
    }
    // Open project tab
    appState.openProjectTab(project.id, project.name, data.emoji);
  }

  private async handleCreateFromTemplate(data: ProjectFormData): Promise<void> {
    const result = await apiClient.createProjectFromTemplate(data.templateId!, {
      title: data.title,
      description: data.description,
      emoji: data.emoji,
      color: data.color,
    });

    if (!result) {
      eventBus.emit(EVENTS.TOAST_SHOW, { message: '❌ Failed to create project from template', type: 'error' });
      return;
    }

    // Create project in local state with the server-assigned ID and template visual
    const emoji = data.emoji || result.template_emoji;
    const color = data.color || result.template_color;
    // Inject project via sync (backend already persisted it)
    // Pull project list so the new project appears
    apiClient.send('project:list-request', {});

    // Open tab immediately (project will sync in shortly)
    appState.openProjectTab(result.project_id, result.project_title, emoji);

    // Apply emoji/color locally once project syncs
    setTimeout(() => {
      projectService.update(result.project_id, { emoji, color } as Partial<import('./types').Project>);
    }, 500);

    eventBus.emit(EVENTS.TOAST_SHOW, {
      message: `✅ Project "${result.project_title}" created with ${result.cards_imported} cards`,
      type: 'success',
      duration: 4000,
    });

    if (this.projectForm) {
      this.projectForm.destroy();
      this.projectForm = null;
    }
    this.viewBeforeForm = null;
    this.currentView = { component: null, view: null };
    this.switchView('kanban');
  }




  private switchView(view: ViewMode): void {
    if (this.currentView.view === view) return;

    // Destroy current view
    if (this.currentView.component) {
      this.currentView.component.destroy();
    }
    this.mainContent.innerHTML = '';

    // Destroy forms if showing
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
      case 'freeboard':
        component = new FreeBoard(this.mainContent);
        break;
      case 'projects':
        component = new ProjectList(this.mainContent);
        break;
      case 'settings':
        component = new SettingsPage(this.mainContent);
        break;
      case 'stats':
        component = new ProjectStats(this.mainContent);
        break;
      case 'roadmap':
        component = new ProjectRoadmap(this.mainContent);
        break;
      case 'knowledge':
        component = new ProjectKnowledge(this.mainContent);
        break;
      case 'sprint':
        component = new SprintPlanner(this.mainContent);
        break;
      case 'docs':
        component = new ProjectDocuments(this.mainContent);
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
      } else if (e.ctrlKey && e.key === 'f') {
        // Don't intercept when user is typing in an input or textarea
        const target = e.target as HTMLElement;
        const inInput = target.tagName === 'INPUT' || target.tagName === 'TEXTAREA' || target.isContentEditable;
        if (!inInput) {
          // Only activate if a card is selected and we're in kanban
          const selectedCardId = appState.get('selectedCardId');
          if (selectedCardId) {
            e.preventDefault();
            const card = appState.getCard(selectedCardId);
            if (card) {
              // Close any open modals first
              eventBus.emit(EVENTS.MODAL_CLOSE, null);
              setTimeout(() => {
                const focusMode = new FocusMode(this.root, {
                  card,
                  onExit: () => {
                    eventBus.emit(EVENTS.FOCUS_MODE_EXIT, null);
                  },
                });
                eventBus.emit(EVENTS.FOCUS_MODE_ENTER, selectedCardId);
              }, 100);
            }
          }
        }
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
    this.projectHeader?.destroy();
    this.toast?.destroy();
    this.keyboardShortcutsModal?.destroy();
    this.commandPalette?.destroy();
    this.cardModal?.destroy();
    this.workerPanel?.destroy();
    this.rightPanel?.destroy();
    this.projectHeader?.destroy();
    // FreeBoard destroyed via switchView cycle
    this.currentView.component?.destroy();
    this.projectForm?.destroy();
    apiClient.close();
    this.root.innerHTML = '';
  }
}
