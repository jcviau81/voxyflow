import { useState, useEffect, useCallback } from 'react';

interface WorkerSession {
  task_id: string;
  session_id: string;
  project_id?: string;
  card_id?: string;
  status: string;
  model?: string;
  intent?: string;
  summary?: string;
  start_time?: number;
  end_time?: number;
  result_summary?: string;
}

/**
 * useWorkerStatus — polls the worker sessions API every 3 seconds
 * and provides an `isCardActive` function to check if a specific card
 * has an active (running/pending) worker session.
 */
export function useWorkerStatus(projectId: string) {
  const [sessions, setSessions] = useState<WorkerSession[]>([]);

  useEffect(() => {
    if (!projectId) return;

    const poll = async () => {
      try {
        const res = await fetch(`/api/workers/sessions?project_id=${encodeURIComponent(projectId)}`);
        if (res.ok) {
          const data = await res.json();
          // API returns { sessions: [...] }
          setSessions(data.sessions ?? []);
        }
      } catch {
        // Ignore network errors during polling
      }
    };

    poll();
    const interval = setInterval(poll, 3000);
    return () => clearInterval(interval);
  }, [projectId]);

  const isCardActive = useCallback(
    (cardId: string): boolean => {
      return sessions.some(
        (s) =>
          s.card_id === cardId &&
          (s.status === 'running' || s.status === 'pending'),
      );
    },
    [sessions],
  );

  return { isCardActive, sessions };
}
