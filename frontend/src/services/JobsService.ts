import { API_URL } from '../utils/constants';

export interface Job {
  id: string;
  name: string;
  type: 'reminder' | 'github_sync' | 'rag_index' | 'custom';
  schedule: string; // cron expression or "every_30min" etc.
  enabled: boolean;
  payload: Record<string, unknown>;
  last_run?: string;
  next_run?: string;
}

class JobsService {
  private baseUrl = `${API_URL}/api/jobs`;

  async getJobs(): Promise<Job[]> {
    const response = await fetch(this.baseUrl);
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    return response.json();
  }

  async createJob(job: Partial<Job>): Promise<Job> {
    const response = await fetch(this.baseUrl, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(job),
    });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    return response.json();
  }

  async updateJob(id: string, patch: Partial<Job>): Promise<Job> {
    const response = await fetch(`${this.baseUrl}/${id}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(patch),
    });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    return response.json();
  }

  async deleteJob(id: string): Promise<void> {
    const response = await fetch(`${this.baseUrl}/${id}`, { method: 'DELETE' });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
  }

  async runJob(id: string): Promise<void> {
    const response = await fetch(`${this.baseUrl}/${id}/run`, { method: 'POST' });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
  }
}

export interface ServiceHealth {
  name: string;
  status: 'ok' | 'down';
}

export interface ServicesHealthResponse {
  services: ServiceHealth[];
}

export const jobsService = new JobsService();
