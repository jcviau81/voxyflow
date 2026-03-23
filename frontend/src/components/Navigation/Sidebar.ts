import { ViewMode } from '../../types';
import { eventBus } from '../../utils/EventBus';
import { EVENTS, SYSTEM_PROJECT_ID } from '../../utils/constants';
import { createElement, cn } from '../../utils/helpers';
import { appState } from '../../state/AppState';
interface FooterIcon {
  action: string;
  icon: string;
  title: string;
}

const FOOTER_ICONS: FooterIcon[] = [
  { action: 'settings', icon: '⚙️', title: 'Settings' },
  { action: 'docs', icon: '📖', title: 'Documentation' },
  { action: 'help', icon: '❓', title: 'Help' },
];

export class Sidebar {
  private container: HTMLElement;
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

    const activeTabId = appState.getActiveTab();

    // Sidebar content wrapper (scrollable)
    const content = createElement('div', { className: 'sidebar-content' });

    // General chat item (always at top)
    const generalSection = createElement('div', { className: 'sidebar-nav' });
    const generalItem = createElement('div', {
      className: cn('sidebar-item', activeTabId === 'main' && 'active'),
      'data-testid': 'sidebar-general',
      'data-tab': 'main',
    });
    const generalIcon = createElement('span', { className: 'sidebar-item-icon' }, '💬');
    const generalLabel = createElement('span', { className: 'sidebar-item-label' }, 'Main Chat');
    generalItem.appendChild(generalIcon);
    generalItem.appendChild(generalLabel);
    generalItem.addEventListener('click', () => {
      appState.switchTab('main');
      appState.setView('chat');
    });
    generalSection.appendChild(generalItem);
    content.appendChild(generalSection);

    // Projects section
    const projectSection = createElement('div', { className: 'sidebar-projects' });
    const projectsHeader = createElement('div', {
      className: 'sidebar-section-header sidebar-section-header--clickable',
      title: 'All projects',
    });
    projectsHeader.appendChild(createElement('span', {}, 'PROJECTS'));
    projectsHeader.appendChild(createElement('span', { className: 'sidebar-all-projects-btn' }, '›'));
    projectsHeader.addEventListener('click', () => appState.setView('projects'));
    projectSection.appendChild(projectsHeader);

    // Filter out the system project — it's represented by the "Main" entry at top
    const projects = appState.get('projects').filter(p => !p.archived && p.id !== SYSTEM_PROJECT_ID);
    const openTabs = appState.getOpenTabs();

    projects.forEach((proj) => {
      const isTabOpen = openTabs.some(t => t.id === proj.id);
      const isActive = activeTabId === proj.id;

      // Compute progress for this project
      const cards = appState.getCardsByProject(proj.id);
      const total = cards.length;
      const done = cards.filter((c) => c.status === 'done').length;
      const inProgress = cards.filter((c) => c.status === 'in-progress').length;
      const pct = total > 0 ? Math.round((done / total) * 100) : 0;
      const dotColor = pct === 100 ? 'done' : pct >= 50 ? 'halfway' : pct > 0 ? 'started' : 'empty';
      const tooltipText = total > 0
        ? `${total} cards · ${done} done · ${inProgress} in progress · ${pct}%`
        : 'No cards yet';

      const item = createElement('div', {
        className: cn('sidebar-project-item', isActive && 'active', isTabOpen && 'has-tab'),
        'data-testid': `sidebar-project-${proj.id}`,
        title: tooltipText,
      });
      item.appendChild(createElement('span', {}, proj.emoji || '📁'));
      item.appendChild(createElement('span', { className: 'sidebar-project-name-text' }, proj.name || (proj as unknown as Record<string, string>).title || 'Untitled'));

      // Progress dot (replaces plain active/tab dot)
      const progressDot = createElement('span', {
        className: `sidebar-progress-dot ${dotColor}`,
        title: tooltipText,
      });
      item.appendChild(progressDot);

      item.addEventListener('click', () => {
        appState.openProjectTab(proj.id, proj.name || (proj as unknown as Record<string, string>).title || 'Untitled', proj.emoji);
        appState.setView('chat');
      });
      projectSection.appendChild(item);
    });

    // New project button
    const newProjectItem = createElement('div', {
      className: 'sidebar-project-item sidebar-new-project',
      'data-testid': 'sidebar-new-project',
    });
    newProjectItem.appendChild(createElement('span', {}, '+'));
    newProjectItem.appendChild(createElement('span', {}, 'New Project'));
    newProjectItem.addEventListener('click', () => {
      eventBus.emit(EVENTS.PROJECT_FORM_SHOW, { mode: 'create' });
    });
    projectSection.appendChild(newProjectItem);

