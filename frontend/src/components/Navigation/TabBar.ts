import { Tab } from '../../types';
import { eventBus } from '../../utils/EventBus';
import { EVENTS } from '../../utils/constants';
import { createElement, cn } from '../../utils/helpers';
import { appState } from '../../state/AppState';

export class TabBar {
  private container: HTMLElement;
  private unsubscribers: (() => void)[] = [];

  constructor(private parentElement: HTMLElement) {
    this.container = createElement('div', {
      className: 'tab-bar',
      'data-testid': 'tab-bar',
    });
    this.render();
    this.setupListeners();
  }

  render(): void {
    this.container.innerHTML = '';

    const tabs = appState.getOpenTabs();
    const activeTabId = appState.getActiveTab();

    // Render each tab
    tabs.forEach((tab) => {
      const tabEl = this.createTabElement(tab, tab.id === activeTabId);
      this.container.appendChild(tabEl);
    });

    // Add "+" button
    const addBtn = createElement('button', {
      className: 'tab-add',
      'data-testid': 'tab-add',
    }, '+');
    addBtn.title = 'New project';
    addBtn.addEventListener('click', () => {
      this.handleNewProject();
    });
    this.container.appendChild(addBtn);

    // Ensure container is in DOM
    if (!this.container.parentElement) {
      this.parentElement.appendChild(this.container);
    }
  }

  private createTabElement(tab: Tab, isActive: boolean): HTMLElement {
    const tabEl = createElement('button', {
      className: cn('tab', isActive && 'active'),
      'data-testid': `tab-${tab.id}`,
      'data-tab-id': tab.id,
    });

    // Emoji
    if (tab.emoji) {
      const emojiSpan = createElement('span', { className: 'tab-emoji' }, tab.emoji);
      tabEl.appendChild(emojiSpan);
    }

    // Label
    const labelSpan = createElement('span', { className: 'tab-label' }, tab.label);
    tabEl.appendChild(labelSpan);

    // Notification dot
    if (tab.hasNotification) {
      const dot = createElement('span', { className: 'tab-notification' });
      tabEl.appendChild(dot);
    }

    // Close button (only for closable tabs)
    if (tab.closable) {
      const closeBtn = createElement('span', {
        className: 'tab-close',
        'data-testid': `tab-close-${tab.id}`,
      }, '×');
      closeBtn.addEventListener('click', (e) => {
        e.stopPropagation();
        appState.closeTab(tab.id);
      });
      tabEl.appendChild(closeBtn);
    }

    // Click to switch
    tabEl.addEventListener('click', () => {
      appState.switchTab(tab.id);
    });

    // Middle-click to close
    tabEl.addEventListener('auxclick', (e) => {
      if (e.button === 1 && tab.closable) {
        e.preventDefault();
        appState.closeTab(tab.id);
      }
    });

    return tabEl;
  }

  private handleNewProject(): void {
    // Switch to projects view to create a new project
    appState.setView('projects');
  }

  private setupListeners(): void {
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
    this.unsubscribers.push(
      eventBus.on(EVENTS.TAB_NOTIFICATION, () => this.render())
    );

    // When a project is created, offer to open it as a tab
    this.unsubscribers.push(
      eventBus.on(EVENTS.PROJECT_CREATED, (project: unknown) => {
        const p = project as { id: string; name: string };
        appState.openProjectTab(p.id, p.name);
      })
    );

    // Keyboard shortcuts: Ctrl+Tab to cycle tabs, Ctrl+W to close
    this.keydownHandler = this.keydownHandler.bind(this);
    document.addEventListener('keydown', this.keydownHandler);
  }

  private keydownHandler(e: KeyboardEvent): void {
    // Ctrl+Tab: cycle to next tab
    if (e.ctrlKey && e.key === 'Tab') {
      e.preventDefault();
      const tabs = appState.getOpenTabs();
      const activeId = appState.getActiveTab();
      const currentIndex = tabs.findIndex(t => t.id === activeId);
      const nextIndex = e.shiftKey
        ? (currentIndex - 1 + tabs.length) % tabs.length
        : (currentIndex + 1) % tabs.length;
      appState.switchTab(tabs[nextIndex].id);
    }

    // Ctrl+W: close current tab (if closable)
    if (e.ctrlKey && e.key === 'w') {
      const activeId = appState.getActiveTab();
      if (activeId !== 'main') {
        e.preventDefault();
        appState.closeTab(activeId);
      }
    }
  }

  update(): void {
    this.render();
  }

  destroy(): void {
    this.unsubscribers.forEach((unsub) => unsub());
    this.unsubscribers = [];
    document.removeEventListener('keydown', this.keydownHandler);
    this.container.remove();
  }
}
