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
  status: (workspaceId: string) => ['workspace-autonomy', workspaceId] as const,
};

export function useWorkspaceAutonomy(workspaceId: string | undefined) {
  return useQuery({
    queryKey: workspaceId ? autonomyKeys.status(workspaceId) : ['workspace-autonomy', 'none'],
    queryFn: () => apiFetch<AutonomyStatus>(`/api/workspaces/${workspaceId}/autonomy`),
    enabled: !!workspaceId,
    staleTime: 10_000,
  });
}

export function useUpsertWorkspaceAutonomy() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async ({
      workspaceId,
      enabled,
      schedule,
      directive,
    }: {
      workspaceId: string;
      enabled: boolean;
      schedule?: string;
      directive?: string;
    }) => {
      const body: Record<string, unknown> = { enabled };
      if (schedule !== undefined) body.schedule = schedule;
      if (directive !== undefined) body.directive = directive;
      return apiFetch<AutonomyStatus & { job?: unknown }>(
        `/api/workspaces/${workspaceId}/autonomy`,
        {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(body),
        },
      );
    },
    onSuccess: (_d, { workspaceId }) => {
      qc.invalidateQueries({ queryKey: autonomyKeys.status(workspaceId) });
    },
  });
}

export function useDisableWorkspaceAutonomy() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (workspaceId: string) =>
      apiFetch<void>(`/api/workspaces/${workspaceId}/autonomy`, { method: 'DELETE' }),
    onSuccess: (_d, workspaceId) => {
      qc.invalidateQueries({ queryKey: autonomyKeys.status(workspaceId) });
    },
  });
}

export function useRunWorkspaceAutonomyNow() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (workspaceId: string) =>
      apiFetch<{ workspace_id: string; result: { status: string; message?: string } }>(
        `/api/workspaces/${workspaceId}/autonomy/run`,
        { method: 'POST' },
      ),
    onSuccess: (_d, workspaceId) => {
      qc.invalidateQueries({ queryKey: autonomyKeys.status(workspaceId) });
    },
  });
}
