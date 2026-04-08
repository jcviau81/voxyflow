import { create } from 'zustand';
import { persist } from 'zustand/middleware';
import type { Project } from '../types';
import { generateId } from '../lib/utils';

export interface ProjectState {
  projects: Project[];
  currentProjectId: string | null;
  selectedCardId: string | null;

  // CRUD
  addProject: (data: { name: string; description?: string; emoji?: string; color?: string; localPath?: string; githubRepo?: string; githubUrl?: string; githubBranch?: string; githubLanguage?: string; inheritMainContext?: boolean }) => Project;
  updateProject: (id: string, updates: Partial<Project>) => void;
  deleteProject: (id: string, onCardCleanup?: (projectId: string) => void) => void;
  setProjects: (projects: Project[]) => void;
  upsertProject: (project: Project) => void;

  // Selection
  selectProject: (projectId: string | null) => void;
  selectCard: (cardId: string | null) => void;

  // Queries
  getProject: (id: string) => Project | undefined;
  getActiveProject: () => Project | undefined;
  getArchivedProjects: () => Project[];
  getActiveProjects: () => Project[];
  getFavoriteProjects: () => Project[];
}

export const useProjectStore = create<ProjectState>()(
  persist(
    (set, get) => ({
      projects: [],
      currentProjectId: null,
      selectedCardId: null,

      addProject: (data) => {
        const project: Project = {
          id: generateId(),
          name: data.name,
          description: data.description ?? '',
          emoji: data.emoji,
          color: data.color,
          localPath: data.localPath,
          githubRepo: data.githubRepo,
          githubUrl: data.githubUrl,
          githubBranch: data.githubBranch,
          githubLanguage: data.githubLanguage,
          inheritMainContext: data.inheritMainContext ?? true,
          createdAt: Date.now(),
          updatedAt: Date.now(),
          cards: [],
          archived: false,
        };
        set((state) => ({ projects: [...state.projects, project] }));
        return project;
      },

      updateProject: (id, updates) => {
        set((state) => ({
          projects: state.projects.map((p) =>
            p.id === id ? { ...p, ...updates, updatedAt: Date.now() } : p
          ),
        }));
      },

      deleteProject: (id, onCardCleanup) => {
        onCardCleanup?.(id);
        set((state) => ({
          projects: state.projects.filter((p) => p.id !== id),
          currentProjectId: state.currentProjectId === id ? null : state.currentProjectId,
        }));
      },

      setProjects: (projects) => set({ projects }),

      upsertProject: (project) => {
        set((state) => {
          const exists = state.projects.some((p) => p.id === project.id);
          if (exists) {
            return {
              projects: state.projects.map((p) =>
                p.id === project.id ? { ...p, ...project } : p
              ),
            };
          }
          return { projects: [...state.projects, project] };
        });
      },

      selectProject: (projectId) => {
        set({ currentProjectId: projectId, selectedCardId: null });
      },

      selectCard: (cardId) => {
        set({ selectedCardId: cardId });
      },

      getProject: (id) => get().projects.find((p) => p.id === id),

      getActiveProject: () => {
        const { projects, currentProjectId } = get();
        return projects.find((p) => p.id === currentProjectId);
      },

      getArchivedProjects: () => get().projects.filter((p) => p.archived),

      getActiveProjects: () => get().projects.filter((p) => !p.archived),

      getFavoriteProjects: () => get().projects.filter((p) => p.isFavorite && !p.archived),
    }),
    {
      name: 'voxyflow_projects',
      partialize: (state) => ({
        projects: state.projects,
        // currentProjectId is derived from URL (synced by AppShell) — not persisted
        selectedCardId: state.selectedCardId,
      }),
    }
  )
);
