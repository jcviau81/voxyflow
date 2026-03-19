import { Message, ViewMode } from '../../types';
import { eventBus } from '../../utils/EventBus';
import { EVENTS, STREAMING_CHAR_DELAY, MAX_MESSAGE_LENGTH, AGENT_PERSONAS } from '../../utils/constants';
import { createElement, formatTime, cn, generateId } from '../../utils/helpers';
import { appState } from '../../state/AppState';
import { chatService } from '../../services/ChatService';
import { apiClient } from '../../services/ApiClient';
import { VoiceInput } from './VoiceInput';
import { MessageBubble } from './MessageBubble';
import { ModelStatusBar } from '../Navigation/ModelStatusBar';
import { EmojiPicker } from './EmojiPicker';
import { WelcomePrompt, WelcomeMode, WelcomeContext } from './WelcomePrompt';
import { SlashCommandMenu, SlashCommand } from './SlashCommands';
import { GitHubPanel } from '../Projects/GitHubPanel';
import { SessionTabBar } from './SessionTabBar';
import { ChatSearch } from './ChatSearch';
import { SmartSuggestions } from './SmartSuggestions';
import { codeReviewService } from '../../services/CodeReviewService';
import { openMeetingNotesModal } from './MeetingNotesModal';

export class ChatWindow {
  private container: HTMLElement;
  private messageList: HTMLElement | null = null;
  private inputArea: HTMLElement | null = null;
  private textInput: HTMLTextAreaElement | null = null;
  private voiceInput: VoiceInput | null = null;
  private emojiPicker: EmojiPicker | null = null;
  private modelStatusBar: ModelStatusBar | null = null;
  private welcomePrompt: WelcomePrompt | null = null;
  private messageBubbles: Map<string, MessageBubble> = new Map();
  private slashMenu: SlashCommandMenu | null = null;
  private githubPanel: GitHubPanel | null = null;
  private sessionTabBar: SessionTabBar | null = null;
  private smartSuggestions: SmartSuggestions | null = null;
  private chatSearch: ChatSearch | null = null;
  private unsubscribers: (() => void)[] = [];
  private autoScroll = true;
  private currentProjectView: 'chat' | 'kanban' | 'stats' | 'roadmap' | 'wiki' | 'sprint' | 'docs' = 'chat';

  // Session management (general chat only)
  private sessions: { id: string; label: string }[] = [{ id: 'session-1', label: 'Session 1' }];
  private activeSessionId = 'session-1';
  private sessionCounter = 1;

  // Code paste detection banner
  private codePasteBanner: HTMLElement | null = null;
  private pendingPastedCode = '';

  constructor(private parentElement: HTMLElement) {
    this.container = createElement('div', { className: 'chat-window', 'data-testid': 'chat-window' });
    chatService.activeSessionId = this.activeSessionId;
    this.render();
    this.setupListeners();
  }

  render(): void {
    this.container.innerHTML = '';

    // === Unified header row — adapts to 3 chat levels ===
    const headerRow = this.renderUnifiedHeader();

    // === Message list ===
    this.messageList = createElement('div', { className: 'chat-messages' });
    this.messageList.addEventListener('scroll', this.handleScroll.bind(this));

    // Render existing messages or welcome prompt
    const chatLevel = this.getChatLevel();
    let sessionIdForRender: string | undefined;
    if (chatLevel === 'general') {
      sessionIdForRender = this.activeSessionId;
    } else {
      const activeTabId = appState.getActiveTab();
      const contextTabId = chatLevel === 'card'
        ? (appState.get('selectedCardId') || activeTabId)
        : activeTabId;
      const sessions = appState.getSessions(contextTabId);
      if (sessions.length > 0) {
        sessionIdForRender = appState.getActiveChatId(contextTabId);
      }
    }
    const messages = chatService.getHistory(
      appState.get('currentProjectId') || undefined,
      sessionIdForRender
    );
    // Loading indicator while connecting
    const initConnState = appState.get('connectionState');
    if (initConnState !== 'connected') {
      const loadingEl = createElement('div', { className: 'chat-loading-indicator' });
      loadingEl.innerHTML = '<div class="chat-loading-spinner"></div><div class="chat-loading-text">Connecting to Voxy...</div>';
      this.messageList.appendChild(loadingEl);
    }

    if (messages.length === 0 && initConnState === 'connected') {
      this.showWelcomePrompt();
    }
    messages.forEach((msg) => this.renderMessage(msg));

    // === Input area ===
    this.inputArea = createElement('div', { className: 'chat-input-area' });

    this.textInput = createElement('textarea', {
      className: 'chat-input',
      placeholder: 'Type a message or press Alt+V for voice...',
      'data-maxlength': MAX_MESSAGE_LENGTH.toString(),
      'data-testid': 'chat-input',
    }) as HTMLTextAreaElement;
    this.textInput.rows = 1;
    this.textInput.addEventListener('keydown', this.handleKeyDown.bind(this));
    this.textInput.addEventListener('input', this.handleInputChange.bind(this));
    this.textInput.addEventListener('paste', this.handlePaste.bind(this));

    const sendBtn = createElement('button', { className: 'chat-send-btn' }, '→');
    sendBtn.addEventListener('click', () => this.sendCurrentMessage());

    // Emoji picker
    const emojiContainer = createElement('div', { className: 'emoji-picker-container' });
    const emojiBtn = createElement('button', { className: 'emoji-picker-btn' }, '😀');
    emojiBtn.title = 'Emoji picker';
    this.emojiPicker = new EmojiPicker(emojiContainer, (emoji: string) => {
      if (this.textInput) {
        const start = this.textInput.selectionStart || 0;
        const end = this.textInput.selectionEnd || 0;
        const val = this.textInput.value;
        this.textInput.value = val.slice(0, start) + emoji + val.slice(end);
        this.textInput.selectionStart = this.textInput.selectionEnd = start + emoji.length;
        this.textInput.focus();
        this.handleInputChange();
      }
    });
    emojiBtn.addEventListener('click', () => this.emojiPicker?.toggle());
    emojiContainer.appendChild(emojiBtn);

    // Voice input
    const voiceContainer = createElement('div', { className: 'voice-input-container' });
    this.voiceInput = new VoiceInput(voiceContainer);

    // Smart suggestions chips row (above textarea)
    const suggestionsWrapper = createElement('div', { className: 'quick-replies-wrapper' });
    this.smartSuggestions?.destroy();
    this.smartSuggestions = new SmartSuggestions(suggestionsWrapper, (text: string) => {
      if (this.textInput) {
        this.textInput.value = text;
        this.textInput.focus();
        this.handleInputChange();
      }
    });

    // Code paste detection banner (hidden by default)
    this.codePasteBanner = this.buildCodePasteBanner();

    // Input row: emoji + textarea + voice + send
    const inputRow = createElement('div', { className: 'chat-input-row' });
    inputRow.appendChild(emojiContainer);
    inputRow.appendChild(this.textInput);
    inputRow.appendChild(voiceContainer);
    inputRow.appendChild(sendBtn);

    this.inputArea.appendChild(suggestionsWrapper);
    this.inputArea.appendChild(this.codePasteBanner);
    this.inputArea.appendChild(inputRow);

    this.container.appendChild(headerRow);

    // Session Tab Bar — show for project and card levels
    this.sessionTabBar?.destroy();
    this.sessionTabBar = null;
    const chatLevelForST = this.getChatLevel();
    if (chatLevelForST === 'project' || chatLevelForST === 'card') {
      const activeTabId = appState.getActiveTab();
      // For card context, use the card id as the tabId so sessions are card-scoped
      const sessionTabId = chatLevelForST === 'card'
        ? (appState.get('selectedCardId') || activeTabId)
        : activeTabId;
      const sessionTabBarContainer = createElement('div', { className: 'session-tab-bar-wrap' });
      this.container.appendChild(sessionTabBarContainer);
      this.sessionTabBar = new SessionTabBar(sessionTabBarContainer, sessionTabId);
    }

    // GitHub Panel — show when project has a github_url and we're in project chat level
    this.githubPanel?.destroy();
    this.githubPanel = null;
    const chatLevelForGH = this.getChatLevel();
    if (chatLevelForGH === 'project') {
      const projectIdForGH = appState.get('currentProjectId');
      const projectForGH = projectIdForGH ? appState.getProject(projectIdForGH) : null;
      const ghUrl = projectForGH?.githubUrl || projectForGH?.githubRepo;
      if (ghUrl) {
        const ghContainer = createElement('div', { className: 'github-panel-wrap' });
        this.container.appendChild(ghContainer);
        this.githubPanel = new GitHubPanel(ghContainer, ghUrl);
      }
    }

    this.container.appendChild(this.messageList);
    this.container.appendChild(this.inputArea);

    // Slash command menu — anchored to the input area, floats above it
    this.slashMenu?.destroy();
    this.slashMenu = new SlashCommandMenu(this.inputArea, (cmd) => this.executeSlashCommand(cmd));

    this.parentElement.appendChild(this.container);
    this.scrollToBottom();

    // Chat history search panel (attached to parentElement so it overlays the window)
    this.chatSearch?.destroy();
    this.chatSearch = new ChatSearch(this.parentElement);
  }

