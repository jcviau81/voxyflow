import { ViewMode } from '../../types';
import { eventBus } from '../../utils/EventBus';
import { EVENTS } from '../../utils/constants';
import { createElement, cn } from '../../utils/helpers';
import { appState } from '../../state/AppState';

interface NavItem {
  view: ViewMode;
  icon: string;
  label: string;
}

const NAV_ITEMS: NavItem[] = [
  { view: 'chat', icon: '💬', label: 'Chat' },
  { view: 'kanban', icon: '📋', label: 'Kanban' },
  { view: 'projects', icon: '📁', label: 'Projects' },
  { view: 'settings', icon: '⚙️', label: 'Settings' },
];

export class Sidebar {
  private container: HTMLElement;
  private navItems: HTMLElement[] = [];
  private unsubscribers: (() => void)[] = [];

  constructor(private parentElement: HTMLElement) {
    this.container = createElement('nav', { className: 'sidebar', 'data-testid': 'sidebar' });
    this.render();
    this.setupListeners();
  }

  render(): void {
    this.container.innerHTML = '';

    // Logo / Brand
    const brand = createElement('div', { className: 'sidebar-brand' });
    const logo = createElement('span', { className: 'sidebar-logo' }, '🔥');
    const name = createElement('span', { className: 'sidebar-name' }, 'Voxyflow');
    brand.appendChild(logo);
    brand.appendChild(name);

    // Navigation items
    const nav = createElement('div', { className: 'sidebar-nav' });
    const currentView = appState.get('currentView');

    this.navItems = NAV_ITEMS.map((item) => {
      const el = createElement('div', {
        className: cn('sidebar-item', item.view === currentView && 'active'),
        'data-view': item.view,
      });
      const icon = createElement('span', { className: 'sidebar-item-icon' }, item.icon);
      const label = createElement('span', { className: 'sidebar-item-label' }, item.label);
      el.appendChild(icon);
      el.appendChild(label);

      el.addEventListener('click', () => {
        appState.setView(item.view);
      });

      nav.appendChild(el);
      return el;
    });

    // Project list section
    const projectSection = createElement('div', { className: 'sidebar-projects' });
    const projectsHeader = createElement('div', { className: 'sidebar-section-header' }, 'Projects');
    projectSection.appendChild(projectsHeader);

    // General / Main item
    const activeTabId = appState.getActiveTab();
    const generalItem = createElement('div', {
      className: cn('sidebar-project-item', activeTabId === 'main' && 'active'),
      'data-testid': 'sidebar-general',
    });
    generalItem.appendChild(createElement('span', {}, '💬'));
    generalItem.appendChild(createElement('span', {}, 'General'));
    generalItem.addEventListener('click', () => {
      appState.switchTab('main');
    });
    projectSection.appendChild(generalItem);

    // Project items
    const projects = appState.get('projects').filter(p => !p.archived);
    const openTabs = appState.getOpenTabs();
    projects.forEach((proj) => {
      const isTabOpen = openTabs.some(t => t.id === proj.id);
      const isActive = activeTabId === proj.id;
      const item = createElement('div', {
        className: cn('sidebar-project-item', isActive && 'active', isTabOpen && 'has-tab'),
        'data-testid': `sidebar-project-${proj.id}`,
      });
      item.appendChild(createElement('span', {}, '📁'));
      item.appendChild(createElement('span', {}, proj.name));
      if (isTabOpen) {
        item.appendChild(createElement('span', { className: 'sidebar-tab-dot' }, '●'));
      }
      item.addEventListener('click', () => {
        appState.openProjectTab(proj.id, proj.name);
      });
      projectSection.appendChild(item);
    });

    // Connection status
    const status = createElement('div', { className: 'sidebar-status' });
    const connectionState = appState.get('connectionState');
    const statusDot = createElement('span', { className: `status-dot ${connectionState}` });
    const statusText = createElement('span', { className: 'status-text' }, connectionState);
    status.appendChild(statusDot);
    status.appendChild(statusText);

    this.container.appendChild(brand);
    this.container.appendChild(nav);
    this.container.appendChild(projectSection);
    this.container.appendChild(status);

    this.parentElement.appendChild(this.container);
  }

  private setupListeners(): void {
    this.unsubscribers.push(
      eventBus.on(EVENTS.VIEW_CHANGE, (view: unknown) => {
        this.updateActiveItem(view as ViewMode);
      })
    );

    this.unsubscribers.push(
      appState.subscribe('connectionState', (state) => {
        const dot = this.container.querySelector('.status-dot');
        const text = this.container.querySelector('.status-text');
        if (dot) dot.className = `status-dot ${state}`;
        if (text) text.textContent = state;
      })
    );

    this.unsubscribers.push(
      eventBus.on(EVENTS.PROJECT_SELECTED, () => this.render())
    );

    // Re-render on tab changes
    this.unsubscribers.push(
      eventBus.on(EVENTS.TAB_SWITCH, () => this.render())
    );
    this.unsubscribers.push(
      eventBus.on(EVENTS.TAB_OPEN, () => this.render())
    );
    this.unsubscribers.push(
      eventBus.on(EVENTS.TAB_CLOSE, () => this.render())
    );

    // Re-render when projects change
    this.unsubscribers.push(
      eventBus.on(EVENTS.PROJECT_CREATED, () => this.render())
    );
    this.unsubscribers.push(
      eventBus.on(EVENTS.PROJECT_DELETED, () => this.render())
    );

    // Toggle sidebar shortcut (Ctrl+B)
    document.addEventListener('keydown', (e) => {
      if (e.ctrlKey && e.key === 'b') {
        e.preventDefault();
        this.toggle();
      }
    });
  }

  private updateActiveItem(view: ViewMode): void {
    this.navItems.forEach((item) => {
      const itemView = item.getAttribute('data-view');
      item.classList.toggle('active', itemView === view);
    });
  }

  toggle(): void {
    const isOpen = appState.get('sidebarOpen');
    appState.set('sidebarOpen', !isOpen);
    this.container.classList.toggle('collapsed', isOpen);
    eventBus.emit(EVENTS.SIDEBAR_TOGGLE, !isOpen);
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
