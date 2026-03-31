import { create } from 'zustand';
import { persist } from 'zustand/middleware';
import type { Tab } from '../types';

const DEFAULT_MAIN_TAB: Tab = {
  id: 'main',
  label: 'Main',
  emoji: '🏠',
  closable: false,
  hasNotification: false,
  isActive: true,
};

export interface TabState {
  openTabs: Tab[];
  activeTab: string;

  // Open a project tab (or switch to it if already open)
  openProjectTab: (projectId: string, projectName: string, emoji?: string) => void;

  // Close a tab — cannot close 'main'; switches to adjacent tab if it was active
  closeTab: (tabId: string) => void;

  // Switch active tab and update isActive flags
  switchTab: (tabId: string) => void;

  // Set notification badge on a tab
  setTabNotification: (tabId: string, hasNotification: boolean) => void;

  // Derived helpers (stable references, fine to call in render)
  getActiveTab: () => string;
  getOpenTabs: () => Tab[];
}

export const useTabStore = create<TabState>()(
  persist(
    (set, get) => ({
      openTabs: [{ ...DEFAULT_MAIN_TAB }],
      activeTab: 'main',

      openProjectTab: (projectId, projectName, emoji) => {
        const existing = get().openTabs.find((t) => t.id === projectId);
        if (existing) {
          get().switchTab(projectId);
          return;
        }

        const tab: Tab = {
          id: projectId,
          label: projectName,
          emoji: emoji ?? '📁',
          closable: true,
          hasNotification: false,
          isActive: false,
        };

        set((state) => ({
          openTabs: [...state.openTabs, tab],
        }));
        get().switchTab(projectId);
      },

      closeTab: (tabId) => {
        if (tabId === 'main') return;

        const { openTabs, activeTab } = get();
        const wasActive = activeTab === tabId;
        const closedIndex = openTabs.findIndex((t) => t.id === tabId);
        const remaining = openTabs.filter((t) => t.id !== tabId);

        set({ openTabs: remaining });

        if (wasActive) {
          // Prefer the tab that was just before; fall back to first
          const fallbackIndex = Math.min(closedIndex, remaining.length - 1);
          const fallback = remaining[fallbackIndex] ?? remaining[0];
          if (fallback) {
            get().switchTab(fallback.id);
          } else {
            get().switchTab('main');
          }
        }
      },

      switchTab: (tabId) => {
        const { openTabs } = get();
        const tab = openTabs.find((t) => t.id === tabId);
        if (!tab) return;

        set({
          openTabs: openTabs.map((t) => ({ ...t, isActive: t.id === tabId })),
          activeTab: tabId,
        });
      },

      setTabNotification: (tabId, hasNotification) => {
        set((state) => ({
          openTabs: state.openTabs.map((t) =>
            t.id === tabId ? { ...t, hasNotification } : t
          ),
        }));
      },

      getActiveTab: () => get().activeTab,
      getOpenTabs: () => get().openTabs,
    }),
    {
      name: 'voxyflow_open_tabs',
      partialize: (state) => ({
        openTabs: state.openTabs,
        activeTab: state.activeTab,
      }),
      // Migration: ensure main tab always exists and has correct defaults
      onRehydrateStorage: () => (state) => {
        if (!state) return;
        const hasMain = state.openTabs.some((t) => t.id === 'main');
        if (!hasMain) {
          state.openTabs.unshift({ ...DEFAULT_MAIN_TAB });
        }
        // Always sync main tab emoji/label with defaults
        state.openTabs = state.openTabs.map((t) =>
          t.id === 'main'
            ? { ...t, emoji: DEFAULT_MAIN_TAB.emoji, label: DEFAULT_MAIN_TAB.label }
            : t
        );
        // Ensure activeTab is valid
        const activeValid = state.openTabs.some((t) => t.id === state.activeTab);
        if (!activeValid) {
          state.activeTab = 'main';
        }
        // Sync isActive flags
        state.openTabs = state.openTabs.map((t) => ({
          ...t,
          isActive: t.id === state.activeTab,
        }));
      },
    }
  )
);