  private getChatLevel(): 'general' | 'project' | 'card' {
    const cardId = appState.get('selectedCardId');
    if (cardId) return 'card';
    const activeTab = appState.getActiveTab();
    if (activeTab !== 'main') return 'project';
    return 'general';
  }

  private renderUnifiedHeader(): HTMLElement {
    const headerRow = createElement('div', {
      className: 'unified-header',
      'data-testid': 'unified-header',
    });

    const chatLevel = this.getChatLevel();
    const projectId = appState.get('currentProjectId');
    const project = projectId ? appState.getProject(projectId) : null;
    const cardId = appState.get('selectedCardId');
    const card = cardId ? appState.getCard(cardId) : null;

    // LEFT: Context title
    const titleSection = createElement('div', {
      className: 'header-title-section',
      'data-testid': 'context-indicator',
    });

    if (chatLevel === 'card' && card) {
      const title = createElement('span', { className: 'header-title' });
      title.textContent = card.title.length > 40
        ? card.title.substring(0, 40) + '...'
        : card.title;
      titleSection.appendChild(title);
    } else if (chatLevel === 'project') {
      // Project name + tabs are in shared ProjectHeader; just show minimal context here
    } else {
      // General chat: show a small indicator
      const title = createElement('span', { className: 'header-title' });
      title.textContent = '💬 Main Chat';
      titleSection.appendChild(title);
    }

    headerRow.appendChild(titleSection);

    // CENTER: Session tabs (general only) — project view toggle is now in shared ProjectHeader
    if (chatLevel === 'general') {
      const sessionTabs = this.renderSessionTabs();
      headerRow.appendChild(sessionTabs);
      const generalToggle = this.renderGeneralViewToggle();
      headerRow.appendChild(generalToggle);
    }
    // Project + Card: nothing in center (tabs in ProjectHeader)

    // RIGHT: Actions + Model status
    const actions = createElement('div', { className: 'header-actions' });

    // Connection status indicator
    const connState = appState.get('connectionState');
    const connIndicator = createElement('div', { className: `chat-conn-status ${connState}` });
    const connDot = createElement('span', { className: 'chat-conn-dot' });
    const connLabel = createElement('span', { className: 'chat-conn-label' },
      connState === 'connected' ? 'Connected' :
      connState === 'connecting' ? 'Connecting...' :
      connState === 'reconnecting' ? 'Reconnecting...' : 'Disconnected'
    );
    connIndicator.appendChild(connDot);
    connIndicator.appendChild(connLabel);
    actions.appendChild(connIndicator);

    // New Session button (general chat only)
    if (chatLevel === 'general') {
      const MAX_GENERAL_SESSIONS = 5;
      const newBtn = createElement('button', {
        className: 'header-btn new-session-btn',
        title: this.sessions.length >= MAX_GENERAL_SESSIONS ? `Max ${MAX_GENERAL_SESSIONS} sessions` : 'New Session (Ctrl+Shift+N)',
        'data-testid': 'new-session-btn',
      }) as HTMLButtonElement;
      newBtn.textContent = '+ New';
      if (this.sessions.length >= MAX_GENERAL_SESSIONS) {
        newBtn.disabled = true;
      }
      newBtn.addEventListener('click', () => this.handleNewSession());
      actions.appendChild(newBtn);
    }

    if (chatLevel === 'project' && this.currentProjectView === 'kanban') {
      // Kanban mode: only show New Card button
      const newCardBtn = createElement('button', {
        className: 'header-btn header-btn-primary',
        'data-testid': 'new-card-btn',
      });
      newCardBtn.textContent = '+ New Card';
      newCardBtn.addEventListener('click', () => {
        eventBus.emit(EVENTS.CARD_FORM_SHOW, { mode: 'create', projectId: appState.get('currentProjectId') });
      });
      actions.appendChild(newCardBtn);
    } else {
      // Chat mode: show Search + Clear + Model Status
      const searchBtn = createElement('button', {
        className: 'header-btn',
        title: 'Search Chat History (Ctrl+Shift+F)',
        'data-testid': 'chat-search-btn',
      });
      searchBtn.textContent = '🔍';
      searchBtn.addEventListener('click', () => {
        eventBus.emit(EVENTS.CHAT_SEARCH_OPEN, {});
      });
      actions.appendChild(searchBtn);

      const clearBtn = createElement('button', {
        className: 'header-btn',
        title: 'Clear Chat',
        'data-testid': 'clear-chat-btn',
      });
      clearBtn.textContent = '🗑️ Clear';
      clearBtn.addEventListener('click', () => this.handleClearChat());
      actions.appendChild(clearBtn);

      // Model status bar (inline)
      const statusBarContainer = createElement('div', { className: 'model-status-bar-container' });
      this.modelStatusBar = new ModelStatusBar(statusBarContainer);
      actions.appendChild(statusBarContainer);
    }

    headerRow.appendChild(actions);

    return headerRow;
  }

