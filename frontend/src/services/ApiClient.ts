import { WebSocketMessage, ApiClientConfig, ConnectionState, AgentInfo, TimeEntry, CardComment, ChecklistItem, CardAttachment, Card } from '../types';

export interface SearchResult {
  message_id: string;
  chat_id: string;
  role: string;
  content: string;
  snippet: string;
  created_at: string | null;
}
import { eventBus } from '../utils/EventBus';
import { EVENTS, WS_URL, API_URL, RECONNECT_MAX_ATTEMPTS, RECONNECT_BASE_DELAY, RECONNECT_MAX_DELAY, HEARTBEAT_INTERVAL, SYSTEM_PROJECT_ID } from '../utils/constants';
import { generateId } from '../utils/helpers';
import { appState } from '../state/AppState';

type MessageHandler = (payload: Record<string, unknown>) => void;

interface QueuedMessage {
  type: string;
  payload: Record<string, unknown>;
  id: string;
  timestamp: number;
}

export class ApiClient {
  private ws: WebSocket | null = null;
  private config: ApiClientConfig;
  private handlers: Map<string, Set<MessageHandler>> = new Map();
  private reconnectAttempts = 0;
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  private heartbeatTimer: ReturnType<typeof setInterval> | null = null;
  private offlineQueue: QueuedMessage[] = [];
  private isClosing = false;

  constructor(config?: Partial<ApiClientConfig>) {
    this.config = {
      url: config?.url || WS_URL,
      reconnectAttempts: config?.reconnectAttempts || RECONNECT_MAX_ATTEMPTS,
      reconnectDelay: config?.reconnectDelay || RECONNECT_BASE_DELAY,
      heartbeatInterval: config?.heartbeatInterval || HEARTBEAT_INTERVAL,
    };

    this.loadOfflineQueue();
    this.registerBuiltinHandlers();
  }

  private registerBuiltinHandlers(): void {
    // Handle tool:executed messages from the backend
    this.on('tool:executed', (payload: Record<string, unknown>) => {
      const { tool, arguments: args, result } = payload as {
        tool: string;
        arguments: Record<string, unknown>;
        result: Record<string, unknown>;
      };
      this.handleToolExecuted(tool, args ?? {}, result ?? {});
    });
  }

  handleToolExecuted(tool: string, args: Record<string, unknown>, result: Record<string, unknown>): void {
    // Emit generic event so ChatWindow can inject a system message
    eventBus.emit(EVENTS.TOOL_EXECUTED, { tool, args, result });

    if (!result?.success) return; // Skip failed tools

    switch (tool) {
      case 'voxyflow.card.create_unassigned': {
        // Cards previously "unassigned" now belong to the system project
        const title = (result.title as string) || (args.content as string) || 'Card';
        this.syncCardsFromBackend(SYSTEM_PROJECT_ID);
        eventBus.emit(EVENTS.TOAST_SHOW, {
          message: `📝 Card added: ${title.substring(0, 30)}...`,
          type: 'success',
        });
        break;
      }

      case 'voxyflow.project.create':
        // Re-sync project list from backend so sidebar updates
        this.syncProjectsFromBackend();
        eventBus.emit(EVENTS.TOAST_SHOW, { message: `✅ Project created`, type: 'success' });
        break;

      case 'voxyflow.card.create':
        // Re-sync project list (card counts) and re-fetch cards into appState
        this.syncProjectsFromBackend();
        this.syncCardsFromBackend(args.project_id as string);
        eventBus.emit(EVENTS.TOAST_SHOW, { message: `✅ Card created`, type: 'success' });
        break;

      case 'voxyflow.card.move':
        eventBus.emit(EVENTS.CARD_MOVED, { cardId: args.card_id, newStatus: args.status });
        break;

      case 'voxyflow.card.delete':
        eventBus.emit(EVENTS.CARD_DELETED, { cardId: args.card_id });
        break;

      default:
        eventBus.emit(EVENTS.TOAST_SHOW, { message: `🔧 Action: ${tool}`, type: 'info' });
        break;
    }
  }

