/**
 * useThemeStore — full appearance state.
 *
 * Mirrors ThemeService.ts + AppState.setTheme() from the vanilla frontend.
 * Persists to localStorage and applies CSS variables / class names to <html>.
 */

import { create } from 'zustand';
import { persist } from 'zustand/middleware';
import {
  type FontSize,
  type SidebarWidth,
  type CardDensity,
  type AnimationSpeed,
  DEFAULT_ACCENT,
  applyAccentColor,
  applyFontSize,
  applySidebarWidth,
  applyCardDensity,
  applyAnimationSpeed,
} from '../lib/themeConstants';

export type { FontSize, SidebarWidth, CardDensity, AnimationSpeed };

export type Theme = 'dark' | 'light';

/** Hex string — e.g. '#ff6b6b'. Use ACCENT_PRESETS for the picker. */
export type AccentColor = string;

export interface ThemeState {
  theme: Theme;
  /** Hex string matching one of ACCENT_PRESETS (or custom). */
  accentColor: AccentColor;
  fontSize: FontSize;
  sidebarWidth: SidebarWidth;
  cardDensity: CardDensity;
  animationSpeed: AnimationSpeed;

  setTheme: (theme: Theme) => void;
  toggleTheme: () => void;
  setAccentColor: (hex: string) => void;
  setFontSize: (size: FontSize) => void;
  setSidebarWidth: (width: SidebarWidth) => void;
  setCardDensity: (density: CardDensity) => void;
  setAnimationSpeed: (speed: AnimationSpeed) => void;
}

function applyTheme(theme: Theme): void {
  const root = document.documentElement;
  root.setAttribute('data-theme', theme);
  root.classList.toggle('dark', theme === 'dark');
}

export const useThemeStore = create<ThemeState>()(
  persist(
    (set, get) => ({
      theme: 'dark',
      accentColor: DEFAULT_ACCENT,
      fontSize: 'medium' as FontSize,
      sidebarWidth: 'normal' as SidebarWidth,
      cardDensity: 'comfortable' as CardDensity,
      animationSpeed: 'normal' as AnimationSpeed,

      setTheme: (theme) => {
        applyTheme(theme);
        set({ theme });
      },

      toggleTheme: () => {
        const next: Theme = get().theme === 'dark' ? 'light' : 'dark';
        applyTheme(next);
        set({ theme: next });
      },

      setAccentColor: (hex) => {
        applyAccentColor(hex);
        set({ accentColor: hex });
      },

      setFontSize: (fontSize) => {
        applyFontSize(fontSize);
        set({ fontSize });
      },

      setSidebarWidth: (sidebarWidth) => {
        applySidebarWidth(sidebarWidth);
        set({ sidebarWidth });
      },

      setCardDensity: (cardDensity) => {
        applyCardDensity(cardDensity);
        set({ cardDensity });
      },

      setAnimationSpeed: (animationSpeed) => {
        applyAnimationSpeed(animationSpeed);
        set({ animationSpeed });
      },
    }),
    {
      name: 'voxyflow_theme',
      partialize: (state) => ({
        theme: state.theme,
        accentColor: state.accentColor,
        fontSize: state.fontSize,
        sidebarWidth: state.sidebarWidth,
        cardDensity: state.cardDensity,
        animationSpeed: state.animationSpeed,
      }),
      onRehydrateStorage: () => (state) => {
        if (!state) return;
        applyTheme(state.theme);
        applyAccentColor(state.accentColor ?? DEFAULT_ACCENT);
        applyFontSize(state.fontSize ?? 'medium');
        applySidebarWidth(state.sidebarWidth ?? 'normal');
        applyCardDensity(state.cardDensity ?? 'comfortable');
        applyAnimationSpeed(state.animationSpeed ?? 'normal');
      },
    }
  )
);