  private renderSessionTabs(): HTMLElement {
    const container = createElement('div', {
      className: 'session-tabs',
      'data-testid': 'session-tabs',
    });

    this.sessions.forEach((session) => {
      const tab = createElement('div', {
        className: `session-tab ${session.id === this.activeSessionId ? 'active' : ''}`,
        'data-session-id': session.id,
      });
      const label = createElement('span', { className: 'session-tab-label' });
      label.textContent = session.label;
      label.addEventListener('click', () => this.switchSession(session.id));
      tab.appendChild(label);

      // Close button (×)
      const closeBtn = createElement('button', { className: 'session-tab-close', title: 'Close session' });
      closeBtn.textContent = '×';
      closeBtn.addEventListener('click', (e) => {
        e.stopPropagation();
        if (this.sessions.length > 1) {
          // Remove session, switch to another
          this.sessions = this.sessions.filter(s => s.id !== session.id);
          if (this.activeSessionId === session.id) {
            this.activeSessionId = this.sessions[0]?.id || '';
          }
          this.updateUnifiedHeader();
          this.reloadMessages();
        } else {
          // Last session: reset
          this.sessions = [{ id: generateId(), label: 'Session 1' }];
          this.activeSessionId = this.sessions[0].id;
          this.updateUnifiedHeader();
          this.reloadMessages();
        }
      });
      tab.appendChild(closeBtn);
      container.appendChild(tab);
    });

    const MAX_GENERAL_SESSIONS = 5;
    const addBtn = createElement('button', {
      className: 'session-tab-add',
      title: this.sessions.length >= MAX_GENERAL_SESSIONS ? `Max ${MAX_GENERAL_SESSIONS} sessions` : 'New session tab',
    }) as HTMLButtonElement;
    addBtn.textContent = '+';
    if (this.sessions.length >= MAX_GENERAL_SESSIONS) {
      addBtn.disabled = true;
    }
    addBtn.addEventListener('click', () => this.handleNewSession());
    container.appendChild(addBtn);

    return container;
  }

  private renderViewToggle(): HTMLElement {
    const viewToggle = createElement('div', {
      className: 'view-toggle',
      'data-testid': 'view-toggle',
    });

    const chatBtn = createElement('button', {
      className: `view-btn ${this.currentProjectView === 'chat' ? 'active' : ''}`,
      'data-view': 'chat',
    }, '💬 Chat');
    chatBtn.addEventListener('click', () => {
      this.currentProjectView = 'chat';
      appState.setView('chat');
    });

    const kanbanBtn = createElement('button', {
      className: `view-btn ${this.currentProjectView === 'kanban' ? 'active' : ''}`,
      'data-view': 'kanban',
    }, '📋 Kanban');
    kanbanBtn.addEventListener('click', () => {
      this.currentProjectView = 'kanban';
      appState.setView('kanban');
    });

    const statsBtn = createElement('button', {
      className: `view-btn ${this.currentProjectView === 'stats' ? 'active' : ''}`,
      'data-view': 'stats',
    }, '📊 Stats');
    statsBtn.addEventListener('click', () => {
      this.currentProjectView = 'stats';
      appState.setView('stats');
    });

    const roadmapBtn = createElement('button', {
      className: `view-btn ${this.currentProjectView === 'roadmap' ? 'active' : ''}`,
      'data-view': 'roadmap',
    }, '📅 Roadmap');
    roadmapBtn.addEventListener('click', () => {
      this.currentProjectView = 'roadmap';
      appState.setView('roadmap');
    });

    const wikiBtn = createElement('button', {
      className: `view-btn ${this.currentProjectView === 'wiki' ? 'active' : ''}`,
      'data-view': 'wiki',
    }, '📖 Wiki');
    wikiBtn.addEventListener('click', () => {
      this.currentProjectView = 'wiki';
      appState.setView('wiki');
    });

    const sprintBtn = createElement('button', {
      className: `view-btn ${this.currentProjectView === 'sprint' ? 'active' : ''}`,
      'data-view': 'sprint',
    }, '🏃 Sprints');
    sprintBtn.addEventListener('click', () => {
      this.currentProjectView = 'sprint';
      appState.setView('sprint');
    });

    const docsBtn = createElement('button', {
      className: `view-btn ${this.currentProjectView === 'docs' ? 'active' : ''}`,
      'data-view': 'docs',
    }, '📚 Docs');
    docsBtn.addEventListener('click', () => {
      this.currentProjectView = 'docs';
      appState.setView('docs');
    });

    viewToggle.appendChild(chatBtn);
    viewToggle.appendChild(kanbanBtn);
    viewToggle.appendChild(statsBtn);
    viewToggle.appendChild(roadmapBtn);
    viewToggle.appendChild(wikiBtn);
    viewToggle.appendChild(sprintBtn);
    viewToggle.appendChild(docsBtn);

    return viewToggle;
  }

