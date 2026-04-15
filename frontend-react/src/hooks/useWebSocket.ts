import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import type { ConnectionState, WebSocketMessage } from '../types';
import { useOfflineQueue, type QueuedMessage } from './useOfflineQueue';

// --- Constants (mirrored from vanilla frontend) ---
const RECONNECT_MAX_ATTEMPTS = 10;
const RECONNECT_BASE_DELAY = 1000; // ms
const RECONNECT_MAX_DELAY = 30000; // ms
const HEARTBEAT_INTERVAL = 30000; // 30s
const PENDING_ACKS_STORAGE_KEY = 'voxyflow_pending_acks';
const ACK_TIMEOUT_MS = 15000; // 15s

function getWsUrl(): string {
  if (typeof window === 'undefined') return 'ws://localhost:8000/ws';
  const proto = window.location.protocol === 'https:' ? 'wss' : 'ws';
  return `${proto}://${window.location.host}/ws`;
}

function generateId(): string {
  return `${Date.now()}-${Math.random().toString(36).slice(2, 9)}`;
}

function loadPendingAcks(): Map<string, QueuedMessage> {
  try {
    const stored = localStorage.getItem(PENDING_ACKS_STORAGE_KEY);
    if (stored) {
      const arr = JSON.parse(stored) as [string, QueuedMessage][];
      return new Map(arr);
    }
  } catch { /* ignore */ }
  return new Map();
}

function savePendingAcks(map: Map<string, QueuedMessage>): void {
  try {
    localStorage.setItem(PENDING_ACKS_STORAGE_KEY, JSON.stringify([...map.entries()]));
  } catch { /* ignore */ }
}

export type MessageHandler = (payload: Record<string, unknown>) => void;

export interface UseWebSocketReturn {
  /** Current connection state */
  connectionState: ConnectionState;
  /** Send a typed message over the socket. Queues if offline. Returns the message id. */
  send: (type: string, payload?: Record<string, unknown>) => string;
  /** Subscribe to messages of a given type. Returns unsubscribe fn. Use '*' for wildcard. */
  subscribe: (type: string, handler: MessageHandler) => () => void;
  /** Whether the socket is currently open */
  connected: boolean;
  /** Number of messages waiting in the offline queue */
  queueSize: number;
}

/**
 * Core WebSocket lifecycle hook.
 *
 * Manages a single persistent WebSocket connection with:
 * - Exponential backoff reconnection (same timing as vanilla ApiClient)
 * - Heartbeat/ping keepalive
 * - Message handler registry (subscribe/unsubscribe)
 * - Connection state tracking
 *
 * Offline queue integration: messages sent while disconnected are queued
 * to localStorage and flushed in order on reconnect (step 5c).
 */
