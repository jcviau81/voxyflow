import { Card } from '../../types';
import { createElement } from '../../utils/helpers';
import { KanbanCard } from './KanbanCard';

export class KanbanColumn {
  private element: HTMLElement;
  private cardContainer: HTMLElement;
  private countEl: HTMLElement;
  private cardComponents: Map<string, KanbanCard> = new Map();

  constructor(
    private parentElement: HTMLElement,
    private status: string,
    private label: string
  ) {
    this.element = createElement('div', {
      className: 'kanban-column',
      'data-status': status,
      'data-testid': 'kanban-column',
    });

    const header = createElement('div', { className: 'kanban-column-header' });
    const title = createElement('span', { className: 'kanban-column-title' }, label);
    this.countEl = createElement('span', { className: 'kanban-column-count' }, '0');
    header.appendChild(title);
    header.appendChild(this.countEl);

    this.cardContainer = createElement('div', { className: 'kanban-column-cards' });

    // Drop zone styling
    this.element.addEventListener('dragenter', (e) => {
      e.preventDefault();
      this.element.classList.add('drag-over');
    });
    this.element.addEventListener('dragleave', (e: DragEvent) => {
      // Only remove highlight when truly leaving the column (not just moving onto a child)
      if (!this.element.contains(e.relatedTarget as Node)) {
        this.element.classList.remove('drag-over');
      }
    });
    this.element.addEventListener('dragover', (e) => {
      e.preventDefault();
    });
    this.element.addEventListener('drop', () => {
      this.element.classList.remove('drag-over');
    });

    this.element.appendChild(header);
    this.element.appendChild(this.cardContainer);
    this.parentElement.appendChild(this.element);
  }

  setCards(cards: Card[]): void {
    // Clear existing
    this.cardComponents.forEach((c) => c.destroy());
    this.cardComponents.clear();
    this.cardContainer.innerHTML = '';

    // Render new cards
    cards
      .sort((a, b) => b.priority - a.priority || b.updatedAt - a.updatedAt)
      .forEach((card) => {
        const kanbanCard = new KanbanCard(this.cardContainer, card);
        this.cardComponents.set(card.id, kanbanCard);
      });

    this.countEl.textContent = cards.length.toString();
  }

  applyFilter(
    query: string,
    priorityFilter: number | null,
    agentFilter: string | null,
    tagFilter: string | null = null,
  ): number {
    let visibleCount = 0;
    this.cardComponents.forEach((card) => {
      if (card.applyFilter(query, priorityFilter, agentFilter, tagFilter)) {
        visibleCount++;
      }
    });
    return visibleCount;
  }

  getCardComponents(): Map<string, KanbanCard> {
    return this.cardComponents;
  }

  destroy(): void {
    this.cardComponents.forEach((c) => c.destroy());
    this.cardComponents.clear();
    this.element.remove();
  }
}
