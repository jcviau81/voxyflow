/**
 * MeetingNotesModal
 *
 * Flow: paste notes → extract → preview cards → select & confirm → creates cards
 */

import { createElement } from '../../utils/helpers';
import { appState } from '../../state/AppState';
import { eventBus } from '../../utils/EventBus';
import { EVENTS } from '../../utils/constants';

interface ExtractedCard {
  title: string;
  description: string;
  priority: number;
  agent_type: string;
  selected: boolean;
}

const PRIORITY_LABELS: Record<number, string> = {
  0: 'Low',
  1: 'Medium',
  2: 'High',
  3: 'Critical',
};

const PRIORITY_COLORS: Record<number, string> = {
  0: '#6c757d',
  1: '#0d6efd',
  2: '#fd7e14',
  3: '#dc3545',
};

export class MeetingNotesModal {
  private overlay: HTMLElement;
  private onClose: () => void;

  constructor(private parentElement: HTMLElement, onClose?: () => void) {
    this.onClose = onClose || (() => {});
    this.overlay = createElement('div', { className: 'meeting-notes-modal-overlay' });
    this.renderStep1();
    this.parentElement.appendChild(this.overlay);
  }

  // ─── Step 1: Paste notes ───────────────────────────────────────────────

  private renderStep1(): void {
    this.overlay.innerHTML = '';

    const modal = createElement('div', { className: 'meeting-notes-modal' });

    const header = createElement('div', { className: 'meeting-notes-modal-header' });
    const title = createElement('h3', {}, '📝 Import Meeting Notes');
    const closeBtn = createElement('button', { className: 'meeting-notes-modal-close' }, '✕');
    closeBtn.addEventListener('click', () => this.close());
    header.appendChild(title);
    header.appendChild(closeBtn);

    const body = createElement('div', { className: 'meeting-notes-modal-body' });

    const label = createElement('label', {});
    label.textContent = 'Paste your meeting notes here:';
    const textarea = createElement('textarea', {
      className: 'meeting-notes-textarea',
      placeholder: 'e.g. John will handle the login page. Sarah will review the API docs. Next week: deploy to staging...',
    }) as HTMLTextAreaElement;
    textarea.rows = 10;

    const footer = createElement('div', { className: 'meeting-notes-modal-footer' });
    const cancelBtn = createElement('button', { className: 'meeting-notes-btn meeting-notes-btn-secondary' }, 'Cancel');
    cancelBtn.addEventListener('click', () => this.close());
    const extractBtn = createElement('button', { className: 'meeting-notes-btn meeting-notes-btn-primary' }, '✨ Extract Action Items');
    extractBtn.addEventListener('click', () => {
      const notes = textarea.value.trim();
      if (!notes) {
        textarea.focus();
        return;
      }
      this.renderStep2Loading(notes);
    });

    footer.appendChild(cancelBtn);
    footer.appendChild(extractBtn);

    body.appendChild(label);
    body.appendChild(textarea);

    modal.appendChild(header);
    modal.appendChild(body);
    modal.appendChild(footer);

    this.overlay.appendChild(modal);

    // Focus textarea
    setTimeout(() => textarea.focus(), 50);

    // Close on overlay click outside modal
    this.overlay.addEventListener('click', (e) => {
      if (e.target === this.overlay) this.close();
    });
  }

  // ─── Step 2: Loading ──────────────────────────────────────────────────

  private renderStep2Loading(notes: string): void {
    this.overlay.innerHTML = '';

    const modal = createElement('div', { className: 'meeting-notes-modal' });

    const header = createElement('div', { className: 'meeting-notes-modal-header' });
    const title = createElement('h3', {}, '📝 Import Meeting Notes');
    header.appendChild(title);

    const body = createElement('div', { className: 'meeting-notes-modal-body meeting-notes-loading' });
    const spinner = createElement('div', { className: 'meeting-notes-spinner' });
    const loadingText = createElement('p', {}, '⏳ Extracting action items…');
    body.appendChild(spinner);
    body.appendChild(loadingText);

    modal.appendChild(header);
    modal.appendChild(body);
    this.overlay.appendChild(modal);

    // Call API
    this.callExtractApi(notes);
  }

