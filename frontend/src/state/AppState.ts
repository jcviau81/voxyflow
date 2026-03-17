import { AppStateData, Message, Project, Card, ViewMode, ConnectionState } from '../types';
import { eventBus } from '../utils/EventBus';
import { EVENTS } from '../utils/constants';
import { generateId, deepClone } from '../utils/helpers';

const STORAGE_KEY = 'voxyflow_state';

const defaultState: AppStateData = {
  currentView: 'chat',
  currentProjectId: null,
  selectedCardId: null,
  messages: [],
  projects: [],
  cards: [],
  sidebarOpen: true,
  connectionState: 'disconnected',
  voiceActive: false,
  volume: 0.8,
  theme: 'dark',
};

class AppState {
  private state: AppStateData;
  private listeners: Map<string, Set<(value: unknown) => void>> = new Map();

  constructor() {
    this.state = this.loadFromStorage() || deepClone(defaultState);
    // Always reset transient state
    this.state.connectionState = 'disconnected';
    this.state.voiceActive = false;
  }

  private loadFromStorage(): AppStateData | null {
    try {
      const stored = localStorage.getItem(STORAGE_KEY);
      if (stored) {
        return JSON.parse(stored) as AppStateData;
      }
    } catch (e) {
      console.warn('[AppState] Failed to load from localStorage:', e);
    }
    return null;
  }

