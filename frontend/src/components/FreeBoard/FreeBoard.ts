import { Idea } from '../../types';
import { eventBus } from '../../utils/EventBus';
import { EVENTS } from '../../utils/constants';
import { createElement } from '../../utils/helpers';
import { appState } from '../../state/AppState';

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

  constructor(parentElement: HTMLElement) {
    this.container = createElement('div', { className: 'freeboard-container' });
    this.container.setAttribute('data-testid', 'freeboard');
    parentElement.appendChild(this.container);
    this.render();
    this.setupListeners();
  }

  // ── Lifecycle ────────────────────────────────────────────────

  private setupListeners(): void {
    this.unsubscribers.push(
      eventBus.on(EVENTS.IDEA_ADDED, () => this.renderGrid())
    );
    this.unsubscribers.push(
      eventBus.on(EVENTS.IDEA_DELETED, () => this.renderGrid())
    );
    this.unsubscribers.push(
      eventBus.on(EVENTS.IDEA_SUGGESTION, (data: unknown) => {
        const suggestion = data as { content: string };
        if (suggestion.content) {
          appState.addIdea(suggestion.content, 'analyzer');
          eventBus.emit(EVENTS.TOAST_SHOW, {
            message: '💡 Note captured',
            type: 'info',
            duration: 2000,
          });
        }
      })
    );
  }

  // ── Render shell ──────────────────────────────────────────────

  private render(): void {
    this.container.innerHTML = '';

    // Header
    const header = createElement('div', { className: 'freeboard-header' });
    const backBtn = createElement('button', { className: 'freeboard-back-btn', title: 'Back to Chat' }, '← Chat');
    backBtn.addEventListener('click', () => appState.setView('chat'));
    const title = createElement('h3', {}, '📝 Notes & Reminders');
    const addBtn = createElement('button', { className: 'freeboard-add-btn' }, '+ Add Note');
    addBtn.setAttribute('data-testid', 'freeboard-add-btn');
    addBtn.addEventListener('click', () => this.toggleForm());
    header.appendChild(backBtn);
    header.appendChild(title);
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

    const ideas = appState.getIdeas() || [];

    if (ideas.length === 0) {
      const empty = createElement('div', { className: 'freeboard-empty' });
      const icon = createElement('div', { className: 'freeboard-empty-icon' }, '🗒️');
      const msg = createElement('div', {}, 'No notes yet. Add one!');
      empty.appendChild(icon);
      empty.appendChild(msg);
      this.grid.appendChild(empty);
    } else {
      const sorted = [...ideas].sort((a, b) => b.createdAt - a.createdAt);
      sorted.forEach(idea => {
        const card = this.createCard(idea);
        this.grid!.appendChild(card);
      });
    }
  }

  // ── Card creation ─────────────────────────────────────────────

  private createCard(idea: Idea): HTMLElement {
    const color = idea.color as CardColor | undefined;
    const body = idea.body;

    const classes = ['freeboard-card'];
    if (color) classes.push(`freeboard-card--${color}`);
    const card = createElement('div', { className: classes.join(' ') });
    card.setAttribute('data-idea-id', idea.id);

    // Title row (with optional color dot)
    const titleEl = createElement('div', { className: 'freeboard-card-title' });
    if (color) {
      const dot = createElement('span', { className: `freeboard-card-color-dot freeboard-card-color-dot--${color}` });
      titleEl.appendChild(dot);
    }
    titleEl.appendChild(document.createTextNode(idea.content));
    card.appendChild(titleEl);

    // Body (optional)
    if (body) {
      const bodyEl = createElement('div', { className: 'freeboard-card-body' }, body);
      card.appendChild(bodyEl);
    }

    // Actions (shown on hover via CSS)
    const actions = createElement('div', { className: 'freeboard-card-actions' });

    const promoteBtn = createElement('button', {
      className: 'freeboard-card-btn freeboard-card-btn--promote',
      title: 'Promote to Project',
    }, '🚀');
    promoteBtn.addEventListener('click', (e) => {
      e.stopPropagation();
      this.promoteIdea(idea);
    });

    const deleteBtn = createElement('button', {
      className: 'freeboard-card-btn freeboard-card-btn--delete',
      title: 'Delete',
    }, '✕');
    deleteBtn.addEventListener('click', (e) => {
      e.stopPropagation();
      appState.deleteIdea(idea.id);
    });

    actions.appendChild(promoteBtn);
    actions.appendChild(deleteBtn);
    card.appendChild(actions);

    return card;
  }

  // ── Promote ───────────────────────────────────────────────────

  private promoteIdea(idea: Idea): void {
    eventBus.emit(EVENTS.PROJECT_FORM_SHOW, {
      mode: 'create',
      prefillTitle: idea.content,
    });
    appState.deleteIdea(idea.id);
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
      placeholder: 'Note title...',
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

    const submitBtn = createElement('button', { className: 'freeboard-form-submit', type: 'button' }, 'Add note');
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

  private submitForm(titleInput: HTMLInputElement, bodyInput: HTMLTextAreaElement): void {
    const title = titleInput.value.trim();
    if (!title) {
      titleInput.focus();
      return;
    }
    const body = bodyInput.value.trim();
    const color = this.selectedColor;

    // addIdea returns the idea reference already stored in state
    const idea = appState.addIdea(title, 'manual');

    // Extend with optional color + body fields (both now part of Idea type)
    if (color) idea.color = color;
    if (body) idea.body = body;

    // Persist extended fields and trigger re-render
    if (color || body) {
      appState.set('ideas', appState.getIdeas());
      eventBus.emit(EVENTS.IDEA_ADDED, idea);
    }

    this.hideForm();
  }

  // ── Destroy ───────────────────────────────────────────────────

  destroy(): void {
    this.unsubscribers.forEach(unsub => unsub());
    this.container.remove();
  }
}
