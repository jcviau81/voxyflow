import { Message, ViewMode } from '../../types';
import { eventBus } from '../../utils/EventBus';
import { EVENTS, STREAMING_CHAR_DELAY, MAX_MESSAGE_LENGTH, AGENT_PERSONAS, SYSTEM_PROJECT_ID } from '../../utils/constants';
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
import { ttsService, cleanTextForSpeech } from '../../services/TtsService';
import { openMeetingNotesModal } from './MeetingNotesModal';
import { TaskPanel } from './TaskPanel';

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
  private taskPanel: TaskPanel | null = null;
  private unsubscribers: (() => void)[] = [];
  private autoScroll = true;
  private currentProjectView: 'chat' | 'kanban' | 'stats' | 'roadmap' | 'wiki' | 'sprint' | 'docs' = 'chat';

  // Session management — delegates to the project session system via getContextTabId().
  // For general/main chat, contextTabId = SYSTEM_PROJECT_ID.
  private get activeSessionId(): string {
    const contextTabId = this.getContextTabId();
    return appState.getActiveChatId(contextTabId) || '';
  }
  private set activeSessionId(value: string) {
    // Only used to sync chatService.activeSessionId — the actual session switch
    // is handled by SessionTabBar and appState.setActiveSession().
    chatService.activeSessionId = value;
  }

  // Code paste detection banner
  private codePasteBanner: HTMLElement | null = null;
  private pendingPastedCode = '';
  private boundHandleScroll: ((e: Event) => void) | null = null;
  private boundHandleKeyDown: ((e: KeyboardEvent) => void) | null = null;
  private boundHandleInputChange: (() => void) | null = null;
  private boundHandlePaste: ((e: ClipboardEvent) => void) | null = null;

  // Mode 2: Native dictation / paste auto-send debounce timer
  private dictationAutoSendTimer: ReturnType<typeof setTimeout> | null = null;

  constructor(private parentElement: HTMLElement) {
    this.container = createElement('div', { className: 'chat-window', 'data-testid': 'chat-window' });
    chatService.activeSessionId = this.activeSessionId;
    this.render();
    this.setupListeners();
  }

  render(): void {
    this.container.innerHTML = '';

    // === Top bar: Title + Tabs + Board toggle ===
    const topBar = this.renderTopBar();
    // === Bottom bar: Status + New + Clear + Search + Model Selector + Analyzer ===
    const bottomBar = this.renderBottomBar();

    // === Message list ===
    this.messageList = createElement('div', { className: 'chat-messages' });
    this.boundHandleScroll = this.handleScroll.bind(this);
    this.messageList.addEventListener('scroll', this.boundHandleScroll);

    // Render existing messages or welcome prompt
    const contextTabIdForRender = this.getContextTabId();
    let sessionIdForRender: string | undefined;
    const sessionsForRender = appState.getSessions(contextTabIdForRender);
    if (sessionsForRender.length > 0) {
      sessionIdForRender = appState.getActiveChatId(contextTabIdForRender);
    }
    const messages = chatService.getHistory(
      appState.get('currentProjectId') || SYSTEM_PROJECT_ID,
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
      // Try loading from backend before showing welcome
      this.loadHistoryFromBackend();
    } else if (messages.length === 0) {
      // Not connected yet — loading indicator is already shown, history will load on connect
    } else {
      messages.forEach((msg) => this.renderMessage(msg));
    }

    // === Input area ===
    this.inputArea = createElement('div', { className: 'chat-input-area' });

    this.textInput = createElement('textarea', {
      className: 'chat-input',
      placeholder: window.innerWidth <= 768 ? 'Message...' : 'Type a message or press Alt+V for voice...',
      'data-maxlength': MAX_MESSAGE_LENGTH.toString(),
      'data-testid': 'chat-input',
    }) as HTMLTextAreaElement;
    this.textInput.rows = 1;
    this.boundHandleKeyDown = this.handleKeyDown.bind(this);
    this.boundHandleInputChange = this.handleInputChange.bind(this);
    this.boundHandlePaste = this.handlePaste.bind(this);
    this.textInput.addEventListener('keydown', this.boundHandleKeyDown);
    this.textInput.addEventListener('input', this.boundHandleInputChange);
    this.textInput.addEventListener('paste', this.boundHandlePaste);

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

    // Voice toggle buttons (auto-send + auto-play)
    const voiceToggles = createElement('div', { className: 'voice-toggles' });
    const autoSendBtn = this.createVoiceToggle('stt_auto_send', '📤', 'Auto-send voice', false);
    const autoPlayBtn = this.createVoiceToggle('tts_auto_play', '🔊', 'Auto-play responses', false);
    voiceToggles.appendChild(autoSendBtn);
    voiceToggles.appendChild(autoPlayBtn);

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

    // Chat action menu (mobile: replaces emoji button with a ⊕ menu)
    const actionMenuContainer = createElement('div', { className: 'chat-action-menu-container' });
    const actionMenuBtn = createElement('button', { className: 'chat-action-menu-btn' }, '⋯');
    actionMenuBtn.title = 'Actions';
    const actionMenu = createElement('div', { className: 'chat-action-menu hidden' });
    
    const menuItemEmoji = createElement('button', { className: 'chat-action-menu-item' }, '😀 Emoji');
    menuItemEmoji.addEventListener('click', () => {
      actionMenu.classList.add('hidden');
      this.emojiPicker?.toggle();
    });
    
    const menuItemNewChat = createElement('button', { className: 'chat-action-menu-item' }, '✨ New Chat');
    menuItemNewChat.addEventListener('click', () => {
      actionMenu.classList.add('hidden');
      this.handleClearChat();
    });
    
    const menuItemClear = createElement('button', { className: 'chat-action-menu-item' }, '🗑️ Clear');
    menuItemClear.addEventListener('click', () => {
      actionMenu.classList.add('hidden');
      this.handleClearChat();
    });

    actionMenu.appendChild(menuItemNewChat);
    actionMenu.appendChild(menuItemEmoji);
    actionMenu.appendChild(menuItemClear);
    actionMenuContainer.appendChild(actionMenu);
    actionMenuContainer.appendChild(actionMenuBtn);
    
    actionMenuBtn.addEventListener('click', (e) => {
      e.stopPropagation();
      actionMenu.classList.toggle('hidden');
    });
    // Close menu on outside click
    document.addEventListener('click', () => actionMenu.classList.add('hidden'));

    // Input row: action menu + textarea + voice toggles + voice + send
    const inputRow = createElement('div', { className: 'chat-input-row' });
    // Desktop: show emoji button. Mobile: show action menu (CSS handles visibility)
    inputRow.appendChild(emojiContainer);
    inputRow.appendChild(actionMenuContainer);
    inputRow.appendChild(this.textInput);
    inputRow.appendChild(voiceToggles);
    inputRow.appendChild(voiceContainer);
    inputRow.appendChild(sendBtn);

    this.inputArea.appendChild(suggestionsWrapper);
    this.inputArea.appendChild(this.codePasteBanner);
    this.inputArea.appendChild(inputRow);

    // Session Tab Bar — show for project and card levels
    // Session Tab Bar — show for all contexts (main, project, card)
    this.sessionTabBar?.destroy();
    this.sessionTabBar = null;
    {
      const sessionTabId = this.getContextTabId();
      const sessionTabBarContainer = createElement('div', { className: 'session-tab-bar-wrap' });
      this.container.appendChild(sessionTabBarContainer);
      this.sessionTabBar = new SessionTabBar(sessionTabBarContainer, sessionTabId);
    }

    // GitHub Panel — moved to project properties (no longer shown above chat)
    this.githubPanel?.destroy();
    this.githubPanel = null;

    // TOP: Title + Tabs + Board toggle
    this.container.appendChild(topBar);

    this.container.appendChild(this.messageList);

    // Task panel — shows active Deep worker tasks above the input
    this.taskPanel?.destroy();
    this.taskPanel = new TaskPanel(this.container);

    // BOTTOM: Status + New + Clear + Search + Model Selector + Analyzer
    this.container.appendChild(bottomBar);

    // Mobile-only new chat button above input
    const newChatMobile = createElement('div', { className: 'chat-new-session-mobile', style: 'display:none' });
    const newChatBtn = createElement('button', {}, '✨ New Chat');
    newChatBtn.addEventListener('click', () => this.handleClearChat());
    newChatMobile.appendChild(newChatBtn);
    this.container.appendChild(newChatMobile);

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

  /** Create a small toggle button for a voice setting stored in voxyflow_settings.voice */
  private createVoiceToggle(settingKey: string, emoji: string, tooltip: string, defaultValue: boolean): HTMLButtonElement {
    const btn = createElement('button', {
      className: 'voice-toggle-btn',
      title: tooltip,
      'data-voice-setting': settingKey,
    }) as HTMLButtonElement;
    btn.textContent = emoji;

    // Read current state
    const isActive = this.getVoiceSetting(settingKey, defaultValue);
    if (isActive) btn.classList.add('active');

    btn.addEventListener('click', () => {
      const current = this.getVoiceSetting(settingKey, defaultValue);
      const newValue = !current;
      this.setVoiceSetting(settingKey, newValue);
      btn.classList.toggle('active', newValue);
    });

    return btn;
  }

  /** Read a voice setting from localStorage */
  private getVoiceSetting<T>(key: string, defaultValue: T): T {
    try {
      const stored = localStorage.getItem('voxyflow_settings');
      if (stored) {
        const settings = JSON.parse(stored);
        const val = settings?.voice?.[key];
        if (val !== undefined) return val as T;
      }
    } catch { /* ignore */ }
    return defaultValue;
  }

  /** Write a voice setting to localStorage */
  private setVoiceSetting(key: string, value: unknown): void {
    try {
      const stored = localStorage.getItem('voxyflow_settings');
      const settings = stored ? JSON.parse(stored) : {};
      if (!settings.voice) settings.voice = {};
      settings.voice[key] = value;
      localStorage.setItem('voxyflow_settings', JSON.stringify(settings));
    } catch { /* ignore */ }
  }

  private getChatLevel(): 'project' | 'card' {
    const cardId = appState.get('selectedCardId');
    if (cardId) return 'card';
    return 'project';
  }

  /** Get the context tab ID for the current view — handles 'main' → SYSTEM_PROJECT_ID */
  private getContextTabId(): string {
    const chatLevel = this.getChatLevel();
    const activeTabId = appState.getActiveTab();
    if (chatLevel === 'card') {
      return appState.get('selectedCardId') || activeTabId;
    }
    return activeTabId === 'main' ? SYSTEM_PROJECT_ID : activeTabId;
  }

  /** True when the active tab is the Main (system project) tab */
  private get isMainTab(): boolean {
    return appState.getActiveTab() === 'main';
  }

  private renderTopBar(): HTMLElement {
    const topBar = createElement('div', {
      className: 'chat-top-bar',
      'data-testid': 'chat-top-bar',
    });

    const chatLevel = this.getChatLevel();
    const cardId = appState.get('selectedCardId');
    const card = cardId ? appState.getCard(cardId) : null;

    // Only show top bar content for card-level chat (card title context)
    // For general and project levels, ProjectHeader handles everything
    if (chatLevel === 'card' && card) {
      const titleSection = createElement('div', {
        className: 'header-title-section',
        'data-testid': 'context-indicator',
      });
      const title = createElement('span', { className: 'header-title' });
      title.textContent = card.title.length > 40
        ? card.title.substring(0, 40) + '...'
        : card.title;
      titleSection.appendChild(title);
      topBar.appendChild(titleSection);
    } else {
      // Hide the bar entirely when not in card context
      topBar.style.display = 'none';
    }

    return topBar;
  }

  private renderBottomBar(): HTMLElement {
    const bottomBar = createElement('div', {
      className: 'chat-bottom-bar',
      'data-testid': 'chat-bottom-bar',
    });

    const chatLevel = this.getChatLevel();

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
    bottomBar.appendChild(connIndicator);

    if (chatLevel === 'project' && this.currentProjectView === 'kanban') {
      const newCardBtn = createElement('button', {
        className: 'header-btn header-btn-primary',
        'data-testid': 'new-card-btn',
      });
      newCardBtn.textContent = '+ New Card';
      newCardBtn.addEventListener('click', () => {
        eventBus.emit(EVENTS.MODAL_OPEN, { type: 'card-detail', mode: 'create', projectId: appState.get('currentProjectId') });
      });
      bottomBar.appendChild(newCardBtn);
    }

    // Clear button
    const clearBtn = createElement('button', {
      className: 'header-btn',
      title: 'Clear Chat',
      'data-testid': 'clear-chat-btn',
    });
    clearBtn.textContent = '🗑️';
    clearBtn.addEventListener('click', () => this.handleClearChat());
    bottomBar.appendChild(clearBtn);

    // Search button
    const searchBtn = createElement('button', {
      className: 'header-btn',
      title: 'Search Chat History (Ctrl+Shift+F)',
      'data-testid': 'chat-search-btn',
    });
    searchBtn.textContent = '🔍';
    searchBtn.addEventListener('click', () => {
      eventBus.emit(EVENTS.CHAT_SEARCH_OPEN, {});
    });
    bottomBar.appendChild(searchBtn);

    // Model status bar (model selector + analyzer)
    const statusBarContainer = createElement('div', { className: 'model-status-bar-container' });
    this.modelStatusBar = new ModelStatusBar(statusBarContainer);
    bottomBar.appendChild(statusBarContainer);

    return bottomBar;
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

  /**
   * Returns the active session ID for the current chat context.
   * Used to guard against rendering messages from other views.
   */
  private getActiveSessionId(): string | undefined {
    const contextTabId = this.getContextTabId();
    const sessions = appState.getSessions(contextTabId);
    if (sessions.length > 0) {
      return appState.getActiveChatId(contextTabId) || undefined;
    }
    return undefined;
  }

  /**
   * Check if a message belongs to the currently active view/session.
   * Messages without a sessionId are rejected — they cannot be routed reliably.
   */
  /** Auto-play TTS for assistant messages (skips enrichment/worker messages) */
  private speakAssistantMessage(msg: Message): void {
    if (msg.role !== 'assistant') return;
    // Don't speak enrichment/deep layer or worker messages
    if (msg.enrichment || msg.isWorkerResult) return;

    const cleaned = cleanTextForSpeech(msg.content);
    if (cleaned) {
      ttsService.speakIfAutoPlay(cleaned);
    }
  }

  private shouldRenderMessage(message: Message): boolean {
    if (!message.sessionId) {
      console.warn('[ChatWindow] Rejecting message without sessionId', message.id);
      return false;
    }

    const contextTabId = this.getContextTabId();
    const activeChatId = appState.getActiveChatId(contextTabId);
    return message.sessionId === activeChatId;
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
      sessionId: this.activeSessionId,
      chatId: this.activeSessionId,  // stable chatId for backend
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
    // Mobile: clear chat when mode switches (from TopBar)
    this.unsubscribers.push(
      eventBus.on('mobile:clear-chat', () => this.handleClearChat())
    );

    // Keyboard shortcut: Ctrl+Shift+N → New Session
    const keyboardHandler = (e: KeyboardEvent) => {
      if (e.ctrlKey && e.shiftKey && e.key === 'N') {
        e.preventDefault();
        this.handleNewSession();
      }
    };
    document.addEventListener('keydown', keyboardHandler);
    this.unsubscribers.push(() => document.removeEventListener('keydown', keyboardHandler));

    // Voice fill-input: put transcript text into the textarea instead of auto-sending
    this.unsubscribers.push(
      eventBus.on('voice:fill-input', (data: unknown) => {
        const { text } = data as { text: string };
        if (this.textInput) {
          this.textInput.value = text || '';
          // Trigger auto-resize
          this.textInput.style.height = 'auto';
          this.textInput.style.height = Math.min(this.textInput.scrollHeight, 150) + 'px';
          if (text) {
            this.textInput.focus();
            this.hideWelcomeIfNeeded();
          }
        }
      })
    );

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
            // Auto-play TTS for assistant responses — only if NOT streaming
            // (streamed messages get spoken at MESSAGE_STREAM_END instead)
            if (!msg.streaming) {
              this.speakAssistantMessage(msg);
            }
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
        // Auto-play TTS for streamed assistant responses
        const streamMsg = appState.getMessages().find((m) => m.id === messageId);
        if (streamMsg) {
          this.speakAssistantMessage(streamMsg);
        }
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
        // Remove loading indicator and load history when connected
        if (state === 'connected') {
          const loading = this.messageList?.querySelector('.chat-loading-indicator');
          if (loading) {
            loading.remove();
          }
          // Always reload history from backend on connect/reconnect.
          // This ensures we have the latest persisted messages, including any that
          // may have been lost due to localStorage staleness or session mismatch.
          this.loadHistoryFromBackend();
          // Reset all model status pills to idle on reconnection (safety net)
          this.modelStatusBar?.resetAllStatuses();
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
        this.updateChatControls();
      })
    );

    // Tab switch — reset view, rebuild context components, and update header
    this.unsubscribers.push(
      eventBus.on(EVENTS.TAB_SWITCH, () => {
        this.currentProjectView = 'chat';
        this.refreshContextComponents();
        this.reloadMessages();
        this.updateChatControls();
      })
    );

    // Tab close — send session:reset for ALL sessions belonging to the closed tab
    this.unsubscribers.push(
      eventBus.on(EVENTS.TAB_CLOSE, (data: unknown) => {
        const tabId = typeof data === 'string' ? data : (data as { tabId?: string })?.tabId;
        if (!tabId) return;
        // Retrieve all sessions for this tab before they are cleaned up
        const closedSessions = appState.getSessions(tabId);
        closedSessions.forEach((session) => {
          apiClient.send('session:reset', {
            sessionId: session.chatId,
            tabId,
          });
        });
      })
    );

    // Project change — reload messages and rebuild context-specific components
    this.unsubscribers.push(
      eventBus.on(EVENTS.PROJECT_SELECTED, () => {
        this.currentProjectView = 'chat';
        this.refreshContextComponents();
        this.reloadMessages();
        this.updateChatControls();
        this.smartSuggestions?.refresh();
      })
    );

    // Card selection — update header for card-level chat
    this.unsubscribers.push(
      eventBus.on(EVENTS.CARD_SELECTED, () => {
        this.reloadMessages();
        this.updateChatControls();
        this.smartSuggestions?.refresh();
      })
    );

    // Chat history search: jump to a chat/session from search results
    this.unsubscribers.push(
      eventBus.on(EVENTS.CHAT_SEARCH_JUMP, (_data: unknown) => {
        // Navigation was already handled by ChatSearch
        // (PROJECT_SELECTED / CARD_SELECTED events), just reload to ensure messages are current
        this.reloadMessages();
      })
    );

    // Session tab switch — reload messages for new session
    this.unsubscribers.push(
      eventBus.on(EVENTS.SESSION_TAB_SWITCH, (data: unknown) => {
        const { tabId } = data as { tabId: string; sessionId: string };
        const contextTabId = this.getContextTabId();
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
          'voxyflow.card.create_unassigned': 'Card added to Main Board',
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
            chatService.sendSystemInit("User wants to start a casual conversation. Greet them naturally based on the time of day and context. Do NOT say 'welcome back' — this may be a brand new user.");
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

    const contextTabId = this.getContextTabId();
    let sessionId: string | undefined;
    const sessionsRL = appState.getSessions(contextTabId);
    if (sessionsRL.length > 0) {
      sessionId = appState.getActiveChatId(contextTabId);
    }

    const messages = chatService.getHistory(
      appState.get('currentProjectId') || SYSTEM_PROJECT_ID,
      sessionId
    );

    if (messages.length === 0) {
      // No in-memory messages — try loading from backend
      this.loadHistoryFromBackend();
    } else {
      messages.forEach((msg) => this.renderMessage(msg));
      this.scrollToBottom();
    }
  }

  /**
   * Load chat history from the backend and render it.
   * Called on page load, reconnect, or when switching to an empty session.
   * Always replaces in-memory messages with authoritative backend data so that
   * stale localStorage snapshots don't hide recent messages after a page refresh.
   *
   * Chat IDs are now stable (no random UUIDs):
   * - Main chat: "project:system-main"
   * - Project chat: "project:{projectId}"
   * - Card chat: "card:{cardId}"
   * - Additional sessions: "project:system-main:session-2", etc.
   */
  private async loadHistoryFromBackend(): Promise<void> {
    const chatLevel = this.getChatLevel();
    const contextTabId = this.getContextTabId();
    let backendChatId: string;
    let projectId: string | undefined;
    let cardId: string | undefined;
    let sessionId: string | undefined;

    if (chatLevel === 'card') {
      const cid = appState.get('selectedCardId');
      if (!cid) { this.showWelcomePrompt(); return; }
      backendChatId = `card:${cid}`;
      cardId = cid;
      projectId = appState.get('currentProjectId') || SYSTEM_PROJECT_ID;
    } else {
      // Project chat (including Main/system-main)
      // The active session's chatId IS the backend chat_id (stable, no random UUID)
      const activeChatId = appState.getActiveChatId(contextTabId);
      sessionId = activeChatId;
      projectId = appState.get('currentProjectId') || SYSTEM_PROJECT_ID;
      backendChatId = activeChatId || `project:${contextTabId}`;
    }

    // Use replace=true: authoritative backend data replaces any stale localStorage snapshot.
    const loaded = await chatService.loadHistory(backendChatId, projectId, cardId, sessionId, true);

    if (!this.messageList) return;

    if (loaded.length > 0) {
      // Re-render with loaded messages
      this.messageList.innerHTML = '';
      this.messageBubbles.clear();
      this.welcomePrompt?.destroy();
      this.welcomePrompt = null;
      loaded.forEach((msg) => this.renderMessage(msg));
      this.scrollToBottom();
    } else {
      this.showWelcomePrompt();
    }
  }

  private updateChatControls(): void {
    // Re-render top bar and bottom bar to reflect current chat level
    this.modelStatusBar?.destroy();
    this.modelStatusBar = null;

    const oldTopBar = this.container.querySelector('[data-testid="chat-top-bar"]');
    if (oldTopBar) {
      const newTopBar = this.renderTopBar();
      oldTopBar.replaceWith(newTopBar);
    }

    const oldBottomBar = this.container.querySelector('[data-testid="chat-bottom-bar"]');
    if (oldBottomBar) {
      const newBottomBar = this.renderBottomBar();
      oldBottomBar.replaceWith(newBottomBar);
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

    if (this.githubPanel) {
      this.githubPanel = null;
    }

    // Recreate SessionTabBar for all contexts (main, project, card)
    {
      const sessionTabId = this.getContextTabId();
      const sessionTabBarContainer = createElement('div', { className: 'session-tab-bar-wrap' });
      if (this.messageList && this.messageList.parentElement === this.container) {
        this.container.insertBefore(sessionTabBarContainer, this.messageList);
      } else {
        this.container.appendChild(sessionTabBarContainer);
      }
      this.sessionTabBar = new SessionTabBar(sessionTabBarContainer, sessionTabId);
    }

    // GitHub panel moved to project properties — no longer rendered in chat
  }

  private showWelcomePrompt(): void {
    if (!this.messageList) return;

    // Destroy previous welcome prompt to prevent duplicates
    if (this.welcomePrompt) {
      this.welcomePrompt.destroy();
      this.welcomePrompt = null;
    }

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

  private async handleNewSession(): Promise<void> {
    // Create a new session on the server for a stable chat_id
    const contextTabId = this.getContextTabId();
    const projectId = appState.get('currentProjectId') || SYSTEM_PROJECT_ID;

    // Try server-side creation first
    const serverResult = await apiClient.createServerSession(projectId);
    let session: import('../../types').SessionInfo;

    if (serverResult) {
      // Server created the session — add to local state
      session = appState.addServerSession(contextTabId, serverResult.chatId, serverResult.title);
    } else {
      // Fallback: create locally with stable chatId
      session = appState.createSession(contextTabId);
    }

    chatService.activeSessionId = session.chatId;

    // Clear the message list UI
    if (this.messageList) {
      this.messageList.innerHTML = '';
    }
    this.messageBubbles.clear();

    // Show welcome prompt
    this.welcomePrompt?.destroy();
    this.welcomePrompt = null;
    this.showWelcomePrompt();

    // Auto-greet on new session
    chatService.sendSystemInit(
      "User just started a new session. Greet them naturally and briefly — one sentence max. Ask what they want to work on.",
      undefined,
      undefined,
      session.chatId,
    );

    // Update header
    this.updateChatControls();

    // Emit switch so SessionTabBar re-renders
    eventBus.emit(EVENTS.SESSION_TAB_SWITCH, { tabId: contextTabId, sessionId: session.id });

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

    // Mode 2: Native dictation / paste auto-send
    // When auto-send is ON and the custom mic (Mode 1) is NOT active,
    // debounce-send after 3s of inactivity. Works with Android/iOS native
    // dictation, paste, or any keyboard input.
    if (this.dictationAutoSendTimer) {
      clearTimeout(this.dictationAutoSendTimer);
      this.dictationAutoSendTimer = null;
    }
    if (val.trim() && !appState.get('voiceActive') && this.isAutoSendEnabled()) {
      this.dictationAutoSendTimer = setTimeout(() => {
        this.dictationAutoSendTimer = null;
        this.sendCurrentMessage();
      }, 3000);
    }
  }

  /** Check if voice auto-send is enabled in settings */
  private isAutoSendEnabled(): boolean {
    try {
      const stored = localStorage.getItem('voxyflow_settings');
      if (stored) {
        const settings = JSON.parse(stored);
        return settings?.voice?.stt_auto_send === true;
      }
    } catch { /* ignore */ }
    return false;
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
          '  Agents: `general`, `coder`, `architect`, `researcher`, `designer`, `writer`, `qa`',
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

        const validAgents = ['general', 'coder', 'architect', 'researcher', 'designer', 'writer', 'qa'];
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
        const standupProjectId = appState.get('currentProjectId') || SYSTEM_PROJECT_ID;
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

    // Clear Mode 2 dictation debounce timer (manual send or Enter key)
    if (this.dictationAutoSendTimer) {
      clearTimeout(this.dictationAutoSendTimer);
      this.dictationAutoSendTimer = null;
    }

    const contextTabId = this.getContextTabId();
    const sessionId = appState.getActiveChatId(contextTabId);

    // Update session title from first user message content
    if (this.sessionTabBar) {
      const activeSession = appState.getActiveSession(contextTabId);
      if (activeSession.title.match(/^Session \d+$/)) {
        this.sessionTabBar.updateSessionTitle(activeSession.id, content);
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
    if (this.dictationAutoSendTimer) {
      clearTimeout(this.dictationAutoSendTimer);
      this.dictationAutoSendTimer = null;
    }
    this.unsubscribers.forEach((unsub) => unsub());
    this.unsubscribers = [];
    if (this.messageList && this.boundHandleScroll) {
      this.messageList.removeEventListener('scroll', this.boundHandleScroll);
    }
    if (this.textInput) {
      if (this.boundHandleKeyDown) this.textInput.removeEventListener('keydown', this.boundHandleKeyDown);
      if (this.boundHandleInputChange) this.textInput.removeEventListener('input', this.boundHandleInputChange);
      if (this.boundHandlePaste) this.textInput.removeEventListener('paste', this.boundHandlePaste);
    }
    this.voiceInput?.destroy();
    this.emojiPicker?.destroy();
    this.modelStatusBar?.destroy();
    this.welcomePrompt?.destroy();
    this.slashMenu?.destroy();
    this.githubPanel?.destroy();
    this.sessionTabBar?.destroy();
    this.smartSuggestions?.destroy();
    this.chatSearch?.destroy();
    this.taskPanel?.destroy();
    this.messageBubbles.forEach((bubble) => bubble.destroy());
    this.messageBubbles.clear();
    this.container.remove();
  }
}
