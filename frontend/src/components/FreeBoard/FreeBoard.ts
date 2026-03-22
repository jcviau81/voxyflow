import { Card } from '../../types';
import { eventBus } from '../../utils/EventBus';
import { EVENTS } from '../../utils/constants';
import { createElement } from '../../utils/helpers';
import { appState } from '../../state/AppState';
import { mainBoardService } from '../../services/MainBoardService';
import { CardDetailModal } from '../shared/CardDetailModal';

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

export class FreeBoard {
  private container: HTMLElement;
  private grid: HTMLElement | null = null;
  private showingForm = false;
  private selectedColor: CardColor | null = null;
  private unsubscribers: (() => void)[] = [];
  private cardDetailModal: CardDetailModal;
  private initialLoadDone = false;

  constructor(parentElement: HTMLElement) {
    this.container = createElement('div', { className: 'freeboard-container' });
    this.container.setAttribute('data-testid', 'freeboard');
    parentElement.appendChild(this.container);
    // Mount card detail modal once on body so it overlays everything
    this.cardDetailModal = new CardDetailModal(document.body);
    this.cardDetailModal.onDeleted = () => this.renderGrid();
    this.cardDetailModal.onUpdated = () => this.renderGrid();
    this.render();
    this.setupListeners();
    this.loadCards();
  }

  // ── Initial load & migration ─────────────────────────────────

  private async loadCards(): Promise<void> {
    // Migrate old localStorage ideas on first load
    const ideas = appState.getIdeas();
    if (ideas.length > 0) {
      await mainBoardService.migrateIdeasToCards();
    }
    // Fetch from API
    await mainBoardService.ensureLoaded();
    this.initialLoadDone = true;
    this.renderGrid();
  }

  // ── Lifecycle ────────────────────────────────────────────────

  private setupListeners(): void {
    this.unsubscribers.push(
      eventBus.on(EVENTS.MAIN_BOARD_UPDATED, () => this.renderGrid())
    );
    this.unsubscribers.push(
      eventBus.on(EVENTS.MAIN_BOARD_CARD_CREATED, () => this.renderGrid())
    );
    this.unsubscribers.push(
      eventBus.on(EVENTS.MAIN_BOARD_CARD_DELETED, () => this.renderGrid())
    );
    // Legacy: still listen for analyzer suggestions
    this.unsubscribers.push(
      eventBus.on(EVENTS.IDEA_SUGGESTION, (data: unknown) => {
        const suggestion = data as { content: string };
        if (suggestion.content) {
          mainBoardService.createCard(suggestion.content).then(() => {
            eventBus.emit(EVENTS.TOAST_SHOW, {
              message: '💡 Card created',
              type: 'info',
              duration: 2000,
            });
          });
        }
      })
    );
  }

  // ── Render shell ──────────────────────────────────────────────

  private render(): void {
    this.container.innerHTML = '';

    // Header — same pattern as KanbanBoard
    const header = createElement('div', { className: 'freeboard-header kanban-header' });

    // View toggle (like Chat/Kanban in project view)
    const viewToggle = createElement('div', { className: 'view-toggle' });
    const chatBtn = createElement('button', { className: 'view-btn', 'data-view': 'chat' }, '💬 Chat');
    chatBtn.addEventListener('click', () => appState.setView('chat'));
    const boardBtn = createElement('button', { className: 'view-btn active', 'data-view': 'freeboard' }, '📝 Board');
    viewToggle.appendChild(chatBtn);
    viewToggle.appendChild(boardBtn);

    const addBtn = createElement('button', { className: 'freeboard-add-btn kanban-add-btn' }, '+ Add Card');
    addBtn.setAttribute('data-testid', 'freeboard-add-btn');
    addBtn.addEventListener('click', () => this.toggleForm());

    header.appendChild(viewToggle);
    header.appendChild(addBtn);
    this.container.appendChild(header);

    // Grid
    this.grid = createElement('div', { className: 'freeboard-grid' });
    this.container.appendChild(this.grid);

    this.renderGrid();
  }