  private renderGeneralViewToggle(): HTMLElement {
    // Just a single "📝 Board" button — no "Chat" tab needed (session tabs handle that)
    const viewToggle = createElement('div', { className: 'view-toggle', 'data-testid': 'general-view-toggle' });
    const boardBtn = createElement('button', {
      className: 'view-btn',
      'data-view': 'freeboard',
    }, '📝 Board');
    boardBtn.addEventListener('click', () => appState.setView('freeboard'));
    viewToggle.appendChild(boardBtn);
    return viewToggle;
  }

  private switchSession(sessionId: string): void {
    if (sessionId === this.activeSessionId) return;
    this.activeSessionId = sessionId;
    chatService.activeSessionId = sessionId;
    // Clear unread indicator for this session
    this.clearSessionUnread(sessionId);
    this.reloadMessages();
    this.updateUnifiedHeader();
  }

  /**
   * Returns the active session ID for the current chat context (project, card, or general).
   * Used to guard against rendering messages from other views.
   */
  private getActiveSessionId(): string | undefined {
    const chatLevel = this.getChatLevel();
    if (chatLevel === 'general') {
      return this.activeSessionId;
    }
    const activeTabId = appState.getActiveTab();
    const contextTabId = chatLevel === 'card'
      ? (appState.get('selectedCardId') || activeTabId)
      : activeTabId;
    const sessions = appState.getSessions(contextTabId);
    if (sessions.length > 0) {
      return appState.getActiveChatId(contextTabId) || undefined;
    }
    return undefined;
  }

  /**
   * Check if a message belongs to the currently active view/session.
   * - General chat: must match activeSessionId.
   * - Project/card chat: if sessions exist, must match the active project/card session.
   *   If no sessions exist yet, allow messages with no sessionId (legacy/unsessioned project chat).
   */
  private shouldRenderMessage(message: Message): boolean {
    const chatLevel = this.getChatLevel();

    if (chatLevel === 'general') {
      // General chat: only render if sessionId matches the active general session
      return !message.sessionId || message.sessionId === this.activeSessionId;
    }

    // Project / card chat
    const activeTabId = appState.getActiveTab();
    const contextTabId = chatLevel === 'card'
      ? (appState.get('selectedCardId') || activeTabId)
      : activeTabId;
    const sessions = appState.getSessions(contextTabId);

    if (sessions.length === 0) {
      // No sessions yet — allow messages that have no sessionId or belong to the project
      return !message.sessionId;
    }

    const activeChatId = appState.getActiveChatId(contextTabId);
    // Allow messages with no sessionId only when there's no active session constraint
    return !message.sessionId || message.sessionId === activeChatId;
  }

  /**
   * Mark a session tab as having unread messages (show dot/badge).
   */
  private markSessionUnread(sessionId?: string): void {
    if (!sessionId || sessionId === this.activeSessionId) return;
    const tab = this.container.querySelector(
      `.session-tab[data-session-id="${sessionId}"]`
    );
    if (tab && !tab.classList.contains('has-unread')) {
      tab.classList.add('has-unread');
    }
  }

  /**
   * Clear the unread indicator for a session tab.
   */
  private clearSessionUnread(sessionId: string): void {
    const tab = this.container.querySelector(
      `.session-tab[data-session-id="${sessionId}"]`
    );
    if (tab) {
      tab.classList.remove('has-unread');
    }
  }

  private handleClearChat(): void {
    const currentProjectId = appState.get('currentProjectId');
    const cardId = appState.get('selectedCardId');

    // Clear messages for current context
    if (cardId) {
      appState.set(
        'messages',
        appState.get('messages').filter((m: Message) => m.cardId !== cardId)
      );
    } else if (currentProjectId) {
      appState.set(
        'messages',
        appState.get('messages').filter((m: Message) => m.projectId !== currentProjectId)
      );
    } else {
      // General chat: clear messages for the active session only
      appState.set(
        'messages',
        appState.get('messages').filter((m: Message) =>
          !!m.projectId || m.sessionId !== this.activeSessionId
        )
      );
    }

    // Clear the message list UI
    if (this.messageList) {
      this.messageList.innerHTML = '';
    }
    this.messageBubbles.clear();

    // Show welcome prompt again
    this.welcomePrompt?.destroy();
    this.welcomePrompt = null;
    this.showWelcomePrompt();

    // Notify backend to reset conversation context
    const chatLevel = this.getChatLevel();
    apiClient.send('session:reset', {
      chatLevel,
      projectId: currentProjectId || undefined,
      cardId: cardId || undefined,
    });

    // Focus input
    if (this.textInput) {
      this.textInput.focus();
    }
  }

  private renderMessage(message: Message): void {
    if (!this.messageList) return;

    const bubble = new MessageBubble(this.messageList, message);
    this.messageBubbles.set(message.id, bubble);

    if (this.autoScroll) {
      this.scrollToBottom();
    }
  }

