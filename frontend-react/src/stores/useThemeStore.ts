/**
 * useThemeStore — theme (dark/light) + accent color.
 *
 * Mirrors the theme logic from AppState.setTheme().
 * Persists to localStorage and syncs the data-theme attribute on <html>.
 */

import { create } from 'zustand';
import { persist } from 'zustand/middleware';

export type Theme = 'dark' | 'light';

export type AccentColor =
  | 'blue'
  | 'purple'
  | 'green'
  | 'orange'
  | 'pink'
  | 'red'
  | 'yellow'
  | 'teal';

export interface ThemeState {
  theme: Theme;
  accentColor: AccentColor;

  setTheme: (theme: Theme) => void;
  toggleTheme: () => void;
  setAccentColor: (color: AccentColor) => void;
}

function applyTheme(theme: Theme): void {
  document.documentElement.setAttribute('data-theme', theme);
}

export const useThemeStore = create<ThemeState>()(
  persist(
    (set, get) => ({
      theme: 'dark',
      accentColor: 'blue',

      setTheme: (theme) => {
        applyTheme(theme);
        set({ theme });
      },

      toggleTheme: () => {
        const next: Theme = get().theme === 'dark' ? 'light' : 'dark';
        applyTheme(next);
        set({ theme: next });
      },

      setAccentColor: (accentColor) => {
        document.documentElement.setAttribute('data-accent', accentColor);
        set({ accentColor });
      },
    }),
    {
      name: 'voxyflow_theme',
      partialize: (state) => ({ theme: state.theme, accentColor: state.accentColor }),
      onRehydrateStorage: () => (state) => {
        // Apply persisted theme to <html> on page load
        if (state) {
          applyTheme(state.theme);
          document.documentElement.setAttribute('data-accent', state.accentColor);
        }
      },
    }
  )
);
