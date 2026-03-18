/**
 * ChatSearch — slide-in panel for searching past conversation history.
 *
 * Trigger: Ctrl+Shift+F or the 🔍 button in the chat header.
 * Close:   Escape key or clicking outside.
 */

import { createElement, formatTime } from '../../utils/helpers';
import { EVENTS } from '../../utils/constants';
import { eventBus } from '../../utils/EventBus';
import { apiClient, SearchResult } from '../../services/ApiClient';
import { appState } from '../../state/AppState';

export class ChatSearch {
  private panel: HTMLElement;
  private input: HTMLInputElement | null = null;
  private resultsList: HTMLElement | null = null;
  private statusEl: HTMLElement | null = null;
  private debounceTimer: ReturnType<typeof setTimeout> | null = null;
  private isOpen = false;
  private keydownHandler: (e: KeyboardEvent) => void;
  private unsubscribers: (() => void)[] = [];

  constructor(private parentElement: HTMLElement) {
    this.panel = createElement('div', { className: 'chat-search-panel', role: 'dialog', 'aria-label': 'Chat History Search' });
    this.panel.setAttribute('aria-hidden', 'true');
    this.buildPanel();
    this.parentElement.appendChild(this.panel);

    // Global keyboard shortcut: Ctrl+Shift+F
    this.keydownHandler = (e: KeyboardEvent) => {
      if (e.ctrlKey && e.shiftKey && e.key === 'F') {
        e.preventDefault();
        this.toggle();
      } else if (e.key === 'Escape' && this.isOpen) {
        e.stopPropagation();
        this.close();
      }
    };
    document.addEventListener('keydown', this.keydownHandler);

    // Listen for open/close via event bus
    this.unsubscribers.push(
      eventBus.on(EVENTS.CHAT_SEARCH_OPEN, () => this.open()),
      eventBus.on(EVENTS.CHAT_SEARCH_CLOSE, () => this.close()),
    );
  }

  // ---------------------------------------------------------------------------
  // Build
  // ---------------------------------------------------------------------------

  private buildPanel(): void {
    this.panel.innerHTML = '';

    // Header row
    const header = createElement('div', { className: 'chat-search-header' });

    const title = createElement('span', { className: 'chat-search-title' });
    title.textContent = '🔍 Search Chat History';

    const closeBtn = createElement('button', {
      className: 'chat-search-close-btn',
      title: 'Close (Escape)',
      'aria-label': 'Close search',
    });
    closeBtn.textContent = '✕';
    closeBtn.addEventListener('click', () => this.close());

    header.appendChild(title);
    header.appendChild(closeBtn);

    // Search input
    this.input = createElement('input', {
      type: 'text',
      className: 'chat-search-input',
      placeholder: 'Search messages…',
      'aria-label': 'Search query',
      autocomplete: 'off',
    }) as HTMLInputElement;

    this.input.addEventListener('input', () => this.handleInputChange());

    // Status / loading indicator
    this.statusEl = createElement('div', { className: 'chat-search-status' });
    this.statusEl.style.display = 'none';

    // Results list
    this.resultsList = createElement('div', {
      className: 'chat-search-results',
      role: 'list',
    });

    this.panel.appendChild(header);
    this.panel.appendChild(this.input);
    this.panel.appendChild(this.statusEl);
    this.panel.appendChild(this.resultsList);
  }

  // ---------------------------------------------------------------------------
  // Open / Close / Toggle
  // ---------------------------------------------------------------------------

  open(): void {
    if (this.isOpen) {
      this.input?.focus();
      return;
    }
    this.isOpen = true;
    this.panel.classList.add('open');
    this.panel.setAttribute('aria-hidden', 'false');
    // Slight delay so CSS transition fires
    requestAnimationFrame(() => this.input?.focus());
  }

  close(): void {
    if (!this.isOpen) return;
    this.isOpen = false;
    this.panel.classList.remove('open');
    this.panel.setAttribute('aria-hidden', 'true');
  }

  toggle(): void {
    if (this.isOpen) {
      this.close();
    } else {
      this.open();
    }
  }

  // ---------------------------------------------------------------------------
  // Search logic (debounced 300 ms)
  // ---------------------------------------------------------------------------