export function useWebSocket(): UseWebSocketReturn {
  const wsRef = useRef<WebSocket | null>(null);
  const [connectionState, setConnectionState] = useState<ConnectionState>('disconnected');
  const { pendingCount, enqueue, flush } = useOfflineQueue();

  // Mutable refs for reconnection state (avoid re-render on every attempt)
  const reconnectAttemptsRef = useRef(0);
  const reconnectTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const heartbeatTimerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const isClosingRef = useRef(false);
  const handlersRef = useRef<Map<string, Set<MessageHandler>>>(new Map());

  // Pending ACK tracking — messages sent but not yet confirmed by backend
  const pendingAcksRef = useRef<Map<string, QueuedMessage>>(loadPendingAcks());
  const pendingAckTimersRef = useRef<Map<string, ReturnType<typeof setTimeout>>>(new Map());

  // --- Heartbeat ---

  const stopHeartbeat = useCallback(() => {
    if (heartbeatTimerRef.current) {
      clearInterval(heartbeatTimerRef.current);
      heartbeatTimerRef.current = null;
    }
  }, []);

  const startHeartbeat = useCallback(() => {
    stopHeartbeat();
    heartbeatTimerRef.current = setInterval(() => {
      if (wsRef.current?.readyState === WebSocket.OPEN) {
        wsRef.current.send(JSON.stringify({ type: 'ping', payload: {}, timestamp: Date.now() }));
      }
    }, HEARTBEAT_INTERVAL);
  }, [stopHeartbeat]);

  // --- Reconnection ---

  const clearReconnectTimer = useCallback(() => {
    if (reconnectTimerRef.current) {
      clearTimeout(reconnectTimerRef.current);
      reconnectTimerRef.current = null;
    }
  }, []);

  // --- Message dispatch ---

  const dispatchMessage = useCallback((message: WebSocketMessage) => {
    const handlers = handlersRef.current.get(message.type);
    if (handlers) {
      handlers.forEach((handler) => {
        try {
          handler(message.payload);
        } catch (error) {
          console.error(`[useWebSocket] Handler error for "${message.type}":`, error);
        }
      });
    }

    // Wildcard handlers
    const wildcardHandlers = handlersRef.current.get('*');
    if (wildcardHandlers) {
      wildcardHandlers.forEach((handler) => {
        try {
          handler({ type: message.type, ...message.payload });
        } catch (error) {
          console.error('[useWebSocket] Wildcard handler error:', error);
        }
      });
    }
  }, []);

  // --- Connect (defined as ref to allow self-referencing from handleDisconnect) ---

  const connectRef = useRef<() => void>(() => {});

  const handleDisconnect = useCallback(() => {
    setConnectionState('reconnecting');

    if (reconnectAttemptsRef.current >= RECONNECT_MAX_ATTEMPTS) {
      console.error('[useWebSocket] Max reconnect attempts reached');
      setConnectionState('disconnected');
      return;
    }

    const delay = Math.min(
      RECONNECT_BASE_DELAY * Math.pow(2, reconnectAttemptsRef.current),
      RECONNECT_MAX_DELAY,
    );

    console.log(
      `[useWebSocket] Reconnecting in ${delay}ms (attempt ${reconnectAttemptsRef.current + 1})`,
    );

    reconnectTimerRef.current = setTimeout(() => {
      reconnectAttemptsRef.current++;
      connectRef.current();
    }, delay);
  }, []);

  const connect = useCallback(() => {
    if (wsRef.current?.readyState === WebSocket.OPEN) return;

    isClosingRef.current = false;
    setConnectionState('connecting');

    try {
      const ws = new WebSocket(getWsUrl());
      wsRef.current = ws;

      ws.onopen = () => {
        console.log('[useWebSocket] Connected');
        reconnectAttemptsRef.current = 0;
        setConnectionState('connected');
        startHeartbeat();
        dispatchMessage({ type: 'ws:connected', payload: {} });

        // Resend messages that were sent but never ACK'd
        if (pendingAcksRef.current.size > 0) {
          console.log(`[useWebSocket] Resending ${pendingAcksRef.current.size} unACK'd messages`);
          for (const [, msg] of pendingAcksRef.current) {
            if (ws.readyState === WebSocket.OPEN) {
              ws.send(JSON.stringify({ type: msg.type, payload: msg.payload, id: msg.id, timestamp: msg.timestamp }));
            }
          }
        }

        // Flush any messages queued while offline
        flush((msg: QueuedMessage) => {
          if (ws.readyState === WebSocket.OPEN) {
            ws.send(JSON.stringify({
              type: msg.type,
              payload: msg.payload,
              id: msg.id,
              timestamp: msg.timestamp,
            }));
            return true;
          }
          return false;
        });
      };

      ws.onmessage = (event: MessageEvent) => {
        try {
          const message: WebSocketMessage = JSON.parse(event.data);

          // Handle ACK internally — don't dispatch to subscribers
          if (message.type === 'message:ack') {
            const messageId = (message.payload as Record<string, unknown>)?.messageId as string;
            if (messageId && pendingAcksRef.current.has(messageId)) {
              const timer = pendingAckTimersRef.current.get(messageId);
              if (timer) { clearTimeout(timer); pendingAckTimersRef.current.delete(messageId); }
              pendingAcksRef.current.delete(messageId);
              savePendingAcks(pendingAcksRef.current);
            }
            return;
          }

          dispatchMessage(message);
        } catch (error) {
          console.error('[useWebSocket] Failed to parse message:', error);
        }
      };

      ws.onerror = () => {
        // Browser WebSocket error events carry no detail for security reasons.
        // onclose fires immediately after and handles reconnection.
      };

      ws.onclose = () => {
        console.log('[useWebSocket] Disconnected');
        stopHeartbeat();
        if (!isClosingRef.current) {
          handleDisconnect();
        }
      };
    } catch (error) {
      console.error('[useWebSocket] Connection error:', error);
      handleDisconnect();
    }
  }, [startHeartbeat, stopHeartbeat, dispatchMessage, handleDisconnect, flush]);

  // Keep connectRef in sync
  useEffect(() => {
    connectRef.current = connect;
  }, [connect]);

  // --- Lifecycle: connect on mount, cleanup on unmount ---

  useEffect(() => {
    connect();

    return () => {
      isClosingRef.current = true;
      stopHeartbeat();
      clearReconnectTimer();
      // Clear all pending ACK timers
      for (const timer of pendingAckTimersRef.current.values()) {
        clearTimeout(timer);
      }
      pendingAckTimersRef.current.clear();
      if (wsRef.current) {
        wsRef.current.close();
        wsRef.current = null;
      }
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // --- Public API ---

  const send = useCallback((type: string, payload: Record<string, unknown> = {}): string => {
    const id = generateId();
    const timestamp = Date.now();

    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({ type, payload, id, timestamp }));
    } else {
      // Queue for offline delivery
      enqueue({ type, payload, id, timestamp });
    }

    // Track chat:message for ACK — covers both sent and enqueued messages
    if (type === 'chat:message') {
      const messageId = payload.messageId as string | undefined;
      if (messageId) {
        const queued: QueuedMessage = { type, payload, id, timestamp };
        pendingAcksRef.current.set(messageId, queued);
        savePendingAcks(pendingAcksRef.current);

        // Timeout: if no ACK within 15s, move to offline queue for retry
        const timer = setTimeout(() => {
          pendingAckTimersRef.current.delete(messageId);
          if (pendingAcksRef.current.has(messageId)) {
            const msg = pendingAcksRef.current.get(messageId)!;
            pendingAcksRef.current.delete(messageId);
            savePendingAcks(pendingAcksRef.current);
            console.warn(`[useWebSocket] No ACK for message ${messageId} after ${ACK_TIMEOUT_MS}ms, re-queuing`);
            enqueue(msg);
          }
        }, ACK_TIMEOUT_MS);
        pendingAckTimersRef.current.set(messageId, timer);
      }
    }

    return id;
  }, [enqueue]);

  const subscribe = useCallback((type: string, handler: MessageHandler): (() => void) => {
    if (!handlersRef.current.has(type)) {
      handlersRef.current.set(type, new Set());
    }
    handlersRef.current.get(type)!.add(handler);

    return () => {
      handlersRef.current.get(type)?.delete(handler);
    };
  }, []);

  const connected = connectionState === 'connected';

  return useMemo(
    () => ({
      connectionState,
      send,
      subscribe,
      connected,
      queueSize: pendingCount,
    }),
    [connectionState, send, subscribe, connected, pendingCount],
  );
}
