import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';

const API = '';

async function apiFetch<T>(url: string, options?: RequestInit): Promise<T> {
  const res = await fetch(`${API}${url}`, options);
  if (!res.ok) {
    const detail = await res.json().catch(() => ({})) as { detail?: string };
    throw new Error(detail.detail ?? `HTTP ${res.status}`);
  }
  return res.json() as Promise<T>;
}

export interface ServerSession {
  chatId: string;
  title?: string;
  lastMessage: { role: string; content: string; timestamp?: string } | null;
  messageCount: number;
  updatedAt: string;
}

export interface SearchResult {
  message_id: string;
  chat_id: string;
  role: string;
  content: string;
  snippet: string;
  created_at: string | null;
}

// --- Query keys ---

export const sessionKeys = {
  all: ['sessions'] as const,
  active: (maxAgeHours?: number) => ['sessions', 'active', maxAgeHours ?? 720] as const,
  search: (query: string, projectId?: string) => ['sessions', 'search', query, projectId] as const,
};

// --- Queries ---

export function useSessions(maxAgeHours = 720) {
  return useQuery({
    queryKey: sessionKeys.active(maxAgeHours),
    queryFn: () =>
      apiFetch<ServerSession[]>(`/api/sessions?active=true&max_age_hours=${maxAgeHours}`),
    staleTime: 60_000,
  });
}

export function useSearchMessages(query: string, projectId?: string, limit = 20) {
  return useQuery({
    queryKey: sessionKeys.search(query, projectId),
    queryFn: () => {
      const params = new URLSearchParams({ q: query, limit: String(limit) });
      if (projectId) params.set('project_id', projectId);
      return apiFetch<SearchResult[]>(`/api/sessions/search/messages?${params}`);
    },
    enabled: query.length > 1,
    staleTime: 30_000,
  });
}

// --- Mutations ---

/**
 * Create a new server session and get back a stable chatId.
 */
export function useCreateSession() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async ({ projectId, title }: { projectId: string; title?: string }) => {
      return apiFetch<{ chatId: string; title: string }>('/api/sessions', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ project_id: projectId, title: title ?? null }),
      });
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: sessionKeys.all });
    },
  });
}

/**
 * Sync sessions from server — re-fetches the active sessions list.
 * Call this after WS reconnect to stay in sync across devices.
 */
export function useSyncSessions() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (maxAgeHours?: number) => {
      const age = maxAgeHours ?? 720;
      return apiFetch<ServerSession[]>(`/api/sessions?active=true&max_age_hours=${age}`);
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: sessionKeys.all });
    },
  });
}

/**
 * Delete a server session by chatId.
 */
export function useDeleteSession() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (chatId: string) => {
      await fetch(`${API}/api/sessions/${encodeURIComponent(chatId)}`, { method: 'DELETE' });
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: sessionKeys.all });
    },
  });
}
