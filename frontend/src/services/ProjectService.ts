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

  requestSync(): void {
    apiClient.send('project:list-request', {});
  }

  destroy(): void {
    this.unsubscribers.forEach((unsub) => unsub());
    this.unsubscribers = [];
  }
}

export const projectService = new ProjectService();
