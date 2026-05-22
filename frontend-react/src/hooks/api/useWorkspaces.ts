import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import type { Workspace, WorkspaceFormData } from '../../types';

const API = '';

async function apiFetch<T>(url: string, options?: RequestInit): Promise<T> {
  const res = await fetch(`${API}${url}`, options);
  if (!res.ok) {
    const detail = await res.json().catch(() => ({})) as { detail?: string };
    throw new Error(detail.detail ?? `HTTP ${res.status}`);
  }
  return res.json() as Promise<T>;
}

function mapRawWorkspace(p: Record<string, unknown>): Workspace {
  return {
    id: p.id as string,
    name: ((p.name ?? p.title) ?? 'Untitled') as string,
    description: (p.description ?? '') as string,
    emoji: p.emoji as string | undefined,
    color: p.color as string | undefined,
    localPath: p.local_path as string | undefined,
    createdAt: p.created_at ? new Date(p.created_at as string).getTime() : Date.now(),
    updatedAt: p.updated_at ? new Date(p.updated_at as string).getTime() : Date.now(),
    cards: (p.cards as string[]) ?? [],
    archived: p.status === 'archived' || (p.archived as boolean) || false,
    isSystem: (p.is_system as boolean) ?? false,
    deletable: p.deletable !== undefined ? (p.deletable as boolean) : true,
    isFavorite: (p.is_favorite as boolean) ?? false,
    techStack: p.tech_stack as Workspace['techStack'],
    githubRepo: p.github_repo as string | undefined,
    githubUrl: p.github_url as string | undefined,
    githubBranch: p.github_branch as string | undefined,
    githubLanguage: p.github_language as string | undefined,
    inheritMainContext: p.inherit_main_context !== undefined ? (p.inherit_main_context as boolean) : true,
  };
}


// --- Query keys ---

export const workspaceKeys = {
  all: ['workspaces'] as const,
  lists: () => ['workspaces', 'list'] as const,
  active: () => ['workspaces', 'list', 'active'] as const,
  archived: () => ['workspaces', 'list', 'archived'] as const,
  detail: (id: string) => ['workspaces', id] as const,
  templates: () => ['workspaces', 'templates'] as const,

};

// --- Queries ---

export function useWorkspaces() {
  return useQuery({
    queryKey: workspaceKeys.active(),
    queryFn: async () => {
      const [activeRaw, archivedRaw] = await Promise.all([
        apiFetch<Record<string, unknown>[]>('/api/workspaces?archived=false'),
        apiFetch<Record<string, unknown>[]>('/api/workspaces?archived=true').catch(() => [] as Record<string, unknown>[]),
      ]);
      const all = [
        ...activeRaw.map(mapRawWorkspace),
        ...archivedRaw.map(mapRawWorkspace),
      ];
      return all;
    },
    staleTime: 60_000,
  });
}

export function useWorkspaceTemplates() {
  return useQuery({
    queryKey: workspaceKeys.templates(),
    queryFn: () => apiFetch<Array<{ id: string; name: string; emoji: string; description: string; color: string; cards: unknown[] }>>('/api/workspaces/templates'),
    staleTime: 5 * 60_000,
  });
}


// --- Mutations ---

export function useCreateWorkspace() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (data: {
      name: string;
      description?: string;
      localPath?: string;
      githubRepo?: string;
      githubUrl?: string;
      githubBranch?: string;
      githubLanguage?: string;
    }) => {
      const body: Record<string, unknown> = {
        title: data.name,
        description: data.description ?? '',
      };
      if (data.localPath) body.local_path = data.localPath;
      if (data.githubRepo) body.github_repo = data.githubRepo;
      if (data.githubUrl) body.github_url = data.githubUrl;
      if (data.githubBranch) body.github_branch = data.githubBranch;
      if (data.githubLanguage) body.github_language = data.githubLanguage;
      const raw = await apiFetch<Record<string, unknown>>('/api/workspaces', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      });
      return mapRawWorkspace(raw);
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: workspaceKeys.lists() });
    },
  });
}

export function useUpdateWorkspace() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async ({ id, updates }: { id: string; updates: Partial<WorkspaceFormData & Workspace> }) => {
      const body: Record<string, unknown> = {};
      if (updates.name !== undefined) body.title = updates.name;
      if (updates.title !== undefined) body.title = updates.title;
      if (updates.description !== undefined) body.description = updates.description;
      if (updates.localPath !== undefined) body.local_path = updates.localPath;
      if (updates.githubRepo !== undefined) body.github_repo = updates.githubRepo;
      if (updates.githubUrl !== undefined) body.github_url = updates.githubUrl;
      if (updates.githubBranch !== undefined) body.github_branch = updates.githubBranch;
      if (updates.githubLanguage !== undefined) body.github_language = updates.githubLanguage;
      if (updates.inheritMainContext !== undefined) body.inherit_main_context = updates.inheritMainContext;

      const raw = await apiFetch<Record<string, unknown>>(`/api/workspaces/${id}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      });
      return mapRawWorkspace(raw);
    },
    onSuccess: (_data, { id }) => {
      qc.invalidateQueries({ queryKey: workspaceKeys.detail(id) });
      qc.invalidateQueries({ queryKey: workspaceKeys.lists() });
    },
  });
}

export function useDeleteWorkspace() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (id: string) => {
      await fetch(`${API}/api/workspaces/${id}`, { method: 'DELETE' });
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: workspaceKeys.lists() });
    },
  });
}

export function useArchiveWorkspace() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async ({ id, restore = false }: { id: string; restore?: boolean }) => {
      await apiFetch(`/api/workspaces/${id}/${restore ? 'restore' : 'archive'}`, { method: 'POST' });
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: workspaceKeys.lists() });
    },
  });
}

export function useToggleFavorite() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (workspaceId: string) => {
      const data = await apiFetch<{ is_favorite: boolean }>(`/api/workspaces/${workspaceId}/favorite`, { method: 'PATCH' });
      return data.is_favorite;
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: workspaceKeys.lists() });
    },
  });
}

export function useExportWorkspace() {
  return useMutation({
    mutationFn: (workspaceId: string) => apiFetch<unknown>(`/api/workspaces/${workspaceId}/export`),
  });
}

export function useImportWorkspace() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: unknown) =>
      apiFetch<{ workspace_id: string; workspace_title: string; cards_imported: number }>('/api/workspaces/import', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(data),
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: workspaceKeys.lists() });
    },
  });
}

export function useCreateWorkspaceFromTemplate() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async ({ templateId, data }: {
      templateId: string;
      data: { title: string; description?: string; emoji?: string; color?: string };
    }) => {
      return apiFetch<{ workspace_id: string; workspace_title: string; cards_imported: number; template_emoji: string; template_color: string }>(
        `/api/workspaces/from-template/${templateId}`,
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(data),
        }
      );
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: workspaceKeys.lists() });
    },
  });
}

export function useExecuteBoardPlan() {
  return useMutation({
    mutationFn: (workspaceId: string) =>
      apiFetch<{ executionId: string; cards: Array<{ id: string; title: string; status: string; position: number }>; total: number }>(
        `/api/workspaces/${workspaceId}/boards/execute`,
        { method: 'POST' }
      ),
  });
}