  private saveToStorage(): void {
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(this.state));
    } catch (e) {
      console.warn('[AppState] Failed to save to localStorage:', e);
    }
  }

  get<K extends keyof AppStateData>(key: K): AppStateData[K] {
    return this.state[key];
  }

  set<K extends keyof AppStateData>(key: K, value: AppStateData[K]): void {
    const oldValue = this.state[key];
    this.state[key] = value;
    this.saveToStorage();
    this.notifyListeners(key, value);
    eventBus.emit(EVENTS.STATE_CHANGED, { key, value, oldValue });
  }

  subscribe<K extends keyof AppStateData>(
    key: K,
    listener: (value: AppStateData[K]) => void
  ): () => void {
    const keyStr = key as string;
    if (!this.listeners.has(keyStr)) {
      this.listeners.set(keyStr, new Set());
    }
    this.listeners.get(keyStr)!.add(listener as (value: unknown) => void);
    return () => {
      this.listeners.get(keyStr)?.delete(listener as (value: unknown) => void);
    };
  }

  private notifyListeners(key: string, value: unknown): void {
    this.listeners.get(key)?.forEach((listener) => {
      try {
        listener(value);
      } catch (e) {
        console.error(`[AppState] Listener error for "${key}":`, e);
      }
    });
  }

  // --- Messages ---

  addMessage(message: Omit<Message, 'id' | 'timestamp'>): Message {
    const fullMessage: Message = {
      ...message,
      id: generateId(),
      timestamp: Date.now(),
    };
    const messages = [...this.state.messages, fullMessage];
    this.set('messages', messages);
    return fullMessage;
  }

  updateMessage(id: string, updates: Partial<Message>): void {
    const messages = this.state.messages.map((m) =>
      m.id === id ? { ...m, ...updates } : m
    );
    this.set('messages', messages);
  }

  getMessages(projectId?: string): Message[] {
    if (projectId) {
      return this.state.messages.filter((m) => m.projectId === projectId);
    }
    return this.state.messages;
  }

  clearMessages(): void {
    this.set('messages', []);
  }

  // --- Projects ---

  addProject(name: string, description: string = ''): Project {
    const project: Project = {
      id: generateId(),
      name,
      description,
      createdAt: Date.now(),
      updatedAt: Date.now(),
      cards: [],
      archived: false,
    };
    const projects = [...this.state.projects, project];
    this.set('projects', projects);
    eventBus.emit(EVENTS.PROJECT_CREATED, project);
    return project;
  }

  updateProject(id: string, updates: Partial<Project>): void {
    const projects = this.state.projects.map((p) =>
      p.id === id ? { ...p, ...updates, updatedAt: Date.now() } : p
    );
    this.set('projects', projects);
    eventBus.emit(EVENTS.PROJECT_UPDATED, { id, updates });
  }

  deleteProject(id: string): void {
    const projects = this.state.projects.filter((p) => p.id !== id);
    const cards = this.state.cards.filter((c) => c.projectId !== id);
    this.set('projects', projects);
    this.set('cards', cards);
    if (this.state.currentProjectId === id) {
      this.set('currentProjectId', null);
    }
    eventBus.emit(EVENTS.PROJECT_DELETED, id);
  }

  getProject(id: string): Project | undefined {
    return this.state.projects.find((p) => p.id === id);
  }

  // --- Cards ---

  addCard(card: Omit<Card, 'id' | 'createdAt' | 'updatedAt' | 'chatHistory'>): Card {
    const fullCard: Card = {
      ...card,
      id: generateId(),
      createdAt: Date.now(),
      updatedAt: Date.now(),
      chatHistory: [],
    };
    const cards = [...this.state.cards, fullCard];
    this.set('cards', cards);

    // Add card ID to project
    const project = this.getProject(card.projectId);
    if (project) {
      this.updateProject(card.projectId, {
        cards: [...project.cards, fullCard.id],
      });
    }

    eventBus.emit(EVENTS.CARD_CREATED, fullCard);
    return fullCard;
  }

  updateCard(id: string, updates: Partial<Card>): void {
    const cards = this.state.cards.map((c) =>
      c.id === id ? { ...c, ...updates, updatedAt: Date.now() } : c
    );
    this.set('cards', cards);
    eventBus.emit(EVENTS.CARD_UPDATED, { id, updates });
  }

  deleteCard(id: string): void {
    const card = this.state.cards.find((c) => c.id === id);
    if (card) {
      const project = this.getProject(card.projectId);
      if (project) {
        this.updateProject(card.projectId, {
          cards: project.cards.filter((cid) => cid !== id),
        });
      }
    }
    const cards = this.state.cards.filter((c) => c.id !== id);
    this.set('cards', cards);
    eventBus.emit(EVENTS.CARD_DELETED, id);
  }

  getCard(id: string): Card | undefined {
    return this.state.cards.find((c) => c.id === id);
  }

  getCardsByProject(projectId: string): Card[] {
    return this.state.cards.filter((c) => c.projectId === projectId);
  }

  getCardsByStatus(projectId: string, status: string): Card[] {
    return this.state.cards.filter(
      (c) => c.projectId === projectId && c.status === status
    );
  }

  moveCard(cardId: string, newStatus: string): void {
    this.updateCard(cardId, { status: newStatus as Card['status'] });
    eventBus.emit(EVENTS.CARD_MOVED, { cardId, newStatus });
  }

  // --- Navigation ---

  setView(view: ViewMode): void {
    this.set('currentView', view);
    eventBus.emit(EVENTS.VIEW_CHANGE, view);
  }

  selectProject(projectId: string | null): void {
    this.set('currentProjectId', projectId);
    this.set('selectedCardId', null);
    eventBus.emit(EVENTS.PROJECT_SELECTED, projectId);
  }

  selectCard(cardId: string | null): void {
    this.set('selectedCardId', cardId);
    eventBus.emit(EVENTS.CARD_SELECTED, cardId);
  }

  // --- Connection ---

  setConnectionState(state: ConnectionState): void {
    this.set('connectionState', state);
  }

  // --- Reset ---

  reset(): void {
    this.state = deepClone(defaultState);
    this.saveToStorage();
    eventBus.emit(EVENTS.STATE_CHANGED, { key: '*', value: null });
  }

  getSnapshot(): AppStateData {
    return deepClone(this.state);
  }
}

export const appState = new AppState();
