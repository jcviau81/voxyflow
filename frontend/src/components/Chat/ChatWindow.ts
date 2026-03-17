import { Message } from '../../types';
import { eventBus } from '../../utils/EventBus';
import { EVENTS, STREAMING_CHAR_DELAY, MAX_MESSAGE_LENGTH } from '../../utils/constants';
import { createElement, markdownToHtml, formatTime, cn } from '../../utils/helpers';
import { appState } from '../../state/AppState';
import { chatService } from '../../services/ChatService';
import { VoiceInput } from './VoiceInput';
import { MessageBubble } from './MessageBubble';

export class ChatWindow {
  private container: HTMLElement;
  private messageList: HTMLElement | null = null;
  private inputArea: HTMLElement | null = null;
  private textInput: HTMLTextAreaElement | null = null;
  private voiceInput: VoiceInput | null = null;
  private messageBubbles: Map<string, MessageBubble> = new Map();
  private unsubscribers: (() => void)[] = [];
  private autoScroll = true;

  constructor(private parentElement: HTMLElement) {
    this.container = createElement('div', { className: 'chat-window', 'data-testid': 'chat-window' });
    this.render();
    this.setupListeners();
  }

  render(): void {
    this.container.innerHTML = '';

    // Header
    const header = createElement('div', { className: 'chat-header' });
    const title = createElement('h2', { className: 'chat-title' }, 'Chat');
    const connectionDot = createElement('span', { className: 'connection-dot' });
    header.appendChild(title);
    header.appendChild(connectionDot);

    // Message list
    this.messageList = createElement('div', { className: 'chat-messages' });
    this.messageList.addEventListener('scroll', this.handleScroll.bind(this));

    // Render existing messages
    const messages = chatService.getHistory(appState.get('currentProjectId') || undefined);
    messages.forEach((msg) => this.renderMessage(msg));

    // Input area
    this.inputArea = createElement('div', { className: 'chat-input-area' });

    this.textInput = createElement('textarea', {
      className: 'chat-input',
      placeholder: 'Type a message or press Alt+V for voice...',
      'data-maxlength': MAX_MESSAGE_LENGTH.toString(),
      'data-testid': 'chat-input',
    }) as HTMLTextAreaElement;
    this.textInput.rows = 1;
    this.textInput.addEventListener('keydown', this.handleKeyDown.bind(this));
    this.textInput.addEventListener('input', this.handleInputResize.bind(this));

    const sendBtn = createElement('button', { className: 'chat-send-btn' }, '→');
    sendBtn.addEventListener('click', () => this.sendCurrentMessage());

    // Voice input
    const voiceContainer = createElement('div', { className: 'voice-input-container' });
    this.voiceInput = new VoiceInput(voiceContainer);

    this.inputArea.appendChild(this.textInput);
    this.inputArea.appendChild(voiceContainer);
    this.inputArea.appendChild(sendBtn);

    this.container.appendChild(header);
    this.container.appendChild(this.messageList);
    this.container.appendChild(this.inputArea);

    this.parentElement.appendChild(this.container);
    this.scrollToBottom();
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
    // New messages
    this.unsubscribers.push(
      eventBus.on(EVENTS.MESSAGE_SENT, (message: unknown) => {
        this.renderMessage(message as Message);
      })
    );

    this.unsubscribers.push(
      eventBus.on(EVENTS.MESSAGE_RECEIVED, (message: unknown) => {
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

    // Project change — reload messages
    this.unsubscribers.push(
      eventBus.on(EVENTS.PROJECT_SELECTED, () => {
        this.reloadMessages();
      })
    );
  }

  private reloadMessages(): void {
    if (!this.messageList) return;
    this.messageList.innerHTML = '';
    this.messageBubbles.clear();

    const messages = chatService.getHistory(appState.get('currentProjectId') || undefined);
    messages.forEach((msg) => this.renderMessage(msg));
    this.scrollToBottom();
  }

  private handleKeyDown(event: KeyboardEvent): void {
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault();
      this.sendCurrentMessage();
    }
  }

  private handleInputResize(): void {
    if (!this.textInput) return;
    this.textInput.style.height = 'auto';
    this.textInput.style.height = Math.min(this.textInput.scrollHeight, 150) + 'px';
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
    this.messageBubbles.forEach((bubble) => bubble.destroy());
    this.messageBubbles.clear();
    this.container.remove();
  }
}
