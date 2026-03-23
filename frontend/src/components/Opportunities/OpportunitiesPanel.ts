import { CardSuggestion } from '../../types';
import { eventBus } from '../../utils/EventBus';
import { EVENTS } from '../../utils/constants';
import { createElement } from '../../utils/helpers';
import { appState } from '../../state/AppState';

export class OpportunitiesPanel {
  private container: HTMLElement;
  private opportunities: CardSuggestion[] = [];
  private unsubscribers: (() => void)[] = [];

  constructor(parentElement: HTMLElement) {
    this.container = createElement('div', { className: 'opportunities-panel' });
    this.container.setAttribute('data-testid', 'opportunities-panel');
    parentElement.appendChild(this.container);
    this.render();
    this.setupListeners();
  }

  private setupListeners(): void {
    this.unsubscribers.push(
      eventBus.on(EVENTS.CARD_SUGGESTION, (data: unknown) => {
        this.addOpportunity(data as CardSuggestion);
      })
    );
  }

  addOpportunity(suggestion: CardSuggestion): void {
    this.opportunities.push(suggestion);
    this.render();
    this.emitBadgeCount();
  }

  removeOpportunity(id: string): void {
    this.opportunities = this.opportunities.filter((o) => o.id !== id);
    this.render();
    this.emitBadgeCount();
  }

  private emitBadgeCount(): void {
    eventBus.emit(EVENTS.OPPORTUNITIES_COUNT, this.opportunities.length);
  }

  render(): void {
    this.container.innerHTML = `
      <div class="opportunities-header">
        <h3>💡 Opportunities</h3>
        <span class="opportunities-badge">${this.opportunities.length}</span>
      </div>
      <div class="opportunities-list">
        ${
          this.opportunities.length === 0
            ? '<div class="opportunities-empty">No suggestions yet. Start chatting!</div>'
            : this.opportunities.map((o) => this.renderCard(o)).join('')
        }
      </div>
    `;

    // Bind accept buttons
    this.container.querySelectorAll('.opp-accept').forEach((btn) => {
      btn.addEventListener('click', (e) => {
        const id = (e.currentTarget as HTMLElement).dataset.id;
        if (id) this.acceptOpportunity(id);
      });
    });

    // Bind dismiss buttons
    this.container.querySelectorAll('.opp-dismiss').forEach((btn) => {
      btn.addEventListener('click', (e) => {
        const id = (e.currentTarget as HTMLElement).dataset.id;
        if (id) this.removeOpportunity(id);
      });
    });
  }

  private renderCard(opp: CardSuggestion): string {
    return `
      <div class="opportunity-card" data-id="${opp.id}">
        <div class="opp-agent">${opp.agentEmoji || '🤖'} ${opp.agentName || 'Ember'}</div>
        <div class="opp-title">${opp.title}</div>
        ${opp.description ? `<div class="opp-description">${opp.description}</div>` : ''}
        <div class="opp-actions">
          <button class="opp-accept" data-id="${opp.id}">Create Card</button>
          <button class="opp-dismiss" data-id="${opp.id}">✕</button>
        </div>
      </div>
    `;
  }

  private acceptOpportunity(id: string): void {
    const opp = this.opportunities.find((o) => o.id === id);
    if (opp) {
      const projectId = appState.get('currentProjectId');
      if (projectId) {
        eventBus.emit(EVENTS.MODAL_OPEN, { type: 'card-detail', mode: 'create', projectId, prefillTitle: opp.title, prefillAgentType: opp.agentType });
      } else {
        eventBus.emit(EVENTS.CREATE_CARD_FROM_SUGGESTION, {
          title: opp.title,
          description: opp.description,
          agentType: opp.agentType,
          agentName: opp.agentName,
        });
      }
      this.removeOpportunity(id);
    }
  }

  destroy(): void {
    this.unsubscribers.forEach((unsub) => unsub());
    this.unsubscribers = [];
    this.container.remove();
  }
}
