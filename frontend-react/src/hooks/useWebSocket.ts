import { useCallback, useEffect, useRef, useState } from 'react';
import type { ConnectionState, WebSocketMessage } from '../types';

// --- Constants (mirrored from vanilla frontend) ---
const RECONNECT_MAX_ATTEMPTS = 10;
const RECONNECT_BASE_DELAY = 1000; // ms
const RECONNECT_MAX_DELAY = 30000; // ms
const HEARTBEAT_INTERVAL = 30000; // 30s

function getWsUrl(): string {
  if (typeof window === 'undefined') return 'ws://localhost:8000/ws';
  const proto = window.location.protocol === 'https:' ? 'wss' : 'ws';
  return `${proto}://${window.location.host}/ws`;
}

function generateId(): string {
  return `${Date.now()}-${Math.random().toString(36).slice(2, 9)}`;
}

export type MessageHandler = (payload: Record<string, unknown>) => void;

export interface UseWebSocketReturn {
  /** Current connection state */
  connectionState: ConnectionState;
  /** Send a typed message over the socket. Returns the message id. */
  send: (type: string, payload?: Record<string, unknown>) => string;
  /** Subscribe to messages of a given type. Returns unsubscribe fn. Use '*' for wildcard. */
  subscribe: (type: string, handler: MessageHandler) => () => void;
  /** Whether the socket is currently open */
  connected: boolean;
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
 * Offline queue is handled separately in step 5c.
 */
export function useWebSocket(): UseWebSocketReturn {
  const wsRef = useRef<WebSocket | null>(null);
  const [connectionState, setConnectionState] = useState<ConnectionState>('disconnected');

  // Mutable refs for reconnection state (avoid re-render on every attempt)
  const reconnectAttemptsRef = useRef(0);
  const reconnectTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const heartbeatTimerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const isClosingRef = useRef(false);
  const handlersRef = useRef<Map<string, Set<MessageHandler>>>(new Map());

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
      };

      ws.onmessage = (event: MessageEvent) => {
        try {
          const message: WebSocketMessage = JSON.parse(event.data);
          dispatchMessage(message);
        } catch (error) {
          console.error('[useWebSocket] Failed to parse message:', error);
        }
      };

      ws.onerror = (event: Event) => {
        console.error('[useWebSocket] WebSocket error:', event);
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
  }, [startHeartbeat, stopHeartbeat, dispatchMessage, handleDisconnect]);

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
    const message: WebSocketMessage = {
      type,
      payload,
      id,
      timestamp: Date.now(),
    };

    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify(message));
    } else {
      console.warn(`[useWebSocket] Cannot send "${type}" — not connected`);
    }

    return id;
  }, []);

  const subscribe = useCallback((type: string, handler: MessageHandler): (() => void) => {
    if (!handlersRef.current.has(type)) {
      handlersRef.current.set(type, new Set());
    }
    handlersRef.current.get(type)!.add(handler);

    return () => {
      handlersRef.current.get(type)?.delete(handler);
    };
  }, []);

  return {
    connectionState,
    send,
    subscribe,
    connected: connectionState === 'connected',
  };
}
