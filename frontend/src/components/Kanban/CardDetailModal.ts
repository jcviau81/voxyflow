import { Card, AgentPersona, CardStatus, AgentInfo, TimeEntry, CardComment, ChecklistItem, CardAttachment, CardRelation, CardRelationType, CardHistoryEntry } from '../../types';

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
import { eventBus } from '../../utils/EventBus';
import { EVENTS, CARD_STATUSES, CARD_STATUS_LABELS, AGENT_PERSONAS, AGENT_TYPE_INFO } from '../../utils/constants';
import { createElement, formatTime } from '../../utils/helpers';
import { appState } from '../../state/AppState';
import { cardService } from '../../services/CardService';
import { apiClient } from '../../services/ApiClient';
import { FocusMode } from '../FocusMode/FocusMode';

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

export class CardDetailModal {
  private overlay: HTMLElement;
  private modal: HTMLElement;
  private card: Card | null = null;
  private unsubscribers: (() => void)[] = [];
  private agents: AgentInfo[] = Object.entries(AGENT_TYPE_INFO).map(([type, info]) => ({
    type,
    name: info.name,
    emoji: info.emoji,
    description: info.description,
    strengths: [],
    keywords: [],
  }));

  constructor(private parentElement: HTMLElement) {
    this.overlay = createElement('div', { className: 'modal-overlay hidden' });
    this.modal = createElement('div', { className: 'modal card-detail-modal' });
    this.overlay.appendChild(this.modal);
    this.parentElement.appendChild(this.overlay);
    this.setupListeners();
    // Load agents from API (for richer descriptions)
    cardService.getAgents().then((agents) => {
      if (agents.length > 0) this.agents = agents;
    }).catch(() => {/* fallback already set */});
  }

