import { AppStateData, Message, Project, Card, ViewMode, ConnectionState, Tab, Idea, SessionInfo, ActivityEntry, ActivityType, NotificationEntry, NotificationType } from '../types';
import { eventBus } from '../utils/EventBus';
import { EVENTS, SYSTEM_PROJECT_ID } from '../utils/constants';
import { generateId, deepClone } from '../utils/helpers';
import { cardStore } from './ReactiveCardStore';

const MAX_ACTIVITIES_PER_PROJECT = 50;
const MAX_NOTIFICATIONS = 100;

const STORAGE_KEY = 'voxyflow_state';
const TABS_STORAGE_KEY = 'voxyflow_open_tabs';

const DEFAULT_MAIN_TAB: Tab = {
  id: 'main',
  label: 'Main',
  emoji: '🏠',
  closable: false,
  hasNotification: false,
  isActive: true,
};

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
  activeTab: 'main',
  openTabs: [{ ...DEFAULT_MAIN_TAB }],
  ideas: [],
  mainBoardCards: [],
  sessions: {},
  activeSession: {},
  activities: {},
  opportunityBadgeCount: 0,
  notifications: [],
  notificationUnreadCount: 0,
  generalSessions: [{ id: 'session-1', label: 'Session 1' }],
  activeGeneralSessionId: 'session-1',
  generalSessionCounter: 1,
};

class AppState {
  private state: AppStateData;
  private listeners: Map<string, Set<(value: unknown) => void>> = new Map();

  constructor() {
    this.state = this.loadFromStorage() || deepClone(defaultState);
    // Always reset transient state
    this.state.connectionState = 'disconnected';
    this.state.voiceActive = false;

    // Apply persisted theme immediately
    const savedTheme = localStorage.getItem('voxyflow_theme') as 'dark' | 'light' | null;
    if (savedTheme === 'light' || savedTheme === 'dark') {
      this.state.theme = savedTheme;
    }
    document.documentElement.setAttribute('data-theme', this.state.theme || 'dark');

    // Ensure tabs are initialized (migration from old state)
    if (!this.state.openTabs || this.state.openTabs.length === 0) {
      this.state.openTabs = [{ ...DEFAULT_MAIN_TAB }];
    }
    if (!this.state.activeTab) {
      this.state.activeTab = 'main';
    }

    // Ensure mainBoardCards is initialized (migration from old state)
    if (!this.state.mainBoardCards) {
      this.state.mainBoardCards = [];
    }

    // Ensure session tab data is initialized (migration from old state)
    if (!this.state.sessions) {
      this.state.sessions = {};
    }
    if (!this.state.activeSession) {
      this.state.activeSession = {};
    }

    // Ensure activity feed initialized (migration from old state)
    if (!this.state.activities) {
      this.state.activities = {};
    }
    if (this.state.opportunityBadgeCount === undefined) {
      this.state.opportunityBadgeCount = 0;
    }

    // Ensure notification center initialized (migration from old state)
    if (!this.state.notifications) {
      this.state.notifications = [];
    }
    if (this.state.notificationUnreadCount === undefined) {
      this.state.notificationUnreadCount = 0;
    }

    // Ensure general chat sessions are initialized (migration from old state)
    if (!this.state.generalSessions || this.state.generalSessions.length === 0) {
      this.state.generalSessions = [{ id: 'session-1', label: 'Session 1' }];
    }
    if (!this.state.activeGeneralSessionId) {
      this.state.activeGeneralSessionId = this.state.generalSessions[0].id;
    }
    if (!this.state.generalSessionCounter) {
      this.state.generalSessionCounter = this.state.generalSessions.length;
    }

    // Restore persisted tabs
    this.loadTabsFromStorage();
  }

