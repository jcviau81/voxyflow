import { create } from 'zustand';
import { persist } from 'zustand/middleware';
import type { Workspace } from '../types';
import { generateId } from '../lib/utils';

export interface WorkspaceState {
  workspaces: Workspace[];
  currentWorkspaceId: string | null;
  selectedCardId: string | null;

  // CRUD
  addWorkspace: (data: { name: string; description?: string; emoji?: string; color?: string; localPath?: string; githubRepo?: string; githubUrl?: string; githubBranch?: string; githubLanguage?: string; inheritMainContext?: boolean }) => Workspace;
  updateWorkspace: (id: string, updates: Partial<Workspace>) => void;
  deleteWorkspace: (id: string, onCardCleanup?: (workspaceId: string) => void) => void;
  setWorkspaces: (workspaces: Workspace[]) => void;
  upsertWorkspace: (workspace: Workspace) => void;

  // Selection
  selectWorkspace: (workspaceId: string | null) => void;
  selectCard: (cardId: string | null) => void;

  // Queries
  getWorkspace: (id: string) => Workspace | undefined;
  getActiveWorkspace: () => Workspace | undefined;
  getArchivedWorkspaces: () => Workspace[];
  getActiveWorkspaces: () => Workspace[];
  getFavoriteWorkspaces: () => Workspace[];
}

export const useWorkspaceStore = create<WorkspaceState>()(
  persist(
    (set, get) => ({
      workspaces: [],
      currentWorkspaceId: null,
      selectedCardId: null,

      addWorkspace: (data) => {
        const workspace: Workspace = {
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
        set((state) => ({ workspaces: [...state.workspaces, workspace] }));
        return workspace;
      },

      updateWorkspace: (id, updates) => {
        set((state) => ({
          workspaces: state.workspaces.map((p) =>
            p.id === id ? { ...p, ...updates, updatedAt: Date.now() } : p
          ),
        }));
      },

      deleteWorkspace: (id, onCardCleanup) => {
        onCardCleanup?.(id);
        set((state) => ({
          workspaces: state.workspaces.filter((p) => p.id !== id),
          currentWorkspaceId: state.currentWorkspaceId === id ? null : state.currentWorkspaceId,
        }));
      },

      setWorkspaces: (workspaces) => set({ workspaces }),

      upsertWorkspace: (workspace) => {
        set((state) => {
          const exists = state.workspaces.some((p) => p.id === workspace.id);
          if (exists) {
            return {
              workspaces: state.workspaces.map((p) =>
                p.id === workspace.id ? { ...p, ...workspace } : p
              ),
            };
          }
          return { workspaces: [...state.workspaces, workspace] };
        });
      },

      selectWorkspace: (workspaceId) => {
        set({ currentWorkspaceId: workspaceId, selectedCardId: null });
      },

      selectCard: (cardId) => {
        set({ selectedCardId: cardId });
      },

      getWorkspace: (id) => get().workspaces.find((p) => p.id === id),

      getActiveWorkspace: () => {
        const { workspaces, currentWorkspaceId } = get();
        return workspaces.find((p) => p.id === currentWorkspaceId);
      },

      getArchivedWorkspaces: () => get().workspaces.filter((p) => p.archived),

      getActiveWorkspaces: () => get().workspaces.filter((p) => !p.archived),

      getFavoriteWorkspaces: () => get().workspaces.filter((p) => p.isFavorite && !p.archived),
    }),
    {
      name: 'voxyflow_workspaces',
      partialize: (state) => ({
        workspaces: state.workspaces,
        // currentWorkspaceId is derived from URL (synced by AppShell) — not persisted
        selectedCardId: state.selectedCardId,
      }),
    }
  )
);
