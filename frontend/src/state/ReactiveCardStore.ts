/**
 * ReactiveCardStore — single source of truth for all cards.
 *
 * Components subscribe to changes and get notified automatically when any card
 * updates. Replaces the dual cards/mainBoardCards stores and manual event emission.
 *
 * Backward compat: emits CARD_UPDATED / CARD_CREATED / CARD_DELETED on eventBus
 * so components that haven't migrated yet still work.
 */

import { Card } from '../types';
import { eventBus } from '../utils/EventBus';
import { EVENTS } from '../utils/constants';

class ReactiveCardStore {
  private cards: Map<string, Card> = new Map();
  private listeners: Set<() => void> = new Set();
  private cardListeners: Map<string, Set<(card: Card) => void>> = new Map();

  /** Subscribe to ALL card changes (for lists/grids that show many cards). */
  subscribe(listener: () => void): () => void {
    this.listeners.add(listener);
    return () => {
      this.listeners.delete(listener);
    };
  }

  /** Subscribe to a SPECIFIC card (for modals/detail views). */
  subscribeToCard(cardId: string, listener: (card: Card) => void): () => void {
    if (!this.cardListeners.has(cardId)) {
      this.cardListeners.set(cardId, new Set());
    }
    this.cardListeners.get(cardId)!.add(listener);
    return () => {
      this.cardListeners.get(cardId)?.delete(listener);
      if (this.cardListeners.get(cardId)?.size === 0) {
        this.cardListeners.delete(cardId);
      }
    };
  }

  /** Bulk set (from API sync). Replaces all cards for a given project, or all cards if no filter. */
  set(cards: Card[]): void {
    this.cards.clear();
    for (const card of cards) {
      this.cards.set(card.id, card);
    }
    this.notify();
    // Backward compat: emit a generic event so old listeners still fire
    eventBus.emit(EVENTS.CARD_CREATED, null);
  }

  /** Replace cards for a specific project only, keeping other projects' cards intact. */
  setForProject(projectId: string, cards: Card[]): void {
    // Remove existing cards for this project
    for (const [id, card] of this.cards) {
      if (card.projectId === projectId) {
        this.cards.delete(id);
      }
    }
    // Add new cards
    for (const card of cards) {
      this.cards.set(card.id, card);
    }
    this.notify();
    // Backward compat
    eventBus.emit(EVENTS.CARD_CREATED, null);
  }

  /** Add or update one card. */
  upsert(card: Card): void {
    const existing = this.cards.get(card.id);
    this.cards.set(card.id, card);
    this.notify();
    this.notifyCard(card.id, card);
    // Backward compat
    if (existing) {
      eventBus.emit(EVENTS.CARD_UPDATED, { id: card.id, cardId: card.id });
    } else {
      eventBus.emit(EVENTS.CARD_CREATED, card);
    }
  }

  /** Remove a card by ID. */
  remove(cardId: string): void {
    this.cards.delete(cardId);
    this.notify();
    // Backward compat
    eventBus.emit(EVENTS.CARD_DELETED, cardId);
  }

  /** Get a card by ID. */
  get(cardId: string): Card | undefined {
    return this.cards.get(cardId);
  }

  /** Get all cards for a project. */
  getByProject(projectId: string): Card[] {
    const result: Card[] = [];
    for (const card of this.cards.values()) {
      if (card.projectId === projectId) {
        result.push(card);
      }
    }
    return result;
  }

  /** Get cards by project and status. */
  getByStatus(projectId: string, status: string): Card[] {
    const result: Card[] = [];
    for (const card of this.cards.values()) {
      if (card.projectId === projectId && card.status === status) {
        result.push(card);
      }
    }
    return result;
  }

  /** Get all cards. */
  getAll(): Card[] {
    return Array.from(this.cards.values());
  }

  /** Notify all global listeners. */
  private notify(): void {
    for (const listener of this.listeners) {
      try {
        listener();
      } catch (e) {
        console.error('[ReactiveCardStore] listener error:', e);
      }
    }
  }

  /** Notify card-specific listeners. */
  private notifyCard(cardId: string, card: Card): void {
    const listeners = this.cardListeners.get(cardId);
    if (!listeners) return;
    for (const listener of listeners) {
      try {
        listener(card);
      } catch (e) {
        console.error('[ReactiveCardStore] card listener error:', e);
      }
    }
  }
}

export const cardStore = new ReactiveCardStore();
