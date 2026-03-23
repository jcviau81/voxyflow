/**
 * MainBoardService — manages Main Board cards (system project "system-main").
 *
 * Post-refactor: Main Board cards are simply the cards belonging to the
 * system project (SYSTEM_PROJECT_ID). This service wraps regular project
 * card endpoints for backward compatibility with FreeBoard and other
 * consumers.
 */

import { Card, Idea } from '../types';
import { appState } from '../state/AppState';
import { apiClient } from './ApiClient';
import { eventBus } from '../utils/EventBus';
import { EVENTS, SYSTEM_PROJECT_ID } from '../utils/constants';

const API_URL_BASE = process.env.VOXYFLOW_API_URL || '';

export class MainBoardService {
  private loaded = false;

  constructor() {
    this.setupSyncHandlers();
  }

  private setupSyncHandlers(): void {
    // Listen for card:sync events that might affect main board cards
    apiClient.on('card:sync', (payload) => {
      const { action, card } = payload as { action: string; card: Card };
      if (card && (card.projectId === SYSTEM_PROJECT_ID || card.projectId === null)) {
        switch (action) {
          case 'created':
            if (!appState.getMainBoardCard(card.id)) {
              appState.addMainBoardCard(card);
            }
            break;
          case 'updated':
            appState.updateMainBoardCard(card.id, card);
            break;
          case 'deleted':
            appState.deleteMainBoardCard(card.id);
            break;
        }
      }
    });
  }

  // ── Fetch from API ────────────────────────────────────────────

  async fetchCards(): Promise<Card[]> {
    try {
      // Use the system project endpoint instead of /cards/unassigned
      const response = await fetch(`${API_URL_BASE}/api/projects/${SYSTEM_PROJECT_ID}/cards`);
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const raw = await response.json();
      const cards: Card[] = raw.map(this.mapApiCardToCard);
      appState.setMainBoardCards(cards);
      this.loaded = true;
      return cards;
    } catch (error) {
      console.error('[MainBoardService] fetchCards error:', error);
      return appState.getMainBoardCards();
    }
  }

  async ensureLoaded(): Promise<Card[]> {
    if (!this.loaded) {
      return this.fetchCards();
    }
    return appState.getMainBoardCards();
  }

  // ── Create ────────────────────────────────────────────────────

  async createCard(title: string, description?: string, color?: string, priority?: number): Promise<Card | null> {
    try {
      // Create card in the system project
      const response = await fetch(`${API_URL_BASE}/api/projects/${SYSTEM_PROJECT_ID}/cards`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          title,
          description: description || '',
          color: color || null,
          priority: priority || 0,
          status: 'card',
        }),
      });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const raw = await response.json();
      const card = this.mapApiCardToCard(raw);
      appState.addMainBoardCard(card);
      return card;
    } catch (error) {
      console.error('[MainBoardService] createCard error:', error);
      return null;
    }
  }

  // ── Delete ────────────────────────────────────────────────────

  async deleteCard(cardId: string): Promise<boolean> {
    try {
      const response = await fetch(`${API_URL_BASE}/api/cards/${cardId}`, {
        method: 'DELETE',
      });
      if (!response.ok && response.status !== 204) throw new Error(`HTTP ${response.status}`);
      appState.deleteMainBoardCard(cardId);
      return true;
    } catch (error) {
      console.error('[MainBoardService] deleteCard error:', error);
      return false;
    }
  }

  // ── Update ────────────────────────────────────────────────────

  async updateCard(cardId: string, updates: Partial<{ title: string; description: string; color: string | null; priority: number }>): Promise<Card | null> {
    try {
      const response = await fetch(`${API_URL_BASE}/api/cards/${cardId}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(updates),
      });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const raw = await response.json();
      const card = this.mapApiCardToCard(raw);
      appState.updateMainBoardCard(cardId, card);
      return card;
    } catch (error) {
      console.error('[MainBoardService] updateCard error:', error);
      return null;
    }
  }

  // ── Assign / Unassign ─────────────────────────────────────────

  async assignToProject(cardId: string, projectId: string): Promise<Card | null> {
    try {
      const response = await fetch(`${API_URL_BASE}/api/cards/${cardId}/assign/${projectId}`, {
        method: 'PATCH',
      });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const raw = await response.json();
      const card = this.mapApiCardToCard(raw);
      // Remove from main board since it now has a different project
      appState.deleteMainBoardCard(cardId);
      // Add to the project cards list
      const projectCards = [...appState.get('cards'), card];
      appState.set('cards', projectCards);
      eventBus.emit(EVENTS.CARD_CREATED, card);
      return card;
    } catch (error) {
      console.error('[MainBoardService] assignToProject error:', error);
      return null;
    }
  }

  async unassignFromProject(cardId: string): Promise<Card | null> {
    try {
      const response = await fetch(`${API_URL_BASE}/api/cards/${cardId}/unassign`, {
        method: 'PATCH',
      });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const raw = await response.json();
      const card = this.mapApiCardToCard(raw);
      // Remove from project cards
      const projectCards = appState.get('cards').filter((c) => c.id !== cardId);
      appState.set('cards', projectCards);
      // Add to main board
      appState.addMainBoardCard(card);
      return card;
    } catch (error) {
      console.error('[MainBoardService] unassignFromProject error:', error);
      return null;
    }
  }

  // ── Migrate localStorage Ideas → Cards ────────────────────────

  async migrateIdeasToCards(): Promise<number> {
    const ideas = appState.getIdeas();
    if (ideas.length === 0) return 0;

    let migrated = 0;
    for (const idea of ideas) {
      const card = await this.createCard(
        idea.content,
        idea.body || '',
        idea.color || undefined,
      );
      if (card) migrated++;
    }

    if (migrated > 0) {
      // Clear old ideas from localStorage
      appState.set('ideas', []);
      console.log(`[MainBoardService] Migrated ${migrated}/${ideas.length} ideas to cards`);
    }

    return migrated;
  }

  // ── API response → Card type mapping ──────────────────────────

  private mapApiCardToCard(raw: Record<string, unknown>): Card {
    return {
      id: raw.id as string,
      title: raw.title as string,
      description: (raw.description as string) || '',
      status: (raw.status as Card['status']) || 'card',
      projectId: (raw.project_id as string | null) ?? SYSTEM_PROJECT_ID,
      color: (raw.color as Card['color']) || null,
      assignedAgent: undefined,
      agentType: (raw.agent_type as string) || undefined,
      dependencies: (raw.dependency_ids as string[]) || [],
      tags: [],
      priority: (raw.priority as number) || 0,
      createdAt: raw.created_at ? new Date(raw.created_at as string).getTime() : Date.now(),
      updatedAt: raw.updated_at ? new Date(raw.updated_at as string).getTime() : Date.now(),
      chatHistory: [],
      totalMinutes: (raw.total_minutes as number) || 0,
      checklistProgress: raw.checklist_progress as Card['checklistProgress'],
      assignee: (raw.assignee as string) || null,
      watchers: (raw.watchers as string) || '',
      votes: (raw.votes as number) || 0,
      files: (raw.files as string[]) || [],
    };
  }

  // ── Cleanup ───────────────────────────────────────────────────

  destroy(): void {
    // No-op for now
  }
}

export const mainBoardService = new MainBoardService();
