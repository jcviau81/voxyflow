/**
 * Unified CardDetailModal — renders the same full-featured UI for ALL cards,
 * regardless of project. Main IS a project now.
 *
 * Opens via:
 *   a) Event-based: eventBus MODAL_OPEN with {type: 'card-detail', cardId}
 *   b) Direct:      modal.open(card)  — receives a Card object
 */

import { Card, Message, AgentPersona, CardStatus, AgentInfo, TimeEntry, CardComment, ChecklistItem, CardAttachment, CardRelation, CardRelationType, CardHistoryEntry, Project } from '../../types';
import { CodeMirrorEditor } from '../Kanban/CodeMirrorEditor';
import { eventBus } from '../../utils/EventBus';
import { EVENTS, CARD_STATUSES, CARD_STATUS_LABELS, AGENT_PERSONAS, AGENT_TYPE_INFO, API_URL, SYSTEM_PROJECT_ID } from '../../utils/constants';
import { createElement, formatTime } from '../../utils/helpers';
import { appState } from '../../state/AppState';
import { cardService } from '../../services/CardService';
import { chatService } from '../../services/ChatService';
import { apiClient } from '../../services/ApiClient';
import { FocusMode } from '../FocusMode/FocusMode';
import { mainBoardService } from '../../services/MainBoardService';

// ── Tag color helper (mirrors KanbanCard) ────────────────────────────────────
const TAG_COLORS_MODAL: Array<[string, string]> = [
  ['rgba(255, 107, 107, 0.18)', '#ff6b6b'],
  ['rgba(78, 205, 196, 0.18)', '#4ecdc4'],
  ['rgba(255, 183, 77, 0.18)', '#ffb74d'],
  ['rgba(66, 165, 245, 0.18)', '#42a5f5'],
  ['rgba(171, 145, 249, 0.18)', '#ab91f9'],
  ['rgba(102, 187, 106, 0.18)', '#66bb6a'],
  ['rgba(255, 138, 101, 0.18)', '#ff8a65'],
  ['rgba(236, 64, 122, 0.18)', '#ec407a'],
];

function getTagColorModal(tag: string): [string, string] {
  let hash = 0;
  for (let i = 0; i < tag.length; i++) {
    hash = (hash * 31 + tag.charCodeAt(i)) >>> 0;
  }
  return TAG_COLORS_MODAL[hash % TAG_COLORS_MODAL.length];
}

// ── Assignee/Watcher helpers ─────────────────────────────────────────────────
function getInitials(name: string): string {
  return name
    .split(/\s+/)
    .map((w) => w[0] ?? '')
    .join('')
    .toUpperCase()
    .slice(0, 2);
}

const AVATAR_COLORS = [
  '#e53935', '#8e24aa', '#1e88e5', '#00897b',
  '#43a047', '#fb8c00', '#f4511e', '#6d4c41',
];

function nameToColor(name: string): string {
  let hash = 0;
  for (let i = 0; i < name.length; i++) {
    hash = (hash * 31 + name.charCodeAt(i)) >>> 0;
  }
  return AVATAR_COLORS[hash % AVATAR_COLORS.length];
}

// ── Color options (for mainboard cards) ──────────────────────────────────────
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

export class CardDetailModal {
  private overlay: HTMLElement;
  private modal: HTMLElement;
  private card: Card | null = null;
  private sessionId = '';
  private chatMessagesEl: HTMLElement | null = null;
  private unsubscribers: (() => void)[] = [];
  private codeMirrorEditor: CodeMirrorEditor | null = null;
  private themeObserver: MutationObserver | null = null;
  private agents: AgentInfo[] = Object.entries(AGENT_TYPE_INFO).map(([type, info]) => ({
    type,
    name: info.name,
    emoji: info.emoji,
    description: info.description,
    strengths: [],
    keywords: [],
  }));

  private activePickerCleanup: (() => void) | null = null;

  // Callbacks so FreeBoard can react to mutations
  onDeleted?: (cardId: string) => void;
  onUpdated?: (card: Card) => void;


  constructor(private parentElement: HTMLElement) {
    this.overlay = createElement('div', { className: 'modal-overlay hidden' });
    this.modal = createElement('div', { className: 'modal card-detail-modal' });
    this.overlay.appendChild(this.modal);
    this.parentElement.appendChild(this.overlay);
    this.setupListeners();
    // Load agents from API (for richer descriptions)
    cardService.getAgents().then((agents) => {
      if (agents.length > 0) this.agents = agents;
    }).catch((err) => { console.warn('[CardDetailModal] Failed to load agents:', err); });
  }

