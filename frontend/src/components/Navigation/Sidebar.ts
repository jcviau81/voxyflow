import { ViewMode, Project, SessionInfo } from '../../types';
import { eventBus } from '../../utils/EventBus';
import { EVENTS, SYSTEM_PROJECT_ID } from '../../utils/constants';
import { createElement, cn } from '../../utils/helpers';
import { appState } from '../../state/AppState';
import { cardStore } from '../../state/ReactiveCardStore';
import { apiClient } from '../../services/ApiClient';
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

    // Filter out the system project — it's represented by the "Main" entry at top
    const allProjects = appState.get('projects').filter(p => !p.archived && p.id !== SYSTEM_PROJECT_ID);

    // ── FAVORITES SECTION ──
    const favorites = allProjects.filter(p => p.isFavorite);
    if (favorites.length > 0) {
      const favSection = createElement('div', { className: 'sidebar-favorites' });
      const favHeader = createElement('div', { className: 'sidebar-section-header' });
      favHeader.appendChild(createElement('span', {}, '⭐ FAVORITES'));
      favSection.appendChild(favHeader);

      favorites.forEach((proj) => {
        favSection.appendChild(this.createProjectItem(proj, activeTabId));
      });

      content.appendChild(favSection);
    }

    // ── ACTIVE SESSIONS SECTION ──
    const sessionEntries = this.getActiveSessionEntries();
    if (sessionEntries.length > 0) {
      const sessSection = createElement('div', { className: 'sidebar-sessions' });
      const sessHeader = createElement('div', { className: 'sidebar-section-header' });
      sessHeader.appendChild(createElement('span', {}, '💬 ACTIVE SESSIONS'));
      sessSection.appendChild(sessHeader);

      sessionEntries.forEach((entry) => {
        const isCurrent = entry.tabId === activeTabId &&
          appState.getActiveSession(entry.tabId).id === entry.session.id;

        const item = createElement('div', {
          className: cn('sidebar-session-item', isCurrent && 'active'),
          title: entry.label,
        });

        // Status dot
        const dot = createElement('span', {
          className: 'sidebar-session-dot',
        }, isCurrent ? '🟢' : '⚫');
        item.appendChild(dot);

        // Breadcrumb label
        const label = createElement('span', { className: 'sidebar-session-label' }, entry.label);
        item.appendChild(label);

        // Close button
        const closeBtn = createElement('span', {
          className: 'sidebar-session-close',
          title: 'Close session',
        }, '×');
        closeBtn.addEventListener('click', (e) => {
          e.stopPropagation();
          this.closeSession(entry.tabId, entry.session);
        });
        item.appendChild(closeBtn);

        // Click to switch
        item.addEventListener('click', () => {
          appState.switchTab(entry.tabId);
          appState.setActiveSession(entry.tabId, entry.session.id);
          appState.setView('chat');
        });

        sessSection.appendChild(item);
      });

      content.appendChild(sessSection);
    }

    // ── PROJECTS LINK ──
    // Sidebar shows ONLY favorites — all projects are accessible via the Projects page
    const projectSection = createElement('div', { className: 'sidebar-projects' });
    const projectsLink = createElement('div', {
      className: 'sidebar-section-header sidebar-section-header--clickable',
      title: 'All projects',
    });
    projectsLink.appendChild(createElement('span', {}, '📁 All Projects'));
    projectsLink.appendChild(createElement('span', { className: 'sidebar-all-projects-btn' }, '›'));
    projectsLink.addEventListener('click', () => appState.setView('projects'));
    projectSection.appendChild(projectsLink);

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
    const archivedProjects = appState.get('projects').filter(p => p.archived && p.id !== SYSTEM_PROJECT_ID);
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

  /**
   * Create a project sidebar item with progress dot and favorite star.
   */
  private createProjectItem(proj: Project, activeTabId: string): HTMLElement {
    const openTabs = appState.getOpenTabs();
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

    // Favorite star (toggle on click, stopPropagation to avoid opening project)
    const star = createElement('span', {
      className: 'sidebar-favorite-star',
      title: proj.isFavorite ? 'Remove from favorites' : 'Add to favorites',
    }, proj.isFavorite ? '⭐' : '☆');
    star.addEventListener('click', (e) => {
      e.stopPropagation();
      apiClient.toggleFavorite(proj.id);
    });
    item.appendChild(star);

    item.appendChild(createElement('span', { className: 'sidebar-project-name-text' }, proj.name || (proj as unknown as Record<string, string>).title || 'Untitled'));

    // Progress dot
    const progressDot = createElement('span', {
      className: `sidebar-progress-dot ${dotColor}`,
      title: tooltipText,
    });
    item.appendChild(progressDot);

    item.addEventListener('click', () => {
      appState.openProjectTab(proj.id, proj.name || (proj as unknown as Record<string, string>).title || 'Untitled', proj.emoji);
      appState.setView('chat');
    });

    return item;
  }

  /**
   * Collect all active sessions across all open tabs for the sidebar sessions section.
   */
  private getActiveSessionEntries(): Array<{ tabId: string; session: SessionInfo; label: string }> {
    const entries: Array<{ tabId: string; session: SessionInfo; label: string }> = [];
    const openTabs = appState.getOpenTabs();

    for (const tab of openTabs) {
      const sessions = appState.get('sessions')[tab.id] || [];
      if (sessions.length === 0) continue;

      for (const session of sessions) {
        let label: string;
        if (tab.id === 'main') {
          label = session.title || 'Main Chat';
        } else {
          const project = appState.getProject(tab.id);
          const projectName = project?.name || tab.label || 'Project';
          label = `${projectName} > ${session.title || 'Session'}`;
        }
        entries.push({ tabId: tab.id, session, label });
      }
    }

    return entries;
  }

  /**
   * Close a session from the sidebar — sends session:reset via WS and removes from state.
   */
  private closeSession(tabId: string, session: SessionInfo): void {
    apiClient.send('session:reset', {
      sessionId: session.chatId,
      tabId,
    });

    const sessions = appState.get('sessions')[tabId] || [];
    if (sessions.length <= 1) {
      // Last session: reset it (clear history, create fresh session)
      appState.closeSession(tabId, session.id);
      appState.createSession(tabId);
    } else {
      appState.closeSession(tabId, session.id);
    }
    this.render();
  }

  private setupListeners(): void {
    // Reactive card store — re-render sidebar when card counts change (progress dots)
    this.unsubscribers.push(
      cardStore.subscribe(() => this.render())
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

    // Re-render on session changes (to update active sessions section)
    this.unsubscribers.push(
      eventBus.on(EVENTS.SESSION_TAB_SWITCH, () => this.render())
    );
    this.unsubscribers.push(
      eventBus.on(EVENTS.SESSION_TAB_NEW, () => this.render())
    );
    this.unsubscribers.push(
      eventBus.on(EVENTS.SESSION_TAB_UPDATE, () => this.render())
    );
    this.unsubscribers.push(
      eventBus.on(EVENTS.SESSION_TAB_CLOSE, () => this.render())
    );
    this.unsubscribers.push(
      eventBus.on(EVENTS.SESSION_TAB_NEW, () => this.render())
    );
    this.unsubscribers.push(
      eventBus.on(EVENTS.SESSION_TAB_UPDATE, () => this.render())
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
