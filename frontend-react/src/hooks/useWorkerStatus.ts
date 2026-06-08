import { useCallback } from 'react';
import { useWorkerStore, type WorkerInfo } from '../stores/useWorkerStore';

/**
 * useWorkerStatus — derives per-card worker activity from useWorkerStore.
 *
 * The store is kept live by useWorkerSync via the WS task:* events, so
 * `isCardActive` flips the instant a worker starts (task:started) or finishes
 * (task:completed/cancelled) — no 3s polling lag, no redundant fetches.
 *
 * The `workspaceId` arg scopes the returned `sessions` list; `isCardActive`
 * matches on cardId across all tracked workers (a card belongs to one
 * workspace, so cross-workspace collisions don't happen).
 */
const ACTIVE_STATUSES = new Set<WorkerInfo['status']>(['pending', 'running']);

export function useWorkerStatus(workspaceId: string) {
  // Subscribe to the whole worker map so any task:* event re-renders consumers.
  const workers = useWorkerStore((s) => s.workers);

  const sessions = Object.values(workers).filter(
    (w) => !workspaceId || w.workspaceId === workspaceId,
  );

  const isCardActive = useCallback(
    (cardId: string): boolean =>
      Object.values(workers).some(
        (w) => w.cardId === cardId && ACTIVE_STATUSES.has(w.status),
      ),
    [workers],
  );

  return { isCardActive, sessions };
}