  private setupListeners(): void {
    this.overlay.addEventListener('click', (e) => {
      if (e.target === this.overlay) this.close();
    });

    this.unsubscribers.push(
      eventBus.on(EVENTS.MODAL_OPEN, (data: unknown) => {
        const { type, cardId } = data as { type: string; cardId: string };
        if (type === 'card-detail') {
          this.open(cardId);
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

    // ESC to close
    document.addEventListener('keydown', (e) => {
      if (e.key === 'Escape' && !this.overlay.classList.contains('hidden')) {
        this.close();
      }
    });
  }

  open(cardId: string): void {
    this.card = appState.getCard(cardId) || null;
    if (!this.card) return;

    this.renderContent();
    this.overlay.classList.remove('hidden');
  }

  close(): void {
    this.overlay.classList.add('hidden');
    appState.selectCard(null);
  }

  private formatMinutes(minutes: number): string {
    if (minutes <= 0) return '0m';
    const h = Math.floor(minutes / 60);
    const m = minutes % 60;
    if (h === 0) return `${m}m`;
    if (m === 0) return `${h}h`;
    return `${h}h ${m}m`;
  }

  private buildTimeSection(cardId: string, totalMinutes: number): HTMLElement {
    const section = createElement('div', { className: 'modal-section time-tracking-section' });
    const label = createElement('label', { className: 'modal-label' }, '⏱ Time Tracking');

    // Total summary
    const totalEl = createElement(
      'div',
      { className: 'time-total' },
      totalMinutes > 0 ? `⏱ ${this.formatMinutes(totalMinutes)} total` : '⏱ No time logged yet'
    );

    // Log time toggle button
    let formVisible = false;
    const logBtn = createElement('button', { className: 'log-time-btn' }, '+ Log Time');

    // Inline form (hidden by default)
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
      submitBtn.textContent = '…';
      (submitBtn as HTMLButtonElement).disabled = true;

      const note = noteInput.value.trim() || undefined;
      const entry = await apiClient.logTime(cardId, mins, note);
      if (entry) {
        // Refresh the section
        const updatedTotal = totalMinutes + mins;
        const newSection = this.buildTimeSection(cardId, updatedTotal);
        section.replaceWith(newSection);
        // Update card totalMinutes in state
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
      logBtn.textContent = formVisible ? '− Cancel' : '+ Log Time';
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

    // Entry list (loaded async)
    const listEl = createElement('div', { className: 'time-entry-list' });
    listEl.textContent = 'Loading…';

    apiClient.fetchTimeEntries(cardId).then((entries) => {
      listEl.innerHTML = '';
      if (entries.length === 0) {
        listEl.appendChild(createElement('div', { className: 'empty-text' }, 'No entries yet.'));
        return;
      }
      // Recompute total from actual entries
      const fetchedTotal = entries.reduce((sum, e) => sum + e.durationMinutes, 0);
      if (fetchedTotal !== totalMinutes) {
        totalEl.textContent = fetchedTotal > 0 ? `⏱ ${this.formatMinutes(fetchedTotal)} total` : '⏱ No time logged yet';
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
        const delBtn = createElement('button', { className: 'time-entry-delete', title: 'Delete entry' }, '×');
        delBtn.addEventListener('click', async () => {
          const ok = await apiClient.deleteTimeEntry(cardId, entry.id);
          if (ok) {
            item.remove();
            const newTotal = Math.max(0, totalMinutes - entry.durationMinutes);
            totalEl.textContent = newTotal > 0 ? `⏱ ${this.formatMinutes(newTotal)} total` : '⏱ No time logged yet';
            // Update state
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

    // Header with count placeholder
    const headerEl = createElement('label', { className: 'modal-label comments-header' }, '💬 Comments');

    // Comment list container
    const listEl = createElement('div', { className: 'comments-list' });
    listEl.textContent = 'Loading…';

    // Optimistic local cache
    let localComments: CardComment[] = [];

    const updateHeader = () => {
      headerEl.textContent = `💬 Comments (${localComments.length})`;
    };

    const renderComment = (comment: CardComment): HTMLElement => {
      const item = createElement('div', { className: 'comment-item' });

      // Avatar with initials
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
      meta.textContent = `${comment.author} · ${dateStr}`;

      const text = createElement('div', { className: 'comment-text' }, comment.content);

      const delBtn = createElement('button', { className: 'comment-delete', title: 'Delete comment' }, '×');
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

    // Load comments async
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

    // Input row
    const inputRow = createElement('div', { className: 'comment-input-row' });
    const textarea = createElement('textarea', {
      className: 'comment-textarea',
      placeholder: 'Add a comment…',
      rows: '2',
    }) as HTMLTextAreaElement;
    const submitBtn = createElement('button', { className: 'comment-submit-btn' }, 'Post') as HTMLButtonElement;
    submitBtn.type = 'button';

    const submitComment = async () => {
      const content = textarea.value.trim();
      if (!content) return;

      // Optimistic UI — add immediately
      const optimisticComment: CardComment = {
        id: `optimistic-${Date.now()}`,
        cardId,
        author: 'User',
        content,
        createdAt: Date.now(),
      };
      // Remove empty-text placeholder if present
      const emptyEl = listEl.querySelector('.empty-text');
      if (emptyEl) emptyEl.remove();

      const optimisticEl = renderComment(optimisticComment);
      optimisticEl.classList.add('comment-optimistic');
      listEl.insertBefore(optimisticEl, listEl.firstChild);
      localComments.unshift(optimisticComment);
      updateHeader();
      textarea.value = '';
      submitBtn.disabled = true;

      // Confirm with server
      const saved = await apiClient.addComment(cardId, content);
      if (saved) {
        // Replace optimistic entry
        optimisticEl.remove();
        localComments = localComments.filter((c) => c.id !== optimisticComment.id);
        const confirmedEl = renderComment(saved);
        listEl.insertBefore(confirmedEl, listEl.firstChild);
        localComments.unshift(saved);
        updateHeader();
      } else {
        // Rollback on failure
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

    // Header
    const headerEl = createElement('label', { className: 'modal-label checklist-header' }, '☑️ Checklist');

    // Progress bar container
    const progressContainer = createElement('div', { className: 'checklist-progress-bar-container' });
    const progressTrack = createElement('div', { className: 'checklist-progress-track' });
    const progressBar = createElement('div', { className: 'checklist-progress-bar' });
    const progressLabel = createElement('span', { className: 'checklist-progress-label' }, '');
    progressTrack.appendChild(progressBar);
    progressContainer.appendChild(progressTrack);
    progressContainer.appendChild(progressLabel);

    // List container
    const listEl = createElement('div', { className: 'checklist-list' });
    listEl.textContent = 'Loading…';

    // Local items cache
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
        // Optimistic update
        row.classList.toggle('completed', newCompleted);
        item.completed = newCompleted;
        updateProgress();
        await apiClient.updateChecklistItem(cardId, item.id, { completed: newCompleted });
      });

      // Inline editable text
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

      // Delete button
      const delBtn = createElement('button', { className: 'checklist-item-delete', title: 'Remove item' }, '×');
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

    // Load items async
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

    // Add item row
    const addRow = createElement('div', { className: 'checklist-add-row' });
    const addInput = createElement('input', {
      type: 'text',
      className: 'form-input checklist-add-input',
      placeholder: 'Add item… (Enter to add)',
    }) as HTMLInputElement;

    const submitAdd = async () => {
      const text = addInput.value.trim();
      if (!text) return;
      addInput.value = '';
      const saved = await apiClient.addChecklistItem(cardId, text);
      if (saved) {
        // Remove empty placeholder
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
    if (mimeType.startsWith('image/')) return '🖼️';
    if (mimeType.includes('pdf')) return '📄';
    if (mimeType.includes('spreadsheet') || mimeType.includes('excel') || mimeType.includes('csv')) return '📊';
    if (mimeType.includes('word') || mimeType.includes('document')) return '📝';
    if (mimeType.includes('zip') || mimeType.includes('archive') || mimeType.includes('tar') || mimeType.includes('gzip')) return '🗜️';
    if (mimeType.startsWith('video/')) return '🎬';
    if (mimeType.startsWith('audio/')) return '🎵';
    return '📄';
  }

  private formatFileSize(bytes: number): string {
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  }

  private buildAttachmentsSection(cardId: string): HTMLElement {
    const section = createElement('div', { className: 'modal-section attachments-section' });

    const headerEl = createElement('label', { className: 'modal-label attachments-header' }, '📎 Attachments');

    // List container
    const listEl = createElement('div', { className: 'attachment-list' });
    listEl.textContent = 'Loading…';

    let localAttachments: CardAttachment[] = [];

    const updateHeader = () => {
      headerEl.textContent = `📎 Attachments (${localAttachments.length})`;
    };

    const renderAttachment = (att: CardAttachment): HTMLElement => {
      const item = createElement('div', { className: 'attachment-item' });

      const icon = createElement('span', { className: 'attachment-icon' }, this.getAttachmentIcon(att.mimeType));

      const info = createElement('div', { className: 'attachment-info' });
      const nameEl = createElement('span', { className: 'attachment-name' }, att.filename);
      const sizeEl = createElement('span', { className: 'attachment-size' }, this.formatFileSize(att.fileSize));
      info.appendChild(nameEl);
      info.appendChild(sizeEl);

      // Image thumbnail preview
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
      }, '⬇️') as HTMLAnchorElement;

      const delBtn = createElement('button', {
        className: 'attachment-delete-btn',
        title: `Delete ${att.filename}`,
      }, '×') as HTMLButtonElement;

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

    // Load attachments async
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

    // Drop zone
    const dropZone = createElement('div', { className: 'attachment-drop-zone' });
    dropZone.innerHTML = '<span>📎 Drop files here or <strong>click to upload</strong></span>';

    const fileInput = createElement('input', {
      type: 'file',
      className: 'attachment-file-input',
      multiple: 'true',
    }) as HTMLInputElement;
    fileInput.style.display = 'none';

    const uploadFiles = async (files: FileList | File[]) => {
      const fileArray = Array.from(files);
      for (const file of fileArray) {
        // Optimistic placeholder
        const placeholder = createElement('div', { className: 'attachment-item attachment-uploading' });
        placeholder.textContent = `⬆️ Uploading ${file.name}…`;
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
          // Show error placeholder
          const errEl = createElement('div', { className: 'attachment-item attachment-error' });
          errEl.textContent = `❌ Failed to upload ${file.name}`;
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
    const sectionLabel = createElement('label', { className: 'modal-label' }, '👤 People');

    // ── Assignee ──────────────────────────────────────────────────────────────
    const assigneeRow = createElement('div', { className: 'assignee-row' });
    const assigneeLabel = createElement('span', { className: 'assignee-field-label' }, '👤 Assigned to:');

    let currentAssignee = card.assignee ?? null;

    // Chip container (shows chip or input)
    const assigneeInputArea = createElement('div', { className: 'assignee-input-area' });

    const renderAssigneeChip = () => {
      assigneeInputArea.innerHTML = '';
      if (currentAssignee) {
        const chip = createElement('span', { className: 'assignee-chip' });
        const circle = createElement('span', { className: 'assignee-chip-avatar' }, getInitials(currentAssignee));
        circle.style.background = nameToColor(currentAssignee);
        const nameEl = createElement('span', { className: 'assignee-chip-name' }, currentAssignee);
        const clearBtn = createElement('button', { className: 'assignee-chip-clear', title: 'Clear assignee' }, '×');
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
          placeholder: 'Type name and press Enter…',
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
    const watchersLabel = createElement('span', { className: 'assignee-field-label' }, '👁 Watchers:');

    let watcherList: string[] = (card.watchers || '').split(',').map((w) => w.trim()).filter(Boolean);

    const watcherChipsContainer = createElement('div', { className: 'watcher-chips-container' });

    const renderWatcherChips = () => {
      watcherChipsContainer.innerHTML = '';
      watcherList.forEach((watcher) => {
        const chip = createElement('span', { className: 'watcher-chip' });
        const nameEl = createElement('span', {}, watcher);
        const removeBtn = createElement('button', { className: 'watcher-chip-remove', title: `Remove ${watcher}` }, '×');
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

      // Input for adding new watcher
      const addInput = createElement('input', {
        type: 'text',
        className: 'form-input watcher-input',
        placeholder: 'Add watcher…',
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
    const label = createElement('label', { className: 'modal-label' }, '▲ Priority Votes');

    const voteCount = card.votes ?? 0;
    const voted = localStorage.getItem(`voxy_voted_${card.id}`) === 'true';

    const countEl = createElement('span', { className: 'vote-count-display' }, `▲ ${voteCount} vote${voteCount !== 1 ? 's' : ''}`);

    const voteBtn = createElement('button', {
      className: 'vote-btn vote-btn-modal' + (voted ? ' voted' : ''),
    }, voted ? 'Un-vote' : 'Vote ▲') as HTMLButtonElement;

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
        countEl.textContent = `▲ ${newCount} vote${newCount !== 1 ? 's' : ''}`;
        voteBtn.textContent = nowVoted ? 'Un-vote' : 'Vote ▲';
        voteBtn.className = 'vote-btn vote-btn-modal' + (nowVoted ? ' voted' : '');
        appState.updateCard(card.id, { votes: newCount });
        // Update in-memory card reference
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
      duplicates: '🔁',
      duplicated_by: '🔁',
      blocks: '⛔',
      is_blocked_by: '🔒',
      relates_to: '🔗',
      cloned_from: '🧬',
      cloned_to: '🧬',
    };
    return icons[type] ?? '🔗';
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
    const headerEl = createElement('label', { className: 'modal-label relations-header' }, '🔗 Related Cards');

    const listEl = createElement('div', { className: 'relations-list' });
    listEl.textContent = 'Loading…';

    let localRelations: CardRelation[] = [];

    const updateHeader = () => {
      headerEl.textContent = `🔗 Related Cards (${localRelations.length})`;
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

      const delBtn = createElement('button', { className: 'relation-delete-btn', title: 'Remove relation' }, '×') as HTMLButtonElement;
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

    // Load async
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

    // Add relation form
    const addRow = createElement('div', { className: 'relation-add-row' });

    const RELATION_TYPES: CardRelationType[] = ['relates_to', 'blocks', 'is_blocked_by', 'duplicates', 'cloned_from'];

    const cardSelect = createElement('select', { className: 'relation-card-select' }) as HTMLSelectElement;
    const cardPlaceholder = document.createElement('option');
    cardPlaceholder.value = '';
    cardPlaceholder.textContent = 'Select card…';
    cardPlaceholder.disabled = true;
    cardPlaceholder.selected = true;
    cardSelect.appendChild(cardPlaceholder);

    const projectCards = card.projectId ? appState.getCardsByProject(card.projectId).filter((c) => c.id !== card.id) : [];
    projectCards.forEach((c) => {
      const opt = document.createElement('option');
      opt.value = c.id;
      opt.textContent = `${c.status === 'done' ? '✅' : '⏳'} ${c.title}`;
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
      addBtn.textContent = '…';

      const saved = await apiClient.addRelation(card.id, targetId, relType);
      if (saved) {
        const emptyEl = listEl.querySelector('.empty-text');
        if (emptyEl) emptyEl.remove();
        localRelations.push(saved);
        listEl.appendChild(renderRelationItem(saved));
        updateHeader();
        cardSelect.value = '';
      } else {
        eventBus.emit(EVENTS.TOAST_SHOW, { message: '❌ Could not add relation', type: 'error', duration: 3000 });
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

    // Collapsible header
    const headerEl = createElement('div', { className: 'history-section-header' });
    const titleEl = createElement('label', { className: 'modal-label history-label' }, '📜 History');
    const toggleEl = createElement('span', { className: 'history-toggle' }, '▶');
    headerEl.appendChild(titleEl);
    headerEl.appendChild(toggleEl);

    // Collapsible body (hidden by default)
    const body = createElement('div', { className: 'history-section-body hidden' });
    let expanded = false;

    headerEl.style.cursor = 'pointer';
    headerEl.addEventListener('click', () => {
      expanded = !expanded;
      body.classList.toggle('hidden', !expanded);
      toggleEl.textContent = expanded ? '▼' : '▶';
      if (expanded && body.dataset.loaded !== 'true') {
        loadHistory();
      }
    });

    const listEl = createElement('div', { className: 'history-list' });

    const STATUS_COLORS: Record<string, string> = {
      idea: '#94a3b8',
      todo: '#60a5fa',
      in_progress: '#f59e0b',
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
      if (value === null || value === 'None' || value === 'null') return '—';
      if (field === 'priority') return PRIORITY_LABELS[value] ?? value;
      if (field === 'description') {
        return value.length > 60 ? value.slice(0, 57) + '…' : value;
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
        const arrow = createElement('span', { className: 'history-arrow' }, ' → ');
        changeEl.appendChild(oldBadge);
        changeEl.appendChild(arrow);
        changeEl.appendChild(newBadge);
      } else {
        const oldText = formatValue(entry.fieldChanged, entry.oldValue);
        const newText = formatValue(entry.fieldChanged, entry.newValue);
        changeEl.textContent = `${oldText} → ${newText}`;
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
      listEl.appendChild(createElement('div', { className: 'empty-text' }, 'Loading…'));
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
    enrichBtn.textContent = '⏳';

    try {
      const result = await apiClient.enrichCard(cardId);
      if (!result) throw new Error('No result');

      // Pre-fill description if empty
      if (!descInput.value.trim() && result.description) {
        descInput.value = result.description;
        // Persist
        if (this.card) cardService.update(this.card.id, { description: result.description });
      }

      // Add checklist items
      for (const text of result.checklist_items) {
        const saved = await apiClient.addChecklistItem(cardId, text);
        if (saved) {
          // Refresh checklist section by triggering a re-render
          const newChecklist = this.buildChecklistSection(cardId);
          checklistSection.replaceWith(newChecklist);
          // reference updated — break here, re-render will handle the rest
          break;
        }
      }
      // Bulk-add remaining items (after section replaced, we can't reuse old ref — use direct API)
      for (let i = 1; i < result.checklist_items.length; i++) {
        await apiClient.addChecklistItem(cardId, result.checklist_items[i]);
      }

      // Show effort badge
      const existingBadge = this.modal.querySelector('.effort-badge');
      if (existingBadge) existingBadge.remove();
      if (result.effort) {
        const badge = createElement('span', { className: `effort-badge effort-badge--${result.effort.toLowerCase()}` }, `⚡ ${result.effort}`);
        enrichBtn.insertAdjacentElement('afterend', badge);
      }

      // Add suggested tags
      if (result.tags && result.tags.length > 0 && this.card) {
        const existingTags = this.card.tags || [];
        const newTags = result.tags.filter((t) => !existingTags.includes(t));
        if (newTags.length > 0) {
          const updatedTags = [...existingTags, ...newTags];
          cardService.update(this.card.id, { tags: updatedTags });
        }
      }

      // Toast
      eventBus.emit(EVENTS.TOAST_SHOW, { message: '✨ Card enriched!', type: 'success', duration: 3000 });
    } catch (err) {
      console.error('[CardDetailModal] enrichCard error:', err);
      eventBus.emit(EVENTS.TOAST_SHOW, { message: '❌ Enrichment failed', type: 'error', duration: 3000 });
    } finally {
      enrichBtn.disabled = false;
      enrichBtn.classList.remove('enrich-loading');
      enrichBtn.textContent = '✨ AI Enrich';
    }
  }

  private renderContent(): void {
    if (!this.card) return;
    this.modal.innerHTML = '';

    // Header
    const header = createElement('div', { className: 'modal-header' });
    const titleInput = createElement('input', {
      className: 'modal-title-input',
      value: this.card.title,
    }) as HTMLInputElement;
    titleInput.addEventListener('change', () => {
      if (this.card) {
        cardService.update(this.card.id, { title: titleInput.value });
      }
    });

    // AI Enrich button
    const enrichBtn = createElement('button', { className: 'enrich-btn', title: 'AI-generate description, checklist, effort & tags' }, '✨ AI Enrich') as HTMLButtonElement;
    enrichBtn.type = 'button';

    // Duplicate button
    const duplicateBtn = createElement('button', { className: 'duplicate-btn', title: 'Duplicate this card' }, '📋 Duplicate') as HTMLButtonElement;
    duplicateBtn.type = 'button';
    duplicateBtn.addEventListener('click', async () => {
      if (!this.card) return;
      duplicateBtn.disabled = true;
      duplicateBtn.textContent = '⏳';
      const newCard = await apiClient.duplicateCard(this.card.id);
      if (newCard) {
        const cards = appState.get('cards') as import('../../types').Card[];
        appState.set('cards', [...cards, newCard]);
        eventBus.emit(EVENTS.CARD_CREATED, newCard);
        eventBus.emit(EVENTS.TOAST_SHOW, { message: `📋 Duplicated: "${newCard.title}"`, type: 'success', duration: 3000 });
        this.close();
      } else {
        eventBus.emit(EVENTS.TOAST_SHOW, { message: '❌ Duplication failed', type: 'error', duration: 3000 });
      }
      duplicateBtn.disabled = false;
      duplicateBtn.textContent = '📋 Duplicate';
    });

    const closeBtn = createElement('button', { className: 'modal-close-btn' }, '✕');
    closeBtn.addEventListener('click', () => this.close());

    header.appendChild(titleInput);
    header.appendChild(enrichBtn);
    header.appendChild(duplicateBtn);
    header.appendChild(closeBtn);

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

    // Description
    const descSection = createElement('div', { className: 'modal-section' });
    const descLabel = createElement('label', { className: 'modal-label' }, 'Description');
    const descInput = createElement('textarea', {
      className: 'modal-description',
      placeholder: 'Add a description...',
    }) as HTMLTextAreaElement;
    descInput.value = this.card.description;
    descInput.addEventListener('change', () => {
      if (this.card) {
        cardService.update(this.card.id, { description: descInput.value });
      }
    });
    descSection.appendChild(descLabel);
    descSection.appendChild(descInput);

    // Agent assignment — chip selector
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

    // Dependencies — multi-select with chips
    const depsSection = createElement('div', { className: 'modal-section' });
    const depsLabel = createElement('label', { className: 'modal-label' }, 'Dependencies');

    // Chips for currently selected dependencies
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
        const statusIcon = depCard ? (depCard.status === 'done' ? '✅ ' : '⏳ ') : '';
        const label = createElement('span', {}, statusIcon + (depCard ? depCard.title : depId));
        const removeBtn = createElement('button', { className: 'dep-chip-remove', title: 'Remove dependency' }, '×');
        removeBtn.addEventListener('click', () => {
          if (this.card) cardService.removeDependency(this.card.id, depId);
        });
        chip.appendChild(label);
        chip.appendChild(removeBtn);
        chipsContainer.appendChild(chip);
      });
    };
    renderChips();

    // Dropdown to add dependencies
    const addDepRow = createElement('div', { className: 'dep-add-row' });
    const projectId = this.card.projectId;
    const allProjectCards = projectId ? appState.getCardsByProject(projectId)
      .filter((c) => c.id !== this.card!.id) : [];

    if (allProjectCards.length > 0) {
      const select = createElement('select', { className: 'dep-add-select' }) as HTMLSelectElement;
      const placeholder = document.createElement('option');
      placeholder.value = '';
      placeholder.textContent = '+ Add dependency…';
      placeholder.disabled = true;
      placeholder.selected = true;
      select.appendChild(placeholder);

      allProjectCards.forEach((c) => {
        const opt = document.createElement('option');
        opt.value = c.id;
        const already = this.card!.dependencies.includes(c.id);
        opt.textContent = `${c.status === 'done' ? '✅' : '⏳'} ${c.title}`;
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

    // Tags — colored pills with × to remove + inline input (Enter or comma to add)
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
        const removeBtn = createElement('span', { className: 'tag-remove', title: `Remove "${tag}"` }, '×');
        removeBtn.addEventListener('click', () => {
          if (this.card) cardService.removeTag(this.card.id, tag);
        });
        tagEl.appendChild(labelSpan);
        tagEl.appendChild(removeBtn);
        tagsContainer.appendChild(tagEl);
      });

      // Tag input wrapper
      const inputWrapper = createElement('div', { className: 'tag-input-wrapper' });
      const tagInput = createElement('input', {
        type: 'text',
        className: 'tag-input-field',
        placeholder: 'Add tag…',
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

      // Commit on comma typed mid-string too
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

    // Metadata
    const metaSection = createElement('div', { className: 'modal-meta' });
    metaSection.appendChild(
      createElement('span', {}, `Created: ${formatTime(this.card.createdAt)}`)
    );
    metaSection.appendChild(
      createElement('span', {}, `Updated: ${formatTime(this.card.updatedAt)}`)
    );

    // Assignee & Watchers
    const assigneeWatchersSection = this.buildAssigneeWatchersSection(this.card);

    // Checklist
    const checklistSection = this.buildChecklistSection(this.card.id);

    // Wire up enrich button now that descInput and checklistSection exist
    const cardIdForEnrich = this.card.id;
    enrichBtn.addEventListener('click', () => {
      this.handleEnrich(cardIdForEnrich, descInput, checklistSection);
    });

    // Vote section
    const voteSection = this.buildVoteSection(this.card);

    // Time tracking
    const timeSection = this.buildTimeSection(this.card.id, this.card.totalMinutes ?? 0);

    // Comments section
    const commentsSection = this.buildCommentsSection(this.card.id);

    // Attachments section
    const attachmentsSection = this.buildAttachmentsSection(this.card.id);

    // Relations section
    const relationsSection = this.buildRelationsSection(this.card);

    // History / Audit Log section
    const historySection = this.buildHistorySection(this.card.id);

    // Focus Mode button
    const focusSection = createElement('div', { className: 'modal-section modal-focus-section' });
    const focusBtn = createElement('button', { className: 'focus-mode-btn' }, '🎯 Focus Mode');
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
    const deleteBtn = createElement('button', { className: 'delete-btn' }, '🗑️ Delete Card');
    deleteBtn.addEventListener('click', () => {
      if (this.card && confirm(`Delete "${this.card.title}"?`)) {
        cardService.delete(this.card.id);
        this.close();
      }
    });
    dangerZone.appendChild(deleteBtn);

    // Assemble
    this.modal.appendChild(header);
    this.modal.appendChild(statusRow);
    this.modal.appendChild(voteSection);
    this.modal.appendChild(descSection);
    this.modal.appendChild(agentSection);
    this.modal.appendChild(assigneeWatchersSection);
    this.modal.appendChild(depsSection);
    this.modal.appendChild(relationsSection);
    this.modal.appendChild(tagsSection);
    this.modal.appendChild(checklistSection);
    this.modal.appendChild(attachmentsSection);
    this.modal.appendChild(timeSection);
    this.modal.appendChild(commentsSection);
    this.modal.appendChild(historySection);
    this.modal.appendChild(focusSection);
    this.modal.appendChild(metaSection);
    this.modal.appendChild(dangerZone);
  }

  update(): void {
    if (this.card) {
      this.card = appState.getCard(this.card.id) || null;
      if (this.card) this.renderContent();
    }
  }

  destroy(): void {
    this.unsubscribers.forEach((unsub) => unsub());
    this.unsubscribers = [];
    this.overlay.remove();
  }
}