  // ── Grid rendering ────────────────────────────────────────────

  private renderGrid(): void {
    if (!this.grid) return;

    // Keep the form element if visible, remove everything else
    const formEl = this.grid.querySelector('.freeboard-add-form');
    this.grid.innerHTML = '';

    // Re-attach form if it was showing
    if (this.showingForm && formEl) {
      this.grid.appendChild(formEl);
    }

    const cards = appState.getMainBoardCards();

    if (cards.length === 0) {
      const empty = createElement('div', { className: 'freeboard-empty' });
      const icon = createElement('div', { className: 'freeboard-empty-icon' }, '🗒️');
      const msg = createElement('div', {}, this.initialLoadDone ? 'No cards yet. Add one!' : 'Loading...');
      empty.appendChild(icon);
      empty.appendChild(msg);
      this.grid.appendChild(empty);
    } else {
      const sorted = [...cards].sort((a, b) => b.createdAt - a.createdAt);
      sorted.forEach(card => {
        const cardEl = this.createCardElement(card);
        this.grid!.appendChild(cardEl);
      });
    }
  }

  // ── Card element creation ─────────────────────────────────────

  private createCardElement(card: Card): HTMLElement {
    const color = card.color as CardColor | undefined;

    const classes = ['freeboard-card'];
    if (color) classes.push(`freeboard-card--${color}`);
    const el = createElement('div', { className: classes.join(' ') });
    el.setAttribute('data-card-id', card.id);
    el.style.cursor = 'pointer';
    el.addEventListener('click', (e) => {
      // Only open modal if not clicking an action button
      const target = e.target as HTMLElement;
      if (target.closest('.freeboard-card-btn')) return;
      this.cardDetailModal.open(card);
    });

    // Title row (with optional color dot)
    const titleEl = createElement('div', { className: 'freeboard-card-title' });
    if (color) {
      const dot = createElement('span', { className: `freeboard-card-color-dot freeboard-card-color-dot--${color}` });
      titleEl.appendChild(dot);
    }
    titleEl.appendChild(document.createTextNode(card.title));
    el.appendChild(titleEl);

    // Description (optional)
    if (card.description) {
      const bodyEl = createElement('div', { className: 'freeboard-card-body' }, card.description);
      el.appendChild(bodyEl);
    }

    // Checklist progress (if any)
    if (card.checklistProgress && card.checklistProgress.total > 0) {
      const prog = card.checklistProgress;
      const progressEl = createElement('div', { className: 'freeboard-card-progress' },
        `✅ ${prog.completed}/${prog.total}`);
      el.appendChild(progressEl);
    }

    // Actions (shown on hover via CSS)
    const actions = createElement('div', { className: 'freeboard-card-actions' });

    const promoteBtn = createElement('button', {
      className: 'freeboard-card-btn freeboard-card-btn--promote',
      title: 'Assign to Project',
    }, '🚀');
    promoteBtn.addEventListener('click', (e) => {
      e.stopPropagation();
      this.promoteCard(card);
    });

    const deleteBtn = createElement('button', {
      className: 'freeboard-card-btn freeboard-card-btn--delete',
      title: 'Delete',
    }, '✕');
    deleteBtn.addEventListener('click', (e) => {
      e.stopPropagation();
      mainBoardService.deleteCard(card.id);
    });

    actions.appendChild(promoteBtn);
    actions.appendChild(deleteBtn);
    el.appendChild(actions);

    return el;
  }

  // ── Promote (assign to project) ───────────────────────────────

  private promoteCard(card: Card): void {
    // Show project form pre-filled (creates project and assigns card)
    eventBus.emit(EVENTS.PROJECT_FORM_SHOW, {
      mode: 'create',
      prefillTitle: card.title,
    });
    // Note: The card stays on main board; user can assign it after creating/selecting a project.
    // For a more advanced UX, a project picker modal would be needed.
  }

