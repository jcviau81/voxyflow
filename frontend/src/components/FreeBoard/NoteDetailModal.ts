import { Idea, Message } from '../../types';
import { eventBus } from '../../utils/EventBus';
import { EVENTS } from '../../utils/constants';
import { createElement } from '../../utils/helpers';
import { appState } from '../../state/AppState';
import { chatService } from '../../services/ChatService';

type CardColor = 'yellow' | 'blue' | 'green' | 'pink' | 'purple' | 'orange';

const COLOR_OPTIONS: { value: CardColor | null; label: string }[] = [
  { value: null,     label: 'None'   },
  { value: 'yellow', label: 'Yellow' },
  { value: 'blue',   label: 'Blue'   },
  { value: 'green',  label: 'Green'  },
  { value: 'pink',   label: 'Pink'   },
  { value: 'purple', label: 'Purple' },
  { value: 'orange', label: 'Orange' },
];

const MAX_CHAT_MESSAGES = 10;

export class NoteDetailModal {
  private overlay: HTMLElement;
  private modal: HTMLElement;
  private idea: Idea | null = null;
  private sessionId: string = '';
  private chatMessagesEl: HTMLElement | null = null;
  private unsubscribers: (() => void)[] = [];

  // Callbacks so FreeBoard can react to mutations
  onDeleted?: (ideaId: string) => void;
  onUpdated?: (idea: Idea) => void;

  constructor(private parentElement: HTMLElement) {
    this.overlay = createElement('div', { className: 'note-detail-modal-overlay hidden' });
    this.modal   = createElement('div', { className: 'note-detail-modal' });
    this.overlay.appendChild(this.modal);
    this.parentElement.appendChild(this.overlay);

    // Close on backdrop click
    this.overlay.addEventListener('click', (e) => {
      if (e.target === this.overlay) this.close();
    });

    // ESC to close
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape' && !this.overlay.classList.contains('hidden')) this.close();
    };
    document.addEventListener('keydown', onKey);
    this.unsubscribers.push(() => document.removeEventListener('keydown', onKey));

