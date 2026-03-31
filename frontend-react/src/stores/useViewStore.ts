import { create } from 'zustand';
import { persist } from 'zustand/middleware';
import type { ViewMode } from '../types';

interface ViewState {
  currentView: ViewMode;
  setView: (view: ViewMode) => void;
}

export const useViewStore = create<ViewState>()(
  persist(
    (set) => ({
      currentView: 'chat',
      setView: (view) => set({ currentView: view }),
    }),
    {
      name: 'voxyflow_view',
    }
  )
);
