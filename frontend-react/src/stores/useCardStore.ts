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
import { immer } from 'zustand/middleware/immer';
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

  // Move / reorder
  moveCard: (cardId: string, newStatus: CardStatus) => void;
  reorderCards: (orderedIds: string[]) => void;

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
    immer((set, get) => ({
      cardsById: {},

      addCard: (data) => {
        const card: Card = {
          ...data,
          id: generateId(),
          createdAt: Date.now(),
          updatedAt: Date.now(),
          chatHistory: [],
        };
        set((state) => {
          state.cardsById[card.id] = card;
        });
        return card;
      },

      updateCard: (id, updates) => {
        set((state) => {
          if (!state.cardsById[id]) return;
          Object.assign(state.cardsById[id], updates);
          state.cardsById[id].updatedAt = Date.now();
        });
      },

      deleteCard: (id) => {
        const card = get().cardsById[id];
        set((state) => {
          delete state.cardsById[id];
        });
        return card;
      },

      upsertCard: (card) => {
        set((state) => {
          state.cardsById[card.id] = card;
        });
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
          for (const [id, card] of Object.entries(state.cardsById)) {
            if (card.projectId === projectId) delete state.cardsById[id];
          }
          for (const card of cards) {
            state.cardsById[card.id] = card;
          }
        });
      },

      moveCard: (cardId, newStatus) => {
        set((state) => {
          if (!state.cardsById[cardId]) return;
          state.cardsById[cardId].status = newStatus;
          state.cardsById[cardId].updatedAt = Date.now();
        });
      },

      reorderCards: (orderedIds) => {
        set((state) => {
          orderedIds.forEach((id, index) => {
            if (state.cardsById[id]) {
              state.cardsById[id].position = index;
            }
          });
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
    })),
    {
      name: 'voxyflow_cards',
      partialize: (state) => ({
        cardsById: Object.fromEntries(
          Object.entries(state.cardsById).map(([id, card]) => {
            // eslint-disable-next-line @typescript-eslint/no-unused-vars
            const { chatHistory: _ch, ...rest } = card;
            return [id, rest];
          })
        ),
      }),
      // Auto-clear corrupted/oversized localStorage so the app never crashes on quota errors
      onRehydrateStorage: () => (_state, error) => {
        if (error) {
          try { localStorage.removeItem('voxyflow_cards'); } catch {}
        }
      },
      storage: {
        getItem: (name) => {
          try {
            const s = localStorage.getItem(name);
            return s ? JSON.parse(s) : null;
          } catch { return null; }
        },
        setItem: (name, value) => {
          const s = JSON.stringify(value);
          try {
            localStorage.setItem(name, s);
          } catch {
            // Quota exceeded — wipe and retry once
            try {
              localStorage.removeItem(name);
              localStorage.setItem(name, s);
            } catch {}
          }
        },
        removeItem: (name) => {
          try { localStorage.removeItem(name); } catch {}
        },
      },
    }
  )
);
