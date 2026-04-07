import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import type { Project, ProjectFormData, Sprint, SprintStatus } from '../../types';

const API = '';

async function apiFetch<T>(url: string, options?: RequestInit): Promise<T> {
  const res = await fetch(`${API}${url}`, options);
  if (!res.ok) {
    const detail = await res.json().catch(() => ({})) as { detail?: string };
    throw new Error(detail.detail ?? `HTTP ${res.status}`);
  }
  return res.json() as Promise<T>;
}

function mapRawProject(p: Record<string, unknown>): Project {
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
    techStack: p.tech_stack as Project['techStack'],
    githubRepo: p.github_repo as string | undefined,
    githubUrl: p.github_url as string | undefined,
    githubBranch: p.github_branch as string | undefined,
    githubLanguage: p.github_language as string | undefined,
    inheritMainContext: p.inherit_main_context !== undefined ? (p.inherit_main_context as boolean) : true,
  };
}

function mapRawSprint(s: {
  id: string; project_id: string; name: string; goal: string | null;
  start_date: string; end_date: string; status: string; created_at: string; card_count: number;
}): Sprint {
  return {
    id: s.id,
    projectId: s.project_id,
    name: s.name,
    goal: s.goal,
    startDate: s.start_date,
    endDate: s.end_date,
    status: s.status as SprintStatus,
    createdAt: s.created_at,
    cardCount: s.card_count,
  };
}

// --- Query keys ---

export const projectKeys = {
  all: ['projects'] as const,
  lists: () => ['projects', 'list'] as const,
  active: () => ['projects', 'list', 'active'] as const,
  archived: () => ['projects', 'list', 'archived'] as const,
  detail: (id: string) => ['projects', id] as const,
  templates: () => ['projects', 'templates'] as const,
  sprints: (projectId: string) => ['projects', projectId, 'sprints'] as const,
};

// --- Queries ---

export function useProjects() {
  return useQuery({
    queryKey: projectKeys.active(),
    queryFn: async () => {
      const [activeRaw, archivedRaw] = await Promise.all([
        apiFetch<Record<string, unknown>[]>('/api/projects?archived=false'),
        apiFetch<Record<string, unknown>[]>('/api/projects?archived=true').catch(() => [] as Record<string, unknown>[]),
      ]);
      const all = [
        ...activeRaw.map(mapRawProject),
        ...archivedRaw.map(mapRawProject),
      ];
      return all;
    },
    staleTime: 60_000,
  });
}

export function useProjectTemplates() {
  return useQuery({
    queryKey: projectKeys.templates(),
    queryFn: () => apiFetch<Array<{ id: string; name: string; emoji: string; description: string; color: string; cards: unknown[] }>>('/api/projects/templates'),
    staleTime: 5 * 60_000,
  });
}

export function useSprints(projectId: string) {
  return useQuery({
    queryKey: projectKeys.sprints(projectId),
    queryFn: async () => {
      const data = await apiFetch<Array<{
        id: string; project_id: string; name: string; goal: string | null;
        start_date: string; end_date: string; status: string; created_at: string; card_count: number;
      }>>(`/api/projects/${projectId}/sprints`);
      return data.map(mapRawSprint);
    },
    staleTime: 30_000,
    enabled: !!projectId,
  });
}

// --- Mutations ---

export function useCreateProject() {
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
      const raw = await apiFetch<Record<string, unknown>>('/api/projects', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      });
      return mapRawProject(raw);
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: projectKeys.lists() });
    },
  });
}

