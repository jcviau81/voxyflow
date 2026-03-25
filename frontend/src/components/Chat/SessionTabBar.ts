/**
 * SessionTabBar — secondary tab bar for switching/creating sessions
 * within a project or card context.
 *
 * Only shown when chatLevel is 'project' or 'card'.
 * Hidden for general chat (which has its own session UI in the header).
 */

import { SessionInfo } from '../../types';
import { eventBus } from '../../utils/EventBus';
import { EVENTS } from '../../utils/constants';
import { createElement } from '../../utils/helpers';
import { appState } from '../../state/AppState';
import { apiClient } from '../../services/ApiClient';

const MAX_SESSIONS = 5;
const MAX_TITLE_LENGTH = 25;

export class SessionTabBar {
  private container: HTMLElement;
  private tabsContainer: HTMLElement | null = null;
  private tabId: string;
  private scope: 'general' | 'project' | 'card';
  private unsubscribers: (() => void)[] = [];

  constructor(parentElement: HTMLElement, tabId: string, scope: 'general' | 'project' | 'card' = 'project') {
    this.tabId = tabId;
    this.scope = scope;
    this.container = createElement('div', {
      className: 'session-tab-bar',
      'data-testid': 'session-tab-bar',
    });
    parentElement.appendChild(this.container);
    this.render();
    this.setupListeners();
  }

  private render(): void {
    this.container.innerHTML = '';

    const sessions = appState.getSessions(this.tabId);
    const activeSession = appState.getActiveSession(this.tabId);

    this.tabsContainer = createElement('div', { className: 'session-tab-bar-tabs' });

    sessions.forEach((session) => {
      const isActive = session.id === activeSession.id;
      const tab = createElement('div', {
        className: `session-tab ${isActive ? 'active' : ''}`,
        'data-session-id': session.id,
        title: session.title,
      });

      const label = createElement('span', { className: 'session-tab-label' });
      label.textContent = this.truncateTitle(session.title);
      tab.appendChild(label);

      // Close button (×) — disabled if only 1 session
      const closeBtn = createElement('button', {
        className: 'session-tab-close',
        title: 'Close session',
        'data-session-id': session.id,
      });
      closeBtn.textContent = '×';
      closeBtn.addEventListener('click', (e) => {
        e.stopPropagation();
        if (sessions.length > 1) {
          this.handleClose(session.id);
        } else {
          // Last session: notify backend BEFORE resetting local state
          const closedChatId = session.chatId;
          apiClient.send('session:reset', {
            sessionId: closedChatId,
            tabId: this.tabId,
          });
          // Reset it (clear history, create fresh session)
          appState.closeSession(this.tabId, session.id);
          appState.createSession(this.tabId, this.scope);
          this.render();
          eventBus.emit(EVENTS.SESSION_TAB_SWITCH);
        }
      });
      tab.appendChild(closeBtn);

      tab.addEventListener('click', () => {
        if (!isActive) {
          this.handleSwitch(session.id);
        }
      });

      this.tabsContainer!.appendChild(tab);
    });

    this.container.appendChild(this.tabsContainer);

    // + button
    const addBtn = createElement('button', {
      className: 'session-tab-new',
      title: 'New session',
      'data-testid': 'session-tab-new',
    });
    addBtn.textContent = '+';
    if (sessions.length >= MAX_SESSIONS) {
      addBtn.setAttribute('disabled', 'true');
      addBtn.setAttribute('aria-disabled', 'true');
      addBtn.title = `Max ${MAX_SESSIONS} sessions`;
    }
    addBtn.addEventListener('click', () => {
      if (sessions.length < MAX_SESSIONS) {
        this.handleNew();
      }
    });
    this.container.appendChild(addBtn);
  }

  private truncateTitle(title: string): string {
    if (title.length <= MAX_TITLE_LENGTH) return title;
    return title.slice(0, MAX_TITLE_LENGTH - 1) + '…';
  }

  private handleSwitch(sessionId: string): void {
    appState.setActiveSession(this.tabId, sessionId);
    // EVENT_SESSION_TAB_SWITCH is already emitted by setActiveSession
  }

  private handleClose(sessionId: string): void {
    // Resolve chatId BEFORE removing from state so we can notify the backend
    const sessions = appState.getSessions(this.tabId);
    const session = sessions.find((s) => s.id === sessionId);
    if (session) {
      apiClient.send('session:reset', {
        sessionId: session.chatId,
        tabId: this.tabId,
      });
    }
    appState.closeSession(this.tabId, sessionId);
    // closeSession emits SESSION_TAB_CLOSE
  }

  private handleNew(): void {
    const session = appState.createSession(this.tabId, this.scope);
    // Emit switch so ChatWindow reloads messages
    eventBus.emit(EVENTS.SESSION_TAB_SWITCH, { tabId: this.tabId, sessionId: session.id });
    eventBus.emit(EVENTS.SESSION_TAB_NEW, { tabId: this.tabId, session });
  }

  private setupListeners(): void {
    // Re-render when sessions change
    this.unsubscribers.push(
      eventBus.on(EVENTS.SESSION_TAB_SWITCH, (data: unknown) => {
        const { tabId } = data as { tabId: string; sessionId: string };
        if (tabId === this.tabId) {
          this.render();
        }
      })
    );

    this.unsubscribers.push(
      eventBus.on(EVENTS.SESSION_TAB_CLOSE, (data: unknown) => {
        const { tabId } = data as { tabId: string; sessionId: string };
        if (tabId === this.tabId) {
          this.render();
        }
      })
    );

    this.unsubscribers.push(
      eventBus.on(EVENTS.SESSION_TAB_NEW, (data: unknown) => {
        const { tabId } = data as { tabId: string };
        if (tabId === this.tabId) {
          this.render();
        }
      })
    );

    this.unsubscribers.push(
      eventBus.on(EVENTS.SESSION_TAB_UPDATE, (data: unknown) => {
        const { tabId } = data as { tabId: string };
        if (tabId === this.tabId) {
          this.render();
        }
      })
    );
  }

  /** Update the session tab's title based on first user message content. */
  updateSessionTitle(sessionId: string, firstMessage: string): void {
    const title = firstMessage.trim().slice(0, MAX_TITLE_LENGTH) || 'Session';
    appState.updateSessionTitle(this.tabId, sessionId, title);
  }

  /** Change which tabId this bar tracks (e.g., when project/card context changes). */
  setTabId(tabId: string): void {
    this.tabId = tabId;
    this.render();
  }

  show(): void {
    this.container.style.display = 'flex';
  }

  hide(): void {
    this.container.style.display = 'none';
  }

  destroy(): void {
    this.unsubscribers.forEach((unsub) => unsub());
    this.unsubscribers = [];
    this.container.remove();
  }
}
