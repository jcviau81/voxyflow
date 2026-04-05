import { useQuery } from '@tanstack/react-query';

export interface RawWorkerTask {
  id: string;
  session_id: string;
  project_id: string | null;
  card_id: string | null;
  action: string;
  description: string;
  model: string;
  status: string;
  result_summary: string | null;
  error: string | null;
  started_at: string | null;
  completed_at: string | null;
  created_at: string;
}

interface WorkerTasksResponse {
  tasks: RawWorkerTask[];
}

async function fetchTasksByStatus(status: string, projectId?: string): Promise<RawWorkerTask[]> {
  const params = new URLSearchParams({ limit: '20', status });
  if (projectId) params.set('project_id', projectId);
  const res = await fetch(`/api/worker-tasks?${params}`);
  if (!res.ok) return [];
  const data: WorkerTasksResponse = await res.json();
  return data.tasks ?? [];
}

export const workerTaskKeys = {
  all: ['worker-tasks'] as const,
  active: (projectId?: string) => ['worker-tasks', 'active', projectId ?? ''] as const,
};

/**
 * Polls GET /api/worker-tasks for running and pending tasks every 3 seconds.
 * Returns the merged array of raw tasks from the backend.
 */
export function useWorkerTasksQuery(projectId?: string) {
  return useQuery({
    queryKey: workerTaskKeys.active(projectId),
    queryFn: async () => {
      const [running, pending] = await Promise.all([
        fetchTasksByStatus('running', projectId),
        fetchTasksByStatus('pending', projectId),
      ]);
      // Deduplicate by id
      const seen = new Set<string>();
      const merged: RawWorkerTask[] = [];
      for (const t of [...running, ...pending]) {
        if (!seen.has(t.id)) {
          seen.add(t.id);
          merged.push(t);
        }
      }
      return merged;
    },
    refetchInterval: 3000,
    staleTime: 0,
  });
}
