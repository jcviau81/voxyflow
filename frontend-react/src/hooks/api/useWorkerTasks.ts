/**
 * useWorkerTasks — Types for worker task API responses.
 *
 * Polling hooks removed — worker monitoring now uses WebSocket push
 * via useWorkerStore + useWorkerSync. These types are kept for
 * any remaining REST interactions.
 */

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

export interface WorkerTasksResponse {
  tasks: RawWorkerTask[];
}
