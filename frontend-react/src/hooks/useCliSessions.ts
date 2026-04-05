import { useState, useEffect, useCallback } from 'react';

export interface CliSessionInfo {
  id: string;
  pid: number;
  sessionId: string;
  chatId: string;
  projectId: string | null;
  model: string;
  type: 'chat' | 'worker';
  startedAt: number;
  durationSeconds: number;
}

interface CliSessionsResponse {
  sessions: CliSessionInfo[];
  count: number;
}

export function useCliSessions(enabled = true, intervalMs = 5000) {
  const [sessions, setSessions] = useState<CliSessionInfo[]>([]);
  const [count, setCount] = useState(0);

  useEffect(() => {
    if (!enabled) return;

    let active = true;

    const poll = async () => {
      try {
        const res = await fetch('/api/cli-sessions/active');
        if (res.ok && active) {
          const data: CliSessionsResponse = await res.json();
          setSessions(data.sessions);
          setCount(data.count);
        }
      } catch {
        // Silently ignore fetch errors
      }
    };

    void poll();
    const id = setInterval(poll, intervalMs);
    return () => {
      active = false;
      clearInterval(id);
    };
  }, [enabled, intervalMs]);

  const kill = useCallback(async (sessionId: string) => {
    try {
      await fetch(`/api/cli-sessions/${sessionId}/close`, { method: 'POST' });
      setSessions((prev) => prev.filter((s) => s.id !== sessionId));
      setCount((prev) => Math.max(0, prev - 1));
    } catch {
      // Silently ignore
    }
  }, []);

  return { sessions, count, kill };
}