  private setupListeners(): void {
    this.overlay.addEventListener('click', (e) => {
      if (e.target === this.overlay) this.close();
    });

    // Event-based open (used by App.ts / Kanban)
    this.unsubscribers.push(
      eventBus.on(EVENTS.MODAL_OPEN, (data: unknown) => {
        const { type, cardId } = data as { type: string; cardId: string };
        if (type === 'card-detail') {
          const card = appState.getCard(cardId);
          if (card) this.open(card);
        }
      })
    );

    this.unsubscribers.push(
      eventBus.on(EVENTS.MODAL_CLOSE, () => this.close())
    );

    this.unsubscribers.push(
      eventBus.on(EVENTS.CARD_UPDATED, (data: unknown) => {
        const { id } = data as { id: string };
        if (this.card && this.card.id === id) {
          this.card = appState.getCard(id) || null;
          if (this.card) this.renderContent();
        }
      })
    );

    // Chat events — refresh chat when messages arrive
    const refreshIfRelevant = () => { if (this.card) this.refreshChat(); };
    this.unsubscribers.push(eventBus.on(EVENTS.MESSAGE_RECEIVED, refreshIfRelevant));
    this.unsubscribers.push(eventBus.on(EVENTS.MESSAGE_STREAM_END, refreshIfRelevant));
    this.unsubscribers.push(eventBus.on(EVENTS.MESSAGE_STREAMING, refreshIfRelevant));

    // ESC to close
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape' && !this.overlay.classList.contains('hidden')) {
        this.close();
      }
    };
    document.addEventListener('keydown', onKey);
    this.unsubscribers.push(() => document.removeEventListener('keydown', onKey));
  }

  // ── Public API ────────────────────────────────────────────────────────────

  /** Open modal with a Card object (used by both FreeBoard direct call and event-based) */
  open(card: Card): void {
    this.card = card;
    this.sessionId = `card:${card.id}`;
    this.renderContent();
    this.overlay.classList.remove('hidden');
  }

  close(): void {
    this.destroyCodeMirror();
    this.overlay.classList.add('hidden');
    this.card = null;
    this.chatMessagesEl = null;
    appState.selectCard(null);
  }

  update(): void {
    if (this.card) {
      this.card = appState.getCard(this.card.id) || null;
      if (this.card) this.renderContent();
    }
  }

  // ── CodeMirror lifecycle ──────────────────────────────────────────────────

  private destroyCodeMirror(): void {
    if (this.codeMirrorEditor) {
      this.codeMirrorEditor.destroy();
      this.codeMirrorEditor = null;
    }
    if (this.themeObserver) {
      this.themeObserver.disconnect();
      this.themeObserver = null;
    }
  }

  // ── Save/Delete helpers ───────────────────────────────────────────────────

  private async saveCard(updates: Partial<Card>): Promise<void> {
    if (!this.card) return;
    // All cards (including system project / main board) use the regular cardService
    cardService.update(this.card.id, updates);
    // Apply updates locally so the modal reflects changes
    this.card = { ...this.card, ...updates };
    this.onUpdated?.(this.card);
  }

  private async deleteCard(): Promise<void> {
    if (!this.card) return;
    if (!confirm(`Delete "${this.card.title}"?`)) return;
    const id = this.card.id;
    cardService.delete(id);
    this.onDeleted?.(id);
    this.close();
  }

  // ── Chat helpers ──────────────────────────────────────────────────────────

  private refreshChat(): void {
    if (!this.chatMessagesEl || !this.card) return;

    const messages = appState
      .getMessages(undefined, this.sessionId)
      .filter((m) => m.role === 'user' || m.role === 'assistant')
      .slice(-MAX_CHAT_MESSAGES);

    this.chatMessagesEl.innerHTML = '';

    if (messages.length === 0) {
      const hint = createElement('div', { className: 'card-chat-empty' },
        'Ask Voxy anything about this card\u2026');
      this.chatMessagesEl.appendChild(hint);
      return;
    }

    messages.forEach((msg: Message) => {
      const bubble = createElement('div', {
        className: `card-chat-bubble card-chat-bubble--${msg.role}`,
      });
      bubble.textContent = msg.streaming ? msg.content + '\u258b' : msg.content;
      this.chatMessagesEl!.appendChild(bubble);
    });

    this.chatMessagesEl.scrollTop = this.chatMessagesEl.scrollHeight;
  }

  private sendChatMessage(content: string): void {
    if (!content.trim() || !this.card) return;
    chatService.sendMessage(
      content.trim(),
      this.card.projectId || undefined,
      this.card.id,
      this.sessionId
    );
  }

  // ── Time helpers ──────────────────────────────────────────────────────────

  private formatMinutes(minutes: number): string {
    if (minutes <= 0) return '0m';
    const h = Math.floor(minutes / 60);
    const m = minutes % 60;
    if (h === 0) return `${m}m`;
    if (m === 0) return `${h}h`;
    return `${h}h ${m}m`;
  }

  // ── Section builders (project-card features) ──────────────────────────────

  private buildTimeSection(cardId: string, totalMinutes: number): HTMLElement {
    const section = createElement('div', { className: 'modal-section time-tracking-section' });
    const label = createElement('label', { className: 'modal-label' }, '\u23f1 Time Tracking');

    const totalEl = createElement(
      'div',
      { className: 'time-total' },
      totalMinutes > 0 ? `\u23f1 ${this.formatMinutes(totalMinutes)} total` : '\u23f1 No time logged yet'
    );

    let formVisible = false;
    const logBtn = createElement('button', { className: 'log-time-btn' }, '+ Log Time');

    const form = createElement('div', { className: 'time-log-form hidden' });
    const durationInput = createElement('input', {
      type: 'number',
      className: 'form-input time-duration-input',
      placeholder: 'Minutes',
      min: '1',
      max: '9999',
    }) as HTMLInputElement;
    const noteInput = createElement('input', {
      type: 'text',
      className: 'form-input time-note-input',
      placeholder: 'Note (optional)',
    }) as HTMLInputElement;
    const submitBtn = createElement('button', { className: 'time-submit-btn' }, 'Log');
    const cancelBtn = createElement('button', { className: 'time-cancel-btn' }, 'Cancel');

    const submitLog = async () => {
      const mins = parseInt(durationInput.value, 10);
      if (!mins || mins < 1) {
        durationInput.classList.add('error');
        return;
      }
      durationInput.classList.remove('error');
      submitBtn.textContent = '\u2026';
      (submitBtn as HTMLButtonElement).disabled = true;

      const note = noteInput.value.trim() || undefined;
      const entry = await apiClient.logTime(cardId, mins, note);
      if (entry) {
        const updatedTotal = totalMinutes + mins;
        const newSection = this.buildTimeSection(cardId, updatedTotal);
        section.replaceWith(newSection);
        const card = appState.getCard(cardId);
        if (card) appState.updateCard(cardId, { totalMinutes: updatedTotal });
      } else {
        submitBtn.textContent = 'Log';
        (submitBtn as HTMLButtonElement).disabled = false;
      }
    };

    logBtn.addEventListener('click', () => {
      formVisible = !formVisible;
      form.classList.toggle('hidden', !formVisible);
      logBtn.textContent = formVisible ? '\u2212 Cancel' : '+ Log Time';
      if (formVisible) durationInput.focus();
    });

    cancelBtn.addEventListener('click', () => {
      formVisible = false;
      form.classList.add('hidden');
      logBtn.textContent = '+ Log Time';
    });

    submitBtn.addEventListener('click', submitLog);
    durationInput.addEventListener('keydown', (e) => {
      if (e.key === 'Enter') submitLog();
      if (e.key === 'Escape') cancelBtn.click();
    });

    form.appendChild(durationInput);
    form.appendChild(noteInput);
    form.appendChild(submitBtn);
    form.appendChild(cancelBtn);

    const listEl = createElement('div', { className: 'time-entry-list' });
    listEl.textContent = 'Loading\u2026';

    apiClient.fetchTimeEntries(cardId).then((entries) => {
      listEl.innerHTML = '';
      if (entries.length === 0) {
        listEl.appendChild(createElement('div', { className: 'empty-text' }, 'No entries yet.'));
        return;
      }
      const fetchedTotal = entries.reduce((sum, e) => sum + e.durationMinutes, 0);
      if (fetchedTotal !== totalMinutes) {
        totalEl.textContent = fetchedTotal > 0 ? `\u23f1 ${this.formatMinutes(fetchedTotal)} total` : '\u23f1 No time logged yet';
        totalMinutes = fetchedTotal;
      }
      entries.forEach((entry) => {
        const item = createElement('div', { className: 'time-entry-item' });
        const dateStr = new Date(entry.loggedAt).toLocaleDateString(undefined, {
          month: 'short', day: 'numeric',
        });
        const dur = createElement('span', { className: 'time-entry-duration' }, this.formatMinutes(entry.durationMinutes));
        const date = createElement('span', { className: 'time-entry-date' }, dateStr);
        const noteEl = entry.note
          ? createElement('span', { className: 'time-entry-note' }, entry.note)
          : null;
        const delBtn = createElement('button', { className: 'time-entry-delete', title: 'Delete entry' }, '\u00d7');
        delBtn.addEventListener('click', async () => {
          const ok = await apiClient.deleteTimeEntry(cardId, entry.id);
          if (ok) {
            item.remove();
            const newTotal = Math.max(0, totalMinutes - entry.durationMinutes);
            totalEl.textContent = newTotal > 0 ? `\u23f1 ${this.formatMinutes(newTotal)} total` : '\u23f1 No time logged yet';
            const card = appState.getCard(cardId);
            if (card) appState.updateCard(cardId, { totalMinutes: newTotal });
          }
        });

        item.appendChild(dur);
        item.appendChild(date);
        if (noteEl) item.appendChild(noteEl);
        item.appendChild(delBtn);
        listEl.appendChild(item);
      });
    });

    section.appendChild(label);
    section.appendChild(totalEl);
    section.appendChild(logBtn);
    section.appendChild(form);
    section.appendChild(listEl);
    return section;
  }

  private buildCommentsSection(cardId: string): HTMLElement {
    const section = createElement('div', { className: 'modal-section comments-section' });
    const headerEl = createElement('label', { className: 'modal-label comments-header' }, '\ud83d\udcac Comments');
    const listEl = createElement('div', { className: 'comments-list' });
    listEl.textContent = 'Loading\u2026';

    let localComments: CardComment[] = [];

    const updateHeader = () => {
      headerEl.textContent = `\ud83d\udcac Comments (${localComments.length})`;
    };

    const renderComment = (comment: CardComment): HTMLElement => {
      const item = createElement('div', { className: 'comment-item' });
      const initials = comment.author
        .split(' ')
        .map((w) => w[0] ?? '')
        .join('')
        .toUpperCase()
        .slice(0, 2);
      const avatar = createElement('div', { className: 'comment-avatar', title: comment.author }, initials);
      const body = createElement('div', { className: 'comment-content' });
      const meta = createElement('div', { className: 'comment-meta' });
      const dateStr = new Date(comment.createdAt).toLocaleDateString(undefined, {
        month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit',
      });
      meta.textContent = `${comment.author} \u00b7 ${dateStr}`;
      const text = createElement('div', { className: 'comment-text' }, comment.content);
      const delBtn = createElement('button', { className: 'comment-delete', title: 'Delete comment' }, '\u00d7');
      delBtn.addEventListener('click', async () => {
        const ok = await apiClient.deleteComment(cardId, comment.id);
        if (ok) {
          item.remove();
          localComments = localComments.filter((c) => c.id !== comment.id);
          updateHeader();
        }
      });
      body.appendChild(meta);
      body.appendChild(text);
      item.appendChild(avatar);
      item.appendChild(body);
      item.appendChild(delBtn);
      return item;
    };

    apiClient.fetchComments(cardId).then((comments) => {
      localComments = [...comments];
      listEl.innerHTML = '';
      updateHeader();
      if (comments.length === 0) {
        listEl.appendChild(createElement('div', { className: 'empty-text' }, 'No comments yet.'));
        return;
      }
      comments.forEach((c) => listEl.appendChild(renderComment(c)));
    });

    const inputRow = createElement('div', { className: 'comment-input-row' });
    const textarea = createElement('textarea', {
      className: 'comment-textarea',
      placeholder: 'Add a comment\u2026',
      rows: '2',
    }) as HTMLTextAreaElement;
    const submitBtn = createElement('button', { className: 'comment-submit-btn' }, 'Post') as HTMLButtonElement;
    submitBtn.type = 'button';

    const submitComment = async () => {
      const content = textarea.value.trim();
      if (!content) return;
      const optimisticComment: CardComment = {
        id: `optimistic-${Date.now()}`,
        cardId,
        author: 'User',
        content,
        createdAt: Date.now(),
      };
      const emptyEl = listEl.querySelector('.empty-text');
      if (emptyEl) emptyEl.remove();
      const optimisticEl = renderComment(optimisticComment);
      optimisticEl.classList.add('comment-optimistic');
      listEl.insertBefore(optimisticEl, listEl.firstChild);
      localComments.unshift(optimisticComment);
      updateHeader();
      textarea.value = '';
      submitBtn.disabled = true;
      const saved = await apiClient.addComment(cardId, content);
      if (saved) {
        optimisticEl.remove();
        localComments = localComments.filter((c) => c.id !== optimisticComment.id);
        const confirmedEl = renderComment(saved);
        listEl.insertBefore(confirmedEl, listEl.firstChild);
        localComments.unshift(saved);
        updateHeader();
      } else {
        optimisticEl.remove();
        localComments = localComments.filter((c) => c.id !== optimisticComment.id);
        updateHeader();
      }
      submitBtn.disabled = false;
    };

    submitBtn.addEventListener('click', submitComment);
    textarea.addEventListener('keydown', (e: KeyboardEvent) => {
      if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) {
        e.preventDefault();
        submitComment();
      }
    });

    inputRow.appendChild(textarea);
    inputRow.appendChild(submitBtn);

    section.appendChild(headerEl);
    section.appendChild(listEl);
    section.appendChild(inputRow);
    return section;
  }

  private buildChecklistSection(cardId: string): HTMLElement {
    const section = createElement('div', { className: 'modal-section checklist-section' });
    const headerEl = createElement('label', { className: 'modal-label checklist-header' }, '\u2611\ufe0f Checklist');

    const progressContainer = createElement('div', { className: 'checklist-progress-bar-container' });
    const progressTrack = createElement('div', { className: 'checklist-progress-track' });
    const progressBar = createElement('div', { className: 'checklist-progress-bar' });
    const progressLabel = createElement('span', { className: 'checklist-progress-label' }, '');
    progressTrack.appendChild(progressBar);
    progressContainer.appendChild(progressTrack);
    progressContainer.appendChild(progressLabel);

    const listEl = createElement('div', { className: 'checklist-list' });
    listEl.textContent = 'Loading\u2026';

    let localItems: ChecklistItem[] = [];

    const updateProgress = () => {
      const total = localItems.length;
      const done = localItems.filter((i) => i.completed).length;
      if (total === 0) {
        progressContainer.style.display = 'none';
        progressLabel.textContent = '';
      } else {
        progressContainer.style.display = '';
        const pct = Math.round((done / total) * 100);
        (progressBar as HTMLElement).style.width = `${pct}%`;
        progressLabel.textContent = `${done}/${total}`;
      }
    };

    const renderItem = (item: ChecklistItem): HTMLElement => {
      const row = createElement('div', { className: `checklist-item${item.completed ? ' completed' : ''}`, 'data-item-id': item.id });
      const checkbox = createElement('input', {
        type: 'checkbox',
        className: 'checklist-checkbox',
      }) as HTMLInputElement;
      checkbox.checked = item.completed;

      checkbox.addEventListener('change', async () => {
        const newCompleted = checkbox.checked;
        row.classList.toggle('completed', newCompleted);
        item.completed = newCompleted;
        updateProgress();
        await apiClient.updateChecklistItem(cardId, item.id, { completed: newCompleted });
      });

      const textEl = createElement('span', { className: 'checklist-item-text' }, item.text);
      textEl.contentEditable = 'true';
      textEl.spellcheck = false;

      textEl.addEventListener('keydown', (e: KeyboardEvent) => {
        if (e.key === 'Enter') { e.preventDefault(); (textEl as HTMLElement).blur(); }
        if (e.key === 'Escape') { textEl.textContent = item.text; (textEl as HTMLElement).blur(); }
      });

      textEl.addEventListener('blur', async () => {
        const newText = (textEl.textContent || '').trim();
        if (newText && newText !== item.text) {
          item.text = newText;
          await apiClient.updateChecklistItem(cardId, item.id, { text: newText });
        } else {
          textEl.textContent = item.text;
        }
      });

      const delBtn = createElement('button', { className: 'checklist-item-delete', title: 'Remove item' }, '\u00d7');
      delBtn.addEventListener('click', async () => {
        const ok = await apiClient.deleteChecklistItem(cardId, item.id);
        if (ok) {
          row.remove();
          localItems = localItems.filter((i) => i.id !== item.id);
          updateProgress();
          if (localItems.length === 0) {
            listEl.appendChild(createElement('div', { className: 'empty-text' }, 'No items yet.'));
          }
        }
      });

      row.appendChild(checkbox);
      row.appendChild(textEl);
      row.appendChild(delBtn);
      return row;
    };

    apiClient.fetchChecklistItems(cardId).then((items) => {
      localItems = [...items];
      listEl.innerHTML = '';
      updateProgress();
      if (items.length === 0) {
        listEl.appendChild(createElement('div', { className: 'empty-text' }, 'No items yet.'));
      } else {
        items.forEach((item) => listEl.appendChild(renderItem(item)));
      }
    });

    const addRow = createElement('div', { className: 'checklist-add-row' });
    const addInput = createElement('input', {
      type: 'text',
      className: 'form-input checklist-add-input',
      placeholder: 'Add item\u2026 (Enter to add)',
    }) as HTMLInputElement;

    const submitAdd = async () => {
      const text = addInput.value.trim();
      if (!text) return;
      addInput.value = '';
      const saved = await apiClient.addChecklistItem(cardId, text);
      if (saved) {
        const emptyEl = listEl.querySelector('.empty-text');
        if (emptyEl) emptyEl.remove();
        localItems.push(saved);
        listEl.appendChild(renderItem(saved));
        updateProgress();
      }
    };

    addInput.addEventListener('keydown', (e: KeyboardEvent) => {
      if (e.key === 'Enter') { e.preventDefault(); submitAdd(); }
    });

    addRow.appendChild(addInput);
    section.appendChild(headerEl);
    section.appendChild(progressContainer);
    section.appendChild(listEl);
    section.appendChild(addRow);
    return section;
  }

  private getAttachmentIcon(mimeType: string): string {
    if (mimeType.startsWith('image/')) return '\ud83d\uddbc\ufe0f';
    if (mimeType.includes('pdf')) return '\ud83d\udcc4';
    if (mimeType.includes('spreadsheet') || mimeType.includes('excel') || mimeType.includes('csv')) return '\ud83d\udcca';
    if (mimeType.includes('word') || mimeType.includes('document')) return '\ud83d\udcdd';
    if (mimeType.includes('zip') || mimeType.includes('archive') || mimeType.includes('tar') || mimeType.includes('gzip')) return '\ud83d\udddc\ufe0f';
    if (mimeType.startsWith('video/')) return '\ud83c\udfac';
    if (mimeType.startsWith('audio/')) return '\ud83c\udfb5';
    return '\ud83d\udcc4';
  }

  private formatFileSize(bytes: number): string {
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  }

  private buildFilesSection(): HTMLElement {
    const section = createElement('div', { className: 'modal-section files-section' });
    const headerEl = createElement('label', { className: 'modal-label' }, '\uD83D\uDCC1 Files');
    const listEl = createElement('div', { className: 'file-ref-list' });

    const files = this.card?.files ?? [];

    if (files.length === 0) {
      listEl.innerHTML = '<span style="opacity:0.5;font-size:12px;">No linked files</span>';
    } else {
      for (const filePath of files) {
        const item = createElement('div', { className: 'file-ref-item' });
        item.style.cssText = 'display:flex;align-items:center;gap:6px;padding:3px 0;font-size:13px;';

        const nameSpan = createElement('span', { title: filePath });
        nameSpan.textContent = filePath.split('/').pop() || filePath;
        nameSpan.style.cssText = 'flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;cursor:default;';

        const removeBtn = createElement('button', {
          className: 'file-ref-remove-btn',
          title: 'Unlink file',
          type: 'button',
        }, '\u2715') as HTMLButtonElement;
        removeBtn.style.cssText = 'background:none;border:none;color:var(--text-secondary);cursor:pointer;font-size:11px;padding:2px 4px;opacity:0.6;';
        removeBtn.addEventListener('click', async () => {
          if (!this.card) return;
          try {
            const baseUrl = API_URL || '';
            const resp = await fetch(`${baseUrl}/api/cards/${this.card.id}/files?path=${encodeURIComponent(filePath)}`, { method: 'DELETE' });
            if (resp.ok) {
              const updated = await resp.json() as string[];
              this.card.files = updated;
              this.refreshFilesSection(section);
            }
          } catch (e) { console.error('Failed to unlink file:', e); }
        });

        item.appendChild(nameSpan);
        item.appendChild(removeBtn);
        listEl.appendChild(item);
      }
    }

    // "Link file" button
    const linkBtn = createElement('button', {
      className: 'modal-btn-secondary',
      type: 'button',
    }, '+ Link file') as HTMLButtonElement;
    linkBtn.style.cssText = 'margin-top:6px;font-size:12px;padding:4px 10px;';
    linkBtn.addEventListener('click', () => this.showFilePicker(section));

    section.appendChild(headerEl);
    section.appendChild(listEl);
    section.appendChild(linkBtn);
    return section;
  }

  private async showFilePicker(filesSection: HTMLElement): Promise<void> {
    if (!this.card) return;
    try {
      const baseUrl = API_URL || '';
      const resp = await fetch(`${baseUrl}/api/workspace/files`);
      if (!resp.ok) return;
      const entries = await resp.json() as Array<{ name: string; path: string; is_dir: boolean }>;

      // Create a simple dropdown picker
      const existing = filesSection.querySelector('.file-picker-dropdown');
      if (existing) { existing.remove(); return; }

      const dropdown = createElement('div', { className: 'file-picker-dropdown' });
      dropdown.style.cssText = 'border:1px solid var(--border-color);border-radius:6px;max-height:160px;overflow-y:auto;margin-top:4px;background:var(--bg-secondary);';

      if (entries.length === 0) {
        dropdown.innerHTML = '<div style="padding:8px;font-size:12px;opacity:0.5;">Workspace is empty</div>';
      } else {
        for (const entry of entries) {
          if (entry.is_dir) continue; // only files for now
          const currentFiles = this.card.files ?? [];
          if (currentFiles.includes(entry.path)) continue; // already linked
          const opt = createElement('div', { className: 'file-picker-option' });
          opt.style.cssText = 'padding:6px 10px;cursor:pointer;font-size:12px;';
          opt.textContent = entry.name;
          opt.title = entry.path;
          opt.addEventListener('mouseenter', () => { opt.style.background = 'var(--bg-hover)'; });
          opt.addEventListener('mouseleave', () => { opt.style.background = ''; });
          opt.addEventListener('click', async () => {
            if (!this.card) return;
            try {
              const addResp = await fetch(`${baseUrl}/api/cards/${this.card.id}/files`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ path: entry.path }),
              });
              if (addResp.ok) {
                const updated = await addResp.json() as string[];
                this.card.files = updated;
                this.refreshFilesSection(filesSection);
              }
            } catch (e) { console.error('Failed to link file:', e); }
            dropdown.remove();
          });
          dropdown.appendChild(opt);
        }
        if (dropdown.children.length === 0) {
          dropdown.innerHTML = '<div style="padding:8px;font-size:12px;opacity:0.5;">All workspace files already linked</div>';
        }
      }

      filesSection.appendChild(dropdown);
      // Close on outside click
      const closeHandler = (ev: Event) => {
        if (!dropdown.contains(ev.target as Node) && !filesSection.contains(ev.target as Node)) {
          dropdown.remove();
          document.removeEventListener('click', closeHandler);
        }
      };
      setTimeout(() => document.addEventListener('click', closeHandler), 10);
    } catch (e) {
      console.error('Failed to load workspace files:', e);
    }
  }

  private refreshFilesSection(section: HTMLElement): void {
    // Re-build the files section content in-place
    const newSection = this.buildFilesSection();
    section.innerHTML = newSection.innerHTML;
    // Re-attach event listeners by replacing the section
    section.replaceWith(newSection);
  }

  private buildAttachmentsSection(cardId: string): HTMLElement {
    const section = createElement('div', { className: 'modal-section attachments-section' });
    const headerEl = createElement('label', { className: 'modal-label attachments-header' }, '\ud83d\udcce Attachments');
    const listEl = createElement('div', { className: 'attachment-list' });
    listEl.textContent = 'Loading\u2026';

    let localAttachments: CardAttachment[] = [];

    const updateHeader = () => {
      headerEl.textContent = `\ud83d\udcce Attachments (${localAttachments.length})`;
    };

    const renderAttachment = (att: CardAttachment): HTMLElement => {
      const item = createElement('div', { className: 'attachment-item' });
      const icon = createElement('span', { className: 'attachment-icon' }, this.getAttachmentIcon(att.mimeType));
      const info = createElement('div', { className: 'attachment-info' });
      const nameEl = createElement('span', { className: 'attachment-name' }, att.filename);
      const sizeEl = createElement('span', { className: 'attachment-size' }, this.formatFileSize(att.fileSize));
      info.appendChild(nameEl);
      info.appendChild(sizeEl);

      if (att.mimeType.startsWith('image/')) {
        const preview = createElement('img', {
          className: 'attachment-preview',
          src: apiClient.getAttachmentDownloadUrl(cardId, att.id),
          alt: att.filename,
          title: att.filename,
        }) as HTMLImageElement;
        preview.onerror = () => { preview.style.display = 'none'; };
        item.appendChild(preview);
      }

      const downloadBtn = createElement('a', {
        className: 'attachment-download-btn',
        href: apiClient.getAttachmentDownloadUrl(cardId, att.id),
        download: att.filename,
        title: `Download ${att.filename}`,
      }, '\u2b07\ufe0f') as HTMLAnchorElement;

      const delBtn = createElement('button', {
        className: 'attachment-delete-btn',
        title: `Delete ${att.filename}`,
      }, '\u00d7') as HTMLButtonElement;

      delBtn.addEventListener('click', async () => {
        if (!confirm(`Delete "${att.filename}"?`)) return;
        const ok = await apiClient.deleteAttachment(cardId, att.id);
        if (ok) {
          item.remove();
          localAttachments = localAttachments.filter((a) => a.id !== att.id);
          updateHeader();
          if (localAttachments.length === 0) {
            listEl.appendChild(createElement('div', { className: 'empty-text' }, 'No attachments yet.'));
          }
        }
      });

      item.appendChild(icon);
      item.appendChild(info);
      item.appendChild(downloadBtn);
      item.appendChild(delBtn);
      return item;
    };

    apiClient.fetchAttachments(cardId).then((attachments) => {
      localAttachments = [...attachments];
      listEl.innerHTML = '';
      updateHeader();
      if (attachments.length === 0) {
        listEl.appendChild(createElement('div', { className: 'empty-text' }, 'No attachments yet.'));
      } else {
        attachments.forEach((a) => listEl.appendChild(renderAttachment(a)));
      }
    });

    const dropZone = createElement('div', { className: 'attachment-drop-zone' });
    dropZone.innerHTML = '<span>\ud83d\udcce Drop files here or <strong>click to upload</strong></span>';

    const fileInput = createElement('input', {
      type: 'file',
      className: 'attachment-file-input',
      multiple: 'true',
    }) as HTMLInputElement;
    fileInput.style.display = 'none';

    const uploadFiles = async (files: FileList | File[]) => {
      const fileArray = Array.from(files);
      for (const file of fileArray) {
        const placeholder = createElement('div', { className: 'attachment-item attachment-uploading' });
        placeholder.textContent = `\u2b06\ufe0f Uploading ${file.name}\u2026`;
        const emptyEl = listEl.querySelector('.empty-text');
        if (emptyEl) emptyEl.remove();
        listEl.insertBefore(placeholder, listEl.firstChild);

        const saved = await apiClient.uploadAttachment(cardId, file);
        placeholder.remove();

        if (saved) {
          localAttachments.unshift(saved);
          const el = renderAttachment(saved);
          listEl.insertBefore(el, listEl.firstChild);
          updateHeader();
        } else {
          const errEl = createElement('div', { className: 'attachment-item attachment-error' });
          errEl.textContent = `\u274c Failed to upload ${file.name}`;
          listEl.insertBefore(errEl, listEl.firstChild);
          setTimeout(() => errEl.remove(), 4000);
        }
      }
    };

    dropZone.addEventListener('click', () => fileInput.click());
    fileInput.addEventListener('change', () => {
      if (fileInput.files && fileInput.files.length > 0) {
        uploadFiles(fileInput.files);
        fileInput.value = '';
      }
    });

    dropZone.addEventListener('dragover', (e) => {
      e.preventDefault();
      dropZone.classList.add('dragover');
    });
    dropZone.addEventListener('dragleave', () => {
      dropZone.classList.remove('dragover');
    });
    dropZone.addEventListener('drop', (e) => {
      e.preventDefault();
      dropZone.classList.remove('dragover');
      if (e.dataTransfer?.files && e.dataTransfer.files.length > 0) {
        uploadFiles(e.dataTransfer.files);
      }
    });

    dropZone.appendChild(fileInput);

    section.appendChild(headerEl);
    section.appendChild(dropZone);
    section.appendChild(listEl);
    return section;
  }

  private buildAssigneeWatchersSection(card: Card): HTMLElement {
    const section = createElement('div', { className: 'modal-section assignee-section' });
    const sectionLabel = createElement('label', { className: 'modal-label' }, '\ud83d\udc64 People');

    // ── Assignee ──────────────────────────────────────────────────────────────
    const assigneeRow = createElement('div', { className: 'assignee-row' });
    const assigneeLabel = createElement('span', { className: 'assignee-field-label' }, '\ud83d\udc64 Assigned to:');

    let currentAssignee = card.assignee ?? null;
    const assigneeInputArea = createElement('div', { className: 'assignee-input-area' });

    const renderAssigneeChip = () => {
      assigneeInputArea.innerHTML = '';
      if (currentAssignee) {
        const chip = createElement('span', { className: 'assignee-chip' });
        const circle = createElement('span', { className: 'assignee-chip-avatar' }, getInitials(currentAssignee));
        circle.style.background = nameToColor(currentAssignee);
        const nameEl = createElement('span', { className: 'assignee-chip-name' }, currentAssignee);
        const clearBtn = createElement('button', { className: 'assignee-chip-clear', title: 'Clear assignee' }, '\u00d7');
        clearBtn.addEventListener('click', () => {
          currentAssignee = null;
          if (this.card) {
            cardService.update(this.card.id, { assignee: null } as Partial<Card>);
            apiClient.patchCard(this.card.id, { assignee: null });
          }
          renderAssigneeChip();
        });
        chip.appendChild(circle);
        chip.appendChild(nameEl);
        chip.appendChild(clearBtn);
        assigneeInputArea.appendChild(chip);
      } else {
        const input = createElement('input', {
          type: 'text',
          className: 'form-input assignee-input',
          placeholder: 'Type name and press Enter\u2026',
        }) as HTMLInputElement;
        const saveAssignee = (name: string) => {
          currentAssignee = name;
          if (this.card) {
            cardService.update(this.card.id, { assignee: name } as Partial<Card>);
            apiClient.patchCard(this.card.id, { assignee: name });
          }
          renderAssigneeChip();
        };
        input.addEventListener('keydown', (e: KeyboardEvent) => {
          if (e.key === 'Enter') {
            const name = input.value.trim();
            if (name) saveAssignee(name);
          } else if (e.key === 'Escape') {
            input.value = '';
          }
        });
        input.addEventListener('blur', () => {
          const name = input.value.trim();
          if (name) saveAssignee(name);
        });
        assigneeInputArea.appendChild(input);
        setTimeout(() => input.focus(), 50);
      }
    };

    renderAssigneeChip();
    assigneeRow.appendChild(assigneeLabel);
    assigneeRow.appendChild(assigneeInputArea);

    // ── Watchers ──────────────────────────────────────────────────────────────
    const watchersRow = createElement('div', { className: 'watchers-row' });
    const watchersLabel = createElement('span', { className: 'assignee-field-label' }, '\ud83d\udc41 Watchers:');

    let watcherList: string[] = (card.watchers || '').split(',').map((w) => w.trim()).filter(Boolean);
    const watcherChipsContainer = createElement('div', { className: 'watcher-chips-container' });

    const renderWatcherChips = () => {
      watcherChipsContainer.innerHTML = '';
      watcherList.forEach((watcher) => {
        const chip = createElement('span', { className: 'watcher-chip' });
        const nameEl = createElement('span', {}, watcher);
        const removeBtn = createElement('button', { className: 'watcher-chip-remove', title: `Remove ${watcher}` }, '\u00d7');
        removeBtn.addEventListener('click', () => {
          watcherList = watcherList.filter((w) => w !== watcher);
          if (this.card) {
            cardService.update(this.card.id, { watchers: watcherList.join(',') } as Partial<Card>);
            apiClient.patchCard(this.card.id, { watchers: watcherList.join(',') });
          }
          renderWatcherChips();
        });
        chip.appendChild(nameEl);
        chip.appendChild(removeBtn);
        watcherChipsContainer.appendChild(chip);
      });

      const addInput = createElement('input', {
        type: 'text',
        className: 'form-input watcher-input',
        placeholder: 'Add watcher\u2026',
      }) as HTMLInputElement;

      const commitWatcher = () => {
        const names = addInput.value.split(',').map((n) => n.trim()).filter(Boolean);
        const newNames = names.filter((n) => !watcherList.includes(n));
        if (newNames.length > 0) {
          watcherList = [...watcherList, ...newNames];
          if (this.card) {
            cardService.update(this.card.id, { watchers: watcherList.join(',') } as Partial<Card>);
            apiClient.patchCard(this.card.id, { watchers: watcherList.join(',') });
          }
          renderWatcherChips();
        } else {
          addInput.value = '';
        }
      };

      addInput.addEventListener('keydown', (e: KeyboardEvent) => {
        if (e.key === 'Enter') { e.preventDefault(); commitWatcher(); }
        else if (e.key === 'Escape') { addInput.value = ''; }
      });
      addInput.addEventListener('blur', () => {
        if (addInput.value.trim()) commitWatcher();
      });

      watcherChipsContainer.appendChild(addInput);
    };

    renderWatcherChips();
    watchersRow.appendChild(watchersLabel);
    watchersRow.appendChild(watcherChipsContainer);

    section.appendChild(sectionLabel);
    section.appendChild(assigneeRow);
    section.appendChild(watchersRow);
    return section;
  }

  private buildVoteSection(card: Card): HTMLElement {
    const section = createElement('div', { className: 'modal-section vote-section' });
    const label = createElement('label', { className: 'modal-label' }, '\u25b2 Priority Votes');

    const voteCount = card.votes ?? 0;
    const voted = localStorage.getItem(`voxy_voted_${card.id}`) === 'true';

    const countEl = createElement('span', { className: 'vote-count-display' }, `\u25b2 ${voteCount} vote${voteCount !== 1 ? 's' : ''}`);

    const voteBtn = createElement('button', {
      className: 'vote-btn vote-btn-modal' + (voted ? ' voted' : ''),
    }, voted ? 'Un-vote' : 'Vote \u25b2') as HTMLButtonElement;

    voteBtn.addEventListener('click', async () => {
      const currentlyVoted = localStorage.getItem(`voxy_voted_${card.id}`) === 'true';
      voteBtn.disabled = true;
      const newCount = currentlyVoted
        ? await apiClient.unvoteCard(card.id)
        : await apiClient.voteCard(card.id);
      if (newCount !== null) {
        const nowVoted = !currentlyVoted;
        if (nowVoted) {
          localStorage.setItem(`voxy_voted_${card.id}`, 'true');
        } else {
          localStorage.removeItem(`voxy_voted_${card.id}`);
        }
        countEl.textContent = `\u25b2 ${newCount} vote${newCount !== 1 ? 's' : ''}`;
        voteBtn.textContent = nowVoted ? 'Un-vote' : 'Vote \u25b2';
        voteBtn.className = 'vote-btn vote-btn-modal' + (nowVoted ? ' voted' : '');
        appState.updateCard(card.id, { votes: newCount });
        if (this.card) this.card = { ...this.card, votes: newCount };
      }
      voteBtn.disabled = false;
    });

    const row = createElement('div', { className: 'vote-row' });
    row.appendChild(countEl);
    row.appendChild(voteBtn);

    section.appendChild(label);
    section.appendChild(row);
    return section;
  }

  // ── Relations helpers ─────────────────────────────────────────────────────

  private getRelationIcon(type: CardRelationType | string): string {
    const icons: Record<string, string> = {
      duplicates: '\ud83d\udd01',
      duplicated_by: '\ud83d\udd01',
      blocks: '\u26d4',
      is_blocked_by: '\ud83d\udd12',
      relates_to: '\ud83d\udd17',
      cloned_from: '\ud83e\uddec',
      cloned_to: '\ud83e\uddec',
    };
    return icons[type] ?? '\ud83d\udd17';
  }

  private getRelationLabel(type: CardRelationType | string): string {
    const labels: Record<string, string> = {
      duplicates: 'Duplicates',
      duplicated_by: 'Duplicated by',
      blocks: 'Blocks',
      is_blocked_by: 'Blocked by',
      relates_to: 'Relates to',
      cloned_from: 'Cloned from',
      cloned_to: 'Cloned to',
    };
    return labels[type] ?? type;
  }

  private getRelationBadgeClass(type: CardRelationType | string): string {
    const classes: Record<string, string> = {
      duplicates: 'relation-type-badge--duplicates',
      duplicated_by: 'relation-type-badge--duplicates',
      blocks: 'relation-type-badge--blocks',
      is_blocked_by: 'relation-type-badge--blocked',
      relates_to: 'relation-type-badge--relates',
      cloned_from: 'relation-type-badge--cloned',
      cloned_to: 'relation-type-badge--cloned',
    };
    return classes[type] ?? '';
  }

  private buildRelationsSection(card: Card): HTMLElement {
    const section = createElement('div', { className: 'modal-section relations-section' });
    const headerEl = createElement('label', { className: 'modal-label relations-header' }, '\ud83d\udd17 Related Cards');

    const listEl = createElement('div', { className: 'relations-list' });
    listEl.textContent = 'Loading\u2026';

    let localRelations: CardRelation[] = [];

    const updateHeader = () => {
      headerEl.textContent = `\ud83d\udd17 Related Cards (${localRelations.length})`;
    };

    const renderRelationItem = (rel: CardRelation): HTMLElement => {
      const item = createElement('div', { className: 'relation-item' });
      const icon = createElement('span', { className: 'relation-icon' }, this.getRelationIcon(rel.relationType));
      const badge = createElement('span', {
        className: `relation-type-badge ${this.getRelationBadgeClass(rel.relationType)}`,
      }, this.getRelationLabel(rel.relationType));
      const titleEl = createElement('span', { className: 'relation-card-title' }, rel.relatedCardTitle);
      const statusDot = createElement('span', {
        className: `relation-status-dot relation-status-dot--${rel.relatedCardStatus}`,
        title: rel.relatedCardStatus,
      });
      const delBtn = createElement('button', { className: 'relation-delete-btn', title: 'Remove relation' }, '\u00d7') as HTMLButtonElement;
      delBtn.addEventListener('click', async () => {
        const ok = await apiClient.deleteRelation(card.id, rel.id);
        if (ok) {
          item.remove();
          localRelations = localRelations.filter((r) => r.id !== rel.id);
          updateHeader();
          if (localRelations.length === 0) {
            listEl.appendChild(createElement('div', { className: 'empty-text' }, 'No relations yet.'));
          }
        }
      });
      item.appendChild(icon);
      item.appendChild(badge);
      item.appendChild(statusDot);
      item.appendChild(titleEl);
      item.appendChild(delBtn);
      return item;
    };

    apiClient.fetchRelations(card.id).then((relations) => {
      localRelations = [...relations];
      listEl.innerHTML = '';
      updateHeader();
      if (relations.length === 0) {
        listEl.appendChild(createElement('div', { className: 'empty-text' }, 'No relations yet.'));
      } else {
        relations.forEach((r) => listEl.appendChild(renderRelationItem(r)));
      }
    });

    const addRow = createElement('div', { className: 'relation-add-row' });

    const RELATION_TYPES: CardRelationType[] = ['relates_to', 'blocks', 'is_blocked_by', 'duplicates', 'cloned_from'];

    const cardSelect = createElement('select', { className: 'relation-card-select' }) as HTMLSelectElement;
    const cardPlaceholder = document.createElement('option');
    cardPlaceholder.value = '';
    cardPlaceholder.textContent = 'Select card\u2026';
    cardPlaceholder.disabled = true;
    cardPlaceholder.selected = true;
    cardSelect.appendChild(cardPlaceholder);

    const projectCards = card.projectId ? appState.getCardsByProject(card.projectId).filter((c) => c.id !== card.id) : [];
    projectCards.forEach((c) => {
      const opt = document.createElement('option');
      opt.value = c.id;
      opt.textContent = `${c.status === 'done' ? '\u2705' : '\u23f3'} ${c.title}`;
      cardSelect.appendChild(opt);
    });

    const typeSelect = createElement('select', { className: 'relation-type-select' }) as HTMLSelectElement;
    RELATION_TYPES.forEach((t) => {
      const opt = document.createElement('option');
      opt.value = t;
      opt.textContent = `${this.getRelationIcon(t)} ${this.getRelationLabel(t)}`;
      typeSelect.appendChild(opt);
    });

    const addBtn = createElement('button', { className: 'relation-add-btn' }, '+ Add') as HTMLButtonElement;
    addBtn.type = 'button';
    addBtn.addEventListener('click', async () => {
      const targetId = cardSelect.value;
      const relType = typeSelect.value as CardRelationType;
      if (!targetId) return;

      addBtn.disabled = true;
      addBtn.textContent = '\u2026';

      const saved = await apiClient.addRelation(card.id, targetId, relType);
      if (saved) {
        const emptyEl = listEl.querySelector('.empty-text');
        if (emptyEl) emptyEl.remove();
        localRelations.push(saved);
        listEl.appendChild(renderRelationItem(saved));
        updateHeader();
        cardSelect.value = '';
      } else {
        eventBus.emit(EVENTS.TOAST_SHOW, { message: '\u274c Could not add relation', type: 'error', duration: 3000 });
      }

      addBtn.disabled = false;
      addBtn.textContent = '+ Add';
    });

    if (projectCards.length > 0) {
      addRow.appendChild(cardSelect);
      addRow.appendChild(typeSelect);
      addRow.appendChild(addBtn);
    } else {
      addRow.appendChild(createElement('span', { className: 'empty-text' }, 'No other cards in this project'));
    }

    section.appendChild(headerEl);
    section.appendChild(listEl);
    section.appendChild(addRow);
    return section;
  }

  private buildHistorySection(cardId: string): HTMLElement {
    const section = createElement('div', { className: 'modal-section history-section' });

    const headerEl = createElement('div', { className: 'history-section-header' });
    const titleEl = createElement('label', { className: 'modal-label history-label' }, '\ud83d\udcdc History');
    const toggleEl = createElement('span', { className: 'history-toggle' }, '\u25b6');
    headerEl.appendChild(titleEl);
    headerEl.appendChild(toggleEl);

    const body = createElement('div', { className: 'history-section-body hidden' });
    let expanded = false;

    headerEl.style.cursor = 'pointer';
    headerEl.addEventListener('click', () => {
      expanded = !expanded;
      body.classList.toggle('hidden', !expanded);
      toggleEl.textContent = expanded ? '\u25bc' : '\u25b6';
      if (expanded && body.dataset.loaded !== 'true') {
        loadHistory();
      }
    });

    const listEl = createElement('div', { className: 'history-list' });

    const STATUS_COLORS: Record<string, string> = {
      idea: '#94a3b8',
      todo: '#60a5fa',
      'in-progress': '#f59e0b',
      done: '#34d399',
      archived: '#6b7280',
    };

    const FIELD_LABELS: Record<string, string> = {
      status: 'Status',
      priority: 'Priority',
      title: 'Title',
      description: 'Description',
      assignee: 'Assignee',
      agent_type: 'Agent',
    };

    const PRIORITY_LABELS: Record<string, string> = {
      '0': 'None', '1': 'Low', '2': 'Medium', '3': 'High', '4': 'Critical',
    };

    const formatValue = (field: string, value: string | null): string => {
      if (value === null || value === 'None' || value === 'null') return '\u2014';
      if (field === 'priority') return PRIORITY_LABELS[value] ?? value;
      if (field === 'description') {
        return value.length > 60 ? value.slice(0, 57) + '\u2026' : value;
      }
      return value;
    };

    const renderEntry = (entry: CardHistoryEntry): HTMLElement => {
      const item = createElement('div', { className: 'history-item' });
      const fieldLabel = FIELD_LABELS[entry.fieldChanged] ?? entry.fieldChanged;
      const fieldEl = createElement('span', { className: 'history-field' }, fieldLabel);
      const changeEl = createElement('span', { className: 'history-change' });

      if (entry.fieldChanged === 'status') {
        const oldBadge = createElement('span', { className: 'history-status-badge' }, formatValue('status', entry.oldValue));
        const newBadge = createElement('span', { className: 'history-status-badge history-status-badge--new' }, formatValue('status', entry.newValue));
        if (entry.oldValue && STATUS_COLORS[entry.oldValue]) {
          (oldBadge as HTMLElement).style.color = STATUS_COLORS[entry.oldValue];
          (oldBadge as HTMLElement).style.borderColor = STATUS_COLORS[entry.oldValue];
        }
        if (entry.newValue && STATUS_COLORS[entry.newValue]) {
          (newBadge as HTMLElement).style.color = STATUS_COLORS[entry.newValue];
          (newBadge as HTMLElement).style.borderColor = STATUS_COLORS[entry.newValue];
        }
        const arrow = createElement('span', { className: 'history-arrow' }, ' \u2192 ');
        changeEl.appendChild(oldBadge);
        changeEl.appendChild(arrow);
        changeEl.appendChild(newBadge);
      } else {
        const oldText = formatValue(entry.fieldChanged, entry.oldValue);
        const newText = formatValue(entry.fieldChanged, entry.newValue);
        changeEl.textContent = `${oldText} \u2192 ${newText}`;
      }

      const dateStr = new Date(entry.changedAt).toLocaleDateString(undefined, {
        month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit',
      });
      const dateEl = createElement('span', { className: 'history-date' }, dateStr);

      item.appendChild(fieldEl);
      item.appendChild(changeEl);
      item.appendChild(dateEl);
      return item;
    };

    const loadHistory = () => {
      listEl.innerHTML = '';
      listEl.appendChild(createElement('div', { className: 'empty-text' }, 'Loading\u2026'));
      apiClient.fetchCardHistory(cardId).then((entries) => {
        body.dataset.loaded = 'true';
        listEl.innerHTML = '';
        const shown = entries.slice(0, 20);
        if (shown.length === 0) {
          listEl.appendChild(createElement('div', { className: 'empty-text' }, 'No changes recorded yet.'));
        } else {
          shown.forEach((e) => listEl.appendChild(renderEntry(e)));
        }
      });
    };

    body.appendChild(listEl);
    section.appendChild(headerEl);
    section.appendChild(body);
    return section;
  }

  private async handleEnrich(cardId: string, descInput: HTMLTextAreaElement, checklistSection: HTMLElement): Promise<void> {
    const enrichBtn = this.modal.querySelector('.enrich-btn') as HTMLButtonElement | null;
    if (!enrichBtn) return;

    enrichBtn.disabled = true;
    enrichBtn.classList.add('enrich-loading');
    enrichBtn.textContent = '\u23f3';

    try {
      const result = await apiClient.enrichCard(cardId);
      if (!result) throw new Error('No result');

      if (!descInput.value.trim() && result.description) {
        descInput.value = result.description;
        if (this.card) {
          cardService.update(this.card.id, { description: result.description });
        }
      }

      for (const text of result.checklist_items) {
        const saved = await apiClient.addChecklistItem(cardId, text);
        if (saved) {
          const newChecklist = this.buildChecklistSection(cardId);
          checklistSection.replaceWith(newChecklist);
          break;
        }
      }
      for (let i = 1; i < result.checklist_items.length; i++) {
        await apiClient.addChecklistItem(cardId, result.checklist_items[i]);
      }

      const existingBadge = this.modal.querySelector('.effort-badge');
      if (existingBadge) existingBadge.remove();
      if (result.effort) {
        const badge = createElement('span', { className: `effort-badge effort-badge--${result.effort.toLowerCase()}` }, `\u26a1 ${result.effort}`);
        enrichBtn.insertAdjacentElement('afterend', badge);
      }

      if (result.tags && result.tags.length > 0 && this.card) {
        const existingTags = this.card.tags || [];
        const newTags = result.tags.filter((t) => !existingTags.includes(t));
        if (newTags.length > 0) {
          const updatedTags = [...existingTags, ...newTags];
          cardService.update(this.card.id, { tags: updatedTags });
        }
      }

      eventBus.emit(EVENTS.TOAST_SHOW, { message: '\u2728 Card enriched!', type: 'success', duration: 3000 });
    } catch (err) {
      console.error('[CardDetailModal] enrichCard error:', err);
      eventBus.emit(EVENTS.TOAST_SHOW, { message: '\u274c Enrichment failed', type: 'error', duration: 3000 });
    } finally {
      enrichBtn.disabled = false;
      enrichBtn.classList.remove('enrich-loading');
      enrichBtn.textContent = '\u2728 AI Enrich';
    }
  }

  // ── Main render ───────────────────────────────────────────────────────────

  private renderContent(): void {
    if (!this.card) return;
    this.destroyCodeMirror();
    this.modal.innerHTML = '';
    this.chatMessagesEl = null;

    // Apply color class
    this.modal.className = 'modal card-detail-modal';
    if (this.card.color) {
      this.modal.classList.add(`card-detail-modal--${this.card.color}`);
    }

    // ── Header ──────────────────────────────────────────────────────────────
    const header = createElement('div', { className: 'modal-header' });
    const titleInput = createElement('input', {
      className: 'modal-title-input',
      value: this.card.title,
    }) as HTMLInputElement;
    titleInput.addEventListener('change', () => {
      if (this.card) {
        this.saveCard({ title: titleInput.value });
      }
    });

    // AI Enrich button
    const enrichBtn = createElement('button', { className: 'enrich-btn', title: 'AI-generate description, checklist, effort & tags' }, '\u2728 AI Enrich') as HTMLButtonElement;
    enrichBtn.type = 'button';

    // Execute button
    const executeBtn = createElement('button', { className: 'execute-btn', title: 'Voxy reads and executes this card' }, '\u25b6 Execute') as HTMLButtonElement;
    executeBtn.type = 'button';
    executeBtn.addEventListener('click', async () => {
      if (!this.card) return;
      executeBtn.disabled = true;
      executeBtn.textContent = '\u25b6 Executing\u2026';
      executeBtn.classList.add('execute-loading');

      const result = await apiClient.executeCard(this.card.id);
      if (result) {
        // Send the execution prompt through the card chat
        this.sendChatMessage(result.prompt);
        eventBus.emit(EVENTS.TOAST_SHOW, { message: `\u25b6 Executing: "${this.card.title}"`, type: 'success', duration: 3000 });
      } else {
        eventBus.emit(EVENTS.TOAST_SHOW, { message: '\u274c Execution failed', type: 'error', duration: 3000 });
      }
      executeBtn.disabled = false;
      executeBtn.textContent = '\u25b6 Execute';
      executeBtn.classList.remove('execute-loading');
    });

    // Duplicate button
    const duplicateBtn = createElement('button', { className: 'duplicate-btn', title: 'Duplicate this card' }, '\ud83d\udccb Duplicate') as HTMLButtonElement;
    duplicateBtn.type = 'button';
    duplicateBtn.addEventListener('click', async () => {
      if (!this.card) return;
      duplicateBtn.disabled = true;
      duplicateBtn.textContent = '\u23f3';
      const newCard = await apiClient.duplicateCard(this.card.id);
      if (newCard) {
        const cards = appState.get('cards') as Card[];
        appState.set('cards', [...cards, newCard]);
        eventBus.emit(EVENTS.CARD_CREATED, newCard);
        eventBus.emit(EVENTS.TOAST_SHOW, { message: `\ud83d\udccb Duplicated: "${newCard.title}"`, type: 'success', duration: 3000 });
        this.onUpdated?.(newCard);
        this.close();
      } else {
        eventBus.emit(EVENTS.TOAST_SHOW, { message: '\u274c Duplication failed', type: 'error', duration: 3000 });
      }
      duplicateBtn.disabled = false;
      duplicateBtn.textContent = '\ud83d\udccb Duplicate';
    });

    const closeBtn = createElement('button', { className: 'modal-close-btn' }, '\u2715');
    closeBtn.addEventListener('click', () => this.close());

    header.appendChild(titleInput);
    header.appendChild(enrichBtn);
    header.appendChild(executeBtn);
    header.appendChild(duplicateBtn);
    header.appendChild(closeBtn);

    // ── Two-column body ──────────────────────────────────────────────────────
    const body = createElement('div', { className: 'modal-body-columns' });

    // ── LEFT COLUMN: Description editor + Chat ──────────────────────────────
    const leftCol = createElement('div', { className: 'modal-col-left' });

    // Description — CodeMirror 6 editor
    const descSection = createElement('div', { className: 'modal-section modal-desc-section' });
    const descLabel = createElement('label', { className: 'modal-label' }, 'Description');

    this.codeMirrorEditor = new CodeMirrorEditor({
      initialValue: this.card.description || '',
      placeholderText: 'Write card description... (Markdown supported)',
      onSave: (value: string) => {
        if (this.card) {
          this.saveCard({ description: value });
        }
      },
    });

    descSection.appendChild(descLabel);
    descSection.appendChild(this.codeMirrorEditor.getElement());

    // Watch for theme changes to refresh CodeMirror
    this.themeObserver = new MutationObserver(() => {
      if (this.codeMirrorEditor) {
        this.codeMirrorEditor.refreshTheme();
      }
    });
    this.themeObserver.observe(document.documentElement, {
      attributes: true,
      attributeFilter: ['data-theme'],
    });

    // ── Card Chat with Voxy (functional, scoped to card) ────────────────────
    const chatSection = createElement('div', { className: 'modal-section modal-chat-section' });
    const chatLabel = createElement('label', { className: 'modal-label' }, '\ud83d\udcac Card Chat');
    const chatHint = createElement('span', { className: 'card-chat-hint' }, 'scoped to this card');

    const chatMessages = createElement('div', { className: 'card-chat-messages' });
    this.chatMessagesEl = chatMessages;

    const chatInputRow = createElement('div', { className: 'card-chat-input-row' });
    const chatInput = createElement('input', {
      type: 'text',
      className: 'card-chat-input-field',
      placeholder: 'Ask Voxy about this card\u2026',
    }) as HTMLInputElement;

    const sendBtn = createElement('button', {
      className: 'card-chat-send-btn',
      type: 'button',
      title: 'Send',
    }, '\u2191') as HTMLButtonElement;

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

    chatInputRow.appendChild(chatInput);
    chatInputRow.appendChild(sendBtn);

    const chatHeaderRow = createElement('div', { className: 'card-chat-header' });
    chatHeaderRow.appendChild(chatLabel);
    chatHeaderRow.appendChild(chatHint);

    chatSection.appendChild(chatHeaderRow);
    chatSection.appendChild(chatMessages);
    chatSection.appendChild(chatInputRow);

    leftCol.appendChild(descSection);
    leftCol.appendChild(chatSection);

    // ── RIGHT COLUMN: Metadata ──────────────────────────────────────────────
    const rightCol = createElement('div', { className: 'modal-col-right' });

    // Status buttons
    const statusRow = createElement('div', { className: 'modal-status-row' });
    for (const status of CARD_STATUSES) {
      const btn = createElement(
        'button',
        {
          className: `status-btn ${this.card.status === status ? 'active' : ''}`,
          'data-status': status,
        },
        CARD_STATUS_LABELS[status]
      );
      btn.addEventListener('click', () => {
        if (this.card) {
          cardService.move(this.card.id, status as CardStatus);
        }
      });
      statusRow.appendChild(btn);
    }
    rightCol.appendChild(statusRow);

    // Vote section
    const voteSection = this.buildVoteSection(this.card);

    // Agent assignment
    const currentAgentType = this.card.agentType || 'ember';
    const agentSection = createElement('div', { className: 'modal-section' });
    const agentLabel = createElement('label', { className: 'modal-label' }, 'Agent');
    const agentSelector = createElement('div', { className: 'agent-selector agent-selector--modal' });

    this.agents.forEach((agent) => {
      const chip = createElement('button', {
        className: 'agent-chip' + (currentAgentType === agent.type ? ' selected' : ''),
        'data-agent-type': agent.type,
        title: agent.description,
      }, `${agent.emoji} ${agent.name}`);
      (chip as HTMLButtonElement).type = 'button';
      chip.addEventListener('click', () => {
        if (!this.card) return;
        agentSelector.querySelectorAll('.agent-chip').forEach((el) => el.classList.remove('selected'));
        chip.classList.add('selected');
        cardService.updateAgentType(this.card.id, agent.type);
      });
      agentSelector.appendChild(chip);
    });

    agentSection.appendChild(agentLabel);
    agentSection.appendChild(agentSelector);
    rightCol.appendChild(agentSection);

    // Assignee & Watchers
    const assigneeWatchersSection = this.buildAssigneeWatchersSection(this.card);

    // Tags
    const tagsSection = createElement('div', { className: 'modal-section' });
    const tagsLabel = createElement('label', { className: 'modal-label' }, 'Tags');
    const tagsContainer = createElement('div', { className: 'modal-tags' });

    const renderTagPills = () => {
      tagsContainer.innerHTML = '';
      if (!this.card) return;

      this.card.tags.forEach((tag) => {
        const [bg, color] = getTagColorModal(tag);
        const tagEl = createElement('span', { className: 'card-tag modal-card-tag', title: tag });
        tagEl.style.background = bg;
        tagEl.style.color = color;
        const labelSpan = createElement('span', {}, tag);
        const removeBtn = createElement('span', { className: 'tag-remove', title: `Remove "${tag}"` }, '\u00d7');
        removeBtn.addEventListener('click', () => {
          if (this.card) {
            cardService.removeTag(this.card.id, tag);
          }
        });
        tagEl.appendChild(labelSpan);
        tagEl.appendChild(removeBtn);
        tagsContainer.appendChild(tagEl);
      });

      const inputWrapper = createElement('div', { className: 'tag-input-wrapper' });
      const tagInput = createElement('input', {
        type: 'text',
        className: 'tag-input-field',
        placeholder: 'Add tag\u2026',
      }) as HTMLInputElement;

      const commitTags = (raw: string) => {
        const tags = raw.split(',').map((t) => t.trim()).filter(Boolean);
        tags.forEach((tag) => {
          if (this.card && !this.card.tags.includes(tag)) {
            cardService.addTag(this.card.id, tag);
          }
        });
        tagInput.value = '';
      };

      tagInput.addEventListener('keydown', (e: KeyboardEvent) => {
        if (e.key === 'Enter') {
          e.preventDefault();
          commitTags(tagInput.value);
        } else if (e.key === ',') {
          e.preventDefault();
          commitTags(tagInput.value);
        } else if (e.key === 'Escape') {
          tagInput.value = '';
        }
      });

      tagInput.addEventListener('input', () => {
        if (tagInput.value.includes(',')) {
          commitTags(tagInput.value);
        }
      });

      inputWrapper.appendChild(tagInput);
      tagsContainer.appendChild(inputWrapper);
    };

    renderTagPills();
    tagsSection.appendChild(tagsLabel);
    tagsSection.appendChild(tagsContainer);

    // Dependencies
    {
      const depsSection = createElement('div', { className: 'modal-section' });
      const depsLabel = createElement('label', { className: 'modal-label' }, 'Dependencies');

      const chipsContainer = createElement('div', { className: 'dependency-chips-container' });
      const renderChips = () => {
        chipsContainer.innerHTML = '';
        if (!this.card) return;
        if (this.card.dependencies.length === 0) {
          chipsContainer.appendChild(createElement('span', { className: 'empty-text' }, 'No dependencies'));
          return;
        }
        this.card.dependencies.forEach((depId) => {
          const depCard = appState.getCard(depId);
          const chip = createElement('span', { className: 'dependency-chip' });
          const statusIcon = depCard ? (depCard.status === 'done' ? '\u2705 ' : '\u23f3 ') : '';
          const label = createElement('span', {}, statusIcon + (depCard ? depCard.title : depId));
          const removeBtn = createElement('button', { className: 'dep-chip-remove', title: 'Remove dependency' }, '\u00d7');
          removeBtn.addEventListener('click', () => {
            if (this.card) cardService.removeDependency(this.card.id, depId);
          });
          chip.appendChild(label);
          chip.appendChild(removeBtn);
          chipsContainer.appendChild(chip);
        });
      };
      renderChips();

      const addDepRow = createElement('div', { className: 'dep-add-row' });
      const projectId = this.card.projectId;
      const allProjectCards = projectId ? appState.getCardsByProject(projectId)
        .filter((c) => c.id !== this.card!.id) : [];

      if (allProjectCards.length > 0) {
        const select = createElement('select', { className: 'dep-add-select' }) as HTMLSelectElement;
        const placeholder = document.createElement('option');
        placeholder.value = '';
        placeholder.textContent = '+ Add dependency\u2026';
        placeholder.disabled = true;
        placeholder.selected = true;
        select.appendChild(placeholder);

        allProjectCards.forEach((c) => {
          const opt = document.createElement('option');
          opt.value = c.id;
          const already = this.card!.dependencies.includes(c.id);
          opt.textContent = `${c.status === 'done' ? '\u2705' : '\u23f3'} ${c.title}`;
          opt.disabled = already;
          select.appendChild(opt);
        });

        select.addEventListener('change', () => {
          const depId = select.value;
          if (depId && this.card) {
            cardService.addDependency(this.card.id, depId);
            select.value = '';
          }
        });

        addDepRow.appendChild(select);
      } else {
        addDepRow.appendChild(createElement('span', { className: 'empty-text' }, 'No other cards in this project'));
      }

      depsSection.appendChild(depsLabel);
      depsSection.appendChild(chipsContainer);
      depsSection.appendChild(addDepRow);
      rightCol.appendChild(depsSection);
    }

    // Checklist
    const checklistSection = this.buildChecklistSection(this.card.id);

    // Attachments
    const attachmentsSection = this.buildAttachmentsSection(this.card.id);

    // Relations
    rightCol.appendChild(this.buildRelationsSection(this.card));

    // Time tracking
    const timeSection = this.buildTimeSection(this.card.id, this.card.totalMinutes ?? 0);

    // Comments
    const commentsSection = this.buildCommentsSection(this.card.id);

    // History
    const historySection = this.buildHistorySection(this.card.id);

    // Color picker
    {
      const colorSection = createElement('div', { className: 'modal-section' });
      const colorLabel = createElement('label', { className: 'modal-label' }, 'Color');
      const colorRow = createElement('div', { className: 'card-detail-color-row' });
      let selectedSwatch: HTMLElement | null = null;
      const currentColor = this.card.color ?? null;

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
          this.saveCard({ color: value } as Partial<Card>);
          this.modal.className = 'modal card-detail-modal';
          if (value) this.modal.classList.add(`card-detail-modal--${value}`);
        });
        colorRow.appendChild(swatch);
      });

      colorSection.appendChild(colorLabel);
      colorSection.appendChild(colorRow);
      rightCol.appendChild(colorSection);
    }

    // Assign to Project
    {
      const promoteSection = createElement('div', { className: 'modal-section', style: 'position: relative;' });
      const promoteBtn = createElement('button', {
        className: 'note-detail-promote-btn',
        type: 'button',
        title: 'Assign to a Project',
      }, '\ud83d\ude80 Assign to Project') as HTMLButtonElement;
      promoteBtn.addEventListener('click', () => {
        if (!this.card) return;
        this.showProjectPicker(promoteBtn, this.card);
      });
      promoteSection.appendChild(promoteBtn);
      rightCol.appendChild(promoteSection);
    }

    // Metadata
    const metaSection = createElement('div', { className: 'modal-meta' });
    metaSection.appendChild(
      createElement('span', {}, `Created: ${formatTime(this.card.createdAt)}`)
    );
    metaSection.appendChild(
      createElement('span', {}, `Updated: ${formatTime(this.card.updatedAt)}`)
    );

    // Focus Mode button
    const focusSection = createElement('div', { className: 'modal-section modal-focus-section' });
    const focusBtn = createElement('button', { className: 'focus-mode-btn' }, '\ud83c\udfaf Focus Mode');
    focusBtn.addEventListener('click', () => {
      if (!this.card) return;
      this.close();
      const focusMode = new FocusMode(document.body, {
        card: this.card,
        onExit: () => {
          eventBus.emit(EVENTS.FOCUS_MODE_EXIT, null);
        },
      });
      eventBus.emit(EVENTS.FOCUS_MODE_ENTER, this.card.id);
    });
    focusSection.appendChild(focusBtn);

    // Delete button
    const dangerZone = createElement('div', { className: 'modal-danger' });
    const deleteBtn = createElement('button', { className: 'delete-btn' }, '\ud83d\uddd1\ufe0f Delete Card');
    deleteBtn.addEventListener('click', () => this.deleteCard());
    dangerZone.appendChild(deleteBtn);

    // Wire up enrich button
    const descTextareaAdapter = document.createElement('textarea') as HTMLTextAreaElement;
    Object.defineProperty(descTextareaAdapter, 'value', {
      get: () => this.codeMirrorEditor ? this.codeMirrorEditor.getValue() : '',
      set: (v: string) => { if (this.codeMirrorEditor) this.codeMirrorEditor.setValue(v); },
    });
    const cardIdForEnrich = this.card.id;
    enrichBtn.addEventListener('click', () => {
      this.handleEnrich(cardIdForEnrich, descTextareaAdapter, checklistSection);
    });

    // ── Workspace Files section ──────────────────────────────────────────────
    const filesSection = this.buildFilesSection();

    // ── Assemble right column ────────────────────────────────────────────────
    // Removed: votes, assignee, watchers — personal workflow, not Jira
    // rightCol.appendChild(voteSection);
    // rightCol.appendChild(assigneeWatchersSection);
    rightCol.appendChild(tagsSection);
    rightCol.appendChild(checklistSection);
    rightCol.appendChild(filesSection);
    rightCol.appendChild(attachmentsSection);
    rightCol.appendChild(timeSection);
    rightCol.appendChild(commentsSection);
    rightCol.appendChild(historySection);
    rightCol.appendChild(focusSection);
    rightCol.appendChild(metaSection);
    rightCol.appendChild(dangerZone);

    // ── Assemble modal ───────────────────────────────────────────────────────
    body.appendChild(leftCol);
    body.appendChild(rightCol);
    this.modal.appendChild(header);
    this.modal.appendChild(body);

    // Populate existing chat history
    this.refreshChat();

    // Focus the chat input
    setTimeout(() => chatInput.focus(), 80);
  }

  // ── Project picker ───────────────────────────────────────────────────────

  private showProjectPicker(anchor: HTMLElement, card: Card): void {
    this.closeProjectPicker();

    const projects = ((appState.get('projects') as Project[]) ?? [])
      .filter(p => p.id !== SYSTEM_PROJECT_ID);

    const dropdown = createElement('div', { className: 'project-picker-dropdown' });

    if (projects.length === 0) {
      const empty = createElement('div', { className: 'project-picker-item project-picker-item--empty' }, 'No projects yet');
      dropdown.appendChild(empty);
    } else {
      projects.forEach(project => {
        const item = createElement('div', { className: 'project-picker-item' });
        item.textContent = `${project.emoji || '📁'} ${project.name}`;
        item.addEventListener('click', async (e) => {
          e.stopPropagation();
          this.closeProjectPicker();
          const result = await mainBoardService.assignToProject(card.id, project.id);
          if (result) {
            eventBus.emit(EVENTS.TOAST_SHOW, { message: `Card moved to ${project.name}`, type: 'success', duration: 3000 });
            this.close();
            this.onUpdated?.(result);
          } else {
            eventBus.emit(EVENTS.TOAST_SHOW, { message: 'Failed to assign card', type: 'error', duration: 3000 });
          }
        });
        dropdown.appendChild(item);
      });
    }

    const newItem = createElement('div', { className: 'project-picker-item project-picker-item--new' });
    newItem.textContent = '+ New Project';
    newItem.addEventListener('click', (e) => {
      e.stopPropagation();
      this.closeProjectPicker();
      eventBus.emit(EVENTS.PROJECT_FORM_SHOW, { mode: 'create', prefillTitle: card.title });
    });
    dropdown.appendChild(newItem);

    const rect = anchor.getBoundingClientRect();
    dropdown.style.position = 'fixed';
    dropdown.style.left = `${rect.left}px`;
    dropdown.style.top = `${rect.bottom + 4}px`;
    document.body.appendChild(dropdown);

    const onOutsideClick = (e: MouseEvent) => {
      if (!dropdown.contains(e.target as Node)) {
        this.closeProjectPicker();
      }
    };
    setTimeout(() => document.addEventListener('click', onOutsideClick), 0);

    this.activePickerCleanup = () => {
      dropdown.remove();
      document.removeEventListener('click', onOutsideClick);
      this.activePickerCleanup = null;
    };
  }

  private closeProjectPicker(): void {
    if (this.activePickerCleanup) this.activePickerCleanup();
  }

  // ── Lifecycle ─────────────────────────────────────────────────────────────

  destroy(): void {
    this.closeProjectPicker();
    this.destroyCodeMirror();
    this.unsubscribers.forEach((unsub) => unsub());
    this.unsubscribers = [];
    this.overlay.remove();
  }
}