    // Refresh chat on any new message (filter by session inside refreshChat)
    const refreshIfRelevant = () => { if (this.idea) this.refreshChat(); };
    this.unsubscribers.push(eventBus.on(EVENTS.MESSAGE_RECEIVED,   refreshIfRelevant));
    this.unsubscribers.push(eventBus.on(EVENTS.MESSAGE_STREAM_END, refreshIfRelevant));
    this.unsubscribers.push(eventBus.on(EVENTS.MESSAGE_STREAMING,  refreshIfRelevant));
  }

  // ── Public API ────────────────────────────────────────────────

  open(idea: Idea): void {
    this.idea      = idea;
    this.sessionId = `note:${idea.id}`;
    this.renderContent();
    this.overlay.classList.remove('hidden');
  }

  close(): void {
    this.overlay.classList.add('hidden');
    this.idea = null;
    this.chatMessagesEl = null;
  }

  // ── State helpers ─────────────────────────────────────────────

  private saveIdea(updates: Partial<Idea>): void {
    if (!this.idea) return;
    this.idea = { ...this.idea, ...updates };
    const ideas = appState.getIdeas().map(i =>
      i.id === this.idea!.id ? this.idea! : i
    );
    appState.set('ideas', ideas);
    this.onUpdated?.(this.idea);
  }

  // ── Chat helpers ──────────────────────────────────────────────

  private refreshChat(): void {
    if (!this.chatMessagesEl || !this.idea) return;

    const messages = appState
      .getMessages(undefined, this.sessionId)
      .filter((m) => m.role === 'user' || m.role === 'assistant')
      .slice(-MAX_CHAT_MESSAGES);

    this.chatMessagesEl.innerHTML = '';

    if (messages.length === 0) {
      const hint = createElement('div', { className: 'note-mini-chat-empty' },
        'Ask Voxy anything about this note…');
      this.chatMessagesEl.appendChild(hint);
      return;
    }

    messages.forEach((msg: Message) => {
      const bubble = createElement('div', {
        className: `note-mini-chat-bubble note-mini-chat-bubble--${msg.role}`,
      });
      bubble.textContent = msg.streaming ? msg.content + '▋' : msg.content;
      this.chatMessagesEl!.appendChild(bubble);
    });

    // Scroll to bottom
    this.chatMessagesEl.scrollTop = this.chatMessagesEl.scrollHeight;
  }

  private sendChatMessage(content: string): void {
    if (!content.trim() || !this.idea) return;
    chatService.sendMessage(content.trim(), undefined, undefined, this.sessionId);
  }

  // ── Render ────────────────────────────────────────────────────

  private renderContent(): void {
    if (!this.idea) return;
    this.modal.innerHTML = '';
    this.chatMessagesEl = null;

    // Apply color class to modal
    this.modal.className = 'note-detail-modal';
    if (this.idea.color) this.modal.classList.add(`note-detail-modal--${this.idea.color}`);

    // ── Header ───────────────────────────────────────────────────
    const header = createElement('div', { className: 'note-detail-header' });

    // Inline-editable title
    const titleEl = createElement('div', {
      className: 'note-detail-title',
      contentEditable: 'true',
      spellcheck: 'false',
      title: 'Click to edit title',
    }) as HTMLElement;
    titleEl.textContent = this.idea.content;
    titleEl.addEventListener('blur', () => {
      const newTitle = (titleEl.textContent || '').trim();
      if (newTitle && newTitle !== this.idea?.content) {
        this.saveIdea({ content: newTitle });
      } else if (!newTitle) {
        // Restore if cleared
        titleEl.textContent = this.idea?.content || '';
      }
    });
    titleEl.addEventListener('keydown', (e) => {
      if (e.key === 'Enter') { e.preventDefault(); titleEl.blur(); }
      if (e.key === 'Escape') { titleEl.textContent = this.idea?.content || ''; titleEl.blur(); }
    });

    // Color picker
    const colorRow = createElement('div', { className: 'note-detail-color-row' });
    let selectedSwatch: HTMLElement | null = null;
    const currentColor = this.idea.color ?? null;

    COLOR_OPTIONS.forEach(({ value, label }) => {
      const cls = value
        ? `freeboard-color-swatch freeboard-color-swatch--${value}`
        : 'freeboard-color-swatch freeboard-color-swatch--none';
      const swatch = createElement('button', { className: cls, title: label, type: 'button' }) as HTMLButtonElement;

      if (value === currentColor || (!value && !currentColor)) {
        swatch.classList.add('selected');
        selectedSwatch = swatch;
      }

      swatch.addEventListener('click', () => {
        if (selectedSwatch) selectedSwatch.classList.remove('selected');
        swatch.classList.add('selected');
        selectedSwatch = swatch;
        this.saveIdea({ color: value as CardColor | undefined });
        // Update modal color accent immediately
        this.modal.className = 'note-detail-modal';
        if (value) this.modal.classList.add(`note-detail-modal--${value}`);
      });
      colorRow.appendChild(swatch);
    });

    // Header action buttons
    const headerBtns = createElement('div', { className: 'note-detail-header-btns' });

    const deleteBtn = createElement('button', {
      className: 'note-detail-btn note-detail-btn--delete',
      title: 'Delete note',
      type: 'button',
    }, '🗑️') as HTMLButtonElement;
    deleteBtn.addEventListener('click', () => {
      if (!this.idea) return;
      if (!confirm(`Delete "${this.idea.content}"?`)) return;
      const id = this.idea.id;
      appState.deleteIdea(id);
      this.onDeleted?.(id);
      this.close();
    });

    const closeBtn = createElement('button', {
      className: 'note-detail-btn note-detail-btn--close',
      title: 'Close',
      type: 'button',
    }, '×') as HTMLButtonElement;
    closeBtn.addEventListener('click', () => this.close());

    headerBtns.appendChild(deleteBtn);
    headerBtns.appendChild(closeBtn);
    header.appendChild(titleEl);
    header.appendChild(colorRow);
    header.appendChild(headerBtns);

    // ── Body ─────────────────────────────────────────────────────
    const body = createElement('div', { className: 'note-detail-body' });

    // ── Left/Top: Note content ────────────────────────────────────
    const contentSection = createElement('div', { className: 'note-detail-content' });

    const contentLabel = createElement('div', { className: 'note-detail-section-label' }, '📝 Note');

    const contentTextarea = createElement('textarea', {
      className: 'note-detail-content-textarea',
      placeholder: 'Add details…',
    }) as HTMLTextAreaElement;
    contentTextarea.value = this.idea.body || '';
    contentTextarea.addEventListener('blur', () => {
      const newBody = contentTextarea.value;
      this.saveIdea({ body: newBody || undefined });
    });

    const createdDate = new Date(this.idea.createdAt).toLocaleDateString(undefined, {
      year: 'numeric', month: 'short', day: 'numeric',
      hour: '2-digit', minute: '2-digit',
    });
    const metaEl = createElement('div', { className: 'note-detail-meta' }, `Created: ${createdDate}`);

    const promoteBtn = createElement('button', {
      className: 'note-detail-promote-btn',
      type: 'button',
      title: 'Promote to Project',
    }, '🚀 Promote to Project') as HTMLButtonElement;
    promoteBtn.addEventListener('click', () => {
      if (!this.idea) return;
      eventBus.emit(EVENTS.PROJECT_FORM_SHOW, {
        mode: 'create',
        prefillTitle: this.idea.content,
      });
      const id = this.idea.id;
      appState.deleteIdea(id);
      this.onDeleted?.(id);
      this.close();
    });

    contentSection.appendChild(contentLabel);
    contentSection.appendChild(contentTextarea);
    contentSection.appendChild(metaEl);
    contentSection.appendChild(promoteBtn);

    // ── Right/Bottom: Mini Chat ────────────────────────────────────
    const chatSection = createElement('div', { className: 'note-mini-chat' });

    const chatHeader = createElement('div', { className: 'note-mini-chat-header' });
    const chatTitle  = createElement('div', { className: 'note-mini-chat-title' }, '💬 Voxy');
    const chatHint   = createElement('div', { className: 'note-mini-chat-hint' }, 'scoped to this note');
    chatHeader.appendChild(chatTitle);
    chatHeader.appendChild(chatHint);

    const chatMessages = createElement('div', { className: 'note-mini-chat-messages' });
    this.chatMessagesEl = chatMessages;

    const inputRow = createElement('div', { className: 'note-mini-chat-input' });
    const chatInput = createElement('input', {
      type: 'text',
      className: 'note-mini-chat-input-field',
      placeholder: 'Ask Voxy about this note…',
    }) as HTMLInputElement;

    const sendBtn = createElement('button', {
      className: 'note-mini-chat-send-btn',
      type: 'button',
      title: 'Send',
    }, '↑') as HTMLButtonElement;

    const doSend = () => {
      const val = chatInput.value.trim();
      if (!val) return;
      chatInput.value = '';
      sendBtn.disabled = true;
      this.sendChatMessage(val);
      setTimeout(() => { sendBtn.disabled = false; }, 500);
    };

    sendBtn.addEventListener('click', doSend);
    chatInput.addEventListener('keydown', (e) => {
      if (e.key === 'Enter') { e.preventDefault(); doSend(); }
    });

    inputRow.appendChild(chatInput);
    inputRow.appendChild(sendBtn);

    chatSection.appendChild(chatHeader);
    chatSection.appendChild(chatMessages);
    chatSection.appendChild(inputRow);

    body.appendChild(contentSection);
    body.appendChild(chatSection);

    // ── Assemble ──────────────────────────────────────────────────
    this.modal.appendChild(header);
    this.modal.appendChild(body);

    // Note context is injected via the system prompt when the user sends their
    // first message. No auto-greeting — wait for user interaction.

    // Populate existing chat history
    this.refreshChat();

    // Focus the chat input
    setTimeout(() => chatInput.focus(), 80);
  }

  // ── Lifecycle ─────────────────────────────────────────────────

  destroy(): void {
    this.unsubscribers.forEach((unsub) => unsub());
    this.unsubscribers = [];
    this.overlay.remove();
  }
}
