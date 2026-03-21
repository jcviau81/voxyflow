import { Idea } from '../../types';
import { eventBus } from '../../utils/EventBus';
import { EVENTS } from '../../utils/constants';
import { createElement } from '../../utils/helpers';
import { appState } from '../../state/AppState';

export class IdeaBoard {
  private container: HTMLElement;
  private listEl: HTMLElement | null = null;
  private emptyEl: HTMLElement | null = null;
  private inputRow: HTMLElement | null = null;
  private showingInput = false;
  private unsubscribers: (() => void)[] = [];

  constructor(parentElement: HTMLElement) {
    this.container = createElement('div', { className: 'idea-board' });
    this.container.setAttribute('data-testid', 'idea-board');
    parentElement.appendChild(this.container);
    this.render();
    this.setupListeners();
  }

  private setupListeners(): void {
    this.unsubscribers.push(
      eventBus.on(EVENTS.IDEA_ADDED, () => {
        this.renderList();
      })
    );

    this.unsubscribers.push(
      eventBus.on(EVENTS.IDEA_DELETED, () => {
        this.renderList();
      })
    );

    this.unsubscribers.push(
      eventBus.on(EVENTS.IDEA_SUGGESTION, (data: unknown) => {
        const suggestion = data as { content: string };
        if (suggestion.content) {
          appState.addIdea(suggestion.content, 'analyzer');
          eventBus.emit(EVENTS.TOAST_SHOW, {
            message: '💡 Idea captured',
            type: 'info',
            duration: 2000,
          });
        }
      })
    );
  }

  private render(): void {
    this.container.innerHTML = '';

    // Header
    const header = createElement('div', { className: 'idea-board-header' });
    const title = createElement('h3', {}, '💡 Ideas & Cards');
    const addBtn = createElement('button', { className: 'btn-sm' }, '+ Add');
    addBtn.setAttribute('data-testid', 'add-idea-btn');
    addBtn.addEventListener('click', () => this.toggleInput());
    header.appendChild(title);
    header.appendChild(addBtn);

    // List
    this.listEl = createElement('div', { className: 'idea-list' });

    // Empty state
    this.emptyEl = createElement('div', { className: 'idea-empty' }, 'No ideas yet. Start brainstorming!');

    this.container.appendChild(header);
    this.container.appendChild(this.listEl);
    this.container.appendChild(this.emptyEl);

    this.renderList();
  }

  private toggleInput(): void {
    if (this.showingInput) {
      this.hideInput();
    } else {
      this.showInput();
    }
  }

  private showInput(): void {
    if (this.showingInput || !this.listEl) return;
    this.showingInput = true;

    this.inputRow = createElement('div', { className: 'idea-input-row' });
    const input = createElement('input', {
      type: 'text',
      placeholder: 'Quick card or idea...',
      className: 'idea-input',
    }) as HTMLInputElement;

    const addBtn = createElement('button', { className: 'btn-sm' }, 'Add');

    const submit = () => {
      const value = input.value.trim();
      if (value) {
        appState.addIdea(value, 'manual');
        input.value = '';
        this.hideInput();
      }
    };

    input.addEventListener('keydown', (e) => {
      if (e.key === 'Enter') {
        e.preventDefault();
        submit();
      } else if (e.key === 'Escape') {
        this.hideInput();
      }
    });

    addBtn.addEventListener('click', submit);

    this.inputRow.appendChild(input);
    this.inputRow.appendChild(addBtn);
    this.listEl.insertBefore(this.inputRow, this.listEl.firstChild);

    // Focus input
    setTimeout(() => input.focus(), 50);
  }

  private hideInput(): void {
    if (!this.showingInput || !this.inputRow) return;
    this.showingInput = false;
    this.inputRow.remove();
    this.inputRow = null;
  }

  private renderList(): void {
    if (!this.listEl || !this.emptyEl) return;

    // Remove all cards but keep input row if present
    const cards = this.listEl.querySelectorAll('.idea-card');
    cards.forEach(c => c.remove());

    const ideas = appState.getIdeas() || [];

    if (ideas.length === 0) {
      this.emptyEl.style.display = 'block';
    } else {
      this.emptyEl.style.display = 'none';
      // Render newest first
      const sorted = [...ideas].sort((a, b) => b.createdAt - a.createdAt);
      sorted.forEach(idea => {
        const card = this.createIdeaCard(idea);
        this.listEl!.appendChild(card);
      });
    }
  }

  private createIdeaCard(idea: Idea): HTMLElement {
    const card = createElement('div', { className: 'idea-card' });

    const content = createElement('div', { className: 'idea-content' }, idea.content);

    const actions = createElement('div', { className: 'idea-actions' });

    const promoteBtn = createElement('button', {
      className: 'idea-promote',
      title: 'Promote to Project',
    }, '🚀');
    promoteBtn.addEventListener('click', () => this.promoteIdea(idea));

    const deleteBtn = createElement('button', {
      className: 'idea-delete',
      title: 'Delete',
    }, '✕');
    deleteBtn.addEventListener('click', () => {
      appState.deleteIdea(idea.id);
    });

    actions.appendChild(promoteBtn);
    actions.appendChild(deleteBtn);

    card.appendChild(content);
    card.appendChild(actions);

    return card;
  }

  private promoteIdea(idea: Idea): void {
    // Open project creation form with idea content as title
    eventBus.emit(EVENTS.PROJECT_FORM_SHOW, {
      mode: 'create',
      prefillTitle: idea.content,
    });
    // Delete idea after promoting
    appState.deleteIdea(idea.id);
  }

  destroy(): void {
    this.unsubscribers.forEach(unsub => unsub());
    this.container.remove();
  }
}