  private setupListeners(): void {
    // Keyboard shortcut: Ctrl+Shift+N → New Session
    const keyboardHandler = (e: KeyboardEvent) => {
      if (e.ctrlKey && e.shiftKey && e.key === 'N') {
        e.preventDefault();
        this.handleNewSession();
      }
    };
    document.addEventListener('keydown', keyboardHandler);
    this.unsubscribers.push(() => document.removeEventListener('keydown', keyboardHandler));

    // New messages
    this.unsubscribers.push(
      eventBus.on(EVENTS.MESSAGE_SENT, (message: unknown) => {
        const msg = message as Message;
        if (this.shouldRenderMessage(msg)) {
          this.hideWelcomeIfNeeded();
          this.renderMessage(msg);
        }
      })
    );

    this.unsubscribers.push(
      eventBus.on(EVENTS.MESSAGE_RECEIVED, (message: unknown) => {
        const msg = message as Message;
        if (this.shouldRenderMessage(msg)) {
          this.hideWelcomeIfNeeded();
          this.renderMessage(msg);
          // Update smart suggestions based on AI response
          if (msg.role === 'assistant') {
            this.smartSuggestions?.onAiResponse(msg.content);
          }
        } else {
          // Mark the session tab as having unread messages
          this.markSessionUnread(msg.sessionId);
        }
      })
    );

    // Enrichment messages (Layer 2 — Deep thinking)
    this.unsubscribers.push(
      eventBus.on(EVENTS.MESSAGE_ENRICHMENT, (message: unknown) => {
        const msg = message as Message;
        if (this.shouldRenderMessage(msg)) {
          this.renderMessage(msg);
        } else {
          this.markSessionUnread(msg.sessionId);
        }
      })
    );

    // Streaming updates
    this.unsubscribers.push(
      eventBus.on(EVENTS.MESSAGE_STREAMING, (data: unknown) => {
        const { messageId, content } = data as { messageId: string; content: string };
        const bubble = this.messageBubbles.get(messageId);
        if (bubble) {
          bubble.updateContent(content, true);
        } else {
          // New streaming message — only render if it belongs to the active session
          const msg = appState.getMessages().find((m) => m.id === messageId);
          if (msg && this.shouldRenderMessage(msg)) {
            this.hideWelcomeIfNeeded();
            this.renderMessage(msg);
          } else if (msg) {
            this.markSessionUnread(msg.sessionId);
          }
        }
        if (this.autoScroll) this.scrollToBottom();
      })
    );

    this.unsubscribers.push(
      eventBus.on(EVENTS.MESSAGE_STREAM_END, (data: unknown) => {
        const { messageId, content } = data as { messageId: string; content: string };
        const bubble = this.messageBubbles.get(messageId);
        if (bubble) {
          bubble.updateContent(content, false);
        }
        // Update smart suggestions after stream ends
        this.smartSuggestions?.onAiResponse(content);
      })
    );

    // Connection state — update indicator in header
    this.unsubscribers.push(
      appState.subscribe('connectionState', (state) => {
        const indicator = this.container.querySelector('.chat-conn-status');
        if (indicator) {
          indicator.className = `chat-conn-status ${state}`;
          const label = indicator.querySelector('.chat-conn-label');
          if (label) {
            label.textContent =
              state === 'connected' ? 'Connected' :
              state === 'connecting' ? 'Connecting...' :
              state === 'reconnecting' ? 'Reconnecting...' : 'Disconnected';
          }
        }
        // Remove loading indicator and show welcome when connected
        if (state === 'connected') {
          const loading = this.messageList?.querySelector('.chat-loading-indicator');
          if (loading) {
            loading.remove();
            const msgs = chatService.getHistory(appState.get('currentProjectId') || undefined);
            if (msgs.length === 0) this.showWelcomePrompt();
          }
        }
      })
    );

    // View change — update header toggle state
    this.unsubscribers.push(
      eventBus.on(EVENTS.VIEW_CHANGE, (view: unknown) => {
        const v = view as ViewMode;
        if (v === 'chat' || v === 'kanban' || v === 'stats' || v === 'roadmap' || v === 'wiki' || v === 'sprint' || v === 'docs') {
          this.currentProjectView = v;
        }
        this.updateUnifiedHeader();
      })
    );

    // Tab switch — reset view, rebuild context components, and update header
    this.unsubscribers.push(
      eventBus.on(EVENTS.TAB_SWITCH, () => {
        this.currentProjectView = 'chat';
        this.refreshContextComponents();
        this.reloadMessages();
        this.updateUnifiedHeader();
      })
    );

    // Project change — reload messages and rebuild context-specific components
    this.unsubscribers.push(
      eventBus.on(EVENTS.PROJECT_SELECTED, () => {
        this.currentProjectView = 'chat';
        this.refreshContextComponents();
        this.reloadMessages();
        this.updateUnifiedHeader();
        this.smartSuggestions?.refresh();
      })
    );

    // Card selection — update header for card-level chat
    this.unsubscribers.push(
      eventBus.on(EVENTS.CARD_SELECTED, () => {
        this.reloadMessages();
        this.updateUnifiedHeader();
        this.smartSuggestions?.refresh();
      })
    );

    // Chat history search: jump to a chat/session from search results
    this.unsubscribers.push(
      eventBus.on(EVENTS.CHAT_SEARCH_JUMP, (data: unknown) => {
        const { chatId } = data as { chatId: string; messageId: string };
        // For general sessions, switch to matching session tab if possible
        if (chatId.startsWith('general:')) {
          const sessionId = chatId.replace('general:', '');
          const existingSession = this.sessions.find((s) => s.id === sessionId);
          if (existingSession) {
            this.switchSession(sessionId);
          }
        }
        // For project/card chats, navigation was already handled by ChatSearch
        // (PROJECT_SELECTED / CARD_SELECTED events), just reload to ensure messages are current
        this.reloadMessages();
      })
    );

    // Session tab switch (project/card context) — reload messages for new session
    this.unsubscribers.push(
      eventBus.on(EVENTS.SESSION_TAB_SWITCH, (data: unknown) => {
        const { tabId } = data as { tabId: string; sessionId: string };
        const chatLevel = this.getChatLevel();
        if (chatLevel === 'general') return; // Not our concern here

        const activeTabId = appState.getActiveTab();
        const contextTabId = chatLevel === 'card'
          ? (appState.get('selectedCardId') || activeTabId)
          : activeTabId;
        if (tabId === contextTabId) {
          this.reloadMessages();
        }
      })
    );

    // Tool execution system messages
    this.unsubscribers.push(
      eventBus.on(EVENTS.TOOL_EXECUTED, (data: unknown) => {
        const { tool, result } = data as { tool: string; args: Record<string, unknown>; result: Record<string, unknown> };
        if (!this.messageList) return;

        // Build a human-readable label for the tool
        const toolLabels: Record<string, string> = {
          'voxyflow.note.add': 'Note added to Main Board',
          'voxyflow.project.create': 'Project created',
          'voxyflow.card.create': 'Card created',
          'voxyflow.card.move': 'Card moved',
          'voxyflow.card.delete': 'Card deleted',
        };
        const status = result?.success ? '' : ' (failed)';
        const label = toolLabels[tool] || tool;
        const text = `🔧 *Executed ${tool}*${status} — ${label}`;

        const msgEl = document.createElement('div');
        msgEl.className = 'tool-execution-message';
        msgEl.textContent = text;
        this.messageList.appendChild(msgEl);

        if (this.autoScroll) {
          this.scrollToBottom();
        }
      })
    );

    // Welcome action handler
    this.unsubscribers.push(
      eventBus.on(EVENTS.WELCOME_ACTION, (data: unknown) => {
        const { action, mode } = data as { action: string; mode: string; cardId?: string };

        switch (action) {
          case 'chat':
            // Hidden init — Voxy responds but no user bubble shown
            chatService.sendSystemInit("User wants to start a casual conversation. Greet them warmly and ask what they'd like to do.");
            break;
          case 'chat-project':
            chatService.sendSystemInit("User wants to discuss this project. Summarize the current state and ask what they want to work on.");
            break;
          case 'discuss':
            chatService.sendSystemInit("User wants to discuss this task. Summarize the card and ask how you can help.");
            break;

          case 'brainstorm':
            chatService.sendSystemInit("User wants to brainstorm a new project idea. Ask them about their interests, suggest creative directions based on their existing projects.");
            break;

          case 'brainstorm-task':
            chatService.sendSystemInit("User wants to brainstorm a new task for this project. Suggest ideas based on the project context.");
            break;

          case 'start-work': {
            const cardData = data as { cardId?: string };
            if (cardData.cardId) {
              chatService.sendMessage(`Let's start working on this task.`, undefined, cardData.cardId);
            }
            break;
          }

          case 'enrich': {
            const enrichData = data as { cardId?: string };
            if (enrichData.cardId) {
              chatService.sendMessage(`Help me enrich this task with detailed requirements and a PRD.`, undefined, enrichData.cardId);
            }
            break;
          }

          case 'research': {
            const researchData = data as { cardId?: string };
            if (researchData.cardId) {
              chatService.sendMessage(`Let's research the best approaches for this task before we start.`, undefined, researchData.cardId);
            }
            break;
          }
        }
      })
    );
  }

