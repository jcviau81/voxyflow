/**
 * useCardStore — Zustand store mirroring ReactiveCardStore + AppState card logic.
 *
 * Cards are keyed by id in a Map-like record for O(1) lookups.
 * Persist middleware serializes to localStorage.
 *
 * SYSTEM_PROJECT_ID ('system-main') hosts Main Board cards.
 */

import { create } from 'zustand';
import { persist } from 'zustand/middleware';
import type { Card, CardStatus } from '../types';
import { generateId } from '../lib/utils';

export const SYSTEM_PROJECT_ID = 'system-main';

export interface CardState {
  /** All cards keyed by id for O(1) access. */
  cardsById: Record<string, Card>;

  // CRUD
  addCard: (data: Omit<Card, 'id' | 'createdAt' | 'updatedAt' | 'chatHistory'>) => Card;
  updateCard: (id: string, updates: Partial<Card>) => void;
  deleteCard: (id: string) => Card | undefined;
  upsertCard: (card: Card) => void;

  /** Bulk-replace all cards (e.g. from API sync). */
  setCards: (cards: Card[]) => void;

  /** Replace cards for a single project, keeping other projects intact. */
  setCardsForProject: (projectId: string, cards: Card[]) => void;

  // Move
  moveCard: (cardId: string, newStatus: CardStatus) => void;

  // Queries (derived — not persisted)
  getCard: (id: string) => Card | undefined;
  getCardsByProject: (projectId: string) => Card[];
  getCardsByStatus: (projectId: string, status: CardStatus) => Card[];
  getAllCards: () => Card[];

  // Main Board helpers (SYSTEM_PROJECT_ID)
  getMainBoardCards: () => Card[];
  setMainBoardCards: (cards: Card[]) => void;
}

export const useCardStore = create<CardState>()(
  persist(
    (set, get) => ({
      cardsById: {},

      addCard: (data) => {
        const card: Card = {
          ...data,
          id: generateId(),
          createdAt: Date.now(),
          updatedAt: Date.now(),
          chatHistory: [],
        };
        set((state) => ({
          cardsById: { ...state.cardsById, [card.id]: card },
        }));
        return card;
      },

      updateCard: (id, updates) => {
        set((state) => {
          const existing = state.cardsById[id];
          if (!existing) return state;
          return {
            cardsById: {
              ...state.cardsById,
              [id]: { ...existing, ...updates, updatedAt: Date.now() },
            },
          };
        });
      },

      deleteCard: (id) => {
        const card = get().cardsById[id];
        set((state) => {
          const next = { ...state.cardsById };
          delete next[id];
          return { cardsById: next };
        });
        return card;
      },

      upsertCard: (card) => {
        set((state) => ({
          cardsById: { ...state.cardsById, [card.id]: card },
        }));
      },

      setCards: (cards) => {
        const cardsById: Record<string, Card> = {};
        for (const card of cards) {
          cardsById[card.id] = card;
        }
        set({ cardsById });
      },

      setCardsForProject: (projectId, cards) => {
        set((state) => {
          // Remove existing cards for this project
          const next: Record<string, Card> = {};
          for (const [id, card] of Object.entries(state.cardsById)) {
            if (card.projectId !== projectId) {
              next[id] = card;
            }
          }
          // Insert new cards
          for (const card of cards) {
            next[card.id] = card;
          }
          return { cardsById: next };
        });
      },

      moveCard: (cardId, newStatus) => {
        set((state) => {
          const existing = state.cardsById[cardId];
          if (!existing) return state;
          return {
            cardsById: {
              ...state.cardsById,
              [cardId]: { ...existing, status: newStatus, updatedAt: Date.now() },
            },
          };
        });
      },

      getCard: (id) => get().cardsById[id],

      getCardsByProject: (projectId) =>
        Object.values(get().cardsById).filter((c) => c.projectId === projectId),

      getCardsByStatus: (projectId, status) =>
        Object.values(get().cardsById).filter(
          (c) => c.projectId === projectId && c.status === status
        ),

      getAllCards: () => Object.values(get().cardsById),

      getMainBoardCards: () =>
        Object.values(get().cardsById).filter((c) => c.projectId === SYSTEM_PROJECT_ID),

      setMainBoardCards: (cards) => get().setCardsForProject(SYSTEM_PROJECT_ID, cards),
    }),
    {
      name: 'voxyflow_cards',
      partialize: (state) => ({ cardsById: state.cardsById }),
    }
  )
);