  private async callExtractApi(notes: string): Promise<void> {
    const projectId = appState.get('currentProjectId');
    if (!projectId) {
      this.renderError('No project selected. Please open a project first.');
      return;
    }

    try {
      const res = await fetch(`/api/projects/${projectId}/meeting-notes`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ notes, project_id: projectId }),
      });

      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error((err as { detail?: string }).detail || `HTTP ${res.status}`);
      }

      const data = await res.json() as { cards: Omit<ExtractedCard, 'selected'>[]; summary: string };
      const cards: ExtractedCard[] = data.cards.map((c) => ({ ...c, selected: true }));
      this.renderStep3Preview(cards, data.summary);
    } catch (err) {
      this.renderError(`Failed to extract meeting notes: ${(err as Error).message}`);
    }
  }

  // ─── Step 3: Preview & select ────────────────────────────────────────

  private renderStep3Preview(cards: ExtractedCard[], summary: string): void {
    this.overlay.innerHTML = '';

    const modal = createElement('div', { className: 'meeting-notes-modal meeting-notes-modal-wide' });

    const header = createElement('div', { className: 'meeting-notes-modal-header' });
    const title = createElement('h3', {}, `📝 ${cards.length} Action Item${cards.length !== 1 ? 's' : ''} Found`);
    const closeBtn = createElement('button', { className: 'meeting-notes-modal-close' }, '✕');
    closeBtn.addEventListener('click', () => this.close());
    header.appendChild(title);
    header.appendChild(closeBtn);

    const body = createElement('div', { className: 'meeting-notes-modal-body' });

    if (summary) {
      const summaryEl = createElement('div', { className: 'meeting-notes-summary' });
      summaryEl.textContent = `📋 ${summary}`;
      body.appendChild(summaryEl);
    }

    if (cards.length === 0) {
      const empty = createElement('p', { className: 'meeting-notes-empty' });
      empty.textContent = 'No action items found in the meeting notes.';
      body.appendChild(empty);
    } else {
      const selectAllRow = createElement('div', { className: 'meeting-notes-select-all-row' });
      const selectAllLabel = createElement('label', { className: 'meeting-card-select' });
      const selectAllCb = createElement('input', { type: 'checkbox' }) as HTMLInputElement;
      selectAllCb.checked = true;
      selectAllCb.addEventListener('change', () => {
        cards.forEach((c) => { c.selected = selectAllCb.checked; });
        checkboxes.forEach((cb) => { cb.checked = selectAllCb.checked; });
        updateConfirmBtn();
      });
      selectAllLabel.appendChild(selectAllCb);
      selectAllLabel.appendChild(document.createTextNode(' Select all'));
      selectAllRow.appendChild(selectAllLabel);
      body.appendChild(selectAllRow);

      const list = createElement('div', { className: 'meeting-extracted-cards' });
      const checkboxes: HTMLInputElement[] = [];

      cards.forEach((card, idx) => {
        const item = createElement('div', { className: 'meeting-card-preview' });

        const checkLabel = createElement('label', { className: 'meeting-card-select' });
        const cb = createElement('input', { type: 'checkbox' }) as HTMLInputElement;
        cb.checked = card.selected;
        cb.addEventListener('change', () => {
          card.selected = cb.checked;
          // Update select-all state
          const allSelected = cards.every((c) => c.selected);
          const noneSelected = cards.every((c) => !c.selected);
          selectAllCb.checked = allSelected;
          selectAllCb.indeterminate = !allSelected && !noneSelected;
          updateConfirmBtn();
        });
        checkboxes.push(cb);
        checkLabel.appendChild(cb);

        const cardInfo = createElement('div', { className: 'meeting-card-info' });

        const cardTitle = createElement('div', { className: 'meeting-card-title' });
        cardTitle.textContent = card.title;

        const cardMeta = createElement('div', { className: 'meeting-card-meta' });
        const priorityBadge = createElement('span', { className: 'meeting-card-priority' });
        priorityBadge.textContent = PRIORITY_LABELS[card.priority] || 'Medium';
        priorityBadge.style.color = PRIORITY_COLORS[card.priority] || '#0d6efd';

        const agentBadge = createElement('span', { className: 'meeting-card-agent' });
        agentBadge.textContent = `🤖 ${card.agent_type}`;

        cardMeta.appendChild(priorityBadge);
        cardMeta.appendChild(agentBadge);

        if (card.description) {
          const cardDesc = createElement('div', { className: 'meeting-card-description' });
          cardDesc.textContent = card.description;
          cardInfo.appendChild(cardTitle);
          cardInfo.appendChild(cardMeta);
          cardInfo.appendChild(cardDesc);
        } else {
          cardInfo.appendChild(cardTitle);
          cardInfo.appendChild(cardMeta);
        }

        item.appendChild(checkLabel);
        item.appendChild(cardInfo);
        list.appendChild(item);
      });

      body.appendChild(list);

      const footer = createElement('div', { className: 'meeting-notes-modal-footer' });
      const backBtn = createElement('button', { className: 'meeting-notes-btn meeting-notes-btn-secondary' }, '← Back');
      backBtn.addEventListener('click', () => this.renderStep1());

      const confirmBtn = createElement('button', { className: 'meeting-notes-btn meeting-notes-btn-primary' });
      const updateConfirmBtn = () => {
        const selectedCount = cards.filter((c) => c.selected).length;
        confirmBtn.textContent = selectedCount > 0
          ? `✅ Create ${selectedCount} Card${selectedCount !== 1 ? 's' : ''}`
          : 'Select at least one card';
        confirmBtn.disabled = selectedCount === 0;
      };
      updateConfirmBtn();

      confirmBtn.addEventListener('click', () => {
        const selected = cards.filter((c) => c.selected);
        if (selected.length > 0) {
          this.confirmCards(selected);
        }
      });

      footer.appendChild(backBtn);
      footer.appendChild(confirmBtn);

      modal.appendChild(header);
      modal.appendChild(body);
      modal.appendChild(footer);
    }

    if (cards.length === 0) {
      const footer = createElement('div', { className: 'meeting-notes-modal-footer' });
      const closeBtn2 = createElement('button', { className: 'meeting-notes-btn meeting-notes-btn-secondary' }, 'Close');
      closeBtn2.addEventListener('click', () => this.close());
      footer.appendChild(closeBtn2);
      modal.appendChild(header);
      modal.appendChild(body);
      modal.appendChild(footer);
    }

    this.overlay.appendChild(modal);
    this.overlay.addEventListener('click', (e) => {
      if (e.target === this.overlay) this.close();
    });
  }

  // ─── Step 4: Confirm & create ─────────────────────────────────────────

  private async confirmCards(cards: ExtractedCard[]): Promise<void> {
    const projectId = appState.get('currentProjectId');
    if (!projectId) return;

    // Show loading
    const confirmBtns = this.overlay.querySelectorAll('.meeting-notes-btn-primary');
    confirmBtns.forEach((b) => {
      (b as HTMLButtonElement).disabled = true;
      (b as HTMLButtonElement).textContent = '⏳ Creating…';
    });

    try {
      const payload = cards.map(({ title, description, priority, agent_type }) => ({
        title, description, priority, agent_type,
      }));

      const res = await fetch(`/api/projects/${projectId}/meeting-notes/confirm`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ cards: payload }),
      });

      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error((err as { detail?: string }).detail || `HTTP ${res.status}`);
      }

      const data = await res.json() as { created: number; card_ids: string[] };

      // Notify UI
      eventBus.emit(EVENTS.TOAST_SHOW, {
        message: `✅ Created ${data.created} card${data.created !== 1 ? 's' : ''} from meeting notes`,
        type: 'success',
        duration: 4000,
      });

      // Refresh project cards
      eventBus.emit(EVENTS.PROJECT_SELECTED, { projectId });

      this.close();
    } catch (err) {
      this.renderError(`Failed to create cards: ${(err as Error).message}`);
    }
  }

  // ─── Error state ─────────────────────────────────────────────────────

  private renderError(message: string): void {
    this.overlay.innerHTML = '';

    const modal = createElement('div', { className: 'meeting-notes-modal' });

    const header = createElement('div', { className: 'meeting-notes-modal-header' });
    const title = createElement('h3', {}, '📝 Import Meeting Notes');
    const closeBtn = createElement('button', { className: 'meeting-notes-modal-close' }, '✕');
    closeBtn.addEventListener('click', () => this.close());
    header.appendChild(title);
    header.appendChild(closeBtn);

    const body = createElement('div', { className: 'meeting-notes-modal-body' });
    const errorEl = createElement('div', { className: 'meeting-notes-error' });
    errorEl.textContent = `⚠️ ${message}`;
    body.appendChild(errorEl);

    const footer = createElement('div', { className: 'meeting-notes-modal-footer' });
    const retryBtn = createElement('button', { className: 'meeting-notes-btn meeting-notes-btn-secondary' }, '← Try Again');
    retryBtn.addEventListener('click', () => this.renderStep1());
    footer.appendChild(retryBtn);

    modal.appendChild(header);
    modal.appendChild(body);
    modal.appendChild(footer);
    this.overlay.appendChild(modal);
  }

  // ─── Lifecycle ────────────────────────────────────────────────────────

  close(): void {
    this.overlay.remove();
    this.onClose();
  }
}

/** Open the Meeting Notes modal. Convenience helper for slash command & command palette. */
export function openMeetingNotesModal(): void {
  const projectId = appState.get('currentProjectId');
  if (!projectId) {
    eventBus.emit(EVENTS.TOAST_SHOW, {
      message: '⚠️ Open a project first to import meeting notes',
      type: 'info',
      duration: 3000,
    });
    return;
  }
  new MeetingNotesModal(document.body);
}