  private reloadMessages(): void {
    if (!this.messageList) return;
    this.messageList.innerHTML = '';
    this.messageBubbles.clear();

    // Destroy old welcome prompt
    this.welcomePrompt?.destroy();
    this.welcomePrompt = null;

    const chatLevel = this.getChatLevel();
    let sessionId: string | undefined;

    if (chatLevel === 'general') {
      sessionId = this.activeSessionId;
    } else {
      const activeTabId = appState.getActiveTab();
      const contextTabId = chatLevel === 'card'
        ? (appState.get('selectedCardId') || activeTabId)
        : activeTabId;
      // Only filter by session chatId if sessions have been created (non-empty)
      const sessions = appState.getSessions(contextTabId);
      if (sessions.length > 0) {
        sessionId = appState.getActiveChatId(contextTabId);
      }
    }

    const messages = chatService.getHistory(
      appState.get('currentProjectId') || undefined,
      sessionId
    );
    if (messages.length === 0) {
      this.showWelcomePrompt();
    }
    messages.forEach((msg) => this.renderMessage(msg));
    this.scrollToBottom();
  }

  private updateUnifiedHeader(): void {
    // Re-render the entire header to reflect current chat level
    const oldHeader = this.container.querySelector('[data-testid="unified-header"]');
    if (oldHeader) {
      // Destroy old model status bar before replacing
      this.modelStatusBar?.destroy();
      this.modelStatusBar = null;

      const newHeader = this.renderUnifiedHeader();
      oldHeader.replaceWith(newHeader);
    }
  }

  /**
   * Destroy and recreate context-specific components (GitHub panel, SessionTabBar)
   * based on the current chat level / project context.
   *
   * Must be called whenever the active tab or project changes so that components
   * from the previous context are cleaned up and the correct ones are shown for
   * the new context.
   */
  private refreshContextComponents(): void {
    // --- Session Tab Bar ---
    if (this.sessionTabBar) {
      this.sessionTabBar.destroy();
      this.sessionTabBar = null;
    }
    // Remove any stale wrap elements left in the DOM
    this.container.querySelector('.session-tab-bar-wrap')?.remove();
    this.container.querySelector('.github-panel-wrap')?.remove();

    // Also destroy the GitHub panel reference (its DOM was just removed above)
    if (this.githubPanel) {
      // destroy() calls container.remove() but the wrap was already removed — that's fine
      this.githubPanel = null;
    }

    const chatLevel = this.getChatLevel();

    // Recreate SessionTabBar for project / card contexts
    if (chatLevel === 'project' || chatLevel === 'card') {
      const activeTabId = appState.getActiveTab();
      const sessionTabId = chatLevel === 'card'
        ? (appState.get('selectedCardId') || activeTabId)
        : activeTabId;
      const sessionTabBarContainer = createElement('div', { className: 'session-tab-bar-wrap' });
      // Insert before the message list so the order matches render()
      if (this.messageList && this.messageList.parentElement === this.container) {
        this.container.insertBefore(sessionTabBarContainer, this.messageList);
      } else {
        this.container.appendChild(sessionTabBarContainer);
      }
      this.sessionTabBar = new SessionTabBar(sessionTabBarContainer, sessionTabId);
    }

    // Recreate GitHub panel only for project context with a github_url
    if (chatLevel === 'project') {
      const projectId = appState.get('currentProjectId');
      const project = projectId ? appState.getProject(projectId) : null;
      const ghUrl = project?.githubUrl || (project as unknown as Record<string, string>)?.githubRepo;
      if (ghUrl) {
        const ghContainer = createElement('div', { className: 'github-panel-wrap' });
        // Insert before the message list (after session tab bar if present)
        if (this.messageList && this.messageList.parentElement === this.container) {
          this.container.insertBefore(ghContainer, this.messageList);
        } else {
          this.container.appendChild(ghContainer);
        }
        this.githubPanel = new GitHubPanel(ghContainer, ghUrl);
      }
    }
  }

