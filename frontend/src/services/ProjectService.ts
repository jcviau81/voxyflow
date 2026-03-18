import { Project } from '../types';
import { appState } from '../state/AppState';
import { apiClient } from './ApiClient';
import { eventBus } from '../utils/EventBus';
import { EVENTS } from '../utils/constants';

export class ProjectService {
  private unsubscribers: (() => void)[] = [];

  constructor() {
    this.setupHandlers();
  }

  private setupHandlers(): void {
    // Sync project updates from backend
    this.unsubscribers.push(
      apiClient.on('project:sync', (payload) => {
        const { action, project } = payload as { action: string; project: Project };
        switch (action) {
          case 'created':
            if (!appState.getProject(project.id)) {
              const projects = [...appState.get('projects'), project];
              appState.set('projects', projects);
            }
            break;
          case 'updated':
            appState.updateProject(project.id, project);
            break;
          case 'deleted':
            appState.deleteProject(project.id);
            break;
        }
      })
    );

    // Handle bulk sync (initial load)
    this.unsubscribers.push(
      apiClient.on('project:list', (payload) => {
        const { projects } = payload as { projects: Project[] };
        appState.set('projects', projects);
      })
    );
  }

  create(name: string, description: string = ''): Project {
    const project = appState.addProject(name, description);
    apiClient.send('project:create', {
      id: project.id,
      name: project.name,
      description: project.description,
    });
    return project;
  }

  update(id: string, updates: Partial<Project>): void {
    appState.updateProject(id, updates);
    apiClient.send('project:update', { id, updates });
  }

  delete(id: string): void {
    appState.deleteProject(id);
    apiClient.send('project:delete', { id });
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

  archive(id: string): void {
    this.update(id, { archived: true });
  }

  unarchive(id: string): void {
    this.update(id, { archived: false });
  }

  select(id: string | null): void {
    appState.selectProject(id);
  }

  async requestSync(): Promise<void> {
    try {
      const response = await fetch('/api/projects');
      if (!response.ok) return;
      const raw = await response.json();
      const projects: Project[] = Array.isArray(raw) ? raw.map((p: Record<string, unknown>) => ({
        id: p.id as string,
        name: (p.name || p.title || 'Untitled') as string,
        description: (p.description || '') as string,
        emoji: p.emoji as string | undefined,
        color: p.color as string | undefined,
        localPath: p.local_path as string | undefined,
        createdAt: p.created_at ? new Date(p.created_at as string).getTime() : Date.now(),
        updatedAt: p.updated_at ? new Date(p.updated_at as string).getTime() : Date.now(),
        cards: (p.cards as string[]) || [],
        archived: (p.archived as boolean) || false,
        techStack: p.tech_stack as import('../types').TechDetectResult | undefined,
        githubRepo: p.github_repo as string | undefined,
        githubUrl: p.github_url as string | undefined,
        githubBranch: p.github_branch as string | undefined,
        githubLanguage: p.github_language as string | undefined,
      })) : [];
      if (projects.length > 0) {
        appState.set('projects', projects);
        eventBus.emit(EVENTS.PROJECT_SELECTED); // trigger sidebar re-render (not PROJECT_CREATED — that expects a project payload)
      }
    } catch (e) {
      // fallback: try WS
      apiClient.send('project:list-request', {});
    }
  }

  destroy(): void {
    this.unsubscribers.forEach((unsub) => unsub());
    this.unsubscribers = [];
  }
}

export const projectService = new ProjectService();