  /**
   * Re-fetch project list from backend and update AppState + sidebar.
   * Debounced to avoid hammering when a worker creates many items at once.
   */
  private _syncTimer: ReturnType<typeof setTimeout> | null = null;
  private syncProjectsFromBackend(): void {
    if (this._syncTimer) clearTimeout(this._syncTimer);
    this._syncTimer = setTimeout(async () => {
      try {
        const API_URL_BASE = process.env.VOXYFLOW_API_URL || '';
        const [activeResp, archivedResp] = await Promise.all([
          fetch(`${API_URL_BASE}/api/projects?archived=false`),
          fetch(`${API_URL_BASE}/api/projects?archived=true`),
        ]);
        if (!activeResp.ok) return;
        const activeRaw = await activeResp.json();
        const archivedRaw = archivedResp.ok ? await archivedResp.json() : [];

        const mapProject = (p: Record<string, unknown>) => ({
          id: p.id as string,
          name: (p.name || p.title || 'Untitled') as string,
          description: (p.description || '') as string,
          emoji: p.emoji as string | undefined,
          color: p.color as string | undefined,
          localPath: p.local_path as string | undefined,
          createdAt: p.created_at ? new Date(p.created_at as string).getTime() : Date.now(),
          updatedAt: p.updated_at ? new Date(p.updated_at as string).getTime() : Date.now(),
          cards: (p.cards as string[]) || [],
          archived: p.status === 'archived' || (p.archived as boolean) || false,
          isSystem: (p.is_system as boolean) || false,
          deletable: p.deletable !== undefined ? (p.deletable as boolean) : true,
        });

        const allProjects = [
          ...(Array.isArray(activeRaw) ? activeRaw.map(mapProject) : []),
          ...(Array.isArray(archivedRaw) ? archivedRaw.map(mapProject) : []),
        ];
        // Ensure system project is always first
        const sysIdx = allProjects.findIndex(p => p.id === SYSTEM_PROJECT_ID);
        if (sysIdx > 0) {
          const [sysProject] = allProjects.splice(sysIdx, 1);
          allProjects.unshift(sysProject);
        }
        appState.set('projects', allProjects);
        eventBus.emit(EVENTS.PROJECT_CREATED);  // triggers sidebar re-render
      } catch (e) {
        console.error('[ApiClient] syncProjectsFromBackend failed:', e);
      }
    }, 500);  // 500ms debounce
  }

  /**
   * Re-fetch cards for a specific project from backend and update AppState.
   * Debounced per-project to avoid hammering when a worker creates many cards at once.
   */
  private _cardSyncTimers = new Map<string, ReturnType<typeof setTimeout>>();
  private syncCardsFromBackend(projectId?: string): void {
    if (!projectId) return;
    const existing = this._cardSyncTimers.get(projectId);
    if (existing) clearTimeout(existing);
    this._cardSyncTimers.set(projectId, setTimeout(async () => {
      this._cardSyncTimers.delete(projectId);
      try {
        const freshCards = await this.fetchCards(projectId) as Card[];
        // Replace cards for this project in appState
        const otherCards = appState.get('cards').filter(
          (c: Card) => c.projectId !== projectId
        );
        appState.set('cards', [...otherCards, ...freshCards] as Card[]);
        eventBus.emit(EVENTS.CARD_CREATED, null); // triggers KanbanBoard.refreshCards()
      } catch (e) {
        console.error('[ApiClient] syncCardsFromBackend failed:', e);
      }
    }, 800));  // 800ms debounce — lets batch tool calls settle
  }

  connect(): void {
    if (this.ws?.readyState === WebSocket.OPEN) return;

    this.isClosing = false;
    this.updateState('connecting');

    try {
      this.ws = new WebSocket(this.config.url);
      this.setupListeners();
    } catch (error) {
      console.error('[ApiClient] Connection error:', error);
      this.handleDisconnect();
    }
  }

  private setupListeners(): void {
    if (!this.ws) return;

    this.ws.onopen = () => {
      console.log('[ApiClient] Connected');
      this.reconnectAttempts = 0;
      this.updateState('connected');
      this.startHeartbeat();
      this.flushOfflineQueue();
      eventBus.emit(EVENTS.WS_CONNECTED);
    };

    this.ws.onmessage = (event: MessageEvent) => {
      try {
        const message: WebSocketMessage = JSON.parse(event.data);
        this.dispatchMessage(message);
        eventBus.emit(EVENTS.WS_MESSAGE, message);
      } catch (error) {
        console.error('[ApiClient] Failed to parse message:', error);
      }
    };

    this.ws.onerror = (event: Event) => {
      console.error('[ApiClient] WebSocket error:', event);
      eventBus.emit(EVENTS.WS_ERROR, event);
    };

    this.ws.onclose = () => {
      console.log('[ApiClient] Disconnected');
      this.stopHeartbeat();
      if (!this.isClosing) {
        this.handleDisconnect();
      }
      eventBus.emit(EVENTS.WS_DISCONNECTED);
    };
  }

  private dispatchMessage(message: WebSocketMessage): void {
    const handlers = this.handlers.get(message.type);
    if (handlers) {
      handlers.forEach((handler) => {
        try {
          handler(message.payload);
        } catch (error) {
          console.error(`[ApiClient] Handler error for "${message.type}":`, error);
        }
      });
    }

    // Also dispatch to wildcard handlers
    const wildcardHandlers = this.handlers.get('*');
    if (wildcardHandlers) {
      wildcardHandlers.forEach((handler) => {
        try {
          handler({ type: message.type, ...message.payload });
        } catch (error) {
          console.error('[ApiClient] Wildcard handler error:', error);
        }
      });
    }
  }