  // ── Add form ──────────────────────────────────────────────────

  private toggleForm(): void {
    if (this.showingForm) {
      this.hideForm();
    } else {
      this.showForm();
    }
  }

  private showForm(): void {
    if (this.showingForm || !this.grid) return;
    this.showingForm = true;
    this.selectedColor = null;

    const form = createElement('div', { className: 'freeboard-add-form' });
    form.setAttribute('data-role', 'add-form');

    // Title input
    const titleInput = createElement('input', {
      type: 'text',
      className: 'freeboard-add-form-title',
      placeholder: 'Card title...',
    }) as HTMLInputElement;

    // Body textarea
    const bodyInput = createElement('textarea', {
      className: 'freeboard-add-form-body',
      placeholder: 'Details (optional)...',
      rows: '3',
    }) as HTMLTextAreaElement;

    // Color row
    const colorRow = createElement('div', { className: 'freeboard-color-row' });
    const colorLabel = createElement('span', { className: 'freeboard-color-label' }, 'Color:');
    colorRow.appendChild(colorLabel);

    let selectedSwatch: HTMLElement | null = null;

    COLOR_OPTIONS.forEach(({ value, label }) => {
      const swatchClass = value
        ? `freeboard-color-swatch freeboard-color-swatch--${value}`
        : 'freeboard-color-swatch freeboard-color-swatch--none selected';
      const swatch = createElement('button', { className: swatchClass, title: label, type: 'button' });
      if (!value) selectedSwatch = swatch; // default = none selected

      swatch.addEventListener('click', () => {
        // Deselect previous
        if (selectedSwatch) selectedSwatch.classList.remove('selected');
        swatch.classList.add('selected');
        selectedSwatch = swatch;
        this.selectedColor = value;
      });

      colorRow.appendChild(swatch);
    });

    // Actions row
    const actionsRow = createElement('div', { className: 'freeboard-add-form-actions' });

    const cancelBtn = createElement('button', { className: 'freeboard-form-cancel', type: 'button' }, 'Cancel');
    cancelBtn.addEventListener('click', () => this.hideForm());

    const submitBtn = createElement('button', { className: 'freeboard-form-submit', type: 'button' }, 'Add card');
    submitBtn.addEventListener('click', () => this.submitForm(titleInput, bodyInput));

    actionsRow.appendChild(cancelBtn);
    actionsRow.appendChild(submitBtn);

    form.appendChild(titleInput);
    form.appendChild(bodyInput);
    form.appendChild(colorRow);
    form.appendChild(actionsRow);

    // Key handlers
    titleInput.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        this.submitForm(titleInput, bodyInput);
      } else if (e.key === 'Escape') {
        this.hideForm();
      }
    });
    bodyInput.addEventListener('keydown', (e) => {
      if (e.key === 'Escape') this.hideForm();
    });

    // Prepend form to grid (above cards)
    this.grid.insertBefore(form, this.grid.firstChild);
    setTimeout(() => titleInput.focus(), 50);
  }

  private hideForm(): void {
    if (!this.showingForm || !this.grid) return;
    this.showingForm = false;
    this.selectedColor = null;
    const form = this.grid.querySelector('[data-role="add-form"]');
    if (form) form.remove();
  }

  private async submitForm(titleInput: HTMLInputElement, bodyInput: HTMLTextAreaElement): Promise<void> {
    const title = titleInput.value.trim();
    if (!title) {
      titleInput.focus();
      return;
    }
    const description = bodyInput.value.trim();
    const color = this.selectedColor;

    // Create via API
    await mainBoardService.createCard(title, description || undefined, color || undefined);

    this.hideForm();
  }

  // ── Destroy ───────────────────────────────────────────────────

  destroy(): void {
    this.unsubscribers.forEach(unsub => unsub());
    this.cardDetailModal.destroy();
    this.container.remove();
  }
}