    // Archived projects link
    const archivedProjects = appState.get('projects').filter(p => p.archived);
    if (archivedProjects.length > 0) {
      const archivedItem = createElement('div', {
        className: 'sidebar-project-item sidebar-archived-link',
        'data-testid': 'sidebar-archived',
        title: `${archivedProjects.length} archived project${archivedProjects.length > 1 ? 's' : ''}`,
      });
      archivedItem.appendChild(createElement('span', {}, '📦'));
      archivedItem.appendChild(createElement('span', { className: 'sidebar-project-name-text' }, `Archived (${archivedProjects.length})`));
      archivedItem.addEventListener('click', () => {
        appState.switchTab('main');
        appState.setView('projects');
        // Emit event to switch to archived filter
        eventBus.emit('PROJECT_LIST_FILTER', { filter: 'archived' });
      });
      projectSection.appendChild(archivedItem);
    }

    content.appendChild(projectSection);

    // Connection status
    const status = createElement('div', { className: 'sidebar-status' });
    const connectionState = appState.get('connectionState');
    const statusDot = createElement('span', { className: `status-dot ${connectionState}` });
    const statusText = createElement('span', { className: 'status-text' }, connectionState);
    status.appendChild(statusDot);
    status.appendChild(statusText);
    content.appendChild(status);

    // Footer icons
    const footer = createElement('div', { className: 'sidebar-footer', 'data-testid': 'sidebar-footer' });

    // Notification bell button
    const unreadCount = appState.getNotificationUnreadCount();
    const bellWrapper = createElement('div', { className: 'notification-bell-wrapper' });
    const bellBtn = createElement('button', {
      className: 'sidebar-icon notification-bell',
      'data-action': 'notifications',
      title: 'Notifications',
    }, '🔔');
    if (unreadCount > 0) {
      const badge = createElement('span', { className: 'notification-badge' }, unreadCount > 99 ? '99+' : String(unreadCount));
      bellWrapper.appendChild(badge);
    }
    bellBtn.addEventListener('click', () => {
      eventBus.emit(EVENTS.NOTIFICATION_PANEL_TOGGLE, null);
      // Re-render to clear badge
      setTimeout(() => this.render(), 50);
    });
    bellWrapper.appendChild(bellBtn);
    footer.appendChild(bellWrapper);

    // Theme toggle button
    const currentTheme = appState.get('theme') || 'dark';
    const themeBtn = createElement('button', {
      className: 'sidebar-icon',
      'data-action': 'theme-toggle',
      title: currentTheme === 'dark' ? 'Switch to light mode' : 'Switch to dark mode',
    }, currentTheme === 'dark' ? '🌙' : '☀️');
    themeBtn.addEventListener('click', () => {
      const theme = appState.get('theme') || 'dark';
      appState.setTheme(theme === 'dark' ? 'light' : 'dark');
      this.render();
    });
    footer.appendChild(themeBtn);

    FOOTER_ICONS.forEach((item) => {
      const btn = createElement('button', {
        className: 'sidebar-icon',
        'data-action': item.action,
        title: item.title,
      }, item.icon);
      btn.addEventListener('click', () => {
        switch (item.action) {
          case 'settings':
            appState.setView('settings');
            eventBus.emit(EVENTS.SETTINGS_OPEN);
            break;
          case 'docs':
            eventBus.emit(EVENTS.DOCS_OPEN);
            break;
          case 'help':
            eventBus.emit(EVENTS.HELP_OPEN);
            break;
        }
      });
      footer.appendChild(btn);
    });

    this.container.appendChild(brand);
    this.container.appendChild(content);
    this.container.appendChild(footer);

    if (!this.container.parentElement) {
      this.parentElement.appendChild(this.container);
    }
  }

  private setupListeners(): void {
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
    this.unsubscribers.push(
      eventBus.on(EVENTS.TAB_SWITCH, () => this.render())
    );
    this.unsubscribers.push(
      eventBus.on(EVENTS.TAB_OPEN, () => this.render())
    );
    this.unsubscribers.push(
      eventBus.on(EVENTS.TAB_CLOSE, () => this.render())
    );
    this.unsubscribers.push(
      eventBus.on(EVENTS.PROJECT_CREATED, () => this.render())
    );
    this.unsubscribers.push(
      eventBus.on(EVENTS.PROJECT_DELETED, () => this.render())
    );
    this.unsubscribers.push(
      eventBus.on(EVENTS.PROJECT_UPDATED, () => this.render())
    );
    this.unsubscribers.push(
      appState.subscribe('theme', () => this.render())
    );

    // Re-render on notification count change (to update badge)
    this.unsubscribers.push(
      eventBus.on(EVENTS.NOTIFICATION_COUNT, () => this.render())
    );

    // Toggle sidebar shortcut (Ctrl+B)
    document.addEventListener('keydown', (e) => {
      if (e.ctrlKey && e.key === 'b') {
        e.preventDefault();
        this.toggle();
      }
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
