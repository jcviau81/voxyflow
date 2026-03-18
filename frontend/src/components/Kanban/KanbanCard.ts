import { Card } from '../../types';
import { createElement, truncate } from '../../utils/helpers';
import { AGENT_PERSONAS, AGENT_TYPE_EMOJI } from '../../utils/constants';
import { eventBus } from '../../utils/EventBus';
import { EVENTS } from '../../utils/constants';
import { appState } from '../../state/AppState';

export class KanbanCard {
  private element: HTMLElement;
  private titleEl: HTMLElement | null = null;

  constructor(private parentElement: HTMLElement, private card: Card) {
    this.element = createElement('div', {
      className: 'kanban-card',
      draggable: 'true',
      'data-card-id': card.id,
    });
    this.render();
    this.setupDrag();
  }

  private escapeHtml(text: string): string {
    return text
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;');
  }

  private highlightText(text: string, query: string): string {
    if (!query) return this.escapeHtml(text);
    const escaped = this.escapeHtml(text);
    const escapedQuery = query.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
    return escaped.replace(
      new RegExp(escapedQuery, 'gi'),
      (match) => `<mark class="search-highlight">${match}</mark>`
    );
  }

  render(): void {
    this.element.innerHTML = '';

    // Title
    const title = createElement('div', { className: 'kanban-card-title' }, this.card.title);
    this.titleEl = title;

    // Description preview
    const desc = createElement(
      'div',
      { className: 'kanban-card-desc' },
      truncate(this.card.description, 80)
    );

    // Footer with metadata
    const footer = createElement('div', { className: 'kanban-card-footer' });

    // Agent badge — show emoji for non-ember agent types
    const agentType = this.card.agentType;
    if (agentType && agentType !== 'ember') {
      const emoji = AGENT_TYPE_EMOJI[agentType];
      if (emoji) {
        const badge = createElement('span', { className: 'agent-badge', title: agentType }, emoji);
        footer.appendChild(badge);
      }
    } else if (!agentType && this.card.assignedAgent) {
      // Fallback: legacy assignedAgent field
      const persona = AGENT_PERSONAS[this.card.assignedAgent];
      if (persona) {
        const agent = createElement('span', { className: 'agent-badge' }, persona.emoji);
        footer.appendChild(agent);
      }
    }

    // Tags
    if (this.card.tags.length > 0) {
      const tagsEl = createElement('div', { className: 'kanban-card-tags' });
      this.card.tags.slice(0, 3).forEach((tag) => {
        const tagEl = createElement('span', { className: 'kanban-card-tag' }, tag);
        tagsEl.appendChild(tagEl);
      });
      footer.appendChild(tagsEl);
    }

    // Dependencies indicator
    if (this.card.dependencies.length > 0) {
      const deps = createElement(
        'span',
        { className: 'kanban-card-deps' },
        `🔗 ${this.card.dependencies.length}`
      );
      footer.appendChild(deps);
    }

    this.element.appendChild(title);
    if (this.card.description) {
      this.element.appendChild(desc);
    }
    this.element.appendChild(footer);

    // Click to edit via inline form
    this.element.addEventListener('click', () => {
      appState.selectCard(this.card.id);
      eventBus.emit(EVENTS.CARD_FORM_SHOW, {
        mode: 'edit',
        card: this.card,
        projectId: this.card.projectId,
      });
    });

    this.parentElement.appendChild(this.element);
  }

  private setupDrag(): void {
    this.element.addEventListener('dragstart', (e: DragEvent) => {
      if (e.dataTransfer) {
        e.dataTransfer.setData('text/plain', this.card.id);
        e.dataTransfer.effectAllowed = 'move';
      }
      this.element.classList.add('dragging');
    });

    this.element.addEventListener('dragend', () => {
      this.element.classList.remove('dragging');
    });
  }

  setHighlight(query: string): void {
    if (!this.titleEl) return;
    this.titleEl.innerHTML = this.highlightText(this.card.title, query);
  }

  /**
   * Apply filter criteria. Returns true if card is visible.
   * Hides/shows via display style.
   */
  applyFilter(query: string, priorityFilter: number | null, agentFilter: string | null): boolean {
    const titleMatch = query
      ? this.card.title.toLowerCase().includes(query.toLowerCase())
      : true;
    const priorityMatch = priorityFilter !== null
      ? this.card.priority === priorityFilter
      : true;
    const agentMatch = agentFilter
      ? (this.card.agentType || 'ember') === agentFilter
      : true;

    const visible = titleMatch && priorityMatch && agentMatch;
    this.element.style.display = visible ? '' : 'none';

    // Apply highlight when visible
    if (visible) {
      this.setHighlight(query);
    }

    return visible;
  }

  getCardData(): Card {
    return this.card;
  }

  update(card: Card): void {
    this.card = card;
    this.render();
  }

  destroy(): void {
    this.element.remove();
  }
}
