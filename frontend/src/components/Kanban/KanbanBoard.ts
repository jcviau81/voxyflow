import { Card, CardStatus } from '../../types';
import { eventBus } from '../../utils/EventBus';
import { EVENTS, CARD_STATUSES, CARD_STATUS_LABELS } from '../../utils/constants';
import { createElement } from '../../utils/helpers';
import { appState } from '../../state/AppState';
import { cardService } from '../../services/CardService';
import { KanbanColumn } from './KanbanColumn';

export class KanbanBoard {
  private container: HTMLElement;
  private columns: Map<string, KanbanColumn> = new Map();
  private unsubscribers: (() => void)[] = [];

  constructor(private parentElement: HTMLElement) {
    this.container = createElement('div', { className: 'kanban-board', 'data-testid': 'kanban-board' });
    this.render();
    this.setupListeners();
  }

  render(): void {
    this.container.innerHTML = '';
    this.columns.clear();

    // Header
    const header = createElement('div', { className: 'kanban-header' });
    const title = createElement('h2', { className: 'kanban-title' }, 'Kanban Board');

    const addBtn = createElement('button', { className: 'kanban-add-btn' }, '+ New Card');
    addBtn.addEventListener('click', () => this.promptNewCard());

    header.appendChild(title);
    header.appendChild(addBtn);
    this.container.appendChild(header);

    // Board with columns
    const board = createElement('div', { className: 'kanban-columns' });

    for (const status of CARD_STATUSES) {
      const column = new KanbanColumn(board, status, CARD_STATUS_LABELS[status]);
      this.columns.set(status, column);
    }

    this.container.appendChild(board);

    // Setup drag & drop on board
    this.setupDragDrop(board);

    this.parentElement.appendChild(this.container);
    this.refreshCards();
  }

  private setupListeners(): void {
    this.unsubscribers.push(
      eventBus.on(EVENTS.CARD_CREATED, () => this.refreshCards())
    );
    this.unsubscribers.push(
      eventBus.on(EVENTS.CARD_UPDATED, () => this.refreshCards())
    );
    this.unsubscribers.push(
      eventBus.on(EVENTS.CARD_DELETED, () => this.refreshCards())
    );
    this.unsubscribers.push(
      eventBus.on(EVENTS.CARD_MOVED, () => this.refreshCards())
    );
    this.unsubscribers.push(
      eventBus.on(EVENTS.PROJECT_SELECTED, () => this.refreshCards())
    );
  }

  private setupDragDrop(board: HTMLElement): void {
    board.addEventListener('dragover', (e: DragEvent) => {
      e.preventDefault();
      if (e.dataTransfer) {
        e.dataTransfer.dropEffect = 'move';
      }
    });

    board.addEventListener('drop', (e: DragEvent) => {
      e.preventDefault();
      const cardId = e.dataTransfer?.getData('text/plain');
      const target = (e.target as HTMLElement).closest('.kanban-column');
      if (cardId && target) {
        const newStatus = target.getAttribute('data-status') as CardStatus;
        if (newStatus) {
          cardService.move(cardId, newStatus);
        }
      }
    });
  }

  private refreshCards(): void {
    const projectId = appState.get('currentProjectId');
    if (!projectId) {
      this.columns.forEach((col) => col.setCards([]));
      return;
    }

    for (const status of CARD_STATUSES) {
      const cards = appState.getCardsByStatus(projectId, status);
      const column = this.columns.get(status);
      if (column) {
        column.setCards(cards);
      }
    }
  }

  private promptNewCard(): void {
    const projectId = appState.get('currentProjectId');
    if (!projectId) {
      eventBus.emit(EVENTS.TOAST_SHOW, {
        message: 'Select a project first',
        type: 'warning',
      });
      return;
    }

    eventBus.emit(EVENTS.CARD_FORM_SHOW, {
      mode: 'create',
      projectId,
    });
  }

  moveCard(cardId: string, newStatus: CardStatus): void {
    cardService.move(cardId, newStatus);
  }

  update(): void {
    this.refreshCards();
  }

  destroy(): void {
    this.unsubscribers.forEach((unsub) => unsub());
    this.unsubscribers = [];
    this.columns.forEach((col) => col.destroy());
    this.columns.clear();
    this.container.remove();
  }
}
