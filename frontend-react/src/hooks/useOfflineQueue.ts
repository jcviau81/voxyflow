import { useCallback, useEffect, useRef, useState } from 'react';

const STORAGE_KEY = 'voxyflow_offline_queue';
const SESSION_FLAG_KEY = 'voxyflow_session_active';
// Stale-entry cutoff. Legitimate offline queueing (brief WiFi blip) resolves
// in seconds; anything older than this is almost certainly a message that sat
// through a backend restart — flushing it would replay against a wiped
// idempotency cache. Applied on load AND on flush so the in-session restart
// path (WS auto-reconnects, sessionStorage flag still set) is also covered.
const MAX_QUEUE_AGE_MS = 60_000;

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
  /** Drop every queued message. Used when the backend restarted underneath us
   *  — those messages targeted a process that no longer exists, replaying them
   *  against a fresh idempotency cache would re-trigger orchestration. */
  clear: () => void;
}

// Fresh-session guard: runs once per page load, before any queue read.
//
// The offline queue is scoped to a single browser session. If we find it
// populated on a fresh load (sessionStorage flag absent), those messages
// were left over from a previous session where the backend likely
// restarted — replaying them now would re-trigger orchestration for
// messages the backend's in-memory idempotency cache (main.py:66-83)
// no longer remembers, replaying the last ~N user turns. Regression of
// fix #22 (0d5d10c) which handled pendingAcks but left this queue.
let _sessionGuardApplied = false;
function _applyFreshSessionGuard(): void {
  if (_sessionGuardApplied) return;
  _sessionGuardApplied = true;
  try {
    const active = sessionStorage.getItem(SESSION_FLAG_KEY);
    if (!active) {
      const prior = localStorage.getItem(STORAGE_KEY);
      if (prior && prior !== '[]') {
        console.log('[useOfflineQueue] Fresh session — discarding stale offline queue to avoid replay');
        localStorage.removeItem(STORAGE_KEY);
      }
      sessionStorage.setItem(SESSION_FLAG_KEY, '1');
    }
  } catch {
    // sessionStorage may throw in private / incognito mode — best-effort.
  }
}

function _dropStale(queue: QueuedMessage[]): QueuedMessage[] {
  const now = Date.now();
  const fresh = queue.filter((m) => now - (m.timestamp ?? 0) <= MAX_QUEUE_AGE_MS);
  const dropped = queue.length - fresh.length;
  if (dropped > 0) {
    console.log(`[useOfflineQueue] Dropped ${dropped} stale queued message(s) (>${MAX_QUEUE_AGE_MS}ms old)`);
  }
  return fresh;
}

function loadQueue(): QueuedMessage[] {
  _applyFreshSessionGuard();
  try {
    const stored = localStorage.getItem(STORAGE_KEY);
    if (stored) {
      const parsed = JSON.parse(stored) as QueuedMessage[];
      return _dropStale(parsed);
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
    // Drop entries that aged past the cutoff while we were disconnected.
    // This is the in-session defence against the backend-restart replay:
    // the WS reconnects automatically without a page reload (so the
    // sessionStorage guard does not fire), but queued messages are now
    // older than any legitimate offline-blip could explain.
    queueRef.current = _dropStale(queueRef.current);
    if (queueRef.current.length === 0) {
      saveQueue(queueRef.current);
      syncCount();
      return;
    }

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

  const clear = useCallback(() => {
    const dropped = queueRef.current.length;
    queueRef.current = [];
    saveQueue(queueRef.current);
    syncCount();
    if (dropped > 0) {
      console.log(`[useOfflineQueue] Cleared ${dropped} queued message(s)`);
    }
  }, [syncCount]);

  // On mount, sync the count from whatever was loaded from localStorage
  useEffect(() => {
    syncCount();
  }, [syncCount]);

  return { pendingCount, enqueue, flush, clear };
}