export function useUpdateProject() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async ({ id, updates }: { id: string; updates: Partial<ProjectFormData & Project> }) => {
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

      const raw = await apiFetch<Record<string, unknown>>(`/api/projects/${id}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      });
      return mapRawProject(raw);
    },
    onSuccess: (_data, { id }) => {
      qc.invalidateQueries({ queryKey: projectKeys.detail(id) });
      qc.invalidateQueries({ queryKey: projectKeys.lists() });
    },
  });
}

export function useDeleteProject() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (id: string) => {
      await fetch(`${API}/api/projects/${id}`, { method: 'DELETE' });
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: projectKeys.lists() });
    },
  });
}

export function useArchiveProject() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async ({ id, restore = false }: { id: string; restore?: boolean }) => {
      await apiFetch(`/api/projects/${id}/${restore ? 'restore' : 'archive'}`, { method: 'POST' });
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: projectKeys.lists() });
    },
  });
}

export function useToggleFavorite() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (projectId: string) => {
      const data = await apiFetch<{ is_favorite: boolean }>(`/api/projects/${projectId}/favorite`, { method: 'PATCH' });
      return data.is_favorite;
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: projectKeys.lists() });
    },
  });
}

export function useExportProject() {
  return useMutation({
    mutationFn: (projectId: string) => apiFetch<unknown>(`/api/projects/${projectId}/export`),
  });
}

export function useImportProject() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: unknown) =>
      apiFetch<{ project_id: string; project_title: string; cards_imported: number }>('/api/projects/import', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(data),
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: projectKeys.lists() });
    },
  });
}

export function useCreateProjectFromTemplate() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async ({ templateId, data }: {
      templateId: string;
      data: { title: string; description?: string; emoji?: string; color?: string };
    }) => {
      return apiFetch<{ project_id: string; project_title: string; cards_imported: number; template_emoji: string; template_color: string }>(
        `/api/projects/from-template/${templateId}`,
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(data),
        }
      );
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: projectKeys.lists() });
    },
  });
}

export function useExecuteBoardPlan() {
  return useMutation({
    mutationFn: (projectId: string) =>
      apiFetch<{ executionId: string; cards: Array<{ id: string; title: string; status: string; position: number }>; total: number }>(
        `/api/projects/${projectId}/boards/execute`,
        { method: 'POST' }
      ),
  });
}

// --- Sprint mutations ---

export function useCreateSprint() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async ({ projectId, data }: {
      projectId: string;
      data: { name: string; goal?: string; start_date: string; end_date: string };
    }) => {
      const s = await apiFetch<{
        id: string; project_id: string; name: string; goal: string | null;
        start_date: string; end_date: string; status: string; created_at: string; card_count: number;
      }>(`/api/projects/${projectId}/sprints`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(data),
      });
      return mapRawSprint(s);
    },
    onSuccess: (_data, { projectId }) => {
      qc.invalidateQueries({ queryKey: projectKeys.sprints(projectId) });
    },
  });
}

export function useUpdateSprint() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async ({ projectId, sprintId, data }: {
      projectId: string;
      sprintId: string;
      data: { name?: string; goal?: string; start_date?: string; end_date?: string };
    }) => {
      const s = await apiFetch<{
        id: string; project_id: string; name: string; goal: string | null;
        start_date: string; end_date: string; status: string; created_at: string; card_count: number;
      }>(`/api/projects/${projectId}/sprints/${sprintId}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(data),
      });
      return mapRawSprint(s);
    },
    onSuccess: (_data, { projectId }) => {
      qc.invalidateQueries({ queryKey: projectKeys.sprints(projectId) });
    },
  });
}

export function useDeleteSprint() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async ({ projectId, sprintId }: { projectId: string; sprintId: string }) => {
      await fetch(`${API}/api/projects/${projectId}/sprints/${sprintId}`, { method: 'DELETE' });
    },
    onSuccess: (_data, { projectId }) => {
      qc.invalidateQueries({ queryKey: projectKeys.sprints(projectId) });
    },
  });
}

export function useSprintAction() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async ({ projectId, sprintId, action }: { projectId: string; sprintId: string; action: 'start' | 'complete' }) => {
      const s = await apiFetch<{
        id: string; project_id: string; name: string; goal: string | null;
        start_date: string; end_date: string; status: string; created_at: string; card_count: number;
      }>(`/api/projects/${projectId}/sprints/${sprintId}/${action}`, { method: 'POST' });
      return mapRawSprint(s);
    },
    onSuccess: (_data, { projectId }) => {
      qc.invalidateQueries({ queryKey: projectKeys.sprints(projectId) });
    },
  });
}