  send(type: string, payload: Record<string, unknown> = {}): string {
    const id = generateId();
    const message: WebSocketMessage = {
      type,
      payload,
      id,
      timestamp: Date.now(),
    };

    if (this.ws?.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify(message));
    } else {
      // Queue for offline delivery
      this.offlineQueue.push({ type, payload, id, timestamp: Date.now() });
      this.saveOfflineQueue();
      console.log(`[ApiClient] Queued message (offline): ${type}`);
    }

    return id;
  }

  on(type: string, handler: MessageHandler): () => void {
    if (!this.handlers.has(type)) {
      this.handlers.set(type, new Set());
    }
    this.handlers.get(type)!.add(handler);

    return () => {
      this.handlers.get(type)?.delete(handler);
    };
  }

  off(type: string, handler: MessageHandler): void {
    this.handlers.get(type)?.delete(handler);
  }

  close(): void {
    this.isClosing = true;
    this.stopHeartbeat();
    this.clearReconnectTimer();
    if (this.ws) {
      this.ws.close();
      this.ws = null;
    }
    this.updateState('disconnected');
  }

  get connected(): boolean {
    return this.ws?.readyState === WebSocket.OPEN;
  }

  get queueSize(): number {
    return this.offlineQueue.length;
  }

  // --- Reconnection ---

  private handleDisconnect(): void {
    this.updateState('reconnecting');

    if (this.reconnectAttempts >= this.config.reconnectAttempts) {
      console.error('[ApiClient] Max reconnect attempts reached');
      this.updateState('disconnected');
      return;
    }

    const delay = Math.min(
      this.config.reconnectDelay * Math.pow(2, this.reconnectAttempts),
      RECONNECT_MAX_DELAY
    );

    console.log(`[ApiClient] Reconnecting in ${delay}ms (attempt ${this.reconnectAttempts + 1})`);

    this.reconnectTimer = setTimeout(() => {
      this.reconnectAttempts++;
      this.connect();
    }, delay);
  }

  private clearReconnectTimer(): void {
    if (this.reconnectTimer) {
      clearTimeout(this.reconnectTimer);
      this.reconnectTimer = null;
    }
  }

  // --- Heartbeat ---

  private startHeartbeat(): void {
    this.stopHeartbeat();
    this.heartbeatTimer = setInterval(() => {
      if (this.ws?.readyState === WebSocket.OPEN) {
        this.ws.send(JSON.stringify({ type: 'ping', payload: {}, timestamp: Date.now() }));
      }
    }, this.config.heartbeatInterval);
  }

  private stopHeartbeat(): void {
    if (this.heartbeatTimer) {
      clearInterval(this.heartbeatTimer);
      this.heartbeatTimer = null;
    }
  }

  // --- Offline Queue ---

  private async flushOfflineQueue(): Promise<void> {
    if (this.offlineQueue.length === 0) return;

    console.log(`[ApiClient] Flushing ${this.offlineQueue.length} queued messages`);
    const queue = [...this.offlineQueue];
    this.offlineQueue = [];

    for (const msg of queue) {
      if (this.ws?.readyState === WebSocket.OPEN) {
        this.ws.send(JSON.stringify({
          type: msg.type,
          payload: msg.payload,
          id: msg.id,
          timestamp: msg.timestamp,
        }));
      } else {
        // Re-queue if disconnected during flush
        this.offlineQueue.push(msg);
        break;
      }
    }

    this.saveOfflineQueue();
  }

  private saveOfflineQueue(): void {
    try {
      localStorage.setItem('voxyflow_offline_queue', JSON.stringify(this.offlineQueue));
    } catch (e) {
      console.warn('[ApiClient] Failed to save offline queue:', e);
    }
  }

  private loadOfflineQueue(): void {
    try {
      const stored = localStorage.getItem('voxyflow_offline_queue');
      if (stored) {
        this.offlineQueue = JSON.parse(stored);
      }
    } catch (e) {
      console.warn('[ApiClient] Failed to load offline queue:', e);
    }
  }

  // --- HTTP helpers ---

  async fetchAgents(): Promise<AgentInfo[]> {
    try {
      const baseUrl = API_URL || '';
      const response = await fetch(`${baseUrl}/api/agents`);
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      return await response.json() as AgentInfo[];
    } catch (error) {
      console.error('[ApiClient] fetchAgents error:', error);
      return [];
    }
  }

  async fetchCards(projectId: string): Promise<unknown[]> {
    try {
      const baseUrl = API_URL || '';
      const response = await fetch(`${baseUrl}/api/projects/${projectId}/cards`);
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const raw = await response.json() as Array<Record<string, unknown>>;
      // Map snake_case backend fields to camelCase frontend fields
      return raw.map((c) => ({
        ...c,
        projectId: c.project_id,
        agentType: c.agent_type,
        agentAssigned: c.agent_assigned,
        agentContext: c.agent_context,
        dependencies: c.dependency_ids ?? [],
        totalMinutes: c.total_minutes ?? 0,
        checklistProgress: c.checklist_progress ?? undefined,
        createdAt: c.created_at ? new Date(c.created_at as string).getTime() : Date.now(),
        updatedAt: c.updated_at ? new Date(c.updated_at as string).getTime() : Date.now(),
        tags: c.tags ?? [],
        chatHistory: c.chat_history ?? [],
        assignee: c.assignee ?? null,
        watchers: c.watchers ?? '',
        votes: (c.votes as number) ?? 0,
        sprintId: c.sprint_id ?? null,
        files: (c.files as string[]) ?? [],
      }));
    } catch (error) {
      console.error('[ApiClient] fetchCards error:', error);
      return [];
    }
  }

  async patchCard(cardId: string, updates: Record<string, unknown>): Promise<unknown | null> {
    try {
      const baseUrl = API_URL || '';
      const response = await fetch(`${baseUrl}/api/cards/${cardId}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(updates),
      });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      return await response.json();
    } catch (error) {
      console.error('[ApiClient] patchCard error:', error);
      return null;
    }
  }

  async exportProject(projectId: string): Promise<unknown | null> {
    try {
      const baseUrl = API_URL || '';
      const response = await fetch(`${baseUrl}/api/projects/${projectId}/export`);
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      return await response.json();
    } catch (error) {
      console.error('[ApiClient] exportProject error:', error);
      return null;
    }
  }

  async importProject(data: unknown): Promise<{ project_id: string; project_title: string; cards_imported: number } | null> {
    try {
      const baseUrl = API_URL || '';
      const response = await fetch(`${baseUrl}/api/projects/import`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(data),
      });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      return await response.json() as { project_id: string; project_title: string; cards_imported: number };
    } catch (error) {
      console.error('[ApiClient] importProject error:', error);
      return null;
    }
  }

  async fetchTimeEntries(cardId: string): Promise<TimeEntry[]> {
    try {
      const baseUrl = API_URL || '';
      const response = await fetch(`${baseUrl}/api/cards/${cardId}/time`);
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const data = await response.json() as Array<{
        id: string; card_id: string; duration_minutes: number; note?: string; logged_at: string;
      }>;
      return data.map((e) => ({
        id: e.id,
        cardId: e.card_id,
        durationMinutes: e.duration_minutes,
        note: e.note,
        loggedAt: new Date(e.logged_at).getTime(),
      }));
    } catch (error) {
      console.error('[ApiClient] fetchTimeEntries error:', error);
      return [];
    }
  }

  async logTime(cardId: string, durationMinutes: number, note?: string): Promise<TimeEntry | null> {
    try {
      const baseUrl = API_URL || '';
      const response = await fetch(`${baseUrl}/api/cards/${cardId}/time`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ duration_minutes: durationMinutes, note: note || null }),
      });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const e = await response.json() as {
        id: string; card_id: string; duration_minutes: number; note?: string; logged_at: string;
      };
      return {
        id: e.id,
        cardId: e.card_id,
        durationMinutes: e.duration_minutes,
        note: e.note,
        loggedAt: new Date(e.logged_at).getTime(),
      };
    } catch (error) {
      console.error('[ApiClient] logTime error:', error);
      return null;
    }
  }

  async deleteTimeEntry(cardId: string, entryId: string): Promise<boolean> {
    try {
      const baseUrl = API_URL || '';
      const response = await fetch(`${baseUrl}/api/cards/${cardId}/time/${entryId}`, {
        method: 'DELETE',
      });
      return response.ok;
    } catch (error) {
      console.error('[ApiClient] deleteTimeEntry error:', error);
      return false;
    }
  }

  async fetchComments(cardId: string): Promise<CardComment[]> {
    try {
      const baseUrl = API_URL || '';
      const response = await fetch(`${baseUrl}/api/cards/${cardId}/comments`);
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const data = await response.json() as Array<{
        id: string; card_id: string; author: string; content: string; created_at: string;
      }>;
      return data.map((c) => ({
        id: c.id,
        cardId: c.card_id,
        author: c.author,
        content: c.content,
        createdAt: new Date(c.created_at).getTime(),
      }));
    } catch (error) {
      console.error('[ApiClient] fetchComments error:', error);
      return [];
    }
  }

  async addComment(cardId: string, content: string, author = 'User'): Promise<CardComment | null> {
    try {
      const baseUrl = API_URL || '';
      const response = await fetch(`${baseUrl}/api/cards/${cardId}/comments`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ content, author }),
      });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const c = await response.json() as {
        id: string; card_id: string; author: string; content: string; created_at: string;
      };
      return {
        id: c.id,
        cardId: c.card_id,
        author: c.author,
        content: c.content,
        createdAt: new Date(c.created_at).getTime(),
      };
    } catch (error) {
      console.error('[ApiClient] addComment error:', error);
      return null;
    }
  }

  async deleteComment(cardId: string, commentId: string): Promise<boolean> {
    try {
      const baseUrl = API_URL || '';
      const response = await fetch(`${baseUrl}/api/cards/${cardId}/comments/${commentId}`, {
        method: 'DELETE',
      });
      return response.ok;
    } catch (error) {
      console.error('[ApiClient] deleteComment error:', error);
      return false;
    }
  }

  async fetchChecklistItems(cardId: string): Promise<ChecklistItem[]> {
    try {
      const baseUrl = API_URL || '';
      const response = await fetch(`${baseUrl}/api/cards/${cardId}/checklist`);
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const data = await response.json() as Array<{
        id: string; card_id: string; text: string; completed: boolean; position: number; created_at: string;
      }>;
      return data.map((i) => ({
        id: i.id,
        cardId: i.card_id,
        text: i.text,
        completed: i.completed,
        position: i.position,
        createdAt: new Date(i.created_at).getTime(),
      }));
    } catch (error) {
      console.error('[ApiClient] fetchChecklistItems error:', error);
      return [];
    }
  }

  async addChecklistItem(cardId: string, text: string): Promise<ChecklistItem | null> {
    try {
      const baseUrl = API_URL || '';
      const response = await fetch(`${baseUrl}/api/cards/${cardId}/checklist`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ text }),
      });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const i = await response.json() as {
        id: string; card_id: string; text: string; completed: boolean; position: number; created_at: string;
      };
      return { id: i.id, cardId: i.card_id, text: i.text, completed: i.completed, position: i.position, createdAt: new Date(i.created_at).getTime() };
    } catch (error) {
      console.error('[ApiClient] addChecklistItem error:', error);
      return null;
    }
  }

  async updateChecklistItem(cardId: string, itemId: string, updates: { text?: string; completed?: boolean }): Promise<ChecklistItem | null> {
    try {
      const baseUrl = API_URL || '';
      const response = await fetch(`${baseUrl}/api/cards/${cardId}/checklist/${itemId}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(updates),
      });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const i = await response.json() as {
        id: string; card_id: string; text: string; completed: boolean; position: number; created_at: string;
      };
      return { id: i.id, cardId: i.card_id, text: i.text, completed: i.completed, position: i.position, createdAt: new Date(i.created_at).getTime() };
    } catch (error) {
      console.error('[ApiClient] updateChecklistItem error:', error);
      return null;
    }
  }

  async deleteChecklistItem(cardId: string, itemId: string): Promise<boolean> {
    try {
      const baseUrl = API_URL || '';
      const response = await fetch(`${baseUrl}/api/cards/${cardId}/checklist/${itemId}`, { method: 'DELETE' });
      return response.ok;
    } catch (error) {
      console.error('[ApiClient] deleteChecklistItem error:', error);
      return false;
    }
  }

  async fetchAttachments(cardId: string): Promise<CardAttachment[]> {
    try {
      const baseUrl = API_URL || '';
      const response = await fetch(`${baseUrl}/api/cards/${cardId}/attachments`);
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const data = await response.json() as Array<{
        id: string; card_id: string; filename: string; file_size: number; mime_type: string; created_at: string;
      }>;
      return data.map((a) => ({
        id: a.id,
        cardId: a.card_id,
        filename: a.filename,
        fileSize: a.file_size,
        mimeType: a.mime_type,
        createdAt: new Date(a.created_at).getTime(),
      }));
    } catch (error) {
      console.error('[ApiClient] fetchAttachments error:', error);
      return [];
    }
  }

  async uploadAttachment(cardId: string, file: File): Promise<CardAttachment | null> {
    try {
      const baseUrl = API_URL || '';
      const formData = new FormData();
      formData.append('file', file);
      const response = await fetch(`${baseUrl}/api/cards/${cardId}/attachments`, {
        method: 'POST',
        body: formData,
      });
      if (!response.ok) {
        const err = await response.json().catch(() => ({})) as { detail?: string };
        throw new Error(err.detail || `HTTP ${response.status}`);
      }
      const a = await response.json() as {
        id: string; card_id: string; filename: string; file_size: number; mime_type: string; created_at: string;
      };
      return {
        id: a.id,
        cardId: a.card_id,
        filename: a.filename,
        fileSize: a.file_size,
        mimeType: a.mime_type,
        createdAt: new Date(a.created_at).getTime(),
      };
    } catch (error) {
      console.error('[ApiClient] uploadAttachment error:', error);
      return null;
    }
  }

  getAttachmentDownloadUrl(cardId: string, attachmentId: string): string {
    const baseUrl = API_URL || '';
    return `${baseUrl}/api/cards/${cardId}/attachments/${attachmentId}/download`;
  }

  async deleteAttachment(cardId: string, attachmentId: string): Promise<boolean> {
    try {
      const baseUrl = API_URL || '';
      const response = await fetch(`${baseUrl}/api/cards/${cardId}/attachments/${attachmentId}`, {
        method: 'DELETE',
      });
      return response.ok;
    } catch (error) {
      console.error('[ApiClient] deleteAttachment error:', error);
      return false;
    }
  }

  async searchMessages(query: string, projectId?: string, limit = 20): Promise<SearchResult[]> {
    try {
      const baseUrl = API_URL || '';
      const params = new URLSearchParams({ q: query, limit: String(limit) });
      if (projectId) params.set('project_id', projectId);
      const response = await fetch(`${baseUrl}/api/sessions/search/messages?${params}`);
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      return await response.json() as SearchResult[];
    } catch (error) {
      console.error('[ApiClient] searchMessages error:', error);
      return [];
    }
  }

  async fetchTemplates(): Promise<Array<{ id: string; name: string; emoji: string; description: string; color: string; cards: unknown[] }> | null> {
    try {
      const baseUrl = API_URL || '';
      const response = await fetch(`${baseUrl}/api/projects/templates`);
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      return await response.json();
    } catch (error) {
      console.error('[ApiClient] fetchTemplates error:', error);
      return null;
    }
  }

  async createProjectFromTemplate(
    templateId: string,
    data: { title: string; description?: string; emoji?: string; color?: string },
  ): Promise<{ project_id: string; project_title: string; cards_imported: number; template_emoji: string; template_color: string } | null> {
    try {
      const baseUrl = API_URL || '';
      const response = await fetch(`${baseUrl}/api/projects/from-template/${templateId}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(data),
      });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      return await response.json();
    } catch (error) {
      console.error('[ApiClient] createProjectFromTemplate error:', error);
      return null;
    }
  }

  // --- AI Enrichment ---

  async enrichCard(cardId: string): Promise<{
    description: string;
    checklist_items: string[];
    effort: string;
    tags: string[];
  } | null> {
    try {
      const baseUrl = API_URL || '';
      const response = await fetch(`${baseUrl}/api/cards/${cardId}/enrich`, { method: 'POST' });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      return await response.json();
    } catch (error) {
      console.error('[ApiClient] enrichCard error:', error);
      return null;
    }
  }

  // --- Card Relations ---

  async fetchRelations(cardId: string): Promise<import('../types').CardRelation[]> {
    try {
      const baseUrl = API_URL || '';
      const response = await fetch(`${baseUrl}/api/cards/${cardId}/relations`);
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const data = await response.json() as Array<{
        id: string; source_card_id: string; target_card_id: string; relation_type: string;
        created_at: string; related_card_id: string; related_card_title: string; related_card_status: string;
      }>;
      return data.map((r) => ({
        id: r.id,
        sourceCardId: r.source_card_id,
        targetCardId: r.target_card_id,
        relationType: r.relation_type as import('../types').CardRelationType,
        createdAt: r.created_at,
        relatedCardId: r.related_card_id,
        relatedCardTitle: r.related_card_title,
        relatedCardStatus: r.related_card_status,
      }));
    } catch (error) {
      console.error('[ApiClient] fetchRelations error:', error);
      return [];
    }
  }

  async addRelation(cardId: string, targetCardId: string, relationType: string): Promise<import('../types').CardRelation | null> {
    try {
      const baseUrl = API_URL || '';
      const response = await fetch(`${baseUrl}/api/cards/${cardId}/relations`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ target_card_id: targetCardId, relation_type: relationType }),
      });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const r = await response.json() as {
        id: string; source_card_id: string; target_card_id: string; relation_type: string;
        created_at: string; related_card_id: string; related_card_title: string; related_card_status: string;
      };
      return {
        id: r.id,
        sourceCardId: r.source_card_id,
        targetCardId: r.target_card_id,
        relationType: r.relation_type as import('../types').CardRelationType,
        createdAt: r.created_at,
        relatedCardId: r.related_card_id,
        relatedCardTitle: r.related_card_title,
        relatedCardStatus: r.related_card_status,
      };
    } catch (error) {
      console.error('[ApiClient] addRelation error:', error);
      return null;
    }
  }

  async deleteRelation(cardId: string, relationId: string): Promise<boolean> {
    try {
      const baseUrl = API_URL || '';
      const response = await fetch(`${baseUrl}/api/cards/${cardId}/relations/${relationId}`, { method: 'DELETE' });
      return response.ok;
    } catch (error) {
      console.error('[ApiClient] deleteRelation error:', error);
      return false;
    }
  }

  // --- History ---

  async fetchCardHistory(cardId: string): Promise<import('../types').CardHistoryEntry[]> {
    try {
      const baseUrl = API_URL || '';
      const response = await fetch(`${baseUrl}/api/cards/${cardId}/history`);
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const data = await response.json() as Array<{
        id: string; card_id: string; field_changed: string;
        old_value: string | null; new_value: string | null;
        changed_at: string; changed_by: string;
      }>;
      return data.map((e) => ({
        id: e.id,
        cardId: e.card_id,
        fieldChanged: e.field_changed,
        oldValue: e.old_value,
        newValue: e.new_value,
        changedAt: e.changed_at,
        changedBy: e.changed_by,
      }));
    } catch (error) {
      console.error('[ApiClient] fetchCardHistory error:', error);
      return [];
    }
  }

// --- Voting ---

  async voteCard(cardId: string): Promise<number | null> {
    try {
      const baseUrl = API_URL || '';
      const response = await fetch(`${baseUrl}/api/cards/${cardId}/vote`, { method: 'POST' });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const data = await response.json() as { votes: number };
      return data.votes;
    } catch (error) {
      console.error('[ApiClient] voteCard error:', error);
      return null;
    }
  }

  async unvoteCard(cardId: string): Promise<number | null> {
    try {
      const baseUrl = API_URL || '';
      const response = await fetch(`${baseUrl}/api/cards/${cardId}/vote`, { method: 'DELETE' });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const data = await response.json() as { votes: number };
      return data.votes;
    } catch (error) {
      console.error('[ApiClient] unvoteCard error:', error);
      return null;
    }
  }

  async cloneCardToProject(cardId: string, targetProjectId: string): Promise<import('../types').Card | null> {
    try {
      const baseUrl = API_URL || '';
      const response = await fetch(`${baseUrl}/api/cards/${cardId}/clone-to/${targetProjectId}`, { method: 'POST' });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const c = await response.json() as Record<string, unknown>;
      return {
        ...(c as unknown as import('../types').Card),
        projectId: c.project_id as string,
        agentType: c.agent_type as string | undefined,
        agentAssigned: c.agent_assigned as string | undefined,
        agentContext: c.agent_context as string | undefined,
        dependencies: (c.dependency_ids as string[]) ?? [],
        totalMinutes: (c.total_minutes as number) ?? 0,
        checklistProgress: (c.checklist_progress as import('../types').ChecklistProgress) ?? undefined,
        createdAt: c.created_at ? new Date(c.created_at as string).getTime() : Date.now(),
        updatedAt: c.updated_at ? new Date(c.updated_at as string).getTime() : Date.now(),
        tags: (c.tags as string[]) ?? [],
        chatHistory: [],
        assignee: (c.assignee as string) ?? null,
        watchers: (c.watchers as string) ?? '',
        votes: (c.votes as number) ?? 0,
        sprintId: (c.sprint_id as string) ?? null,
        files: (c.files as string[]) ?? [],
      } as import('../types').Card;
    } catch (error) {
      console.error('[ApiClient] cloneCardToProject error:', error);
      return null;
    }
  }

  async moveCardToProject(cardId: string, targetProjectId: string): Promise<import('../types').Card | null> {
    try {
      const baseUrl = API_URL || '';
      const response = await fetch(`${baseUrl}/api/cards/${cardId}/move-to/${targetProjectId}`, { method: 'POST' });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const c = await response.json() as Record<string, unknown>;
      return {
        ...(c as unknown as import('../types').Card),
        projectId: c.project_id as string,
        agentType: c.agent_type as string | undefined,
        agentAssigned: c.agent_assigned as string | undefined,
        agentContext: c.agent_context as string | undefined,
        dependencies: (c.dependency_ids as string[]) ?? [],
        totalMinutes: (c.total_minutes as number) ?? 0,
        checklistProgress: (c.checklist_progress as import('../types').ChecklistProgress) ?? undefined,
        createdAt: c.created_at ? new Date(c.created_at as string).getTime() : Date.now(),
        updatedAt: c.updated_at ? new Date(c.updated_at as string).getTime() : Date.now(),
        tags: (c.tags as string[]) ?? [],
        chatHistory: [],
        assignee: (c.assignee as string) ?? null,
        watchers: (c.watchers as string) ?? '',
        votes: (c.votes as number) ?? 0,
        sprintId: (c.sprint_id as string) ?? null,
        files: (c.files as string[]) ?? [],
      } as import('../types').Card;
    } catch (error) {
      console.error('[ApiClient] moveCardToProject error:', error);
      return null;
    }
  }

  async duplicateCard(cardId: string): Promise<import('../types').Card | null> {
    try {
      const baseUrl = API_URL || '';
      const response = await fetch(`${baseUrl}/api/cards/${cardId}/duplicate`, { method: 'POST' });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const c = await response.json() as Record<string, unknown>;
      return {
        ...(c as unknown as import('../types').Card),
        projectId: c.project_id as string,
        agentType: c.agent_type as string | undefined,
        agentAssigned: c.agent_assigned as string | undefined,
        agentContext: c.agent_context as string | undefined,
        dependencies: (c.dependency_ids as string[]) ?? [],
        totalMinutes: (c.total_minutes as number) ?? 0,
        checklistProgress: (c.checklist_progress as import('../types').ChecklistProgress) ?? undefined,
        createdAt: c.created_at ? new Date(c.created_at as string).getTime() : Date.now(),
        updatedAt: c.updated_at ? new Date(c.updated_at as string).getTime() : Date.now(),
        tags: (c.tags as string[]) ?? [],
        chatHistory: [],
        assignee: (c.assignee as string) ?? null,
        watchers: (c.watchers as string) ?? '',
        votes: (c.votes as number) ?? 0,
        sprintId: (c.sprint_id as string) ?? null,
        files: (c.files as string[]) ?? [],
      } as import('../types').Card;
    } catch (error) {
      console.error('[ApiClient] duplicateCard error:', error);
      return null;
    }
  }

  async executeCard(cardId: string): Promise<{ prompt: string; projectName?: string } | null> {
    try {
      const baseUrl = API_URL || '';
      const response = await fetch(`${baseUrl}/api/cards/${cardId}/execute`, { method: 'POST' });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      return await response.json() as { prompt: string; projectName?: string };
    } catch (error) {
      console.error('[ApiClient] executeCard error:', error);
      return null;
    }
  }

  // --- Sprint API ---

  async listSprints(projectId: string): Promise<import('../types').Sprint[]> {
    try {
      const baseUrl = API_URL || '';
      const response = await fetch(`${baseUrl}/api/projects/${projectId}/sprints`);
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const data = await response.json() as Array<{
        id: string; project_id: string; name: string; goal: string | null;
        start_date: string; end_date: string; status: string; created_at: string; card_count: number;
      }>;
      return data.map((s) => ({
        id: s.id, projectId: s.project_id, name: s.name, goal: s.goal,
        startDate: s.start_date, endDate: s.end_date, status: s.status as import('../types').SprintStatus,
        createdAt: s.created_at, cardCount: s.card_count,
      }));
    } catch (error) {
      console.error('[ApiClient] listSprints error:', error);
      return [];
    }
  }

  async createSprint(projectId: string, data: { name: string; goal?: string; start_date: string; end_date: string }): Promise<import('../types').Sprint | null> {
    try {
      const baseUrl = API_URL || '';
      const response = await fetch(`${baseUrl}/api/projects/${projectId}/sprints`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(data),
      });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const s = await response.json() as { id: string; project_id: string; name: string; goal: string | null; start_date: string; end_date: string; status: string; created_at: string; card_count: number };
      return { id: s.id, projectId: s.project_id, name: s.name, goal: s.goal, startDate: s.start_date, endDate: s.end_date, status: s.status as import('../types').SprintStatus, createdAt: s.created_at, cardCount: s.card_count };
    } catch (error) {
      console.error('[ApiClient] createSprint error:', error);
      return null;
    }
  }

  async updateSprint(projectId: string, sprintId: string, data: { name?: string; goal?: string; start_date?: string; end_date?: string }): Promise<import('../types').Sprint | null> {
    try {
      const baseUrl = API_URL || '';
      const response = await fetch(`${baseUrl}/api/projects/${projectId}/sprints/${sprintId}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(data),
      });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const s = await response.json() as { id: string; project_id: string; name: string; goal: string | null; start_date: string; end_date: string; status: string; created_at: string; card_count: number };
      return { id: s.id, projectId: s.project_id, name: s.name, goal: s.goal, startDate: s.start_date, endDate: s.end_date, status: s.status as import('../types').SprintStatus, createdAt: s.created_at, cardCount: s.card_count };
    } catch (error) {
      console.error('[ApiClient] updateSprint error:', error);
      return null;
    }
  }

  async deleteSprint(projectId: string, sprintId: string): Promise<boolean> {
    try {
      const baseUrl = API_URL || '';
      const response = await fetch(`${baseUrl}/api/projects/${projectId}/sprints/${sprintId}`, { method: 'DELETE' });
      return response.ok;
    } catch (error) {
      console.error('[ApiClient] deleteSprint error:', error);
      return false;
    }
  }

  async startSprint(projectId: string, sprintId: string): Promise<import('../types').Sprint | null> {
    try {
      const baseUrl = API_URL || '';
      const response = await fetch(`${baseUrl}/api/projects/${projectId}/sprints/${sprintId}/start`, { method: 'POST' });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const s = await response.json() as { id: string; project_id: string; name: string; goal: string | null; start_date: string; end_date: string; status: string; created_at: string; card_count: number };
      return { id: s.id, projectId: s.project_id, name: s.name, goal: s.goal, startDate: s.start_date, endDate: s.end_date, status: s.status as import('../types').SprintStatus, createdAt: s.created_at, cardCount: s.card_count };
    } catch (error) {
      console.error('[ApiClient] startSprint error:', error);
      return null;
    }
  }

  async completeSprint(projectId: string, sprintId: string): Promise<import('../types').Sprint | null> {
    try {
      const baseUrl = API_URL || '';
      const response = await fetch(`${baseUrl}/api/projects/${projectId}/sprints/${sprintId}/complete`, { method: 'POST' });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const s = await response.json() as { id: string; project_id: string; name: string; goal: string | null; start_date: string; end_date: string; status: string; created_at: string; card_count: number };
      return { id: s.id, projectId: s.project_id, name: s.name, goal: s.goal, startDate: s.start_date, endDate: s.end_date, status: s.status as import('../types').SprintStatus, createdAt: s.created_at, cardCount: s.card_count };
    } catch (error) {
      console.error('[ApiClient] completeSprint error:', error);
      return null;
    }
  }

  // --- State ---

  private updateState(state: ConnectionState): void {
    appState.setConnectionState(state);
  }
}

// Global singleton
export const apiClient = new ApiClient();
