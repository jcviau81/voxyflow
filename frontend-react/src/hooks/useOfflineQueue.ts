import { useCallback, useEffect, useRef, useState } from 'react';

const STORAGE_KEY = 'voxyflow_offline_queue';

export interface QueuedMessage {
  type: string;
  payload: Record<string, unknown>;
  id: string;
  timestamp: number;
}

export interface UseOfflineQueueReturn {
  /** Number of messages waiting in the queue */
  pendingCount: number;
  /** Add a message to the offline queue */
  enqueue: (msg: QueuedMessage) => void;
  /** Flush queued messages via the provided sender. Re-queues on failure. */
  flush: (sender: (msg: QueuedMessage) => boolean) => void;
}

function loadQueue(): QueuedMessage[] {
  try {
    const stored = localStorage.getItem(STORAGE_KEY);
    if (stored) {
      return JSON.parse(stored) as QueuedMessage[];
    }
  } catch (e) {
    console.warn('[useOfflineQueue] Failed to load from localStorage:', e);
  }
  return [];
}

function saveQueue(queue: QueuedMessage[]): void {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(queue));
  } catch (e) {
    console.warn('[useOfflineQueue] Failed to save to localStorage:', e);
  }
}

/**
 * Offline message queue that persists to localStorage.
 *
 * Mirrors the vanilla ApiClient offline queue:
 * - Queue messages when WebSocket is disconnected
 * - Persist to localStorage so messages survive page refresh
 * - Flush in order on reconnect, re-queue if connection drops mid-flush
 */
export function useOfflineQueue(): UseOfflineQueueReturn {
  const queueRef = useRef<QueuedMessage[]>(loadQueue());
  const [pendingCount, setPendingCount] = useState(queueRef.current.length);

  // Sync count helper
  const syncCount = useCallback(() => {
    setPendingCount(queueRef.current.length);
  }, []);

  const enqueue = useCallback((msg: QueuedMessage) => {
    queueRef.current.push(msg);
    saveQueue(queueRef.current);
    syncCount();
    console.log(`[useOfflineQueue] Queued message (offline): ${msg.type}`);
  }, [syncCount]);

  const flush = useCallback((sender: (msg: QueuedMessage) => boolean) => {
    if (queueRef.current.length === 0) return;

    console.log(`[useOfflineQueue] Flushing ${queueRef.current.length} queued messages`);
    const toSend = [...queueRef.current];
    queueRef.current = [];

    for (const msg of toSend) {
      const sent = sender(msg);
      if (!sent) {
        // Re-queue this and all remaining messages
        queueRef.current.push(msg);
        const idx = toSend.indexOf(msg);
        queueRef.current.push(...toSend.slice(idx + 1));
        break;
      }
    }

    saveQueue(queueRef.current);
    syncCount();
  }, [syncCount]);

  // On mount, sync the count from whatever was loaded from localStorage
  useEffect(() => {
    syncCount();
  }, [syncCount]);

  return { pendingCount, enqueue, flush };
}
