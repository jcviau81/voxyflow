import { Message, ViewMode } from '../../types';
import { eventBus } from '../../utils/EventBus';
import { EVENTS, STREAMING_CHAR_DELAY, MAX_MESSAGE_LENGTH, AGENT_PERSONAS } from '../../utils/constants';
import { createElement, formatTime, cn } from '../../utils/helpers';
import { appState } from '../../state/AppState';
import { chatService } from '../../services/ChatService';
import { apiClient } from '../../services/ApiClient';
import { VoiceInput } from './VoiceInput';
import { MessageBubble } from './MessageBubble';
import { ModelStatusBar } from '../Navigation/ModelStatusBar';
import { EmojiPicker } from './EmojiPicker';
import { WelcomePrompt, WelcomeMode, WelcomeContext } from './WelcomePrompt';

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
  private unsubscribers: (() => void)[] = [];
  private autoScroll = true;
  private currentProjectView: 'chat' | 'kanban' = 'chat';

  // Session management (general chat only)
  private sessions: { id: string; label: string }[] = [{ id: 'session-1', label: 'Session 1' }];
  private activeSessionId = 'session-1';
  private sessionCounter = 1;

  constructor(private parentElement: HTMLElement) {
    this.container = createElement('div', { className: 'chat-window', 'data-testid': 'chat-window' });
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
    const messages = chatService.getHistory(appState.get('currentProjectId') || undefined);
    if (messages.length === 0) {
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

    this.inputArea.appendChild(emojiContainer);
    this.inputArea.appendChild(this.textInput);
    this.inputArea.appendChild(voiceContainer);
    this.inputArea.appendChild(sendBtn);

    this.container.appendChild(headerRow);
    this.container.appendChild(this.messageList);
    this.container.appendChild(this.inputArea);

    this.parentElement.appendChild(this.container);
    this.scrollToBottom();
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
    } else if (chatLevel === 'project' && project) {
      const emoji = createElement('span', { className: 'context-emoji header-emoji' });
      emoji.textContent = project.emoji || '📁';
      const name = createElement('span', { className: 'header-title' });
      name.textContent = project.name;
      titleSection.appendChild(emoji);
      titleSection.appendChild(name);
    } else {
      const emoji = createElement('span', { className: 'context-emoji header-emoji' });
      emoji.textContent = '💬';
      const name = createElement('span', { className: 'header-title' });
      name.textContent = 'General Chat';
      titleSection.appendChild(emoji);
      titleSection.appendChild(name);
    }

    headerRow.appendChild(titleSection);

    // CENTER: Session tabs (general only) or View toggle (project only)
    if (chatLevel === 'general') {
      const sessionTabs = this.renderSessionTabs();
      headerRow.appendChild(sessionTabs);
    } else if (chatLevel === 'project') {
      const viewToggle = this.renderViewToggle();
      headerRow.appendChild(viewToggle);
    }
    // Card: nothing in center

    // RIGHT: Actions + Model status
    const actions = createElement('div', { className: 'header-actions' });

    // Connection dot
    const connectionDot = createElement('span', { className: 'connection-dot' });
    actions.appendChild(connectionDot);

    // New Session button (general chat only)
    if (chatLevel === 'general') {
      const newBtn = createElement('button', {
        className: 'header-btn new-session-btn',
        title: 'New Session (Ctrl+Shift+N)',
        'data-testid': 'new-session-btn',
      });
      newBtn.textContent = '+ New';
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
      // Chat mode: show Clear + Model Status
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
      const tab = createElement('button', {
        className: `session-tab ${session.id === this.activeSessionId ? 'active' : ''}`,
        'data-session-id': session.id,
      });
      tab.textContent = session.label;
      tab.addEventListener('click', () => this.switchSession(session.id));
      container.appendChild(tab);
    });

    const addBtn = createElement('button', {
      className: 'session-tab-add',
      title: 'New session tab',
    });
    addBtn.textContent = '+';
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

    viewToggle.appendChild(chatBtn);
    viewToggle.appendChild(kanbanBtn);

    return viewToggle;
  }

  private switchSession(sessionId: string): void {
    if (sessionId === this.activeSessionId) return;
    this.activeSessionId = sessionId;
    this.reloadMessages();
    this.updateUnifiedHeader();
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
      // General chat: clear messages without a projectId
      appState.set(
        'messages',
        appState.get('messages').filter((m: Message) => !!m.projectId)
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
        this.hideWelcomeIfNeeded();
        this.renderMessage(message as Message);
      })
    );

    this.unsubscribers.push(
      eventBus.on(EVENTS.MESSAGE_RECEIVED, (message: unknown) => {
        this.hideWelcomeIfNeeded();
        this.renderMessage(message as Message);
      })
    );

    // Enrichment messages (Layer 2 — Opus deep thinking)
    this.unsubscribers.push(
      eventBus.on(EVENTS.MESSAGE_ENRICHMENT, (message: unknown) => {
        this.renderMessage(message as Message);
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
          // New streaming message
          const msg = appState.getMessages().find((m) => m.id === messageId);
          if (msg) this.renderMessage(msg);
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
      })
    );

    // Connection state
    this.unsubscribers.push(
      appState.subscribe('connectionState', (state) => {
        const dot = this.container.querySelector('.connection-dot');
        if (dot) {
          dot.className = `connection-dot ${state}`;
        }
      })
    );

    // View change — update header toggle state
    this.unsubscribers.push(
      eventBus.on(EVENTS.VIEW_CHANGE, (view: unknown) => {
        const v = view as ViewMode;
        if (v === 'chat' || v === 'kanban') {
          this.currentProjectView = v;
        }
        this.updateUnifiedHeader();
      })
    );

    // Tab switch — reset view and update header
    this.unsubscribers.push(
      eventBus.on(EVENTS.TAB_SWITCH, () => {
        this.currentProjectView = 'chat';
        this.updateUnifiedHeader();
      })
    );

    // Project change — reload messages
    this.unsubscribers.push(
      eventBus.on(EVENTS.PROJECT_SELECTED, () => {
        this.currentProjectView = 'chat';
        this.reloadMessages();
        this.updateUnifiedHeader();
      })
    );

    // Card selection — update header for card-level chat
    this.unsubscribers.push(
      eventBus.on(EVENTS.CARD_SELECTED, () => {
        this.reloadMessages();
        this.updateUnifiedHeader();
      })
    );

    // Welcome action handler
    this.unsubscribers.push(
      eventBus.on(EVENTS.WELCOME_ACTION, (data: unknown) => {
        const { action, mode } = data as { action: string; mode: string; cardId?: string };

        switch (action) {
          case 'chat':
          case 'chat-project':
          case 'discuss':
            // Just focus input
            this.textInput?.focus();
            break;

          case 'brainstorm':
            // Send an opening brainstorm message from user
            chatService.sendMessage("Let's brainstorm a new project! What should we build?");
            break;

          case 'brainstorm-task':
            chatService.sendMessage("Let's brainstorm a new task for this project.");
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

    const messages = chatService.getHistory(appState.get('currentProjectId') || undefined);
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
    this.sessionCounter++;
    const newSession = {
      id: `session-${this.sessionCounter}`,
      label: `Session ${this.sessionCounter}`,
    };
    this.sessions.push(newSession);
    this.activeSessionId = newSession.id;

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
    // Hide welcome prompt on typing
    if (this.textInput.value.trim().length > 0) {
      this.hideWelcomeIfNeeded();
    }
  }

  private sendCurrentMessage(): void {
    if (!this.textInput) return;
    const content = this.textInput.value.trim();
    if (!content) return;

    chatService.sendMessage(content);
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
    this.messageBubbles.forEach((bubble) => bubble.destroy());
    this.messageBubbles.clear();
    this.container.remove();
  }
}
