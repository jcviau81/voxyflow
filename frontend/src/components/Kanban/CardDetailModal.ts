import { Card, AgentPersona, CardStatus, AgentInfo, TimeEntry, CardComment, ChecklistItem } from '../../types';

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

    const closeBtn = createElement('button', { className: 'modal-close-btn' }, '✕');
    closeBtn.addEventListener('click', () => this.close());

    header.appendChild(titleInput);
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
    const allProjectCards = appState.getCardsByProject(projectId)
      .filter((c) => c.id !== this.card!.id);

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

    // Checklist
    const checklistSection = this.buildChecklistSection(this.card.id);

    // Time tracking
    const timeSection = this.buildTimeSection(this.card.id, this.card.totalMinutes ?? 0);

    // Comments section
    const commentsSection = this.buildCommentsSection(this.card.id);

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
    this.modal.appendChild(descSection);
    this.modal.appendChild(agentSection);
    this.modal.appendChild(depsSection);
    this.modal.appendChild(tagsSection);
    this.modal.appendChild(checklistSection);
    this.modal.appendChild(timeSection);
    this.modal.appendChild(commentsSection);
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
