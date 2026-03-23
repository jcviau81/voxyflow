import { Card, CardStatus, AgentPersona, AgentInfo } from '../types';
import { appState } from '../state/AppState';
import { apiClient } from './ApiClient';
import { eventBus } from '../utils/EventBus';
import { EVENTS, API_URL } from '../utils/constants';

export class CardService {
  private unsubscribers: (() => void)[] = [];
  private agentsCache: AgentInfo[] | null = null;

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

  async create(data: {
    title: string;
    description?: string;
    projectId: string;
    status?: CardStatus;
    assignedAgent?: AgentPersona;
    tags?: string[];
    priority?: number;
  }): Promise<Card> {
    // Optimistic local update
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

    // Persist via REST
    try {
      const baseUrl = API_URL || '';
      const response = await fetch(`${baseUrl}/api/projects/${data.projectId}/cards`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          title: card.title,
          description: card.description,
          status: card.status,
          priority: card.priority,
        }),
      });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const raw = await response.json();
      // Update local card with server-assigned id and fields
      appState.updateCard(card.id, {
        id: raw.id,
        createdAt: raw.created_at ? new Date(raw.created_at).getTime() : card.createdAt,
        updatedAt: raw.updated_at ? new Date(raw.updated_at).getTime() : card.updatedAt,
      });
      card.id = raw.id;
    } catch (error) {
      console.error('[CardService] create REST error:', error);
    }

    return card;
  }

  async update(id: string, updates: Partial<Card>): Promise<void> {
    appState.updateCard(id, updates);
    try {
      const baseUrl = API_URL || '';
      const patchBody: Record<string, unknown> = {};
      if (updates.title !== undefined) patchBody.title = updates.title;
      if (updates.description !== undefined) patchBody.description = updates.description;
      if (updates.status !== undefined) patchBody.status = updates.status;
      if (updates.priority !== undefined) patchBody.priority = updates.priority;
      if (updates.assignedAgent !== undefined) patchBody.agent_assigned = updates.assignedAgent;
      if (updates.agentType !== undefined) patchBody.agent_type = updates.agentType;
      if (updates.recurrence !== undefined) patchBody.recurrence = updates.recurrence;
      if (Object.keys(patchBody).length > 0) {
        const response = await fetch(`${baseUrl}/api/cards/${id}`, {
          method: 'PATCH',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(patchBody),
        });
        if (!response.ok) console.error(`[CardService] update REST error: HTTP ${response.status}`);
      }
    } catch (error) {
      console.error('[CardService] update REST error:', error);
    }
  }

  async delete(id: string): Promise<void> {
    appState.deleteCard(id);
    try {
      const baseUrl = API_URL || '';
      const response = await fetch(`${baseUrl}/api/cards/${id}`, { method: 'DELETE' });
      if (!response.ok && response.status !== 204) {
        console.error(`[CardService] delete REST error: HTTP ${response.status}`);
      }
    } catch (error) {
      console.error('[CardService] delete REST error:', error);
    }
  }

  async archive(id: string): Promise<void> {
    // Optimistic: remove from active view
    appState.deleteCard(id);
    try {
      const baseUrl = API_URL || '';
      const response = await fetch(`${baseUrl}/api/cards/${id}/archive`, { method: 'POST' });
      if (!response.ok) console.error(`[CardService] archive REST error: HTTP ${response.status}`);
    } catch (error) {
      console.error('[CardService] archive REST error:', error);
    }
  }

  async restore(id: string): Promise<Card | null> {
    try {
      const baseUrl = API_URL || '';
      const response = await fetch(`${baseUrl}/api/cards/${id}/restore`, { method: 'POST' });
      if (!response.ok) {
        console.error(`[CardService] restore REST error: HTTP ${response.status}`);
        return null;
      }
      const raw = await response.json();
      const card = this.mapRawToCard(raw);
      appState.set('cards', [...appState.get('cards'), card]);
      return card;
    } catch (error) {
      console.error('[CardService] restore REST error:', error);
      return null;
    }
  }

  async listArchived(projectId: string): Promise<Card[]> {
    try {
      const baseUrl = API_URL || '';
      const response = await fetch(`${baseUrl}/api/projects/${projectId}/cards/archived`);
      if (!response.ok) return [];
      const raw = await response.json();
      return raw.map((r: Record<string, unknown>) => this.mapRawToCard(r));
    } catch (error) {
      console.error('[CardService] listArchived REST error:', error);
      return [];
    }
  }

  private mapRawToCard(raw: Record<string, unknown>): Card {
    return {
      id: raw.id as string,
      title: raw.title as string,
      description: (raw.description as string) || '',
      status: (raw.status as CardStatus) || 'idea',
      projectId: (raw.project_id as string) || null,
      priority: (raw.priority as number) || 0,
      dependencies: (raw.dependency_ids as string[]) || [],
      tags: (raw.tags as string[]) || [],
      chatHistory: [],
      createdAt: raw.created_at ? new Date(raw.created_at as string).getTime() : Date.now(),
      updatedAt: raw.updated_at ? new Date(raw.updated_at as string).getTime() : Date.now(),
      archivedAt: (raw.archived_at as string) || null,
      agentType: (raw.agent_type as string) || undefined,
      assignee: (raw.assignee as string) || null,
      votes: (raw.votes as number) || 0,
    } as Card;
  }

  async move(cardId: string, newStatus: CardStatus): Promise<void> {
    appState.moveCard(cardId, newStatus);
    try {
      const baseUrl = API_URL || '';
      const response = await fetch(`${baseUrl}/api/cards/${cardId}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ status: newStatus }),
      });
      if (!response.ok) console.error(`[CardService] move REST error: HTTP ${response.status}`);
    } catch (error) {
      console.error('[CardService] move REST error:', error);
    }
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

  async getAgents(): Promise<AgentInfo[]> {
    if (this.agentsCache) return this.agentsCache;
    const agents = await apiClient.fetchAgents();
    if (agents.length > 0) {
      this.agentsCache = agents;
    }
    return agents;
  }

  async updateAgentType(cardId: string, agentType: string): Promise<void> {
    appState.updateCard(cardId, { agentType });
    await apiClient.patchCard(cardId, { agent_type: agentType });
  }

  destroy(): void {
    this.unsubscribers.forEach((unsub) => unsub());
    this.unsubscribers = [];
  }
}

export const cardService = new CardService();