  private loadFromStorage(): AppStateData | null {
    try {
      const stored = localStorage.getItem(STORAGE_KEY);
      if (stored) {
        const data = JSON.parse(stored) as AppStateData;
        return data;
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

    // Track chat activity for project contexts
    if (fullMessage.projectId && fullMessage.role === 'user' && !fullMessage.streaming) {
      const snippet = fullMessage.content.length > 60
        ? fullMessage.content.slice(0, 60) + '…'
        : fullMessage.content;
      this.addActivity(fullMessage.projectId, 'chat_message', `💬 ${snippet}`);
    }

    return fullMessage;
  }

  updateMessage(id: string, updates: Partial<Message>): void {
    const messages = this.state.messages.map((m) =>
      m.id === id ? { ...m, ...updates } : m
    );
    this.set('messages', messages);
  }

  getMessages(projectId?: string, sessionId?: string): Message[] {
    let messages = this.state.messages;
    if (projectId) {
      messages = messages.filter((m) => m.projectId === projectId);
    }
    if (sessionId) {
      messages = messages.filter((m) => m.sessionId === sessionId);
    }
    return messages;
  }

  /**
   * Replace messages in bulk — used to inject history from backend without N re-renders.
   * Merges with existing messages, deduplicating by timestamp + role.
   *
   * replace=false (default): merge, dedup by timestamp+role+content prefix.
   * replace=true: replace ALL messages globally (use with care).
   */
  setMessages(newMessages: Message[], replace = false): void {
    if (replace) {
      this.set('messages', newMessages);
      return;
    }
    // Merge: add only messages that don't already exist (dedup by timestamp + role + content prefix)
    const existing = this.state.messages;
    const existingKeys = new Set(
      existing.map((m) => `${m.role}:${m.timestamp}:${m.content.slice(0, 50)}`)
    );
    const toAdd = newMessages.filter(
      (m) => !existingKeys.has(`${m.role}:${m.timestamp}:${m.content.slice(0, 50)}`)
    );
    if (toAdd.length > 0) {
      this.set('messages', [...existing, ...toAdd]);
    }
  }

  /**
   * Replace messages for a specific session (identified by sessionId or projectId+cardId),
   * preserving messages from other sessions/contexts.
   * Used when reloading history from the backend to ensure stale snapshots are evicted.
   */
  replaceSessionMessages(newMessages: Message[], sessionId?: string, projectId?: string, cardId?: string): void {
    const existing = this.state.messages;
    // Keep messages that don't belong to this session/context
    const kept = existing.filter((m) => {
      if (sessionId && m.sessionId === sessionId) return false;
      if (!sessionId && cardId && m.cardId === cardId) return false;
      if (!sessionId && !cardId && projectId && m.projectId === projectId) return false;
      return true;
    });
    this.set('messages', [...kept, ...newMessages]);
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
    this.set('projects', projects);
    // Remove all cards for this project from the reactive store
    for (const card of cardStore.getByProject(id)) {
      cardStore.remove(card.id);
    }
    if (this.state.currentProjectId === id) {
      this.set('currentProjectId', null);
    }
    eventBus.emit(EVENTS.PROJECT_DELETED, id);
  }

  getProject(id: string): Project | undefined {
    return this.state.projects.find((p) => p.id === id);
  }

  // --- Cards (delegated to ReactiveCardStore) ---

  addCard(card: Omit<Card, 'id' | 'createdAt' | 'updatedAt' | 'chatHistory'>): Card {
    const fullCard: Card = {
      ...card,
      id: generateId(),
      createdAt: Date.now(),
      updatedAt: Date.now(),
      chatHistory: [],
    };
    cardStore.upsert(fullCard);

    // Add card ID to project (only for project-assigned cards)
    if (card.projectId) {
      const project = this.getProject(card.projectId);
      if (project) {
        this.updateProject(card.projectId, {
          cards: [...project.cards, fullCard.id],
        });
      }
    }

    return fullCard;
  }

  updateCard(id: string, updates: Partial<Card>): void {
    const existing = cardStore.get(id);
    if (existing) {
      cardStore.upsert({ ...existing, ...updates, updatedAt: Date.now() });
    }
  }

  deleteCard(id: string): void {
    const card = cardStore.get(id);
    if (card && card.projectId) {
      const project = this.getProject(card.projectId);
      if (project) {
        this.updateProject(card.projectId, {
          cards: project.cards.filter((cid) => cid !== id),
        });
      }
    }
    cardStore.remove(id);
  }

  getCard(id: string): Card | undefined {
    return cardStore.get(id);
  }

  getCardsByProject(projectId: string): Card[] {
    return cardStore.getByProject(projectId);
  }

  getCardsByStatus(projectId: string, status: string): Card[] {
    return cardStore.getByStatus(projectId, status);
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

  // --- Tabs ---

  private loadTabsFromStorage(): void {
    try {
      const saved = localStorage.getItem(TABS_STORAGE_KEY);
      if (saved) {
        const tabs = JSON.parse(saved) as Tab[];
        // Ensure main tab always exists
        const hasMain = tabs.some(t => t.id === 'main');
        if (!hasMain) {
          tabs.unshift({ ...DEFAULT_MAIN_TAB });
        }
        // Always sync main tab emoji/label with defaults (migration)
        const mainTab = tabs.find(t => t.id === 'main');
        if (mainTab) {
          mainTab.emoji = DEFAULT_MAIN_TAB.emoji;
          mainTab.label = DEFAULT_MAIN_TAB.label;
        }
        this.state.openTabs = tabs;
        // Ensure active tab is valid
        const activeValid = tabs.some(t => t.id === this.state.activeTab);
        if (!activeValid) {
          this.state.activeTab = 'main';
        }
        // Set isActive flags
        this.state.openTabs.forEach(t => {
          t.isActive = t.id === this.state.activeTab;
        });
      }
    } catch (e) {
      console.warn('[AppState] Failed to load tabs from localStorage:', e);
    }
  }

  private saveTabsToStorage(): void {
    try {
      localStorage.setItem(TABS_STORAGE_KEY, JSON.stringify(this.state.openTabs));
    } catch (e) {
      console.warn('[AppState] Failed to save tabs to localStorage:', e);
    }
  }

  openProjectTab(projectId: string, projectName: string, emoji?: string): void {
    const existing = this.state.openTabs.find(t => t.id === projectId);
    if (existing) {
      // Tab already open, just switch to it
      this.switchTab(projectId);
      return;
    }

    const tab: Tab = {
      id: projectId,
      label: projectName,
      emoji: emoji || '📁',
      closable: true,
      hasNotification: false,
      isActive: false,
    };

    const tabs = [...this.state.openTabs, tab];
    this.set('openTabs', tabs);
    this.saveTabsToStorage();
    eventBus.emit(EVENTS.TAB_OPEN, tab);
    this.switchTab(projectId);
  }

  closeTab(tabId: string): void {
    if (tabId === 'main') return; // Cannot close main tab

    const wasActive = this.state.activeTab === tabId;
    const oldTabs = this.state.openTabs;
    const closedIndex = oldTabs.findIndex(t => t.id === tabId);

    const tabs = oldTabs.filter(t => t.id !== tabId);
    this.set('openTabs', tabs);
    this.saveTabsToStorage();
    eventBus.emit(EVENTS.TAB_CLOSE, tabId);

    // If we closed the active tab, switch to nearest remaining tab
    if (wasActive) {
      if (tabs.length === 0) {
        // Should not happen (main always exists), but guard anyway
        this.switchTab('main');
      } else {
        // Prefer the tab that was just before; fall back to main
        const fallbackIndex = Math.min(closedIndex, tabs.length - 1);
        const fallbackTab = tabs[fallbackIndex] || tabs[0];
        this.switchTab(fallbackTab.id);
      }
    }
  }

  switchTab(tabId: string): void {
    const tab = this.state.openTabs.find(t => t.id === tabId);
    if (!tab) return;

    // Update active states
    const tabs = this.state.openTabs.map(t => ({
      ...t,
      isActive: t.id === tabId,
    }));
    this.set('openTabs', tabs);
    this.set('activeTab', tabId);
    this.saveTabsToStorage();

    // Update project context
    if (tabId === 'main') {
      this.selectProject(SYSTEM_PROJECT_ID);
    } else {
      this.selectProject(tabId);
    }

    eventBus.emit(EVENTS.TAB_SWITCH, tabId);
  }

  setTabNotification(tabId: string, hasNotification: boolean): void {
    const tabs = this.state.openTabs.map(t =>
      t.id === tabId ? { ...t, hasNotification } : t
    );
    this.set('openTabs', tabs);
    this.saveTabsToStorage();
    eventBus.emit(EVENTS.TAB_NOTIFICATION, { tabId, hasNotification });
  }

  getOpenTabs(): Tab[] {
    return this.state.openTabs;
  }

  getActiveTab(): string {
    return this.state.activeTab;
  }

  // --- Ideas ---

  addIdea(content: string, source: 'manual' | 'analyzer' = 'manual'): Idea {
    const idea: Idea = {
      id: generateId(),
      content,
      createdAt: Date.now(),
      source,
    };
    const ideas = [...this.state.ideas, idea];
    this.set('ideas', ideas);
    eventBus.emit(EVENTS.IDEA_ADDED, idea);
    return idea;
  }

  deleteIdea(id: string): void {
    const ideas = this.state.ideas.filter(i => i.id !== id);
    this.set('ideas', ideas);
    eventBus.emit(EVENTS.IDEA_DELETED, id);
  }

  getIdeas(): Idea[] {
    return this.state.ideas || [];
  }

  // --- Main Board Cards (delegated to ReactiveCardStore, SYSTEM_PROJECT_ID) ---

  setMainBoardCards(cards: Card[]): void {
    cardStore.setForProject(SYSTEM_PROJECT_ID, cards);
    eventBus.emit(EVENTS.MAIN_BOARD_UPDATED, cards);
  }

  getMainBoardCards(): Card[] {
    return cardStore.getByProject(SYSTEM_PROJECT_ID);
  }

  addMainBoardCard(card: Card): void {
    cardStore.upsert(card);
    eventBus.emit(EVENTS.MAIN_BOARD_CARD_CREATED, card);
  }

  updateMainBoardCard(id: string, updates: Partial<Card>): void {
    const existing = cardStore.get(id);
    if (existing) {
      cardStore.upsert({ ...existing, ...updates, updatedAt: Date.now() });
    }
    eventBus.emit(EVENTS.MAIN_BOARD_UPDATED, cardStore.getByProject(SYSTEM_PROJECT_ID));
  }

  deleteMainBoardCard(id: string): void {
    cardStore.remove(id);
    eventBus.emit(EVENTS.MAIN_BOARD_CARD_DELETED, id);
  }

  getMainBoardCard(id: string): Card | undefined {
    return cardStore.get(id);
  }

  // --- Activity Feed ---

  addActivity(projectId: string, type: ActivityType, message: string): ActivityEntry {
    const entry: ActivityEntry = {
      id: generateId(),
      projectId,
      type,
      message,
      timestamp: Date.now(),
    };
    const existing = this.state.activities[projectId] || [];
    // Prepend new entry and trim to max
    const updated = [entry, ...existing].slice(0, MAX_ACTIVITIES_PER_PROJECT);
    this.state.activities = {
      ...this.state.activities,
      [projectId]: updated,
    };
    this.saveToStorage();
    eventBus.emit(EVENTS.ACTIVITY_ADDED, entry);
    return entry;
  }

  getActivities(projectId: string, limit = 10): ActivityEntry[] {
    const all = this.state.activities[projectId] || [];
    return all.slice(0, limit);
  }

  clearActivities(projectId: string): void {
    const activities = { ...this.state.activities };
    delete activities[projectId];
    this.state.activities = activities;
    this.saveToStorage();
  }

  // --- Opportunity Badge ---

  incrementOpportunityBadge(): void {
    this.state.opportunityBadgeCount = (this.state.opportunityBadgeCount || 0) + 1;
    this.saveToStorage();
    eventBus.emit(EVENTS.OPPORTUNITIES_COUNT, this.state.opportunityBadgeCount);
  }

  clearOpportunityBadge(): void {
    this.state.opportunityBadgeCount = 0;
    this.saveToStorage();
    eventBus.emit(EVENTS.OPPORTUNITIES_COUNT, 0);
  }

  getOpportunityBadgeCount(): number {
    return this.state.opportunityBadgeCount || 0;
  }

  // --- Session Tabs (per project/card context) ---

  /**
   * Create a new session for a given tabId.
   * Auto-assigns a sequential title ("Session 1", "Session 2", …).
   * Returns the created SessionInfo. Does NOT create a session if max (5) reached.
   */
  createSession(tabId: string): SessionInfo {
    const existing = this.state.sessions[tabId] || [];
    if (existing.length >= 5) {
      // Return last session if max reached
      return existing[existing.length - 1];
    }
    const sessionNumber = existing.length + 1;
    const session: SessionInfo = {
      id: generateId(),
      chatId: `${tabId}::${generateId()}`,
      title: `Session ${sessionNumber}`,
      createdAt: Date.now(),
    };
    const updatedSessions = {
      ...this.state.sessions,
      [tabId]: [...existing, session],
    };
    const updatedActive = {
      ...this.state.activeSession,
      [tabId]: session.id,
    };
    this.state.sessions = updatedSessions;
    this.state.activeSession = updatedActive;
    this.saveToStorage();
    return session;
  }

  /**
   * Close (remove) a session for a given tabId.
   * Won't close the last remaining session.
   * Switches active session if the closed one was active.
   */
  closeSession(tabId: string, sessionId: string): void {
    const existing = this.state.sessions[tabId] || [];
    if (existing.length <= 1) return; // Never close the last session

    const updatedList = existing.filter((s) => s.id !== sessionId);
    const updatedSessions = {
      ...this.state.sessions,
      [tabId]: updatedList,
    };
    this.state.sessions = updatedSessions;

    // If we closed the active session, switch to the first remaining one
    if (this.state.activeSession[tabId] === sessionId) {
      this.state.activeSession = {
        ...this.state.activeSession,
        [tabId]: updatedList.length > 0 ? updatedList[0].id : '',
      };
    }
    this.saveToStorage();
    eventBus.emit(EVENTS.SESSION_TAB_CLOSE, { tabId, sessionId });
  }

  /**
   * Set the active session for a tabId. Creates sessions array if needed.
   */
  setActiveSession(tabId: string, sessionId: string): void {
    this.state.activeSession = {
      ...this.state.activeSession,
      [tabId]: sessionId,
    };
    this.saveToStorage();
    eventBus.emit(EVENTS.SESSION_TAB_SWITCH, { tabId, sessionId });
  }

  /**
   * Get sessions for a tabId, auto-creating an initial session if none exist.
   */
  getSessions(tabId: string): SessionInfo[] {
    if (!this.state.sessions[tabId] || this.state.sessions[tabId].length === 0) {
      this.createSession(tabId);
    }
    return this.state.sessions[tabId] || [];
  }

  /**
   * Get the active SessionInfo for a tabId.
   */
  getActiveSession(tabId: string): SessionInfo {
    const sessions = this.getSessions(tabId);
    const activeId = this.state.activeSession[tabId];
    if (sessions.length === 0) return { id: '', chatId: '', title: 'Session 1', createdAt: Date.now() };
    return sessions.find((s) => s.id === activeId) || sessions[0];
  }

  /**
   * Returns the chat_id for the active session of a given tabId.
   * This is the ID used when communicating with the backend.
   */
  getActiveChatId(tabId: string): string {
    return this.getActiveSession(tabId).chatId;
  }

  /**
   * Update a session's title (e.g. after first message).
   */
  updateSessionTitle(tabId: string, sessionId: string, title: string): void {
    const sessions = this.state.sessions[tabId];
    if (!sessions) return;
    const updated = sessions.map((s) =>
      s.id === sessionId ? { ...s, title } : s
    );
    this.state.sessions = {
      ...this.state.sessions,
      [tabId]: updated,
    };
    this.saveToStorage();
    eventBus.emit(EVENTS.SESSION_TAB_UPDATE, { tabId, sessionId, title });
  }

  // --- Notification Center ---

  addNotification(entry: Omit<NotificationEntry, 'id' | 'timestamp' | 'read'>): NotificationEntry {
    const notification: NotificationEntry = {
      ...entry,
      id: generateId(),
      timestamp: Date.now(),
      read: false,
    };
    const existing = this.state.notifications || [];
    // Prepend and trim to max (FIFO: oldest are at the end)
    const updated = [notification, ...existing].slice(0, MAX_NOTIFICATIONS);
    this.state.notifications = updated;
    this.state.notificationUnreadCount = (this.state.notificationUnreadCount || 0) + 1;
    this.saveToStorage();
    eventBus.emit(EVENTS.NOTIFICATION_ADDED, notification);
    eventBus.emit(EVENTS.NOTIFICATION_COUNT, this.state.notificationUnreadCount);
    return notification;
  }

  markAllNotificationsRead(): void {
    this.state.notifications = (this.state.notifications || []).map(n => ({ ...n, read: true }));
    this.state.notificationUnreadCount = 0;
    this.saveToStorage();
    eventBus.emit(EVENTS.NOTIFICATION_COUNT, 0);
  }

  clearNotifications(): void {
    this.state.notifications = [];
    this.state.notificationUnreadCount = 0;
    this.saveToStorage();
    eventBus.emit(EVENTS.NOTIFICATION_COUNT, 0);
    eventBus.emit(EVENTS.NOTIFICATION_CLEARED, null);
  }

  getNotifications(): NotificationEntry[] {
    return this.state.notifications || [];
  }

  getNotificationUnreadCount(): number {
    return this.state.notificationUnreadCount || 0;
  }

  // --- Theme ---

  setTheme(theme: 'dark' | 'light'): void {
    this.set('theme', theme);
    document.documentElement.setAttribute('data-theme', theme);
    localStorage.setItem('voxyflow_theme', theme);
  }

  // --- Reset ---

  reset(): void {
    this.state = deepClone(defaultState);
    this.saveToStorage();
    this.saveTabsToStorage();
    eventBus.emit(EVENTS.STATE_CHANGED, { key: '*', value: null });
  }

  getSnapshot(): AppStateData {
    return deepClone(this.state);
  }
}

export const appState = new AppState();