  private showWelcomePrompt(): void {
    if (!this.messageList) return;

    const projectId = appState.get('currentProjectId');
    const cardId = appState.get('selectedCardId');

    let mode: WelcomeMode = 'general';
    const context: WelcomeContext = {};

    if (cardId) {
      mode = 'card';
      const card = appState.getCard(cardId);
      if (card) {
        context.card = card;
        context.tags = card.tags;
        // Resolve dependencies
        context.deps = card.dependencies
          .map((depId) => appState.getCard(depId))
          .filter((c): c is import('../../types').Card => !!c);
      }
    } else if (projectId) {
      mode = 'project';
      const project = appState.getProject(projectId);
      if (project) {
        context.project = project;
        const projectCards = appState.getCardsByProject(projectId);
        context.inProgressCards = projectCards.filter((c) => c.status === 'in-progress');
        context.todoCount = projectCards.filter((c) => c.status === 'todo').length;
      }
    }

    this.welcomePrompt = new WelcomePrompt(this.messageList, mode, context);
  }

  private hideWelcomeIfNeeded(): void {
    if (this.welcomePrompt?.isVisible()) {
      this.welcomePrompt.hide();
    }
  }

  private handleNewSession(): void {
    // Create a new session tab (general chat only)
    const MAX_GENERAL_SESSIONS = 5;
    if (this.sessions.length >= MAX_GENERAL_SESSIONS) return;
    // Label based on current count, not a global counter
    const nextNum = this.sessions.length + 1;
    const newSession = {
      id: generateId(),
      label: `Session ${nextNum}`,
    };
    this.sessions.push(newSession);
    this.activeSessionId = newSession.id;
    chatService.activeSessionId = newSession.id;

    // Clear the message list UI for the new session
    if (this.messageList) {
      this.messageList.innerHTML = '';
    }
    this.messageBubbles.clear();

    // Show welcome prompt
    this.welcomePrompt?.destroy();
    this.welcomePrompt = null;
    this.showWelcomePrompt();

    // Notify backend to reset conversation context
    apiClient.send('session:reset', {
      chatLevel: 'general',
      sessionId: newSession.id,
    });

    // Update header to show new tab
    this.updateUnifiedHeader();

    // Focus input
    if (this.textInput) {
      this.textInput.focus();
    }
  }

