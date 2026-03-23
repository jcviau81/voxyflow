import { Project } from '../types';
import { appState } from '../state/AppState';
import { eventBus } from '../utils/EventBus';
import { EVENTS, SYSTEM_PROJECT_ID } from '../utils/constants';

const API_URL_BASE = process.env.VOXYFLOW_API_URL || '';

/**
 * ProjectService — uses REST API (fetch) for all CRUD operations.
 * Projects are persisted in the backend database.
 */
export class ProjectService {

  /**
   * Load all projects from backend and populate AppState.
   * Called on app init.
   */
  async requestSync(): Promise<void> {
    try {
      const [activeResp, archivedResp] = await Promise.all([
        fetch(`${API_URL_BASE}/api/projects?archived=false`),
        fetch(`${API_URL_BASE}/api/projects?archived=true`),
      ]);
      if (!activeResp.ok) return;
      const activeRaw = await activeResp.json();
      const archivedRaw = archivedResp.ok ? await archivedResp.json() : [];
      const active: Project[] = Array.isArray(activeRaw)
        ? activeRaw.map((p: Record<string, unknown>) => this.mapRawProject(p))
        : [];
      const archived: Project[] = Array.isArray(archivedRaw)
        ? archivedRaw.map((p: Record<string, unknown>) => this.mapRawProject(p))
        : [];
      const allProjects = [...active, ...archived];
      // Ensure system project is always first
      const sysIdx = allProjects.findIndex(p => p.id === SYSTEM_PROJECT_ID);
      if (sysIdx > 0) {
        const [sysProject] = allProjects.splice(sysIdx, 1);
        allProjects.unshift(sysProject);
      }
      if (allProjects.length > 0) {
        appState.set('projects', allProjects);
        eventBus.emit(EVENTS.PROJECT_SELECTED);
      }
    } catch (e) {
      console.error('[ProjectService] Failed to sync projects from backend:', e);
    }
  }

  /**
   * Create a project via REST API.
   * Returns the created project with server-generated ID.
   */
  async create(name: string, description: string = ''): Promise<Project> {
    try {
      const resp = await fetch(`${API_URL_BASE}/api/projects`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ title: name, description }),
      });
      if (resp.ok) {
        const raw = await resp.json();
        const project = this.mapRawProject(raw);
        // Add to AppState and emit PROJECT_CREATED for listeners
        const projects = [...appState.get('projects'), project];
        appState.set('projects', projects);
        eventBus.emit(EVENTS.PROJECT_CREATED, project);
        return project;
      }
    } catch (e) {
      console.error('[ProjectService] REST create failed:', e);
    }
    // Fallback: create locally (won't persist but at least UI works)
    const project = appState.addProject(name, description);
    return project;
  }

  /**
   * Update a project via REST API.
   * Maps frontend field names to backend snake_case names.
   */
  async update(id: string, updates: Partial<Project>): Promise<void> {
    // Map frontend camelCase → backend snake_case
    const body: Record<string, unknown> = {};
    if (updates.name !== undefined) body.title = updates.name;
    if (updates.description !== undefined) body.description = updates.description;
    if (updates.localPath !== undefined) body.local_path = updates.localPath;
    if (updates.githubRepo !== undefined) body.github_repo = updates.githubRepo;
    if (updates.githubUrl !== undefined) body.github_url = updates.githubUrl;
    if (updates.githubBranch !== undefined) body.github_branch = updates.githubBranch;
    if (updates.githubLanguage !== undefined) body.github_language = updates.githubLanguage;
    if (updates.inheritMainContext !== undefined) body.inherit_main_context = updates.inheritMainContext;
    // Note: emoji and color are frontend-only (not in backend schema)
    // They are stored in AppState but not sent to the backend

    // Update AppState immediately for responsive UI
    appState.updateProject(id, updates);

    if (Object.keys(body).length === 0) return;

    try {
      const resp = await fetch(`${API_URL_BASE}/api/projects/${id}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      });
      if (resp.ok) {
        const raw = await resp.json();
        const project = this.mapRawProject(raw);
        appState.updateProject(id, project);
      } else {
        console.error('[ProjectService] PATCH failed:', resp.status, await resp.text());
      }
    } catch (e) {
      console.error('[ProjectService] REST update failed:', e);
    }
  }

  /**
   * Delete a project via REST API.
   */
  async delete(id: string): Promise<void> {
    appState.deleteProject(id);
    try {
      const resp = await fetch(`${API_URL_BASE}/api/projects/${id}`, { method: 'DELETE' });
      if (!resp.ok && resp.status !== 204) {
        console.error('[ProjectService] DELETE failed:', resp.status);
      }
    } catch (e) {
      console.error('[ProjectService] REST delete failed:', e);
    }
  }

  list(): Project[] {
    return appState.get('projects').filter((p) => !p.archived);
  }

  listArchived(): Project[] {
    return appState.get('projects').filter((p) => p.archived);
  }

  get(id: string): Project | undefined {
    return appState.getProject(id);
  }

  async archive(id: string): Promise<void> {
    try {
      const resp = await fetch(`${API_URL_BASE}/api/projects/${id}/archive`, { method: 'POST' });
      if (resp.ok) {
        appState.updateProject(id, { archived: true });
        eventBus.emit(EVENTS.PROJECT_UPDATED, { id });
      }
    } catch (e) {
      console.error('[ProjectService] Archive failed:', e);
    }
  }

  async unarchive(id: string): Promise<void> {
    try {
      const resp = await fetch(`${API_URL_BASE}/api/projects/${id}/restore`, { method: 'POST' });
      if (resp.ok) {
        appState.updateProject(id, { archived: false });
        eventBus.emit(EVENTS.PROJECT_UPDATED, { id });
      }
    } catch (e) {
      console.error('[ProjectService] Restore failed:', e);
    }
  }

  select(id: string | null): void {
    appState.selectProject(id);
  }

  /**
   * Map backend snake_case response to frontend Project type.
   */
  private mapRawProject(p: Record<string, unknown>): Project {
    return {
      id: p.id as string,
      name: (p.name || p.title || 'Untitled') as string,
      description: (p.description || '') as string,
      emoji: p.emoji as string | undefined,
      color: p.color as string | undefined,
      localPath: p.local_path as string | undefined,
      createdAt: p.created_at ? new Date(p.created_at as string).getTime() : Date.now(),
      updatedAt: p.updated_at ? new Date(p.updated_at as string).getTime() : Date.now(),
      cards: (p.cards as string[]) || [],
      archived: p.status === 'archived' || (p.archived as boolean) || false,
      techStack: p.tech_stack as import('../types').TechDetectResult | undefined,
      githubRepo: p.github_repo as string | undefined,
      githubUrl: p.github_url as string | undefined,
      githubBranch: p.github_branch as string | undefined,
      githubLanguage: p.github_language as string | undefined,
      inheritMainContext: p.inherit_main_context !== undefined ? (p.inherit_main_context as boolean) : true,
    };
  }

  destroy(): void {
    // No-op — no WS subscriptions to clean up
  }
}

export const projectService = new ProjectService();
