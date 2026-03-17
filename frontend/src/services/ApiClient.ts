import { WebSocketMessage, ApiClientConfig, ConnectionState } from '../types';
import { eventBus } from '../utils/EventBus';
import { EVENTS, WS_URL, RECONNECT_MAX_ATTEMPTS, RECONNECT_BASE_DELAY, RECONNECT_MAX_DELAY, HEARTBEAT_INTERVAL } from '../utils/constants';
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

  // --- State ---

  private updateState(state: ConnectionState): void {
    appState.setConnectionState(state);
  }
}

// Global singleton
export const apiClient = new ApiClient();
