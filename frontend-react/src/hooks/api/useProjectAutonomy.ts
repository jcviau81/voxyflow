import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

export interface AutonomyStatus {
  enabled: boolean;
  schedule: string;
  next_run: string | null;
  directive: string;
  file_path: string;
  actionable: boolean;
  job_exists: boolean;
}

const API = '';

async function apiFetch<T>(url: string, options?: RequestInit): Promise<T> {
  const res = await fetch(`${API}${url}`, options);
  if (res.status === 204) return undefined as unknown as T;
  if (!res.ok) {
    const detail = (await res.json().catch(() => ({}))) as { detail?: string };
    throw new Error(detail.detail ?? `HTTP ${res.status}`);
  }
  return res.json() as Promise<T>;
}

export const autonomyKeys = {
  status: (projectId: string) => ['project-autonomy', projectId] as const,
};

export function useProjectAutonomy(projectId: string | undefined) {
  return useQuery({
    queryKey: projectId ? autonomyKeys.status(projectId) : ['project-autonomy', 'none'],
    queryFn: () => apiFetch<AutonomyStatus>(`/api/projects/${projectId}/autonomy`),
    enabled: !!projectId,
    staleTime: 10_000,
  });
}

export function useUpsertProjectAutonomy() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async ({
      projectId,
      enabled,
      schedule,
      directive,
    }: {
      projectId: string;
      enabled: boolean;
      schedule?: string;
      directive?: string;
    }) => {
      const body: Record<string, unknown> = { enabled };
      if (schedule !== undefined) body.schedule = schedule;
      if (directive !== undefined) body.directive = directive;
      return apiFetch<AutonomyStatus & { job?: unknown }>(
        `/api/projects/${projectId}/autonomy`,
        {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(body),
        },
      );
    },
    onSuccess: (_d, { projectId }) => {
      qc.invalidateQueries({ queryKey: autonomyKeys.status(projectId) });
    },
  });
}

export function useDisableProjectAutonomy() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (projectId: string) =>
      apiFetch<void>(`/api/projects/${projectId}/autonomy`, { method: 'DELETE' }),
    onSuccess: (_d, projectId) => {
      qc.invalidateQueries({ queryKey: autonomyKeys.status(projectId) });
    },
  });
}

export function useRunProjectAutonomyNow() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (projectId: string) =>
      apiFetch<{ project_id: string; result: { status: string; message?: string } }>(
        `/api/projects/${projectId}/autonomy/run`,
        { method: 'POST' },
      ),
    onSuccess: (_d, projectId) => {
      qc.invalidateQueries({ queryKey: autonomyKeys.status(projectId) });
    },
  });
}
