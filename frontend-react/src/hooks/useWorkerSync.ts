/**
 * useWorkerSync — wires WebSocket subscriptions to the useWorkerStore.
 *
 * Mount once in AppShell. Handles:
 *   - Initial snapshot load on mount
 *   - WS event subscriptions for real-time updates
 *   - Re-sync on WS reconnect
 *   - Re-sync on tab visibility resume
 *   - Periodic TTL purge of expired tasks
 */

import { useEffect, useRef } from 'react';
import { useWS } from '../providers/WebSocketProvider';
import { useProjectStore } from '../stores/useProjectStore';
import { useWorkerStore } from '../stores/useWorkerStore';

export function useWorkerSync(): void {
  const { subscribe } = useWS();
  const currentProjectId = useProjectStore((s) => s.currentProjectId);
  const projectIdRef = useRef(currentProjectId);
  projectIdRef.current = currentProjectId;

  const {
    loadSnapshot,
    handleTaskStarted,
    handleTaskProgress,
    handleTaskCompleted,
    handleTaskCancelled,
    handleToolExecuted,
    handleCliSessionStarted,
    handleCliSessionEnded,
    purgeExpired,
  } = useWorkerStore();

  // ── Load snapshot on mount and project change ──────────────────────────
  useEffect(() => {
    void loadSnapshot(currentProjectId);
  }, [currentProjectId, loadSnapshot]);

  // ── WS event subscriptions ─────────────────────────────────────────────
  useEffect(() => {
    const unsubs = [
      subscribe('task:started', handleTaskStarted),
      subscribe('task:progress', handleTaskProgress),
      subscribe('task:completed', handleTaskCompleted),
      subscribe('task:cancelled', handleTaskCancelled),
      subscribe('task:timeout', (p) => {
        // Treat timeout as failure
        const taskId = p.taskId as string;
        if (!taskId) return;
        handleTaskCompleted({
          ...p,
          success: false,
          result: `Timed out after ${(p.timeout_seconds as number) ?? '?'}s`,
        });
      }),
      subscribe('tool:executed', handleToolExecuted),
      subscribe('cli:session:started', handleCliSessionStarted),
      subscribe('cli:session:ended', handleCliSessionEnded),
      // Re-fetch snapshot on WS reconnect
      subscribe('ws:connected', () => {
        void loadSnapshot(projectIdRef.current);
      }),
    ];
    return () => unsubs.forEach((u) => u());
  }, [
    subscribe,
    loadSnapshot,
    handleTaskStarted,
    handleTaskProgress,
    handleTaskCompleted,
    handleTaskCancelled,
    handleToolExecuted,
    handleCliSessionStarted,
    handleCliSessionEnded,
  ]);

  // ── Visibility re-sync ────────────────────────────────────────────────
  useEffect(() => {
    const handler = () => {
      if (document.visibilityState === 'visible') {
        void loadSnapshot(projectIdRef.current);
        purgeExpired();
      }
    };
    document.addEventListener('visibilitychange', handler);
    return () => document.removeEventListener('visibilitychange', handler);
  }, [loadSnapshot, purgeExpired]);

  // ── Periodic TTL cleanup ──────────────────────────────────────────────
  useEffect(() => {
    const timer = setInterval(purgeExpired, 30_000);
    return () => clearInterval(timer);
  }, [purgeExpired]);
}
