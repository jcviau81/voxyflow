import { Card, CardStatus, AgentPersona } from '../types';
import { appState } from '../state/AppState';
import { apiClient } from './ApiClient';
import { eventBus } from '../utils/EventBus';
import { EVENTS } from '../utils/constants';

export class CardService {
  private unsubscribers: (() => void)[] = [];

  constructor() {
    this.setupHandlers();
  }

  private setupHandlers(): void {
    // Sync card updates from backend
    this.unsubscribers.push(
      apiClient.on('card:sync', (payload) => {
        const { action, card } = payload as { action: string; card: Card };
        switch (action) {
          case 'created':
            if (!appState.getCard(card.id)) {
              const cards = [...appState.get('cards'), card];
              appState.set('cards', cards);
            }
            break;
          case 'updated':
            appState.updateCard(card.id, card);
            break;
          case 'deleted':
            appState.deleteCard(card.id);
            break;
          case 'moved':
            appState.moveCard(card.id, card.status);
            break;
        }
      })
    );

    // Handle bulk sync
    this.unsubscribers.push(
      apiClient.on('card:list', (payload) => {
        const { cards } = payload as { cards: Card[] };
        appState.set('cards', cards);
      })
    );
  }

  create(data: {
    title: string;
    description?: string;
    projectId: string;
    status?: CardStatus;
    assignedAgent?: AgentPersona;
    tags?: string[];
    priority?: number;
  }): Card {
    const card = appState.addCard({
      title: data.title,
      description: data.description || '',
      status: data.status || 'idea',
      projectId: data.projectId,
      assignedAgent: data.assignedAgent,
      dependencies: [],
      tags: data.tags || [],
      priority: data.priority || 0,
    });

    apiClient.send('card:create', {
      id: card.id,
      title: card.title,
      description: card.description,
      status: card.status,
      projectId: card.projectId,
      assignedAgent: card.assignedAgent,
      tags: card.tags,
      priority: card.priority,
    });

    return card;
  }

  update(id: string, updates: Partial<Card>): void {
    appState.updateCard(id, updates);
    apiClient.send('card:update', { id, updates });
  }

  delete(id: string): void {
    appState.deleteCard(id);
    apiClient.send('card:delete', { id });
  }

  move(cardId: string, newStatus: CardStatus): void {
    appState.moveCard(cardId, newStatus);
    apiClient.send('card:move', { id: cardId, status: newStatus });
  }

  assignAgent(cardId: string, agent: AgentPersona | undefined): void {
    this.update(cardId, { assignedAgent: agent });
  }

  addDependency(cardId: string, dependencyId: string): void {
    const card = appState.getCard(cardId);
    if (card && !card.dependencies.includes(dependencyId)) {
      this.update(cardId, {
        dependencies: [...card.dependencies, dependencyId],
      });
    }
  }

  removeDependency(cardId: string, dependencyId: string): void {
    const card = appState.getCard(cardId);
    if (card) {
      this.update(cardId, {
        dependencies: card.dependencies.filter((d) => d !== dependencyId),
      });
    }
  }

  addTag(cardId: string, tag: string): void {
    const card = appState.getCard(cardId);
    if (card && !card.tags.includes(tag)) {
      this.update(cardId, { tags: [...card.tags, tag] });
    }
  }

  removeTag(cardId: string, tag: string): void {
    const card = appState.getCard(cardId);
    if (card) {
      this.update(cardId, { tags: card.tags.filter((t) => t !== tag) });
    }
  }

  list(projectId: string): Card[] {
    return appState.getCardsByProject(projectId);
  }

  listByStatus(projectId: string, status: CardStatus): Card[] {
    return appState.getCardsByStatus(projectId, status);
  }

  get(id: string): Card | undefined {
    return appState.getCard(id);
  }

  select(id: string | null): void {
    appState.selectCard(id);
  }

  requestSync(projectId: string): void {
    apiClient.send('card:list-request', { projectId });
  }

  destroy(): void {
    this.unsubscribers.forEach((unsub) => unsub());
    this.unsubscribers = [];
  }
}

export const cardService = new CardService();
