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

    // Project selector (bottom)
    const projectSection = createElement('div', { className: 'sidebar-project' });
    const currentProject = appState.get('currentProjectId');
    const project = currentProject ? appState.getProject(currentProject) : null;
    const projectLabel = createElement(
      'div',
      { className: 'sidebar-project-name' },
      project ? project.name : 'No project selected'
    );
    projectSection.appendChild(projectLabel);

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
      eventBus.on(EVENTS.PROJECT_SELECTED, () => {
        const currentProject = appState.get('currentProjectId');
        const project = currentProject ? appState.getProject(currentProject) : null;
        const nameEl = this.container.querySelector('.sidebar-project-name');
        if (nameEl) {
          nameEl.textContent = project ? project.name : 'No project selected';
        }
      })
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