  private handleKeyDown(event: KeyboardEvent): void {
    // Let the slash menu consume navigation/confirm keys first
    if (this.slashMenu?.isVisible()) {
      const consumed = this.slashMenu.handleKey(event);
      if (consumed) {
        event.preventDefault();
        return;
      }
    }
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault();
      this.sendCurrentMessage();
    }
  }

  private handleInputChange(): void {
    if (!this.textInput) return;
    // Auto-resize
    this.textInput.style.height = 'auto';
    this.textInput.style.height = Math.min(this.textInput.scrollHeight, 150) + 'px';
    const val = this.textInput.value;
    // Hide welcome prompt on typing
    if (val.trim().length > 0) {
      this.hideWelcomeIfNeeded();
    }
    // Smart suggestions — fade out while typing
    this.smartSuggestions?.onUserTyping(val);
    // Slash command menu
    if (val.startsWith('/')) {
      this.slashMenu?.update(val);
    } else {
      this.slashMenu?.hide();
    }
  }

  private executeSlashCommand(cmd: SlashCommand): void {
    if (!this.textInput) return;
    const input = this.textInput.value.trim();

    // Clear input
    this.textInput.value = '';
    this.textInput.style.height = 'auto';
    this.textInput.focus();

    switch (cmd.name) {
      case '/new':
        this.handleNewSession();
        break;

      case '/clear':
        this.handleClearChat();
        break;

      case '/help': {
        const helpText = [
          '**Available commands:**',
          '`/new` — Start a new session',
          '`/clear` — Clear chat messages visually',
          '`/help` — Show this help message',
          '`/agent [name]` — Switch agent persona',
          '  Agents: `ember`, `coder`, `architect`, `researcher`, `designer`, `writer`, `qa`',
        ].join('\n');

        // Inject as an assistant message locally (no round-trip to server)
        const helpMsg: Message = {
          id: `slash-help-${Date.now()}`,
          role: 'assistant',
          content: helpText,
          timestamp: Date.now(),
          sessionId: this.activeSessionId,
        };
        this.hideWelcomeIfNeeded();
        this.renderMessage(helpMsg);
        break;
      }

      case '/agent': {
        // Parse agent name from typed input, e.g. "/agent coder"
        const parts = input.split(/\s+/);
        const agentName = parts[1]?.toLowerCase() || '';

        const validAgents = ['ember', 'coder', 'architect', 'researcher', 'designer', 'writer', 'qa'];
        if (!agentName || !validAgents.includes(agentName)) {
          const errMsg: Message = {
            id: `slash-agent-err-${Date.now()}`,
            role: 'assistant',
            content: `Unknown agent. Available: ${validAgents.map((a) => '`' + a + '`').join(', ')}`,
            timestamp: Date.now(),
            sessionId: this.activeSessionId,
          };
          this.hideWelcomeIfNeeded();
          this.renderMessage(errMsg);
        } else {
          eventBus.emit(EVENTS.AGENT_SWITCH, { agent: agentName });
          const confirmMsg: Message = {
            id: `slash-agent-ok-${Date.now()}`,
            role: 'assistant',
            content: `Switched to **${agentName}** agent.`,
            timestamp: Date.now(),
            sessionId: this.activeSessionId,
          };
          this.hideWelcomeIfNeeded();
          this.renderMessage(confirmMsg);
        }
        break;
      }

      case '/standup': {
        const standupProjectId = appState.get('currentProjectId');
        if (!standupProjectId) {
          const noProjectMsg: Message = {
            id: `slash-standup-err-${Date.now()}`,
            role: 'assistant',
            content: '⚠️ No project selected. Open a project to generate a standup.',
            timestamp: Date.now(),
            sessionId: this.activeSessionId,
          };
          this.hideWelcomeIfNeeded();
          this.renderMessage(noProjectMsg);
          break;
        }
        // Show loading message
        const loadingMsg: Message = {
          id: `slash-standup-loading-${Date.now()}`,
          role: 'assistant',
          content: '⏳ Generating daily standup…',
          timestamp: Date.now(),
          sessionId: this.activeSessionId,
        };
        this.hideWelcomeIfNeeded();
        this.renderMessage(loadingMsg);
        // Call API and show result
        fetch(`/api/projects/${standupProjectId}/standup`, { method: 'POST' })
          .then(r => r.json())
          .then(data => {
            const bubble = this.messageBubbles.get(loadingMsg.id);
            if (bubble) {
              bubble.updateContent(`📋 **Daily Standup**\n\n${data.summary}`, false);
            }
          })
          .catch(() => {
            const bubble = this.messageBubbles.get(loadingMsg.id);
            if (bubble) {
              bubble.updateContent('⚠️ Failed to generate standup. Try again.', false);
            }
          });
        break;
      }

      case '/meeting':
        openMeetingNotesModal();
        break;

      default:
        break;
    }
  }

  private sendCurrentMessage(): void {
    if (!this.textInput) return;
    const content = this.textInput.value.trim();
    if (!content) return;

    const chatLevel = this.getChatLevel();
    let sessionId: string | undefined;

    if (chatLevel === 'general') {
      sessionId = this.activeSessionId;
    } else {
      // project or card — use the active session's chatId
      const activeTabId = appState.getActiveTab();
      const contextTabId = chatLevel === 'card'
        ? (appState.get('selectedCardId') || activeTabId)
        : activeTabId;
      sessionId = appState.getActiveChatId(contextTabId);

      // Update session title from first user message content
      if (this.sessionTabBar) {
        const activeSession = appState.getActiveSession(contextTabId);
        if (activeSession.title.match(/^Session \d+$/)) {
          // Still has the default name — update with first 25 chars
          this.sessionTabBar.updateSessionTitle(activeSession.id, content);
        }
      }
    }

    chatService.sendMessage(content, undefined, undefined, sessionId);
    this.textInput.value = '';
    this.textInput.style.height = 'auto';
    this.textInput.focus();
  }

  private handleScroll(): void {
    if (!this.messageList) return;
    const { scrollTop, scrollHeight, clientHeight } = this.messageList;
    this.autoScroll = scrollHeight - scrollTop - clientHeight < 50;
  }

  private scrollToBottom(): void {
    if (!this.messageList) return;
    requestAnimationFrame(() => {
      this.messageList!.scrollTop = this.messageList!.scrollHeight;
    });
  }

  /** Build the code-paste detection banner element (hidden by default). */
  private buildCodePasteBanner(): HTMLElement {
    const banner = createElement('div', { className: 'code-paste-banner hidden' });

    const label = createElement('span', { className: 'code-paste-banner-label' });
    label.textContent = '💡 Looks like code! Want me to review it?';

    const reviewBtn = createElement('button', {
      className: 'code-paste-banner-btn code-paste-banner-review',
      type: 'button',
    }, '🔍 Review');

    const dismissBtn = createElement('button', {
      className: 'code-paste-banner-btn code-paste-banner-dismiss',
      type: 'button',
    }, '✕ Dismiss');

    reviewBtn.addEventListener('click', async () => {
      banner.classList.add('hidden');
      const code = this.pendingPastedCode;
      this.pendingPastedCode = '';
      if (!code) return;

      // Detect language (rough heuristic from the code itself)
      const lang = codeReviewService.detectLanguageFromCode(code);

      // Post a loading assistant message
      const loadingMsg: Message = {
        id: `code-review-${Date.now()}`,
        role: 'assistant',
        content: '⏳ Reviewing your code…',
        timestamp: Date.now(),
        sessionId: this.activeSessionId,
      };
      this.hideWelcomeIfNeeded();
      this.renderMessage(loadingMsg);

      try {
        const result = await codeReviewService.review(code, lang);
        const bubble = this.messageBubbles.get(loadingMsg.id);
        if (bubble) {
          bubble.updateContent(codeReviewService.formatResultAsMarkdown(result), false);
        }
      } catch {
        const bubble = this.messageBubbles.get(loadingMsg.id);
        if (bubble) {
          bubble.updateContent('⚠️ Code review failed. Please try again.', false);
        }
      }
    });

    dismissBtn.addEventListener('click', () => {
      banner.classList.add('hidden');
      this.pendingPastedCode = '';
    });

    banner.appendChild(label);
    banner.appendChild(reviewBtn);
    banner.appendChild(dismissBtn);
    return banner;
  }

  /** Handle paste events — detect if pasted content looks like code. */
  private handlePaste(event: ClipboardEvent): void {
    const pasted = event.clipboardData?.getData('text') || '';
    if (!pasted || pasted.length < 20) return;

    if (codeReviewService.looksLikeCode(pasted)) {
      this.pendingPastedCode = pasted;
      this.codePasteBanner?.classList.remove('hidden');

      // Auto-dismiss after 10s
      setTimeout(() => {
        this.codePasteBanner?.classList.add('hidden');
        this.pendingPastedCode = '';
      }, 10000);
    }
  }

  update(): void {
    this.reloadMessages();
  }

  destroy(): void {
    this.unsubscribers.forEach((unsub) => unsub());
    this.unsubscribers = [];
    this.voiceInput?.destroy();
    this.emojiPicker?.destroy();
    this.modelStatusBar?.destroy();
    this.welcomePrompt?.destroy();
    this.slashMenu?.destroy();
    this.githubPanel?.destroy();
    this.sessionTabBar?.destroy();
    this.smartSuggestions?.destroy();
    this.chatSearch?.destroy();
    this.messageBubbles.forEach((bubble) => bubble.destroy());
    this.messageBubbles.clear();
    this.container.remove();
  }
}