  private handleInputChange(): void {
    if (this.debounceTimer) {
      clearTimeout(this.debounceTimer);
    }
    const query = this.input?.value.trim() ?? '';
    if (!query) {
      this.clearResults();
      return;
    }
    this.debounceTimer = setTimeout(() => this.runSearch(query), 300);
  }

  private async runSearch(query: string): Promise<void> {
    if (!this.resultsList || !this.statusEl) return;

    this.statusEl.textContent = 'Searching…';
    this.statusEl.style.display = 'block';
    this.resultsList.innerHTML = '';

    const projectId = appState.get('currentProjectId') || undefined;
    const results = await apiClient.searchMessages(query, projectId);

    this.statusEl.style.display = 'none';

    if (results.length === 0) {
      const empty = createElement('div', { className: 'chat-search-empty' });
      empty.textContent = 'No messages found.';
      this.resultsList.appendChild(empty);
      return;
    }

    results.forEach((r) => this.renderResult(r, query));
  }

  private clearResults(): void {
    if (this.resultsList) this.resultsList.innerHTML = '';
    if (this.statusEl) this.statusEl.style.display = 'none';
  }

  // ---------------------------------------------------------------------------
  // Render a single result row
  // ---------------------------------------------------------------------------

  private renderResult(result: SearchResult, query: string): void {
    if (!this.resultsList) return;

    const row = createElement('div', {
      className: 'chat-search-result',
      role: 'listitem',
    });

    // Role icon
    const roleIcon = createElement('span', { className: 'chat-search-role-icon' });
    roleIcon.textContent = result.role === 'user' ? '🧑' : result.role === 'assistant' ? '🤖' : '⚙️';
    roleIcon.title = result.role;

    // Snippet with highlighted match
    const snippetEl = createElement('span', { className: 'chat-search-snippet' });
    snippetEl.innerHTML = this.highlightMatch(result.snippet, query);

    // Timestamp
    const tsEl = createElement('span', { className: 'chat-search-timestamp' });
    tsEl.textContent = result.created_at
      ? formatTime(new Date(result.created_at).getTime())
      : '';

    // "Go to" button
    const gotoBtn = createElement('button', {
      className: 'chat-search-goto-btn',
      title: `Jump to this conversation (${result.chat_id})`,
    });
    gotoBtn.textContent = 'Go to →';
    gotoBtn.addEventListener('click', () => this.jumpToResult(result));

    row.appendChild(roleIcon);
    row.appendChild(snippetEl);
    row.appendChild(tsEl);
    row.appendChild(gotoBtn);
    this.resultsList.appendChild(row);
  }

  /**
   * Wrap the matched substring in a <mark> for visual highlight.
   */
  private highlightMatch(text: string, query: string): string {
    // Escape special regex chars
    const escaped = query.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
    const regex = new RegExp(`(${escaped})`, 'gi');
    // Escape HTML first to avoid XSS
    const safe = text
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;');
    return safe.replace(regex, '<mark>$1</mark>');
  }

  // ---------------------------------------------------------------------------
  // Navigation: jump to the chat/session that contains the result
  // ---------------------------------------------------------------------------

  private jumpToResult(result: SearchResult): void {
    const chatId = result.chat_id;

    // Determine context from chat_id prefix
    // chat_id formats: "general:{sessionId}", "project:{projectId}", "card:{cardId}"
    if (chatId.startsWith('card:')) {
      const cardId = chatId.replace('card:', '');
      eventBus.emit(EVENTS.CARD_SELECTED, { cardId });
    } else if (chatId.startsWith('project:')) {
      const projectId = chatId.replace('project:', '');
      eventBus.emit(EVENTS.PROJECT_SELECTED, { projectId });
    }
    // For general sessions we can't easily jump to a specific message without
    // additional plumbing, so we emit CHAT_SEARCH_JUMP and let ChatWindow handle it.

    eventBus.emit(EVENTS.CHAT_SEARCH_JUMP, { chatId, messageId: result.message_id });
    this.close();
  }

  // ---------------------------------------------------------------------------
  // Destroy
  // ---------------------------------------------------------------------------

  destroy(): void {
    document.removeEventListener('keydown', this.keydownHandler);
    this.unsubscribers.forEach((u) => u());
    this.unsubscribers = [];
    if (this.debounceTimer) clearTimeout(this.debounceTimer);
    this.panel.remove();
  }
}
